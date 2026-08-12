# coding=utf-8
"""드라이버 pip 핀 ↔ `requirements.txt` 드리프트 가드.

드라이버는 자기 의존성을 `dependencies_module` 에 직접 선언한다:

    'dependencies_module': [('pip-pypi', 'requests', 'requests==2.31.0')]

그리고 `return_dependencies()`(`aot_flask/utils/utils_general.py`)는 이 `==`
버전을 **설치본과 정확히 일치하는지** 비교한다(`required_version !=
installed_version` → version_mismatch). 그래서 `requirements.txt` 를 bump 하면
그 패키지를 선언한 드라이버가 **전부 조용히 "unmet dependencies" 가 된다.**

증상이 고약하다. 앱은 정상 기동하고 로그도 조용한데, 사용자가 그 장치를 웹
UI 에서 추가하려 하면 "has unmet dependencies" 만 뜨고 생성이 막힌다. 이미 만들어
둔 장치는 계속 돌기 때문에 한참 뒤 새 장치를 추가하려는 순간에야 드러나고,
그때는 원인이 된 bump 로부터 멀어져 있다.

두 번 났다(2026-08-10 하루에 둘 다 발견):

  requests  2.31.0 → 2.33.0   드라이버 10개  (th1x 3, ttn_data_storage 3,
                                             ecowitt, remote_output 2, remote_aot_input)
  Pillow    8.1.2  → 12.3.0   드라이버 13개  (ssd1306 8, ssd1309, amg8833,
                                             anyleaf 3)

requests 쪽은 원격 AoT 복합장치를 웹 UI 로 만들어 보다가 **하위 Input/Output 이
하나도 안 생기는 것**으로 발견했다. Pillow 쪽은 그 김에 전수 대조해서 찾았다.

**검사 범위 — `requirements.txt` 에 있는 패키지만 본다.** 하드웨어 라이브러리
(adafruit_*, luma.oled, Adafruit_GPIO 등 70여 종)는 `requirements.txt` 에 없고
필요할 때 on-demand 로 설치되므로, 선언된 버전이 정본이다. 그건 비교 대상이
아니다(설치돼 있으면 통과, 없으면 정상적으로 미충족으로 잡힌다).

**정적 검사다.** `aot.config` 도 Flask 도 import 하지 않고 소스만 AST 로 읽는다 —
설치가 깨지거나 하드웨어 라이브러리가 없어도 이 검사가 가려지지 않게.

버전을 올릴 때: `requirements.txt` 를 고쳤으면 같은 커밋에서 이 검사를 돌리고,
걸린 드라이버의 선언도 함께 올릴 것. **다만 메이저 버전이 뛴 경우 핀만 맞추면
안 된다** — Pillow 8→12 처럼 제거된 API 를 쓰고 있으면 게이트는 통과하되 런타임에
죽는다(그때는 실제 코드 경로를 돌려 확인했고 수정은 불필요했다).
"""
import ast
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
REQUIREMENTS = REPO / "requirements.txt"

#: 드라이버 모듈이 있는 디렉터리. 최상위 파일만 본다 — custom_* 하위 디렉터리는
#: 사용자가 넣는 것이라 레포의 requirements.txt 와 묶을 근거가 없다.
DRIVER_DIRS = (
    "aot/inputs",
    "aot/outputs",
    "aot/functions",
    "aot/widgets",
    "aot/actions",
    "aot/inputs_gis",
    "aot/devices",
)


def _normalize(name):
    """PEP 503 정규화 — `Pillow`/`pillow`, `foo_bar`/`foo-bar` 를 같게 본다."""
    return re.sub(r"[-_.]+", "-", name).lower()


#: 버전 지정자. `==` 를 `===` 보다 뒤에 두면 안 된다(먼저 걸리는 쪽이 이긴다).
_SPECIFIER_RE = re.compile(r"(===|==|>=|<=|~=|!=|<|>)")


def _requirements_pins():
    """requirements.txt 의 `pkg==ver` 핀을 {정규화이름: 버전} 으로."""
    pins = {}
    for raw in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        # 환경 마커(`; python_version < "3.11"`)와 줄끝 주석을 떼어낸다.
        line = line.split(";")[0].split("#")[0].strip()
        m = re.match(r"^([A-Za-z0-9_.\-]+)\s*==\s*([^\s]+)$", line)
        if m:
            pins[_normalize(m.group(1))] = m.group(2)
    return pins


def _requirements_ranges():
    """requirements.txt 가 **범위**로 잡은 패키지 → {정규화이름: 지정자 전체}.

    `==` 로 고정하지 않은 것들이다(`scipy>=1.7.0` 등). `_requirements_pins()`
    는 `==` 만 읽으므로 이 부류를 아예 못 본다 — 그 사각지대가 실제로
    `scipy==1.8.0` 을 살려 뒀다. 드라이버가 범위 패키지를 `==` 로 고정하면
    설치본이 그 값과 다른 순간 그 장치는 웹 UI 에서 추가할 수 없게 된다.
    """
    ranges = {}
    for raw in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        line = line.split(";")[0].split("#")[0].strip()
        match = _SPECIFIER_RE.search(line)
        if not match or line[match.start():match.end()] == "==":
            continue
        ranges[_normalize(line[:match.start()].strip())] = line[match.start():]
    return ranges


