"""Il runner del benchmark: puzzle x risolutori -> righe di risultati.

Una riga per (puzzle, risolutore). Il file di output è volutamente grezzo e
ridondante: l'analisi si fa dopo, e avere i dati completi permette di
riesaminarli senza rilanciare il benchmark.
"""

from __future__ import annotations

import csv
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import chess

from .dataset import META_THEMES, Puzzle
from .engine import Engine
from .solvers import Solver

# Se la mossa proposta perde meno di questo rispetto alla migliore, la
# consideriamo "accettabile" anche se non coincide con la soluzione ufficiale.
EQUIV_TOLERANCE_CP = 30


@dataclass
class Result:
    puzzle_id: str
    solver: str
    rating: int
    rating_bucket: str
    theme: str                # tema principale (quello usato per stratificare)
    themes: str               # tutti i temi non-meta di Lichess, separati da spazio
    fen: str
    expected_uci: str
    expected_san: str
    got_uci: str
    got_san: str
    legal: bool
    exact_match: bool         # coincide con la soluzione ufficiale di Lichess
    engine_equivalent: bool   # non è la soluzione ma è ugualmente vincente
    cp_loss: int              # quanto costa la mossa proposta, in centipawn
    theme_said: str
    theme_correct: bool       # il tema dichiarato corrisponde a uno dei temi del puzzle
    explanation: str
    raw: str                  # risposta integrale del solutore (vuota per le baseline)
    error: str                # chiamata fallita: la riga va esclusa dalle metriche
    seconds: float


# Come un modello può nominare ciascun tema di Lichess. Il confronto avviene
# per frase intera, non per parola singola: con l'intersezione di parole
# "attack" combaciava con discoveredAttack e xRayAttack, "piece" con
# hangingPiece e trappedPiece, "mate" con ogni tipo di matto — e il tasso di
# temi corretti (RQ3) risultava gonfiato.
THEME_SYNONYMS: dict[str, list[str]] = {
    "fork": ["fork", "double attack", "royal fork", "family fork"],
    "pin": ["pin", "pinned", "pinning", "absolute pin", "relative pin"],
    "skewer": ["skewer"],
    "discoveredAttack": ["discovered attack", "discovery", "discovered check",
                         "revealed attack", "revealed check"],
    "doubleCheck": ["double check"],
    "deflection": ["deflection", "deflect", "overload", "overloaded", "overloading"],
    "attraction": ["attraction", "decoy", "lure", "luring"],
    "clearance": ["clearance", "line clearance", "square clearance", "vacating"],
    "interference": ["interference", "interpose", "interposition"],
    "sacrifice": ["sacrifice", "sacrificing", "sac"],
    "xRayAttack": ["x ray", "xray"],
    "zugzwang": ["zugzwang"],
    "trappedPiece": ["trapped piece", "trapped", "trapping", "trap"],
    "hangingPiece": ["hanging piece", "hanging", "undefended piece", "undefended",
                     "loose piece", "en prise", "free piece", "unprotected"],
    "backRankMate": ["back rank mate", "back rank", "back rank checkmate"],
    "smotheredMate": ["smothered mate", "smothered"],
    "anastasiaMate": ["anastasia mate", "anastasia"],
}


def _norm(text: str) -> str:
    """minuscolo, camelCase separato, solo lettere e spazi singoli."""
    text = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", text)
    return " ".join(re.split(r"[^a-z]+", text.lower())).strip()


def _theme_matches(said: str, actual: str) -> bool:
    """Il tema dichiarato nomina il tema di Lichess `actual`?

    Accetta i sinonimi di THEME_SYNONYMS, con un suffisso flessivo
    (pins, forks, sacrificed). Per i temi fuori dal dizionario serve la frase
    completa ("quiet move" per quietMove).
    """
    if not said or not actual:
        return False
    phrases = THEME_SYNONYMS.get(actual, [_norm(actual)])
    text = _norm(said)
    return any(
        re.search(rf"\b{re.escape(_norm(p))}(?:s|es|d|ed|ing)?\b", text) for p in phrases
    )


def _any_theme_matches(said: str, themes: tuple[str, ...]) -> bool:
    """Un puzzle ha spesso più temi tattici (fork + sacrifice): vale ognuno."""
    return any(_theme_matches(said, t) for t in themes if t not in META_THEMES)


def _is_equivalent(judgement) -> bool:
    """La mossa, pur non ufficiale, vince quanto la soluzione?

    Se la posizione contiene un matto forzato serve un matto altrettanto
    rapido: i matti sono compressi in MATE_SCORE - n, quindi in centipawn
    "matto in 1" e "matto in 10" distano 9 cp e passerebbero la tolleranza.
    """
    if judgement.mate_before is not None and judgement.mate_before > 0:
        return judgement.mate_after is not None and judgement.mate_after <= judgement.mate_before
    return judgement.cp_loss <= EQUIV_TOLERANCE_CP


def run_puzzle(puzzle: Puzzle, solver: Solver, engine: Engine, judge_depth: int = 16) -> Result:
    board = puzzle.board
    expected = chess.Move.from_uci(puzzle.first_move)

    start = time.perf_counter()
    answer = solver.solve(board)
    elapsed = time.perf_counter() - start

    got = answer.move
    legal = got is not None and got in board.legal_moves
    exact = legal and got == expected

    cp_loss = -1
    equivalent = False
    if legal and not exact:
        # Solo qui serve il motore: se la mossa è già quella giusta o è
        # illegale, non c'è nulla da giudicare e risparmiamo un'analisi.
        judgement = engine.judge(board, got, depth=judge_depth)
        cp_loss = judgement.cp_loss
        equivalent = _is_equivalent(judgement)
    elif exact:
        cp_loss = 0

    return Result(
        puzzle_id=puzzle.puzzle_id,
        solver=solver.name,
        rating=puzzle.rating,
        rating_bucket=puzzle.rating_bucket,
        theme=puzzle.main_theme,
        themes=" ".join(t for t in puzzle.themes if t not in META_THEMES),
        fen=puzzle.fen,
        expected_uci=puzzle.first_move,
        expected_san=board.san(expected),
        got_uci=got.uci() if got else answer.illegal_attempt,
        got_san=board.san(got) if legal else "",
        legal=legal,
        exact_match=exact,
        engine_equivalent=equivalent,
        cp_loss=cp_loss,
        theme_said=answer.theme,
        theme_correct=_any_theme_matches(answer.theme, puzzle.themes or (puzzle.main_theme,)),
        explanation=answer.explanation,
        raw=answer.raw,
        error=answer.error,
        seconds=round(elapsed, 3),
    )


def run_benchmark(
    puzzles: list[Puzzle],
    solvers: list[Solver],
    engine: Engine,
    out_path: str | Path,
    judge_depth: int = 16,
    verbose: bool = True,
) -> list[Result]:
    """Esegue tutti i risolutori su tutti i puzzle e scrive un CSV.

    Il CSV viene scritto incrementalmente: un run lungo che si interrompe a
    metà lascia comunque i dati già raccolti.
    """
    results: list[Result] = []
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        writer = None
        total = len(puzzles) * len(solvers)
        done = 0
        for puzzle in puzzles:
            for solver in solvers:
                result = run_puzzle(puzzle, solver, engine, judge_depth)
                results.append(result)
                row = asdict(result)
                if writer is None:
                    writer = csv.DictWriter(fh, fieldnames=list(row))
                    writer.writeheader()
                writer.writerow(row)
                fh.flush()
                done += 1
                if verbose and done % 25 == 0:
                    print(f"  {done}/{total}...", flush=True)
    return results
