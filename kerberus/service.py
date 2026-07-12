from __future__ import annotations

import hashlib
import hmac
import json
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from .config import AppConfig
from .crypto import (
    IdentityBundle,
    IdentitySecrets,
    generate_identity,
    open_message_payload,
    profile_destination,
    rotating_contact_code,
    seal_message,
    sign_control,
    update_destination,
    update_public_profile,
    verify_control,
)
from .sam import SamClient
from .vault import Vault


class MessengerService:
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
        self.warm_recent_contacts()
        return active

    def _receive_safely(self, payload: bytes) -> bytes | None:
        try:
            return self._receive(payload, inline_reply=True)
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
        with self._state_lock:
            for entry in self.vault.state.get("outbox", []):
                entry["last_attempt"] = 0
            for entry in self.vault.state.get("pending", {}).values():
                entry["last_attempt"] = 0
            for entry in self.vault.state.get("control_outbox", []):
                entry["last_attempt"] = 0
            status = self.queue_status()
            self.vault.save()
        self.flush_control_outbox(background=True)
        self.flush_pending_contacts(background=True)
        self.flush_outbox(background=True)
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
        return dict(settings)

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
            "target_code": normalized,
            "sender": identity.to_dict(),
        }
        payload = json.dumps(request, separators=(",", ":"))
        with self._state_lock:
            self.vault.state["pending"][destination] = {
                "first_message": first_message.strip(),
                "payload": payload,
                "created_at": int(time.time()),
                "last_attempt": 0,
                "attempts": 0,
            }
            self.vault.save()
        sent = self._attempt_pending_contact(destination, force=True)
        return "sent" if sent else "queued"

    def messages_for(self, contact_id: str) -> list[dict]:
        return [m for m in self.vault.state["messages"] if m["contact_id"] == contact_id]

    def delete_message(self, message_id: str) -> bool:
        """Delete one local copy and cancel its pending delivery, if any."""
        if not message_id:
            return False
        with self._state_lock:
            before = len(self.vault.state["messages"])
            self.vault.state["messages"] = [
                message for message in self.vault.state["messages"]
                if message.get("message_id") != message_id
            ]
            self.vault.state["outbox"] = [
                entry for entry in self.vault.state["outbox"]
                if entry.get("message_id") != message_id
            ]
            changed = len(self.vault.state["messages"]) != before
            if changed:
                self.vault.save()
        return changed

    def forward_message(self, contact_id: str, text: str) -> str:
        # Forwarding creates a fresh envelope, message id, KEM secret and nonce.
        # No original sender or conversation metadata is attached.
        if not text.strip():
            raise ValueError("Messaggio vuoto")
        return self.send_message(contact_id, text)

    def send_message(self, contact_id: str, text: str) -> str:
        identity = self.identity()
        if not identity:
            raise RuntimeError("Identità non configurata")
        contact = IdentityBundle.from_dict(self.vault.state["contacts"][contact_id])
        envelope = seal_message(identity, self.secrets(), contact, text)
        message_id = envelope["message_id"]
        payload = json.dumps(envelope, separators=(",", ":"))
        now = int(time.time())
        with self._state_lock:
            self.vault.state["messages"].append({
                "message_id": message_id,
                "contact_id": contact_id,
                "direction": "out",
                "text": text,
                "time": now,
                "sent_at": now,
                "received_at": None,
                "delivered_at": None,
                "recipient_received_at": None,
                "status": "pending",
            })
            self.vault.state["outbox"].append({
                "message_id": message_id,
                "contact_id": contact_id,
                "destination": contact.destination,
                "payload": payload,
                "created_at": now,
                "last_attempt": 0,
                "attempts": 0,
            })
            self.vault.state["outbox"] = self.vault.state["outbox"][-10_000:]
            self.vault.save()
        if self.on_message:
            self.on_message("new", contact_id)
        sent = self._attempt_outbox(message_id, force=True)
        return "sent" if sent else "queued"

    def _receive(self, payload: bytes, inline_reply: bool = False) -> bytes | None:
        envelope = json.loads(payload.decode("utf-8"))
        message_type = envelope.get("type")
        if message_type == "contact_request":
            try:
                self._receive_contact_request(envelope)
            except Exception as exc:
                self._emit_protocol_event("contact_request_rejected", str(exc))
                self._send_contact_reject(envelope, str(exc))
            return
        if message_type == "contact_accept":
            self._receive_contact_accept(envelope)
            return
        if message_type == "contact_reject":
            self._receive_contact_reject(envelope)
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
            received_at = int(stored.get("received_at") or time.time())
            if inline_reply:
                return self._message_ack_payload(sender, message_id, received_at)
            self._send_message_ack(sender, message_id, received_at)
            return None
        clear = open_message_payload(identity, self.secrets(), sender, envelope)
        received_at = int(time.time())
        with self._state_lock:
            self.vault.state["seen"].append(message_id)
            self.vault.state["seen"] = self.vault.state["seen"][-10000:]
            self._store_message(
                sender_id,
                "in",
                clear["text"],
                message_id=message_id,
                status="received",
                sent_at=clear["sent_at"],
                received_at=received_at,
            )
        self._emit_protocol_event("message_received", f"Messaggio cifrato ricevuto da {sender.name}")
        if self.on_message:
            self.on_message("new", sender_id)
        if inline_reply:
            return self._message_ack_payload(sender, message_id, received_at)
        self._send_message_ack(sender, message_id, received_at)
        return None

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

    def _receive_contact_request(self, envelope: dict) -> None:
        sender = self._validated_contact(envelope["sender"])
        duplicate = self._consume_contact_code(envelope.get("target_code", ""), sender.identity_id)
        self._save_contact(sender)
        event = "Ritrasmissione valida" if duplicate else "Richiesta valida"
        self._emit_protocol_event("contact_request_received", f"{event} ricevuta da {sender.name}")
        identity = self.identity()
        if not identity:
            return
        response = {"version": 1, "type": "contact_accept", "sender": identity.to_dict()}
        self._queue_control(sender.destination, response)
        self._emit_protocol_event("contact_accept_queued", "Conferma firmata inserita nella coda I2P")

    def _receive_contact_accept(self, envelope: dict) -> None:
        sender = self._validated_contact(envelope["sender"])
        self._save_contact(sender)
        self._emit_protocol_event("contact_accept_received", f"Contatto confermato: {sender.name}")
        pending = None
        with self._state_lock:
            pending = self.vault.state["pending"].pop(profile_destination(sender.profile_code), None)
            self.vault.save()
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
            "reason": public_reason,
            "sender": identity.to_dict(),
        }
        self._queue_control(sender.destination, response)

    def _receive_contact_reject(self, envelope: dict) -> None:
        sender = self._validated_contact(envelope["sender"])
        destination = profile_destination(sender.profile_code)
        with self._state_lock:
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
        ack = {
            "version": 1,
            "type": "message_ack",
            "message_id": message_id,
            "sender_id": identity.identity_id,
            "recipient_id": sender.identity_id,
        }
        timing = {**ack, "received_at": received_at}
        return {
            **timing,
            "signature": sign_control(self.secrets(), ack),
            "timing_signature": sign_control(self.secrets(), timing),
        }

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
            self._stop_delivery.wait(2)

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
            retry_after = min(120, 15 * (2 ** min(prior_attempts, 3)))
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
        self._emit_protocol_event("contact_request_sent", "Stream aperto; attendo la conferma firmata")
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
            retry_after = min(60, 5 * (2 ** min(prior_attempts, 4)))
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
            prior_attempts = max(entry.get("attempts", 0) - 1, 0)
            retry_after = min(60, 5 * (2 ** min(prior_attempts, 4)))
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
            self._emit_protocol_event("message_retry", f"Messaggio in coda; retry I2P automatico: {exc}")
            return False
        with self._state_lock:
            still_pending = any(item["message_id"] == message_id for item in self.vault.state["outbox"])
            if still_pending:
                for message in self.vault.state["messages"]:
                    if message.get("message_id") == message_id:
                        message["status"] = "sent"
                        break
                self.vault.save()
        if still_pending:
            self._emit_protocol_event("message_stream_sent", "Messaggio inviato; attendo conferma dal destinatario")
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
    ) -> None:
        with self._state_lock:
            self.vault.state["messages"].append({
                "message_id": message_id,
                "contact_id": contact_id,
                "direction": direction,
                "text": text,
                "time": sent_at if sent_at is not None else int(time.time()),
                "sent_at": sent_at if sent_at is not None else int(time.time()),
                "received_at": received_at,
                "delivered_at": None,
                "recipient_received_at": None,
                "status": status,
            })
            self.vault.save()

    def close(self, wait: bool = False) -> None:
        self._stop_delivery.set()
        self.sam.stop()
        self._delivery_pool.shutdown(wait=wait, cancel_futures=True)
