"""One owns the handoff; browser callbacks are untrusted version candidates."""
from copy import deepcopy
from datetime import timedelta, timezone
from hashlib import sha256
import hmac
import secrets
from urllib.parse import quote, urlencode, urlsplit

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, update

from ..adapters.nebula_lca import same_pinned_model
from ..errors import DomainError
from ..hashing import canonical_content_sha256, canonical_graph_sha256, canonical_json_sha256
from ..models import Application, ModelingHandoff, ModelSource, SeedInstallation, SystemModel, SystemRevision, new_id, utcnow
from ..runtime_models import MethodPackage
from .model_processing_runtime import reviewed_template_profile


class HandoffStart(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=255)
    base_model_id: str | None = Field(default=None, min_length=1, max_length=36)
    base_revision_id: str | None = Field(default=None, min_length=1, max_length=36)


class HandoffCredentials(BaseModel):
    model_config = ConfigDict(extra="forbid")
    state: str = Field(min_length=20, max_length=128)
    confirmation_token: str = Field(min_length=20, max_length=128)


class HandoffCandidate(HandoffCredentials):
    project_id: str = Field(min_length=1, max_length=255, pattern=r"^[A-Za-z0-9_-]+$")
    base_version: int | None = Field(default=None, gt=0, strict=True)
    saved_version: int = Field(gt=0, strict=True)
    upstream_graph_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


def digest(value: str) -> str:
    return sha256(value.encode()).hexdigest()


def refuse(code: str, message: str, status: int = 409):
    raise DomainError(code=code, message=message, status_code=status)


