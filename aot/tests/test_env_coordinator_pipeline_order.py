# coding=utf-8
"""제어 파이프라인의 순서 계약 테스트.

`_run_cycle` 안에서 `commands`(ActuatorCommand dict)와 `final_cmds`(Post-Gate가
만든 별개 dict)는 **서로 다른 객체**다.

    final_cmds, _ = self._post_gate.check(
        {aid: {'value': c.value, 'reason': c.reason} for aid, c in commands.items()}, ...)

Post-Gate 는 입력을 dict 로 변환해 새 객체를 만들고, 내부에서 다시 `dict(commands)`
로 복사한다. 따라서 이 시점 이후 `commands` 를 고쳐도 전송 대상에 닿지 않는다.

2026-08-04 감사에서 그 경계를 사이에 두고 두 기능이 정반대로 어긋나 있었다.

    능동 탐색(probe)  : Post-Gate 뒤에서 commands 를 수정 → 로그○ 전송✗
                        (enable_active_probing 을 켜도 장치에 나가지 않았다)
    순환팬(mixing)    : Post-Gate 뒤에서 final_cmds 를 수정 → 로그✗ 전송○
                        (dict 규약인 final_cmds 에 ActuatorCommand 를 섞기도 했다)

둘 다 Post-Gate **앞**으로 옮겨 `commands` 를 대상으로 삼는다. 그러면 로그와
전송이 같은 값을 보고, 탐색 값도 Post-Gate 의 NaN/범위 검증을 받는다.

이 테스트는 소스의 호출 순서를 직접 확인한다 — 사이클 전체를 돌리려면 센서·
InfluxDB·프로파일이 모두 필요해 단위 테스트로는 과하고, 정작 지켜야 할 것은
"어느 단계가 어느 dict 를 언제 만지는가" 하나이기 때문이다.
"""
import ast
import inspect

from aot.functions.custom_functions.env_coordinator_impl import _cycle_mixin


def _run_cycle_source():
    """모듈 전체를 파싱해 _run_cycle 노드를 돌려준다.

    메서드 소스만 떼어내면 들여쓰기가 남아 그대로는 파싱되지 않는다. 파일을
    통째로 읽어 노드를 고르는 편이 단순하고 깨질 여지도 없다.
    """
    path = inspect.getsourcefile(_cycle_mixin)
    tree = ast.parse(open(path, encoding='utf-8').read())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == '_run_cycle':
            return node
    raise AssertionError('_run_cycle 를 찾지 못했다')


def _line_of(tree, predicate):
    """조건에 맞는 첫 노드의 줄 번호."""
    for node in ast.walk(tree):
        if predicate(node):
            return node.lineno
    return None


def _call_line(tree, attr_name):
    return _line_of(tree, lambda n: (
        isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == attr_name))


def test_probe_and_mixing_run_before_post_gate():
    """탐색·혼합이 Post-Gate 뒤에 있으면 전송 대상에 닿지 않거나 로그에서 빠진다."""
    tree = _run_cycle_source()

    probe_line     = _call_line(tree, 'step')                    # _probe_scheduler.step
    mixing_line    = _call_line(tree, '_apply_mixing_actuators')
    post_gate_line = _call_line(tree, 'check')                   # _post_gate.check
    dispatch_line  = _call_line(tree, '_dispatch')

    assert probe_line and mixing_line and post_gate_line and dispatch_line

    assert probe_line < post_gate_line, (
        '능동 탐색이 Post-Gate 뒤에 있다 — commands 를 고쳐도 final_cmds 로 '
        '전송되지 않아 탐색이 무효가 된다')
    assert mixing_line < post_gate_line, (
        '순환팬 제어가 Post-Gate 뒤에 있다 — 전송은 되지만 '
        'write_cycle_metrics(commands) 에 잡히지 않아 근거를 추적할 수 없다')
    assert post_gate_line < dispatch_line


def test_mixing_targets_commands_not_final_cmds():
    """혼합 제어는 commands(ActuatorCommand)에 적용해야 타입 규약이 유지된다."""
    tree = _run_cycle_source()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == '_apply_mixing_actuators'):
            first_arg = node.args[0]
            assert isinstance(first_arg, ast.Name), '첫 인자가 이름이 아니다'
            assert first_arg.id == 'commands', (
                f'_apply_mixing_actuators 가 {first_arg.id} 를 받는다 — '
                'dict 규약인 final_cmds 에 ActuatorCommand 를 섞으면 안 된다')
            return
    raise AssertionError('_apply_mixing_actuators 호출을 찾지 못했다')


def test_cycle_metrics_logged_after_probe_and_mixing():
    """로그가 탐색·혼합보다 앞서면 그 결정들이 기록에서 빠진다."""
    tree = _run_cycle_source()

    metrics_line = _line_of(tree, lambda n: (
        isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == 'write_cycle_metrics'))
    probe_line  = _call_line(tree, 'step')
    mixing_line = _call_line(tree, '_apply_mixing_actuators')

    assert metrics_line, 'write_cycle_metrics 호출을 찾지 못했다'
    assert probe_line < metrics_line
    assert mixing_line < metrics_line


def test_mixing_produces_actuator_command_not_dict():
    """_apply_mixing_actuators 가 dict 를 넣으면 Post-Gate 변환(c.value)에서 터진다."""
    src = inspect.getsource(_cycle_mixin.CycleMixin._apply_mixing_actuators)
    assert 'ActuatorCommand(' in src
    assert "{'value'" not in src, '혼합 제어가 dict 를 만들고 있다'
