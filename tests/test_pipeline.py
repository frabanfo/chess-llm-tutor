"""Test della pipeline. Eseguire con: pytest -q

I test che richiedono Stockfish si saltano automaticamente se il binario non
c'è, così il resto della suite gira comunque (utile in CI).
"""

from __future__ import annotations

import sys
from pathlib import Path

import chess
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from chesstutor.dataset import load_puzzles  # noqa: E402
from chesstutor.representations import REPRESENTATIONS, build_prompt  # noqa: E402
from chesstutor.solvers import RandomSolver, parse_answer  # noqa: E402
from chesstutor.metrics import wilson_interval  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "puzzles_sample.csv"


@pytest.fixture(scope="module")
def puzzles():
    return load_puzzles(FIXTURE, min_popularity=0, min_plays=0)


def test_fixtures_load(puzzles):
    assert len(puzzles) >= 5


def test_all_moves_legal(puzzles):
    for puzzle in puzzles:
        puzzle.validate()  # solleva se una mossa è illegale


def test_setup_fen_is_not_puzzle_fen(puzzles):
    """La FEN del CSV è la posizione PRIMA della mossa avversaria.

    Se questo test fallisce, qualcuno ha "semplificato" dataset.py saltando
    l'applicazione della prima mossa — e tutte le metriche diventano sbagliate.
    """
    for puzzle in puzzles:
        assert puzzle.fen != puzzle.setup_fen
        assert chess.Board(puzzle.setup_fen).turn != puzzle.board.turn


def test_solution_is_legal_from_puzzle_position(puzzles):
    for puzzle in puzzles:
        board = puzzle.board
        assert chess.Move.from_uci(puzzle.first_move) in board.legal_moves
        assert len(puzzle.solution_san) == len(puzzle.solution)


def test_representations_all_render(puzzles):
    board = puzzles[0].board
    for name in REPRESENTATIONS:
        text = build_prompt(board, name)
        assert "MOVE:" in text and len(text) > 100


def test_piece_list_mentions_every_piece(puzzles):
    board = puzzles[0].board
    text = REPRESENTATIONS["piece_list"](board)
    for square, piece in board.piece_map().items():
        assert chess.square_name(square) in text, f"manca {piece} in {chess.square_name(square)}"


@pytest.mark.parametrize("text,expected", [
    ("MOVE: e4\nTHEME: x\nWHY: y", "e2e4"),
    ("MOVE: **e4**", "e2e4"),
    ("MOVE: e2e4", "e2e4"),
    ("the best move is e4 here", "e2e4"),
    ("MOVE: Qh8#", None),          # illegale nella posizione iniziale
    ("non ne ho idea", None),
    ("MOVE: 1. e4", "e2e4"),        # numero di mossa
    ("MOVE: 1...e4", "e2e4"),
    ("MOVE: Nf3!?", "g1f3"),        # annotazioni
    ("MOVE: ♘f3", "g1f3"),     # figurina Unicode
    ("MOVE: e4 (pawn to e4)", "e2e4"),
])
def test_parser(text, expected):
    board = chess.Board()
    answer = parse_answer(text, board)
    assert (answer.move.uci() if answer.move else None) == expected


def test_parser_rejects_illegal_without_guessing():
    """Una mossa illegale resta illegale: nessuna correzione benevola."""
    board = chess.Board()
    answer = parse_answer("MOVE: Nf6", board)  # è il turno del Bianco
    assert answer.move is None
    assert answer.illegal_attempt == "Nf6"


@pytest.mark.parametrize("text", ["MOVE: 0-0", "MOVE: O-O", "I castle: 0-0"])
def test_parser_accepts_castling_with_zeros(text):
    board = chess.Board("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1")
    assert parse_answer(text, board).move == chess.Move.from_uci("e1g1")


def test_llm_error_is_not_an_illegal_move():
    """Una chiamata fallita è un errore, non una mossa illegale del modello."""
    from chesstutor.solvers import LLMSolver

    def boom(prompt):
        raise TimeoutError("rate limited")

    answer = LLMSolver(boom).solve(chess.Board())
    assert answer.move is None
    assert "rate limited" in answer.error
    assert answer.illegal_attempt == ""