class ModelingHandoffService:
    def __init__(self, container):
        self.c = container

    def configuration(self):
        raw = self.c.settings.nebula_lca_editor_url
        parsed = urlsplit(raw or "")
        ready = bool(parsed.scheme in ("http", "https") and parsed.netloc and not parsed.username
                     and not parsed.password and not parsed.query and not parsed.fragment)
        return {"schema_version": "nebula_one.modeling-handoff.v1", "available": ready,
                "editor_url": raw.rstrip("/") + "/" if ready else None,
                "message": "在 Nebula LCA 中建模，保存后返回确认分析版本。" if ready else "专业建模暂不可用，请联系管理员检查服务连接。"}

    def _template_binding_of(self, model: SystemModel):
        """The reviewed template a base project was bound to, with the revision that says so.

        What comes back from the editor is an edit of that base, so the rules reviewed against the
        base's template are the ones that turn it into a calculation model. Without this record the
        returned project names a purpose it cannot resolve rules for, which is why the whole-plant
        extension could never reach an accounting purpose through the formal return flow.
        """
        with self.c.database.session() as db:
            application = db.get(Application, model.application_id)
            base_revision_id = (model.upstream_receipt or {}).get("base_revision_id")
            revision = db.get(SystemRevision, base_revision_id) if base_revision_id else None
            if revision is not None and revision.system_model_id != model.id:
                revision = None
        profile = reviewed_template_profile(application, revision)
        installation = None
        if profile is None:
            # The catalog's "修改模板" opens its installed source model, not an already
            # materialized project instance. Resolve only that exact ready installation;
            # a bare imported model cannot claim a reviewed template by name.
            from .seed_projects import SeedProjectService

            with self.c.database.session() as db:
                matches = list(db.scalars(select(SeedInstallation).where(
                    SeedInstallation.system_model_id == model.id,
                    SeedInstallation.application_id == model.application_id,
                    SeedInstallation.engine_base_url == self.c.client.base_url,
                    SeedInstallation.status == "ready",
                )))
                if len(matches) > 1:
                    refuse("MODELING_TEMPLATE_AMBIGUOUS", "源模型对应多个已验证模板安装记录。")
                if not matches:
                    return None
                installation = matches[0]
                _, _, _, definition, item, _ = SeedProjectService(self.c)._source(db, installation.id)
                profile = definition.get("profile")
                if profile is None:
                    return None
                display_metadata = deepcopy((definition.get("identity_revision") or {}).get("content", {}).get("display_metadata", []))
        binding = {"profile": profile, "bound_model_id": model.id}
        from .inventory_derivation import recipe_of
        source_context = revision.application_context if revision is not None else (application.context if application else {})
        recipe = recipe_of(source_context) or (definition.get("inventory_derivation") if installation is not None else None)
        if recipe:
            binding["inventory_derivation"] = deepcopy(recipe)
        if installation is not None:
            binding["source_installation_id"] = installation.id
            binding["template_sha256"] = item["template_sha256"]
            binding["display_metadata"] = display_metadata
        if revision is not None:
            binding["bound_revision_id"] = revision.id
            binding["bound_content_sha256"] = revision.content_sha256
        return binding

    def start(self, payload: HandoffStart):
        if not self.configuration()["available"]:
            refuse("MODELING_EDITOR_NOT_CONFIGURED", "专业建模入口尚未配置。", 503)
        if payload.base_revision_id and not payload.base_model_id:
            refuse("MODELING_BASE_REVISION_INVALID", "所选数据版本缺少基础模型。")
        base = {}
        if payload.base_model_id:
            model = self.c.system_models.get(payload.base_model_id)
            if model.provider_base_url.rstrip("/") != self.c.client.base_url:
                old_url = model.provider_base_url.rstrip("/")
                if old_url not in self.c.settings.nebula_lca_trusted_source_urls:
                    refuse("MODELING_ENGINE_CHANGED", "模型来自另一算法服务，不能在当前服务中编辑。")
                verified = self.c.client.get_provider_model_snapshot(model.upstream_project_id, model.upstream_version).payload
                if not same_pinned_model(model.graph_snapshot, verified["graph"]):
                    refuse("MODELING_BASE_CHANGED", "当前算法服务中的基础模型与原版本不一致。")
                with self.c.database.session() as db:
                    current = db.get(SystemModel, model.id)
                    if current is None or current.provider_base_url.rstrip("/") != old_url:
                        refuse("MODELING_ENGINE_CHANGED", "模型连接已变化，请重新进入。")
                    receipt = deepcopy(current.upstream_receipt or {})
                    history = list(receipt.get("verified_engine_connections") or [])
                    history.append({"previous_base_url": old_url, "current_base_url": self.c.client.base_url,
                                    "project_id": model.upstream_project_id, "version": model.upstream_version,
                                    "graph_hash": verified["graph_hash"]})
                    receipt["verified_engine_connections"] = history
                    current.upstream_receipt = receipt
                    current.provider_base_url = self.c.client.base_url
                    db.commit()
                model.provider_base_url = self.c.client.base_url
            snapshot = self.c.client.get_provider_model_snapshot(model.upstream_project_id, model.upstream_version).payload
            if not same_pinned_model(model.graph_snapshot, snapshot["graph"]):
                refuse("MODELING_BASE_CHANGED", "上游版本与项目保存的模型内容不一致。")
            base = {"project_id": model.upstream_project_id, "version": model.upstream_version,
                    "upstream_graph_hash": snapshot["graph_hash"], "model_id": model.id}
            binding = self._template_binding_of(model)
            if binding is not None:
                base["template_binding"] = binding
            if payload.base_revision_id:
                with self.c.database.session() as db:
                    selected_revision = db.get(SystemRevision, payload.base_revision_id)
                    if selected_revision is None or selected_revision.system_model_id != model.id:
                        refuse("MODELING_BASE_REVISION_INVALID", "所选数据版本不属于基础模型。")
                    base["selected_revision_id"] = selected_revision.id
                    base["selected_revision_sha256"] = selected_revision.content_sha256
                    rules_ref = ((selected_revision.application_context or {}).get("project_inputs") or {}).get("model_processing_rules_ref")
                    if rules_ref is not None:
                        base["model_processing_rules_ref"] = deepcopy(rules_ref)
        state, confirmation = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        record = ModelingHandoff(id=new_id(), name=payload.name, state_sha256=digest(state),
            confirmation_sha256=digest(confirmation), engine_base_url=self.c.client.base_url,
            base_identity=base, expires_at=utcnow() + timedelta(hours=2))
        with self.c.database.session() as db:
            db.add(record)
            db.commit()
        query = {"handoff_id": record.id, "state": state, "return_target": "nebula_one"}
        path = "/"
        if base:
            path = f"/projects/{quote(base['project_id'], safe='')}"
            query["version"] = str(base["version"])
        return {"handoff_id": record.id, "state": state, "confirmation_token": confirmation,
                "expires_at": record.expires_at.isoformat(),
                "editor_url": self.c.settings.nebula_lca_editor_url.rstrip("/") + path + "?" + urlencode(query)}

    def _read(self, db, handoff_id, credentials):
        row = db.get(ModelingHandoff, handoff_id)
        if row is None or not hmac.compare_digest(row.state_sha256, digest(credentials.state)) or not hmac.compare_digest(row.confirmation_sha256, digest(credentials.confirmation_token)):
            refuse("MODELING_HANDOFF_INVALID", "建模会话不匹配，请从发起建模的浏览器返回。", 403)
        if row.expires_at.replace(tzinfo=timezone.utc) < utcnow():
            refuse("MODELING_HANDOFF_EXPIRED", "建模会话已过期，请重新发起。", 410)
        if row.engine_base_url != self.c.client.base_url:
            refuse("MODELING_ENGINE_CHANGED", "算法服务配置已改变，请重新发起建模。")
        if row.status == "cancelled":
            refuse("MODELING_HANDOFF_CANCELLED", "本次建模接入已取消。", 410)
        return row

    def _snapshot(self, row, payload):
        base = row.base_identity
        if base and (payload.project_id != base["project_id"] or payload.base_version != base["version"] or payload.saved_version <= base["version"]):
            refuse("MODELING_BASE_MISMATCH", "返回模型必须是从所选版本另存的新版本。")
        if not base and payload.base_version is not None:
            refuse("MODELING_BASE_MISMATCH", "新建模型会话不能携带其他基础版本。")
        snapshot = self.c.client.get_provider_model_snapshot(payload.project_id, payload.saved_version).payload
        if snapshot["graph_hash"] != payload.upstream_graph_hash:
            refuse("MODELING_HASH_MISMATCH", "返回的模型内容与算法服务保存版本不一致。")
        candidate = {"project_id": payload.project_id, "version": payload.saved_version,
                     "upstream_graph_hash": snapshot["graph_hash"],
                     "hydrated_graph_sha256": canonical_graph_sha256(snapshot["graph"])}
        return snapshot, candidate

    def preview(self, handoff_id, payload: HandoffCandidate):
        with self.c.database.session() as db:
            row = self._read(db, handoff_id, payload)
            snapshot, candidate = self._snapshot(row, payload)
            if row.candidate and row.candidate != candidate:
                refuse("MODELING_CANDIDATE_CHANGED", "已确认预览的版本发生变化，请重新发起接入。")
            if row.status != "confirmed":
                changed = db.execute(update(ModelingHandoff).where(ModelingHandoff.id == handoff_id, ModelingHandoff.status == "pending").values(candidate=candidate, status="previewed"))
                if not changed.rowcount:
                    db.refresh(row)
                    if row.status != "previewed" or row.candidate != candidate:
                        refuse("MODELING_HANDOFF_CHANGED", "建模会话已改变，请刷新后重试。")
                db.commit()
            return {"name": row.name, **candidate, "functional_unit": snapshot["functional_unit"],
                    "node_count": len(snapshot["graph"].get("nodes") or []), "issues": snapshot.get("issues") or [],
                    "status": row.status, "result": row.result}

    def confirm(self, handoff_id, payload: HandoffCandidate):
        with self.c.database.session() as db:
            row = self._read(db, handoff_id, payload)
            if row.status == "confirmed":
                if (payload.project_id, payload.saved_version, payload.upstream_graph_hash) != (row.candidate["project_id"], row.candidate["version"], row.candidate["upstream_graph_hash"]):
                    refuse("MODELING_CANDIDATE_CHANGED", "这次建模已经接入了另一版本。")
                return row.result
            if row.status != "previewed":
                refuse("MODELING_PREVIEW_REQUIRED", "请先核验并查看模型版本。")
            snapshot, candidate = self._snapshot(row, payload)
            if row.candidate != candidate:
                refuse("MODELING_CANDIDATE_CHANGED", "模型内容已改变，请重新核验。")
            # Compare-and-set and all three records share one transaction, including retries.
            claimed = db.execute(update(ModelingHandoff).where(ModelingHandoff.id == handoff_id, ModelingHandoff.status == "previewed").values(status="confirming"))
            if not claimed.rowcount:
                db.expire_all()
                current = self._read(db, handoff_id, payload)
                if current.status == "confirmed":
                    return current.result
                refuse("MODELING_CONFIRM_CONFLICT", "另一次确认正在处理，请重试。")
            self.c.profiles.require("system_analysis")
            app_id, model_id, revision_id = new_id(), new_id(), new_id()
            context = {"modeling_handoff_id": row.id, "modeling_source": candidate,
                       "project_capabilities": ["mfa.solved.v1"],
                       "modeling_functional_unit": snapshot["functional_unit"]}
            # `_snapshot` has already refused anything that is not a newer version of the pinned base
            # project, so this is the reviewed template the returned model actually descends from.
            binding = row.base_identity.get("template_binding")
            selected_revision_id = row.base_identity.get("selected_revision_id")
            if selected_revision_id:
                selected_revision = db.get(SystemRevision, selected_revision_id)
                if (selected_revision is None or selected_revision.content_sha256 != row.base_identity.get("selected_revision_sha256")
                        or selected_revision.system_model_id != row.base_identity.get("model_id")):
                    refuse("MODELING_BASE_REVISION_CHANGED", "所选数据版本的固定内容已改变。")
            if isinstance(binding, dict):
                context["modeling_template_binding"] = deepcopy(binding)
                # Only a return that descends from a reviewed template can be filled in the
                # workbench; an unbound model keeps the professional read-only view.
                context["template_locked"] = True
                if row.base_identity.get("model_processing_rules_ref"):
                    context["project_inputs"] = {"model_processing_rules_ref": deepcopy(row.base_identity["model_processing_rules_ref"])}
            graph = snapshot["graph"]
            receipt = {k: v for k, v in snapshot.items() if k != "graph"}
            receipt.update(candidate, base_revision_id=revision_id, modeling_handoff_id=row.id,
                           modeling_base_identity=row.base_identity)
            app = Application(id=app_id, name=row.name, application_type="system_analysis", context=context)
            model = SystemModel(id=model_id, application_id=app_id, name=row.name, provider="nebula_lca",
                provider_base_url=self.c.client.base_url, upstream_project_id=payload.project_id,
                upstream_version=payload.saved_version, graph_sha256=candidate["hydrated_graph_sha256"],
                graph_snapshot=graph, upstream_receipt=receipt)
            revision = SystemRevision(id=revision_id, system_model_id=model_id, revision_number=1,
                label=f"Nebula LCA v{payload.saved_version}", revision_kind="base",
                graph_sha256=candidate["hydrated_graph_sha256"], content_sha256=canonical_content_sha256(graph, context),
                graph_snapshot=graph, application_context=context, status="draft")
            db.add(app)
            db.flush()
            db.add(model)
            db.flush()
            db.add(revision)
            source_content = dict(application_id=app_id, name=row.name, source_type="nebula_project_version",
                provider="nebula_lca", provider_base_url=self.c.client.base_url, status="attached",
                file_name=None, file_sha256=None, upstream_project_id=payload.project_id,
                upstream_version=payload.saved_version, graph_sha256=candidate["hydrated_graph_sha256"],
                import_receipt={"provider_snapshot": receipt}, candidate_versions=[{
                    "project_id": payload.project_id, "version": payload.saved_version,
                    "graph_hash": candidate["hydrated_graph_sha256"]}],
                external_dependencies=[], issues=snapshot.get("issues") or [])
            db.add(ModelSource(system_model_id=model_id, **source_content,
                content_sha256=canonical_json_sha256(source_content), attached_at=utcnow()))
            if binding:
                if binding.get("source_installation_id"):
                    from .seed_projects import SeedProjectService

                    _, installed_source, _, definition, item, registrations = SeedProjectService(self.c)._source(
                        db, binding["source_installation_id"])
                    if (installed_source.id != binding["bound_model_id"] or
                            item["template_sha256"] != binding["template_sha256"] or
                            definition["profile"] != binding["profile"]):
                        refuse("MODELING_TEMPLATE_CHANGED", "已安装模板在建模期间发生变化，请重新发起。")
                    for package, digest in registrations:
                        existing = db.scalar(select(MethodPackage).where(
                            MethodPackage.package_id == package.package_id,
                            MethodPackage.version == package.version))
                        if existing is not None and existing.content_sha256 != digest:
                            refuse("MODELING_TEMPLATE_METHOD_CHANGED", "模板方法包的固定内容已改变。")
                        if existing is None:
                            db.add(MethodPackage(**package.model_dump(mode="python"),
                                                 content_sha256=digest, status="registered"))
                    db.flush()
                from .returned_projects import reference_demand
                from .returned_cbam_binding import bind_reviewed_cbam, register_reviewed_cbam_extension
                from .official_product_method import bind_official_product_method, bind_official_organization_method, bind_official_cbam_partial_method, bind_official_organization_lifecycle_method
                bind_official_product_method(db, app)
                bind_official_organization_method(db, app)
                bind_official_cbam_partial_method(db, app, revision=revision)
                bind_official_organization_lifecycle_method(db, app)
                try:
                    with db.begin_nested():
                        register_reviewed_cbam_extension(db, app, revision)
                        bind_reviewed_cbam(db, app, revision, reference_demand(app, revision),
                                           context.get("project_inputs") or {})
                except DomainError:
                    # The returned graph is still importable; its workbench names the method gap.
                    pass
            result = {"application_id": app_id, "system_model_id": model_id, "revision_id": revision_id}
            row.result, row.status = result, "confirmed"
            db.commit()
            return result

    def cancel(self, handoff_id, payload: HandoffCredentials):
        with self.c.database.session() as db:
            row = self._read(db, handoff_id, payload)
            if row.status == "confirmed":
                refuse("MODELING_ALREADY_CONFIRMED", "项目已接入，不能取消该会话。")
            result = db.execute(update(ModelingHandoff).where(ModelingHandoff.id == handoff_id, ModelingHandoff.status.in_(["pending", "previewed"])).values(status="cancelled"))
            if not result.rowcount:
                refuse("MODELING_HANDOFF_CHANGED", "会话状态已改变。")
            db.commit()
            return {"status": "cancelled"}
