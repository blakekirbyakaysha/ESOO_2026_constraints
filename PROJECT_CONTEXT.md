# ESOO 2026 constraints: project context

Written for later Claude sessions (and the user) to pick up the work. Last updated 2026-10-16. Usage instructions for the scripts are in `README.md`; this file holds the reasoning, findings and decisions.

## Goal
Model Victoria **without WRL (Western Renewables Link) and VNI West**, because those projects are at risk, so that Victorian prices reflect a world where they slip or are cancelled. The PLEXOS model cannot hold all the ESOO constraints, so a **subset of the most important constraints** must be moved across. Focus: constraints with Victorian DUIDs on the LHS or Victorian-relevant interconnectors. The aim is to model Victoria better in general, not only WRL-related constraints, but WRL-related ones (and Marinus) get closer attention and are reported separately.

VNI West is an augmentation to VIC1-NSW1. NSW1-SA1 is also relevant to Victoria. Victorian-relevant interconnectors used throughout: `VIC1-NSW1`, `V-SA`, `V-S-MNSP1` (Murraylink), `T-V-MNSP1` (Basslink), `NSW1-SA1`, `Marinus_1`.

## Source files
- `ESOO2026 Constraints Details.xlsx` (58 MB). Sheets: Disclaimer, Information, Constraint_equations, Outage_Constraints (106 rows, same layout but LHS from column F, `timeslice` = `Outage`), Timeslice.
  - Constraint_equations: 32,820 rows (constraint x timeslice), 2,103 unique constraint IDs. Columns A-F: constraint, timeslice, description, penalty, rhsTerms, state (always empty). From column G: 1,076 LHS coefficient columns (8 LINE interconnector flow terms, 642 GENERATOR, 213 BATTERY Generation, 213 BATTERY Load). Battery headers are duplicated by name, so row 2 (type) disambiguates.
  - `rhsTerms` is a text block already in PLEXOS form (`termId, groupId, termType, objectId, coef, ...`). It changes even where LHS DUID coefficients don't, because it also reflects fleet changes.
  - Timeslices: `GrpN` (1,070 constraints single version) and `Summer_GrpN` / `NotSummer_GrpN` (1,033 seasonal pairs). Penalty constant ($500,000).
  - Grp start dates: 0 Jul-2026, 1 Feb-2027, 2 Dec-2027, 3 Jun-2028, 4 May-2029, 5 Mar-2030, 6 Nov-2030, 7 Jul-2031, 8 Dec-2031, 9 Apr-2032, 10 Jul-2033, 11 Jan-2035 (ends Jul-2036). All start on the 1st of a month.
- `constraint_objects.csv` (user-supplied PLEXOS export, 3,116 objects): `Category` is `NetworkConstraints` (2,207, real) or `NetworkSubEquations` (909). Authoritative classifier. In the FY27 results (2,880 names) 1,971 are real constraints and 909 are sub-equations; the 236 file entries missing from FY27 results are all real constraints (expected to appear in later Grps, e.g. `N>>Hume_*`).
- `esoo_node_memberships.csv` (user-supplied): Generator.Nodes / Battery.Nodes -> node and region (`Child Category` = VIC/NSW/QLD/SA/TAS). Used to flag Victorian DUIDs.
- `constraint_changes_by_grp.csv`: 9,254 rows, one per constraint x season x Grp transition with added/removed/changed LHS and RHS terms. Used for WRL / Marinus flags.
- `ESOO_results/<FY>/*.csv`: PLEXOS outputs from the user's baseline run (ESOO constraints as published, WITH WRL), run one year at a time. FY27 = Jul-2026 to Jun-2027. A no-WRL run will follow ("might be harder to do properly").

## Findings: what changes by Grp (material = coefficient change > 0.001 or any term added/removed)
Largest steps are Grp0->1, 2->3, 5->6, 7->8, 10->11. Grp1->2 and Grp8->9 are almost nothing.

