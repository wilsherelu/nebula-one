"""Project instances of verified installed seeds; model identities stay immutable."""
from copy import deepcopy
from uuid import UUID, NAMESPACE_URL, uuid5

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ..adapters.nebula_lca import same_pinned_model
from ..analysis.cbam_trial_v2 import is_multi_process_v2, precursor_membership_coverage_gaps
from ..errors import DomainError
from ..hashing import canonical_content_sha256, canonical_graph_sha256, canonical_json_sha256, without_display_labels
from ..models import Application, SeedInstallation, SystemModel, SystemRevision, new_id, utcnow
from ..runtime_models import BoundaryDefinition, MethodPackage, Period
from ..schemas import ModelOperationBatchCreate, ModelOperationItem
from ..runtime_schemas import ProviderBackgroundProcessPin, ProviderProjectBackgroundPin
from ..release_resources import DEMO_PROJECT, demo_project_key, display_labels, pick_name
from ..model_processing_contract import PackageRef, load_model_processing_rules_by_reference, TemplateRef
from .project_background import ProjectBackgroundService, list_background_ports
from .project_template_profiles import load_profile
from .project_template_revision import apply_template_revision
from ..mapped_background_schemas import ProviderMappedBackgroundProcessPin
from .project_mapped_background import ProjectMappedBackgroundService
from .project_user_background import ProjectUserBackgroundService
from .flow_display import exact_flow_labels
from .case_display import display_project_graph

BOUNDARY_FIELDS = ('name', 'boundary_type', 'included_entity_ids', 'included_process_ids',
                   'included_flow_rules', 'excluded_items', 'consolidation_policy', 'period_id',
                   'geographic_scope', 'method_package_ref')


class SeedProjectCreate(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=255)
    project_key: UUID
    expected_template_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')


def fail(code, message, status=409, **details):
    raise DomainError(code=code, message=message, status_code=status, details=details)


def same_editor_source_graph(authored, saved):
    """Compare an authored bundle with LCA's saved graph_slim serialization."""
    left, right = without_display_labels(authored), without_display_labels(saved)
    versions = (left.get('metadata', {}).get('storage_schema_version'),
                right.get('metadata', {}).get('storage_schema_version'))
    if versions not in (("nebula.project.bundle.v1", "graph_slim_v1"),
                        ("graph_slim_v1", "graph_slim_v1"),
                        ("nebula.project.bundle.v1", "nebula.project.bundle.v1")):
        return False
    for graph in (left, right):
        graph['metadata'].pop('storage_schema_version')
        for edge in graph.get('exchanges', []):
            if edge.get('sourceHandle') in (None, f"out:{edge.get('sourcePortId')}"):
                edge.pop('sourceHandle', None)
            if edge.get('targetHandle') in (None, f"in:{edge.get('targetPortId')}"):
                edge.pop('targetHandle', None)
    return canonical_json_sha256(left) == canonical_json_sha256(right)


def pin_editor_model_receipt(model, exact, editor):
    current = deepcopy(model.upstream_receipt or {})
    endpoint = f"/api/projects/{editor['engine_project_id']}/versions/{editor['engine_version']}"
    if (current.get('endpoint') == endpoint and
            current.get('template_editor_source') == editor and
            'template_installed_source' in current):
        return False
    if 'template_installed_source' not in current:
        current['template_installed_source'] = deepcopy({
            key: value for key, value in current.items()
            if key not in ('template_editor_source', 'template_installed_source')})
    current['endpoint'] = endpoint
    current['retrieved_at'] = utcnow().isoformat()
    current.pop('upstream_created_at', None)
    current['source_policy'] = exact['source_policy']
    current['allowed_lcia_scope'] = exact['allowed_lcia_scope']
    current['functional_unit'] = exact['functional_unit']['display_text']
    current['template_editor_source'] = deepcopy(editor)
    model.upstream_receipt = current
    return True


def inventory_fields(graph):
    """Single-quantity internal links expose one shared value at both ends."""
    aliases = {}
    for edge in graph.get('exchanges', []):
        if edge.get('quantityMode', 'single') == 'single':
            aliases[(edge['toNode'], edge['targetPortId'])] = f"{edge['fromNode']}::{edge['sourcePortId']}"
    fields = []
    for node in graph.get('nodes', []):
        for group in ('inputs', 'outputs', 'emissions'):
            for port in node.get(group, []):
                fields.append({'key': aliases.get((node['id'], port['id']), f"{node['id']}::{port['id']}"),
                    'process_id': node['id'], 'port_id': port['id'], 'process': node.get('name', node['id']),
                    'label': port.get('name', port['id']), 'group': group, 'flow_type': port.get('type'), 'value': port.get('amount'),
                    'unit': port.get('unit'), 'flow_uuid': port.get('flowUuid', port.get('flow_uuid')),
                    'mode': node.get('mode'), 'linked': (node['id'], port['id']) in aliases,
                    'reference_product': bool(port.get('isProduct')),
                    **({'description': port['display_description']} if port.get('display_description') else {}),
                    **({'source_label': port['source_display_name'], 'source_process_name': node.get('source_display_name')}
                       if 'source_display_name' in port else {}),
                    **({'source_catalog_label': port['source_catalog_display_name']} if port.get('source_catalog_display_name') else {})})
    return fields


