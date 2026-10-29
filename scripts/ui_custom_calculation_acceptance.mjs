// Continue the UI-created custom template/project with an actual UI solve and receipt comparison.
import assert from 'node:assert/strict';
import {readFileSync,mkdirSync,writeFileSync} from 'node:fs';
import {launchChrome,Cdp,sleep} from './browser/cdp.mjs';
const [base,source,out]=process.argv.slice(2), prior=JSON.parse(readFileSync(source,'utf8'));
assert.ok(prior.passed);mkdirSync(out,{recursive:true});
const chrome=await launchChrome({port:19490}),cdp=new Cdp(chrome.wsUrl);await cdp.ready;await cdp.newTab();
const report={source,checks:[]};
async function get(route){const r=await fetch(`${base}/api/v1${route}`);assert.ok(r.ok,await r.clone().text());return r.json();}
async function wait(expr){for(let i=0;i<400;i++){if(await cdp.evaluate(`!!(${expr})`))return;await sleep(150);}throw Error(`Timeout ${expr}`);}
async function click(text){const expr=`[...document.querySelectorAll('button')].find(e=>e.textContent.trim()===${JSON.stringify(text)}&&e.getBoundingClientRect().height>0)`;await wait(expr);const p=await cdp.evaluate(`(()=>{const e=${expr};e.scrollIntoView({block:'nearest'});const r=e.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()`);for(const type of ['mousePressed','mouseReleased'])await cdp.send('Input.dispatchMouseEvent',{type,...p,button:'left',clickCount:1},cdp.sessionId);await sleep(250);}
try{
  await cdp.setViewport({width:1440,height:900});
  const app=prior.projectId,rev=prior.changedRevision,mid=prior.reinheritedMethod.id;
  await cdp.navigate(`${base}/applications/${app}/calculation-methods?revision=${rev}&method=${mid}`);
  await click('检查');await click('校验该方法版本');
  await wait(`document.body.innerText.includes('检查通过')||document.body.innerText.includes('校验通过')||document.body.innerText.includes('可用')`);
  const version=await get(`/calculation-methods/${mid}/versions/1`);assert.equal(version.status,'ready');
  report.checks.push('UI-created custom method validates on the changed production revision');
  await cdp.navigate(`${base}/applications/${app}/workbench?revision=${rev}`);
  await click('核算');await wait(`document.querySelector('.calculation-method-dialog')`);
  assert.ok(await cdp.evaluate(`document.querySelector('.calculation-method-dialog').innerText.includes('产品碳足迹')`));
  await click('开始计算');await wait(`location.pathname.endsWith('/results')`);
  await wait(`document.querySelector('.tag-result__scheme')`);
  const snapshots=await get(`/applications/${app}/solved-system-snapshots`);
  const saved=snapshots.find(s=>s.system_revision_id===rev);assert.ok(saved);
  const snapshot=saved;
  const receipt=snapshot.lcia_results.indicator_contribution_receipts.find(r=>r.canonical_indicator_key==='climate change');
  const ids=new Set(version.rules.map(r=>r.exchange_id));assert.equal(ids.size,2);
  const terms=receipt.terms.filter(t=>ids.has(t.exchange_id));assert.equal(terms.length,2);
  for(const term of terms) assert.ok(Math.abs(term.amount*term.cf_value-term.contribution_value)<1e-9);
  const expected=terms.reduce((s,t)=>s+t.contribution_value,0);
  const history=await get(`/applications/${app}/tag-grouping-results?snapshot_id=${saved.id}`);
  const grouped=history.find(r=>r.schemes.some(s=>s.scheme.method_id===mid));assert.ok(grouped);
  const scheme=grouped.schemes.find(s=>s.scheme.method_id===mid);
  assert.ok(Math.abs(scheme.tag_total.value-expected)<1e-9);
  const text=await cdp.evaluate(`document.querySelector('.tag-result__scheme').innerText`);
  assert.ok(text.includes(String(expected)));assert.ok(grouped.reconciled);
  await cdp.screenshot(`${out}/custom-calculated.png`);
  report.checks.push('UI calculation returns a classified subtotal identical to the two exact CO2 receipt terms');
  report.application_id=app;report.revision_id=rev;report.method_id=mid;report.snapshot_id=saved.id;
  report.expected=expected;report.actual=scheme.tag_total.value;report.unit=scheme.tag_total.unit;
  report.terms=terms;report.passed=true;
}catch(e){report.error=e.stack;try{report.page=await cdp.evaluate('document.body.innerText');await cdp.screenshot(`${out}/failed.png`);}catch{}process.exitCode=1;}
finally{writeFileSync(`${out}/summary.json`,JSON.stringify(report,null,2));cdp.close();chrome.child.kill();}
console.log(JSON.stringify(report));
