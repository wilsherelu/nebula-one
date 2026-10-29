// Owned local acceptance: unchanged shipped LCA, current One source, isolated persisted data.
const fs = require('node:fs');
const path = require('node:path');
const {spawn} = require('node:child_process');
const {DesktopRuntime, stopChild, waitHealthy} = require('../desktop/runtime.cjs');
const root = path.resolve(__dirname, '..');
async function main() {
  const [resourcesArg, dataArg, python] = process.argv.slice(2);
  if (!resourcesArg || !dataArg || !python) throw Error('resources data python required');
  const resources = path.resolve(resourcesArg), data = path.resolve(dataArg);
  const relative = path.relative(path.join(root, '.local-evidence'), data);
  if (relative.startsWith('..') || path.isAbsolute(relative)) throw Error('Use an owned .local-evidence directory');
  const runtime = new DesktopRuntime(resources, data);
  let source;
  async function stopSource() {
    if (!source || source.exitCode !== null) return;
    // Windows venv launchers have a Python child; stop this owned tree, not all Python processes.
    if (process.platform === 'win32') await new Promise(resolve => {
      const killer = spawn('taskkill.exe', ['/PID',String(source.pid),'/T','/F'], {windowsHide:true,stdio:'ignore'});
      killer.on('exit',resolve);
    });
    else await stopChild(source);
  }
  try {
    const origins = await runtime.start();
    await stopChild(runtime.children.pop());
    const env = {...process.env};
    for (const key of Object.keys(env)) if (/^(NEBULA_|DATABASE_URL$|AUTO_BOOTSTRAP_|AUTO_STARTUP_)/.test(key)) delete env[key];
    Object.assign(env, {PYTHONPATH:path.join(root,'src'), PYTHONUTF8:'1',
      NO_PROXY:'127.0.0.1,localhost', no_proxy:'127.0.0.1,localhost',
      NEBULA_ONE_PORT:new URL(origins.oneOrigin).port, NEBULA_ONE_HOST:'127.0.0.1',
      NEBULA_ONE_DATABASE_URL:'sqlite:///'+path.join(data,'one/nebula-one.db').replaceAll('\\','/'),
      NEBULA_LCA_BASE_URL:'http://nebula-lca.desktop.invalid',
      NEBULA_ONE_DESKTOP_ENGINE_ENDPOINT:origins.lcaOrigin,
      NEBULA_LCA_TRUSTED_SOURCE_URLS:origins.lcaOrigin,
      NEBULA_LCA_EDITOR_URL:origins.editorOrigin, NEBULA_LCA_TIMEOUT_SECONDS:'180',
      NEBULA_ONE_CASEPACK_ROOTS:path.join(resources,'cases'),
      NEBULA_ONE_RELEASE_CATALOG_FILE:path.join(resources,'config/public-catalog.v1.json'),
      NEBULA_ONE_SEED_AUTOLOAD_FILE:path.join(resources,'config/steel-demo.json'),
      NEBULA_ONE_WEB_ROOT:path.join(root,'web/dist')});
    async function start() {
      const log=fs.openSync(path.join(data,'logs/one-source.log'),'a');
      source=spawn(python,['-m','nebula_one'],{cwd:root,env,windowsHide:true,stdio:['ignore',log,log]});
      fs.closeSync(log); await waitHealthy(origins.oneOrigin,source);
      fs.writeFileSync(path.join(data,'origins.json'),JSON.stringify({...origins,sourcePid:source.pid,resources,data},null,2));
    }
    await start(); console.log(JSON.stringify(origins));
    while (!fs.existsSync(path.join(data,'stop'))) {
      if (fs.existsSync(path.join(data,'restart'))) {
        fs.unlinkSync(path.join(data,'restart')); await stopSource(); await start();
        console.log('restarted '+source.pid);
      }
      await new Promise(r=>setTimeout(r,500));
    }
  } finally {await stopSource();await runtime.stop();}
}
main().catch(e=>{console.error(e);process.exitCode=1;});
