# coding=utf-8
"""AI `create_output` — 성공 판정은 `new_id`, `messages["error"]` 가 아니다.

`output_add()` 는 Output(과 그 채널 행)을 이미 커밋한 **뒤에** 에러를 덧붙일 수
있다 — 가장 흔한 경로는 저장 후 `manipulate_output('Add', ...)` 의 데몬 리로드
알림이다(데몬 바쁨/재시작 중/응답 없음). 이 테스트가 재현하는 상황이 정확히
그것이다: 테스트 환경엔 데몬이 없으니 이 알림은 **항상** 실패한다.

`create_output` 이 `messages["error"]` 를 `new_id` 보다 먼저 보면, 채널까지
멀쩡히 생긴 출력을 "실패" 로 보고한다 — 호출자(AI)는 다시 만들어야 한다고
믿고 재시도하고, 실제로는 이미 있는 출력에 하나가 더 늘어난다.
2026-09-08, ChirpStack gRPC 출력 20개가 채널 없이 남아 있는 것을 조사하다가
발견했다(그 20개 자체의 원인은 아니었다 — 이 재현에서도 채널은 정상 생성된다 —
但 별개로 실재하는 결함이라 고쳤다).
"""
import unittest


class CreateOutputSuccessVsErrorTest(unittest.TestCase):
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
        cls.app.config.setdefault('SECRET_KEY', 'create-output-test')
        db.init_app(cls.app)
        cls.db = db
        Babel(cls.app)

    def setUp(self):
        self.ctx = self.app.app_context()
        self.ctx.push()
        self.db.session.rollback()

    def tearDown(self):
        self.db.session.rollback()
        self.ctx.pop()

    def test_daemon_unreachable_is_a_warning_not_a_failure(self):
        from aot.ai.services.aot_data_tool_service import AoTDataToolService
        from aot.databases.models import Output, OutputChannel

        result = AoTDataToolService.create_output(output_type='chirpstack_downlink')

        # 데몬이 없는 테스트 환경이니 리로드 알림은 반드시 실패한다 — 그 실패가
        # 여기 있는 것 자체는 이 시나리오를 제대로 재현했다는 증거다.
        self.assertNotIn('error', result,
                          "데몬 리로드 실패가 생성 자체의 실패로 보고됐다: %r" % (result,))
        self.assertEqual(result.get('status'), 'created')
        self.assertIn('output_id', result)
        self.assertIn('warning', result,
                       "데몬 리로드가 실패했는데 그 사실이 어디에도 안 남았다")
        self.assertIn('Daemon', result['warning'])

        # 보고만 고쳐지고 실제 생성은 안 됐다면 의미가 없다 — 행이 실재하는지 본다.
        output_id = result['output_id']
        self.assertIsNotNone(Output.query.filter_by(unique_id=output_id).first())
        channels = OutputChannel.query.filter_by(output_id=output_id).all()
        self.assertEqual(len(channels), 1,
                          "채널이 생성되지 않았다 — 이 결함과는 별개 문제다")

    def test_unknown_output_type_is_still_a_real_error(self):
        """new_id 를 먼저 보는 것이 "에러를 무시한다" 는 뜻이 되면 안 된다."""
        from aot.ai.services.aot_data_tool_service import AoTDataToolService

        result = AoTDataToolService.create_output(output_type='not_a_real_output_type')
        self.assertIn('error', result)
        self.assertNotIn('output_id', result)


if __name__ == '__main__':
    unittest.main()
