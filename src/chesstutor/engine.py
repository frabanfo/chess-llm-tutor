"""Wrapper attorno a Stockfish: valutazioni, giudizio delle mosse, rilevamento blunder.

Un'unica istanza del motore viene riusata per tutte le analisi: avviare un
processo UCI costa ~50ms e in un benchmark da migliaia di posizioni la
differenza si sente.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import chess
import chess.engine

# Su Windows non c'è un percorso di sistema: scripts/get_stockfish.py deposita il
# binario qui dentro.
_LOCAL_BIN = Path(__file__).resolve().parents[2] / "bin"

# Percorsi tipici: Debian/Ubuntu usa /usr/games, Homebrew /opt/homebrew/bin.
DEFAULT_PATHS = [
    os.environ.get("STOCKFISH_PATH", ""),
    "/usr/games/stockfish",
    "/usr/local/bin/stockfish",
    "/opt/homebrew/bin/stockfish",
    "stockfish",
]

# Oltre questa soglia (in centipawn) una mossa è considerata un errore grave.
BLUNDER_THRESHOLD = 150
MISTAKE_THRESHOLD = 80
# I punteggi di matto vengono compressi a questo valore per poter fare aritmetica.
MATE_SCORE = 10_000


def find_stockfish() -> str:
    """Restituisce il primo binario Stockfish utilizzabile, o solleva RuntimeError.

    Il contenuto di bin/ viene riletto a ogni chiamata, così il motore si trova
    anche se è stato scaricato dopo l'import del modulo.
    """
    import shutil

    local = sorted(_LOCAL_BIN.rglob("stockfish*.exe")) + sorted(_LOCAL_BIN.rglob("stockfish"))
    candidates = [DEFAULT_PATHS[0], *(str(p) for p in local if p.is_file()), *DEFAULT_PATHS[1:]]

    for path in candidates:
        if path and (os.path.isfile(path) or shutil.which(path)):
            return path
    raise RuntimeError(
        "Stockfish non trovato. Su Windows: python scripts/get_stockfish.py\n"
        "Altrimenti installalo (apt install stockfish / brew install stockfish) "
        "oppure imposta la variabile d'ambiente STOCKFISH_PATH."
    )


@dataclass(frozen=True)
class Evaluation:
    """Valutazione di una posizione dal punto di vista di chi deve muovere."""

    cp: int  # centipawn, compressi se è matto
    mate_in: int | None  # positivo = matto a favore di chi muove
    best_move: chess.Move | None
    pv: tuple[chess.Move, ...]

    @property
    def is_mate(self) -> bool:
        return self.mate_in is not None


class Engine:
    """Contesto attorno a un processo Stockfish."""

    def __init__(self, path: str | None = None, threads: int = 1, hash_mb: int = 128):
        self.path = path or find_stockfish()
        self._engine = chess.engine.SimpleEngine.popen_uci(self.path)
        # Thread=1 rende le valutazioni deterministiche a parità di depth, il che
        # è ciò che serve per un benchmark riproducibile.
        self._engine.configure({"Threads": threads, "Hash": hash_mb})

    def close(self) -> None:
        self._engine.quit()

    def __enter__(self) -> "Engine":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def evaluate(
        self, board: chess.Board, depth: int = 18, multipv: int = 1,
        nodes: int | None = None,
    ) -> list[Evaluation]:
        """Analizza la posizione e restituisce le migliori `multipv` linee.

        Con `nodes` la ricerca è limitata dal numero di nodi invece che dalla
        profondità: serve per baseline volutamente deboli.

        Restituisce una lista vuota se la partita è già finita (matto o stallo):
        in quel caso Stockfish non produce alcuna variante principale.
        """
        if board.is_game_over():
            return []

        limit = chess.engine.Limit(nodes=nodes) if nodes else chess.engine.Limit(depth=depth)
        infos = self._engine.analyse(board, limit, multipv=multipv)
        if isinstance(infos, dict):  # multipv=1 può restituire un dict singolo
            infos = [infos]

        out: list[Evaluation] = []
        for info in infos:
            pv = tuple(info.get("pv", ()))
            score = info["score"].pov(board.turn)
            out.append(
                Evaluation(
                    cp=score.score(mate_score=MATE_SCORE),
                    mate_in=score.mate(),
                    best_move=pv[0] if pv else None,
                    pv=pv,
                )
            )
        return out

    def best_move(
        self, board: chess.Board, depth: int = 18, nodes: int | None = None
    ) -> chess.Move | None:
        evals = self.evaluate(board, depth=depth, nodes=nodes)
        return evals[0].best_move if evals else None

    def judge(
        self, board: chess.Board, move: chess.Move, depth: int = 18
    ) -> "MoveJudgement":
        """Quanto costa `move` rispetto alla mossa migliore, in centipawn.

        Il confronto avviene sempre dal punto di vista di chi muove: valutiamo la
        posizione prima della mossa, poi la posizione dopo, e ribaltiamo il segno
        di quest'ultima perché il tratto è passato all'avversario.
        """
        before = self.evaluate(board, depth=depth)
        if not before:
            raise ValueError("Posizione già terminata, nessuna mossa da giudicare.")
        best = before[0]

        mate_after = None
        board.push(move)
        try:
            if board.is_checkmate():
                after_cp = MATE_SCORE  # abbiamo dato matto: valore massimo
                mate_after = 1
            elif board.is_game_over():
                after_cp = 0  # patta
            else:
                after = self.evaluate(board, depth=depth)
                after_cp = -after[0].cp  # ribalta: ora tocca all'avversario
                if after[0].mate_in is not None and after[0].mate_in < 0:
                    # L'avversario prende matto in k mosse: per chi ha mosso
                    # è un matto in k+1, contando la mossa appena giocata.
                    mate_after = -after[0].mate_in + 1
        finally:
            board.pop()

        loss = best.cp - after_cp
        return MoveJudgement(
            move=move,
            best_move=best.best_move,
            cp_before=best.cp,
            cp_after=after_cp,
            cp_loss=max(0, loss),
            is_best=(move == best.best_move),
            mate_before=best.mate_in,
            mate_after=mate_after,
        )


@dataclass(frozen=True)
class MoveJudgement:
    move: chess.Move
    best_move: chess.Move | None
    cp_before: int
    cp_after: int
    cp_loss: int
    is_best: bool
    # Matti forzati per chi muove, in mosse (None = nessun matto a favore).
    # Servono perché la compressione dei matti in MATE_SCORE - n rende "matto
    # in 1" e "matto in 10" quasi indistinguibili in centipawn.
    mate_before: int | None = None
    mate_after: int | None = None

    @property
    def label(self) -> str:
        if self.is_best:
            return "best"
        if self.cp_loss >= BLUNDER_THRESHOLD:
            return "blunder"
        if self.cp_loss >= MISTAKE_THRESHOLD:
            return "mistake"
        if self.cp_loss >= 30:
            return "inaccuracy"
        return "ok"


@contextmanager
def engine(path: str | None = None, **kwargs):
    """Helper: `with engine() as eng: ...`"""
    eng = Engine(path, **kwargs)
    try:
        yield eng
    finally:
        eng.close()
