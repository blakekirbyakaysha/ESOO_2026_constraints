# Findings: how long the committed-and-anticipated constraints stay valid (2026-10-28)

Written for Blake Kirby (Akaysha Energy) to pick up later. Source: ESOO 2026 Table 11 (PDF pp. 67-68), plus web searches on individual projects. Project-to-constraint links are my inference unless marked confirmed.

## Question
Our selected constraints come from the **committed and anticipated (C&A)** scenario. Our own modelling is closer to **government schemes and actionable developments (GS&AD)**, and we cannot get GS&AD constraint equations. Until when is it valid to use the C&A constraints? Our model excludes WRL and VNI West Stage 2. We can proxy the Western Victoria Reinforcement Project, move Grp timings, and switch constraints off one by one. We carry the top 50 plus `V>>V_NIL_BAML1_ELML1`.

## Table 11, paired by scenario (GS&AD vs C&A)
Pairing checked against our Grps: WRL Nov 2030 = Grp6 and Marinus Stage 1 Dec 2031 = Grp8 (both match C&A).

| Project | GS&AD | C&A |
|---|---|---|
| Project EnergyConnect Stage 2 | Dec 2027 | Dec 2027 |
| HumeLink | Dec 2027 | Jun 2028 |
| Hunter-Central Coast REZ network | Jul 2028 | Jan 2029 |
| Central-West Orana REZ network | Dec 2028 | Jun 2029 |
| Gladstone | Mar 2029 (critical); balance mid-2030 | Mar 2030; balance mid-2031 |
| Western Victoria Reinforcement Project | Jun 2029 | not included |
| Western Renewables Link | Nov 2029 | Nov 2030 |
| Hunter Transmission Project | Nov 2029 | not included |
| Sydney Ring South power flow control | Jul 2030 | not included |
| Marinus Stage 1 | Dec 2030 | Dec 2031 |
| Tasmania REZ expansion | Dec 2030 | not included |
| Switching station near Wondalga | Apr 2031 | not included |
| Central to North Queensland | Jul 2031 | not included |
| Gippsland offshore transmission | Jul 2031 (opt 1), Jul 2033 (opt 2) | not included |
| VNI West | Stage 1 Aug 2029; Stage 2 Nov 2031 | not included |
| CopperString | Jun 2032 | Jun 2033 |
| Brisbane Area Reinforcement | Jun 2032 | not included |
| Central-West Orana REZ expansion | Mar 2033 | not included |
| Sydney Ring South 500 kV | Jul 2033 | not included |
| New England REZ | Jan 2034 | Jan 2035 |
| Marinus Stage 2 | Dec 2034 | not included |

Every difference makes GS&AD earlier or stronger, so the C&A constraints **overstate congestion**, increasingly over time.

## Differences we can close ourselves
- **Western Victoria Reinforcement Project (Jun 2029):** proxy it (user is confident).
- **Timing-only differences:** move Grp start dates to the GS&AD dates:

| Project | Move from | Move to |
|---|---|---|
| HumeLink | Jun 2028 | Dec 2027 |
| Hunter-Central Coast REZ | Jan 2029 | Jul 2028 |
| Central-West Orana REZ | Jun 2029 | Dec 2028 |
| Gladstone | Mar 2030 | Mar 2029 |
| Marinus Stage 1 | Dec 2031 | Dec 2030 |
| CopperString | Jun 2033 | Jun 2032 |
| New England REZ | Jan 2035 | Jan 2034 |

- **Check first:** which projects each Grp bundles (`inputs\constraint_changes_by_grp.csv`). Moving a Grp moves everything in it. Only Grp5->6 = WRL is confirmed.
- **Adder end dates:** `outputs\rhs_offsets\rhs_offsets_to_apply.csv` end dates are tied to the original Grp dates. Re-check after any shift.

