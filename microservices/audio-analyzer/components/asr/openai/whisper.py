from components.asr.base_asr import BaseASR
import whisper
import logging
from utils.config_loader import config
from utils.ensure_model import get_asr_model_path
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

WHISPER_MODEL_MAP = {
    "whisper-tiny": "tiny",
    "whisper-base": "base",
    "whisper-small": "small",
    "whisper-medium": "medium",
    "whisper-large": "large-v3",
}


class Whisper(BaseASR):
    """
    Robust Whisper ASR with silence-safe filtering.
    Prevents hallucinations without dropping real speech.
    """

    def __init__(self, model_name="whisper-small", device="cpu", revision=None):
        if model_name not in WHISPER_MODEL_MAP:
            raise ValueError(f"Invalid ASR model name: {model_name}")

        self.model_name = model_name
        model_id = WHISPER_MODEL_MAP[model_name]
        logger.info(f"Loading Whisper model={model_id} on device={device}")

        # Load from the models volume so the file persisted by ensure_model()
        # is used.  This prevents openai-whisper from attempting an outbound
        # download at container startup when the network is unavailable.
        download_root = get_asr_model_path()
        self.model = whisper.load_model(model_id, device=device, download_root=download_root)

        # ---- Conservative thresholds (DO NOT overtune) ----
        self.NO_SPEECH_THRESHOLD = config.models.asr.no_speech_threshold
        self.LOGPROB_THRESHOLD = config.models.asr.logprob_threshold
        self.MIN_DURATION_SEC = config.models.asr.min_duration_sec
        self.MIN_WORDS = config.models.asr.min_words
        self.BEAM_SIZE = max(1, int(getattr(config.models.asr, "beam_size", 5) or 1))
        self.BEST_OF = max(1, int(getattr(config.models.asr, "best_of", 1) or 1))
        # openai-whisper's DecodingOptions has no repetition_penalty field —
        # passing it as a kwarg raises TypeError.  Applied as post-processing.
        self.REPETITION_PENALTY = getattr(config.models.asr, "repetition_penalty", 1.0)
        # When enabled, transcribe() passes whisper a temperature *schedule*
        # instead of a single scalar, restoring openai-whisper's built-in
        # decode-and-retry mechanism: it retries at the next, higher
        # temperature only when compression_ratio/logprob checks judge the
        # previous attempt low-confidence. Previously a single float was
        # passed (effectively always temperature=0.0/greedy with no retry),
        # which silently disabled this robustness mechanism.
        self.TEMPERATURE_FALLBACK = bool(getattr(config.models.asr, "temperature_fallback", True))
        # Caps how many escalating-temperature retries whisper.transcribe()
        # may make (the built-in ladder is 6 steps: 0.0, 0.2, ... 1.0). On
        # genuinely short/choppy live-mic audio, letting it run the full
        # ladder was observed to cost up to ~6x the normal decode latency
        # (2.5s -> 17.5s for a single kiosk turn) while still producing a
        # wrong transcript at the end — the later, higher-temperature
        # attempts sample more randomly and are not more likely to recover
        # the correct words on audio that is short/ambiguous by nature, they
        # just cost more time. Capping bounds the worst case while still
        # allowing one retry for the genuinely-recoverable "one bad decode"
        # case. Default of 2 matches the (0.0, 0.2) prefix of the original
        # ladder; set higher to trade latency back for more retry attempts,
        # or equal to 6 to restore the original unbounded behaviour.
        self.TEMPERATURE_FALLBACK_MAX_RETRIES = max(
            1, int(getattr(config.models.asr, "temperature_fallback_max_retries", 2) or 2)
        )
        # Native whisper param: skip generation over silent regions > N seconds.
        # null/None disables it.
        _hst = getattr(config.models.asr, "hallucination_silence_threshold", None)
        self.HALLUCINATION_SILENCE_THRESHOLD = float(_hst) if _hst is not None else None
        # Word-level timestamps. Required by diarization to split a whisper
        # segment that spans two speakers at the acoustic turn boundary.
        self.WORD_TIMESTAMPS = bool(getattr(config.models.asr, "word_timestamps", False))

    def _is_silent_segment(self, seg: Dict[str, Any]) -> bool:
        """
        Decide whether a segment is silence / hallucination.
        Uses MULTIPLE signals to avoid dropping real speech.
        """

        text = seg.get("text", "").strip()
        duration = float(seg["end"]) - float(seg["start"])
        no_speech_prob = seg.get("no_speech_prob", 0.0)
        avg_logprob = seg.get("avg_logprob", 0.0)

        # 1. Must be acoustically silence-like
        if no_speech_prob <= self.NO_SPEECH_THRESHOLD:
            return False

        # 2. Must be low confidence
        if avg_logprob >= self.LOGPROB_THRESHOLD:
            return False

        # 3. Must be very short or nearly empty
        if duration >= self.MIN_DURATION_SEC and len(text.split()) >= self.MIN_WORDS:
            return False

        return True

    def _remove_repeated_phrases(self, text: str) -> str:
        """
        Remove consecutive repeated word sequences (window 1-8 words).
        Only active when repetition_penalty > 1.0.
        """
        if not text or self.REPETITION_PENALTY <= 1.0:
            return text

        words = text.split()
        if len(words) < 2:
            return text

        result: List[str] = []
        i = 0
        while i < len(words):
            found = False
            max_window = min(8, (len(words) - i) // 2)
            for w in range(max_window, 0, -1):
                if words[i : i + w] == words[i + w : i + 2 * w]:
                    result.extend(words[i : i + w])
                    i += 2 * w
                    found = True
                    break
            if not found:
                result.append(words[i])
                i += 1
        return " ".join(result)

    def clean_text(self, text: str) -> str:
        """Public hook so diarization-split sub-segments get repetition filtering.

        Args:
            text: text rebuilt from word-level timings.

        Returns:
            Text with consecutive repeated word sequences removed.
        """
        return self._remove_repeated_phrases(text)

    def _deduplicate_segments(self, segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Drop segments whose text is identical to the immediately preceding
        segment (common whisper loop artifact). Only active when
        repetition_penalty > 1.0.
        """
        if self.REPETITION_PENALTY <= 1.0:
            return segments

        deduped: List[Dict[str, Any]] = []
        prev_text: str | None = None
        for seg in segments:
            text = seg["text"].strip().lower()
            if text != prev_text:
                deduped.append(seg)
                prev_text = text
        return deduped

    def _temperature_schedule(self, base_temperature: float):
        """Build the temperature argument passed to whisper's transcribe().

        When TEMPERATURE_FALLBACK is enabled, returns a tuple starting at
        `base_temperature` and stepping by 0.2, capped at
        `TEMPERATURE_FALLBACK_MAX_RETRIES` steps (openai-whisper's own
        default retry ladder runs the full 6 steps to 1.0). whisper.transcribe()
        tries each temperature in order and only advances to the next one
        when the compression_ratio/logprob checks judge the current attempt
        low-confidence, so well-recognized audio still decodes once at
        `base_temperature` with no extra cost — the cap only bounds the
        worst case for genuinely low-confidence audio, where the full ladder
        was observed to cost up to 6x normal latency without producing a
        better transcript.

        When disabled, returns `base_temperature` unchanged (single decode,
        previous behaviour) — useful for reproducible output or benchmarking.
        """
        if not self.TEMPERATURE_FALLBACK:
            return base_temperature

        start = base_temperature if base_temperature is not None else 0.0
        schedule = []
        t = round(start, 2)
        while t <= 1.0 + 1e-6 and len(schedule) < self.TEMPERATURE_FALLBACK_MAX_RETRIES:
            schedule.append(round(t, 2))
            t += 0.2
        return tuple(schedule) if schedule else (start,)

    def transcribe(self, audio_path: str, temperature: float = 0.0, language: str | None = None) -> Dict[str, Any]:
        """
        Transcribe audio with strong silence suppression and zero speech loss.
        """

        # no_speech_threshold and logprob_threshold are passed to whisper's
        # internal segment filter AND re-checked in _is_silent_segment() below.
        # Both layers read from the same config values so the behaviour is
        # consistent; the double-pass only affects segments whisper would have
        # kept but our stricter multi-signal check rejects.
        result = self.model.transcribe(
            audio_path,
            temperature=self._temperature_schedule(temperature),
            language=language,
            condition_on_previous_text=False,
            no_speech_threshold=self.NO_SPEECH_THRESHOLD,
            logprob_threshold=self.LOGPROB_THRESHOLD,

            # Repetition control (decoder level)
            beam_size=self.BEAM_SIZE,
            best_of=self.BEST_OF,

            # Hallucination guard
            compression_ratio_threshold=2.4,

            # Skip generation over silent regions (mic noise fix)
            hallucination_silence_threshold=self.HALLUCINATION_SILENCE_THRESHOLD,

            # Per-word timings (used by diarization to split mixed-speaker segments)
            word_timestamps=self.WORD_TIMESTAMPS,

            verbose=False,
        )

        kept_segments: List[Dict[str, Any]] = []
        dropped = 0

        for seg in result.get("segments", []):
            if self._is_silent_segment(seg):
                dropped += 1
                logger.debug(
                    "openai-whisper: dropped segment [%.2fs-%.2fs] no_speech_prob=%.3f "
                    "avg_logprob=%.3f text=%r",
                    float(seg.get("start", 0.0)), float(seg.get("end", 0.0)),
                    seg.get("no_speech_prob", 0.0), seg.get("avg_logprob", 0.0),
                    seg.get("text", "").strip()[:80],
                )
                continue

            logger.debug(
                "openai-whisper: kept segment [%.2fs-%.2fs] no_speech_prob=%.3f "
                "avg_logprob=%.3f compression_ratio=%.3f",
                float(seg.get("start", 0.0)), float(seg.get("end", 0.0)),
                seg.get("no_speech_prob", 0.0), seg.get("avg_logprob", 0.0),
                seg.get("compression_ratio", 0.0),
            )

            kept_segments.append({
                "start": float(seg["start"]),
                "end": float(seg["end"]),
                "text": seg["text"].strip(),
                "avg_logprob": seg.get("avg_logprob"),
                "compression_ratio": seg.get("compression_ratio"),
                "no_speech_prob": seg.get("no_speech_prob"),
                "words": [
                    {
                        "word": w.get("word", ""),
                        "start": float(w.get("start", seg["start"])),
                        "end": float(w.get("end", seg["end"])),
                    }
                    for w in (seg.get("words") or [])
                ],
            })

        # Post-processing repetition removal (repetition_penalty > 1.0)
        kept_segments = self._deduplicate_segments(kept_segments)
        for seg in kept_segments:
            seg["text"] = self._remove_repeated_phrases(seg["text"])

        final_text = " ".join(s["text"] for s in kept_segments).strip()
        final_text = self._remove_repeated_phrases(final_text)

        logger.info(
            "openai-whisper transcribe summary: model=%s segments_total=%d kept=%d dropped=%d "
            "language=%s",
            self.model_name, len(result.get("segments", [])), len(kept_segments), dropped,
            result.get("language"),
        )

        return {
            "text": final_text,
            "segments": kept_segments,
            "language": result.get("language"),
            "meta": {
                "model": self.model_name,
                "temperature": temperature,
                "segments_total": len(result.get("segments", [])),
                "segments_kept": len(kept_segments),
                "segments_dropped": dropped,
            },
        }
