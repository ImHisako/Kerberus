import base64
import struct
import unittest

from kerberus.voice import (
    VOICE_CODEC,
    VOICE_MAX_SAMPLES,
    VOICE_SAMPLE_RATE,
    pcm_to_wav,
    test_tone_wav,
    validate_voice_payload,
)


def encoded_voice(sample_count: int = 16_000) -> bytes:
    header = (
        b"KVA1"
        + struct.pack(">IIhBB", VOICE_SAMPLE_RATE, sample_count, 0, 0, 0)
    )
    return header + bytes((sample_count - 1 + 1) // 2)


class VoicePayloadTests(unittest.TestCase):
    def test_valid_container_is_normalized(self):
        encoded = encoded_voice()
        voice = validate_voice_payload({
            "codec": VOICE_CODEC,
            "duration_ms": 1000,
            "data": base64.b64encode(encoded).decode("ascii"),
        })
        self.assertEqual(voice["sample_rate"], 16_000)
        self.assertEqual(voice["sample_count"], 16_000)
        self.assertEqual(voice["duration_ms"], 1000)

    def test_malformed_and_oversized_voice_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_voice_payload({"codec": VOICE_CODEC, "data": "not base64!"})
        with self.assertRaises(ValueError):
            validate_voice_payload({
                "codec": VOICE_CODEC,
                "data": base64.b64encode(encoded_voice(VOICE_MAX_SAMPLES) + b"x").decode("ascii"),
            })

    def test_pcm_to_wav_has_bounded_riff_container(self):
        wav = pcm_to_wav(bytes(32_000))
        self.assertEqual(wav[:4], b"RIFF")
        self.assertEqual(wav[8:12], b"WAVE")
        self.assertEqual(len(wav), 32_044)

    def test_output_device_test_tone_is_a_playable_wav(self):
        wav = test_tone_wav(800)
        self.assertEqual(wav[:4], b"RIFF")
        self.assertEqual(wav[8:12], b"WAVE")
        self.assertEqual(len(wav), 25_644)


if __name__ == "__main__":
    unittest.main()
