/** User edits -> exact check/use -> real solve -> organization report and downloads. */
import {launchChrome,Cdp,sleep} from './browser/cdp.mjs';
import {readFileSync,writeFileSync,mkdirSync,readdirSync} from 'node:fs';
import {resolve,join} from 'node:path';
const fixture=JSON.parse(readFileSync(process.argv[2],'utf8'));
const out=resolve(process.argv[3]);mkdirSync(out,{recursive:true});mkdirSync(join(out,'downloads'),{recursive:true});
const base=fixture.base,app=fixture.application_id,rev=fixture.revision_id;
const browser=await launchChrome({port:9361});const cdp=new Cdp(browser.wsUrl);await cdp.ready;await cdp.newTab();
await cdp.setViewport({width:1440,height:900});
await cdp.send('Page.setDownloadBehavior',{behavior:'allow',downloadPath:join(out,'downloads')},cdp.sessionId);
const checks=[],phases={};
function check(name,condition,detail){checks.push({name,pass:!!condition,detail});if(!condition)throw new Error(name+': '+JSON.stringify(detail));}
async function wait(expr,label,seconds=30){const deadline=Date.now()+seconds*1000;while(Date.now()<deadline){if(await cdp.evaluate(`!!(${expr})`))return;await sleep(200);}throw new Error('wait: '+label);}
const text=(selector,value)=>`[...document.querySelectorAll(${JSON.stringify(selector)})].find(e=>e.textContent.trim()===${JSON.stringify(value)})`;
async function click(expr){await wait(expr,expr);await cdp.evaluate(`(${expr}).scrollIntoView({block:'center'})`);await sleep(120);const r=await cdp.evaluate(`(()=>{const r=(${expr}).getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()`);
  for(const type of ['mouseMoved','mousePressed','mouseReleased'])await cdp.send('Input.dispatchMouseEvent',{type,x:r.x,y:r.y,button:'left',clickCount:1},cdp.sessionId);await sleep(180);}
async function choose(expr,value){await click(expr);const option=text('.arco-select-popup .arco-select-option',value);await click(option);}
async function get(path){return cdp.evaluate(`fetch(${JSON.stringify('/api/v1'+path)}).then(async r=>{if(!r.ok)throw Error(await r.text());return r.json()})`);}
async function editor(){await cdp.navigate(`${base}/applications/${app}/calculation-methods?model=${fixture.model_id}&revision=${rev}&method=${fixture.method_id}`);await wait('document.querySelector(".calculation-method-editor")','method editor');}
const materialRow=`[...document.querySelectorAll('.method-scope .arco-table-tr')].find(r=>/铁矿石|Iron ore|iron ore/.test(r.textContent))`;
async function save(){const before=await get(`/calculation-methods/${fixture.method_id}`);await click(text('button','保存为新版本'));
  const until=Date.now()+15000;while(Date.now()<until){const after=await get(`/calculation-methods/${fixture.method_id}`);if(after.latest_version>before.latest_version){check('immutable_new_version',true,{before:before.latest_version,after:after.latest_version});return;}await sleep(200);}throw Error('new version was not saved');}
async function calculate(label){await cdp.navigate(`${base}/applications/${app}/workbench?revision=${rev}`);await click(text('button','核算'));
  await click(text('.calculation-method-choices strong','组织碳核算'));
  await choose('document.querySelector("#calc-user-method")',fixture.method_name);
  const detail=await get(`/calculation-methods/${fixture.method_id}`);
  const latest=detail.versions.find(v=>v.version===detail.latest_version);
  await choose('document.querySelector("#calc-method-version")',`方法版本 ${latest.version} · ${latest.status==='ready'?'可用':'草稿'}`);
  await click(text('button','检查并使用'));await wait('document.querySelector(".calculation-method-dialog__effective")','exact method ready');
  await click(text('button','开始计算'));await wait('location.pathname.endsWith("/organization") && new URLSearchParams(location.search).has("record")','organization persisted',60);
  await wait('document.querySelector(".frozen-report")','nonempty organization result');
  const record=await cdp.evaluate('new URLSearchParams(location.search).get("record")');
  const report=await get(`/applications/${app}/organization-lifecycle-inventories/${record}/report-data`);
  const org=await get(`/applications/${app}/organization-lifecycle-inventories/${record}`);
  const summary=Object.fromEntries(report.summary.map(row=>[row.group,row.value]));
  const body=await cdp.evaluate('document.querySelector(".frozen-report").innerText');
  check(label+'_screen_has_nonempty_scope_results',body.includes('厂内直接排放')&&body.includes('用户排除'),body.slice(0,220));
  check(label+'_frozen_method',report.user_method.method_id===fixture.method_id&&report.sources.result.content_sha256===org.content_sha256,report.user_method);
  await cdp.screenshot(join(out,label+'.png'));phases[label]={record,summary,report,org};return phases[label];}
