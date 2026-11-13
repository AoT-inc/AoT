# coding=utf-8
"""aot/utils/module_hooks.py — 모듈 파일 안의 웹 훅 공통 처리.

훅은 데몬도 읽는 모듈 파일에 있으므로 flask 를 import 하지 않고, 바로 띄우던
메시지는 messages 에 담아 웹 쪽이 꺼내 flash 한다. 그 약속을 고정한다.
"""
import ast
import glob
import os

from aot.utils import module_hooks

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))


def _imports(path):
    tree = ast.parse(open(path, encoding='utf-8').read())
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_module_hooks_does_not_import_flask():
    names = _imports(os.path.join(ROOT, 'aot', 'utils', 'module_hooks.py'))
    assert not any(n == 'flask' or n.startswith('flask.') for n in names)
    assert not any(n.startswith('aot.aot_flask') for n in names)


def test_hook_modules_do_not_import_web_layer():
    paths = glob.glob(os.path.join(ROOT, 'aot', 'functions', 'display_*.py'))
    paths += [os.path.join(ROOT, *p.split('/')) for p in (
        'aot/actions/input_action_execute_python_code.py',
        'aot/inputs/python_code.py',
        'aot/inputs/python_code_v_2_0.py',
        'aot/outputs/on_off_python.py',
        'aot/outputs/pwm_python.py')]
    assert len(paths) >= 17
    for path in paths:
        for n in _imports(path):
            assert not (n == 'flask' or n.startswith('flask.')), (path, n)
            assert not n.startswith('aot.aot_flask'), (path, n)


def test_queue_and_drain_flash():
    messages = {"success": [], "error": []}
    module_hooks.queue_flash(messages, 'success', 'a')
    module_hooks.queue_flash(messages, 'error', 'b')
    assert module_hooks.drain_flash(messages) == [('success', 'a'), ('error', 'b')]
    # 꺼내면 messages 에 남지 않는다 — JSON 응답에 섞이지 않게
    assert module_hooks.FLASH_QUEUE_KEY not in messages
    assert module_hooks.drain_flash(messages) == []
    assert module_hooks.drain_flash(None) == []


def test_web_app_testing_without_app_context_is_false():
    assert module_hooks.web_app_testing() is False


def test_web_app_testing_reads_current_app():
    from flask import Flask
    app = Flask(__name__)
    app.config['TESTING'] = True
    with app.app_context():
        assert module_hooks.web_app_testing() is True
    app.config['TESTING'] = False
    with app.app_context():
        assert module_hooks.web_app_testing() is False


def test_channel_options_defaults_and_web_alias():
    from aot.aot_flask.utils import utils_general
    assert (utils_general.custom_channel_options_return_json
            is module_hooks.custom_channel_options_return_json)
    assert utils_general.normalize_option_value is module_hooks.normalize_option_value

    dict_options = {'dev': {'custom_channel_options': [
        {'id': 'line', 'type': 'text', 'default_value': 'x'},
        {'id': 'n', 'type': 'integer', 'default_value': 3},
    ]}}
    error, js = module_hooks.custom_channel_options_return_json(
        [], dict_options, None, 'fid', 0, device='dev', use_defaults=True)
    assert error == []
    assert js == '{"line": "x", "n": 3}'
