# coding=utf-8
"""Site-wide LoRaWAN downlink pacing (single shared rate limiter).

A site typically has ONE LoRaWAN gateway, which is half-duplex: while it is
transmitting a downlink it cannot hear device uplinks. If many downlinks are
enqueued at once — valve control from the on/off output, CFG/class changes from
the LoRaWAN class scheduler, plus retries — ChirpStack hands them to the gateway
back-to-back, the gateway floods the air, and the device ACK uplinks (FP11/FP12)
that the retry logic depends on get lost, triggering MORE retries
(self-reinforcing congestion).

Every downlink path shares the ONE limiter in this module so the whole site is
paced together (not just per module). Outputs and functions run in the same AoT
daemon process, so these module-level globals are genuinely shared.

Usage — call pace_send() and drop the downlink if it returns False (never call
it while holding a lock: it sleeps):

    from aot.utils.lorawan_pacing import pace_send
    if not pace_send():
        return False  # backlog too deep; sending now would defeat the pacing
    # ... perform the actual enqueue ...
"""

import logging
import threading
from time import sleep, time

logger = logging.getLogger(__name__)

# Minimum gap between ANY two downlinks site-wide, sized so the half-duplex
# gateway is actually IDLE when the device's ACK comes back.
#
# The original 1.5 s assumed a short downlink. It is not: a Class C downlink goes
# out in RX2, and with the KR920 default rx2_dr=0 (SF12) a ~16 B frame occupies
# ~1.32 s of gateway TX time — during which the concentrator cannot receive on
# ANY of its channels. Measured on site (2026-07-27), the device's FP11 ctrl_ack
# lands ~1.7 s after dispatch, i.e. squarely inside the NEXT transmission when
# the gap is 1.5 s: the ACK was being lost structurally, not by chance. Busy
# minutes showed 23-26 downlinks/min => 50-57 % of the minute deaf, and each lost
# ACK triggered a retry, which produced yet another 1.32 s of deafness.
#
# 4.0 s => ~1.32 s TX + ~2.7 s listening per slot (33 % TX duty), so both the
# ctrl_ack (~1.7 s) and a valve's completion status land in a quiet window.
#
# ⚠ **이 상수는 RX2 데이터레이트에 묶여 있다.** 둘은 함께 움직여야 한다 —
# 한쪽만 바꾸면 게이트웨이가 포화되거나(간격만 줄임) 이득이 없다(DR만 올림).
#
#     rx2_dr=0 (SF12)  airtime ~1.32 s  ->  간격 4.0 s
#     rx2_dr=2 (SF10)  airtime ~0.37 s  ->  간격 1.5 s   ← 현재
#     rx2_dr=3 (SF9)   airtime ~0.19 s  ->  간격 0.8 s
#
# RX2 DR 은 ChirpStack 쪽 설정이다(`/etc/chirpstack/region_kr920.toml` 의
# `rx2_dr`). **거기를 SF12 로 되돌린다면 이 값도 4.0 으로 되돌릴 것** — 안 그러면
# 1.32초짜리 송신을 1.5초 간격으로 쏘게 되어(88 % duty) 게이트웨이가 사실상 내내
# 귀먹고, 이 모듈이 막으려던 바로 그 붕괴가 재현된다.
#
# 1.5 s => ~0.37 s TX + ~1.13 s listening (25 % TX duty). SF12 시절의 33 % 보다
# 오히려 여유가 있고, 업링크는 ADR 로 SF7 근처까지 내려가 ACK 자체도 훨씬 짧다
# (실측 2026-09-02 aot-004: RX1 다운링크가 SF7 로 나가고 있었다).
#
# aot-004 실측(2026-09-01 rx2_dr 0->2 전환, 밤새 관수 검증): 전환 뒤 확인 실패
# 0건. 전환 전 같은 서버는 관수 시간대마다 시간당 6~15건이었다.
MIN_GLOBAL_DOWNLINK_INTERVAL_S = 1.5
# Cap how long a single send may block waiting for its slot. Past this the
# downlink is DROPPED, not sent late.
#
# It used to be sent late: the cap clamped the returned sleep but the slot had
# already been reserved, so once the backlog passed ~7 deep every caller slept
# 30 s and then transmitted at once — the pacing silently inverted into a
# thundering herd at exactly the congestion it exists to prevent. A valve
# command that has been queued 30 s is stale anyway, so failing it visibly beats
# flooding the air with it.
MAX_PACE_WAIT_S = 30.0

_PACE_LOCK = threading.Lock()
_NEXT_SLOT = [0.0]  # mutable holder: earliest epoch the next downlink may go out


