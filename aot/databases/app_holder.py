# coding=utf-8
"""데몬 스레드가 Flask 앱 컨텍스트를 여는 자리 (아키텍처 7b).

`Model.query` 는 앱 컨텍스트가 필요한데 데몬 스레드에는 없다. 예전에는 데몬
코드가 AI 스케줄러의 `_flask_app` 을 직접 가져다 써서 데몬이 AI 계층을 import
했다. 앱 참조를 이 모듈이 들고, 앱 팩토리 쪽(`AISchedulerService.init_app`)이
`set_app` 으로 채운다.
"""
_app = None


def set_app(app):
    global _app
    _app = app


def get_app():
    return _app


def run_in_app(fn, default=None):
    """앱 컨텍스트 안에서 fn() 을 실행한다.

    이미 컨텍스트가 있으면 그대로, 없으면 등록된 앱으로 연다. 앱이 없으면
    default 를 돌려준다.
    """
    from flask import has_app_context
    if has_app_context():
        return fn()
    if _app is None:
        return default
    with _app.app_context():
        return fn()
