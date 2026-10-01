// Run with Electron as the entry script. This exercises the actual main/preload IPC.
const { app, BrowserWindow } = require('electron');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
let tested = false;
const reportPath = process.env.NEBULA_ONE_DESKTOP_WINDOW_REPORT;
if (!reportPath || !process.env.NEBULA_ONE_DESKTOP_TEST_DATA) throw new Error('Isolated test data and report paths required');

app.on('browser-window-created', (_event, main) => {
  if (tested) return;
  tested = true;
  main.webContents.once('did-finish-load', async () => {
    try {
      const originalUrl = main.webContents.getURL();
      const oneOrigin = new URL(originalUrl).origin;
      async function call(origin, route, payload) {
        const response = await fetch(origin + route, payload ? {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)} : {});
        const result = await response.json();
        if (!response.ok) throw new Error(JSON.stringify(result));
        return result;
      }
      const template = (await call(oneOrigin, '/api/v1/project-templates')).items.find(item => item.seed_id);
      const handoff = await call(oneOrigin, '/api/v1/modeling/handoffs', {
        name:'Desktop window modelling acceptance', base_model_id:template.source_model_id, base_revision_id:template.source_revision_id});
      const opened = await main.webContents.executeJavaScript(`(async () => {
        const handoff = ${JSON.stringify(handoff)};
        sessionStorage.setItem('nebula-one:modeling:' + handoff.handoff_id, JSON.stringify({state:handoff.state,confirmation_token:handoff.confirmation_token}));
        return window.__NEBULA_ONE_DESKTOP__.openEditor({url:handoff.editor_url,handoff_id:handoff.handoff_id,state:handoff.state,confirmation_token:handoff.confirmation_token});
      })()`);
      assert.equal(opened, true);
      assert.equal(main.webContents.getURL(), originalUrl);
      const editor = BrowserWindow.getAllWindows().find(window => window.id !== main.id);
      assert.ok(editor);
      const editorUrl = new URL(handoff.editor_url);
      assert.equal(editor.webContents.getURL(), handoff.editor_url);
      assert.ok(await editor.webContents.executeJavaScript('document.getElementById("root")?.childElementCount > 0'),
        'Deep editor route must mount the renderer before handoff acceptance');
      assert.equal(await editor.webContents.executeJavaScript('window.__NEBULA_DESKTOP__.oneOrigin'), oneOrigin);
      const projectId = editorUrl.pathname.split('/').pop();
      const baseVersion = Number(editorUrl.searchParams.get('version'));
      const current = await call(editorUrl.origin, `/api/projects/${projectId}/versions/${baseVersion}`);
      current.graph.nodes[0].name += ' (desktop acceptance)';
      const saved = await call(editorUrl.origin, `/api/projects/${projectId}/versions`, {graph:current.graph});
      assert.ok(saved.version > baseVersion);
      const candidate = {state:handoff.state, confirmation_token:handoff.confirmation_token,
        project_id:projectId, base_version:baseVersion, saved_version:saved.version, upstream_graph_hash:saved.graph_hash};
      const returning = new URL('/modeling/return', oneOrigin);
      for (const [key,value] of Object.entries({...candidate, handoff_id:handoff.handoff_id, status:'saved'})) {
        if (key !== 'confirmation_token') returning.searchParams.set(key,String(value));
      }
      await editor.loadURL(returning.toString());
      const credentials = await editor.webContents.executeJavaScript(`JSON.parse(sessionStorage.getItem(${JSON.stringify('nebula-one:modeling:'+handoff.handoff_id)}))`);
      assert.equal(credentials.state, handoff.state);
      assert.equal(credentials.confirmation_token, handoff.confirmation_token);
      const preview = await call(oneOrigin, `/api/v1/modeling/handoffs/${handoff.handoff_id}/preview`, candidate);
      assert.equal(preview.version, saved.version);
      const confirmed = await call(oneOrigin, `/api/v1/modeling/handoffs/${handoff.handoff_id}/confirm`, candidate);
      assert.ok(confirmed.application_id && confirmed.revision_id);
      assert.equal(main.webContents.getURL(), originalUrl);
      const preferences = editor.webContents.getLastWebPreferences();
      assert.equal(preferences.nodeIntegration, false);
      assert.equal(preferences.contextIsolation, true);
      assert.equal(preferences.sandbox, true);
      fs.writeFileSync(reportPath, JSON.stringify({status:'passed', main_preserved:true,
        separate_window:true, session_preserved:true, saved_version:saved.version, confirmed, preferences}, null, 2));
      app.quit();
    } catch (error) {
      fs.writeFileSync(reportPath, JSON.stringify({status:'failed', error:error.stack}, null, 2));
      process.exitCode = 1;
      app.quit();
    }
  });
});
require('../main.cjs');
