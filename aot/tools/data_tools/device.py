import logging
import re

logger = logging.getLogger(__name__)


def _tag_sim(entry, name):
    """목록 항목(type·device 를 가진 dict)에 시뮬레이션 표시를 붙인다 — 표시 전용."""
    entry.update(_sim_fields(entry.get("type"), entry.get("device"), name))
    return entry


from aot.tools.aot_data_tool_service import _control_targets_for
from aot.tools.aot_data_tool_service import _plot_ended_on
from aot.tools.aot_data_tool_service import _vpd_basis_of
from aot.tools.aot_data_tool_service import _vpd_readout_of
from aot.tools.aot_data_tool_service import _plot_started_on
from aot.aot_flask.extensions import db
from aot.databases.models import Camera
from aot.databases.models import CustomController
from aot.databases.models import DeviceMeasurements
from aot.databases.models import GeoShape
from aot.databases.models import Input
from aot.databases.models import Output
from aot.tools.sim_marker import sim_fields as _sim_fields
from aot.utils.command_origin import TYPE_AI
from aot.utils.execution_context import clear_execution_context
from aot.utils.execution_context import set_execution_context
from aot.outputs.command_forms import (
    parse_run_seconds, plan_output_command, timed_run_refusal)
from datetime import datetime
from sqlalchemy import or_


