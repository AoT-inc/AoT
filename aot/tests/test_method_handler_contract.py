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
