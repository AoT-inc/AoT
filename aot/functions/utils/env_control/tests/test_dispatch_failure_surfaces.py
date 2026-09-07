# coding=utf-8
"""dispatch 실패가 **위로 전달되는지** — 조용한 성공을 막는 가드.

## 무엇을 지키는가

이 경로의 실패는 **예외로 오지 않는다.** `control.output_on/off` 는 Pyro5 RPC
이고, 데몬(`aot_daemon.output_on`)과 클라이언트(`DaemonControl.output_on`)가
각자 `except Exception` 으로 잡아 `(1, msg)` 튜플로 바꾼다. 그래서 어댑터가
반환값을 버리면 실패를 알 방법이 통째로 사라진다.

## 실제로 그렇게 샜다 (2026-09-07 영양 천창1)

릴레이 참조가 비어(`{'device_id': None, 'channel_id': None}`) 명령이 한 번도
실행되지 않았는데, 4개 층이 연달아 그것을 놓쳤다:

    actuator_paired._relay_on   경고만 남기고 return   → 예외 없음
    DispatchAdapter.send        반환값을 버림(-> None)
    _dispatch                   예외만 failed 에 넣음  → 성공으로 집계
    record_dispatch(success=T)  신뢰도를 **올린다**

결과: 130회 명령이 전부 성공으로 기록되고 `actuator_mismatch` 는 48시간 내내
0 이었다 — 감지 장치가 정확히 반대로 작동했다. 그동안 코디네이터는 그 창이
열렸다고 믿고 부하분담 장부에 그 몫을 쌓았다.

## 여기서 고정하는 계약

1. 어댑터는 `(1, msg)` 를 받으면 **예외를 올린다** (그래야 `_dispatch` 가 본다).
2. `(0, msg)` 와 **튜플이 아닌 반환(None 포함)** 은 통과시킨다 — 반환값을 주지
   않는 자리가 아직 남아 있어, 모르는 것을 실패로 바꾸면 정상 장치가 무더기로
   신뢰를 잃는다(그쪽 오탐이 훨씬 위험하다).
3. **모든** 어댑터의 모든 `control.output_*` 호출이 검사를 지난다(AST).
   목록으로 관리하면 새 어댑터가 생길 때 조용히 갈라진다.
"""
import ast
import inspect
import pathlib

import pytest

from aot.functions.utils.env_control import dispatch_adapters as da


# ── 테스트 대역 ──────────────────────────────────────────────────────────────

class _FakeControl:
    """데몬이 실제로 돌려주는 모양을 흉내낸다 — 예외가 아니라 `(code, msg)`."""

    def __init__(self, ret):
        self.ret = ret
        self.calls = []

    def output_on(self, *a, **k):
        self.calls.append(('on', a, k))
        return self.ret

    def output_off(self, *a, **k):
        self.calls.append(('off', a, k))
        return self.ret


def _all_adapters():
    """구체 어댑터 전수 — 새로 만들면 자동으로 여기 걸린다."""
    return {
        'value':    da.DispatchAdapter(),
        'pwm':      da.PwmAdapter(),
        'timeprop': da.TimeProportionalAdapter(),
        'paired':   da.PairedAdapter(),
        'volume':   da.VolumetricAdapter(flow_lpm=2.0),
        'pulsed':   da.PulsedDoseAdapter(
            da.TimeProportionalAdapter(), max_on_sec=10.0, min_off_sec=60.0),
    }


# ── 1. 실패는 반드시 예외가 된다 ─────────────────────────────────────────────

@pytest.mark.parametrize('name', sorted(_all_adapters()))
def test_daemon_failure_becomes_an_exception(name):
    """`(1, msg)` = 데몬이 거부했다. 삼키면 `_dispatch` 가 성공으로 센다."""
    adapter = _all_adapters()[name]
    with pytest.raises(RuntimeError) as exc:
        adapter.send(_FakeControl((1, '릴레이 설정 없음')),
                     'act-1', 60.0, 0, 600.0)
    # 어느 장치인지 메시지에 남아야 한다 — 로그만 보고 원인에 닿을 수 있게.
    assert 'act-1' in str(exc.value)


