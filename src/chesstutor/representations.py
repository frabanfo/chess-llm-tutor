"""Modi diversi di descrivere una posizione a un LLM.

Questa è la variabile indipendente centrale dell'esperimento. L'ipotesi è che
la FEN nuda sia una rappresentazione pessima per un modello linguistico — è
compatta ma richiede di "decomprimere" mentalmente le case vuote — mentre una
lista esplicita di pezzi con le loro caselle elimina quel lavoro.

Ogni funzione prende una `chess.Board` e restituisce una stringa.
"""

from __future__ import annotations

import chess

PIECE_NAMES = {
    chess.PAWN: "pedone", chess.KNIGHT: "cavallo", chess.BISHOP: "alfiere",
    chess.ROOK: "torre", chess.QUEEN: "donna", chess.KING: "re",
}
PIECE_NAMES_EN = {
    chess.PAWN: "pawn", chess.KNIGHT: "knight", chess.BISHOP: "bishop",
    chess.ROOK: "rook", chess.QUEEN: "queen", chess.KING: "king",
}


def fen(board: chess.Board) -> str:
    """Rappresentazione minima: la FEN e basta."""
    return board.fen()


def ascii_board(board: chess.Board) -> str:
    """Diagramma ASCII con coordinate, più la FEN come riferimento."""
    rows = []
    for rank in range(7, -1, -1):
        cells = []
        for file in range(8):
            piece = board.piece_at(chess.square(file, rank))
            cells.append(piece.symbol() if piece else ".")
        rows.append(f"{rank + 1} | " + " ".join(cells))
    rows.append("   " + "-" * 17)
    rows.append("    " + " ".join("abcdefgh"))
    side = "White" if board.turn == chess.WHITE else "Black"
    return "\n".join(rows) + f"\n\nSide to move: {side}\nFEN: {board.fen()}"


def piece_list(board: chess.Board, lang: str = "en") -> str:
    """Elenco esplicito di ogni pezzo e della sua casella.

    Rimuove del tutto il lavoro di parsing della FEN. Se questa
    rappresentazione batte la FEN nuda, il collo di bottiglia del modello è
    percettivo, non tattico — ed è il risultato più interessante del benchmark.
    """
    names = PIECE_NAMES if lang == "it" else PIECE_NAMES_EN
    lines = []
    for color, label in ((chess.WHITE, "White"), (chess.BLACK, "Black")):
        parts = []
        for piece_type in (chess.KING, chess.QUEEN, chess.ROOK,
                           chess.BISHOP, chess.KNIGHT, chess.PAWN):
            squares = board.pieces(piece_type, color)
            for sq in sorted(squares):
                parts.append(f"{names[piece_type]} {chess.square_name(sq)}")
        lines.append(f"{label}: " + ", ".join(parts))

    side = "White" if board.turn == chess.WHITE else "Black"
    lines.append(f"Side to move: {side}")
    if board.is_check():
        lines.append("The side to move is in check.")
    return "\n".join(lines)


def piece_list_with_moves(board: chess.Board) -> str:
    """Lista dei pezzi + tutte le mosse legali in SAN.

    Fornire le mosse legali elimina un'intera classe di errori (il modello che
    propone mosse illegali) e isola la vera domanda: sa scegliere quella
    giusta? Confrontare questa condizione con `piece_list` separa "non sa
    quali mosse esistono" da "non sa quale mossa è buona".
    """
    legal = sorted(board.san(m) for m in board.legal_moves)
    return piece_list(board) + "\n\nLegal moves: " + ", ".join(legal)


def pgn_context(board: chess.Board, history_plies: int = 12) -> str:
    """La posizione descritta tramite la sequenza di mosse che l'ha prodotta.

    Richiede una board con lo stack delle mosse popolato; se non c'è, ricade
    sulla FEN. Ha senso per analizzare partite reali, meno per i puzzle isolati.
    """
    if not board.move_stack:
        return fen(board)
    replay = chess.Board()
    sans = []
    for move in board.move_stack:
        sans.append(replay.san(move))
        replay.push(move)
    tail = sans[-history_plies:]
    return "Moves so far: " + " ".join(tail) + f"\n\nFEN: {board.fen()}"


REPRESENTATIONS = {
    "fen": fen,
    "ascii": ascii_board,
    "piece_list": piece_list,
    "piece_list_moves": piece_list_with_moves,
}


SOLVE_PROMPT = """You are analysing a chess position. Find the single best move.

{position}

Respond in exactly this format, nothing else:
MOVE: <the move in standard algebraic notation, e.g. Nxf7+ or Qh5#>
THEME: <the tactical motif in one or two words, e.g. fork, back rank mate>
WHY: <one sentence explaining why the move wins>"""


def build_prompt(board: chess.Board, representation: str = "piece_list") -> str:
    render = REPRESENTATIONS[representation]
    return SOLVE_PROMPT.format(position=render(board))
