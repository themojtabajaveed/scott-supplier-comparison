"""Live supplier run. Requires: playwright installed, GEMINI_API_KEY in env (free tier).
Never hardcode the key. Local only; read-only pages; no accounts, no spend.

Usage:
  GEMINI_API_KEY=... python3 scripts/run_supplier_live.py --site wessex_mill
  GEMINI_API_KEY=... python3 scripts/run_supplier_live.py --score traces/rows-*.json
"""
import argparse, glob, json, os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))



def run_site(site_name, domain="supplier", atomic=False, dry_run=False):
    from scout.engine.agent import run
    from scout.engine.browser import ReadOnlyBrowser
    from scout.engine.llm import GeminiFree
    from scout.engine.trace import Trace
    from scout.workflows import supplier, provider

    if dry_run:
        selected=(provider if domain == "provider" else supplier).WORKFLOW
        print(json.dumps({"domain":domain,"atomic":atomic,"sites":[s["name"] for s in selected["sites"] if not site_name or s["name"]==site_name],"network_used":False}))
        return
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        sys.exit("GEMINI_API_KEY not set; refusing to run (fail-closed on missing key)")
    wf = dict((provider if domain == "provider" else supplier).WORKFLOW)
    if atomic:
        wf["atomic_fields"]=(provider if domain == "provider" else supplier).ATOMIC_FIELDS
        wf["atomic_requirements"]=getattr(provider if domain == "provider" else supplier,"ATOMIC_REQUIREMENTS",{})
    if site_name:
        wf["sites"] = [s for s in wf["sites"] if s["name"] == site_name]

        if not wf["sites"]:
            sys.exit(f"unknown site {site_name}")
    stamp = int(time.time())  # one stamp, so the rows file pairs with its trace
    trace_path = f"traces/supplier-{site_name or 'all'}-{stamp}.jsonl"
    os.makedirs("traces", exist_ok=True)
    trace = Trace(trace_path)
    browser = ReadOnlyBrowser()
    # Binding confirmation is intentionally absent until independently resolved.
    from scout import live_run
    if not live_run.binding_confirmed(os.environ):
        sys.exit("Free-project/key binding not confirmed; no generation permitted")
    # One shared ledger (eval-results/live-ledger.jsonl) and cumulative caps with the local UI;
    # this script keeps its own per-run limits on top of them.
    try:
        llm = live_run.make_client(key, per_run={"calls": 8, "input": 40000, "output": 8000})
    except live_run.LedgerError as e:
        sys.exit(f"Usage ledger unreadable ({e}); refusing to run")
    # Local caps are not evidence of free billing.
    try:
        rows = run(wf["question"], wf, llm, browser, trace)
    finally:
        browser.close()
        trace.close()
    out = f"traces/rows-{site_name or 'all'}-{stamp}.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=1)
    print(json.dumps({"rows_file": out, "trace": trace_path, "llm_spent": llm.spent,
                      "sites": [{ "site": r["site"],
                                  "status": r.get("status", {f:v["status"] for f,v in r.get("atomic_fields",{}).items()}),
                                  "pages": r.get("pages_visited", []),
                                  "page_texts": len(r.get("page_texts") or []),
                                  "error": r.get("error")} for r in rows]}, indent=1))


def score(pattern):
    from scout.evals import harness
    rows = []
    for path in sorted(glob.glob(pattern)):
        with open(path, encoding="utf-8") as f:
            rows.extend(json.load(f))
    truth = harness.load_truth("scout/evals/supplier_truth.yaml")
    report = harness.score_run(rows, truth)
    print(json.dumps({"summary": harness.summary(report), "per_site": report}, indent=1))

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--site")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--atomic", action="store_true")
    ap.add_argument("--domain", choices=["supplier","provider"], default="supplier")
    ap.add_argument("--score", metavar="GLOB")
    a = ap.parse_args()
    if a.score:
        score(a.score)
    else:
        run_site(a.site, a.domain, a.atomic, a.dry_run)
