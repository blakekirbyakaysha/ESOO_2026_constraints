"""Rank Victorian-relevant constraints from outputs/<tag>/daily.parquet (built by esoo_results.py).

Ranks per base constraint across ALL years (not per year). `_G_<n>` RHS sub-expressions are excluded.
Writes outputs/<tag>/ranking.csv (every constraint that binds, with tests) and
outputs/<tag>/ranking_wrl.csv (the WRL / Marinus-affected subset), and prints how many constraints
fall out under each selection test.

Usage: python scripts/rank_constraints.py --tag with_wrl [--cover 0.9]
"""
import argparse
import re
import sys
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parent))  # sibling imports also work under python -I

from esoo_results import ROOT, real_constraints, vic_tags

TOP_N_DAYS = 5


def grp_flags() -> pl.DataFrame:
    """Per constraint: WRL (Grp5->6) and Marinus (Grp7->8) flags, from the workbook cache and constraint_changes_by_grp.csv."""
    meta = pl.read_parquet(ROOT / "cache" / "eq_meta.parquet").with_columns(
        pl.col("timeslice").str.extract(r"Grp(\d+)", 1).cast(pl.Int64).alias("grp")
    )
    span = meta.drop_nulls("grp").group_by("constraint").agg(pl.col("grp").min().alias("first_grp"), pl.col("grp").max().alias("last_grp"))
    ch = pl.read_csv(ROOT / "inputs" / "constraint_changes_by_grp.csv")
    wrl_net = (
        ch.filter((pl.col("from_grp") == 5) & (pl.col("to_grp") == 6))
        .filter((pl.col("lhs_add_n") > 0) | (pl.col("lhs_rem_n") > 0) | (pl.col("lhs_chg_max") > 0.05))
        .select("constraint").unique().with_columns(pl.lit(True).alias("wrl_lhs_change"))
    )
    marinus = (
        ch.filter((pl.col("to_grp") == 8) & pl.col("lhs_add").fill_null("").str.contains("Marinus_1"))
        .select("constraint").unique().with_columns(pl.lit(True).alias("marinus_added"))
    )
    return (
        span.join(wrl_net, on="constraint", how="left").join(marinus, on="constraint", how="left")
        .with_columns(
            (pl.col("first_grp") == 6).alias("wrl_new"),          # first appears at Grp6
            (pl.col("last_grp") == 5).alias("wrl_retired"),       # last defined at Grp5, i.e. dropped at the WRL step
            pl.col("wrl_lhs_change").fill_null(False),
            pl.col("marinus_added").fill_null(False),
        )
    )


def rank(daily: pl.DataFrame, cover: float, peak_day: float, price: float, max_grp: int | None = None) -> pl.DataFrame:
    daily = real_constraints(daily)
    if max_grp is not None:
        daily = daily.filter(pl.col("grp") <= max_grp)
    per_fy = daily.group_by("constraint", "fy").agg(pl.col("rental").sum().alias("r")).pivot(on="fy", index="constraint", values="r")
    per_fy = per_fy.rename({c: f"rental_FY{c}" for c in per_fy.columns if c != "constraint"})
    c = daily.group_by("constraint").agg(
        pl.col("rental").sum().alias("rental"),
        pl.col("hrs_bind").sum().alias("hrs_bind"),
        (pl.col("hrs_bind") > 0).sum().alias("days_bind"),
        pl.col("price").max().alias("max_price"),
        pl.col("rental").max().alias("peak_day_rental"),
        pl.col("violation").sum().alias("violation"),
        pl.col("rental").sort(descending=True).head(TOP_N_DAYS).sum().alias("top_days_rental"),
    ).with_columns((pl.col("top_days_rental") / pl.col("rental")).alias("top_days_share"))
    tags = vic_tags()
    c = c.join(tags, on="constraint", how="left").join(grp_flags(), on="constraint", how="left").join(per_fy, on="constraint", how="left")
    c = c.with_columns(
        (pl.col("has_vic_duid").fill_null(False) | pl.col("has_vic_ic").fill_null(False)).alias("vic"),
        (pl.col("wrl_new").fill_null(False) | pl.col("wrl_retired").fill_null(False) | pl.col("wrl_lhs_change").fill_null(False)
         | pl.col("marinus_added").fill_null(False)).alias("wrl_related"),
    )
    # negative rental is a solver artefact on a few violating constraints, so the cover is built on positive rental only
    v = c.filter(pl.col("vic") & (pl.col("hrs_bind") > 0) & (pl.col("rental") > 0)).sort("rental", descending=True).with_columns(
        (pl.col("rental").cum_sum() / pl.col("rental").sum()).alias("cum_rental_share")
    )
    return v.with_columns(
        (pl.col("cum_rental_share").shift(1).fill_null(0) < cover).alias("t_rental_cover"),
        (pl.col("peak_day_rental") >= peak_day).alias("t_episodic"),  # one day alone is worth >= peak_day rental
        (pl.col("max_price") >= price).alias("t_price_spike"),
        (pl.col("violation") > 0).alias("t_violation"),
    ).with_columns(
        (pl.col("t_rental_cover") | pl.col("t_episodic") | pl.col("t_price_spike") | pl.col("t_violation")).alias("selected_any")
    )


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="with_wrl")
    ap.add_argument("--cover", type=float, default=0.9)
    ap.add_argument("--peak-day", type=float, default=250, help="include if any single day's rental >= this")
    ap.add_argument("--max-grp", type=int, default=None, help="ignore days in Grps above this (e.g. 9 to drop the distorted Grp10/11 period)")
    ap.add_argument("--price", type=float, default=50, help="include if daily-mean shadow price >= this $/MW")
    a = ap.parse_args()
    out = ROOT / "outputs" / a.tag
    v = rank(pl.read_parquet(out / "daily.parquet"), a.cover, a.peak_day, a.price, a.max_grp)
    v.write_csv(out / "ranking.csv")
    v.filter(pl.col("wrl_related")).write_csv(out / "ranking_wrl.csv")
    n = v.height
    print(f"Victorian-relevant constraints that bind at least once: {n}")
    print(f"  rental cover {a.cover:.0%}: {v['t_rental_cover'].sum()}")
    print(f"  + episodic (a single day >= {a.peak_day:g} rental): adds {(v['t_episodic'] & ~v['t_rental_cover']).sum()}")
    print(f"  + price spike (>= ${a.price:g}/MW): adds {(v['t_price_spike'] & ~v['t_rental_cover'] & ~v['t_episodic']).sum()}")
    print(f"  + violation: adds {(v['t_violation'] & ~v['t_rental_cover'] & ~v['t_episodic'] & ~v['t_price_spike']).sum()}")
    print(f"  selected by any test: {v['selected_any'].sum()}")
    print("sensitivity (additions beyond rental cover): peak-day threshold -> extra constraints")
    rest = v.filter(~pl.col("t_rental_cover"))
    for t in (50, 100, 250, 500, 1000):
        print(f"  peak day >= {t}: +{(rest['peak_day_rental'] >= t).sum()}")
    for t in (20, 50, 100, 200):
        print(f"  max price >= ${t}: +{(rest['max_price'] >= t).sum()}")
    w = v.filter(pl.col("wrl_related"))
    print(f"WRL / Marinus-related among binding Victorian-relevant: {w.height} (selected by any test: {w['selected_any'].sum()}) -> ranking_wrl.csv")
