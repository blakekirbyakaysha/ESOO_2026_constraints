"""Build the PLEXOS half-hourly RHS input file from the hourly ESOO RHS results in inputs/final_rhs/.

Layout follows the template inputs/raw/ESOO_2026_constraint_RHS.csv: Year, Month, Day, Period, then one column per constraint.
The column list and order are read from the template, so edit the template to add or remove columns. The template only lists the
odd periods (hourly, held for 30 min); this script writes all 48 periods per day.
    odd period 2h+1 (hh:00)  = the ESOO hourly value for hour h
    even period 2h+2 (hh:30) = the average of hour h and hour h+1 (23:30 uses the next day's 00:00)

Source folders (inputs/final_rhs/<FY>[_no WRL]/RHS.csv, long format Name,Year,Month,Day,Period,Value; FY = year the FY ends,
Period 1..24 = hour starting 00:00). Empty or missing folders are tolerated and filled (see below).

Column rules (decisions by Blake, 2026-10-30):
  '<name>_no WRL'    no-WRL folders; with-WRL folder when a pre-WRL FY has no no-WRL folder (FY <= PRE_WRL_LAST_FY).
  '<name>_with WRL'  with-WRL folders; no-WRL folder when a pre-WRL FY has no with-WRL folder.
  '<name>' (shared)  with-WRL folders (same pre-WRL fallback as above).
  'no limit' (1e30) neighbour: the half-hour takes the finite neighbour; both no-limit gives 1e30.
  No source data (no folder, constraint not run, e.g. LINC1_LITO1 and DPTX3_DPTX4 are not modelled): 1e30 (no limit),
  listed in the report so it is obvious what still needs the real data.
  A single missing hour between two present hours (each file lacks 23:00 on 1 July) is filled from its neighbours and reported.

Out-of-model adjustments (ADJUSTMENTS below; applied to the hourly RHS before averaging, every scenario column of that constraint;
the other adders in outputs/FINAL/final_rhs_adders.csv are already entered in the ESOO equations):
  SIPS: V>>V_NIL_DDSM1_DDSM2 and V>>V_NIL_MRDD1_MRDB2 set to 10,000 MW in Nov-Mar until 2032-03-31.
  N::N_NIL_63: +65 MW in Dec-Feb (the equation carries +45 everywhere; summer needs +110).

Outputs (outputs/FINAL/rhs_30min/): ESOO_2026_constraint_RHS_30min.csv and ESOO_2026_constraint_RHS_30min_report.csv.
Run: .venv\\Scripts\\python.exe -X utf8 -I scripts\\build_rhs_30min.py [--start 2026-07-01] [--end 2033-06-30]
"""
import argparse
import re
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "inputs" / "final_rhs"
TEMPLATE = ROOT / "inputs" / "raw" / "ESOO_2026_constraint_RHS.csv"
OUT = ROOT / "outputs" / "FINAL" / "rhs_30min"

NOLIM = 1e30             # PLEXOS 'no limit'
NOLIM_TEST = 1e29        # anything at or above this is treated as no limit
PRE_WRL_LAST_FY = 2030   # WRL enters in Nov 2030 (FY31); up to FY30 the two scenarios share a network
GRID_START = date(2026, 7, 1)   # first hour of FY27

# kind 'set': value set to `value` where the RHS is a real limit; kind 'add': value added.
# months are calendar months; to is inclusive (None = end of run).
ADJUSTMENTS = [
    dict(name="V>>V_NIL_DDSM1_DDSM2", kind="set", value=10000.0, months=(11, 12, 1, 2, 3), to=date(2032, 3, 31), why="SIPS"),
    dict(name="V>>V_NIL_MRDD1_MRDB2", kind="set", value=10000.0, months=(11, 12, 1, 2, 3), to=date(2032, 3, 31), why="SIPS"),
    dict(name="N::N_NIL_63", kind="add", value=65.0, months=(12, 1, 2), to=None, why="Dec-Feb adder beyond the +45 in the equation"),
]


