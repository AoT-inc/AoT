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


# ─── 2단계가 꺼져 있으면 아예 등록하지 않는다 ─────────────────────────────
#
# 1단계(ai_enabled)는 "AI 메뉴를 노출한다" 일 뿐인데, 예전에는 그것만 보고 잡을
# 등록했다. 실측(2026-09-08): ai_running=False·활성 에이전트 0 인 설치에서 잡
# 10개가 전부 등록돼 60초마다 깨어나고 있었다.

def test_owned_jobs_are_removed_not_just_skipped():
    """잡스토어가 DB 영속이라, 등록을 건너뛰는 것만으로는 꺼지지 않는다.

    예전에 켜져 있을 때 저장된 잡이 그대로 남아 스위치와 무관하게 계속
    깨어났다 — ai_enabled 를 끄고 재시작해도 10개가 전부 살아 있었다.
    """
    sch = _FakeScheduler([
        'ai_scheduler_mcp_health',
        'ai_scheduler_user_string_translation',
        'context_source_sync_abc',
        'calendar_sync_3',
        'some_unrelated_job',          # 남의 잡은 건드리지 않는다
    ])

    removed = svc._remove_owned_jobs(sch)

    remaining = {j.id for j in sch.get_jobs()}
    assert remaining == {'some_unrelated_job'}
    assert removed == 4


def test_every_registered_job_id_is_removable():
    """등록하는 잡은 반드시 정리 목록에 있어야 한다.

    여기 안 적힌 잡은 한번 등록되면 스위치를 꺼도 지울 수 없는 잡이 된다.
    """
    import inspect
    import re
    src = inspect.getsource(svc.AISchedulerService.init_app)
    registered = set(re.findall(r"id=['\"]([a-z_]+)['\"]", src))
    known = set(svc._OWNED_JOB_IDS)
    assert registered <= known, (
        'init_app 이 등록하지만 _OWNED_JOB_IDS 에 없는 잡: %s'
        % sorted(registered - known))


# ─── 예약을 실행하는 프로세스는 하나뿐 ────────────────────────────────────
#
# 잡스토어는 DB 하나를 공유한다. 둘 이상이 실행하면 같은 예약이 그 수만큼
# 발화하고, 그 예약에는 장치 제어가 들어 있다(실측 2026-09-08: 웹 워커와 데몬이
# 동시에 aot_scheduler.db 를 열고 있었다).

def _repo_source(*parts):
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, '..', *parts), encoding='utf-8') as fh:
        return fh.read()


def test_create_app_does_not_execute_schedules_by_default():
    """기본이 실행이면, 잡스토어를 공유하는 프로세스가 늘 때마다 조용히 는다."""
    import inspect as _inspect
    from aot.aot_flask import app as flask_app_mod
    param = _inspect.signature(flask_app_mod.create_app).parameters['run_scheduler']
    assert param.default is False


def test_only_the_daemon_asks_to_execute():
    """실행을 요청하는 호출부는 데몬 하나뿐이어야 한다."""
    assert 'create_app(run_scheduler=True)' in _repo_source('aot_daemon.py')
    for entry in ('start_flask_ui.py', 'aot_mcp_server.py', 'check_startup.py'):
        assert 'run_scheduler=True' not in _repo_source(entry), \
            '%s 가 예약 실행을 요청한다 — 데몬과 겹친다' % entry


def test_non_executing_process_still_starts_paused():
    """멈춰서라도 띄워야 add_job 이 잡스토어에 닿는다.

    아예 안 띄우면 APScheduler 가 잡을 자기 메모리(_pending_jobs)에 담고
    start() 때 비우므로, 웹·MCP 에서 승인한 예약이 DB 에 닿지 못하고 사라진다.
    """
    import inspect as _inspect
    src = _inspect.getsource(svc.AISchedulerService.init_app)
    assert 'paused=not execute' in src
    assert 'if not execute' in src


def test_heartbeat_is_not_an_ai_job():
    """AI 를 꺼도 사용자 예약은 실행돼야 하고, 그러려면 다른 프로세스가 넣은
    잡을 데몬이 알아채야 한다 — 심박이 AI 게이트와 함께 지워지면 안 된다."""
    assert svc._HEARTBEAT_JOB_ID not in svc._OWNED_JOB_IDS


def test_registration_gate_uses_runtime_state_not_ai_enabled():
    """판정은 ai_runtime_state 를 거친다 — 모델 주석이 지정한 정본이다."""
    import inspect
    src = inspect.getsource(svc.AISchedulerService.init_app)
    assert 'ai_runtime_state' in src
    assert 'ai_autonomy_enabled' in src
    # 1단계만 보고 등록하던 예전 판정이 남아 있으면 안 된다.
    assert 'settings.ai_enabled' not in src
