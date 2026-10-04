"""Versioned release defaults, applied only to a pristine official example."""
from sqlalchemy import select

from ..models import SystemRevision
from ..release_resources import DEMO_PROJECT
from .public_supply_seed import ensure_public_supply_seed
from .project_user_background import ProjectUserBackgroundService, UserBackgroundSelection
from .project_workspace import ProjectWorkspaceService, ProjectInputs
from ..seeds.standard_seed_bundle import REPO_ROOT


def ensure_demo_backgrounds(container, created, declarations):
    application = container.applications.get(created['application_id'])
    with container.database.session() as db:
        revisions = list(db.scalars(select(SystemRevision).where(
            SystemRevision.system_model_id == created['system_model_id'])))
    if (application.context.get('resource_purpose') != DEMO_PROJECT or len(revisions) != 1
            or revisions[0].revision_kind != 'base'
            or revisions[0].application_context.get('project_inputs')):
        return {'outcome': 'preserved_existing_inputs'}
    revision = revisions[0]
    workspace_service = ProjectWorkspaceService(container)
    workspace = workspace_service.read(application.id, revision.id)
    pins = []
    for declaration in declarations:
        _, supply = ensure_public_supply_seed(container.client,
            path=REPO_ROOT / declaration['path'], declared_hash=declaration['content_sha256'],
            seed_id=declaration['seed_id'], seed_version=declaration['version'])
        for exchange_id in declaration['consumer_exchange_ids']:
            resolved = ProjectUserBackgroundService(container.client).resolve(revision.graph_snapshot,
                UserBackgroundSelection(consumer_exchange_id=exchange_id,
                    project_id=supply['project_id'], version=supply['version']))
            pins.append(resolved['pin'])
    saved = workspace_service.save(application.id, ProjectInputs(
        revision_id=revision.id, expected_content_sha256=workspace['content_sha256'],
        amounts=[item['amount'] for item in workspace['demand']], demand_mode='reference_output',
        values={field['key']: field['value'] for field in workspace['fields'] if not field['linked']},
        project_background_pins=pins, source='Versioned official example background defaults'))
    return {'outcome': 'initialized', 'revision_id': saved['revision_id'],
            'project_background_pins': saved['project_background_pins']}