def mid(a, b):
    """Half-hour value between hours a and b (arrays). NaN = no data in either hour."""
    with np.errstate(invalid="ignore"):
        na, nb = a >= NOLIM_TEST, b >= NOLIM_TEST
        out = (a + b) / 2
        out = np.where(na & ~nb, b, out)
        out = np.where(nb & ~na, a, out)
        out = np.where(na & nb, NOLIM, out)
    return np.where(np.isnan(a) | np.isnan(b), np.nan, out)


def fy_of(ts):
    """Financial year (year it ends) of a datetime64[h] array."""
    months = ts.astype("datetime64[M]")
    y = months.astype("datetime64[Y]").astype(int) + 1970
    m = months.astype(int) % 12 + 1
    return y + (m >= 7)


def load_sources(t0, n_hours):
    """Return {scenario: {name: hourly array}} and {(scenario, fy): True} for folders actually loaded."""
    raw = {"with": {}, "no": {}}
    loaded = set()
    folders = []
    for f in SRC.iterdir():
        m = re.fullmatch(r"(\d{4})(_no WRL)?", f.name)
        if m and f.is_dir():
            folders.append((int(m.group(1)), "no" if m.group(2) else "with", f))
    for fy, scen, f in sorted(folders):             # ascending FY: the next FY's first hour overrides the boundary row
        p = f / "RHS.csv"
        if not p.exists() or p.stat().st_size == 0:
            print(f"  (empty folder, skipped: {f.name})")
            continue
        d = pl.read_csv(p, infer_schema_length=100000)
        d = d.with_columns(
            idx=((pl.date("Year", "Month", "Day") - pl.lit(t0)).dt.total_days() * 24 + pl.col("Period") - 1).cast(pl.Int64))
        loaded.add((scen, fy))
        for (name,), g in d.group_by("Name"):
            arr = raw[scen].setdefault(name, np.full(n_hours, np.nan))
            idx = g["idx"].to_numpy()
            keep = (idx >= 0) & (idx < n_hours)
            arr[idx[keep]] = g["Value"].to_numpy()[keep]
    return raw, loaded


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-07-01")
    ap.add_argument("--end", default="2033-06-30")
    a = ap.parse_args()
    start, end = date.fromisoformat(a.start), date.fromisoformat(a.end)
    n_days = (end - start).days + 1
    t0 = GRID_START
    n_hours = (end - t0).days * 24 + 24 + 1            # grid from FY27 start to the end of run, plus the next midnight
    ts = np.datetime64(t0, "h") + np.arange(n_hours)
    fy = fy_of(ts)
    off = (start - t0).days * 24                        # first output hour on the grid

    template_cols = pl.read_csv(TEMPLATE, n_rows=0).columns
    cols = template_cols[4:]
    print(f"Template: {len(cols)} constraint columns; output {start} to {end} = {n_days} days x 48 periods")

    raw, loaded = load_sources(t0, n_hours)
    loaded_fy = {s: sorted(f for (sc, f) in loaded if sc == s) for s in raw}
    print("Loaded FY folders:", {s: v for s, v in loaded_fy.items()})

    # pre-WRL fallback: a scenario with no folder for a pre-WRL FY takes the other scenario's data for that FY
    other = {"with": "no", "no": "with"}
    fallback_fys = {s: [f for f in range(fy.min(), PRE_WRL_LAST_FY + 1)
                        if (s, f) not in loaded and (other[s], f) in loaded] for s in raw}
    series = {s: {n: v.copy() for n, v in raw[s].items()} for s in raw}
    for s, fys in fallback_fys.items():
        for f in fys:
            sel = fy == f
            for n, v in raw[other[s]].items():
                series[s].setdefault(n, np.full(n_hours, np.nan))[sel] = v[sel]
    for s, fys in fallback_fys.items():
        if fys:
            print(f"  {s}-WRL columns: FY{fys} copied from {other[s]}-WRL (pre-WRL, same network)")

    month = ts.astype("datetime64[M]").astype(int) % 12 + 1
    day_end = ts.astype("datetime64[D]")
    report = []

    def resolve(col):
        if col.endswith("_no WRL"):
            return "no", col[: -len("_no WRL")]
        if col.endswith("_with WRL"):
            return "with", col[: -len("_with WRL")]
        return "with", col

    used = set()
    out_cols = {}
    for col in cols:
        scen, name = resolve(col)
        used.add((scen, name))
        h = series[scen].get(name)
        if h is None:
            out_cols[col] = np.full(n_days * 48, NOLIM)
            report.append(dict(column=col, issue="no source data in any folder: filled 1e30", first="", last="", hours=n_days * 24))
            continue
        h = h.copy()
        # single missing hour between two present hours
        gap = np.isnan(h)
        gap[0] = gap[-1] = False
        fillable = gap & ~np.isnan(np.roll(h, 1)) & ~np.isnan(np.roll(h, -1))
        fillable &= (np.arange(n_hours) >= off) & (np.arange(n_hours) < off + n_days * 24)
        for i in np.flatnonzero(fillable):
            h[i] = mid(h[i - 1], h[i + 1])
            report.append(dict(column=col, issue="single missing hour interpolated", first=str(ts[i]), last=str(ts[i]), hours=1))
        # out-of-model adjustments
        for adj in ADJUSTMENTS:
            if adj["name"] != name:
                continue
            m = np.isin(month, adj["months"]) & ~np.isnan(h) & (h < NOLIM_TEST)
            if adj["to"] is not None:
                m &= day_end <= np.datetime64(adj["to"], "D")
            h[m] = adj["value"] if adj["kind"] == "set" else h[m] + adj["value"]
            report.append(dict(column=col, issue=f"adjustment applied ({adj['kind']} {adj['value']:g}, {adj['why']})",
                               first=str(ts[m][0]) if m.any() else "", last=str(ts[m][-1]) if m.any() else "", hours=int(m.sum())))
        # hourly -> 48 periods per day
        hh = h[off: off + n_days * 24 + 1]
        o = np.empty(n_days * 48)
        o[0::2] = hh[:-1]
        o[1::2] = mid(hh[:-1], hh[1:])
        miss = np.isnan(o)
        if miss.any():
            # report contiguous missing blocks at day resolution
            idx = np.flatnonzero(miss)
            blocks = np.split(idx, np.flatnonzero(np.diff(idx) > 1) + 1)
            for b in blocks:
                s_ts = np.datetime64(start, "m") + b[0] * 30
                e_ts = np.datetime64(start, "m") + b[-1] * 30
                report.append(dict(column=col, issue="no source data for these periods: filled 1e30", first=str(s_ts), last=str(e_ts), hours=round(len(b) / 2, 1)))
            o[miss] = NOLIM
        out_cols[col] = o

    used_names = {n for _, n in used}
    unused = sorted({n for s in series for n in series[s]} - used_names)
    if unused:
        print("Result names with no template column:", unused)

    # index columns
    days = np.array([start + timedelta(days=i) for i in range(n_days)])
    year = np.repeat([d.year for d in days], 48)
    mon = np.repeat([d.month for d in days], 48)
    dom = np.repeat([d.day for d in days], 48)
    per = np.tile(np.arange(1, 49), n_days)
    df = {"Year": year.astype(str), "Month": mon.astype(str), "Day": dom.astype(str), "Period": per.astype(str)}
    for col, v in out_cols.items():
        s = np.char.mod("%.4f", v)
        s[v >= NOLIM_TEST] = "1e+30"
        df[col] = s
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / "ESOO_2026_constraint_RHS_30min.csv"
    pl.DataFrame(df).write_csv(p, quote_style="never")
    rep = pl.DataFrame(report, schema={"column": pl.Utf8, "issue": pl.Utf8, "first": pl.Utf8, "last": pl.Utf8, "hours": pl.Float64})
    rep.write_csv(OUT / "ESOO_2026_constraint_RHS_30min_report.csv")

    print(f"Wrote {p} ({n_days * 48} rows x {len(df)} columns)")
    print(f"Wrote report ({rep.height} lines). Summary of issues:")
    if rep.height:
        print(rep.group_by("issue").agg(pl.col("column").n_unique().alias("columns"), pl.col("hours").sum().alias("hours")).sort("issue"))
    ex = [c for c in cols if (out_cols[c] >= NOLIM_TEST).all()]
    if ex:
        print("Columns that are 1e30 for the whole period:", ex)


if __name__ == "__main__":
    main()
