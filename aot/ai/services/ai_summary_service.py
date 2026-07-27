# coding=utf-8
import logging
import json
from datetime import datetime, timedelta
from aot.utils.time_utils import get_local_now, utc_now, to_local, serialize_ts
from typing import Optional, Dict, Any, List
from sqlalchemy import desc

from aot.aot_flask.extensions import db
from aot.databases.models.ai_summary import AISystemSummary
# @ANCHOR: DECOUPLED_VIA_AI_CALLER_INTERFACE (IMP-007)
# AIAgentService accessed via lazy imports inside each method to prevent
# circular dependency. Top-level import removed per SBS-002_V2.

logger = logging.getLogger(__name__)

class AISummaryService:
    """
    v26.0: Core service for generating hierarchical system summaries (Semantic Snapshots).
    Includes incremental update logic and AI coordination.

    @phase active
    @stability unstable
    @dependency AISystemSummary
    """

    @staticmethod
    def get_latest_summary(scope_type: str = 'system', scope_id: Optional[str] = None) -> Optional[AISystemSummary]:
        """Retrieve the most recent active summary for a given scope."""
        query = AISystemSummary.query.filter_by(
            scope_type=scope_type,
            scope_id=scope_id,
            is_active=True
        ).order_by(desc(AISystemSummary.timestamp))
        return query.first()

    @staticmethod
    def should_generate_new_summary(
        scope_type: str, 
        scope_id: Optional[str], 
        current_metrics: Dict[str, Any],
        threshold: float = 0.05
    ) -> bool:
        """
        Incremental Logic: Check if metrics have deviated enough to warrant a new summary.
        Default threshold is 5% deviation.
        """
        latest = AISummaryService.get_latest_summary(scope_type, scope_id)
        if not latest:
            return True # First run
        
        # Check time interval (minimum 1 hour unless forced)
        if utc_now().replace(tzinfo=None) - latest.timestamp < timedelta(hours=1):
            return False

        try:
            prev_metrics = json.loads(latest.metadata_json) if latest.metadata_json else {}
        except:
            return True

        # Simplified deviation check for key metrics (e.g., active devices, error rates)
        # Note: Detailed implementation will depend on gathered data structure
        for key in ['active_devices', 'error_rate', 'total_count']:
            if key in current_metrics and key in prev_metrics:
                prev_val = prev_metrics[key]
                curr_val = current_metrics[key]
                if prev_val == 0:
                    if curr_val > 0: return True
                    continue
                
                deviation = abs(curr_val - prev_val) / prev_val
                if deviation > threshold:
                    logger.info(f"Summary trigger: Metric '{key}' deviated by {deviation:.2%}")
                    return True
        
        return False

    @staticmethod
    def gather_scope_data(scope_type: str, scope_id: Optional[str]) -> Dict[str, Any]:
        """
        Collect system state data for the specified scope.
        Implement hierarchical data aggregation logic (System > Farm > Zone > Facility > Device).
        """
        from aot.databases.models import Input, GeoMap, GeoShape, DeviceMeasurements, GeoFacility

        data = {
            'timestamp': utc_now().isoformat(),
            'scope_type': scope_type,
            'scope_id': scope_id,
            'metrics': {
                'total_devices': 0,
                'active_devices': 0,
                'total_measurements': 0,
                'active_measurements': 0,
                'error_rate': 0.0
            },
            'structure': {},
            'recent_events': [],
            'env_control': None,
        }

        # 1. Base Query for Inputs (Devices) based on scope
        query = Input.query
        facility = None
        if scope_type == 'farm' and scope_id:
            query = query.filter(Input.map_config_id == scope_id)
        elif scope_type == 'device_group' and scope_id:
            query = query.filter(Input.map_overlay_id == int(scope_id))
        elif scope_type == 'device' and scope_id:
            query = query.filter(Input.unique_id == scope_id)
        elif scope_type == 'facility' and scope_id:
            # @ANCHOR: GATHER_SCOPE_FACILITY [multi-site fix, 2026-07-07]
            # Previously had NO branch for 'facility' at all — the query ran
            # unfiltered, so a per-facility summary was silently built from
            # every device in the whole installation (Context Broadcast calls
            # this once per active facility, so multi-site installs got the
            # same global numbers repeated under each facility's summary).
            # scope_id is expected to be a GeoFacility.unique_id — the
            # convention this AI subsystem uses throughout for "which site".
            # See .local/plans/phase6_knowledge_digest_design.md (multi-site addendum).
            facility = GeoFacility.query.filter_by(unique_id=scope_id).first()
            device_ids = set()
            if facility:
                for s in (facility.sensors or []):
                    if s.get('device_id'):
                        device_ids.add(s['device_id'])
                for f in (facility.fittings or []):
                    if f.get('input_id'):
                        device_ids.add(f['input_id'])
                    if f.get('actuator_id'):
                        device_ids.add(f['actuator_id'])
            # .in_() on an empty set correctly yields zero rows (not "all
            # rows") — an unresolvable facility_id must never fall back to
            # the whole system.
            query = query.filter(Input.unique_id.in_(device_ids))

        devices = query.all()
        data['metrics']['total_devices'] = len(devices)
        # NOTE: is_activated is the USER'S on/off intent, not reachability. A
        # device the operator switched off during maintenance is "not activated"
        # but perfectly healthy. This metric was previously consumed as if it
        # meant "offline" (ai_anomaly_detector), which raised connectivity
        # alarms whenever someone simply disabled a few devices.
        data['metrics']['active_devices'] = len([d for d in devices if d.is_activated])

        # Real communication state, from the daemon's comm_* contract
        # (io_link_health_infra_plan.md). Only devices that can actually observe
        # their own link are counted: a fire-and-forget output is not "online"
        # or "offline", it is unverifiable, and including it either way would
        # distort the ratio the anomaly detector thresholds on.
        comm_capable_count = 0
        comm_offline_count = 0
        try:
            from aot.aot_client import DaemonControl
            live = DaemonControl().input_status_all()  # {} if the daemon is down
            for d in devices:
                status = live.get(d.unique_id)
                if not status or not status.get('comm_capable'):
                    continue
                comm_capable_count += 1
                if status.get('comm_is_fault'):
                    comm_offline_count += 1
        except Exception as e:
            logger.warning(f"[SummaryService] Could not read device comm status: {e}")
        data['metrics']['comm_capable_devices'] = comm_capable_count
        data['metrics']['comm_offline_devices'] = comm_offline_count

        # 2. Gather measurements for these devices
        device_ids_list = [d.unique_id for d in devices]
        measurements = DeviceMeasurements.query.filter(DeviceMeasurements.device_id.in_(device_ids_list)).all()
        data['metrics']['total_measurements'] = len(measurements)
        data['metrics']['active_measurements'] = len([m for m in measurements if m.is_enabled])

        # 3. Structural Info (Site/Zone names)
        if scope_type == 'system':
            data['structure']['farms'] = [m.name for m in GeoMap.query.all()]
        elif scope_type == 'farm' and scope_id:
            farm = GeoMap.query.filter_by(unique_id=scope_id).first()
            data['structure']['farm_name'] = farm.name if farm else "Unknown"
            data['structure']['zones'] = [s.feature.get('properties', {}).get('name', 'Unnamed')
                                        for s in GeoShape.query.filter_by(geo_id=scope_id, type='zone').all()]
        elif scope_type == 'facility' and scope_id:
            data['structure']['facility_name'] = facility.name if facility else "Unknown"
            if facility:
                data['structure']['bay_count'] = facility.bay_count
            # Environment-control (env_coordinator) function config + latest
            # cycle's human-readable decision summary — lets advice cite real
            # setpoints/thresholds and WHY the controller is doing what it's
            # doing, instead of only device counts. None if no coordinator is
            # bound to this facility.
            data['env_control'] = AISummaryService._gather_env_control_context(scope_id)

        # 4. Error/Event Integration (Placeholder)
        # In a real scenario, we would query AITaskHistory or system logs

        return data

    @staticmethod
    def _gather_env_control_context(geo_facility_id: str) -> Optional[List[Dict[str, Any]]]:
        """Read every env_coordinator function bound to this facility (a
        multi-bay facility can have one coordinator per bay via bay_scope —
        see FUNCTION_INFORMATION 'bay_scope') plus its latest cycle's
        structured decision summary (targets actually applied, limiting
        factor, safety-gate status, actuator commands + reason codes).

        Read-only; never raises — returns None on any lookup failure so
        advice generation degrades gracefully to device-count-only context.
        See docs/ai/env-control.md and
        aot/functions/custom_functions/env_coordinator_impl/_cycle_mixin.py
        (_build_cycle_summary).
        """
        try:
            from aot.databases.models import CustomController, FunctionRuntimeState

            coordinators = CustomController.query.filter_by(
                device='env_coordinator', is_activated=True
            ).all()

            matched = []
            for c in coordinators:
                try:
                    opts = json.loads(c.custom_options) if c.custom_options else {}
                except (ValueError, TypeError):
                    continue
                if opts.get('geo_facility_id') == geo_facility_id:
                    matched.append((c, opts))
            if not matched:
                return None

            out = []
            for controller, opts in matched:
                entry = {
                    'function_name': controller.name,
                    'bay_scope': opts.get('bay_scope') or None,
                    'effect_engine': opts.get('effect_engine', 'legacy'),
                    'crop_preset': opts.get('crop_preset'),
                    'target_vpd_kpa': opts.get('target_vpd'),
                    'target_co2_ppm': opts.get('target_co2'),
                    'temp_range_c': [opts.get('temp_min'), opts.get('temp_max')],
                    'humid_range_pct': [opts.get('humid_min'), opts.get('humid_max')],
                    'guide_temp_range_c': [opts.get('guide_T_min'), opts.get('guide_T_max')],
                    'guide_humid_range_pct': [opts.get('guide_RH_min'), opts.get('guide_RH_max')],
                }
                state = FunctionRuntimeState.query.filter_by(function_id=controller.unique_id).first()
                if state and state.summary_json:
                    try:
                        entry['latest_cycle_summary'] = json.loads(state.summary_json)
                    except (ValueError, TypeError):
                        pass
                out.append(entry)
            return out
        except Exception as e:
            logger.debug(f"[AISummaryService] env_control context read failed: {e}")
            return None

    @staticmethod
    def generate_system_summary(
        agent_id: str = 'auto',
        scope_type: str = 'system',
        scope_id: Optional[str] = None,
        force: bool = False,
        domain_context: Optional[Dict[str, Any]] = None,
    ) -> Optional[AISystemSummary]:
        """
        Main entry point for generating a summary.
        Coordinates data gathering, incremental check, and AI generation via AIAgentService.

        `domain_context` is the facility's resolved domain module (crop,
        growth stage, pest/weather — DomainContextLoader.load_active_module)
        when the caller already has it, e.g. _context_broadcast_job's Step 3.
        Folded into the same prompt as gather_scope_data's device/env_control
        data so periodic advice can cite crop stage and pest/weather signals,
        not just device counts and control setpoints. None if the caller has
        no domain module for this scope (e.g. non-facility scopes, or a
        facility with nothing registered in the domain YAML registry).
        """
        # Check if AI features are enabled
        from aot.databases.models import AIGlobalSettings
        ai_settings = AIGlobalSettings.query.first()
        if not ai_settings or not ai_settings.ai_enabled:
            logger.info("AI features are disabled. Skipping summary generation.")
            return None

        current_data = AISummaryService.gather_scope_data(scope_type, scope_id)
        if domain_context:
            current_data['domain_context'] = domain_context

        # Incremental check using simplified metrics map
        check_metrics = {
            'active_devices': current_data['metrics']['active_devices'],
            'total_count': current_data['metrics']['total_devices'],
            'error_rate': current_data['metrics']['error_rate']
        }
        
        if not force and not AISummaryService.should_generate_new_summary(scope_type, scope_id, check_metrics):
            logger.debug(f"Skipping summary generation for {scope_type}:{scope_id} - no significant change.")
            return AISummaryService.get_latest_summary(scope_type, scope_id)

        start_time = utc_now()
        
        # 1. Select Agent
        agent = None
        if agent_id == 'auto':
            # Prefer 'synthesizer' or 'supervisor' for summarization
            from aot.databases.models import AIAgent
            agent = (AIAgent.query.filter_by(pipeline_role='synthesizer', is_activated=True).first() or
                     AIAgent.query.filter_by(role='supervisor', is_activated=True).first())
        else:
            from aot.databases.models import AIAgent
            agent = AIAgent.query.filter_by(unique_id=agent_id).first()
        
        if not agent:
            logger.error("No suitable AI agent found for summary generation.")
            return None

        # 2. Prepare Context & Prompt
        latest_summary = AISummaryService.get_latest_summary(scope_type, scope_id)
        prev_text = latest_summary.summary_text if latest_summary else "No previous summary available."
        
        # Token-optimized data injection (Token Diet)
        data_str = json.dumps(current_data, indent=2, ensure_ascii=False)
        if len(data_str) > 10000: # Simple threshold for POC
            # env_control[*].latest_cycle_summary is the largest, least
            # essential-to-truncate-first field (per-actuator command list) —
            # drop it before ever touching the setpoint/threshold values
            # above it, which are what makes a facility summary specific.
            logger.warning("Scope data too large, applying token diet (dropping cycle-summary detail).")
            env_control = current_data.get('env_control')
            if env_control:
                for entry in env_control:
                    entry.pop('latest_cycle_summary', None)
            data_str = json.dumps(current_data, indent=2, ensure_ascii=False)

        _env_control_directive = (
            "\n[환경 제어 근거]: 'env_control'에 이 시설의 환경제어(env_coordinator) 함수 설정과 "
            "최근 사이클의 실제 제어 근거(limiting_factor, deviation, gate 등)가 이미 포함되어 있습니다. "
            "장치 개수만으로 판단하지 말고, 이 설정값(목표 VPD/CO2/온습도 범위, 제어 모드)과 최근 판단 "
            "근거를 실제로 인용하여 왜 그렇게 판단했는지 설명하세요. 이 데이터에 없는 수치는 지어내지 마세요."
        ) if current_data.get('env_control') else ""

        _domain_context_directive = (
            "\n[도메인 맥락]: 'domain_context'에 이 시설에 등록된 작물/재배단계/병해충/날씨 정보가 "
            "이미 포함되어 있습니다. 이 정보를 근거로 현재 재배단계에 맞는 관찰이나 주의사항을 "
            "함께 언급하세요. 이 데이터에 없는 작물명이나 단계는 지어내지 마세요."
        ) if current_data.get('domain_context') else ""

        prompt = f"""
        당신은 AoT(AI of Things) 시스템의 상황 분석 전문가입니다.
        아래 데이터를 바탕으로 현재 시스템 상태에 대한 'Semantic Snapshot'(의미론적 요약)을 작성하세요.

        [범위]: {scope_type} ({scope_id if scope_id else '전체 시스템'})
        [이전 요약]: {prev_text}

        [현재 상태 데이터]:
        {data_str}
        {_env_control_directive}
        {_domain_context_directive}

        [지시사항]:
        1. 현재 시스템의 전반적인 건강 상태와 연결성을 평가하세요.
        2. 이전 상태와 비교하여 발생한 주요 변화(증분 변화)를 기술하세요.
        3. 주의가 필요한 잠재적 위험 요소나 이상 징후를 식별하세요.
        4. 사용자가 시스템의 상황을 한눈에 파악할 수 있도록 명확하고 전문적인 한국어로 작성하세요.

        응답은 자연어 요약문만 포함하세요.
        """

        try:
            from aot.ai.services.ai_agent_service import AIAgentService  # lazy — avoids circular import
            engine = AIAgentService.get_engine(agent.unique_id)
            if not engine:
                raise ValueError(f"Failed to initialize engine for agent {agent.unique_id}")
            
            # Context is minimal for snapshots to save tokens
            ai_context = {
                "current_time": get_local_now().strftime("%Y-%m-%d %H:%M:%S"),
                "scope_info": {"type": scope_type, "id": scope_id}
            }
            
            result = engine.run_reasoning(ai_context, prompt)
            summary_text = result.get('insight', '요약을 생성할 수 없습니다.')
            
            # Anomaly Detection Integration (Phase 26.3)
            from aot.ai.services.ai_anomaly_detector import AIAnomalyDetector
            anomaly_result = AIAnomalyDetector.detect_anomalies(current_data, latest_summary)
            
            new_summary = AISystemSummary(
                summary_text=summary_text,
                scope_type=scope_type,
                scope_id=scope_id,
                version=(latest_summary.version + 1) if latest_summary else 1,
                previous_summary_id=latest_summary.unique_id if latest_summary else None,
                generation_time_ms=int((utc_now() - start_time).total_seconds() * 1000),
                token_count=len(prompt.split()) + len(summary_text.split()), # Rough estimation
                metadata_json=json.dumps(current_data, ensure_ascii=False),
                anomaly_detected=anomaly_result.get('anomaly_detected', False),
                alert_level=anomaly_result.get('alert_level', 'none'),
                change_summary=json.dumps(anomaly_result.get('anomalies', []), ensure_ascii=False)
            )
            new_summary.save()
            
            # Trigger Alerts if needed (Phase 26.3)
            if new_summary.anomaly_detected:
                scope_info = {
                    "scope_type": scope_type,
                    "scope_id": scope_id,
                    "scope_name": current_data.get('name', scope_type)
                }
                AIAnomalyDetector.trigger_alerts(
                    anomaly_result,
                    scope_info,
                    summary_text=summary_text
                )
                # OI-02: trigger immediate context broadcast on warning/critical anomaly
                if anomaly_result.get('alert_level') in ('warning', 'critical'):
                    try:
                        from aot.ai.services.ai_scheduler_service import AISchedulerService
                        AISchedulerService.trigger_context_broadcast_now()
                    except Exception as _oi02_exc:
                        logger.warning("OI-02 context broadcast trigger failed: %s", _oi02_exc)

            # Redis Caching (Phase 26.4)
            from aot.ai.services.cache_manager import CacheManager
            CacheManager.set_latest_summary(scope_type, scope_id, new_summary)
            
            logger.info(f"Successfully generated summary v{new_summary.version} for {scope_type}")
            return new_summary
            
        except Exception as e:
            logger.error(f"Error during AI summary generation: {e}", exc_info=True)
            return None

    @staticmethod
    def get_summary_history(scope_type: str, scope_id: Optional[str], limit: int = 10) -> List[AISystemSummary]:
        """Retrieve recent summaries for a given scope."""
        return AISystemSummary.query.filter_by(
            scope_type=scope_type,
            scope_id=scope_id,
            is_active=True
        ).order_by(desc(AISystemSummary.timestamp)).limit(limit).all()

    @staticmethod
    def generate_comparison(summary_id_1: str, summary_id_2: str) -> Dict[str, Any]:
        """
        Use an AI agent to compare two snapshots and highlight critical changes.
        """
        # Check if AI features are enabled
        from aot.databases.models import AIGlobalSettings
        ai_settings = AIGlobalSettings.query.first()
        if not ai_settings or not ai_settings.ai_enabled:
            return {"error": "AI features are disabled"}
        
        s1 = AISystemSummary.query.filter_by(unique_id=summary_id_1).first()
        s2 = AISystemSummary.query.filter_by(unique_id=summary_id_2).first()
        
        if not s1 or not s2:
             return {"error": "One or both summaries not found."}

        # Select agent
        from aot.databases.models import AIAgent
        agent = (AIAgent.query.filter_by(pipeline_role='synthesizer', is_activated=True).first() or
                 AIAgent.query.filter_by(role='supervisor', is_activated=True).first())
        
        if not agent:
            return {"error": "No suitable agent for comparison found."}

        # s1/s2.timestamp are naive-UTC (SQLite column) — localize before either
        # the prompt or the returned dict shows them, or the AI/caller reads a
        # bare UTC instant as if it were local wall-clock time.
        prompt = f"""
        당신은 AoT 시스템 분석 전문가입니다. 아래 두 시점의 시스템 스냅샷을 비교하여 주요 변화와 트렌드를 분석하세요.

        [스냅샷 1 ({to_local(s1.timestamp)})]:
        {s1.summary_text}

        [스냅샷 2 ({to_local(s2.timestamp)})]:
        {s2.summary_text}
        
        [지시사항]:
        1. 두 시점 사이의 가장 중요한 상태 변화 3가지를 꼽으세요.
        2. 시스템 건강 상태가 개선되었는지, 악화되었는지 평가하세요.
        3. 향후 주의 깊게 관찰해야 할 지표나 장치를 제안하세요.
        
        응답은 자연어 분석문만 포함하세요.
        """

        try:
            from aot.ai.services.ai_agent_service import AIAgentService  # lazy — avoids circular import
            engine = AIAgentService.get_engine(agent.unique_id)
            if not engine:
                raise ValueError("Engine initialization failed.")

            result = engine.run_reasoning({}, prompt)
            return {
                "comparison": result.get('insight', '비교 결과 생성 실패'),
                "s1": {"id": s1.unique_id, "timestamp": serialize_ts(s1.timestamp)},
                "s2": {"id": s2.unique_id, "timestamp": serialize_ts(s2.timestamp)}
            }
        except Exception as e:
            logger.error(f"Comparison error: {e}")
            return {"error": str(e)}

    @staticmethod
    def analyze_trends(scope_type: str, scope_id: Optional[str], limit: int = 7) -> Dict[str, Any]:
        """
        v26.9: AI-driven longitudinal analysis of system health.
        """
        # Check if AI features are enabled
        from aot.databases.models import AIGlobalSettings
        ai_settings = AIGlobalSettings.query.first()
        if not ai_settings or not ai_settings.ai_enabled:
            return {"error": "AI features are disabled"}
        
        history = AISummaryService.get_summary_history(scope_type, scope_id, limit=limit)
        if not history:
            return {"error": "No history found for trend analysis."}
            
        # Select agent
        from aot.databases.models import AIAgent
        agent = (AIAgent.query.filter_by(pipeline_role='synthesizer', is_activated=True).first() or
                 AIAgent.query.filter_by(role='supervisor', is_activated=True).first())
        
        if not agent:
            return {"error": "No suitable agent for trend analysis found."}

        # s.timestamp is naive-UTC — localize so the trend prompt's dated history
        # isn't silently 9h off from what a KST reader/analyst would expect.
        history_texts = [f"[{to_local(s.timestamp)}]: {s.summary_text}" for s in history]
        history_combined = "\n\n".join(history_texts)

        prompt = f"""
        당신은 AoT 시스템의 데이터 분석 전문가입니다. 최근 {len(history)}개의 스냅샷을 분석하여 중장기 트렌드를 보고하세요.
        
        [이력 데이터]:
        {history_combined}
        
        [지시사항]:
        1. 시스템의 전반적인 건강 상태가 어떤 방향(개선/악화/현상유지)으로 이동하고 있는지 진단하세요.
        2. 이 기간 동안 관찰된 가장 뚜렷한 패턴이나 반복되는 이슈를 식별하세요.
        3. 향후 1주간의 시스템 상태를 예측하고 권장 조치를 제안하세요.
        
        응답은 자연어 분석문만 포함하세요.
        """

        try:
            from aot.ai.services.ai_agent_service import AIAgentService
            engine = AIAgentService.get_engine(agent.unique_id)
            if not engine:
                raise ValueError("Engine initialization failed.")
                
            result = engine.run_reasoning({}, prompt)
            return {
                "trends": result.get('insight', '트렌드 분석 실패'),
                "sample_size": len(history),
                "scope": {"type": scope_type, "id": scope_id}
            }
        except Exception as e:
            logger.error(f"Trend analysis error: {e}")
            return {"error": str(e)}

    @staticmethod
    def archive_old_summaries(days: int = 30) -> int:
        """
        Deactivate summaries older than X days to keep context retrieval efficient.
        """
        cutoff = utc_now().replace(tzinfo=None) - timedelta(days=days)
        old_summaries = AISystemSummary.query.filter(
            AISystemSummary.timestamp < cutoff,
            AISystemSummary.is_active == True
        ).all()
        
        count = 0
        for s in old_summaries:
            s.is_active = False
            count += 1
        
        if count > 0:
            db.session.commit()
            logger.info(f"Archived {count} old AI summaries.")
        return count
