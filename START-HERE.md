# Start here: Scott (MVP prototype)

Scott compares the **delivered cost of one fixed order** across suppliers. It **refuses to rank** when the evidence
does not support a ranking. Every demo here uses **invented suppliers** on reserved `.example` addresses, with no live
prices.

- **Overview:** [README.md](README.md), with screenshots, architecture, setup and verification.
- **Video:** [docs/video/scott-m1-walkthrough.mp4](docs/video/scott-m1-walkthrough.mp4). The storyboard is
  [STORYBOARD-DEMO.md](STORYBOARD-DEMO.md).

## Quickstart (about 2 minutes)

**Requirement:** Python 3.13.

```
python3 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
python -m pip install -r requirements.txt
```

The install needs a package registry. Everything below runs offline, with no keys and no network.

**1. See the comparison page.** Start the demo UI, then open http://127.0.0.1:8017/m1 and use the scenario chips (S1 to
S5):

```
python -S scripts/scout_ui_demo.py
```

**2. Run the comparison from the command line.** This writes `sample-runs/compare-<timestamp>/comparison.md` and
`result.json`:

```
python -S scripts/compare_offline.py --synthetic
```

**3. Run a sample question end to end on invented sources.** Each run writes a new `sample-runs/run-<timestamp>/`
folder holding `result.json`, `comparison.md` and `trace.md`, and never overwrites an existing one:

```
python -S scripts/scout_question.py --question 'Compare strong white bread flour 16kg delivery conditions' --demo --output-dir sample-runs
python -S scripts/scout_question.py --question 'Compare Ministral 3 8B Standard USD uncached input and output per million tokens' --demo --output-dir sample-runs
```

**4. Build the invented demo scorecard.** It prints JSON:

```
python scripts/build_demo_scorecard.py
```

**5. Inspect saved evidence.** This prints JSON (see [EVIDENCE-LEDGER.md](EVIDENCE-LEDGER.md)):

```
python -S scripts/evidence_ledger.py demo/recordings/demo_mill_one-result.json
```

**6. Run the tests.** On Python 3.13 the expected result is `505 passed, 2 skipped`. The 2 skipped tests need the
optional browser extra; see "Set up" in [README.md](README.md).

```
python -m pytest -q
```

## What the demo shows

| Scenario | What happens |
|---|---|
| S1 | Delivery decides the winner: the mill with the lower product price costs more delivered. |
| S2 | A mixed VAT basis is compared only at an explicitly quoted rate. |
| S3 | The same pack written two ways is still the same order. |
| S4 | Conflicting prices and an unmet minimum order are named, so there is no ranking. |
| S5 | The VAT basis is not confirmed, so ranking is refused. |

The "Saved records, 30 Oct" tab says that the real recorded runs are not included.

## Local web UI and the live connector

`python -S scripts/scout_ui.py` starts the full local UI on 127.0.0.1 only, and it fetches nothing on its own.

The live connector is **disabled by default**. A live run of one configured supplier page is refused unless all of
these hold:
- an API key is set in the server's own environment;
- a local `scott.local.json` exists, copied from `scott.local.example.json` and never committed;
- Playwright is installed;
- a usage ledger file exists. This repository includes none, and a missing ledger refuses every live run.

The connector's limits are set in code, in `scout/live_run.py`: a per-run call cap (`UI_RUN_CALL_CAP`) and cumulative
call and token caps (`CUMULATIVE_CAPS`). A run that could exceed them is refused before any model call. These are local
counters: they do not show what a provider bills.
