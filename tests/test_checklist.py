from scout.engine import checklist

def test_all_verified():
    got = {"price": {"value": "£17.45", "quote": "q", "quote_verbatim": True}}
    assert checklist.check(got, ["price"]) == {"price": "verified"}

def test_missing_field_is_unverified():
    assert checklist.check({}, ["price"]) == {"price": "unverified"}
    assert checklist.check({"price": None}, ["price"]) == {"price": "unverified"}

def test_quote_not_on_page():
    got = {"price": {"value": "£17.45", "quote": "made up", "quote_verbatim": False}}
    assert checklist.check(got, ["price"]) == {"price": "quote_not_on_page"}

def test_summary_counts():
    s = {"a": "verified", "b": "unverified", "c": "quote_not_on_page", "d": "verified"}
    assert checklist.summary(s) == {"verified": 2, "unverified": 1, "quote_not_on_page": 1}
