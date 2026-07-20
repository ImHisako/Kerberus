from __future__ import annotations

import base64
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
import emoji as emoji_data
from PyQt6 import sip
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Callable
from PyQt6.QtCore import (
    QAbstractListModel, QByteArray, QBuffer, QEvent, QIODevice, QModelIndex, QObject,
    QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer, QUrl, pyqtSignal,
)
from PyQt6.QtGui import (
    QCloseEvent,
    QColor,
    QContextMenuEvent,
    QDesktopServices,
    QFont,
    QFontMetrics,
    QIcon,
    QImage,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QResizeEvent,
    QRegion,
    QTextCharFormat,
    QTextLayout,
    QTextOption,
    QWheelEvent,
)
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtMultimedia import (
    QAudioFormat, QAudioOutput, QAudioSource, QMediaDevices, QMediaPlayer,
)
from PyQt6.QtMultimediaWidgets import QVideoWidget
from PyQt6.QtWidgets import (
    QAbstractButton,
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QDialog,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QListView,
    QMainWindow,
    QMenu,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QStyledItemDelegate,
    QSystemTrayIcon,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .config import AppConfig
from . import __version__
from .crypto import IdentityBundle, b64, destination_b32, pq_available, pq_unavailable_reason, profile_destination, unb64
from .link_preview import extract_url, extract_urls, fetch_link_preview
from .network_insights import collect_i2p_peer_connections, lookup_ip_geolocation
from .router import I2P_VERSION, RouterInstaller
from .service import MessengerService
from .updates import UpdateInfo, check_for_update, download_update
from .voice import test_tone_wav


THEMES = {
    "default": {
        "window": "#0c0f13", "sidebar": "#12161b", "surface": "#171c22",
        "surface_2": "#20262e", "surface_3": "#29313b", "border": "#2d3540",
        "text": "#f2f5f7", "muted": "#909aa6", "faint": "#626d79",
        "accent": "#35d09a", "accent_hover": "#50ddb0", "accent_dark": "#174d3b",
        "cyan": "#4dbbd5", "warning": "#f0b35a", "danger": "#ef6b73",
    },
    "pink": {
        "window": "#170f16", "sidebar": "#21131e", "surface": "#291825",
        "surface_2": "#382031", "surface_3": "#482940", "border": "#57344e",
        "text": "#fff3fa", "muted": "#c39aad", "faint": "#8e687d",
        "accent": "#f472b6", "accent_hover": "#fb8fc6", "accent_dark": "#612447",
        "cyan": "#d88cff", "warning": "#f5bd68", "danger": "#ff7185",
    },
    "orange": {
        "window": "#15100b", "sidebar": "#1e160e", "surface": "#281c12",
        "surface_2": "#372619", "surface_3": "#473122", "border": "#59402d",
        "text": "#fff6ed", "muted": "#bea38d", "faint": "#876e5b",
        "accent": "#f59e42", "accent_hover": "#ffb35f", "accent_dark": "#603817",
        "cyan": "#e7c15b", "warning": "#f7c768", "danger": "#ef6b73",
    },
    "white": {
        "window": "#f6f7f9", "sidebar": "#ffffff", "surface": "#ffffff",
        "surface_2": "#edf0f3", "surface_3": "#e1e6eb", "border": "#ccd3da",
        "text": "#18212b", "muted": "#5f6d7a", "faint": "#8995a1",
        "accent": "#16865f", "accent_hover": "#0f9c6b", "accent_dark": "#ccecdf",
        "cyan": "#157f9b", "warning": "#b66b12", "danger": "#c73f4b",
    },
    "dark": {
        "window": "#050608", "sidebar": "#0a0c0f", "surface": "#101318",
        "surface_2": "#171b21", "surface_3": "#21262e", "border": "#292f38",
        "text": "#f6f7f9", "muted": "#9aa3ad", "faint": "#626b75",
        "accent": "#8b9cff", "accent_hover": "#a2afff", "accent_dark": "#29315f",
        "cyan": "#6ec5df", "warning": "#eeb35f", "danger": "#f06c76",
    },
}
COLORS = dict(THEMES["default"])

_LANGUAGE = "it"
_ENGLISH = {
    "Impostazioni": "Settings", "Salva impostazioni": "Save settings", "Annulla": "Cancel",
    "Chiudi": "Close", "Continua": "Continue", "Nuovo contatto": "New contact",
    "Aggiungi un contatto": "Add a contact", "Invia richiesta": "Send request",
    "Primo messaggio (opzionale)": "First message (optional)", "Scrivi un messaggio": "Write a message",
    "Invia": "Send", "Emoji": "Emoji", "Reagisci": "React", "Copia": "Copy",
    "Tutte le emoji…": "All emoji…",
    "Inoltra…": "Forward…", "Elimina da questo dispositivo": "Delete from this device",
    "Privacy di questa chat": "Privacy for this chat", "Privacy chat": "Chat privacy",
    "Impostazioni per questa conversazione": "Settings for this conversation",
    "Conferme di consegna": "Delivery receipts", "Conferme di lettura (spunte blu)": "Read receipts (blue ticks)",
    "Notifiche desktop": "Desktop notifications", "Esporta chat completa + delay": "Export full chat + delays",
    "Salva": "Save", "Attivo": "Enabled", "Disattivo": "Disabled",
    "PRIVACY E INVITI": "PRIVACY AND INVITES", "Codice contatto": "Contact code",
    "INTERVALLO DI ROTAZIONE": "ROTATION INTERVAL", "Ogni minuto": "Every minute",
    "Ogni 5 minuti": "Every 5 minutes", "Ogni 15 minuti": "Every 15 minutes", "Ogni ora": "Every hour",
    "Ruota immediatamente dopo il primo utilizzo": "Rotate immediately after first use",
    "RICEVUTE E RETE": "RECEIPTS AND NETWORK", "Invia conferme di consegna": "Send delivery receipts",
    "Invia conferme di lettura (spunte blu)": "Send read receipts (blue ticks)",
    "Anteprime link esterne con titolo e immagine": "External link previews with title and image",
    "Consenti funzioni clearnet esplicite (es. aggiornamenti)": "Allow explicit clearnet features (e.g. updates)",
    "DIAGNOSTICA LOCALE": "LOCAL DIAGNOSTICS", "Apri Console UI": "Open UI console",
    "Controlla aggiornamenti": "Check for updates", "Lingua dell’applicazione": "Application language",
    "La lingua selezionata verrà applicata al prossimo avvio.": "The selected language will be applied on next launch.",
    "Italiano": "Italian", "Inglese": "English", "Cerca emoji…": "Search emoji…",
    "Nessuna emoji trovata": "No emoji found", "Precedente": "Previous", "Successiva": "Next",
    "Reazione": "Reaction",
    "Puoi aggiungere più reazioni. Clicca con il tasto sinistro su una tua reazione per rimuoverla":
        "You can add multiple reactions. Left-click one of your reactions to remove it",
    "Recenti": "Recent", "Persone": "People", "Animali e natura": "Animals and nature",
    "Cibo e bevande": "Food and drink", "Attività": "Activities", "Viaggi": "Travel",
    "Oggetti": "Objects", "Simboli": "Symbols", "Bandiere": "Flags",
    "Apri profilo": "Open profile", "Profilo del contatto": "Contact profile",
    "CONTATTO VERIFICATO": "VERIFIED CONTACT", "Profilo firmato e verificato": "Signed and verified profile",
    "IDENTITY ID": "IDENTITY ID", "INDIRIZZO I2P": "I2P ADDRESS",
    "Copia ID": "Copy ID", "ID copiato": "ID copied", "Non disponibile": "Not available",
    "Chiavi pubbliche Ed25519, X25519 e ML-KEM-768": "Ed25519, X25519 and ML-KEM-768 public keys",
    "Dettagli di invio e ritardo": "Delivery and delay details", "In attesa": "Pending",
    "Inviato": "Sent", "Consegnato": "Delivered", "Letto": "Read",
    "Cerca conversazioni": "Search conversations", "CONVERSAZIONI": "CONVERSATIONS",
    "Canale ibrido X25519 + ML-KEM-768": "Hybrid X25519 + ML-KEM-768 channel",
    "Nuovo profilo": "New profile", "Crea il tuo profilo": "Create your profile",
    "Nome visibile": "Display name", "Crea vault": "Create vault", "Sblocca Kerberus": "Unlock Kerberus",
    "Password": "Password", "Ripeti password": "Repeat password", "Sblocca": "Unlock",
}
_ENGLISH.update({
    "Aggiungi contatto": "Add contact", "Annulla richiesta": "Cancel request",
    "Apri Kerberus": "Open Kerberus", "Apri informazioni I2P": "Open I2P information",
    "Apri link": "Open link", "Apri nel browser": "Open in browser",
    "Aprire link esterno?": "Open external link?", "Stai per lasciare Kerberus": "You are about to leave Kerberus",
    "Questo collegamento verrà aperto nel browser predefinito. Controlla attentamente il dominio prima di continuare.":
        "This link will open in your default browser. Carefully check the domain before continuing.",
    "Un sito esterno potrebbe essere dannoso, tracciare il tuo indirizzo IP o tentare di rubare informazioni.":
        "An external site could be malicious, track your IP address, or try to steal information.",
    "Collegamento non valido": "Invalid link", "Kerberus può aprire soltanto collegamenti HTTP o HTTPS validi.":
        "Kerberus can open only valid HTTP or HTTPS links.",
    "Attività dell’app": "Application activity",
    "CODICE CONTATTO": "CONTACT CODE", "CONNESSIONE PRIVATA": "PRIVATE CONNECTION",
    "Cambia foto": "Change picture", "Canale I2P pronto": "I2P channel ready",
    "Caricamento anteprima…": "Loading preview…", "Chat e delay esportati in JSON": "Chat and delays exported to JSON",
    "Configura I2P": "Configure I2P", "Console UI": "UI console", "Controllo bridge SAM": "Checking SAM bridge",
    "Copia codice": "Copy code", "DIAGNOSTICA DI CONSEGNA": "DELIVERY DIAGNOSTICS",
    "EVENTI LOCALI · NESSUN CONTENUTO DEI MESSAGGI": "LOCAL EVENTS · NO MESSAGE CONTENT",
    "Esci": "Exit", "Esporta profilo": "Export profile", "I2P: verifica...": "I2P: checking...",
    "Il mio profilo": "My profile", "Importa": "Import", "Inoltra": "Forward",
    "Inoltra messaggio": "Forward message", "Invio e ricezione": "Sending and receiving",
    "La chat sarà disponibile dopo la conferma firmata dell’altro dispositivo": "The chat will be available after the other device's signed confirmation",
    "Le tue conversazioni": "Your conversations", "Messaggio copiato": "Message copied",
    "Messaggio inoltrato con nuova cifratura": "Message forwarded with fresh encryption",
    "Impostazioni chat": "Chat settings", "Preferenze della conversazione": "Conversation preferences",
    "Privacy e ricevute": "Privacy and receipts", "Personalizza il comportamento solo per questa chat.":
        "Customize behavior for this chat only.",
    "Usa la preferenza generale dell’app oppure definisci un’eccezione.":
        "Use the app-wide preference or define an exception.",
    "Anteprime link": "Link previews", "Controlla il recupero di titoli e immagini esterne.":
        "Control retrieval of external titles and images.",
    "Notifiche della chat": "Chat notifications", "Mostra una notifica desktop per i nuovi messaggi.":
        "Show a desktop notification for new messages.",
    "Visibilità del profilo": "Profile visibility", "Decidi cosa mostrare a questo contatto nella schermata profilo.":
        "Choose what this contact sees on the profile screen.",
    "Mostra il mio Identity ID": "Show my Identity ID",
    "Consente a questo contatto di visualizzarlo aprendo il tuo profilo.":
        "Allow this contact to see it when opening your profile.",
    "L’Identity ID resta necessario al protocollo crittografico: questa opzione ne controlla soltanto la visualizzazione nell’interfaccia.":
        "The Identity ID remains necessary to the cryptographic protocol; this option controls only its display in the interface.",
    "Dati e diagnostica": "Data and diagnostics", "Esporta questa conversazione con timestamp e ritardi.":
        "Export this conversation with timestamps and delays.",
    "Esporta dati chat": "Export chat data", "Salva modifiche": "Save changes",
    "Impostazioni della chat aggiornate": "Chat settings updated",
    "Identity ID nascosto": "Identity ID hidden", "Questo contatto ha scelto di non mostrarlo nel profilo.":
        "This contact chose not to display it on the profile.",
    "Il contatto ha aggiornato la visibilità del proprio Identity ID":
        "The contact updated the visibility of their Identity ID",
    "Massimizza": "Maximize", "Ripristina": "Restore",
    "Argon2id · XChaCha20-Poly1305 · nessuna telemetria applicativa":
        "Argon2id · XChaCha20-Poly1305 · no application telemetry",
    "I2P streaming · X25519 + ML-KEM-768 · XChaCha20-Poly1305":
        "I2P streaming · X25519 + ML-KEM-768 · XChaCha20-Poly1305",
    "Diagnostica JSON (*.json)": "Diagnostics JSON (*.json)",
    "Immagini (*.png *.jpg *.jpeg *.webp *.bmp)": "Images (*.png *.jpg *.jpeg *.webp *.bmp)",
    "Tutti i file (*.*)": "All files (*.*)",
    "Invia un file cifrato (25 MB · video 100 MB)": "Send an encrypted file (25 MB · video 100 MB)",
    "Invia file": "Send file", "Salva file": "Save file", "Salva allegato": "Save attachment",
    "Allegato": "Attachment", "Allegato inviato": "Attachment sent",
    "Allegato salvato": "Attachment saved", "Riproduci video": "Play video",
    "Cifratura e invio dell’allegato…": "Encrypting and sending attachment…",
    "Metti in pausa": "Pause", "Riprendi": "Resume", "Annulla trasferimento": "Cancel transfer",
    "Trasferimento annullato": "Transfer cancelled", "Trasferimento in pausa": "Transfer paused",
    "Interrompere e annullare questo trasferimento?": "Stop and cancel this transfer?",
    "Il file è vuoto": "The file is empty",
    "Allegato salvato: {path}": "Attachment saved: {path}",
    "Profilo Kerberus (*.kbid *.json);;Tutti i file (*.*)": "Kerberus profile (*.kbid *.json);;All files (*.*)",
    "Profilo Kerberus (*.kbid)": "Kerberus profile (*.kbid)",
    "Kerberus · I2P messenger": "Kerberus · I2P messenger",
    "Richiesta affidata a I2P: la chat si aprirà dopo la conferma firmata":
        "Request handed to I2P: the chat will open after signed confirmation",
    "Contatto non ancora raggiungibile: richiesta salvata e ritentata automaticamente":
        "Contact not reachable yet: request saved and retried automatically",
    "Messaggistica privata attraverso I2P": "Private messaging through I2P",
    "Mostra ID crittografico": "Show cryptographic ID", "Nascondi ID crittografico": "Hide cryptographic ID",
    "Nuovo contatto verificato": "New verified contact", "Nuovo messaggio cifrato": "New encrypted message",
    "PROFILO KERBERUS": "KERBERUS PROFILE", "Privacy della chat aggiornata": "Chat privacy updated",
    "Profilo": "Profile", "Profilo firmato e aggiornato": "Signed profile updated", "Pulisci": "Clear",
    "Richiesta contatto annullata": "Contact request cancelled", "Richiesta in attesa": "Request pending",
    "Riconnetti": "Reconnect", "Rimuovi": "Remove", "Riprova code": "Retry queues",
    "Router I2P avviato · attendo il bridge SAM": "I2P router started · waiting for SAM bridge",
    "Salva messaggi, timestamp, stati e ritardi in un file JSON": "Save messages, timestamps, states and delays to a JSON file",
    "Salva profilo": "Save profile", "Scegli la chat": "Choose a chat", "Stato I2P": "I2P status",
    "Tempi del messaggio": "Message timing", "USERNAME": "USERNAME",
    "Consigliato: limita il riutilizzo accidentale di un invito condiviso.": "Recommended: limits accidental reuse of a shared invitation.",
    "Quando attive, Kerberus contatta automaticamente il sito del link. Host locali e indirizzi privati sono bloccati.":
        "When enabled, Kerberus automatically contacts the linked website. Local hosts and private addresses are blocked.",
    "Scegli per quanto tempo resta stabile il codice. La destination I2P non cambia; cambia soltanto il token di invito autenticato.":
        "Choose how long the code remains stable. The I2P destination does not change; only the authenticated invitation token changes.",
    "Le opzioni in automatico ereditano la policy generale. Le ricevute sono cifrate end-to-end. Le anteprime, se attive, contattano il sito e possono rivelare il tuo indirizzo IP al sito stesso.":
        "Automatic options inherit the global policy. Receipts are end-to-end encrypted. When enabled, previews contact the website and may reveal your IP address to it.",
    "L’orario di invio è autenticato nel messaggio cifrato. Il ritardo a senso unico dipende anche dalla sincronizzazione degli orologi; il tempo andata/ritorno usa invece l’orologio del mittente.":
        "The send time is authenticated inside the encrypted message. One-way delay also depends on clock synchronization; round-trip time uses the sender's clock.",
    "Destinatario temporaneamente non raggiungibile: messaggio cifrato in coda con retry automatico":
        "Recipient temporarily unreachable: encrypted message queued with automatic retry",
    "Kerberus ha ricevuto un nuovo messaggio.": "Kerberus received a new message.",
    "Impostazioni salvate · riavvia Kerberus per applicare la lingua": "Settings saved · restart Kerberus to apply the language",
})
_ENGLISH.update({
    "Proteggi il tuo spazio": "Protect your space", "Bentornato": "Welcome back",
    "Crea una password locale": "Create a local password", "Inserisci la password del vault": "Enter your vault password",
    "Le password non coincidono.": "The passwords do not match.", "Nuovo contatto": "New contact",
    "Conferma non ancora ricevuta": "Confirmation not received yet", "Nuovo tentativo tra 10 s": "Retrying in 10 seconds",
    "Anteprima non disponibile": "Preview unavailable", "Apri profilo": "Open profile",
    "Generali": "General", "Privacy": "Privacy", "Rete": "Network", "Sicurezza": "Security",
    "Diagnostica": "Diagnostics", "Personalizza Kerberus, la privacy e il comportamento della rete":
        "Customize Kerberus, privacy, and network behavior",
    "Aspetto e lingua": "Appearance and language", "Scegli la lingua usata in tutta l’applicazione.":
        "Choose the language used throughout the application.",
    "La modifica viene applicata subito a tutta l’interfaccia.": "The change is applied immediately across the interface.",
    "Ricevute dei messaggi": "Message receipts", "Controlla quali conferme cifrate inviare ai contatti.":
        "Choose which encrypted confirmations are sent to contacts.",
    "Comunica al mittente che il messaggio cifrato è arrivato al dispositivo.":
        "Tell the sender that the encrypted message reached this device.",
    "Conferme di lettura": "Read receipts", "Mostra le spunte blu dopo l’apertura della conversazione.":
        "Show blue ticks after the conversation is opened.",
    "Inviti e codice contatto": "Invites and contact code",
    "Riduci il rischio di riutilizzo involontario dei codici condivisi.":
        "Reduce the risk of accidentally reusing shared codes.",
    "Durata del codice": "Code lifetime", "Il token cambia; la destination I2P firmata rimane invariata.":
        "The token changes; the signed I2P destination stays the same.",
    "Codice monouso": "Single-use code", "Ruota immediatamente il token dopo il primo utilizzo valido.":
        "Rotate the token immediately after its first valid use.",
    "Contenuti esterni": "External content", "Decidi quando Kerberus può usare la rete clearnet oltre a I2P.":
        "Choose when Kerberus may use the clearnet in addition to I2P.",
    "Anteprime dei link": "Link previews", "Recupera titolo e immagine. Host locali e indirizzi privati restano bloccati.":
        "Fetch the title and image. Local hosts and private addresses remain blocked.",
    "Funzioni clearnet": "Clearnet features", "Consente azioni esplicite come il controllo e il download degli aggiornamenti.":
        "Allow explicit actions such as checking and downloading updates.",
    "Trasporto privato": "Private transport", "I messaggi continuano a viaggiare nel canale I2P cifrato end-to-end.":
        "Messages continue to travel through the end-to-end encrypted I2P channel.",
    "Prestazioni I2P": "I2P performance", "Riduci la latenza senza limitare i peer scelti automaticamente dal router.":
        "Reduce latency without limiting peers automatically selected by the router.",
    "Modalità bassa latenza": "Low-latency mode",
    "Usa tunnel da 2 hop e ACK iniziali immediati. Riduce l’anonimato rispetto ai 3 hop consigliati.":
        "Uses 2-hop tunnels and immediate initial ACKs. Reduces anonymity compared with the recommended 3 hops.",
    "Mantieni pronti i contatti recenti": "Keep recent contacts ready",
    "Compromesso privacy/prestazioni: apre in anticipo fino a 8 stream recenti e velocizza il primo messaggio, ma genera traffico e metadati di connessione in background. Per la massima privacy disattivalo.":
        "Privacy/performance trade-off: pre-opens up to 8 recent streams and speeds up the first message, but creates background traffic and connection metadata. Disable it for maximum privacy.",
    "Maschera quali contatti sono recenti": "Mask which contacts are recent",
    "Non falsifica I2P: seleziona casualmente fino a 8 contatti reali invece della cronologia recente. Riduce la correlazione con le chat recenti, ma il router SAM vede comunque le destination e anche un contatto non recente può osservare la connessione.":
        "Does not spoof I2P: randomly selects up to 8 real contacts instead of recent history. This reduces correlation with recent chats, but the SAM router still sees destinations and a non-recent contact may observe the connection.",
    "Conferma modalità bassa latenza": "Confirm low-latency mode",
    "Kerberus ridurrà i tunnel I2P da 3 a 2 hop. Il percorso più corto può diminuire la latenza, ma rende più economici gli attacchi di correlazione e analisi statistica del traffico.":
        "Kerberus will reduce I2P tunnels from 3 to 2 hops. The shorter path may reduce latency, but makes correlation and statistical traffic-analysis attacks less costly.",
    "La cifratura end-to-end X25519 + ML-KEM-768 non cambia e non viene usato zero-hop. Per la protezione I2P più alta mantieni 3 hop.":
        "End-to-end X25519 + ML-KEM-768 encryption is unchanged and zero-hop is never used. Keep 3 hops for the highest I2P protection.",
    "Mantieni massima privacy": "Keep maximum privacy", "Capisco, usa 2 hop": "I understand, use 2 hops",
    "Ottimizzazioni sempre attive: profilo interattivo, fast receive, primo frame nel SYN, stream persistenti e risposte full-duplex.":
        "Always-on optimizations: interactive profile, fast receive, first frame in SYN, persistent streams, and full-duplex replies.",
    "Protezione streaming": "Streaming protection", "Mantieni la finestra fuori dalle catture schermo supportate.":
        "Keep the window out of supported screen captures.",
    "Nascondi Kerberus durante streaming e condivisione schermo":
        "Hide Kerberus during streaming and screen sharing",
    "Su Windows chiede al sistema di escludere la finestra da OBS, registrazioni e condivisioni che rispettano le API di cattura.":
        "On Windows, asks the system to exclude the window from OBS, recordings, and sharing tools that honor capture APIs.",
    "Disponibile su Windows 10 versione 2004 o successiva. Non protegge da fotocamere, software con privilegi superiori o metodi di cattura non supportati.":
        "Available on Windows 10 version 2004 or later. It does not protect against cameras, higher-privileged software, or unsupported capture methods.",
    "Non disponibile su questo sistema: non esiste un’esclusione universale dalle catture schermo.":
        "Unavailable on this system: there is no universal screen-capture exclusion.",
    "Protezione locale": "Local protection", "Il vault e le chiavi private restano cifrati sul dispositivo.":
        "The vault and private keys remain encrypted on this device.",
    "Strumenti e diagnostica": "Tools and diagnostics", "Controlla lo stato locale senza includere il testo dei messaggi.":
        "Inspect local status without including message text.",
    "Impostazioni salvate": "Settings saved", "Protezione streaming attiva": "Streaming protection enabled",
    "Protezione streaming disattivata": "Streaming protection disabled",
    "Protezione streaming non disponibile: {detail}": "Streaming protection unavailable: {detail}",
    "Questa funzione è disponibile solo su Windows": "This feature is available only on Windows",
    "Chiudi Kerberus": "Close Kerberus", "Elimina messaggio": "Delete message",
    "Esportazione in chiaro": "Plaintext export", "Esporta chat e diagnostica": "Export chat and diagnostics",
    "Esportazione chat": "Chat export", "Clearnet disabilitata": "Clearnet disabled",
    "Aggiornamenti": "Updates", "Aggiornamento disponibile": "Update available",
    "Aggiornamento verificato": "Verified update", "Foto profilo": "Profile picture",
    "Scegli foto profilo": "Choose profile picture", "Importa profilo": "Import profile",
    "Profilo non valido": "Invalid profile", "Configura I2P su Linux": "Configure I2P on Linux",
    "Configurazione I2P": "I2P setup", "Installa I2P": "Install I2P", "Download e verifica I2P...": "Download and verify I2P...",
    "Bridge SAM": "SAM bridge", "I2P verificato": "I2P verified", "I2P connesso": "I2P connected",
    "I2P non connesso": "I2P not connected", "Ultimo evento": "Last event", "In attesa della conferma": "Awaiting confirmation",
    "Codice non disponibile": "Code unavailable", "In attesa della connessione I2P": "Waiting for the I2P connection",
    "Eliminare questo messaggio soltanto dal vault locale? Non verrà cancellato dal dispositivo del contatto.":
        "Delete this message only from the local vault? It will not be removed from the contact's device.",
    "Il file conterrà l’intera chat e i dati temporali in chiaro. Non condividerlo senza averlo controllato. Continuare?":
        "The file will contain the full chat and timing data in plaintext. Review it before sharing. Continue?",
    "Annullare questa richiesta di contatto e interrompere i tentativi automatici?":
        "Cancel this contact request and stop automatic retries?",
    "Abilita le funzioni clearnet nelle impostazioni prima di controllare gli aggiornamenti.":
        "Enable clearnet features in Settings before checking for updates.",
    "La checksum pubblicata nella release è valida. Chiudere Kerberus e avviare l'installer?":
        "The checksum published with the release is valid. Close Kerberus and launch the installer?",
    "Chiudere Kerberus e arrestare anche il router I2P? Tutte le comunicazioni I2P verranno interrotte.":
        "Close Kerberus and stop the I2P router too? All I2P communications will be interrupted.",
    "Conferma non ancora ricevuta · tentativi {count}": "Confirmation not received yet · attempts {count}",
    "Carica messaggi precedenti ({count})": "Load earlier messages ({count})",
    "Automatico ({state})": "Automatic ({state})", "attivo": "enabled", "disattivo": "disabled",
    "{seconds} secondi": "{seconds} seconds", "{minutes} min {seconds} s": "{minutes} min {seconds} s",
    "Kerberus {version} è la versione più recente.": "Kerberus {version} is the latest version.",
    "È disponibile Kerberus {version}. Scaricare ora l'aggiornamento dalla release GitHub?":
        "Kerberus {version} is available. Download the update from the GitHub release now?",
    "SHA-256 valida. Il nuovo eseguibile è stato salvato in:\n{path}":
        "SHA-256 verified. The new executable was saved to:\n{path}",
    "{policy} · nuovo codice tra {seconds} secondi": "{policy} · new code in {seconds} seconds",
    "Monouso": "Single use", "Riutilizzabile nel periodo": "Reusable during this period",
    "Retry avviato: {messages} messaggi, {contacts} contatti, {controls} conferme":
        "Retry started: {messages} messages, {contacts} contacts, {controls} confirmations",
    "{messages} messaggi · {contacts} contatti · {controls} conferme":
        "{messages} messages · {contacts} contacts · {controls} confirmations",
    "Scaricare l'installer ufficiale I2P {version} e verificarne la checksum SHA-256?":
        "Download the official I2P {version} installer and verify its SHA-256 checksum?",
    "Non ancora disponibile": "Not available yet",
    "Non calcolabile: gli orologi dei dispositivi non sono sincronizzati":
        "Unavailable: the device clocks are not synchronized",
    "Inviato dal mittente": "Sent by sender", "Ricevuto dal destinatario": "Received by recipient",
    "Ritardo indicato": "Reported delay", "ACK ricevuto sul mittente": "ACK received by sender",
    "Tempo totale andata/ritorno": "Total round-trip time", "Versione": "Version",
    "Destination": "Destination", "Trasporto": "Transport", "Messaggi": "Messages",
    "Profilo tunnel": "Tunnel profile", "Bassa latenza · 2 hop": "Low latency · 2 hops",
    "Massima privacy · 3 hop": "Maximum privacy · 3 hops",
    "Identità": "Identity", "Metadati": "Metadata", "Code locali": "Local queues",
    "ONLINE": "ONLINE", "OFFLINE": "OFFLINE", "Tunnel pronto · SAM locale": "Tunnel ready · local SAM",
    "I2P: connesso": "I2P: connected", "I2P: non connesso": "I2P: disconnected",
    "Canale I2P pronto": "I2P channel ready", "Richiesta contatto rifiutata": "Contact request rejected",
    "Messaggio inoltrato con nuova cifratura": "Message forwarded with fresh encryption",
})
_ENGLISH.update({
    "Contatto firmato e verificato": "Signed and verified contact",
    "✓  Profilo firmato e verificato": "✓  Signed and verified profile",
    "Identificatore crittografico stabile del contatto.": "Stable cryptographic identifier for this contact.",
    "Identity ID nascosto\nQuesto contatto ha scelto di non mostrarlo nel profilo.":
        "Identity ID hidden\nThis contact chose not to display it on the profile.",
    "Indirizzo I2P": "I2P address",
    "Destination pubblica usata per raggiungere il contatto.":
        "Public destination used to reach this contact.",
    "Paesi e peer I2P": "I2P countries and peers",
    "Osserva gli endpoint pubblici collegati al router locale e richiedi gratuitamente i dettagli di un singolo IP.":
        "View public endpoints connected to the local router and request details for one IP for free.",
    "Aggiorna connessioni": "Refresh connections", "Analisi in corso…": "Scanning…",
    "Premi Aggiorna connessioni per rilevare i peer del router I2P locale.":
        "Select Refresh connections to detect peers of the local I2P router.",
    "Lettura delle connessioni del router I2P locale…": "Reading local I2P router connections…",
    "Nessun peer pubblico I2P rilevato. Verifica che il router sia avviato.":
        "No public I2P peers detected. Check that the router is running.",
    "{count} peer di trasporto osservati. Non rappresentano necessariamente gli hop esatti dei tunnel.":
        "{count} transport peers observed. They do not necessarily represent the exact tunnel hops.",
    "Paese e rete non ancora richiesti": "Country and network not requested yet",
    "Dettagli IP": "IP details", "Paese sconosciuto": "Unknown country", "Rete sconosciuta": "Unknown network",
    "Info IP non disponibile: {detail}": "IP info unavailable: {detail}",
    "Analisi rete non disponibile: {detail}": "Network scan unavailable: {detail}",
    "Richiesta informazioni IP in corso…": "Requesting IP information…",
    "Connessioni rilevate ({count})": "Detected connections ({count})",
    "Comprimi elenco peer": "Collapse peer list", "Espandi elenco peer": "Expand peer list",
    "Lettura automatica delle connessioni del router I2P locale…":
        "Automatically reading local I2P router connections…",
    "Osserva gli endpoint pubblici collegati al router locale e visualizza automaticamente paese e rete.":
        "View public endpoints connected to the local router with automatic country and network details.",
    "Su Windows usa l’esclusione nativa; su Linux abilita una privacy curtain che nasconde l’app nell’area di notifica.":
        "On Windows it uses native exclusion; on Linux it enables a privacy curtain that hides the app in the system tray.",
    "Linux non offre un’esclusione universale mentre la finestra resta visibile: la modalità privacy la nasconde completamente e permette di riaprirla dall’area di notifica.":
        "Linux provides no universal exclusion while the window remains visible: privacy mode hides it completely and lets you reopen it from the system tray.",
    "Nascondi Kerberus ora": "Hide Kerberus now", "Nascondi per lo streaming": "Hide for streaming",
    "Attiva prima la protezione streaming": "Enable streaming protection first",
    "Area di notifica non disponibile: Kerberus è stato minimizzato":
        "System tray unavailable: Kerberus was minimized",
    "Kerberus è nascosto dalla cattura. Usa l’icona nell’area di notifica per riaprirlo.":
        "Kerberus is hidden from capture. Use the system tray icon to reopen it.",
    "Protezione Linux pronta: usa Nascondi ora per rimuovere Kerberus dalla cattura":
        "Linux protection ready: use Hide now to remove Kerberus from capture",
    "Questa funzione è disponibile su Windows e Linux": "This feature is available on Windows and Linux",
    "La diagnostica di rete richiede il componente psutil": "Network diagnostics requires the psutil component",
    "Indirizzo IP non valido": "Invalid IP address",
    "Le informazioni sono disponibili solo per IP pubblici": "Information is available only for public IPs",
    "Limite giornaliero del servizio IP raggiunto": "Daily IP service limit reached",
    "Risposta del servizio IP troppo grande": "IP service response is too large",
    "Risposta del servizio IP non valida": "Invalid IP service response",
})
_ENGLISH.update({
    "Messaggio vocale": "Voice message",
    "Privacy dei messaggi vocali": "Voice-message privacy",
    "Registra messaggio vocale cifrato": "Record encrypted voice message",
    "Annulla registrazione": "Cancel recording",
    "Termina e invia": "Stop and send",
    "Registrazione vocale annullata": "Voice recording cancelled",
    "Compressione vocale nel helper Go e cifratura…": "Compressing voice in the Go helper and encrypting…",
    "Decodifica vocale con il codec Go…": "Decoding voice with the Go codec…",
    "Riproduzione messaggio vocale cifrato": "Playing encrypted voice message",
    "Nessun microfono disponibile": "No microphone is available",
    "Il formato del microfono non è supportato": "The microphone format is not supported",
    "Impossibile avviare il microfono": "Unable to start the microphone",
    "Il messaggio vocale è troppo breve": "The voice message is too short",
    "Durata vocale": "Voice duration",
    "Codifica Go": "Go encoding",
    "Decodifica Go": "Go decoding",
    "Registrazione {minutes}:{seconds:02d} · massimo 2:00": "Recording {minutes}:{seconds:02d} · maximum 2:00",
    "Il formato del microfono produce troppi dati; seleziona un dispositivo standard":
        "The microphone format produces too much data; select a standard device",
    "Il contenuto sarà cifrato end-to-end e trasportato soltanto tramite I2P. Durata, dimensione e tempistica del traffico possono comunque essere osservabili e correlate. Il microfono resta attivo soltanto durante la registrazione visibile. Continuare?":
        "Content is end-to-end encrypted and transported only through I2P. Traffic duration, size, and timing may still be observable and correlated. The microphone remains active only during visible recording. Continue?",
    "Audio e messaggi vocali": "Audio and voice messages",
    "Scegli il microfono e le cuffie usati da Kerberus e verifica il percorso audio completo.":
        "Choose the microphone and headphones used by Kerberus and verify the complete audio path.",
    "Microfono": "Microphone",
    "Dispositivo usato per registrare i messaggi vocali.": "Device used to record voice messages.",
    "Cuffie o altoparlanti": "Headphones or speakers",
    "Dispositivo sul quale vengono riprodotti messaggi vocali e test.":
        "Device used to play voice messages and tests.",
    "Predefinito di sistema": "System default",
    "Prova uscita": "Test output",
    "Prova microfono (3 s)": "Test microphone (3 s)",
    "Il test microfono registra, comprime e decodifica con il helper Go, poi riproduce sulle cuffie scelte.":
        "The microphone test records, compresses and decodes with the Go helper, then plays through the selected headphones.",
    "Tono inviato al dispositivo di uscita scelto.": "Tone sent to the selected output device.",
    "Registrazione di prova in corso per 3 secondi…": "Test recording in progress for 3 seconds…",
    "Elaborazione con il codec Go…": "Processing with the Go codec…",
    "Test completato: dovresti sentire la registrazione sul dispositivo di uscita scelto.":
        "Test complete: you should hear the recording on the selected output device.",
    "È già in corso una registrazione.": "A recording is already in progress.",
    "Aspetto": "Appearance",
    "Tema e interfaccia": "Theme and interface",
    "Personalizza colori, leggibilità e spaziatura dei controlli.":
        "Customize colors, readability, and control spacing.",
    "Tema dell’applicazione": "Application theme",
    "Cambia la palette di tutta l’interfaccia senza riavviare Kerberus.":
        "Change the entire interface palette without restarting Kerberus.",
    "Predefinito": "Default", "Rosa": "Pink", "Arancione": "Orange",
    "Bianco": "White", "Scuro": "Dark",
    "Dimensione del testo": "Text size",
    "Aumenta o riduci il testo mantenendo invariato il contenuto.":
        "Increase or reduce text size without changing content.",
    "Densità dell’interfaccia": "Interface density",
    "Regola lo spazio verticale di pulsanti, menu e campi.":
        "Adjust the vertical spacing of buttons, menus, and fields.",
    "Compatta": "Compact", "Bilanciata": "Balanced", "Spaziosa": "Spacious",
    "Anteprima palette": "Palette preview",
    "Le modifiche di aspetto vengono applicate immediatamente e salvate nel vault locale.":
        "Appearance changes are applied immediately and stored in the local vault.",
    "Emoji e simboli": "Emoji and symbols",
    "Scegli un’emoji o cercala per nome.": "Choose an emoji or search for it by name.",
    "Reazioni al messaggio": "Message reactions",
    "Chiudi pannello emoji": "Close emoji panel",
    "Apri menu emoji": "Open emoji menu",
    "Evento protocollo": "Protocol event",
    "Apertura Console UI": "Opening UI console",
    "Apertura Impostazioni": "Opening Settings",
    "Apertura Nuovo contatto": "Opening New contact",
    "Apertura Profilo": "Opening Profile",
    "Apertura Stato I2P": "Opening I2P status",
    "Invio messaggio richiesto": "Message send requested",
    "Impostazioni privacy aggiornate": "Privacy settings updated",
    "Policy rete e ricevute aggiornata": "Network and receipt policy updated",
    "Dispositivi audio aggiornati": "Audio devices updated",
    "Aspetto dell’interfaccia aggiornato": "Interface appearance updated",
    "Richiesta contatto annullata localmente": "Contact request cancelled locally",
    "Conferma contatto restituita sullo stesso stream I2P":
        "Contact confirmation returned over the same I2P stream",
    "Conferma contatto inserita nella coda I2P": "Contact confirmation added to the I2P queue",
    "Il contatto ha aggiornato la visibilità del proprio Identity ID":
        "The contact updated the visibility of their Identity ID",
    "Nessuna conferma ricevuta entro 10 minuti": "No confirmation received within 10 minutes",
    "Frame affidato a SAM; attendo la conferma firmata del destinatario":
        "Frame handed to SAM; waiting for the recipient’s signed confirmation",
    "Messaggio consegnato e confermato": "Message delivered and confirmed",
})
_ITALIAN = {value: key for key, value in _ENGLISH.items()}

_RUNTIME_ENGLISH_REPLACEMENTS = (
    ("Evento protocollo", "Protocol event"),
    ("Impostazioni privacy aggiornate", "Privacy settings updated"),
    ("Policy rete e ricevute aggiornata", "Network and receipt policy updated"),
    ("Dispositivi audio aggiornati", "Audio devices updated"),
    ("Aspetto dell’interfaccia aggiornato", "Interface appearance updated"),
    ("Richiesta contatto annullata localmente", "Contact request cancelled locally"),
    ("Conferma contatto restituita sullo stesso stream I2P", "Contact confirmation returned over the same I2P stream"),
    ("Conferma contatto inserita nella coda I2P", "Contact confirmation added to the I2P queue"),
    ("Il contatto ha aggiornato la visibilità del proprio Identity ID", "The contact updated the visibility of their Identity ID"),
    ("Nessuna conferma ricevuta entro 10 minuti", "No confirmation received within 10 minutes"),
    ("Frame affidato a SAM; attendo la conferma firmata del destinatario", "Frame handed to SAM; waiting for the recipient’s signed confirmation"),
    ("Messaggio consegnato e confermato", "Message delivered and confirmed"),
    ("Frame I2P ricevuto ma rifiutato", "I2P frame received but rejected"),
    ("Retry immediato", "Immediate retry"),
    (" messaggi", " messages"),
    (" contatti", " contacts"),
    (" conferme", " confirmations"),
    ("Profilo I2P applicato", "I2P profile applied"),
    ("bassa latenza", "low latency"),
    ("massima privacy", "maximum privacy"),
    ("Messaggio vocale cifrato ricevuto da", "Encrypted voice message received from"),
    ("Messaggio cifrato ricevuto da", "Encrypted message received from"),
    ("Ritrasmissione valida ricevuta da", "Valid retransmission received from"),
    ("Richiesta valida ricevuta da", "Valid request received from"),
    ("Contatto confermato", "Contact confirmed"),
    ("Destinatario non raggiungibile; nuovo tentativo automatico", "Recipient unreachable; new automatic attempt"),
    ("Conferma di protocollo in coda; retry I2P", "Protocol confirmation queued; I2P retry"),
    ("Errore nella coda", "Queue error"),
    ("Invio I2P fallito dopo", "I2P send failed after"),
    ("Frame scritto sullo stream in", "Frame written to the stream in"),
    ("attendo conferma cifrata", "waiting for encrypted ACK"),
)


def set_language(language: str) -> None:
    global _LANGUAGE
    _LANGUAGE = language if language in {"it", "en"} else "it"


def tr(text: str) -> str:
    return _ENGLISH.get(text, text) if _LANGUAGE == "en" else _ITALIAN.get(text, text)


def tr_format(text: str, **values: object) -> str:
    return tr(text).format(**values)


def tr_runtime(text: str) -> str:
    """Translate diagnostic text that may contain runtime values."""
    if _LANGUAGE != "en":
        return tr(text)
    translated = _ENGLISH.get(text)
    if translated is not None:
        return translated
    for italian, english in _RUNTIME_ENGLISH_REPLACEMENTS:
        text = text.replace(italian, english)
    return text


def localize_widget(root: QWidget) -> None:
    if isinstance(root, QDialog):
        root.setWindowTitle(tr(root.windowTitle()))
    for widget in [root, *root.findChildren(QWidget)]:
        if isinstance(widget, (QLabel, QPushButton, QToolButton, QCheckBox)) and widget.text():
            widget.setText(tr(widget.text()))
        if isinstance(widget, QLineEdit) and widget.placeholderText():
            widget.setPlaceholderText(tr(widget.placeholderText()))
        if isinstance(widget, QPlainTextEdit) and widget.placeholderText():
            widget.setPlaceholderText(tr(widget.placeholderText()))
        if isinstance(widget, QComboBox):
            for index in range(widget.count()):
                widget.setItemText(index, tr(widget.itemText(index)))
        if widget.toolTip():
            widget.setToolTip(tr(widget.toolTip()))

ICON_DIR = Path(__file__).resolve().parent / "assets" / "lucide"


def lucide_icon(name: str, color: str = "#aeb8c4", size: int = 24) -> QIcon:
    source = (ICON_DIR / f"{name}.svg").read_text("utf-8").replace("currentColor", color)
    renderer = QSvgRenderer(QByteArray(source.encode("utf-8")))
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return QIcon(pixmap)


def audio_device_id(device: object) -> str:
    """Return a JSON-safe opaque identifier for a Qt audio device."""
    try:
        return bytes(device.id()).hex()
    except (AttributeError, TypeError, ValueError):
        return ""


def resolve_audio_device(devices: list[object], stored_id: str, default: object) -> object:
    """Resolve a saved device, falling back safely when hardware was removed."""
    if stored_id:
        for device in devices:
            if audio_device_id(device) == stored_id:
                return device
    return default


def available_audio_inputs() -> list[object]:
    return list(QMediaDevices.audioInputs())


def available_audio_outputs() -> list[object]:
    return list(QMediaDevices.audioOutputs())


def avatar_pixmap(identity: IdentityBundle, size: int) -> QPixmap:
    canvas = QPixmap(size, size)
    canvas.fill(Qt.GlobalColor.transparent)
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    path.addEllipse(0, 0, size, size)
    painter.setClipPath(path)
    if identity.avatar_data:
        image = QImage.fromData(unb64(identity.avatar_data), "PNG")
        scaled = image.scaled(
            size,
            size,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        x = max(0, (scaled.width() - size) // 2)
        y = max(0, (scaled.height() - size) // 2)
        painter.drawImage(0, 0, scaled.copy(x, y, size, size))
    else:
        painter.fillPath(path, QColor(COLORS["accent_dark"]))
        painter.setPen(QColor(COLORS["accent"]))
        font = painter.font()
        font.setBold(True)
        font.setPixelSize(max(13, size // 2))
        painter.setFont(font)
        painter.drawText(QRect(0, 0, size, size), Qt.AlignmentFlag.AlignCenter, identity.name[:1].upper() or "?")
    painter.end()
    return canvas


def set_avatar(label: QLabel, identity: IdentityBundle, size: int) -> None:
    label.setFixedSize(size, size)
    label.setPixmap(avatar_pixmap(identity, size))


def build_style(text_scale: int = 100, density: str = "comfortable") -> str:
    font_size = max(12, min(18, round(14 * text_scale / 100)))
    control_padding = {"compact": 7, "comfortable": 9, "spacious": 12}.get(density, 9)
    field_padding = {"compact": 8, "comfortable": 10, "spacious": 13}.get(density, 10)
    nav_padding = {"compact": 8, "comfortable": 11, "spacious": 14}.get(density, 11)
    return f"""
* {{
    font-family: "Segoe UI";
    font-size: {font_size}px;
    color: {COLORS['text']};
}}
QMainWindow {{ background: transparent; }}
QDialog {{ background: transparent; }}
QFrame#appShell, QFrame#dialogShell {{ background: {COLORS['window']}; border: 1px solid {COLORS['border']}; border-radius: 12px; }}
QFrame#titlebar {{ background: {COLORS['sidebar']}; border-bottom: 1px solid {COLORS['border']}; }}
QFrame#sidebar {{ background: {COLORS['sidebar']}; border-right: 1px solid {COLORS['border']}; }}
QFrame#topbar {{ background: {COLORS['window']}; border-bottom: 1px solid {COLORS['border']}; }}
QFrame#composer {{ background: {COLORS['window']}; border-top: 1px solid {COLORS['border']}; }}
QFrame#emojiPanel {{ background: {COLORS['sidebar']}; border-top: 1px solid {COLORS['border']}; }}
QFrame#emojiHeader {{ background: transparent; border: 0; }}
QLabel#emojiPanelTitle {{ color: {COLORS['text']}; font-size: 16px; font-weight: 700; }}
QLineEdit#emojiSearch {{ background: {COLORS['window']}; border-radius: 9px; }}
QFrame#emojiCategories {{ background: {COLORS['surface']}; border: 1px solid {COLORS['border']}; border-radius: 9px; }}
QScrollArea#emojiScroll {{ background: {COLORS['surface']}; border: 1px solid {COLORS['border']}; border-radius: 10px; }}
QFrame#emojiFooter {{ background: {COLORS['sidebar']}; border: 0; border-top: 1px solid {COLORS['border']}; }}
QFrame#settingsSidebar {{ background: {COLORS['sidebar']}; border: 1px solid {COLORS['border']}; border-radius: 10px; }}
QFrame#settingsCard {{ background: {COLORS['surface']}; border: 1px solid {COLORS['border']}; border-radius: 10px; }}
QFrame#settingsRow {{ background: transparent; border-top: 1px solid {COLORS['border']}; }}
QFrame#inlineConfirmation {{
    background: #2a2218;
    border-top: 1px solid #6b512d;
    border-bottom: 1px solid #6b512d;
}}
QPushButton#confirmLowLatency {{ background: {COLORS['warning']}; color: #20170b; font-weight: 700; }}
QPushButton#confirmLowLatency:hover {{ background: #f6c574; }}
QFrame#chatSettingsPanel {{ background: {COLORS['sidebar']}; border-left: 1px solid {COLORS['border']}; }}
QLabel#brand {{ font-size: 20px; font-weight: 700; color: {COLORS['text']}; }}
QLabel#pageTitle {{ font-size: 18px; font-weight: 650; }}
QLabel#dialogTitle {{ font-size: 22px; font-weight: 700; }}
QLabel#muted, QLabel#contactMeta, QLabel#timestamp {{ color: {COLORS['muted']}; }}
QLabel#eyebrow {{ color: {COLORS['accent']}; font-size: 12px; font-weight: 700; }}
QLineEdit, QPlainTextEdit {{
    background: {COLORS['surface_2']};
    border: 1px solid {COLORS['border']};
    border-radius: 7px;
    padding: {field_padding}px 12px;
    selection-background-color: {COLORS['accent_dark']};
}}
QLineEdit:focus, QPlainTextEdit:focus {{ border-color: {COLORS['accent']}; }}
QPushButton {{
    background: {COLORS['surface_2']};
    border: 1px solid {COLORS['border']};
    border-radius: 7px;
    padding: {control_padding}px 14px;
    font-weight: 600;
}}
QPushButton:hover {{ background: {COLORS['surface_3']}; border-color: {COLORS['faint']}; }}
QPushButton:pressed {{ background: {COLORS['sidebar']}; }}
QPushButton#primary {{ background: {COLORS['accent']}; color: #07120e; border: 0; }}
QPushButton#primary:hover {{ background: {COLORS['accent_hover']}; }}
QPushButton#ghost {{ background: transparent; border: 0; color: {COLORS['muted']}; }}
QPushButton#ghost:hover {{ color: {COLORS['text']}; background: {COLORS['surface_2']}; }}
QPushButton#settingsNav {{ background: transparent; border: 0; padding: {nav_padding}px 12px; text-align: left; color: {COLORS['muted']}; }}
QPushButton#settingsNav:hover {{ background: {COLORS['surface_2']}; color: {COLORS['text']}; }}
QPushButton#settingsNav:checked {{ background: {COLORS['accent_dark']}; color: {COLORS['accent']}; }}
QToolButton {{
    background: transparent;
    border: 0;
    border-radius: 7px;
    padding: 8px;
}}
QToolButton:hover {{ background: {COLORS['surface_2']}; }}
QToolButton#sendButton {{ background: {COLORS['accent']}; color: #07120e; }}
QToolButton#sendButton:hover {{ background: {COLORS['accent_hover']}; }}
QToolButton#attachmentButton {{ background: {COLORS['surface_2']}; border: 1px solid {COLORS['border']}; border-radius: 24px; }}
QToolButton#attachmentButton:hover {{ background: {COLORS['surface_3']}; border-color: {COLORS['accent']}; }}
QToolButton#timingButton {{ padding: 1px; border-radius: 4px; }}
QToolButton#emojiToggle {{ border: 1px solid transparent; }}
QToolButton#emojiToggle:hover {{ border-color: {COLORS['border']}; }}
QToolButton#emojiToggle[active="true"] {{ background: {COLORS['accent_dark']}; border-color: {COLORS['accent']}; color: {COLORS['accent']}; }}
QToolButton#chatSettingsToggle[active="true"] {{ background: {COLORS['accent_dark']}; color: {COLORS['accent']}; }}
QToolButton#emojiCategory {{ background: transparent; border-radius: 7px; padding: 4px; }}
QToolButton#emojiCategory:hover {{ background: {COLORS['surface_2']}; }}
QToolButton#emojiCategory[active="true"] {{ background: {COLORS['accent_dark']}; color: {COLORS['accent']}; }}
QToolButton#emojiItem {{ background: transparent; border: 1px solid transparent; border-radius: 8px; padding: 2px; }}
QToolButton#emojiItem:hover {{ background: {COLORS['surface_3']}; border-color: {COLORS['border']}; }}
QToolButton#emojiPager {{ background: {COLORS['surface_2']}; border: 1px solid {COLORS['border']}; border-radius: 7px; padding: 5px; }}
QToolButton#emojiPager:hover {{ background: {COLORS['surface_3']}; border-color: {COLORS['faint']}; }}
QToolButton#emojiClose {{ background: transparent; border: 1px solid transparent; border-radius: 7px; padding: 6px; }}
QToolButton#emojiClose:hover {{ background: {COLORS['surface_2']}; border-color: {COLORS['border']}; }}
QToolButton#windowButton {{ border-radius: 0; padding: 0; }}
QToolButton#windowButton:hover {{ background: {COLORS['surface_3']}; }}
QToolButton#closeButton {{ border-radius: 0; padding: 0; }}
QToolButton#closeButton:hover {{ background: {COLORS['danger']}; }}
QListWidget {{ background: transparent; border: 0; outline: 0; padding: 0; }}
QListWidget::item {{ border: 0; padding: 0; }}
QListWidget::item:selected {{ background: {COLORS['surface_2']}; border-radius: 6px; }}
QListWidget::item:hover:!selected {{ background: {COLORS['surface_2']}; border-radius: 6px; }}
QScrollArea {{ background: transparent; border: 0; }}
QScrollBar:vertical {{ background: transparent; width: 14px; margin: 2px 2px 2px 0; }}
QScrollBar::handle:vertical {{ background: {COLORS['border']}; border-radius: 5px; min-height: 42px; }}
QScrollBar::handle:vertical:hover {{ background: {COLORS['faint']}; }}
QScrollBar::handle:vertical:pressed {{ background: {COLORS['accent']}; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QProgressBar {{ background: {COLORS['surface_2']}; border: 0; border-radius: 5px; min-height: 10px; }}
QProgressBar::chunk {{ background: {COLORS['accent']}; border-radius: 5px; }}
QComboBox {{
    background: {COLORS['surface_2']};
    border: 1px solid {COLORS['border']};
    border-radius: 8px;
    min-height: 20px;
    padding: {control_padding}px 42px {control_padding}px 12px;
    selection-background-color: {COLORS['accent_dark']};
}}
QComboBox:hover {{ background: {COLORS['surface_3']}; border-color: {COLORS['faint']}; }}
QComboBox:focus, QComboBox:on {{ border-color: {COLORS['accent']}; }}
QComboBox:disabled {{ color: {COLORS['faint']}; background: {COLORS['surface']}; }}
QComboBox::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 34px;
    border-left: 1px solid {COLORS['border']};
    border-top-right-radius: 8px;
    border-bottom-right-radius: 8px;
}}
QComboBox::down-arrow {{ image: url("{(ICON_DIR / 'chevron-down.svg').as_posix()}"); width: 15px; height: 15px; }}
QComboBox QAbstractItemView {{
    background: {COLORS['surface_2']};
    border: 1px solid {COLORS['faint']};
    border-radius: 8px;
    padding: 6px;
    outline: 0;
    selection-background-color: {COLORS['accent_dark']};
    selection-color: {COLORS['text']};
}}
QComboBox QAbstractItemView::item {{ min-height: 36px; padding: 7px 11px; border-radius: 6px; }}
QFrame#dropdownPopup {{
    background: {COLORS['surface_2']};
    border: 1px solid {COLORS['faint']};
    border-radius: 10px;
}}
QFrame#dropdownOptionHost {{ background: {COLORS['surface_2']}; border: 0; }}
QPushButton#dropdownOption {{
    background: transparent;
    border: 0;
    border-radius: 7px;
    color: {COLORS['text']};
    min-height: 22px;
    padding: 8px 12px;
    text-align: left;
}}
QPushButton#dropdownOption:hover {{ background: {COLORS['surface_3']}; }}
QPushButton#dropdownOption:focus {{ background: {COLORS['surface_3']}; border: 1px solid {COLORS['faint']}; }}
QPushButton#dropdownOption:pressed {{ background: {COLORS['accent_dark']}; }}
QPushButton#dropdownOption[selected="true"] {{
    background: {COLORS['accent_dark']};
    color: {COLORS['accent']};
    font-weight: 650;
}}
QPushButton#dropdownOption:disabled {{ color: {COLORS['faint']}; }}
QMenu {{
    background: {COLORS['surface_2']};
    border: 1px solid #46515e;
    border-radius: 9px;
    padding: 7px;
}}
QMenu::item {{ min-width: 170px; padding: 9px 28px 9px 12px; border-radius: 6px; }}
QMenu::item:selected {{ background: {COLORS['accent_dark']}; color: {COLORS['text']}; }}
QMenu::item:disabled {{ color: {COLORS['faint']}; }}
QMenu::separator {{ height: 1px; background: {COLORS['border']}; margin: 6px 8px; }}
QMenu::right-arrow {{ image: url("{(ICON_DIR / 'chevron-right.svg').as_posix()}"); width: 13px; height: 13px; }}
QCheckBox {{ spacing: 9px; }}
"""


STYLE = build_style()


def apply_appearance(theme: str, text_scale: int, density: str) -> tuple[str, int, str]:
    """Apply a validated palette, text scale and control density application-wide."""
    global STYLE
    selected_theme = theme if theme in THEMES else "default"
    selected_scale = text_scale if text_scale in {90, 100, 110, 120} else 100
    selected_density = density if density in {"compact", "comfortable", "spacious"} else "comfortable"
    COLORS.clear()
    COLORS.update(THEMES[selected_theme])
    STYLE = build_style(selected_scale, selected_density)
    application = QApplication.instance()
    if application is not None:
        application.setStyleSheet(STYLE)
    return selected_theme, selected_scale, selected_density


def set_window_capture_exclusion(window: QWidget, enabled: bool) -> tuple[bool, str]:
    """Apply native capture exclusion, or prepare Linux privacy-curtain mode."""
    if sys.platform.startswith("linux"):
        return True, (
            "Protezione Linux pronta: usa Nascondi ora per rimuovere Kerberus dalla cattura"
            if enabled else "Protezione streaming disattivata"
        )
    if sys.platform != "win32":
        return False, "Questa funzione è disponibile su Windows e Linux"
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        set_affinity = user32.SetWindowDisplayAffinity
        set_affinity.argtypes = (wintypes.HWND, wintypes.DWORD)
        set_affinity.restype = wintypes.BOOL
        affinity = 0x00000011 if enabled else 0x00000000  # WDA_EXCLUDEFROMCAPTURE / WDA_NONE
        if not set_affinity(wintypes.HWND(int(window.winId())), wintypes.DWORD(affinity)):
            error = ctypes.get_last_error()
            return False, str(ctypes.WinError(error))
        return True, "Protezione streaming attiva" if enabled else "Protezione streaming disattivata"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


class DropdownItemDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index) -> QSize:
        size = super().sizeHint(option, index)
        size.setHeight(max(40, size.height()))
        return size


class DropdownPopup(QFrame):
    """Styled popup used by ModernComboBox instead of the platform menu."""

    def __init__(self, combo: "ModernComboBox"):
        super().__init__(combo, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.combo = combo
        self.setObjectName("dropdownPopup")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(1, 1, 1, 1)
        outer.setSpacing(0)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded if combo.count() > combo.maxVisibleItems()
            else Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.scroll.setStyleSheet("QScrollArea { background: transparent; border: 0; }")
        host = QFrame()
        host.setObjectName("dropdownOptionHost")
        layout = QVBoxLayout(host)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(2)
        self.buttons: list[QPushButton] = []
        for item_index in range(combo.count()):
            model_index = combo.model().index(item_index, combo.modelColumn(), combo.rootModelIndex())
            enabled = bool(combo.model().flags(model_index) & Qt.ItemFlag.ItemIsEnabled)
            selected = item_index == combo.currentIndex()
            button = QPushButton(combo.itemText(item_index))
            button.setObjectName("dropdownOption")
            button.setProperty("selected", selected)
            button.setIcon(lucide_icon("check", COLORS["accent"] if selected else COLORS["surface_2"], 16))
            button.setIconSize(QSize(16, 16))
            button.setFixedHeight(40)
            button.setEnabled(enabled)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.installEventFilter(self)
            button.clicked.connect(lambda _checked=False, index=item_index: self.choose(index))
            layout.addWidget(button)
            self.buttons.append(button)
        layout.addStretch(1)
        self.scroll.setWidget(host)
        outer.addWidget(self.scroll)

        visible_rows = max(1, min(combo.count(), combo.maxVisibleItems()))
        self.setFixedHeight(visible_rows * 42 + 14)
        if 0 <= combo.currentIndex() < len(self.buttons):
            QTimer.singleShot(0, lambda: self.scroll.ensureWidgetVisible(self.buttons[combo.currentIndex()]))

    def choose(self, index: int) -> None:
        if not 0 <= index < self.combo.count():
            return
        self.combo.setCurrentIndex(index)
        self.combo.activated.emit(index)
        self.close()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.KeyPress and isinstance(event, QKeyEvent):
            if event.key() == Qt.Key.Key_Escape:
                self.close()
                self.combo.setFocus(Qt.FocusReason.PopupFocusReason)
                return True
            if event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_Home, Qt.Key.Key_End):
                enabled = [button for button in self.buttons if button.isEnabled()]
                if not enabled:
                    return True
                current = enabled.index(watched) if watched in enabled else 0
                if event.key() == Qt.Key.Key_Home:
                    target = 0
                elif event.key() == Qt.Key.Key_End:
                    target = len(enabled) - 1
                else:
                    step = -1 if event.key() == Qt.Key.Key_Up else 1
                    target = (current + step) % len(enabled)
                enabled[target].setFocus(Qt.FocusReason.TabFocusReason)
                self.scroll.ensureWidgetVisible(enabled[target])
                return True
        return super().eventFilter(watched, event)


class ModernComboBox(QComboBox):
    """Compact custom dropdown that ignores wheel changes while closed."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setItemDelegate(DropdownItemDelegate(self))
        self.setMaxVisibleItems(10)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._popup: DropdownPopup | None = None

    def showPopup(self) -> None:
        if self.count() <= 0:
            return
        if self._popup is not None:
            self._popup.close()
        widest = max(
            (self.fontMetrics().horizontalAdvance(self.itemText(index)) for index in range(self.count())),
            default=0,
        )
        popup = DropdownPopup(self)
        self._popup = popup
        popup.destroyed.connect(lambda _object=None, closed=popup: self._popup_closed(closed))
        popup_width = max(self.width(), min(widest + 76, 460))
        popup.setFixedWidth(popup_width)
        position = self.mapToGlobal(QPoint(0, self.height() + 5))
        screen = self.screen().availableGeometry()
        if position.x() + popup_width > screen.right():
            position.setX(screen.right() - popup_width)
        if position.y() + popup.height() > screen.bottom():
            position.setY(self.mapToGlobal(QPoint(0, -popup.height() - 5)).y())
        position.setX(max(screen.left(), position.x()))
        position.setY(max(screen.top(), position.y()))
        popup.move(position)
        popup.show()
        popup.raise_()
        if 0 <= self.currentIndex() < len(popup.buttons):
            popup.buttons[self.currentIndex()].setFocus(Qt.FocusReason.PopupFocusReason)

    def hidePopup(self) -> None:
        if self._popup is not None:
            self._popup.close()
        else:
            super().hidePopup()

    def _popup_closed(self, popup: DropdownPopup) -> None:
        if self._popup is popup:
            self._popup = None

    def wheelEvent(self, event: QWheelEvent) -> None:
        event.ignore()


class ChatMessageModel(QAbstractListModel):
    MessageRole = int(Qt.ItemDataRole.UserRole) + 1

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self.messages: list[dict] = []

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.messages)

    def data(self, index: QModelIndex, role: int = int(Qt.ItemDataRole.DisplayRole)):
        if not index.isValid() or not 0 <= index.row() < len(self.messages):
            return None
        message = self.messages[index.row()]
        if role == self.MessageRole:
            return message
        if role == int(Qt.ItemDataRole.DisplayRole):
            return str(message.get("text", ""))
        return None

    def set_messages(self, messages: list[dict]) -> None:
        self.beginResetModel()
        self.messages = [dict(message) for message in messages]
        self.endResetModel()

    def append_messages(self, messages: list[dict]) -> None:
        if not messages:
            return
        first = len(self.messages)
        self.beginInsertRows(QModelIndex(), first, first + len(messages) - 1)
        self.messages.extend(dict(message) for message in messages)
        self.endInsertRows()

    def update_messages(self, messages: list[dict]) -> None:
        self.messages = [dict(message) for message in messages]
        if self.messages:
            self.dataChanged.emit(
                self.index(0, 0), self.index(len(self.messages) - 1, 0),
                [self.MessageRole, int(Qt.ItemDataRole.DisplayRole)],
            )


def is_emoji_reaction(text: str, maximum_emoji: int = 6) -> bool:
    """Return whether *text* is a short, emoji-only reaction message."""
    compact = re.sub(r"\s+", "", str(text).strip())
    if not compact:
        return False
    emoji_items = emoji_data.emoji_list(compact)
    return 1 <= len(emoji_items) <= maximum_emoji and emoji_data.purely_emoji(compact)


def reaction_items(reactions: object) -> tuple[tuple[str, str], ...]:
    """Flatten legacy strings and current per-user reaction lists for rendering."""
    if not isinstance(reactions, dict):
        return ()
    items: list[tuple[str, str]] = []
    for owner, stored in reactions.items():
        values = stored if isinstance(stored, list) else [stored] if isinstance(stored, str) else []
        seen: set[str] = set()
        for value in values:
            emoji = str(value)
            if emoji_data.is_emoji(emoji) and emoji not in seen:
                items.append((str(owner), emoji))
                seen.add(emoji)
    return tuple(items)


def reaction_groups(reactions: object) -> tuple[tuple[str, tuple[str, ...]], ...]:
    grouped: dict[str, list[str]] = {}
    for owner, emoji in reaction_items(reactions):
        grouped.setdefault(emoji, []).append(owner)
    return tuple((emoji, tuple(owners)) for emoji, owners in grouped.items())


def format_file_size(value: object) -> str:
    try:
        size = max(0, int(value))
    except (TypeError, ValueError):
        size = 0
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


class ChatMessageDelegate(QStyledItemDelegate):
    def __init__(self, view: "VirtualChatView"):
        super().__init__(view)
        self.view = view
        self.local_identity: IdentityBundle | None = None
        self.remote_identity: IdentityBundle | None = None
        self.local_avatar: QPixmap | None = None
        self.remote_avatar: QPixmap | None = None
        self.link_previews = False
        self.preview_cache: dict[str, dict] = {}
        self.preview_requested: Callable[[str], None] | None = None
        self._preview_images: dict[str, QImage] = {}
        self._attachment_images: dict[str, QImage] = {}

    def configure(
        self,
        local_identity: IdentityBundle | None,
        remote_identity: IdentityBundle | None,
        local_avatar: QPixmap | None,
        remote_avatar: QPixmap | None,
        link_previews: bool,
        preview_cache: dict[str, dict] | None = None,
        preview_requested: Callable[[str], None] | None = None,
    ) -> None:
        self.local_identity = local_identity
        self.remote_identity = remote_identity
        self.local_avatar = local_avatar
        self.remote_avatar = remote_avatar
        self.link_previews = link_previews
        self.preview_cache = preview_cache if preview_cache is not None else {}
        self.preview_requested = preview_requested

    def invalidate_preview(self, url: str) -> None:
        self._preview_images.pop(url, None)

    def _preview_image(self, url: str, preview: dict) -> QImage | None:
        cached = self._preview_images.get(url)
        if cached is not None:
            return cached if not cached.isNull() else None
        image = QImage()
        raw_image = preview.get("image", b"")
        if isinstance(raw_image, bytes) and raw_image:
            image.loadFromData(raw_image)
        self._preview_images[url] = image
        return image if not image.isNull() else None

    def _preview_layout(self, url: str, preview: dict | None, width: int, font: QFont) -> dict[str, object]:
        if preview is None:
            return {"state": "loading", "height": 66, "image": None, "image_height": 0}
        if preview.get("_error"):
            return {"state": "error", "height": 66, "image": None, "image_height": 0}

        inner_width = max(120, width - 22)
        image = self._preview_image(url, preview)
        image_height = 0
        if image is not None:
            image_height = min(138, max(82, round(image.height() * inner_width / max(1, image.width()))))
        title_font = QFont(font)
        title_font.setPointSizeF(max(10.0, title_font.pointSizeF() + 0.5))
        title_font.setBold(True)
        small_font = QFont(font)
        small_font.setPointSizeF(max(8.0, small_font.pointSizeF() - 1.5))
        title = str(preview.get("title") or url)
        description = str(preview.get("description") or "")
        author = str(preview.get("author") or "")
        title_height = min(42, max(18, QFontMetrics(title_font).boundingRect(
            QRect(0, 0, inner_width, 10_000),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap), title,
        ).height()))
        description_height = 0
        if description:
            description_height = min(38, max(16, QFontMetrics(small_font).boundingRect(
                QRect(0, 0, inner_width, 10_000),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap), description,
            ).height()))
        text_height = 10 + 16 + 4 + title_height
        if author:
            text_height += 18
        if description_height:
            text_height += 5 + description_height
        text_height += 11
        return {
            "state": "ready", "height": image_height + text_height,
            "image": image, "image_height": image_height,
            "title_height": title_height, "description_height": description_height,
        }

    @staticmethod
    def _metadata(message: dict, outgoing: bool) -> str:
        timestamp = int(message.get("sent_at", message.get("time", 0)) or 0)
        metadata = datetime.fromtimestamp(timestamp).strftime("%H:%M") if timestamp else ""
        if outgoing:
            marks = {"pending": "◷", "sent": "✓", "delivered": "✓✓", "read": "✓✓"}
            metadata += "  " + marks.get(str(message.get("status", "")), "✓")
        return metadata.strip()

    @staticmethod
    def _url_spans(text: str) -> list[tuple[str, int, int]]:
        spans: list[tuple[str, int, int]] = []
        offset = 0
        for url in extract_urls(text):
            start = text.find(url, offset)
            if start >= 0:
                spans.append((url, start, start + len(url)))
                offset = start + len(url)
        return spans

    def _body_layout(self, text: str, font: QFont, width: int, styled_links: bool = False) -> QTextLayout:
        layout = QTextLayout(text, font)
        option = QTextOption()
        option.setWrapMode(QTextOption.WrapMode.WordWrap)
        layout.setTextOption(option)
        if styled_links:
            formats: list[QTextLayout.FormatRange] = []
            for _url, start, end in self._url_spans(text):
                text_format = QTextCharFormat()
                text_format.setForeground(QColor(COLORS["cyan"]))
                text_format.setFontUnderline(True)
                value = QTextLayout.FormatRange()
                value.start = start
                value.length = end - start
                value.format = text_format
                formats.append(value)
            layout.setFormats(formats)
        layout.beginLayout()
        cursor_y = 0.0
        while True:
            line = layout.createLine()
            if not line.isValid():
                break
            line.setLineWidth(width)
            line.setPosition(QPointF(0, cursor_y))
            cursor_y += line.height()
        layout.endLayout()
        return layout

    @staticmethod
    def _bubble_rect(row_rect: QRect, geometry: dict[str, object]) -> QRect:
        bubble_width = int(geometry["bubble_width"])
        if bool(geometry["outgoing"]):
            bubble_x = row_rect.right() - 20 - 43 - bubble_width
        else:
            bubble_x = row_rect.left() + 20 + 43
        return QRect(bubble_x, row_rect.top() + 4, bubble_width, int(geometry["bubble_height"]))

    def link_regions(self, message: dict, row_rect: QRect, font: QFont) -> list[tuple[str, QRectF]]:
        geometry = self._layout(message, row_rect.width(), font)
        urls = geometry.get("urls", ())
        if not isinstance(urls, tuple) or not urls:
            return []
        regions: list[tuple[str, QRectF]] = []
        bubble_rect = self._bubble_rect(row_rect, geometry)
        body_x = bubble_rect.left() + 14
        body_y = bubble_rect.top() + 10 + int(geometry["author_height"])
        content_width = bubble_rect.width() - 28
        preview_link = str(geometry.get("link", ""))
        preview_geometry = geometry.get("preview_geometry")
        if preview_link and isinstance(preview_geometry, dict):
            preview_y = body_y + int(geometry["body_height"]) + 5
            preview_rect = QRect(body_x, preview_y, content_width, int(preview_geometry["height"]))
            regions.append((preview_link, QRectF(preview_rect)))
        if bool(geometry["emoji_reaction"]):
            return regions
        text = str(geometry["display_text"])
        text_layout = self._body_layout(text, geometry["body_font"], content_width)
        for url, start, end in self._url_spans(text):
            for line_index in range(text_layout.lineCount()):
                line = text_layout.lineAt(line_index)
                line_start = line.textStart()
                line_end = line_start + line.textLength()
                segment_start = max(start, line_start)
                segment_end = min(end, line_end)
                if segment_start >= segment_end:
                    continue
                start_value = line.cursorToX(segment_start)
                end_value = line.cursorToX(segment_end)
                start_x = float(start_value[0] if isinstance(start_value, tuple) else start_value)
                end_x = float(end_value[0] if isinstance(end_value, tuple) else end_value)
                hit_rect = QRectF(
                    body_x + min(start_x, end_x) - 2,
                    body_y + line.y() - 2,
                    max(6.0, abs(end_x - start_x) + 4),
                    line.height() + 4,
                )
                regions.append((url, hit_rect))
        return regions

    def link_at(self, message: dict, row_rect: QRect, font: QFont, position: QPoint) -> str:
        for url, region in self.link_regions(message, row_rect, font):
            if region.contains(QPointF(position)):
                return url
        return ""

    @staticmethod
    def _reaction_rows(
        groups: tuple[tuple[str, tuple[str, ...]], ...],
        font: QFont,
        maximum_width: int,
    ) -> tuple[tuple[tuple[str, tuple[str, ...], str, int], ...], ...]:
        reaction_font = QFont(font)
        reaction_font.setFamilies(["Segoe UI Emoji", "Noto Color Emoji", "Apple Color Emoji"])
        metrics = QFontMetrics(reaction_font)
        rows: list[list[tuple[str, tuple[str, ...], str, int]]] = []
        current: list[tuple[str, tuple[str, ...], str, int]] = []
        used = 0
        for emoji, owners in groups:
            text = f"{emoji} {len(owners)}"
            width = min(maximum_width, metrics.horizontalAdvance(text) + 20)
            required = width + (5 if current else 0)
            if current and used + required > maximum_width:
                rows.append(current)
                current = []
                used = 0
                required = width
            current.append((emoji, owners, text, width))
            used += required
        if current:
            rows.append(current)
        return tuple(tuple(row) for row in rows)

    def reaction_regions(
        self,
        message: dict,
        row_rect: QRect,
        font: QFont,
    ) -> list[tuple[str, tuple[str, ...], QRect]]:
        geometry = self._layout(message, row_rect.width(), font)
        rows = geometry.get("reaction_rows", ())
        if not isinstance(rows, tuple) or not rows:
            return []
        bubble_rect = self._bubble_rect(row_rect, geometry)
        outgoing = bool(geometry["outgoing"])
        y = bubble_rect.bottom() + 4
        regions: list[tuple[str, tuple[str, ...], QRect]] = []
        for row in rows:
            row_width = sum(chip[3] for chip in row) + max(0, len(row) - 1) * 5
            cursor_x = bubble_rect.right() - row_width + 1 if outgoing else bubble_rect.left()
            for emoji, owners, _text, width in row:
                rect = QRect(cursor_x, y, width, 22)
                regions.append((emoji, owners, rect))
                cursor_x += width + 5
            y += 26
        return regions

    def reaction_at(self, message: dict, row_rect: QRect, font: QFont, position: QPoint) -> str:
        local_id = self.local_identity.identity_id if self.local_identity is not None else ""
        for emoji, owners, region in self.reaction_regions(message, row_rect, font):
            if local_id in owners and region.contains(position):
                return emoji
        return ""

    def voice_at(self, message: dict, row_rect: QRect, font: QFont, position: QPoint) -> bool:
        geometry = self._layout(message, row_rect.width(), font)
        if not bool(geometry.get("voice_message")):
            return False
        bubble_rect = self._bubble_rect(row_rect, geometry)
        region = QRect(
            bubble_rect.left() + 10,
            bubble_rect.top() + 8 + int(geometry["author_height"]),
            bubble_rect.width() - 20,
            int(geometry["body_height"]) + 6,
        )
        return region.contains(position)

    def _attachment_image(self, message: dict) -> QImage | None:
        attachment = message.get("attachment")
        if not isinstance(attachment, dict) or not str(attachment.get("mime", "")).startswith("image/"):
            return None
        cache_key = f"{message.get('message_id', '')}:{attachment.get('sha256', '')}"
        cached = self._attachment_images.get(cache_key)
        if cached is not None:
            return cached if not cached.isNull() else None
        image = QImage()
        try:
            encoded = str(attachment.get("data", "")).encode("ascii")
            image.loadFromData(base64.b64decode(encoded, validate=True))
        except (ValueError, UnicodeEncodeError):
            pass
        self._attachment_images[cache_key] = image
        return image if not image.isNull() else None

    def attachment_action_at(self, message: dict, row_rect: QRect, font: QFont, position: QPoint) -> str:
        geometry = self._layout(message, row_rect.width(), font)
        if not bool(geometry.get("attachment_message")):
            return ""
        bubble_rect = self._bubble_rect(row_rect, geometry)
        x = bubble_rect.left() + 14
        y = bubble_rect.top() + 10 + int(geometry["author_height"])
        width = bubble_rect.width() - 28
        content_height = int(geometry.get("attachment_content_height", geometry["body_height"]))
        state = str(geometry.get("attachment_state", "complete"))
        if state in {"transferring", "paused"}:
            controls_y = y + content_height + 12
            pause_button = QRect(x + width - 202, controls_y, 96, 30)
            cancel_button = QRect(x + width - 100, controls_y, 96, 30)
            if pause_button.contains(position):
                return "resume_attachment" if state == "paused" else "pause_attachment"
            if cancel_button.contains(position):
                return "cancel_attachment"
            return ""
        if state != "complete":
            return ""
        if bool(geometry.get("attachment_video")):
            return "play_video" if QRect(x, y, width, content_height - 30).contains(position) else ""
        if not bool(geometry.get("attachment_image")):
            button = QRect(x + width - 104, y + 17, 96, 36)
            return "save_attachment" if button.contains(position) else ""
        return ""

    def video_rect(self, message: dict, row_rect: QRect, font: QFont) -> QRect:
        geometry = self._layout(message, row_rect.width(), font)
        if not bool(geometry.get("attachment_video")) or str(geometry.get("attachment_state", "complete")) != "complete":
            return QRect()
        bubble_rect = self._bubble_rect(row_rect, geometry)
        return QRect(
            bubble_rect.left() + 14,
            bubble_rect.top() + 10 + int(geometry["author_height"]),
            bubble_rect.width() - 28,
            int(geometry.get("attachment_content_height", geometry["body_height"])) - 30,
        )

    def _layout(self, message: dict, width: int, font: QFont) -> dict[str, object]:
        outgoing = message.get("direction") == "out"
        identity = self.local_identity if outgoing else self.remote_identity
        max_bubble_width = max(130, min(560, width - 126))
        max_text_width = max(102, max_bubble_width - 28)
        text = str(message.get("text", ""))
        display_text = text.strip()
        voice = message.get("voice") if message.get("kind") == "voice" else None
        voice_message = isinstance(voice, dict)
        attachment = message.get("attachment") if message.get("kind") == "attachment" else None
        attachment_message = isinstance(attachment, dict)
        attachment_mime = str(attachment.get("mime", "")) if attachment_message else ""
        attachment_image_data = self._attachment_image(message) if attachment_message else None
        attachment_image = attachment_mime.startswith("image/") and attachment_image_data is not None
        attachment_video = attachment_mime.startswith("video/")
        attachment_state = str(attachment.get("state", "complete")) if attachment_message else ""
        attachment_active = attachment_state in {"transferring", "paused"}
        duration_ms = int(voice.get("duration_ms", 0)) if voice_message else 0
        duration_text = f"{duration_ms // 60000}:{duration_ms // 1000 % 60:02d}"
        if voice_message:
            display_text = f"Messaggio vocale  {duration_text}"
        if attachment_message:
            display_text = str(attachment.get("name", "Allegato"))
        emoji_reaction = not voice_message and not attachment_message and is_emoji_reaction(text)
        body_font = QFont(font)
        if emoji_reaction:
            body_font.setFamilies(["Segoe UI Emoji", "Noto Color Emoji", "Apple Color Emoji"])
            body_font.setPointSizeF(20.0 if len(emoji_data.emoji_list(re.sub(r"\s+", "", text))) <= 3 else 17.0)
        body_metrics = QFontMetrics(body_font)

        author_font = QFont(font)
        author_font.setPointSizeF(max(8.0, author_font.pointSizeF() - 1))
        author_font.setBold(True)
        author_width = QFontMetrics(author_font).horizontalAdvance(identity.name) if identity is not None else 0
        meta_font = QFont(font)
        meta_font.setPointSizeF(max(7.5, meta_font.pointSizeF() - 2))
        metadata = self._metadata(message, outgoing)
        metadata_width = QFontMetrics(meta_font).horizontalAdvance(metadata)

        lines = display_text.splitlines() or [""]
        natural_text_width = max((body_metrics.horizontalAdvance(line) for line in lines), default=0)
        urls = () if voice_message or attachment_message else extract_urls(display_text)
        link = urls[0] if self.link_previews and urls else ""
        preview = self.preview_cache.get(link) if link else None
        reactions = message.get("reactions", {})
        reaction_values = tuple(emoji for _owner, emoji in reaction_items(reactions))
        grouped_reactions = reaction_groups(reactions)
        minimum_content_width = 360 if attachment_message else (230 if voice_message else (80 if emoji_reaction else 72))
        natural_content_width = max(
            minimum_content_width,
            natural_text_width,
            author_width,
            metadata_width,
            320 if link else 0,
        )
        text_width = min(max_text_width, natural_content_width)
        bubble_width = min(max_bubble_width, max(108 if emoji_reaction else 100, text_width + 28))
        text_width = bubble_width - 28
        reaction_rows = self._reaction_rows(grouped_reactions, font, max_bubble_width)
        attachment_content_height = 0
        if voice_message:
            body_height = 42
        elif attachment_image:
            image_height = round(attachment_image_data.height() * text_width / max(1, attachment_image_data.width()))
            attachment_content_height = min(270, max(120, image_height)) + 30
            body_height = attachment_content_height
        elif attachment_video:
            attachment_content_height = 210
            body_height = attachment_content_height
        elif attachment_message:
            attachment_content_height = 72
            body_height = attachment_content_height
        elif emoji_reaction:
            body_height = body_metrics.height() + 4
        else:
            text_layout = self._body_layout(display_text, body_font, text_width)
            body_height = int(text_layout.boundingRect().height() + 0.999)
        if attachment_active:
            body_height += 50
        body_height = max(body_height, 20)
        author_height = 18 if identity is not None else 0
        preview_geometry = self._preview_layout(link, preview, text_width, font) if link else None
        link_height = int(preview_geometry["height"]) + 8 if preview_geometry is not None else 0
        reaction_height = len(reaction_rows) * 26
        bubble_height = 18 + author_height + body_height + link_height + 23
        row_height = max(54, bubble_height + reaction_height + 8)
        return {
            "outgoing": outgoing,
            "identity": identity,
            "avatar": self.local_avatar if outgoing else self.remote_avatar,
            "bubble_width": bubble_width,
            "bubble_height": bubble_height,
            "row_height": row_height,
            "body_height": body_height,
            "body_font": body_font,
            "display_text": display_text,
            "urls": urls,
            "author_height": author_height,
            "link": link,
            "link_height": link_height,
            "preview": preview,
            "preview_geometry": preview_geometry,
            "reactions": reaction_values,
            "reaction_groups": grouped_reactions,
            "reaction_rows": reaction_rows,
            "reaction_height": reaction_height,
            "emoji_reaction": emoji_reaction,
            "voice_message": voice_message,
            "voice_duration": duration_text,
            "attachment_message": attachment_message,
            "attachment": attachment,
            "attachment_image": attachment_image,
            "attachment_video": attachment_video,
            "attachment_image_data": attachment_image_data,
            "attachment_state": attachment_state,
            "attachment_active": attachment_active,
            "attachment_content_height": attachment_content_height,
            "metadata": metadata,
        }

    def sizeHint(self, option, index: QModelIndex) -> QSize:
        message = index.data(ChatMessageModel.MessageRole) or {}
        width = max(420, self.view.viewport().width())
        geometry = self._layout(message, width, option.font)
        return QSize(width, int(geometry["row_height"]))

    def paint(self, painter: QPainter, option, index: QModelIndex) -> None:
        message = index.data(ChatMessageModel.MessageRole) or {}
        geometry = self._layout(message, option.rect.width(), option.font)
        outgoing = bool(geometry["outgoing"])
        margin = 20
        if outgoing:
            avatar_x = option.rect.right() - margin - 34
        else:
            avatar_x = option.rect.left() + margin
        bubble_rect = self._bubble_rect(option.rect, geometry)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        emoji_reaction = bool(geometry["emoji_reaction"])
        bubble_border = QColor(COLORS["accent"] if emoji_reaction else ("transparent" if outgoing else COLORS["border"]))
        if emoji_reaction:
            bubble_border.setAlpha(145)
        painter.setPen(QPen(bubble_border, 1))
        painter.setBrush(QColor(COLORS["accent_dark"] if outgoing else COLORS["surface_2"]))
        painter.drawRoundedRect(bubble_rect, 9, 9)

        avatar = geometry["avatar"]
        avatar_rect = QRect(avatar_x, option.rect.top() + 8, 34, 34)
        if isinstance(avatar, QPixmap) and not avatar.isNull():
            painter.drawPixmap(avatar_rect, avatar)
        else:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(COLORS["accent_dark"]))
            painter.drawEllipse(avatar_rect)
            identity = geometry["identity"]
            initial = identity.name[:1].upper() if isinstance(identity, IdentityBundle) else "?"
            painter.setPen(QColor(COLORS["accent"]))
            font = QFont(option.font)
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(avatar_rect, int(Qt.AlignmentFlag.AlignCenter), initial)

        x = bubble_rect.left() + 14
        y = bubble_rect.top() + 10
        content_width = bubble_rect.width() - 28
        identity = geometry["identity"]
        if isinstance(identity, IdentityBundle):
            author_font = QFont(option.font)
            author_font.setPointSizeF(max(8.0, author_font.pointSizeF() - 1))
            author_font.setBold(True)
            painter.setFont(author_font)
            painter.setPen(QColor(COLORS["text"] if outgoing else COLORS["accent"]))
            painter.drawText(QRect(x, y, content_width, 18), int(Qt.AlignmentFlag.AlignVCenter), identity.name)
            y += int(geometry["author_height"])

        painter.setFont(geometry["body_font"])
        painter.setPen(QColor(COLORS["text"]))
        body_height = int(geometry["body_height"])
        if bool(geometry.get("attachment_message")):
            attachment = geometry.get("attachment")
            attachment = attachment if isinstance(attachment, dict) else {}
            name = str(attachment.get("name", tr("Allegato")))
            details = f"{format_file_size(attachment.get('size'))} · {str(attachment.get('mime', 'application/octet-stream'))}"
            attachment_state = str(geometry.get("attachment_state", "complete"))
            attachment_active = bool(geometry.get("attachment_active"))
            attachment_rect = QRect(x, y, content_width, int(geometry.get("attachment_content_height", body_height)))
            painter.setPen(QPen(QColor(COLORS["border"]), 1))
            painter.setBrush(QColor(COLORS["surface"] if outgoing else COLORS["surface_3"]))
            painter.drawRoundedRect(attachment_rect, 9, 9)
            if bool(geometry.get("attachment_image")):
                image_rect = attachment_rect.adjusted(1, 1, -1, -30)
                image = geometry.get("attachment_image_data")
                if isinstance(image, QImage) and not image.isNull():
                    scaled = image.scaled(
                        image_rect.size(), Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                    target = QRect(
                        image_rect.left() + (image_rect.width() - scaled.width()) // 2,
                        image_rect.top() + (image_rect.height() - scaled.height()) // 2,
                        scaled.width(), scaled.height(),
                    )
                    painter.drawImage(target, scaled)
                painter.setPen(QColor(COLORS["muted"]))
                painter.drawText(
                    QRect(attachment_rect.left() + 10, attachment_rect.bottom() - 28, attachment_rect.width() - 20, 24),
                    int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                    QFontMetrics(option.font).elidedText(name, Qt.TextElideMode.ElideMiddle, attachment_rect.width() - 20),
                )
            elif bool(geometry.get("attachment_video")):
                video_rect = attachment_rect.adjusted(1, 1, -1, -30)
                painter.setBrush(QColor("#080a0d"))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawRoundedRect(video_rect, 8, 8)
                circle = QRect(video_rect.center().x() - 27, video_rect.center().y() - 27, 54, 54)
                painter.setBrush(QColor(COLORS["accent_dark"]))
                painter.setPen(QPen(QColor(COLORS["accent"]), 1))
                painter.drawEllipse(circle)
                play = QPainterPath()
                play.moveTo(circle.left() + 22, circle.top() + 15)
                play.lineTo(circle.left() + 22, circle.bottom() - 15)
                play.lineTo(circle.right() - 14, circle.center().y())
                play.closeSubpath()
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(COLORS["accent"]))
                painter.drawPath(play)
                painter.setPen(QColor(COLORS["muted"]))
                painter.drawText(
                    QRect(attachment_rect.left() + 10, attachment_rect.bottom() - 28, attachment_rect.width() - 20, 24),
                    int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                    QFontMetrics(option.font).elidedText(name, Qt.TextElideMode.ElideMiddle, attachment_rect.width() - 20),
                )
            else:
                painter.setPen(QColor(COLORS["text"]))
                name_font = QFont(option.font)
                name_font.setBold(True)
                painter.setFont(name_font)
                text_space = attachment_rect.width() - (128 if attachment_state == "complete" else 24)
                painter.drawText(
                    QRect(attachment_rect.left() + 12, attachment_rect.top() + 10, text_space, 24),
                    int(Qt.AlignmentFlag.AlignVCenter),
                    QFontMetrics(name_font).elidedText(name, Qt.TextElideMode.ElideMiddle, text_space),
                )
                painter.setFont(option.font)
                painter.setPen(QColor(COLORS["muted"]))
                painter.drawText(
                    QRect(attachment_rect.left() + 12, attachment_rect.top() + 35, attachment_rect.width() - 128, 20),
                    int(Qt.AlignmentFlag.AlignVCenter), details,
                )
                if attachment_state == "complete":
                    button = QRect(attachment_rect.right() - 103, attachment_rect.top() + 17, 95, 36)
                    painter.setPen(QPen(QColor(COLORS["accent"]), 1))
                    painter.setBrush(QColor(COLORS["accent_dark"]))
                    painter.drawRoundedRect(button, 8, 8)
                    painter.setPen(QColor(COLORS["accent"]))
                    painter.drawText(button, int(Qt.AlignmentFlag.AlignCenter), tr("Salva file"))
            if attachment_active:
                progress = max(0, min(100, int(attachment.get("progress", 0))))
                progress_y = attachment_rect.bottom() + 7
                progress_rect = QRect(attachment_rect.left(), progress_y, attachment_rect.width(), 6)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(COLORS["surface_3"]))
                painter.drawRoundedRect(progress_rect, 3, 3)
                if progress:
                    painter.setBrush(QColor(COLORS["accent"]))
                    painter.drawRoundedRect(QRect(progress_rect.left(), progress_rect.top(), round(progress_rect.width() * progress / 100), 6), 3, 3)
                controls_y = progress_y + 11
                painter.setPen(QColor(COLORS["muted"]))
                painter.drawText(QRect(attachment_rect.left(), controls_y, 70, 30), int(Qt.AlignmentFlag.AlignVCenter), f"{progress}%")
                pause_button = QRect(attachment_rect.right() - 201, controls_y, 96, 30)
                cancel_button = QRect(attachment_rect.right() - 99, controls_y, 96, 30)
                for button, label, danger in (
                    (pause_button, tr("Riprendi") if attachment_state == "paused" else tr("Metti in pausa"), False),
                    (cancel_button, tr("Annulla"), True),
                ):
                    color = COLORS["danger"] if danger else COLORS["accent"]
                    painter.setPen(QPen(QColor(color), 1))
                    painter.setBrush(QColor(COLORS["surface"]))
                    painter.drawRoundedRect(button, 7, 7)
                    painter.setPen(QColor(color))
                    painter.drawText(button, int(Qt.AlignmentFlag.AlignCenter), label)
        elif bool(geometry.get("voice_message")):
            voice_rect = QRect(x, y, content_width, body_height)
            painter.setPen(QPen(QColor(COLORS["accent"]), 1))
            painter.setBrush(QColor(COLORS["surface_3"]))
            painter.drawEllipse(QRect(voice_rect.left(), voice_rect.top() + 4, 34, 34))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(COLORS["accent"]))
            play = QPainterPath()
            play.moveTo(voice_rect.left() + 13, voice_rect.top() + 13)
            play.lineTo(voice_rect.left() + 13, voice_rect.top() + 29)
            play.lineTo(voice_rect.left() + 25, voice_rect.top() + 21)
            play.closeSubpath()
            painter.drawPath(play)
            waveform_left = voice_rect.left() + 48
            waveform_width = max(30, voice_rect.width() - 98)
            painter.setPen(QPen(QColor(COLORS["accent"] if outgoing else COLORS["cyan"]), 2))
            for bar in range(18):
                bar_x = waveform_left + round(bar * waveform_width / 18)
                height = 7 + ((bar * 11 + 5) % 18)
                painter.drawLine(
                    bar_x, voice_rect.center().y() - height // 2,
                    bar_x, voice_rect.center().y() + height // 2,
                )
            painter.setPen(QColor(COLORS["muted"]))
            painter.drawText(
                QRect(voice_rect.right() - 45, voice_rect.top(), 45, voice_rect.height()),
                int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                str(geometry.get("voice_duration", "0:00")),
            )
        elif emoji_reaction:
            painter.drawText(
                QRect(x, y, content_width, body_height),
                int(Qt.AlignmentFlag.AlignCenter), str(geometry["display_text"]),
            )
        else:
            body_layout = self._body_layout(
                str(geometry["display_text"]), geometry["body_font"], content_width, styled_links=True,
            )
            body_layout.draw(painter, QPointF(x, y))
        y += body_height + 5

        link = geometry["link"]
        if isinstance(link, str) and link:
            preview = geometry["preview"]
            if preview is None and self.preview_requested is not None:
                self.preview_requested(link)
            preview_geometry = geometry["preview_geometry"]
            if isinstance(preview_geometry, dict):
                self._paint_preview_card(
                    painter, QRect(x, y, content_width, int(preview_geometry["height"])),
                    link, preview if isinstance(preview, dict) else None, preview_geometry, option.font,
                )
            y += int(geometry["link_height"])

        reaction_regions = self.reaction_regions(message, option.rect, option.font)
        if reaction_regions:
            reaction_font = QFont(option.font)
            reaction_font.setFamilies(["Segoe UI Emoji", "Noto Color Emoji", "Apple Color Emoji"])
            painter.setFont(reaction_font)
            local_id = self.local_identity.identity_id if self.local_identity is not None else ""
            group_by_emoji = {emoji: owners for emoji, owners in geometry.get("reaction_groups", ())}
            text_by_emoji = {
                emoji: f"{emoji} {len(owners)}"
                for emoji, owners in group_by_emoji.items()
            }
            for emoji, owners, reaction_rect in reaction_regions:
                owned = local_id in owners
                painter.setPen(QPen(QColor(COLORS["accent"] if owned else COLORS["border"]), 1))
                painter.setBrush(QColor(COLORS["accent_dark"] if owned else COLORS["surface_3"]))
                painter.drawRoundedRect(reaction_rect, 11, 11)
                painter.setPen(QColor(COLORS["text"]))
                painter.drawText(
                    reaction_rect,
                    int(Qt.AlignmentFlag.AlignCenter),
                    text_by_emoji.get(emoji, emoji),
                )

        metadata = str(geometry["metadata"])
        if outgoing:
            painter.setPen(QColor(COLORS["cyan"] if message.get("status") == "read" else COLORS["muted"]))
        else:
            painter.setPen(QColor(COLORS["muted"]))
        meta_font = QFont(option.font)
        meta_font.setPointSizeF(max(7.5, meta_font.pointSizeF() - 2))
        painter.setFont(meta_font)
        painter.drawText(
            QRect(x, bubble_rect.bottom() - 22, content_width, 17),
            int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter), metadata,
        )
        painter.restore()

    def _paint_preview_card(
        self,
        painter: QPainter,
        rect: QRect,
        url: str,
        preview: dict | None,
        layout: dict[str, object],
        base_font: QFont,
    ) -> None:
        painter.setPen(QPen(QColor(COLORS["border"]), 1))
        painter.setBrush(QColor(COLORS["surface"]))
        painter.drawRoundedRect(rect, 9, 9)
        accent = QRect(rect.left(), rect.top() + 8, 3, max(12, rect.height() - 16))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(COLORS["danger"] if str((preview or {}).get("site", "")).lower() == "youtube" else COLORS["cyan"]))
        painter.drawRoundedRect(accent, 2, 2)

        state = str(layout.get("state", "loading"))
        if state != "ready":
            label_font = QFont(base_font)
            label_font.setBold(True)
            painter.setFont(label_font)
            painter.setPen(QColor(COLORS["cyan"] if state == "loading" else COLORS["muted"]))
            label = tr("Caricamento anteprima…") if state == "loading" else tr("Anteprima non disponibile")
            painter.drawText(rect.adjusted(13, 8, -12, -30), int(Qt.AlignmentFlag.AlignVCenter), label)
            painter.setFont(base_font)
            painter.setPen(QColor(COLORS["muted"]))
            painter.drawText(
                rect.adjusted(13, 34, -12, -7), int(Qt.AlignmentFlag.AlignVCenter),
                QFontMetrics(base_font).elidedText(url, Qt.TextElideMode.ElideMiddle, rect.width() - 25),
            )
            return

        cursor_y = rect.top()
        image = layout.get("image")
        image_height = int(layout.get("image_height", 0))
        if isinstance(image, QImage) and not image.isNull() and image_height:
            image_rect = QRect(rect.left() + 1, cursor_y + 1, rect.width() - 2, image_height)
            scaled = image.scaled(
                image_rect.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            source_x = max(0, (scaled.width() - image_rect.width()) // 2)
            source_y = max(0, (scaled.height() - image_rect.height()) // 2)
            painter.save()
            clip = QPainterPath()
            clip.addRoundedRect(QRectF(image_rect), 8, 8)
            painter.setClipPath(clip)
            painter.drawImage(image_rect, scaled, QRect(source_x, source_y, image_rect.width(), image_rect.height()))
            painter.restore()
            cursor_y += image_height

        text_rect = QRect(rect.left() + 13, cursor_y + 9, rect.width() - 25, rect.bottom() - cursor_y - 18)
        preview = preview or {}
        site_font = QFont(base_font)
        site_font.setPointSizeF(max(7.5, site_font.pointSizeF() - 2))
        site_font.setBold(True)
        painter.setFont(site_font)
        painter.setPen(QColor(COLORS["danger"] if str(preview.get("site", "")).lower() == "youtube" else COLORS["cyan"]))
        painter.drawText(QRect(text_rect.left(), text_rect.top(), text_rect.width(), 16), int(Qt.AlignmentFlag.AlignVCenter), str(preview.get("site") or "LINK").upper())
        cursor_y = text_rect.top() + 20

        title_font = QFont(base_font)
        title_font.setPointSizeF(max(10.0, title_font.pointSizeF() + 0.5))
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.setPen(QColor(COLORS["text"]))
        title_height = int(layout.get("title_height", 18))
        painter.drawText(
            QRect(text_rect.left(), cursor_y, text_rect.width(), title_height),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap),
            str(preview.get("title") or url),
        )
        cursor_y += title_height

        small_font = QFont(base_font)
        small_font.setPointSizeF(max(8.0, small_font.pointSizeF() - 1.5))
        painter.setFont(small_font)
        author = str(preview.get("author") or "")
        if author:
            cursor_y += 2
            painter.setPen(QColor(COLORS["text"]))
            painter.drawText(QRect(text_rect.left(), cursor_y, text_rect.width(), 16), int(Qt.AlignmentFlag.AlignVCenter), author)
            cursor_y += 16
        description = str(preview.get("description") or "")
        description_height = int(layout.get("description_height", 0))
        if description and description_height:
            cursor_y += 5
            painter.setPen(QColor(COLORS["muted"]))
            painter.drawText(
                QRect(text_rect.left(), cursor_y, text_rect.width(), description_height),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap), description,
            )


class VirtualChatView(QListView):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.chat_model = ChatMessageModel(self)
        self.chat_delegate = ChatMessageDelegate(self)
        self.setModel(self.chat_model)
        self.setItemDelegate(self.chat_delegate)
        self.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # Compute the full scrollbar range once; painting remains virtualized.
        self.setLayoutMode(QListView.LayoutMode.SinglePass)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setWordWrap(True)
        self.setSpacing(2)
        self.setStyleSheet("background: transparent; border: 0; outline: 0;")
        self.setMouseTracking(True)
        self.verticalScrollBar().setSingleStep(36)
        self.on_action: Callable[[str, dict], None] | None = None
        self.on_timing: Callable[[dict], None] | None = None
        self.on_open_link: Callable[[str], None] | None = None
        self._pressed_link = ""
        self._pressed_reaction = ""
        self._pressed_voice = False
        self._pressed_attachment = ""
        self._pressed_position = QPoint()
        self._video_message_id = ""
        # Multimedia objects are relatively expensive and can initialize native
        # backends.  Most chats never play a video, so create them only on demand.
        self._video_widget: QVideoWidget | None = None
        self._video_audio: QAudioOutput | None = None
        self._video_player: QMediaPlayer | None = None

    def configure(
        self,
        local_identity: IdentityBundle | None,
        remote_identity: IdentityBundle | None,
        local_avatar: QPixmap | None,
        remote_avatar: QPixmap | None,
        link_previews: bool,
        preview_cache: dict[str, dict] | None = None,
        preview_requested: Callable[[str], None] | None = None,
    ) -> None:
        self.chat_delegate.configure(
            local_identity, remote_identity, local_avatar, remote_avatar, link_previews,
            preview_cache, preview_requested,
        )
        self.scheduleDelayedItemsLayout()
        self.viewport().update()

    def sync_messages(self, messages: list[dict]) -> str:
        old_ids = [str(message.get("message_id", "")) for message in self.chat_model.messages]
        new_ids = [str(message.get("message_id", "")) for message in messages]
        if new_ids == old_ids:
            self.chat_model.update_messages(messages)
            self.viewport().update()
            self._position_video_widget()
            return "updated"
        if len(new_ids) >= len(old_ids) and new_ids[:len(old_ids)] == old_ids:
            self.chat_model.update_messages(messages[:len(old_ids)])
            self.chat_model.append_messages(messages[len(old_ids):])
            self._position_video_widget()
            return "appended"
        self.chat_model.set_messages(messages)
        self._position_video_widget()
        return "reset"

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        index = self.indexAt(event.pos())
        if not index.isValid():
            return
        message = index.data(ChatMessageModel.MessageRole)
        if not isinstance(message, dict):
            return
        menu = QMenu(self)
        attachment = message.get("attachment") if message.get("kind") == "attachment" else None
        attachment_state = str(attachment.get("state", "complete")) if isinstance(attachment, dict) else ""
        reaction_menu = menu.addMenu(tr("Reagisci"))
        reaction_actions = {
            reaction_menu.addAction(emoji): emoji for emoji in ("👍", "❤️", "😂", "😮", "😢", "🔥")
        }
        all_reactions = reaction_menu.addAction(tr("Tutte le emoji…"))
        copy_action = menu.addAction(tr("Copia")) if message.get("kind") not in {"voice", "attachment"} else None
        save_attachment = menu.addAction(tr("Salva allegato")) if message.get("kind") == "attachment" and attachment_state == "complete" else None
        pause_attachment = menu.addAction(tr("Riprendi") if attachment_state == "paused" else tr("Metti in pausa")) \
            if attachment_state in {"transferring", "paused"} else None
        cancel_attachment = menu.addAction(tr("Annulla trasferimento")) if attachment_state in {"transferring", "paused"} else None
        timing_action = menu.addAction(tr("Dettagli di invio e ritardo"))
        link = extract_url(str(message.get("text", "")))
        open_link = menu.addAction(tr("Apri link")) if link else None
        can_forward = message.get("kind") != "attachment" or attachment_state == "complete" or message.get("direction") == "out"
        forward_action = menu.addAction(tr("Inoltra…")) if can_forward else None
        menu.addSeparator()
        delete_action = menu.addAction(tr("Elimina da questo dispositivo"))
        selected = menu.exec(event.globalPos())
        if selected in reaction_actions and self.on_action is not None:
            self.on_action("react:" + reaction_actions[selected], message)
        elif selected is all_reactions and self.on_action is not None:
            self.on_action("reaction_picker", message)
        elif copy_action is not None and selected is copy_action and self.on_action is not None:
            self.on_action("copy", message)
        elif save_attachment is not None and selected is save_attachment and self.on_action is not None:
            self.on_action("save_attachment", message)
        elif pause_attachment is not None and selected is pause_attachment and self.on_action is not None:
            self.on_action("resume_attachment" if attachment_state == "paused" else "pause_attachment", message)
        elif cancel_attachment is not None and selected is cancel_attachment and self.on_action is not None:
            self.on_action("cancel_attachment", message)
        elif selected is timing_action and self.on_timing is not None:
            self.on_timing(message)
        elif open_link is not None and selected is open_link and link:
            if self.on_open_link is not None:
                self.on_open_link(link)
        elif forward_action is not None and selected is forward_action and self.on_action is not None:
            self.on_action("forward", message)
        elif selected is delete_action and self.on_action is not None:
            self.on_action("delete", message)

    def _link_at_position(self, position: QPoint) -> str:
        index = self.indexAt(position)
        if not index.isValid():
            return ""
        message = index.data(ChatMessageModel.MessageRole)
        if not isinstance(message, dict):
            return ""
        return self.chat_delegate.link_at(message, self.visualRect(index), self.font(), position)

    def _reaction_at_position(self, position: QPoint) -> str:
        index = self.indexAt(position)
        if not index.isValid():
            return ""
        message = index.data(ChatMessageModel.MessageRole)
        if not isinstance(message, dict):
            return ""
        return self.chat_delegate.reaction_at(message, self.visualRect(index), self.font(), position)

    def _voice_at_position(self, position: QPoint) -> bool:
        index = self.indexAt(position)
        if not index.isValid():
            return False
        message = index.data(ChatMessageModel.MessageRole)
        if not isinstance(message, dict):
            return False
        return self.chat_delegate.voice_at(message, self.visualRect(index), self.font(), position)

    def _attachment_at_position(self, position: QPoint) -> str:
        index = self.indexAt(position)
        if not index.isValid():
            return ""
        message = index.data(ChatMessageModel.MessageRole)
        if not isinstance(message, dict):
            return ""
        return self.chat_delegate.attachment_action_at(
            message, self.visualRect(index), self.font(), position,
        )

    def play_inline_video(self, message_id: str, path: Path) -> None:
        self._ensure_video_player()
        assert self._video_player is not None
        assert self._video_widget is not None
        if message_id == self._video_message_id:
            if self._video_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                self._video_player.pause()
            else:
                self._video_player.play()
            return
        self._video_message_id = message_id
        self._video_player.setSource(QUrl.fromLocalFile(str(path)))
        self._position_video_widget()
        self._video_widget.show()
        self._video_widget.raise_()
        self._video_player.play()

    def _ensure_video_player(self) -> None:
        if self._video_player is not None:
            return
        self._video_widget = QVideoWidget(self.viewport())
        self._video_widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._video_widget.hide()
        self._video_audio = QAudioOutput(self)
        self._video_player = QMediaPlayer(self)
        self._video_player.setAudioOutput(self._video_audio)
        self._video_player.setVideoOutput(self._video_widget)

    def stop_inline_video(self) -> None:
        if self._video_player is None or self._video_widget is None:
            self._video_message_id = ""
            return
        self._video_player.stop()
        self._video_player.setSource(QUrl())
        self._video_message_id = ""
        self._video_widget.hide()

    def _position_video_widget(self) -> None:
        if not self._video_message_id or self._video_widget is None:
            return
        row = next((
            index for index, message in enumerate(self.chat_model.messages)
            if str(message.get("message_id", "")) == self._video_message_id
        ), -1)
        if row < 0:
            self.stop_inline_video()
            return
        index = self.chat_model.index(row, 0)
        row_rect = self.visualRect(index)
        if not row_rect.isValid() or not self.viewport().rect().intersects(row_rect):
            self._video_widget.hide()
            return
        message = self.chat_model.messages[row]
        rect = self.chat_delegate.video_rect(message, row_rect, self.font()).adjusted(1, 1, -1, -1)
        if rect.isValid():
            self._video_widget.setGeometry(rect)
            self._video_widget.show()
            self._video_widget.raise_()

    def scrollContentsBy(self, dx: int, dy: int) -> None:
        super().scrollContentsBy(dx, dy)
        self._position_video_widget()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._position_video_widget()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._pressed_position = event.position().toPoint()
            self._pressed_link = self._link_at_position(self._pressed_position)
            self._pressed_reaction = self._reaction_at_position(self._pressed_position)
            self._pressed_voice = self._voice_at_position(self._pressed_position)
            self._pressed_attachment = self._attachment_at_position(self._pressed_position)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        position = event.position().toPoint()
        link = self._link_at_position(position) if event.button() == Qt.MouseButton.LeftButton else ""
        reaction = self._reaction_at_position(position) if event.button() == Qt.MouseButton.LeftButton else ""
        voice = self._voice_at_position(position) if event.button() == Qt.MouseButton.LeftButton else False
        attachment = self._attachment_at_position(position) if event.button() == Qt.MouseButton.LeftButton else ""
        moved = (position - self._pressed_position).manhattanLength()
        if link and link == self._pressed_link and moved <= QApplication.startDragDistance():
            self._pressed_link = ""
            if self.on_open_link is not None:
                self.on_open_link(link)
            event.accept()
            return
        if reaction and reaction == self._pressed_reaction and moved <= QApplication.startDragDistance():
            self._pressed_reaction = ""
            index = self.indexAt(position)
            message = index.data(ChatMessageModel.MessageRole) if index.isValid() else None
            if self.on_action is not None and isinstance(message, dict):
                self.on_action("react:" + reaction, message)
            event.accept()
            return
        if voice and self._pressed_voice and moved <= QApplication.startDragDistance():
            index = self.indexAt(position)
            message = index.data(ChatMessageModel.MessageRole) if index.isValid() else None
            if self.on_action is not None and isinstance(message, dict):
                self.on_action("play_voice", message)
            self._pressed_voice = False
            event.accept()
            return
        if attachment and attachment == self._pressed_attachment and moved <= QApplication.startDragDistance():
            index = self.indexAt(position)
            message = index.data(ChatMessageModel.MessageRole) if index.isValid() else None
            if self.on_action is not None and isinstance(message, dict):
                self.on_action(attachment, message)
            self._pressed_attachment = ""
            event.accept()
            return
        self._pressed_link = ""
        self._pressed_reaction = ""
        self._pressed_voice = False
        self._pressed_attachment = ""
        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        position = event.position().toPoint()
        interactive = (
            self._link_at_position(position)
            or self._reaction_at_position(position)
            or self._voice_at_position(position)
            or self._attachment_at_position(position)
        )
        self.viewport().setCursor(
            Qt.CursorShape.PointingHandCursor if interactive else Qt.CursorShape.ArrowCursor
        )
        super().mouseMoveEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        self.viewport().setCursor(Qt.CursorShape.ArrowCursor)
        super().leaveEvent(event)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self.scheduleDelayedItemsLayout()


class AppSignals(QObject):
    message_received = pyqtSignal(str, str)
    contacts_changed = pyqtSignal(str)
    protocol_event = pyqtSignal(str, str)
    router_changed = pyqtSignal(bool, str)
    task_done = pyqtSignal(object)
    task_error = pyqtSignal(str)
    download_progress = pyqtSignal(int, int)


class DialogTitleBar(QFrame):
    def __init__(self, dialog: QDialog, title: str):
        super().__init__(dialog)
        self.dialog = dialog
        self.setObjectName("titlebar")
        self.setFixedHeight(42)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 0, 0, 0)
        mark = QLabel("K")
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark.setFixedSize(24, 24)
        mark.setStyleSheet(f"background: {COLORS['accent_dark']}; color: {COLORS['accent']}; border-radius: 5px; font-weight: 800;")
        caption = QLabel(title)
        caption.setStyleSheet("font-weight: 650;")
        close = QToolButton()
        close.setObjectName("closeButton")
        close.setIcon(lucide_icon("x"))
        close.setIconSize(QSize(14, 14))
        close.setFixedSize(46, 41)
        close.setToolTip("Chiudi")
        close.clicked.connect(dialog.reject)
        layout.addWidget(mark)
        layout.addSpacing(8)
        layout.addWidget(caption)
        layout.addStretch()
        layout.addWidget(close)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.dialog.windowHandle():
            self.dialog.windowHandle().startSystemMove()
            event.accept()
            return
        super().mousePressEvent(event)


class KerberusDialog(QDialog):
    def __init__(self, title: str, parent: QWidget | None = None, width: int = 520):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedWidth(width)
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        shell = QFrame()
        shell.setObjectName("dialogShell")
        shell_layout = QVBoxLayout(shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)
        shell_layout.addWidget(DialogTitleBar(self, title))
        body = QWidget()
        self.body_layout = QVBoxLayout(body)
        self.body_layout.setContentsMargins(28, 26, 28, 26)
        self.body_layout.setSpacing(12)
        shell_layout.addWidget(body)
        root.addWidget(shell)

    def resizeEvent(self, event: QResizeEvent) -> None:
        path = QPainterPath()
        path.addRoundedRect(8, 8, max(0, self.width() - 16), max(0, self.height() - 16), 12, 12)
        self.setMask(QRegion(path.toFillPolygon().toPolygon()))
        super().resizeEvent(event)

    def showEvent(self, event: QEvent) -> None:
        localize_widget(self)
        super().showEvent(event)
        owner = self.parentWidget()
        while owner is not None and owner.parentWidget() is not None:
            owner = owner.parentWidget()
        if owner is not None and hasattr(owner, "service"):
            try:
                enabled = bool(owner.service.settings().get("stream_proof_enabled", False))
            except Exception:
                enabled = False
            if enabled:
                QTimer.singleShot(0, lambda: set_window_capture_exclusion(self, True))


class KerberusMessageDialog(KerberusDialog):
    def __init__(self, title: str, message: str, parent: QWidget | None = None, confirm: bool = False):
        super().__init__(title, parent, 500)
        row = QHBoxLayout()
        icon = QLabel()
        icon.setPixmap(lucide_icon("info", COLORS["accent"], 28).pixmap(28, 28))
        text = QLabel(message)
        text.setWordWrap(True)
        text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        row.addWidget(icon, alignment=Qt.AlignmentFlag.AlignTop)
        row.addWidget(text, 1)
        self.body_layout.addLayout(row)
        actions = QHBoxLayout()
        actions.addStretch()
        if confirm:
            cancel = QPushButton("Annulla")
            cancel.setObjectName("ghost")
            cancel.clicked.connect(self.reject)
            actions.addWidget(cancel)
        accept = QPushButton("Continua" if confirm else "Chiudi")
        accept.setObjectName("primary")
        accept.clicked.connect(self.accept)
        actions.addWidget(accept)
        self.body_layout.addLayout(actions)

    @classmethod
    def show_message(cls, parent: QWidget | None, title: str, message: str) -> None:
        cls(title, message, parent).exec()

    @classmethod
    def ask(cls, parent: QWidget | None, title: str, message: str) -> bool:
        return cls(title, message, parent, confirm=True).exec() == QDialog.DialogCode.Accepted


class ExternalLinkDialog(KerberusDialog):
    def __init__(self, url: str, parent: QWidget | None = None):
        super().__init__("Aprire link esterno?", parent, 560)
        target = QUrl(url)
        heading_row = QHBoxLayout()
        icon = QLabel()
        icon.setPixmap(lucide_icon("info", COLORS["warning"], 30).pixmap(30, 30))
        heading = QVBoxLayout()
        title = QLabel("Stai per lasciare Kerberus")
        title.setStyleSheet("font-size: 16px; font-weight: 700;")
        explanation = QLabel(
            "Questo collegamento verrà aperto nel browser predefinito. "
            "Controlla attentamente il dominio prima di continuare."
        )
        explanation.setObjectName("muted")
        explanation.setWordWrap(True)
        heading.addWidget(title)
        heading.addWidget(explanation)
        heading_row.addWidget(icon, alignment=Qt.AlignmentFlag.AlignTop)
        heading_row.addLayout(heading, 1)
        self.body_layout.addLayout(heading_row)

        destination = QFrame()
        destination.setObjectName("settingsCard")
        destination_layout = QVBoxLayout(destination)
        destination_layout.setContentsMargins(14, 12, 14, 12)
        destination_layout.setSpacing(5)
        domain = QLabel(target.host().lower())
        domain.setStyleSheet(f"color: {COLORS['accent']}; font-size: 15px; font-weight: 700;")
        self.url_field = QLineEdit(url)
        self.url_field.setReadOnly(True)
        self.url_field.setCursorPosition(0)
        self.url_field.setStyleSheet("font-family: Consolas; font-size: 11px;")
        destination_layout.addWidget(domain)
        destination_layout.addWidget(self.url_field)
        self.body_layout.addWidget(destination)

        warning = QLabel(
            "Un sito esterno potrebbe essere dannoso, tracciare il tuo indirizzo IP "
            "o tentare di rubare informazioni."
        )
        warning.setWordWrap(True)
        warning.setStyleSheet(
            f"background: #2d2519; border: 1px solid #5d4829; border-radius: 7px; "
            f"color: {COLORS['warning']}; padding: 10px 12px;"
        )
        self.body_layout.addWidget(warning)

        actions = QHBoxLayout()
        actions.addStretch()
        cancel = QPushButton("Annulla")
        cancel.setObjectName("ghost")
        cancel.clicked.connect(self.reject)
        open_button = QPushButton("Apri nel browser")
        open_button.setObjectName("primary")
        open_button.setIcon(lucide_icon("external-link", "#07120e", 16))
        open_button.clicked.connect(self.accept)
        actions.addWidget(cancel)
        actions.addWidget(open_button)
        self.body_layout.addLayout(actions)

    @classmethod
    def confirm(cls, parent: QWidget | None, url: str) -> bool:
        return cls(url, parent).exec() == QDialog.DialogCode.Accepted


def open_external_link(parent: QWidget | None, url: str) -> bool:
    target = QUrl(url)
    if target.scheme().lower() not in {"http", "https"} or not target.isValid() or not target.host():
        KerberusMessageDialog.show_message(
            parent, "Collegamento non valido",
            "Kerberus può aprire soltanto collegamenti HTTP o HTTPS validi.",
        )
        return False
    owner = parent.window() if parent is not None else None
    if not ExternalLinkDialog.confirm(owner, url):
        return False
    return QDesktopServices.openUrl(target)


class KerberusProgressDialog(KerberusDialog):
    def __init__(self, title: str, message: str, parent: QWidget | None = None):
        super().__init__(title, parent, 500)
        label = QLabel(message)
        label.setObjectName("muted")
        self.body_layout.addWidget(label)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setTextVisible(False)
        self.body_layout.addWidget(self.progress)

    def setMaximum(self, maximum: int) -> None:
        self.progress.setMaximum(maximum)

    def setValue(self, value: int) -> None:
        self.progress.setValue(value)


class PasswordDialog(KerberusDialog):
    def __init__(self, create: bool, parent: QWidget | None = None):
        super().__init__("Crea vault" if create else "Sblocca Kerberus", parent, 440)
        layout = self.body_layout
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(12)
        title = QLabel("Proteggi il tuo spazio" if create else "Bentornato")
        title.setObjectName("dialogTitle")
        layout.addWidget(title)
        subtitle = QLabel("Crea una password locale" if create else "Inserisci la password del vault")
        subtitle.setObjectName("muted")
        layout.addWidget(subtitle)
        layout.addSpacing(8)
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setPlaceholderText("Password")
        layout.addWidget(self.password)
        self.confirm = None
        if create:
            self.confirm = QLineEdit()
            self.confirm.setEchoMode(QLineEdit.EchoMode.Password)
            self.confirm.setPlaceholderText("Ripeti password")
            layout.addWidget(self.confirm)
        layout.addSpacing(8)
        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = QPushButton("Annulla")
        cancel.setObjectName("ghost")
        cancel.clicked.connect(self.reject)
        submit = QPushButton("Crea vault" if create else "Sblocca")
        submit.setObjectName("primary")
        submit.clicked.connect(self._submit)
        buttons.addWidget(cancel)
        buttons.addWidget(submit)
        layout.addLayout(buttons)
        self.password.returnPressed.connect(self._submit)
        if self.confirm:
            self.confirm.returnPressed.connect(self._submit)

    def _submit(self) -> None:
        if self.confirm is not None and self.password.text() != self.confirm.text():
            KerberusMessageDialog.show_message(self, "Vault", "Le password non coincidono.")
            return
        self.accept()


class ContactDialog(KerberusDialog):
    def __init__(self, parent: QWidget | None = None):
        super().__init__("Nuovo contatto", parent, 600)
        layout = self.body_layout
        layout.setContentsMargins(28, 26, 28, 26)
        layout.setSpacing(12)
        eyebrow = QLabel("CONNESSIONE PRIVATA")
        eyebrow.setObjectName("eyebrow")
        layout.addWidget(eyebrow)
        title = QLabel("Aggiungi un contatto")
        title.setObjectName("dialogTitle")
        layout.addWidget(title)
        layout.addSpacing(8)
        self.code = QLineEdit()
        self.code.setPlaceholderText("XXXX-KERBERUS-...")
        self.code.setClearButtonEnabled(True)
        layout.addWidget(self.code)
        self.first_message = QPlainTextEdit()
        self.first_message.setPlaceholderText("Primo messaggio (opzionale)")
        self.first_message.setFixedHeight(88)
        layout.addWidget(self.first_message)
        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = QPushButton("Annulla")
        cancel.setObjectName("ghost")
        cancel.clicked.connect(self.reject)
        submit = QPushButton("Invia richiesta")
        submit.setObjectName("primary")
        submit.clicked.connect(self.accept)
        buttons.addWidget(cancel)
        buttons.addWidget(submit)
        layout.addLayout(buttons)
        self.code.setFocus()


class ComposerEdit(QPlainTextEdit):
    send_requested = pyqtSignal()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not (event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            self.send_requested.emit()
            return
        super().keyPressEvent(event)


class VoiceRecorder(QObject):
    """Capture microphone PCM; compression and resampling stay in the Go helper."""

    finished = pyqtSignal(bytes, int, int, str, int)
    failed = pyqtSignal(str)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._source: QAudioSource | None = None
        self._device: QIODevice | None = None
        self._format: QAudioFormat | None = None
        self._data = bytearray()
        self._active = False
        self._overflow_pending = False

    @property
    def active(self) -> bool:
        return self._active

    def start(self, device: object | None = None) -> None:
        if self._active:
            return
        if device is None:
            device = QMediaDevices.defaultAudioInput()
        if device.isNull():
            self.failed.emit("Nessun microfono disponibile")
            return
        desired = QAudioFormat()
        desired.setSampleRate(16_000)
        desired.setChannelCount(1)
        desired.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        audio_format = desired if device.isFormatSupported(desired) else device.preferredFormat()
        sample_formats = {
            QAudioFormat.SampleFormat.UInt8: "u8",
            QAudioFormat.SampleFormat.Int16: "s16le",
            QAudioFormat.SampleFormat.Int32: "s32le",
            QAudioFormat.SampleFormat.Float: "f32le",
        }
        if audio_format.sampleFormat() not in sample_formats:
            self.failed.emit("Il formato del microfono non è supportato")
            return
        self._data.clear()
        self._overflow_pending = False
        self._format = audio_format
        self._source = QAudioSource(device, audio_format, self)
        self._device = self._source.start()
        if self._device is None:
            self._source.deleteLater()
            self._source = None
            self.failed.emit("Impossibile avviare il microfono")
            return
        self._device.readyRead.connect(self._read_available)
        self._active = True

    def _read_available(self) -> None:
        if self._device is not None:
            self._data.extend(bytes(self._device.readAll()))
            if len(self._data) > 64 * 1024 * 1024 and not self._overflow_pending:
                self._overflow_pending = True
                QTimer.singleShot(0, self._fail_oversized_capture)

    def _fail_oversized_capture(self) -> None:
        if self._active:
            self.stop(discard=True)
            self.failed.emit("Il formato del microfono produce troppi dati; seleziona un dispositivo standard")

    def stop(self, *, discard: bool = False) -> None:
        if not self._active or self._source is None or self._format is None:
            return
        self._read_available()
        self._source.stop()
        audio_format = self._format
        raw = bytes(self._data)
        duration_ms = max(0, audio_format.durationForBytes(len(raw)) // 1000)
        sample_formats = {
            QAudioFormat.SampleFormat.UInt8: "u8",
            QAudioFormat.SampleFormat.Int16: "s16le",
            QAudioFormat.SampleFormat.Int32: "s32le",
            QAudioFormat.SampleFormat.Float: "f32le",
        }
        sample_format = sample_formats.get(audio_format.sampleFormat(), "")
        self._active = False
        self._device = None
        self._format = None
        self._data.clear()
        self._source.deleteLater()
        self._source = None
        if discard:
            return
        if duration_ms < 300:
            self.failed.emit("Il messaggio vocale è troppo breve")
            return
        self.finished.emit(
            raw,
            audio_format.sampleRate(),
            audio_format.channelCount(),
            sample_format,
            duration_ms,
        )


_EMOJI_CATALOG: list[tuple[str, str, str]] | None = None


def emoji_catalog() -> list[tuple[str, str, str]]:
    global _EMOJI_CATALOG
    if _EMOJI_CATALOG is None:
        rows = []
        for value in emoji_data.EMOJI_DATA:
            english = emoji_data.demojize(value, language="en").strip(":").replace("_", " ")
            italian = emoji_data.demojize(value, language="it").strip(":").replace("_", " ")
            rows.append((value, italian, english))
        _EMOJI_CATALOG = rows
    return _EMOJI_CATALOG


def _search_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    return "".join(char for char in normalized if not unicodedata.combining(char))


class EmojiPicker(KerberusDialog):
    PAGE_SIZE = 180

    def __init__(self, on_selected: Callable[[str], None], parent: QWidget | None = None, reaction: bool = False):
        super().__init__("Reazione" if reaction else "Emoji", parent, 680)
        self.resize(680, 590)
        self._on_selected = on_selected
        self._page = 0
        self._filtered = emoji_catalog()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Cerca emoji…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        self.body_layout.addWidget(self.search)
        if reaction:
            hint = QLabel(
                "Puoi aggiungere più reazioni. Clicca con il tasto sinistro su una tua reazione per rimuoverla"
            )
            hint.setObjectName("muted")
            self.body_layout.addWidget(hint)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumHeight(410)
        self.grid_host = QWidget()
        self.grid = QGridLayout(self.grid_host)
        self.grid.setContentsMargins(4, 4, 4, 4)
        self.grid.setSpacing(4)
        scroll.setWidget(self.grid_host)
        self.body_layout.addWidget(scroll, 1)
        navigation = QHBoxLayout()
        self.previous = QPushButton("Precedente")
        self.previous.setObjectName("ghost")
        self.previous.clicked.connect(lambda: self._change_page(-1))
        self.page_label = QLabel()
        self.page_label.setObjectName("muted")
        self.next = QPushButton("Successiva")
        self.next.setObjectName("ghost")
        self.next.clicked.connect(lambda: self._change_page(1))
        navigation.addWidget(self.previous)
        navigation.addStretch()
        navigation.addWidget(self.page_label)
        navigation.addStretch()
        navigation.addWidget(self.next)
        self.body_layout.addLayout(navigation)
        self._render()
        self.search.setFocus()

    def _filter(self, query: str) -> None:
        needle = _search_key(query.strip())
        self._filtered = [
            row for row in emoji_catalog()
            if not needle or needle in _search_key(f"{row[1]} {row[2]}")
        ]
        self._page = 0
        self._render()

    def _change_page(self, offset: int) -> None:
        pages = max(1, (len(self._filtered) + self.PAGE_SIZE - 1) // self.PAGE_SIZE)
        self._page = min(max(0, self._page + offset), pages - 1)
        self._render()

    def _render(self) -> None:
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        start = self._page * self.PAGE_SIZE
        page = self._filtered[start:start + self.PAGE_SIZE]
        if not page:
            empty = QLabel(tr("Nessuna emoji trovata"))
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.grid.addWidget(empty, 0, 0, 1, 12)
        for index, (value, italian, english) in enumerate(page):
            button = QToolButton()
            button.setText(value)
            button.setFont(QFont("Segoe UI Emoji", 18))
            button.setFixedSize(48, 42)
            button.setToolTip(english if _LANGUAGE == "en" else italian)
            button.clicked.connect(lambda _checked=False, selected=value: self._select(selected))
            self.grid.addWidget(button, index // 12, index % 12)
        pages = max(1, (len(self._filtered) + self.PAGE_SIZE - 1) // self.PAGE_SIZE)
        self.page_label.setText(f"{self._page + 1}/{pages} · {len(self._filtered)} emoji")
        self.previous.setEnabled(self._page > 0)
        self.next.setEnabled(self._page + 1 < pages)

    def _select(self, value: str) -> None:
        self._on_selected(value)
        self.accept()


_EMOJI_CATEGORIES = (
    ("recent", "◷", "Recenti"),
    ("people", "😀", "Persone"),
    ("nature", "🐻", "Animali e natura"),
    ("food", "🍕", "Cibo e bevande"),
    ("activity", "⚽", "Attività"),
    ("travel", "🚗", "Viaggi"),
    ("objects", "💡", "Oggetti"),
    ("symbols", "♥", "Simboli"),
    ("flags", "⚑", "Bandiere"),
)

_DEFAULT_RECENT_EMOJI = (
    "😂", "❤️", "👍", "😊", "🔥", "🥰", "🙏", "😭", "😘", "🎉", "😍", "🤣",
    "😁", "👌", "💪", "✨", "😅", "😉", "🤔", "😎", "👏", "💚", "😮", "😢",
)


def _emoji_category(value: str, english: str) -> str:
    """Return a practical picker category without expanding the public catalog tuple."""
    codepoints = [ord(char) for char in value if char not in {"\ufe0f", "\u200d"}]
    first = codepoints[0] if codepoints else 0
    name = f" {english.casefold()} "
    if 0x1F1E6 <= first <= 0x1F1FF or " flag " in name:
        return "flags"
    if any(token in name for token in (
        " food ", " fruit ", " vegetable ", " drink ", " beverage ", " cake ", " cookie ",
        " bread ", " rice ", " meat ", " pizza ", " sandwich ", " bottle ", " cup ", " glass ",
    )) or 0x1F345 <= first <= 0x1F37F or 0x1F950 <= first <= 0x1F96F:
        return "food"
    if any(token in name for token in (
        " animal ", " bird ", " cat ", " dog ", " flower ", " tree ", " plant ", " leaf ",
        " moon ", " sun ", " cloud ", " weather ", " insect ", " fish ", " monkey ",
    )) or 0x1F400 <= first <= 0x1F43E:
        return "nature"
    if any(token in name for token in (
        " vehicle ", " car ", " bus ", " train ", " airplane ", " boat ", " ship ", " map ",
        " building ", " house ", " hotel ", " mountain ", " beach ", " camping ", " cityscape ",
    )) or 0x1F680 <= first <= 0x1F6FF:
        return "travel"
    if any(token in name for token in (
        " ball ", " sport ", " game ", " medal ", " trophy ", " musical ", " performing arts ",
        " skiing ", " snowboard ", " swimming ", " chess ", " target ",
    )) or 0x1F3A0 <= first <= 0x1F3FA:
        return "activity"
    if first < 0x1F000 or any(token in name for token in (
        " heart ", " arrow ", " button ", " sign ", " symbol ", " mark ", " zodiac ",
        " circle ", " square ", " warning ", " number ", " prohibited ",
    )):
        return "symbols"
    if any(token in name for token in (
        " face ", " person ", " people ", " hand ", " family ", " woman ", " man ", " child ",
        " baby ", " boy ", " girl ", " body ", " gesture ", " hair ",
    )) or 0x1F600 <= first <= 0x1F64F:
        return "people"
    return "objects"


class EmojiPanel(QFrame):
    """Embedded, reusable emoji browser inspired by modern chat composers."""

    PAGE_SIZE = 96
    selected = pyqtSignal(str)
    close_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("emojiPanel")
        self.setMinimumHeight(430)
        self.setMaximumHeight(460)
        self._category = "recent"
        self._page = 0
        self._reaction_mode = False
        available = {value for value, _italian, _english in emoji_catalog()}
        self._recent = [value for value in _DEFAULT_RECENT_EMOJI if value in available]
        self._filtered: list[tuple[str, str, str]] = []
        self._category_buttons: dict[str, QToolButton] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 14, 20, 14)
        layout.setSpacing(10)

        header = QFrame()
        header.setObjectName("emojiHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(10)
        heading = QVBoxLayout()
        heading.setSpacing(2)
        self.panel_title = QLabel("Emoji e simboli")
        self.panel_title.setObjectName("emojiPanelTitle")
        self.reaction_hint = QLabel("Scegli un’emoji o cercala per nome.")
        self.reaction_hint.setObjectName("muted")
        self.reaction_hint.setWordWrap(True)
        heading.addWidget(self.panel_title)
        heading.addWidget(self.reaction_hint)
        close = QToolButton()
        close.setObjectName("emojiClose")
        close.setIcon(lucide_icon("x"))
        close.setIconSize(QSize(17, 17))
        close.setFixedSize(34, 34)
        close.setToolTip("Chiudi pannello emoji")
        close.clicked.connect(self.close_requested.emit)
        header_layout.addLayout(heading, 1)
        header_layout.addWidget(close, alignment=Qt.AlignmentFlag.AlignTop)
        layout.addWidget(header)

        self.search = QLineEdit()
        self.search.setObjectName("emojiSearch")
        self.search.setPlaceholderText("Cerca emoji…")
        self.search.setClearButtonEnabled(True)
        self.search.addAction(lucide_icon("search"), QLineEdit.ActionPosition.LeadingPosition)
        self.search.textChanged.connect(self._filter)
        layout.addWidget(self.search)

        category_bar = QFrame()
        category_bar.setObjectName("emojiCategories")
        categories = QHBoxLayout(category_bar)
        categories.setContentsMargins(6, 4, 6, 4)
        categories.setSpacing(4)
        for key, glyph, label in _EMOJI_CATEGORIES:
            button = QToolButton()
            button.setObjectName("emojiCategory")
            button.setText(glyph)
            button.setFont(QFont("Segoe UI Emoji", 16))
            button.setFixedSize(38, 34)
            button.setToolTip(label)
            button.clicked.connect(lambda _checked=False, selected=key: self.set_category(selected))
            categories.addWidget(button)
            self._category_buttons[key] = button
        categories.addStretch()
        layout.addWidget(category_bar)

        scroll = QScrollArea()
        scroll.setObjectName("emojiScroll")
        scroll.setWidgetResizable(True)
        scroll.setMinimumHeight(190)
        scroll.viewport().setStyleSheet("background: transparent;")
        self.grid_host = QWidget()
        self.grid_host.setStyleSheet("background: transparent;")
        self.grid = QGridLayout(self.grid_host)
        self.grid.setContentsMargins(2, 2, 2, 2)
        self.grid.setSpacing(2)
        scroll.setWidget(self.grid_host)
        layout.addWidget(scroll, 1)

        footer_frame = QFrame()
        footer_frame.setObjectName("emojiFooter")
        footer_frame.setFixedHeight(40)
        footer = QHBoxLayout(footer_frame)
        footer.setContentsMargins(2, 6, 0, 0)
        footer.setSpacing(6)
        self.section_label = QLabel()
        self.section_label.setObjectName("muted")
        self.previous = QToolButton()
        self.previous.setObjectName("emojiPager")
        self.previous.setIcon(lucide_icon("chevron-left"))
        self.previous.setToolTip("Precedente")
        self.previous.clicked.connect(lambda: self._change_page(-1))
        self.next = QToolButton()
        self.next.setObjectName("emojiPager")
        self.next.setIcon(lucide_icon("chevron-right"))
        self.next.setToolTip("Successiva")
        self.next.clicked.connect(lambda: self._change_page(1))
        footer.addWidget(self.section_label)
        footer.addStretch()
        footer.addWidget(self.previous)
        footer.addWidget(self.next)
        layout.addWidget(footer_frame)
        self.set_category("recent")

    def set_category(self, category: str) -> None:
        if category not in self._category_buttons:
            category = "recent"
        self._category = category
        self._page = 0
        if self.search.text():
            self.search.blockSignals(True)
            self.search.clear()
            self.search.blockSignals(False)
        self._update_category_buttons()
        self._filter("")

    def set_reaction_mode(self, enabled: bool) -> None:
        self._reaction_mode = enabled
        self.panel_title.setText(tr("Reazioni al messaggio" if enabled else "Emoji e simboli"))
        self.reaction_hint.setText(tr(
            "Puoi aggiungere più reazioni. Clicca con il tasto sinistro su una tua reazione per rimuoverla"
            if enabled else "Scegli un’emoji o cercala per nome."
        ))
        self._render()

    def _update_category_buttons(self) -> None:
        for key, button in self._category_buttons.items():
            button.setProperty("active", key == self._category)
            button.style().unpolish(button)
            button.style().polish(button)

    def _filter(self, query: str) -> None:
        needle = _search_key(query.strip())
        if needle:
            self._filtered = [
                row for row in emoji_catalog()
                if needle in _search_key(f"{row[1]} {row[2]}")
            ]
        elif self._category == "recent":
            by_value = {row[0]: row for row in emoji_catalog()}
            self._filtered = [by_value[value] for value in self._recent if value in by_value]
        else:
            self._filtered = [
                row for row in emoji_catalog() if _emoji_category(row[0], row[2]) == self._category
            ]
        self._page = 0
        self._render()

    def _change_page(self, offset: int) -> None:
        pages = max(1, (len(self._filtered) + self.PAGE_SIZE - 1) // self.PAGE_SIZE)
        self._page = min(max(0, self._page + offset), pages - 1)
        self._render()

    def _render(self) -> None:
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        start = self._page * self.PAGE_SIZE
        page = self._filtered[start:start + self.PAGE_SIZE]
        if not page:
            empty = QLabel(tr("Nessuna emoji trovata"))
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.grid.addWidget(empty, 0, 0, 1, 12)
        for index, (value, italian, english) in enumerate(page):
            button = QToolButton()
            button.setObjectName("emojiItem")
            button.setText(value)
            button.setFont(QFont("Segoe UI Emoji", 19))
            button.setFixedSize(42, 38)
            button.setToolTip(english if _LANGUAGE == "en" else italian)
            button.clicked.connect(lambda _checked=False, selected=value: self._select(selected))
            self.grid.addWidget(button, index // 12, index % 12)
        pages = max(1, (len(self._filtered) + self.PAGE_SIZE - 1) // self.PAGE_SIZE)
        label = next((label for key, _glyph, label in _EMOJI_CATEGORIES if key == self._category), "Emoji")
        if self.search.text().strip():
            label = "Emoji"
        prefix = f"{tr('Reazione')} · " if self._reaction_mode else ""
        self.section_label.setText(f"{prefix}{tr(label)} · {len(self._filtered)}")
        self.previous.setEnabled(self._page > 0)
        self.next.setEnabled(self._page + 1 < pages)

    def _select(self, value: str) -> None:
        if value in self._recent:
            self._recent.remove(value)
        self._recent.insert(0, value)
        del self._recent[36:]
        self.selected.emit(value)


class ContactRow(QWidget):
    def __init__(self, contact: IdentityBundle, last_message: str = ""):
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(11)
        avatar = QLabel()
        set_avatar(avatar, contact, 40)
        layout.addWidget(avatar)
        text = QVBoxLayout()
        text.setSpacing(2)
        name = QLabel(contact.name)
        name.setStyleSheet("font-weight: 650;")
        preview = QLabel(last_message or contact.identity_id[:18])
        preview.setObjectName("contactMeta")
        preview.setMaximumWidth(185)
        text.addWidget(name)
        text.addWidget(preview)
        layout.addLayout(text, 1)


class PendingContactRow(QWidget):
    def __init__(self, pending: dict, on_cancel: Callable[[str], None]):
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(11)
        mark = QLabel("…")
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark.setFixedSize(40, 40)
        mark.setStyleSheet(
            f"background: {COLORS['surface_2']}; color: {COLORS['warning']}; "
            "border-radius: 20px; font-size: 18px; font-weight: 700;"
        )
        layout.addWidget(mark)
        text = QVBoxLayout()
        text.setSpacing(2)
        title = QLabel("Richiesta in attesa")
        title.setStyleSheet("font-weight: 650;")
        attempts = int(pending.get("attempts", 0))
        meta = QLabel(tr_format("Conferma non ancora ricevuta · tentativi {count}", count=attempts))
        meta.setObjectName("contactMeta")
        text.addWidget(title)
        text.addWidget(meta)
        layout.addLayout(text, 1)
        cancel = QToolButton()
        cancel.setIcon(lucide_icon("x", COLORS["danger"], 16))
        cancel.setToolTip("Annulla richiesta")
        destination = str(pending.get("destination", ""))
        cancel.clicked.connect(lambda: on_cancel(destination))
        layout.addWidget(cancel)
        self.setToolTip("La chat sarà disponibile dopo la conferma firmata dell’altro dispositivo")


class LinkPreviewCard(QFrame):
    def __init__(self, url: str):
        super().__init__()
        self.setObjectName("linkPreviewCard")
        self.url = url
        self.setStyleSheet(
            f"QFrame#linkPreviewCard {{ background: {COLORS['surface']}; border: 1px solid {COLORS['border']}; border-radius: 7px; }}"
        )
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.accent = QFrame()
        self.accent.setFixedWidth(4)
        self.accent.setStyleSheet(f"background: {COLORS['cyan']}; border: 0; border-radius: 2px;")
        outer.addWidget(self.accent)
        content = QVBoxLayout()
        content.setContentsMargins(12, 9, 12, 11)
        content.setSpacing(6)
        self.site = QLabel("Caricamento anteprima…")
        self.site.setStyleSheet(f"border: 0; color: {COLORS['muted']}; font-size: 11px;")
        self.author = QLabel()
        self.author.setStyleSheet("border: 0; font-weight: 650;")
        self.author.hide()
        self.title = QLabel(url)
        self.title.setWordWrap(True)
        self.title.setStyleSheet(f"border: 0; color: {COLORS['cyan']}; font-size: 14px; font-weight: 650;")
        self.description = QLabel()
        self.description.setWordWrap(True)
        self.description.setStyleSheet(f"border: 0; color: {COLORS['muted']};")
        self.description.hide()
        self.image = QLabel()
        self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image.setMinimumHeight(0)
        self.image.setStyleSheet("border: 0; background: #080a0d; border-radius: 5px;")
        self.image.hide()
        open_button = QPushButton("Apri link")
        open_button.setObjectName("ghost")
        open_button.clicked.connect(lambda: open_external_link(self, self.url))
        content.addWidget(self.site)
        content.addWidget(self.author)
        content.addWidget(self.title)
        content.addWidget(self.description)
        content.addWidget(self.image)
        content.addWidget(open_button, alignment=Qt.AlignmentFlag.AlignRight)
        outer.addLayout(content, 1)

    def set_preview(self, preview: dict) -> None:
        self.url = str(preview.get("url") or self.url)
        site = str(preview.get("site") or "Link")
        self.site.setText(site)
        self.title.setText(str(preview.get("title") or self.url))
        author = str(preview.get("author") or "")
        self.author.setText(author)
        self.author.setVisible(bool(author))
        description = str(preview.get("description") or "")
        self.description.setText(description)
        self.description.setVisible(bool(description))
        if site.lower() == "youtube":
            self.accent.setStyleSheet(f"background: {COLORS['danger']}; border: 0; border-radius: 2px;")
        raw_image = preview.get("image", b"")
        if isinstance(raw_image, bytes) and raw_image:
            image = QImage()
            if image.loadFromData(raw_image):
                pixmap = QPixmap.fromImage(image).scaled(
                    430, 250, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
                )
                self.image.setPixmap(pixmap)
                self.image.setFixedHeight(pixmap.height())
                self.image.show()

    def set_error(self) -> None:
        self.site.setText("Anteprima non disponibile")


class MessageBubble(QWidget):
    def __init__(
        self,
        text: str,
        timestamp: int,
        outgoing: bool,
        status: str = "",
        timing: dict | None = None,
        on_timing: Callable[[dict], None] | None = None,
        on_action: Callable[[str, dict], None] | None = None,
        link_preview: bool = False,
        on_link_preview: Callable[[str, LinkPreviewCard], None] | None = None,
        author: IdentityBundle | None = None,
        author_avatar: QPixmap | None = None,
    ):
        super().__init__()
        self.message = timing or {"text": text, "status": status}
        self.outgoing = outgoing
        self.on_action = on_action
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)
        outer = QHBoxLayout(self)
        outer.setContentsMargins(20, 4, 20, 4)
        outer.setSpacing(9)
        avatar = QLabel()
        if author_avatar is not None:
            avatar.setFixedSize(34, 34)
            avatar.setPixmap(author_avatar)
        elif author is not None:
            set_avatar(avatar, author, 34)
        else:
            avatar.setFixedSize(34, 34)
            avatar.hide()
        if outgoing:
            outer.addStretch(1)
        else:
            outer.addWidget(avatar, alignment=Qt.AlignmentFlag.AlignTop)
        bubble = QFrame()
        bubble.setMaximumWidth(560)
        color = COLORS["accent_dark"] if outgoing else COLORS["surface_2"]
        border = "transparent" if outgoing else COLORS["border"]
        bubble.setStyleSheet(f"QFrame {{ background: {color}; border: 1px solid {border}; border-radius: 8px; }}")
        content = QVBoxLayout(bubble)
        content.setContentsMargins(13, 10, 13, 8)
        content.setSpacing(5)
        username = QLabel(author.name if author is not None else "")
        username.setStyleSheet(
            f"border: 0; background: transparent; color: {COLORS['accent'] if not outgoing else COLORS['text']}; "
            "font-size: 12px; font-weight: 700;"
        )
        content.addWidget(username)
        if author is None:
            username.hide()
        body = QLabel(text)
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        body.setStyleSheet("border: 0; background: transparent;")
        content.addWidget(body)
        if link_preview and on_link_preview is not None:
            url = extract_url(text)
            if url:
                preview = LinkPreviewCard(url)
                content.addWidget(preview)
                on_link_preview(url, preview)
        self._timestamp = timestamp
        self.time_label = QLabel()
        self.time_label.setObjectName("timestamp")
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.time_label.setStyleSheet("border: 0; background: transparent; font-size: 11px;")
        metadata = QHBoxLayout()
        metadata.setContentsMargins(0, 0, 0, 0)
        metadata.setSpacing(4)
        metadata.addStretch()
        metadata.addWidget(self.time_label)
        timing_button = QToolButton()
        timing_button.setObjectName("timingButton")
        timing_button.setIcon(lucide_icon("clock", COLORS["muted"], 13))
        timing_button.setIconSize(QSize(13, 13))
        timing_button.setFixedSize(20, 20)
        timing_button.setToolTip("Dettagli di invio e ritardo")
        if timing is not None and on_timing is not None:
            timing_button.clicked.connect(lambda: on_timing(timing))
        else:
            timing_button.setEnabled(False)
        metadata.addWidget(timing_button)
        content.addLayout(metadata)
        self.reactions_label = QLabel()
        self.reactions_label.setStyleSheet("border: 0; background: transparent; font-size: 14px;")
        content.addWidget(self.reactions_label, alignment=Qt.AlignmentFlag.AlignRight)
        self._rendered_status: str | None = None
        self._rendered_reactions: tuple[str, ...] | None = None
        self.update_message(self.message)
        outer.addWidget(bubble)
        if outgoing:
            outer.addWidget(avatar, alignment=Qt.AlignmentFlag.AlignTop)
        else:
            outer.addStretch(1)

    def _show_context_menu(self, position: QPoint) -> None:
        if self.on_action is None:
            return
        menu = QMenu(self)
        reaction_menu = menu.addMenu(tr("Reagisci"))
        reaction_actions = {reaction_menu.addAction(emoji): emoji for emoji in ("👍", "❤️", "😂", "😮", "😢", "🔥")}
        all_reactions = reaction_menu.addAction(tr("Tutte le emoji…"))
        copy_action = menu.addAction(tr("Copia"))
        forward_action = menu.addAction(tr("Inoltra…"))
        menu.addSeparator()
        delete_action = menu.addAction(tr("Elimina da questo dispositivo"))
        selected = menu.exec(self.mapToGlobal(position))
        if selected in reaction_actions:
            self.on_action("react:" + reaction_actions[selected], self.message)
        elif selected is all_reactions:
            self.on_action("reaction_picker", self.message)
        elif selected is copy_action:
            self.on_action("copy", self.message)
        elif selected is forward_action:
            self.on_action("forward", self.message)
        elif selected is delete_action:
            self.on_action("delete", self.message)

    def update_message(self, message: dict) -> None:
        self.message = message
        status = str(message.get("status", ""))
        if status != self._rendered_status:
            time_text = datetime.fromtimestamp(self._timestamp).strftime("%H:%M")
            if self.outgoing:
                marks = {
                    "pending": (f"◷ {tr('In attesa')}", COLORS["muted"]),
                    "sent": (f"✓ {tr('Inviato')}", COLORS["muted"]),
                    "delivered": (f"✓✓ {tr('Consegnato')}", COLORS["muted"]),
                    "read": (f"✓✓ {tr('Letto')}", COLORS["cyan"]),
                }
                mark, color = marks.get(status, ("✓", COLORS["muted"]))
                time_text += f"  {mark}"
                self.time_label.setStyleSheet(
                    f"border: 0; background: transparent; font-size: 11px; color: {color};"
                )
            self.time_label.setText(time_text)
            self._rendered_status = status
        reactions = message.get("reactions", {})
        values = tuple(emoji for _owner, emoji in reaction_items(reactions))
        if values != self._rendered_reactions:
            self.reactions_label.setText(" ".join(values))
            self.reactions_label.setVisible(bool(values))
            self._rendered_reactions = values


class ClickableFrame(QFrame):
    clicked = pyqtSignal()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)


class ToggleSwitch(QAbstractButton):
    def __init__(self, checked: bool = False, parent: QWidget | None = None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(46, 26)
        self.toggled.connect(lambda _checked: self.update())

    def paintEvent(self, _event: QEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        if not self.isEnabled():
            track = QColor(COLORS["surface_3"])
            knob = QColor(COLORS["faint"])
        elif self.isChecked():
            track = QColor(COLORS["accent"])
            knob = QColor("#07120e")
        else:
            track = QColor(COLORS["surface_3"])
            knob = QColor(COLORS["muted"])
        painter.setBrush(track)
        painter.drawRoundedRect(0, 2, 46, 22, 11, 11)
        painter.setBrush(knob)
        painter.drawEllipse(25 if self.isChecked() else 3, 5, 16, 16)
        painter.end()


class SettingsToggleRow(QFrame):
    def __init__(self, title: str, detail: str, checked: bool = False):
        super().__init__()
        self.setObjectName("settingsRow")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 13, 16, 13)
        layout.setSpacing(14)
        text = QVBoxLayout()
        text.setSpacing(3)
        heading = QLabel(title)
        heading.setStyleSheet("font-weight: 650;")
        heading.setWordWrap(True)
        heading.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        description = QLabel(detail)
        description.setObjectName("muted")
        description.setWordWrap(True)
        description.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        text.addWidget(heading)
        text.addWidget(description)
        self.switch = ToggleSwitch(checked)
        layout.addLayout(text, 1)
        layout.addWidget(self.switch, alignment=Qt.AlignmentFlag.AlignVCenter)

    def isChecked(self) -> bool:
        return self.switch.isChecked()

    def setEnabled(self, enabled: bool) -> None:
        super().setEnabled(enabled)
        self.switch.setEnabled(enabled)


class InlineConfirmationPanel(QFrame):
    confirmed = pyqtSignal()
    cancelled = pyqtSignal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("inlineConfirmation")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 15, 16, 15)
        layout.setSpacing(10)
        heading_row = QHBoxLayout()
        icon = QLabel()
        icon.setPixmap(lucide_icon("info", COLORS["warning"], 24).pixmap(24, 24))
        heading = QLabel("Conferma modalità bassa latenza")
        heading.setStyleSheet(f"color: {COLORS['warning']}; font-size: 15px; font-weight: 750;")
        heading.setWordWrap(True)
        heading_row.addWidget(icon, alignment=Qt.AlignmentFlag.AlignTop)
        heading_row.addWidget(heading, 1)
        layout.addLayout(heading_row)
        warning = QLabel(
            "Kerberus ridurrà i tunnel I2P da 3 a 2 hop. Il percorso più corto può diminuire la latenza, "
            "ma rende più economici gli attacchi di correlazione e analisi statistica del traffico."
        )
        warning.setWordWrap(True)
        layout.addWidget(warning)
        unchanged = QLabel(
            "La cifratura end-to-end X25519 + ML-KEM-768 non cambia e non viene usato zero-hop. "
            "Per la protezione I2P più alta mantieni 3 hop."
        )
        unchanged.setObjectName("muted")
        unchanged.setWordWrap(True)
        layout.addWidget(unchanged)
        actions = QHBoxLayout()
        actions.addStretch()
        cancel = QPushButton("Mantieni massima privacy")
        cancel.setObjectName("cancelLowLatency")
        cancel.clicked.connect(self.cancelled.emit)
        confirm = QPushButton("Capisco, usa 2 hop")
        confirm.setObjectName("confirmLowLatency")
        confirm.clicked.connect(self.confirmed.emit)
        actions.addWidget(cancel)
        actions.addWidget(confirm)
        layout.addLayout(actions)
        self.hide()


class SettingsCard(QFrame):
    def __init__(self, icon_name: str, title: str, detail: str = ""):
        super().__init__()
        self.setObjectName("settingsCard")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(16, 15, 16, 14)
        header_layout.setSpacing(12)
        icon = QLabel()
        icon.setFixedSize(34, 34)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setPixmap(lucide_icon(icon_name, COLORS["accent"], 19).pixmap(19, 19))
        icon.setStyleSheet(f"background: {COLORS['accent_dark']}; border-radius: 8px;")
        labels = QVBoxLayout()
        labels.setSpacing(2)
        heading = QLabel(title)
        heading.setStyleSheet("font-size: 16px; font-weight: 700;")
        heading.setWordWrap(True)
        heading.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        labels.addWidget(heading)
        if detail:
            description = QLabel(detail)
            description.setObjectName("muted")
            description.setWordWrap(True)
            description.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            labels.addWidget(description)
        header_layout.addWidget(icon, alignment=Qt.AlignmentFlag.AlignTop)
        header_layout.addLayout(labels, 1)
        outer.addWidget(header)
        self.content_layout = QVBoxLayout()
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(0)
        outer.addLayout(self.content_layout)

    def add_row(self, row: QWidget) -> QWidget:
        self.content_layout.addWidget(row)
        return row


class ChatSettingsPanel(QFrame):
    close_requested = pyqtSignal()
    save_requested = pyqtSignal(dict)
    export_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("chatSettingsPanel")
        self.setFixedWidth(360)
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        header = QHBoxLayout()
        header_icon = QLabel()
        header_icon.setFixedSize(34, 34)
        header_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header_icon.setPixmap(lucide_icon("settings-2", COLORS["accent"], 19).pixmap(19, 19))
        header_icon.setStyleSheet(f"background: {COLORS['accent_dark']}; border-radius: 8px;")
        header_text = QVBoxLayout()
        header_text.setSpacing(1)
        title = QLabel("Impostazioni chat")
        title.setStyleSheet("font-size: 17px; font-weight: 700;")
        subtitle = QLabel("Preferenze della conversazione")
        subtitle.setObjectName("muted")
        header_text.addWidget(title)
        header_text.addWidget(subtitle)
        close = QToolButton()
        close.setIcon(lucide_icon("x"))
        close.setToolTip("Chiudi")
        close.clicked.connect(self.close_requested.emit)
        header.addWidget(header_icon)
        header.addLayout(header_text, 1)
        header.addWidget(close, alignment=Qt.AlignmentFlag.AlignTop)
        root.addLayout(header)

        contact_row = QFrame()
        contact_row.setObjectName("settingsCard")
        contact_layout = QHBoxLayout(contact_row)
        contact_layout.setContentsMargins(12, 10, 12, 10)
        self.contact_avatar = QLabel()
        self.contact_name = QLabel()
        self.contact_name.setStyleSheet("font-weight: 700;")
        contact_layout.addWidget(self.contact_avatar)
        contact_layout.addWidget(self.contact_name, 1)
        root.addWidget(contact_row)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.viewport().setStyleSheet("background: transparent;")
        host = QWidget()
        host.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 4, 0)
        layout.setSpacing(10)

        privacy = SettingsCard(
            "shield-check", "Privacy e ricevute", "Personalizza il comportamento solo per questa chat."
        )
        delivery_row, self.delivery = self._select_row(
            "Conferme di consegna", "Usa la preferenza generale dell’app oppure definisci un’eccezione."
        )
        read_row, self.reads = self._select_row(
            "Conferme di lettura", "Usa la preferenza generale dell’app oppure definisci un’eccezione."
        )
        previews_row, self.previews = self._select_row(
            "Anteprime link", "Controlla il recupero di titoli e immagini esterne."
        )
        privacy.add_row(delivery_row)
        privacy.add_row(read_row)
        privacy.add_row(previews_row)
        layout.addWidget(privacy)

        notifications_card = SettingsCard("message-circle", "Notifiche della chat")
        self.notifications = SettingsToggleRow(
            "Notifiche desktop", "Mostra una notifica desktop per i nuovi messaggi."
        )
        notifications_card.add_row(self.notifications)
        layout.addWidget(notifications_card)

        profile_card = SettingsCard(
            "user-round", "Visibilità del profilo",
            "Decidi cosa mostrare a questo contatto nella schermata profilo.",
        )
        self.identity_visibility = SettingsToggleRow(
            "Mostra il mio Identity ID",
            "Consente a questo contatto di visualizzarlo aprendo il tuo profilo.",
        )
        profile_card.add_row(self.identity_visibility)
        identity_hint = QLabel(
            "L’Identity ID resta necessario al protocollo crittografico: questa opzione ne controlla soltanto "
            "la visualizzazione nell’interfaccia."
        )
        identity_hint.setObjectName("muted")
        identity_hint.setWordWrap(True)
        identity_hint.setContentsMargins(14, 11, 14, 13)
        profile_card.add_row(identity_hint)
        layout.addWidget(profile_card)

        export_card = SettingsCard(
            "terminal", "Dati e diagnostica", "Esporta questa conversazione con timestamp e ritardi."
        )
        export_row = QFrame()
        export_row.setObjectName("settingsRow")
        export_layout = QHBoxLayout(export_row)
        export_layout.setContentsMargins(14, 12, 14, 12)
        export = QPushButton("Esporta dati chat")
        export.setIcon(lucide_icon("upload"))
        export.clicked.connect(self.export_requested.emit)
        export_layout.addWidget(export)
        export_layout.addStretch()
        export_card.add_row(export_row)
        layout.addWidget(export_card)
        layout.addStretch()
        scroll.setWidget(host)
        root.addWidget(scroll, 1)

        save = QPushButton("Salva modifiche")
        save.setObjectName("primary")
        save.setIcon(lucide_icon("shield-check", "#07120e"))
        save.clicked.connect(self._save)
        root.addWidget(save)

    @staticmethod
    def _select_row(title: str, detail: str) -> tuple[QFrame, QComboBox]:
        row = QFrame()
        row.setObjectName("settingsRow")
        layout = QVBoxLayout(row)
        layout.setContentsMargins(14, 11, 14, 12)
        layout.setSpacing(5)
        heading = QLabel(title)
        heading.setStyleSheet("font-weight: 650;")
        description = QLabel(detail)
        description.setObjectName("muted")
        description.setWordWrap(True)
        combo = ModernComboBox()
        layout.addWidget(heading)
        layout.addWidget(description)
        layout.addWidget(combo)
        return row, combo

    @staticmethod
    def _load_tri_state(box: QComboBox, value: object, global_value: bool) -> None:
        box.clear()
        state = tr("attivo" if global_value else "disattivo")
        box.addItem(tr_format("Automatico ({state})", state=state), None)
        box.addItem(tr("Attivo"), True)
        box.addItem(tr("Disattivo"), False)
        box.setCurrentIndex(0 if value is None else (1 if value else 2))

    def load_settings(self, contact: IdentityBundle, current: dict, global_settings: dict) -> None:
        set_avatar(self.contact_avatar, contact, 42)
        self.contact_name.setText(contact.name)
        self._load_tri_state(
            self.delivery, current.get("send_delivery_receipts"), bool(global_settings["send_delivery_receipts"])
        )
        self._load_tri_state(
            self.reads, current.get("send_read_receipts"), bool(global_settings["send_read_receipts"])
        )
        self._load_tri_state(
            self.previews, current.get("link_previews"), bool(global_settings["link_previews"])
        )
        self.notifications.switch.setChecked(bool(current.get("notifications", True)))
        self.identity_visibility.switch.setChecked(bool(current.get("show_identity_id", True)))

    def _save(self) -> None:
        self.save_requested.emit({
            "send_delivery_receipts": self.delivery.currentData(),
            "send_read_receipts": self.reads.currentData(),
            "link_previews": self.previews.currentData(),
            "notifications": self.notifications.isChecked(),
            "show_identity_id": self.identity_visibility.isChecked(),
        })


class ContactProfilePanel(QFrame):
    close_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("chatSettingsPanel")
        self.setFixedWidth(360)
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        header = QHBoxLayout()
        icon = QLabel()
        icon.setFixedSize(34, 34)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setPixmap(lucide_icon("user-round", COLORS["accent"], 19).pixmap(19, 19))
        icon.setStyleSheet(f"background: {COLORS['accent_dark']}; border-radius: 8px;")
        text = QVBoxLayout()
        text.setSpacing(1)
        title = QLabel("Profilo del contatto")
        title.setStyleSheet("font-size: 17px; font-weight: 700;")
        subtitle = QLabel("Contatto firmato e verificato")
        subtitle.setObjectName("muted")
        text.addWidget(title)
        text.addWidget(subtitle)
        close = QToolButton()
        close.setIcon(lucide_icon("x"))
        close.setToolTip("Chiudi")
        close.clicked.connect(self.close_requested.emit)
        header.addWidget(icon)
        header.addLayout(text, 1)
        header.addWidget(close, alignment=Qt.AlignmentFlag.AlignTop)
        root.addLayout(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.viewport().setStyleSheet("background: transparent;")
        host = QWidget()
        host.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 4, 0)
        layout.setSpacing(10)

        summary = QFrame()
        summary.setObjectName("settingsCard")
        summary_layout = QVBoxLayout(summary)
        summary_layout.setContentsMargins(16, 18, 16, 18)
        summary_layout.setSpacing(7)
        self.avatar = QLabel()
        self.avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.name = QLabel()
        self.name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.name.setStyleSheet("font-size: 20px; font-weight: 750;")
        verified = QLabel("✓  Profilo firmato e verificato")
        verified.setAlignment(Qt.AlignmentFlag.AlignCenter)
        verified.setStyleSheet(f"color: {COLORS['accent']}; font-weight: 650;")
        keys = QLabel("Chiavi pubbliche Ed25519, X25519 e ML-KEM-768")
        keys.setObjectName("muted")
        keys.setAlignment(Qt.AlignmentFlag.AlignCenter)
        keys.setWordWrap(True)
        summary_layout.addWidget(self.avatar, alignment=Qt.AlignmentFlag.AlignCenter)
        summary_layout.addWidget(self.name)
        summary_layout.addWidget(verified)
        summary_layout.addWidget(keys)
        layout.addWidget(summary)

        identity_card = SettingsCard(
            "shield-check", "Identity ID", "Identificatore crittografico stabile del contatto."
        )
        identity_content = QFrame()
        identity_content.setObjectName("settingsRow")
        identity_layout = QVBoxLayout(identity_content)
        identity_layout.setContentsMargins(14, 12, 14, 14)
        identity_layout.setSpacing(8)
        self.identity_field = QLineEdit()
        self.identity_field.setReadOnly(True)
        self.identity_field.setStyleSheet("font-family: Consolas; font-size: 12px;")
        self.hidden_identity = QLabel("Identity ID nascosto\nQuesto contatto ha scelto di non mostrarlo nel profilo.")
        self.hidden_identity.setObjectName("muted")
        self.hidden_identity.setWordWrap(True)
        self.copy_identity = QPushButton("Copia ID")
        self.copy_identity.setIcon(lucide_icon("copy"))
        self.copy_identity.clicked.connect(self._copy_identity)
        identity_layout.addWidget(self.identity_field)
        identity_layout.addWidget(self.hidden_identity)
        identity_layout.addWidget(self.copy_identity, alignment=Qt.AlignmentFlag.AlignLeft)
        identity_card.add_row(identity_content)
        layout.addWidget(identity_card)

        address_card = SettingsCard("network", "Indirizzo I2P", "Destination pubblica usata per raggiungere il contatto.")
        address_content = QFrame()
        address_content.setObjectName("settingsRow")
        address_layout = QVBoxLayout(address_content)
        address_layout.setContentsMargins(14, 12, 14, 14)
        self.address_field = QLineEdit()
        self.address_field.setReadOnly(True)
        self.address_field.setStyleSheet("font-family: Consolas; font-size: 12px;")
        address_layout.addWidget(self.address_field)
        address_card.add_row(address_content)
        layout.addWidget(address_card)
        layout.addStretch()
        scroll.setWidget(host)
        root.addWidget(scroll, 1)

    def load_profile(self, contact: IdentityBundle, identity_id_visible: bool) -> None:
        set_avatar(self.avatar, contact, 84)
        self.name.setText(contact.name)
        self.identity_field.setText(contact.identity_id if identity_id_visible else "")
        self.identity_field.setVisible(identity_id_visible)
        self.copy_identity.setVisible(identity_id_visible)
        self.hidden_identity.setVisible(not identity_id_visible)
        try:
            address = destination_b32(contact.destination)
        except ValueError:
            try:
                address = profile_destination(contact.profile_code)
            except ValueError:
                address = tr("Non disponibile")
        self.address_field.setText(address)

    def _copy_identity(self) -> None:
        if self.identity_field.text():
            QApplication.clipboard().setText(self.identity_field.text())
            self.copy_identity.setText(tr("ID copiato"))
            QTimer.singleShot(1600, lambda: self.copy_identity.setText(tr("Copia ID")))


class NetworkInsightsPanel(QWidget):
    refresh_requested = pyqtSignal()
    lookup_requested = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._detail_labels: dict[str, QLabel] = {}
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 16)
        root.setSpacing(10)

        controls = QHBoxLayout()
        self.refresh = QPushButton("Aggiorna connessioni")
        self.refresh.setIcon(lucide_icon("refresh-cw"))
        self.refresh.clicked.connect(self.refresh_requested.emit)
        controls.addStretch()
        controls.addWidget(self.refresh)
        root.addLayout(controls)

        self.status = QLabel("Lettura automatica delle connessioni del router I2P locale…")
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        self.disclosure = QToolButton()
        self.disclosure.setObjectName("peerDisclosure")
        self.disclosure.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.disclosure.setCheckable(True)
        self.disclosure.setChecked(True)
        self.disclosure.clicked.connect(self._set_expanded)
        root.addWidget(self.disclosure, alignment=Qt.AlignmentFlag.AlignLeft)
        self.peer_host = QWidget()
        self.peer_layout = QVBoxLayout(self.peer_host)
        self.peer_layout.setContentsMargins(0, 0, 0, 0)
        self.peer_layout.setSpacing(8)
        root.addWidget(self.peer_host)
        self._peer_count = 0
        self._set_expanded(True)

    def _set_expanded(self, expanded: bool) -> None:
        self.disclosure.setChecked(expanded)
        self.disclosure.setIcon(lucide_icon("chevron-down" if expanded else "chevron-right", COLORS["muted"], 16))
        self.disclosure.setText(tr_format("Connessioni rilevate ({count})", count=self._peer_count))
        self.disclosure.setToolTip(tr("Comprimi elenco peer" if expanded else "Espandi elenco peer"))
        self.peer_host.setVisible(expanded)

    def set_loading(self, loading: bool) -> None:
        self.refresh.setEnabled(not loading)
        self.refresh.setText(tr("Analisi in corso…") if loading else tr("Aggiorna connessioni"))
        if loading:
            self.status.setText(tr("Lettura delle connessioni del router I2P locale…"))

    def set_peers(self, peers: list[dict]) -> None:
        while self.peer_layout.count():
            item = self.peer_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._detail_labels.clear()
        self._peer_count = len(peers)
        self._set_expanded(self.disclosure.isChecked())
        if not peers:
            self.status.setText(tr("Nessun peer pubblico I2P rilevato. Verifica che il router sia avviato."))
            return
        self.status.setText(tr_format("{count} peer di trasporto osservati. Non rappresentano necessariamente gli hop esatti dei tunnel.", count=len(peers)))
        for peer in peers:
            ip = str(peer.get("ip", ""))
            row = QFrame()
            row.setObjectName("settingsCard")
            layout = QHBoxLayout(row)
            layout.setContentsMargins(12, 10, 12, 10)
            icon = QLabel()
            icon.setPixmap(lucide_icon("network", COLORS["accent"], 18).pixmap(18, 18))
            text = QVBoxLayout()
            text.setSpacing(2)
            endpoint = QLabel(f"{ip}:{peer.get('port', '')}")
            endpoint.setStyleSheet("font-family: Consolas; font-weight: 650;")
            detail = QLabel(tr("Paese e rete non ancora richiesti"))
            detail.setObjectName("muted")
            detail.setWordWrap(True)
            text.addWidget(endpoint)
            text.addWidget(detail)
            info = QPushButton("Dettagli IP")
            info.setIcon(lucide_icon("info"))
            info.clicked.connect(lambda _checked=False, selected=ip: self.lookup_requested.emit(selected))
            layout.addWidget(icon, alignment=Qt.AlignmentFlag.AlignTop)
            layout.addLayout(text, 1)
            layout.addWidget(info)
            self._detail_labels[ip] = detail
            self.peer_layout.addWidget(row)

    def set_lookup_result(self, ip: str, result: dict[str, str]) -> None:
        label = self._detail_labels.get(ip)
        if label is None:
            return
        country = result.get("country") or result.get("country_code") or tr("Paese sconosciuto")
        code = result.get("country_code", "")
        flag = "".join(chr(127397 + ord(char)) for char in code.upper()) if len(code) == 2 else ""
        network = result.get("as_name") or result.get("asn") or tr("Rete sconosciuta")
        label.setText(f"{flag} {country}  ·  {network}".strip())

    def set_lookup_error(self, ip: str, error: str) -> None:
        label = self._detail_labels.get(ip)
        if label is not None:
            label.setText(tr_format("Info IP non disponibile: {detail}", detail=tr(error)))


class TitleBar(QFrame):
    def __init__(self, window: "KerberusWindow"):
        super().__init__(window)
        self.window = window
        self.setObjectName("titlebar")
        self.setFixedHeight(42)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 0, 0, 0)
        layout.setSpacing(8)
        mark = QLabel("K")
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark.setFixedSize(24, 24)
        mark.setStyleSheet(f"background: {COLORS['accent_dark']}; color: {COLORS['accent']}; border-radius: 5px; font-weight: 800;")
        title = QLabel("Kerberus")
        title.setStyleSheet("font-weight: 650;")
        layout.addWidget(mark)
        layout.addWidget(title)
        layout.addStretch(1)

        self.minimize_button = self._window_button("minus", "Minimizza")
        self.maximize_button = self._window_button("maximize-2", "Massimizza")
        self.close_button = self._window_button("x", "Chiudi", close=True)
        self.minimize_button.clicked.connect(window.showMinimized)
        self.maximize_button.clicked.connect(window.toggle_maximize)
        self.close_button.clicked.connect(window.close)
        layout.addWidget(self.minimize_button)
        layout.addWidget(self.maximize_button)
        layout.addWidget(self.close_button)

    def _window_button(self, icon: str, tooltip: str, close: bool = False) -> QToolButton:
        button = QToolButton()
        button.setObjectName("closeButton" if close else "windowButton")
        button.setIcon(lucide_icon(icon))
        button.setIconSize(QSize(14, 14))
        button.setFixedSize(46, 41)
        button.setToolTip(tooltip)
        return button

    def update_maximize_icon(self, maximized: bool) -> None:
        self.maximize_button.setIcon(lucide_icon("minimize-2" if maximized else "maximize-2"))
        self.maximize_button.setToolTip("Ripristina" if maximized else "Massimizza")

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.window.windowHandle():
            self.window.windowHandle().startSystemMove()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.window.toggle_maximize()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class ResizeHandle(QWidget):
    def __init__(self, window: "KerberusWindow", edges: Qt.Edge):
        super().__init__(window)
        self.window = window
        self.edges = edges
        if edges in (Qt.Edge.TopEdge | Qt.Edge.LeftEdge, Qt.Edge.BottomEdge | Qt.Edge.RightEdge):
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        elif edges in (Qt.Edge.TopEdge | Qt.Edge.RightEdge, Qt.Edge.BottomEdge | Qt.Edge.LeftEdge):
            self.setCursor(Qt.CursorShape.SizeBDiagCursor)
        elif edges & (Qt.Edge.LeftEdge | Qt.Edge.RightEdge):
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        else:
            self.setCursor(Qt.CursorShape.SizeVerCursor)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.window.windowHandle():
            self.window.windowHandle().startSystemResize(self.edges)
            event.accept()
            return
        super().mousePressEvent(event)


class KerberusWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.service = MessengerService(AppConfig())
        self.signals = AppSignals()
        self.selected_contact = ""
        self._connecting = False
        self._router_connected = False
        self._router_detail = "Verifica non ancora completata"
        self._workers: list[threading.Thread] = []
        self._preview_pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="kerberus-preview")
        self._network_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="kerberus-ip-info")
        self._resources_released = False
        self._download_dialog: KerberusProgressDialog | None = None
        # Il bordo resta ridimensionabile, ma non copre la scrollbar della chat.
        self._resize_margin = 2
        self._allow_close = False
        self._shutdown_complete = False
        self._ui_events: list[str] = []
        self._open_dialogs: set[QDialog] = set()
        self._modeless_by_title: dict[str, QDialog] = {}
        self._link_preview_cache: dict[str, dict] = {}
        self._link_preview_waiters: dict[str, list[LinkPreviewCard]] = {}
        self._link_preview_pending: set[str] = set()
        self._ip_lookup_cache: dict[str, dict[str, str]] = {}
        self._ip_lookup_pending: set[str] = set()
        self._rendered_contact = ""
        self._bubble_local_author: IdentityBundle | None = None
        self._bubble_remote_author: IdentityBundle | None = None
        self._bubble_local_avatar: QPixmap | None = None
        self._bubble_remote_avatar: QPixmap | None = None
        self._bubble_link_previews = False
        self._emoji_panel_open = False
        self._emoji_reaction_message: dict | None = None
        self._chat_settings_panel_open = False
        self._contact_profile_panel_open = False
        self._stream_proof_active = False
        self._stream_proof_detail = ""
        self._tray: QSystemTrayIcon | None = None
        self._voice_recorder = VoiceRecorder(self)
        self._voice_recorder.finished.connect(self._voice_recorded)
        self._voice_recorder.failed.connect(self._voice_recording_failed)
        self._voice_record_started = 0.0
        self._voice_record_contact = ""
        self._voice_record_mode = "message"
        self._audio_test_output_device_id = ""
        self._audio_test_status: QLabel | None = None
        self._audio_test_button: QPushButton | None = None
        self._voice_privacy_acknowledged = False
        self._voice_timer = QTimer(self)
        self._voice_timer.setInterval(250)
        self._voice_timer.timeout.connect(self._update_voice_recording)
        self._voice_player: QMediaPlayer | None = None
        self._voice_audio_output: QAudioOutput | None = None
        self._voice_buffer: QBuffer | None = None
        self._attachment_temp_dir = tempfile.TemporaryDirectory(prefix="kerberus-media-")
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle("Kerberus")
        self.setMinimumSize(1020, 620)
        self.resize(1180, 760)
        self.signals.message_received.connect(self.refresh_messages)
        self.signals.contacts_changed.connect(self._contact_arrived)
        self.signals.protocol_event.connect(self._protocol_event)
        self.signals.router_changed.connect(self._set_router_status)
        self.signals.download_progress.connect(self._update_download)
        self.service.on_message = self.signals.message_received.emit
        self.service.on_contacts_changed = self.signals.contacts_changed.emit
        self.service.on_protocol_event = self.signals.protocol_event.emit

    def initialize(self) -> bool:
        create = not self.service.vault.exists
        password = PasswordDialog(create, self)
        if password.exec() != QDialog.DialogCode.Accepted:
            return False
        try:
            if create:
                self.service.vault.create(password.password.text())
            else:
                self.service.vault.unlock(password.password.text())
        except Exception as exc:
            KerberusMessageDialog.show_message(self, "Vault", str(exc))
            return self.initialize()
        if not pq_available():
            KerberusMessageDialog.show_message(
                self,
                "Post-quantum",
                "Il backend ML-KEM-768 non può essere caricato. Reinstalla Kerberus con l'installer più recente.\n\n"
                f"Dettaglio tecnico: {pq_unavailable_reason()}",
            )
            return False
        set_language(str(self.service.settings().get("language", "it")))
        appearance = self.service.settings()
        apply_appearance(
            str(appearance.get("theme", "default")),
            int(appearance.get("text_scale", 100)),
            str(appearance.get("ui_density", "comfortable")),
        )
        if not self.service.identity():
            name, ok = self._ask_name()
            if not ok:
                return False
            self.service.create_identity(name)
        self._build_ui()
        localize_widget(self)
        self._setup_tray()
        self.refresh_contacts()
        QTimer.singleShot(150, self.connect_router)
        if self.service.settings().get("clearnet_enabled", False):
            QTimer.singleShot(5000, self.check_updates)
        return True

    def _ask_name(self) -> tuple[str, bool]:
        dialog = KerberusDialog("Nuovo profilo", self, 430)
        layout = dialog.body_layout
        layout.setContentsMargins(28, 26, 28, 26)
        title = QLabel("Crea il tuo profilo")
        title.setObjectName("dialogTitle")
        layout.addWidget(title)
        field = QLineEdit()
        field.setPlaceholderText("Nome visibile")
        layout.addWidget(field)
        submit = QPushButton("Continua")
        submit.setObjectName("primary")
        submit.clicked.connect(dialog.accept)
        layout.addWidget(submit, alignment=Qt.AlignmentFlag.AlignRight)
        field.returnPressed.connect(dialog.accept)
        accepted = dialog.exec() == QDialog.DialogCode.Accepted and bool(field.text().strip())
        return field.text().strip(), accepted

    def _build_ui(self) -> None:
        root = QFrame()
        root.setObjectName("appShell")
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        self.title_bar = TitleBar(self)
        root_layout.addWidget(self.title_bar)
        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)
        body_layout.addWidget(self._build_sidebar())
        body_layout.addWidget(self._build_content(), 1)
        root_layout.addWidget(body, 1)
        self.setCentralWidget(root)
        if hasattr(self, "emoji_panel"):
            self.emoji_panel.hide()
        if hasattr(self, "chat_side_panel"):
            self.chat_side_panel.hide()
        self._create_resize_handles()
        self._log_action("UI pronta")

    def _create_resize_handles(self) -> None:
        for handle in getattr(self, "_resize_handles", []):
            handle.hide()
            handle.deleteLater()
        edge_sets = (
            Qt.Edge.TopEdge,
            Qt.Edge.BottomEdge,
            Qt.Edge.LeftEdge,
            Qt.Edge.RightEdge,
            Qt.Edge.TopEdge | Qt.Edge.LeftEdge,
            Qt.Edge.TopEdge | Qt.Edge.RightEdge,
            Qt.Edge.BottomEdge | Qt.Edge.LeftEdge,
            Qt.Edge.BottomEdge | Qt.Edge.RightEdge,
        )
        self._resize_handles = [ResizeHandle(self, edges) for edges in edge_sets]
        self._position_resize_handles()

    def _position_resize_handles(self) -> None:
        if not hasattr(self, "_resize_handles"):
            return
        margin = self._resize_margin
        width, height = self.width(), self.height()
        geometries = (
            QRect(margin, 0, max(0, width - 2 * margin), margin),
            QRect(margin, height - margin, max(0, width - 2 * margin), margin),
            QRect(0, margin, margin, max(0, height - 2 * margin)),
            QRect(width - margin, margin, margin, max(0, height - 2 * margin)),
            QRect(0, 0, margin, margin),
            QRect(width - margin, 0, margin, margin),
            QRect(0, height - margin, margin, margin),
            QRect(width - margin, height - margin, margin, margin),
        )
        for handle, geometry in zip(self._resize_handles, geometries):
            handle.setGeometry(geometry)
            handle.setVisible(not self.isMaximized())
            handle.raise_()

    def resizeEvent(self, event: QResizeEvent) -> None:
        self._position_resize_handles()
        if self.isMaximized():
            self.clearMask()
        else:
            path = QPainterPath()
            path.addRoundedRect(0, 0, self.width(), self.height(), 12, 12)
            self.setMask(QRegion(path.toFillPolygon().toPolygon()))
        super().resizeEvent(event)

    def toggle_maximize(self) -> None:
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()
        QTimer.singleShot(0, lambda: self.title_bar.update_maximize_icon(self.isMaximized()))

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.WindowStateChange and hasattr(self, "title_bar"):
            self.title_bar.update_maximize_icon(self.isMaximized())
            self._position_resize_handles()
        super().changeEvent(event)

    def showEvent(self, event: QEvent) -> None:
        super().showEvent(event)
        QTimer.singleShot(0, self._apply_stream_proof_setting)

    def _apply_stream_proof_setting(self, notify: bool = False) -> bool:
        enabled = bool(self.service.settings().get("stream_proof_enabled", False))
        targets: list[QWidget] = [self]
        for widget in QApplication.topLevelWidgets():
            owner = widget.parentWidget()
            while owner is not None and owner is not self:
                owner = owner.parentWidget()
            if owner is self and widget not in targets:
                targets.append(widget)
        results = [set_window_capture_exclusion(target, enabled) for target in targets]
        success = all(result[0] for result in results)
        detail = next((result[1] for result in results if not result[0]), results[0][1])
        self._stream_proof_active = bool(enabled and success)
        self._stream_proof_detail = detail
        if enabled:
            self._log_action(
                "Protezione streaming attiva" if success
                else f"Protezione streaming non applicata: {detail}"
            )
        if notify:
            message = tr(detail) if success else tr_format(
                "Protezione streaming non disponibile: {detail}", detail=detail
            )
            self.statusBar().showMessage(message, 7000)
        return success

    def _activate_linux_stream_shield(self, enabled_override: bool | None = None) -> None:
        if not sys.platform.startswith("linux"):
            return
        enabled = (
            bool(enabled_override) if enabled_override is not None
            else bool(self.service.settings().get("stream_proof_enabled", False))
        )
        if not enabled:
            self.statusBar().showMessage(tr("Attiva prima la protezione streaming"), 5000)
            return
        if self._tray is None:
            self.statusBar().showMessage(
                tr("Area di notifica non disponibile: Kerberus è stato minimizzato"), 5000
            )
            self.showMinimized()
            return
        for widget in QApplication.topLevelWidgets():
            if widget is self:
                continue
            owner = widget.parentWidget()
            while owner is not None and owner is not self:
                owner = owner.parentWidget()
            if owner is self:
                widget.hide()
        self.hide()
        self._tray.showMessage(
            tr("Protezione streaming"),
            tr("Kerberus è nascosto dalla cattura. Usa l’icona nell’area di notifica per riaprirlo."),
            QSystemTrayIcon.MessageIcon.Information,
            5000,
        )

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if not self.isMaximized():
            self.setCursor(self._edge_cursor(event.position().toPoint()))
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and not self.isMaximized():
            edges = self._resize_edges(event.position().toPoint())
            if edges and self.windowHandle():
                self.windowHandle().startSystemResize(edges)
                event.accept()
                return
        super().mousePressEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        if not self.isMaximized():
            self.unsetCursor()
        super().leaveEvent(event)

    def _resize_edges(self, point: QPoint) -> Qt.Edge:
        edges = Qt.Edge(0)
        if point.x() <= self._resize_margin:
            edges |= Qt.Edge.LeftEdge
        elif point.x() >= self.width() - self._resize_margin:
            edges |= Qt.Edge.RightEdge
        if point.y() <= self._resize_margin:
            edges |= Qt.Edge.TopEdge
        elif point.y() >= self.height() - self._resize_margin:
            edges |= Qt.Edge.BottomEdge
        return edges

    def _edge_cursor(self, point: QPoint) -> Qt.CursorShape:
        edges = self._resize_edges(point)
        if edges in (Qt.Edge.TopEdge | Qt.Edge.LeftEdge, Qt.Edge.BottomEdge | Qt.Edge.RightEdge):
            return Qt.CursorShape.SizeFDiagCursor
        if edges in (Qt.Edge.TopEdge | Qt.Edge.RightEdge, Qt.Edge.BottomEdge | Qt.Edge.LeftEdge):
            return Qt.CursorShape.SizeBDiagCursor
        if edges & (Qt.Edge.LeftEdge | Qt.Edge.RightEdge):
            return Qt.CursorShape.SizeHorCursor
        if edges & (Qt.Edge.TopEdge | Qt.Edge.BottomEdge):
            return Qt.CursorShape.SizeVerCursor
        return Qt.CursorShape.ArrowCursor

    def _build_sidebar(self) -> QWidget:
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(310)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(16, 18, 16, 14)
        layout.setSpacing(12)
        brand_row = QHBoxLayout()
        brand = QLabel("KERBERUS")
        brand.setObjectName("brand")
        brand_row.addWidget(brand)
        brand_row.addStretch()
        add = QToolButton()
        add.setIcon(lucide_icon("user-plus", COLORS["accent"]))
        add.setIconSize(QSize(18, 18))
        add.setToolTip("Aggiungi contatto")
        add.clicked.connect(self.add_contact)
        brand_row.addWidget(add)
        layout.addLayout(brand_row)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Cerca conversazioni")
        self.search.setClearButtonEnabled(True)
        self.search.addAction(lucide_icon("search"), QLineEdit.ActionPosition.LeadingPosition)
        self.search.textChanged.connect(self.refresh_contacts)
        layout.addWidget(self.search)

        label = QLabel("CONVERSAZIONI")
        label.setObjectName("eyebrow")
        layout.addWidget(label)
        self.contacts_list = QListWidget()
        self.contacts_list.setSpacing(3)
        self.contacts_list.itemClicked.connect(self._select_contact_item)
        layout.addWidget(self.contacts_list, 1)

        status_row = ClickableFrame()
        status_row.setStyleSheet(f"background: {COLORS['surface']}; border-radius: 7px;")
        status_row.setCursor(Qt.CursorShape.PointingHandCursor)
        status_row.setToolTip("Apri informazioni I2P")
        status_row.clicked.connect(self.show_i2p_info)
        status_layout = QHBoxLayout(status_row)
        status_layout.setContentsMargins(11, 9, 9, 9)
        self.router_dot = QLabel()
        self.router_dot.setFixedSize(9, 9)
        if self._router_connected:
            router_color = COLORS["accent"]
            router_label = "I2P: connesso"
            router_meta = "Tunnel pronto · SAM locale"
        elif self._connecting:
            router_color = COLORS["warning"]
            router_label = "I2P: connessione..."
            router_meta = "Avvio router e tunnel"
        elif self._router_detail == "Verifica non ancora completata":
            router_color = COLORS["warning"]
            router_label = "I2P: verifica..."
            router_meta = "Controllo bridge SAM"
        else:
            router_color = COLORS["danger"]
            router_label = "I2P: non connesso"
            router_meta = "Nuovo tentativo tra 10 s"
        self.router_dot.setStyleSheet(f"background: {router_color}; border-radius: 4px;")
        self.router_text = QLabel(router_label)
        self.router_text.setObjectName("muted")
        self.router_text.setToolTip(self._router_detail)
        status_text = QVBoxLayout()
        status_text.setSpacing(1)
        self.router_meta = QLabel(router_meta)
        self.router_meta.setObjectName("muted")
        self.router_meta.setStyleSheet("font-size: 11px;")
        status_text.addWidget(self.router_text)
        status_text.addWidget(self.router_meta)
        configure = QToolButton()
        configure.setIcon(lucide_icon("network"))
        configure.setToolTip("Configura I2P")
        configure.clicked.connect(self.router_setup)
        status_layout.addWidget(self.router_dot)
        status_layout.addLayout(status_text, 1)
        status_layout.addWidget(configure)
        layout.addWidget(status_row)

        utility = QHBoxLayout()
        profile = QPushButton("Profilo")
        profile.setObjectName("ghost")
        profile.setIcon(lucide_icon("user-round"))
        profile.clicked.connect(self.show_profile)
        import_button = QPushButton("Importa")
        import_button.setObjectName("ghost")
        import_button.setIcon(lucide_icon("upload"))
        import_button.clicked.connect(self.import_contact)
        settings = QToolButton()
        settings.setIcon(lucide_icon("settings-2"))
        settings.setIconSize(QSize(20, 20))
        settings.setFixedSize(42, 42)
        settings.setToolTip("Impostazioni")
        settings.clicked.connect(self.show_settings)
        utility.addWidget(profile)
        utility.addWidget(import_button)
        utility.addWidget(settings)
        layout.addLayout(utility)
        return sidebar

    def _build_content(self) -> QWidget:
        content = QStackedWidget()
        self.content_stack = content
        empty = QWidget()
        empty_layout = QVBoxLayout(empty)
        empty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark = QLabel()
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark.setFixedSize(68, 68)
        mark.setPixmap(lucide_icon("message-circle", COLORS["accent"], 32).pixmap(32, 32))
        mark.setStyleSheet(f"background: {COLORS['accent_dark']}; border-radius: 8px;")
        title = QLabel("Le tue conversazioni")
        title.setObjectName("dialogTitle")
        subtitle = QLabel("Messaggistica privata attraverso I2P")
        subtitle.setObjectName("muted")
        empty_layout.addWidget(mark, alignment=Qt.AlignmentFlag.AlignCenter)
        empty_layout.addSpacing(10)
        empty_layout.addWidget(title, alignment=Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(subtitle, alignment=Qt.AlignmentFlag.AlignCenter)
        content.addWidget(empty)

        chat_page = QWidget()
        chat_layout = QVBoxLayout(chat_page)
        chat_layout.setContentsMargins(0, 0, 0, 0)
        chat_layout.setSpacing(0)
        topbar = ClickableFrame()
        topbar.setObjectName("topbar")
        topbar.setFixedHeight(76)
        topbar.setCursor(Qt.CursorShape.PointingHandCursor)
        topbar.setToolTip("Apri profilo")
        topbar.clicked.connect(self.show_contact_profile)
        topbar_layout = QHBoxLayout(topbar)
        topbar_layout.setContentsMargins(22, 12, 22, 12)
        name_box = QVBoxLayout()
        name_box.setSpacing(2)
        self.chat_avatar = QLabel()
        topbar_layout.addWidget(self.chat_avatar)
        self.chat_name = QLabel()
        self.chat_name.setObjectName("pageTitle")
        self.chat_security = QLabel("Canale ibrido X25519 + ML-KEM-768")
        self.chat_security.setObjectName("muted")
        name_box.addWidget(self.chat_name)
        name_box.addWidget(self.chat_security)
        topbar_layout.addLayout(name_box)
        topbar_layout.addStretch()
        self.contact_profile_button = QToolButton()
        self.contact_profile_button.setObjectName("chatSettingsToggle")
        self.contact_profile_button.setIcon(lucide_icon("user-round"))
        self.contact_profile_button.setIconSize(QSize(20, 20))
        self.contact_profile_button.setToolTip("Apri profilo")
        self.contact_profile_button.clicked.connect(self.show_contact_profile)
        topbar_layout.addWidget(self.contact_profile_button)
        self.chat_settings_button = QToolButton()
        self.chat_settings_button.setObjectName("chatSettingsToggle")
        self.chat_settings_button.setIcon(lucide_icon("settings-2"))
        self.chat_settings_button.setToolTip("Privacy di questa chat")
        self.chat_settings_button.clicked.connect(self.show_chat_settings)
        topbar_layout.addWidget(self.chat_settings_button)
        chat_layout.addWidget(topbar)

        chat_workspace = QWidget()
        workspace_layout = QHBoxLayout(chat_workspace)
        workspace_layout.setContentsMargins(0, 0, 0, 0)
        workspace_layout.setSpacing(0)
        conversation = QWidget()
        conversation_layout = QVBoxLayout(conversation)
        conversation_layout.setContentsMargins(0, 0, 0, 0)
        conversation_layout.setSpacing(0)

        self.message_view = VirtualChatView()
        self.message_view.on_action = self.message_action
        self.message_view.on_timing = self.show_message_timing
        self.message_view.on_open_link = lambda url: open_external_link(self, url)
        self.message_scroll = self.message_view
        conversation_layout.addWidget(self.message_scroll, 1)

        self.emoji_panel = EmojiPanel()
        self.emoji_panel.selected.connect(self._emoji_selected)
        self.emoji_panel.close_requested.connect(lambda: self._set_emoji_panel_visible(False))
        conversation_layout.addWidget(self.emoji_panel)
        self.emoji_panel.hide()

        composer_frame = QFrame()
        composer_frame.setObjectName("composer")
        composer_layout = QHBoxLayout(composer_frame)
        composer_layout.setContentsMargins(20, 14, 20, 16)
        composer_layout.setSpacing(10)
        self.attachment_button = QToolButton()
        self.attachment_button.setObjectName("attachmentButton")
        self.attachment_button.setIcon(lucide_icon("plus", COLORS["accent"], 22))
        self.attachment_button.setIconSize(QSize(22, 22))
        self.attachment_button.setFixedSize(48, 48)
        self.attachment_button.setToolTip("Invia un file cifrato (25 MB · video 100 MB)")
        self.attachment_button.clicked.connect(self.choose_attachment)
        composer_layout.addWidget(self.attachment_button, alignment=Qt.AlignmentFlag.AlignBottom)
        self.composer = ComposerEdit()
        self.composer.setPlaceholderText("Scrivi un messaggio")
        self.composer.setFixedHeight(58)
        self.composer.send_requested.connect(self.send_message)
        composer_layout.addWidget(self.composer, 1)
        self.voice_recording_label = QLabel("Registrazione 0:00 · massimo 2:00")
        self.voice_recording_label.setStyleSheet(f"color: {COLORS['danger']}; font-weight: 700;")
        self.voice_recording_label.hide()
        composer_layout.addWidget(self.voice_recording_label, 1)
        self.voice_cancel_button = QToolButton()
        self.voice_cancel_button.setObjectName("emojiToggle")
        self.voice_cancel_button.setIcon(lucide_icon("x", COLORS["danger"]))
        self.voice_cancel_button.setFixedSize(48, 48)
        self.voice_cancel_button.setToolTip("Annulla registrazione")
        self.voice_cancel_button.clicked.connect(self.cancel_voice_recording)
        self.voice_cancel_button.hide()
        composer_layout.addWidget(self.voice_cancel_button, alignment=Qt.AlignmentFlag.AlignBottom)
        self.voice_button = QToolButton()
        self.voice_button.setObjectName("emojiToggle")
        self.voice_button.setIcon(lucide_icon("mic", COLORS["danger"]))
        self.voice_button.setIconSize(QSize(21, 21))
        self.voice_button.setFixedSize(48, 48)
        self.voice_button.setToolTip("Registra messaggio vocale cifrato")
        self.voice_button.clicked.connect(self.toggle_voice_recording)
        composer_layout.addWidget(self.voice_button, alignment=Qt.AlignmentFlag.AlignBottom)
        self.emoji_button = QToolButton()
        self.emoji_button.setObjectName("emojiToggle")
        self.emoji_button.setIcon(lucide_icon("smile", COLORS["muted"], 22))
        self.emoji_button.setIconSize(QSize(22, 22))
        self.emoji_button.setFixedSize(48, 48)
        self.emoji_button.setToolTip("Apri menu emoji")
        self.emoji_button.clicked.connect(self.show_emoji_menu)
        composer_layout.addWidget(self.emoji_button, alignment=Qt.AlignmentFlag.AlignBottom)
        self.send_button = QToolButton()
        self.send_button.setObjectName("sendButton")
        self.send_button.setIcon(lucide_icon("send", "#07120e"))
        self.send_button.setIconSize(QSize(21, 21))
        self.send_button.setFixedSize(48, 48)
        self.send_button.setToolTip("Invia")
        self.send_button.clicked.connect(self.send_message)
        composer_layout.addWidget(self.send_button, alignment=Qt.AlignmentFlag.AlignBottom)
        conversation_layout.addWidget(composer_frame)
        workspace_layout.addWidget(conversation, 1)
        self.chat_settings_panel = ChatSettingsPanel()
        self.chat_settings_panel.close_requested.connect(
            lambda: self._set_chat_settings_panel_visible(False)
        )
        self.chat_settings_panel.save_requested.connect(self._save_chat_settings)
        self.chat_settings_panel.export_requested.connect(
            lambda: self.export_chat_debug(self.chat_settings_panel, self.selected_contact)
        )
        self.contact_profile_panel = ContactProfilePanel()
        self.contact_profile_panel.close_requested.connect(
            lambda: self._set_contact_profile_panel_visible(False)
        )
        self.chat_side_panel = QStackedWidget()
        self.chat_side_panel.setFixedWidth(360)
        self.chat_side_panel.addWidget(self.chat_settings_panel)
        self.chat_side_panel.addWidget(self.contact_profile_panel)
        workspace_layout.addWidget(self.chat_side_panel)
        chat_layout.addWidget(chat_workspace, 1)
        content.addWidget(chat_page)
        # QStackedWidget resets child visibility while adopting the page.
        self.emoji_panel.hide()
        self.chat_side_panel.hide()
        return content

    def refresh_contacts(self, *_args) -> None:
        if not hasattr(self, "contacts_list"):
            return
        query = self.search.text().strip().lower()
        selected = self.selected_contact
        self.contacts_list.clear()
        for contact in self.service.contacts():
            if query and query not in contact.name.lower() and query not in contact.profile_code.lower():
                continue
            messages = self.service.messages_for(contact.identity_id)
            preview = messages[-1]["text"] if messages else "Nuovo contatto"
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, contact.identity_id)
            item.setSizeHint(QSize(270, 62))
            self.contacts_list.addItem(item)
            self.contacts_list.setItemWidget(item, ContactRow(contact, preview))
            if contact.identity_id == selected:
                self.contacts_list.setCurrentItem(item)
        for pending in self.service.pending_contacts():
            if query and query not in "richiesta in attesa":
                continue
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, "")
            item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            item.setSizeHint(QSize(270, 62))
            self.contacts_list.addItem(item)
            self.contacts_list.setItemWidget(item, PendingContactRow(pending, self.cancel_pending_contact))

    def cancel_pending_contact(self, destination: str) -> None:
        if not destination:
            return
        if not KerberusMessageDialog.ask(
            self,
            "Annulla richiesta",
            "Annullare questa richiesta di contatto e interrompere i tentativi automatici?",
        ):
            return
        if self.service.cancel_pending_contact(destination):
            self.refresh_contacts()
            self.statusBar().showMessage(tr("Richiesta contatto annullata"), 4000)

    def _select_contact_item(self, item: QListWidgetItem) -> None:
        self.select_contact(item.data(Qt.ItemDataRole.UserRole))

    def select_contact(self, contact_id: str) -> None:
        if self._voice_recorder.active and contact_id != self._voice_record_contact:
            self.cancel_voice_recording()
        contacts = {contact.identity_id: contact for contact in self.service.contacts()}
        contact = contacts.get(contact_id)
        if not contact:
            return
        self.selected_contact = contact_id
        set_avatar(self.chat_avatar, contact, 44)
        self.chat_name.setText(contact.name)
        self._emoji_reaction_message = None
        self._set_emoji_panel_visible(False)
        self._set_chat_settings_panel_visible(False)
        self._set_contact_profile_panel_visible(False)
        self.content_stack.setCurrentIndex(1)
        self.refresh_messages("select", contact_id)
        self._run_task(
            lambda: self.service.mark_chat_read(contact_id),
            lambda _value: None,
            lambda error: self._log_action(f"Errore ricevuta di lettura: {error}"),
        )
        self.composer.setFocus()

    def _prepare_message_render_context(self) -> None:
        self._bubble_local_author = self.service.identity()
        contact_data = self.service.vault.state.get("contacts", {}).get(self.selected_contact)
        self._bubble_remote_author = IdentityBundle.from_dict(contact_data) if contact_data else None
        self._bubble_local_avatar = (
            avatar_pixmap(self._bubble_local_author, 34) if self._bubble_local_author is not None else None
        )
        self._bubble_remote_avatar = (
            avatar_pixmap(self._bubble_remote_author, 34) if self._bubble_remote_author is not None else None
        )
        self._bubble_link_previews = bool(
            self.service.effective_chat_setting(self.selected_contact, "link_previews")
        )

    def refresh_messages(self, reason: str = "new", contact_id: str = "") -> None:
        if reason == "new" and contact_id and self._tray is not None and not self.isActiveWindow():
            contact_messages = self.service.messages_for(contact_id)
            if (
                contact_messages
                and contact_messages[-1].get("direction") == "in"
                and self.service.chat_settings(contact_id).get("notifications", True)
            ):
                self._tray.showMessage(
                    "Nuovo messaggio cifrato",
                    "Kerberus ha ricevuto un nuovo messaggio.",
                    QSystemTrayIcon.MessageIcon.Information,
                    4000,
                )
        if not self.selected_contact or not hasattr(self, "message_view"):
            if contact_id:
                self.refresh_contacts()
            return
        if contact_id and contact_id != self.selected_contact:
            self.refresh_contacts()
            return
        all_messages = self.service.messages_for(self.selected_contact)
        scrollbar = self.message_scroll.verticalScrollBar()
        distance_from_bottom = max(0, scrollbar.maximum() - scrollbar.value())
        was_at_bottom = distance_from_bottom <= 24
        changed_contact = self._rendered_contact != self.selected_contact
        self._prepare_message_render_context()
        self.message_view.configure(
            self._bubble_local_author,
            self._bubble_remote_author,
            self._bubble_local_avatar,
            self._bubble_remote_avatar,
            self._bubble_link_previews,
            self._link_preview_cache,
            self._request_message_link_preview if self._bubble_link_previews else None,
        )
        old_count = len(self.message_view.chat_model.messages)
        sync_mode = self.message_view.sync_messages(all_messages)
        added = all_messages[old_count:] if sync_mode == "appended" else []
        self._rendered_contact = self.selected_contact
        if reason != "status":
            self.refresh_contacts()
        should_follow_bottom = (
            changed_contact
            or reason == "select"
            or (bool(added) and (
                was_at_bottom or any(message.get("direction") == "out" for message in added)
            ))
        )
        if should_follow_bottom:
            self._pin_scroll_to_bottom()
        elif sync_mode == "reset" and not changed_contact:
            QTimer.singleShot(0, lambda: scrollbar.setValue(
                max(scrollbar.minimum(), scrollbar.maximum() - distance_from_bottom)
            ))

    def load_older_messages(self) -> None:
        # The virtualized model always contains the complete conversation.
        return

    def _pin_scroll_to_bottom(self) -> None:
        QTimer.singleShot(0, self.message_view.scrollToBottom)

    def message_action(self, action: str, message: dict) -> None:
        if action in {"pause_attachment", "resume_attachment"}:
            paused = action == "pause_attachment"
            message_id = str(message.get("message_id", ""))
            self._run_task(
                lambda: self.service.set_attachment_paused(message_id, paused),
                lambda _value: self.refresh_messages("status", self.selected_contact),
                lambda error: self._error(tr("Allegato"), error),
            )
            return
        if action == "cancel_attachment":
            if not KerberusMessageDialog.ask(
                self, tr("Annulla trasferimento"), tr("Interrompere e annullare questo trasferimento?"),
            ):
                return
            message_id = str(message.get("message_id", ""))
            self._run_task(
                lambda: self.service.cancel_attachment(message_id),
                lambda _value: self.refresh_messages("status", self.selected_contact),
                lambda error: self._error(tr("Allegato"), error),
            )
            return
        if action == "save_attachment":
            self.save_attachment(message)
            return
        if action == "play_video":
            message_id = str(message.get("message_id", ""))
            self._run_task(
                lambda: self._prepare_inline_video(message_id),
                self._play_inline_video_ready,
                lambda error: self._error("Video", error),
            )
            return
        if action == "play_voice":
            message_id = str(message.get("message_id", ""))
            self.statusBar().showMessage(tr("Decodifica vocale con il codec Go…"), 3000)
            self._run_task(
                lambda: self.service.decode_voice(message_id),
                self._play_voice_wav,
                lambda error: self._error("Messaggio vocale", error),
            )
            return
        if action == "reaction_picker":
            self._emoji_reaction_message = message
            self.emoji_panel.set_reaction_mode(True)
            self._set_chat_settings_panel_visible(False)
            self._set_contact_profile_panel_visible(False)
            self._set_emoji_panel_visible(True)
            return
        if action.startswith("react:"):
            emoji = action.split(":", 1)[1]
            self._run_task(
                lambda: self.service.react_to_message(self.selected_contact, str(message.get("message_id", "")), emoji),
                lambda _value: self.refresh_messages("status", self.selected_contact),
                lambda error: self._error("Reazione", error),
            )
            return
        if action == "copy":
            QApplication.clipboard().setText(str(message.get("text", "")))
            self.statusBar().showMessage(tr("Messaggio copiato"), 2500)
            return
        if action == "delete":
            if KerberusMessageDialog.ask(
                self,
                "Elimina messaggio",
                "Eliminare questo messaggio soltanto dal vault locale? Non verrà cancellato dal dispositivo del contatto.",
            ):
                self.service.delete_message(str(message.get("message_id", "")))
                self.refresh_messages("delete", self.selected_contact)
            return
        if action == "forward":
            self.forward_message(message)

    def _emoji_selected(self, value: str) -> None:
        reaction_message = self._emoji_reaction_message
        if reaction_message is not None:
            # Keep the embedded picker open so several reactions can be added
            # to the same message without reopening the context menu.
            self.message_action("react:" + value, reaction_message)
            return
        self.composer.insertPlainText(value)
        self.composer.setFocus()

    def _set_emoji_panel_visible(self, visible: bool) -> None:
        if not hasattr(self, "emoji_panel"):
            return
        self._emoji_panel_open = visible
        self.emoji_panel.setVisible(visible)
        self.emoji_button.setProperty("active", visible)
        self.emoji_button.setIcon(lucide_icon(
            "smile", COLORS["accent"] if visible else COLORS["muted"], 22
        ))
        self.emoji_button.style().unpolish(self.emoji_button)
        self.emoji_button.style().polish(self.emoji_button)
        if visible:
            self.emoji_panel.search.setFocus()

    def show_emoji_menu(self, _anchor: QToolButton | None = None) -> None:
        self._emoji_reaction_message = None
        self.emoji_panel.set_reaction_mode(False)
        opening = not self._emoji_panel_open
        if opening:
            self._set_chat_settings_panel_visible(False)
            self._set_contact_profile_panel_visible(False)
        self._set_emoji_panel_visible(opening)

    def show_contact_profile(self) -> None:
        if not self.selected_contact:
            return
        contact = next(
            (item for item in self.service.contacts() if item.identity_id == self.selected_contact),
            None,
        )
        if contact is None:
            return
        identity_id_visible = bool(
            self.service.chat_settings(contact.identity_id).get("remote_identity_id_visible", True)
        )
        if self._contact_profile_panel_open:
            self._set_contact_profile_panel_visible(False)
            return
        self.contact_profile_panel.load_profile(contact, identity_id_visible)
        self._set_emoji_panel_visible(False)
        self._set_chat_settings_panel_visible(False)
        self._set_contact_profile_panel_visible(True)

    def show_chat_settings(self) -> None:
        if not self.selected_contact:
            return
        if self._chat_settings_panel_open:
            self._set_chat_settings_panel_visible(False)
            return
        contact = next(
            (item for item in self.service.contacts() if item.identity_id == self.selected_contact),
            None,
        )
        if contact is None:
            return
        self.chat_settings_panel.load_settings(
            contact,
            self.service.chat_settings(self.selected_contact),
            self.service.settings(),
        )
        self._set_emoji_panel_visible(False)
        self._set_contact_profile_panel_visible(False)
        self._set_chat_settings_panel_visible(True)

    def _set_chat_settings_panel_visible(self, visible: bool) -> None:
        if not hasattr(self, "chat_settings_panel"):
            return
        self._chat_settings_panel_open = visible
        if visible:
            self._contact_profile_panel_open = False
            self.chat_side_panel.setCurrentWidget(self.chat_settings_panel)
            self.chat_settings_panel.show()
            self.chat_side_panel.show()
            self.contact_profile_button.setProperty("active", False)
            self.contact_profile_button.style().unpolish(self.contact_profile_button)
            self.contact_profile_button.style().polish(self.contact_profile_button)
        elif not self._contact_profile_panel_open:
            self.chat_settings_panel.hide()
            self.chat_side_panel.hide()
        self.chat_settings_button.setProperty("active", visible)
        self.chat_settings_button.style().unpolish(self.chat_settings_button)
        self.chat_settings_button.style().polish(self.chat_settings_button)

    def _set_contact_profile_panel_visible(self, visible: bool) -> None:
        if not hasattr(self, "contact_profile_panel"):
            return
        self._contact_profile_panel_open = visible
        if visible:
            self._chat_settings_panel_open = False
            self.chat_side_panel.setCurrentWidget(self.contact_profile_panel)
            self.contact_profile_panel.show()
            self.chat_side_panel.show()
            self.chat_settings_button.setProperty("active", False)
            self.chat_settings_button.style().unpolish(self.chat_settings_button)
            self.chat_settings_button.style().polish(self.chat_settings_button)
        elif not self._chat_settings_panel_open:
            self.contact_profile_panel.hide()
            self.chat_side_panel.hide()
        self.contact_profile_button.setProperty("active", visible)
        self.contact_profile_button.style().unpolish(self.contact_profile_button)
        self.contact_profile_button.style().polish(self.contact_profile_button)

    def _save_chat_settings(self, values: dict) -> None:
        if not self.selected_contact:
            return
        chat_id = self.selected_contact
        try:
            self.service.update_chat_settings(chat_id, **values)
        except Exception as exc:
            self._error("Impostazioni chat", str(exc))
            return
        if self.selected_contact == chat_id:
            self._rendered_contact = ""
            self.refresh_messages("settings", chat_id)
        self._set_chat_settings_panel_visible(False)
        self.statusBar().showMessage(tr("Impostazioni della chat aggiornate"), 4000)

    def export_chat_debug(self, parent: QWidget, contact_id: str) -> None:
        if not contact_id:
            return
        if not KerberusMessageDialog.ask(
            parent,
            "Esportazione in chiaro",
            "Il file conterrà l’intera chat e i dati temporali in chiaro. Non condividerlo senza averlo controllato. Continuare?",
        ):
            return
        contact = next((item for item in self.service.contacts() if item.identity_id == contact_id), None)
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", contact.name if contact else "chat").strip("._") or "chat"
        default_name = f"kerberus-debug-{safe_name}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
        path, _ = QFileDialog.getSaveFileName(
            parent,
            tr("Esporta chat e diagnostica"),
            default_name,
            tr("Diagnostica JSON (*.json)"),
        )
        if not path:
            return
        try:
            Path(path).write_text(self.service.export_chat_debug(contact_id), encoding="utf-8")
        except Exception as exc:
            self._error("Esportazione chat", str(exc))
            return
        self._log_action("Chat e diagnostica esportate")
        self.statusBar().showMessage(tr("Chat e delay esportati in JSON"), 5000)

    def _setup_tray(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        tray = QSystemTrayIcon(lucide_icon("shield-check", COLORS["accent"], 32), self)
        tray.setToolTip(tr("Kerberus · I2P messenger"))
        menu = QMenu(self)
        show_action = menu.addAction(tr("Apri Kerberus"))
        show_action.triggered.connect(lambda: (self.showNormal(), self.raise_(), self.activateWindow()))
        if sys.platform.startswith("linux"):
            hide_action = menu.addAction(tr("Nascondi per lo streaming"))
            hide_action.setIcon(lucide_icon("eye-off"))
            hide_action.triggered.connect(lambda _checked=False: self._activate_linux_stream_shield())
            menu.addSeparator()
        quit_action = menu.addAction(tr("Esci"))

        quit_action.triggered.connect(self.exit_from_tray)
        tray.setContextMenu(menu)
        tray.activated.connect(
            lambda reason: show_action.trigger()
            if reason == QSystemTrayIcon.ActivationReason.Trigger else None
        )
        tray.show()
        self._tray = tray

    def forward_message(self, message: dict) -> None:
        contacts = self.service.contacts()
        if not contacts:
            return
        dialog = KerberusDialog("Inoltra messaggio", self, 500)
        layout = dialog.body_layout
        title = QLabel("Scegli la chat")
        title.setObjectName("dialogTitle")
        layout.addWidget(title)
        picker = QListWidget()
        for contact in contacts:
            item = QListWidgetItem(contact.name)
            item.setData(Qt.ItemDataRole.UserRole, contact.identity_id)
            picker.addItem(item)
        layout.addWidget(picker)
        actions = QHBoxLayout()
        cancel = QPushButton("Annulla")
        cancel.setObjectName("ghost")
        cancel.clicked.connect(dialog.reject)
        send = QPushButton("Inoltra")
        send.setObjectName("primary")
        send.clicked.connect(dialog.accept)
        actions.addStretch()
        actions.addWidget(cancel)
        actions.addWidget(send)
        layout.addLayout(actions)

        def submit() -> None:
            item = picker.currentItem()
            if item is None:
                return
            contact_id = str(item.data(Qt.ItemDataRole.UserRole))
            is_voice = message.get("kind") == "voice"
            is_attachment = message.get("kind") == "attachment"
            self._run_task(
                lambda: self.service.forward_voice(contact_id, message.get("voice"))
                if is_voice else self.service.forward_attachment_message(contact_id, str(message.get("message_id", "")))
                if is_attachment else self.service.forward_message(contact_id, str(message.get("text", ""))),
                lambda _value: self.statusBar().showMessage(tr("Messaggio inoltrato con nuova cifratura"), 4000),
                lambda error: self._error("Inoltro", error),
            )

        dialog.accepted.connect(submit)
        self._show_modeless(dialog)

    def show_message_timing(self, message: dict) -> None:
        dialog = KerberusDialog("Tempi del messaggio", self, 540)
        available_height = self.screen().availableGeometry().height()
        dialog.setFixedHeight(max(420, min(640, available_height - 48)))
        layout = dialog.body_layout
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(8)
        eyebrow = QLabel("DIAGNOSTICA DI CONSEGNA")
        eyebrow.setObjectName("eyebrow")
        title = QLabel("Invio e ricezione")
        title.setObjectName("dialogTitle")
        layout.addWidget(eyebrow)
        layout.addWidget(title)

        def format_time(value: object) -> str:
            if not isinstance(value, int):
                return tr("Non ancora disponibile")
            return datetime.fromtimestamp(value).strftime("%d/%m/%Y · %H:%M:%S")

        def format_delay(seconds: int) -> str:
            if seconds < 0:
                return tr("Non calcolabile: gli orologi dei dispositivi non sono sincronizzati")
            if seconds < 60:
                return tr_format("{seconds} secondi", seconds=seconds)
            minutes, remainder = divmod(seconds, 60)
            return tr_format("{minutes} min {seconds} s", minutes=minutes, seconds=remainder)

        def format_ms(value: object) -> str:
            if not isinstance(value, (int, float)):
                return tr("Non ancora disponibile")
            return f"{value:.3f} ms"

        sent_at = message.get("sent_at", message.get("time"))
        outgoing = message.get("direction") == "out"
        received_at = message.get("recipient_received_at") if outgoing else message.get("received_at")
        delivered_at = message.get("delivered_at")
        rows = [
            ("Inviato dal mittente", format_time(sent_at)),
            ("Ricevuto dal destinatario", format_time(received_at)),
        ]
        if isinstance(sent_at, int) and isinstance(received_at, int):
            rows.append(("Ritardo indicato", format_delay(received_at - sent_at)))
        else:
            rows.append(("Ritardo indicato", tr("In attesa della conferma")))
        if outgoing:
            rows.append(("ACK ricevuto sul mittente", format_time(delivered_at)))
            metrics = message.get("transport_metrics", {})
            if isinstance(metrics, dict) and metrics:
                rows.extend([
                    ("Python ↔ helper: overhead IPC", format_ms(metrics.get("python_helper_ipc_overhead_ms"))),
                    ("Python ↔ helper: richiesta completa", format_ms(metrics.get("python_helper_roundtrip_ms"))),
                    ("Attesa coda del contatto", format_ms(metrics.get("queue_wait_ms"))),
                    ("Handshake SAM locale", format_ms(metrics.get("sam_handshake_ms"))),
                    ("Comando STREAM CONNECT locale", format_ms(metrics.get("sam_connect_command_ms"))),
                ])
            rows.append(("Ricevuta cifrata andata/ritorno", format_ms(message.get("encrypted_receipt_rtt_ms"))))
            if isinstance(sent_at, int) and isinstance(delivered_at, int):
                rows.append(("Tempo totale andata/ritorno", format_delay(delivered_at - sent_at)))
        if message.get("kind") == "voice":
            voice = message.get("voice", {})
            metrics = message.get("voice_metrics", {})
            if isinstance(voice, dict):
                rows.append(("Durata vocale", f"{int(voice.get('duration_ms', 0)) / 1000:.1f} s"))
                rows.append(("Codec", str(voice.get("codec", ""))))
            if isinstance(metrics, dict):
                rows.append(("Codifica Go", format_ms(metrics.get("encode_ms"))))
                rows.append(("Decodifica Go", format_ms(metrics.get("decode_ms"))))

        scroll = QScrollArea()
        scroll.setObjectName("timingScroll")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        rows_host = QFrame()
        rows_host.setObjectName("timingRows")
        rows_layout = QVBoxLayout(rows_host)
        rows_layout.setContentsMargins(0, 0, 4, 0)
        rows_layout.setSpacing(6)
        for label, value in rows:
            row = QFrame()
            row.setObjectName("timingRow")
            row.setStyleSheet(
                f"QFrame#timingRow {{ background: {COLORS['surface']}; "
                f"border: 1px solid {COLORS['border']}; border-radius: 7px; }}"
            )
            row.setMinimumHeight(38)
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(11, 6, 11, 6)
            row_layout.setSpacing(12)
            key = QLabel(label.upper())
            key.setObjectName("eyebrow")
            key.setWordWrap(True)
            data = QLabel(value)
            data.setObjectName("timingValue")
            data.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            data.setWordWrap(True)
            data.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            row_layout.addWidget(key, 3)
            row_layout.addWidget(data, 2)
            rows_layout.addWidget(row)
        scroll.setWidget(rows_host)
        layout.addWidget(scroll, 1)

        note = QLabel(
            "L’orario di invio è autenticato nel messaggio cifrato. Il ritardo a senso unico dipende anche dalla "
            "sincronizzazione degli orologi; il tempo andata/ritorno usa invece l’orologio del mittente."
        )
        note.setObjectName("muted")
        note.setWordWrap(True)
        layout.addWidget(note)
        actions = QHBoxLayout()
        actions.addStretch()
        close = QPushButton("Chiudi")
        close.setObjectName("primary")
        close.clicked.connect(dialog.accept)
        actions.addWidget(close)
        layout.addLayout(actions)
        self._show_modeless(dialog)

    def send_message(self) -> None:
        text = self.composer.toPlainText().strip()
        if not text or not self.selected_contact:
            return
        self._log_action("Invio messaggio richiesto")
        self.composer.clear()
        contact_id = self.selected_contact
        self._run_task(
            lambda: self.service.send_message(contact_id, text),
            self._message_send_result,
            lambda error: self._error("Invio", error),
        )

    def choose_attachment(self) -> None:
        if not self.selected_contact:
            return
        path, _ = QFileDialog.getOpenFileName(self, tr("Invia file"), "", tr("Tutti i file (*.*)"))
        if not path:
            return
        source = Path(path)
        try:
            if source.stat().st_size <= 0:
                raise ValueError(tr("Il file è vuoto"))
        except OSError as exc:
            self._error(tr("Invia file"), str(exc))
            return
        except ValueError as exc:
            self._error(tr("Invia file"), str(exc))
            return
        contact_id = self.selected_contact
        self.statusBar().showMessage(tr("Cifratura e invio dell’allegato…"), 5000)
        self._run_task(
            lambda: self.service.send_attachment_file(contact_id, source),
            self._attachment_send_result,
            lambda error: self._error(tr("Invia file"), error),
        )

    def _attachment_send_result(self, value: object) -> None:
        self._message_send_result(value)
        if value != "queued":
            self.statusBar().showMessage(tr("Allegato inviato"), 4000)

    def save_attachment(self, message: dict) -> None:
        attachment = message.get("attachment")
        if not isinstance(attachment, dict):
            return
        name = str(attachment.get("name", "allegato"))
        self.service.config.downloads_path.mkdir(parents=True, exist_ok=True)
        suggested = self.service.config.downloads_path / name
        path, _ = QFileDialog.getSaveFileName(self, tr("Salva allegato"), str(suggested), tr("Tutti i file (*.*)"))
        if not path:
            return
        message_id = str(message.get("message_id", ""))

        def save() -> Path:
            destination = Path(path)
            return self.service.save_attachment_to(message_id, destination)

        self._run_task(
            save,
            lambda destination: self.statusBar().showMessage(
                tr_format("Allegato salvato: {path}", path=destination), 5000,
            ),
            lambda error: self._error(tr("Salva allegato"), error),
        )

    def _prepare_inline_video(self, message_id: str) -> tuple[str, Path]:
        metadata = self.service.attachment_metadata(message_id)
        extension = Path(str(metadata.get("name", ""))).suffix.lower()
        if not re.fullmatch(r"\.[a-z0-9]{1,8}", extension):
            extension = {
                "video/mp4": ".mp4", "video/webm": ".webm", "video/quicktime": ".mov",
            }.get(str(metadata.get("mime", "")), ".video")
        destination = Path(self._attachment_temp_dir.name) / f"{message_id}{extension}"
        if not destination.exists():
            self.service.save_attachment_to(message_id, destination)
        return message_id, destination

    def _play_inline_video_ready(self, value: object) -> None:
        if not isinstance(value, tuple) or len(value) != 2:
            return
        message_id, path = value
        if hasattr(self, "message_view"):
            self.message_view.play_inline_video(str(message_id), Path(path))

    def toggle_voice_recording(self) -> None:
        if self._voice_recorder.active:
            self._voice_recorder.stop()
            return
        if not self.selected_contact:
            return
        if not self._voice_privacy_acknowledged:
            accepted = KerberusMessageDialog.ask(
                self,
                tr("Privacy dei messaggi vocali"),
                tr(
                    "Il contenuto sarà cifrato end-to-end e trasportato soltanto tramite I2P. "
                    "Durata, dimensione e tempistica del traffico possono comunque essere osservabili e correlate. "
                    "Il microfono resta attivo soltanto durante la registrazione visibile. Continuare?"
                ),
            )
            if not accepted:
                return
            self._voice_privacy_acknowledged = True
        self._voice_record_contact = self.selected_contact
        self._voice_record_mode = "message"
        self._voice_recorder.start(self._selected_audio_input())
        if not self._voice_recorder.active:
            return
        self._voice_record_started = time.monotonic()
        self._set_voice_recording_ui(True)
        self._voice_timer.start()
        self._update_voice_recording()

    def cancel_voice_recording(self) -> None:
        self._voice_recorder.stop(discard=True)
        self._voice_timer.stop()
        self._voice_record_contact = ""
        self._set_voice_recording_ui(False)
        self.statusBar().showMessage(tr("Registrazione vocale annullata"), 2500)

    def _set_voice_recording_ui(self, active: bool) -> None:
        self.composer.setVisible(not active)
        self.attachment_button.setVisible(not active)
        self.emoji_button.setVisible(not active)
        self.send_button.setVisible(not active)
        self.voice_recording_label.setVisible(active)
        self.voice_cancel_button.setVisible(active)
        self.voice_button.setIcon(lucide_icon(
            "send" if active else "mic",
            COLORS["accent"] if active else COLORS["danger"],
        ))
        self.voice_button.setToolTip("Termina e invia" if active else "Registra messaggio vocale cifrato")

    def _update_voice_recording(self) -> None:
        if not self._voice_recorder.active:
            self._voice_timer.stop()
            return
        precise_elapsed = time.monotonic() - self._voice_record_started
        elapsed = min(120, int(precise_elapsed))
        self.voice_recording_label.setText(tr_format(
            "Registrazione {minutes}:{seconds:02d} · massimo 2:00",
            minutes=elapsed // 60,
            seconds=elapsed % 60,
        ))
        if precise_elapsed >= 119.5:
            self._voice_recorder.stop()

    def _voice_recording_failed(self, message: str) -> None:
        if self._voice_record_mode == "audio_test":
            self._finish_audio_test(tr(message), success=False)
            self._voice_record_mode = "message"
            return
        self._voice_timer.stop()
        self._set_voice_recording_ui(False)
        self._voice_record_contact = ""
        self._error(tr("Messaggio vocale"), tr(message))

    def _voice_recorded(
        self,
        pcm: bytes,
        sample_rate: int,
        channels: int,
        sample_format: str,
        _duration_ms: int,
    ) -> None:
        if self._voice_record_mode == "audio_test":
            output_device_id = self._audio_test_output_device_id
            self._voice_record_mode = "message"
            self._set_audio_test_status(tr("Elaborazione con il codec Go…"))

            def test_ready(value: object) -> None:
                self._play_voice_wav(value, output_device_id)
                self._finish_audio_test(
                    tr("Test completato: dovresti sentire la registrazione sul dispositivo di uscita scelto."),
                    success=True,
                )

            self._run_task(
                lambda: self.service.test_voice_roundtrip(
                    pcm,
                    sample_rate=sample_rate,
                    channels=channels,
                    sample_format=sample_format,
                ),
                test_ready,
                lambda error: self._finish_audio_test(error, success=False),
            )
            return
        contact_id = self._voice_record_contact
        self._voice_timer.stop()
        self._voice_record_contact = ""
        self._set_voice_recording_ui(False)
        if not contact_id:
            return
        self.statusBar().showMessage(tr("Compressione vocale nel helper Go e cifratura…"), 5000)
        self._run_task(
            lambda: self.service.send_voice(
                contact_id,
                pcm,
                sample_rate=sample_rate,
                channels=channels,
                sample_format=sample_format,
            ),
            self._message_send_result,
            lambda error: self._error("Invio vocale", error),
        )

    def _selected_audio_input(self, device_id: str | None = None) -> object:
        stored_id = (
            str(self.service.settings().get("audio_input_device_id", ""))
            if device_id is None else device_id
        )
        return resolve_audio_device(
            available_audio_inputs(), stored_id, QMediaDevices.defaultAudioInput()
        )

    def _create_audio_output(self, device_id: str | None = None) -> QAudioOutput:
        stored_id = (
            str(self.service.settings().get("audio_output_device_id", ""))
            if device_id is None else device_id
        )
        device = resolve_audio_device(
            available_audio_outputs(), stored_id, QMediaDevices.defaultAudioOutput()
        )
        if not device.isNull():
            return QAudioOutput(device, self)
        return QAudioOutput(self)

    def _set_audio_test_status(self, message: str) -> None:
        if self._audio_test_status is not None and not sip.isdeleted(self._audio_test_status):
            self._audio_test_status.setText(message)

    def _finish_audio_test(self, message: str, *, success: bool) -> None:
        self._set_audio_test_status(message)
        if self._audio_test_button is not None and not sip.isdeleted(self._audio_test_button):
            self._audio_test_button.setEnabled(True)
        if not success:
            self.statusBar().showMessage(message, 5000)
        self._audio_test_button = None
        self._audio_test_status = None
        self._audio_test_output_device_id = ""

    def _start_microphone_test(
        self,
        input_device_id: str,
        output_device_id: str,
        status: QLabel,
        button: QPushButton,
    ) -> None:
        if self._voice_recorder.active:
            status.setText(tr("È già in corso una registrazione."))
            return
        self._voice_record_mode = "audio_test"
        self._audio_test_output_device_id = output_device_id
        self._audio_test_status = status
        self._audio_test_button = button
        button.setEnabled(False)
        status.setText(tr("Registrazione di prova in corso per 3 secondi…"))
        self._voice_recorder.start(self._selected_audio_input(input_device_id))
        if self._voice_recorder.active:
            QTimer.singleShot(
                3_000,
                lambda: self._voice_recorder.stop()
                if self._voice_record_mode == "audio_test" and self._voice_recorder.active else None,
            )

    def _play_voice_wav(self, wav_data: object, output_device_id: str | None = None) -> None:
        if not isinstance(wav_data, bytes):
            self._error("Messaggio vocale", "Audio decodificato non valido")
            return
        if self._voice_player is not None:
            self._voice_player.stop()
            self._voice_player.deleteLater()
        if self._voice_buffer is not None:
            self._voice_buffer.close()
            self._voice_buffer.deleteLater()
        if self._voice_audio_output is not None:
            self._voice_audio_output.deleteLater()
        self._voice_audio_output = self._create_audio_output(output_device_id)
        self._voice_player = QMediaPlayer(self)
        self._voice_player.setAudioOutput(self._voice_audio_output)
        self._voice_buffer = QBuffer(self)
        self._voice_buffer.setData(QByteArray(wav_data))
        self._voice_buffer.open(QIODevice.OpenModeFlag.ReadOnly)
        self._voice_player.setSourceDevice(self._voice_buffer, QUrl("voice-message.wav"))
        self._voice_player.play()
        self.statusBar().showMessage(tr("Riproduzione messaggio vocale cifrato"), 3500)

    def _message_send_result(self, value: object) -> None:
        self.refresh_messages("status", self.selected_contact)
        if value == "queued":
            self.statusBar().showMessage(
                "Destinatario temporaneamente non raggiungibile: messaggio cifrato in coda con retry automatico",
                8000,
            )

    def add_contact(self) -> None:
        self._log_action("Apertura Nuovo contatto")
        dialog = ContactDialog(self)

        def submit() -> None:
            if not dialog.code.text().strip():
                return
            code = dialog.code.text()
            first_message = dialog.first_message.toPlainText()
            self._run_task(
                lambda: self.service.request_contact(code, first_message),
                self._contact_request_result,
                lambda error: self._error("Nuovo contatto", error),
            )

        dialog.accepted.connect(submit)
        self._show_modeless(dialog)

    def _contact_request_result(self, value: object) -> None:
        self.refresh_contacts()
        message = "Richiesta affidata a I2P: la chat si aprirà dopo la conferma firmata"
        if value == "queued":
            message = "Contatto non ancora raggiungibile: richiesta salvata e ritentata automaticamente"
        self.statusBar().showMessage(tr(message), 8000)

    def _protocol_event(self, kind: str, detail: str) -> None:
        self._log_action(f"Evento protocollo: {kind} · {detail}")
        if kind in {
            "contact_request_received", "contact_accept_inline", "contact_accept_received",
            "contact_request_cancelled",
        }:
            self.refresh_contacts()
        if kind == "contact_reject_received":
            KerberusMessageDialog.show_message(self, "Richiesta contatto rifiutata", detail)
            return
        self.statusBar().showMessage(tr_runtime(detail), 8000)

    def _log_action(self, action: str) -> None:
        safe = tr_runtime(action).replace("\r", " ").replace("\n", " ")[:180]
        self._ui_events.append(f"{datetime.now().strftime('%H:%M:%S')}  {safe}")
        self._ui_events = self._ui_events[-1000:]

    def _show_modeless(self, dialog: QDialog) -> None:
        title = dialog.windowTitle()
        existing = self._modeless_by_title.get(title)
        if existing is not None:
            try:
                existing.show()
                existing.raise_()
                existing.activateWindow()
                dialog.deleteLater()
                return
            except RuntimeError:
                self._modeless_by_title.pop(title, None)
        dialog.setModal(False)
        dialog.setWindowModality(Qt.WindowModality.NonModal)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self._open_dialogs.add(dialog)
        self._modeless_by_title[title] = dialog

        def released() -> None:
            self._open_dialogs.discard(dialog)
            if self._modeless_by_title.get(title) is dialog:
                self._modeless_by_title.pop(title, None)

        dialog.finished.connect(lambda _result: released())
        dialog.destroyed.connect(released)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def show_ui_console(self) -> None:
        self._log_action("Apertura Console UI")
        dialog = KerberusDialog("Console UI", self, 760)
        dialog.setMinimumHeight(500)
        layout = dialog.body_layout
        eyebrow = QLabel("EVENTI LOCALI · NESSUN CONTENUTO DEI MESSAGGI")
        eyebrow.setObjectName("eyebrow")
        layout.addWidget(eyebrow)
        title = QLabel("Attività dell’app")
        title.setObjectName("dialogTitle")
        layout.addWidget(title)
        console = QPlainTextEdit()
        console.setReadOnly(True)
        console.setStyleSheet("font-family: Consolas; font-size: 12px;")
        console.setPlainText("\n".join(self._ui_events))
        layout.addWidget(console, 1)
        buttons = QHBoxLayout()
        clear = QPushButton("Pulisci")
        clear.clicked.connect(lambda: (self._ui_events.clear(), console.clear()))
        close = QPushButton("Chiudi")
        close.setObjectName("primary")
        close.clicked.connect(dialog.accept)
        buttons.addWidget(clear)
        buttons.addStretch()
        buttons.addWidget(close)
        layout.addLayout(buttons)
        self._show_modeless(dialog)

    def show_settings(self) -> None:
        self._log_action("Apertura Impostazioni")
        current = self.service.settings()
        dialog = KerberusDialog("Impostazioni", self, 900)
        dialog.resize(900, 680)
        dialog.body_layout.setContentsMargins(20, 18, 20, 18)
        dialog.body_layout.setSpacing(14)

        heading_row = QHBoxLayout()
        heading_text = QVBoxLayout()
        heading_text.setSpacing(2)
        title = QLabel("Impostazioni")
        title.setObjectName("dialogTitle")
        subtitle = QLabel("Personalizza Kerberus, la privacy e il comportamento della rete")
        subtitle.setObjectName("muted")
        heading_text.addWidget(title)
        heading_text.addWidget(subtitle)
        heading_row.addLayout(heading_text)
        heading_row.addStretch()
        version = QLabel(f"Kerberus {__version__}")
        version.setObjectName("muted")
        heading_row.addWidget(version, alignment=Qt.AlignmentFlag.AlignBottom)
        dialog.body_layout.addLayout(heading_row)

        main = QHBoxLayout()
        main.setSpacing(14)
        navigation = QFrame()
        navigation.setObjectName("settingsSidebar")
        navigation.setFixedWidth(205)
        navigation_layout = QVBoxLayout(navigation)
        navigation_layout.setContentsMargins(8, 10, 8, 10)
        navigation_layout.setSpacing(4)
        pages = QStackedWidget()
        pages.setMinimumHeight(500)
        nav_group = QButtonGroup(dialog)
        nav_group.setExclusive(True)

        def add_page() -> tuple[QScrollArea, QVBoxLayout]:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setMinimumWidth(0)
            scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            scroll.viewport().setStyleSheet("background: transparent;")
            host = QWidget()
            host.setStyleSheet("background: transparent;")
            host.setMinimumWidth(0)
            host.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            page_layout = QVBoxLayout(host)
            page_layout.setContentsMargins(2, 2, 8, 2)
            page_layout.setSpacing(12)
            page_layout.addStretch()
            scroll.setWidget(host)
            pages.addWidget(scroll)
            return scroll, page_layout

        def add_card(page_layout: QVBoxLayout, card: SettingsCard) -> SettingsCard:
            page_layout.insertWidget(page_layout.count() - 1, card)
            return card

        nav_specs = (
            ("settings-2", "Generali"),
            ("image-plus", "Aspetto"),
            ("shield-check", "Privacy"),
            ("network", "Rete"),
            ("lock-keyhole", "Sicurezza"),
            ("terminal", "Diagnostica"),
        )
        for index, (icon_name, label) in enumerate(nav_specs):
            button = QPushButton(label)
            button.setObjectName("settingsNav")
            button.setCheckable(True)
            button.setIcon(lucide_icon(icon_name))
            button.setIconSize(QSize(18, 18))
            button.clicked.connect(lambda _checked=False, selected=index: pages.setCurrentIndex(selected))
            nav_group.addButton(button, index)
            navigation_layout.addWidget(button)
        navigation_layout.addStretch()
        nav_group.button(0).setChecked(True)
        main.addWidget(navigation)
        main.addWidget(pages, 1)
        dialog.body_layout.addLayout(main, 1)

        # Generali
        _general, general_layout = add_page()
        language_card = add_card(
            general_layout,
            SettingsCard("settings-2", "Aspetto e lingua", "Scegli la lingua usata in tutta l’applicazione."),
        )
        language_row = QFrame()
        language_row.setObjectName("settingsRow")
        language_layout = QHBoxLayout(language_row)
        language_layout.setContentsMargins(16, 13, 16, 13)
        language_text = QVBoxLayout()
        language_text.setSpacing(3)
        language_text.addWidget(QLabel("Lingua dell’applicazione"))
        language_hint = QLabel("La modifica viene applicata subito a tutta l’interfaccia.")
        language_hint.setObjectName("muted")
        language_hint.setWordWrap(True)
        language_hint.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        language_text.addWidget(language_hint)
        language = ModernComboBox()
        language.addItem("Italiano", "it")
        language.addItem("Inglese", "en")
        language.setCurrentIndex(0 if current.get("language", "it") == "it" else 1)
        language.setFixedWidth(190)
        language_layout.addLayout(language_text, 1)
        language_layout.addWidget(language)
        language_card.add_row(language_row)

        audio_card = add_card(
            general_layout,
            SettingsCard(
                "mic", "Audio e messaggi vocali",
                "Scegli il microfono e le cuffie usati da Kerberus e verifica il percorso audio completo.",
            ),
        )

        def audio_device_row(
            title_text: str,
            hint_text: str,
            devices: list[object],
            selected_id: str,
            object_name: str,
        ) -> tuple[QFrame, ModernComboBox]:
            row = QFrame()
            row.setObjectName("settingsRow")
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(16, 13, 16, 13)
            row_text = QVBoxLayout()
            row_text.setSpacing(3)
            row_text.addWidget(QLabel(title_text))
            hint = QLabel(hint_text)
            hint.setObjectName("muted")
            hint.setWordWrap(True)
            hint.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            row_text.addWidget(hint)
            combo = ModernComboBox()
            combo.setObjectName(object_name)
            combo.addItem("Predefinito di sistema", "")
            for device in devices:
                device_key = audio_device_id(device)
                combo.addItem(device.description(), device_key)
                if device_key and device_key == selected_id:
                    combo.setCurrentIndex(combo.count() - 1)
            combo.setMinimumWidth(250)
            combo.setMaximumWidth(330)
            row_layout.addLayout(row_text, 1)
            row_layout.addWidget(combo)
            return row, combo

        input_row, audio_input = audio_device_row(
            "Microfono",
            "Dispositivo usato per registrare i messaggi vocali.",
            available_audio_inputs(),
            str(current.get("audio_input_device_id", "")),
            "audioInputDevice",
        )
        output_row, audio_output = audio_device_row(
            "Cuffie o altoparlanti",
            "Dispositivo sul quale vengono riprodotti messaggi vocali e test.",
            available_audio_outputs(),
            str(current.get("audio_output_device_id", "")),
            "audioOutputDevice",
        )
        audio_card.add_row(input_row)
        audio_card.add_row(output_row)

        audio_test_row = QFrame()
        audio_test_row.setObjectName("settingsRow")
        audio_test_layout = QVBoxLayout(audio_test_row)
        audio_test_layout.setContentsMargins(16, 13, 16, 15)
        audio_test_layout.setSpacing(9)
        test_buttons = QHBoxLayout()
        output_test = QPushButton("Prova uscita")
        output_test.setObjectName("audioOutputTest")
        output_test.setIcon(lucide_icon("send"))
        microphone_test = QPushButton("Prova microfono (3 s)")
        microphone_test.setObjectName("audioInputTest")
        microphone_test.setIcon(lucide_icon("mic"))
        test_buttons.addWidget(output_test)
        test_buttons.addWidget(microphone_test)
        test_buttons.addStretch()
        audio_test_layout.addLayout(test_buttons)
        audio_test_status = QLabel(
            "Il test microfono registra, comprime e decodifica con il helper Go, poi riproduce sulle cuffie scelte."
        )
        audio_test_status.setObjectName("muted")
        audio_test_status.setWordWrap(True)
        audio_test_layout.addWidget(audio_test_status)
        audio_card.add_row(audio_test_row)

        def play_output_test() -> None:
            self._play_voice_wav(test_tone_wav(), str(audio_output.currentData()))
            audio_test_status.setText(tr("Tono inviato al dispositivo di uscita scelto."))

        output_test.clicked.connect(play_output_test)
        microphone_test.clicked.connect(
            lambda: self._start_microphone_test(
                str(audio_input.currentData()),
                str(audio_output.currentData()),
                audio_test_status,
                microphone_test,
            )
        )

        # Aspetto
        _appearance, appearance_layout = add_page()
        appearance_card = add_card(
            appearance_layout,
            SettingsCard(
                "image-plus", "Tema e interfaccia",
                "Personalizza colori, leggibilità e spaziatura dei controlli.",
            ),
        )

        def appearance_combo_row(
            title_text: str,
            hint_text: str,
            object_name: str,
        ) -> tuple[QFrame, ModernComboBox]:
            row = QFrame()
            row.setObjectName("settingsRow")
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(16, 13, 16, 13)
            copy = QVBoxLayout()
            copy.setSpacing(3)
            copy.addWidget(QLabel(title_text))
            hint = QLabel(hint_text)
            hint.setObjectName("muted")
            hint.setWordWrap(True)
            hint.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            copy.addWidget(hint)
            combo = ModernComboBox()
            combo.setObjectName(object_name)
            combo.setFixedWidth(190)
            row_layout.addLayout(copy, 1)
            row_layout.addWidget(combo)
            return row, combo

        theme_row, theme = appearance_combo_row(
            "Tema dell’applicazione",
            "Cambia la palette di tutta l’interfaccia senza riavviare Kerberus.",
            "applicationTheme",
        )
        for key, label in (
            ("default", "Predefinito"), ("pink", "Rosa"), ("orange", "Arancione"),
            ("white", "Bianco"), ("dark", "Scuro"),
        ):
            theme.addItem(label, key)
            if key == current.get("theme", "default"):
                theme.setCurrentIndex(theme.count() - 1)
        appearance_card.add_row(theme_row)

        palette_row = QFrame()
        palette_row.setObjectName("settingsRow")
        palette_layout = QHBoxLayout(palette_row)
        palette_layout.setContentsMargins(16, 12, 16, 14)
        palette_layout.addWidget(QLabel("Anteprima palette"))
        palette_layout.addStretch()
        for key in ("default", "pink", "orange", "white", "dark"):
            swatch = QFrame()
            swatch.setObjectName(f"themeSwatch-{key}")
            swatch.setFixedSize(34, 24)
            palette = THEMES[key]
            swatch.setToolTip(key.title())
            fill = "#ffffff" if key == "white" else palette["accent"]
            border = palette["border"] if key == "white" else palette["surface_2"]
            swatch.setStyleSheet(
                f"background: {fill}; border: 5px solid {border}; "
                f"border-radius: 7px;"
            )
            palette_layout.addWidget(swatch)
        appearance_card.add_row(palette_row)

        text_row, text_scale = appearance_combo_row(
            "Dimensione del testo",
            "Aumenta o riduci il testo mantenendo invariato il contenuto.",
            "textScale",
        )
        for scale in (90, 100, 110, 120):
            text_scale.addItem(f"{scale}%", scale)
            if scale == int(current.get("text_scale", 100)):
                text_scale.setCurrentIndex(text_scale.count() - 1)
        appearance_card.add_row(text_row)

        density_row, ui_density = appearance_combo_row(
            "Densità dell’interfaccia",
            "Regola lo spazio verticale di pulsanti, menu e campi.",
            "uiDensity",
        )
        for key, label in (
            ("compact", "Compatta"), ("comfortable", "Bilanciata"), ("spacious", "Spaziosa"),
        ):
            ui_density.addItem(label, key)
            if key == current.get("ui_density", "comfortable"):
                ui_density.setCurrentIndex(ui_density.count() - 1)
        appearance_card.add_row(density_row)

        appearance_note = QLabel(
            "Le modifiche di aspetto vengono applicate immediatamente e salvate nel vault locale."
        )
        appearance_note.setObjectName("muted")
        appearance_note.setWordWrap(True)
        appearance_note.setContentsMargins(16, 13, 16, 15)
        appearance_card.add_row(appearance_note)

        original_appearance = (
            str(current.get("theme", "default")),
            int(current.get("text_scale", 100)),
            str(current.get("ui_density", "comfortable")),
        )

        def preview_appearance() -> None:
            apply_appearance(
                str(theme.currentData()), int(text_scale.currentData()), str(ui_density.currentData())
            )

        theme.currentIndexChanged.connect(preview_appearance)
        text_scale.currentIndexChanged.connect(preview_appearance)
        ui_density.currentIndexChanged.connect(preview_appearance)
        dialog.rejected.connect(lambda: apply_appearance(*original_appearance))

        # Privacy
        _privacy, privacy_layout = add_page()
        receipts_card = add_card(
            privacy_layout,
            SettingsCard("shield-check", "Ricevute dei messaggi", "Controlla quali conferme cifrate inviare ai contatti."),
        )
        delivery_receipts = SettingsToggleRow(
            "Conferme di consegna",
            "Comunica al mittente che il messaggio cifrato è arrivato al dispositivo.",
            bool(current["send_delivery_receipts"]),
        )
        read_receipts = SettingsToggleRow(
            "Conferme di lettura",
            "Mostra le spunte blu dopo l’apertura della conversazione.",
            bool(current["send_read_receipts"]),
        )
        receipts_card.add_row(delivery_receipts)
        receipts_card.add_row(read_receipts)

        invite_card = add_card(
            privacy_layout,
            SettingsCard("user-plus", "Inviti e codice contatto", "Riduci il rischio di riutilizzo involontario dei codici condivisi."),
        )
        interval_row = QFrame()
        interval_row.setObjectName("settingsRow")
        interval_layout = QHBoxLayout(interval_row)
        interval_layout.setContentsMargins(16, 13, 16, 13)
        interval_text = QVBoxLayout()
        interval_text.setSpacing(3)
        interval_text.addWidget(QLabel("Durata del codice"))
        interval_hint = QLabel("Il token cambia; la destination I2P firmata rimane invariata.")
        interval_hint.setObjectName("muted")
        interval_hint.setWordWrap(True)
        interval_hint.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        interval_text.addWidget(interval_hint)
        interval = ModernComboBox()
        for minutes, label in ((1, "Ogni minuto"), (5, "Ogni 5 minuti"), (15, "Ogni 15 minuti"), (60, "Ogni ora")):
            interval.addItem(label, minutes)
            if minutes == current["contact_code_period_minutes"]:
                interval.setCurrentIndex(interval.count() - 1)
        interval.setFixedWidth(190)
        interval_layout.addLayout(interval_text, 1)
        interval_layout.addWidget(interval)
        invite_card.add_row(interval_row)
        single_use = SettingsToggleRow(
            "Codice monouso",
            "Ruota immediatamente il token dopo il primo utilizzo valido.",
            bool(current["contact_code_single_use"]),
        )
        invite_card.add_row(single_use)

        # Rete
        _network, network_layout = add_page()
        external_card = add_card(
            network_layout,
            SettingsCard("network", "Contenuti esterni", "Decidi quando Kerberus può usare la rete clearnet oltre a I2P."),
        )
        link_previews = SettingsToggleRow(
            "Anteprime dei link",
            "Recupera titolo e immagine. Host locali e indirizzi privati restano bloccati.",
            bool(current["link_previews"]),
        )
        clearnet = SettingsToggleRow(
            "Funzioni clearnet",
            "Consente azioni esplicite come il controllo e il download degli aggiornamenti.",
            bool(current["clearnet_enabled"]),
        )
        external_card.add_row(link_previews)
        external_card.add_row(clearnet)
        transport_card = add_card(
            network_layout,
            SettingsCard("lock-keyhole", "Trasporto privato", "I messaggi continuano a viaggiare nel canale I2P cifrato end-to-end."),
        )
        transport_info = QLabel("I2P streaming · X25519 + ML-KEM-768 · XChaCha20-Poly1305")
        transport_info.setObjectName("muted")
        transport_info.setWordWrap(True)
        transport_info.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        transport_info.setContentsMargins(16, 14, 16, 16)
        transport_card.add_row(transport_info)

        performance_card = add_card(
            network_layout,
            SettingsCard(
                "clock", "Prestazioni I2P",
                "Riduci la latenza senza limitare i peer scelti automaticamente dal router.",
            ),
        )
        low_latency = SettingsToggleRow(
            "Modalità bassa latenza",
            "Usa tunnel da 2 hop e ACK iniziali immediati. Riduce l’anonimato rispetto ai 3 hop consigliati.",
            bool(current.get("low_latency_mode", False)),
        )
        low_latency.setObjectName("lowLatencySetting")
        warm_recent = SettingsToggleRow(
            "Mantieni pronti i contatti recenti",
            "Compromesso privacy/prestazioni: apre in anticipo fino a 8 stream recenti e velocizza il primo "
            "messaggio, ma genera traffico e metadati di connessione in background. Per la massima privacy disattivalo.",
            bool(current.get("warm_recent_contacts", True)),
        )
        mask_recent = SettingsToggleRow(
            "Maschera quali contatti sono recenti",
            "Non falsifica I2P: seleziona casualmente fino a 8 contatti reali invece della cronologia recente. "
            "Riduce la correlazione con le chat recenti, ma il router SAM vede comunque le destination e anche "
            "un contatto non recente può osservare la connessione.",
            bool(current.get("mask_recent_contact_metadata", False)),
        )
        mask_recent.setEnabled(warm_recent.isChecked())
        warm_recent.switch.toggled.connect(mask_recent.setEnabled)
        performance_card.add_row(low_latency)
        confirmation = InlineConfirmationPanel()
        performance_card.add_row(confirmation)
        performance_card.add_row(warm_recent)
        performance_card.add_row(mask_recent)
        active_optimizations = QLabel(
            "Ottimizzazioni sempre attive: profilo interattivo, fast receive, primo frame nel SYN, "
            "stream persistenti e risposte full-duplex."
        )
        active_optimizations.setObjectName("muted")
        active_optimizations.setWordWrap(True)
        active_optimizations.setContentsMargins(16, 13, 16, 15)
        performance_card.add_row(active_optimizations)

        def set_low_latency_checked(checked: bool) -> None:
            low_latency.switch.blockSignals(True)
            low_latency.switch.setChecked(checked)
            low_latency.switch.blockSignals(False)
            confirmation.hide()

        def request_low_latency(enabled: bool) -> None:
            if not enabled:
                confirmation.hide()
                return
            low_latency.switch.blockSignals(True)
            low_latency.switch.setChecked(False)
            low_latency.switch.blockSignals(False)
            confirmation.show()
            confirmation.setFocus(Qt.FocusReason.OtherFocusReason)

        low_latency.switch.toggled.connect(request_low_latency)
        confirmation.confirmed.connect(lambda: set_low_latency_checked(True))
        confirmation.cancelled.connect(lambda: set_low_latency_checked(False))

        peer_card = add_card(
            network_layout,
            SettingsCard(
                "network", "Paesi e peer I2P",
                "Osserva gli endpoint pubblici collegati al router locale e visualizza automaticamente paese e rete.",
            ),
        )
        network_insights = NetworkInsightsPanel()
        peer_card.add_row(network_insights)
        network_context = {"active": True}

        def stop_network_insights(*_args: object) -> None:
            # Results can arrive after the modeless settings dialog was closed.
            # Do not touch widgets while Qt is deleting their native objects.
            network_context["active"] = False

        dialog.finished.connect(stop_network_insights)
        dialog.destroyed.connect(stop_network_insights)

        def refresh_network_insights() -> None:
            if not network_context["active"] or sip.isdeleted(network_insights):
                return
            network_insights.set_loading(True)

            def loaded(value: object) -> None:
                if not network_context["active"] or sip.isdeleted(network_insights):
                    return
                network_insights.set_loading(False)
                peers = value if isinstance(value, list) else []
                network_insights.set_peers(peers)
                for peer in peers:
                    ip = str(peer.get("ip", ""))
                    if ip:
                        lookup_peer(ip)

            def failed(error: str) -> None:
                if not network_context["active"] or sip.isdeleted(network_insights):
                    return
                network_insights.set_loading(False)
                network_insights.status.setText(tr_format("Analisi rete non disponibile: {detail}", detail=tr(error)))

            self._run_task(collect_i2p_peer_connections, loaded, failed)

        def lookup_peer(ip: str) -> None:
            if not network_context["active"] or sip.isdeleted(network_insights):
                return
            cached = self._ip_lookup_cache.get(ip)
            if cached is not None:
                network_insights.set_lookup_result(ip, cached)
                return
            if ip in self._ip_lookup_pending:
                return
            self._ip_lookup_pending.add(ip)
            label = network_insights._detail_labels.get(ip)
            if label is not None:
                label.setText(tr("Richiesta informazioni IP in corso…"))
            def lookup_loaded(value: object) -> None:
                self._ip_lookup_pending.discard(ip)
                result = value if isinstance(value, dict) else {}
                self._ip_lookup_cache[ip] = result
                if network_context["active"] and not sip.isdeleted(network_insights):
                    network_insights.set_lookup_result(ip, result)

            def lookup_failed(error: str) -> None:
                self._ip_lookup_pending.discard(ip)
                if network_context["active"] and not sip.isdeleted(network_insights):
                    network_insights.set_lookup_error(ip, error)

            self._run_network_task(
                lambda: lookup_ip_geolocation(ip),
                lookup_loaded,
                lookup_failed,
            )

        network_insights.refresh_requested.connect(refresh_network_insights)
        network_insights.lookup_requested.connect(lookup_peer)
        network_insights.auto_refresh = QTimer(network_insights)
        network_insights.auto_refresh.setInterval(30_000)
        network_insights.auto_refresh.timeout.connect(refresh_network_insights)
        network_insights.auto_refresh.start()
        QTimer.singleShot(0, refresh_network_insights)

        # Sicurezza
        _security, security_layout = add_page()
        capture_card = add_card(
            security_layout,
            SettingsCard("camera", "Protezione streaming", "Mantieni la finestra fuori dalle catture schermo supportate."),
        )
        stream_proof = SettingsToggleRow(
            "Nascondi Kerberus durante streaming e condivisione schermo",
            "Su Windows usa l’esclusione nativa; su Linux abilita una privacy curtain che nasconde l’app nell’area di notifica.",
            bool(current.get("stream_proof_enabled", False)),
        )
        stream_proof.setEnabled(sys.platform == "win32" or sys.platform.startswith("linux"))
        capture_card.add_row(stream_proof)
        availability = QLabel(
            "Disponibile su Windows 10 versione 2004 o successiva. Non protegge da fotocamere, software con privilegi superiori o metodi di cattura non supportati."
            if sys.platform == "win32" else
            (
                "Linux non offre un’esclusione universale mentre la finestra resta visibile: la modalità privacy la nasconde completamente e permette di riaprirla dall’area di notifica."
                if sys.platform.startswith("linux") else
                "Non disponibile su questo sistema: non esiste un’esclusione universale dalle catture schermo."
            )
        )
        availability.setObjectName("muted")
        availability.setWordWrap(True)
        availability.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        availability.setContentsMargins(16, 13, 16, 15)
        capture_card.add_row(availability)
        if sys.platform.startswith("linux"):
            linux_row = QFrame()
            linux_row.setObjectName("settingsRow")
            linux_layout = QHBoxLayout(linux_row)
            linux_layout.setContentsMargins(16, 12, 16, 14)
            hide_now = QPushButton("Nascondi Kerberus ora")
            hide_now.setIcon(lucide_icon("eye-off"))
            hide_now.clicked.connect(
                lambda _checked=False: self._activate_linux_stream_shield(stream_proof.isChecked())
            )
            linux_layout.addWidget(hide_now)
            linux_layout.addStretch()
            capture_card.add_row(linux_row)
        local_card = add_card(
            security_layout,
            SettingsCard("lock-keyhole", "Protezione locale", "Il vault e le chiavi private restano cifrati sul dispositivo."),
        )
        local_info = QLabel("Argon2id · XChaCha20-Poly1305 · nessuna telemetria applicativa")
        local_info.setObjectName("muted")
        local_info.setWordWrap(True)
        local_info.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        local_info.setContentsMargins(16, 14, 16, 16)
        local_card.add_row(local_info)

        # Diagnostica
        _diagnostics, diagnostics_layout = add_page()
        tools_card = add_card(
            diagnostics_layout,
            SettingsCard("terminal", "Strumenti e diagnostica", "Controlla lo stato locale senza includere il testo dei messaggi."),
        )
        tools_row = QFrame()
        tools_row.setObjectName("settingsRow")
        tools_layout = QHBoxLayout(tools_row)
        tools_layout.setContentsMargins(16, 14, 16, 14)
        tools_layout.setSpacing(10)
        console_button = QPushButton("Apri Console UI")
        console_button.setIcon(lucide_icon("terminal"))
        console_button.clicked.connect(self.show_ui_console)
        update_button = QPushButton("Controlla aggiornamenti")
        update_button.setIcon(lucide_icon("refresh-cw"))
        update_button.clicked.connect(lambda: self.check_updates(manual=True))
        tools_layout.addWidget(console_button)
        tools_layout.addWidget(update_button)
        tools_layout.addStretch()
        tools_card.add_row(tools_row)

        actions = QHBoxLayout()
        cancel = QPushButton("Annulla")
        cancel.setObjectName("ghost")
        cancel.clicked.connect(dialog.reject)
        save = QPushButton("Salva impostazioni")
        save.setObjectName("primary")
        save.clicked.connect(dialog.accept)
        actions.addStretch()
        actions.addWidget(cancel)
        actions.addWidget(save)
        dialog.body_layout.addLayout(actions)

        def save_settings() -> None:
            self.service.update_settings(int(interval.currentData()), single_use.isChecked())
            self.service.update_audio_settings(
                str(audio_input.currentData()), str(audio_output.currentData())
            )
            self.service.update_appearance_settings(
                str(theme.currentData()), int(text_scale.currentData()), str(ui_density.currentData())
            )
            self.service.update_privacy_settings(
                send_delivery_receipts=delivery_receipts.isChecked(),
                send_read_receipts=read_receipts.isChecked(),
                link_previews=link_previews.isChecked(),
                clearnet_enabled=clearnet.isChecked(),
                stream_proof_enabled=stream_proof.isChecked(),
                language=str(language.currentData()),
            )
            desired_low_latency = low_latency.isChecked()
            desired_warm_recent = warm_recent.isChecked()
            desired_mask_recent = mask_recent.isChecked()

            def network_applied(value: object) -> None:
                result = value if isinstance(value, dict) else {}
                mode = "bassa latenza · 2 hop" if result.get("low_latency_mode") else "massima privacy · 3 hop"
                self._log_action(f"Profilo I2P applicato · {mode}")

            self._run_task(
                lambda: self.service.update_network_settings(
                    low_latency_mode=desired_low_latency,
                    warm_recent_contacts=desired_warm_recent,
                    mask_recent_contact_metadata=desired_mask_recent,
                ),
                network_applied,
                lambda error: self._protocol_event("network_profile_error", error),
            )
            set_language(str(language.currentData()))
            apply_appearance(
                str(theme.currentData()), int(text_scale.currentData()), str(ui_density.currentData())
            )
            self._build_ui()
            localize_widget(self)
            self.refresh_contacts()
            if self._tray is not None:
                old_tray = self._tray
                self._tray = None
                old_tray.hide()
                old_tray.deleteLater()
                self._setup_tray()
            self._apply_stream_proof_setting(notify=True)
            if self.selected_contact:
                self._rendered_contact = ""
                self.refresh_messages("settings", self.selected_contact)
            self._log_action("Impostazioni privacy salvate")
            self.statusBar().showMessage(tr("Impostazioni salvate"), 5000)

        dialog.accepted.connect(save_settings)
        self._show_modeless(dialog)

    def check_updates(self, manual: bool = False) -> None:
        if not self.service.settings().get("clearnet_enabled", False):
            if manual:
                KerberusMessageDialog.show_message(
                    self, "Clearnet disabilitata",
                    "Abilita le funzioni clearnet nelle impostazioni prima di controllare gli aggiornamenti.",
                )
            return
        self._log_action("Controllo aggiornamenti GitHub")

        def found(value: object) -> None:
            info = value if isinstance(value, UpdateInfo) else None
            if info is None:
                if manual:
                    KerberusMessageDialog.show_message(
                        self, "Aggiornamenti",
                        tr_format("Kerberus {version} è la versione più recente.", version=__version__),
                    )
                return
            if KerberusMessageDialog.ask(
                self,
                "Aggiornamento disponibile",
                tr_format(
                    "È disponibile Kerberus {version}. Scaricare ora l'aggiornamento dalla release GitHub?",
                    version=info.version,
                ),
            ):
                self._download_update(info)

        def failed(error: str) -> None:
            if manual:
                self._error("Aggiornamenti", error)

        self._run_task(lambda: check_for_update(__version__), found, failed)

    def _download_update(self, info: UpdateInfo) -> None:
        self.statusBar().showMessage(f"Download Kerberus {info.version}…", 10000)

        def ready(value: object) -> None:
            path = Path(str(value))
            if os.name != "nt":
                KerberusMessageDialog.show_message(
                    self,
                    "Aggiornamento verificato",
                    tr_format("SHA-256 valida. Il nuovo eseguibile è stato salvato in:\n{path}", path=path),
                )
                return
            if not KerberusMessageDialog.ask(
                self,
                "Aggiornamento verificato",
                "La checksum pubblicata nella release è valida. Chiudere Kerberus e avviare l'installer?",
            ):
                return
            subprocess.Popen([str(path)], cwd=path.parent, close_fds=True)
            self._allow_close = True
            self.close()

        self._run_task(
            lambda: download_update(info, self.service.config.downloads_path / "updates"),
            ready,
            lambda error: self._error("Aggiornamenti", error),
        )

    def show_profile(self) -> None:
        self._log_action("Apertura Profilo")
        identity = self.service.identity()
        if not identity:
            return
        dialog = KerberusDialog("Il mio profilo", self, 720)
        layout = dialog.body_layout
        layout.setContentsMargins(30, 28, 30, 28)
        layout.setSpacing(12)
        eyebrow = QLabel("PROFILO KERBERUS")
        eyebrow.setObjectName("eyebrow")
        layout.addWidget(eyebrow)
        profile_row = QHBoxLayout()
        profile_row.setSpacing(18)
        avatar = QLabel()
        set_avatar(avatar, identity, 88)
        profile_row.addWidget(avatar, alignment=Qt.AlignmentFlag.AlignTop)
        profile_fields = QVBoxLayout()
        username_label = QLabel("USERNAME")
        username_label.setObjectName("eyebrow")
        username = QLineEdit(identity.name)
        username.setMaxLength(40)
        username.addAction(lucide_icon("pencil"), QLineEdit.ActionPosition.LeadingPosition)
        profile_fields.addWidget(username_label)
        profile_fields.addWidget(username)
        photo_actions = QHBoxLayout()
        choose_photo = QPushButton("Cambia foto")
        choose_photo.setIcon(lucide_icon("image-plus"))
        remove_photo = QPushButton("Rimuovi")
        remove_photo.setObjectName("ghost")
        photo_actions.addWidget(choose_photo)
        photo_actions.addWidget(remove_photo)
        photo_actions.addStretch()
        profile_fields.addLayout(photo_actions)
        profile_row.addLayout(profile_fields, 1)
        layout.addLayout(profile_row)
        avatar_data = identity.avatar_data

        def choose_avatar() -> None:
            nonlocal avatar_data
            path, _ = QFileDialog.getOpenFileName(
                dialog,
                tr("Scegli foto profilo"),
                "",
                tr("Immagini (*.png *.jpg *.jpeg *.webp *.bmp)"),
            )
            if not path:
                return
            try:
                avatar_data = self._normalize_avatar(Path(path))
                preview = IdentityBundle.from_dict(identity.to_dict())
                preview.avatar_data = avatar_data
                set_avatar(avatar, preview, 88)
            except Exception as exc:
                self._error("Foto profilo", str(exc))

        def remove_avatar() -> None:
            nonlocal avatar_data
            avatar_data = ""
            preview = IdentityBundle.from_dict(identity.to_dict())
            preview.avatar_data = ""
            set_avatar(avatar, preview, 88)

        choose_photo.clicked.connect(choose_avatar)
        remove_photo.clicked.connect(remove_avatar)
        crypto_row = QHBoxLayout()
        crypto_id = QLabel()
        crypto_id.setObjectName("muted")
        crypto_id.setWordWrap(True)
        reveal_id = QToolButton()
        reveal_id.setIcon(lucide_icon("eye"))
        reveal_id.setIconSize(QSize(17, 17))
        reveal_id.setFixedSize(34, 34)
        identity_visible = True

        def toggle_identity() -> None:
            nonlocal identity_visible
            identity_visible = not identity_visible
            if identity_visible:
                crypto_id.setText(f"ID crittografico  {identity.identity_id}")
                crypto_id.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                reveal_id.setIcon(lucide_icon("eye-off"))
                reveal_id.setToolTip("Nascondi ID crittografico")
            else:
                crypto_id.setText("ID crittografico  " + "*" * 32)
                crypto_id.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
                reveal_id.setIcon(lucide_icon("eye"))
                reveal_id.setToolTip("Mostra ID crittografico")

        reveal_id.clicked.connect(toggle_identity)
        toggle_identity()
        crypto_row.addWidget(crypto_id, 1)
        crypto_row.addWidget(reveal_id, alignment=Qt.AlignmentFlag.AlignTop)
        layout.addLayout(crypto_row)
        layout.addSpacing(14)
        code_label = QLabel("CODICE CONTATTO")
        code_label.setObjectName("eyebrow")
        layout.addWidget(code_label)
        code = QPlainTextEdit()
        code.setReadOnly(True)
        code.setFixedHeight(104)
        code.setStyleSheet("font-family: Consolas; font-size: 13px;")
        layout.addWidget(code)
        expiry = QLabel()
        expiry.setObjectName("muted")
        layout.addWidget(expiry)
        actions = QHBoxLayout()
        export = QPushButton("Esporta profilo")
        export.setIcon(lucide_icon("upload"))
        export.clicked.connect(lambda: self.export_identity(dialog))
        copy = QPushButton("Copia codice")
        copy.setIcon(lucide_icon("copy"))
        save = QPushButton("Salva profilo")
        save.setObjectName("primary")
        save.setIcon(lucide_icon("shield-check", "#07120e"))
        save.clicked.connect(dialog.accept)

        def copy_code() -> None:
            current = code.toPlainText().strip()
            if current and not current.startswith("In attesa"):
                QApplication.clipboard().setText(current)
                copy.setText("Copiato")

        copy.clicked.connect(copy_code)
        actions.addWidget(export)
        actions.addWidget(copy)
        actions.addStretch()
        actions.addWidget(save)
        layout.addLayout(actions)
        timer = QTimer(dialog)

        def refresh_code() -> None:
            try:
                current = self.service.contact_code()
                if code.toPlainText() != current:
                    code.setPlainText(current)
                    copy.setText("Copia codice")
                settings = self.service.settings()
                period_seconds = settings["contact_code_period_minutes"] * 60
                elapsed = max(0, int(time.time()) - settings["contact_code_anchor_time"])
                seconds = period_seconds - (elapsed % period_seconds)
                policy = tr("Monouso" if settings["contact_code_single_use"] else "Riutilizzabile nel periodo")
                expiry.setText(tr_format(
                    "{policy} · nuovo codice tra {seconds} secondi", policy=policy, seconds=seconds
                ))
            except Exception:
                code.setPlainText("In attesa della connessione I2P")
                expiry.setText("Codice non disponibile")

        timer.timeout.connect(refresh_code)
        timer.start(1000)
        refresh_code()
        def save_profile() -> None:
            self._run_task(
                lambda: self.service.update_profile(username.text(), avatar_data),
                self._profile_saved,
                lambda error: self._error("Profilo", error),
            )

        dialog.accepted.connect(save_profile)
        self._show_modeless(dialog)

    @staticmethod
    def _normalize_avatar(path: Path) -> str:
        image = QImage(str(path))
        if image.isNull():
            raise ValueError("Immagine non leggibile")
        for size in (256, 224, 192, 160, 128):
            scaled = image.scaled(
                size,
                size,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            x = max(0, (scaled.width() - size) // 2)
            y = max(0, (scaled.height() - size) // 2)
            square = scaled.copy(x, y, size, size).convertToFormat(QImage.Format.Format_ARGB32)
            buffer = QBuffer()
            buffer.open(QIODevice.OpenModeFlag.WriteOnly)
            square.save(buffer, "PNG")
            raw = bytes(buffer.data())
            buffer.close()
            if len(raw) <= 120_000:
                return b64(raw)
        raise ValueError("Immagine troppo complessa da comprimere in modo sicuro")

    def _profile_saved(self, value: object) -> None:
        self.refresh_contacts()
        if self.selected_contact:
            self.select_contact(self.selected_contact)
        self.statusBar().showMessage(tr("Profilo firmato e aggiornato"), 5000)

    def import_contact(self) -> None:
        self._log_action("Importazione profilo richiesta")
        path, _ = QFileDialog.getOpenFileName(
            self, tr("Importa profilo"), "", tr("Profilo Kerberus (*.kbid *.json);;Tutti i file (*.*)")
        )
        if not path:
            return
        try:
            contact = self.service.import_contact(Path(path).read_text("utf-8"))
            self.refresh_contacts()
            self.select_contact(contact.identity_id)
        except Exception as exc:
            self._error("Profilo non valido", str(exc))

    def export_identity(self, parent: QWidget | None = None) -> None:
        self._log_action("Esportazione profilo richiesta")
        identity = self.service.identity()
        if not identity:
            return
        path, _ = QFileDialog.getSaveFileName(
            parent or self, tr("Esporta profilo"), f"{identity.name}.kbid", tr("Profilo Kerberus (*.kbid)")
        )
        if path:
            Path(path).write_text(self.service.export_identity(), encoding="utf-8")

    def connect_router(self) -> None:
        if self._connecting:
            return
        self._connecting = True
        self._log_action("Connessione I2P avviata")
        if hasattr(self, "router_dot"):
            self.router_dot.setStyleSheet(f"background: {COLORS['warning']}; border-radius: 4px;")
            self.router_text.setText("I2P: connessione...")
            self.router_meta.setText("Avvio router e tunnel")

        def work() -> None:
            try:
                if not self.service.sam.available():
                    RouterInstaller.ensure_sam_enabled()
                    RouterInstaller.start_installed()
                    for _ in range(45):
                        if self.service.sam.available():
                            break
                        time.sleep(1)
                self.service.connect_router()
                self.signals.router_changed.emit(True, "I2P: connesso")
            except Exception as exc:
                self.signals.router_changed.emit(False, str(exc))

        thread = threading.Thread(target=work, daemon=True)
        self._workers.append(thread)
        thread.start()

    def _set_router_status(self, connected: bool, detail: str) -> None:
        self._connecting = False
        self._router_connected = connected
        self._router_detail = detail
        color = COLORS["accent"] if connected else COLORS["danger"]
        self.router_dot.setStyleSheet(f"background: {color}; border-radius: 4px;")
        self.router_text.setText(tr("I2P: connesso" if connected else "I2P: non connesso"))
        self.router_meta.setText(tr("Tunnel pronto · SAM locale" if connected else "Nuovo tentativo tra 10 s"))
        self.router_text.setToolTip(detail)
        self._log_action("I2P connesso" if connected else f"Connessione I2P non riuscita · {detail}")
        if connected:
            self.statusBar().showMessage(tr("Canale I2P pronto"), 3500)
        else:
            QTimer.singleShot(10000, self.connect_router)

    def show_i2p_info(self) -> None:
        self._log_action("Apertura Stato I2P")
        identity = self.service.identity()
        dialog = KerberusDialog("Stato I2P", self, 620)
        layout = dialog.body_layout
        layout.setContentsMargins(28, 26, 28, 26)
        layout.setSpacing(12)
        header = QHBoxLayout()
        icon = QLabel()
        icon.setPixmap(lucide_icon("network", COLORS["accent"] if self._router_connected else COLORS["danger"], 30).pixmap(30, 30))
        title_box = QVBoxLayout()
        title = QLabel("I2P connesso" if self._router_connected else "I2P non connesso")
        title.setObjectName("dialogTitle")
        subtitle = QLabel(self._router_detail)
        subtitle.setObjectName("muted")
        subtitle.setWordWrap(True)
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header.addWidget(icon, alignment=Qt.AlignmentFlag.AlignTop)
        header.addLayout(title_box, 1)
        state_badge = QLabel("ONLINE" if self._router_connected else "OFFLINE")
        state_badge.setStyleSheet(
            f"background: {COLORS['accent_dark'] if self._router_connected else '#552a30'}; "
            f"color: {COLORS['accent'] if self._router_connected else COLORS['danger']}; "
            "border-radius: 7px; padding: 5px 9px; font-size: 11px; font-weight: 800;"
        )
        header.addWidget(state_badge, alignment=Qt.AlignmentFlag.AlignTop)
        layout.addLayout(header)
        layout.addSpacing(8)

        destination = "Non disponibile"
        queues = self.service.queue_status()
        if identity and identity.destination:
            try:
                destination = destination_b32(identity.destination)
            except ValueError:
                pass
        details = (
            ("Versione", f"Kerberus {__version__}"),
            ("Bridge SAM", f"{self.service.config.sam_host}:{self.service.config.sam_port}"),
            ("Destination", destination),
            ("Trasporto", "I2P streaming · sessione persistente"),
            (
                "Profilo tunnel",
                "Bassa latenza · 2 hop" if self.service.settings().get("low_latency_mode", False)
                else "Massima privacy · 3 hop",
            ),
            ("Messaggi", "X25519 + ML-KEM-768 · XChaCha20-Poly1305"),
            ("Identità", "Ed25519 · profili firmati"),
            ("Metadati", "Padding a bucket · anti-replay · timestamp cifrati"),
            (
                "Code locali",
                tr_format(
                    "{messages} messaggi · {contacts} contatti · {controls} conferme",
                    messages=queues["messages"], contacts=queues["contacts"], controls=queues["control"],
                ),
            ),
            ("Ultimo evento", self.service.last_protocol_event),
        )
        for label, value in details:
            row = QFrame()
            row.setStyleSheet(f"background: {COLORS['surface']}; border: 1px solid {COLORS['border']}; border-radius: 7px;")
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(12, 10, 12, 10)
            key = QLabel(label)
            key.setObjectName("muted")
            data = QLabel(value)
            data.setWordWrap(True)
            data.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            row_layout.addWidget(key)
            row_layout.addStretch()
            row_layout.addWidget(data, 1)
            layout.addWidget(row)
        actions = QHBoxLayout()
        reconnect = QPushButton("Riconnetti")
        reconnect.setIcon(lucide_icon("refresh-cw"))
        reconnect.clicked.connect(lambda: (dialog.accept(), self.connect_router()))
        retry = QPushButton("Riprova code")
        retry.clicked.connect(lambda: (dialog.accept(), self._retry_queues()))
        close = QPushButton("Chiudi")
        close.setObjectName("primary")
        close.clicked.connect(dialog.accept)
        actions.addWidget(reconnect)
        actions.addWidget(retry)
        actions.addStretch()
        actions.addWidget(close)
        layout.addLayout(actions)
        self._show_modeless(dialog)

    def _retry_queues(self) -> None:
        status = self.service.retry_all_now()
        self._log_action("Retry manuale delle code I2P")
        self.statusBar().showMessage(
            tr_format(
                "Retry avviato: {messages} messaggi, {contacts} contatti, {controls} conferme",
                messages=status["messages"], contacts=status["contacts"], controls=status["control"],
            ),
            8000,
        )

    def router_setup(self) -> None:
        if self.service.sam.available():
            self.connect_router()
            return
        if os.name != "nt":
            RouterInstaller.ensure_sam_enabled()
            if RouterInstaller.start_installed():
                self.statusBar().showMessage(tr("Router I2P avviato · attendo il bridge SAM"), 8000)
                QTimer.singleShot(1500, self.connect_router)
                return
            KerberusMessageDialog.show_message(
                self,
                "Configura I2P su Linux",
                "Installa I2P dal repository ufficiale della distribuzione, avvialo con “i2prouter start” "
                "e verifica che SAM ascolti soltanto su 127.0.0.1:7656. Kerberus ha già preparato la "
                "configurazione utente in ~/.i2p/clients.config.d/.",
            )
            return
        if not KerberusMessageDialog.ask(
            self, "Installa I2P", tr_format(
                "Scaricare l'installer ufficiale I2P {version} e verificarne la checksum SHA-256?",
                version=I2P_VERSION,
            )
        ):
            return
        self._download_dialog = KerberusProgressDialog("Configurazione I2P", "Download e verifica I2P...", self)
        self._download_dialog.show()

        def download() -> Path:
            return RouterInstaller(self.service.config.downloads_path).download_windows(
                lambda done, total: self.signals.download_progress.emit(done, total)
            )

        self._run_task(download, self._download_ready, lambda error: self._download_failed(error))

    def _update_download(self, done: int, total: int) -> None:
        if self._download_dialog:
            self._download_dialog.setMaximum(max(total, 1))
            self._download_dialog.setValue(done)

    def _download_ready(self, value: object) -> None:
        if self._download_dialog:
            self._download_dialog.close()
            self._download_dialog = None
        path = Path(value)
        if KerberusMessageDialog.ask(self, "I2P verificato", "Checksum valida. Avviare l'installer?"):
            RouterInstaller.launch_installer(path)

    def _download_failed(self, error: str) -> None:
        if self._download_dialog:
            self._download_dialog.close()
            self._download_dialog = None
        self._error("I2P", error)

    def _contact_arrived(self, contact_id: str) -> None:
        self.refresh_contacts()
        QTimer.singleShot(100, self.refresh_contacts)
        if not self.selected_contact or self.selected_contact == contact_id:
            self.select_contact(contact_id)
        self.statusBar().showMessage(tr("Nuovo contatto verificato"), 5000)

    def _run_task(
        self,
        function: Callable[[], object],
        success: Callable[[object], None],
        failure: Callable[[str], None],
    ) -> None:
        signals = AppSignals()
        signals.task_done.connect(success)
        signals.task_error.connect(failure)
        self._task_signals = getattr(self, "_task_signals", [])
        self._task_signals.append(signals)

        def work() -> None:
            try:
                signals.task_done.emit(function())
            except Exception as exc:
                signals.task_error.emit(str(exc))

        thread = threading.Thread(target=work, daemon=True)
        self._workers.append(thread)
        thread.start()

    def _run_preview_task(
        self,
        function: Callable[[], object],
        success: Callable[[object], None],
        failure: Callable[[str], None],
    ) -> None:
        signals = AppSignals()
        signals.task_done.connect(success)
        signals.task_error.connect(failure)
        self._task_signals = getattr(self, "_task_signals", [])
        self._task_signals.append(signals)

        def work() -> None:
            try:
                signals.task_done.emit(function())
            except Exception as exc:
                signals.task_error.emit(str(exc))

        try:
            self._preview_pool.submit(work)
        except RuntimeError:
            failure("Anteprime in chiusura")

    def _run_network_task(
        self,
        function: Callable[[], object],
        success: Callable[[object], None],
        failure: Callable[[str], None],
    ) -> None:
        signals = AppSignals()
        signals.task_done.connect(success)
        signals.task_error.connect(failure)
        self._task_signals = getattr(self, "_task_signals", [])
        self._task_signals.append(signals)

        def work() -> None:
            try:
                signals.task_done.emit(function())
            except Exception as exc:
                signals.task_error.emit(str(exc))

        try:
            self._network_pool.submit(work)
        except RuntimeError:
            failure("Diagnostica rete in chiusura")

    def _request_message_link_preview(self, url: str) -> None:
        if not url or url in self._link_preview_cache or url in self._link_preview_pending:
            return
        self._link_preview_pending.add(url)

        def update_layout() -> None:
            if not hasattr(self, "message_view"):
                return
            self.message_view.chat_delegate.invalidate_preview(url)
            self.message_view.scheduleDelayedItemsLayout()
            self.message_view.viewport().update()

        def loaded(value: object) -> None:
            self._link_preview_pending.discard(url)
            self._link_preview_cache[url] = value if isinstance(value, dict) else {"url": url}
            update_layout()

        def failed(error: str) -> None:
            self._link_preview_pending.discard(url)
            self._link_preview_cache[url] = {"url": url, "_error": error}
            update_layout()

        self._run_preview_task(lambda: fetch_link_preview(url), loaded, failed)

    def _error(self, title: str, message: str) -> None:
        self._log_action(f"Errore UI: {title}")
        KerberusMessageDialog.show_message(self, title, message)

    def closeEvent(self, event: QCloseEvent) -> None:
        if not self._allow_close:
            if not KerberusMessageDialog.ask(
                self,
                "Chiudi Kerberus",
                "Chiudere Kerberus e arrestare anche il router I2P? Tutte le comunicazioni I2P verranno interrotte.",
            ):
                event.ignore()
                return
            self._allow_close = True
        self._shutdown()
        event.accept()

    def exit_from_tray(self) -> None:
        self._allow_close = True
        self.close()
        if not self._shutdown_complete:
            self._shutdown()

    def _shutdown(self) -> None:
        if not self._shutdown_complete:
            self._shutdown_complete = True
            if self._voice_recorder.active:
                self._voice_recorder.stop(discard=True)
            if self._voice_player is not None:
                self._voice_player.stop()
            if hasattr(self, "message_view"):
                self.message_view.stop_inline_video()
            if self._tray is not None:
                self._tray.hide()
            self._release_resources()
            RouterInstaller.stop_running()
        self._quit_application()

    def _release_resources(self, *, wait: bool = False) -> None:
        """Release non-Qt resources before this window can be destroyed.

        Worker callbacks retain Qt signal objects, so test and application
        teardown must stop their executors before Qt starts deleting widgets.
        Waiting is useful for deterministic test cleanup; the interactive
        shutdown remains immediate because its workers are best-effort tasks.
        """
        if self._resources_released:
            return
        self._resources_released = True
        self._preview_pool.shutdown(wait=wait, cancel_futures=True)
        self._network_pool.shutdown(wait=wait, cancel_futures=True)
        if wait:
            current = threading.current_thread()
            for worker in self._workers:
                if worker is not current and worker.is_alive():
                    worker.join(timeout=10)
        self.service.close()
        self._attachment_temp_dir.cleanup()

    @staticmethod
    def _quit_application() -> None:
        application = QApplication.instance()
        if application is not None:
            application.quit()


def run() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("Kerberus")
    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI", 10))
    app.setStyleSheet(STYLE)
    window = KerberusWindow()
    if not window.initialize():
        return
    window.show()
    sys.exit(app.exec())