| Transition | Summary |
|---|---|
| 0->1 | `NSW1-SA1` term added to ~768 equations; V-SA / V-S-MNSP1 / VIC1-NSW1 re-weighted |
| 1->2 | 21 constraints, 4 new `S:VN_HIC+PEC*`, tiny RHS tweaks |
| 2->3 | Heavy VIC1-NSW1 / NSW1-SA1 re-weighting, V-S-MNSP1 added, Snowy (TUMUT3, SHGEN) terms, new `N>>Hume_*` |
| 3->4, 4->5, 6->7 | Mostly NSW1-QLD1 / N-Q-MNSP1 and Qld pumped hydro; 22 new `Q>>NIL_*` at 4->5 |
| **5->6** | **Western Victoria (WRL, confirmed by user):** 27 new constraints all Victorian (`V>>WVic_*` etc.), 40 retired (25 Victorian with new counterparts, 15 Qld `Q_NIL_STRGTH_*`), Ballarat renamed `3BAL220B` in 21 descriptions, 326 constraints shift on VIC1-NSW1, 304 on V-SA, 369 on V-S-MNSP1 (up to ~0.85), 223 constraints move > 0.05. ~450 NSW/Qld/SA constraints change only in PLEXOS terms (fleet changes, not network). The file's `material` flag is true for 995 constraints at this step, so it is too broad to define "WRL-related". |
| **7->8** | `Marinus_1` term added to 224 equations (141 Victorian, 35 Tasmanian), coefficients 0.07-1.0 (median ~0.38), mostly Latrobe / eastern Vic. Otherwise Grp8 is about Grp7 + Marinus. |
| 9->10 | North Qld: Ross-Strathmore 275 kV replaced by cut-in at `4NQ_275` (low confidence). No interconnector change. |
| 10->11 | New England REZ-like network; VIC1-NSW1, NSW1-QLD1, N-Q-MNSP1, NSW1-SA1 re-weighted in ~76 constraints > 0.05; 104 Victorian constraints change slightly. |

Overall: 327 constraints never change materially, 1,776 do.

Project-to-Grp mapping is **inferred** from constraint names, not stated in the workbook. Only Grp5->6 = WRL is user-confirmed. **No VNI West step exists in the ESOO set**, so Grp0-5 Victorian equations are effectively no-WRL, no-VNI-West. This is an inference; verify against AEMO's ESOO augmentation list.

## Open inconsistency
The user's list of projects in their model "not accounted for in any ESOO group" includes WRL (x2), VNI West (x3), New England REZ Network Infrastructure Project, plus Sydney Ring North, CQ-NQ Option 3/4, T2, N9b 2a, Copperstring, V8, N5 Option 2 (3rd Dinawan transformer), DN1, Central-West Orana REZ Expansion, Borumba PHES augmentation, SEVIC1. WRL appears in ESOO Grp6 and New England REZ looks like Grp11, so list entries probably are different stages or timing. Unresolved. None have equations in the workbook; they stay unrepresented. N5, V8 and SEVIC1 could touch Victorian limits.

## Results data: what the files are
- Per-property CSVs (`Name, Year, Month, Day, Period, Value`), one row per constraint per day (Period always 1). FY27 run has 2,880 constraints x 365 days. Properties: Activity, Hours Active, Hours Binding, Penalty Cost, Price (shadow price, daily mean), Rental, RHS, Slack, Violation.
- Hours Active is always 24 (useless). RHS / Slack of 2.4e31 mean "no limit" (set to null). Price is a daily mean, so intra-day spikes are smoothed.
- The result names carry **no Grp**; Grp is derived from the date.
- **Sub-equations are not real constraints** (user-confirmed: they sit on the RHS tied to decision variables). `constraint_objects.csv` classifies them. The `_G_<n>` suffix (822 names; the `groupId` in `rhsTerms`) had no false positives but missed 87 sub-equations without the suffix (`X_CHK_*`, `SA_METRO_GEN_ON`, `X_CS_FLOOR`, ...); none bind. Sub-equations are excluded from ranking. They never bind or earn rental. The only sub-equation violation in FY27 is `X-T_SOU_G_34` (Tasmanian, 90 units); real-constraint violation (108) is on Queensland `Q>>Q_BBBB1/GGBB1...` constraints, nothing Victorian. `constraint_base` strips `_G_<n>` suffixes (chained too) to match the workbook.
- Other tags: 104 names from the Outage_Constraints sheet are included in the LHS cache so they are tagged; a few model-only constraints stay untagged (none bind).

