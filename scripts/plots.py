#!/usr/bin/env python3
"""Grafici e numeri chiave delle tre domande di ricerca (PLAN.md, settimana 3).

    python scripts/plots.py --results results/baselines.csv results/run1.csv

Accetta più CSV (baseline e run LLM possono stare in file separati) e scrive in
results/figures/:

    rq1_by_solver.png       accuratezza per risolutore, con IC di Wilson 95%
    rq2_by_rating.png       accuratezza per fascia di rating, una linea per risolutore
    rq3_move_vs_theme.png   mossa trovata vs tema riconosciuto (solo LLM)
    themes_heatmap.png      accuratezza tema x risolutore
    cp_loss.png             quanto costano le mosse sbagliate (ma legali)
    summary.md              le tre frasi dei criteri di successo, con i numeri

I risolutori LLM si riconoscono dal nome "modello:rappresentazione"; le
baseline restano in grigio, come metro di riferimento.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from chesstutor.metrics import load_results, summary, wilson_interval  # noqa: E402

BUCKET_ORDER = ["<1200", "1200-1599", "1600-1999", "2000-2399", "2400+"]
REPRESENTATION_ORDER = ["fen", "ascii", "piece_list", "piece_list_moves"]
BASELINE_ORDER = ["random", "greedy", "stockfish_n1", "stockfish_d1", "stockfish_d2", "stockfish_d4"]
# Le mosse sbagliate possono perdere ~10.000 cp (un matto concesso): oltre
# questa soglia il dettaglio non conta e schiaccerebbe il resto del grafico.
CP_LOSS_CLIP = 1000

# Palette di riferimento (skill dataviz, tema chiaro), validata in quest'ordine
# per daltonismo sulle coppie adiacenti. I colori vanno alle rappresentazioni
# in ordine fisso, mai in base al rango, così fen è sempre blu in ogni grafico.
SURFACE = "#fcfcfb"
TEXT = "#0b0b0b"
TEXT_2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
BASELINE_GRAYS = ["#c3c2b7", "#a3a29b", "#898781", "#6b6a65", "#52514e", "#3a3936"]
SEQUENTIAL = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "axes.edgecolor": GRID, "axes.labelcolor": TEXT_2, "text.color": TEXT,
    "xtick.color": TEXT_2, "ytick.color": TEXT_2, "axes.grid": True,
    "grid.color": GRID, "grid.linewidth": 0.8, "axes.spines.top": False,
    "axes.spines.right": False, "axes.titlesize": 13, "axes.titleweight": "bold",
    "axes.titlelocation": "left", "font.size": 10, "legend.frameon": False,
})


def is_llm(solver: str) -> bool:
    return ":" in solver


def solver_order(solvers) -> list[str]:
    """Baseline nel loro ordine canonico, poi gli LLM per rappresentazione."""
    solvers = list(dict.fromkeys(solvers))
    base = [s for s in BASELINE_ORDER if s in solvers]
    base += sorted(s for s in solvers if not is_llm(s) and s not in base)
    rep_rank = {r: i for i, r in enumerate(REPRESENTATION_ORDER)}
    llm = sorted((s for s in solvers if is_llm(s)),
                 key=lambda s: (s.rsplit(":", 1)[0], rep_rank.get(s.rsplit(":", 1)[1], 99), s))
    return base + llm


def solver_colors(order: list[str]) -> dict[str, str]:
    """Grigi per le baseline, palette categoriale per gli LLM (in ordine fisso)."""
    colors, grays, llm_i = {}, iter(BASELINE_GRAYS * 3), 0
    for s in order:
        if is_llm(s):
            colors[s] = SERIES[llm_i % len(SERIES)]
            llm_i += 1
        else:
            colors[s] = next(grays)
    return colors


def short(solver: str) -> str:
    """'claude-sonnet-5-5:piece_list' -> 'piece_list' se c'è un solo modello."""
    return solver.rsplit(":", 1)[1] if is_llm(solver) else solver


def label_fn(order: list[str]):
    models = {s.rsplit(":", 1)[0] for s in order if is_llm(s)}
    return short if len(models) <= 1 else (lambda s: s)


def _pct_axis(ax, axis="y"):
    fmt = matplotlib.ticker.PercentFormatter(1.0, decimals=0)
    (ax.yaxis if axis == "y" else ax.xaxis).set_major_formatter(fmt)


