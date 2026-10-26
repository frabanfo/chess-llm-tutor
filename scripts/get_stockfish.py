#!/usr/bin/env python3
"""Scarica il binario ufficiale di Stockfish dentro bin/ (utile su Windows).

    python scripts/get_stockfish.py

Su Linux e macOS conviene il package manager (apt/brew): lo script lo segnala
e si ferma. Su Windows non esiste un pacchetto comodo, quindi prende la release
da GitHub, sceglie la build in base alle istruzioni supportate dalla CPU e
verifica che il binario risponda al protocollo UCI.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import platform
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BIN_DIR = ROOT / "bin"
RELEASES_API = "https://api.github.com/repos/official-stockfish/Stockfish/releases/latest"

# Costanti di IsProcessorFeaturePresent (winnt.h).
PF_AVX2 = 40
PF_AVX512F = 41


def pick_build() -> str:
    """Sceglie la variante di build più veloce fra quelle eseguibili dalla CPU."""
    machine = platform.machine().lower()
    if machine in ("arm64", "aarch64"):
        return "windows-armv8"

    try:
        feature_present = ctypes.windll.kernel32.IsProcessorFeaturePresent
    except AttributeError:
        return "windows-x86-64-sse41-popcnt"

    if feature_present(PF_AVX512F):
        return "windows-x86-64-avx512"
    if feature_present(PF_AVX2):
        return "windows-x86-64-avx2"
    # Fallback compatibile con qualsiasi x86-64 recente.
    return "windows-x86-64-sse41-popcnt"


def asset_url(build: str) -> tuple[str, str]:
    request = urllib.request.Request(RELEASES_API, headers={"User-Agent": "chess-llm-tutor"})
    with urllib.request.urlopen(request) as response:
        release = json.load(response)

    wanted = f"stockfish-{build}.zip"
    for asset in release["assets"]:
        if asset["name"] == wanted:
            return release["tag_name"], asset["browser_download_url"]
    raise SystemExit(f"Nessun asset '{wanted}' nella release {release['tag_name']}.")


def download(url: str, dest: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "chess-llm-tutor"})
    with urllib.request.urlopen(request) as response, dest.open("wb") as out:
        total = int(response.headers.get("Content-Length", 0))
        done = 0
        while chunk := response.read(1 << 20):
            out.write(chunk)
            done += len(chunk)
            if total:
                print(f"\r  {done / 1e6:.0f}/{total / 1e6:.0f} MB", end="", flush=True)
    print()


def extract(archive: Path, dest_dir: Path) -> Path:
    """Scompatta lo zip in dest_dir e restituisce il percorso dell'eseguibile."""
    with zipfile.ZipFile(archive) as zf:
        zf.extractall(dest_dir)

    exes = [p for p in dest_dir.rglob("stockfish*.exe") if p.is_file()]
    if not exes:
        raise SystemExit(f"Nessun eseguibile trovato in {dest_dir}.")
    return max(exes, key=lambda p: p.stat().st_size)


def verify(exe: Path) -> str:
    """Avvia il binario e ne legge la riga di identificazione UCI."""
    proc = subprocess.run(
        [str(exe)], input="uci\nquit\n", capture_output=True, text=True, timeout=30,
    )
    for line in proc.stdout.splitlines():
        if line.startswith("id name"):
            return line.removeprefix("id name").strip()
    raise SystemExit(
        f"Il binario non ha risposto a UCI (exit {proc.returncode}).\n"
        "Se la CPU non supporta la build scelta, riprova con "
        "--build windows-x86-64-sse41-popcnt."
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--build", help="variante da scaricare (default: dedotta dalla CPU)")
    parser.add_argument("--force", action="store_true", help="riscarica anche se già presente")
    args = parser.parse_args()

    if sys.platform != "win32":
        raise SystemExit(
            "Su Linux/macOS usa il package manager:\n"
            "    sudo apt install stockfish\n"
            "    brew install stockfish"
        )

    BIN_DIR.mkdir(exist_ok=True)
    existing = sorted(BIN_DIR.rglob("stockfish*.exe"))
    if existing and not args.force:
        print(f"Stockfish già presente: {existing[0]}")
        print(f"  {verify(existing[0])}")
        return

    build = args.build or pick_build()
    tag, url = asset_url(build)
    print(f"Scarico Stockfish {tag} ({build}, ~73 MB)...")

    archive = BIN_DIR / f"stockfish-{build}.zip"
    download(url, archive)
    exe = extract(archive, BIN_DIR)
    archive.unlink()

    print(f"Installato: {exe}")
    print(f"  {verify(exe)}")
    print("\nengine.py lo trova da solo; per usarlo altrove:")
    print(f'  $env:STOCKFISH_PATH = "{exe}"')


if __name__ == "__main__":
    main()
