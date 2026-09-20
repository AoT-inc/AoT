import logging

logger = logging.getLogger(__name__)


from aot.aot_flask.extensions import db
from aot.databases.models import AITask
from aot.databases.models import GeoShape
from aot.databases.models import Misc
from aot.databases.models import Notes
from aot.utils.time_utils import serialize_ts
from datetime import timedelta


class SystemToolsMixin:

    @classmethod
    def open_drawer(cls, drawer=None, **extra):
        """[읽기전용] 서랍을 열어 그 안 도구들의 정의를 돌려준다.

        매니페스트에는 자주 쓰는 도구만 싣고 나머지는 서랍에 둔다. 이 도구가
        그 서랍을 여는 유일한 수단이다 — 그래서 절대 서랍 안으로 내려가지
        않는다(`never_demote`, 가드가 고정한다).

        모르는 이름이면 **오류가 아니라 목록을 돌려준다.** 서랍 이름을 틀렸을
        때 "없다" 로 끝내면 LLM 이 포기하는데, 목록을 주면 다시 고를 수 있다.
        """
        from aot.tools import tool_registry as registry

        known = registry.DRAWERS
        if not drawer or drawer not in known:
            return {
                "error": ("unknown drawer: %s" % drawer) if drawer
                         else "drawer is required",
                "drawers": registry.drawer_index(),
            }

        names = set(registry.tools_in_drawer(drawer))
        tools = [dict(t.manifest) for t in registry.TOOLS
                 if t.manifest and t.name in names]
        return {"drawer": drawer, "description": known[drawer],
                "count": len(tools), "tools": tools}

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
            from aot.utils.device_tz import resolve_location_tz
            from datetime import datetime as _dt, timezone as _tzinfo

            resolved_name = None
            if not target_id and target_name:
                target_id, _tt, resolved_name, _lat, _lng = \
                    cls._resolve_note_target(target_name)
                if not target_id:
                    return {
                        "status": "success",
                        "message": (f"위치 '{target_name}'를 찾지 못해 농장 기본 시간대로 "
                                    f"응답합니다."),
                        "available_targets": cls._geoshape_name_candidates(),
                        "location": "farm-wide (default)",
                        "timezone": str(resolve_location_tz(None)),
                        "local_time": _dt.now(_tzinfo.utc).astimezone(
                            resolve_location_tz(None)).strftime('%Y-%m-%d %H:%M:%S'),
                        "sun": cls._sun_block(None, resolve_location_tz(None)),
                    }

            tz = resolve_location_tz(target_id)
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
            from aot.utils.time_utils import utc_now

            cutoff = utc_now() - timedelta(minutes=int(lookback_minutes))

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
                    "created_at": serialize_ts(t.created_at) if t.created_at else None,
                })

            # 2. Query MCP server status
            mcp_status = []
            try:
                from aot.databases.models import MCPServer
                active_ids = providers.get('mcp_active_server_ids')()
                all_servers = MCPServer.query.filter_by(is_activated=True).all()
                for srv in all_servers:
                    _is_degraded = srv.unique_id not in active_ids
                    mcp_status.append({
                        "name": srv.name,
                        "unique_id": srv.unique_id,
                        "is_degraded": _is_degraded,
                        "has_tool": tool_name in (srv.tool_names or []) if tool_name else None,
                    })
            except Exception as _mcp_err:
                logger.warning(f"[031_STEP_3] Could not query MCP status: {_mcp_err}")
                mcp_status = [{"error": str(_mcp_err)}]

            # 3. Build failure summary
            failure_reasons = []
            if not [s for s in mcp_status if not s.get('is_degraded') and not s.get('error')]:
                failure_reasons.append("All MCP servers are offline or unreachable.")
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
    def get_tool_detail_tool(cls, tool_name=None, **extra):
        """@ANCHOR: AGENT_LOOP_GET_TOOL_DETAIL — full description + argument schema
        for ONE tool by name (Phase 1 agent loop, docs/design/ai-agent-loop.md §4).
        The lean catalog shown every step is name + one-line description only, to
        keep prompts small; this expands one entry on demand."""
        if not tool_name:
            return {"error": "tool_name is required"}
        from aot.tools.tool_registry import TOOLS
        for t in TOOLS:
            if t.name == tool_name.strip():
                if not t.manifest:
                    return {"tool_name": t.name, "detail": "No extended schema recorded for this tool."}
                return {"tool_name": t.name, "detail": dict(t.manifest)}
        return {"error": f"Unknown tool: {tool_name}"}

    @classmethod
    def list_pending_confirmations(cls, **extra):
        """[읽기전용] 지금 사람 승인을 기다리는 쓰기/제어 요청 목록. 이전 도구 호출이
        'pending_approval'을 반환했을 때, confirmation_id를 다시 찾거나 사용자에게
        무엇이 대기 중인지 보여줄 때 쓴다. 승인/거부 자체는 respond_to_confirmation을
        쓴다."""
        try:
            from aot.tools import mcp_safety_gate as gate
            return {"pending": gate.list_pending()}
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

        target_id, target_type, resolved_name, _lat, _lng = \
            cls._resolve_note_target(target_name)

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
        # 구역도 컨테이너다 — 그 안에 식생 구획이 들어 있고, 그 구획이 자기
        # 노트·일정을 갖는다. site 만 펼치던 때는 "3-1 에 무엇이 있나" 에
        # 답할 수 없었고, 작업을 구획별로 나눠 걸어야 할 때 AI 가 그 존재를
        # 몰랐다.
        if target_type in ('site', 'zone'):
            try:
                _root = GeoShape.query.filter_by(unique_id=target_id).first()
                if _root is not None:
                    from aot.utils.geo_hierarchy import _plot_ids_inside
                    from aot.databases.models import GeoPlot
                    _ids = [_root.unique_id] + [
                        c.unique_id for c in
                        cls._geo_shape_descendants(_root)
                        if c.unique_id]
                    for _pid in _plot_ids_inside(
                            _ids, geo_ids={_root.geo_id} if _root.geo_id else None):
                        _pl = GeoPlot.query.filter_by(unique_id=_pid).first()
                        if _pl is None:
                            continue
                        _pn = _pl.name or _pl.subject
                        if _pn:
                            children.append({"name": _pn, "type": "plot"})
            except Exception:
                pass
        if target_type == 'site':
            try:
                site_shape = GeoShape.query.filter_by(unique_id=target_id).first()
                if site_shape:
                    seen_names = set()
                    for c in cls._geo_shape_descendants(site_shape):
                        # geo_descendant_shapes() returns the FULL nested subtree
                        # (zones, device markers, labels, ...) - only the immediate
                        # 'zone' level answers "does this container have sub-zones
                        # to loop over"; devices/labels would just be noise here.
                        if c.type != 'zone':
                            continue
                        c_name = c.name or None
                        if c_name and c_name not in seen_names:
                            seen_names.add(c_name)
                            children.append({"name": c_name, "type": c.type})
            except Exception:
                pass

        note = (
            "This name resolves to exactly one entity. A write tool called with "
            "this target_name attaches ONLY to it."
        ) if not children else (
            "This name resolves to a container whose sub-entities are listed in "
            "'children'. A write tool called with this target_name attaches ONLY "
            "to the container itself - it does NOT automatically apply to each "
            "child. If the request applies to each child separately (e.g. 'each "
            "zone', 'per section'), call the write tool once per entry in "
            "'children', using that child's exact name as target_name."
        )

        return {
            "status": "success",
            "target_id": target_id,
            "target_type": target_type,
            "resolved_name": resolved_name,
            "children": children,
            "note": note,
        }

    @classmethod
    def _forecast_is_usable(cls):
        """지금 쓸 만한 예보가 있는가. 파일이 없거나 낡았으면 False.

        브리핑이 예보 도구를 **안내할지 말지** 정하는 데 쓴다. 예보가 죽은
        시스템에 "예보를 확인하라" 고 적어 두면 읽는 AI 는 매 대화마다 그것을
        부르고, 매번 같은 "오래된 예보" 보고가 사용자에게 나간다.
        """
        try:
            from aot.functions.utils.env_control.forecast_feedforward import _load_forecast
            from aot.utils.timekit import as_tz, utc_now as _utc_now
            from datetime import datetime as _dt2
            data = _load_forecast() or {}
            if not (data.get('forecasts') or {}):
                return False
            pub_raw = data.get('pub_dt')
            if not pub_raw:
                return False
            pub = as_tz('Asia/Seoul').localize(
                _dt2.strptime(str(pub_raw), '%Y%m%d%H%M'))
            age_h = (_utc_now() - pub).total_seconds() / 3600.0
            return age_h <= cls._FORECAST_UNUSABLE_H
        except Exception:                                   # noqa: BLE001
            return False

    @classmethod
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
            tree = S.get_spatial_tree(depth=2) or {}
            nodes = tree.get("hierarchy") or []
            by_type, names = {}, {}
            def _walk(items):
                for n in items:
                    t = n.get("type") or "unknown"
                    by_type[t] = by_type.get(t, 0) + 1
                    # 장치는 이름을 싣지 않는다 — 수가 많고 get_device_list 가 있다.
                    if t in ("site", "zone", "facility") and n.get("name"):
                        names.setdefault(t, []).append(n["name"])
                    _walk(n.get("children") or [])
            _walk(nodes)
            return {"counts": by_type,
                    "names": {k: _capped(v) for k, v in names.items()},
                    "see": "get_spatial_tree for the tree with devices"}

        def _crops_summary():
            cs = S.get_crop_status() or {}
            open_plots = cs.get("open_field_plots") or []
            bay_plots = cs.get("facility_bay_plots") or []
            subjects = []
            for p in list(open_plots) + list(bay_plots):
                sub = p.get("crop") or p.get("subject")
                if sub and sub not in subjects:
                    subjects.append(sub)
            # `plot_count` 를 원본에서 그대로 가져오면 안 된다 — 그 값은 노지만
            # 세므로 시설 구획과 더하면 합이 맞지 않는다(실측: 39 / 39 / 5).
            return {
                "plot_count": len(open_plots) + len(bay_plots),
                "open_field": len(open_plots),
                "in_facility": len(bay_plots),
                "subjects": _capped(subjects),
                # 시설은 몇 개뿐이고 작물·단계가 붙어 있어 그대로 둔다.
                "facilities": cs.get("facilities") or [],
                "see": "get_crop_status for every plot with its stage and guidance",
            }

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
        # 이상 상태는 요약하지 않는다 — 작고(348토큰), 이 도구의 존재 이유에
        # 가장 가까운 부분이다.
        brief["anomalies"] = _safe("이상 상태", lambda: S.get_anomalies())
        # 핸들러 이름은 get_device_list_tool 이다(도구명과 다름). _safe 가 예외를
        # 처리하므로 hasattr 류의 방어 가드는 두지 않는다 — 가드를 두면 이름이
        # 틀렸을 때 조용히 빈 값이 되어 오히려 사실을 감춘다.
        # 집계의 정의를 응답에 함께 싣는다. 이 수(63)는 get_anomalies 의
        # metrics.total_devices(32)와 **다른 것을 센다** — 여기는 Input+Output+
        # Camera+복합장치 전부, 저기는 Input 만이다. 정의를 안 적어 두면 둘을
        # 나란히 본 AI 가 "장치 31개가 사라졌다" 로 읽는다(2026-08-17 실제 혼동).
        def _device_summary():
            _res = (S.get_device_list_tool() or {}).get("results") or []
            _by_type = {}
            for _r in _res:
                _t = _r.get("type") or "unknown"
                _by_type[_t] = _by_type.get(_t, 0) + 1
            return {
                "device_count": len(_res),
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
                    "original table. Do not tell the user a document was archived unless "
                    "it appears in search_archives.")
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
    def list_dashboards(cls, tab_id=None, with_options=False, **extra):
        """[읽기전용] 대시보드 탭과 그 안의 위젯들.

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

            out = []
            for tab in tabs:
                widgets = (Widget.query.filter(Widget.tab_id == tab.unique_id)
                           .order_by(Widget.position_y, Widget.position_x).all())
                entries = []
                for w in widgets:
                    brief = cls._widget_brief(
                        w, catalog.get(w.graph_type))
                    if w.graph_type not in catalog:
                        brief['warning'] = ('this widget type is not installed on '
                                            'this system — it will not render')
                    if with_options:
                        try:
                            brief['options'] = json.loads(w.custom_options or '{}')
                        except Exception:
                            brief['options'] = {}
                    entries.append(brief)
                entry = {'tab_id': tab.unique_id, 'name': tab.name,
                         'position': tab.sort_order,
                         'widget_count': len(entries), 'widgets': entries}
                if tab.locked:
                    entry['locked'] = True
                out.append(entry)
            return {"status": "success", "tabs": out}
        except Exception as e:
            logger.exception("Error in list_dashboards")
            return {"status": "error", "message": str(e)}

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

            catalog = cls._widget_catalog()
            info = catalog.get(w.graph_type)
            changed = []

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
                if 'execute_at_modification' in info:
                    (allow, _page_refresh, w, final) = info['execute_at_modification'](
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
            note = cls._notify_daemon_widget('refresh', widget_id)
            if note:
                out["warnings"] = [note]
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
            result = TabService.delete_tab(tab_id)
            if not result.get('success'):
                return {"status": "error", "message": result.get('message')}
            return {"status": "success", "deleted": tab_id}
        except Exception as e:
            logger.exception("Error in delete_tab")
            return {"status": "error", "message": str(e)}

