// Node Playwright port of tests/test_network_integration.py::test_chromium_blocks_post_and_redirect_before_server_receives
// NOT EQUIVALENT to the Python test: the routing DECISION is the product's Python network_allowed (asked over a
// loopback helper), but the route handler below is a JavaScript REPLICA of ReadOnlyBrowser._route_request running
// on Node Playwright, not the product's Python handler on Python Playwright. Same assertions as the Python test.
const { chromium } = require('playwright');
const http = require('http');
const { spawn } = require('child_process');
const path = require('path');

const hits = [];
const fixture = http.createServer((req, res) => {
  hits.push([req.method, req.url]);
  if (req.method === 'POST') { res.writeHead(200); return res.end(); }
  if (req.url === '/redirect') { res.writeHead(302, {Location: `http://localhost:${fixture.address().port}/target`}); return res.end(); }
  res.writeHead(200, {'Content-Type': 'text/html'}); res.end('<html>fixture</html>');
});

function ask(port, body) {
  return new Promise((resolve, reject) => {
    const data = JSON.stringify(body);
    const r = http.request({host: '127.0.0.1', port, method: 'POST', path: '/',
      headers: {'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(data)}},
      res => { let b = ''; res.on('data', c => b += c); res.on('end', () => resolve(JSON.parse(b).allowed)); });
    r.on('error', reject); r.end(data);
  });
}

(async () => {
  await new Promise(r => fixture.listen(0, '127.0.0.1', r));
  const base = `http://127.0.0.1:${fixture.address().port}`;
  const helper = spawn('python3', ['-S', path.join(__dirname, 'decision_server.py'), base]);
  const helperPort = await new Promise(r => helper.stdout.once('data', d => r(parseInt(String(d), 10))));
  const browser = await chromium.launch();
  const failures = [];
  try {
    const page = await browser.newPage({serviceWorkers: 'block'});
    let roots = [base];  // set_source(base)
    await page.route('**/*', async route => {  // replica of ReadOnlyBrowser._route_request
      const req = route.request();
      if (process.env.SCOTT_NEGATIVE_CONTROL === 'allow_all') return route.continue();  // control: must FAIL
      if (!await ask(helperPort, {method: req.method(), url: req.url(), resource_type: req.resourceType(), roots})) {
        return route.abort();
      }
      const response = await route.fetch({maxRedirects: 0});
      if (response.status() >= 300 && response.status() < 400) return route.abort();
      return route.fulfill({response});
    });
    await page.goto(base + '/page', {waitUntil: 'domcontentloaded'});
    await page.evaluate(async () => { try { await fetch('/cart/add', {method: 'POST', body: 'x'}); } catch (e) {} });
    let raised = false;
    try { await page.goto(base + '/redirect', {waitUntil: 'domcontentloaded'}); } catch (e) { raised = true; }
    const has = (m, p) => hits.some(h => h[0] === m && h[1] === p);
    if (!raised) failures.push('redirect navigation did not raise');
    if (!has('GET', '/page')) failures.push('GET /page not received');
    if (!has('GET', '/redirect')) failures.push('GET /redirect not received');
    if (hits.some(([m, p]) => m === 'POST' || p === '/cart/add' || p === '/target')) failures.push('blocked request reached the server: ' + JSON.stringify(hits));
  } finally {
    await browser.close(); helper.kill(); fixture.close();
  }
  console.log(JSON.stringify({hits, failures, result: failures.length ? 'FAIL' : 'PASS'}));
  process.exit(failures.length ? 1 : 0);
})();
