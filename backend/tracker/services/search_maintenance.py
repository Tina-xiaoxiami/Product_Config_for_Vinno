"""One lazy background worker for the local workbench's rebuildable search index."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from threading import Event, Lock, Thread, current_thread
import time
from typing import Any


class SearchMaintenance:
    """Schedule incremental refreshes without starting threads during app creation.

    The app calls ``ensure_started`` on its first request. ``start_thread=False``
    lets tests exercise the same scheduling rules with ``run_if_due``. The refresh
    callback shares the SearchIndex lock with synchronous refreshes and reads.
    """

    def __init__(
        self,
        refresh: Callable[[], dict[str, Any]],
        *,
        interval_seconds: float = 300,
        enabled: bool = True,
        start_thread: bool = True,
        manual_refresh: Callable[[], dict[str, Any]] | None = None,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("索引更新间隔必须大于 0 秒。")
        self._refresh = refresh
        self._manual_refresh = manual_refresh or refresh
        self._interval = float(interval_seconds)
        self._enabled = bool(enabled)
        self._start_thread = start_thread
        self._state_lock = Lock()
        self._refresh_lock = Lock()
        self._wake = Event()
        self._closed = False
        self._started = False
        self._paused = False
        self._running = False
        self._next_due = 0.0
        self._last_error = ""
        self._last_finished_at: str | None = None
        self._last_result: dict[str, Any] | None = None
        self._thread: Thread | None = None

    def ensure_started(self) -> dict[str, Any]:
        with self._state_lock:
            if not self._started and not self._closed:
                self._started = True
                if self._enabled and self._start_thread:
                    self._thread = Thread(target=self._work, name="workbench-search-index", daemon=True)
                    self._thread.start()
        return self.status()

    def status(self) -> dict[str, Any]:
        with self._state_lock:
            return {
                "enabled": self._enabled,
                "paused": self._paused,
                "started": self._started,
                "running": self._running,
                "interval_seconds": self._interval,
                "last_finished_at": self._last_finished_at,
                "last_error": self._last_error,
                "last_result": self._last_result,
            }

    def pause(self) -> dict[str, Any]:
        with self._state_lock:
            self._paused = True
        self._wake.set()
        return self.status()

    def resume(self) -> dict[str, Any]:
        with self._state_lock:
            self._paused = False
            self._next_due = 0.0
        self.ensure_started()
        self._wake.set()
        return self.status()

    def refresh_now(self, *, manual: bool = False) -> dict[str, Any]:
        if not self._refresh_lock.acquire(blocking=False):
            return {"skipped": True, "reason": "already_running"}
        with self._state_lock:
            self._running = True
        try:
            result = self._manual_refresh() if manual else self._refresh()
            with self._state_lock:
                self._last_error = ""
                self._last_result = result
            return result
        except Exception as error:
            with self._state_lock:
                self._last_error = f"更新资料索引失败（{type(error).__name__}）；可恢复来源后重试。"
            raise
        finally:
            with self._state_lock:
                self._running = False
                self._last_finished_at = datetime.now().astimezone().isoformat(timespec="seconds")
                self._next_due = time.monotonic() + self._interval
            self._refresh_lock.release()

    def run_if_due(self, *, now: float | None = None) -> bool:
        current = time.monotonic() if now is None else now
        with self._state_lock:
            if self._closed or not self._started or not self._enabled or self._paused or self._running:
                return False
            if current < self._next_due:
                return False
        try:
            result = self.refresh_now()
            if result.get("skipped"):
                return False
        except Exception:
            # refresh_now records a sanitized visible error; later cycles retry.
            pass
        with self._state_lock:
            self._next_due = current + self._interval
        return True

    def _work(self) -> None:
        while True:
            with self._state_lock:
                if self._closed:
                    return
            self.run_if_due()
            with self._state_lock:
                wait_seconds = self._interval if self._paused else max(0.05, self._next_due - time.monotonic())
            self._wake.wait(wait_seconds)
            self._wake.clear()

    def close(self) -> None:
        with self._state_lock:
            self._closed = True
            thread = self._thread
        self._wake.set()
        if thread is not None and thread is not current_thread():
            thread.join(timeout=1)
