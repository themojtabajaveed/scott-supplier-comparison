"""Buyer-readable M1 view (/m1): functional and negative scenarios, no internal codes, no outbound socket."""
import importlib.util
import re
import socket
import sys
import threading
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
_spec = importlib.util.spec_from_file_location('scout_ui_m1', ROOT / 'scripts' / 'scout_ui.py')
ui = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ui)
from scout import m1_view  # noqa: E402

CODES = re.compile(r'no_structured_offer|not_confirmed|not_comparable|unverifiable|ineligible|free_threshold|'
                   r'cheapest_among_verified|abstained|offer_state|\{"|\bNone\b|demo_mill_')
KEYS = ['recorded', 's1', 's2', 's3', 's4', 's5']


def text(html):
    return re.sub(r'<[^>]+>', ' ', html)


@pytest.mark.parametrize('key', KEYS)
def test_every_scenario_is_plain_words_with_order_date_and_disclosure(key):
    html = m1_view.body(key)
    assert not CODES.search(text(html)), CODES.search(text(html)).group(0)
    assert 'Order answered:' in html and 'Evidence date:' in html
    if key == 'recorded' and 'not included in this copy' in html:  # the saved records are not included
        assert 'class="card m1-row"' not in html
    else:
        assert '<details class="ev">' in html or 'No quotes were used' in html


def test_banners_separate_recorded_from_synthetic():
    assert m1_view.banner('recorded') == 'Recorded: saved 30 Oct 2026 records, not live'
    assert all(m1_view.banner(k) == 'Synthetic: invented mills, not supplier facts' for k in KEYS[1:])


def test_recorded_says_the_saved_records_are_not_in_this_copy():
    # The saved 30 October records are not included, so the recorded tab says so and shows no supplier, price or
    # quote.
    t = text(m1_view.body('recorded'))
    assert ('No recorded comparison: the saved 30 October 2026 records are not included in this copy (they are '
            'kept privately), so nothing from them is shown.') in t
    assert 'none shown: the saved 30 October 2026 records are not included in this copy' in t
    assert '£' not in t.split('Prices count only')[0] and 'Wessex' not in t and 'Shipton' not in t
def test_s1_ranks_on_known_vat_and_delivery_decides():
    t = text(m1_view.body('s1'))
    assert ('Lowest delivered among the 2 suppliers with verified prices: Demo Mill A (invented) £64.00. Demo Mill B '
            '(invented) has the lower product price (£62.00) but costs more delivered (£67.95).') in t
    assert 'product price quoted VAT-inclusive' in t and '£64.00 delivered, inc VAT' in t


def test_s2_mixed_vat_shows_the_quoted_rate_conversion():
    t = text(m1_view.body('s2'))
    assert 'Demo Mill F (invented) £67.20 inc VAT' in t and 'at the quoted 20%' in t
    # the card shows the normalised figure the ranking used, and the rate quote is in its evidence
    assert 'Converted from £56.00 ex VAT at the quoted 20%' in t
    assert 'VAT rate quoted:' in t and 'SYNTHETIC: all prices exclude VAT at 20%' in t


def test_negative_unknown_vat_refuses_ranking():
    t = text(m1_view.body('s5'))
    head = t.split('Evidence date')[0]
    assert 'No ranking: the VAT basis is not confirmed for every price and charge' in head and 'Lowest' not in head
    # uncertainty is as prominent as the amount: no bare "delivered" headline for an unknown-VAT total
    assert 'Quoted total £64.00, VAT not confirmed' in t and 'Quoted total £67.95, VAT not confirmed' in t
    assert '£64.00 delivered' not in t and '£67.95 delivered' not in t
    assert 'VAT basis not stated' in t  # the reason stays on each card and in the full claim wording


def test_recorded_tab_shows_no_supplier_cards_or_quotes_when_records_are_absent():
    html = m1_view.body('recorded')
    assert 'class="card m1-row"' not in html and '<details class="ev">' not in html


def test_negative_conflicting_and_excluded_are_named_in_words():
    t = text(m1_view.body('s4'))
    assert 'Only one supplier could be verified, so there is no ranking' in t
    assert 'Not verified' in t and 'conflicting prices' in t
    assert 'Excluded' in t and 'minimum order value £100 not met' in t


def test_unknown_scenario_key_falls_back_to_recorded():
    assert m1_view.body('<script>') == m1_view.body('recorded')


def test_page_over_http_makes_no_outbound_connection(monkeypatch):
    real = socket.socket.connect
    outbound = []

    def guarded(sock, address):
        host = address[0] if isinstance(address, tuple) else address
        if not (isinstance(host, str) and (host.startswith('127.') or host in ('localhost', '::1'))):
            outbound.append(address)
            raise OSError('outbound connection blocked in test')
        return real(sock, address)
    monkeypatch.setattr(socket.socket, 'connect', guarded)
    server = ui.make_server(port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        for key in KEYS:
            with urllib.request.urlopen('http://127.0.0.1:%d/m1?s=%s' % (port, key), timeout=10) as resp:
                html = resp.read().decode('utf-8')
            assert resp.status == 200 and 'M1 comparison' in html
            assert m1_view.banner(key) in html
            assert not CODES.search(text(html.split('<main>')[1].split('</main>')[0]))
    finally:
        server.shutdown()
        server.server_close()
    assert outbound == []


def test_tabs_have_plain_names_with_ids_secondary_and_synthetic_date_is_short():
    html = m1_view.body('s3')
    for name in ('Saved records, 30 Oct', 'Delivery decides the winner', 'Mixed VAT, quoted rate',
                 'Same pack, written two ways', 'Conflicting and excluded', 'VAT unknown: no ranking'):
        assert name in html
    assert '<span class="m1-id">S3</span>' in html
    assert 'Evidence date:</strong> undated invented quotes' in html


def test_mixed_basis_cards_show_the_same_basis_figure_as_the_primary_headline():
    html = m1_view.body('s2')
    heads = dict(re.findall(r'<h3>([^<]+)</h3><p class="m1-total">([^<]+)</p>', html))
    # both primary headlines are on the same (VAT-inclusive) basis the ranking compared
    assert heads == {'Demo Mill E (invented)': '£69.00 delivered, inc VAT',
                     'Demo Mill F (invented)': '£67.20 delivered, inc VAT'}, heads
    assert '£56.00' not in ''.join(heads.values())  # the ex-VAT original is secondary, never the headline
    assert '<p class="m1-reason">Converted from £56.00 ex VAT at the quoted 20%</p>' in html
