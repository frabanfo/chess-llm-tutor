# Preregistrazione RQ3 — "capisce, non calcola"

Versione 1 · 2026-10-27 · stato: **aperta agli emendamenti fino al pilota**

Questo file fissa *prima di vedere i dati* campione, bracci, metriche, soglie
e le frasi che finiranno nel README per ogni esito possibile. Il design e le
motivazioni sono in [`rq3-four-arm-experiment.md`](rq3-four-arm-experiment.md);
il codice che esegue queste regole è `src/chesstutor/rq3.py`, testato in
`tests/test_pipeline.py` (test `test_rq3_*`).

**Regola di congelamento.** Dopo il pilota sono ammessi solo emendamenti
datati in fondo a questo file (prompt, parser). Prima di inviare il batch del
campione principale il file viene congelato: il commit hash va nel README e in
`results/rq3/main_summary.md`. Dopo, nessuna modifica.

## Modello e parametri

`claude-sonnet-5-5`, `effort=medium`, `max_tokens=16000`, Message Batches API.
Nessun fallback su altri modelli. Il run legge solo dalla cache
(`scripts/rq3.py run`): se manca una risposta si ferma senza chiamare l'API.

## Campione

- Sorgente: `data/sample.csv` (sha256 `89f4efa3…6925022`), seed `0`.
- Solo puzzle con **esattamente un** tema in `TACTICAL_THEMES`. I tag Lichess
  sono in ordine alfabetico, quindi con più temi tattici il "principale" sarebbe
  arbitrario.
- Vocabolario chiuso di 10 temi: `fork`, `pin`, `skewer`, `discoveredAttack`,
  `deflection`, `hangingPiece`, `trappedPiece`, `sacrifice`, `interference`,
  `doubleCheck`.
- Principale: 8 puzzle per (tema, fascia di rating) × 5 fasce = 400
  (sha256 degli id ordinati `c5d0fba8…2113d346`). Se una cella ha meno di 8
  puzzle il campionatore fallisce.
- Pilota: 4 per tema = 40, disgiunti dai 400 (sha256 `804a966e…ec8a5f32`).
  Le risposte del pilota non entrano mai nell'analisi.
- Controllo RQ1: 10 per tema = 100 dei 400, anche in rappresentazione `fen`,
  solo bracci `theme_only` e `move_only`. Descrittivo, nessuna frase.

## Bracci (rappresentazione `piece_list`)

Stessi 400 puzzle in tutti i bracci. I tre bracci sulla mossa differiscono
**solo** nella riga del suggerimento (verificato da
`test_rq3_move_prompts_differ_only_in_the_hint_line`).

`theme_only`:

```
You are analysing a chess position. Identify the tactical motif.

<posizione>

Choose exactly one motif from this list: fork, pin, skewer, discovered attack, deflection, hanging piece, trapped piece, sacrifice, interference, double check.

Respond in exactly this format, nothing else:
THEME: <one motif from the list>
```

`move_only`, `hint_true`, `hint_false` (la riga del suggerimento manca in
`move_only`):

```
You are analysing a chess position. Find the single best move.

<posizione>

The tactical motif in this position is: <etichetta>.

Respond in exactly this format, nothing else:
MOVE: <the move in standard algebraic notation, e.g. Nxf7+ or Qh5#>
WHY: <one sentence explaining why the move wins>
```

- `hint_true`: l'etichetta del tema del puzzle.
- `hint_false`: estratta con `random.Random(f"{seed}:{puzzle_id}")`, uniforme
  fra i temi del vocabolario esclusi:
  - il tema del puzzle;
  - il suo affine: `discoveredAttack`–`doubleCheck`, `deflection`–`sacrifice`,
    `pin`–`skewer`, `hangingPiece`–`trappedPiece`;
  - ogni tema che un tag del puzzle nomina già via `THEME_SYNONYMS` (per esempio
    `discoveredCheck` esclude `discoveredAttack`). Sul campione principale questa
    regola non esclude nulla oltre le coppie affini; resta come garanzia.

## Metriche

- **Tema** (`theme_only`): corretto solo se la risposta nomina esattamente
  un'etichetta del vocabolario (sinonimi di `THEME_SYNONYMS` ammessi) e quella
  è il tema del puzzle. Più etichette, anche via sinonimi, etichette fuori
  vocabolario o risposta vuota = sbagliato; il tasso è riportato. La colonna
  `theme_correct` del benchmark (regola permissiva) **non** si usa.
- **Pavimento del tema:** calcolato sul campione valutato: "sempre il tema più
  frequente" e "estrazione per frequenza" (∑p²). Bilanciato su 10 temi: 10%.
- **Mossa** (primaria): `solved` = `exact_match` OR `engine_equivalent`.
  Secondaria: `exact_match`. Mosse illegali o illeggibili = sbagliate, tasso
  riportato per braccio.
