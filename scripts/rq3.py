#!/usr/bin/env python3
"""RQ3 a quattro bracci: campione, batch, run dalla cache, analisi preregistrata.

Le regole stanno in src/chesstutor/rq3.py e in
docs/designs/rq3-preregistration.md; questo script le esegue nell'ordine.

    # 1. campione: 400 principali + 40 pilota (disgiunti), in results/rq3/
    python scripts/rq3.py sample --puzzles data/sample.csv

    # 2. batch (metà prezzo): prima a secco per contare e stimare il costo
    python scripts/rq3.py submit --set pilot --dry-run
    python scripts/rq3.py submit --set pilot
    python scripts/llm_batch.py collect --wait

    # 3. run dalla sola cache: si ferma se manca anche una risposta
    python scripts/rq3.py run --set pilot

    # 4. numeri e frasi preregistrate
    python scripts/rq3.py analyse --set pilot

Modello, effort e max-tokens devono coincidere fra submit e run, altrimenti
le chiavi di cache non combaciano (e run si ferma prima di partire).
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import llm_batch  # noqa: E402
from chesstutor import rq3  # noqa: E402
from chesstutor.dataset import load_puzzles, write_sample  # noqa: E402
from chesstutor.solvers import (  # noqa: E402
    RandomSolver, cache_key, cached_completer, completer_cache_id, load_cache,
)

MAIN_REP = "piece_list"
CONTROL_REP = "fen"
CONTROL_ARMS = ("theme_only", "move_only")


def load_set(directory: Path, name: str):
    path = directory / f"{name}.csv"
    if not path.exists():
        sys.exit(f"{path} non esiste: lancia prima `python scripts/rq3.py sample`")
    return load_puzzles(path, min_popularity=0, min_plays=0)


def planned_prompts(puzzles, with_control: bool, seed: int) -> list[str]:
    """Tutti i prompt di un set: l'unico elenco usato sia da submit sia da run."""
    prompts = [rq3.arm_prompt(p, arm, MAIN_REP, seed) for p in puzzles for arm in rq3.ARMS]
    if with_control:
        prompts += [rq3.arm_prompt(p, arm, CONTROL_REP, seed)
                    for p in rq3.control_subset(puzzles, seed) for arm in CONTROL_ARMS]
    return prompts


def effort_of(args):
    return None if args.effort.lower() == "none" else args.effort


def cmd_sample(args) -> None:
    puzzles = load_puzzles(args.puzzles, min_popularity=0, min_plays=0)
    main, pilot = rq3.sample(puzzles, args.seed)
    args.dir.mkdir(parents=True, exist_ok=True)
    write_sample(main, args.dir / "main.csv")
    write_sample(pilot, args.dir / "pilot.csv")
    print(f"{len(main)} principali, {len(pilot)} pilota -> {args.dir}")
    false = Counter(rq3.false_theme(p, args.seed) for p in main)
    print("Temi falsi usati (principale):", ", ".join(f"{t} {n}" for t, n in false.most_common()))
    extra = sum(bool(rq3.tag_exclusions(p)) for p in main)
    print(f"Puzzle con temi esclusi da un altro tag (D3): {extra}")


def cmd_submit(args) -> None:
    puzzles = load_set(args.dir, args.set)
    effort = effort_of(args)
    prompts = planned_prompts(puzzles, args.set == "main", args.seed)
    requests = llm_batch.requests_for_prompts(prompts, args.model, args.max_tokens, effort,
                                              load_cache(args.cache))
    cost = llm_batch.estimate_cost(requests, args.model, args.est_output_tokens)
    print(f"{len(prompts)} prompt pianificati, {len(requests)} non ancora in cache")
    if cost is not None:
        print(f"Costo stimato col batch: ~${cost:.2f} "
              f"(ipotesi {args.est_output_tokens} token di output per risposta)")
    if args.dry_run or not requests:
        return
    llm_batch.submit_batch(requests, completer_cache_id(args.model, args.max_tokens, effort), args.cache)


