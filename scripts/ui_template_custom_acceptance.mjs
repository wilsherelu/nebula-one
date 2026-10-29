import {mkdirSync, writeFileSync} from 'node:fs';
import assert from 'node:assert/strict';
import {launchChrome, Cdp, sleep} from './browser/cdp.mjs';

const [base, port, out] = process.argv.slice(2);
mkdirSync(out, {recursive: true});
const report = {checks: [], screenshots: []};
let chrome, cdp;
async function wait(expr) {
  for (let i = 0; i < 80; i++) {
    if (await cdp.evaluate(`!!(${expr})`)) return;
    await sleep(150);
  }
  throw new Error(`Not ready: ${expr}`);
}
async function click(expr) {
  await cdp.evaluate(`(${expr})?.scrollIntoView({block:'center',inline:'nearest'})`);
  await sleep(150);
  const box = await cdp.evaluate(`(() => {const e=${expr};if(!e)return null;const r=e.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2,w:r.width,h:r.height}})()`);
  assert.ok(box?.w && box?.h, `Control is not visible: ${expr}`);
  for (const type of ['mousePressed', 'mouseReleased']) await cdp.send('Input.dispatchMouseEvent', {x:box.x,y:box.y,type,button:'left',clickCount:1}, cdp.sessionId);
  await sleep(200);
}
const button = text => `[...document.querySelectorAll('button')].find(b=>b.textContent.trim()===${JSON.stringify(text)})`;
const row = `[...document.querySelectorAll('.method-scope__detail tr')].find(r=>r.textContent.includes('二氧化碳') && r.querySelector('[aria-label="是否计入"]'))`;
async function option(expr, text) {
  await click(expr);
  const target = `[...document.querySelectorAll('.arco-select-popup .arco-select-option')].find(e=>e.textContent.trim()===${JSON.stringify(text)})`;
  await wait(target); await click(target);
}
async function shot(name) {report.screenshots.push(await cdp.screenshot(`${out}/${name}.png`));}
try {
  chrome = await launchChrome({port:Number(port)});
  cdp = new Cdp(chrome.wsUrl); await cdp.ready; await cdp.newTab();
  await cdp.setViewport({width:1440,height:900});
  await cdp.navigate(`${base}/templates`);
  await wait(`document.querySelector('.template-library-card')`);
  await click(`[...document.querySelectorAll('.template-library-card button')].find(b=>b.textContent.trim()==='配置模板')`);
  await wait(`document.querySelector('.template-task-row')`);
  const listUrl = await cdp.evaluate('location.href');
  for (const [name,width,height,deviceScaleFactor] of [['1440',1440,900,1],['1280',1280,800,1],['150pct',853,533,1.5],['390',390,844,1]]) {
    await cdp.setViewport({width,height,deviceScaleFactor}); await sleep(200); await shot(`list-${name}`);
  }
  await cdp.setViewport({width:1440,height:900});
  await click(button('新建方案')); await wait(`document.querySelector('.arco-modal input')`);
  await click(`document.querySelector('.arco-modal input')`);
  await cdp.send('Input.insertText',{text:`逐流自定义验收 ${Date.now()}`},cdp.sessionId);
  await click(button('创建并编辑'));
  await wait(`document.querySelector('.method-scope__process-list')`);
  assert.equal(await cdp.evaluate(`document.body.innerText.includes('PROJECT_TEMPLATE_UNAVAILABLE')`),false);
  const method = await cdp.evaluate(`new URLSearchParams(location.search).get('method')`);
  const editorUrl = await cdp.evaluate('location.href');
  const detail = await (await fetch(`${base}/api/v1/calculation-methods/${method}`)).json();
  const worksheet = await fetch(`${base}/api/v1/applications/${detail.method.application_id}/workspace/${detail.method.model_revision_id}`);
  report.sourceWorksheetStatus = worksheet.status;
  report.checks.push('New custom method opens its real process/flow editor');
  await wait(row);
  await option(`(${row}).querySelector('[aria-label="是否计入"]')`, '计入');
  await option(`(${row}).querySelector('[aria-label="结果分类"]')`, '范围1');
  await click(`(${row}).querySelector('summary')`);
  await option(`(${row}).querySelector('[aria-label="位置角色"]')`, '场内过程');
  await click(`(${row}).querySelector('summary')`);
  await click(button('保存为新版本'));
  let saved;
  for (let i=0;i<60;i++) {
    saved=await (await fetch(`${base}/api/v1/calculation-methods/${method}`)).json();
    if (saved.latest_version===2) break;
    await sleep(150);
  }
  assert.equal(saved.latest_version,2);
  const changed=saved.versions.find(v=>v.version===2).rules;
  assert.ok(changed.some(r=>r.boundary_status==='selected'&&r.scope==='scope_1'&&r.exchange_id));
  report.method = method; report.savedRules = changed;
  report.checks.push('Per-flow inclusion and Scope saved on immutable v2');
  await cdp.navigate(editorUrl); await wait(row);
  assert.ok(await cdp.evaluate(`(${row}).textContent.includes('计入') && (${row}).textContent.includes('范围1')`));
  report.checks.push('Reload preserves inclusion and classification');
  for (const [name,width,height,deviceScaleFactor] of [['1440',1440,900,1],['1280',1280,800,1],['150pct',853,533,1.5],['390',390,844,1]]) {
    await cdp.setViewport({width,height,deviceScaleFactor}); await sleep(250); await shot(`editor-${name}`);
    assert.ok(await cdp.evaluate('document.documentElement.scrollWidth<=innerWidth+1'));
    assert.ok(await cdp.evaluate(`document.querySelector('.project-workspace-header').getBoundingClientRect().bottom <= document.querySelector('.calculation-method-editor').getBoundingClientRect().top`), 'Template heading overlaps the editor');
  }
  report.checks.push('Both views captured at four viewports; editor has no body overflow');
  report.consoleErrors=cdp.consoleErrors(); assert.equal(report.consoleErrors.length,0);
  report.listUrl=listUrl; report.passed=true;
} catch(error) {report.passed=false;report.error=error.stack;try{await shot('failed');}catch{}}
finally {cdp?.close();chrome?.child.kill();writeFileSync(`${out}/summary.json`,JSON.stringify(report,null,2));}
console.log(JSON.stringify({passed:report.passed,checks:report.checks,error:report.error}));
process.exitCode=report.passed?0:1;
