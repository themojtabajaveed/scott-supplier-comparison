"""Bounded read-only navigation: follow evidence links for missing fields only."""
import json
from scout.engine import agent
from scout.engine.browser import ReadOnlyBrowser, BLOCKED_CLICK, EVIDENCE_HINT, _same_domain
from scout.engine.trace import Trace

ENTRY = "https://mill.example/flour-16kg"
POLICY = "https://mill.example/policies/shipping-policy"

ENTRY_PAGE = "Demo Strong Flour 16kg\n£\n12.34\nGreat for bread."
POLICY_PAGE = ("Shipping policy\nOur usual delivery charge on orders worth up to "
               "£24.99 is £5.40.")

WORKFLOW = {
    "name": "supplier",
    "question": "test",
    "fields": {"product_price": "price", "delivery_charge": "delivery charge"},
    "required": ["product_price", "delivery_charge"],
    "sites": [{"name": "mill", "url": ENTRY}],
}

class FakeBrowser:
    def __init__(self, pages, link_map):
        self.pages, self.link_map = pages, link_map
        self.visited = []
    def goto(self, url):
        if url not in self.pages: raise RuntimeError("404")
        self._url = url
        self.visited.append(url)
        return url
    def text(self): return self.pages[self._url]
    def pick_evidence_link(self, missing_fields, exclude=()):
        real = ReadOnlyBrowser.__new__(ReadOnlyBrowser)
        real.links = lambda: self.link_map.get(self._url, [])
        real.current_url = lambda: self._url
        return ReadOnlyBrowser.pick_evidence_link(real, missing_fields, exclude=exclude)

class FakeLLM:
    def __init__(self, by_url): self.by_url = by_url
    def generate_json(self, prompt):
        url = prompt.split("Source URL: ")[1].splitlines()[0]
        return self.by_url.get(url, {})

def _run(tmp_path, browser, llm, workflow=WORKFLOW):
    trace = Trace(str(tmp_path / "t.jsonl"))
    rows = agent.run("test", workflow, llm, browser, trace)
    trace.close()
    kinds = [json.loads(l)["kind"] for l in open(tmp_path / "t.jsonl")]
    return rows[0], kinds

def test_follows_policy_link_and_tags_source_url(tmp_path):
    browser = FakeBrowser(
        {ENTRY: ENTRY_PAGE, POLICY: POLICY_PAGE},
        {ENTRY: [("Delivery", POLICY), ("Buy now", "https://mill.example/cart")]})
    llm = FakeLLM({
        ENTRY: {"product_price": {"value": "£17.45", "quote": "17.45"},
                "delivery_charge": None},
        POLICY: {"delivery_charge": {"value": "£5.40", "quote": "£24.99 is £5.40"}},
    })
    row, kinds = _run(tmp_path, browser, llm)
    assert row["status"]["delivery_charge"] == "verified"
    assert row["fields"]["delivery_charge"]["source_url"] == POLICY
    assert row["pages_visited"] == [ENTRY, POLICY]
    assert "nav_extracted" in kinds and "site_done" in kinds
    assert "https://mill.example/cart" not in browser.visited  # transactional link never followed

def test_no_relevant_link_stops_and_stays_unverified(tmp_path):
    browser = FakeBrowser({ENTRY: ENTRY_PAGE},
                          {ENTRY: [("Contact us", "https://mill.example/contact"),
                                   ("Home", "https://mill.example/")]})
    llm = FakeLLM({ENTRY: {"product_price": {"value": "£17.45", "quote": "17.45"},
                           "delivery_charge": None}})
    row, kinds = _run(tmp_path, browser, llm)
    assert row["status"]["delivery_charge"] == "unverified"
    assert row["pages_visited"] == [ENTRY]
    assert "nav_stop" in kinds

def test_page_budget_bounds_navigation(tmp_path):
    p1, p2 = "https://mill.example/a", "https://mill.example/b"
    pages = {ENTRY: "flour £17.45", p1: "nothing relevant here", p2: "also nothing"}
    links = {ENTRY: [("Delivery", p1)], p1: [("Shipping", p2)], p2: [("Delivery", ENTRY)]}
    browser = FakeBrowser(pages, links)
    llm = FakeLLM({ENTRY: {"product_price": {"value": "£17.45", "quote": "£17.45"},
                           "delivery_charge": None},
                   p1: {"delivery_charge": None}, p2: {"delivery_charge": None}})
    workflow = dict(WORKFLOW, max_pages=2)
    row, kinds = _run(tmp_path, browser, llm, workflow)
    assert row["pages_visited"] == [ENTRY, p1]  # budget respected
    assert row["status"]["delivery_charge"] == "unverified"

