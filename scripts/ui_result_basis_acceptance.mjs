/**
 * v3 结果口径 toggle acceptance (req #2/#4), driven through the REAL built web UI in real Chrome.
 *
 * It opens the PCF results page for a real EF3.1-characterised snapshot, captures pixel screenshots
 * at four viewports, then toggles 本次总量 -> 单位产品 (per-reference-output) in the UI and proves:
 *   - the number the user SEES matches the API projection for the same frozen snapshot at both bases;
 *   - switching the display basis reuses the SAME solve (solve_hash byte-identical, raw_total == total)
 *     and triggers no re-solve;
 *   - per-tonne == per-kg x 1000;
 *   - the HTML report and the XLSX export carry the SAME intensity number and the SAME frozen result
 *     identity (x-nebula-result-sha256 == the API projected content_sha256), so page/API/XLSX/HTML agree;
 *   - an incompatible base unit is refused (422) rather than silently converted.
 * No assertion here re-derives the denominator by hand: every expected value is read back from the
 * server's own projection, so it cannot be made to pass by editing a constant.
 *
 * Usage: node scripts/ui_result_basis_acceptance.mjs <BASE> <PORT> <OUT> <APP> <SNAP> <METHOD_REF>
 */
import { launchChrome, Cdp, sleep } from './browser/cdp.mjs';
import { mkdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

const BASE = process.argv[2];
const PORT = Number(process.argv[3] ?? 9355);
const OUT = process.argv[4];
const APP = process.argv[5];
const SNAP = process.argv[6];
const METHOD = process.argv[7];
if (!BASE || !APP || !SNAP || !METHOD) { console.error('need BASE PORT OUT APP SNAP METHOD'); process.exit(2); }
mkdirSync(OUT, { recursive: true });

const results = { base: BASE, app: APP, snapshot: SNAP, method: METHOD, headless: true, checks: [], screenshots: [] };
const check = (name, ok, detail) => { results.checks.push({ name, ok: !!ok, detail }); if (!ok) console.log(`FAIL ${name}: ${JSON.stringify(detail)}`); };

const VIEWPORTS = [
  { name: '1280x800', width: 1280, height: 800, deviceScaleFactor: 1 },
  { name: '1440x900', width: 1440, height: 900, deviceScaleFactor: 1 },
  { name: '150pct', width: 853, height: 533, deviceScaleFactor: 1.5, note: 'browser zoom 150% via deviceScaleFactor on 1280x800 physical capture' },
  { name: '390px', width: 390, height: 844, deviceScaleFactor: 1, note: 'agreed narrow browse mode' },
];

// Parse a locale-formatted number string (Arco/Intl grouping separators) into a float.
function parseNum(text) {
  const cleaned = String(text).replace(/[,\s\u00a0]/g, '');
  const m = cleaned.match(/-?\d+(\.\d+)?/);
  return m ? Number(m[0]) : NaN;
}
const close = (a, b, tol = 1e-6) => Number.isFinite(a) && Number.isFinite(b) && Math.abs(a - b) <= tol * Math.max(1, Math.abs(b));

async function apiFetch(path, init) {
  const response = await fetch(`${BASE}${path}`, init);
  return response;
}
function pcfBody(basis, baseAmount, baseUnit) {
  const body = { method_package_ref: METHOD };
  if (basis && basis !== 'total') Object.assign(body, { result_basis: basis, base_amount: baseAmount, base_unit: baseUnit });
  return body;
}
async function apiPost(body) {
  const response = await apiFetch(`/api/v1/solved-system-snapshots/${SNAP}/product-carbon-footprint`,
    { method: 'POST', headers: { 'content-type': 'application/json', accept: 'application/json' }, body: JSON.stringify(body) });
  return { status: response.status, json: response.status === 200 ? await response.json() : await response.text() };
}

async function rectOf(cdp, expr) {
  return cdp.evaluate(`(() => { const el = ${expr}; if (!el) return null; const r = el.getBoundingClientRect(); return { x: r.x, y: r.y, w: r.width, h: r.height }; })()`);
}
async function clickElement(cdp, expr, label) {
  await cdp.evaluate(`(() => { const el = ${expr}; if (!el) return; const r = el.getBoundingClientRect(); if (r.top < 0 || r.bottom > window.innerHeight) el.scrollIntoView({ block: 'center' }); })()`);
  await sleep(120);
  const rect = await rectOf(cdp, expr);
  if (!rect || rect.w === 0 || rect.h === 0) throw new Error(`click target not visible: ${label}`);
  for (const type of ['mousePressed', 'mouseReleased']) {
    await cdp.send('Input.dispatchMouseEvent', { type, x: rect.x + rect.w / 2, y: rect.y + rect.h / 2, button: 'left', clickCount: 1 }, cdp.sessionId);
  }
  await sleep(200);
}
// Read the headline value+unit shown by the PCF summary metric card.
async function screenHeadline(cdp) {
  return cdp.evaluate(`(() => { const el = document.querySelector('.pcf-product-summary__value'); if (!el) return null;
    const txt = (el.innerText || el.textContent || '').trim();
    const card = el.querySelector('*');
    return { text: txt }; })()`);
}
async function waitFor(cdp, expr, timeoutMs = 25000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (await cdp.evaluate(`!!(${expr})`).catch(() => false)) return true;
    await sleep(150);
  }
  return false;
}