def claim_send_slot(min_interval=MIN_GLOBAL_DOWNLINK_INTERVAL_S,
                    max_wait=MAX_PACE_WAIT_S):
    """Reserve the next global send slot and return seconds to sleep before sending.

    Returns None if the backlog is already deeper than max_wait, in which case
    NO slot is reserved and the caller must drop the downlink — reserving one
    anyway would push the queue out further for everybody behind it.

    The lock is held only to claim a monotonically increasing slot (fast); the
    caller does the sleeping outside the lock, so a slow or failing send never
    stalls the rest of the site.
    """
    try:
        mi = float(min_interval)
    except Exception:
        mi = MIN_GLOBAL_DOWNLINK_INTERVAL_S
    if mi < 0:
        mi = 0.0
    with _PACE_LOCK:
        now = time()
        slot = now if now >= _NEXT_SLOT[0] else _NEXT_SLOT[0]
        if slot - now > max_wait:
            return None
        _NEXT_SLOT[0] = slot + mi
    return max(0.0, slot - now)


def pace_send(min_interval=MIN_GLOBAL_DOWNLINK_INTERVAL_S,
              max_wait=MAX_PACE_WAIT_S):
    """Wait for this downlink's slot. False means drop it instead of sending.

    Every downlink path goes through here so the drop decision lives in one
    place: callers that merely swallowed an exception and transmitted anyway
    were how the pacing got bypassed before.
    """
    wait = claim_send_slot(min_interval=min_interval, max_wait=max_wait)
    if wait is None:
        return False
    if wait > 0:
        sleep(wait)
    return True


# --------------------------------------------------------------------------- #
# 전송 디스패처 — 페이싱 대기를 호출 스레드에서 떼어낸다
# --------------------------------------------------------------------------- #
#
# ## 왜 필요한가
#
# 위의 `pace_send()` 는 **호출 스레드를 최대 MAX_PACE_WAIT_S 만큼 재운다.** 그런데
# 출력 제어는 Pyro5 RPC 를 타고 들어오고 그 왕복 예산은 **8초**(하드캡 10초,
# `aot_client._MAX_RPC_TIMEOUT`)다. 페이싱 간격이 4초이므로 동시에 들어온 세
# 번째 명령부터 대기가 8초에 닿는다 — 즉 **밸브 3개를 함께 조작하는 순간부터
# 호출자는 타임아웃을 본다.**
#
# 그리고 Pyro5 는 클라이언트가 포기해도 데몬 스레드를 멈추지 않는다. 명령은
# 결국 나가는데 호출자는 실패로 판정하고 재시도한다. 재시도는 슬롯을 새로
# 예약하므로 뒤에 선 모두의 대기가 늘고, 그래서 더 많은 오탐이 나고, 다시 더
# 많은 재시도가 붙는다 — **실패 판정이 진짜 실패를 만드는 되먹임**이다. 실측
# (aot-004, 2026-08-31): 관수 스텝 전환 시각에만 OFF 타임아웃 23건이 몰렸고,
# 그 밸브들은 실제로는 꺼져 있었다.
#
# 여기서는 호출자가 **큐에 넣고 즉시 돌아간다.** 페이싱은 전용 워커가 지킨다.
#
# ## 명령 큐가 아니라 의도 큐다
#
# 같은 대상(key)의 아직 안 나간 항목이 있으면 **새 것이 그 자리를 대신한다.**
# 밸브에게 의미 있는 것은 마지막 의도 하나뿐이라, 재시도나 재전송이 큐를
# 부풀리지 않는다. 되먹임을 정책으로 끊는 자리다.
#
# ⚠ 설정 명령(CFG·임의 페이로드)은 서로 다른 내용이라 **병합하면 안 된다** —
# 뒤엣것이 앞엣것을 지워 설정이 조용히 유실된다. 호출자가 고유 키를 준다.

# 큐에 담아 둘 수 있는 최대 항목 수. 넘으면 접수를 거부한다(조용히 버리지
# 않는다 — 호출자가 실패를 알아야 한다). 밸브 수십 개 + 설정 명령을 담고도
# 남을 만큼 두되 무한은 아니어야 한다.
MAX_QUEUE_DEPTH = 128

# 큐에서 이만큼 묵은 항목은 보내지 않고 버린다. 30초 기다린 밸브 명령은 이미
# 낡았다는 판단은 MAX_PACE_WAIT_S 와 같은 근거다(위 주석 참조).
MAX_QUEUE_AGE_S = MAX_PACE_WAIT_S

_Q_LOCK = threading.Condition()
_QUEUE = []          # [{'key','fn','at','deadline','label'}]
_WORKER = None
_DROPPED_STALE = [0]


