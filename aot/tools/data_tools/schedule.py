import logging

logger = logging.getLogger(__name__)


from aot.tools import providers
from aot.aot_flask.extensions import db
from aot.utils.time_utils import utc_now
from datetime import timedelta


class ScheduleToolsMixin:

    @classmethod
    def _extract_spatial_tags(cls, content):
        """내용에서 공간(장소/장치) 이름을 추출하여 태그 형태로 반환합니다."""
        if not content:
            return ""
        
        try:
            # 1. 공간 계층 구조 가져오기
            hierarchy = providers.get('spatial_hierarchy')()
            
            # 2. 모든 장소 이름 수집 (재귀적)
            all_names = set()
            def collect_names(nodes):
                for node in nodes:
                    if 'name' in node:
                        all_names.add(node['name'])
                    if 'children' in node:
                        collect_names(node['children'])
            
            collect_names(hierarchy)
            
            # 3. 매칭되는 이름 찾기
            found_tags = []
            for name in all_names:
                if name in content:
                    # 중복 방지를 위해 #를 붙여서 추가
                    tag = f"#{name.replace(' ', '_')}"
                    if tag not in found_tags:
                        found_tags.append(tag)
            
            return ", ".join(found_tags) if found_tags else ""
        except Exception as e:
            logger.error(f"Error in _extract_spatial_tags: {e}")
            return ""

    @classmethod
    def add_schedule_tool(cls, date, content, worker=None, time="09:00", tags=None,
                          target_name=None, **extra):
        """
        [분류 B - 일정/계획 전용 도구]
        사람의 작업/이벤트 일정(제초·방제·정식·수확·점검·출하 등)을 등록합니다.
        (SchedulerJobMeta 기반, action_type='human')
        Routing: propose_job(action_type='human') -> approve_job(decided_by='AI')
        No APScheduler trigger is created for human-type schedules.

        위치 연결: target_name(구역/시설/장치 이름, 예 '온실', '3-1', '1포장 1-1')을 주면
        _resolve_note_target로 실제 엔티티(target_id)에 붙여 지도·위치별 조회가 성립합니다.
        모호/미해석이면 available_targets를 돌려주니 ask_user로 확인 후 재시도하세요.
        위치를 특정하지 않는 농장 전체 일정이면 target_name 없이 등록합니다(떠 있는 일정).
        """
        try:
            scheduler = providers.get('job_scheduler')

            # LLM aliases for the location name.
            if not target_name:
                target_name = extra.pop('location', None) or extra.pop('zone_name', None) \
                    or extra.pop('place', None) or extra.pop('entity_name', None)

            # 1. Resolve location FIRST — the target's tz is the wall-clock anchor
            #    (device-local is the confirmed policy, timezone-management.md §6).
            #    run_at is computed in step 2 once the anchor is known. Do NOT
            #    silently create a floating (target_id='none') schedule when the user
            #    named a place — same orphan footgun the notes tool guards against.
            target_id = 'none'
            target_type = None
            resolved_name = None
            if target_name:
                _tid, _tt, resolved_name, _lat, _lng = \
                    cls._resolve_note_target(target_name)
                if not _tid:
                    return {
                        "status": "needs_disambiguation",
                        "error": "target_not_found",
                        "message": (f"위치 '{target_name}'를 특정하지 못했습니다. "
                                    f"available_targets에서 정확한 이름을 고르도록 ask_user로 "
                                    f"확인한 뒤 다시 등록하세요."),
                        "available_targets": cls._geoshape_name_candidates(),
                    }
                target_id = _tid
                target_type = _tt

            # 2. Anchor the wall-clock to the target's local tz, then store as UTC.
            _anchor_tz, _anchor_name, _anchor_src = \
                cls._resolve_schedule_anchor(target_id)
            run_at = cls._schedule_wall_to_utc(date, time, anchor_tz=_anchor_tz)

            # 3. Build reasoning + params
            job_name = content if not worker else f"{content} (worker: {worker})"
            spatial_tags = tags or cls._extract_spatial_tags(content)
            tag_label = "ai_scheduled, human_work"
            if spatial_tags:
                tag_label += f", {spatial_tags}"
            reasoning = f"[human_schedule] {job_name}"
            if resolved_name:
                reasoning += f" @ {resolved_name}"
            reasoning += f" | tags: {tag_label}"

            params = {'content': content, 'worker': worker or '', 'tags': tag_label}
            if target_type:
                params['target_type'] = target_type
            if resolved_name:
                params['target_name'] = resolved_name

            # 4. Propose job as DRAFT (source_type='human' marks it as a human work item)
            meta = scheduler.propose_job(
                action_type='human',
                target_id=target_id,
                params=params,
                reasoning=reasoning,
                schedule_time=run_at,
                proposed_by='AI',
                approval_required=False,
                source_type='human',
            )

            # 5. Immediately approve — no APScheduler trigger for human schedules
            scheduler.approve_job(meta.id, decided_by='AI')

            # Persist the tz anchor so display can re-derive device-local time.
            try:
                meta.anchor_tz = _anchor_name
                meta.anchor_source = _anchor_src
                from aot.databases.models import db as _db
                _db.session.commit()
            except Exception:
                pass

            result = {
                "status": "success",
                "message": f"Schedule registered: {date} {time} ({_anchor_name}) - {content}",
                "job_id": meta.unique_id,
                "tags": tag_label,
            }
            if target_id != 'none':
                result["attached_to"] = resolved_name or target_id
                result["target_id"] = target_id
                result["target_type"] = target_type
            else:
                result["attached"] = False
                result["note_hint"] = ("위치 미지정 — 특정 구역/시설에 표시되지 않는 "
                                       "농장 전체 일정입니다.")
            return result
        except Exception as e:
            logger.error(f"Error in add_schedule_tool: {e}")
            return {"error": f"Error while registering schedule: {str(e)}"}

    @classmethod
    def _hhmm_to_minutes(cls, hhmm):
        try:
            h, m = str(hhmm).split(':')
            return int(h) * 60 + int(m)
        except Exception:
            return None

    @classmethod
    def validate_schedule_batch(cls, entries, content=None, window_start=None,
                                window_end=None, duration_minutes=60):
        """
        Pure validation, no writes - shared by the MCP approval gate (so a bad
        batch is caught BEFORE a human ever sees an approval prompt for it,
        not after) and by add_schedule_batch_tool itself (defense in depth for
        any caller that reaches the handler through a path other than the
        gate). Returns None when the batch is fine, or an error dict when not.

        Checks, in order:
          1. entries is a non-empty list.
          2. content is available (shared or per-entry) for every entry.
          3. No target_name repeated within the batch.
          4. LEAF-ONLY: no entry's target_name may resolve to a container
             (a site with child zones). Confirmed 2026-07-26: an advisory
             warning here was not enough - a different model called
             resolve_target, saw the child zones, and used the site name
             anyway. A batch's whole purpose is one entry per leaf unit, so
             this is a hard rejection (nothing created), not a note attached
             to something that still gets approved.
          5. Every entry's time <= window_end, if window_end is given.
          6. CAPACITY: len(entries) * duration_minutes must fit inside
             window_end - window_start, if BOTH are given. This is the check
             that catches "9 zones x 1h each into a 4h window" BEFORE any
             time is assigned per entry - pure arithmetic, not something the
             caller needs to reason through correctly on its own.
        """
        if not entries or not isinstance(entries, list):
            return {"status": "error", "message": "entries must be a non-empty list"}
        if not content and not all(e.get('content') for e in entries):
            return {"status": "error",
                    "message": "content is required (either shared, or set per-entry on every entry)"}

        names = [e.get('target_name') for e in entries]
        dupes = sorted({n for n in names if n and names.count(n) > 1})
        if dupes:
            return {
                "status": "error",
                "error": "duplicate_target",
                "message": f"target_name repeated within the same batch: {dupes}",
            }

        containers = []
        for n in sorted({n for n in names if n}):
            try:
                r = cls.resolve_target_tool(n)
            except Exception:
                continue
            if r.get('children'):
                containers.append({
                    "target_name": n,
                    "target_type": r.get('target_type'),
                    "children": r.get('children'),
                })
        if containers:
            return {
                "status": "error",
                "error": "container_target_in_batch",
                "message": (
                    f"{len(containers)} entr(y/ies) target a container (site), not a "
                    f"single leaf zone: {[c['target_name'] for c in containers]}. Nothing "
                    f"was created. A batch entry must target one leaf unit - expand each "
                    f"container to its 'children' below and add one entry per child "
                    f"instead of one entry for the whole container."),
                "container_entries": containers,
            }

        if window_end:
            bad = [e for e in entries if not e.get('time') or e['time'] > window_end]
            if bad:
                return {
                    "status": "error",
                    "error": "outside_window",
                    "message": f"{len(bad)} entr(y/ies) fall after window_end={window_end}. "
                               f"Nothing was created - fix the times and retry.",
                    "offending_entries": bad,
                }

        if window_start and window_end:
            _start_min = cls._hhmm_to_minutes(window_start)
            _end_min = cls._hhmm_to_minutes(window_end)
            if _start_min is not None and _end_min is not None and _end_min > _start_min:
                _available = _end_min - _start_min
                _required = len(entries) * duration_minutes
                if _required > _available:
                    return {
                        "status": "error",
                        "error": "insufficient_window",
                        "message": (
                            f"{len(entries)} entries x {duration_minutes}min = {_required}min "
                            f"needed, but window {window_start}-{window_end} only has "
                            f"{_available}min. Nothing was created. This does not fit in one "
                            f"day as given - either (a) call this tool once per date, splitting "
                            f"entries across multiple dates so each date's entries fit the "
                            f"window, or (b) ask the user how the work should be compressed or "
                            f"parallelized, then retry with entries/duration_minutes that fit."),
                        "required_minutes": _required,
                        "available_minutes": _available,
                        "entries_count": len(entries),
                        "duration_minutes": duration_minutes,
                    }
        return None

    @classmethod
    def add_schedule_batch_tool(cls, date, entries, content=None, worker=None,
                                tags=None, window_start=None, window_end=None,
                                duration_minutes=60, **extra):
        """
        [Human task / memo, BATCH] Register MULTIPLE per-entity work schedules
        in ONE call, gated by a SINGLE approval instead of one approval (and
        one rate-limited request slot) per entry.

        Use this instead of N separate add_schedule calls whenever a request
        applies per sub-unit ('각 구역별로', 'each zone') — call resolve_target
        on the container name first to get the exact child names to put in
        `entries`.

        Args:
            date (str): Shared date (YYYY-MM-DD) for every entry.
            entries (list[dict]): [{target_name (required), time (required,
                HH:MM), content (optional, overrides the shared `content`),
                worker (optional, overrides the shared `worker`)}, ...].
                Duplicate target_name within the same batch is rejected.
            content/worker/tags: Shared defaults used by any entry that omits
                its own content/worker. `content` is required unless every
                entry supplies its own.
            window_start/window_end (str, optional): 'HH:MM'. window_end alone
                rejects any entry whose time falls after it. BOTH together
                additionally validate that len(entries) * duration_minutes
                actually fits the window - if not, the whole batch is
                rejected up front (nothing created) instead of silently
                accepting a schedule that cannot physically happen in one day.
            duration_minutes (int, default 60): assumed minutes per entry,
                used only for the capacity check above.
        """
        _err = cls.validate_schedule_batch(
            entries, content=content, window_start=window_start,
            window_end=window_end, duration_minutes=duration_minutes)
        if _err:
            return _err

        results = []
        for e in entries:
            r = cls.add_schedule_tool(
                date=date,
                content=e.get('content') or content,
                worker=e.get('worker') or worker,
                time=e.get('time', '09:00'),
                tags=tags,
                target_name=e.get('target_name'),
            )
            results.append({"target_name": e.get('target_name'), "time": e.get('time'), "result": r})

        failed = [r for r in results if not r['result'].get('job_id')]
        return {
            "status": "success" if not failed else "partial_failure",
            "count": len(results),
            "failed_count": len(failed),
            "results": results,
        }

    @classmethod
    def schedule_device_control_tool(cls, device_id, scheduled_time=None, state='on', duration_minutes=None,
                                     delay_seconds=None, duration_seconds=None,
                                     solar_event=None, solar_offset_minutes=0,
                                     solar_date_offset_days=0, **kwargs):
        """
        [시스템 제어 예약 전용]
        밸브, 펌프, 스프링클러 등 시스템 장치의 제어를 특정 시간에 예약합니다.
        AISchedulerService.propose_job()으로 SchedulerJobMeta + APScheduler 등록까지 완료합니다.

        Accepts:
          scheduled_time: ISO 8601 string (absolute time) — preferred
          delay_seconds:  relative delay in seconds from now (alternative to scheduled_time)
          solar_event:    'sunrise'|'sunset'|'solar_noon'|'civil_dawn'|'civil_dusk'
                          — 그 장치 위치의 태양 이벤트 기준으로 시각을 잡는다.
                          solar_offset_minutes(±분)·solar_date_offset_days(N일 뒤)와 함께.
          duration_minutes: run duration in minutes
          duration_seconds: run duration in seconds (alternative to duration_minutes)

        "내일 일몰 30분 전에 밸브 열어줘" 같은 요청에서, 일몰 시각을 사람이나 모델이
        직접 계산해 ISO 로 넘길 필요가 없다 — 계절마다 달라지는 값이라 그렇게 하면
        틀린다. solar_event 를 쓰면 장치 위치의 실제 태양시로 해석한다.
        """
        try:
            from aot.utils.tz_utils import now_utc, to_utc
            from datetime import datetime, timedelta
            scheduler = providers.get('job_scheduler')

            # 1. 장치 확인 (UUID, 정확한 이름, 부분 이름 순서로 조회)
            # 각 단계에서 둘 이상 걸리면 멈춘다. 예약은 나중에 혼자 실행되므로
            # 잘못 고르면 사람이 지켜보지 않는 시각에 엉뚱한 장치가 움직인다.
            from aot.services.resolvers.device_resolver import resolve_output
            match = resolve_output(device_id, allow_partial=True)
            if match.error:
                return {"error": match.error}
            output = match.row
            if not output:
                return {"error": f"Device not found: {device_id}"}

            # 2. 시간 파싱 — scheduled_time 또는 delay_seconds 지원
            now = now_utc()
            if solar_event is not None:
                from aot.utils.solar import SUN_EVENTS, next_sun_event
                if solar_event not in SUN_EVENTS:
                    return {"error": (f"Unknown solar_event: {solar_event}. "
                                      f"Use one of: {', '.join(SUN_EVENTS)}")}
                scheduled_dt = next_sun_event(
                    solar_event,
                    target_id=output.unique_id,
                    time_offset_minutes=int(solar_offset_minutes or 0),
                    date_offset_days=int(solar_date_offset_days or 0),
                    now=now)
                if scheduled_dt is None:
                    return {"error": (f"'{solar_event}' does not occur at this device's "
                                      f"location in the coming days (polar day/night), "
                                      f"or the location has no coordinates.")}
            elif delay_seconds is not None:
                scheduled_dt = now + timedelta(seconds=int(delay_seconds))
            elif scheduled_time is not None:
                if isinstance(scheduled_time, str):
                    try:
                        scheduled_dt = datetime.fromisoformat(scheduled_time.replace('Z', '+00:00'))
                    except Exception:
                        return {"error": f"Invalid time format: {scheduled_time}. Use ISO 8601 format."}
                else:
                    scheduled_dt = scheduled_time
                if scheduled_dt.tzinfo is None:
                    # No offset given (the model doesn't always include one) —
                    # interpret it as the TARGET DEVICE'S OWN local wall-clock
                    # time (every device resolves its tz from coordinates, see
                    # device_tz.py) rather than rejecting it as ambiguous. This
                    # is what a user means by "4pm" for a specific device — not
                    # a UTC instant, and not necessarily the farm-wide default.
                    from aot.utils.device_tz import resolve_location_tz
                    scheduled_dt = resolve_location_tz(output.unique_id).localize(scheduled_dt)
                scheduled_dt = to_utc(scheduled_dt)  # normalise to UTC-aware
                if scheduled_dt <= now:
                    return {"error": f"Requested schedule time {scheduled_time} is in the past. Please provide a future time."}
            else:
                return {"error": "You must provide one of: scheduled_time, delay_seconds, solar_event."}

            # 3. 시간 변환 — duration_seconds 지원
            if duration_seconds is not None:
                _duration_minutes = max(1, int(duration_seconds) // 60)
            elif duration_minutes is not None:
                _duration_minutes = int(duration_minutes)
            else:
                _duration_minutes = 5  # default

            duration_sec = _duration_minutes * 60

            # scheduled_dt is UTC-aware — display in the DEVICE'S OWN location tz
            # (every Output resolves its tz from coordinates, see device_tz.py),
            # not left as a bare UTC instant: a raw strftime here would report
            # the confirmation time up to 9h off from the device's actual wall
            # clock (KST).
            from aot.utils.device_tz import resolve_location_tz
            _display_dt = scheduled_dt.astimezone(resolve_location_tz(output.unique_id))

            # 3. SchedulerJobMeta 생성 + 자동 승인 (APScheduler 등록)
            #    proposed_by='HUMAN' + approval_required=False → propose_job() 내부에서 approve_job() 자동 호출
            meta = scheduler.propose_job(
                action_type='control_output',
                target_id=output.unique_id,
                params={'state': state, 'duration_minutes': _duration_minutes},
                reasoning=f"User request: {output.name} {state} at {_display_dt.strftime('%H:%M')}",
                schedule_time=scheduled_dt,
                duration_sec=duration_sec,
                proposed_by='HUMAN',    # 사용자가 직접 지시 → 추가 승인 불필요
                approval_required=False  # → propose_job이 approve_job() 자동 호출
            )

            # Persist the device-local tz anchor (already used for interpretation
            # above) so display can re-derive the device wall-clock. §6.
            try:
                from aot.utils.device_tz import resolve_location_tz_and_source
                _atz, _asrc = resolve_location_tz_and_source(output.unique_id)
                meta.anchor_tz = str(_atz)
                meta.anchor_source = _asrc   # 위치 모르면 'system'(추정)
                from aot.databases.models import db as _db
                _db.session.commit()
            except Exception:
                pass

            logger.info(f"[AI Schedule] Registered APScheduler job: {output.name} {state} at {scheduled_dt} (meta_id={meta.id if hasattr(meta, 'id') else meta})")
            return {
                "status": "success",
                "message": f"Scheduled {output.name} to {state} at {_display_dt.strftime('%Y-%m-%d %H:%M:%S')} (for {_duration_minutes} min)",
                "scheduler_job_id": meta.id if hasattr(meta, 'id') else str(meta),
            }
        except Exception as e:
            logger.error(f"Error in schedule_device_control_tool: {e}")
            return {"error": f"Error while scheduling device control: {str(e)}"}

    @classmethod
    def _resolve_schedule_anchor(cls, target_id):
        """예약 벽시계의 앵커 tz 를 해석한다 (docs/design/timezone-management.md §6).

        확정 정책: 장치 예약은 '장치 현지 시각' 기준. target_id 가 위치를 가진
        엔티티(구역/시설/장치)면 그 위치의 tz 를, 없으면(떠 있는 농장 전체 일정)
        시스템 tz 를 앵커로 쓴다. 반환: (tzinfo, tz_name, source).
        """
        from aot.utils.timekit import system_tz
        if target_id and target_id != 'none':
            try:
                # 위치를 몰라 시스템 시간대로 떨어진 대상은 출처를 'system' 으로
                # 적는다 — 'device' 로 적으면 화면이 추정값을 장치 현지 시각이라
                # 말한다. (§3.2: 시스템 tz 사용은 기록·라벨)
                from aot.utils.device_tz import resolve_location_tz_and_source
                tz, source = resolve_location_tz_and_source(target_id)
                if tz is not None:
                    return tz, str(tz), source
            except Exception:
                pass
        tz = system_tz()
        return tz, str(tz), 'system'

    @classmethod
    def _schedule_wall_to_utc(cls, date_str, time_str="09:00", anchor_tz=None):
        """벽시계 날짜/시각(YYYY-MM-DD, HH:MM)을 앵커 tz 로 해석해 저장용
        UTC-aware datetime 으로 변환한다.

        anchor_tz(pytz tzinfo 또는 IANA 문자열)를 주면 그 시계로 해석한다 —
        확정 정책상 장치 예약은 장치 현지 tz 가 앵커. 생략 시 시스템 tz(농장 기본)로
        폴백해 기존 동작을 보존한다. 저장은 UTC-aware, 표시는 앵커 tz 로 되돌린다.
        """
        from aot.utils.timekit import wall_to_utc, system_tz
        tz = anchor_tz if anchor_tz is not None else system_tz()
        return wall_to_utc(f"{date_str} {time_str}", tz)

    @classmethod
    def _resolve_schedule_job(cls, job_id):
        """일정을 unique_id(우선) 또는 정수 PK로 조회. 없으면 None."""
        from aot.databases.models.scheduler import SchedulerJobMeta
        if job_id is None:
            return None
        key = str(job_id).strip()
        meta = SchedulerJobMeta.query.filter_by(unique_id=key).first()
        if meta:
            return meta
        if key.isdigit():
            return SchedulerJobMeta.query.get(int(key))
        return None

    @classmethod
    def _schedule_summary(cls, meta):
        """SchedulerJobMeta 한 행을 AI가 읽기 쉬운 요약 dict로 직렬화."""
        import json as _json
        from aot.utils.time_utils import serialize_ts
        try:
            params = _json.loads(meta.params_json) if meta.params_json else {}
        except Exception:
            params = {}
        content = params.get('content')
        if not content and meta.action_type == 'control_output' and params.get('state'):
            # Device-control rows never had a human 'content' string (only
            # {state, duration_minutes}) — falling back to the raw internal
            # `reasoning` log line ("User request: Valve1 on at 16:00") read as
            # a debug message, not a summary, once this became user-facing.
            dur = params.get('duration_minutes')
            content = f"{str(params['state']).capitalize()}" + (f" ({dur}min)" if dur else "")
        content = content or meta.reasoning or meta.action_type

        # Display the wall-clock in the schedule's anchor tz (device-local by
        # policy) so a viewer in another tz still sees the device's own time. §7
        anchor = getattr(meta, 'anchor_tz', None)
        if not anchor and meta.target_id and meta.target_id != 'none':
            try:
                from aot.utils.device_tz import resolve_location_tz
                anchor = str(resolve_location_tz(meta.target_id))
            except Exception:
                anchor = None
        if meta.schedule_time:
            from aot.utils.timekit import to_tz
            when = (to_tz(meta.schedule_time, anchor).isoformat() if anchor
                    else serialize_ts(meta.schedule_time))
        else:
            when = None

        return {
            'job_id': meta.unique_id,
            'when': when,
            'when_tz': anchor,
            'content': content,
            'worker': params.get('worker') or None,
            'location': params.get('target_name') or None,   # resolved entity name
            'target_id': meta.target_id if meta.target_id and meta.target_id != 'none' else None,
            'kind': meta.action_type,          # human / control_output / automated_fire ...
            'state': meta.state,
            'editable': bool(meta.is_editable),
            'deletable': bool(meta.is_deletable),
        }

    @classmethod
    def search_schedule_tool(cls, query=None, target_name=None,
                             include_past=False, include_archived=False,
                             limit=20, **extra):
        """
        [분류 C - 일정 조회 도구]
        농장 운영 일정(작업·이벤트·장치 예약)을 SchedulerJobMeta 원장에서 조회한다.
        기본은 '앞으로 예정된 일정'(schedule_time >= 지금)만. edit/delete_schedule에
        넘길 job_id를 얻으려면 먼저 이 도구로 대상을 찾는다(노트의 search→act 패턴).

        Args:
            query (str): 내용/사유(reasoning·content) 부분 검색 키워드. 없으면 전체.
            target_name (str): 특정 위치/장치에 걸린 일정만 (이름 → unique_id 해석).
            include_past (bool): True면 지난 일정/기록도 포함(기본 False = 예정만).
            include_archived (bool): True면 취소/보관(ARCHIVED)된 것도 포함(기본 False).
            limit (int): 최대 반환 건수(기본 20).
        """
        try:
            from aot.databases.models.scheduler import SchedulerJobMeta
            from sqlalchemy import or_ as _or

            q = SchedulerJobMeta.query

            if not include_archived:
                q = q.filter(SchedulerJobMeta.state != 'ARCHIVED')

            if not include_past:
                now = utc_now()
                # 예정된 것(미래) + 시간이 없는 항목은 포함, 과거는 제외
                q = q.filter(_or(SchedulerJobMeta.schedule_time == None,   # noqa: E711
                                 SchedulerJobMeta.schedule_time >= now))

            if query and query.strip():
                like = f"%{query.strip()}%"
                q = q.filter(_or(SchedulerJobMeta.reasoning.like(like),
                                 SchedulerJobMeta.params_json.like(like)))

            # 대상 안에서 일어나는 일 **전부** 를 본다 — 구역·시설·장치·식생.
            # 정확 일치만 보던 때는 site 를 물으면 0건이 나왔다(_scope_for_target).
            scope = None
            if target_name:
                ids, scope = cls._scope_for_target(target_name)
                if ids:
                    q = q.filter(SchedulerJobMeta.target_id.in_(ids))
                else:
                    # 이름을 못 찾았다. 여기서 필터를 걸지 않으면 **전체 일정**
                    # 이 그 대상의 것인 양 돌아간다.
                    q = q.filter(SchedulerJobMeta.target_id == '\x00none')

            # 예정은 임박한 순, 과거 포함이면 최신순
            if include_past:
                q = q.order_by(SchedulerJobMeta.created_at.desc())
            else:
                q = q.order_by(SchedulerJobMeta.schedule_time.asc())

            rows = q.limit(max(1, int(limit))).all()
            results = [cls._schedule_summary(r) for r in rows]
            out = {
                "status": "success",
                "count": len(results),
                "results": results,
            }
            if scope is not None:
                out["scope"] = scope
                if not scope['resolved']:
                    # 0건을 "예정 없음" 으로 읽으면 "충돌 없습니다" 라는 틀린
                    # 답이 확신에 찬 문장으로 나간다. 못 찾은 것은 없는 것이 아니다.
                    out["warning"] = (
                        "'%s' could not be resolved to any place or device, so "
                        "this is NOT evidence that nothing is scheduled. Ask the "
                        "user for the exact name, or call resolve_target first."
                        % target_name)
            return out
        except Exception as e:
            logger.error(f"Error in search_schedule_tool: {e}")
            return {"error": f"Error while querying schedules: {str(e)}"}

    @classmethod
    def edit_schedule_tool(cls, job_id, date=None, time=None, content=None,
                           worker=None, target_name=None, duration_minutes=None,
                           at=None, **extra):
        """
        [일정 수정 — 변이(승인 필요)]
        기존 일정의 시각/소요시간/내용/담당자/위치를 수정한다. 먼저 search_schedule로 job_id를 얻는다.
        장치 예약(control_output)이 이미 APScheduler에 등록돼 있으면 트리거도 함께 재조정.

        Args:
            job_id (str): search_schedule가 돌려준 job_id(unique_id) 또는 정수 id.
            date (str): 새 날짜 YYYY-MM-DD (시각만 바꾸려면 생략 가능 — 기존 날짜 유지).
            time (str): 새 시각 HH:MM (날짜만 바꾸려면 생략 가능 — 기존 시각 유지).
            content (str): 새 내용/설명.
            worker (str): 새 담당자.
            target_name (str): 새 위치(구역/시설/장치 이름)로 재연결. 미해석이면
                available_targets를 돌려주니 ask_user로 확인 후 재시도.
            duration_minutes (int): 새 소요시간(분). 기존 duration_sec/end_time을 대체한다.
            at (str): 화면 전용 — 오프셋이 붙은 절대순간(ISO 8601). 주면 date/time
                대신 쓴다. 캘린더는 보는 사람의 시계로 시각을 고르므로 벽시계로
                보내면 장치 시계로 다시 읽혀 시차만큼 밀린다. AI 도구 표면
                (tool_registry)에는 노출하지 않는다.
        """
        try:
            import json as _json

            meta = cls._resolve_schedule_job(job_id)
            if not meta:
                return {"error": f"Schedule not found: {job_id}"}
            if not meta.is_editable:
                return {"error": f"This schedule is not editable (kind={meta.action_type})."}

            try:
                params = _json.loads(meta.params_json) if meta.params_json else {}
            except Exception:
                params = {}

            # 0. 위치 재연결 (target_name) — 미해석이면 disambiguation 요청
            if target_name:
                _tid, _tt, _rn, _lat, _lng = \
                    cls._resolve_note_target(target_name)
                if not _tid:
                    return {
                        "status": "needs_disambiguation",
                        "error": "target_not_found",
                        "message": (f"위치 '{target_name}'를 특정하지 못했습니다. "
                                    f"available_targets에서 정확한 이름을 고르도록 ask_user로 "
                                    f"확인한 뒤 다시 수정하세요."),
                        "available_targets": cls._geoshape_name_candidates(),
                    }
                meta.target_id = _tid
                params['target_type'] = _tt
                params['target_name'] = _rn

            # 앵커 tz(장치 현지) — 위치가 바뀌었으면 새 위치 기준. §6
            _anchor_tz, _anchor_name, _anchor_src = \
                cls._resolve_schedule_anchor(meta.target_id)
            if target_name:
                # 위치 재연결: 발화 순간(UTC)은 유지하되 표시 앵커를 새 장치로 갱신.
                meta.anchor_tz = _anchor_name
                meta.anchor_source = _anchor_src

            # 1. 시각 변경 — 앵커 tz 기준 해석. date/time 하나만 와도 기존값과 병합.
            new_dt = None
            if at:
                from aot.utils.timekit import instant_or_wall_to_utc
                new_dt = instant_or_wall_to_utc(at, _anchor_tz)
                meta.schedule_time = new_dt
                meta.anchor_tz = _anchor_name
                meta.anchor_source = _anchor_src
            elif date or time:
                from aot.utils.timekit import to_tz
                base_local = to_tz(meta.schedule_time, _anchor_tz) if meta.schedule_time else None
                new_date = date or (base_local.strftime("%Y-%m-%d") if base_local else None)
                new_time = time or (base_local.strftime("%H:%M") if base_local else "09:00")
                if not new_date:
                    return {"error": "date is required (no existing date to keep)."}
                new_dt = cls._schedule_wall_to_utc(new_date, new_time, anchor_tz=_anchor_tz)
                meta.schedule_time = new_dt
                meta.anchor_tz = _anchor_name
                meta.anchor_source = _anchor_src

            # 2. 내용/담당자 변경
            if content is not None:
                params['content'] = content
            if worker is not None:
                params['worker'] = worker
            # params가 바뀐 경우(위치 재연결 포함) 저장
            if content is not None or worker is not None or target_name:
                meta.params_json = _json.dumps(params)

            # 2b. 소요시간 변경 — end_time은 (변경됐을 수 있는) schedule_time 기준으로
            # 재계산하므로 반드시 시각 변경 처리 다음에 온다. duration_minutes가 없어도
            # 시각만 바뀌었고 기존 duration_sec이 있으면 end_time을 같이 이동시킨다.
            if duration_minutes is not None:
                try:
                    duration_minutes = int(duration_minutes)
                except (TypeError, ValueError):
                    return {"error": "duration_minutes must be a number."}
                if duration_minutes <= 0:
                    return {"error": "duration_minutes must be positive."}
                meta.duration_sec = duration_minutes * 60
            if (new_dt is not None or duration_minutes is not None) and meta.duration_sec and meta.schedule_time:
                meta.end_time = meta.schedule_time + timedelta(seconds=meta.duration_sec)

            # 3. edit 추적
            meta.edit_count = (meta.edit_count or 0) + 1
            meta.last_edited_at = utc_now()
            meta.last_edited_by = 'AI'

            # 4. APScheduler 트리거 재조정 (등록된 장치 예약 한정)
            rescheduled = False
            if new_dt is not None and meta.action_type != 'human' and meta.state == 'PENDING':
                try:
                    job = providers.get('job_scheduler').get_job(f'scheduler_meta_{meta.id}')
                    if job is not None:
                        job.modify(next_run_time=new_dt)
                        rescheduled = True
                except Exception as _sch_err:
                    logger.warning(f"[edit_schedule] APScheduler reschedule failed: {_sch_err}")

            db.session.commit()
            return {
                "status": "success",
                "message": "Schedule updated"
                           + (" (device trigger rescheduled)" if rescheduled else ""),
                "schedule": cls._schedule_summary(meta),
            }
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error in edit_schedule_tool: {e}")
            return {"error": f"Error while editing schedule: {str(e)}"}

    @classmethod
    def delete_schedule_tool(cls, job_id, reason=None, **extra):
        """
        [일정 삭제/취소 — 변이(승인 필요)]
        일정을 취소한다. 소프트 삭제(state=ARCHIVED)로 되돌릴 수 있게 보관하며,
        등록된 장치 예약(APScheduler 트리거)은 실제로 제거해 더 이상 발화하지 않게 한다.

        Args:
            job_id (str): search_schedule가 돌려준 job_id(unique_id) 또는 정수 id.
            reason (str): 취소 사유(선택, 감사/학습용).
        """
        try:
            meta = cls._resolve_schedule_job(job_id)
            if not meta:
                return {"error": f"Schedule not found: {job_id}"}
            if not meta.is_deletable:
                return {"error": f"This schedule cannot be deleted (kind={meta.action_type})."}
            if meta.state == 'ARCHIVED':
                return {"status": "success", "message": "Schedule was already cancelled.",
                        "job_id": meta.unique_id}

            # 1. 등록된 APScheduler 트리거 제거 (있으면)
            removed_trigger = False
            try:
                sched = providers.get('job_scheduler')
                if sched.get_job(f'scheduler_meta_{meta.id}') is not None:
                    sched.remove_job(f'scheduler_meta_{meta.id}')
                    removed_trigger = True
            except Exception as _sch_err:
                logger.warning(f"[delete_schedule] APScheduler remove failed: {_sch_err}")

            # 2. 소프트 삭제 (되돌림 가능하도록 보관)
            meta.state = 'ARCHIVED'
            meta.deletion_reason = reason or 'Cancelled via AI request'
            meta.last_edited_at = utc_now()
            meta.last_edited_by = 'AI'
            db.session.commit()

            return {
                "status": "success",
                "message": "Schedule cancelled"
                           + (" (device trigger removed)" if removed_trigger else ""),
                "job_id": meta.unique_id,
            }
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error in delete_schedule_tool: {e}")
            return {"error": f"Error while deleting schedule: {str(e)}"}

    @classmethod
    def _set_entity_activation(cls, entity_id, activate):
        """Activate/deactivate an Input or controller (Conditional/Trigger/PID/
        CustomController) by unique_id or name. Sets is_activated + signals the
        daemon. Returns a result dict or {'error': ...}."""
        try:
            from aot.databases.models import Input
            from aot.databases.models.function import Conditional, Trigger
            from aot.databases.models.controller import CustomController
            from aot.databases.models.pid import PID
            from aot.aot_flask.extensions import db as _db
            from aot.aot_client import DaemonControl

            if not entity_id:
                return {"error": "entity_id is required."}

            resolvers = [
                (Conditional, 'Conditional'), (Trigger, 'Trigger'), (PID, 'PID'),
                (CustomController, 'Function'), (Input, 'Input'),
            ]
            mod = None
            kind = None
            for model, label in resolvers:
                mod = model.query.filter(
                    (model.unique_id == entity_id) | (model.name == entity_id)).first()
                if mod is not None:
                    kind = label
                    break
            if mod is None:
                return {"error": f"Activatable entity not found: {entity_id}"}

            mod.is_activated = bool(activate)
            _db.session.commit()

            try:
                daemon = DaemonControl()
                if activate:
                    ret_err, ret_msg = daemon.controller_activate(mod.unique_id)
                else:
                    ret_err, ret_msg = daemon.controller_deactivate(mod.unique_id)
                if ret_err:
                    return {"status": "success_with_warning", "entity_id": mod.unique_id,
                            "name": mod.name, "type": kind, "is_activated": bool(activate),
                            "daemon_warning": ret_msg}
            except Exception as daemon_err:
                logger.warning("[_set_entity_activation] Daemon call failed for %s: %s", mod.unique_id, daemon_err)
                return {"status": "success_with_warning", "entity_id": mod.unique_id,
                        "name": mod.name, "type": kind, "is_activated": bool(activate),
                        "daemon_warning": str(daemon_err)}

            return {"status": "success", "entity_id": mod.unique_id, "name": mod.name,
                    "type": kind, "is_activated": bool(activate),
                    "message": f"'{mod.name}' {'activated' if activate else 'deactivated'}"}
        except Exception as e:
            logger.exception("Error in _set_entity_activation")
            return {"error": f"Error while {'activating' if activate else 'deactivating'}: {str(e)}"}

