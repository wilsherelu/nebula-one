import {launchChrome,Cdp,sleep} from './browser/cdp.mjs';
import {readFileSync,writeFileSync,mkdirSync} from 'node:fs';
import {join} from 'node:path';
const fixture=JSON.parse(readFileSync(process.argv[2],'utf8')),out=process.argv[3];mkdirSync(out,{recursive:true});
const launched=await launchChrome({port:9363}),cdp=new Cdp(launched.wsUrl);await cdp.ready;await cdp.newTab();
await cdp.setViewport({width:1440,height:900});const checks=[];
function check(name,ok,detail){checks.push({name,pass:!!ok,detail});if(!ok)throw Error(name);}
async function wait(expr){for(let i=0;i<150;i++){if(await cdp.evaluate(`!!(${expr})`))return;await sleep(200);}throw Error('wait: '+expr);}
async function click(expr){await wait(expr);await cdp.evaluate(`(${expr}).scrollIntoView({block:'center'})`);await sleep(100);const r=await cdp.evaluate(`(()=>{const r=(${expr}).getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()`);
for(const type of ['mouseMoved','mousePressed','mouseReleased'])await cdp.send('Input.dispatchMouseEvent',{type,x:r.x,y:r.y,button:'left',clickCount:1},cdp.sessionId);}
const open=`[...document.querySelectorAll('.sankey-viewer button')].find(b=>b.textContent.includes('打开全图'))`;
try{
await cdp.navigate(`${fixture.base}/applications/${fixture.app}/results?snapshot=${fixture.mfa}&view=mfa`);
await wait('document.querySelector(".sankey-viewer__viewport img")?.naturalWidth>0');
check('real_mfa_chart_loaded',true);await click(open);await wait('document.querySelector(".sankey-fullscreen__exit")');
await cdp.send('Input.dispatchMouseEvent',{type:'mouseWheel',x:800,y:650,deltaX:1000,deltaY:1600},cdp.sessionId);await sleep(200);
const visible=await cdp.evaluate('(()=>{const r=document.querySelector(".sankey-fullscreen__exit").getBoundingClientRect();return r.top>=0&&r.bottom<=innerHeight&&r.left>=0&&r.right<=innerWidth})()');
check('floating_exit_visible_after_scroll',visible);await cdp.screenshot(join(out,'mfa-fullscreen.png'));
await click('document.querySelector(".sankey-fullscreen__exit")');await wait('!document.querySelector(".sankey-fullscreen")');check('floating_exit_closes_fullscreen',true);
await click(open);await wait('document.querySelector(".sankey-fullscreen")');
for(const type of ['keyDown','keyUp'])await cdp.send('Input.dispatchKeyEvent',{type,key:'Escape',code:'Escape',windowsVirtualKeyCode:27,nativeVirtualKeyCode:27},cdp.sessionId);
await wait('!document.querySelector(".sankey-fullscreen")');check('native_escape_closes_fullscreen',true);
await cdp.navigate(`${fixture.base}/applications/${fixture.app}/results?snapshot=${fixture.cbam}&view=cbam`);
await wait('document.querySelector(".result-tabs__panel .cbam-result .frozen-report")');await sleep(2500);
await cdp.evaluate('window.__stableSamples=[]');
for(let i=0;i<60;i++){
  const sample=await cdp.evaluate('(()=>{const p=document.querySelector(".result-tabs__panel"),tabs=document.querySelector(".result-tabs__list");return {tabs:!!tabs,text:p?.innerText?.replace(/\\s+/g," ").trim()??null,height:p?.getBoundingClientRect().height}})()');
  await cdp.evaluate(`window.__stableSamples.push(${JSON.stringify(sample)})`);await sleep(500);
}
const samples=await cdp.evaluate('window.__stableSamples');
check('cbam_navigation_mode_stays_stable_30_seconds',samples.every(s=>s.tabs===samples[0].tabs),{singleTask:!samples[0].tabs});
check('cbam_panel_content_and_height_stable',samples.every(s=>s.text===samples[0].text&&s.height===samples[0].height)&&samples[0].text?.length>100,samples);
await cdp.screenshot(join(out,'cbam-stable.png'));check('no_console_errors',cdp.consoleErrors().length===0,cdp.consoleErrors());
}catch(error){checks.push({name:'journey',pass:false,error:String(error)});await cdp.screenshot(join(out,'failure.png')).catch(()=>{});writeFileSync(join(out,'failure-dom.txt'),await cdp.evaluate('document.body.innerText'));
writeFileSync(join(out,'failure-state.json'),JSON.stringify(await cdp.evaluate(`(async()=>({url:location.href,snapshots:await fetch('/api/v1/applications/${fixture.app}/solved-system-snapshots').then(r=>r.json())}))()`),null,2));}
finally{writeFileSync(join(out,'result-stability.json'),JSON.stringify({fixture,checks},null,2));cdp.close();launched.child.kill();}
console.log(JSON.stringify({pass:checks.filter(c=>c.pass).length,fail:checks.filter(c=>!c.pass)}));process.exitCode=checks.some(c=>!c.pass)?1:0;
