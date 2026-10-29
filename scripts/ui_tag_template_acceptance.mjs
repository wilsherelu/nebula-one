/** Real browser journey; all writes use visible controls and CDP mouse/keyboard events.
 * Usage: node scripts/ui_tag_template_acceptance.mjs <base> <debug-port> <evidence-dir>
 * The target must be a dedicated acceptance instance, never a user's database.
 */
import assert from 'node:assert/strict';
import { mkdirSync, writeFileSync } from 'node:fs';
import { launchChrome, Cdp, sleep } from './browser/cdp.mjs';

const [base, debugPort, out] = process.argv.slice(2);
assert.ok(base && debugPort && out, 'Expected base URL, Chrome debugging port, evidence directory');
mkdirSync(out, { recursive: true });
const run = Date.now().toString();
const name = `结果分类模板验收 ${run}`;
const templateName = `结果分类模板 ${run}`;
const projectName = `结果分类项目 ${run}`;
const report = { base, startedAt: new Date().toISOString(), checks: [], screenshots: [], layouts: [], httpErrors: [], consoleErrors: [] };
let chrome, cdp;
const visible = `e => { const r=e.getBoundingClientRect(); return r.width>0 && r.height>0 && getComputedStyle(e).visibility!=='hidden'; }`;
const button = (text, scope = 'document') => `[...${scope}.querySelectorAll('button')].filter(${visible}).find(e=>e.textContent.trim()===${JSON.stringify(text)})`;
const modal = `[...document.querySelectorAll('.arco-modal')].filter(${visible}).at(-1)`;
const row = `[...document.querySelectorAll('.tag-scheme tr,.tag-scheme .method-scope__card')].filter(${visible}).find(e=>e.textContent.includes('二氧化碳')&&e.querySelector('[aria-label="结果分类"]'))`;
const check = label => { report.checks.push(label); console.log(label); };
async function wait(expression, timeout = 18000) {
  const until = Date.now() + timeout;
  while (Date.now() < until) {
    if (await cdp.evaluate(`!!(${expression})`)) return;
    await sleep(120);
  }
  throw new Error(`Timed out: ${expression}`);
}
async function click(expression) {
  // Arco keeps exiting popup nodes briefly. Wait for a stable, unobscured hit target rather than
  // reading an option from the previous popup and clicking after its closing animation removes it.
  let box, previous;
  const deadline = Date.now() + 18000;
  while (Date.now() < deadline) {
    const current = await cdp.evaluate(`(() => {
      const e=${expression}; if(!e) return null;
      const r=e.getBoundingClientRect();
      if(!r.width||!r.height||e.disabled) return null;
      if(r.top<0||r.bottom>innerHeight||r.left<0||r.right>innerWidth){e.scrollIntoView({block:'center',inline:'nearest'});return null;}
      const x=r.x+r.width/2,y=r.y+r.height/2,hit=document.elementFromPoint(x,y);
      return hit&&(hit===e||e.contains(hit))?{x,y,w:r.width,h:r.height}:null;
    })()`);
    if (current && previous && Object.keys(current).every(key => Math.abs(current[key] - previous[key]) < 0.5)) { box = current; break; }
    previous = current;
    await sleep(120);
  }
  assert.ok(box, `No stable clickable control: ${expression}`);
  for (const type of ['mouseMoved', 'mousePressed', 'mouseReleased']) {
    await cdp.send('Input.dispatchMouseEvent', { type, x: box.x, y: box.y, button: 'left', clickCount: 1 }, cdp.sessionId);
  }
  await sleep(150);
}
async function fill(expression, value) {
  await click(expression);
  await cdp.send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'a', code: 'KeyA', windowsVirtualKeyCode: 65, modifiers: 2 }, cdp.sessionId);
  await cdp.send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'a', code: 'KeyA', windowsVirtualKeyCode: 65, modifiers: 2 }, cdp.sessionId);
  await cdp.send('Input.insertText', { text: value }, cdp.sessionId);
  await sleep(100);
}
async function option(expression, label) {
  await cdp.evaluate(`(() => {window.__optionClicks=[];(${expression}).addEventListener('click',e=>window.__optionClicks.push({target:e.target.tagName,type:e.type,trusted:e.isTrusted}));})()`);
  await click(expression);
  (report.optionInteractions ??= []).push(await cdp.evaluate(`({label:${JSON.stringify(label)},clicks:window.__optionClicks,options:[...document.querySelectorAll('.arco-select-option')].filter(${visible}).map(e=>e.textContent.trim()),wrapper:(${expression}).parentElement.outerHTML.slice(0,1800)})`));
  const target = `[...document.querySelectorAll('.arco-select-option')].filter(${visible}).find(e=>e.textContent.trim()===${JSON.stringify(label)})`;
  await click(target);
}
async function get(path) {
  const response = await fetch(`${base}${path}`);
  assert.equal(response.status, 200, `${path}: ${response.status} ${await response.clone().text()}`);
  return response.json();
}
async function methodAt(version, status) {
  for (let i = 0; i < 100; i++) {
    const detail = await get(`/api/v1/calculation-methods/${report.methodId}`);
    const record = detail.versions.find(item => item.version === version);
    if (record && (!status || record.status === status)) return { detail, record };
    await sleep(150);
  }
  throw new Error(`Method version ${version} / ${status} was not persisted`);
}
async function screenshot(name) { report.screenshots.push(await cdp.screenshot(`${out}/${name}.png`)); }
async function closeModal() { await click(button('关闭', `(${modal})`)); }
const viewports = [
  ['1440', 1440, 900, 1], ['1280', 1280, 800, 1],
  ['150pct', 853, 533, 1.5], ['390', 390, 844, 1],
];
try {
  chrome = await launchChrome({ port: Number(debugPort) });
  cdp = new Cdp(chrome.wsUrl); await cdp.ready; await cdp.newTab();
  await cdp.send('Network.enable', {}, cdp.sessionId);
  cdp.ws.addEventListener('message', event => {
    const data = JSON.parse(event.data);
    if (data.method === 'Network.responseReceived' && data.params.response.status >= 400) {
      report.httpErrors.push({ url: data.params.response.url, status: data.params.response.status });
    }
    if (data.method === 'Runtime.exceptionThrown') report.consoleErrors.push(data.params.exceptionDetails.exception?.description ?? data.params.exceptionDetails.text);
    if (data.method === 'Log.entryAdded' && data.params.entry.level === 'error') report.consoleErrors.push(data.params.entry.text);
  });
  await cdp.setViewport({ width: 1440, height: 900 });
  await cdp.navigate(`${base}/templates`);
  await wait('document.querySelector(".template-library-card")');
  await click(`[...document.querySelectorAll('.template-library-card button')].find(e=>e.textContent.trim()==='配置模板')`);
  await wait(button('新建结果分类'));
  report.templateUrl = await cdp.evaluate('location.href');
  const templateMatch = report.templateUrl.match(/templates\/([^/?]+)/);
  assert.ok(templateMatch, report.templateUrl);
  report.sourceTemplateId = templateMatch[1];
  await click(button('新建结果分类'));
  await fill(`(${modal}).querySelector('input')`, name);
  // Create a leaf up front; later deletion must preserve the assigned flow by reclassifying it.
  await fill(`(${modal}).querySelectorAll('input')[1]`, '临时分类');
  await click(button('创建并编辑', `(${modal})`));
  await wait('document.querySelector(".tag-scheme")');
  report.editorUrl = await cdp.evaluate('location.href');
  report.methodId = await cdp.evaluate('new URLSearchParams(location.search).get("method")');
  let created = await methodAt(1);
  assert.equal(created.record.semantics, 'result_category.v1');
  assert.deepEqual(created.record.rules, []);
  check('Template entry creates an actual result_category.v1 caliber with no legacy switch');

  await click(button('添加结果分类'));
  await fill(`document.querySelectorAll('.tag-scheme__category-inline [aria-label="分类名称"]').item(1)`, '现场排放');
  await wait(row);
  await option(`(${row}).querySelector('[aria-label="结果分类"]')`, '临时分类');
  const temporary = `[...document.querySelectorAll('.tag-scheme__cat-row')].find(e=>e.querySelector('input')?.value==='临时分类')`;
  await click(button('删除', `(${temporary})`));
  await wait(`(${modal}).textContent.includes('1 条归属')`);
  await screenshot('delete-category-impact');
  await option(`(${modal}).querySelector('[aria-label="这些归属如何处理"]')`, '现场排放');
  await click(button('删除分类', `(${modal})`));
  assert.ok(await cdp.evaluate(`(${row}).textContent.includes('现场排放')`));
  await click(button('保存为新版本'));
  let saved = await methodAt(2);
  assert.equal(saved.record.reporting_dimensions[0].categories.length, 1);
  assert.equal(saved.record.reporting_dimensions[0].categories[0].name, '现场排放');
  assert.equal(saved.record.rules.length, 1);
  assert.equal(saved.record.rules[0].categories[saved.record.reporting_dimensions[0].id], saved.record.reporting_dimensions[0].categories[0].id);
  report.savedRule = saved.record.rules[0];
  check('Category deletion shows impact and reclassifies the CO2 match before saving immutable v2');
  await cdp.navigate(report.editorUrl);
  await wait(row);
  assert.ok(await cdp.evaluate(`(${row}).textContent.includes('现场排放')`));
  check('Reload reads the saved category and exact flow match');
  await click(button('检查'));
  await click(button('校验该方法版本', `(${modal})`));
  await methodAt(2, 'ready');
  await screenshot('validated');
  await closeModal();
  await click(button('更多'));
  await click(`[...document.querySelectorAll('[role="menuitem"],.arco-menu-item,.arco-dropdown-menu-item')].filter(${visible}).find(e=>e.textContent.trim()==='来源与诊断')`);
  await wait(`(${modal}).textContent.includes('来源与诊断')`);
  await screenshot('source-dialog');
  assert.equal(await cdp.evaluate('document.body.innerText.includes("MODEL_PROCESSING_TEMPLATE_UNBOUND")'), false);
  await closeModal();
  check('Persisted result-category version validates; source dialog does not trigger template-binding failure');
  // Batch actions stay visible and disabled until a flow is selected.
  assert.equal(await cdp.evaluate('document.querySelector(".tag-scheme__batch button").disabled'), true);
  await click(`[...document.querySelectorAll('.tag-scheme tbody .arco-checkbox')].filter(${visible})[0]`);
  await wait(`document.querySelector('.calculation-method-rules__batch')?.textContent.includes('已选 1 条')`);
  await click(button('取消选择'));
  await wait(`document.querySelector('.tag-scheme__batch button').disabled`);
  check('Persistent batch assignment explains selection and disables empty actions');

  for (const [name, width, height, deviceScaleFactor] of viewports) {
    await cdp.setViewport({ width, height, deviceScaleFactor }); await sleep(180);
    await cdp.evaluate('window.scrollTo(0,0)');
    await screenshot(`editor-${name}`);
    const layout = await cdp.evaluate(`(() => {
      const table=document.querySelector('.tag-scheme .arco-table,.tag-scheme .method-scope__cards');
      const rect=table?.getBoundingClientRect();
      const rows=[...document.querySelectorAll('.tag-scheme tbody tr.arco-table-tr,.tag-scheme .method-scope__card')];
      return {width:innerWidth,height:innerHeight,scrollWidth:document.documentElement.scrollWidth,
        tableTop:rect?.top, workspaceTop:document.querySelector('.calculation-method-editor')?.getBoundingClientRect().top,
        visibleRows:rows.filter(e=>{const r=e.getBoundingClientRect();return r.top>=0&&r.bottom<=innerHeight&&r.height>0;}).length,
        availableContentFraction:rect?Math.max(0,innerHeight-rect.top)/innerHeight:0};})()`);
    report.layouts.push({ name, ...layout });
  }
  report.layoutFailures = [];
  for (const { name, width, ...layout } of report.layouts) {
    if (layout.scrollWidth > width + 1) report.layoutFailures.push(`${name} body overflow`);
    if (width >= 1280) {
      if (layout.visibleRows < 6) report.layoutFailures.push(`${name}: fewer than 6 visible flow rows`);
      if (layout.availableContentFraction < 0.65) report.layoutFailures.push(`${name}: flows occupy <65% of viewport`);
    }
  }
  check('Four viewport screenshots captured and layout requirements measured');
  const secondEmission = `[...document.querySelectorAll('.tag-scheme .method-scope__card')].find(e=>e.textContent.includes('二氧化碳')&&e.querySelector('[aria-label="结果分类"]')?.textContent.includes('无'))`;
  await option(`(${secondEmission}).querySelector('[aria-label="结果分类"]')`, '现场排放');
  await click(button('保存为新版本'));
  saved = await methodAt(3);
  assert.equal(saved.record.rules.length, 2);
  assert.equal(new Set(saved.record.rules.map(rule => rule.exchange_id)).size, 2);
  await click(button('检查'));
  await click(button('校验该方法版本', `(${modal})`));
  await methodAt(3, 'ready');
  await closeModal();
  await screenshot('mobile-saved');
  await click(`[...document.querySelectorAll('button')].filter(${visible}).find(e=>e.textContent.replace('‹','').trim()==='返回结果分类')`);
  await wait(`!location.search.includes('method=')`);
  check('At 390px a second exact CO2 flow is assigned, saved, checked, and the compact back control returned to the template');
  await cdp.setViewport({ width: 1440, height: 900 });
  await click(button('保存为我的模板'));
  await fill('document.querySelector("#template-save-name")', templateName);
  await wait(`document.querySelector('.template-save-dialog').textContent.includes(${JSON.stringify(name)})`);
  await click(button('保存模板', `(${modal})`));
  await wait(`!document.querySelector('#template-save-name')`);
  const templates = (await get('/api/v1/project-templates')).items;
  const mine = templates.find(item => item.title === templateName);
  assert.ok(mine, 'UI save did not create the template');
  report.savedTemplate = mine;
  const frozen = await get(`/api/v1/project-templates/${mine.id}/accounting-methods`);
  const scheme = frozen.methods.find(item => item.user_method?.method_id === report.methodId);
  assert.equal(scheme?.user_method?.semantics, 'result_category.v1');
  check('Save as my template freezes the checked result-category caliber using the UI');
  await cdp.navigate(`${base}/templates`);
  const card = `[...document.querySelectorAll('.template-library-card')].find(e=>e.textContent.includes(${JSON.stringify(templateName)}))`;
  await wait(card);
  await click(button('新建项目', `(${card})`));
  await fill('document.querySelector("#project-name")', projectName);
  await click(button('创建项目，填写数据', `(${modal})`));
  await wait('location.pathname.includes("/workbench")');
  report.projectUrl = await cdp.evaluate('location.href');
  report.projectId = report.projectUrl.match(/applications\/([^/?]+)/)[1];
  const inherited = (await get(`/api/v1/applications/${report.projectId}/calculation-methods`)).find(item => item.origin_method_id === report.methodId);
  assert.ok(inherited && inherited.id !== report.methodId);
  const inheritedVersion = await get(`/api/v1/calculation-methods/${inherited.id}/versions/1`);
  assert.equal(inheritedVersion.semantics, 'result_category.v1');
  assert.deepEqual(inheritedVersion.rules, saved.record.rules);
  report.inheritedMethod = inherited;
  await screenshot('created-project');
  check('UI-created project inherits independent result-category rules and exact semantics');
  assert.ok(report.projectUrl.includes('revision='), 'Created project did not land on a saved revision');
  const firstRevision = new URL(report.projectUrl).searchParams.get('revision');
  await wait(`document.querySelector('.project-data-form input[aria-label*=" / "]:not([disabled])')`);
  const field = await cdp.evaluate(`(() => {
    const e=document.querySelector('.project-data-form input[aria-label*=" / "]:not([disabled])');
    return e ? {label:e.getAttribute('aria-label'), value:Number(e.value)} : null;
  })()`);
  assert.ok(field && field.label, 'No editable production field on the new project');
  await fill(`document.querySelector('[aria-label=${JSON.stringify(field.label)}]')`, String((Number.isFinite(field.value) ? field.value : 0) + 1));
  await click(button('保存项目'));
  await wait(`new URLSearchParams(location.search).get('revision')!==${JSON.stringify(firstRevision)}`, 60000);
  report.changedRevision = await cdp.evaluate(`new URLSearchParams(location.search).get('revision')`);
  const reinherited = (await get(`/api/v1/applications/${report.projectId}/calculation-methods?model_revision_id=${report.changedRevision}`)).find(item => item.origin_method_id === inherited.id);
  assert.ok(reinherited && reinherited.id !== inherited.id, 'Input change did not carry the scheme to the next revision');
  const reinheritedVersion = await get(`/api/v1/calculation-methods/${reinherited.id}/versions/1`);
  assert.equal(reinheritedVersion.semantics, 'result_category.v1');
  assert.deepEqual(reinheritedVersion.rules, saved.record.rules);
  report.reinheritedMethod = reinherited;
  await screenshot('changed-input');
  check('Changing production data creates the next revision and re-inherits the same result-category rules');
  assert.deepEqual(report.httpErrors, []);
  assert.deepEqual(report.consoleErrors, []);
  assert.deepEqual(cdp.anomalies, []);
  assert.deepEqual(report.layoutFailures, [], 'Desktop six-row / 65% content budget and viewport overflow requirements');
  report.passed = true;
} catch (error) {
  report.passed = false; report.error = error.stack;
  try { report.pageText = await cdp.evaluate('document.body.innerText'); await screenshot('failed'); } catch {}
} finally {
  report.finishedAt = new Date().toISOString();
  cdp?.close(); chrome?.child.kill();
  writeFileSync(`${out}/summary.json`, JSON.stringify(report, null, 2));
}
console.log(JSON.stringify({ passed: report.passed, checks: report.checks.length, error: report.error, out }));
process.exitCode = report.passed ? 0 : 1;
