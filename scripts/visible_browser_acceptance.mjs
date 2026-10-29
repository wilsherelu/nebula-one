/**
 * Visible-browser acceptance for the template workspace, driven against a real Chrome over CDP.
 *
 * Unlike the in-app browser (viewport 0x0, no pixels), this launches real Chrome headless=new and
 * captures PNG screenshots at each requested viewport, so the evidence is pixel-level, not DOM-only.
 * A positive control (full-screen overlay) is captured at every viewport to prove the capture
 * pipeline reflects live pixels rather than a stale frame.
 */
import { launchChrome, Cdp, sleep } from './browser/cdp.mjs';
import { mkdirSync, writeFileSync } from 'node:fs';

const BASE = process.argv[2] ?? 'http://127.0.0.1:18954';
const ORGANIZATION = process.argv.includes('--organization');
const OUT = process.env.NEBULA_BROWSER_EVIDENCE_DIR ?? '.local-evidence/u6-browser';
const PORT = Number(process.argv[3] ?? 9333);
const ATTACH = process.argv.includes('--attach');
mkdirSync(OUT, { recursive: true });

// Unique per run so re-runs don't trip the server's "name already exists for this model revision"
// guard (correct product behaviour) left over from a previous acceptance pass.
const RUN = Math.random().toString(36).slice(2, 8);

// Engineering identifiers that must never surface as a user-facing label. They are allowed inside
// collapsed <details> source disclosures, which are not "visible" (offsetParent is null when closed).
const ENUM_BLACKLIST = [
  'cbam_trial', 'cbam_partial_review', 'product_carbon_footprint',
  'organization_period_inventory', 'organization_lifecycle_carbon', 'organization_ghg_inventory',
  'official_package', 'user_method', 'scope_1', 'scope_2', 'scope_3',
  'not_validated', 'boundaries/cbam', '/boundaries/', 'rule_source', 'content_sha256',
  'method_package_ref', 'graph_sha256', 'bundle_content_sha256',
];
const UUID_RE = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i;
const SHA_RE = /\b[0-9a-f]{64}\b/i;

const VIEWPORTS = [
  { name: '1280x800', width: 1280, height: 800, dsf: 1 },
  { name: '1440x900', width: 1440, height: 900, dsf: 1 },
  { name: '150pct', width: 853, height: 533, dsf: 1.5, note: 'browser zoom 150% emulated via deviceScaleFactor=1.5 on a 1280x800 physical capture' },
  { name: '390px', width: 390, height: 844, dsf: 1, note: 'agreed browse mode' },
];

const results = { base: BASE, head: null, viewports: {}, checks: [], screenshots: [], consoleErrors: [] };

