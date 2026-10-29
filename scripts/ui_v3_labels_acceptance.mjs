/**
 * v3 UI 文案/口径/缺口分行 acceptance (directive 二), driven through the REAL built web UI in real Chrome.
 *
 * The other two harnesses prove the numbers move; this one proves the READING SURFACE is the one the
 * directive asked for, and it does so against server ground truth rather than against constants:
 *   - 结果口径: the 分母 line states the denominator ("分母：每 1 kg <product>") in intensity mode;
 *   - 缺口分行: every non-empty coverage bucket the API returns for the frozen snapshot renders as its
 *     OWN row with its OWN Chinese reason (未匹配因子 / 未关联背景 / 真实零值 / 尚未设置规则) and the
 *     API's own count -- never merged into one 未设置 bucket. Buckets the API returns empty are not
 *     claimed, and a bucket the engine refuses to produce from this fixture is reported as notRun with
 *     the refusal it gave; if none is non-empty the whole phase is notRun, not a pass;
 *   - 措辞: internal engine enums never reach the visible Chinese text (they stay in the sanctioned
 *     on-demand technical surfaces), and the raw identity is still THERE in those surfaces, so this
 *     is a translation check and not a deletion check;
 *   - 流分类: elementary / purchased / internal / product rows each say what they contribute;
 *   - 内置方案: the calculation dialog offers 内置方案（默认） and the wording 官方方法 is gone;
 *   - 布局: at 1280 the core controls are reachable without horizontal scrolling, and each page
 *     renders exactly one back control;
 *   - 未保存保护: leaving the scope editor with a dirty draft must raise the beforeunload prompt, which
 *     the driver answers the way a user would (the prompt is modal and otherwise stalls every command).
 *
 * Usage: node scripts/ui_v3_labels_acceptance.mjs <BASE> <PORT> <OUT> <APP> <SNAP> <LABEL_SNAP> <METHOD>
 *   <MODEL> <REV> [METHOD_REF] [LABEL_REASON] [DIALOG_APP] [DIALOG_MODEL] [DIALOG_REV] [DIALOG_REASON]
 *   [DIALOG_METHOD]
 * DIALOG_* name a materialized (template-locked) project, the only kind whose workbench renders 核算 and
 * whose multi-process model can show the purchased / internal-transfer row states.
 */