def _declared_pins():
    """드라이버가 선언한 pip 핀 목록.

    `('pip-pypi', <module>, '<pkg>==<ver>')` 3-튜플만 걷는다. `pip-git`/`apt`
    같은 다른 설치 방식과, `==` 없는 선언(버전 미고정)은 비교 대상이 아니다.
    """
    found = []
    for rel in DRIVER_DIRS:
        for path in sorted((REPO / rel).glob("*.py")):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):  # pragma: no cover
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Tuple) or len(node.elts) != 3:
                    continue
                parts = [e.value for e in node.elts
                         if isinstance(e, ast.Constant) and isinstance(e.value, str)]
                if len(parts) != 3 or parts[0] != "pip-pypi":
                    continue
                install_id = parts[2]
                if "==" not in install_id:
                    continue
                pkg, _sep, version = install_id.partition("==")
                # `Pillow[extra]==x` 형태의 extras 는 이름에서 떼어낸다.
                pkg = pkg.split("[")[0].strip()
                found.append((path.relative_to(REPO).as_posix(), pkg, version))
    return found


def test_requirements_has_pins():
    """검사 자체가 무력화되지 않았는지 — 핀을 하나도 못 읽으면 전부 통과해버린다."""
    assert len(_requirements_pins()) > 50


def test_drivers_declare_pins():
    """드라이버 선언을 하나도 못 걷으면 이 검사는 아무것도 지키지 않는다."""
    assert len(_declared_pins()) > 50


def test_driver_pip_pins_match_requirements():
    """requirements.txt 가 고정한 패키지는 드라이버 선언도 같은 버전이어야 한다.

    어긋나면 `return_dependencies()` 가 그 드라이버를 '의존성 미충족' 으로 판정해
    웹 UI 에서 추가할 수 없게 된다.
    """
    pins = _requirements_pins()
    drift = []
    for rel_path, pkg, declared in _declared_pins():
        pinned = pins.get(_normalize(pkg))
        if pinned is not None and pinned != declared:
            drift.append((rel_path, pkg, declared, pinned))

    if drift:
        lines = [
            "드라이버 pip 핀이 requirements.txt 와 어긋납니다. 어긋난 드라이버는",
            "웹 UI 에서 '의존성 미충족' 으로 추가가 막힙니다.",
            "",
        ]
        for rel_path, pkg, declared, pinned in sorted(drift):
            lines.append(
                f"  {rel_path}: {pkg}=={declared}  →  requirements.txt 는 {pinned}")
        lines += [
            "",
            "고치는 법: 각 드라이버의 dependencies_module 선언을 requirements.txt 의",
            "버전으로 맞추세요. 메이저 버전이 뛴 경우에는 핀만 맞추지 말고 그 드라이버가",
            "실제로 쓰는 API 가 살아 있는지 런타임으로 확인할 것.",
        ]
        pytest.fail("\n".join(lines))


def test_drivers_do_not_pin_what_requirements_leaves_open():
    """requirements.txt 가 범위로 둔 패키지를 드라이버가 `==` 로 굳히면 안 된다.

    위 검사는 `==` 로 고정된 것만 대조하므로 이 부류를 못 본다. 그런데 결과는
    같다 — 오히려 더 조용하다. requirements.txt 가 `scipy>=1.7.0` 이면 설치본은
    해결된 최신 버전이고, 드라이버가 `scipy==1.8.0` 을 선언하면
    `return_dependencies()` 의 정확일치 비교가 version_mismatch 를 내서 그
    장치(anyleaf pH/ORP/EC)를 웹 UI 에서 추가할 수 없게 된다. 어디에도 에러는
    남지 않고 그냥 "의존성 미충족" 으로만 보인다.

    드라이버는 requirements.txt 와 **같은 지정자 형태**를 쓰면 된다. `==` 가
    없으면 `return_dependencies()` 는 버전 비교 자체를 하지 않는다.
    """
    ranges = _requirements_ranges()
    frozen = []
    for rel_path, pkg, declared in _declared_pins():
        spec = ranges.get(_normalize(pkg))
        if spec is not None:
            frozen.append((rel_path, pkg, declared, spec))

    if frozen:
        lines = [
            "requirements.txt 가 범위로 둔 패키지를 드라이버가 `==` 로 고정했습니다.",
            "설치본이 그 값과 달라지는 순간 그 장치는 웹 UI 에서 추가가 막힙니다.",
            "",
        ]
        for rel_path, pkg, declared, spec in sorted(frozen):
            lines.append(
                f"  {rel_path}: {pkg}=={declared}  →  requirements.txt 는 {pkg}{spec}")
        lines += [
            "",
            "고치는 법: 드라이버 선언을 requirements.txt 와 같은 형태로 두세요",
            "(예: `('pip-pypi', 'scipy', 'scipy>=1.7.0')`).",
        ]
        pytest.fail("\n".join(lines))
