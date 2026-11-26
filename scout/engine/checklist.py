"""Completeness check: a field is verified only with value + verbatim quote."""

def check(extracted, required):
    status = {}
    for f in required:
        item = extracted.get(f)
        if item is None:
            status[f] = "unverified"
        elif not item.get("quote_verbatim", False):
            status[f] = "quote_not_on_page"
        else:
            status[f] = "verified"
    return status

def summary(status):
    return {"verified": sum(1 for v in status.values() if v == "verified"),
            "unverified": sum(1 for v in status.values() if v == "unverified"),
            "quote_not_on_page": sum(1 for v in status.values() if v == "quote_not_on_page")}
