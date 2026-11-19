"""Append the final RHS adder to each ESOO equation's rhsTerms text, so the adders can be pasted back in bulk.

For every row of outputs/FINAL/esoo_equation_edits.csv (constraint x timeslice) it adds ONE new top-level constant term
    <next term id>, 0, C, RHS_Adder_MMS_Proxy, <adder MW>, , ,
to that equation's rhsTerms. Top-level terms are summed, so this adds the adder (MW) to the RHS without touching any
existing term (existing constants such as `Constant`, `Operating_Margin` and the ROCOF `ADD_24MW_ON_IC` use the same form).
Re-running replaces any earlier RHS_Adder_MMS_Proxy line, so it is safe to repeat.

Input (default): cache/eq_meta.parquet, i.e. the published ESOO workbook. To start from your own copy-out instead, pass a
CSV with columns constraint, timeslice, rhsTerms:  apply_adders_to_rhs.py my_rhs_export.csv
Output: outputs/FINAL/rhs_terms_with_adders.csv   constraint, timeslice, adder_mw, rhsTerms (new text), status
        outputs/FINAL/rhs_adder_lines.csv         constraint, timeslice, adder_mw, line_to_append (for equations pasted by hand)
status: ok, or TRUNCATED (the source cell was cut at Excel's 32,767-character limit, so append the line to the full text from the model).
Run: .venv\\Scripts\\python.exe -X utf8 -I scripts\\apply_adders_to_rhs.py [export.csv]"""
import sys
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parents[1]
FINAL = ROOT / "outputs" / "FINAL"
NAME = "RHS_Adder_MMS_Proxy"
EXCEL_LIMIT = 32767

src = pl.read_csv(sys.argv[1], infer_schema_length=0) if len(sys.argv) > 1 else pl.read_parquet(ROOT / "cache" / "eq_meta.parquet")
text = {(r["constraint"], r["timeslice"]): (r["rhsTerms"] or "") for r in src.select("constraint", "timeslice", "rhsTerms").iter_rows(named=True)}
edits = pl.read_csv(FINAL / "esoo_equation_edits.csv", infer_schema_length=None)

out, lines = [], []
for r in edits.iter_rows(named=True):
    key = (r["constraint"], r["timeslice"])
    if key not in text:
        out.append({"constraint": key[0], "timeslice": key[1], "adder_mw": r["add_to_rhs_constant_mw"], "rhsTerms": "", "status": "NOT FOUND in source"})
        continue
    kept = [l for l in text[key].split("\n") if l.strip() and f", {NAME}," not in l]
    ids = []
    for l in kept:
        head = l.split(",", 1)[0].strip()
        if head.isdigit():
            ids.append(int(head))
    truncated = len(text[key]) >= EXCEL_LIMIT - 1
    new_id = (max(ids) + 1) if ids else 1
    adder = float(r["add_to_rhs_constant_mw"])
    line = f"{new_id}, 0, C, {NAME}, {adder:g}, , ,"
    out.append({"constraint": key[0], "timeslice": key[1], "adder_mw": adder, "rhsTerms": "\n".join(kept + [line]),
                "status": "TRUNCATED" if truncated else "ok"})
    lines.append({"constraint": key[0], "timeslice": key[1], "adder_mw": adder, "line_to_append": line})
res = pl.DataFrame(out, infer_schema_length=None)
res.write_csv(FINAL / "rhs_terms_with_adders.csv")
pl.DataFrame(lines, infer_schema_length=None).write_csv(FINAL / "rhs_adder_lines.csv")
print(res.group_by("status").len())
print(res.filter(pl.col("status") == "TRUNCATED").select("constraint").unique().to_series().to_list())