def _save(fig, path: Path) -> Path:
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return path


def plot_by_solver(df, order, colors, label, out: Path) -> Path:
    """RQ1: tasso di risoluzione per risolutore, con intervallo di Wilson."""
    s = summary(df).set_index("solver").loc[order[::-1]]
    fig, ax = plt.subplots(figsize=(8, 0.45 * len(s) + 1.6))
    y = range(len(s))
    ax.barh(y, s["solved_rate"], height=0.6, color=[colors[k] for k in s.index], zorder=2)
    ax.errorbar(s["solved_rate"], y,
                xerr=[s["solved_rate"] - s["ci_low"], s["ci_high"] - s["solved_rate"]],
                fmt="none", ecolor=TEXT, elinewidth=1.2, capsize=3, zorder=3)
    for yi, (_, row) in zip(y, s.iterrows()):
        ax.text(row["ci_high"] + 0.012, yi, f"{row['solved_rate']:.1%}  (n={int(row['n'])})",
                va="center", fontsize=9, color=TEXT_2)
    ax.set_yticks(list(y), [label(k) for k in s.index])
    ax.set_xlim(0, 1.18)
    _pct_axis(ax, "x")
    ax.grid(axis="y", visible=False)
    ax.set_xlabel("puzzle risolti (mossa ufficiale o equivalente), IC 95% di Wilson")
    ax.set_title("Accuratezza per risolutore")
    return _save(fig, out / "rq1_by_solver.png")


def plot_by_rating(df, order, colors, label, out: Path) -> Path:
    """RQ2: la curva per fascia di rating; bande di confidenza solo sugli LLM."""
    s = summary(df, ["solver", "rating_bucket"])
    buckets = [b for b in BUCKET_ORDER if b in set(s["rating_bucket"])]
    x = {b: i for i, b in enumerate(buckets)}
    fig, ax = plt.subplots(figsize=(9, 5.2))
    ends = []
    for solver in order:
        rows = s[s["solver"] == solver].copy()
        rows["x"] = rows["rating_bucket"].map(x)
        rows = rows.sort_values("x")
        llm = is_llm(solver)
        ax.plot(rows["x"], rows["solved_rate"], color=colors[solver],
                lw=2, ls="-" if llm else "--", marker="o", ms=5 if llm else 3,
                label=label(solver), zorder=3 if llm else 2)
        if llm:
            ax.fill_between(rows["x"], rows["ci_low"], rows["ci_high"],
                            color=colors[solver], alpha=0.12, lw=0, zorder=1)
        last = rows.iloc[-1]
        ends.append([last["solved_rate"], last["x"], label(solver)])
    # Etichette a fine linea, distanziate quando le linee finiscono vicine.
    ends.sort()
    for i in range(1, len(ends)):
        ends[i][0] = max(ends[i][0], ends[i - 1][0] + 0.035)
    for y, x_end, text in ends:
        ax.text(x_end + 0.06, y, text, va="center", fontsize=8.5, color=TEXT_2)
    ax.set_xticks(range(len(buckets)), buckets)
    ax.set_xlim(-0.2, len(buckets) - 0.2)
    ax.set_ylim(0, 1.02)
    _pct_axis(ax)
    ax.set_xlabel("fascia di rating del puzzle")
    ax.set_ylabel("puzzle risolti")
    ax.set_title("Accuratezza per fascia di rating")
    ax.legend(loc="lower left", fontsize=8.5, ncol=2)
    return _save(fig, out / "rq2_by_rating.png")


def move_vs_theme(df) -> pd.DataFrame:
    """RQ3 per ogni risolutore LLM: mossa trovata, tema giusto, tema giusto a mossa sbagliata."""
    rows = []
    for solver, sub in df[~df["errored"]].groupby("solver"):
        if not is_llm(solver):
            continue
        missed = sub[~sub["solved"]]
        rows.append({
            "solver": solver,
            "n": len(sub),
            "solved_rate": sub["solved"].mean(),
            "theme_rate": sub["theme_correct"].mean(),
            "n_missed": len(missed),
            "theme_when_missed": missed["theme_correct"].mean() if len(missed) else float("nan"),
        })
    return pd.DataFrame(rows)


