// Verify the installed server code and installed editor assets, without starting backends.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const Module = require('node:module');
const asar = require('@electron/asar');

async function main() {
  const installation = path.resolve(process.argv[2]);
  const report = path.resolve(process.argv[3]);
  const filename = path.join(installation, 'resources/app.asar');
  const runtime = new Module(filename, module);
  runtime.filename = filename;
  runtime.paths = module.paths;
  runtime._compile(asar.extractFile(filename, 'runtime.cjs').toString('utf8'), filename);
  const root = path.join(installation, 'resources/runtime/editor');
  const server = runtime.exports.editorServer(root, 'http://127.0.0.1:9');
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const origin = `http://127.0.0.1:${server.address().port}`;
  const records = [];
  try {
    for (const route of ['/projects/852aa1f8-ca2a-5ecd-86d1-ace69b5f6170?version=2', '/projects/852aa1f8-ca2a-5ecd-86d1-ace69b5f6170/?version=2']) {
      const response = await fetch(origin + route);
      assert.equal(response.status, 200);
      const html = await response.text();
      const urls = [...html.matchAll(/(?:src|href)=["']([^"']+\.(?:js|css))["']/g)].map(match => match[1]);
      assert.ok(urls.some(url => url.endsWith('.js')));
      assert.ok(urls.some(url => url.endsWith('.css')));
      for (const url of urls) {
        const absolute = new URL(url, origin + route);
        assert.ok(absolute.pathname.startsWith('/assets/'), absolute.href);
        const asset = await fetch(absolute);
        assert.equal(asset.status, 200, absolute.href);
        assert.ok(asset.headers.get('content-type').includes(url.endsWith('.js') ? 'javascript' : 'css'));
        const bytes = Buffer.from(await asset.arrayBuffer());
        assert.deepEqual(bytes, fs.readFileSync(path.join(root, absolute.pathname)));
        records.push({route, asset:absolute.pathname, status:asset.status, size:bytes.length,
          sha256:crypto.createHash('sha256').update(bytes).digest('hex')});
      }
    }
    fs.writeFileSync(report, JSON.stringify({status:'passed', installation, records}, null, 2));
    console.log(JSON.stringify({status:'passed', assets:records.length, report}));
  } finally { await new Promise(resolve => server.close(resolve)); }
}
main().catch(error => { console.error(error); process.exitCode=1; });
