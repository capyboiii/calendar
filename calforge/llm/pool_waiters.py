"""Fair pending allocations, read/written only while the machine pool gate is held."""
import json
import os
import time
from pathlib import Path

FILE = '.calforge_waiters.json'
TTL = 60


def load(root: Path, alive) -> dict:
    try:
        state = json.loads((root / FILE).read_text(encoding='utf-8'))
    except (FileNotFoundError, ValueError):
        state = {}
    if not isinstance(state, dict):
        state = {}
    now = time.time()
    requests = []
    owners = {}
    records = state.get('requests', [])
    for r in records if isinstance(records, list) else []:
        try:
            if (not isinstance(r['token'], str) or not isinstance(r['pid'], int)
                    or not isinstance(r['created'], int) or r['role'] not in ('chat', 'image')
                    or not isinstance(r['priority'], bool) or not isinstance(r['names'], list)
                    or any(not isinstance(n, str) or '/' in n or '\\' in n for n in r['names'])):
                continue
            if r['pid'] not in owners:
                owners[r['pid']] = alive(r['pid'])
            if 0 <= now - r['seen'] < TTL and owners[r['pid']]:
                requests.append(r)
        except (KeyError, TypeError):
            continue
    streak = state.get('priority_streak', 0)
    return {'requests': requests, 'priority_streak': min(2, max(0, streak)) if isinstance(streak, int) else 0}


def save(root: Path, state: dict) -> None:
    tmp = root / (FILE + f'.{os.getpid()}.tmp')
    tmp.write_text(json.dumps(state), encoding='utf-8')
    tmp.replace(root / FILE)


def register(state, token, names, role, priority):
    now = time.time()
    request = next((r for r in state['requests'] if r['token'] == token), None)
    if request is None:
        request = {'token': token, 'pid': os.getpid(), 'created': time.time_ns()}
        state['requests'].append(request)
    request.update(names=names, role=role, priority=bool(priority), seen=now)


def allocations(state, free, slots):
    checked = {}
    def available(name, role):
        key = (name, role)
        if key not in checked:
            checked[key] = free(name, role)
        return checked[key]
    result = {}
    assigned = set()
    pending = list(state['requests'])
    streak = state['priority_streak']
    for _ in range(slots):
        runnable = [r for r in pending if any(n not in assigned and available(n, r['role']) for n in r['names'])]
        if not runnable:
            break
        urgent = [r for r in runnable if r['priority']]
        ordinary = [r for r in runnable if not r['priority']]
        choices = ordinary if ordinary and streak >= 2 else urgent or ordinary
        request = min(choices, key=lambda r: r['created'])
        name = next(n for n in request['names'] if n not in assigned and available(n, request['role']))
        result[request['token']] = name
        assigned.add(name)
        pending.remove(request)
        streak = min(2, streak + 1) if request['priority'] else 0
    return result


def granted(state, request):
    state['requests'].remove(request)
    state['priority_streak'] = min(2, state['priority_streak'] + 1) if request['priority'] else 0
