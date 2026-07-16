# ADR 0003 — Messaggi vocali privati con codec Go

## Stato

Accettata per Kerberus 0.8.0.

## Decisione

- I vocali sono messaggi asincroni, non chiamate in tempo reale.
- Qt Multimedia acquisisce il formato nativo del microfono e riproduce un WAV locale in memoria.
- Il helper Go converte input `u8`, `s16le`, `s32le` o `f32le`, esegue downmix e ricampionamento lineare a 16 kHz mono e applica IMA-ADPCM a 4 bit per campione.
- Il contenitore `KVA1` include frequenza, numero di campioni, predittore e indice IMA. Il decoder rifiuta contenitori incoerenti e output oltre 120 secondi.
- Il payload codificato viene inserito nel Double Ratchet v3, poi nell’envelope ibrido X25519 + ML-KEM-768 già firmato e cifrato. Solo il frame cifrato raggiunge SAM/I2P.
- I bucket di padding più grandi sono limitati affinché il frame finale resti sotto il limite SAM di 4 MB.
- Il vault conserva il vocale e l’outbox cifrati. L’export diagnostico omette sempre il contenuto audio.

## Motivazioni

IMA-ADPCM offre compressione 4:1, costo CPU prevedibile, implementazione Go senza dipendenze native e pacchetti riproducibili sulle piattaforme già supportate. Opus offrirebbe un bitrate inferiore, ma introdurrebbe una libreria nativa aggiuntiva, packaging CGo e una superficie di aggiornamento separata. Il formato è versionato per permettere un codec futuro senza reinterpretare i messaggi esistenti.

## Privacy e limiti

La cifratura protegge il contenuto e I2P nasconde gli indirizzi di rete diretti nelle condizioni previste dal suo modello. Dimensione, durata e tempistica restano metadati osservabili; i vocali producono inoltre pattern più riconoscibili del testo. L’interfaccia lo dichiara prima del primo utilizzo della sessione. “Privato” non significa anonimato assoluto e non protegge un endpoint compromesso o un microfono controllato da altro software locale.
