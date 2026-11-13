import logging
from aot.tools.aot_data_tool_service import _with_translated_alias
from ._shims import _FakeForm

logger = logging.getLogger(__name__)


from aot.aot_flask.extensions import db
from aot.databases.models import DeviceMeasurements
from aot.databases.models import GeoShape
from aot.databases.models import Input
from aot.databases.models import Output


class CommonToolsMixin:
    """Cross-drawer target-name-resolution helpers.
    
    These are called from 2+ drawers (record/schedule/space/system/device/
    measurement) so they cannot live in a single drawer file without one
    drawer importing another. Split out of aot_data_tool_service.py, where
    they were plain @staticmethods on AoTDataToolService.
    """

    _FakeForm = _FakeForm

    @staticmethod
    def _bounded_limit(limit, default, maximum):
        """목록 조회의 limit — 기본 `default`, 상한 `maximum`, 1 이상. 못 읽는 값은 기본.

        응답 캡(15,000토큰)은 넘으면 자른 채 보내고 모델은 다시 부른다 — 한 번에 캡 안에 들어오는 크기로
        미리 막는다(2026-11-07 실측: search_schedule limit=500 → 53,877토큰 → 잘림 → 3번 재조회)."""
        try:
            n = int(limit) if limit not in (None, '') else default
        except (TypeError, ValueError):
            n = default
        return max(1, min(n, maximum))

    @staticmethod
    def _offset(offset):
        try:
            return max(0, int(offset)) if offset not in (None, '') else 0
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _page_rows(rows, limit=None, offset=None, default=None):
        """목록 한 쪽 — (그 쪽, 안내 dict 또는 None). limit·offset 은 조회 도구 전체의 같은 말.

        자르지 않았으면 안내는 None. 잘랐으면 전체 수와 다음 offset 을 알린다 — 이어 받는 길이
        응답에 있어야 AI 가 건수를 지어내지 않는다."""
        try:
            lim = int(limit) if limit not in (None, '') else (default or 0)
            off = max(0, int(offset)) if offset not in (None, '') else 0
        except (TypeError, ValueError):
            lim, off = (default or 0), 0
        lim = max(0, lim)
        total = len(rows)
        if not lim and not off:
            return rows, None
        page = rows[off:off + lim] if lim else rows[off:]
        if len(page) >= total:
            return page, None
        info = {"total": total, "shown": len(page), "offset": off}
        if off + len(page) < total:
            info["next_offset"] = off + len(page)
        return page, info

    @staticmethod
    def _place_geo(kind, ident, full=True):
        """장소(대지·구역·시설)의 좌표 요약 — {center:[lat,lng], bbox, area_m2}.

        도형 전체(GeoJSON)는 싣지 않는다. full=False 면 center 만(목록용).
        좌표를 알 수 없으면(도형 없음·점이 아님 등) 해당 필드를 뺀다 —
        빈 dict 는 "지도에 그려진 도형이 없다" 는 뜻이다. 시설 id 가 GeoFacility
        것이면 연결된 도형으로 넘어간다. 계산은 device_binding 의 기존 함수를 쓴다."""
        if kind not in ('site', 'zone', 'facility') or not ident:
            return {}
        try:
            from aot.space import device_binding as db_
            from aot.databases.models import GeoFacility
            sh = GeoShape.query.filter(GeoShape.unique_id == ident).first()
            if sh is None:
                fac = GeoFacility.query.filter_by(unique_id=ident).first()
                if fac is not None and fac.shape_uuid:
                    sh = GeoShape.query.filter(
                        GeoShape.unique_id == fac.shape_uuid).first()
            if sh is None:
                return {}
            feat = sh.feature or {}
            center = db_._centroid(feat)
            if not center:
                return {}
            out = {"center": center}
            if full:
                pts = db_._flat_coords((feat.get('geometry') or {}).get('coordinates'))
                lats, lngs = [p[1] for p in pts], [p[0] for p in pts]
                out["bbox"] = [round(min(lats), 7), round(min(lngs), 7),
                               round(max(lats), 7), round(max(lngs), 7)]
                area = db_._area_m2(feat)
                if area:
                    out["area_m2"] = area
            return out
        except Exception:                                   # noqa: BLE001
            logger.debug("place geo lookup failed", exc_info=True)
            return {}

    @staticmethod
    def _with_target(out, kind, ident, ref=None, exact=False):
        """조회 결과에 **풀린 대상**(종류·id)을 싣는다 — 화면 따라가기(screen_follow)가
        이름을 다시 풀지 않고 이 id 로 연다. 대상이 정확히 하나로 풀렸을 때만 부른다
        (여럿이면 싣지 않는다). resolve_target 의 target_id/target_type 과 같은 이름이다.

        ref 는 사람이 말한 인자. 주면 **어떻게 풀렸는지** `match`('id'|'exact'|'partial')
        를 함께 싣고, 말 일부가 무시됐으면 `ignored_terms` 도 싣는다 — 따라가기는 partial
        이면 열지 않고 되묻는다. exact=True 는 이름·id 정확일치만 받는 리졸버(시설 등)."""
        if isinstance(out, dict) and ident and 'target_id' not in out:
            out['target_id'] = str(ident)
            out['target_type'] = kind
            if ref:
                from aot.tools.screen_follow import match_of
                m, ignored = match_of(ref, ident, exact)
                if m:
                    out['match'] = m
                if ignored:
                    out['ignored_terms'] = ignored
        return out

    @classmethod
    def _device_ids_with_measurement(cls, measurement_type):
        """그 측정을 **실제로 가진** 장치 id 집합. 이름은 보지 않는다.

        이름으로 센서를 찾는 것은 믿을 수 없다 — 같은 토양수분 센서가
        '토양온습도_1' 이기도 '온습도_1' 이기도 하다. 그래서 후보를 이름으로
        추려 놓고 장치마다 get_device_measurements 를 불러 채널을 확인하는
        왕복이 생겼다(실측 7회). DeviceMeasurements.measurement 로 한 번에
        거르면 그 왕복 전체가 사라진다.
        """
        like = "%%%s%%" % str(measurement_type).strip()
        rows = DeviceMeasurements.query.with_entities(
            DeviceMeasurements.device_id).filter(
                DeviceMeasurements.measurement.like(like)).all()
        return {r[0] for r in rows if r[0]}

    @classmethod
    def _without_ai_excluded(cls, results, key='id'):
        """목록 결과에서 'AI 판단에 포함' 을 끈 입력·출력을 덜어 낸다.

        docs/ai/overview.md#device-ai-toggle — 끈 장치는 AI 도구의 조회에서
        빠진다. 판정은 공용 헬퍼(`device_resolver.ai_excluded_ids`) 하나다.
        복합장치 행의 `member_ids` 에서도 뺀다. 원본 목록은 건드리지 않는다."""
        from aot.services.resolvers.device_resolver import ai_excluded_ids
        hidden = ai_excluded_ids()
        if not hidden:
            return results
        out = []
        for r in results or []:
            if r.get(key) in hidden:
                continue
            if r.get('member_ids'):
                r = dict(r, member_ids=[m for m in r['member_ids']
                                        if m not in hidden])
            out.append(r)
        return out

    @classmethod
    def _geoshape_name_candidates(cls, limit=20):
        """지도 도형(GeoShape) 이름 후보 목록 — 위치 미해석 시 ask_user 제시용."""
        import json as _json
        out = []
        for s in GeoShape.query.limit(40).all():
            try:
                f = s.feature if isinstance(s.feature, dict) else _json.loads(s.feature or '{}')
                nm = (f.get('properties') or {}).get('name')
                if nm:
                    out.append(nm)
            except Exception:
                continue
        return out[:limit]

    # ── 같은 이름 ────────────────────────────────────────────────────────
    #
    # 벤치(26-09-23): '육묘장' 은 지도 두 장의 부지 둘과, 그중 한 부지 **안의**
    # 같은 이름 시설 하나에 걸렸다. 정확일치 단계가 정렬 순서로 시설을 골라
    # "exactly one entity" 라고 답했고, 모델은 거의 되묻지 않았다. 또 이름 없이
    # 부른 구역 요약은 부지(센서 8개)를, resolve_target 을 거친 경로는
    # 시설(7개)을 봐서 같은 '육묘장' 의 센서 수가 달랐다.
    #
    # 그래서 **어느 단계에서 걸렸든** 후보를 **곳** 단위로 묶는다
    # (`_settle`: 정확일치·한정어·부분일치 전부).
    #   - 같은 장치를 가리키는 도형(마커+폴리곤)은 한 곳이다.
    #   - 같은 이름의 도형이 다른 도형 **안에** 있으면 한 곳이고, 이름은 바깥
    #     전체를 가리킨다(구역 요약·공간 트리가 나열하는 그 도형). 안쪽 것은
    #     `inner` 로 남겨 resolve_target 이 `also_inside` 로 알린다 — 시설
    #     전용 도구가 시설을 원하면 그 target_id 를 쓴다.
    #   - 그래도 둘 이상 남으면 **모호**다. 쓰기 리졸버는 고르지 않고
    #     (None, 'ambiguous'), resolve_target 과 쓰기 도구는 후보를 돌려준다.
    #     같은 이름의 Input/Output 이 둘 이상이어도 같다(`device_resolver` 가
    #     조작 경로에서 이미 그렇게 한다).
    #
    # 후보마다 붙이는 `use_name`(그 하나만 가리키는 이름)은 **실제로 리졸버에
    # 다시 넣어 그 후보로 풀리는 것만** 싣는다. 풀리지 않는 이름을 건네면 다음
    # 호출이 같은 자리에서 또 막힌다(리뷰 실측: 여러 낱말 지도 이름, 이름이 같은
    # 지도 둘). 만들 수 없으면 비워 두고 target_id 로 부르라고 안내한다.

    _PLACE_TYPES = ('zone', 'site', 'facility', 'facility_bay', 'equipment')
    _ZONE_LIKE_TYPES = ('zone', 'feature', 'device')

    @staticmethod
    def _shape_parent_lookup():
        """(부모 맵 {id: 부모 id}, {id: ShapeRec}). 캐시가 있으면 기하를 안 읽는다."""
        from aot.space import shape_index
        from aot.utils import geo_hierarchy as gh
        recs = shape_index.all_shapes()
        by_id = {r.id: r for r in recs}
        pmap = None
        try:
            pmap = gh._parent_map_from_cache(recs)
        except Exception:
            pmap = None
        if pmap is None:
            try:
                pmap = gh.build_geo_parent_map(GeoShape.query.all())
            except Exception:
                pmap = {}
        return pmap or {}, by_id

    @staticmethod
    def _ancestor_ids(sid, pmap, limit=16):
        out, cur = [], pmap.get(sid)
        while cur is not None and cur not in out and len(out) < limit:
            out.append(cur)
            cur = pmap.get(cur)
        return out

    @staticmethod
    def _exact_pref(rec):
        # 종전 정확일치의 선호(구역류 먼저)를 그대로 쓴다 — 장치 하나의
        # 마커·폴리곤 중 무엇을 대표로 삼는지는 바뀌지 않는다.
        return 0 if rec.type in ('zone', 'feature', 'device') else 1

    @classmethod
    def _group_places(cls, hits, pmap=None):
        """도형 [(rec, name)] → 곳 목록 [{'rep': (rec, name), 'device_id', 'inner'}].

        `inner` 는 대표(바깥) 도형 안에 든 같은 곳의 도형들이다.
        """
        places, by_dev, loose = [], {}, []
        for rec, name in hits:
            if rec.device_id:
                by_dev.setdefault(str(rec.device_id).split('::')[0], []).append((rec, name))
            else:
                loose.append((rec, name))
        for dev, members in by_dev.items():
            members.sort(key=lambda m: cls._exact_pref(m[0]))
            places.append({'rep': members[0], 'device_id': dev, 'inner': []})
        if len(loose) > 1 and pmap is None:
            pmap, _ = cls._shape_parent_lookup()
        ids = {rec.id for rec, _n in loose}
        outer, nested = {}, []
        for rec, name in loose:
            inside = [a for a in cls._ancestor_ids(rec.id, pmap or {}) if a in ids]
            if not inside:
                place = {'rep': (rec, name), 'device_id': None, 'inner': []}
                places.append(place)
                outer[rec.id] = place
            else:
                # 조상 목록은 가까운 것부터다 — 마지막이 가장 바깥이다.
                nested.append((inside[-1], (rec, name)))
        for top, member in nested:
            if top in outer:
                outer[top]['inner'].append(member)
        return places

    @classmethod
    def _same_name_devices(cls, ql):
        rows = []
        from sqlalchemy import func
        for model, kind in ((Input, 'input'), (Output, 'output')):
            try:
                rows.extend((r, kind) for r in model.query.filter(
                    func.lower(model.name) == ql).all())
            except Exception:
                continue
        return rows

    @classmethod
    def _normalized_name_devices(cls, key):
        """표기(공백·밑줄·하이픈·전각·대소문자)만 다른 이름의 입력/출력 장치."""
        from aot.tools.name_key import name_key
        rows = []
        for model, kind in ((Input, 'input'), (Output, 'output')):
            try:
                rows.extend((r, kind) for r in model.query.all()
                            if r.name and name_key(r.name) == key)
            except Exception:
                continue
        return rows

    @staticmethod
    def _map_names_by_lower():
        """{소문자 지도 이름: [geo_id, …]} — 이름이 같은 지도가 여럿일 수 있다."""
        out = {}
        try:
            from aot.databases.models import GeoMap
            for m in GeoMap.query.all():
                mn = (m.name or '').strip().lower()
                if mn:
                    out.setdefault(mn, []).append(m.unique_id)
        except Exception:
            return {}
        return out

    @classmethod
    def _resolve_facility(cls, token):
        """시설 인자 → GeoFacility 행(못 찾으면 None).

        시설은 ID 가 둘이다 — 시설 행의 `GeoFacility.unique_id`(코디네이터
        옵션·작물 현황·이상 점검이 쓴다)와 그 시설 도형의 `GeoShape.unique_id`
        (= `GeoFacility.shape_uuid`, 공간 트리·장소 경로가 쓴다). 도구마다 한쪽만
        받아, 트리에서 본 ID 로 부르면 빈 답이나 다른 답이 나왔다(2026-10-09 외부
        점검: 육묘장3 을 get_anomalies 에 도형 ID 로 주면 센서 0개, 시설 ID 로 주면
        2개). 시설을 받는 도구는 모두 여기를 지난다 — 어느 ID 든, 이름이든.
        이름은 정확히 하나일 때만 받는다(여럿이면 None).
        """
        token = str(token or '').strip()
        if not token:
            return None
        try:
            from aot.databases.models import GeoFacility
            row = GeoFacility.query.filter(
                (GeoFacility.unique_id == token) |
                (GeoFacility.shape_uuid == token)).first()
            if row is not None:
                return row
            named = [f for f in GeoFacility.query.all()
                     if (f.name or '').strip().lower() == token.lower()]
            return named[0] if len(named) == 1 else None
        except Exception as e:                              # noqa: BLE001
            logger.debug("_resolve_facility failed: %s", e)
            return None

    @classmethod
    def _device_names(cls, ids):
        """장치 ID → 장치 표의 실제 이름. 못 찾으면 빠진다.

        입력만 보면 밸브 같은 출력이 이름 대신 ID 로 나간다(구역 센서 요약이
        그랬다). 장치 이름이 필요한 도구는 여기를 쓴다.
        """
        ids = [i for i in set(ids) if i]
        if not ids:
            return {}
        out = {}
        try:
            from aot.databases.models import (
                Conditional, CustomController, Function, Input, Output, PID,
                Trigger)
            for model in (Input, Output, CustomController, Function, PID,
                          Trigger, Conditional):
                for uid, name in db.session.query(
                        model.unique_id, model.name).filter(
                        model.unique_id.in_(ids)).all():
                    if name:
                        out.setdefault(uid, name)
        except Exception as e:                              # noqa: BLE001
            logger.debug("_device_names: %s", e)
        return out

    @classmethod
    def _resolve_core(cls, target_name):
        """이름 해석의 본체. `_resolve_note_target` 은 이 결과의 'result' 다.

        Returns dict:
          result  — (target_id, target_type, resolved_name, lat, lng) 5-tuple.
                    모호하면 (None, 'ambiguous', None, None, None).
          places  — 모호할 때 서로 다른 곳들(`_group_places` 모양).
          devices — 모호할 때 지도에 없는 같은 이름 장치들 [(row, kind)].
          place   — 곳으로 묶어 답했을 때 그 곳(안쪽 같은 이름 `inner` 포함).
        """
        from aot.space import shape_index
        NONE = (None, None, None, None, None)
        res = {'result': NONE, 'places': [], 'devices': [], 'place': None,
               'plots': [], 'ignored_terms': []}
        if not target_name or not str(target_name).strip():
            return res
        _q = str(target_name).strip()
        _ql = _q.lower()

        # 이름이 있는 도형: 파싱 결과를 공용 인덱스에서 받는다.
        # 예전에는 이 함수와 `_resolve_note_target_ids` 가 각자
        # `GeoShape.query.all()` 을 돌아, 이름 하나 해석에 그 조회가 세 번
        # 났다(실측 23.5ms × 3). 비용은 파싱이 아니라 JSON 컬럼이 실린 행을
        # 읽는 것이다.
        shapes = shape_index.named_shapes()

        def _ret(shape, name):
            _tt = shape.type if shape.type in cls._PLACE_TYPES else 'zone'
            return shape.unique_id, _tt, name, None, None

        def _settle(hits, devices=()):
            """후보 → 한 곳이면 답, 여럿이면 모호, 없으면 None(다음 단계로)."""
            places = cls._group_places(hits) if hits else []
            mapped = {p['device_id'] for p in places if p['device_id']}
            loose_dev = [(r, k) for (r, k) in devices if r.unique_id not in mapped]
            n = len(places) + len(loose_dev)
            if n == 0:
                return None
            if n > 1:
                # 'ambiguous' 표시는 번역 별칭 재시도를 막는다 — 적힌 이름이
                # 여럿에 걸린 것이지 못 찾은 것이 아니다. 별칭으로 다시 찾으면
                # 또 다른 하나를 조용히 고르게 된다(실측: '육묘장' → 일본어
                # 지도의 '育苗場').
                res.update(result=(None, 'ambiguous', None, None, None),
                           places=places, devices=loose_dev)
                return res
            if places:
                res.update(result=_ret(*places[0]['rep']), place=places[0])
                return res
            row, kind = loose_dev[0]
            res['result'] = (row.unique_id, kind, row.name, None, None)
            return res

        # 1) Exact full-name match (most reliable). Grouped into PLACES: two
        #    different places → ambiguous (a write must not coin-flip); one
        #    place → its representative (the outer shape when same-name shapes
        #    are nested). Exactly one Input/Output with that exact name is the
        #    answer too — it must not fall through to the partial (ilike) pass
        #    below, which takes whichever row comes first ('v1' → 'v11').
        exact = [(s, n) for (s, n, nl) in shapes if nl == _ql]
        got = _settle(exact, cls._same_name_devices(_ql))
        if got:
            return got

        # 1b) 표기만 다른 이름 — "온습도 7" ↔ "온습도_7"(공백·밑줄·하이픈·전각·
        #     대소문자). 정확일치가 없을 때만, 열쇠가 같은 것이 한 곳이면 답하고
        #     여럿이면 모호다(고르지 않는다). 철자가 다른 이름은 여기서 맞추지 않는다.
        from aot.tools.name_key import name_key
        _qk = name_key(_q)
        if _qk:
            norm = [(s, n) for (s, n, nl) in shapes if name_key(n) == _qk]
            got = _settle(norm, cls._normalized_name_devices(_qk))
            if got:
                if got['result'][0]:
                    got['matched'] = {'rule': 'normalized', 'term': _q,
                                      'as': got['result'][2]}
                return got

        # 2) 한정어가 붙은 이름.
        #
        # 2a) 지도 이름 한정어('그린 육묘장', 'New Design Map 1구역'). 지도
        #     이름은 여러 낱말일 수 있어 **원문 앞머리의 가장 긴 지도 이름**을
        #     찾는다(낱말 단위로 쪼개 보던 때는 여러 낱말 이름을 못 알아봤다).
        #     이름이 같은 지도가 둘 이상이면 그 이름은 한정어가 못 된다 — 어느
        #     지도인지 가리지 못한다. 한정되면 그 뒤의 해석은 **그 지도 안에서만**
        #     한다: 그 지도에 없는데 다른 지도의 것으로 답하면 한정어를 무시한 것이다.
        scope, rest = shapes, _ql
        maps = cls._map_names_by_lower()
        for mn in sorted(maps, key=len, reverse=True):
            if len(maps[mn]) != 1:
                continue
            if _ql.startswith(mn) and len(_ql) > len(mn) and _ql[len(mn)].isspace():
                geo = maps[mn][0]
                scope = [t for t in shapes if t[0].geo_id == geo]
                rest = _ql[len(mn):].strip()
                got = _settle([(s, n) for (s, n, nl) in scope if nl == rest])
                if got:
                    return got
                break
        map_scoped = scope is not shapes

        # 2b) Token-based hierarchical match, e.g. "1포장 1-1" → site "1포장" +
        #     zone "1-1". 여기서도 고르지 않는다 — 한정어가 없거나 한정어로도
        #     하나로 안 좁혀지면 모호다(예전에는 첫 행을 골랐다: '1 구역' → 구역
        #     '1' 중 아무거나, '육묘장 온도' → 부지 '육묘장' 중 아무거나).
        tokens = [t for t in rest.replace(',', ' ').split() if t]
        if len(tokens) >= 2:
            token_set = set(tokens)
            site_ids = {s.id for (s, n, nl) in scope if s.type == 'site' and nl in token_set}
            zone_hits = [(s, n) for (s, n, nl) in scope
                         if s.type in cls._ZONE_LIKE_TYPES and nl in token_set]
            if zone_hits:
                # Disambiguate by parent site when a site token is present.
                if site_ids:
                    scoped = [(s, n) for (s, n) in zone_hits if s.parent_id in site_ids]
                    if not scoped:
                        # parent_id 는 운영에서 비어 있다 — 실제 부모는 공간
                        # 포함이다(`geo_hierarchy`). 그것으로 한 번 더 본다.
                        _pm, _ = cls._shape_parent_lookup()
                        scoped = [(s, n) for (s, n) in zone_hits
                                  if site_ids & set(cls._ancestor_ids(s.id, _pm))]
                    got = _settle(scoped)
                    if got:
                        return cls._narrow_leftover(got, tokens, scope)
                got = _settle(zone_hits)
                if got:
                    return cls._narrow_leftover(got, tokens, scope)
            # Only a site matched a token → attach to the site — unless the
            # other words name something INSIDE it (`_narrow_leftover`).
            got = _settle([(s, n) for (s, n, nl) in scope
                           if s.type == 'site' and nl in token_set])
            if got:
                return cls._narrow_leftover(got, tokens, scope)

        # 3) Substring fallback.
        #
        # Both directions need a floor of two characters on the SHORTER side.
        # A one-character shape name ('2' — a real zone here) is contained in
        # any sentence that happens to hold that character: '비닐하우스 2동 옆
        # 창고' resolved to zone '2' with status 'success' and the note "resolves
        # to exactly one entity", so add_schedule/create_note wrote there with
        # nothing in the response to doubt. The mirror case is as bad — a
        # one-character QUERY is contained in half the names on the map.
        #
        # Length is the guard rather than a word-boundary check because Korean
        # particles attach directly to the noun ('1포장에', '3-1에서'): requiring
        # a delimiter after the name would reject most of how people actually
        # write. That leaves a two-character name matching inside a longer word
        # ('25' in '온도 25도'); the map has no such name today, and tightening
        # further would cost more real usage than it buys.
        subs = [(s, n) for (s, n, nl) in scope
                if (len(rest) >= 2 and rest in nl) or (len(nl) >= 2 and nl in rest)]
        # Several DIFFERENT names matching is a question, not an answer.
        # '포장' hits 1포장·2포장·3포장 and taking the first wrote to 1포장
        # without ever saying it chose. One name is then grouped into places
        # like the exact pass: shapes of one name nested inside each other are
        # one place (the outer one), but the same name in two separate places
        # is ambiguous ('육묘장에' on two maps).
        if subs and len({n for (_s, n) in subs}) == 1:
            got = _settle(subs)
            if got:
                return got

        if map_scoped:
            # 지도 한정어가 있었는데 그 지도 안에서 못 찾았다. 장치·작물
            # 이름으로 넓히면 한정어를 무시한 답이 된다.
            return res

        # 4) Input / Output devices by partial name. 여럿이면 고르지 않는다 —
        #    '.first()' 로 하나를 집던 때는 'TEST 측창' 이 측창 넷 중 저장 순서로
        #    앞선 것에, 'v3' 가 여덟 중 하나에 붙었고 응답에는 고른 흔적이 없었다.
        #    Input 에서 찾으면 Output 을 안 보던 것도 같은 구멍이라 둘을 함께 모은다.
        #    (장치 조작 경로는 `device_resolver` 가 따로 해석한다 — 여기는 기록·
        #    일정·조회가 이름을 붙이는 곳이다.)
        partial = []
        for model, _tt in ((Input, 'input'), (Output, 'output')):
            try:
                partial.extend((r, _tt) for r in model.query.filter(
                    model.name.ilike(f"%{_q}%")).order_by(model.id).all())
            except Exception:
                continue
        if len(partial) == 1:
            row, _tt = partial[0]
            res['result'] = (row.unique_id, _tt, row.name, None, None)
            return res
        if partial:
            # 지도에 표시된 장치는 그 표지 도형을 곳으로 삼는다 — 후보에 어느
            # 지도·어디인지와, 되풀리는 이름(use_name)이 붙는다.
            ids = {r.unique_id for (r, _k) in partial}
            markers = [(s, n) for (s, n, nl) in shapes if s.device_id in ids]
            got = _settle(markers, partial)
            if got:
                return got

        # 5) Crop-name fallback — growers say what GROWS there, not the map name.
        by_subject = cls._resolve_target_by_subject(_q)
        if by_subject:
            res['result'] = by_subject
        return res

    @classmethod
    def _narrow_leftover(cls, res, tokens, scope):
        """장소 이름 뒤에 남은 낱말이 있으면 그 장소 **안에서** 좁힌다.

        '3포장 콩' 은 예전에 '3포장' 만 대지로 걸리고 '콩' 은 조용히 버려져, 응답
        어디에도 표시 없이 3포장 전체가 대상이 됐다 — 쓰기 도구가 이 이름을 받으면
        콩 구획이 아니라 3포장 전체에 붙는다(2026-10-08 외부 MCP 점검). 이제:

          · 남은 낱말이 그 장소 안의 구획(작물·품종·이름)이나 장치 이름에 하나로
            걸리면 그것이 답이다.
          · 여럿이면 고르지 않는다(모호 — 후보를 돌려주고 쓰기는 거절된다).
          · 아무것에도 안 걸리면 장소로 답하되 `ignored_terms` 에 적는다.
            '3포장 온도' 처럼 개체가 아닌 말이 붙는 정상 호출이 있어서 거절하지
            않는다 — 위험한 것은 그 안의 무언가를 가리키는 낱말이 버려지는 것이다.
        """
        tid, ttype = res['result'][0], res['result'][1]
        if not tid or ttype == 'ambiguous':
            return res
        names = {nl for (s, n, nl) in scope
                 if s.type == 'site' or s.type in cls._ZONE_LIKE_TYPES}
        leftover = [t for t in tokens if t not in names]
        if not leftover:
            return res
        text = ' '.join(leftover)
        stems = [text]
        stripped = cls._strip_place_suffix(text)
        if stripped and stripped not in stems:
            stems.append(stripped)

        plots, devices = [], []
        try:
            from aot.space import device_membership as dm
            from aot.databases.models import GeoPlot
            idx = dm.PlaceIndex()
            seen, inside = set(), []
            rows = {}
            subj = [p for p in cls._active_subject_plots() if p.get('plot_id')]
            if subj:
                rows = {r.unique_id: r for r in GeoPlot.query.filter(
                    GeoPlot.unique_id.in_([p['plot_id'] for p in subj])).all()}
            for p in subj:
                row = rows.get(p['plot_id'])
                if row is None or row.unique_id in seen:
                    continue
                if idx.plot_within(row, tid):
                    seen.add(row.unique_id)
                    inside.append((row, p))

            def _fields(p):
                return [str(v).strip().lower()
                        for v in (p['subject'], p['variety'], p['name'])
                        if v and str(v).strip()]

            def _match(p):
                """이 구획이 남은 낱말에 어떻게 걸리는가 → 'exact'|'word'|'fragment'|None.

                한 등급을 고르고 나머지를 버리지 않는다(2026-10-09). 예전에는
                정확일치가 하나라도 있으면 그것만 남겨 '3포장 콩' 이 이름이 '콩'
                인 구획 하나로 조용히 정해졌는데, 같은 곳에 '콩 1구'~'콩 7구'·
                '올콩'·'검정콩' 이 있었다 — 사람이 말한 '콩' 은 대개 그 전부다.
                한 글자 조각('마' → '고구마')은 후보로만 싣고 그것 하나로는
                정하지 않는다(아래)."""
                fs = _fields(p)
                best = None
                for st in stems:
                    if st in fs:
                        return 'exact'
                    if any(st in f.split() for f in fs):
                        best = 'word'
                    elif best is None and any(
                            st in f or (len(st) >= 2 and len(f) >= 2 and f in st)
                            for f in fs):
                        best = 'fragment'
                return best

            hits = []
            for (r, p) in inside:
                m = _match(p)
                if m:
                    hits.append((r, p, m))
            # 한 글자 조각만으로 걸린 것은 혼자서는 답이 되지 못한다 — 다른
            # 후보와 함께일 때만 싣는다. 혼자면 낱말을 무시한 것으로 적는다.
            weak = all(m == 'fragment' and max(len(st) for st in stems) < 2
                       for (_r, _p, m) in hits)
            if hits and weak and len(hits) == 1:
                hits = []
            order = {'exact': 0, 'word': 1, 'fragment': 2}
            hits.sort(key=lambda h: (order[h[2]], (h[1].get('name') or h[1].get('subject') or '')))
            plots = [(r, p.get('name') or p.get('subject'), m) for (r, p, m) in hits]

            members = dm.place_members(tid) or set()
            for model, kind in ((Input, 'input'), (Output, 'output')):
                for row in model.query.filter(model.unique_id.in_(list(members))).all():
                    if (row.name or '').strip().lower() in stems:
                        devices.append((row, kind))
        except Exception as e:                              # noqa: BLE001
            logger.debug("_narrow_leftover failed: %s", e)
            res['ignored_terms'] = leftover
            return res

        n = len(plots) + len(devices)
        place_name = res['result'][2]
        if n == 1:
            if plots:
                row, label, how = plots[0]
                res['result'] = (row.unique_id, 'plot', label, None, None)
                # 어떻게 좁혔는지 함께 낸다 — 정확일치가 아니면 사람이 확인할 몫이다.
                res['matched'] = {'rule': how, 'term': text, 'within': place_name}
            else:
                row, kind = devices[0]
                res['result'] = (row.unique_id, kind, row.name, None, None)
                res['matched'] = {'rule': 'exact', 'term': text, 'within': place_name}
            res['place'] = None
            return res
        if n > 1:
            res.update(result=(None, 'ambiguous', None, None, None),
                       places=[], devices=devices, plots=plots, place=None)
            return res
        res['ignored_terms'] = leftover
        return res

    @classmethod
    def _resolve_explain(cls, target_name):
        """`_resolve_core` + 번역 별칭 재시도(`_with_translated_alias` 와 같은 규칙).

        `_resolve_note_target` 과 **같은 답**을 내되 모호할 때 후보까지 준다.
        """
        d = cls._resolve_core(target_name)
        r = d['result']
        if r[0] or r[1] == 'ambiguous':
            return d
        try:
            from aot.tools import providers
            source = providers.get('reverse_lookup')(target_name)
        except Exception:
            source = None
        if source and source != target_name:
            return cls._resolve_core(source)
        return d

    @classmethod
    def _qualified_name(cls, rec, name, target_id, pmap, by_id, maps_lower, map_names):
        """그 도형 하나만 가리키는 이름 — 리졸버로 되짚어 확인된 것만. 없으면 None."""
        options = []
        mn = map_names.get(rec.geo_id)
        mn_ok = bool(mn) and len(maps_lower.get(mn.strip().lower(), [])) == 1
        if mn_ok:
            options.append('%s %s' % (mn, name))
        nl = (name or '').strip().lower()
        for a in cls._ancestor_ids(rec.id, pmap)[:3]:
            anc = by_id.get(a)
            if anc is None or not anc.name or anc.name.strip().lower() == nl:
                continue
            options.append('%s %s' % (anc.name, name))
            if mn_ok:
                options.append('%s %s %s' % (mn, anc.name, name))
        for q in options:
            try:
                if cls._resolve_note_target(q)[0] == target_id:
                    return q
            except Exception:
                continue
        return None

    @classmethod
    def _describe_places(cls, places, devices=(), plots=()):
        """곳 목록 → 후보 dict 목록.

        dict: name, type, where, target_id, use_name(검증된 것만), also_inside,
        _rep(대표 도형 또는 None), _geo.
        """
        pmap, by_id = cls._shape_parent_lookup()
        maps_lower = cls._map_names_by_lower()
        try:
            from aot.databases.models import GeoMap
            map_names = {m.unique_id: (m.name or '').strip() for m in GeoMap.query.all()}
        except Exception:
            map_names = {}
        mapped = {p['device_id'] for p in places if p.get('device_id')}

        def _type(rec, is_device):
            if rec.type in cls._PLACE_TYPES:
                return rec.type
            return 'device' if is_device else 'zone'

        out = []
        for p in places:
            rec, name = p['rep']
            chain = [by_id[a].name for a in reversed(cls._ancestor_ids(rec.id, pmap))
                     if a in by_id and by_id[a].name]
            where = ' > '.join([x for x in [map_names.get(rec.geo_id)] + chain if x])
            # 후보마다 사람이 구분할 단서가 있어야 한다 — 없으면 모델이 id 로
            # 되묻는다. 지도 이름도 상위 도형도 없으면 그 사실을 적는다.
            c = {'name': name, 'type': _type(rec, bool(p.get('device_id'))),
                 'where': where or 'top level of an unnamed map',
                 'target_id': rec.unique_id,
                 '_rep': p['rep'], '_geo': rec.geo_id}
            un = cls._qualified_name(rec, name, rec.unique_id, pmap, by_id,
                                     maps_lower, map_names)
            if un:
                c['use_name'] = un
            inner = cls._also_inside(p, pmap, by_id, maps_lower, map_names)
            if inner:
                c['also_inside'] = inner
            out.append(c)
        for row, kind in devices:
            if row.unique_id in mapped:
                continue
            tab = None
            try:
                from aot.services.resolvers.device_resolver import _tab_names
                tab = _tab_names([row])
            except Exception:
                tab = None
            c = {'name': row.name, 'type': kind,
                 'where': ('not placed on a map' + (' (tab: %s)' % tab if tab else '')),
                 'target_id': row.unique_id, '_rep': None, '_geo': None}
            # 장치 이름 그대로가 그 장치 하나로 되풀리면 그것이 use_name 이다.
            # 이름이 같은 장치가 또 있으면 싣지 않는다(target_id 로 안내된다).
            try:
                if row.name and cls._resolve_note_target(row.name)[0] == row.unique_id:
                    c['use_name'] = row.name
            except Exception:
                pass
            out.append(c)
        if plots:
            # 구획 후보(`_narrow_leftover`) — 어디에 있는지는 장소 경로로 적는다.
            try:
                from aot.space.device_membership import PlaceIndex
                idx = PlaceIndex()
            except Exception:
                idx = None
            for entry in plots:
                row, label = entry[0], entry[1]
                how = entry[2] if len(entry) > 2 else None
                path = idx.plot_path(row) if idx is not None else ''
                where = ' > '.join(x for x in [map_names.get(row.geo_id), path] if x)
                c = {'name': label, 'type': 'plot',
                     'where': where or 'not inside any place',
                     'target_id': row.unique_id, '_rep': None, '_geo': row.geo_id}
                if how:
                    # exact = 이름·작물·품종이 그 낱말 그대로 · word = 띄어 쓴 낱말
                    # 하나로 ('콩 7구') · fragment = 붙은 말의 일부로 ('검정콩').
                    c['match'] = how
                # 그 구획 하나로 되풀리는 이름만 use_name 으로 싣는다 — 이름 그대로,
                # 아니면 안쪽 장소부터 '장소 이름' 을 붙여 본다.
                tries = [label] + ['%s %s' % (seg, label)
                                   for seg in reversed(path.split(' > ')) if seg]
                for cand in tries:
                    try:
                        if cand and cls._resolve_note_target(cand)[0] == row.unique_id:
                            c['use_name'] = cand
                            break
                    except Exception:
                        continue
                out.append(c)
        return out

    @classmethod
    def _also_inside(cls, place, pmap=None, by_id=None, maps_lower=None, map_names=None):
        """곳 하나의 안쪽 같은 이름 도형 → [{type, target_id, use_name?}]."""
        inner = (place or {}).get('inner') or []
        if not inner:
            return []
        if pmap is None or by_id is None:
            pmap, by_id = cls._shape_parent_lookup()
        if maps_lower is None:
            maps_lower = cls._map_names_by_lower()
        if map_names is None:
            try:
                from aot.databases.models import GeoMap
                map_names = {m.unique_id: (m.name or '').strip() for m in GeoMap.query.all()}
            except Exception:
                map_names = {}
        out = []
        for rec, name in inner:
            e = {'type': rec.type if rec.type in cls._PLACE_TYPES else 'zone',
                 'target_id': rec.unique_id}
            un = cls._qualified_name(rec, name, rec.unique_id, pmap, by_id,
                                     maps_lower, map_names)
            if un:
                e['use_name'] = un
            out.append(e)
        return out

    @classmethod
    def _name_places(cls, target_name):
        """이름 → 서로 다른 곳 후보 [dict]. 모호하지 않으면 [].

        리졸버와 **같은 해석**이다(정확일치만이 아니라 한정어·부분일치 단계에서
        생긴 모호함도 여기서 나온다).
        """
        if not target_name or not str(target_name).strip():
            return []
        d = cls._resolve_explain(target_name)
        if d['result'][1] != 'ambiguous':
            return []
        return cls._describe_places(d['places'], d['devices'], d.get('plots', ()))

    @staticmethod
    def _public_places(places):
        return [{k: v for k, v in c.items() if not k.startswith('_')} for c in places]

    @staticmethod
    def _ambiguous_scope_reading(scope):
        """읽기 도구가 이름 여럿을 한꺼번에 훑었을 때 붙이는 안내. 아니면 None."""
        if not scope or scope.get('target_type') != 'ambiguous':
            return None
        return ("'%s' names several different places (scope.candidates), so "
                "results from ALL of them are included. Say that, and tell them "
                "apart by 'where' (never by id) — or ask the user which one "
                "they meant."
                % scope.get('requested'))

    @classmethod
    def _ambiguous_places(cls, target_name):
        """모호하면 공개용 후보 목록, 아니면 None."""
        try:
            places = cls._name_places(target_name)
        except Exception as e:
            logger.debug("_ambiguous_places failed: %s", e)
            return None
        return cls._public_places(places) if len(places) > 1 else None

    @staticmethod
    def _ambiguity_refusal(target_name, candidates):
        """쓰기 도구가 모호한 이름을 거절할 때의 공통 응답(영어, 구조화 필드)."""
        no_name = [c for c in candidates if not c.get('use_name')]
        msg = ("'%s' names %d different places/devices, so nothing was written. "
               "Ask the user which one they mean (describe each by its 'where'), "
               "then retry with that candidate's 'use_name' as target_name"
               % (target_name, len(candidates)))
        if no_name:
            msg += (" — or, for a candidate without 'use_name', pass its "
                    "'target_id' as target_id")
        return {"status": "needs_disambiguation", "error": "ambiguous_name",
                "message": msg + ".", "candidates": candidates}

    @classmethod
    def _target_by_id(cls, target_id):
        """target_id → (target_id, target_type, name) — 쓰기 대상이 될 수 있는
        것(지도 도형·구획·Input·Output)만. 없으면 None.

        이름 경로와 같은 대상 집합이다: 이름 리졸버가 돌려줄 수 있는 것만
        받는다. 모르는 id 를 그대로 받으면 어디에도 안 보이는 일정이 생긴다.
        """
        if not target_id or not str(target_id).strip():
            return None
        tid = str(target_id).strip()
        found = cls._target_by_id_lookup(tid)
        if found is not None:
            # 쓰기 시점 그룹 스코프 — 찾은 대상으로 묻는다(쓰기 호출이 묶여
            # 있을 때만; write_scope.enforce). 지도 도형이면 연결된 장치·시설.
            from aot.aot_flask.access import write_scope
            write_scope.enforce(found[0])
        return found

    @classmethod
    def _target_by_id_lookup(cls, tid):
        """`_target_by_id` 의 조회부 — 판정 없이 찾기만 한다."""
        try:
            from aot.space import shape_index
            for rec in shape_index.all_shapes():
                if rec.unique_id == tid:
                    return (tid, rec.type if rec.type in cls._PLACE_TYPES else 'zone',
                            rec.name or tid)
        except Exception:
            pass
        try:
            from aot.databases.models import GeoPlot
            pl = GeoPlot.query.filter_by(unique_id=tid).first()
            if pl is not None:
                return (tid, 'plot', pl.name or pl.subject or tid)
        except Exception:
            pass
        for model, kind in ((Input, 'input'), (Output, 'output')):
            try:
                row = model.query.filter_by(unique_id=tid).first()
            except Exception:
                row = None
            if row is not None:
                return (tid, kind, row.name or tid)
        return None

    @staticmethod
    @_with_translated_alias
    def _resolve_note_target(target_name):
        """Resolve a human location/entity name to (target_id, target_type,
        resolved_name, gps_lat, gps_lng). Returns (None, ...) when no match,
        and (None, 'ambiguous', None, None, None) when the name belongs to two
        or more different places/devices at any stage (see `_resolve_core`) —
        callers that only test the id keep refusing, and `_ambiguous_places` /
        resolve_target list the candidates.

        Notes attach to an entity via target_id == that entity's unique_id, and
        the per-entity note view filters by target_id, so an unresolved name must
        NOT silently become a floating (invisible) note.

        Zone names are HIERARCHICAL and short: a user says "1포장 1-1" meaning the
        zone named "1-1" inside the site named "1포장" (the zone row's own name is
        just "1-1"). So resolution: exact full-name match → map-name / site
        qualified match → substring fallback → Input/Output → crop name.
        """
        from aot.tools.aot_data_tool_service import AoTDataToolService
        result = AoTDataToolService._resolve_core(target_name)['result']
        # 쓰기 시점 그룹 스코프 — 이름이 **풀린 대상**으로 묻는다(쓰기 호출이
        # 묶여 있을 때만). 이름·옛 별칭·번역 별칭 어느 길로 왔든 여기를 지난다.
        if result and isinstance(result[0], str) and result[0]:
            from aot.aot_flask.access import write_scope
            write_scope.enforce(result[0])
        return result


    _CROP_PLACE_SUFFIXES = ('재배지', '하우스', '농장', '온실', '포장', '구역', '밭')

    @classmethod
    def _strip_place_suffix(cls, text):
        """'콩밭' → '콩', '상추 재배지' → '상추'. None when nothing was stripped."""
        t = str(text or '').strip()
        for suf in cls._CROP_PLACE_SUFFIXES:
            if t.endswith(suf) and len(t) > len(suf):
                return t[:-len(suf)].strip() or None
        return None

    @classmethod
    def _active_subject_plots(cls):
        """Active GeoPlot rows paired with the zone that contains them, as
        [{'subject','variety','name','plot_id','zone_id','zone_type','zone_name'}].

        **A plot IS a write target now.** It was not when this was written —
        notes and schedules only attached to GeoShapes, so a plot outside every
        zone was useless and got dropped. Since 2026-08-18 a note's selected
        span can become a schedule attached to the plot itself, so dropping
        those rows means the resolver cannot reach what the user just created.
        `zone_*` stays (a plot is still reported with the zone it sits in), but
        it is no longer required.
        """
        import json as _json
        from aot.databases.models import GeoMap
        from aot.space import plot_context, device_membership

        out = []
        try:
            maps = GeoMap.query.all()
        except Exception:
            return out

        for m in maps:
            try:
                rows = plot_context.active_plots(m.unique_id)
            except Exception:
                continue
            if not rows:
                continue
            try:
                containers = device_membership.load_containers(m.unique_id)
            except Exception:
                containers = None
            for row in rows:
                try:
                    zone = plot_context.zone_for_plot(row, containers=containers)
                except Exception:
                    zone = None
                zone_name, zone_id, _zt = '', None, None
                if zone is not None:
                    try:
                        feat = zone.feature if isinstance(zone.feature, dict) else _json.loads(zone.feature or '{}')
                        props = feat.get('properties') or {}
                        zone_name = str(props.get('name') or props.get('label') or props.get('title') or '').strip()
                    except Exception:
                        zone_name = ''
                    zone_id = zone.unique_id
                    _zt = zone.type if zone.type in ('zone', 'site', 'facility', 'facility_bay', 'equipment') else 'zone'
                out.append({
                    'subject': row.subject, 'variety': row.variety, 'name': row.name,
                    'plot_id': row.unique_id,
                    'zone_id': zone_id, 'zone_type': _zt, 'zone_name': zone_name,
                })
        return out

    @classmethod
    def _resolve_target_by_subject(cls, query):
        """Resolve '콩밭' / '장풍' to the PLOT that subject is in.

        Farm hands name a plot by what is in it, not by the map's zone name
        ('3-1'), so every zone-name pass above misses those words entirely.
        Matching runs against ACTIVE plots only — last year's subject must not
        steer this year's note.

        **It resolves to the plot, not its zone.** It used to return the
        containing zone, because a GeoPlot could not be written against.
        That stopped being true on 2026-08-18: a note's selected span becomes a
        schedule attached to the plot. Returning the zone meant the user asked
        about '장풍', the resolver answered 'zone 3-1', and the two schedules
        sitting on 장풍 itself were unreachable by any name (measured — 0 hits).

        Returns the same 5-tuple as _resolve_note_target(), or None for no match.

        One subject spread over several PLOTS resolves to None on purpose. The
        5-tuple cannot carry 'ambiguous', and this resolver feeds write tools
        (add_schedule, create_note) — picking the first would silently write to
        the wrong plot. No match lets the caller ask.
        """
        try:
            plots = cls._active_subject_plots()
        except Exception as e:
            logger.debug(f"_resolve_target_by_subject: plot lookup failed: {e}")
            return None
        if not plots:
            return None

        ql = str(query or '').strip().lower()
        if not ql:
            return None

        def _fields(p):
            return [str(v).strip().lower()
                    for v in (p['subject'], p['variety'], p['name'])
                    if v and str(v).strip()]

        def _one_zone(hits):
            """이름 하나가 구획 하나로 좁혀질 때만 답한다.

            같은 작물이 두 구획에 있으면 None — 5-tuple 에 '모호함' 을 담을
            자리가 없고, 이 리졸버는 쓰기 도구도 쓰므로 하나를 골라 버리면
            엉뚱한 구획에 조용히 쓰인다.
            """
            plot_ids = {p.get('plot_id') for p in hits if p.get('plot_id')}
            if len(plot_ids) == 1:
                p = next(h for h in hits if h.get('plot_id'))
                label = p.get('name') or p.get('subject')
                return p['plot_id'], 'plot', label, None, None
            # 구획 id 가 없는(옛 데이터) 경우에만 zone 으로 물러선다.
            zone_ids = {p['zone_id'] for p in hits if p.get('zone_id')}
            if len(zone_ids) != 1:
                return None
            p = next(h for h in hits if h.get('zone_id'))
            return p['zone_id'], p['zone_type'], p['zone_name'], None, None

        stems = [ql]
        stripped = cls._strip_place_suffix(ql)
        if stripped:
            stems.append(stripped)

        for stem in stems:
            hits = [p for p in plots if stem in _fields(p)]
            if hits:
                return _one_zone(hits)

        # Partial match, kept tight on both sides: a 1-character subject name ('마')
        # matches inside half the words in the language ('고구마'), so require two
        # characters before either string is allowed to contain the other.
        for stem in stems:
            if len(stem) < 2:
                continue
            hits = [p for p in plots if any(
                stem in f or (len(f) >= 2 and f in stem) for f in _fields(p))]
            if hits:
                return _one_zone(hits)

        return None

    @classmethod
    def _expand_place_ids(cls, shape):
        """도형 → 그 안에서 일어나는 일의 target_id 들과 내역 — 정본
        (`device_membership.place_scope_ids`)을 그대로 부른다. 화면(노트·일정
        모달)과 같은 함수여야 AI 와 화면의 답이 갈리지 않는다."""
        from aot.space.device_membership import place_scope_ids
        return place_scope_ids(shape)

    @classmethod
    def _scope_for_target(cls, target_name):
        """이름 하나를 **그 안에서 일어나는 일 전부**의 target_id 집합으로.

        "3포장의 예정을 요약해" 는 3포장 안에서 일어나는 일을 묻는 것이지 3포장
        도형에 붙은 것만 묻는 것이 아니다. 예전에는 `target_id ==` 정확 일치라
        실측(2026-08-18 김제)에서 `search_schedule('3포장')` 이 0건을 냈다 —
        실제로는 구역에 1건, 그 안 식생에 2건이 있었다.

        `scope` 를 함께 돌려주는 것이 요점이다. 결과가 0건일 때 **"정말 없다"
        와 "못 찾았다" 를 구분할 근거**가 그것뿐이기 때문이다. 이름이 아예
        해석되지 않으면 `scope['resolved']` 가 False 이고, 그때 0건은
        "없음" 이 아니라 "묻는 대상을 못 찾음" 이다.

        Returns (ids: list[str], scope: dict).
        """
        scope = {'requested': target_name, 'resolved': False,
                 'resolved_name': None, 'target_type': None,
                 'expanded': None, 'searched_ids': 0}
        if not target_name or not str(target_name).strip():
            return [], scope

        # 이름이 여러 정체성에 걸릴 수 있다(장치 = Input/Output + 마커 + 폴리곤).
        # 그 합집합은 `_resolve_note_target_ids` 가 계산하고, **그 안에서 이미**
        # `_resolve_note_target` 을 부른다 — 여기서 또 부르면 같은 해석을 두 번
        # 한다(실측 22.6ms 중복).
        try:
            ids, rname = cls._resolve_note_target_ids(target_name)
        except Exception:
            ids, rname = [], None

        # 이름이 서로 다른 곳 여럿이면 **전부** 훑고 그 사실을 scope 에 싣는다.
        # 하나만 펼치면 나머지 곳의 기록이 "없음" 으로 보인다.
        try:
            _places = cls._name_places(target_name)
        except Exception:
            _places = []
        if len(_places) > 1:
            ids = list(ids or [])
            for c in _places:
                ids.append(c['target_id'])
                rec = (c.get('_rep') or (None,))[0]
                if rec is None:
                    continue
                try:
                    shape = GeoShape.query.filter_by(unique_id=rec.unique_id).first()
                    if shape is not None:
                        more, _b = cls._expand_place_ids(shape)
                        ids.extend(more)
                except Exception as _e:
                    logger.debug(f"_scope_for_target: 자손 확장 실패: {_e}")
            seen, uniq = set(), []
            for i in ids:
                if i and i not in seen:
                    seen.add(i)
                    uniq.append(i)
            scope.update({'resolved': True, 'resolved_name': rname or target_name,
                          'target_type': 'ambiguous',
                          'candidates': cls._public_places(_places),
                          'searched_ids': len(uniq)})
            return uniq, scope

        if not ids:
            return [], scope

        tid = ids[0]
        try:
            _t, ttype, _r, _la, _ln = \
                cls._resolve_note_target(target_name)
        except Exception:
            ttype = None
        scope.update({'resolved': True, 'resolved_name': rname,
                      'target_type': ttype})
        ids = list(ids)

        # 도형이면 그 아래 전부로 넓힌다(구역·시설·장치·식생).
        try:
            shape = GeoShape.query.filter_by(unique_id=tid).first()
        except Exception:
            shape = None
        if shape is not None:
            try:
                more, breakdown = cls._expand_place_ids(shape)
                ids.extend(more)
                scope['expanded'] = breakdown
            except Exception as _e:
                logger.debug(f"_scope_for_target: 자손 확장 실패: {_e}")

        seen, uniq = set(), []
        for i in ids:
            if i and i not in seen:
                seen.add(i)
                uniq.append(i)
        scope['searched_ids'] = len(uniq)
        return uniq, scope

    @classmethod
    def _geo_shape_descendants(cls, root_shape):
        """Return every GeoShape nested under root_shape (e.g. a site's child
        zones and the device markers inside them), as GeoShape rows. See
        aot/utils/geo_hierarchy.py for why this is needed (GeoShape.parent_id
        is unset in production; the real parent signal is spatial
        containment).
        """
        # **경량 레코드**를 돌려준다(ShapeRec: id·unique_id·type·parent_id·
        # device_id·geo_id·name). 자손에서 읽는 것이 그뿐이라 ORM 전체 조회
        # (16.8ms/150행)가 통째로 빠진다 — `_resolve_note_target_ids` 의
        # site 확장 경로 22.6ms 가 거의 전부 그 조회였다.
        #
        # **기하는 없다.** 자손의 폴리곤이 필요하면 `geo_descendant_shapes`
        # 를 직접 쓸 것.
        from aot.utils.geo_hierarchy import geo_descendant_recs
        return geo_descendant_recs(root_shape)

    @classmethod
    def _resolve_note_target_ids(cls, target_name):
        """Resolve a name to ALL candidate note target_ids, not just one.

        A single physical device carries MULTIPLE identities that a note may be
        bound to, and they do NOT share a unique_id:
          - the Input/Output row's unique_id (the device panel '노트 작성하기'
            writes the note here, e.g. Output 'v111' → 3acafd0c…),
          - one or more map GeoShapes (a marker + a polygon) whose OWN unique_id
            differs, but whose device_id points back to that Input/Output.
        _resolve_note_target() returns only the single most-specific match (a
        shape), so a note written on the Output is missed. Gathering the union of
        {shape.unique_id, shape.device_id, device.unique_id} for the name finds
        the note wherever it was attached.

        Returns (candidate_ids: list[str], resolved_name: str|None).
        """
        import json as _json
        ids, resolved_name = [], None
        if not target_name or not str(target_name).strip():
            return ids, None
        _q = str(target_name).strip()
        _ql = _q.lower()

        # Primary (hierarchical/zone-aware) resolution first — keeps '1포장 1-1'
        # scoping and substring behaviour intact.
        tid, _tt, rname, _la, _ln = cls._resolve_note_target(target_name)
        if tid:
            ids.append(tid)
            resolved_name = rname

        # A 'site' (포장) is a container: its own notes are rare, but each child
        # zone (구역) carries its own notes (e.g. crop info per zone). A query
        # asked about the site must also surface every descendant zone's notes,
        # not just the site shape's own target_id — otherwise "1포장에서 생산하는
        # 작물" answers "no info" even though "1-1", "1-2" ... each have one.
        if tid and _tt == 'site':
            try:
                site_shape = GeoShape.query.filter_by(unique_id=tid).first()
            except Exception:
                site_shape = None
            if site_shape:
                # 여기서는 ORM 행이 필요하다(기하 파싱 → 자손 판정). 공용
                # 인덱스는 이름 해석용 경량 레코드라 기하를 들지 않는다.
                # A descendant 'device' marker's OWN unique_id is not what a
                # note attaches to — the device panel writes the note against
                # the underlying Input/Output's unique_id (shape.device_id),
                # a distinct identity (same dual-identity issue documented on
                # this method's docstring, above). Missing this union meant a
                # site query silently dropped every note attached to a device
                # placed under it (e.g. valve notes under '1포장').
                for _desc in cls._geo_shape_descendants(site_shape):
                    if _desc.unique_id:
                        ids.append(_desc.unique_id)
                    if _desc.device_id:
                        ids.append(str(_desc.device_id).split('::')[0])

        # GeoShapes whose display name matches EXACTLY → add the shape's own id
        # and the device it represents. 같은 공용 인덱스를 쓴다(위 주석 참조).
        try:
            from aot.space import shape_index
            for shape, _name, _nl in shape_index.named_shapes():
                if _nl == _ql:
                    if shape.unique_id:
                        ids.append(shape.unique_id)
                    if shape.device_id:
                        ids.append(str(shape.device_id).split('::')[0])
                    resolved_name = resolved_name or _name
        except Exception:
            pass

        # Input/Output/Function rows matching the name → add their unique_id.
        try:
            from aot.databases.models import Function as _Function
        except Exception:
            _Function = None
        for model in (m for m in (Input, Output, _Function) if m is not None):
            try:
                for d in model.query.filter(model.name.ilike(_q)).all():
                    if d.unique_id:
                        ids.append(d.unique_id)
                    resolved_name = resolved_name or d.name
            except Exception:
                continue

        # De-duplicate, preserve order.
        seen, out = set(), []
        for i in ids:
            if i and i not in seen:
                seen.add(i)
                out.append(i)
        return out, resolved_name

    _FORECAST_UNUSABLE_H = 24


    # ── 읽기 도구의 대상 인자 — id 또는 사람이 쓰는 이름 (3-A) ────────────────
    #
    # 조회 도구 여럿이 대상을 unique_id 로만 받아, 모델은 이름을 id 로 바꾸는
    # 호출(resolve_target·search_devices)을 먼저 해야 했다(첫 호출의 약 5분의 1).
    # 이제 같은 인자에 이름을 줘도 된다. 규칙은 쓰기 도구·resolve_target 과 같다:
    #   - id 정확일치가 먼저다(앞 도구가 낸 id 를 이름 검색으로 새게 하지 않는다).
    #   - 이름이 여럿에 걸리면 **고르지 않고** needs_disambiguation + 후보.
    #   - 후보는 사람이 가를 단서('where')와 함께 낸다(되물을 때 id 대신).
    # 읽기이므로 그룹 스코프 판정은 없다(보기는 전원 공개, _scope_refusal).

    #: 여러 대상을 한 번에 받는 인자(3-F)의 상한. 넘으면 나눠 부르라고 답한다.
    MAX_READ_TARGETS = 10

    _READ_AMBIGUOUS_READING = (
        "Several different things share this name, so nothing was picked. Ask the "
        "user which one they mean, describing each candidate by its 'where' "
        "(never by id), then call again with that candidate's 'use_name' or id. "
        "For a read you may instead answer for EACH candidate, labelled by 'where'.")

    # @manual ai/overview#tool-arguments
    @classmethod
    def _map_is_not_a_place(cls, token, arg='zone_id'):
        """token 이 지도 id 면 되묻는 오류 dict(그 지도의 대지 이름 포함), 아니면 None."""
        try:
            from aot.databases.models import GeoMap
            from aot.space.device_membership import place_label
            m = GeoMap.query.filter_by(unique_id=token).first()
            if m is None:
                return None
            sites = sorted({place_label(s) for s in GeoShape.query.filter_by(
                geo_id=token, type='site').all()} - {''})
        except Exception as e:                              # noqa: BLE001
            logger.debug("_map_is_not_a_place failed: %s", e)
            return None
        return {"error": ("'%s' is the id of the map '%s', not of a place. Pass a "
                          "site or zone (name or id) in %s." % (token, m.name or '', arg)),
                "reason": "map_id_given_for_place",
                "sites_on_this_map": sites[:30]}

    @classmethod
    def _read_place(cls, token, arg='zone_id'):
        """zone/site/facility 인자 → (GeoShape, None) 또는 (None, 오류 dict).

        id(unique_id·geo_id) 정확일치 → 이름(쓰기 도구와 같은 리졸버,
        번역 별칭·작물 이름 포함). 이름이 장치로 풀리면 곳이 아니라고 답한다.
        """
        token = str(token or '').strip()
        if not token:
            return None, {"error": "%s is required (unique_id or name)" % arg}
        row = GeoShape.query.filter(GeoShape.unique_id == token).first()
        if row is not None:
            return row, None
        # 지도 id 는 장소가 아니다. 예전에는 `geo_id == token` 으로 그 지도의
        # **아무 도형 하나**(마커일 수도 있다)를 장소로 써서, 엉뚱한 범위로
        # 조용히 답했다(2026-10-08).
        merr = cls._map_is_not_a_place(token, arg)
        if merr:
            return None, merr
        try:
            detail = cls._resolve_explain(token)
        except Exception as e:                              # noqa: BLE001
            logger.debug("_read_place resolve failed: %s", e)
            detail = {'result': (None, None, None, None, None),
                      'places': [], 'devices': []}
        tid, ttype = detail['result'][0], detail['result'][1]
        if ttype == 'ambiguous':
            return None, cls._read_ambiguity(
                token, cls._public_places(
                    cls._describe_places(detail['places'], detail['devices'], detail.get('plots', ()))))
        if tid and ttype == 'plot':
            # 작물 이름은 그 구획으로 풀린다 — 곳 인자에는 구획이 든 구역을 준다.
            try:
                from aot.databases.models import GeoPlot
                from aot.space import plot_context
                pl = GeoPlot.query.filter_by(unique_id=tid).first()
                zone = plot_context.zone_for_plot(pl) if pl is not None else None
                if zone is not None:
                    return zone, None
            except Exception as e:                          # noqa: BLE001
                logger.debug("_read_place plot→zone failed: %s", e)
        if tid and ttype not in ('input', 'output', 'plot'):
            row = GeoShape.query.filter_by(unique_id=tid).first()
            if row is not None:
                return row, None
        if tid and ttype in ('input', 'output'):
            return None, {"error": ("'%s' is a device, not a zone or site — pass a "
                                    "place here." % token),
                          "reason": "device_not_place"}
        return None, {"error": "No zone or site named '%s'." % token,
                      "available_targets": cls._geoshape_name_candidates()}

    # @manual ai/overview#tool-arguments
    @classmethod
    def _read_plot(cls, token):
        """구획 인자 → (GeoPlot, None) 또는 (None, 오류 dict).

        id → 재배 중인 구획의 이름 → 작물·품종 이름(재배 중인 것만). 지난
        작기의 이름은 id 로만 받는다 — 올해 물음이 작년 구획으로 새지 않게.
        """
        from aot.databases.models import GeoPlot
        token = str(token or '').strip()
        if not token:
            return None, {"error": "plot_id is required (unique_id or name)"}
        row = GeoPlot.query.filter_by(unique_id=token).first()
        if row is not None:
            return row, None
        try:
            plots = cls._active_subject_plots()
        except Exception as e:                              # noqa: BLE001
            logger.debug("_read_plot lookup failed: %s", e)
            plots = []
        ql = token.lower()
        # 세 칸(구획 이름·작물·품종)을 **모두** 본다. 첫 칸에서 멈추면, 작물
        # 이름과 같은 이름을 단 구획 하나가 그 작물을 기르는 다른 구획들을
        # 가려 조용히 하나를 고르게 된다(리뷰 26-09-24).
        by_id = {}
        for field, label in (('name', 'plot name'), ('subject', 'crop'),
                             ('variety', 'variety')):
            for p in plots:
                if str(p.get(field) or '').strip().lower() != ql:
                    continue
                hit = by_id.setdefault(p['plot_id'], dict(p, _matched=[]))
                if label not in hit['_matched']:
                    hit['_matched'].append(label)
        hits = list(by_id.values())
        if len(hits) == 1:
            row = GeoPlot.query.filter_by(unique_id=hits[0]['plot_id']).first()
            if row is not None:
                return row, None
        if len(hits) > 1:
            return None, cls._read_ambiguity(token, [
                {"name": p.get('name') or p.get('subject'),
                 "subject": p.get('subject'), "variety": p.get('variety'),
                 "matched_by": ", ".join(p['_matched']),
                 "where": p.get('zone_name') or 'not inside a named zone',
                 "plot_id": p['plot_id']}
                for p in hits])
        names = sorted({str(p.get('name') or p.get('subject') or '')
                        for p in plots} - {''})
        # 대지·구역·시설을 구획 자리에 넘긴 경우 — 왜 안 되는지와 갈 곳을 말한다
        # (2026-10-11 외부 AI: '1포장' id 로 get_plot 을 불러 "No growing plot"
        # 만 받고 이유를 몰랐다).
        try:
            place, _perr = cls._read_place(token)
        except Exception:                                   # noqa: BLE001
            place = None
        if place is not None:
            kind = place.type or 'place'
            return None, {
                "error": ("'%s' is a %s, not a plot — this argument takes one "
                          "growing plot. For the plots inside it call "
                          "list_plots(zone_id='%s')." % (
                              cls._shape_display_name(place) or token, kind,
                              place.unique_id)),
                "growing_plots": names[:20]}
        return None, {"error": "No growing plot named '%s'." % token,
                      "growing_plots": names[:20]}

    # @manual ai/overview#tool-arguments
    @classmethod
    def _read_device(cls, token, kinds=None, arg='device_id'):
        """장치 인자 → (row, kind, None) 또는 (None, None, 오류 dict).

        `_resolve_device_target`(get_device_detail 과 같은 해석)을 쓰고, 종류가
        맞지 않으면(출력 자리에 센서) 그렇게 말한다."""
        if isinstance(token, dict):
            # search_devices 응답을 통째로 넘기는 호출자가 있다. 결과가 하나면
            # 그것, 여럿이면 고르지 않고 후보를 돌려준다(첫 결과를 고르면 이름
            # 모호함과 같은 조용한 선택이 된다).
            res = token.get('results') or (token.get('result') or {}).get('results') or []
            ids = []
            for r in res if isinstance(res, list) else []:
                if not isinstance(r, dict):
                    continue
                rid = r.get('id') or r.get('unique_id') or r.get('device_id')
                if rid and str(rid) not in ids:
                    ids.append(str(rid))
            if len(ids) > 1:
                found = []
                for rid in ids:
                    row, kind, _e = cls._resolve_device_target(rid)
                    if row is not None and (not kinds or kind in kinds):
                        found.append((row, kind))
                if len(found) > 1:
                    listed = found[:10]
                    return None, None, cls._read_ambiguity(
                        None, [
                            {"id": r.unique_id, "name": r.name, "kind": k,
                             "where": w}
                            for (r, k), w in zip(
                                listed, cls._device_candidates_where(listed))],
                        message=("The search result given as %s holds %d "
                                 "devices — see 'candidates'."
                                 % (arg, len(found))))
                ids = [found[0][0].unique_id] if found else ids[:1]
            token = ids[0] if ids else ''
        token = str(token or '').strip()
        if not token:
            return None, None, {"error": "%s is required (unique_id or name)" % arg}
        row, kind, err = cls._resolve_device_target(token)
        if err:
            if err.get("needs_disambiguation"):
                err = dict(err)
                err["status"] = "needs_disambiguation"
                err["_reading"] = [cls._READ_AMBIGUOUS_READING]
            return None, None, err
        if kinds and kind not in kinds:
            def _a(k):
                return ('an ' if k[:1] in 'aeiou' else 'a ') + k
            return None, None, {"error": "'%s' is %s, not %s." % (
                getattr(row, 'name', None) or token, _a(kind),
                ' or '.join(_a(k) for k in kinds))}
        return row, kind, None

    # @manual ai/overview#tool-arguments
    @classmethod
    def _read_ambiguity(cls, token, candidates, message=None):
        return {"status": "needs_disambiguation", "error": "ambiguous_name",
                "query": token,
                "message": message or (
                    "'%s' names %d different things — see 'candidates'."
                    % (token, len(candidates))),
                "candidates": candidates,
                "_reading": [cls._READ_AMBIGUOUS_READING]}

    # @manual ai/overview#tool-arguments
    @classmethod
    def _targets_arg(cls, single, many, arg):
        """단수 인자와 복수 인자(목록)를 하나의 목록으로. (목록, 오류 dict|None).

        단수 자리에 목록을 줘도 받는다(모델이 흔히 그렇게 보낸다). 순서를
        지키며 겹치는 것을 뺀다. 상한을 넘으면 나눠 부르라고 답한다."""
        items = []
        for value in (single, many):
            if value is None or value == '':
                continue
            if isinstance(value, (list, tuple)):
                items.extend(value)
            else:
                items.append(value)
        tokens = []
        for v in items:
            t = v if isinstance(v, dict) else str(v).strip()
            if t and t not in tokens:
                tokens.append(t)
        if len(tokens) > cls.MAX_READ_TARGETS:
            return tokens, {"error": ("At most %d targets per call (%d given) — "
                                      "split them into several calls."
                                      % (cls.MAX_READ_TARGETS, len(tokens)))}
        if not tokens:
            return tokens, {"error": "%s is required (unique_id or name)" % arg}
        return tokens, None

    # @manual ai/overview#tool-arguments
    @classmethod
    def _for_each_target(cls, tokens, one):
        """대상마다 `one(token)` → {"count", "results": [...], "_reading"?}.

        대상 하나짜리 응답과 모양이 같게 둔다(각 항목 = 단수 호출의 응답 +
        `requested`). `_reading` 은 겹치지 않게 위로 모은다."""
        results, readings = [], []
        for t in tokens:
            r = one(t)
            if isinstance(r, dict):
                r = dict(r)
                rd = r.pop('_reading', None)
                for line in ([rd] if isinstance(rd, str) else (rd or [])):
                    if line not in readings:
                        readings.append(line)
                results.append(dict({"requested": t}, **r))
            else:
                results.append({"requested": t, "result": r})
        out = {"count": len(results), "results": results}
        if readings:
            out["_reading"] = readings
        # 응답 캡이 대상을 통째로 떨구지 않게 — 각 대상 안의 목록을 먼저
        # 대상마다 몫만큼 줄인다(tool_execution._cap_result 'share_across').
        from aot.tools.tool_execution import CAP_PRIORITY_KEY
        out[CAP_PRIORITY_KEY] = {"share_across": "results"}
        return out
