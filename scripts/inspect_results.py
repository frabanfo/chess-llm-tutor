#!/usr/bin/env python3
"""Guarda i singoli puzzle dietro le tabelle aggregate.

    python scripts/inspect_results.py                      # una riga per puzzle x solver
    python scripts/inspect_results.py --failed             # solo quelli non risolti
    python scripts/inspect_results.py --solver random      # filtra per risolutore
    python scripts/inspect_results.py --equivalent         # "risolti" senza la mossa ufficiale
    python scripts/inspect_results.py --errors             # chiamate API fallite
    python scripts/inspect_results.py --puzzle FIX003      # scheda completa, con scacchiera

Il report di run_benchmark.py aggrega; qui si scende al caso singolo, che è
dove si capisce se un tasso significa qualcosa o è un artefatto.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import chess  # noqa: E402

from chesstutor.metrics import load_results  # noqa: E402
from chesstutor.representations import ascii_board  # noqa: E402

COLUMNS = ["puzzle_id", "solver", "rating", "theme", "expected_san", "got_san",
           "legal", "exact_match", "engine_equivalent", "cp_loss"]


def text(value) -> str:
    """Le celle vuote del CSV arrivano come NaN, che è truthy: qui diventano ''."""
    return "" if value is None or value != value else str(value)


def show_detail(df, puzzle_id: str, raw: bool = False) -> None:
    rows = df[df.puzzle_id == puzzle_id]
    if rows.empty:
        raise SystemExit(f"Nessun puzzle '{puzzle_id}' in questi risultati.")

    first = rows.iloc[0]
    print(f"\n=== {puzzle_id} — {first.theme}, rating {first.rating} ===")
    print(f"https://lichess.org/training/{puzzle_id}")
    print(ascii_board(chess.Board(first.fen)))
    print(f"\nSoluzione ufficiale: {first.expected_san}")

    for _, row in rows.iterrows():
        if row.errored:
            print(f"\n  {row.solver}: ERRORE — {row.error}")
            continue
        verdict = ("esatta" if row.exact_match else
                   "equivalente" if row.engine_equivalent else
                   "sbagliata" if row.legal else "ILLEGALE")
        loss = "" if row.cp_loss < 0 else f", cp_loss {row.cp_loss}"
        print(f"\n  {row.solver}: {text(row.got_san) or text(row.got_uci)} "
              f"→ {verdict}{loss}")
        if text(row.theme_said):
            mark = "ok" if row.theme_correct else f"≠ {row.theme}"
            print(f"    tema dichiarato: {row.theme_said} ({mark})")
        if text(row.explanation):
            print(f"    {row.explanation}")
        if raw and text(row.raw):
            print("    --- risposta integrale ---")
            print("    " + text(row.raw).replace("\n", "\n    "))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", default="results/benchmark.csv")
    parser.add_argument("--puzzle", help="scheda completa di un singolo puzzle")
    parser.add_argument("--solver", help="filtra per risolutore")
    parser.add_argument("--theme", help="filtra per tema")
    parser.add_argument("--failed", action="store_true", help="solo i puzzle non risolti")
    parser.add_argument("--illegal", action="store_true", help="solo le mosse illegali")
    parser.add_argument("--errors", action="store_true", help="solo le chiamate fallite")
    parser.add_argument("--raw", action="store_true",
                        help="con --puzzle: mostra anche la risposta integrale dell'LLM")
    parser.add_argument("--equivalent", action="store_true",
                        help="solo i 'risolti' che non sono la mossa ufficiale")
    parser.add_argument("--sort", default="cp_loss", help="colonna di ordinamento")
    args = parser.parse_args()

    df = load_results(args.results)

    if args.puzzle:
        show_detail(df, args.puzzle, raw=args.raw)
        return

    if args.solver:
        df = df[df.solver == args.solver]
    if args.theme:
        df = df[df.theme == args.theme]
    if args.errors:
        df = df[df.errored]
    else:
        df = df[~df.errored]
    if args.failed:
        df = df[~df.solved]
    if args.illegal:
        df = df[~df.legal]
    if args.equivalent:
        df = df[df.engine_equivalent]

    if df.empty:
        print("Nessuna riga corrisponde ai filtri.")
        return

    df = df.sort_values(args.sort, ascending=False)
    columns = COLUMNS + ["error"] if args.errors else COLUMNS
    print(df[columns].to_string(index=False))
    print(f"\n{len(df)} righe. Dettaglio di una: --puzzle {df.iloc[0].puzzle_id}")


if __name__ == "__main__":
    main()