## Remaining unrepresented projects (GS&AD only)
| Project | Date | Conclusion |
|---|---|---|
| Hunter Transmission | Nov 2029 | NSW-only (Central NSW to Sydney). Probably low impact on Victorian prices (judgement). |
| VNI West Stage 1 | Aug 2029 | NSW-side works: Dinawan-Wagga-Gugaa to 500 kV, Dinawan switchyard, Gugaa cut into TL51, Gugaa-Wagga rebuild. It improves delivery to Wagga. The Tumut, Murray and Maragle constraints are upstream and still enforced. Only `N>>_N_NIL_UTMR1_LTWG1` is plausibly touched (TL51), and only if Stage 1 is included. |
| VNI West Stage 2 | Nov 2031 | Excluded in our modelling. |
| Sydney Ring South power flow control | Jul 2030 | Power flow control on the existing 330 kV network (PADR: from 2030-31). Relieves the corridor into south-west Sydney from the south. `BASW1` is probably Bannaby-Sydney West (name-based). From Jul 2030 switch `BASW1` off or uplift its RHS. |
| Wondalga switching station | Apr 2031 | The interface between HumeLink East (Bannaby-Wondalga) and West (Maragle-Wagga), built alongside the Snowy 2.0 switching yard. Plausibly affects the Murray/Tumut/Maragle constraint group (inference). The 450 MW function is unconfirmed. |
| Gippsland offshore transmission | Jul 2031 | Extends the network from the Latrobe Valley to a coastal hub. Affects only Latrobe or Gippsland outflow constraints. Earlier claim that it limits most Victorian constraints was wrong and retracted. |

## Validity by constraint group
| Group | Valid until |
|---|---|
| Victoria-only constraints (WBBA, KGBE, RCWEKG, MLGL, NWVIC_GFT1, others) | No limiter identified in Table 11, provided the Western Victoria proxy is in place. |
| `N>>N_NIL_BASW1` | About Jul 2030 (then switch off or uplift RHS) |
| Murray/Tumut/Maragle group: `UTMR1_LTMR1` (+`_R`), `MGLT1_MGUT1` (+`_R`), `MGUT1_LTMG1` (+`_R`), `MGLT1_MRUT1` | About Apr 2031 (Wondalga, unconfirmed) |
| `N>>_N_NIL_UTMR1_LTWG1` | Aug 2029 only if VNI West Stage 1 is included |
| `N^^V_NIL_1`, `V^^N_NIL_1` (Victoria-NSW) | Stage 1 alone should change the transfer limit little (judgement). Re-check at HumeLink timing and Wondalga (Apr 2031). |
| All constraints | Not usable after Jun 2033 (Grp9 cutoff). Past that, scarcity distortion and later projects dominate. |

## Not verified
- Name-based constraint readings (`BASW1` = Bannaby-Sydney West, "WG" = Wagga, etc.) need checking against `cache\lhs_terms.parquet`.
- The AEMO Wondalga consultation page returned HTTP 403. Open it in a browser and read the identified need: https://www.aemo.com.au/Consultations/Current-and-closed-consultations/Draft-2026-ISP-non-network-options-consultation-Switching-Station-Near-Wondalga
- Sydney Ring South details come from search summaries, not the PADR itself. One result's claim that AEMO made only the switching station and power flow controllers actionable is unverified.
- Based on Table 11 only. No project was tied to its constraint equations.

## Next steps
1. Open the Wondalga AEMO page and record the need statement.
2. Scan `lhs_terms.parquet` for Wagga, Gugaa, Dinawan, Lower Tumut, Maragle, Bannaby and Sydney West terms to confirm which constraints each project touches.
3. Check what each Grp bundles in `constraint_changes_by_grp.csv` before moving any Grp date.
4. Re-check the RHS adder end dates after Grp shifts.
5. Record the per-constraint end dates in `PROJECT_CONTEXT.md` once confirmed.

## Sources
- ESOO 2026 (Table 11, pp. 67-68): https://www.aemo.com.au/-/media/files/electricity/nem/planning_and_forecasting/nem_esoo/2026/2026-electricity-statement-of-opportunities.pdf
- Sydney Ring South PADR (AEMO): https://www.aemo.com.au/consultations/current-and-closed-consultations/padr-sydney-ring-south-project
- Sydney Ring South (Transgrid): https://www.transgrid.com.au/projects-innovation/sydney-ring-south/
- HumeLink West (Transgrid): https://www.transgrid.com.au/humelink-west
- Gippsland offshore wind (Victorian Government): https://energy.vic.gov.au/renewable-energy/vicgrid/offshore-wind-transmission/gippsland-offshore-wind
- Gippsland options assessment report: https://www.energy.vic.gov.au/__data/assets/pdf_file/0012/700221/Gippsland-options-assessment-report.pdf