def test_cache_is_keyed_by_model(tmp_path):
    """Cambiare modello non deve restituire le risposte del modello precedente."""
    from chesstutor.solvers import cached_completer

    cache = str(tmp_path / "cache.jsonl")
    a = cached_completer(lambda p: "risposta A", cache, cache_id="model-a")
    assert a("prompt") == "risposta A"
    # Wrapper nuovi rileggono il file, come in un secondo run.
    b = cached_completer(lambda p: "risposta B", cache, cache_id="model-a")
    c = cached_completer(lambda p: "risposta C", cache, cache_id="model-b")
    assert b("prompt") == "risposta A"     # stesso modello: cache
    assert c("prompt") == "risposta C"     # modello diverso: nuova chiamata


@pytest.mark.parametrize("said,theme,expected", [
    ("fork", "fork", True),
    ("Forks", "fork", True),
    ("discovered attack", "discoveredAttack", True),
    ("back-rank mate", "backRankMate", True),
    ("pinned piece", "pin", True),
    ("X-ray", "xRayAttack", True),
    ("attack", "discoveredAttack", False),   # parola generica
    ("attack", "xRayAttack", False),
    ("piece", "hangingPiece", False),
    ("mate", "backRankMate", False),
    ("spinning", "pin", False),              # sottostringa, non parola
    ("", "fork", False),
])
def test_theme_matching(said, theme, expected):
    from chesstutor.benchmark import _theme_matches
    assert _theme_matches(said, theme) is expected


def test_theme_matches_any_puzzle_theme():
    from chesstutor.benchmark import _any_theme_matches
    assert _any_theme_matches("sacrifice", ("fork", "sacrifice", "middlegame"))
    assert not _any_theme_matches("middlegame", ("fork", "middlegame"))


def test_slower_mate_is_not_equivalent():
    """In centipawn matto in 1 e matto in 10 distano 9 cp: non devono bastare."""
    from chesstutor.benchmark import _is_equivalent
    from chesstutor.engine import MoveJudgement

    def j(cp_loss, before, after):
        move = chess.Move.from_uci("e2e4")
        return MoveJudgement(move, move, 0, 0, cp_loss, False, before, after)

    assert _is_equivalent(j(0, 2, 2))
    assert _is_equivalent(j(0, 3, 1))       # più rapido va bene
    assert not _is_equivalent(j(9, 1, 10))
    assert not _is_equivalent(j(5000, 2, None))
    assert _is_equivalent(j(20, None, None))
    assert not _is_equivalent(j(40, None, None))


def test_weakness_profile():
    from chesstutor.analysis import Mistake, weakness_profile

    mistakes = [
        Mistake("g1", 20, "", "Qh5", "Qxd5", 900, "blunder", "middlegame"),
        Mistake("g1", 40, "", "Kf2", "Ke2", 100, "mistake", "endgame"),
        Mistake("g2", 30, "", "Rd1", "Re1", 200, "blunder", "middlegame"),
    ]
    profile = weakness_profile(mistakes)
    assert profile["total_mistakes"] == 3
    assert profile["blunders"] == 2
    assert profile["by_phase"]["middlegame"] == {"count": 2, "avg_cp_loss": 550}
    assert profile["worst"][0].cp_loss == 900
    assert weakness_profile([])["avg_cp_loss"] == 0


def test_random_solver_always_legal(puzzles):
    solver = RandomSolver(seed=1)
    for puzzle in puzzles:
        answer = solver.solve(puzzle.board)
        assert answer.move in puzzle.board.legal_moves


def test_wilson_interval():
    lo, hi = wilson_interval(5, 10)
    assert lo < 0.5 < hi
    assert wilson_interval(0, 0) == (0.0, 0.0)
    lo, hi = wilson_interval(10, 10)
    assert hi == 1.0 and lo > 0.6


# --- test che richiedono Stockfish ---

stockfish = pytest.importorskip("chess.engine")


