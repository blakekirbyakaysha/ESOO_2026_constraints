"""Fit flat RHS adders (MMS - ESOO) per constraint. See PLAN_RHS_OFFSETS.md.

Run: .venv\\Scripts\\python.exe -X utf8 -I scripts\\rhs_offsets.py
"""
import math
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import median

import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import polars as pl

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from compare_to_MMS import profile_key, safe_name  # noqa: E402

OUT = ROOT / "outputs" / "mms_comparison"   # inputs from compare_to_MMS.py
RES = ROOT / "outputs" / "rhs_offsets"       # everything this script writes
PLOTS = RES / "plots"
PLOTS_LONG = RES / "plots_longrun"

# ---- thresholds ----
MIN_CELL_N = 10            # values per (month, slot) cell, each source
MIN_SLOTS_PER_MONTH = 40
MIN_MONTHS = 9
ROUND_MW = 5
MATERIAL_MW = 20.0
MATERIAL_PCT = 0.03
SIGN_MONTHS_OF_12 = 8      # scaled proportionally when fewer months (2/3 of months)
SIGN_NEUTRAL_MW = 10.0     # months whose gap is within this of zero do not count against the sign test
LOO_MONTH_FRAC = 0.75
LOO_MAE_DROP = 0.20
SEASONAL_GAIN = 0.15       # seasonal LOO MAE must be this much below flat
SURROGATE_PCT = 0.25
IQR_RATIO_MAX = 0.5
DIURNAL_MIN_MW = 50.0
SENTINEL = 1e20
SUMMER = {12, 1, 2}
# MMS data cleaning (from manual review): intervals where the MMS RHS is swamped are not comparable to ESOO.
# MMS RHS above the cap is treated as swamped and dropped before fitting. DDSM/MRDD sit at ~2,400 / ~1,950 MW but jump
# to 8,000-12,000 MW in daytime slots while SIPS is active.
SWAMP_CAP: dict[str, float] = {"V>>V_NIL_DDSM1_DDSM2": 5000.0, "V>>V_NIL_MRDD1_MRDB2": 5000.0}
# Excluded by the user (2026-10-28): no adder is fitted and the constraint is reported as excluded.
EXCLUDED = {
    "V>>NIL_SMTX2_SMTX1_R": "EXCLUDED (user): MMS RHS jumps to ~15,000 MW frequently, so it binds falsely in ESOO; ignore the constraint",
    "N>>NIL_LINC1_LITO1": "EXCLUDED (user): disabled in the model",
    "N>>N_NIL_DPTX3_DPTX4": "EXCLUDED (user): disabled in the model (LHS equation does not match MMS)",
}
# RHS swamped while SIPS is active (1 Nov-31 Mar): one adder for the SIPS months, one for the rest of the year.
SIPS_CONSTRAINTS = {"V>>V_NIL_DDSM1_DDSM2", "V>>V_NIL_MRDD1_MRDB2"}
SIPS_MONTHS = {11, 12, 1, 2, 3}
SIPS_END_GRP = 9           # assumption: SIPS runs to the end of the 2031-32 summer (user: "until 2032"); Grp9 starts 2032-04-01
SIPS_RHS_MW = 10000.0      # neither constraint binds in MMS during SIPS and barely in ESOO: switch it off in SIPS months
SIPS_EVIDENCE: dict[str, str] = {}   # filled in main(): binding evidence quoted in the reason
SIPS_MIN_MONTHS = 3        # months per SIPS segment (the Jul-Jan fit window leaves 3 SIPS and 4 non-SIPS months)
TAIL_Q = 0.10              # low-end fit uses the P10 of each (month, slot) cell, where the constraint is most likely to bind
LHS_FLAG_PCT = 15.0         # |ESOO - MMS LHS| on the Jul-Sep overlap, as % of the MMS RHS
DYNAMIC: set[str] = set()  # ROCOF constraints used to be excluded; the market model fixes RHS to ESOO outcomes, so they are fitted like the rest
GRP_START = {0: date(2026, 7, 1), 1: date(2027, 2, 1), 2: date(2027, 12, 1), 3: date(2028, 6, 1),
             4: date(2029, 5, 1), 5: date(2030, 3, 1), 6: date(2030, 11, 1), 7: date(2031, 7, 1),
             8: date(2031, 12, 1), 9: date(2032, 4, 1), 10: date(2033, 7, 1), 11: date(2035, 1, 1)}
RUN_START = date(2026, 7, 1)
MONTH_ORDER = [7, 8, 9, 10, 11, 12, 1, 2, 3, 4, 5, 6]


def load_scale() -> dict[str, float]:
    """ESOO/MMS coefficient ratio per constraint (scripts/equation_check/classify_equations.py), kept only where the ESOO
    equation is a scaled copy of MMS (outside 1 +/- SCALE_TOL). The MMS RHS and headroom are multiplied by it before
    fitting, so the adder is k x MMS - ESOO instead of a gap that mostly reflects the scale."""
    f = ROOT / "outputs" / "equation_check" / "equation_check_summary.csv"
    if not f.exists():
        return {}
    d = pl.read_csv(f, infer_schema_length=None).filter(pl.col("coef_ratio_med").is_not_null())
    return {r["esoo_constraint"]: float(r["coef_ratio_med"]) for r in d.iter_rows(named=True)
            if abs(float(r["coef_ratio_med"]) - 1.0) > SCALE_TOL}


SCALE_TOL = 0.05
SCALE: dict[str, float] = {}
EQ_INFO: dict[str, tuple] = {}


def r5(x: float) -> float:
    return float(round(x / ROUND_MW) * ROUND_MW)


def need_same_sign(n: int) -> int:
    return min(n, math.ceil(SIGN_MONTHS_OF_12 * n / 12))


def quantile(vals: list[float], q: float) -> float:
    s = sorted(vals)
    pos = q * (len(s) - 1)
    lo, hi = math.floor(pos), math.ceil(pos)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


# ---------------- data ----------------
def load_pair(name: str):
    path = OUT / f"{safe_name(name)}_30min.csv"
    df = pl.read_csv(path, infer_schema_length=None, try_parse_dates=False)
    df = df.with_columns(
        pl.col("datetime").str.to_datetime(strict=False),
        pl.col("actual_rhs").cast(pl.Float64, strict=False),
        pl.col("esoo_rhs").cast(pl.Float64, strict=False),
        pl.col("actual_lhs").cast(pl.Float64, strict=False),
        pl.col("esoo_lhs").cast(pl.Float64, strict=False),
    )
    mms, esoo, mms_h, esoo_h = {}, {}, {}, {}   # *_h = headroom (RHS - LHS)
    cap = SWAMP_CAP.get(name, SENTINEL)
    k = SCALE.get(name, 1.0)
    ok = lambda v: v is not None and math.isfinite(v) and abs(v) < SENTINEL  # noqa: E731
    for ts, a, e, al, el in zip(df["datetime"], df["actual_rhs"], df["esoo_rhs"], df["actual_lhs"], df["esoo_lhs"]):
        _, month, _, slot = profile_key(ts)
        if ok(a) and ok(al) and a <= cap:
            mms_h.setdefault((month, slot), []).append(k * (a - al))
        if ok(e) and ok(el):
            esoo_h.setdefault((month, slot), []).append(e - el)
        if a is not None and math.isfinite(a) and abs(a) < SENTINEL and a <= cap:
            mms.setdefault((month, slot), []).append(k * a)
        if e is not None and math.isfinite(e) and abs(e) < SENTINEL:
            esoo.setdefault((month, slot), []).append(e)
    both = df.filter(
        pl.col("actual_rhs").is_not_null() & pl.col("esoo_rhs").is_not_null()
        & (pl.col("actual_rhs").abs() < SENTINEL) & (pl.col("esoo_rhs").abs() < SENTINEL)
    )
    overlap = float((SCALE.get(name, 1.0) * both["actual_rhs"] - both["esoo_rhs"]).mean()) if both.height else None
    bind = df["actual_binding"].cast(pl.Boolean, strict=False).mean() if "actual_binding" in df.columns else None
    return mms, esoo, overlap, (bind * 100 if bind is not None else None), mms_h, esoo_h