## Selection approach (decisions so far)
- Rank **across all years**, not per year, so that irregular-but-severe constraints are captured. Per-FY rental columns are kept in `ranking.csv`.
- A constraint is selected if **any** test passes: (1) rental cumulative cover of Victorian-relevant rental (default 90%), (2) any single day's rental >= `--peak-day` (default 250), (3) daily-mean shadow price >= `--price` (default $50/MW), (4) any violation. The "top-5-days share" test was tried and dropped (it picked up nearly every low-day constraint).
- The 90% cover may need revising if too many constraints fall inside it. The model's constraint cap is **unknown**; the user wants to see how many fall out first, then decide.
- WRL / Marinus-related constraints are reported separately (`ranking_wrl.csv`): `wrl_new` (first Grp6), `wrl_retired` (last Grp5), `wrl_lhs_change` (LHS add/remove/change >0.05 at Grp5->6), `marinus_added` (`Marinus_1` added at ->Grp8).
- Victorian-relevant = a VIC generator/battery (per node region) with a non-zero LHS coefficient, or one of the six interconnectors on the LHS. Tags are per base constraint across all its timeslices (Summer/NotSummer not separated).

### FY27 (with-WRL) preliminary result
2,880 constraints, 307 ever bind. Victorian-relevant: 1,134, of which 97 bind (about $599k of $770k total rental). Rental cover 90% = 12 constraints (50% = 3, 80% = 5, 95% = 19, 99% = 36); peak day >= 250 adds 10; price >= $50 adds 1; total 23 selected. WRL / Marinus-related binding = 37 (8 selected). Top by rental: `T_ROCOF_3_2`, `N^^N_NIL_WGLT`, `V^^N_NIL_1`, `N>>_N_NIL_UTMR1_LTWG1`, `N>>N_NIL_UTMR1_LTMR1`. FY27 has only Grp0/Grp1, so Grp6+ WRL constraints (`V>>WVic_*`) are not yet visible.

### With-WRL, all years (FY27-FY36) result, 2026-10-16
- Loaded 8.09M constraint-days. Constraint count per FY: 2,880 / 2,921 in FY27/28, then ~2,030-2,070 from FY29 (sub-equations stop being output; real constraints 1,971-2,068 every year).
- **Grp10 and Grp11 (from Jul 2033, FY34-36) are distorted in the with-WRL run.** Victorian-relevant rental is ~$0.2-0.7M per Grp for Grp0-9, but ~$660M each for Grp10 and Grp11, with thousands of days at price > $1,000, shadow prices of $100k+, and violation in the 100,000s (`N>>NIL_96B_96W_R`, `S>S_NIL_CLTX1_CLTX2_R`, `V>>V_NIL_GNTX1_GNTX2_R`, `N>>N_NIL_MOON1_*`, `V::S_NIL_MAXG_1`). Negative rental of -$1.5e8 on `V::S_NIL_MAXG_1` is a solver artefact. Cause (user-confirmed): the ESOO includes only committed and anticipated generation, so supply-demand balance worsens through the horizon; Grp10/11 are scarcity-driven (price cap, unserved energy), not network-driven. Rental scales with price, so late-horizon rental overstates network importance. The real model will have more supply. Rankings including Grp10/11 are dominated by these and are not usable.
- `rank_constraints.py` now has `--max-grp` (use 9) and builds the rental cover on positive rental only. Saved: `outputs/with_wrl/ranking_maxgrp9.csv`, `ranking_wrl_maxgrp9.csv` (also copied to `ranking.csv`), and the all-Grp versions `ranking_maxgrp11.csv`.
- **Grp0-9 (to Jun 2033) result:** 159 Victorian-relevant constraints bind; 90% rental cover = 22; + peak day >= $250 adds 48; price >= $50 adds 1; **71 selected**. Peak-day sensitivity: >=500 +25, >=1000 +16. WRL/Marinus-related binding = 66, 36 selected (5 retired at Grp5, 29 LHS-changed, 3 Marinus-added, 0 new). Top: `T_ROCOF_3_2` (31% of rental), `V::V_1900`, `N>>N_NIL_UTMR1_LTMR1`, `N^^V_NIL_1`, `N>>N_NIL_BASW1`, `V_NWVIC_GFT1_750`.
- The 27 new WRL constraints (`V>>WVic_*`) essentially never bind with WRL in (1 of 17 in the workbook binds, tiny). They only matter in the no-WRL run, so they cannot be ranked from this run.
- Per-FY 90% cover union would be 37 constraints (including Grp10/11 years), a cross-check on the cover size.

