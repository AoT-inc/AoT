import logging

logger = logging.getLogger(__name__)


from aot.tools.aot_data_tool_service import _control_targets_for
from aot.tools.aot_data_tool_service import _plot_ended_on
from aot.tools.aot_data_tool_service import _plot_started_on
from aot.aot_flask.extensions import db
from aot.databases.models import Camera
from aot.databases.models import CustomController
from aot.databases.models import DeviceMeasurements
from aot.databases.models import GeoShape
from aot.databases.models import Input
from aot.databases.models import Output
from aot.utils.command_origin import TYPE_AI
from aot.utils.execution_context import clear_execution_context
from aot.utils.execution_context import set_execution_context
from aot.utils.time_utils import serialize_ts
from datetime import datetime
from sqlalchemy import or_


class DeviceToolsMixin:

    _SEARCH_STOPWORDS = frozenset({
        'a', 'an', 'the', 'is', 'are', 'was', 'were', 'be', 'been', 'being',
        'for', 'of', 'to', 'in', 'on', 'at', 'by', 'with', 'and', 'or', 'not',
        'this', 'that', 'these', 'those', 'it', 'its', 'as', 'from',
    })

    @classmethod
    def _device_parent_map(cls):
        """{Input/Output.unique_id: (parent_device_id, parent_device_name)}.

        복합장치(Device) 티어는 새 테이블이 아니라 is_device=True 를 선언한
        CustomController 행이고, 하위 Input/Output 은 parent_device_id 로
        그 행을 가리킨다(.local/plans/device_group_console_plan.md). AI 쪽
        검색·목록 도구는 지금까지 이 관계를 전혀 몰라서, PLC 하나가 Input과
        Output 으로 흩어져 보이면 이름이 비슷한 것들을 각각 추측해서 찾아야
        했다 — 이 맵을 결과에 섞어 넣으면 "이 Input 은 이 장치 소속"이라는
        사실이 데이터에 명시된다. 새 MCP 도구를 만들지 않고 기존 도구의
        결과에 필드만 얹는다(Phase 5).
        """
        try:
            from aot.databases.models.controller import CustomController
            from aot.utils.functions import device_module_names

            device_names = device_module_names()
            if not device_names:
                return {}

            id_to_name = {
                d.unique_id: d.name
                for d in CustomController.query.filter(
                    CustomController.device.in_(device_names)).all()
            }
            if not id_to_name:
                return {}

            mapping = {}
            for inp in Input.query.filter(Input.parent_device_id.in_(id_to_name)).all():
                mapping[inp.unique_id] = (inp.parent_device_id, id_to_name[inp.parent_device_id])
            for out in Output.query.filter(Output.parent_device_id.in_(id_to_name)).all():
                mapping[out.unique_id] = (out.parent_device_id, id_to_name[out.parent_device_id])
            return mapping
        except Exception:
            return {}

    @classmethod
    def _annotate_device_membership(cls, results):
        """search_devices()/get_device_list_tool() 결과 리스트에
        parent_device_id/parent_device_name 을 제자리에서 채운다(있는 것만)."""
        parent_map = cls._device_parent_map()
        if not parent_map:
            return results
        for r in results:
            if r.get('type') in ('input', 'output'):
                parent = parent_map.get(r.get('id'))
                if parent:
                    r['parent_device_id'], r['parent_device_name'] = parent
        return results

    @classmethod
    def _annotate_device_zone(cls, results):
        """결과에 소속 구역 이름을 제자리에서 채운다(있는 것만)."""
        try:
            from aot.tools import providers
            zmap = providers.get('device_zone_map')()
        except Exception:
            return results
        for r in results:
            if r.get('type') in ('input', 'output') and zmap.get(r.get('id')):
                r['zone'] = zmap[r['id']]
        return results

    @classmethod
    def search_devices(cls, query=None, measurement_type=None):
        """
        이름 또는 타입으로 장치를 검색합니다.
        v2: Multi-token query expansion.
          - Splits query by whitespace and searches each token independently
            (e.g. "1구역 밸브" → searches "1구역" AND "밸브" separately).
          - Loads term aliases from AIDomainGlossary (category='term_alias')
            to handle user-specific terms (e.g. "1포장" → "1구역").
          - Deduplicates results by unique_id.
        v3: measurement_type 필터.
          - 그 측정을 실제로 가진 장치만 남긴다(이름 무관).
          - query 없이 단독으로도 쓴다 — "토양수분 센서 전부" 가 한 번에 온다.
          - query 와 함께 주면 교집합("1포장 안의 토양수분 센서").
        """
        if not query and not measurement_type:
            return {"error": "query or measurement_type is required"}

        try:
            import re

            candidate_ids = None
            if measurement_type:
                candidate_ids = cls._device_ids_with_measurement(
                    measurement_type)
                if not candidate_ids:
                    return {"results": [], "count": 0,
                            "message": ("No device has a measurement matching "
                                        "'%s'." % measurement_type)}

            # 측정 종류만 물은 경우. 이름 검색 경로(토큰 확장·별칭·구역 확장)를
            # 태울 근거가 없으므로 후보를 그대로 낸다.
            if not query:
                results = []
                for item in Input.query.filter(
                        Input.unique_id.in_(list(candidate_ids))).all():
                    results.append({"id": item.unique_id, "name": item.name,
                                    "type": "input", "device": item.device})
                for item in Output.query.filter(
                        Output.unique_id.in_(list(candidate_ids))).all():
                    results.append({"id": item.unique_id, "name": item.name,
                                    "type": "output", "device": item.output_type})
                # 집계 함수(VPD·평균 등)도 자기 측정 채널을 갖는다. 빼면
                # measurement_type='vapor_pressure_deficit' 이 0건이 되는데,
                # get_sensor_detail 은 그 값을 읽을 수 있다(찾을 수만 없다).
                for item in CustomController.query.filter(
                        CustomController.unique_id.in_(list(candidate_ids))).all():
                    results.append({"id": item.unique_id, "name": item.name,
                                    "type": "function", "device": item.device})
                results = cls._annotate_device_zone(results)
                results = cls._annotate_device_membership(results)
                return {"results": results, "count": len(results)}

            def _normalize_variants(term):
                """Generate search variants for a term to handle spacing differences.
                e.g. '밸브3' → ['밸브3', '밸브 3']
                     '밸브 3' → ['밸브 3', '밸브3']
                """
                variants = [term]
                # Collapse all whitespace → no-space variant
                no_space = re.sub(r'\s+', '', term)
                if no_space != term:
                    variants.append(no_space)
                # Insert space between Korean (Hangul) block and digit (or vice versa)
                spaced = re.sub(r'([\uAC00-\uD7A3])(\d)', r'\1 \2', term)
                spaced = re.sub(r'(\d)([\uAC00-\uD7A3])', r'\1 \2', spaced)
                if spaced != term:
                    variants.append(spaced)
                return variants

            # Build search token list: individual tokens + full query.
            # Drop single-letter alphabetic tokens and common English stopwords —
            # each becomes a `%term%` LIKE against name/device_type, and a token
            # like "a" or "for" incidentally substring-matches almost every row
            # (confirmed: "a" alone matched 26/26 outputs in a real dev DB via
            # output_type, e.g. names containing a bare "a" letter) rather than
            # actually narrowing the search. Digits are kept (e.g. "3" in "zone 3"
            # is real device-numbering signal, matching "밸브3"/"AoT-C-003").
            tokens = [t.strip() for t in query.split() if t.strip()]
            tokens = [t for t in tokens
                      if t.lower() not in cls._SEARCH_STOPWORDS
                      and not (len(t) == 1 and t.isalpha())]
            _base_terms = [query] + tokens
            # Expand each base term with normalization variants
            _expanded = []
            for t in _base_terms:
                for v in _normalize_variants(t):
                    if v not in _expanded:
                        _expanded.append(v)
            search_terms = _expanded

            # Load term aliases from AIDomainGlossary
            try:
                from aot.databases.models.ai_domain_glossary import AIDomainGlossary
                alias_rows = AIDomainGlossary.query.filter_by(category='term_alias', is_active=True).all()
                alias_map = {a.term.lower(): a.definition for a in alias_rows}
            except Exception:
                alias_map = {}

            # Expand each token with its alias (if any), including normalization variants
            for token in list(tokens):
                canonical = alias_map.get(token.lower())
                if canonical:
                    for v in _normalize_variants(canonical):
                        if v not in search_terms:
                            search_terms.append(v)

            # 번역된 이름으로 검색할 수 있어야 한다. 사용자 지정 이름 번역이
            # 켜져 있으면 화면에는 "1号ハウス" 가 보이는데 DB 에는 "1번 하우스"
            # 로 저장되어 있고, 사용자는 자기가 보는 이름으로 말한다.
            # docs/design/user-string-live-translation.md
            try:
                from aot.tools import providers
                reverse_lookup = providers.get('reverse_lookup')
                for term in [query] + tokens:
                    source = reverse_lookup(term)
                    if source and source not in search_terms:
                        search_terms.append(source)
            except Exception:
                pass

            seen_ids = set()
            results = []

            for term in search_terms:
                q = f"%{term}%"
                for item in Input.query.filter(
                    or_(Input.name.like(q), Input.device.like(q))
                ).all():
                    if item.unique_id not in seen_ids:
                        seen_ids.add(item.unique_id)
                        results.append({"id": item.unique_id, "name": item.name, "type": "input", "device": item.device})

                for item in Output.query.filter(
                    or_(Output.name.like(q), Output.output_type.like(q))
                ).all():
                    if item.unique_id not in seen_ids:
                        seen_ids.add(item.unique_id)
                        results.append({"id": item.unique_id, "name": item.name, "type": "output", "device": item.output_type})

                # 복합장치(Device) — is_device=True 모듈이 만드는 CustomController
                # 행. PLC 처럼 "장치 하나"로 물어보면 그 자체가 검색되고,
                # member_ids 로 하위 Input/Output 을 바로 가리킬 수 있다.
                try:
                    # CustomController 는 모듈 상단에서 임포트한다. 여기서 다시
                    # 지역 임포트하면 그 이름이 함수 전체의 지역변수가 되어,
                    # 이 블록보다 앞에서 쓰는 자리가 UnboundLocalError 로 죽는다.
                    from aot.utils.functions import device_module_names
                    _dev_names = device_module_names()
                    if _dev_names:
                        for item in CustomController.query.filter(
                            CustomController.device.in_(_dev_names),
                            CustomController.name.like(q)
                        ).all():
                            if item.unique_id not in seen_ids:
                                seen_ids.add(item.unique_id)
                                member_ids = (
                                    [i.unique_id for i in Input.query.filter_by(
                                        parent_device_id=item.unique_id).all()] +
                                    [o.unique_id for o in Output.query.filter_by(
                                        parent_device_id=item.unique_id).all()]
                                )
                                results.append({
                                    "id": item.unique_id, "name": item.name,
                                    "type": "device", "device": item.device,
                                    "member_ids": member_ids,
                                })
                except Exception:
                    pass

                for item in Camera.query.filter(
                    or_(Camera.name.like(q), Camera.camera_type.like(q))
                ).all():
                    if item.unique_id not in seen_ids:
                        seen_ids.add(item.unique_id)
                        results.append({"id": item.unique_id, "name": item.name, "type": "camera", "device": item.camera_type})

                # v26.10: Include GeoShapes (Sites/Zones) in search results
                # v26.11: Also check feature.properties.name (GeoJSON standard field)
                for item in GeoShape.query.all():
                    feat = item.feature or {}
                    feat_props = feat.get('properties', {})
                    meta = item.meta_json or {}
                    meta_props = meta.get('properties', {})
                    name = (feat_props.get('name') or feat_props.get('label')
                            or meta_props.get('name') or meta_props.get('label')
                            or item.geo_id)
                    if term.lower() in name.lower() or term.lower() in item.geo_id.lower():
                        if item.unique_id not in seen_ids:
                            seen_ids.add(item.unique_id)
                            results.append({
                                "id": item.unique_id,
                                "geo_id": item.geo_id,
                                "name": name,
                                "type": "zone",
                                "device": item.type
                            })

            # Zone-aware expansion: devices carry a SPATIALLY-derived zone (their geo
            # shape's centroid inside a zone polygon). When the query references a zone
            # (e.g. "1-4구역"), include the devices LOCATED in that zone — otherwise
            # "1포장 1-4구역 밸브 켜줘" finds the zone shape but never the valves in it.
            # `zone_scoped_query` also flags this for the caller (see _zone_scope_note
            # below): a location-scoped device search must not be read as "everything
            # that exists at this location" — plots/crops live in a separate registry
            # keyed by variety name, not by zone name, so they never surface here.
            zone_scoped_query = False
            try:
                from aot.tools import providers
                zmap = providers.get('device_zone_map')()  # {device_id: zone_name}
            except Exception:
                zmap = {}
            if zmap:
                # Annotate existing device results with their zone.
                for r in results:
                    if r.get('type') in ('input', 'output') and zmap.get(r['id']):
                        r['zone'] = zmap[r['id']]

                def _add_device_by_id(did, zn):
                    if did in seen_ids:
                        return
                    o = Output.query.filter_by(unique_id=did).first()
                    if o:
                        seen_ids.add(did)
                        results.append({"id": o.unique_id, "name": o.name, "type": "output", "device": o.output_type, "zone": zn})
                        return
                    i = Input.query.filter_by(unique_id=did).first()
                    if i:
                        seen_ids.add(did)
                        results.append({"id": i.unique_id, "name": i.name, "type": "input", "device": i.device, "zone": zn})

                zone_index = {}
                for did, zn in zmap.items():
                    zone_index.setdefault(zn, []).append(did)

                # Determine the location the query scopes to, most-specific first.
                # (1) Zone-level: a specific zone is named (e.g. "1-4구역" → "1-4").
                #     Require length ≥2 so a bare "1" in "1포장" doesn't match.
                # (2) Site-level: only when NO specific zone is named — a whole site
                #     (e.g. "3포장" / "site 3"). Zone names follow the "N-M" convention
                #     where N is the site number, so "3포장" → every zone "3-*". A
                #     specific zone always wins over its site ("1포장 1-4구역" → 1-4).
                referenced = {zn for zn in zone_index if zn and len(zn) >= 2 and zn in query}
                allowed_zones = set(referenced)
                if not referenced:
                    def _shape_display_name(s):
                        feat = s.feature or {}
                        if isinstance(feat, str):
                            import json as _json
                            try:
                                feat = _json.loads(feat)
                            except Exception:
                                feat = {}
                        props = feat.get('properties', {}) if isinstance(feat, dict) else {}
                        return str(props.get('name') or props.get('label') or '').strip()

                    # (a) Geometric: the query names an actual 'site' GeoShape → every
                    # descendant zone/feature is in scope, regardless of naming
                    # convention (a zone need not be named "N-M" to belong to site N).
                    from aot.utils.geo_hierarchy import geo_descendant_shapes
                    for site_shape in GeoShape.query.filter_by(type='site').all():
                        s_name = _shape_display_name(site_shape)
                        if s_name and len(s_name) >= 2 and s_name in query:
                            for child in geo_descendant_shapes(site_shape):
                                c_name = _shape_display_name(child)
                                if c_name and c_name in zone_index:
                                    allowed_zones.add(c_name)

                    # (b) Naming-convention fallback ("N포장"/"site N" → zone "N-*") —
                    # kept for zones that follow this convention but whose polygon
                    # isn't (yet) drawn spatially inside the site's polygon.
                    site_nums = set(re.findall(r'(\d+)\s*포장', query))
                    site_nums |= {m for m in re.findall(r'site\s*(\d+)', query, re.IGNORECASE)}
                    if site_nums:
                        for zn in zone_index:
                            m = re.match(r'\s*(\d+)\s*[-–]', zn or '')
                            if m and m.group(1) in site_nums:
                                allowed_zones.add(zn)

                zone_scoped_query = bool(allowed_zones)

                if allowed_zones:
                    # Include every device located in the scoped zones...
                    for zn in allowed_zones:
                        for did in zone_index.get(zn, []):
                            _add_device_by_id(did, zn)
                    # ...and DROP device results that are outside that location. A
                    # location-scoped command ("1포장 1-4구역 밸브") must not sweep in
                    # broad name matches (밸브1..51) that live nowhere near the zone.
                    results = [r for r in results
                               if r.get('type') not in ('input', 'output')
                               or r.get('zone') in allowed_zones]

            if candidate_ids is not None:
                # 이름 검색이 끝난 뒤에 거른다 — 구역 확장까지 마친 집합에
                # 걸어야 "1포장 안의 토양수분 센서" 가 성립한다. 측정을 갖지
                # 않는 종류(구역·카메라)는 이 질문의 답이 아니므로 함께 빠진다.
                results = [r for r in results if r.get('id') in candidate_ids]

            results = cls._annotate_device_membership(results)
            out = {"results": results, "count": len(results)}
            notes = []
            note = cls._complex_device_note(results)
            if note:
                notes.append(note)
            note = cls._zone_scope_note(zone_scoped_query)
            if note:
                notes.append(note)
            if notes:
                out["_reading"] = notes
            return out
        except Exception as e:
            return {"error": str(e)}

    @classmethod
    def _zone_scope_note(cls, zone_scoped_query):
        """질의가 zone/site를 가리켰을 때만, 이 결과의 한계를 알린다.

        `search_devices`는 장치(Input/Output/Camera/복합장치)와 구역 도형의
        **이름**만 뒤진다. 작물 구획(plot)은 별도 레지스트리에 품종명으로
        등록돼 zone 이름을 담지 않으므로 여기 결과에 절대 나타나지 않는다.
        "이 구역 장치를 찾아봤는데 결과가 이거다"를 "이 구역엔 이게 전부다"로
        읽으면(특히 작물 유무 판단) 실제 사례로 확인된 오판이 재발한다
        (.local/plans/mcp_tool_audit_tracker.md 8번 항목).
        """
        if not zone_scoped_query:
            return None
        return ("This query was matched to a specific zone/site. These results are "
                "devices and zone shapes whose NAME matched — they are not an "
                "inventory of everything at that location. Plots/crops are a "
                "separate registry keyed by variety name (not by zone name), so "
                "they never appear here even when a plot is actively growing "
                "there. Do not conclude 'no crop/plot here' from this result — "
                "call list_plots (filtered by map_id or the plot's zone) to check "
                "plot existence.")

    @classmethod
    def _complex_device_note(cls, results):
        """복합장치(PLC 등)가 **실제로 결과에 있을 때만** 그 규칙을 낸다.

        복합장치는 한 물리 장치의 읽기/쓰기가 Input·Output 으로 쪼개져 있어,
        모르면 하위 항목을 독립 장치로 취급하게 된다. 다만 결과에 복합장치가
        없으면 그 설명은 매번 읽히기만 하고 쓰이지 않는다 — 그래서 도구 설명이
        아니라 결과가 말한다.
        """
        rows = results or []
        if not (any(r.get('type') == 'device' and r.get('member_ids') for r in rows)
                or any(r.get('parent_device_id') for r in rows)):
            return None
        return ("A complex device (e.g. a PLC) is in these results: one physical "
                "unit whose readings/controls are split across separate Input and "
                "Output entries. A 'device' row lists its member_ids, and a member "
                "row carries parent_device_id + parent_device_name. Answer and act "
                "at the parent device level rather than treating a member as "
                "standalone.")

    @classmethod
    def get_device_list_tool(cls, **kwargs):
        """
        Returns all registered devices (inputs, outputs, cameras, complex
        devices) with id/name/type.
        Used for full device listing queries (no keyword filter).

        @ANCHOR: GET_DEVICE_LIST_TOOL
        """
        try:
            results = []
            seen_ids = set()
            for item in Input.query.all():
                if item.unique_id not in seen_ids:
                    seen_ids.add(item.unique_id)
                    results.append({"id": item.unique_id, "name": item.name, "type": "input", "device": item.device})
            for item in Output.query.all():
                if item.unique_id not in seen_ids:
                    seen_ids.add(item.unique_id)
                    results.append({"id": item.unique_id, "name": item.name, "type": "output", "device": item.output_type})
            for item in Camera.query.all():
                if item.unique_id not in seen_ids:
                    seen_ids.add(item.unique_id)
                    results.append({"id": item.unique_id, "name": item.name, "type": "camera", "device": item.camera_type})

            # 복합장치(Device) — search_devices() 와 동일한 이유로 목록에도
            # 포함한다. 여기서는 필터가 없으므로 전수 조회.
            try:
                from aot.databases.models.controller import CustomController
                from aot.utils.functions import device_module_names
                _dev_names = device_module_names()
                if _dev_names:
                    for item in CustomController.query.filter(
                            CustomController.device.in_(_dev_names)).all():
                        if item.unique_id not in seen_ids:
                            seen_ids.add(item.unique_id)
                            member_ids = (
                                [i.unique_id for i in Input.query.filter_by(
                                    parent_device_id=item.unique_id).all()] +
                                [o.unique_id for o in Output.query.filter_by(
                                    parent_device_id=item.unique_id).all()]
                            )
                            results.append({
                                "id": item.unique_id, "name": item.name,
                                "type": "device", "device": item.device,
                                "member_ids": member_ids,
                            })
            except Exception:
                pass

            results = cls._annotate_device_membership(results)
            out = {"results": results, "count": len(results)}
            note = cls._complex_device_note(results)
            if note:
                out["_reading"] = [note]
            return out
        except Exception as e:
            return {"error": str(e)}

    @classmethod
    def operate_device_tool(cls, device_id, state, **kwargs):
        """
        [분류 A - 물리 제어 전용 도구]
        장치를 직접 제어합니다. (on, off, open, close, set_value 등)
        """
        try:
            if not device_id or not state:
                return {"error": "Missing device_id or state"}

            # 1. 상태값 검증
            ALLOWED_STATES = ['on', 'off', 'open', 'close', 'set_value']
            state = state.lower()
            if state not in ALLOWED_STATES:
                return {"error": f"Invalid state value: {state}. Allowed values: {ALLOWED_STATES}"}

            # 2. 장치 존재 여부 확인 (UUID 또는 이름)
            # 이름이 겹치면 고르지 않는다 — `.first()` 로 아무거나 집으면
            # 엉뚱한 밸브를 연다(2026-08-28: v11 이 두 개였다).
            from aot.services.resolvers.device_resolver import resolve_output
            match = resolve_output(device_id)
            if match.error:
                return {"error": match.error}
            target = match.row
            if not target:
                return {"error": f"Device (output) to control not found: {device_id}"}

            # 3. 시간/값 파라미터 정규화 (Deep Discovery)
            # duration_seconds, duration_minutes, duration, value 등 다양한 variant 대응
            d_sec = kwargs.get('duration_seconds')
            d_min = kwargs.get('duration_minutes') or kwargs.get('duration')
            val = kwargs.get('value')
            
            # 우선순위: duration_seconds > duration_minutes/duration (*60) > value > 0
            if d_sec is not None:
                duration = float(d_sec)
            elif d_min is not None:
                duration = float(d_min) * 60.0
            else:
                duration = float(val or 0)

            # 4. @ANCHOR: OPERATE_DEVICE_CHANNEL_INJECTION (TASK_17)
            # Resolve physical output_channel from OutputChannel table before daemon call.
            # Eliminates 'output channel doesn't exist: None' — channel=0 is a valid integer.
            resolved_uid = target.unique_id
            output_channel = None
            try:
                from aot.databases.models.output import OutputChannel as _OC
                oc_row = _OC.query.filter_by(output_id=resolved_uid).first()
                if oc_row is not None and oc_row.channel is not None:
                    output_channel = int(oc_row.channel)
                    logger.info(
                        f"[operate_device_tool][CHANNEL_RESOLVED] "
                        f"device='{resolved_uid}' → output_channel={output_channel}"
                    )
                else:
                    # [PC-099-ERROR] DB diagnostic: row exists but channel is NULL, or no row at all
                    _diag = (
                        f"oc_row={oc_row!r}, "
                        f"channel={oc_row.channel if oc_row else 'NO_ROW'}, "
                        f"output_type='{target.output_type}'"
                    )
                    logger.error(
                        f"[PC-099-ERROR][CHANNEL_NULL] output_channel is None for "
                        f"device='{resolved_uid}'. DB diagnostic: {_diag}. "
                        f"Daemon call will proceed with channel=None — expect hardware error."
                    )
            except Exception as _ch_err:
                logger.error(
                    f"[PC-099-ERROR][CHANNEL_LOOKUP_FAILED] OutputChannel query failed "
                    f"for device='{resolved_uid}': {_ch_err}"
                )

            from aot.aot_client import DaemonControl
            daemon = DaemonControl()

            # AI 가 낸 명령임을 명시한다. 이 도구는 웹 요청 문맥 안에서도(사용자가
            # AI 에게 시킨 경우) MCP 서버 프로세스에서도 불린다. 표시가 없으면
            # 앞은 사람이 직접 누른 것과 구분되지 않고, 뒤는 출처 불명(unknown)으로
            # 남아 우회 접근 탐지 신호를 흐린다. override 라 요청 문맥보다 우선한다.
            set_execution_context(
                source_type=TYPE_AI,
                source_id=kwargs.get('agent_id') or 'operate_device')
            try:
                if state in ('on', 'open'):
                    out_err, out_msg = daemon.output_on_off(
                        resolved_uid, 'on', output_type='sec', amount=duration,
                        output_channel=output_channel
                    )
                elif state in ('off', 'close'):
                    out_err, out_msg = daemon.output_on_off(
                        resolved_uid, 'off', output_type='sec', amount=0,
                        output_channel=output_channel
                    )
                elif state == 'set_value':
                    out_err, out_msg = daemon.output_on_off(
                        resolved_uid, 'on', output_type='value', amount=duration,
                        output_channel=output_channel
                    )
                else:
                    return {"error": f"Unsupported state: {state}"}
            finally:
                clear_execution_context()

            if out_err:
                logger.error(f"[operate_device_tool] Daemon error: {out_msg}")
                return {"error": f"Device control failed: {out_msg}"}
            
            logger.info(f"[operate_device_tool] OK: device={resolved_uid}({target.name}), state={state}, duration={duration}s")
            return {"status": "success", "execution_result": out_msg, "resolved_duration": duration}
        except Exception as e:
            logger.error(f"Error in operate_device_tool: {e}")
            return {"error": f"Error while controlling device: {str(e)}"}

    @classmethod
    def get_device_measurements(cls, device_id):
        """
        Returns all measurement channels for a given Input or CustomController device_id.
        Also accepts a search_devices result dict — extracts the first device_id automatically.
        Used by the AI to resolve measurement IDs needed for select_measurement options.
        """
        try:
            # Accept search_devices result dict (e.g. {"results": [{"id": "..."}], "count": 1})
            if isinstance(device_id, dict):
                results = device_id.get('results') or device_id.get('result', {}).get('results', [])
                if results and isinstance(results, list):
                    device_id = results[0].get('id') or results[0].get('unique_id') or results[0].get('device_id')
            if not device_id or not isinstance(device_id, str):
                return {"error": "device_id is required (string UUID)"}

            rows = DeviceMeasurements.query.filter_by(device_id=device_id).all()
            if not rows:
                return {"error": f"No measurements found for device_id: {device_id}"}

            measurements = [
                {
                    "measurement_id": r.unique_id,
                    "channel": r.channel,
                    "measurement": r.measurement,
                    "unit": r.unit,
                    "name": getattr(r, 'name', ''),
                    # Ready-to-use value for select_measurement fields: "device_id,measurement_id"
                    "select_value": f"{device_id},{r.unique_id}",
                }
                for r in rows
            ]

            # Convenience map: measurement_type → select_value  (e.g. "temperature" → "uuid,uuid")
            # Makes it easy for the AI to pick the right channel by type name.
            select_by_type = {
                m["measurement"]: m["select_value"]
                for m in measurements
            }

            return {
                "device_id": device_id,
                "measurements": measurements,
                "select_by_type": select_by_type,
            }
        except Exception as e:
            return {"error": str(e)}

    @classmethod
    def _kind_of_controller(cls, controller):
        """CustomController 행 하나 → 'device'(복합장치) 또는 'function'(그 외).

        저장 구조는 하나(custom_controller 테이블)라, 행 자체가 아니라 그 행의
        `device` 컬럼이 가리키는 모듈이 `is_device` 를 선언했는지로 가른다
        (`_device_parent_map` 상단 주석과 같은 판정, `device_module_names` 참조).
        """
        from aot.utils.functions import device_module_names
        try:
            return 'device' if controller.device in device_module_names() else 'function'
        except Exception:
            return 'function'

    @classmethod
    def _resolve_device_target(cls, token):
        """unique_id 또는 이름 → (row, kind, None) 확정, 또는 (None, None, 오류dict).

        Input·Output·CustomController(장치/함수) 세 갈래를 함께 본다. unique_id
        정확일치가 먼저다(도구 체이닝이 낸 uuid 를 이름 검색으로 새게 하지
        않기 위해 — `geo_distance.resolve_query` 와 같은 순서). 그 다음은 이름
        **정확**일치이고, 여러 종류에 걸쳐 모은다 — Input 과 Output 이 같은
        이름을 쓰는 경우가 실제로 있다. 겹치면 고르지 않고
        `needs_disambiguation` 과 후보를 돌려준다(space.py 의
        `distance_between`/`geo_distance._ambiguous_error` 와 같은 형식 —
        uuid 를 실어서 다음 호출이 바로 되물을 수 있게 한다).
        """
        token = (token or '').strip()
        if not token:
            return None, None, {"error": "device_id is required (unique_id or name)"}

        # 0) unique_id 정확일치.
        row = Input.query.filter_by(unique_id=token).first()
        if row is not None:
            return row, 'input', None
        row = Output.query.filter_by(unique_id=token).first()
        if row is not None:
            return row, 'output', None
        row = CustomController.query.filter_by(unique_id=token).first()
        if row is not None:
            return row, cls._kind_of_controller(row), None

        # 1) 이름 정확일치 — 세 테이블을 한꺼번에 모은다.
        candidates = []
        for r in Input.query.filter(Input.name == token).all():
            candidates.append((r, 'input'))
        for r in Output.query.filter(Output.name == token).all():
            candidates.append((r, 'output'))
        for r in CustomController.query.filter(CustomController.name == token).all():
            candidates.append((r, cls._kind_of_controller(r)))

        if not candidates:
            return None, None, {"error": f"Device not found: {token}"}

        if len(candidates) > 1:
            _MAX_LISTED = 10
            listed = candidates[:_MAX_LISTED]
            return None, None, {
                "error": ("%r matches %d things — say which one (pass its "
                          "unique_id)." % (token, len(candidates))),
                "needs_disambiguation": True,
                "query": token,
                "candidates": [
                    {"id": r.unique_id, "name": r.name, "kind": k,
                     "module_type": getattr(r, 'device', None)
                                    or getattr(r, 'output_type', None)}
                    for (r, k) in listed
                ],
                "candidates_shown": len(listed),
                "candidates_total": len(candidates),
            }

        row, kind = candidates[0]
        return row, kind, None

    @classmethod
    def _summarize_connection_fields(cls, custom_options_json):
        """소유 장치의 `custom_options`(JSON 문자열)에서 연결 필드만 요약한다.

        **비밀번호·토큰·키 값은 절대 싣지 않는다** — 키 이름이 secret 패턴에
        걸리면 값 대신 'set'/'unset' 만 낸다. 그 밖의 스칼라 값(호스트·포트·
        주소 등)은 그대로 낸다. 중첩된 dict/list 는 "연결 필드" 로 보기엔
        너무 크고 장치마다 구조가 달라 여기서는 건너뛴다.
        """
        import json as _json
        import re as _re

        if not custom_options_json:
            return {}
        try:
            opts = _json.loads(custom_options_json)
        except (ValueError, TypeError):
            return {}
        if not isinstance(opts, dict):
            return {}

        secret_pat = _re.compile(
            r'password|token|secret|key|credential|passphrase|auth', _re.I)
        out = {}
        for k, v in opts.items():
            if secret_pat.search(str(k)):
                out[k] = 'set' if v else 'unset'
            elif isinstance(v, (str, int, float, bool)) and v not in (None, ''):
                out[k] = v
        return out

    @classmethod
    def _spatial_label(cls, spatial_kind, spatial_id):
        """GeoBinding.spatial_id → (사람이 읽는 이름, 공간 종류) 또는 (None, None)."""
        try:
            if spatial_kind == 'shape':
                shape = GeoShape.query.filter_by(unique_id=spatial_id).first()
                if not shape:
                    return None, None
                from aot.aot_flask.geo import plot_context
                name = plot_context._shape_name(shape) or shape.geo_id
                return name, shape.type
            if spatial_kind in ('fitting', 'actuator', 'sensor_role', 'weather'):
                from aot.databases.models import GeoFacility
                fac_id = str(spatial_id).split(':')[0]
                fac = GeoFacility.query.filter_by(unique_id=fac_id).first()
                return (fac.name if fac else None), 'facility'
        except Exception:
            logger.warning("get_device_detail: 공간 이름 해석 실패 (%s, %s)",
                            spatial_kind, spatial_id, exc_info=True)
        return None, None

    @classmethod
    def _geo_bindings_for(cls, device_id):
        """이 장치가 현재 매여 있는 공간 목록, 또는 (빈 목록, 이유)."""
        try:
            from aot.aot_flask.geo import device_binding
            rows = device_binding.bindings_for_device(device_id)
        except Exception:
            logger.warning("get_device_detail: GeoBinding 조회 실패 (%s)",
                            device_id, exc_info=True)
            return [], "담당 구역을 확인할 수 없습니다(조회 실패)."
        if not rows:
            return [], "지도의 어느 공간에도 배정되지 않았습니다."
        out = []
        for b in rows:
            name, space_type = cls._spatial_label(b.spatial_kind, b.spatial_id)
            out.append({
                "spatial_kind": b.spatial_kind,
                "role": b.role,
                "space_type": space_type,
                "space_name": name,
                "space_id": b.spatial_id,
            })
        return out, None

    @classmethod
    def _device_constraints(cls, kind, what):
        """무엇을 못 하는가 — 이 항목을 움직이는 도구가 승인 대상인지, 비활성인지."""
        from aot.tools.tool_registry import approval_required_tools

        if kind == 'output':
            controlling_tools = ['operate_device', 'set_output_state']
        elif kind in ('device', 'function'):
            controlling_tools = ['activate_function', 'deactivate_function']
        else:
            controlling_tools = []

        requires_approval = None
        if controlling_tools:
            approval_set = approval_required_tools()
            requires_approval = any(t in approval_set for t in controlling_tools)

        notes = []
        if kind == 'input':
            notes.append("센서/입력은 읽기 전용입니다 — 이 항목을 직접 "
                        "제어하는 도구가 없습니다.")
        if what.get('active') is False:
            notes.append("비활성 상태입니다 — 지금 동작하지 않습니다.")

        return {
            "controlling_tools": controlling_tools,
            "requires_approval": requires_approval,
            "notes": notes,
        }

    @classmethod
    def get_device_detail(cls, device_id=None, **extra):
        """장치 하나의 정체·위치·측정·제어·통신·담당구역·제약을 **한 번에** 낸다.

        지금까지는 장치 하나를 파악하려면 search_devices(무엇인지) →
        get_device_measurements(무엇을 재는지) → get_device_location(어디인지)
        을 잇달아 불러야 했다 — MCP 는 호출마다 고정비가 커서 이 왕복이
        비싸다(docs 의 mcp_surface_cost 계열 실측). 이 도구 하나로 끝낸다.

        `device_id` 는 unique_id 또는 사람이 부르는 이름을 받는다. 이름이
        여러 개에 걸리면 하나를 고르지 않고 `needs_disambiguation` 과 후보
        목록을 그대로 돌려준다(space.py 의 `distance_between` 과 같은 관례).

        기존 도구(get_device_location·get_device_measurements)를 그대로
        불러 조합하고, 그 두 도구가 모르는 조각(OutputChannel, 소유
        복합장치의 통신 필드, GeoBinding)만 새로 조회한다. 읽기 전용이다.

        없는 조각은 키를 지우지 않고 null/빈 목록 + `*_note` 로 이유를
        남긴다 — "없다" 와 "모른다" 를 구분하기 위함이다.
        """
        try:
            token = device_id
            if isinstance(token, dict):
                results = token.get('results') or token.get('result', {}).get('results', [])
                if results and isinstance(results, list):
                    token = (results[0].get('id') or results[0].get('unique_id')
                             or results[0].get('device_id'))
            if not token or not isinstance(token, str) or not token.strip():
                return {"error": "device_id is required (unique_id or name)"}

            row, kind, err = cls._resolve_device_target(token.strip())
            if err:
                return err

            resolved_id = row.unique_id

            # 1) 무엇인가.
            if kind == 'input':
                module_type = row.device
                active = bool(row.is_activated)
                active_note = None
            elif kind == 'output':
                module_type = row.output_type
                active = None
                active_note = (
                    "Output 에는 활성/비활성 필드가 없습니다 (대신 "
                    "is_ai_enabled=%s 로 AI 제어 허용 여부만 있습니다)."
                    % bool(getattr(row, 'is_ai_enabled', True)))
            else:  # 'device' 또는 'function' — CustomController
                module_type = row.device
                active = bool(row.is_activated)
                active_note = None

            what = {
                "kind": kind,
                "module_type": module_type,
                "name": row.name,
                "active": active,
                "active_note": active_note,
            }

            # 2) 어디에 있는가 — get_device_location 은 Input/Output만 안다.
            if kind in ('input', 'output'):
                loc = cls.get_device_location(device_id=resolved_id)
                if isinstance(loc, dict) and not loc.get('error'):
                    location = loc
                    if loc.get('lat') is None and loc.get('lng') is None:
                        location_note = "지도에 배치되지 않았습니다(위경도 없음)."
                    else:
                        location_note = None
                else:
                    location = None
                    location_note = (isinstance(loc, dict) and loc.get('error')) \
                        or "위치를 확인할 수 없습니다."
            else:
                location = None
                location_note = ("get_device_location 은 Input/Output 만 조회합니다 "
                                 "— 복합장치·함수는 이 도구로 위치를 확인할 수 "
                                 "없습니다.")

            # 3) 무엇을 재는가 — get_device_measurements 를 그대로 쓴다.
            meas = cls.get_device_measurements(resolved_id)
            if isinstance(meas, dict) and not meas.get('error'):
                measurements = meas.get('measurements') or []
                measurements_note = None if measurements else "측정 채널이 없습니다."
            else:
                measurements = []
                measurements_note = (isinstance(meas, dict) and meas.get('error')) \
                    or "측정 채널을 확인할 수 없습니다."

            # 4) 무엇을 제어하는가 — OutputChannel 은 새로 조회한다.
            if kind == 'output':
                from aot.databases.models.output import OutputChannel
                ch_rows = OutputChannel.query.filter_by(output_id=resolved_id).all()
                output_channels = [
                    {"id": c.unique_id, "channel": c.channel, "name": c.name}
                    for c in ch_rows
                ]
                output_channels_note = None if output_channels else (
                    "등록된 출력 채널이 없습니다(단일 채널이거나 미설정).")
            else:
                output_channels = []
                output_channels_note = (
                    "OutputChannel 은 Output 에만 있습니다 — 이 항목은 %s 입니다."
                    % kind)

            # 5) 어떤 통신을 쓰는가 — 소유 Device(또는 자기 자신)의 연결 필드.
            owner = None
            if kind == 'device':
                owner = row
            else:
                parent_id = getattr(row, 'parent_device_id', None)
                if parent_id:
                    owner = CustomController.query.filter_by(
                        unique_id=parent_id).first()
            if owner is not None:
                communication = {
                    "controller_id": owner.unique_id,
                    "controller_name": owner.name,
                    "module": owner.device,
                    "fields": cls._summarize_connection_fields(owner.custom_options),
                }
                communication_note = None
            else:
                communication = None
                communication_note = "상위 복합장치(통신 모듈)에 속하지 않은 독립 항목입니다."

            # 6) 어느 구역을 맡는가 — GeoBinding 은 새로 조회한다.
            geo_bindings, geo_bindings_note = cls._geo_bindings_for(resolved_id)

            # 7) 무엇을 못 하는가.
            constraints = cls._device_constraints(kind, what)

            return {
                "device_id": resolved_id,
                "what": what,
                "location": location,
                "location_note": location_note,
                "measurements": measurements,
                "measurements_note": measurements_note,
                "output_channels": output_channels,
                "output_channels_note": output_channels_note,
                "communication": communication,
                "communication_note": communication_note,
                "geo_bindings": geo_bindings,
                "geo_bindings_note": geo_bindings_note,
                "constraints": constraints,
            }
        except Exception as e:
            logger.exception("Error in get_device_detail")
            return {"error": str(e)}

    @classmethod
    def list_unbound_slots(cls, map_id=None, facility_id=None, kinds=None, **extra):
        """Slots with no device bound — what a deletion or a swap left behind.
        Read-only."""
        from aot.aot_flask.geo import device_binding

        if isinstance(kinds, str):
            kinds = [k.strip() for k in kinds.split(',') if k.strip()]
        try:
            slots = device_binding.unbound_slots(
                facility_uuid=facility_id or None,
                map_uuid=map_id or None,
                kinds=tuple(kinds) if kinds else None)
        except Exception as e:
            return {"error": str(e)}
        return {"slots": slots, "count": len(slots)}

    @classmethod
    def rebind_device(cls, old_device_id=None, new_device_id=None, **extra):
        """Move every map slot held by one device over to another device.
        Requires human approval — this changes WHICH physical machine a zone
        or marker commands."""
        from aot.aot_flask.geo import device_binding

        if not old_device_id or not new_device_id:
            return {"error": "old_device_id and new_device_id are required"}
        try:
            result = device_binding.rebind_device(
                old_device_id, new_device_id, commit=True)
        except device_binding.BindingConflict as e:
            db.session.rollback()
            return {"error": str(e), "conflict": True}
        except (device_binding.BindingError,
                device_binding.BindingNotFound) as e:
            db.session.rollback()
            return {"error": str(e)}
        except Exception as e:
            db.session.rollback()
            return {"error": str(e)}

        result["status"] = "rebound" if result["moved"] else "nothing_moved"
        return result

    @classmethod
    def get_control_state(cls, facility_name=None, facility_id=None,
                          include_inactive=False, **extra):
        """[읽기전용] 환경제어 코디네이터의 현재 목표값과 최근 판단 결과.

        무엇이 목표이고(setpoint), 무엇이 제약을 걸었고(limiting factor),
        안전게이트가 열렸는지, 어떤 액추에이터에 왜 명령이 갔는지를 반환한다.
        예보/센서만으로는 알 수 없는 "지금 시스템이 무슨 의도로 움직이는가"에
        해당하므로, 제어 조언 전에 반드시 읽어야 하는 값이다.

        AISummaryService._gather_env_control_context() 와 같은 소스를 읽지만
        의도적으로 다르게 만든 점이 두 가지 있다:
          - function_id 를 포함한다. 코디네이터는 이름이 겹칠 수 있어
            (실환경에 'Env Coordinator' 동명 2개 존재) 이름으로는 키가 안 된다.
          - target_temperature/humidity, tolerance, priority, 스케줄 창을
            추가로 노출한다. 조언에 필요한데 그쪽에는 빠져 있다.
        """
        import json as _json
        try:
            from aot.databases.models import CustomController, FunctionRuntimeState, GeoFacility

            q = CustomController.query.filter_by(device='env_coordinator')
            if not include_inactive:
                q = q.filter_by(is_activated=True)
            controllers = q.all()
            if not controllers:
                return {"status": "success", "count": 0, "coordinators": [],
                        "message": "No environment-control coordinator (env_coordinator) is registered."}

            # 시설 이름 해석용 (geo_facility_id → GeoFacility.unique_id)
            fac_names = {f.unique_id: f.name for f in GeoFacility.query.all()}

            wanted_name = (facility_name or '').strip().lower() or None
            out = []
            for c in controllers:
                try:
                    o = _json.loads(c.custom_options) if c.custom_options else {}
                except (ValueError, TypeError):
                    o = {}

                fid = o.get('geo_facility_id')
                fname = fac_names.get(fid)
                if facility_id and fid != facility_id:
                    continue
                if wanted_name and wanted_name not in (fname or '').lower():
                    continue

                # 이 코디네이터가 **무엇을 기르고 있는가**. 설정값을 판단하려면
                # 목표 온습도만으로는 부족하다 — 같은 25도가 상추에는 높고
                # 토마토에는 적정이다. 작물도 목표도 구획의 프로그램에서 온다
                # (예전에는 함수에서 고른 `crop_preset` 이 실제로 심긴 것과
                # 다를 수 있었다).
                _bay = (o.get('bay_scope') or '').strip() or None
                _plants = []
                if fid:
                    try:
                        from aot.aot_flask.geo import plot_context as _pc
                        _plants = [_pc.plot_brief_for_control(r)
                                   for r in _pc.plots_in_facility(fid, bay_id=_bay)]
                    except Exception as exc:
                        logger.warning(
                            "list_env_coordinators: 식생 조회 실패(%s): %s", fid, exc)

                entry = {
                    "function_id": c.unique_id,
                    "function_name": c.name,
                    "is_activated": bool(c.is_activated),
                    "facility_id": fid,
                    "facility_name": fname,
                    "bay_scope": o.get('bay_scope') or None,
                    "plots": _plants,
                    "effect_engine": o.get('effect_engine', 'legacy'),
                    "targets": {
                        "source": "plot program",
                        **_control_targets_for(c),
                    },
                    "tolerance": {
                        "vpd": o.get('tolerance_vpd'),
                        "temperature_c": o.get('tolerance_temperature'),
                        "humidity_pct": o.get('tolerance_humidity'),
                        "co2_ppm": o.get('tolerance_co2'),
                    },
                    "priority": {
                        "vpd": o.get('priority_vpd'),
                        "temperature": o.get('priority_temperature'),
                        "humidity": o.get('priority_humidity'),
                        "co2": o.get('priority_co2'),
                    },
                    "safety_range": {
                        "temp_c": [o.get('temp_min'), o.get('temp_max')],
                        "humid_pct": [o.get('humid_min'), o.get('humid_max')],
                        "guide_temp_c": [o.get('guide_T_min'), o.get('guide_T_max')],
                        "guide_humid_pct": [o.get('guide_RH_min'), o.get('guide_RH_max')],
                    },
                    "window": {
                        # 시작일·종료일 모두 구획에서 온다 — 함수 옵션에는
                        # 둘 다 없다(2026-09-01). season_end_confirmed=False 면
                        # 예상치일 뿐 실제 종료가 아니다.
                        "season": [_plot_started_on(c), _plot_ended_on(c)[0]],
                        "season_end_confirmed": _plot_ended_on(c)[1],
                        "daily_enabled": o.get('time_enable'),
                        "daily": [o.get('time_start'), o.get('time_end')],
                    },
                }

                state = FunctionRuntimeState.query.filter_by(function_id=c.unique_id).first()
                if state and state.summary_json:
                    try:
                        entry["latest_cycle_summary"] = _json.loads(state.summary_json)
                    except (ValueError, TypeError):
                        entry["latest_cycle_summary_error"] = "Failed to parse summary_json"
                else:
                    entry["latest_cycle_summary"] = None
                    entry["latest_cycle_note"] = (
                        "No decision-cycle record yet - the coordinator has never run, "
                        "or summary recording is disabled.")
                out.append(entry)

            return {"status": "success", "count": len(out), "coordinators": out}
        except Exception as e:
            logger.exception("Error in get_control_state")
            return {"status": "error", "message": str(e)}

    @classmethod
    def get_output_state(cls, device_id, channel=None, **extra):
        """[읽기전용] 출력장치(밸브/펌프/릴레이 등)의 현재 ON/OFF 상태.

        set_output_state(쓰기)의 짝이 되는 읽기 도구 — 이게 없으면 AI가 장치를
        끄고 켤 수는 있어도 "지금 켜져 있는지"는 확인할 방법이 없었다.
        get_control_state는 env_coordinator에 등록된 액추에이터만 커버해서
        일반 밸브/펌프에는 못 쓴다 (그건 그 나름대로 목적이 다르다).

        세 가지를 합친다:
          - 실시간 on/off 상태: DaemonControl.output_states_all() (데몬 다운 시
            안전하게 빈 dict를 반환하도록 이미 처리되어 있음)
          - 켜진 지속시간(초): DaemonControl.output_sec_currently_on()
          - 정확히 언제 켜졌는지: InfluxDB의 output_started_at (base_output.py가
            켜질 때마다 기록 — LoRaWAN처럼 컨펌이 필요한 장치는 실제 컨펌된
            시점 기준이라 커맨드 전송 시각보다 정확하다). AoT_timer 위젯이 쓰는
            것과 같은 조회 로직(_read_latest_started_at)을 그대로 재사용한다 —
            KST/UTC 오인식 같은 이미 검증된 예외 처리를 중복 구현하지 않기 위해.

        과거 on/off 반복 이력(언제 껐다 켰다 했는지)은 다루지 않는다 — 그건
        InfluxDB를 직접 시계열로 조회해야 하는 별개 질문이다.
        """
        try:
            if isinstance(device_id, dict):
                results = device_id.get('results') or device_id.get('result', {}).get('results', [])
                if results and isinstance(results, list):
                    device_id = results[0].get('id') or results[0].get('unique_id') or results[0].get('device_id')
            if not device_id or not isinstance(device_id, str):
                return {"error": "device_id is required (string UUID)"}

            output = Output.query.filter_by(unique_id=device_id).first()
            if not output:
                return {"error": f"No Output found with unique_id {device_id}"}

            from aot.aot_client import DaemonControl
            from aot.widgets.AoT_timer import _read_latest_started_at

            daemon = DaemonControl()
            all_states = daemon.output_states_all() or {}
            channel_states = all_states.get(device_id, {})

            if not channel_states:
                return {
                    "status": "success",
                    "device_id": device_id,
                    "name": output.name,
                    "channels": {},
                    "message": "No live state available (daemon may be down, or this "
                               "output hasn't been read since it started)."
                }

            wanted_channels = [channel] if channel is not None else sorted(channel_states.keys())
            channels_out = {}
            for ch in wanted_channels:
                if ch not in channel_states:
                    continue
                entry = {"state": channel_states[ch]}
                if entry["state"] is None:
                    # null의 원인은 최소 두 가지고, 이 응답만으로는 구분이 안 된다:
                    # 한 번도 조작 안 함, 드라이버가 아직 설정을 못 마침(예:
                    # LoRaWAN 다운링크가 API 토큰 없이 등록됨), 또는 그 드라이버가
                    # 원래 상태를 되읽지 않음. 실측(2026-09-16, mcp_tool_audit_
                    # tracker.md #18): 임실 붕어섬 밸브 13개가 전부 이 상태였는데,
                    # 실제 원인은 `chirpstack_downlink` 드라이버의 `cs_api_token`
                    # 설정값이 빈 문자열이라 `is_setup()`이 False로 떨어져
                    # `is_on()`이 절대 값을 못 내는 것이었다 — "이 드라이버는
                    # 원래 상태를 안 알려준다"는 처음 가정은 틀렸다(실제로는
                    # 확인가능한 필드다, 설정만 마치면 됨). 이 도구 층에서
                    # 원인을 단정하지 않는다 — 드라이버 종류·설정을 몰라도 되는
                    # 응답 구조를 유지하려면, 원인 판정은 사람이 장치 설정 화면을
                    # 보고 하게 두는 편이 낫다.
                    entry["note"] = ("state is null for this channel — this can mean the "
                                      "output has never been commanded, its driver has not "
                                      "finished setup (e.g. a LoRaWAN downlink missing its "
                                      "API token/EUI), or the driver does not report state "
                                      "back at all. This response cannot tell which; check "
                                      "the device's own configuration to find out.")
                try:
                    entry["seconds_on"] = daemon.output_sec_currently_on(device_id, ch)
                except Exception:
                    entry["seconds_on"] = None
                try:
                    started = _read_latest_started_at(device_id, ch, lookback_sec=7 * 86400)
                    if started:
                        entry["started_at"] = serialize_ts(
                            datetime.utcfromtimestamp(started["selected_epoch"]))
                except Exception:
                    pass
                channels_out[str(ch)] = entry

            return {
                "status": "success",
                "device_id": device_id,
                "name": output.name,
                "channels": channels_out,
            }
        except Exception as e:
            logger.exception("Error in get_output_state")
            return {"error": str(e)}

