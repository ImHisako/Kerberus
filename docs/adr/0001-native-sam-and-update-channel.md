# ADR 0001 — Trasporto SAM nativo e canale aggiornamenti

Data: 2026-07-12

## Decisione

Le release includono un helper Go a dipendenze zero che gestisce `STREAM CONNECT`,
`STREAM ACCEPT`, frame in entrambe le direzioni e risposte sullo stesso stream. Identità, chiavi, vault e primitive E2EE restano nel processo
principale e nelle librerie crittografiche già adottate. In assenza dell'helper il
client usa automaticamente il percorso Python interoperabile.

Gli stream usano `SILENT=true` e `i2p.streaming.connectDelay=125` per consentire il
trasporto del primo frame nel SYN. La consegna è attestata soltanto dall'ACK E2EE;
una scrittura riuscita sul socket locale non viene presentata come consegna.

Il client controlla esclusivamente la release GitHub stabile più recente, rifiuta
versioni non superiori a quella installata e richiede che artefatto e manifest
SHA-256 siano entrambi presenti. L'applicazione non installa nulla senza conferma.

## Conseguenze e limiti

- Si elimina un round-trip durante l'apertura normale dello stream.
- Tre acceptor nativi restano pendenti e vengono rimpiazzati appena SAM consegna una
  connessione; i comandi IPC sono smistati su code dinamiche per destination. Ogni
  contatto conserva l'ordine FIFO, mentre contatti diversi avanzano in parallelo.
- Le risposte IPC includono tempi separati per attesa in coda, handler Go, handshake
  SAM locale e scrittura del comando CONNECT. Il client misura anche round-trip e
  overhead IPC Python↔Go, mentre un cronometro monotono associa invio e ricevuta E2EE.
- Il tempo reale di apertura I2P non è deducibile da `SILENT=true`: il benchmark live
  apre quindi uno stream usa-e-getta con `SILENT=false` e misura `STREAM STATUS`, senza
  modificare il percorso di produzione.
- Ogni stream accettato viene riusato come canale full-duplex per messaggi e controlli
  nella direzione opposta, evitando un secondo handshake I2P Streaming.
- Gli stream restano caldi e vengono riutilizzati; aumenta leggermente il traffico di
  keepalive e l'uso di risorse del router.
- Non viene ridotta la lunghezza dei tunnel I2P e non cambia il protocollo E2EE.
- La SHA-256 protegge da corruzione e mismatch, ma il manifest proviene dallo stesso
  account GitHub. Finché gli artefatti non sono firmati con una chiave offline o un
  certificato verificato, la compromissione del canale di release resta un rischio.
- Copiare e inoltrare espone plaintext soltanto su azione locale esplicita; inoltrare
  produce un envelope nuovo e non trasmette metadati del mittente originale.
