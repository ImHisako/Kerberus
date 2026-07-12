# Kerberus

Kerberus è un messenger desktop sperimentale che comunica attraverso I2P usando SAM v3. L'applicazione è scritta in Python con PyQt6 e conserva identità, contatti e cronologia in un vault locale cifrato.

> Kerberus è ancora un progetto in sviluppo e non è stato sottoposto a un audit di sicurezza indipendente. Non promette anonimato assoluto e non deve ancora essere usato per proteggere persone o dati ad alto rischio.

## Funzionalità

- Interfaccia desktop PyQt6 senza cornice di sistema su Windows e Linux.
- Router I2P 2.12.0 tramite SAM v3 su `127.0.0.1:7656`.
- Installazione automatica di I2P e, quando necessario, Azul Zulu JDK 26.
- Identità self-sovereign firmate con Ed25519.
- Cifratura messaggi ibrida X25519 + ML-KEM-768.
- Payload protetti con XChaCha20-Poly1305.
- Double Ratchet v2 persistente con ratchet DH X25519, cancellazione delle chiavi usate e supporto limitato ai messaggi fuori ordine.
- Codici contatto con rotazione configurabile (1, 5, 15 o 60 minuti) e opzione monouso.
- Impostazioni integrate e console UI locale con log delle azioni privo di contenuti dei messaggi.
- Username e foto profilo firmati.
- Cronologia e outbox salvate nel vault cifrato.
- ACK firmati, anti-replay e retry automatici.
- Ricevute di consegna e lettura cifrate end-to-end, disattivabili globalmente o per chat.
- Spunte di stato, reazioni cifrate, selettore emoji, impostazioni per chat e tray desktop.
- Esportazione diagnostica per chat in JSON con cronologia completa, timestamp, stati, reazioni e delay; chiavi e stato ratchet sono esclusi.
- Anteprime link opzionali con metadata Open Graph, miniature e apertura esplicita; disattivate per impostazione predefinita.
- Stream I2P persistenti e riutilizzati tra contatti per ridurre la latenza.
- Helper nativo Go incluso nelle release per multiplexare invio, ricezione e ACK sugli stream SAM senza richiedere Go sul PC dell'utente.
- Apertura stream 0-RTT: il primo frame può viaggiare nel SYN I2P Streaming.
- Messaggi mostrati immediatamente nella UI prima della consegna di rete.
- Controllo aggiornamenti GitHub Releases con anti-rollback e verifica SHA-256.
- Menu contestuale dei messaggi per copiare, eliminare localmente o inoltrare con una nuova cifratura.

## Come funziona

```text
PyQt6 UI
   |
MessengerService
   |-- Vault cifrato (Argon2id + XChaCha20-Poly1305)
   |-- Identità e protocollo E2EE
   `-- SamClient
          |-- helper Go nativo (CONNECT, ACCEPT, frame e ACK)
          |-- listener Python avviato solo come fallback automatico
          |
          `-- I2P Router 2.12.0 / SAM 127.0.0.1:7656
```

Kerberus mantiene una destination I2P persistente per profilo. Il codice contatto contiene l'indirizzo `.b32.i2p` derivato dalla destination, più un token temporaneo verificabile soltanto dal proprietario. Quando la richiesta viene accettata, i due client si scambiano i profili pubblici firmati e creano la conversazione.

Ogni messaggio viene cifrato per il destinatario e salvato localmente prima dell'invio. Se il peer o la sua LeaseSet non sono raggiungibili, il messaggio resta nella outbox cifrata e viene ritentato con backoff breve. Una ricevuta cifrata e autenticata lo marca come consegnato.

