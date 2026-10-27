"""RQ3 a quattro bracci: "capisce, non calcola".

Questo modulo è l'unico proprietario delle regole preregistrate in
docs/designs/rq3-preregistration.md: vocabolario dei temi, campione, tema
falso, prompt dei bracci, punteggio del tema, pavimenti, classificazione degli
effetti e frasi del README. Batch e benchmark costruiscono i prompt da qui, così
non possono divergere (un prompt diverso di un carattere è un cache miss).

I quattro bracci, sugli stessi puzzle:

    theme_only   posizione -> solo il motivo, da un elenco chiuso
    move_only    posizione -> MOVE + WHY
    hint_true    posizione + motivo giusto -> MOVE + WHY
    hint_false   posizione + motivo sbagliato plausibile -> MOVE + WHY
"""

from __future__ import annotations

import random

from .benchmark import _theme_matches
from .dataset import TACTICAL_THEMES, Puzzle
from .metrics import wilson_interval
from .representations import REPRESENTATIONS
from .solvers import Answer, Solver, parse_answer

# I 10 temi con almeno 88 puzzle a tema tattico singolo in data/sample.csv.
VOCABULARY = (
    "fork", "pin", "skewer", "discoveredAttack", "deflection",
    "hangingPiece", "trappedPiece", "sacrifice", "interference", "doubleCheck",
)
# Come il tema compare nei prompt: una sola mappa per elenco e suggerimenti.
LABELS = {
    "fork": "fork", "pin": "pin", "skewer": "skewer",
    "discoveredAttack": "discovered attack", "deflection": "deflection",
    "hangingPiece": "hanging piece", "trappedPiece": "trapped piece",
    "sacrifice": "sacrifice", "interference": "interference",
    "doubleCheck": "double check",
}
# Motivi che si implicano a vicenda: mai usati come tema falso l'uno dell'altro.
AFFINE_PAIRS = frozenset({
    frozenset({"discoveredAttack", "doubleCheck"}),
    frozenset({"deflection", "sacrifice"}),
    frozenset({"pin", "skewer"}),
    frozenset({"hangingPiece", "trappedPiece"}),
})
ARMS = ("theme_only", "move_only", "hint_true", "hint_false")
MOVE_ARMS = ("move_only", "hint_true", "hint_false")
BUCKETS = ("<1200", "1200-1599", "1600-1999", "2000-2399", "2400+")

MAIN_PER_CELL = 8        # 8 x 5 fasce = 40 puzzle per tema, 400 in tutto
PILOT_PER_THEME = 4      # 40 puzzle di pilota, disgiunti dai 400
CONTROL_PER_THEME = 10   # 100 dei 400 anche in fen (controllo RQ1, descrittivo)
EQUIVALENCE_MARGIN = 5.0  # punti percentuali
BOOTSTRAP_SAMPLES = 10_000


# --- campione -----------------------------------------------------------------

def tactical_theme(puzzle: Puzzle) -> str | None:
    """L'unico tema tattico del puzzle, o None se ne ha zero o più di uno.

    I tag Lichess sono in ordine alfabetico, quindi con più temi tattici il
    "principale" sarebbe arbitrario: RQ3 usa solo i puzzle a tema singolo.
    """
    tags = [t for t in puzzle.themes if t in TACTICAL_THEMES]
    return tags[0] if len(tags) == 1 else None