def util_matched_adders(name: str, qs=(0.95, 0.99)) -> dict:
    """RHS adder (MW) that makes the upper tail of ESOO utilisation (LHS/RHS) match MMS, per quantile. Uses LHS and RHS
    together, so an ESOO LHS that is higher than MMS is credited against a higher RHS instead of being ignored. {q: MW}
    (None if there are too few positive-RHS intervals)."""
    df = pl.read_csv(OUT / f"{safe_name(name)}_30min.csv", infer_schema_length=None).with_columns(
        *[pl.col(c).cast(pl.Float64, strict=False) for c in ("actual_lhs", "esoo_lhs", "actual_rhs", "esoo_rhs")])
    ok = lambda c: (pl.col(c).is_not_null()) & (pl.col(c).abs() < SENTINEL)  # noqa: E731
    cap = SWAMP_CAP.get(name, SENTINEL)
    m = df.filter(ok("actual_lhs") & ok("actual_rhs") & (pl.col("actual_rhs") > 0) & (pl.col("actual_rhs") <= cap))
    e = df.filter(ok("esoo_lhs") & ok("esoo_rhs") & (pl.col("esoo_rhs") > 0))
    if m.height < 1000 or e.height < 1000:
        return {q: None for q in qs}
    um = (m["actual_lhs"] / m["actual_rhs"]).to_numpy()
    el, er = e["esoo_lhs"].to_numpy(), e["esoo_rhs"].to_numpy()
    out = {}
    for q in qs:
        target = float(np.quantile(um, q))
        lo, hi = -0.9 * float(er.min()), 3.0 * float(np.median(er))
        for _ in range(50):          # utilisation falls as the adder rises, so bisect
            mid = (lo + hi) / 2
            if float(np.quantile(el / (er + mid), q)) > target:
                lo = mid
            else:
                hi = mid
        out[q] = r5((lo + hi) / 2)
    return out


def build_cells(mms, esoo, esoo_months=None, stat=median):
    """cells[month] = {slot: (mms_med, esoo_med, diff)}; only usable months."""
    cells = {}
    for (m, s), mv in mms.items():
        ev = esoo.get((m, s))
        if ev is None or len(mv) < MIN_CELL_N or len(ev) < MIN_CELL_N:
            continue
        if esoo_months is not None and m not in esoo_months:
            continue
        mm, em = stat(mv), stat(ev)
        cells.setdefault(m, {})[s] = (mm, em, mm - em)
    return {m: c for m, c in cells.items() if len(c) >= MIN_SLOTS_PER_MONTH}


def month_med(cells, m):
    return median(d for _, _, d in cells[m].values())


def fit_flat(cells, months):
    ms = [month_med(cells, m) for m in months]
    return r5(median(ms)) if ms else 0.0


def fit_seasonal(cells, months):
    s = [m for m in months if m in SUMMER]
    n = [m for m in months if m not in SUMMER]
    return fit_flat(cells, s), fit_flat(cells, n)


def mae_cells(cells, m, a):
    return sum(abs(d - a) for _, _, d in cells[m].values()), len(cells[m])


def loo(cells):
    months = sorted(cells)
    res = {"none": 0.0, "flat": 0.0, "seas": 0.0, "n": 0, "improved_flat": 0, "improved_seas": 0}
    for m in months:
        rest = [x for x in months if x != m]
        af = fit_flat(cells, rest)
        asu, ans = fit_seasonal(cells, rest)
        aseas = asu if m in SUMMER else ans
        e0, n = mae_cells(cells, m, 0.0)
        ef, _ = mae_cells(cells, m, af)
        es, _ = mae_cells(cells, m, aseas)
        res["none"] += e0
        res["flat"] += ef
        res["seas"] += es
        res["n"] += n
        res["improved_flat"] += ef < e0
        res["improved_seas"] += es < e0
    for k in ("none", "flat", "seas"):
        res[k] /= max(res["n"], 1)
    return res


# ---------------- RHS change dates ----------------
SEASONS = ("Summer", "NotSummer")
STEP_FRAC = 0.25           # ESOO RHS level step must exceed this share of the adder (or the 20 MW floor) to end it
STEP_DAYS = 30


def candidates(changes: pl.DataFrame, name: str, freeze: bool):
    """{season: [(grp, desc), ...]} structural RHS changes (rhs_any), ascending. freeze = no-WRL freeze at Grp6+."""
    sub = changes.filter((pl.col("constraint") == name) & pl.col("rhs_any"))
    out = {}
    for season in SEASONS:
        rows = sub.filter(pl.col("season").is_in([season, "All"]))
        if freeze:
            rows = rows.filter(pl.col("to_grp") < 6)
        lst = []
        for g in sorted(set(rows["to_grp"].to_list())):
            r = rows.filter(pl.col("to_grp") == g)
            lst.append((int(g), f"Grp{g}: {int(r['rhs_add_n'].sum())} RHS terms added, {int(r['rhs_rem_n'].sum())} "
                                f"removed, {int(r['rhs_chg_n'].sum())} coefficient-changed"))
        out[season] = lst
    return out


def end_dict(cand, steps=None, adders=None):
    """{season: (grp|None, desc)}. steps None = structural rule (first rhs_any change ends the adder).
    Otherwise the first rhs_any change whose ESOO RHS level step (MW) is negative and exceeds max(20, STEP_FRAC*|adder|)
    ends it (a positive step, an uprating, never does: the adder stays on top of it); a Grp with no ESOO RHS data around it counts as exceeding."""
    out = {}
    for s in SEASONS:
        out[s] = (None, "")
        thr = None if steps is None else max(MATERIAL_MW, STEP_FRAC * abs(adders[s]))
        ignored = []
        for g, desc in cand[s]:
            if steps is None:
                out[s] = (g, desc)
                break
            st = steps.get(g)
            if st is not None and st > thr:     # uprating: the adder is a representation gap, so it stays on top of the lift
                ignored.append(f"Grp{g} ({st:+.0f} MW uprating, adder kept)")
                continue
            if st is None or abs(st) > thr:
                stxt = "no ESOO RHS data around Grp" if st is None else f"ESOO RHS step {st:+.0f} MW > {thr:.0f} MW"
                out[s] = (g, f"{desc}; {stxt}")
                break
            ignored.append(f"Grp{g} ({st:+.0f} MW)")
        else:
            if ignored:
                out[s] = (None, "RHS changes ignored (small, or uprating with adder kept): " + ", ".join(ignored))
    return out


def load_steps(tag: str, names) -> dict:
    """{constraint: {grp: MW step}}: seasonally adjusted level step at each Grp start. Step = median daily ESOO RHS
    in the STEP_DAYS after the start minus the STEP_DAYS before, minus the same difference one year earlier (else
    later) when that window contains no other Grp start. Daily RHS is a 24-hour sum, so divide by 24.
    None if no clean comparison window or no data."""
    d = pl.read_parquet(ROOT / "outputs" / tag / "daily.parquet").filter(
        pl.col("constraint").is_in(list(names)) & (pl.col("rhs").abs() < SENTINEL))

    def diff(x, s):
        a = x.filter((pl.col("date") >= s - timedelta(STEP_DAYS)) & (pl.col("date") < s))["rhs"]
        b = x.filter((pl.col("date") >= s) & (pl.col("date") < s + timedelta(STEP_DAYS)))["rhs"]
        return (b.median() - a.median()) / 24 if len(a) >= 10 and len(b) >= 10 else None

    def shifted(s, y):
        try:
            return s.replace(year=s.year + y)
        except ValueError:
            return s.replace(year=s.year + y, day=28)

    out = {}
    for n in names:
        x = d.filter(pl.col("constraint") == n)
        out[n] = {}
        for g, s in GRP_START.items():
            if g == 0:
                continue
            raw, adj = diff(x, s), None
            if raw is not None:
                for y in (-1, 1):
                    s2 = shifted(s, y)
                    if all(abs((t2 - s2).days) > 35 for t2 in GRP_START.values()):
                        ref = diff(x, s2)
                        if ref is not None:
                            adj = raw - ref
                            break
            out[n][g] = adj
    return out


def end_str(g):
    return "end_of_run" if g is None else (GRP_START[g] - timedelta(days=1)).isoformat()


# ---------------- main ----------------
SEG_MIN_MONTHS = 5         # minimum months for a short (segment or data-limited) fit
SPREAD_FRAC = 1.0          # P10-P90 spread of monthly gaps may not exceed the adder itself (else a flat value is not representative)
PRE_MONTHS = {7, 8, 9, 10, 11, 12, 1}
POST_MONTHS = {2, 3, 4, 5, 6}


def ends_txt(ch):
    s, n = end_str(ch["Summer"][0]), end_str(ch["NotSummer"][0])
    return s if s == n else f"Summer={s}; NotSummer={n}"


