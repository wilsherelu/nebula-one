const fs = require('node:fs');
const path = require('node:path');
const net = require('node:net');
const http = require('node:http');
const { spawn } = require('node:child_process');

async function availablePort(preferred = 0) {
  const probe = net.createServer();
  return new Promise((resolve, reject) => {
    probe.once('error', error => {
      if (preferred && error.code === 'EADDRINUSE') resolve(availablePort());
      else reject(error);
    });
    probe.listen(preferred, '127.0.0.1', () => {
      const port = probe.address().port;
      probe.close(error => error ? reject(error) : resolve(port));
    });
  });
}

async function waitHealthy(origin, child, timeout = 180000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    if (child.exitCode !== null || child.signalCode !== null) throw new Error('Backend exited before startup completed');
    try {
      const response = await fetch(`${origin}/health`, { signal: AbortSignal.timeout(1500) });
      if (response.ok) return;
    } catch { /* Health is expected to be unavailable during bootstrap. */ }
    await new Promise(resolve => setTimeout(resolve, 250));
  }
  throw new Error('Backend startup timed out; inspect the application logs');
}

function startChild(executable, env, logDirectory, label) {
  const log = fs.openSync(path.join(logDirectory, `${label}.log`), 'a');
  const child = spawn(executable, [], { env, windowsHide: true, stdio: ['ignore', log, log] });
  fs.closeSync(log);
  child.startError = null;
  child.on('error', error => { child.startError = error; });
  return child;
}

async function stopChild(child) {
  if (!child || child.exitCode !== null || child.signalCode !== null || !child.pid) return;
  await new Promise(resolve => {
    const timer = setTimeout(() => { child.kill('SIGKILL'); resolve(); }, 5000);
    child.once('exit', () => { clearTimeout(timer); resolve(); });
    child.kill('SIGTERM');
  });
}

function editorServer(root, apiOrigin) {
  const mime = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml', '.json': 'application/json', '.png': 'image/png', '.woff2': 'font/woff2' };
  return http.createServer((request, response) => {
    const parsed = new URL(request.url, 'http://127.0.0.1');
    if (parsed.pathname === '/api' || parsed.pathname.startsWith('/api/')) {
      const upstream = http.request(apiOrigin + parsed.pathname.slice(4) + parsed.search, {
        method: request.method, headers: { ...request.headers, host: new URL(apiOrigin).host }
      }, incoming => {
        response.writeHead(incoming.statusCode, incoming.headers);
        incoming.pipe(response);
      });
      upstream.on('error', () => { response.writeHead(502); response.end('Local modelling service unavailable'); });
      request.pipe(upstream);
      return;
    }
    let filename;
    try { filename = path.resolve(root, '.' + decodeURIComponent(parsed.pathname)); }
    catch { response.writeHead(400); response.end(); return; }
    const relative = path.relative(root, filename);
    if (relative.startsWith('..') || path.isAbsolute(relative)) { response.writeHead(403); response.end(); return; }
    if (!fs.existsSync(filename) || !fs.statSync(filename).isFile()) {
      if (path.extname(filename)) { response.writeHead(404); response.end(); return; }
      filename = path.join(root, 'index.html');
    }
    response.setHeader('Content-Type', mime[path.extname(filename)] || 'application/octet-stream');
    response.setHeader('Cache-Control', 'no-store');
    const stream = fs.createReadStream(filename);
    stream.on('error', () => { response.writeHead(404); response.end(); });
    stream.pipe(response);
  });
}

class DesktopRuntime {
  constructor(resources, data) { this.resources = resources; this.data = data; this.children = []; }

