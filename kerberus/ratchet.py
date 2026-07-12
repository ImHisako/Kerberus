from __future__ import annotations

import hashlib
import hmac
import os
import time
import copy
from typing import Any

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from nacl.bindings import crypto_aead_xchacha20poly1305_ietf_decrypt, crypto_aead_xchacha20poly1305_ietf_encrypt

from .crypto import IdentityBundle, IdentitySecrets, b64, canonical, unb64


MAX_SKIP = 256


class RatchetError(ValueError):
    pass


def _hkdf(secret: bytes, salt: bytes, info: bytes, length: int = 32) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=length, salt=salt, info=info).derive(secret)


def _initial_state(identity: IdentityBundle, secrets: IdentitySecrets, peer: IdentityBundle) -> dict[str, Any]:
    private = X25519PrivateKey.from_private_bytes(unb64(secrets.exchange_private))
    shared = private.exchange(X25519PublicKey.from_public_bytes(unb64(peer.exchange_public)))
    pair = ":".join(sorted((identity.identity_id, peer.identity_id))).encode("ascii")
    root = _hkdf(shared, hashlib.sha256(pair).digest(), b"kerberus-double-ratchet-v3-root")

    def directional(sender: str, recipient: str) -> str:
        info = f"kerberus-dr-v3-chain:{sender}:{recipient}".encode("ascii")
        return b64(_hkdf(root, hashlib.sha256(pair).digest(), info))

    return {
        "version": 3,
        "root": b64(root),
        "dh_self_private": secrets.exchange_private,
        "dh_self_public": identity.exchange_public,
        "dh_remote": peer.exchange_public,
        "send_chain": directional(identity.identity_id, peer.identity_id),
        "recv_chain": directional(peer.identity_id, identity.identity_id),
        "send_n": 0,
        "recv_n": 0,
        "previous_send_n": 0,
        "phase": "new",
        "skipped": {},
    }


def ensure_state(
    states: dict[str, Any], identity: IdentityBundle, secrets: IdentitySecrets, peer: IdentityBundle
) -> dict[str, Any]:
    state = states.get(peer.identity_id)
    if not isinstance(state, dict) or state.get("version") != 3:
        state = _initial_state(identity, secrets, peer)
        states[peer.identity_id] = state
    return state


def _root_step(root: bytes, dh: bytes) -> tuple[bytes, bytes]:
    material = _hkdf(dh, root, b"kerberus-double-ratchet-v3-step", 64)
    return material[:32], material[32:]


def _chain_step(chain: bytes) -> tuple[bytes, bytes]:
    message_key = hmac.new(chain, b"kerberus-dr-v3-message", hashlib.sha256).digest()
    next_chain = hmac.new(chain, b"kerberus-dr-v3-next", hashlib.sha256).digest()
    return next_chain, message_key


def _new_dh() -> tuple[str, str]:
    private = X25519PrivateKey.generate()
    return b64(private.private_bytes_raw()), b64(private.public_key().public_bytes_raw())


def _dh(private: str, public: str) -> bytes:
    return X25519PrivateKey.from_private_bytes(unb64(private)).exchange(
        X25519PublicKey.from_public_bytes(unb64(public))
    )


def _start_initiator(state: dict[str, Any]) -> None:
    private, public = _new_dh()
    root, chain = _root_step(unb64(state["root"]), _dh(private, state["dh_remote"]))
    state.update({
        "root": b64(root), "send_chain": b64(chain), "send_n": 0,
        "previous_send_n": int(state.get("send_n", 0)),
        "dh_self_private": private, "dh_self_public": public,
    })


def is_ready(states: dict[str, Any], peer_id: str) -> bool:
    state = states.get(peer_id)
    return isinstance(state, dict) and state.get("version") == 3 and state.get("phase") == "ready"


def initiate(
    states: dict[str, Any], identity: IdentityBundle, secrets: IdentitySecrets, peer: IdentityBundle
) -> dict[str, Any] | None:
    """Start a content-free authenticated handshake.

    User content is deliberately held back until both peers contributed an
    ephemeral DH key. This avoids deriving the first message solely from
    long-term identity keys.
    """
    state = ensure_state(states, identity, secrets, peer)
    if state.get("phase") == "ready":
        return None
    if state.get("phase") == "new":
        _start_initiator(state)
        state["phase"] = "init_sent"
    return {"ratchet_version": 3, "dh": state["dh_self_public"]}


def accept_init(
    states: dict[str, Any], identity: IdentityBundle, secrets: IdentitySecrets,
    peer: IdentityBundle, header: dict[str, Any],
) -> dict[str, Any]:
    remote = str(header.get("dh", ""))
    if header.get("ratchet_version") != 3 or not remote:
        raise RatchetError("Handshake ratchet non valido")
    state = _initial_state(identity, secrets, peer)
    _dh_ratchet(state, remote)
    state["phase"] = "ready"
    states[peer.identity_id] = state
    return {"ratchet_version": 3, "dh": state["dh_self_public"]}


