# ESOO 2026 no-WRL constraint study: close-out (state at 2026-10-29)

Written for: Blake Kirby (Akaysha Energy), who owns every decision. Status: adders and equation edits are final and ready to enter in the ESOO; the re-run verification (6F) waits for the ESOO re-run.

## Scope and method
- Victoria is modelled without WRL and VNI West. The 49-constraint candidate list (`outputs/final_constraint_list.csv`) is kept whole. Blake does not model a dynamic RHS: the RHS is fixed in the market model, so every adder is a proxy for an MMS-calibrated level.
- RHS adders = MMS - ESOO, from 12 months of MMS data against the ESOO FY27 run, fitted on month x half-hour gaps (median, or P10 where the median fit fails). Where the ESOO equation is a scaled copy of MMS (coefficient ratio outside 1 +/- 0.05), the MMS RHS is multiplied by that ratio first (`rhs_offsets.py`).
- ESOO equations were compared with the mapped MMS equations (`scripts/equation_check/`): 20 same, 6 same with dynamic RHS, 3 scaled, 2 different formulation, 1 IC-only; 3 constraints have no usable MMS data.

## Final decisions (Blake, 2026-10-29)
- Adders: `final_rhs_adders.csv`. Edits to enter by hand: `esoo_equation_edits.csv`. The table covers 50 constraints: 15 have add_adder rows (14 non-zero; `V>>V_NIL_WETX1_R` is override 0, and DDSM's Apr-Oct adder is one of the 14), 31 have no adder, 3 are not modelled, and 2 carry a SIPS rule applied out-of-model (DDSM also has the Apr-Oct adder).
- MLGL pair: no adder (scaled copy; gap is never positive in the 9 months with data). `N>>NIL_MGLT1_MRUT1`: no adder after scaling. `V>>V_NIL_BAML1_ELML1`: no adder (different formulation). `N^^V_NIL_1`: adder rejected (-165; utilisation matching gives +80/0).
- ROCOF and other dynamic-RHS constraints keep fixed adders as an approximation.
- Not modelled: `V>>NIL_SMTX2_SMTX1_R`, `N>>NIL_LINC1_LITO1`, `N>>N_NIL_DPTX3_DPTX4`; the equation check supports the first two and shows the DPTX equation is sound (ESOO LHS includes plants absent from MMS).
- No remapping of the three constraints without MMS data (ESOO RHS used as is). Candidate-list trimming, Marinus terms and WRL-affected equation form (6C, 6D) were dropped by Blake.
- SIPS (`V>>V_NIL_DDSM1_DDSM2`, `V>>V_NIL_MRDD1_MRDB2`): set RHS to 10,000 MW in Nov-Mar until 2032-03-31, applied to the RHS time series, not in the ESOO equations. DDSM's Apr-Oct +145 is entered in all months of its flat equation.
- `N::N_NIL_63`: the ESOO equation has no Summer/NotSummer timeslices, so +45 is entered everywhere and the extra +65 for Dec-Feb is applied to the RHS time series (`out_of_model_seasonal_adjustments.csv`).

## Entering the adders
`scriptsuild_plexos_paste.py` reads the PLEXOS RHS exports in `inputs/rhs_adjust/` and writes paste-ready files in `outputs/FINAL/plexos_paste/` (same format: tab separated, UTF-8, CRLF, every row of each export, so Ctrl+A / copy / paste works). Each changed row gets one extra expression line `1 <adder MW> MUL ADD` at the end, so the adder is added to the finished RHS. `plexos_paste_summary.csv` lists every row changed. (The earlier `apply_adders_to_rhs.py` works on the published workbook text and is not used.) `N^^V_NIL_1` and `V>>V_NIL_BAML1_ELML1` get no adder and stay in the model with the ESOO RHS as is.

## Files
`final_rhs_adders.csv`, `esoo_equation_edits.csv`, `out_of_model_seasonal_adjustments.csv`, `equation_check_summary.csv`, this file. Supporting: `outputs/equation_check/DECISION_SHORTLIST.md`, `outputs/rhs_offsets/` (charts with an explanation panel per constraint), `inputs/adder_review.csv`.
Rebuild: `.venv\Scripts\python.exe -X utf8 -I scripts\rhs_offsets.py` then `scripts\build_final_package.py`.

## Known limitations
- Only one year of MMS data (Oct 2025 to Sep 2026) against one ESOO year; ESOO FY27 months are paired with MMS months of the same calendar month.
- Name-only DUID matching; Snowy unit names (MURRAY01-14) do not match the MMS aggregate. ESOO LHS excess from extra plants versus dispatch could not be separated (no ESOO unit generation).
- SIPS end date 2032-03-31 is assumed from "until 2032". Grp-to-project mapping is inferred (only Grp5 to Grp6 = WRL confirmed). Several adders are low-end (P10) or short-fit (7 months) and flagged in the review sheet.
- Sister MMS variants (SMTX R5/T, LINC1_LITO1 CLOSE) are not in Constraint_Data.

## Still open
1. 6F: after Blake's ESOO re-run with interval reporting, verify the adders landed (new RHS minus old RHS = adder) and build the RHS series per constraint and scenario with the SIPS and Dec-Feb adjustments.
2. 6G: object-name match against Blake's model, reference-year check.