## Planned approach / caveats
1. **Baseline (with WRL):** ESOO as published, run per FY to 2036, 1 reference year, 1 outage pattern, all constraints. User is dropping in remaining years (2028 folder present).
2. **No-WRL run:** Grp5 equations held from Nov 2030, with the Grp8 `Marinus_1` (and `T-V-MNSP1`) coefficient added to the 141 Victorian constraints. Do not hold Grp5 blindly for NSW/Qld changes; test Grp10 and Grp11 effects on Victoria separately. Post-Nov-2030 rankings should come from the no-WRL run, because the as-published run ranks WRL-era constraints that are being removed. Fallback: FY27-FY30 rankings plus Grp5-form constraints ranked in FY30.
3. **Robustness:** one reference year underrates episodic constraints. A second reference year with contrasting Victorian wind/solar, then take the union of selected constraints. Stop if ~90% of impact overlaps.
4. **Validation:** run the selected subset with and without WRL and compare Victorian prices and curtailment against the full set.
5. FY31 straddles Grp5/6 (Nov 2030); FY32 holds Grps 7, 8, 9, so per-FY tables are also tagged by Grp (daily data allows this).
6. The user is undecided on the final deliverable; possible build: the full no-WRL (Grp5-held plus Marinus) constraint workbook, ready to queue as a run.

## Status / next step
- All years FY27-FY36 loaded and ranked (see result above). Next: user decides the cap/thresholds, and whether to investigate Grp10/11 distortion in the with-WRL run (probably the cause is missing network augmentations); then the no-WRL run (`--tag no_wrl`) and comparison.
- Then: no-WRL run results (`--tag no_wrl`) and a comparison of the two rankings.

## Environment notes
- Python 3.13 with a project-local `.venv` (polars, pyarrow, openpyxl, fastexcel). Global Python has no packages. Use `.venv\Scripts\python.exe`; set `PYTHONIOENCODING=utf-8` when printing tables with box characters on Windows.
- Generated folders: `cache/` (from the workbook), `outputs/<tag>/` (per run). Both can be regenerated.

## Constraint cap
User wants <= 20 constraints if possible. With-WRL Grp0-9: top 20 by rental = 89% of positive rental (10 = 77.5%, 15 = 85%, 25 = 92%, 40 = 96.5%). Beyond the top 20, 17 constraints still have a single day >= $1,000 rental; 5 have >= $5,000 (`V>>NIL_SMTX5`, `N::V_NIL_MSDD`, `S>>S_NIL_RBTX1_RBTX2`, `V>>NIL_SMTX2_SMTX1_R`, `N>>N_NIL_MGUT1_LTMG1_R`).

## Draft shortlist (with-WRL, Grp0-9, `scripts/draft_list.py`, 2026-10-16)
Three ranks (mean per-FY rental share, hours binding, total rental) averaged; top 15 = 83.7% of positive rental and 68.5% of hours binding. Shortlist: `T_ROCOF_3_2`, `N>>N_NIL_UTMR1_LTMR1`, `N^^V_NIL_1`, `V_NWVIC_GFT1_750`, `V::V_1900`, `V>>V_NIL_GNTX1_GNTX2_R`, `V^^N_NIL_1`, `N^^N_NIL_WGLT`, `N>>_N_NIL_UTMR1_LTWG1`, `V>>V_NIL_WETX1_R`, `S:VS_800`, `N>>N_NIL_BASW1`, `V>>NIL_BABE1`, `S>>S_NIL_RBTX1_RBTX2`, `N::N_NIL_63`. Caveats: `N^^N_NIL_WGLT` (defined only to Grp2) and `N>>_N_NIL_UTMR1_LTWG1` (defined to Grp11 but binds in only 2 FYs) are early-horizon only. `V::V_1900` and `N>>N_NIL_BASW1` are rental-heavy but low on hours (ranks 19 / 26), so likely scarcity-inflated. Remaining ~5 slots reserved for no-WRL / Marinus constraints after the no-WRL run (candidates with big single days: `V>>NIL_SMTX5`, `V>>NIL_SMTX2_SMTX1_R`).

