import logging
from ._shims import tz_scoped

logger = logging.getLogger(__name__)


from aot.aot_flask.extensions import db
from aot.databases.models import AITask
from aot.databases.models import GeoShape
from aot.databases.models import Misc
from aot.databases.models import Notes
from aot.utils.timekit import iso_at, FARM, today_at
from datetime import timedelta

from aot.tools.data_tools import screen_map_look as _look
from aot.utils.timekit import naive_utc as _tk_naive_utc, utc_now as _tk_utc_now


def _hook_reads_form(hook):
    """위젯 수정 훅이 웹 폼(request_form)의 **값을 읽는가**(AST 로 판정).

    `if request_form:` 같은 진리값 검사만 하는 훅은 폼 없이도 돈다. 그 밖에
    request_form 을 쓰면(.keys()·.get()·다른 함수에 넘김) 폼 전용이다 — 목록을
    손으로 두지 않는다(새 위젯이 생기면 갈라진다). 판정할 수 없으면 폼 전용으로
    본다: 잘못 부르면 죽거나 설정을 지우지만, 건너뛰면 파생값이 그대로일 뿐이다."""
    import ast
    import inspect
    import textwrap
    try:
        tree = ast.parse(textwrap.dedent(inspect.getsource(hook)))
    except (OSError, TypeError, SyntaxError):
        return True
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))), None)
    if fn is None or len(fn.args.args) < 2:
        return True
    form = fn.args.args[1].arg
    tests = set()
    for n in ast.walk(fn):
        if isinstance(n, (ast.If, ast.IfExp, ast.While)) and \
                isinstance(n.test, ast.Name) and n.test.id == form:
            tests.add(id(n.test))
    return any(isinstance(n, ast.Name) and n.id == form and id(n) not in tests
               for n in ast.walk(fn))