@pytest.fixture(scope="module")
def engine():
    from chesstutor.engine import Engine, find_stockfish
    try:
        find_stockfish()
    except RuntimeError:
        pytest.skip("Stockfish non installato")
    eng = Engine()
    yield eng
    eng.close()


def test_engine_finds_mate_in_one(engine):
    board = chess.Board("r1bqkbnr/pppp1ppp/2n5/4p3/2B1P3/5Q2/PPPP1PPP/RNB1K1NR w KQkq - 4 4")
    evals = engine.evaluate(board, depth=12)
    assert evals[0].mate_in == 1
    assert board.san(evals[0].best_move) == "Qxf7#"


def test_engine_returns_empty_on_finished_game(engine):
    board = chess.Board("r1bqkbnr/pppp1Qpp/2n5/4p3/2B1P3/8/PPPP1PPP/RNB1K1NR b KQkq - 0 4")
    assert board.is_checkmate()
    assert engine.evaluate(board) == []


def test_judge_penalises_a_blunder(engine):
    board = chess.Board("rnbqkbnr/ppp2ppp/8/3pp3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 0 3")
    good = engine.judge(board, chess.Move.from_uci("f3e5"), depth=12)
    bad = engine.judge(board, chess.Move.from_uci("f3g1"), depth=12)
    assert bad.cp_loss > good.cp_loss


def test_judge_reports_mate_lengths(engine):
    # Matto in 1 (Qxf7#) disponibile; Qf3-e2 lo lascia sfuggire.
    board = chess.Board("r1bqkbnr/pppp1ppp/2n5/4p3/2B1P3/5Q2/PPPP1PPP/RNB1K1NR w KQkq - 4 4")
    mate = engine.judge(board, chess.Move.from_uci("f3f7"), depth=12)
    assert mate.mate_before == 1 and mate.mate_after == 1
    quiet = engine.judge(board, chess.Move.from_uci("f3e2"), depth=12)
    assert quiet.mate_after is None or quiet.mate_after > 1


def test_node_limited_baseline_is_legal(puzzles, engine):
    from chesstutor.solvers import StockfishSolver
    solver = StockfishSolver(engine, nodes=1)
    assert solver.name == "stockfish_n1"
    for puzzle in puzzles:
        assert solver.solve(puzzle.board).move in puzzle.board.legal_moves


# Donna bianca in d1, nera in d5 sulla colonna aperta: Qxd5 la vince, Qh5?? la regala.
HANGING_QUEEN_PGN = """[Event "test"]
[Site "https://lichess.org/abcd1234"]
[White "me"]
[Black "opponent"]
[SetUp "1"]
[FEN "4k3/8/8/3q4/8/8/8/3QK3 w - - 0 20"]

20. Qh5+ { [%clk 0:01:30] } Qxh5 { [%clk 0:01:20] } *
"""


def test_analyse_game_finds_hung_queen(engine):
    import io
    import chess.pgn
    from chesstutor.analysis import analyse_game, mistakes_to_puzzles

    game = chess.pgn.read_game(io.StringIO(HANGING_QUEEN_PGN))
    mistakes = analyse_game(game, engine, "me", depth=10)
    assert len(mistakes) == 1
    m = mistakes[0]
    assert (m.played_san, m.best_san, m.label, m.game_id) == ("Qh5+", "Qxd5", "blunder", "abcd1234")
    assert analyse_game(game, engine, "nobody", depth=10) == []

    puzzles = mistakes_to_puzzles(mistakes, engine, depth=10)
    assert len(puzzles) == 1 and puzzles[0]["solution_san"] == "Qxd5"


def test_benchmark_end_to_end(puzzles, engine, tmp_path):
    from chesstutor.benchmark import run_benchmark
    from chesstutor.solvers import StockfishSolver

    out = tmp_path / "r.csv"
    results = run_benchmark(
        puzzles[:3], [StockfishSolver(engine, depth=14)], engine,
        out, judge_depth=10, verbose=False,
    )
    assert len(results) == 3
    assert all(r.legal for r in results)
    # Stockfish a depth 14 deve risolvere quasi tutti i puzzle di questo campione.
    assert sum(r.exact_match or r.engine_equivalent for r in results) >= 2
    assert out.exists()
