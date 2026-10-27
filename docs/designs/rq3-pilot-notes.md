# Note del pilota RQ3

2026-10-27 · batch `msgbatch_01KNRxgpZ1kkHKhErxF94Zff` · 40 puzzle × 4 bracci = 160 risposte,
0 fallite. I numeri del pilota **non** entrano nell'analisi (puzzle disgiunti dai 400).

## Costo reale

Token reali dal batch: input medio 233, output medio 940 (mediana 948, max 1.895).
Costo del pilota: **$0,79** ($0,0049 a richiesta), contro i ~$2 stimati con
l'ipotesi di 2.500 token di output. Proiezione del principale (1.800 richieste):
**~$8,88**, sotto la regola di stop di $45.

## Cosa ho letto

- Tutte le 120 risposte sulla mossa e le 40 sul tema, per formato e mossa estratta.
- Per intero: 6jIif (`hint_true`) e 2Hg9w (`hint_true`).

## Problemi trovati

1. **Bug del parser (corretto, emendamento 2).** Il modello ignora "nothing else":
   ragiona per esteso nel testo (risposte di 1.400-2.700 caratteri) e chiude con le
   righe `MOVE:` / `WHY:` o `THEME:`. Le 120 risposte sulla mossa hanno tutte la
   riga `MOVE:` finale, ma solo 3 iniziano con essa; nessuna delle 40 sul tema
   inizia con `THEME:`. Il parser prendeva la *prima* occorrenza di "move:"
   anche dentro il ragionamento ("…g6 is the thematic move: the queen…" → mossa
   `the`). Effetto: mosse "illegali" 7,5% / 22,5% / 10,0% (move_only / hint_true /
   hint_false), scese a 7,5% / 2,5% / 2,5% leggendo l'ultima riga `MOVE:`. In
   2Hg9w la risposta finale era proprio la soluzione (`g6`).
2. **Mosse illegali rimaste (5): errori veri del modello.** Mosse impossibili nella
   posizione (`Rxh4`, `Qxd1#`, `Rxc5`, `Rxg3+`) e un `Nxd4` ambiguo (due cavalli
   possono catturare): per la regola preregistrata sono sbagliate.
3. **Distribuzione dei temi detti.** sacrifice 9, fork 7, discovered attack 7,
   pin 6, deflection 5, hanging piece 5, skewer 1. Mai `trapped piece`,
   `interference`, `double check`. Non è un bug: è un dato da riportare.
4. **Ragionamento visibile.** Le richieste non attivano il thinking esteso, quindi
   il modello ragiona nel testo. È la condizione preregistrata e resta così; i
   token del ragionamento sono già nel costo misurato.

## Verifica a mano dei temi falsi

Da fare sulla scacchiera: per ognuno dei 40 puzzle, il motivo suggerito in
`hint_false` è davvero assente? Se uno risulta presente, va aggiunto alle coppie
affini con un emendamento prima del congelamento.

| Puzzle | Tema vero | Tema falso suggerito | Davvero assente? |
|---|---|---|---|
| [2hCao](https://lichess.org/training/2hCao) | deflection | pin | da verificare |
| [5yJml](https://lichess.org/training/5yJml) | deflection | hangingPiece | da verificare |
| [6jIif](https://lichess.org/training/6jIif) | deflection | skewer | da verificare |
| [87Pon](https://lichess.org/training/87Pon) | deflection | fork | da verificare |
| [2OVre](https://lichess.org/training/2OVre) | discoveredAttack | pin | da verificare |
| [50Xlc](https://lichess.org/training/50Xlc) | discoveredAttack | trappedPiece | da verificare |
| [82Kie](https://lichess.org/training/82Kie) | discoveredAttack | trappedPiece | da verificare |
| [AhuqD](https://lichess.org/training/AhuqD) | discoveredAttack | sacrifice | da verificare |
| [0esic](https://lichess.org/training/0esic) | doubleCheck | fork | da verificare |
| [1fiRb](https://lichess.org/training/1fiRb) | doubleCheck | skewer | da verificare |
| [74sjc](https://lichess.org/training/74sjc) | doubleCheck | interference | da verificare |
| [A8YYl](https://lichess.org/training/A8YYl) | doubleCheck | interference | da verificare |
| [2p6Ql](https://lichess.org/training/2p6Ql) | fork | pin | da verificare |
| [37T1L](https://lichess.org/training/37T1L) | fork | discoveredAttack | da verificare |
| [3CZAm](https://lichess.org/training/3CZAm) | fork | sacrifice | da verificare |
| [7EGdm](https://lichess.org/training/7EGdm) | fork | trappedPiece | da verificare |
| [13aYW](https://lichess.org/training/13aYW) | hangingPiece | pin | da verificare |
| [1M63I](https://lichess.org/training/1M63I) | hangingPiece | doubleCheck | da verificare |
| [4mV2x](https://lichess.org/training/4mV2x) | hangingPiece | fork | da verificare |
| [BFhmJ](https://lichess.org/training/BFhmJ) | hangingPiece | pin | da verificare |
| [0tXDk](https://lichess.org/training/0tXDk) | interference | discoveredAttack | da verificare |
| [2H7bW](https://lichess.org/training/2H7bW) | interference | hangingPiece | da verificare |
| [6OsTF](https://lichess.org/training/6OsTF) | interference | doubleCheck | da verificare |
| [B8iW3](https://lichess.org/training/B8iW3) | interference | discoveredAttack | da verificare |
| [4L59W](https://lichess.org/training/4L59W) | pin | doubleCheck | da verificare |
| [5kFaY](https://lichess.org/training/5kFaY) | pin | sacrifice | da verificare |
| [7r30W](https://lichess.org/training/7r30W) | pin | fork | da verificare |
| [9gkYg](https://lichess.org/training/9gkYg) | pin | hangingPiece | da verificare |
| [1NXUf](https://lichess.org/training/1NXUf) | sacrifice | doubleCheck | da verificare |
| [5CVcD](https://lichess.org/training/5CVcD) | sacrifice | fork | da verificare |
| [5r6Zp](https://lichess.org/training/5r6Zp) | sacrifice | trappedPiece | da verificare |
| [9mWZR](https://lichess.org/training/9mWZR) | sacrifice | doubleCheck | da verificare |
| [1oRBy](https://lichess.org/training/1oRBy) | skewer | doubleCheck | da verificare |
| [7nXjo](https://lichess.org/training/7nXjo) | skewer | doubleCheck | da verificare |
| [9B6jW](https://lichess.org/training/9B6jW) | skewer | hangingPiece | da verificare |
| [9sZey](https://lichess.org/training/9sZey) | skewer | hangingPiece | da verificare |
| [2Hg9w](https://lichess.org/training/2Hg9w) | trappedPiece | sacrifice | da verificare |
| [6lGwF](https://lichess.org/training/6lGwF) | trappedPiece | doubleCheck | da verificare |
| [7vx6n](https://lichess.org/training/7vx6n) | trappedPiece | sacrifice | da verificare |
| [8mHje](https://lichess.org/training/8mHje) | trappedPiece | discoveredAttack | da verificare |