def plot_move_vs_theme(df, order, label, out: Path) -> Path | None:
    mt = move_vs_theme(df)
    if mt.empty:
        return None
    mt = mt.set_index("solver").loc[[s for s in order if s in set(mt["solver"])]]
    measures = [("solved_rate", "mossa trovata"),
                ("theme_rate", "tema riconosciuto"),
                ("theme_when_missed", "tema riconosciuto\nquando la mossa è sbagliata")]
    fig, ax = plt.subplots(figsize=(max(6, 1.9 * len(mt) + 2), 4.8))
    width = 0.26
    for i, (col, name) in enumerate(measures):
        xs = [k + (i - 1) * (width + 0.02) for k in range(len(mt))]
        ax.bar(xs, mt[col], width=width, color=SERIES[i], label=name, zorder=2)
        for xi, v in zip(xs, mt[col]):
            if v == v:
                ax.text(xi, v + 0.015, f"{v:.0%}", ha="center", fontsize=8.5, color=TEXT_2)
    ax.set_xticks(range(len(mt)), [label(s) for s in mt.index])
    ax.set_ylim(0, 1.1)
    _pct_axis(ax)
    ax.grid(axis="x", visible=False)
    ax.legend(loc="upper left", ncol=3, fontsize=8.5)
    ax.set_title("Riconoscere il motivo vs trovare la mossa")
    return _save(fig, out / "rq3_move_vs_theme.png")


def plot_theme_heatmap(df, order, label, out: Path) -> Path:
    """Dove ogni risolutore è cieco: tasso per tema, celle con n."""
    s = summary(df, ["theme", "solver"])
    rate = s.pivot(index="theme", columns="solver", values="solved_rate")[order]
    n = s.pivot(index="theme", columns="solver", values="n")[order]
    # Temi ordinati dal più difficile per il primo LLM (o per la media).
    key = next((c for c in order if is_llm(c)), None)
    rate = rate.loc[(rate[key] if key else rate.mean(axis=1)).sort_values().index]
    n = n.loc[rate.index]

    cmap = matplotlib.colors.LinearSegmentedColormap.from_list("seq", SEQUENTIAL)
    fig, ax = plt.subplots(figsize=(1.1 * len(order) + 3, 0.38 * len(rate) + 1.8))
    ax.imshow(rate.values, cmap=cmap, vmin=0, vmax=1, aspect="auto")
    for i in range(rate.shape[0]):
        for j in range(rate.shape[1]):
            v = rate.values[i, j]
            if v != v:
                continue
            ax.text(j, i, f"{v:.0%}", ha="center", va="center", fontsize=8,
                    color="#ffffff" if v > 0.55 else TEXT)
    ax.set_xticks(range(len(order)), [label(s) for s in order], rotation=30, ha="right")
    ax.set_yticks(range(len(rate)), rate.index)
    ax.grid(False)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.set_title(f"Accuratezza per tema (n per cella: {int(n.min().min())}–{int(n.max().max())})")
    return _save(fig, out / "themes_heatmap.png")


def plot_cp_loss(df, order, colors, label, out: Path) -> Path | None:
    """Mosse sbagliate ma legali: quasi giuste o catastrofiche?"""
    wrong = df[~df["errored"] & df["legal"] & ~df["solved"] & (df["cp_loss"] >= 0)]
    solvers = [s for s in order if s in set(wrong["solver"])]
    if not solvers:
        return None
    data = [wrong.loc[wrong["solver"] == s, "cp_loss"].clip(upper=CP_LOSS_CLIP) for s in solvers]
    fig, ax = plt.subplots(figsize=(8, 0.5 * len(solvers) + 1.8))
    bp = ax.boxplot(data[::-1], orientation="horizontal", widths=0.55, patch_artist=True,
                    showfliers=False, medianprops={"color": TEXT, "lw": 1.6},
                    whiskerprops={"color": MUTED}, capprops={"color": MUTED})
    for patch, s in zip(bp["boxes"], solvers[::-1]):
        patch.set(facecolor=colors[s], edgecolor=SURFACE, alpha=0.85)
    for yi, (s, d) in enumerate(zip(solvers[::-1], data[::-1]), 1):
        ax.text(CP_LOSS_CLIP * 1.02, yi, f"mediana {d.median():.0f} · n={len(d)}",
                va="center", fontsize=8.5, color=TEXT_2)
    ax.set_yticks(range(1, len(solvers) + 1), [label(s) for s in solvers[::-1]])
    ax.set_xlim(0, CP_LOSS_CLIP * 1.35)
    ax.grid(axis="y", visible=False)
    ax.set_xlabel(f"centipawn persi rispetto alla mossa migliore (tagliati a {CP_LOSS_CLIP})")
    ax.set_title("Quanto costano le mosse sbagliate")
    return _save(fig, out / "cp_loss.png")


