# ESOO 2026 constraint selection for Victoria

Tools to analyse PLEXOS results for the AEMO 2026 ESOO network constraints and pick the subset worth moving into a Victorian price model that has WRL (Western Renewables Link) and VNI West removed or delayed. See `PROJECT_CONTEXT.md` for the background, findings and decisions.

## Layout

| Path | What it is |
|---|---|
| `inputs\` | Everything the scripts read. Nothing in here is generated. |
| `inputs\ESOO2026 Constraints Details.xlsx` | AEMO constraint equations |
| `inputs\esoo_node_memberships.csv` | Generator / battery to node and region |
| `inputs\constraint_objects.csv` | PLEXOS constraint object list; `Category` = `NetworkConstraints` (real) or `NetworkSubEquations` |
| `inputs\constraint_changes_by_grp.csv` | What changes in each constraint at each Grp step (derived earlier) |
| `inputs\ESOO_results\<FY>\` | PLEXOS result CSVs, with-WRL run, one folder per financial year |
| `inputs\ESOO_results_no_WRL\<FY>\` | Same, no-WRL run (FY27-30 copied from with-WRL, FY31-33 re-run with the summer fix) |
| `inputs\ESOO_results_no_WRL_v1\` | Superseded first no-WRL run, kept for `compare_versions.py`. Do not edit |
| `inputs\compare_to_MMS\` | MMS actuals, 2027 ESOO output and the equation-mapping workbook for `compare_to_MMS.py` |
| `inputs\mapping\` | Equation mapping workbooks used to build the MMS mapping (`scripts\mapping_tools\`) |
| `inputs\raw\` | Raw AEMO dumps (`Network_constraints.txt`, `Network_subeqations.txt`, `Mapping.xlsx`, `ESOO_subequations.xlsx`) not read by the main scripts |
| `scripts\` | The scripts described below; `scripts\mapping_tools\` holds the one-off MMS mapping scrapers |
| `cache\` | Generated from the workbook (safe to delete and rebuild) |
| `outputs\<tag>\` | Generated per run, e.g. `with_wrl`, `no_wrl`; also `rhs_offsets`, `mms_comparison` |

Result folders can be passed to `esoo_results.py` by bare name (`ESOO_results_no_WRL`); it looks in `inputs\` if the name is not found in the current folder.

## Setup

A local virtual environment is in `.venv` (polars, pyarrow, openpyxl, fastexcel). To recreate it:

```
python -m venv .venv
.venv\Scripts\python.exe -m pip install polars pyarrow openpyxl fastexcel matplotlib
```

## Quick start: re-run everything yourself

Open a PowerShell in the project folder (`C:\Dev\ESOO_2026_constraints`) and run these. Each takes seconds to a minute; step 1 is only needed if the workbook changes. The scripts can be run exactly as written (`-X utf8` avoids console encoding errors; `-I` is fine).

```
# 1. Only if the ESOO workbook changed (minutes): rebuild cache/
.venv\Scripts\python.exe -X utf8 -I scripts\build_lhs_cache.py

# 2. Load each run's results (re-do whenever you add or replace result folders)
.venv\Scripts\python.exe -X utf8 -I scripts\esoo_results.py ESOO_results        --tag with_wrl
.venv\Scripts\python.exe -X utf8 -I scripts\esoo_results.py ESOO_results_no_WRL --tag no_wrl

# 3. Rank, then build the shortlist, for each run
.venv\Scripts\python.exe -X utf8 -I scripts\rank_constraints.py --tag with_wrl --max-grp 9
.venv\Scripts\python.exe -X utf8 -I scripts\draft_list.py       --tag with_wrl --max-grp 9
.venv\Scripts\python.exe -X utf8 -I scripts\rank_constraints.py --tag no_wrl   --max-grp 9
.venv\Scripts\python.exe -X utf8 -I scripts\draft_list.py       --tag no_wrl   --max-grp 9

