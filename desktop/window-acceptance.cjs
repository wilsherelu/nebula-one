// Explicit packaged acceptance: actual renderer clicks, IPC, native view identity and persistence.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { BrowserWindow, dialog } = require('electron');
async function until(check, message) {
  for (let i=0; i<120; i++) { if (await check()) return; await new Promise(resolve => setTimeout(resolve, 250)); }
  throw new Error(message);
}
async function accept({app, mainWindow, workspace, runtime}) {
  const report = process.env.NEBULA_ONE_DESKTOP_WINDOW_REPORT;
  const evidence = {packaged:app.isPackaged};
  const one = mainWindow.webContents, editor = workspace.editor.webContents;
  const evaluate = (contents, code) => contents.executeJavaScript(code);
  const click = (contents, selector) => evaluate(contents, `(() => {const element=document.querySelector(${JSON.stringify(selector)}); if(!element) throw new Error('Missing control: '+${JSON.stringify(selector)}); element.click();})()`);
  const button = (contents, text) => evaluate(contents, `(() => {const element=[...document.querySelectorAll('button')].find(item=>item.textContent.trim()===${JSON.stringify(text)}); if(!element) throw new Error('Missing button: '+${JSON.stringify(text)}); element.click();})()`);
  async function call(origin, route, body) {
    const response = await fetch(origin+route, body ? {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)} : {});
    const result = await response.json(); assert.ok(response.ok, JSON.stringify(result)); return result;
  }
  try {
    await until(() => evaluate(one, 'Boolean(document.querySelector("[aria-label=\\"专业建模\\"]"))'), 'One navigation not rendered');
    const applications = await call(runtime.oneOrigin,'/api/v1/applications');
    assert.equal(applications.length,1);
    const demo = applications[0];
    const model = (await call(runtime.oneOrigin,`/api/v1/applications/${demo.id}/system-models`))[0];
    const revisions = await call(runtime.oneOrigin,`/api/v1/system-models/${model.id}/revisions`);
    const revision = revisions.find(item => item.application_context.project_inputs);
    assert.ok(revision);
    await mainWindow.loadURL(`${runtime.oneOrigin}/applications/${demo.id}/workbench?step=data&revision=${revision.id}`);
    await until(() => evaluate(one,'Boolean(document.querySelector("input.arco-input"))'), 'One quantity form not rendered');
    const draft = await evaluate(one, `(() => {const input=[...document.querySelectorAll('input.arco-input')].find(item=>!item.disabled && item.value && Number.isFinite(Number(item.value))); if(!input) throw new Error('No editable quantity'); const original=input.value; const value=String(Number(original)+1); Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input,value); input.dispatchEvent(new Event('input',{bubbles:true})); return {label:input.getAttribute('aria-label'),value,original};})()`);
    const originalUrl = one.getURL();
    await click(one,'[aria-label="专业建模"]');
    await until(() => evaluate(editor,'Boolean(document.querySelector(".pm-stat-value"))'), 'LCA home not mounted');
    await until(() => evaluate(editor,'[...document.querySelectorAll(".pm-stat-value")].every(item=>/^\\d+$/.test(item.textContent.trim()))'), 'LCA statistics not loaded');
    const stats = await call(runtime.editorOrigin,'/api/stats');
    const projects = await call(runtime.editorOrigin,'/api/projects');
    const all = await call(runtime.editorOrigin,'/api/projects?include_resources=true');
    assert.equal(stats.projects,1); assert.equal(projects.total,1);
    assert.ok(all.items.some(item=>item.status==='resource'));
    assert.equal(await evaluate(editor,'Boolean([...document.querySelectorAll("button")].find(item=>item.textContent.trim()==="新建"))'),false);
    assert.equal(BrowserWindow.getAllWindows().length,1);
    assert.equal(one.getURL(),originalUrl);
    await button(editor,'返回 Nebula One');
    await until(()=>!workspace.visible,'Return did not reveal One');
    assert.equal(one.getURL(),originalUrl);
    assert.ok(await evaluate(one,`[...document.querySelectorAll('input')].some(item=>item.value===${JSON.stringify(draft.value)})`));
    await click(one,'[aria-label="专业建模"]');
    assert.equal(BrowserWindow.getAllWindows().length,1);
    evidence.home={stats,visible:projects.items.map(item=>item.project_id),resources:all.items.filter(item=>item.status==='resource').map(item=>item.project_id),draft_retained:true,window_count:1};
    // Four algorithms consume the install-default associations before any handoff writes.
    evidence.snapshots=await require('./four-task-smoke.cjs').accept(runtime.oneOrigin,path.dirname(report),{officialDefaultsOnly:true,resourceDirectory:runtime.resources});
    workspace.showOne();
    await evaluate(one,`(()=>{const input=[...document.querySelectorAll('input')].find(item=>item.value===${JSON.stringify(draft.value)});Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input,${JSON.stringify(draft.original)});input.dispatchEvent(new Event('input',{bubbles:true}));})()`);
    const template=(await call(runtime.oneOrigin,'/api/v1/project-templates')).items.find(item=>item.seed_id);
    const handoff=await call(runtime.oneOrigin,'/api/v1/modeling/handoffs',{name:'Single window acceptance',base_model_id:template.source_model_id,base_revision_id:template.source_revision_id});
    const opened=await evaluate(one,`(async()=>{const handoff=${JSON.stringify(handoff)};sessionStorage.setItem('nebula-one:modeling:'+handoff.handoff_id,JSON.stringify({state:handoff.state,confirmation_token:handoff.confirmation_token}));return window.__NEBULA_ONE_DESKTOP__.openEditor({url:handoff.editor_url,handoff_id:handoff.handoff_id,state:handoff.state,confirmation_token:handoff.confirmation_token});})()`);
    assert.equal(opened,true);
    await until(()=>evaluate(editor,'Boolean(document.querySelector(".lca-node-title-text"))'),'Model canvas not mounted');
    const editorUrl = new URL(editor.getURL());
    const projectId=editorUrl.pathname.split('/').pop();
    const before=await call(runtime.editorOrigin,`/api/projects/${projectId}/latest`);
    await click(editor,'.lca-node-title-text');
    const name='Single window saved process';
    await evaluate(editor,`(()=>{const input=document.querySelector('.lca-node-title input');Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input,${JSON.stringify(name)});input.dispatchEvent(new Event('input',{bubbles:true}));})()`);
    await evaluate(editor,`document.querySelector('.lca-node-title input').dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}))`);
    await until(()=>workspace.dirty,'Editor did not report unsaved model changes');
    const originalDialog=dialog.showMessageBoxSync;
    try {
      dialog.showMessageBoxSync=()=>0;
      assert.equal(await workspace.open(runtime.editorOrigin+'/?from_nebula_one=1'),false);
      assert.equal(editor.getURL(),editorUrl.toString());
    } finally {dialog.showMessageBoxSync=originalDialog;}
    await button(editor,'返回 Nebula One');
    assert.equal(one.getURL(),originalUrl);
    await click(one,'[aria-label="专业建模"]');
    assert.equal(editor.getURL(),editorUrl.toString());
    assert.ok(await evaluate(editor,`[...document.querySelectorAll('.lca-node-title-text')].some(item=>item.textContent===${JSON.stringify(name)})`));
    await button(editor,'保存');
    let saved;
    await until(async()=>{saved=await call(runtime.editorOrigin,`/api/projects/${projectId}/latest`);return saved.version>before.version && saved.graph.nodes.some(item=>item.name===name);},'Saved model did not reread');
    await until(()=>!workspace.dirty,'Saved model still marked unsaved');
    evidence.edit={version:saved.version,graph_hash:saved.graph_hash,process_name:name,draft_retained:true,discard_cancelled:true};
    await until(()=>evaluate(editor,`[...document.querySelectorAll('button')].filter(item=>item.textContent.trim()==='返回 Nebula One').length===2`),'Saved return action unavailable');
    await evaluate(editor,`[...document.querySelectorAll('button')].filter(item=>item.textContent.trim()==='返回 Nebula One').at(-1).click()`);
    await until(()=>evaluate(one,`Boolean([...document.querySelectorAll('button')].find(item=>item.textContent.trim()==='确认版本，创建分析项目'))`),'One exact version confirmation not rendered');
    await button(one,'确认版本，创建分析项目');
    await until(()=>one.getURL().includes('/workbench?model='),'Confirmed model did not enter One');
    evidence.edit.returned_url=one.getURL();
    evidence.edit.session_preserved=true;
    assert.equal(BrowserWindow.getAllWindows().length,1);
    for(const contents of [one,editor]) {
      const preferences=contents.getLastWebPreferences();
      assert.equal(preferences.sandbox,true);assert.equal(preferences.contextIsolation,true);assert.equal(preferences.nodeIntegration,false);
    }
    evidence.status='passed';
  } catch(error) { evidence.status='failed'; evidence.error=error.stack; }
  fs.writeFileSync(report,JSON.stringify(evidence,null,2));
  workspace.dirty=false;
  app.quit();
}
module.exports={accept};
