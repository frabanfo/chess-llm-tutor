# chess-llm-tutor

Quanto sono bravi gli LLM a risolvere puzzle di scacchi — e cosa cambia se
descrivi la posizione in modo diverso. Poi: usare quella risposta per costruire
un tutor che spiega i tuoi errori.

Due parti, in ordine:

1. **Benchmark** — ~2.000 puzzle Lichess stratificati per rating e tema, quattro
   rappresentazioni della posizione, due baseline. Stockfish fa da giudice.
2. **Tutor** — le tue partite Lichess → errori → profilo di debolezze → puzzle
   personalizzati e spiegazioni in linguaggio naturale ancorate al motore.

La parte 1 giustifica la parte 2: invece di "ho messo un LLM sopra Stockfish",
il progetto dice "ho misurato dove l'LLM sbaglia e ho progettato il sistema
attorno a quel limite".

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Stockfish
sudo apt install stockfish     # Debian/Ubuntu → /usr/games/stockfish
brew install stockfish         # macOS
# oppure: export STOCKFISH_PATH=/percorso/del/binario
```

Su Windows non c'è un pacchetto comodo: lo script scarica la release ufficiale
in `bin/`, scegliendo la build in base alle istruzioni della CPU.

```powershell
python -m venv .venv; .venv\Scripts\Activate.ps1
pip install -r requirements.txt
python scripts/get_stockfish.py
```

Verifica che tutto giri:

```bash
pytest -q            # 47 test, ~3s
```

## Uso

**Prova a secco** (nessuna chiamata API, usa le fixture incluse):

```bash
python scripts/run_benchmark.py --puzzles tests/fixtures/puzzles_sample.csv --dry-run
```

**Scarica il dataset vero** e campiona (~300 MB, una volta sola):

```bash
python scripts/download_puzzles.py --per-cell 25 --out data/sample.csv
```

**Benchmark completo**, confrontando tre rappresentazioni:

```bash
export ANTHROPIC_API_KEY=...
python scripts/run_benchmark.py --puzzles data/sample.csv \
    --model claude-opus-5-5 --effort medium \
    --representations fen ascii piece_list \
    --out results/run1.csv
```

Le risposte del modello vengono messe in cache su disco
(`results/llm_cache.jsonl`), con una chiave che include modello, `effort` e
`max_tokens`: rilanciare il benchmark dopo aver sistemato le metriche non costa
nulla, e cambiare modello non riusa per sbaglio le risposte di un altro.

I modelli attuali non accettano `temperature` e ragionano prima di
rispondere: i token di ragionamento contano in `--max-tokens` (default 16000),
e la riproducibilità si affida a un `--effort` fisso più la cache. Per modelli
che non supportano `effort` (es. `claude-haiku-4-5`) usare `--effort none`.

Le chiamate fallite (rate limit, rifiuti, risposte troncate) finiscono nella
colonna `error` e sono escluse dai tassi, non contate come mosse illegali.

**Ispeziona i singoli casi** dietro le tabelle aggregate — il CSV ha una riga
per (puzzle, risolutore), con FEN, mossa attesa, mossa data e cp_loss:

```bash
python scripts/inspect_results.py --failed        # non risolti, per cp_loss
python scripts/inspect_results.py --illegal       # mosse illegali (solo LLM)
python scripts/inspect_results.py --equivalent    # passati senza la mossa ufficiale
python scripts/inspect_results.py --errors        # chiamate API fallite
python scripts/inspect_results.py --puzzle 9rklp --raw  # scheda + risposta integrale
```

## Struttura

```
src/chesstutor/
  engine.py           wrapper Stockfish: valutazioni, giudizio mosse, blunder
  dataset.py          caricamento e campionamento stratificato dei puzzle
  representations.py  4 modi di descrivere una posizione + prompt
  solvers.py          Random / Stockfish / LLM, con parser delle risposte
  benchmark.py        il runner: puzzle x solver → CSV
  metrics.py          aggregazione con intervalli di Wilson
  analysis.py         PGN → errori → profilo → puzzle personalizzati
scripts/
  get_stockfish.py    scarica Stockfish in bin/ (Windows)
  download_puzzles.py scarica il DB Lichess e campiona
  run_benchmark.py    il benchmark, con report finale
  inspect_results.py  i singoli casi dietro le tabelle
tests/                suite pytest + puzzle di fixture verificati
```

## Tre cose che vale la pena sapere prima di toccare il codice

**Il campo FEN del dataset Lichess non è la posizione del puzzle.** È la
posizione *prima* della mossa avversaria, e la prima mossa in `Moves` è quella
dell'avversario. La posizione da risolvere si ottiene applicandola; la
soluzione parte dall'indice 1. È l'errore più comune con questo dataset e
produce metriche che sembrano plausibili ma sono senza senso. C'è un test
apposta (`test_setup_fen_is_not_puzzle_fen`) che fallisce se qualcuno
"semplifica" quel passaggio.

**Una mossa illegale resta illegale.** Il parser accetta SAN e UCI e tollera
punteggiatura e markdown, ma non cerca la mossa legale "più simile" a quella
proposta. Aggiustare le risposte gonfia l'accuratezza e rende il benchmark
inutile: il tasso di mosse illegali è di per sé un risultato interessante.

**Risolto ≠ mossa ufficiale.** Un puzzle conta come risolto se la mossa
coincide con la soluzione di Lichess *oppure* se il motore la giudica
equivalente (entro 30 centipawn). Alcune posizioni hanno più di una mossa
vincente, e punire la seconda sarebbe misurare la memoria del dataset invece
della capacità tattica. Le due metriche restano separate nel CSV
(`exact_match` e `engine_equivalent`), così puoi riportarle entrambe.
Se la posizione ha un matto forzato, la tolleranza in centipawn non basta
(matto in 1 e matto in 10 distano 9 cp una volta compressi): serve un matto
altrettanto rapido.

**Il tema si riconosce per frase, non per parola.** `theme_correct` accetta i
sinonimi di `THEME_SYNONYMS` in `benchmark.py` ("double attack" per `fork`,
"x-ray" per `xRayAttack`) su uno qualunque dei temi non-meta del puzzle, ma
non parole generiche come "attack", "piece" o "mate" che combaciano con mezzi temi.

## Note metodologiche

Con 25 puzzle per cella la differenza fra 60% e 68% non è statisticamente
distinguibile: `metrics.py` riporta sempre l'intervallo di Wilson al 95%
insieme al tasso, proprio per non invitare a sovrainterpretare il rumore.

Le baseline non sono decorative. `RandomSolver` stabilisce il pavimento (che
su posizioni con ~30 mosse legali non è zero: a volte azzecca). `StockfishSolver`
rende il risultato leggibile: "gioca come Stockfish limitato a 1 nodo" comunica
molto più di "58% di accuratezza". Attenzione però: già a `depth=1` Stockfish
risolve oltre il 90% dei puzzle in ogni fascia di rating, quindi non distingue
la difficoltà. `stockfish_n1` (ricerca limitata a 1 nodo) scende da ~89% sotto
1200 a ~61% sopra 2000, ed è il metro utile per la curva per rating.

Il motore gira con `Threads=1`: a parità di profondità le valutazioni sono
deterministiche, quindi il benchmark è riproducibile.

## Dati

- Puzzle: [database.lichess.org](https://database.lichess.org/) (CC0)
- Partite: [API Lichess](https://lichess.org/api), endpoint
  `/api/games/user/{username}`, nessuna autenticazione richiesta per le
  partite pubbliche