async function rectOf(cdp, jsExpr) {
  return await cdp.evaluate(`(() => { const el = ${jsExpr}; if (!el) return null;
    const r = el.getBoundingClientRect();
    return { x: r.x, y: r.y, w: r.width, h: r.height }; })()`);
}
async function mouseClick(cdp, x, y) {
  await cdp.send('Input.dispatchMouseEvent', { type: 'mouseMoved', x, y }, cdp.sessionId);
  await cdp.send('Input.dispatchMouseEvent', { type: 'mousePressed', x, y, button: 'left', clickCount: 1 }, cdp.sessionId);
  await cdp.send('Input.dispatchMouseEvent', { type: 'mouseReleased', x, y, button: 'left', clickCount: 1 }, cdp.sessionId);
}
async function clickElement(cdp, jsExpr, label) {
  // Coordinate clicks only land inside the viewport; scroll an off-screen target to center first.
  // Skip the scroll when the target is already fully visible so an open popup option isn't
  // scrolled away (which would close the dropdown before the option click lands).
  await cdp.evaluate(`(() => { const el = ${jsExpr}; if (!el) return;
    const r = el.getBoundingClientRect();
    if (r.top < 0 || r.bottom > window.innerHeight || r.left < 0 || r.right > window.innerWidth)
      el.scrollIntoView({ block: 'center', inline: 'center' }); })()`);
  await sleep(120);
  const rect = await rectOf(cdp, jsExpr);
  if (!rect || rect.w === 0 || rect.h === 0) throw new Error(`click target not visible: ${label}`);
  await mouseClick(cdp, rect.x + rect.w / 2, rect.y + rect.h / 2);
  await sleep(150);
}
async function fillControlledInput(cdp, jsExpr, text) {
  await clickElement(cdp, jsExpr, 'input');
  await cdp.evaluate(`(() => { const el = ${jsExpr}; el.focus();
    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
    setter.call(el, ''); el.dispatchEvent(new Event('input', { bubbles: true })); })()`);
  await cdp.send('Input.insertText', { text }, cdp.sessionId);
  await sleep(120);
}
async function selectOption(cdp, triggerJsExpr, optionText, label) {
  await clickElement(cdp, triggerJsExpr, `select ${label}`);
  const optionExpr = `[...document.querySelectorAll('.arco-select-popup .arco-select-option')]
    .find(el => el.textContent.trim() === ${JSON.stringify(optionText)})
    ?? [...document.querySelectorAll('.arco-select-popup .arco-select-option')]
    .find(el => el.textContent.includes(${JSON.stringify(optionText)}))`;
  await waitFor(cdp, optionExpr, 4000, `option "${optionText}" for ${label}`);
  await clickElement(cdp, optionExpr, `option ${label}`);
}
async function waitFor(cdp, jsExpr, timeoutMs, what) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const found = await cdp.evaluate(`!!(${jsExpr})`).catch(() => false);
    if (found) return true;
    await sleep(150);
  }
  throw new Error(`timeout waiting for ${what}`);
}
async function visibleText(cdp) {
  return await cdp.evaluate(`(() => {
    const parts = [];
    const walk = el => {
      if (el.nodeType !== 1) return;
      const style = getComputedStyle(el);
      if (style.display === 'none' || style.visibility === 'hidden') return;
      if (el.tagName === 'SCRIPT' || el.tagName === 'STYLE') return;
      for (const child of el.childNodes) {
        if (child.nodeType === 3) { const t = child.textContent.trim(); if (t) parts.push(t); }
        else walk(child);
      }
    };
    walk(document.body);
    return parts.join('\\n');
  })()`);
}
async function enumLeak(cdp) {
  return await cdp.evaluate(`(() => {
    const blacklist = ${JSON.stringify(ENUM_BLACKLIST)};
    const leaks = [];
    const walk = el => {
      if (el.nodeType !== 1) return;
      const style = getComputedStyle(el);
      if (style.display === 'none' || style.visibility === 'hidden') return;
      if (el.tagName === 'SCRIPT' || el.tagName === 'STYLE' || el.tagName === 'CODE') return;
      // A closed <details> hides its content via the details slot (not display:none), so its
      // children still compute as visible. Only the <summary> is actually shown; skip the rest.
      const closedDetails = el.tagName === 'DETAILS' && !el.open;
      for (const child of el.childNodes) {
        if (closedDetails && !(child.nodeType === 1 && child.tagName === 'SUMMARY')) continue;
        if (child.nodeType === 3) {
          const text = child.textContent;
          for (const token of blacklist) if (text.includes(token)) leaks.push({ token, tag: el.tagName, text: text.trim().slice(0, 80) });
          if (/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i.test(text)) leaks.push({ token: 'uuid', tag: el.tagName, text: text.trim().slice(0, 80) });
          if (/\\b[0-9a-f]{64}\\b/i.test(text)) leaks.push({ token: 'sha256', tag: el.tagName, text: text.trim().slice(0, 80) });
        } else walk(child);
      }
    };
    walk(document.body);
    return leaks;
  })()`);
}
async function positiveControl(cdp, shotName) {
  await cdp.evaluate(`(() => { const d = document.createElement('div'); d.id = 'nebula-overlay';
    d.style.cssText = 'position:fixed;inset:0;background:#ff0044;z-index:999999;'; document.body.appendChild(d); })()`);
  const shot = await cdp.screenshot(`${OUT}/${shotName}`);
  await cdp.evaluate(`document.getElementById('nebula-overlay')?.remove()`);
  return shot;
}
async function shot(cdp, name) {
  const s = await cdp.screenshot(`${OUT}/${name}.png`);
  results.screenshots.push({ name, ...s });
  return s;
}
function check(name, ok, detail) { results.checks.push({ name, status: ok ? 'pass' : 'fail', ok: !!ok, detail }); }

