"""Aggregazione dei risultati con intervalli di confidenza.

Nota metodologica: con 25 puzzle per cella, la differenza fra 60% e 68% non è
statisticamente distinguibile. Riportare accuratezze nude invita a
sovrainterpretare il rumore, quindi ogni tasso qui esce accompagnato da un
intervallo di Wilson.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Rate:
    successes: int
    total: int

    @property
    def value(self) -> float:
        return self.successes / self.total if self.total else 0.0

    @property
    def ci(self) -> tuple[float, float]:
        return wilson_interval(self.successes, self.total)

    def __str__(self) -> str:
        lo, hi = self.ci
        return f"{self.value:.1%} [{lo:.1%}–{hi:.1%}] (n={self.total})"


def wilson_interval(successes: int, total: int, z: float = 1.96) -> tuple[float, float]:
    """Intervallo di confidenza al 95% per una proporzione (metodo di Wilson).

    Preferito a quello normale perché resta sensato con n piccoli e con tassi
    vicini a 0 o 1 — esattamente il regime in cui cadono le celle di questo
    benchmark.
    """
    if total == 0:
        return (0.0, 0.0)
    p = successes / total
    denom = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denom
    margin = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denom
    return (max(0.0, centre - margin), min(1.0, centre + margin))


def load_results(path: str):
    import pandas as pd

    df = pd.read_csv(path)
    for col in ("legal", "exact_match", "engine_equivalent", "theme_correct"):
        if col in df:
            df[col] = df[col].astype(str).str.lower().isin(("true", "1"))
    # "Risolto" = mossa ufficiale oppure una mossa altrettanto vincente.
    df["solved"] = df["exact_match"] | df["engine_equivalent"]
    # Le colonne di testo vuote arrivano come NaN; i CSV vecchi non le hanno.
    for col in ("raw", "error", "theme_said", "explanation", "got_san", "got_uci"):
        df[col] = df[col].fillna("").astype(str) if col in df else ""
    df["errored"] = df["error"] != ""
    return df


def summary(df, group_by: list[str] | None = None):
    """Tabella riassuntiva: tasso di mosse legali, risolte e temi corretti.

    Le righe con una chiamata fallita (`errors`) sono escluse dai tassi: un
    rate limit non dice nulla sulla capacità del modello, e contarlo come
    mossa illegale gonfierebbe l'illegalità.
    """
    import pandas as pd

    keys = group_by or ["solver"]
    rows = []
    for key, all_rows in df.groupby(keys, dropna=False):
        key = key if isinstance(key, tuple) else (key,)
        sub = all_rows[~all_rows["errored"]] if "errored" in all_rows else all_rows
        n = len(sub)
        if n == 0:
            continue
        solved = int(sub["solved"].sum())
        lo, hi = wilson_interval(solved, n)
        rows.append({
            **dict(zip(keys, key)),
            "n": n,
            "errors": len(all_rows) - n,
            "legal_rate": sub["legal"].mean(),
            "solved_rate": solved / n if n else 0.0,
            "ci_low": lo,
            "ci_high": hi,
            "exact_rate": sub["exact_match"].mean(),
            "theme_rate": sub["theme_correct"].mean(),
            "median_cp_loss": sub.loc[sub["cp_loss"] >= 0, "cp_loss"].median(),
        })
    return pd.DataFrame(rows).sort_values("solved_rate", ascending=False)


def print_report(df, worst_n: int = 6) -> None:
    fmt = lambda x: f"{x:.3f}"  # noqa: E731
    overall = summary(df)

    print("\n=== Per risolutore ===")
    print(overall.to_string(index=False, float_format=fmt))
    print("\n=== Per risolutore x fascia di rating ===")
    print(summary(df, ["solver", "rating_bucket"]).to_string(
        index=False, float_format=fmt))

    # Un blocco per risolutore: aggregare i temi su tutti i risolutori insieme
    # produce una media che dipende da quante baseline sono state lanciate, non
    # dal tema. L'ordinamento è per ci_high, non per tasso nudo, così un tema con
    # 2 puzzle e 50% non scavalca uno con 100 puzzle e 68%.
    print(f"\n=== Per tema (peggiori {worst_n} per risolutore, per ci_high) ===")
    for solver in overall["solver"]:
        sub = summary(df[df["solver"] == solver], ["theme"])
        worst = sub.sort_values(["ci_high", "solved_rate"]).head(worst_n)
        print(f"\n{solver}")
        print(worst.to_string(index=False, float_format=fmt))
