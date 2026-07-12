# Kerberus

**Messaggistica desktop privata e diretta su I2P con cifratura ibrida post-quantum.**

[English](README.md) · [Decisioni architetturali](docs/adr/) · [Documentazione I2P SAM](https://i2p.net/en/docs/api/samv3/)

Kerberus è un messenger peer-to-peer sperimentale per Windows e Linux. Combina trasporto I2P, identità autonome firmate, cifratura ibrida X25519 + ML-KEM-768 per ogni messaggio, Double Ratchet persistente e vault locale cifrato. Non esistono un servizio account Kerberus, una directory centrale dei contatti, un database remoto dei messaggi, un endpoint di analytics o una mailbox cloud.

> [!WARNING]
> Kerberus è in sviluppo attivo e non è stato sottoposto a un audit di sicurezza indipendente. Non garantisce anonimato assoluto e non dovrebbe ancora essere usato per proteggere persone, operazioni o dati ad alto rischio. Prima dell’uso leggi [Confini di sicurezza e limitazioni](#confini-di-sicurezza-e-limitazioni).

## Perché Kerberus

Il progetto segue alcuni principi fondamentali:

- **Comunicazione diretta:** i messaggi viaggiano tra destination I2P senza attraversare un server Kerberus.
- **Controllo locale:** chiavi d’identità, contatti, cronologia, code, preferenze e stato ratchet restano nel vault cifrato del dispositivo.
- **Crittografia a più livelli:** anonimizzazione del trasporto, cifratura ibrida, firme e ratchet affrontano problemi differenti.
- **Controlli privacy:** ricevute di consegna, ricevute di lettura, notifiche e anteprime link sono configurabili globalmente o per chat.
- **Dichiarazioni verificabili:** la documentazione distingue ciò che viene protetto, ciò che resta osservabile e ciò che non è stato revisionato indipendentemente.

## Panoramica delle funzionalità

| Area | Funzionalità |
|---|---|
| Messaggi | Testo diretto, outbox locale cifrata, retry automatico, inoltro con nuova cifratura, eliminazione locale, stati di consegna e lettura |
| Identità | Profili firmati Ed25519, ID crittografico stabile, username, avatar, destination I2P persistente |
| Contatti | Codici a rotazione, uso singolo opzionale, request/accept/reject firmati, cancellazione delle richieste pendenti |
| Cifratura | Envelope ibrido X25519 + ML-KEM-768, XChaCha20-Poly1305, autenticazione Ed25519, Double Ratchet v3, messaggi fuori ordine limitati |
| Privacy | Nessuna telemetria applicativa, ricevute e reazioni cifrate, impostazioni per chat, anteprime opzionali, padding a classi di dimensione |
| Interfaccia | Desktop PyQt6, italiano e inglese, selettore Unicode ricercabile, reazioni, avatar e username sui messaggi, system tray |
| Diagnostica | Console eventi locale, errori di connessione espliciti, export JSON per chat con timestamp e misure dei ritardi |
| Trasporto | I2P SAM v3, sessione e stream persistenti, multiplexer Go nativo con fallback Python, risposte inline full-duplex |
| Piattaforme | Installer standalone Windows, build portabili Linux, avvio dal sorgente con Python 3.11+ |

## Esperienza di messaggistica

### Outbox locale affidabile

Ogni messaggio viene scritto nel vault cifrato prima del tentativo di rete. Se il destinatario, la destination o la LeaseSet non sono temporaneamente raggiungibili, il ciphertext rimane in coda e Kerberus lo ritenta con un backoff limitato. Una scrittura riuscita sul socket SAM locale produce lo stato **Inviato**, non **Consegnato**: soltanto una ricevuta end-to-end autenticata può confermare la consegna.

Gli stati sono:

- **In attesa** — salvato nel vault e in attesa di invio o dell’handshake ratchet.
- **Inviato** — affidato allo stream I2P, senza ricevuta del destinatario.
- **Consegnato** — il destinatario ha restituito una ricevuta cifrata.
- **Letto** — il destinatario ha restituito una ricevuta di lettura cifrata; le doppie spunte diventano azzurre.

Le ricevute di consegna e lettura possono essere disabilitate globalmente o per una singola conversazione.

### Reazioni ed emoji

Kerberus include un selettore ricercabile basato sull’intero catalogo emoji distribuito dal pacchetto `emoji`, comprese varianti, tonalità della pelle, bandiere e sequenze ZWJ. La ricerca riconosce nomi italiani e inglesi. Le reazioni sono cifrate nel canale ratchet. Se l’utente seleziona nuovamente la stessa reazione, Kerberus la rimuove localmente e invia al peer un evento di rimozione autenticato.

### Azioni sui messaggi

Il menu contestuale consente di:

- copiare il plaintext negli appunti di sistema;
- inoltrarlo come nuovo messaggio cifrato senza metadati del mittente originale;
- eliminare la copia locale e l’eventuale elemento non inviato nell’outbox;
- aggiungere o rimuovere una reazione cifrata;
- visualizzare tempi di invio, ricezione, consegna e lettura.

Eliminare un messaggio già consegnato non cancella la copia del peer. Gli appunti sono esterni al vault e possono essere osservati dal sistema operativo o da altre applicazioni locali.

### Profili e interfaccia della chat

Ogni messaggio mostra username e avatar firmati del mittente. L’avatar fa parte del profilo pubblico firmato ed è limitato a un piccolo PNG. Le conversazioni lunghe caricano inizialmente i 160 messaggi più recenti; la cronologia precedente viene caricata progressivamente per mantenere l’interfaccia reattiva.

L’app supporta italiano e inglese. La lingua scelta viene salvata nel vault e applicata al successivo avvio.

## Contatti e verifica dell’identità

Ogni installazione genera un’identità autonoma composta da:

- chiave pubblica di firma Ed25519;
- chiave pubblica statica di scambio X25519;
- chiave pubblica ML-KEM-768;
- destination I2P persistente;
- nome visibile e avatar PNG opzionale;
- firma Ed25519 dell’intero profilo pubblico.

L’identity ID è il digest SHA-256 della chiave pubblica Ed25519. Un profilo non può sostituire silenziosamente la chiave di firma mantenendo lo stesso identity ID.

### Codici contatto

Il codice contatto lega un token autenticato temporaneo alla destination `.b32.i2p` del profilo. L’utente può scegliere una rotazione di 1, 5, 15 o 60 minuti e richiedere la rotazione immediata dopo il primo utilizzo.

Lo scambio dei contatti applica questi controlli:

1. Il richiedente firma la richiesta completa, compresi request ID casuale e codice destinatario.
2. Il destinatario verifica firma del profilo, codice a rotazione, firma della richiesta e destination I2P remota.
3. Accettazioni e rifiuti sono firmati e vincolati al request ID originale.
4. Un’accettazione è valida soltanto finché esiste la richiesta locale corrispondente.
5. La destination remota riportata da SAM deve corrispondere alla destination contenuta nel profilo firmato.
6. Le ritrasmissioni sono idempotenti e non possono creare un contatto accettato senza richiesta.

Le richieste pendenti possono essere annullate dalla lista delle conversazioni.

## Architettura

```text
┌──────────────────────────────────────────────────────────────┐
│ Interfaccia desktop PyQt6                                   │
│ chat · profili · impostazioni privacy · diagnostica         │
└──────────────────────────────┬───────────────────────────────┘
                               │
┌──────────────────────────────▼───────────────────────────────┐
│ MessengerService                                             │
│ contatti · ratchet · ricevute · reazioni · outbox · retry   │
├──────────────────────────────┬───────────────────────────────┤
│ Vault cifrato               │ E2EE applicativa               │
│ Argon2id                     │ Ed25519                        │
│ XChaCha20-Poly1305           │ X25519 + ML-KEM-768           │
│                              │ Double Ratchet v3              │
└──────────────────────────────┴───────────────┬───────────────┘
                                               │ frame cifrati
┌──────────────────────────────────────────────▼───────────────┐
│ Trasporto SAM                                                 │
│ multiplexer Go nativo · fallback Python automatico           │
└──────────────────────────────────────────────┬───────────────┘
                                               │ 127.0.0.1:7656
┌──────────────────────────────────────────────▼───────────────┐
│ Router I2P · tunnel · LeaseSet · Streaming                  │
└──────────────────────────────────────────────────────────────┘
```

Kerberus mantiene una sessione SAM longeva per il profilo locale. Le release includono un helper Go senza dipendenze che mantiene più accept pendenti, multiplexa i frame, riutilizza gli stream e consente risposte sullo stesso stream full-duplex. Se l’helper non parte o termina, il trasporto Python subentra usando lo stesso protocollo applicativo e le stesse code cifrate.

## Crittografia e modello di sicurezza

Kerberus usa deliberatamente più livelli complementari.

### 1. Livello di trasporto I2P

I2P fornisce destination e tunnel instradati con lo scopo di nascondere le posizioni di rete dirette dei partecipanti agli altri peer e agli osservatori ordinari. Kerberus si collega a SAM v3 esclusivamente su `127.0.0.1:7656`.

Le impostazioni comprendono:

- destination I2P persistente e sessione SAM longeva;
- tre tunnel in ingresso e tre in uscita, più un backup per direzione;
- lunghezza dei tunnel predefinita: Kerberus non abilita tunnel zero-hop per ridurre la latenza;
- `i2cp.leaseSetEncType=6,4` per compatibilità LeaseSet ML-KEM-768/ECIES-X25519 nelle versioni I2P supportate;
- profilo streaming interattivo, stream persistenti, TCP no-delay e keepalive;
- `SILENT=true` e breve `connectDelay`, per accompagnare l’apertura stream con il primo frame;
- ricevute applicative come unica conferma autorevole della consegna.

I2P protegge il percorso di rete, ma non sostituisce la cifratura end-to-end applicativa o la sicurezza degli endpoint.

### 2. Identità e controlli firmati

I profili pubblici sono firmati Ed25519. Richieste contatto, accettazioni, rifiuti, ACK legacy e aggiornamenti profilo vengono autenticati prima di modificare lo stato locale. Anche gli envelope dei messaggi sono firmati, vincolando mittente, destinatario, message ID casuale, chiave effimera, ciphertext ML-KEM, nonce e payload cifrato.

Ed25519 fornisce autenticazione classica e **non** è uno schema di firma post-quantum.

### 3. Envelope ibrido per messaggio

Ogni messaggio, ricevuta, reazione o controllo ratchet viene incapsulato per il destinatario usando due componenti:

1. scambio X25519 con una nuova chiave effimera e la chiave X25519 statica del destinatario;
2. nuova incapsulazione ML-KEM-768 verso la chiave pubblica ML-KEM del destinatario.

I due segreti vengono combinati tramite HKDF-SHA-512. Il payload dell’envelope viene cifrato con XChaCha20-Poly1305 e l’envelope completo viene firmato Ed25519. Ogni operazione usa un nonce casuale nuovo di 24 byte.

La costruzione ibrida mira a mantenere la confidenzialità se almeno uno tra X25519 e ML-KEM rimane sicuro. La composizione completa non è stata verificata formalmente.

### 4. Double Ratchet v3

L’envelope cifrato trasporta un canale Double Ratchet persistente interno:

- chiavi di ratchet DH X25519;
- aggiornamenti della root key con HKDF-SHA-256;
- catene HMAC-SHA-256 indipendenti per invio e ricezione;
- chiavi per messaggio usate con XChaCha20-Poly1305;
- header ratchet autenticati come associated data AEAD;
- aggiornamenti transazionali dello stato in ricezione: un’autenticazione fallita non avanza il ratchet;
- massimo 256 chiavi saltate per gestire messaggi fuori ordine senza crescita illimitata;
- rimozione delle chiavi messaggio consumate dallo stato corrente.

Prima del primo contenuto utente, Kerberus completa un handshake autenticato senza contenuto in cui entrambi i peer contribuiscono nuove chiavi X25519 effimere. Il messaggio resta nel vault finché l’handshake non è terminato. In questo modo il primo payload applicativo non dipende soltanto da materiale ricostruibile dalle chiavi a lungo termine.

Il ratchet è progettato per forward secrecy classica e recupero post-compromissione dopo successivi passi DH onesti. Essendo basato su X25519, **non è post-quantum**. Kerberus non fornisce forward secrecy post-quantum.

### 5. Padding e protezione dai replay

Prima della cifratura, i payload vengono riempiti in classi grossolane basate su 512, 2.048, 8.192 o 32.768 byte. Il padding riduce la precisione dell’analisi delle lunghezze, ma non nasconde esistenza, direzione, tempistica o classe approssimativa del traffico.

I message ID sono valori casuali da 128 bit. Il vault mantiene un insieme limitato degli ID già elaborati; contatori ratchet e autenticazione AEAD impediscono che un replay venga accettato come nuovo contenuto.

### 6. Vault locale cifrato

Il vault conserva chiavi segrete dell’identità, contatti, messaggi, outbox, code di controllo, preferenze e stato ratchet.

- Salt casuale e Argon2id derivano una chiave vault da 256 bit dalla password.
- L’implementazione usa i limiti di operazioni e memoria Argon2id `MODERATE` di PyNaCl.
- L’intero stato serializzato è cifrato con XChaCha20-Poly1305.
- `KBV1` e salt vengono autenticati come associated data.
- Ogni scrittura usa un nonce casuale nuovo e sostituzione atomica tramite file temporaneo.
- È richiesta una password di almeno 10 caratteri.

La destination I2P privata persistente viene salvata separatamente perché SAM ne ha bisogno durante la creazione della sessione di trasporto. Kerberus la scrive atomicamente e applica i permessi `0600` su POSIX; su Windows eredita l’ACL della directory profilo dell’utente. Non è cifrata dalla password del vault.

Python non garantisce la cancellazione sicura degli oggetti immutabili, quindi copie delle chiavi possono restare nella memoria del processo fino al recupero da parte del runtime.

## Metadati e privacy

Kerberus non invia intenzionalmente telemetria, crash report, analytics, rubriche, cronologia o chiavi a un servizio gestito dal progetto. Nell’architettura corrente tale servizio non esiste.

Le riduzioni dei metadati applicativi includono:

- identificatori casuali per messaggi e richieste;
- classi di padding del plaintext;
- ricevute di consegna, lettura e reazioni cifrate;
- nuova incapsulazione ibrida e nuovo nonce per envelope;
- inoltro senza metadati del mittente o della conversazione originale;
- diagnostica UI locale che esclude il contenuto dei messaggi, salvo export esplicito della chat.

Queste misure non eliminano tutti i metadati. Router I2P locale, sistema operativo, peer e osservatori sufficientemente capaci possono ancora osservare o dedurre tempistiche, volume, periodi online, riutilizzo della destination e relazioni di comunicazione.

## Controlli privacy

Le impostazioni globali e per chat comprendono:

- ricevute di consegna;
- ricevute di lettura;
- notifiche desktop;
- anteprime link esterne;
- durata e uso singolo dei codici contatto.

### Anteprime link

Le anteprime sono disattivate per impostazione predefinita. Quando abilitate, Kerberus può contattare direttamente un sito clearnet per scaricare metadata HTML/Open Graph e un’immagine di dimensione limitata. L’implementazione:

- accetta soltanto HTTP e HTTPS;
- rifiuta credenziali incluse negli URL;
- blocca localhost, `.local`, `.internal`, `.i2p`, indirizzi privati, loopback, link-local e riservati;
- collega il socket direttamente all’IP pubblico già verificato per resistere al DNS rebinding;
- rivalida ogni redirect;
- limita numero di redirect, dimensioni e timeout;
- limita le anteprime a tre worker concorrenti.

Il sito può comunque osservare l’indirizzo IP clearnet del dispositivo e la tempistica della richiesta. Le anteprime non passano attraverso I2P e devono restare disabilitate se questa esposizione non è accettabile.

## Diagnostica e misurazione dei ritardi

La console UI locale registra eventi di protocollo e interfaccia senza memorizzare intenzionalmente il testo dei messaggi. Gli errori di connessione riportano tipo di eccezione e contesto.

Ogni conversazione può essere esportata in un file JSON scelto dall’utente contenente:

- cronologia completa in plaintext;
- direzione e stato dei messaggi;
- message ID e reazioni;
- timestamp di invio, ricezione locale, ricezione peer, consegna e lettura;
- calcoli one-way, round-trip e ritardo di lettura;
- diagnostica delle code.

Chiavi private, stato ratchet, payload cifrati e destination I2P del contatto sono esclusi. Il file esportato è intenzionalmente in chiaro e deve essere protetto dall’utente. Il ritardo one-way dipende dalla sincronizzazione degli orologi; il round-trip usa l’orologio locale del mittente ed è normalmente più affidabile.

## Installazione

### Requisiti

- Windows 10/11 x64 oppure Linux x86_64/aarch64 con ambiente desktop;
- connessione Internet e router I2P compatibile;
- Python 3.11+ soltanto per l’avvio dal sorgente;
- Go 1.24+ soltanto per creare gli artefatti;
- Java 17+ per il router I2P Java standard. Kerberus non usa direttamente Java.

### Release Windows

1. Scarica `KerberusInstaller.exe` dalla release desiderata.
2. Chiudi eventuali processi Kerberus precedenti.
3. Avvia l’installer e autorizza I2P/Java solo se necessari.
4. Avvia Kerberus, crea il vault cifrato e attendi **I2P: connesso**.

L’installer include applicazione e helper nativo. Può scaricare l’installer I2P 2.12.0 fissato e Azul Zulu JDK quando necessario, verifica SHA-256 prefissate, verifica il publisher Authenticode di Azul e configura SAM soltanto su loopback.

### Release Linux

1. Installa e avvia I2P dal repository della distribuzione o ufficiale.
2. Metti `Kerberus-linux-<arch>` e `install-linux.sh` nella stessa directory.
3. Esegui:

```bash
bash install-linux.sh
```

4. Avvia Kerberus dal menu applicazioni o con `~/.local/bin/kerberus`.

Kerberus salva la configurazione SAM utente in `~/.i2p/clients.config.d/`. Le installazioni I2P come servizio di sistema possono richiedere l’abilitazione di SAM dalla console router o nella directory prevista dalla distribuzione.

### Avvio dal sorgente

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

Ambiente virtuale manuale:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m kerberus.main
```

## Utilizzo di base

### Aggiungere un contatto

1. Entrambi gli utenti attendono lo stato I2P connesso.
2. Il destinatario apre **Profilo** e condivide il codice contatto corrente.
3. Il richiedente apre **Nuovo contatto**, inserisce il codice e può scrivere un primo messaggio.
4. La richiesta rimane visibile come pendente finché l’accettazione firmata non viene verificata.
5. Dopo l’handshake ratchet iniziale, il contenuto in coda viene cifrato e inviato.

La mailbox corrente è soltanto locale. In generale entrambi i peer devono essere online contemporaneamente: non esiste un relay Kerberus sempre attivo che conserva i messaggi offline.

### Errori di connessione

- **CANT_REACH_PEER** — il peer può essere offline o la LeaseSet non disponibile. Kerberus chiude soltanto quello stream e mantiene il messaggio nell’outbox cifrata.
- **INVALID_ID** — il router non riconosce più la sessione SAM. Kerberus esegue una ricostruzione coordinata per la generazione interessata.
- **SAM non disponibile** — verifica che I2P sia avviato e che `127.0.0.1:7656` sia raggiungibile.

Il primo avvio I2P può richiedere alcuni minuti per integrarsi nella rete e costruire i tunnel.

## Test

Suite locale completa:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v
```

Trasporto nativo:

```powershell
cd native
go test ./...
go vet ./...
```

Test end-to-end opzionale con due destination reali sul router locale:

```powershell
$env:KERBERUS_LIVE_I2P = "1"
.\.venv\Scripts\python.exe -m unittest tests.test_live_i2p -v
```

Il test live esegue lo scambio contatti, invia una raffica di dieci messaggi, verifica consegna e ordine e stampa statistiche di latenza.

## Creazione delle release

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

Gli artefatti vengono scritti in `release/`. GitHub Actions esegue test e build Windows/Linux e pubblica le release associate ai tag.

## Struttura del repository

```text
kerberus/
  crypto.py        identità, firme ed envelope ibrido
  ratchet.py       stato Double Ratchet e gestione chiavi messaggio
  service.py       contatti, messaggi, ricevute, reazioni, code e retry
  vault.py         persistenza locale cifrata
  sam.py           sessione SAM, stream, IPC helper e fallback Python
  link_preview.py  parsing metadata e download resistente a SSRF
  router.py        bootstrap, configurazione, avvio e arresto I2P
  updates.py       controllo release GitHub e verifica SHA-256
  ui.py            interfaccia PyQt6 e localizzazione
native/             multiplexer SAM in Go
installer.py        installer Windows
build_release.py    build PyInstaller
tests/              test crypto, service, UI, trasporto, updater e live
docs/adr/           decisioni architetturali
```

## Confini di sicurezza e limitazioni

- **Protocollo sperimentale:** Kerberus e il suo Double Ratchet non sono stati verificati formalmente né sottoposti ad audit indipendente.
- **Nessun anonimato assoluto:** I2P riduce l’esposizione di rete ma non elimina compromissione endpoint, correlazioni comportamentali, analisi temporale o rischi da osservatore globale.
- **Ibrido non significa interamente post-quantum:** ML-KEM contribuisce alla confidenzialità dell’envelope. Firme Ed25519 e Double Ratchet X25519 restano classici.
- **La compromissione dell’endpoint prevale:** malware, screenshot, monitoraggio appunti, lettura memoria o accesso al vault sbloccato possono esporre plaintext e chiavi.
- **Nessuna garanzia di cancellazione sicura:** snapshot, backup, SSD, swap e gestione memoria Python possono conservare dati precedenti.
- **Chiave I2P separata:** la destination privata SAM ha permessi ristretti ma non è cifrata dalla password del vault.
- **Disponibilità diretta:** non esiste una mailbox offline esterna; la consegna dipende dalla raggiungibilità dei peer e di I2P.
- **Esposizione anteprime:** le anteprime abilitate contattano siti clearnet e rivelano a questi l’IP clearnet del dispositivo.
- **Export in chiaro:** export diagnostici e appunti spostano intenzionalmente plaintext fuori dal vault.
- **Fiducia nelle release:** gli aggiornamenti richiedono manifest SHA-256 corrispondenti e rifiutano rollback, ma artefatto e checksum provengono dalla stessa release GitHub. Non esiste ancora una firma offline indipendente o un certificato code-signing del progetto.
- **Funzioni non implementate:** gruppi, sincronizzazione multi-device, allegati, voce/video, backup delle chiavi e mailbox distribuite.

## Licenze

Le icone Lucide in `kerberus/assets/lucide/` mantengono la licenza upstream inclusa nella directory. Le dipendenze di terze parti mantengono le rispettive licenze. Il repository attualmente non contiene un file `LICENSE` generale: non presumere una licenza open source per il resto del codice finché non verrà aggiunta.