def complete_init(
    states: dict[str, Any], identity: IdentityBundle, secrets: IdentitySecrets,
    peer: IdentityBundle, header: dict[str, Any],
) -> None:
    state = ensure_state(states, identity, secrets, peer)
    remote = str(header.get("dh", ""))
    if header.get("ratchet_version") != 3 or state.get("phase") != "init_sent" or not remote:
        raise RatchetError("Risposta handshake ratchet inattesa")
    _dh_ratchet(state, remote)
    state["phase"] = "ready"


def encrypt(
    states: dict[str, Any],
    identity: IdentityBundle,
    secrets: IdentitySecrets,
    peer: IdentityBundle,
    payload: dict[str, Any],
) -> dict[str, Any]:
    state = ensure_state(states, identity, secrets, peer)
    if state.get("phase") != "ready":
        raise RatchetError("Handshake ratchet non completato")
    payload = dict(payload)
    payload.setdefault("sent_at", int(time.time()))
    chain, message_key = _chain_step(unb64(state["send_chain"]))
    number = int(state.get("send_n", 0))
    header = {
        "ratchet_version": 3,
        "dh": state["dh_self_public"],
        "pn": int(state.get("previous_send_n", 0)),
        "n": number,
    }
    nonce = os.urandom(24)
    ciphertext = crypto_aead_xchacha20poly1305_ietf_encrypt(canonical(payload), canonical(header), nonce, message_key)
    state["send_chain"] = b64(chain)
    state["send_n"] = number + 1
    return {**header, "nonce": b64(nonce), "ratchet_ciphertext": b64(ciphertext)}


def _skip_keys(state: dict[str, Any], until: int) -> None:
    current = int(state.get("recv_n", 0))
    if until - current > MAX_SKIP:
        raise RatchetError("Troppi messaggi ratchet mancanti")
    chain = unb64(state["recv_chain"])
    skipped = state.setdefault("skipped", {})
    while current < until:
        chain, message_key = _chain_step(chain)
        skipped[f"{state['dh_remote']}:{current}"] = b64(message_key)
        current += 1
    while len(skipped) > MAX_SKIP:
        skipped.pop(next(iter(skipped)))
    state["recv_chain"] = b64(chain)
    state["recv_n"] = current


def _dh_ratchet(state: dict[str, Any], remote: str) -> None:
    _skip_keys(state, int(state.get("recv_n", 0)))
    state["previous_send_n"] = int(state.get("send_n", 0))
    state["send_n"] = 0
    state["recv_n"] = 0
    state["dh_remote"] = remote
    root, recv_chain = _root_step(
        unb64(state["root"]), _dh(state["dh_self_private"], remote)
    )
    private, public = _new_dh()
    root, send_chain = _root_step(root, _dh(private, remote))
    state.update({
        "root": b64(root), "recv_chain": b64(recv_chain), "send_chain": b64(send_chain),
        "dh_self_private": private, "dh_self_public": public,
    })


def decrypt(
    states: dict[str, Any],
    identity: IdentityBundle,
    secrets: IdentitySecrets,
    peer: IdentityBundle,
    envelope: dict[str, Any],
) -> dict[str, Any]:
    existing = states.get(peer.identity_id)
    state = copy.deepcopy(existing) if isinstance(existing, dict) and existing.get("version") == 3 else _initial_state(identity, secrets, peer)
    if state.get("phase") != "ready":
        raise RatchetError("Handshake ratchet non completato")
    remote = str(envelope.get("dh", ""))
    number = envelope.get("n")
    if not remote or not isinstance(number, int) or number < 0:
        raise RatchetError("Header ratchet non valido")
    header = {
        "ratchet_version": envelope.get("ratchet_version"),
        "dh": remote,
        "pn": envelope.get("pn"),
        "n": number,
    }
    skipped_id = f"{remote}:{number}"
    encoded_key = state.setdefault("skipped", {}).pop(skipped_id, None)
    if encoded_key:
        message_key = unb64(encoded_key)
    else:
        if remote != state.get("dh_remote"):
            _skip_keys(state, int(envelope.get("pn", 0)))
            _dh_ratchet(state, remote)
        _skip_keys(state, number)
        chain, message_key = _chain_step(unb64(state["recv_chain"]))
        state["recv_chain"] = b64(chain)
        state["recv_n"] = number + 1
    try:
        clear = crypto_aead_xchacha20poly1305_ietf_decrypt(
            unb64(str(envelope["ratchet_ciphertext"])), canonical(header),
            unb64(str(envelope["nonce"])), message_key,
        )
    except Exception as exc:
        raise RatchetError("Messaggio ratchet non autenticato") from exc
    import json
    value = json.loads(clear.decode("utf-8"))
    if not isinstance(value, dict):
        raise RatchetError("Payload ratchet non valido")
    states[peer.identity_id] = state
    return value
