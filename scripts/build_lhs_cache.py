"""One-off: stream the ESOO constraint workbook into small parquet caches.

Outputs (in cache/):
  eq_meta.parquet   constraint, timeslice, description, penalty, rhsTerms
  lhs_terms.parquet constraint, timeslice, obj, obj_type, coef   (non-zero LHS coefficients only; includes the Outage_Constraints sheet with timeslice "Outage")

Usage: python scripts/build_lhs_cache.py [workbook.xlsx]
"""
import sys
from pathlib import Path

import openpyxl
import polars as pl

ROOT = Path(__file__).resolve().parent.parent
xlsx = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "inputs" / "ESOO2026 Constraints Details.xlsx"
out = ROOT / "cache"
out.mkdir(exist_ok=True)

wb = openpyxl.load_workbook(xlsx, read_only=True, data_only=True)
ws = wb["Constraint_equations"]
rows = ws.iter_rows(values_only=True)
names = next(rows)
types = next(rows)
FIRST_LHS = 6  # columns A-F are metadata

# Battery headers are duplicated by name; type row disambiguates (GENERATOR / LINE / BATTERY Generation / BATTERY Load)
lhs_cols = [(i, names[i], types[i]) for i in range(FIRST_LHS, len(names)) if names[i] is not None]

meta, terms = [], []
for n, r in enumerate(rows):
    if r[0] is None:
        continue
    c, ts = r[0], r[1]
    meta.append((c, ts, r[2], r[3], r[4]))
    for i, nm, ty in lhs_cols:
        v = r[i] if i < len(r) else None
        if v in (None, "", 0, "0"):
            continue
        terms.append((c, ts, nm, ty, float(v)))
    if n % 2000 == 0:
        print(n, flush=True)

# Outage_Constraints sheet: constraintId, timeSliceId, description, rhs, penalty, then LHS from column F; row 2 = type
ws2 = wb["Outage_Constraints"]
rows2 = ws2.iter_rows(values_only=True)
names2, types2 = next(rows2), next(rows2)
cols2 = [(i, names2[i], types2[i]) for i in range(5, len(names2)) if names2[i] is not None]
for r in rows2:
    if r[0] is None:
        continue
    meta.append((r[0], "Outage", r[2], r[4], r[3]))
    for i, nm, ty in cols2:
        v = r[i] if i < len(r) else None
        if v in (None, "", 0, "0"):
            continue
        terms.append((r[0], "Outage", nm, ty, float(v)))

pl.DataFrame(meta, schema=["constraint", "timeslice", "description", "penalty", "rhsTerms"], orient="row").write_parquet(out / "eq_meta.parquet")
pl.DataFrame(terms, schema=["constraint", "timeslice", "obj", "obj_type", "coef"], orient="row").write_parquet(out / "lhs_terms.parquet")
print("done", len(meta), len(terms))