### Shortlist revised 2026-10-16 (cap up to 40)
User allowed up to 40 constraints and wants constraints that bind heavily in only some years kept. `draft_list.py` now = 15 core (mean of share/hours/rental ranks) + year-specific (any constraint inside the 90% cumulative rental cover of any single FY, FY27-33), capped at 40. Result at `--fy-cover 0.9`: 36 (15 core + 21 year-specific), 94.8% of positive rental, 80.2% of hours binding; 4 slots left for the no-WRL run. At 0.8 it is 20; at 0.95 it hits the cap of 40. Mean-share alone under-weights one-year spikes (1/7 weight). Constraints that spike on single days (e.g. `V>>NIL_SMTX5`) are not captured by the FY cover (only by the peak-day test in `ranking_maxgrp9.csv`).

## Notes 2026-10-16 (draft_list.csv Q&A)
- `cover_fys` (scripts/draft_list.py): FYs in which a constraint is inside that FY's 90% cumulative share of Victorian positive rental (`--fy-cover`). Drives the `year_specific` shortlist entries (non-core, in any FY cover, ranked by max_fy_share, total capped at --cap).
- Flag columns in outputs/with_wrl/draft_list.csv: R wrl_lhs_change, S marinus_added, T wrl_new, U wrl_retired (from `grp_flags()` in rank_constraints.py, left-joined).
- 11 of 163 rows have blank flags (all four null) because the constraint is not in `cache/eq_meta.parquet` with a Grp timeslice. None are shortlisted. They are V^^V_MLNK_KGTS, N^^V_MLNK_1, N^^V_MLNK_ARWBBA, VSML_ZERO, SVML_ZERO, S_V_ROCOF, V_S_ROCOF, S_V_ROCOF_Reclass, V_S_ROCOF_Reclass, SV_250_LKB_Reclass, VS_V-SA_250_Reclass. Cause inferred from names (Murraylink/zero-flow/ROCOF/reclass), NOT verified. Blank = unchecked, not WRL-neutral.
- Shortlist is 36 (cap 40); 19 of the 36 are flagged WRL/Marinus-affected. Flagged and high ranked: N>>N_NIL_UTMR1_LTMR1 (3), N>>_N_NIL_UTMR1_LTWG1 (9), V>>NIL_BABE1 (12). Unaffected top ones: T_ROCOF_3_2, N^^V_NIL_1, V_NWVIC_GFT1_750, V::V_1900, V>>V_NIL_GNTX1_GNTX2_R, S:VS_800.
- Conclusion: unflagged equations can be used as-is in the no-WRL model, but the ranking comes from the with-WRL run, so binding may shift without WRL. Flagged ones need the Grp5 equation (check new/retired existence at Grp5). Suggested next steps: build the Grp5-equation list for the <=20 cap; ideally run a no-WRL ranking or check constraints just below the cutoff; hand-check the 11 blank-flag constraints.
- Tooling: run scripts with `.venv\Scripts\python.exe -X utf8 -I` (cp1252 console errors on `┆`-style table chars otherwise; `-I` ignores PYTHONIOENCODING).

