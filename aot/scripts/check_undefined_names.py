#!/usr/bin/env python3
# coding=utf-8
"""
정의되지 않은 이름 검사 — 리팩터가 지역변수를 빠뜨린 것을 커밋 전에 잡는다.

## 왜

2026-08-04 `f0464ca2c` 가 `_run_cycle`(727줄)을 쪼개며 꼬리 작업을
`_finalize_cycle` 로 옮겼는데, **`cycle_sec` 하나를 넘기지 않았다.** 그 함수
안의 네 곳이 정의되지 않은 이름을 참조했고, greybox 그림자 단계가 매 사이클
`NameError` 로 죽었다. 예외는 `except Exception` 이 debug 로 삼켰고 기본 설치는
debug 를 남기지 않아 **8주 동안 아무 흔적이 없었다**(2026-09-28 발견).

그 사이 사라진 것: 1스텝 예측·오차 기록, 기상 구간별 KPI, 물리 모델 재학습.
전부 "제어를 물리 모델로 전환해도 되는가" 를 판정하는 근거라, 그림자를 아무리
오래 돌려도 게이트가 열릴 수 없는 상태였다. 앱은 정상 기동하고 테스트는
통과하며 화면에도 이상이 없다 — 이 계열의 실패는 **조용하다.**

`python3 -m pyflakes` 한 줄이면 즉시 드러나는 결함이었다. 그래서 검사로 만든다.

## 무엇을 보나

pyflakes 의 `undefined name` / `local variable ... referenced before assignment`
만 본다. 미사용 import 같은 스타일 지적은 보지 않는다 — 그것까지 막으면 잡음이
커져 아무도 안 보게 된다.

## 이미 있던 것(baseline)

기존 25건은 대부분 사용자 코드 템플릿(`python_code.py` 가 실행 시점에 주입하는
`sys` 등)이나 조건부 import 다. 이 검사가 막는 것은 **새로 생기는 것**이라,
기존 항목은 `_BASELINE` 에 파일별 이름으로 적어 두고 통과시킨다. 줄 번호는
적지 않는다 — 파일이 조금만 움직여도 전부 어긋난다.

⚠ `_BASELINE` 에 이름을 추가하는 것은 "괜찮다고 판단했다" 는 뜻이다. 근거 없이
늘리지 말 것. 진짜 결함이면 고치고 지운다.

    python3 aot/scripts/check_undefined_names.py            # 전체(aot/)
    python3 aot/scripts/check_undefined_names.py --staged   # 인덱스의 .py 만(훅)
    python3 aot/scripts/check_undefined_names.py --json
    python3 aot/scripts/check_undefined_names.py aot/functions   # 경로 지정

종료 0=정상, 1=새 항목 발견, 2=검사 실패(pyflakes 없음 등).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 파일(저장소 기준 상대경로) → 이미 있던 정의되지 않은 이름들.
# 2026-09-28 시점의 전수 조사 결과. 대부분 실행 시점에 주입되는 이름이다.
_BASELINE = {
    # 사용자가 쓴 파이썬 코드를 문자열로 실행하는 템플릿 — 이름은 실행 시 주입된다.
    'aot/inputs/python_code.py': {'sys'},
    'aot/inputs/python_code_v_2_0.py': {'sys'},
    'aot/outputs/python_code.py': {'sys'},
    'aot/outputs/on_off_python.py': {'sys'},
    'aot/outputs/pwm_python.py': {'sys'},
    # 조건부/지연 import 와 gettext 별칭.
    'aot/inputs/chirpstack_MQTT_jmespath.py': {'mqtt'},
    'aot/aot_flask/utils/utils_settings.py': {'_'},
    'aot/aot_flask/utils/utils_notes.py': {'_'},
    'aot/aot_flask/utils/utils_geo.py': {'config'},
    'aot/aot_flask/routes_ai_agent.py': {'custom_options'},
    'aot/services/cold_storage_service.py': {'Document'},
    'aot/inputs/atlas_ph.py': {'slope_return'},
    'aot/outputs/on_off_sparkfun_board_4_relays.py': {'dict_states'},
}

_WANTED = ('undefined name', 'referenced before assignment')


def _pyflakes_lines(paths):
    """pyflakes 출력 줄. 없으면 None(검사 불가)."""
    try:
        proc = subprocess.run([sys.executable, '-m', 'pyflakes', *paths],
                              cwd=REPO_ROOT, capture_output=True, text=True)
    except Exception:
        return None
    if proc.returncode not in (0, 1) and not proc.stdout:
        return None
    return proc.stdout.splitlines()


def _parse(line):
    """'경로:줄:열: undefined name 'x'' → (경로, 줄, 이름). 관심 밖이면 None."""
    if not any(w in line for w in _WANTED):
        return None
    head, _, msg = line.partition(': ')
    bits = head.split(':')
    if len(bits) < 2:
        return None
    path = os.path.relpath(os.path.join(REPO_ROOT, bits[0]), REPO_ROOT)
    name = msg.split("'")[1] if "'" in msg else msg.strip()
    return path, bits[1], name


def scan(paths):
    """(새 항목, 기존 항목) — 각 원소는 {'file','line','name','message'}."""
    lines = _pyflakes_lines(paths)
    if lines is None:
        return None, None
    fresh, known = [], []
    for line in lines:
        got = _parse(line)
        if not got:
            continue
        path, lineno, name = got
        item = {'file': path, 'line': lineno, 'name': name, 'message': line}
        (known if name in _BASELINE.get(path, set()) else fresh).append(item)
    return fresh, known


def _staged_py():
    out = subprocess.run(['git', 'diff', '--cached', '--name-only', '--diff-filter=ACMR'],
                         cwd=REPO_ROOT, capture_output=True, text=True).stdout
    return [f for f in out.split()
            if f.endswith('.py') and os.path.exists(os.path.join(REPO_ROOT, f))]


def main():
    ap = argparse.ArgumentParser(description='정의되지 않은 이름 검사')
    ap.add_argument('paths', nargs='*', default=None)
    ap.add_argument('--staged', action='store_true', help='인덱스의 .py 만 본다(훅)')
    ap.add_argument('--json', action='store_true')
    args = ap.parse_args()

    if args.staged:
        targets = _staged_py()
        if not targets:
            if not args.json:
                print('검사할 파이썬 파일이 스테이지에 없습니다.')
            return 0
    else:
        targets = args.paths or ['aot']

    fresh, known = scan(targets)
    if fresh is None:
        msg = ('pyflakes 를 실행할 수 없습니다 — `pip install pyflakes` 후 다시 '
               '돌리세요. (검사를 못 한 것이지 통과한 것이 아닙니다)')
        print(json.dumps({'status': 'unavailable', 'message': msg}) if args.json else msg,
              file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps({'new': fresh, 'baseline': known}, ensure_ascii=False, indent=2))
        return 1 if fresh else 0

    if not fresh:
        print('OK: 새로 생긴 정의되지 않은 이름 없음 (기존 %d건은 baseline).' % len(known))
        return 0

    print('정의되지 않은 이름 %d건 — 리팩터가 값을 빠뜨렸는지 확인하세요:' % len(fresh))
    for it in fresh:
        print('  %s' % it['message'])
    print('\n실행 중에는 그 자리에 닿을 때만 터지고, 예외를 삼키는 코드 안이면 '
          '아무 흔적도 남지 않습니다(2026-08-04 greybox 그림자 사고).')
    return 1


if __name__ == '__main__':
    sys.exit(main())