def fit_one(row, rec, mms, esoo, cells, cand_w, cand_n, st_w, st_n, seg, apply_from, cap=None, short_ok=False,
            min_months=None):
    """Fit and test one segment. cap = (grp, text) forces the adder to end at that Grp start."""
    rec = dict(rec, segment=seg, apply_from=apply_from.isoformat())

    def finish(rec):
        if rec["form"] == "seasonal":
            ad = {"Summer": rec["fitted_summer_mw"], "NotSummer": rec["fitted_notsummer_mw"]}
        else:
            ad = {s: rec["fitted_flat_mw"] for s in SEASONS}
        ch_with, ch_no = end_dict(cand_w, st_w, ad), end_dict(cand_n, st_n, ad)
        if cap:
            def capped(ch):
                out = {}
                for s_ in SEASONS:
                    g_ = ch[s_][0]
                    out[s_] = cap if g_ is None or cap[0] <= g_ else ch[s_]
                return out
            ch_with, ch_no = capped(ch_with), capped(ch_no)
        rec["end_with_wrl"], rec["end_no_wrl"] = ends_txt(ch_with), ends_txt(ch_no)
        rec["rhs_change_desc"] = "; ".join(f"{s}: {d}" for s, (g, d) in ch_with.items() if d)
        rec["_changes"] = (ch_with, ch_no)
        return rec

    months = sorted(cells)
    rec["months_used"] = len(months)
    rec.update(fitted_flat_mw=0.0, fitted_summer_mw=0.0, fitted_notsummer_mw=0.0, form="none",
               adder_flat_mw=0.0, adder_summer_mw=0.0, adder_notsummer_mw=0.0)
    for k in ("median_mms_rhs", "adder_pct_of_rhs", "months_same_sign", "loo_months_improved", "loo_mae_none",
              "loo_mae_flat", "loo_mae_seasonal", "diurnal_range_mw", "iqr_ratio", "gap_spread_mw"):
        rec[k] = None

    if rec["esoo_constraint"] in EXCLUDED:
        rec.update(status="excluded", reason=EXCLUDED[rec["esoo_constraint"]])
        return finish(rec)
    if rec["esoo_constraint"] in DYNAMIC:
        rec.update(status="excluded_dynamic_rhs", reason="RHS depends on decision variables")
        return finish(rec)
    need = min_months or (SEG_MIN_MONTHS if short_ok else MIN_MONTHS)
    if len(months) < need:
        rec.update(status="insufficient_data", reason=f"only {len(months)} usable months (need {need})")
        return finish(rec)
    short = len(months) < MIN_MONTHS

    med_rhs = median(c[0] for m in months for c in cells[m].values())
    rec["median_mms_rhs"] = med_rhs
    thresh = max(MATERIAL_MW, MATERIAL_PCT * abs(med_rhs))
    a = fit_flat(cells, months)
    asu, ans = fit_seasonal(cells, months)
    rec.update(fitted_flat_mw=a, fitted_summer_mw=asu, fitted_notsummer_mw=ans)
    L = loo(cells)
    rec.update(loo_mae_none=L["none"], loo_mae_flat=L["flat"], loo_mae_seasonal=L["seas"],
               loo_months_improved=L["improved_flat"])

    def sign_count(ms, val):
        return sum(1 for m in ms if month_med(cells, m) * val > 0 or abs(month_med(cells, m)) < SIGN_NEUTRAL_MW)

    def loo_pass(imp, mae, nm):
        return imp >= LOO_MONTH_FRAC * nm and mae <= (1 - LOO_MAE_DROP) * L["none"]

    nm = len(months)
    ss = sign_count(months, a)
    rec["months_same_sign"] = ss
    fails = []
    if abs(a) < thresh:
        fails.append(f"flat adder {a:+.0f} MW below materiality {thresh:.0f} MW")
    elif ss < need_same_sign(nm):
        fails.append(f"sign not consistent ({ss}/{nm} months)")
    if not loo_pass(L["improved_flat"], L["flat"], nm):
        fails.append(f"out-of-sample gain too small (improved {L['improved_flat']}/{nm} months, "
                     f"MAE {L['none']:.0f}->{L['flat']:.0f})")
    form, chosen = "none", (0.0, 0.0)
    if not fails:
        form, chosen = "flat", (a, a)
    else:
        flat_reason = fails[0]
        sm = [m for m in months if m in SUMMER]
        nmn = [m for m in months if m not in SUMMER]
        vals = []
        for ms, v in ((sm, asu), (nmn, ans)):
            ok = (ms and abs(v) >= thresh and sign_count(ms, v) >= need_same_sign(len(ms)))
            vals.append(v if ok else 0.0)
        sdiff_ok = abs(asu - ans) >= thresh
        seas_loo = loo_pass(L["improved_seas"], L["seas"], nm)
        seas_vs_flat = L["seas"] <= (1 - SEASONAL_GAIN) * L["flat"]
        if any(vals) and sdiff_ok and seas_loo and seas_vs_flat:
            form, chosen = "seasonal", (vals[0], vals[1])
        else:
            fails = [flat_reason]

    if form == "flat":
        rec.update(form="flat", adder_flat_mw=a, adder_summer_mw=a, adder_notsummer_mw=a)
    elif form == "seasonal":
        rec.update(form="seasonal", adder_summer_mw=chosen[0], adder_notsummer_mw=chosen[1])
    eff = max(abs(chosen[0]), abs(chosen[1])) if form != "none" else abs(a)
    rec["adder_pct_of_rhs"] = eff / abs(med_rhs) * 100 if med_rhs else None

    # diagnostics
    by_slot = {}
    for m in months:
        for s, (_, _, d) in cells[m].items():
            by_slot.setdefault(s, []).append(d)
    sl = [median(v) for v in by_slot.values()]
    rec["diurnal_range_mw"] = max(sl) - min(sl)
    ratios = []
    for m in months:
        vals = [v for (mm, _), vs in mms.items() if mm == m for v in vs]
        md = median(vals)
        if md:
            ratios.append((quantile(vals, .75) - quantile(vals, .25)) / abs(md))
    rec["iqr_ratio"] = median(ratios) if ratios else None
    applied = [chosen[0] if m in SUMMER else chosen[1] for m in months] if form != "none" else [a] * nm
    resid = [month_med(cells, m) - ap for m, ap in zip(months, applied)]
    rec["gap_spread_mw"] = quantile(resid, .9) - quantile(resid, .1)

    flags = []
    if row["match_method"] == "No match" and eff > SURROGATE_PCT * abs(med_rhs):
        flags.append("surrogate mapping with large adder (likely different formulation)")
    if rec["iqr_ratio"] is not None and rec["iqr_ratio"] > IQR_RATIO_MAX:
        flags.append(f"MMS RHS bimodal/wide (IQR/median {rec['iqr_ratio']:.2f})")
    if rec["diurnal_range_mw"] > max(eff, DIURNAL_MIN_MW):
        flags.append(f"diurnal shape disagrees (range {rec['diurnal_range_mw']:.0f} MW)")
    if rec["gap_spread_mw"] > SPREAD_FRAC * eff:
        flags.append(f"gap varies by month (P10-P90 spread {rec['gap_spread_mw']:.0f} MW vs adder {eff:.0f} MW)")
    if rec.get("lhs_bias_pct") is not None and abs(rec["lhs_bias_pct"]) > LHS_FLAG_PCT:
        flags.append(f"ESOO LHS differs from MMS by {rec['lhs_bias_pct']:+.0f}% of RHS (Jul-Sep overlap): an RHS adder may not be the right fix")
    if short:
        flags.append(f"short fit ({nm} months)")

    if form == "none":
        rec.update(status="no_change", reason=fails[0] if fails else "no adder")
    elif flags:
        rec.update(status="review", reason="; ".join(flags))
    elif row["match_method"] == "No match":
        rec.update(status="apply_surrogate", reason="passed all tests; surrogate mapping, no flags")
    else:
        rec.update(status="apply", reason="passed all tests")
    if rec["status"] not in ("apply", "apply_surrogate", "review", "set_rhs"):
        rec.update(adder_flat_mw=0.0, adder_summer_mw=0.0, adder_notsummer_mw=0.0)
    return finish(rec)


