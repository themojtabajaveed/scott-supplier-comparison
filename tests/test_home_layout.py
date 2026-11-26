"""The home page's recorded table (20 November 2026): Shipton's unconfirmed 16kg price is worded as on the
comparison sheet, and the table reads fully in its card at desktop and phone widths. Offline: saved result
files and a local server only; the layout test skips when Playwright's Chromium is not installed.
"""
import importlib.util
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_spec = importlib.util.spec_from_file_location('scout_ui_home', ROOT / 'scripts' / 'scout_ui.py')
ui = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ui)

needs_recordings = pytest.mark.skipif(
    not all((ui.RECORDED_DIR / (s + '-result.json')).is_file() for s in ui.RECORDED_SITES),
    reason='recorded live results not bundled')


def test_home_marks_demo_site_three_amount_as_not_confirmed_and_keeps_it_in_the_quotes(monkeypatch):
    # Invented demo recordings (tests/demo_suppliers.py); demo site three is the analogue whose page
    # quotes another pack size, so its 16kg price stays unresolved. Same assertions, invented amounts.
    sys.path.insert(0, str(ROOT / 'tests'))
    import demo_suppliers as demo
    demo.use_demo_recordings(monkeypatch, ui)
    page = ui.recorded_section(ui.RECORDED_DIR)
    three = page[page.index('href="/recorded/%s"' % demo.THREE):]
    three = three[:three.index('</tr>')]
    price = three[:three.index('</td>')]
    assert '<strong>16kg price not confirmed</strong>' in price
    assert 'Pack size: unresolved (16kg vs 1KG)' in price
    summary = price[:price.index('<details>')]
    assert '15.67' not in summary and 'pack size: 1KG / 16kg' not in summary  # no headline amount or packs
    quotes = price[price.index('<details>'):]
    assert 'not confirmed as the 16kg sack price' in quotes and '16kg | £15.67 | available=True' in quotes
    # Offer screen offer-v1: the recordings captured no structured offer record, so no price is a headline; the
    # quotes are kept.
    assert '<p class="cell-v">amount: £12.34</p>' not in page and '<p class="cell-v">amount: £14.56</p>' not in page
    assert '£12.34' in page and '£14.56' in page
    assert 'Price (16kg sack) quoted: 3 of 3 (3 with the 16kg price not confirmed)' in page
    assert page.count('As saved (read 30 October 2026): engine status literal_components_present.') == 2
    assert page.count('by screen offer-v1 from this run&#x27;s text evidence only') == 3


def test_other_pages_keep_their_tables_as_they_were(monkeypatch):
    sys.path.insert(0, str(ROOT / 'tests'))
    import demo_suppliers as demo
    demo.use_demo_recordings(monkeypatch, ui)  # invented demo recordings
    rows, links = ui.recorded_rows(ui.RECORDED_DIR)
    plain_table = ui.comparison_table(rows, links)  # result pages: no home flag
    assert 'home-cmp' not in plain_table
    # offer-v1: one rule on every page; no recorded October price is a headline (read date unknown here).
    assert 'Price (16kg sack) quoted: 3 of 3 (3 with the 16kg price not confirmed) ·' in plain_table
    assert 'As saved (read date not recorded)' in plain_table
    sheet = ui.comparison_body(ui.RECORDED_DIR)
    assert 'home-cmp' not in sheet and sheet.count('16kg price not confirmed') == 6  # 3 suppliers, table and card


def test_home_table_reads_fully_at_desktop_and_phone_widths(monkeypatch):
    sync = pytest.importorskip('playwright.sync_api')
    sys.path.insert(0, str(ROOT / 'tests'))
    import demo_suppliers as demo
    demo.use_demo_recordings(monkeypatch, ui)  # invented demo recordings
    server = ui.make_server(0, recorded_dir=ui.RECORDED_DIR)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync.sync_playwright() as p:
            try:
                browser = p.chromium.launch()
            except Exception as exc:  # Chromium not installed
                pytest.skip('Chromium not available: %s' % exc)
            try:
                for width in (1280, 1024, 900, 700, 414):
                    page = browser.new_page(viewport={'width': width, 'height': 900})
                    page.goto('http://127.0.0.1:%d/' % server.server_address[1])
                    m = page.evaluate('''() => { const s = document.querySelector('#recorded .home-cmp');
                        return {clipped: s.querySelector('table').scrollWidth - s.clientWidth,
                                page: document.documentElement.scrollWidth - document.documentElement.clientWidth,
                                columns: s.querySelectorAll('tbody tr:first-child td').length}; }''')
                    assert m['clipped'] <= 0 and m['page'] <= 0, (width, m)
                    assert m['columns'] == 5, (width, m)  # every field column is still there
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