def test_cross_domain_link_never_picked(tmp_path):
    browser = FakeBrowser({ENTRY: ENTRY_PAGE},
                          {ENTRY: [("Delivery info", "https://other-site.example/delivery")]})
    llm = FakeLLM({ENTRY: {"product_price": {"value": "£17.45", "quote": "17.45"},
                           "delivery_charge": None}})
    row, kinds = _run(tmp_path, browser, llm)
    assert row["pages_visited"] == [ENTRY]
    assert "nav_stop" in kinds

def test_domain_and_hint_helpers():
    assert _same_domain("www.demo-mill-three.example", "demo-mill-three.example")  # invented example host
    assert not _same_domain("mill.example", "other.example")
    assert EVIDENCE_HINT.search("Shipping policy")
    assert not EVIDENCE_HINT.search("Contact us")
    assert BLOCKED_CLICK.search("Add to basket")

class VariantFakeBrowser(FakeBrowser):
    """Selecting a variant swaps the page text, like a real pack-size dropdown."""
    def __init__(self, pages, link_map, variant_pages):
        super().__init__(pages, link_map)
        self.variant_pages = variant_pages  # url -> {option: page_text}
        self.selected = []
    def try_select_variant(self, option_text):
        options = self.variant_pages.get(self._url, {})
        if option_text in options:
            self.pages[self._url] = options[option_text]
            self.selected.append(option_text)
            return True
        return False

def test_variant_selection_recovers_price(tmp_path):
    entry_with_dropdown = "Demo Canadian-style Flour\nfrom £1.23\nSize: 1kg 16kg 25kg"
    after_select = "Demo Canadian-style Flour 16kg\n£15.67\nIn stock"
    browser = VariantFakeBrowser(
        {ENTRY: entry_with_dropdown},
        {ENTRY: []},
        {ENTRY: {"16kg": after_select}})
    llm = FakeLLM({ENTRY: {"product_price": None, "delivery_charge": None}})
    # after selection the same URL serves new text; FakeLLM keys on URL, so key by content via second entry
    llm.by_url[ENTRY] = None  # placeholder, replaced below by content-aware fake
    class ContentLLM:
        def generate_json(self, prompt):
            if "£15.67" in prompt:
                return {"product_price": {"value": "£15.67", "quote": "£15.67"},
                        "delivery_charge": None}
            return {"product_price": None, "delivery_charge": None}
    workflow = dict(WORKFLOW, sites=[{"name": "mill", "url": ENTRY, "variant_option": "16kg"}])
    row, kinds = _run(tmp_path, browser, ContentLLM(), workflow)
    assert browser.selected == ["16kg"]
    assert row["status"]["product_price"] == "verified"
    assert row["fields"]["product_price"]["source_url"] == ENTRY
    assert "variant_selected" in kinds

def test_variant_step_skipped_without_matching_option(tmp_path):
    browser = VariantFakeBrowser({ENTRY: ENTRY_PAGE}, {ENTRY: []}, {ENTRY: {}})
    llm = FakeLLM({ENTRY: {"product_price": {"value": "£17.45", "quote": "17.45"},
                           "delivery_charge": None}})
    workflow = dict(WORKFLOW, sites=[{"name": "mill", "url": ENTRY, "variant_option": "16kg"}])
    row, kinds = _run(tmp_path, browser, llm, workflow)
    assert browser.selected == []
    assert row["status"]["delivery_charge"] == "unverified"
    assert "variant_selected" not in kinds

def test_variant_json_endpoint_recovers_price(tmp_path):
    entry = "Demo Canadian-style Flour\nfrom £1.23\nSize: 1kg 16kg 25kg"
    js_url = ENTRY + ".js"
    js_text = "Demo Canadian-style Flour\n1kg | £1.23 | available=True\n16kg | £15.67 | available=True"
    browser = VariantFakeBrowser({ENTRY: entry}, {ENTRY: []}, {ENTRY: {}})
    browser.fetch_variant_data = lambda: (js_url, js_text)
    class LLM:
        def generate_json(self, prompt):
            if "£15.67" in prompt:
                return {"product_price": {"value": "£15.67", "quote": "£15.67"},
                        "delivery_charge": None}
            return {"product_price": None, "delivery_charge": None}
    workflow = dict(WORKFLOW, sites=[{"name": "mill", "url": ENTRY, "variant_option": "16kg"}])
    row, kinds = _run(tmp_path, browser, LLM(), workflow)
    assert row["status"]["product_price"] == "verified"
    assert row["fields"]["product_price"]["source_url"] == js_url
    assert row["fields"]["product_price"]["evidence_type"] == "store_json_endpoint"
    assert "variant_json_extracted" in kinds

def test_delivery_link_beats_gluten_free_collection():
 b=ReadOnlyBrowser.__new__(ReadOnlyBrowser)
 b.current_url=lambda:'https://mill.example/product'
 b.links=lambda:[('Gluten Free Flour','https://mill.example/gluten-free'),('Delivery','https://mill.example/delivery')]
 assert b.pick_evidence_link(['free_delivery_threshold','delivery_charge','delivery_geography'])=='https://mill.example/delivery'
