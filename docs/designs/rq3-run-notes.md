# Note del run principale RQ3

2026-11-19 · preregistrazione congelata a `ec7f7f4` · `claude-sonnet-5-5`, `effort=medium`,
`max_tokens=16000`, Message Batches API · 400 puzzle × 4 bracci + controllo `fen` su 100 × 2
= 1.800 risposte, 0 fallite, 0 troncate (tutte `stop_reason=end_turn`), 0 puzzle esclusi.

`results/` non è versionato: i numeri sotto sono copiati da `results/rq3/main_summary.md`
(rigenerabile con `python scripts/rq3.py analyse --set main` dalla cache).

## Costo reale

| Batch | Token medi in / out | Costo |
|---|---|---|
| `msgbatch_012QfrGBfhspdymwZcs1iujf` (11:30, usato) | 222 / 943 (mediana 964, max 2.175) | $8,88 |
| `msgbatch_01GMYg2jhPtnUe43atToHTz3` (11:31, **duplicato**) | 222 / 948 | $8,93 |
| pilota `msgbatch_01KNRxgpZ1kkHKhErxF94Zff` (27/10) | 233 / 940 | $0,79 |

$0,0049 a richiesta, identico al pilota: la proiezione di $8,88 era esatta.
Speso in totale su RQ3: **$18,60** (sarebbero stati $9,67 senza il duplicato), sotto il tetto di $50.

**Il duplicato.** Il submit del principale è partito due volte a un minuto di distanza, una
dal terminale dell'utente e una da Claude Code. Il secondo `submit` ha visto 1.800 richieste
"non ancora in cache" perché il primo batch era inviato ma non raccolto, e `submit` non
guardava `results/llm_batches.jsonl`. Le risposte del duplicato sono state scartate in
`collect` (chiavi già in cache): l'analisi usa solo il primo batch. Correzione: `submit`
(in `llm_batch.py` e `rq3.py`) ora si rifiuta se esiste un batch non raccolto con lo
stesso namespace (`--force` per forzare), e il dry-run lo segnala.

## Esito preregistrato

> **Sa cosa cercare solo se glielo dici: il collo di bottiglia è dove guardare.**
> L'effetto di un motivo sbagliato non è distinguibile con 400 puzzle.

| Misura | Valore |
|---|---|
| Motivo riconosciuto (`theme_only`) | 31,5% [27,1–36,2], pavimento 10% |
| Mossa trovata, `move_only` | 37,2% [32,7–42,1], livello basso; `random` 5,5% |
| Mossa trovata, `hint_true` / `hint_false` | 47,8% / 35,2% |
| D_true = hint_true − move_only | +10,5 punti [+5,5, +15,5], grande positivo |
| D_false = hint_false − move_only | −2,0 punti [−7,0, +3,0], inconclusivo |
| Riconosce il motivo e sbaglia la mossa | 15,8% [12,5–19,6] |
| Mosse illegali (move_only / hint_true / hint_false) | 8,5% / 5,5% / 9,8% |
| D_true se il motivo era / non era riconosciuto (descrittivo) | +12,7 [+4,7, +21,4] / +9,5 [+3,3, +15,7] |
| D_true senza `hangingPiece` (descrittivo) | +10,8 [+5,5, +16,1] |
| Controllo `fen` (100 puzzle, descrittivo) | motivo 35,0%, mossa 39,0% |

## Per tema (descrittivo, 40 puzzle per tema, rumore ±15 punti)

| Tema | Riconosciuto | move_only | hint_true | hint_false | D_true |
|---|---|---|---|---|---|
| doubleCheck | 25 | 38 | 68 | 22 | +30 |
| skewer | 20 | 32 | 50 | 35 | +18 |
| pin | 42 | 22 | 38 | 30 | +15 |
| discoveredAttack | 50 | 32 | 45 | 35 | +12 |
| trappedPiece | 25 | 38 | 50 | 38 | +12 |
| interference | 2 | 15 | 25 | 18 | +10 |
| hangingPiece | 55 | 72 | 80 | 68 | +8 |
| sacrifice | 32 | 35 | 38 | 30 | +3 |
| fork | 52 | 45 | 48 | 40 | +2 |
| deflection | 10 | 42 | 38 | 38 | −5 |

Temi detti in `theme_only`: discoveredAttack 77, fork 73, hangingPiece 69, pin 56,
sacrifice 51, deflection 35, trappedPiece 13, skewer 12, doubleCheck 11, interference 3.

## Lettura

- "Capisce, non calcola" non regge: riconosce il motivo sopra il caso ma poco (31,5%), e
  sentirsi dire il motivo giusto vale +10 punti sulla mossa. L'effetto non viene da
  `hangingPiece` e c'è anche quando il motivo era già riconosciuto.
- Il guadagno è sui motivi geometrici (scacco doppio, infilata, inchiodatura); quasi nullo
  su fork e sacrifice, che il modello nomina già spesso. Le etichette dette sono sbilanciate
  (tre temi = 55% delle risposte): parte del 31,5% è calibrazione delle etichette.
- Un motivo sbagliato non costa in modo misurabile, ma con ±5 punti non si può nemmeno dire
  che lo ignori.

**Limiti.** Il risultato è modesto e non autorizza conclusioni su *come* il modello ragioni:
misuriamo risposte, non processi. Il ragionamento è nel testo (thinking esteso non attivo),
un solo modello, un solo effort.

## Prossimo passo proposto

Ripetere i quattro bracci su modelli diversi (per esempio un modello più piccolo e uno di
fascia più alta, più effort diversi), per vedere se D_true e il riconoscimento del motivo
cambiano con la capacità del modello. Va preregistrato come RQ a parte: nuovo budget,
stessi 400 puzzle, cache con namespace per modello.
