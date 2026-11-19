# Manual runbook: open workstreams (no Claude needed)

Written 2026-10-28. Background is in `PROJECT_CONTEXT.md`; script details are in `README.md`. Run everything from `C:\Dev\ESOO_2026_constraints` in PowerShell. Always use the project Python with `-X utf8 -I`:

```
.venv\Scripts\python.exe -X utf8 -I scripts\<script>.py
```

## Where things stand
- With-WRL (FY27-33) and no-WRL (summer-fixed re-run, FY31-33) results are loaded and ranked. Summer check passed.
- Shortlist 39, candidate list 49 (43 tier A, 6 tier B): `outputs\final_constraint_list.csv`. Sub-equations: `outputs\final_constraint_subequations.csv`.
- RHS adders from the MMS comparison are fitted: `outputs\rhs_offsets\rhs_offsets_to_apply.csv`.
- Goal: at most 20 constraints in your model, plus Marinus kept in both scenarios.

## Refresh everything (only if result folders or the workbook change)
```
.venv\Scripts\python.exe -X utf8 -I scripts\esoo_results.py ESOO_results        --tag with_wrl
.venv\Scripts\python.exe -X utf8 -I scripts\esoo_results.py ESOO_results_no_WRL --tag no_wrl
.venv\Scripts\python.exe -X utf8 -I scripts\rank_constraints.py --tag with_wrl --max-grp 9
.venv\Scripts\python.exe -X utf8 -I scripts\draft_list.py       --tag with_wrl --max-grp 9
.venv\Scripts\python.exe -X utf8 -I scripts\rank_constraints.py --tag no_wrl   --max-grp 9
.venv\Scripts\python.exe -X utf8 -I scripts\draft_list.py       --tag no_wrl   --max-grp 9
.venv\Scripts\python.exe -X utf8 -I scripts\compare_runs.py
.venv\Scripts\python.exe -X utf8 -I scripts\final_list.py
.venv\Scripts\python.exe -X utf8 -I scripts\compare_versions.py     # what changed vs no_wrl_v1
```
Run the loaders before the rankers. Keep `--max-grp 9` (Grp10/11 are scarcity-distorted).

