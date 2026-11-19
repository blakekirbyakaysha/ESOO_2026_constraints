"""What changed between two versions of the no-WRL run (default: no_wrl_v1 = first run with summers missing, vs no_wrl = re-run).

Reads outputs/<tag>/{ranking.csv,draft_list.csv,daily.parquet} and, for the candidate list, <tag>/downstream/final_constraint_list.csv (old)
vs outputs/final_constraint_list.csv (new). Prints and writes outputs/changes_<old>_to_<new>.csv:
  1. seasonal constraints, Dec-Feb after Dec 2030: hours binding in each version (did the summer fix work?)
  2. per-constraint rental / hours / rank change, biggest movers
  3. shortlist membership: added, removed, unchanged
  4. candidate list (final_constraint_list.csv): added, removed, tier changes, equation_form changes

Usage: python scripts/compare_versions.py [--old no_wrl_v1] [--new no_wrl]
"""
import argparse
import sys
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parent))  # sibling imports also work under python -I

from esoo_results import ROOT

ap = argparse.ArgumentParser()
ap.add_argument("--old", default="no_wrl_v1")
ap.add_argument("--new", default="no_wrl")
a = ap.parse_args()
out = ROOT / "outputs"

# 1. did the summer fix work
meta = pl.read_parquet(ROOT / "cache" / "eq_meta.parquet").filter(pl.col("timeslice").str.contains("NotSummer_Grp"))
seasonal = meta["constraint"].unique().to_list()
print("1. seasonal constraints, Dec-Feb after Dec 2030 (Grp<=9): hours binding / constraints binding")
for t in (a.old, a.new):
    d = pl.read_parquet(out / t / "daily.parquet", columns=["constraint", "date", "hrs_bind", "grp"]).filter(
        pl.col("constraint").is_in(seasonal) & (pl.col("date") >= pl.date(2030, 12, 1)) & (pl.col("grp") <= 9) & pl.col("date").dt.month().is_in([12, 1, 2])
    )
    n = d.filter(pl.col("hrs_bind") > 0)["constraint"].n_unique()
    print(f"   {t:12s} {d['hrs_bind'].sum():>10,.0f} hours   {n} constraints")

# 2. per-constraint changes
def rk(t):
    r = pl.read_csv(out / t / "ranking.csv").select("constraint", "rental", "hrs_bind", "peak_day_rental")
    return r.with_columns(pl.col("rental").rank("ordinal", descending=True).alias("rental_rank"))
o, n = rk(a.old), rk(a.new)
j = o.join(n, on="constraint", how="full", coalesce=True, suffix="_new").rename({"rental": "rental_old", "hrs_bind": "hrs_old", "peak_day_rental": "peak_old", "rental_rank": "rank_old", "rental_new": "rental_new", "hrs_bind_new": "hrs_new", "peak_day_rental_new": "peak_new", "rental_rank_new": "rank_new"})
j = j.with_columns((pl.col("rental_new").fill_null(0) - pl.col("rental_old").fill_null(0)).alias("d_rental"), (pl.col("hrs_new").fill_null(0) - pl.col("hrs_old").fill_null(0)).alias("d_hrs"))
j.sort("d_rental", descending=True).write_csv(out / f"changes_{a.old}_to_{a.new}.csv")
print(f"\n2. ranking: {o.height} constraints bind in {a.old}, {n.height} in {a.new}; written to outputs/changes_{a.old}_to_{a.new}.csv")
print("   biggest rental increases:", j.sort("d_rental", descending=True).head(8).select("constraint", "d_rental", "d_hrs").to_dicts())
print("   biggest rental decreases:", j.sort("d_rental").head(5).select("constraint", "d_rental", "d_hrs").to_dicts())

# 3. shortlist membership
def sl(t):
    return set(pl.read_csv(out / t / "draft_list.csv").filter(pl.col("shortlist_reason").is_in(["core", "year_specific"]))["constraint"])
so, sn = sl(a.old), sl(a.new)
print(f"\n3. shortlist: {a.old} {len(so)}, {a.new} {len(sn)}, unchanged {len(so & sn)}")
print("   added:", sorted(sn - so)); print("   removed:", sorted(so - sn))

# 4. candidate list
old_f, new_f = out / a.old / "downstream" / "final_constraint_list.csv", out / "final_constraint_list.csv"
if old_f.exists() and new_f.exists():
    fo, fn = pl.read_csv(old_f), pl.read_csv(new_f)
    co, cn = set(fo["constraint"]), set(fn["constraint"])
    print(f"\n4. candidate list: old {len(co)}, new {len(cn)}, unchanged {len(co & cn)}")
    print("   added:", sorted(cn - co)); print("   removed:", sorted(co - cn))
    m = fo.select("constraint", pl.col("tier").alias("tier_old"), pl.col("equation_form").alias("form_old")).join(fn.select("constraint", pl.col("tier").alias("tier_new"), pl.col("equation_form").alias("form_new")), on="constraint")
    print("   tier changes:", m.filter(pl.col("tier_old") != pl.col("tier_new")).select("constraint", "tier_old", "tier_new").to_dicts())
    print("   equation_form changes:", m.filter(pl.col("form_old") != pl.col("form_new")).select("constraint", "form_old", "form_new").to_dicts())
else:
    print("\n4. candidate list: run scripts/final_list.py first (needs outputs/final_constraint_list.csv)")
