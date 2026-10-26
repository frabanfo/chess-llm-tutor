#!/usr/bin/env python3
"""Scarica il database puzzle di Lichess e ne estrae un campione stratificato.

    python scripts/download_puzzles.py --per-cell 25 --out data/sample.csv

Il file completo è ~300 MB compressi (~1 GB scompattato, ~5M puzzle). Viene
scaricato una volta sola in data/ e riusato.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from chesstutor.dataset import (  # noqa: E402
    PUZZLE_DB_URL, load_puzzles, stratified_sample, write_sample,
)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def ensure_database() -> Path:
    csv_path = DATA_DIR / "lichess_db_puzzle.csv"
    if csv_path.exists():
        print(f"Database già presente: {csv_path}")
        return csv_path

    DATA_DIR.mkdir(exist_ok=True)
    archive = DATA_DIR / "lichess_db_puzzle.csv.zst"
    if not archive.exists():
        print(f"Scarico {PUZZLE_DB_URL} (~300 MB)...")
        subprocess.run(["curl", "-L", "-o", str(archive), PUZZLE_DB_URL], check=True)

    print("Decomprimo...")
    decompress(archive, csv_path)
    return csv_path


def decompress(archive: Path, csv_path: Path) -> None:
    """Scompatta lo .zst con il modulo zstandard, o col binario zstd se manca."""
    try:
        import zstandard
    except ImportError:
        zstandard = None

    if zstandard is not None:
        tmp = csv_path.with_suffix(".csv.partial")
        with archive.open("rb") as src, tmp.open("wb") as dst:
            zstandard.ZstdDecompressor().copy_stream(src, dst)
        tmp.replace(csv_path)
        return

    if shutil.which("zstd") is None:
        sys.exit(
            "Serve un decompressore zstd. Installa il modulo Python:\n"
            "    pip install zstandard\n"
            "oppure il binario (apt install zstd / brew install zstd)."
        )
    subprocess.run(["zstd", "-d", "-f", str(archive), "-o", str(csv_path)], check=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--per-cell", type=int, default=25,
                        help="puzzle per ogni cella (fascia rating x tema)")
    parser.add_argument("--scan-limit", type=int, default=800_000,
                        help="quante righe leggere dal database prima di campionare")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--out", default="data/sample.csv")
    args = parser.parse_args()

    csv_path = ensure_database()
    print(f"Carico fino a {args.scan_limit:,} puzzle...")
    puzzles = load_puzzles(csv_path, limit=args.scan_limit)
    print(f"  {len(puzzles):,} puzzle dopo i filtri di qualità")

    sample = stratified_sample(puzzles, per_cell=args.per_cell, seed=args.seed)
    print(f"  {len(sample):,} puzzle nel campione stratificato")

    bad = 0
    for puzzle in sample:
        try:
            puzzle.validate()
        except ValueError as exc:
            print("  ATTENZIONE:", exc)
            bad += 1
    print(f"  {bad} puzzle non validi")

    write_sample(sample, args.out)
    print(f"Scritto {args.out}")


if __name__ == "__main__":
    main()
