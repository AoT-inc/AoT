# coding=utf-8
"""MCPBridgeService._heal_aot_script_path — 죽은 MCP 스크립트 경로 자가복구.

`mcp_servers.command` 는 create_app() 이 매 기동마다 자기 설치 경로로 덮어쓰는
**공유 한 줄**이다. 다른 체크아웃(워크트리·임시 복사본)에서 앱을 한 번 띄우면
그 경로가 박히고, 그 뒤 모든 spawn 이 `can't open file` 로 죽는다.
2026-08-10 사람이 예약한 릴레이가 정각에 이 이유로 실패했다.
"""
import os

from aot.ai.services import mcp_bridge_service
from aot.ai.services.mcp_bridge_service import MCPBridgeService


class _FakeServer(object):
    def __init__(self, command):
        self.command = command
        self.name = 'AoT System Expert Server'


def _real_script(tmp_path):
    root = tmp_path / 'app'
    (root / 'aot').mkdir(parents=True)
    script = root / 'aot' / 'aot_mcp_server.py'
    script.write_text('# stub\n')
    return str(root), str(script)


def test_stale_script_path_is_repointed(tmp_path):
    root, script = _real_script(tmp_path)
    server = _FakeServer('/usr/local/bin/python /tmp/wt3/aot/aot_mcp_server.py')

    healed = MCPBridgeService._heal_aot_script_path(server, server.command, root)

    assert healed.endswith(script)
    assert '/tmp/wt3' not in healed


def test_live_path_is_left_alone(tmp_path):
    root, script = _real_script(tmp_path)
    cmd = '%s %s' % ('/usr/bin/env python', script)
    server = _FakeServer(cmd)

    assert MCPBridgeService._heal_aot_script_path(server, cmd, root) == cmd


def test_dead_absolute_interpreter_falls_back_to_sys_executable(tmp_path):
    import sys
    root, script = _real_script(tmp_path)
    cmd = '/nonexistent/venv/bin/python %s' % script
    server = _FakeServer(cmd)

    healed = MCPBridgeService._heal_aot_script_path(server, cmd, root)

    assert healed == '%s %s' % (sys.executable, script)


def test_bare_interpreter_name_is_not_rewritten(tmp_path):
    """`python` 은 셸이 PATH 로 푼다 — 절대경로가 아니면 건드리지 않는다."""
    root, script = _real_script(tmp_path)
    cmd = 'python %s' % script
    server = _FakeServer(cmd)

    assert MCPBridgeService._heal_aot_script_path(server, cmd, root) == cmd


def test_external_mcp_command_is_untouched(tmp_path):
    """외부 MCP 의 깨진 커맨드는 운영자의 몫이다 — 경로를 지어내지 않는다."""
    root, _ = _real_script(tmp_path)
    cmd = 'npx -y @modelcontextprotocol/server-filesystem /srv/data'
    server = _FakeServer(cmd)

    assert MCPBridgeService._heal_aot_script_path(server, cmd, root) == cmd


def test_install_directory_is_the_second_candidate(tmp_path, monkeypatch):
    """project_root 에 없으면 INSTALL_DIRECTORY 로 한 번 더 찾는다."""
    install, script = _real_script(tmp_path)
    monkeypatch.setattr(mcp_bridge_service, 'INSTALL_DIRECTORY', install)
    empty_root = str(tmp_path / 'empty')
    os.makedirs(empty_root)
    cmd = '/usr/local/bin/python /tmp/wt3/aot/aot_mcp_server.py'

    healed = MCPBridgeService._heal_aot_script_path(_FakeServer(cmd), cmd, empty_root)

    assert healed.endswith(script)


def test_no_candidate_anywhere_leaves_command_alone(tmp_path, monkeypatch):
    """고칠 대상을 못 찾으면 조용히 바꾸지 말고 원래대로 실패하게 둔다."""
    empty_root = str(tmp_path / 'empty')
    os.makedirs(empty_root)
    monkeypatch.setattr(mcp_bridge_service, 'INSTALL_DIRECTORY', empty_root)
    cmd = '/usr/local/bin/python /tmp/wt3/aot/aot_mcp_server.py'
    server = _FakeServer(cmd)

    assert MCPBridgeService._heal_aot_script_path(server, cmd, empty_root) == cmd
