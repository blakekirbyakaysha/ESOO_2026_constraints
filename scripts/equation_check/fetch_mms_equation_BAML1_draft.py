import sys
sys.path.insert(0, r"C:\Dev\ESOO_2026_constraints\scripts\mapping_tools")
import quick_extract as q
import pandas as pd
pd.set_option("display.width", 250); pd.set_option("display.max_rows", 400)
out = r"C:\Dev\ESOO_2026_constraints\outputs\baml1_equation_check"
import os; os.makedirs(out, exist_ok=True)
ids = ["V>>NIL_ELML_BAML2", "V>>SML_NIL_1", "V>>SML_NIL_1_5M"]
inl = ",".join(f"'{i}'" for i in ids)
for t in ("spdconnectionpointconstraint", "spdinterconnectorconstraint", "spdregionconstraint", "genericconstraintrhs", "gencondata"):
    df = q.qt_post_request(f"SELECT * FROM mms.{t} WHERE GENCONID IN ({inl}) ORDER BY GENCONID, EFFECTIVEDATE DESC, VERSIONNO DESC")
    df.to_csv(f"{out}/mms_{t}.csv", index=False)
    print(t, df.shape, sorted(df['GENCONID'].unique()) if len(df) else '')
d = q.qt_post_request("SELECT DUID, CONNECTIONPOINTID, REGIONID, STATIONID, START_DATE, END_DATE FROM mms.dudetailsummary")
d.to_csv(f"{out}/mms_dudetailsummary.csv", index=False); print("dudetailsummary", d.shape)
try:
    c = q.qt_post_request("SELECT DUID, EFFECTIVEDATE, VERSIONNO, REGISTEREDCAPACITY, MAXCAPACITY, DISPATCHTYPE FROM mms.dudetail")
    c.to_csv(f"{out}/mms_dudetail.csv", index=False); print("dudetail", c.shape)
except Exception as e: print("dudetail ERR", str(e)[:150])
