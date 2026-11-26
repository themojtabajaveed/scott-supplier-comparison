"""Offline engine test: fake browser serves fixtures, fake LLM answers extraction."""
import json
from scout.engine import agent
from scout.engine.browser import ReadOnlyBrowser
from scout.engine.trace import Trace

PAGE = ("Demo Strong Flour 16kg\n£\n17.45\n"  # invented page text
        "Standard delivery costs £3.85, and orders above £50* ship free at the standard rate (terms apply)")

WORKFLOW = {
    "name": "supplier",
    "question": "test",
    "fields": {"product_price": "price", "delivery_charge": "delivery charge"},
    "required": ["product_price", "delivery_charge"],
    "sites": [{"name": "mill_a", "url": "https://a.example/p"},
              {"name": "mill_b", "url": "https://b.example/p"}],
}

class FakeBrowser:
    def __init__(self, pages, link_map=None):
        self.pages = pages
        self.link_map = link_map or {}  # url -> [(anchor_text, href)]
    def goto(self, url):
        if url not in self.pages: raise RuntimeError("connection refused")
        self._url = url
        return url
    def text(self): return self.pages[self._url]
    def pick_evidence_link(self, missing_fields, exclude=()):
        # runs the REAL selection logic against the fake link graph
        real = ReadOnlyBrowser.__new__(ReadOnlyBrowser)
        real.links = lambda: self.link_map.get(self._url, [])
        real.current_url = lambda: self._url
        return ReadOnlyBrowser.pick_evidence_link(real, missing_fields, exclude=exclude)

class FakeLLM:
    """Returns canned extraction per site; tracks calls for retry assertions."""
    def __init__(self, answers): self.answers = answers; self.calls = []
    def generate_json(self, prompt):
        self.calls.append(prompt)
        url = next(l.split("Source URL: ")[1].splitlines()[0] for l in [prompt])
        return self.answers.get(url, {})

def test_run_extracts_verified_and_unverified(tmp_path):
    answers = {
        "https://a.example/p": {
            "product_price": {"value": "£17.45", "quote": "17.45"},
            "delivery_charge": {"value": "£3.85", "quote": "Standard delivery costs £3.85"},
        },
        "https://b.example/p": {
            "product_price": {"value": "£22.10", "quote": "not actually on the page"},
        },
    }
    browser = FakeBrowser({"https://a.example/p": PAGE, "https://b.example/p": PAGE})
    llm = FakeLLM(answers)
    trace = Trace(str(tmp_path / "trace.jsonl"))
    rows = agent.run("test", WORKFLOW, llm, browser, trace)
    trace.close()

    a, b = rows
    assert a["status"] == {"product_price": "verified", "delivery_charge": "verified"}
    # b: bad quote triggers one retry; FakeLLM returns the same bad answer, so it stays unverified
    assert b["status"]["product_price"] == "quote_not_on_page"  # retry got same bad quote
    assert b["status"]["delivery_charge"] == "unverified"
    # retry happened exactly once for b, no retry for a
    assert len(llm.calls) == 3
    # trace captured the lifecycle
    kinds = [json.loads(l)["kind"] for l in open(tmp_path / "trace.jsonl")]
    assert kinds[0] == "site_start" and "extracted" in kinds and "retry" in kinds and kinds[-1] == "run_complete"

def test_site_error_is_recorded_not_raised(tmp_path):
    browser = FakeBrowser({})  # every goto raises
    llm = FakeLLM({})
    trace = Trace(str(tmp_path / "t.jsonl"))
    rows = agent.run("test", WORKFLOW, llm, browser, trace)
    trace.close()
    assert rows[0]["error"] == "connection refused"
    assert rows[0]["fields"] == {"product_price": None, "delivery_charge": None}
    assert llm.calls == []  # no spend against an unread page

def test_malformed_llm_reply_means_unverified_not_crash():
    from scout.engine import extract
    class ListLLM:
        def generate_json(self, prompt): return ["not", "a", "dict"]
    got = extract.extract_fields("q", {"price": "p"}, "some page text", "https://x.example", ListLLM())
    assert got == {"price": None}
