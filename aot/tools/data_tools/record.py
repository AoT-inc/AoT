import logging

logger = logging.getLogger(__name__)


from aot.aot_flask.extensions import db
from aot.databases.models import GeoShape
from aot.databases.models import Input
from aot.databases.models import Notes
from aot.databases.models import Output
from aot.utils.time_utils import serialize_ts
from aot.utils.time_utils import to_local
from datetime import datetime
from datetime import timedelta
from sqlalchemy import or_
import json


class RecordToolsMixin:

    @classmethod
    def search_notes_tool(cls, query=None, category=None, limit=10,
                          target_name=None, target_id=None, target_names=None,
                          **extra):
        """
        [분류 C - 노트/일정 읽기 도구]
        노트(메모, 일정, 작업 기록)를 조회합니다. 두 가지 모드:

        1) 위치/엔티티별 조회 (권장): target_name 또는 target_id를 주면 그 구역·
           장치에 부착된 노트를 모두 반환합니다. "3-1 구역 노트 요약" 같은 요청은
           반드시 이 모드로 — 노트는 target_id로 엔티티에 붙어 있고 본문에 구역명이
           없을 수 있어 키워드 검색으로는 안 잡힙니다.
        2) 키워드 검색: query로 name/tags/note LIKE 검색.

        Args:
            query (str): 검색 키워드. target_name과 함께 주면 그 엔티티 내에서 추가 필터.
            category (str): 카테고리 필터. None이면 전체.
            limit (int): 최대 반환 건수(기본 10).
            target_name (str): 노트가 붙은 위치/장치 이름(예: '3-1', '1포장 1-1', '밸브1').
            target_id (str): 대상 unique_id(이미 아는 경우 target_name 대신).
            target_names (list): 여러 곳을 한 번에(최대 MAX_READ_TARGETS, 3-F).
                곳마다 target_name 하나로 부른 응답을 results 에 담는다.
        """
        if target_names:
            tokens, err = cls._targets_arg(target_name, target_names,
                                           'target_names')
            if err:
                return err
            if len(tokens) > 1:
                return cls._for_each_target(tokens, lambda t: cls.search_notes_tool(
                    query=query, category=category, limit=limit, target_name=t))
            target_name = tokens[0]
        try:
            if not target_name:
                from aot.tools.target_names import get_target_name_alias
                target_name = get_target_name_alias(extra)

            from aot.databases.models.notes import Notes
            from sqlalchemy import or_

            resolved_name = None
            candidate_ids = []
            # Resolve a location/entity NAME → ALL candidate target_ids. A device
            # exists as an Input/Output row AND as map shape(s) with different
            # unique_ids, and a note may be attached to any of them — so query the
            # union, not just the single most-specific match.
            scope = None
            if target_id:
                candidate_ids = [target_id]
            elif target_name:
                # 대상 안에서 일어나는 일 **전부** — 구역·시설·장치·식생.
                # 예전에는 site 일 때만 자손 도형을 붙였고, 식생은 GeoShape 가
                # 아니라 어느 층위에서도 보이지 않았다(2026-08-18 실측: 구역을
                # 물어도 그 안 식생 노트가 0건).
                candidate_ids, scope = \
                    cls._scope_for_target(target_name)
                resolved_name = scope.get('resolved_name')
                if not candidate_ids:
                    return {
                        "status": "success", "count": 0, "results": [],
                        "scope": scope,
                        "message": f"Location/device '{target_name}' was not found.",
                        "warning": (
                            "The name did not resolve, so this is NOT evidence "
                            "that there are no notes. Ask for the exact name, or "
                            "call resolve_target first."),
                    }

            # The LLM frequently passes an ENTITY NAME in `query` instead of
            # `target_name` (observed: {'query': 'v111'}). A note's text rarely
            # contains the entity's name, so a pure keyword search misses it and
            # wrongly reports "no notes". If `query` resolves to an entity, treat
            # it as a target too (and skip the keyword LIKE that would AND it back
            # to zero). Only when nothing resolves is `query` a real keyword.
            entity_query = False
            if not candidate_ids and query and query.strip():
                _q_ids, _q_name = \
                    cls._resolve_note_target_ids(query.strip())
                if _q_ids:
                    candidate_ids = _q_ids
                    resolved_name = resolved_name or _q_name
                    entity_query = True

            if not candidate_ids and not (query and query.strip()):
                return {"error": "Either 'query' or 'target_name' (a location/device) is required."}

            db_query = Notes.query.filter(Notes.is_archived == False)  # noqa: E712

            if candidate_ids:
                # Per-entity read — matches the web UI /notes/target/<id>, but
                # across every identity the named device/shape resolves to.
                db_query = db_query.filter(Notes.target_id.in_(candidate_ids))
            if query and query.strip() and not entity_query:
                _q = f"%{query.strip()}%"
                db_query = db_query.filter(or_(
                    Notes.name.like(_q), Notes.tags.like(_q), Notes.note.like(_q)))
            if category:
                db_query = db_query.filter(Notes.category == category)

            rows = db_query.order_by(Notes.date_time.desc()).limit(limit).all()

            if not rows:
                _where = (f"location/device '{resolved_name or target_name}'"
                          if (target_name or target_id) else f"query '{query}'")
                out = {
                    "status": "success", "count": 0, "results": [],
                    "message": f"No notes found for {_where}.",
                }
                # 무엇을 훑고 0건인지 말한다 — 그래야 "정말 없다" 와 "못
                # 찾았다" 가 구분된다.
                if scope is not None:
                    out["scope"] = scope
                    _amb = cls._ambiguous_scope_reading(scope)
                    if _amb:
                        out.setdefault("_reading", []).append(_amb)
                return out

            # Each note displays in ITS OWN location tz (the device/zone/site it is
            # attached to) — consistent with how that entity's schedules show device
            # tz. A located note "at 3-1 06:00" should read 06:00 there, not in the
            # system clock. Cached per target_id (search is usually one target). §7
            _tz_by_target = {}
            from aot.utils.timekit import to_tz

            def _note_tzname(tid):
                if not tid:
                    return None
                if tid not in _tz_by_target:
                    try:
                        from aot.utils.device_tz import resolve_location_tz
                        _tz_by_target[tid] = str(resolve_location_tz(tid))
                    except Exception:
                        _tz_by_target[tid] = None
                return _tz_by_target[tid]

            # A site query now pulls notes from every descendant zone too (see
            # _resolve_note_target_ids), so a bare target_id is no longer enough
            # for the AI to tell WHICH zone a note belongs to — resolve each
            # note's own entity display name alongside it.
            _name_by_target = {}
            import json as _json

            def _note_target_name(tid):
                if not tid:
                    return None
                if tid not in _name_by_target:
                    _nm = None
                    try:
                        shape = GeoShape.query.filter_by(unique_id=tid).first()
                        if shape:
                            feat = shape.feature if isinstance(shape.feature, dict) else _json.loads(shape.feature or '{}')
                            props = feat.get('properties') or {}
                            _nm = str(props.get('name') or props.get('label') or props.get('title') or '').strip() or None
                    except Exception:
                        _nm = None
                    if not _nm:
                        try:
                            for model in (Input, Output):
                                row = model.query.filter_by(unique_id=tid).first()
                                if row:
                                    _nm = row.name
                                    break
                        except Exception:
                            pass
                    # 식생·시설은 GeoShape 가 아니다. 이름이 없으면 AI 는 "어느
                    # 구획 것인지" 를 구분할 수 없는데, 이 도구는 site 를 물으면
                    # 그 아래 전부를 돌려주므로 구분이 곧 답의 정확도가 된다.
                    if not _nm:
                        try:
                            from aot.databases.models import GeoPlot, GeoFacility
                            pl = GeoPlot.query.filter_by(unique_id=tid).first()
                            if pl is not None:
                                _nm = pl.name or pl.subject
                            else:
                                fac = GeoFacility.query.filter_by(unique_id=tid).first()
                                if fac is not None:
                                    _nm = getattr(fac, 'name', None)
                        except Exception:
                            pass
                    _name_by_target[tid] = _nm
                return _name_by_target[tid]

            results = []
            for r in rows:
                # r.date_time is stored naive-UTC (SQLite). Display in the note's
                # location tz when it has one, else the system tz.
                _ntz = _note_tzname(r.target_id)
                if r.date_time:
                    if _ntz:
                        _date = to_tz(r.date_time, _ntz).strftime("%Y-%m-%d %H:%M")
                    else:
                        _date = to_local(r.date_time).strftime("%Y-%m-%d %H:%M")
                else:
                    _date = None
                entry = {
                    "note_id": r.unique_id,
                    "date": _date,
                    "date_tz": _ntz,
                    "name": r.name,
                    "category": r.category,
                    "tags": r.tags,
                    # Full content (up to 2000 chars) so the AI can SUMMARIZE — a
                    # 300-char cut dropped photos/plans and made summaries wrong.
                    "note": (r.note or "")[:2000],
                    "target_id": r.target_id,
                    "target_type": r.target_type,
                    "target_name": _note_target_name(r.target_id),
                }
                # 첨부파일. 예전에는 이 줄이 없어서, 사진이 붙은 노트도 AI 에게는
                # 텍스트만 보였다 — 사진 캡션만 남은 노트("왼쪽부터 산포, 채흔
                # ...")를 AI 가 영영 해석할 수 없었던 원인이다. 첨부가 없을 때는
                # 키 자체를 넣지 않는다(대부분의 노트가 그렇고, 빈 배열이 결과마다
                # 붙으면 그게 곧 응답 비대화다).
                _files = [f.strip() for f in (r.files or "").split(",") if f.strip()]
                if _files:
                    entry["files"] = _files
                results.append(entry)

            out = {
                "status": "success",
                "count": len(results),
                "results": results,
                "query": query,
                "target": resolved_name or target_name or target_id,
            }
            # 파일명만으로는 AI 가 "사진이 있다"는 사실까지만 알고 내용을 못 본다.
            # 실제 픽셀을 가져오는 경로를 결과에 실어 준다 — 설명(고정비)이 아니라
            # 첨부가 실제로 있을 때만 나가는 조건부 안내다.
            if any("files" in _e for _e in results):
                out.setdefault("_reading", []).append(
                    "Some notes carry 'files' — image/photo attachments. The filename "
                    "alone is not the content: call get_note_attachment(note_id, filename) "
                    "to actually SEE one. Do that before answering a question the photo "
                    "would settle, and before saying a note has no detail.")
            if scope is not None:
                out["scope"] = scope
                _amb = cls._ambiguous_scope_reading(scope)
                if _amb:
                    out.setdefault("_reading", []).append(_amb)
            return out
        except Exception as e:
            logger.error(f"Error in search_notes_tool: {e}")
            return {"error": f"Error while querying notes: {str(e)}"}

    @classmethod
    def get_note_attachment_tool(cls, note_id=None, filename=None, max_dimension=1024,
                                 **extra):
        """[분류 A - 읽기 도구] 노트에 첨부된 사진을 실제로 본다.

        `search_notes` 는 첨부 **파일명**까지만 준다. 이 도구가 그 파일을 열어
        이미지 블록으로 돌려주므로, 여기까지 와야 AI 가 사진의 내용을 본다.

        **왜 한 장씩인가.** 응답 캡(_MAX_RESPONSE_TOKENS)은 글자 수로 재는데
        base64 이미지는 한 장이 수십만 자다. 여러 장을 한 응답에 실으면 캡이
        터지거나 클라이언트가 거부한다. 이미지는 `_content_blocks` 로 실려
        캡의 자를 비껴가고(tool_execution._execute_tool 참조), 대신 호출당
        한 장으로 묶어 총량을 사람이 통제하게 둔다.
        """
        import base64
        import io
        import os as _os

        try:
            from PIL import Image
            from aot.config import PATH_NOTE_ATTACHMENTS
            from aot.databases.models import Notes

            if not note_id:
                return {"status": "error",
                        "message": "note_id is required. Get it from search_notes."}

            note = Notes.query.filter_by(unique_id=str(note_id).strip()).first()
            if note is None:
                return {"status": "error",
                        "message": f"No note found with note_id '{note_id}'."}

            available = [f.strip() for f in (note.files or "").split(",") if f.strip()]
            if not available:
                return {"status": "error", "note_id": note.unique_id,
                        "message": "This note has no attachments."}

            if filename:
                # 요청한 이름은 **반드시 이 노트가 실제로 가진 목록 안**이어야
                # 한다. 이 대조가 곧 경로 탈출 방어다 — 사용자가 준 문자열로
                # 경로를 만들지 않고, 목록에서 고른 값으로만 만든다.
                want = _os.path.basename(str(filename).strip())
                match = next((f for f in available
                              if f == want or _os.path.basename(f) == want), None)
                if match is None:
                    return {"status": "error", "note_id": note.unique_id,
                            "requested": filename, "files": available,
                            "message": "That filename is not attached to this note. "
                                       "Pick one from 'files'."}
                target = match
            else:
                target = available[0]

            path = _os.path.join(PATH_NOTE_ATTACHMENTS, target)
            # 심볼릭 링크·상대경로로 첨부 디렉터리를 벗어나지 않았는지 최종 확인.
            _root = _os.path.realpath(PATH_NOTE_ATTACHMENTS)
            if _os.path.commonpath([_os.path.realpath(path), _root]) != _root:
                return {"status": "error",
                        "message": "Resolved path escapes the attachment directory."}
            if not _os.path.isfile(path):
                return {"status": "error", "note_id": note.unique_id,
                        "filename": target, "files": available,
                        "message": "The note references this file but it is missing "
                                   "on disk (DB row and uploads/ are out of sync)."}

            size_on_disk = _os.path.getsize(path)
            base = {"status": "success", "note_id": note.unique_id,
                    "note_name": note.name, "filename": target,
                    "bytes_on_disk": size_on_disk,
                    "attachment_count": len(available)}
            if len(available) > 1:
                base["files"] = available
                base["note"] = ("This note has %d attachments; this call returned "
                                "one. Call again with another filename to see the "
                                "rest." % len(available))

            try:
                img = Image.open(path)
                img.load()
            except Exception:
                # 이미지가 아닌 첨부(PDF·문서 등)는 정상 상태다. 실패가 아니라
                # "이건 그림이 아니다"라고 분명히 말한다.
                base["status"] = "not_an_image"
                base["message"] = ("This attachment is not a readable image, so it "
                                   "cannot be shown. Its name and size are above.")
                return base

            orig_w, orig_h = img.size
            try:
                limit = int(max_dimension)
            except (TypeError, ValueError):
                limit = 1024
            limit = max(256, min(limit, 2048))

            # JPEG 는 알파·팔레트를 못 싣는다. 변환을 안 하면 PNG 스크린샷류에서
            # 그대로 터진다.
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            if max(orig_w, orig_h) > limit:
                img.thumbnail((limit, limit), Image.LANCZOS)

            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=80, optimize=True)
            data = buf.getvalue()

            base["original_dimensions"] = f"{orig_w}x{orig_h}"
            base["returned_dimensions"] = f"{img.size[0]}x{img.size[1]}"
            base["returned_bytes"] = len(data)
            base["_content_blocks"] = [{
                "type": "image",
                "data": base64.b64encode(data).decode("ascii"),
                "mimeType": "image/jpeg",
            }]
            return base
        except Exception as e:
            logger.error(f"Error in get_note_attachment_tool: {e}", exc_info=True)
            return {"status": "error",
                    "message": f"Error while reading the attachment: {str(e)}"}

    @classmethod
    def list_notices(cls, limit=10, **extra):
        """List notice board posts, most recent first. Read-only."""
        try:
            from aot.databases.models import NoticePost
            posts = (NoticePost.query.order_by(NoticePost.date_time.desc())
                     .limit(int(limit) if limit else 10).all())
            return {"notices": [
                {"notice_id": p.unique_id, "title": p.title, "pinned": bool(p.pinned),
                 "date_time": serialize_ts(p.date_time) if p.date_time else None}
                for p in posts
            ]}
        except Exception as e:
            return {"error": str(e)}

    @classmethod
    def create_notice(cls, title=None, body=None, pinned=False, **extra):
        """Create a notice board post (title + body only — attachments/polls
        require the web UI). Uses the same notice_add() the web route calls."""
        from aot.aot_flask.utils.utils_notice import notice_add
        if not title and not body:
            return {"error": "title or body is required"}
        form = cls._FakeForm(
            title=title, body=body, category=None, files=[],
            publish_now=True, publish_at=None,
            set_expire=False, expire_at=None,
            pinned=bool(pinned),
        )
        try:
            errors, post = notice_add(form)
        except Exception as e:
            logger.error(f"[create_notice] notice_add raised: {e}")
            return {"error": str(e)}
        if errors:
            return {"error": "; ".join(str(e) for e in errors)}
        if not post:
            return {"error": "Notice created but no post returned"}
        r = {"notice_id": post.unique_id, "title": post.title, "status": "created"}
        if extra:
            r["ignored_args"] = list(extra.keys())
        return r

    @classmethod
    def modify_notice(cls, notice_id=None, title=None, body=None, pinned=None, **extra):
        """Update an existing notice post's title/body/pinned state. Requires
        the calling user to be the post's author or an admin (enforced by
        utils_notice.can_manage_post() on the caller's real session)."""
        from aot.aot_flask.utils.utils_notice import notice_mod
        from aot.databases.models import NoticePost
        if not notice_id:
            return {"error": "notice_id is required"}
        existing = NoticePost.query.filter_by(unique_id=notice_id).first()
        if not existing:
            return {"error": f"Notice not found: {notice_id}"}
        form = cls._FakeForm(
            notice_unique_id=notice_id,
            title=title if title is not None else existing.title,
            body=body if body is not None else existing.body,
            category=existing.category,
            files=[],
            publish_now=(existing.publish_at is None), publish_at=existing.publish_at,
            set_expire=(existing.expire_at is not None), expire_at=existing.expire_at,
            pinned=(bool(pinned) if pinned is not None else existing.pinned),
        )
        try:
            errors, post = notice_mod(form)
        except Exception as e:
            logger.error(f"[modify_notice] notice_mod raised: {e}")
            return {"error": str(e)}
        if errors:
            return {"error": "; ".join(str(e) for e in errors)}
        r = {"notice_id": notice_id, "status": "modified"}
        if extra:
            r["ignored_args"] = list(extra.keys())
        return r

    @classmethod
    def delete_notice(cls, notice_id=None, **extra):
        """Delete a notice post by unique_id. Requires the calling user to be
        the post's author or an admin (enforced by can_manage_post())."""
        from aot.aot_flask.utils.utils_notice import notice_del
        if not notice_id:
            return {"error": "notice_id is required"}
        try:
            errors = notice_del(notice_id)
        except Exception as e:
            logger.error(f"[delete_notice] notice_del raised: {e}")
            return {"error": str(e)}
        if errors:
            return {"error": "; ".join(str(e) for e in errors)}
        return {"notice_id": notice_id, "status": "deleted"}

    @classmethod
    def create_note(cls, name=None, note=None, tags=None, category='general',
                    target_id=None, target_type=None, target_name=None,
                    gps_lat=None, gps_lng=None, priority=None, **extra):
        """Create a plain memo/note. For a dated work task (weeding, inspection)
        use add_schedule instead — that registers a SchedulerJobMeta job, not a
        Notes row.

        Notes in AoT are NOT shown via a widget — every device, land/facility, and
        zone/shape HAS its own notes, viewed PER-ENTITY. A note is visible on an
        entity only when target_id == that entity's unique_id. So when the user
        asks to note something "at 1포장 1-1" / "on 밸브1", pass target_name (the
        location/entity name) — this handler resolves it to the real unique_id and
        target_type. Alternatively pass target_id directly if already known."""
        from aot.databases.models import Notes
        if not name and not note:
            return {"error": "name or note is required"}

        def _to_float(v):
            try:
                return float(v) if v is not None and v != '' else None
            except (TypeError, ValueError):
                return None

        def _to_int(v):
            try:
                return int(v) if v is not None and v != '' else None
            except (TypeError, ValueError):
                return None

        # LLM aliases for the location name — 목록은 aot/tools/target_names.py
        # 하나다(그룹 스코프 판정이 같은 목록을 읽는다).
        from aot.tools.target_names import pop_target_name_alias
        _alias = pop_target_name_alias(extra)
        if not target_name:
            target_name = _alias

        gps_lat = _to_float(gps_lat)
        gps_lng = _to_float(gps_lng)
        resolved_name = None

        # Resolve a location NAME → target_id (+ target_type, gps) so the note
        # attaches to the entity and is actually visible.
        if not target_id and target_name:
            _tid, _tt, resolved_name, _lat, _lng = cls._resolve_note_target(target_name)
            if not _tid:
                _amb = cls._ambiguous_places(target_name) if _tt == 'ambiguous' else None
                if _amb:
                    return cls._ambiguity_refusal(target_name, _amb)
                # Fail LOUD with candidates rather than silently create an
                # invisible floating note (the exact bug the user hit).
                candidates = []
                import json as _json
                for s in GeoShape.query.limit(40).all():
                    try:
                        f = s.feature if isinstance(s.feature, dict) else _json.loads(s.feature or '{}')
                        nm = (f.get('properties') or {}).get('name')
                        if nm:
                            candidates.append(nm)
                    except Exception:
                        continue
                return {
                    "error": "target_not_found",
                    "message": (
                        f"Location/device '{target_name}' was not found, so there is "
                        f"nothing to attach the note to. Retry with an exact name from "
                        f"available_targets."
                    ),
                    "available_targets": candidates[:20],
                }
            target_id = _tid
            if not target_type:
                target_type = _tt
            if gps_lat is None:
                gps_lat = _to_float(_lat)
            if gps_lng is None:
                gps_lng = _to_float(_lng)

        # 쓰기 시점 그룹 스코프 — 노트를 붙일 대상으로 묻는다. 이름으로 풀린
        # 대상은 리졸버가 이미 물었고, 직접 준 target_id 는 여기서 묻는다
        # (쓰기 호출이 묶여 있을 때만; write_scope.enforce).
        if isinstance(target_id, str) and target_id.strip():
            from aot.aot_flask.access import write_scope
            write_scope.enforce(target_id.strip())

        # 대상 자신의 태그는 서버가 보장한다 — AI 가 태그를 안 주는 것이 보통이라
        # (실측: 구획 노트 넷이 태그 없이 남았다) 여기서 붙이지 않으면 그 노트는
        # 노트 페이지에서 '태그 없음' 으로 남는다.
        from aot.aot_flask.utils import utils_notes as _un
        _tags = _un.ensure_target_tag(tags or '', target_id)

        n = Notes(
            name=name or (note[:50] if note else 'Note'),
            note=note or '', tags=_tags, category=category or 'general',
            target_id=target_id or None,
            target_type=target_type or None,
            gps_lat=gps_lat,
            gps_lng=gps_lng,
        )
        _prio = _to_int(priority)
        if _prio is not None:
            n.priority = _prio
        # AI-authored, human-requested note.
        n.context_state = 'user_requested'
        try:
            db.session.add(n)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            return {"error": str(e)}
        r = {"note_id": n.unique_id, "name": n.name, "status": "created"}
        if target_id:
            r["target_id"] = target_id
            r["target_type"] = target_type
            r["attached_to"] = resolved_name or target_id
        else:
            # Surfaced so the AI can tell the user it's a general (unattached) memo,
            # not claim it's "on 1포장 1-1" when it isn't.
            r["attached"] = False
            r["note_hint"] = ("Saved as a general memo with no location; it will not "
                              "appear on any specific device or zone.")
        if extra:
            r["ignored_args"] = list(extra.keys())
        return r

    @classmethod
    def _known_knowledge_tags(cls):
        """라이브러리에서 실제로 쓰이는 태그. 없는 태그를 필터로 쓰지 않기 위해
        필요하고, 모델에게 무엇이 있는지 알려 줄 때도 쓴다."""
        try:
            from aot.databases.models import AIKnowledgeChunk
            out = set()
            for (tags,) in AIKnowledgeChunk.query.with_entities(
                    AIKnowledgeChunk.tags).filter_by(is_enabled=True).all():
                for t in (tags or '').split(','):
                    t = t.strip().lower()
                    if t:
                        out.add(t)
            return out
        except Exception:
            return set()

    @classmethod
    def _registered_lookup_briefs(cls):
        """등록된 조회 소스를 **바로 부를 수 있는 형태**로. 표 파일은 읽지 않는다
        — 이 함수는 검색 응답마다 불리므로 DB 한 번으로 끝나야 한다.

        @ANCHOR: LOOKUP_BRIEF
        예전에는 제목만 돌려줬다. 그러면 모델이 조회하기 전에 반드시
        list_lookup_sources 를 한 번 더 불러 id 를 얻어야 했고, 그 한 번이
        판단 지점 하나·단계 하나였다. 실측(2026-08-25)에서 조사 요청이 바로
        거기서 두 번 갈렸다 — 목록까지 열고 조회로 안 넘어가거나, 목록조차
        안 열거나.

        **루프에서 한 단계를 강제하지 않는 이유**(사용자 지적): 조회 소스가
        있다는 이유만으로 단계를 더 돌리면, 조사와 무관한 요청까지 표 쪽으로
        끌려가 엉뚱한 답을 만든다. 그래서 강제하는 대신 **결정을 하나 없앤다**
        — 부를 때 필요한 것을 미리 실어 주면 중간 단계 자체가 사라지고, 다른
        요청의 동작은 아무것도 바뀌지 않는다.
        """
        try:
            from aot.databases.models import AIContextSource
            import json as _json
            out = []
            for src in AIContextSource.query.filter_by(
                    is_active=True, is_enabled=True, source_type='csv_table').all():
                try:
                    cfg = _json.loads(src.config_json or '{}')
                except (ValueError, TypeError):
                    cfg = {}
                out.append({
                    'title': (cfg.get('title') or src.source_name or '').strip(),
                    'call': "query_reference_table(table_id='%s', query=…)" % src.source_id,
                    'answers': (cfg.get('answers') or '').strip(),
                    'name_language': (cfg.get('name_language') or '').strip(),
                })
            try:
                from aot.tools import providers
                for a in providers.get('data_source_query').describe_all():
                    if not a.get('label'):
                        continue
                    out.append({
                        'title': a['label'],
                        'call': "query_data_source(source_id='%s', operation=…)" % a.get('source_id'),
                        'answers': (a.get('answers') or '').strip(),
                        'name_language': '',
                    })
            except Exception:
                pass
            return [b for b in out if b['title']]
        except Exception:
            return []

    @classmethod
    def knowledge_search_tool(cls, query=None, top_k=3, tags=None, **extra):
        """Free-text search across manuals + synced domain knowledge + AI-curated
        notes. Read-only — the write counterpart is knowledge_shelve."""
        from aot.tools import providers
        if not query or not str(query).strip():
            return {"error": "query is required"}
        try:
            top_k = int(top_k)
        except (TypeError, ValueError):
            top_k = 3
        _tags = [t.strip() for t in str(tags).split(',') if t.strip()] if tags else None

        # @ANCHOR: KNOWLEDGE_SEARCH_UNKNOWN_TAG
        # 없는 태그로 거르면 **전부가 걸러진다.** 태그는 운영자·AI 가 자유롭게
        # 붙이는 값이라 정해진 어휘가 없는데, 모델은 그것을 모르고 그럴듯한 말을
        # 지어 넣는다.
        #
        # 실측(2026-08-25): "가을 무는 어떻게 키워야 되지?" 에 모델이
        # tags='crop' 을 붙여 불렀다. 이 라이브러리의 실제 태그는
        # '무,가을무,김장무,재배' 라 하나도 안 걸렸고, 답을 담은 바로 그 항목이
        # 필터에 잘려 나갔다. 서버가 이미 접지로 같은 내용을 넣어 줬는데도
        # 모델은 자기 빈 검색 결과를 믿고 "정보가 없습니다" 로 끝냈다.
        #
        # 그래서 **하나도 안 맞는 태그는 필터로 쓰지 않는다.** 거르는 대신 무엇이
        # 있는지 알려 준다 — 조용히 빈손을 주는 것보다 스스로 고칠 수 있게 하는
        # 편이 낫다.
        _tag_note = ''
        if _tags:
            known = cls._known_knowledge_tags()
            if known and not (set(t.lower() for t in _tags) & known):
                _tag_note = ("\n\n[NOTE] The tag(s) %s are not used by any item here, so "
                             "they were IGNORED (filtering on them would have hidden "
                             "everything). Tags are free-form, not a fixed vocabulary. "
                             "Tags actually in use: %s."
                             % (', '.join(repr(t) for t in _tags),
                                ', '.join(sorted(known)[:15])))
                _tags = None
        text = providers.get('knowledge_search')(query, top_k=top_k, tags=_tags)

        # 도메인 라이브러리가 비었다는 사실을 응답이 직접 말한다. 예전에는 빈
        # 결과에 "Try different keywords" 만 돌려줬는데, 자료가 하나도 없는
        # 설치에서 그 말은 **검색어가 틀렸다는 뜻으로 읽힌다.** 모델은 키워드만
        # 바꿔 가며 같은 빈손을 반복하고, 끝내 라이브러리가 비었다는 사실을 모른
        # 채 자기 지식으로 넘어간다 — 그리고 그것을 출처처럼 적는다.
        #
        # ⚠ **빈 결과만 보고 판정하면 안 된다.** 검색은 저장소에 늘 있는 AoT
        # 매뉴얼도 함께 뒤지므로, "상추 생육단계" 같은 질문에도 매뉴얼의 엉뚱한
        # 섹션(실측: Security.ko.md)이 느슨하게 걸려 결과가 비지 않는다. 그래서
        # 결과가 **있을 때도** 그것이 매뉴얼뿐이면 그 사실을 함께 말한다.
        # 매니페스트가 아니라 응답이라 고정비가 0이다.
        populated = providers.get('knowledge_library_populated')()

        # 참조표는 **검색 대상이 아니다** — 등록만 해 두고 물어볼 때 조회한다
        # (reference_table_service 모듈 주석). 그래서 이 검색이 빈손이어도
        # 답이 표 안에 있을 수 있는데, 모델은 표의 존재를 모른 채 "정보가
        # 없습니다" 로 끝낸다(실측 2026-08-24: 오크라 생육 온도 질문에서 그랬다).
        # 여기서 한 줄 가리켜 주는 것이 그 간극을 메우는 가장 싼 방법이다 —
        # 매니페스트가 아니라 응답이라 표가 없는 설치에서는 고정비가 0이다.
        _briefs = cls._registered_lookup_briefs()
        _pointer = ''
        if _briefs:
            # **조건절을 붙이지 않는다.** 예전 문구는 "per-item value 나 실시간
            # 외부 데이터를 묻는 경우" 로 조건을 달았는데, "땅콩 재배 방법을
            # 조사해줘" 는 그 조건에 안 걸린다고 읽혔다 — 재현 2026-08-25 에서
            # 모델이 이 안내를 받고도 조회 없이 "자료를 제공해주시면" 으로
            # 끝냈다. 무엇을 하지 말라(모른다고 답하기·사용자에게 되묻기)를
            # 먼저 말하고, 그 전에 무엇을 하라를 명령형으로 붙인다.
            # 부르는 법을 **여기서 바로** 준다. 제목만 주면 모델이 id 를 얻으려
            # list_lookup_sources 를 한 번 더 불러야 하고, 그 한 번이 판단
            # 지점이자 단계 하나다(LOOKUP_BRIEF 주석 참조).
            _lines = []
            for b in _briefs[:3]:
                _line = "  - %s → %s" % (b['title'], b['call'])
                if b['answers']:
                    _line += "\n      answers: %s" % b['answers'][:150]
                if b['name_language']:
                    _line += ("\n      rows are named in: %s — translate the user's word "
                              "yourself if needed." % b['name_language'][:80])
                _lines.append(_line)
            _more = ("\n  (…%d more — list_lookup_sources for the rest)"
                     % (len(_briefs) - 3)) if len(_briefs) > 3 else ""
            _pointer = ("\n\n[NOTE] This search does NOT cover the %d registered lookup "
                        "source(s). They are queried on demand and can hold exactly what "
                        "was just missing. Call one DIRECTLY — you do not need "
                        "list_lookup_sources first:\n%s%s\nDo NOT say the information is "
                        "unavailable, and do NOT ask the user to supply it, until you "
                        "have queried every source whose 'answers' fits the question."
                        % (len(_briefs), "\n".join(_lines), _more))
        # 두 안내는 서로 다른 것을 말한다 — 하나가 다른 하나를 덮으면 안 된다.
        _pointer = _tag_note + _pointer

        if not text:
            if not populated:
                return {"result": ("The knowledge library is EMPTY — no domain source "
                                   "has been synced, so this returns nothing about "
                                   f"'{query}' no matter how it is worded. Do not "
                                   "retry with other keywords. Either answer from your "
                                   "own general knowledge AND say plainly that it is "
                                   "unverified — never pass it off as a citation in a "
                                   "source_note — or tell the user a knowledge source "
                                   "can be added in the AI library settings." + _pointer),
                        "library_empty": True}
            return {"result": f"No documentation section matched '{query}'. "
                              f"Try different keywords." + _pointer}

        if not populated:
            return {"result": (text + "\n\n---\n[NOTE] The domain knowledge library is "
                               "EMPTY — everything above is the AoT system manual "
                               "(how to operate AoT), not reference material about "
                               "crops, livestock or facilities. If you were asking "
                               "about a subject rather than about AoT, treat this as "
                               "NO SOURCE FOUND: say your answer is your own "
                               "unverified knowledge, and do not cite it as a "
                               "source." + _pointer),
                    "library_empty": True}
        return {"result": text + _pointer}

    _LOCAL_SCRIPTS = {
        'ko': ((0xAC00, 0xD7A3), (0x1100, 0x11FF)),          # 한글
        'ja': ((0x3040, 0x30FF), (0x4E00, 0x9FFF)),          # 가나·한자
        'zh': ((0x4E00, 0x9FFF),),                           # 한자
        'zh_Hant': ((0x4E00, 0x9FFF),),
        'th': ((0x0E00, 0x0E7F),),                           # 타이
        'ru': ((0x0400, 0x04FF),), 'uk': ((0x0400, 0x04FF),),
        'sr': ((0x0400, 0x04FF),), 'bg': ((0x0400, 0x04FF),),
        'el': ((0x0370, 0x03FF),),                           # 그리스
        'he': ((0x0590, 0x05FF),),                           # 히브리
        'ar': ((0x0600, 0x06FF),),                           # 아랍
        'hi': ((0x0900, 0x097F),),                           # 데바나가리
    }

    @classmethod
    def _missing_local_name(cls, heading, content):
        """설치 언어의 문자가 제목·태그 어디에도 없으면 그 언어 코드를 돌려준다.

        판정할 수 없으면(라틴 문자권, 요청 문맥 밖, 조회 실패) None — 막지
        않는다. 이 검사의 목적은 확실한 실패를 잡는 것이지 의심스러운 것을
        훈계하는 게 아니다.
        """
        try:
            from flask_babel import get_locale
            loc = get_locale()
            if loc is None:
                return None
            code = str(loc)
        except Exception:
            return None

        ranges = (cls._LOCAL_SCRIPTS.get(code)
                  or cls._LOCAL_SCRIPTS.get(code.split('_')[0]))
        if not ranges:
            return None

        # **태그는 보지 않는다.** knowledge_search 는 제목(3배)과 본문만
        # 점수화하고 태그는 필터일 뿐이라, 태그에만 있는 이름으로는 이 항목이
        # 검색에 걸리지 않는다 — 그것을 통과시키면 검사가 목적을 잃는다.
        text = '%s %s' % (heading or '', content or '')
        for ch in text:
            o = ord(ch)
            if any(lo <= o <= hi for lo, hi in ranges):
                return None
        return code

    @classmethod
    def _missing_source_name(cls, heading, content, source_ref):
        """등록된 **표**에서 옮긴 항목인데 그 표가 쓰는 이름이 제목·태그에
        없으면 표 제목을 돌려준다(없으면 None).

        왜 필요한가. 현지 이름만 달면 반대쪽이 막힌다 — 실측(2026-08-25):
        땅콩 항목이 '땅콩 재배 기준' / 'crop,땅콩' 으로 저장돼 한국어 조회는
        전부 걸렸지만 'peanut' 은 0건이었다. 그 표를 다시 조회하거나, 학명으로
        찾거나, 다른 언어 사용자가 같은 항목에 닿을 길이 없다.

        **표에서 옮긴 것에만 적용한다.** 현장 관찰 메모("3동 관수 밸브가 새는
        중")에는 대응하는 외국어 이름이 애초에 없고, 그런 것까지 영문을
        요구하면 지어내게 된다. API 소스(kind='api')도 제외한다 — 그쪽은
        측정값이라 '이름으로 찾는' 자료가 아니고, 한국 기관 자료에 영문
        이름을 강요할 이유도 없다.
        """
        if not source_ref:
            return None
        try:
            import json as _json
            import re as _re

            from aot.databases.models import AIContextSource

            src = AIContextSource.query.filter_by(
                source_id=str(source_ref), source_type='csv_table').first()
            if src is None:
                return None
            # 학명이든 통용명이든 상관하지 않는다 — 어느 쪽이든 그 표로 되짚어
            # 갈 수 있다. 다만 **태그는 세지 않는다**(위 _missing_local_name 의
            # 같은 이유). 실측에서 태그가 'crop,땅콩' 이었는데, 태그를 세면
            # 범용 분류어 'crop' 이 라틴 낱말이라 그대로 통과했다 — 정작 잡아야
            # 할 바로 그 사례가 빠져나갔다.
            text = '%s %s' % (heading or '', content or '')
            if _re.search(r'[A-Za-z]{3,}', text):
                return None
            try:
                cfg = _json.loads(src.config_json or '{}')
            except (ValueError, TypeError):
                cfg = {}
            return (cfg.get('title') or src.source_name or 'the source table').strip()
        except Exception:
            logger.debug("source-name check skipped", exc_info=True)
            return None

    @classmethod
    def knowledge_shelve(cls, content=None, tags=None, heading=None, entity_ref=None,
                         attribution=None, content_kind='prose', ttl_hours=None,
                         source_url=None, source_ref=None, **extra):
        """Save a piece of knowledge the AI just derived or was told, so a
        later query can retrieve it. Always shelved as ai_curated/unconfirmed
        — see knowledge_shelve_service.shelve_knowledge for the governance
        (dedup/quota/contradiction-flag) this delegates to."""
        from aot.tools import providers

        if not content or not str(content).strip():
            return {"error": "content is required"}
        if not tags:
            return {
                "error": "tags is required",
                "message": "Provide at least one scope tag (crop/livestock/structure/"
                           "topic this knowledge is about) — an untagged note would "
                           "surface for every unrelated query.",
            }

        _table = cls._missing_source_name(heading, content, source_ref)
        if _table:
            return {
                "error": "findable in only one language",
                "message": ("This came from %r, whose rows are named in that source's own "
                            "vocabulary — but neither the heading nor the body carries that "
                            "name (tags are not scored by search, so they do not count). "
                            "Someone searching the scientific or English name, or tracing "
                            "this back to the table, will not find it. Keep BOTH names, "
                            "e.g. heading '땅콩(Arachis hypogaea) 재배 기준'. Then call this "
                            "again." % _table),
            }

        _lang = cls._missing_local_name(heading, content)
        if _lang:
            return {
                "error": "not findable later",
                "message": ("This install's language is %r, but neither the heading nor "
                            "the body contains a single character of that language — a "
                            "person searching in their own words will never get this back "
                            "(search scores the heading 3x and the body 1x; TAGS ARE NOT "
                            "SCORED, so a tag does not make it findable). Put the "
                            "subject's name AS THE USER SAYS IT in the heading, and keep "
                            "the source's own name alongside it. Then call this again."
                            % _lang),
            }

        if not attribution:
            attribution = f"AI 대화 비치 ({datetime.utcnow().date()})"

        ttl = None
        try:
            if ttl_hours is not None and float(ttl_hours) > 0:
                ttl = datetime.utcnow() + timedelta(hours=float(ttl_hours))
        except (TypeError, ValueError):
            ttl = None

        result = providers.get('knowledge_shelve')(
            content=str(content), tags=tags, heading=heading,
            entity_ref=entity_ref, attribution=attribution,
            content_kind=content_kind, ttl=ttl, source_url=source_url,
            source_ref=source_ref,
        )
        if extra:
            result["ignored_args"] = list(extra.keys())
        return result

    @classmethod
    def list_lookup_sources(cls, **extra):
        """이 시스템이 **찾아볼 수 있는 것** 전부 — 참조표와 연결된 데이터 API.

        발견 지점을 하나로 둔다. 둘로 나누면 모델이 한쪽만 보고 "없다" 고
        단정한다(실측 2026-08-25: 표가 있는데 knowledge_search 만 보고 끝냈다).
        종류는 kind 로 구분한다 — 조회 방법이 다르기 때문이다."""
        from aot.databases.models import AIContextSource
        from aot.utils import reference_table_service as rts
        import json as _json

        out = []
        rows = AIContextSource.query.filter_by(
            is_active=True, is_enabled=True, source_type='csv_table').all()
        for src in rows:
            try:
                cfg = _json.loads(src.config_json or '{}')
            except (ValueError, TypeError):
                cfg = {}
            out.append(rts.describe(src, cfg))
        for t in out:
            t['kind'] = 'table'

        from aot.tools import providers
        apis = []
        try:
            for a in providers.get('data_source_query').describe_all():
                a['kind'] = 'api'
                apis.append(a)
        except Exception as exc:
            logger.debug("[LookupSources] api listing skipped: %s", exc)

        if not out and not apis:
            return {
                "sources": [],
                "note": "Nothing is registered to look things up in. Do NOT invent values "
                        "— say the operator can add a source on the AI Library page.",
            }
        # @ANCHOR: LOOKUP_SOURCES_NEXT_STEP
        # 이 안내가 서술형이던 동안 실제로 이런 일이 났다(재현 2026-08-25,
        # "땅콩 재배 방법을 조사해서 라이브러리에 정리해줘"): 모델이
        # knowledge_search 로 0건을 받고 → 이 목록을 열어 FAO ECOCROP 을 **보고도**
        # → 조회하지 않고 "자료를 제공해주시면 정리해 드리겠습니다" 로 끝냈다.
        #
        # 목록만 주면 모델은 이것을 자료 사전으로 읽는다. 그래서 **다음 행동**을
        # 명령형으로 못박고, 별칭이 화이트리스트가 아니라는 것을 여기서 말한다 —
        # 별칭 24개에 '땅콩' 이 없다는 사실이 "이 표로는 못 찾는다" 는 정지
        # 신호로 작동했다.
        return {
            "sources": out + apis,
            "note": "This IS the answer to 'how do I research that here' — you are NOT "
                    "done until you have queried the source whose 'answers' text fits. "
                    "kind='table' -> query_reference_table(table_id, query). "
                    "kind='api' -> query_data_source(source_id, operation, params). "
                    "'aliases' are EXAMPLES, not a whitelist: if the user's word is not "
                    "listed, translate it into the table's 'name_language' yourself and "
                    "query anyway — an absent alias is not evidence the row is absent. "
                    "NEVER ask the user to supply material one of these sources can "
                    "answer. Honour any 'caveat' when you cite the numbers.",
        }

    @classmethod
    def query_data_source(cls, source_id=None, operation=None, params=None,
                          limit=5, columns=None, **extra):
        """등록된 데이터 API 를 지금 조회한다 — 고정 동기화가 아니라 질문할 때."""
        from aot.tools import providers
        if not operation:
            return {"error": "operation is required — call list_lookup_sources to see "
                             "which operations this source has."}
        if isinstance(params, str):
            try:
                params = json.loads(params)
            except (ValueError, TypeError):
                return {"error": "params must be an object, e.g. {\"userId\": \"PF_0000001\"}"}
        payload, err = providers.get('data_source_query').query(
            source_id, operation, params=params, limit=limit, columns=columns)
        if err:
            return {"error": err}
        return payload

    @classmethod
    def query_reference_table(cls, table_id=None, query=None, limit=5, columns=None, **extra):
        """참조표에서 이름으로 행을 찾는다."""
        from aot.databases.models import AIContextSource
        from aot.utils import reference_table_service as rts
        import json as _json

        if not query or not str(query).strip():
            return {"error": "query is required"}
        q = AIContextSource.query.filter_by(
            is_active=True, is_enabled=True, source_type='csv_table')
        src = q.filter_by(source_id=table_id).first() if table_id else None
        if src is None:
            candidates = q.all()
            if len(candidates) == 1 and not table_id:
                src = candidates[0]      # 표가 하나뿐이면 굳이 고르게 하지 않는다
            else:
                return {"error": "table_id not found — call list_lookup_sources first",
                        "available": [c.source_id for c in candidates]}
        try:
            cfg = _json.loads(src.config_json or '{}')
        except (ValueError, TypeError):
            cfg = {}
        _cols = None
        if columns:
            _cols = ([c.strip() for c in columns.split(',') if c.strip()]
                     if isinstance(columns, str) else list(columns))
        rows, err = rts.query(src, cfg, str(query), limit=limit, columns=_cols)
        if err:
            return {"error": err}
        if not rows:
            # 0건일 때 **무엇을 해야 하는지**를 여기서 말한다. 매니페스트가 아니라
            # 응답이라 고정비가 0이고, 필요한 순간에만 나간다.
            #
            # 왜 별칭표로 안 되는가(사용자 지적, 2026-08-24): 김장무·총각무·
            # 알타리무·달청무가 전부 radish 다. 유의어는 끝이 없어서 표로 다 담을
            # 수 없다 — 유의어를 정규 이름으로 옮기는 일은 **모델이 잘하는 일**이고,
            # 표가 어느 언어로 매겨졌는지는 **데이터가 아는 일**이다. 각자 잘하는
            # 쪽에 맡긴다: 언어는 name_language 로 알려 주고, 옮기는 판단은 모델에게
            # 넘기되 여기서 명시적으로 시킨다.
            hint = ''
            lang = (cfg.get('name_language') or '').strip()
            tried = str(query).strip()
            if lang:
                hint = (" This table is keyed by: %s. '%s' may be a local or colloquial "
                        "name for something listed under a different one — work out the "
                        "canonical name yourself (e.g. a regional variety name maps to its "
                        "species' common or scientific name) and call this tool ONCE more "
                        "with that. Only if that also returns nothing is the row absent."
                        % (lang, tried))
            return {"rows": [], "matched": 0, "query": tried,
                    "name_language": lang or None,
                    "aliases": (cfg.get('aliases') or '').strip() or None,
                    "note": ("No row matched '%s'." % tried) + hint +
                            " Do NOT answer from your own memory as if the table had said it."}
        result = {"rows": rows, "matched": len(rows),
                  "table": (cfg.get('title') or src.source_name),
                  # 이 값을 knowledge_shelve(source_ref=...) 에 그대로 넘기면,
                  # 비친 항목이 "확인할 데가 있는 것" 으로 표시된다.
                  "source_ref": src.source_id}
        # 기본 투영이 걸렸으면 그 사실을 말한다 — 안 그러면 모델은 이 표에 이
        # 컬럼들뿐이라고 읽고, 없는 값을 '없다' 고 단정한다.
        if not _cols and (cfg.get('summary_columns') or '').strip():
            result["columns_shown"] = 'summary'
            result["more_columns"] = ("This table has more columns than shown. "
                                      "Call again with columns='*' or a specific "
                                      "column list if you need them.")
        # 표기를 싣는 것만으로는 부족하다 — "답변에 적으라" 고 말하지 않으면
        # 모델은 이것을 그냥 메타데이터로 읽는다(source_attribution 모듈 주석).
        from aot.utils import source_attribution
        source_attribution.apply(result, cfg, cfg.get('preset_key'))
        return result

    @classmethod
    def list_library_source_types_tool(cls, **extra):
        """List every knowledge-library source type the operator can add, so
        the AI recommends the full range (not just SmartFarmKorea). Read-only.
        Reads the LIBRARY_PRESETS catalog (routes_ai_library) — the same list
        the Add-source dropdown shows."""
        from aot.aot_flask.routes_ai_library import LIBRARY_PRESETS  # lazy: avoid import cycle
        system, custom = [], []
        for key, p in LIBRARY_PRESETS.items():
            entry = {
                "key": key,
                "label": p.get("label", key),
                "description": p.get("description_ko") or p.get("description", ""),
            }
            entry["region"] = p.get("region", "any")
            entry["topics"] = p.get("topics", ["any"])
            if p.get("is_system"):
                entry["url"] = p.get("url_source", "")
                entry["needs_api_key"] = True
                entry["multi_operation"] = bool(p.get("multi_operation"))
                system.append(entry)
            else:
                entry["source_type"] = p.get("source_type", key)
                custom.append(entry)
        regions = sorted({e["region"] for e in system})
        return {
            "system_presets": system,
            "custom_types": custom,
            # 지역 축을 **결과에서 계산해** 싣는다. 상수로 "한국 전용" 이라고
            # 적어 두면 지역 불가지 프리셋이 하나라도 생기는 순간 거짓말이 된다.
            "system_preset_regions": regions,
            "note": "system_presets are pre-built external public-data APIs — each needs its own API "
                    "key from that provider, and each carries a `region`. IMPORTANT: every built-in "
                    "preset today is region='KR' (Korean public data). If this operation is NOT in "
                    "Korea, say so plainly instead of recommending one — the way anywhere else gets "
                    "covered is custom_types, which ingest the operator's OWN material: a document "
                    "(PDF/text/markdown), a web page, any REST API, or an internal DB query. Those "
                    "work in any country and for any subject (crop, livestock, structure, "
                    "infrastructure). When asked what can be added, present BOTH groups and match "
                    "them to where the operator actually is and what they actually manage.",
        }

    @classmethod
    def smartfarmkorea_lookup_tool(cls, dataset=None, api_key=None, mode='farms',
                                   user_id=None, query=None, crop=None, limit=20, **extra):
        """Discover SmartFarmKorea farms or cropping seasons (read-only) so the
        AI can resolve userId/facilityId/croppingSerlNo without asking the user
        for codes. Wraps resolve_farms/resolve_seasons. `crop` filters to farms/
        seasons of that crop (딸기/토마토/…) — use it so a 딸기 request never
        returns a 토마토 farm. Only 시설/노지 have a discovery chain — 축산
        returns a clear no-op error."""
        from aot.tools import providers
        sfk = providers.get('smartfarmkorea')
        if not api_key or not str(api_key).strip():
            return {"error": "api_key is required (the SmartFarmKorea service key)"}
        ops = sfk.operations_for_preset(str(dataset or '').strip())
        mode = str(mode or 'farms').strip().lower()
        key = str(api_key).strip()

        if mode == 'farms':
            items, err = sfk.resolve_farms(key, operations=ops)
        elif mode == 'seasons':
            if not user_id or not str(user_id).strip():
                return {"error": "user_id is required for mode='seasons' — first look up farms and pick a userId"}
            items, err = sfk.resolve_seasons(key, str(user_id).strip(), operations=ops)
        else:
            return {"error": "mode must be 'farms' or 'seasons'"}
        if err:
            return {"error": err}

        items = items or []
        total = len(items)
        # crop filter: match the resolved crop name (or the raw itemCode, so a
        # numeric code still works). Applied separately from `query` so the AI
        # can combine region (query) AND crop precisely.
        if crop:
            c = str(crop).strip().lower()
            items = [it for it in items
                     if c in str(it.get('crop', '')).lower() or c in str(it.get('itemCode', '')).lower()]
        if query:
            q = str(query).strip().lower()
            def _hay(it):
                return ' '.join([str(it.get('label', '')), str(it.get('userId', '')),
                                 str(it.get('croppingSerlNo', '')), str(it.get('itemCode', ''))]).lower()
            items = [it for it in items if q in _hay(it)]
        try:
            lim = int(limit)
        except (TypeError, ValueError):
            lim = 20
        shown = items[:lim]
        _filters = ', '.join(f for f in [f"crop='{crop}'" if crop else '', f"query='{query}'" if query else ''] if f)
        if _filters:
            note = f"{total} total; {len(items)} matched ({_filters}), showing {len(shown)}"
        elif total > len(shown):
            note = f"{total} total; showing first {len(shown)} — pass crop and/or query to narrow"
        else:
            note = f"{total} total"
        return {"mode": mode, "total": total, "returned": len(shown), "note": note, "items": shown}

    @classmethod
    def configure_library_source_tool(cls, preset_key=None, api_key=None, operations=None,
                                      source_id=None, activate=True, sync=True,
                                      farm_label=None, season_label=None, **params):
        """Create or update a SmartFarmKorea library source with resolved
        config, then (default) activate + sync so its measured data enters the
        knowledge layer. Mutating → approval-gated (registers a source and
        fetches external data). `params` carries the per-operation values
        (userId/facilityId/croppingSerlNo/itemCode/measDate/startDate/endDate/
        fldCode/sectCode/fatrCode) — pass whatever the selected operations need
        (resolve IDs via smartfarmkorea_lookup, don't ask the user for codes)."""
        import json as _json
        import uuid as _uuid
        from aot.tools import providers
        from aot.databases.models import AIContextSource, Misc

        _SFK_PRESETS = ('smartfarmkorea', 'smartfarmkorea_outdoor', 'smartfarmkorea_livestock')
        if preset_key not in _SFK_PRESETS:
            return {"error": f"preset_key must be one of {_SFK_PRESETS}"}
        if not api_key or not str(api_key).strip():
            return {"error": "api_key is required"}

        ops_list = operations or []
        if isinstance(ops_list, str):
            ops_list = [o.strip() for o in ops_list.split(',') if o.strip()]
        if not ops_list:
            return {"error": "operations is required (at least one operation key)"}

        dataset_ops = providers.get('smartfarmkorea').operations_for_preset(preset_key)
        unknown = [o for o in ops_list if o not in dataset_ops]
        if unknown:
            return {"error": f"unknown operations for {preset_key}: {unknown}",
                    "valid_operations": list(dataset_ops.keys())}

        _ALL_PARAMS = ['userId', 'facilityId', 'croppingSerlNo', 'itemCode', 'measDate',
                       'startDate', 'endDate', 'fldCode', 'sectCode', 'fatrCode']
        config = {'preset_key': preset_key, 'api_key': str(api_key).strip(), 'operations': ops_list}
        for p in _ALL_PARAMS:
            if params.get(p) is not None:
                config[p] = str(params.get(p)).strip()
        if farm_label:
            config['_farmLabel'] = str(farm_label)
        if season_label:
            config['_seasonLabel'] = str(season_label)

        # Validate each selected op's required (non-serviceKey) params are present.
        missing_report = []
        for op_key in ops_list:
            op = dataset_ops[op_key]
            miss = [p for p in op['params'] if p != 'serviceKey' and not (config.get(p) or '').strip()]
            if miss:
                missing_report.append({"operation": op['label_ko'], "missing": miss})
        if missing_report:
            return {"error": "missing required params for some operations", "details": missing_report,
                    "hint": "Resolve userId/croppingSerlNo via smartfarmkorea_lookup; ask the user for "
                            "date ranges and any classification codes (fldCode/sectCode/fatrCode)."}

        from aot.aot_flask.routes_ai_library import LIBRARY_PRESETS  # lazy: avoid import cycle
        preset = LIBRARY_PRESETS.get(preset_key, {})

        if source_id:
            source = AIContextSource.query.filter_by(source_id=source_id).first()
            if not source:
                return {"error": f"source_id not found: {source_id}"}
            source.config_json = _json.dumps(config)
            action = 'updated'
        else:
            misc = Misc.query.first()
            fid = (getattr(misc, 'default_facility_id', None) or 'default') if misc else 'default'
            source = AIContextSource(
                facility_id=fid,
                source_name=preset.get('label', preset_key),
                source_type=preset.get('source_type', 'rest_api'),
                parameter_name=f"{preset_key}.{str(_uuid.uuid4())[:8]}",
                config_json=_json.dumps(config),
                sync_interval_min=preset.get('sync_interval_min', 1440),
                is_active=True, is_enabled=False,
            )
            db.session.add(source)
            action = 'created'

        if activate:
            source.is_enabled = True
        db.session.commit()

        result = {"status": action, "source_id": source.source_id,
                  "source_name": source.source_name, "operations": ops_list,
                  "activated": bool(activate)}

        if sync and activate:
            from aot.tools import providers
            msgs = providers.get('source_sync')(source.source_id)
            result["synced"] = not bool(msgs.get('error'))
            result["sync_error"] = msgs.get('error')
            result["sync_info"] = msgs.get('info')
            result["sync_warning"] = msgs.get('warning')
        return result

    @classmethod
    def submit_advice(cls, title=None, advice=None, rationale=None, proposed_action=None,
                      scope_type='system', scope_id=None, severity='info',
                      confidence=None, agent_id=None, agent_kind='external', **extra):
        """[의견 제출] 관측에 근거한 조언을 원장에 남긴다. 제어는 실행되지 않는다.

        상충하는 의견도 덮어쓰지 않고 나란히 쌓인다 — 사람이 출처와 근거를 보고
        판단하는 것이 목적이다. 제어가 필요하다고 보면 proposed_action 에 무엇을
        왜 해야 하는지 적을 것. 실제 실행은 사람 승인을 거친다.
        """
        from datetime import datetime as _dt
        try:
            from aot.databases.models import AIAdvice

            title = (title or '').strip()
            advice = (advice or '').strip()
            if not advice:
                return {"status": "error",
                        "message": "'advice' is required - state what you are advising."}
            if not title:
                # 제목을 생략하면 본문 첫 문장으로 대신한다 (칩·목록 표시용).
                title = advice.split('.')[0].strip()[:200]

            valid_scopes = ('system', 'farm', 'zone', 'facility', 'device')
            if scope_type not in valid_scopes:
                return {"status": "error",
                        "message": f"scope_type must be one of: {', '.join(valid_scopes)}."}
            valid_sev = ('info', 'advice', 'warning', 'urgent')
            if severity not in valid_sev:
                severity = 'info'

            # 스코프 이름 해석 — 목록에서 사람이 알아볼 수 있게.
            scope_name = None
            if scope_id:
                try:
                    shape = GeoShape.query.filter(
                        or_(GeoShape.unique_id == scope_id, GeoShape.geo_id == scope_id)).first()
                    if shape and shape.feature:
                        scope_name = (shape.feature.get('properties') or {}).get('name')
                    if not scope_name:
                        from aot.databases.models import GeoFacility
                        fac = GeoFacility.query.filter_by(unique_id=scope_id).first()
                        scope_name = fac.name if fac else None
                except Exception:
                    scope_name = None

            try:
                conf = float(confidence) if confidence is not None else None
                if conf is not None:
                    conf = min(max(conf, 0.0), 1.0)
            except (TypeError, ValueError):
                conf = None

            row = AIAdvice(
                agent_id=(agent_id or 'unknown')[:100],
                agent_kind=agent_kind if agent_kind in ('main', 'external', 'subordinate') else 'external',
                scope_type=scope_type,
                scope_id=scope_id,
                scope_name=scope_name,
                title=title[:200],
                advice=advice,
                rationale=(rationale or '').strip(),
                proposed_action=(proposed_action or '').strip(),
                severity=severity,
                confidence=conf,
                status='pending',
                created_at=_dt.utcnow(),
            )
            row.save()

            return {
                "status": "success",
                "advice_id": row.unique_id,
                "submitted_by": row.agent_id,
                "scope": {"type": scope_type, "id": scope_id, "name": scope_name},
                "review_status": "pending",
                "message": ("Advice recorded in the ledger. Nothing was executed; a human "
                            "will review it. Use list_advice to compare with other AI "
                            "opinions on the same target."),
                # 조언 ≠ 실행. 쓰기가 거부된 뒤 이 도구를 부른 모델이 "완료했습니다"
                # 라고 보고했다(2026-09-23 재측정 lat_22, 3건) — 조언이 저장된
                # 것을 요청한 노트·변경이 된 것으로 말했다. 그 구분을 응답에 싣는다.
                "_reading": [
                    "Only a suggestion was saved, for a person to review. It is "
                    "not the note or change the user asked for, and nothing it "
                    "proposes was carried out. Say that plainly (e.g. 'not "
                    "applied; left as a suggestion for review') - do not report "
                    "the request as done. Refer to things by name, not id."],
            }
        except Exception as e:
            logger.exception("Error in submit_advice")
            return {"status": "error", "message": str(e)}

    @classmethod
    def list_advice(cls, scope_type=None, scope_id=None, status=None, agent_id=None,
                    severity=None, limit=20, **extra):
        """[읽기전용] 원장에 쌓인 AI 의견 조회 — 자신·타 AI·메인 AI의 의견 전부.

        조언을 내기 전에 이 도구로 같은 대상에 이미 어떤 의견이 있는지 확인할 것.
        중복 제출을 막고, 다른 AI와 판단이 갈리면 그 차이를 근거와 함께 짚을 수 있다.
        """
        try:
            from aot.databases.models import AIAdvice

            q = AIAdvice.query
            if scope_type:
                q = q.filter(AIAdvice.scope_type == scope_type)
            if scope_id:
                q = q.filter(AIAdvice.scope_id == scope_id)
            if status:
                q = q.filter(AIAdvice.status == status)
            if agent_id:
                q = q.filter(AIAdvice.agent_id == agent_id)
            if severity:
                q = q.filter(AIAdvice.severity == severity)
            try:
                lim = min(max(int(limit), 1), 100)
            except (TypeError, ValueError):
                lim = 20

            rows = q.order_by(AIAdvice.created_at.desc()).limit(lim).all()
            results = [{
                "advice_id": r.unique_id,
                # serialize_ts 로 낸다(원시 isoformat 이 아니라). 이 컬럼은 naive
                # UTC 로 저장되므로 그대로 내보내면 **오프셋이 아예 없는** 문자열이
                # 되고, 읽는 쪽은 그것을 현지시각으로 읽는다 — 한국이면 9시간
                # 어긋난 채 "방금 낸 의견" 이 오전으로 보인다.
                "created_at": serialize_ts(r.created_at),
                "agent_id": r.agent_id,
                "agent_kind": r.agent_kind,
                "scope": {"type": r.scope_type, "id": r.scope_id, "name": r.scope_name},
                "title": r.title,
                "advice": r.advice,
                "rationale": r.rationale,
                "proposed_action": r.proposed_action,
                "severity": r.severity,
                "confidence": r.confidence,
                "status": r.status,
                "review_note": r.review_note,
                "reviewed_at": serialize_ts(r.reviewed_at),
            } for r in rows]

            # 같은 대상에 여러 주체가 의견을 냈으면 알려준다 — 상충 가능 신호.
            contested = {}
            for r in results:
                if r["status"] != 'pending':
                    continue
                key = f"{r['scope']['type']}:{r['scope']['id']}"
                contested.setdefault(key, set()).add(r["agent_id"])
            multi = [k for k, v in contested.items() if len(v) > 1]

            out = {"status": "success", "count": len(results), "results": results}
            if multi:
                out["multiple_agents_on_same_scope"] = multi
                out["note"] = ("More than one AI has advised on the same target. Where "
                               "judgements differ, explain the difference using each "
                               "rationale as evidence.")
            return out
        except Exception as e:
            logger.exception("Error in list_advice")
            return {"status": "error", "message": str(e)}

    @classmethod
    def _cold_storage_service(cls):
        from aot.services.cold_storage_service import ColdStorageService
        return ColdStorageService()

    @classmethod
    def search_archives(cls, query=None, limit=50, offset=0):
        """아카이브된 문서를 메타데이터로 검색한다. 실제 아카이브 실물만 조회된다.

        **검색 대상은 저장된 메타데이터뿐이다** — 제목과 태그(그리고 이후
        아카이브된 것에 한해 노트가 매달렸던 대상). 본문도, 날짜도, 위치도
        색인돼 있지 않다. 그래서 "3-1 구역 아카이브 노트" 같은 질문은 제목에
        그 말이 우연히 들어 있지 않으면 0건이 된다 — 없는 것이 아니라 이
        검색으로는 못 찾는 것이다. 빈 결과의 note 가 그 둘을 구분해 말한다.
        """
        try:
            try:
                limit = max(1, min(int(limit), 200))
                offset = max(0, int(offset))
            except (TypeError, ValueError):
                limit, offset = 50, 0

            svc = cls._cold_storage_service()
            result = svc.search_archives(query=query or None, limit=limit, offset=offset)
            # 서비스 반환 키는 'results' 다 — 'archives' 로 읽으면 아카이브가
            # 있어도 항상 빈 목록이 되어 "보관된 문서 없음" 으로 보고된다.
            archives = result.get('results', [])
            out = {
                "status": "success",
                "count": len(archives),
                "total": result.get('total', len(archives)),
                "results": archives,
            }
            if not archives:
                # 예전에는 무조건 "아카이브된 문서가 없다" 고 단정했다. 검색어를
                # 준 경우에도 그렇게 답하므로, **검색어가 안 맞은 것**을 "아무것도
                # 아카이브되지 않았다" 로 보고하는 자리였다. 둘을 갈라 말한다.
                # 검색어가 없었다면 방금 받은 total 이 곧 전체 개수다 — 다시
                # 묻지 않는다. 전체를 따로 세어야 하는 경우는 "검색어를 줬고
                # 0건" 일 때뿐이다(그때의 total 은 '조건에 맞는 수'라 0이다).
                total_archived = int(result.get('total') or 0)
                if query:
                    try:
                        total_archived = int(
                            svc.search_archives(query=None, limit=1, offset=0)
                            .get('total', 0))
                    except Exception:
                        logger.debug("[ARCHIVE] total count probe failed",
                                     exc_info=True)

                if not total_archived:
                    out["note"] = ("No archived documents at all. This is the "
                                   "expected state until tier migration is wired "
                                   "— it does not mean a search failed.")
                elif query:
                    out["note"] = (
                        "%d archived document(s) exist but none matched this "
                        "query. Only the title and tags are indexed — not the "
                        "body, the date, or the location/zone the note was "
                        "attached to. Do not report this as 'nothing archived "
                        "for that place'; retry with a word from the title, or "
                        "search the live notes with search_notes."
                        % total_archived)
                else:
                    out["note"] = ("%d archived document(s) exist but this page "
                                   "is empty — check offset/limit."
                                   % total_archived)
            return out
        except Exception as e:
            logger.exception("Error in search_archives")
            return {"status": "error", "message": str(e)}

    @classmethod
    def get_archived_document(cls, document_id=None, include_content=False):
        """아카이브 문서 하나를 조회한다. include_content=True 면 본문까지 해제한다."""
        try:
            if not document_id or not isinstance(document_id, str):
                return {"status": "error", "message": "document_id is required"}

            svc = cls._cold_storage_service()
            result = svc.restore_document(document_id,
                                          decompress=bool(include_content))
            if result is None:
                return {
                    "status": "not_found",
                    "document_id": document_id,
                    "message": ("Not in the archive. If the document is marked tier 3, that "
                                "is an intent flag only — its content is still in the "
                                "original table."),
                }
            return {"status": "success", "document": result}
        except FileNotFoundError as e:
            # DB 행은 있는데 파일이 없다 — 조용히 넘기면 안 되는 불일치다.
            logger.error("Archive file missing for %s: %s", document_id, e)
            return {
                "status": "error",
                "document_id": document_id,
                "message": f"Archive record exists but its file is missing: {e}",
            }
        except Exception as e:
            logger.exception("Error in get_archived_document")
            return {"status": "error", "message": str(e)}

    @classmethod
    def archive_note(cls, note_id=None, retention_policy='default'):
        """노트 본문을 아카이브에 복사하고 tier 를 3(cold)으로 표시한다."""
        try:
            if not note_id or not isinstance(note_id, str):
                return {"status": "error", "message": "note_id is required"}

            note = Notes.query.filter_by(unique_id=note_id).first()
            if note is None:
                return {"status": "not_found", "message": f"Note {note_id} not found"}

            content = note.note or ''
            if not content.strip():
                return {"status": "error",
                        "message": "Note has no content to archive"}

            # 대상(구역·구획 등)을 함께 남긴다. 예전에는 제목과 태그만 남겨서,
            # 아카이브를 위치로 되찾을 방법이 **원리적으로** 없었다 —
            # search_archives 가 메타데이터만 뒤지기 때문이다. 이후 아카이브분
            # 부터 위치로 좁힐 수 있다(기존 것은 소급되지 않는다).
            meta = {"name": note.name, "note_tags": note.note_tags,
                    "target_type": note.target_type, "target_id": note.target_id}
            svc = cls._cold_storage_service()
            result = svc.archive_document(
                document_id=note_id, content=content, metadata=meta,
                retention_policy=retention_policy, archived_by='ai')

            note.tier = 3
            db.session.commit()

            return {
                "status": "success",
                "document_id": note_id,
                "archive_path": result['archive_path'],
                "compression_ratio": result['compression_ratio'],
                "note": ("A copy was archived and the note was marked tier 3. "
                         "The original note text was NOT deleted — deletion is "
                         "handled by the retention policy, not by archiving."),
            }
        except ValueError as e:      # 이미 아카이브됨
            return {"status": "error", "message": str(e)}
        except Exception as e:
            db.session.rollback()
            logger.exception("Error in archive_note")
            return {"status": "error", "message": str(e)}

    @classmethod
    def restore_note_from_archive(cls, note_id=None, target_tier=2):
        """아카이브 본문을 확인하고 노트를 지정 티어로 되돌린다."""
        try:
            if not note_id or not isinstance(note_id, str):
                return {"status": "error", "message": "note_id is required"}
            try:
                target_tier = int(target_tier)
            except (TypeError, ValueError):
                target_tier = 2
            if target_tier not in (1, 2, 3):
                return {"status": "error", "message": "target_tier must be 1, 2 or 3"}

            svc = cls._cold_storage_service()
            archived = svc.restore_document(note_id, decompress=True)
            if archived is None:
                return {"status": "not_found",
                        "message": f"{note_id} is not in the archive"}

            note = Notes.query.filter_by(unique_id=note_id).first()
            if note is None:
                # 아카이브만 남고 원본이 사라진 경우 — 본문을 돌려주되 상태를 밝힌다.
                return {
                    "status": "orphan_archive",
                    "document_id": note_id,
                    "content": archived.get('content'),
                    "message": ("The archive exists but the original note is gone. "
                                "Returning the archived text; recreating the note is "
                                "a separate action."),
                }

            note.tier = target_tier
            db.session.commit()
            return {
                "status": "success",
                "document_id": note_id,
                "tier": target_tier,
                "content_matches_original": (note.note or '') == archived.get('content'),
            }
        except Exception as e:
            db.session.rollback()
            logger.exception("Error in restore_note_from_archive")
            return {"status": "error", "message": str(e)}

    @classmethod
    def set_document_tier(cls, note_id=None, tier=None):
        """노트의 티어 값만 바꾼다 — 내용은 옮기지 않는다."""
        try:
            if not note_id or not isinstance(note_id, str):
                return {"status": "error", "message": "note_id is required"}
            try:
                tier = int(tier)
            except (TypeError, ValueError):
                return {"status": "error", "message": "tier must be 1, 2 or 3"}
            if tier not in (1, 2, 3):
                return {"status": "error", "message": "tier must be 1, 2 or 3"}

            note = Notes.query.filter_by(unique_id=note_id).first()
            if note is None:
                return {"status": "not_found", "message": f"Note {note_id} not found"}

            previous, note.tier = note.tier, tier
            db.session.commit()

            out = {"status": "success", "document_id": note_id,
                   "previous_tier": previous, "tier": tier}
            if tier == 3:
                out["note"] = ("Marked cold, but nothing was moved. Use archive_note "
                               "to actually place a copy in the archive.")
            return out
        except Exception as e:
            db.session.rollback()
            logger.exception("Error in set_document_tier")
            return {"status": "error", "message": str(e)}

    @classmethod
    def delete_archive(cls, document_id=None, reason=''):
        """아카이브 사본을 삭제한다. 원본 노트는 건드리지 않는다."""
        try:
            if not document_id or not isinstance(document_id, str):
                return {"status": "error", "message": "document_id is required"}

            svc = cls._cold_storage_service()
            deleted = svc.delete_archive(document_id, deletion_reason=reason or 'ai request')
            if not deleted:
                return {"status": "not_found",
                        "message": f"{document_id} is not in the archive"}
            return {
                "status": "success",
                "document_id": document_id,
                "note": ("The archived copy was deleted. The original note was not "
                         "touched; its tier value is unchanged and may still read 3."),
            }
        except Exception as e:
            logger.exception("Error in delete_archive")
            return {"status": "error", "message": str(e)}

