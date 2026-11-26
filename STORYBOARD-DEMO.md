# Storyboard: Scott M1 guided walkthrough (about 106 seconds)

**What it is:** a guided walkthrough recorded offline on 25 November 2026 from `python3 -S scripts/scout_ui_demo.py`
(page `/m1`), the documented demo entry point.

**How it was made:**
- Each scenario opens with an **establishing shot** at the page top, uncropped: the banner, the "M1 comparison"
  heading and the scenario chips, with the active chip highlighted. It holds for about 4 seconds.
- An eased scroll then pans down into the claim and the cards. In S1 it continues to the opened evidence.
- The page is recorded clean, with no overlay. The captions are drawn afterwards in a reserved 110px band **below** the
  1280×720 page viewport, so nothing on the page is covered.
- No caption spans a scenario change. The band is empty for 0.4 s before each change, so the previous caption never
  sits over the next scenario's page.
- A phone-width part (390px wide) is centred in the frame. The video has no audio.

**Output:** 1280×830, 105.7 seconds.

**Order:** the useful comparison first, then VAT, then the refusals to rank, then the same-pack case, the recorded
tab and phone width.

| # | Time | Screen | Caption in the band below the page (exact) |
|---|---|---|---|
| 1 | 0:00.00–0:05.20 | `s1` page top: banner, heading, chips with **S1** active | "Guided walkthrough of an MVP prototype. Invented mills, not supplier facts. Scenario S1: delivery decides the winner." |
| 2 | 0:05.20–0:12.02 | pan down to the claim and both cards: A £64.00, B £67.95 delivered, inc VAT | "Order: 4 × 16kg to England mainland. Mill B has the lower product price (£62.00), but Mill A is lower delivered: £64.00 against £67.95, both inc VAT." |
| 3 | 0:12.02–0:18.90 | Mill A evidence **opened**: "SYNTHETIC: free delivery on orders over £50" | "Every figure keeps its quote: Mill A's free delivery comes from the quoted "over £50" rule (evidence opened)." |
| 4 | 0:19.49–0:23.29 | `s2` page top, **S2** chip active | "Scenario S2: a mixed VAT basis, compared only at a quoted rate." |
| 5 | 0:23.29–0:29.92 | pan down: E £69.00; F £67.20 inc VAT, "Converted from £56.00 ex VAT at the quoted 20%" | "Mixed VAT: Mill F quotes ex VAT, so it is compared at its quoted 20% rate: £56.00 ex VAT is £67.20 inc VAT." |
| 6 | 0:29.92–0:34.72 | held on the claim and cards | "£67.20 inc VAT is lower than Mill E's £69.00 inc VAT. No rate is ever assumed." |
| 7 | 0:35.32–0:39.12 | `s5` page top, **S5** chip active | "Scenario S5: the VAT basis is not confirmed." |
| 8 | 0:39.12–0:45.35 | pan down: "No ranking…"; P and Q "Quoted total £64.00 / £67.95, VAT not confirmed" | "Scott refuses to rank. Both totals stay visible (£64.00 and £67.95), marked "VAT not confirmed", but they are not compared." |
| 9 | 0:45.94–0:49.74 | `s4` page top, **S4** chip active | "Scenario S4: conflicting prices and an unmet minimum order." |
| 10 | 0:49.74–0:57.16 | pan down: A £64.00; C "Not verified" (£15.50 vs £14.00); D "Excluded" (minimum £100) | "Conflicting price records (£15.50 vs £14.00) and an unmet £100 minimum order are named. With one verified mill, there is no ranking." |
| 11 | 0:57.76–1:01.56 | `s3` page top, **S3** chip active | "Scenario S3: the same pack, written two ways." |
| 12 | 1:01.56–1:07.58 | pan down: G £69.85, H £71.50 delivered, inc VAT | "In the invented offer data the two mills write the pack differently ("16kg", "16 kg"; not shown on this page). It is still the same order, so they rank: £69.85 vs £71.50." |
| 13 | 1:08.17–1:11.97 | `recorded` page top: blue "Recorded" banner, "Saved records, 30 Oct" chip active | "The "Saved records, 30 Oct" tab." |
| 14 | 1:11.97–1:18.70 | short pan to "No recorded comparison… not included in this copy" | "The saved 30 October records are not included in this copy, so no recorded comparison is shown." |
| 15 | 1:18.70–1:22.90 | phone 390px: page top, heading, chips stacked, **S1** active | "Phone width (390 px): the same page, heading and scenario chips." |
| 16 | 1:22.90–1:28.52 | pan down: cards stacked, £64.00 and £67.95 | "At phone width the cards stack: £64.00 and £67.95 delivered, inc VAT." |
| 17 | 1:29.11–1:32.92 | phone: page top, **S5** active | "Phone width, scenario S5: the VAT basis is not confirmed." |
| 18 | 1:32.92–1:39.70 | pan down: P and Q "Quoted total …, VAT not confirmed" | "Unknown VAT at phone width: "Quoted total £64.00, VAT not confirmed"." |
| 19 | 1:39.70–1:45.70 | End card (no caption) | "Scott MVP prototype", then "Fixed example orders · no live prices · synthetic scenarios are invented · Guided walkthrough recorded offline from the local demo page, 25 November 2026". |

**End card:** the video in `docs/video/` ends with a plain "Scott MVP prototype" card.

**Short cut (about 50 seconds):** rows 1–8 (S1, S2 and S5) and the end card.

**Caption note (row 12):** the "16kg" / "16 kg" spellings are in the invented offer data (`scripts/compare_offline.py`),
not on the page itself, and the caption says so.

**Captions:** every caption figure was checked against the recorded frames.