## No-WRL run result, 2026-10-19
- Method used: global freeze of timeslices at Grp5 from Nov 2030 (Grp6-11 off; Marinus excluded; 101 Grp6+ constraints deactivated). The targeted per-constraint edit was abandoned (about 487,000 LHS properties differ from Grp5 in Grp6-11 for the 486 WRL/Marinus-affected constraints; only 7,422 are interconnector terms; PLEXOS XML is 1.4 GB). Lists and scripts are in outputs/no_wrl/ (plan, drop, deactivate, freeze_grp5, line_edits).
- Run years: FY31-33 re-run with the freeze; FY27-30 copied from the with-WRL run (identical, freeze starts Nov 2030). Results in ESOO_results_no_WRL/. Loaded with `--tag no_wrl`; 5.84M constraint-days.
- Grp0-9, FY27-33: 162 Victorian-relevant constraints bind (with-WRL 159), 90% rental cover = 21 (22), 71 selected by any test (71). Shortlist 35 (15 core + 20 year-specific), 95.4% of positive rental, 71.6% of hours binding.
- Compare (compare_runs.py, FY27-33): Victorian positive rental 5.16M no-WRL vs 4.13M with-WRL; top-10 overlap 9, top-20 overlap 18; shortlists 35 vs 36 with 32 common. Only in no-WRL: N>>NIL_LINC1_LITO1, T>>T_NIL_SHGT2_R, V>>V_NIL_GLLR1. Only in with-WRL: N::V_NIL_MSDD, S>>S_NIL_RBTX1_RBTX2, V>>NIL_SMTX5, V>>V_NIL_MRDD1_MRDB2. So WRL moves the top ranks very little.
- N>>N_NIL_BASW1 has a single-day rental of ~$974k (FY33), likely a scarcity/violation artefact; unchecked. It is in the no-WRL core.
- Scripts fixed to run under `python -I` (add own folder to sys.path). README has a quick-start for re-running without Claude.

## Candidate list 2026-10-19
User reversed the BASW1 exclusion and the sub-regional-demand rule (can include them; wants many constraints, as long as material). `scripts/final_list.py` writes outputs/final_constraint_list.csv: tier A = union of with_wrl and no_wrl shortlists (39), tier B = single-day rental >= $1,000 in either run (11, review), 50 total. 28 take the Grp5 equation, 22 as published. 7 constraints have `_G_` sub-equations (44 rows, 3 names not in constraint_objects.csv). BASW1 and V::V_1900 carry a review note (single-day rental > $50k). N^^N_NIL_WGLT is only defined to Grp2. User has more testing to do on specific constraints before extracting equations (steps 4-6: pull equations, own-model runs, validation).

Update 2026-10-19 (Marinus kept): user's own model needs Marinus in both scenarios. final_list.py now keeps Marinus by default (`--no-marinus` restores the old behaviour). Of the 50 candidates only 5 carry Marinus_1 (V>>V_NIL_YPAHWC1_YPCHWG2_R, T>>T_NIL_SHGT2_R, V>>NIL_SMTX2_SMTX1_R, V>>NIL_SMTX5, T>>T_NIL_HAGT2_R); only V>>NIL_SMTX2_SMTX1_R is WRL-affected, so it alone needs Grp5 + the Marinus_1 term (`add_marinus_term`). Now 24 constraints take the Grp5 equation, 26 as published. Marinus_1 coefficients are the same Grp8-11 (-1.0 to 0.72). They were fitted with WRL in the network, so on a no-WRL network they are approximate. Caveat: the no-WRL ESOO run excluded Marinus, so Marinus-driven binding in Grp8-9 is only captured via the with-WRL run (the shortlist is a union).

Update 2026-10-22: final_list.py sub-equation logic fixed. It now names nested groups with the full ancestor chain (N::N_NIL_63_G_2_G_3), and picks up type-X terms (X_N::V_MSDD_ST etc.) plus their _G_ children. Sub-equation file: 44 -> 132 rows over 10 constraints, 0 names missing from constraint_objects.csv. 15 candidates have Grp5 rhsTerms cut at Excel 32,767-char cell limit (column rhs_truncated); visible parts contain no G/X terms. outputs/subequations_keep_on.txt is the older 41-name list (subset of the new one). Run the script with -X utf8.

