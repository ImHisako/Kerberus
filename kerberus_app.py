import sys


def release_self_test(expected_version: str) -> int:
    """Verify that the frozen app contains the intended release and core modules."""
    try:
        from kerberus import __version__
        from kerberus.service import MessengerService
        from kerberus.ui import KerberusWindow

        _ = (MessengerService, KerberusWindow)
        return 0 if __version__ == expected_version else 4
    except Exception:
        return 5


def crypto_self_test() -> int:
    from kerberus.crypto import generate_identity, open_message, pq_unavailable_reason, seal_message

    try:
        alice, alice_secrets = generate_identity("self-test-alice", "alice-destination")
        bob, bob_secrets = generate_identity("self-test-bob", "bob-destination")
        envelope = seal_message(alice, alice_secrets, bob, "kerberus-crypto-self-test")
        return 0 if open_message(bob, bob_secrets, alice, envelope) == "kerberus-crypto-self-test" else 3
    except Exception:
        # Windowed release builds have no console; the exit code is consumed by
        # build_release.py. Source runs may inspect the import reason explicitly.
        _ = pq_unavailable_reason()
        return 2


def voice_self_test() -> int:
    try:
        from kerberus.voice import NativeVoiceCodec

        pcm = bytes(3_200)
        codec = NativeVoiceCodec()
        voice, _encode_metrics = codec.encode(
            pcm, sample_rate=16_000, channels=1, sample_format="s16le"
        )
        decoded, _decode_metrics = codec.decode(voice)
        return 0 if len(decoded) == len(pcm) else 7
    except Exception:
        return 6


def main() -> None:
    if "--release-self-test" in sys.argv:
        index = sys.argv.index("--release-self-test")
        expected = sys.argv[index + 1] if index + 1 < len(sys.argv) else ""
        raise SystemExit(release_self_test(expected))
    if "--crypto-self-test" in sys.argv:
        raise SystemExit(crypto_self_test())
    if "--voice-self-test" in sys.argv:
        raise SystemExit(voice_self_test())
    from kerberus.main import main as app_main

    app_main()


if __name__ == "__main__":
    main()
