from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets as secure_random
import time
import uuid
from dataclasses import dataclass
from typing import Any

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from nacl.bindings import (
    crypto_aead_xchacha20poly1305_ietf_decrypt,
    crypto_aead_xchacha20poly1305_ietf_encrypt,
)
from nacl.pwhash import argon2id

try:
    from pqcrypto.kem import ml_kem_768
    _mlkem_import_error = ""
except (ImportError, OSError) as exc:
    ml_kem_768 = None
    _mlkem_import_error = f"{type(exc).__name__}: {exc}"


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def sign_control(secrets: "IdentitySecrets", payload: dict[str, Any]) -> str:
    signer = Ed25519PrivateKey.from_private_bytes(unb64(secrets.signing_private))
    return b64(signer.sign(canonical(payload)))


def verify_control(identity: "IdentityBundle", payload: dict[str, Any], signature: str) -> None:
    Ed25519PublicKey.from_public_bytes(unb64(identity.signing_public)).verify(
        unb64(signature), canonical(payload)
    )


def pq_available() -> bool:
    return ml_kem_768 is not None


def pq_unavailable_reason() -> str:
    return _mlkem_import_error or "modulo pqcrypto non caricato"


@dataclass(slots=True)
class IdentitySecrets:
    signing_private: str
    exchange_private: str
    pq_private: str


@dataclass(slots=True)
class IdentityBundle:
    version: int
    name: str
    identity_id: str
    signing_public: str
    exchange_public: str
    pq_public: str
    destination: str
    profile_code: str = ""
    avatar_data: str = ""
    signature: str = ""

    def unsigned(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "name": self.name,
            "identity_id": self.identity_id,
            "signing_public": self.signing_public,
            "exchange_public": self.exchange_public,
            "pq_public": self.pq_public,
            "destination": self.destination,
            "profile_code": self.profile_code,
            "avatar_data": self.avatar_data,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.unsigned(), "signature": self.signature}

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "IdentityBundle":
        return cls(
            version=value["version"],
            name=value["name"],
            identity_id=value["identity_id"],
            signing_public=value["signing_public"],
            exchange_public=value["exchange_public"],
            pq_public=value["pq_public"],
            destination=value.get("destination", ""),
            profile_code=value.get("profile_code", ""),
            avatar_data=value.get("avatar_data", ""),
            signature=value.get("signature", ""),
        )

    def verify(self) -> None:
        if self.version != 1 or not self.name or len(self.name) > 80:
            raise ValueError("Formato identità non supportato")
        if len(unb64(self.signing_public)) != 32 or len(unb64(self.exchange_public)) != 32:
            raise ValueError("Chiave classica non valida")
        if not pq_available() or len(unb64(self.pq_public)) != ml_kem_768.PUBLIC_KEY_SIZE:
            raise ValueError("Chiave ML-KEM-768 non valida")
        if self.profile_code and profile_destination(self.profile_code) != destination_b32(self.destination):
            raise ValueError("Codice Kerberus non associato alla destination firmata")
        expected = hashlib.sha256(unb64(self.signing_public)).hexdigest()
        if expected != self.identity_id:
            raise ValueError("Identity ID non corrispondente alla chiave di firma")
        if self.avatar_data:
            avatar = unb64(self.avatar_data)
            if len(avatar) > 120_000 or not avatar.startswith(b"\x89PNG\r\n\x1a\n"):
                raise ValueError("Foto profilo non valida")
        verifier = Ed25519PublicKey.from_public_bytes(unb64(self.signing_public))
        payloads = [self.unsigned()]
        if not self.avatar_data:
            legacy = dict(self.unsigned())
            legacy.pop("avatar_data")
            payloads.append(legacy)
        for payload in payloads:
            try:
                verifier.verify(unb64(self.signature), canonical(payload))
                return
            except Exception:
                continue
        raise ValueError("Firma del profilo non valida")


def generate_identity(name: str, destination: str = "") -> tuple[IdentityBundle, IdentitySecrets]:
    if not pq_available():
        raise RuntimeError("Backend ML-KEM-768 non disponibile")
    signing = Ed25519PrivateKey.generate()
    exchange = X25519PrivateKey.generate()
    pq_public, pq_private = ml_kem_768.generate_keypair()
    signing_public = signing.public_key().public_bytes_raw()
    bundle = IdentityBundle(
        version=1,
        name=name.strip() or "Anonimo",
        identity_id=hashlib.sha256(signing_public).hexdigest(),
        signing_public=b64(signing_public),
        exchange_public=b64(exchange.public_key().public_bytes_raw()),
        pq_public=b64(pq_public),
        destination=destination,
    )
    secrets = IdentitySecrets(
        signing_private=b64(signing.private_bytes_raw()),
        exchange_private=b64(exchange.private_bytes_raw()),
        pq_private=b64(pq_private),
    )
    bundle.signature = b64(signing.sign(canonical(bundle.unsigned())))
    return bundle, secrets


