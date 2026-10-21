"""Cross-process limit on unfinished books, separate from Chrome/account leases."""
from contextlib import contextmanager
import json
import math
import os
from pathlib import Path
import threading
import time
import uuid

from .pool import AccountPool, _pid_alive

FILE = '.calforge_books.json'
_local = threading.RLock()


def limit_for_capacity(capacity):
    capacity = max(1, int(capacity))
    return min(capacity, max(2, min(4, math.ceil(capacity / 12))))


class BookBudget:
    def __init__(self, root, limit, *, rank=None, capacity=None):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.limit = max(1, int(limit))
        self.rank = rank if rank is not None else int(os.environ.get('CALFORGE_QUEUE_RANK') or 0)
        self.owner = uuid.uuid4().hex
        self.gate = AccountPool(self.root, [], cap=1, leases=True)
        self.released = set()
        self.last_error = ''
        names = [p.name for p in self.root.iterdir() if p.is_dir() and not p.name.startswith('.')]
        capacity = max(1, int(capacity or len(names) or 1))
        self.monitor = AccountPool(self.root, names, cap=capacity, global_cap=capacity, leases=True)

    @contextmanager
    def _state(self):
        with _local, self.gate._process_gate():
            try:
                data = json.loads((self.root / FILE).read_text(encoding='utf-8'))
            except FileNotFoundError:
                data = {}
            # Invalid shared state fails closed; never assume every slot is free.
            if not isinstance(data, dict):
                raise ValueError('Invalid unfinished-book state')
            alive = {}
            def live(r):
                pid = r.get('pid', 0)
                if pid not in alive:
                    alive[pid] = _pid_alive(pid)
                return alive[pid]
            keep = lambda r: not (r.get('owner') == self.owner and r.get('key') in self.released)
            data['active'] = [r for r in data.get('active', []) if live(r) and keep(r)]
            data['waiting'] = [r for r in data.get('waiting', []) if live(r) and keep(r) and time.time()-r.get('seen',0)<60]
            yield data
            tmp = self.root / (FILE + f'.{os.getpid()}.tmp')
            tmp.write_text(json.dumps(data), encoding='utf-8')
            tmp.replace(self.root / FILE)

    def acquire(self, key):
        try:
            return self._acquire(key)
        except (OSError, ValueError, TypeError, KeyError) as error:
            self.last_error = str(error)
            return False

    def _acquire(self, key):
        key = str(key)
        self.released.discard(key)
        # Check before taking the shared gate; spare_capacity uses that gate too.
        spare = not self.monitor.names or self.monitor.spare_capacity() > 0
        with self._state() as data:
            existing = next((r for r in data['active'] if r['key'] == key), None)
            if existing:
                return existing['owner'] == self.owner
            token = self.owner + ':' + key
            row = next((r for r in data['waiting'] if r['token'] == token), None)
            if row is None:
                row = dict(key=key, token=token, owner=self.owner, pid=os.getpid(), rank=self.rank,
                           created=time.time_ns())
                data['waiting'].append(row)
            row['seen'] = time.time()
            limit = data['active'][0].get('limit', self.limit) if data['active'] else self.limit
            first = min(data['waiting'], key=lambda r:(r['rank'],r['created']))
            if len(data['active']) >= limit or first['token'] != token or (data['active'] and not spare):
                return False
            data['waiting'].remove(row)
            row['limit'] = limit
            data['active'].append(row)
            return True

    def release(self, key):
        self.released.add(str(key))
        try:
            with self._state():
                pass
        except (OSError, ValueError, TypeError, KeyError) as error:
            # The next allocation retries this tombstone before counting slots.
            self.last_error = str(error)

    def close(self):
        try:
            with self._state() as data:
                for name in ('active','waiting'):
                    data[name] = [r for r in data[name] if r['owner'] != self.owner]
        except (OSError, ValueError, TypeError, KeyError):
            pass  # records are also reclaimed when the subprocess exits


def for_config(cfg, *, root=None):
    from .. import config
    from .pool import planned_cap
    capacity = int(os.environ.get('CALFORGE_GLOBAL_BROWSER_CAP') or planned_cap(cfg))
    limit = int(cfg.get('max_active_books') or limit_for_capacity(capacity))
    return BookBudget(root or config.get_profiles_dir(cfg), limit, capacity=capacity)


@contextmanager
def book_slot(cfg, key, on_event=print):
    """Single-book UI actions must obey the same cap as batch jobs."""
    budget = for_config(cfg)
    try:
        next_log = 0
        while not budget.acquire(key):
            if time.monotonic() >= next_log:
                on_event(f'⏳ Chờ cuốn đang làm hoàn tất; giới hạn chung {budget.limit} cuốn')
                next_log = time.monotonic() + 30
            time.sleep(.25)
        yield
    finally:
        budget.close()
