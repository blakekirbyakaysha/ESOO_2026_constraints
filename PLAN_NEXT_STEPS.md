# Plan: re-run the no-WRL ESOO with summers fixed, then update the candidate list

Written 2026-10-26 so a fresh Claude session (or you) can pick up. Read `PROJECT_CONTEXT.md` for background and `README.md` for how to run the scripts. This file is the to-do list and the record of what is kept versus redone.

## Why a re-run is needed
In the first no-WRL ESOO run, the Grp5 freeze was done by extending `Grp5`, `Summer_Grp5` and `NotSummer_Grp5`. `Summer_Grp5` is empty (Grp5 = Mar-Oct 2030, no summer), so about 969 seasonal constraints had no equation in summers after Nov 2030. Evidence: seasonal constraints in Dec-Feb after Dec 2030 (FY31-33) bound 0 hours in the no-WRL run against 31,581 hours (97 constraints) with WRL. Non-summer months are close (44,286 vs 53,681 hours).

## Old data is preserved (done 2026-10-26)
| What | Kept at |
|---|---|
| Old no-WRL outputs (daily, summary, ranking, draft_list, helper lists) | `outputs\no_wrl_v1\` |
| Old downstream files (candidate list, sub-equation lists, WRL-affected list, comparison) | `outputs\no_wrl_v1\downstream\` |
| Old raw results (FY27-33, 2.1 GB) | `inputs\ESOO_results_no_WRL_v1\` |
| With-WRL run (not affected by the problem) | `inputs\ESOO_results\`, `outputs\with_wrl\` |

Do not edit or delete the `_v1` folders. The re-run goes to the normal names (`ESOO_results_no_WRL\`, tag `no_wrl`) so the scripts work unchanged.

## Step 1 (you): re-run the no-WRL ESOO with the summer fix
1. In the ESOO model, from Nov 2030 to the end of the run, hold:
   - `Grp5` (single-version constraints) and `NotSummer_Grp5` in non-summer months,
   - **`Summer_Grp4` in summer months (Dec-Feb)**. `Summer_Grp5` stays empty, so do not rely on it.
   - Switch off Grp6-Grp11 (including Summer/NotSummer versions). Leave `Outage` alone.
   - Deactivate the 101 constraints only defined from Grp6 on (`outputs\no_wrl\deactivate_list.csv`) and their `_G_` sub-equations. Keep the 41 sub-equations in `outputs\no_wrl_v1\downstream\subequations_keep_on.txt` on.
2. Run FY31, FY32, FY33 (FY27-FY30 are identical to the with-WRL run, copy them from `inputs\ESOO_results\`). Stop at FY33 (Jun 2033); Grp10/11 are scarcity-driven.
3. If you turn on interval reporting, report RHS (and ideally Price, Activity, Hours Binding) for the ~50 candidate constraints at interval resolution, for both scenarios (with-WRL FY27-33, no-WRL FY31-33).
4. Put the results in `inputs\ESOO_results_no_WRL\<FY>\` (the folder now holds the old results too, since I copied, not moved them: delete or empty it first, the old copy is safe in `inputs\ESOO_results_no_WRL_v1\`).

## Step 2 (Claude or you): load, rank, compare
Commands are in the README quick start. In short:
```
.venv\Scripts\python.exe -X utf8 -I scripts\esoo_results.py ESOO_results_no_WRL --tag no_wrl
.venv\Scripts\python.exe -X utf8 -I scripts\rank_constraints.py --tag no_wrl --max-grp 9
.venv\Scripts\python.exe -X utf8 -I scripts\draft_list.py       --tag no_wrl --max-grp 9
.venv\Scripts\python.exe -X utf8 -I scripts\compare_runs.py                   # with_wrl vs no_wrl
.venv\Scripts\python.exe -X utf8 -I scripts\final_list.py                     # rebuilds the candidate list
.venv\Scripts\python.exe -X utf8 -I scripts\compare_versions.py               # what changed vs no_wrl_v1
```
`compare_versions.py` is the "what changed" report: summer-binding check, per-constraint rental/hours movement (`outputs\changes_no_wrl_v1_to_no_wrl.csv`), shortlist additions/removals, candidate-list additions/removals, tier and equation-form changes.

**First check:** seasonal constraints in Dec-Feb after Dec 2030 should now bind (close to the with-WRL figure). If they still show 0 hours, the Summer timeslice setting did not take; stop and fix that before anything else.

## Step 3 (Claude): act on what changed
For each constraint that moved, decide with the user:
- Added to the candidate list: extract its equation (Grp5 form if WRL-affected, otherwise published; see `equation_form`), note any sub-equations.
- Removed: confirm it can be dropped from the model.
- Tier changes: re-check tier B (single-day rental) items; they depend on price.
- Regenerate: `outputs\subequations_keep_on.txt`, `outputs\wrl_affected_constraints.txt`, `outputs\final_constraint_subequations.csv` (all come from `final_list.py` output).

## Step 4 (Claude): interval RHS (if interval reporting was on)
See also `outputs\rhs_offsets\rhs_offsets.csv` (flat RHS adders from the MMS comparison, `scripts\rhs_offsets.py`).
Turn the interval RHS into one time series per constraint and scenario (with-WRL from the with-WRL run, no-WRL from the no-WRL run). Flag gaps and no-limit values (2.4e31). Check summer RHS for the 11 seasonal candidates is valid. Keep the Jun 2028 (Grp2->3) date as in the ESOO, or shift the RHS for the 11 constraints that jump there (mostly NSW `MGLT1`/`MGUT1`/`LTMG1`/`UTMR1`/`LTWG1`, up to +241%).

## What does NOT need redoing (keep)
These do not depend on the no-WRL results run:
- `cache\` (workbook-derived), the with-WRL loading, ranking and shortlist (`outputs\with_wrl\`).
- WRL / Marinus flags per constraint (`grp_flags()`), `plan.csv`, `drop_list.csv` (27 WRL-only), `deactivate_list.csv` (101), `freeze_grp5_list.csv` (486), `line_edits.csv` (interconnector-only edits).
- The rules for equation form: 24 of the current 50 take the Grp5 equation (WRL-affected), 26 as published; only `V>>NIL_SMTX2_SMTX1_R` needs Grp5 + the `Marinus_1` term (0.7188). The 4 other Marinus constraints use their published equations (the 2 Tasmanian ones also get re-weighted at Grp8, so do not use Grp5 for them).
- Scripts: `esoo_results.py`, `rank_constraints.py`, `draft_list.py`, `final_list.py`, `compare_runs.py`, `compare_versions.py`, `no_wrl_plan.py`, `no_wrl_line_edits.py` (all run under `-X utf8 -I`).

## What DOES need redoing after the re-run
Depends on the no-WRL results: `outputs\no_wrl\*` (daily, summary, ranking, draft_list), the compare output, `final_constraint_list.csv` membership and tiers, `final_constraint_subequations.csv`, `subequations_keep_on.txt`, `wrl_affected_constraints.txt`, `frozen_missing_terms.csv`, the interval RHS series. Expect most of the list to be unchanged; the changes should be concentrated in seasonal constraints that bind in summer.

## Decisions already made (do not re-litigate)
- Method: global freeze by timeslice (targeted per-constraint edit abandoned: about 487,000 properties differ and the XML is 1.4 GB). Per-constraint editing is only for the ~24 WRL-affected constraints in the user's own model.
- Marinus is kept in the user's own model, in both scenarios. The no-WRL ESOO run excludes it (this only affects the ranking in Grp8-9).
- BASW1 and the sub-regional-demand constraints are included; the user can model them. Tier A = union of shortlists, tier B = single day >= $1,000 (review).
- The user's own model will have two versions of each WRL-affected constraint (frozen / not frozen) switched by a scenario. The 2 retired constraints (`V>>NIL_WBBA1`, `V>>V_NIL_WBBA1_RCKESS1`) are off from Nov 2030 in the with-WRL version. Only 2 of the 24 are seasonal (`N>>N_NIL_WGANM1_WLJI1`, `V>>NIL_SMTX2_SMTX1_R`); their frozen version uses `NotSummer_Grp5` for all months.
- The 50 objects missing from 4 frozen equations are existing plants added at the WRL step, so freezing correctly excludes them (`outputs\no_wrl\frozen_missing_terms.csv`).
- The user plans to fix the RHS from interval ESOO output. They are adjusting Grp timings in their own model to match their network assumptions.

## Open items
- Grp-to-project mapping is inferred (only Grp5->6 = WRL is confirmed).
- RHS depends on ESOO dispatch and the reference year; check the user's model uses the same weather/demand year.
- ROCOF constraints (`T_ROCOF_3_2`, `T_ROCOF_1`, `S_V_NIL_ROCOF`, `V_S_NIL_ROCOF`): RHS depends on decision variables, so a fixed profile is an approximation. Check how much `T_ROCOF_3_2` (about 30% of rental) matters after the swap.
- Check object names in the equations match the user's model (silently ignored if not). Needs an export of their generator and battery names.
- `N>>N_NIL_BASW1` and `V::V_1900` have single-day rentals above $50k (possible scarcity artefact). `N^^N_NIL_WGLT` is only defined to Grp2.
- Marinus_1 coefficient values were fitted with WRL in the network, so they are approximate in the no-WRL case.
- Still to check: whether any other Tasmanian constraints in the 50 are re-weighted at Grp8 without carrying `Marinus_1`.
