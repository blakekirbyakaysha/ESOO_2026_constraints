"""Draft shortlist of Victorian-relevant constraints that is robust to scarcity-inflated years.

Rental scales with price, and the ESOO fleet (committed + anticipated only) gets short later in the horizon, so late years
inflate rental. This script ranks three ways on Grps <= --max-grp and prints/writes a combined shortlist:
  share_rank  : mean over FYs of the constraint's share of that FY's Victorian positive rental (each year counts equally)
  hours_rank  : total hours binding (price independent)
  rental_rank : total positive rental (as in rank_constraints.py)
Shortlist = core + year-specific:
  core          : best (lowest) mean of the three ranks, --n slots (default 15)
  year-specific : any other constraint inside the --fy-cover (default 90%) cumulative share of any single FY's Victorian
                  positive rental, so constraints that bind heavily in only some years are kept. Ordered by max_fy_share,
                  and the total shortlist is capped at --cap (default 40).
Writes outputs/<tag>/draft_list.csv (`shortlist_reason` = core / year_specific / blank).

Usage: python scripts/draft_list.py --tag with_wrl [--max-grp 9] [--n 15] [--fy-cover 0.9] [--cap 40]
"""
import argparse
import sys
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parent))  # sibling imports also work under python -I

from esoo_results import ROOT, real_constraints, vic_tags
from rank_constraints import grp_flags

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="with_wrl")
    ap.add_argument("--max-grp", type=int, default=9)
    ap.add_argument("--n", type=int, default=15)
    ap.add_argument("--fy-cover", type=float, default=0.9)
    ap.add_argument("--cap", type=int, default=40)
    a = ap.parse_args()
    out = ROOT / "outputs" / a.tag
    d = real_constraints(pl.read_parquet(out / "daily.parquet")).filter(pl.col("grp") <= a.max_grp)
    t = vic_tags()
    vic = t.filter(pl.col("has_vic_duid").fill_null(False) | pl.col("has_vic_ic").fill_null(False))["constraint"]
    d = d.filter(pl.col("constraint").is_in(vic.implode())).with_columns(pl.col("rental").clip(lower_bound=0).alias("rental_pos"))
    fy = d.group_by("constraint", "fy").agg(pl.col("rental_pos").sum().alias("r"))
    fy = fy.with_columns((pl.col("r") / pl.col("r").sum().over("fy")).alias("share"))
    nfy = d["fy"].n_unique()
    fy = fy.sort("share", descending=True).with_columns(
        (pl.col("share").cum_sum().over("fy") - pl.col("share") < a.fy_cover).alias("in_fy_cover")
    )
    share = fy.group_by("constraint").agg(
        (pl.col("share").sum() / nfy).alias("mean_fy_share"), pl.col("share").max().alias("max_fy_share"),
        pl.col("fy").sort_by("share", descending=True).first().alias("peak_fy"),
        pl.col("in_fy_cover").any().alias("in_any_fy_cover"), pl.col("fy").filter(pl.col("in_fy_cover")).sort().alias("cover_fys"),
    ).with_columns(pl.col("cover_fys").list.join(",").alias("cover_fys"))
    tot = d.group_by("constraint").agg(
        pl.col("rental_pos").sum().alias("rental"), pl.col("hrs_bind").sum().alias("hrs_bind"),
        (pl.col("hrs_bind") > 0).sum().alias("days_bind"), pl.col("rental_pos").max().alias("peak_day_rental"),
        pl.col("price").max().alias("max_price"), pl.col("violation").sum().alias("violation"),
        pl.col("fy").filter(pl.col("rental_pos") > 0).n_unique().alias("fys_binding"),
    ).join(share, on="constraint").filter(pl.col("hrs_bind") > 0)
    tot = tot.with_columns(
        pl.col("mean_fy_share").rank("min", descending=True).alias("share_rank"),
        pl.col("hrs_bind").rank("min", descending=True).alias("hours_rank"),
        pl.col("rental").rank("min", descending=True).alias("rental_rank"),
    ).with_columns(((pl.col("share_rank") + pl.col("hours_rank") + pl.col("rental_rank")) / 3).alias("mean_rank"))
    tot = tot.join(grp_flags().select("constraint", "wrl_lhs_change", "marinus_added", "wrl_new", "wrl_retired"), on="constraint", how="left").sort("mean_rank")
    tot = tot.with_columns(pl.col("max_fy_share").rank("min", descending=True).alias("maxfy_rank"))
    core = tot.head(a.n)["constraint"]
    extra = (tot.filter(pl.col("in_any_fy_cover") & ~pl.col("constraint").is_in(core.implode()))
             .sort("max_fy_share", descending=True).head(max(a.cap - a.n, 0))["constraint"])
    tot = tot.with_columns(
        pl.when(pl.col("constraint").is_in(core.implode())).then(pl.lit("core"))
        .when(pl.col("constraint").is_in(extra.implode())).then(pl.lit("year_specific")).otherwise(pl.lit("")).alias("shortlist_reason")
    ).with_columns((pl.col("shortlist_reason") != "").alias("shortlist"))
    tot.write_csv(out / "draft_list.csv")
    pl.Config.set_tbl_rows(60); pl.Config.set_tbl_cols(30); pl.Config.set_tbl_width_chars(250); pl.Config.set_tbl_formatting("ASCII_MARKDOWN")
    print(tot.filter(pl.col("shortlist") | (pl.int_range(pl.len()) < a.n + 5)).select("constraint", "mean_rank", "share_rank", "hours_rank", "rental_rank", "mean_fy_share", "max_fy_share", "peak_fy", "cover_fys", "hrs_bind", "fys_binding", "peak_day_rental", "max_price", "wrl_lhs_change", "marinus_added", "shortlist_reason"))
    sl = tot.filter(pl.col("shortlist"))
    print(f"shortlist {sl.height} (core {(sl['shortlist_reason'] == 'core').sum()}, year-specific {(sl['shortlist_reason'] == 'year_specific').sum()}): share of positive rental {sl['rental'].sum() / tot['rental'].sum():.1%}, share of hours binding {sl['hrs_bind'].sum() / tot['hrs_bind'].sum():.1%}")