def analyse(row, changes, wrl_set, final_set, steps):
    """Return ([record], cells_all, low_cells_all); one fit per constraint (median-based, or P10 if only that passes)."""
    name = row["esoo_constraint"]
    rec = {"esoo_constraint": name, "mms_constraint": row["mms_constraint"], "match_method": row["match_method"],
           "in_final_list": name in final_set}
    mms, esoo, overlap, bind, mms_h, esoo_h = load_pair(name)
    rec["overlap_bias_jul_sep"] = overlap
    rec["mms_binding_pct"] = bind

    cand_w = candidates(changes, name, freeze=False)
    cand_n = candidates(changes, name, freeze=name in wrl_set)
    st_w, st_n = steps["with_wrl"].get(name, {}), steps["no_wrl"].get(name, {})
    struct_w, struct_n = end_dict(cand_w), end_dict(cand_n)
    rec["first_rhs_change_grp_summer"] = struct_w["Summer"][0]
    rec["first_rhs_change_grp_notsummer"] = struct_w["NotSummer"][0]
    rec["end_with_wrl_structural"], rec["end_no_wrl_structural"] = ends_txt(struct_w), ends_txt(struct_n)

    if name in wrl_set:
        # Grp6+ RHS changes on WRL-affected constraints are the WRL effect ESOO models. Both scenarios share the same
        # adder and end date so that the with/no-WRL difference stays ESOO's own (no-WRL can never exceed with-WRL).
        cand_w = cand_n
    cells_all = build_cells(mms, esoo)
    a_all = fit_flat(cells_all, sorted(cells_all)) if cells_all else 0.0
    g1 = any(g == 1 for s in SEASONS for g, _ in cand_w[s])
    step1 = st_w.get(1)
    # Material (seasonally adjusted) RHS step at Grp1: the offset is only measured on the Jul-Jan equation.
    pre_only = g1 and (step1 is None or abs(step1) > max(MATERIAL_MW, STEP_FRAC * abs(a_all)))
    esoo_months = {m for (m, _) in esoo}
    data_limited = bool(esoo_months) and esoo_months <= PRE_MONTHS and not pre_only

    lhs_b, rhs_m = row.get("lhs_bias_esoo_minus_mms"), row.get("rhs_mms_mean_on_overlap")
    rec["lhs_bias_pct"] = lhs_b / abs(rhs_m) * 100 if lhs_b is not None and rhs_m else None

    months = PRE_MONTHS if pre_only else None
    cap = None
    if pre_only and (step1 is None or step1 < 0):   # a positive Grp1 step keeps the adder; otherwise the fit window ends there
        cap = (1, "fit window ends at Grp1 (ESOO RHS step down or no data)")
    elif data_limited:
        cap = (1, "ESOO RHS data end Jan 2027")
    short_ok = pre_only or data_limited
    low = lambda v: quantile(v, TAIL_Q)  # noqa: E731
    args = (row, rec, mms, esoo)
    low_all = build_cells(mms, esoo, None, low)

    if name in SIPS_CONSTRAINTS:
        usable = set(months) if months else set(range(1, 13))
        segs = []
        for label, active, seg_cap in (("SIPS", SIPS_MONTHS, (SIPS_END_GRP, "SIPS retired after the 2031-32 summer (assumed)")),
                                       ("NonSIPS", set(range(1, 13)) - SIPS_MONTHS, None)):
            c = seg_cap if cap is None else (cap if seg_cap is None or cap[0] <= seg_cap[0] else seg_cap)
            cells = build_cells(mms, esoo, active & usable, median)
            r = fit_one(*args, cells, cand_w, cand_n, st_w, st_n, label, RUN_START, cap=c, short_ok=True,
                        min_months=SIPS_MIN_MONTHS)
            if label == "SIPS":
                gtxt = f"SIPS retired after the 2031-32 summer (assumed, Grp{SIPS_END_GRP} start)"
                r["_changes"] = tuple({s_: (SIPS_END_GRP, gtxt) for s_ in SEASONS} for _ in range(2))
                r["end_with_wrl"] = r["end_no_wrl"] = ends_txt(r["_changes"][0])
                r["rhs_change_desc"] = gtxt
                r.update(status="set_rhs", set_rhs_mw=SIPS_RHS_MW, form="none", adder_flat_mw=0.0, adder_summer_mw=0.0,
                         adder_notsummer_mw=0.0, reason=f"set RHS to {SIPS_RHS_MW:,.0f} MW in Nov-Mar (constraint effectively off): "
                         + SIPS_EVIDENCE.get(name, ""))
            r.update(months_active=sorted(active),
                     segment_label="Nov-Mar (SIPS active)" if label == "SIPS" else "Apr-Oct (SIPS off)",
                     fit_basis="median", tail_p10_gap_mw=None, headroom_gap_mw=None, headroom_status=None)
            segs.append(r)
        return segs, cells_all, low_all

    def fit(stat, m_=mms, e_=esoo):
        cells = build_cells(m_, e_, months, stat)
        return fit_one(row, rec, m_, e_, cells, cand_w, cand_n, st_w, st_n, "full", RUN_START, cap=cap, short_ok=short_ok)

    primary, tail = fit(median), fit(low)
    rec_p, rec_t = primary, tail
    rec_p["fit_basis"] = "median"
    rec_p["tail_p10_gap_mw"] = rec_t["fitted_flat_mw"] if rec_t["status"] not in ("insufficient_data", "excluded") else None
    has = ("apply", "apply_surrogate", "review", "set_rhs")
    if rec_p["status"] == "no_change" and rec_t["status"] in has:
        # median gap rejected, but the low end (where the constraint binds) shows a consistent gap
        rec_t["fit_basis"] = "P10"
        rec_t["tail_p10_gap_mw"] = rec_t["fitted_flat_mw"]
        rec_t["status"] = "review"
        rec_t["reason"] = f"low-end (P10) adder; median-based fit gave none ({rec_p['reason']}); " + rec_t["reason"]
        rec_p = rec_t
    elif rec_p["status"] in has and rec_p["tail_p10_gap_mw"] is not None:
        eff = rec_p["adder_flat_mw"] if rec_p["form"] == "flat" else min(rec_p["adder_summer_mw"], rec_p["adder_notsummer_mw"])
        if eff > 0 and eff - rec_p["tail_p10_gap_mw"] > max(MATERIAL_MW, 0.5 * eff):
            rec_p["status"] = "review"
            rec_p["reason"] += f"; optimistic at low end (P10 gap only {rec_p['tail_p10_gap_mw']:+.0f} MW vs adder {eff:+.0f} MW)"
    # Headroom-matched gap: fit MMS - ESOO on (RHS - LHS). It differs from the RHS gap by the LHS bias, so it is the adder
    # that would reproduce MMS headroom if the LHS difference is real rather than a modelling artefact. Information only.
    if name not in EXCLUDED and mms_h and esoo_h:
        rec_h = fit(median, mms_h, esoo_h)
        rec_p["headroom_gap_mw"] = rec_h["fitted_flat_mw"] if rec_h["status"] != "insufficient_data" else None
        rec_p["headroom_status"] = rec_h["status"]
    else:
        rec_p["headroom_gap_mw"], rec_p["headroom_status"] = None, None
    ua = util_matched_adders(name) if name not in EXCLUDED else {0.95: None, 0.99: None}
    rec_p["util_adder_p95_mw"], rec_p["util_adder_p99_mw"] = ua[0.95], ua[0.99]
    return [rec_p], cells_all, low_all


def apply_rows(rec):
    ch_with, ch_no = rec["_changes"]
    if rec.get("set_rhs_mw"):
        return [{"esoo_constraint": rec["esoo_constraint"], "segment": rec["segment"], "status": rec["status"],
                 "season": rec["segment_label"], "months": ",".join(map(str, rec["months_active"])), "scenario": "both",
                 "action": "set_rhs", "adder_mw": None, "rhs_value_mw": rec["set_rhs_mw"], "apply_from": rec["apply_from"],
                 "apply_to": end_str(SIPS_END_GRP), "ends_at_grp": SIPS_END_GRP, "rhs_change_desc": rec["rhs_change_desc"]}]
    summ, nots = rec["adder_summer_mw"], rec["adder_notsummer_mw"]
    if summ == 0 and nots == 0:
        return []
    end = {sc: {s: ch[s][0] for s in SEASONS} for sc, ch in (("with_wrl", ch_with), ("no_wrl", ch_no))}
    split = rec["form"] == "seasonal" or any(end[sc]["Summer"] != end[sc]["NotSummer"] for sc in end)
    seasons = [("Summer", summ), ("NotSummer", nots)] if split else [("All", summ)]
    if rec.get("months_active"):
        seasons = [(rec["segment_label"], summ)]
    out = []
    for season, val in seasons:
        if val == 0:
            continue
        key = "NotSummer" if season == "NotSummer" else "Summer"
        gw, gn = end["with_wrl"][key], end["no_wrl"][key]
        same = gw == gn
        scen = [("both", gw)] if same else [("with_wrl", gw), ("no_wrl", gn)]
        for sc, g in scen:
            ch = ch_with if sc != "no_wrl" else ch_no
            base = {"esoo_constraint": rec["esoo_constraint"], "segment": rec["segment"], "status": rec["status"],
                    "season": season, "scenario": sc, "action": "add_adder", "rhs_value_mw": None,
                    "months": ",".join(map(str, rec["months_active"])) if rec.get("months_active") else "all"}
            out.append({**base, "adder_mw": val, "apply_from": rec["apply_from"], "apply_to": end_str(g),
                        "ends_at_grp": "" if g is None else g, "rhs_change_desc": ch[key][1]})
    return out


