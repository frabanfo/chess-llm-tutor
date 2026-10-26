"""Report HTML del tutor: profilo, errori peggiori spiegati, puzzle personalizzati.

Un unico file autonomo (CSS inline, scacchiere SVG generate da python-chess),
così si apre con un doppio clic e si può allegare o pubblicare senza dipendenze.
Le varianti mostrate vengono tutte dalla PV di Stockfish: il testo dell'LLM, se
c'è, è affiancato alla linea del motore, mai al posto suo.
"""

from __future__ import annotations

import html
from dataclasses import dataclass

import chess
import chess.svg

from .analysis import CP_LOSS_CAP, Mistake
from .engine import MATE_SCORE

PLAYED_COLOR = "#e34948cc"
BEST_COLOR = "#1baf7acc"
BOARD_COLORS = {"square light": "#ebe6da", "square dark": "#a7a093",
                "margin": "#00000000", "coord": "#52514e"}


@dataclass
class ExplainedMistake:
    mistake: Mistake
    pv_san: list[str]          # linea principale di Stockfish dopo la mossa migliore
    explanation: str = ""      # testo dell'LLM; vuoto se non richiesto


def board_svg(fen: str, played: str = "", best: str = "", size: int = 300) -> str:
    """Scacchiera dal punto di vista di chi muove, con frecce per le due mosse."""
    board = chess.Board(fen)
    arrows = []
    for san, color in ((played, PLAYED_COLOR), (best, BEST_COLOR)):
        if san:
            try:
                move = board.parse_san(san)
            except ValueError:
                continue
            arrows.append(chess.svg.Arrow(move.from_square, move.to_square, color=color))
    return chess.svg.board(board, orientation=board.turn, arrows=arrows, size=size,
                           colors=BOARD_COLORS)


def _game_link(m: Mistake) -> str:
    if not m.game_id:
        return ""
    url = f"https://lichess.org/{html.escape(m.game_id)}#{m.ply}"
    return f'<a href="{url}" target="_blank" rel="noopener">partita {html.escape(m.game_id)}</a>'


def _clock(seconds: float | None) -> str:
    if seconds is None:
        return ""
    minutes, secs = divmod(int(seconds), 60)
    return f"{minutes}:{secs:02d} sull'orologio"


def _loss(cp_loss: int) -> str:
    """I matti sono compressi a ~MATE_SCORE: mostrare "−9999 cp" non dice nulla."""
    return "matto in gioco" if cp_loss >= MATE_SCORE // 2 else f"−{cp_loss} cp"


def _stat(value: str, label: str) -> str:
    return f'<div class="stat"><div class="v">{value}</div><div class="l">{label}</div></div>'


CSS = """
:root { --surface:#fcfcfb; --card:#ffffff; --ink:#0b0b0b; --ink-2:#52514e; --muted:#898781;
  --line:#e1e0d9; --bad:#c8302f; --good:#0f8a5f; --accent:#2a78d6; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {
  --surface:#1a1a19; --card:#232322; --ink:#ffffff; --ink-2:#c3c2b7; --muted:#898781;
  --line:#2c2c2a; --bad:#e66767; --good:#199e70; --accent:#3987e5; } }
:root[data-theme="dark"] { --surface:#1a1a19; --card:#232322; --ink:#ffffff; --ink-2:#c3c2b7;
  --muted:#898781; --line:#2c2c2a; --bad:#e66767; --good:#199e70; --accent:#3987e5; }
* { box-sizing:border-box; }
body { margin:0; background:var(--surface); color:var(--ink);
  font:16px/1.55 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width:1040px; margin:0 auto; padding:32px 16px 64px; }
h1 { font-size:28px; margin:0 0 4px; } h2 { font-size:20px; margin:40px 0 12px; }
.sub { color:var(--ink-2); margin:0 0 24px; }
.stats { display:grid; grid-template-columns:repeat(auto-fit,minmax(140px,1fr)); gap:12px; }
.stat { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:14px 16px; }
.stat .v { font-size:24px; font-weight:650; font-variant-numeric:tabular-nums; }
.stat .l { color:var(--ink-2); font-size:13px; }
table { border-collapse:collapse; width:100%; background:var(--card); border:1px solid var(--line);
  border-radius:10px; overflow:hidden; font-variant-numeric:tabular-nums; }
th, td { text-align:left; padding:8px 12px; border-bottom:1px solid var(--line); font-size:14px; }
th { color:var(--ink-2); font-weight:600; } tr:last-child td { border-bottom:0; }
.card { display:grid; grid-template-columns:300px 1fr; gap:24px; background:var(--card);
  border:1px solid var(--line); border-radius:12px; padding:20px; margin:0 0 16px; }
.card svg { width:100%; height:auto; display:block; }
.moves { display:flex; flex-wrap:wrap; gap:8px 20px; margin:4px 0 10px; }
.played { color:var(--bad); font-weight:650; } .best { color:var(--good); font-weight:650; }
.meta { color:var(--muted); font-size:13px; }
.pv { font-family:ui-monospace, Consolas, monospace; font-size:14px; color:var(--ink-2); }
.expl p { margin:8px 0; }
.note { color:var(--muted); font-style:italic; }
details summary { cursor:pointer; color:var(--accent); }
.grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(220px,1fr)); gap:16px; }
.puzzle { background:var(--card); border:1px solid var(--line); border-radius:12px; padding:14px; }
.puzzle svg { width:100%; height:auto; display:block; margin-bottom:8px; }
a { color:var(--accent); }
@media (max-width:640px) { .card { grid-template-columns:1fr; } }
"""


