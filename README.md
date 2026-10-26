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
pytest -q            # 55 test, ~5s
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

**Baseline** (nessuna chiamata API, ~1 ora sui 2.006 puzzle):

```bash
python scripts/run_benchmark.py --puzzles data/sample.csv --dry-run \
    --baselines random greedy stockfish_d1 stockfish_d2 stockfish_d4 \
    --out results/baselines.csv
```

Un run interrotto si riprende con `--resume`: le righe già nel CSV restano,
quelle con un errore API vengono ritentate.

**Run LLM, via Batch API.** Il benchmark chiama il modello una richiesta alla
volta: con il ragionamento attivo, 8.000 chiamate sono decine di ore.
`llm_batch.py` invia le stesse richieste in un unico batch (metà prezzo, di
solito finito entro un'ora) e scrive le risposte nella cache che il benchmark
legge. Modello, `--effort`, `--max-tokens` e rappresentazioni devono
coincidere fra i due script, altrimenti le chiavi di cache non combaciano.

```bash
export ANTHROPIC_API_KEY=...

# pilota: 200 puzzle, una rappresentazione (~$2-3 con Sonnet 5.5)
python scripts/llm_batch.py submit --puzzles data/sample.csv --limit 200 \
    --representations piece_list --dry-run          # conta e stima il costo
python scripts/llm_batch.py submit --puzzles data/sample.csv --limit 200 --representations piece_list
python scripts/llm_batch.py collect --wait
python scripts/run_benchmark.py --puzzles data/sample.csv --limit 200 --baselines \
    --representations piece_list --out results/pilot.csv

# run completo: 2.006 puzzle x 4 rappresentazioni (~$100 stimati con Sonnet 5.5)
python scripts/llm_batch.py submit --puzzles data/sample.csv \
    --representations fen ascii piece_list piece_list_moves
python scripts/llm_batch.py collect --wait
python scripts/run_benchmark.py --puzzles data/sample.csv --baselines \
    --representations fen ascii piece_list piece_list_moves --out results/llm.csv
```

Le risposte del modello vengono messe in cache su disco
(`results/llm_cache.jsonl`), con una chiave che include modello, `effort` e
`max_tokens`: rilanciare il benchmark dopo aver sistemato le metriche non costa
nulla, e cambiare modello non riusa per sbaglio le risposte di un altro.

I modelli attuali non accettano `temperature` e ragionano prima di
rispondere: i token di ragionamento contano in `--max-tokens` (default 16000),
e la riproducibilità si affida a un `--effort` fisso più la cache. Per modelli
che non supportano `effort` (es. `claude-haiku-4-5`) usare `--effort none`.
Nessun fallback automatico su un altro modello in caso di rifiuto: la risposta
di un modello diverso contaminerebbe il confronto.

Le chiamate fallite (rate limit, rifiuti, risposte troncate) finiscono nella
colonna `error` e sono escluse dai tassi, non contate come mosse illegali.

**Grafici e numeri chiave** (settimana 3). Accetta più CSV, così baseline e run
LLM possono stare in file separati:

```bash
python scripts/plots.py --results results/baselines.csv results/llm.csv
```

Scrive in `results/figures/` i grafici di RQ1 (accuratezza per risolutore, IC
di Wilson), RQ2 (curva per fascia di rating), RQ3 (mossa trovata vs tema
riconosciuto), la heatmap per tema, la distribuzione dei cp persi e
`summary.md` con le tre frasi dei criteri di successo di `PLAN.md`.

**Il tutor** (settimana 4): partite Lichess → errori → profilo → puzzle
personalizzati → report HTML.

```bash
python scripts/tutor.py --user <username> --max-games 50            # solo motore
python scripts/tutor.py --user <username> --max-games 50 --explain  # + spiegazioni LLM
```

Il PGN scaricato resta in `results/tutor/<username>/` e viene riusato
(`--refresh` per riscaricarlo); lì finiscono anche `mistakes.csv`,
`puzzles.csv` e `report.html`. Ogni variante mostrata nel report viene dalla PV
di Stockfish: l'LLM spiega la linea del motore, non ne inventa di sue.

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
  solvers.py          Random / Greedy / Stockfish / LLM, con parser delle risposte
  benchmark.py        il runner: puzzle x solver → CSV
  metrics.py          aggregazione con intervalli di Wilson
  analysis.py         PGN → errori → profilo → puzzle personalizzati
  report.py           report HTML del tutor
scripts/
  get_stockfish.py    scarica Stockfish in bin/ (Windows)
  download_puzzles.py scarica il DB Lichess e campiona
  run_benchmark.py    il benchmark, con report finale
  inspect_results.py  i singoli casi dietro le tabelle
  llm_batch.py        riempie la cache LLM con la Batch API
  plots.py            grafici RQ1/RQ2/RQ3 e numeri chiave
  tutor.py            partite Lichess → report HTML
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
su posizioni con ~30 mosse legali non è zero: risolve il 5%). `GreedySolver`
gioca la mossa "visibile" senza calcolare: matto in 1, altrimenti la cattura
che rende di più, altrimenti uno scacco. Scende dal 55% sotto 1200 al 24% sopra
2400, ed è il metro per la curva di RQ2: un LLM sotto `greedy` non sta
calcolando nulla.

Stockfish invece non distingue la difficoltà: già a `depth=1` risolve oltre
l'87% dei puzzle in ogni fascia di rating. E limitarlo per nodi non aiuta:
Stockfish completa sempre almeno un'iterazione, quindi con `nodes=1` esplora
comunque ~60 nodi a profondità 2 e risolve il 96-99% ovunque. Le baseline
Stockfish servono come tetto, non come metro.

Il motore gira con `Threads=1`: a parità di profondità le valutazioni sono
deterministiche, quindi il benchmark è riproducibile.

## Dati

- Puzzle: [database.lichess.org](https://database.lichess.org/) (CC0)
- Partite: [API Lichess](https://lichess.org/api), endpoint
  `/api/games/user/{username}`, nessuna autenticazione richiesta per le
  partite pubbliche
