"""Build outputs/FINAL/: final_rhs_adders.csv (every candidate and matched constraint: adder or the reason for none),
esoo_equation_edits.csv (per ESOO timeslice: amount to add to the RHS constant) and a copy of the equation check summary.
Inputs: outputs/rhs_offsets/rhs_offsets_to_apply.csv, inputs/adder_review.csv, outputs/final_constraint_list.csv,
outputs/equation_check/equation_check_summary.csv, outputs/mms_comparison/matched_constraints.csv, cache/eq_meta.parquet.
Run: .venv\\Scripts\\python.exe -X utf8 -I scripts\\build_final_package.py
Sign convention: adder = MMS - ESOO, added to the ESOO RHS (scaled MMS where the ESOO equation is a scaled copy)."""
import re
import shutil
from datetime import date, timedelta
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parents[1]
FINAL = ROOT / "outputs" / "FINAL"
FINAL.mkdir(parents=True, exist_ok=True)
GRP_START = {0: date(2026, 7, 1), 1: date(2027, 2, 1), 2: date(2027, 12, 1), 3: date(2028, 6, 1), 4: date(2029, 5, 1),
             5: date(2030, 3, 1), 6: date(2030, 11, 1), 7: date(2031, 7, 1), 8: date(2031, 12, 1), 9: date(2032, 4, 1),
             10: date(2033, 7, 1), 11: date(2035, 1, 1)}
FAR = date(2099, 12, 31)
EXCLUDED_NOTE = {
    "V>>NIL_SMTX2_SMTX1_R": "not modelled (Blake): MMS series is a configuration variant swamped at ~15,000 MW; equation check supports exclusion",
    "N>>NIL_LINC1_LITO1": "not modelled (Blake): disabled; MMS series is the 'Kurri-Rothbury-Singleton open' variant, swamped ~60% of the time; equation check supports exclusion",
    "N>>N_NIL_DPTX3_DPTX4": "not modelled (Blake): disabled; equation check shows the equation is sound but ESOO LHS includes plants absent from MMS",
}
SIPS_NOTE = "applied out-of-model: set the RHS time series to 10,000 MW in Nov-Mar until 2032-03-31 (not entered in the ESOO equation)"

rev = {r["esoo_constraint"]: r for r in pl.read_csv(ROOT / "inputs" / "adder_review.csv", infer_schema_length=0).fill_null("").iter_rows(named=True)}
eqc = {r["esoo_constraint"]: r for r in pl.read_csv(ROOT / "outputs" / "equation_check" / "equation_check_summary.csv", infer_schema_length=None).iter_rows(named=True)}
final = pl.read_csv(ROOT / "outputs" / "final_constraint_list.csv", infer_schema_length=None)
matched = pl.read_csv(ROOT / "outputs" / "mms_comparison" / "matched_constraints.csv")
mms_of = {r["esoo_constraint"]: (r["mms_constraint"], r["status"]) for r in matched.iter_rows(named=True)}
apply = pl.read_csv(ROOT / "outputs" / "rhs_offsets" / "rhs_offsets_to_apply.csv", infer_schema_length=None)
meta = pl.read_parquet(ROOT / "cache" / "eq_meta.parquet")
wrl = {l.strip() for l in (ROOT / "outputs" / "wrl_affected_constraints.txt").read_text().splitlines() if l.strip()}
ts_of = {(c[0] if isinstance(c, tuple) else c): set(g["timeslice"].to_list()) for c, g in meta.group_by("constraint")}

universe = list(dict.fromkeys(final["constraint"].to_list() + list(mms_of)))
cand = set(final["constraint"].to_list())
rows = []
for c in universe:
    mms, mstat = mms_of.get(c, ("", "no MMS match"))
    r = rev.get(c, {})
    e = eqc.get(c, {})
    base = {"constraint": c, "on_candidate_list": c in cand, "mms_constraint": mms if mstat == "matched" else "",
            "equation_class": e.get("equation_class", ""), "blake_decision": r.get("decision", ""),
            "override_mw": r.get("override_mw", ""), "wrl_affected": c in wrl}
    a = apply.filter(pl.col("esoo_constraint") == c)
    if a.height:
        for x in a.iter_rows(named=True):
            note = SIPS_NOTE if x["action"] == "set_rhs" else (
                "Blake override" if r.get("decision") == "override" else "")
            rows.append({**base, "season": x["season"], "months": x["months"], "scenario": x["scenario"], "action": x["action"],
                         "adder_mw": x["adder_mw"], "rhs_value_mw": x["rhs_value_mw"], "apply_from": x["apply_from"],
                         "apply_to": x["apply_to"], "basis": f"{r.get('fit_basis', '')} fit; {r.get('reason', '')}"[:300],
                         "note": note})
        continue
    if c in EXCLUDED_NOTE:
        why, act = EXCLUDED_NOTE[c], "not_modelled"
    elif mstat != "matched":
        why, act = "no MMS match: ESOO RHS used as is", "none"
    elif r.get("decision") == "reject":
        why, act = "equation kept in the model with the ESOO RHS as is; RHS adder rejected by Blake (" + (e.get("note", "") or "")[:160] + ")", "none"
    else:
        why, act = "no adder: " + (r.get("reason", "") or "")[:200], "none"
    rows.append({**base, "season": "", "months": "", "scenario": "", "action": act, "adder_mw": None, "rhs_value_mw": None,
                 "apply_from": "", "apply_to": "", "basis": "", "note": why})
