"""The shared engine: browse -> extract -> check -> retry once -> bounded navigation -> report.

Navigation: when required fields stay unverified on the entry page, the agent
follows same-domain links whose anchor text hints at the missing evidence
(delivery/shipping/policy/faq), up to a per-site page budget. Every visited
page is traced; each accepted fact keeps the URL of the page its quote came
from. Read-only: navigation is GET-only through the browser wrapper, and its
click guard still applies.
"""
from . import extract, checklist

DEFAULT_MAX_PAGES = 3  # entry page + up to 2 evidence pages per site

def _missing(status):
    return [f for f, s in status.items() if s == "unverified"]

def run(question, workflow, llm, browser, trace):
    """workflow: dict with fields, required, sites [{name, url}], optional max_pages."""
    if workflow.get("atomic_fields"):
        from .atomic_run import run_atomic
        return run_atomic(question, workflow, llm, browser, trace)
    max_pages = workflow.get("max_pages", DEFAULT_MAX_PAGES)
    rows = []
    base_question = question
    for site in workflow["sites"]:
        question = site.get("question", workflow.get("question", base_question))
        trace.log("site_start", site=site["name"], url=site["url"])
        try:
            if hasattr(browser,"set_source"):browser.set_source(site["url"])
            entry_url = browser.goto(site["url"])
            page_text = browser.text()
        except Exception as e:
            trace.log("site_error", site=site["name"], error=str(e))
            rows.append({"site": site["name"], "url": site["url"], "error": str(e),
                         "fields": {f: None for f in workflow["required"]}, "status": {},
                         "pages_visited": []})
            continue
        pages = [entry_url]
        got = extract.extract_fields(question, workflow["fields"], page_text, entry_url, llm)
        for item in got.values():
            if item:
                item["source_url"] = entry_url
        status = checklist.check(got, workflow.get("research_fields", workflow["required"]))
        trace.log("extracted", site=site["name"], page=entry_url, status=status)

        # one same-page retry for quotes that were not verbatim
        bad = [f for f, s in status.items() if s == "quote_not_on_page"]
        if bad:
            trace.log("retry", site=site["name"], page=entry_url, fields=bad)
            got2 = extract.extract_fields(question, {f: workflow["fields"][f] for f in bad},
                                          page_text, entry_url, llm)
            for f in bad:
                if got2.get(f) and got2[f].get("quote_verbatim"):
                    got2[f]["source_url"] = entry_url
                    got[f] = got2[f]
            status = checklist.check(got, workflow.get("research_fields", workflow["required"]))
            trace.log("retry_result", site=site["name"], page=entry_url, status=status)

        # variant dropdown: if the site declares one, select it and re-read the page
        if site.get("variant_option") and _missing(status):
            if browser.try_select_variant(site["variant_option"]):
                page_text = browser.text()
                trace.log("variant_selected", site=site["name"], page=entry_url,
                          option=site["variant_option"])
                needed = {f: workflow["fields"][f] for f in _missing(status)}
                got2 = extract.extract_fields(question, needed, page_text, entry_url, llm)
                for f, item in got2.items():
                    if item and item.get("quote_verbatim"):
                        item["source_url"] = entry_url
                        got[f] = item
                status = checklist.check(got, workflow.get("research_fields", workflow["required"]))
                trace.log("variant_extracted", site=site["name"], page=entry_url, status=status)

        # variant JSON evidence: store's own data endpoint when the selector can't be operated
        if _missing(status) and getattr(browser, "fetch_variant_data", None):
            vd = browser.fetch_variant_data()
            if vd:
                js_url, js_text = vd
                needed = {f: workflow["fields"][f] for f in _missing(status)}
                got2 = extract.extract_fields(question, needed, js_text, js_url, llm)
                for f, item in got2.items():
                    if item and item.get("quote_verbatim"):
                        item["source_url"] = js_url
                        item["evidence_type"] = "store_json_endpoint"
                        got[f] = item
                status = checklist.check(got, workflow.get("research_fields", workflow["required"]))
                trace.log("variant_json_extracted", site=site["name"], page=js_url, status=status)

        # bounded read-only navigation for still-missing fields
        while _missing(status) and len(pages) < max_pages:
            link = browser.pick_evidence_link(_missing(status), exclude=pages)
            if not link:
                trace.log("nav_stop", site=site["name"], reason="no relevant unvisited link")
                break
            try:
                url = browser.goto(link)
                text = browser.text()
            except Exception as e:
                trace.log("nav_error", site=site["name"], url=link, error=str(e))
                break
            pages.append(url)
            needed = {f: workflow["fields"][f] for f in _missing(status)}
            got2 = extract.extract_fields(question, needed, text, url, llm)
            for f, item in got2.items():
                if item and item.get("quote_verbatim"):
                    item["source_url"] = url
                    got[f] = item
            status = checklist.check(got, workflow.get("research_fields", workflow["required"]))
            trace.log("nav_extracted", site=site["name"], page=url, status=status)

        trace.log("site_done", site=site["name"], pages=pages, status=status)
        rows.append({"site": site["name"], "url": entry_url, "fields": got,
                     "status": status, "pages_visited": pages})
    trace.log("run_complete", sites=len(rows))
    return rows
