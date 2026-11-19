# Plan: flat RHS adders from the MMS comparison

Written 2026-10-27 for an implementing session (Sonnet). Read `PROJECT_CONTEXT.md` and `README.md` (section on `compare_to_MMS.py`) first. Run Python with `.venv\Scripts\python.exe -X utf8 -I`.

## Goal
For each constraint in `outputs\mms_comparison\comparison_summary.csv` (30 constraints), decide whether the ESOO RHS needs a flat adder to match MMS actual RHS, and if so how much. Use the fewest parameters the data supports: **no adder** by default, **one flat value** if the evidence is strong and stable, **two values (Summer / NotSummer)** only if one value clearly fails. Do not fit time-of-day shapes or monthly values. The output is a reviewed table that the user will apply by hand in the ESOO PLEXOS model. Do not edit any PLEXOS inputs or the RHS series in this task.

## User decisions (2026-10-27, settled)
- `V>>V_NIL_BAML1_ELML1` stays in the model, even though it is not in `outputs\final_constraint_list.csv`. Treat it like any other constraint.
- Each adder applies from the start of the run **until the constraint's RHS equation first changes** (at a later Grp), then stops. See step 7.
- The user makes the changes in the ESOO model themselves, so the output must give, per constraint and timeslice, the adder value and the date range it applies to.

Sign convention: `adder = MMS - ESOO` (added to the ESOO RHS). The `*_bias_esoo_minus_mms` columns in `comparison_summary.csv` have the opposite sign.

## The data, and why the existing metrics are not enough
- Per-constraint files: `outputs\mms_comparison\<safe_name>_30min.csv` with `datetime, esoo_constraint, mms_constraint, actual_lhs, esoo_lhs, actual_rhs, esoo_rhs, actual_binding`. Read with `infer_schema_length=None` (otherwise the RHS columns can be read as strings).
- MMS covers Oct 2025-Sep 2026; ESOO covers FY27 (Jul 2026-Jun 2027). The exact time overlap is only Jul-Sep 2026 (4,416 half-hours, winter only), which is what `comparison_summary.csv` uses. Fitting on that alone would bake a winter bias into all months.
- So pair the sources by **month of year and half-hour slot**, not by timestamp. Use `profile_key()` from `scripts\compare_to_MMS.py` (import it; it handles the interval-ending midnight convention). ESOO RHS sentinels are already nulled in the CSVs; also drop MMS RHS with `abs >= 1e20`.
- The ESOO RHS comes from ESOO dispatch, and the MMS RHS from actual dispatch in a different year. A flat adder can only correct a systematic level difference, not dispatch-driven variation. The rules below are designed to reject anything that is not a stable level difference.

## Method (new script `scripts\rhs_offsets.py`)

### 1. Build the paired grid
For each constraint, compute the **median** MMS RHS and the median ESOO RHS for each (month, slot) cell, giving up to 12 x 48 cells. Use medians, because the MMS RHS has outage and constraint-swap outliers (for example `N>>NIL_LINC1_LITO1` jumps by about 10,000 MW in some months). Keep a cell only if both sources have at least 10 values in it. Keep a month only if at least 40 of its 48 slots are kept. `diff = mms_med - esoo_med` per cell.

### 2. Gates applied before fitting (status set, no adder)
Apply these in order; the first that matches sets the status.
| Gate | Status |
|---|---|
| RHS depends on decision variables: `T_ROCOF_1`, `T_ROCOF_3_2`, `S_V_NIL_ROCOF`, `V_S_NIL_ROCOF` | `excluded_dynamic_rhs` |
| Fewer than 9 usable months | `insufficient_data` |