def sample(puzzles: list[Puzzle], seed: int = 0) -> tuple[list[Puzzle], list[Puzzle]]:
    """(campione principale, pilota): 8 per (tema, fascia) + 4 per tema, disgiunti.

    Fallisce invece di restituire meno puzzle: il design promette 40 puzzle per
    tema, e un campione più piccolo in silenzio cambierebbe gli IC.
    """
    cells: dict[tuple[str, str], list[Puzzle]] = {}
    for puzzle in puzzles:
        theme = tactical_theme(puzzle)
        if theme in VOCABULARY:
            cells.setdefault((theme, puzzle.rating_bucket), []).append(puzzle)

    main: list[Puzzle] = []
    pilot: list[Puzzle] = []
    for theme in VOCABULARY:
        leftovers: list[Puzzle] = []
        for bucket in BUCKETS:
            pool = sorted(cells.get((theme, bucket), []), key=lambda p: p.puzzle_id)
            if len(pool) < MAIN_PER_CELL:
                raise ValueError(f"cella ({theme}, {bucket}): {len(pool)} puzzle, "
                                 f"ne servono {MAIN_PER_CELL}")
            random.Random(f"{seed}:{theme}:{bucket}").shuffle(pool)
            main.extend(pool[:MAIN_PER_CELL])
            leftovers.extend(pool[MAIN_PER_CELL:])
        if len(leftovers) < PILOT_PER_THEME:
            raise ValueError(f"{theme}: {len(leftovers)} puzzle per il pilota, "
                             f"ne servono {PILOT_PER_THEME}")
        leftovers.sort(key=lambda p: p.puzzle_id)
        pilot.extend(random.Random(f"{seed}:{theme}:pilot").sample(leftovers, PILOT_PER_THEME))
    return main, pilot


def control_subset(main: list[Puzzle], seed: int = 0) -> list[Puzzle]:
    """I puzzle del controllo in fen: 10 per tema, scelti fra i 400."""
    subset: list[Puzzle] = []
    for theme in VOCABULARY:
        pool = sorted((p for p in main if tactical_theme(p) == theme), key=lambda p: p.puzzle_id)
        subset.extend(random.Random(f"{seed}:{theme}:control").sample(pool, CONTROL_PER_THEME))
    return subset


# --- tema falso ---------------------------------------------------------------

def false_theme_candidates(puzzle: Puzzle) -> list[str]:
    """Temi del vocabolario che si possono suggerire come falsi per questo puzzle.

    Esclusi: il tema del puzzle, il suo affine, e ogni tema che un tag del
    puzzle nomina già, anche fuori vocabolario (un tag discoveredCheck rende
    vero "discovered attack").
    """
    true = tactical_theme(puzzle)
    named = set(tag_exclusions(puzzle))
    return [f for f in VOCABULARY
            if f != true and frozenset({f, true}) not in AFFINE_PAIRS and f not in named]


def tag_exclusions(puzzle: Puzzle) -> list[str]:
    """Temi esclusi solo perché un tag del puzzle li nomina già (regola D3)."""
    true = tactical_theme(puzzle)
    return [f for f in VOCABULARY
            if f != true and frozenset({f, true}) not in AFFINE_PAIRS
            and any(_theme_matches(tag, f) for tag in puzzle.themes)]


def false_theme(puzzle: Puzzle, seed: int = 0) -> str:
    """Il tema falso del puzzle. Deterministico fra processi: niente hash()."""
    candidates = false_theme_candidates(puzzle)
    if not candidates:
        raise ValueError(f"{puzzle.puzzle_id}: nessun tema falso possibile")
    return random.Random(f"{seed}:{puzzle.puzzle_id}").choice(candidates)


# --- prompt -------------------------------------------------------------------

THEME_PROMPT = """You are analysing a chess position. Identify the tactical motif.

{position}

Choose exactly one motif from this list: {labels}.

Respond in exactly this format, nothing else:
THEME: <one motif from the list>"""

MOVE_INTRO = "You are analysing a chess position. Find the single best move."
HINT_LINE = "The tactical motif in this position is: {label}."
MOVE_FORMAT = """Respond in exactly this format, nothing else:
MOVE: <the move in standard algebraic notation, e.g. Nxf7+ or Qh5#>
WHY: <one sentence explaining why the move wins>"""


def arm_prompt(puzzle: Puzzle, arm: str, representation: str = "piece_list", seed: int = 0) -> str:
    """Il prompt di un braccio. I tre bracci sulla mossa differiscono solo nella
    riga del suggerimento: è l'invariante su cui poggia il confronto causale."""
    position = REPRESENTATIONS[representation](puzzle.board)
    if arm == "theme_only":
        labels = ", ".join(LABELS[t] for t in VOCABULARY)
        return THEME_PROMPT.format(position=position, labels=labels)
    if arm == "move_only":
        parts = [MOVE_INTRO, position, MOVE_FORMAT]
    elif arm == "hint_true":
        parts = [MOVE_INTRO, position, HINT_LINE.format(label=LABELS[tactical_theme(puzzle)]), MOVE_FORMAT]
    elif arm == "hint_false":
        parts = [MOVE_INTRO, position, HINT_LINE.format(label=LABELS[false_theme(puzzle, seed)]), MOVE_FORMAT]
    else:
        raise ValueError(f"braccio sconosciuto: {arm}")
    return "\n\n".join(parts)


