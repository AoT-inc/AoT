# coding=utf-8
"""업그레이드 스크립트가 aotflask 를 멈추면서 스스로 죽지 않게 지키는 회귀 가드.

웹 화면의 업그레이드는 스크립트를 aotflask 서비스의 자식으로 띄운다. 스크립트가
`systemctl stop aotflask` 를 하면 같은 cgroup 의 스크립트도 함께 죽는다(aot-005,
26.11.2 업그레이드: env 가 /tmp 에 남고 서비스는 꺼진 채 멈춤).
"""
import subprocess
from pathlib import Path

UPGRADE = Path(__file__).resolve().parents[2] / "aot" / "scripts" / "upgrade_install.sh"


def test_syntax_is_valid():
    subprocess.run(["bash", "-n", str(UPGRADE)], check=True)


def test_detaches_into_own_scope_before_stopping_aotflask():
    text = UPGRADE.read_text(encoding="utf-8")
    guard = text.index('[ -z "$AOT_UPGRADE_DETACHED" ]')
    scope = text.index("systemd-run --scope --quiet --collect --unit")
    stop = text.index("systemctl stop aotflask aotmcp")
    call = text.rindex("\nrunSelfUpgrade")
    assert guard < scope < stop, "분리는 서비스를 멈추는 줄보다 앞서야 한다"
    assert scope < call
    # 서비스 안의 파이프(tee)로 출력하지 않고 로그 파일에 직접 쓴다
    assert "/tmp/aotupgrade.log" in text
    assert "pipefail" in text  # 안쪽 스크립트의 종료 코드를 잃지 않는다


def test_502_page_is_static_not_a_jinja_template():
    # nginx 가 파일을 그대로 내보내므로 렌더링되지 않는 `{{ }}`·`{% %}` 가 남아 있으면 화면에 그대로 보인다
    page = (UPGRADE.parents[1] / "aot_flask" / "templates" / "502.html").read_text(encoding="utf-8")
    assert "{{_(" not in page.replace(" ", "")
    assert "{%" not in page
    assert 'http-equiv="refresh"' in page  # 서비스가 돌아오면 스스로 평소 화면으로
