"""Compare ESOO Grp0 LHS equations with the mapped MMS equations for every matched constraint.
Run with the project venv:  .venv\\Scripts\\python.exe -X utf8 -I scripts\\equation_check\\compare_equations.py
Needs outputs/equation_check/raw/ (fetch_mms_equations.py, global python).
Writes outputs/equation_check/: equation_check_summary_raw.csv, terms/<esoo id>__<timeslice>.csv"""
import re
from pathlib import Path
import numpy as np
import polars as pl

pl.Config.set_tbl_rows(100); pl.Config.set_tbl_width_chars(250); pl.Config.set_tbl_cols(20)
ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "outputs" / "equation_check" / "raw"
OUT = ROOT / "outputs" / "equation_check"; (OUT / "terms").mkdir(parents=True, exist_ok=True)
CMP = ROOT / "outputs" / "mms_comparison"
ASOF = ["2026-09-30", "2025-10-01"]
EXCLUDED = {"V>>NIL_SMTX2_SMTX1_R", "N>>NIL_LINC1_LITO1", "N>>N_NIL_DPTX3_DPTX4"}


def rd(n):
    return pl.read_csv(RAW / f"mms_{n}.csv", infer_schema_length=None)


cp = rd("spdconnectionpointconstraint").filter(pl.col("BIDTYPE") == "ENERGY")
ic = rd("spdinterconnectorconstraint")
gd = rd("gencondata")
du = rd("dudetailsummary").with_columns(pl.col("START_DATE").cast(pl.Utf8), pl.col("END_DATE").cast(pl.Utf8))
esoo = pl.read_parquet(ROOT / "cache" / "lhs_terms.parquet")
meta = pl.read_parquet(ROOT / "cache" / "eq_meta.parquet")
matched = pl.read_csv(CMP / "matched_constraints.csv").filter(pl.col("status") == "matched")
files = {}
for _p in CMP.glob("*_30min.csv"):
    _d = pl.read_csv(_p, infer_schema_length=0, n_rows=1)
    if _d.height:
        files[_d["esoo_constraint"][0]] = _p


def asof(df, gid, date):
    x = df.filter((pl.col("GENCONID") == gid) & (pl.col("EFFECTIVEDATE").cast(pl.Utf8).str.slice(0, 10) <= date))
    if x.height == 0:
        return x, None
    mx = x["EFFECTIVEDATE"].max()
    x = x.filter(pl.col("EFFECTIVEDATE") == mx)
    return x.filter(pl.col("VERSIONNO") == x["VERSIONNO"].max()), str(mx)[:10]


def mms_terms(gid, date):
    """MMS generator terms (DUID) and interconnector terms as of date."""
    x, v = asof(cp, gid, date)
    if x.height:
        act = du.filter((pl.col("START_DATE").str.slice(0, 10) <= "2026-09-30") &
                        (pl.col("END_DATE").is_null() | (pl.col("END_DATE").str.slice(0, 10) >= "2025-10-01")))
        x = x.join(act, on="CONNECTIONPOINTID", how="left")
        g = x.select(pl.col("DUID").alias("obj"), pl.col("FACTOR").alias("mms_factor")).unique()
    else:
        g = pl.DataFrame(schema={"obj": pl.Utf8, "mms_factor": pl.Float64})
    y, _ = asof(ic, gid, date)
    i = y.select(pl.col("INTERCONNECTORID").alias("obj"), pl.col("FACTOR").alias("mms_factor")) if y.height \
        else pl.DataFrame(schema={"obj": pl.Utf8, "mms_factor": pl.Float64})
    return g, i, v


def desc(gid, date):
    x, _ = asof(gd, gid, date)
    return (x["DESCRIPTION"][0], x["DYNAMICRHS"][0], x["CONSTRAINTVALUE"][0]) if x.height else ("", None, None)


def toks(s):
    return set(re.findall(r"[A-Za-z]*\d+[A-Za-z0-9]*|[A-Z]{3,}", s or ""))


def q(a, p):
    a = np.asarray(a, float)
    a = a[~np.isnan(a)]
    return float(np.quantile(a, p)) if len(a) else None


