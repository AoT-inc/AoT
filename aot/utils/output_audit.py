# coding=utf-8
"""Output 제어 명령의 감사 기록 — 큐 적재 + 백그라운드 flush.

## 왜 게이트에서 바로 DB 에 쓰지 않는가

Output 제어는 Pyro5 RPC 로 들어오고, 클라이언트는 이 왕복에 **기본 8초 / 하드캡
10초**만 준다 (`aot_client.py` `_MAX_RPC_TIMEOUT`). 데몬 핸들러가 그 예산을 넘기면
웹 UI 는 "Could not connect to Daemon: receiving: timeout" 을 띄운다 — 데몬은 멀쩡한데도.
2026-07-31 에 실제로 이 증상으로 Output 저장이 실패했고, 그때 얻은 교훈이
"데몬에 새 작업을 붙일 땐 10초 안에 끝나는지부터 따져라" 였다.

감사 기록은 부가 기능이라 제어 경로의 지연 예산을 쓸 자격이 없다. 그래서 게이트는
**큐에 넣고 즉시 반환**하고, 별도 writer 스레드가 모아서 커밋한다. SQLite 쓰기
경합(데몬·flask 동시 쓰기)도 이 배치로 줄어든다.

## 큐가 넘치면

`put_nowait` 가 실패하면 드롭 카운터만 올리고 제어는 그대로 진행한다. 대신 드롭 수를
주기적으로 WARN 으로 남긴다 — **조용한 유실이 제일 나쁘다.** 기록이 빠진 걸 모르면
"기록이 없다 = 명령이 없었다" 로 잘못 읽게 된다.
"""
import logging
import os
import queue
import threading

logger = logging.getLogger(__name__)

# 큐 상한. 넘치면 드롭하고 카운터를 올린다. writer 가 죽어도 메모리가 무한히
# 늘지 않게 하는 안전장치라 넉넉하되 유한해야 한다.
_MAXSIZE = 2000

# 한 번에 커밋할 최대 건수 — 트랜잭션이 너무 길어져 다른 쓰기를 막지 않도록.
_BATCH = 50

# 운영 중 즉시 무력화용. 켜고 끄려면 환경변수 후 데몬 재시작.
_ENABLED = os.environ.get('AOT_OUTPUT_AUDIT', '1') not in ('0', 'false', 'False')

_q = queue.Queue(maxsize=_MAXSIZE)
_dropped = 0
_dropped_lock = threading.Lock()
_writer_thread = None
_stop_event = threading.Event()
_flask_app = None


def is_enabled():
    return _ENABLED


def record(entry):
    """감사 항목을 큐에 넣는다. 논블로킹이며 절대 예외를 올리지 않는다.

    :param entry: audit_log() 로 넘길 필드를 담은 dict
    """
    if not _ENABLED:
        return
    global _dropped
    try:
        _q.put_nowait(entry)
    except queue.Full:
        with _dropped_lock:
            _dropped += 1
    except Exception:
        # 감사 실패가 제어를 막지 않는다.
        logger.debug("감사 항목 적재 실패", exc_info=True)


def _flush_one(entry):
    from aot.utils.audit import audit_log, OUTPUT_CONTROL
    from aot.utils.command_origin import normalize_origin

    raw_origin = entry.get('origin')
    origin = normalize_origin(raw_origin)
    if origin.get('_coerced'):
        # 여기서 터뜨려 항목을 버리는 대신 기록은 남기고, 어떤 값이 왔는지
        # 남겨 둔다 — 원인을 못 찾은 채로 유실만 계속되는 것이 제일 나쁘다.
        logger.warning(
            "output 감사: origin 이 dict 가 아닙니다(%r, output=%s) — "
            "unknown 으로 기록합니다", raw_origin, entry.get('output_id'))
    detail = (
        "channel={} state={} type={} amount={} origin={}".format(
            entry.get('channel'),
            entry.get('state'),
            entry.get('output_type'),
            entry.get('amount'),
            origin.get('type'),
        )
    )
    if origin.get('_coerced'):
        # 원래 값을 detail 에 남겨야 나중에 어느 경로가 이걸 보내는지 찾을 수 있다.
        detail += f" origin_raw={origin.get('_raw')}"
    origin_id = origin.get('id')
    if origin_id is not None:
        detail += f" origin_id={origin_id}"

    # 데몬에는 요청 문맥이 없어 audit_log() 의 자동 행위자 추출이 통하지 않는다.
    # 출처에서 뽑은 값을 명시적으로 넘긴다.
    user_id = origin_id if origin.get('type') == 'user' else None
    audit_log(
        OUTPUT_CONTROL,
        target_type='Output',
        target_id=entry.get('output_id'),
        target_name=entry.get('output_name'),
        result=entry.get('result', 'success'),
        detail=detail,
        user_id=user_id,
        username=origin.get('name'),
        ip_address=entry.get('ip_address'),
    )


def _write_batch(batch):
    if not batch:
        return 0
    try:
        with _flask_app.app_context():
            for entry in batch:
                try:
                    _flush_one(entry)
                except Exception:
                    logger.exception("감사 항목 기록 실패 — 건너뜁니다")
    except Exception:
        logger.exception("감사 flush 실패 — %s건 유실", len(batch))
        return 0
    return len(batch)


def _writer_loop():
    while not _stop_event.is_set():
        try:
            first = _q.get(timeout=1.0)
        except queue.Empty:
            _report_drops()
            continue

        batch = [first]
        while len(batch) < _BATCH:
            try:
                batch.append(_q.get_nowait())
            except queue.Empty:
                break

        _write_batch(batch)
        _report_drops()


def _report_drops():
    global _dropped
    with _dropped_lock:
        if _dropped:
            logger.warning(
                "Output 감사 항목 %s건을 큐 포화로 버렸습니다 (상한 %s)",
                _dropped, _MAXSIZE)
            _dropped = 0


def start_writer(flask_app):
    """데몬 기동 시 1회 호출. flask_app 은 app_context() 제공용."""
    global _writer_thread, _flask_app
    if not _ENABLED:
        logger.info("Output 감사 기록이 비활성화돼 있습니다 (AOT_OUTPUT_AUDIT=0)")
        return
    if _writer_thread is not None and _writer_thread.is_alive():
        return
    _flask_app = flask_app
    _stop_event.clear()
    _writer_thread = threading.Thread(
        target=_writer_loop, name='OutputAuditWriter', daemon=True)
    _writer_thread.start()
    logger.info("Output 감사 writer 를 시작했습니다")


def stop_writer(timeout=5):
    """writer 를 멈추고 **남은 큐를 동기로 마저 쓴다.**

    데몬 종료 경로가 각 Output 의 Shutdown State 를 하드웨어에 내보내는데, 그
    기록이 큐에 있는 채로 프로세스가 죽으면 "종료가 장치를 껐다"는 사실이 통째로
    사라진다. 정확히 그 기록이 필요해서 만든 기능이므로 여기서 흘리면 안 된다.
    """
    _stop_event.set()
    if _writer_thread is not None:
        _writer_thread.join(timeout)

    if _flask_app is None:
        return
    remaining = []
    while True:
        try:
            remaining.append(_q.get_nowait())
        except Exception:
            break
    written = _write_batch(remaining)
    if written:
        logger.info("종료 시 감사 %s건을 마저 기록했습니다", written)
    _report_drops()