### 3. Candidate fits
- **Flat:** `a = median over months of (median diff in that month)`, so each month has equal weight. Round to the nearest 5 MW.
- **Seasonal:** the same, separately for Summer (Dec, Jan, Feb, matching the model's `Summer_*` timeslices) and NotSummer (Mar-Nov). Round each to 5 MW.

### 4. Tests (all thresholds are constants at the top of the script)
For the flat fit:
- **Material:** `|a| >= max(20 MW, 3% of the median MMS RHS)`.
- **Consistent sign:** at least 10 of the usable months have a monthly median diff with the same sign as `a` (scale proportionally if fewer than 12 months, so at least 80%).
- **Out-of-sample gain (leave one month out):** for each month, refit `a` on the other months, apply it to the held-out month's cells, and compare the cell MAE against no adder. Pass if the adder lowers the MAE in at least 75% of the held-out months **and** the total held-out MAE drops by at least 20%.

For the seasonal fit, use the same leave-one-month-out test, refitting both values each time. Choose seasonal over flat only if all of these hold:
- the seasonal held-out MAE is at least 15% below the flat held-out MAE,
- `|a_summer - a_notsummer| >= max(20 MW, 3% of the median MMS RHS)`,
- each seasonal value passes the materiality and sign tests within its own months. A season value that fails is set to 0, not dropped silently.

### 5. Equivalence flags (do not block, but downgrade the status)
`match_method` is `No match` for 17 constraints. These were mapped by hand to an MMS constraint with a different ID (for example `N>>N_NIL_BASW1` -> `N>>NIL_39`), so the two equations may differ, and part of the RHS gap may be formulation rather than level. Flag, and set the status to `review` instead of `apply`, if any of the following holds:
- the mapping is `No match` and `|a| > 25%` of the median MMS RHS (likely a different formulation; expected for `V>V_NIL_MLGL2_MLGL1`, `N>>NIL_MGLT1_MRUT1`, `N>>_N_NIL_UTMR1_LTWG1`, `N>>NIL_LINC1_LITO1`),
- the MMS RHS within months is bimodal or very wide: the median across months of `IQR / median` is above 0.5,
- the diurnal shape disagrees: pool all months, compute the median diff per slot, and flag if `max - min > max(|a|, 50 MW)`. Report this range in all cases.

### 6. Statuses
`apply` (passed everything, `Constraint ID` match), `apply_surrogate` (passed everything, `No match` mapping but no flags), `review` (passed the tests but flagged in step 5), `no_change` (failed materiality, sign or out-of-sample tests), plus the gate statuses from step 2. Record the first failing test in a `reason` column, in plain words.

### 7. End date: the first RHS equation change
The adder is fitted against FY27 ESOO and applies only until the constraint's RHS equation first changes. Find that change in `constraint_changes_by_grp.csv`: rows for the constraint where `rhs_any` is True. Take the smallest `to_grp`. Handle the `season` column: a change in `Summer` rows ends the Summer adder, a change in `NotSummer` rows ends the NotSummer adder, and `All` ends both. So a flat adder can end at different dates for the two seasons; report them separately.

Convert Grp to the date it starts (from `PROJECT_CONTEXT.md`): 0 Jul-2026, 1 Feb-2027, 2 Dec-2027, 3 Jun-2028, 4 May-2029, 5 Mar-2030, 6 Nov-2030, 7 Jul-2031, 8 Dec-2031, 9 Apr-2032, 10 Jul-2033, 11 Jan-2035. The adder applies up to the day before that date. If there is no RHS change, it applies to the end of the run.

Before relying on this, check what `rhs_any` actually flags (coefficient change only, or also added or removed terms) by looking at a few rows against `ESOO2026 Constraints Details.xlsx` / `cache\`, and state the definition in the README. A change in LHS terms only does **not** end the adder.

**Change inside the fit window:** if the first RHS change is at Grp1 (Feb 2027), the FY27 ESOO data mixes two RHS equations. Then fit only on ESOO months before Feb 2027 (Jul-Jan, paired with the same MMS months). With 7 months, the 9-month minimum fails, so set the status to `review` with the reason "RHS changes Feb 2027 inside fit window"; still report the fitted value on Jul-Jan.

**No-WRL scenario:** WRL-affected constraints (`outputs\wrl_affected_constraints.txt`) are frozen at their Grp5 equation from Nov 2030 in the no-WRL version, so RHS changes from Grp6 onwards do not happen there. For these, report the end date twice: `end_with_wrl` (from the rule above) and `end_no_wrl` (ignore changes at Grp6 and later; if the first change is at Grp5 or earlier, it is the same as with WRL). For the other constraints the two are the same.

### 8. Outputs (to `outputs\mms_comparison\`)
- `rhs_offsets_to_apply.csv`: the user's working list for editing the ESOO model. One row per constraint, timeslice and scenario where an adder is non-zero and the status is `apply`, `apply_surrogate` or `review`: `esoo_constraint, status, season (All|Summer|NotSummer), scenario (with_wrl|no_wrl), adder_mw, apply_from (2026-07-01), apply_to (last day before the first RHS change, or end of run), ends_at_grp, rhs_change_desc`. Sort by status then constraint. If both scenarios have the same dates, a single row with `scenario = both` is fine.
- `rhs_offsets.csv`: one row per constraint with `esoo_constraint, mms_constraint, match_method, in_final_list, status, reason, adder_flat_mw, adder_summer_mw, adder_notsummer_mw, form (none|flat|seasonal), median_mms_rhs, adder_pct_of_rhs, months_used, months_same_sign, loo_months_improved, loo_mae_none, loo_mae_flat, loo_mae_seasonal, diurnal_range_mw, iqr_ratio, overlap_bias_jul_sep (exact-overlap check, MMS - ESOO), mms_binding_pct, first_rhs_change_grp_summer, first_rhs_change_grp_notsummer, end_with_wrl, end_no_wrl, rhs_change_desc`. Adder columns are 0 when the status is not `apply`/`apply_surrogate`/`review` (keep the fitted values in `fitted_flat_mw`, `fitted_summer_mw`, `fitted_notsummer_mw` for every row).
- `rhs_offsets_monthly.csv`: long table `esoo_constraint, month, mms_median, esoo_median, diff_median, n_cells`.
- `rhs_offsets_monthly.png`: one small panel per constraint, monthly median diff (bars or points) with horizontal line(s) for the chosen adder, title coloured or labelled by status. Load the `dataviz` skill before writing chart code.
- Print a short console summary: counts by status, and the `apply`/`review` rows with their adders.

### 9. Documentation
Add a short section to `README.md` (how to run, what the statuses mean, the sign convention) and a dated note to `PROJECT_CONTEXT.md` with the result counts. Do not edit `PLAN_NEXT_STEPS.md` beyond adding one line under Step 4 pointing to `rhs_offsets.csv`.

## Sanity checks the implementer should run and report
From a quick look at monthly medians (2026-10-27), the rules above should roughly give the following. If the script disagrees by a lot, check the code before tuning thresholds. **Do not tune thresholds to reach these results.**
- Likely `apply`: `N^^V_NIL_1` (ESOO about 180 MW above MMS in all 12 months, so an adder of about -180), `V>>NIL_WBBA_KGBE` and `V>>NIL_WBBA_RCWEKG` (about +140), `S:VS_800` (about +95).
- Likely seasonal or `review`: `V^^N_NIL_1`, `V>>V_NIL_WETX1_R`, `N^^N_NIL_WGLT`, `N>>N_NIL_WASS1_WAIN1`.
- Likely `review` (large gap, surrogate mapping): `V>V_NIL_MLGL2_MLGL1` (about +1,000), `N>>NIL_MGLT1_MRUT1`, `N>>_N_NIL_UTMR1_LTWG1`, `N>>NIL_LINC1_LITO1`, and probably `V>>V_NIL_BAML1_ELML1` (ESOO 350-690 MW above MMS in every month, so about -550, but mapped to `V>>NIL_ELML_BAML2`).
- Likely `no_change`: `V::V_1900` (identical), `N>>N_NIL_DPTX3_DPTX4`, `N>>N_NIL_UTMR1_LTMR1`, `N>>N_NIL_UTMR1_LTMR1_R`, `V>>V_NIL_MRDD1_MRDB2`, `V>>S_NIL_MHNW1_MHNW2_NO_MLRB`, `S>>S_NIL_WEWT1_LKDP1`, `V_NWVIC_GFT1_750` (sign flips between months or small).
- `excluded_dynamic_rhs`: the 4 ROCOF constraints (also note the ESOO data for `S_V_NIL_ROCOF` and `V_S_NIL_ROCOF` stop at Feb 2027).

## Out of scope
Editing the ESOO PLEXOS model (the user does this from `rhs_offsets_to_apply.csv`), applying the adders to the interval RHS series, changing the MMS mapping workbook, and fitting LHS or headroom corrections.
