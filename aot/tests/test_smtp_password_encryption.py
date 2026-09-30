# coding=utf-8
"""SMTP 비밀번호의 저장 시 암호화 (2026-09-25).

`smtp.passw` 는 평문 Text 였고 설정 내보내기·백업에 그대로 실렸다. 이제 컬럼에는
`aotenc1:` 표지가 붙은 암호문만 들어가고, 읽는 쪽(메일 발송)만 복호화한다.
"""
import importlib.util
import os
import sqlite3

import pytest

from aot.utils import crypto

_MIG = 'p6_78_smtp_password_encrypt_20260930'


@pytest.fixture(autouse=True)
def _fixed_key(monkeypatch):
    """파일 시스템의 flask_secret_key 를 건드리지 않는다."""
    from cryptography.fernet import Fernet
    monkeypatch.setattr(crypto, '_fernet', Fernet(Fernet.generate_key()))


def _other_install_key(monkeypatch):
    from cryptography.fernet import Fernet
    monkeypatch.setattr(crypto, '_fernet', Fernet(Fernet.generate_key()))


class TestSealed:

    def test_봉인하면_평문이_보이지_않는다(self):
        sealed = crypto.seal_secret('app-pass-1234')
        assert sealed.startswith(crypto.SEALED_PREFIX)
        assert 'app-pass-1234' not in sealed

    def test_봉인한_값은_되읽힌다(self):
        assert crypto.open_sealed(crypto.seal_secret('pw')) == ('pw', crypto.SEALED_OK)

    def test_같은_값도_봉인할_때마다_다르다(self):
        assert crypto.seal_secret('pw') != crypto.seal_secret('pw')

    def test_빈_값은_None(self):
        assert crypto.seal_secret('') is None
        assert crypto.seal_secret(None) is None
        assert crypto.open_sealed(None) == (None, crypto.SEALED_EMPTY)

    def test_표지_없는_옛_값은_평문으로_읽는다(self):
        assert crypto.open_sealed('old-plain') == ('old-plain', crypto.SEALED_LEGACY)

    def test_다른_키로_봉인된_값은_읽을_수_없다(self, monkeypatch):
        sealed = crypto.seal_secret('pw')
        _other_install_key(monkeypatch)
        assert crypto.open_sealed(sealed) == (None, crypto.SEALED_UNREADABLE)


class TestSmtpModel:

    def _smtp(self, **kw):
        from aot.databases.models import SMTP
        return SMTP(**kw)

    def test_대입하면_컬럼에는_암호문이_들어간다(self):
        smtp = self._smtp()
        smtp.passw = 'secret-app-password'
        assert smtp.passw_enc.startswith(crypto.SEALED_PREFIX)
        assert 'secret-app-password' not in smtp.passw_enc
        assert smtp.passw == 'secret-app-password'

    def test_생성자_인자도_봉인된다(self):
        smtp = self._smtp(passw='abc')
        assert smtp.passw_enc.startswith(crypto.SEALED_PREFIX)

    def test_기본값은_비어_있다(self):
        """예전 기본값 'password' 는 가짜 자격증명이었다."""
        smtp = self._smtp()
        assert smtp.passw is None and not smtp.has_password

    def test_컬럼_이름은_그대로_passw(self):
        from aot.databases.models import SMTP
        assert 'passw' in SMTP.__table__.columns

    def test_다른_설치에서_복원되면_읽을_수_없음으로_알린다(self, monkeypatch):
        smtp = self._smtp(passw='abc')
        _other_install_key(monkeypatch)
        assert smtp.passw is None
        assert smtp.has_password and smtp.password_unreadable

    def test_옛_평문_행도_동작한다(self):
        smtp = self._smtp()
        smtp.passw_enc = 'legacy'
        assert smtp.passw == 'legacy' and smtp.password_is_legacy_plaintext


class TestSendEmailGuard:

    def test_비밀번호가_없으면_서버에_접속하지_않고_이유를_남긴다(self, caplog):
        from aot.utils import send_data
        with caplog.at_level('ERROR'):
            rc = send_data.send_email('smtp.example.com', 'ssl', 465, 'u', None,
                                      'f@example.com', 'to@example.com', 'hi')
        assert rc == 1
        assert 'cannot be decrypted' in caplog.text

    def test_로그인_없는_프로토콜은_비밀번호가_없어도_막지_않는다(self, monkeypatch):
        from aot.utils import send_data
        called = {}

        class _Srv:
            def __init__(self, *a, **k): called['connect'] = True
            def ehlo(self): pass
            def sendmail(self, *a): return {}
            def quit(self): pass

        monkeypatch.setattr(send_data.smtplib, 'SMTP', _Srv)
        rc = send_data.send_email('h', 'unencrypted_no_login', 25, 'u', None,
                                  'f@example.com', 'to@example.com', 'hi')
        assert rc == 0 and called['connect']


def _load_migration():
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, '..', '..', 'alembic_db', 'alembic', 'versions',
                        _MIG + '.py')
    spec = importlib.util.spec_from_file_location(_MIG, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(mod, fn, engine):
    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext
    with engine.begin() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            getattr(mod, fn)()


@pytest.fixture
def smtp_db(tmp_path):
    import sqlalchemy as sa
    path = tmp_path / 'aot.db'
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE smtp (id INTEGER PRIMARY KEY, host TEXT, passw TEXT)")
    con.executemany("INSERT INTO smtp (id, host, passw) VALUES (?,?,?)",
                    [(1, 'h', 'plain-pass'), (2, 'h', None), (3, 'h', '')])
    con.commit()
    con.close()
    return sa.create_engine(f'sqlite:///{path}')


def _passws(engine):
    import sqlalchemy as sa
    with engine.connect() as c:
        return dict(c.execute(sa.text("SELECT id, passw FROM smtp")).fetchall())


def test_migration_chain():
    mod = _load_migration()
    assert mod.revision == _MIG
    assert mod.down_revision == 'p6_77_mcp_central_auth_20260928'
    from aot.config import ALEMBIC_VERSION
    assert ALEMBIC_VERSION == _MIG or ALEMBIC_VERSION > _MIG


def test_migration_encrypts_plaintext_and_keeps_empty(smtp_db):
    mod = _load_migration()
    _run(mod, 'upgrade', smtp_db)
    rows = _passws(smtp_db)
    assert 'plain-pass' not in rows[1]
    assert crypto.open_sealed(rows[1]) == ('plain-pass', crypto.SEALED_OK)
    assert rows[2] is None and rows[3] == ''


def test_migration_is_idempotent_daemon_and_app_both_run_it(smtp_db):
    mod = _load_migration()
    _run(mod, 'upgrade', smtp_db)
    first = _passws(smtp_db)[1]
    _run(mod, 'upgrade', smtp_db)
    assert _passws(smtp_db)[1] == first          # 이중 암호화 없음


def test_migration_downgrade_restores_plaintext(smtp_db):
    mod = _load_migration()
    _run(mod, 'upgrade', smtp_db)
    _run(mod, 'downgrade', smtp_db)
    assert _passws(smtp_db)[1] == 'plain-pass'


def test_migration_skips_when_table_missing(tmp_path):
    import sqlalchemy as sa
    engine = sa.create_engine(f'sqlite:///{tmp_path / "empty.db"}')
    _run(_load_migration(), 'upgrade', engine)   # 예외 없이 끝나야 한다