- **Pavimento della mossa:** `random` sugli stessi puzzle.
- **Errori API:** righe con `error` escluse; il batch si ripete al massimo 3
  volte sulle sole richieste mancanti. Se dopo 3 tentativi un puzzle ha ancora
  un errore in un braccio, è escluso da tutti i bracci; il conteggio è riportato.
- **IC:** Wilson per i tassi; differenze a coppie per puzzle con bootstrap
  percentile, 10.000 ricampionamenti, seed 0. Le curve per fascia sono
  esplorative, senza correzione per confronti multipli.

## Esiti e frasi

Margine di equivalenza ±5 punti. Ogni differenza a coppie con IC [lo, hi]
riceve una sola categoria; le regole si applicano in ordine e vince la prima
vera (`rq3.classify`):

1. grande positivo: lo > +5
2. grande negativo: hi < −5
3. equivalente: −5 ≤ lo e hi ≤ +5
4. piccolo positivo: lo > 0
5. piccolo negativo: hi < 0
6. inconclusivo: tutto il resto

- **R (riconosce):** limite inferiore Wilson di `theme_only` > pavimento "tema
  più frequente".
- **L (livello della mossa)**, IC Wilson di `move_only`: *basso* se il limite
  superiore < 50%, *alto* se il limite inferiore > 50%, altrimenti *incerto*.
- **D_true** = hint_true − move_only; **D_false** = hint_false − move_only.
- **E:** se D_false è positivo (piccolo o grande), E = hint_true − hint_false;
  altrimenti E = D_true. D_true si riporta sempre.

La frase principale viene da `rq3.outcome_key`; il testo esatto è in
`rq3.SENTENCES`.

| R | caso di E | L | categoria di E | frase |
|---|---|---|---|---|
| no | qualsiasi | qualsiasi | qualsiasi | RQ3 falsificata: non riconosce il motivo meglio del caso |
| sì | D_true | basso | equivalente | "Capisce, non calcola" |
| sì | D_true | alto | equivalente | Trova già la mossa: il suggerimento è ridondante |
| sì | D_true | incerto | equivalente | Riconosce, trova la mossa nel M%, saperlo non aiuta |
| sì | D_true | qualsiasi | grande positivo | Sa cosa cercare solo se glielo dici |
| sì | D_true | qualsiasi | piccolo positivo | Il suggerimento aiuta di E punti |
| sì | D_true | qualsiasi | negativo | Il motivo giusto lo peggiora di E punti |
| sì | D_true | qualsiasi | inconclusivo | Effetto non distinguibile con n puzzle |
| sì | hint_true − hint_false | — | equivalente | Il contenuto del motivo non conta |
| sì | hint_true − hint_false | — | positivo | Il motivo giusto aiuta E punti più di uno sbagliato |
| sì | hint_true − hint_false | — | negativo | Il motivo giusto rende meno di uno sbagliato: da indagare |
| sì | hint_true − hint_false | — | inconclusivo | Differenza non distinguibile con n puzzle |

Frase su D_false, sempre accanto alla principale:

- negativo: "un motivo sbagliato costa D punti";
- equivalente: "ignora un suggerimento sbagliato";
- positivo: "anche un motivo sbagliato lo aiuta";
- inconclusivo: riportato come tale.

Analisi descrittive, senza frasi:

- tabella per puzzle tema × mossa, con la quota "riconosce e sbaglia la mossa" e
  il suo IC;
- D_true separato fra i puzzle con tema giusto e quelli con tema sbagliato;
- controllo in `fen`.

## Budget

Stima dal dry-run (`scripts/rq3.py submit --dry-run`, 2.500 token di output per
risposta): pilota circa $2 (160 richieste), principale circa $23 (1.800
richieste). Sono stime, nulla è ancora speso. Regola di stop: dopo il pilota si
ricalcola il costo per richiesta dai token reali; se la proiezione del
principale supera i $45, non si invia e si emenda il piano.

## Figura principale

Barre del tasso di mosse trovate per `move_only`, `hint_true` e `hint_false`,
con IC di Wilson e il pavimento `random` come linea; accanto, `theme_only` con
il pavimento del tema.

## Emendamenti

**1 — 2026-10-27, prima del pilota.** Sulle baseline del campione principale
(`results/rq3/main_baselines.csv`, nessuna chiamata API) `greedy` risolve il
97,5% dei puzzle `hangingPiece`, contro il 17,5–47,5% degli altri temi: lì il
suggerimento "hanging piece" quasi rivela la mossa. Si aggiunge un'analisi
**descrittiva**: D_true calcolato escludendo i 40 puzzle `hangingPiece`
(`d_true_without_hanging_piece`). Le frasi principali, le soglie e il campione
non cambiano.