def adder_on(d, recs, scen=0):
    """Suggested adder (MW) on date d, over the constraint's segment records (with-WRL end dates)."""
    s = "Summer" if d.month in SUMMER else "NotSummer"
    for rec in recs:
        g = rec["_changes"][scen][s][0]
        if rec.get("months_active") and d.month not in rec["months_active"]:
            continue
        if date.fromisoformat(rec["apply_from"]) <= d and (g is None or d < GRP_START[g]):
            return rec["adder_summer_mw"] if s == "Summer" else rec["adder_notsummer_mw"]
    return 0.0


def segment_label(recs):
    return " / ".join(f"{r['segment']}: {r['status']}" if len(recs) > 1 else r["status"] for r in recs)


def explain(recs, cells=None):
    """Plain-language reasons for the adder (or lack of one), drawn on each constraint chart."""
    import textwrap
    name = recs[0]["esoo_constraint"]
    r0 = recs[0]
    lines = []
    ec = EQ_INFO.get(name)
    if ec:
        lines.append(f"Equation check: {ec[0]} - {ec[1]}.")
    if name in SCALE:
        lines.append(f"ESOO's equation is a scaled copy of MMS (coefficients x{SCALE[name]:.2f}), so the MMS RHS is multiplied by "
                     f"{SCALE[name]:.2f} before comparing: the adder is {SCALE[name]:.2f} x MMS - ESOO, not the raw MW gap.")
    if cells:
        gaps = [month_med(cells, m) for m in cells]
        lines.append(f"Gap{' (scale-adjusted)' if name in SCALE else ''} by month, over all {len(gaps)} months with data: median "
                     f"{median(gaps):+.0f} MW, range {min(gaps):+.0f} to {max(gaps):+.0f} MW, positive in {sum(g > 0 for g in gaps)} of {len(gaps)}.")
    if any(r["adder_summer_mw"] or r["adder_notsummer_mw"] or r.get("set_rhs_mw") for r in recs):
        basis = "the low end (P10 of each month/half-hour)" if r0.get("fit_basis") == "P10" else "the median gap"
        lines.append(f"Adder basis: {basis}, tested for materiality, same sign in 2/3 of months and out-of-sample gain.")
    elif r0["status"] == "insufficient_data" and cells and all(month_med(cells, m) <= 0 for m in cells):
        lines.append(f"No adder: the fit window was too short ({r0['reason']}), but the gap is never positive in any of the "
                     f"{len(cells)} months with data, so there is no positive adder to apply whatever the window.")
    else:
        lines.append(f"No adder because: {r0['reason']}.")
    lb = r0.get("lhs_bias_pct")
    if lb is not None and abs(lb) > LHS_FLAG_PCT:
        lines.append(f"ESOO LHS differs from MMS by {lb:+.0f}% of RHS. The adder only corrects the RHS level: an LHS difference from "
                     "extra plants or different dispatch is treated as a real ESOO result and is not offset by changing the RHS.")
    if r0.get("util_adder_p95_mw") is not None:
        lines.append(f"Cross-check: the adder that matches LHS/RHS utilisation is {r0['util_adder_p95_mw']:+.0f} MW (P95) / "
                     f"{r0['util_adder_p99_mw']:+.0f} MW (P99).")
    return "\n".join(textwrap.fill(ln, 150, subsequent_indent="   ") for ln in lines)


def headline(recs):
    """(text, colour): clear verdict line for plot titles, adder or not."""
    parts, any_add = [], False
    for r in recs:
        pre = f"{r['segment']}: " if len(recs) > 1 else ""
        if r.get("set_rhs_mw"):
            any_add = True
            parts.append(f"{pre}SET RHS TO {r['set_rhs_mw']:,.0f} MW in {r['segment_label']} until {r['end_with_wrl']} [{r['reason']}]")
        elif r["adder_summer_mw"] or r["adder_notsummer_mw"]:
            any_add = True
            v = f"{r['adder_flat_mw']:+.0f}" if r["form"] == "flat" else \
                f"S {r['adder_summer_mw']:+.0f}/NS {r['adder_notsummer_mw']:+.0f}"
            parts.append(f"{pre}ADDER {v} MW (WRL to {r['end_with_wrl']}, no-WRL to {r['end_no_wrl']}) [{r['status']}]")
        else:
            cand = "" if r["status"] in ("insufficient_data", "excluded_dynamic_rhs") else \
                f" (best-fit gap {r['fitted_flat_mw']:+.0f} MW rejected)"
            parts.append(f"{pre}NO ADDER RECOMMENDED{cand} [{r['status']}]: {r['reason']}")
    return "\n".join(parts), ("#c4501b" if any_add else "#2e7d32")


def candidate_on(recs):
    """Rejected best-fit flat gap (MW) when no adder is recommended, else 0."""
    r = recs[0]
    if r["adder_summer_mw"] or r["adder_notsummer_mw"] or r["status"] in ("insufficient_data", "excluded_dynamic_rhs"):
        return 0.0
    return r["fitted_flat_mw"]


def make_constraint_plot(recs, cells, low=None):
    name = recs[0]["esoo_constraint"]
    df = pl.read_csv(OUT / f"{safe_name(name)}_30min.csv", infer_schema_length=None).with_columns(
        pl.col("datetime").str.to_datetime(strict=False),
        pl.col("actual_rhs").cast(pl.Float64, strict=False), pl.col("esoo_rhs").cast(pl.Float64, strict=False))
    df = df.with_columns(
        pl.when(pl.col("actual_rhs").abs() < SENTINEL).then(pl.col("actual_rhs")).alias("actual_rhs"),
        pl.when(pl.col("esoo_rhs").abs() < SENTINEL).then(pl.col("esoo_rhs")).alias("esoo_rhs"))
    day = (df.with_columns((pl.col("datetime") - pl.duration(minutes=1)).dt.date().alias("day"))
           .group_by("day").agg(pl.col("actual_rhs").median().alias("mms"), pl.col("esoo_rhs").median().alias("esoo"))
           .sort("day"))
    days = day["day"].to_list()
    esoo = day["esoo"].to_list()
    esoo_add = [None if e is None else e + adder_on(d, recs) for e, d in zip(esoo, days)]
    c_mms, c_esoo, c_add = "#2a6f97", "#8a8f98", "#c4501b"
    fig, (a1, a2, a3) = plt.subplots(3, 1, figsize=(10, 9.4), gridspec_kw={"height_ratios": [1.3, 1, 0.6]})
    kk = SCALE.get(name, 1.0)
    a1.plot(days, [None if v is None else kk * v for v in day["mms"].to_list()], color=c_mms, lw=1.1,
            label="MMS actual (Oct 2025-Sep 2026)" + (f" x{kk:.2f}" if kk != 1.0 else ""))
    a1.plot(days, esoo, color=c_esoo, lw=1.1, label="ESOO (FY27)")
    cand = candidate_on(recs)
    if any(r["adder_summer_mw"] or r["adder_notsummer_mw"] for r in recs):
        a1.plot(days, esoo_add, color=c_add, lw=1.3, ls="--", label="ESOO + suggested adder")
    elif cand:
        a1.plot(days, [None if e is None else e + cand for e in esoo], color="#999", lw=1.0, ls=":",
                label=f"ESOO + rejected best-fit gap ({cand:+.0f} MW)")
    a1.axvspan(date(2026, 7, 1), date(2026, 9, 30), color="#f2e6d0", alpha=0.6, lw=0, label="same-period overlap")
    a1.set_ylabel("RHS (MW), daily median")
    a1.set_title("Timeline: sources cover different years, overlap is Jul-Sep 2026", fontsize=9, loc="left")
    a1.legend(frameon=False, fontsize=8, loc="best")
    ms = [m for m in MONTH_ORDER if m in cells]
    xs = [MONTH_ORDER.index(m) for m in ms]
    mm = [median(c[0] for c in cells[m].values()) for m in ms]
    em = [median(c[1] for c in cells[m].values()) for m in ms]
    ad = [adder_on(date(2026 if m >= 7 else 2027, m, 15), recs) for m in ms]
    a2.plot(xs, mm, color=c_mms, marker="o", ms=4, lw=1.1, label="MMS median")
    a2.plot(xs, em, color=c_esoo, marker="o", ms=4, lw=1.1, label="ESOO median")
    if any(ad):
        a2.plot(xs, [e + a for e, a in zip(em, ad)], color=c_add, marker="o", ms=4, lw=1.3, ls="--",
                label="ESOO + adder")
    elif cand:
        a2.plot(xs, [e + cand for e in em], color="#999", marker="o", ms=3, lw=1.0, ls=":",
                label=f"ESOO + rejected best-fit gap ({cand:+.0f} MW)")
    if low:
        lx = [MONTH_ORDER.index(m) for m in MONTH_ORDER if m in low]
        a2.plot(lx, [median(c[0] for c in low[m].values()) for m in MONTH_ORDER if m in low], color=c_mms, ls=":", lw=1.0,
                label="MMS P10 (low end)")
        a2.plot(lx, [median(c[1] for c in low[m].values()) + adder_on(date(2026 if m >= 7 else 2027, m, 15), recs)
                     for m in MONTH_ORDER if m in low], color=c_add, ls=":", lw=1.0, label="ESOO P10 + adder (low end)")
    if not xs:
        a2.text(0.5, 0.5, "no usable month-of-year pairs", transform=a2.transAxes, ha="center", color="#777")
    a2.set_xticks(range(12))
    a2.set_xticklabels(["Jul", "Aug", "Sep", "Oct", "Nov", "Dec", "Jan", "Feb", "Mar", "Apr", "May", "Jun"])
    a2.set_ylabel("RHS (MW), monthly median")
    a2.set_title("Same months paired by month of year (the basis for the fit)", fontsize=9, loc="left")
    a2.legend(frameon=False, fontsize=8, loc="best")
    for ax in (a1, a2):
        for sp in ("top", "right"):
            ax.spines[sp].set_visible(False)
        ax.grid(axis="y", color="#e3e3e3", lw=0.6)
    a3.axis("off")
    a3.text(0, 1, "Why this adder (or none):\n" + explain(recs, cells), fontsize=7.8, va="top", ha="left")
    txt, col = headline(recs)
    fig.suptitle(f"{name}  [MMS: {recs[0]['mms_constraint']}]", fontsize=9, y=0.995)
    fig.text(0.5, 0.965, txt, fontsize=8.5, color=col, ha="center", va="top", fontweight="bold", wrap=True)
    fig.tight_layout(rect=(0, 0, 1, 0.92))
    fig.savefig(PLOTS / f"{safe_name(name)}.png", dpi=120)
    plt.close(fig)