const near=(a,b)=>a!=null&&Math.abs(a-b)<=1e-7;
try{
  const included=await calculate('included');
  for(const [scope,key] of [['scope_1','on_site_direct'],['scope_2','purchased_energy_lifecycle'],['scope_3','other_value_chain']])check('included_'+scope,near(included.summary[key],fixture.expected[scope]),included.summary);
  await editor();await wait(materialRow,'material rule');await choose(`(${materialRow}).querySelector('[aria-label="边界归属"]')`,'已排除');await save();
  const excluded=await calculate('excluded');
  check('excluded_supplier_preserved',excluded.org.result.base_accounting.groups.other_value_chain.value===included.org.result.base_accounting.groups.other_value_chain.value,excluded.org.result.base_accounting);
  check('excluded_scope3_moves_to_detail',excluded.summary.other_value_chain===null&&near(excluded.summary.user_excluded,fixture.expected.scope_3),excluded.summary);
  check('exclusion_only_changes_scope3',near(excluded.summary.on_site_direct,included.summary.on_site_direct)&&near(excluded.summary.purchased_energy_lifecycle,included.summary.purchased_energy_lifecycle),excluded.summary);
  check('known_model_total_preserved',near(excluded.report.user_rule_totals.known_model,included.report.user_rule_totals.known_model),excluded.report.user_rule_totals);
  await editor();await choose(`(${materialRow}).querySelector('[aria-label="边界归属"]')`,'已纳入');
  await click(text('.arco-tabs-header-title','结果归集'));await choose(`(${materialRow}).querySelector('[aria-label="供应链分组"]')`,'材料组 B');await save();
  const regrouped=await calculate('regrouped');
  const cats=Object.fromEntries(regrouped.report.custom_dimensions[0].categories.map(c=>[c.id,c.subtotal]));
  check('custom_group_moves_supplier_contribution',near(cats.line_b,fixture.expected.scope_3)&&near(cats.line_a,fixture.expected.scope_1+fixture.expected.scope_2),cats);
  const customText=await cdp.evaluate('document.querySelector(".frozen-report__dimension").innerText');
  check('custom_group_visible_on_screen',customText.includes('材料组 B')&&customText.includes('19,340.2'),customText);
  check('regroup_preserves_counted_total',near(included.report.user_rule_totals.counted,regrouped.report.user_rule_totals.counted),regrouped.report.user_rule_totals);
  check('distinct_frozen_snapshots',new Set(Object.values(phases).map(p=>p.org.solved_snapshot_id)).size===3,Object.values(phases).map(p=>p.org.solved_snapshot_id));
  const replayed=await calculate('replayed');
  check('repeat_check_and_solve_reuses_frozen_record',replayed.org.solved_snapshot_id===regrouped.org.solved_snapshot_id&&replayed.org.content_sha256===regrouped.org.content_sha256,
    {original:regrouped.org.solved_snapshot_id,replayed:replayed.org.solved_snapshot_id});
  for(const menu of ['Excel 明细','下载 HTML 报告']){await click(text('button','更多'));await click(text('.arco-menu-item',menu));await sleep(1000);}
  for(let attempt=0;attempt<50;attempt++){const f=readdirSync(join(out,'downloads'));if(f.some(x=>x.endsWith('.xlsx'))&&f.some(x=>x.endsWith('.html')))break;await sleep(200);}
  const files=readdirSync(join(out,'downloads'));check('exports_downloaded',files.some(f=>f.endsWith('.xlsx'))&&files.some(f=>f.endsWith('.html')),files);
  const before=await cdp.evaluate('document.querySelector(".frozen-report").innerText');await sleep(3000);
  check('result_idle_stable',before===await cdp.evaluate('document.querySelector(".frozen-report").innerText'));
  check('no_browser_errors',cdp.consoleErrors().length===0,cdp.consoleErrors());
}catch(error){writeFileSync(join(out,'failure-dom.txt'),await cdp.evaluate('document.body.innerText').catch(()=>''));await cdp.screenshot(join(out,'failure.png')).catch(()=>{});checks.push({name:'journey',pass:false,error:String(error)});}
finally{writeFileSync(join(out,'scope3-ui-summary.json'),JSON.stringify({checks,phases},null,2));await cdp.close();browser.child.kill();}
console.log(JSON.stringify({passed:checks.filter(c=>c.pass).length,failed:checks.filter(c=>!c.pass)}));process.exitCode=checks.some(c=>!c.pass)?1:0;
