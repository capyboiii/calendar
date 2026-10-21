"""Shared source and durable completion plans for 1–5 books from one link."""
from __future__ import annotations

import hashlib
import io
import json
import os
import time
from contextlib import contextmanager
from pathlib import Path

from PIL import Image

from . import fetch, prompts, session, store
from ..imagegen.driver import TempError


def assignments(source_count: int, book_count: int) -> list[dict]:
    if not 1 <= source_count <= 12 or not 1 <= book_count <= 5:
        raise ValueError("Cần 1–12 artwork nguồn và 1–5 cuốn")
    return [dict(id=f"b{b:02d}m{m:02d}", book_index=b, artwork_index=m)
            for b in range(1, book_count + 1) for m in range(source_count + 1, 13)]


def variant_assignments(source_count, book_count):
    assignments(source_count, book_count)  # validate bounds
    return [dict(id=f"b{b:02d}m{m:02d}", book_index=b, artwork_index=m,
                 reference_index=m if m <= source_count else 1,
                 concept="variation" if m <= source_count else "new")
            for m in range(1, 13) for b in range(1, book_count + 1)]


@contextmanager
def group_lock(path):
    """Nonblocking OS lock: siblings yield to the scheduler without holding an account."""
    from .run import PoolWaiting
    handle = (path / ".prepare.lock").open("a+b")
    locked = False
    try:
        handle.seek(0)
        if os.name == "nt":
            import msvcrt
            if os.fstat(handle.fileno()).st_size == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                raise PoolWaiting("nhóm đang lấy ảnh nguồn/lập kế hoạch") from None
        else:
            import fcntl
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                raise PoolWaiting("nhóm đang lấy ảnh nguồn/lập kế hoạch") from None
        locked = True
        yield
    finally:
        if locked:
            if os.name == "nt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def source_valid(d):
    data, refs = store.read(d), store.refs(d)
    if not data.get("refs_complete") or len(refs) != data.get("refs_count") or not 1 <= len(refs) <= 12:
        return False
    for ref in refs:
        try:
            with Image.open(ref) as im:
                im.verify()
            with Image.open(ref) as im:
                im.load()
        except PermissionError:
            raise
        except (OSError, ValueError, SyntaxError):
            return False
    return True


def fingerprint(refs):
    return hashlib.sha256(b"".join(hashlib.sha256(p.read_bytes()).digest() for p in refs)).hexdigest()


def valid_generated(data):
    if session.landscape_ok(data) is not None:
        return False
    try:
        with Image.open(io.BytesIO(data)) as im:
            im.verify()
        with Image.open(io.BytesIO(data)) as im:
            im.load()
    except (OSError, ValueError, SyntaxError):
        return False
    return True


def validate_plan(data, jobs):
    rows = data.get("artworks") if isinstance(data, dict) else None
    if not isinstance(rows, list) or len(rows) != len(jobs):
        raise TempError("kế hoạch artwork thiếu/sai số lượng")
    expected = {job["id"] for job in jobs}
    result = {}
    for row in rows:
        if not isinstance(row, dict) or row.get("id") not in expected or row["id"] in result:
            raise TempError("kế hoạch artwork sai hoặc trùng phân công")
        prompt = row.get("prompt")
        if not isinstance(prompt, str) or len(prompt.strip()) < 80:
            raise TempError("prompt artwork trống hoặc quá ngắn")
        result[row["id"]] = prompt.strip()
    if len(set(result.values())) != len(result):
        raise TempError("kế hoạch có prompt trùng nhau")
    return result


