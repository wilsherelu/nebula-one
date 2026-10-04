"""A release boot's project list shows projects, not the records that hold a seed."""
from __future__ import annotations

import pytest

from nebula_one.config import Settings
from nebula_one.database import Database
from nebula_one.models import Application, SeedInstallation
from nebula_one.profiles import ApplicationProfiles
from nebula_one.release_resources import (
    DEFAULT_LANGUAGE, display_labels, display_name_of, internal_application_ids,
    pick_name, read_language,
)
from nebula_one.services.applications import ApplicationService


@pytest.fixture()
def database(tmp_path):
    engine = Database(Settings(database_url=f"sqlite:///{(tmp_path / 'release.db').as_posix()}"))
    engine.create_schema()
    yield engine
    engine.dispose()


@pytest.fixture()
def service(database) -> ApplicationService:
    return ApplicationService(database, ApplicationProfiles())


def _installation(database, application_id, editor_application_id=None) -> None:
    with database.session() as db:
        db.add(SeedInstallation(
            id=f"install-{application_id}", seed_id="nebula.iron-steel.bf-bof-crude-steel",
            seed_version="1.1.0", install_key=f"key-{application_id}",
            bundle_content_sha256="0" * 64, engine_base_url="http://engine.test",
            engine_db_digest="d" * 32, engine_openapi_version="1", status="ready",
            application_id=application_id,
            stage_receipts={"editor_source": {"application_id": editor_application_id}}
            if editor_application_id else {}))
        db.commit()


def _application(database, application_id, **context) -> None:
    with database.session() as db:
        db.add(Application(id=application_id, name=application_id, application_type="cbam",
                           context=context))
        db.commit()


def test_the_seed_and_its_modeling_source_are_not_projects(database, service) -> None:
    _application(database, "seed-record")
    _application(database, "modeling-source")
    _application(database, "visitor-example", resource_purpose="demo_project")
    _installation(database, "seed-record", editor_application_id="modeling-source")
    with database.session() as db:
        assert internal_application_ids(db) == {"seed-record", "modeling-source"}
    assert [record.id for record in service.list()] == ["visitor-example"]


def test_a_project_created_from_a_template_stays_visible(service, database) -> None:
    _application(database, "own-project")
    assert [record.id for record in service.list()] == ["own-project"]


def test_historical_and_unrecorded_internal_editor_sources_stay_hidden(database, service):
    from uuid import NAMESPACE_URL, uuid5
    from nebula_one.services.seed_projects import project_application_id
    _application(database, 'seed-record')
    _application(database, 'current-editor')
    _application(database, 'old-editor')
    _installation(database, 'seed-record', 'current-editor')
    template = {'seed_id': 'steel', 'seed_version': '1.1.0',
                'installation_id': 'install-seed-record', 'profile': {'content_sha256': 'a' * 64}}
    key = uuid5(NAMESPACE_URL, f"nebula-one:template-editor:steel:1.1.0:{'a' * 64}")
    recovered_id = project_application_id(key, template['installation_id'])
    _application(database, recovered_id, seed_template=template)
    _application(database, 'user-with-same-template', seed_template=template)
    with database.session() as db:
        row = db.get(SeedInstallation, 'install-seed-record')
        row.stage_receipts = {**row.stage_receipts,
                              'editor_source_history': [{'application_id': 'old-editor'}]}
        db.commit()
    assert [record.id for record in service.list()] == ['user-with-same-template']


def test_a_requested_language_name_falls_back_to_a_name_that_exists() -> None:
    class Holder:
        context = {"display_name": {"zh": "钢铁示例"}}

    assert display_name_of(Holder(), "zh") == "钢铁示例"
    assert display_name_of(Holder(), "en") == "钢铁示例"
    assert display_name_of(Holder(), None) == "钢铁示例"

    class Untagged:
        context = {}

    assert display_name_of(Untagged(), "en") is None


def test_the_requested_language_falls_back_to_the_release_default() -> None:
    assert read_language("EN") == "en"
    assert read_language("  zh ") == "zh"
    assert read_language("fr") == DEFAULT_LANGUAGE
    assert read_language(None) == DEFAULT_LANGUAGE


def test_pick_name_prefers_the_language_and_never_invents_one() -> None:
    names = {"zh": "高炉—转炉钢铁", "en": "Blast furnace – BOF steel"}
    assert pick_name(names, "en") == "Blast furnace – BOF steel"
    assert pick_name(names, "zh") == "高炉—转炉钢铁"
    assert pick_name({"zh": "", "en": "Only English"}, "zh") == "Only English"
    assert pick_name({}, "zh") is None


def test_exchange_labels_read_the_pinned_projection_in_the_requested_language() -> None:
    records = [
        {"exchange_id": "a::power", "name_zh": "区域电力", "name_en": "Regional power mix"},
        {"exchange_id": "a::ore", "name_zh": "铁矿石", "name_en": ""},
        {"name_zh": "no exchange id"},
    ]
    assert display_labels(records, "en") == {"a::power": "Regional power mix", "a::ore": "铁矿石"}
    assert display_labels(records, "zh") == {"a::power": "区域电力", "a::ore": "铁矿石"}
    assert display_labels(None, "zh") == {}
