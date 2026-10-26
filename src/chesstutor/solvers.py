"""I "risolutori" messi alla prova dal benchmark.

Tutti implementano la stessa interfaccia, così il runner non sa né gli
importa se dietro c'è un LLM, Stockfish o un generatore casuale. Le due
baseline non sono decorative: senza `RandomSolver` non si sa quale accuratezza
corrisponda a "zero conoscenza", e senza `StockfishSolver` a profondità
ridotta non si sa quanto valga il punteggio dell'LLM in termini di forza.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass

import chess

from .representations import build_prompt


@dataclass
class Answer:
    """Risposta di un risolutore, già normalizzata."""

    move: chess.Move | None      # None se non è stata estratta una mossa legale
    theme: str = ""
    explanation: str = ""
    raw: str = ""
    illegal_attempt: str = ""    # testo della mossa se era illegale/impossibile da leggere
    error: str = ""              # chiamata fallita (API, rifiuto, troncamento): non è una mossa illegale


class Solver:
    name = "base"

    def solve(self, board: chess.Board) -> Answer:
        raise NotImplementedError


class RandomSolver(Solver):
    """Baseline inferiore: mossa legale a caso. Stabilisce il pavimento."""

    name = "random"

    def __init__(self, seed: int = 0):
        self.rng = random.Random(seed)

    def solve(self, board: chess.Board) -> Answer:
        moves = list(board.legal_moves)
        return Answer(move=self.rng.choice(moves) if moves else None)


class StockfishSolver(Solver):
    """Baseline superiore, con profondità regolabile.

    A depth=1 è poco più che una ricerca greedy dei materiali: usarlo come
    termine di paragone rende leggibile il risultato dell'LLM ("gioca come
    Stockfish a profondità 2" dice molto più di "58% di accuratezza").
    """

    def __init__(self, engine, depth: int = 12, nodes: int | None = None):
        self.engine = engine
        self.depth = depth
        self.nodes = nodes
        # Anche a depth=1 Stockfish risolve >90% dei puzzle a ogni fascia di
        # rating: per una baseline che degradi con la difficoltà serve limitare
        # i nodi esplorati, non la profondità nominale.
        self.name = f"stockfish_n{nodes}" if nodes else f"stockfish_d{depth}"

    def solve(self, board: chess.Board) -> Answer:
        move = self.engine.best_move(board, depth=self.depth, nodes=self.nodes)
        return Answer(move=move, explanation=self.name.replace("_", " "))


MOVE_RE = re.compile(r"MOVE:\s*(.+)", re.IGNORECASE)
THEME_RE = re.compile(r"THEME:\s*(.+)", re.IGNORECASE)
WHY_RE = re.compile(r"WHY:\s*(.+)", re.IGNORECASE)


SAN_TOKEN = r"(?:[KQRBN]?[a-h]?[1-8]?x?[a-h][1-8](?:=?[QRBN])?|O-O(?:-O)?)[+#]?"
FALLBACK_RE = re.compile(rf"(?<![\w-])({SAN_TOKEN})(?![\w-])")
MOVE_NUMBER_RE = re.compile(r"^\d+\s*(?:\.+|…)\s*")
FIGURINES = str.maketrans({
    "♔": "K", "♕": "Q", "♖": "R", "♗": "B", "♘": "N",
    "♚": "K", "♛": "Q", "♜": "R", "♝": "B", "♞": "N",
    "×": "x", "–": "-", "—": "-",
})


def _normalise_move_text(text: str) -> str:
    """Riduce il contenuto della riga MOVE al solo token della mossa.

    Toglie markdown, numero di mossa ("1.", "23..."), figurine Unicode e
    annotazioni ("!", "?"), e converte l'arrocco scritto con gli zeri. Non
    tocca il contenuto della mossa: se resta illegale, resta illegale.
    """
    text = text.translate(FIGURINES).replace("*", "").replace("`", "").strip()
    text = MOVE_NUMBER_RE.sub("", text).strip()
    parts = text.split()
    token = parts[0].strip(".,;:!?\"'()[]") if parts else ""
    if re.fullmatch(r"0-0(-0)?[+#]?", token):
        token = token.replace("0", "O")
    return token


def parse_answer(text: str, board: chess.Board) -> Answer:
    """Estrae mossa/tema/spiegazione dalla risposta di un LLM.

    Il parsing è volutamente permissivo sulla notazione (accetta SAN e UCI, e
    ripulisce la punteggiatura) ma severo sulla legalità: una mossa illegale è
    un errore, non la si "aggiusta" cercando la più simile. Gonfiare
    l'accuratezza con correzioni benevole renderebbe il benchmark inutile.
    """
    move_text = ""
    match = MOVE_RE.search(text)
    if match:
        move_text = match.group(1)
    else:
        # Nessun formato rispettato: prendi il primo token che assomiglia a una mossa.
        fallback = FALLBACK_RE.search(text.translate(FIGURINES).replace("0-0", "O-O"))
        if fallback:
            move_text = fallback.group(1)

    cleaned = _normalise_move_text(move_text)
    move = None
    if cleaned:
        try:
            move = board.parse_san(cleaned)
        except (ValueError, chess.InvalidMoveError, chess.IllegalMoveError,
                chess.AmbiguousMoveError):
            try:
                candidate = chess.Move.from_uci(cleaned.lower())
                move = candidate if candidate in board.legal_moves else None
            except (ValueError, chess.InvalidMoveError):
                move = None

    theme = THEME_RE.search(text)
    why = WHY_RE.search(text)
    return Answer(
        move=move,
        theme=theme.group(1).strip() if theme else "",
        explanation=why.group(1).strip() if why else "",
        raw=text,
        illegal_attempt="" if move else cleaned,
    )


class LLMSolver(Solver):
    """Interroga un LLM tramite una funzione `complete(prompt) -> str`.

    Tenere la chiamata al modello fuori da questa classe significa che si può
    usare qualunque provider (o una cache su disco, o un mock nei test) senza
    toccare il benchmark.
    """

    def __init__(self, complete, representation: str = "piece_list", name: str | None = None):
        self.complete = complete
        self.representation = representation
        self.name = name or f"llm_{representation}"

    def solve(self, board: chess.Board) -> Answer:
        prompt = build_prompt(board, self.representation)
        try:
            text = self.complete(prompt)
        except Exception as exc:  # una chiamata fallita non deve fermare il run
            # Registrata come errore, non come mossa illegale: altrimenti un
            # rate limit gonfierebbe il tasso di illegalità del modello.
            return Answer(move=None, error=f"{type(exc).__name__}: {exc}")
        return parse_answer(text, board)


class CompletionError(RuntimeError):
    """Risposta senza testo utilizzabile (rifiuto, troncamento)."""


def anthropic_completer(
    model: str = "claude-opus-5-5",
    max_tokens: int = 16000,
    effort: str | None = "medium",
    max_retries: int = 5,
):
    """Crea una funzione `complete` che usa l'SDK Anthropic.

    Richiede `pip install anthropic` e la variabile d'ambiente ANTHROPIC_API_KEY.

    I modelli attuali ragionano prima di rispondere e i token di ragionamento
    contano in `max_tokens`: un limite basso tronca la risposta prima della
    riga MOVE. `temperature` non è più accettata, quindi la riproducibilità si
    affida a un `effort` fisso e alla cache. Con modelli che non supportano
    `effort` (es. Sonnet 4.5, Haiku 4.5) passare `effort=None`.
    """
    import anthropic

    client = anthropic.Anthropic(max_retries=max_retries)
    extra = {"output_config": {"effort": effort}} if effort else {}

    def complete(prompt: str) -> str:
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
            **extra,
        )
        text = "".join(b.text for b in response.content if b.type == "text")
        if response.stop_reason in ("refusal", "max_tokens") and "MOVE:" not in text.upper():
            raise CompletionError(f"stop_reason={response.stop_reason}")
        return text

    complete.cache_id = f"anthropic|{model}|max_tokens={max_tokens}|effort={effort}"
    return complete


def cached_completer(complete, cache_path: str, cache_id: str | None = None):
    """Avvolge un completer con una cache su disco (JSONL).

    Indispensabile: rilancerai il benchmark decine di volte mentre sistemi le
    metriche, e senza cache pagheresti ogni volta le stesse chiamate.

    La chiave include `cache_id` (modello e parametri; di default quello
    esposto dal completer): senza, cambiare modello restituirebbe in silenzio
    le risposte del modello precedente. Gli errori non finiscono in cache.
    """
    import hashlib
    import json
    import os

    cache: dict[str, str] = {}
    if os.path.exists(cache_path):
        with open(cache_path, encoding="utf-8") as fh:
            for line in fh:
                try:
                    entry = json.loads(line)
                    cache[entry["key"]] = entry["response"]
                except (json.JSONDecodeError, KeyError):
                    continue

    namespace = cache_id if cache_id is not None else getattr(complete, "cache_id", "")

    def wrapped(prompt: str) -> str:
        key = hashlib.sha256(f"{namespace}\0{prompt}".encode()).hexdigest()
        if key in cache:
            return cache[key]
        response = complete(prompt)
        cache[key] = response
        with open(cache_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"key": key, "model": namespace, "response": response}) + "\n")
        return response

    return wrapped