def prepare(b, accts, stop=None):
    from .run import Book, run_stage
    from ..ideation.extract import extract_json
    d = store.source_dir(b.d)
    with group_lock(d):
        if store.read(d).get('planning_mode') == 'single_session':
            prepare_single_session(b, accts, stop)
            b.status(source_count=len(store.refs(d)), refs_count=len(store.refs(d)), refs_complete=True)
            return
        shared = Book(b.cfg, d, b.on_event)
        if not source_valid(d):
            # Never silently change originals underneath books already using them.
            if store.read(d).get("source_fingerprint"):
                raise TempError("bộ ảnh nguồn đã dùng bị hỏng; cần khôi phục ảnh nguồn trước khi chạy tiếp")
            b.status(stage="lấy ảnh nguồn dùng chung")
            run_stage(accts, f"{d.name} lấy ảnh mẫu từ link",
                      lambda s, n: fetch.fetch_work(shared, s, n), stop=stop)
        if not source_valid(d):
            raise TempError("chưa có bộ artwork nguồn hợp lệ")
        refs = store.refs(d)
        digest = fingerprint(refs)
        metadata = store.read(d)
        if metadata.get("source_fingerprint") not in (None, digest):
            raise TempError("bộ ảnh nguồn đã thay đổi; dừng để tránh trộn artwork")
        variants = b.item.get("kind") == "source_variants"
        jobs = (variant_assignments if variants else assignments)(len(refs), int(b.item["book_count"]))
        if variants:
            # Start this book as soon as its own plan is ready; do not make it wait
            # for all 60 prompts in a five-book group.
            jobs = [job for job in jobs if job['book_index'] == b.item['book_index']]
        plan = metadata.get("completion_plan", {})
        if not isinstance(plan, dict):
            plan = {}
        for offset in range(0, len(jobs), 10):
            batch = jobs[offset:offset + 10]
            if all(isinstance(plan.get(job["id"]), str) and len(plan[job["id"]]) >= 80 for job in batch):
                continue
            b.status(stage=f"lập kế hoạch ảnh bù ({offset}/{len(jobs)})")

            def work(s, name):
                if len(refs) > 10:
                    s.attach(refs[10:])
                    s.ask_text(f"These are source artworks numbered {list(range(11, len(refs)+1))} in attachment order. "
                               "Study and remember their scenes, "
                               "clothing, composition and integral text so subsequent new concepts avoid duplicating them. "
                               "Briefly acknowledge only; do not generate images. The next message contains the primary "
                               "reference as its first attachment and the other source artworks.")
                s.attach(refs[:10])
                ask = prompts.expansion_plan(batch, plan, len(refs), b.item["book_count"], variants=variants)
                for attempt in range(3):
                    answer = s.ask_text(ask)
                    try:
                        parsed = validate_plan(extract_json(answer), batch)
                        if set(parsed.values()) & set(plan.values()):
                            raise TempError("prompt lặp lại kế hoạch trước")
                        return parsed
                    except (ValueError, TypeError, TempError) as error:
                        if attempt == 2:
                            raise TempError(f"kế hoạch artwork không hợp lệ: {error}") from error
                        ask = f"Correct the JSON only. Error: {error}. Required assignments: {json.dumps(batch)}"

            # run_stage returns account name, so persist the validated plan inside its work.
            def persist(s, name):
                additions = work(s, name)
                plan.update(additions)
                store.write(d, source_fingerprint=digest, source_count=len(refs), completion_plan=plan)

            run_stage(accts, f"{d.name} lập kế hoạch ảnh bù", persist, stop=stop)
        store.write(d, source_fingerprint=digest, source_count=len(refs), completion_plan=plan)
    # Copy originals byte-for-byte. No generation or upscale in the artwork phase.
    if not variants:
        for month, ref in enumerate(refs, 1):
            if b.done(f"m{month:02d}") is None:
                with b.lock:
                    session.save(ref.read_bytes(), b.raw(f"m{month:02d}"))
    b.status(source_count=len(refs), refs_count=len(refs), refs_complete=True)
    b._grid_ready_check()