def process_graph_projection(graph):
    """The read-only process topology the workbench draws, straight from the stored revision.

    Nodes and edges are what the saved graph itself declares; a connection exists only where an
    exchange does, so the canvas can never invent a link by array order. Background suppliers are
    associations shown per exchange, not foreground topology, so they are deliberately absent here.
    """
    nodes = [{'id': node['id'], 'name': node.get('name', node['id'])} for node in graph.get('nodes', [])]
    node_ids = {node['id'] for node in nodes}
    labels = {(node['id'], port['id']): port['name'] for node in graph.get('nodes', [])
              for port in node.get('outputs', []) if port.get('source_display_name') and port.get('name')}
    edges = [
        {'source': edge['fromNode'], 'target': edge['toNode'], 'label': labels.get((edge['fromNode'], edge.get('sourcePortId')), edge.get('name', edge['id']))}
        for edge in graph.get('exchanges', [])
        if edge['fromNode'] in node_ids and edge['toNode'] in node_ids and edge['fromNode'] != edge['toNode']
    ]
    return {'nodes': nodes, 'edges': edges}


def demand_for_inventory(fields, demand, payload):
    """Keep a batch's solve demand tied to its declared final output unless explicitly overridden."""
    if payload.demand_mode != 'reference_output':
        return payload.amounts
    output_amounts = []
    for item in demand:
        matches = {field['key'] for field in fields
                   if field['group'] == 'outputs' and field['reference_product']
                   and field['flow_uuid'] == item['reference_flow_uuid']
                   and field['unit'] == item['unit']}
        if len(matches) != 1:
            fail('PROJECT_REFERENCE_OUTPUT_AMBIGUOUS', '目标产品产出缺失或不唯一，不能自动确定求解需求。', 422)
        amount = payload.values[next(iter(matches))]
        if amount <= 0:
            fail('PROJECT_REFERENCE_AMOUNT_INVALID', '目标产品产出必须大于零。', 422)
        output_amounts.append(amount)
    return output_amounts


