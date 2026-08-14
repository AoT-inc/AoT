# coding=utf-8
from aot.utils.time_utils import utc_now
from aot.databases import CRUDMixin
from aot.databases import set_uuid
from aot.aot_flask.extensions import db


class GeoPlanting(CRUDMixin, db.Model):
    """식생 구획(작기) — 짧게 살고 기하까지 함께 죽는 공간 단위.

    설계 정본: docs/design/geo-vegetation-planting.md

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
    (`planting_context.sensors_for_planting`).

    ## 겹침은 정상이다

    간작·혼작(고랑 사이 다른 작물, 과수 아래 하부 작물)이 실제로 흔하다.
    **동시 유효한 구획끼리 기하가 겹쳐도 막지 않는다** — 유니크 인덱스나
    겹침 검증을 추가하지 말 것(VP-3). 그 대가로 면적 비율의 합이 100%를 넘을
    수 있고, zone 의 미배정 면적은 반드시 **합집합**으로 계산해야 한다
    (단순 합으로 빼면 겹친 만큼 이중으로 빠져 음수가 된다).

    @phase active
    @stability experimental
    @dependency GeoMap, GeoShape(zone, 파생 참조), GeoFacility(bay 스냅샷)
    """
    __tablename__ = "geo_planting"
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
    feature = db.Column(db.JSON, nullable=False)

    # ── 작물 ──────────────────────────────────────────────────────────
    crop = db.Column(db.String(64), nullable=False)
    variety = db.Column(db.String(64), nullable=True)

    # ── 시간 ──────────────────────────────────────────────────────────
    # Date 이고 DateTime 이 아니다. 농사의 단위는 날이라 파종 시각의 시분초는
    # 의미가 없고 tz 변환 문제만 부른다 — "오늘 심었다"는 지도의 tz 가
    # 무엇이든 같은 날짜여야 한다(timezone-management.md 의 tz 상속 체인을
    # 탈 이유가 없다).
    planted_on = db.Column(db.Date, nullable=False)
    # index=True 는 마이그레이션(p6_34)의 ix_geo_planting_ended_on 과 짝이다.
    # 새 설치는 create_all(모델 기준), 업그레이드는 alembic 을 타므로 둘이
    # 어긋나면 **서버마다 인덱스가 달라진다.** 에러는 나지 않고 조회만 느려져
    # 아무도 모른 채 굴러간다 — 실제로 이 컬럼에서 한 번 어긋나 있었다.
    ended_on = db.Column(db.Date, nullable=True, index=True)   # NULL = 재배 중
    expected_end_on = db.Column(db.Date, nullable=True)   # 계획·알림용
    # 'harvested' | 'failed' | 'replaced' | 'removed'
    ended_reason = db.Column(db.String(16), nullable=True)

    # ── 출처 ──────────────────────────────────────────────────────────
    # 'drawn' | 'bay_snapshot' | 'copied'
    source_kind = db.Column(db.String(16), nullable=False, default='drawn')
    # bay_snapshot → GeoFacility.unique_id + ':' + bay_id
    # copied       → 원본 GeoPlanting.unique_id
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
    # 확정된 배치는 **구획 노트**로 남긴다(`create_note(target_type='planting')`).
    # 엔티티별 노트 다이제스트가 AI 컨텍스트에 미리 실리므로 다음 대화가 그
    # 문장을 읽고, 숫자는 조회 파라미터(`bed_pitch_cm`/`rows_per_bed`)로 넘긴다.
    # 계산은 여전히 서버가 한다(`planting_context.capacity_estimate`).
    #
    # ⚠ 여기에 배치 컬럼을 되살리지 말 것. 되살린다면 위 두 가지가 왜 더는
    #   문제가 아닌지 먼저 적을 것.

    # ── 표시 ──────────────────────────────────────────────────────────
    name = db.Column(db.String(120), nullable=True)
    # 사용자가 작물 구분용으로 고른 색. 미설정이면 테마의 vegetation 으로
    # 수렴한다(aot-geo-theme-colors.js DEFAULTS 한 벌).
    #
    # color-system.md 의 "색 각인 금지"와 충돌하지 않는다 — 그 규칙이 막는 것은
    # 렌더할 때마다 계산된 테마색을 도형에 되써 넣는 sync-back 이고, 이 값은
    # 사람이 의도적으로 고른 데이터다. GeoShape.feature 에는 들어가지 않는다.
    color = db.Column(db.String(16), nullable=True)

    created_at = db.Column(db.DateTime, default=utc_now)
    updated_at = db.Column(db.DateTime, default=utc_now, onupdate=utc_now)

    def is_active(self, on=None):
        """`on`(date, 기본 오늘) 시점에 재배 중인가.

        지도 기본 렌더의 판정과 같아야 한다 — 여기와 `active_plantings` 의
        쿼리가 갈리면 목록에는 있는데 지도에 없는(또는 그 반대) 구획이 생긴다.

        `ended_on` 은 **"종료된 날"** 이지 마지막 재배일이 아니다. 그래서 그날
        부터 이미 활성이 아니다(`> on`). `>= on` 으로 두면 "재배 종료"를 누른
        사람이 화면에서는 사라진 구획을 새로고침하면 다시 보게 된다 — 하루
        동안만 어긋나는 종류라 버그로 신고되기도 어렵다.

        이력 조회(`plantings_overlapping`)는 이 판정과 무관하게 전 기간을
        보므로, 종료 당일의 기록이 사라지지는 않는다.
        """
        if on is None:
            from datetime import date
            on = date.today()
        if self.planted_on and self.planted_on > on:
            return False        # 아직 안 심음 (계획 상태)
        return self.ended_on is None or self.ended_on > on

    def __repr__(self):
        return "<{cls}(id={s.id}, crop={s.crop!r})>".format(
            s=self, cls=self.__class__.__name__)
