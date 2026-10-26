"""Caricamento e campionamento del database puzzle di Lichess.

Formato del CSV (https://database.lichess.org/#puzzles):

    PuzzleId,FEN,Moves,Rating,RatingDeviation,Popularity,NbPlays,Themes,GameUrl,OpeningTags

ATTENZIONE — la trappola principale del dataset: il campo `FEN` è la posizione
PRIMA della mossa avversaria, e la PRIMA mossa in `Moves` è quella
dell'avversario. La posizione del puzzle vera e propria si ottiene applicando
quella prima mossa; la soluzione è composta dalle mosse dispari successive
(indici 1, 3, 5...). Chi salta questo passaggio ottiene metriche senza senso.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

import chess

PUZZLE_DB_URL = "https://database.lichess.org/lichess_db_puzzle.csv.zst"

CSV_COLUMNS = [
    "PuzzleId", "FEN", "Moves", "Rating", "RatingDeviation",
    "Popularity", "NbPlays", "Themes", "GameUrl", "OpeningTags",
]

# Temi tattici "puri", utili per il benchmark. I temi di Lichess includono anche
# etichette non tattiche (lunghezza, fase di gioco) che qui non ci interessano.
TACTICAL_THEMES = [
    "fork", "pin", "skewer", "discoveredAttack", "doubleCheck",
    "deflection", "attraction", "clearance", "interference",
    "sacrifice", "xRayAttack", "zugzwang", "trappedPiece",
    "hangingPiece", "backRankMate", "smotheredMate", "anastasiaMate",
]

# Etichette da ignorare quando si determina il tema "principale" di un puzzle.
META_THEMES = {
    "short", "long", "veryLong", "oneMove", "crushing", "advantage",
    "equality", "mate", "mateIn1", "mateIn2", "mateIn3", "mateIn4", "mateIn5",
    "opening", "middlegame", "endgame", "master", "masterVsMaster", "superGM",
}


@dataclass(frozen=True)
class Puzzle:
    puzzle_id: str
    setup_fen: str          # posizione PRIMA della mossa avversaria (come nel CSV)
    moves: tuple[str, ...]  # tutte le mosse UCI, inclusa quella avversaria iniziale
    rating: int
    popularity: int
    nb_plays: int
    themes: tuple[str, ...] = field(default=())
    game_url: str = ""
    rating_deviation: int = 0
    opening_tags: str = ""

    @property
    def fen(self) -> str:
        """La posizione da risolvere: il turno di chi deve trovare la tattica."""
        board = chess.Board(self.setup_fen)
        board.push_uci(self.moves[0])
        return board.fen()

    @property
    def board(self) -> chess.Board:
        return chess.Board(self.fen)

    @property
    def solution(self) -> tuple[str, ...]:
        """Solo le mosse del solutore (indici dispari nel campo Moves)."""
        return self.moves[1:]

    @property
    def first_move(self) -> str:
        """La mossa chiave: quella che il benchmark chiede di trovare."""
        return self.moves[1]

    @property
    def solution_san(self) -> list[str]:
        """La soluzione in notazione algebrica, per i prompt e i report."""
        board = self.board
        out = []
        for uci in self.solution:
            move = chess.Move.from_uci(uci)
            out.append(board.san(move))
            board.push(move)
        return out

    @property
    def main_theme(self) -> str:
        """Il tema tattico più informativo, scartando le etichette meta."""
        for theme in self.themes:
            if theme in TACTICAL_THEMES:
                return theme
        for theme in self.themes:
            if theme not in META_THEMES:
                return theme
        return self.themes[0] if self.themes else "unknown"

    @property
    def rating_bucket(self) -> str:
        r = self.rating
        if r < 1200:
            return "<1200"
        if r < 1600:
            return "1200-1599"
        if r < 2000:
            return "1600-1999"
        if r < 2400:
            return "2000-2399"
        return "2400+"

    def validate(self) -> None:
        """Verifica che tutte le mosse siano legali. Solleva ValueError se no."""
        board = chess.Board(self.setup_fen)
        for uci in self.moves:
            move = chess.Move.from_uci(uci)
            if move not in board.legal_moves:
                raise ValueError(f"{self.puzzle_id}: mossa illegale {uci}")
            board.push(move)


def _row_to_puzzle(row: dict) -> Puzzle:
    return Puzzle(
        puzzle_id=row["PuzzleId"],
        setup_fen=row["FEN"],
        moves=tuple(row["Moves"].split()),
        rating=int(row["Rating"]),
        popularity=int(row["Popularity"]),
        nb_plays=int(row["NbPlays"]),
        themes=tuple(row["Themes"].split()) if row.get("Themes") else (),
        game_url=row.get("GameUrl", ""),
        rating_deviation=int(row.get("RatingDeviation") or 0),
        opening_tags=row.get("OpeningTags") or "",
    )


def load_puzzles(
    path: str | Path,
    limit: int | None = None,
    min_popularity: int = 80,
    min_plays: int = 100,
) -> list[Puzzle]:
    """Carica i puzzle da un CSV, filtrando quelli poco affidabili.

    I filtri di default scartano i puzzle impopolari o poco giocati: il loro
    rating è rumoroso e alcuni sono semplicemente mal costruiti.
    """
    puzzles: list[Puzzle] = []
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            try:
                puzzle = _row_to_puzzle(row)
            except (KeyError, ValueError):
                continue
            if puzzle.popularity < min_popularity or puzzle.nb_plays < min_plays:
                continue
            if len(puzzle.moves) < 2:
                continue
            puzzles.append(puzzle)
            if limit and len(puzzles) >= limit:
                break
    return puzzles


def stratified_sample(
    puzzles: list[Puzzle],
    per_cell: int = 25,
    themes: list[str] | None = None,
    seed: int = 0,
) -> list[Puzzle]:
    """Campiona `per_cell` puzzle per ogni combinazione (fascia rating x tema).

    La stratificazione è il punto centrale del design sperimentale: senza di
    essa il campione riflette la distribuzione del database (dominata dai
    puzzle di fascia media) e non si può dire nulla su come la difficoltà
    influenzi l'accuratezza.
    """
    import random

    rng = random.Random(seed)
    themes = themes or TACTICAL_THEMES

    cells: dict[tuple[str, str], list[Puzzle]] = {}
    for puzzle in puzzles:
        theme = puzzle.main_theme
        if theme not in themes:
            continue
        cells.setdefault((puzzle.rating_bucket, theme), []).append(puzzle)

    sample: list[Puzzle] = []
    for key in sorted(cells):
        pool = cells[key]
        rng.shuffle(pool)
        sample.extend(pool[:per_cell])
    return sample


def write_sample(puzzles: list[Puzzle], path: str | Path) -> None:
    """Salva un campione in CSV, con lo stesso formato dell'originale."""
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for p in puzzles:
            writer.writerow({
                "PuzzleId": p.puzzle_id,
                "FEN": p.setup_fen,
                "Moves": " ".join(p.moves),
                "Rating": p.rating,
                "RatingDeviation": p.rating_deviation,
                "Popularity": p.popularity,
                "NbPlays": p.nb_plays,
                "Themes": " ".join(p.themes),
                "GameUrl": p.game_url,
                "OpeningTags": p.opening_tags,
            })