## Correction 2026-10-26: Summer_Grp5 is empty, first no-WRL run lost summers
- `Summer_Grp5` and `Summer_Grp7` have no constraints (Grp5 = Mar-Oct 2030, Grp7 = Jul-Nov 2031, no summer). The global freeze extended Grp5 timeslices, so ~969 seasonal constraints had no equation in summers from Dec 2030. Evidence: seasonal constraints, Dec-Feb after Dec 2030, FY31-33: 0 hours binding / 0 constraints binding in no_wrl vs 31,581 hours / 97 constraints in with_wrl. Non-summer months are close (44,286 vs 53,681 hours).
- Fix for the ESOO re-run: hold `Summer_Grp4` in summers (Grp4->5 LHS change is ~0 for the candidates) plus `NotSummer_Grp5` in non-summers and plain `Grp5` for single-version constraints. Re-load and re-rank no_wrl afterwards; the no_wrl ranking and shortlist produced before this are biased against seasonal constraints in summer (partly offset because the final list is a union with with_wrl).
- Earlier "208/244 objects missing from the frozen LHS" was an artefact of the same season mismatch (Summer_Grp6 rows had no Summer_Grp5 counterpart). Season-insensitive result: 50 objects are in the published Grp6-9 equations but not in Grp5, in 4 of the 24 WRL-affected constraints (V>>NIL_WBBA_KGBE 42, V>>NIL_WBBA_RCWEKG 49, V>>V_NIL_BAML1_ELML1 4, V>>NIL_SMTX2_SMTX1_R 1). All 50 are existing plants (in hundreds of other constraints from Grp0), newly added to these constraints at the WRL step, so freezing correctly excludes them. outputs/no_wrl/frozen_missing_terms.csv lists them.
- Among the 50 candidates, 11 are seasonal; of the 24 WRL-affected, only N>>N_NIL_WGANM1_WLJI1 and V>>NIL_SMTX2_SMTX1_R. Their frozen version should use NotSummer_Grp5 (or Summer_Grp4 in summers).

## RHS adders 2026-10-27
`scripts/rhs_offsets.py` (see README) fits flat MMS-minus-ESOO RHS adders. Result for 30 constraints: apply 2 (N^^V_NIL_1 -165 MW; N::N_NIL_63 seasonal +110 Summer / +45 NotSummer), apply_surrogate 1 (N>>N_NIL_WASS1_WAIN1 +430, ends May 2028), review 18, no_change 5, excluded_dynamic_rhs 4. Most review cases are because `rhs_any` flags an RHS change at Grp1 (Feb 2027), so they were fitted on Jul-Jan only (7 months) and the adder ends 2027-01-31. That includes V>>NIL_WBBA_KGBE/RCWEKG (+165/+180). S:VS_800 (+110) is review for diurnal shape only. Thresholds were not tuned. Output: outputs/rhs_offsets/rhs_offsets_to_apply.csv.

