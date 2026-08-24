# coding=utf-8
"""
프로그램 승인 면제의 안전 계약 (2026-08-24).

프로그램은 제어가 아니라 **제어에 영향을 주는 참고자료**다. 장치를 직접 움직이지
않고 오래 두고 보는 문서라, 만들 때마다 승인을 받게 하면 마찰만 남는다 —
그래서 `create_program`·`modify_program` 에서 승인을 뗐다(사용자 결정).

**뗄 수 있었던 이유는 위험이 작아서가 아니라 더 강한 게이트가 뒤에 있어서다.**
그 게이트가 사라지면 승인 면제는 곧바로 위험해진다: AI 가 지어낸 단계 기간과
목표 온도가 아무 사람도 거치지 않고 온실 설정이 된다.

그래서 이 파일은 **두 사실을 한자리에 묶는다** — "승인이 없다" 와 "제어에 못
닿는다". 둘 중 하나만 바꾸면 여기서 깨진다. 승인을 되살리든 검토 게이트를
지키든, 그 판단을 사람이 하게 만드는 것이 이 테스트의 일이다.
"""
import os
import sys
import unittest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir, os.path.pardir)))
os.environ["ALEMBIC_RUNNING"] = "1"

from flask import Flask
from flask_babel import Babel

from aot.aot_flask.extensions import db
from aot.ai.services import tool_registry as registry


def _make_test_app():
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['TESTING'] = True
    db.init_app(app)
    Babel(app)
    return app


class TestProgramApprovalContract(unittest.TestCase):

    def test_program_authoring_tools_are_not_approval_gated(self):
        from aot.ai.services.ai_action_service import AIActionService
        for name in ('create_program', 'modify_program'):
            self.assertFalse(AIActionService.requires_approval(name),
                             '%s 가 다시 승인 대상이 됐다 — 참고자료를 만드는 데 '
                             '승인을 받게 하면 마찰만 남는다는 결정을 되돌리는 '
                             '것이라면, 이 테스트도 함께 고칠 것' % name)

    def test_deleting_a_programme_is_still_gated(self):
        """삭제는 복구 불가라 _CONFIG_ONLY 금지 조항에 걸린다."""
        from aot.ai.services.ai_action_service import AIActionService
        self.assertTrue(AIActionService.requires_approval('delete_program'))

    def test_the_tools_declare_config_only_not_plain_ungated(self):
        """`config_only` 는 '쓰기이지만 승인 면제' 를 뜻한다 — 역할 검사와 감사는
        그대로 남는다. 플래그를 통째로 지우면 그것까지 잃는다."""
        for name in ('create_program', 'modify_program'):
            t = registry._BY_NAME[name]
            self.assertTrue(t.config_only, '%s 에 config_only 선언이 없다' % name)
            self.assertFalse(t.physical, '%s 는 물리 제어가 아니다' % name)

    def test_an_ai_written_programme_cannot_drive_control_until_a_person_checks_it(self):
        """승인을 뗀 근거 그 자체. 이것이 깨지면 AI 가 지어낸 목표 온도가
        아무 사람도 거치지 않고 온실 설정이 된다."""
        app = _make_test_app()
        with app.app_context():
            db.create_all()
            try:
                from aot.aot_flask.geo import program_io
                from aot.databases.models import GeoProgram
                row, err = program_io.create_program({
                    'name': '테스트 프로그램', 'subject': '무', 'kind': 'vegetation',
                    'source_note': '테스트',
                    'stages': [{'key': 'a', 'name': '가', 'days': 10,
                                'targets': {'temp_day': 20}}],
                }, source='ai')
                self.assertIsNone(err, err)
                saved = GeoProgram.query.filter_by(subject='무').first()
                self.assertEqual('ai', saved.source)
                self.assertIsNone(saved.reviewed_at)
                self.assertFalse(
                    saved.usable_for_control(),
                    'AI 가 쓴 프로그램이 사람 확인 없이 제어에 쓰인다 — 승인을 뗀 '
                    '전제가 무너졌다. 승인 게이트를 되살리거나 이 게이트를 고칠 것')
            finally:
                db.session.remove()
                db.drop_all()

    def test_the_ai_cannot_mark_its_own_programme_reviewed(self):
        """검토를 AI 가 세울 수 있으면 게이트가 없는 것과 같다."""
        app = _make_test_app()
        with app.app_context():
            db.create_all()
            try:
                from aot.aot_flask.geo import program_io
                from aot.databases.models import GeoProgram
                row, err = program_io.create_program({
                    'name': 'T', 'subject': '무', 'kind': 'vegetation',
                    'source_note': 'x',
                    'stages': [{'key': 'a', 'name': '가', 'days': 10}],
                }, source='ai')
                self.assertIsNone(err, err)
                saved = GeoProgram.query.filter_by(subject='무').first()
                program_io.update_program(saved.unique_id, {'reviewed': True}, by='ai')
                db.session.expire_all()
                again = GeoProgram.query.filter_by(subject='무').first()
                self.assertIsNone(again.reviewed_at,
                                  'AI 가 스스로 검토 완료로 만들 수 있다')
            finally:
                db.session.remove()
                db.drop_all()


if __name__ == '__main__':
    unittest.main()