rows = []
for r in matched.iter_rows(named=True):
    eid, mid = r["esoo_constraint"], r["mms_constraint"]
    safe = re.sub(r"[^A-Za-z0-9]", "_", eid)
    ratios = {}
    if eid in files:
        d = pl.read_csv(files[eid], infer_schema_length=None).with_columns(
            *[pl.col(c).cast(pl.Float64, strict=False) for c in ["actual_lhs", "esoo_lhs", "actual_rhs", "esoo_rhs"]])
        d = d.drop_nulls(["actual_rhs", "esoo_rhs"])
        for nm, e_, a_ in (("rhs", "esoo_rhs", "actual_rhs"), ("lhs", "esoo_lhs", "actual_lhs")):
            for p in (.05, .5, .95):
                ea, aa = q(d[e_], p), q(d[a_], p)
                ratios[f"{nm}_ratio_P{int(p * 100)}"] = round(ea / aa, 2) if ea is not None and aa and abs(aa) > 1e-6 else None
        if d.height:
            ratios["rhs_mms_P5_P50_P95"] = "/".join(f"{q(d['actual_rhs'], p):.0f}" for p in (.05, .5, .95))
            ratios["rhs_esoo_P5_P50_P95"] = "/".join(f"{q(d['esoo_rhs'], p):.0f}" for p in (.05, .5, .95))
    e_all = esoo.filter(pl.col("constraint") == eid)
    have = e_all["timeslice"].unique().to_list()
    tss = [t for t in ("Grp0", "NotSummer_Grp0", "Summer_Grp0") if t in have]
    ed = meta.filter((pl.col("constraint") == eid) & (pl.col("timeslice") == (tss[0] if tss else "Grp0")))
    edesc = ed["description"][0] if ed.height else ""
    for ts in tss:
        e = e_all.filter(pl.col("timeslice") == ts)
        eg = e.filter(pl.col("obj_type").is_in(["GENERATOR", "BATTERY Generation"])).group_by("obj").agg(pl.col("coef").max()).rename({"coef": "esoo_coef"})
        el = e.filter(pl.col("obj_type") == "LINE").group_by("obj").agg(pl.col("coef").first()).rename({"coef": "esoo_coef"})
        for date in ASOF:
            g, i, ver = mms_terms(mid, date)
            mdesc, dyn, cval = desc(mid, date)
            j = eg.join(g, on="obj", how="full", coalesce=True)
            both = j.filter(pl.col("esoo_coef").is_not_null() & pl.col("mms_factor").is_not_null() & (pl.col("mms_factor") != 0))
            ji = el.join(i, on="obj", how="full", coalesce=True)
            tab = pl.concat([j.with_columns(pl.lit("GEN").alias("kind")), ji.with_columns(pl.lit("IC").alias("kind"))]).with_columns(
                (pl.col("esoo_coef") / pl.col("mms_factor")).alias("ratio"),
                pl.when(pl.col("mms_factor").is_null()).then(pl.lit("ESOO only"))
                  .when(pl.col("esoo_coef").is_null()).then(pl.lit("MMS only")).otherwise(pl.lit("both")).alias("presence"))
            if date == ASOF[0]:
                tab.write_csv(OUT / "terms" / f"{safe}__{ts}.csv")
            rat = both["esoo_coef"] / both["mms_factor"] if both.height else pl.Series([], dtype=pl.Float64)
            icb = ji.filter(pl.col("esoo_coef").is_not_null() & pl.col("mms_factor").is_not_null())
            es_only = j.filter(pl.col("mms_factor").is_null())
            ms_only = j.filter(pl.col("esoo_coef").is_null())
            wm = float(both["esoo_coef"].abs().sum() / max(eg["esoo_coef"].abs().sum(), 1e-9)) if eg.height else None
            wmm = float(both["mms_factor"].abs().sum() / max(j["mms_factor"].abs().sum(), 1e-9)) if j.height else None
            dt = toks(edesc) & toks(mdesc)
            rows.append(dict(
                esoo_constraint=eid, mms_constraint=mid, timeslice=ts, mms_asof=date, mms_version=ver,
                provisional_exclusion=eid in EXCLUDED,
                esoo_gen_terms=eg.height, mms_gen_terms=g.height, matched_terms=both.height,
                esoo_only=es_only.height, mms_only=ms_only.height,
                esoo_only_names=";".join(es_only.sort("esoo_coef", descending=True)["obj"].head(8).to_list()),
                mms_only_names=";".join(ms_only.drop_nulls("obj")["obj"].head(8).to_list()),
                matched_share_esoo=round(wm, 2) if wm is not None else None,
                matched_share_mms=round(wmm, 2) if wmm is not None else None,
                coef_ratio_med=round(float(rat.median()), 2) if len(rat) else None,
                coef_ratio_P10=round(float(rat.quantile(.1)), 2) if len(rat) else None,
                coef_ratio_P90=round(float(rat.quantile(.9)), 2) if len(rat) else None,
                coef_corr=round(float(both.select(pl.corr("esoo_coef", "mms_factor")).item()), 2) if both.height > 2 else None,
                ic_terms=";".join(f"{o}:esoo {a}|mms {b}" for o, a, b in icb.select("obj", "esoo_coef", "mms_factor").rows()),
                esoo_ic_only=";".join(ji.filter(pl.col("mms_factor").is_null())["obj"].to_list()),
                mms_ic_only=";".join(ji.filter(pl.col("esoo_coef").is_null())["obj"].to_list()),
                mms_dynamic_rhs=dyn, mms_constraint_value=cval,
                desc_token_overlap=round(len(dt) / max(len(toks(edesc) | toks(mdesc)), 1), 2),
                esoo_desc=edesc, mms_desc=mdesc, **ratios))
res = pl.DataFrame(rows, infer_schema_length=None)
res.write_csv(OUT / "equation_check_summary_raw.csv")
print(res.filter(pl.col("mms_asof") == ASOF[0]).select(
    "esoo_constraint", "timeslice", "esoo_gen_terms", "mms_gen_terms", "matched_terms", "matched_share_esoo",
    "coef_ratio_med", "coef_ratio_P10", "coef_ratio_P90", "coef_corr", "rhs_ratio_P50", "lhs_ratio_P50"))
