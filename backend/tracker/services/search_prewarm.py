"""One replaceable background batch of current-query whitepaper previews."""
from pathlib import Path
import logging
from threading import Condition, Thread
import sqlite3

from tracker.services.section_cache import section_cache

logger = logging.getLogger(__name__)


class WhitepaperPrewarmer:
    def __init__(self):
        self._condition = Condition()
        self._serial = 0
        self._epoch = 0
        self._request_id = 0
        self._active_requests = set()
        self._query_key = None
        self._signature = None
        self._pending = None
        self._closed = False
        self._worker = Thread(target=self._work, name='search-prewarm', daemon=True)
        self._worker.start()

    def begin(self, query_key):
        """Identify requests on arrival, not completion, to reject late old work."""
        with self._condition:
            if query_key != self._query_key:
                self._query_key = query_key
                self._epoch += 1
                self._serial += 1
                self._signature = None
                self._pending = None
                self._condition.notify_all()
            self._request_id += 1
            ticket = (self._epoch, self._request_id)
            self._active_requests.add(ticket)
            return ticket

    def finish(self, ticket):
        with self._condition:
            self._active_requests.discard(ticket)
            self._condition.notify_all()

    def schedule(self, ticket, index, candidates, resolve_candidate):
        candidates = tuple(candidates[:40])
        generation = section_cache.generation()
        signature = (str(index.path), candidates, generation)
        with self._condition:
            if self._closed or ticket != (self._epoch, self._request_id) or signature == self._signature:
                return
            self._serial += 1
            self._signature = signature
            self._pending = (self._serial, generation, index, candidates, resolve_candidate)
            self._condition.notify()

    def _work(self):
        while True:
            with self._condition:
                while self._pending is None and not self._closed:
                    self._condition.wait()
                if self._closed:
                    return
                batch, self._pending = self._pending, None
            try:
                self._run(*batch)
            except Exception:
                logger.exception("Whitepaper preview prewarming failed")
                with self._condition:
                    if batch[0] == self._serial:
                        self._signature = None

    def _run(self, serial, generation, index, candidates, resolve_candidate):
        failed = False
        try:
            for source_id, locator, query in candidates:
                while True:
                    with self._condition:
                        while self._active_requests and not self._closed and serial == self._serial:
                            self._condition.wait()
                        if self._closed or serial != self._serial:
                            return
                    # Refresh waits for at most this preview, so older work cannot
                    # repopulate the cache after refresh invalidates its generation.
                    with index.refresh_lock:
                        with self._condition:
                            if self._closed or serial != self._serial:
                                return
                            if self._active_requests:
                                continue
                        if section_cache.generation() != generation:
                            return
                        try:
                            candidate = resolve_candidate(source_id)
                            meta = index.source_metadata(source_id)
                            if (not candidate or candidate.get('doc_type') != '白皮书' or not meta
                                    or meta.get('status') != 'indexed'
                                    or candidate['path'].resolve() != Path(meta['path']).resolve()):
                                failed = True
                            else:
                                preview = index.preview(source_id, locator=locator, query=query, include_images=False)
                                if preview is None or preview.get('stale'):
                                    failed = True
                        except (sqlite3.Error, OSError, ValueError, RuntimeError, KeyError):
                            failed = True
                        break
        finally:
            with self._condition:
                if failed and serial == self._serial:
                    self._signature = None

    def close(self):
        with self._condition:
            self._closed = True
            self._serial += 1
            self._pending = None
            self._condition.notify()
