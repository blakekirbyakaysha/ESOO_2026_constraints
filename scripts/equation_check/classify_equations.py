"""Combine compare_equations.py statistics (as of 2026-09-30, Grp0) with the reviewed classification of each matched
constraint and write outputs/equation_check/equation_check_summary.csv (one row per ESOO constraint).
Classes: same | scaled | different formulation | remap | same (dynamic RHS) | no gen terms (IC only).
The class and note per constraint are the analyst's reading of the evidence (descriptions, term tables, ratios); the
statistics columns come from the comparison. Re-check the classes if the mapping or MMS data change.
Run: .venv\\Scripts\\python.exe -X utf8 -I scripts\\equation_check\\classify_equations.py"""
from pathlib import Path
import polars as pl

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs" / "equation_check"

# (class, adder_method, note)
C = {
 "N::N_NIL_63": ("same", "additive RHS adder valid", "Identical description. Matched coefs ratio 1.00. ESOO has extra new-plant terms (MMS equation has only plants registered today), so ESOO LHS is higher by construction."),
 "N::V_NIL_MSDD": ("same", "additive RHS adder valid", "Identical description; matched coefs 1.00. ESOO LHS differs from MMS by correlation ~0 (dispatch differences), not by formulation."),
 "N^^N_NIL_WGLT": ("same", "additive RHS adder valid", "Identical description and interconnector terms (VIC1-NSW1 0.376, V-S-MNSP1 -0.156); matched coefs 1.00."),
 "N^^V_NIL_1": ("same", "additive RHS adder valid, with caution", "Identical description; matched coefs 1.00, interconnector VIC1-NSW1 -1.0 in both. No NSW1-SA1 term in ESOO or in any MMS version (MMS had V-S-MNSP1 -0.119 until 2025-12-02, then dropped it; ESOO has none) - NSW1-SA1 check closed. ESOO LHS about 1.96x MMS because ESOO has 55 extra terms (Snowy MURRAY01-14 unit names vs MMS aggregate MURRAY, and future plants), and RHS P5 is 1.44x. Name matching covers only 24% of ESOO coefficient weight."),
 "N>>_N_NIL_UTMR1_LTWG1": ("same", "additive RHS adder valid", "Elements agree (Murray-Upper Tumut 65 on loss of Wagga-Lower Tumut 051). Matched coefs 1.00. MMS id V>>N_NIL_65_051."),
 "N>>N_NIL_BASW1": ("same", "additive RHS adder valid", "Elements agree (Bannaby-Sydney West 39, Nil trip). Coefs 0.96 and interconnector factors 0.96 of MMS; RHS ratio ~0.97."),
 "N>>N_NIL_UTMR1_LTMR1": ("same", "additive RHS adder valid", "Elements agree (65 on trip of 66). Coefs 1.00. ESOO has an extra V-S-MNSP1 term."),
 "N>>N_NIL_UTMR1_LTMR1_R": ("same", "additive RHS adder valid", "Elements agree (reverse direction). MMS note: swamped if TL 64 out of service."),
 "N>>N_NIL_WASS1_WAIN1": ("same", "additive RHS adder valid", "Elements agree (76 on trip of 77). Coefs 0.96, interconnector factors ~0.96 of MMS."),
 "N>>N_NIL_WGANM1_WLJI1": ("same", "additive RHS adder valid", "Elements agree (996 on trip of 62). Coefs 0.90 and VIC1-NSW1 0.264 vs 0.292 (0.90): ESOO about 10% smaller on LHS; MMS swamps when 996 is out of service."),
 "N>>NIL_LINC1_LITO1": ("same", "none (excluded): MMS match is a configuration variant", "Elements agree (Liddell-Newcastle 81 on trip of 82) and coefs match 1.00 on 99 terms. The mapped MMS id is the 'Kurri-Rothbury-Singleton 132kV OPEN' variant, swamped (RHS 15,000 MW) in about 60% of intervals: MMS non-swamped P5 RHS 5,590 vs ESOO 5,650, so the +9,890 MW gap is a swamp state, not an equation difference. The CLOSE variant (N>>NIL_81_82_CLOSE) is not in Constraint_Data. Exclusion supported: no usable adder."),
 "N>>NIL_MGLT1_MRUT1": ("scaled", "compare in utilisation space; do not apply an additive gap", "Elements agree (Lower Tumut-Maragle 64 on trip of 65). Coefs 0.79 and VIC1-NSW1 0.567 vs 0.721 (0.79): ESOO equation is about 0.79x MMS on the LHS; RHS ratio P5 0.59 / P50 see rhs_ratio_P50."),
 "S_V_NIL_ROCOF": ("same (dynamic RHS)", "do not use an additive gap (RHS depends on decision variables)", "Identical description; only interconnector terms (V-SA -1.0). RHS ESOO/MMS P50 0.63."),
 "S:VS_800": ("same (dynamic RHS)", "none needed: fixed 800 MW limit", "Identical description, interconnector terms V-S-MNSP1 and V-SA -1.0 in both. Constant RHS by design; ESOO/MMS RHS P50 0.87 reflects dynamic RHS or data."),
 "S>>S_NIL_WEWT1_LKDP1": ("same", "additive RHS adder valid", "Elements agree (Waterloo East-Waterloo on trip of Davenport-Mt Lock). Coefs 0.98. ESOO has an extra V-SA term."),
 "T_ROCOF_1": ("same (dynamic RHS)", "do not use an additive gap (RHS depends on decision variables)", "Identical description and interconnector term T-V-MNSP1 -0.8577. RHS P50 ratio 0.87, LHS ratio 4.65 (small denominator)."),
 "T_ROCOF_3_2": ("same (dynamic RHS)", "do not use an additive gap (RHS depends on decision variables)", "Identical description; MMS DYNAMICRHS=1. RHS ratio P50 0.68."),
 "V_NWVIC_GFT1_750": ("same", "none needed: fixed 750 MW limit", "Identical description; 6 matched generator terms at 1.00; RHS ratio ~1.02."),
 "V_S_NIL_ROCOF": ("same (dynamic RHS)", "do not use an additive gap (RHS depends on decision variables)", "Identical description; V-SA +1.0 in both. RHS ratio P50 0.64."),
 "V::V_1900": ("same", "none needed: fixed 1,900 MW limit", "Identical description; MMS equation has the aggregate MURRAY DUID, ESOO the unit names MURRAY01-14 (name match 0%, not a real difference). RHS 1,900 in both."),
 "V^^N_NIL_1": ("same", "additive RHS adder valid", "Identical description; interconnector terms VIC1-NSW1 1.0 and V-S-MNSP1 0.192 identical; coefs 1.00."),
 "V>>NIL_MLGL1_MLGL2": ("scaled", "compare in utilisation space; ESOO units = 0.5x MMS, so an MMS MW gap must be halved", "Elements agree. MMS has one equation 'Moorabool-Geelong #1 or #2 on trip of the other', ESOO has one per direction. All coefs and interconnector terms are 0.50x MMS (corr 0.99) and RHS ratio ~0.55, so ESOO is a half-scale copy: the MW gap is not an adder in ESOO units (+1,085 MW would be about +540 in ESOO units if the scale were applied, and utilisation matching gives +85/0)."),
 "V>V_NIL_MLGL2_MLGL1": ("scaled", "as V>>NIL_MLGL1_MLGL2 (same MMS series)", "Same as V>>NIL_MLGL1_MLGL2: one MMS series serves both directions; ESOO equations are 0.5x MMS on every term."),
 "V>>NIL_SMTX2_SMTX1_R": ("different formulation", "none (excluded): MMS match is a configuration variant", "Elements agree in text but the mapped V>>NIL_SMTX_SMTX_R2 is the 'radial mode, Yallourn W1 on 220kV' variant: MMS RHS is at or above 5,000 MW in 89% of intervals and ~15,000 MW (swamped) in 66%, while ESOO RHS is 5,400-6,600. Coefs 1.13x, interconnector factors 1.11x. Sister variants R5 and T exist in MMS but are not in Constraint_Data. Exclusion supported: no usable adder from this series."),
 "V>>NIL_WBBA_KGBE": ("same", "additive RHS adder valid, with caution", "Elements agree (Waubra-Ballarat on trip of Kerang-Bendigo). Coefs 0.93, but ESOO has V-SA where MMS has V-S-MNSP1 (Heywood vs Murraylink term): check the interconnector term in the ESOO equation."),
 "V>>NIL_WBBA_RCWEKG": ("same", "additive RHS adder valid, with caution", "Elements agree (Waubra-Ballarat on trip of Red Cliffs-Wemen-Kerang/Koorangie). Coefs 0.93; same V-SA vs V-S-MNSP1 difference as KGBE."),
 "V>>S_NIL_MHNW1_MHNW2_NO_MLRB": ("no gen terms (IC only)", "additive RHS adder valid", "Elements agree (Monash-North West Bend 2 on trip of 1); no generator terms in either, only V-S-MNSP1 1.0 identical."),
 "V>>V_NIL_BAML1_ELML1": ("different formulation", "reject additive adder; utilisation space gives about +35 MW or none", "ESOO monitors Ballarat-Moorabool No.1 for loss of Elaine-Moorabool; mapped MMS monitors Elaine-Moorabool for loss of Ballarat-Moorabool No.2. All matched coefs 1.46x (corr 0.95), RHS 1.44x, LHS 1.6-1.9x. Closer MMS equation V>>SML_NIL_1 retired in 2017."),
 "V>>V_NIL_DDSM1_DDSM2": ("same", "additive RHS adder valid (non-SIPS months); SIPS months set RHS out of model", "Elements agree (Dederang-South Morang, parallel line trip). Coefs 1.00. MMS note: swamp if SIPS available. ESOO has an extra V-SA term."),
 "V>>V_NIL_MRDD1_MRDB2": ("same", "additive RHS adder valid (non-SIPS months); SIPS months set RHS out of model", "Elements agree (Murray-Dederang 1 on loss of 2). Coefs 1.02 (corr 0.93). MMS note: swamp if SIPS available."),
 "V>>V_NIL_WETX1_R": ("same (dynamic RHS)", "override 0 stands; RHS depends on decision variables", "Elements agree (Wemen 220/66 transformer, pre-contingent). 2 matched terms at 1.00; MMS DYNAMICRHS=1."),
 "N>>N_NIL_DPTX3_DPTX4": ("same", "none (excluded); equation is not wrong, ESOO LHS reflects plants missing from MMS", "22 MMS generator terms match ESOO exactly (ratio 1.00, corr 1.00). The other 55 ESOO terms (67% of coefficient weight) are plants not in the MMS equation today (Baldon, Junction Rivers, Silver City, Limondale and others), so ESOO LHS is higher (median utilisation 0.33 vs MMS 0.05) and ESOO binds where MMS never does. ESOO also has a VIC1-NSW1 term MMS lacks. The 'LHS does not check out' is explained by forward-looking plant terms. Exclusion is a modelling choice rather than an equation error."),
}