def update_destination(bundle: IdentityBundle, secrets: IdentitySecrets, destination: str) -> None:
    bundle.destination = destination
    try:
        current_matches = profile_destination(bundle.profile_code) == destination_b32(destination)
    except ValueError:
        current_matches = False
    if not current_matches:
        alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
        prefix = "".join(secure_random.choice(alphabet) for _ in range(4))
        bundle.profile_code = f"{prefix}-KERBERUS-{destination_b32(destination).removesuffix('.b32.i2p')}"
    resign_identity(bundle, secrets)


def resign_identity(bundle: IdentityBundle, secrets: IdentitySecrets) -> None:
    bundle.name = bundle.name.strip()
    if not bundle.name or len(bundle.name) > 40 or not all(char.isprintable() for char in bundle.name):
        raise ValueError("L'username deve contenere da 1 a 40 caratteri stampabili")
    signer = Ed25519PrivateKey.from_private_bytes(unb64(secrets.signing_private))
    bundle.signature = b64(signer.sign(canonical(bundle.unsigned())))


def update_public_profile(
    bundle: IdentityBundle,
    secrets: IdentitySecrets,
    name: str,
    avatar_data: str,
) -> None:
    if avatar_data:
        avatar = unb64(avatar_data)
        if len(avatar) > 120_000 or not avatar.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("La foto profilo deve essere un PNG valido sotto 120 KB")
    bundle.name = name
    bundle.avatar_data = avatar_data
    resign_identity(bundle, secrets)


PROFILE_CODE_RE = re.compile(
    r"^([A-HJ-NP-Z2-9]{4})-KERBERUS-(?:([A-HJ-NP-Z2-9]{16})-)?([a-z2-7]{52})$",
    re.IGNORECASE,
)


def destination_b32(destination: str) -> str:
    if not destination:
        raise ValueError("Destination I2P mancante")
    try:
        standard = destination.translate(str.maketrans("-~", "+/"))
        raw = base64.b64decode(standard + "=" * (-len(standard) % 4), validate=True)
    except Exception as exc:
        raise ValueError("Destination I2P non valida") from exc
    if len(raw) < 384:
        raise ValueError("Destination I2P troppo corta")
    address = base64.b32encode(hashlib.sha256(raw).digest()).decode("ascii").lower().rstrip("=")
    return f"{address}.b32.i2p"


def profile_destination(code: str) -> str:
    match = PROFILE_CODE_RE.fullmatch(code.strip())
    if not match:
        raise ValueError("Codice non valido: usa il formato XXXX-KERBERUS-...")
    return f"{match.group(3).lower()}.b32.i2p"


def rotating_contact_code(
    identity: IdentityBundle,
    secrets: IdentitySecrets,
    minute: int | None = None,
    *,
    period_minutes: int = 1,
    generation: int = 0,
    anchor_time: int = 0,
    timestamp: int | None = None,
) -> str:
    if not identity.destination:
        raise ValueError("Profilo non ancora collegato a I2P")
    if period_minutes not in (1, 5, 15, 60):
        raise ValueError("Durata codice contatto non supportata")
    current_time = timestamp if timestamp is not None else (int(time.time()) if minute is None else minute * 60)
    period_seconds = period_minutes * 60
    slot = (
        max(0, current_time - anchor_time) // period_seconds
        if anchor_time > 0
        else current_time // period_seconds
    )
    key = unb64(secrets.signing_private)
    digest = hmac.new(
        key,
        f"kerberus-contact-code-v2:{slot}:{generation}".encode("ascii"),
        hashlib.sha256,
    ).digest()
    token = base64.b32encode(digest).decode("ascii").rstrip("=")
    prefix = token[:4].replace("I", "8").replace("O", "9")
    rotating = token[4:20].replace("I", "8").replace("O", "9")
    suffix = destination_b32(identity.destination).removesuffix(".b32.i2p")
    return f"{prefix}-KERBERUS-{rotating}-{suffix}"


def _message_key(classical: bytes, quantum: bytes, context: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA512(), length=32, salt=hashlib.sha256(context).digest(), info=b"kerberus-v1-hybrid-message").derive(classical + quantum)


