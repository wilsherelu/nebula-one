// Exercise the installed bytes with owned data, including an upgrade from an older installation.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const Module = require('node:module');
const { spawn } = require('node:child_process');
const { createHash } = require('node:crypto');
const asar = require('@electron/asar');
const { accept } = require('../four-task-smoke.cjs');

function loadRuntime(installation) {
  const archive = path.join(installation, 'resources/app.asar');
  const loaded = new Module(archive);
  loaded.filename = archive;
  loaded._compile(asar.extractFile(archive, 'runtime.cjs').toString('utf8'), archive);
  return loaded.exports.DesktopRuntime;
}

async function command(binary, args, log) {
  const stream = fs.createWriteStream(log);
  try {
    await new Promise((resolve, reject) => {
      const child = spawn(binary, args, { windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] });
      child.stdout.on('data', data => { stream.write(data); process.stdout.write(data); });
      child.stderr.on('data', data => { stream.write(data); process.stderr.write(data); });
      child.on('error', reject);
      child.on('exit', code => code === 0 ? resolve() : reject(new Error(`${binary} exited ${code}; ${log}`)));
    });
  } finally { stream.end(); }
}

async function main() {
  const [installedArg, dataArg, evidenceArg, python, previousArg] = process.argv.slice(2);
  assert.ok(installedArg && dataArg && evidenceArg && python);
  const installation = path.resolve(installedArg), data = path.resolve(dataArg);
  const evidence = path.resolve(evidenceArg);
  assert.ok(!fs.existsSync(data), 'Use a new owned data directory for upgrade acceptance');
  fs.mkdirSync(evidence, { recursive: true });
  const resources = path.join(installation, 'resources/runtime');
  const manifest = JSON.parse(fs.readFileSync(path.join(resources, 'payload-manifest.json')));
  const report = { installation, data, one_commit: manifest.one_commit, lca_commit: manifest.lca_commit, checks: [] };
  let runtime;
  async function get(origin, route) {
    const response = await fetch(origin + route);
    assert.equal(response.status, 200, route);
    return response.json();
  }
  try {
    for (const file of manifest.files) {
      const bytes = fs.readFileSync(path.join(resources, file.path));
      assert.equal(bytes.length, file.size, file.path);
      assert.equal(createHash('sha256').update(bytes).digest('hex'), file.sha256, file.path);
    }
    report.checks.push(`Verified ${manifest.files.length} shipped payload files`);
    let previousTemplates;
    if (previousArg) {
      const previous = path.resolve(previousArg), PreviousRuntime = loadRuntime(previous);
      runtime = new PreviousRuntime(path.join(previous, 'resources/runtime'), data);
      const old = await runtime.start();
      previousTemplates = await get(old.oneOrigin, '/api/v1/project-templates');
      report.previous = { installation: previous, templates: previousTemplates.items.map(item => item.id) };
      await runtime.stop();
    }
    const Runtime = loadRuntime(installation);
    runtime = new Runtime(resources, data);
    const startup = await runtime.start();
    report.startup = startup;
    if (previousTemplates) {
      assert.deepEqual(await get(startup.oneOrigin, '/api/v1/project-templates'), previousTemplates);
      report.checks.push('Existing template records survived the installed database upgrade');
    }
    report.engine = await get(startup.lcaOrigin, '/api/desktop/status');
    assert.equal(report.engine.runtime.ef31_runtime_source_count, 1);
    report.snapshots = await accept(startup.oneOrigin, data, { officialDefaultsOnly: true, resourceDirectory: resources });
    report.checks.push('Packaged MFA / PCF / CBAM / organization tasks passed');
    const root = path.resolve(__dirname, '../..');
    const live = path.join(evidence, 'live');
    await command(python, [path.join(root, 'scripts/live_tag_template_acceptance.py'), '--one', startup.oneOrigin, '--output', live], path.join(evidence, 'live.log'));
    report.checks.push('Real engine tag totals, deduplication and frozen HTML/JSON exports passed');
    await command(process.execPath, [path.join(root, 'scripts/ui_tag_template_acceptance.mjs'), startup.oneOrigin, '19472', path.join(evidence, 'browser')], path.join(evidence, 'browser.log'));
    report.checks.push('Visible browser template creation and four viewports passed');
    await command(process.execPath, [path.join(root, 'scripts/ui_tag_results_acceptance.mjs'), startup.oneOrigin,
      path.join(live, 'summary.json'), '19473', path.join(evidence, 'results-browser')], path.join(evidence, 'results-browser.log'));
    report.checks.push('Visible result selection, history and browser exports passed');
    const pids = runtime.children.map(child => child.pid);
    await runtime.stop();
    for (const pid of pids) assert.throws(() => process.kill(pid, 0), 'Owned backend must exit');
    runtime = new Runtime(resources, data);
    const restarted = await runtime.start();
    report.restarted = restarted;
    await command(python, [path.join(root, 'scripts/live_tag_template_acceptance.py'), '--one', restarted.oneOrigin, '--output', live, '--readback'], path.join(evidence, 'readback.log'));
    report.checks.push('Frozen results survived a full packaged backend restart');
    report.status = 'passed';
  } catch (error) {
    report.status = 'failed'; report.error = error.stack;
    throw error;
  } finally {
    if (runtime) await runtime.stop();
    fs.writeFileSync(path.join(evidence, 'summary.json'), JSON.stringify(report, null, 2));
  }
  console.log(JSON.stringify({ status: report.status, evidence }));
}
main().catch(error => { console.error(error); process.exitCode = 1; });