raw = pl.read_csv(OUT / "equation_check_summary_raw.csv", infer_schema_length=None).filter(pl.col("mms_asof") == "2026-09-30")
raw = raw.sort("esoo_constraint", "timeslice").group_by("esoo_constraint", maintain_order=True).first()
rows = []
for r in raw.iter_rows(named=True):
    cls, method, note = C[r["esoo_constraint"]]
    rows.append({**{k: r[k] for k in ("esoo_constraint", "mms_constraint", "provisional_exclusion")}, "equation_class": cls, "adder_method": method, "note": note,
        **{k: r[k] for k in ("esoo_gen_terms", "mms_gen_terms", "matched_terms", "matched_share_esoo", "coef_ratio_med", "coef_ratio_P10", "coef_ratio_P90", "coef_corr",
                             "ic_terms", "esoo_ic_only", "mms_ic_only", "esoo_only_names", "mms_only_names", "mms_dynamic_rhs",
                             "rhs_ratio_P5", "rhs_ratio_P50", "rhs_ratio_P95", "lhs_ratio_P5", "lhs_ratio_P50", "lhs_ratio_P95", "rhs_mms_P5_P50_P95", "rhs_esoo_P5_P50_P95",
                             "esoo_desc", "mms_desc")}})
out = pl.DataFrame(rows, infer_schema_length=None)
extra = pl.DataFrame([
 {"esoo_constraint": "V>>NIL_WBBA1", "mms_constraint": "V>>SML_NIL_6", "equation_class": "remap", "note": "V>>SML_NIL_6 is retired (last RHS 2022-05-11) and its description (Bendigo-Fosterville-Shepparton 220kV on a Moorabool trip) is a different element; no MMS equivalent found. No MMS data in Constraint_Data."},
 {"esoo_constraint": "V>>V_NIL_GNTX1_GNTX2_R", "mms_constraint": "V>V_GNTS_B2_1", "equation_class": "remap", "note": "V>V_GNTS_B2_1 retired (last RHS 2021-04-09). Candidate replacement V>NIL_GNTX_GNTX ('avoid O/L GNTS B2 or B3 220/66kV transformer, flow 66 to 220kV, on trip of the other'); not in Constraint_Data, so needs a data pull and a Blake decision."},
 {"esoo_constraint": "V>>V_NIL_WBBA1_RCKESS1", "mms_constraint": "V>>V_NIL_7", "equation_class": "remap", "note": "V>>V_NIL_7 retired (last RHS 2023-03-06); it was the Waubra-Ballarat on trip of Red Cliffs-Wemen-Kerang equation, now V>>NIL_WBBA_RCWEKG (already mapped to ESOO V>>NIL_WBBA_RCWEKG and in Constraint_Data). Candidate: map this ESOO constraint to V>>NIL_WBBA_RCWEKG after confirming the ESOO elements."},
], infer_schema_length=None)
out = pl.concat([out, extra], how="diagonal_relaxed")
out.write_csv(OUT / "equation_check_summary.csv")
print(out.group_by("equation_class").len().sort("len", descending=True))
