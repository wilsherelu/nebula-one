const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { randomUUID } = require('node:crypto');
const { DesktopRuntime } = require('./runtime.cjs');

async function accept(origin, directory) {
  const evidence = [];
  async function call(method, route, body) {
    const response = await fetch(origin + route, {method, ...(body ? {headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)} : {}), signal:AbortSignal.timeout(180000)});
    const text = await response.text();
    let result; try { result = JSON.parse(text); } catch { result = text; }
    evidence.push({method, route, status:response.status, result});
    fs.writeFileSync(path.join(directory, 'four-task-http.json'), JSON.stringify(evidence, null, 2));
    if (!response.ok) throw new Error(`${route}: ${response.status} ${text.slice(0, 2000)}`);
    return result;
  }
  const application = (await call('GET', '/api/v1/applications')).find(item => item.context.resource_purpose === 'demo_project');
  assert.ok(application, 'Official demo must exist');
  const prefix = `/api/v1/applications/${application.id}`;
  const model = (await call('GET', prefix + '/system-models'))[0];
  const revisions = await call('GET', `/api/v1/system-models/${model.id}/revisions`);
  const initial = await call('GET', prefix + '/workspace/' + revisions[revisions.length-1].id);
  const suppliers = await call('GET', prefix + '/workspace/' + initial.revision_id + '/background/user-projects');
  const supplyResource = JSON.parse(fs.readFileSync(path.join(__dirname, 'resources/src/nebula_one/resources/public_supply/tiangong-china-grid-2022.v1.json'), 'utf8'));
  const supplier = suppliers.items.find(item => item.name === supplyResource.project_name);
  assert.ok(supplier, 'Exact public electricity background must be installed');
  const fields = initial.fields.filter(field => !field.linked && field.port_id === 'grid-electricity-in');
  assert.equal(fields.length, 2);
  const pins = [];
  for (const field of fields) {
    pins.push((await call('POST', prefix + '/workspace/' + initial.revision_id + '/background/user-project-resolve', {
      project_id:supplier.project_id, version:1, consumer_exchange_id:field.key
    })).pin);
  }
  const workspace = await call('POST', prefix + '/workspace/inputs', {
    revision_id: initial.revision_id, expected_content_sha256: initial.content_sha256,
    demand_mode:'reference_output', amounts:[7], project_background_pins:pins,
    values:Object.fromEntries(initial.fields.filter(field => !field.linked).map(field => [field.key,field.value])),
    source:'Desktop packaged runtime acceptance'
  });
  const periods = await call('GET', prefix + '/periods');
  const packages = await call('GET', '/api/v1/method-packages');
  const outcomes = {};
  for (const task of ['mfa', 'pcf', 'cbam', 'organization']) {
    const request = {demand:workspace.demand, analysis_task:task,
      calculation_purpose:task === 'cbam' ? 'cbam' : 'lca',
      project_background_pins:pins, idempotency_key:`desktop-${task}-${randomUUID()}`,
      ...(['pcf','organization'].includes(task) ? {climate_default:true} : {})};
    const snapshot = await call('POST', prefix + `/system-revisions/${workspace.revision_id}/solve`, request);
    assert.deepEqual(await call('POST', prefix + `/system-revisions/${workspace.revision_id}/solve`, request), snapshot);
    assert.equal(snapshot.system_revision_id, workspace.revision_id);
    const route = `/api/v1/solved-system-snapshots/${snapshot.id}`;
    let result;
    if (task === 'mfa') result = await call('GET', route + '/mfa');
    if (task === 'pcf') {
      const method = (await call('GET', route + '/product-carbon-footprint/default-method')).reference;
      result = await call('POST', route + '/product-carbon-footprint', {method_package_ref:method});
      assert.ok(result.total_footprint.value > 0);
    }
    if (task === 'cbam') {
      const hash = snapshot.provider_receipt.calculation_basis.source_model.graph_sha256;
      const boundary = (await call('GET', prefix + '/boundaries')).find(item => item.geographic_scope?.graph_sha256 === hash && item.method_package_ref);
      assert.ok(boundary);
      result = await call('POST', route + '/cbam-trial', {method_package_ref:boundary.method_package_ref,
        reporting_period_id:periods[0].id, boundary_definition_id:boundary.id,
        end_use_declaration:'sold_or_transferred_as_crude_steel'});
    }
    if (task === 'organization') {
      const refs = (await call('GET', prefix)).context.method_package_refs;
      const method = refs.slice().reverse().map(ref => packages.find(item => `${item.package_id}@${item.version}` === ref))
        .find(item => item?.package_kind === 'organization_lifecycle_carbon');
      assert.ok(method);
      result = await call('POST', prefix + '/organization-lifecycle-inventories', {solved_snapshot_id:snapshot.id,
        method_package_ref:`${method.package_id}@${method.version}`, reporting_period_id:periods[0].id,
        facility:'Desktop steel acceptance', controlled_process_ids:workspace.process_graph.nodes.map(node => node.id),
        input_basis:'annual_total', period_product_output:workspace.demand[0].amount, other_activities:[]});
    }
    outcomes[task] = {snapshot_id:snapshot.id, revision_id:workspace.revision_id, result};
  }
  fs.writeFileSync(path.join(directory, 'four-task-summary.json'), JSON.stringify(outcomes, null, 2));
  return Object.fromEntries(Object.entries(outcomes).map(([task, value]) => [task, value.snapshot_id]));
}

async function main() {
  const directory = path.resolve(process.argv[2]);
  const runtime = new DesktopRuntime(path.join(__dirname, 'resources'), directory);
  try {
    const origins = await runtime.start();
    console.log(JSON.stringify(await accept(origins.oneOrigin, directory)));
  } finally { await runtime.stop(); }
}
if (require.main === module) main().catch(error => { console.error(error); process.exitCode=1; });
module.exports = {accept};
