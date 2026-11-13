# coding=utf-8
"""opencv 는 headless 하나만 쓴다 — requirements 의 핀과 코드의 설치 선언이 같아야 한다.

`opencv-python` 과 `opencv-python-headless` 는 같은 `cv2` 모듈을 제공해서 함께 깔리면 서로 덮어쓴다.
컨테이너에는 GUI 라이브러리가 없어 non-headless 가 덮으면 import 가 깨질 수 있다.
(`library: 'opencv-python'` 은 DB 에 저장된 카메라 종류 값이라 바꾸지 않는다 — pip 사양만 본다.)
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_SPEC = re.compile(r"'(opencv-python[^']*)'")


def _pinned():
    for line in (ROOT / 'requirements.txt').read_text().splitlines():
        if line.startswith('opencv-python-headless=='):
            return line.strip()
    raise AssertionError('requirements.txt 에 opencv-python-headless 핀이 없다')


def test_every_pip_spec_is_the_pinned_headless_package():
    pin = _pinned()
    bad = []
    for path in (ROOT / 'aot').rglob('*.py'):
        if 'tests' in path.parts:
            continue
        for n, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
            if "'cv2'" not in line:
                continue
            m = _SPEC.search(line)
            if m and m.group(1) != pin:
                bad.append(f'{path.relative_to(ROOT)}:{n} {m.group(1)}')
    assert not bad, f'requirements 의 {pin} 와 다른 opencv 설치 선언: {bad}'
