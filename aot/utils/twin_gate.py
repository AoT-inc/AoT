# coding=utf-8
"""디지털트윈(실험) 켜짐 판정의 정본 — 플래그 · 낮은 사양 잠금 · 서비스 하트비트.

설정 화면(S1)과 별도 서비스 `aot_twin`(S2)이 **같은 판정**을 쓰도록 여기 한곳에 둔다.
`Misc.twin_enabled` 를 직접 읽어 켜짐을 판단하지 말 것 — 낮은 사양 잠금이 빠진다.

DB 계약 (`misc` 행, alembic p6_90):
  twin_enabled    Boolean  사용자가 켠 플래그. 기본 False.
  twin_run_times  Text     'HH:MM,HH:MM' (현지). 기본 DEFAULT_RUN_TIMES.
  twin_heartbeat  JSON     서비스가 쓴다 (`write_heartbeat`).
      at           ISO 8601 UTC 문자열 'YYYY-MM-DDTHH:MM:SSZ' — 하트비트를 쓴 시각
      status       'running' | 'idle'(플래그 꺼짐·대기) | 'locked'(잠금 판정으로 멈춤) | 'error'
      version      서비스 버전 문자열
      sites        대상 대지 수 (int)
      plots        대상 구획 수 (int)
      last_run_at  마지막 계산 회차 시각 (at 와 같은 형식, 없으면 None)
      failures     최근 회차 실패 수 (int)
      locked_reason  잠겼을 때 twin_supported() 의 reason 코드, 아니면 None
  서비스는 TWIN_HEARTBEAT_INTERVAL_S 마다(플래그가 꺼져 있어도) 하트비트를 쓴다.
  `at` 이 TWIN_HEARTBEAT_MAX_AGE_S 보다 낡으면 화면은 "서비스가 실행 중이 아님" 으로 본다.

잠금 (이중 잠금: 화면·저장 경로와 서비스 시작 시 둘 다 `twin_supported()` 를 부른다):
  - HARDWARE_PROFILE=LOW  (AOT_TWIN_IGNORE_PROFILE=1 이면 이 항목만 건너뛴다 — 아래 참고)
  - 파이 Zero·1·2·3 (모델 문자열로 판정; 4·5 는 메모리로 가른다)
  - 기기 메모리 TWIN_MIN_MEM_GB 미만 (컨테이너 한도는 보지 않는다; 측정 불가면 잠그지 않는다 — 예: 파이가 아닌 맥 직접 실행)

⚠ docker/docker-compose.yml(개발용)과 prod 기본값은 HARDWARE_PROFILE=LOW 라서, 그대로면
  개발서버도 잠긴다. 운영자가 명시적으로 `AOT_TWIN_IGNORE_PROFILE=1` 을 주면 프로파일 항목만
  무시한다(파이 모델·메모리 잠금은 그대로).

표준 라이브러리 + 지연 import 만 쓴다 — 서비스(Flask 없는 프로세스)에서도 import 된다.

@phase active
@stability experimental
"""
import datetime
import logging
import os
import re

logger = logging.getLogger("aot.twin_gate")

# --- 기준 상수 -------------------------------------------------------------
# 4 GB 급 보드의 MemTotal 은 3.7~3.8 GB 로 보고된다(커널·GPU 예약분). 공칭 4 GB 를 통과시키려면
# 문턱을 4.0 이 아니라 3.5 로 둬야 한다.
TWIN_MIN_MEM_GB = 3.5
TWIN_LOCKED_PROFILES = ('LOW',)
# 'Raspberry Pi Zero 2 W' · 'Raspberry Pi Model B Rev 2'(1세대) · 'Raspberry Pi 2/3 Model B'.
# 4·5 는 여기에 안 걸리고 메모리로 가른다.
TWIN_LOW_PI_RE = re.compile(r'raspberry pi (zero|model|[123]\b)', re.IGNORECASE)
IGNORE_PROFILE_ENV = 'AOT_TWIN_IGNORE_PROFILE'

