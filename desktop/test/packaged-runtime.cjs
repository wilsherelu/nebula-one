// Run only the exact packaged runtime/backends, with owned acceptance data.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const Module = require('node:module');
const asar = require('@electron/asar');
const { accept } = require('../four-task-smoke.cjs');

async function main() {
  const installation = path.resolve(process.argv[2]);
  const data = path.resolve(process.argv[3]);
  const report = path.resolve(process.argv[4]);
  const asarPath = path.join(installation, 'resources/app.asar');
  const module = new Module(asarPath);
  module.filename = asarPath;
  module._compile(asar.extractFile(asarPath, 'runtime.cjs').toString('utf8'), asarPath);
  const Runtime = module.exports.DesktopRuntime;
  const resources = path.join(installation, 'resources/runtime');
  const manifest = JSON.parse(fs.readFileSync(path.join(resources, 'payload-manifest.json')));
  let runtime = new Runtime(resources, data);
  try {
    const startup = await runtime.start();
    const engineStatus = await (await fetch(startup.lcaOrigin + '/api/desktop/status')).json();
    assert.equal(engineStatus.runtime.ef31_runtime_source_count, 1, 'Only the installed public runtime may characterize results');
    const pids = runtime.children.map(child => child.pid);
    const snapshots = await accept(startup.oneOrigin, data, {
      officialDefaultsOnly: process.argv.includes('--official-defaults'),
      resourceDirectory: resources
    });
    // The shipped supply resource is read from the installation, never from the source checkout.
    const supplyResource = path.join(resources, 'src/nebula_one/resources/public_supply/tiangong-china-grid-2022.v1.json');
    assert.ok(fs.existsSync(supplyResource), 'Packaged installation must carry its own public supply resource');
    assert.ok(!path.resolve(supplyResource).startsWith(path.join(__dirname, '..')), 'Supply resource must not resolve into the source tree');
    const evidence = JSON.parse(fs.readFileSync(path.join(data, 'four-task-http.json')));
    const reads = [...new Map(evidence.filter(item => item.method === 'GET'
      && (item.route.endsWith('/mfa') || item.route.endsWith('/solved-system-snapshots')
        || /organization-lifecycle-inventories\/[a-f0-9-]+$/.test(item.route)))
      .map(item => [item.route, item])).values()];
    const pcfReads = evidence.filter(item => item.method === 'POST' && item.route.endsWith('/product-carbon-footprint'));
    await runtime.stop();
    for (const pid of pids) assert.throws(() => process.kill(pid, 0), 'Owned backend must exit');
    runtime = new Runtime(resources, data);
    const restarted = await runtime.start();
    for (const record of reads) {
      const response = await fetch(restarted.oneOrigin + record.route);
      assert.equal(response.status, 200);
      const actual = await response.json();
      if (actual.result) assert.deepEqual(actual.result, record.result.result);
      else assert.deepEqual(actual, record.result);
    }
    for (const record of pcfReads) {
      const method = record.result.method_package.reference;
      const response = await fetch(restarted.oneOrigin + record.route, {method:'POST',
        headers:{'Content-Type':'application/json'}, body:JSON.stringify({method_package_ref:method})});
      assert.equal(response.status, 200);
      assert.deepEqual(await response.json(), record.result);
    }
    fs.writeFileSync(report, JSON.stringify({status:'passed', installation, resources, data,
      one_commit:manifest.one_commit, lca_commit:manifest.lca_commit,
      snapshots, startup, restarted, engineStatus, persisted_reads:reads.length + pcfReads.length, original_pids_exited:pids}, null, 2));
    console.log(JSON.stringify({status:'passed', report}));
  } finally { await runtime.stop(); }
}
main().catch(error => { console.error(error); process.exitCode=1; });