def _rate(sub) -> str:
    k, n = int(sub["solved"].sum()), len(sub)
    lo, hi = wilson_interval(k, n)
    return f"{k / n:.1%} (IC 95% {lo:.1%}–{hi:.1%}, n={n})" if n else "n/d"


def write_summary(df, order, out: Path) -> Path:
    """Le tre frasi dei criteri di successo di PLAN.md, con i numeri di questo run."""
    ok = df[~df["errored"]]
    lines = ["# Numeri chiave", ""]
    llm = [s for s in order if is_llm(s)]

    lines += ["## RQ1 — rappresentazione", ""]
    for s in order:
        lines.append(f"- `{s}`: {_rate(ok[ok['solver'] == s])}")
    fen = next((s for s in llm if s.endswith(":fen")), None)
    if fen:
        fen_rate = ok.loc[ok["solver"] == fen, "solved"].mean()
        for s in llm:
            if s == fen:
                continue
            a = ok.loc[ok["solver"] == s].set_index("puzzle_id")["solved"]
            b = ok.loc[ok["solver"] == fen].set_index("puzzle_id")["solved"]
            both = a.index.intersection(b.index)
            diff = a[both].astype(int) - b[both].astype(int)
            # IC della differenza appaiata (stessi puzzle): approssimazione normale.
            se = diff.std(ddof=1) / len(diff) ** 0.5 if len(diff) > 1 else float("nan")
            lines.append(f"- `{short(s)}` vs `fen`: {diff.mean() * 100:+.1f} punti "
                         f"(IC 95% {(diff.mean() - 1.96 * se) * 100:+.1f}…"
                         f"{(diff.mean() + 1.96 * se) * 100:+.1f}, {len(diff)} puzzle appaiati; "
                         f"fen = {fen_rate:.1%})")
    lines.append("")

    lines += ["## RQ2 — curva per rating", ""]
    s = summary(df, ["solver", "rating_bucket"])
    for solver in order:
        rows = s[s["solver"] == solver].set_index("rating_bucket")
        parts = [f"{b} {rows.loc[b, 'solved_rate']:.0%}" for b in BUCKET_ORDER if b in rows.index]
        lines.append(f"- `{solver}`: " + " → ".join(parts))
    lines.append("")

    lines += ["## RQ3 — tema vs mossa", ""]
    mt = move_vs_theme(df)
    if mt.empty:
        lines.append("Nessun risolutore LLM in questi risultati.")
    for _, r in mt.iterrows():
        lines.append(f"- `{r['solver']}`: mossa {r['solved_rate']:.1%}, tema {r['theme_rate']:.1%}; "
                     f"quando sbaglia la mossa riconosce il tema nel "
                     f"{r['theme_when_missed']:.1%} dei casi ({r['n_missed']} puzzle)")
    path = out / "summary.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def make_all(results: list[str], out_dir: str) -> list[Path]:
    df = pd.concat([load_results(p) for p in results], ignore_index=True)
    df = df.drop_duplicates(["puzzle_id", "solver"], keep="last")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    order = solver_order(df["solver"])
    colors = solver_colors(order)
    label = label_fn(order)
    paths = [
        plot_by_solver(df, order, colors, label, out),
        plot_by_rating(df, order, colors, label, out),
        plot_move_vs_theme(df, order, label, out),
        plot_theme_heatmap(df, order, label, out),
        plot_cp_loss(df, order, colors, label, out),
        write_summary(df, order, out),
    ]
    return [p for p in paths if p]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", nargs="+", default=["results/benchmark.csv"])
    parser.add_argument("--out", default="results/figures")
    args = parser.parse_args()
    for path in make_all(args.results, args.out):
        print(path)


if __name__ == "__main__":
    main()