def make_longrun_plot(recs, daily, mms_daily, wrl_affected):
    """Full-run daily-average ESOO RHS, with-WRL (top) and no-WRL (bottom), with and without the adder."""
    name = recs[0]["esoo_constraint"]
    c_mms, c_esoo, c_add = "#2a6f97", "#8a8f98", "#c4501b"
    panels = (("with_wrl", 0, "With WRL"), ("no_wrl", 1, "No WRL (WRL-affected constraints frozen at Grp5 from Nov 2030)"))         if wrl_affected else (("with_wrl", 0, "With and without WRL (constraint not WRL-affected, identical)"),)
    fig, axes = plt.subplots(len(panels), 1, figsize=(11, 7.5 if wrl_affected else 4.5), sharex=True, sharey=True,
                             squeeze=False)
    axes = axes.flatten()
    for ax, (tag, scen, title) in zip(axes, panels):
        x = daily[tag].filter(pl.col("constraint") == name).sort("date")
        days = x["date"].to_list()
        esoo = [v / 24 for v in x["rhs"].to_list()]   # daily RHS is the sum of 24 hourly values
        adj = [e + adder_on(d, recs, scen) for e, d in zip(esoo, days)]
        g_end = min((g for g, _ in recs[0]["_changes"][scen].values() if g is not None), default=None)
        if g_end is not None:
            ax.axvspan(GRP_START[g_end], date(2036, 7, 1), color="#eeeeee", alpha=0.7, lw=0,
                       label="offset unvalidated (RHS equation changed)")
        if mms_daily:
            ax.plot(mms_daily[0], mms_daily[1], color=c_mms, lw=0.9, label="MMS actual (daily mean)")
        ax.plot(days, esoo, color=c_esoo, lw=0.8, label="ESOO")
        cand = candidate_on(recs)
        if any(r["adder_summer_mw"] or r["adder_notsummer_mw"] for r in recs):
            ax.plot(days, adj, color=c_add, lw=0.9, ls="--", label="ESOO + suggested adder")
        elif cand:
            ax.plot(days, [e + cand for e in esoo], color="#999", lw=0.8, ls=":",
                    label=f"ESOO + rejected best-fit gap ({cand:+.0f} MW)")
        for g, s in GRP_START.items():
            if g:
                ax.axvline(s, color="#cccccc", lw=0.6, ls=":")
                ax.text(s, 1.0, f"G{g}", transform=ax.get_xaxis_transform(), fontsize=6.5, color="#777", ha="left", va="bottom")
        ax.set_ylabel("RHS (MW), daily mean")
        ax.set_title(title, fontsize=9, loc="left", pad=14)
        ax.grid(axis="y", color="#e3e3e3", lw=0.6)
        for sp in ("top", "right"):
            ax.spines[sp].set_visible(False)
    axes[0].legend(frameon=False, fontsize=8, loc="best")
    txt, col = headline(recs)
    fig.suptitle(f"{name}  [MMS: {recs[0]['mms_constraint']}]", fontsize=9, y=0.995)
    fig.text(0.5, 0.955, txt, fontsize=8.5, color=col, ha="center", va="top", fontweight="bold", wrap=True)
    fig.tight_layout(rect=(0, 0, 1, 0.9))
    fig.savefig(PLOTS_LONG / f"{safe_name(name)}.png", dpi=120)
    plt.close(fig)


def make_chart(groups, cells_by):
    order = {"set_rhs": 0, "apply": 0, "apply_surrogate": 1, "review": 2, "no_change": 3, "excluded_dynamic_rhs": 4,
             "excluded": 4, "insufficient_data": 5}
    groups = sorted(groups, key=lambda g: (min(order[r["status"]] for r in g), g[0]["esoo_constraint"]))
    n = len(groups)
    cols = 6
    rows = math.ceil(n / cols)
    fig, axes = plt.subplots(rows, cols, figsize=(cols * 3.0, rows * 2.4), sharex=True)
    axes = axes.flatten()
    for ax, recs in zip(axes, groups):
        name = recs[0]["esoo_constraint"]
        cells = cells_by[name]
        xs = [i for i, m in enumerate(MONTH_ORDER) if m in cells]
        ys = [month_med(cells, MONTH_ORDER[i]) for i in xs]
        ax.bar(xs, ys, color="#8fa3b8", width=0.7)
        ax.axhline(0, color="#555", lw=0.6)
        for i, m in enumerate(MONTH_ORDER):
            v = adder_on(date(2026 if m >= 7 else 2027, m, 15), recs)
            if v:
                ax.hlines(v, i - .4, i + .4, color="#c4501b", lw=1.8)
        ax.set_title(f"{name}\n[{segment_label(recs)}]", fontsize=6)
        ax.tick_params(labelsize=6)
        ax.set_xticks(range(12))
        ax.set_xticklabels([str(m) for m in MONTH_ORDER])
        for sp in ("top", "right"):
            ax.spines[sp].set_visible(False)
    for ax in axes[n:]:
        ax.axis("off")
    fig.suptitle("Monthly median RHS difference, k x MMS - ESOO (MW; k=1 unless ESOO is a scaled copy); bars = months (Jul..Jun), orange = suggested adder",
                 fontsize=9)
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    fig.savefig(RES / "rhs_offsets_monthly.png", dpi=130)
    plt.close(fig)


# ---------------- manual review file ----------------
REVIEW = ROOT / "inputs" / "adder_review.csv"
REVIEW_USER = ["decision", "override_mw", "comment", "previous_decision", "reviewed_ok", "reviewed_suggestion", "reviewed_reason"]
REVIEW_CTX = ["esoo_constraint", "mms_constraint", "review_status", "what_changed", "suggested_status", "suggested_adder",
              "suggested_end", "fit_basis", "util_matched_adder", "equation_class", "reason"]
DECISIONS = {"accept", "reject", "override"}
NEW_WARNINGS = ("optimistic at low end", "ESOO LHS differs")
S_NOCHANGE, S_WARN, S_RE, S_NEW, S_EXCL = ("NO CHANGE (your decision stands)", "NO CHANGE to adder - NEW WARNING (see reason)",
                                            "RE-REVIEW: suggestion changed", "NEW constraint", "EXCLUDED (per your instruction)")


