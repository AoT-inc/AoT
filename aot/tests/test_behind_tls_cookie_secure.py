# coding=utf-8
"""AOT_BEHIND_TLS 환경변수 회귀 가드.

배경 — 2026-09-23. `register_extensions()` 는 `DOCKER_CONTAINER` 이면 무조건
`SESSION_COOKIE_SECURE` · `REMEMBER_COOKIE_SECURE` · `WTF_CSRF_SSL_STRICT` 를
끈다(`aot/aot_flask/app.py`). LAN 에서 http 로 직접 쓰는 설치본(lite 장비 등)의
로그인이 깨지지 않게 하려는 것이지만, nginx proxy manager 같은 리버스 프록시
뒤에서 https 로만 서비스되는 설치본(ai.aotinc.co.kr, NAS 데모)도 똑같이
Docker 로 뜨므로 함께 꺼진다. 그 결과 세션 쿠키와 "로그인 유지"(remember,
90일) 쿠키 모두 Secure 없이 나간다 — 방문자가 주소창에 http:// 를 치면,
리버스 프록시가 https 로 돌려보내기 전에 이미 저장된 쿠키가 그 첫 평문 요청에
그대로 실려 나간다. remember 쿠키는 수명이 90일이라 더 위험하다.

`AOT_BEHIND_TLS=1` 은 이 완화를 건너뛰고 Secure 를 강제한다. 기본값은
꺼짐이어야 한다 — 그래야 훨씬 많은 LAN/Docker 설치본의 로그인이 지금처럼
유지된다. 이 파일은 그 기본값과, 켰을 때의 동작을 함께 고정한다.
"""
import pytest

from aot.config import ProdConfig


@pytest.fixture
def make_app(tmp_path, monkeypatch):
    """(docker, behind_tls) 조합으로 create_app() 을 돌려 쿠키 설정을 본다.

    `ALEMBIC_RUNNING=1` 은 conftest 가 전역으로 이미 세워 둔다 — 그래서
    `register_extensions()` 는 Misc 테이블을 읽지 않고 `force_https=False` 로
    시작한다. 즉 아래 단언은 Misc.force_https(관리자의 "Force HTTPS" 설정)와
    무관하게, DOCKER_CONTAINER·AOT_BEHIND_TLS 분기만으로 결정된 값이다.
    """

    def _make(docker, behind_tls, index):
        from aot.aot_flask.app import create_app
        from aot.aot_flask.extensions import db
        import aot.config as aot_config

        # 모듈 상수를 직접 바꾼다 — register_extensions() 는
        # `from aot.config import DOCKER_CONTAINER` 를 호출 시점에 실행하므로
        # (모듈은 conftest 에서 이미 로드돼 있다) 환경변수가 아니라 이 속성을
        # 봐야 실제로 반영된다.
        monkeypatch.setattr(aot_config, 'DOCKER_CONTAINER', docker)
        if behind_tls is None:
            monkeypatch.delenv('AOT_BEHIND_TLS', raising=False)
        else:
            monkeypatch.setenv('AOT_BEHIND_TLS', behind_tls)

        db_file = tmp_path / f"behind_tls_{index}.db"

        class _Config(ProdConfig):
            SQLALCHEMY_DATABASE_URI = f"sqlite:///{db_file}"
            TESTING = True

        application = create_app(config=_Config)
        with application.app_context():
            db.create_all()
            db.session.remove()
        return application

    return _make


def test_docker_without_behind_tls_keeps_cookies_insecure(make_app):
    """기존 LAN/Docker 기본 동작 — AOT_BEHIND_TLS 를 안 주면 지금처럼 꺼진다."""
    app = make_app(docker=True, behind_tls=None, index=1)
    assert app.config['SESSION_COOKIE_SECURE'] is False
    assert app.config['REMEMBER_COOKIE_SECURE'] is False
    assert app.config['WTF_CSRF_SSL_STRICT'] is False


def test_docker_with_behind_tls_forces_secure_cookies(make_app):
    """AOT_BEHIND_TLS=1 이면 Docker 완화를 건너뛰고 세 설정 모두 켠다."""
    app = make_app(docker=True, behind_tls='1', index=2)
    assert app.config['SESSION_COOKIE_SECURE'] is True
    assert app.config['REMEMBER_COOKIE_SECURE'] is True
    assert app.config['WTF_CSRF_SSL_STRICT'] is True


def test_behind_tls_works_without_docker_flag_too(make_app):
    """Docker 판정과 무관하게 AOT_BEHIND_TLS=1 만으로도 Secure 가 켜져야 한다."""
    app = make_app(docker=False, behind_tls='1', index=3)
    assert app.config['SESSION_COOKIE_SECURE'] is True
    assert app.config['REMEMBER_COOKIE_SECURE'] is True
    assert app.config['WTF_CSRF_SSL_STRICT'] is True


def test_behind_tls_requires_exact_value_one(make_app):
    """'0' 같은 값은 켜짐이 아니다 — 문자열 '1' 만 켠다(오탈자로 인한 오발동 방지)."""
    app = make_app(docker=True, behind_tls='0', index=4)
    assert app.config['SESSION_COOKIE_SECURE'] is False
    assert app.config['REMEMBER_COOKIE_SECURE'] is False
    assert app.config['WTF_CSRF_SSL_STRICT'] is False