TWIN_HEARTBEAT_INTERVAL_S = 60
TWIN_HEARTBEAT_MAX_AGE_S = 180

DEFAULT_RUN_TIMES = '06:10,18:10'
MAX_RUN_TIMES = 12

REASON_PROFILE_LOW = 'profile_low'
REASON_PI_MODEL = 'pi_model'
REASON_LOW_MEMORY = 'low_memory'

# 로그·서비스용 영어 문구. 화면은 reason 코드를 보고 번역된 문구를 고른다.
LOCK_MESSAGES = {
    REASON_PROFILE_LOW: 'HARDWARE_PROFILE is LOW.',
    REASON_PI_MODEL: 'This Raspberry Pi model is too small.',
    REASON_LOW_MEMORY: 'Less than %.1f GB of memory.' % TWIN_MIN_MEM_GB,
}

_RUN_TIME_RE = re.compile(r'^([01]?\d|2[0-3]):([0-5]\d)$')


# --- 잠금 ------------------------------------------------------------------
def twin_supported():
    """이 기기에서 디지털트윈을 켤 수 있는가. `(True, '')` 또는 `(False, reason코드)`."""
    from aot.config.mcp_config import HARDWARE_PROFILE
    from aot.utils import system_environment as env

    if (str(HARDWARE_PROFILE or '').upper() in TWIN_LOCKED_PROFILES
            and os.environ.get(IGNORE_PROFILE_ENV, '') not in ('1', 'true', 'TRUE')
            and not ignore_profile_flag()):
        return False, REASON_PROFILE_LOW

    model = env.pi_model()
    if model and TWIN_LOW_PI_RE.search(model):
        return False, REASON_PI_MODEL

    # 컨테이너 메모리 한도가 아니라 기기 메모리 — aot_twin 자신의 한도(768M)로 스스로 잠기지 않게
    mem = env.mem_total_gb(host_only=True)
    if mem is not None and mem < TWIN_MIN_MEM_GB:
        return False, REASON_LOW_MEMORY

    return True, ''


# --- Misc 읽기·쓰기 (테스트가 갈아끼우는 두 지점) ---------------------------
def _load_misc():
    """Misc 행(없으면 None). Flask 앱 컨텍스트 안이면 그 세션, 밖이면 데몬식 독립 세션."""
    try:
        from flask import has_app_context
        in_flask = has_app_context()
    except Exception:
        in_flask = False
    try:
        from aot.databases.models import Misc
        if in_flask:
            return Misc.query.first()
        from aot.utils.database import db_retrieve_table_daemon
        return db_retrieve_table_daemon(Misc, entry='first')
    except Exception:
        logger.debug("twin_gate: Misc 조회 실패", exc_info=True)
        return None


def _store_heartbeat(data):
    from aot.config import AOT_DB_PATH
    from aot.databases.models import Misc
    from aot.databases.utils import session_scope
    with session_scope(AOT_DB_PATH) as session:
        misc = session.query(Misc).first()
        if misc is None:
            return False
        misc.twin_heartbeat = data
    return True


# --- 플래그 ----------------------------------------------------------------
def ignore_profile_flag():
    """사용자가 설정 > 디지털트윈에서 '낮은 사양 프로파일 잠금 해제'를 켰는가(HARDWARE_PROFILE 항목만 건너뜀).

    환경변수 `AOT_TWIN_IGNORE_PROFILE` 과 같은 효과의 화면 옵션이다. 파이 모델·기기 메모리 잠금은 그대로다.
    """
    misc = _load_misc()
    return bool(misc is not None and getattr(misc, 'twin_ignore_profile', False))


def auto_forecast_enabled():
    """대지에 트윈을 켤 때 가까운 예보 입력이 없으면 새로 만드는가(기본 켜짐)."""
    misc = _load_misc()
    v = getattr(misc, 'twin_auto_forecast', None) if misc is not None else None
    return True if v is None else bool(v)


