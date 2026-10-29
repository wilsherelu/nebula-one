/**
 * v3 逐流调整 + Scope 分类 acceptance (req #4), driven through the REAL built web Scope editor in real Chrome.
 *
 * Opens the unified 核算设置 editor bound to a real EF3.1-characterised revision and a fresh user
 * method, and proves the v3 contribution/non-contribution split and a genuine per-flow round-trip:
 *   - contribution rows (elementary emissions) expose editable 是否计入 + 结果分类 selects;
 *   - a product-output row is a NON-contribution: it renders '—' in 是否计入 / 结果分类, its batch
 *     checkbox is disabled, and the flow kind reads as a product output — never counted as a gap;
 *   - editing an emission (计入 + 范围1), saving 新版本, then RELOADING the page reads the persisted
 *     范围1 back from the server (not client optimism), and the API detail confirms the frozen rule.
 * No assertion here fabricates state: persistence is proven by a page reload + the server's own read.
 *
 * Usage: node scripts/ui_scope_editor_acceptance.mjs <BASE> <PORT> <OUT> <APP> <MODEL> <REV> <METHOD>
 */
import { launchChrome, Cdp, sleep } from './browser/cdp.mjs';
import { mkdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

const BASE = process.argv[2];
const PORT = Number(process.argv[3] ?? 9362);
const OUT = process.argv[4];
const APP = process.argv[5];
const MODEL = process.argv[6];
const REV = process.argv[7];
const METHOD = process.argv[8];
if (!BASE || !APP || !MODEL || !REV || !METHOD) { console.error('need BASE PORT OUT APP MODEL REV METHOD'); process.exit(2); }
mkdirSync(OUT, { recursive: true });

const results = { base: BASE, app: APP, model: MODEL, revision: REV, method: METHOD, headless: true, checks: [], screenshots: [] };
const check = (name, ok, detail) => { results.checks.push({ name, ok: !!ok, detail }); if (!ok) console.log(`FAIL ${name}: ${JSON.stringify(detail)}`); };

const VIEWPORTS = [
  { name: '1280x800', width: 1280, height: 800, deviceScaleFactor: 1 },
  { name: '390px', width: 390, height: 844, deviceScaleFactor: 1, note: 'agreed narrow browse mode' },
];

async function waitFor(cdp, expr, timeoutMs = 25000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (await cdp.evaluate(`!!(${expr})`).catch(() => false)) return true;
    await sleep(150);
  }
  return false;
}
async function rectOf(cdp, expr) {
  return cdp.evaluate(`(() => { const el = ${expr}; if (!el) return null; const r = el.getBoundingClientRect(); return { x: r.x + r.width / 2, y: r.y + r.height / 2, w: r.width, h: r.height }; })()`);
}
async function clickElement(cdp, expr, label) {
  await cdp.evaluate(`(() => { const el = ${expr}; if (!el) return; const r = el.getBoundingClientRect(); if (r.top < 0 || r.bottom > window.innerHeight) el.scrollIntoView({ block: 'center' }); })()`);
  await sleep(140);
  const rect = await rectOf(cdp, expr);
  if (!rect || rect.w === 0 || rect.h === 0) throw new Error(`click target not visible: ${label}`);
  for (const type of ['mousePressed', 'mouseReleased']) {
    await cdp.send('Input.dispatchMouseEvent', { type, x: rect.x, y: rect.y, button: 'left', clickCount: 1 }, cdp.sessionId);
  }
  await sleep(220);
}
// Mark a row's boundary/scope select by attribute so it can be targeted after a re-render.
async function tagRow(cdp, predicate, attr) {
  return cdp.evaluate(`(() => {
    const rows = [...document.querySelectorAll('.method-scope__detail .arco-table-body .arco-table-tr')];
    const row = rows.find(${predicate});
    if (!row) return null;
    row.setAttribute('${attr}', '1');
    return { count: rows.length };
  })()`);
}
async function selectRowOption(cdp, attr, ariaLabel, optionText) {
  await clickElement(cdp, `document.querySelector('.method-scope__detail .arco-table-tr[${attr}] [aria-label=${JSON.stringify(ariaLabel)}]')`, `${attr}/${ariaLabel}`);
  const picked = await (async () => { const deadline = Date.now() + 6000;
    while (Date.now() < deadline) {
      const ok = await cdp.evaluate(`(() => { const opt=[...document.querySelectorAll('.arco-select-popup .arco-select-option')].find(o=>(o.innerText||'').trim()===${JSON.stringify(optionText)}); if(!opt) return false; opt.setAttribute('data-v3opt','1'); return true; })()`);
      if (ok) return true; await sleep(120);
    } return false; })();
  if (!picked) throw new Error(`option not found: ${optionText}`);
  await clickElement(cdp, `document.querySelector('.arco-select-option[data-v3opt]')`, `option ${optionText}`);
  await cdp.evaluate(`document.querySelector('.arco-select-option[data-v3opt]')?.removeAttribute('data-v3opt')`);
  await sleep(150);
}
async function apiGet(path) {
  const response = await fetch(`${BASE}${path}`, { headers: { accept: 'application/json' } });
  return { status: response.status, json: response.status === 200 ? await response.json() : await response.text() };
}