def suggestion(group):
    """(adder text, end text) for a constraint's segment records."""
    adders, ends = [], []
    for rec in group:
        if rec.get("set_rhs_mw"):
            adders.append(f"{rec['segment_label']}: SET RHS {rec['set_rhs_mw']:g}")
            ends.append(f"{rec['segment_label']}: to {rec['end_with_wrl']}")
        elif rec["adder_summer_mw"] or rec["adder_notsummer_mw"]:
            v = f"{rec['adder_flat_mw']:+.0f}" if rec["form"] == "flat" else \
                f"S {rec['adder_summer_mw']:+.0f} / NS {rec['adder_notsummer_mw']:+.0f}"
            pre = f"{rec['segment_label']}: " if rec.get("segment_label") else ""
            adders.append(pre + v)
            ends.append(pre + f"WRL {rec['end_with_wrl']}; no-WRL {rec['end_no_wrl']}")
    return (" | ".join(adders) or "none"), " | ".join(ends)


def norm_sug(sug, end):
    """Comparable suggestion key; Excel drops the leading '+' from numbers when it saves the file."""
    return f"{str(sug or '').replace('+', '').strip()}|{(end or '').replace('+', '').strip()}"


def load_review() -> dict:
    """{constraint: {...}} from the hand-edited file. Blank decision = not yet reviewed."""
    if not REVIEW.exists():
        return {}
    out = {}
    for r in pl.read_csv(REVIEW, infer_schema_length=0, encoding="utf8-lossy").iter_rows(named=True):
        dec = (r.get("decision") or "").strip().lower()
        ov = (r.get("override_mw") or "").strip()
        val = float(ov) if ov else None
        if val is not None and not dec:
            dec = "override"
        if dec and dec not in DECISIONS:
            print(f"WARNING adder_review.csv: unknown decision '{dec}' for {r['esoo_constraint']} (use accept/reject/override)")
            dec = ""
        if dec == "override" and val is None:
            print(f"WARNING adder_review.csv: {r['esoo_constraint']} is 'override' with no override_mw; ignored")
            dec = ""
        shown = f"{r.get('suggested_adder') or ''}|{r.get('suggested_end') or ''}" if r.get("suggested_adder") else ""
        reviewed = (r.get("reviewed_suggestion") or "").strip() or shown     # older files: what was shown is what was reviewed
        reviewed_reason = (r.get("reviewed_reason") or "").strip() or (r.get("reason") or "")
        status = r.get("review_status") or ""
        pending = status.startswith(("RE-REVIEW", "NEW")) or "NEW WARNING" in status
        ack = (r.get("reviewed_ok") or "").strip().lower() in ("y", "yes") or (status.startswith(("RE-REVIEW", "NEW")) and bool(dec))
        if pending and ack and shown:      # user has looked at the suggestion now shown
            reviewed, reviewed_reason = shown, r.get("reason") or ""
        out[r["esoo_constraint"]] = {"decision": dec, "override_mw": val, "comment": (r.get("comment") or "").strip(),
                                     "previous_decision": (r.get("previous_decision") or "").strip(),
                                     "was": norm_sug(*re.split(r"(?<! )\|(?! )", reviewed, maxsplit=1)) if reviewed else None,   # segment separators are " | "
                                     "was_text": reviewed,
                                     "was_reason": reviewed_reason, "status": "", "what": ""}
    return out


def review_state(name, group, rev):
    """Compare this run's suggestion with what the user saw and set review_status/what_changed. A decision made on a
    suggestion that has since changed is moved to previous_decision (override MW is kept, but flagged)."""
    sug, end = suggestion(group)
    now = norm_sug(sug, end)
    reason = " ; ".join(r["reason"] for r in group)
    if rev is None:
        rev = {"decision": "", "override_mw": None, "comment": "", "previous_decision": "", "was": None, "was_text": "",
               "was_reason": "", "status": "", "what": ""}
    rev.setdefault("now_text", "")
    if name in EXCLUDED:
        if rev["decision"] != "reject":
            rev["decision"] = "reject"
            rev["comment"] = (rev["comment"] + " " if rev["comment"] else "") + EXCLUDED[name]
        rev["status"], rev["what"] = S_EXCL, EXCLUDED[name]
    elif rev["was"] is None:
        rev["status"], rev["what"] = S_NEW, "not in the file you reviewed"
    elif rev["was"] == now:
        new_flags = [w for w in NEW_WARNINGS if w in reason and w not in rev["was_reason"]]
        if new_flags:
            rev["status"], rev["what"] = S_WARN, "new warning: " + ", ".join(new_flags)
        else:
            rev["status"], rev["what"] = S_NOCHANGE, ""
    else:
        why = []
        if any(r.get("fit_basis") == "P10" for r in group):
            why.append("low-end (P10) method")
        if len(group) > 1:
            why.append("SIPS / non-SIPS split")
        if rev["was"].split("|")[0] == now.split("|")[0]:
            why.append("end date changed (uprating no longer ends the adder)")
        rev["status"] = S_RE
        rev["what"] = f"was {rev['was_text'].replace('|', ' to ').strip()} -> now {sug} to {end or 'n/a'}" + (f" [{', '.join(why)}]" if why else "")
        if rev["decision"] in ("accept", "reject"):
            rev["previous_decision"] = rev["decision"]
            rev["decision"] = ""
    if rev["status"] in (S_NOCHANGE, S_EXCL):    # otherwise the reviewed suggestion stays until the user acknowledges
        rev["was"], rev["was_text"], rev["was_reason"] = now, f"{sug}|{end}", reason
    rev["now_text"] = f"{sug}|{end}"
    return rev


def equation_classes():
    """ESOO constraint -> class from scripts/equation_check/classify_equations.py (information only; empty if not run)."""
    f = ROOT / "outputs" / "equation_check" / "equation_check_summary.csv"
    if not f.exists():
        return {}
    d = pl.read_csv(f, infer_schema_length=None)
    return {r["esoo_constraint"]: r["equation_class"] for r in d.iter_rows(named=True)}


def sync_review(groups, review):
    """Rewrite the review file: refresh the suggestion columns and review_status, keep every comment/override as typed."""
    rows = []
    eqc = equation_classes()
    order = lambda g: (g[0]["status"] not in ("apply", "apply_surrogate", "review", "set_rhs"), g[0]["esoo_constraint"])  # noqa: E731
    for g in sorted(groups, key=order):
        name = g[0]["esoo_constraint"]
        o = review[name]
        sug, end = suggestion(g)
        rows.append({"esoo_constraint": name, "mms_constraint": g[0]["mms_constraint"], "review_status": o["status"],
                     "what_changed": o["what"], "suggested_status": "/".join(r["status"] for r in g),
                     "suggested_adder": sug, "suggested_end": end, "fit_basis": g[0].get("fit_basis") or "",
                     "util_matched_adder": "" if g[0].get("util_adder_p95_mw") is None else
                     f"P95 {g[0]['util_adder_p95_mw']:+.0f} / P99 {g[0]['util_adder_p99_mw']:+.0f}",
                     "equation_class": eqc.get(name, ""),
                     "reason": (f"[MMS RHS scaled x{SCALE[name]:.2f} (ESOO equation is a scaled copy)] " if name in SCALE else "")
                     + " ; ".join(r["reason"] for r in g),
                     "decision": o["decision"], "override_mw": "" if o["override_mw"] is None else f"{o['override_mw']:g}",
                     "comment": o["comment"], "previous_decision": o["previous_decision"], "reviewed_ok": "",
                     "reviewed_suggestion": o["was_text"] or o["now_text"],
                     "reviewed_reason": o["was_reason"]})
    try:
        pl.DataFrame(rows).select(REVIEW_CTX + REVIEW_USER).write_csv(REVIEW)
    except OSError as e:
        print(f"WARNING could not update {REVIEW} (open in Excel?): {e}")


def review_rows(rows, rec, rev):
    """Apply a manual decision to this constraint's to-apply rows. reject drops them; override replaces the adder
    override on a no-adder constraint adds one flat row."""
    dec = rev["decision"] if rev else ""
    if dec == "reject":
        return []
    if dec != "override":
        return rows
    ov = rev["override_mw"]
    if not rows:
        return [{"esoo_constraint": rec["esoo_constraint"], "segment": rec["segment"], "status": rec["status"],
                 "season": "All", "scenario": "both", "adder_mw": ov, "apply_from": rec["apply_from"],
                 "apply_to": "end_of_run", "ends_at_grp": "",
                 "rhs_change_desc": "manual override; end date not assessed (no suggested adder)"}]
    return [r if r.get("action") == "set_rhs" else {**r, "adder_mw": ov} for r in rows]