def apply_inventory_inputs(container, parent, payload, demand, *, idempotency_prefix, label):
    """Restate one data version's port amounts and inputs as a new revision.

    One edit contract, shared by a template instance and by a model returned from professional
    modelling: the fillable list is the stored graph's own exchanges, so a process the editor added
    is opened field by field instead of the whole project being refused for not matching a template.
    """
    if parent.content_sha256 != payload.expected_content_sha256:
        fail('PROJECT_INPUT_CONFLICT', '数据版本已改变，请重新加载。')
    fields = inventory_fields(parent.graph_snapshot)
    if set(payload.values) != {f['key'] for f in fields}:
        fail('PROJECT_FIELDS_INVALID', '填报清单与固定模板不一致。', 422)
    if len(payload.amounts) != len(demand) or not payload.source.strip():
        fail('PROJECT_INPUT_INVALID', '请完整填写核算规模和数据来源。', 422)
    if any(f['reference_product'] and payload.values[f['key']] <= 0 for f in fields):
        fail('PROJECT_REFERENCE_AMOUNT_INVALID', '参考产品数量必须大于零。', 422)
    from .inventory_derivation import derive_inventory, recipe_of
    submitted_graph = deepcopy(parent.graph_snapshot)
    for node in submitted_graph.get('nodes', []):
        for group in ('inputs', 'outputs', 'emissions'):
            for port in node.get(group, []):
                field = next(f for f in fields if f['process_id'] == node['id'] and f['port_id'] == port['id'])
                port['amount'] = payload.values[field['key']]
    submitted_graph, derived_values = derive_inventory(submitted_graph, recipe_of(parent.application_context))
    effective_values = {**payload.values}
    for field in fields:
        derived = derived_values.get(f"{field['process_id']}::{field['port_id']}")
        if derived is not None:
            effective_values[field['key']] = float(derived)
    operations = [ModelOperationItem(operation_type='flow.update_port', payload={
        'process_id': f['process_id'], 'port_id': f['port_id'],
        'changes': {'amount': effective_values[f['key']]}}) for f in fields]
    amounts = {(f['process_id'], f['port_id']): effective_values[f['key']] for f in fields}
    for edge in parent.graph_snapshot.get('exchanges', []):
        supply = amounts[(edge['fromNode'], edge['sourcePortId'])]
        consumer = amounts[(edge['toNode'], edge['targetPortId'])]
        operations.append(ModelOperationItem(operation_type='flow.update_exchange', payload={
            'exchange_id': edge['id'], 'changes': {'amount': consumer, 'providerAmount': supply,
                'consumerAmount': consumer}}))
    pins = payload.background_process_pins
    if pins is None:
        pins = [ProviderBackgroundProcessPin.model_validate(p) for p in parent.application_context.get('project_inputs', {}).get('background_process_pins', [])]
    mapped_pins = payload.mapped_background_process_pins
    if mapped_pins is None:
        mapped_pins = [ProviderMappedBackgroundProcessPin.model_validate(p) for p in parent.application_context.get('project_inputs', {}).get('mapped_background_process_pins', [])]
    project_pins = payload.project_background_pins
    if project_pins is None:
        project_pins = [ProviderProjectBackgroundPin.model_validate(p) for p in parent.application_context.get('project_inputs', {}).get('project_background_pins', [])]
    consumers = [p.consumer_exchange_id for p in [*pins, *mapped_pins, *project_pins]]
    if len(consumers) != len(set(consumers)):
        fail('PROJECT_BACKGROUND_DUPLICATE', '一个投入只能关联一个背景供应过程。', 422)
    # Verify against the edited quantities as zero inputs cannot supply a leaf.
    edited_graph = deepcopy(parent.graph_snapshot)
    for n in edited_graph['nodes']:
        for p in n.get('inputs', []):
            p['amount'] = amounts[(n['id'], p['id'])]
    ProjectBackgroundService(container.client).validate(edited_graph, pins)
    ProjectMappedBackgroundService(container.client).validate(edited_graph, mapped_pins)
    ProjectUserBackgroundService(container.client).validate(edited_graph, project_pins)
    rules_ref = payload.model_processing_rules_ref
    if rules_ref is None:
        stored_ref = parent.application_context.get('project_inputs', {}).get('model_processing_rules_ref')
        rules_ref = PackageRef.model_validate(stored_ref) if stored_ref else None
    if rules_ref is not None:
        from .model_processing_runtime import template_identity
        from .returned_cbam_binding import _identity_graph
        with container.database.session() as db:
            model = db.get(SystemModel, parent.system_model_id)
            application = db.get(Application, model.application_id) if model else None
        rules = load_model_processing_rules_by_reference(**rules_ref.model_dump())
        if (rules.applicable_template != TemplateRef.model_validate(template_identity(parent, application)) or
                rules.reviewed_returned_graph is not None and
                rules.reviewed_returned_graph['accepted_graph_identity_sha256'] != canonical_json_sha256(_identity_graph(edited_graph))):
            fail('MODEL_PROCESSING_RULES_MISMATCH', '模型处理规则包不属于此模板和图版本。', 409)
    effective_amounts = demand_for_inventory(fields, demand, payload)
    data = {'demand': [{**d, 'amount': n} for d, n in zip(demand, effective_amounts)],
        'demand_mode': payload.demand_mode,
        'values': effective_values, 'source': payload.source.strip(),
        'background_process_pins': [p.model_dump(mode='json') for p in pins]}
    if mapped_pins:
        data['mapped_background_process_pins'] = [p.model_dump(mode='json') for p in mapped_pins]
    if project_pins:
        data['project_background_pins'] = [p.model_dump(mode='json') for p in project_pins]
    if rules_ref is not None:
        data['model_processing_rules_ref'] = rules_ref.model_dump(mode='json')
    operations.append(ModelOperationItem(operation_type='system.merge_context', payload={'context': {'project_inputs': data}}))
    batch = ModelOperationBatchCreate(parent_revision_id=parent.id,
        expected_parent_content_sha256=parent.content_sha256,
        idempotency_key=idempotency_prefix + ':' + canonical_json_sha256({'parent': parent.id, 'data': data}),
        operations=operations, label=label)
    _, revision, _, _ = container.system_revisions.apply_batch(parent.system_model_id, batch, template_input=True)
    return revision


def project_application_id(project_key, installation_id):
    return str(uuid5(project_key, f'seed-project:{installation_id}'))