def solver_name(model: str, representation: str, arm: str) -> str:
    return f"{model}:{representation}:{arm}"


def arm_of(solver: str) -> str | None:
    """Il braccio codificato nel nome del solver, o None (es. 'random')."""
    arm = solver.rsplit(":", 1)[-1]
    return arm if arm in ARMS else None


class ArmLLMSolver(Solver):
    """Un braccio di RQ3: deve vedere il puzzle per suggerirne il tema."""

    def __init__(self, complete, arm: str, representation: str = "piece_list",
                 model: str = "llm", seed: int = 0):
        if arm not in ARMS:
            raise ValueError(f"braccio sconosciuto: {arm}")
        self.complete = complete
        self.arm = arm
        self.representation = representation
        self.seed = seed
        self.name = solver_name(model, representation, arm)

    def solve(self, board):
        raise NotImplementedError("i bracci di RQ3 hanno bisogno del puzzle: usa solve_puzzle")

    def solve_puzzle(self, puzzle: Puzzle) -> Answer:
        try:
            text = self.complete(arm_prompt(puzzle, self.arm, self.representation, self.seed))
        except Exception as exc:  # stessa regola di LLMSolver: errore, non mossa illegale
            return Answer(move=None, error=f"{type(exc).__name__}: {exc}")
        return parse_answer(text, puzzle.board)


# --- punteggio del tema -------------------------------------------------------

def score_theme(said: str) -> str | None:
    """L'etichetta del vocabolario nominata dalla risposta, se è una sola.

    Più etichette (anche via sinonimi), nessuna o una fuori vocabolario
    contano come risposta sbagliata.
    """
    matches = [t for t in VOCABULARY if _theme_matches(said, t)]
    return matches[0] if len(matches) == 1 else None


def theme_floors(themes: list[str]) -> dict[str, float]:
    """Pavimenti ciechi sul campione valutato: sempre il tema più frequente, e
    un'estrazione secondo le frequenze (valore atteso sum p^2)."""
    n = len(themes)
    if not n:
        return {"always_most_frequent": 0.0, "frequency_weighted": 0.0}
    shares = [themes.count(t) / n for t in set(themes)]
    return {"always_most_frequent": max(shares), "frequency_weighted": sum(p * p for p in shares)}


# --- statistica e frasi preregistrate ----------------------------------------

def paired_bootstrap(a, b, samples: int = BOOTSTRAP_SAMPLES, seed: int = 0) -> tuple[float, float, float]:
    """Differenza media a - b (in punti percentuali) con IC 95% percentile.

    `a` e `b` sono esiti 0/1 allineati per puzzle: si ricampionano i puzzle,
    non le righe, così il confronto resta a coppie.
    """
    import numpy as np

    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    if a.shape != b.shape or not len(a):
        raise ValueError("servono esiti allineati e non vuoti")
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(a), size=(samples, len(a)))
    diffs = (a[idx].mean(axis=1) - b[idx].mean(axis=1)) * 100
    lo, hi = np.percentile(diffs, [2.5, 97.5])
    return float((a.mean() - b.mean()) * 100), float(lo), float(hi)


def classify(lo: float, hi: float, margin: float = EQUIVALENCE_MARGIN) -> str:
    """Una sola categoria per l'IC [lo, hi] in punti: regole in ordine, la prima vera vince."""
    if lo > margin:
        return "grande positivo"
    if hi < -margin:
        return "grande negativo"
    if -margin <= lo and hi <= margin:
        return "equivalente"
    if lo > 0:
        return "piccolo positivo"
    if hi < 0:
        return "piccolo negativo"
    return "inconclusivo"


