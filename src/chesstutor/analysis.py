"""Analisi delle partite di un giocatore: dai PGN al profilo di debolezze.

È il ponte fra la parte sperimentale e l'applicazione. Il benchmark dice
quanto ci si può fidare dell'LLM; questo modulo produce il materiale su cui il
tutor lavora davvero — gli errori reali di una persona specifica.
"""

from __future__ import annotations

import io
from collections import Counter, defaultdict
from dataclasses import dataclass

import chess
import chess.pgn

from .engine import BLUNDER_THRESHOLD, MISTAKE_THRESHOLD, Engine

LICHESS_GAMES_URL = "https://lichess.org/api/games/user/{username}"


def fetch_games(username: str, max_games: int = 200, token: str | None = None,
                perf_type: str | None = "blitz,rapid,classical") -> str:
    """Scarica le partite di un utente da Lichess in formato PGN.

    L'endpoint fa streaming e non richiede autenticazione per le partite
    pubbliche, ma con un token personale i rate limit sono più generosi.
    """
    import requests

    params = {"max": max_games, "evals": "false", "clocks": "true", "opening": "true"}
    if perf_type:
        params["perfType"] = perf_type
    headers = {"Accept": "application/x-chess-pgn"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    response = requests.get(
        LICHESS_GAMES_URL.format(username=username),
        params=params, headers=headers, timeout=120,
    )
    response.raise_for_status()
    return response.text


@dataclass
class Mistake:
    game_id: str
    ply: int
    fen: str              # posizione prima dell'errore
    played_san: str
    best_san: str
    cp_loss: int
    label: str
    phase: str            # opening / middlegame / endgame
    time_left: float | None = None


def _phase(board: chess.Board) -> str:
    """Fase di gioco stimata dal materiale rimasto sulla scacchiera."""
    pieces = sum(
        len(board.pieces(pt, color))
        for pt in (chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN)
        for color in (chess.WHITE, chess.BLACK)
    )
    if board.fullmove_number <= 10:
        return "opening"
    return "endgame" if pieces <= 6 else "middlegame"


def analyse_game(
    game: chess.pgn.Game,
    engine: Engine,
    player: str,
    depth: int = 14,
    threshold: int = MISTAKE_THRESHOLD,
) -> list[Mistake]:
    """Trova gli errori di `player` in una partita.

    Analizza solo le mosse del giocatore indicato: dimezza il tempo di calcolo
    e le mosse dell'avversario non servono al profilo.
    """
    headers = game.headers
    if player.lower() == headers.get("White", "").lower():
        player_color = chess.WHITE
    elif player.lower() == headers.get("Black", "").lower():
        player_color = chess.BLACK
    else:
        return []

    game_id = headers.get("Site", "").rsplit("/", 1)[-1]
    board = game.board()
    mistakes: list[Mistake] = []
    # Tempo sul proprio orologio prima di muovere = quello registrato dopo la
    # propria mossa precedente (i PGN Lichess hanno [%clk] dopo ogni mossa).
    last_clock: dict[bool, float | None] = {chess.WHITE: None, chess.BLACK: None}

    for ply, node in enumerate(game.mainline()):
        move = node.move
        mover = board.turn
        time_left = last_clock[mover]
        last_clock[mover] = node.clock()
        if board.turn != player_color or board.is_game_over():
            board.push(move)
            continue
        # Salta le prime mosse: la teoria d'apertura produce falsi positivi.
        if board.fullmove_number <= 4:
            board.push(move)
            continue

        judgement = engine.judge(board, move, depth=depth)
        if judgement.cp_loss >= threshold:
            mistakes.append(Mistake(
                game_id=game_id,
                ply=ply,
                fen=board.fen(),
                played_san=board.san(move),
                best_san=board.san(judgement.best_move) if judgement.best_move else "",
                cp_loss=judgement.cp_loss,
                label=judgement.label,
                phase=_phase(board),
                time_left=time_left,
            ))
        board.push(move)

    return mistakes


def analyse_pgn_file(
    pgn_text: str, engine: Engine, player: str, depth: int = 14, max_games: int = 50
) -> list[Mistake]:
    stream = io.StringIO(pgn_text)
    all_mistakes: list[Mistake] = []
    for i in range(max_games):
        game = chess.pgn.read_game(stream)
        if game is None:
            break
        all_mistakes.extend(analyse_game(game, engine, player, depth=depth))
    return all_mistakes


def weakness_profile(mistakes: list[Mistake]) -> dict:
    """Riassume gli errori in un profilo interpretabile.

    Il conteggio grezzo non basta: un giocatore fa più mosse in mediogioco che
    in finale, quindi confrontare i valori assoluti fra fasi è fuorviante. Qui
    riportiamo sia i conteggi sia la perdita media, che è meno sensibile a
    quanto spesso una fase si presenta.
    """
    by_phase = defaultdict(list)
    for m in mistakes:
        by_phase[m.phase].append(m.cp_loss)

    blunders = [m for m in mistakes if m.cp_loss >= BLUNDER_THRESHOLD]
    return {
        "total_mistakes": len(mistakes),
        "blunders": len(blunders),
        "avg_cp_loss": (sum(m.cp_loss for m in mistakes) / len(mistakes)) if mistakes else 0,
        "by_phase": {
            phase: {
                "count": len(losses),
                "avg_cp_loss": sum(losses) / len(losses),
            }
            for phase, losses in sorted(by_phase.items())
        },
        "by_label": dict(Counter(m.label for m in mistakes)),
        "worst": sorted(mistakes, key=lambda m: -m.cp_loss)[:10],
    }


def mistakes_to_puzzles(mistakes: list[Mistake], engine: Engine, depth: int = 18) -> list[dict]:
    """Trasforma gli errori in puzzle personalizzati.

    Tiene solo le posizioni con una soluzione netta: se la seconda miglior
    mossa è quasi buona quanto la prima, non è un puzzle, è una scelta di
    piano — e un "puzzle" senza soluzione unica frustra chi lo prova.
    """
    puzzles = []
    for m in mistakes:
        board = chess.Board(m.fen)
        evals = engine.evaluate(board, depth=depth, multipv=2)
        if len(evals) < 2 or not evals[0].best_move:
            continue
        margin = evals[0].cp - evals[1].cp
        if margin < 200:
            continue
        puzzles.append({
            "fen": m.fen,
            "solution_uci": evals[0].best_move.uci(),
            "solution_san": board.san(evals[0].best_move),
            "played_san": m.played_san,
            "margin_cp": margin,
            "source_game": m.game_id,
            "phase": m.phase,
        })
    return puzzles


EXPLAIN_PROMPT = """You are a chess coach explaining a mistake to a student rated around {rating}.

Position (the student was to move):
{position}

The student played: {played}
The engine's best move: {best}
The engine's main line after the best move: {pv}
Evaluation swing: {cp_loss} centipawns

Write two short paragraphs:
1. What the student's move overlooked — be concrete, name the squares and pieces.
2. Why the engine's move is better, following the main line above.

Do not invent variations that are not in the main line given. Do not use jargon
without explaining it. Address the student as "you"."""


def build_explanation_prompt(
    mistake: Mistake, pv_san: list[str], rating: int = 1500, representation: str = "piece_list"
) -> str:
    """Prompt per la spiegazione, ancorato all'output del motore.

    L'istruzione di non inventare varianti è la parte importante: è lì che gli
    LLM sbagliano sistematicamente, producendo linee illegali dette con grande
    sicurezza. Fornire la PV e vietare tutto il resto sposta il compito da
    "calcola" a "spiega ciò che ti è stato dato", che è quello che sanno fare.
    """
    from .representations import REPRESENTATIONS

    board = chess.Board(mistake.fen)
    return EXPLAIN_PROMPT.format(
        rating=rating,
        position=REPRESENTATIONS[representation](board),
        played=mistake.played_san,
        best=mistake.best_san,
        pv=" ".join(pv_san),
        cp_loss=mistake.cp_loss,
    )
