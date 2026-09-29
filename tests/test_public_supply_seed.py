import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from nebula_one.errors import DomainError
from nebula_one.hashing import canonical_json_sha256
from nebula_one.services.public_supply_seed import ensure_public_supply_seed


RESOURCE = Path(__file__).resolve().parents[1] / "src/nebula_one/resources/public_supply/china-grid-co2-2023.v1.json"
DOCUMENT = json.loads(RESOURCE.read_text(encoding="utf-8"))
CONTENT_HASH = canonical_json_sha256(DOCUMENT)


class EditableProjectClient:
    def __init__(self):
        self.project = None
        self.versions = {}
        self.version_writes = 0

    def list_provider_projects(self):
        if self.project is None:
            return []
        return [{"project_id": self.project["project_id"], "name": self.project["name"],
                 "latest_version": max(self.versions, default=None)}]

    def create_provider_project(self, payload):
        self.project = {"project_id": "editable-grid", **payload}
        return SimpleNamespace(payload=self.project)

    def get_provider_project(self, project_id):
        assert project_id == "editable-grid"
        return SimpleNamespace(payload=self.project)

    def mark_provider_supply_resource(self, project_id):
        assert project_id == "editable-grid"
        self.project["status"] = "resource"
        return SimpleNamespace(payload=self.project)

    def list_provider_project_versions(self, project_id):
        assert project_id == "editable-grid"
        return [{"project_id": project_id, "version": version, "graph_hash": canonical_json_sha256(graph)}
                for version, graph in self.versions.items()]

    def create_model_version(self, *, project_id, graph, compile_pts_on_save):
        assert project_id == "editable-grid" and not compile_pts_on_save
        version = max(self.versions, default=0) + 1
        self.versions[version] = deepcopy(graph)
        self.version_writes += 1
        return SimpleNamespace(payload={"version": version})

    def get_provider_model_snapshot(self, project_id, version):
        assert project_id == "editable-grid"
        return SimpleNamespace(payload={"graph": self.versions[version],
                                        "graph_hash": canonical_json_sha256(self.versions[version]),
                                        "source_policy": self.project["source_policy"]})


def _install(client, declared_hash=CONTENT_HASH):
    return ensure_public_supply_seed(client, path=RESOURCE, declared_hash=declared_hash,
                                     seed_id=DOCUMENT["seed_id"], seed_version=DOCUMENT["seed_version"])


def test_seed_replays_without_overwriting_new_editable_version():
    client = EditableProjectClient()
    assert _install(client)[0] == "executed"
    assert client.project["status"] == "resource"
    original = deepcopy(client.versions[1])
    edited = deepcopy(original)
    edited["nodes"][0]["outputs"][1]["amount"] = 0.6
    client.create_model_version(project_id="editable-grid", graph=edited, compile_pts_on_save=False)
    assert _install(client)[0] == "replayed"
    assert client.version_writes == 2
    assert client.versions[1] == original
    assert client.versions[2]["nodes"][0]["outputs"][1]["amount"] == 0.6


def test_seed_refuses_drift_before_writing():
    client = EditableProjectClient()
    with pytest.raises(DomainError, match="content changed"):
        _install(client, declared_hash="0" * 64)
    assert client.project is None