def move_level(lo: float, hi: float) -> str:
    """Livello L dell'accuratezza di move_only, dal suo IC di Wilson (frazioni)."""
    if hi < 0.5:
        return "basso"
    if lo > 0.5:
        return "alto"
    return "incerto"


SENTENCES = {
    "falsified": "Non riconosce il motivo meglio del caso: RQ3 è falsificata, e il tutor resta com'è (spiega solo la PV di Stockfish).",
    "understands_not_calculates": "Capisce, non calcola: riconosce il motivo, sbaglia spesso la mossa, e saperlo non lo aiuta.",
    "redundant_hint": "Riconosce il motivo e trova già la mossa nella maggior parte dei casi: il suggerimento è ridondante.",
    "neutral_hint": "Riconosce il motivo, trova la mossa nel {move_rate} dei casi, e saperlo non lo aiuta.",
    "needs_where_to_look": "Sa cosa cercare solo se glielo dici: il collo di bottiglia è dove guardare.",
    "hint_helps": "Il suggerimento aiuta di {effect} punti: riconoscimento e calcolo contano entrambi.",
    "hint_hurts": "Dirgli il motivo giusto lo peggiora di {effect} punti: il suggerimento interferisce col suo calcolo.",
    "inconclusive": "Con {n} puzzle l'effetto del suggerimento non è distinguibile.",
    "content_irrelevant": "Il contenuto del motivo non conta: uno giusto aiuta quanto uno sbagliato.",
    "true_beats_false": "Il motivo giusto aiuta {effect} punti più di uno sbagliato.",
    "false_beats_true": "Il motivo giusto rende {effect} punti meno di uno sbagliato: va indagato prima di trarne regole.",
    "true_vs_false_inconclusive": "La differenza fra motivo giusto e sbagliato non è distinguibile con {n} puzzle.",
    "false_costs": "Un motivo sbagliato costa {effect} punti.",
    "false_ignored": "Ignora un suggerimento sbagliato.",
    "any_hint_helps": "Anche un motivo sbagliato lo aiuta di {effect} punti: conta ricevere un suggerimento, non il suo contenuto.",
    "false_inconclusive": "L'effetto di un motivo sbagliato non è distinguibile con {n} puzzle.",
}

POSITIVE = ("grande positivo", "piccolo positivo")
NEGATIVE = ("grande negativo", "piccolo negativo")


def outcome_key(recognises: bool, level: str, e_relative_to_false: bool, category: str) -> str:
    """La frase principale del README, dalla tabella "Esiti e frasi"."""
    if not recognises:
        return "falsified"
    if e_relative_to_false:  # caso 2: E = hint_true - hint_false
        if category == "equivalente":
            return "content_irrelevant"
        if category in POSITIVE:
            return "true_beats_false"
        if category in NEGATIVE:
            return "false_beats_true"
        return "true_vs_false_inconclusive"
    if category == "equivalente":  # caso 1: E = D_true
        return {"basso": "understands_not_calculates", "alto": "redundant_hint",
                "incerto": "neutral_hint"}[level]
    if category == "grande positivo":
        return "needs_where_to_look"
    if category == "piccolo positivo":
        return "hint_helps"
    if category in NEGATIVE:
        return "hint_hurts"
    return "inconclusive"


def false_hint_key(category: str) -> str:
    if category in NEGATIVE:
        return "false_costs"
    if category == "equivalente":
        return "false_ignored"
    if category in POSITIVE:
        return "any_hint_helps"
    return "false_inconclusive"