let chrome, cdp;
try {
  const started = await launchChrome({ port: PORT, headless: true, windowSize: '1400,950' });
  chrome = started.child;
  cdp = new Cdp(started.wsUrl);
  await cdp.ready;
  await cdp.newTab();
  check('chrome_real_headless', !!started.binary, { binary: started.binary });

  const url = `${BASE}/applications/${APP}/calculation-methods?model=${MODEL}&revision=${REV}&method=${METHOD}`;
  await cdp.navigate(url);
  const mounted = await waitFor(cdp, `document.querySelector('.calculation-method-editor') && document.querySelectorAll('.method-scope__detail .arco-table-body .arco-table-tr').length > 0`);
  check('scope_editor_renders_rows', mounted, { url });

  // Classify each row: a contribution row carries an editable 是否计入 + 结果分类 select; a
  // non-contribution (product/internal) renders '—' with no selects and a disabled checkbox.
  const rowInfo = await cdp.evaluate(`(() => {
    const rows = [...document.querySelectorAll('.method-scope__detail .arco-table-body .arco-table-tr')];
    return rows.map(tr => ({
      text: (tr.innerText || '').trim(),
      editable: !!tr.querySelector('[aria-label="是否计入"]') && !!tr.querySelector('[aria-label="结果分类"]'),
      dash: /—/.test(tr.innerText || ''),
      checkboxDisabled: (tr.querySelector('input[type=checkbox]') || {}).disabled ?? null,
    }));
  })()`);
  const contributionRows = rowInfo.filter(r => r.editable);
  const nonContributionRows = rowInfo.filter(r => !r.editable && r.dash);
  check('emission_contribution_rows_editable', contributionRows.length >= 1, { contributionRows: contributionRows.length, rowInfo });
  check('product_output_row_noncontribution', nonContributionRows.length >= 1
    && nonContributionRows.some(r => /产品输出/.test(r.text)), { nonContributionRows });
  check('noncontribution_checkbox_disabled', nonContributionRows.length >= 1
    && nonContributionRows.every(r => r.checkboxDisabled === true), { nonContributionRows });
  check('contribution_checkbox_enabled', contributionRows.length >= 1
    && contributionRows.every(r => r.checkboxDisabled === false), { contributionRows });

  // Tag the first contribution (emission) row for a genuine per-flow Scope round-trip.
  const tagged = await tagRow(cdp, 'tr => !!tr.querySelector(\'[aria-label="结果分类"]\')', 'data-v3scope');
  check('contribution_row_tagged', !!tagged, tagged);

  await selectRowOption(cdp, 'data-v3scope', '是否计入', '计入');
  await selectRowOption(cdp, 'data-v3scope', '结果分类', '范围1');

  const dirtyShown = await waitFor(cdp, `document.querySelector('.calculation-method-editor__dirty')`, 8000);
  check('per_flow_edit_marks_draft_dirty', dirtyShown, { dirtyShown });

  // Save 新版本 through the UI, then wait for the dirty bar to clear (server confirmed head version).
  await clickElement(cdp, `[...document.querySelectorAll('.calculation-method-editor__actions button')].find(b => (b.innerText||'').trim() === '保存为新版本')`, '保存为新版本');
  const saved = await waitFor(cdp, `!document.querySelector('.calculation-method-editor__dirty')`, 20000);
  check('save_new_version_settles', saved, { saved });

  // Server read-back: the latest version froze a rule with scope_1 and boundary selected.
  const detail = await apiGet(`/api/v1/calculation-methods/${METHOD}`);
  const latest = (detail.json?.versions ?? []).find(v => v.version === detail.json?.latest_version);
  const frozenRule = (latest?.rules ?? []).find(r => r.scope === 'scope_1' && r.boundary_status === 'selected');
  check('api_latest_version_freezes_scope1_rule', detail.status === 200 && !!frozenRule,
    { status: detail.status, latest_version: detail.json?.latest_version, rules: (latest?.rules ?? []).map(r => ({ exchange_id: r.exchange_id, scope: r.scope, boundary_status: r.boundary_status })) });

  // Reload the editor from the server and confirm the row reads 范围1 back (not client optimism).
  await cdp.navigate(url);
  await waitFor(cdp, `document.querySelector('.calculation-method-editor')`, 25000);
  const reloadedValue = await (async () => { const deadline = Date.now() + 15000;
    while (Date.now() < deadline) {
      const v = await cdp.evaluate(`(() => { const rows=[...document.querySelectorAll('.method-scope__detail .arco-table-body .arco-table-tr')];
        const hit = rows.find(tr => { const s = tr.querySelector('[aria-label="结果分类"]'); return s && (s.innerText||'').includes('范围1'); });
        return hit ? '范围1' : null; })()`);
      if (v) return v; await sleep(250);
    } return null; })();
  check('reloaded_editor_reads_persisted_scope1', reloadedValue === '范围1', { reloadedValue });

  // Pixel screenshots at two viewports.
  for (const vp of VIEWPORTS) {
    await cdp.setViewport({ width: vp.width, height: vp.height, deviceScaleFactor: vp.deviceScaleFactor });
    await sleep(250);
    const s = await cdp.screenshot(join(OUT, `scope-editor-${vp.name}.png`));
    results.screenshots.push({ phase: 'scope', ...vp, ...s });
    check(`viewport_capture_${vp.name}`, s.width >= vp.width && s.height >= vp.height, s);
  }

  const consoleErrors = cdp.consoleErrors();
  check('no_console_errors', consoleErrors.length === 0, { consoleErrors });
} catch (error) {
  check('acceptance_crashed', false, { error: String(error && error.stack || error) });
} finally {
  try { cdp && cdp.close(); } catch { /* ignore */ }
  try { chrome && chrome.kill(); } catch { /* ignore */ }
  writeFileSync(join(OUT, 'ui-scope-editor-summary.json'), JSON.stringify(results, null, 2));
}

const failed = results.checks.filter(c => !c.ok);
console.log(JSON.stringify({ passed: failed.length === 0, total: results.checks.length, failed: failed.map(c => c.name) }, null, 2));
process.exit(failed.length === 0 ? 0 : 1);
