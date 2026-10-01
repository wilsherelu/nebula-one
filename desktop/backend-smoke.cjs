const path = require('node:path');
const fs = require('node:fs');
const { DesktopRuntime } = require('./runtime.cjs');

async function main() {
  const data = process.argv[2];
  if (!data) throw new Error('Specify an isolated desktop data directory');
  const runtime = new DesktopRuntime(path.join(__dirname, 'resources'), path.resolve(data));
  try {
    const origins = await runtime.start();
    const response = await fetch(origins.oneOrigin + '/api/v1/applications');
    const projects = await response.json();
    if (!response.ok) throw new Error(JSON.stringify(projects));
    const report = {...origins, projects, children:runtime.children.map(child => child.pid)};
    fs.writeFileSync(path.join(data, 'backend-smoke.json'), JSON.stringify(report, null, 2));
    process.stdout.write(JSON.stringify(report));
  } finally { await runtime.stop(); }
}
main().catch(error => { process.stderr.write(error.stack); process.exitCode = 1; });
