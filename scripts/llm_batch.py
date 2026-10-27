#!/usr/bin/env python3
"""Riempie la cache LLM con la Message Batches API: metà prezzo, in parallelo.

Il benchmark chiama l'LLM una richiesta alla volta: 8.000 chiamate con il
ragionamento attivo sono decine di ore. Qui le stesse richieste partono in un
unico batch, e le risposte finiscono in results/llm_cache.jsonl con la stessa
chiave che usa cached_completer. Dopo, run_benchmark.py trova tutto in cache.

    # quante richieste e quanto costa, senza chiamare l'API
    python scripts/llm_batch.py submit --puzzles data/sample.csv --limit 200 \\
        --representations piece_list --dry-run

    # invia, poi raccogli (--wait aspetta la fine del batch)
    python scripts/llm_batch.py submit --puzzles data/sample.csv --limit 200 --representations piece_list
    python scripts/llm_batch.py collect --wait

    # infine il benchmark vero, che legge dalla cache
    python scripts/run_benchmark.py --puzzles data/sample.csv --limit 200 \\
        --model claude-sonnet-5-5 --representations piece_list --out results/pilot.csv

Modello, effort, max-tokens e rappresentazioni devono coincidere fra
llm_batch.py e run_benchmark.py, altrimenti le chiavi di cache non combaciano.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from chesstutor.dataset import load_puzzles  # noqa: E402
from chesstutor.representations import build_prompt  # noqa: E402
from chesstutor.solvers import (  # noqa: E402
    CompletionError, append_to_cache, cache_key, completer_cache_id, load_cache,
    request_params, response_text,
)

STATE = Path("results/llm_batches.jsonl")
# $ per milione di token (input, output), prezzi standard; il batch costa la metà.
PRICES = {"claude-opus-5-5": (4.0, 20.0), "claude-sonnet-5-5": (2.0, 10.0),
          "claude-haiku-4-5": (1.0, 5.0)}


def requests_for_prompts(prompts, model, max_tokens, effort, cache) -> list[dict]:
    """Richieste per i prompt non ancora in cache, senza doppioni.

    Il custom_id è la chiave di cache stessa (sha256, 64 caratteri esadecimali,
    il massimo consentito): la raccolta non ha bisogno di altre tabelle. È
    l'unico posto che decide chiave e salto della cache per ogni batch.
    """
    namespace = completer_cache_id(model, max_tokens, effort)
    requests, seen = [], set()
    for prompt in prompts:
        key = cache_key(namespace, prompt)
        if key in cache or key in seen:
            continue
        seen.add(key)
        requests.append({"custom_id": key,
                         "params": request_params(prompt, model, max_tokens, effort)})
    return requests


def build_requests(puzzles, representations, model, max_tokens, effort, cache) -> list[dict]:
    """Richieste per le coppie (puzzle, rappresentazione) non ancora in cache."""
    prompts = (build_prompt(puzzle.board, rep) for puzzle in puzzles for rep in representations)
    return requests_for_prompts(prompts, model, max_tokens, effort, cache)


def estimate_cost(requests: list[dict], model: str, output_tokens: int) -> float | None:
    """Stima grezza: ~4 caratteri per token in input, output fisso per richiesta."""
    if model not in PRICES:
        return None
    price_in, price_out = PRICES[model]
    tokens_in = sum(len(r["params"]["messages"][0]["content"]) / 4 for r in requests)
    tokens_out = output_tokens * len(requests)
    return (tokens_in * price_in + tokens_out * price_out) / 1e6 / 2


def collect_results(results, namespace: str, cache_path: str) -> dict[str, int]:
    """Scrive in cache le risposte riuscite; gli errori restano fuori.

    Una richiesta non riuscita (errore, rifiuto, troncamento) non va in cache:
    al run del benchmark verrà ritentata con una chiamata diretta.
    """
    cache = load_cache(cache_path)
    counts = {"cached": 0, "already": 0, "failed": 0}
    for result in results:
        if result.custom_id in cache:
            counts["already"] += 1
            continue
        if result.result.type != "succeeded":
            counts["failed"] += 1
            continue
        try:
            text = response_text(result.result.message)
        except CompletionError:
            counts["failed"] += 1
            continue
        append_to_cache(cache_path, result.custom_id, namespace, text)
        cache[result.custom_id] = text
        counts["cached"] += 1
    return counts


def read_state() -> list[dict]:
    if not STATE.exists():
        return []
    return [json.loads(line) for line in STATE.read_text(encoding="utf-8").splitlines() if line]


def write_state(entries: list[dict]) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text("".join(json.dumps(e) + "\n" for e in entries), encoding="utf-8")


def cmd_submit(args) -> None:
    puzzles = load_puzzles(args.puzzles, limit=args.limit, min_popularity=0, min_plays=0)
    effort = None if args.effort.lower() == "none" else args.effort
    requests = build_requests(puzzles, args.representations, args.model,
                              args.max_tokens, effort, load_cache(args.cache))
    cost = estimate_cost(requests, args.model, args.est_output_tokens)
    print(f"{len(puzzles)} puzzle x {len(args.representations)} rappresentazioni: "
          f"{len(requests)} richieste non ancora in cache")
    if cost is not None:
        print(f"Costo stimato col batch: ~${cost:.2f} "
              f"(ipotesi {args.est_output_tokens} token di output per risposta, ragionamento incluso)")
    if args.dry_run or not requests:
        return
    submit_batch(requests, completer_cache_id(args.model, args.max_tokens, effort), args.cache)


def submit_batch(requests: list[dict], namespace: str, cache: str) -> str:
    """Invia un batch e lo registra in STATE, così `collect` lo trova."""
    import anthropic

    batch = anthropic.Anthropic().messages.batches.create(requests=requests)
    entries = read_state()
    entries.append({"id": batch.id, "namespace": namespace,
                    "cache": cache, "requests": len(requests), "collected": False})
    write_state(entries)
    print(f"Batch {batch.id} inviato. Raccogli con: python scripts/llm_batch.py collect --wait")
    return batch.id


def cmd_collect(args) -> None:
    import anthropic

    client = anthropic.Anthropic()
    entries = read_state()
    pending = [e for e in entries if not e["collected"]]
    if not pending:
        print("Nessun batch da raccogliere.")
        return
    for entry in pending:
        while True:
            batch = client.messages.batches.retrieve(entry["id"])
            if batch.processing_status == "ended" or not args.wait:
                break
            c = batch.request_counts
            print(f"  {entry['id']}: {c.processing} in corso, {c.succeeded} riusciti...", flush=True)
            time.sleep(60)
        if batch.processing_status != "ended":
            print(f"{entry['id']}: ancora in corso ({batch.processing_status})")
            continue
        counts = collect_results(client.messages.batches.results(entry["id"]),
                                 entry["namespace"], entry["cache"])
        entry["collected"] = True
        write_state(entries)
        print(f"{entry['id']}: {counts['cached']} risposte in cache, "
              f"{counts['failed']} fallite (verranno ritentate dal benchmark)")


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    submit = sub.add_parser("submit", help="invia un batch con le richieste mancanti")
    submit.add_argument("--puzzles", required=True)
    submit.add_argument("--limit", type=int, default=None)
    submit.add_argument("--model", default="claude-sonnet-5-5")
    submit.add_argument("--effort", default="medium")
    submit.add_argument("--max-tokens", type=int, default=16000)
    submit.add_argument("--representations", nargs="+", default=["piece_list"],
                        choices=["fen", "ascii", "piece_list", "piece_list_moves"])
    submit.add_argument("--cache", default="results/llm_cache.jsonl")
    submit.add_argument("--est-output-tokens", type=int, default=2500)
    submit.add_argument("--dry-run", action="store_true", help="conta e stima, non invia")
    submit.set_defaults(func=cmd_submit)

    collect = sub.add_parser("collect", help="scarica i risultati dei batch inviati")
    collect.add_argument("--wait", action="store_true", help="aspetta che i batch finiscano")
    collect.set_defaults(func=cmd_collect)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
