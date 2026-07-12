import sys


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


def main() -> None:
    if "--crypto-self-test" in sys.argv:
        raise SystemExit(crypto_self_test())
    from kerberus.main import main as app_main

    app_main()


if __name__ == "__main__":
    main()
