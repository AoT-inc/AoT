# coding=utf-8
"""3-way(열기/닫기/정지) 액추에이터의 방향 판정.

`output.html` 인라인 스크립트의 회귀 가드. 2026-09-08 사용자 리포트 —
버튼이 custom_ui 색과 무관하게 항상 같은(회색) 모양으로 보인다는 지적을
쫓다가 실제로 확인했다: 밸브 위치가 100.0(완전히 열림)이라 행은
`active-background` 인데, 열기/닫기 버튼은 **둘 다** 회색이었다.

원인은 두 겹이었다.

1. 첫 수정(자체구동형 전용, `open_id`/`close_id` 가 아예 없는 경우만)은
   범위가 좁았다. 실측해 보니 **open_id/close_id 가 설정된, 훨씬 흔한
   경우**가 진짜 원인이었다 — 그 서브출력(릴레이)이 "움직이는 동안만
   on 을 보고하고 멈추면 off 로 돌아가는" 설계라, 정지 상태에서는
   openActive/closeActive 가 둘 다 false 로 나온다. 실측: 액추에이터
   자기 위치 100.0, 연결된 open/close 서브출력은 둘 다 "off".
2. 그래서 판정 기준을 "open_id/close_id 가 있는가" 에서 "실제로 어느
   쪽도 활성으로 안 나왔는가"(`!openActive && !closeActive`)로 넓혔다 —
   서브출력이 있든 없든, 답을 못 얻었으면 같은 fallback 을 쓴다.

`.aot-btn-on.aot-paired-inactive` 를 붙일지 말지는 `openActive`/`closeActive`
로 정해지므로, 이 파일은 실제 파일 텍스트에서 그 판정 블록을 **마커로
그대로 잘라** node 로 돌린다(재구현이 아니라 실물 검사 —
`test_output_state_classifier_js.py` 와 같은 방식).
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

HTML = (Path(__file__).resolve().parents[1] /
        'aot_flask' / 'templates' / 'pages' / 'output.html')

pytestmark = pytest.mark.skipif(
    shutil.which('node') is None, reason='node is required to run this block')


def _extract_block():
    text = HTML.read_text(encoding='utf-8')
    m = re.search(
        r'// @self-driven-direction-start.*?\n(.*?)// @self-driven-direction-end',
        text, re.S)
    assert m, ('output.html 에서 @self-driven-direction-start/-end 마커를 '
               '못 찾았다 — 판정 블록이 옮겨지거나 지워졌다')
    return m.group(1)


BLOCK = _extract_block()


def decide(lastDir, ownActive, ownSt, openActive=False, closeActive=False):
    """마커 블록을 실제 텍스트 그대로 node 에서 돌려 최종 openActive/closeActive 를 얻는다.

    openActive/closeActive 인자는 **서브출력 상태로 이미 정해진 값**이다
    (real code 에서는 openSt/closeSt 로부터 이 블록 앞에서 계산된다) —
    기본값 False 는 "서브출력이 없거나, 있어도 off 를 보고했다" 는 흔한
    경우를 흉내낸다.
    """
    own_st_js = 'null' if ownSt is None else json.dumps(ownSt)
    last_dir_js = 'null' if lastDir is None else json.dumps(lastDir)
    script = f"""
      var ownActive = {json.dumps(ownActive)};
      var ownSt = {own_st_js};
      var oid = 'dev', ch = '0';
      var pairedLastDirection = {{}};
      pairedLastDirection[oid + '-' + ch] = {last_dir_js};
      var openActive = {json.dumps(openActive)}, closeActive = {json.dumps(closeActive)};
      {BLOCK}
      console.log(JSON.stringify({{openActive: openActive, closeActive: closeActive}}));
    """
    proc = subprocess.run(['node', '-e', script],
                          capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_fresh_load_no_click_memory_still_shows_open():
    """회귀 그 자체: 클릭 기록 없이 새로 열어도 위치가 양수면 열기가 켜진다."""
    got = decide(lastDir=None, ownActive=True, ownSt=45)
    assert got == {'openActive': True, 'closeActive': False}, got


def test_configured_relays_reporting_off_still_shows_open():
    """실측 재현: open_id/close_id 서브출력이 있어도 둘 다 off 를 보고하면
    (릴레이가 움직일 때만 on 을 유지하는 설계) 같은 fallback 을 쓴다.
    액추에이터 자체 위치는 100.0(완전 개방), 서브출력 둘 다 'off' 였다."""
    got = decide(lastDir=None, ownActive=True, ownSt=100.0,
                openActive=False, closeActive=False)
    assert got == {'openActive': True, 'closeActive': False}, got


def test_relay_that_does_report_active_is_not_overridden():
    """서브출력이 실제로 활성을 보고했다면(드문 설계지만 가능) 그 값을
    존중한다 — fallback 은 "둘 다 모른다" 일 때만 끼어든다."""
    got = decide(lastDir=None, ownActive=True, ownSt=100.0,
                openActive=True, closeActive=False)
    assert got == {'openActive': True, 'closeActive': False}, got


def test_fresh_load_fully_closed_stays_neutral():
    """완전히 닫힌 상태(False)는 둘 다 켜지지 않는다 — 조용한 기본값이 맞다."""
    got = decide(lastDir=None, ownActive=False, ownSt=False)
    assert got == {'openActive': False, 'closeActive': False}, got


def test_click_memory_wins_over_position_when_present():
    """이번 세션에서 정지 중간에 눌렀다면(위치>0인데 마지막 클릭은 닫기)
    클릭 기록이 위치 추정보다 우선해야 한다."""
    got = decide(lastDir='close', ownActive=True, ownSt=30)
    assert got == {'openActive': False, 'closeActive': True}, got


def test_click_memory_open_still_works():
    got = decide(lastDir='open', ownActive=True, ownSt=80)
    assert got == {'openActive': True, 'closeActive': False}, got