out = pl.DataFrame(rows, infer_schema_length=None)
out.write_csv(FINAL / "final_rhs_adders.csv")


# ---------- ESOO equation edits: add adder_mw to the RHS constant of each timeslice ----------
def d(s):
    return FAR if s == "end_of_run" else date.fromisoformat(s)


# A seasonal adder on an equation that has no Summer/NotSummer timeslices cannot be entered as two values: enter the
# NotSummer (lower, conservative) value year-round and apply the Summer excess to Dec-Feb out-of-model.
post = []
adds = apply.filter((pl.col("action") == "add_adder") & (pl.col("adder_mw") != 0))
for c in adds["esoo_constraint"].unique().to_list():
    sub = adds.filter(pl.col("esoo_constraint") == c)
    if set(sub["season"].to_list()) == {"Summer", "NotSummer"} and not any(t.startswith(("Summer_", "NotSummer_")) for t in ts_of.get(c, set())):
        summ = sub.filter(pl.col("season") == "Summer").row(0, named=True)
        non = sub.filter(pl.col("season") == "NotSummer").row(0, named=True)
        post.append({"constraint": c, "months": "12,1,2", "extra_adder_mw": summ["adder_mw"] - non["adder_mw"], "apply_from": summ["apply_from"],
                     "apply_to": summ["apply_to"], "note": f"ESOO equation has no seasonal timeslices: Summer adder {summ['adder_mw']:+.0f} vs NotSummer {non['adder_mw']:+.0f}. "
                     f"Enter {non['adder_mw']:+.0f} in all timeslices and add the extra to the RHS time series in Dec-Feb"})
        adds = adds.filter(~((pl.col("esoo_constraint") == c) & (pl.col("season") == "Summer")))
        adds = adds.with_columns(pl.when(pl.col("esoo_constraint") == c).then(pl.lit("All")).otherwise(pl.col("season")).alias("season"))
pl.DataFrame(post, infer_schema_length=None).write_csv(FINAL / "out_of_model_seasonal_adjustments.csv") if post else None

edits = []
for x in adds.iter_rows(named=True):
    c, lo, hi = x["esoo_constraint"], d(x["apply_from"]), d(x["apply_to"])
    have = ts_of.get(c, set())
    for g in range(12):
        gs = GRP_START[g]
        ge = GRP_START[g + 1] - timedelta(days=1) if g < 11 else FAR
        if hi < gs or lo > ge:
            continue
        names = [t for t in (f"Grp{g}", f"Summer_Grp{g}", f"NotSummer_Grp{g}") if t in have]
        if x["season"] == "Summer":
            names = [t for t in names if t.startswith("Summer_") or t == f"Grp{g}"]
        elif x["season"] == "NotSummer":
            names = [t for t in names if t.startswith("NotSummer_") or t == f"Grp{g}"]
        note = ""
        if c in wrl:
            note = "WRL-affected: in the frozen (no-WRL) version Grp5 is held from Nov 2030, so the Grp5 entry carries through"
        if c == "V>>V_NIL_DDSM1_DDSM2":
            note = "Apr-Oct adder entered in all months of the flat equation; Nov-Mar RHS is replaced by 10,000 MW out-of-model until 2032-03-31"
        if x["season"] == "All" and any(t.startswith("Summer_") for t in names) and f"Summer_Grp{g}" not in have and f"NotSummer_Grp{g}" in have:
            note = (note + "; " if note else "") + "no Summer timeslice at this Grp (NotSummer equation applies in all months)"
        if not names:
            note = (note + "; " if note else "") + "NO MATCHING TIMESLICE FOUND - check"
        for t in names or [f"Grp{g}"]:
            edits.append({"constraint": c, "timeslice": t, "add_to_rhs_constant_mw": x["adder_mw"], "scenario": x["scenario"],
                          "from": max(lo, gs).isoformat(), "to": "end_of_run" if min(hi, ge) == FAR else min(hi, ge).isoformat(), "note": note})
ed = pl.DataFrame(edits, infer_schema_length=None)
ed = (ed.group_by("constraint", "timeslice", "add_to_rhs_constant_mw", "from", "to", "note")
        .agg(pl.col("scenario").unique().sort().alias("sc"))
        .with_columns(pl.when(pl.col("sc").list.len() > 1).then(pl.lit("both")).otherwise(pl.col("sc").list.first()).alias("scenario"))
        .drop("sc").select("constraint", "timeslice", "add_to_rhs_constant_mw", "scenario", "from", "to", "note")
        .sort("constraint", "timeslice", "from"))
ed.write_csv(FINAL / "esoo_equation_edits.csv")
shutil.copy(ROOT / "outputs" / "equation_check" / "equation_check_summary.csv", FINAL / "equation_check_summary.csv")
print("final_rhs_adders rows", out.height, "| edits", ed.height, "| constraints with edits", ed["constraint"].n_unique())
print(out.group_by("action").len().sort("len", descending=True))
print(ed.filter(pl.col("note").str.contains("NO MATCHING")).height, "edit rows without a matching timeslice")
