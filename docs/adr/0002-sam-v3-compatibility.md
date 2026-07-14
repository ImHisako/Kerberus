# ADR 0002: compatibilità SAM v3 e I2P Streaming

## Stato

Accettato per Kerberus 0.4.

## Riferimenti normativi

- SAM v3: https://i2p.net/en/docs/api/samv3/
- Streaming: https://i2p.net/en/docs/api/streaming/
- Opzioni I2CP: https://i2p.net/en/docs/specs/i2cp-overview/
- Tunnel: https://i2p.net/en/docs/specs/tunnel-implementation/

## Decisioni

- Kerberus mantiene una sola sessione SAM longeva per profilo e stream persistenti per peer.
- L'ID SAM è casuale e `SIGNATURE_TYPE=7` viene usato durante `DEST GENERATE`; non viene inviato erroneamente con una destination privata persistente.
- La LeaseSet usa `i2cp.leaseSetEncType=6,4`, supportata dal router Java incluso e richiesta dalla documentazione corrente per ML-KEM-768 con fallback ECIES-X25519.
- `STREAM ACCEPT SILENT=false` conserva la destination remota e permette più accept pendenti sulle implementazioni SAM correnti.
- `STREAM CONNECT SILENT=true` consente di scrivere subito il primo frame. Questo non costituisce una conferma di connessione o consegna: Kerberus considera autorevoli solo le risposte applicative cifrate.
- La conferma di un contatto torna sullo stesso stream bidirezionale. La coda su un secondo stream resta solo come fallback per chiamate non-inline.
- `connectDelay=125` permette il payload nel SYN; `initialAckDelay=25`, profilo interattivo e keepalive a 30 secondi privilegiano la latenza senza ridurre lunghezza o anonimato dei tunnel.
- Quantità 3 e backup 1 sono nei range raccomandati. Il profilo standard usa 3 hop; zero-hop è vietato e non sono selezionati peer espliciti.
- La modalità opzionale a bassa latenza ricrea la stessa sessione persistente con tunnel in ingresso e uscita da 2 hop, varianza 0 e ACK iniziale immediato. Quantità 3 e backup 1 restano invariati e zero-hop è sempre vietato. L'interfaccia richiede una conferma incorporata che avverte esplicitamente della minore resistenza alla correlazione del traffico.
- SAM richiede una destination reale per `STREAM CONNECT`, quindi Kerberus non dichiara di falsificare questi metadati. L'opzione di mascheramento del warm-up campiona casualmente fino a 8 contatti reali al posto della cronologia recente: nasconde la recency semplice, ma non la destination al router locale e può rendere visibile una connessione ai contatti campionati.
- La preparazione anticipata di un massimo di otto contatti recenti è configurabile. Riduce il tempo del primo invio riutilizzando stream persistenti, al costo di traffico e metadati di connessione in background.
- SAM rimane esclusivamente su loopback. L'assenza di TLS/autenticazione SAM non è accettabile se il bridge viene esposto su rete.

## Compatibilità e limiti

- Gli indirizzi b32 in `STREAM CONNECT` richiedono Java I2P 0.9.48+ o i2pd 2.38.0+.
- Gli accept concorrenti richiedono Java I2P 0.9.24+ o i2pd 2.50.0+ quando viene negoziato SAM 3.1.
- `i2cp.leaseSetEncType=6,4` richiede API I2P 0.9.67+; Kerberus distribuisce e verifica una versione compatibile del router Java.
- La documentazione I2P raccomanda test anche con perdita, jitter e latenze fino ad almeno 15 secondi. I test unitari coprono retry, duplicati e messaggi fuori ordine; il test live richiede un router locale ed è opt-in.
