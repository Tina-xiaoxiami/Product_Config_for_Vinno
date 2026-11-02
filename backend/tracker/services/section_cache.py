"""Bounded, process-local cache for verified, text-only section parsing."""
from collections import OrderedDict
from copy import deepcopy
from contextlib import contextmanager
import json
from pathlib import Path
from threading import RLock, Lock


class SectionCache:
    def __init__(self, max_entries=64, max_bytes=16 * 1024 * 1024):
        self.max_entries = max_entries
        self.max_bytes = max_bytes
        self._entries = OrderedDict()
        self._bytes = 0
        self._generation = 0
        self._lock = RLock()
        self._inflight = {}

    @contextmanager
    def singleflight(self, key):
        with self._lock:
            lock, count = self._inflight.get(key, (Lock(), 0))
            self._inflight[key] = (lock, count + 1)
        try:
            with lock:
                yield
        finally:
            with self._lock:
                lock, count = self._inflight[key]
                if count == 1:
                    del self._inflight[key]
                else:
                    self._inflight[key] = (lock, count - 1)

    def generation(self):
        with self._lock:
            return self._generation

    def clear(self):
        with self._lock:
            self._entries.clear()
            self._bytes = 0
            self._generation += 1

    def get(self, key):
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            self._entries.move_to_end(key)
            return deepcopy(entry[0])

    def put(self, key, value, generation):
        size = len(json.dumps(value, ensure_ascii=False).encode('utf-8'))
        if size > self.max_bytes:
            return
        with self._lock:
            if generation != self._generation:
                return
            previous = self._entries.pop(key, None)
            if previous:
                self._bytes -= previous[1]
            self._entries[key] = (deepcopy(value), size)
            self._bytes += size
            while len(self._entries) > self.max_entries or self._bytes > self.max_bytes:
                _, (_, removed_size) = self._entries.popitem(last=False)
                self._bytes -= removed_size


def file_cache_identity(path):
    resolved = Path(path).expanduser().resolve(strict=True)
    stat = resolved.stat()
    return resolved, (stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_ino, stat.st_dev)


section_cache = SectionCache()
