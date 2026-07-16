from __future__ import annotations

import base64
import io
import math
import struct
import subprocess
import time
import wave
from pathlib import Path
from typing import Any

from .sam import _hidden_startupinfo, _native_helper_path


VOICE_CODEC = "kerberus-ima-adpcm-v1"
VOICE_SAMPLE_RATE = 16_000
VOICE_MAX_SECONDS = 120
VOICE_MAX_SAMPLES = VOICE_SAMPLE_RATE * VOICE_MAX_SECONDS
VOICE_HEADER_SIZE = 16
VOICE_MAX_ENCODED_BYTES = VOICE_HEADER_SIZE + VOICE_MAX_SAMPLES // 2
_SAMPLE_FORMATS = {"u8", "s16le", "s32le", "f32le"}


def _parse_container(encoded: bytes) -> tuple[int, int]:
    if len(encoded) < VOICE_HEADER_SIZE or encoded[:4] != b"KVA1":
        raise ValueError("Contenitore del messaggio vocale non valido")
    sample_rate, sample_count = struct.unpack(">II", encoded[4:12])
    expected = VOICE_HEADER_SIZE + (max(0, sample_count - 1) + 1) // 2
    if (
        sample_rate != VOICE_SAMPLE_RATE
        or not 1 <= sample_count <= VOICE_MAX_SAMPLES
        or len(encoded) != expected
        or encoded[14] > 88
        or encoded[15] != 0
    ):
        raise ValueError("Formato del messaggio vocale non valido")
    return sample_rate, sample_count


def validate_voice_payload(value: object) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("codec") != VOICE_CODEC:
        raise ValueError("Codec del messaggio vocale non supportato")
    data = value.get("data")
    if not isinstance(data, str) or len(data) > (VOICE_MAX_ENCODED_BYTES * 4 // 3 + 8):
        raise ValueError("Messaggio vocale troppo grande")
    try:
        encoded = base64.b64decode(data, validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError("Dati del messaggio vocale non validi") from exc
    sample_rate, sample_count = _parse_container(encoded)
    duration_ms = round(sample_count * 1000 / sample_rate)
    supplied_duration = value.get("duration_ms")
    if supplied_duration is not None and supplied_duration != duration_ms:
        raise ValueError("Durata del messaggio vocale non valida")
    return {
        "codec": VOICE_CODEC,
        "sample_rate": sample_rate,
        "sample_count": sample_count,
        "duration_ms": duration_ms,
        "data": data,
    }


class NativeVoiceCodec:
    """Encode and decode voice data in the bundled dependency-free Go helper."""

    def __init__(self, executable: Path | None = None):
        self.executable = executable or _native_helper_path()

    def _run(self, arguments: list[str], payload: bytes, timeout: float = 30) -> bytes:
        if self.executable is None or not self.executable.is_file():
            raise RuntimeError(
                "Codec vocale Go non disponibile. Nelle build sorgente esegui prima build_release.py."
            )
        try:
            result = subprocess.run(
                [str(self.executable), *arguments],
                input=payload,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                startupinfo=_hidden_startupinfo(),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError("Il codec vocale Go non ha risposto") from exc
        if result.returncode != 0:
            raise ValueError(f"Elaborazione vocale rifiutata dal codec Go ({result.returncode})")
        return result.stdout

    def encode(
        self,
        pcm: bytes,
        *,
        sample_rate: int,
        channels: int,
        sample_format: str,
    ) -> tuple[dict[str, Any], dict[str, float | int | str]]:
        if sample_format not in _SAMPLE_FORMATS:
            raise ValueError("Formato del microfono non supportato")
        started = time.perf_counter_ns()
        encoded = self._run([
            "--voice-encode",
            "--sample-rate", str(sample_rate),
            "--channels", str(channels),
            "--sample-format", sample_format,
        ], pcm)
        elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
        sample_rate, sample_count = _parse_container(encoded)
        voice = validate_voice_payload({
            "codec": VOICE_CODEC,
            "duration_ms": round(sample_count * 1000 / sample_rate),
            "data": base64.b64encode(encoded).decode("ascii"),
        })
        return voice, {
            "backend": "go-native-ima-adpcm",
            "encode_ms": round(elapsed_ms, 3),
            "pcm_bytes": len(pcm),
            "encoded_bytes": len(encoded),
        }

    def decode(self, voice: object) -> tuple[bytes, dict[str, float | int | str]]:
        normalized = validate_voice_payload(voice)
        encoded = base64.b64decode(normalized["data"], validate=True)
        started = time.perf_counter_ns()
        pcm = self._run(["--voice-decode"], encoded)
        elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
        expected = int(normalized["sample_count"]) * 2
        if len(pcm) != expected:
            raise ValueError("Il codec Go ha prodotto audio di dimensione non valida")
        return pcm, {
            "backend": "go-native-ima-adpcm",
            "decode_ms": round(elapsed_ms, 3),
            "pcm_bytes": len(pcm),
            "encoded_bytes": len(encoded),
        }


def pcm_to_wav(pcm: bytes, sample_rate: int = VOICE_SAMPLE_RATE) -> bytes:
    if len(pcm) % 2 or len(pcm) > VOICE_MAX_SAMPLES * 2:
        raise ValueError("PCM vocale non valido")
    output = io.BytesIO()
    with wave.open(output, "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(sample_rate)
        target.writeframes(pcm)
    return output.getvalue()


def test_tone_wav(duration_ms: int = 800, frequency_hz: float = 523.25) -> bytes:
    """Create a quiet deterministic tone for testing the selected output device."""
    if not 100 <= duration_ms <= 5_000 or not 100 <= frequency_hz <= 2_000:
        raise ValueError("Parametri del tono di test non validi")
    sample_count = round(VOICE_SAMPLE_RATE * duration_ms / 1000)
    amplitude = 7_000
    pcm = bytearray(sample_count * 2)
    for index in range(sample_count):
        # Short fades avoid a click at the start and end of the test.
        fade = min(1.0, index / 320, (sample_count - index - 1) / 320)
        sample = round(amplitude * fade * math.sin(2 * math.pi * frequency_hz * index / VOICE_SAMPLE_RATE))
        struct.pack_into("<h", pcm, index * 2, sample)
    return pcm_to_wav(bytes(pcm))
