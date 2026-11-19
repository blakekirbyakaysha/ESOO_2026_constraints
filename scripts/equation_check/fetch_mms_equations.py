"""Fetch MMS equation tables (all versions) for every matched constraint plus extras. Run with GLOBAL python (pandas, requests).
Output: outputs/equation_check/raw/mms_<table>.csv"""
import sys, os
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "mapping_tools"))
import quick_extract as q
import pandas as pd

out = ROOT / "outputs" / "equation_check" / "raw"; out.mkdir(parents=True, exist_ok=True)
m = pd.read_csv(ROOT / "outputs" / "mms_comparison" / "matched_constraints.csv")
ids = set(m["mms_constraint"].dropna())
ids |= {"V>>NIL_SMTX_SMTX_R5", "V>>NIL_SMTX_SMTX_T", "V>>NIL_SMTX_SMTX_R2"}   # SMTX variants
inl = ",".join(f"'{i}'" for i in sorted(ids))
for t in ("spdconnectionpointconstraint", "spdinterconnectorconstraint", "spdregionconstraint", "genericconstraintrhs", "gencondata"):
    df = q.qt_post_request(f"SELECT * FROM mms.{t} WHERE GENCONID IN ({inl}) ORDER BY GENCONID, EFFECTIVEDATE DESC, VERSIONNO DESC")
    df.to_csv(out / f"mms_{t}.csv", index=False)
    print(t, df.shape, df["GENCONID"].nunique() if len(df) else 0)
d = q.qt_post_request("SELECT DUID, CONNECTIONPOINTID, REGIONID, STATIONID, START_DATE, END_DATE FROM mms.dudetailsummary")
d.to_csv(out / "mms_dudetailsummary.csv", index=False); print("dudetailsummary", d.shape)
# search for better matches for the unmatched / questionable ones