let launched = null;
let wsUrl;
if (ATTACH) {
  const version = await (await fetch(`http://127.0.0.1:${PORT}/json/version`)).json();
  wsUrl = version.webSocketDebuggerUrl;
  results.binary = 'attached (pre-launched Chrome)';
} else {
  launched = await launchChrome({ port: PORT });
  results.binary = launched.binary;
  wsUrl = launched.wsUrl;
}
const cdp = new Cdp(wsUrl);
await cdp.ready;
await cdp.newTab();

try {
  // ---- Interactive journey at 1280x800 (the only viewport that writes data) ----
  const vp = VIEWPORTS[0];
  await cdp.setViewport(vp);
  results.viewports[vp.name] = { ...vp };

  await cdp.navigate(`${BASE}/templates`);
  await shot(cdp, '01-templates');
  const cardActions = await cdp.evaluate(`(() => {
    const card = document.querySelector('.template-library-card');
    return card ? [...card.querySelectorAll('button')].map(b => b.textContent.trim()) : [];
  })()`);
  check('template_card_two_actions', cardActions.length === 2 && cardActions.includes('新建项目') && cardActions.includes('配置模板'), { cardActions });
  const cardLinks = await cdp.evaluate(`document.querySelectorAll('.template-library-card a').length`);
  check('template_card_no_bare_links', cardLinks === 0, { cardLinks });
  check('templates_no_enum_leak', (await enumLeak(cdp)).length === 0, await enumLeak(cdp));

  // Enter the configuration workspace. The first screen contains the two accounting rule tasks, so the
  // reader lands on tasks, not a flat card grid; copy-and-adjust lives inside the relevant task row.
  await clickElement(cdp, `[...document.querySelectorAll('.template-library-card button')].find(b => b.textContent.trim() === '配置模板')`, '配置模板');
  await waitFor(cdp, `location.pathname.includes('/config')`, 8000, 'config route');
  await waitFor(cdp, `document.querySelector('.template-task-row')`, 8000, 'task rows');
  await shot(cdp, '02-config-tasks');
  const backLinks = await cdp.evaluate(`[...document.querySelectorAll('a')].filter(a => a.textContent.trim() === '返回工艺模板').length`);
  check('config_single_back_link', backLinks === 1, { backLinks });
  const taskTitles = await cdp.evaluate(`[...document.querySelectorAll('.template-task-row h2')].map(h => h.textContent.trim())`);
  check('config_shows_two_rule_tasks',
    taskTitles.length === 2 && taskTitles.includes('CBAM') && taskTitles.some(t => t.includes('范围')),
    { taskTitles });
  await clickElement(cdp, `[...document.querySelectorAll('.result-tabs__navigation button')].find(b => b.textContent.trim() === '模型与数据')`, '模型与数据');
  await waitFor(cdp, `document.querySelector('.template-indicator')`, 8000, 'default LCIA information');
  const indicator = await cdp.evaluate(`document.querySelector('.template-indicator')?.textContent`);
  check('config_default_lcia_is_model_setting', indicator?.includes('默认评价指标') && indicator?.includes('查看来源'), { indicator });
  await shot(cdp, '02-default-lcia');
  await clickElement(cdp, `[...document.querySelectorAll('.result-tabs__navigation button')].find(b => b.textContent.trim() === '核算方案')`, '核算方案');
  await waitFor(cdp, `document.querySelector('.template-task-row')`, 8000, 'rule tasks restored');
  check('config_no_enum_leak', (await enumLeak(cdp)).length === 0, await enumLeak(cdp));

  // Copy the declared official scheme and adjust. In the task panel the copy lives behind the task row's
  // "查看与调整" forward action (the official preset has no user method yet, so it opens the copy dialog).
  // The expression must resolve to the button itself, not the row, or the coordinate click lands on
  // empty space. The organization lifecycle scheme is the 范围1–3 task's preset; CBAM is its own task.
  const taskTitle = ORGANIZATION ? '范围' : 'CBAM';
  const schemeTitle = ORGANIZATION ? '组织生命周期碳' : 'CBAM';
  await clickElement(cdp, `[...document.querySelectorAll('.template-task-row')].find(r => r.querySelector('h2')?.textContent.trim().includes(${JSON.stringify(taskTitle)}))?.querySelector('.template-task-row__actions button')`, `${taskTitle} task forward`);
  await waitFor(cdp, `document.querySelector('.template-copy-dialog')`, 8000, 'copy dialog');
  await shot(cdp, '03-copy-dialog');
  await fillControlledInput(cdp, `document.querySelector('#template-copy-name')`, `浏览器验收 ${schemeTitle} 副本 ${RUN}`);
  const hasBoundary = await cdp.evaluate(`!!document.querySelector('#template-copy-boundary')`);
  if (hasBoundary) {
    // Single frozen boundary is pre-selected; open the disclosure to confirm source detail is present but collapsed.
    const boundaryOpen = await cdp.evaluate(`document.querySelector('.template-copy-dialog__source')?.open ?? null`);
    check('copy_boundary_source_collapsed', boundaryOpen === false, { boundaryOpen });
  }
  await clickElement(cdp, `[...document.querySelectorAll('.template-copy-dialog .form-actions button')].find(b => b.textContent.trim() === '创建副本')`, '创建副本');
  await waitFor(cdp, `location.search.includes('method=')`, 12000, 'editor route');
  await waitFor(cdp, `document.querySelector('.calculation-method-editor')`, 8000, 'method editor');
  await shot(cdp, '04-editor-scope');

  // The flow table must be populated with real inventory rows.
  await waitFor(cdp, `document.querySelectorAll('.method-scope__detail .arco-table-tr').length > 1`, 8000, 'flow rows');
  const rowCount = await cdp.evaluate(`document.querySelectorAll('.method-scope__detail .arco-table-tr').length`);
  check('editor_flow_table_populated', rowCount > 1, { rowCount });
  const processNames = await cdp.evaluate(`[...document.querySelectorAll('.method-scope__process-name')].map(e => e.textContent.trim())`);
  check('editor_process_nav_real', processNames.length >= 3, { processNames });
  check('editor_no_enum_leak', (await enumLeak(cdp)).length === 0, await enumLeak(cdp));

  // Pick a process, then exclude one flow through the real per-row control. P2 renamed the per-flow
  // inclusion labels (已排除→不计入, 已纳入→计入); '不计入' is the current "exclude this flow" option.
  await clickElement(cdp, `document.querySelectorAll('.method-scope__process-list button')[1] ?? document.querySelector('.method-scope__process-list button')`, 'second process');
  await sleep(300);
  await shot(cdp, '05-editor-process');
  await selectOption(cdp, `document.querySelector('.method-scope__detail .arco-table-tr .arco-select')`, '不计入', 'first flow boundary');
  await waitFor(cdp, `document.querySelector('.calculation-method-editor__dirty')`, 5000, 'dirty bar');
  const dirtyText = await cdp.evaluate(`document.querySelector('.calculation-method-editor__dirty')?.textContent?.trim() ?? null`);
  check('editor_flow_edit_marks_dirty', !!dirtyText, { dirtyText });
  await shot(cdp, '06-editor-edited');

  // Save as a new immutable version. The action bar sits at the top of the editor; after the table
  // interactions the window can be scrolled down, and scrollIntoView only moves the inner scroll
  // container — leaving the button's window-rect off-viewport so the coordinate click misses. Bring
  // the window back to the top so the button is at its natural, clickable position.
  await cdp.evaluate(`window.scrollTo(0, 0)`);
  await sleep(150);
  await clickElement(cdp, `[...document.querySelectorAll('.calculation-method-editor__bar button')].find(b => b.textContent.trim() === '保存为新版本')`, '保存为新版本');
  await waitFor(cdp, `!document.querySelector('.calculation-method-editor__dirty')`, 12000, 'save settled');
  await shot(cdp, '07-editor-saved');

  // Validate.
  await clickElement(cdp, `[...document.querySelectorAll('.arco-tabs-header-title')].find(e => e.textContent.trim() === '检查与试算')`, '检查与试算 tab');
  await waitFor(cdp, `[...document.querySelectorAll('button')].some(b => b.textContent.trim() === '校验该方法版本')`, 6000, 'validate button');
  await clickElement(cdp, `[...document.querySelectorAll('button')].find(b => b.textContent.trim() === '校验该方法版本')`, '校验该方法版本');
  await waitFor(cdp, `document.querySelector('.calculation-method-review .arco-alert')`, 20000, 'validation result alert');
  const validationOk = await cdp.evaluate(`(() => { const a = document.querySelector('.calculation-method-review .arco-alert');
    return a ? a.textContent.trim().slice(0, 120) : null; })()`);
  check('validation_returns_result', validationOk !== null, { validationOk });
  await shot(cdp, '08-editor-validated');

  // Save as my template.
  await clickElement(cdp, `[...document.querySelectorAll('.calculation-method-editor__bar button')].find(b => b.textContent.trim() === '返回方法列表')`, '返回方法列表');
  await waitFor(cdp, `document.querySelector('.template-task-row')`, 8000, 'scheme list after editing');
  await clickElement(cdp, `[...document.querySelectorAll('.project-header-actions button')].find(b => b.textContent.trim() === '保存为我的模板')`, '保存为我的模板');
  await waitFor(cdp, `document.querySelector('.template-save-dialog')`, 8000, 'save dialog');
  await waitFor(cdp, `document.querySelector('#template-save-name')?.value`, 8000, 'save name prefilled');
  await shot(cdp, '09-save-dialog');
  await clickElement(cdp, `[...document.querySelectorAll('.template-save-dialog .form-actions button')].find(b => b.textContent.trim() === '保存模板')`, '保存模板');
  await waitFor(cdp, `[...document.querySelectorAll('*')].some(e => e.textContent.includes('已保存为'))`, 15000, 'saved alert');
  await shot(cdp, '10-saved-alert');
  const savedAlert = await cdp.evaluate(`(() => { const e = [...document.querySelectorAll('.arco-alert, .arco-message, [class*=toast], [class*=notification]')].find(n => n.textContent.includes('已保存为')); return e ? e.textContent.trim().slice(0, 160) : null; })()`);
  check('save_template_success_alert', !!savedAlert, { savedAlert });

  // Create a project from the saved template.
  await clickElement(cdp, `[...document.querySelectorAll('.project-header-actions button')].find(b => b.textContent.trim() === '新建项目')`, '新建项目');
  await waitFor(cdp, `document.querySelector('.project-create-dialog')`, 8000, 'create dialog');
  await shot(cdp, '11-create-dialog');
  await fillControlledInput(cdp, `document.querySelector('#project-name')`, `浏览器验收项目 ${RUN}`);
  await clickElement(cdp, `[...document.querySelectorAll('.project-create-dialog button')].find(b => b.textContent.trim() === '创建项目，填写数据')`, '创建项目');
  await waitFor(cdp, `location.pathname.includes('/workbench')`, 20000, 'project workbench');
  await shot(cdp, '12-project-workbench');
  results.projectUrl = await cdp.evaluate('location.href');

  // Project results page. This project has not been solved yet, so the honest state is an explicit
  // empty/prompt panel — never a blank <main>. An empty results page is only acceptable when the app
  // renders a recognized empty-state or compute CTA; a blank main is a failure, not a pass.
  const appId = await cdp.evaluate(`location.pathname.split('/')[2]`);
  await cdp.navigate(`${BASE}/applications/${appId}/results`);
  await waitFor(cdp, `document.querySelector('main')`, 8000, 'results page');
  await waitFor(cdp, `(() => { const m = document.querySelector('main');
    return m && (m.querySelector('.pcf-result, .arco-table, .metric-card, .arco-empty, .arco-alert, .arco-result, button, a')); })()`, 12000, 'results meaningful content');
  const resultsState = await cdp.evaluate(`(() => { const m = document.querySelector('main');
    const kind = m.querySelector('.pcf-result') ? 'pcf-result'
      : m.querySelector('.arco-empty') ? 'empty-state'
      : m.querySelector('.arco-alert') ? 'alert'
      : m.querySelector('.metric-card, .arco-table') ? 'metrics'
      : m.querySelector('button, a') ? 'cta-only' : 'blank';
    return { kind, text: (m.innerText || '').trim().slice(0, 200), nodes: m.querySelectorAll('*').length }; })()`);
  results.resultsState = resultsState;
  check('results_page_not_blank', resultsState.kind !== 'blank' && resultsState.nodes > 3, resultsState);
  await shot(cdp, '13-project-results');
  results.appId = appId;

  // ---- Layout at the other viewports (read-only navigation to the same screens) ----
  const configUrl = `${BASE}/templates`;
  for (const other of VIEWPORTS.slice(1)) {
    await cdp.setViewport(other);
    results.viewports[other.name] = { ...other };
    const before = await shot(cdp, `v-${other.name}-templates`);
    const control = await positiveControl(cdp, `v-${other.name}-control`);
    check(`positive_control_${other.name}`, before.sha256 !== control.sha256, { before: before.sha256, control: control.sha256 });
    await cdp.navigate(`${BASE}/templates`);
    await shot(cdp, `v-${other.name}-templates-nav`);
    // Config + editor are reachable without writing: open the CBAM copy we created (read-only view).
    await clickElement(cdp, `[...document.querySelectorAll('.template-library-card button')].find(b => b.textContent.trim() === '配置模板')`, '配置模板');
    await waitFor(cdp, `location.pathname.includes('/config')`, 8000, 'config route');
    await waitFor(cdp, `document.querySelector('.template-task-row')`, 8000, 'task rows');
    await shot(cdp, `v-${other.name}-config`);
    if (other.width < 768) {
      const rows = await cdp.evaluate(`Array.from(document.querySelectorAll('.template-task-row')).map(row => {
        const select = row.querySelector('.template-task-row__select')?.getBoundingClientRect();
        const action = row.querySelector('.template-task-row__actions')?.getBoundingClientRect();
        return { selectBottom: select?.bottom, actionTop: action?.top, actionRight: action?.right,
          viewport: innerWidth };
      })`);
      check(`${other.name}_actions_below_selector`, rows.length === 2 && rows.every(row =>
        row.actionTop >= row.selectBottom && row.actionRight <= row.viewport), rows);
    }
    const leak = await enumLeak(cdp);
    check(`${other.name}_config_no_enum_leak`, leak.length === 0, leak);
  }

  results.consoleErrors = cdp.consoleErrors();
  check('no_console_errors', results.consoleErrors.length === 0, results.consoleErrors.slice(0, 10));
} catch (error) {
  results.fatal = { message: String(error?.message ?? error), stack: String(error?.stack ?? '') };
  try { await shot(cdp, 'fatal-state'); } catch { /* ignore */ }
  results.consoleErrors = cdp.consoleErrors();
} finally {
  results.head = (await import('node:child_process')).execSync('git rev-parse HEAD').toString().trim();
  const passed = results.checks.filter(c => c.ok).length;
  const failed = results.checks.filter(c => !c.ok).length;
  results.summary = { passed, failed, total: results.checks.length, fatal: !!results.fatal };
  writeFileSync(`${OUT}/summary.json`, JSON.stringify(results, null, 2));
  console.log(JSON.stringify(results.summary));
  if (results.fatal) console.log('FATAL', results.fatal.message);
  cdp.close();
  await sleep(200);
  if (launched) launched.child.kill();
  process.exit(results.fatal || failed ? 1 : 0);
}
