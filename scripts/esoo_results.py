"""Load PLEXOS constraint results dropped in inputs/ESOO_results/<FY>/*.csv and summarise them.

Folder convention: ESOO_results/2027/Hours Binding.csv, Price.csv, ...  (FY27 = Jul-2026..Jun-2027).
Per-property CSVs have columns Name, Year, Month, Day, Period, Value (daily output, Period = 1).

Usage:
    python scripts/esoo_results.py [results_root] [--tag no_wrl]
writes summary parquet/csv to outputs/<tag>/.
"""
import argparse
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "cache"

# Property CSV stem -> column name. Hours Active is always 24 so is skipped.
PROPS = {
    "Hours Binding": "hrs_bind",
    "Price": "price",
    "Rental": "rental",
    "Violation": "violation",
    "Penalty Cost": "penalty_cost",
    "Activity": "activity",
    "RHS": "rhs",
    "Slack": "slack",
}
BIG = 1e20  # RHS / slack sentinel (2.4e31) meaning "no limit"

# Timeslice start dates (ESOO 'Timeslice' sheet). Grp N applies from its start until the next start.
GRP_STARTS = [
    (0, "2026-07-01"), (1, "2027-02-01"), (2, "2027-12-01"), (3, "2028-06-01"),
    (4, "2029-05-01"), (5, "2030-03-01"), (6, "2030-11-01"), (7, "2031-07-01"),
    (8, "2031-12-01"), (9, "2032-04-01"), (10, "2033-07-01"), (11, "2035-01-01"),
]

VIC_INTERCONNECTORS = ["VIC1-NSW1", "V-SA", "V-S-MNSP1", "T-V-MNSP1", "NSW1-SA1", "Marinus_1"]


def grp_table() -> pl.DataFrame:
    return pl.DataFrame(GRP_STARTS, schema=["grp", "start"], orient="row").with_columns(
        pl.col("start").str.to_date()
    ).sort("start")


def load_property(root: Path, stem: str) -> pl.LazyFrame:
    """One property across all FY folders -> Name, fy, date, <col>."""
    frames = []
    for fy_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        f = fy_dir / f"{stem}.csv"
        if f.exists():
            frames.append(
                pl.scan_csv(f, schema_overrides={"Value": pl.Float64}).with_columns(
                    pl.lit(fy_dir.name).alias("fy")
                )
            )
    if not frames:
        raise FileNotFoundError(f"no '{stem}.csv' under {root}")
    col = PROPS[stem]
    return (
        pl.concat(frames)
        .with_columns(pl.date(pl.col("Year"), pl.col("Month"), pl.col("Day")).alias("date"))
        .select(pl.col("Name").alias("constraint"), "fy", "date", pl.col("Value").alias(col))
    )


def load_daily(root: Path) -> pl.DataFrame:
    """Constraint x day table with every available property joined on, plus Grp."""
    df = None
    for stem, col in PROPS.items():
        try:
            lf = load_property(root, stem)
        except FileNotFoundError:
            continue
        if col in ("rhs", "slack"):
            lf = lf.with_columns(pl.when(pl.col(col).abs() > BIG).then(None).otherwise(pl.col(col)).alias(col))
        df = lf if df is None else df.join(lf, on=["constraint", "fy", "date"], how="left")
    daily = df.collect()
    return daily.sort("date").join_asof(grp_table(), left_on="date", right_on="start").drop("start")


def base_name(col: str = "constraint") -> pl.Expr:
    """PLEXOS split constraints carry '_G_<n>' suffixes (sometimes chained); the workbook uses the base name."""
    return pl.col(col).str.replace(r"(_G_\d+)+$", "")


def load_categories() -> pl.DataFrame | None:
    """constraint_objects.csv (PLEXOS export): Name -> category ('NetworkConstraints' or 'NetworkSubEquations').
    Sub-equations sit on the RHS tied to decision variables and are not real constraints."""
    f = ROOT / "inputs" / "constraint_objects.csv"
    if not f.exists():
        return None
    return pl.read_csv(f, encoding="utf8-lossy").select(pl.col("Name").alias("constraint"), pl.col("Category").alias("category"))


