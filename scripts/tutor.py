#!/usr/bin/env python3
"""Il tutor: dalle tue partite Lichess a un report con errori spiegati e puzzle.

    # solo motore, nessuna chiamata API
    python scripts/tutor.py --user frabaffo --max-games 50

    # con le spiegazioni dell'LLM (richiede ANTHROPIC_API_KEY)
    python scripts/tutor.py --user frabaffo --max-games 50 --explain

Scrive in results/tutor/<user>/: il PGN scaricato (riusato ai lanci successivi,
--refresh per riscaricarlo), mistakes.csv, puzzles.csv e report.html.
"""

from __future__ import annotations

import argparse
import csv
import io
import statistics
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import chess  # noqa: E402
import chess.pgn  # noqa: E402

from chesstutor.analysis import (  # noqa: E402
    analyse_pgn_file, build_explanation_prompt, fetch_games, mistakes_to_puzzles,
    weakness_profile,
)
from chesstutor.engine import Engine  # noqa: E402
from chesstutor.report import ExplainedMistake, render_report  # noqa: E402
from chesstutor.solvers import anthropic_completer, cached_completer  # noqa: E402


def player_rating(pgn_text: str, player: str) -> int:
    """Rating mediano del giocatore nelle partite scaricate (per tarare le spiegazioni)."""
    stream, ratings = io.StringIO(pgn_text), []
    while (game := chess.pgn.read_game(stream)) is not None:
        h = game.headers
        for side in ("White", "Black"):
            if h.get(side, "").lower() == player.lower() and h.get(f"{side}Elo", "?").isdigit():
                ratings.append(int(h[f"{side}Elo"]))
    return int(statistics.median(ratings)) if ratings else 1500


def count_games(pgn_text: str, limit: int) -> int:
    stream, n = io.StringIO(pgn_text), 0
    while n < limit and chess.pgn.read_headers(stream) is not None:
        n += 1
    return n


def principal_variation(engine: Engine, fen: str, depth: int, plies: int = 8) -> list[str]:
    """PV di Stockfish in SAN, a partire dalla mossa migliore."""
    board = chess.Board(fen)
    evals = engine.evaluate(board, depth=depth)
    sans = []
    for move in (evals[0].pv if evals else ())[:plies]:
        sans.append(board.san(move))
        board.push(move)
    return sans


def write_csv(rows: list[dict], path: Path) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        if not rows:
            return
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--user", required=True, help="username Lichess")
    parser.add_argument("--max-games", type=int, default=50)
    parser.add_argument("--perf", default="blitz,rapid,classical",
                        help="tipi di partita Lichess, separati da virgola")
    parser.add_argument("--depth", type=int, default=14, help="profondità di analisi delle partite")
    parser.add_argument("--worst", type=int, default=10, help="errori da spiegare nel report")
    parser.add_argument("--max-puzzles", type=int, default=12)
    parser.add_argument("--explain", action="store_true", help="genera le spiegazioni con l'LLM")
    parser.add_argument("--model", default="claude-sonnet-5-5")
    parser.add_argument("--effort", default="medium")
    parser.add_argument("--refresh", action="store_true", help="riscarica le partite")
    parser.add_argument("--out", default="results/tutor")
    args = parser.parse_args()

    out = Path(args.out) / args.user
    out.mkdir(parents=True, exist_ok=True)
    pgn_path = out / "games.pgn"
    if args.refresh or not pgn_path.exists():
        print(f"Scarico fino a {args.max_games} partite di {args.user}...")
        pgn_path.write_text(fetch_games(args.user, max_games=args.max_games, perf_type=args.perf),
                            encoding="utf-8")
    pgn_text = pgn_path.read_text(encoding="utf-8")
    games = count_games(pgn_text, args.max_games)
    rating = player_rating(pgn_text, args.user)
    print(f"{games} partite, rating mediano {rating}")

    with Engine() as engine:
        print(f"Analisi a profondità {args.depth}...")
        mistakes = analyse_pgn_file(pgn_text, engine, args.user, depth=args.depth,
                                    max_games=args.max_games)
        profile = weakness_profile(mistakes)
        print(f"{profile['total_mistakes']} errori, {profile['blunders']} blunder")

        candidates = sorted(mistakes, key=lambda m: -m.cp_loss)
        puzzles = mistakes_to_puzzles(candidates, engine, depth=args.depth + 2)[:args.max_puzzles]

        complete = None
        if args.explain:
            complete = cached_completer(
                anthropic_completer(args.model, effort=None if args.effort == "none" else args.effort),
                str(out / "llm_cache.jsonl"),
            )
        explained = []
        for m in profile["worst"][:args.worst]:
            pv = principal_variation(engine, m.fen, depth=args.depth + 4)
            text = ""
            if complete:
                try:
                    text = complete(build_explanation_prompt(m, pv, rating=rating)).strip()
                except Exception as exc:  # un errore API non deve far perdere l'analisi
                    print(f"  spiegazione fallita per {m.game_id}: {type(exc).__name__}: {exc}")
            explained.append(ExplainedMistake(m, pv, text))

    write_csv([asdict(m) for m in mistakes], out / "mistakes.csv")
    write_csv(puzzles, out / "puzzles.csv")
    report = out / "report.html"
    report.write_text(render_report(args.user, profile, explained, puzzles, games,
                                    model=args.model if args.explain else ""),
                      encoding="utf-8")
    print(f"Report: {report}")


if __name__ == "__main__":
    main()
