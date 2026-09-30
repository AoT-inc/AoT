# coding=utf-8
"""이메일 알림 경로 8건 수정 확인(2026-09-25).

실제 메일 계정·라이브 DB 를 쓰지 않는다. 진짜 SMTP 대화는 이 파일 안의 임시
로컬 SMTP 서버(127.0.0.1, 무암호·무로그인)로 받고, DB 조회는 패치한다.
"""
import socketserver
import threading
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from aot.controllers.base_conditional import AbstractConditional
from aot.utils.send_data import send_email


class _Handler(socketserver.StreamRequestHandler):
    def _send(self, line):
        self.wfile.write((line + "\r\n").encode())

    def handle(self):
        self._send("220 test")
        data_mode, buf = False, []
        while True:
            line = self.rfile.readline()
            if not line:
                return
            text = line.decode(errors="replace")
            if data_mode:
                if text.strip() == ".":
                    self.server.mails.append("".join(buf))
                    data_mode, buf = False, []
                    self._send("250 ok")
                else:
                    buf.append(text)
                continue
            cmd = text.strip().upper()
            if cmd.startswith("EHLO") or cmd.startswith("HELO"):
                self._send("250 test")
            elif cmd.startswith("DATA"):
                data_mode = True
                self._send("354 go")
            elif cmd.startswith("QUIT"):
                self._send("221 bye")
                return
            else:
                self._send("250 ok")


@pytest.fixture
def smtp_server():
    class _Server(socketserver.ThreadingTCPServer):
        allow_reuse_address = True
        daemon_threads = True
    srv = _Server(("127.0.0.1", 0), _Handler)
    srv.mails = []
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()
    srv.server_close()


def _smtp_row(port):
    return SimpleNamespace(host="127.0.0.1", protocol="unencrypted_no_login",
                           port=port, user="u", passw="p", email_from="a@b.c")


# 1. run_action(message=X) 가 액션까지 전달된다
class _FakeControl:
    def __init__(self):
        self.calls = []

    def trigger_action(self, action_id, value=None, debug=False):
        self.calls.append((action_id, value))
        return {}


def test_run_action_forwards_message_override():
    cond = AbstractConditional(logger=Mock(), function_id="f", message="기본")
    cond.control = _FakeControl()
    cond.run_action("A" * 36, message="덮어쓴 문구")
    assert cond.control.calls[0][1]["message"] == "덮어쓴 문구"
    cond.run_action("A" * 36)
    assert cond.control.calls[1][1]["message"] == "기본"


# 2·3. Send Email 액션: 실패를 메시지에 드러내고 SMTP 미설정도 dict 를 돌려준다
def _email_action(email="x@y.z"):
    from aot.actions import email as mod
    inst = mod.ActionModule.__new__(mod.ActionModule)
    inst.email = email
    inst.logger = Mock()
    return mod, inst


def test_email_action_success_and_failure(smtp_server):
    mod, inst = _email_action()
    with patch.object(mod, "check_allowed_to_email", return_value=(0, True)), \
            patch.object(mod, "db_retrieve_table_daemon",
                         return_value=_smtp_row(smtp_server.server_address[1])):
        out = inst.run_action({"message": "경보"})
    assert "Email 'x@y.z'." in out["message"] and "Error" not in out["message"]
    assert len(smtp_server.mails) == 1

    # 닫힌 포트로 보내면 실패가 메시지에 남고 logger.error 가 불린다
    mod, inst = _email_action()
    with patch.object(mod, "check_allowed_to_email", return_value=(0, True)), \
            patch.object(mod, "db_retrieve_table_daemon",
                         return_value=_smtp_row(1)):
        out = inst.run_action({"message": "경보"})
    assert "failed to send" in out["message"]
    assert "Email 'x@y.z'." not in out["message"]
    assert inst.logger.error.called


def test_email_action_smtp_unreadable_returns_dict():
    mod, inst = _email_action()
    with patch.object(mod, "check_allowed_to_email", return_value=(0, True)), \
            patch.object(mod, "db_retrieve_table_daemon", return_value=None):
        out = inst.run_action({"message": "경보"})
    assert isinstance(out, dict) and "SMTP settings" in out["message"]


def test_email_action_hourly_limit_is_visible():
    mod, inst = _email_action()
    with patch.object(mod, "check_allowed_to_email", return_value=(9e12, False)):
        out = inst.run_action({"message": "경보"})
    assert "hourly limit" in out["message"]


# 5. 포트를 비워도 프로토콜 기본 포트로 보낸다(send_email 의 기본 포트 규칙)
def test_send_email_blank_port_falls_back_to_protocol_default():
    with patch("aot.utils.send_data.smtplib.SMTP") as smtp_cls:
        smtp_cls.return_value.sendmail.return_value = {}
        rc = send_email("h", "unencrypted_no_login", None, "u", "p", "a@b.c",
                        "t@b.c", "x")
    assert rc == 0 and smtp_cls.call_args[0][1] == 25


def test_password_reset_no_longer_requires_port():
    import inspect
    from aot.aot_flask import routes_password_reset
    src = inspect.getsource(routes_password_reset)
    assert "smtp.protocol and smtp.port" not in src


# 6. 안 쓰는 smtp_ssl 폼 필드 제거
def test_unused_smtp_ssl_field_removed():
    from aot.aot_flask.forms.forms_settings import SettingsEmail
    assert not hasattr(SettingsEmail, "smtp_ssl")


# 7. 조건 종류 라벨은 표시 시점에 번역된다
def test_conditional_condition_labels_are_lazy():
    from aot.config import CONDITIONAL_CONDITIONS
    label = dict(CONDITIONAL_CONDITIONS)["measurement"]
    assert not isinstance(label, str)   # LazyString: import 시점에 굳지 않았다
    assert "(" in str(label)


# 8. ko 번역에서 "Error" 가 살아 있다
def test_ko_error_messages():
    from babel.messages.pofile import read_po
    with open("aot/aot_flask/translations/ko/LC_MESSAGES/messages.po", "rb") as fh:
        cat = read_po(fh)
    assert cat.get("Error: Data not found.").string == "오류: 데이터를 찾을 수 없습니다"
    assert cat.get("Error: No data for the last %(period)s seconds").string.startswith("오류:")
    for k in ("Send Email", "Send Email with Photo", "E-Mail Address", "with Timestamp"):
        assert cat.get(k).string
