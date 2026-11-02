"""Local personal shortcuts and verified online backups of the business database."""

from __future__ import annotations

from tracker.services.search_intent import validate_search_task, parse_version_selection

from contextlib import closing
from datetime import datetime
import json
import os
from pathlib import Path
import re
import sqlite3
from threading import RLock
from uuid import uuid4
from typing import Any


SOURCES = {"release", "config", "controlled", "training", "term", "registration",
           "product_state", "probe_version", "knowledge", "qa"}
BACKUP_ID = re.compile(r"^\d{8}-\d{6}-[a-f0-9]{8}$")
PREVIEW_ID = re.compile(r"^(controlled:\d+:(docx|pdf)|training:[a-f0-9]{24}|release:(source|change|candidate|feature|table):\d+)$")


class PersonalWorkspace:
    def __init__(self, database_path: Path):
        self.database_path = Path(database_path)
        self.path = self.database_path.with_suffix(".personal.json")
        self.backup_directory = self.database_path.parent / "backups" / "workbench"
        self._lock = RLock()

    @staticmethod
    def defaults() -> dict[str, Any]:
        return {"schema_version": 1, "saved_searches": [], "recent_documents": [],
                "index_paused": False, "last_backup": None}

    def read(self) -> dict:
        with self._lock:
            defaults = self.defaults()
            if not self.path.exists():
                return defaults
            try:
                stored = json.loads(self.path.read_text(encoding="utf-8"))
                if not isinstance(stored, dict) or stored.get("schema_version") != 1:
                    raise ValueError("个人设置格式不受支持。")
                self._validated_updates({"saved_searches": stored.get("saved_searches", []),
                                         "index_paused": stored.get("index_paused", False)})
                recent = stored.get("recent_documents", [])
                if not isinstance(recent, list) or len(recent) > 20 or any(
                    not isinstance(entry, dict)
                    or not isinstance(entry.get("preview_id"), str)
                    or not PREVIEW_ID.fullmatch(entry["preview_id"])
                    or any(not isinstance(entry.get(key), str) for key in ("title", "locator", "opened_at"))
                    for entry in recent
                ):
                    raise ValueError("最近资料记录格式无效。")
                backup = stored.get("last_backup")
                if backup is not None and (
                    not isinstance(backup, dict)
                    or not isinstance(backup.get("id"), str)
                    or not BACKUP_ID.fullmatch(backup["id"])
                    or not isinstance(backup.get("created_at"), str)
                    or type(backup.get("retention_count")) is not int
                    or not isinstance(backup.get("validation"), dict)
                ):
                    raise ValueError("备份记录格式无效。")
                return {**defaults, **stored}
            except (OSError, json.JSONDecodeError) as error:
                raise ValueError("个人设置无法读取，请保留原文件并从导出的设置恢复。") from error

    def _write(self, value: dict) -> dict:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{uuid4().hex}.tmp")
        try:
            temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
            os.chmod(temporary, 0o600)
            temporary.replace(self.path)
        finally:
            temporary.unlink(missing_ok=True)
        return value

    def update(self, payload: dict) -> dict:
        updates = self._validated_updates(payload)
        with self._lock:
            return self._write({**self.read(), **updates})

    def restore(self, payload: dict) -> dict:
        updates = self._validated_updates(payload)
        if "saved_searches" not in updates:
            raise ValueError("恢复文件缺少常用入口列表。")
        with self._lock:
            try:
                current = self.read()
            except ValueError:
                current = self.defaults()
                if self.path.exists():
                    preserved = self.path.with_name(f"{self.path.stem}.corrupt-{uuid4().hex}.json")
                    preserved.write_bytes(self.path.read_bytes())
                    os.chmod(preserved, 0o600)
            return self._write({**current, **updates})

    def _validated_updates(self, payload: dict) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("个人设置必须是对象。")
        allowed = {"saved_searches", "index_paused", "schema_version"}
        if payload.keys() - allowed:
            raise ValueError("个人设置包含不支持的字段。")
        if "schema_version" in payload and payload["schema_version"] != 1:
            raise ValueError("个人设置格式版本不受支持。")
        updates: dict[str, Any] = {}
        if "index_paused" in payload:
            if not isinstance(payload["index_paused"], bool):
                raise ValueError("自动更新开关必须为布尔值。")
            updates["index_paused"] = payload["index_paused"]
        if "saved_searches" in payload:
            searches = payload["saved_searches"]
            if not isinstance(searches, list) or len(searches) > 40:
                raise ValueError("常用搜索必须为列表，最多保存 40 项。")
            updates["saved_searches"] = [self._shortcut(item) for item in searches]
        return updates

    @staticmethod
    def _shortcut(item: dict) -> dict:
        if not isinstance(item, dict):
            raise ValueError("每个常用搜索必须为对象。")
        result: dict[str, Any] = {}
        for key, limit in (("query", 200), ("name", 100), ("model", 100)):
            value = item.get(key, "")
            if not isinstance(value, str) or len(value) > limit:
                raise ValueError("常用搜索的名称、机型或关键词无效。")
            result[key] = value.strip()
        if not result["query"]:
            raise ValueError("常用搜索需要关键词。")
        result["name"] = result["name"] or result["query"]
        sources = item.get("sources")
        if not isinstance(sources, list) or not sources or any(not isinstance(s, str) or s not in SOURCES for s in sources):
            raise ValueError("常用搜索来源无效。")
        result["sources"] = list(dict.fromkeys(sources))
        for key, choices, default in (
            ("scope", {"current", "all"}, "current"),
            ("market", {"", "domestic", "overseas"}, ""),
            ("verification", {"", "verified", "unverified", "approved", "pending_review", "not_applicable", "source_live"}, ""),
        ):
            value = item.get(key, default)
            if not isinstance(value, str) or value not in choices:
                raise ValueError("常用搜索筛选值无效。")
            result[key] = value
        project_id = item.get("projectId")
        if project_id is not None and (type(project_id) is not int or project_id < 1):
            raise ValueError("常用搜索项目无效。")
        result["projectId"] = project_id
        current_only = item.get("currentOnly", False)
        if not isinstance(current_only, bool):
            raise ValueError("当前版本筛选值无效。")
        result["currentOnly"] = current_only
        task = item.get("task", "search")
        if not isinstance(task, str):
            raise ValueError("常用搜索任务无效。")
        version_from, version_to = item.get("versionFrom", ""), item.get("versionTo", "")
        versions = item.get("versions", "")
        validate_search_task(task, version_from, version_to, versions)
        result["versions"] = ",".join(parse_version_selection(versions))
        expand_related = item.get("expandRelated", False)
        if not isinstance(expand_related, bool):
            raise ValueError("关联词扩展值无效。")
        result.update(task=task, versionFrom=version_from, versionTo=version_to, expandRelated=expand_related)
        country = item.get("country", "")
        if not isinstance(country, str) or country and not re.fullmatch(r"[A-Za-z]{2}", country):
            raise ValueError("常用搜索国家须为两位代码。")
        result["country"] = country.upper()
        return result

    def add_recent(self, payload: dict) -> dict:
        if not isinstance(payload, dict):
            raise ValueError("资料记录格式无效。")
        source_id = payload.get("preview_id", "")
        if not isinstance(source_id, str) or not PREVIEW_ID.fullmatch(source_id):
            raise ValueError("资料标识无效。")
        for key in ("title", "locator"):
            if not isinstance(payload.get(key, ""), str) or len(payload.get(key, "")) > 500:
                raise ValueError("资料记录文字无效。")
        item = {"preview_id": source_id, "title": payload.get("title", "资料"),
                "locator": payload.get("locator", ""),
                "opened_at": datetime.now().astimezone().isoformat(timespec="seconds")}
        with self._lock:
            settings = self.read()
            recent = [entry for entry in settings["recent_documents"] if entry["preview_id"] != source_id]
            return self._write({**settings, "recent_documents": [item, *recent][:20]})

    def create_backup(self) -> dict:
        with self._lock:
            settings = self.read()
            self.backup_directory.mkdir(parents=True, exist_ok=True)
            backup_id = datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid4().hex[:8]
            destination = self.backup_directory / f"{backup_id}.db"
            temporary = destination.with_suffix(".tmp")
            try:
                with closing(sqlite3.connect(self.database_path.resolve().as_uri() + "?mode=ro", uri=True)) as source:
                    with closing(sqlite3.connect(temporary)) as target:
                        source.backup(target)
                        integrity = target.execute("PRAGMA integrity_check").fetchone()[0]
                        if integrity != "ok":
                            raise ValueError("备份完整性检查未通过，原工作库未修改。")
                        counts = {f"{label}_count": target.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                                  for label, table in (("project", "projects"), ("release", "releases"), ("review", "review_decisions"))}
                os.chmod(temporary, 0o600)
                temporary.replace(destination)
                result = {"id": backup_id, "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                          "validation": {"integrity": integrity, **counts}, "retention_count": 7}
                self._write({**settings, "last_backup": result})
                backups = sorted((path for path in self.backup_directory.glob("*.db")
                                  if BACKUP_ID.fullmatch(path.stem) and path != destination),
                                 key=lambda path: (path.stat().st_mtime_ns, path.name))
                for old in backups[:-6]:
                    old.unlink()
                return result
            finally:
                temporary.unlink(missing_ok=True)

    def ensure_daily_backup(self) -> dict:
        with self._lock:
            last = self.read().get("last_backup")
            if last and last["created_at"][:10] == datetime.now().date().isoformat() and self.backup_file(last["id"]):
                return last
            return self.create_backup()

    def backup_file(self, backup_id: str) -> Path | None:
        if not BACKUP_ID.fullmatch(backup_id):
            return None
        path = self.backup_directory / f"{backup_id}.db"
        return path if path.is_file() and not path.is_symlink() else None
