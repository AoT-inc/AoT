# coding=utf-8
from aot.utils.time_utils import utc_now
from aot.databases import CRUDMixin
from aot.databases import set_uuid
from aot.aot_flask.extensions import db


class GeoPlot(CRUDMixin, db.Model):
    """공간 구획 — 어떤 대상이, 어디에, 언제부터 언제까지 있는가.

    설계 정본: docs/design/geo-plot-instance.md
    (식생 고유의 판단은 geo-vegetation-plot.md, 프로그램 쪽은 program-layer.md)

    ## 식생은 대상 중 하나일 뿐이다

    같은 구조("무엇이, 어디에, 언제부터")가 가축(어느 축사에 언제 입식) ·
    시설물(어디에 언제 설치) · 도로·녹지 관리에 그대로 쓰인다. 그래서 이 표는
    작물 전용이 아니라 **대상 종류(`kind`)를 갖는 구획**이다 — `GeoProgram` 이
    이미 종류를 갖는데 붙일 대상이 식생뿐이면 절반만 넓힌 것이 된다.

    ## 왜 GeoShape 가 아닌가

    `GeoShape` 는 **전부 반영구**다(site·zone·facility·facility_bay·equipment·
    마커). 만료라는 개념이 아예 없고, `type` 은 I7 로 불변이며, 무결성 검사는
    "고아 = 문제" 를 전제한다. 여기에 3개월 뒤 죽는 종류를 하나 섞으면
    `GeoShape` 를 읽는 **모든 경로**가 "만료된 건 빼라"를 각자 기억해야 한다
    (get_overlays·site_summary·check_geo_integrity·지도 위젯·시설 위젯·AI 도구).
    한 곳이 빠지면 지도가 몇 년치 옛 두둑으로 뒤덮이고 검사는 만료 도형을
    고아로 신고한다 — 이 도메인이 이미 크게 데인 "읽는 경로마다 기준이 다름"의
    성립 조건 그대로다.

    ## 작기 하나 = 행 하나 = 기하 + 작물 + 기간

    노지 두둑은 갈아엎으면 위치가 바뀐다. 그래서 "반영구 구획 + 시간축 속성"
    으로 나누면 노지에서 전제가 깨진다. 기하가 작기에 종속되므로 한 행이
    셋을 함께 들고, 정본이 하나가 된다.

    ## 수명은 구조가 아니라 데이터다

    엽채류 30일, 과채류 3~9개월, 인삼 4~6년, 과수 10~30년. `ended_on` 이
    NULL 인 행 하나가 과수 30년을 담고, 45일짜리 행이 한 해에 여러 개 생긴다.
    구조는 같다 — 짧은 것을 전제로 설계하면 과수원이, 긴 것을 전제로 하면
    노지 이랑이 들어오지 못한다.

    ## 소속도 센서도 저장하지 않는다

    zone 소속 컬럼이 없다. `device_membership` 이 확립한 원칙(소속은 유도
    가능한 값이므로 물질화하지 않는다)을 그대로 따른다 — 저장하면 복제가 남의
    링크를 복사하고 zone 재생성이 참조를 끊는다(2026-08-03 `map_overlay_id`
    사고). 센서도 마찬가지로 매달지 않고 공간 포함으로 파생한다
    (`plot_context.sensors_for_plot`).

    **시설 구획은 여기서 갈린다** — 기하를 그리지 않으면 소속을 파생할 근거가
    없으므로 부모(`facility_uuid`/`bay_id`)가 위치의 정본이 된다. 아래 그
    컬럼 주석에 왜 이것이 위 원칙의 예외가 아닌지 적어 두었다.

    ## 겹침은 정상이다

    간작·혼작(고랑 사이 다른 작물, 과수 아래 하부 작물)이 실제로 흔하다.
    **동시 유효한 구획끼리 기하가 겹쳐도 막지 않는다** — 유니크 인덱스나
    겹침 검증을 추가하지 말 것(VP-3). 그 대가로 면적 비율의 합이 100%를 넘을
    수 있고, zone 의 미배정 면적은 반드시 **합집합**으로 계산해야 한다
    (단순 합으로 빼면 겹친 만큼 이중으로 빠져 음수가 된다).

    @phase active
    @stability experimental
    @dependency GeoMap, GeoShape(zone, 파생 참조), GeoFacility(부모 참조)
    """
    __tablename__ = "geo_plot"
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, unique=True, primary_key=True)
    unique_id = db.Column(db.String(36), nullable=False, unique=True,
                          default=set_uuid)

    # ── 공간 ──────────────────────────────────────────────────────────
    # GeoMap.unique_id. GeoShape.geo_id 와 같은 규약(문자열 uuid 참조).
    geo_id = db.Column(db.String(64), nullable=False, index=True)

    # GeoJSON Feature — geometry 는 Polygon | MultiPolygon 만(VP-1).
    # properties 에 device_id/channel_id/색 사본을 넣지 않는다(VP-4):
    # 사본은 원본이 바뀌어도 따라오지 않아 조용히 갈린다(GB-5 와 같은 결).
    # zone 소속은 여기에도, 컬럼에도 두지 않는다 — 공간 포함으로 파생한다.
    #
    # **NULL 일 수 있다**(p6_39). 시설 구획은 기하 없이 성립한다 — 위치의
    # 정본이 아래 `facility_uuid`/`bay_id` 이기 때문이다. 대신 VP-7 이 선다:
    # `feature` 와 `facility_uuid` 중 적어도 하나는 있어야 한다.
    feature = db.Column(db.JSON, nullable=True)

    # ── 시설 부모 (기하 대신 위치를 정하는 축) ─────────────────────────
    #
    # ## VP-5("소속을 컬럼으로 저장하지 않는다")와 충돌하지 않는다
    #
    # VP-5 의 근거는 "**파생 가능하니까** 물질화하지 않는다" 였다(저장하면
    # 복제가 남의 링크를 복사하고 zone 재생성이 참조를 끊는다). 노지 두둑은
    # 갈아엎으면 위치가 바뀌므로 기하가 정본이고 소속은 공간 포함으로 나온다.
    #
    # 시설은 반대다. 동·구역이 구조물로 존재하고 사람도 기하가 아니라
    # **"3동"** 이라고 부른다. 기하를 그리지 않으면 소속을 파생할 근거 자체가
    # 없으므로 VP-5 의 전제가 성립하지 않는다 — 예외가 아니라 조건이 다른
    # 경우다. 그래서 여기서는 **부모가 정본이고 기하가 파생**이다(노지와 정확히
    # 반대). 파생한 기하를 이 컬럼들에 되써 넣지 말 것(sync-back 금지와 같은 결).
    #
    # ## 왜 `source_ref` 파싱으로 대신하지 않는가
    #
    # `source_ref='<facility_uuid>:<bay_id>'` 를 소속의 정본으로 승격시키면
    # `unique_id = 'uuid::채널'` 과 같은 문자열 파싱 계약이 하나 더 생긴다.
    # `source_*` 는 원래 뜻인 **출처 기록**으로 둔다 — 백필로 만들어진 구획이
    # 어디서 왔는지는 소속과 다른 질문이다.
    facility_uuid = db.Column(db.String(36), nullable=True, index=True)
    # 시설 구역 id — `facility_bays.compute_bay_slices()` 가 만드는 값과 같은
    # 어휘다('bay_3' | 'bay_3_5'). 단동(bay_count=1)은 저장 시 'bay_1' 로
    # 자동으로 채운다 — 구역이 하나뿐이라 사람이 고를 것이 없고, NULL 로 두면
    # "시설 전체"와 "구역 1"이 같은 대상을 두 가지로 표현하게 된다.
    # NULL 은 다동 시설에서만 의미를 갖는다(= 시설 전체).
    bay_id = db.Column(db.String(40), nullable=True)

    # ── 대상 ──────────────────────────────────────────────────────────
    #
    # 대상 종류 — `GeoProgram.kind` 와 **같은 어휘**를 쓴다
    # ('vegetation' | 'livestock' | 'facility' | 'other').
    #
    # **프로그램에서 파생하지 않고 저장한다.** 프로그램이 NULL 인 구획이 정상
    # 이므로(프로그램은 "있으면 자동" 이지 필수가 아니다) 파생하면 프로그램
    # 없는 구획의 종류를 알 수 없다. 대신 프로그램을 붙일 때 종류가 다르면
    # 거부한다 — 식생 구획에 가축 프로그램이 붙으면 단계·목표 해석이 통째로
    # 엉뚱해지는데 에러는 나지 않는다.
    kind = db.Column(db.String(24), nullable=False, default='vegetation',
                     index=True)
    # 이 구획에 있는 것. 작물명일 수도, 가축·수종·시설물 이름일 수도 있다.
    #
    # ⚠ `crop` 이 아니다(p6_44). `GeoProgram.subject` 와 **같은 축**이고 둘을
    # 문자열로 맞추므로 이름도 같아야 한다 — 한쪽만 좁은 이름이면 붙이는 자리
    # 마다 "이 crop 이 저 subject 인가" 를 다시 확인하게 된다.
    subject = db.Column(db.String(64), nullable=False)
    variety = db.Column(db.String(64), nullable=True)

    # ── 시간 ──────────────────────────────────────────────────────────
    # Date 이고 DateTime 이 아니다. 이 축의 단위는 날이라 시작 시각의 시분초는
    # 의미가 없고 tz 변환 문제만 부른다 — "오늘 시작했다"는 지도의 tz 가
    # 무엇이든 같은 날짜여야 한다(timezone-management.md 의 tz 상속 체인을
    # 탈 이유가 없다).
    #
    # ⚠ `started_on` 이 아니다(p6_44) — "심다" 는 식생에만 있다. 가축 입식·
    # 시설물 설치도 같은 칸을 쓴다.
    started_on = db.Column(db.Date, nullable=False)
    # index=True 는 마이그레이션(p6_44)의 ix_geo_plot_ended_on 과 짝이다.
    # 새 설치는 create_all(모델 기준), 업그레이드는 alembic 을 타므로 둘이
    # 어긋나면 **서버마다 인덱스가 달라진다.** 에러는 나지 않고 조회만 느려져
    # 아무도 모른 채 굴러간다 — 실제로 이 컬럼에서 한 번 어긋나 있었다.
    ended_on = db.Column(db.Date, nullable=True, index=True)   # NULL = 진행 중
    expected_end_on = db.Column(db.Date, nullable=True)   # 계획·알림용
    # 'harvested' | 'failed' | 'replaced' | 'removed'
    ended_reason = db.Column(db.String(16), nullable=True)

    # ── 출처 ──────────────────────────────────────────────────────────
    # 'drawn' | 'bay_snapshot' | 'copied'
    source_kind = db.Column(db.String(16), nullable=False, default='drawn')
    # bay_snapshot → GeoFacility.unique_id + ':' + bay_id
    # copied       → 원본 GeoPlot.unique_id
    #
    # bay 는 **참조가 아니라 스냅샷**이다. 나중에 bay_count 를 바꾸면 bay 기하가
    # 재계산되는데, 과거 작기가 그것을 따라가면 "작년에 여기 뭐가 있었나"의
    # 답이 조용히 달라진다. 그래서 기하는 복사하고 출처만 남긴다.
    source_ref = db.Column(db.String(80), nullable=True)

    # ── 배치 컬럼은 두지 않는다 (26.08.5 에 있었으나 p6_36 에서 제거) ──────
    #
    # `bed_width_cm` / `path_width_cm` 을 잠깐 두었다가 걷어냈다. 두 가지가
    # 틀렸다.
    #
    # 1. **모호한 사람의 말이 정수 칸에 들어가지 않는다.** 농부는 두둑과 고랑을
    #    따로 세지 않아서, "두둑 폭" 을 물으면 고랑을 뺀 윗면으로 답하는 사람과
    #    고랑까지 포함한 한 세트로 답하는 사람이 갈린다. 같은 밭이 120+40 으로도
    #    160+0 으로도 기록되고, 에러 없이 두둑 수만 달라진다. 컬럼은 "어느 쪽
    #    의미로 적었는지" 를 담지 못한다.
    # 2. **대화에서 나오는 결론마다 컬럼을 늘릴 수는 없다.** 두둑 배치는 시작일
    #    뿐이고 멀칭·지주·관수 관행이 뒤따른다. 그것을 전부 정량화해 스키마에
    #    담는 것이 어렵기 때문에 노트가 존재한다.
    #
    # 확정된 배치는 **구획 노트**로 남긴다(`create_note(target_type='plot')`).
    # 엔티티별 노트 다이제스트가 AI 컨텍스트에 미리 실리므로 다음 대화가 그
    # 문장을 읽고, 숫자는 조회 파라미터(`bed_pitch_cm`/`rows_per_bed`)로 넘긴다.
    # 계산은 여전히 서버가 한다(`plot_context.capacity_estimate`).
    #
    # ⚠ 여기에 배치 컬럼을 되살리지 말 것. 되살린다면 위 두 가지가 왜 더는
    #   문제가 아닌지 먼저 적을 것.

    # ── 재배 프로그램 (p6_40) ─────────────────────────────────────────
    #
    # 작물의 단계·목표·자원을 담은 템플릿(`GeoProgram`)을 가리킨다. 이것이
    # 있으면 사람이 적는 것은 **작물·품종·파종일·프로그램 넷뿐**이고, 현재 단계·
    # 목표 환경·예상 수확일·자원 일정은 전부 여기서 파생한다.
    #
    # **버전을 함께 고정한다.** 프로그램을 고쳐도 진행 중인 작기의 해석이 바뀌면
    # "그때 무엇을 목표로 길렀나" 의 답이 조용히 달라진다 — bay 기하를 참조가
    # 아니라 스냅샷으로 복사한 것과 같은 판단이다.
    #
    # NULL 이면 프로그램 없이 동작한다(종전과 동일). 프로그램은 "있으면 자동"
    # 이지 필수가 아니다.
    program_uuid = db.Column(db.String(36), nullable=True, index=True)
    program_version = db.Column(db.Integer, nullable=True)

    # ── 단계 일정 (P8, 2026-08-24) ────────────────────────────────────
    #
    # 단계 전환을 사람 확인 없이 기록한다.
    #
    # **프로그램이 아니라 여기 있다**(p6_56 에서 이전). 자동 승인이 묻는 것은
    # "이 작물의 단계 모델이 정확한가" 가 아니라 "이 자리를 사람 눈 없이 믿을 수
    # 있는가" 이고, 그것은 작물이 아니라 구획의 성질이다 — 같은 프로그램을 쓰는
    # 두 구획이 서로 다른 답을 갖는 것이 정상이다. 프로그램에 두면 그 둘을 나누려고
    # 작물 지식을 한 벌 더 복제하게 된다.
    #
    # 기본은 꺼짐이다. 켜져 있는 것이 기본이면 사람이 아무 결정도 하지 않았는데
    # 단계가 스스로 넘어간다.
    auto_advance = db.Column(db.Boolean, nullable=False, default=False)

    # 사람이 정한 **단계 경계** — `{단계키: {started_on, set_by, set_at}}`.
    #
    # 프로그램의 단계 길이는 표준이고 현실은 표준대로 가지 않는다. 정식이 비로
    # 닷새 밀리면 그 사실을 적을 자리가 여기다(docs/design/program-layer.md §P8).
    #
    # ## 원장(`geo_plot_stage_event`)에 넣지 않는다
    #
    # 원장은 추가 전용이고 계획은 자주 고쳐진다 — 축을 드래그할 때마다 줄이 쌓이면
    # "무슨 일이 있었나" 를 보는 화면이 일정 수정으로 도배된다. 계획은 사건이 아니라
    # **상태**다.
    #
    # ## 절대 날짜로 담는다
    #
    # 화면은 "+7일" 로 말하지만 저장은 날짜다. 상대값을 저장하면 앞 단계가 밀릴 때
    # 그 7일이 어느 날이었는지 조용히 달라진다(색 각인 금지와 같은 결).
    #
    # ## 단계 길이는 담지 않는다
    #
    # 경계 날짜 하나만 담는다. 길이와 날짜를 둘 다 저장할 수 있으면 어긋났을 때
    # 무엇이 맞는지 답할 수 없다 — 명시한 경계는 고정되고 나머지는 프로그램 길이로
    # 이어 붙는다(`plot_context.stage_schedule`).
    stage_plan = db.Column(db.JSON, nullable=True)

    # ── 표시 ──────────────────────────────────────────────────────────
    name = db.Column(db.String(120), nullable=True)
    # 사용자가 구분용으로 고른 색. 미설정이면 테마의 vegetation 으로
    # 수렴한다(aot-geo-theme-colors.js DEFAULTS 한 벌).
    #
    # color-system.md 의 "색 각인 금지"와 충돌하지 않는다 — 그 규칙이 막는 것은
    # 렌더할 때마다 계산된 테마색을 도형에 되써 넣는 sync-back 이고, 이 값은
    # 사람이 의도적으로 고른 데이터다. GeoShape.feature 에는 들어가지 않는다.
    color = db.Column(db.String(16), nullable=True)

    # ── 구역 안에서의 몫 (p6_50) ──────────────────────────────────────
    #
    # 시설 구획은 기하가 없어 같은 구역의 두 구획이 **똑같이 "그 구역 전체"** 를
    # 가리킨다. 얼마씩인지 적는 자리가 여기다.
    #
    #     {"amount": 4}     구역 총량(`GeoFacility.bays[].capacity.total`) 대비 몫
    #     {"percent": 33}   총량이 아직 없는 시설에서의 폴백
    #
    # **비율은 저장하지 않는다** — `amount/total` 에서 파생한다. 저장하면 총량이
    # 바뀔 때 둘이 조용히 갈린다(정본을 둘로 만들지 않는다는 이 도메인의 원칙).
    # `percent` 는 그 파생이 불가능할 때만 쓰는 별개 축이고, 총량을 적는 순간
    # `amount` 로 옮겨 적는 것은 사람의 일이다 — 서버가 어림해 채우지 않는다.
    #
    # **합이 총량을 넘는 것은 정상이다**(간작·혼작, VP-3). 막지 않고 화면이
    # 알린다 — 노지 구획의 면적 겹침에 유니크 인덱스를 걸지 않은 것과 같은 판단.
    #
    # 노지 구획(자기 기하가 있는 구획)에는 쓰지 않는다. 거기서는 면적이 기하에서
    # 나오므로 몫을 따로 적으면 정본이 둘이 된다.
    allocation = db.Column(db.JSON, nullable=True)

    # 이 구획만의 **단계 구성** — `{removed: [키], added: [{...}], guidance: {키: 글}}`.
    #
    # 프로그램의 단계 목록은 표준이고, 현장에서는 한 단계를 건너뛰거나(육묘 없이
    # 바로 정식) 한 단계를 더 넣는 일(추비)이 흔하다. 그리고 그 시기에 무엇을
    # 할지는 프로그램이 비워 둔 채로 오는 경우가 대부분이라, 사람이 그 자리에서
    # 적을 수 있어야 한다.
    #
    # ## 복제가 아니라 **차이**다
    #
    # 단계 목록을 통째로 복사하지 않는다. 복사하면 프로그램을 고쳐도 구획이
    # 따라오지 않고, 버전 고정이 의미를 잃는다(§P8 의 판단 그대로). 여기 담기는
    # 것은 표준과 달라진 부분뿐이고, 나머지는 여전히 프로그램에서 읽는다.
    #
    # ## `stage_plan` 과 나누어 둔다
    #
    # 경계 날짜는 확정된 전환보다 앞선 것이 지워진다(`_drop_plan_upto`) — 이미
    # 답이 나온 질문이라서다. 지침과 구성은 그 규칙을 타면 **안 된다**: 지나간
    # 단계에 적어 둔 관찰이 전환 한 번에 사라지면 기록으로서 값이 없다.
    stage_overrides = db.Column(db.JSON, nullable=True)

    created_at = db.Column(db.DateTime, default=utc_now)
    updated_at = db.Column(db.DateTime, default=utc_now, onupdate=utc_now)

    def stage_plan_map(self):
        """계획 경계 → `{단계키: date}`. 깨진 값은 조용히 버린다.

        JSON 이 손상돼도 화면과 제어를 막지 않는다 — 그 구획은 프로그램 기본
        일정으로 되돌아갈 뿐이다(`stage_list()` 가 같은 태도를 취한다).
        """
        from datetime import date as _date

        plan = self.stage_plan
        if not isinstance(plan, dict):
            return {}
        out = {}
        for key, entry in plan.items():
            raw = entry.get('started_on') if isinstance(entry, dict) else None
            if not raw:
                continue
            try:
                y, m, d = (int(x) for x in str(raw).split('-')[:3])
                out[str(key)] = _date(y, m, d)
            except (TypeError, ValueError):
                continue
        return out

    def stage_override_map(self):
        """단계 구성 → `{removed: set, added: [dict], guidance: {키: 글}}`.

        깨진 값은 조용히 버린다 — 그 구획은 프로그램 그대로 동작할 뿐이다
        (`stage_plan_map` 과 같은 태도).
        """
        raw = self.stage_overrides
        if not isinstance(raw, dict):
            raw = {}
        removed = raw.get('removed')
        added = raw.get('added')
        guidance = raw.get('guidance')
        return {
            'removed': {str(k) for k in removed} if isinstance(removed, list) else set(),
            'added': [a for a in added if isinstance(a, dict) and a.get('key')]
                     if isinstance(added, list) else [],
            'guidance': {str(k): v for k, v in guidance.items() if v}
                        if isinstance(guidance, dict) else {},
        }

    def has_own_geometry(self):
        """자기 기하를 가진 구획인가(= 노지식 정본).

        False 면 위치의 정본은 `facility_uuid`/`bay_id` 이고, 기하는 시설에서
        파생한다(`plot_context.geometry_of`). 면적·치수·식재량은 이 경우
        **내지 않는다** — 시설은 노지형·베드형·수직형에 따라 같은 바닥 면적이
        전혀 다른 재배 규모라, 면적에 재식거리를 곱하는 노지식 추정이 형태에
        따라 몇 배씩 틀린 숫자를 낸다(틀렸다는 표시 없이).
        """
        feat = self.feature
        if not isinstance(feat, dict):
            return False
        geom = feat.get('geometry')
        return isinstance(geom, dict) and bool(geom.get('coordinates'))

    def is_active(self, on=None):
        """`on`(date, 기본 오늘) 시점에 재배 중인가.

        지도 기본 렌더의 판정과 같아야 한다 — 여기와 `active_plots` 의
        쿼리가 갈리면 목록에는 있는데 지도에 없는(또는 그 반대) 구획이 생긴다.

        `ended_on` 은 **"종료된 날"** 이지 마지막 재배일이 아니다. 그래서 그날
        부터 이미 활성이 아니다(`> on`). `>= on` 으로 두면 "재배 종료"를 누른
        사람이 화면에서는 사라진 구획을 새로고침하면 다시 보게 된다 — 하루
        동안만 어긋나는 종류라 버그로 신고되기도 어렵다.

        이력 조회(`plots_overlapping`)는 이 판정과 무관하게 전 기간을
        보므로, 종료 당일의 기록이 사라지지는 않는다.
        """
        if on is None:
            from datetime import date
            on = date.today()
        if self.started_on and self.started_on > on:
            return False        # 아직 안 심음 (계획 상태)
        return self.ended_on is None or self.ended_on > on

    def __repr__(self):
        return "<{cls}(id={s.id}, kind={s.kind!r}, subject={s.subject!r})>".format(
            s=self, cls=self.__class__.__name__)
