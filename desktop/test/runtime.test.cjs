const { test } = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { availablePort, editorServer } = require('../runtime.cjs');
const { ownedUrl, validateHandoff } = require('../security.cjs');

test('desktop validates accounting release separately from structural model', () => {
  const { matchesTemplateRelease } = require('../runtime.cjs');
  const { createHash } = require('node:crypto');
  // Fixture keys are written in recursive sorted order so JSON.stringify reproduces the runtime
  // serializer's canonical hash independently. The library carries a task declaration exactly as the
  // seeded steel-1.1.7 release does, and the backend always exposes `tasks` on accounting_library.
  const library = {id:'library', methods:[], schema_version:'nebula_one.template-method-library.v1',
    tasks:[{default_ref:'pcf@1.0.3', refs:['pcf@1.0.3'], role:'complete_model'}],
    template_profile:{content_sha256:'a'.repeat(64), id:'steel', version:'1.1.4'}, version:'1.1.7'};
  const hash = createHash('sha256').update(JSON.stringify(library)).digest('hex');
  const profile = {id:'steel',version:'1.1.4',source_seed:{seed_id:'seed'}};
  const item = {seed_id:'seed',version:'1.1.7',accounting_library:{id:library.id,version:library.version,
    content_sha256:hash,template_profile:library.template_profile,methods:[],tasks:library.tasks}};
  assert.equal(matchesTemplateRelease(item,profile,[library]),true);
  assert.equal(matchesTemplateRelease({...item,version:'1.1.4'},profile,[library]),false);
  assert.equal(matchesTemplateRelease({...item,accounting_library:{...item.accounting_library,content_sha256:'b'.repeat(64)}},profile,[library]),false);
  // A diverging task declaration is a different accounting release and must not be waved through.
  assert.equal(matchesTemplateRelease({...item,accounting_library:{...item.accounting_library,
    tasks:[{default_ref:'cbam@1.0.7', refs:['cbam@1.0.7'], role:'cbam'}]}},profile,[library]),false);
  assert.equal(matchesTemplateRelease(item,profile,[library,library]),false);
  assert.equal(matchesTemplateRelease({seed_id:'seed',version:'1.1.4'},profile,[]),true);
});

test('occupied preferred port selects a new loopback port', async () => {
  const server = http.createServer();
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  try { assert.notEqual(await availablePort(server.address().port), server.address().port); }
  finally { await new Promise(resolve => server.close(resolve)); }
});

test('handoff credentials bind to exact owned editor URL', () => {
  const payload = { handoff_id: 'abcf2b9a-58fa-46e8-b6d8-21bec0529a7a', state: 'exact-state', confirmation_token: 'secret' };
  payload.url = `http://127.0.0.1:32123/projects/id?handoff_id=${payload.handoff_id}&state=${payload.state}`;
  assert.equal(validateHandoff(payload, 'http://127.0.0.1:32123'), true);
  assert.equal(validateHandoff({...payload, state: 'other'}, 'http://127.0.0.1:32123'), false);
  assert.equal(validateHandoff(payload, 'http://127.0.0.1:32124'), false);
  assert.equal(ownedUrl('http://127.0.0.1:32123@evil.test/', ['http://127.0.0.1:32123']), false);
  assert.equal(ownedUrl('file:///etc/passwd', ['http://127.0.0.1:32123']), false);
});

test('editor serves SPA and proxies HTTP method, path and body', async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'nebula-editor-'));
  fs.writeFileSync(path.join(root, 'index.html'), '<main>editor</main>');
  const api = http.createServer((req, res) => {
    let body = ''; req.on('data', chunk => body += chunk);
    req.on('end', () => res.end(JSON.stringify({method: req.method, url: req.url, body})));
  });
  await new Promise(resolve => api.listen(0, '127.0.0.1', resolve));
  const editor = editorServer(root, `http://127.0.0.1:${api.address().port}`);
  await new Promise(resolve => editor.listen(0, '127.0.0.1', resolve));
  const origin = `http://127.0.0.1:${editor.address().port}`;
  try {
    assert.equal(await (await fetch(origin + '/projects/id')).text(), '<main>editor</main>');
    assert.equal((await fetch(origin + '/missing.js')).status, 404);
    const response = await fetch(origin + '/api/projects?version=7', {method:'POST', body:'exact-body'});
    assert.deepEqual(await response.json(), {method:'POST', url:'/api/projects?version=7', body:'exact-body'});
    assert.equal((await (await fetch(origin + '/api/stats')).json()).url, '/api/stats');
  } finally {
    await Promise.all([new Promise(resolve => editor.close(resolve)), new Promise(resolve => api.close(resolve))]);
    fs.rmSync(root, {recursive:true});
  }
});
