# Testing

## Running the tests

```
python -m pytest -q
```

| Environment | Result |
|---|---|
| Python 3.13, `requirements.txt` | 505 passed, 2 skipped |
| Python 3.12, Playwright 1.47.0, Chromium 129 (build 1134) | 507 passed, 0 skipped |

The 2 tests that skip without Playwright's Chromium are:
- `tests/test_network_integration.py::test_chromium_blocks_post_and_redirect_before_server_receives`. It runs the
  product's own Python request handler (`ReadOnlyBrowser._route_request` in `scout/engine/browser.py`) in Chromium
  against a local HTTP server, and checks that a POST and a redirect target never reach the server.
  - **Negative control:** with the allow decision (`network_allowed`) forced to allow everything, this test fails,
    because the POST reaches the server.
- `tests/test_home_layout.py::test_home_table_reads_fully_at_desktop_and_phone_widths`.

The handler's decision logic is also unit-tested without a browser
(`tests/test_planner_loop.py::test_real_route_handler_aborts_before_network`). A Node Playwright port of the
request-blocking check is in `tests/browser_node/`.

**Scope:** the counts above come from the development environment. A separate clean-install run on 26 November 2026
(new virtual environment from a fresh unzip, Python 3.13.18, PyYAML 6.0.4, pytest 9.2.0, resolved from the unpinned
`requirements.txt`) gave `505 passed, 2 skipped`, and the commands in `START-HERE.md` ran. The two skipped tests need
Playwright, which was not installed in that run.

## Test data

- **Invented data only.** Every fixture uses invented suppliers on reserved `.example` addresses, or invented amounts
  and wording. No test contains third-party page text or real supplier prices.
- **Synthetic contract.** `tests/comparison_expected.json` (23 cases) and `tests/adversarial_expected.json` (10 cases)
  are synthetic derivatives of a non-public contract. [`tests/COMPARISON-DERIVATION.md`](../tests/COMPARISON-DERIVATION.md)
  documents the derivation and a check that uses no engine code (33 of 33).
- **Demo recordings.** `demo/recordings/` and `demo/later-runs/` hold results produced by the real engine over invented
  pages. Tests that read saved results use these.

## Coverage limits

These checks depend on real recorded data, which this repository does not include, so they are not part of this suite:
- **Demo amounts vs real amounts.** A check that the demo fixtures never equal a real recorded amount. The real amounts
  are not in this repository.
- **Byte-for-byte report comparison.** A byte-for-byte comparison with one preserved real report. Here,
  `test_current_code_sets_exactly_the_two_guarded_status_cells` covers only the two guarded status cells.
- **One real later run.** One parameter instance of
  `tests/test_plain_view.py::test_comparison_table_lists_every_quote_and_source` that reads a real later run. The same
  test runs on the three demo recordings.

These branches are covered with invented data instead:
- **The "text removed" label.** The M1 view labels removed quotes as removed (`tests/test_uncovered_paths_synthetic.py`).
- **Both later-run branches.** "Same amounts" runs on `demo/later-runs/`, and "different amounts" runs in
  `tests/test_uncovered_paths_synthetic.py`.
- **Constructed row.** One assertion in
  `tests/test_plain_view.py::test_recorded_comparison_reports_real_coverage_and_why_details_are_missing` checks the "no
  delivery or shipping page was read" wording on a constructed copy of a demo row.

## Live connector tests

The live connector is tested only with fake browsers and fake model transports, with no network and no real key. The
tests give every run a temporary local configuration holding a placeholder project (`tests/conftest.py`).
- **Guide check.** `tests/test_live_ui.py::StartHereMatchesConstants::test_start_here_live_section_points_to_the_limits_in_code`
  reads the limits from `scout/live_run.py`. It checks that `START-HERE.md` points to them and does not restate figures,
  which could go stale.
