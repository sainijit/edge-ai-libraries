import logging
import os
import urllib.request

logger = logging.getLogger(__name__)

_RELEASE_BASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
_MODEL_FILENAME = "kokoro-v1.0.onnx"
_VOICES_FILENAME = "voices-v1.0.bin"

_REQUIRED_FILES = [_MODEL_FILENAME, _VOICES_FILENAME]


def model_exists(output_dir: str) -> bool:
    return all(os.path.exists(os.path.join(output_dir, f)) for f in _REQUIRED_FILES)


def _download(url: str, dest_path: str) -> None:
    logger.info("Downloading Kokoro asset %s -> %s", url, dest_path)
    tmp_path = f"{dest_path}.part"
    try:
        urllib.request.urlretrieve(url, tmp_path)  # noqa: S310 - fixed, trusted release URL
        os.replace(tmp_path, dest_path)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def ensure(output_dir: str) -> None:
    """Download the Kokoro-82M ONNX weights + voice pack if not already cached.

    Same two release assets the kiosk-voice-lab prototype uses (MIT package,
    Apache-2.0 model weights) — kokoro-v1.0.onnx (~330MB) and
    voices-v1.0.bin (~27MB), fetched once and cached under models/kokoro/.
    """
    if model_exists(output_dir):
        logger.info("Using cached Kokoro model at %s", output_dir)
        return

    os.makedirs(output_dir, exist_ok=True)
    model_path = os.path.join(output_dir, _MODEL_FILENAME)
    voices_path = os.path.join(output_dir, _VOICES_FILENAME)

    if not os.path.exists(model_path):
        _download(f"{_RELEASE_BASE}/{_MODEL_FILENAME}", model_path)
    if not os.path.exists(voices_path):
        _download(f"{_RELEASE_BASE}/{_VOICES_FILENAME}", voices_path)


def model_path(output_dir: str) -> str:
    return os.path.join(output_dir, _MODEL_FILENAME)


def voices_path(output_dir: str) -> str:
    return os.path.join(output_dir, _VOICES_FILENAME)