def _worker_loop():
    while True:
        with _Q_LOCK:
            while not _QUEUE:
                _Q_LOCK.wait()
            item = _QUEUE.pop(0)

        # 너무 묵은 명령은 보내지 않는다. 지금 내보내 봐야 현재 의도가 아니다.
        if time() > item['deadline']:
            _DROPPED_STALE[0] += 1
            logger.error(
                "다운링크 폐기(%s): 큐에서 %.0f초를 기다려 이미 낡았습니다. "
                "누적 폐기 %d건", item.get('label') or item['key'],
                MAX_QUEUE_AGE_S, _DROPPED_STALE[0])
            continue

        # 슬롯 계산은 기존 리미터를 그대로 쓴다. 워커가 하나뿐이라 여기서
        # 백로그가 깊어질 수 없고(직전 전송 이후 간격만 기다린다), 혹시 다른
        # 경로가 pace_send() 를 쓰더라도 같은 타임라인을 공유하게 된다.
        # 간격은 **호출 시점에** 모듈 값을 읽는다. 함수 기본 인자로 두면 정의
        # 시점 값이 박혀, 운영 중 조정도 테스트의 단축도 먹지 않는다.
        interval = MIN_GLOBAL_DOWNLINK_INTERVAL_S
        wait = claim_send_slot(min_interval=interval)
        if wait is None:
            wait = interval
        if wait > 0:
            sleep(wait)

        try:
            item['fn']()
        except Exception:
            # 한 건의 전송 실패가 워커를 죽이면 이후 모든 제어가 멈춘다.
            logger.exception("다운링크 전송 중 예외(%s)", item.get('label') or item['key'])


def _ensure_worker():
    global _WORKER
    if _WORKER is not None and _WORKER.is_alive():
        return
    _WORKER = threading.Thread(
        target=_worker_loop, name='lorawan-downlink', daemon=True)
    _WORKER.start()


def submit_downlink(key, fn, label=None, merge=True):
    """전송을 큐에 맡기고 **즉시** 돌아간다.

    :param key: 병합 단위. 같은 key 의 미전송 항목은 이 항목으로 대체된다.
    :param fn: 실제 전송을 수행하는 무인자 콜러블(워커 스레드에서 실행).
    :param merge: False 면 기존 항목을 지우지 않고 나란히 줄을 선다(설정 명령).
    :return: 큐에 받아들였으면 True, 큐가 가득 차 거부했으면 False.

    True 는 **접수**를 뜻하지 전송 성공이 아니다. 실제 전송 결과는 장치
    확인(`ConfirmableOutputMixin`)이 판정한다 — 그 구분이 이 설계의 요점이다.
    """
    now = time()
    item = {'key': key, 'fn': fn, 'at': now,
            'deadline': now + MAX_QUEUE_AGE_S, 'label': label}
    with _Q_LOCK:
        if merge:
            for i, existing in enumerate(_QUEUE):
                if existing['key'] == key:
                    # 자리는 그대로 두고 내용만 바꾼다 — 뒤로 밀면 먼저 온
                    # 명령이 계속 밀려 굶는다.
                    item['deadline'] = existing['deadline']
                    _QUEUE[i] = item
                    _Q_LOCK.notify()
                    return True
        if len(_QUEUE) >= MAX_QUEUE_DEPTH:
            logger.error(
                "다운링크 큐가 가득 찼습니다(%d건) — 접수 거부: %s",
                len(_QUEUE), label or key)
            return False
        _QUEUE.append(item)
        _Q_LOCK.notify()
    _ensure_worker()
    return True


def backlog_seconds():
    """지금 접수하면 실제로 나가기까지 대략 얼마나 걸리는가.

    확인 창(`begin_command`)을 이만큼 늘리는 데 쓴다. 창을 접수 시각에 고정한
    채 두면 페이싱으로 늦게 나간 명령은 **창이 이미 닫힌 뒤에 전파돼** 확인이
    올 수 없고, 멀쩡한 장치가 통신 장애로 판정된다.
    """
    with _Q_LOCK:
        depth = len(_QUEUE)
    return depth * MIN_GLOBAL_DOWNLINK_INTERVAL_S


def queue_depth():
    with _Q_LOCK:
        return len(_QUEUE)


def _reset_for_test():
    """테스트 전용: 큐와 슬롯 타임라인을 비운다."""
    with _Q_LOCK:
        del _QUEUE[:]
    with _PACE_LOCK:
        _NEXT_SLOT[0] = 0.0
    _DROPPED_STALE[0] = 0