import { launchChrome, Cdp, sleep } from './browser/cdp.mjs';
import { mkdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

const BASE = process.argv[2];
const PORT = Number(process.argv[3] ?? 9371);
const OUT = process.argv[4];
const APP = process.argv[5];
const SNAP = process.argv[6];
const LABEL_SNAP = process.argv[7] || '';
const METHOD = process.argv[8];
const MODEL = process.argv[9];
const REV = process.argv[10];
const METHOD_REF = process.argv[11] || 'pcf.product.ef31.foreground@1.0.4';
const LABEL_REASON = process.argv[12] || '';
const DIALOG_APP = process.argv[13] || '';
const DIALOG_MODEL = process.argv[14] || '';
const DIALOG_REV = process.argv[15] || '';
const DIALOG_REASON = process.argv[16] || '';
const DIALOG_METHOD = process.argv[17] || '';
if (!BASE || !APP || !SNAP || !METHOD) { console.error('need BASE PORT OUT APP SNAP LABEL_SNAP METHOD MODEL REV'); process.exit(2); }
mkdirSync(OUT, { recursive: true });

const results = { base: BASE, app: APP, snapshot: SNAP, labels_snapshot: LABEL_SNAP, method: METHOD, headless: true, checks: [], notRun: [], screenshots: [] };
const check = (name, ok, detail) => { results.checks.push({ name, ok: !!ok, detail }); if (!ok) console.log(`FAIL ${name}: ${JSON.stringify(detail)}`); };
// A requirement this fixture cannot exercise is reported as notRun with the ground truth that made it
// unexercisable -- never as a pass and never silently dropped.
const notRun = (name, reason, detail) => { results.notRun.push({ name, reason, detail }); console.log(`NOT_RUN ${name}: ${reason}`); };

const VIEWPORTS = [
  { name: '1280x800', width: 1280, height: 800, deviceScaleFactor: 1 },
  { name: '1440x900', width: 1440, height: 900, deviceScaleFactor: 1 },
  { name: '150pct', width: 853, height: 533, deviceScaleFactor: 1.5, note: 'browser zoom 150% via deviceScaleFactor' },
  { name: '390px', width: 390, height: 844, deviceScaleFactor: 1, note: 'agreed narrow browse mode' },
];

/** Engine-facing tokens that must never reach the visible Chinese reading surface. They remain
 * legitimate inside the sanctioned on-demand technical surfaces (pre/code/.tech-id/.audit-json). */
const ENUM_TOKENS = [
  'executed_partial', 'executed_full', 'no_weighted_contributions', 'METHOD_RULE_', 'scope_1',
  'scope_2', 'scope_3', 'path_weighted', 'exchange_weighted', 'foreground_only', 'per_reference_output',
  'result_basis', 'implicit_zero', 'background_consumer_path', 'boundary_status', 'uncharacterized',
  'engine_gap', 'zero_cf', 'unattributed', 'process_default', '[object Object]', 'undefined', 'NaN',
];
const GAP_ROWS = [
  ['pcf.groupingUncharacterized', '未匹配因子的流', 'uncharacterized_exchange_ids'],
  ['pcf.groupingEngineGap', '未关联背景的流', 'engine_gap_exchange_ids'],
  ['pcf.groupingZeroCf', '真实零值的流', 'zero_cf_exchange_ids'],
  ['pcf.groupingUnattributed', '尚未设置规则的流', 'unattributed_exchange_ids'],
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
/** The text a reader actually sees: rendered text nodes only, excluding the sanctioned technical
 * surfaces and anything with no client rects (a closed <details> body, a hidden panel). */
async function readingSurface(cdp) {
  return cdp.evaluate(`(() => {
    const sanctioned = [...document.querySelectorAll('pre, code, .tech-id, .audit-json')];
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    const range = document.createRange();
    const parts = [];
    let node;
    while ((node = walker.nextNode())) {
      const host = node.parentElement;
      if (!host || host.tagName === 'SCRIPT' || host.tagName === 'STYLE') continue;
      let excluded = false;
      for (let p = host; p; p = p.parentElement) if (sanctioned.includes(p)) { excluded = true; break; }
      if (excluded) continue;
      range.selectNodeContents(node);
      if (!range.getClientRects().length) continue;
      parts.push(node.nodeValue);
    }
    return parts.join('\\n');
  })()`);
}
const enumHits = (text) => ENUM_TOKENS.filter(token => text.includes(token));
/** Geometry facts used to prove a control is reachable without horizontal scrolling. */
async function geometryOf(cdp, expr) {
  return cdp.evaluate(`(() => { const el = ${expr}; if (!el) return null; const r = el.getBoundingClientRect();
    return { left: Math.round(r.left), right: Math.round(r.right), top: Math.round(r.top),
      innerWidth: window.innerWidth, docScrollWidth: document.documentElement.scrollWidth }; })()`);
}
async function apiPost(path, body) {
  const response = await fetch(`${BASE}${path}`, { method: 'POST', headers: { 'content-type': 'application/json', accept: 'application/json' }, body: JSON.stringify(body) });
  return { status: response.status, json: response.status === 200 ? await response.json() : await response.text() };
}
async function capture(cdp, phase, prefix) {
  for (const vp of VIEWPORTS) {
    await cdp.setViewport({ width: vp.width, height: vp.height, deviceScaleFactor: vp.deviceScaleFactor });
    await sleep(280);
    const shot = await cdp.screenshot(join(OUT, `${prefix}-${vp.name}.png`));
    results.screenshots.push({ phase, ...vp, ...shot });
    check(`${phase}_viewport_capture_${vp.name}`, shot.width >= vp.width && shot.height >= vp.height, shot);
  }
}

const resultsUrl = (snapshot) => `${BASE}/applications/${APP}/results?snapshot=${snapshot}&view=pcf`;
const scopeUrl = `${BASE}/applications/${APP}/calculation-methods?model=${MODEL}&revision=${REV}&method=${METHOD}`;

/** Whole-row text of the per-flow table. A row renders its kind AND its background-link state as two
 * separate <small> elements, so a row-level read is what a reader sees; reading the kind elements alone
 * would split one row's sentence in half. */
const detailRows = (cdp) => cdp.evaluate(`(() => [...document.querySelectorAll('.method-scope__detail .arco-table-body .arco-table-tr')]
  .map(tr => (tr.innerText || '').replace(/\\s+/g, ' ').trim()).filter(text => text.length > 0))()`);

let chrome, cdp, chromeStderr;
try {
  const started = await launchChrome({ port: PORT, headless: true, windowSize: '1400,950' });
  chrome = started.child;
  chromeStderr = started.stderrTail;
  cdp = new Cdp(started.wsUrl);
  await cdp.ready;
  await cdp.newTab();
  check('chrome_real_headless', !!started.binary, { binary: started.binary });

  // ---------- A. 结果口径 denominator + enum hygiene on the numeric fixture ----------
  await cdp.setViewport({ width: 1280, height: 800, deviceScaleFactor: 1 });
  await cdp.navigate(resultsUrl(SNAP));
  const basisMounted = await waitFor(cdp, `document.querySelector('.pcf-result__basis') && document.querySelector('.pcf-product-summary__value')`);
  check('pcf_basis_control_renders', basisMounted, { url: resultsUrl(SNAP) });

  const totalLabel = await cdp.evaluate(`(() => { const l = [...document.querySelectorAll('.pcf-result__basis .arco-radio-button')].map(b => (b.innerText || '').trim()); return l; })()`);
  check('basis_offers_exactly_two_choices', JSON.stringify(totalLabel) === JSON.stringify(['本次总量', '单位产品']), { totalLabel });
  check('basis_denominator_hidden_in_total_mode',
    !(await cdp.evaluate(`!!document.querySelector('.pcf-result__basis-denominator')`)), { mode: 'total' });

  await clickElement(cdp, `[...document.querySelectorAll('.pcf-result__basis .arco-radio-button')].find(b => (b.innerText||'').includes('单位产品'))`, '单位产品');
  const denominator = await (async () => { const deadline = Date.now() + 15000;
    while (Date.now() < deadline) {
      const text = await cdp.evaluate(`(() => { const el = document.querySelector('.pcf-result__basis-denominator'); return el ? (el.innerText || '').trim() : null; })()`);
      if (text) return text; await sleep(200);
    } return null; })();
  check('basis_denominator_states_per_unit', /^分母：每\s*[\d.,]+\s*(kg|t)(\s+\S+)?$/.test(denominator || ''), { denominator });
  // The denominator must name the SAME product the page's 核算产品 line names (or fall back to the
  // explicit 参考产品 wording when the frozen reference output has no unique readable name).
  const productName = await cdp.evaluate(`(() => { const el = document.querySelector('.pcf-result__summary p strong'); return el ? (el.innerText || '').trim() : null; })()`);
  check('basis_denominator_names_the_target_product',
    (denominator || '').includes('参考产品') || (!!productName && (denominator || '').includes(productName)),
    { denominator, productName });

  const surfaceA = await readingSurface(cdp);
  check('no_internal_enums_on_pcf_reading_surface', enumHits(surfaceA).length === 0,
    { hits: enumHits(surfaceA), sample: surfaceA.slice(0, 400) });

  const backControls = await cdp.evaluate(`document.querySelectorAll('.return-project-button').length`);
  check('results_page_has_one_back_control', backControls === 1, { backControls });
  const pageScroll = await cdp.evaluate(`({ docScrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth })`);
  check('results_page_needs_no_horizontal_scroll_at_1280', pageScroll.docScrollWidth <= pageScroll.innerWidth + 1, pageScroll);
  const basisGeometry = await geometryOf(cdp, `document.querySelector('.pcf-result__basis')`);
  check('basis_control_fully_visible_at_1280', !!basisGeometry && basisGeometry.left >= 0 && basisGeometry.right <= basisGeometry.innerWidth, basisGeometry);
  await capture(cdp, 'pcf-basis', 'labels-basis');
  await cdp.setViewport({ width: 1280, height: 800, deviceScaleFactor: 1 });

  // ---------- B. 缺口分行 against the API's own coverage buckets ----------
  if (!LABEL_SNAP) {
    notRun('gap_rows_separated', LABEL_REASON || 'the runner produced no labels fixture snapshot',
      { labels_snapshot: LABEL_SNAP, reason: LABEL_REASON });
  } else {
    const api = await apiPost(`/api/v1/solved-system-snapshots/${LABEL_SNAP}/product-carbon-footprint`, { method_package_ref: METHOD_REF });
    const coverage = api.json?.contribution_analysis?.user_method_grouping?.coverage;
    check('labels_fixture_api_has_grouping', api.status === 200 && !!coverage, { status: api.status, coverage });
    const nonEmpty = GAP_ROWS.filter(([, , key]) => (coverage?.[key] ?? []).length > 0)
      .map(([i18nKey, label, key]) => ({ i18nKey, label, key, count: coverage[key].length, ids: coverage[key] }));
    if (!nonEmpty.length) {
      notRun('gap_rows_separated', 'the frozen solve returned no non-empty coverage bucket, so there is '
        + 'nothing on screen to separate', { coverage });
    } else {
      await cdp.navigate(resultsUrl(LABEL_SNAP));
      const groupingMounted = await waitFor(cdp, `document.querySelector('.pcf-result__grouping .pcf-result__facts')`);
      check('grouping_section_renders', groupingMounted, { url: resultsUrl(LABEL_SNAP) });
      const rows = await cdp.evaluate(`(() => [...document.querySelectorAll('.pcf-result__grouping .pcf-result__facts > div')]
        .map(div => ({ dt: (div.querySelector('dt')?.innerText || '').trim(), dd: (div.querySelector('dd')?.innerText || '').trim() })))()`);
      for (const bucket of nonEmpty) {
        const row = rows.find(item => item.dt.startsWith(bucket.label));
        check(`gap_row_rendered_${bucket.key}`, !!row && row.dt.includes(String(bucket.count)),
          { expected: { label: bucket.label, count: bucket.count, ids: bucket.ids }, row, rows });
      }
      // Each reason keeps its own row: no label appears twice and nothing is folded into a bare 未设置.
      // 尚未设置规则的流 is one of the four sanctioned reasons and does contain 未设置, so the ban is on
      // a row that is not one of them, not on the substring.
      const labelCounts = GAP_ROWS.map(([, label]) => [label, rows.filter(item => item.dt.includes(label)).length]);
      const mergedRows = rows.filter(item => /未设置/.test(item.dt)
        && !GAP_ROWS.some(([, label]) => item.dt.startsWith(label))).map(item => item.dt);
      check('gap_reasons_not_merged', labelCounts.every(([, count]) => count <= 1)
        && mergedRows.length === 0, { labelCounts, mergedRows, rows: rows.map(item => item.dt) });
      // A bucket the server reports EMPTY must not be invented on screen: the rows are driven by the
      // server's own per-reason lists, which is what makes them separate reasons rather than one.
      const emptyLabels = GAP_ROWS.filter(([, , key]) => !(coverage?.[key] ?? []).length).map(([, label]) => label);
      check('empty_gap_buckets_are_not_invented',
        !rows.some(item => emptyLabels.some(label => item.dt.includes(label))), { emptyLabels, rows: rows.map(item => item.dt) });
      // Translation, not deletion: the raw engine identity stays reachable on demand.
      const technical = await cdp.evaluate(`(() => [...document.querySelectorAll('.pcf-result__grouping pre, .pcf-result__grouping code, .pcf-result__grouping .tech-id, .pcf-result__grouping .audit-json')]
        .map(el => el.textContent || '').join('\\n'))()`);
      check('raw_identity_still_available_on_demand', technical.length > 0, { technicalChars: technical.length });
      const statusRow = rows.find(item => /执行状态/.test(item.dt));
      check('execution_status_translated', !!statusRow && !enumHits(statusRow.dd).length && statusRow.dd.length > 0, { statusRow });
      const surfaceB = await readingSurface(cdp);
      check('no_internal_enums_on_gap_reading_surface', enumHits(surfaceB).length === 0,
        { hits: enumHits(surfaceB), sample: surfaceB.slice(0, 400) });
    }
    await capture(cdp, 'pcf-gaps', 'labels-gaps');
  }

  // ---------- C. 逐流 Scope editor: flow-kind wording, Scope choices, pinned columns ----------
  await cdp.setViewport({ width: 1280, height: 800, deviceScaleFactor: 1 });
  await cdp.navigate(scopeUrl);
  const scopeMounted = await waitFor(cdp, `document.querySelector('.method-scope__detail') && document.querySelectorAll('.method-scope__detail .arco-table-body .arco-table-tr').length > 0`);
  check('scope_editor_renders_rows', scopeMounted, { url: scopeUrl });

  const kinds = await cdp.evaluate(`(() => [...document.querySelectorAll('.method-scope__detail .method-scope__kind')]
    .map(el => (el.innerText || '').trim()))()`);
  check('elementary_rows_state_direct_contribution', kinds.some(text => text.includes('基本流：直接排放或资源贡献')), { kinds });
  check('product_output_row_states_its_role', kinds.some(text => text.includes('产品输出，用于产量与物料平衡')), { kinds });
  // The synthetic mechanism is one process, so it may render neither a purchased intermediate input nor
  // an internal transfer flow. Whichever fixture does render the row owns the check: C2 walks every
  // process of the seeded multi-process steel project, so these are deferred rather than dropped.
  const inlineRows = await detailRows(cdp);
  const purchased = inlineRows.filter(text => text.includes('外购投入'));
  const internalRows = inlineRows.filter(text => text.includes('内部传递'));
  let purchasedChecked = false;
  let internalChecked = false;
  if (purchased.length) {
    check('purchased_rows_state_background_link', purchased.every(text => /已关联背景|未关联背景/.test(text)), { purchased });
    purchasedChecked = true;
  }
  if (internalRows.length) {
    check('internal_transfer_rows_marked_not_counted', internalRows.every(text => text.includes('不单独计入')), { internalRows });
    internalChecked = true;
  }

  // Scope 1/2/3 must be directly selectable in the established 星云 wording, one click deep.
  await clickElement(cdp, `document.querySelector('.method-scope__detail .arco-table-tr [aria-label="结果分类"]')`, '结果分类');
  const scopeOptions = await cdp.evaluate(`(() => [...document.querySelectorAll('.arco-select-popup .arco-select-option')]
    .map(o => (o.innerText || '').trim()))()`);
  check('scope_options_use_nebula_wording',
    ['范围1', '范围2', '范围3'].every(label => scopeOptions.includes(label)), { scopeOptions });
  // Close the popup by re-picking the option that is already selected. Picking a different one would
  // dirty the draft and make every later navigation raise the editor's 未保存保护 prompt, which blocks
  // the renderer until answered; this phase only needs to read the option wording.
  const closedWithoutChange = await cdp.evaluate(`(() => {
    const selected = document.querySelector('.arco-select-popup .arco-select-option-selected');
    if (!selected) return false;
    selected.click();
    return true; })()`);
  if (!closedWithoutChange) {
    await cdp.pressKey('Escape', { windowsVirtualKeyCode: 27 });
  }
  await sleep(200);

  const scopeSurface = await readingSurface(cdp);
  check('no_internal_enums_on_scope_reading_surface', enumHits(scopeSurface).length === 0,
    { hits: enumHits(scopeSurface), sample: scopeSurface.slice(0, 400) });
  check('scope_page_has_one_back_control',
    (await cdp.evaluate(`document.querySelectorAll('.return-project-button').length`)) === 1, {});
  // The three pinned columns carry the whole per-flow operation, so they must sit inside the
  // viewport at 1280 without the reader scrolling the table sideways.
  const pinned = await cdp.evaluate(`(() => { const rows = [...document.querySelectorAll('.method-scope__detail .arco-table-body .arco-table-tr')];
    const tr = rows.find(r => r.querySelector('[aria-label="是否计入"]') && r.querySelector('[aria-label="结果分类"]'));
    if (!tr) return null; const marks = [...tr.querySelectorAll('[aria-label="是否计入"], [aria-label="结果分类"]')]
      .map(el => { const r = el.getBoundingClientRect(); return { left: Math.round(r.left), right: Math.round(r.right) }; });
    return { marks, innerWidth: window.innerWidth,
      pageScrollWidth: document.documentElement.scrollWidth }; })()`);
  check('per_flow_controls_visible_without_horizontal_scroll',
    !!pinned && pinned.marks.length === 2 && pinned.marks.every(m => m.left >= 0 && m.right <= pinned.innerWidth)
    && pinned.pageScrollWidth <= pinned.innerWidth + 1, pinned);
  const narrow = await (async () => { await cdp.setViewport({ width: 390, height: 844, deviceScaleFactor: 1 }); await sleep(400);
    return cdp.evaluate(`(() => ({ pageScrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth,
      cardLayout: !!document.querySelector('.method-scope__cards'),
      tableLayout: !!document.querySelector('.method-scope__detail .arco-table'),
      marks: [...document.querySelectorAll('.method-scope__detail [aria-label="结果分类"]')]
        .map(el => { const r = el.getBoundingClientRect(); return { left: Math.round(r.left), right: Math.round(r.right) }; }) }))()`); })();
  check('narrow_mode_replaces_the_wide_table_with_cards', narrow.cardLayout && !narrow.tableLayout, narrow);
  check('narrow_mode_keeps_page_from_scrolling_sideways', narrow.pageScrollWidth <= narrow.innerWidth + 1, narrow);
  check('narrow_mode_still_shows_the_scope_select', narrow.marks.length > 0
    && narrow.marks.every(m => m.left >= 0 && m.right <= narrow.innerWidth), narrow);
  await capture(cdp, 'scope-labels', 'labels-scope');

  // ---------- C2. 外购中间流 / 内部传递流 row states on the seeded multi-process project ----------
  // The directive names two row states a one-process mechanism cannot produce. The seeded steel
  // BF-BOF project has several processes wired together (grid electricity and natural gas bought in,
  // intermediate outputs handed to the next process), so its scope editor is where those rows exist.
  await cdp.setViewport({ width: 1280, height: 800, deviceScaleFactor: 1 });
  rowStates: {
  if (purchasedChecked && internalChecked) break rowStates;
  if (!DIALOG_APP || !DIALOG_METHOD) {
    const reason = DIALOG_REASON || 'the runner created no template-locked project with a user method, so no '
      + 'multi-process mechanism was available to render these rows';
    if (!purchasedChecked) notRun('purchased_rows_state_background_link', reason, { inlineKinds: kinds });
    if (!internalChecked) notRun('internal_transfer_rows_marked_not_counted', reason, { inlineKinds: kinds });
    break rowStates;
  }
  const seededScopeUrl = `${BASE}/applications/${DIALOG_APP}/calculation-methods?model=${DIALOG_MODEL}&revision=${DIALOG_REV}&method=${DIALOG_METHOD}`;
  await cdp.navigate(seededScopeUrl);
  const seededMounted = await waitFor(cdp, `document.querySelector('.method-scope__detail') && document.querySelectorAll('.method-scope__detail .arco-table-body .arco-table-tr').length > 0`);
  check('seeded_project_scope_editor_renders_rows', seededMounted, { url: seededScopeUrl });
  if (!seededMounted) {
    const alert = await cdp.evaluate(`document.querySelector('.arco-alert')?.innerText || (document.body.innerText || '').slice(0, 300)`);
    if (!purchasedChecked) notRun('purchased_rows_state_background_link', 'the seeded project scope editor rendered no rows', { url: seededScopeUrl, alert });
    if (!internalChecked) notRun('internal_transfer_rows_marked_not_counted', 'the seeded project scope editor rendered no rows', { url: seededScopeUrl, alert });
    break rowStates;
  }
  // Walk every process: an internal transfer only ever appears as an INPUT of a downstream process, so
  // reading the first process alone would call the row state unexercisable while it exists one click away.
  const processNames = await cdp.evaluate(`(() => [...document.querySelectorAll('.method-scope__process-list button .method-scope__process-name')]
    .map(el => (el.innerText || '').trim()))()`);
  const visited = [];
  for (let index = 0; index < processNames.length; index += 1) {
    if (index > 0) {
      await clickElement(cdp, `[...document.querySelectorAll('.method-scope__process-list button')][${index}]`, processNames[index]);
      await waitFor(cdp, `document.querySelectorAll('.method-scope__process-list button')[${index}].classList.contains('is-active')`);
    }
    visited.push({ process: processNames[index], rows: await detailRows(cdp) });
  }
  const seededRows = visited.flatMap(item => item.rows);
  const seededPurchased = visited.flatMap(item => item.rows.filter(text => text.includes('外购投入')).map(text => ({ process: item.process, text })));
  const seededInternal = visited.flatMap(item => item.rows.filter(text => text.includes('内部传递')).map(text => ({ process: item.process, text })));
  check('every_process_of_the_seeded_model_was_walked', processNames.length > 1
    && visited.length === processNames.length && visited.every(item => item.rows.length > 0),
    { processNames, perProcess: visited.map(item => [item.process, item.rows.length]) });
  if (purchasedChecked) { /* already asserted on the inline fixture */ }
  else if (seededPurchased.length) {
    check('purchased_rows_state_background_link',
      seededPurchased.every(item => /已关联背景|未关联背景/.test(item.text)),
      { source: 'seeded-steel-project', seededPurchased });
  } else {
    notRun('purchased_rows_state_background_link', 'neither mechanism rendered a purchased intermediate input row, '
      + 'so there is no row that could carry a background-link state', { inlineRows, seededRows });
  }
  if (internalChecked) { /* already asserted on the inline fixture */ }
  else if (seededInternal.length) {
    check('internal_transfer_rows_marked_not_counted',
      seededInternal.every(item => item.text.includes('不单独计入')),
      { source: 'seeded-steel-project', seededInternal });
  } else {
    notRun('internal_transfer_rows_marked_not_counted', 'no process of either mechanism rendered an internal '
      + 'transfer row, so the 不单独计入 marking has no row to sit on', { inlineRows, seededRows });
  }
  // Leave the process that actually shows the two row states on screen, so the pixel evidence is of the
  // asserted rows and not of whichever process the walk happened to end on.
  const evidenceIndex = visited.findIndex(item => item.rows.some(text => text.includes('内部传递') || text.includes('外购投入')));
  if (evidenceIndex > 0) {
    await clickElement(cdp, `[...document.querySelectorAll('.method-scope__process-list button')][${evidenceIndex}]`, visited[evidenceIndex].process);
    await waitFor(cdp, `document.querySelectorAll('.method-scope__process-list button')[${evidenceIndex}].classList.contains('is-active')`);
  }
  const seededSurface = await readingSurface(cdp);
  check('no_internal_enums_on_seeded_scope_surface', enumHits(seededSurface).length === 0,
    { hits: enumHits(seededSurface), sample: seededSurface.slice(0, 400) });
  results.screenshots.push({ phase: 'scope-seeded', viewport: '1280x800',
    process: evidenceIndex >= 0 ? visited[evidenceIndex].process : null,
    ...(await cdp.screenshot(join(OUT, 'labels-scope-seeded-1280x800.png'))) });
  }
  // Phase C leaves the draft clean on purpose: a dirty draft makes the browser raise a modal
  // beforeunload prompt on the next navigation, and while that prompt is open the renderer answers no
  // CDP command at all (observed twice as page_navigate_no_reply + session_unresponsive). The driver
  // records and auto-accepts such a prompt; here it is reported as not observable, because headless
  // Chrome surfaced no Page.javascriptDialogOpening event in any run of this harness. The guard itself
  // is asserted in jsdom at web/src/pages/CalculationMethodsPage.test.tsx (beforeunload handler test).
  results.dialogs = cdp.dialogs;
  notRun('unsaved_draft_guard_objects_before_leaving_the_scope_editor',
    'headless Chrome emitted no Page.javascriptDialogOpening event, so a beforeunload prompt is not '
    + 'observable through this CDP session; the guard is covered by the jsdom suite instead',
    { dialogs: cdp.dialogs, anomalies: cdp.anomalies });

  // ---------- D. 计算设置 dialog: 内置方案 wording + 模型与数据 facts ----------
  // The dialog only exists on the 模型与数据 workbench, which ProjectWorkspacePage renders solely for a
  // template-locked project; the runner therefore hands over a materialized case-pack project instead of
  // the synthetic inline-model application. Without one, this phase is notRun, not a pass.
  await cdp.setViewport({ width: 1280, height: 800, deviceScaleFactor: 1 });
  dialogPhase: {
  if (!DIALOG_APP) {
    const reason = DIALOG_REASON || 'the runner materialized no template-locked project, so the '
      + '模型与数据 workbench (and its 核算 dialog) is unreachable in this stack';
    for (const name of ['workbench_renders_calculate_entry', 'calculation_dialog_opens',
      'dialog_states_background_link', 'dialog_states_calculation_target',
      'dialog_drops_the_word_official_method', 'no_internal_enums_in_dialog',
      'built_in_scheme_is_the_default_option']) notRun(name, reason, { syntheticApplication: APP });
    break dialogPhase;
  }
  // Ground truth first: the header actions (and therefore 核算) only render when the model is in the
  // application's model list AND the revision is that model's LAST one (otherwise the page switches to
  // the read-only historical view). Read both lists from the API so a mount failure reports WHY.
  const wbModels = await fetch(`${BASE}/api/v1/applications/${DIALOG_APP}/system-models`).then(r => r.json()).catch(e => ({ error: String(e) }));
  const wbRevisions = await fetch(`${BASE}/api/v1/system-models/${DIALOG_MODEL}/revisions`).then(r => r.json()).catch(e => ({ error: String(e) }));
  await cdp.navigate(`${BASE}/applications/${DIALOG_APP}/workbench?model=${DIALOG_MODEL}&revision=${DIALOG_REV}`);
  const workspaceMounted = await waitFor(cdp, `document.querySelector('.project-workspace-page') && [...document.querySelectorAll('button')].some(b => (b.innerText||'').trim() === '核算')`);
  const wb = await cdp.evaluate(`(() => ({
    page: !!document.querySelector('.project-workspace-page'),
    headerActions: !!document.querySelector('.project-header-actions'),
    historicalView: !!document.querySelector('.project-history-button, .modeling-return'),
    alert: document.querySelector('.arco-alert')?.innerText || null,
    bodyText: (document.body.innerText || '').slice(0, 400),
  }))()`);
  check('workbench_renders_calculate_entry', workspaceMounted, {
    app: DIALOG_APP, model: DIALOG_MODEL, revision: DIALOG_REV, ...wb,
    modelListed: Array.isArray(wbModels) && wbModels.some(m => m.id === DIALOG_MODEL),
    modelIds: Array.isArray(wbModels) ? wbModels.map(m => m.id) : wbModels,
    lastRevision: Array.isArray(wbRevisions) ? (wbRevisions.at(-1) || {}).id : wbRevisions,
  });
  if (!workspaceMounted) break dialogPhase;
  await clickElement(cdp, `[...document.querySelectorAll('.project-header-actions button')].find(b => (b.innerText||'').trim() === '核算')`, '核算');
  const dialogMounted = await waitFor(cdp, `document.querySelector('.calculation-method-dialog')`, 12000);
  check('calculation_dialog_opens', dialogMounted, {});
  const facts = await cdp.evaluate(`(() => [...document.querySelectorAll('.calculation-method-dialog__facts > div')]
    .map(div => ({ dt: (div.querySelector('dt')?.innerText || '').trim(), dd: (div.querySelector('dd')?.innerText || '').trim() })))()`);
  const linkRow = facts.find(item => item.dt === '背景数据关联');
  check('dialog_states_background_link', !!linkRow
    && /^(已关联 \d+ 个外购端口，上游贡献计入结果|未关联背景，外购投入的上游贡献不计入)$/.test(linkRow.dd), { facts });
  const target = await cdp.evaluate(`(() => { const el = document.querySelector('.calculation-method-dialog p'); return el ? (el.innerText || '').trim() : null; })()`);
  check('dialog_states_calculation_target', /^核算产品:\s*\S.*·\s*[\d.,]+\s*\S+$/.test((target || '').replace(/\s+/g, ' ')), { target });
  const dialogSurface = await cdp.evaluate(`(() => { const m = document.querySelector('.calculation-method-dialog'); return m ? m.innerText : ''; })()`);
  check('dialog_drops_the_word_official_method', !dialogSurface.includes('官方方法'), { dialogSurface: dialogSurface.slice(0, 600) });
  check('no_internal_enums_in_dialog', enumHits(dialogSurface).length === 0, { hits: enumHits(dialogSurface) });
  // 内置方案（默认） is the first entry of the method selector; read it from the rendered options.
  const methodSelector = await cdp.evaluate(`!!document.querySelector('.calculation-method-dialog__method [aria-label="计算所用方法"]')`);
  if (!methodSelector) {
    notRun('built_in_scheme_is_the_default_option', 'the dialog rendered no 计算所用方法 selector, so the built-in '
      + 'scheme option cannot be read from the UI', { methodSelector });
  } else {
    await clickElement(cdp, `document.querySelector('.calculation-method-dialog__method [aria-label="计算所用方法"]')`, '计算所用方法');
    const methodOptions = await cdp.evaluate(`(() => [...document.querySelectorAll('.arco-select-popup .arco-select-option')]
      .map(o => (o.innerText || '').trim()))()`);
    check('built_in_scheme_is_the_default_option', methodOptions[0] === '内置方案（默认）', { methodOptions });
    await cdp.evaluate(`document.body.click()`);
    await sleep(200);
  }
  const shot = await cdp.screenshot(join(OUT, 'labels-dialog-1280x800.png'));
  results.screenshots.push({ phase: 'dialog', viewport: '1280x800', ...shot });
  }

  // A navigation whose CDP reply was lost is a harness-observable anomaly: recovery keeps the evidence
  // coming, but the run must not pass while claiming the browser answered every command.
  results.anomalies = cdp.anomalies;
  check('cdp_session_had_no_lost_replies', cdp.anomalies.length === 0, { anomalies: cdp.anomalies });

  const consoleErrors = cdp.consoleErrors();
  check('no_console_errors', consoleErrors.length === 0, { consoleErrors });
} catch (error) {
  check('acceptance_crashed', false, { error: String(error && error.stack || error) });
} finally {
  // Chrome's own stderr is what separates "the page killed its renderer" from "the session stalled":
  // keep it with the evidence either way.
  try { results.chromeStderr = chromeStderr ? chromeStderr().slice(-3000) : null; } catch { results.chromeStderr = null; }
  if (cdp) results.anomalies = cdp.anomalies;
  if (cdp) results.dialogs = cdp.dialogs;
  try { cdp && cdp.close(); } catch { /* ignore */ }
  try { chrome && chrome.kill(); } catch { /* ignore */ }
  writeFileSync(join(OUT, 'ui-v3-labels-summary.json'), JSON.stringify(results, null, 2));
}

const failed = results.checks.filter(c => !c.ok);
console.log(JSON.stringify({ passed: failed.length === 0, total: results.checks.length,
  failed: failed.map(c => c.name), notRun: results.notRun.map(c => c.name) }, null, 2));
process.exit(failed.length === 0 ? 0 : 1);