def render_report(
    player: str,
    profile: dict,
    explained: list[ExplainedMistake],
    puzzles: list[dict],
    games_analysed: int,
    model: str = "",
) -> str:
    esc = html.escape
    parts = [
        "<!doctype html><html lang='it'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width, initial-scale=1'>",
        f"<title>Tutor scacchi · {esc(player)}</title><style>{CSS}</style></head><body><main>",
        f"<h1>I tuoi errori, spiegati</h1><p class='sub'>{esc(player)} · {games_analysed} "
        "partite analizzate con Stockfish</p>",
        "<div class='stats'>",
        _stat(str(profile["total_mistakes"]), "errori (≥ 80 cp)"),
        _stat(str(profile["blunders"]), "blunder (≥ 150 cp)"),
        _stat(f"{profile['avg_cp_loss']:.0f}", f"cp persi in media per errore (max {CP_LOSS_CAP})"),
        _stat(f"{profile['total_mistakes'] / games_analysed:.1f}" if games_analysed else "–",
              "errori per partita"),
    ]
    if profile.get("time_trouble") is not None:
        parts.append(_stat(f"{profile['time_trouble']:.0%}", "errori con meno di 30 s"))
    parts.append("</div>")

    parts.append("<h2>Dove sbagli</h2><table><tr><th>Fase</th><th>Errori</th>"
                 "<th>cp persi in media</th></tr>")
    for phase, row in profile["by_phase"].items():
        parts.append(f"<tr><td>{esc(phase)}</td><td>{row['count']}</td>"
                     f"<td>{row['avg_cp_loss']:.0f}</td></tr>")
    parts.append("</table>")

    parts.append(f"<h2>I tuoi {len(explained)} errori peggiori</h2>")
    for i, e in enumerate(explained, 1):
        m = e.mistake
        meta = " · ".join(x for x in (m.phase, _clock(m.time_left), _game_link(m)) if x)
        if e.explanation:
            paras = "".join(f"<p>{esc(p)}</p>" for p in e.explanation.split("\n") if p.strip())
            note = f"<p class='meta'>Spiegazione scritta da {esc(model)} a partire dalla linea del motore.</p>" if model else ""
            body = f"<div class='expl'>{paras}{note}</div>"
        else:
            body = "<p class='note'>Spiegazione non generata (lancia il tutor con --explain).</p>"
        parts.append(
            f"<div class='card'><div>{board_svg(m.fen, m.played_san, m.best_san)}</div><div>"
            f"<div class='meta'>#{i} · {esc(m.label)} · {_loss(m.cp_loss)}</div>"
            f"<div class='moves'><span>Hai giocato <span class='played'>{esc(m.played_san)}</span></span>"
            f"<span>Meglio <span class='best'>{esc(m.best_san)}</span></span></div>"
            f"<div class='pv'>Linea del motore: {esc(' '.join(e.pv_san))}</div>"
            f"{body}<div class='meta'>{meta}</div></div></div>"
        )

    parts.append(f"<h2>{len(puzzles)} puzzle dalle tue partite</h2>"
                 "<p class='sub'>Posizioni in cui hai sbagliato e la mossa migliore è netta "
                 "(almeno 2 pedoni meglio della seconda scelta). Tocca a te.</p><div class='grid'>")
    for p in puzzles:
        side = "Bianco" if chess.Board(p["fen"]).turn == chess.WHITE else "Nero"
        parts.append(
            f"<div class='puzzle'>{board_svg(p['fen'], size=220)}"
            f"<div class='meta'>Muove il {side} · {esc(p['phase'])}</div>"
            f"<details><summary>Soluzione</summary><p><span class='best'>{esc(p['solution_san'])}</span>"
            f" (in partita: <span class='played'>{esc(p['played_san'])}</span>)</p></details></div>"
        )
    parts.append("</div></main></body></html>")
    return "".join(parts)
