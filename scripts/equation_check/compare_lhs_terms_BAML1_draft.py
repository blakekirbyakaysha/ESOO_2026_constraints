import polars as pl
pl.Config.set_tbl_rows(100); pl.Config.set_tbl_width_chars(240); pl.Config.set_fmt_str_lengths(40)
D = r"C:\Dev\ESOO_2026_constraints\outputs\baml1_equation_check"
e = pl.read_parquet(r"C:\Dev\ESOO_2026_constraints\cache\lhs_terms.parquet").filter((pl.col("constraint")=="V>>V_NIL_BAML1_ELML1")&(pl.col("timeslice")=="Grp0"))
e = e.filter(pl.col("obj_type").is_in(["GENERATOR","BATTERY Generation"])).group_by("obj").agg(pl.col("coef").max())   # generation-side coefficient
cp = pl.read_csv(f"{D}/mms_spdconnectionpointconstraint.csv", infer_schema_length=None).filter(pl.col("BIDTYPE")=="ENERGY")
du = pl.read_csv(f"{D}/mms_dudetailsummary.csv", infer_schema_length=None)
def asof(g, date):
    x = cp.filter((pl.col("GENCONID")==g)&(pl.col("EFFECTIVEDATE")<=date)); mx = x["EFFECTIVEDATE"].max()
    return x.filter(pl.col("EFFECTIVEDATE")==mx), mx
for g, date in (("V>>NIL_ELML_BAML2","2026-09-30"),("V>>NIL_ELML_BAML2","2025-10-01")):
    x, mx = asof(g, date)
    # connection point -> DUIDs (active in Sept 2026)
    m = x.join(du.filter((pl.col("START_DATE")<="2026-09-30")&((pl.col("END_DATE").is_null())|(pl.col("END_DATE")>="2025-10-01"))), left_on="CONNECTIONPOINTID", right_on="CONNECTIONPOINTID", how="left")
    print(g, date, "version", mx, "connection-point terms", x.height, "-> DUID rows", m.height, "unmapped cps", m.filter(pl.col("DUID").is_null()).height)
    j = e.join(m.select("DUID","FACTOR","CONNECTIONPOINTID").unique(), left_on="obj", right_on="DUID", how="full", coalesce=True)
    both = j.filter(pl.col("coef").is_not_null()&pl.col("FACTOR").is_not_null())
    print("  ESOO gen/battery terms", e.height, "| matched by DUID name", both.height, "| ESOO-only", j.filter(pl.col("FACTOR").is_null()).height, "| MMS-only", j.filter(pl.col("coef").is_null()).height)
    if both.height:
        r = (both["coef"]/both["FACTOR"])
        print("  coef ratio ESOO/MMS on matched: median %.2f  P10 %.2f P90 %.2f   corr %.2f" % (r.median(), r.quantile(.1), r.quantile(.9), both.select(pl.corr("coef","FACTOR")).item()))
        print("  sum ESOO coef (matched) %.1f   sum MMS factor (matched) %.1f" % (both["coef"].sum(), both["FACTOR"].sum()))
        print(both.with_columns((pl.col("coef")/pl.col("FACTOR")).alias("ratio")).sort("coef", descending=True).head(14))
    print("  ESOO-only (name not a MMS DUID in this equation):", j.filter(pl.col("FACTOR").is_null()).sort("coef", descending=True)["obj"].to_list()[:40])
    print("  MMS-only (DUID/CP in MMS equation, not in ESOO):", j.filter(pl.col("coef").is_null()).sort("FACTOR", descending=True).select("obj","FACTOR","CONNECTIONPOINTID").head(25).rows())

# ---- save a joined table for manual verification (2026-09-30 version of V>>NIL_ELML_BAML2)
x, mx = asof("V>>NIL_ELML_BAML2", "2026-09-30")
m = x.join(du.filter((pl.col("START_DATE")<="2026-09-30")&((pl.col("END_DATE").is_null())|(pl.col("END_DATE")>="2025-10-01"))), on="CONNECTIONPOINTID", how="left")
j = e.join(m.select(pl.col("DUID").alias("obj"), pl.col("FACTOR").alias("mms_factor"), "CONNECTIONPOINTID").unique(), on="obj", how="full", coalesce=True)
j = j.rename({"coef": "esoo_coef"}).with_columns((pl.col("esoo_coef")/pl.col("mms_factor")).alias("ratio_esoo_over_mms"),
    pl.when(pl.col("mms_factor").is_null()).then(pl.lit("ESOO only (name not matched to a MMS DUID in this equation)"))
      .when(pl.col("esoo_coef").is_null()).then(pl.lit("MMS only")).otherwise(pl.lit("both")).alias("presence")).sort("presence","esoo_coef", descending=[False, True])
j.write_csv(r"C:\Dev\ESOO_2026_constraints\outputs\baml1_equation_check\lhs_terms_esoo_vs_mms.csv")
print("saved", j.height)
import numpy as np
d = pl.read_csv(r"C:\Dev\ESOO_2026_constraints\outputs\mms_comparison\V_V_NIL_BAML1_ELML1_30min.csv", infer_schema_length=None).with_columns(*[pl.col(c).cast(pl.Float64, strict=False) for c in ["actual_lhs","esoo_lhs","actual_rhs","esoo_rhs"]])
for c1, c2, nm in (("esoo_rhs","actual_rhs","RHS"),("esoo_lhs","actual_lhs","LHS")):
    a, b = d[c1].drop_nulls().to_numpy(), d[c2].drop_nulls().to_numpy()
    print(nm, "ESOO/MMS ratio at P5,P25,P50,P75,P95:", [round(float(np.quantile(a,q)/np.quantile(b,q)),2) for q in (.05,.25,.5,.75,.95)])
