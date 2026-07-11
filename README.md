# Kerberus

Kerberus è un messenger desktop sperimentale che comunica attraverso I2P usando SAM v3. L'applicazione è scritta in Python con PyQt6 e conserva identità, contatti e cronologia in un vault locale cifrato.

> Kerberus è ancora un progetto in sviluppo e non è stato sottoposto a un audit di sicurezza indipendente. Non promette anonimato assoluto e non deve ancora essere usato per proteggere persone o dati ad alto rischio.

## Funzionalità

- Interfaccia desktop PyQt6 senza cornice Windows standard.
- Router I2P 2.12.0 tramite SAM v3 su `127.0.0.1:7656`.
- Installazione automatica di I2P e, quando necessario, Azul Zulu JDK 26.
- Identità self-sovereign firmate con Ed25519.
- Cifratura messaggi ibrida X25519 + ML-KEM-768.
- Payload protetti con XChaCha20-Poly1305.
- Codici contatto monouso che cambiano ogni minuto.
- Username e foto profilo firmati.
- Cronologia e outbox salvate nel vault cifrato.
- ACK firmati, anti-replay e retry automatici.
- Stream I2P persistenti e riutilizzati tra contatti per ridurre la latenza.
- Messaggi mostrati immediatamente nella UI prima della consegna di rete.

## Come funziona

```text
PyQt6 UI
   |
MessengerService
   |-- Vault cifrato (Argon2id + XChaCha20-Poly1305)
   |-- Identità e protocollo E2EE
   `-- SamClient
          |
          `-- I2P Router 2.12.0 / SAM 127.0.0.1:7656
```

Kerberus mantiene una destination I2P persistente per profilo. Il codice contatto contiene l'indirizzo `.b32.i2p` derivato dalla destination, più un token temporaneo verificabile soltanto dal proprietario. Quando la richiesta viene accettata, i due client si scambiano i profili pubblici firmati e creano la conversazione.

Ogni messaggio viene cifrato per il destinatario e salvato localmente prima dell'invio. Se il peer o la sua LeaseSet non sono raggiungibili, il messaggio resta nella outbox cifrata e viene ritentato con backoff. Un ACK Ed25519 valido lo marca come consegnato.

Per diminuire la latenza, la sessione SAM e gli stream già aperti verso i contatti rimangono attivi. Kerberus usa tre tunnel in ingresso e uscita, un tunnel di backup e il profilo streaming interattivo. Queste impostazioni seguono le indicazioni delle documentazioni ufficiali [SAM v3](https://i2p.net/en/docs/api/samv3/), [I2CP](https://i2p.net/en/docs/specs/i2cp-overview/) e [Streaming](https://i2p.net/en/docs/api/streaming/).

## Requisiti

- Windows 10 o Windows 11 a 64 bit.
- Connessione Internet.
- Per lo sviluppo: Python 3.11 o successivo.
- Per I2P: Java 17 o successivo. L'installer può installare Azul Zulu JDK 26.0.1+8.

## Installazione per utenti

1. Chiudi eventuali versioni precedenti di Kerberus.
2. Avvia `KerberusInstaller.exe`.
3. Accetta l'installazione di Java o I2P quando richiesta.
4. Avvia Kerberus dal desktop o dal menu Start.
5. Crea il vault e attendi lo stato **I2P: connesso**.

L'installer scarica I2P 2.12.0 dal sito ufficiale e verifica la SHA-256 fissata nel codice. SAM viene configurato soltanto su loopback.

## Avvio dal sorgente

Apri PowerShell nella cartella del progetto:

```powershell
.\setup.ps1
.\start.ps1
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
5. Dopo la conferma firmata, la chat appare su entrambi i client.

Mittente e destinatario devono essere online contemporaneamente per la consegna. L'attuale outbox è locale: non esiste ancora una mailbox I2P esterna sempre attiva.

## Stati dei messaggi

- **In attesa**: salvato nel vault, ancora da inviare.
- **Inviato**: scritto nello stream I2P, ACK non ancora ricevuto.
- **Consegnato**: ACK firmato ricevuto dal destinatario.

Un errore `CANT_REACH_PEER` non distrugge la sessione SAM: viene riaperto soltanto lo stream del contatto e il messaggio resta in coda. Un errore `INVALID_ID` causa una sola ricostruzione coordinata della sessione se la sua generazione è ancora quella guasta.

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

## Struttura del repository

```text
kerberus/
  crypto.py       identità, firme e cifratura ibrida
  sam.py          sessione SAM, stream persistenti e recovery
  service.py      contatti, messaggi, ACK, outbox e retry
  vault.py        persistenza locale cifrata
  router.py       avvio, arresto e bootstrap I2P
  ui.py           interfaccia PyQt6
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
- Non è ancora presente un Double Ratchet completo, quindi il progetto non offre ancora le stesse proprietà di post-compromise recovery dei messenger maturi.
- Non sono ancora implementati gruppi, multi-device, allegati o mailbox distribuite.
- La protezione dei metadati dipende anche dal router I2P, dal sistema operativo e dal comportamento dell'utente.
- Le release non sono ancora firmate con un certificato di code signing.

## Licenze

Le icone Lucide incluse in `kerberus/assets/lucide/` mantengono la loro licenza originale, disponibile nello stesso percorso. Le altre dipendenze conservano le rispettive licenze upstream.
