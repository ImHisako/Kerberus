# Kerberus

**Private, direct desktop messaging over I2P with hybrid post-quantum encryption.**

[Italiano](README.it.md) · [Architecture decisions](docs/adr/) · [I2P SAM documentation](https://i2p.net/en/docs/api/samv3/)

Kerberus is an experimental peer-to-peer messenger for Windows and Linux. It combines I2P transport, self-sovereign signed identities, hybrid X25519 + ML-KEM-768 message encryption, a persistent Double Ratchet, and an encrypted local vault. There is no Kerberus account service, central contact directory, message database, analytics endpoint, or cloud mailbox.

> [!WARNING]
> Kerberus is under active development and has not received an independent security audit. It is not a guarantee of anonymity and should not yet be relied upon to protect high-risk people, operations, or data. Read [Security boundaries and limitations](#security-boundaries-and-limitations) before using it.

## Why Kerberus

Kerberus is designed around a small set of principles:

- **Direct communication:** messages travel between I2P destinations instead of through a Kerberus server.
- **Local ownership:** identity keys, contacts, history, queues, preferences, and ratchet state stay in an encrypted vault on the device.
- **Layered cryptography:** transport anonymity, hybrid per-message encryption, signatures, and ratcheting solve different parts of the problem.
- **Privacy controls:** delivery receipts, read receipts, notifications, and link previews can be controlled globally or per conversation.
- **Honest security claims:** Kerberus documents what it protects, what remains observable, and which components have not been independently reviewed.

## Feature overview

| Area | Capabilities |
|---|---|
| Messaging | Direct text messages, encrypted local outbox, automatic retry, forwarding with fresh encryption, local deletion, delivery and read states |
| Identity | Ed25519-signed profiles, stable cryptographic identity ID, username, avatar, persistent I2P destination |
| Contacts | Rotating contact codes, optional single use, signed request/accept/reject controls, pending-request cancellation |
| Encryption | X25519 + ML-KEM-768 hybrid envelope, XChaCha20-Poly1305, Ed25519 authentication, Double Ratchet v3, bounded out-of-order support |
| Privacy | No application telemetry, encrypted receipts and reactions, per-chat overrides, optional link previews, padded plaintext buckets, Windows capture exclusion and Linux privacy curtain |
| Interface | PyQt6 desktop UI, Italian and English, embedded emoji and contact-profile panels, reactions, modern dropdowns, organized settings, system tray |
| Diagnostics | Local UI event console, explicit connection errors, I2P transport peers with automatic geographic details, per-chat JSON export |
| Transport | I2P SAM v3, persistent session and streams, native Go multiplexer with Python fallback, full-duplex inline replies |
| Platforms | Standalone Windows installer and Linux portable builds, source execution on Python 3.11+ |

## Messaging experience

### Reliable local outbox

A message is written to the encrypted vault before network delivery is attempted. If the recipient, destination, or LeaseSet is temporarily unavailable, the ciphertext remains queued and Kerberus retries it with bounded backoff. A successful write to the local SAM socket is shown as **Sent**, not **Delivered**; only an authenticated end-to-end receipt can mark it as delivered.

Message states are:

- **Pending** — safely stored in the vault and waiting for a send attempt or ratchet handshake.
- **Sent** — handed to the I2P stream; no recipient receipt has arrived yet.
- **Delivered** — the recipient returned an encrypted delivery receipt.
- **Read** — the recipient returned an encrypted read receipt; the double ticks turn blue.

Delivery and read receipts can be disabled globally or for an individual conversation.

### Reactions and emoji

Kerberus includes a searchable picker backed by the full emoji catalog shipped by the `emoji` package, including variants, skin tones, flags, and ZWJ sequences. Search terms work in Italian and English. Short emoji-only messages are recognized as quick reactions and displayed in a compact bubble with enlarged emoji; attached reactions use dedicated chips. Each participant can add multiple reactions to one message. Reactions are encrypted inside the ratchet channel; left-clicking one of your own reactions removes only that emoji and sends an authenticated removal event to the peer.

### Message actions

The context menu on a message supports:

- copying plaintext to the system clipboard;
- forwarding it as a completely new encrypted message without original-sender metadata;
- deleting the local copy and any unsent outbox entry;
- adding or removing an encrypted reaction;
- inspecting send, receive, delivery, and read timing.

Deleting a delivered message cannot erase the peer's copy. Clipboard contents are outside the vault and may be visible to the operating system or other local applications.

### Profiles and conversation UI

Every message displays the sender's signed username and avatar. Avatars are signed as part of the public profile and limited to a small PNG payload. Bubble width follows its content: it remains compact for short text and grows up to a readable limit for long messages. Conversations use a virtualized model/view: the complete history is available to one stable scrollbar while only visible rows are painted. Dragging or using the wheel therefore moves continuously without creating message widgets or paginated range jumps. Conversation settings and contact profiles open in the same in-app side drawer rather than separate movable windows.

Each user can choose per contact whether their identity ID is displayed in the peer's profile UI. This encrypted preference controls presentation only: the stable identity ID remains part of the authenticated protocol and is already technically known to an accepted contact.

The application supports Italian and English. The selected language is stored in the vault and applied immediately.

## Contacts and identity verification

Each installation creates a self-sovereign identity containing:

- an Ed25519 signing public key;
- an X25519 static exchange public key;
- an ML-KEM-768 public key;
- a persistent I2P destination;
- a display name and optional PNG avatar;
- an Ed25519 signature over the complete public profile.

The identity ID is the SHA-256 digest of the Ed25519 public key. A profile cannot silently replace its signing key while retaining the same identity ID.

### Contact codes

A contact code binds a temporary authenticated token to the profile's `.b32.i2p` destination. The user can choose a rotation period of 1, 5, 15, or 60 minutes and can require immediate rotation after first use.

The contact exchange provides the following controls:

1. The requester signs the complete request, including a random request ID and target code.
2. The recipient verifies the profile signature, rotating code, request signature, and remote I2P destination.
3. Accept and reject controls are signed and bound to the original request ID.
4. An acceptance is valid only while the matching local request is pending.
5. The remote destination reported by SAM is matched against the signed profile destination.
6. Replays are handled idempotently and cannot create an unsolicited accepted contact.

Pending requests can be cancelled from the conversation list.

## Architecture

```text
┌──────────────────────────────────────────────────────────────┐
│ PyQt6 desktop interface                                     │
│ conversations · profiles · privacy settings · diagnostics   │
└──────────────────────────────┬───────────────────────────────┘
                               │
┌──────────────────────────────▼───────────────────────────────┐
│ MessengerService                                             │
│ contacts · ratchets · receipts · reactions · outbox · retry │
├──────────────────────────────┬───────────────────────────────┤
│ Encrypted vault              │ Application E2EE              │
│ Argon2id                      │ Ed25519                        │
│ XChaCha20-Poly1305            │ X25519 + ML-KEM-768           │
│                               │ Double Ratchet v3             │
└──────────────────────────────┴───────────────┬───────────────┘
                                               │ encrypted frames
┌──────────────────────────────────────────────▼───────────────┐
│ SAM transport                                                 │
│ native Go stream multiplexer · automatic Python fallback     │
└──────────────────────────────────────────────┬───────────────┘
                                               │ 127.0.0.1:7656
┌──────────────────────────────────────────────▼───────────────┐
│ I2P router · tunnels · LeaseSets · Streaming                 │
└──────────────────────────────────────────────────────────────┘
```

Kerberus maintains one long-lived SAM session for the local profile. The release build includes a dependency-free Go helper that keeps multiple accepts pending, multiplexes framed traffic, reuses streams, and permits replies on the same full-duplex stream. If the helper cannot start or exits, the Python transport takes over using the same application protocol and encrypted queues.

## Cryptography and security design

Kerberus deliberately uses multiple layers. They are complementary, not interchangeable.

### 1. I2P transport layer

I2P provides destination addressing and routed tunnels intended to hide the participants' direct network locations from each other and from ordinary network observers. Kerberus connects to SAM v3 only on `127.0.0.1:7656`.

Transport settings include:

- persistent I2P destination and long-lived SAM session;
- three inbound and three outbound tunnels, plus one backup each;
- default tunnel length retained — Kerberus does not enable zero-hop tunnels for lower latency;
- optional **Low latency** mode with two-hop tunnels and immediate initial ACKs, enabled only after an embedded UI warning; it reduces resistance to traffic correlation but does not change end-to-end encryption;
- `i2cp.leaseSetEncType=6,4` for ML-KEM-768/ECIES-X25519 LeaseSet compatibility in supported I2P versions;
- interactive streaming profile, persistent peer streams, TCP no-delay, and keepalive;
- `SILENT=true` with a short `connectDelay`, allowing the first frame to accompany stream establishment;
- configurable pre-warming of up to eight contacts to reduce first-message latency, explicitly presented as a privacy/performance trade-off because it creates background traffic and connection metadata; disable it for maximum privacy. An optional mode uniformly selects real contacts instead of using recent history, reducing correlation with the latest chats without pretending nonexistent destinations are valid. The SAM router still sees selected destinations and contacts may observe the connection;
- application receipts as the only authoritative delivery signal.

I2P protects the network route; it does not replace application-layer end-to-end encryption or endpoint security.

### 2. Signed identities and controls

Public profiles are signed with Ed25519. Contact requests, acceptances, rejections, legacy acknowledgements, and profile changes are authenticated before they affect local state. Message envelopes are also signed, binding the sender, recipient, random message ID, ephemeral key, ML-KEM ciphertext, nonce, and encrypted payload.

Ed25519 provides classical authentication. It is **not** a post-quantum signature scheme.

### 3. Hybrid per-message envelope

Every application message, receipt, reaction, or ratchet control is wrapped for the recipient using two key-agreement components:

1. a fresh ephemeral X25519 key exchange with the recipient's static X25519 public key;
2. a fresh ML-KEM-768 encapsulation to the recipient's ML-KEM public key.

Both shared secrets are combined with HKDF-SHA-512. The envelope payload is encrypted with XChaCha20-Poly1305, and the complete envelope is signed with Ed25519. A random 24-byte nonce is generated for every encryption.

The hybrid construction is intended to retain confidentiality if either X25519 or ML-KEM remains secure. This has not been formally verified as a complete protocol construction.

### 4. Double Ratchet v3

The encrypted envelope carries an inner persistent Double Ratchet channel:

- X25519 DH ratchet keys;
- HKDF-SHA-256 root-key updates;
- independent HMAC-SHA-256 sending and receiving chains;
- per-message keys used with XChaCha20-Poly1305;
- authenticated ratchet headers as AEAD associated data;
- transactional receive-state updates — failed authentication does not advance state;
- at most 256 skipped message keys for bounded out-of-order delivery;
- consumed message keys removed from the current state.

Before the first user payload is encrypted, Kerberus completes a content-free authenticated handshake in which both peers contribute fresh ephemeral X25519 keys. User content remains queued in the vault until that handshake completes. This prevents the first application payload from being protected only by reconstructable long-term-key material.

The ratchet is designed to provide classical forward secrecy and post-compromise recovery after subsequent honest DH steps. The ratchet itself is X25519-based and therefore **not post-quantum**. Kerberus should not be described as providing post-quantum forward secrecy.

### 5. Padding and replay protection

Clear payloads are padded into coarse size classes based on 512, 2,048, 8,192, or 32,768-byte buckets before envelope encryption. Padding reduces exact-length leakage but does not hide the existence, timing, direction, or approximate class of traffic.

Message IDs are random 128-bit values. The vault keeps a bounded set of previously processed IDs, and ratchet counters plus AEAD authentication prevent a replay from being accepted as new content.

### 6. Encrypted local vault

The vault stores the identity secret keys, contacts, messages, outbox, control queues, preferences, and ratchet state.

- A random salt and Argon2id derive a 256-bit vault key from the password.
- The current implementation uses the PyNaCl `MODERATE` Argon2id operations and memory limits.
- The full serialized state is encrypted with XChaCha20-Poly1305.
- `KBV1` and the salt are authenticated as associated data.
- Every write uses a fresh random nonce and atomic temporary-file replacement.
- A minimum password length of 10 characters is enforced.

The persistent private I2P destination is stored separately because SAM requires it when creating the transport session. Kerberus writes it atomically and restricts it to mode `0600` on POSIX; Windows relies on the user's profile-directory ACL. It is not encrypted by the vault password.

Python does not guarantee secure zeroization of immutable key objects, so secrets may remain in process memory until reclaimed by the runtime.

## Metadata and privacy

Kerberus does not intentionally send telemetry, crash reports, analytics, address books, message history, or key material to a Kerberus-operated service. No such service exists in the current architecture.

Application-level metadata reductions include:

- random message and request identifiers;
- padded plaintext size classes;
- encrypted delivery receipts, read receipts, and reactions;
- fresh hybrid encapsulation and nonce per envelope;
- forwarding without original-sender or source-conversation metadata;
- local-only UI diagnostics that exclude message bodies unless the user explicitly exports a chat.

These measures do not make metadata disappear. The local I2P router, operating system, contacted peer, and a sufficiently capable traffic observer may still learn or infer timing, volume, online periods, destination reuse, and communication relationships.

## Privacy controls

Global and per-chat settings cover:

- delivery receipts;
- read receipts;
- desktop notifications;
- external link previews;
- contact-code lifetime and single-use behavior.
- Windows/Linux streaming protection.
- I2P transport-peer inspection with free, keyless per-IP lookup.

### Streaming protection

On Windows, the optional streaming-protection setting applies `WDA_EXCLUDEFROMCAPTURE` to the main window and owned dialogs. Compatible capture and screen-sharing tools should omit Kerberus while the window remains visible on the local monitor.

Linux has no universal application opt-out while a window remains visible. Kerberus therefore provides a privacy curtain: **Hide Kerberus now** removes the main window and owned dialogs from the desktop while leaving the tray icon available for restoring the app. This reliably keeps the hidden content out of full-screen sharing, but does not claim invisible-while-locally-visible behavior. Neither platform mode protects against cameras, higher-privileged software, or unsupported capture paths.

### Network insights and IP details

The Network settings page automatically inspects public TCP connections owned by the local I2P router when opened and every 30 seconds afterward. These are observed transport peers and are not necessarily the exact hops of a particular I2P tunnel. Country, ASN, and network name are automatically retrieved for every new address through `ipwho.is` and cached for the session. The peer list can be collapsed with its chevron control. Each lookup discloses that peer address to the external service.

### Link previews

Link previews are disabled by default. Kerberus makes every HTTP/HTTPS URL in message text clickable and underlined even without a preview. Before handing a link to the browser, it always displays an in-app confirmation with the domain, complete URL, and a security warning; cancelling does not launch the browser. When previews are enabled, the same confirmation protects clicks anywhere on the modern card containing the site, title, author, description, and image when available. Messages without a URL receive no preview indicator. Kerberus may contact a clearnet website directly to obtain HTML/Open Graph metadata and a limited-size image. The implementation:

- accepts only HTTP and HTTPS;
- rejects credentials embedded in URLs;
- blocks localhost, `.local`, `.internal`, `.i2p`, private, loopback, link-local, and reserved addresses;
- pins the actual connection to the already validated public IP to resist DNS rebinding;
- revalidates every redirect;
- limits redirect count, response size, and request time;
- limits preview concurrency to three workers.

The destination website can still observe the device's clearnet IP address and request timing. Link previews are not routed through I2P and should remain disabled when that disclosure is unacceptable.

## Diagnostics and delay measurement

The local UI console records protocol and interface events without intentionally recording message bodies. Connection failures are surfaced with the exception type and context.

Each conversation can be exported to a user-selected JSON file containing:

- plaintext message history;
- direction and delivery state;
- message IDs and reactions;
- send, local receive, peer receive, delivery, and read timestamps;
- one-way, round-trip, and read-delay calculations;
- queue diagnostics.

Private keys, ratchet state, encrypted payloads, and the contact's I2P destination are excluded. The exported file is intentionally plaintext and must be protected by the user. One-way delay is clock-dependent; round-trip delay uses the sender's local clock and is generally more reliable.

## Installation

### Requirements

- Windows 10/11 x64, or Linux x86_64/aarch64 with a desktop environment;
- an Internet connection and a compatible I2P router;
- Python 3.11+ only when running from source;
- Go 1.24+ only when building release artifacts;
- Java 17+ for the standard Java I2P router. Kerberus itself does not use Java.

### Windows release

1. Download `KerberusInstaller.exe` from the intended release.
2. Close any older Kerberus process.
3. Run the installer and approve I2P/Java installation only if required.
4. Launch Kerberus, create the encrypted vault, and wait for **I2P: connected**.

The installer includes the application and native helper. It can download the pinned I2P 2.12.0 installer and Azul Zulu JDK when needed, verifies fixed SHA-256 values, verifies the Azul Authenticode publisher, and configures SAM on loopback only.

### Linux release

1. Install and start I2P from the distribution or official repository.
2. Place `Kerberus-linux-<arch>` and `install-linux.sh` in the same directory.
3. Run:

```bash
bash install-linux.sh
```

4. Start Kerberus from the application menu or with `~/.local/bin/kerberus`.

Kerberus writes its user SAM configuration under `~/.i2p/clients.config.d/`. System-service I2P installations may require SAM to be enabled through the router console or distribution-specific configuration directory.

### Run from source

Windows PowerShell:

```powershell
.\setup.ps1
.\start.ps1
```

Linux:

```bash
sudo apt install python3-venv
bash setup.sh
bash start.sh
```

Manual virtual environment:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m kerberus.main
```

## Basic use

### Add a contact

1. Both users wait for the I2P status to become connected.
2. The recipient opens **Profile** and shares the current contact code.
3. The requester opens **New contact**, enters the code, and optionally writes a first message.
4. The request remains visible as pending until the signed acceptance is verified.
5. After the initial ratchet handshake, queued user content is encrypted and sent.

The current mailbox is local only. Both peers generally need to be online at the same time for delivery; there is no always-on Kerberus relay storing offline messages.

### Connection errors

- **CANT_REACH_PEER** — the peer may be offline or its LeaseSet may be unavailable. Kerberus drops only that peer stream and keeps the message in the encrypted outbox.
- **INVALID_ID** — the router no longer recognizes the SAM session. Kerberus performs one coordinated session rebuild for the affected generation.
- **SAM unavailable** — verify that the I2P router is running and `127.0.0.1:7656` is reachable.

The first I2P startup may take several minutes while the router integrates and builds tunnels.

## Testing

Run the complete local suite:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v
```

Run the native transport checks:

```powershell
cd native
go test ./...
go test '-bench=Benchmark' '-run=^$' -benchmem ./...
go vet ./...
```

Run the opt-in end-to-end test with two real destinations on a local I2P router:

```powershell
$env:KERBERUS_LIVE_I2P = "1"
.\.venv\Scripts\python.exe -m unittest tests.test_live_i2p -v
```

The live test performs contact exchange, sends a ten-message burst, verifies delivery and ordering, and separately reports Python↔helper IPC overhead, the local SAM handshake, actual I2P stream opening, and encrypted-receipt round-trip time. The stream-opening probe uses a disposable `SILENT=false` connection; normal sends retain `SILENT=true` and the 0-RTT path.

The helper processes different destinations concurrently through independent dynamic queues. Commands for one destination remain FIFO, so a slow `STREAM CONNECT` for one contact does not suspend other contacts.

## Building releases

Windows:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[build]"
.\.venv\Scripts\python.exe .\build_release.py
```

Linux:

```bash
.venv/bin/python -m pip install -e '.[build]'
.venv/bin/python build_release.py
```

Python source artifacts and the complete source archive:

```powershell
.\.venv\Scripts\python.exe build_source_release.py --tag v0.7.0
```

Artifacts are written to `release/`. GitHub Actions runs Python and Go tests, builds Windows, Linux, wheel, sdist, and source-archive outputs in separate jobs, then publishes them through one final release job. The tag must exactly match the application version, so this release uses `v0.7.0`; a mismatched tag stops the build. See [`RELEASE.md`](RELEASE.md) for the complete checklist.

## Repository layout

```text
kerberus/
  crypto.py        identities, signatures, hybrid envelope encryption
  ratchet.py       Double Ratchet state and message-key handling
  service.py       contacts, messaging, receipts, reactions, queues, retry
  vault.py         encrypted local persistence
  sam.py           SAM session, streams, native-helper IPC, Python fallback
  link_preview.py  metadata parsing and SSRF-resistant preview fetching
  network_insights.py  local I2P peer discovery and explicit free IP lookup
  router.py        I2P bootstrap, configuration, start and stop
  updates.py       GitHub release check and SHA-256 verification
  ui.py            PyQt6 desktop interface and localization
native/             Go SAM stream multiplexer
installer.py        Windows installer
build_release.py    PyInstaller release build
build_source_release.py  verified wheel, sdist, and source archive
tests/              crypto, service, UI, transport, updater and live tests
docs/adr/           architecture decision records
```

## Security boundaries and limitations

- **Experimental protocol:** Kerberus and its Double Ratchet implementation have not been independently audited or formally verified.
- **No absolute anonymity:** I2P reduces network exposure but cannot eliminate endpoint compromise, behavioral correlation, timing analysis, or global-observer risk.
- **Hybrid does not mean fully post-quantum:** ML-KEM contributes to envelope confidentiality. Ed25519 signatures and the X25519 Double Ratchet remain classical.
- **Endpoint compromise wins:** malware, screen capture, clipboard monitoring, memory inspection, or access to an unlocked vault can expose plaintext and keys.
- **No secure deletion guarantee:** filesystem snapshots, backups, SSD behavior, swap, and Python memory management may preserve old data.
- **Separate I2P destination key:** the SAM private destination is permission-restricted but not encrypted by the vault password.
- **Direct availability:** there is no external offline mailbox. Delivery depends on both peers and the I2P network being reachable.
- **Link-preview disclosure:** enabled previews contact clearnet websites and reveal the device's clearnet IP to those sites.
- **Plaintext exports:** debug exports and clipboard operations intentionally move plaintext outside the vault.
- **Release trust:** updates require matching SHA-256 manifests and reject rollback, but the artifact and checksum come from the same GitHub release. There is no independent offline signature or project code-signing certificate yet.
- **Missing product areas:** groups, multi-device synchronization, attachments, voice/video, key backup, and distributed mailboxes are not implemented.

## Licensing

The Lucide icons under `kerberus/assets/lucide/` retain their upstream license in that directory. Third-party dependencies retain their respective upstream licenses. This repository currently does not contain a project-wide `LICENSE` file; do not assume an open-source license for the remaining code until one is added.