@pytest.mark.parametrize('name', sorted(_all_adapters()))
def test_turning_off_also_surfaces_failure(name):
    """끄기(0%)도 실패를 드러낸다.

    "못 끈 것" 은 "못 켠 것" 보다 위험한데, 여기가 조용하면 그 사실이
    어디에도 안 남는다.
    """
    adapter = _all_adapters()[name]
    with pytest.raises(RuntimeError):
        adapter.send(_FakeControl((1, 'off 실패')), 'act-1', 0.0, 0, 600.0)


# ── 2. 정상은 통과한다 (오탐이 더 위험하다) ──────────────────────────────────

@pytest.mark.parametrize('name', sorted(_all_adapters()))
@pytest.mark.parametrize('ret', [(0, 'OK'), None, 'Error-ish-string'],
                         ids=['success_tuple', 'none', 'non_tuple'])
def test_non_failure_returns_pass_through(name, ret):
    """튜플이 아닌 반환은 **성공으로 본다**.

    반환값을 주지 않는 경로가 아직 남아 있다. 모르는 것을 실패로 바꾸면
    멀쩡한 장치가 전부 신뢰를 잃는다.
    """
    _all_adapters()[name].send(_FakeControl(ret), 'act-1', 60.0, 0, 600.0)


def test_judgement_matches_the_audit_log_rule():
    """판정 규약은 `controller_output.output_on_off` 의 감사로그와 **같아야** 한다.

    두 벌이 되면 갈라지고, 갈라지면 감사로그와 제어가 서로 다른 성패를
    기록한다. 거기 규칙은 `bool(ret[0])` 하나다.
    """
    assert da._raise_if_failed(None, 'a', 'x') is None
    assert da._raise_if_failed((0, 'ok'), 'a', 'x') is None
    assert da._raise_if_failed([], 'a', 'x') is None
    with pytest.raises(RuntimeError):
        da._raise_if_failed((1, 'nope'), 'a', 'x')
    with pytest.raises(RuntimeError):
        da._raise_if_failed((2, 'nope'), 'a', 'x')


# ── 3. 새 어댑터가 검사를 빠뜨리는 것을 막는다 ───────────────────────────────

def test_every_control_call_is_checked():
    """모든 `control.output_*` 호출이 `_raise_if_failed` 를 지난다.

    ⚠ 이 검사가 없으면 새 어댑터를 추가할 때 조용히 갈라진다 — 그 어댑터만
      실패를 삼키게 되고, 증상은 "그 장치만 고장을 안 알린다" 라 원인에
      닿기까지 오래 걸린다.
    """
    src = pathlib.Path(inspect.getfile(da)).read_text()
    tree = ast.parse(src)

    guarded = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == '_raise_if_failed'):
            for arg in node.args:
                for sub in ast.walk(arg):
                    if isinstance(sub, ast.Call):
                        guarded.add((sub.lineno, sub.col_offset))

    unguarded = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in ('output_on', 'output_off')
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == 'control'
                and (node.lineno, node.col_offset) not in guarded):
            unguarded.append(node.lineno)

    assert not unguarded, (
        '검사를 지나지 않는 control.output_* 호출이 있습니다 (줄 %s). '
        '_raise_if_failed 로 감싸세요 — 안 그러면 그 장치의 실패가 '
        '성공으로 집계됩니다.' % unguarded)


def test_adapters_under_test_cover_every_concrete_class():
    """위 테스트가 도는 어댑터 목록이 실제 클래스 전수와 일치하는가.

    목록을 손으로 관리하므로, 새 어댑터가 생기면 여기서 먼저 깨져야 한다.
    """
    concrete = {
        name for name, obj in vars(da).items()
        if isinstance(obj, type)
        and issubclass(obj, da.DispatchAdapter)
        and name != 'ValueAdapter'          # DispatchAdapter 별칭
    }
    covered = {type(a).__name__ for a in _all_adapters().values()}
    assert concrete == covered, (
        '테스트가 다루지 않는 어댑터: %s' % (concrete - covered))
