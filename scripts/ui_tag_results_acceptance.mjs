/** Real Chrome result acceptance over a dedicated local instance.
 * Usage: node scripts/ui_tag_results_acceptance.mjs <base> <summaryPath> <debugPort> <evidenceDir>
 * All product writes and selections go through visible controls. API calls only read evidence.
 */
import assert from 'node:assert/strict';
import { mkdirSync, readFileSync, readdirSync, statSync, writeFileSync } from 'node:fs';
import { resolve, join } from 'node:path';
import { createHash } from 'node:crypto';
import { launchChrome, Cdp, sleep } from './browser/cdp.mjs';

const [base, summaryPath, debugPort, evidenceDir] = process.argv.slice(2);
assert.ok(base && summaryPath && debugPort && evidenceDir, 'Expected base, summaryPath, debugPort, evidenceDir');
assert.ok(['127.0.0.1', 'localhost'].includes(new URL(base).hostname), 'Use a dedicated local acceptance instance');
const source = JSON.parse(readFileSync(summaryPath, 'utf8'));
assert.ok(source.passed && source.schemes.length === 2 && source.expected.length === 2, 'Expected real-engine two-scheme evidence');
const out = resolve(evidenceDir), downloadDir = join(out, 'downloads');
mkdirSync(downloadDir, { recursive: true });
const report = { base, source: resolve(summaryPath), startedAt: new Date().toISOString(),
  applicationId: source.application_id, revisionId: source.revision_id, snapshotId: source.snapshot_id,
  checks: [], modes: [], screenshots: [], downloads: [], httpErrors: [], consoleErrors: [], uiIssues: [] };
