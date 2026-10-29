import assert from 'node:assert/strict';
import { mkdirSync, writeFileSync } from 'node:fs';
import { launchChrome, Cdp, sleep } from './browser/cdp.mjs';
const [base, out] = process.argv.slice(2);
mkdirSync(out, {recursive:true});
async function api(route, body) {
  const r=await fetch(`${base}/api/v1${route}`,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{});
  assert.ok(r.ok,await r.clone().text());return r.json();
}
const seed=(await api('/project-templates')).items.find(t=>t.seed_id==='nebula.iron-steel.bf-bof-crude-steel');
const head=(await api(`/project-templates/${seed.id}/accounting-methods`)).template;
const method=await api(`/applications/${head.source_application_id}/calculation-methods`,{
  name:`Inline ${Date.now()}`,purpose:'custom',model_revision_id:head.source_revision_id,
  semantics:'result_category.v1',rules:[],reporting_dimensions:[{id:'category',name:'分类',categories:[{id:'direct',name:'现场排放',is_leaf:true}]}]});
const chrome=await launchChrome({port:19486});const cdp=new Cdp(chrome.wsUrl);await cdp.ready;await cdp.newTab();
const report={layouts:[]};
try {
  await cdp.setViewport({width:1440,height:900});
  await cdp.navigate(`${base}/templates/${seed.id}/config?tab=methods&method=${method.method.id}`);
  await sleep(1000);
  async function click(selector){const p=await cdp.evaluate(`(()=>{const e=document.querySelector(${JSON.stringify(selector)});const r=e.getBoundingClientRect();return{x:r.x+r.width/2,y:r.y+r.height/2}})()`);for(const type of ['mousePressed','mouseReleased'])await cdp.send('Input.dispatchMouseEvent',{type,...p,button:'left',clickCount:1},cdp.sessionId);await sleep(250);}
  assert.equal(await cdp.evaluate(`document.body.innerText.includes('顶级分类')`),false);
  assert.ok(await cdp.evaluate(`!!document.querySelector('.tag-scheme__category-inline input')`));
  assert.ok(await cdp.evaluate(`document.querySelector('.tag-scheme__batch button').disabled`));
  await click('.tag-scheme tbody input[type=checkbox]');
  assert.equal(await cdp.evaluate(`document.querySelector('.tag-scheme__batch button').disabled`),false);
  assert.ok(await cdp.evaluate(`document.body.innerText.includes('焦粉燃烧')&&document.body.innerText.includes('碳酸盐分解')`));
  for(const [width,height] of [[1440,900],[1280,800],[853,533],[390,844]]){
    await cdp.setViewport({width,height});await sleep(250);
    const layout=await cdp.evaluate(`(()=>{const root=document.scrollingElement;const b=document.querySelector('.tag-scheme__batch').getBoundingClientRect();return {height:innerHeight,scroll:root.scrollHeight,client:root.clientHeight,bottom:b.bottom,top:b.top,width:root.scrollWidth}})()`);
    report.layouts.push({width,...layout});
    await cdp.screenshot(`${out}/editor-${width}.png`);
    assert.ok(layout.scroll<=layout.client+1,JSON.stringify(layout));
    assert.ok(layout.width<=width+1,JSON.stringify(layout));
    assert.ok(layout.bottom<=height+1&&layout.top>=0,JSON.stringify(layout));
  }
  report.passed=true;
}catch(e){report.error=e.stack;process.exitCode=1;}finally{writeFileSync(`${out}/summary.json`,JSON.stringify(report,null,2));cdp.close();chrome.child.kill();}
console.log(JSON.stringify(report));