# 4. Compare the two runs (years present in both)
.venv\Scripts\python.exe -X utf8 -I scripts\compare_runs.py
```

Results to read: `outputs\<tag>\draft_list.csv` (the shortlist: rows where `shortlist_reason` is `core` or `year_specific`), `outputs\<tag>\ranking.csv` (every binding Victorian-relevant constraint) and `outputs\compare_with_wrl_vs_no_wrl.csv`.

Things that catch people out:
- **Folder layout.** Each run folder has one sub-folder per financial year, named for the year it ends (FY27 = `2027`), holding `Price.csv`, `Rental.csv`, `Hours Binding.csv` and so on. A year folder missing from a run just isn't loaded.
- **`--max-grp 9` is deliberate.** Grp10/11 (Jul 2033 on) are scarcity-driven in the ESOO (only committed and anticipated generation), so they distort rankings. Drop the flag only to look at them.
- **Compare like with like.** `compare_runs.py` only uses years present in both runs, but the shortlists in `draft_list.csv` use every year in that run. If one run has fewer years, its shortlist isn't comparable.
- **`draft_list.csv` has every ranked row**, not just the shortlist. Filter on `shortlist_reason`.
- **Re-run step 2 before 3** after changing result files, or the rankings use stale data.
- If a script says `No module named 'polars'`, you're not using the project Python: always call `.venv\Scripts\python.exe`.

## No-WRL run

The no-WRL run is the ESOO model with WRL removed, done by freezing the network at the Grp5 equations from Nov 2030 (the Grp6 start, which is where WRL enters). Marinus (Grp8) never appears, and VNI West has no ESOO step so is already out. See `PROJECT_CONTEXT.md` for why.

**How it is built in PLEXOS (global freeze via timeslices):**
1. Extend the Grp5 timeslices so the frozen equations are active from Nov 2030 to the end of the horizon: `Grp5` (single-version constraints) and `NotSummer_Grp5` in non-summer months, and **`Summer_Grp4` in summer months (Dec-Feb)**. `Summer_Grp5` is empty (Grp5 is Mar-Oct 2030, so it has no summer), so extending it leaves every seasonal constraint with no equation in summer. The first no-WRL run made this mistake: seasonal constraints bound 0 hours in Dec-Feb after Dec 2030, against 31,581 hours with WRL. Summer_Grp4 and NotSummer_Grp5 have near-identical LHS (max coefficient difference 0.0001 for the candidates).
2. Deactivate the Grp6-Grp11 timeslices (including Summer/NotSummer versions). Leave `Outage` alone.
3. Deactivate the 101 constraints that only exist from Grp6 on (`outputs\no_wrl\deactivate_list.csv`: includes the 27 `V>>WVic_*` WRL constraints), and their `_G_` sub-equations.
4. Run one year at a time into `ESOO_results_no_WRL\<FY>\`. Only FY31-FY33 differ from the with-WRL run. Copy FY27-FY30 from `ESOO_results\` instead of re-running, after checking that one re-run year (e.g. FY30) matches.

**Limits:** every constraint is frozen, not only the WRL-affected ones, so new generators and batteries added after Nov 2030 are missing from the equations (NSW/Qld/SA constraints can look looser than they are). Grp10/11 stay scarcity-driven.

**Helper scripts and lists** (only needed if you want to do a targeted, per-constraint version instead of the global freeze, which turned out to be too many properties to edit by hand):

| File | What it is |
|---|---|
| `scripts\no_wrl_plan.py` -> `outputs\no_wrl\plan.csv` | Which constraints WRL drops / restores / changes |
| `outputs\no_wrl\drop_list.csv` | 27 WRL-only constraints |
| `outputs\no_wrl\deactivate_list.csv` | 101 constraints first defined at Grp6 or later |
| `outputs\no_wrl\freeze_grp5_list.csv` | 486 constraints a targeted freeze would hold at Grp5 (WRL-affected, plus Marinus-only ones) |
| `scripts\no_wrl_line_edits.py` -> `outputs\no_wrl\line_edits.csv` | 7,422 interconnector coefficient edits (Grp6-11 back to Grp5) for those constraints |
| `scripts\compare_runs.py` | Compares two loaded runs and their shortlists |
| `scripts\compare_versions.py` | What changed between two versions of the same run (default `no_wrl_v1` vs `no_wrl`): summer-binding check, ranking movers, shortlist and candidate-list changes |

## Candidate list for your own model

After both runs are ranked and have a `draft_list.csv`:

```
.venv\Scripts\python.exe -X utf8 -I scripts\final_list.py            # --spike 1000 sets the tier B single-day rental threshold
```

Writes `outputs\final_constraint_list.csv` (tier A = union of both runs' shortlists; tier B = single-day rental >= `--spike`, which depends on price so review it) and `outputs\final_constraint_subequations.csv` (the `_G_` sub-equations each constraint needs). `equation_form` says whether to take the Grp5 equation (WRL/Marinus-affected) or the latest published one; `review_note` flags single-day rental > $50k.

## Compare ESOO constraints with MMS actuals

Place the actual constraint data, 2027 ESOO output, and populated equation mapping workbook in `inputs\compare_to_MMS\`, then run:

```
.venv\Scripts\python.exe -X utf8 -I scripts\compare_to_MMS.py
```

The default inputs are `inputs\compare_to_MMS\Constraint_Data.csv`, `inputs\compare_to_MMS\ESOO_2027_network_constraints.csv`, and `inputs\compare_to_MMS\Equation_mapping_populated_BK_manual.xlsx`. The script uses the mapping workbook's `Output` value to match an ESOO constraint to its MMS name. Paths can be overridden with `--actuals`, `--esoo`, `--mapping`, and `--output`.

MMS data are restricted to the latest 12 calendar months available, then averaged to 30-minute interval-ending LHS/RHS values. The hourly ESOO values are held constant across their two 30-minute intervals. RHS values with absolute magnitude at least `1e20` are treated as no-limit/off sentinels and excluded from RHS charts and RHS/headroom metrics. For each matched constraint the script writes to `outputs\mms_comparison\`:

- `matched_constraints.csv`, including mappings missing from either data source.
- `comparison_summary.csv`, with LHS/RHS means and bias, MAE, RMSE, correlation, the same metrics for headroom (`RHS - LHS`), actual binding share, and point counts. Error metrics use only timestamps available in both sources; the binding share marks a half-hour interval if any of its MMS 5-minute records is binding.
- A matched 30-minute time-series CSV and PNG per constraint. The PNG separates LHS and RHS and marks the date overlap.
- LHS and RHS profile PNGs per constraint: annual, financial-quarter (Q1 = Jul-Sep), and calendar-month average daily profiles, with ±1 standard deviation shading.

Each run overwrites the summary and match tables and refreshes generated time-series/profile files for every constraint in the mapping workbook, removing prior generated files for those constraints that are no longer matched. Other files in the output folder are left alone. The plots retain each source's own dates; they do not imply the non-overlapping months are contemporaneous. Check the reported overlap and interval counts before interpreting error metrics. The sample data currently span Oct 2025-Sep 2026 for MMS and FY2027 for ESOO, so direct time-aligned metrics use only their shared period. These metrics are descriptive validation aids, not a substitute for checking constraint direction, scaling, equation equivalence, and binding behavior in the target market model.

## RHS adders from the MMS comparison (`rhs_offsets.py`)

```
.venv\Scripts\python.exe -X utf8 -I scripts\rhs_offsets.py
```

Reads the per-constraint `outputs\mms_comparison\*_30min.csv` files (run `compare_to_MMS.py` first), pairs MMS and ESOO RHS by month-of-year and half-hour slot (medians), and decides per constraint whether a flat RHS adder (none, one value, or Summer and NotSummer values) is supported. **Sign: `adder = MMS - ESOO`**, added to the ESOO RHS (opposite to the `*_bias_esoo_minus_mms` columns). Thresholds are constants at the top of the script. Outputs in `outputs\rhs_offsets\`: `rhs_offsets_to_apply.csv` (working list: adder, season, scenario, apply_from/apply_to), `rhs_offsets.csv` (all metrics per constraint), `rhs_offsets_monthly.csv`, `rhs_offsets_monthly.png`, and `plots\<constraint>.png` (MMS actual, ESOO, and ESOO + adder, as a timeline and by month of year, for each constraint with an adder), and `plots_longrun\<constraint>.png` (ESOO daily-mean RHS over the full run with and without the adder, with-WRL on top and no-WRL below, MMS actuals for reference and Grp starts marked).

Statuses: `apply` (passed every test, constraint-ID match), `apply_surrogate` (passed, hand-mapped MMS constraint, no flags), `review` (flagged: large adder on a surrogate mapping, wide/bimodal MMS RHS, diurnal disagreement, or the RHS changes at Grp1 inside the fit window so only Jul-Jan was fitted), `no_change` (failed materiality, sign or leave-one-month-out test), `excluded_dynamic_rhs` (ROCOF constraints), `insufficient_data`.

Each adder applies from 2026-07-01 until the first RHS change that moves the ESOO RHS level materially. Candidate changes come from `constraint_changes_by_grp.csv`, where `rhs_any` is true when any RHS term is added, removed or has a changed coefficient between consecutive Grps (LHS-only changes do not count; fleet-driven term changes do). A candidate ends the adder only if the step in the ESOO daily RHS across that Grp start (median of the 30 days after minus the 30 days before, from `outputs\<tag>\daily.parquet`; the daily RHS is the sum of 24 hourly values, so it is divided by 24 to give MW) exceeds `max(20 MW, 25% of the adder)`, or if there is no ESOO RHS data around it. Smaller changes are listed in `rhs_change_desc` as ignored. `end_with_wrl` / `end_no_wrl` use this rule (the no-WRL run's own RHS is used and WRL-affected constraints ignore changes at Grp6+ in both scenarios, because those changes are the WRL effect ESOO models; both scenarios then carry the same adder and end date, so the with/no-WRL difference stays ESOO's own); `end_*_structural` give the older rule (first `rhs_any` change, whatever its size). The step is seasonally adjusted: the same before/after difference one year earlier (else later, if that window holds no other Grp start) is subtracted, because ESOO RHS has a strong seasonal switch that otherwise fakes steps at Grp starts. The same test decides the fit window: if the Grp1 (Feb 2027) change is material, the offset is fitted on Jul-Jan only (the equation actually measured; `review`, short fit) and ends at Grp1. There are no separate post-change fits, because pairing MMS 2025-26 with ESOO 2027 after a change would cancel real ESOO change. Fits under 9 months are capped at `review`. A `review` flag "gap varies by month" is raised when the P10-P90 spread of the monthly gaps exceeds the adder itself (`SPREAD_FRAC`), i.e. a flat value is not representative. Where an adder ends, the long-run plots shade the period as "offset unvalidated". ROCOF constraints are no longer excluded, since the market model fixes the RHS to the ESOO outcome; `S_V_NIL_ROCOF` and `V_S_NIL_ROCOF` have ESOO RHS values only for Jul 2026-Jan 2027, so they are fitted on those 7 months (the 9-month minimum is waived), marked `review`, and the adder ends 2027-01-31. The step is a rough 30-day level measure, and seasonal effects at the boundary are not removed. Tolerances (`STEP_FRAC`, `STEP_DAYS`) are constants at the top of `scripts\rhs_offsets.py`.

**Changes 2026-10-28 (after manual review, `inputsdder_review.csv`):** (1) An ESOO RHS *uprating* (positive step) no longer ends or reduces the adder: the adder is a representation gap measured on today's network, so it stays on top of the lift; only a downrating (or no data around the Grp) ends it. Small/uprating steps are listed in `rhs_change_desc`. (2) Data cleaning before fitting: `SWAMP_CAP` drops MMS RHS above a cap (V>>NIL_SMTX2_SMTX1_R), and `SIPS_CONSTRAINTS` (DDSM1_DDSM2, MRDD1_MRDB2) drop Nov-Mar in both sources. (3) Every constraint is also fitted on the low end (P10 of each month/slot cell, where constraints bind). If the median fit gives no adder but the P10 fit passes the same tests, the P10 adder is recommended as `review` (`fit_basis` = P10); if a median adder sits well above the P10 gap it is flagged "optimistic at low end". `tail_p10_gap_mw` is reported for all. (4) `lhs_bias_pct` (ESOO - MMS LHS as % of MMS RHS, Jul-Sep overlap) is reported, and over 15% flags that an RHS adder may not be the right fix. (5) The review file clears an accept/reject decision, with a note in the comment, when the suggestion it was made on has changed. (6) The Grp1 fit window now ends the adder at Grp1 if the Grp1 step is negative or has no data (it was inconsistent with the end rule before). The residual-after-uprating logic was removed.

**Further changes 2026-10-28:** (7) `EXCLUDED` in `scripts
hs_offsets.py` lists constraints the user has ignored/disabled (V>>NIL_SMTX2_SMTX1_R, N>>NIL_LINC1_LITO1, N>>N_NIL_DPTX3_DPTX4); they get no adder and a `reject` in the review file. (8) `SIPS_CONSTRAINTS` (DDSM1_DDSM2, MRDD1_MRDB2) get two segments, `SIPS` (Nov-Mar, assumed to end 2032-03-31, `SIPS_END_GRP`) and `NonSIPS` (Apr-Oct), each fitted on its own months (minimum 3, so `review`); MMS RHS above `SWAMP_CAP` (5,000 MW) is dropped first. `rhs_offsets_to_apply.csv` has a `months` column for these. (9) `headroom_gap_mw` fits MMS - ESOO on headroom (RHS - LHS), i.e. the RHS adder that would reproduce MMS headroom given ESOO's own LHS; information only. (10) `inputsdder_review.csv` has `review_status` / `what_changed` per constraint: NO CHANGE, NO CHANGE with a new warning, RE-REVIEW (a decision made on a suggestion that has since changed is moved to `previous_decision`), NEW, or EXCLUDED. A flag stays until you act: enter a decision on a RE-REVIEW row, or type `y` in `reviewed_ok` for any pending row. Do not edit `reviewed_suggestion` / `reviewed_reason`. (11) DDSM1_DDSM2 / MRDD1_MRDB2 SIPS segments are not fitted: neither binds in MMS during Nov-Mar and ESOO binds them only ~0.2-0.5% of those hours, so the recommendation is `action = set_rhs` to `SIPS_RHS_MW` (10,000 MW) for Nov-Mar to 2032-03-31 (`rhs_offsets_to_apply.csv` has `action` and `rhs_value_mw` columns). A blank `decision` means the suggestion is applied as shown; `reject` drops the constraint, `override` replaces adder MW only. (12) `util_adder_p95_mw` / `util_adder_p99_mw` (and `util_matched_adder` in the review sheet): the RHS adder that makes the upper tail of ESOO utilisation (LHS/RHS) match MMS. It uses LHS and RHS together, so a higher ESOO LHS is credited against a higher RHS. Diagnostic: use it to sanity-check an RHS-only adder where `lhs_bias_pct` is flagged.

## Workflow

Run everything from the project folder.

1. **Drop results in.** One folder per year, named for the end of the financial year (FY27 = Jul 2026 to Jun 2027):
   ```
   inputs/ESOO_results/2027/Hours Binding.csv
   inputs/ESOO_results/2027/Price.csv
   ...
   ```
   Each CSV has `Name, Year, Month, Day, Period, Value` (daily, one row per constraint per day). Recognised files: Hours Binding, Price, Rental, Violation, Penalty Cost, Activity, RHS, Slack. Missing files are skipped. Hours Active is ignored (always 24).

2. **Build the constraint cache** (once, or when the workbook changes; takes a few minutes):
   ```
   .venv\Scripts\python.exe scripts\build_lhs_cache.py
   ```
   Writes `cache/eq_meta.parquet` and `cache/lhs_terms.parquet` (every non-zero LHS term, including the Outage_Constraints sheet).

3. **Load and summarise a run:**
   ```
   .venv\Scripts\python.exe scripts\esoo_results.py --tag with_wrl
   ```
   Reads every year folder under `ESOO_results/` (or pass another root as the first argument). Writes to `outputs/with_wrl/`:
   - `daily.parquet`: constraint x day, all properties joined, plus the Grp in force that day.
   - `summary_by_constraint_fy_grp.csv`: hours and days binding, max price, rental, violation, penalty cost, with Victorian tags.

   Use a different `--tag` for each run (for example `no_wrl`), and point the first argument at that run's results folder.

4. **Rank the constraints:**
   ```
   .venv\Scripts\python.exe scripts\rank_constraints.py --tag with_wrl
   ```
   Options: `--cover 0.9` (cumulative rental share), `--peak-day 250` (any single day's rental), `--price 50` (daily-mean shadow price, $/MW). Prints how many constraints each test selects and a sensitivity table, and writes:
   - `ranking.csv`: every Victorian-relevant constraint that binds, ranked by rental across all years, with the selection tests and per-FY rental.
   - `ranking_wrl.csv`: the subset related to WRL or Marinus.

   Add `--max-grp 9` to ignore Grp10/11 (Jul 2033 on), which are scarcity-distorted in the with-WRL run (ESOO has only committed and anticipated generation). The rental cover uses positive rental only.

5. **Draft shortlist** (robust to scarcity-inflated years):
   ```
   .venv\Scripts\python.exe scripts\draft_list.py --tag with_wrl --max-grp 9 --n 15
   ```
   Ranks Victorian-relevant constraints by mean per-FY rental share, hours binding and total rental (core, `--n 15`), then adds any constraint inside the 90% cumulative rental cover of any single FY (`--fy-cover`), so constraints that bind heavily in only some years are kept, up to `--cap 40` in total. Writes `outputs/<tag>/draft_list.csv` with `shortlist_reason` = core / year_specific.

## How it works

- **Victorian-relevant** means the constraint has a Victorian generator or battery (region taken from `esoo_node_memberships.csv`) or one of `VIC1-NSW1`, `V-SA`, `V-S-MNSP1`, `T-V-MNSP1`, `NSW1-SA1`, `Marinus_1` on its LHS.
- **Grp** is derived from the date using the ESOO Timeslice dates. PLEXOS result names carry no Grp.
- **Sub-equations** (`NetworkSubEquations` in `constraint_objects.csv`) sit on the RHS tied to decision variables and are not real constraints, so they are excluded from ranking. Most have `_G_<n>` suffixes, but 87 do not, so the file is the authority, not the name. Result names missing from the file are reported with a warning and kept unless they match `_G_<n>`. `constraint_base` removes the `_G_<n>` suffix so names match the workbook.
- **Ranking** is across all years, so a constraint that binds rarely but hard is still caught. A constraint is selected if any of these hold: it is inside the rental cumulative cover; one day alone reaches the peak-day rental; the shadow price reaches the price threshold; it has any violation.
- **WRL / Marinus flags:** `wrl_new` (first defined at Grp6), `wrl_retired` (last defined at Grp5), `wrl_lhs_change` (LHS term added, removed or changed by more than 0.05 at Grp5 to 6), `marinus_added` (`Marinus_1` added at Grp8).
- RHS and Slack values of 2.4e31 mean no limit and are set to null.

## Caveats

- Price and rental are daily means, so short spikes inside a day are smoothed.
- One reference year can miss constraints that bind rarely. A second reference year is planned.
- Summer and NotSummer versions of a constraint are not separated in the Victorian tags.
- A with-WRL run cannot show how the WRL-era constraints would rank without WRL; that is what the no-WRL run (above) is for.
- `N>>N_NIL_BASW1` shows a single-day rental of about $974,000 in FY33, which looks like a scarcity or violation artefact. Check it before keeping it on a shortlist.
- The thresholds are starting defaults and the model's constraint cap is not yet known.

## Changes 2026-10-29
- `scripts/equation_check/` (fetch_mms_equations.py with the global python, then compare_equations.py and classify_equations.py with the venv) compares ESOO and MMS equations and writes `outputs/equation_check/equation_check_summary.csv`.
- `rhs_offsets.py` scales the MMS RHS by the ESOO/MMS coefficient ratio where it is outside 1 +/- 0.05, adds an `equation_class` column to `inputs/adder_review.csv`, and draws a "why this adder (or none)" panel on every chart. Reviewer comments no longer appear in chart titles.
- `scripts/build_final_package.py` writes `outputs/FINAL/` (final adders, ESOO equation edits, out-of-model seasonal adjustment, close-out notes).
