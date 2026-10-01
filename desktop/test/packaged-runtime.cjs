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
  const startup = await runtime.start();
  const pids = runtime.children.map(child => child.pid);
  try {
    const snapshots = await accept(startup.oneOrigin, data);
    const evidence = JSON.parse(fs.readFileSync(path.join(data, 'four-task-http.json')));
    const reads = evidence.filter(item => item.method === 'GET'
      && (item.route.endsWith('/mfa') || /organization-lifecycle-inventories\/[a-f0-9-]+$/.test(item.route)));
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
    fs.writeFileSync(report, JSON.stringify({status:'passed', installation,
      one_commit:manifest.one_commit, lca_commit:manifest.lca_commit,
      snapshots, startup, restarted, persisted_reads:reads.length, original_pids_exited:pids}, null, 2));
    console.log(JSON.stringify({status:'passed', report}));
  } finally { await runtime.stop(); }
}
main().catch(error => { console.error(error); process.exitCode=1; });