class SystemToolsMixin:

    @classmethod
    def get_system_update_status(cls, **kwargs):
        """
        AoT 소프트웨어(시스템)의 업데이트 가용 여부를 확인합니다. 읽기 전용.

        현재 설치된 버전(AOT_VERSION)을, 이 설치가 실제로 업그레이드하는 경로의
        정본과 비교합니다 — 네이티브 설치는 GitHub 릴리스 태그, Docker 배포는
        컨테이너 레지스트리(GHCR)입니다. Docker에서 GitHub 태그를 보면 이미지
        빌드가 끝나기 전 구간에서 "설치할 수 없는 업데이트"를 알리게 됩니다.
        조회 실패/rate-limit 시 DB에 캐시된 Misc.aot_upgrade_available 로 폴백합니다.
        """
        try:
            from aot.config import AOT_VERSION
            from aot.utils.update_availability import (check_upgrade_exists,
                                                       is_docker_install,
                                                       running_image_reference,
                                                       updater_status)

            current_version = AOT_VERSION
            update_available = None
            latest_version = None
            available_releases = []
            errors = []

            # 1. 라이브 조회 (관리자 업그레이드 페이지와 동일 경로)
            try:
                (upgrade_exists,
                 releases,
                 _all_tags,
                 current_latest_tag,
                 check_errors) = check_upgrade_exists()
                update_available = bool(upgrade_exists)
                latest_version = current_latest_tag
                available_releases = releases or []
                errors = list(check_errors or [])
            except Exception as e:
                errors.append(str(e))

            # 2. 라이브 조회 실패 시 DB 캐시 플래그로 폴백
            if update_available is None:
                try:
                    mod_misc = Misc.query.first()
                    if mod_misc is not None:
                        update_available = bool(mod_misc.aot_upgrade_available)
                except Exception as e:
                    errors.append(str(e))

            is_docker = is_docker_install()
            source = "container registry (GHCR)" if is_docker else "GitHub release tags"

            if update_available is None:
                return {
                    "current_version": current_version,
                    "update_available": None,
                    "deployment": "docker" if is_docker else "native",
                    "message": (
                        f"Could not check for updates ({source} unreachable or "
                        "rate-limited). Try again later, or check Admin → Upgrade."
                    ),
                    "errors": errors,
                }

            if update_available:
                message = (
                    f"An update is available. Installed version {current_version}"
                    + (f", latest release {latest_version}." if latest_version else ".")
                    + " You can update from Admin → Upgrade."
                )
            else:
                message = f"You are on the latest version (currently {current_version})."

            result = {
                "current_version": current_version,
                "latest_version": latest_version,
                "update_available": update_available,
                "available_releases": available_releases,
                "deployment": "docker" if is_docker else "native",
                "update_source": source,
                "message": message,
                "errors": errors,
            }

            if is_docker:
                # Docker has no in-app upgrade path yet, so say how it is
                # actually applied instead of leaving the caller to assume the
                # Admin → Upgrade button exists.
                result["image"] = running_image_reference()
                result["one_click_update_available"] = updater_status()['present']
                if update_available and not result["one_click_update_available"]:
                    result["message"] += (
                        " This is a Docker install: the update is applied on the"
                        " host by pulling the new image and recreating the"
                        " containers."
                    )

            return result
        except Exception as e:
            return {"error": str(e)}

    @classmethod
    def get_local_time_tool(cls, target_name=None, target_id=None, **extra):
        """
        [읽기전용] 특정 위치(구역/시설/장치)의 현재 로컬시각·시간대를 반환한다.
        모든 지도 도형/장치는 좌표를 가지며 그로부터 IANA 시간대가 해석된다
        (aot/utils/device_tz.py — timezonefinder 기반, 명시적 설정이 없으면
        좌표→시간대, 그마저 없으면 농장 전체 기본 시간대로 폴백).

        위치에 대해 설명·계획할 때(예: "그 구역은 지금 몇시야?", "야간작업이라
        오늘 말고 내일로 옮기자") 이 도구로 실제 현지시각을 확인한 뒤 답하라
        — 전역 설정을 무조건 가정하지 말 것.
        """
        try:
            from aot.utils.timekit import FARM, tz_of
            from datetime import datetime as _dt, timezone as _tzinfo

            resolved_name = None
            if not target_id and target_name:
                target_id, _tt, resolved_name, _lat, _lng = \
                    cls._resolve_note_target(target_name)
                if not target_id and _tt == 'ambiguous':
                    # 이름이 여러 곳에 걸렸다. 농장 기본 시간대로 "성공" 이라
                    # 답하면 다른 시간대의 곳을 두고 틀린 시각을 확신하게 된다.
                    # 후보들의 시간대가 모두 같으면 그 답은 어느 쪽이든 맞다.
                    amb = cls._ambiguous_places(target_name) or []
                    tzs = {}
                    for c in amb:
                        try:
                            c["timezone"] = str(tz_of(c["target_id"]))
                        except Exception:
                            c["timezone"] = None
                        tzs.setdefault(c["timezone"], []).append(c)
                    if amb and len(tzs) == 1 and None not in tzs:
                        tz = tz_of(amb[0]["target_id"])
                        now_local = _dt.now(_tzinfo.utc).astimezone(tz)
                        return {
                            "status": "success",
                            "location": target_name,
                            "timezone": str(tz),
                            "local_time": now_local.strftime('%Y-%m-%d %H:%M:%S'),
                            "utc_offset": now_local.strftime('%z'),
                            "note": (f"'{target_name}' names {len(amb)} different "
                                     "places, all in this same timezone — the "
                                     "time is the same for each. Sunrise/sunset "
                                     "differ per place: pass one candidate's "
                                     "target_id for those."),
                            "candidates": amb,
                        }
                    return {
                        "status": "needs_disambiguation",
                        "error": "ambiguous_name",
                        "message": (f"'{target_name}' names {len(amb)} different "
                                    "places in different timezones. Ask which one, "
                                    "or answer for each using its 'timezone'; "
                                    "retry with a candidate's 'use_name' or "
                                    "'target_id' for its local time and sun."),
                        "candidates": amb,
                    }
                if not target_id:
                    return {
                        "status": "success",
                        "message": (f"위치 '{target_name}'를 찾지 못해 농장 기본 시간대로 "
                                    f"응답합니다."),
                        "available_targets": cls._geoshape_name_candidates(),
                        "location": "farm-wide (default)",
                        "timezone": str(tz_of(FARM)),
                        "local_time": _dt.now(_tzinfo.utc).astimezone(
                            tz_of(FARM)).strftime('%Y-%m-%d %H:%M:%S'),
                        "sun": cls._sun_block(None, tz_of(FARM)),
                    }

            tz = tz_of(target_id)
            now_local = _dt.now(_tzinfo.utc).astimezone(tz)
            return {
                "status": "success",
                "location": resolved_name or target_name or "farm-wide (default)",
                "timezone": str(tz),
                "local_time": now_local.strftime('%Y-%m-%d %H:%M:%S'),
                "utc_offset": now_local.strftime('%z'),
                "sun": cls._sun_block(target_id, tz),
            }
        except Exception as e:
            logger.error(f"Error in get_local_time_tool: {e}")
            return {"error": f"Error while resolving local time: {str(e)}"}

    @classmethod
    def _sun_block(cls, target_id, tz):
        """그 위치의 오늘 태양시 요약 — get_local_time 응답에 실린다.

        "지금 주간인가", "일몰까지 얼마 남았나"는 농작업 판단의 기본값인데
        (관수·분무·차광·환기는 전부 태양일에 묶인다), 지금까지 AI 는 시각만 알고
        해가 언제 뜨고 지는지는 몰라서 계절을 무시한 조언을 했다.
        좌표를 해석할 수 없으면 None — 호출부는 그대로 실어 보낸다.
        """
        try:
            from aot.utils.solar import STATUS_NORMAL, sun_times, is_daytime, next_sun_event
            from aot.utils.timekit import utc_now

            times = sun_times(target_id=target_id)
            if times is None:
                return None

            now = utc_now()

            def _local(dt):
                return dt.astimezone(tz).strftime('%Y-%m-%d %H:%M') if dt else None

            day = is_daytime(target_id=target_id, at=now)
            # 다음 경계 — 주간이면 일몰, 야간이면 일출.
            next_kind = 'sunset' if day else 'sunrise'
            next_dt = next_sun_event(next_kind, target_id=target_id, now=now)

            block = {
                "sunrise": _local(times.sunrise),
                "sunset": _local(times.sunset),
                "solar_noon": _local(times.solar_noon),
                "civil_dawn": _local(times.civil_dawn),
                "civil_dusk": _local(times.civil_dusk),
                "is_daytime": day,
                "status": times.status,
            }
            if times.day_length_seconds is not None:
                block["day_length_hours"] = round(times.day_length_seconds / 3600.0, 2)
            if next_dt is not None:
                block["next_event"] = {
                    "kind": next_kind,
                    "local_time": _local(next_dt),
                    "in_minutes": max(0, int((next_dt - now).total_seconds() // 60)),
                }
            if times.status != STATUS_NORMAL:
                block["note"] = ("이 위치·날짜에는 일출/일몰이 없습니다 "
                                 "(백야 또는 극야).")
            return block
        except Exception as e:
            logger.debug(f"_sun_block failed for {target_id}: {e}")
            return None

    @classmethod
    def analyze_system_failure_tool(cls, device_id=None, tool_name=None, lookback_minutes=60, **kwargs):
        """
        @ANCHOR: ANALYZE_SYSTEM_FAILURE_TOOL
        [031_STEP_3] Diagnostic RAG — audit AITask failure logs and MCP bridge status.

        Called by the Planner when the user reports a hardware failure or
        when 'operate_device' returns PC-099-ERROR. Provides specific reasons
        instead of generic error codes.

        Args:
            device_id:         (optional) Target device UUID/name to filter logs.
            tool_name:         (optional) MCP tool name that failed (e.g. 'operate_device').
            lookback_minutes:  How far back to search AITask logs (default 60 min).

        Returns:
            dict with 'failure_summary', 'failed_tasks', 'mcp_status', 'recommendation'.
        """
        try:
            from aot.tools import providers
            from aot.utils.timekit import utc_now

            cutoff = _tk_naive_utc(utc_now() - timedelta(minutes=int(lookback_minutes)))  # DB 열은 naive UTC

            # 1. Query recent failed AITask records
            failed_q = AITask.query.filter(
                AITask.status.in_(['failed', 'error']),
                AITask.created_at >= cutoff
            )
            if device_id:
                failed_q = failed_q.filter(
                    (AITask.target_id == device_id) | (AITask.title.contains(device_id))
                )
            failed_tasks_db = failed_q.order_by(AITask.created_at.desc()).limit(10).all()

            failed_tasks = []
            for t in failed_tasks_db:
                failed_tasks.append({
                    "task_id": t.unique_id,
                    "title": t.title,
                    "action_type": t.action_type,
                    "target_id": t.target_id,
                    "status": t.status,
                    "execution_result": (t.execution_result or '')[:300],
                    "created_at": iso_at(t.created_at, FARM) if t.created_at else None,
                })

            # 2. Query MCP server status
            mcp_status = []
            try:
                from aot.databases.models import MCPServer
                active_ids = providers.get('mcp_active_server_ids')()
                all_servers = MCPServer.query.filter_by(is_activated=True).all()
                for srv in all_servers:
                    # 자식 프로세스 목록은 프로세스마다 따로다 — MCP 컨테이너처럼 서버를 직접 띄우지 않는 곳은 목록이 비어
                    # 있어 멀쩡한 서버도 '오프라인' 이 된다(2026-10-29 점검). 이 프로세스가 아는 서버가 없으면 모름(None).
                    _is_degraded = (srv.unique_id not in active_ids) if active_ids else None
                    # 모르는 값(None)은 칸째 뺀다 — null 두 칸은 읽는 쪽이 '고장인가' 로 오해했다(2026-11-09 점검 6번).
                    # 아래 판정은 .get 으로 읽어 칸이 없으면 None 과 같다.
                    _row = {"name": srv.name, "unique_id": srv.unique_id}
                    if _is_degraded is not None:
                        _row["is_degraded"] = _is_degraded
                    if tool_name:
                        _row["has_tool"] = tool_name in (srv.tool_names or [])
                    mcp_status.append(_row)
            except Exception as _mcp_err:
                logger.warning(f"[031_STEP_3] Could not query MCP status: {_mcp_err}")
                mcp_status = [{"error": str(_mcp_err)}]

            # 3. Build failure summary
            failure_reasons = []
            if mcp_status and all(s.get('is_degraded') is None and not s.get('error') for s in mcp_status):
                failure_reasons.append("MCP server status is not readable from this process (unknown, not offline); "
                                       "a call that just answered means the server is reachable.")
            elif not [s for s in mcp_status if not s.get('is_degraded') and not s.get('error')]:
                _down = [s.get('name') for s in mcp_status if s.get('is_degraded')]
                if len(mcp_status) == 1 and _down:
                    failure_reasons.append("The only active MCP server (%s) is offline or unreachable." % _down[0])
                else:
                    failure_reasons.append("None of the %d active MCP servers is reachable." % len(mcp_status))
            elif tool_name:
                tool_server = next((s for s in mcp_status if s.get('has_tool') and not s.get('is_degraded')), None)
                if not tool_server:
                    failure_reasons.append(f"The MCP server providing the '{tool_name}' tool is offline.")

            for t in failed_tasks:
                err_text = t.get('execution_result', '')
                if 'PC-099-ERROR' in err_text:
                    failure_reasons.append(f"[{t['title']}] Physical execution failed: {err_text[:150]}")
                elif 'Safety violation' in err_text:
                    failure_reasons.append(f"[{t['title']}] Blocked by a safety constraint violation.")
                elif err_text:
                    failure_reasons.append(f"[{t['title']}] Error: {err_text[:150]}")

            recommendation = "Check the MCP server status, restart the server, or verify device connectivity."
            if not failure_reasons:
                recommendation = "No recent failure records. Check device power and network connectivity."

            return {
                "failure_summary": failure_reasons if failure_reasons else ["Could not identify a specific error cause."],
                "failed_tasks": failed_tasks,
                "mcp_status": mcp_status,
                "recommendation": recommendation,
                "lookback_minutes": lookback_minutes,
            }

        except Exception as e:
            logger.error(f"[031_STEP_3] analyze_system_failure_tool error: {e}")
            return {"error": f"Error while running diagnostic tool: {str(e)}"}

    @classmethod
    def list_pending_confirmations(cls, **extra):
        """[읽기전용] 지금 사람 승인을 기다리는 쓰기/제어 요청 목록. 이전 도구 호출이
        'pending_approval'을 반환했을 때, confirmation_id를 다시 찾거나 사용자에게
        무엇이 대기 중인지 보여줄 때 쓴다. 승인/거부 자체는 respond_to_confirmation을
        쓴다."""
        try:
            from aot.tools import mcp_safety_gate as gate
            from aot.utils.timekit import FARM, iso_at
            pending = gate.list_pending()
            for item in pending:
                # DB 의 naive UTC 를 그대로 내면 '08:12' 로 보여 농장 시각(17:12+09:00)과 어긋난다.
                item["created_at"] = iso_at(item.get("created_at"), FARM)
            return {"pending": pending}
        except Exception as e:
            return {"error": str(e)}

    @classmethod
    def list_ai_agents(cls, **extra):
        """List AI pipeline agents. Read-only."""
        try:
            from aot.databases.models.ai import AIAgent
            return {"agents": [{"agent_id": a.unique_id, "name": a.name, "role": a.role,
                                "pipeline_role": a.pipeline_role, "specialty": a.specialty,
                                "entry_id": a.entry_id, "is_activated": a.is_activated}
                               for a in AIAgent.query.all()]}
        except Exception as e:
            return {"error": str(e)}

    @classmethod
    def list_ai_entries(cls, **extra):
        """List AI service entries (models) that an agent can be bound to. Read-only.
        Call before create_ai_agent to get a valid entry_id."""
        try:
            from aot.databases.models.ai import AIEntry
            return {"entries": [{"entry_id": e.unique_id, "name": e.name,
                                 "model_type": e.model_type, "model_name": e.model_name}
                                for e in AIEntry.query.all()]}
        except Exception as e:
            return {"error": str(e)}

    @classmethod
    def create_ai_agent(cls, name=None, entry_id=None, role='worker', specialty='general',
                        system_prompt=None, pipeline_role='worker', model_tier='standard',
                        tool_access='auto', **extra):
        """Create a new AI pipeline agent bound to an AIEntry (AI service). Hardened:
        missing/invalid entry_id returns the available entries so the model can pick one."""
        import json as _json
        from aot.databases.models.ai import AIAgent, AIEntry
        if not name:
            return {"error": "name is required"}
        entries = AIEntry.query.all()
        if not entry_id:
            return {"error": "entry_id is required (the AI service to bind to)",
                    "available_entries": [{"entry_id": e.unique_id, "name": e.name} for e in entries]}
        entry = AIEntry.query.filter_by(unique_id=entry_id).first()
        if not entry:
            return {"error": f"AIEntry not found: {entry_id}",
                    "available_entries": [{"entry_id": e.unique_id, "name": e.name} for e in entries]}
        if not system_prompt:
            system_prompt = 'You are a helpful assistant for the AoT (AI of Things) platform.'
        try:
            agent = AIAgent(
                name=name, entry_id=entry_id, role=role, specialty=specialty,
                system_prompt=system_prompt, pipeline_role=pipeline_role,
                model_tier=model_tier, tool_access=tool_access,
                custom_options_json='{}', is_activated=False,
            )
            if hasattr(agent, 'save'):
                agent.save()
            else:
                db.session.add(agent); db.session.commit()
        except Exception as e:
            db.session.rollback()
            logger.error(f"[create_ai_agent] failed: {e}")
            return {"error": str(e)}
        r = {"agent_id": agent.unique_id, "name": name, "status": "created"}
        if extra:
            r["ignored_args"] = list(extra.keys())
        return r

    @classmethod
    def modify_ai_agent(cls, agent_id=None, **fields):
        """Update an AI agent's editable fields (name, role, specialty, system_prompt,
        pipeline_role, model_tier, tool_access, model_name). Unknown fields ignored."""
        from aot.databases.models.ai import AIAgent
        if not agent_id:
            return {"error": "agent_id is required"}
        agent = AIAgent.query.filter_by(unique_id=agent_id).first()
        if not agent:
            return {"error": f"Agent not found: {agent_id}"}
        allowed = {'name', 'role', 'specialty', 'system_prompt', 'pipeline_role',
                   'model_tier', 'tool_access', 'model_name'}
        changed, ignored = [], []
        for k, v in fields.items():
            if k in allowed:
                setattr(agent, k, v); changed.append(k)
            else:
                ignored.append(k)
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            return {"error": str(e)}
        r = {"agent_id": agent_id, "status": "modified", "changed": changed}
        if ignored:
            r["ignored_args"] = ignored
        return r

    @classmethod
    def delete_ai_agent(cls, agent_id=None, **extra):
        """Delete an AI agent by unique_id (also clears its MCP access mappings)."""
        from aot.databases.models.ai import AIAgent
        if not agent_id:
            return {"error": "agent_id is required"}
        agent = AIAgent.query.filter_by(unique_id=agent_id).first()
        if not agent:
            return {"error": f"Agent not found: {agent_id}"}
        try:
            from aot.databases.models.mcp_server import AgentMCPAccess
            AgentMCPAccess.query.filter_by(agent_unique_id=agent_id).delete()
        except Exception as e:
            logger.warning(f"[delete_ai_agent] mapping cleanup failed (non-fatal): {e}")
        try:
            db.session.delete(agent)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            return {"error": str(e)}
        return {"agent_id": agent_id, "status": "deleted"}

    @classmethod
    def resolve_target_tool(cls, target_name):
        """
        [Read-only, no approval required] Resolve a place/device name to its
        exact entity BEFORE calling a write tool that takes target_name (e.g.
        add_schedule, create_note, create_notice). Uses the same resolver
        those write tools use internally, so the result is guaranteed
        consistent with what a write call would attach to.

        Write tools sit behind a human-approval gate that only inspects the
        tool NAME, not its arguments — the target-name resolution itself only
        runs after approval is granted, which is too late to catch a wrong
        hierarchy level (e.g. a site name given when the request actually
        means each of its zones). Calling this tool first, before any write,
        surfaces that information while it still costs nothing to correct.

        Returns target_type and, if the entity contains finer-grained
        children (e.g. a site containing zones), their exact names in
        `children`. A write tool call attaches to ONLY the resolved entity —
        it never expands to `children` automatically. When the request
        implies handling each child separately, call the write tool once per
        entry in `children`, using that child's exact name.
        """
        import json as _json
        if not target_name or not str(target_name).strip():
            return {"status": "error", "message": "target_name is empty"}

        # 같은 이름이 서로 다른 곳 여럿이면 고르지 않는다(`_resolve_core`).
        # 예전에는 정렬 순서로 하나를 골라 "exactly one entity" 라고 답했다.
        # 쓰기 도구와 **같은 해석**을 한 번만 돌린다 — 정확일치뿐 아니라
        # 한정어('산양삼 1')·부분일치('육묘장에') 단계의 모호함도 여기서 나온다.
        detail = cls._resolve_explain(target_name)
        target_id, target_type, resolved_name, _lat, _lng = detail['result']
        if target_type == 'ambiguous':
            ambiguous = cls._public_places(
                cls._describe_places(detail['places'], detail['devices'], detail.get('plots', ())))
            no_name = [c for c in ambiguous if not c.get('use_name')]
            resp = {
                "status": "needs_disambiguation",
                "error": "ambiguous_name",
                "message": (f"'{target_name}' names {len(ambiguous)} different "
                            "things — see 'candidates'."),
                "candidates": ambiguous,
                "_reading": [
                    "Several different places/devices share this name, so "
                    "nothing was picked. Do not choose one yourself: ask the user "
                    "which one they mean, describing each candidate by its "
                    "'where'. If the question only reads data, you may instead "
                    "answer for EACH candidate, labelled by its 'where'.",
                    "After the user chooses, pass that candidate's 'use_name' as "
                    "target_name (it names only that one), or its 'target_id' "
                    "as target_id (add_schedule, edit_schedule, create_note and "
                    "get_local_time take one). A write tool given the bare name "
                    "will refuse."
                    + (" Some candidates have no 'use_name' — no name points at "
                       "only that one, so use its 'target_id'." if no_name else ""),
                ],
            }
            if any(c.get('match') for c in ambiguous):
                resp["_reading"].append(
                    "Plot candidates carry 'match': 'exact' (its name, crop or "
                    "variety is exactly the word), 'word' (a separate word of it, "
                    "e.g. '콩 7구') or 'fragment' (part of a longer word, e.g. "
                    "'검정콩'). An exact match is not the answer on its own — the "
                    "user's word usually means all of them, so ask.")
            return resp

        if not target_id:
            # A subject name found in two zones resolves to nothing above (a
            # coin-flip zone would be written to). Listing the subjects with their
            # zones turns that dead end into a question the user can answer.
            subject_targets = []
            try:
                seen = set()
                for p in cls._active_subject_plots():
                    key = (p['subject'], p['zone_name'])
                    if p['subject'] and key not in seen:
                        seen.add(key)
                        subject_targets.append({"subject": p['subject'], "zone": p['zone_name']})
            except Exception:
                subject_targets = []
            return {
                "status": "needs_disambiguation",
                "error": "target_not_found",
                "message": (
                    f"'{target_name}' could not be resolved to a known entity. "
                    "A crop name ('콩밭', '상추 재배지') also resolves, to the zone "
                    "it is in — see 'subject_targets'; when one subject appears "
                    "in several zones, ask which one and pass that zone name."
                ),
                "available_targets": cls._geoshape_name_candidates(),
                "subject_targets": subject_targets[:20],
            }

        children = []
        # 컨테이너(대지·구역·시설) 안의 쓰기 대상 — 구역·시설·구획 — 을 **소속
        # 경로와 함께** 낸다(2026-10-08 외부 MCP 점검). 예전에는 구획과 구역
        # 이름만 한 줄로 늘어놓아 시설이 빠지고, 시설 안 '콩' 과 노지 '콩 N구' 를
        # 구분할 수 없었다 — 쓰기 도구에 그 이름을 넘길 때 어느 쪽인지 몰랐다.
        # 소속은 정본(device_membership.PlaceIndex) — list_plots·search_devices 와
        # 같은 경로 표기다.
        child_ids = []
        if target_type in ('site', 'zone', 'facility'):
            try:
                from aot.space import device_membership as _dm
                from aot.space import plot_context as _pc
                _idx = _dm.PlaceIndex()
                _root = _idx.by_uid.get(target_id)
                if _root is not None:
                    _places = [sh for sh in _idx.shapes
                               if sh.type in ('zone', 'facility')
                               and sh.unique_id != target_id
                               and _dm.place_label(sh)
                               and target_id in _idx.chain_uids(sh)]
                    _places.sort(key=lambda sh: (len(_idx.chain(sh)),
                                                 0 if sh.type == 'zone' else 1,
                                                 _dm.place_label(sh)))
                    for sh in _places:
                        children.append({"name": _dm.place_label(sh), "type": sh.type,
                                         "place": _idx.path(sh)})
                        child_ids.append(sh.unique_id)
                    _plots = _pc.active_plots(_root.geo_id)
                    if _root.type == 'facility':
                        # 시설 구획은 기하로는 시설을 감싼 장소에 속한다 — 시설
                        # 지정(facility_uuid)으로 고른다.
                        from aot.databases.models import GeoFacility
                        _fac = GeoFacility.query.filter_by(
                            shape_uuid=target_id).first()
                        _plots = [pl for pl in _plots if _fac is not None
                                  and getattr(pl, 'facility_uuid', None) == _fac.unique_id]
                    else:
                        _plots = [pl for pl in _plots
                                  if _idx.plot_within(pl, target_id)]
                    for pl in sorted(_plots, key=lambda pl: (
                            _idx.plot_path(pl), pl.name or pl.subject or '')):
                        _pn = pl.name or pl.subject
                        if _pn:
                            children.append({"name": _pn, "type": "plot",
                                             "place": _idx.plot_path(pl)})
                            child_ids.append(pl.unique_id)
                    # 이름만으로 그것 하나를 가리키지 못하면(다른 곳에 같은 이름)
                    # 이 컨테이너 이름을 앞에 붙인 이름을 낸다 — '3포장 콩' 처럼
                    # 그 안으로 좁혀진다(_narrow_leftover). 되짚어 확인된 것만.
                    _rl = resolved_name or _dm.place_label(_root)
                    # 이름이 겹치는지는 한 번 세어 본다 — 자식마다 해석을 돌리면
                    # 자식 수 × 30ms 라 대지 하나에 0.6초가 들었다(실측).
                    _counts = cls._name_counts()
                    for c, cid in zip(children, child_ids):
                        try:
                            if _counts.get(c['name'].strip().lower(), 0) <= 1:
                                continue
                            if cls._resolve_note_target(c['name'])[0] == cid:
                                continue
                            _alt = '%s %s' % (_rl, c['name'])
                            if cls._resolve_note_target(_alt)[0] == cid:
                                c['use_name'] = _alt
                        except Exception:
                            continue
            except Exception:
                logger.debug('resolve_target: children 조회 실패', exc_info=True)

        note = (
            "This name resolves to exactly one entity. A write tool called with "
            "this target_name attaches ONLY to it."
        ) if not children else (
            "This name resolves to a container whose sub-entities are listed in "
            "'children'. A write tool called with this target_name attaches ONLY "
            "to the container itself - it does NOT automatically apply to each "
            "child. If the request applies to each child separately (e.g. 'each "
            "zone', 'per section'), call the write tool once per entry in "
            "'children', using that child's 'use_name' as target_name when it has "
            "one (its bare name also names something elsewhere), otherwise its "
            "name. Each child's 'place' says where it sits."
        )

        out = {
            "status": "success",
            "target_id": target_id,
            "target_type": target_type,
            "resolved_name": resolved_name,
            "children": children,
            "note": note,
        }
        out.update(cls._place_geo(target_type, target_id))
        # 같은 이름이 안팎으로 겹치면 이름은 바깥을 가리킨다. 안쪽(예: 부지
        # '육묘장' 안의 시설 '육묘장')을 원하는 도구가 그것을 잃지 않게 알린다.
        try:
            inner = cls._also_inside(detail.get('place'))
        except Exception:
            inner = []
        if inner:
            out["also_inside"] = inner
            out["note"] += (
                " The same name is also used by the shape(s) in 'also_inside', "
                "which sit inside this one; the name means this outer one. If a "
                "tool needs the inner one (e.g. a facility-only tool), pass its "
                "'target_id'.")
        # 장소 뒤의 낱말로 그 안의 하나를 골랐다면 어떻게 골랐는지 함께 낸다
        # (`_narrow_leftover`). 정확일치가 아니면 사람이 의도한 것인지 물을 몫이다.
        matched = detail.get('matched')
        if matched:
            out["matched"] = matched
            if matched.get('rule') not in ('exact', 'normalized'):
                out["note"] += (
                    " '%s' was picked inside '%s' because '%s' matches it as a %s "
                    "(not its exact name). Confirm with the user before writing to it."
                    % (resolved_name, matched.get('within'), matched.get('term'),
                       'separate word' if matched.get('rule') == 'word'
                       else 'part of a longer name'))
        # 장소 뒤에 붙은 낱말이 그 안의 어떤 것에도 걸리지 않았다(`_narrow_leftover`).
        # 조용히 버리면 '3포장 콩' 이 3포장 전체가 되던 것과 같은 모양이라,
        # 무시한 낱말과 그 결과를 응답에 적는다.
        ignored = detail.get('ignored_terms') or []
        if ignored:
            out["ignored_terms"] = ignored
            out["note"] += (
                " The words %s did not match any plot or device inside '%s', so "
                "they were IGNORED and this result is the whole of '%s'. If they "
                "were meant to pick something inside it, do not write to this "
                "target — ask the user, or pass a name from 'children'."
                % (', '.join("'%s'" % t for t in ignored), resolved_name,
                   resolved_name))
        return out

    @classmethod
    def _name_counts(cls):
        """이름(소문자) → 그 이름을 가진 대상 수 — 장소·구획·장치.

        resolve_target 의 children 에 use_name 이 필요한지 가리는 데만 쓴다.
        1 이면 이름이 그것 하나를 가리킨다. 구획은 이름 또는 작물명을 센다
        (리졸버가 둘 다로 찾는다)."""
        from collections import Counter
        out = Counter()
        try:
            from aot.space import shape_index
            for (_r, _n, nl) in shape_index.named_shapes():
                out[nl] += 1
        except Exception:
            pass
        try:
            from aot.databases.models import GeoPlot
            for name, subject in GeoPlot.query.with_entities(
                    GeoPlot.name, GeoPlot.subject).filter(
                    GeoPlot.ended_on.is_(None)).all():
                for v in {str(x).strip().lower() for x in (name, subject)
                          if x and str(x).strip()}:
                    out[v] += 1
        except Exception:
            pass
        try:
            from aot.databases.models import Input, Output
            for model in (Input, Output):
                for (n,) in model.query.with_entities(model.name).all():
                    if n and n.strip():
                        out[n.strip().lower()] += 1
        except Exception:
            pass
        return out

    @classmethod
    def _forecast_is_usable(cls):
        """예보 출처(Open-Meteo)가 등록돼 있는가 — 브리핑이 예보 도구를 안내할지 정한다."""
        try:
            return cls._open_meteo_forecast_source() is not None
        except Exception:                                   # noqa: BLE001
            return False

    @classmethod
    @tz_scoped
    def get_system_brief(cls, **extra):
        """[읽기전용] 이 시스템이 무엇이고 지금 어떤 상태인지 — 단일 진입점.

        도구를 수십 개 열어줘도 외부 AI는 "무엇을 언제 써야 하는가"를 모른다.
        인앱 AI는 시스템 프롬프트와 컨텍스트 자동주입으로 그 문제를 피하지만
        MCP 경로에는 그 파이프라인이 없다. 이 도구가 그 공백을 메운다:
        접속 직후 한 번 호출하면 공간 계층·작물·활성 제어·이상 여부·의견 원장
        현황과 다음에 쓸 도구를 함께 얻는다.

        개별 조회 도구를 대체하지 않는다 — 어디를 파야 할지 알려주는 지도다.
        """
        brief = {"status": "success"}
        S = cls

        def _safe(label, fn):
            """한 구획이 실패해도 브리핑 전체를 잃지 않는다."""
            try:
                return fn()
            except Exception as exc:
                logger.warning("get_system_brief: %s 실패: %s", label, exc)
                return {"error": f"Failed to read {label}: {exc}"}

        # ── 왜 요약만 싣는가 ────────────────────────────────────────────
        # 예전에는 `get_spatial_tree` · `get_crop_status` · `get_control_state`
        # 의 응답을 **통째로** 담았다. 세 도구의 합집합이라 이 도구 하나가
        # 18,974 토큰이 되어 **MCP 상한(15,000)을 넘었고, 잘린 채 전달됐다**
        # (실측 2026-09-05: spatial 6,841 · crops 6,844 · control 4,447).
        # 게다가 `crops` 는 `get_crop_status` 와 **정확히 같은 값**이라, 브리핑을
        # 읽고 그 도구를 다시 부르면 같은 6,844 를 두 번 냈다.
        #
        # 그래서 여기서는 **셀 수 있는 것과 이름만** 내고 어디서 자세히 볼지
        # 가리킨다 — 이 도구의 원래 목적("어디를 파야 할지 알려주는 지도")
        # 그대로다. 온전한 18,974 와 요약을 견주는 것이 아니라, **잘린 15,000
        # 과 온전한 요약**을 견주는 것이 옳은 비교다.
        #
        # ⚠ **이름을 빼지 말 것.** "구획 39건" 만 있으면 무엇이 있는지 알 수
        #   없어 반드시 되물어야 하고, 그러면 줄인 만큼을 두 번째 호출이 도로
        #   쓴다. 이름이 있으면 많은 질문이 여기서 끝난다.
        # 이름 목록의 상한. 설치가 커지면 이름만으로도 응답이 불어나므로
        # 자르되, **몇 건 중 몇 건인지**를 함께 남긴다("39건" 만 남기면 무엇이
        # 있는지 알 수 없어 되묻게 되고, 줄인 만큼을 두 번째 호출이 도로 쓴다).
        _NAME_CAP = 40

        def _capped(names):
            names = list(names or [])
            if len(names) <= _NAME_CAP:
                return names
            return names[:_NAME_CAP] + ["… +%d more" % (len(names) - _NAME_CAP)]

        def _spatial_summary():
            # 기본 보기 = 곳은 모든 깊이, 장치는 개수. 예전 depth=2 는 대지 안
            # 두 겹째 구역(3포장 > 1구역 > 3-1)의 이름을 빠뜨렸다.
            tree = S.get_spatial_tree() or {}
            nodes = tree.get("hierarchy") or []
            by_type, names = {}, {}
            def _walk(items):
                for n in items:
                    t = n.get("type") or "unknown"
                    by_type[t] = by_type.get(t, 0) + 1
                    if n.get("devices"):
                        by_type["device"] = by_type.get("device", 0) + n["devices"]
                    # 장치는 이름을 싣지 않는다 — 수가 많고 get_device_list 가 있다.
                    if t in ("site", "zone", "facility") and n.get("name"):
                        names.setdefault(t, []).append(n["name"])
                    _walk(n.get("children") or [])
            _walk(nodes)
            return {"counts": by_type,
                    "names": {k: _capped(v) for k, v in names.items()},
                    "see": "get_spatial_tree for the tree with devices"}

        def _crops_summary():
            # 이름을 모으려면 **잘리지 않은** 목록이 필요하다. 기본 limit(10)으로
            # 부르면 47건 중 앞쪽만 남아 작물 이름이 13개로 줄었다(2026-10-10 외부
            # AI 5차 점검 I-10). 브리핑은 이름과 개수만 내므로 구획 상세가 응답에
            # 실리지 않는다 — 전체를 받아도 크기는 이름 수만큼이고, 그것도
            # _capped 가 40개에서 자르며 몇 개가 더 있는지 밝힌다.
            cs = S.get_crop_status(limit=100000) or {}
            # `open_field_plots`/`facility_bay_plots` 는 get_crop_status 자체가
            # (2026-09-29부터) limit=30 으로 자를 수 있다 — 개수는 그 잘린
            # 목록의 len() 이 아니라 원본이 낸 참값(`plot_count`/
            # `facility_bay_plot_count`)으로 센다. 그 값을 그대로 더해서도 안
            # 된다 — `plot_count` 는 노지만 세므로 시설 구획과 더해야 합이
            # 맞는다(실측: 39 / 39 / 5).
            open_plots = cs.get("open_field_plots") or []
            bay_plots = cs.get("facility_bay_plots") or []
            n_open = cs.get("plot_count", len(open_plots))
            n_bay = cs.get("facility_bay_plot_count", len(bay_plots))
            subjects = []
            for p in list(open_plots) + list(bay_plots):
                sub = p.get("crop") or p.get("subject")
                if sub and sub not in subjects:
                    subjects.append(sub)
            # 시설 행은 이름·작물·단계만 남긴다. `controlled_by`(uuid)·
            # `season_window`·growth_stage 상세는 get_crop_status 가 내는 것과
            # **완전히 같은 값**이라 여기 다시 실으면 브리핑이 그 도구의 크기를
            # 그대로 흡수한다 — "see" 가 이미 그쪽을 가리킨다.
            facilities = [
                {k: f.get(k) for k in ('facility_name', 'crop', 'stage')
                 if f.get(k) is not None}
                for f in (cs.get("facilities") or [])]
            out = {
                "plot_count": n_open + n_bay,
                "open_field": n_open,
                "in_facility": n_bay,
                "subjects": _capped(subjects),
                "facilities": facilities,
                "see": "get_crop_status for every plot with its stage and guidance",
            }
            return out

        def _control_summary():
            st = S.get_control_state() or {}
            coords = st.get("coordinators") or []
            rows = []
            for c in coords:
                rows.append({"facility_name": c.get("facility_name"),
                             "function_name": c.get("function_name"),
                             "is_activated": c.get("is_activated")})
            return {"coordinator_count": len(coords), "coordinators": rows,
                    "see": ("get_control_state for targets, limiting factor "
                            "and safety-gate status")}

        brief["spatial"] = _safe("공간 계층", _spatial_summary)
        brief["crops"] = _safe("작물", _crops_summary)
        brief["control"] = _safe("제어 상태", _control_summary)
        # 이상 상태는 핵심만 싣는다 — get_anomalies 본문을 통째로 넣으면 정의 문단·_reading 까지
        # 붙어 브리핑의 큰 부분을 중복으로 채운다(2026-10-28 점검). 전체는 overview.anomalies.
        def _anomaly_summary():
            full = S.get_anomalies()
            if not isinstance(full, dict) or full.get("status") != "success":
                return full
            m = full.get("metrics") or {}
            sil = full.get("silent_devices") or {}
            return {k: v for k, v in {
                "anomaly_detected": full.get("anomaly_detected"),
                "alert_level": full.get("alert_level"),
                "anomalies": full.get("anomalies"),
                "comm_offline_devices": m.get("comm_offline_devices"),
                "comm_offline_list": full.get("comm_offline_list"),
                "silent_level": full.get("silent_level"),
                "silent_count": sil.get("count"),
                "silent_partial_count": sil.get("partial_silent_count"),
                "see": "get_anomalies for the metrics, definitions and silent devices",
            }.items() if v not in (None, [], "")}

        brief["anomalies"] = _safe("이상 상태", _anomaly_summary)
        # 핸들러 이름은 get_device_list_tool 이다(도구명과 다름). _safe 가 예외를
        # 처리하므로 hasattr 류의 방어 가드는 두지 않는다 — 가드를 두면 이름이
        # 틀렸을 때 조용히 빈 값이 되어 오히려 사실을 감춘다.
        # 집계의 정의를 응답에 함께 싣는다. 이 수(63)는 get_anomalies 의
        # metrics.total_devices(32)와 **다른 것을 센다** — 여기는 Input+Output+
        # Camera+복합장치 전부, 저기는 Input 만이다. 정의를 안 적어 두면 둘을
        # 나란히 본 AI 가 "장치 31개가 사라졌다" 로 읽는다(2026-08-17 실제 혼동).
        def _device_summary():
            _list = S.get_device_list_tool() or {}
            _res = _list.get("results") or []
            # 목록은 한 쪽(기본 40)만 싣는다 — 전체 수와 종류별 수는 자르기 전에 센
            # page.total·count_by_type 이다(길이를 세면 129개가 40개로 보고된다).
            _page = _list.get("page") or {}
            _by_type = _list.get("count_by_type") if _page else None
            if not _by_type:
                _by_type = {}
                for _r in _res:
                    _t = _r.get("type") or "unknown"
                    _by_type[_t] = _by_type.get(_t, 0) + 1
            return {
                "device_count": _page.get("total") or len(_res),
                "count_by_type": _by_type,
                "counts": ("device_count = every registered entity: inputs + "
                           "outputs + cameras + complex devices. get_anomalies' "
                           "metrics.total_devices counts INPUTS ONLY, so it is "
                           "normally smaller — the two are different definitions, "
                           "not a discrepancy."),
                "note": "Use get_device_list / search_devices for the full list",
            }

        brief["devices"] = _safe("장치 요약", _device_summary)
        pending = _safe("의견 원장", lambda: S.list_advice(status='pending', limit=5))
        brief["advice_ledger"] = {
            "pending_count": pending.get("count") if isinstance(pending, dict) else None,
            "recent": (pending.get("results") if isinstance(pending, dict) else None),
            "contested": (pending.get("multiple_agents_on_same_scope")
                          if isinstance(pending, dict) else None),
        }

        brief["how_to_proceed"] = [
            "1. Use this brief to identify the target (facility/zone) and its crop.",
            "2. To judge control, read get_control_state for current targets, the limiting "
            "factor and safety-gate status.",
            # 예보 안내는 **예보가 살아 있을 때만** 싣는다. 죽은 예보를 가리키면
            # 읽는 AI 가 매 대화마다 그 도구를 부르고, 매번 "예보가 오래됐다" 를
            # 사용자에게 보고한다 — 하지 말라고 해도 다음 대화의 브리핑이 다시
            # 시킨다(2026-09-16).
            ("3. Sensor history: get_sensor_detail." +
             (" Forecast: get_weather_forecast."
              if cls._forecast_is_usable() else "") +
             " If a reading looks missing or frozen, call "
             "get_device_freshness — anomalies.comm_offline_devices only counts drivers "
             "that report a fault themselves and stays 0 for a device that simply went "
             "silent."),
            "4. Look up growing guidance and manual references with knowledge_search.",
            "5. Check search_schedule for already-planned work to avoid duplicate or "
            "conflicting instructions.",
            "6. Submit findings with submit_advice; check list_advice first to see other "
            "AI opinions.",
            "7. Executing control (operate_device etc.) requires human approval. Do not "
            "retry direct execution - state what should be done and why, as advice.",
        ]
        return brief

    @classmethod
    def get_storage_tier_status(cls):
        """문서 스토리지 티어 현황 — 설정 활성 여부, 티어 분포, 아카이브 실물 통계."""
        try:
            from aot.databases.models.tier_adaptive_storage import (
                AdaptiveStorageSettings, TierDecision)
            from aot.databases.models.cold_storage import ColdDocuments

            settings = AdaptiveStorageSettings.query.first()
            enabled = bool(settings and settings.enabled)

            tier_counts = {}
            for tier, count in (db.session.query(Notes.tier, db.func.count(Notes.id))
                                .group_by(Notes.tier).all()):
                tier_counts[str(tier if tier is not None else 2)] = count

            archived_rows = ColdDocuments.query.count()
            decisions = TierDecision.query.count()

            out = {
                "status": "success",
                "adaptive_storage_enabled": enabled,
                "document_tier_counts": tier_counts,
                "archived_document_rows": archived_rows,
                "tier_decision_rows": decisions,
            }

            if not enabled:
                out["note"] = (
                    "Adaptive storage is DISABLED (no AdaptiveStorageSettings row, or "
                    "enabled=false). The hourly reclassification job exits immediately, "
                    "so tier values are not being updated at all.")

            # 가장 중요한 경고. tier 값과 실물 아카이브는 아직 연결돼 있지 않다.
            if archived_rows == 0 and any(t == '3' for t in tier_counts):
                out["warning"] = (
                    "Some documents are marked tier 3 (cold) but cold_documents is empty. "
                    "Tier migration is still a placeholder — the tier value records an "
                    "INTENT, not a completed move. Document content is still in its "
                    "original table. Do not tell the user a document was archived.")
            return out
        except Exception as e:
            logger.exception("Error in get_storage_tier_status")
            return {"status": "error", "message": str(e)}

    @classmethod
    def _widget_catalog(cls):
        from aot.utils.widgets import parse_widget_information
        return parse_widget_information()

    @classmethod
    def _jsonable(cls, value):
        """lazy_gettext 객체가 섞인 값을 JSON 직렬화 가능한 형태로 푼다.

        위젯 정의는 사람이 읽는 문구를 전부 `lazy_gettext` 로 감싸는데, 그
        객체는 `str` 의 하위 타입이 아니라 `json.dumps` 가 통째로 실패한다
        (`Object of type LazyString is not JSON serializable`). 그래서
        **필드마다 `str()` 을 손으로 붙이는 방식은 새 필드가 늘 때마다
        조용히 깨진다** — 실제로 `options_select` 가 그렇게 빠져서
        select 형 옵션을 가진 위젯(AoT_map·AoT_graph 등) 대부분에서
        `get_widget`/`list_widget_types` 가 응답을 만들지 못했다.

        중첩 구조를 그대로 유지한 채 lazy 객체만 문자열로 바꾼다. 튜플은
        JSON 에 없으므로 리스트가 된다.
        """
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, (list, tuple)):
            return [cls._jsonable(v) for v in value]
        if isinstance(value, dict):
            return {str(k): cls._jsonable(v)
                    for k, v in value.items()}
        return str(value)

    @classmethod
    def _widget_option_schema(cls, widget_info):
        """위젯 종류 하나의 옵션 스키마 — 사람이 읽을 수 있는 형태로.

        `name`/`phrase`/`options_select`/`default_value` 는 lazy_gettext
        객체를 담을 수 있어 그대로 JSON 으로 못 나간다 — `_jsonable` 을 지난다.
        """
        out = []
        for opt in (widget_info.get('custom_options') or []):
            if 'id' not in opt:
                continue
            entry = {
                'id': opt['id'],
                'type': opt.get('type'),
                'name': str(opt.get('name') or opt['id']),
            }
            if opt.get('phrase'):
                entry['phrase'] = str(opt['phrase'])
            if 'default_value' in opt:
                entry['default'] = cls._jsonable(
                    opt['default_value'])
            if opt.get('options_select'):
                entry['accepts'] = cls._jsonable(
                    opt['options_select'])
            out.append(entry)
        return out

    @classmethod
    def _coerce_widget_options(cls, widget_info, options):
        """AI 가 준 옵션을 스키마에 맞춰 거른다 → (정제된 dict, 오류 목록).

        **스키마에 없는 id 는 조용히 무시하지 않고 오류로 돌려준다.** 무시하면
        오타 하나가 "설정했다고 했는데 화면이 안 바뀐다" 로 나타나고, 그때
        원인이 위젯인지 도구인지 알 방법이 없다.

        값의 의미(그 장치가 실제로 있는지 등)까지는 보지 않는다 — 그것은 위젯
        자신의 훅이 판단할 몫이고, 여기서 흉내내면 두 벌이 되어 갈라진다.
        """
        schema = {opt['id']: opt for opt in (widget_info.get('custom_options') or [])
                  if 'id' in opt}
        clean, errors = {}, []
        for key, value in (options or {}).items():
            opt = schema.get(key)
            if opt is None:
                errors.append("unknown option '%s' for this widget type" % key)
                continue
            kind = opt.get('type')
            try:
                if kind == 'integer':
                    clean[key] = int(value)
                elif kind == 'float':
                    clean[key] = float(value)
                elif kind == 'bool':
                    clean[key] = bool(value)
                else:
                    # select_* / text / 그 밖 — 위젯이 문자열이나 목록으로 받는다.
                    clean[key] = value
            except (TypeError, ValueError):
                errors.append("option '%s' expects %s, got %r" % (key, kind, value))
        return clean, errors

    @classmethod
    def _widget_brief(cls, widget, widget_info=None):
        name = (widget.name or '').strip()
        out = {
            'widget_id': widget.unique_id,
            'name': name or None,
            'widget_type': widget.graph_type,
            'position': {'x': widget.position_x, 'y': widget.position_y,
                         'width': widget.width, 'height': widget.height},
        }
        if widget_info:
            out['type_name'] = str(widget_info.get('widget_name') or widget.graph_type)
        return out

    @classmethod
    def _notify_daemon_widget(cls, action, widget_id):
        """데몬에 위젯 변경을 알린다. 데몬이 없어도 저장은 유효하다.

        저장은 DB 에 끝났고 이 통지는 실행 중인 데몬의 캐시를 새로 고치는 것뿐
        이라, 실패를 저장 실패로 올리면 **성공한 작업을 실패로 보고**하게 된다.
        대신 무엇이 안 됐는지는 응답에 남긴다.
        """
        try:
            from aot.aot_client import DaemonControl
            control = DaemonControl()
            if action == 'remove':
                control.widget_remove(widget_id)
            else:
                control.widget_add_refresh(widget_id)
            return None
        except Exception as exc:
            logger.warning("[widget] 데몬 통지 실패(%s, %s): %s", action, widget_id, exc)
            return ("saved, but the running daemon could not be notified (%s) — "
                    "the dashboard may need a page reload to pick it up." % exc)

    @classmethod
    def get_screen(cls, user_id=None, focus=None, **extra):
        """[읽기전용] 키 주인이 지금 어느 기기로 어느 AoT 화면을 보고 있는가.

        웹 서버가 평소 요청에서 남긴 접속 기록(utils.web_presence)을 읽는다.
        `user_id` 는 인자가 아니라 인증에서 온다(tool_execution 이 덮어쓴다) —
        남의 접속 기록을 보는 수단이 되면 안 된다.

        시각은 "몇 초/분 전" 으로만 준다. 절대 시각을 주면 기기·농장 시간대가
        섞여 모델이 "지금" 을 잘못 읽는다(서버 안내문 TIME 단락과 같은 이유).
        """
        import time as _time
        from aot.utils import web_presence as wp

        if not user_id:
            return {"status": "error", "error": (
                "This connection is not tied to an AoT user, so there is no "
                "screen to look up.")}
        now = _time.time()
        rows = wp.recent(user_id, now=now)
        if not rows:
            return {"status": "success", "screens": [], "likely": None,
                    "confidence": "none",
                    "summary": ("The user has no AoT web page open (no visit in "
                                "the last 12 hours). Answer without a screen.")}

        dash_names = {}
        refs = {r['page_ref'] for r in rows
                if r.get('page_kind') == 'dashboard' and r.get('page_ref')}
        if refs:
            from aot.databases.models import Dashboard
            for d in Dashboard.query.filter(Dashboard.unique_id.in_(refs)).all():
                dash_names[d.unique_id] = d.name

        def ago(ts):
            return None if not ts else max(0, int(now - ts))

        def page_label(r):
            kind = r.get('page_kind')
            if not kind:
                return 'unknown page'
            if kind == 'dashboard' and r.get('page_ref'):
                name = dash_names.get(r['page_ref'])
                return "dashboard '%s'" % name if name else 'a dashboard (deleted)'
            if kind in wp.TAB_PAGE_TYPES:
                return cls._screen_page_label(r)
            return kind if kind != 'dashboard' else 'dashboard'

        screens = []
        for r in rows:
            item = {
                "device": r.get('device') or 'Browser',
                "form": r.get('form'),
                "page": page_label(r),
                "state": wp.state_of(r, now),
                "last_activity_s_ago": ago(r.get('seen_at')),
                "page_opened_s_ago": ago(r.get('page_at')),
                "last_user_action_s_ago": ago(r.get('acted_at')),
                "screen": r['browser_key'][:12],
                # P2 — 이 기기에서 사용자가 "AI 화면 조작 허용" 을 켰는가.
                "ai_control": "on" if r.get('ai_allowed') else "off",
            }
            # A6 — 조회한 곳을 이 화면에 함께 여는가(끔·묻기·자동). 자동이 기본이라
            # 다를 때만 싣는다.
            if r.get('ai_allowed') and wp.follow_mode(r) != wp.FOLLOW_DEFAULT:
                item["follow"] = wp.follow_mode(r)
            if wp.has_grant(r, now):
                item["confirmed"] = True     # 사용자가 이 화면을 확인해 줬다
            item.update(cls._screen_freshness(r, now))
            screens.append(item)
        idx, confidence = wp.pick_likely(rows, now)
        likely = screens[idx] if idx is not None else None
        focus = (focus or '').strip()
        fkey = focus.lower()
        live = cls._screen_live_state(rows[idx], now, with_maps=fkey in ('map', 'maps')) \
            if idx is not None else None
        if live:
            live.pop('_visible_ids', None)
            if live.get('dialog_text'):
                live['window_content'] = live.pop('dialog_text')
            likely = dict(likely, **live)
        row = rows[idx] if idx is not None else None
        kind = row.get('page_kind') if row else None
        dash = row.get('page_ref') if row and kind == 'dashboard' else None

        # 대화의 중심만 싣는다(사용자 2026-10-11: "불필요한 정보가 섞이지 않게, 과도한
        # 토큰 없이"). 지도 창이 열려 있으면 그 창, 아니면 보이는 위젯(대시보드)이나
        # 지금 탭의 카드(입력·출력·함수·구획). 그 밖의 것(탭 목록·모든 위젯·지도
        # 레이어)은 focus 로 요청할 때만.
        if likely is not None and likely.get('open_dialog') and dash:
            item = cls._screen_open_item(row, likely.get('open_dialog'))
            if item:
                likely['open_item'] = item
        if likely is not None and (kind in wp.TAB_PAGE_TYPES or kind == 'plots') \
                and not likely.get('open_dialog'):
            shown = cls._screen_page_content(row, user_id)
            if shown:
                likely['showing'] = shown

        if likely is not None and row is not None:
            miss = wp.last_view_miss(row['browser_key'], now=now)
            if miss:
                # 방금 AI 가 가리킨 곳으로 화면이 갔지만 사용자에게 안 보인다 — 보인다고 말하지 않게.
                likely['scroll_miss'] = "'%s' is not visible on the user's screen (%s); do not say it is shown" % miss
        if likely is not None:
            recent = cls._screen_recent_cards(user_id)
            if recent:
                likely['ai_cards'] = recent

        if likely is not None and fkey:
            # 요청한 것만 — 보이는 위젯 목록을 다시 붙이지 않는다.
            likely.pop('visible_widgets', None)
            if fkey == 'tabs':
                tabs = cls._screen_tab_list(user_id, kind)
                likely['tabs'] = [label for _tid, label in tabs]
            elif fkey in ('widgets', 'all') and dash:
                likely['widgets'] = cls._screen_all_widgets(dash)
            elif fkey in ('map', 'maps'):
                pass                         # 위에서 with_maps 로 실었다
            else:
                hit = cls._screen_focus_one(row, user_id, focus, dash)
                likely['focus'] = hit or (
                    "'%s' is not on this screen. For a place use get_place_overview, "
                    "for a device get_device_detail." % focus)

        if confidence == 'high':
            summary = "Most likely screen: %s on %s (%s)." % (
                likely['page'], likely['device'], 'being viewed now')
        elif confidence == 'low':
            summary = ("No page is being viewed right now. Last open: %s on %s, "
                       "%d min ago." % (likely['page'], likely['device'],
                                        (likely['last_activity_s_ago'] or 0) // 60))
        elif confidence == 'ambiguous':
            summary = ("Several screens are being viewed at once (%s). Ask the "
                       "user which one they mean." % ", ".join(
                           "%s on %s" % (s['page'], s['device'])
                           for s in screens if s['state'] == 'viewing'))
        else:
            summary = "No AoT page has been open in the last 30 minutes."
        if likely is not None:
            for k in ('page_opened_s_ago', 'last_user_action_s_ago'):
                likely.pop(k, None)
        # 다른 화면은 고를 때 필요한 것만 — 기기·페이지·상태·지정 값.
        # 오래 닫혀 있고 AI 조작도 꺼진 화면은 고를 일이 없다 — 싣지 않는다(재시험:
        # 매번 따라와 군더더기였고 어느 화면을 쓸지 헷갈리게 했다).
        others = [{k: s[k] for k in ('device', 'page', 'state', 'screen',
                                     'ai_control', 'stale_view') if s.get(k) is not None}
                  for i, s in enumerate(screens) if i != idx
                  and (s.get('state') == 'viewing' or s.get('ai_control') == 'on')]
        return {
            "status": "success",
            "summary": summary,
            "likely": likely,
            "confidence": confidence,
            "screens": others,
            "note": ("Shows what the conversation is about on that screen: the open "
                     "window's content, else the visible widgets or the open tab's "
                     "cards. focus='<widget or card name>' | 'widgets' | 'tabs' | "
                     "'map' for more. Before changing a screen, name the device and "
                     "page and get the user's OK."),
        }

    #: 자막은 60초 뒤 스스로 걷힌다(aot-ai-caption.js CAPTION_HIDE_MS) — 그 안에 올린 카드만 "떠 있을 수 있다".
    _CARD_ON_SCREEN_S = 60

    @classmethod
    def _screen_recent_cards(cls, user_id, cap=3):
        """방금 AI 가 띄운 카드(아직 안 닫힌 것) 몇 장 — 카드가 화면에 떠 있는지 AI 가 스스로 알게.
        화면이 실제로 보여 주는지는 모른다(사용자가 × 로 걷었을 수 있다). 닫기는 action=close_card."""
        from datetime import timedelta
        from aot.databases.models import AIScreenCard, User
        from aot.utils.timekit import utc_now
        user = User.query.filter(User.unique_id == user_id).first()
        if user is None:
            return []
        since = _tk_naive_utc(utc_now() - timedelta(seconds=cls._CARD_ON_SCREEN_S))  # DB 열은 naive UTC
        rows = (AIScreenCard.query
                .filter(AIScreenCard.user_id == user.id, AIScreenCard.dismissed_at.is_(None),
                        AIScreenCard.read_at.is_(None), AIScreenCard.created_at >= since)
                .order_by(AIScreenCard.created_at.desc()).limit(cap).all())
        return [{"card": c.unique_id[:8], "title": c.title or '',
                 "s_ago": max(0, int((_tk_naive_utc(utc_now()) - c.created_at).total_seconds()))} for c in rows]

    @classmethod
    def _screen_all_widgets(cls, dash, cap=24):
        """대시보드의 모든 위젯 — 한 줄씩(값은 위젯마다 셋까지). focus='widgets'."""
        from aot.databases.models import Widget
        ws = (Widget.query.filter(Widget.tab_id == dash)
              .order_by(Widget.position_y, Widget.position_x).limit(cap).all())
        ws = [w for w in ws if (w.name or '').strip()]
        contents = cls._screen_widget_contents([w.unique_id for w in ws],
                                               max_widgets=cap, max_values=3)
        return [cls._screen_with_type(contents.get(w.unique_id)
                                      or (w.name or '').strip(), w) for w in ws]

    #: 숨은 탭·끊긴 동기화로 보는 이 초 넘게 오래된 화면 상태는 낡았을 수 있다.
    _SCREEN_STALE_S = 30

    @classmethod
    def _screen_freshness(cls, row, now):
        """화면 JS 의 마지막 동기화(client_at)와 보임(visible)을 그대로 드러낸다.
        숨은 탭은 동기화를 멈추므로(2026-10-12 리허설: 대시보드 ~2분 지연) 숨었거나
        동기화가 오래됐으면 stale_view 한 줄로 AI 가 낡은 값을 최신으로 오해하지 않게
        한다. 서버가 이미 가진 값만 쓴다."""
        out = {}
        v = row.get('visible')
        visible = None if v is None else bool(v)
        synced = None
        if row.get('client_at'):
            synced = max(0, int(now - row['client_at']))
        if visible is not None and synced is not None:
            out['visible'] = visible
        if synced is not None:
            out['synced_s_ago'] = synced
        hidden = visible is False
        late = synced is not None and synced > cls._SCREEN_STALE_S
        if hidden or late:
            out['stale_view'] = (
                "This screen is %s, so what it shows may be out of date. Do not "
                "treat these values as current." % (
                    'hidden (background tab)' + (' and last synced %ds ago' % synced
                                                 if late else '')
                    if hidden else 'last synced %ds ago' % synced))
        return out

    #: 위젯 종류(graph_type = widget_name_unique) → 사람 말 분류. 모르는 값은 other.
    _WIDGET_KIND = {
        'AoT_map': 'map',
        'AoT_graph': 'graph',
        'AoT_gauge_angular': 'card', 'AoT_wind_angular': 'card',
        'widget_gauge_solid': 'card', 'widget_measurement': 'card',
        'widget_measurement_multi': 'card', 'widget_indicator': 'card',
        'widget_function_status': 'card', 'AoT_output_value': 'card',
        'AoT_output_pwm': 'card', 'AoT_controller_act_deact': 'card',
        'AoT_pid': 'card', 'AoT_timer': 'card', 'AoT_plot': 'card',
        'AoT_fcst_announcement': 'card', 'AoT_advice': 'card',
        'widget_trigger_sequence': 'card',
    }

    @classmethod
    def _widget_kind(cls, graph_type):
        """graph|card|map|other. 표에 없어도 이름에 graph/chart 가 들면 graph."""
        gt = (graph_type or '').strip()
        if gt in cls._WIDGET_KIND:
            return cls._WIDGET_KIND[gt]
        low = gt.lower()
        if 'graph' in low or 'chart' in low or '그래프' in gt:
            return 'graph'
        return 'other'

    @classmethod
    def _screen_with_type(cls, line, widget):
        """위젯 한 줄 뒤에 종류(graph_type)와 분류 {graph|card|map|other} 를 붙인다 —
        그래프인지 카드인지 이름만으로는 알 수 없다(2026-10-11 리허설)."""
        gt = (getattr(widget, 'graph_type', None) or '').strip()
        out = '%s [%s] {%s}' % (line, gt, cls._widget_kind(gt)) if gt and line else line
        # 위젯 id 앞 8자 — highlight·open_widget_settings 의 widget 이 받는다(G7).
        uid = (getattr(widget, 'unique_id', None) or '')[:8]
        return '%s #%s' % (out, uid) if uid and out else out

    @staticmethod
    def _screen_widget_pick(widgets, ref):
        """widget 인자(전체 id | 앞 8자 `#` 선택 | 이름) → (위젯, 오류). 이름이 겹치면
        오류로 id 를 알려 준다."""
        ref = str(ref or '').strip()
        key = ref.lstrip('#').lower()
        hit = [w for w in widgets if (w.unique_id or '').lower() == key]
        if not hit and len(key) >= 6 and all(c in '0123456789abcdef-' for c in key):
            hit = [w for w in widgets if (w.unique_id or '').lower().startswith(key)]
        if not hit:
            hit = [w for w in widgets if w.name == ref]
        if len(hit) > 1:
            return None, ("Several widgets match '%s': %s. Use the #id from "
                          "get_screen." % (ref, ', '.join(
                              '#' + w.unique_id[:8] for w in hit[:6])))
        return (hit[0] if hit else None), None

    @staticmethod
    def _screen_focus_widget(dash, ref):
        """대시보드에서 이름·id 앞부분으로 위젯 하나를 고른다(첫 번째) — 없으면 None."""
        if not dash:
            return None
        from aot.databases.models import Widget
        want = ref.strip().lower()
        ws = Widget.query.filter(Widget.tab_id == dash).all()
        tag = want.lstrip('#')
        hits = ([w for w in ws if len(tag) >= 6 and (w.unique_id or '').lower().startswith(tag)]
                or [w for w in ws if (w.name or '').strip().lower() == want]
                or [w for w in ws if want in (w.name or '').strip().lower()])
        return hits[0] if hits else None

    @classmethod
    def _screen_focus_pick(cls, row, ref):
        """설명하려는 위젯·카드 → 화면에 보이게 할 강조 인자, 없으면 None. 대시보드는 위젯, 입력·출력·함수
        페이지는 지금 보는 탭의 카드(이름이 둘 이상에 맞거나 다른 탭이면 고르지 않는다)."""
        ref = (ref or '').strip()
        if not ref:
            return None
        if row.get('page_kind') == 'dashboard':
            w = cls._screen_focus_widget(row.get('page_ref'), ref)
            return ({'widget_id': w.unique_id, 'id': w.unique_id, 'name': w.name,
                     'describe': "highlight widget '%s'" % w.name} if w is not None else None)
        if row.get('page_kind') in ('inputs', 'outputs', 'functions'):
            card, _problem = cls._screen_card_args(row, ref)
            return cls._screen_card_highlight(card) if card else None
        return None

    @classmethod
    def _screen_focus_one(cls, row, user_id, ref, dash):
        """대화의 중심이 된 것 하나 — 이 화면의 위젯이나 카드 이름으로."""
        from aot.utils import web_presence as wp
        want = ref.strip().lower()
        hit = cls._screen_focus_widget(dash, ref)
        if hit is not None:
            c = cls._screen_widget_contents([hit.unique_id], max_values=8)
            return cls._screen_with_type(c.get(hit.unique_id) or (hit.name or '').strip(), hit)
        if row.get('page_kind') in wp.TAB_PAGE_TYPES:
            for line in cls._screen_page_content(row, user_id, cap=60) or []:
                if want in line.lower():
                    return line
        return None

    @classmethod
    def _screen_page_content(cls, row, user_id, cap=8):
        """탭이 있는 페이지의 지금 탭 — 카드마다 핵심 한 줄(입력: 값 둘, 출력: 상태,
        함수: 실행 여부, 구획: 작목·품종·며칠째). 사람이 그 탭에서 보는 수준."""
        import datetime as _dt
        from aot.utils import web_presence as wp
        kind = row.get('page_kind')
        lines, more = [], 0
        try:
            if kind == 'plots':
                from aot.databases.models import GeoPlot
                ps = GeoPlot.query.filter(GeoPlot.ended_on.is_(None)).all()
                for p in ps[:cap]:
                    days = (today_at(p) - p.started_on).days if p.started_on else None
                    lines.append('%s%s%s' % (p.name or p.subject or 'plot',
                                             ' (%s)' % p.variety if p.variety else '',
                                             ', day %d' % days if days is not None else ''))
                more = max(0, len(ps) - cap)
            else:
                tabs = cls._screen_tab_list(user_id, kind)
                tab = row.get('page_ref') or (tabs[0][0] if tabs else None)
                if not tab:
                    return None
                if kind == 'inputs':
                    lines, more = cls._screen_input_cards(tab, cap)
                elif kind == 'outputs':
                    from aot.databases.models import Output
                    outs = Output.query.filter(Output.tab_id == tab).order_by(
                        Output.position_y, Output.id).all()
                    for o in outs[:cap]:
                        lines.append(cls._screen_output_text(o.unique_id)
                                     or (o.name or '').strip())
                    more = max(0, len(outs) - cap)
                elif kind == 'functions':
                    from aot.databases.models import (Conditional, CustomController,
                                                      Function, PID, Trigger)
                    found = []
                    for model in (CustomController, Conditional, Trigger, PID, Function):
                        found += model.query.filter(model.tab_id == tab).all()
                    for f in found[:cap]:
                        lines.append('%s: %s' % ((f.name or '').strip(),
                                                 'running' if f.is_activated else 'stopped'))
                    more = max(0, len(found) - cap)
        except Exception:                                   # noqa: BLE001
            return None
        if more:
            lines.append('+%d more (focus=<name> for one)' % more)
        return lines or None

    @classmethod
    def _screen_input_cards(cls, tab, cap):
        """입력 탭의 카드 — 장치마다 값 둘까지."""
        from aot.databases.models import DeviceMeasurements, Input
        try:
            from aot.utils.influx import get_last_measurement
        except Exception:                                   # noqa: BLE001
            get_last_measurement = None
        devs = Input.query.filter(Input.tab_id == tab).order_by(
            Input.position_y, Input.id).all()
        lines = []
        for d in devs[:cap]:
            vals = []
            if get_last_measurement is not None:
                for dm in DeviceMeasurements.query.filter(
                        DeviceMeasurements.device_id == d.unique_id).limit(3).all():
                    try:
                        last = get_last_measurement(d.unique_id, dm.unique_id, max_age=1800)
                    except Exception:                       # noqa: BLE001
                        last = None
                    if last and last[1] is not None:
                        try:
                            v = '%.1f' % float(last[1])
                        except (TypeError, ValueError):
                            v = str(last[1])
                        vals.append('%s %s' % ((dm.name or dm.measurement or '').strip(), v))
                    if len(vals) >= 2:
                        break
            name = (d.name or '').strip()
            if vals:
                lines.append('%s: %s' % (name, ' · '.join(vals)))
            else:
                lines.append(name + ('' if d.is_activated else ' (off)'))
        return lines, max(0, len(devs) - cap)

    @classmethod
    def _screen_open_item(cls, row, dialog):
        """열린 지도 창이 무엇의 창인가 — "이 구획" 을 풀 수 있게 종류·이름·id 만.

        화면은 창 제목만 보고한다(누가 열었든). 그 제목을 그 지도의 도형 이름으로
        풀어 본다 — 못 풀면 아무것도 싣지 않는다(제목은 open_dialog 에 이미 있다).
        값은 싣지 않는다: 값은 조회 도구가 더 정확하다."""
        suffix = ' (map)'
        if not dialog or not str(dialog).endswith(suffix):
            return None
        name = str(dialog)[:-len(suffix)].strip()
        if not name:
            return None
        try:
            args, problem = cls._screen_map_item_args(row, None, name, None)
        except Exception:                                   # noqa: BLE001
            return None
        if problem or not args:
            return None
        return {"kind": args.get('kind'), "name": args.get('name'),
                "id": args.get('id')}

    @classmethod
    def _screen_place_hint(cls, user_id):
        """지금 화면에 열려 있는 장소 하나 → ({kind, name, id} | None, 사유 | None).

        예보 도구가 `place` 없이 불릴 때 쓴다. 신선한(20초) 화면 중 열린 지도 창이
        하나로 풀리면 그것, 화면들의 열린 항목이 엇갈리면 None + 'screen ambiguous'.
        열린 창이 없으면 **보이는 지도가 비추는 대지**를 쓴다(2026-11-09 — 지도로 김제를
        보는데 장소 없이 물으면 농장 기본 좌표(영양)로 답했다): 지도 가운데가 든 대지,
        없으면 범위에 걸린 대지가 하나일 때만. 화면마다 다른 대지면 'screen ambiguous'.
        무거운 `_screen_live_state` 는 쓰지 않는다."""
        if not user_id:
            return None, None
        import json as _json
        import time as _time
        from aot.utils import web_presence as wp
        now = _time.time()
        opened, items, seen = 0, [], []
        for row in wp.recent(user_id, now=now):
            if not row.get('client_state') or now - (row.get('client_at') or 0) > 20:
                continue
            try:
                st = _json.loads(row['client_state'])
            except (TypeError, ValueError):
                continue
            if not isinstance(st, dict):
                continue
            if st.get('dialog'):
                opened += 1
            item = cls._screen_open_item(row, st.get('dialog'))
            if item and item.get('id'):
                items.append(item)
            elif not st.get('dialog'):
                site = cls._screen_map_site(st.get('maps'))
                if site:
                    seen.append(site)
        if items:
            if len({i['id'] for i in items}) == 1:
                return items[0], None
            return None, 'screen ambiguous'
        if seen:
            if len({i['id'] for i in seen}) == 1:
                return seen[0], None
            return None, 'screen ambiguous'
        # 신선한 화면이 있어도 열린 창이 하나도 없으면 엇갈린 게 아니다 — 사유 없음.
        return None, ('screen ambiguous' if opened else None)

    @classmethod
    def _screen_map_site(cls, maps):
        """화면이 보고한 지도들(보이는 위젯만 온다)이 비추는 대지 하나 → {kind, name, id} | None.

        지도 가운데가 든 대지가 먼저, 없으면 범위에 걸린 대지가 하나일 때만. 지도끼리
        엇갈리거나 못 풀면 None — 추측하지 않는다."""
        import json as _json
        found = {}
        for m in (maps if isinstance(maps, list) else [])[:2]:
            if not isinstance(m, dict):
                continue
            view = m.get('view') if isinstance(m.get('view'), dict) else {}
            try:
                west, south, east, north = [float(v) for v in view.get('bounds')]
            except (TypeError, ValueError):
                continue
            try:
                from aot.databases.models import Widget
                w = Widget.query.filter(Widget.unique_id == str(m.get('widget_id'))).first()
                map_uuid = _json.loads((w.custom_options if w else None) or '{}').get('map_uuid')
                if not map_uuid:
                    continue
                from shapely.geometry import Point, box
                from aot.space import device_membership as dm
                sites = [(sh, poly) for sh, kind, poly in dm.load_containers(map_uuid)
                         if kind == 'site' and poly is not None]
            except Exception:                               # noqa: BLE001
                logger.debug("screen map site lookup failed", exc_info=True)
                continue
            center = Point((west + east) / 2.0, (south + north) / 2.0)
            hit = [sh for sh, poly in sites if poly.contains(center)]
            if not hit:
                frame = box(west, south, east, north)
                hit = [sh for sh, poly in sites if poly.intersects(frame)]
            if len({sh.unique_id for sh in hit}) != 1:
                if hit:
                    return None
                continue
            sh = hit[0]
            found[sh.unique_id] = {"kind": "site", "id": sh.unique_id,
                                   "name": cls._shape_display_name(sh) or sh.unique_id}
        return next(iter(found.values())) if len(found) == 1 else None

    @classmethod
    def _screen_live_state(cls, row, now, with_maps=False):
        """화면 JS 가 방금(20초 안) 보고한 세부 상태 — 열린 창, 보이는 위젯.
        "AI 화면 조작 허용" 을 켠 기기만 보고한다."""
        import json as _json
        if not row.get('client_state') or now - (row.get('client_at') or 0) > 20:
            return None
        try:
            st = _json.loads(row['client_state'])
        except ValueError:
            return None
        out = {}
        if st.get('dialog'):
            out['open_dialog'] = str(st['dialog'])[:80]
        under = {}
        if st.get('dialog_tabs'):
            # 열린 지도 창의 탭 — modal_tab 이 이 이름을 받는다.
            under['dialog_tabs'] = [str(t)[:40] for t in st['dialog_tabs']][:8]
            under['dialog_tab'] = str(st.get('dialog_tab') or '')[:40] or None
        if st.get('dialog_text'):
            # 열린 지도 창의 지금 탭에 보이는 글 — 사용자가 보는 것과 같은 내용의
            # 요약(화면이 상한을 두고 보낸다). 대화의 중심이 그 창일 때 쓴다.
            under['dialog_text'] = str(st['dialog_text'])[:600]
        nd = st.get('notes_drawer')
        if isinstance(nd, dict):
            # 노트 서랍이 맨 위 — 서랍의 내용을 싣고, 아래 깔린 지도 창의 값은
            # 서랍 값으로 오인되지 않게 underlying_dialog 로 묶는다(2026-10-15).
            out['notes_drawer'] = {
                'title': str(nd.get('title') or '')[:60],
                'items': [str(i)[:40] for i in (nd.get('items') or [])][:5]}
            if under:
                u = {'tabs': under.get('dialog_tabs'), 'tab': under.get('dialog_tab'),
                     'text': under.get('dialog_text')}
                out['underlying_dialog'] = {k: v for k, v in u.items() if v}
        else:
            out.update(under)
        ids = [str(i) for i in (st.get('visible_widgets') or [])][:40]
        map_ids = [str(m.get('widget_id')) for m in (st.get('maps') or [])
                   if isinstance(m, dict)][:2]
        seen_cache = {}               # 지도 위젯 id → (범위 안 이름, 범위 안 구획) — 한 번만 구한다
        names = {}
        widgets = {}
        if ids or map_ids:
            from aot.databases.models import Widget
            widgets = {w.unique_id: w for w in
                       Widget.query.filter(Widget.unique_id.in_(ids + map_ids)).all()}
            names = {k: (w.name or '').strip() for k, w in widgets.items()}
        if st.get('dialog_device_id'):
            # 열린 설정창이 어느 장치의 것인가(모달 id 에서) — 종류와 문서로 가는 길까지.
            opened = cls._screen_open_settings(str(st['dialog_device_id'])[:40])
            if opened:
                out['open_settings'] = opened
        out['_visible_ids'] = [i for i in ids if names.get(i)]
        if ids and not out.get('open_dialog'):
            # 보이는 위젯이 지금 보여 주는 값까지 — "화면의 내용을 볼 수 있냐" 에
            # 답할 수 있게(2026-10-11). 이름만 주면 AI 는 "안 보인다" 고 답했다.
            # 창이 열려 있으면 대화의 중심은 그 창이다 — 뒤의 위젯 값은 섞지 않는다
            # (사용자 2026-10-11: "불필요한 정보가 섞이지 않게").
            contents = cls._screen_widget_contents(out['_visible_ids'])
            # 지도 위젯 줄에는 지금 지도에 보이는 곳과 그려진 도형 색·기상 표현을 붙인다
            # (지도 상세는 focus='map'). 사용자가 "파란 도형이 뭐야" 하고 물을 때 AI 가 focus 를
            # 알아서 고르리라 기대하지 않는다 — 기본 응답에 짧게 싣는다.
            for m in (st.get('maps') or [])[:2]:
                if not isinstance(m, dict):
                    continue
                wid = str(m.get('widget_id'))
                if wid in out['_visible_ids']:
                    seen, plots = cls._screen_map_seen(widgets.get(wid), m, seen_cache)
                    extra = []
                    if seen and seen.get('in_view'):
                        extra.append('in view: %s' % seen['in_view'])
                    look = _look.look_short(m, plots)
                    if look:
                        extra.append(look)
                    if extra and wid in contents:
                        contents[wid] += ' · ' + ' · '.join(extra)
                    elif extra:                 # 내용 줄이 없는 지도 위젯(지도 미지정)도 이름 뒤에 붙인다
                        contents[wid] = '%s — %s' % (names[wid], ' · '.join(extra))
            out['visible_widgets'] = [
                cls._screen_with_type(contents.get(i) or names[i], widgets.get(i))
                for i in out['_visible_ids']]
            # 위젯 줄 값은 잠깐 담아 둔 것일 수 있다 — 5초 넘게 묵었으면 알린다.
            import time as _time
            ages = [_time.time() - cls._SCREEN_CONTENT_CACHE[(i, 6)][0]
                    for i in out['_visible_ids'] if (i, 6) in cls._SCREEN_CONTENT_CACHE]
            if ages and max(ages) >= 5:
                out['values_age_s'] = int(max(ages))
        maps = []
        for m in ((st.get('maps') or [])[:2] if with_maps else []):
            if not isinstance(m, dict):
                continue
            # 사용자가 보는 것만 — 바탕 지도와 켜진 레이어. 고를 수 있는 레이어
            # 목록 전체(실측 500여 토큰)는 싣지 않는다: map_control 이 없는 이름을
            # 받으면 그 오류가 목록을 알려 준다(_screen_map_control_args).
            keep = {k: m.get(k) for k in ('base', 'overlays_on', 'shapes_hidden',
                                          'labels_hidden') if m.get(k)}
            # 보기 상태 — map_control 의 결과를 화면에서 읽어 확인할 수 있게.
            view = m.get('view') if isinstance(m.get('view'), dict) else {}
            if view.get('bearing'):
                keep['bearing'] = view['bearing']
            if m.get('pitch'):
                keep['pitch'] = m['pitch']
            if m.get('fullscreen'):
                keep['fullscreen'] = True
            # 지도 조작(map_control)은 이 이름들로 받는다 — 위젯은 이름으로 부른다.
            item = dict(map=names.get(str(m.get('widget_id'))) or None, **keep)
            # 지금 지도에 보이는 곳 — 범위와 확대 수준에서 이름만 뽑는다.
            seen, plots = cls._screen_map_seen(widgets.get(str(m.get('widget_id'))), m, seen_cache)
            if seen:
                item.update(seen)
            # 그려진 도형의 색(종류·구획별)과 기상 표현이 어떻게 보이고 무엇을 뜻하는지.
            item.update(_look.look_detail(m, plots))
            maps.append(item)
        if maps:
            out['maps'] = maps
        here = cls._screen_here(st.get('here'), row, now, widgets)
        if here:
            out['here'] = here
        return out or None

    #: 사용자가 켠 '현재 위치'를 이 시간(초)이 지나면 읽지 않는다(화면도 10분에 스스로 끈다).
    _SCREEN_HERE_MAX_AGE_S = 600

    @classmethod
    def _screen_here(cls, raw, row, now, widgets):
        """화면이 보고한 현재 위치 → 서버가 푼 관계(이름·거리·오차). **좌표는 싣지 않는다.**

        "AI 화면 조작 허용"을 켠 기기만, 20초 안의 보고(호출자가 이미 거른다)에서, 측정 뒤
        10분 안일 때만. 기기 시계와 맞대지 않도록 화면은 측정 뒤 지난 시간(age_s)을 보낸다.
        """
        import json as _json
        if not isinstance(raw, dict) or not row.get('ai_allowed'):
            return None
        try:
            lat, lng = float(raw['lat']), float(raw['lng'])
            acc = float(raw['acc'])
            age = float(raw.get('age_s') or 0) + max(0.0, now - (row.get('client_at') or now))
        except (KeyError, TypeError, ValueError):
            return None
        if not (-90 <= lat <= 90 and -180 <= lng <= 180) or acc <= 0 or age > cls._SCREEN_HERE_MAX_AGE_S:
            return None
        map_uuid = None
        try:
            wid = str(raw.get('widget_id') or '')
            w = widgets.get(wid)
            if w is None and wid:
                from aot.databases.models import Widget
                w = Widget.query.filter(Widget.unique_id == wid).first()
            if w is not None:
                map_uuid = _json.loads(w.custom_options or '{}').get('map_uuid')
            from aot.utils import geo_distance
            around = geo_distance.around_point(lat, lng, acc, map_uuid=map_uuid)
        except Exception:
            logger.exception('screen here: 현재 위치 풀이 실패')
            return None
        out = dict(age_s=int(age), **around)
        # 어떻게 정한 자리인가 — 'gps'(기기 위치) · 'center'(보던 지도의 중심) · 'pick'(지도를 눌러 고른 곳) ·
        # 'search'(주소 검색 결과) · 'favorite'(즐겨찾기).
        # 사람이 지도에서 고른 자리는 화면이 이미 푼 주소 한 줄을 같이 받는다(서버가 외부 지오코더를 부르지 않는다).
        src = raw.get('src')
        if src in ('center', 'pick', 'search', 'favorite'):
            out['source'] = src
            addr = str(raw.get('addr') or '').strip()[:160]
            if addr:
                out['address'] = addr
        return out

    #: 위젯 설정에서 값을 가리키는 "장치 uuid,채널 uuid" 쌍.
    _WIDGET_VALUE_PAIR = None

    @staticmethod
    def _screen_effective_unit(dm):
        """채널 값이 실제로 저장된 단위 — 변환(Conversion)이 걸렸으면 변환 뒤 단위.

        InfluxDB 에는 변환된 값이 변환 단위로 쌓이므로 `dm.unit`(원 단위)을 그대로
        쓰면 값은 °C 인데 "°F" 로 읽힌다(2026-10-11, 실외 온도 20.3 °F). 웹 위젯과
        같은 기준인 return_measurement_info 를 따른다."""
        from aot.databases.models import Conversion
        from aot.utils.system_pi import return_measurement_info
        conv = None
        if getattr(dm, 'conversion_id', None):
            conv = Conversion.query.filter(
                Conversion.unique_id == dm.conversion_id).first()
        _ch, unit, _meas = return_measurement_info(dm, conv)
        return unit or dm.unit

    @classmethod
    def _screen_widget_contents(cls, widget_ids, max_widgets=8, max_values=6):
        """보이는 위젯마다 지금 보여 주는 것 — 사람이 화면에서 보는 수준의 한 줄.

        위젯은 값을 "장치 uuid,채널 uuid" 쌍으로 가리킨다(measurement·
        measurement_speed·그래프 계열 …). 그 쌍의 마지막 값을 읽는다 — 그래프의
        시계열 전체는 싣지 않는다(값이 더 필요하면 조회 도구가 정확하다).

        - 값 하나인 위젯(게이지): "온도 — 17.8 °C"(위젯 이름이 곧 설명이다).
        - 값 여럿: 장치마다 묶어 그 장치 이름을 붙인다 — "육묘장 온습도: 온도 21.0 °C ·
          습도 53.0 %". 같은 장치 안에서 채널 이름이 겹치면("Wind" 둘) 측정 종류를
          덧붙인다. 장치 이름 없이 채널 이름만 주면 화면의 라벨과 다르게 읽혔다.
        - 지도 위젯: 어느 지도(그 지도의 대지)를 띄웠는지 먼저 — 위젯 이름("GIS")만으로는
          그 지도가 '영양' 인지 알 수 없었다(2026-10-11).
        값이 없는 위젯(제어기 등)은 싣지 않는다 — 호출자가 이름만 쓴다."""
        import json as _json
        import re as _re
        from aot.databases.models import DeviceMeasurements, Input, Output, Widget
        if cls._WIDGET_VALUE_PAIR is None:
            u = r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}'
            cls._WIDGET_VALUE_PAIR = _re.compile('(%s),(%s)' % (u, u))
        try:
            from aot.config_devices_units import UNITS
        except Exception:                                   # noqa: BLE001
            UNITS = {}
        try:
            from aot.utils.influx import get_last_measurement
        except Exception:                                   # noqa: BLE001
            get_last_measurement = None
        import time as _time
        out = {}
        now = _time.time()
        want = list(widget_ids)[:max_widgets]
        # 같은 위젯을 몇 초 안에 다시 묻는 일이 잦다(get_screen 을 잇달아 부른다) —
        # 값 조회가 위젯마다 InfluxDB·데몬을 부르므로 잠깐 담아 둔다.
        cache = cls._SCREEN_CONTENT_CACHE
        for wid in list(want):
            hit = cache.get((wid, max_values))
            if hit and now - hit[0] < cls._SCREEN_CONTENT_TTL_S:
                if hit[1]:
                    out[wid] = hit[1]
                want.remove(wid)
        rows = Widget.query.filter(Widget.unique_id.in_(want)).all() if want else []
        outputs = {r.unique_id: r for r in Output.query.all()} if rows else {}
        for w in rows:
            raw = w.custom_options or ''
            try:
                opts = _json.loads(raw) if raw else {}
            except ValueError:
                opts = {}
            head = cls._screen_map_heading(opts) if w.graph_type == 'AoT_map' else None
            pairs = []
            out_ids = []          # 이 위젯이 보여 주는 출력 — 값이 아니라 상태다
            for dev, meas in cls._WIDGET_VALUE_PAIR.findall(raw):
                if dev in outputs:
                    if dev not in out_ids:
                        out_ids.append(dev)
                    continue
                if (dev, meas) not in pairs:
                    pairs.append((dev, meas))
            extra = cls._screen_widget_extra(w, opts, out_ids)
            try:
                age = int(float(opts.get('max_measure_age') or 1800))
            except (TypeError, ValueError):
                age = 1800
            try:
                places = max(0, min(int(opts.get('decimal_places', 1)), 3))
            except (TypeError, ValueError):
                places = 1
            groups = {}                     # 장치 → [(채널 이름, 측정 종류, 글)]
            order = []
            for dev, meas in pairs[:max(0, max_values - len(extra))]:
                if get_last_measurement is None:
                    break
                dm = DeviceMeasurements.query.filter(
                    DeviceMeasurements.unique_id == meas).first()
                if dm is None:
                    continue
                try:
                    last = get_last_measurement(dev, meas, max_age=age)
                except Exception:                           # noqa: BLE001
                    last = None
                eff = cls._screen_effective_unit(dm)
                if eff == 'bearing':
                    unit = '°'
                else:
                    unit = (UNITS.get(eff) or {}).get('unit', eff or '')
                if last and last[1] is not None:
                    try:
                        val = ('%.' + str(places) + 'f') % float(last[1])
                    except (TypeError, ValueError):
                        val = str(last[1])
                    text = ('%s%s%s' % (val, '' if unit == '°' else ' ', unit)).strip()
                elif len(pairs) == 1:
                    text = 'no recent value'
                else:
                    continue        # 여러 값 중 비어 있는 것은 줄만 차지한다
                if dev not in groups:
                    groups[dev] = []
                    order.append(dev)
                groups[dev].append(((dm.name or dm.measurement or '').strip(),
                                    (dm.measurement or '').strip(), text))
            parts = []
            if len(pairs) == 1 and order and not head and not extra:
                parts.append(groups[order[0]][0][2])
            elif order:
                names = cls._screen_device_names(order)
                model_devs = cls._screen_model_devices(order)
                sim_devs = cls._screen_sim_devices(order)
                for dev in order:
                    labels = [lab for lab, _m, _t in groups[dev]]
                    vals = ' · '.join(
                        ('%s (%s) %s' % (lab, m, t)) if lab and m and labels.count(lab) > 1
                        else ('%s %s' % (lab, t) if lab else t)
                        for lab, m, t in groups[dev])
                    # 장치가 하나뿐인 그래프는 위젯 이름이 이미 설명이라 장치 이름을 뺀다.
                    if len(order) > 1 or head:
                        vals = '%s%s%s: %s' % (names.get(dev) or 'device',
                                               ' [model]' if dev in model_devs else '',
                                               ' [sim]' if dev in sim_devs else '', vals)
                    parts.append(vals)
            parts.extend(extra)
            line = None
            if head or parts:
                line = '%s — %s' % ((w.name or '').strip(), ' / '.join(
                    ([head] if head else []) + parts))[:240]
                out[w.unique_id] = line
            cache[(w.unique_id, max_values)] = (now, line)
        if len(cache) > 500:
            cache.clear()
        return out

    #: 위젯 내용 캐시 — (위젯 id, 값 상한) → (시각, 한 줄).
    _SCREEN_CONTENT_CACHE = {}
    _SCREEN_CONTENT_TTL_S = 15.0

    @staticmethod
    def _screen_model_devices(ids):
        """값이 실측이 아니라 모델인 입력 장치 id (data_origin 표기용)."""
        try:
            from aot.databases.models import Input
            from aot.utils.inputs import model_input_drivers
            md = model_input_drivers()
            return {r.unique_id for r in Input.query.filter(
                Input.unique_id.in_(list(ids))).all() if r.device in md}
        except Exception:                                   # noqa: BLE001
            return set()

    @staticmethod
    def _screen_sim_devices(ids):
        """시뮬레이션 장치로 표시할 입력 id — 표시 전용(`[sim]`)."""
        try:
            from aot.databases.models import Input
            from aot.tools.sim_marker import is_simulated
            return {r.unique_id for r in Input.query.filter(
                Input.unique_id.in_(list(ids))).all()
                if is_simulated('input', r.device, r.name)[0]}
        except Exception:                                   # noqa: BLE001
            return set()

    @classmethod
    def _screen_device_names(cls, ids):
        """장치·함수 id → 이름(입력·출력·함수 모두 — 그래프가 함수 값도 보여 준다)."""
        from aot.databases.models import Input, Output
        names = {}
        for model in (Input, Output):
            names.update({r.unique_id: (r.name or '').strip() for r in
                          model.query.filter(model.unique_id.in_(ids)).all()})
        for i in ids:
            if i in names:
                continue
            try:
                row, _k, _c, err = cls._resolve_function_target(i)
            except Exception:                               # noqa: BLE001
                row, err = None, True
            if row is not None and not err:
                names[i] = (row.name or '').strip()
        return names

    @classmethod
    def _screen_output_text(cls, output_id):
        """출력 하나의 지금 상태 — "켜짐/꺼짐", 여닫이면 "열림 35 %"."""
        try:
            st = cls._output_state_one(output_id)
        except Exception:                                   # noqa: BLE001
            return None
        if not isinstance(st, dict) or st.get('status') == 'error':
            return None
        name = (st.get('name') or '').strip()
        pos = st.get('position') or {}
        if pos.get('percent') is not None:
            txt = 'open %g %%' % round(float(pos['percent']), 1)
        else:
            chans = st.get('channels') or {}
            states = [str((c or {}).get('state')) for c in chans.values()
                      if (c or {}).get('state') is not None]
            if not states:
                return None
            txt = states[0] if len(set(states)) == 1 else ', '.join(states[:4])
        return ('%s %s' % (name, txt)).strip()

    @classmethod
    def _screen_widget_extra(cls, w, opts, out_ids):
        """측정값이 아닌 위젯 내용 — 출력 상태·함수 상태·구획·공지·승인 대기.

        사람이 그 위젯에서 보는 핵심 한두 마디만. 2026-10-11 실측: 타이머·천창·인버터·
        함수 상태·밸브 순차 제어·품종 현황·공지·승인 위젯이 이름만 나가 AI 가
        내용을 짐작했다."""
        parts = []
        for oid in out_ids[:4]:
            t = cls._screen_output_text(oid)
            if t:
                parts.append(t)
        fid = opts.get('function_id')
        if fid:
            try:
                row, _k, _c, err = cls._resolve_function_target(fid)
            except Exception:                               # noqa: BLE001
                row, err = None, True
            if row is not None and not err:
                parts.append('%s %s' % ((row.name or '').strip(),
                                        'running' if row.is_activated else 'stopped'))
        gt = w.graph_type or ''
        if opts.get('plot_uuid') and gt == 'AoT_plot':
            try:
                from aot.databases.models import GeoPlot
                p = GeoPlot.query.filter(GeoPlot.unique_id == opts['plot_uuid']).first()
            except Exception:                               # noqa: BLE001
                p = None
            if p is not None:
                import datetime as _dt
                days = (today_at(p) - p.started_on).days if p.started_on else None
                parts.append('%s%s%s' % (p.name or p.subject or 'plot',
                                         ' (%s)' % p.variety if p.variety else '',
                                         ', day %d' % days if days is not None else ''))
        if gt == 'widget_mcp_review':
            try:
                from aot.databases.models.mcp_audit import MCPConfirmation
                import datetime as _dt
                n = MCPConfirmation.query.filter(
                    MCPConfirmation.status == 'pending',
                    MCPConfirmation.expires_at > _tk_naive_utc(_tk_utc_now())).count()
                parts.append('%d pending approval%s' % (n, '' if n == 1 else 's'))
            except Exception:                               # noqa: BLE001
                pass
        if gt == 'widget_notice':
            try:
                from aot.databases.models.notice import NoticePost
                latest = (NoticePost.query.order_by(NoticePost.date_time.desc())
                          .limit(2).all())
                titles = [(n.title or '').strip()[:40] for n in latest if n.title]
                if titles:
                    parts.append('latest: ' + ' | '.join(titles))
            except Exception:                               # noqa: BLE001
                pass
        return parts

    #: 지금 보이는 곳 목록에 싣는 이름의 상한 — 매 get_screen 에 실린다.
    _IN_VIEW_MAX_NAMES = 10

    @classmethod
    def _screen_map_seen(cls, widget, m, cache):
        """한 지도 보고(`m`)의 범위 안 이름과 범위 안 구획 ``[(이름, GeoPlot.color)]`` — 지도마다 한 번."""
        wid = str(m.get('widget_id'))
        if wid not in cache:
            plots = []
            cache[wid] = (cls._screen_map_in_view(widget, m.get('view'), m.get('shapes_hidden'),
                                                  plots_out=plots), plots)
        return cache[wid]

    @classmethod
    def _screen_map_in_view(cls, widget, view, hidden=None, plots_out=None):
        """지도 위젯이 지금 보여 주는 범위 안의 대지·구역·시설·구획 이름.

        화면 JS 가 보고한 범위(view.bounds=[서,남,동,북])와 겹치는 도형의 **이름만**
        싣는다 — 좌표·값은 싣지 않는다. 사용자가 도형 종류를 껐으면(shapes_hidden)
        그 종류는 뺀다: 화면에 안 보이는 것을 "보인다" 고 말하지 않는다.
        시설 구획은 기하가 없어 시설 외피로 판정한다(plot_geometry.geometry_of).
        돌려주는 것은 {'in_view': '3포장(3-1, 3-2) · 1포장', 'zoom': 17.2}; 판정할
        수 없으면 None."""
        import json as _json
        if widget is None or not isinstance(view, dict):
            return None
        try:
            west, south, east, north = [float(v) for v in view.get('bounds')]
            zoom = float(view.get('zoom'))
        except (TypeError, ValueError):
            return None
        try:
            opts = _json.loads(widget.custom_options or '{}')
        except ValueError:
            return None
        map_uuid = opts.get('map_uuid')
        if not map_uuid:
            return None
        from shapely.geometry import box
        from aot.databases.models import GeoFacility, GeoShape
        from aot.space import device_membership as dm
        from aot.space.plot_context import active_plots
        from aot.space.plot_geometry import geometry_of, _shapely
        # 위젯의 도형 토글 이름 → 이 요약의 종류
        off = {{'land': 'site'}.get(k, k) for k in (hidden if isinstance(hidden, list) else []) if isinstance(k, str)}
        frame = box(west, south, east, north)

        def seen(geom):
            poly = _shapely(geom)
            return poly is not None and poly.intersects(frame)

        containers = dm.load_containers(map_uuid)
        sites = [(sh, poly) for sh, kind, poly in containers
                 if kind == 'site' and 'site' not in off]
        zones = [(sh, poly) for sh, kind, poly in containers if kind == 'zone']
        in_view = {}                      # 대지 uuid → [이름]
        order = []

        def bucket(site_shape, label, rank=0):
            key = site_shape.unique_id if site_shape is not None else None
            if key not in in_view:
                in_view[key] = {'site': site_shape, 'children': []}
                order.append(key)
            if label:
                in_view[key]['children'].append((rank, label))

        def site_of(geom):
            return dm.site_for_geometry(map_uuid, geom, containers)

        for sh, poly in sites:
            if poly.intersects(frame):
                bucket(sh, None)
        if 'zone' not in off:
            for sh, poly in zones:
                if poly.intersects(frame):
                    bucket(site_of(dm._feature(sh).get('geometry')), dm.place_label(sh), 0)
        if 'facility' not in off:
            for sh in GeoShape.query.filter(GeoShape.geo_id == map_uuid,
                                            GeoShape.type == 'facility').all():
                geom = (dm._feature(sh).get('geometry') or {})
                if seen(geom):
                    bucket(site_of(geom), dm.place_label(sh), 1)
        if 'plot' not in off:
            facilities = {}
            for p in active_plots(map_uuid):
                geom = geometry_of(p, facilities)
                if geom and seen(geom):
                    bucket(site_of(geom), (p.name or p.subject or '').strip(), 2)
                    if plots_out is not None:       # 구획 색은 GeoPlot.color 가 테마 기본색을 이긴다
                        plots_out.append(((p.name or p.subject or '').strip(), p.color))
        if not order:
            return {'zoom': round(zoom, 1)}
        # 대지는 전부 싣고(어느 곳을 보는지가 먼저다), 남는 이름 몫을 대지마다 나눈다 —
        # 한 대지가 상한을 다 써서 다른 대지가 "…" 로 사라지지 않게. 종류 순서는
        # 구역 → 시설 → 구획, 같은 종류 안에서는 이름순(3-1, 3-2, 3-10).
        import re as _re

        def natural(item):
            rank, label = item
            return (rank, [int(t) if t.isdigit() else t for t in _re.split(r'(\d+)', label)])

        named = sum(1 for k in order if in_view[k]['site'] is not None)
        share = max(2, (cls._IN_VIEW_MAX_NAMES - named) // max(len(order), 1))
        parts = []
        for key in order:
            site = in_view[key]['site']
            head = dm.place_label(site) if site is not None else ''
            kids = []
            for _rank, label in sorted(set(in_view[key]['children']), key=natural):
                if label and label != head and label not in kids:
                    kids.append(label)
            if not head and not kids:
                continue
            shown = kids[:share]
            more = ', …' if len(shown) < len(kids) else ''
            if head:
                parts.append('%s(%s%s)' % (head, ', '.join(shown), more) if shown else head)
            else:
                parts.append(', '.join(shown) + more)
        out = {'zoom': round(zoom, 1)}
        if parts:
            out['in_view'] = ' · '.join(parts)
        return out

    @staticmethod
    def _screen_map_heading(opts):
        """지도 위젯이 띄운 지도와 그 지도의 대지 — "지도 '영양' (대지: 육묘장)".
        위젯 설정의 map_uuid 로 찾는다. 없으면 None(이름을 짐작하지 않는다)."""
        from aot.databases.models import GeoMap
        from aot.space.device_membership import place_label
        mid = (opts or {}).get('map_uuid')
        if not mid:
            return None
        m = GeoMap.query.filter(GeoMap.unique_id == str(mid)).first()
        if m is None:
            return None
        sites = [place_label(s) for s in GeoShape.query.filter(
            GeoShape.type == 'site', GeoShape.geo_id == m.unique_id)
            .order_by(GeoShape.id).limit(6).all()]
        head = "map '%s'" % (m.name or '')
        if sites:
            head += ' (sites: %s%s)' % (', '.join(sites[:5]),
                                        ', …' if len(sites) > 5 else '')
        # 지도 범례의 값(OpenWeather 등)은 브라우저가 화면 중심으로 가져온다 — 서버는 모른다.
        head += ' [legend values: source=map_view_center(client)]'
        return head

    #: screen_action 의 동작. 화면만 바꾸고 아무것도 저장하지 않는다 — 저장은
    #: modify_widget 같은 기존 도구와 승인 게이트가 맡는다.
    _SCREEN_ACTIONS = ('navigate', 'highlight', 'open_widget_settings',
                       'open_map_item', 'open_notes', 'modal_tab', 'map_control',
                       'close_modal', 'close_card', 'post', 'read', 'reload')
    #: map_control 의 동작 → value 가 필요한가. 보기(확대·회전·기울기)는 저장되지
    #: 않고, 라벨·도형·레이어는 패널에서 바꾼 것처럼 남는다(패널이 그렇게 저장한다).
    _MAP_OPS = {'zoom_in': False, 'zoom_out': False, 'zoom': True, 'rotate': True,
                'tilt': True, 'reset_north': False, 'orbit': False,
                'fullscreen': False, 'labels': False, 'shapes': False,
                'base_layer': False, 'overlay': False, 'time': False}
    _MAP_LABEL_KINDS = ('site', 'zone', 'facility', 'plot', 'equipment', 'input',
                        'output', 'function')
    #: 센서는 입력(input) 라벨이다 — 단수 sensor·복수 sensors 모두 같은 input 으로
    #: 보낸다(2026-10-12: 단수만 따로 남아 '성공인데 안 나타남' 이 재현됐다).
    _MAP_LABEL_ALIASES = {'device': 'input', 'devices': 'input', 'sensor': 'input',
                          'sensors': 'input', 'inputs': 'input', 'outputs': 'output',
                          'controller': 'output', 'actuator': 'output'}
    _MAP_SHAPE_KINDS = ('land', 'zone', 'facility', 'plot', 'equipment', 'device',
                        'drawn')
    #: 지도 위젯에서 창을 여는 도형 종류. 설비(equipment)는 여는 창이 없다
    #: (사용자 확인 2026-10-10).
    _MAP_ITEM_KINDS = ('site', 'zone', 'facility', 'plot', 'device')

    @classmethod
    def screen_action(cls, user_id=None, screen=None, action=None, page=None,
                      dashboard=None, widget=None, message=None, item=None,
                      kind=None, tab=None, op=None, value=None, layer=None,
                      center=None, confirm_token=None, title=None, attach=None,
                      card=None, **extra):
        """[화면 조작] 사용자가 보는 AoT 웹 화면 하나를 바꾼다 (화면 연동 P2).

        위치 확인을 **서버가 강제**한다(사용자 2026-10-10): 짐작한 화면에 바로
        실행하지 않는다. 처음 부르면 확인 대기로 두고 confirm_token 을 준다 — AI 가
        사용자에게 기기·화면을 묻고 동의를 받아 token 과 함께 다시 부르거나, 그
        화면의 [허용] 카드를 사람이 누르면 실행된다. 확인된 화면은 일정 시간 다시
        묻지 않는다(web_presence.GRANT_S).

        action='post' 는 화면을 조작하지 않는다 — 키 주인의 AI 수신함에 제목+마크다운
        카드를 남기고, 허용된 화면에 자막으로 보낸다(_screen_post). 화면 해석·확인
        토큰·그랜트를 타지 않는다. 'toast' 는 숨은 별칭이다. post 는 attach={name,
        text|b64|ref|url} 로 이미지·파일(P1·P4)을 함께 남긴다.

        action='read' 도 화면을 조작하지 않는다 — 키 주인의 AI 카드(item=카드 id, 없으면
        목록)를 읽는다(_screen_read). 화면 해석·확인·그랜트·명령 수 제한을 타지 않는다.
        `card` 는 도메인(lite)용 숨은 별칭으로 item 과 같다.

        `user_id` 는 인자가 아니라 인증에서 온다(tool_execution 이 덮어쓴다).
        `ai_key_id`·`ai_link_id` 도 같다(카드의 보낸 쪽 이름이 위조되지 않게).
        """
        from aot.utils import web_presence as wp

        if not user_id:
            return {"status": "error", "error": (
                "This connection is not tied to an AoT user, so there is no "
                "screen to control.")}

        if action in ('post', 'toast'):
            return cls._screen_post(
                user_id, title, message, extra.get('ai_key_id'),
                extra.get('ai_link_id'), attach=attach,
                screen=screen, page=page, dashboard=dashboard, widget=widget,
                item=card or item, kind=kind, tab=tab, op=op, value=value, layer=layer,
                center=center)

        if action == 'read':
            return cls._screen_read(
                user_id, card or item, value,
                screen=screen, page=page, dashboard=dashboard, tab=tab,
                widget=widget, kind=kind, op=op, layer=layer, center=center,
                title=title, message=message, attach=attach)

        # 대화로 받은 동의 — token 만으로 그 명령을 찾는다(인자를 다시 맞출 필요 없게).
        if confirm_token:
            row = wp.confirm_by_token(user_id, str(confirm_token).strip())
            if row is None:
                return {"status": "error", "error": (
                    "Unknown confirm_token. Call screen_action again without it "
                    "to start over.")}
            return cls._screen_confirmed(cls._screen_action_outcome(
                row, link=cls._screen_link(user_id, row.get('browser_key'))))

        if action not in cls._SCREEN_ACTIONS:
            return {"status": "error", "error": (
                "action must be one of: %s." % ", ".join(cls._SCREEN_ACTIONS))}
        screen = (screen or '').strip()
        target = wp.resolve_screen(user_id, screen)
        defaulted = False
        if target is None and not screen:
            # 안전할 때만 생략을 받는다 — 지금 보는 중이고 AI 조작을 켠 화면이 딱
            # 하나일 때. 여럿이면 짐작하지 않는다(위치 확인이 이 도구의 안전장치).
            import time as _time
            now = _time.time()
            live = [r for r in wp.recent(user_id, now=now)
                    if r.get('ai_allowed') and wp.state_of(r, now) == 'viewing']
            if len(live) == 1:
                target, defaulted = live[0], True
        if target is None:
            return {"status": "error", "error": cls._screen_which_error(
                user_id, screen)}
        if not target.get('ai_allowed'):
            return {"status": "error", "error": (
                "AI control is off on %s. The user can turn it on there: AoT "
                "menu Manage > 'AI settings'."
                % (target.get('device') or 'that device'))}
        if wp.recent_command_count(user_id) >= wp.RATE_PER_MIN:
            return {"status": "error", "error": "Too many screen actions in a "
                    "minute. Wait a moment."}

        if action == 'close_card':
            args, problem = cls._screen_close_card_args(user_id, card or item)
        else:
            args, problem = cls._screen_action_args(target, action, page, dashboard,
                                                    widget, message, item, kind, tab,
                                                    op, value, layer, center)
        if problem:
            return {"status": "error", "error": problem}
        ignored = cls._screen_unused(action, item=item, kind=kind, widget=widget,
                                     value=value)

        if action in ('navigate', 'reload'):
            blocked = cls._screen_edit_block(target, action)
            if blocked:
                return blocked

        # 그 기기에서 "AI 화면 조작 허용" 을 켰으면 그것이 허락이다 — [허용] 카드를 한 번 더
        # 묻지 않는다(사용자 결정 2026-10-20; 근거는 `wp.auto_confirmed`). 켜지 않았거나
        # 오래 닫힌 화면은 위에서 이미 걸러졌고, 예전 확인(grant)이 남아 있는 화면도 그대로
        # 통과한다.
        if wp.auto_confirmed(target) or wp.has_grant(target):
            cid, _tok = wp.add_command(user_id, target['browser_key'], action,
                                       args, confirmed=True,
                                       source=wp.EXPLICIT_SOURCE)
            wp.extend_grant(target['browser_key'])
            out = cls._screen_confirmed(
                cls._screen_action_outcome(wp.wait_finished(cid),
                                           link=wp.page_link(target)))
            if out.get('confirmed'):
                out.setdefault("grant_note", (
                    "AI screen control is on for this device, so it ran without "
                    "asking."))
            if ignored:
                out["ignored"] = ignored
            return cls._screen_defaulted(out, defaulted, target)

        cid, token = wp.add_command(user_id, target['browser_key'], action, args,
                                    confirmed=False, source=wp.EXPLICIT_SOURCE)
        where = "%s — %s" % (target.get('device') or 'browser',
                             cls._screen_page_label(target))
        pending = {"ignored": ignored} if ignored else {}
        return cls._screen_defaulted(dict(pending, **{
            "status": "needs_confirmation",
            "confirmed": False,
            "confirm_token": token,
            "screen": where,
            "action": args.get('describe'),
            "ask_user": "Ask the user: do this on %s? (%s)" % (where,
                                                               args.get('describe')),
            "note": ("An [Allow] card is also shown on that screen; if the user "
                     "taps it, it runs without another call. Once the user agrees "
                     "in the conversation, call screen_action with only "
                     "confirm_token. After that, this screen does not need "
                     "confirming again for %d minutes." % int(wp.GRANT_S // 60)),
        }), defaulted, target)

    @classmethod
    def _screen_edit_block(cls, target, action):
        """화면이 방금(20초 안) 설정창(Bootstrap 모달)이 열려 있다고 알렸으면 이동·새로고침을 보내지
        않고 이유를 바로 돌려준다. 화면 JS 는 입력 중에 페이지를 떠나지 않는데(미저장 입력 보호),
        그 거절은 한참 뒤에야 오고 그 사이 응답은 sent/queued 뿐이라 AI 가 이유를 추측했다
        (2026-10-28 점검). 자동으로 닫지는 않는다 — 닫으면 사용자가 쓰던 값이 사라진다."""
        import json as _json
        import time as _time
        if not target.get('client_state') or _time.time() - (target.get('client_at') or 0) > 20:
            return None
        try:
            st = _json.loads(target['client_state'])
        except (TypeError, ValueError):
            return None
        name = str(st.get('dialog') or '') if isinstance(st, dict) else ''
        if not name or name.endswith(' (map)') or name.endswith(' (notes)'):
            return None                    # 보기 창은 막지 않는다 — 화면도 입력 중으로 세지 않는다
        return {"status": "error", "reason_code": "settings_dialog_open",
                "error": ("A settings window ('%s') is open on that screen, so the page was not "
                          "changed: leaving would discard what the user is entering. Ask the user, "
                          "or send action=close_modal first (unsaved values are lost) and then "
                          "%s again." % (name[:60], action))}

    #: 동작마다 쓰지 않는 인자 — 받으면 하되 쓰지 않았다고 응답에 밝힌다. 조용히 버리면
    #: AI 는 "장미원을 열었다" 고 말한다(2026-10-14 사용자 시험: navigate+장미원).
    _SCREEN_UNUSED = {
        'navigate': ('item', 'kind', 'widget', 'value'),
        'close_modal': ('item', 'widget', 'value'),
        'close_card': ('widget', 'value'),
        'reload': ('item', 'widget', 'value'),
        #: post 는 화면을 쓰지 않는다 — 화면을 가리키는 인자는 전부 쓰지 않았다고 알린다.
        'post': ('screen', 'page', 'dashboard', 'tab', 'widget', 'item', 'kind', 'op',
                 'value', 'layer', 'center'),
        #: read 는 카드 id(item)와 범위(value)만 쓴다.
        'read': ('screen', 'page', 'dashboard', 'tab', 'widget', 'kind', 'op', 'layer',
                 'center', 'title', 'message', 'attach'),
    }

    @classmethod
    def _screen_post(cls, user_id, title, message, key_id, link_id, attach=None,
                     **unused):
        """[AI 수신함] 제목+마크다운 메시지(와 이미지·파일·영상 링크 attach)를 키 주인의 수신함에
        남기고, AI 조작을 허용한 화면(보는 중·열림, 최근 순 최대 3)에 자막으로 보낸다.

        화면별 확인(confirm_token)을 타지 않는다 — 사용자 결정 2026-10-19: 출처 표기·
        분당 6/일 100 제한·감사(ai_card.post)로 완화. 수신 판정: AI 허용 화면이 있으면
        저장+전달 / 접속 기록은 있는데 모두 꺼짐이면 거부 / 기록이 없으면 저장만.
        HTML 은 서버에서 바꾸지 않고 원문 저장(표시측이 textContent 로만 그린다).

        attach(P1)는 ai_card_files 가 검사한다: 허용 확장자 10종 + 매직바이트 교차 +
        5 MiB. 파일은 락 밖에서 먼저 쓰고, 저장이 거절되거나 예외가 나면 지운다.
        attach.url(P4)은 서버가 공개 https 주소에서 받아 같은 검사를 지나게 한다(ai_card_fetch,
        SSRF 방어).

        P5: attach 는 객체 한 개 또는 **배열(최대 8)** 이다. 명시 attach 는 전부 아니면 없음 —
        하나라도 실패하면 이미 쓴 파일을 지우고 오류다. 영상 링크(YouTube·Vimeo·직접 mp4/webm/mov)는
        `attach.url` 이나 본문 링크에서 **자동 인식**해 영상 타일로 남기고(서버는 영상 본문을 받지
        않는다 — 포스터·oEmbed 만 고정 호스트에서 받는다), 본문 이미지 링크도 남은 칸만큼(최대 4개)
        첨부로 승격한다. 한 post 의 가져오기는 합계 30초 안(POST_FETCH_BUDGET_S)이다. 화면 명령에는
        카드 id·이름·크기와 영상 URL 만 싣고 사용자 파일 경로는 싣지 않는다(화면이 카드 id 와 첨부
        번호로 같은 출처 API 경로를 만든다).
        """
        import time as _time
        from aot.aot_flask.extensions import db
        from aot.databases.models import MCPExternalAccount, User, UserAPIKey
        from aot.utils import audit, web_presence as wp
        from aot.utils import ai_card_fetch as fetcher
        from aot.utils import ai_card_files as files
        from aot.utils import ai_card_resources as resource_links
        from aot.utils import ai_card_video as video_links
        from aot.utils import ai_screen_cards as cards

        has_attach = attach not in (None, '')
        text = cards.clean_body(message)
        ref = unused.get('item')
        ref = str(ref).strip() if ref not in (None, '') else ''
        if ref and not text.strip() and not has_attach:
            unused.pop('item', None)
            return cls._screen_raise(user_id, ref, unused)
        if not text.strip() and not has_attach:
            return {"status": "error", "error": "message is required."}
        user = User.query.filter(User.unique_id == user_id).first()
        if user is None:
            return {"status": "error", "error": (
                "This connection is not tied to an AoT user, so there is no "
                "inbox to post to.")}

        truncated = len(text) > cards.BODY_MAX
        if truncated:
            text = text[:cards.BODY_MAX]
        head = cards.clean_line(title, cards.TITLE_MAX) or cards.derive_title(text)

        now = _time.time()
        allowed, problem = cls._card_screens(user_id, unused.pop('screen', None), now)
        if problem:
            return {"status": "error", "error": problem}

        # 같은 제목·같은 본문이 방금 올라갔으면 다시 쌓지 않는다(자동 카드가 두 번 오르는 것 방지) —
        # 첨부가 있으면 다른 카드일 수 있어 건너뛴다. 사용자가 일부러 다시 보내려면 제목·본문을 바꾸면 된다.
        if not has_attach and cards.recent_duplicate(user.id, head, text):
            return {"status": "skipped", "note": cls._NOTE_DUPLICATE}

        # ── 명시 attach 해석(네트워크 없음) ──
        plan = []                       # [('file', (name, key, value)) | ('video', Video)]
        if has_attach:
            try:
                parsed = files.parse_attach_list(attach)
            except files.FileError as exc:
                return {"status": "error", "error": str(exc)}
            if len(parsed) > 1 and any(files.item_ext(*it) == 'html' for it in parsed):
                return {"status": "error", "error": "attach: html must be sent alone."}
            for it in parsed:
                name, key, value = it
                vid = video_links.parse_video_url(value) \
                    if key == 'url' and isinstance(value, str) and cls._RECOGNIZE_VIDEO_LINKS \
                    else None
                plan.append(('video', vid) if vid else ('file', it))
            if sum(1 for kind, _x in plan if kind == 'video') > files.VIDEO_MAX:
                return {"status": "error", "error": (
                    "attach: at most %d video links." % files.VIDEO_MAX)}
            b64_chars = sum(len(v) for _n, k, v in parsed if k == 'b64' and isinstance(v, str))
            if b64_chars > (-(-files.CARD_MAX_BYTES // 3) * 4 + 64 * len(parsed)):
                return {"status": "error", "error": cls._CARD_TOTAL_MSG}
        n_files = sum(1 for kind, _x in plan if kind == 'file')

        problem = cards.check_rate(user.id, files=n_files or None)
        if problem is None and allowed and \
                wp.recent_command_count(user_id) >= wp.RATE_PER_MIN:
            problem = "Too many screen actions in a minute. Wait a moment."
        if problem:
            return {"status": "error", "error": problem}

        # 가져오기 시도는 시작 때 잰 남은 횟수(시간 30·일 100 중 작은 쪽) 안에서만 한다 — 성공한
        # 시도는 카드가 생긴 뒤에야 감사 행이 되므로, 한 post 가 상한을 넘기지 못하게 미리 묶는다.
        budget = cls._FetchBudget(files.POST_FETCH_BUDGET_S, fetcher.attempts_left(user.id))
        poster_skipped = False
        video_over = 0
        items, attempts = [], []        # attempts = [(fetcher.Attempt, 바이트)] — 항목마다 감사 1행
        total = 0
        note_failed = 0

        def finish_all(code, card_uuid=None):
            for att, size in attempts:
                att.finish(code, size, card_uuid)

        stored = []                     # 이 요청이 디스크에 쓴 상대경로(실패 시 지운다)
        try:
            try:
                if plan:
                    files.check_disk()
                for idx, (kind, payload) in enumerate(plan):
                    if kind == 'video':
                        items.append(cls._video_item(payload))
                        continue
                    name, key, value = payload
                    if key == 'url':
                        if budget.over():
                            raise files.FileError(cls._FETCH_BUDGET_MSG)
                        if not budget.take():
                            raise files.FileError(fetcher.limit_problem(user.id) or fetcher.MSG_HOUR)
                    try:
                        prepared = files.prepare(dict({key: value}, **(
                            {'name': name} if name else {})), user, user.id)
                    except files.FileError as exc:
                        if len(plan) > 1:      # 어느 원소가 틀렸는지 번호를 붙인다
                            raise files.FileError("attach[%d]: %s" % (idx, exc)) from None
                        raise
                    if prepared.get('fetch'):
                        attempts.append((prepared['fetch'], len(prepared['data'])))
                    total += len(prepared['data'])
                    if total > files.CARD_MAX_BYTES:
                        raise files.FileError(cls._CARD_TOTAL_MSG)
                    items.append(dict(prepared, kind=prepared['kind']))
                if len(items) > 1 and any(i['kind'] == 'artifact' for i in items):
                    raise files.FileError("attach: html must be sent alone.")
            except files.FileError as exc:
                finish_all('store')
                return {"status": "error", "error": str(exc)}

            # ── 본문 미디어(이미지 승격·영상 링크 인식) — 남은 칸만큼 ──
            if len(items) < files.CARD_MAX_ATTACH and \
                    not any(i['kind'] == 'artifact' for i in items):
                got, failed, total, over_videos = cls._promote_body_media(
                    files, fetcher, video_links, cards, user, text, items, plan, attempts,
                    budget, total)
                note_failed += failed
                video_over = over_videos

            # ── 영상 포스터(순서대로, 예산 안에서) ──
            def poster_gate():
                nonlocal poster_skipped
                if budget.over() or not budget.take():
                    poster_skipped = True
                    return False
                return True
            for it in items:
                if it['kind'] != 'video':
                    continue
                poster = video_links.fetch_poster(it['video'], user, poster_gate)
                attempts.extend(poster.attempts)
                it['poster'] = poster.jpeg
                if poster.title and not it.get('labeled') and it['video'].provider in ('vimeo', 'web'):
                    it['name'] = poster.title
                # 뷰어 안 재생 가능 여부는 여기서 한 번만 판정해 저장한다(목록은 DNS 를 하지 않는다).
                it['playable'] = video_links.judge_playable(it['video'], user, budget.over)

            # 웹페이지 링크는 이미지를 받은 것만 타일이 된다 — 못 받은 것은 링크로 남기고 가져오기 감사만 남긴다.
            items[:] = [i for i in items
                        if not (i['kind'] == 'video' and i['video'].provider == 'web'
                                and not i.get('poster'))]
            head = head or (cards.clean_line(items[0]['name'], cards.TITLE_MAX)
                            if items else '')

            source, source_key = 'AI', None
            if key_id:
                key = UserAPIKey.query.filter(UserAPIKey.unique_id == str(key_id),
                                              UserAPIKey.user_id == user.id).first()
                if key is not None:
                    source, source_key = (key.name or 'AI').strip() or 'AI', key.unique_id
            elif link_id:
                link = MCPExternalAccount.query.filter(
                    MCPExternalAccount.id == link_id,
                    MCPExternalAccount.user_id == user.id).first()
                if link is not None:
                    source = (link.label or 'AI').strip() or 'AI'
            source = cards.clean_line(source, cards.SOURCE_MAX) or 'AI'

            att_rows = []
            stamp = cards._now()
            try:
                for it in items:
                    if it['kind'] == 'video':
                        v = it['video']
                        poster_rel = None
                        if it.get('poster'):
                            poster_rel = files.store_poster(it['poster'], stamp)
                            stored.append(poster_rel)
                        att_rows.append({
                            'kind': 'video', 'path': None, 'thumb': poster_rel,
                            'name': it['name'], 'mime': None,
                            'size': len(it['poster']) if it.get('poster') else 0,
                            'url': v.url, 'provider': v.provider, 'host': v.host,
                            'playable': bool(it.get('playable'))})
                    elif it['kind'] == 'viz':
                        # viz 는 파일이 없다(video 처럼) — 정규화된 스펙만 spec 칸에 담는다.
                        att_rows.append({
                            'kind': 'viz', 'path': None, 'thumb': None,
                            'name': it['name'], 'mime': 'application/json',
                            'size': len(it['data']),
                            'spec': it['data'].decode('utf-8')})
                    else:
                        rel = files.store(it['ext'], it['data'], it['thumb'], stamp)
                        stored.append(rel)
                        att_rows.append({
                            'kind': it['kind'], 'path': rel,
                            'thumb': files.thumb_rel(rel) if it['thumb'] else None,
                            'name': it['name'], 'mime': it['mime'], 'size': len(it['data'])})
            except OSError:
                logger.exception('[ai_card] 파일 저장 실패')
                files.remove_files(stored)
                finish_all('store')
                return {"status": "error", "error": "The file could not be stored."}
            try:
                card, problem = cards.create_limited(user.id, head, text, source, source_key,
                                                     attachments=att_rows)
            except BaseException:
                files.remove_files(stored)
                finish_all('store')
                raise
            if card is None:   # 검사 뒤 저장 사이에 다른 요청이 한도를 채운 경우(경쟁)
                files.remove_files(stored)
                finish_all('store')
                return {"status": "error", "error": problem}
            finish_all('ok', card.unique_id)    # 가져오기 감사: 항목마다 정확히 한 행
        finally:        # 어디서 끝나든 가져오기 감사는 정확히 한 행(성공은 위에서 이미 남김)
            finish_all('store')

        atts = cards.attachments(card)
        targets = cls._send_card(user_id, card, atts, allowed, now)

        detail = "%s (%d chars) → %d screens" % (head[:80], len(text), len(targets))
        fl = cards.file_atts(atts)
        vids = [a for a in atts if a.kind == 'video']
        if fl:
            detail += " + %d file%s (%s)" % (len(fl), '' if len(fl) == 1 else 's',
                                             files.human_size(sum(a.size or 0 for a in fl)))
        if vids:
            detail += "%s %d video%s (%s)" % (
                ',' if fl else ' +', len(vids), '' if len(vids) == 1 else 's',
                '/'.join(sorted({a.provider or 'video' for a in vids})))
        audit.audit_log(
            audit.AI_CARD_POST, target_type='AICard', target_id=card.unique_id,
            target_name=source, detail=detail, user_id=user.id, username=user.name)

        out = {"status": "posted", "card": card.unique_id[:8],
               "shown_on": [r.get('device') or 'Browser' for r in targets],
               "truncated": truncated}
        # MCP resource_link(P2) — 숨은 키. 실행층(_finish_result)이 꺼내 표준 MCP 전송이고
        # 협상한 버전이 ≥2025-06-18 일 때만 블록으로 붙이고, 아니면 버린다(JSON 에 안 나간다).
        out["_resource_links"] = resource_links.link_blocks(card)
        if len(atts) == 1 and atts[0].kind != 'video':
            out["file"] = {"name": atts[0].name, "size": atts[0].size or 0,
                           "kind": atts[0].kind}
        elif atts:
            out["files"] = [
                {"name": a.name, "kind": cls._card_media_kind(a), "provider": a.provider}
                if a.kind == 'video' else
                {"name": a.name, "size": a.size or 0, "kind": a.kind} for a in atts]
        if note_failed:
            out["note_image"] = cls._NOTE_IMAGE if note_failed == 1 else \
                cls._NOTE_IMAGES % note_failed
        if video_over:
            out["note_links"] = cls._NOTE_VIDEO_OVER % video_over
        if poster_skipped:
            out["note_video"] = cls._NOTE_VIDEO
        if not targets:
            out["note"] = ("Saved to the user's AoT AI inbox; shown when they open "
                           "AoT with AI control on.")
        ignored = cls._screen_unused('post', **unused)
        if ignored:
            out["ignored"] = ignored
        return out

    @classmethod
    def _card_screens(cls, user_id, picked, now):
        """카드를 띄울 화면 → (화면 목록, 문제 문장). 카드는 지정한 화면에만 띄운다. 지정이 없고
        화면이 둘 이상이면 모두에 뿌리지 않고 아무것도 저장하기 전에 화면 목록과 함께 돌려보낸다.
        접속 기록이 없으면 ([], None) — 저장만 한다."""
        from aot.utils import web_presence as wp
        rows = wp.recent(user_id, now=now)
        allowed = [r for r in rows if r.get('ai_allowed')]
        picked = (picked or '').strip()
        if picked:
            one = wp.resolve_screen(user_id, picked, now=now)
            if one is None or not one.get('ai_allowed'):
                return None, cls._screen_which_error(user_id, picked, post=True)
            allowed = [one]
        else:
            live = [r for r in allowed if wp.state_of(r, now) in ('viewing', 'open')]
            if len(live) > 1:
                # 읽기 경로(screen_follow.resolve)와 같게 — 지금 **보는 중** 화면이 정확히
                # 하나면, 배경에 '열림' 화면이 더 있어도 그 화면으로 올린다(사용자가 눈으로
                # 보고 있는 곳). 그래야 여러 기기·탭을 켜 둔 흔한 상황에서도 값 조회 카드가
                # 조용히 사라지지 않는다. 보는 중이 0개거나 2개 이상일 때만 되묻는다.
                viewing = [r for r in live if wp.state_of(r, now) == 'viewing']
                if len(viewing) == 1:
                    allowed = [viewing[0]]
                else:
                    return None, cls._screen_which_error(user_id, '', post=True)
        if rows and not allowed:
            return None, ("AI control is off on all of the user's screens. They can turn it "
                          "on: AoT menu Manage > 'AI settings'.")
        return allowed, None

    @classmethod
    def _send_card(cls, user_id, card, atts, allowed, now, raised=False):
        """저장된 카드 한 장을 허용된 화면(보는 중·열림, 최대 3)에 자막으로 보낸다. 보낸 화면 목록."""
        from aot.utils import web_presence as wp
        from aot.utils import ai_screen_cards as cards
        targets = [r for r in allowed if wp.state_of(r, now) in ('viewing', 'open')][:3]
        args = {'card': card.unique_id, 'title': card.title or '', 'message': card.body or '',
                'source': card.source_label or 'AI', 'at': cards.iso_z(card.created_at),
                'kind': card.kind or 'text', 'describe': "show an AI card"}
        if raised:
            args['raised'] = True       # 화면은 이미 받은 카드라도 다시 띄우고 미읽음 수를 올리지 않는다
        if atts:
            args['file'] = cards.file_info(card, atts)
            args['files'] = cards.file_items(atts)
        for r in targets:
            # 같은 호출이 화면을 다른 대시보드로 옮기는 중이면(날씨·예보 조회가 지도를 옮긴다) 카드는 그 대시보드에
            # 도착한 뒤에 내보낸다 — 이동이 페이지를 다시 읽으므로 같이 보내면 카드가 떴다가 곧 사라진다(2026-10-30).
            wp.add_command(user_id, r['browser_key'], 'ai_card', args,
                           confirmed=True,
                           hold_for=wp.pending_dashboard(r['browser_key'], include_queued=True))
        return targets

    @classmethod
    def _screen_raise(cls, user_id, ref, unused):
        """[AI 카드 다시 띄우기] 예전에 만든 카드(id 앞 8자 이상)를 수신함 맨 위로 끌어올리고 허용된
        화면에 자막으로 다시 보낸다(P7-11). 새 카드를 만들지 않으므로 카드 수 제한(분당·일)은 타지
        않고 화면 명령 제한만 탄다. 사용자가 닫은 카드도 되살린다(찾아 달라고 한 카드다)."""
        import time as _time
        from aot.databases.models import User
        from aot.utils import audit, web_presence as wp
        from aot.utils import ai_screen_cards as cards

        user = User.query.filter(User.unique_id == user_id).first()
        if user is None:
            return {"status": "error", "error": (
                "This connection is not tied to an AoT user, so there is no "
                "inbox to post to.")}
        card, why = cards.find_card(user.id, ref)
        if card is None:
            shown = cards.clean_line(ref, 40)
            if why == 'ambiguous':
                return {"status": "error", "error": (
                    "AI card id '%s' is ambiguous. Use more characters." % shown)}
            return {"status": "error", "error": (
                "No AI card '%s' for this user. read with card=<words> finds one." % shown)}
        now = _time.time()
        allowed, problem = cls._card_screens(user_id, unused.pop('screen', None), now)
        if problem is None and allowed and \
                wp.recent_command_count(user_id) >= wp.RATE_PER_MIN:
            problem = "Too many screen actions in a minute. Wait a moment."
        if problem:
            return {"status": "error", "error": problem}
        card = cards.raise_card(user.id, card.unique_id, reopen=True)
        if card is None:            # 그 사이 만료·삭제
            return {"status": "error", "error": "No AI card '%s' for this user." % ref[:40]}
        targets = cls._send_card(user_id, card, cards.attachments(card), allowed, now, raised=True)
        audit.audit_log(
            audit.AI_CARD_POST, target_type='AICard', target_id=card.unique_id,
            target_name=card.source_label or 'AI',
            detail="raise: %s → %d screens" % ((card.title or '')[:80], len(targets)),
            user_id=user.id, username=user.name)
        out = {"status": "raised", "card": card.unique_id[:8], "title": card.title or '',
               "shown_on": [r.get('device') or 'Browser' for r in targets]}
        if not targets:
            out["note"] = ("Moved to the top of the user's AoT AI inbox; shown when they open "
                           "AoT with AI control on.")
        ignored = cls._screen_unused('post', **unused)
        if ignored:
            out["ignored"] = ignored
        return out

    #: 본문 이미지를 첨부로 올리지 못했을 때 AI 에게 알리는 한 줄(응답 토큰이고 설명 토큰이 아니다).
    _NOTE_DUPLICATE = "The same card was just posted; not posted again."
    _NOTE_IMAGE = "The image link was not attached; it stays a link."
    _NOTE_IMAGES = "%d image links were not attached; they stay links."
    _NOTE_VIDEO = "Some video thumbnails were not fetched (URL fetch limit or time); the links stay."
    _NOTE_VIDEO_OVER = "%d video links were not attached (a card shows 4 videos); they stay links. Post them on another card."
    _CARD_TOTAL_MSG = "attach total is larger than 20 MB."
    _FETCH_BUDGET_MSG = "Fetching the attachments took too long. Send fewer links."

    #: 본문 마크다운 이미지(`![](https://…)`·`[글](….jpg)`·맨 주소)를 서버가 받아 첨부로 승격한다(사용자
    #: 결정 2026-10-20 — 링크로 준 이미지도 섬네일·뷰어로 본다). P5: 최대 4개, 카드 8칸·일 20개 안에서.
    #: 서버가 AI 가 준 주소를 GET 하는 통로는 명시적 attach.url 과 같은 SSRF 방어·한도(시간 30·일 100
    #: 시도)를 거친다(plans/p4_security_20261020.md D1: 새 통로가 아니라 같은 통로를 쓰기 쉽게 한 것).
    _PROMOTE_MD_IMAGES = True
    #: 본문·attach.url 의 영상 링크(YouTube·Vimeo·mp4/webm/mov)를 영상 타일로 인식한다. 서버 요청은
    #: 포스터·oEmbed 뿐이고(고정 호스트), 직접 영상 링크는 요청 0 이다. iframe 임베드는 없다.
    _RECOGNIZE_VIDEO_LINKS = True
    #: 일반 웹페이지 링크의 og:image 타일(2026-10-22). 이미지를 못 받으면 타일 없이 링크로 남는다.
    _PREVIEW_WEB_LINKS = True

    class _FetchBudget:
        """한 post 의 가져오기 시간 예산(POST_FETCH_BUDGET_S) — 시작 시각만 든다."""

        def __init__(self, seconds, attempts=10 ** 6):
            import time as _time
            self._end = _time.monotonic() + seconds
            self._attempts = attempts

        def take(self):
            """가져오기 시도 한 번을 예약한다. 남은 횟수가 없으면 False(시도하지 않는다)."""
            if self._attempts <= 0:
                return False
            self._attempts -= 1
            return True

        def over(self):
            import time as _time
            return _time.monotonic() >= self._end

    @staticmethod
    def _video_item(video):
        """영상 링크 하나의 저장 준비물(포스터는 아직 없다)."""
        return {'kind': 'video', 'video': video, 'name': video.name, 'poster': None}

    @staticmethod
    def _card_media_kind(att):
        """응답에 내보내는 종류: 웹페이지 링크 타일은 저장만 'video' 행이다 — AI 에게는 'link' 로 말한다."""
        return 'link' if att.provider == 'web' else 'video'

    @classmethod
    def _promote_body_media(cls, files, fetcher, video_links, cards, user, text, items,
                            plan, attempts, budget, total):
        """본문의 이미지·영상 링크를 남은 칸만큼 items 에 더한다 → (더한 수, 실패한 이미지 수, 총 바이트, 한도 밖 영상 수).

        등장 순서대로 한 번씩만 시도한다(실패해도 다른 후보로 채우지 않는다 — 시간 30·일 100 시도
        상한이 그대로여야 D1 유출 대역이 늘지 않는다). 이미지는 일 20개 잔여·가져오기 예산·디스크·
        URL 한도를 모두 통과해야 시도하고, 이미지가 아닌 응답은 버린다(시도는 감사에 남는다).
        명시 attach 와 같은 주소는 건너뛴다. 실패 사유는 알리지 않는다."""
        slots = files.CARD_MAX_ATTACH - len(items)
        n_video = sum(1 for i in items if i['kind'] == 'video' and i['video'].provider != 'web')
        n_web = sum(1 for i in items if i['kind'] == 'video' and i['video'].provider == 'web')
        explicit = set()
        for kind, payload in plan:
            if kind == 'video':
                explicit.update((payload.url,))
            elif payload[1] == 'url' and isinstance(payload[2], str):
                explicit.add(payload[2])
        for it in items:
            if it['kind'] == 'video':
                explicit.add(it['video'].url)
        img_cap = min(files.PROMOTE_MAX, slots) if cls._PROMOTE_MD_IMAGES else 0
        vid_cap = min(files.VIDEO_MAX - n_video, slots) if cls._RECOGNIZE_VIDEO_LINKS else 0
        web_cap = min(video_links.WEB_MAX - n_web, slots) if cls._PREVIEW_WEB_LINKS else 0
        # 한도(영상 4)를 넘어 첨부되지 못한 영상 링크 수 — 조용히 빠지면 AI 는 5개 다 올렸다고 말한다(10-28 점검).
        n_found = len([1 for _p, k, _u in video_links.find_body_media(text, 0, 99, explicit, 0)
                       if k == 'video']) if cls._RECOGNIZE_VIDEO_LINKS else 0
        if img_cap <= 0 and vid_cap <= 0 and web_cap <= 0:
            return 0, 0, total, n_found
        added = failed = got_video = 0
        left_today = max(0, cards.files_left_today(user.id)
                         - sum(1 for i in items if i['kind'] in cards.FILE_KINDS))
        for pos, kind, url in video_links.find_body_media(text, img_cap, vid_cap, explicit, web_cap):
            if len(items) >= files.CARD_MAX_ATTACH:
                break
            if kind in ('video', 'link'):
                # 웹페이지는 포스터를 받은 것만 타일로 남는다(아래 포스터 단계). 제목은 본문의 링크 설명이 먼저.
                parsed = video_links.parse_video_url(url) if kind == 'video' \
                    else video_links.parse_web_url(url)
                item = cls._video_item(parsed)
                label = video_links.label_near(text, pos, url)
                if label:
                    item['name'], item['labeled'] = label, True
                items.append(item)
                added += 1
                got_video += kind == 'video'
                continue
            if left_today <= 0 or budget.over() or not budget.take():
                failed += 1
                continue
            try:
                files.check_disk()
                prepared = files.prepare({'url': url}, user, user.id)
            except files.FileError:
                failed += 1
                continue
            size = len(prepared['data'])
            if prepared.get('fetch'):
                attempts.append((prepared['fetch'], size))
            if prepared['kind'] != 'image':
                if prepared.get('fetch'):
                    prepared['fetch'].finish('mismatch', size)
                failed += 1
                continue
            if total + size > files.CARD_MAX_BYTES:
                if prepared.get('fetch'):          # 받았지만 붙이지 않았다 — 감사에 ok 로 남기지 않는다
                    prepared['fetch'].finish('store', size)
                failed += 1
                continue
            total += size
            left_today -= 1
            items.append(dict(prepared, kind='image'))
            added += 1
        return added, failed, total, max(0, n_found - got_video)

    @classmethod
    def _screen_read(cls, user_id, item, value, **unused):
        """[AI 카드 읽기] 키 주인의 AI 수신함을 읽는다. 화면·확인·그랜트·명령 수 제한을
        타지 않고(화면 허용과 무관), 읽음 상태는 바꾸지 않는다(사람의 상태).

        item 없음 → 보이는 최신 10장 목록. item 있음 → unique_id 앞 8자 이상으로 키
        주인의 카드(닫힘 포함·만료 제외) 한 장의 글(본문 + 텍스트 파일 본문)을 value
        범위('0-2000')만큼, 한 번에 최대 4,000자. 이미지·PDF 는 본문만 준다.
        """
        from aot.databases.models import User
        from aot.utils import ai_screen_cards as cards

        user = User.query.filter(User.unique_id == user_id).first()
        if user is None:
            return {"status": "error", "error": (
                "This connection is not tied to an AoT user, so there is no "
                "inbox to read.")}
        ignored = cls._screen_unused('read', **unused)
        ref = str(item).strip() if item not in (None, '') else ''
        if not ref or not cards.looks_like_card_id(ref):
            # 카드 id 가 아닌 글은 찾기다("지난번에 만든 ○○ 찾아줘") — 제목·본문·파일 이름에 그 글이 든 카드 목록.
            query = cards.clean_line(ref, cards.SEARCH_MAX) if ref else ''
            listed, more = cards.read_list(user.id, q=query or None)
            out = {"status": "ok", "cards": listed, "more": more}
            if query:
                out["query"] = query
            if ignored:
                out["ignored"] = ignored
            return out

        card, why = cards.find_card(user.id, ref)
        if card is None:
            shown = cards.clean_line(ref, 40)
            if why == 'ambiguous':
                return {"status": "error", "error": (
                    "AI card id '%s' is ambiguous. Use more characters." % shown)}
            return {"status": "error", "error": "No AI card '%s' for this user." % shown}
        span = cards.parse_range(value)
        if span is None:
            return {"status": "error", "error": "value must be a range like 0-2000."}
        start, end = span
        atts = cards.attachments(card)
        text, total, stop, clipped = cards.card_text(card, start, end, atts=atts)
        # 카드 글·파일 본문은 다른 AI 연결이나 노트 첨부에서 온 것일 수 있다 — 누가 썼는지
        # (source)와 "지시가 아니라 자료"라는 표식을 글보다 앞에 싣는다(P1 보안 리뷰 M3).
        out = {"status": "ok", "card": card.unique_id[:8], "title": card.title or '',
               "kind": card.kind or 'text', "source": card.source_label or 'AI',
               "caution": cards.READ_CAUTION}
        if len(atts) == 1 and atts[0].kind != 'video':
            info = cards.att_info(atts[0])
            out["file"] = {"name": info['name'], "size": info['size'],
                           "type": info['mime']}
        elif atts:         # 첨부 2개 이상(또는 영상 하나) — 번호 i 는 resources 의 /file/<i> 와 같다
            out["files"] = [
                {"i": a.position, "kind": cls._card_media_kind(a), "provider": a.provider or '',
                 "url": a.url or ''} if a.kind == 'video' else
                {"i": a.position, "name": a.name or '', "size": a.size or 0,
                 "type": a.mime or ''} for a in atts]
        out["range"] = "%d-%d" % (start, stop)
        out["total"] = total
        out["text"] = text
        if clipped:
            out["clipped"] = True
        if stop < total:
            out["next"] = "%d-%d" % (stop, stop + min(end - start, cards.READ_MAX))
        fl = cards.file_atts(atts)
        if fl and not any(cards.att_text(a) is not None for a in fl):
            out["note"] = "File content is not readable as text here."
        if ignored:
            out["ignored"] = ignored
        return out

    @classmethod
    def _screen_unused(cls, action, **given):
        names = [k for k in cls._SCREEN_UNUSED.get(action, ())
                 if given.get(k) not in (None, '')]
        if not names:
            return None
        hint = (" To show a place or plot, call open_map_item with it once the page "
                "is open." if action == 'navigate' and 'item' in names else "")
        return {"args": names,
                "note": "%s does not use %s — it was not applied.%s" % (
                    action, ", ".join(names), hint)}

    @classmethod
    def _screen_which_error(cls, user_id, screen, post=False):
        """screen 을 못 정했을 때의 오류 — 고를 수 있는 화면(후보)을 함께 준다.
        후보가 없으면 get_screen 으로 알아내라고만 한다.

        post=True(카드 올리기): 카드는 AI 조작이 **켜진** 화면에만 오른다 — 꺼진 화면을 후보로 주면 모델이 그
        화면을 골라 다시 실패한다(2026-11-07 실측: screen_action post 59건 실패, 대부분 화면 미지정 뒤 재호출).
        그래서 켜진 화면만 최근 순으로 싣고(첫째 = 가장 최근에 쓴 화면), 같은 호출을 `screen` 만 더해 다시 부르라고
        말한다. 사용자에게 먼저 되묻도록 시키지 않는다 — 어느 쪽이든 카드는 수신함에 남는다."""
        import time as _time
        from aot.utils import web_presence as wp
        now = _time.time()
        rows = wp.recent(user_id, now=now)
        if post:
            rows = [r for r in rows if r.get('ai_allowed')]
        cands = ["%s = %s, %s, %s, ai_control %s" % (
            r['browser_key'][:12], r.get('device') or 'Browser',
            cls._screen_page_label(r), wp.state_of(r, now),
            'on' if r.get('ai_allowed') else 'off') for r in rows[:8]]
        if post and cands:
            head = ("Unknown screen, or AI control is off on it ('%s'). The card was not posted." % screen[:40]) \
                if screen else "Which screen should show the card? Several are open, so it was not posted."
            return (head + " Repeat the same call with `screen` set to one of (most recent first): "
                    + "; ".join(cands) + ".")
        head = ("Unknown screen '%s'." % screen[:40]) if screen else \
            "Which screen? Several are open, so none was assumed."
        if not cands:
            return (head + " The user has no AoT page open. Call get_screen, tell "
                    "the user which device and page you mean, and pass that "
                    "screen's `screen` value.")
        return (head + " Pass `screen` as one of: " + "; ".join(cands)
                + ". Tell the user which device and page you mean first.")

    @staticmethod
    def _screen_confirmed(out):
        """이 화면이 확인된 상태로 실행됐음을 알린다 — 동작은 의도다: 한 번 확인된
        화면(사용자가 [허용] 을 누르거나 대화로 동의)은 쓸 때마다 GRANT_S 로 연장돼
        그동안 확인 없이 바로 실행된다. 설명과 동작이 어긋나 보였다(2026-10-11)."""
        from aot.utils import web_presence as wp
        if isinstance(out, dict) and out.get('status') not in (
                'error', 'needs_confirmation', 'rejected', 'expired'):
            out["confirmed"] = True
            out["grant_left_s"] = int(wp.GRANT_S)    # 쓸 때마다 다시 채워진다
        return out

    @staticmethod
    def _screen_defaulted(out, defaulted, target):
        """screen 을 생략해 서버가 고른 경우 어느 화면이었는지 알린다."""
        if defaulted and isinstance(out, dict):
            out["screen_defaulted"] = "%s (%s)" % (
                target.get('device') or 'Browser', target['browser_key'][:12])
        return out

    @classmethod
    def _screen_page_label(cls, row):
        from aot.utils import web_presence as wp
        kind = row.get('page_kind')
        if kind == 'dashboard' and row.get('page_ref'):
            from aot.databases.models import Dashboard
            d = Dashboard.query.filter(Dashboard.unique_id == row['page_ref']).first()
            if d:
                return "dashboard '%s'" % d.name
        if kind in wp.TAB_PAGE_TYPES:
            tabs = cls._screen_tab_list(row.get('user_id'), kind)
            # 주소에 tab_id 가 없으면 그 사람에게 보이는 첫 탭이 열린다(라우트와 같다).
            ref = row.get('page_ref') or (tabs[0][0] if tabs else None)
            name = next((label for tid, label in tabs if tid == ref), None)
            if name:
                return "%s tab '%s'" % (kind, name)
        return kind or 'unknown page'

    @classmethod
    def _screen_tab_list(cls, user_id, page_kind):
        """페이지의 탭 [(id, 이름)] — 그 사람에게 보이는 것만, 화면 순서대로.

        같은 이름이 둘 이상이면 '영양 #1', '영양 #2' 처럼 순서를 붙인다(실제로
        입력 페이지에 '영양' 탭이 둘 있다). 대시보드는 대시보드 행이 곧 탭이다.
        """
        from collections import Counter
        from aot.utils import web_presence as wp
        if page_kind == 'dashboard':
            from sqlalchemy import text
            from aot.databases.models import Dashboard
            rows = [(d.unique_id, (d.name or '').strip()) for d in
                    Dashboard.query.order_by(text("COALESCE(sort_order, 999999), id")).all()]
        elif page_kind in wp.TAB_PAGE_TYPES:
            from aot.databases.models import User
            from aot.services.tab_service import TabService
            # 화면과 같은 판정(visible_tabs_for_page)을 **키 주인**으로 — 여기는
            # 요청 사용자가 없는 실행층이라 사람을 직접 넘긴다.
            user = User.query.filter(User.unique_id == user_id).first() \
                if user_id else None
            tabs = TabService.visible_tabs_for_page(wp.TAB_PAGE_TYPES[page_kind],
                                                    user=user)
            rows = [(t.unique_id, (t.name or '').strip()) for t in tabs]
        else:
            return []
        counts = Counter(name for _tid, name in rows)
        seen = Counter()
        out = []
        for tid, name in rows:
            if counts[name] > 1:
                seen[name] += 1
                name = '%s #%d' % (name, seen[name])
            out.append((tid, name))
        return out

    @classmethod
    def _screen_nav_candidates(cls, user_id, page):
        """navigate 오류에 붙일 후보 — 대시보드 이름 또는 그 페이지의 탭 이름."""
        names = [label for _tid, label in cls._screen_tab_list(user_id, page)[:20]]
        if not names:
            return ""
        return " %s: %s." % ("Dashboards" if page == 'dashboard' else "Tabs",
                             ", ".join("'%s'" % n for n in names))

    @classmethod
    def _screen_find_tab(cls, tabs, ref):
        """탭 목록에서 id·이름('영양 #2' 포함)으로 하나 → ((id, 이름), 문제 문장)."""
        ref = (ref or '').strip()
        for tid, label in tabs:
            if ref in (tid, label):
                return (tid, label), None
        hits = [(tid, label) for tid, label in tabs
                if label.split(' #')[0] == ref]
        if len(hits) > 1:
            return None, ("'%s' names %d tabs: %s. Pass one of these." % (
                ref, len(hits), ", ".join("'%s'" % h[1] for h in hits)))
        if hits:
            return hits[0], None
        return None, ("No tab named '%s'. Tabs here: %s." % (
            ref, ", ".join("'%s'" % label for _tid, label in tabs[:20]) or 'none'))

    @classmethod
    def _screen_close_card_args(cls, user_id, ref):
        """close_card — 카드 id(앞 8자 이상)를 내 카드의 전체 id 로 풀어 보낸다. 없으면 떠 있는 카드 전부."""
        ref = str(ref).strip() if ref not in (None, '') else ''
        if not ref:
            return {'card': '', 'describe': "close the AI cards on screen"}, None
        from aot.databases.models import User
        from aot.utils import ai_screen_cards as cards
        user = User.query.filter(User.unique_id == user_id).first()
        card, why = cards.find_card(user.id, ref) if user else (None, None)
        if card is None:
            shown = cards.clean_line(ref, 40)
            if why == 'ambiguous':
                return None, "AI card id '%s' is ambiguous. Use more characters." % shown
            return None, "No AI card '%s' for this user." % shown
        return {'card': card.unique_id, 'describe': "close the AI card on screen"}, None

    @classmethod
    def _screen_action_args(cls, target, action, page, dashboard, widget, message,
                            item=None, kind=None, tab=None, op=None, value=None,
                            layer=None, center=None):
        """동작별 인자 검사 → (화면 JS 에 넘길 args, 문제 문장)."""
        from aot.utils import web_presence as wp
        from aot.databases.models import Dashboard, Widget

        def find_dashboard(ref):
            if not ref:
                return None
            q = Dashboard.query
            return (q.filter(Dashboard.unique_id == ref).first()
                    or q.filter(Dashboard.name == ref).first())

        if action == 'navigate':
            tab = (tab or '').strip() or None
            page = (page or '').strip()
            here_kind = target.get('page_kind')
            if not page:
                if dashboard:
                    page = 'dashboard'
                elif tab and (here_kind == 'dashboard' or here_kind in wp.TAB_PAGE_TYPES):
                    page = here_kind      # "영양 탭으로" — 지금 보는 페이지의 탭
            if page not in wp.NAVIGABLE:
                return None, ("page must be one of: %s."
                              % ", ".join(sorted(wp.NAVIGABLE)))
            url = wp.NAVIGABLE[page]
            describe = "open the %s page" % page
            label = None
            uid = target.get('user_id')
            if dashboard and page != 'dashboard':
                return None, ("`dashboard` goes with page='dashboard' (e.g. page="
                              "'dashboard', dashboard='%s'). A tab inside the %s "
                              "page is `tab`: page='%s', tab=<tab name>.%s" % (
                                  dashboard, page, page,
                                  cls._screen_nav_candidates(uid, page)))
            ref = (dashboard or tab) if page == 'dashboard' else tab
            if page == 'dashboard' and not ref:
                return None, ("Which dashboard? A dashboard is opened with page="
                              "'dashboard' plus dashboard=<name>.%s"
                              % cls._screen_nav_candidates(uid, 'dashboard'))
            if ref:
                if page != 'dashboard' and page not in wp.TAB_PAGE_TYPES:
                    return None, ("The %s page has no tabs. To open a dashboard use "
                                  "page='dashboard', dashboard=<name>.%s" % (
                                      page, cls._screen_nav_candidates(uid, 'dashboard')))
                tabs = cls._screen_tab_list(uid, page)
                hit, problem = cls._screen_find_tab(tabs, ref)
                if problem:
                    if page != 'dashboard':
                        dhit, _p = cls._screen_find_tab(
                            cls._screen_tab_list(uid, 'dashboard'), ref)
                        if dhit:
                            problem = ("'%s' is a dashboard, not a tab of the %s "
                                       "page. Use page='dashboard', dashboard='%s'."
                                       % (ref, page, dhit[1]))
                    elif dashboard:
                        problem += " Use page='dashboard', dashboard=<one of these>."
                    return None, problem
                tid, label = hit
                if page == 'dashboard':
                    url = '/dashboard/%s' % tid
                    describe = "open dashboard '%s'" % label
                else:
                    url = '%s?tab_id=%s' % (url, tid)
                    describe = "open the %s page, tab '%s'" % (page, label)
            # page·label 은 화면이 사람 말로 [허용] 카드를 그리는 데 쓴다.
            return {'url': url, 'page': page, 'label': label,
                    'describe': describe}, None

        tab_page = target.get('page_kind') in ('inputs', 'outputs', 'functions')
        if action == 'highlight' and (item or kind) and not tab_page:
            # 지도 안의 핀(장치·구획 …) 강조 — 위젯 전체가 아니라 그 자리. 이름 해석·
            # 지도 소속 판정은 open_map_item 과 같다(widget 은 지도 위젯).
            out, problem = cls._screen_map_item_args(
                target, widget, item, kind, None, center=center, zoom=value)
            if problem:
                return None, problem
            out['pin'] = True
            out['describe'] = "highlight %s '%s' on the map" % (out['kind'], out['name'])
            return out, None

        if action in ('highlight', 'open_widget_settings') and tab_page:
            # 입력·출력·함수 페이지 — 위젯이 아니라 카드다: 설정은 카드의 톱니를 누르고, 강조는 지금 보는 탭의
            # 그 카드로 스크롤해 테두리를 건다(다른 탭의 카드는 화면에 없다 — 그 안내는 `_screen_card_args`).
            out, problem = cls._screen_card_args(target, widget or item)
            if out and action == 'highlight':
                out = cls._screen_card_highlight(out)
            return out, problem

        if action in ('highlight', 'open_widget_settings'):
            if not widget:
                return None, ("widget is required (name or widget_id from get_screen)."
                              + (" To point at a place or device on a map, pass "
                                 "item (and kind) instead." if action == 'highlight'
                                 else ""))
            here = target.get('page_ref') if target.get('page_kind') == 'dashboard' else None
            if not here:
                return None, cls._screen_not_dashboard(target, action)
            w, amb = cls._screen_widget_pick(
                Widget.query.filter(Widget.tab_id == here).all(), widget)
            if amb:
                return None, amb
            if w is None:
                return None, ("No widget '%s' on the dashboard that screen is "
                              "showing. Check get_screen's widget list, or "
                              "navigate to its dashboard first." % widget)
            if action == 'open_widget_settings':
                d = find_dashboard(here)
                if d is not None and d.locked:
                    return None, ("That dashboard is locked, so its widget "
                                  "settings cannot be opened.")
                describe = "open the settings of widget '%s'" % w.name
            else:
                describe = "highlight widget '%s'" % w.name
            return {'widget_id': w.unique_id, 'name': w.name,
                    'describe': describe}, None

        if action == 'open_map_item':
            if target.get('page_kind') in ('inputs', 'outputs', 'functions'):
                # 입력·출력·함수 페이지에는 지도가 없다 — 같은 동작이 그 장치 카드의 설정창을 연다.
                return cls._screen_card_item_args(target, widget or item, kind)
            return cls._screen_map_item_args(target, widget, item, kind, tab,
                                             center=center, zoom=value)

        if action == 'open_notes':
            return cls._screen_notes_args(item, kind)

        if action == 'modal_tab':
            # 지도 창의 탭(현황·환경·제어·설정 …). 어떤 탭이 있는지는 화면만 안다 —
            # get_screen 의 dialog_tabs. 없는 이름이면 화면이 목록과 함께 실패를 돌려준다.
            # AI 가 `tab` 대신 value 로 주는 일이 잦았다(2026-10-28 점검) — 글자면 탭 이름으로 받는다.
            name = (tab or (value if isinstance(value, str) else '') or '').strip()
            if not name:
                return None, "tab is required (a tab of the open map window)."
            return {'tab': name[:60],
                    'describe': "open the '%s' tab of the open window" % name}, None

        if action == 'map_control':
            return cls._screen_map_control_args(target, widget, op, value, kind, layer)

        if action == 'close_modal':
            return {'describe': "close the open dialog"}, None
        return {'describe': "reload the page"}, None   # reload

    #: 페이지 → 그 페이지 카드의 DB 모델(함수 페이지는 여러 종류).
    @staticmethod
    def _screen_card_models(page_kind):
        from aot.databases.models import (Conditional, CustomController, Function,
                                          Input, Output, PID, Trigger)
        return {'inputs': [('input', Input)], 'outputs': [('output', Output)],
                'functions': [('function', m) for m in (
                    CustomController, Conditional, Trigger, PID, Function)]
                }.get(page_kind, [])

    @classmethod
    def _screen_card_args(cls, target, widget):
        """입력·출력·함수 페이지의 카드 하나 → 설정 버튼을 누르는 데 필요한 것.

        카드는 지금 보는 탭의 것만 누를 수 있다(다른 탭의 카드는 화면에 없다)."""
        kind = target.get('page_kind')
        ref = (widget or '').strip()
        if not ref:
            return None, ("widget is required: the name or id of the card on this %s "
                          "page (see get_screen)." % kind)
        tabs = cls._screen_tab_list(target.get('user_id'), kind)
        tab = target.get('page_ref') or (tabs[0][0] if tabs else None)
        cards = []          # (card_kind, row)
        for card_kind, model in cls._screen_card_models(kind):
            for row in model.query.filter(model.tab_id == tab).all():
                cards.append((card_kind, row))
        hits = [c for c in cards if c[1].unique_id == ref]
        hits = hits or [c for c in cards if (c[1].name or '').strip() == ref]
        hits = hits or [c for c in cards if ref.lower() in (c[1].name or '').lower()]
        if len(hits) > 1:
            return None, ("'%s' matches %d cards on this tab: %s. Use the full name "
                          "or id." % (ref, len(hits), ", ".join(
                              "'%s'" % (c[1].name or '') for c in hits[:6])))
        if not hits:
            names = [(c[1].name or '').strip() for c in cards][:12]
            return None, ("No card '%s' on the tab that screen is showing. Cards "
                          "here: %s. A card on another tab needs a navigate with "
                          "that tab first." % (ref, ", ".join(
                              "'%s'" % n for n in names) or 'none'))
        card_kind, row = hits[0]
        name = (row.name or '').strip()
        return {'card_kind': card_kind, 'card_id': row.unique_id, 'name': name,
                'describe': "open the settings of %s card '%s'" % (card_kind, name)
                }, None

    @staticmethod
    def _screen_card_highlight(card):
        """카드 인자(`_screen_card_args`)를 강조 명령 인자로 — `id` 는 같은 대상을 거듭 보내지 않는 판정이 쓴다."""
        return dict(card, id=card['card_id'], widget_id=card['card_id'],
                    describe="highlight the %s card '%s'" % (card['card_kind'], card['name']))

    @classmethod
    def _screen_card_item_args(cls, target, ref, kind=None):
        """open_map_item 이 입력·출력·함수 페이지에서 받을 때 — 장치 이름·id 로 그 카드의 설정창.

        지금 보는 탭의 카드가 아니면 어디에 있는지 말한다(탭을 바꾸거나 다른 페이지로 가야 한다)."""
        page = target.get('page_kind')
        ref = (ref or '').strip()
        if not ref:
            return None, "item is required (a device name or id on this %s page)." % page
        if (kind or '').strip().lower() in ('site', 'zone', 'facility', 'plot'):
            return None, ("The %s page lists device cards; a %s has no settings window "
                          "here. Navigate to a dashboard with its map." % (page, kind))
        args, problem = cls._screen_card_args(target, ref)
        if args:
            return args, None
        low = ref.lower()
        for card_kind, model in [m for p_ in ('inputs', 'outputs', 'functions')
                                 for m in cls._screen_card_models(p_)]:
            every = model.query.all()
            rows = [r for r in every if r.unique_id == ref or (r.name or '').strip() == ref]
            rows = rows or [r for r in every if low and low in (r.name or '').lower()]
            if len(rows) != 1:
                continue
            row, name = rows[0], (rows[0].name or '').strip()
            here = {'input': 'inputs', 'output': 'outputs', 'function': 'functions'}[card_kind]
            tab = next((label for tid, label in cls._screen_tab_list(
                target.get('user_id'), here) if tid == row.tab_id), None)
            return None, ("'%s' is %s %s; its card is on the %s page%s. Navigate there "
                          "first (page='%s'%s), then call open_map_item again." % (
                              name, 'an' if card_kind == 'input' else 'a', card_kind, here,
                              (", tab '%s'" % tab) if tab else '', here,
                              (", tab='%s'" % tab) if tab else ''))
        return None, problem

    @classmethod
    def _screen_open_settings(cls, device_id):
        """열린 설정창의 대상 — 모달 id(modal_config_<id>)의 id 를 장치로 푼다.

        종류명이 설정창 위에 보이므로(사용자 2026-10-11) 그 종류를 알려 주고, 그 종류의
        설명(AI 문서)을 찾아가는 길과 핵심 몇 줄을 함께 준다. 모르는 id 면 None."""
        from aot.databases.models import (Conditional, CustomController, Function,
                                          Input, Output, PID, Trigger, Widget)
        ident = str(device_id or '').strip()
        if not ident:
            return None
        try:
            for kind, model in (('input', Input), ('output', Output)):
                row = model.query.filter(model.unique_id == ident).first()
                if row is not None:
                    return cls._screen_device_type_info(kind, row.device, row)
            for model in (CustomController, Conditional, Trigger, PID, Function):
                row = model.query.filter(model.unique_id == ident).first()
                if row is not None:
                    ftype = getattr(row, 'device', None) or getattr(
                        row, 'function_type', None) or model.__name__.lower()
                    return cls._screen_device_type_info('function', ftype, row)
            w = Widget.query.filter(Widget.unique_id == ident).first()
            if w is not None:
                return {'kind': 'widget', 'name': (w.name or '').strip(), 'id': ident,
                        'type': w.graph_type}
        except Exception:                                   # noqa: BLE001
            logger.debug("open settings lookup failed", exc_info=True)
        return None

    @staticmethod
    def _clip_at_boundary(text, limit):
        """글이 limit 를 넘으면 문장(없으면 단어) 경계에서 자르고 '…' 을 붙인다.
        문장 중간에서 뚝 끊긴 요약이 AI 에게 읽히지 않게 한다."""
        import re as _re
        s = _re.sub(r'\s+', ' ', str(text or '')).strip()
        if len(s) <= limit:
            return s
        head = s[:limit]
        cut = max(head.rfind('. '), head.rfind('! '), head.rfind('? '),
                  head.rfind('。'))
        if cut >= limit * 0.4:
            return head[:cut + 1].rstrip() + ' …'
        cut = head.rfind(' ')
        if cut >= limit * 0.4:
            head = head[:cut]
        return head.rstrip(' ,;:-') + '…'

    @classmethod
    def _screen_device_type_info(cls, kind, dev_type, row):
        """설정창 대상 한 줄 + 종류 설명으로 가는 길."""
        out = {'kind': kind, 'name': (row.name or '').strip(),
               'id': row.unique_id, 'type': dev_type}
        info = {}
        try:
            if kind == 'input':
                info = cls._input_types().get(dev_type) or {}
                name = info.get('input_name')
            elif kind == 'output':
                info = cls._output_types().get(dev_type) or {}
                name = info.get('output_name')
            else:
                from aot.config import FUNCTION_INFO
                info = FUNCTION_INFO.get(dev_type) or {}
                name = info.get('name') or info.get('function_name')
        except Exception:                                   # noqa: BLE001
            name = None
        out['type_name'] = name or dev_type
        brief = []
        for key in ('input_manufacturer', 'measurements_name'):
            if info.get(key):
                brief.append('%s: %s' % (key.replace('input_', ''),
                                         cls._clip_at_boundary(info[key], 80)))
        if info.get('interfaces'):
            brief.append('interfaces: %s' % ', '.join(str(i) for i in info['interfaces'][:6]))
        if info.get('message'):
            brief.append(cls._clip_at_boundary(info['message'], 160))
        if brief:
            out['type_summary'] = ' | '.join(brief)
        # 운영 모드에서 부를 수 있는 길만 적는다(옵션 목록 도구는 설정 모드 전용이라
        # 응답이 운영 밖 도구를 가리키면 안 된다 — 종류 id 를 정확히 주는 것으로 대신한다).
        out['type_docs'] = ("This is device type '%s' (%s). For its manual call "
                            "knowledge_search with query='%s'; this device's own "
                            "settings: get_device_detail with id='%s'." % (
                                dev_type, out['type_name'], out['type_name'],
                                row.unique_id))
        return out

    @classmethod
    def _screen_not_dashboard(cls, target, action):
        """대시보드가 아닌 화면에서 위젯 동작을 거절할 때의 안내 — 왜 안 되는지와
        대신 할 수 있는 것을 말한다(설계상 위젯은 대시보드에만 있다)."""
        from aot.utils import web_presence as wp
        kind = target.get('page_kind')
        if kind in wp.TAB_PAGE_TYPES:
            noun = {'inputs': 'input', 'outputs': 'output', 'functions': 'function'}.get(
                kind, 'device')
            if action == 'highlight':
                return ("The %s page lists %s cards, not dashboard widgets, so "
                        "highlight does not apply here. To show a card's settings "
                        "use open_widget_settings with the %s name; to point at a "
                        "widget, navigate to its dashboard first." % (
                            kind, noun, noun))
            return ("The %s page has no dashboard widgets. Pass the %s card's "
                    "name or id as `widget` to open its settings." % (kind, noun))
        return ("That screen is not showing a dashboard (it shows %s). Widgets "
                "live on dashboards: navigate to the widget's dashboard first." %
                (kind or 'an unknown page'))

    @classmethod
    def _screen_notes_args(cls, item, kind=None):
        """노트창을 열 대상 하나 → (id, 종류, 이름). 웹의 노트창(`open-notes` 이벤트)이
        받는 targetId·targetType·name 과 같다. 이름은 노트 쓰기 도구와 같은 해석기를
        쓴다 — 노트가 붙는 곳이 곧 노트창이 여는 곳이다."""
        ref = (item or '').strip()
        if not ref:
            return None, "item is required (a place, plot or device name or id)."
        found = None
        try:
            found = cls._target_by_id_lookup(ref)
            if found is None:
                tid, ttype, name, _lat, _lng = cls._resolve_note_target(ref)
                if ttype == 'ambiguous':
                    cands = []
                    for c in (cls._ambiguous_places(ref) or [])[:6]:
                        cands.append("%s (%s)" % (c.get('use_name') or c.get('name')
                                                  or ref, c.get('type')))
                    return None, ("'%s' matches several places: %s. Pass one of "
                                  "these names." % (ref, ", ".join(cands)))
                if tid:
                    found = (tid, ttype, name)
        except Exception as exc:                            # noqa: BLE001
            return None, "Cannot open notes for '%s': %s" % (ref, exc)
        if found is None:
            return None, ("Nothing named '%s' that has notes (sites, zones, "
                          "facilities, plots, devices)." % ref)
        tid, ttype, name = found
        kind = (kind or '').strip().lower()
        # device 는 input·output 둘 다, sensor 는 input 의 다른 이름이다.
        ok = {ttype}
        if ttype in ('input', 'output'):
            ok.add('device')
        if ttype == 'input':
            ok.add('sensor')
        if kind and kind not in ok:
            return None, "'%s' is a %s, not a %s." % (ref, ttype, kind)
        name = name or ref
        return {'target_id': tid, 'target_type': ttype, 'name': name,
                'describe': "open the notes of %s '%s'" % (ttype, name)}, None

    @classmethod
    def _screen_map_item_args(cls, target, widget, item, kind, tab=None,
                              center=None, zoom=None, for_highlight=False):
        """지도 위젯의 도형 하나 → 그 창을 여는 데 필요한 것(종류·ID·이름).

        라벨을 눌렀을 때와 **같은 창**을 연다. 화면 JS 는 라벨을 흉내 내지 않고
        지도 위젯이 라벨 클릭에 쓰는 함수를 ID 로 부른다 — 라벨은 겹침 정리·
        레이어 끄기로 화면에 없을 때가 많다. 그 도형이 이 위젯의 지도에 있는지는
        화면이 판단한다(위젯이 고르는 지도는 서버 쪽 대체 규칙이 복잡하다).
        """
        from aot.databases.models import GeoPlot, GeoShape, Input, Output

        w, problem = cls._screen_pick_map(target, widget)
        if problem:
            return None, problem

        ref = (item or '').strip()
        kind = (kind or '').strip().lower() or None
        # 사람이 부르는 말 — 센서·입력·출력은 지도에서 모두 '장치', 대지는 site.
        kind = {'sensor': 'device', 'input': 'device', 'output': 'device',
                'land': 'site', 'field': 'site'}.get(kind, kind)
        # 오류의 후보 표기('영양 육묘장 (facility)')를 그대로 다시 보내도 받는다.
        import re as _re
        m = _re.match(r'^(.*\S)\s*\((site|zone|facility|plot|device)\)$', ref)
        if m:
            ref, kind = m.group(1), kind or m.group(2)
        if not ref:
            return None, "item is required (a place, plot or device name or id)."
        if kind and kind not in cls._MAP_ITEM_KINDS:
            if kind == 'equipment':
                return None, "Equipment has no window to open."
            return None, "kind must be one of: %s." % ", ".join(cls._MAP_ITEM_KINDS)

        found = None      # (kind, id, name)

        def from_shape(shape, name=None):
            t = (shape.type or '').lower()
            name = name or ((shape.feature or {}).get('properties') or {}).get('name')
            if t in ('site', 'zone', 'facility'):
                return t, shape.unique_id, name
            from aot.space.device_binding import device_for_shape
            dev = device_for_shape(shape)
            if dev:
                return 'device', dev, name
            return None

        def plot_row(p):
            return 'plot', p.unique_id, p.name or p.subject

        def plot_label(p):
            return ((p.name or '').strip(), (p.subject or '').strip())

        growing = GeoPlot.query.filter(GeoPlot.ended_on.is_(None)).all()

        if kind in (None, 'plot'):
            p = GeoPlot.query.filter(GeoPlot.unique_id == ref).first()
            if p is None:
                # 구획 라벨은 이름이 없으면 작목(subject)을 쓴다 — '콩 4구' 처럼.
                # 여기서는 정확히 같은 것만. 사람이 그 일부('4구')로 부르는 경우는
                # 장소·장치 이름을 다 본 뒤 맨 끝에서 받는다(2026-10-10 실화면 확인).
                hits = [p for p in growing if ref in plot_label(p)]
                if len(hits) > 1:
                    return None, ("'%s' matches %d growing plots: %s. Use the "
                                  "full name." % (ref, len(hits), ", ".join(
                                      "'%s'" % (p.name or p.subject) for p in hits[:6])))
                p = hits[0] if hits else None
            if p is not None:
                found = plot_row(p)
        if found is None and kind != 'plot':
            shape = GeoShape.query.filter(GeoShape.unique_id == ref).first()
            if shape is not None:
                if (shape.type or '') == 'equipment':
                    return None, "Equipment has no window to open."
                found = from_shape(shape)
            if found is None:
                for model in (Input, Output):
                    row = model.query.filter(model.unique_id == ref).first()
                    if row is not None:
                        found = ('device', row.unique_id, row.name)
                        break
            if found is None:
                tid, ttype, name, _lat, _lng = cls._resolve_note_target(ref)
                if ttype == 'ambiguous':
                    # 같은 이름이 여럿 — 종류로 먼저 좁히고, 그래도 여럿이면 지금
                    # 고른 지도에 있는 것을 쓴다(사용자는 보고 있는 지도의 것을 말한다).
                    # 후보는 '영양 육묘장(site)' 처럼 종류와 함께 보여 준다
                    # (2026-10-11 시험: 같은 이름 두 개만 나와 고를 수 없었다).
                    cands = []
                    for c in (cls._ambiguous_places(ref) or []):
                        label = c.get('use_name') or c.get('name') or ref
                        cands.append((c.get('type'), c.get('target_id'), label))
                        for x in c.get('also_inside') or []:
                            cands.append((x.get('type'), x.get('target_id'), label))
                    if kind:
                        cands = [c for c in cands if c[0] == kind] or cands
                    map_uuid = cls._screen_widget_map_uuid(w)
                    if len(cands) > 1 and map_uuid:
                        here = [c for c in cands if c[1] and GeoShape.query.filter(
                            GeoShape.unique_id == c[1],
                            GeoShape.geo_id == map_uuid).first() is not None]
                        cands = here or cands
                    if len(cands) == 1:
                        shape = GeoShape.query.filter(
                            GeoShape.unique_id == cands[0][1]).first()
                        if shape is not None:
                            found = from_shape(shape, cands[0][2])
                    if found is None:
                        return None, ("'%s' matches several places: %s. Pass kind or "
                                      "one of these names." % (ref, ", ".join(
                                          "%s (%s)" % (c[2], c[0]) for c in cands[:6])))
                if tid and ttype in ('input', 'output'):
                    found = ('device', tid, name)
                elif tid:
                    shape = GeoShape.query.filter(GeoShape.unique_id == tid).first()
                    if shape is not None:
                        found = from_shape(shape, name)
                        if found is None and (shape.type or '') == 'equipment':
                            return None, "Equipment has no window to open."
        if found is None and kind in (None, 'plot'):
            # 마지막으로 구획 이름의 일부 — 장소·장치 이름보다 뒤에 둔다. 앞에
            # 두면 구역 '3-1' 을 '콩 3-1구' 같은 구획으로 잘못 잡는다.
            hits = [p for p in growing if any(ref in t for t in plot_label(p) if t)]
            if len(hits) > 1:
                return None, ("'%s' matches %d growing plots: %s. Use the full "
                              "name." % (ref, len(hits), ", ".join(
                                  "'%s'" % (p.name or p.subject) for p in hits[:6])))
            if hits:
                found = plot_row(hits[0])
        if found is None:
            return None, ("Nothing named '%s' that opens a window on the map "
                          "(sites, zones, facilities, plots, devices)." % ref)
        if kind and kind != found[0] and found[0] in ('site', 'zone', 'facility') \
                and kind in ('site', 'zone', 'facility'):
            # 대지와 시설이 같은 이름인 곳이 있다('영양 육묘장'). 이름이 대지로 풀렸어도
            # 같은 지도에 그 이름의 시설이 있으면 그것이다(2026-10-11 재시험).
            base = GeoShape.query.filter(GeoShape.unique_id == found[1]).first()
            same = [sh for sh in (GeoShape.query.filter(
                GeoShape.type == kind, GeoShape.geo_id == base.geo_id).all()
                if base is not None else [])
                if (((sh.feature or {}).get('properties') or {}).get('name') or '').strip()
                == (found[2] or '').strip()]
            if len(same) == 1:
                found = from_shape(same[0], found[2]) or found
        if kind and kind != found[0]:
            return None, "'%s' is a %s, not a %s." % (ref, found[0], kind)
        # 그 지도에 없으면 화면에 보내지 않는다 — 서버가 지도 소속을 안다(대지·구역·
        # 시설·구획). 보내면 화면이 조용히 버리고 AI 는 '열었다' 고 말했다.
        map_uuid = cls._screen_widget_map_uuid(w)
        geo = None
        if found[0] == 'plot':
            p = GeoPlot.query.filter(GeoPlot.unique_id == found[1]).first()
            geo = p.geo_id if p else None
        elif found[0] in ('site', 'zone', 'facility'):
            sh = GeoShape.query.filter(GeoShape.unique_id == found[1]).first()
            geo = sh.geo_id if sh else None
        if map_uuid and geo and geo != map_uuid:
            label = ref if (found[2] and found[2] in ref) else (found[2] or ref)
            where = cls._screen_maps_showing(found[0], found[1], w.unique_id)
            return None, ("%s '%s' is not on map '%s'. %s" % (
                found[0], label, (w.name or '').strip(),
                ("It is shown on %s — navigate there first." % "; ".join(where))
                if where else "No map on the user's dashboards shows it."))
        k, ident, name = found
        if name and name in ref and len(ref) > len(name):
            name = ref                      # '영양 육묘장' 을 '육묘장' 으로 줄이지 않는다
        out = {'widget_id': w.unique_id, 'kind': k, 'id': ident, 'name': name or ref,
               'describe': "open %s '%s' on map '%s'" % (k, name or ref, w.name or '')}
        if tab:
            out['tab'] = str(tab).strip()[:60]          # 창이 뜬 뒤 그 탭을 누른다
            out['describe'] += ", tab '%s'" % out['tab']
        # 지도 이동 — 창만 열면 지도는 그대로여서 사용자가 "어디" 인지 못 본다
        # (2026-10-11 리허설). 서버가 도형 좌표를 알려 주고 화면이 flyTo 한다.
        want_center = not (center is False or str(center).lower() in (
            'false', 'off', '0', 'no'))
        out['center'] = want_center
        if want_center:
            ll = cls._screen_item_lnglat(k, ident, map_uuid)
            if ll:
                out['lnglat'] = ll
                try:
                    if zoom not in (None, ''):
                        out['zoom'] = max(1.0, min(22.0, float(zoom)))
                        out['zoom_fixed'] = True
                except (TypeError, ValueError):
                    pass
                out.setdefault('zoom', cls._MAP_ITEM_ZOOM.get(k, 17.0))
        return out, None

    #: 지도 항목을 가운데로 가져올 때의 기본 확대 수준(지금이 더 가까우면 유지).
    _MAP_ITEM_ZOOM = {'site': 16.0, 'zone': 17.0, 'facility': 18.0, 'plot': 18.0,
                      'device': 18.0}

    @classmethod
    def _screen_item_lnglat(cls, kind, ident, map_uuid=None):
        """지도 항목의 대표 좌표 [경도, 위도] — 못 찾으면 None.

        대지·구역·시설은 도형, 구획은 자기 도형, 장치는 매여 있는 지도 도형
        (그 지도 것만 — 없으면 좌표 없음)."""
        from aot.databases.models import GeoPlot, GeoShape
        from aot.space import device_binding as db_

        def lnglat(feature):
            c = db_._centroid(feature)          # [lat, lng]
            return [c[1], c[0]] if c else None

        try:
            if kind == 'plot':
                p = GeoPlot.query.filter(GeoPlot.unique_id == ident).first()
                return lnglat(p.feature) if p is not None else None
            if kind in ('site', 'zone', 'facility'):
                sh = GeoShape.query.filter(GeoShape.unique_id == ident).first()
                return lnglat(sh.feature) if sh is not None else None
            if kind == 'device':
                shapes = []
                for b in db_.bindings_for_device(ident):
                    if b.spatial_kind == 'shape':
                        sh = GeoShape.query.filter(
                            GeoShape.unique_id == b.spatial_id).first()
                        if sh is not None:
                            shapes.append(sh)
                # **이 지도의 도형만** 쓴다. 예전에는 이 지도 것을 앞에 둘 뿐 없으면
                # 다른 지도(다른 현장)의 도형 중심으로 넘어가, 영양 지도에서 연 장치가
                # 김제 쪽 좌표로 날아갔다. 이 지도에 매인 도형이 없으면 좌표가 없다
                # (L4 S3c: 장치 행에 위치 컬럼이 없다 — 배치 도형만이 정본).
                if map_uuid:
                    shapes = [sh for sh in shapes if sh.geo_id == map_uuid]
                for sh in shapes:
                    got = lnglat(sh.feature)
                    if got:
                        return got
        except Exception:                                   # noqa: BLE001
            logger.debug("screen item position lookup failed", exc_info=True)
        return None

    #: 시간 슬라이더 이동 한도 — 지도 시간 축 자체가 +7일·−2일 안으로 다시 가두지만, 터무니없는 값은 거절한다.
    _MAP_TIME_LIMIT_MS = 30 * 86400 * 1000

    @classmethod
    def _screen_time_arg(cls, value):
        """map_control op=time 의 value → (시각 지정, 오류).

        받는 모양: ``now`` · 지금 기준 오프셋(``+24h``, ``-3h``, ``+90m``, ``+2d``) · ISO 8601 시각.
        시간대(Z·+09:00)가 있으면 절대 시각, 없으면 사용자 화면의 현지 시각으로 읽는다
        (화면이 그 지도의 시간대를 알고 있다 — 서버는 모른다).
        """
        import datetime as _dt
        import re as _re
        text = str(value if value is not None else '').strip()
        if not text:
            return None, ("value is required for time: 'now', an offset from now like "
                          "'+24h' / '+2d', or an ISO 8601 time like '2026-10-24T15:00+09:00'.")
        low = text.lower()
        if low in ('now', 'current'):
            return {'kind': 'now', 'text': 'now'}, None
        m = _re.match(r'^([+-]?)\s*(\d+(?:\.\d+)?)\s*(m|min|h|d)$', low)
        if m:
            unit = {'m': 60, 'min': 60, 'h': 3600, 'd': 86400}[m.group(3)]
            ms = int(round(float(m.group(2)) * unit * 1000)) * (-1 if m.group(1) == '-' else 1)
            if abs(ms) > cls._MAP_TIME_LIMIT_MS:
                return None, "time offset is too far; the time slider covers about -2 hours to +7 days."
            return {'kind': 'offset', 'ms': ms, 'text': '%s from now' % text}, None
        try:
            if text.endswith(('Z', 'z')):
                from aot.utils.timekit import parse_utc
                dt = parse_utc(text)
            else:
                dt = _dt.datetime.fromisoformat(text)
        except ValueError:
            return None, ("time must be 'now', an offset like '+24h', or an ISO 8601 time "
                          "like '2026-10-24T15:00+09:00' (got %r)." % text[:40])
        if dt.tzinfo is None:
            return {'kind': 'local', 'iso': dt.replace(microsecond=0).isoformat(), 'text': text}, None
        return {'kind': 'at', 'ms': int(dt.timestamp() * 1000), 'text': text}, None

    @classmethod
    def _screen_map_control_args(cls, target, widget, op, value, kind, layer):
        """지도 조작 — 보기(확대·회전·기울기·북쪽·처음 보기)·전체화면·라벨·도형·레이어."""
        op = (op or '').strip()
        if op == 'reset_view':      # 옛 이름 — 동작은 처음 보기가 아니라 천천히 도는 회전이었다
            op = 'orbit'
        if op not in cls._MAP_OPS:
            return None, "op must be one of: %s." % ", ".join(cls._MAP_OPS)
        w, problem = cls._screen_pick_map(target, widget)
        if problem:
            return None, problem
        out = {'widget_id': w.unique_id, 'op': op}
        mapname = w.name or ''
        if op == 'time':
            when, problem = cls._screen_time_arg(value)
            if problem:
                return None, problem
            out['time'] = when
            out['describe'] = "move map '%s' time slider to %s" % (mapname, when['text'])
            return out, None
        if cls._MAP_OPS[op]:
            try:
                out['value'] = float(value)
            except (TypeError, ValueError):
                return None, "value (a number) is required for %s." % op
        elif op in ('fullscreen', 'labels', 'shapes', 'overlay', 'orbit'):
            # 켜기/끄기 — 기본은 켜기. 문자열로 와도 받는다.
            out['value'] = not (value is False or str(value).lower() in
                                ('false', 'off', '0', 'no', 'hide'))
        if op == 'labels':
            # 지도 라벨에는 '장치' 종류가 따로 없다 — 센서는 입력(input), 제어 장치는
            # 출력(output) 라벨이다. 사람이 부르는 말(device·field_sensor …)은 받아 준다
            # (2026-10-11 리허설: 설명은 device 라는데 거부, sensor 는 성공인데 안 나타남).
            kind = cls._MAP_LABEL_ALIASES.get((kind or '').strip().lower(),
                                              (kind or '').strip().lower())
            if kind not in cls._MAP_LABEL_KINDS:
                return None, ("kind must be one of: %s ('device', 'sensor' and "
                              "'sensors' mean input: field sensors are input "
                              "labels, controllers are output labels)." % ", ".join(cls._MAP_LABEL_KINDS))
            out['kind'] = kind
        if op == 'shapes':
            k = {'site': 'land'}.get(kind, kind)    # 포장 도형의 범주 이름은 land
            if k not in cls._MAP_SHAPE_KINDS:
                return None, "kind must be one of: site, %s." % ", ".join(
                    cls._MAP_SHAPE_KINDS[1:])
            out['kind'] = k
        if op in ('base_layer', 'overlay'):
            choices = cls._screen_layer_choices(target, w, op)
            if not (layer or '').strip():
                return None, ("layer is required. Choices: %s."
                              % (", ".join(choices) if choices else
                                 "the names shown in that map's layer menu"))
            if choices and layer.strip().lower() not in {c.lower() for c in choices}:
                return None, ("No layer '%s' on that map. Choices: %s."
                              % (layer.strip()[:80], ", ".join(choices)))
            out['name'] = layer.strip()[:80]
        what = {'labels': "%s labels" % out.get('kind'),
                'shapes': "%s shapes" % out.get('kind'),
                'overlay': "overlay '%s'" % out.get('name'),
                'fullscreen': 'fullscreen', 'orbit': 'slow 360° rotation'}.get(op)
        if what:
            out['describe'] = "turn %s %s on map '%s'" % (
                what, 'on' if out.get('value', True) else 'off', mapname)
        elif op == 'base_layer':
            out['describe'] = "switch map '%s' to base layer '%s'" % (mapname, out['name'])
        else:
            out['describe'] = "%s map '%s'%s" % (
                op.replace('_', ' '), mapname,
                ' to %g' % out['value'] if 'value' in out else '')
        return out, None

    @staticmethod
    def _screen_layer_choices(target, w, op):
        """그 지도 위젯에서 고를 수 있는 레이어 이름 — 화면이 보고한 목록에서.
        get_screen 에는 싣지 않고(사용자가 보는 것이 아니다) 여기서만 쓴다."""
        import json as _json
        try:
            st = _json.loads(target.get('client_state') or '{}')
        except ValueError:
            return []
        key = 'base_layers' if op == 'base_layer' else 'overlays'
        for m in st.get('maps') or []:
            if isinstance(m, dict) and str(m.get('widget_id')) == str(
                    getattr(w, 'unique_id', '')):
                return [str(x)[:80] for x in (m.get(key) or [])][:12]
        return []

    @classmethod
    def _screen_widget_map_uuid(cls, w):
        import json as _json
        try:
            return (_json.loads(w.custom_options or '{}') or {}).get('map_uuid')
        except (ValueError, AttributeError):
            return None

    @classmethod
    def _screen_item_geos(cls, kind, ident):
        """그 항목이 그려지는 지도(geo id)들 — 대지·구역·시설·구획은 자기 지도 하나,
        장치는 매여 있는 도형들의 지도. 모르면 빈 집합."""
        from aot.databases.models import GeoPlot, GeoShape
        if kind == 'plot':
            p = GeoPlot.query.filter(GeoPlot.unique_id == ident).first()
            return {p.geo_id} if p is not None and p.geo_id else set()
        if kind in ('site', 'zone', 'facility'):
            sh = GeoShape.query.filter(GeoShape.unique_id == ident).first()
            return {sh.geo_id} if sh is not None and sh.geo_id else set()
        if kind == 'device':
            try:
                from aot.space import device_binding as db_
                geos = set()
                for b in db_.bindings_for_device(ident):
                    if b.spatial_kind == 'shape':
                        sh = GeoShape.query.filter(
                            GeoShape.unique_id == b.spatial_id).first()
                        if sh is not None and sh.geo_id:
                            geos.add(sh.geo_id)
                return geos
            except Exception:                               # noqa: BLE001
                logger.debug("device map lookup failed", exc_info=True)
        return set()

    @classmethod
    def _screen_map_widgets_for(cls, kind, ident):
        """그 항목을 보여 주는 지도 위젯들(모든 대시보드) — 위젯이 고른 지도(map_uuid)와
        항목의 지도가 같은 것. 항목의 지도를 모르면 빈 목록(화면이 판단한다)."""
        from aot.databases.models import Widget
        geos = cls._screen_item_geos(kind, ident)
        if not geos:
            return []
        return [w for w in (Widget.query.filter(Widget.graph_type == 'AoT_map')
                            .order_by(Widget.position_y, Widget.position_x).all())
                if cls._screen_widget_map_uuid(w) in geos]

    @classmethod
    def _screen_maps_showing(cls, kind, ident, except_widget=None):
        """그 도형을 보여 주는 지도 위젯들 — "대시보드 '영양'의 지도 'GIS'" (최대 3)."""
        from aot.databases.models import Dashboard
        dnames = {d.unique_id: d.name for d in Dashboard.query.all()}
        out = []
        for w in cls._screen_map_widgets_for(kind, ident):
            if w.unique_id != except_widget:
                out.append("dashboard '%s', map '%s'" % (dnames.get(w.tab_id, '?'),
                                                         (w.name or '').strip()))
        return out[:3]

    @classmethod
    def _screen_pick_map(cls, target, widget=None):
        """그 화면의 대시보드에서 지도 위젯 **하나**를 고른다 → (위젯, 문제 문장).

        예전에는 지도가 여럿이면 화면이 위에서부터 차례로 시도해, 사용자가 보던
        지도 A 에 없는 대상이 B·C 를 엉뚱한 곳으로 움직였다(2026-10-11). 이제는
        하나만 고르고, 거기 없으면 실패로 돌려준다(화면이 다른 지도에 있는지는
        알려 준다). 순서: 이름으로 지정 → 이 화면에서 마지막으로 다룬 지도(지금도
        보이면) → 지금 보이는 지도 → 마지막으로 다룬 지도 → 맨 위 지도.
        """
        import json as _json
        import time as _time
        from aot.databases.models import Widget
        from aot.utils import web_presence as wp

        here = target.get('page_ref') if target.get('page_kind') == 'dashboard' else None
        if not here:
            return None, ("That screen is not showing a dashboard. Navigate to "
                          "the dashboard with the map first.")
        maps = (Widget.query.filter(Widget.tab_id == here,
                                    Widget.graph_type == 'AoT_map')
                .order_by(Widget.position_y, Widget.position_x).all())
        if widget:
            picked, amb = cls._screen_widget_pick(maps, widget)
            if amb:
                return None, amb
            maps = [picked] if picked else []
            if len(maps) > 1:
                return None, ("Several map widgets are named '%s'. Use the widget_id "
                              "from get_screen." % widget)
        if not maps:
            return None, "No map widget%s on the dashboard that screen is showing." % (
                " named '%s'" % widget if widget else "")
        if len(maps) == 1:
            return maps[0], None
        by_id = {m.unique_id: m for m in maps}
        visible = []
        if target.get('client_state') and \
                _time.time() - (target.get('client_at') or 0) < 60:
            try:
                visible = [i for i in (_json.loads(target['client_state'])
                                       .get('visible_widgets') or []) if i in by_id]
            except ValueError:
                visible = []
        last = wp.last_map_widget(target['browser_key'])
        if last in by_id and (not visible or last in visible):
            return by_id[last], None
        if visible:
            return by_id[visible[0]], None
        if last in by_id:
            return by_id[last], None
        return maps[0], None

    @classmethod
    def _screen_link(cls, user_id, browser_key):
        from aot.utils import web_presence as wp
        if not browser_key:
            return None
        return wp.page_link(wp.resolve_screen(user_id, str(browser_key)[:12]))

    @classmethod
    def _screen_not_on_map(cls, args, msg):
        """'지도에 없음' 을 사람이 쓰는 이름과 다음 할 일로 — 화면은 위젯 id 만 보낸다
        (화면의 제목은 사용자 언어로 번역돼 'Gimje' 처럼 왔다)."""
        import json as _json
        from aot.databases.models import Widget
        try:
            others = _json.loads(msg[len('not_on_map:'):]) or []
        except ValueError:
            others = []
        names = {w.unique_id: (w.name or '').strip() for w in Widget.query.filter(
            Widget.unique_id.in_([args.get('widget_id')] + list(others))).all()}
        what = "%s '%s'" % (args.get('kind') or 'item', args.get('name') or '?')
        text = "%s is not on map '%s'." % (what, names.get(args.get('widget_id'), '?'))
        if others:
            return text + " It is on map %s on this dashboard — pass widget='%s'." % (
                ", ".join("'%s'" % names.get(o, '?') for o in others),
                names.get(others[0], '?'))
        where = cls._screen_maps_showing(args.get('kind'), args.get('id'),
                                         args.get('widget_id'))
        if where:
            return text + " It is shown on %s — navigate there first." % "; ".join(where)
        return text + " No map on the user's dashboards shows it."

    #: 대상 종류마다 창의 탭이 다르다(2026-10-30) — 이 탭은 이 종류의 창에만 있다.
    #: 구역 창에는 트윈이 없다(대지·시설·구획에만). 탭 이름은 화면 JS 가 알아듣는 말.
    _TAB_OWNERS = (
        (('twin', '트윈', '디지털 트윈', '디지털트윈', 'digital twin'),
         ('site', 'facility', 'plot')),
        (('detail', 'facility detail', '시설 상세', '시설상세', '상세'), ('facility',)),
    )

    @classmethod
    def _screen_tab_hint(cls, row, args, msg):
        """창에 없는 탭으로 실패했을 때 — 그 탭을 가진 안쪽·바깥쪽 대상 후보를 덧붙인다(실패 응답에만).

        "3-1 의 트윈" 처럼 사용자는 창의 종류를 모른다. 구역에는 트윈이 없으니 그 안의 구획이나
        바깥 대지를 열어야 한다 — AI 가 짐작하지 않도록 이름으로 알려 준다. 모르면 빈 글."""
        import re as _re
        m = _re.search(r'no tab "(.*?)"', str(msg or ''))
        if not m:
            return ''
        want = _re.sub(r'\s+', ' ', m.group(1)).strip().lower()
        owners = next((kinds for names, kinds in cls._TAB_OWNERS if want in names), None)
        if not owners:
            return ''
        kind, ident, name = args.get('kind'), args.get('id'), args.get('name')
        try:
            if not ident:        # modal_tab — 지금 열린 창이 무엇의 창인가
                import json as _json
                from aot.utils import web_presence as wp
                pres = next((r for r in wp.recent(row.get('user_id'))
                             if r['browser_key'] == row.get('browser_key')), None)
                st = _json.loads(pres.get('client_state') or '{}') if pres else {}
                opened = cls._screen_open_item(pres, st.get('dialog')) if pres else None
                kind, ident, name = (opened or {}).get('kind'), (opened or {}).get('id'), \
                    (opened or {}).get('name')
            if not ident or kind in owners or kind not in ('site', 'zone', 'facility', 'plot'):
                return ''
            inside, above = cls._screen_tab_owners(kind, ident, owners)
        except Exception:                                   # noqa: BLE001
            logger.debug("tab hint failed", exc_info=True)
            return ''
        parts = []
        for label, found in (('inside it', inside), ('above it', above)):
            if found:
                parts.append("%s: %s%s" % (label, ", ".join(found[:6]), (
                    " (+%d more)" % (len(found) - 6)) if len(found) > 6 else ''))
        if not parts:
            return ''
        return (" A %s window has no '%s' tab; the windows that do: %s. Open one with "
                "open_map_item (item=<name>, tab='%s')." % (
                    kind, m.group(1), "; ".join(parts), m.group(1)))

    @classmethod
    def _screen_tab_owners(cls, kind, ident, owners):
        """그 대상 안쪽·바깥쪽에서 탭을 가진 종류의 대상 이름 → (안쪽 목록, 바깥쪽 목록).

        "종류 '이름'" 모양. 안쪽은 구획·시설, 바깥은 감싸는 대지(소속 판정은 지도 창과 같은 PlaceIndex)."""
        from aot.space.device_membership import PLACE_TYPES, PlaceIndex, place_label
        from aot.databases.models import GeoPlot
        idx = PlaceIndex()
        shape = idx.by_uid.get(ident)
        plots, places, above = [], [], []
        if 'plot' in owners and shape is not None:
            for p in GeoPlot.query.filter(GeoPlot.ended_on.is_(None)).all():
                if idx.plot_within(p, ident) and (p.name or p.subject):
                    plots.append("plot '%s'" % (p.name or p.subject))
        if shape is not None:
            for s in idx.shapes:
                if s.type in owners and s.type in PLACE_TYPES and s.unique_id != ident \
                        and ident in idx.chain_uids(s) and place_label(s):
                    places.append("%s '%s'" % (s.type, place_label(s)))
            outer = idx.chain(shape)
        else:                       # 구획 — 감싸는 장소들
            plot = GeoPlot.query.filter(GeoPlot.unique_id == ident).first()
            box = idx.plot_container(plot) if plot is not None else None
            outer = idx.chain(box) if box is not None else []
        above = ["%s '%s'" % (s.type, place_label(s)) for s in outer
                 if s.type in owners and s.unique_id != ident and place_label(s)]
        return plots + places, above

    @staticmethod
    def _screen_split_meta(msg):
        """화면이 결과 앞에 붙인 `@@{json}@@` 부가 정보를 떼어 (meta, 나머지 글).

        화면 결과는 글 한 줄이라, 지도 이동·강조 대상·라벨 변경 여부 같은 구조를
        이 표시로 실어 보낸다."""
        import json as _json
        import re as _re
        msg = str(msg or '')
        m = _re.match(r'^@@(\{.*?\})@@', msg)
        if not m:
            return {}, msg
        try:
            meta = _json.loads(m.group(1))
        except ValueError:
            meta = {}
        return (meta if isinstance(meta, dict) else {}), msg[m.end():]

    @classmethod
    def _screen_action_outcome(cls, row, link=None):
        import json as _json
        import time as _time
        if row is None:
            return {"status": "error", "error": "The screen action disappeared."}
        args = _json.loads(row.get('args') or '{}')
        result = _json.loads(row.get('result') or '{}') if row.get('result') else {}
        st = row['status']
        if st == 'done':
            meta, msg = cls._screen_split_meta(result.get('message'))
            msg = msg or None
            if msg and msg.startswith('window opened, but'):
                # 창은 열렸고 탭만 못 바꿨다 — '완료' 로만 읽히면 성공으로 오해한다.
                return dict({"status": "partial",
                             "done": "the window opened; the tab did not",
                             "message": msg[len('window opened, but '):]
                             + cls._screen_tab_hint(row, args, msg)}, **meta)
            out = {"status": "success", "done": args.get('describe'), "message": msg}
            if row.get('action') in ('navigate', 'reload'):
                # 화면은 떠나기 전에 결과부터 보낸다 — 새 페이지가 상태를 보고하기까지 몇 초는 이전 화면이 보인다.
                # B3(2026-11-07): "다시 읽어라" 로 끝나던 문구가 get_screen 재확인을 불렀다 — 이동은 끝났고 확인 호출은 필요 없다.
                out["note"] = ("The move is done and the page is loading. Do not call get_screen to confirm it "
                               "(it may show the old page for a few seconds); call it only to read the new page.")
            if args.get('op') == 'time':
                # 슬라이더 이동은 답에 덧붙이는 일이라 "옮겼습니다" 를 되풀이 보고하면 소음이다. 다만 이 응답이
                # 대화의 마지막 도구 결과라, "말하지 마라" 만 있으면 AI 가 답 전체를 비운다(2026-10-24 실측).
                out["say"] = ("Done. The map time is already updated on the user's screen, so it needs no "
                              "separate report; answer with the forecast values themselves, in the user's language.")
            if meta.get('highlighted') == 'widget' and args.get('pin'):
                # 화면이 요청과 다른 것을 했다(핀이 없어 지도 위젯 전체를 강조) — '성공' 으로
                # 읽히면 AI 는 그 장소를 가리켰다고 말한다(2026-10-14 사용자 시험).
                out["status"] = "partial"
                out["done"] = "highlighted the whole map widget instead"
            if meta.get('in_view') is False:
                # 화면이 그 자리로 가 보았지만 사용자에게 보이지 않는다(가려졌거나 화면 밖) — '성공' 으로 읽히면
                # AI 는 "보시는 곳이 ~입니다" 라고 말한다.
                out["status"] = "partial"
                out["done"] = "the target is not visible on the user's screen"
                out["message"] = meta.get('view_note') or out["message"]
            if row.get('action') == 'open_map_item' and args.get('center', True) \
                    and 'centered' not in meta:
                # 서버가 좌표를 못 찾아 화면에 이동을 시키지 못했다 — 말해 준다.
                meta['centered'] = False
                meta['center_note'] = ("no position known for this item, so the "
                                       "map view did not move")
            out.update(meta)
            return out
        if st in ('queued', 'delivered'):
            # 화면이 지금 보이는 중이면 몇 초 안에 실행된다 — "백그라운드라 나중에"
            # 라고 하면 AI 가 사용자에게 틀리게 말하거나 같은 명령을 다시 보낸다
            # (2026-10-11 시험: 1~3초 안에 실행된 명령이 '10분 안에' 로 답해졌다).
            from aot.utils import web_presence as wp
            pres = next((r for r in wp.recent(row.get('user_id'))
                         if r['browser_key'] == row.get('browser_key')), None)
            if pres is not None and wp.state_of(pres, _time.time()) == 'viewing':
                return {"status": "sent", "action": args.get('describe'),
                        "note": ("The screen has not confirmed it yet; it usually "
                                 "runs within a few seconds. Check get_screen "
                                 "before sending it again.")}
            out = {"status": "queued", "action": args.get('describe'),
                   "note": ("Sent. The screen has not run it yet — it may be in "
                            "the background; it runs when the screen comes back "
                            "(within 10 minutes).")}
            if link:
                # 폰에서 AI 앱으로 대화하면 AoT 탭은 뒤에 있다 — 링크를 누르면
                # 그 화면이 열리면서 밀린 명령을 바로 가져간다(2026-10-11).
                out["link"] = link
                out["note"] += (" If the user is on a phone talking to you in "
                                "another app, give them this link to tap.")
            return out
        if st == 'proposed':
            return {"status": "needs_confirmation",
                    "confirm_token": row.get('token'),
                    "note": "Still waiting for the user's OK."}
        if st == 'failed':
            msg = result.get('message') or 'unknown reason'
            if msg == 'no dialog was open':
                # 거짓 성공의 반대편 — 닫을 창이 없다. AI 카드는 창이 아니라 close_modal 이 닫지 않는다.
                return {"status": "error", "reason_code": "not_found",
                        "error": ("No dialog is open on that screen, so nothing was closed. "
                                  "AI cards are not dialogs; close_modal does not close them.")}
            if msg.startswith('not_on_map:'):
                return {"status": "error", "error": cls._screen_not_on_map(args, msg)}
            return {"status": "error", "error": "The screen could not do it: %s%s" % (
                msg, cls._screen_tab_hint(row, args, msg))}
        if st == 'rejected':
            return {"status": "rejected", "note": (
                "Not done: %s." % (result.get('reason') or 'declined'))}
        return {"status": "expired", "note": ("Not done: it waited too long. "
                                              "Ask again if still wanted.")}

    @classmethod
    def list_dashboards(cls, tab_id=None, with_options=False, brief=False, detail=False, **extra):
        """[읽기전용] 대시보드 탭과 그 안의 위젯들.

        `brief`·`detail` 은 도구 스키마에 없는 처리기 인자다 — 도메인 표면(find.dashboards)만 쓴다(2026-10-31).
        `brief`: 탭을 안 정하면 탭 이름·위젯 수만, 탭을 정하면 그 탭의 위젯을 좌표 없이(위젯 id 는 그대로 —
        위젯 조작이 쓴다). 좌표는 `detail.widget` 이나 `detail=true`. `with_options`·`detail` 이면 예전 모양.
        안 주면(인앱 AI) 예전과 같다.

        `custom_options` 는 기본으로 싣지 않는다 — 위젯 하나가 지도나 시설처럼
        큰 설정을 들고 있으면 목록 하나가 응답 상한을 넘길 수 있다. 하나를
        자세히 볼 때는 `get_widget` 을 쓴다.
        """
        try:
            import json
            from sqlalchemy import text
            from aot.databases.models import Dashboard, Widget

            catalog = cls._widget_catalog()
            # 대시보드 탭의 정본은 **Dashboard 테이블**이다. Widget.tab_id 의 FK
            # 선언은 tab.unique_id 를 가리키지만 실제로 담기는 값은 Dashboard 의
            # unique_id 이고, 화면(routes_dashboard.page_dashboard)도 Dashboard 를
            # 읽는다. FK 강제가 꺼져 있어 이 어긋남은 아무 에러도 내지 않는다 —
            # TabService.get_tabs_for_page('dashboard') 를 보면 **빈 목록**이
            # 돌아와 "대시보드가 하나도 없다" 로 읽힌다(실제로 겪었다).
            q = Dashboard.query.order_by(text("COALESCE(sort_order, 999999), id"))
            tabs = q.all()
            if tab_id:
                tabs = [t for t in tabs if t.unique_id == tab_id]
                if not tabs:
                    return {"status": "error",
                            "message": "no dashboard with id %s" % tab_id}

            lean = bool(brief) and not with_options and not detail
            out = []
            for tab in tabs:
                widgets = (Widget.query.filter(Widget.tab_id == tab.unique_id)
                           .order_by(Widget.position_y, Widget.position_x).all())
                entries = []
                for w in widgets:
                    item = cls._widget_brief(
                        w, catalog.get(w.graph_type))
                    if w.graph_type not in catalog:
                        item['warning'] = ('this widget type is not installed on '
                                           'this system — it will not render')
                    if with_options:
                        try:
                            item['options'] = json.loads(w.custom_options or '{}')
                        except Exception:
                            item['options'] = {}
                    if lean:
                        item.pop('position', None)
                    entries.append(item)
                entry = {'tab_id': tab.unique_id, 'name': tab.name,
                         'position': tab.sort_order,
                         'widget_count': len(entries), 'widgets': entries}
                if tab.locked:
                    entry['locked'] = True
                out.append(entry)
            if lean:
                return cls._dashboards_lean(out, bool(tab_id))
            return {"status": "success", "tabs": out}
        except Exception as e:
            logger.exception("Error in list_dashboards")
            return {"status": "error", "message": str(e)}

    @staticmethod
    def _dashboards_lean(tabs, one_tab):
        """find.dashboards 요약. 탭 하나를 정했으면 그 탭의 위젯(id 포함, 좌표 없음), 아니면 탭 이름·위젯 수만.

        탭 id 는 싣지 않는다 — 대시보드 이름은 유일하고(`Dashboard.name` unique) 탭 대상은 이름으로 푼다."""
        if one_tab:
            return {"status": "success",
                    "next": {"more": "detail.widget(target=<widget name or id>) gives position and settings; "
                                     "detail=true lists every widget with position"},
                    "tabs": tabs}
        rows = []
        for t in tabs:
            row = {"name": t.get('name'), "widgets": t.get('widget_count')}
            if t.get('locked'):
                row["locked"] = True
            rows.append(row)
        return {"status": "success",
                "next": {"call": "find(op='dashboards', target=<tab name>)",
                         "why": "that tab's widgets with their ids; detail=true lists every tab's widgets with position"},
                "count": len(rows), "tabs": rows}

    @classmethod
    def list_widget_types(cls, widget_type=None, **extra):
        """[읽기전용] 이 시스템에 설치된 위젯 종류.

        종류 이름만 아는 것으로는 `create_widget` 을 부를 수 없다 — 어떤 옵션을
        받는지가 종류마다 다르기 때문이다. 그래서 `widget_type` 을 주면 그 종류의
        **옵션 스키마**까지 낸다. 안 주면 목록만 낸다(전 종류의 스키마를 한 번에
        실으면 응답이 통째로 커진다).
        """
        try:
            catalog = cls._widget_catalog()
            if widget_type:
                info = catalog.get(widget_type)
                if not info:
                    return {"status": "error",
                            "message": "unknown widget type '%s'" % widget_type,
                            "available": sorted(catalog)}
                return {"status": "success", "widget_type": widget_type,
                        "name": str(info.get('widget_name') or widget_type),
                        "message": str(info.get('message') or '') or None,
                        "default_size": {"width": info.get('widget_width'),
                                         "height": info.get('widget_height')},
                        "options": cls._widget_option_schema(info)}
            return {"status": "success",
                    "types": [{"widget_type": key,
                               "name": str(info.get('widget_name') or key),
                               "option_count": len(info.get('custom_options') or [])}
                              for key, info in sorted(catalog.items())],
                    "next": ("call again with widget_type=<one of these> to get its "
                             "option schema before creating one")}
        except Exception as e:
            logger.exception("Error in list_widget_types")
            return {"status": "error", "message": str(e)}

    @classmethod
    def get_widget(cls, widget_id=None, **extra):
        """[읽기전용] 위젯 하나 — 설정(custom_options) 포함."""
        try:
            import json
            from aot.databases.models import Widget

            if not widget_id:
                return {"status": "error", "message": "widget_id is required"}
            w = Widget.query.filter(Widget.unique_id == widget_id).first()
            if not w:
                return {"status": "error", "message": "no widget with id %s" % widget_id}

            catalog = cls._widget_catalog()
            info = catalog.get(w.graph_type)
            out = cls._widget_brief(w, info)
            try:
                out['options'] = json.loads(w.custom_options or '{}')
            except Exception:
                out['options'] = {}
            out['tab_id'] = w.tab_id
            if info:
                out['option_schema'] = cls._widget_option_schema(info)
            else:
                out['warning'] = ('this widget type is not installed on this system '
                                  '— it will not render')
            return {"status": "success", "widget": out}
        except Exception as e:
            logger.exception("Error in get_widget")
            return {"status": "error", "message": str(e)}

    @classmethod
    def create_widget(cls, tab_id=None, widget_type=None, name=None, options=None,
                      width=None, height=None, **extra):
        """[쓰기] 대시보드 탭에 위젯을 추가한다. 사람 승인 필요."""
        try:
            import json
            from aot.databases.models import Dashboard, Widget
            from aot.aot_flask.utils.utils_general import custom_options_return_json

            if not tab_id or not widget_type:
                return {"status": "error",
                        "message": "tab_id and widget_type are required — call "
                                   "list_dashboards for tabs and list_widget_types "
                                   "for the types"}
            # 위 list_dashboards 주석 참조 — 대시보드 탭은 Dashboard 테이블이다.
            tab = Dashboard.query.filter(Dashboard.unique_id == tab_id).first()
            if not tab:
                return {"status": "error",
                        "message": "no dashboard with id %s" % tab_id}
            # 쓰기 시점 그룹 스코프 — 위젯을 놓을 대시보드로, 그리고 옵션에
            # 적은 장치·다른 대시보드로 묻는다(위젯 버튼이 그 장치를 움직인다).
            from aot.aot_flask.access import scope as _scope
            from aot.aot_flask.access import write_scope
            write_scope.enforce(tab)
            if options:
                write_scope.enforce(
                    list(dict.fromkeys(_scope._uuid_values(options))))
            if tab.locked:
                return {"status": "error",
                        "message": "the dashboard '%s' is locked — the UI hides the "
                                   "add-widget control on a locked dashboard, so "
                                   "adding one here would bypass a deliberate "
                                   "choice. Ask the user to unlock it first."
                                   % tab.name}

            catalog = cls._widget_catalog()
            info = catalog.get(widget_type)
            if not info:
                return {"status": "error",
                        "message": "unknown widget type '%s'" % widget_type,
                        "available": sorted(catalog)}

            clean, errors = cls._coerce_widget_options(info, options)
            if errors:
                return {"status": "error", "message": "; ".join(errors),
                        "option_schema": cls._widget_option_schema(info)}

            # 기본 옵션은 위젯 자신의 스키마에서 만든다. 폼이 없을 때
            # custom_options_return_json 이 default_value/타입별 기본을 채운다 —
            # 여기서 빈 dict 로 시작하면 위젯이 없는 키를 읽고 렌더에서 죽는다.
            err, defaults_json = custom_options_return_json(
                [], catalog, None, device=widget_type, use_defaults=True)
            try:
                merged = json.loads(defaults_json)
            except Exception:
                merged = {}
            merged.update(clean)

            new_widget = Widget()
            new_widget.tab_id = tab_id
            new_widget.graph_type = widget_type
            new_widget.name = (name or '').strip() or str(
                info.get('widget_name') or widget_type)
            new_widget.width = int(width) if width else (info.get('widget_width') or 6)
            new_widget.height = int(height) if height else (info.get('widget_height') or 6)
            # 모바일 전체 폭은 위젯 행의 설정이다(P6-63). 웹의 위젯 추가 폼과
            # 같은 기본값을 쓴다 — 위젯 종류가 그렇게 선언했거나, 폭이 24열의
            # 절반을 넘거나. 여기서 안 채우면 AI 가 만든 지도·달력이 폰에서
            # 반 폭으로 접힌 채 놓인다.
            new_widget.mobile_full_width = bool(
                info.get('mobile_full_width') or new_widget.width > 12)
            # 새 위젯은 그 탭의 맨 아래에. 기존 위젯 위에 겹쳐 놓으면 사람이
            # 지금 보고 있는 화면이 재배치된다.
            bottom = 0
            for each in Widget.query.filter(Widget.tab_id == tab_id).all():
                bottom = max(bottom, (each.position_y or 0) + (each.height or 0))
            new_widget.position_x = 0
            new_widget.position_y = bottom
            new_widget.custom_options = json.dumps(merged)

            creation_errors = []
            if 'execute_at_creation' in info:
                creation_errors, new_widget = info['execute_at_creation'](
                    creation_errors, new_widget, info)
                if creation_errors:
                    return {"status": "error",
                            "message": "; ".join(str(e) for e in creation_errors)}

            new_widget.save()

            # 그 종류가 이 시스템에 처음 놓인 위젯이면 Flask 가 아직 그 템플릿을
            # 모른다. 웹 UI 는 이때 재시작을 안내한다(reload_flask) — 여기서
            # 마음대로 재시작하면 화면을 보고 있는 사람의 세션이 끊기므로,
            # 사실만 알리고 결정은 사람에게 남긴다.
            first_of_type = Widget.query.filter(
                Widget.graph_type == widget_type).count() == 1

            warnings = []
            try:
                from aot.utils.widget_generate_html import generate_widget_html
                generate_widget_html()
            except Exception as exc:
                logger.warning("[widget] 템플릿 재생성 실패: %s", exc)
                warnings.append("widget template regeneration failed: %s" % exc)

            note = cls._notify_daemon_widget('refresh', new_widget.unique_id)
            if note:
                warnings.append(note)

            out = {"status": "success", "widget_id": new_widget.unique_id,
                   "name": new_widget.name, "widget_type": widget_type,
                   "tab_id": tab_id}
            if first_of_type:
                out["requires_restart"] = True
                out["restart_note"] = (
                    "This is the first widget of this type on this system, so the web "
                    "service must be restarted before it renders. Tell the user; do "
                    "not restart anything yourself.")
            if warnings:
                out["warnings"] = warnings
            return out
        except Exception as e:
            logger.exception("Error in create_widget")
            return {"status": "error", "message": str(e)}

    @classmethod
    def set_tool_profile(cls, key_id=None, profile=None, modules=None,
                         link_id=None, **extra):
        """[쓰기] 이 연결의 API 키가 보여 줄 도구 묶음을 바꾼다. 사람 승인 필요.

        key_id 는 호출자가 고르지 않는다 — 실행층(tool_execution)이 인증된 연결의
        키로 덮어쓴다. 웹 승인 화면에서 실행될 때도 그 값이 저장된 인자에 실려
        있다. 바뀐 목록은 앱이 다시 연결하거나 새 대화를 열 때부터 보인다(이
        서버는 진행 중인 연결에 목록 변경을 알리지 않는다).

        인가 서버(OAuth)로 들어온 연결(claude.ai 원격 커넥터 등)은 키가 없다 —
        link_id(계정 연결 행)의 묶음을 바꾼다. 그 연결에서도 실행층이 인증된
        값으로 덮어쓴다. 운영·설정은 토큰 범위를 넘지 못한다(restrict_role)."""
        from aot.databases.models import MCPExternalAccount, User, UserAPIKey
        from aot.databases.models.user_api_key import tool_profile_columns
        from aot.tools import tool_registry as registry
        from aot.utils import audit
        if not key_id and not link_id:
            return {"status": "error", "message": (
                "This connection has no API key or linked account of its own "
                "(built-in AI or legacy key) — change the tool profile on the "
                "web: Settings > General > AI Tool List.")}
        value = (profile or '').strip().lower()
        if value == registry.TOOL_PROFILE_OPERATIONS and modules:
            value = registry.compose_tool_profile(modules)
        new_value = registry.parse_tool_profile(value)
        if new_value is None:
            return {"status": "error", "message": (
                "profile must be 'lite', 'operations' or 'configuration' "
                "(modules only with 'operations': %s)"
                % ", ".join(registry.TOOL_MODULES))}
        if not key_id:
            link = MCPExternalAccount.query.filter(
                MCPExternalAccount.id == link_id).first()
            if link is None:
                return {"status": "error", "message": "Linked account not found."}
            before = link.tool_profile or '(token scope)'
            link.tool_profile = new_value
            db.session.commit()
            owner = User.query.filter(User.id == link.user_id).first()
            audit.audit_log(audit.API_KEY_PROFILE_CHANGE, target_type='User',
                            target_id=owner.unique_id if owner else None,
                            target_name=owner.name if owner else None,
                            detail='linked account: %s' % (link.label or link.issuer),
                            before={'tool_profile': before},
                            after={'tool_profile': new_value})
            return cls._tool_profile_result(
                {"status": "success", "account": link.label or link.issuer},
                before, new_value,
                "The new tool list applies when a new chat starts — tell the user "
                "to start one. 'operations' and 'configuration' never go beyond what "
                "the sign-in token allows: without setup access in the token the "
                "connection stays 'operations'.")
        row = UserAPIKey.query.filter(UserAPIKey.unique_id == key_id).first()
        if row is None or row.revoked_at is not None:
            return {"status": "error", "message": "API key not found."}
        before = row.tool_profile_spec
        row.tool_profile, row.tool_modules = tool_profile_columns(new_value)
        db.session.commit()
        owner = User.query.filter(User.id == row.user_id).first()
        audit.audit_log(audit.API_KEY_PROFILE_CHANGE, target_type='User',
                        target_id=owner.unique_id if owner else None,
                        target_name=owner.name if owner else None,
                        detail=row.name or None,
                        before={'tool_profile': before},
                        after={'tool_profile': row.tool_profile_spec})
        return cls._tool_profile_result(
            {"status": "success", "key": row.name}, before, row.tool_profile_spec,
            "The new tool list applies after the app reconnects or a new chat "
            "starts — tell the user to do that.")

    @staticmethod
    def _tool_profile_result(out, before, after, note):
        """set_tool_profile 응답 — 켜진 모듈을 싣고, 같은 값이면 바뀐 것이 없다고 말한다.

        2026-10-28 점검: before·after 가 같은데 성공만 나와 모델이 반영된 줄 알았고,
        켜진 모듈이 없어 무엇이 열렸는지 응답으로 알 수 없었다."""
        from aot.tools import tool_registry as registry
        out["tool_profile"] = {"before": before, "after": after}
        out["modules_on"] = [m for m in registry.TOOL_MODULES
                             if m in registry.profile_modules(after)]
        if before == after:
            out["changed"] = False
            out["note"] = ("Nothing changed — it already was '%s'. If a tool is still "
                           "missing, the tool list has not refreshed: reconnect or "
                           "start a new chat." % after)
        else:
            out["note"] = note
        return out

    @classmethod
    def modify_widget(cls, widget_id=None, name=None, options=None, width=None,
                      height=None, position_x=None, position_y=None,
                      tab_id=None, **extra):
        """[쓰기] 위젯의 이름·크기·위치·탭·설정을 바꾼다. 사람 승인 필요.

        준 것만 바꾼다 — 빠진 인자는 "비우라"가 아니라 "그대로 두라"다.
        """
        try:
            import json
            from aot.databases.models import Dashboard, Widget

            if not widget_id:
                return {"status": "error", "message": "widget_id is required"}
            w = Widget.query.filter(Widget.unique_id == widget_id).first()
            if not w:
                return {"status": "error", "message": "no widget with id %s" % widget_id}
            # 쓰기 시점 그룹 스코프 — 위젯이 놓인 대시보드로 묻는다.
            from aot.aot_flask.access import write_scope
            write_scope.enforce(w)

            catalog = cls._widget_catalog()
            info = catalog.get(w.graph_type)
            changed = []
            form_only_warning = None

            # 잠금은 **레이아웃**을 지킨다 — 잠긴 대시보드에서 UI 는 이동·크기
            # 조정을 막는다(gs-no-move/gs-no-resize). 이름과 설정까지 막지는
            # 않으므로 여기서도 막지 않는다: 통째로 거부하면 잠가 둔 화면의
            # 값을 고치는 정상 작업이 함께 불가능해진다.
            if any(v is not None for v in (width, height, position_x, position_y)):
                board = Dashboard.query.filter(
                    Dashboard.unique_id == w.tab_id).first()
                if board is not None and board.locked:
                    return {"status": "error",
                            "message": "the dashboard '%s' is locked, so this "
                                       "widget's size and position cannot be "
                                       "changed. Its name and settings still can."
                                       % board.name}

            if name is not None:
                w.name = str(name).strip()
                changed.append('name')
            for attr, value in (('width', width), ('height', height),
                                ('position_x', position_x), ('position_y', position_y)):
                if value is not None:
                    try:
                        setattr(w, attr, int(value))
                    except (TypeError, ValueError):
                        return {"status": "error",
                                "message": "%s must be an integer" % attr}
                    changed.append(attr)

            if tab_id is not None and tab_id != w.tab_id:
                # 대시보드 탭은 Dashboard 테이블이다(list_dashboards 주석 참조).
                target = Dashboard.query.filter(Dashboard.unique_id == tab_id).first()
                if not target:
                    return {"status": "error",
                            "message": "no dashboard with id %s" % tab_id}
                write_scope.enforce(target)   # 옮겨 갈 대시보드도
                if target.locked:
                    return {"status": "error",
                            "message": "the target dashboard '%s' is locked"
                                       % target.name}
                w.tab_id = tab_id
                changed.append('tab_id')

            if options:
                if not info:
                    return {"status": "error",
                            "message": "widget type '%s' is not installed here, so "
                                       "its options cannot be validated" % w.graph_type}
                clean, errors = cls._coerce_widget_options(info, options)
                if errors:
                    return {"status": "error", "message": "; ".join(errors),
                            "option_schema": cls._widget_option_schema(info)}
                try:
                    current = json.loads(w.custom_options or '{}')
                except Exception:
                    current = {}
                new_options = dict(current)
                new_options.update(clean)

                # 위젯이 자기 훅을 갖고 있으면 그것을 지나야 한다 — 웹 UI 의 AJAX
                # 저장 경로(save_widget_custom_options)와 같은 계약이다. 건너뛰면
                # 필드 매핑이나 파생값이 빠진 채 저장돼, 저장은 됐는데 화면은
                # 다르게 나오는 상태가 된다.
                hook = info.get('execute_at_modification')
                if hook is not None and _hook_reads_form(hook):
                    # 웹 폼 전용 훅(그래프의 y축·색, 공지의 카테고리 …)은 폼 입력
                    # 에서 값을 **다시 계산**한다 — 폼 없이 부르면 죽고(None),
                    # 빈 폼을 주면 그 설정을 지운다. 건너뛰고 그 값들은 그대로 둔다.
                    form_only_warning = (
                        "This widget type recomputes some settings only from the "
                        "web form (e.g. graph axis/colour options); those were "
                        "left as they were. Change them on the dashboard.")
                elif hook is not None:
                    (allow, _page_refresh, w, final) = hook(
                        w, None, current, new_options)
                    if not allow:
                        return {"status": "error",
                                "message": "the widget rejected this change "
                                           "(execute_at_modification)"}
                    new_options = final
                w.custom_options = json.dumps(new_options)
                changed.append('options')

            if not changed:
                return {"status": "error",
                        "message": "nothing to change — pass at least one of name, "
                                   "options, width, height, position_x, position_y, "
                                   "tab_id"}

            db.session.commit()
            out = {"status": "success", "widget_id": widget_id, "changed": changed}
            warnings = [form_only_warning] if form_only_warning else []
            note = cls._notify_daemon_widget('refresh', widget_id)
            if note:
                warnings.append(note)
            if warnings:
                out["warnings"] = warnings
            return out
        except Exception as e:
            logger.exception("Error in modify_widget")
            db.session.rollback()
            return {"status": "error", "message": str(e)}

    @classmethod
    def delete_widget(cls, widget_id=None, **extra):
        """[쓰기] 위젯을 대시보드에서 지운다. 사람 승인 필요."""
        try:
            from aot.databases.models import Widget

            if not widget_id:
                return {"status": "error", "message": "widget_id is required"}
            w = Widget.query.filter(Widget.unique_id == widget_id).first()
            if not w:
                return {"status": "error", "message": "no widget with id %s" % widget_id}
            # 쓰기 시점 그룹 스코프 — 위젯이 놓인 대시보드로 묻는다.
            from aot.aot_flask.access import write_scope
            write_scope.enforce(w)

            removed = cls._widget_brief(w)
            catalog = cls._widget_catalog()
            info = catalog.get(w.graph_type)

            # 위젯이 자기 뒷정리를 갖고 있으면 먼저 부른다(웹 UI 와 같은 순서).
            # 행을 지운 뒤에 부르면 훅이 참조할 대상이 이미 없다.
            warnings = []
            if info and 'execute_at_deletion' in info:
                try:
                    info['execute_at_deletion'](widget_id)
                except Exception as exc:
                    logger.warning("[widget] execute_at_deletion 실패: %s", exc)
                    warnings.append("the widget's own cleanup failed: %s" % exc)

            db.session.delete(w)
            db.session.commit()

            note = cls._notify_daemon_widget('remove', widget_id)
            if note:
                warnings.append(note)
            out = {"status": "success", "deleted": removed}
            if warnings:
                out["warnings"] = warnings
            return out
        except Exception as e:
            logger.exception("Error in delete_widget")
            db.session.rollback()
            return {"status": "error", "message": str(e)}

    @classmethod
    def list_tabs(cls, page_type=None, **extra):
        """[읽기전용] 탭 목록 — Input/Output/Function/Programs 화면이 공유하는
        같은 탭 인프라(`TabService`)를 그대로 쓴다.

        **대시보드만 예외다.** 대시보드 탭의 정본은 `Tab` 이 아니라 `Dashboard`
        테이블이고(`list_dashboards` 주석 참조), `Tab` 에는 `page_type=
        'dashboard'` 행이 아예 없다. 그런데 'dashboard' 는 `TAB_PAGE_TYPES` 의
        유효값이라, 예전에는 이 조회가 **`status: success` + 빈 목록**을 돌려
        줬다 — 실측(로컬): 위젯 16개짜리 '김제' 를 포함해 대시보드 11개가
        멀쩡히 있는데도 `{"tabs": []}`. 에러도 아니고 경고도 아닌 "없음" 이라
        읽는 쪽에서 의심할 자리가 없었다.

        그래서 대시보드는 정본 테이블에서 읽어 준다. 어느 도구를 골랐는지에
        따라 사실이 달라지지 않게 하는 것 — 같은 파일의
        `[WEATHER_TOOL_UNIFICATION]` 이 이미 세운 원칙이다.
        """
        try:
            from aot.services.tab_service import TabService, TAB_PAGE_TYPES

            if page_type not in TAB_PAGE_TYPES:
                return {"status": "error",
                        "message": "page_type must be one of %s" % (TAB_PAGE_TYPES,)}

            if page_type == 'dashboard':
                from sqlalchemy import text
                from aot.databases.models import Dashboard
                boards = Dashboard.query.order_by(
                    text("COALESCE(sort_order, 999999), id")).all()
                return {
                    "status": "success",
                    "tabs": [{"unique_id": b.unique_id, "name": b.name,
                              "position": b.sort_order} for b in boards],
                    "note": ("Dashboard tabs are kept in their own registry, not "
                             "in the shared tab table — these rows come from "
                             "there. call list_dashboards for the widgets on "
                             "each."),
                }

            tabs = TabService.get_tabs_for_page(page_type)
            return {"status": "success",
                    "tabs": [{"unique_id": t.unique_id, "name": t.name,
                             "position": t.position} for t in tabs]}
        except Exception as e:
            logger.exception("Error in list_tabs")
            return {"status": "error", "message": str(e)}

    @classmethod
    def create_tab(cls, page_type=None, name=None, **extra):
        """[쓰기] 새 탭을 만든다. 사람 승인 필요."""
        try:
            from aot.services.tab_service import TabService, TAB_PAGE_TYPES

            if page_type not in TAB_PAGE_TYPES:
                return {"status": "error",
                        "message": "page_type must be one of %s" % (TAB_PAGE_TYPES,)}
            tab = TabService.create_tab(page_type, name)
            if not tab:
                return {"status": "error", "message": "tab creation failed"}
            return {"status": "success", "tab_id": tab.unique_id, "name": tab.name}
        except Exception as e:
            logger.exception("Error in create_tab")
            return {"status": "error", "message": str(e)}

    @classmethod
    def modify_tab(cls, tab_id=None, name=None, **extra):
        """[쓰기] 탭 이름을 바꾼다. 사람 승인 필요."""
        try:
            from aot.services.tab_service import TabService

            if not tab_id or not (name or '').strip():
                return {"status": "error",
                        "message": "tab_id and name are required"}
            # 쓰기 시점 그룹 스코프 — 탭은 그 자신이 부여 단위다.
            from aot.aot_flask.access import write_scope
            write_scope.enforce(('Tab', tab_id))
            ok = TabService.rename_tab(tab_id, name)
            if not ok:
                return {"status": "error", "message": "rename failed — tab not found?"}
            return {"status": "success", "tab_id": tab_id, "name": name}
        except Exception as e:
            logger.exception("Error in modify_tab")
            return {"status": "error", "message": str(e)}

    @classmethod
    def delete_tab(cls, tab_id=None, **extra):
        """[쓰기] 탭을 삭제한다. 사람 승인 필요.

        Input/Output/Function 은 소속 카드까지 함께 삭제된다(UI와 동일). Programs
        는 예외 — 소속 프로그램은 다른 구획이 계속 참조할 수 있어 지우지 않고
        기본 탭으로 옮겨진다. 마지막 남은 탭은 지울 수 없다.
        """
        try:
            from aot.services.tab_service import TabService

            if not tab_id:
                return {"status": "error", "message": "tab_id is required"}
            # 쓰기 시점 그룹 스코프 — 탭은 그 자신이 부여 단위다.
            from aot.aot_flask.access import write_scope
            write_scope.enforce(('Tab', tab_id))
            result = TabService.delete_tab(tab_id)
            if not result.get('success'):
                return {"status": "error", "message": result.get('message')}
            return {"status": "success", "deleted": tab_id}
        except Exception as e:
            logger.exception("Error in delete_tab")
            return {"status": "error", "message": str(e)}

