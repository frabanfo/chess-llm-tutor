"""chesstutor — benchmark di LLM su puzzle di scacchi + tutor personalizzato."""

from .dataset import Puzzle, load_puzzles, stratified_sample
from .engine import Engine, engine, find_stockfish
from .solvers import LLMSolver, RandomSolver, StockfishSolver, parse_answer

__all__ = [
    "Puzzle", "load_puzzles", "stratified_sample",
    "Engine", "engine", "find_stockfish",
    "LLMSolver", "RandomSolver", "StockfishSolver", "parse_answer",
]
__version__ = "0.1.0"