def prepare_single_session(b, accts, stop=None):
    """Plan each source's N variants together; distribute sources across the shared pool.

    The historical planning_mode name remains readable for existing queued groups.
    Completed assignments are never discarded when resuming an older group.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from threading import Lock
    from .run import Book, StageFailed, run_stage
    from ..ideation.extract import extract_json
    d = store.source_dir(b.d)
    data = store.read(d)
    if not source_valid(d):
        if data.get('source_fingerprint'):
            raise StageFailed('ảnh nguồn đã dùng bị hỏng; không tự lấy lại để trộn kế hoạch')
        b.status(stage='lấy ảnh nguồn dùng chung')
        tried = set()
        def fetch_source(s, name):
            try:
                fetch.fetch_work(Book(b.cfg, d, b.on_event), s, name)
            except TempError:
                tried.add(name)
                raise
        run_stage(accts, f'{d.name} lấy ảnh nguồn dùng chung',
                  fetch_source, avoid=tried, stop=stop)
    if not source_valid(d):
        raise TempError('chưa có bộ artwork nguồn hợp lệ')
    refs = store.refs(d)
    digest = fingerprint(refs)
    data = store.read(d)
    if data.get('source_fingerprint') not in (None, digest):
        raise StageFailed('bộ ảnh nguồn đã thay đổi giữa lúc lập kế hoạch')
    jobs = variant_assignments(len(refs), b.item['book_count'])
    plan = dict(data.get('completion_plan') or {})
    if data.get('plan_ready'):
        validate_plan({'artworks': [{'id': j['id'], 'prompt': plan.get(j['id'])} for j in jobs]}, jobs)
        recover_preparation_children(b.cfg, d)
        return
    store.write(d, source_fingerprint=digest, source_count=len(refs),
                planner_strategy='per_artwork', plan_ready=False)
    write_lock = Lock()

    def plan_month(month):
        batch = [j for j in jobs if j['artwork_index'] == month]
        if all(isinstance(plan.get(j['id']), str) and len(plan[j['id']]) >= 80 for j in batch):
            return
        def work(s, name):
            if stop and stop.is_set():
                raise StageFailed('người dùng dừng; giữ kế hoạch đã lưu')
            # All N variants share one request/session. Other source artworks can
            # be planned concurrently by other accounts, without a group owner.
            s.attach([refs[batch[0]['reference_index'] - 1]])
            local_jobs = [dict(j, reference_index=1) for j in batch]
            with write_lock:
                previous = dict(plan)
                b.status(stage=f'lập idea song song: artwork {month}/12')
            ask = prompts.expansion_plan(local_jobs, previous, 1, b.item['book_count'], variants=True)
            for attempt in range(3):
                answer = s.ask_text(ask)
                try:
                    additions = validate_plan(extract_json(answer), batch)
                    with write_lock:
                        batch_ids = {j['id'] for j in batch}
                        if set(additions.values()) & {v for k, v in plan.items() if k not in batch_ids}:
                            raise TempError('prompt lặp nguyên văn trong kế hoạch')
                        # Preserve any completed assignments from an interrupted group.
                        for key, value in additions.items():
                            if not isinstance(plan.get(key), str) or len(plan[key]) < 80:
                                plan[key] = value
                        planners = dict(store.read(d).get('artwork_planners') or {})
                        planners[str(month)] = dict(account=name, chat=s.chat_url())
                        store.write(d, completion_plan=dict(plan), artwork_planners=planners)
                    b.on_event(f'[{name}] artwork {month}: đã chốt {len(batch)} idea cho các cuốn')
                    return
                except (ValueError, TypeError, TempError) as error:
                    if attempt == 2:
                        raise TempError(f'kế hoạch artwork {month} chưa hợp lệ: {error}') from error
                    ask = f'Correct JSON only. Error: {error}. Assignments:\n{json.dumps(local_jobs)}'
        run_stage(accts, f'{d.name} lập idea artwork {month}', work, stop=stop)

    workers = max(1, min(12, len(accts.names) if accts is not None else 1))
    errors = []
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix='clone-plan') as executor:
        futures = [executor.submit(plan_month, month) for month in range(1, 13)]
        for future in as_completed(futures):
            try:
                future.result()
            except Exception as error:
                errors.append(error)
    if errors:
        raise errors[0]
    validate_plan({'artworks': [{'id': j['id'], 'prompt': plan.get(j['id'])} for j in jobs]}, jobs)
    store.write(d, completion_plan=plan, plan_ready=True)
    recover_preparation_children(b.cfg, d)
    b.on_event(f'Đã chốt {len(jobs)} prompt theo từng artwork; bắt đầu phân phối vẽ')


def recover_preparation_children(cfg, source):
    """A sibling may have completed shared preparation after this child failed."""
    data = store.read(source)
    if not data.get('plan_ready'):
        return
    for child in data.get('children', []):
        path = store.item_dir(Path(cfg['projects_dir']), child['id'])
        item = store.read(path)
        if (item.get('status') == 'failed' and item.get('stage') in
                ('lấy ảnh nguồn dùng chung', 'lấy ảnh mẫu từ link') and
                'chưa xong sau' in item.get('reason', '')):
            store.write(path, status='pending', stage='nguồn và idea chung đã sẵn sàng',
                        reason='', art_state='queued', preparation_recovered=True)


def generate(b, s, name, *, months=None, yield_check=None):
    d = store.source_dir(b.d)
    if store.read(d).get('planning_mode') == 'single_session' and not store.read(d).get('plan_ready'):
        raise TempError('kế hoạch cả nhóm chưa chốt; chưa được phân phối vẽ')
    refs = store.refs(d)
    plan = store.read(d).get("completion_plan", {})
    attached = False
    variants = b.item.get("kind") == "source_variants"
    assigned_months = b.missing("m") if months is None else months
    for month in assigned_months:
        if b.done(f"m{month:02d}"):
            continue
        if not variants and month <= len(refs):
            raise TempError("artwork nguồn chưa được lưu đầy đủ")
        ident = f"b{b.item['book_index']:02d}m{month:02d}"
        prompt = plan.get(ident)
        if not prompt:
            raise TempError(f"thiếu prompt đã phân công cho {ident}")
        saved = d / "generated" / ident
        pending_base = d / 'candidates' / ident
        pending = next((p for p in pending_base.parent.glob(ident + '.*')
                        if p.suffix.lower() in store.IMG_EXT and valid_generated(p.read_bytes())), None)
        cached = next((p for p in saved.parent.glob(ident + ".*")
                       if p.suffix.lower() in store.IMG_EXT and valid_generated(p.read_bytes())), None)
        if cached:
            with b.lock:
                session.save(cached.read_bytes(), b.raw(f"m{month:02d}"))
            b._grid_ready_check()
            if pending:
                pending.unlink(missing_ok=True)
            continue
        b.status(stage=f"vẽ artwork cuốn {b.item['book_index']}/{b.item['book_count']} (tháng {month})")
        # One assigned image per turn; never fill the next month with an extra image.
        reference = refs[month - 1] if variants and month <= len(refs) else refs[0]
        if variants and pending:
            # A network/DOM failure in visual verification must not throw away
            # an already-downloaded image and pay for another generation.
            s.attach([reference, pending])
            reason = inspect_artwork(s, attached_candidate=True)
            if not reason:
                data = pending.read_bytes()
                session.save(data, saved)
                with b.lock:
                    session.save(data, b.raw(f'm{month:02d}'))
                pending.unlink(missing_ok=True)
                b._grid_ready_check()
                continue
            pending.replace(pending.with_suffix(f'.rejected-{time.time_ns()}'))
        known = {hashlib.sha256(p.read_bytes()).digest() for p in refs}
        known.update(hashlib.sha256(p.read_bytes()).digest() for p in saved.parent.glob("*")
                     if p.suffix.lower() in store.IMG_EXT)
        ask = prompts.expansion_render(prompt)
        valid = None
        for attempt in range(3 if variants else 1):
            turn = s.ask_images(ask, 1, attach=[reference] if variants and attempt == 0
                                else (refs[:10] if not variants and not attached else None))
            attached = True
            valid = next((data for data in turn.images if valid_generated(data)
                          and hashlib.sha256(data).digest() not in known), None)
            if turn.problem:
                raise turn.problem
            reason = "No valid, distinct landscape artwork was received."
            if valid is not None and variants:
                pending = session.save(valid, pending_base)
                reason = inspect_artwork(s)
                if reason:
                    pending.replace(pending.with_suffix(f'.rejected-{time.time_ns()}'))
            if valid is not None and not reason:
                break
            if valid is not None and not variants:
                break
            valid = None
            b.on_event(f"[{name}] {ident}: vẽ lại — {reason}")
            ask = ("Correct the last image and generate ONE replacement artwork. " + reason + "\n"
                   + prompts.expansion_render(prompt))
        if valid is None:
            raise TempError(f"artwork {ident} chưa qua kiểm tra: {reason}")
        session.save(valid, saved)
        with b.lock:
            session.save(valid, b.raw(f"m{month:02d}"))
        if variants and pending:
            pending.unlink(missing_ok=True)
        b.on_event(f"[{name}] {ident}: đã lưu")
        b._grid_ready_check()
        if turn.problem:
            raise turn.problem
        if yield_check and month != assigned_months[-1] and yield_check():
            from .run import PoolWaiting
            raise PoolWaiting("nhường tài khoản sau khi lưu artwork cho việc đang chờ")
    # Metadata must see the full book, not just this session's completion images.
    s.has_art = False


def inspect_artwork(s, *, attached_candidate=False):
    from ..ideation.extract import extract_json
    target = ("Visually inspect the candidate in the LAST attachment against the FIRST attachment (source artwork). "
              if attached_candidate else "Visually inspect the image you JUST GENERATED against the attached source artwork. ")
    answer = s.ask_text(target +
        "Return ONLY JSON with boolean keys upright, artwork_only, distinct, and a short reason string. "
        "upright: the scene reads in its natural orientation, with coherent gravity and upright architecture/lettering; "
        "a naturally reclining person is allowed, a rotated or tilted photographed page is not. "
        "artwork_only: flat full-bleed illustration with no paper, calendar grids, binding, mockup background or page edges. "
        "distinct: a genuinely different action/scene/composition and appropriate clothing versus the source, "
        "rather than its copy, crop, rotation or recolor. Be critical: set false if any criterion fails.")
    try:
        report = extract_json(answer)
    except (ValueError, TypeError) as error:
        raise TempError('kiểm tra ảnh trả JSON không đọc được; giữ ảnh để kiểm tra lại') from error
    if any(type(report.get(key)) is not bool for key in ('upright', 'artwork_only', 'distinct')):
        raise TempError('kiểm tra ảnh thiếu kết quả hợp lệ; giữ ảnh để kiểm tra lại')
    if all(report.get(key) is True for key in ("upright", "artwork_only", "distinct")):
        return ""
    return str(report.get("reason") or "Orientation, artwork-only framing or substantial variation failed.")[:1000]


def generate_parallel(b, accts, stop=None):
    """Independent images share the existing account pool; never reserve an outer account."""
    from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
    from .run import PoolWaiting, run_stage
    data = store.read(store.source_dir(b.d))
    if data.get('planning_mode') == 'single_session' and not data.get('plan_ready'):
        raise TempError('kế hoạch cả nhóm chưa chốt; chưa được mượn tài khoản vẽ')
    months = b.missing("m")
    if not months:
        return
    # Share actual Chrome/RAM capacity among books with artwork still to do,
    # rather than assigning by account count or the original group size.
    count = max(1, len(accts.names))
    capacity = getattr(accts.pool, 'image_capacity', lambda: count)()
    if isinstance(capacity, int) and not isinstance(capacity, bool):
        count = min(count, max(1, capacity))
    cached = getattr(accts, '_clone_art_share', (0, 0))
    if time.monotonic() < cached[0]:
        contenders = cached[1]
    else:
        contenders = 0
        from ..imagegen.plan import job_done
        for other in store.pending(b.cfg['projects_dir']):
            selected = getattr(accts, 'clone_item_ids', None)
            if selected is not None and other.name not in selected:
                continue
            item = store.read(other)
            if item.get('status') != 'running':
                continue
            path = Path(item['book']) if item.get('book') else other / 'work'
            if any(job_done(path, f'm{m:02d}') is None for m in range(1, 13)):
                contenders += 1
        accts._clone_art_share = (time.monotonic() + .75, contenders)
    workers = min(len(months), max(1, (count + max(1, contenders) - 1) // max(1, contenders)))
    errors = []
    chunks = [months[i::workers] for i in range(workers)]
    from ..llm.pool import IMAGE
    previous_workers = int(store.read(b.d).get('pool_art_workers') or 0)
    for index in range(workers, min(previous_workers, 12)):
        accts.pool.cancel_wait(IMAGE, f'{b.d.resolve()}:art:worker:{index}')
    if previous_workers != workers:
        b.status(pool_art_workers=workers)
    def work(index, chunk):
        accts._request.ident = f"{b.d.resolve()}:art:worker:{index}"
        accts._request.defer = True
        accts._request.priority = False
        waiting = False
        try:
            def render(s, name):
                b._watch(s, name, f"artwork {chunk}")
                generate(b, s, name, months=chunk,
                         yield_check=lambda: accts.pool.should_yield(name))
            run_stage(accts, f"{b.d.name} artwork {chunk}",
                      render, stop=stop)
        except PoolWaiting:
            waiting = not (stop and stop.is_set())
            raise
        finally:
            # Keep queued requests visible between scheduler retries so current
            # owners can see them and yield after saving an image.
            if not waiting:
                accts.pool.cancel_wait(IMAGE, accts._request.ident)
            accts._request.ident = None
    with ThreadPoolExecutor(max_workers=workers) as executor:
        active = {executor.submit(work, index, chunk): index for index, chunk in enumerate(chunks)}
        retry = {}
        while active:
            finished, _ = wait(active, timeout=.5, return_when=FIRST_COMPLETED)
            for future in finished:
                index = active.pop(future)
                try:
                    future.result()
                except PoolWaiting:
                    # A yielded branch must be able to borrow again while its
                    # siblings are still drawing. Otherwise their long turns
                    # leave newly freed accounts idle behind a group barrier.
                    retry[index] = time.monotonic() + .75
                except Exception as error:
                    errors.append(error)
            if errors or (stop and stop.is_set()):
                continue
            # If every branch is waiting, return to the outer scheduler rather
            # than keeping an executor alive with no useful work.
            if not active:
                break
            for index, ready_at in list(retry.items()):
                if time.monotonic() >= ready_at:
                    active[executor.submit(work, index, chunks[index])] = index
                    del retry[index]
    fatal = next((e for e in errors if not isinstance(e, PoolWaiting)), None)
    if fatal:
        clear_art_waits(b.d, accts)
        raise fatal
    if b.missing("m"):
        raise PoolWaiting("artwork còn chờ tài khoản")


def clear_art_waits(d, accts):
    from ..llm.pool import IMAGE
    for index in range(min(12, int(store.read(d).get('pool_art_workers') or 0))):
        accts.pool.cancel_wait(IMAGE, f'{d.resolve()}:art:worker:{index}')
