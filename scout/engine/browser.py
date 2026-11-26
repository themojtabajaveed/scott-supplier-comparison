"""Read-only browser wrapper (Playwright). Imported lazily so offline tests need no browser.

Guard rails: http/https GET navigation only; no form submission, no clicks on
elements labelled buy/order/submit/pay/checkout. pick_evidence_link only
surfaces same-domain http(s) links whose anchor text suggests factual
evidence pages. This agent researches; it never transacts.
"""
import re
from urllib.parse import urljoin, urlparse

BLOCKED_CLICK = re.compile(r"buy|order|submit|pay|checkout|add to (cart|basket)|purchase", re.I)
EVIDENCE_HINT = re.compile(
    r"delivery|shipping|dispatch|postage|policy|policies|faq|terms|price|pricing|"
    r"variant|size|pack|product", re.I)

def _same_domain(entry_netloc, href_netloc):
    bare = lambda n: n.lower().removeprefix("www.")
    return bare(href_netloc) == bare(entry_netloc)

def safe_destination(url, roots):
    import ipaddress
    p=urlparse(url)
    if p.scheme not in ('http','https') or not p.hostname or p.username or p.password:return False
    host=p.hostname.casefold()
    if host=='localhost' or host.endswith(('.local','.internal')):return False
    try:
        if not ipaddress.ip_address(host).is_global:return False
    except ValueError:pass
    if p.port not in (None,80,443):return False
    if re.search(r'/(?:cart|basket|checkout|account|login|logout|orders?|purchase|pay|admin)(?:/|$|[.?])',p.path,re.I):return False
    if re.search(r'(?:^|&)(?:action|add-to-cart|checkout|submit|delete|token|key)=',p.query,re.I):return False
    return not roots or any(_same_domain(urlparse(r).netloc,p.netloc) for r in roots)

def network_allowed(method,url,resource_type,roots):
    # All methods except GET/HEAD denied, including analytics POST. Third-party
    # static assets allowed only over public HTTP(S); documents/fetch/XHR stay on source.
    if method.upper() not in ('GET','HEAD'):return False
    scoped=resource_type not in ('image','stylesheet','font','media','script')
    return safe_destination(url,roots if scoped else [])

