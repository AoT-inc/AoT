import logging

logger = logging.getLogger(__name__)


from aot.aot_flask.extensions import db


class DefinitionToolsMixin:

    @classmethod
    def _input_types(cls):
        from aot.aot_flask.utils.utils_input import parse_input_information
        return parse_input_information()

    @classmethod
    def _output_types(cls):
        from aot.utils.outputs import parse_output_information
        return parse_output_information()

    @classmethod
    def list_device_types(cls, kind=None, **extra):
        """List valid device TYPES available for creation.
        kind: 'input' | 'output' | 'function'. Call this BEFORE create_* so the
        chosen type is real (never invent a type). Returns {kind, types:[{type,name}]}."""
        k = (kind or '').lower().strip()
        try:
            if k == 'function':
                from aot.config import FUNCTION_INFO
                return {"kind": "function", "types": [
                    {"type": t, "name": (FUNCTION_INFO[t].get('name') or t)} for t in sorted(FUNCTION_INFO)]}
            if k == 'input':
                d = cls._input_types()
                return {"kind": "input", "types": [
                    {"type": t, "name": (v.get('input_name') or t), "interfaces": v.get('interfaces')}
                    for t, v in sorted(d.items())]}
            if k == 'output':
                d = cls._output_types()
                return {"kind": "output", "types": [
                    {"type": t, "name": (v.get('output_name') or t), "interfaces": v.get('interfaces')}
                    for t, v in sorted(d.items())]}
            return {"error": "kind must be one of: input, output, function"}
        except Exception as e:
            return {"error": str(e)}

    @classmethod
    def get_device_type_options(cls, kind=None, device_type=None, **extra):
        """Return the configurable OPTION schema (id/type/name/default) for a device
        type, so the AI knows what to pass to modify_*. kind: 'input'|'output'|'function'."""
        k = (kind or '').lower().strip()
        try:
            if k == 'function':
                from aot.config import FUNCTION_INFO
                info = FUNCTION_INFO.get(device_type)
            elif k == 'input':
                info = cls._input_types().get(device_type)
            elif k == 'output':
                info = cls._output_types().get(device_type)
            else:
                return {"error": "kind must be one of: input, output, function"}
            if not info:
                return {"error": f"Unknown {k}_type '{device_type}'"}
            opts = info.get('custom_options') or info.get('options') or []
            out = []
            for o in (opts if isinstance(opts, list) else []):
                if isinstance(o, dict) and o.get('id'):
                    out.append({"id": o.get('id'), "type": o.get('type'),
                                "name": o.get('name'), "default": o.get('default_value')})
            return {"kind": k, "device_type": device_type, "options": out}
        except Exception as e:
            return {"error": str(e)}

    @classmethod
    def create_input(cls, input_type=None, name=None, interface=None, params=None, **extra):
        """Create a new Input (sensor / data source) of a registered type. Then use
        modify_input to fill its options. Hardened: unknown/missing type returns the
        valid list; unexpected kwargs are ignored."""
        from aot.aot_flask.utils.utils_input import input_add
        try:
            types = cls._input_types()
        except Exception as e:
            return {"error": f"could not load input types: {e}"}
        if not input_type:
            return {"error": "input_type is required", "valid_input_types": sorted(types.keys())}
        if input_type not in types:
            return {"error": f"Unknown input_type '{input_type}'", "valid_input_types": sorted(types.keys())}
        iface = interface or ''
        if not iface:
            ifaces = types[input_type].get('interfaces') or []
            iface = ifaces[0] if ifaces else ''
        form = cls._FakeForm(input_type=f"{input_type},{iface}")
        try:
            ret = input_add(form)
        except Exception as e:
            logger.error(f"[create_input] input_add raised: {e}")
            return {"error": str(e)}
        messages = ret[0] if isinstance(ret, (list, tuple)) else {}
        new_id = ret[-1] if isinstance(ret, (list, tuple)) else None
        if messages.get("error"):
            return {"error": "; ".join(messages["error"])}
        if not new_id:
            return {"error": "Input created but unique_id not returned"}
        result = {"input_id": new_id, "input_type": input_type, "status": "created"}
        if name or params:
            cls.modify_input(new_id, name=name, params=params)
            result["configured"] = True
        if extra:
            result["ignored_args"] = list(extra.keys())
        return result

    #: 입력의 표준 칸 중 종류가 `options_enabled` 로 켠 것 — 웹 설정 화면에서 옵션처럼
    #: 보이지만 custom_options 가 아니라 Input 칸에 저장된다(주기·사전 출력). 예전엔
    #: params 로 오면 custom_options 에 적고 성공했다 — 아무도 읽지 않는 키였다.
    _INPUT_COLUMN_OPTIONS = {
        'period': (('period', 'Period (seconds)', 'float'),),
        'start_offset': (('start_offset', 'Start offset (seconds)', 'float'),),
        'pre_output': (('pre_output_id', 'Pre output (output id)', 'text'),
                       ('pre_output_duration', 'Pre output duration (seconds)', 'float'),
                       ('pre_output_during_measure', 'Pre output during measurement',
                        'bool')),
    }

    @classmethod
    def _device_option_spec(cls, kind, module_type):
        """(custom 옵션 {id: 정의}, 표준 칸 {칸: (이름, 종류)}) — 종류를 모르면 None."""
        try:
            types = cls._input_types() if kind == 'input' else cls._output_types()
            info = (types or {}).get(module_type)
        except Exception:                                   # noqa: BLE001
            info = None
        if not info:
            return None
        custom = {o['id']: o for o in (info.get('custom_options') or [])
                  if isinstance(o, dict) and o.get('id')
                  and o.get('type') not in ('message', 'new_line')}
        columns = {}
        if kind == 'input':
            for flag in info.get('options_enabled') or ():
                for col, label, typ in cls._INPUT_COLUMN_OPTIONS.get(flag, ()):
                    columns[col] = (label, typ)
        return custom, columns

    @classmethod
    def _device_params_problem(cls, kind, row, params):
        """입출력 수정 params 의 문제(거절 본문) 또는 None. 종류 정의를 모르면 키를 보지 않는다."""
        if params in (None, {}):
            return None
        if not isinstance(params, dict):
            return {"error": "params must be an object of {option_id: value}. "
                             "Nothing was changed."}
        spec = cls._device_option_spec(
            kind, row.device if kind == 'input' else row.output_type)
        if spec is None:
            return None
        custom, columns = spec
        unknown = sorted(k for k in params if k not in custom and k not in columns)
        bad = {}
        for k, v in params.items():
            if k in custom:
                why = cls._option_value_problem(custom[k], v)
            elif k in columns and columns[k][1] != 'text':
                why = cls._option_value_problem({'type': columns[k][1]}, v)
            else:
                why = None
            if why:
                bad[k] = why
        if not unknown and not bad:
            return None
        parts = []
        if unknown:
            parts.append("unknown option key(s): %s" % ", ".join(unknown))
        if bad:
            parts.append("invalid value(s): %s" % "; ".join(
                "%s %s" % (k, why) for k, why in sorted(bad.items())))
        return {"error": "; ".join(parts) + ". Nothing was changed.",
                "valid_keys": sorted(custom) + sorted(columns)}

    @classmethod
    def validate_device_options(cls, input_id=None, output_id=None, params=None, **_extra):
        """modify_input·modify_output 의 params 를 승인 앞에서 본다
        (tool_execution._pre_gate_validation) — 틀린 키로 승인을 받고 실행에서 막히거나,
        아무도 안 읽는 키가 저장되지 않게."""
        from aot.databases.models import Input, Output
        if input_id:
            kind, row = 'input', Input.query.filter_by(unique_id=input_id).first()
        elif output_id:
            kind, row = 'output', Output.query.filter_by(unique_id=output_id).first()
        else:
            return None
        if row is None:
            return None
        return cls._device_params_problem(kind, row, params)

    @staticmethod
    def _column_value(typ, value):
        if typ == 'float':
            return float(value)
        if typ == 'bool':
            return value is True or str(value).strip().lower() in ('true', '1')
        return value or None

    @classmethod
    def modify_input(cls, input_id=None, name=None, params=None, **extra):
        """Update an Input's display name and/or custom_options, then reload it in the
        daemon. params: dict of option_id → value. Direct write (no full form replay)."""
        import json as _json
        from aot.databases.models import Input
        if not input_id:
            return {"error": "input_id is required"}
        inp = Input.query.filter_by(unique_id=input_id).first()
        if not inp:
            return {"error": f"Input not found: {input_id}"}
        from aot.aot_flask.access import write_scope
        write_scope.enforce(inp)  # 쓰기 시점 그룹 스코프(묶여 있을 때만)
        problem = cls._device_params_problem('input', inp, params)
        if problem:
            return problem
        changed = []
        if name:
            inp.name = name; changed.append("name")
        if params:
            spec = cls._device_option_spec('input', inp.device)
            columns = spec[1] if spec else {}
            custom = {k: v for k, v in params.items() if k not in columns}
            if params.get('pre_output_id'):
                write_scope.enforce(params['pre_output_id'])  # 사전 출력도 그룹 범위 안의 것만
            for col in (k for k in params if k in columns):
                setattr(inp, col, cls._column_value(columns[col][1], params[col]))
                changed.append(col)
            if custom:
                existing = {}
                try:
                    existing = _json.loads(getattr(inp, 'custom_options', None) or '{}')
                except Exception:
                    existing = {}
                existing.update(custom)
                inp.custom_options = _json.dumps(existing); changed.append("custom_options")
        db.session.commit()
        try:
            # DaemonControl has no input_activate/input_deactivate — Input's daemon
            # reload primitive is the generic controller_activate/deactivate pair
            # (aot/aot_flask/utils/utils_general.py's controller_activate_deactivate
            # uses the same two calls for controller_type='Input'). The previous
            # input_activate/input_deactivate calls didn't exist on DaemonControl at
            # all, so this reload always raised AttributeError and silently no-opped
            # (caught below) — the daemon kept running with the pre-edit config.
            from aot.aot_client import DaemonControl
            d = DaemonControl()
            if getattr(inp, 'is_activated', False):
                d.controller_deactivate(input_id); d.controller_activate(input_id)
        except Exception as e:
            logger.warning(f"[modify_input] daemon reload failed (non-fatal): {e}")
        r = {"input_id": input_id, "status": "modified", "changed": changed}
        if extra:
            r["ignored_args"] = list(extra.keys())
        return r

    @classmethod
    def delete_input(cls, input_id=None, **extra):
        """Delete an Input by unique_id."""
        from aot.aot_flask.utils.utils_input import input_del
        if not input_id:
            return {"error": "input_id is required"}
        from aot.aot_flask.access import write_scope
        write_scope.enforce(input_id)  # 쓰기 시점 그룹 스코프(묶여 있을 때만)
        try:
            messages = input_del(input_id)
        except Exception as e:
            logger.error(f"[delete_input] input_del raised: {e}")
            return {"error": str(e)}
        if isinstance(messages, dict) and messages.get("error"):
            return {"error": "; ".join(messages["error"])}
        return {"input_id": input_id, "status": "deleted"}

    @staticmethod
    def _as_active(value):
        """켜기/끄기 값 — 불리언, 'true'/'false' 글자, 0/1. 알아볼 수 없으면 None.
        도메인 스키마의 `active` 는 type 이 없어 호스트가 글자로 넘길 수 있다 — bool('false') 는 참이다."""
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)) and value in (0, 1):
            return bool(value)
        text = str(value).strip().lower()
        if text in ('true', '1', 'on', 'yes'):
            return True
        if text in ('false', '0', 'off', 'no'):
            return False
        return None

    @classmethod
    def input_activation_state(cls, input_id=None, active=None, **_extra):
        """켜기/끄기 요청이 지금 상태와 같은가 — 같으면 승인 없이 그렇다고 답하려고 틀이 먼저 본다.
        이름·지금 상태·같은지, 또는 None(입력을 못 찾음·값을 못 알아봄 → 평소 흐름이 거절한다)."""
        from aot.databases.models import Input
        want = cls._as_active(active)
        inp = Input.query.filter_by(unique_id=input_id).first() if input_id else None
        if inp is None or want is None:
            return None
        return {"name": inp.name, "is_activated": bool(inp.is_activated), "same": bool(inp.is_activated) == want}

    @classmethod
    def activate_input(cls, input_id=None, active=True, **extra):
        """Turns an Input (sensor / data source) on or off. Off stops its readings; whatever uses
        them is not switched off. Turning on runs the web page's checks (period, measurement
        channels, required options)."""
        from aot.databases.models import Input
        if not input_id:
            return {"error": "input_id is required"}
        want = cls._as_active(active)
        if want is None:
            return {"error": "active must be true or false. Nothing was changed."}
        inp = Input.query.filter_by(unique_id=input_id).first()
        if not inp:
            return {"error": f"Input not found: {input_id}"}
        from aot.aot_flask.access import write_scope
        write_scope.enforce(inp)  # 쓰기 시점 그룹 스코프(묶여 있을 때만)
        if bool(inp.is_activated) == want:
            return {"input_id": input_id, "name": inp.name, "status": "unchanged", "is_activated": want,
                    "message": "'%s' is already %s - nothing was changed." % (inp.name, "on" if want else "off")}
        out, problem = cls._set_input_active(inp, want)
        if problem:
            return {"error": "Not turned on: %s. Nothing was changed." % problem}
        out.update(input_id=input_id, name=inp.name)
        if out.get("status") == "success_with_warning":
            from aot.tools.mcp_safety_gate import mark_runtime_unconfirmed
            out = mark_runtime_unconfirmed(out)
        if extra:
            out["ignored_args"] = list(extra.keys())
        return out

    @classmethod
    def _set_input_active(cls, inp, want):
        """입력을 켜거나 끈다 → (결과 dict, 오류 문구 또는 None). 켤 때는 웹과 같은 점검(주기·측정 채널·필수 옵션)을
        먼저 본다. DB 표시를 바꾸고 데몬에 알리는 것은 웹 `controller_activate_deactivate` 와 같다 — 그 함수의 로그인
        권한 검사(flask_login)는 MCP 요청에 사람이 없어 쓸 수 없다. 권한은 게이트·역할·쓰기 스코프가 이미 판정했다."""
        if want:
            from aot.aot_flask.utils.utils_general import check_for_valid_unit_and_conversion
            from aot.aot_flask.utils.utils_input import input_activation_checks
            problems = input_activation_checks(inp.unique_id).get("error") or []
            problems = check_for_valid_unit_and_conversion(inp.unique_id, list(problems))
            if problems:
                return None, "; ".join(str(p) for p in problems)
        inp.is_activated = want
        db.session.commit()
        out = {"is_activated": want, "status": "activated" if want else "deactivated"}
        try:
            from aot.aot_client import DaemonControl
            control = DaemonControl()
            err, msg = (control.controller_activate(inp.unique_id) if want
                        else control.controller_deactivate(inp.unique_id))[:2]
            if err:
                out.update(status="success_with_warning", daemon_warning=msg)
        except Exception as e:
            logger.warning(f"[activate_input] on/off saved, daemon call failed: {e}")
            out.update(status="success_with_warning", daemon_warning=str(e))
        return out, None

    @classmethod
    def create_output(cls, output_type=None, name=None, interface=None, params=None, **extra):
        """Create a new Output (actuator / relay / valve) of a registered type. Then use
        modify_output to fill its options. Hardened like create_input."""
        from aot.aot_flask.utils.utils_output import output_add
        try:
            types = cls._output_types()
        except Exception as e:
            return {"error": f"could not load output types: {e}"}
        if not output_type:
            return {"error": "output_type is required", "valid_output_types": sorted(types.keys())}
        if output_type not in types:
            return {"error": f"Unknown output_type '{output_type}'", "valid_output_types": sorted(types.keys())}
        iface = interface or ''
        if not iface:
            ifaces = types[output_type].get('interfaces') or []
            iface = ifaces[0] if ifaces else ''
        form = cls._FakeForm(output_type=f"{output_type},{iface}")
        try:
            ret = output_add(form, {})  # empty request_form → defaults applied
        except Exception as e:
            logger.error(f"[create_output] output_add raised: {e}")
            return {"error": str(e)}
        messages = ret[0] if isinstance(ret, (list, tuple)) else {}
        # output_add returns a 6-tuple (...,output_id,size_y) or a 2-tuple (messages,id)
        new_id = None
        if isinstance(ret, (list, tuple)):
            if len(ret) >= 6:
                new_id = ret[4]
            elif len(ret) == 2:
                new_id = ret[1]
            else:
                new_id = ret[-1]

        # new_id decides success, not messages["error"]. output_add() can
        # commit the Output (and its channel rows) and THEN append an error —
        # most commonly manipulate_output('Add', ...)'s post-save daemon
        # reload, which fails on its own (daemon busy/restarting/unreachable)
        # without undoing anything already saved. Checking "error" first told
        # the caller nothing was created when something real was — the
        # caller would retry create_output believing it needed to, leaving a
        # redundant Output behind each retry. 2026-09-08, found while
        # investigating an unrelated report.
        if not new_id:
            if messages.get("error"):
                return {"error": "; ".join(messages["error"])}
            return {"error": "Output created but unique_id not returned"}
        result = {"output_id": new_id, "output_type": output_type, "status": "created"}
        if messages.get("error"):
            # Created, but something after the save failed non-fatally (see
            # above) — surface it so the caller can decide whether to retry
            # just that part (e.g. a config reload), not the whole creation.
            result["warning"] = "; ".join(messages["error"])
        if name or params:
            cls.modify_output(new_id, name=name, params=params)
            result["configured"] = True
        if extra:
            result["ignored_args"] = list(extra.keys())
        return result

    @classmethod
    def modify_output(cls, output_id=None, name=None, params=None, **extra):
        """Update an Output's name and/or custom_options, then reload it in the daemon."""
        import json as _json
        from aot.databases.models import Output
        if not output_id:
            return {"error": "output_id is required"}
        out = Output.query.filter_by(unique_id=output_id).first()
        if not out:
            return {"error": f"Output not found: {output_id}"}
        from aot.aot_flask.access import write_scope
        write_scope.enforce(out)  # 쓰기 시점 그룹 스코프(묶여 있을 때만)
        problem = cls._device_params_problem('output', out, params)
        if problem:
            return problem
        changed = []
        if name:
            out.name = name; changed.append("name")
        if params:
            existing = {}
            try:
                existing = _json.loads(getattr(out, 'custom_options', None) or '{}')
            except Exception:
                existing = {}
            existing.update(params)
            out.custom_options = _json.dumps(existing); changed.append("custom_options")
        db.session.commit()
        try:
            # DaemonControl has no output_activate/output_deactivate — Output has no
            # is_activated concept at all (it's always "on the bus"; config reload is
            # done via output_setup, the same primitive the web route's
            # manipulate_output('Modify', output_id) uses after an edit — see
            # aot/aot_flask/utils/utils_output.py). The previous output_deactivate/
            # output_activate calls didn't exist on DaemonControl, so this reload
            # always raised AttributeError and silently no-opped (caught below) — the
            # daemon kept running with the pre-edit config.
            from aot.aot_client import DaemonControl
            d = DaemonControl()
            d.output_setup('Modify', output_id)
        except Exception as e:
            logger.warning(f"[modify_output] daemon reload failed (non-fatal): {e}")
        r = {"output_id": output_id, "status": "modified", "changed": changed}
        if extra:
            r["ignored_args"] = list(extra.keys())
        return r

    @classmethod
    def delete_output(cls, output_id=None, **extra):
        """Delete an Output by unique_id."""
        from aot.aot_flask.utils.utils_output import output_del
        if not output_id:
            return {"error": "output_id is required"}
        from aot.aot_flask.access import write_scope
        write_scope.enforce(output_id)  # 쓰기 시점 그룹 스코프(묶여 있을 때만)
        form = cls._FakeForm(output_id=output_id)
        try:
            messages = output_del(form)
        except Exception as e:
            logger.error(f"[delete_output] output_del raised: {e}")
            return {"error": str(e)}
        if not isinstance(messages, dict):
            return {"output_id": output_id, "status": "deleted"}
        # 삭제 여부와 뒤처리 실패는 다른 질문이다. error 만 보면 커밋까지 끝난
        # 삭제를 "실패" 로 읽어 같은 삭제를 다시 시도하게 되고, error 가 비었다는
        # 이유로 "deleted" 를 돌려주면 지울 것이 없었던 호출까지 성공이 된다.
        if messages.get("deleted"):
            out = {"output_id": output_id, "status": "deleted"}
            if messages.get("error"):
                # 행은 사라졌지만 데몬이 아직 이 출력을 들고 있을 수 있다 —
                # 삼키면 재시작 전까지 유령 출력이 남는다.
                out["cleanup_error"] = "; ".join(messages["error"])
                out["note"] = ("The output was deleted, but post-delete cleanup "
                               "failed. Do NOT retry the delete; report the "
                               "cleanup_error instead.")
            return out
        if messages.get("error"):
            return {"error": "; ".join(messages["error"])}
        return {"error": f"output not found or not deleted: {output_id}"}

    @classmethod
    def list_gis_inputs(cls, **extra):
        """[읽기전용] 등록된 GIS 입력(레이어) 목록 - VWorld/Google/OpenWeather 등
        지도에 얹는 외부 데이터 제공자. 각 항목의 type이 list_device_types(kind='input')
        결과의 'gis_'로 시작하는 타입과 대응한다."""
        try:
            from aot.databases.models import GeoLayer
            return {"gis_inputs": [
                {"layer_id": l.unique_id, "name": l.name, "type": l.type,
                 "is_activated": bool(l.is_activated)}
                for l in GeoLayer.query.all()]}
        except Exception as e:
            return {"error": str(e)}

    @classmethod
    def create_gis_input(cls, layer_type=None, name=None, params=None, **extra):
        """Creates a new GIS Input (map layer/provider — e.g. gis_vworld,
        gis_openweather). layer_type must come from list_device_types(kind='input'),
        filtered to 'gis_*' entries. Always created DEACTIVATED (matches the web UI's
        own default) — call activate_gis_input afterward once configured. Then use
        modify_gis_input to fill options (e.g. api_key)."""
        from aot.aot_flask.utils.utils_geo import geo_layer_add
        try:
            types = cls._input_types()
        except Exception as e:
            return {"error": f"could not load input types: {e}"}
        if not layer_type:
            gis_types = sorted(t for t in types if t.startswith('gis_'))
            return {"error": "layer_type is required", "valid_gis_types": gis_types}
        if layer_type not in types:
            gis_types = sorted(t for t in types if t.startswith('gis_'))
            return {"error": f"Unknown layer_type '{layer_type}'", "valid_gis_types": gis_types}
        form = cls._FakeForm(input_type=layer_type)
        try:
            messages = geo_layer_add(form)
        except Exception as e:
            logger.error(f"[create_gis_input] geo_layer_add raised: {e}")
            return {"error": str(e)}
        if messages.get("error"):
            return {"error": "; ".join(messages["error"])}
        from aot.databases.models import GeoLayer
        layer = GeoLayer.query.filter_by(type=layer_type).order_by(GeoLayer.id.desc()).first()
        if not layer:
            return {"error": "GIS Input created but could not be looked back up"}
        result = {"layer_id": layer.unique_id, "layer_type": layer_type,
                  "status": "created", "is_activated": False}
        if name or params:
            cls.modify_gis_input(layer.unique_id, name=name, params=params)
            result["configured"] = True
        if extra:
            result["ignored_args"] = list(extra.keys())
        return result

    @classmethod
    def modify_gis_input(cls, layer_id=None, name=None, params=None, **extra):
        """Updates a GIS Input's name and/or options (e.g. api_key), direct write —
        same lightweight pattern as modify_input (no full form replay). params:
        dict of option_id -> value (e.g. {'api_key': '...'})."""
        import json as _json
        from aot.databases.models import GeoLayer
        if not layer_id:
            return {"error": "layer_id is required"}
        layer = GeoLayer.query.filter_by(unique_id=layer_id).first()
        if not layer:
            return {"error": f"GIS Input not found: {layer_id}"}
        if params and not isinstance(params, dict):
            return {"error": "params must be an object of {option_id: value}. Nothing was changed."}
        changed = []
        if name:
            layer.name = name; changed.append("name")
        if params and isinstance(params, dict):
            existing = {}
            try:
                existing = _json.loads(layer.options or '{}')
            except Exception:
                existing = {}
            existing.update(params)
            layer.options = _json.dumps(existing); changed.append("options")
        db.session.commit()
        try:
            from aot.aot_flask.utils.utils_geo import invalidate_geo_config_cache
            invalidate_geo_config_cache()
        except Exception as e:
            logger.warning(f"[modify_gis_input] cache invalidation failed (non-fatal): {e}")
        r = {"layer_id": layer_id, "status": "modified", "changed": changed}
        if extra:
            r["ignored_args"] = list(extra.keys())
        return r

    @classmethod
    def activate_gis_input(cls, layer_id=None, active=True, **extra):
        """Activates or deactivates a GIS Input. New GIS Inputs are created
        deactivated (create_gis_input) — call this once options are configured."""
        from aot.aot_flask.utils.utils_geo import geo_layer_activate
        if not layer_id:
            return {"error": "layer_id is required"}
        want = cls._as_active(active)
        if want is None:
            return {"error": "active must be true or false"}
        active = want
        try:
            messages = geo_layer_activate(layer_id, active=active)
        except Exception as e:
            logger.error(f"[activate_gis_input] geo_layer_activate raised: {e}")
            return {"error": str(e)}
        if messages.get("error"):
            return {"error": "; ".join(messages["error"])}
        return {"layer_id": layer_id, "status": "activated" if active else "deactivated"}

    @classmethod
    def delete_gis_input(cls, layer_id=None, **extra):
        """Deletes a GIS Input by unique_id."""
        from aot.aot_flask.utils.utils_geo import geo_layer_del
        if not layer_id:
            return {"error": "layer_id is required"}
        try:
            messages = geo_layer_del(layer_id)
        except Exception as e:
            logger.error(f"[delete_gis_input] geo_layer_del raised: {e}")
            return {"error": str(e)}
        if isinstance(messages, dict) and messages.get("error"):
            return {"error": "; ".join(messages["error"])}
        return {"layer_id": layer_id, "status": "deleted"}