Update 2026-10-27 (end-date rule): the market model fixes RHS to ESOO outcomes, so ROCOF constraints are fitted like the rest and adders apply to all equations. An adder now ends at the first `rhs_any` change whose ESOO RHS level step exceeds max(20 MW, 25% of the adder) (step = 30-day median before/after the Grp start, daily RHS / 24 because the results' daily RHS is a 24-hour sum). Earlier step figures in this session were not divided by 24 and were wrong. Result: apply 3 (N^^V_NIL_1 -165, N::N_NIL_63 seasonal +110/+45, T_ROCOF_3_2 +210), apply_surrogate 4 (N>>NIL_MGLT1_MRUT1 +560, N>>N_NIL_WASS1_WAIN1 +430, N>>_N_NIL_UTMR1_LTWG1 +565, V>>V_NIL_WETX1_R +25; first three end 2028-05-31), review 13, no_change 8, insufficient_data 2. The WBBA pair stays `review` (Grp1 step +49 MW vs a 41 MW tolerance, fitted Jul-Jan only, ends 2027-01-31).

Update 2026-10-27 (ROCOF data-limited): S_V_NIL_ROCOF and V_S_NIL_ROCOF have ESOO RHS only for Jul-Jan, so the 9-month minimum is waived for constraints whose ESOO RHS ends by Jan 2027; they are fitted on 7 months, status `review`, adder ends 2027-01-31 (S_V +375 MW, V_S +250 MW). July has no gap (ESOO RHS is ~1,230 MW in July then drops to a 556 MW floor), so a flat adder overshoots July.

Update 2026-10-27 (segment fits, after reviewing the per-constraint plots): ending the adder at a material Grp1 step produced cliffs (e.g. V>>NIL_WBBA_KGBE: MMS flat ~800 MW, ESOO ~640 then ~700 after Grp1, so ESOO+adder dropped from 800 to 700 when the adder was removed). rhs_offsets.py now fits pre_grp1 (Jul-Jan) and post_grp1 (Feb-Jun) adders separately against the same MMS months (WBBA_KGBE +165 -> +100, WBBA_RCWEKG +180 -> +105, V^^N_NIL_1 -45 failed -> -140 consistent, DPTX3_DPTX4 +15 -> -80, UTMR1_LTMR1 +5 -> +85), and carries the post adder to the next material step. New review flag when the P10-P90 spread of monthly gaps exceeds the adder (SPREAD_FRAC = 1.0; 0.5 flagged almost everything). Fits under 9 months are capped at review. ROCOF pair: user prefers a flat uplift even though it overshoots the spike days. rhs_offsets.csv is now one row per constraint segment.

Update 2026-10-27 (revised rules): the post-Grp1 segment fits were wrong in principle (they paired MMS 2025-26 with ESOO 2027 and so cancelled real ESOO change; same-period Jul-Sep 2026 gaps agree with the all-month fits, e.g. WBBA_KGBE +165/+165, N^^V_NIL_1 -165/-170). Removed. Steps are now seasonally adjusted (raw Grp3 step for N>>_N_NIL_UTMR1_LTWG1 was +456 MW, adjusted -61). One fit per constraint, restricted to Jul-Jan only if the Grp1 adjusted step is material. Result: apply 3 (N^^V_NIL_1 -165, N::N_NIL_63 +110/+45, V>>NIL_WBBA_KGBE +150 to 2030-10-31), apply_surrogate 2 (WASS1_WAIN1 +430 to 2028-05-31, UTMR1_LTWG1 +565 to end of run), review 11, no_change 14. DPTX3_DPTX4, UTMR1_LTMR1 and V^^N_NIL_1 are now no_change. NSW1-SA1 question for N^^V_NIL_1 / V^^N_NIL_1 is open: neither equation references SA terms, N^^V_NIL_1 never changes and differs from MMS from day one; confirming needs the MMS equation history (version/effective dates, RHS terms).

Update 2026-10-27 (WRL consistency): ending a with-WRL adder at the Grp6 WRL step while the no-WRL case kept it put no-WRL RHS above with-WRL (V>>NIL_WBBA_KGBE: 810 vs 750 MW). For WRL-affected constraints Grp6+ changes are now ignored in both scenarios, so both carry the same adder and end date (KGBE +150, RCWEKG +180, LTWG1 +565, BAML1 -645, MLGL2 +1085 all to end of run; MGLT1 +560 to 2028-05-31). Remaining end_with/end_no differences (N>>N_NIL_BASW1, LINC1_LITO1) are only the no-WRL run's data ending mid-2033.

## Cleanup 2026-10-28
All script inputs now live under `inputs\` (workbook, csv inputs, ESOO result folders, compare_to_MMS, mapping, raw dumps); `quick_extract*.py` moved to `scripts\mapping_tools\`. Scripts and README updated. Three items were locked by Excel and still need moving by hand: `ESOO2026 Constraints Details.xlsx` and `Mapping.xlsx` (project root) and the `compare_to_MMS` folder. Scripts already point at `inputs\`, so `build_lhs_cache.py` and `compare_to_MMS.py` will not find them until moved.

## Scenario validity findings 2026-10-28
How long the committed-and-anticipated constraints stay valid against the government-schemes-and-actionable scenario (Table 11): see `FINDINGS_scenario_validity.md`. Summary: Victoria-only constraints have no identified limiter once the Western Victoria Reinforcement Project is proxied; `BASW1` to about Jul 2030 (Sydney Ring South power flow control); the Murray/Tumut/Maragle group to about Apr 2031 (Wondalga, unconfirmed); nothing usable after Jun 2033. Name-based constraint links are unverified. Note: the "Cleanup 2026-10-28" note above is out of date, the three locked items were moved later the same day.
