# Equation check: decisions needed (2026-10-29)

Written for: Blake Kirby. Source: `equation_check_summary.csv`. "Adder" = MMS minus ESOO RHS, added to the ESOO RHS. "Util adder" = the adder that matches LHS/RHS utilisation (P95 / P99).

**Working rule (agreed 2026-10-29):** where coefficients and RHS agree but ESOO LHS is higher, the extra LHS is treated as extra objects in the ESOO fleet and the RHS gap stands. This could not be tested (no ESOO unit generation), and is an assumption. The utilisation adder is used only for the genuinely scaled MLGL pair.


## Review outcomes (Blake, 2026-10-29) and follow-up evidence
| Constraint | Blake's outcome | Evidence added |
|---|---|---|
| MLGL pair | Agree: replace +1,085 with a small adder | Scale-adjusted gap (0.5 x MMS RHS - ESOO RHS) is -121 median / -185 at P10; utilisation adder +85 / 0. |
| N>>NIL_MGLT1_MRUT1 | Logic of the earlier recommendation rejected: correct | Coefficients 0.79x and RHS 0.76x agree, so ESOO is a scaled copy. Raw gap +649 median, but scale-adjusted gap (0.79 x MMS RHS - ESOO RHS) is +11 median and +483 at P10. The +560 is mostly scale. |
| V>>NIL_WBBA_KGBE / RCWEKG | Not understood: same issue (coefficients 0.93x) | Raw gap +169 / +180 median; scale-adjusted +112 / +124 median, +38 / +47 at P10. Suggested adders +150 / +180 include about 40-55 MW of scale. |
| V>>V_NIL_BAML1_ELML1 | Needs investigation | Different monitored element and different RHS structure (MMS RHS is built from a line rating, VRAT15_ELML, less margins and wind terms). After the 1.46x scale the median RHS gap is -14 MW (P10 -225), so the -645 is almost entirely scale. Equation cannot be validated further without the retired MMS equation. Recommendation: no adder. |
| N^^V_NIL_1 | Needs investigation | The RHS is dynamic, not a fixed level: both ESOO and MMS use 1313 minus 0.4875 x largest Vic unit minus 0.4709 x South NSW generation plus Canberra and margin terms. The ESOO/MMS RHS gap therefore reflects ESOO dispatch (fleet, largest unit), not a level error. Recommendation: treat as dynamic RHS like the ROCOFs, no adder (reject -165). |
| N>>N_NIL_DPTX3_DPTX4 | Keep excluded | Excluded means no adder needed. For reference the gap is mixed (+62 median, -57 at P10). |
| SMTX2, LINC1 | Agree: keep excluded | |
| ROCOFs | Leave as approximate | |
| Remaps | Not pursued | Treated as no MMS match; ESOO RHS used as is. |

## 1. Scaled copies: the MW gap is the wrong number
| Constraint | Evidence | Current adder (your decision) | Util adder | Recommendation |
|---|---|---|---|---|
| V>>NIL_MLGL1_MLGL2 and V>V_NIL_MLGL2_MLGL1 | Every ESOO coefficient is 0.50x MMS; RHS ratio 0.55, LHS ratio 0.60 | +1,085 (tentative accept) | +85 / 0 | Replace with a small adder (0 to +85). Do not carry +1,085 into the equations. |
| N>>NIL_MGLT1_MRUT1 | ESOO coefficients 0.79x MMS; RHS ratio 0.76; LHS ratio 1.0 | +560 (accept; your comment asks how uprating is represented) | +415 / +490 | Keep the RHS gap (+560). Coefficients (0.79) and RHS (0.76) agree, so the higher ESOO LHS is treated as extra objects in the ESOO fleet, not an RHS error. Not verified: no ESOO unit generation is available to split extra objects from dispatch. Your comment on how uprating is represented still applies. |

## 2. Different formulation: no additive adder
| Constraint | Evidence | Current | Recommendation |
|---|---|---|---|
| V>>V_NIL_BAML1_ELML1 | Monitored and tripped elements are swapped versus MMS; coefficients 1.46x | -645 (rejected) | Keep the rejection. Use no adder, or about +35. |
| V>>NIL_SMTX2_SMTX1_R | Mapped MMS is a radial-mode variant, swamped at about 15,000 MW two thirds of the time | Excluded | Keep excluded. |
| N>>NIL_LINC1_LITO1 | Mapped MMS is the "132kV open" variant, swamped about 60% of the time; ESOO RHS about equals MMS un-swamped RHS | Excluded | Keep excluded. |

## 3. Exclusion that the evidence does not fully support
| Constraint | Evidence | Recommendation |
|---|---|---|
| N>>N_NIL_DPTX3_DPTX4 | 22 matched coefficients are identical. ESOO LHS is higher only because 55 extra terms are plants not in the MMS equation today (67% of coefficient weight). | Your call. The equation is not wrong, so excluding it is a modelling choice. If you keep it excluded, the reason is "ESOO binds heavily with future plants", not "equation does not check out". |

## 4. ESOO LHS much larger than MMS while the RHS is close
| Constraint | RHS ratio / LHS ratio | Current adder | Util adder | Recommendation |
|---|---|---|---|---|
| N^^V_NIL_1 | 1.36 / 1.96 | -165 (accept) | +80 / 0 | The equation is the same (coefficients 1.00), so the higher ESOO LHS is treated as extra objects. The -165 stands on that logic, but a negative adder with an ESOO RHS 1.36x MMS is the one to re-read. |
| V>>NIL_WBBA_KGBE and V>>NIL_WBBA_RCWEKG | 0.8 / 1.44 and 0.78 / 1.47 | +150 and +180 (accept) | +150 / +40 and +135 / +60 | Keep the RHS gap. Check the V-SA versus V-S-MNSP1 term in the ESOO equation. |

## 5. ROCOF (RHS depends on dispatch)
S_V_NIL_ROCOF (+375), V_S_NIL_ROCOF (+250), T_ROCOF_1 (+145), T_ROCOF_3_2 (+210), all accepted. The util adders are +500/+180, +110/+5, +195/+105 and +260/+130. A fixed adder is an approximation here. Recommendation: keep your accepts, but treat them as approximate. T_ROCOF_3_2 is about 30% of rental, so it is the one that matters most.

## 6. Missing MMS data: decide whether to remap
| ESOO constraint | Candidate MMS equivalent | Status |
|---|---|---|
| V>>V_NIL_WBBA1_RCKESS1 | V>>NIL_WBBA_RCWEKG | Probable. It is in Constraint_Data, but it is already used by another ESOO constraint. |
| V>>V_NIL_GNTX1_GNTX2_R | V>NIL_GNTX_GNTX | Probable, but not in Constraint_Data. It needs a data pull. |
| V>>NIL_WBBA1 | none found | The old mapped equation is retired and is a different element. Use ESOO RHS as is. |
