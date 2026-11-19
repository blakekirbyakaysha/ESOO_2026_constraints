"""Interconnector-only no-WRL edits: for each constraint on outputs/no_wrl/freeze_grp5_list.csv, list every LINE
(interconnector) coefficient in Grp6-11 that differs from its Grp5 value, with the Grp5 value to put back (0 = remove term).
Generator / battery terms are left as published (mostly fleet additions, not network).
Writes outputs/no_wrl/line_edits.csv (constraint, timeslice, interconnector, published_coef, no_wrl_coef)."""
import sys
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parent))  # sibling imports also work under python -I

from esoo_results import ROOT

fr = pl.read_csv(ROOT / "outputs" / "no_wrl" / "freeze_grp5_list.csv")["constraint"]
t = pl.read_parquet(ROOT / "cache" / "lhs_terms.parquet").filter(
    pl.col("constraint").is_in(fr.implode()) & (pl.col("obj_type") == "LINE")
).with_columns(
    pl.col("timeslice").str.extract(r"(Summer|NotSummer)_", 1).fill_null("").alias("s"),
    pl.col("timeslice").str.extract(r"Grp(\d+)", 1).cast(pl.Int64).alias("g"),
).drop_nulls("g")
g5 = t.filter(pl.col("g") == 5).select("constraint", "s", "obj", pl.col("coef").alias("no_wrl_coef"))
later = t.filter(pl.col("g") >= 6)
grid = g5.select("constraint", "s").unique().join(later.select("constraint", "s", "g").unique(), on=["constraint", "s"])
# every (constraint, season, later Grp) x every interconnector seen in Grp5 or that Grp
objs = pl.concat([g5.select("constraint", "s", "obj"), later.select("constraint", "s", "obj")]).unique()
d = (
    grid.join(objs, on=["constraint", "s"])
    .join(g5, on=["constraint", "s", "obj"], how="left")
    .join(later.select("constraint", "s", "g", "obj", pl.col("coef").alias("published_coef")), on=["constraint", "s", "g", "obj"], how="left")
    .with_columns(pl.col("no_wrl_coef").fill_null(0.0), pl.col("published_coef").fill_null(0.0))
    .filter((pl.col("no_wrl_coef") - pl.col("published_coef")).abs() > 1e-9)
    .with_columns(
        pl.when(pl.col("s") == "").then(pl.format("Grp{}", pl.col("g"))).otherwise(pl.format("{}_Grp{}", pl.col("s"), pl.col("g"))).alias("timeslice")
    )
    .select("constraint", "timeslice", pl.col("obj").alias("interconnector"), "published_coef", "no_wrl_coef")
    .sort("constraint", "timeslice", "interconnector")
)
d.write_csv(ROOT / "outputs" / "no_wrl" / "line_edits.csv")
print("edits:", d.height, "constraints:", d["constraint"].n_unique())
print(d.group_by("interconnector").len().sort("len", descending=True))
