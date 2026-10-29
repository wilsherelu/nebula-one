// Run existing product journeys against the installed backends, never source assets.
const fs = require('node:fs');
const path = require('node:path');
const Module = require('node:module');
const { spawn } = require('node:child_process');
const asar = require('@electron/asar');

function run(binary, args, options = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(binary, args, { stdio: 'inherit', ...options });
    child.on('error', reject);
    child.on('exit', code => code === 0 ? resolve() : reject(new Error(`${args[0]} exited ${code}`)));
  });
}
async function main() {
  const [installation, data, output] = process.argv.slice(2).map(item => path.resolve(item));
  fs.mkdirSync(output, { recursive: true });
  const asarPath = path.join(installation, 'resources/app.asar');
  const module = new Module(asarPath);
  module.filename = asarPath;
  module._compile(asar.extractFile(asarPath, 'runtime.cjs').toString('utf8'), asarPath);
  const { DesktopRuntime, availablePort } = module.exports;
  const runtime = new DesktopRuntime(path.join(installation, 'resources/runtime'), data);
  try {
    const origins = await runtime.start();
    const summary = JSON.parse(fs.readFileSync(path.join(data, 'four-task-summary.json')));
    const apps = await (await fetch(origins.oneOrigin + '/api/v1/applications')).json();
    const demo = apps.find(item => item.context.resource_purpose === 'demo_project');
    const fixture = path.join(output, 'fixture.json');
    const python = process.env.NEBULA_TEST_PYTHON || 'C:/Users/31534/PycharmProjects/ILCD/.venv/Scripts/python.exe';
    await run(python, ['-c',
      'import sys,json;from pathlib import Path;sys.path.insert(0,"scripts");from v3_ui_acceptance_run import _make_pcf_snapshot;out=Path(sys.argv[3]);out.mkdir(parents=True,exist_ok=True);(out/"fixture.json").write_text(json.dumps(_make_pcf_snapshot(sys.argv[1],sys.argv[2],out)),encoding="utf-8")',
      origins.oneOrigin, origins.lcaOrigin, output]);
    const f = JSON.parse(fs.readFileSync(fixture));
    await run(process.execPath, ['scripts/ui_result_basis_acceptance.mjs', origins.oneOrigin, String(await availablePort(0)),
      path.join(output, 'basis'), f.application_id, f.snapshot_id, f.method_package_ref]);
    await run(process.execPath, ['scripts/ui_scope_editor_acceptance.mjs', origins.oneOrigin, String(await availablePort(0)),
      path.join(output, 'scope'), f.application_id, f.model_id, f.system_revision_id, f.method_id]);
    await run(process.execPath, ['scripts/ui_public_factor_gaps.mjs', origins.oneOrigin, String(await availablePort(0)),
      path.join(output, 'gaps'), demo.id, summary.pcf.snapshot_id]);
    await run(process.execPath, ['scripts/visible_browser_acceptance.mjs', origins.oneOrigin, String(await availablePort(0))], {
      env: { ...process.env, NEBULA_BROWSER_EVIDENCE_DIR: path.join(output, 'template') },
    });
    fs.writeFileSync(path.join(output, 'summary.json'), JSON.stringify({ passed: true, installation,
      manifest: JSON.parse(fs.readFileSync(path.join(installation, 'resources/runtime/payload-manifest.json'))).one_commit,
      journeys: ['basis', 'scope', 'gaps', 'template'] }, null, 2));
  } finally { await runtime.stop(); }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