def main():
    SCALE.update(load_scale())
    _f = ROOT / "outputs" / "equation_check" / "equation_check_summary.csv"
    if _f.exists():
        EQ_INFO.update({r["esoo_constraint"]: (r["equation_class"], r["adder_method"])
                        for r in pl.read_csv(_f, infer_schema_length=None).iter_rows(named=True)})
    print("MMS RHS scaled for:", {k: round(v, 2) for k, v in SCALE.items()})
    review = load_review()
    summary = pl.read_csv(OUT / "comparison_summary.csv", infer_schema_length=None)
    changes = pl.read_csv(ROOT / "inputs" / "constraint_changes_by_grp.csv", infer_schema_length=None)
    wrl_set = {l.strip() for l in (ROOT / "outputs" / "wrl_affected_constraints.txt").read_text().splitlines() if l.strip()}
    final_set = set(pl.read_csv(ROOT / "outputs" / "final_constraint_list.csv", infer_schema_length=None)["constraint"])

    names = summary["esoo_constraint"].to_list()
    steps = {tag: load_steps(tag, names) for tag in ("with_wrl", "no_wrl")}
    PLOTS.mkdir(parents=True, exist_ok=True)
    PLOTS_LONG.mkdir(parents=True, exist_ok=True)
    for old in list(PLOTS.glob("*.png")) + list(PLOTS_LONG.glob("*.png")):
        old.unlink()
    daily = {tag: pl.read_parquet(ROOT / "outputs" / tag / "daily.parquet").filter(
        pl.col("constraint").is_in(names) & (pl.col("rhs").abs() < SENTINEL)) for tag in ("with_wrl", "no_wrl")}

    def mms_daily_for(name):
        df = pl.read_csv(OUT / f"{safe_name(name)}_30min.csv", infer_schema_length=None).with_columns(
            pl.col("datetime").str.to_datetime(strict=False), pl.col("actual_rhs").cast(pl.Float64, strict=False))
        df = df.filter(pl.col("actual_rhs").abs() < SENTINEL)
        d = (df.with_columns((pl.col("datetime") - pl.duration(minutes=1)).dt.date().alias("day"))
             .group_by("day").agg(pl.col("actual_rhs").mean()).sort("day"))
        return d["day"].to_list(), d["actual_rhs"].to_list()

    for name in SIPS_CONSTRAINTS:
        df = pl.read_csv(OUT / f"{safe_name(name)}_30min.csv", infer_schema_length=None).with_columns(
            pl.col("datetime").str.to_datetime(strict=False), pl.col("actual_rhs").cast(pl.Float64, strict=False),
            pl.col("actual_binding").cast(pl.Boolean, strict=False)).filter(pl.col("actual_rhs").abs() < SENTINEL)
        sips = df.filter(pl.col("datetime").dt.month().is_in(sorted(SIPS_MONTHS)))
        e = daily["with_wrl"].filter(pl.col("constraint") == name).with_columns(
            pl.col("date").dt.month().alias("m"), pl.col("date").dt.year().alias("y")).with_columns(
            pl.when(pl.col("m") >= 7).then(pl.col("y") + 1).otherwise(pl.col("y")).alias("fyn"))
        es = e.filter(pl.col("m").is_in(sorted(SIPS_MONTHS)) & (pl.col("fyn") <= 2032))
        SIPS_EVIDENCE[name] = (
            f"MMS Nov-Mar: {int(sips['actual_binding'].sum())} binding of {sips.height:,} intervals, RHS >{SWAMP_CAP.get(name, 5000):,.0f} MW in "
            f"{(sips['actual_rhs'] > SWAMP_CAP.get(name, 5000)).mean() * 100:.0f}% of them; ESOO (with WRL, FY27-32): "
            f"{es['hrs_bind'].sum():.0f} binding hours in Nov-Mar ({es['hrs_bind'].sum() / (es.height * 24) * 100:.1f}% of hours), "
            f"${es['rental'].sum():,.0f} rental")

    groups, recs, cells_by, low_by, monthly, to_apply = [], [], {}, {}, [], []
    for row in summary.iter_rows(named=True):
        seg_recs, cells, low_cells = analyse(row, changes, wrl_set, final_set, steps)
        name = row["esoo_constraint"]
        groups.append(seg_recs)
        recs += seg_recs
        cells_by[name] = cells
        low_by[name] = low_cells
        for m in MONTH_ORDER:
            if m in cells:
                c = cells[m].values()
                monthly.append({"esoo_constraint": name, "month": m,
                                "mms_median": median(x[0] for x in c), "esoo_median": median(x[1] for x in c),
                                "diff_median": month_med(cells, m), "n_cells": len(cells[m])})
        rev = review_state(name, seg_recs, review.get(name))
        review[name] = rev
        for rec in seg_recs:
            rec["review_decision"] = rev["decision"]
            rec["review_override_mw"] = rev["override_mw"]
            rec["review_comment"] = rev["comment"]
            base = apply_rows(rec) if rec["status"] in ("apply", "apply_surrogate", "review", "set_rhs") else []
            to_apply += review_rows(base, rec, rev)

    cols = ["esoo_constraint", "segment", "mms_constraint", "match_method", "in_final_list", "status", "reason",
            "adder_flat_mw", "adder_summer_mw", "adder_notsummer_mw", "form",
            "fitted_flat_mw", "fitted_summer_mw", "fitted_notsummer_mw", "median_mms_rhs", "adder_pct_of_rhs",
            "months_used", "months_same_sign", "loo_months_improved", "loo_mae_none", "loo_mae_flat",
            "loo_mae_seasonal", "diurnal_range_mw", "iqr_ratio", "gap_spread_mw", "overlap_bias_jul_sep",
            "mms_binding_pct", "apply_from", "first_rhs_change_grp_summer", "first_rhs_change_grp_notsummer",
            "end_with_wrl", "end_no_wrl", "end_with_wrl_structural", "end_no_wrl_structural", "rhs_change_desc",
            "fit_basis", "tail_p10_gap_mw", "headroom_gap_mw", "headroom_status", "util_adder_p95_mw", "util_adder_p99_mw", "lhs_bias_pct", "review_decision", "review_override_mw", "review_comment"]
    schema = {"first_rhs_change_grp_summer": pl.Int64, "first_rhs_change_grp_notsummer": pl.Int64,
              "review_override_mw": pl.Float64}
    sync_review(groups, review)
    print("\nReview status:", {st: sum(1 for g in groups if review[g[0]["esoo_constraint"]]["status"] == st)
                                for st in (S_NOCHANGE, S_WARN, S_RE, S_NEW, S_EXCL)})
    pl.DataFrame([{c: r.get(c) for c in cols} for r in recs], schema_overrides=schema,
                 infer_schema_length=None).sort("status", "esoo_constraint", "segment").write_csv(RES / "rhs_offsets.csv")
    pl.DataFrame(monthly).write_csv(RES / "rhs_offsets_monthly.csv")
    ta_cols = ["esoo_constraint", "segment", "status", "season", "months", "scenario", "action", "adder_mw", "rhs_value_mw",
               "apply_from", "apply_to",
               "ends_at_grp", "rhs_change_desc"]
    num = {"adder_mw": pl.Float64, "rhs_value_mw": pl.Float64}
    ta = pl.DataFrame([{"action": "add_adder", "rhs_value_mw": None, "months": "all", **r, "ends_at_grp": str(r["ends_at_grp"])}
                       for r in to_apply], schema_overrides=num, infer_schema_length=None) if to_apply else \
        pl.DataFrame(schema={c: num.get(c, pl.Utf8) for c in ta_cols})
    ta.select(ta_cols).sort("status", "esoo_constraint", "apply_from", "season").write_csv(RES / "rhs_offsets_to_apply.csv")
    make_chart(groups, cells_by)
    for g in groups:
        make_constraint_plot(g, cells_by[g[0]["esoo_constraint"]], low_by[g[0]["esoo_constraint"]])
        make_longrun_plot(g, daily, mms_daily_for(g[0]["esoo_constraint"]), g[0]["esoo_constraint"] in wrl_set)

    print("Status counts (constraint-segments):")
    for s, c in sorted({s: sum(r["status"] == s for r in recs) for s in {r["status"] for r in recs}}.items()):
        print(f"  {s}: {c}")
    print("\napply / apply_surrogate / review:")
    for r in sorted(recs, key=lambda r: (r["status"], r["esoo_constraint"], r["segment"])):
        if r["status"] in ("apply", "apply_surrogate", "review", "set_rhs"):
            print(f"  {r['status']:16s} {r['esoo_constraint']:28s} {r['segment']:9s} {r['form']:8s} "
                  f"S={r['adder_summer_mw']:+.0f} NS={r['adder_notsummer_mw']:+.0f} to {r['end_with_wrl']} "
                  f"| {r['reason']}")


if __name__ == "__main__":
    main()
