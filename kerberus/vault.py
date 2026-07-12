from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from nacl.bindings import crypto_aead_xchacha20poly1305_ietf_decrypt, crypto_aead_xchacha20poly1305_ietf_encrypt
from nacl.pwhash import argon2id

from .crypto import canonical, derive_vault_key


MAGIC = b"KBV1"


def empty_state() -> dict[str, Any]:
    return {
        "identity": None,
        "secrets": None,
        "contacts": {},
        "messages": [],
        "outbox": [],
        "control_outbox": [],
        "seen": [],
        "pending": {},
        "used_contact_codes": [],
        "chat_settings": {},
        "ratchets": {},
        "settings": {
            "contact_code_period_minutes": 1,
            "contact_code_single_use": True,
            "contact_code_generation": 0,
            "contact_code_anchor_time": int(time.time()),
            "send_delivery_receipts": True,
            "send_read_receipts": True,
            "link_previews": False,
            "minimize_to_tray": True,
            "clearnet_enabled": False,
            "dns_mode": "none",
            "dns_host": "base.dns.mullvad.net",
            "dns_ipv4": "194.242.2.4",
            "dns_ipv6": "2a07:e340::4",
            "dns_port": 853,
        },
    }


class Vault:
    def __init__(self, path: Path):
        self.path = path
        self._key: bytes | None = None
        self.state = empty_state()

    @property
    def exists(self) -> bool:
        return self.path.exists()

    def create(self, password: str) -> None:
        if len(password) < 10:
            raise ValueError("La password deve contenere almeno 10 caratteri")
        salt = os.urandom(argon2id.SALTBYTES)
        self._key = derive_vault_key(password, salt)
        self.state = empty_state()
        self._write(salt)

    def unlock(self, password: str) -> None:
        raw = self.path.read_bytes()
        if len(raw) < 4 + argon2id.SALTBYTES + 24 or raw[:4] != MAGIC:
            raise ValueError("Vault non valido")
        salt = raw[4 : 4 + argon2id.SALTBYTES]
        nonce = raw[4 + argon2id.SALTBYTES : 4 + argon2id.SALTBYTES + 24]
        ciphertext = raw[4 + argon2id.SALTBYTES + 24 :]
        key = derive_vault_key(password, salt)
        try:
            clear = crypto_aead_xchacha20poly1305_ietf_decrypt(ciphertext, MAGIC + salt, nonce, key)
        except Exception as exc:
            raise ValueError("Password errata o vault danneggiato") from exc
        self._key = key
        self.state = json.loads(clear.decode("utf-8"))
        self.state.setdefault("seen", [])
        self.state.setdefault("outbox", [])
        self.state.setdefault("control_outbox", [])
        self.state.setdefault("pending", {})
        self.state.setdefault("used_contact_codes", [])
        self.state.setdefault("chat_settings", {})
        self.state.setdefault("ratchets", {})
        settings = self.state.setdefault("settings", {})
        settings.setdefault("contact_code_period_minutes", 1)
        settings.setdefault("contact_code_single_use", True)
        settings.setdefault("contact_code_generation", 0)
        settings.setdefault("contact_code_anchor_time", int(time.time()))
        settings.setdefault("send_delivery_receipts", True)
        settings.setdefault("send_read_receipts", True)
        settings.setdefault("link_previews", False)
        settings.setdefault("minimize_to_tray", True)
        settings.setdefault("clearnet_enabled", False)
        settings.setdefault("dns_mode", "none")
        settings.setdefault("dns_host", "base.dns.mullvad.net")
        settings.setdefault("dns_ipv4", "194.242.2.4")
        settings.setdefault("dns_ipv6", "2a07:e340::4")
        settings.setdefault("dns_port", 853)

    def save(self) -> None:
        if self._key is None:
            raise RuntimeError("Vault bloccato")
        raw = self.path.read_bytes()
        salt = raw[4 : 4 + argon2id.SALTBYTES]
        self._write(salt)

    def _write(self, salt: bytes) -> None:
        assert self._key is not None
        nonce = os.urandom(24)
        ciphertext = crypto_aead_xchacha20poly1305_ietf_encrypt(canonical(self.state), MAGIC + salt, nonce, self._key)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_bytes(MAGIC + salt + nonce + ciphertext)
        os.replace(temp, self.path)
