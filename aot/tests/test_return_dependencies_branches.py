# coding=utf-8
"""`utils_general.return_dependencies()` 의 분기별 판정 회귀 테스트.

이 함수는 두 값을 돌려준다.

* `unmet_deps` — 채워져 있으면 웹 UI 가 그 장치/메서드의 **생성을 막는다**
  (utils_input/output/function/action/method 전부 같은 패턴).
* `met_deps`  — 관리자 Dependencies 페이지의 "충족됨" 목록에만 쓰인다.

2026-08-10 감사에서 pip-pypi 분기만 올바르고 나머지 세 분기가 제각각 틀려
있는 걸 실측으로 확인해 아래 4건을 고쳤다. 같은 실수가 되돌아오지 않게
분기마다 "미충족/충족/중복선언" 세 경우를 고정한다.

1. apt: 미충족 판정과 중복제거를 `and` 로 묶어, 미설치인데 이미 목록에
   있으면 else 로 떨어져 met_deps=True 가 됐다.
2. bash-commands: 파일이 전부 있어도 met_deps 를 켜는 else 가 아예 없었다
   (highstock, 그래프/게이지 위젯이 여기 해당 — 실측상 unmet=0 인데
   met=False 라 Dependencies 페이지 어느 목록에도 안 나왔다).
3. bash-commands: 중복제거를 실제로 넣는 튜플이 아니라 쓰지도 않는 `entry`
   로 검사해서, 중복제거가 늘 통과하고(같은 항목이 여러 번 쌓임) else 의
   met_deps=True 는 도달 불가능한 죽은 코드였다.
4. internal/apt: `'apt <이름>'` 문자열을 그대로 dpkg-query 에 넘겨 인자가 두
   개가 됐고, 'apt' 자신은 늘 설치돼 있으니 무엇을 선언하든 "설치됨"이었다.

추가로 루프 머리의 `if not each_dict: met_deps = True` 는 장치 딕셔너리의
아무 필드나 비어 있으면 켜졌다(예: TH16 의 measurements_use_same_timestamp).
이제 dependencies_module 이 비었을 때만 켠다.
"""
import sys
from contextlib import contextmanager
from unittest.mock import patch

import pytest

from aot.aot_flask.utils import utils_general

DEVICE = 'ZZZ_TEST_DEVICE'


@contextmanager
def only(dependencies, extra_fields=None):
    """모든 의존성 소스를 합성 장치 하나로 대체한다."""
    device = {'name': DEVICE, 'dependencies_module': dependencies}
    if extra_fields:
        device.update(extra_fields)
    empty = {}
    with patch.multiple(
            utils_general,
            parse_function_information=lambda: empty,
            parse_action_information=lambda: empty,
            parse_input_information=lambda: empty,
            parse_output_information=lambda: empty,
            parse_widget_information=lambda: empty,
            CAMERA_INFO=empty,
            FUNCTION_INFO=empty,
            METHOD_INFO=empty,
            DEPENDENCIES_GENERAL={DEVICE: device}):
        yield


def _run():
    unmet, met, _ = utils_general.return_dependencies(DEVICE)
    return unmet, met


# ---------------------------------------------------------------------------
# apt
# ---------------------------------------------------------------------------

APT = ('apt', 'zzz-pkg', 'zzz-pkg')


def test_apt_missing_is_unmet():
    with only([APT]), patch.object(utils_general, 'dpkg_package_exists',
                                   return_value=None):
        unmet, met = _run()
    assert len(unmet) == 1
    assert met is False


def test_apt_missing_twice_stays_unmet():
    """중복 선언이 미충족을 '충족'으로 뒤집으면 안 된다(회귀 1)."""
    with only([APT, APT]), patch.object(utils_general, 'dpkg_package_exists',
                                        return_value=None):
        unmet, met = _run()
    assert len(unmet) == 1, "중복제거가 깨졌다"
    assert met is False, "미설치인데 met_deps 가 켜졌다"


def test_apt_present_is_met():
    with only([APT]), patch.object(utils_general, 'dpkg_package_exists',
                                   return_value=True):
        unmet, met = _run()
    assert unmet == []
    assert met is True


# ---------------------------------------------------------------------------
# bash-commands
# ---------------------------------------------------------------------------

def test_bash_commands_all_files_present_is_met(tmp_path):
    """파일이 전부 있으면 충족으로 잡혀야 한다(회귀 2)."""
    f = tmp_path / "present.js"
    f.write_text("x")
    with only([('bash-commands', [str(f)], ['true'])]):
        unmet, met = _run()
    assert unmet == []
    assert met is True, "bash-commands 충족이 met_deps 에 반영되지 않았다"


def test_bash_commands_missing_twice_is_deduped(tmp_path):
    """같은 선언이 두 번 있어도 항목이 두 번 쌓이면 안 된다(회귀 3)."""
    missing = str(tmp_path / "missing.js")
    dep = ('bash-commands', [missing], ['true'])
    with only([dep, dep]):
        unmet, met = _run()
    assert len(unmet) == 1, f"중복제거 실패: {unmet}"
    assert met is False


# ---------------------------------------------------------------------------
# internal
# ---------------------------------------------------------------------------

def test_internal_file_exists_present_is_met(tmp_path):
    f = tmp_path / "flag"
    f.write_text("x")
    with only([('internal', f'file-exists {f}', 'thing')]):
        unmet, met = _run()
    assert unmet == []
    assert met is True


def test_internal_file_exists_missing_twice_stays_unmet(tmp_path):
    missing = tmp_path / "absent"
    dep = ('internal', f'file-exists {missing}', 'thing')
    with only([dep, dep]):
        unmet, met = _run()
    assert len(unmet) == 1
    assert met is False, "파일이 없는데 met_deps 가 켜졌다"


def test_internal_apt_passes_bare_package_name_to_dpkg():
    """'apt <이름>' 을 통째로 넘기면 dpkg 가 'apt' 를 보고 늘 설치됐다고 한다(회귀 4)."""
    with only([('internal', 'apt zzz-pkg', 'zzz-pkg')]), \
            patch.object(utils_general, 'dpkg_package_exists',
                         return_value=None) as dpkg:
        unmet, met = _run()
    dpkg.assert_called_once_with('zzz-pkg')
    assert len(unmet) == 1
    assert met is False


# ---------------------------------------------------------------------------
# met_deps 의 출처
# ---------------------------------------------------------------------------

def test_empty_dependencies_module_is_met():
    """선언된 의존성이 없으면 충족할 것도 없다."""
    with only([]):
        unmet, met = _run()
    assert unmet == []
    assert met is True


def test_unrelated_empty_field_does_not_set_met(tmp_path):
    """dependencies_module 이 아닌 빈 필드가 met_deps 를 켜면 안 된다."""
    missing = str(tmp_path / "missing.js")
    with only([('bash-commands', [missing], ['true'])],
              extra_fields={'measurements_use_same_timestamp': False,
                            'options_disabled': []}):
        unmet, met = _run()
    assert len(unmet) == 1
    assert met is False, "무관한 빈 필드가 met_deps 를 켰다"


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-v']))