## Workstream 1: act on candidate-list changes (PLAN_NEXT_STEPS Step 3)
1. Open `outputs\changes_no_wrl_v1_to_no_wrl.csv` and the "what changed" printout from `compare_versions.py`. Note constraints added or removed from the candidate list.
2. **Added: `N>>N_NIL_DPTX3_DPTX4` and `V>>NIL_BUTX1_BUTX2`.** Their Grp5 equations are already extracted in `outputs\new_candidates\` (`N__N_NIL_DPTX3_DPTX4_Grp5.csv`, `V__NIL_BUTX1_BUTX2_Grp5.csv`). Use them in your model. In `outputs\final_constraint_subequations.csv`, filter on those two names; if they have `_G_` sub-equations, switch those on.
3. **Removed constraints:** check each in `final_constraint_list.csv` is genuinely absent and decide if you still want it. `V>>V_NIL_BAML1_ELML1` stays in the model even though it is not in the list.
4. **Equation form** (column `equation_form` in `final_constraint_list.csv`): `Grp5` = WRL-affected, use the Grp5 equation in the frozen (no-WRL) version; `published` = use the latest equation. Only `V>>NIL_SMTX2_SMTX1_R` needs Grp5 plus the `Marinus_1` term (0.7188).
5. **Sub-equations to keep on:** the `_G_` names in `final_constraint_subequations.csv` (authority) and `outputs\subequations_keep_on.txt` (older, subset).
6. Seasonal candidates (11): for the two seasonal WRL-affected ones (`N>>N_NIL_WGANM1_WLJI1`, `V>>NIL_SMTX2_SMTX1_R`) the frozen version uses `NotSummer_Grp5` in all months.
7. Trim to <=20: sort the candidate list by tier then by `outputs\no_wrl\ranking.csv` and `outputs\with_wrl\ranking.csv` rental rank, and cut. Items that need a judgement call: `N>>N_NIL_BASW1` and `V::V_1900` (single-day rental above $50k, possible scarcity artefact), `N^^N_NIL_WGLT` (only defined to Grp2).

## Workstream 2: RHS adders from MMS (apply by hand)
1. (Optional re-run) `compare_to_MMS.py` then `rhs_offsets.py`. Inputs live in `inputs\compare_to_MMS\`.
2. Open `outputs\rhs_offsets\rhs_offsets_to_apply.csv`. Each row: constraint, season (All, Summer, NotSummer), scenario, `adder_mw`, `apply_from`, `apply_to`. **Sign: adder = MMS - ESOO**, so add it to the ESOO RHS.
3. Status guide: `apply` and `apply_surrogate` are safe to use (surrogate = hand-mapped MMS constraint, so check the equations match). `review` rows are flagged: look at the plot in `outputs\rhs_offsets\plots\<constraint>.png` before using. `no_change` and `insufficient_data` get no adder. Every matched constraint now has a plot (in `plots\` and `plots_longrun\`); the green bold title says "NO ADDER RECOMMENDED" with the reason and the rejected best-fit gap (dotted grey line), orange means an adder is recommended.
4. Current `apply` rows: `N^^V_NIL_1` -165, `N::N_NIL_63` +110 Summer / +45 NotSummer, `V>>NIL_WBBA_KGBE` +150. `apply_surrogate`: `N>>N_NIL_WASS1_WAIN1` +430 (to 2028-05-31), `N>>_N_NIL_UTMR1_LTWG1` +565.
5. Use the full-run plots in `outputs\rhs_offsets\plots_longrun\` to check the adder end dates (shaded = adder unvalidated).
6. Open question: `N^^V_NIL_1` / `V^^N_NIL_1` and NSW1-SA1. Neither equation references SA terms, and `N^^V_NIL_1` differs from MMS from day one. Confirming needs the MMS equation history (effective dates, RHS terms). Treat the -165 as provisional until checked.

## Workstream 3: interval RHS series (PLAN_NEXT_STEPS Step 4)
Only possible if interval reporting was on for the ESOO re-run.
1. Put interval RHS (and ideally Price, Activity, Hours Binding) for the candidate constraints into the results folders, both scenarios (with-WRL FY27-33, no-WRL FY31-33).
2. Build one RHS time series per constraint and scenario. Flag gaps and no-limit values (2.4e31).
3. Check summer RHS exists for the 11 seasonal candidates.
4. The Grp2->3 date is Jun 2028 in the ESOO. Keep it, or shift the RHS for the 11 constraints that jump there (mostly NSW `MGLT1`, `MGUT1`, `LTMG1`, `UTMR1`, `LTWG1`; up to +241%).
5. Apply the Workstream 2 adders on top, within their date ranges.
There is no script for the series yet. Interval RHS is also a place to check that your model uses the same weather and demand year as the ESOO.

## Checks still open (from PLAN_NEXT_STEPS)
- Object names in the equations must match your model's generator and battery names. Names that do not match are silently ignored, so export your names and compare against the equation terms.
- `T_ROCOF_3_2` is about 30% of rental and its RHS depends on decision variables: check how much it matters after the swap. The ROCOF RHS is fixed to ESOO output with a flat uplift (your preference).
- Marinus_1 coefficients were fitted with WRL in the network, so they are approximate without it.
- Other Tasmanian constraints in the candidates that are re-weighted at Grp8 without `Marinus_1`: not yet checked.
- Grp-to-project mapping is inferred; only Grp5->6 = WRL is confirmed.

## Key dates (Grp start)
0 Jul-2026, 1 Feb-2027, 2 Dec-2027, 3 Jun-2028, 4 May-2029, 5 Mar-2030, 6 Nov-2030 (WRL), 7 Jul-2031, 8 Dec-2031 (Marinus), 9 Apr-2032, 10 Jul-2033, 11 Jan-2035.

## Folders you must not edit
`outputs\no_wrl_v1\`, `inputs\ESOO_results_no_WRL_v1\` (old no-WRL run, kept for comparison) and `inputs\ESOO_results\` (with-WRL).

## If a script fails
- `No module named 'polars'`: you used the wrong Python. Use `.venv\Scripts\python.exe`.
- Garbled console or encoding error: add `-X utf8`.
- Stale numbers: re-run the loader (`esoo_results.py`) before the ranker.
