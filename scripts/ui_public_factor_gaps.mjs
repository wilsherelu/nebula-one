// Real rendered missing-factor state against the packaged public engine's demo.
import { launchChrome, Cdp, sleep } from './browser/cdp.mjs';
import { mkdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import assert from 'node:assert/strict';

const [base, port, out, app, snapshot] = process.argv.slice(2);
mkdirSync(out, { recursive: true });
const checks = [];
let chrome, cdp;
try {
  const resolve = await (await fetch(`${base}/api/v1/solved-system-snapshots/${snapshot}/product-carbon-footprint/default-method`)).json();
  const response = await fetch(`${base}/api/v1/solved-system-snapshots/${snapshot}/product-carbon-footprint`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ method_package_ref: resolve.reference }),
  });
  assert.equal(response.status, 200);
  const result = await response.json();
  assert.equal(result.data_quality.characterization_coverage.status, 'partial');
  chrome = await launchChrome({ port: Number(port) });
  cdp = new Cdp(chrome.wsUrl);
  await cdp.ready;
  await cdp.newTab();
  await cdp.navigate(`${base}/applications/${app}/results?snapshot=${snapshot}&view=pcf`);
  for (let attempt = 0; attempt < 80; attempt++) {
    if (await cdp.evaluate('Boolean(document.querySelector(".pcf-result__factor-gaps"))')) break;
    await sleep(250);
  }
  for (const [name, width, height, scale] of [['1280x800',1280,800,1], ['1440x900',1440,900,1], ['150pct',853,533,1.5], ['390px',390,844,1]]) {
    await cdp.setViewport({ width, height, deviceScaleFactor: scale });
    await sleep(250);
    const state = await cdp.evaluate(`(() => {
      const gaps = document.querySelector('.pcf-result__factor-gaps');
      return { text: gaps?.innerText, rows: gaps?.querySelectorAll('li').length,
        headline: document.querySelector('.pcf-product-summary__value')?.innerText,
        pageWidth: document.documentElement.scrollWidth, viewport: innerWidth };
    })()`);
    assert.ok(state.text?.includes('缺因子不代表排放为零'));
    assert.equal(state.rows, result.data_quality.characterization_coverage.uncharacterized_exchanges.length);
    assert.ok(state.headline.includes('已匹配因子的贡献小计'));
    assert.ok(!/[0-9a-f]{8}-[0-9a-f]{4}-/i.test(state.text), 'Readable flow names must replace internal IDs');
    assert.ok(state.pageWidth <= state.viewport + 2, 'Result page must fit the viewport');
    checks.push({ name, state, screenshot: await cdp.screenshot(join(out, `factor-gaps-${name}.png`)) });
  }
  assert.deepEqual(cdp.consoleErrors(), []);
  writeFileSync(join(out, 'summary.json'), JSON.stringify({ passed: true, snapshot, result_sha256: result.content_sha256, checks }, null, 2));
} finally {
  cdp?.close();
  chrome?.child.kill();
}
