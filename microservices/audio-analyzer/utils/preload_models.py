import logging
import os
import struct
import tempfile
import time
import wave
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError

from components.asr_component import ASRComponent
from utils.config_loader import config

logger = logging.getLogger(__name__)

# Hard ceiling on warmup inference time. A silent clip normally finishes in
# well under a second (the VAD skip path), but this exists as a safety net —
# a warmup must never be able to block container startup indefinitely if a
# future change to Whisper's decode/retry behaviour reintroduces a stall. The
# transcription thread is left to finish in the background; only the startup
# path stops waiting for it.
_WARMUP_TIMEOUT_SEC = 15.0

# 1.5s of TRUE digital silence (amplitude 0), 16kHz mono PCM16.
#
# This must be genuine silence, not a barely-audible tone. An earlier version
# of this warmup used amplitude=1 to "look like a real signal" and it backfired
# badly: whisper's no_speech_threshold correctly refuses to skip ambiguous
# near-silent audio, so TEMPERATURE_FALLBACK (see openai/whisper.py) retried
# the decode across its full temperature schedule, hallucinating at each step
# — one measured run took 66.7s. That is not just a warmup bug: it means any
# real customer utterance that is quiet or ambiguous (background noise, a
# trailing-off sentence) can hit the exact same 60+ second stall in
# production. True silence lets Whisper's VAD skip generation immediately
# (the fast path every real leading/trailing silent chunk also takes), so the
# warmup only pays for encoder-forward-pass thread/kernel setup, not a decode.
_WARMUP_SAMPLE_RATE = 16000
_WARMUP_DURATION_SEC = 1.5


def _write_warmup_wav(path: str) -> None:
    n_samples = int(_WARMUP_SAMPLE_RATE * _WARMUP_DURATION_SEC)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(_WARMUP_SAMPLE_RATE)
        w.writeframes(struct.pack("<h", 0) * n_samples)


def preload_models():
    """Load ASR/diarization weights AND pay their first-inference cost.

    Constructing ``ASRComponent`` alone only loads model *weights* into
    memory. It does not run anything through them, so PyTorch/whisper's
    first-call kernel warmup (thread pool sizing, MKL-DNN op selection) and
    pyannote's first-inference buffer allocation were still being paid by
    the kiosk's very first real customer utterance — the single worst
    moment to add ~0.7-1s of latency. Measured directly: a fresh container's
    first ``/v1/audio/transcriptions`` call took ~3.3s versus ~2.4-2.6s on
    every call after it, for the identical audio.

    This runs one real (silent) transcription — and diarization, when
    enabled — through the loaded models during startup instead, so that cost
    lands before the health check reports ready rather than on a customer.
    Failures here are logged and swallowed: a missed warmup must never block
    the service from starting.
    """
    asr = ASRComponent(
        session_id="startup",
        provider=config.models.asr.provider,
        model_name=config.models.asr.name,
        device=config.models.asr.device,
    )

    warmup_path = os.path.join(tempfile.gettempdir(), "asr_warmup.wav")
    try:
        _write_warmup_wav(warmup_path)

        t0 = time.monotonic()
        # Not a context manager on purpose: `with` calls shutdown(wait=True)
        # on exit, which would block startup until the thread finishes even
        # after we give up waiting on it below. A leaked worker thread that
        # finishes late and logs its own completion is an acceptable trade
        # for startup never being able to hang.
        pool = ThreadPoolExecutor(max_workers=1)
        future = pool.submit(
            asr.asr.transcribe, warmup_path, temperature=0.0, language=None
        )
        try:
            future.result(timeout=_WARMUP_TIMEOUT_SEC)
        except FutureTimeoutError:
            logger.warning(
                "[STARTUP] ASR warmup exceeded %.0fs — continuing startup "
                "without waiting for it (weights are loaded; only the "
                "first-call speed bonus is lost)",
                _WARMUP_TIMEOUT_SEC,
            )
            pool.shutdown(wait=False)
            raise
        pool.shutdown(wait=False)
        logger.info(
            "[STARTUP] ASR warmup transcription completed in %.0fms",
            (time.monotonic() - t0) * 1000,
        )

        if asr.enable_diarization and asr.pyannote_diarizer is not None:
            t0 = time.monotonic()
            asr.pyannote_diarizer.diarize(warmup_path, session_id="startup-warmup")
            logger.info(
                "[STARTUP] Diarizer warmup completed in %.0fms",
                (time.monotonic() - t0) * 1000,
            )
    except FutureTimeoutError:
        pass
    except Exception as exc:
        logger.warning(
            "[STARTUP] ASR/diarizer warmup inference failed (non-fatal, "
            "weights are still loaded — only the first-call speed bonus is "
            "lost): %s",
            exc,
        )
    finally:
        try:
            os.remove(warmup_path)
        except OSError:
            pass
