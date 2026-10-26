#!/usr/bin/env python3
"""Esegue il benchmark.

    # prova a secco, senza chiamate API
    python scripts/run_benchmark.py --puzzles tests/fixtures/puzzles_sample.csv --dry-run

    # run vero, confrontando tre rappresentazioni della posizione
    python scripts/run_benchmark.py --puzzles data/sample.csv \\
        --model claude-sonnet-5-5 --representations fen ascii piece_list
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from chesstutor.benchmark import run_benchmark  # noqa: E402
from chesstutor.dataset import load_puzzles  # noqa: E402
from chesstutor.engine import Engine  # noqa: E402
from chesstutor.metrics import load_results, print_report  # noqa: E402
from chesstutor.solvers import (  # noqa: E402
    GreedySolver, LLMSolver, RandomSolver, StockfishSolver, anthropic_completer, cached_completer,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--puzzles", required=True)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--model", default="claude-sonnet-5-5")
    parser.add_argument("--effort", default="medium",
                        help="low/medium/high/xhigh/max; 'none' per modelli che non lo supportano")
    parser.add_argument("--max-tokens", type=int, default=16000,
                        help="include i token di ragionamento: non abbassarlo troppo")
    parser.add_argument("--representations", nargs="+", default=["piece_list"],
                        choices=["fen", "ascii", "piece_list", "piece_list_moves"])
    parser.add_argument("--baselines", nargs="*", default=["random", "greedy", "stockfish_d1"],
                        help="baseline da includere: random, greedy, stockfish_dN (profondità), "
                             "stockfish_nN (nodi; nota: n1 equivale circa a d2)")
    parser.add_argument("--judge-depth", type=int, default=16)
    parser.add_argument("--out", default="results/benchmark.csv")
    parser.add_argument("--cache", default="results/llm_cache.jsonl")
    parser.add_argument("--resume", action="store_true",
                        help="riprende un run interrotto: salta le righe già in --out "
                             "e ritenta solo le chiamate fallite")
    parser.add_argument("--dry-run", action="store_true",
                        help="salta l'LLM, usa solo le baseline")
    args = parser.parse_args()

    puzzles = load_puzzles(args.puzzles, limit=args.limit,
                           min_popularity=0, min_plays=0)
    print(f"{len(puzzles)} puzzle caricati")

    with Engine() as engine:
        solvers = []
        for name in args.baselines:
            if name == "random":
                solvers.append(RandomSolver(seed=0))
            elif name == "greedy":
                solvers.append(GreedySolver(seed=0))
            elif name.startswith("stockfish_d"):
                solvers.append(StockfishSolver(engine, depth=int(name.split("_d")[1])))
            elif name.startswith("stockfish_n"):
                solvers.append(StockfishSolver(engine, nodes=int(name.split("_n")[1])))
            else:
                parser.error(f"baseline sconosciuta: {name}")

        if not args.dry_run:
            Path(args.cache).parent.mkdir(parents=True, exist_ok=True)
            effort = None if args.effort.lower() == "none" else args.effort
            complete = cached_completer(
                anthropic_completer(args.model, max_tokens=args.max_tokens, effort=effort),
                args.cache,
            )
            for rep in args.representations:
                solvers.append(LLMSolver(complete, representation=rep,
                                         name=f"{args.model}:{rep}"))

        print(f"Risolutori: {', '.join(s.name for s in solvers)}")
        run_benchmark(puzzles, solvers, engine, args.out,
                      judge_depth=args.judge_depth, resume=args.resume)

    print(f"\nRisultati in {args.out}")
    print_report(load_results(args.out))


if __name__ == "__main__":
    main()
