"""Compare two runs (default with_wrl vs no_wrl) on the same Grps / years, and their shortlists.

Both runs must already be loaded (esoo_results.py) and, for the shortlist comparison, have a draft_list.csv (draft_list.py).
Years are limited to those present in BOTH runs. Prints: Victorian positive rental, how many bind, top-N overlap, and the
shortlist overlap / differences. Writes outputs/compare_<a>_vs_<b>.csv (per-constraint rental and hours in each run).

Usage: python scripts/compare_runs.py [--a with_wrl] [--b no_wrl] [--max-grp 9]
"""
import argparse
import sys
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parent))  # sibling imports also work under python -I

from esoo_results import ROOT, real_constraints, vic_tags


def load(tag: str, max_grp: int, fys: list[str] | None = None) -> pl.DataFrame:
    d = real_constraints(pl.read_parquet(ROOT / "outputs" / tag / "daily.parquet")).filter(pl.col("grp") <= max_grp)
    return d if fys is None else d.filter(pl.col("fy").is_in(fys))


def per_constraint(d: pl.DataFrame, vic: pl.Series, suffix: str) -> pl.DataFrame:
    return (
        d.filter(pl.col("constraint").is_in(vic.implode()))
        .group_by("constraint")
        .agg(pl.col("rental").clip(0, None).sum().alias(f"rental_{suffix}"), pl.col("hrs_bind").sum().alias(f"hrs_{suffix}"))
    )


def shortlist(tag: str) -> set[str]:
    f = ROOT / "outputs" / tag / "draft_list.csv"
    if not f.exists():
        return set()
    return set(pl.read_csv(f).filter(pl.col("shortlist_reason").is_in(["core", "year_specific"]))["constraint"])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", default="with_wrl")
    ap.add_argument("--b", default="no_wrl")
    ap.add_argument("--max-grp", type=int, default=9)
    a = ap.parse_args()

    fy_a = set(pl.read_parquet(ROOT / "outputs" / a.a / "daily.parquet", columns=["fy"])["fy"].unique())
    fy_b = set(pl.read_parquet(ROOT / "outputs" / a.b / "daily.parquet", columns=["fy"])["fy"].unique())
    fys = sorted(fy_a & fy_b)
    print(f"years compared (in both runs): {', '.join(fys)}")
    tags = vic_tags()
    vic = tags.filter(pl.col("has_vic_duid") | pl.col("has_vic_ic"))["constraint"]

    ra = per_constraint(load(a.a, a.max_grp, fys), vic, "a")
    rb = per_constraint(load(a.b, a.max_grp, fys), vic, "b")
    j = ra.join(rb, on="constraint", how="full", coalesce=True).fill_null(0).sort("rental_b", descending=True)
    j.write_csv(ROOT / "outputs" / f"compare_{a.a}_vs_{a.b}.csv")

    print(f"Victorian positive rental: {a.a} {ra['rental_a'].sum():,.0f}  {a.b} {rb['rental_b'].sum():,.0f}")
    print(f"binding (hours > 0): {a.a} {ra.filter(pl.col('hrs_a') > 0).height}  {a.b} {rb.filter(pl.col('hrs_b') > 0).height}")
    top_a = ra.sort("rental_a", descending=True)["constraint"].to_list()
    top_b = rb.sort("rental_b", descending=True)["constraint"].to_list()
    for k in (10, 15, 20, 30):
        print(f"top {k} by rental, overlap: {len(set(top_a[:k]) & set(top_b[:k]))}")
    print(f"in {a.b} top 20 but not {a.a} top 20:", sorted(set(top_b[:20]) - set(top_a[:20])))
    print(f"in {a.a} top 20 but not {a.b} top 20:", sorted(set(top_a[:20]) - set(top_b[:20])))

    sa, sb = shortlist(a.a), shortlist(a.b)
    if sa and sb:
        print(f"shortlists: {a.a} {len(sa)}, {a.b} {len(sb)}, common {len(sa & sb)}")
        print(f"only in {a.b}:", sorted(sb - sa))
        print(f"only in {a.a}:", sorted(sa - sb))
