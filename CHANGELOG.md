# Changelog

## 0.7.0

- Modalità I2P opzionale a bassa latenza con tunnel da 2 hop, ACK immediato, conferma incorporata e preparazione configurabile dei contatti recenti.
- Dispatcher Go concorrente tra contatti e FIFO per singola destination, con benchmark e misure separate per IPC Python/Go, handshake SAM, apertura stream I2P e ricevuta cifrata.
- Reazioni multiple per partecipante, chip aggregati e rimozione della propria reazione con clic sinistro; avvertenza esplicita sul compromesso privacy/prestazioni degli stream recenti preparati.
- Mascheramento opzionale della recency nel warm-up: campionamento casuale di un massimo di 8 contatti reali, con avvertenza che non può falsificare le destination visibili a SAM.

## 0.6.0

- Nuova cronologia chat virtualizzata con scrollbar stabile e scorrimento fluido su conversazioni lunghe.
- Bolle adattive alla lunghezza del contenuto, messaggi emoji compatti e chip moderni per le reazioni.
- Anteprime link complete con immagini e URL cliccabili protetti da una conferma di sicurezza interna.
- Selettore emoji, profilo contatto e impostazioni conversazione integrati nella finestra principale.
- Rework completo delle impostazioni, dropdown personalizzati e localizzazione italiana/inglese estesa.
- Visibilità dell'Identity ID configurabile per contatto.
- Protezione streaming Windows e privacy curtain Linux.
- Diagnostica automatica dei peer I2P con dettagli geografici e lista richiudibile.
- Packaging 0.6.0 centralizzato e pipeline unica per binari Windows/Linux, wheel, sdist e archivio sorgente.
