const { test } = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { availablePort, editorServer } = require('../runtime.cjs');
const { ownedUrl, validateHandoff } = require('../security.cjs');

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
