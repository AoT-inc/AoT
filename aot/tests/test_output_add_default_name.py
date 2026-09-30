# coding=utf-8
"""새 출력의 기본 이름 — 모듈의 짧은 이름/이름에서 가져온다.

입력은 `input_name_short` → `input_name` 으로 기본 이름을 정하는데, 출력은
`"Name"` 글자를 그대로 넣어 카드 머리글·알림에 "Name" 이 그대로 나왔다.
"""
import unittest
from types import SimpleNamespace


class OutputAddDefaultNameTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from flask import Flask
        from flask_babel import Babel
        from aot.aot_flask.extensions import db
        from aot.config import AOT_DB_PATH
        import aot.databases.models  # noqa: F401

        cls.app = Flask(__name__)
        cls.app.config['SQLALCHEMY_DATABASE_URI'] = AOT_DB_PATH
        cls.app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        cls.app.config.setdefault('SECRET_KEY', 'output-name-test')
        cls.app.config['TESTING'] = True
        db.init_app(cls.app)
        cls.db = db
        Babel(cls.app)

    def setUp(self):
        self.ctx = self.app.app_context()
        self.ctx.push()
        self.db.session.rollback()
        self.created = []

    def tearDown(self):
        from aot.databases.models import Output, OutputChannel
        self.db.session.rollback()
        for oid in self.created:
            OutputChannel.query.filter(OutputChannel.output_id == oid).delete()
            Output.query.filter(Output.unique_id == oid).delete()
        self.db.session.commit()
        self.ctx.pop()

    def _add(self, output_type):
        from aot.aot_flask.utils import utils_output
        from aot.databases.models import Output
        form = SimpleNamespace(output_type=SimpleNamespace(data=output_type + ','))
        msgs = utils_output.output_add(form, {})[0]
        row = Output.query.filter(Output.output_type == output_type).order_by(
            Output.id.desc()).first()
        self.assertIsNotNone(row, msgs)
        self.created.append(row.unique_id)
        return row

    def test_default_name_comes_from_module(self):
        from aot.aot_flask.utils.utils_output import parse_output_information
        info = parse_output_information()['virtual_on_off_single']
        expected = str(info.get('output_name_short') or info['output_name'])
        row = self._add('virtual_on_off_single')
        self.assertEqual(row.name, expected)
        self.assertNotEqual(row.name, 'Name')
