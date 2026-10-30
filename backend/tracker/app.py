from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from flask import Flask, g, jsonify, render_template, request, send_file
from werkzeug.exceptions import NotFound
import sqlite3
import re

from tracker.config import load_config
from tracker.database import Database
from tracker.domain import compare_change_sets
from tracker.services.knowledge_documents import (
    knowledge_documents as build_knowledge_documents,
)
from tracker.services.knowledge_items import (
    knowledge_items as build_knowledge_items,
    probe_versions as build_probe_versions,
)
from tracker.services.knowledge_issues import (
    knowledge_issues as build_knowledge_issues,
)
from tracker.services.registration import registration_query
from tracker.services.qa import find_answer, revalidate_structured_answers
from tracker.services.joint_answer import structured_signature
from tracker.seed import TERMS
from tracker.services.import_service import (
    preview_release_notes,
    review_import_candidate,
    stage_release_notes,
)
from tracker.services.product_strategy import (
    ProductStrategyReader,
    ProductStrategySourceUnavailable,
)
from tracker.services.product_states import product_state_options, product_states
from tracker.services.workbench import (
    config_system_entry,
    module_catalog,
    overview_for_project,
    sources_status,
    training_assets,
)
from tracker.services.search_index import SearchIndex
from tracker.services.personal_workspace import PersonalWorkspace
from tracker.services.document_registry import DocumentRegistry
from tracker.services.search_maintenance import SearchMaintenance
from tracker.services.search_prewarm import WhitepaperPrewarmer
from tracker.services.search_intent import located_version
from tracker.services.release_evolution import release_evolution_answer
from tracker.services.illustration_choices import decorate_illustration_choices, save_illustration_choice
from tracker.services.release_review import (ReviewConflict, decorate_release_review, save_release_review,
    list_release_review_history, restore_release_review)
from tracker.services.scenario_queries import probe_answer, feature_answer, version_answer, release_feature_answer, release_fallback_allowed
from tracker.services.description_settings import ModelSettings
from tracker.services.description_model import DescriptionModel
from tracker.services.release_evidence import release_evidence
from tracker.services.model_workspace import build_model_workspace
from tracker.services.document_scope_suggestions import suggest_document_scope
from tracker.services.unified_search import controlled_source_candidates
from tracker.services.unified_search import (
    refresh_search_index,
    resolve_source_candidate,
    search_source_coverage,
    search_version_coverage,
    sync_search_roots_and_metadata,
    unified_search,
    training_source_id,
    training_source_path,
)


def success(data: Any, status: int = 200):
    return jsonify({"success": True, "data": data}), status


def failure(code: str, message: str, status: int = 400, details: Any = None):
    error = {"code": code, "message": message}
    if details is not None:
        error["details"] = details
    return jsonify({"success": False, "error": error}), status


def _payload_text(payload: dict[str, Any], key: str, fallback: Any) -> str:
    """取 JSON 文本字段：未提供与 `null` 一律沿用现有值。

    部分更新（PATCH）里，把「没传」当成「传了空」会静默清空既有内容；
    把 `null` 直接 `str()` 又会写成字面量 `"None"`。两种都按「未提供」处理。
    """
    value = payload.get(key)
    if value is None:
        return str(fallback or "")
    return str(value)


SOURCE_ROOT_KEYS = ("RELEASE_NOTE_ROOT", "CONTROLLED_MATERIALS_ROOT", "TRAINING_ROOT")
"""始终允许被登记为来源目录的只读根。"""


def configured_source_roots(config: Mapping[str, Any]) -> list[Path]:
    """允许登记为来源目录的根：三个固定只读根 + 配置里额外声明的 `source_roots`。"""
    roots = [
        Path(str(config[key])).expanduser().resolve()
        for key in SOURCE_ROOT_KEYS
        if str(config.get(key) or "").strip()
    ]
    roots.extend(
        Path(str(root)).expanduser().resolve()
        for root in (config.get("SOURCE_ROOTS") or [])
        if str(root).strip()
    )
    return roots


def validated_source_root(config: Mapping[str, Any], raw_path: Any) -> str:
    """把网页提交的来源目录限制在**启动时配置的根目录之内**。

    README 的既有约束是「网页不能提交任意文件路径，扫描根目录必须在启动时配置」，
    但接口此前只判断 `is_dir()`：空路径等价于当前工作目录、`../` 与 `~` 也能通过，
    于是一次本该校验失败的请求会把服务进程的 CWD 或任意目录登记成扫描根，随后
    `scan-preview` / `scan` 会真的去读它。这里把约束落到路由上：

    - 空路径不再回落成 `.`，直接拒绝；
    - 相对路径拒绝（配置根本身可以是相对的，但会被解析成绝对路径）；
    - 必须位于 `release_note_root` / `controlled_materials_root` / `training_root` 之内；
    - 一个根都没配置时明确报错，而不是放行任意路径。
    """
    raw = str(raw_path or "").strip()
    if not raw:
        raise ValueError("请填写来源目录；空路径不再被当作当前工作目录。")
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        raise ValueError("来源目录必须是从配置根目录出发的绝对路径。")
    candidate = candidate.resolve()
    roots = configured_source_roots(config)
    if not roots:
        raise ValueError(
            "尚未配置任何来源根目录（release_note_root / controlled_materials_root / "
            "training_root）；请先在 config/local.json 配置并重启后再登记来源。"
        )
    if not any(candidate == root or root in candidate.parents for root in roots):
        raise ValueError(
            "来源目录必须位于启动时配置的根目录之内：" + "、".join(str(root) for root in roots)
        )
    if not candidate.is_dir():
        raise ValueError("来源目录不存在或不是目录。")
    return str(candidate)


def static_asset_version(static_folder: str | None) -> str:
    """静态资源版本号：取样式与脚本的最新修改时间。

    无 Cache-Control 的静态文件会被浏览器启发式缓存，改完样式却看不到效果；
    把 mtime 带进 URL 后，文件一改链接就变，页面刷新即拿到新版。
    """
    newest = 0
    for name in ("styles.css", "embedded.css", "app.js", "workspace.js", "description-settings.js", "description.css"):
        if not static_folder:
            break
        try:
            newest = max(newest, int(Path(static_folder, name).stat().st_mtime))
        except OSError:
            continue
    return str(newest)


