// Upgrade-compatibility check against a BACKUP COPY of an existing install's database.
// Never points at the live user data dir: the caller copies one/nebula-one.db and
// lca/nebula-lca.db into an isolated directory first. This starts the exact packaged
// backends against that copy (so migrations run on the copy), then proves every old
// record is still present and readable through the API, and that owned processes exit.
//
// Note on the applications list: GET /api/v1/applications intentionally hides internal
// seed / modeling-source applications (ApplicationService.list filters internal_application_ids);
// those are reached by id. So compatibility is asserted per-id, not by list length.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const Module = require('node:module');
const { isDeepStrictEqual } = require('node:util');
const asar = require('@electron/asar');
const { DatabaseSync } = require('node:sqlite');

function readState(oneDb) {
  const db = new DatabaseSync(oneDb, { readOnly: true });
  try {
    const ids = (table) => db.prepare(`SELECT id FROM "${table}"`).all().map((row) => row.id).sort();
    const count = (table) => db.prepare(`SELECT COUNT(*) AS c FROM "${table}"`).get().c;
    return {
      application_ids: ids('applications'),
      applications: count('applications'),
      method_packages: count('method_packages'),
      method_package_rows: db.prepare('SELECT id, package_id, version, content_sha256, manifest FROM method_packages ORDER BY id').all(),
      solved_snapshot_ids: ids('solved_system_snapshots'),
      solved_system_snapshots: count('solved_system_snapshots'),
      organization_inventory_ids: ids('organization_period_inventories'),
      periods: count('periods'),
      system_models: count('system_models'),
    };
  } finally { db.close(); }
}

async function main() {
  const installation = path.resolve(process.argv[2]);
  const data = path.resolve(process.argv[3]);
  const report = path.resolve(process.argv[4]);
  const oneDb = path.join(data, 'one', 'nebula-one.db');
  assert.ok(fs.existsSync(oneDb), `Backup copy of one DB must exist at ${oneDb}`);
  const before = readState(oneDb);

  const asarPath = path.join(installation, 'resources/app.asar');
  const module = new Module(asarPath);
  module.filename = asarPath;
  module._compile(asar.extractFile(asarPath, 'runtime.cjs').toString('utf8'), asarPath);
  const Runtime = module.exports.DesktopRuntime;
  const resources = path.join(installation, 'resources/runtime');
  const manifest = JSON.parse(fs.readFileSync(path.join(resources, 'payload-manifest.json')));

  const runtime = new Runtime(resources, data);
  const checks = [];
  const record = (name, ok, detail) => checks.push({ name, ok: !!ok, detail });
  try {
    const startup = await runtime.start();
    const pids = runtime.children.map((child) => child.pid);
    const get = async (route) => {
      const response = await fetch(startup.oneOrigin + route, { signal: AbortSignal.timeout(60000) });
      const text = await response.text();
      let body; try { body = JSON.parse(text); } catch { body = text; }
      return { status: response.status, body };
    };

    // A healthy start against the old DB means every schema migration ran without error.
    record('backend_started_healthy_on_old_db', !!startup.oneOrigin, { oneOrigin: startup.oneOrigin });

    // Every pre-upgrade application must still be fetchable by id (seeds are hidden from
    // the list endpoint by design, so id reads are the compatibility contract).
    const appReads = {};
    for (const id of before.application_ids) {
      const one = await get(`/api/v1/applications/${id}`);
      appReads[id] = one.status;
    }
    const appsOk = before.application_ids.every((id) => appReads[id] === 200);
    record('all_original_applications_readable_by_id', appsOk, { appReads });

    const packages = await get('/api/v1/method-packages');
    const packageCount = Array.isArray(packages.body) ? packages.body.length : (packages.body?.items?.length ?? -1);
    const currentPackages = readState(oneDb).method_package_rows;
    const changedOrMissing = before.method_package_rows.filter((original) =>
      !currentPackages.some((current) => isDeepStrictEqual(current, original))).map((row) => row.id);
    record('method_packages_preserved', packages.status === 200 && packageCount >= before.method_packages && changedOrMissing.length === 0,
      { status: packages.status, before: before.method_packages, after: packageCount, changedOrMissing });

    // Collect every snapshot id reachable through its application, then read each one's MFA.
    const reachable = new Set();
    for (const id of before.application_ids) {
      const list = await get(`/api/v1/applications/${id}/solved-system-snapshots`);
      if (list.status === 200 && Array.isArray(list.body)) for (const item of list.body) reachable.add(item.id);
    }
    const listedOk = before.solved_snapshot_ids.every((id) => reachable.has(id));
    record('all_original_solved_snapshots_listed', listedOk,
      { expected: before.solved_snapshot_ids, reachable: [...reachable].sort() });

    let mfaOk = 0;
    for (const id of before.solved_snapshot_ids) {
      const mfa = await get(`/api/v1/solved-system-snapshots/${id}/mfa`);
      if (mfa.status === 200) mfaOk += 1;
    }
    record('all_original_solved_snapshots_mfa_readable', mfaOk === before.solved_system_snapshots,
      { readable: mfaOk, total: before.solved_system_snapshots });

    let orgOk = 0;
    for (const id of before.organization_inventory_ids) {
      const direct = await get(`/api/v1/organization-lifecycle-inventories/${id}`);
      if (direct.status === 200) { orgOk += 1; continue; }
      for (const appId of before.application_ids) {
        const scoped = await get(`/api/v1/applications/${appId}/organization-lifecycle-inventories/${id}`);
        if (scoped.status === 200) { orgOk += 1; break; }
      }
    }
    record('organization_inventories_readable', orgOk === before.organization_inventory_ids.length,
      { readable: orgOk, total: before.organization_inventory_ids.length });

    await runtime.stop();
    for (const pid of pids) assert.throws(() => process.kill(pid, 0), 'Owned backend must exit');
    record('owned_backends_exited', true, { pids });

    // Post-migration the storage layer must still contain every original id (no loss);
    // the desktop seed may ADD an internal demo application, so counts can only grow.
    const after = readState(oneDb);
    const appsPreserved = before.application_ids.every((id) => after.application_ids.includes(id));
    const snapshotsPreserved = before.solved_snapshot_ids.every((id) => after.solved_snapshot_ids.includes(id));
    record('storage_preserves_all_original_application_ids', appsPreserved,
      { before: before.application_ids, after: after.application_ids });
    record('storage_preserves_all_original_snapshot_ids', snapshotsPreserved,
      { before: before.solved_system_snapshots, after: after.solved_system_snapshots });

    const failed = checks.filter((item) => !item.ok);
    fs.writeFileSync(report, JSON.stringify({
      status: failed.length ? 'failed' : 'passed',
      installation, one_commit: manifest.one_commit, lca_commit: manifest.lca_commit,
      before, after, checks, failed: failed.map((item) => item.name),
    }, null, 2));
    console.log(JSON.stringify({ status: failed.length ? 'failed' : 'passed', report, checks: checks.map((c) => `${c.ok ? 'pass' : 'FAIL'} ${c.name}`) }));
    if (failed.length) process.exitCode = 1;
  } finally { await runtime.stop(); }
}
main().catch((error) => { console.error(error); process.exitCode = 1; });
