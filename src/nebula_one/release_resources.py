"""What each boot-created application exists for, so a project list shows only real projects.

A release boot creates more than the example a visitor should open: the installed seed record and
its pinned modeling source are applications too, and an unfiltered list presents them as projects.
Both are already declared by the installation table, so the projection reads that declaration
instead of matching names or capping a list length. The example project the release manifest
creates carries its own purpose and short bilingual display names on its context.
"""

from __future__ import annotations

from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import select

from .models import SeedInstallation

DEMO_PROJECT = "demo_project"
MODELING_SOURCE = "modeling_source"
DEMO_PROJECT_NAMESPACE = uuid5(NAMESPACE_URL, "https://nebula-one.app/demo-project")


def demo_project_key(declared_key: str) -> UUID:
    """One example project per declared key, so a repeated boot replays instead of duplicating."""
    return uuid5(DEMO_PROJECT_NAMESPACE, f"demo-project|{declared_key}")


def internal_application_ids(db) -> set[str]:
    """Application ids that exist to hold a seed or its modeling source, not to be worked in."""
    from .models import SeedInstallation

    internal: set[str] = set()
    for row in db.scalars(select(SeedInstallation)):
        if row.application_id:
            internal.add(row.application_id)
        receipts = row.stage_receipts or {}
        for editor in [receipts.get("editor_source") or {}, *receipts.get("editor_source_history", [])]:
            if editor.get("application_id"):
                internal.add(editor["application_id"])
    # Earlier versions did not keep every replaced editor receipt. Recover only the
    # deterministic internal creation identity; template-created user projects differ.
    from .models import Application
    from .services.seed_projects import project_application_id
    for app in db.scalars(select(Application)):
        context = app.context or {}
        if context.get("resource_purpose") == MODELING_SOURCE:
            internal.add(app.id)
        template = context.get("seed_template") or {}
        profile = template.get("profile") or {}
        if all(template.get(key) for key in ("installation_id", "seed_id", "seed_version")) and profile.get("content_sha256"):
            key = uuid5(NAMESPACE_URL, f'nebula-one:template-editor:{template["seed_id"]}:{template["seed_version"]}:{profile["content_sha256"]}')
            if app.id == project_application_id(key, template["installation_id"]):
                internal.add(app.id)
    return internal


def display_name_of(application, language: str | None = None) -> str | None:
    """Prefer the requested language, fall back to a name that really exists, invent nothing."""
    names = (application.context or {}).get("display_name")
    if not isinstance(names, dict):
        return None
    return pick_name(names, language)


LANGUAGES = ("zh", "en")
DEFAULT_LANGUAGE = "zh"


def read_language(value: str | None) -> str:
    """The interface language a request asked for; an unknown value keeps the release default."""
    lowered = (value or "").strip().lower()
    return lowered if lowered in LANGUAGES else DEFAULT_LANGUAGE


def pick_name(names: dict, language: str | None) -> str | None:
    preferred = str(names.get(language or "") or "").strip()
    if preferred:
        return preferred
    for value in names.values():
        text = str(value or "").strip()
        if text:
            return text
    return None


def display_labels(records, language: str) -> dict[str, str]:
    """Exchange id to the pinned projection in the requested language.

    Both names come from the same pinned upstream flow projection, so choosing between them is a
    read-side view, not a local translation, and never invents a label the data does not carry.
    """
    other = "en" if language == "zh" else "zh"
    labels: dict[str, str] = {}
    for item in records or []:
        exchange_id = item.get("exchange_id")
        if not exchange_id:
            continue
        name = pick_name({"zh": item.get("name_zh"), "en": item.get("name_en")}, language) \
            or str(item.get(f"name_{other}") or "").strip()
        if name:
            labels[exchange_id] = name
    return labels