def cmd_run(args) -> None:
    from chesstutor.benchmark import run_benchmark
    from chesstutor.engine import Engine

    puzzles = load_set(args.dir, args.set)
    effort = effort_of(args)
    namespace = completer_cache_id(args.model, args.max_tokens, effort)
    cache = load_cache(args.cache)
    missing = [p for p in planned_prompts(puzzles, args.set == "main", args.seed)
               if cache_key(namespace, p) not in cache]
    if missing:
        sys.exit(f"{len(missing)} risposte non sono in cache: rilancia `submit` e `collect` "
                 "(o controlla che modello, effort e max-tokens coincidano). Nessuna chiamata fatta.")

    complete = cached_completer(_no_live_calls, args.cache, cache_id=namespace, cache_only=True)
    solvers = [rq3.ArmLLMSolver(complete, arm, MAIN_REP, args.model, args.seed) for arm in rq3.ARMS]
    solvers.append(RandomSolver(seed=0))
    with Engine() as engine:
        run_benchmark(puzzles, solvers, engine, args.dir / f"{args.set}_{MAIN_REP}.csv",
                      judge_depth=args.judge_depth, resume=args.resume)
        if args.set == "main":
            control = [rq3.ArmLLMSolver(complete, arm, CONTROL_REP, args.model, args.seed)
                       for arm in CONTROL_ARMS]
            run_benchmark(rq3.control_subset(puzzles, args.seed), control, engine,
                          args.dir / f"{args.set}_control_{CONTROL_REP}.csv",
                          judge_depth=args.judge_depth, resume=args.resume)
    print(f"Risultati in {args.dir}. Poi: python scripts/rq3.py analyse --set {args.set}")


def _no_live_calls(prompt: str) -> str:
    raise RuntimeError("chiamata API non prevista: il run di RQ3 legge solo la cache")


def pct(x: float) -> str:
    return f"{x:.1%}"


def ci(pair) -> str:
    return f"[{pair[0]:.1%}–{pair[1]:.1%}]"


def points(triple) -> str:
    return f"{triple[0]:+.1f} punti [{triple[1]:+.1f}, {triple[2]:+.1f}]"


def render(report: dict, control: dict | None, set_name: str) -> str:
    r = report
    lines = [
        f"# RQ3 — risultati ({set_name})", "",
        f"**{r['headline']}** {r['false_hint_sentence']}", "",
        f"Puzzle analizzati: {r['n']} (esclusi per errori API: {r['excluded_for_errors']}).", "",
        "| Misura | Valore |", "|---|---|",
        f"| Motivo riconosciuto (`theme_only`) | {pct(r['theme_rate'])} {ci(r['theme_ci'])} |",
        f"| Pavimento cieco (tema più frequente / estrazione per frequenza) | "
        f"{pct(r['floors']['always_most_frequent'])} / {pct(r['floors']['frequency_weighted'])} |",
        f"| Risposte sul tema non valutabili | {pct(r['theme_unparsed'])} |",
        f"| Mossa trovata, `move_only` | {pct(r['move_rate'])} {ci(r['move_ci'])} — livello {r['move_level']} |",
        f"| Mossa trovata, `hint_true` / `hint_false` | {pct(r['hint_true_rate'])} / {pct(r['hint_false_rate'])} |",
        f"| Pavimento della mossa (`random`) | "
        f"{pct(r['random_rate']) if r['random_rate'] is not None else 'n/d'} |",
        f"| D_true = hint_true − move_only | {points(r['d_true'])} — {r['d_true_category']} |",
        f"| D_false = hint_false − move_only | {points(r['d_false'])} — {r['d_false_category']} |",
        f"| E ({'hint_true − hint_false' if r['e_relative_to_false'] else 'D_true'}) | "
        f"{points(r['e'])} — {r['e_category']} |",
        f"| Riconosce il motivo e sbaglia la mossa | {pct(r['recognised_missed'])} {ci(r['recognised_missed_ci'])} |",
        f"| Mosse illegali (move_only / hint_true / hint_false) | "
        + " / ".join(pct(r['illegal_rate'][a]) for a in rq3.MOVE_ARMS) + " |",
    ]
    for label, key in (("D_true se il motivo era riconosciuto", "d_true_when_theme_right"),
                       ("D_true se il motivo non era riconosciuto", "d_true_when_theme_wrong")):
        lines.append(f"| {label} (descrittivo) | {points(r[key]) if r[key] else 'n/d'} |")
    if control:
        lines += ["", f"Controllo in `{CONTROL_REP}` (descrittivo, {control['n']} puzzle): motivo "
                      f"{pct(control['theme_rate'])}, mossa {pct(control['move_rate'])}."]
    return "\n".join(lines) + "\n"


