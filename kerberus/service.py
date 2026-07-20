from __future__ import annotations

import base64
import hashlib
import hmac
import json
import copy
import mimetypes
import os
import secrets
import threading
import time
import uuid
import emoji as emoji_data
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from nacl.bindings import crypto_aead_xchacha20poly1305_ietf_decrypt, crypto_aead_xchacha20poly1305_ietf_encrypt

from .config import AppConfig
from .crypto import (
    IdentityBundle,
    IdentitySecrets,
    b64,
    destination_b32,
    generate_identity,
    open_message_payload,
    profile_destination,
    rotating_contact_code,
    seal_payload,
    sign_control,
    update_destination,
    update_public_profile,
    unb64,
    verify_control,
)
from .sam import SamClient
from .ratchet import (
    accept_init as ratchet_accept_init,
    complete_init as ratchet_complete_init,
    decrypt as ratchet_decrypt,
    encrypt as ratchet_encrypt,
    initiate as ratchet_initiate,
    is_ready as ratchet_is_ready,
)
from .vault import Vault
from .voice import NativeVoiceCodec, pcm_to_wav, validate_voice_payload


def _reaction_values(value: object) -> list[str]:
    """Normalize legacy single reactions and the current multi-reaction format."""
    candidates = value if isinstance(value, list) else [value] if isinstance(value, str) else []
    normalized: list[str] = []
    for candidate in candidates:
        emoji = str(candidate)
        if emoji_data.is_emoji(emoji) and len(emoji) <= 32 and emoji not in normalized:
            normalized.append(emoji)
    return normalized[:12]


ATTACHMENT_CHUNK_BYTES = 512 * 1024
MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024
MAX_VIDEO_ATTACHMENT_BYTES = 100 * 1024 * 1024
MAX_INLINE_IMAGE_BYTES = 5 * 1024 * 1024


def _safe_attachment_name(value: object) -> str:
    name = str(value).replace("\\", "/").rsplit("/", 1)[-1].replace("\x00", "").strip()
    if not name:
        raise ValueError("Nome allegato non valido")
    return name[:180]