def analyse(df, representation: str = "piece_list", seed: int = 0) -> dict:
    """Numeri e frasi preregistrate da un CSV di risultati (metrics.load_results).

    Il tema si ricalcola da `theme_said` con score_theme: la colonna
    `theme_correct` usa la regola permissiva del benchmark e qui non vale.
    """
    def in_scope(solver: str) -> bool:
        parts = solver.rsplit(":", 2)
        return len(parts) == 3 and parts[1] == representation and arm_of(solver) is not None

    rows = df[df["solver"].map(in_scope)]
    rows = rows.assign(arm=rows["solver"].map(arm_of))
    errored = set(rows.loc[rows["errored"], "puzzle_id"])
    complete = rows[~rows["puzzle_id"].isin(errored)]
    counts = complete.groupby("puzzle_id")["arm"].nunique()
    keep = set(counts[counts == len(ARMS)].index)
    rows = complete[complete["puzzle_id"].isin(keep)]
    ids = sorted(keep)
    n = len(ids)
    if not n:
        raise ValueError("nessun puzzle con tutti e quattro i bracci senza errori")

    def by_arm(arm):
        return rows[rows["arm"] == arm].set_index("puzzle_id").loc[ids]

    theme_rows = by_arm("theme_only")
    true_themes = [next(t for t in str(s).split() if t in VOCABULARY) for s in theme_rows["themes"]]
    scored = [score_theme(s) for s in theme_rows["theme_said"]]
    theme_ok = [s == t for s, t in zip(scored, true_themes)]
    solved = {arm: by_arm(arm)["solved"].astype(bool).tolist() for arm in MOVE_ARMS}

    theme_lo, theme_hi = wilson_interval(sum(theme_ok), n)
    floors = theme_floors(true_themes)
    recognises = theme_lo > floors["always_most_frequent"]
    move_lo, move_hi = wilson_interval(sum(solved["move_only"]), n)
    level = move_level(move_lo, move_hi)

    d_true = paired_bootstrap(solved["hint_true"], solved["move_only"], seed=seed)
    d_false = paired_bootstrap(solved["hint_false"], solved["move_only"], seed=seed)
    d_false_cat = classify(d_false[1], d_false[2])
    e_relative_to_false = d_false_cat in POSITIVE
    e = paired_bootstrap(solved["hint_true"], solved["hint_false"], seed=seed) if e_relative_to_false else d_true
    e_cat = classify(e[1], e[2])

    move_rate = sum(solved["move_only"]) / n
    key = outcome_key(recognises, level, e_relative_to_false, e_cat)
    headline = SENTENCES[key].format(move_rate=f"{move_rate:.0%}", effect=f"{abs(e[0]):.1f}", n=n)
    false_key = false_hint_key(d_false_cat)
    false_sentence = SENTENCES[false_key].format(effect=f"{abs(d_false[0]):.1f}", n=n)

    recognised_missed = sum(t and not m for t, m in zip(theme_ok, solved["move_only"]))
    random_rows = df[(df["solver"] == "random") & df["puzzle_id"].isin(keep)]

    def split_effect(mask):
        a = [x for x, k in zip(solved["hint_true"], mask) if k]
        b = [x for x, k in zip(solved["move_only"], mask) if k]
        return paired_bootstrap(a, b, seed=seed) if a else None

    return {
        "n": n,
        "excluded_for_errors": len(errored),
        "theme_rate": sum(theme_ok) / n, "theme_ci": (theme_lo, theme_hi),
        "theme_unparsed": sum(s is None for s in scored) / n,
        "floors": floors, "recognises": recognises,
        "move_rate": move_rate, "move_ci": (move_lo, move_hi), "move_level": level,
        "hint_true_rate": sum(solved["hint_true"]) / n,
        "hint_false_rate": sum(solved["hint_false"]) / n,
        "illegal_rate": {arm: float((~by_arm(arm)["legal"].astype(bool)).mean()) for arm in MOVE_ARMS},
        "random_rate": float(random_rows["solved"].mean()) if len(random_rows) else None,
        "d_true": d_true, "d_true_category": classify(d_true[1], d_true[2]),
        "d_false": d_false, "d_false_category": d_false_cat,
        "e": e, "e_category": e_cat, "e_relative_to_false": e_relative_to_false,
        "recognised_missed": recognised_missed / n,
        "recognised_missed_ci": wilson_interval(recognised_missed, n),
        "d_true_when_theme_right": split_effect(theme_ok),
        "d_true_when_theme_wrong": split_effect([not t for t in theme_ok]),
        "headline_key": key, "headline": headline,
        "false_hint_key": false_key, "false_hint_sentence": false_sentence,
    }