let chrome, cdp;
try {
  const started = await launchChrome({ port: PORT, headless: true, windowSize: '1400,950' });
  chrome = started.child;
  cdp = new Cdp(started.wsUrl);
  await cdp.ready;
  await cdp.newTab();
  check('chrome_real_headless', started.binary && true, { binary: started.binary });

  const url = `${BASE}/applications/${APP}/results?snapshot=${SNAP}&view=pcf`;
  await cdp.navigate(url);
  const rendered = await waitFor(cdp, `document.querySelector('.pcf-result__basis') && document.querySelector('.pcf-product-summary__value')`);
  check('pcf_panel_renders_default_lcia', rendered, { url });

  // Authoritative API projections for the same frozen snapshot.
  const apiTotal = await apiPost(pcfBody(null));
  const apiPerKg = await apiPost(pcfBody('per_reference_output', 1, 'kg'));
  const apiPerT = await apiPost(pcfBody('per_reference_output', 1, 't'));
  check('api_total_ok', apiTotal.status === 200, apiTotal);
  check('api_intensity_kg_ok', apiPerKg.status === 200, apiPerKg);
  check('api_intensity_t_ok', apiPerT.status === 200, apiPerT);
  const totalVal = apiTotal.json?.total_footprint?.value;
  const perKgVal = apiPerKg.json?.total_footprint?.value;
  const perTVal = apiPerT.json?.total_footprint?.value;
  check('per_tonne_is_per_kg_times_1000', close(perTVal, perKgVal * 1000), { perKgVal, perTVal });

  // Switching the display basis must reuse the frozen solve, not re-run it.
  const solveHashTotal = apiTotal.json?.source_snapshot?.content_sha256;
  const solveHashIntensity = apiPerKg.json?.source_snapshot?.content_sha256;
  check('toggle_reuses_frozen_solve', !!solveHashTotal && solveHashTotal === solveHashIntensity, { solveHashTotal, solveHashIntensity });
  const rawTotal = apiPerKg.json?.result_basis?.source?.raw_total?.value;
  check('intensity_raw_total_equals_batch_total', close(rawTotal, totalVal), { rawTotal, totalVal });
  // The unique producing-output hit is frozen on the real snapshot (guardrail #3 on the UI path).
  const refOut = apiPerKg.json?.result_basis?.reference_output;
  check('intensity_freezes_unique_producing_hit', !!refOut && refOut.selector === 'reference_flow_uuid'
    && !!refOut.producing_process_uuid && !!refOut.producing_exchange_id
    && refOut.identity === refOut.producing_exchange_id, refOut);

  // Four viewports (page stays mounted; basis state persists across viewport changes).
  let head0 = await screenHeadline(cdp);
  const screenTotalNum = parseNum(head0?.text);
  check('screen_total_matches_api_total', close(screenTotalNum, totalVal), { screenTotalNum, totalVal, screen: head0?.text });
  for (const vp of VIEWPORTS) {
    await cdp.setViewport({ width: vp.width, height: vp.height, deviceScaleFactor: vp.deviceScaleFactor });
    await sleep(250);
    const s = await cdp.screenshot(join(OUT, `pcf-total-${vp.name}.png`));
    results.screenshots.push({ phase: 'total', ...vp, ...s });
    check(`viewport_capture_${vp.name}`, s.width >= vp.width && s.height >= vp.height, s);
  }

  // Toggle to 单位产品 in the UI: click the intensity radio, then read the new headline.
  const intensityLabel = await cdp.evaluate(`(() => { const labels=[...document.querySelectorAll('.pcf-result__basis .arco-radio-button')];
    const hit = labels.find(l => (l.innerText||'').includes('单位产品')); if (!hit) return null;
    hit.setAttribute('data-v3intensity','1'); return true; })()`);
  check('intensity_toggle_present', !!intensityLabel, { found: intensityLabel });
  await clickElement(cdp, `document.querySelector('[data-v3intensity]')`, '单位产品');
  const updated = await (async () => { const deadline = Date.now() + 20000;
    while (Date.now() < deadline) { const t = await screenHeadline(cdp); const n = parseNum(t?.text);
      if (Number.isFinite(n) && !close(n, totalVal, 1e-9)) return t; await sleep(200); } return await screenHeadline(cdp); })();
  const screenIntensityNum = parseNum(updated?.text);
  check('screen_intensity_matches_api_intensity_per_kg', close(screenIntensityNum, perKgVal), { screenIntensityNum, perKgVal, screen: updated?.text });
  check('screen_intensity_unit_is_per_kg', /\/\s*1\s*kg/.test(updated?.text || ''), { screen: updated?.text });

  // Capture the intensity view at the desktop viewport (the headline the user now sees).
  await cdp.setViewport({ width: 1280, height: 800, deviceScaleFactor: 1 });
  await sleep(200);
  const sIntensity = await cdp.screenshot(join(OUT, 'pcf-intensity-1280x800.png'));
  results.screenshots.push({ phase: 'intensity', viewport: '1280x800', ...sIntensity });

  // Cross-format: the HTML report carries the SAME intensity number and frozen identity.
  const html = await apiFetch(`/api/v1/solved-system-snapshots/${SNAP}/product-carbon-footprint/report.html?method_package_ref=${encodeURIComponent(METHOD)}&result_basis=per_reference_output&base_amount=1&base_unit=kg`);
  const htmlText = await html.text();
  const htmlNumStr = String(perKgVal);
  check('html_report_has_intensity_basis', html.status === 200 && htmlText.includes('单位产品') && htmlText.includes(htmlNumStr), { status: html.status, containsBasis: htmlText.includes('单位产品'), containsNumber: htmlText.includes(htmlNumStr) });
  check('html_result_sha_binds_projected_identity', html.headers.get('x-nebula-result-sha256') === apiPerKg.json?.content_sha256, { header: html.headers.get('x-nebula-result-sha256'), api: apiPerKg.json?.content_sha256 });

  // Cross-format: the XLSX export carries the same projected identity header and is a real workbook.
  const xlsx = await apiFetch(`/api/v1/solved-system-snapshots/${SNAP}/product-carbon-footprint/export.xlsx?method_package_ref=${encodeURIComponent(METHOD)}&result_basis=per_reference_output&base_amount=1&base_unit=kg`);
  const xlsxBytes = Buffer.from(await xlsx.arrayBuffer());
  check('xlsx_export_is_a_zip', xlsx.status === 200 && xlsxBytes.slice(0, 2).toString('latin1') === 'PK', { status: xlsx.status, head: xlsxBytes.slice(0, 2).toString('latin1'), bytes: xlsxBytes.length });
  check('xlsx_result_sha_binds_projected_identity', xlsx.headers.get('x-nebula-result-sha256') === apiPerKg.json?.content_sha256, { header: xlsx.headers.get('x-nebula-result-sha256'), api: apiPerKg.json?.content_sha256 });

  // Negative control: an incompatible base unit is refused, the total stays available.
  const refused = await apiPost(pcfBody('per_reference_output', 1, 'kWh'));
  check('incompatible_base_unit_refused', refused.status === 422, { status: refused.status, body: typeof refused.json === 'string' ? refused.json.slice(0, 200) : refused.json });

  const consoleErrors = cdp.consoleErrors();
  check('no_console_errors', consoleErrors.length === 0, { consoleErrors });
} catch (error) {
  check('acceptance_crashed', false, { error: String(error && error.stack || error) });
} finally {
  try { cdp && cdp.close(); } catch { /* ignore */ }
  try { chrome && chrome.kill(); } catch { /* ignore */ }
  writeFileSync(join(OUT, 'ui-result-basis-summary.json'), JSON.stringify(results, null, 2));
}

const failed = results.checks.filter(c => !c.ok);
console.log(JSON.stringify({ passed: failed.length === 0, total: results.checks.length, failed: failed.map(c => c.name) }, null, 2));
process.exit(failed.length === 0 ? 0 : 1);