def real_constraints(df: pl.DataFrame, col: str = "constraint") -> pl.DataFrame:
    """Keep real constraints only. Uses constraint_objects.csv; names missing from it are reported and kept
    unless they match the '_G_<n>' sub-equation pattern. Falls back to the pattern if the file is absent."""
    pattern = pl.col(col).str.contains(r"_G_\d+$")
    cats = load_categories()
    if cats is None:
        print("WARNING: constraint_objects.csv not found; using the _G_<n> name pattern to drop sub-equations")
        return df.filter(~pattern)
    cats = cats.rename({"constraint": col})
    j = df.join(cats, on=col, how="left")
    unk = j.filter(pl.col("category").is_null())[col].unique()
    if len(unk):
        print(f"WARNING: {len(unk)} names not in constraint_objects.csv (kept unless _G_ pattern), e.g. {unk.head(5).to_list()}")
    keep = (pl.col("category") == "NetworkConstraints") | (pl.col("category").is_null() & ~pattern)
    return j.filter(keep).drop("category")


def vic_tags() -> pl.DataFrame | None:
    """Per constraint: does the LHS carry a Victorian DUID and/or a VIC-relevant interconnector?
    Needs cache/ from scripts/build_lhs_cache.py and esoo_node_memberships.csv."""
    terms_f, mem_f = CACHE / "lhs_terms.parquet", ROOT / "inputs" / "esoo_node_memberships.csv"
    if not (terms_f.exists() and mem_f.exists()):
        return None
    mem = pl.read_csv(mem_f).select(pl.col("Parent Name").alias("obj"), pl.col("Child Category").alias("region")).unique()
    vic_objs = mem.filter(pl.col("region") == "VIC")["obj"].unique().to_list()
    terms = pl.read_parquet(terms_f)
    return terms.group_by("constraint").agg(
        pl.col("obj").is_in(vic_objs).any().alias("has_vic_duid"),
        pl.col("obj").is_in(VIC_INTERCONNECTORS).any().alias("has_vic_ic"),
        pl.col("obj").filter(pl.col("obj").is_in(VIC_INTERCONNECTORS)).unique().sort().str.join(";").alias("ics"),
        pl.col("obj").is_in(vic_objs).sum().alias("n_vic_duid_terms"),
    )


def summarise(daily: pl.DataFrame) -> pl.DataFrame:
    """Per constraint x FY x Grp impact metrics."""
    have = [c for c in ("price", "rental", "violation", "penalty_cost") if c in daily.columns]
    aggs = [
        pl.col("hrs_bind").sum().alias("hrs_bind"),
        (pl.col("hrs_bind") > 0).sum().alias("days_bind"),
    ]
    if "price" in have:
        aggs += [pl.col("price").max().alias("max_price"),
                 (pl.col("price") * pl.col("hrs_bind")).sum().alias("price_x_hrs")]
    for c in ("rental", "violation", "penalty_cost"):
        if c in have:
            aggs.append(pl.col(c).sum().alias(c))
    out = daily.group_by("constraint", "fy", "grp").agg(aggs)
    out = out.with_columns(base_name().alias("constraint_base"))
    tags = vic_tags()
    if tags is not None:
        out = out.join(tags, left_on="constraint_base", right_on="constraint", how="left")
    return out.sort("fy", "grp", "hrs_bind", descending=[False, False, True])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("root", nargs="?", default=str(ROOT / "inputs" / "ESOO_results"))
    ap.add_argument("--tag", default="with_wrl", help="label for the run, used as output folder name")
    a = ap.parse_args()
    root = Path(a.root)
    if not root.exists() and (ROOT / "inputs" / a.root).exists():   # bare folder name -> inputs/<name>
        root = ROOT / "inputs" / a.root
    daily = load_daily(root)
    summ = summarise(daily)
    out = ROOT / "outputs" / a.tag
    out.mkdir(parents=True, exist_ok=True)
    daily.write_parquet(out / "daily.parquet")
    summ.write_csv(out / "summary_by_constraint_fy_grp.csv")
    print(f"{daily.height:,} constraint-days, {summ.height:,} summary rows -> {out}")
