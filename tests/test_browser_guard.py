import pytest
from scout.engine.browser import ReadOnlyBrowser, BLOCKED_CLICK

def _bare_browser():
    b = ReadOnlyBrowser.__new__(ReadOnlyBrowser)  # no playwright needed
    class FakePage:
        def __getattr__(self, name):
            raise AssertionError("page must not be touched when guard blocks")
    b.page = FakePage()
    return b

@pytest.mark.parametrize("label", ["Buy now", "Add to cart", "Add to basket",
                                   "Checkout", "Pay £24.90", "Submit order", "Place Order"])
def test_blocked_click_labels(label):
    with pytest.raises(ValueError):
        _bare_browser().click(label)

@pytest.mark.parametrize("label", ["Delivery & Returns tab", "16kg", "Read more reviews"])
def test_allowed_labels_pass_the_regex(label):
    assert not BLOCKED_CLICK.search(label)

def test_blocked_option():
    with pytest.raises(ValueError):
        _bare_browser().select_option("Size", "Buy 16kg now")

def test_non_http_url_refused():
    with pytest.raises(ValueError):
        _bare_browser().goto("file:///etc/passwd")

def test_try_select_variant_never_raises():
    b = ReadOnlyBrowser.__new__(ReadOnlyBrowser)
    class ExplodingPage:
        def query_selector_all(self, *a): raise RuntimeError("page exploded")
    b.page = ExplodingPage()
    assert b.try_select_variant("16kg") is False
