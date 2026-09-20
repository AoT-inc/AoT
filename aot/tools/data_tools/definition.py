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
        changed = []
        if name:
            inp.name = name; changed.append("name")
        if params and isinstance(params, dict):
            existing = {}
            try:
                existing = _json.loads(getattr(inp, 'custom_options', None) or '{}')
            except Exception:
                existing = {}
            existing.update(params)
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
        try:
            messages = input_del(input_id)
        except Exception as e:
            logger.error(f"[delete_input] input_del raised: {e}")
            return {"error": str(e)}
        if isinstance(messages, dict) and messages.get("error"):
            return {"error": "; ".join(messages["error"])}
        return {"input_id": input_id, "status": "deleted"}

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
        changed = []
        if name:
            out.name = name; changed.append("name")
        if params and isinstance(params, dict):
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
        try:
            messages = geo_layer_activate(layer_id, active=bool(active))
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

