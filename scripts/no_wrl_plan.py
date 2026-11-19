"""Build the no-WRL edit plan for the ESOO constraint inputs (format-independent).

Targeted method (see PROJECT_CONTEXT.md): WRL is the Grp5->6 step (Nov 2030).
  drop        wrl_new           27 constraints first defined at Grp6 (V>>WVic_* etc.): delete
  restore     wrl_retired (Vic) Victorian constraints last defined at Grp5: keep their Grp5 equation for Grp6-11
  revert      wrl_lhs_change    use the Grp5 equation (LHS + rhsTerms) for Grp6-11
  +marinus    marinus_added     Marinus is kept, so at Grp8-11 the reverted equation also gets Marinus_1 at its Grp8 coefficient
  keep        everything else, as published
Writes outputs/no_wrl/plan.csv (one row per constraint with an action) and prints counts.
"""
import sys
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parent))  # sibling imports also work under python -I

from esoo_results import ROOT, vic_tags
from rank_constraints import grp_flags

flags = grp_flags()
tags = vic_tags().select("constraint", "has_vic_duid", "has_vic_ic")
p = flags.join(tags, on="constraint", how="left").with_columns(
    (pl.col("has_vic_duid").fill_null(False) | pl.col("has_vic_ic").fill_null(False)).alias("vic")
)
p = p.with_columns(
    pl.when(pl.col("wrl_new")).then(pl.lit("drop"))
    .when(pl.col("wrl_retired") & pl.col("vic")).then(pl.lit("restore"))
    .when(pl.col("wrl_lhs_change") & ~pl.col("wrl_retired")).then(pl.lit("revert"))
    .when(pl.col("wrl_retired")).then(pl.lit("retired_non_vic_review"))
    .otherwise(pl.lit("keep")).alias("action")
)
print(p.group_by("action").len().sort("action"))
print("revert + marinus term:", p.filter((pl.col("action").is_in(["revert", "restore"])) & pl.col("marinus_added")).height)
print("marinus_added but action keep:", p.filter((pl.col("action") == "keep") & pl.col("marinus_added")).height)
p.filter(pl.col("action") != "keep").sort("action", "constraint").write_csv(ROOT / "outputs" / "no_wrl" / "plan.csv")
