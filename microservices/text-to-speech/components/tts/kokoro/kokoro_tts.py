import logging
import threading

import numpy as np

from components.tts.base import BaseTTSService, TTSServiceConfig, model_name_matches, normalize_model_name
from components.tts.text_normalizer import normalize_for_speech
from utils.ensure_model import ensure_model, get_tts_model_path
from utils.ensure_kokoro import model_path, voices_path


logger = logging.getLogger(__name__)


IMPLEMENTATION_NAME = "kokoro"

# American-English voice packs bundled in voices-v1.0.bin. Not exhaustive of
# every language Kokoro ships, but this service is English-only for now (see
# default_language enforcement in dto/speech_dto.py and base.py).
SUPPORTED_VOICES = [
    "af_heart", "af_alloy", "af_aoede", "af_bella", "af_jessica", "af_kore",
    "af_nicole", "af_nova", "af_river", "af_sarah", "af_sky",
    "am_adam", "am_echo", "am_eric", "am_fenrir", "am_liam", "am_michael",
    "am_onyx", "am_puck", "am_santa",
    "bf_alice", "bf_emma", "bf_isabella", "bf_lily",
    "bm_daniel", "bm_fable", "bm_george", "bm_lewis",
]

# Uncapped, kokoro-onnx's CPU threads fight the LLM/ASR for cores on the same
# box. 4 matches the kiosk-voice-lab prototype's measured-good value.
_INTRA_OP_THREADS = 4


def normalize_model_name_(model_name: str) -> str:
    return normalize_model_name(model_name)


def matches_model_name(model_name: str) -> bool:
    return model_name_matches(normalize_model_name(model_name), "kokoro")


def is_supported_voice(voice: str) -> bool:
    return voice in SUPPORTED_VOICES


class KokoroTTSService(BaseTTSService):
    _models = {}
    _lock = threading.Lock()
    _default_sample_rate = 24000

    def __init__(self, config: TTSServiceConfig):
        super().__init__(config)
        model_key = self._get_model_key(IMPLEMENTATION_NAME)
        with KokoroTTSService._lock:
            if model_key not in KokoroTTSService._models:
                try:
                    from kokoro_onnx import Kokoro
                except ImportError as exc:
                    raise RuntimeError(
                        "kokoro-onnx is not installed. Install requirements.txt before starting the service."
                    ) from exc

                ensure_model()
                output_dir = get_tts_model_path()
                onnx_path = model_path(output_dir)
                bin_path = voices_path(output_dir)

                try:
                    import onnxruntime as ort

                    session_options = ort.SessionOptions()
                    session_options.intra_op_num_threads = _INTRA_OP_THREADS
                    session = ort.InferenceSession(onnx_path, session_options)
                    kokoro = Kokoro.from_session(session, bin_path)
                except Exception:
                    logger.exception(
                        "[KOKORO] Failed to build a thread-capped onnxruntime session; "
                        "falling back to the library default (uncapped)."
                    )
                    kokoro = Kokoro(onnx_path, bin_path)

                KokoroTTSService._models[model_key] = kokoro

        self.model = KokoroTTSService._models[model_key]
        self._inference_lock = self._get_inference_lock(IMPLEMENTATION_NAME)
        self.sample_rate = self._default_sample_rate

    def synthesize(
        self,
        text: str,
        language: str | None = None,
        speaker: str | None = None,
        instructions: str | None = None,
    ) -> dict:
        normalized_text = self._validate_text(text)
        spoken_text = normalize_for_speech(normalized_text)
        if not spoken_text:
            raise ValueError("Input text contains no pronounceable characters")
        if spoken_text != normalized_text:
            logger.debug(
                "[KOKORO] Normalised text for synthesis: %r -> %r",
                normalized_text, spoken_text,
            )
        chosen_language, chosen_speaker = self._resolve_voice_request(language, speaker)

        if instructions:
            raise ValueError("Kokoro does not support free-form voice instructions.")
        if chosen_speaker not in SUPPORTED_VOICES:
            raise ValueError(
                f"Unsupported voice '{chosen_speaker}'. Supported voices: {', '.join(SUPPORTED_VOICES)}."
            )

        with self._inference_lock:
            audio, sample_rate = self.model.create(spoken_text, voice=chosen_speaker, speed=1.0)

        return self._build_result(
            np.asarray(audio, dtype=np.float32), sample_rate, chosen_speaker, chosen_language, instructions
        )

    def get_model_info(self) -> dict:
        info = self._build_model_info(IMPLEMENTATION_NAME, self.model)
        info["supported_languages"] = [self.config.default_language]
        info["supported_speakers"] = SUPPORTED_VOICES
        return info


def create_service(config: TTSServiceConfig):
    return KokoroTTSService(config)
