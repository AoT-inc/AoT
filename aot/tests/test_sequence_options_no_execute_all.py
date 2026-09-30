# coding=utf-8
"""시퀀스 설정 모달에는 '모든 액션 실행' 버튼이 없어야 한다.

그 버튼은 모든 스텝의 출력을 순서·지연·지속시간 없이 즉시 발사한다(밸브와
펌프가 동시에 켜지고 자동으로 꺼지지 않는다). 시퀀스는 활성화로 실행한다.
다른 트리거 타입의 모달에는 그대로 남아 있어야 한다.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / 'aot_flask/templates/pages/function_options'


def test_sequence_modal_has_no_execute_all_button():
    src = (ROOT / 'trigger_sequence_options.html').read_text(encoding='utf-8')
    assert "execute_all_actions" not in src
    assert "processRequest(this, 'execute_all_actions')" not in src


def test_other_trigger_modal_keeps_it():
    src = (ROOT / 'trigger_options.html').read_text(encoding='utf-8')
    assert "execute_all_actions" in src
