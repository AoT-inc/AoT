# coding=utf-8
"""노트 구간 ↔ 예정 링크의 정본 로직.

읽기·쓰기·정리가 **여기 하나**에 있다. 흩으면 이 레포가 반복해서 데인
"읽는 경로마다 기준이 다름" 이 그대로 재현된다 — 어떤 화면은 끊어진 링크를
지우고 어떤 화면은 남기면, 같은 노트가 화면마다 다른 개수의 일정을 갖는다.

세 가지 판단이 여기 모여 있다.

1. **재탐색** — 노트를 고치면 offset 이 어긋난다. 선택 당시 텍스트로 다시
   찾아 offset 을 갱신한다. 찾지 못하면 하이라이트만 포기하고 링크는 남긴다.
2. **자가 치유** — 대상 일정이 사라졌으면 읽는 김에 링크를 걷는다. 일정
   삭제 경로가 한 곳이 아니라, 삭제 쪽에서 챙기게 하면 언젠가 빠뜨린다.
3. **고아 판정** — 사용자가 그 구간을 지우면 "이 예정도 취소할까요" 를
   물어야 한다. 묻지 않고 지우면 오타 하나 고치다 잡아둔 약속이 사라지고,
   묻지 않고 남기면 본문에 없는 약속이 조용히 남는다. **판정만 여기서 하고
   결정은 사람이 한다.**
"""
from flask import current_app

from aot.aot_flask.extensions import db
from aot.databases.models import NoteScheduleLink
from aot.databases.models.scheduler import SchedulerJobMeta

# 재탐색은 정확히 같은 문자열만 본다. 부분 일치·유사도로 넓히면 비슷한 문장이
# 여럿인 노트에서 **엉뚱한 구간**에 하이라이트가 붙는데, 그건 링크가 끊긴
# 것보다 나쁘다(사용자는 잘못된 자리를 사실로 읽는다).
_MIN_SNAPSHOT = 1


def _job_map(links):
    uids = {l.job_uid for l in links}
    if not uids:
        return {}
    rows = SchedulerJobMeta.query.filter(
        SchedulerJobMeta.unique_id.in_(uids)).all()
    return {r.unique_id: r for r in rows}


def relocate(link, body):
    """편집된 본문에서 구간을 다시 찾는다. (start, end) 또는 None.

    먼저 원래 자리를 확인하고(대개 맞다 — 뒤쪽을 고쳐도 앞은 그대로다),
    아니면 전체에서 스냅샷을 찾는다. **첫 번째 일치만 쓴다** — 같은 문장이
    여러 번 나오면 어느 것이 그 약속인지 알 방법이 없고, 추측해서 옮기면
    사용자는 옮겨진 자리를 사실로 읽는다.
    """
    snap = link.text_snapshot or ''
    if len(snap) < _MIN_SNAPSHOT or not body:
        return None
    s, e = link.start_offset or 0, link.end_offset or 0
    if 0 <= s < e <= len(body) and body[s:e] == snap:
        return s, e
    idx = body.find(snap)
    if idx < 0:
        return None
    return idx, idx + len(snap)


def links_for_note(note, prune=True):
    """이 노트에 걸린 링크들. `links_for_notes` 의 1건짜리 껍데기."""
    return links_for_notes([note], prune=prune).get(note.unique_id, [])


