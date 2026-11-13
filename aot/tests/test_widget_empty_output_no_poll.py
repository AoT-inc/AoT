# coding=utf-8
"""출력을 고르지 않은 출력 값·PWM 위젯이 빈 주소로 폴링·명령하지 않는가.

## 왜 이 테스트가 있나

출력 칸이 빈 위젯은 템플릿이 장치·채널 ID 를 빈 문자열로 넘긴다. 예전에는 그래도
`start()` 가 폴링을 시작해 `/outputstate_unique_id//`·`/output_target_pct//` 같은
빈 주소를 갱신마다 불렀고, 대시보드 콘솔이 404 로 찼다(2026-11-12 맥북 8084, 맥미니 DB
복제본의 '액추에이터 위치' 위젯). 타이머 위젯은 템플릿에서, 인디케이터는 입력이 맞을
때만 시작해 이미 막혀 있었다 — 이 둘만 빠져 있었다.

위젯의 실제 JS 를 node 로 돌려, 빈 ID 면 요청이 0건이고 ID 가 있으면 예전처럼 부르는지 본다.
"""
import json
import shutil
import subprocess

import jinja2
import pytest

from aot.widgets import AoT_output_pwm, AoT_output_value

pytestmark = pytest.mark.skipif(not shutil.which('node'), reason='node 필요')

_HARNESS = r"""
const calls = [];
const el = () => ({ dataset: {}, textContent: '', value: '', classList: { add() {}, remove() {}, toggle() {} } });
global.window = {};
global.document = { getElementById: () => el(), activeElement: null };
global.toastr = { success() {}, error() {} };
const rec = (kind) => (url, a, b) => {
  calls.push(kind + ' ' + (typeof url === 'string' ? url : (url && url.url)));
  const p = { fail() { return p; }, done() { return p; } };
  return p;
};
global.$ = { getJSON: rec('GET'), ajax: rec('AJAX'), post: rec('POST') };
global.setInterval = () => 1;
global.clearInterval = () => {};
eval(process.argv[1]);
const api = window[process.argv[2]];
const args = JSON.parse(process.argv[3]);
api.start('w1', args.dev, args.ch, 5);
if (api.onCommand) api.onCommand('w1', args.dev, args.ch, 'open');
else api.onCommit('w1', args.dev, args.ch, 40);
console.log(JSON.stringify(calls));
"""


def _js(module):
    src = module.WIDGET_INFORMATION['widget_dashboard_js']
    return jinja2.Template(src).render(
        misc={'hide_alert_success': False, 'hide_alert_warning': False}, _=lambda x: x)


def _run(module, global_name, dev, ch):
    out = subprocess.run(
        ['node', '-e', _HARNESS, _js(module), global_name, json.dumps({'dev': dev, 'ch': ch})],
        capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


@pytest.mark.parametrize('module,global_name', [
    (AoT_output_value, 'AoTOutputValue'),
    (AoT_output_pwm, 'AoTOutputPWM'),
])
def test_empty_output_sends_no_request(module, global_name):
    calls = _run(module, global_name, '', '')
    assert calls == [], f'출력이 빈 위젯이 빈 주소로 요청했다: {calls}'


@pytest.mark.parametrize('module,global_name', [
    (AoT_output_value, 'AoTOutputValue'),
    (AoT_output_pwm, 'AoTOutputPWM'),
])
def test_configured_output_still_polls_and_commands(module, global_name):
    calls = _run(module, global_name, 'dev-1', 'ch-1')
    assert any('outputstate_unique_id/dev-1/ch-1' in c for c in calls), calls
    assert any('output_mod/dev-1/ch-1/' in c for c in calls), calls
    assert not any('//' in c.split(' ', 1)[1] for c in calls), calls
