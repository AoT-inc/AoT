# coding=utf-8
"""제어 사이클의 구조 계약 테스트.

`_run_cycle` 은 727줄까지 자라 있었다. 한 메서드가 센서 수집·게이트·목표 산출·
조율·전송·학습·상태저장을 전부 안고 있으면, 오늘 실제로 겪은 종류의 버그
(어느 단계가 어느 dict 를 언제 만지는지 헷갈려 probe 가 전송되지 않던 문제)를
읽어서 발견하기가 매우 어렵다.

부가 계산과 꼬리 작업을 메서드로 떼어냈다. 각 추출은 **본문을 한 글자도 바꾸지
않고 옮기기만** 했다 — 제어 코드라 "옮겼을 뿐" 을 보장하는 편이 검토와 되돌리기
모두 쉽기 때문이다.

이 테스트는 그 구조가 도로 뭉치지 않도록 지킨다. 줄 수 상한은 취향이 아니라
"한 화면에서 흐름을 볼 수 있는가" 의 대리 지표다.
"""
import ast
import inspect

import pytest

from aot.functions.custom_functions.env_coordinator_impl import _cycle_mixin

# 추출된 단계와 그 역할. 이름이 바뀌면 여기도 바뀌어야 한다 —
# 그 자체가 "무엇이 단계인가" 를 명시하는 기록이다.
_EXTRACTED = {
    '_collect_external_context':      '실외 컨텍스트 확정(공유·시설센서·승계)',
    '_check_hard_constraints':        '온습도·광량 하드 임계 판정',
    '_apply_forecast_feedforward':    '예보 기반 목표 선제 보정',
    '_apply_photosynthesis_priority': '광합성 제한인자 우선순위 격상',
    '_finalize_cycle':                '학습·누적·상태 저장(명령 이후)',
}

# _run_cycle 이 다시 비대해지지 않게 막는 상한. 현재 402줄이며, 남은 부분은
# L1→L2→L3 주 파이프라인이라 데이터가 촘촘히 흘러 더 쪼개면 인자 목록만
# 길어진다. 여유를 조금 두되 727줄 시절로 돌아가지는 못하게 한다.
_RUN_CYCLE_MAX_LINES = 480


def _functions():
    src = inspect.getsource(_cycle_mixin)
    tree = ast.parse(src)
    return {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}


def test_run_cycle_stays_readable():
    fn = _functions()['_run_cycle']
    length = fn.end_lineno - fn.lineno + 1
    assert length <= _RUN_CYCLE_MAX_LINES, (
        f'_run_cycle 이 {length}줄이다(상한 {_RUN_CYCLE_MAX_LINES}). '
        '새 단계를 인라인으로 붙이는 대신 메서드로 떼어내라 — '
        '727줄 시절에는 probe 가 전송되지 않는 것조차 읽어서 알기 어려웠다.')


@pytest.mark.parametrize('name,role', sorted(_EXTRACTED.items()))
def test_extracted_stage_exists(name, role):
    """추출된 단계가 도로 인라인되면 여기서 걸린다."""
    assert name in _functions(), f'{name} ({role}) 가 사라졌다'


@pytest.mark.parametrize('name', sorted(_EXTRACTED))
def test_extracted_stage_is_called_from_run_cycle(name):
    """정의만 남고 호출이 빠지면 그 단계가 통째로 죽는다 — 조용히."""
    run_cycle = _functions()['_run_cycle']
    called = any(
        isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        and n.func.attr == name
        for n in ast.walk(run_cycle))
    assert called, f'_run_cycle 이 {name} 를 호출하지 않는다'


def test_cycle_context_carries_finalize_inputs():
    """_finalize_cycle 이 쓰는 값은 전부 _CycleContext 로 전달돼야 한다.

    지역변수를 직접 참조하면 NameError 가 나거나, 더 나쁘게는 모듈 전역을
    주워 조용히 다른 값으로 동작한다.
    """
    ctx_fields = {
        f.target.id if isinstance(f, ast.AnnAssign) and isinstance(f.target, ast.Name)
        else None
        for f in _functions_class_body('_CycleContext')
    } - {None}

    finalize = _functions()['_finalize_cycle']
    # 메서드 앞머리에서 ctx.<field> 로 되살리는 이름들
    unpacked = {
        n.targets[0].id
        for n in finalize.body
        if isinstance(n, ast.Assign)
        and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name)
        and isinstance(n.value, ast.Attribute)
        and isinstance(n.value.value, ast.Name) and n.value.value.id == 'ctx'
    }
    assert unpacked, '_finalize_cycle 이 ctx 에서 아무것도 꺼내지 않는다'
    missing = unpacked - ctx_fields
    assert not missing, f'_CycleContext 에 없는 필드를 꺼내려 한다: {missing}'


def _functions_class_body(class_name):
    tree = ast.parse(inspect.getsource(_cycle_mixin))
    for n in ast.walk(tree):
        if isinstance(n, ast.ClassDef) and n.name == class_name:
            return n.body
    raise AssertionError(f'{class_name} 를 찾지 못했다')


def test_extractions_did_not_change_dispatch_order():
    """추출이 제어 순서를 흔들지 않았는지 — 순서 계약은 별도 파일이 지키지만,
    여기서도 dispatch 가 finalize 보다 앞선다는 큰 골격만 확인한다."""
    run_cycle = _functions()['_run_cycle']

    def line_of(attr):
        for n in ast.walk(run_cycle):
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and n.func.attr == attr):
                return n.lineno
        return None

    dispatch = line_of('_dispatch')
    finalize = line_of('_finalize_cycle')
    constraints = line_of('_check_hard_constraints')

    assert constraints and dispatch and finalize
    assert constraints < dispatch, '임계 판정은 전송보다 앞서야 한다'
    assert dispatch < finalize, '학습·상태저장은 명령을 보낸 뒤에 한다'