def _normalize_attachment(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("Allegato non valido")
    name = _safe_attachment_name(value.get("name", ""))
    mime_type = str(value.get("mime", "application/octet-stream")).strip().lower()
    if not mime_type or "/" not in mime_type or len(mime_type) > 127:
        mime_type = "application/octet-stream"
    encoded = value.get("data", "")
    if not isinstance(encoded, str):
        raise ValueError("Dati allegato non validi")
    try:
        raw = base64.b64decode(encoded.encode("ascii"), validate=True)
    except (ValueError, UnicodeEncodeError) as exc:
        raise ValueError("Dati allegato non validi") from exc
    if not raw:
        raise ValueError("Il file è vuoto")
    limit = MAX_VIDEO_ATTACHMENT_BYTES if mime_type.startswith("video/") else MAX_ATTACHMENT_BYTES
    if len(raw) > limit:
        raise ValueError("Il file supera il limite consentito")
    declared_size = value.get("size")
    if declared_size is not None and declared_size != len(raw):
        raise ValueError("Dimensione allegato non valida")
    digest = hashlib.sha256(raw).hexdigest()
    declared_digest = str(value.get("sha256", ""))
    if declared_digest and not hmac.compare_digest(declared_digest, digest):
        raise ValueError("Hash allegato non valido")
    return {
        "name": name,
        "mime": mime_type,
        "size": len(raw),
        "sha256": digest,
        "data": base64.b64encode(raw).decode("ascii"),
    }


def _attachment_limit(mime_type: str) -> int:
    return MAX_VIDEO_ATTACHMENT_BYTES if mime_type.startswith("video/") else MAX_ATTACHMENT_BYTES


def _normalize_attachment_metadata(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("Metadati allegato non validi")
    name = _safe_attachment_name(value.get("name", ""))
    mime_type = str(value.get("mime", "application/octet-stream")).strip().lower()
    if not mime_type or "/" not in mime_type or len(mime_type) > 127:
        mime_type = "application/octet-stream"
    try:
        size = int(value.get("size", -1))
        total_chunks = int(value.get("total_chunks", 0))
    except (TypeError, ValueError) as exc:
        raise ValueError("Dimensione allegato non valida") from exc
    if size <= 0 or size > _attachment_limit(mime_type):
        raise ValueError("Dimensione allegato non valida")
    expected_chunks = (size + ATTACHMENT_CHUNK_BYTES - 1) // ATTACHMENT_CHUNK_BYTES
    if total_chunks != expected_chunks:
        raise ValueError("Numero di blocchi non valido")
    digest = str(value.get("sha256", "")).lower()
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise ValueError("Hash allegato non valido")
    return {
        "name": name,
        "mime": mime_type,
        "size": size,
        "sha256": digest,
        "chunk_size": ATTACHMENT_CHUNK_BYTES,
        "total_chunks": total_chunks,
    }


class MessengerService:
    _MESSAGE_RETRY_SECONDS = (2, 3, 5, 8, 12, 20)
    _CONTROL_RETRY_SECONDS = (2, 3, 5, 8, 12)
    _CONTACT_RETRY_SECONDS = (3, 5, 8, 12, 20, 30)
    def __init__(self, config: AppConfig):
        self.config = config
        self.vault = Vault(config.vault_path)
        self.sam = SamClient(config.sam_host, config.sam_port, config.sam_keys_path)
        self.on_message: Callable[[str, str], None] | None = None
        self.on_contacts_changed: Callable[[str], None] | None = None
        self.on_protocol_event: Callable[[str, str], None] | None = None
        self.last_protocol_event = "Nessuna richiesta elaborata in questa sessione"
        self._listener: threading.Thread | None = None
        self._delivery_thread: threading.Thread | None = None
        self._stop_delivery = threading.Event()
        self._state_lock = threading.RLock()
        self._delivery_pool = ThreadPoolExecutor(max_workers=6, thread_name_prefix="kerberus-delivery")
        self._inflight: set[tuple[str, str]] = set()
        # Monotonic timestamps are session-local by design: wall-clock changes
        # cannot corrupt encrypted receipt round-trip measurements.
        self._receipt_started_ns: dict[str, int] = {}
        self._voice_codec: NativeVoiceCodec | None = None
        self._attachment_store = config.vault_path.parent / "attachments"

    def identity(self) -> IdentityBundle | None:
        value = self.vault.state.get("identity")
        return IdentityBundle.from_dict(value) if value else None

    def secrets(self) -> IdentitySecrets:
        return IdentitySecrets(**self.vault.state["secrets"])

    def create_identity(self, name: str) -> IdentityBundle:
        bundle, secrets = generate_identity(name)
        self.vault.state["identity"] = bundle.to_dict()
        self.vault.state["secrets"] = {field: getattr(secrets, field) for field in secrets.__dataclass_fields__}
        self.vault.save()
        return bundle

    def connect_router(self) -> str:
        if not self.sam.available():
            raise ConnectionError("SAM non raggiungibile su 127.0.0.1:7656")
        if not self.config.sam_keys_path.exists():
            destination = self.sam.generate_persistent_destination()
        else:
            destination = ""
        self.sam.set_receiver(self._receive_safely)
        self.sam.configure_low_latency(bool(self.settings().get("low_latency_mode", False)), restart=False)
        active = self.sam.start_session() or destination
        identity = self.identity()
        if identity and active:
            update_destination(identity, self.secrets(), active)
            self.vault.state["identity"] = identity.to_dict()
            self.vault.save()
        if not self.sam.native_active and (self._listener is None or not self._listener.is_alive()):
            self._listener = threading.Thread(target=self.sam.listen, args=(self._receive_safely,), daemon=True)
            self._listener.start()
        if self._delivery_thread is None or not self._delivery_thread.is_alive():
            self._stop_delivery.clear()
            self._delivery_thread = threading.Thread(target=self._delivery_loop, daemon=True)
            self._delivery_thread.start()
        self.retry_all_now()
        if self.settings().get("warm_recent_contacts", True):
            self.warm_recent_contacts()
        return active

    def _receive_safely(self, payload: bytes, remote_destination: str = "") -> bytes | None:
        try:
            return self._receive(payload, remote_destination, inline_reply=True)
        except Exception as exc:
            self._emit_protocol_event("receive_error", f"Frame I2P ricevuto ma rifiutato: {type(exc).__name__}")
            return None

    def queue_status(self) -> dict[str, int]:
        with self._state_lock:
            return {
                "messages": len(self.vault.state.get("outbox", [])),
                "contacts": len(self.vault.state.get("pending", {})),
                "control": len(self.vault.state.get("control_outbox", [])),
            }

    def retry_all_now(self) -> dict[str, int]:
        handshakes: set[str] = set()
        resumable_attachments: list[str] = []
        with self._state_lock:
            # Upgrade locally-created requests from pre-authentication releases.
            # They can be re-signed safely because the original target code and
            # local signed profile are still inside the encrypted vault.
            for entry in self.vault.state.get("pending", {}).values():
                try:
                    request = json.loads(str(entry.get("payload", "")))
                    if request.get("type") == "contact_request" and not request.get("signature"):
                        request_id = uuid.uuid4().hex
                        request["request_id"] = request_id
                        request["signature"] = sign_control(self.secrets(), request)
                        entry["request_id"] = request_id
                        entry["payload"] = json.dumps(request, separators=(",", ":"))
                except (TypeError, ValueError, json.JSONDecodeError):
                    continue
            for entry in self.vault.state.get("outbox", []):
                contact_id = str(entry.get("contact_id", ""))
                if not ratchet_is_ready(self.vault.state.setdefault("ratchets", {}), contact_id):
                    stored = next(
                        (message for message in self.vault.state.get("messages", [])
                         if message.get("message_id") == entry.get("message_id")), None
                    )
                    if stored:
                        entry["payload"] = ""
                        entry["deferred"] = {"kind": "message", "text": str(stored.get("text", ""))}
                        handshakes.add(contact_id)
                entry["last_attempt"] = 0
            for entry in self.vault.state.get("pending", {}).values():
                entry["last_attempt"] = 0
            for entry in self.vault.state.get("control_outbox", []):
                entry["last_attempt"] = 0
            resumable_attachments = [
                str(transfer_id) for transfer_id, transfer in self.vault.state.setdefault("attachment_transfers", {}).items()
                if isinstance(transfer, dict) and transfer.get("direction") == "out"
                and transfer.get("state") == "transferring" and not transfer.get("paused")
                and not transfer.get("active_message_id")
            ]
            status = self.queue_status()
            self.vault.save()
        for contact_id in handshakes:
            contact_data = self.vault.state.get("contacts", {}).get(contact_id)
            if contact_data:
                self._ensure_ratchet_handshake(IdentityBundle.from_dict(contact_data))
        self.flush_control_outbox(background=True)
        self.flush_pending_contacts(background=True)
        self.flush_outbox(background=True)
        for transfer_id in resumable_attachments:
            self._queue_next_attachment_part(transfer_id, force=True)
        self._emit_protocol_event(
            "queues_retried",
            f"Retry immediato: {status['messages']} messaggi, {status['contacts']} contatti, {status['control']} conferme",
        )
        return status

    def warm_contact(self, contact_id: str) -> None:
        contact = self.vault.state.get("contacts", {}).get(contact_id)
        if not contact or not hasattr(self.sam, "warm"):
            return
        destination = contact.get("destination", "")
        if destination:
            self._submit_delivery("warm", contact_id, self._warm_destination, destination)

    def warm_recent_contacts(self, limit: int = 8) -> None:
        if self.settings().get("mask_recent_contact_metadata", False):
            # SAM CONNECT cannot use a fake destination. Randomly selecting
            # real contacts hides which conversations were most recent without
            # creating unsolicited streams to arbitrary third parties.
            candidates = [
                str(contact_id)
                for contact_id, contact in self.vault.state.get("contacts", {}).items()
                if isinstance(contact, dict) and contact.get("destination")
            ]
            selected = secrets.SystemRandom().sample(candidates, min(limit, len(candidates)))
            for contact_id in selected:
                self.warm_contact(contact_id)
            return
        recent_ids: list[str] = []
        for message in reversed(self.vault.state.get("messages", [])):
            contact_id = message.get("contact_id", "")
            if contact_id and contact_id not in recent_ids:
                recent_ids.append(contact_id)
            if len(recent_ids) >= limit:
                break
        for contact_id in recent_ids:
            self.warm_contact(contact_id)

    def _warm_destination(self, destination: str) -> bool:
        try:
            self.sam.warm(destination)
            return True
        except Exception:
            # Il warm-up è solo un'ottimizzazione. SAM può non essere ancora
            # pronto durante l'avvio e il normale invio aprirà lo stream dopo.
            return False

    def import_contact(self, raw: str) -> IdentityBundle:
        if len(raw.encode("utf-8")) > 300_000:
            raise ValueError("File identità troppo grande")
        bundle = IdentityBundle.from_dict(json.loads(raw))
        bundle.verify()
        if not bundle.destination:
            raise ValueError("Il contatto non contiene una destination I2P")
        self.vault.state["contacts"][bundle.identity_id] = bundle.to_dict()
        self.vault.save()
        return bundle

    def export_identity(self) -> str:
        identity = self.identity()
        if not identity:
            raise RuntimeError("Identità non configurata")
        return json.dumps(identity.to_dict(), sort_keys=True, indent=2)

    def contacts(self) -> list[IdentityBundle]:
        return [IdentityBundle.from_dict(item) for item in self.vault.state["contacts"].values()]

    def contact_code(self) -> str:
        identity = self.identity()
        if not identity:
            raise RuntimeError("Identità non configurata")
        settings = self.settings()
        return rotating_contact_code(
            identity,
            self.secrets(),
            period_minutes=settings["contact_code_period_minutes"],
            generation=settings["contact_code_generation"],
            anchor_time=settings["contact_code_anchor_time"],
        )

    def settings(self) -> dict:
        settings = self.vault.state.setdefault("settings", {})
        settings.setdefault("contact_code_period_minutes", 1)
        settings.setdefault("contact_code_single_use", True)
        settings.setdefault("contact_code_generation", 0)
        settings.setdefault("contact_code_anchor_time", int(time.time()))
        settings.setdefault("send_delivery_receipts", True)
        settings.setdefault("send_read_receipts", True)
        settings.setdefault("link_previews", False)
        settings.setdefault("clearnet_enabled", False)
        settings.setdefault("stream_proof_enabled", False)
        settings.setdefault("low_latency_mode", False)
        settings.setdefault("warm_recent_contacts", True)
        settings.setdefault("mask_recent_contact_metadata", False)
        settings.setdefault("audio_input_device_id", "")
        settings.setdefault("audio_output_device_id", "")
        settings.setdefault("language", "it")
        settings.setdefault("theme", "default")
        settings.setdefault("text_scale", 100)
        settings.setdefault("ui_density", "comfortable")
        for obsolete in ("dns_mode", "dns_host", "dns_ipv4", "dns_ipv6", "dns_port", "minimize_to_tray", "ipinfo_token"):
            settings.pop(obsolete, None)
        return dict(settings)

    def update_network_settings(
        self,
        *,
        low_latency_mode: bool,
        warm_recent_contacts: bool,
        mask_recent_contact_metadata: bool | None = None,
    ) -> dict:
        """Persist and apply the Kerberus-specific I2P transport profile."""
        enabled = bool(low_latency_mode)
        keep_warm = bool(warm_recent_contacts)
        with self._state_lock:
            settings = self.vault.state.setdefault("settings", {})
            was_warm = bool(settings.get("warm_recent_contacts", True))
            was_masked = bool(settings.get("mask_recent_contact_metadata", False))
            mask_metadata = was_masked if mask_recent_contact_metadata is None else bool(mask_recent_contact_metadata)
            settings["low_latency_mode"] = enabled
            settings["warm_recent_contacts"] = keep_warm
            settings["mask_recent_contact_metadata"] = mask_metadata
            self.vault.save()
        restarted = self.sam.configure_low_latency(enabled)
        if restarted:
            self.retry_all_now()
        if keep_warm and (restarted or not was_warm or mask_metadata != was_masked) and self.sam.destination:
            self.warm_recent_contacts()
        mode = "bassa latenza · 2 hop" if enabled else "massima privacy · 3 hop"
        self._emit_protocol_event("network_profile_updated", f"Profilo I2P applicato: {mode}")
        return {
            "low_latency_mode": enabled,
            "warm_recent_contacts": keep_warm,
            "mask_recent_contact_metadata": mask_metadata,
            "session_restarted": restarted,
        }

    def update_settings(self, period_minutes: int, single_use: bool) -> dict:
        if period_minutes not in (1, 5, 15, 60):
            raise ValueError("Intervallo codice non supportato")
        with self._state_lock:
            settings = self.vault.state.setdefault("settings", {})
            if settings.get("contact_code_period_minutes", 1) != period_minutes:
                settings["contact_code_generation"] = int(settings.get("contact_code_generation", 0)) + 1
                settings["contact_code_anchor_time"] = int(time.time())
            settings["contact_code_period_minutes"] = period_minutes
            settings["contact_code_single_use"] = bool(single_use)
            settings.setdefault("contact_code_generation", 0)
            settings.setdefault("contact_code_anchor_time", int(time.time()))
            self.vault.save()
        self._emit_protocol_event("settings_updated", "Impostazioni privacy aggiornate")
        return dict(settings)

    def update_privacy_settings(self, **values: object) -> dict:
        allowed = {
            "send_delivery_receipts", "send_read_receipts", "link_previews",
            "clearnet_enabled", "stream_proof_enabled",
            "language",
        }
        unknown = set(values) - allowed
        if unknown:
            raise ValueError(f"Impostazioni non supportate: {', '.join(sorted(unknown))}")
        if "language" in values and values["language"] not in {"it", "en"}:
            raise ValueError("Lingua non supportata")
        with self._state_lock:
            settings = self.vault.state.setdefault("settings", {})
            settings.update(values)
            for obsolete in ("dns_mode", "dns_host", "dns_ipv4", "dns_ipv6", "dns_port", "minimize_to_tray", "ipinfo_token"):
                settings.pop(obsolete, None)
            self.vault.save()
        self._emit_protocol_event("privacy_settings_updated", "Policy rete e ricevute aggiornata")
        return self.settings()

    def update_audio_settings(self, input_device_id: str, output_device_id: str) -> dict:
        """Persist opaque Qt audio-device ids inside the encrypted local vault."""
        if not isinstance(input_device_id, str) or not isinstance(output_device_id, str):
            raise ValueError("Identificatore del dispositivo audio non valido")
        if len(input_device_id) > 4096 or len(output_device_id) > 4096:
            raise ValueError("Identificatore del dispositivo audio troppo lungo")
        with self._state_lock:
            settings = self.vault.state.setdefault("settings", {})
            settings["audio_input_device_id"] = input_device_id
            settings["audio_output_device_id"] = output_device_id
            self.vault.save()
        self._emit_protocol_event("audio_settings_updated", "Dispositivi audio aggiornati")
        return self.settings()

    def update_appearance_settings(self, theme: str, text_scale: int, ui_density: str) -> dict:
        """Persist validated application-wide appearance preferences."""
        if theme not in {"default", "pink", "orange", "white", "dark"}:
            raise ValueError("Tema non supportato")
        if text_scale not in {90, 100, 110, 120}:
            raise ValueError("Dimensione del testo non supportata")
        if ui_density not in {"compact", "comfortable", "spacious"}:
            raise ValueError("Densità dell’interfaccia non supportata")
        with self._state_lock:
            settings = self.vault.state.setdefault("settings", {})
            settings["theme"] = theme
            settings["text_scale"] = text_scale
            settings["ui_density"] = ui_density
            self.vault.save()
        self._emit_protocol_event("appearance_settings_updated", "Aspetto dell’interfaccia aggiornato")
        return self.settings()

    def test_voice_roundtrip(
        self,
        pcm: bytes,
        *,
        sample_rate: int,
        channels: int,
        sample_format: str,
    ) -> bytes:
        """Exercise the same Go encode/decode path used by shared voice messages."""
        codec = self._voice_codec or NativeVoiceCodec()
        self._voice_codec = codec
        voice, _encode_metrics = codec.encode(
            pcm,
            sample_rate=sample_rate,
            channels=channels,
            sample_format=sample_format,
        )
        decoded, _decode_metrics = codec.decode(voice)
        return pcm_to_wav(decoded)

    def chat_settings(self, contact_id: str) -> dict:
        stored = self.vault.state.setdefault("chat_settings", {}).setdefault(contact_id, {})
        return {
            "send_delivery_receipts": stored.get("send_delivery_receipts"),
            "send_read_receipts": stored.get("send_read_receipts"),
            "link_previews": stored.get("link_previews"),
            "notifications": bool(stored.get("notifications", True)),
            "show_identity_id": bool(stored.get("show_identity_id", True)),
            "remote_identity_id_visible": bool(stored.get("remote_identity_id_visible", True)),
        }

    def update_chat_settings(self, contact_id: str, **values: object) -> dict:
        if contact_id not in self.vault.state.get("contacts", {}):
            raise ValueError("Contatto non trovato")
        allowed = {
            "send_delivery_receipts", "send_read_receipts", "link_previews", "notifications",
            "show_identity_id",
        }
        if set(values) - allowed:
            raise ValueError("Impostazione chat non supportata")
        with self._state_lock:
            stored = self.vault.state.setdefault("chat_settings", {}).setdefault(contact_id, {})
            visibility_changed = (
                "show_identity_id" in values
                and bool(stored.get("show_identity_id", True)) != bool(values["show_identity_id"])
            )
            stored.update(values)
            self.vault.save()
        if visibility_changed:
            self._send_identity_visibility(contact_id, bool(values["show_identity_id"]))
        return self.chat_settings(contact_id)

    def _send_identity_visibility(self, contact_id: str, visible: bool) -> None:
        identity = self.identity()
        contact_data = self.vault.state.get("contacts", {}).get(contact_id)
        if not identity or not contact_data:
            return
        contact = IdentityBundle.from_dict(contact_data)
        envelope = seal_payload(
            identity, self.secrets(), contact,
            {"kind": "identity_visibility", "visible": bool(visible)},
        )
        self._queue_control(contact.destination, envelope, background=True)

    def _privacy_enabled(self, contact_id: str, name: str) -> bool:
        override = self.chat_settings(contact_id).get(name)
        return bool(self.settings().get(name, False) if override is None else override)

    def effective_chat_setting(self, contact_id: str, name: str) -> bool:
        return self._privacy_enabled(contact_id, name)

    def update_profile(self, name: str, avatar_data: str) -> IdentityBundle:
        identity = self.identity()
        if not identity:
            raise RuntimeError("Identità non configurata")
        update_public_profile(identity, self.secrets(), name, avatar_data)
        with self._state_lock:
            self.vault.state["identity"] = identity.to_dict()
            self.vault.save()
        update = {"version": 1, "type": "profile_update", "sender": identity.to_dict()}
        payload = json.dumps(update, separators=(",", ":")).encode("utf-8")
        for contact in self.contacts():
            try:
                self.sam.send(contact.destination, payload)
            except Exception:
                continue
        return identity

    def request_contact(self, code: str, first_message: str = "") -> str:
        identity = self.identity()
        if not identity or not identity.profile_code:
            raise RuntimeError("Profilo non ancora collegato a I2P")
        normalized = code.strip().upper()
        destination = profile_destination(normalized)
        if destination == profile_destination(self.contact_code()):
            raise ValueError("Non puoi aggiungere il tuo stesso codice")
        request = {
            "version": 1,
            "type": "contact_request",
            "request_id": uuid.uuid4().hex,
            "target_code": normalized,
            "sender": identity.to_dict(),
        }
        request["signature"] = sign_control(self.secrets(), request)
        payload = json.dumps(request, separators=(",", ":"))
        with self._state_lock:
            self.vault.state["pending"][destination] = {
                "target_code": normalized,
                "request_id": request["request_id"],
                "first_message": first_message.strip(),
                "payload": payload,
                "created_at": int(time.time()),
                "last_attempt": 0,
                "attempts": 0,
            }
            self.vault.save()
        sent = self._attempt_pending_contact(destination, force=True)
        return "sent" if sent else "queued"

    def pending_contacts(self) -> list[dict]:
        with self._state_lock:
            return [
                {
                    "destination": destination,
                    "target_code": str(entry.get("target_code", "")),
                    "created_at": int(entry.get("created_at", 0)),
                    "last_attempt": int(entry.get("last_attempt", 0)),
                    "attempts": int(entry.get("attempts", 0)),
                }
                for destination, entry in self.vault.state.get("pending", {}).items()
                if entry.get("payload")
            ]

    def cancel_pending_contact(self, destination: str) -> bool:
        with self._state_lock:
            removed = self.vault.state.get("pending", {}).pop(destination, None)
            if removed is not None:
                self.vault.save()
        if removed is not None:
            self._emit_protocol_event("contact_request_cancelled", "Richiesta contatto annullata localmente")
            return True
        return False

    def messages_for(self, contact_id: str) -> list[dict]:
        return [m for m in self.vault.state["messages"] if m["contact_id"] == contact_id]

    def export_chat_debug(self, contact_id: str) -> str:
        contact_data = self.vault.state.get("contacts", {}).get(contact_id)
        identity = self.identity()
        if not contact_data or not identity:
            raise ValueError("Chat non trovata")
        contact = IdentityBundle.from_dict(contact_data)

        def iso_time(value: object) -> str | None:
            if not isinstance(value, int) or value < 0:
                return None
            return datetime.fromtimestamp(value, timezone.utc).isoformat()

        def delay(later: object, earlier: object) -> int | None:
            if not isinstance(later, int) or not isinstance(earlier, int):
                return None
            return later - earlier

        with self._state_lock:
            exported_messages = []
            for message in self.vault.state.get("messages", []):
                if message.get("contact_id") != contact_id:
                    continue
                sent_at = message.get("sent_at", message.get("time"))
                received_at = message.get("received_at")
                recipient_received_at = message.get("recipient_received_at")
                delivered_at = message.get("delivered_at")
                read_at = message.get("read_at")
                outgoing = message.get("direction") == "out"
                peer_received_at = recipient_received_at if outgoing else received_at
                exported_messages.append({
                    "index": len(exported_messages),
                    "message_id": str(message.get("message_id", "")),
                    "direction": "out" if outgoing else "in",
                    "status": str(message.get("status", "")),
                    "kind": str(message.get("kind", "message")),
                    "text": str(message.get("text", "")),
                    "voice": {
                        "codec": str(dict(message.get("voice") or {}).get("codec", "")),
                        "duration_ms": dict(message.get("voice") or {}).get("duration_ms"),
                        "sample_rate": dict(message.get("voice") or {}).get("sample_rate"),
                        "sample_count": dict(message.get("voice") or {}).get("sample_count"),
                    } if message.get("kind") == "voice" else None,
                    "attachment": {
                        "name": str(dict(message.get("attachment") or {}).get("name", "")),
                        "mime": str(dict(message.get("attachment") or {}).get("mime", "")),
                        "size": dict(message.get("attachment") or {}).get("size"),
                        "sha256": str(dict(message.get("attachment") or {}).get("sha256", "")),
                    } if message.get("kind") == "attachment" else None,
                    "voice_codec_timings_ms": copy.deepcopy(message.get("voice_metrics", {}))
                    if isinstance(message.get("voice_metrics"), dict) else {},
                    "timestamps": {
                        "sent_epoch": sent_at,
                        "sent_utc": iso_time(sent_at),
                        "local_received_epoch": received_at,
                        "local_received_utc": iso_time(received_at),
                        "peer_received_epoch": recipient_received_at,
                        "peer_received_utc": iso_time(recipient_received_at),
                        "delivery_ack_epoch": delivered_at,
                        "delivery_ack_utc": iso_time(delivered_at),
                        "read_epoch": read_at,
                        "read_utc": iso_time(read_at),
                    },
                    "delays_seconds": {
                        "one_way_clock_dependent": delay(peer_received_at, sent_at),
                        "round_trip_local_clock": delay(delivered_at, sent_at) if outgoing else None,
                        "read_after_send": delay(read_at, sent_at) if outgoing else None,
                    },
                    "transport_timings_ms": copy.deepcopy(message.get("transport_metrics", {}))
                    if isinstance(message.get("transport_metrics"), dict) else {},
                    "encrypted_receipt_roundtrip_ms": message.get("encrypted_receipt_rtt_ms"),
                    "reactions": dict(message.get("reactions", {}))
                    if isinstance(message.get("reactions", {}), dict) else {},
                })
            pending_messages = sum(
                entry.get("contact_id") == contact_id for entry in self.vault.state.get("outbox", [])
            )
            pending_controls = sum(
                entry.get("destination") == contact.destination
                for entry in self.vault.state.get("control_outbox", [])
            )

        report = {
            "format": "kerberus-chat-debug-v1",
            "warning": "Contiene testo e metadati temporali in chiaro. Non contiene audio, password, chiavi private, stato ratchet o payload cifrati.",
            "exported_at_utc": datetime.now(timezone.utc).isoformat(),
            "local_profile": {"name": identity.name, "identity_id": identity.identity_id},
            "contact": {"name": contact.name, "identity_id": contact.identity_id},
            "diagnostics": {
                "message_count": len(exported_messages),
                "pending_messages": pending_messages,
                "pending_controls": pending_controls,
                "native_transport_active": bool(getattr(self.sam, "native_active", False)),
                "last_protocol_event": self.last_protocol_event,
                "delay_notes": {
                    "one_way_clock_dependent": "Dipende dalla sincronizzazione degli orologi dei due dispositivi.",
                    "round_trip_local_clock": "Calcolato interamente con l'orologio del mittente.",
                },
            },
            "messages": exported_messages,
        }
        return json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)

    def delete_message(self, message_id: str) -> bool:
        """Delete one local copy and cancel its pending delivery, if any."""
        if not message_id:
            return False
        transfer_id = ""
        total_chunks = 0
        with self._state_lock:
            transfer = next((item for item in self.vault.state.setdefault("attachment_transfers", {}).values() if item.get("message_id") == message_id), None)
            if isinstance(transfer, dict):
                transfer_id = str(transfer.get("transfer_id", ""))
                total_chunks = int(dict(transfer.get("attachment") or {}).get("total_chunks", 0))
        if transfer_id and isinstance(transfer, dict) and transfer.get("state") not in {"complete", "cancelled"}:
            self.cancel_attachment(message_id)
        with self._state_lock:
            before = len(self.vault.state["messages"])
            self.vault.state["messages"] = [
                message for message in self.vault.state["messages"]
                if message.get("message_id") != message_id
            ]
            self.vault.state["outbox"] = [
                entry for entry in self.vault.state["outbox"]
                if entry.get("message_id") != message_id and entry.get("attachment_transfer_id") != transfer_id
            ]
            if transfer_id:
                self.vault.state.setdefault("attachment_transfers", {}).pop(transfer_id, None)
            changed = len(self.vault.state["messages"]) != before
            if changed:
                self.vault.save()
        if transfer_id:
            self._delete_attachment_chunks(transfer_id, total_chunks)
        return changed

    def forward_message(self, contact_id: str, text: str) -> str:
        # Forwarding creates a fresh envelope, message id, KEM secret and nonce.
        # No original sender or conversation metadata is attached.
        if not text.strip():
            raise ValueError("Messaggio vuoto")
        return self.send_message(contact_id, text)

    def send_message(self, contact_id: str, text: str) -> str:
        text = text.strip()
        if not text:
            raise ValueError("Messaggio vuoto")
        return self._send_user_payload(
            contact_id,
            {"kind": "message", "text": text},
            text=text,
        )

    def send_attachment(
        self,
        contact_id: str,
        filename: str,
        data: bytes,
        mime_type: str = "",
    ) -> str:
        if not isinstance(data, bytes):
            raise ValueError("Dati allegato non validi")
        guessed_mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        normalized_mime = (mime_type or guessed_mime).lower()
        self._validate_attachment_size(len(data), normalized_mime)
        chunks = (data[offset:offset + ATTACHMENT_CHUNK_BYTES] for offset in range(0, len(data), ATTACHMENT_CHUNK_BYTES))
        preview = data if normalized_mime.startswith("image/") and len(data) <= MAX_INLINE_IMAGE_BYTES else None
        return self._create_attachment_transfer(
            contact_id, filename, normalized_mime, len(data), hashlib.sha256(data).hexdigest(), chunks, preview,
        )

    def send_attachment_file(self, contact_id: str, path: Path) -> str:
        source = Path(path)
        size = source.stat().st_size
        mime_type = (mimetypes.guess_type(source.name)[0] or "application/octet-stream").lower()
        self._validate_attachment_size(size, mime_type)
        digest = hashlib.sha256()
        with source.open("rb") as stream:
            while block := stream.read(ATTACHMENT_CHUNK_BYTES):
                digest.update(block)
        preview = source.read_bytes() if mime_type.startswith("image/") and size <= MAX_INLINE_IMAGE_BYTES else None

        def chunks() -> Iterable[bytes]:
            with source.open("rb") as stream:
                while block := stream.read(ATTACHMENT_CHUNK_BYTES):
                    yield block

        return self._create_attachment_transfer(
            contact_id, source.name, mime_type, size, digest.hexdigest(), chunks(), preview,
        )

    @staticmethod
    def _validate_attachment_size(size: int, mime_type: str) -> None:
        if size <= 0:
            raise ValueError("Il file è vuoto")
        limit = _attachment_limit(mime_type)
        if size > limit:
            label = "100 MB" if mime_type.startswith("video/") else "25 MB"
            raise ValueError(f"Il file supera il limite di {label}")

    def _create_attachment_transfer(
        self,
        contact_id: str,
        filename: str,
        mime_type: str,
        size: int,
        digest: str,
        chunks: Iterable[bytes],
        preview: bytes | None = None,
    ) -> str:
        identity = self.identity()
        if not identity:
            raise RuntimeError("Identità non configurata")
        contact = IdentityBundle.from_dict(self.vault.state["contacts"][contact_id])
        transfer_id = uuid.uuid4().hex
        message_id = uuid.uuid4().hex
        total_chunks = (size + ATTACHMENT_CHUNK_BYTES - 1) // ATTACHMENT_CHUNK_BYTES
        metadata = _normalize_attachment_metadata({
            "name": filename, "mime": mime_type, "size": size, "sha256": digest,
            "total_chunks": total_chunks,
        })
        storage_key = os.urandom(32)
        written = 0
        chunk_count = 0
        stored_digest = hashlib.sha256()
        try:
            for index, chunk in enumerate(chunks):
                if not chunk or len(chunk) > ATTACHMENT_CHUNK_BYTES:
                    raise ValueError("Blocco allegato non valido")
                self._write_attachment_chunk(transfer_id, index, storage_key, bytes(chunk))
                written += len(chunk)
                chunk_count = index + 1
                stored_digest.update(chunk)
            if written != size or chunk_count != total_chunks or stored_digest.hexdigest() != digest:
                raise ValueError("File modificato durante la preparazione")
        except Exception:
            self._delete_attachment_chunks(transfer_id, total_chunks)
            raise
        attachment = {
            **metadata, "transfer_id": transfer_id, "state": "transferring",
            "progress": 0, "completed_chunks": 0,
        }
        if preview is not None:
            attachment["data"] = base64.b64encode(preview).decode("ascii")
        now = int(time.time())
        transfer = {
            "transfer_id": transfer_id, "message_id": message_id, "contact_id": contact_id,
            "destination": contact.destination, "direction": "out", "attachment": metadata,
            "storage_key": b64(storage_key), "manifest_acked": False, "completed_chunks": 0,
            "active_message_id": "", "active_phase": "", "active_index": -1,
            "paused": False, "state": "transferring", "created_at": now,
        }
        message = {
            "message_id": message_id, "contact_id": contact_id, "direction": "out",
            "kind": "attachment", "text": str(metadata["name"]), "time": now, "sent_at": now,
            "received_at": None, "delivered_at": None, "recipient_received_at": None,
            "read_at": None, "reactions": {}, "status": "pending", "attachment": attachment,
        }
        with self._state_lock:
            self.vault.state.setdefault("attachment_transfers", {})[transfer_id] = transfer
            self.vault.state["messages"].append(message)
            self.vault.save()
        if self.on_message:
            self.on_message("new", contact_id)
        return "sent" if self._queue_next_attachment_part(transfer_id, force=True) else "queued"

    def forward_attachment(self, contact_id: str, attachment: object) -> str:
        # Backward compatibility for attachments produced by pre-chunk releases.
        normalized = _normalize_attachment(attachment)
        return self._send_user_payload(
            contact_id,
            {"kind": "attachment", "attachment": normalized},
            text=str(normalized["name"]),
            attachment=normalized,
        )

    def forward_attachment_message(self, contact_id: str, message_id: str) -> str:
        metadata, data = self.attachment_content(message_id)
        return self.send_attachment(contact_id, str(metadata["name"]), data, str(metadata["mime"]))

    def attachment_content(self, message_id: str) -> tuple[dict[str, object], bytes]:
        with self._state_lock:
            message = next(
                (item for item in self.vault.state.get("messages", []) if item.get("message_id") == message_id),
                None,
            )
            if not message or message.get("kind") != "attachment":
                raise ValueError("Allegato non trovato")
            raw_attachment = copy.deepcopy(message.get("attachment"))
            if isinstance(raw_attachment, dict) and not raw_attachment.get("transfer_id"):
                attachment = _normalize_attachment(raw_attachment)
                return attachment, base64.b64decode(str(attachment["data"]).encode("ascii"), validate=True)
            transfer_id = str(dict(raw_attachment or {}).get("transfer_id", ""))
            transfer = copy.deepcopy(self.vault.state.setdefault("attachment_transfers", {}).get(transfer_id))
        if not transfer:
            raise ValueError("Trasferimento allegato non trovato")
        metadata = _normalize_attachment_metadata(transfer.get("attachment"))
        if transfer.get("direction") == "in" and transfer.get("state") != "complete":
            raise ValueError("Download dell’allegato non completato")
        data = b"".join(self._read_attachment_chunk(transfer, index) for index in range(int(metadata["total_chunks"])))
        if len(data) != metadata["size"] or hashlib.sha256(data).hexdigest() != metadata["sha256"]:
            raise ValueError("Verifica SHA-256 dell’allegato non riuscita")
        return metadata, data

    def attachment_metadata(self, message_id: str) -> dict[str, object]:
        with self._state_lock:
            message = next((item for item in self.vault.state.get("messages", []) if item.get("message_id") == message_id), None)
            attachment = copy.deepcopy(message.get("attachment")) if message else None
            if not isinstance(attachment, dict):
                raise ValueError("Allegato non trovato")
            transfer_id = str(attachment.get("transfer_id", ""))
            if transfer_id:
                transfer = self.vault.state.setdefault("attachment_transfers", {}).get(transfer_id)
                if not isinstance(transfer, dict):
                    raise ValueError("Trasferimento allegato non trovato")
                return _normalize_attachment_metadata(transfer.get("attachment"))
        legacy = _normalize_attachment(attachment)
        return {key: legacy[key] for key in ("name", "mime", "size", "sha256")}

    def save_attachment_to(self, message_id: str, destination: Path) -> Path:
        with self._state_lock:
            message = next((item for item in self.vault.state.get("messages", []) if item.get("message_id") == message_id), None)
            raw_attachment = copy.deepcopy(message.get("attachment")) if message else None
            transfer_id = str(dict(raw_attachment or {}).get("transfer_id", ""))
            transfer = copy.deepcopy(self.vault.state.setdefault("attachment_transfers", {}).get(transfer_id))
        if not transfer:
            _metadata, data = self.attachment_content(message_id)
            Path(destination).write_bytes(data)
            return Path(destination)
        metadata = _normalize_attachment_metadata(transfer.get("attachment"))
        if transfer.get("direction") == "in" and transfer.get("state") != "complete":
            raise ValueError("Download dell’allegato non completato")
        target = Path(destination)
        temporary = target.with_name(target.name + ".kerberus-part")
        digest = hashlib.sha256()
        written = 0
        with temporary.open("wb") as stream:
            for index in range(int(metadata["total_chunks"])):
                chunk = self._read_attachment_chunk(transfer, index)
                stream.write(chunk)
                digest.update(chunk)
                written += len(chunk)
        if written != metadata["size"] or digest.hexdigest() != metadata["sha256"]:
            temporary.unlink(missing_ok=True)
            raise ValueError("Verifica SHA-256 dell’allegato non riuscita")
        os.replace(temporary, target)
        return target

    def _attachment_chunk_path(self, transfer_id: str, index: int) -> Path:
        if len(transfer_id) != 32 or any(character not in "0123456789abcdef" for character in transfer_id):
            raise ValueError("ID trasferimento non valido")
        return self._attachment_store / f"{transfer_id}-{index:04d}.kac"

    def _write_attachment_chunk(self, transfer_id: str, index: int, key: bytes, data: bytes) -> None:
        path = self._attachment_chunk_path(transfer_id, index)
        path.parent.mkdir(parents=True, exist_ok=True)
        nonce = os.urandom(24)
        associated = f"kerberus-attachment:{transfer_id}:{index}".encode("ascii")
        ciphertext = crypto_aead_xchacha20poly1305_ietf_encrypt(data, associated, nonce, key)
        temporary = path.with_suffix(".tmp")
        temporary.write_bytes(nonce + ciphertext)
        os.replace(temporary, path)

    def _read_attachment_chunk(self, transfer: dict, index: int) -> bytes:
        transfer_id = str(transfer.get("transfer_id", ""))
        raw = self._attachment_chunk_path(transfer_id, index).read_bytes()
        if len(raw) < 40:
            raise ValueError("Blocco allegato danneggiato")
        associated = f"kerberus-attachment:{transfer_id}:{index}".encode("ascii")
        return crypto_aead_xchacha20poly1305_ietf_decrypt(
            raw[24:], associated, raw[:24], unb64(str(transfer.get("storage_key", ""))),
        )

    def _delete_attachment_chunks(self, transfer_id: str, total_chunks: int) -> None:
        for index in range(max(0, total_chunks)):
            self._attachment_chunk_path(transfer_id, index).unlink(missing_ok=True)

    def _queue_next_attachment_part(self, transfer_id: str, force: bool = False) -> bool:
        contact: IdentityBundle | None = None
        existing_message_id = ""
        with self._state_lock:
            transfer = self.vault.state.setdefault("attachment_transfers", {}).get(transfer_id)
            if not isinstance(transfer, dict):
                return False
            if transfer.get("state") in {"complete", "cancelled", "failed"}:
                return True
            active_message_id = str(transfer.get("active_message_id", ""))
            if active_message_id:
                entry = next((item for item in self.vault.state["outbox"] if item.get("message_id") == active_message_id), None)
                if entry:
                    if force:
                        entry["paused"] = False
                        entry["last_attempt"] = 0
                        self.vault.save()
                    existing_message_id = active_message_id
                else:
                    transfer["active_message_id"] = ""
        if existing_message_id:
            return self._attempt_outbox(existing_message_id, force=force)
        with self._state_lock:
            transfer = self.vault.state.setdefault("attachment_transfers", {}).get(transfer_id)
            if not isinstance(transfer, dict) or transfer.get("active_message_id"):
                return False
            if transfer.get("paused"):
                return False
            metadata = _normalize_attachment_metadata(transfer.get("attachment"))
            contact_data = self.vault.state.get("contacts", {}).get(transfer.get("contact_id"))
            if not contact_data:
                return False
            contact = IdentityBundle.from_dict(contact_data)
            if not transfer.get("manifest_acked"):
                phase = "manifest"
                index = -1
                clear = {
                    "kind": "attachment_manifest", "transfer_id": transfer_id,
                    "chat_message_id": str(transfer.get("message_id", "")), "attachment": metadata,
                }
            else:
                index = int(transfer.get("completed_chunks", 0))
                if index >= int(metadata["total_chunks"]):
                    self._complete_outgoing_attachment_locked(transfer)
                    self.vault.save()
                    return True
                phase = "chunk"
                raw_chunk = self._read_attachment_chunk(transfer, index)
                clear = {
                    "kind": "attachment_chunk", "transfer_id": transfer_id, "index": index,
                    "data": base64.b64encode(raw_chunk).decode("ascii"),
                    "sha256": hashlib.sha256(raw_chunk).hexdigest(),
                }
            protocol_message_id = uuid.uuid4().hex
            ready = ratchet_is_ready(self.vault.state.setdefault("ratchets", {}), contact.identity_id)
            envelope = self._seal_ratchet(contact, clear, message_id=protocol_message_id) if ready else None
            payload = json.dumps(envelope, separators=(",", ":")) if envelope else ""
            self.vault.state["outbox"].append({
                "message_id": protocol_message_id, "contact_id": contact.identity_id,
                "destination": contact.destination, "payload": payload,
                "deferred": None if envelope else clear, "created_at": int(time.time()),
                "last_attempt": 0, "attempts": 0, "attachment_transfer_id": transfer_id,
                "attachment_phase": phase, "attachment_index": index, "paused": False,
            })
            transfer["active_message_id"] = protocol_message_id
            transfer["active_phase"] = phase
            transfer["active_index"] = index
            self.vault.save()
        if contact is not None and not ready:
            self._ensure_ratchet_handshake(contact)
        return self._attempt_outbox(protocol_message_id, force=True)

    def _complete_outgoing_attachment_locked(self, transfer: dict) -> None:
        transfer["state"] = "complete"
        transfer["paused"] = False
        message = next((item for item in self.vault.state.get("messages", []) if item.get("message_id") == transfer.get("message_id")), None)
        if message:
            if message.get("status") != "read":
                message["status"] = "delivered"
            message["delivered_at"] = int(time.time())
            attachment = message.get("attachment")
            if isinstance(attachment, dict):
                attachment.update({"state": "complete", "progress": 100, "completed_chunks": attachment.get("total_chunks", 0)})

    def _attachment_protocol_acked(self, transfer_id: str, protocol_message_id: str, received_at: object = None) -> None:
        contact_id = ""
        continue_transfer = False
        with self._state_lock:
            self._receipt_started_ns.pop(protocol_message_id, None)
            transfer = self.vault.state.setdefault("attachment_transfers", {}).get(transfer_id)
            if not isinstance(transfer, dict) or transfer.get("active_message_id") != protocol_message_id:
                return
            contact_id = str(transfer.get("contact_id", ""))
            phase = str(transfer.get("active_phase", ""))
            if phase == "manifest":
                transfer["manifest_acked"] = True
            elif phase == "chunk":
                transfer["completed_chunks"] = max(
                    int(transfer.get("completed_chunks", 0)), int(transfer.get("active_index", -1)) + 1,
                )
            transfer["active_message_id"] = ""
            transfer["active_phase"] = ""
            transfer["active_index"] = -1
            metadata = _normalize_attachment_metadata(transfer.get("attachment"))
            completed = int(transfer.get("completed_chunks", 0))
            message = next((item for item in self.vault.state.get("messages", []) if item.get("message_id") == transfer.get("message_id")), None)
            if message:
                message["status"] = "sent"
                attachment = message.get("attachment")
                if isinstance(attachment, dict):
                    attachment["completed_chunks"] = completed
                    attachment["progress"] = round(completed * 100 / int(metadata["total_chunks"]))
                    attachment["state"] = "paused" if transfer.get("paused") else "transferring"
            if completed >= int(metadata["total_chunks"]):
                self._complete_outgoing_attachment_locked(transfer)
                if message and isinstance(received_at, int):
                    message["recipient_received_at"] = received_at
            else:
                continue_transfer = not bool(transfer.get("paused")) and transfer.get("state") == "transferring"
            self.vault.save()
        if contact_id and self.on_message:
            self.on_message("status", contact_id)
        if continue_transfer:
            marker = f"{transfer_id}:{protocol_message_id}"
            self._submit_delivery("attachment", marker, self._queue_next_attachment_part, transfer_id)

    def set_attachment_paused(self, message_id: str, paused: bool) -> bool:
        transfer_id = ""
        contact: IdentityBundle | None = None
        active_message_id = ""
        direction = ""
        with self._state_lock:
            transfer = next((item for item in self.vault.state.setdefault("attachment_transfers", {}).values() if item.get("message_id") == message_id), None)
            if not isinstance(transfer, dict) or transfer.get("state") in {"complete", "cancelled", "failed"}:
                return False
            transfer_id = str(transfer.get("transfer_id", ""))
            direction = str(transfer.get("direction", ""))
            transfer["paused"] = paused
            active_message_id = str(transfer.get("active_message_id", ""))
            for entry in self.vault.state.get("outbox", []):
                if entry.get("message_id") == active_message_id:
                    entry["paused"] = paused
                    if not paused:
                        entry["last_attempt"] = 0
            message = next((item for item in self.vault.state.get("messages", []) if item.get("message_id") == message_id), None)
            if message and isinstance(message.get("attachment"), dict):
                message["attachment"]["state"] = "paused" if paused else "transferring"
            contact_data = self.vault.state.get("contacts", {}).get(transfer.get("contact_id"))
            contact = IdentityBundle.from_dict(contact_data) if contact_data else None
            self.vault.save()
        if direction == "in" and contact is not None:
            with self._state_lock:
                envelope = self._seal_ratchet(contact, {
                    "kind": "attachment_flow", "transfer_id": transfer_id,
                    "action": "pause" if paused else "resume",
                })
                self.vault.save()
            self._queue_control(contact.destination, envelope, background=True)
        if self.on_message and contact is not None:
            self.on_message("status", contact.identity_id)
        if not paused and direction == "out":
            if active_message_id:
                self._attempt_outbox(active_message_id, force=True)
            else:
                self._queue_next_attachment_part(transfer_id, force=True)
        return True

    def cancel_attachment(self, message_id: str) -> bool:
        transfer_id = ""
        contact: IdentityBundle | None = None
        total_chunks = 0
        with self._state_lock:
            transfer = next((item for item in self.vault.state.setdefault("attachment_transfers", {}).values() if item.get("message_id") == message_id), None)
            if not isinstance(transfer, dict) or transfer.get("state") in {"complete", "cancelled"}:
                return False
            transfer_id = str(transfer.get("transfer_id", ""))
            total_chunks = int(dict(transfer.get("attachment") or {}).get("total_chunks", 0))
            transfer["state"] = "cancelled"
            transfer["paused"] = False
            active = str(transfer.get("active_message_id", ""))
            self.vault.state["outbox"] = [item for item in self.vault.state.get("outbox", []) if item.get("message_id") != active]
            message = next((item for item in self.vault.state.get("messages", []) if item.get("message_id") == message_id), None)
            if message and isinstance(message.get("attachment"), dict):
                message["attachment"]["state"] = "cancelled"
            contact_data = self.vault.state.get("contacts", {}).get(transfer.get("contact_id"))
            contact = IdentityBundle.from_dict(contact_data) if contact_data else None
            self.vault.save()
        # A cancelled transfer cannot be resumed, so its encrypted spool no
        # longer serves a purpose on either side of the conversation.
        self._delete_attachment_chunks(transfer_id, total_chunks)
        if contact is not None and ratchet_is_ready(self.vault.state.setdefault("ratchets", {}), contact.identity_id):
            with self._state_lock:
                envelope = self._seal_ratchet(contact, {"kind": "attachment_cancel", "transfer_id": transfer_id})
                self.vault.save()
            self._queue_control(contact.destination, envelope, background=True)
            if self.on_message:
                self.on_message("status", contact.identity_id)
        return True

    def send_voice(
        self,
        contact_id: str,
        pcm: bytes,
        *,
        sample_rate: int,
        channels: int,
        sample_format: str,
    ) -> str:
        codec = self._voice_codec or NativeVoiceCodec()
        self._voice_codec = codec
        voice, metrics = codec.encode(
            pcm,
            sample_rate=sample_rate,
            channels=channels,
            sample_format=sample_format,
        )
        return self._send_user_payload(
            contact_id,
            {"kind": "voice", "voice": voice},
            text="Messaggio vocale",
            voice=voice,
            voice_metrics=metrics,
        )

    def forward_voice(self, contact_id: str, voice: object) -> str:
        normalized = validate_voice_payload(voice)
        return self._send_user_payload(
            contact_id,
            {"kind": "voice", "voice": normalized},
            text="Messaggio vocale inoltrato",
            voice=normalized,
        )

    def decode_voice(self, message_id: str) -> bytes:
        with self._state_lock:
            message = next(
                (item for item in self.vault.state.get("messages", []) if item.get("message_id") == message_id),
                None,
            )
            if not message or message.get("kind") != "voice":
                raise ValueError("Messaggio vocale non trovato")
            voice = copy.deepcopy(message.get("voice"))
        codec = self._voice_codec or NativeVoiceCodec()
        self._voice_codec = codec
        pcm, metrics = codec.decode(voice)
        with self._state_lock:
            message["voice_metrics"] = {**dict(message.get("voice_metrics") or {}), **metrics}
            self.vault.save()
        return pcm_to_wav(pcm)

    def _send_user_payload(
        self,
        contact_id: str,
        clear: dict,
        *,
        text: str,
        voice: dict | None = None,
        voice_metrics: dict | None = None,
        attachment: dict[str, object] | None = None,
    ) -> str:
        identity = self.identity()
        if not identity:
            raise RuntimeError("Identità non configurata")
        contact = IdentityBundle.from_dict(self.vault.state["contacts"][contact_id])
        message_id = uuid.uuid4().hex
        with self._state_lock:
            ready = ratchet_is_ready(self.vault.state.setdefault("ratchets", {}), contact_id)
            envelope = self._seal_ratchet(contact, clear, message_id=message_id) if ready else None
        payload = json.dumps(envelope, separators=(",", ":")) if envelope else ""
        now = int(time.time())
        kind = str(clear.get("kind", "message"))
        stored_message = {
            "message_id": message_id,
            "contact_id": contact_id,
            "direction": "out",
            "kind": kind,
            "text": text,
            "time": now,
            "sent_at": now,
            "received_at": None,
            "delivered_at": None,
            "recipient_received_at": None,
            "read_at": None,
            "reactions": {},
            "status": "pending",
        }
        if voice is not None:
            stored_message["voice"] = copy.deepcopy(voice)
        if voice_metrics is not None:
            stored_message["voice_metrics"] = copy.deepcopy(voice_metrics)
        if attachment is not None:
            stored_message["attachment"] = copy.deepcopy(attachment)
        with self._state_lock:
            self.vault.state["messages"].append(stored_message)
            self.vault.state["outbox"].append({
                "message_id": message_id,
                "contact_id": contact_id,
                "destination": contact.destination,
                "payload": payload,
                "deferred": None if envelope else copy.deepcopy(clear),
                "created_at": now,
                "last_attempt": 0,
                "attempts": 0,
            })
            self.vault.state["outbox"] = self.vault.state["outbox"][-10_000:]
            self.vault.save()
        if not ready:
            self._ensure_ratchet_handshake(contact)
        if self.on_message:
            self.on_message("new", contact_id)
        sent = self._attempt_outbox(message_id, force=True)
        return "sent" if sent else "queued"

    def react_to_message(self, contact_id: str, message_id: str, emoji: str) -> None:
        if not emoji_data.is_emoji(emoji) or len(emoji) > 32:
            raise ValueError("Reazione non valida")
        contact = IdentityBundle.from_dict(self.vault.state["contacts"][contact_id])
        target = next((m for m in self.vault.state["messages"] if m.get("message_id") == message_id), None)
        if not target or target.get("contact_id") != contact_id:
            raise ValueError("Messaggio non trovato")
        identity = self.identity()
        if not identity:
            raise RuntimeError("Identità non configurata")
        with self._state_lock:
            reactions = target.setdefault("reactions", {})
            if not isinstance(reactions, dict):
                reactions = {}
                target["reactions"] = reactions
            own_reactions = _reaction_values(reactions.get(identity.identity_id))
            remove = emoji in own_reactions
            if remove:
                own_reactions.remove(emoji)
            else:
                if len(own_reactions) >= 12:
                    raise ValueError("Puoi aggiungere al massimo 12 reazioni per messaggio")
                own_reactions.append(emoji)
            if own_reactions:
                reactions[identity.identity_id] = own_reactions
            else:
                reactions.pop(identity.identity_id, None)
            self.vault.save()
        with self._state_lock:
            envelope = self._seal_ratchet(contact, {
                "kind": "reaction", "target_id": message_id,
                "emoji": emoji, "remove": remove,
            })
            self.vault.save()
        self._queue_control(contact.destination, envelope, background=True)
        if self.on_message:
            self.on_message("status", contact_id)

    def mark_chat_read(self, contact_id: str) -> int:
        identity = self.identity()
        contact_data = self.vault.state.get("contacts", {}).get(contact_id)
        if not identity or not contact_data:
            return 0
        unread: list[str] = []
        with self._state_lock:
            for message in self.vault.state.get("messages", []):
                if message.get("contact_id") == contact_id and message.get("direction") == "in" and not message.get("read_at"):
                    message["read_at"] = int(time.time())
                    unread.append(str(message.get("message_id", "")))
            if unread:
                self.vault.save()
        if unread and self._privacy_enabled(contact_id, "send_read_receipts"):
            contact = IdentityBundle.from_dict(contact_data)
            with self._state_lock:
                envelope = self._seal_ratchet(contact, {
                    "kind": "read", "message_ids": unread[-100:],
                })
                self.vault.save()
            self._queue_control(contact.destination, envelope, background=True)
        return len(unread)

    def _seal_ratchet(self, contact: IdentityBundle, payload: dict, *, message_id: str | None = None) -> dict:
        identity = self.identity()
        if not identity:
            raise RuntimeError("Identità non configurata")
        states = self.vault.state.setdefault("ratchets", {})
        working = copy.deepcopy(states)
        inner = ratchet_encrypt(working, identity, self.secrets(), contact, payload)
        envelope = seal_payload(
            identity, self.secrets(), contact, {"kind": "ratchet", **inner}, message_id=message_id
        )
        states[contact.identity_id] = working[contact.identity_id]
        return envelope

    def _send_ratchet_handshake(
        self, contact: IdentityBundle, action: str, header: dict | None = None, *, background: bool = False
    ) -> None:
        identity = self.identity()
        if not identity:
            return
        envelope = seal_payload(identity, self.secrets(), contact, {
            "kind": "ratchet_handshake", "action": action, "header": header or {},
        })
        self._queue_control(contact.destination, envelope, background=background)

    def _ensure_ratchet_handshake(self, contact: IdentityBundle) -> None:
        identity = self.identity()
        if not identity:
            return
        with self._state_lock:
            states = self.vault.state.setdefault("ratchets", {})
            if ratchet_is_ready(states, contact.identity_id):
                return
            state = states.get(contact.identity_id, {})
            if identity.identity_id < contact.identity_id:
                header = ratchet_initiate(states, identity, self.secrets(), contact)
                self.vault.save()
                action = "init"
            elif not state.get("nudge_sent"):
                state = states.setdefault(contact.identity_id, state)
                state["nudge_sent"] = True
                self.vault.save()
                header, action = {}, "nudge"
            else:
                return
        if header is not None:
            self._send_ratchet_handshake(contact, action, header)

    def _receive_ratchet_handshake(self, sender: IdentityBundle, clear: dict) -> None:
        identity = self.identity()
        if not identity:
            return
        action = clear.get("action")
        header = clear.get("header")
        if not isinstance(header, dict):
            raise ValueError("Header handshake ratchet non valido")
        reply: tuple[str, dict] | None = None
        with self._state_lock:
            states = self.vault.state.setdefault("ratchets", {})
            if action == "nudge":
                if identity.identity_id < sender.identity_id:
                    init = ratchet_initiate(states, identity, self.secrets(), sender)
                    if init is not None:
                        reply = ("init", init)
            elif action == "init":
                reply = ("ready", ratchet_accept_init(states, identity, self.secrets(), sender, header))
            elif action == "ready":
                ratchet_complete_init(states, identity, self.secrets(), sender, header)
            else:
                raise ValueError("Azione handshake ratchet non valida")
            self.vault.save()
        if reply:
            self._send_ratchet_handshake(sender, *reply)
        if action in {"init", "ready"}:
            self.flush_outbox(background=True)

    def _remember_attachment_protocol(self, message_id: str, received_at: int) -> None:
        seen = self.vault.state.setdefault("attachment_seen", {})
        seen[message_id] = received_at
        while len(seen) > 10_000:
            seen.pop(next(iter(seen)))
        self.vault.state["seen"].append(message_id)
        self.vault.state["seen"] = self.vault.state["seen"][-10_000:]

    def _receive_attachment_manifest(self, sender_id: str, clear: dict, message_id: str, received_at: int) -> bool:
        transfer_id = str(clear.get("transfer_id", ""))
        chat_message_id = str(clear.get("chat_message_id", ""))
        if any(len(value) != 32 or any(character not in "0123456789abcdef" for character in value) for value in (transfer_id, chat_message_id)):
            return False
        try:
            metadata = _normalize_attachment_metadata(clear.get("attachment"))
        except ValueError:
            return False
        with self._state_lock:
            transfers = self.vault.state.setdefault("attachment_transfers", {})
            if transfer_id in transfers or any(item.get("message_id") == chat_message_id for item in self.vault.state.get("messages", [])):
                return False
            attachment = {
                **metadata, "transfer_id": transfer_id, "state": "transferring",
                "progress": 0, "completed_chunks": 0,
            }
            transfer = {
                "transfer_id": transfer_id, "message_id": chat_message_id, "contact_id": sender_id,
                "direction": "in", "attachment": metadata, "storage_key": b64(os.urandom(32)),
                "received_chunks": [], "paused": False, "state": "transferring",
                "created_at": received_at,
            }
            transfers[transfer_id] = transfer
            self.vault.state["messages"].append({
                "message_id": chat_message_id, "contact_id": sender_id, "direction": "in",
                "kind": "attachment", "text": str(metadata["name"]),
                "time": int(clear.get("sent_at", received_at)), "sent_at": int(clear.get("sent_at", received_at)),
                "received_at": received_at, "delivered_at": None, "recipient_received_at": None,
                "read_at": None, "reactions": {}, "status": "receiving", "attachment": attachment,
            })
            self._remember_attachment_protocol(message_id, received_at)
            self.vault.save()
        self._emit_protocol_event("attachment_manifest_received", f"Download cifrato avviato: {metadata['name']}")
        if self.on_message:
            self.on_message("new", sender_id)
        return True

    def _receive_attachment_chunk(self, sender_id: str, clear: dict, message_id: str, received_at: int) -> bool:
        transfer_id = str(clear.get("transfer_id", ""))
        try:
            index = int(clear.get("index", -1))
            encoded = str(clear.get("data", "")).encode("ascii")
            raw_chunk = base64.b64decode(encoded, validate=True)
        except (TypeError, ValueError, UnicodeEncodeError):
            return False
        digest = str(clear.get("sha256", ""))
        if not raw_chunk or len(raw_chunk) > ATTACHMENT_CHUNK_BYTES or not hmac.compare_digest(hashlib.sha256(raw_chunk).hexdigest(), digest):
            return False
        with self._state_lock:
            transfer = self.vault.state.setdefault("attachment_transfers", {}).get(transfer_id)
            if not isinstance(transfer, dict) or transfer.get("direction") != "in" or transfer.get("contact_id") != sender_id:
                return False
            if transfer.get("state") in {"cancelled", "failed", "complete"}:
                return False
            metadata = _normalize_attachment_metadata(transfer.get("attachment"))
            total_chunks = int(metadata["total_chunks"])
            if index < 0 or index >= total_chunks:
                return False
            expected_size = ATTACHMENT_CHUNK_BYTES if index < total_chunks - 1 else int(metadata["size"]) - ATTACHMENT_CHUNK_BYTES * (total_chunks - 1)
            if len(raw_chunk) != expected_size:
                return False
            received = {int(value) for value in transfer.get("received_chunks", [])}
            if index not in received:
                self._write_attachment_chunk(transfer_id, index, unb64(str(transfer["storage_key"])), raw_chunk)
                received.add(index)
            transfer["received_chunks"] = sorted(received)
            completed = len(received)
            message = next((item for item in self.vault.state.get("messages", []) if item.get("message_id") == transfer.get("message_id")), None)
            state = "paused" if transfer.get("paused") else "transferring"
            if completed == total_chunks:
                try:
                    full_digest = hashlib.sha256()
                    assembled_size = 0
                    preview_parts: list[bytes] = []
                    keep_preview = str(metadata["mime"]).startswith("image/") and int(metadata["size"]) <= MAX_INLINE_IMAGE_BYTES
                    for chunk_index in range(total_chunks):
                        block = self._read_attachment_chunk(transfer, chunk_index)
                        full_digest.update(block)
                        assembled_size += len(block)
                        if keep_preview:
                            preview_parts.append(block)
                    if assembled_size != metadata["size"] or full_digest.hexdigest() != metadata["sha256"]:
                        raise ValueError("SHA-256 non valido")
                    state = "complete"
                    transfer["state"] = "complete"
                    if message and keep_preview and isinstance(message.get("attachment"), dict):
                        message["attachment"]["data"] = base64.b64encode(b"".join(preview_parts)).decode("ascii")
                except Exception:
                    state = "failed"
                    transfer["state"] = "failed"
            if message and isinstance(message.get("attachment"), dict):
                message["attachment"].update({
                    "completed_chunks": completed, "progress": round(completed * 100 / total_chunks), "state": state,
                })
                message["status"] = "received" if state == "complete" else state
            self._remember_attachment_protocol(message_id, received_at)
            self.vault.save()
        if self.on_message:
            self.on_message("status", sender_id)
        return state != "failed"

    def _receive_attachment_flow(self, sender_id: str, clear: dict) -> None:
        transfer_id = str(clear.get("transfer_id", ""))
        action = str(clear.get("action", ""))
        if action not in {"pause", "resume"}:
            return
        active_message_id = ""
        with self._state_lock:
            transfer = self.vault.state.setdefault("attachment_transfers", {}).get(transfer_id)
            if not isinstance(transfer, dict) or transfer.get("direction") != "out" or transfer.get("contact_id") != sender_id:
                return
            paused = action == "pause"
            transfer["paused"] = paused
            active_message_id = str(transfer.get("active_message_id", ""))
            for entry in self.vault.state.get("outbox", []):
                if entry.get("message_id") == active_message_id:
                    entry["paused"] = paused
                    if not paused:
                        entry["last_attempt"] = 0
            message = next((item for item in self.vault.state.get("messages", []) if item.get("message_id") == transfer.get("message_id")), None)
            if message and isinstance(message.get("attachment"), dict):
                message["attachment"]["state"] = "paused" if paused else "transferring"
            self.vault.save()
        if self.on_message:
            self.on_message("status", sender_id)
        if action == "resume":
            if active_message_id:
                self._attempt_outbox(active_message_id, force=True)
            else:
                self._queue_next_attachment_part(transfer_id, force=True)

    def _receive_attachment_cancel(self, sender_id: str, clear: dict) -> None:
        transfer_id = str(clear.get("transfer_id", ""))
        total_chunks = 0
        with self._state_lock:
            transfer = self.vault.state.setdefault("attachment_transfers", {}).get(transfer_id)
            if not isinstance(transfer, dict) or transfer.get("contact_id") != sender_id:
                return
            total_chunks = int(dict(transfer.get("attachment") or {}).get("total_chunks", 0))
            transfer["state"] = "cancelled"
            active = str(transfer.get("active_message_id", ""))
            self.vault.state["outbox"] = [item for item in self.vault.state.get("outbox", []) if item.get("message_id") != active]
            message = next((item for item in self.vault.state.get("messages", []) if item.get("message_id") == transfer.get("message_id")), None)
            if message and isinstance(message.get("attachment"), dict):
                message["attachment"]["state"] = "cancelled"
            self.vault.save()
        self._delete_attachment_chunks(transfer_id, total_chunks)
        if self.on_message:
            self.on_message("status", sender_id)

    def _receive(self, payload: bytes, remote_destination: str = "", inline_reply: bool = False) -> bytes | None:
        envelope = json.loads(payload.decode("utf-8"))
        message_type = envelope.get("type")
        if message_type == "contact_request":
            try:
                destination, response = self._receive_contact_request(envelope, remote_destination)
                if inline_reply:
                    self._emit_protocol_event(
                        "contact_accept_inline", "Conferma contatto restituita sullo stesso stream I2P"
                    )
                    return json.dumps(response, separators=(",", ":")).encode("utf-8")
                self._queue_control(destination, response, background=False)
                self._emit_protocol_event("contact_accept_queued", "Conferma contatto inserita nella coda I2P")
            except Exception as exc:
                self._emit_protocol_event("contact_request_rejected", str(exc))
                self._send_contact_reject(envelope, str(exc))
            return
        if message_type == "contact_accept":
            self._receive_contact_accept(envelope, remote_destination)
            return
        if message_type == "contact_reject":
            self._receive_contact_reject(envelope, remote_destination)
            return
        if message_type == "profile_update":
            self._receive_profile_update(envelope)
            return
        if message_type == "message_ack":
            self._receive_message_ack(envelope)
            return
        if message_type != "message":
            return
        message_id = envelope.get("message_id", "")
        if not isinstance(message_id, str) or len(message_id) != 32:
            return
        sender_id = envelope.get("sender_id", "")
        contact_data = self.vault.state["contacts"].get(sender_id)
        identity = self.identity()
        if not contact_data or not identity:
            return
        sender = IdentityBundle.from_dict(contact_data)
        with self._state_lock:
            duplicate = message_id in self.vault.state["seen"]
        if duplicate:
            stored = next(
                (message for message in self.vault.state["messages"] if message.get("message_id") == message_id),
                {},
            )
            protocol_received_at = self.vault.state.setdefault("attachment_seen", {}).get(message_id)
            if not stored and not isinstance(protocol_received_at, int):
                return None
            received_at = int(stored.get("received_at") or time.time()) if stored else int(protocol_received_at)
            protocol_ack = isinstance(protocol_received_at, int)
            if protocol_ack or self._privacy_enabled(sender_id, "send_delivery_receipts"):
                if inline_reply:
                    return self._message_ack_payload(sender, message_id, received_at)
                self._send_message_ack(sender, message_id, received_at)
            return None
        clear = open_message_payload(identity, self.secrets(), sender, envelope)
        received_at = int(time.time())
        kind = clear.get("kind", "message")
        if kind == "ratchet_handshake":
            with self._state_lock:
                self.vault.state["seen"].append(message_id)
                self.vault.state["seen"] = self.vault.state["seen"][-10000:]
                self.vault.save()
            self._receive_ratchet_handshake(sender, clear)
            return None
        if kind == "ratchet":
            with self._state_lock:
                clear = ratchet_decrypt(
                    self.vault.state.setdefault("ratchets", {}), identity, self.secrets(), sender, clear
                )
                self.vault.save()
            kind = clear.get("kind", "")
        if kind == "delivery":
            with self._state_lock:
                self.vault.state["seen"].append(message_id)
                self.vault.state["seen"] = self.vault.state["seen"][-10000:]
            self._receive_encrypted_delivery(sender_id, clear)
            return None
        if kind == "read":
            with self._state_lock:
                self.vault.state["seen"].append(message_id)
                self.vault.state["seen"] = self.vault.state["seen"][-10000:]
            self._receive_read_receipt(sender_id, clear)
            return None
        if kind == "reaction":
            with self._state_lock:
                self.vault.state["seen"].append(message_id)
                self.vault.state["seen"] = self.vault.state["seen"][-10000:]
            self._receive_reaction(sender_id, clear)
            return None
        if kind == "identity_visibility":
            with self._state_lock:
                self.vault.state["seen"].append(message_id)
                self.vault.state["seen"] = self.vault.state["seen"][-10000:]
            self._receive_identity_visibility(sender_id, clear)
            return None
        if kind == "attachment_flow":
            with self._state_lock:
                self.vault.state["seen"].append(message_id)
                self.vault.state["seen"] = self.vault.state["seen"][-10000:]
                self.vault.save()
            self._receive_attachment_flow(sender_id, clear)
            return None
        if kind == "attachment_cancel":
            with self._state_lock:
                self.vault.state["seen"].append(message_id)
                self.vault.state["seen"] = self.vault.state["seen"][-10000:]
                self.vault.save()
            self._receive_attachment_cancel(sender_id, clear)
            return None
        if kind in {"attachment_manifest", "attachment_chunk"}:
            accepted = self._receive_attachment_manifest(sender_id, clear, message_id, received_at) \
                if kind == "attachment_manifest" else self._receive_attachment_chunk(sender_id, clear, message_id, received_at)
            if not accepted:
                return None
            if inline_reply:
                return self._message_ack_payload(sender, message_id, received_at)
            self._send_message_ack(sender, message_id, received_at)
            return None
        if kind not in {"message", "voice", "attachment"}:
            return None
        voice = None
        attachment = None
        text = ""
        if kind == "voice":
            try:
                voice = validate_voice_payload(clear.get("voice"))
            except ValueError:
                return None
            text = "Messaggio vocale"
        elif kind == "attachment":
            try:
                attachment = _normalize_attachment(clear.get("attachment"))
            except ValueError:
                return None
            text = str(attachment["name"])
        else:
            text = str(clear["text"])
        with self._state_lock:
            self.vault.state["seen"].append(message_id)
            self.vault.state["seen"] = self.vault.state["seen"][-10000:]
            self._store_message(
                sender_id,
                "in",
                text,
                message_id=message_id,
                status="received",
                sent_at=clear["sent_at"],
                received_at=received_at,
                kind=kind,
                voice=voice,
                attachment=attachment,
            )
        event_label = {
            "voice": "Messaggio vocale cifrato",
            "attachment": "Allegato cifrato",
        }.get(kind, "Messaggio cifrato")
        self._emit_protocol_event("message_received", f"{event_label} ricevuto da {sender.name}")
        if self.on_message:
            self.on_message("new", sender_id)
        if self._privacy_enabled(sender_id, "send_delivery_receipts"):
            if inline_reply:
                return self._message_ack_payload(sender, message_id, received_at)
            self._send_message_ack(sender, message_id, received_at)
        return None

    def _receive_encrypted_delivery(self, sender_id: str, clear: dict) -> None:
        message_id = clear.get("target_id", "")
        if not isinstance(message_id, str):
            return
        self._mark_outgoing_status(sender_id, [message_id], "delivered", clear.get("received_at"))

    def _receive_read_receipt(self, sender_id: str, clear: dict) -> None:
        ids = clear.get("message_ids", [])
        if isinstance(ids, list):
            self._mark_outgoing_status(sender_id, [str(value) for value in ids[:100]], "read")

    def _receive_reaction(self, sender_id: str, clear: dict) -> None:
        target_id, emoji = clear.get("target_id", ""), str(clear.get("emoji", ""))
        remove = clear.get("remove") is True
        legacy_remove_all = remove and not emoji
        if not target_id or (not legacy_remove_all and (not emoji_data.is_emoji(emoji) or len(emoji) > 32)):
            return
        with self._state_lock:
            for message in self.vault.state.get("messages", []):
                if message.get("message_id") == target_id and message.get("contact_id") == sender_id:
                    reactions = message.setdefault("reactions", {})
                    if not isinstance(reactions, dict):
                        reactions = {}
                        message["reactions"] = reactions
                    if remove:
                        if legacy_remove_all:
                            reactions.pop(sender_id, None)
                        else:
                            sender_reactions = _reaction_values(reactions.get(sender_id))
                            if emoji in sender_reactions:
                                sender_reactions.remove(emoji)
                            if sender_reactions:
                                reactions[sender_id] = sender_reactions
                            else:
                                reactions.pop(sender_id, None)
                    else:
                        sender_reactions = _reaction_values(reactions.get(sender_id))
                        if emoji not in sender_reactions and len(sender_reactions) < 12:
                            sender_reactions.append(emoji)
                        reactions[sender_id] = sender_reactions
                    self.vault.save()
                    break
        if self.on_message:
            self.on_message("status", sender_id)

    def _receive_identity_visibility(self, sender_id: str, clear: dict) -> None:
        visible = clear.get("visible")
        if not isinstance(visible, bool):
            return
        with self._state_lock:
            stored = self.vault.state.setdefault("chat_settings", {}).setdefault(sender_id, {})
            stored["remote_identity_id_visible"] = visible
            self.vault.save()
        self._emit_protocol_event(
            "identity_visibility_updated",
            "Il contatto ha aggiornato la visibilità del proprio Identity ID",
        )

    def _mark_outgoing_status(self, contact_id: str, message_ids: list[str], status: str, received_at: object = None) -> None:
        changed = False
        attachment_acks: list[tuple[str, str]] = []
        now = int(time.time())
        with self._state_lock:
            if status in {"delivered", "read"}:
                pending = set(message_ids)
                attachment_acks = [
                    (str(item.get("attachment_transfer_id", "")), str(item.get("message_id", "")))
                    for item in self.vault.state.get("outbox", [])
                    if item.get("message_id") in pending and item.get("attachment_transfer_id")
                ]
                self.vault.state["outbox"] = [item for item in self.vault.state["outbox"] if item.get("message_id") not in pending]
            for message in self.vault.state.get("messages", []):
                if message.get("message_id") in message_ids and message.get("direction") == "out" and message.get("contact_id") == contact_id:
                    current_status = str(message.get("status", "pending"))
                    rank = {"pending": 0, "sent": 1, "delivered": 2, "read": 3}
                    message["status"] = status if rank.get(status, 0) >= rank.get(current_status, 0) else current_status
                    if status == "delivered":
                        message["delivered_at"] = now
                        self._finish_receipt_timing(message)
                        if isinstance(received_at, int):
                            message["recipient_received_at"] = received_at
                    elif status == "read":
                        message["delivered_at"] = message.get("delivered_at") or now
                        self._finish_receipt_timing(message)
                        message["read_at"] = now
                    changed = True
            if changed or attachment_acks:
                self.vault.save()
        for transfer_id, protocol_message_id in attachment_acks:
            self._attachment_protocol_acked(transfer_id, protocol_message_id, received_at)
        if changed and self.on_message:
            self.on_message("status", contact_id)

    def _finish_receipt_timing(self, message: dict) -> None:
        message_id = str(message.get("message_id", ""))
        started_ns = self._receipt_started_ns.pop(message_id, None)
        if started_ns is not None and "encrypted_receipt_rtt_ms" not in message:
            message["encrypted_receipt_rtt_ms"] = round(
                (time.perf_counter_ns() - started_ns) / 1_000_000,
                3,
            )

    def _validated_contact(self, value: dict) -> IdentityBundle:
        contact = IdentityBundle.from_dict(value)
        contact.verify()
        if not contact.profile_code:
            raise ValueError("Profilo senza codice Kerberus")
        return contact

    def _save_contact(self, contact: IdentityBundle) -> None:
        with self._state_lock:
            self.vault.state["contacts"][contact.identity_id] = contact.to_dict()
            self.vault.save()
        if self.on_contacts_changed:
            self.on_contacts_changed(contact.identity_id)
        self.warm_contact(contact.identity_id)

    @staticmethod
    def _signed_control(sender: IdentityBundle, envelope: dict) -> None:
        signed = dict(envelope)
        signature = str(signed.pop("signature", ""))
        verify_control(sender, signed, signature)

    @staticmethod
    def _remote_matches(sender: IdentityBundle, remote_destination: str) -> bool:
        if not remote_destination:
            return True  # Direct unit/in-process transports have no SAM peer metadata.
        try:
            claimed = profile_destination(sender.profile_code)
            actual = remote_destination.lower() if remote_destination.lower().endswith(".b32.i2p") else destination_b32(remote_destination)
            return hmac.compare_digest(claimed, actual)
        except ValueError:
            return False

    def _receive_contact_request(self, envelope: dict, remote_destination: str = "") -> tuple[str, dict]:
        sender = self._validated_contact(envelope["sender"])
        self._signed_control(sender, envelope)
        if not self._remote_matches(sender, remote_destination):
            raise ValueError("Destination I2P del richiedente non autenticata")
        request_id = envelope.get("request_id", "")
        if not isinstance(request_id, str) or len(request_id) != 32:
            raise ValueError("Identificatore richiesta non valido")
        duplicate = self._consume_contact_code(envelope.get("target_code", ""), sender.identity_id)
        self._save_contact(sender)
        event = "Ritrasmissione valida" if duplicate else "Richiesta valida"
        self._emit_protocol_event("contact_request_received", f"{event} ricevuta da {sender.name}")
        identity = self.identity()
        if not identity:
            raise RuntimeError("Identità locale non configurata")
        response = {
            "version": 1, "type": "contact_accept", "request_id": request_id,
            "sender": identity.to_dict(),
        }
        if identity.identity_id < sender.identity_id:
            with self._state_lock:
                response["ratchet_init"] = ratchet_initiate(
                    self.vault.state.setdefault("ratchets", {}), identity, self.secrets(), sender
                )
                self.vault.save()
        response["signature"] = sign_control(self.secrets(), response)
        return sender.destination, response

    def _receive_contact_accept(self, envelope: dict, remote_destination: str = "") -> None:
        sender = self._validated_contact(envelope["sender"])
        self._signed_control(sender, envelope)
        if not self._remote_matches(sender, remote_destination):
            raise ValueError("Destination I2P della conferma non autenticata")
        destination = profile_destination(sender.profile_code)
        request_id = envelope.get("request_id", "")
        with self._state_lock:
            pending = self.vault.state["pending"].get(destination)
            if not pending or not hmac.compare_digest(str(pending.get("request_id", "")), str(request_id)):
                raise ValueError("Conferma contatto non richiesta o scaduta")
            self.vault.state["pending"].pop(destination, None)
            self.vault.save()
        self._save_contact(sender)
        self._emit_protocol_event("contact_accept_received", f"Contatto confermato: {sender.name}")
        init_header = envelope.get("ratchet_init")
        if isinstance(init_header, dict):
            with self._state_lock:
                ready = ratchet_accept_init(
                    self.vault.state.setdefault("ratchets", {}), self.identity(), self.secrets(), sender, init_header
                )
                self.vault.save()
            self._send_ratchet_handshake(sender, "ready", ready)
        else:
            self._ensure_ratchet_handshake(sender)
        if pending and pending.get("first_message"):
            self.send_message(sender.identity_id, pending["first_message"])

    def _send_contact_reject(self, envelope: dict, reason: str) -> None:
        try:
            sender = self._validated_contact(envelope["sender"])
        except Exception:
            return
        identity = self.identity()
        if not identity:
            return
        public_reason = "Codice contatto scaduto, già usato o non valido"
        if "formato" in reason.lower() or "firma" in reason.lower():
            public_reason = "Profilo del richiedente non valido"
        response = {
            "version": 1,
            "type": "contact_reject",
            "request_id": str(envelope.get("request_id", "")),
            "reason": public_reason,
            "sender": identity.to_dict(),
        }
        response["signature"] = sign_control(self.secrets(), response)
        self._queue_control(sender.destination, response)

    def _receive_contact_reject(self, envelope: dict, remote_destination: str = "") -> None:
        sender = self._validated_contact(envelope["sender"])
        self._signed_control(sender, envelope)
        if not self._remote_matches(sender, remote_destination):
            raise ValueError("Destination I2P del rifiuto non autenticata")
        destination = profile_destination(sender.profile_code)
        with self._state_lock:
            pending = self.vault.state["pending"].get(destination)
            if not pending or not hmac.compare_digest(
                str(pending.get("request_id", "")), str(envelope.get("request_id", ""))
            ):
                raise ValueError("Rifiuto riferito a una richiesta diversa o scaduta")
            self.vault.state["pending"].pop(destination, None)
            self.vault.save()
        self._emit_protocol_event(
            "contact_reject_received",
            envelope.get("reason", "Richiesta rifiutata dal destinatario"),
        )

    def _emit_protocol_event(self, kind: str, detail: str) -> None:
        self.last_protocol_event = detail
        if self.on_protocol_event:
            self.on_protocol_event(kind, detail)

    def _receive_profile_update(self, envelope: dict) -> None:
        sender = self._validated_contact(envelope["sender"])
        if sender.identity_id not in self.vault.state["contacts"]:
            return
        self._save_contact(sender)

    def _send_message_ack(self, sender: IdentityBundle, message_id: str, received_at: int) -> None:
        envelope = self._message_ack(sender, message_id, received_at)
        if envelope:
            self._queue_control(sender.destination, envelope, background=True)

    def _message_ack(self, sender: IdentityBundle, message_id: str, received_at: int) -> dict | None:
        identity = self.identity()
        if not identity:
            return None
        if not ratchet_is_ready(self.vault.state.setdefault("ratchets", {}), sender.identity_id):
            self._ensure_ratchet_handshake(sender)
            return None
        # Delivery receipts are encrypted like messages. A passive relay can no
        # longer correlate a clear message id with its acknowledgement.
        with self._state_lock:
            envelope = self._seal_ratchet(sender, {
                "kind": "delivery", "target_id": message_id, "received_at": received_at,
            })
            self.vault.save()
        return envelope

    def _message_ack_payload(self, sender: IdentityBundle, message_id: str, received_at: int) -> bytes | None:
        envelope = self._message_ack(sender, message_id, received_at)
        return json.dumps(envelope, separators=(",", ":")).encode("utf-8") if envelope else None

    def _receive_message_ack(self, envelope: dict) -> None:
        message_id = envelope.get("message_id", "")
        if not isinstance(message_id, str) or len(message_id) != 32:
            return
        sender_id = envelope.get("sender_id", "")
        identity = self.identity()
        contact_data = self.vault.state["contacts"].get(sender_id)
        if not identity or not contact_data or envelope.get("recipient_id") != identity.identity_id:
            return
        signed_keys = ("version", "type", "message_id", "sender_id", "recipient_id")
        signed = {key: envelope[key] for key in signed_keys}
        contact = IdentityBundle.from_dict(contact_data)
        verify_control(contact, signed, envelope.get("signature", ""))
        verified_received_at = None
        remote_received = envelope.get("received_at")
        if isinstance(remote_received, int) and remote_received >= 0:
            try:
                verify_control(
                    contact,
                    {**signed, "received_at": remote_received},
                    envelope.get("timing_signature", ""),
                )
                verified_received_at = remote_received
            except Exception:
                pass
        with self._state_lock:
            pending_ids = {item["message_id"] for item in self.vault.state["outbox"]}
            if message_id not in pending_ids:
                return
            self.vault.state["outbox"] = [
                item for item in self.vault.state["outbox"] if item["message_id"] != message_id
            ]
            for message in self.vault.state["messages"]:
                if message.get("message_id") == message_id and message.get("direction") == "out":
                    message["status"] = "delivered"
                    message["delivered_at"] = int(time.time())
                    self._finish_receipt_timing(message)
                    if verified_received_at is not None:
                        message["recipient_received_at"] = verified_received_at
                    break
            self.vault.save()
        if self.on_message:
            self.on_message("status", sender_id)

    def _delivery_loop(self) -> None:
        while not self._stop_delivery.is_set():
            self.flush_control_outbox(background=True)
            self.flush_pending_contacts(background=True)
            self.flush_outbox(background=True)
            self._stop_delivery.wait(1)

    def flush_pending_contacts(self, background: bool = False) -> None:
        with self._state_lock:
            destinations = [
                destination for destination, entry in self.vault.state["pending"].items()
                if entry.get("payload")
            ]
        for destination in destinations:
            if self._stop_delivery.is_set():
                return
            if background:
                self._submit_delivery("contact", destination, self._attempt_pending_contact, destination)
            else:
                self._attempt_pending_contact(destination)

    def _attempt_pending_contact(self, destination: str, force: bool = False) -> bool:
        now = int(time.time())
        with self._state_lock:
            entry = self.vault.state["pending"].get(destination)
            if not entry or not entry.get("payload"):
                return True
            if now - entry.get("created_at", now) > 600:
                self.vault.state["pending"].pop(destination, None)
                self.vault.save()
                self._emit_protocol_event("contact_request_expired", "Nessuna conferma ricevuta entro 10 minuti")
                return False
            prior_attempts = max(entry.get("attempts", 0) - 1, 0)
            retry_after = self._CONTACT_RETRY_SECONDS[
                min(prior_attempts, len(self._CONTACT_RETRY_SECONDS) - 1)
            ]
            if not force and now - entry.get("last_attempt", 0) < retry_after:
                return False
            entry["last_attempt"] = now
            entry["attempts"] = entry.get("attempts", 0) + 1
            payload = entry["payload"].encode("utf-8")
            self.vault.save()
        try:
            self.sam.send(destination, payload)
        except Exception as exc:
            self._emit_protocol_event("contact_request_retry", f"Destinatario non raggiungibile; nuovo tentativo automatico: {exc}")
            return False
        self._emit_protocol_event(
            "contact_request_dispatched",
            "Frame affidato a SAM; attendo la conferma firmata del destinatario",
        )
        return True

    def _queue_control(self, destination: str, envelope: dict, background: bool = False) -> None:
        payload = json.dumps(envelope, separators=(",", ":"))
        control_id = hashlib.sha256((destination + payload).encode("utf-8")).hexdigest()
        with self._state_lock:
            queue = self.vault.state.setdefault("control_outbox", [])
            if not any(item["control_id"] == control_id for item in queue):
                queue.append({
                    "control_id": control_id,
                    "destination": destination,
                    "payload": payload,
                    "last_attempt": 0,
                    "attempts": 0,
                })
                self.vault.state["control_outbox"] = queue[-1000:]
                self.vault.save()
        if background:
            self._submit_delivery("control", control_id, self._attempt_control_force, control_id)
        else:
            self._attempt_control(control_id, force=True)

    def _attempt_control_force(self, control_id: str) -> bool:
        return self._attempt_control(control_id, force=True)

    def flush_control_outbox(self, background: bool = False) -> None:
        with self._state_lock:
            control_ids = [item["control_id"] for item in self.vault.state.get("control_outbox", [])]
        for control_id in control_ids:
            if self._stop_delivery.is_set():
                return
            if background:
                self._submit_delivery("control", control_id, self._attempt_control, control_id)
            else:
                self._attempt_control(control_id)

    def _attempt_control(self, control_id: str, force: bool = False) -> bool:
        now = int(time.time())
        with self._state_lock:
            entry = next(
                (item for item in self.vault.state.get("control_outbox", []) if item["control_id"] == control_id),
                None,
            )
            if not entry:
                return True
            prior_attempts = max(entry.get("attempts", 0) - 1, 0)
            retry_after = self._CONTROL_RETRY_SECONDS[min(prior_attempts, len(self._CONTROL_RETRY_SECONDS) - 1)]
            if not force and now - entry.get("last_attempt", 0) < retry_after:
                return False
            entry["last_attempt"] = now
            entry["attempts"] = entry.get("attempts", 0) + 1
            destination = entry["destination"]
            payload = entry["payload"].encode("utf-8")
            self.vault.save()
        try:
            self.sam.send(destination, payload)
        except Exception as exc:
            self._emit_protocol_event("control_retry", f"Conferma di protocollo in coda; retry I2P: {exc}")
            return False
        with self._state_lock:
            self.vault.state["control_outbox"] = [
                item for item in self.vault.state.get("control_outbox", [])
                if item["control_id"] != control_id
            ]
            self.vault.save()
        return True

    def flush_outbox(self, background: bool = False) -> None:
        with self._state_lock:
            message_ids = [item["message_id"] for item in self.vault.state["outbox"]]
        for message_id in message_ids:
            if self._stop_delivery.is_set():
                return
            if background:
                self._submit_delivery("message", message_id, self._attempt_outbox, message_id)
            else:
                self._attempt_outbox(message_id)

    def _submit_delivery(self, kind: str, item_id: str, function: Callable[[str], bool], argument: str) -> None:
        marker = (kind, item_id)
        with self._state_lock:
            if marker in self._inflight:
                return
            self._inflight.add(marker)

        def run() -> None:
            try:
                function(argument)
            except Exception as exc:
                self._emit_protocol_event("delivery_error", f"Errore nella coda {kind}: {exc}")
            finally:
                with self._state_lock:
                    self._inflight.discard(marker)

        try:
            self._delivery_pool.submit(run)
        except RuntimeError:
            with self._state_lock:
                self._inflight.discard(marker)

    def _attempt_outbox(self, message_id: str, force: bool = False) -> bool:
        now = int(time.time())
        with self._state_lock:
            entry = next((item for item in self.vault.state["outbox"] if item["message_id"] == message_id), None)
            if not entry:
                return True
            if entry.get("paused"):
                return False
            if not entry.get("payload"):
                contact_data = self.vault.state.get("contacts", {}).get(entry.get("contact_id"))
                if not contact_data or not ratchet_is_ready(
                    self.vault.state.setdefault("ratchets", {}), str(entry.get("contact_id", ""))
                ):
                    return False
                contact = IdentityBundle.from_dict(contact_data)
                envelope = self._seal_ratchet(
                    contact, dict(entry.get("deferred") or {}), message_id=message_id
                )
                entry["payload"] = json.dumps(envelope, separators=(",", ":"))
                entry.pop("deferred", None)
            prior_attempts = max(entry.get("attempts", 0) - 1, 0)
            retry_after = self._MESSAGE_RETRY_SECONDS[min(prior_attempts, len(self._MESSAGE_RETRY_SECONDS) - 1)]
            if not force and now - entry.get("last_attempt", 0) < retry_after:
                return False
            entry["last_attempt"] = now
            entry["attempts"] = entry.get("attempts", 0) + 1
            destination = entry["destination"]
            payload = entry["payload"].encode("utf-8")
            self.vault.save()
        started = time.monotonic()
        with self._state_lock:
            self._receipt_started_ns[message_id] = time.perf_counter_ns()
        try:
            transport_metrics = self.sam.send(destination, payload)
        except Exception as exc:
            with self._state_lock:
                self._receipt_started_ns.pop(message_id, None)
            elapsed = time.monotonic() - started
            self._emit_protocol_event(
                "message_retry",
                f"Invio I2P fallito dopo {elapsed:.2f}s ({type(exc).__name__}): {exc}",
            )
            return False
        elapsed = time.monotonic() - started
        with self._state_lock:
            parent_message_id = ""
            transfer_id = str(entry.get("attachment_transfer_id", ""))
            if transfer_id:
                transfer = self.vault.state.setdefault("attachment_transfers", {}).get(transfer_id, {})
                parent_message_id = str(transfer.get("message_id", "")) if isinstance(transfer, dict) else ""
            for message in self.vault.state["messages"]:
                if message.get("message_id") in {message_id, parent_message_id}:
                    if isinstance(transport_metrics, dict):
                        message["transport_metrics"] = copy.deepcopy(transport_metrics)
                    if parent_message_id:
                        message["status"] = "sent"
                    break
            still_pending = any(item["message_id"] == message_id for item in self.vault.state["outbox"])
            if still_pending:
                for message in self.vault.state["messages"]:
                    if message.get("message_id") == message_id:
                        message["status"] = "sent"
                        break
            self.vault.save()
        if still_pending:
            self._emit_protocol_event(
                "message_stream_sent", f"Frame scritto sullo stream in {elapsed:.2f}s; attendo conferma cifrata"
            )
        else:
            self._emit_protocol_event("message_delivered", "Messaggio consegnato e confermato")
        if self.on_message:
            self.on_message("status", entry["contact_id"])
        return True

    def _consume_contact_code(self, supplied: str, sender_id: str = "") -> bool:
        normalized = supplied.strip().upper()
        identity = self.identity()
        if not identity:
            raise RuntimeError("Identità non configurata")
        fingerprint = hashlib.sha256(normalized.encode("ascii")).hexdigest()
        with self._state_lock:
            used = self.vault.state["used_contact_codes"]
            for entry in used:
                if isinstance(entry, str) and hmac.compare_digest(entry, fingerprint):
                    raise ValueError("Codice contatto già utilizzato")
                if isinstance(entry, dict) and hmac.compare_digest(entry.get("fingerprint", ""), fingerprint):
                    if sender_id and hmac.compare_digest(entry.get("sender_id", ""), sender_id):
                        return True
                    raise ValueError("Codice contatto già utilizzato")
            settings = self.settings()
            period = settings["contact_code_period_minutes"]
            generation = settings["contact_code_generation"]
            anchor_time = settings["contact_code_anchor_time"]
            current_time = int(time.time())
            expected_codes = (
                rotating_contact_code(
                    identity,
                    self.secrets(),
                    period_minutes=period,
                    generation=generation,
                    anchor_time=anchor_time,
                    timestamp=current_time - offset * period * 60,
                ).upper()
                for offset in range(2)
            )
            if not any(hmac.compare_digest(normalized, expected) for expected in expected_codes):
                raise ValueError("Codice contatto scaduto o non valido")
            if settings["contact_code_single_use"]:
                used.append({"fingerprint": fingerprint, "sender_id": sender_id})
                self.vault.state["used_contact_codes"] = used[-5000:]
                self.vault.state["settings"]["contact_code_generation"] = generation + 1
                self.vault.state["settings"]["contact_code_anchor_time"] = current_time
                self.vault.save()
        return False

    def _store_message(
        self,
        contact_id: str,
        direction: str,
        text: str,
        message_id: str = "",
        status: str = "received",
        sent_at: int | None = None,
        received_at: int | None = None,
        kind: str = "message",
        voice: dict | None = None,
        attachment: dict[str, object] | None = None,
    ) -> None:
        stored = {
            "message_id": message_id,
            "contact_id": contact_id,
            "direction": direction,
            "kind": kind,
            "text": text,
            "time": sent_at if sent_at is not None else int(time.time()),
            "sent_at": sent_at if sent_at is not None else int(time.time()),
            "received_at": received_at,
            "delivered_at": None,
            "recipient_received_at": None,
            "read_at": None,
            "reactions": {},
            "status": status,
        }
        if voice is not None:
            stored["voice"] = copy.deepcopy(voice)
        if attachment is not None:
            stored["attachment"] = copy.deepcopy(attachment)
        with self._state_lock:
            self.vault.state["messages"].append(stored)
            self.vault.save()

    def close(self, wait: bool = False) -> None:
        self._stop_delivery.set()
        self.sam.stop()
        self._delivery_pool.shutdown(wait=wait, cancel_futures=True)