def twin_flag():
    """사용자가 켠 플래그만(잠금 무시). 화면의 토글 표시용 — 켜짐 판단에는 twin_enabled()."""
    misc = _load_misc()
    return bool(misc is not None and getattr(misc, 'twin_enabled', False))


def twin_enabled():
    """플래그가 켜져 있고 잠기지 않았을 때만 True."""
    if not twin_flag():
        return False
    return twin_supported()[0]


# --- 실행 시각 -------------------------------------------------------------
def normalize_run_times(text):
    """'6:10, 18:10' → ('06:10,18:10', None). 형식이 틀리면 (None, 오류코드).

    오류코드: 'empty' | 'format' | 'too_many'. 같은 시각은 합치고 오름차순으로 정렬한다.
    """
    parts = [p.strip() for p in str(text or '').replace(';', ',').split(',') if p.strip()]
    if not parts:
        return None, 'empty'
    if len(parts) > MAX_RUN_TIMES:
        return None, 'too_many'
    out = set()
    for p in parts:
        m = _RUN_TIME_RE.match(p)
        if not m:
            return None, 'format'
        out.add('%02d:%02d' % (int(m.group(1)), int(m.group(2))))
    return ','.join(sorted(out)), None


def run_times():
    """저장된 실행 시각 목록 ['06:10', '18:10']. 비었거나 깨졌으면 기본값."""
    misc = _load_misc()
    raw = getattr(misc, 'twin_run_times', None) if misc is not None else None
    norm, err = normalize_run_times(raw or DEFAULT_RUN_TIMES)
    if err:
        norm, _ = normalize_run_times(DEFAULT_RUN_TIMES)
    return norm.split(',')


# --- 하트비트 --------------------------------------------------------------
def _utcnow():
    return datetime.datetime.now(datetime.timezone.utc)


def _iso(dt):
    return dt.astimezone(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _parse_ts(value):
    """ISO 8601 문자열 또는 epoch 초 → aware UTC datetime. 못 읽으면 None."""
    if value is None or value == '':
        return None
    try:
        if isinstance(value, (int, float)):
            return datetime.datetime.fromtimestamp(float(value), datetime.timezone.utc)
        text = str(value).strip()
        if text.endswith('Z'):
            text = text[:-1] + '+00:00'
        dt = datetime.datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt.astimezone(datetime.timezone.utc)
    except (ValueError, TypeError, OverflowError, OSError):
        return None


def read_heartbeat():
    """서비스가 남긴 하트비트 dict. 없거나 dict 가 아니면 None."""
    misc = _load_misc()
    hb = getattr(misc, 'twin_heartbeat', None) if misc is not None else None
    if isinstance(hb, str):
        import json
        try:
            hb = json.loads(hb)
        except ValueError:
            return None
    return hb if isinstance(hb, dict) else None


def heartbeat_stale(max_age=TWIN_HEARTBEAT_MAX_AGE_S, heartbeat=None, now=None):
    """하트비트가 없거나 읽을 수 없거나 max_age(초)보다 낡았으면 True."""
    hb = heartbeat if heartbeat is not None else read_heartbeat()
    if not hb:
        return True
    at = _parse_ts(hb.get('at'))
    if at is None:
        return True
    age = ((now or _utcnow()) - at).total_seconds()
    return age > max_age


def write_heartbeat(status, version='', sites=0, plots=0, last_run_at=None,
                    failures=0, locked_reason=None, now=None):
    """서비스가 부르는 쓰기 도우미. `at` 은 여기서 찍는다. 성공하면 True."""
    ts = now or _utcnow()
    if isinstance(last_run_at, datetime.datetime):
        last_run_at = _iso(last_run_at)
    data = {
        'at': _iso(ts),
        'status': status,
        'version': version,
        'sites': int(sites),
        'plots': int(plots),
        'last_run_at': last_run_at,
        'failures': int(failures),
        'locked_reason': locked_reason,
    }
    try:
        return bool(_store_heartbeat(data))
    except Exception:
        logger.warning("twin_gate: 하트비트 기록 실패", exc_info=True)
        return False