def create_app(config: dict[str, Any] | None = None) -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="static")

    @app.context_processor
    def _inject_static_version() -> dict[str, str]:
        return {"static_version": static_asset_version(app.static_folder)}

    settings = load_config()
    app.config.from_mapping(settings.as_flask_config())
    if config:
        app.config.update(config)
    database = Database(app.config["DATABASE_PATH"])
    database.initialize()
    if app.config.get("RELEASE_NOTE_ROOT"):
        database.add_project_source(
            database.default_project_id(),
            str(app.config["RELEASE_NOTE_ROOT"]),
            file_keywords=["ULTIMUS"],
        )
    if not app.config.get("TESTING", False):
        database.seed_terms(TERMS)
    app.extensions["tracker_database"] = database
    personal_workspace = PersonalWorkspace(database.path)
    app.extensions["personal_workspace"] = personal_workspace
    model_settings_path = app.config.get("DESCRIPTION_MODEL_SETTINGS_PATH")
    if model_settings_path is None and app.config.get("TESTING"):
        model_settings_path = database.path.with_suffix(".model.json")
    model_settings = ModelSettings(Path(model_settings_path) if model_settings_path else None)
    description_model = DescriptionModel(model_settings)
    app.extensions["description_model_settings"] = model_settings
    app.extensions["description_model"] = description_model
    search_index_path = app.config.get("SEARCH_INDEX_PATH") or database.path.with_name(
        f"{database.path.stem}.search-index.db"
    )
    search_index = SearchIndex(search_index_path)
    app.extensions["tracker_search_index"] = search_index
    prewarmer = None if app.config.get("TESTING") else WhitepaperPrewarmer()
    app.extensions["search_prewarm"] = prewarmer
    product_strategy_reader = ProductStrategyReader(
        app.config["PRODUCT_CONFIG_DATABASE"]
    )
    app.extensions["product_strategy_reader"] = product_strategy_reader

    def search_roots() -> dict[str, Any]:
        database.configure_document_evidence_roots(
            allowed_roots=[app.config["CONTROLLED_MATERIALS_ROOT"]]
            if app.config.get("CONTROLLED_MATERIALS_ROOT") else [],
            extraction_roots=app.config.get("CONTROLLED_EXTRACTION_ROOTS", []),
        )
        return {"materials_root": app.config.get("CONTROLLED_MATERIALS_ROOT"),
                "training_root": app.config.get("TRAINING_ROOT"),
                "controlled_extraction_roots": app.config.get("CONTROLLED_EXTRACTION_ROOTS", []),
                "historical_roots": historical_roots()}

    def historical_roots() -> list[str]:
        return [str(root) for root in [app.config.get("RELEASE_NOTE_ROOT"),
                *app.config.get("SOURCE_ROOTS", []), *app.config.get("CONTROLLED_EXTRACTION_ROOTS", [])] if root]

    search_roots()

    maintenance = SearchMaintenance(
        lambda: refresh_search_index(database, search_index, **search_roots()),
        manual_refresh=lambda: refresh_search_index(database, search_index, retry_failed=True, **search_roots()),
        enabled=not app.config.get("TESTING") and app.config.get("SEARCH_AUTO_UPDATE", True),
        interval_seconds=app.config.get("SEARCH_UPDATE_INTERVAL_SECONDS", 300),
        start_thread=not app.config.get("TESTING"),
    )
    try:
        if personal_workspace.read()["index_paused"]:
            maintenance.pause()
    except ValueError:
        maintenance.pause()
    app.extensions["search_maintenance"] = maintenance

    def document_registry() -> DocumentRegistry:
        # Keep token selection inside the current explicit allowlist.
        return DocumentRegistry(database, allowed_roots=[app.config["CONTROLLED_MATERIALS_ROOT"]]
                                if app.config.get("CONTROLLED_MATERIALS_ROOT") else [],
                                extraction_roots=app.config.get("CONTROLLED_EXTRACTION_ROOTS", []))

    def scope_suggester(document: dict[str, Any]) -> dict[str, Any]:
        roots = search_roots()
        if 'scope_candidates' not in g:
            g.scope_candidates = controlled_source_candidates(database, **roots)
        return suggest_document_scope(database, search_index, document, candidates=g.scope_candidates, **roots)

    def json_object() -> dict[str, Any]:
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            raise ValueError("请求内容必须为 JSON 对象。")
        return payload

    def text_fields(payload: dict[str, Any], keys: tuple[str, ...]) -> None:
        if any(payload.get(key) is not None and not isinstance(payload[key], str) for key in keys):
            raise ValueError("文字字段不能填写对象或列表。")

    @app.before_request
    def start_local_index_updates():
        if request.method == "GET" and request.path in {"/", "/api/v1/workbench/search", "/api/v1/workbench/search-index"}:
            maintenance.ensure_started()

    def requested_project_id() -> int:
        value = request.args.get("project_id")
        if value in {None, ""}:
            return database.default_project_id()
        try:
            project_id = int(value)
        except ValueError as error:
            raise ValueError("project_id must be an integer") from error
        try:
            database.get_project(project_id)
        except KeyError as error:
            # 此前这里让 KeyError 直接冒泡：9 条读路由返回 500 HTML，前端 `api()`
            # 无条件 JSON.parse，用户连「项目不存在」都看不到，只看到解析错误。
            # 与 `/projects/<id>/scan-preview` 一致，按 404 + JSON 返回。
            raise NotFound(f"项目 {project_id} 不存在。") from error
        return project_id

    @app.before_request
    def require_json_for_mutations():
        """所有写操作必须带 `application/json`。

        这是本机的**唯一跨站防线**：浏览器无法在跨域下发出 `application/json`
        （会先触发预检），因此这一条同时挡住了 CSRF 与简单表单提交。服务虽只监听
        127.0.0.1，但用户浏览器里的任意页面都能向 localhost 发跨站表单 POST，
        而 `/undo` 会删除版本数据，绝不能例外——历史上它被豁免过，
        导致一条 `application/x-www-form-urlencoded` 表单即可删版本。
        """
        if (
            request.path.startswith("/api/")
            and request.method in {"POST", "PUT", "PATCH", "DELETE"}
            and not request.is_json
        ):
            return failure(
                "json_required",
                "API mutations require application/json.",
                415,
            )

    @app.before_request
    def restrict_integrated_business_writes():
        """Keep canonical product master data out of the release evidence store."""
        if not app.config.get("INTEGRATED_MODE") or request.method == "GET":
            return None
        restricted = request.path.startswith(
            (
                "/api/v1/features",
                "/api/v1/terms",
                "/api/v1/categories",
                "/api/v1/knowledge-hub/qa",
            )
        )
        restricted = restricted or request.path in {
            "/api/v1/import-candidates/batch/promote",
            "/api/v1/import-candidates/batch/confirm",
        }
        if (
            request.path.startswith("/api/v1/import-candidates/")
            and request.path.endswith("/approve")
        ):
            payload = request.get_json(silent=True)
            restricted = restricted or bool(
                isinstance(payload, dict) and payload.get("promote_to_feature")
            )
        if restricted:
            return failure(
                "integrated_mode_restricted",
                "集成模式下功能、术语和问答主数据只能在产品配置管理系统中维护。",
                403,
            )
        return None

    @app.errorhandler(ValueError)
    def handle_value_error(error: ValueError):
        return failure("validation_error", str(error), 400)

    @app.errorhandler(NotFound)
    def handle_not_found(error: NotFound):
        """接口层的 404 也要是 JSON：前端 `api()` 只解析 JSON。"""
        if request.path.startswith("/api/"):
            return failure("not_found", str(error.description or "资源不存在。"), 404)
        return error

    @app.errorhandler(sqlite3.IntegrityError)
    def handle_integrity_error(_error: sqlite3.IntegrityError):
        return failure("conflict", "The requested change conflicts with existing data.", 409)

    @app.get("/")
    def index():
        embedded = bool(app.config.get("INTEGRATED_MODE")) and request.args.get(
            "embedded"
        ) == "1"
        return render_template(
            "index.html",
            workbench_home=bool(app.config.get("WORKBENCH_HOME", True)),
            embedded=embedded,
            integrated_mode=bool(app.config.get("INTEGRATED_MODE")),
            allowed_views=app.config.get(
                "INTEGRATED_ALLOWED_VIEWS",
                ["search", "review", "releases", "compare"],
            ),
            base_path=request.script_root.rstrip("/"),
        )

    @app.get("/api/v1/health")
    def health():
        return success({"service": "feature-release-tracker", "status": "ok"})

    @app.get("/api/v1/workbench/modules")
    def workbench_modules():
        return success(module_catalog())

    @app.get("/api/v1/workbench/personal")
    def workbench_personal():
        try:
            settings = personal_workspace.read()
        except ValueError as error:
            return success({**personal_workspace.defaults(), "index_paused": True,
                            "recovery_required": True, "settings_error": str(error)})
        backup_error = None
        if not app.config.get("TESTING"):
            try:
                personal_workspace.ensure_daily_backup()
            except (OSError, sqlite3.Error, ValueError):
                backup_error = "自动备份未成功，请检查可用空间后重试。"
        return success({**personal_workspace.read(), "backup_error": backup_error})

    @app.post("/api/v1/workbench/personal/restore")
    def restore_workbench_personal():
        result = personal_workspace.restore(json_object())
        maintenance.pause() if result["index_paused"] else maintenance.resume()
        return success(result)

    @app.put("/api/v1/workbench/personal")
    def update_workbench_personal():
        result = personal_workspace.update(request.get_json(silent=True))
        maintenance.pause() if result["index_paused"] else maintenance.resume()
        return success(result)

    @app.post("/api/v1/workbench/personal/recent")
    def workbench_recent_document():
        return success(personal_workspace.add_recent(request.get_json(silent=True)))

    @app.post("/api/v1/workbench/backups")
    def workbench_backup():
        try:
            return success(personal_workspace.create_backup(), 201)
        except (OSError, sqlite3.Error):
            return failure("backup_failed", "备份未成功，请检查可用空间后重试。", 503)

    @app.get("/api/v1/workbench/backups/<backup_id>/download")
    def workbench_backup_download(backup_id: str):
        path = personal_workspace.backup_file(backup_id)
        if not path:
            return failure("not_found", "该备份不存在或已超过保留数量。", 404)
        response = send_file(path, as_attachment=True, download_name=f"产品管理-{backup_id}.db", max_age=0)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/v1/workbench/search-index")
    def workbench_search_index_status():
        return success({**search_index.status(), "maintenance": maintenance.status(),
                        "coverage": search_source_coverage(database, search_index, **search_roots())})

    @app.post("/api/v1/workbench/search-index/refresh")
    def workbench_search_index_refresh():
        if not request.is_json:
            return failure("validation_error", "请求必须使用 application/json。", 415)
        result = maintenance.refresh_now(manual=True)
        return success(result)

    @app.get("/api/v1/workbench/search")
    def workbench_unified_search():
        raw_sources = request.args.get("sources", "release,config,controlled,training,term,registration,product_state,probe_version,knowledge,qa")
        sources = {item.strip() for item in raw_sources.split(",") if item.strip()}
        query_key = tuple(sorted((key, value) for key, value in request.args.items(multi=True)
                                 if key not in {"source_group", "release_category", "page"}))
        prewarm_ticket = prewarmer.begin(query_key) if prewarmer else None
        try:
            if request.args.get("expand_related", "false") not in {"true", "false"}:
                raise ValueError("关联词扩展须为 true 或 false。")
            unavailable_sources = sync_search_roots_and_metadata(
                database,
                search_index,
                **search_roots(),
            )
            result = unified_search(
                database,
                search_index,
                product_strategy_reader,
                query=request.args.get("q", ""),
                sources=sources,
                project_id=requested_project_id(),
                scope=request.args.get("scope", "current"),
                verification=request.args.get("verification", ""),
                current_only=request.args.get("current_only") == "true",
                model=request.args.get("model", ""),
                market=request.args.get("market", ""),
                country=request.args.get("country", ""),
                task=request.args.get("task", "search"),
                expand_related=request.args.get("expand_related") == "true",
                version_from=request.args.get("version_from", "").strip(),
                version_to=request.args.get("version_to", "").strip(),
                versions=request.args.get("versions", ""),
                source_group=request.args.get("source_group", "all"),
                release_category=request.args.get("release_category", "all"),
                whitepaper_model=request.args.get("whitepaper_model", ""),
                chapter_candidate=lambda source_id: resolve_source_candidate(database, source_id, **search_roots()),
                unavailable_sources=unavailable_sources,
                prewarm=(lambda candidates: prewarmer.schedule(prewarm_ticket, search_index, candidates,
                    lambda source_id: resolve_source_candidate(database, source_id, **search_roots()))) if prewarmer else None,
                page=int(request.args.get("page", "1")),
                page_size=int(request.args.get("page_size", "40")),
            )
            result["coverage"] = search_source_coverage(database, search_index,
                include_versions=bool(result['filters']['versions'] or result['filters']['version_from'] or result['filters']['version_to']), **search_roots())
            result["coverage"]["release"] = {"projects": [
                {"project_id": project["id"], "name": project["name"],
                 "versions": [release["version"] for release in database.list_releases(project["id"])]}
                for project in database.list_projects()
                if request.args.get("scope") == "all" or project["id"] == requested_project_id()
            ]}
            result['coverage']['versions'] = search_version_coverage(
                database, result['coverage'], result, requested_project_id())
            for source in ('controlled', 'training'):
                result['coverage'][source].pop('version_files', None)
        except (ValueError, TypeError) as error:
            return failure("validation_error", str(error))
        finally:
            if prewarmer:
                prewarmer.finish(prewarm_ticket)
        return success(result)

    def feature_scenario(project, query, args, *, allow_generation=True):
        unavailable = sync_search_roots_and_metadata(database, search_index, **search_roots())
        document_versions = {}
        latest_versions = {}
        for document in database.list_documents():
            versions = database.list_document_versions(document['id'])
            labels = [located_version(v.get('version_label') or '', document.get('title') or '') for v in versions]
            latest_versions[document['id']] = max((tuple(map(int, label.split('.'))) for label in labels if label), default=None)
            for version in versions:
                document_versions[version['id']] = document
        def search_page(page, model):
            page_result = unified_search(database, search_index, product_strategy_reader, query=query,
                sources={"release", "controlled"}, project_id=project, scope="current",
                source_group="whitepaper", whitepaper_model=model, page=page, page_size=100,
                unavailable_sources=unavailable,
                chapter_candidate=lambda source_id: resolve_source_candidate(database, source_id, **search_roots()))
            for item in page_result['results']:
                document = document_versions.get(item.get('document_version_id'))
                if document:
                    item['_scenario_document_id'] = str(document['id'])
                    item['_scenario_document_label'] = document['title']
            page_result['results'] = [item for item in page_result['results'] if (doc := document_versions.get(item.get('document_version_id'))) and latest_versions.get(doc['id']) is not None and re.fullmatch(r'\d+(?:\.\d+)+', item.get('version') or '') and tuple(map(int, item['version'].split('.'))) == latest_versions[doc['id']]]
            return page_result
        def preview_section(source_id, locator, needle):
            candidate = resolve_source_candidate(database, source_id, **search_roots())
            indexed_path = search_index.source_path(source_id)
            if not candidate or not indexed_path or candidate["path"].resolve() != indexed_path.resolve():
                return None
            try:
                return search_index.preview(source_id, locator=locator, query=needle, include_images=False)
            except OSError:
                return None
        result = feature_answer(database, project, query, args.get("model", ""), search_page,
                                preview_section, '', args.get("document", ""), args.get("section", ""))
        result['later_changes'] = []
        result['description'] = None
        return result

    @app.get("/api/v1/workbench/model-settings")
    def workbench_model_settings():
        return success(model_settings.public())

    @app.put("/api/v1/workbench/model-settings")
    def update_workbench_model_settings():
        payload = json_object()
        text_fields(payload, ('provider', 'model', 'api_key'))
        return success(model_settings.save(provider=payload.get('provider'), model=payload.get('model'),
            api_key=payload.get('api_key', ''), daily_tokens=payload.get('daily_tokens')))

    @app.put("/api/v1/workbench/scenario/feature-description")
    def update_scenario_feature_description():
        payload = json_object()
        text_fields(payload, ('q', 'model', 'document', 'section', 'target', 'content', 'source_fingerprint'))
        query = (payload.get('q') or '').strip()
        if not query or len(query) > 200:
            raise ValueError('请输入不超过 200 字的功能名称。')
        requested_project_id()
        return failure('retired_workflow', '功能说明已改为Release Note版本演进，不再编辑模型摘要。', 410)

    @app.route("/api/v1/workbench/scenario", methods=["GET", "POST"])
    def workbench_scenario():
        args = json_object() if request.method == "POST" else request.args
        if request.method == "POST":
            text_fields(args, ("task", "q", "code", "series", "model", "target", "base", "document", "section"))
        task = args.get("task", "")
        project = requested_project_id()
        query = (args.get("q") or "").strip()
        try:
            if task in {"probe", "feature", "whitepaper"} and (not query or len(query) > 200):
                raise ValueError("请输入不超过 200 字的探头或功能名称。")
            if task == "probe":
                result = probe_answer(database, project, query, args.get("code", ""), args.get("series", ""))
            elif task == "feature":
                result = decorate_illustration_choices(database, decorate_release_review(database, release_evolution_answer(database, project, query, args.get("target", "")), project, query, args.get("target", "")), project)
            elif task == "whitepaper":
                result = feature_scenario(project, query, args, allow_generation=False)
            elif task == "version":
                def compare_releases(earlier, later):
                    comparison = compare_change_sets(database.list_changes(earlier['id']), database.list_changes(later['id']))
                    comparison['structured'] = database.compare_release_structured(earlier['id'], later['id'])
                    return comparison
                result = version_answer(database, project, args.get("target", ""), args.get("base", ""), compare_releases)
            else:
                raise ValueError("不支持的查询任务。")
            return success(result)
        except (ValueError, TypeError) as error:
            return failure("validation_error", str(error))

    def release_review_context(args):
        query = args.get('q', '')
        target = args.get('target', '')
        if not isinstance(query, str) or not query.strip() or len(query) > 200 or not isinstance(target, str):
            raise ValueError('请输入有效的功能名称和目标版本。')
        project = requested_project_id()
        return project, query.strip(), target, release_evolution_answer(database, project, query.strip(), target)

    @app.put('/api/v1/workbench/scenario/review')
    def workbench_save_release_review():
        payload = json_object()
        try:
            project, query, target, answer = release_review_context(payload)
            return success(decorate_illustration_choices(database, save_release_review(database, answer, project, query, target, payload), project))
        except ReviewConflict as error:
            return failure('review_conflict', str(error), 409)
        except (ValueError, TypeError) as error:
            return failure('validation_error', str(error))

    @app.get('/api/v1/workbench/scenario/review-history')
    def workbench_release_review_history():
        try:
            project, query, target, answer = release_review_context(request.args)
            return success(list_release_review_history(database, answer, project, query, target, kind=request.args.get('kind', 'body')))
        except (ValueError, TypeError) as error:
            return failure('validation_error', str(error))

    @app.post('/api/v1/workbench/scenario/review/restore')
    def workbench_restore_release_review():
        payload = json_object()
        try:
            project, query, target, answer = release_review_context(payload)
            return success(decorate_illustration_choices(database, restore_release_review(database, answer, project, query, target, payload), project))
        except ReviewConflict as error:
            return failure('review_conflict', str(error), 409)
        except (ValueError, TypeError) as error:
            return failure('validation_error', str(error))

    @app.put('/api/v1/workbench/scenario/illustrations/select')
    def workbench_select_current_illustration():
        payload = json_object()
        try:
            project, query, target, answer = release_review_context(payload)
            answer = decorate_release_review(database, answer, project, query, target)
            return success(save_illustration_choice(database, answer, project, payload))
        except ReviewConflict as error:
            return failure('review_conflict', str(error), 409)
        except (ValueError, TypeError) as error:
            return failure('validation_error', str(error))

    @app.get("/api/v1/workbench/search-index/sources/<path:source_id>/preview")
    def workbench_search_preview(source_id: str):
        if source_id.startswith("release:"):
            if request.args.get("file") == "1" or request.args.get("download") == "1":
                return failure("validation_error", "版本记录提供保存的文本快照，请从资料预览获取已登记原文件。")
            preview = release_evidence(database, source_id, request.args.get("locator", ""), query=request.args.get("q", "")[:200])
            return success(preview) if preview else failure("not_found", "版本原文记录不存在。", 404)
        candidate = resolve_source_candidate(
            database,
            source_id,
            **search_roots(),
        )
        indexed_path = search_index.source_path(source_id)
        if candidate and not indexed_path:
            result = maintenance.refresh_now()
            if result.get("skipped"):
                return failure("index_updating", "资料索引正在更新，请稍后再打开。", 409)
            indexed_path = search_index.source_path(source_id)
        if not candidate or not indexed_path:
            return failure("not_found", "资料未登记、已移除或不在允许的来源范围内。", 404)
        if candidate["path"].resolve() != indexed_path.resolve():
            return failure("not_found", "资料来源已变化，请刷新索引后再打开。", 404)
        try:
            preview = search_index.preview(source_id, locator=request.args.get("locator", ""), query=request.args.get("q", "")[:200])
        except OSError:
            return failure("source_unavailable", "资料当前不可读取。", 503)
        if not preview:
            return failure("not_found", "索引中没有该资料。", 404)
        if preview["stale"]:
            return failure("source_changed", "原文件在索引后发生变化，请先刷新搜索索引。", 409)
        file_requested = request.args.get("file") == "1"
        suffix = candidate["path"].suffix.casefold()
        if request.args.get("download") == "1":
            response = send_file(candidate["path"], as_attachment=True, download_name=candidate["path"].name, max_age=0)
            response.headers["Cache-Control"] = "no-store"
            response.headers["X-Content-Type-Options"] = "nosniff"
            return response
        if file_requested and suffix in {".pdf", ".png", ".jpg", ".jpeg"}:
            mimetypes = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}
            response = send_file(
                candidate["path"],
                mimetype=mimetypes[suffix],
                as_attachment=False,
                conditional=True,
                max_age=0,
            )
            response.headers["Cache-Control"] = "no-store"
            response.headers["X-Content-Type-Options"] = "nosniff"
            return response
        return success(preview)

    @app.get("/api/v1/workbench/overview")
    def workbench_overview():
        return success(overview_for_project(database, requested_project_id()))

    @app.get("/api/v1/workbench/model")
    def workbench_model_workspace():
        return success(build_model_workspace(database, product_strategy_reader,
                       model=request.args.get("model", ""), market=request.args.get("market", "domestic"),
                       country=request.args.get("country", ""), series=request.args.get("series", ""), scope_suggester=scope_suggester))

    @app.get('/api/v1/knowledge-hub/documents/<int:document_id>/scope-suggestion')
    def document_scope_suggestion(document_id: int):
        document = next((row for row in database.list_documents() if row['id'] == document_id), None)
        if document is None:
            return failure('not_found', '资料不存在。', 404)
        return success(scope_suggester(document))

    @app.get("/api/v1/knowledge-hub/documents/files")
    def document_file_catalog():
        return success(document_registry().file_catalog())

    @app.get("/api/v1/workbench/historical-documents/files")
    def historical_file_catalog():
        return success(DocumentRegistry(database, allowed_roots=historical_roots(), configure_evidence_roots=False).file_catalog())

    @app.post("/api/v1/workbench/historical-documents")
    def register_historical_document():
        payload = json_object()
        fields = {key: payload.get(key, "") for key in ("title", "model_scope", "scope_market", "file_token", "version_label")}
        if any(not isinstance(value, str) for value in fields.values()):
            raise ValueError("资料登记字段必须为文字。")
        result = DocumentRegistry(database, allowed_roots=historical_roots(), configure_evidence_roots=False).register_document(
            **fields, doc_type="历史补充资料")
        return success(result, 200 if result["duplicate"] else 201)

    @app.post("/api/v1/knowledge-hub/documents")
    def register_controlled_document():
        payload = json_object()
        fields = {key: payload.get(key, "") for key in ("title", "doc_type", "model_scope", "scope_market", "file_token", "version_label")}
        if any(not isinstance(value, str) for value in fields.values()):
            raise ValueError("资料登记字段必须为文字。")
        result = document_registry().register_document(**fields, extract_source_token=payload.get("extract_source_token"), effective_date=payload.get("effective_date"))
        return success(result, 200 if result["duplicate"] else 201)

    @app.post("/api/v1/knowledge-hub/documents/<int:document_id>/versions")
    def append_controlled_document_version(document_id: int):
        payload = json_object()
        text_fields(payload, ("file_token", "version_label", "extract_source_token", "effective_date"))
        result = document_registry().append_version(document_id, file_token=payload.get("file_token"), version_label=payload.get("version_label"),
                         extract_source_token=payload.get("extract_source_token"), effective_date=payload.get("effective_date"))
        return success(result, 200 if result["duplicate"] else 201)

    @app.post("/api/v1/knowledge-hub/documents/<int:document_id>/versions/<int:version_id>/review")
    def review_controlled_document(document_id: int, version_id: int):
        payload = json_object()
        text_fields(payload, ("reviewer", "reviewed_at", "basis", "model_scope", "scope_market"))
        return success(document_registry().review_version(document_id, version_id, reviewer=payload.get("reviewer"),
                       reviewed_at=payload.get("reviewed_at"), basis=payload.get("basis"), confirmed=payload.get("confirmed"),
                       model_scope=payload.get("model_scope"), scope_market=payload.get("scope_market")))

    @app.get("/api/v1/knowledge-hub/documents/options")
    def knowledge_document_options():
        return success(
            {
                "doc_types": sorted(
                    {
                        document["doc_type"]
                        for document in database.list_documents()
                        if document["doc_type"]
                    }
                )
            }
        )

    @app.get("/api/v1/knowledge-hub/documents")
    def knowledge_documents_api():
        return success(
            build_knowledge_documents(
                database,
                query=request.args.get("q", ""),
                doc_type=request.args.get("doc_type", ""),
                track=request.args.get("track", ""),
                evidence=request.args.get("evidence", ""),
                verification=request.args.get("verification", ""),
                model=request.args.get("model", ""),
                market=request.args.get("market", ""),
                scope_suggester=scope_suggester,
            )
        )

    @app.get("/api/v1/knowledge-hub/items/options")
    def knowledge_item_options():
        return success(
            {
                "categories": [
                    {"code": row["code"], "name": row["name"], "level": row["level"]}
                    for row in database.list_knowledge_categories()
                ]
            }
        )

    @app.get("/api/v1/knowledge-hub/items")
    def knowledge_items_api():
        return success(
            build_knowledge_items(
                database,
                query=request.args.get("q", ""),
                category=request.args.get("category", ""),
                code_type=request.args.get("code_type", ""),
                evidence=request.args.get("evidence", ""),
            )
        )

    @app.get("/api/v1/knowledge-hub/probe-versions")
    def probe_versions_api():
        return success(
            build_probe_versions(
                database,
                probe=request.args.get("probe", ""),
                series=request.args.get("series", ""),
                version=request.args.get("version", ""),
            )
        )

    @app.get("/api/v1/knowledge-hub/issues")
    def knowledge_issues_api():
        """待处理问题清单（只读）。

        `status` 省略时默认 `open`——这是待处理清单；显式传 `status=` （空值）表示不限状态。
        全部筛选都只作用于本次读取，不写库。
        """
        return success(
            build_knowledge_issues(
                database,
                query=request.args.get("q", ""),
                severity=request.args.get("severity", ""),
                status=request.args.get("status", "open"),
                issue_type=request.args.get("issue_type", ""),
            )
        )

    @app.get("/api/v1/knowledge-hub/qa/search")
    def qa_search_api():
        return success(find_answer(
            database,
            request.args.get("q", ""),
            market=request.args.get("market", ""),
            country=request.args.get("country", ""),
            model=request.args.get("model", ""),
            reader=product_strategy_reader,
            probe=request.args.get("probe", ""),
            item=request.args.get("item", ""),
        ))

    @app.post("/api/v1/knowledge-hub/qa/revalidate")
    def qa_revalidate_api():
        return success({"changed": revalidate_structured_answers(database, product_strategy_reader)})

    @app.get("/api/v1/knowledge-hub/qa/questions")
    def qa_questions_api():
        return success(database.list_qa_questions(request.args.get("status") or None, request.args.get("requester") or None))

    @app.post("/api/v1/knowledge-hub/qa/questions")
    def qa_submit_question_api():
        payload = request.get_json() or {}
        question_id = database.submit_qa_question(
            question=payload.get("question", ""),
            market_code=payload.get("market", ""),
            country_code=payload.get("country", ""),
            model_name=payload.get("model", ""),
            requester=payload.get("requester", ""),
            reason_code=payload.get("reason_code", "unanswered"),
            context_note=payload.get("context_note", ""),
        )
        return success({"id": question_id, "status": "open"}, 201)

    @app.get("/api/v1/knowledge-hub/qa/answers")
    def qa_answers_api():
        return success(database.list_qa_answers(request.args.get("status") or None))

    @app.get("/api/v1/knowledge-hub/qa/evidence-options")
    def qa_evidence_options_api():
        return success(database.list_current_qa_evidence(request.args.get("q", "")))

    @app.post("/api/v1/knowledge-hub/qa/answers")
    def qa_create_draft_api():
        payload = request.get_json() or {}
        answer_id = database.create_qa_draft(
            standard_question=payload.get("standard_question", ""),
            similar_questions=payload.get("similar_questions", []),
            answer_text=payload.get("answer_text", ""),
            market_code=payload.get("market", ""),
            country_code=payload.get("country", ""),
            model_name=payload.get("model", ""),
            registration_result=payload.get("registration_result", ""),
            strategy_result=payload.get("strategy_result", ""),
            limitations=payload.get("limitations", ""),
            evidence_id=payload.get("evidence_id"),
        )
        return success({"id": answer_id, "status": "draft"}, 201)

    @app.post("/api/v1/knowledge-hub/qa/answers/<int:answer_id>/review")
    def qa_review_api(answer_id: int):
        database.submit_qa_for_review(answer_id)
        return success({"id": answer_id, "status": "in_review"})

    @app.post("/api/v1/knowledge-hub/qa/answers/<int:answer_id>/publish")
    def qa_publish_api(answer_id: int):
        payload = request.get_json() or {}
        scope = database.get_qa_answer_scope(answer_id)
        signature = structured_signature(database, product_strategy_reader, country=scope["country_code"], model=scope["model_name"])
        database.publish_qa_answer(
            answer_id, reviewer=payload.get("reviewer", ""),
            verified_at=payload.get("verified_at", ""),
            structured_signature=signature,
        )
        return success({"id": answer_id, "status": "published"})

    @app.post("/api/v1/knowledge-hub/qa/answers/<int:answer_id>/retire")
    def qa_retire_api(answer_id: int):
        payload = request.get_json() or {}
        database.retire_qa_answer(answer_id, reason=payload.get("reason", ""))
        return success({"id": answer_id, "status": "retired"})

    @app.get("/api/v1/knowledge-hub/qa/notifications")
    def qa_notifications_api():
        requester = request.args.get("requester", "").strip()
        if not requester:
            raise ValueError("请提供提问人。")
        return success(database.list_qa_notifications(
            requester,
            lambda country, model: structured_signature(database, product_strategy_reader, country=country, model=model),
        ))

    @app.post("/api/v1/knowledge-hub/qa/questions/<int:question_id>/feedback")
    def qa_feedback_api(question_id: int):
        payload = request.get_json() or {}
        if not isinstance(payload.get("helpful"), bool):
            raise ValueError("反馈必须明确选择是否解决问题。")
        feedback_id = database.add_qa_feedback(
            question_id, helpful=payload["helpful"], detail=payload.get("detail", ""),
        )
        return success({"id": feedback_id}, 201)

    @app.get("/api/v1/knowledge-hub/registrations/models")
    def registration_models():
        return success(database.list_registration_models(request.args.get("country", "CN")))

    @app.get("/api/v1/knowledge-hub/registrations")
    def registrations():
        return success(
            registration_query(
                database,
                request.args.get("model", ""),
                request.args.get("country", "CN"),
            )
        )

    @app.get("/api/v1/knowledge-hub/product-states/options")
    def product_states_options_api():
        return success(product_state_options(database))

    @app.get("/api/v1/knowledge-hub/product-states")
    def product_states_api():
        return success(
            product_states(
                database,
                market_code=request.args.get("market", "CN"),
                model_name=request.args.get("model", ""),
            )
        )

    @app.get("/api/v1/workbench/config-system")
    def workbench_config_system():
        return success(config_system_entry(app.config.get("PRODUCT_CONFIG_SYSTEM_URL")))

    @app.get("/api/v1/workbench/training")
    def workbench_training():
        root = app.config.get("TRAINING_ROOT")
        payload = training_assets(root, request.args.get("q", ""))
        if root and payload["status"] == "available":
            resolved_root = Path(root).expanduser().resolve()

            def add_previews(entries):
                for entry in entries:
                    if entry["kind"] == "directory":
                        add_previews(entry.get("children", []))
                        continue
                    relative_name = Path(entry["path"]).as_posix()
                    if training_source_path(resolved_root, relative_name) is not None:
                        entry["preview_id"] = training_source_id(relative_name)

            add_previews(payload["entries"])
        return success(payload)

    @app.get("/api/v1/workbench/sources")
    def workbench_sources():
        return success(
            sources_status(
                database=database,
                project_id=requested_project_id(),
                product_config_database=app.config.get("PRODUCT_CONFIG_DATABASE"),
                controlled_materials_root=app.config.get("CONTROLLED_MATERIALS_ROOT"),
                training_root=app.config.get("TRAINING_ROOT"),
            )
        )

    @app.get("/api/v1/knowledge-hub/product-strategies/models")
    def product_strategy_models():
        try:
            return success(product_strategy_reader.list_models())
        except ProductStrategySourceUnavailable as error:
            return failure("source_unavailable", str(error), 503)

    @app.get("/api/v1/knowledge-hub/product-strategies")
    def product_strategies():
        try:
            payload = product_strategy_reader.query(
                market=request.args.get("market", "domestic"),
                model=request.args.get("model", ""),
                query=request.args.get("q", ""),
            )
        except ProductStrategySourceUnavailable as error:
            return failure("source_unavailable", str(error), 503)
        # 补充最近一次一致性快照的登记信息；本次查询本身仍是只读直连，不是读快照。
        payload["source"]["snapshot"] = database.latest_strategy_snapshot()
        return success(payload)

    @app.get("/api/v1/dashboard")
    def dashboard():
        return success(database.counts(requested_project_id()))

    @app.get("/api/v1/review-issues")
    def review_issues():
        return success(database.list_review_issues(requested_project_id()))

    @app.get("/api/v1/projects")
    def list_projects():
        return success(database.list_projects())

    @app.post("/api/v1/projects")
    def create_project():
        payload = request.get_json(silent=True) or {}
        keywords = payload.get("file_keywords", [])
        if not isinstance(keywords, list):
            return failure("validation_error", "file_keywords must be a list")
        raw_source_root = str(payload.get("source_root", "") or "").strip()
        source_root = (
            validated_source_root(app.config, raw_source_root) if raw_source_root else ""
        )
        return success(
            database.create_project(
                str(payload.get("name", "")),
                str(payload.get("code", "")),
                source_root,
                [str(keyword) for keyword in keywords],
            ),
            201,
        )

    @app.post("/api/v1/projects/<int:project_id>/sources")
    def add_project_source(project_id: int):
        payload = request.get_json(silent=True) or {}
        keywords = payload.get("file_keywords", [])
        if not isinstance(keywords, list):
            return failure("validation_error", "file_keywords must be a list")
        # 路径必须落在启动配置的根目录内；校验失败由 ValueError 处理器转成 400。
        path = validated_source_root(app.config, payload.get("path"))
        try:
            return success(
                database.add_project_source(
                    project_id,
                    path,
                    str(payload.get("label", "Release Note")),
                    [str(keyword) for keyword in keywords],
                ),
                201,
            )
        except KeyError:
            return failure("not_found", "Project not found.", 404)

    @app.get("/api/v1/projects/<int:project_id>/scan-preview")
    def project_scan_preview(project_id: int):
        try:
            project = database.get_project(project_id)
        except KeyError:
            return failure("not_found", "Project not found.", 404)
        enabled_sources = [source for source in project["sources"] if source["enabled"]]
        previews = [
            {
                "source_id": source["id"],
                "source_path": source["path"],
                **preview_release_notes(source["path"], source["file_keywords"]),
            }
            for source in enabled_sources
        ]
        versions = [version for preview in previews for version in preview["versions"]]
        return success(
            {
                "project_id": project_id,
                "versions_found": sum(preview["versions_found"] for preview in previews),
                "ready_pairs": sum(preview["ready_pairs"] for preview in previews),
                "needs_review": sum(preview["needs_review"] for preview in previews),
                "versions": versions,
                "sources": previews,
            }
        )

    @app.get("/api/v1/projects/<int:project_id>/health")
    def project_health(project_id: int):
        try:
            project = database.get_project(project_id)
        except KeyError:
            return failure("not_found", "Project not found.", 404)
        sources = [source for source in project["sources"] if source["enabled"]]
        previews = [
            {
                "source_id": source["id"],
                "source_path": source["path"],
                **preview_release_notes(source["path"], source["file_keywords"]),
            }
            for source in sources
        ]
        versions = [
            {**version, "source_path": preview["source_path"]}
            for preview in previews
            for version in preview["versions"]
        ]
        candidates = database.list_import_candidates("pending", project_id)
        risk_counts = {
            level: sum(item["risk_level"] == level for item in candidates)
            for level in ("high", "medium", "low")
        }
        needs_review = sum(preview["needs_review"] for preview in previews)
        score = max(0, 100 - needs_review * 15 - risk_counts["high"] * 3 - risk_counts["medium"])
        releases = database.list_releases(project_id)
        batches = database.list_import_batches(project_id)
        return success(
            {
                "project_id": project_id,
                "status": "attention" if needs_review or risk_counts["high"] else "healthy",
                "score": score,
                "scan": {
                    "versions_found": sum(item["versions_found"] for item in previews),
                    "ready_pairs": sum(item["ready_pairs"] for item in previews),
                    "needs_review": needs_review,
                },
                "review_risk": risk_counts,
                "source_issues": [item for item in versions if item["status"] != "ready"],
                "latest_version": releases[0]["version"] if releases else None,
                "latest_batch": batches[0] if batches else None,
            }
        )

    @app.get("/api/v1/terms")
    def list_terms():
        return success(
            database.list_terms(
                query=request.args.get("q", ""),
                top_level_only=request.args.get("top_level", "0") == "1",
            )
        )

    @app.get("/api/v1/categories")
    def list_product_categories():
        return success(database.list_product_categories())

    @app.post("/api/v1/categories")
    def create_product_category():
        payload = request.get_json(silent=True) or {}
        return success(
            database.create_product_category(str(payload.get("name", ""))), 201
        )

    @app.patch("/api/v1/categories/<int:category_id>")
    def rename_product_category(category_id: int):
        payload = request.get_json(silent=True) or {}
        try:
            return success(
                database.rename_product_category(
                    category_id, str(payload.get("name", ""))
                )
            )
        except KeyError:
            return failure("not_found", "分类不存在。", 404)

    @app.post("/api/v1/terms/<int:term_id>/confirm")
    def confirm_term(term_id: int):
        payload = request.get_json(silent=True) or {}
        try:
            return success(
                database.confirm_term(
                    term_id,
                    str(payload["cn_name"]) if "cn_name" in payload else None,
                    str(payload["en_name"]) if "en_name" in payload else None,
                    str(payload["category"]) if "category" in payload else None,
                )
            )
        except KeyError:
            return failure("not_found", "Term not found.", 404)
        except ValueError:
            return failure(
                "validation_error",
                "确认术语前必须填写中文名称和英文名称。",
            )
        except sqlite3.IntegrityError:
            return failure(
                "conflict",
                "修改后的中英文术语与现有词条重复。",
                409,
            )

    @app.patch("/api/v1/terms/<int:term_id>")
    def update_term(term_id: int):
        payload = request.get_json(silent=True) or {}
        try:
            return success(
                database.update_term(
                    term_id,
                    str(payload.get("cn_name", "")),
                    str(payload.get("en_name", "")),
                    str(payload.get("category", "")),
                )
            )
        except KeyError:
            return failure("not_found", "Term not found.", 404)
        except sqlite3.IntegrityError:
            return failure("conflict", "修改后的内容与现有词条重复。", 409)

    @app.patch("/api/v1/terms/<int:term_id>/entry-type")
    def set_term_entry_type(term_id: int):
        payload = request.get_json(silent=True) or {}
        try:
            return success(
                database.set_term_entry_type(term_id, str(payload.get("entry_type", "")))
            )
        except KeyError:
            return failure("not_found", "Term not found.", 404)

    @app.get("/api/v1/features")
    def list_features():
        return success(
            database.list_features(
                request.args.get("q", ""), project_id=requested_project_id()
            )
        )

    @app.get("/api/v1/feature-matches")
    def feature_matches():
        return success(
            database.search_feature_matches(
                request.args.get("q", ""), project_id=requested_project_id()
            )
        )

    @app.post("/api/v1/features")
    def create_feature():
        payload = request.get_json(silent=True) or {}
        required = ("cn_name", "en_name")
        missing = [name for name in required if not str(payload.get(name, "")).strip()]
        if missing:
            return failure(
                "validation_error",
                "Chinese and English feature names are required.",
                details={"missing": missing},
            )
        feature_id = database.create_feature(
            cn_name=payload["cn_name"],
            en_name=payload["en_name"],
            cn_description=payload.get("cn_description", ""),
            en_description=payload.get("en_description", ""),
            term_id=payload.get("term_id"),
            category=str(payload.get("category", "")),
            project_id=int(payload.get("project_id") or database.default_project_id()),
        )
        return success(database.get_feature(feature_id), 201)

    @app.get("/api/v1/features/<int:feature_id>")
    def get_feature(feature_id: int):
        try:
            return success(database.get_feature(feature_id))
        except KeyError:
            return failure("not_found", "Feature not found.", 404)

    @app.get("/api/v1/features/<int:feature_id>/timeline")
    def feature_timeline(feature_id: int):
        try:
            return success(database.get_feature_timeline(feature_id))
        except KeyError:
            return failure("not_found", "Feature not found.", 404)

    @app.patch("/api/v1/features/<int:feature_id>")
    def update_feature(feature_id: int):
        payload = request.get_json(silent=True) or {}
        try:
            current = database.get_feature(feature_id)
        except KeyError:
            return failure("not_found", "Feature not found.", 404)

        # PATCH 是部分更新：**没出现的字段一律沿用现有值**。此前描述字段用
        # `payload.get(..., "")` 兜底，于是「只改名称」的请求会把已审核的双语最终
        # 描述清空，并写入一条空的 approved 修订——功能库唯一的正式产出被静默抹掉。
        # `null` 与「未提供」等价处理，避免 str(None) 写成字面量 "None"。
        cn_name = _payload_text(payload, "cn_name", current["cn_name"])
        en_name = _payload_text(payload, "en_name", current["en_name"])
        cn_description = _payload_text(payload, "cn_description", current["cn_description"])
        en_description = _payload_text(payload, "en_description", current["en_description"])
        category = (
            str(current["category"] or "")
            if payload.get("category") is None
            else str(payload["category"])
        )
        try:
            return success(
                database.update_feature(
                    feature_id,
                    cn_name,
                    en_name,
                    cn_description,
                    en_description,
                    category,
                )
            )
        except KeyError:
            return failure("not_found", "Feature not found.", 404)

    @app.post("/api/v1/features/<int:feature_id>/children")
    def create_child_feature(feature_id: int):
        payload = request.get_json(silent=True) or {}
        cn_name = str(payload.get("cn_name", "")).strip()
        en_name = str(payload.get("en_name", "")).strip()
        if not cn_name or not en_name:
            return failure(
                "validation_error",
                "独立子功能必须填写中文名称和英文名称。",
            )
        try:
            child_id = database.create_child_feature(
                feature_id,
                cn_name,
                en_name,
                str(payload.get("cn_description", "")),
                str(payload.get("en_description", "")),
                str(payload.get("category", "")),
            )
            return success(database.get_feature(child_id), 201)
        except KeyError:
            return failure("not_found", "Parent feature not found.", 404)

    @app.post("/api/v1/features/<int:feature_id>/notes")
    def create_feature_note(feature_id: int):
        payload = request.get_json(silent=True) or {}
        try:
            note_id = database.add_feature_note(
                feature_id,
                str(payload.get("cn_content", "")),
                str(payload.get("en_content", "")),
            )
            note = next(
                item
                for item in database.get_feature(feature_id)["notes"]
                if item["id"] == note_id
            )
            return success(note, 201)
        except KeyError:
            return failure("not_found", "Feature not found.", 404)

    @app.post("/api/v1/features/<int:feature_id>/revisions")
    def add_feature_revision(feature_id: int):
        payload = request.get_json(silent=True) or {}
        cn_description = str(payload.get("cn_description", "")).strip()
        en_description = str(payload.get("en_description", "")).strip()
        if not cn_description or not en_description:
            return failure(
                "validation_error",
                "Approved feature descriptions require Chinese and English content.",
            )
        try:
            revision_id = database.add_feature_revision(
                feature_id,
                cn_description,
                en_description,
                review_status="approved" if payload.get("approve") else "pending",
            )
        except KeyError:
            return failure("not_found", "Feature not found.", 404)
        return success({"revision_id": revision_id}, 201)

    @app.get("/api/v1/releases")
    def list_releases():
        releases = database.list_releases(requested_project_id())
        for release in releases:
            release["changes"] = database.list_changes(release["id"])
        return success(releases)

    @app.get("/api/v1/releases/<int:release_id>/configuration-tables")
    def release_configuration_tables(release_id: int):
        try:
            return success(database.list_release_configuration_tables(release_id))
        except KeyError:
            return failure("not_found", "Release not found.", 404)

    @app.get("/api/v1/releases/<int:release_id>/archive")
    def release_archive(release_id: int):
        try:
            return success(database.get_release_archive(release_id))
        except KeyError:
            return failure("not_found", "Release not found.", 404)

    @app.get("/api/v1/releases/<int:release_id>/effective-configuration")
    def release_effective_configuration(release_id: int):
        try:
            return success(database.get_effective_configuration(release_id))
        except KeyError:
            return failure("not_found", "Release not found.", 404)

    @app.get("/api/v1/release-search")
    def release_search():
        return success(
            database.search_release_history(
                request.args.get("q", ""),
                project_id=requested_project_id(),
                all_projects=request.args.get("scope") == "all",
                result_type=request.args.get("type", "all"),
            )
        )

    @app.get("/api/v1/comparisons")
    def comparison():
        from_version = request.args.get("from")
        to_version = request.args.get("to")
        by_version = {
            release["version"]: release
            for release in database.list_releases(requested_project_id())
        }
        if from_version not in by_version or to_version not in by_version:
            return failure("validation_error", "Both versions must exist.")
        earlier = database.list_changes(by_version[from_version]["id"])
        later = database.list_changes(by_version[to_version]["id"])
        result = compare_change_sets(earlier, later)
        result["structured"] = database.compare_release_structured(
            by_version[from_version]["id"], by_version[to_version]["id"]
        )
        return success(result)

    @app.post("/api/v1/import-batches/scan")
    def scan_release_notes():
        payload = request.get_json(silent=True) or {}
        project_id = int(payload.get("project_id") or database.default_project_id())
        ready_only = payload.get("ready_only") is True
        try:
            project = database.get_project(project_id)
        except KeyError:
            return failure("not_found", "Project not found.", 404)
        sources = [source for source in project["sources"] if source["enabled"]]
        if not sources:
            return failure(
                "configuration_error",
                "Release Note directory is not configured.",
                503,
            )
        # 不写死键集合：`stage_release_notes` 还会给出 `review_decisions_recorded`、
        # `review_decisions_unmatched`、`versions_skipped_empty` 等安全计数。
        # 历史上这里只累加 7 个固定键并把其余**静默丢弃**，于是「重扫后有哪些人工
        # 审核结论已对不上当前候选」这个信号永远到不了操作者眼前。现在原样透传：
        # 批次 stats、接口响应、前端提示三处都能看到。
        totals: dict[str, int] = {}
        previews = [
            preview_release_notes(source["path"], source["file_keywords"])
            for source in sources
        ]
        versions = [
            item["version"]
            for preview in previews
            for item in preview["versions"]
            if not ready_only or item["status"] == "ready"
        ]
        preexisting = {item["version"] for item in database.list_releases(project_id)}
        batch_id = database.create_import_batch(
            project_id,
            ready_only,
            "；".join(source["path"] for source in sources),
        )
        try:
            for source in sources:
                result = stage_release_notes(
                    database,
                    source["path"],
                    project_id=project_id,
                    file_keywords=source["file_keywords"],
                    ready_only=ready_only,
                )
                for key, value in result.items():
                    totals[key] = totals.get(key, 0) + int(value)
            batch = database.complete_import_batch(batch_id, versions, preexisting, totals)
        except Exception as error:
            database.fail_import_batch(batch_id, str(error))
            raise
        response_data = dict(totals)
        if "project_id" in payload:
            response_data.update({"batch_id": batch_id, "undoable": batch["undoable"]})
        return success(response_data)

    @app.get("/api/v1/import-batches")
    def list_import_batches():
        return success(database.list_import_batches(requested_project_id()))

    @app.post("/api/v1/import-batches/<int:batch_id>/undo")
    def undo_import_batch(batch_id: int):
        try:
            return success(database.undo_import_batch(batch_id))
        except KeyError:
            return failure("not_found", "Import batch not found.", 404)

    @app.get("/api/v1/import-candidates")
    def list_import_candidates():
        return success(
            database.list_import_candidates(
                request.args.get("status", "pending"), requested_project_id()
            )
        )

    @app.post("/api/v1/import-candidates/batch/approve")
    def approve_import_candidates():
        payload = request.get_json(silent=True) or {}
        candidate_ids = payload.get("candidate_ids")
        if not isinstance(candidate_ids, list) or any(
            not isinstance(candidate_id, int) or isinstance(candidate_id, bool)
            for candidate_id in candidate_ids
        ):
            return failure("validation_error", "candidate_ids must be a list of integers.")
        try:
            return success(database.approve_import_candidates(candidate_ids))
        except KeyError:
            return failure("not_found", "Import candidate not found.", 404)

    @app.post("/api/v1/import-candidates/batch/promote")
    def promote_import_candidates():
        payload = request.get_json(silent=True) or {}
        candidate_ids = payload.get("candidate_ids")
        if not isinstance(candidate_ids, list) or any(
            not isinstance(candidate_id, int) or isinstance(candidate_id, bool)
            for candidate_id in candidate_ids
        ):
            return failure("validation_error", "candidate_ids must be a list of integers.")
        try:
            return success(database.promote_import_candidates(candidate_ids))
        except KeyError:
            return failure("not_found", "Import candidate not found.", 404)

    @app.post("/api/v1/import-candidates/recommendations")
    def candidate_recommendations():
        """推荐处置：记入版本变更 / 新建功能 / 增强已有功能（含推荐理由）。"""
        payload = request.get_json(silent=True) or {}
        candidate_ids = payload.get("candidate_ids")
        if not isinstance(candidate_ids, list) or any(
            not isinstance(candidate_id, int) or isinstance(candidate_id, bool)
            for candidate_id in candidate_ids
        ):
            return failure("validation_error", "candidate_ids must be a list of integers.")
        return success({"recommendations": database.recommend_candidate_actions(candidate_ids)})

    @app.post("/api/v1/import-candidates/batch/confirm")
    def confirm_import_candidates():
        """按推荐处置批量提交：能建立/关联功能的建立或关联，其余记入版本变更。"""
        payload = request.get_json(silent=True) or {}
        candidate_ids = payload.get("candidate_ids")
        if not isinstance(candidate_ids, list) or any(
            not isinstance(candidate_id, int) or isinstance(candidate_id, bool)
            for candidate_id in candidate_ids
        ):
            return failure("validation_error", "candidate_ids must be a list of integers.")
        try:
            return success(database.confirm_import_candidates(candidate_ids))
        except KeyError:
            return failure("not_found", "Import candidate not found.", 404)

    @app.get("/api/v1/import-candidates/suspected-pairs")
    def suspected_candidate_pairs():
        """疑似同一变更的中英配对：人工确认后即可合并，不必逐条手工编辑。"""
        return success(
            {"pairs": database.list_suspected_candidate_pairs(requested_project_id())}
        )

    @app.post("/api/v1/import-candidates/merge")
    def merge_import_candidates():
        """把人工确认同属一条变更的中英两条合并成一条（可撤销）。"""
        payload = request.get_json(silent=True) or {}
        cn_candidate_id = payload.get("cn_candidate_id")
        en_candidate_id = payload.get("en_candidate_id")
        for value in (cn_candidate_id, en_candidate_id):
            if not isinstance(value, int) or isinstance(value, bool):
                return failure(
                    "validation_error",
                    "cn_candidate_id and en_candidate_id must be integers.",
                )
        try:
            return success(
                database.merge_bilingual_candidates(cn_candidate_id, en_candidate_id)
            )
        except KeyError:
            return failure("not_found", "Import candidate not found.", 404)
        except ValueError as error:
            return failure("validation_error", str(error))

    @app.patch("/api/v1/import-candidates/<int:candidate_id>")
    def update_import_candidate(candidate_id: int):
        payload = request.get_json(silent=True) or {}
        try:
            current = database.get_import_candidate(candidate_id)
            updated = database.update_import_candidate(
                candidate_id,
                str(payload.get("category", current["category"])),
                str(payload.get("title_cn", current["title_cn"])),
                str(payload.get("title_en", current["title_en"])),
            )
            return success(updated)
        except KeyError:
            return failure("not_found", "Import candidate not found.", 404)

    @app.post("/api/v1/import-candidates/<int:candidate_id>/<decision>")
    def review_candidate(candidate_id: int, decision: str):
        if decision not in {"approve", "reject", "restore"}:
            return failure("validation_error", "Decision must be approve, reject, or restore.")
        try:
            return success(
                review_import_candidate(
                    database,
                    candidate_id,
                    decision,
                    request.get_json(silent=True) or {},
                )
            )
        except KeyError:
            return failure("not_found", "Import candidate not found.", 404)

    return app


if __name__ == "__main__":
    create_app().run(host="127.0.0.1", port=5050, debug=True)
