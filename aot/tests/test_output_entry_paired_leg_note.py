# coding=utf-8
"""출력 카드에 "짝 액추에이터가 사용 중" 표시가 실제로 렌더링되는지 확인.

`routes_output.py` 가 만드는 `paired_leg_usage` 를 `output_entry.html` 이
튜플 키(`(output_id, channel)`)로 그대로 찾아 쓴다 — Jinja 쪽 타입(문자열
output_id, 정수 channel)이 Python 쪽(`paired_actuator_common.
paired_leg_relations`)과 어긋나면 조용히 아무것도 안 뜬다(예외가 아니라
`dict.get()` 이 `None` 을 돌려줄 뿐이므로). 그래서 실제 템플릿을 실제 Jinja
환경(flask-babel `_` 포함)으로 렌더링해 문자열이 나오는지까지 확인한다.
"""
import pytest


@pytest.fixture
def app():
    from aot.aot_flask.app import create_app
    from aot.config import ProdConfig

    class _Config(ProdConfig):
        SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
        TESTING = True
        WTF_CSRF_ENABLED = False

    return create_app(config=_Config)


class _Output:
    def __init__(self, unique_id, name, output_type, interface=None, pin=None):
        self.unique_id = unique_id
        self.name = name
        self.output_type = output_type
        self.interface = interface
        self.pin = pin


def _dict_outputs(output_type):
    return {
        output_type: {
            'channels_dict': {0: {}},
            'output_name': 'Virtual On/Off',
            'output_library': '',
            'options_enabled': ['button_on'],
        }
    }


def _render_card(app, each_output, paired_leg_usage):
    from aot.aot_flask.forms import forms_output

    with app.test_request_context():
        form_mod_output = forms_output.OutputMod()
        return app.jinja_env.get_template('pages/output_entry.html').render(
            each_output=each_output,
            form_mod_output=form_mod_output,
            dict_outputs=_dict_outputs(each_output.output_type),
            dict_translation={'copy_to_clipboard': {'phrase': 'Copy'}},
            custom_options_values_output_channels={each_output.unique_id: {0: {}}},
            three_way_output_types=frozenset({'actuator_paired', 'actuator_paired_bus'}),
            output_states={},
            paired_leg_usage=paired_leg_usage,
        )


def test_plain_channel_without_leg_usage_shows_no_note(app):
    out = _Output('relay-1', '평범한 릴레이', 'virtual_on_off_single')
    html = _render_card(app, out, paired_leg_usage={})
    assert 'aot-form-hint' not in html


def test_open_leg_channel_shows_owner_and_leg(app):
    out = _Output('relay-1', '측창 열기 릴레이', 'virtual_on_off_single')
    usage = {
        ('relay-1', 0): [{
            'owner_id': 'valve-1', 'owner_name': '측창',
            'leg': 'open', 'partners': [('relay-2', 0)],
        }],
    }
    html = _render_card(app, out, paired_leg_usage=usage)
    assert 'aot-form-hint' in html
    assert '측창' in html
    assert 'open' in html


def test_selector_leg_channel_shows_selector_label(app):
    out = _Output('sel-1', '선택 릴레이', 'virtual_on_off_single')
    usage = {
        ('sel-1', 0): [{
            'owner_id': 'v1', 'owner_name': '측창1',
            'leg': 'selector', 'partners': [('sel-2', 0)],
        }],
    }
    html = _render_card(app, out, paired_leg_usage=usage)
    assert 'selector' in html
    assert '측창1' in html


def test_paired_actuator_card_itself_never_shows_the_note(app):
    """짝 액추에이터 자신의 카드는 이미 열기/닫기/정지 버튼이 있다 — 자기 자신을
    자기 다리라고 표시하면 혼란만 준다(이 표시는 밑단 on/off 카드 전용)."""
    out = _Output('valve-1', '측창', 'actuator_paired')
    usage = {
        ('open-relay', 0): [{
            'owner_id': 'valve-1', 'owner_name': '측창',
            'leg': 'open', 'partners': [('close-relay', 0)],
        }],
    }
    html = _render_card(app, out, paired_leg_usage=usage)
    assert 'aot-form-hint' not in html


def test_missing_context_var_does_not_crash(app):
    """`paired_leg_usage` 를 안 넘기는 다른 렌더 경로가 있어도(예: 옛 테스트,
    다른 모달) 카드가 깨지면 안 된다."""
    out = _Output('relay-1', '평범한 릴레이', 'virtual_on_off_single')

    with app.test_request_context():
        from aot.aot_flask.forms import forms_output
        form_mod_output = forms_output.OutputMod()
        html = app.jinja_env.get_template('pages/output_entry.html').render(
            each_output=out,
            form_mod_output=form_mod_output,
            dict_outputs=_dict_outputs(out.output_type),
            dict_translation={'copy_to_clipboard': {'phrase': 'Copy'}},
            custom_options_values_output_channels={out.unique_id: {0: {}}},
            three_way_output_types=frozenset(),
            output_states={},
            # paired_leg_usage 를 일부러 안 넘긴다.
        )
    assert 'aot-form-hint' not in html