class ReadOnlyBrowser:
    def __init__(self):
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch()
        self.page = self._browser.new_page(service_workers="block")
        self._roots=[]
        self.page.route("**/*", self._route_request)

    def _route_request(self, route):
        request=route.request
        if not network_allowed(request.method,request.url,request.resource_type,self._roots):
            route.abort();return
        # Chromium routing may not intercept every hop after continue_(). Fetch
        # without redirect following; reject all redirects before any second hop.
        response=route.fetch(max_redirects=0)
        if 300<=response.status<400:
            route.abort();return
        route.fulfill(response=response)

    def goto(self, url):
        if not url.startswith(("http://", "https://")):
            raise ValueError(f"refusing non-http(s) url: {url}")
        roots=getattr(self,'_roots',[]) or [url]
        if not safe_destination(url,roots):raise ValueError('unsafe destination')
        self._roots=roots
        self.page.goto(url, wait_until="domcontentloaded")
        if not safe_destination(self.current_url(),roots):raise ValueError('unsafe redirect')
        return self.current_url()

    def set_source(self, url):
        if not safe_destination(url,[]):raise ValueError('unsafe source')
        self._roots=[url]

    def current_url(self):
        return self.page.url

    def text(self):
        self.expand_collapsed()
        return self.page.inner_text("body")

    def expand_collapsed(self):
        """Bounded, visible evidence tabs only. No forced or hidden control changes."""
        clicked = 0
        seen = set()
        for selector in ("[role=tab]", "button[aria-expanded='false']", "summary"):
            for el in self.page.query_selector_all(selector):
                if clicked >= 6:
                    return
                try:
                    label = el.inner_text().strip()
                    if (not label or label in seen or BLOCKED_CLICK.search(label)
                            or not EVIDENCE_HINT.search(label) or not el.is_visible()):
                        continue
                    seen.add(label)
                    el.click(timeout=1500)
                    clicked += 1
                except Exception:
                    continue

    def semantic_text(self):
        """Label real table cells with headers; keep surrounding page text separate."""
        from .table_evidence import render_tables
        self.expand_collapsed()
        tables=self.page.eval_on_selector_all("table", r"""els => els.map(t => {
          let p=t.previousElementSibling, context='';
          for(let n=0;p && n<5;n++,p=p.previousElementSibling){
            if(/^H[1-6]$/.test(p.tagName)){context=p.innerText;break;}
          }
          const rows=[...t.querySelectorAll('tr')];
          const headers=[...t.querySelectorAll('thead th')].map(c=>c.innerText.trim());
          let scope=t.parentElement;
          for(let n=0;scope && n<4;n++,scope=scope.parentElement){
            if(scope.querySelector('table')===t && scope.querySelectorAll('table').length===1 &&
               scope.querySelector('[aria-pressed], [role=checkbox]'))break;
          }
          const controls=scope && scope.querySelectorAll('table').length===1 ?
            [...scope.querySelectorAll('[aria-pressed],[role=checkbox]')].map(e=>({
              text:e.innerText.trim(),role:e.getAttribute('role'),
              pressed:e.getAttribute('aria-pressed'),checked:e.getAttribute('aria-checked'),
              label:e.closest('label')?.innerText.trim() || e.parentElement?.querySelector('label')?.innerText.trim() || ''})) : [];
          const unit=scope && scope.querySelectorAll('table').length===1 ?
            [...scope.querySelectorAll('span')].map(e=>e.innerText.trim()).find(s=>/^Prices\s+\//i.test(s)) || '' : '';
          return {context,controls,unit,headers,rows:rows.filter(r=>!r.closest('thead')).map(r=>
            [...r.querySelectorAll('th,td')].map(c=>c.innerText.trim()))};
        })""")
        table_text=render_tables(tables)
        body=self.page.inner_text("body")
        self.last_original_text=body
        self.last_tables=tables
        return ("SEMANTIC TABLE EVIDENCE (derived from page DOM):\n"+table_text+
                "\nPAGE TEXT:\n"+body) if table_text else body

    def links(self):
        """[(anchor_text, absolute_url)] for same-domain http(s) anchors."""
        base = self.current_url()
        raw = self.page.eval_on_selector_all(
            "a[href]", "els => els.map(e => [e.innerText || '', e.getAttribute('href')])")
        out = []
        for text, href in raw:
            if not href:
                continue
            abs_url = urljoin(base, href)
            p = urlparse(abs_url)
            if p.scheme in ("http", "https") and _same_domain(urlparse(base).netloc, p.netloc):
                out.append((text.strip(), abs_url))
        return out

    def pick_evidence_link(self, missing_fields, exclude=()):
        """First same-domain link hinting at evidence for a missing field.

        Anchor text is matched against generic evidence hints plus the field
        names themselves. Blocked (transactional) labels and visited URLs are
        skipped. Returns None when nothing relevant remains.
        """
        words = {w for f in missing_fields for w in f.split("_") if len(w) > 2 and w not in {"free", "threshold", "charge", "time", "geography"}}
        if any(f.startswith("delivery") or f == "free_delivery_threshold" for f in missing_fields):
            words.update({"delivery", "shipping", "dispatch", "postage"})
        field_words = re.compile("|".join(sorted(words)), re.I) if words else None
        base_netloc = urlparse(self.current_url()).netloc
        generic, targeted = [], []
        for text, url in self.links():
            if url in exclude or BLOCKED_CLICK.search(text):
                continue
            if not _same_domain(base_netloc, urlparse(url).netloc):
                continue  # evidence must stay on the supplier's own domain
            if field_words and field_words.search(text):
                targeted.append((text, url))  # anchor names a missing field: best lead
            elif EVIDENCE_HINT.search(text):
                generic.append((text, url))
        candidates = targeted + generic
        return candidates[0][1] if candidates else None

    def try_select_variant(self, option_text):
        """Select a pack-size/variant option (read-only: no cart, no submit).
        Tries visible <select>s, then radio-style variant inputs, then a hidden
        <select> behind a custom widget. Never raises: any failure returns False."""
        try:
            hidden = []
            for sel in self.page.query_selector_all("select"):
                labels = [o.inner_text().strip() for o in sel.query_selector_all("option")]
                match = next((l for l in labels
                              if option_text.lower() in l.lower() and not BLOCKED_CLICK.search(l)), None)
                if not match:
                    continue
                if sel.is_visible():
                    sel.select_option(label=match, timeout=3000)
                    self.page.wait_for_load_state("domcontentloaded")
                    return True
                hidden.append((sel, match))
            for r in self.page.query_selector_all("input[type=radio]"):
                lab = r.get_attribute("value") or r.get_attribute("aria-label") or ""
                if option_text.lower() in lab.lower() and not BLOCKED_CLICK.search(lab):
                    r.check(timeout=3000)
                    self.page.wait_for_load_state("domcontentloaded")
                    return True
        except Exception:
            return False
        return False

    def click(self, accessible_name):
        if BLOCKED_CLICK.search(accessible_name):
            raise ValueError(f"read-only guard: refusing to click {accessible_name!r}")
        self.page.get_by_text(accessible_name, exact=False).first.click()
        self.page.wait_for_load_state("domcontentloaded")

    def select_option(self, selector_label, option):
        if BLOCKED_CLICK.search(option):
            raise ValueError(f"read-only guard: refusing option {option!r}")
        self.page.get_by_label(selector_label).select_option(label=option)

    # Raw markup only: script bodies are returned as text and parsed as JSON in Python (scout.engine.offers);
    # nothing in them is executed. Ordinary scripts are returned only when they name productVariants.
    STRUCTURED_QUERY = r"""() => {
      const out = [];
      for (const s of document.querySelectorAll('script')) {
        const t = (s.getAttribute('type') || '').trim().toLowerCase();
        const body = s.textContent || '';
        if (t === 'application/ld+json') out.push({origin: 'jsonld', body});
        else if (t === 'application/json') out.push({origin: 'application_json', body,
                 attrs: {id: s.id || '', resource: s.getAttribute('data-resource') || ''}});
        else if ((t === '' || t.includes('javascript')) && body.includes('productVariants'))
          out.push({origin: 'inline_script', body});
      }
      for (const o of document.querySelectorAll('select option, input[type=radio]')) {
        const text = o.tagName === 'OPTION' ? o.textContent
          : (o.getAttribute('aria-label') || (o.labels && o.labels[0] ? o.labels[0].textContent : '') || '');
        out.push({origin: 'option', value: o.value || '', text: (text || '').trim(), disabled: !!o.disabled});
      }
      return out;
    }"""

    def structured_offers(self):
        """Capture objects for the loaded page (no new request, no model call). Untested against live pages."""
        from .offers import captures_from_raw
        try:
            raw = self.page.evaluate(self.STRUCTURED_QUERY)
        except Exception:
            return None  # capture failed: the price stays unconfirmed rather than guessed
        return captures_from_raw(raw, self.current_url())

    def fetch_variant_data(self):
        """Read-only GET of the store's own variant JSON for a /products/<handle> page
        (Shopify exposes it at <url>.js). Returns (url, text) or None. The text is read in
        code (store_data.read_pack), not by the model, when the page did not give the price."""
        import json, urllib.request
        url = self.current_url().split("?")[0]
        if "/products/" not in url:
            return None
        js_url = url + ".js"
        try:
            if not safe_destination(js_url,[url]):return None
            class SafeRedirect(urllib.request.HTTPRedirectHandler):
                def redirect_request(self,req,fp,code,msg,headers,newurl):
                    if not safe_destination(newurl,[url]):raise ValueError('unsafe redirect')
                    return super().redirect_request(req,fp,code,msg,headers,newurl)
            opener=urllib.request.build_opener(SafeRedirect)
            with opener.open(js_url, timeout=15) as r:
                data = json.loads(r.read())
        except Exception:
            return None
        if not isinstance(data, dict) or "variants" not in data:
            return None
        from .store_data import format_variants  # the store's numbers; no currency is added
        return js_url, format_variants(data)

    def close(self):
        self._browser.close()
        self._pw.stop()
