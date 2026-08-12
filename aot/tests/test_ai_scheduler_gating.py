# coding=utf-8
"""AI 스케줄러 백그라운드 잡의 런타임 게이팅과 반복 오류 억제.

세 가지를 고정한다(2026-08-12).

1. **AI 작동을 시작하지 않았는데 돌고 있었다.** `_context_source_sync_job` 과
   `_calendar_sync_job` 은 `ai_enabled` 만 보고 등록돼 런타임 게이트가 아예
   없었다. 그래서 "AI > AI 에이전트" 에서 시작하지 않은 서버에서도 외부 소스를
   매 주기 긁었다. 같은 파일의 다른 잡 4종은 전부 게이트를 갖고 있었다.
2. **못 고치는 설정 오류를 매 주기 WARNING 으로 찍었다.** `file_path` 없는
   document 소스가 24시간에 19줄을 쌓았다 — 새 정보는 첫 줄뿐이다.
3. 억제가 **영구화되면 안 된다** — 복구 후 재실패는 다시 크게 말해야 한다.
"""
import contextlib

import pytest

from aot.ai.services import ai_scheduler_service as svc


class _FakeApp(object):
    def app_context(self):
        return contextlib.nullcontext()


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    monkeypatch.setattr(svc, '_flask_app', _FakeApp())
    monkeypatch.setattr(svc, '_context_sync_last_error', {})


def _set_autonomy(monkeypatch, value):
    from aot.ai.services import ai_runtime_state
    monkeypatch.setattr(ai_runtime_state, 'ai_autonomy_enabled', lambda *a, **k: value)
    monkeypatch.setattr(ai_runtime_state, 'background_skip_reason',
                        lambda *a, **k: 'AI 작동 시작 안 됨')


def _set_sync_result(monkeypatch, results):
    """sync_source 를 차례대로 돌려주는 스텁으로 갈아끼우고 호출 기록을 준다."""
    from aot.ai.services import context_source_service
    calls = []

    def _sync(source_id):
        calls.append(source_id)
        return results[min(len(calls) - 1, len(results) - 1)]

    monkeypatch.setattr(context_source_service, 'sync_source', _sync)
    return calls


def test_skipped_while_ai_not_started(monkeypatch, caplog):
    _set_autonomy(monkeypatch, False)
    calls = _set_sync_result(monkeypatch, [{'error': ['boom']}])

    with caplog.at_level('WARNING', logger=svc.__name__):
        svc._context_source_sync_job('src-1')

    assert calls == []            # 소스를 건드리지도 않는다
    assert caplog.records == []   # 로그도 남기지 않는다


def test_runs_when_ai_started(monkeypatch):
    _set_autonomy(monkeypatch, True)
    calls = _set_sync_result(monkeypatch, [{}])

    svc._context_source_sync_job('src-1')

    assert calls == ['src-1']


def test_identical_error_warns_once(monkeypatch, caplog):
    _set_autonomy(monkeypatch, True)
    _set_sync_result(monkeypatch, [{'error': ['file_path is required for document source.']}])

    with caplog.at_level('DEBUG', logger=svc.__name__):
        for _ in range(5):
            svc._context_source_sync_job('src-1')

    warnings = [r for r in caplog.records if r.levelname == 'WARNING']
    assert len(warnings) == 1
    assert 'file_path is required' in warnings[0].getMessage()


def test_changed_error_warns_again(monkeypatch, caplog):
    _set_autonomy(monkeypatch, True)
    _set_sync_result(monkeypatch, [{'error': ['first']}, {'error': ['second']}])

    with caplog.at_level('WARNING', logger=svc.__name__):
        svc._context_source_sync_job('src-1')
        svc._context_source_sync_job('src-1')

    warnings = [r.getMessage() for r in caplog.records if r.levelname == 'WARNING']
    assert len(warnings) == 2


def test_calendar_sync_skipped_while_ai_not_started(monkeypatch, caplog):
    """캘린더 연결만으로는 동기화가 시작되지 않는다 — AI 작동도 켜져 있어야 한다."""
    _set_autonomy(monkeypatch, False)
    from aot.ai.services import calendar_sync_service
    calls = []
    monkeypatch.setattr(calendar_sync_service, 'sync_connection',
                        lambda cid: calls.append(cid) or {})

    with caplog.at_level('WARNING', logger=svc.__name__):
        svc._calendar_sync_job(7)

    assert calls == []
    assert caplog.records == []


def test_calendar_sync_runs_when_ai_started(monkeypatch):
    _set_autonomy(monkeypatch, True)
    from aot.ai.services import calendar_sync_service
    calls = []
    monkeypatch.setattr(calendar_sync_service, 'sync_connection',
                        lambda cid: calls.append(cid) or {})

    svc._calendar_sync_job(7)

    assert calls == [7]


def test_recovery_is_reported_and_rearms(monkeypatch, caplog):
    """복구를 알린 뒤 다시 실패하면 또 크게 말해야 한다 — 억제가 영구화되면
    안 된다."""
    _set_autonomy(monkeypatch, True)
    _set_sync_result(monkeypatch, [{'error': ['boom']}, {}, {'error': ['boom']}])

    with caplog.at_level('INFO', logger=svc.__name__):
        svc._context_source_sync_job('src-1')
        svc._context_source_sync_job('src-1')
        svc._context_source_sync_job('src-1')

    levels = [r.levelname for r in caplog.records if r.levelname in ('WARNING', 'INFO')]
    assert levels.count('WARNING') == 2
    assert any('recovered' in r.getMessage() for r in caplog.records)


# ─── 고아 잡 정리 ──────────────────────────────────────────────────────────

class _FakeJob(object):
    def __init__(self, job_id):
        self.id = job_id


class _FakeScheduler(object):
    def __init__(self, job_ids):
        self._jobs = [_FakeJob(j) for j in job_ids]
        self.removed = []

    def get_jobs(self):
        return list(self._jobs)

    def remove_job(self, job_id):
        self._jobs = [j for j in self._jobs if j.id != job_id]
        self.removed.append(job_id)


def test_orphan_jobs_are_pruned():
    """비활성화된 소스의 잡은 기동 때 지운다 — 게이트 때문에 스스로 사라질
    기회가 없어졌기 때문."""
    sch = _FakeScheduler([
        'context_source_sync_live',
        'context_source_sync_dead',
        'calendar_sync_3',            # 접두사가 다르면 건드리지 않는다
        'ai_scheduler_weather_summary',
    ])

    svc._prune_orphan_jobs(sch, 'context_source_sync_', {'live'}, '[T]')

    assert sch.removed == ['context_source_sync_dead']


def test_prune_failure_is_not_fatal(monkeypatch):
    """정리 실패가 기동을 막으면 안 된다."""
    class _Boom(object):
        def get_jobs(self):
            raise RuntimeError('jobstore down')

    svc._prune_orphan_jobs(_Boom(), 'context_source_sync_', set(), '[T]')  # 예외 없음
