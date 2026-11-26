# Synthetic contract derivation

**These are derived test data, not independent supplier research.** `tests/comparison_expected.json` (23 cases,
derived from a non-public contract, v1.2) and `tests/adversarial_expected.json` (10 cases, derived from a non-public
set, v1.2) exercise the comparison layer on invented suppliers. The real-record originals are not included, and
this page does not list their values.

## Transformations
1. Real-record GBP amounts are doubled (minor units too), with one exception: the per-parcel surcharge is an invented
   £13.40 (kept above the £9.90 standard charge so every surcharge relation holds).
2. Kept unchanged on purpose: percentage rates (VAT 20%), quantities, parcel counts, pack sizes, dates, and the
   destinations the engine's explicit area table recognises (England mainland, UK, Northern Ireland, the Channel
   Islands). Zone lists otherwise use invented names (North Coast Isles, Far Valley District); "Northern Ireland"
   stays in the surcharge list because the Northern Ireland cases need the engine to recognise it.
3. Suppliers, labels, URLs, SKUs, product names and variant ids are invented (scout/workflows/demo_supplier.py).
4. Quotes are invented wording that keeps the tokens the engine reads (over/Over/from, "*", "per parcel",
   "before VAT", "Most Of" wording, zone words).

## Scope of the preservation claim, and rounding
The claim that the derivation preserves each business outcome is made **only for the 33 cases below**, each checked
independently. It is not a general claim that doubling preserves every rule: with penny rounding, a doubled amount
can round differently from the original in general (for example, a VAT conversion ending in a half penny).
- **Rounding policy:** the engine rounds money half-up to 0.01 (`CENT`, `ROUND_HALF_UP`). Every derived amount is
  a whole number of pennies, and in the checked cases no conversion produced a fraction of a penny (A4 and C2:
  £150.00 / 1.20 = £125.00 exactly).
- **Boundary coverage:**
  - A1: equality with a "from" rule qualifies.
  - A2: equality with an "over" rule does not.
  - A3: 0.02 below the threshold.
  - B1: below the minimum order.
  - A4 and C2: VAT conversion at the quoted 20%.
  - C3: a pre-VAT rule without a rate abstains.
  - D4: an exact tie.
  - D6: a lower product price but a higher delivered total.
  - H8: double counting is forbidden.
  - H4: two different charges conflict.

## Check without engine code (33 of 33 OK)
The "computed" column comes from the hand rule applied to the synthetic inputs. The last relation column is a
separate re-evaluation of the same relation on the non-public original values; only its truth value is shown here. The engine is
then checked against the same expectations by the contract, adversarial and wording suites.

| Case | Business assertion (hand rule) | Synthetic inputs | Computed by hand rule | Asserted by synthetic contract | Relation holds (synthetic) | Same relation on original values | OK |
|---|---|---|---|---|---|---|---|

