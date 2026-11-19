"""Build the candidate constraint list for the user's own model from both runs' rankings.

Tier A = union of the with_wrl and no_wrl shortlists (draft_list.csv, core + year_specific).
Tier B = not in tier A, but a single day's rental >= --spike in either run (episodic constraints; price-dependent, so review).
Constraints first defined at Grp6 (WRL-only, `wrl_new`) are dropped: they do not exist in a no-WRL model.

For each constraint it says which equation to take for a no-WRL model: the Grp5 equation if WRL (or Marinus) touches it, otherwise the
latest published equation up to Grp9. Marinus is KEPT by default (published Grp8+ equations already carry `Marinus_1`; WRL-affected
constraints that also carry it need Grp5 + the Marinus_1 term, flagged in `add_marinus_term`). Pass --no-marinus to treat Marinus-added
constraints as Grp5-form too. It also lists the `_G_<n>` sub-equations that form needs (group ids in its rhsTerms).

Writes outputs/final_constraint_list.csv and outputs/final_constraint_subequations.csv.
Usage: python scripts/final_list.py [--spike 1000]
"""
import argparse
import sys
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parent))  # sibling imports also work under python -I

from esoo_results import ROOT

TAGS = ("no_wrl", "with_wrl")
ap = argparse.ArgumentParser()
ap.add_argument("--no-marinus", action="store_true", help="exclude Marinus: also hold Marinus-added constraints at Grp5")
ap.add_argument("--spike", type=float, default=1000.0, help="tier B: single-day rental threshold")
a = ap.parse_args()

dl = {t: pl.read_csv(ROOT / "outputs" / t / "draft_list.csv") for t in TAGS}
rk = {t: pl.read_csv(ROOT / "outputs" / t / "ranking.csv") for t in TAGS}
short = {t: set(dl[t].filter(pl.col("shortlist_reason").is_in(["core", "year_specific"]))["constraint"]) for t in TAGS}

spike = set()
for t in TAGS:
    spike |= set(rk[t].filter(pl.col("peak_day_rental") >= a.spike)["constraint"])
tier_a = short["no_wrl"] | short["with_wrl"]
tier_b = spike - tier_a
cands = sorted(tier_a | tier_b)

flags = rk["no_wrl"].select("constraint", "wrl_lhs_change", "marinus_added", "wrl_new", "wrl_retired", "first_grp", "last_grp").join(
    rk["with_wrl"].select("constraint", "wrl_lhs_change", "marinus_added", "wrl_new", "wrl_retired", "first_grp", "last_grp"),
    on="constraint", how="full", coalesce=True,
)
# the flag columns are identical in both rankings (same workbook); take whichever is present
flag_cols = {c: pl.coalesce(c, f"{c}_right").alias(c) for c in ["wrl_lhs_change", "marinus_added", "wrl_new", "wrl_retired", "first_grp", "last_grp"]}
flags = flags.select("constraint", *flag_cols.values())

def side(t: str, suffix: str) -> pl.DataFrame:
    r = rk[t].select("constraint", "rental", "hrs_bind", "peak_day_rental", "max_price")
    d = dl[t].select("constraint", "mean_rank", "shortlist_reason")
    return r.join(d, on="constraint", how="left").rename({c: f"{c}_{suffix}" for c in r.columns + d.columns if c != "constraint"})

out = (
    pl.DataFrame({"constraint": cands})
    .join(side("no_wrl", "nowrl"), on="constraint", how="left")
    .join(side("with_wrl", "withwrl"), on="constraint", how="left")
    .join(flags, on="constraint", how="left")
    .with_columns(
        pl.col("constraint").is_in(list(tier_a)).map_elements(lambda x: "A" if x else "B", return_dtype=pl.String).alias("tier"),
        pl.max_horizontal("peak_day_rental_nowrl", "peak_day_rental_withwrl").alias("peak_day_rental_max"),
    )
)
dropped = out.filter(pl.col("wrl_new").fill_null(False))["constraint"].to_list()
out = out.filter(~pl.col("wrl_new").fill_null(False))

# equation form for a no-WRL model
meta = pl.read_parquet(ROOT / "cache" / "eq_meta.parquet").with_columns(
    pl.col("timeslice").str.extract(r"Grp(\d+)", 1).cast(pl.Int64).alias("g")
).drop_nulls("g")
last = meta.filter(pl.col("g") <= 9).group_by("constraint").agg(pl.col("g").max().alias("latest_grp_le9"))
out = out.join(last, on="constraint", how="left").with_columns(
    (pl.col("wrl_lhs_change").fill_null(False) | pl.col("wrl_retired").fill_null(False) | (pl.col("marinus_added").fill_null(False) & a.no_marinus)).alias("needs_grp5"),
    (pl.col("marinus_added").fill_null(False) & ~pl.lit(a.no_marinus)).alias("has_marinus"),
).with_columns(
    pl.when(pl.col("needs_grp5")).then(5).otherwise(pl.col("latest_grp_le9")).alias("eq_grp"),
).with_columns(
    pl.when(pl.col("needs_grp5")).then(pl.lit("Grp5 (WRL-affected)")).otherwise(pl.lit("as published (latest Grp<=9)")).alias("equation_form"),
    (pl.col("needs_grp5") & pl.col("has_marinus")).alias("add_marinus_term"),
    pl.when(pl.col("peak_day_rental_max") >= 50000).then(pl.lit("single-day rental > $50k: check for scarcity/violation")).otherwise(pl.lit("")).alias("review_note"),
)

