import yaml
from scout.evals import harness
from scout.workflows import demo_supplier

# The invented demo reference.
TRUTH = "demo/evals/demo_supplier_truth.yaml"

def test_truth_loads_and_covers_workflow_sites():
    truth = harness.load_truth(TRUTH)
    workflow_sites = {s["name"] for s in demo_supplier.SITES}
    assert set(truth["sites"].keys()) == workflow_sites

def test_verified_cells_have_value_and_evidence():
    truth = harness.load_truth(TRUTH)
    for site, spec in truth["sites"].items():
        for field, cell in spec["fields"].items():
            if cell.get("verified"):
                assert cell.get("value"), f"{site}.{field} verified without value"
                assert cell.get("quote") or cell.get("evidence"), f"{site}.{field} no quote/evidence"
            else:
                assert cell.get("value") in (None, ""), f"{site}.{field} unverified but has value"

def test_urls_are_https():
    truth = harness.load_truth(TRUTH)
    for site, spec in truth["sites"].items():
        assert spec["url"].startswith("https://")

def test_harness_scoring_against_fake_run():
    truth = harness.load_truth(TRUTH)
    rows = [{"site": "demo_mill_one", "url": truth["sites"]["demo_mill_one"]["url"],
             "fields": {"product_price": {"value": "£12.34", "quote": "x", "quote_verbatim": True},
                        "delivery_charge": {"value": "£3.80 standard", "quote": "x", "quote_verbatim": True}},
             "status": {}}]
    report = harness.score_run(rows, truth)
    assert report["demo_mill_one"]["product_price"] == "correct"
    assert report["demo_mill_one"]["delivery_charge"] == "correct"
    assert report["demo_mill_one"]["delivery_time"] == "missing_in_run"
    assert report["demo_mill_two"]["product_price"] == "missing_in_run"
    s = harness.summary(report)
    assert s["correct"] == 2 and s["incorrect"] == 0