def links_for_notes(notes, prune=True):
    """{노트 uuid: [링크 dict]} — **배치로 읽는다.**

    노트마다 따로 부르면 목록 한 번에 노트 수만큼 질의가 나간다(대상 하나에
    노트 30건이면 30회 + 일정 조회 30회). 화면은 한 번에 다 그리므로 질의도
    한 번이어야 한다.

    `prune=True` 면 대상 일정이 사라진 링크를 이 자리에서 걷는다(자가 치유).
    읽기 요청이 쓰기를 하는 것이 마음에 걸릴 수 있지만, 대안은 삭제 경로
    전부가 링크를 기억하는 것이고 그쪽이 훨씬 잘 깨진다.
    """
    by_uid = {n.unique_id: n for n in notes if n is not None}
    if not by_uid:
        return {}
    links = (NoteScheduleLink.query
             .filter(NoteScheduleLink.note_id.in_(list(by_uid)))
             .order_by(NoteScheduleLink.start_offset).all())
    if not links:
        return {}

    jobs = _job_map(links)
    dangling = [l for l in links if l.job_uid not in jobs]
    if prune and dangling:
        try:
            for l in dangling:
                db.session.delete(l)
            db.session.commit()
        except Exception:
            db.session.rollback()
            current_app.logger.exception('note_links: 끊어진 링크 정리 실패')
        links = [l for l in links if l.job_uid in jobs]

    out = {}
    dirty = False
    for l in links:
        job = jobs.get(l.job_uid)
        note = by_uid.get(l.note_id)
        if job is None or note is None:
            continue
        span = relocate(l, note.note or '')
        if span and (span[0] != l.start_offset or span[1] != l.end_offset):
            l.start_offset, l.end_offset = span
            dirty = True
        out.setdefault(l.note_id, []).append({
            'link_id': l.unique_id,
            'job_uid': l.job_uid,
            'start': span[0] if span else None,
            'end': span[1] if span else None,
            # 구간을 못 찾아도 무엇에 대한 약속이었는지는 말해 준다.
            'text': l.text_snapshot,
            'orphaned': span is None,
            'when': job.schedule_time.isoformat() if job.schedule_time else None,
            'anchor_tz': getattr(job, 'anchor_tz', None),
            'state': job.state,
        })
    if dirty:
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
    return out


def orphaned_after_edit(note, new_body):
    """본문을 `new_body` 로 바꾸면 구간이 사라지는 링크들.

    **저장하기 전에** 부른다 — 저장한 뒤 물으면 사용자는 이미 없어진 글을
    보며 "무엇을 지웠는지" 를 기억해내야 한다.
    """
    links = NoteScheduleLink.query.filter_by(note_id=note.unique_id).all()
    if not links:
        return []
    jobs = _job_map(links)
    out = []
    for l in links:
        if l.job_uid not in jobs:
            continue
        if relocate(l, new_body or '') is None:
            job = jobs[l.job_uid]
            out.append({
                'link_id': l.unique_id,
                'job_uid': l.job_uid,
                'text': l.text_snapshot,
                'when': job.schedule_time.isoformat() if job.schedule_time else None,
            })
    return out


def drop_for_note(note_uid):
    """노트가 사라질 때 그 링크들을 함께 걷는다. 지운 개수를 돌려준다.

    **예정은 지우지 않는다.** 노트를 지우는 것과 약속을 취소하는 것은 다른
    결정이고, 사람은 앞의 것만 말했다. 예정은 `/scheduler` 에 그대로 남아
    거기서 취소할 수 있다.

    이것이 없으면 링크는 아무 데서도 안 읽히는 채 DB 에 영원히 남는다 —
    `links_for_notes` 가 노트 기준으로 읽으므로 노트가 없으면 조회 자체가
    닿지 않아, 읽을 때 걷는 자가 치유도 그 행에는 닿지 못한다.

    **노트 삭제 경로를 새로 만들면 이 호출도 함께 붙일 것** (현재 2곳:
    `utils_notes.note_del`, `routes_notes_api.api_notes_delete`).
    """
    if not note_uid:
        return 0
    rows = NoteScheduleLink.query.filter_by(note_id=note_uid).all()
    for r in rows:
        db.session.delete(r)
    return len(rows)


def unlink(link, cancel_job=False):
    """링크를 끊는다. `cancel_job` 이면 예정도 함께 취소한다.

    **기본은 예정을 남기는 것**이다. 이미 잡힌 약속이 글 편집으로 조용히
    사라지면 안 된다 — 사람이 그러라고 말했을 때만 취소한다.

    예정을 지울 때는 감사 로그를 **먼저** 지운다. `scheduler_audit_log`
    가 정수 `job_meta_id` 를 NOT NULL 로 물고 있어, 그냥 지우면
    IntegrityError 로 통째로 실패한다(실제로 겪었다).
    """
    job_uid = link.job_uid
    db.session.delete(link)
    if cancel_job:
        job = SchedulerJobMeta.query.filter_by(unique_id=job_uid).first()
        if job is not None:
            try:
                from aot.databases.models.scheduler import SchedulerAuditLog
                for row in SchedulerAuditLog.query.filter_by(
                        job_meta_id=job.id).all():
                    db.session.delete(row)
            except Exception:
                current_app.logger.exception('note_links: 감사 로그 정리 실패')
            db.session.delete(job)
    db.session.commit()
    return job_uid