# sub-equations of the chosen Grp form, checked against constraint_objects.csv. rhsTerms lines are `termId, groupId, type, name, coef, ...`:
#  - a type-G term t inside group p opens group t; its object is <constraint>_G_<t> (top level) or <parent object>_G_<t> (nested), so the
#    whole ancestor chain is in the name (e.g. N::N_NIL_63_G_2_G_3), not just the group id
#  - a type-X term names a sub-equation directly (X_..., X-...); its own `_G_` children are matched by prefix in constraint_objects.csv
#  - any other term whose name is a sub-equation object is picked up too (e.g. CHK_*, SA_METRO_GEN_ON)
# Excel cuts cells at 32,767 characters, so some Grp5 rhsTerms end mid-line; those constraints are flagged in `rhs_truncated`.
objs = set(pl.read_csv(ROOT / "inputs" / "constraint_objects.csv").filter(pl.col("Category") == "NetworkSubEquations")["Name"])


def with_children(base: str) -> list[str]:
    return sorted(x for x in objs if x == base or x.startswith(base + "_G_"))


rows, truncated = [], []
for c, g in out.select("constraint", "eq_grp").iter_rows():
    names = set()
    for rhs in meta.filter((pl.col("constraint") == c) & (pl.col("g") == g))["rhsTerms"].drop_nulls():
        if len(rhs.rstrip().split(chr(10))[-1].split(",")) < 8:
            truncated.append(c)
        gobj = {0: c}
        terms = []
        for ln in rhs.splitlines():
            p = [x.strip() for x in ln.split(",")]
            if len(p) >= 8 and p[0].isdigit() and p[1].isdigit():
                terms.append((int(p[0]), int(p[1]), p[2], p[3]))
        for t, gi, ty, nm in terms:  # parents precede children in the term order
            if ty == "G":
                gobj[t] = f"{gobj.get(gi, c)}_G_{t}"
        for t, o in gobj.items():
            if t:
                names.add(o)
        for t, gi, ty, nm in terms:
            if nm and (ty == "X" or nm in objs or any(x.startswith(nm + "_G_") for x in objs)):
                names.add(nm)
    for base in sorted(names):
        found = with_children(base)
        for n in found:
            rows.append((c, g, n))
        if base not in objs:
            rows.append((c, g, base + "  (not in constraint_objects.csv)"))
subs = pl.DataFrame(rows, schema=["constraint", "eq_grp", "sub_equation"], orient="row").unique(maintain_order=True)
out = out.with_columns(pl.col("constraint").is_in(truncated).alias("rhs_truncated"))
n_sub = subs.group_by("constraint").len().rename({"len": "n_sub_equations"})
out = out.join(n_sub, on="constraint", how="left").with_columns(pl.col("n_sub_equations").fill_null(0)).sort("tier", "mean_rank_nowrl", nulls_last=True)

cols = ["constraint", "tier", "shortlist_reason_nowrl", "shortlist_reason_withwrl", "mean_rank_nowrl", "mean_rank_withwrl", "rental_nowrl", "rental_withwrl",
        "hrs_bind_nowrl", "hrs_bind_withwrl", "peak_day_rental_max", "max_price_nowrl", "wrl_lhs_change", "marinus_added", "wrl_retired",
        "equation_form", "eq_grp", "has_marinus", "add_marinus_term", "n_sub_equations", "rhs_truncated", "review_note"]
out.select(cols).write_csv(ROOT / "outputs" / "final_constraint_list.csv")
subs.write_csv(ROOT / "outputs" / "final_constraint_subequations.csv")
print(f"tier A (union of shortlists): {out.filter(pl.col('tier') == 'A').height}   tier B (single day >= ${a.spike:,.0f}): {out.filter(pl.col('tier') == 'B').height}")
print("dropped as WRL-only:", dropped)
print(out.group_by("equation_form").len())
print("sub-equation rows:", subs.height, " constraints with sub-equations:", n_sub.height)
print("rhs truncated at the Excel cell limit (sub-equations in the cut-off tail cannot be seen):", truncated)
print("review notes:", out.filter(pl.col("review_note") != "")["constraint"].to_list())
