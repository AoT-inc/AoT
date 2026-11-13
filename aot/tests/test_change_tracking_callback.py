# coding=utf-8
"""7c: DB 변경 리스너는 주입된 콜백을 부르고, 콜백 없이는 등록되지 않는다."""
import pytest
from sqlalchemy import Column, Integer, create_engine
from sqlalchemy.orm import Session, declarative_base

from aot.databases import change_tracking as ct


def test_handler_calls_injected_callback():
    calls = []
    handler = ct._on_change("added", lambda **kw: calls.append(kw))

    class Thing:
        pass

    handler(None, None, Thing())
    assert len(calls) == 1
    assert calls[0]['change_note'] == 'Thing added'


def test_callback_failure_never_breaks_write():
    def boom(**kw):
        raise RuntimeError('x')
    ct._on_change("updated", boom)(None, None, object())


def test_register_requires_callback():
    with pytest.raises(TypeError):
        ct.register_change_listeners()


def test_real_event_reaches_callback(monkeypatch):
    from aot.databases import models
    Base = declarative_base()

    class Input(Base):
        __tablename__ = 'input_ct_test'
        id = Column(Integer, primary_key=True)

    monkeypatch.setattr(ct, '_registered', False)
    monkeypatch.setattr(ct, '_TRACKED_MODELS', ('Input',))
    monkeypatch.setattr(models, 'Input', Input, raising=False)
    calls = []
    ct.register_change_listeners(lambda **kw: calls.append(kw['change_note']))
    eng = create_engine('sqlite://')
    Base.metadata.create_all(eng)
    with Session(eng) as s:
        s.add(Input())
        s.commit()
    assert calls == ['Input added']
