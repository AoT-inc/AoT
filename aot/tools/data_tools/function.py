import logging

logger = logging.getLogger(__name__)


from aot.aot_flask.extensions import db


class FunctionToolsMixin:

    @classmethod
    def get_function_list(cls, function_type=None, active_only=False):
        """
        Returns all registered Function-type controllers with their name, type,
        activation state, and period. Trigger entries also carry trigger_type
        (e.g. 'trigger_sequence') so a sequence can be told apart from a plain
        timer/edge trigger without a separate get_function_detail call per row.

        :param function_type: Filter by type string — one of 'conditional',
                              'trigger', 'pid', 'custom'. Case-insensitive.
                              None returns all types.
        :param active_only:   If True, returns only is_activated=True entries.
        :returns:             {"results": [...], "count": int}
        """
        try:
            from aot.databases.models.function import Conditional, Trigger
            from aot.databases.models.controller import CustomController
            from aot.databases.models.pid import PID

            results = []

            # Normalize filter
            _type_filter = function_type.lower().strip() if function_type else None

            def _should_include(type_key):
                return _type_filter is None or _type_filter == type_key

            if _should_include('conditional'):
                rows = Conditional.query.all()
                for r in rows:
                    if active_only and not getattr(r, 'is_activated', False):
                        continue
                    results.append({
                        "function_id": r.unique_id,
                        "name": r.name,
                        "function_type": "conditional",
                        "is_activated": bool(getattr(r, 'is_activated', False)),
                        "period": getattr(r, 'period', None),
                    })

            if _should_include('trigger'):
                rows = Trigger.query.all()
                for r in rows:
                    if active_only and not getattr(r, 'is_activated', False):
                        continue
                    results.append({
                        "function_id": r.unique_id,
                        "name": r.name,
                        "function_type": "trigger",
                        "trigger_type": getattr(r, 'trigger_type', None),
                        "is_activated": bool(getattr(r, 'is_activated', False)),
                        "period": getattr(r, 'period', None),
                    })

            if _should_include('pid'):
                rows = PID.query.all()
                for r in rows:
                    if active_only and not getattr(r, 'is_activated', False):
                        continue
                    results.append({
                        "function_id": r.unique_id,
                        "name": r.name,
                        "function_type": "pid",
                        "is_activated": bool(getattr(r, 'is_activated', False)),
                        "period": getattr(r, 'period', None),
                    })

            if _should_include('custom'):
                rows = CustomController.query.all()
                for r in rows:
                    if active_only and not getattr(r, 'is_activated', False):
                        continue
                    results.append({
                        "function_id": r.unique_id,
                        "name": r.name,
                        "function_type": "custom",
                        "device": getattr(r, 'device', None),
                        "is_activated": bool(getattr(r, 'is_activated', False)),
                        "period": getattr(r, 'period', None),
                    })

            return {"results": results, "count": len(results)}
        except Exception as e:
            logger.exception("Error in get_function_list")
            return {"error": f"Error while querying Function list: {str(e)}"}

    @classmethod
    def _sequence_detail(cls, trig):
        """Ordered steps + weekly schedule of a trigger_sequence.

        Without this a sequence looks like a name and a period, so the AI can
        neither explain what it does nor tell a valve from the pump. The
        controller already derives the whole picture for the widget
        (get_static_status: per-step start/end, group, duration, mode), so read
        that rather than recomputing the slot maths here. DB-derived and
        read-only — no daemon RPC, so it answers the same from any process.
        """
        try:
            from aot.controllers.controller_trigger_sequence import SequenceTriggerController
            status = SequenceTriggerController.get_static_status(trig.unique_id)
        except Exception as exc:
            logger.warning(f"[_sequence_detail] step read failed: {exc}")
            return {"steps_error": str(exc)}

        if not isinstance(status, dict) or status.get('error'):
            return {"steps_error": str((status or {}).get('error'))}

        steps = []
        for s in status.get('steps') or []:
            # '-' 는 "가리키는 장치를 못 찾았다" 는 뜻인데, 그대로 넘기면
            # 모델은 그냥 빈 값으로 읽고 사용자에게 아무 말도 하지 않는다.
            _detail = s.get('device_detail')
            if _detail == '-':
                _detail = "missing — the referenced device no longer exists"
            step = {
                "action_id": s.get('unique_id'),
                "device": _detail,
                "label": s.get('display_name') or _detail,
                # 'single' takes its turn in the running order; 'total' spans
                # the whole cycle (a field's pump, typically).
                "mode": s.get('type'),
                "group": s.get('group_name'),
                "enabled": s.get('enabled'),
                "duration_seconds": s.get('original_duration'),
                "starts_at_seconds": s.get('start'),
                "ends_at_seconds": s.get('end'),
            }
            if s.get('type') == 'total':
                step["lead_seconds"] = s.get('total_lead')
                step["lag_seconds"] = s.get('total_lag')
            steps.append(step)

        # The resolved plan for EVERY weekday, not just today. Without this a
        # caller configuring Friday from a Thursday session has no way to check
        # what it built — 'steps' above is today's slot maths only.
        weekly_plan = []
        for idx in range(7):
            try:
                plan = SequenceTriggerController.plan_for_day(trig.unique_id, idx)
            except Exception as exc:
                logger.warning(f"[_sequence_detail] plan_for_day({idx}) failed: {exc}")
                continue
            if plan.get('runs'):
                weekly_plan.append(plan)

        return {
            "window_start": status.get('window_start'),
            "window_end": status.get('window_end'),
            "cycle_period_seconds": status.get('period'),
            "weekdays": status.get('weekdays'),
            "schedule": status.get('schedule'),
            "weekly_plan": weekly_plan,
            "steps": steps,
            "step_count": len(steps),
            "steps_note": (
                "'weekly_plan' is what actually happens, per weekday, in wall-clock "
                "time — read that to answer 'when does it water?' and to check any "
                "change you just made. 'steps' below is the raw step list with "
                "today's offsets in seconds. Steps sharing a group run together. A "
                "'total' step spans the whole cycle; its lead/lag hold it inside the "
                "other steps' window (pump starts after the valve opens, stops before "
                "it closes). A weekday can override which steps run, their group and "
                "their duration — so ONE sequence covers different days; never create "
                "a second sequence just because a day differs."
            ),
        }

    @classmethod
    def get_function_detail(cls, function_id):
        """
        Returns detailed configuration for a specific Function-type controller.
        Searches Conditional, Trigger, PID, and CustomController by unique_id
        or name (exact match).

        :param function_id: unique_id (UUID string) or exact name of the function.
        :returns:           dict with full field set for the matched entity.
        """
        try:
            from aot.databases.models.function import Conditional, Trigger
            from aot.databases.models.controller import CustomController
            from aot.databases.models.pid import PID

            if not function_id:
                return {"error": "function_id is required."}

            # Search order: Conditional → Trigger → PID → CustomController
            cond = Conditional.query.filter(
                (Conditional.unique_id == function_id) | (Conditional.name == function_id)
            ).first()
            if cond:
                return {
                    "function_id": cond.unique_id,
                    "name": cond.name,
                    "function_type": "conditional",
                    "is_activated": bool(getattr(cond, 'is_activated', False)),
                    "period": getattr(cond, 'period', None),
                    "start_offset": getattr(cond, 'start_offset', None),
                    "use_pylint": getattr(cond, 'use_pylint', None),
                    "log_level_debug": getattr(cond, 'log_level_debug', None),
                    "tab_id": getattr(cond, 'tab_id', None),
                }

            trig = Trigger.query.filter(
                (Trigger.unique_id == function_id) | (Trigger.name == function_id)
            ).first()
            if trig:
                detail = {
                    "function_id": trig.unique_id,
                    "name": trig.name,
                    "function_type": "trigger",
                    "trigger_type": getattr(trig, 'trigger_type', None),
                    "is_activated": bool(getattr(trig, 'is_activated', False)),
                    "period": getattr(trig, 'period', None),
                    "timer_start_time": getattr(trig, 'timer_start_time', None),
                    "timer_end_time": getattr(trig, 'timer_end_time', None),
                    "log_level_debug": getattr(trig, 'log_level_debug', None),
                    "tab_id": getattr(trig, 'tab_id', None),
                }
                if getattr(trig, 'trigger_type', None) == 'trigger_sequence':
                    detail.update(cls._sequence_detail(trig))
                return detail

            pid = PID.query.filter(
                (PID.unique_id == function_id) | (PID.name == function_id)
            ).first()
            if pid:
                return {
                    "function_id": pid.unique_id,
                    "name": pid.name,
                    "function_type": "pid",
                    "is_activated": bool(getattr(pid, 'is_activated', False)),
                    "period": getattr(pid, 'period', None),
                    "setpoint": getattr(pid, 'setpoint', None),
                    "log_level_debug": getattr(pid, 'log_level_debug', None),
                    "tab_id": getattr(pid, 'tab_id', None),
                }

            ctrl = CustomController.query.filter(
                (CustomController.unique_id == function_id) | (CustomController.name == function_id)
            ).first()
            if ctrl:
                return {
                    "function_id": ctrl.unique_id,
                    "name": ctrl.name,
                    "function_type": "custom",
                    "device": getattr(ctrl, 'device', None),
                    "is_activated": bool(getattr(ctrl, 'is_activated', False)),
                    "period": getattr(ctrl, 'period', None),
                    "log_level_debug": getattr(ctrl, 'log_level_debug', None),
                    "tab_id": getattr(ctrl, 'tab_id', None),
                }

            return {"error": f"Function not found: {function_id}"}
        except Exception as e:
            logger.exception("Error in get_function_detail")
            return {"error": f"Error while querying Function details: {str(e)}"}

    @classmethod
    def activate_function_tool(cls, function_id):
        """
        Activates a Function-type controller (Conditional, Trigger, PID, or
        CustomController). Updates is_activated=True in DB and signals the daemon.
        Refuses to activate a trigger_sequence that has no steps yet.

        NOTE: This tool is in APPROVAL_REQUIRED_TOOLS — the planning service
        will intercept it and request human confirmation before execution.

        :param function_id: unique_id (UUID) or exact name of the function.
        :returns:           {"status": "success", ...} or {"error": "..."}
        """
        return cls._set_function_activation(function_id, activate=True)

    @classmethod
    def deactivate_function_tool(cls, function_id):
        """
        Deactivates a Function-type controller (Conditional, Trigger, PID, or
        CustomController). Updates is_activated=False in DB and signals the daemon.

        NOTE: This tool is in APPROVAL_REQUIRED_TOOLS — the planning service
        will intercept it and request human confirmation before execution.

        :param function_id: unique_id (UUID) or exact name of the function.
        :returns:           {"status": "success", ...} or {"error": "..."}
        """
        return cls._set_function_activation(function_id, activate=False)

    @classmethod
    def _set_function_activation(cls, function_id, activate):
        """
        Internal helper shared by activate_function_tool and deactivate_function_tool.
        Resolves function type, updates DB, and calls DaemonControl.
        """
        try:
            from aot.databases.models.function import Conditional, Trigger, Actions
            from aot.databases.models.controller import CustomController
            from aot.databases.models.pid import PID
            from aot.aot_flask.extensions import db as _db
            from aot.aot_client import DaemonControl

            if not function_id:
                return {"error": "function_id is required."}

            # Resolve entity and controller_type label used by DaemonControl
            mod = None
            controller_type = None

            cond = Conditional.query.filter(
                (Conditional.unique_id == function_id) | (Conditional.name == function_id)
            ).first()
            if cond:
                mod = cond
                controller_type = 'Conditional'

            if mod is None:
                trig = Trigger.query.filter(
                    (Trigger.unique_id == function_id) | (Trigger.name == function_id)
                ).first()
                if trig:
                    mod = trig
                    controller_type = 'Trigger'

            if mod is None:
                pid = PID.query.filter(
                    (PID.unique_id == function_id) | (PID.name == function_id)
                ).first()
                if pid:
                    mod = pid
                    controller_type = 'PID'

            if mod is None:
                ctrl = CustomController.query.filter(
                    (CustomController.unique_id == function_id) | (CustomController.name == function_id)
                ).first()
                if ctrl:
                    mod = ctrl
                    controller_type = 'Function'  # DaemonControl uses 'Function' for CustomController

            if mod is None:
                return {"error": f"Function not found: {function_id}"}

            # A trigger_sequence with no steps has nothing to run — activating it
            # would flip is_activated on real device control with no configured
            # actions. create_sequence_function already refuses to create one
            # empty; mirror that guard here so an empty one can't be activated
            # later either (same message style as configure_sequence_day).
            if activate and controller_type == 'Trigger' and getattr(mod, 'trigger_type', None) == 'trigger_sequence':
                has_steps = Actions.query.filter(Actions.function_id == mod.unique_id).first()
                if not has_steps:
                    return {"error": f"'{mod.name}' has no steps yet — add devices to it "
                                      "before activating (create_sequence_function / modify_sequence_step)."}

            # Update DB
            mod.is_activated = activate
            _db.session.commit()

            # Signal daemon
            action_label = 'activate' if activate else 'deactivate'
            try:
                daemon = DaemonControl()
                if activate:
                    ret_err, ret_msg = daemon.controller_activate(mod.unique_id)
                else:
                    ret_err, ret_msg = daemon.controller_deactivate(mod.unique_id)

                if ret_err:
                    logger.warning(
                        f"[_set_function_activation] Daemon warning for {mod.unique_id}: {ret_msg}"
                    )
                    return {
                        "status": "success_with_warning",
                        "function_id": mod.unique_id,
                        "name": mod.name,
                        "function_type": controller_type,
                        "is_activated": activate,
                        "daemon_warning": ret_msg,
                        "message": f"DB update complete. Daemon response: {ret_msg}",
                    }
            except Exception as daemon_err:
                # Daemon may be offline — DB update succeeded, log warning
                logger.warning(
                    f"[_set_function_activation] Daemon call failed for {mod.unique_id}: {daemon_err}"
                )
                return {
                    "status": "success_with_warning",
                    "function_id": mod.unique_id,
                    "name": mod.name,
                    "function_type": controller_type,
                    "is_activated": activate,
                    "daemon_warning": str(daemon_err),
                    "message": "DB update complete. The daemon may be offline.",
                }

            logger.info(
                f"[_set_function_activation] {action_label} OK: "
                f"{controller_type}/{mod.unique_id} ({mod.name})"
            )
            return {
                "status": "success",
                "function_id": mod.unique_id,
                "name": mod.name,
                "function_type": controller_type,
                "is_activated": activate,
                "message": f"'{mod.name}' {'activated' if activate else 'deactivated'}",
            }
        except Exception as e:
            logger.exception("Error in _set_function_activation")
            return {"error": f"Error while {'activating' if activate else 'deactivating'} Function: {str(e)}"}

    @classmethod
    def get_active_functions_summary(cls, **kwargs):
        """
        Returns a summary of all currently active Function-type controllers.
        Designed for AI context injection — provides a compact view of what
        automation is currently running.

        :returns: {"active_functions": [...], "count": int}
        """
        try:
            from aot.databases.models.function import Conditional, Trigger
            from aot.databases.models.controller import CustomController
            from aot.databases.models.pid import PID

            active = []

            for r in Conditional.query.filter_by(is_activated=True).all():
                active.append({
                    "function_id": r.unique_id,
                    "name": r.name,
                    "function_type": "conditional",
                    "is_activated": True,
                    "period": getattr(r, 'period', None),
                })

            for r in Trigger.query.filter_by(is_activated=True).all():
                active.append({
                    "function_id": r.unique_id,
                    "name": r.name,
                    "function_type": "trigger",
                    "trigger_type": getattr(r, 'trigger_type', None),
                    "is_activated": True,
                    "period": getattr(r, 'period', None),
                })

            for r in PID.query.filter_by(is_activated=True).all():
                active.append({
                    "function_id": r.unique_id,
                    "name": r.name,
                    "function_type": "pid",
                    "is_activated": True,
                    "period": getattr(r, 'period', None),
                })

            for r in CustomController.query.filter_by(is_activated=True).all():
                active.append({
                    "function_id": r.unique_id,
                    "name": r.name,
                    "function_type": "custom",
                    "device": getattr(r, 'device', None),
                    "is_activated": True,
                    "period": getattr(r, 'period', None),
                })

            return {"active_functions": active, "count": len(active)}
        except Exception as e:
            logger.exception("Error in get_active_functions_summary")
            return {"error": f"Error while querying active Function summary: {str(e)}"}

    @classmethod
    def create_function_tool(cls, function_type=None, name=None, params=None, **extra):
        """
        Creates a new function of the given type.
        function_type: one of the registered FUNCTION_INFO keys, e.g.
                       'trigger_sequence' (sequential device control),
                       'conditional_conditional', 'pid_pid', 'trigger_timer_duration'.
        name: optional display name (falls back to function module default)
        params: dict of custom_options values to override after creation.
                For select_measurement fields, use 'device_id,measurement_id' format.
        Returns: {"function_id": "...", "name": "...", "function_type": "..."}

        Hardened: tolerates unexpected top-level kwargs (e.g. an LLM inventing
        `devices=[...]`) instead of raising TypeError — they are ignored with a
        warning, and an invalid/missing function_type returns the valid list so the
        model can self-correct rather than crash. Device/action wiring (which valves,
        order, timing) is NOT set here — it is configured after creation via the
        function editor / modify_function_options.
        """
        import json as _json
        from aot.aot_flask.utils.utils_function import function_add
        from aot.config import FUNCTION_INFO

        _valid = sorted(FUNCTION_INFO.keys())

        if not function_type:
            return {"error": "function_type is required.", "valid_function_types": _valid}

        if function_type not in FUNCTION_INFO:
            return {
                "error": f"Unknown function_type '{function_type}'. There is no dedicated "
                         f"parameter for a device list — to control several devices in "
                         f"order, create a 'trigger_sequence' function, then configure its "
                         f"steps.",
                "valid_function_types": _valid,
            }

        # An LLM sometimes invents top-level args (e.g. devices=[...]). These cannot be
        # mapped to custom_options blindly, so ignore them (never crash) and report it
        # back so the caller learns the correct shape ({function_type, name, params}).
        ignored_args = list(extra.keys())
        if ignored_args:
            logger.warning(f"[create_function] ignoring unexpected args {ignored_args} "
                           f"(only function_type/name/params are accepted)")

        # Minimal form shim — function_add only reads .function_type.data
        class _FakeForm:
            class _Field:
                def __init__(self, data): self.data = data
            def __init__(self, ft): self.function_type = self._Field(ft)

        try:
            messages, dep_name, unmet_deps, dep_msg, new_function_id = function_add(_FakeForm(function_type))
        except Exception as e:
            logger.error(f"[create_function] function_add raised: {e}")
            return {"error": str(e)}

        if messages.get("error"):
            return {"error": "; ".join(messages["error"]), "unmet_deps": unmet_deps}

        if not new_function_id:
            return {"error": "Function created but unique_id not returned"}

        # Look up the newly created record by unique_id. `Function` MUST stay in this
        # list: function_add() creates a plain Function row for 'function_actions', and
        # while it was missing here new_func stayed None for that type — so `name` and
        # `params` were silently dropped and the result reported name "" while the row
        # kept its 'Function Name' default. Same class of omission as the one that made
        # delete_function() report false-positive deletes. If a new controller table is
        # ever added, add it here too.
        from aot.databases.models.controller import CustomController
        from aot.databases.models.function import Conditional, Function, Trigger
        from aot.databases.models.pid import PID

        unapplied = []
        new_func = None
        for Model in [CustomController, Conditional, PID, Trigger, Function]:
            try:
                row = Model.query.filter_by(unique_id=new_function_id).first()
                if row:
                    new_func = row
                    break
            except Exception:
                continue

        if new_func is None:
            # Never fail silently again: the row exists (function_add returned its id)
            # but no known model matched it, so nothing below can be applied.
            logger.error(f"[create_function] created {new_function_id} but no controller "
                         f"model matched it; name/params not applied")
            if name:
                unapplied.append("name")
            if params:
                unapplied.append("params")

        # Apply display name if provided
        if new_func and name:
            new_func.name = name
            db.session.commit()

        # Apply custom params if provided
        logger.info(f"[create_function] new_func={new_func}, params={params}")
        if new_func and params and isinstance(params, dict):
            # Not every controller table has custom_options — `Function` does not.
            # Assigning to a missing column would set a throwaway Python attribute and
            # commit cleanly, reporting success for options that were never stored.
            if not hasattr(type(new_func), 'custom_options'):
                logger.warning(f"[create_function] {type(new_func).__name__} has no "
                               f"custom_options column; params not applied")
                unapplied.append("params")
            else:
                existing = {}
                try:
                    existing = _json.loads(getattr(new_func, 'custom_options', None) or '{}')
                except Exception:
                    existing = {}
                logger.info(f"[create_function] existing before update: {existing}")
                existing.update(params)
                logger.info(f"[create_function] existing after update: {existing}")
                new_func.custom_options = _json.dumps(existing)
                db.session.commit()
                logger.info(f"[create_function] custom_options committed: {new_func.custom_options[:200]}")

        function_id = new_function_id

        # Never auto-activate on creation — this is an absolute rule, not just a default:
        # a freshly-created function has no device steps/targets configured yet, and
        # activation must always be its own explicit, approval-gated step
        # (activate_function), never bundled into creation. Do not reintroduce an
        # 'activate' bypass parameter here.
        result = {
            "function_id": function_id,
            "name": getattr(new_func, 'name', ''),
            "function_type": function_type,
            "status": "created",
            "activated": False,
            "note": ("Created deactivated — configure its options/steps, then "
                     "activate with activate_function."),
        }
        if ignored_args:
            result["ignored_args"] = ignored_args
            result["note"] = ("Ignored non-schema arg(s): "
                              f"{ignored_args}. The function was created (deactivated & empty); "
                              "configure its device steps, then activate.")
        if unapplied:
            # Say so rather than returning a clean result for settings that never landed.
            result["unapplied"] = sorted(set(unapplied))
            result["note"] = (f"Created, but {sorted(set(unapplied))} could not be applied "
                              f"to a '{function_type}' function — set them via the function "
                              "editor / modify_function_options, then activate.")
        return result

    @classmethod
    def modify_function_options(cls, function_id, params):
        """
        Updates custom_options fields of an existing function.
        params: dict — keys are custom_option IDs, values are the new settings.
                For select_measurement fields: 'device_id,measurement_id' string.
        Also triggers daemon reload so the change takes effect immediately.
        """
        import json as _json
        if not function_id or not params:
            return {"error": "function_id and params are required"}

        from aot.databases.models.controller import CustomController
        from aot.databases.models.function import Conditional, Function, Trigger
        from aot.databases.models.pid import PID

        func = None
        for Model in [CustomController, Conditional, PID, Trigger, Function]:
            try:
                row = Model.query.filter_by(unique_id=function_id).first()
                if row:
                    func = row
                    break
            except Exception:
                continue

        if func is None:
            return {"error": f"Function not found: {function_id}"}

        # Only CustomController and Conditional have a custom_options column. For
        # PID/Trigger/Function the settings are real columns, so the write below
        # would set an unmapped attribute that commit() silently drops — reporting
        # success while changing nothing. This guard used to name Trigger alone, so
        # PID kept failing silently and Function was not even looked up. Test by
        # column, not by class, so a new controller table cannot reopen the hole.
        if not hasattr(type(func), 'custom_options'):
            kind = type(func).__name__
            hint = ("For a trigger_sequence use modify_sequence_schedule (window, "
                    "period, weekdays). Other trigger types must be edited in the "
                    "web UI." if isinstance(func, Trigger) else
                    "Edit it in the web UI.")
            err = {"error": (f"This function is a {kind}; its settings are columns, "
                             f"not custom_options, so this tool cannot change them. {hint}"),
                   "function_id": function_id,
                   "controller_type": kind}
            if isinstance(func, Trigger):
                err["trigger_type"] = getattr(func, 'trigger_type', None)
            return err

        # Capture BEFORE the edit: a deactivated function must stay deactivated.
        was_activated = bool(getattr(func, 'is_activated', False))

        existing = {}
        try:
            existing = _json.loads(getattr(func, 'custom_options', None) or '{}')
        except Exception:
            existing = {}

        existing.update(params)
        func.custom_options = _json.dumps(existing)
        db.session.commit()

        # Reload in daemon so changes take effect without manual restart — but ONLY
        # if it was already running. daemon.controller_activate() is not a reload
        # primitive: it sets is_activated=True in the database and starts the
        # controller thread (aot_daemon.py). Calling it unconditionally meant that
        # editing the options of a DEACTIVATED function turned it on — and since
        # this tool is config_only (approval-exempt), that handed an unapproved
        # path to real device control, breaking the config_only contract in
        # tool_registry.py ("이 도구만으로는 어떤 장비도 움직이지 않는다").
        # Activation stays where it belongs: activate_function, which needs approval.
        reloaded = False
        if was_activated:
            try:
                from aot.aot_client import DaemonControl
                daemon = DaemonControl()
                daemon.controller_deactivate(function_id)
                daemon.controller_activate(function_id)
                reloaded = True
            except Exception as e:
                logger.warning(f"[modify_function_options] daemon reload failed (non-fatal): {e}")

        result = {"function_id": function_id, "status": "modified",
                  "changed": list(params.keys()),
                  "activated": was_activated, "reloaded": reloaded}
        if not was_activated:
            result["note"] = ("Saved while deactivated — it stays deactivated. "
                              "Activate with activate_function (requires approval).")
        return result

    @classmethod
    def configure_sequence_day(cls, function_id, day, slots, start=None, end=None,
                               period_seconds=None, repeat=False):
        """Set a whole weekday's run plan on a sequence in ONE call.

        Doing this through modify_sequence_step meant one approval per step per
        field — about twenty gated calls to lay out a single evening's watering,
        which is enough friction that a caller gives up and makes a second
        sequence instead (that is exactly what happened on 2026-08-06). Here a
        caller says what a farmer says — "from 21:00, v321 and v322 together for
        40 minutes, then v331 and v332 together for an hour" — and that is one
        approval.

        slots: ordered list of {devices: [name|action_id, ...], minutes|seconds,
        group?}. Devices in the same slot run simultaneously. Any step of the
        sequence not named here is switched OFF for this weekday only; other
        weekdays keep their own plan.
        """
        import json as _json
        from aot.databases.models.function import Actions, Trigger
        from aot.databases.models.output import Output
        from aot.utils.weekly_schedule import (
            parse_schedule, from_legacy, validate, minutes_to_hhmm, time_to_minutes,
            DAY_NAMES)
        from aot.utils import sequence_schedule
        from aot.controllers.controller_trigger_sequence import SequenceTriggerController

        if not function_id:
            return {"error": "function_id is required"}
        if not isinstance(slots, list) or not slots:
            return {"error": "slots must be a non-empty ordered list, e.g. "
                             "[{'devices': ['v321','v322'], 'minutes': 40}, ...]"}
        try:
            day = int(day)
        except (TypeError, ValueError):
            return {"error": f"day must be 0-6 (0=Mon), got {day!r}"}
        if not 0 <= day <= 6:
            return {"error": f"day must be 0-6 (0=Mon), got {day}"}

        trig = Trigger.query.filter(
            (Trigger.unique_id == function_id) | (Trigger.name == function_id)).first()
        if not trig:
            return {"error": f"Sequence not found: {function_id}"}
        if trig.trigger_type != 'trigger_sequence':
            return {"error": f"'{trig.name}' is a {trig.trigger_type}, not a sequence."}

        steps = Actions.query.filter(Actions.function_id == trig.unique_id).all()
        if not steps:
            return {"error": f"'{trig.name}' has no steps yet — add devices to it first."}

        out_names = {o.unique_id: o.name for o in Output.query.all()}
        index, catalog = {}, []
        for a in steps:
            try:
                o = _json.loads(a.custom_options) if a.custom_options else {}
            except Exception:
                o = {}
            dev = out_names.get(str(o.get('output') or a.do_unique_id or '').split(',')[0], '')
            label = (o.get('display_name') or '').strip()
            for key in filter(None, (a.unique_id, dev, label)):
                index.setdefault(key.lower(), a.unique_id)
            catalog.append(label and f"{label} ({dev})" or dev)

        resolved, unknown = [], []
        for i, slot in enumerate(slots):
            if not isinstance(slot, dict):
                return {"error": f"slots[{i}] must be an object with 'devices' and a duration"}
            names = slot.get('devices') or slot.get('device')
            names = [names] if isinstance(names, str) else list(names or [])
            if not names:
                return {"error": f"slots[{i}] has no 'devices'"}
            if slot.get('minutes') is not None:
                secs = float(slot['minutes']) * 60
            elif slot.get('seconds') is not None:
                secs = float(slot['seconds'])
            else:
                return {"error": f"slots[{i}] needs 'minutes' (or 'seconds')"}
            if secs <= 0:
                return {"error": f"slots[{i}] duration must be positive"}
            ids = []
            for n in names:
                uid = index.get(str(n).strip().lower())
                (ids.append(uid) if uid else unknown.append(n))
            resolved.append({"ids": ids, "seconds": secs,
                             "group": (slot.get('group') or '').strip()})
        if unknown:
            return {"error": f"Not steps of '{trig.name}': {unknown}",
                    "available_steps": sorted(set(catalog))}

        listed = [uid for s in resolved for uid in s['ids']]
        if len(listed) != len(set(listed)):
            return {"error": "The same step appears in more than one slot."}

        sched = sequence_schedule.load(trig)
        sched['mode'] = 'per_day'
        entry = sched['days'].setdefault(str(day), {})

        # Run order is global (there is no per-weekday order map), so only
        # PERMUTE the order values these steps already hold. Steps that run on
        # other days keep their own values and their position relative to this
        # set, which is what stops one day's layout from scrambling another's.
        opts_of = {}
        for a in steps:
            try:
                opts_of[a.unique_id] = _json.loads(a.custom_options) if a.custom_options else {}
            except Exception:
                opts_of[a.unique_id] = {}
        pool = sorted(opts_of[u].get('gridstack_y', opts_of[u].get('position', 0)) or 0
                      for u in listed)
        by_uid = {a.unique_id: a for a in steps}
        for pos, uid in zip(pool, listed):
            opts_of[uid]['gridstack_y'] = pos
            by_uid[uid].custom_options = _json.dumps(opts_of[uid])

        actions_map, groups_map, durations_map = {}, {}, {}
        for i, s in enumerate(resolved):
            gname = s['group'] or (f"g{i + 1}" if len(s['ids']) > 1 else '')
            for uid in s['ids']:
                actions_map[uid] = True
                groups_map[uid] = gname
                durations_map[uid] = s['seconds']
        for a in steps:
            if a.unique_id not in actions_map:
                actions_map[a.unique_id] = False

        entry['actions'] = actions_map
        entry['groups'] = groups_map
        entry['durations'] = durations_map
        entry['enabled'] = True

        span = sum(s['seconds'] for s in resolved)  # overlap=0 assumed for sizing
        overlap = float(trig.output_duration or 0)
        if overlap and len(resolved) > 1:
            span += overlap * (len(resolved) - 1)

        entry['start'] = str(start) if start else entry.get('start') or '00:00'
        if end:
            entry['end'] = '24:00' if str(end) == '00:00' else str(end)
        else:
            try:
                fin = time_to_minutes(entry['start']) + int((span + 59) // 60)
                entry['end'] = minutes_to_hhmm(min(fin, 1440))
            except ValueError:
                return {"error": f"start must be 'HH:MM', got {entry['start']!r}"}
        entry['period'] = int(period_seconds) if period_seconds else (
            int(span) if not repeat else int(entry.get('period') or span))

        # 저장은 정본 모듈 하나로 — 검증하고, 레거시 창 컬럼도 한 규칙으로 맞춘다.
        # 예전에는 JSON 과 timer_weekday 만 쓰고 시작·종료·주기 거울은 옛 값으로
        # 남겨 두었다.
        errors = sequence_schedule.save(trig, sched)
        if errors:
            db.session.rollback()
            return {"error": "The resulting schedule is not valid", "details": errors}
        db.session.commit()

        try:
            from aot.aot_client import DaemonControl
            DaemonControl().refresh_daemon_trigger_settings(trig.unique_id)
        except Exception as exc:
            logger.warning(f"[configure_sequence_day] daemon refresh failed "
                           f"(saved, applies on next start): {exc}")

        plan = SequenceTriggerController.plan_for_day(trig.unique_id, day)
        return {
            "function_id": trig.unique_id,
            "name": trig.name,
            "status": "configured",
            "plan": plan,
            "note": (f"{DAY_NAMES[day]} only. Steps not listed are off for this weekday; "
                     "other weekdays are untouched. Read 'plan' back to the user — it is "
                     "the actual wall-clock result, not the request."),
        }

    @classmethod
    def _modify_sequence_step_for_day(cls, action, opts, day, enabled=None, group_name=None,
                                      duration_seconds=None, global_only=None):
        """Per-weekday override for one step, stored in the trigger's schedule.

        A sequence is one ordered step list, but weekly_schedule v1 lets each
        weekday override which steps run (`actions`), how they are grouped
        (`groups`) and how long they run (`durations`). That is how one sequence
        covers, say, a Thursday-evening pass and a Friday-dawn pass with
        different valves — no second sequence needed. The maps live on the
        Trigger, not on the step, so this writes there.
        """
        import json as _json
        from aot.databases.models.function import Actions, Trigger
        from aot.utils.weekly_schedule import (
            parse_schedule, from_legacy, validate, day_action_group, DAY_NAMES)
        from aot.utils import sequence_schedule

        blocked = [k for k, v in (global_only or {}).items() if v is not None]
        if blocked:
            return {"error": f"{', '.join(blocked)} cannot be set per weekday — a "
                             "weekday can override which steps run, their group and "
                             "their duration, nothing else. Call again without 'day' "
                             "to change these for every day."}
        if enabled is None and group_name is None and duration_seconds is None:
            return {"error": "With 'day', pass at least one of enabled, group_name, "
                             "duration_seconds."}
        try:
            day = int(day)
        except (TypeError, ValueError):
            return {"error": f"day must be 0-6 (0=Mon), got {day!r}"}
        if not 0 <= day <= 6:
            return {"error": f"day must be 0-6 (0=Mon), got {day}"}

        trig = Trigger.query.filter_by(unique_id=action.function_id).first()
        if not trig:
            return {"error": f"Sequence not found for step {action.unique_id}"}

        sched = sequence_schedule.load(trig)
        sched['mode'] = 'per_day'
        entry = sched['days'].setdefault(str(day), {})
        uid = action.unique_id

        if enabled is not None:
            entry.setdefault('actions', {})[uid] = bool(enabled)
        if group_name is not None:
            # '' is meaningful here: "explicitly ungrouped on this day".
            entry.setdefault('groups', {})[uid] = str(group_name).strip()

        propagated = []
        if duration_seconds is not None:
            try:
                dur = float(duration_seconds)
            except (TypeError, ValueError):
                return {"error": f"duration_seconds must be a number, got {duration_seconds!r}"}
            if dur < 0:
                return {"error": f"duration_seconds cannot be negative, got {dur}"}
            entry.setdefault('durations', {})[uid] = dur
            # Same invariant as the global path: a group runs on one duration,
            # so every member sharing this day's effective group follows.
            eff = day_action_group(sched, day, uid, (opts.get('group_name') or '').strip() or None)
            if eff:
                for sib in Actions.query.filter(
                        Actions.function_id == action.function_id,
                        Actions.unique_id != uid).all():
                    try:
                        sopts = _json.loads(sib.custom_options) if sib.custom_options else {}
                    except Exception:
                        sopts = {}
                    sib_eff = day_action_group(
                        sched, day, sib.unique_id,
                        (sopts.get('group_name') or '').strip() or None)
                    if sib_eff == eff:
                        entry['durations'][sib.unique_id] = dur
                        propagated.append(sib.unique_id)

        errors = sequence_schedule.save(trig, sched)
        if errors:
            db.session.rollback()
            return {"error": "Invalid schedule after the per-day change", "details": errors}
        db.session.commit()

        try:
            from aot.aot_client import DaemonControl
            DaemonControl().refresh_daemon_trigger_settings(trig.unique_id)
        except Exception as exc:
            logger.warning(f"[modify_sequence_step] daemon refresh failed "
                           f"(saved, applies on next start): {exc}")

        result = {
            "action_id": uid,
            "function_id": trig.unique_id,
            "status": "modified",
            "scope": f"{DAY_NAMES[day]} only",
            "day": day,
            "runs_this_day": entry.get('actions', {}).get(uid, opts.get('enabled', True)),
            "group_this_day": entry.get('groups', {}).get(
                uid, (opts.get('group_name') or '').strip() or None) or None,
            "duration_this_day": entry.get('durations', {}).get(uid, opts.get('action_duration')),
            "note": ("This overrides the step's global setting on this weekday only; "
                     "other weekdays are untouched."),
        }
        if propagated:
            result["duration_propagated_to"] = propagated
        return result

    @classmethod
    def modify_sequence_step(cls, action_id, group_name=None, duration_seconds=None,
                             mode=None, enabled=None, display_name=None,
                             lead_seconds=None, lag_seconds=None, order=None,
                             day=None):
        """Configure ONE step of a trigger_sequence.

        create_sequence_function only lays down uniform steps (same duration,
        all 'single', never grouped), so without this the AI can build the
        skeleton of a sequence but not the shape a real irrigation run needs —
        valves opening together, different durations per slot, a pump spanning
        the rest. Those live in the step's custom_options, which
        modify_function_options cannot reach (it is Trigger-blind, and steps
        are Actions rows anyway).

        Mirrors the web routes' rules rather than inventing new ones:
        - a device group has ONE common duration, so setting the duration of a
          grouped step propagates to every member (function_sequence_update_
          action_duration);
        - joining an existing group inherits that group's duration;
        - a 'total' step cannot be grouped, and lead/lag apply only to it
          (function_sequence_update_step).
        """
        import json as _json
        from aot.databases.models.function import Actions

        if not action_id:
            return {"error": "action_id is required (from get_function_detail steps[].action_id)"}
        if all(v is None for v in (group_name, duration_seconds, mode, enabled,
                                   display_name, lead_seconds, lag_seconds, order)):
            return {"error": "Nothing to change: pass at least one of group_name, "
                             "duration_seconds, mode, enabled, display_name, "
                             "lead_seconds, lag_seconds, order."}
        if mode is not None and mode not in ('single', 'total'):
            return {"error": f"mode must be 'single' or 'total', got {mode!r}"}

        action = Actions.query.filter_by(unique_id=action_id).first()
        if not action:
            return {"error": f"Step not found: {action_id}"}

        try:
            opts = _json.loads(action.custom_options) if action.custom_options else {}
        except Exception:
            opts = {}

        if day is not None:
            return cls._modify_sequence_step_for_day(
                action, opts, day, enabled=enabled, group_name=group_name,
                duration_seconds=duration_seconds,
                global_only={'mode': mode, 'display_name': display_name,
                             'lead_seconds': lead_seconds, 'lag_seconds': lag_seconds,
                             'order': order})

        effective_mode = mode or opts.get('sequence_mode', 'single')

        def _members_of(name):
            """Sibling steps sharing group `name` (excludes this one)."""
            out = []
            for m in Actions.query.filter(
                    Actions.function_id == action.function_id,
                    Actions.unique_id != action.unique_id).all():
                try:
                    mo = _json.loads(m.custom_options) if m.custom_options else {}
                except Exception:
                    mo = {}
                if (mo.get('group_name') or '').strip() == name:
                    out.append((m, mo))
            return out

        if display_name is not None:
            if str(display_name).strip():
                opts['display_name'] = str(display_name).strip()
            else:
                opts.pop('display_name', None)

        if order is not None:
            # Run order is by gridstack_y (the key the widget's drag-reorder
            # writes, see routes_function.function_save_order) — steps have no
            # separate ordering column. Without this the AI can group and time a
            # sequence but not decide which slot goes first, which for irrigation
            # is half the meaning of "sequence".
            try:
                opts['gridstack_y'] = int(order)
            except (TypeError, ValueError):
                return {"error": f"order must be an integer, got {order!r}"}

        if enabled is not None:
            opts['enabled'] = bool(enabled)

        if mode is not None:
            opts['sequence_mode'] = effective_mode

        inherited = None
        if effective_mode == 'total':
            # Total steps are never grouped; margins are theirs alone.
            opts.pop('group_name', None)
            for key, val in (('total_lead', lead_seconds), ('total_lag', lag_seconds)):
                if val is None:
                    continue
                try:
                    margin = max(0.0, float(val))
                except (TypeError, ValueError):
                    return {"error": f"{key} must be a number of seconds, got {val!r}"}
                if margin:
                    opts[key] = margin
                else:
                    opts.pop(key, None)
        else:
            opts.pop('total_lead', None)
            opts.pop('total_lag', None)
            if group_name is not None:
                name = str(group_name).strip()
                if not name:
                    opts.pop('group_name', None)
                else:
                    opts['group_name'] = name
                    # Joining an existing group inherits its common duration,
                    # unless this call sets one explicitly.
                    if duration_seconds is None:
                        for _m, mo in _members_of(name):
                            if 'action_duration' in mo:
                                opts['action_duration'] = mo['action_duration']
                                inherited = mo['action_duration']
                                break

        propagated = []
        if duration_seconds is not None:
            try:
                dur = float(duration_seconds)
            except (TypeError, ValueError):
                return {"error": f"duration_seconds must be a number, got {duration_seconds!r}"}
            if dur < 0:
                return {"error": f"duration_seconds cannot be negative, got {dur}"}
            opts['action_duration'] = dur
            # One group, one duration — keep the invariant whichever member was edited.
            current_group = (opts.get('group_name') or '').strip()
            if current_group:
                for m, mo in _members_of(current_group):
                    mo['action_duration'] = dur
                    m.custom_options = _json.dumps(mo)
                    propagated.append(m.unique_id)

        action.custom_options = _json.dumps(opts)
        db.session.commit()

        try:
            from aot.aot_client import DaemonControl
            DaemonControl().refresh_daemon_trigger_settings(action.function_id)
        except Exception as exc:
            logger.warning(f"[modify_sequence_step] daemon refresh failed "
                           f"(saved, applies on next start): {exc}")

        result = {
            "action_id": action.unique_id,
            "function_id": action.function_id,
            "status": "modified",
            "mode": opts.get('sequence_mode', 'single'),
            "group": opts.get('group_name'),
            "duration_seconds": opts.get('action_duration'),
            "enabled": opts.get('enabled', True),
            "display_name": opts.get('display_name'),
            "order": opts.get('gridstack_y'),
        }
        if opts.get('sequence_mode') == 'total':
            result["lead_seconds"] = opts.get('total_lead', 0)
            result["lag_seconds"] = opts.get('total_lag', 0)
        if inherited is not None:
            result["note"] = (f"Joined group '{opts.get('group_name')}' and inherited its "
                              f"common duration ({inherited}s).")
        if propagated:
            result["duration_propagated_to"] = propagated
            result["note"] = (f"A group shares one duration, so {len(propagated)} other "
                              f"step(s) in '{opts.get('group_name')}' were set to {opts['action_duration']}s too.")
        return result

    @classmethod
    def modify_sequence_schedule(cls, function_id, start=None, end=None,
                                 period_seconds=None, weekdays=None, day=None):
        """Change when a trigger_sequence runs: window, cycle period, weekdays.

        The schedule of record is Trigger.timer_schedule (weekly_schedule v1);
        the legacy timer_* columns are only a fallback the controller uses when
        that JSON is absent, so writing them alone changes nothing for any
        sequence that has one. This edits the JSON and back-syncs the columns,
        exactly as the web form's /function_sequence_update_schedule does.

        Reload goes through refresh_daemon_trigger_settings, which keeps the
        running cycle — deactivate/activate would force every output off and
        restart the cycle from zero, cutting irrigation short mid-run.

        day: 0=Mon..6=Sun. Given, the window/period apply to that weekday only
        (switching the schedule to per_day mode); omitted, they apply to every
        enabled day. weekdays replaces the set of enabled days.
        """
        import json as _json
        from aot.databases.models.function import Trigger
        from aot.utils.weekly_schedule import (
            parse_schedule, from_legacy, validate, to_legacy, build_warnings,
            get_today_idx)
        from aot.utils import sequence_schedule

        if not function_id:
            return {"error": "function_id is required"}
        if start is None and end is None and period_seconds is None and weekdays is None:
            return {"error": "Nothing to change: pass at least one of "
                             "start, end, period_seconds, weekdays."}

        trig = Trigger.query.filter(
            (Trigger.unique_id == function_id) | (Trigger.name == function_id)).first()
        if not trig:
            return {"error": f"Sequence not found: {function_id}"}
        if trig.trigger_type != 'trigger_sequence':
            return {"error": f"'{trig.name}' is a {trig.trigger_type}, not a sequence."}

        sched = sequence_schedule.load(trig)

        # "00:00" as an end means end-of-day, stored as "24:00" (a literal
        # 00:00 end would fail validation as start >= end).
        if end is not None and str(end).strip() == '00:00':
            end = '24:00'

        if day is not None:
            try:
                day = int(day)
            except (TypeError, ValueError):
                return {"error": f"day must be 0-6 (0=Mon), got {day!r}"}
            if not 0 <= day <= 6:
                return {"error": f"day must be 0-6 (0=Mon), got {day}"}
            sched['mode'] = 'per_day'
            targets = [str(day)]
        else:
            targets = [k for k in (str(i) for i in range(7))
                       if sched['days'].get(k, {}).get('enabled', True)] or \
                      [str(i) for i in range(7)]

        for key in targets:
            entry = sched['days'].setdefault(key, {})
            if start is not None:
                entry['start'] = str(start)
            if end is not None:
                entry['end'] = str(end)
            if period_seconds is not None:
                entry['period'] = int(float(period_seconds))
        if day is None:
            shared = sched.setdefault('shared', {})
            if start is not None:
                shared['start'] = str(start)
            if end is not None:
                shared['end'] = str(end)
            if period_seconds is not None:
                shared['period'] = int(float(period_seconds))

        if weekdays is not None:
            if isinstance(weekdays, str):
                weekdays = [t.strip() for t in weekdays.split(',') if t.strip()]
            try:
                wanted = {int(w) for w in weekdays}
            except (TypeError, ValueError):
                return {"error": f"weekdays must be numbers 0-6 (0=Mon), got {weekdays!r}"}
            if not wanted or any(not 0 <= w <= 6 for w in wanted):
                return {"error": f"weekdays must be numbers 0-6 (0=Mon), got {weekdays!r}"}
            for i in range(7):
                sched['days'].setdefault(str(i), {})['enabled'] = (i in wanted)

        # 저장은 정본 모듈 하나로. 예전에는 여기서만 per_day 의 레거시 주기를
        # "오늘 요일" 로 덮어써, 같은 컬럼이 저장 경로마다 다른 뜻이 됐다. 오늘의
        # 주기는 이제 읽을 때 JSON 에서 계산한다(sequence_schedule.today_period).
        errors = sequence_schedule.save(trig, sched)
        if errors:
            db.session.rollback()
            return {"error": "Invalid schedule", "details": errors}

        db.session.commit()

        try:
            from aot.aot_client import DaemonControl
            DaemonControl().refresh_daemon_trigger_settings(trig.unique_id)
        except Exception as exc:
            logger.warning(f"[modify_sequence_schedule] daemon refresh failed "
                           f"(saved, applies on next start): {exc}")

        # Report the days actually edited, not the legacy columns: to_legacy()
        # summarises the whole week from the FIRST ENABLED day, so after a
        # day-scoped edit those columns describe some other day. Relaying them
        # as "the new window" would tell the user the wrong time.
        day_names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
        applied = []
        for key in targets:
            entry = sched['days'].get(key, {})
            applied.append({
                "day": int(key),
                "day_name": day_names[int(key)],
                "start": entry.get('start'),
                "end": entry.get('end'),
                "period_seconds": entry.get('period'),
                "runs_on_this_day": bool(entry.get('enabled', True)),
            })

        return {
            "function_id": trig.unique_id,
            "name": trig.name,
            "status": "modified",
            "mode": sched.get('mode'),
            "applied": applied,
            "enabled_weekdays": [
                {"day": i, "day_name": day_names[i]}
                for i in range(7)
                if sched['days'].get(str(i), {}).get('enabled', True)
            ],
            "warnings": build_warnings(sched),
            "note": ("'applied' lists only the weekdays this call changed. Other "
                     "weekdays keep their own window/period — check 'schedule' in "
                     "get_function_detail before telling the user the sequence "
                     "runs at one time every day."),
        }

    @classmethod
    def create_sequence_function(cls, name=None, device_ids=None, state='on',
                                 step_duration=0, pause_seconds=0, **extra):
        """Create a trigger_sequence AND fill its steps — one ordered output action per
        device — so it is actually configured, not an empty shell. This is what "밸브
        순차 제어 시퀀스" means: create the trigger, add an output_on_off action for each
        valve in order. Always created deactivated — this tool is config_only (no human
        approval gate) precisely because activation is a separate, approval-gated step
        (activate_function). Do not add an 'activate' bypass here again: a config_only
        tool that can also flip is_activated would let real device control turn on
        without any approval.

        device_ids: ordered list of Output unique_ids (the valves).
        state: 'on'/'off' applied to every step. step_duration: seconds each step runs
        (0 = until the next step). pause_seconds: delay between steps.
        Returns {function_id, steps:[names], step_count, activated}."""
        import json as _json
        from aot.aot_flask.utils.utils_function import function_add
        from aot.databases.models import Output
        from aot.databases.models.function import Actions, Trigger
        try:
            from aot.databases.models import OutputChannel
        except Exception:
            OutputChannel = None

        if not device_ids or not isinstance(device_ids, (list, tuple)):
            return {"error": "device_ids (ordered list of Output ids) is required"}

        # 1. Create the trigger_sequence. function_add does NOT activate (activation is
        #    a separate step), so actions can be added while it is deactivated.
        form = cls._FakeForm(function_type='trigger_sequence')
        try:
            ret = function_add(form)
        except Exception as e:
            logger.error(f"[create_sequence] function_add raised: {e}")
            return {"error": str(e)}
        messages = ret[0] if isinstance(ret, (list, tuple)) else {}
        new_id = ret[-1] if isinstance(ret, (list, tuple)) else None
        if messages.get("error"):
            return {"error": "; ".join(messages["error"])}
        if not new_id:
            return {"error": "Sequence function created but id not returned"}

        trig = Trigger.query.filter_by(unique_id=new_id).first()
        if name and trig:
            trig.name = name

        # 2. One ordered output_on_off action per device (position sets run order).
        _off = str(state).lower() in ('off', 'false', '0', 'close', 'stop')
        st = 'off' if _off else 'on'
        steps = []
        for i, did in enumerate(device_ids):
            o = Output.query.filter_by(unique_id=did).first()
            if not o:
                continue
            chid = ''
            if OutputChannel is not None:
                ch = OutputChannel.query.filter_by(output_id=did).first()
                chid = ch.unique_id if ch else ''
            co = {
                "output": f"{did},{chid}",
                "state": st,
                "duration": 0.0,
                "action_duration": float(step_duration or 0),
                "sequence_mode": "single",
                "position": i,
            }
            act = Actions(
                function_id=new_id, function_type='trigger',
                action_type='output_on_off', custom_options=_json.dumps(co),
                pause_duration=float(pause_seconds or 0),
            )
            if hasattr(act, 'save'):
                act.save()
            else:
                db.session.add(act)
            steps.append(o.name)
        db.session.commit()

        if not steps:
            return {"error": "None of the given device_ids resolved to Outputs; "
                             "no steps added.", "function_id": new_id}

        # Always created deactivated — this is a config_only (unapproved) tool, so it
        # must never be the thing that turns on real device control. Activation is a
        # separate, approval-gated step via activate_function.
        result = {
            "function_id": new_id, "function_type": "trigger_sequence",
            "name": (trig.name if trig else name), "status": "created",
            "steps": steps, "step_count": len(steps), "activated": False,
            "note": "Created deactivated — activate with activate_function (requires approval).",
        }
        if extra:
            result["ignored_args"] = list(extra.keys())
        return result

    @classmethod
    def delete_function(cls, function_id=None, **extra):
        """Delete a Function/Controller by unique_id (completes function CRUD)."""
        from aot.aot_flask.utils.utils_misc import determine_controller_type
        if not function_id:
            return {"error": "function_id is required"}

        # function_del() only deletes rows from the plain `Function` table
        # (function_actions type). Conditional/PID/Trigger/CustomController live in
        # their own tables, so calling function_del() on those unique_ids silently
        # no-ops (no matching row to delete) while this tool still reported
        # "status": "deleted" — a false-positive delete. Dispatch by actual
        # controller_type, same as the web route (routes_function.py) and
        # function_duplicate() already do.
        controller_type = determine_controller_type(function_id)
        if not controller_type or controller_type == 'Input':
            return {"error": f"No function/controller found with id '{function_id}'"}

        try:
            if controller_type == "Conditional":
                from aot.aot_flask.utils.utils_conditional import conditional_del
                messages = conditional_del(function_id)
            elif controller_type == "PID":
                from aot.aot_flask.utils.utils_pid import pid_del
                messages = pid_del(function_id)
            elif controller_type == "Trigger":
                from aot.aot_flask.utils.utils_trigger import trigger_del
                messages = trigger_del(function_id)
            elif controller_type == "Function_Custom":
                from aot.aot_flask.utils.utils_controller import controller_del
                messages = controller_del(function_id)
            else:  # "Function"
                from aot.aot_flask.utils.utils_function import function_del
                messages = function_del(function_id)
        except Exception as e:
            logger.error(f"[delete_function] delete raised: {e}")
            return {"error": str(e)}
        if isinstance(messages, dict) and messages.get("error"):
            return {"error": "; ".join(messages["error"])}
        return {"function_id": function_id, "status": "deleted"}