  async start() {
    const payload = JSON.parse(fs.readFileSync(path.join(this.resources, 'payload-manifest.json'), 'utf8'));
    const logs = path.join(this.data, 'logs');
    fs.mkdirSync(logs, { recursive: true });
    const lcaData = path.join(this.data, 'lca');
    const oneData = path.join(this.data, 'one');
    fs.mkdirSync(lcaData, { recursive: true });
    fs.mkdirSync(oneData, { recursive: true });
    const lcaPort = await availablePort();
    this.lcaOrigin = `http://127.0.0.1:${lcaPort}`;
    // Do not inherit developer database, API or licensed-runtime configuration.
    const env = { ...process.env };
    for (const key of Object.keys(env)) {
      if (/^(NEBULA_|DATABASE_URL$|DATA_PLATFORM_|AUTO_BOOTSTRAP_|AUTO_STARTUP_)/.test(key)) delete env[key];
    }
    const lca = startChild(path.join(this.resources, 'backends/nebula-lca-api/nebula-lca-api.exe'), {
      ...env, NEBULA_DESKTOP: '1', NEBULA_DATA_DIR: lcaData,
      NEBULA_API_PORT: String(lcaPort), AUTO_BOOTSTRAP_REFERENCE_DATA_ON_STARTUP: 'false',
      AUTO_STARTUP_MAINTENANCE_ON_STARTUP: 'true',
      NEBULA_LCA_EF31_DIR: path.join(this.resources, 'backends/nebula-lca-api/_internal/data/EF3.1'),
      NEBULA_PROVIDER_ELEMENTARY_CATALOG_PATH: path.join(this.resources, 'backends/nebula-lca-api/_internal/data/provider_profiles/steel_elementary_catalog.v1.csv'),
      NEBULA_REFERENCE_BOOTSTRAP_PROFILE: path.join(this.resources, 'backends/nebula-lca-api/_internal/data/provider_profiles/steel_elementary_catalog.v1.provenance.json'),
      NEBULA_LCA_ENGINE_COMMIT: payload.lca_commit,
      NEBULA_PROVIDER_TIDAS_FLOW_SNAPSHOT_PATH: path.join(this.resources, 'backends/nebula-lca-api/_internal/data/provider_profiles/steel_tiangong_open_flows.v2.json'),
      NEBULA_PROVIDER_TIDAS_REFERENCE_DEPENDENCY_SNAPSHOT_PATH: path.join(this.resources, 'backends/nebula-lca-api/_internal/data/provider_profiles/steel_tiangong_open_references.v1.json')
    }, logs, 'lca');
    this.children.push(lca);
    await waitHealthy(this.lcaOrigin, lca);
    this.editor = editorServer(path.join(this.resources, 'editor'), this.lcaOrigin);
    await new Promise((resolve, reject) => {
      this.editor.once('error', reject);
      this.editor.listen(0, '127.0.0.1', resolve);
    });
    this.editorOrigin = `http://127.0.0.1:${this.editor.address().port}`;
    const onePort = await availablePort();
    this.oneOrigin = `http://127.0.0.1:${onePort}`;
    const one = startChild(path.join(this.resources, 'backends/nebula-one-api/nebula-one-api.exe'), {
      ...env, NEBULA_ONE_PORT: String(onePort), NEBULA_ONE_DESKTOP_RESOURCES: this.resources,
      NEBULA_ONE_DESKTOP_DATA: oneData, NEBULA_ONE_DESKTOP_ENGINE_ENDPOINT: this.lcaOrigin,
      NEBULA_LCA_EDITOR_URL: this.editorOrigin,
      NEBULA_LCA_TRUSTED_SOURCE_URLS: this.lcaOrigin
    }, logs, 'one');
    this.children.push(one);
    await waitHealthy(this.oneOrigin, one);
    const templates = await fetch(`${this.oneOrigin}/api/v1/project-templates`).then(response => {
      if (!response.ok) throw new Error('Steel template initialization failed');
      return response.json();
    });
    const catalog = JSON.parse(fs.readFileSync(path.join(this.resources, 'config/public-catalog.v1.json'), 'utf8'));
    const profileRoot = path.join(this.resources, 'cases/project-templates');
    const profiles = fs.readdirSync(profileRoot).map(name =>
      JSON.parse(fs.readFileSync(path.join(profileRoot, name, 'template.json'), 'utf8')));
    for (const expected of catalog.seed_templates) {
      const profile = profiles.find(item => item.source_seed.seed_id === expected.seed_id
        && item.source_seed.version === expected.version
        && item.source_seed.bundle_content_sha256 === expected.bundle_content_sha256);
      if (!profile || !templates.items.some(item => item.seed_id === expected.seed_id && item.version === profile.version)) {
        throw new Error('Packaged steel template is unavailable; inspect the initialization log');
      }
    }
    return { oneOrigin: this.oneOrigin, editorOrigin: this.editorOrigin, lcaOrigin: this.lcaOrigin };
  }

  async stop() {
    if (this.editor) await new Promise(resolve => this.editor.close(resolve));
    for (const child of [...this.children].reverse()) await stopChild(child);
  }
}

module.exports = { availablePort, waitHealthy, stopChild, editorServer, DesktopRuntime };
