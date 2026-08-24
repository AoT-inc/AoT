# -*- coding: utf-8 -*-
#
# gunicorn_conf.py - Environment-adaptive gunicorn settings for aotflask.
#
# Thread count priority:
#   1. GUNICORN_THREADS environment variable
#   2. Manual setting in the settings DB (misc.gunicorn_threads, NULL = auto)
#   3. Automatic recommendation from the detected environment
#      (cores, memory, Raspberry Pi / Docker limits)
#
# Resolution never raises — any failure falls back to the automatic value,
# so service startup cannot be blocked here.
#
# ─────────────────────────────────────────────────────────────────────────────
# workers 는 1이다 — **캐시 때문이 아니라 스케줄러 때문이다.**
#
# 예전 주석은 "flask-caching 과 OpenMeteo 쿨다운이 프로세스 메모리라서" 라고
# 적고 있었는데 앞의 절반은 사실이 아니다: flask-caching 은 최초 커밋부터
# `FileSystemCache` 이고(extensions.py) 주석에 "Shared across gunicorn workers"
# 라고 붙어 있다. 그 근거를 믿고 워커를 늘리면 **훨씬 나쁜 일이 난다.**
#
# 진짜 이유: `create_app()` 이 `AISchedulerService.init_app()` 을 부르고, 그것이
# 영구 잡스토어(SQLAlchemyJobStore)를 물린 BackgroundScheduler 를 띄운다.
# 스케줄러 인스턴스는 모듈 전역이라 **프로세스당 하나**이고, 프로세스 사이를
# 조율하는 장치(파일락·리더선출)가 없다. `max_instances: 1` 은 한 스케줄러
# 안에서만 유효하다. 따라서 workers=N 이면 스케줄러 N 개가 같은 잡스토어에서
# 각자 만기 잡을 집어 실행한다 — **예약이 최대 N 번 발화하고, 그 예약에는
# 장치 제어가 포함된다.** 밸브가 N 번 열리는 것은 캐시 불일치와 무게가 다르다.
#
# ⚠ `preload_app = True` 로는 해결되지 않는다. 그러면 앱 팩토리가 fork 전
# 마스터에서 한 번 돌지만 **스케줄러 스레드는 fork 된 자식에게 상속되지 않아**
# 예약이 0 번 발화한다. N 번이 0 번이 될 뿐 둘 다 조용한 고장이다.
#
# 그래서 워커를 늘리려면 **스케줄러를 웹 프로세스 밖으로 먼저 옮겨야 한다**
# (설계: docs/design/scheduler-process-separation.md). 그 전까지 이 값은 1이다.
#
# 남는 성능은 실재한다 — 라즈베리파이 4B 실측(2026-08-24): 동시 요청을 1→12 로
# 올려도 처리량이 3.8→3.5 req/s 로 그대로이고(GIL 에 묶인 Python 구간), 그때
# 워커는 코어 1.2~1.5 개, 시스템 전체는 4코어 중 34~52% 만 쓴다. 코어 두 개
# 남짓이 놀고 있다는 뜻이다. 다만 워커를 늘린 뒤에는 SQLite 쓰기 경합이 다음
# 병목 후보이므로 **늘리고 나서 다시 재야 한다.**
#
# 프로세스 메모리에 남아 워커를 늘리면 갈라지는 것들(전부 경미, 안전 문제 아님):
#   - routes_geo._openmeteo_fail_until — 상류 장애 시 60초 창에서 호출이 N 배
#   - site_summary._CACHE(30초) — 적중률이 떨어져 재계산이 는다
# ─────────────────────────────────────────────────────────────────────────────
#
import os
import sys

_INSTALL_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if _INSTALL_DIR not in sys.path:
    sys.path.insert(0, _INSTALL_DIR)

from aot.utils.system_environment import detect, resolve_gunicorn_threads

# Mirrors aot.config DB path resolution without importing the full config
# (which pulls flask_babel and the rest of the app at master startup).
# Must NOT require 'databases' to already exist under AOT_LOCAL_DIR -- see
# the matching comment in aot/config/__init__.py.
_local_dir = os.environ.get('AOT_LOCAL_DIR')
if _local_dir:
    _db_path = os.path.join(_local_dir, 'databases', 'aot.db')
else:
    _db_path = os.path.join(_INSTALL_DIR, 'aot', 'databases', 'aot.db')

_env = detect()
_threads, _source = resolve_gunicorn_threads(database_path=_db_path)

workers = 1
worker_class = 'gthread'
threads = _threads
timeout = 300

print(
    f"[gunicorn_conf] platform={_env['platform_type']} "
    f"cores={_env['cpu_cores']} mem={_env['mem_total_gb']}GB "
    f"-> threads={threads} (source={_source})",
    flush=True)