def control_rates(df) -> dict | None:
    """Tassi descrittivi del controllo in fen: niente frasi, niente bracci hint."""
    rows = df[df["solver"].str.contains(f":{CONTROL_REP}:")]
    if rows.empty:
        return None
    theme = rows[rows["solver"].str.endswith(":theme_only") & ~rows["errored"]]
    move = rows[rows["solver"].str.endswith(":move_only") & ~rows["errored"]]
    truth = [next((t for t in str(s).split() if t in rq3.VOCABULARY), None) for s in theme["themes"]]
    hits = [rq3.score_theme(s) == t for s, t in zip(theme["theme_said"], truth)]
    return {"n": len(theme), "theme_rate": sum(hits) / len(hits) if hits else 0.0,
            "move_rate": float(move["solved"].mean()) if len(move) else 0.0}


def cmd_analyse(args) -> None:
    from chesstutor.metrics import load_results

    path = args.dir / f"{args.set}_{MAIN_REP}.csv"
    if not path.exists():
        sys.exit(f"{path} non esiste: lancia prima `python scripts/rq3.py run --set {args.set}`")
    report = rq3.analyse(load_results(path), MAIN_REP, args.seed)
    control_path = args.dir / f"{args.set}_control_{CONTROL_REP}.csv"
    control = control_rates(load_results(control_path)) if control_path.exists() else None
    text = render(report, control, args.set)
    out = args.dir / f"{args.set}_summary.md"
    out.write_text(text, encoding="utf-8")
    print(text)
    print(f"Scritto {out}")


def main() -> None:
    # La console di Windows è cp1252: senza questo, "−" e "–" del report fanno crashare print.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", type=Path, default=ROOT / "results" / "rq3")
    parser.add_argument("--seed", type=int, default=0)
    sub = parser.add_subparsers(dest="cmd", required=True)

    sample = sub.add_parser("sample", help="estrae 400 + 40 puzzle a tema singolo")
    sample.add_argument("--puzzles", default=str(ROOT / "data" / "sample.csv"))
    sample.set_defaults(func=cmd_sample)

    def model_args(p):
        p.add_argument("--set", choices=["pilot", "main"], required=True)
        p.add_argument("--model", default="claude-sonnet-5-5")
        p.add_argument("--effort", default="medium")
        p.add_argument("--max-tokens", type=int, default=16000)
        p.add_argument("--cache", default=str(ROOT / "results" / "llm_cache.jsonl"))

    submit = sub.add_parser("submit", help="invia in batch i prompt non ancora in cache")
    model_args(submit)
    submit.add_argument("--est-output-tokens", type=int, default=2500)
    submit.add_argument("--dry-run", action="store_true", help="conta e stima, non invia")
    submit.set_defaults(func=cmd_submit)

    run = sub.add_parser("run", help="esegue i bracci leggendo solo dalla cache")
    model_args(run)
    run.add_argument("--judge-depth", type=int, default=16)
    run.add_argument("--resume", action="store_true")
    run.set_defaults(func=cmd_run)

    analyse = sub.add_parser("analyse", help="numeri e frasi preregistrate")
    analyse.add_argument("--set", choices=["pilot", "main"], required=True)
    analyse.set_defaults(func=cmd_analyse)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