def seal_payload(
    sender: IdentityBundle,
    secrets: IdentitySecrets,
    recipient: IdentityBundle,
    payload: dict[str, Any],
    *,
    message_id: str | None = None,
) -> dict[str, Any]:
    if not pq_available():
        raise RuntimeError(f"ML-KEM-768 non disponibile: {pq_unavailable_reason()}")
    sent_at = int(time.time())
    clear_fields = {**payload, "sent_at": sent_at}
    unpadded = canonical({**clear_fields, "padding": ""})
    bucket = next((size for size in (512, 2048, 8192, 32768) if len(unpadded) <= size), None)
    if bucket is None:
        raise ValueError("Messaggio troppo lungo")
    padding = b64(os.urandom(max(0, (bucket - len(unpadded)) * 3 // 4)))
    clear_payload = canonical({**clear_fields, "padding": padding})
    ephemeral = X25519PrivateKey.generate()
    ephemeral_public = ephemeral.public_key().public_bytes_raw()
    classical = ephemeral.exchange(X25519PublicKey.from_public_bytes(unb64(recipient.exchange_public)))
    pq_ciphertext, quantum = ml_kem_768.encrypt(unb64(recipient.pq_public))
    header = {
        "version": 1,
        "type": "message",
        "sender_id": sender.identity_id,
        "recipient_id": recipient.identity_id,
        "message_id": message_id or uuid.uuid4().hex,
        "ephemeral": b64(ephemeral_public),
        "pq_ciphertext": b64(pq_ciphertext),
    }
    context = canonical(header)
    key = _message_key(classical, quantum, context)
    nonce = os.urandom(24)
    ciphertext = crypto_aead_xchacha20poly1305_ietf_encrypt(clear_payload, context, nonce, key)
    envelope = {**header, "nonce": b64(nonce), "ciphertext": b64(ciphertext)}
    signer = Ed25519PrivateKey.from_private_bytes(unb64(secrets.signing_private))
    envelope["signature"] = b64(signer.sign(canonical(envelope)))
    return envelope


def seal_message(sender: IdentityBundle, secrets: IdentitySecrets, recipient: IdentityBundle, plaintext: str) -> dict[str, Any]:
    return seal_payload(sender, secrets, recipient, {"kind": "message", "text": plaintext})


def open_message_payload(
    recipient: IdentityBundle,
    secrets: IdentitySecrets,
    sender: IdentityBundle,
    envelope: dict[str, Any],
) -> dict[str, Any]:
    signed = dict(envelope)
    signature = unb64(signed.pop("signature"))
    Ed25519PublicKey.from_public_bytes(unb64(sender.signing_public)).verify(signature, canonical(signed))
    if envelope.get("sender_id") != sender.identity_id or envelope.get("recipient_id") != recipient.identity_id:
        raise ValueError("Destinatario o mittente non valido")
    header = {key: envelope[key] for key in ("version", "type", "sender_id", "recipient_id", "message_id", "ephemeral", "pq_ciphertext")}
    context = canonical(header)
    private = X25519PrivateKey.from_private_bytes(unb64(secrets.exchange_private))
    classical = private.exchange(X25519PublicKey.from_public_bytes(unb64(envelope["ephemeral"])))
    if not pq_available():
        raise RuntimeError(f"ML-KEM-768 non disponibile: {pq_unavailable_reason()}")
    quantum = ml_kem_768.decrypt(unb64(secrets.pq_private), unb64(envelope["pq_ciphertext"]))
    key = _message_key(classical, quantum, context)
    clear = crypto_aead_xchacha20poly1305_ietf_decrypt(unb64(envelope["ciphertext"]), context, unb64(envelope["nonce"]), key)
    payload = json.loads(clear.decode("utf-8"))
    sent_at = payload.get("sent_at")
    if not isinstance(sent_at, int) or sent_at < 0:
        raise ValueError("Timestamp mittente non valido")
    kind = str(payload.get("kind", "message"))
    result = {key: value for key, value in payload.items() if key != "padding"}
    result["kind"] = kind
    result["sent_at"] = sent_at
    if kind == "message":
        result["text"] = str(payload["text"])
    return result


def open_message(recipient: IdentityBundle, secrets: IdentitySecrets, sender: IdentityBundle, envelope: dict[str, Any]) -> str:
    return str(open_message_payload(recipient, secrets, sender, envelope)["text"])


def derive_vault_key(password: str, salt: bytes) -> bytes:
    return argon2id.kdf(32, password.encode("utf-8"), salt, opslimit=argon2id.OPSLIMIT_MODERATE, memlimit=argon2id.MEMLIMIT_MODERATE)