Per diminuire la latenza, la sessione SAM e gli stream già aperti verso i contatti rimangono attivi. `SILENT=true` e un breve `connectDelay` permettono al primo frame di essere incluso nel SYN, evitando un round-trip applicativo. Kerberus usa tre tunnel in ingresso e uscita, un tunnel di backup e il profilo streaming interattivo. Non riduce la lunghezza dei tunnel per guadagnare velocità, perché cambierebbe il compromesso di anonimato. Queste impostazioni seguono le indicazioni delle documentazioni ufficiali [SAM v3](https://i2p.net/en/docs/api/samv3/), [I2CP](https://i2p.net/en/docs/specs/i2cp-overview/) e [Streaming](https://i2p.net/en/docs/api/streaming/).

## Requisiti

- Windows 10/11 a 64 bit oppure Linux x86_64/aarch64 con ambiente desktop.
- Connessione Internet.
- Per lo sviluppo: Python 3.11 o successivo.
- Solo per creare gli artefatti di release: Go 1.24 o successivo.
- Per il router I2P standard: Java 17 o successivo. Kerberus non usa direttamente Java e l'installer lo aggiunge solo quando deve installare o aggiornare quel router.

## Installazione per utenti

### Windows

1. Chiudi eventuali versioni precedenti di Kerberus.
2. Avvia `KerberusInstaller.exe`.
3. Accetta l'installazione di I2P e, solo se necessario al router standard, di Java.
4. Avvia Kerberus dal desktop o dal menu Start.
5. Crea il vault e attendi lo stato **I2P: connesso**.

`Kerberus.exe` e `KerberusInstaller.exe` includono Python, dipendenze native e helper Go: l'utente non deve installare Python o Go.

L'installer scarica I2P 2.12.0 dal sito ufficiale e verifica la SHA-256 fissata nel codice. SAM viene configurato soltanto su loopback.

La documentazione I2P distingue il pacchetto Windows standard, che richiede Java, dall'Easy Install Bundle che include un runtime privato. Questa release usa il pacchetto standard per mantenere l'integrazione con `I2Psvc.exe`; se I2P 2.12.0 è già presente, non scarica né installa Java.

### Linux

1. Installa I2P dal repository ufficiale della distribuzione e avvialo come utente con `i2prouter start`.
2. Scarica `Kerberus-linux-<arch>` e `install-linux.sh` nella stessa cartella.
3. Esegui `bash install-linux.sh`.
4. Avvia Kerberus dal menu applicazioni o con `~/.local/bin/kerberus`.

Kerberus configura SAM in `~/.i2p/clients.config.d/` e lo mantiene su `127.0.0.1:7656`. Per installazioni I2P gestite come servizio di sistema potrebbe essere necessario abilitare SAM dalla console router o nella directory configurata dalla distribuzione.

## Build automatica

Il workflow GitHub Actions `.github/workflows/build.yml` esegue test e build sia su Windows sia su Linux. Produce installer Windows, binario Linux standalone, installer utente Linux e checksum; sui tag `v*` pubblica gli artefatti nella GitHub Release.

All'avvio Kerberus controlla in background la release stabile più recente. Non accetta downgrade, scarica l'artefatto specifico della piattaforma e lo rende disponibile soltanto se la SHA-256 coincide con il manifest della stessa release. L'installazione richiede sempre una conferma esplicita; le release non hanno ancora una firma di code signing indipendente, quindi una compromissione dell'account o del workflow GitHub resta nel modello di minaccia.

## Avvio dal sorgente

Apri PowerShell nella cartella del progetto:

```powershell
.\setup.ps1
.\start.ps1
```

Su Linux:

```bash
# Debian/Ubuntu, solo per l'avvio dal sorgente:
sudo apt install python3-venv
bash setup.sh
bash start.sh
```

In alternativa:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m kerberus.main
```

## Aggiungere un contatto

1. Entrambi gli utenti devono attendere **I2P: connesso**.
2. Il destinatario apre il proprio profilo e genera il codice contatto.
3. Il mittente inserisce il codice tramite il pulsante per aggiungere un contatto.
4. Il codice visualizzato cambia ogni minuto ed è monouso; le ritrasmissioni tecniche dello stesso mittente restano idempotenti.
5. La richiesta appare come **Richiesta in attesa**. La conferma firmata torna sullo stesso stream I2P full-duplex e, solo dopo la verifica, la chat diventa utilizzabile su entrambi i client.

Mittente e destinatario devono essere online contemporaneamente per la consegna. L'attuale outbox è locale: non esiste ancora una mailbox I2P esterna sempre attiva.

## Stati dei messaggi

- **In attesa**: salvato nel vault, ancora da inviare.
- **Inviato**: scritto nello stream I2P, ricevuta non ancora ricevuta.
- **Consegnato**: ricevuta cifrata ricevuta dal destinatario.
- **Letto**: ricevuta cifrata di lettura ricevuta; le doppie spunte diventano azzurre.

Un errore `CANT_REACH_PEER` non distrugge la sessione SAM: viene riaperto soltanto lo stream del contatto e il messaggio resta in coda. Un errore `INVALID_ID` causa una sola ricostruzione coordinata della sessione se la sua generazione è ancora quella guasta.

Con il tasto destro su una bolla è possibile copiare il testo, cancellare la sola copia locale oppure inoltrarlo. L'inoltro crea un nuovo messaggio cifrato senza allegare l'identità del mittente originale. La cancellazione non può rimuovere copie già consegnate all'altro dispositivo.

## Test

Suite completa:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v
```

Test end-to-end con due destination reali sul router I2P locale:

```powershell
$env:KERBERUS_LIVE_I2P = "1"
.\.venv\Scripts\python.exe -m unittest tests.test_live_i2p -v
```

## Creare la release Windows

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[build]"
.\.venv\Scripts\python.exe .\build_release.py
```

Gli artefatti vengono prodotti in `release/`:

- `Kerberus.exe`: applicazione standalone.
- `KerberusInstaller.exe`: installer con applicazione inclusa.
- `SHA256SUMS.txt`: impronte degli eseguibili generate per la release locale.

## Creare la release Linux

```bash
.venv/bin/python -m pip install -e '.[build]'
.venv/bin/python build_release.py
```

Produce `Kerberus-linux-<arch>`, `install-linux.sh` e `SHA256SUMS-linux.txt`.

Durante la build viene compilato `native/kerberus-native`; il binario è poi incorporato nell'eseguibile PyInstaller. Go mantiene tre `STREAM ACCEPT` pendenti, riusa gli stream in uscita e registra anche gli stream ricevuti come canali full-duplex per le risposte, evitando un secondo handshake nella direzione opposta. I callback applicativi passano attraverso una coda ordinata separata, così un messaggio ricevuto può causare immediatamente un nuovo invio senza bloccare il lettore IPC. Se l'helper non può essere avviato o termina, Kerberus avvia automaticamente il trasporto Python mantenendo lo stesso protocollo e la stessa outbox.

## Struttura del repository

```text
kerberus/
  crypto.py       identità, firme e cifratura ibrida
  sam.py          sessione SAM, stream persistenti e recovery
  service.py      contatti, messaggi, ACK, outbox e retry
  vault.py        persistenza locale cifrata
  router.py       avvio, arresto e bootstrap I2P
  ui.py           interfaccia PyQt6
  updates.py      update check, download e verifica GitHub Releases
native/            multiplexer SAM persistente in Go
installer.py      installer Windows
build_release.py  build PyInstaller
tests/            test unitari, UI e integrazione I2P
```

## Risoluzione problemi

### I2P non connesso

- Verifica che I2P 2.12.0 sia avviato.
- Verifica che `127.0.0.1:7656` sia raggiungibile.
- Apri lo stato I2P nell'app e usa **Riconnetti**.
- Il primo avvio può richiedere alcuni minuti per integrare il router e costruire i tunnel.

### CANT_REACH_PEER

Il peer può essere offline, avere tunnel non ancora pubblicati oppure aver appena riavviato I2P. Il messaggio rimane cifrato nella outbox e viene ritentato automaticamente senza abbattere la sessione principale.

### INVALID_ID

Indica che SAM non riconosce più la sessione. Kerberus coordina una singola ricostruzione della sessione e chiude gli stream appartenenti alla vecchia generazione. Errori ripetuti possono indicare un riavvio del router o SAM non stabile.

### La chat mostra anteprime ma non bolle

Aggiorna entrambi i client alla stessa versione indicata nella finestra **Stato I2P**. La cronologia è nel vault e viene renderizzata nuovamente dopo l'aggiornamento.

## Sicurezza e limiti

- La destination privata SAM è persistente e salvata separatamente dal vault perché serve per creare la sessione prima del traffico applicativo.
- Il Double Ratchet cancella le chiavi consumate e rinnova le catene dopo i cambi DH. Il protocollo è nuovo, non interoperabile con la 0.3 per i nuovi messaggi e non è stato sottoposto a audit indipendente.
- Non sono ancora implementati gruppi, multi-device, allegati o mailbox distribuite.
- La protezione dei metadati dipende anche dal router I2P, dal sistema operativo e dal comportamento dell'utente.
- Kerberus non raccoglie telemetria. Padding a bucket, identificatori casuali, chiavi effimere e ricevute cifrate riducono i metadati applicativi, ma non possono nascondere ogni correlazione temporale a un avversario globale.
- Le anteprime link contattano il sito solo quando la relativa opzione è attiva. Download limitati, timeout, controllo dei redirect e blocco di host locali/privati riducono i rischi SSRF, ma il sito può osservare l'indirizzo IP del dispositivo. Kerberus non offre configurazioni DNS proprie.
- Le release non sono ancora firmate con un certificato di code signing.

## Licenze

Le icone Lucide incluse in `kerberus/assets/lucide/` mantengono la loro licenza originale, disponibile nello stesso percorso. Le altre dipendenze conservano le rispettive licenze upstream.