| A1 | 'from' rule: value >= threshold qualifies; free = 0.00 | value 100.00, threshold £100 from | qualified, 0.00 | qualified, 0.00 | True | True | yes |
| A2 | 'over' rule: equality does not qualify; standard charge applies | value 100.00, threshold £100 over | not_qualified, 9.90 | not_qualified, 9.90 | False | False | yes |
| A3 | 'over' rule: just below the threshold | value 99.98 | not_qualified, 9.90 | not_qualified, 9.90 | False | False | yes |
| A4 | pre-VAT threshold with quoted 20%: value/1.2 > £120 | value 150.00 inc VAT | qualified, 0.00, ex VAT 125.00 | qualified, 0.00, ex VAT 125.00 | True | True | yes |
| A5 | 'over' rule not met at one sack; per-parcel surcharge listed, not applied | value 33.92 | not_qualified, 9.90, listed 13.40 | not_qualified, 9.90, listed 13.40 | True | True | yes |
| A6 | destination outside surcharge zones: standard applies, surcharge not applied | England mainland | applied 9.90, not applied 13.40 | applied 9.90, not applied 13.40 | True | True | yes |
| A7 | destination inside surcharge zones, parcel count 1: per-parcel x 1 | Northern Ireland, 1 parcel | 13.40 | 13.40 | True | True | yes |
| B1 | minimum order: value < minimum is ineligible | value 33.92, minimum £40 | ineligible | ineligible | True | True | yes |
| B2 | every availability signal for the 16kg offer says unavailable: excluded as unavailable | three agreeing signals | ineligible: product unavailable | ineligible: product unavailable | True | True | yes |
| B3 | destination named in the quoted geography exclusion: excluded | Channel Islands vs quoted exclusion | ineligible: destination excluded | ineligible: destination excluded | True | True | yes |
| B4 | requested pack (25kg) is not the configured pack (16kg): offer not confirmed | 25kg order, 16kg binding | ineligible: offer not confirmed for the requested pack | ineligible: offer not confirmed for the requested pack | True | True | yes |
| C1 | total = price x qty + standard charge | 33.92 x 1 + 9.90 | 43.82 | 43.82 | True | True | yes |
| C2 | free under pre-VAT rule: total = value + 0.00 | value 150.00 | 150.00 | 150.00 | True | True | yes |
| C3 | pre-VAT rule without a rate: abstain, no total | - | None | None | True | True | yes |
| C4 | currency conflict at offer level: no total | - | None | None | True | True | yes |
| C5 | 'Over' rule not met and no charge quoted: no total | value 47.00 | not_qualified, None | not_qualified, None | False | False | yes |
| C6 | minor-unit record alone: no currency, no total | - | None | None | True | True | yes |
| D1 | per-supplier total = price + charge, AND the verdict abstains (unknown VAT basis: no ranking) | demo_mill_one 43.82, demo_mill_three 56.60, demo_mill_two 60.90 | abstains; [('demo_mill_one', '43.82'), ('demo_mill_three', '56.60'), ('demo_mill_two', '60.90')] | abstains; [('demo_mill_one', '43.82'), ('demo_mill_three', '56.60'), ('demo_mill_two', '60.90')] | True | True | yes |
| D2 | per-supplier total = price + charge, AND the verdict abstains (unknown VAT basis: no ranking) | demo_mill_one 43.82, demo_mill_three 56.60 | abstains; [('demo_mill_one', '43.82'), ('demo_mill_three', '56.60')] | abstains; [('demo_mill_one', '43.82'), ('demo_mill_three', '56.60')] | True | True | yes |
| D3 | per-supplier total = price + charge, AND the verdict abstains (unknown VAT basis: no ranking) | demo_mill_one 43.82, demo_mill_two 60.90 | abstains; [('demo_mill_one', '43.82'), ('demo_mill_two', '60.90')] | abstains; [('demo_mill_one', '43.82'), ('demo_mill_two', '60.90')] | True | True | yes |
| D4 | tie preserved: equal totals on both suppliers | one 43.82, three 43.82 | True | True | True | True | yes |
| D5 | no verified price (expired, unavailable, conflicting): no comparison | - | none | none | True | True | yes |
| D6 | lower product price but higher delivered total | one 33.92+9.90=43.82, three 30.00+18.00=48.00 | 30.00<33.92 and 48.00>43.82 | 30.00<33.92 and 48.00>43.82 | True | True | yes |
| H1 | value over threshold but starred terms uncaptured, NI per-parcel: abstain; component only | value 101.76 | abstained, component 13.40, no total | abstained, component 13.40, no total | True | True | yes |
| H2 | 'Most Of' zone wording: abstain even though value qualifies | value 120.00 | abstained, no total | abstained, no total | True | True | yes |
| H3 | quoted exclusion beats qualifying value: not_qualified; component only | value 135.68 | not_qualified, component 13.40 | not_qualified, component 13.40 | True | True | yes |
| H4 | two different standard charges (9.90 vs 11.90): abstain, no total | 9.90 vs 11.90 | abstained-conflict, None | abstained-conflict, None | True | True | yes |
| H5 | order value from a conflicting offer: membership abstains | 45.60 vs 38.00 | abstained | abstained | True | True | yes |
| H6 | per-parcel charge with unknown parcel count: abstain | 3 sacks, NI | abstained, None | abstained, None | True | True | yes |
| H7 | free rule into a named surcharge zone: abstain, no free claim | value 135.68, Highlands | abstained | abstained | True | True | yes |
| H8 | same charge on two pages applies once: total = price + charge, never + 2 x charge | 33.92 + 9.90 | 43.82 (not 53.72) | 43.82 (not 53.72) | True | True | yes |
| H9 | amountless threshold: abstain; standard charge as a labelled component; no total | - | abstained, 9.90, None | abstained, 9.90, None | True | True | yes |
| H10 | EUR order value vs GBP rule: abstain, never convert | EUR 101.76 | abstained, None | abstained, None | True | True | yes |
