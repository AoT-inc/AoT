# coding=utf-8
from aot.utils.time_utils import utc_now
from aot.databases import CRUDMixin
from aot.databases import set_uuid
from aot.aot_flask.extensions import db


class GeoProgram(CRUDMixin, db.Model):
    """관리 프로그램 — 대상의 단계별 기간·목표·자원을 담는 **템플릿**.

    설계 정본: docs/design/program-layer.md

    ## 식생은 대상 중 하나일 뿐이다

    같은 구조("무엇을, 어떤 단계로, 어떤 목표로")가 식생·가축·시설물·도로에 그대로
    쓰인다. 그래서 이 표는 작물 전용이 아니라 **대상 종류(`kind`)를 갖는 관리
    프로그램**이다 — 이름을 좁게 두면 그 용도에서 같은 구조를 한 벌 더 만들게 된다.

    ## 왜 필요한가

    "이 작물은 몇 단계로 며칠씩 자라고, 그때 목표 환경은 얼마인가" 는 한때 **네 곳에
    흩어져 있고 서로 만나지 않았다**: `STAGE_DURATION_MAP`(AI 전용 하드코딩) ·
    스마트팜코리아 setpoint 캐시(AI 전용) · `FunctionCropPreset`(제어 전용, 단계 개념
    없음) · Method 곡선(사람이 손으로 그림). AI 는 "지금 개화기, 최적 22~26℃" 를
    아는데 그 값이 제어로 흐르지 않고, 제어는 같은 목표를 사람이 다시 그렸다.

    **지금은 이 표가 정본이다** — 제어가 매 사이클 여기를 읽고(코디네이터에는
    목표도 작물도 없다), AI 도 같은 값을 본다. 위 네 곳 중 남은 것은 템플릿을
    만들 때의 재료뿐이다(`docs/design/coordinator-plot-targets.md`).

    이 테이블은 그 흩어진 지식을 **한 층**으로 모아 식생 구획이 참조하게 한다.

    ## 템플릿이고, 구획이 인스턴스다

    `GeoPlot` 이 `program_uuid` + `program_version` 으로 참조한다. **버전을 함께
    고정하는 것이 핵심이다** — 프로그램을 고쳐도 진행 중인 작기의 해석이 바뀌면
    "그때 무엇을 목표로 길렀나" 의 답이 조용히 달라진다(bay 기하를 참조가 아니라
    스냅샷으로 복사한 것과 같은 판단).

    ## 출처가 신뢰를 정한다

    `source` 가 `ai` 인 프로그램은 사람이 확인(`reviewed_at`)하기 전에는 제어에
    쓰이지 않는다. 단계 기간과 목표 온도는 그럴듯하게 지어낼 수 있는 값이고, 그것이
    곧바로 온실 설정이 되면 되돌릴 근거가 없다.

    ## 품종·품목은 상속이 아니라 복제다

    품종본은 `derived_from` 에 원본 uuid 를 적은 **별도 행**이다. 부모를 실시간
    참조하면 기본을 고쳤을 때 자식이 조용히 바뀐다 — `derived_from` 은 링크가 아니라
    출처 기록이다(`source_ref` 와 같은 성격).

    @phase active
    @stability experimental
    @dependency GeoPlot(식생 종류 참조)
    """
    __tablename__ = "geo_program"
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, unique=True, primary_key=True)
    unique_id = db.Column(db.String(36), nullable=False, unique=True,
                          default=set_uuid)

    name = db.Column(db.String(128), nullable=False)

    # 대상 종류 — 'vegetation' | 'livestock' | 'facility' | 'other'.
    #
    # **좁게 시작한다**(어휘는 한 번 퍼지면 되돌리기 어렵다). `other` 가 있으므로
    # 새 종류가 필요할 때 코드를 고치지 않고도 담을 수 있고, 정말 자주 쓰이면
    # 그때 이름을 준다.
    #
    # 소비처가 자기 종류만 고르게 한다 — 식생 구획은 `vegetation` 만 본다.
    kind = db.Column(db.String(24), nullable=False, default='vegetation',
                     index=True)
    # 이 프로그램이 다루는 **대상**. 작물명일 수도, 수종·잔디 종류일 수도, 그 밖의
    # 관리 대상일 수도 있다.
    #
    # ⚠ `crop` 이 아니다(p6_42). AoT 는 용도를 농업으로 한정하지 않는다 — 공원의
    # 잔디, 가로수, 체육시설 녹지에는 "작물" 이 그냥 틀린 말이다. 어휘가 좁으면
    # 그 용도에서 화면 전체가 어색해진다.
    #
    # 공간 구획(`GeoPlot.subject`)과는 문자열로 맞춘다 — 그쪽은 "심은 것" 을
    # 사람이 자유롭게 적는 칸이라 코드 목록이 없다.
    subject = db.Column(db.String(64), nullable=False, index=True)
    # NULL = 그 대상의 기본. 값이 있으면 품종·품목 전용(고를 때 이쪽이 이긴다).
    variety = db.Column(db.String(64), nullable=True)

    # 'builtin' | 'external' | 'user' | 'ai'
    source = db.Column(db.String(16), nullable=False, default='user')
    source_ref = db.Column(db.String(120), nullable=True)   # 'smartfarm:tomato' 등
    # AI 가 만들었다면 **근거**를 적는다. 없으면 나중에 이 값을 고칠 사람이 판단할
    # 재료가 없다.
    source_note = db.Column(db.Text, nullable=True)
    # 복제 출처(링크가 아니라 기록). 원본이 바뀌어도 따라가지 않는다.
    derived_from = db.Column(db.String(36), nullable=True)

    # 사람이 확인한 시각. `source='ai'` 인데 비어 있으면 제어 연결 금지.
    reviewed_at = db.Column(db.DateTime, nullable=True)

    # 내용을 고칠 때마다 올린다. 구획은 이 값을 고정해 둔다.
    version = db.Column(db.Integer, nullable=False, default=1)

    # 단계 목록 —
    #   [{ key, name, days, gdd?, targets{}, functions[], tasks[] }]
    # `days` 는 **그 단계의 길이**다(누적이 아니다). 누적으로 두면 중간 단계를
    # 늘릴 때 뒤 단계를 전부 손봐야 한다.
    stages = db.Column(db.JSON, nullable=False, default=list)

    # 이 프로그램이 다루는 **목표 항목의 정의** —
    #   [{ key, label, unit, measurement, shape, min, max, fixed, hidden }]
    #
    # ## 왜 정의가 프로그램에 있나 (2026-08-20)
    #
    # 예전에는 여섯 항목이 `program_io._TARGET_FIELDS` 에 코드로 박혀 있었다.
    # 그러면 **종류를 모른다** — 축사 프로그램의 편집 화면에도 DLI·VPD 칸이
    # 그대로 나오고, 그 화면은 그냥 틀린 말을 한다. 반대로 EC·pH 처럼 실제로
    # 관리하는 값은 적을 칸이 없었다.
    #
    # ## 정의는 프로그램 단위, 값은 단계 단위
    #
    # 같은 항목은 **모든 단계에서 같은 것을 뜻해야 한다.** 정의를 단계마다 들려
    # 두면 육묘기의 "습도 %" 와 착과기의 "습도 g/m³" 가 조용히 갈리고, 그것을
    # 읽는 제어·AI 는 둘을 같은 값으로 비교한다. 정의가 위에 있으면 그 사고가
    # 구조적으로 불가능하다. 단계는 `targets = {키: 숫자}` 만 갖는다.
    #
    # ## `measurement` 가 제어 연결을 정한다
    #
    # `config_devices_units.MEASUREMENTS` 의 키다(새 어휘를 짓지 않는다 — 센서·
    # 그래프가 이미 그 어휘를 쓰므로, 목표가 거기 붙으면 "이 목표를 재는 센서" 를
    # 잇는 길이 저절로 생긴다). 비어 있으면 AoT 가 뜻을 모르는 값이라 **표시·
    # 조언 전용**이고 제어에 닿지 않는다 — 코드는 자기가 뜻을 모르는 값으로
    # 물리적 행동을 할 수 없다.
    target_defs = db.Column(db.JSON, nullable=True)

    # 목표 곡선 — `{목표항목: Method.unique_id}`.
    #
    # 단계별 `targets` 는 **계단**이다(그 단계 내내 같은 값). 실제 재배는 주차마다
    # 조금씩 옮겨 가는 쪽이 많고, AoT 에는 그것을 표현하는 수단이 이미 있다 —
    # Method(시간축 곡선). 그래서 항목마다 Method 를 걸 수 있게 한다.
    #
    # **곡선이 있으면 곡선이 이긴다**(더 세밀하다). 없는 항목은 단계 값을 쓴다.
    # 기준 시각은 **파종일**이다 — 프로그램은 작기의 시작부터 도는 것이므로,
    # 함수의 `method_start_time`(그 함수가 켜진 시각)과는 다른 기준이다.
    targets_methods = db.Column(db.JSON, nullable=True)

    # 자원 역할 선언 — `[{role, default}]` (P6, 2026-08-20 재설계).
    #
    # **함수 uuid 를 담지 않는다.** 프로그램은 "이 작물은 관수를 쓴다" 까지만
    # 말하고, 그 일을 무엇이 하는지는 현장이 기하로 푼다
    # (`plot_context.resources_for_plot`). 예전에는 `stages[].functions` 에
    # 함수 uuid 를 적었는데, 그러면 프로그램이 템플릿이기를 그만둔다 — 두 번째
    # 온실에서 쓰려면 복제해야 하고 작물 지식이 두 벌이 된다.
    #
    # `default` 는 **단계 기본값**이다. 목표(`target_defs`)와 같은 패턴 —
    # 프로그램에 한 번 적고 달라지는 단계에서만 덮어쓴다. 관수는 대개 작기 내내
    # 필요하고, 단계마다 달라지는 것은 예외(수확 전 단수) 쪽이다.
    resource_defs = db.Column(db.JSON, nullable=True)

    # 광합성 파라미터(Big-Leaf 모델 상수 + GDD 기준온도 + 권장 DLI/GDD).
    # 키 이름은 제어 쪽 `CropParams` 와 **같다** — 갈리면 값이 조용히 무시되고
    # 모델이 기본값으로 돈다. 여기 두는 이유는 프로그램이 자기 완결적이어야
    # 버전 고정이 의미를 갖기 때문이다: 파라미터가 밖에 있으면 프로그램 버전을
    # 고정해도 목표가 바뀔 수 있다.
    photosynthesis = db.Column(db.JSON, nullable=True)

    # 이 프로그램을 쓰는 구획의 단계 전환을 사람 확인 없이 기록한다(P7).
    #
    # **버전 고정을 타지 않는다.** 단계 기간·목표는 "그때 무엇을 목표로 길렀나" 의
    # 답이라 고정하지만, 자동 승인은 농학적 해석이 아니라 **운영 취향**이다 —
    # 지금 켜면 지금부터 적용되는 것이 사람이 기대하는 동작이다.
    #
    # 기본은 꺼짐이다. 켜져 있는 것이 기본이면 사람이 아무 결정도 하지 않았는데
    # 단계가 스스로 넘어간다.
    auto_advance = db.Column(db.Boolean, nullable=False, default=False)

    notes = db.Column(db.Text, nullable=True)

    # 소속 탭(`Tab.unique_id`) — geo/program 화면의 사용자 구획 정보일 뿐이다.
    #
    # **진짜 FK 제약을 걸지 않는다**(`geo_planting.facility_uuid`와 같은 패턴,
    # p6_39). 탭이 지워져도 이 값이 가리키는 행이 사라져서는 안 된다 — 이
    # 프로그램은 다른 구획(`GeoPlot.program_uuid`)에서 참조 중일 수 있어, DB
    # 레벨 CASCADE로 함께 지우면 무결성이 깨진다. 탭 삭제 시 재배정은
    # `TabService`의 고아 정리가 담당한다.
    tab_id = db.Column(db.String(36), nullable=True, index=True)

    created_at = db.Column(db.DateTime, default=utc_now)
    updated_at = db.Column(db.DateTime, default=utc_now, onupdate=utc_now)

    # ── 읽기 헬퍼 ─────────────────────────────────────────────────────
    def stage_list(self):
        """단계 목록(리스트). JSON 이 깨져 있어도 화면을 막지 않는다."""
        return self.stages if isinstance(self.stages, list) else []

    def target_def_list(self):
        """목표 항목 정의 → 리스트.

        **비어 있으면 종류의 고정 항목으로 채워 답한다.** 이 컬럼은 나중에 생겼고
        (`p6_47`), 마이그레이션이 채워 넣기는 하지만 그 전에 만들어진 행이나
        JSON 이 깨진 행이 있을 수 있다. 읽는 쪽마다 "비었으면 어떻게" 를 각자
        정하면 화면과 제어가 다른 목록을 보게 된다.
        """
        from aot.aot_flask.geo.program_io import fixed_target_defs

        defs = self.target_defs
        if isinstance(defs, list) and defs:
            return defs
        return fixed_target_defs(self.kind)

    def resource_def_list(self):
        """자원 역할 정의 → `[{role, default}]`. 없으면 빈 목록.

        **비어 있음이 정상이다** — 자원을 쓰지 않는 프로그램이 있다. 목표
        (`target_def_list`)처럼 고정 항목으로 채우지 않는 이유는, 자원은 종류가
        정해 주는 것이 아니라 그 작물을 어떻게 기르는가의 문제라서다.
        """
        defs = self.resource_defs
        return defs if isinstance(defs, list) else []

    def total_days(self):
        """전체 재배 기간(일). 단계에 `days` 가 없으면 그 단계는 0으로 센다.

        예상 수확일을 파생하는 근거다 — 사람이 종료일을 따로 적지 않아도 되게.
        """
        total = 0
        for st in self.stage_list():
            try:
                total += int(st.get('days') or 0)
            except (TypeError, ValueError, AttributeError):
                continue
        return total

    def is_editable(self):
        """사람이 화면에서 고칠 수 있는가.

        내장·외부는 읽기 전용이다 — 고치고 싶으면 복제한다. 원본을 고치게 두면
        업그레이드나 외부 갱신이 그 수정을 덮어써 조용히 되돌아간다.
        """
        return self.source in ('user', 'ai')

    def usable_for_control(self):
        """제어에 쓸 수 있는가 — `ai` 는 사람 확인 전까지 안 된다."""
        return self.source != 'ai' or self.reviewed_at is not None

    def __repr__(self):
        return ("<{cls}(id={s.id}, kind={s.kind!r}, subject={s.subject!r}, "
                "v={s.version})>".format(s=self, cls=self.__class__.__name__))
