"""Eval harness: score a run's rows against a truth seed.

A run is the list of rows returned by engine.agent.run(). For each truth cell
marked verified with a value, the run's extracted value is compared after
normalisation. Outcomes per cell: correct | incorrect | missing_in_run.
Cells with verified: false in the truth seed are skipped (nothing to score).
"""
import re, yaml

def _norm(s):
    if s is None:
        return None
    s = str(s).lower()
    s = re.sub(r"[^a-z0-9£$.]+", " ", s).strip()
    return s

def _matches(run_value, truth_value):
    rv, tv = _norm(run_value), _norm(truth_value)
    if rv is None or tv is None:
        return False
    # numeric containment: "£17.45" in "£17.45 standard" counts as correct
    return tv in rv or rv in tv

def load_truth(path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)

def score_run(rows, truth):
    """rows: engine output. truth: loaded supplier_truth.yaml. Returns per-site report."""
    by_site = {r["site"]: r for r in rows}
    report = {}
    for site, spec in truth["sites"].items():
        row = by_site.get(site)
        cells = {}
        for field, cell in spec["fields"].items():
            if not cell.get("verified") or cell.get("value") in (None, ""):
                continue  # nothing truthful to score against
            run_item = (row or {}).get("fields", {}).get(field)
            if not run_item or not run_item.get("value"):
                cells[field] = "missing_in_run"
            elif _matches(run_item["value"], cell["value"]):
                cells[field] = "correct"
            else:
                cells[field] = "incorrect"
        report[site] = cells
    return report

def summary(report):
    counts = {"correct": 0, "incorrect": 0, "missing_in_run": 0}
    for cells in report.values():
        for outcome in cells.values():
            counts[outcome] += 1
    return counts
