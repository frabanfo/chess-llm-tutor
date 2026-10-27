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

    def solve_puzzle(self, puzzle) -> Answer:
        """Punto d'ingresso del runner. Di default guarda solo la scacchiera;
        i risolutori che devono conoscere il puzzle (es. i bracci di RQ3 che
        suggeriscono il tema) lo ridefiniscono."""
        return self.solve(puzzle.board)


class RandomSolver(Solver):
    """Baseline inferiore: mossa legale a caso. Stabilisce il pavimento."""

    name = "random"

    def __init__(self, seed: int = 0):
        self.rng = random.Random(seed)

    def solve(self, board: chess.Board) -> Answer:
        moves = list(board.legal_moves)
        return Answer(move=self.rng.choice(moves) if moves else None)


PIECE_VALUES = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3,
                chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 0}


class GreedySolver(Solver):
    """Baseline intermedia: gioca la mossa "visibile" senza calcolare.

    Matto in 1 se c'è; altrimenti la cattura che rende di più (valore preso,
    meno il pezzo che cattura se la casa è difesa); altrimenti uno scacco;
    altrimenti una mossa a caso. Misura quanti puzzle si risolvono senza
    vedere la risposta avversaria, che è l'ipotesi di RQ2. Stockfish non va
    bene per questo ruolo: anche limitato a 1 nodo completa una ricerca a
    profondità 2 e risolve >90% dei puzzle a ogni fascia di rating.
    """

    name = "greedy"

    def __init__(self, seed: int = 0):
        self.rng = random.Random(seed)

    @staticmethod
    def _capture_gain(board: chess.Board, move: chess.Move) -> int:
        if board.is_en_passant(move):
            victim = 1
        else:
            piece = board.piece_at(move.to_square)
            victim = PIECE_VALUES[piece.piece_type] if piece else 0
        if move.promotion:
            victim += PIECE_VALUES[move.promotion] - 1
        attacker = PIECE_VALUES[board.piece_type_at(move.from_square)]
        board.push(move)
        defended = board.is_attacked_by(board.turn, move.to_square)
        board.pop()
        return victim - (attacker if defended else 0)

    def solve(self, board: chess.Board) -> Answer:
        moves = sorted(board.legal_moves, key=lambda m: m.uci())  # ordine stabile
        if not moves:
            return Answer(move=None)
        for move in moves:
            board.push(move)
            mate = board.is_checkmate()
            board.pop()
            if mate:
                return Answer(move=move, explanation="mate in 1")
        gains = [(self._capture_gain(board, m), m) for m in moves
                 if board.is_capture(m) or m.promotion]
        best = max(gains, key=lambda g: g[0], default=None)
        if best and best[0] > 0:
            return Answer(move=best[1], explanation=f"capture +{best[0]}")
        checks = [m for m in moves if board.gives_check(m)]
        if checks:
            return Answer(move=checks[0], explanation="check")
        return Answer(move=self.rng.choice(moves))


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
        # Attenzione: Stockfish completa sempre almeno una iterazione, quindi
        # con nodes=1 esplora comunque ~60 nodi a profondità 2. Come baseline
        # debole usare GreedySolver.
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


def completer_cache_id(model: str, max_tokens: int, effort: str | None) -> str:
    """Identifica modello e parametri nella chiave di cache."""
    return f"anthropic|{model}|max_tokens={max_tokens}|effort={effort}"


def request_params(prompt: str, model: str, max_tokens: int, effort: str | None) -> dict:
    """Parametri di una richiesta Messages: identici per chiamate dirette e batch."""
    params = {"model": model, "max_tokens": max_tokens,
              "messages": [{"role": "user", "content": prompt}]}
    if effort:
        params["output_config"] = {"effort": effort}
    return params


def response_text(response) -> str:
    """Testo di una risposta; solleva CompletionError se è inutilizzabile.

    Un rifiuto o una risposta troncata senza riga MOVE è un errore della
    chiamata, non una mossa illegale del modello.
    """
    text = "".join(b.text for b in response.content if b.type == "text")
    if response.stop_reason in ("refusal", "max_tokens") and "MOVE:" not in text.upper():
        raise CompletionError(f"stop_reason={response.stop_reason}")
    return text


def anthropic_completer(
    model: str = "claude-sonnet-5-5",
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
    `effort` (es. Haiku 4.5) passare `effort=None`.

    Niente fallback automatico su un altro modello in caso di rifiuto: nel
    benchmark la risposta di un modello diverso contaminerebbe i risultati, e
    un rifiuto va registrato come errore.
    """
    import anthropic

    client = anthropic.Anthropic(max_retries=max_retries)

    def complete(prompt: str) -> str:
        response = client.messages.create(**request_params(prompt, model, max_tokens, effort))
        return response_text(response)

    complete.cache_id = completer_cache_id(model, max_tokens, effort)
    return complete


def cache_key(namespace: str, prompt: str) -> str:
    import hashlib
    return hashlib.sha256(f"{namespace}\0{prompt}".encode()).hexdigest()


def append_to_cache(cache_path: str, key: str, namespace: str, response: str) -> None:
    import json
    with open(cache_path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"key": key, "model": namespace, "response": response}) + "\n")


def load_cache(cache_path: str) -> dict[str, str]:
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
    return cache


def cached_completer(complete, cache_path: str, cache_id: str | None = None,
                     cache_only: bool = False):
    """Avvolge un completer con una cache su disco (JSONL).

    Indispensabile: rilancerai il benchmark decine di volte mentre sistemi le
    metriche, e senza cache pagheresti ogni volta le stesse chiamate.

    La chiave include `cache_id` (modello e parametri; di default quello
    esposto dal completer): senza, cambiare modello restituirebbe in silenzio
    le risposte del modello precedente. Gli errori non finiscono in cache.

    Con `cache_only=True` un prompt assente dalla cache solleva
    CompletionError invece di chiamare l'API: dopo un batch, un prompt che non
    combacia diventa una riga `error` visibile, non una spesa a prezzo pieno.
    """
    cache = load_cache(cache_path)
    namespace = cache_id if cache_id is not None else getattr(complete, "cache_id", "")

    def wrapped(prompt: str) -> str:
        key = cache_key(namespace, prompt)
        if key in cache:
            return cache[key]
        if cache_only:
            raise CompletionError("not in cache")
        response = complete(prompt)
        cache[key] = response
        append_to_cache(cache_path, key, namespace, response)
        return response

    return wrapped