class DeviceToolsMixin:
    #: 키워드 없는 장치 전체 목록의 한 쪽 크기 — 129개를 한 번에 쏟지 않는다(2026-10-28 점검).
    _DEVICE_LIST_PAGE = 40

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
    def search_devices(cls, query=None, measurement_type=None, limit=None, offset=None):
        """이름·측정으로 장치 찾기. limit·offset 은 결과 목록을 쪽으로 나눈다(조회 도구 공통)."""
        # 상한: 한 번에 100건 — 검색 결과는 기본으로도 한 쪽(40)만 준다(2026-11-07: 19,774토큰 → 캡에 잘림).
        limit = cls._bounded_limit(limit, cls._DEVICE_LIST_PAGE, 100)
        if not query and not measurement_type:
            # 검색어가 없으면 전체 목록이다 — 도메인의 find.devices 가 get_device_list 를 겸한다(재설계 PR 3).
            return cls.get_device_list_tool(limit=limit, offset=offset)
        out = cls._search_devices_all(query=query, measurement_type=measurement_type)
        if isinstance(out, dict) and isinstance(out.get('results'), list):
            page, info = cls._page_rows(out['results'], limit, offset)
            out = dict(out, results=page, count=len(page))
            if info:
                out['page'] = info
        return out

    @classmethod
    def _search_devices_all(cls, query=None, measurement_type=None):
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
                                        "'%s'. Stored names are rarely the "
                                        "everyday word (soil moisture = "
                                        "'volumetric_water_content') — check a "
                                        "device's real names with "
                                        "get_device_measurements before saying "
                                        "there are none." % measurement_type)}

            # 측정 종류만 물은 경우. 이름 검색 경로(토큰 확장·별칭·구역 확장)를
            # 태울 근거가 없으므로 후보를 그대로 낸다.
            if not query:
                results = []
                for item in Input.query.filter(
                        Input.unique_id.in_(list(candidate_ids))).all():
                    results.append(_tag_sim({"id": item.unique_id, "name": item.name, "type": "input", "device": item.device},
                         item.name))
                for item in Output.query.filter(
                        Output.unique_id.in_(list(candidate_ids))).all():
                    results.append(_tag_sim({"id": item.unique_id, "name": item.name, "type": "output", "device": item.output_type},
                         item.name))
                # 집계 함수(VPD·평균 등)도 자기 측정 채널을 갖는다. 빼면
                # measurement_type='vapor_pressure_deficit' 이 0건이 되는데,
                # get_sensor_detail 은 그 값을 읽을 수 있다(찾을 수만 없다).
                for item in CustomController.query.filter(
                        CustomController.unique_id.in_(list(candidate_ids))).all():
                    results.append({"id": item.unique_id, "name": item.name,
                                    "type": "function", "device": item.device})
                results = cls._without_ai_excluded(results)
                from aot.space.device_membership import annotate_places
                annotate_places(results)
                results = cls._annotate_device_membership(results)
                out = {"results": results, "count": len(results)}
                cls._mark_same_names(out)
                return out

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
                # 밑줄 표기('온습도_7')도 같은 이름이다 — 변형마다 한 벌 더.
                for v in list(variants):
                    u = re.sub(r'\s+', '_', v.strip()) if ' ' in v else v
                    if u != v and u not in variants:
                        variants.append(u)
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
                        results.append(_tag_sim({"id": item.unique_id, "name": item.name, "type": "input", "device": item.device},
                         item.name))

                for item in Output.query.filter(
                    or_(Output.name.like(q), Output.output_type.like(q))
                ).all():
                    if item.unique_id not in seen_ids:
                        seen_ids.add(item.unique_id)
                        results.append(_tag_sim({"id": item.unique_id, "name": item.name, "type": "output", "device": item.output_type},
                         item.name))

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
                            # 장소(site·zone·facility)는 그 종류로, 그 밖의 도형
                            # (장치 영역 폴리곤·마커)은 장소가 아니라고 표기한다.
                            # 예전에는 모두 type='zone' 에 진짜 종류를 'device'
                            # 칸에 실어, 대지가 "zone" 으로 읽혔다(2026-10-08).
                            from aot.space.device_membership import PLACE_TYPES as _PT
                            results.append({
                                "id": item.unique_id,
                                "geo_id": item.geo_id,
                                "name": name,
                                "type": item.type if item.type in _PT else "map_shape",
                                **({} if item.type in _PT else {"shape_type": item.type}),
                            })

            # 장소 범위 — 질의에 장소 이름이 들어 있으면 그 장소(하위 포함) 안의
            # 장치만 남긴다. 소속은 정본(device_membership)으로 판정한다.
            # 예전에는 `device_zone_map`(장치 영역 폴리곤만 · 지도 무관 · 바인딩
            # 안 봄)과 "N포장 → N-*" 이름 규칙을 섞어 써서, 대지를 물으면 밸브만
            # 나오고 센서는 빠졌으며 소속도 3-1/3-2 로만 보였다(2026-10-08).
            # `zone_scoped_query` 는 호출자에게 알린다(_zone_scope_note): 장소로
            # 좁힌 장치 검색은 "그곳에 있는 모든 것" 이 아니다 — 구획(작물)은
            # 품종명으로 등록돼 여기 나오지 않는다.
            from aot.space import device_membership as _dm
            _places = _dm.PlaceIndex()
            _scoped = _dm.places_named(query, index=_places)
            # 이름이 같은 장소가 여럿이면 섞지 않는다 — 두 곳의 장치를 한 목록에
            # 내면 어느 쪽 것인지 알 수 없다(2026-10-08: '1포장' 이 김제 대지와
            # 그린하트바이오 구역을 함께 잡았다). resolve_target 과 같은 후보를
            # 돌려준다 — 후보의 use_name('김제 1포장')으로 다시 물으면 좁혀진다.
            _dups = _dm.same_name_groups(_scoped)
            if _dups:
                _label = _dm.place_label(_dups[0][0])
                _cands = cls._public_places(cls._describe_places(
                    [{'rep': (sh, _label), 'device_id': None} for sh in _dups[0]]))
                return {
                    "status": "needs_disambiguation",
                    "error": "ambiguous_name",
                    "message": ("'%s' names %d different places, so their devices "
                                "were not mixed into one list — see 'candidates'."
                                % (_label, len(_cands))),
                    "candidates": _cands,
                    "results": [], "count": 0,
                    "_reading": [
                        "Ask the user which place they mean, describing each "
                        "candidate by its 'where' — or, if the question only reads "
                        "data, search again once per candidate. Put that candidate's "
                        "'use_name' in the query (e.g. its map name before the place "
                        "name) and the search narrows to it."],
                }
            zone_scoped_query = bool(_scoped)
            if _scoped:
                allowed = set()
                for _pl in _scoped:
                    allowed |= (_dm.place_members(_pl.unique_id) or set())
                for did in sorted(allowed):
                    if did in seen_ids:
                        continue
                    o = Output.query.filter_by(unique_id=did).first()
                    if o:
                        seen_ids.add(did)
                        results.append(_tag_sim({"id": o.unique_id, "name": o.name, "type": "output", "device": o.output_type},
                         o.name))
                        continue
                    i = Input.query.filter_by(unique_id=did).first()
                    if i:
                        seen_ids.add(did)
                        results.append(_tag_sim({"id": i.unique_id, "name": i.name, "type": "input", "device": i.device},
                         i.name))
                # 장소 밖의 장치 결과는 뺀다 — "1포장 1-4구역 밸브" 가 다른
                # 곳의 밸브1..51 까지 쓸어 오지 않게.
                results = [r for r in results
                           if r.get('type') not in ('input', 'output')
                           or r.get('id') in allowed]
                # 이름으로 걸린 장소·도형도 범위의 지도 것만 — '김제 1포장' 으로
                # 물었는데 그린하트바이오의 구역 '1포장' 이 이름 일치로 섞였다.
                _maps = {_pl.geo_id for _pl in _scoped}
                results = [r for r in results
                           if not r.get('geo_id') or r.get('geo_id') in _maps]
            _dm.annotate_places(results, index=_places,
                                kinds=('input', 'output', 'function', 'device'))
            for r in results:
                if r.get('type') in _dm.PLACE_TYPES:
                    _shape = _places.by_uid.get(r.get('id'))
                    _p = _places.path(_shape) if _shape is not None else ''
                    if _p:
                        r['place'] = _p

            if candidate_ids is not None:
                # 이름 검색이 끝난 뒤에 거른다 — 구역 확장까지 마친 집합에
                # 걸어야 "1포장 안의 토양수분 센서" 가 성립한다. 측정을 갖지
                # 않는 종류(구역·카메라)는 이 질문의 답이 아니므로 함께 빠진다.
                results = [r for r in results if r.get('id') in candidate_ids]

            results = cls._without_ai_excluded(results)
            results = cls._annotate_device_membership(results)
            out = {"results": results, "count": len(results)}
            if not results:
                out["message"] = (
                    "No device or place name contains '%s'. Names are often Korean, so try the word the grower "
                    "uses, search by measurement_type, or browse with get_spatial_tree." % (query or ""))
            notes = []
            note = cls._complex_device_note(results)
            if note:
                notes.append(note)
            note = cls._zone_scope_note(zone_scoped_query)
            if note:
                notes.append(note)
            if notes:
                out["_reading"] = notes
            cls._mark_same_names(out)
            return out
        except Exception as e:
            return {"error": str(e)}

    #: 같은 이름 표시에서 셀 종류 — 구역 도형은 장치가 아니다.
    _SAME_NAME_KINDS = ('input', 'output', 'device', 'camera', 'function')

    @classmethod
    def _mark_same_names(cls, out):
        """결과 안에 이름이 같은 장치가 여럿이면 표시한다(제자리 수정).

        벤치(26-09-23 lat_14): 'v111' 이 둘인데 목록에서 하나만 읽고 답했다.
        목록에는 둘 다 있었지만 같은 이름이라는 사실이 어디에도 없었다.
        행마다 `same_name_count` 와 사람이 가를 단서 `where` 를 붙이고, 위에
        `same_name_groups`(이름·개수)와 `_reading` 한 줄을 싣는다."""
        results = out.get("results") or []
        groups = {}
        for r in results:
            if r.get("type") not in cls._SAME_NAME_KINDS:
                continue
            key = str(r.get("name") or "").strip().lower()
            if key:
                groups.setdefault(key, []).append(r)
        dup = {k: rows for k, rows in groups.items() if len(rows) > 1}
        if not dup:
            return out
        # 도구 어휘: 'function'=CustomController(지도 어휘와 같다), 'camera' 는 이 자리만.
        from aot.space.device_kind import models_for
        models = {**models_for(('input', 'output', 'device', 'function'),
                               vocabulary='geo'),
                  'camera': Camera}
        for rows in dup.values():
            pairs = []
            for r in rows:
                model = models.get(r.get("type"))
                row = (model.query.filter_by(unique_id=r.get("id")).first()
                       if model is not None else None)
                pairs.append((row, r))
            known = [(row, r.get("type")) for row, r in pairs if row is not None]
            try:
                wheres = iter(cls._device_candidates_where(known))
            except Exception:                               # noqa: BLE001
                wheres = iter(())
            for row, r in pairs:
                r["same_name_count"] = len(rows)
                if row is not None:
                    w = next(wheres, None)
                    if w:
                        r["where"] = w
        out["same_name_groups"] = [
            {"name": rows[0].get("name"), "count": len(rows)}
            for rows in dup.values()]
        reading = out.get("_reading") or []
        if isinstance(reading, str):
            reading = [reading]
        reading.append(
            "'same_name_groups': more than one device has the same name here. "
            "They are different devices — do not answer from just one. Cover "
            "each (tell them apart by 'where', not by id) or ask which one the "
            "user means.")
        out["_reading"] = reading
        return out

    @classmethod
    def _zone_scope_note(cls, zone_scoped_query):
        """질의가 zone/site를 가리켰을 때만, 이 결과가 무엇인지 알린다.

        장소로 좁힌 센서·출력은 **이름이 아니라 소속**(정본 `device_membership`
        — 지도 위 위치 또는 바인딩, 하위 장소 포함)으로 나온다. 예전 문구는
        "이름이 일치한 것뿐" 이라고 말했는데 2026-10-08 소속 통일 뒤로는 사실이
        아니다 — 모델이 응답과 문구를 대조해 "도구가 설명과 다르다" 고 읽는다.
        나머지(장소 자체·함수·카메라)는 여전히 이름으로 걸린 것이다.

        작물 구획(plot)은 별도 레지스트리라 여기 결과에 절대 나타나지 않는다.
        이것을 "이 장소엔 작물이 없다" 로 읽으면 실제 사례로 확인된 오판이
        재발한다(.local/plans/mcp_tool_audit_tracker.md 8번 항목).
        """
        if not zone_scoped_query:
            return None
        return ("This query named a place (site/zone). The sensors and outputs "
                "listed are the ones that BELONG to it — placed inside it on the "
                "map or bound to it, sub-zones included — and each carries its "
                "'place' path (e.g. 'Site > Zone'). Other entries (the place "
                "itself, functions, cameras) matched by name. Plots/crops are a "
                "separate registry and never appear here, even when something "
                "is growing there — call list_plots with zone_id set to this "
                "place to see what is planted.")

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
    def get_device_list_tool(cls, limit=None, offset=None, **kwargs):
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
                    # active — 켜짐 여부(출력은 켜고 끄는 상태가 아니라 칸이 없다).
                    results.append(_tag_sim({"id": item.unique_id, "name": item.name, "type": "input", "device": item.device,
                                             "active": bool(item.is_activated)},
                         item.name))
            for item in Output.query.all():
                if item.unique_id not in seen_ids:
                    seen_ids.add(item.unique_id)
                    results.append(_tag_sim({"id": item.unique_id, "name": item.name, "type": "output", "device": item.output_type},
                         item.name))
            for item in Camera.query.all():
                if item.unique_id not in seen_ids:
                    seen_ids.add(item.unique_id)
                    results.append({"id": item.unique_id, "name": item.name, "type": "camera", "device": item.camera_type,
                                    "active": bool(item.is_activated)})

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
                                "active": bool(item.is_activated),
                                "member_ids": member_ids,
                            })
            except Exception:
                pass

            results = cls._without_ai_excluded(results)
            results = cls._annotate_device_membership(results)
            # 꺼진 것의 수 — 쪽으로 자르기 전 전체에서 센다(첫 쪽에 안 보여도 알린다).
            off = sum(1 for r in results if r.get("active") is False)
            by_type = {}
            for r in results:
                by_type[r.get("type")] = by_type.get(r.get("type"), 0) + 1
            # 필터 없는 전체 목록은 한 쪽(기본 40)만 — 129개를 다 싣지 않는다. 이어 받기는 offset.
            results, page = cls._page_rows(results, limit, offset, default=cls._DEVICE_LIST_PAGE)
            out = {"results": results, "count": len(results)}
            if off:
                out["inactive"] = off
            if page:
                out["page"] = page
                out["count_by_type"] = by_type
                out["more"] = ("Showing %d of %d. Narrow with find.devices(query, measurement) or "
                               "page with offset." % (page["shown"], page["total"]))
            note = cls._complex_device_note(results)
            if note:
                out["_reading"] = [note]
            return out
        except Exception as e:
            return {"error": str(e)}

    @classmethod
    def validate_ai_control_target(cls, device_id=None, **extra):
        """물리 제어 도구(operate_device·schedule_device_control·set_output_state)
        의 출력이 'AI 판단에 포함' 을 끈 장치면 이유를 담은 오류, 아니면 None.

        `tool_execution._pre_gate_validation` 이 승인 게이트 **앞에서** 부른다 —
        실행층도 같은 헬퍼(`device_resolver`)로 거절하지만, 여기서 먼저 막지
        않으면 어차피 거절될 요청이 승인 큐에서 사람을 기다린다."""
        from aot.services.resolvers.device_resolver import (
            AI_EXCLUDED, ai_control_refusal)
        message = ai_control_refusal(device_id)
        if message:
            return {"error": message, "reason_code": AI_EXCLUDED}
        return cls._run_time_refusal(device_id, extra) or cls._value_refusal(device_id, extra)

    @classmethod
    def _value_refusal(cls, device_id, extra):
        """set_value(또는 값을 실은 켜기)를 이 출력이 못 받으면 오류, 아니면 None.

        승인 앞에서 막는다 — 켜고 끄기만 되는 출력에 값을 주거나 PWM 에 0-100 % 밖의 값을 주면
        실행 때 어차피 거절된다(PWM 모듈은 범위 밖 값을 받으면 아무것도 안 하고 성공을 돌려줬다)."""
        state = str(extra.get('state') or '').lower()
        value = extra.get('value')
        if state != 'set_value' and value is None:
            return None
        if state not in ('set_value', 'on'):
            return None
        scheduled = any(extra.get(k) is not None
                        for k in ('scheduled_time', 'delay_seconds', 'solar_event'))
        try:
            from aot.services.resolvers.device_resolver import resolve_output
            row = resolve_output(device_id, allow_partial=scheduled, ai=True).row
        except Exception:                                   # noqa: BLE001
            row = None
        if row is None:
            return None                                     # 대상 오류는 실행층이 알린다
        from aot.outputs.command_forms import plan_output_command
        plan = plan_output_command(state, row.output_type, value, 0)
        if 'error' in plan:
            return {"error": plan['error'], "reason_code": "bad_value"}
        return None

    @classmethod
    def _run_time_refusal(cls, device_id, extra):
        """요청한 가동 시간이 숫자로 맞지 않거나 이 출력·상태가 못 받는 것이면 오류, 아니면 None.

        승인 앞에서 막는다 — 30초를 부탁했는데 0분으로 깎여 타이머 없이 켜지던 일(2026-10-30)을
        승인 큐에 올리지 않는다. 예약(시각 인자가 있는 호출)은 상태가 꺼짐이어도 숫자만 본다."""
        sec, minutes = extra.get('duration_seconds'), extra.get('duration_minutes')
        if sec is None and minutes is None:
            return None
        run_sec, err = parse_run_seconds(sec, minutes)
        if err:
            return {"error": err, "reason_code": "bad_run_time"}
        scheduled = any(extra.get(k) is not None
                        for k in ('scheduled_time', 'delay_seconds', 'solar_event'))
        state = str(extra.get('state') or 'on').lower()
        if scheduled and state != 'on':
            return None
        try:
            from aot.services.resolvers.device_resolver import resolve_output
            row = resolve_output(device_id, allow_partial=scheduled, ai=True).row
        except Exception:                                   # noqa: BLE001
            row = None
        why = timed_run_refusal(state, getattr(row, 'output_type', None))
        if why:
            return {"error": why, "reason_code": "no_timed_run"}
        return None

    @classmethod
    def operate_device_tool(cls, device_id, state, duration_seconds=None,
                            duration_minutes=None, **kwargs):
        """
        [분류 A - 물리 제어 전용 도구]
        장치를 직접 제어합니다. (on, off, open, close, set_value 등)

        실패 응답에는 `dispatched` 를 싣는다 — False 는 데몬에 보내기 전에 멈춘
        확정 실패, True 는 보냈거나 보내다 끊긴 것(시간 초과·통신 오류·데몬
        오류)이다. 뒤쪽은 장치가 이미 움직였을 수 있으므로 실행층이 "안 됨" 이
        아니라 "모름" 으로 알린다(`mcp_safety_gate.annotate_write_outcome`).
        """
        sent = False
        try:
            if not device_id or not state:
                return {"error": "Missing device_id or state", "dispatched": False}

            # 1. 상태값 검증
            ALLOWED_STATES = ['on', 'off', 'open', 'close', 'set_value']
            state = state.lower()
            if state not in ALLOWED_STATES:
                return {"error": f"Invalid state value: {state}. Allowed values: {ALLOWED_STATES}",
                        "dispatched": False}

            # 2. 장치 존재 여부 확인 (UUID 또는 이름)
            # 이름이 겹치면 고르지 않는다 — `.first()` 로 아무거나 집으면
            # 엉뚱한 밸브를 연다(2026-08-28: v11 이 두 개였다).
            # ai=True — 'AI 판단에 포함' 을 끈 출력은 대상이 아니다(이유를 돌려준다).
            from aot.services.resolvers.device_resolver import resolve_output
            match = resolve_output(device_id, ai=True)
            if match.error:
                out = {"error": match.error, "dispatched": False}
                if match.reason:
                    out["reason_code"] = match.reason
                return out
            target = match.row
            if not target:
                return {"error": f"Device (output) to control not found: {device_id}",
                        "dispatched": False}

            # 3. 시간/값 파라미터 정규화 — duration_seconds | duration_minutes(소수 가능) | duration(옛 이름, 분)
            # | value. 분을 정수로 깎지 않는다: 0.5분은 30초다(2026-10-30: 0 으로 깎여 타이머 없이 켜졌다).
            if duration_seconds is None and duration_minutes is None:
                duration_minutes = kwargs.get('duration')
            run_sec, run_err = parse_run_seconds(duration_seconds, duration_minutes)
            if run_err:
                return {"error": run_err, "dispatched": False}
            val = kwargs.get('value')
            # 우선순위: duration_seconds/duration_minutes > value > 0
            # value 가 '40%' 같은 글이면 여기서 죽지 않고 plan_output_command 가 읽거나 거절한다.
            try:
                duration = float(run_sec) if run_sec is not None else float(val or 0)
            except (TypeError, ValueError):
                duration = 0.0

            # 4. @ANCHOR: OPERATE_DEVICE_CHANNEL_INJECTION (TASK_17)
            # Resolve physical output_channel from OutputChannel table before daemon call.
            # Eliminates 'output channel doesn't exist: None' — channel=0 is a valid integer.
            resolved_uid = target.unique_id
            output_channel = None
            try:
                from aot.databases.models.output import OutputChannel as _OC
                oc_row = (_OC.query.filter_by(output_id=resolved_uid)
                          .order_by(_OC.channel).first())
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

            # 5. 출력 모듈이 받는 명령 형식으로 바꾼다. 데몬의 output_on_off 는
            # 모듈이 모르는 형식(PWM 출력에 'sec', 값 출력에 'on')을 받으면
            # 아무것도 하지 않고 성공을 돌려준다 — 여기서 맞춰 보내거나 거절한다.
            plan = plan_output_command(state, target.output_type, val, duration)
            if 'error' in plan:
                return {"error": plan['error'], "dispatched": False}

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
                # 여기서부터는 명령이 데몬으로 나간다 — 이후 실패는 결과를 모른다.
                sent = True
                out_err, out_msg = daemon.output_on_off(
                    resolved_uid, plan['state'], output_type=plan['output_type'],
                    amount=plan['amount'], output_channel=output_channel
                )
            finally:
                clear_execution_context()

            if out_err:
                logger.error(f"[operate_device_tool] Daemon error: {out_msg}")
                return {"error": f"Device control failed: {out_msg}",
                        "dispatched": True}
            
            logger.info(f"[operate_device_tool] OK: device={resolved_uid}({target.name}), state={state}, duration={duration}s")
            out = {"status": "success", "execution_result": out_msg}
            if plan['output_type'] == 'sec':
                out["resolved_duration"] = duration
            else:
                # PWM 듀티·개도·값 — 가동 시간이 아니다. 예전엔 값이 duration 자리로 흘러
                # `resolved_duration: 37.0` 이 실려 "37초" 로 읽힐 수 있었다(2026-11-12).
                out["value"] = plan['amount']
            return out
        except Exception as e:
            logger.error(f"Error in operate_device_tool: {e}")
            return {"error": f"Error while controlling device: {str(e)}",
                    "dispatched": sent}

    #: "Rain (daily sum) +3d" 처럼 이름 끝에 시간 오프셋이 붙은 채널 — 같은 계열로 묶는다.
    _CHANNEL_OFFSET = re.compile(r'^(.*?)\s*\+(\d+)\s*([A-Za-z]+)$')

    @classmethod
    def _channel_table(cls, rows, with_measurement=False):
        """채널 목록 → 이름·단위 표. 같은 계열(이름 끝의 `+Nh`/`+Nd` 만 다른 것)은 한 줄로 묶는다.

        예: `Rain (daily sum) +0d` … `+15d` 16개 → `{"name": "Rain (daily sum) +0d~+15d", "unit": "mm", "n": 16}`.
        한 줄뿐인 채널은 이름 그대로(`n` 없음). 순서는 처음 나온 차례다. id 는 싣지 않는다 — 채널 id·select_value 는
        `measurement` 로 고른 채널에만 따라온다(`get_device_measurements`). `with_measurement` 면 이름에 저장
        측정 이름이 안 들어 있을 때만 그 이름을 덧붙인다(고를 때 쓰는 낱말)."""
        order, groups = [], {}
        for r in rows:
            name = str(r.get('name') or r.get('measurement') or '')
            unit = r.get('unit')
            m = cls._CHANNEL_OFFSET.match(name)
            key = (m.group(1), m.group(3), unit) if m else ('', len(order), unit)
            if key not in groups:
                groups[key] = {'base': m.group(1) if m else name, 'u': m.group(3) if m else '',
                               'offs': [], 'rows': [], 'name': name, 'unit': unit}
                order.append(key)
            if m:
                groups[key]['offs'].append(int(m.group(2)))
            groups[key]['rows'].append(r)
        table = []
        for key in order:
            g = groups[key]
            if len(g['rows']) >= 2 and g['offs']:
                label = "%s +%d%s~+%d%s" % (g['base'], min(g['offs']), g['u'], max(g['offs']), g['u'])
            else:
                label = g['name']
            row = {"name": label, "unit": g['unit']}
            if len(g['rows']) >= 2 and g['offs']:
                row["n"] = len(g['rows'])
            first = g['rows'][0]
            meas = first.get('measurement')
            if with_measurement and meas and str(meas).lower() not in label.lower():
                row["measurement"] = meas
            table.append(row)
        return table

    @classmethod
    def get_device_measurements(cls, device_id, measurement_type=None, brief=False):
        """
        Returns all measurement channels for a given Input or CustomController device_id.
        device_id may be the unique_id or the device's name (ambiguous names
        return candidates). Also accepts a search_devices result dict — extracts
        the first device_id automatically.
        Used by the AI to resolve measurement IDs needed for select_measurement options.

        `brief`·`measurement_type` 는 도구 스키마에 없는 처리기 인자다 — 도메인 표면(measure.channels)만 쓴다.
        - `brief` 만: 이름·단위 표(같은 계열은 묶음, id 없음) + `next`. 채널이 40개인 예보 장치가 5천 토큰이었다.
        - `brief` + `measurement_type`: 이름이나 측정 이름에 그 낱말이 든 채널만, 지금 모양 그대로(id·select_value 포함) —
          위젯·함수 설정에 쓰는 id 를 받는 길이다.
        둘 다 안 주면(인앱 AI·장치 상세) 예전과 같은 전체 응답이다."""
        try:
            row, _kind, err = cls._read_device(device_id)
            if err:
                return err
            device_id = row.unique_id

            rows = DeviceMeasurements.query.filter_by(device_id=device_id).all()
            if not rows:
                return {"error": f"No measurements found for device_id: {device_id}"}

            from aot.databases.models import Conversion
            from aot.utils.system_pi import return_measurement_info
            conversions = {c.unique_id: c for c in Conversion.query.filter(
                Conversion.unique_id.in_(
                    [r.conversion_id for r in rows if r.conversion_id])).all()}

            def _stored_unit(r):
                # 변환이 걸린 채널은 변환 뒤 단위로 저장된다 — 원 단위(r.unit)로 알리면
                # 값과 단위가 어긋난다.
                return return_measurement_info(
                    r, conversions.get(r.conversion_id))[1] or r.unit

            if brief and not measurement_type:
                return {
                    "status": "success",
                    "next": {
                        "call": ("measure(op='channels', target=<same target>, measurement=<a word from "
                                 "name or measurement>) gives only those channels with measurement_id "
                                 "and select_value"),
                        "why": "names and units only; the ids that widget and function settings need "
                               "come with a chosen measurement"},
                    "device_id": device_id,
                    "channel_count": len(rows),
                    "channels": cls._channel_table(
                        [{"name": getattr(r, 'name', ''), "measurement": r.measurement,
                          "unit": _stored_unit(r)} for r in rows], with_measurement=True),
                }

            measurements = [
                {
                    "measurement_id": r.unique_id,
                    "channel": r.channel,
                    "measurement": r.measurement,
                    "unit": _stored_unit(r),
                    "name": getattr(r, 'name', ''),
                    # Ready-to-use value for select_measurement fields: "device_id,measurement_id"
                    "select_value": f"{device_id},{r.unique_id}",
                }
                for r in rows
            ]

            if brief and measurement_type:
                word = str(measurement_type).strip().lower()
                matched = [m for m in measurements
                           if word in str(m["measurement"] or "").lower()
                           or word in str(m["name"] or "").lower()]
                if not matched:
                    return {
                        "status": "not_found",
                        "message": "No channel of this device has '%s' in its name or measurement." % measurement_type,
                        "device_id": device_id,
                        "channels": cls._channel_table(
                            [{"name": m["name"], "measurement": m["measurement"], "unit": m["unit"]}
                             for m in measurements], with_measurement=True)}
                measurements = matched

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

        # 'AI 판단에 포함' 을 끈 입력·출력은 AI 도구의 대상이 아니다
        # (docs/ai/overview.md#device-ai-toggle). 판정은 공용 헬퍼 하나다.
        from aot.services.resolvers.device_resolver import (
            AI_EXCLUDED, ai_excluded, ai_excluded_error)

        def _refused(r):
            return {"error": ai_excluded_error(r), "reason_code": AI_EXCLUDED}

        # 0) unique_id 정확일치.
        row = Input.query.filter_by(unique_id=token).first()
        if row is not None:
            return (None, None, _refused(row)) if ai_excluded(row) \
                else (row, 'input', None)
        row = Output.query.filter_by(unique_id=token).first()
        if row is not None:
            return (None, None, _refused(row)) if ai_excluded(row) \
                else (row, 'output', None)
        row = CustomController.query.filter_by(unique_id=token).first()
        if row is not None:
            return row, cls._kind_of_controller(row), None
        # 지도 도형 id — resolve_target 후보의 target_id 는 장치가 아니라 그 장치 표식 도형이다. 도형이 가리키는
        # 장치로 읽는다(2026-11-03: 센서 조회에 그 id 를 넣으면 Device not found).
        shape = GeoShape.query.filter_by(unique_id=token).first()
        if shape is not None:
            from aot.space.device_binding import device_for_shape
            dev = device_for_shape(shape)
            if dev and dev != token:
                return cls._resolve_device_target(dev)

        # 1) 이름 정확일치 — 세 테이블을 한꺼번에 모은다. AI 에서 뺀 장치는
        #    후보가 아니다 — 같은 이름의 다른 장치와 겹쳐 되묻게 하지도 않는다.
        candidates, hidden = [], []
        for r in Input.query.filter(Input.name == token).all():
            (hidden if ai_excluded(r) else candidates).append((r, 'input'))
        for r in Output.query.filter(Output.name == token).all():
            (hidden if ai_excluded(r) else candidates).append((r, 'output'))
        for r in CustomController.query.filter(CustomController.name == token).all():
            candidates.append((r, cls._kind_of_controller(r)))

        if not candidates:
            if hidden:
                return None, None, _refused(hidden[0][0])
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
                                    or getattr(r, 'output_type', None),
                     "where": w}
                    for (r, k), w in zip(listed, cls._device_candidates_where(listed))
                ],
                "candidates_shown": len(listed),
                "candidates_total": len(candidates),
            }

        row, kind = candidates[0]
        return row, kind, None

    @classmethod
    def _device_candidates_where(cls, rows_kinds):
        """이름이 같은 장치 후보마다 사람이 구분할 단서 — 구역·지도·소속 장치·탭.

        이것이 없던 때는 후보가 id 로만 갈려, 모델이 되물을 때 uuid 를 그대로
        보여 줬다(2026-09-23 재측정 lat_14). 조회가 실패해도 후보는 낸다.

        - 지도: 정본 경로(`device_binding.shapes_for_devices` — 바인딩 우선,
          없으면 레거시 `GeoShape.device_id`)로 찾는다. 도형이 여럿이면 지도
          이름을 정렬해 모두 적는다(첫 도형은 DB 순서라 호출마다 달랐다).
        - 장소: 정본 경로(`device_membership.PlaceIndex.device_paths` — 마커·
          바인딩·시설 설비)로 '3포장 > 3-1' 처럼 적는다. 장소가 잡혔는데 지도
          도형이 없으면 "지도에 없음" 이라고 쓰지 않는다(장소가 곧 지도 위다).
        - 문장은 모델이 읽는 영어라 번역하지 않는다. 탭 이름이 없으면 뺀다.
        - 단서가 똑같은 후보끼리는 종류·모듈을 덧붙여 가른다.
        """
        try:
            from aot.space.device_membership import PlaceIndex
            zmap = {d: ps[0] for d, ps in PlaceIndex().device_paths(
                [r.unique_id for r, _k in rows_kinds]).items()}
        except Exception:
            zmap = {}
        pmap = cls._device_parent_map()
        tabs = {}
        try:
            from aot.databases.models import Tab
            tab_ids = {getattr(r, 'tab_id', None) for r, _k in rows_kinds} - {None, ''}
            if tab_ids:
                tabs = {t.unique_id: (t.name or '').strip()
                        for t in Tab.query.filter(Tab.unique_id.in_(tab_ids)).all()}
        except Exception:
            tabs = {}
        placed = {}
        try:
            from aot.space import device_binding
            from aot.databases.models import GeoMap
            by_dev = device_binding.shapes_for_devices(
                [r.unique_id for r, _k in rows_kinds])
            geo_ids = {sh.geo_id for shs in by_dev.values() for sh in shs}
            maps = {m.unique_id: (m.name or '').strip()
                    for m in GeoMap.query.filter(
                        GeoMap.unique_id.in_(geo_ids)).all()} if geo_ids else {}
            for dev, shs in by_dev.items():
                if shs:
                    placed[dev] = sorted({maps.get(sh.geo_id) or '' for sh in shs} - {''})
        except Exception:
            placed = {}
        out = []
        for r, _k in rows_kinds:
            parts = []
            zone = zmap.get(r.unique_id)
            if zone:
                parts.append('in %s' % zone)
            if r.unique_id in placed:
                names = placed[r.unique_id]
                parts.append('on map %s' % ', '.join(names) if names else 'on the map')
            elif not zone:
                parts.append('not on a map')
            if r.unique_id in pmap:
                pname = (pmap[r.unique_id][1] or '').strip()
                parts.append('part of %s' % pname if pname
                             else 'part of an unnamed device')
            tab = tabs.get(getattr(r, 'tab_id', None))
            if tab:
                parts.append('tab %s' % tab)
            out.append(', '.join(parts))
        # 단서가 겹치면 종류·모듈로 가른다(같은 탭·같은 구역의 입력과 출력 등).
        seen = {}
        for w in out:
            seen[w] = seen.get(w, 0) + 1
        for i, (r, k) in enumerate(rows_kinds):
            if seen[out[i]] > 1:
                mod = getattr(r, 'device', None) or getattr(r, 'output_type', None)
                extra = '%s %s' % (k, mod) if mod else k
                out[i] = '%s, %s' % (out[i], extra) if out[i] else extra
        return out

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

    #: 장치 옵션 보기에 싣는 최대 개수 — 큰 모듈도 한 화면 분량으로.
    _DEVICE_OPTION_CAP = 30

    @classmethod
    def _device_options_view(cls, kind, module_type, row):
        """입력·출력의 설정 옵션 — 키·이름·지금 값. 입출력 수정의 params 키가 이것이다.

        2026-10-28 claude.ai 점검: 장치 상세에 옵션 id·지금 값이 없어 AI 가 매뉴얼의
        옵션 이름(사람 말)만 보고 params 에 무엇을 넣을지 몰랐다. 원천은 종류의 옵션
        정의(웹 설정 화면과 같다)·입력의 표준 칸(주기·사전 출력)·저장값이다 — 정의에
        없는 저장 키는 싣지 않는다. 비밀 값(키·토큰·비밀번호)은 연결 필드 요약과 같은
        규칙으로 set/unset 만 낸다."""
        import json as _json
        import re as _re
        spec = cls._device_option_spec(kind, module_type)
        if not spec:
            return []
        custom, columns = spec
        try:
            stored = _json.loads(getattr(row, 'custom_options', None) or '{}')
        except (ValueError, TypeError):
            stored = {}
        if not isinstance(stored, dict):
            stored = {}
        secret = _re.compile(r'password|token|secret|key|credential|passphrase|auth', _re.I)
        out = [{"key": col, "name": label, "value": getattr(row, col, None)}
               for col, (label, _typ) in columns.items()]
        for key, o in custom.items():
            value = stored.get(key, o.get('default_value'))
            if secret.search(str(key)):
                value = 'set' if value else 'unset'
            item = {"key": key, "value": value}
            if o.get('name'):
                item["name"] = str(o['name'])
            out.append(item)
        return out[:cls._DEVICE_OPTION_CAP]

    @classmethod
    def _spatial_label(cls, spatial_kind, spatial_id):
        """GeoBinding.spatial_id → (사람이 읽는 이름, 공간 종류) 또는 (None, None)."""
        try:
            if spatial_kind == 'shape':
                shape = GeoShape.query.filter_by(unique_id=spatial_id).first()
                if not shape:
                    return None, None
                from aot.space import plot_context
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
            from aot.space import device_binding
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
            # operate_device 가 즉시 제어의 정식 경로다. 네이티브 set_output_state
            # 는 외부 키 목록에 없으므로 여기서 가리키지 않는다.
            controlling_tools = ['operate_device']
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

    #: `fields` 로 더 청할 수 있는 갈래 → 전체 응답의 칸. 요약은 이 칸들을 싣지 않는다.
    _DETAIL_MORE = {
        'options': ('options',),
        'connection': ('communication', 'communication_note'),
        'measurements': ('measurements', 'measurements_note'),
        'bindings': ('geo_bindings', 'geo_bindings_note'),
        'constraints': ('constraints',),
        'location': ('location', 'location_note'),
        'outputs': ('output_channels', 'output_channels_note'),
    }

    @classmethod
    def _detail_summary(cls, full, fields):
        """전체 응답 → 요약(이름·종류·켜짐·상태·위치·최근 수신·측정 채널 이름과 단위) + `fields` 로 청한 갈래.

        접속 옵션 전체와 장치 옵션 전체, 측정 채널의 id·select_value 는 길어서(MQTT 장치 하나가 수백 토큰)
        기본 응답에서 뺀다. 이름을 모르는 갈래는 무시하지 않고 알려 준다. 'all' 이면 전체."""
        want = [str(f).strip().lower() for f in (fields if isinstance(fields, (list, tuple)) else [fields])
                if f not in (None, '')]
        if 'all' in want:
            return full
        what = full.get('what') or {}
        keep = {k: what[k] for k in what if k not in ('active_note',)}
        out = {"device_id": full.get("device_id"), "what": keep}
        loc = full.get("location") or {}
        if loc.get("place"):
            out["place"] = loc["place"]
        elif loc.get("lat") is not None and loc.get("lng") is not None:
            out["lat"], out["lng"] = loc["lat"], loc["lng"]
        else:
            out["place"] = None
        if full.get("last_seen") is not None:
            out["last_seen"] = full["last_seen"]
        # 같은 계열(`Rain +0d`…`+15d`)은 한 줄로 — 채널이 수십 개인 예보 장치가 이름만으로도 길었다.
        chans = cls._channel_table(full.get("measurements") or [])
        if chans:
            out["channels"] = chans
        outs = [{"channel": c.get("channel"), "name": c.get("name")} for c in full.get("output_channels") or []]
        if outs:
            out["output_channels"] = outs
        spaces = [b.get("space_name") for b in full.get("geo_bindings") or [] if b.get("space_name")]
        if spaces:
            out["bound_to"] = spaces
        unknown = []
        for name in want:
            if name == 'summary':
                continue
            cols = cls._DETAIL_MORE.get(name)
            if not cols:
                unknown.append(name)
                continue
            for col in cols:
                if col in full:
                    out[col] = full[col]
        if 'measurements' in out:
            # 채널 id 를 청했으면 `measurements` 가 이름·단위도 이미 싣는다 — 같은 표를 두 번 싣지 않는다.
            out.pop("channels", None)
        left = [n for n in ('options', 'connection', 'measurements', 'bindings', 'constraints')
                if cls._DETAIL_MORE[n][0] in full and cls._DETAIL_MORE[n][0] not in out]
        if unknown:
            out["unknown_fields"] = unknown
        if left:
            out["more"] = "fields=[%s] adds the rest (all = everything)" % ", ".join(left)
        return out

    @classmethod
    def get_device_detail(cls, device_id=None, fields=None, **extra):
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
                from aot.services.resolvers.device_resolver import (
                    device_status_info)
                status_info = device_status_info(row)
                active_note = (
                    "상태 %s%s — 켜 둔 채지만 평균·침묵 판정에서 빠집니다."
                    % (status_info["status"],
                       (": " + status_info["note"]) if status_info["note"] else "")
                    if status_info else None)
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
            if kind == 'input':
                what["device_status"] = status_info or {"status": "ok"}
            if kind == 'output':
                # 이 출력이 받는 명령 — 없으면 AI 가 PWM·개폐 출력도 켜고 끄기만 된다고 여겼다(2026-11-12).
                from aot.outputs.command_forms import output_capabilities, value_range
                what["controls"] = output_capabilities(module_type)
                rng = value_range(module_type)
                if rng:
                    what["value_range"] = rng
            if kind in ('input', 'output'):
                what.update(_sim_fields(kind, module_type, row.name))

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

            out = {
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
            if kind in ('input', 'output'):
                out["options"] = cls._device_options_view(kind, module_type, row)
            if fields is not None:
                # 요약 보기(도메인 틀의 detail.device) — 전체는 fields 로 청한 갈래만 더한다.
                if kind == 'input':
                    try:
                        # 채널 수는 measure.freshness 와 같게 — 2개만 물으면 온도·습도가 조용하고
                        # 배터리만 오는 장치를 '7일 동안 수신 없음' 으로 잘못 보였다(2026-10-31).
                        age, seen, _label = cls._last_seen_seconds(
                            resolved_id, window_s=7 * 86400)
                        out["last_seen"] = ({"at": seen, "age_s": int(age)} if seen is not None
                                            else {"at": None, "within": "7d"})
                    except Exception:
                        logger.debug("get_device_detail: 최근 수신 조회 실패", exc_info=True)
                return cls._detail_summary(out, fields)
            # 기본 응답에는 설정 옵션·연결 값(호스트·사용자명·클라이언트 ID·포트)을 싣지 않는다 —
            # 장치 하나가 수백 토큰이고 민감하다(2026-11-03). 청하면(fields) 나온다.
            if "options" in out or (out.get("communication") or {}).get("fields"):
                out.pop("options", None)
                if out.get("communication"):
                    out["communication"] = {k: v for k, v in out["communication"].items()
                                            if k != "fields"}
                out["more"] = ("fields=[options, connection] adds the settings and connection "
                               "values (secrets only as set/unset)")
            return out
        except Exception as e:
            logger.exception("Error in get_device_detail")
            return {"error": str(e)}

    @classmethod
    def get_control_state(cls, facility_name=None, facility_id=None,
                          include_inactive=False, detail=False, brief=False, **extra):
        """[읽기전용] 환경제어 코디네이터의 현재 목표값과 최근 판단 결과.

        `brief` 는 도구 스키마에 없는 처리기 인자다 — 도메인 표면(overview.control_state)만 켠다(2026-10-31).
        시설을 안 정하고 `detail` 도 아니면 제어기마다 **한 줄**(이름·시설·동작 여부·제한 요인·게이트·편차·움직이는 명령)만 낸다
        (제어기 3개에 5천 토큰). 시설을 정하면 아래 `detail=False` 의 줄인 형태, `detail=True` 면 전부 — 예전과 같다.
        안 주면(인앱 AI·개요) 예전과 같다.

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

        `detail`(기본 False)이 꺼져 있으면 두 곳을 줄인다(2026-09-29, 벤치
        실측 중앙값 14,954자 → 목표 4,000자 이하):
          - 코디네이터마다 `tolerance`/`priority`(설정값, 자주 안 바뀜)를
            뺀다 — `safety_range`(안전 상·하한)는 그대로 남는다.
          - `latest_cycle_summary`는 이 도구의 존재 이유(목표·제약·게이트·
            액추에이터+사유)에 해당하는 키만 남기고, UI 관측용 진단값
            (greybox_skill·mpc_shadow·solar_lead·capability·basis·actuation·
            vent·outputs_by_kind·trend·photo)은 뺀다 — 그 값들은 화면
            [현황] 탭이 쓰는 값이지 제어 조언에 필요한 값이 아니다.
        `detail=True`면 둘 다 원본 그대로 낸다. 무엇을 뺐는지는 응답의
        `_omitted`가 말한다 — 없는 값이 아니라 줄인 값이다.
        """
        import json as _json
        lean = bool(brief) and not detail and not facility_id and not facility_name
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
            _facs = GeoFacility.query.all()
            fac_names = {f.unique_id: f.name for f in _facs}
            # 시설은 ID 가 둘이다 — GeoFacility.unique_id(코디네이터 옵션이 가리킨다)
            # 와 그 시설 도형의 GeoShape.unique_id(공간 트리·장소 경로가 쓴다).
            # 한쪽만 내면 두 도구를 대조할 수 없었다(2026-10-09 외부 점검). 둘 다
            # 싣고, facility_id 인자는 어느 쪽이든 받는다.
            fac_shape = {f.unique_id: f.shape_uuid for f in _facs}
            _tfac = None        # 정확히 풀린 시설 하나 — 결과에 대상 id 로 싣는다
            if facility_id:
                _fr = cls._resolve_facility(facility_id)
                if _fr is not None:
                    facility_id = _fr.unique_id
                    _tfac = _fr
            elif facility_name:
                _tfac = cls._resolve_facility(str(facility_name).strip())

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
                if fid and not lean:
                    try:
                        from aot.space import plot_context as _pc
                        _plants = [
                            cls._plot_ctl_brief(_pc.plot_brief_for_control(r), detail)
                            for r in _pc.plots_in_facility(fid, bay_id=_bay)]
                    except Exception as exc:
                        logger.warning(
                            "list_env_coordinators: 식생 조회 실패(%s): %s", fid, exc)

                entry = {
                    "function_id": c.unique_id,
                    "function_name": c.name,
                    "is_activated": bool(c.is_activated),
                    "facility_id": fid,
                    "facility_place_id": fac_shape.get(fid),
                    "facility_name": fname,
                    "bay_scope": o.get('bay_scope') or None,
                    "plots": _plants,
                    "effect_engine": o.get('effect_engine', 'legacy'),
                    "targets": {
                        "source": "plot program",
                        **_control_targets_for(c),
                        # vpd_kpa 가 어느 VPD 의 목표인가 — air(기본) 또는 leaf.
                        "vpd_basis": _vpd_basis_of(o),
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
                if detail:
                    entry["tolerance"] = {
                        "vpd": o.get('tolerance_vpd'),
                        "temperature_c": o.get('tolerance_temperature'),
                        "humidity_pct": o.get('tolerance_humidity'),
                        "co2_ppm": o.get('tolerance_co2'),
                    }
                    entry["priority"] = {
                        "vpd": o.get('priority_vpd'),
                        "temperature": o.get('priority_temperature'),
                        "humidity": o.get('priority_humidity'),
                        "co2": o.get('priority_co2'),
                    }

                state = FunctionRuntimeState.query.filter_by(function_id=c.unique_id).first()
                if state and state.summary_json:
                    try:
                        summary = _json.loads(state.summary_json)
                        # 공기 VPD 는 air_kpa, 잎 VPD 는 잰 엽온이 있을 때만(`vpd`).
                        _vr = _vpd_readout_of(summary)
                        if _vr:
                            summary["vpd"] = _vr
                        _dr = cls._degraded_reasons(summary)
                        if _dr:
                            summary["degraded_reasons"] = _dr
                        summary = (summary if detail
                                   else cls._cycle_summary_brief(summary))
                        # 근거는 숫자(27)로 저장된다 — 이름을 곁들인다.
                        if isinstance(summary, dict):
                            from aot.functions.utils.env_control import \
                                log_channels as _LC
                            for _cmd in summary.get('commands') or []:
                                if isinstance(_cmd, dict) and 'reason' in _cmd:
                                    _cmd['reason_name'] = _LC.reason_name(
                                        _cmd['reason'])
                        # 사이클 시각은 epoch 초로 저장된다 — 그대로 내면 모델이
                        # 숫자를 읽지 못한다. 시설(없으면 함수)의 위치 시각으로.
                        if isinstance(summary, dict) and isinstance(
                                summary.get('ts'), (int, float)):
                            from aot.utils.timekit import iso_at
                            summary = dict(summary, ts=iso_at(summary['ts'], fid or c.unique_id))
                        entry["latest_cycle_summary"] = summary
                    except (ValueError, TypeError):
                        entry["latest_cycle_summary_error"] = "Failed to parse summary_json"
                else:
                    entry["latest_cycle_summary"] = None
                    entry["latest_cycle_note"] = (
                        "No decision-cycle record yet - the coordinator has never run, "
                        "or summary recording is disabled.")
                out.append(entry)

            if lean and out:
                return cls._control_lines(out)
            result = {"status": "success", "count": len(out), "coordinators": out}
            if out and _tfac is not None and getattr(_tfac, 'shape_uuid', None):
                cls._with_target(result, 'facility', _tfac.shape_uuid,
                                 ref=facility_id or facility_name, exact=True)
            if out and not detail:
                result["_omitted"] = (
                    "Each coordinator's 'tolerance'/'priority' (rarely-changing "
                    "config) and 'latest_cycle_summary' fields other than "
                    "ts/limiting_factor/strain/deviation/targets/gate/"
                    "feedforward/schedule/commands/unmeasured/modes/vpd (display-"
                    "only diagnostics: capability, greybox_skill, mpc_shadow, "
                    "solar_lead, basis, actuation, vent, outputs_by_kind, "
                    "trend, photo) were dropped to fit the response size. "
                    "Each plot under 'plots' also drops 'timeline.stages' "
                    "(the full stage-by-stage schedule — get_plot has it) and "
                    "keeps only the current stage's name/index/position. Call "
                    "again with detail=true for all of it.")
            return result
        except Exception as e:
            logger.exception("Error in get_control_state")
            return {"status": "error", "message": str(e)}

    @classmethod
    def _control_lines(cls, entries):
        """overview.control_state 대상 없음 — 제어기마다 한 줄. 값은 전체 응답의 것을 그대로 옮긴다(반올림·단위 변경 없음).

        이름이 겹치는 제어기('Env Coordinator' 동명 2개 사례)에만 function_id 를 단다. 명령은 움직이는 것(0% 아님)만
        "slot kind pct%" 로, 쉬는 것은 개수만. 시설을 주면 목표·안전 범위·구획·판단 전체(줄인 형태)를 받는다."""
        names = {}
        for e in entries:
            key = str(e.get('function_name') or '').strip().lower()
            names[key] = names.get(key, 0) + 1
        rows = []
        for e in entries:
            row = {"function_name": e.get("function_name"), "facility_name": e.get("facility_name"),
                   "is_activated": e.get("is_activated")}
            if names[str(e.get('function_name') or '').strip().lower()] > 1:
                row["function_id"] = e.get("function_id")
            cyc = e.get("latest_cycle_summary")
            if not isinstance(cyc, dict):
                row["latest_cycle"] = None
                rows.append(row)
                continue
            row["ts"] = cyc.get("ts")
            row["limiting_factor"] = cyc.get("limiting_factor")
            gate = cyc.get("gate") or {}
            row["gate_triggered"] = bool(gate.get("triggered"))
            if gate.get("triggered") and gate.get("description"):
                row["gate"] = gate["description"]
            if cyc.get("deviation"):
                row["deviation"] = cyc["deviation"]
            if cyc.get("unmeasured"):
                row["unmeasured"] = cyc["unmeasured"]
            moving, idle = [], 0
            for c in cyc.get("commands") or []:
                if not isinstance(c, dict):
                    continue
                if c.get("pct"):
                    moving.append("%s %s %s%%" % (c.get("slot_key"), c.get("kind"), c.get("pct")))
                else:
                    idle += 1
            if moving:
                row["commands"] = moving
            if idle:
                row["idle_commands"] = idle
            rows.append(row)
        return {"status": "success",
                "next": {"call": "overview(op='control_state', target=<facility name>)",
                         "why": "that facility's targets, safety range, plots and every command with its reason; "
                                "detail=true gives every controller in full"},
                "count": len(rows), "coordinators": rows}

    #: `latest_cycle_summary` 의 키 중 이 도구의 존재 이유(목표·제약·게이트·
    #: 액추에이터+사유)에 해당하는 것만. 나머지는 화면 [현황] 탭의 관측용
    #: 진단값(greybox_skill·mpc_shadow·solar_lead·capability·basis·actuation·
    #: vent·outputs_by_kind·trend·photo)이라 기본 응답에서 뺀다.
    _CYCLE_SUMMARY_KEEP = (
        'ts', 'limiting_factor', 'strain', 'deviation', 'targets', 'gate',
        'degraded_reasons',
        'feedforward', 'schedule', 'commands', 'unmeasured', 'modes',
        # 현재 VPD — 공기 VPD(air_kpa)와, 잰 엽온이 있을 때만 잎 VPD(leaf_kpa), 목표 기준.
        # 목표 편차(`deviation.vpd`)가 어느 VPD 의 것인지 읽는 근거다.
        'vpd',
    )

    _AXIS_LABEL = {'T': 'temperature', 'RH': 'humidity', 'CO2': 'CO2',
                   'Light': 'light'}

    @classmethod
    def _degraded_reasons(cls, summary):
        """모드에 'degraded' 가 있으면 어느 변수·방향이 왜 NATURAL 인지.

        NATURAL 은 센서 상태가 아니라 **그 축을 움직일 구동기 종류가 등록되지
        않았다**는 뜻이다(authority.derive_authority). 센서가 안 들어와 제어에서
        빠진 변수는 `unmeasured` 가 따로 말한다 — 둘을 섞지 않는다.
        """
        if not isinstance(summary, dict) or 'degraded' not in (summary.get('modes') or []):
            return None
        try:
            from aot.functions.utils.env_control.authority import _KIND_AUTHORITY
        except Exception:                                   # noqa: BLE001
            _KIND_AUTHORITY = {}
        axes = summary.get('natural_axes')
        if axes is None:
            return [{"reason": "some variables are NATURAL (no actuator registered "
                               "for that axis); this cycle record predates the axis "
                               "list - it appears after the next cycle."}]
        out = []
        for key in axes:
            var, _, direction = key.partition('_')
            kinds = sorted(k for k, m in _KIND_AUTHORITY.items() if key in m)
            out.append({
                "axis": key,
                "meaning": "%s %s" % (cls._AXIS_LABEL.get(var, var),
                                      'increase' if direction == 'up' else 'decrease'),
                "reason": "no registered actuator can move this axis (needs one of: "
                          "%s) - not a sensor fault" % (', '.join(kinds) or 'n/a'),
            })
        um = summary.get('unmeasured') or []
        if um:
            out.append({"axis": "unmeasured", "variables": list(um),
                        "reason": "target set but no measurement (sensor off/no data)"})
        return out

    @classmethod
    def _cycle_summary_brief(cls, summary):
        """`_build_cycle_summary` 원본(dict) → 요약(dict). 원본은 건드리지 않는다."""
        if not isinstance(summary, dict):
            return summary
        return {k: summary[k] for k in cls._CYCLE_SUMMARY_KEEP if k in summary}

    @classmethod
    def _plot_ctl_brief(cls, p, detail):
        """`plot_brief_for_control` 결과 → `detail=False` 면 `timeline.stages`
        (전체 단계 일정 — 실측: 구획 하나에 최대 수 킬로바이트)를 뺀다.

        `timeline` 의 나머지 스칼라(시작·기준일·끝·경과일·오늘 진행률)는
        남는다 — "지금 몇 %째인가" 는 제어 조언에도 쓰이지만, 단계별 전체
        일정표는 get_plot 의 몫이다. `plot_brief_for_control` 자체(화면 제어
        탭이 같이 쓴다)는 건드리지 않고, 여기서 얕은 복사만 한다."""
        if detail or not isinstance(p, dict):
            return p
        tl = p.get('timeline')
        if not isinstance(tl, dict) or 'stages' not in tl:
            return p
        p = dict(p)
        p['timeline'] = {k: v for k, v in tl.items() if k != 'stages'}
        return p

    @classmethod
    def get_output_state(cls, device_id=None, channel=None, device_ids=None,
                         **extra):
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

        대상은 unique_id 또는 이름(`_read_device`), 여러 개면 `device_ids`
        (최대 MAX_READ_TARGETS) — 같은 도구를 장치마다 되풀이 부르던 왕복을 줄인다.
        """
        tokens, err = cls._targets_arg(device_id, device_ids, 'device_id')
        if err:
            return err
        if len(tokens) == 1:
            return cls._output_state_one(tokens[0], channel)
        return cls._for_each_target(
            tokens, lambda t: cls._output_state_one(t, channel))

    @classmethod
    def _output_state_one(cls, token, channel=None):
        try:
            output, _kind, err = cls._read_device(token, kinds=('output',))
            if err:
                return err
            device_id = output.unique_id

            from aot.aot_client import DaemonControl
            from aot.widgets.AoT_timer import _read_latest_started_at

            daemon = DaemonControl()
            all_states = daemon.output_states_all() or {}
            channel_states = all_states.get(device_id, {})

            # 모터로 여닫는 장치면 **얼마나 열려 있는지**를 따로 싣는다 —
            # 데몬이 죽어 있어도 저장된 위치는 읽힌다.
            position = cls._actuator_position(output, channel_states)

            if not channel_states:
                out = {
                    "status": "success",
                    "device_id": device_id,
                    "name": output.name,
                    "channels": {},
                    "message": "No live state available (daemon may be down, or this "
                               "output hasn't been read since it started)."
                }
                if position is not None:
                    out["position"] = position
                    out["_reading"] = cls._actuator_position_reading(position)
                return out

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
                        # 이 출력이 놓인 곳의 시각(예전엔 농장 시각).
                        from aot.utils.timekit import iso_at
                        entry["started_at"] = iso_at(started["selected_epoch"], device_id)
                except Exception:
                    pass
                channels_out[str(ch)] = entry

            out = {
                "status": "success",
                "device_id": device_id,
                "name": output.name,
                "channels": channels_out,
            }
            if position is not None:
                out["position"] = position
                out["_reading"] = cls._actuator_position_reading(position)
            return out
        except Exception as e:
            logger.exception("Error in get_output_state")
            return {"error": str(e)}

    @classmethod
    def _actuator_position(cls, output, channel_states):
        """모터로 여닫는 장치(측창·천창·커튼) → 개도 dict. 그런 장치가 아니면 None.

        벤치(26-09-23): "측창 얼마나 열려 있어?" 에 응답이 채널 `off`·
        `seconds_on 0` 뿐이라 모델 대부분이 "닫힘(0%)" 으로 답했다. 저장된
        위치는 50% 였다. 모터가 멈춰 있다는 것과 닫혀 있다는 것은 다르다.

        **알아보는 기준은 장치 종류 이름이 아니라 `last_position_pct` 옵션**
        이다 — 환경 코디네이터가 같은 기준으로 장치 위치를 읽는다
        (`_sync_prev_from_devices`: "actuator_paired 만 보유"). 이 값은 장치
        모듈이 이동·정지마다 저장해 재시작 뒤에도 남는다.

        출처 순서: 데몬이 **숫자**로 준 현재 위치(이동 중이면 경과 시간으로
        추정한 값) → 저장된 마지막 위치. 데몬의 `off` 는 이 모듈에서 0% 를
        뜻하지만 저장값과 어긋나면 **둘 다** 보인다 — 하나를 골라 말하면
        틀린 쪽을 고른 사실이 사라진다. 제어 로직은 건드리지 않는다(읽기만).

        `value_logged_then` 은 `last_moved_at` 에 기록된 duty_cycle 이다 —
        모듈은 이동을 **시작할 때 목표값**을, **멈출 때 위치**를 같은 계열에
        쓴다. 그래서 그 값은 목표일 수도 위치일 수도 있다(`_reading` 이 밝힌다).

        ⚠ 원격 출력(`remote_output_pwm`/`remote_output_on_off`)으로 감싼 다른
        서버의 개폐기는 알아보지 못한다 — 위치 옵션이 이 서버에 없고, 알려면
        원격 서버에 물어야 해서 싸지 않다. 그런 출력은 종전처럼 채널 상태만 낸다.
        """
        import json as _json
        try:
            from aot.databases.models import OutputChannel
            ch0 = OutputChannel.query.filter_by(
                output_id=output.unique_id, channel=0).first()
            opts = _json.loads((ch0.custom_options if ch0 else '') or '{}')
        except Exception:
            return None
        if not isinstance(opts, dict) or 'last_position_pct' not in opts:
            return None

        def _num(v):
            try:
                return None if v is None or isinstance(v, bool) else float(v)
            except (TypeError, ValueError):
                return None

        saved = _num(opts.get('last_position_pct'))
        target = _num(opts.get('last_target_pct'))
        live_raw = (channel_states or {}).get(0, (channel_states or {}).get('0'))
        live = _num(live_raw)

        pos = {"percent": None, "source": None,
               "meaning": "0 = fully closed, 100 = fully open"}
        if live is not None:
            pos.update(percent=round(live, 1), source="live")
        elif saved is not None:
            pos.update(percent=round(saved, 1), source="saved")
            if live_raw == 'off' and saved > 0:
                pos["live_state_disagrees"] = True
        if target is not None and target >= 0:
            pos["last_target_percent"] = round(target, 1)

        # 마지막으로 움직이거나 멈춘 시각 — 모듈이 그때마다 duty_cycle 로
        # 기록한다(정지 시에는 위치, 출발 시에는 목표값).
        try:
            from aot.utils.influx import read_influxdb_single
            ts, val = read_influxdb_single(
                output.unique_id, 'percent', 0, measure='duty_cycle',
                duration_sec=30 * 86400, value='LAST')
            if ts is not None:
                from aot.utils.timekit import iso_at
                pos["last_moved_at"] = iso_at(ts, output.unique_id)
                if _num(val) is not None:
                    pos["value_logged_then"] = round(float(val), 1)
        except Exception:
            pass
        return pos

    @staticmethod
    def _actuator_position_reading(position):
        notes = [
            "This output is a motor-driven opening (vent/curtain). How open it "
            "is lives in 'position.percent', not in the channel 'state': "
            "'seconds_on' 0 means the motor is not running right now, NOT that "
            "it is closed. Answer 'how open' from 'position' and say which "
            "'source' it came from ('live' = the running daemon, 'saved' = the "
            "last position the device stored after it moved).",
            "What the environment controller is trying to set it to is a "
            "different number — read it with get_control_state "
            "if the question is about control.",
        ]
        if position.get("value_logged_then") is not None:
            notes.append(
                "'value_logged_then' is the number the device logged at "
                "'last_moved_at'. It logs its TARGET when a move starts and its "
                "POSITION when the move ends, so it may be where the opening was "
                "heading rather than where it stopped — use 'percent' for how "
                "open it is.")
        if position.get("percent") is None:
            notes.append(
                "The position is unknown — nothing live and nothing saved. Say "
                "that; do not report it as closed.")
        if position.get("live_state_disagrees"):
            notes.append(
                "'live_state_disagrees': the channel reports 'off' (which this "
                "device uses for 0%%) but the saved position is %s%%. Tell the "
                "user both numbers; the device may need checking."
                % position.get("percent"))
        return notes