class SeedProjectService:
    def __init__(self, container):
        self.c = container

    def _source(self, db, installation_id):
        row = db.get(SeedInstallation, installation_id)
        if not row or row.status != 'ready' or row.engine_base_url.rstrip('/') != self.c.client.base_url:
            fail('SEED_TEMPLATE_UNAVAILABLE', '标准模型尚未在当前算法服务完成安装验证。')
        model = db.get(SystemModel, row.system_model_id)
        app = db.get(Application, row.application_id)
        if not model or not app:
            fail('SEED_TEMPLATE_UNAVAILABLE', '标准模型安装记录不完整。')
        refs = app.context.get('method_package_refs', [])
        packages = list(db.scalars(select(MethodPackage).where(
            MethodPackage.package_id.in_([r.rsplit('@', 1)[0] for r in refs]))))
        pins = {f'{p.package_id}@{p.version}': p.content_sha256 for p in packages if f'{p.package_id}@{p.version}' in refs}
        if set(pins) != set(refs):
            fail('SEED_TEMPLATE_METHOD_MISSING', '标准模型的方法版本未完整安装。')
        context = deepcopy(app.context)
        profile = load_profile(self.c.settings.casepack_roots, row)
        registrations = []
        replacements = {}
        if profile:
            for old_ref, package, digest in profile[2]:
                if old_ref not in pins:
                    fail('SEED_TEMPLATE_METHOD_MISSING', '项目模板的方法替换不属于原模型。')
                new_ref = f'{package.package_id}@{package.version}'
                replacements[old_ref] = new_ref
                del pins[old_ref]
                pins[new_ref] = digest
                registrations.append((package, digest))
            context['method_package_refs'] = [replacements.get(ref, ref) for ref in refs]
        capabilities = ['mfa.solved.v1']
        for p in packages:
            if f'{p.package_id}@{p.version}' not in refs:
                continue
            if p.package_kind == 'product_carbon_footprint':
                capabilities.append('pcf.product.v1')
            if p.package_kind == 'cbam_trial':
                capabilities.append('cbam.trial.v2')
        content = {'seed_id': row.seed_id, 'seed_version': row.seed_version,
            'bundle_content_sha256': row.bundle_content_sha256, 'graph_sha256': model.graph_sha256,
            'boundary_pins': {b.id: b.content_sha256 for b in db.scalars(select(BoundaryDefinition).where(
                BoundaryDefinition.application_id == app.id, BoundaryDefinition.status == 'frozen'))},
            'method_pins': pins, 'source_context': context, 'capabilities': capabilities,
            'method_replacements': replacements,
            'profile': {'id': profile[0]['id'], 'version': profile[0]['version'], 'content_sha256': profile[1]} if profile else None}
        upgrade = profile[0].get('identity_revision') if profile else None
        if profile:
            for key in ('inventory_derivation', 'boundary_revision'):
                if profile[0].get(key):
                    content[key] = deepcopy(profile[0][key])
        derived_graph = apply_template_revision(model.graph_snapshot, upgrade)
        from .inventory_derivation import derive_inventory
        derived_graph, _ = derive_inventory(derived_graph, content.get('inventory_derivation'))
        manifests = {f'{p.package_id}@{p.version}': p for p in packages}
        manifests |= {f'{package.package_id}@{package.version}': package for package, _ in registrations}
        for ref in sorted(pins):
            package = manifests.get(ref)
            if package is None or package.package_kind != 'cbam_trial':
                continue
            gaps = precursor_membership_coverage_gaps(derived_graph, package.manifest) \
                if is_multi_process_v2(package.manifest) else []
            if gaps:
                fail('SEED_TEMPLATE_PRECURSOR_EVIDENCE_STALE',
                     '方法包的前体归属记录未覆盖修订后模型的跨界投入，请先升版方法包。',
                     method_package_ref=ref, gaps=gaps)
        if upgrade:
            content['identity_revision'] = deepcopy(upgrade)
            content['derived_graph_sha256'] = canonical_json_sha256(derived_graph)
        editor_pin = (row.stage_receipts or {}).get('editor_source') or {}
        editor_current = not content.get('inventory_derivation') or editor_pin.get('template_profile') == content.get('profile')
        editor_model = db.get(SystemModel, editor_pin.get('system_model_id')) if editor_pin else None
        editor_revision = db.get(SystemRevision, editor_pin.get('revision_id')) if editor_pin else None
        if editor_pin and (not editor_model or not editor_revision or
                           editor_revision.system_model_id != editor_model.id or
                           editor_model.application_id != editor_pin.get('application_id') or
                           editor_model.upstream_project_id != editor_pin.get('engine_project_id') or
                           editor_model.upstream_version != editor_pin.get('engine_version') or
                           editor_revision.content_sha256 != editor_pin.get('revision_content_sha256') or
                           (editor_current and not same_pinned_model(editor_revision.graph_snapshot, derived_graph))):
            fail('SEED_TEMPLATE_EDITOR_SOURCE_CHANGED', '模板编辑源版本的固定身份已变化。')
        if not editor_current:
            editor_pin, editor_model, editor_revision = {}, None, None
        item = {'id': row.id, 'title': profile[0]['title'] if profile else app.name, 'version': profile[0]['version'] if profile else row.seed_version,
            'template_sha256': canonical_json_sha256(content), 'seed_id': row.seed_id,
            'installed_application_id': app.id,
            'source_application_id': editor_model.application_id if editor_model else app.id,
            'source_model_id': editor_model.id if editor_model else model.id,
            'source_revision_id': editor_revision.id if editor_revision else (model.upstream_receipt or {}).get('base_revision_id'),
            'process_count': len(model.graph_snapshot.get('nodes', [])),
            'field_count': len(inventory_fields(model.graph_snapshot)), 'capabilities': capabilities}
        release_catalog = getattr(self.c, 'release_catalog', None)
        if release_catalog and release_catalog.seed_title(row):
            item['title'] = release_catalog.seed_title(row)
            # The declared projection travels with the canonical name so a reader can fall back to
            # the real name instead of inventing a translation for a language the release did not author.
            declared = release_catalog.seed_display_name(row)
            if declared:
                item['display_name'] = declared
        return row, model, app, content, item, registrations

    def ensure_editor_source(self, installation_id):
        """Pin a separate editable instance to the reviewed flow identities in Nebula LCA."""
        with self.c.database.session() as db:
            row, source, _, definition, item, _ = self._source(db, installation_id)
            if not definition.get('identity_revision'):
                return 'replayed', {'installation_id': row.id, 'system_model_id': source.id}
            if ((row.stage_receipts or {}).get('editor_source') and
                    (not definition.get('inventory_derivation') or
                     row.stage_receipts['editor_source'].get('template_profile') == definition.get('profile'))):
                editor = (row.stage_receipts or {})['editor_source']
                exact = self.c.client.get_provider_model_snapshot(editor['engine_project_id'], editor['engine_version']).payload
                model = db.get(SystemModel, editor['system_model_id'])
                if exact['graph_hash'] != editor['engine_graph_hash'] or not same_pinned_model(model.graph_snapshot, exact['graph']):
                    fail('SEED_TEMPLATE_EDITOR_SOURCE_CHANGED', '算法服务中的模板编辑源版本与固定记录不一致。')
                if pin_editor_model_receipt(model, exact, editor):
                    db.commit()
                return 'replayed', deepcopy(editor)
            project_id = source.upstream_project_id
            project_key = uuid5(NAMESPACE_URL, f'nebula-one:template-editor:{row.seed_id}:{row.seed_version}:{definition["profile"]["content_sha256"]}')
        created = self.create(installation_id, SeedProjectCreate(
            name=f'{item["title"]} · 建模源', project_key=project_key,
            expected_template_sha256=item['template_sha256']))
        with self.c.database.session() as db:
            revision = db.get(SystemRevision, created['revision_id'])
            graph = deepcopy(revision.graph_snapshot)
        exact = None
        for version in sorted(self.c.client.list_project_versions(project_id), key=lambda value: value['version']):
            candidate = self.c.client.get_provider_model_snapshot(project_id, version['version']).payload
            if same_editor_source_graph(graph, candidate['graph']):
                exact = candidate
                break
        if exact is None:
            saved = self.c.client.create_model_version(project_id=project_id, graph=graph, compile_pts_on_save=False).payload
            exact = self.c.client.get_provider_model_snapshot(project_id, saved['version']).payload
            if not same_editor_source_graph(graph, exact['graph']):
                fail('SEED_TEMPLATE_EDITOR_SOURCE_CHANGED', '算法服务未保留已审阅的模板流身份。')
        with self.c.database.session() as db:
            row = db.get(SeedInstallation, installation_id)
            model = db.get(SystemModel, created['system_model_id'])
            revision = db.get(SystemRevision, created['revision_id'])
            if not row or not model or not revision or not same_editor_source_graph(revision.graph_snapshot, exact['graph']):
                fail('SEED_TEMPLATE_EDITOR_SOURCE_CHANGED', '模板编辑源版本的本地固定记录不一致。')
            receipt = {'application_id': created['application_id'],
                       'system_model_id': model.id, 'revision_id': revision.id,
                       'revision_content_sha256': revision.content_sha256,
                       'engine_project_id': project_id, 'engine_version': exact['version'],
                       'engine_graph_hash': exact['graph_hash'], 'template_profile': definition.get('profile')}
            model.upstream_version = exact['version']
            model.graph_snapshot = deepcopy(exact['graph'])
            model.graph_sha256 = canonical_graph_sha256(exact['graph'])
            pin_editor_model_receipt(model, exact, receipt)
            previous_receipts = deepcopy(row.stage_receipts or {})
            previous_editor = previous_receipts.get('editor_source')
            if previous_editor and previous_editor != receipt:
                previous_receipts['editor_source_history'] = [*previous_receipts.get('editor_source_history', []), previous_editor]
            row.stage_receipts = {**previous_receipts, 'editor_source': deepcopy(receipt)}
            db.commit()
            return 'executed', receipt

    def catalog(self):
        with self.c.database.session() as db:
            rows = list(db.scalars(select(SeedInstallation).where(SeedInstallation.status == 'ready',
                SeedInstallation.engine_base_url == self.c.client.base_url,
                SeedInstallation.application_id.is_not(None), SeedInstallation.system_model_id.is_not(None))))
            release_catalog = getattr(self.c, 'release_catalog', None)
            return {'items': [self._source(db, row.id)[4] for row in rows
                              if not release_catalog or release_catalog.allows_seed(row)]}

    def ensure_demo_project(self, seed, version, bundle_content_sha256, key, display_name):
        """Create the one example project a fresh release shows, through the ordinary create path.

        Nothing here is a second data set: it is the same template instance a visitor would create
        by hand, declared once so the first screen has something openable.
        """
        with self.c.database.session() as db:
            row = db.scalar(select(SeedInstallation).where(
                SeedInstallation.seed_id == seed, SeedInstallation.seed_version == version,
                SeedInstallation.bundle_content_sha256 == bundle_content_sha256,
                SeedInstallation.status == 'ready',
                SeedInstallation.engine_base_url == self.c.client.base_url))
            if row is None:
                fail('SEED_TEMPLATE_SOURCE_UNAVAILABLE', '示例项目要求的精确种子尚未就绪。', 409,
                     seed=seed, version=version, bundle_content_sha256=bundle_content_sha256)
            _, _, _, _, item, _ = self._source(db, row.id)
            project_key = demo_project_key(key)
            replayed = db.get(Application, project_application_id(project_key, row.id)) is not None
        name = str(display_name.get('zh') or next(iter(display_name.values()), '')).strip()
        if not name:
            fail('SEED_DEMO_PROJECT_NAME_MISSING', '示例项目缺少可显示的简短名称。', 422)
        created = self.create(row.id, SeedProjectCreate(
            name=name, project_key=project_key, expected_template_sha256=item['template_sha256']),
            resource_purpose=DEMO_PROJECT, display_name=display_name)
        return ('replayed' if replayed else 'executed'), {**created, 'seed_id': seed,
            'seed_version': version, 'display_name': dict(display_name)}

    def create(self, installation_id, payload, *, resource_purpose=None, display_name=None):
        app_id = project_application_id(payload.project_key, installation_id)
        with self.c.database.session() as db:
            release_catalog = getattr(self.c, 'release_catalog', None)
            row = db.get(SeedInstallation, installation_id)
            if release_catalog and (row is None or not release_catalog.allows_seed(row)):
                fail('SEED_TEMPLATE_UNAVAILABLE', '此模板不在当前发布目录。', 404)
            row, source, source_app, definition, item, registrations = self._source(db, installation_id)
            if payload.expected_template_sha256 != item['template_sha256']:
                fail('SEED_TEMPLATE_CHANGED', '模板版本已变化，请重新选择。')
            request_hash = canonical_json_sha256(payload.model_dump(mode='json'))
            existing = db.get(Application, app_id)
            if existing:
                if existing.context.get('project_create_sha256') != request_hash:
                    fail('SEED_PROJECT_KEY_CONFLICT', '此创建请求已经用于另一个项目。')
                model = db.scalar(select(SystemModel).where(SystemModel.application_id == app_id))
                return {'application_id': app_id, 'system_model_id': model.id, 'revision_id': model.upstream_receipt['base_revision_id']}
            exact = self.c.client.get_provider_model_snapshot(source.upstream_project_id, source.upstream_version).payload
            if not same_pinned_model(source.graph_snapshot, exact['graph']):
                fail('SEED_TEMPLATE_MODEL_CHANGED', '上游模型与已验证模板不一致。')
            fu = exact['functional_unit']
            if not fu.get('flow_uuid') or not fu.get('unit') or not fu.get('amount'):
                fail('SEED_TEMPLATE_PRODUCT_MISSING', '模板缺少明确的参考产品。')
            products = [p for n in source.graph_snapshot.get('nodes', []) for p in n.get('outputs', [])
                        if p.get('isProduct') and p.get('flowUuid') == fu['flow_uuid'] and p.get('unit') == fu['unit']]
            if len(products) != 1 or not all(products[0].get(k) for k in ('unitGroupUuid', 'unitGroupVersion')):
                fail('SEED_TEMPLATE_PRODUCT_IDENTITY_MISSING', '模板参考产品的精确单位身份不完整或不唯一。')
            demand = [{'reference_flow_uuid': fu['flow_uuid'], 'amount': fu['amount'], 'unit': fu['unit'],
                       'unit_group_uuid': products[0]['unitGroupUuid'], 'unit_group_version': products[0]['unitGroupVersion']}]
            model_id, revision_id = new_id(), new_id()
            context = {**deepcopy(definition['source_context']), 'template_locked': True,
                'seed_template': {**definition, 'installation_id': row.id, 'title': item['title'],
                    **({'title_display': item['display_name']} if item.get('display_name') else {}),
                    'template_sha256': item['template_sha256'], 'demand': demand},
                'project_capabilities': definition['capabilities'], 'project_create_sha256': request_hash}
            if resource_purpose:
                context['resource_purpose'] = resource_purpose
            if display_name:
                context['display_name'] = dict(display_name)
            app = Application(id=app_id, name=payload.name, application_type=source_app.application_type,
                description=source_app.name, context=context)
            graph = apply_template_revision(source.graph_snapshot, definition.get('identity_revision'))
            from .inventory_derivation import derive_inventory
            graph, _ = derive_inventory(graph, definition.get('inventory_derivation'))
            revision_graph_hash = canonical_json_sha256(graph) if definition.get('identity_revision') else source.graph_sha256
            receipt = {**deepcopy(source.upstream_receipt), 'base_revision_id': revision_id,
                'template_source_model_id': source.id, 'seed_template_sha256': item['template_sha256']}
            model = SystemModel(id=model_id, application_id=app_id, name=source.name, provider=source.provider,
                provider_base_url=source.provider_base_url, upstream_project_id=source.upstream_project_id,
                upstream_version=source.upstream_version, graph_sha256=source.graph_sha256,
                graph_snapshot=deepcopy(source.graph_snapshot), upstream_receipt=receipt)
            revision = SystemRevision(id=revision_id, system_model_id=model_id, revision_number=1,
                label='模板初始数据', revision_kind='base', graph_sha256=revision_graph_hash,
                content_sha256=canonical_content_sha256(graph, context), graph_snapshot=graph,
                application_context=context, status='draft')
            db.add(app)
            db.flush()
            db.add(model)
            db.flush()
            db.add(revision)
            for package, digest in registrations:
                existing_package = db.scalar(select(MethodPackage).where(MethodPackage.package_id == package.package_id, MethodPackage.version == package.version))
                if existing_package and existing_package.content_sha256 != digest:
                    fail('METHOD_PACKAGE_VERSION_CONFLICT', '同一方法版本已登记不同内容。')
                if not existing_package:
                    db.add(MethodPackage(**package.model_dump(mode='python'), content_sha256=digest, status='registered'))
            period_map = {}
            for p in db.scalars(select(Period).where(Period.application_id == source_app.id)):
                pid = new_id()
                period_map[p.id] = pid
                db.add(Period(id=pid, application_id=app_id, key=p.key, name=p.name,
                    start_date=p.start_date, end_date=p.end_date, resolution=p.resolution))
            db.flush()
            boundary_ids = []
            for b in db.scalars(select(BoundaryDefinition).where(BoundaryDefinition.application_id == source_app.id,
                                                               BoundaryDefinition.status == 'frozen')):
                content = {k: deepcopy(getattr(b, k)) for k in BOUNDARY_FIELDS}
                content['period_id'] = period_map.get(b.period_id)
                content['method_package_ref'] = definition['method_replacements'].get(b.method_package_ref, b.method_package_ref)
                if content['boundary_type'] == 'cbam_trial' and definition.get('boundary_revision'):
                    boundary_revision = deepcopy(definition['boundary_revision'])
                    exchange_revisions = boundary_revision.pop('exchange_revisions', [])
                    for replacement in exchange_revisions:
                        rows = [row for key in ('included_flow_rules', 'excluded_items') for row in content[key]
                                if row.get('exchange_id') == replacement['exchange_id']]
                        if len(rows) != 1:
                            fail('SEED_TEMPLATE_BOUNDARY_EXCHANGE_MISMATCH', 'Boundary revision must match one exact exchange.')
                        rows[0].update(deepcopy(replacement))
                    content['consolidation_policy'] = {**content.get('consolidation_policy', {}), **boundary_revision}
                if content['geographic_scope'].get('graph_sha256'):
                    content['geographic_scope']['graph_sha256'] = revision_graph_hash
                boundary_id = new_id()
                boundary_ids.append(boundary_id)
                db.add(BoundaryDefinition(id=boundary_id, application_id=app_id, **content,
                    content_sha256=canonical_json_sha256(content), status='frozen', frozen_at=utcnow()))
            context = deepcopy(context)
            context['seed_template']['boundary_ids'] = boundary_ids
            app.context = deepcopy(context)
            revision.application_context = deepcopy(context)
            revision.content_sha256 = canonical_content_sha256(graph, context)
            from .official_product_method import (bind_official_product_method,
                bind_official_organization_method, bind_official_cbam_partial_method,
                bind_official_organization_lifecycle_method)
            for bind in (bind_official_product_method, bind_official_organization_method,
                         bind_official_cbam_partial_method, bind_official_organization_lifecycle_method):
                bind(db, app)
            revision.application_context = deepcopy(app.context)
            revision.content_sha256 = canonical_content_sha256(graph, revision.application_context)
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                fail('SEED_PROJECT_CREATE_CONFLICT', '同一项目正在创建，请重试。')
            return {'application_id': app_id, 'system_model_id': model_id, 'revision_id': revision_id}

    def read(self, application, revision, template=None, language='zh'):
        # The shared inventory read: a template instance passes nothing and reads its own seed
        # template, while a model returned from professional modelling injects a computed view so the
        # same field/port contract is used without pretending the return is an installed seed record.
        template = template or application.context['seed_template']
        inputs = revision.application_context.get('project_inputs', {})
        # A project keeps the display projection its own template version was created with;
        # only revisions validated from 1.1.1 on carry the upstream bilingual projection.
        labels = display_labels(template.get('identity_revision', {}).get('content', {})
                                 .get('display_metadata', []), language)
        catalog_labels, display_issues = exact_flow_labels(self.c.client, revision.graph_snapshot, language)
        labels = {**catalog_labels, **labels}
        graph, case_sources = display_project_graph(revision.graph_snapshot, self.c.settings.casepack_roots, language, labels)
        fields = inventory_fields(graph)
        ports = list_background_ports(graph)
        for field in fields:
            key = f"{field['process_id']}::{field['port_id']}"
            if key in labels and 'source_label' not in field:
                field['label'] = labels[key]
        for port in ports:
            field = next((f for f in fields if f"{f['process_id']}::{f['port_id']}" == port['exchange_id']), None)
            if field:
                port['label'] = field['label']
        mapped = inputs.get('mapped_background_process_pins', [])
        providers = {str(pin.get('process_uuid') or '') for pin in mapped} - {''}
        # The pinned native climate contract answers mapped providers without bare provider pins.
        native_climate = None if not mapped else {'available': bool(providers)
            and not inputs.get('background_process_pins') and not inputs.get('project_background_pins'), 'provider_count': len(providers)}
        return {'application_id': application.id, 'revision_id': revision.id,
            'content_sha256': revision.content_sha256,
            'template_title': pick_name(template.get('title_display') or {}, language) or template['title'],
            'fields': fields, 'process_graph': process_graph_projection(graph),
            'flow_display_issues': display_issues,
            'case_display_sources': case_sources,
            'demand': inputs.get('demand', template['demand']),
            'demand_mode': inputs.get('demand_mode', 'explicit'),
            'source': inputs.get('source', template.get('source_default', '模板示例值（未经实测）')),
            'saved': bool(inputs),
            'capabilities': list(dict.fromkeys([*template['capabilities'],
                *(application.context.get('project_capabilities') or [])])),
            'blocked_capabilities': template.get('blocked_capabilities', []),
            'native_climate': native_climate,
            'native_inventory': None if native_climate is None else {
                'available': native_climate['available'] and len(providers) == 1
                    and bool(self.c.settings.native_inventory_contract_file),
                'provider_count': native_climate['provider_count'],
            },
            'background_options': [], 'background_note': '背景过程须与投入流的身份、版本和单位一致。已关联的背景数据随当前数据版本保存。',
            'background_ports': ports,
            'background_process_pins': inputs.get('background_process_pins', []),
            'mapped_background_process_pins': inputs.get('mapped_background_process_pins', []),
            'project_background_pins': inputs.get('project_background_pins', []),
            'model_processing_rules_ref': inputs.get('model_processing_rules_ref'),
            'inventory_editing': True}

    def save(self, application, parent, payload, language='zh'):
        template = application.context['seed_template']
        revision = apply_inventory_inputs(self.c, parent, payload, template['demand'],
            idempotency_prefix='seed-input', label='实景清单')
        # The classification stays fixed; each changed graph receives a new boundary pin.
        # Retrying a save also completes this step if a previous request was interrupted.
        with self.c.database.session() as db:
            originals = [b for b in db.scalars(select(BoundaryDefinition).where(
                BoundaryDefinition.application_id == application.id, BoundaryDefinition.status == 'frozen'))
                if b.id in template['boundary_ids'] and b.geographic_scope.get('graph_sha256')]
            contents = [{k: deepcopy(getattr(b, k)) for k in BOUNDARY_FIELDS} for b in originals]
        for content in contents:
            content['name'] += f' / {revision.id}'
            content['geographic_scope']['graph_sha256'] = revision.graph_sha256
            self.c.seed_installation._freeze_boundary(application.id, content)
        return self.read(application, revision, template, language)
