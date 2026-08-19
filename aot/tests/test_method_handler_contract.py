# coding=utf-8
"""메서드 핸들러 생성 규약 테스트.

`create_method_handler()` 는 **모든** 핸들러를
`(method, method_data, logger, target_id=...)` 로 생성한다. 서브클래스가 자체
`__init__` 을 두면서 `target_id` 를 빠뜨리면 그 타입만 TypeError 로 로드가
통째로 실패한다 — 그런데 실패 지점이 죄다 `except Exception` 으로 감싸여 있어
(PID·트리거·조율기 모두) 조용히 기본값으로 물러난다. 즉 **에러 로그를 직접
읽기 전까지는 아무도 모른다.**

2026-07-31 `d48b2b7` 이 `AbstractMethod` 에 `target_id` 를 추가하면서
`DailyMultiPointMethod` 만 갱신에서 빠졌고, aot-005 '고추육묘 VPD'(DailyMultiPoint)
목표가 4일간 정적 기본값 0.8 로 떨어져 있었다.

DB 는 건드리지 않는다 — Method/MethodData 는 스텁으로 대체한다.
"""
import inspect
import json

from aot.utils import method as method_mod
from aot.utils.method import AbstractMethod, create_method_handler


class _DataQuery:
    """MethodData 쿼리 흉내 — filter(...).all()/.first() 만 쓰인다."""

    def __init__(self, rows):
        self._rows = rows

    def filter(self, *_a, **_k):
        return self

    def all(self):
        return list(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None


def _method_classes():
    """method 모듈이 노출하는 AbstractMethod 서브클래스 전부."""
    found = []
    for name in dir(method_mod):
        obj = getattr(method_mod, name)
        if inspect.isclass(obj) and issubclass(obj, AbstractMethod):
            found.append((name, obj))
    return sorted(found)


def test_every_method_class_accepts_target_id():
    """팩토리가 넘기는 target_id 를 모든 핸들러가 받아야 한다.

    새 메서드 타입을 추가하면서 자체 __init__ 을 두면 여기서 걸린다.
    """
    missing = [
        name for name, cls in _method_classes()
        if 'target_id' not in inspect.signature(cls.__init__).parameters
    ]
    assert not missing, (
        'create_method_handler() 는 모든 핸들러에 target_id 를 넘긴다. '
        '다음 클래스는 받지 못해 로드가 TypeError 로 실패한다: %s' % missing)


def test_every_method_class_is_reachable_by_factory():
    """팩토리의 이름 규칙(`<method_type>Method`)이 실제 클래스와 맞는지."""
    for name, _cls in _method_classes():
        if name.startswith('Abstract'):
            continue
        assert name.endswith('Method'), name
        method_type = name[:-len('Method')]
        assert getattr(method_mod, method_type + 'Method', None) is not None


def _multipoint_stub():
    points = {
        'version': 3,
        'weeks': [0],
        'points': [
            {'point_id': 0, 't_sec': 0, 'values': [0.6], 'smooth': False,
             'curve': 'linear', 'handle_dt': None, 'handle_dv': None,
             'is_endpoint': True},
            {'point_id': 1, 't_sec': 86400, 'values': [1.2], 'smooth': False,
             'curve': 'linear', 'handle_dt': None, 'handle_dv': None,
             'is_endpoint': True},
        ],
    }

    class _Row:
        output_id = None
        duration_sec = None
        points_json = json.dumps(points)

    class _Method:
        unique_id = 'test-multipoint'
        method_type = 'DailyMultiPoint'
        name = 'VPD 곡선'

    return _Method(), _DataQuery([_Row()])


def test_factory_loads_daily_multipoint_with_target_id():
    """회귀: DailyMultiPoint 가 target_id 와 함께 생성되어야 한다.

    수정 전에는 여기서 TypeError:
    `DailyMultiPointMethod.__init__() got an unexpected keyword argument 'target_id'`
    """
    m, data = _multipoint_stub()
    handler = create_method_handler(m, data, logger=None, target_id='pid-001')

    assert handler is not None
    assert handler.target_id == 'pid-001'
    # 폴백(_default_data)이 아니라 실제 points_json 을 읽었는지 — 로드 실패를
    # 조용한 기본값으로 착각하지 않기 위해 값까지 확인한다.
    assert handler._data['points'][1]['values'] == [1.2]


def test_factory_loads_daily_multipoint_without_target_id():
    """target_id 를 안 넘기는 호출부(조율기·그래프)도 그대로 동작해야 한다."""
    m, data = _multipoint_stub()
    handler = create_method_handler(m, data)

    assert handler is not None
    assert handler.target_id is None


# ── facility_tz: 문자열도 받는다 ─────────────────────────────────────────────
#
# 하루 곡선은 **시각이 곧 값**이라, 시간대를 잘못 잡으면 새벽 목표가 한낮에
# 적용된다(한국이면 9시간). 그런데 예전에는 시간대를 **문자열로 넘기면**
# `datetime.fromtimestamp(tz='Asia/Seoul')` 가 TypeError 를 내고 그대로 UTC 로
# 떨어졌다 — 에러도 로그도 없이 값만 9시간 밀렸다(2026-08-19 시뮬레이션에서
# 발견: 같은 곡선이 0.33 대신 0.66 을 돌려줬다).

def _daily_curve_stub():
    """00:00 에 0.0, 12:00 에 12.0, 24:00 에 0.0 — 시각이 곧 값인 곡선."""
    points = {
        'version': 3,
        'weeks': [0],
        'points': [
            {'point_id': 0, 't_sec': 0, 'values': [0.0], 'smooth': False,
             'curve': 'linear', 'handle_dt': None, 'handle_dv': None,
             'is_endpoint': True},
            {'point_id': 1, 't_sec': 43200, 'values': [12.0], 'smooth': False,
             'curve': 'linear', 'handle_dt': None, 'handle_dv': None,
             'is_endpoint': False},
            {'point_id': 2, 't_sec': 86400, 'values': [0.0], 'smooth': False,
             'curve': 'linear', 'handle_dt': None, 'handle_dv': None,
             'is_endpoint': True},
        ],
    }

    class _Row:
        output_id = None
        duration_sec = None
        points_json = json.dumps(points)

    class _Method:
        unique_id = 'tz-curve'
        method_type = 'DailyMultiPoint'
        name = 'tz 곡선'

    return _Method(), _DataQuery([_Row()])


def _at(handler, tz):
    """2026-01-01 03:00 UTC 에서의 곡선 값."""
    import calendar
    ts = calendar.timegm((2026, 1, 1, 3, 0, 0, 0, 0, 0))
    val, _ended = handler.calculate_setpoint(ts, weeks_elapsed=0.0,
                                             facility_tz=tz)
    return val


def test_facility_tz_accepts_a_timezone_name():
    """문자열과 tz 객체가 **같은 값**이어야 한다."""
    import pytz
    handler = create_method_handler(*_daily_curve_stub())
    by_name = _at(handler, 'Asia/Seoul')
    by_obj = _at(handler, pytz.timezone('Asia/Seoul'))
    assert by_name is not None
    assert abs(by_name - by_obj) < 1e-9, (by_name, by_obj)
    # 03:00 UTC = 12:00 KST → 곡선의 정점.
    assert abs(by_name - 12.0) < 1e-6, by_name


def test_utc_fallback_is_not_silent():
    """해석할 수 없는 시간대면 UTC 로 계산하되 **말한다**. 조용히 밀리면
    "왜 새벽에 한낮 목표가 잡히지" 를 추적할 단서가 없다."""
    class _Log:
        def __init__(self):
            self.warnings = []

        def warning(self, msg, *args):
            self.warnings.append(msg % args if args else msg)

        def debug(self, *a, **k):
            pass

    log = _Log()
    m, data = _daily_curve_stub()
    handler = create_method_handler(m, data, logger=log)
    val = _at(handler, 'Nowhere/Bad')
    # 03:00 UTC → 0→12 직선의 1/4 지점(3.0). KST 로 읽었다면 정점 12.0 이다.
    assert abs(val - 3.0) < 1e-6, val
    assert log.warnings, '조용히 UTC 로 떨어졌다'
    assert 'Nowhere/Bad' in log.warnings[0]