const resultUrl = `${base}/applications/${source.application_id}/results?snapshot=${source.snapshot_id}&revision=${source.revision_id}&view=pcf`;
const panel = `document.querySelector('.pcf-result__tag-grouping')`;
const visible = `e=>{const r=e.getBoundingClientRect();return r.width>0&&r.height>0&&getComputedStyle(e).visibility!=='hidden'}`;
const button = (label, scope = 'document') => `[...${scope}.querySelectorAll('button')].filter(${visible}).find(e=>e.textContent.trim()===${JSON.stringify(label)})`;
const modal = `[...document.querySelectorAll('.arco-modal')].filter(${visible}).at(-1)`;
let chrome, cdp;
const check = name => { report.checks.push(name); console.log(name); };
async function wait(expression, timeout = 24000) {
  const until = Date.now() + timeout;
  while (Date.now() < until) {
    if (await cdp.evaluate(`!!(${expression})`)) return;
    await sleep(150);
  }
  throw new Error(`Timed out: ${expression}`);
}
async function click(expression) {
  let previous, target;
  const until = Date.now() + 18000;
  while (Date.now() < until) {
    const current = await cdp.evaluate(`(()=>{const e=${expression};if(!e)return null;
      const r=e.getBoundingClientRect();if(!r.width||!r.height||e.disabled)return null;
      if(r.top<0||r.bottom>innerHeight||r.left<0||r.right>innerWidth){e.scrollIntoView({block:'center',inline:'nearest'});return null;}
      const x=r.x+r.width/2,y=r.y+r.height/2,hit=document.elementFromPoint(x,y);
      return hit&&(hit===e||e.contains(hit))?{x,y,w:r.width,h:r.height}:null;})()`);
    if (current && previous && Object.keys(current).every(key => Math.abs(current[key] - previous[key]) < 0.5)) { target = current; break; }
    previous = current; await sleep(120);
  }
  assert.ok(target, `No stable clickable control: ${expression}`);
  for (const type of ['mouseMoved', 'mousePressed', 'mouseReleased']) await cdp.send('Input.dispatchMouseEvent', {
    type, x: target.x, y: target.y, button: 'left', clickCount: 1,
  }, cdp.sessionId);
  await sleep(180);
}
async function fill(expression, value) {
  await click(expression);
  for (const type of ['keyDown', 'keyUp']) await cdp.send('Input.dispatchKeyEvent', {
    type, key: 'a', code: 'KeyA', windowsVirtualKeyCode: 65, modifiers: 2,
  }, cdp.sessionId);
  await cdp.send('Input.insertText', {text: value}, cdp.sessionId);
}
async function option(selector, label) {
  await click(`document.querySelector(${JSON.stringify(selector)})`);
  await click(`[...document.querySelectorAll('.arco-select-option')].filter(${visible}).find(e=>e.textContent.trim()===${JSON.stringify(label)})`);
}
async function get(path) {
  const response = await fetch(`${base}/api/v1${path}`);
  assert.equal(response.status, 200, `${path}: ${response.status} ${await response.clone().text()}`);
  return response.json();
}
async function screenshot(name) {
  report.screenshots.push(await cdp.screenshot(join(out, `${name}.png`)));
}
async function readGrouping(mode) {
  await wait(`(()=>{const p=document.querySelector('.tag-result > .frozen-input-identity pre');
    if(!p)return false;const d=JSON.parse(p.textContent);return d.mode===${JSON.stringify(mode)}&&d.schemes.length===2;})()`);
  const data = await cdp.evaluate(`JSON.parse(document.querySelector('.tag-result > .frozen-input-identity pre').textContent)`);
  assert.equal(data.snapshot_id, source.snapshot_id);
  assert.equal(data.semantics, 'result_category.v1');
  assert.ok(data.schemes.every(item => item.semantics === 'result_category.v1' && item.populated === true));
  assert.deepEqual(data.schemes.map(item => ({method_id: item.scheme.method_id, version: item.scheme.version,
    content_sha256: item.scheme.content_sha256})).sort((a,b)=>a.method_id.localeCompare(b.method_id)),
    [...source.schemes].sort((a,b)=>a.method_id.localeCompare(b.method_id)));
  const rendered = await cdp.evaluate(`[...document.querySelectorAll('.tag-result__scheme')].map(e=>({
    name:e.querySelector('.tag-result__scheme-head strong').textContent,
    value:e.querySelector('.tag-result__scheme-head .tabular').textContent,
    categoryValue:e.querySelector('tbody .tabular')?.textContent??null}))`);
  for (let index = 0; index < source.schemes.length; index++) {
    const actual = data.schemes.find(item => item.scheme.method_id === source.schemes[index].method_id);
    assert.ok(Math.abs(actual.tag_total.value - source.expected[index]) < 1e-8);
    const card = rendered.find(item => item.name === actual.scheme.name);
    assert.ok(card && Math.abs(parseFloat(card.value.replaceAll(',', '')) - source.expected[index]) < 1e-6, 'Visible scheme total differs from real receipt');
    assert.ok(Math.abs(parseFloat(card.categoryValue.replaceAll(',', '')) - source.expected[index]) < 1e-6, 'Visible category subtotal differs from real receipt');
  }
  let setValue = null;
  if (mode !== 'separate') {
    const expectedSet = source.persisted.find(item => item.result.mode === mode).result[mode].value;
    const text = await cdp.evaluate(`document.querySelector('.tag-result__set .tabular').textContent`);
    setValue = parseFloat(text.replaceAll(',', ''));
    assert.ok(Math.abs(setValue - expectedSet) < 1e-6, `Visible ${mode} total differs from real receipt`);
  }
  report.modes.push({mode, resultId: data.result_id, rendered, setValue, contentSha256: data.content_sha256});
  return data;
}
async function download(format, expected) {
  const before = new Set(readdirSync(downloadDir));
  await click(button(format === 'html' ? '导出归集报告' : '导出归集数据', `(${panel})`));
  let file;
  const until = Date.now() + 15000;
  while (Date.now() < until) {
    const names = readdirSync(downloadDir).filter(name => !before.has(name) && name.endsWith(`.${format}`));
    if (names.length === 1 && statSync(join(downloadDir, names[0])).size > 0) { file = join(downloadDir, names[0]); break; }
    await sleep(150);
  }
  assert.ok(file, `No real ${format} download completed`);
  const bytes = readFileSync(file), text = bytes.toString('utf8');
  if (format === 'json') {
    const result = JSON.parse(text);
    assert.equal(result.result_id, expected.result_id);
    assert.equal(result.content_sha256, expected.content_sha256);
    assert.equal(result.snapshot_id, source.snapshot_id);
    assert.deepEqual(result.schemes, expected.schemes);
  } else {
    assert.match(text, /<!doctype html>/i);
    assert.ok(text.includes('结果分类归集结果'), 'HTML does not use result-category wording');
    assert.ok(text.includes('已分类贡献小计'), 'HTML does not label assigned contributions');
    for (const scheme of expected.schemes) assert.ok(text.includes(scheme.scheme.name), 'HTML missing frozen scheme name');
    assert.ok(text.includes(expected.content_sha256), 'HTML missing frozen result hash');
  }
  report.downloads.push({format, file, bytes: bytes.length, sha256: createHash('sha256').update(bytes).digest('hex'), resultId: expected.result_id});
}
try {
  chrome = await launchChrome({port: Number(debugPort)});
  cdp = new Cdp(chrome.wsUrl); await cdp.ready; await cdp.newTab();
  await cdp.send('Browser.setDownloadBehavior', {behavior:'allow',downloadPath:downloadDir,eventsEnabled:true});
  await cdp.send('Network.enable', {}, cdp.sessionId);
  cdp.ws.addEventListener('message', event => {
    const data = JSON.parse(event.data);
    if (data.method === 'Network.responseReceived' && data.params.response.status >= 400) report.httpErrors.push({url:data.params.response.url,status:data.params.response.status});
    if (data.method === 'Runtime.exceptionThrown') report.consoleErrors.push(data.params.exceptionDetails.exception?.description ?? data.params.exceptionDetails.text);
    if (data.method === 'Log.entryAdded' && data.params.entry.level === 'error') report.consoleErrors.push(data.params.entry.text);
    if (data.method === 'Network.requestWillBeSent' && data.params.request.url.includes('/conversion-preview') && data.params.request.method === 'POST') {
      (report.previewBodies ??= []).push({ url: data.params.request.url, body: data.params.request.postData });
    }
  });
  await cdp.setViewport({width:1440,height:900});
  await cdp.navigate(resultUrl);
  await wait(`${panel}?.querySelector('.tag-result__schemes')`);
  await screenshot('results-first-screen-1440');
  const methods = await get(`/applications/${source.application_id}/calculation-methods?model_revision_id=${source.revision_id}`);
  const names = source.schemes.map(ref => methods.find(method => method.id === ref.method_id)?.name);
  assert.ok(names.every(Boolean));
  const checkbox = name => `[...document.querySelectorAll('.tag-result__schemes label')].find(e=>e.textContent.includes(${JSON.stringify(name)}))`;
  for (const name of names) {
    await wait(checkbox(name));
    if (!(await cdp.evaluate(`(${checkbox(name)}).querySelector('input').checked`))) await click(checkbox(name));
  }
  const separate = await readGrouping('separate');
  await cdp.evaluate(`(${panel}).scrollIntoView({block:'start'})`); await sleep(250); await screenshot('tag-separate-1440');
  check('Two exact schemes and their visible category subtotals match the real engine receipt');
  await option('[aria-label="查看方式"]', '并集');
  await readGrouping('union'); await screenshot('tag-union-1440');
  await option('[aria-label="查看方式"]', '交集');
  const intersection = await readGrouping('intersection'); await screenshot('tag-intersection-1440');
  check('Union and intersection visible values match the expected de-duplicated contributions');

  await cdp.send('Page.reload', {ignoreCache:true}, cdp.sessionId);
  await wait(`${panel}?.querySelector('[aria-label="历史归集结果"]')`);
  const history = await get(`/applications/${source.application_id}/tag-grouping-results?snapshot_id=${source.snapshot_id}`);
  const candidates = history.filter(item => item.result_id && item.indicator_key === intersection.indicator_key);
  const historyIndex = candidates.findIndex(item => item.result_id === intersection.result_id);
  assert.ok(historyIndex >= 0);
  await click(`document.querySelector('[aria-label="历史归集结果"]')`);
  const options = await cdp.evaluate(`[...document.querySelectorAll('.arco-select-option')].filter(${visible}).map(e=>e.textContent.trim())`);
  report.historyOptions = options;
  if (new Set(options).size !== options.length) report.uiIssues.push('Historical choices contain duplicate labels; result modes cannot be distinguished before opening');
  await screenshot('tag-history-options-1440');
  await click(`[...document.querySelectorAll('.arco-select-option')].filter(${visible})[${historyIndex + 1}]`);
  await wait(`JSON.parse(document.querySelector('.tag-result > .frozen-input-identity pre')?.textContent||'{}').result_id===${JSON.stringify(intersection.result_id)}`);
  const reread = await readGrouping('intersection');
  assert.equal(reread.result_id, intersection.result_id);
  assert.equal(reread.content_sha256, intersection.content_sha256);
  check('After a browser reload, the historical selection reads the same frozen result and hash');
  await download('html', reread); await download('json', reread);
  check('Visible HTML and JSON export buttons download complete files for the selected frozen result');

  // Create an independent draft through the same project UI so the unfinished-plan next step is observable.
  await cdp.navigate(`${base}/applications/${source.application_id}/calculation-methods?revision=${source.revision_id}`);
  await wait(button('新建结果分类')); await click(button('新建结果分类'));
  const draftName = `待检查结果分类 ${Date.now()}`;
  await fill(`document.querySelector('.calculation-methods__create input')`, draftName);
  await click(button('创建并编辑'));
  await wait('document.querySelector(".tag-scheme")');
  report.draftMethodId = await cdp.evaluate('new URLSearchParams(location.search).get("method")');
  const draft = await get(`/calculation-methods/${report.draftMethodId}`);
  assert.equal(draft.method.model_revision_id, source.revision_id);
  assert.equal(draft.versions.at(-1).semantics, 'result_category.v1');
  await cdp.navigate(resultUrl);
  const draftLink = `[...document.querySelectorAll('.pcf-result__tag-grouping a')].find(e=>e.textContent.includes(${JSON.stringify(draftName)}))`;
  await wait(draftLink); await click(draftLink);
  await wait('document.querySelector(".tag-scheme")');
  assert.equal(await cdp.evaluate('new URLSearchParams(location.search).get("method")'), report.draftMethodId);
  assert.equal(await cdp.evaluate('new URLSearchParams(location.search).get("revision")'), source.revision_id);
  await click(button('检查')); await wait(button('校验该方法版本', `(${modal})`));
  await screenshot('draft-check-entry-1440');
  check('The draft notice leads to the exact model revision and scheme check dialog');

  // A legacy scheme stays reachable as read-only history instead of being hidden behind the new entry.
  const legacy = await get(`/calculation-methods/${source.legacy_conversion.source_method_id}`);
  await cdp.navigate(`${base}/applications/${legacy.method.application_id}/calculation-methods?revision=${legacy.method.model_revision_id}&method=${source.legacy_conversion.source_method_id}`);
  await wait(`document.body.textContent.includes('旧标签方案保持原样只读')`);
  const has = label => cdp.evaluate(`!![...document.querySelectorAll('button')].filter(${visible}).find(e=>e.textContent.trim()===${JSON.stringify(label)})`);
  assert.equal(await has('保存为新版本'), false, 'Legacy scheme must not offer in-place save');
  assert.equal(await has('管理分类'), false, 'Legacy scheme must not offer category editing');
  await click(button('转换为结果分类'));
  await wait(`document.querySelector('.legacy-conversion')?.textContent.includes('1 条归属会带入新口径。')`);
  const legacyDialog = await cdp.evaluate(`document.querySelector('.legacy-conversion').innerText`);
  assert.ok(legacyDialog.includes('1 条旧“已选但未分类”会变为“无”'), legacyDialog);
  await screenshot('legacy-conversion-preview-1440');
  await click(button('取消', `(${modal})`));
  await wait(`!document.querySelector('.legacy-conversion')`);
  check('Legacy tag scheme stays reachable read-only and previews its conversion in the browser');

  // A pre-caliber ordinary method (no semantics) is read-only as well, both where the template
  // inherited it into the project and from the template configuration itself.
  const ordinary = source.legacy_ordinary;
  assert.ok(ordinary?.inherited_method_id, 'Live summary lacks the inherited legacy ordinary method');
  const ordinaryUrl = `${base}/applications/${source.application_id}/calculation-methods?revision=${ordinary.initial_revision_id}&method=${ordinary.inherited_method_id}`;
  const hasButton = label => cdp.evaluate(`!![...document.querySelectorAll('button')].filter(${visible}).find(e=>e.textContent.trim()===${JSON.stringify(label)})`);
  await cdp.navigate(ordinaryUrl);
  await wait(`document.body.textContent.includes('旧普通方法保持原样只读')`);
  assert.equal(await hasButton('保存为新版本'), false, 'Legacy ordinary method must not offer in-place save');
  assert.equal(await hasButton('管理分类'), false, 'Legacy ordinary method must not expose the category editor');
  assert.equal(await cdp.evaluate(`!!document.querySelector('[aria-label="是否计入"]')`), false, 'Legacy ordinary method must not reopen the inclusion editor');
  assert.equal(await cdp.evaluate(`!!document.querySelector('[aria-label="结果分类"]')`), false, 'Legacy ordinary method must not expose per-flow category pickers');
  assert.ok(await cdp.evaluate(`document.body.textContent.includes('旧范围分布')`), 'Legacy ordinary history is not shown');
  await screenshot('legacy-ordinary-readonly-1440');
  await click(button('转换为结果分类'));
  await wait(`document.querySelector('.legacy-conversion')?.textContent.includes('旧方法没有分类树')`);
  assert.ok(await cdp.evaluate(`(${modal}).textContent.includes('还有 1 条旧归属未处理')`), 'Scope-only conversion is not blocked before a decision');
  const submit = button('创建结果分类口径', `(${modal})`);
  assert.equal(await cdp.evaluate(`!!(${submit})?.disabled`), true, 'Conversion is enabled with an unresolved legacy assignment');
  await fill(`document.querySelector('.legacy-conversion__target input')`, '现场排放');
  await click(button('添加分类', `(${modal})`));
  await wait(`document.querySelector('.legacy-conversion__target [aria-label="分类 1"]')`);
  await fill(`document.querySelector('.legacy-conversion__target [aria-label="分类 1"]')`, '现场');
  await wait(`document.querySelector('.legacy-conversion [aria-label="第 1 条旧归属"]')`);
  await option('.legacy-conversion [aria-label="第 1 条旧归属"]', '现场');
  await wait(`!(${submit})?.disabled`);
  assert.ok(await cdp.evaluate(`(${modal}).textContent.includes('1 条带入新口径')`), 'Confirmed impact is not shown');
  // Converting the same source twice must not reuse its name; the name field is the last input.
  await fill(`[...document.querySelectorAll('.legacy-conversion input')].at(-1)`, `现场排放结果分类 ${Date.now()}`);
  await screenshot('legacy-ordinary-mapped-1440');
  await click(submit);
  await wait(`new URLSearchParams(location.search).get('method')!==${JSON.stringify(ordinary.inherited_method_id)}`, 30000);
  report.ordinaryConvertedMethodId = await cdp.evaluate(`new URLSearchParams(location.search).get('method')`);
  const ordinaryConverted = await get(`/calculation-methods/${report.ordinaryConvertedMethodId}`);
  assert.equal(ordinaryConverted.versions[0].semantics, 'result_category.v1');
  const ordinaryDimension = ordinaryConverted.versions[0].reporting_dimensions;
  assert.equal(ordinaryDimension.length, 1);
  assert.equal(ordinaryDimension[0].name, '现场排放');
  const ordinaryLeaf = ordinaryDimension[0].categories.find(item => item.name === '现场');
  assert.ok(ordinaryLeaf, 'Chosen target category is missing from the converted method');
  assert.deepEqual(ordinaryConverted.versions[0].rules.map(item => item.categories), [{[ordinaryDimension[0].id]: ordinaryLeaf.id}]);
  const ordinarySource = await get(`/calculation-methods/${ordinary.inherited_method_id}`);
  assert.equal(ordinarySource.versions[0].content_sha256, ordinary.source_content_sha256);
  assert.equal(ordinarySource.versions[0].rules[0].scope, 'scope_1');
  await cdp.navigate(`${base}/templates/${source.template_id}/config?method=${ordinary.source_method_id}`);
  await wait(`document.body.textContent.includes('旧普通方法保持原样只读')`);
  assert.equal(await hasButton('保存为新版本'), false, 'Template view must not offer in-place save for the legacy ordinary method');
  assert.equal(await cdp.evaluate(`!!document.querySelector('[aria-label="是否计入"]')`), false);
  assert.ok(await hasButton('转换为结果分类'), 'Template view must offer the conversion entry');
  await screenshot('template-legacy-ordinary-readonly-1440');
  check('Legacy ordinary method stays read-only in the project and template, and its scope-only history converts only after an explicit target mapping');

  // An invalid legacy category never silently becomes “无”: conversion stays blocked until the
  // reader maps it to a declared leaf, and the source keeps its invalid category and exact bytes.
  const invalid = source.invalid_mapping;
  assert.ok(invalid?.source_method_id, 'Live summary lacks the invalid legacy category case');
  await cdp.navigate(`${base}/applications/${invalid.application_id}/calculation-methods?revision=${invalid.revision_id}&method=${invalid.source_method_id}`);
  await wait(`document.body.textContent.includes('旧标签方案保持原样只读')`);
  await click(button('转换为结果分类'));
  await wait(`document.querySelector('.legacy-conversion')?.textContent.includes('还有 1 条旧归属未处理')`);
  const invalidSubmit = button('创建结果分类口径', `(${modal})`);
  assert.equal(await cdp.evaluate(`!!(${invalidSubmit})?.disabled`), true, 'Invalid category conversion is enabled without a mapping');
  assert.ok(await cdp.evaluate(`document.querySelector('.legacy-conversion').textContent.includes('不在新分类树中')`), 'The old invalid category is not disclosed');
  await screenshot('legacy-invalid-category-blocked-1440');
  await option('.legacy-conversion [aria-label="第 1 条旧归属"]', 'Direct');
  await wait(`!(${invalidSubmit})?.disabled`);
  assert.ok(await cdp.evaluate(`(${modal}).textContent.includes('1 条带入新口径')`), 'Invalid category mapping impact is not shown');
  await fill(`[...document.querySelectorAll('.legacy-conversion input')].at(-1)`, `无效分类修复结果 ${Date.now()}`);
  await click(invalidSubmit);
  await wait(`new URLSearchParams(location.search).get('method')!==${JSON.stringify(invalid.source_method_id)}`, 30000);
  report.invalidRemappedMethodId = await cdp.evaluate(`new URLSearchParams(location.search).get('method')`);
  const remapped = await get(`/calculation-methods/${report.invalidRemappedMethodId}`);
  assert.equal(remapped.versions[0].semantics, 'result_category.v1');
  assert.deepEqual(remapped.versions[0].rules.map(item => item.categories), [{tag: 'direct'}]);
  const invalidSource = await get(`/calculation-methods/${invalid.source_method_id}`);
  assert.equal(invalidSource.versions[0].content_sha256, invalid.source_content_sha256);
  assert.deepEqual(invalidSource.versions[0].rules[0].categories, {tag: 'ghost'});
  check('Invalid legacy category blocks conversion in the browser until remapped, and the read-only source keeps its exact category and bytes');
  assert.deepEqual(report.httpErrors, []); assert.deepEqual(report.consoleErrors, []); assert.deepEqual(cdp.anomalies, []);
  report.passed = true;
} catch (error) {
  report.passed = false; report.error = error.stack;
  try { report.pageText = await cdp.evaluate('document.body.innerText'); await screenshot('failed'); } catch {}
} finally {
  report.finishedAt = new Date().toISOString();
  report.browserAnomalies = cdp?.anomalies ?? [];
  cdp?.close(); chrome?.child.kill();
  writeFileSync(join(out,'summary.json'), JSON.stringify(report,null,2));
}
console.log(JSON.stringify({passed:report.passed,checks:report.checks.length,uiIssues:report.uiIssues,error:report.error,out}));
process.exitCode = report.passed ? 0 : 1;
