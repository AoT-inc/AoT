import logging
from aot.tools.aot_data_tool_service import _with_translated_alias
from ._shims import _FakeForm

logger = logging.getLogger(__name__)


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

    @staticmethod
    @_with_translated_alias
    def _resolve_note_target(target_name):
        """Resolve a human location/entity name to (target_id, target_type,
        resolved_name, gps_lat, gps_lng). Returns (None, ...) when no match.

        Notes attach to an entity via target_id == that entity's unique_id, and
        the per-entity note view filters by target_id, so an unresolved name must
        NOT silently become a floating (invisible) note.

        Zone names are HIERARCHICAL and short: a user says "1포장 1-1" meaning the
        zone named "1-1" inside the site named "1포장" (the zone row's own name is
        just "1-1"). So resolution: exact full-name match → token-based match that
        prefers the most specific shape (zone/feature over site) and uses a site
        token to disambiguate via parent_id → substring fallback → Input/Output.
        """
        from aot.tools.aot_data_tool_service import AoTDataToolService
        if not target_name or not str(target_name).strip():
            return None, None, None, None, None
        _q = str(target_name).strip()
        _ql = _q.lower()

        # 이름이 있는 도형: 파싱 결과를 공용 인덱스에서 받는다.
        # 예전에는 이 함수와 `_resolve_note_target_ids` 가 각자
        # `GeoShape.query.all()` 을 돌아, 이름 하나 해석에 그 조회가 세 번
        # 났다(실측 23.5ms × 3). 비용은 파싱이 아니라 JSON 컬럼이 실린 행을
        # 읽는 것이다.
        from aot.aot_flask.geo import shape_index
        shapes = shape_index.named_shapes()

        def _ret(shape, name):
            _tt = shape.type if shape.type in ('zone', 'site', 'facility', 'facility_bay', 'equipment') else 'zone'
            return shape.unique_id, _tt, name, None, None

        _ZONE_TYPES = ('zone', 'feature', 'device')

        # 1) Exact full-name match (most reliable). Prefer a more specific type.
        exact = [(s, n) for (s, n, nl) in shapes if nl == _ql]
        if exact:
            exact.sort(key=lambda sn: 0 if sn[0].type in _ZONE_TYPES else 1)
            return _ret(*exact[0])

        # 2) Token-based hierarchical match, e.g. "1포장 1-1" → site "1포장" + zone "1-1".
        tokens = [t for t in _ql.replace(',', ' ').split() if t]
        if len(tokens) >= 2:
            token_set = set(tokens)
            site_ids = {s.id for (s, n, nl) in shapes if s.type == 'site' and nl in token_set}
            zone_hits = [(s, n) for (s, n, nl) in shapes if s.type in _ZONE_TYPES and nl in token_set]
            if zone_hits:
                # Disambiguate by parent site when a site token is present.
                if site_ids:
                    scoped = [(s, n) for (s, n) in zone_hits if s.parent_id in site_ids]
                    if scoped:
                        return _ret(*scoped[0])
                return _ret(*zone_hits[0])
            # Only a site matched a token → attach to the site.
            site_hits = [(s, n) for (s, n, nl) in shapes if s.type == 'site' and nl in token_set]
            if site_hits:
                return _ret(*site_hits[0])

        # 3) Substring fallback, preferring the most specific (zone-like) shape.
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
        subs = [(s, n) for (s, n, nl) in shapes
                if (len(_ql) >= 2 and _ql in nl) or (len(nl) >= 2 and nl in _ql)]
        if subs:
            # Several DIFFERENT names matching is a question, not an answer.
            # '포장' hits 1포장·2포장·3포장 and taking the first wrote to 1포장
            # without ever saying it chose. Distinct NAMES, not rows — three
            # shapes all named '육묘장' are one answer, not an ambiguity.
            if len({n for (_s, n) in subs}) > 1:
                subs = []
        if subs:
            subs.sort(key=lambda sn: 0 if sn[0].type in _ZONE_TYPES else 1)
            return _ret(*subs[0])

        # 4) Input / Output devices by name.
        for model, _tt in ((Input, 'input'), (Output, 'output')):
            row = model.query.filter(model.name.ilike(f"%{_q}%")).first()
            if row:
                return row.unique_id, _tt, row.name, None, None

        # 5) Crop-name fallback — growers say what GROWS there, not the map name.
        by_subject = AoTDataToolService._resolve_target_by_subject(_q)
        if by_subject:
            return by_subject

        return None, None, None, None, None

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
        from aot.aot_flask.geo import plot_context, device_membership

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
            from aot.utils.geo_hierarchy import descendant_target_ids
            try:
                more, breakdown = descendant_target_ids(shape)
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
            from aot.aot_flask.geo import shape_index
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

