# coding=utf-8
"""일지 빌드(백그라운드 생성) 수명주기와 비용 추정."""
import threading

from ._shared import MAX_JOURNAL_ROWS, resolve_target_row
from .calc import (
    _channel_info, _rows_for, build_journal_for_target, count_channels_detail,
    resolve_devices,
)
from .render import journal_to_jsonable, summarize_for_card


def first_data_at(target_type, target_id, max_channels=12):
    """이 대상의 자료가 **실제로 언제부터** 있는가 → date | None.

    대지·구역에는 구획의 `started_on` 같은 날짜가 없어, 사람이 감으로 기간을
    넣으면 앞쪽이 통째로 빈 문서가 나온다(실측: 10개 버킷 중 7개). 그 시작
    시각은 시스템이 아는 사실이므로 추측시킬 이유가 없다.

    채널마다 `first()` 한 번씩만 묻는다. **채널이 많으면 앞의 몇 개만 본다** —
    이건 폼을 채워 주는 편의 기능이라 사람을 기다리게 할 값이 아니고, 가장 이른
    시각을 정확히 맞히지 못해도 사람이 고쳐 넣으면 된다.
    """
    from aot.databases.models import DeviceMeasurements
    from aot.utils.influx import query_string
    from aot.utils.timekit import to_tz

    target_row = resolve_target_row(target_type, target_id)
    sensor_ids, actuators, _unassigned, _area = resolve_devices(
        target_type, target_row)

    ids = [d for d in (sensor_ids or []) if d]
    ids += [a.get('output_id') for a in (actuators or []) if a.get('output_id')]
    if not ids:
        return None

    rows = DeviceMeasurements.query.filter(
        DeviceMeasurements.device_id.in_(ids)).all()

    from aot.utils.device_tz import resolve_location_tz
    tz = resolve_location_tz(target_id)

    earliest = None
    looked = 0
    for dm in rows:
        if looked >= max_channels:
            break
        channel, unit, _display, measure_filter = _channel_info(dm)
        if unit is None:
            continue
        looked += 1
        try:
            tables = query_string(unit, dm.device_id, channel=channel,
                                  measure=measure_filter, value='FIRST')
        except Exception:
            continue
        for table in (tables or []):
            for rec in table.records:
                stamp = rec.get_time()
                if stamp is None:
                    continue
                if earliest is None or stamp < earliest:
                    earliest = stamp
    if earliest is None:
        return None
    try:
        return to_tz(earliest, tz).date()
    except Exception:
        return None


# ── 자원 보호 (§13) ─────────────────────────────────────────────────────────
#
# 이 앱은 라즈베리파이 같은 저사양 기기에서 **데몬(장치 제어)과 같은 기기 위에**
# 웹이 함께 돈다는 것이 실제 배포 환경이다. 일지 생성은 채널마다 InfluxDB
# 쿼리가 나가는 작업이라, 큰 zone/site 를 통째로 고르면 짧은 시간에 쿼리가
# 몰려 CPU·IO 를 잡아먹고 다른 요청이나 데몬 동작을 지연시킨다.
#
# 새 작업 큐 시스템을 들여오지 않는다. 이 저장소가 이미 쓰는 패턴만 재사용한다:
#
#   a) 예방이 우선 — 시작하기 전에 세어 보고 넘으면 **시작하지 않는다**.
#   b) 백그라운드 스레드 + 전역 단일 실행 잠금 (routes_geo._start_overlay_tiling).
#   c) 채널 간 페이싱 (QUERY_DUTY — LoRaWAN 다운링크와 같은 원칙).
#   d) 중간에 죽은 작업 회수 — 저사양 기기는 재시작이 드물지 않다.

#: 한 일지가 쏠 수 있는 InfluxDB 쿼리 수 상한. 환경 채널당 3회(min/max/mean) +
#: 제어 채널당 1회(sum)로 세며, **기간과 무관**하다.
#:
#: ⚠ 세 상한은 서로 다른 것을 잡고, **실제로 걸리는 것은 대개 행 수 하나**다.
#:   실측(2026-09-05, 김제 3-1 — 환경 15채널 중 원형 2 + 제어 1):
#:
#:       일수     쿼리      행     판정
#:          1       44    2,472   ok
#:         51       44  126,072   ok
#:        202       44  499,344   ok
#:        205       44  506,760   too-much-data      ← 여기서 걸린다
#:       1101       44           period-too-long     ← 이미 한참 전에 걸렸다
#:
#:   쿼리 수는 기간이 아무리 길어도 44 로 고정이라 상한 240 에 닿지 않는다.
#:   기간 상한 1,100 일도 이 규모에서는 **도달 불가**다 — 하루 행 수가
#:   500,000/1,100 ≈ 455 미만일 때만 기간이 먼저 걸리고, 그것은 대략 환경
#:   채널 6개 미만인 대상뿐이다.
#:
#:   그래서 `period-too-long` 안내("기간이 너무 깁니다")는 채널이 아주 적은
#:   대상에서만 나온다. **"기간을 줄이세요" 라고 말하는 자리는 실제로는
#:   `too-much-data` 쪽**이고, 그 문구가 기간과 범위를 함께 말하는 이유가
#:   여기 있다. 셋 중 하나를 만질 때는 이 관계를 함께 볼 것 — 쿼리 상한만
#:   낮추면 아무 일도 안 일어나고, 행 상한만 올리면 기간 상한이 그제야
#:   의미를 갖는다.
MAX_QUERIES_PER_JOURNAL = 240

#: 기간 상한(일). 횟수 상한만으로는 **스캔 부하가 안 잡힌다** — 채널 1개짜리
#: 5년 일지는 상한을 여유롭게 통과하면서 단일 쿼리로는 가장 무겁다. Influx 가
#: 훑는 점 수는 기간에 비례하기 때문이다.
MAX_JOURNAL_DAYS = 1100          # ≈ 3년

#: 앱 전체에서 일지 생성은 **한 번에 하나**.
#:
#: ⚠ 이것이 "앱 전체" 로 성립하는 근거는 `install/gunicorn_conf.py` 의
#:   **`workers = 1`** 이다(스케줄러 때문에 1로 고정돼 있다). 워커를 늘리면 이
#:   잠금은 프로세스마다 따로 생겨 보장이 조용히 깨진다 — 그때는 DB 를 쓰는
#:   잠금으로 바꿔야 한다.
_BUILD_LOCK = threading.Lock()

#: 'running' 인 채 이만큼 지난 행은 죽은 것으로 보고 회수한다(§13d).
STALE_RUNNING_MINUTES = 30


def estimate_journal_cost(target_type, target_id, start_date, end_date,
                          measurements=None):
    """집계를 **시작하기 전에** 비용을 센다 → dict.

    ```
    {'ok': bool, 'reason': str|None,
     'env_channels', 'control_channels', 'queries', 'days', 'rows'}
    ```

    `ok=False` 면 라우트가 400 으로 거절한다 — **몰래 일부만 잘라 보여주지
    않는다.** 무엇을 뺐는지 모르는 채로 "됐다" 고 말하는 것이 이 저장소가
    반복해서 겪은 실패다.

    세는 기준은 실제로 도는 것과 같아야 한다(`resolve_devices`·`count_channels`
    를 그대로 쓴다) — 게이트가 따로 세면 통과해 놓고 다르게 도는 일이 생긴다.
    구획의 구역 폴백은 거리(기하)로만 정해져 기간과 무관하므로, 여기서 다시
    불러도 실제 집계와 항상 같은 센서를 센다.
    """
    days = (end_date - start_date).days + 1
    target_row = resolve_target_row(target_type, target_id)
    sensor_ids, actuators, _unassigned, _area = resolve_devices(
        target_type, target_row)

    env_channels, circular_channels = count_channels_detail(sensor_ids,
                                                            measurements)
    control_channels = len([a for a in actuators if a.get('output_id')])
    # 원형 채널은 집계 3회가 아니라 **원자료 조회 1회**다(`_circular_channel_stats`).
    queries = ((env_channels - circular_channels) * 3 + circular_channels
               + control_channels)
    rows = _rows_for(env_channels, circular_channels, control_channels, days)

    reason = None
    if days > MAX_JOURNAL_DAYS:
        reason = 'period-too-long'
    elif queries > MAX_QUERIES_PER_JOURNAL:
        reason = 'too-many-channels'
    elif rows > MAX_JOURNAL_ROWS:
        reason = 'too-much-data'

    return {'ok': reason is None, 'reason': reason,
            'env_channels': env_channels, 'control_channels': control_channels,
            'queries': queries, 'days': days, 'rows': rows}


def reclaim_stale_builds(minutes=None):
    """중간에 죽은 'running' 행을 'error' 로 회수한다 → 회수한 개수.

    빌드 중 프로세스가 재시작되면(저사양 기기에서 드물지 않다) 그 행은 영원히
    `'running'` 으로 남고, 화면은 사용자에게 "잠시 후 새로고침" 을 **영원히**
    말하게 된다. 잠금은 프로세스와 함께 사라지므로 다시 만드는 것을 막는 것도
    없다 — 회수해서 "다시 시도" 를 말할 수 있게 한다.

    허브 라우트 진입 시 부른다(§8).
    """
    from datetime import timedelta as _td

    from aot.aot_flask.extensions import db
    from aot.databases.models import GeoJournal
    from aot.utils.timekit import utc_now

    cutoff = (utc_now() - _td(minutes=minutes or STALE_RUNNING_MINUTES))
    cutoff = cutoff.replace(tzinfo=None)      # started_at 은 naive UTC 로 저장된다
    rows = GeoJournal.query.filter(
        GeoJournal.status == 'running',
        GeoJournal.started_at.isnot(None),
        GeoJournal.started_at < cutoff).all()
    for row in rows:
        row.status = 'error'
        row.error_message = 'build-interrupted'
    if rows:
        db.session.commit()
    return len(rows)


def _run_journal_build(app, journal_uuid, measurements=None,
                       granularity=None, wait=False):
    """백그라운드에서 일지 하나를 채운다. 선례: `routes_geo._start_overlay_tiling`.

    ## 잠금이 바깥이 아니라 **안**에 있는 이유

    `with _BUILD_LOCK:` 을 스레드를 띄우기 **전**에 걸면 요청 스레드가 거기서
    막혀 §13b 의 목적(웹 요청을 막지 않는다)이 무너진다. 스레드 안에서 걸어야
    두 번째 요청도 즉시 돌아가고, 실제 InfluxDB 부하만 순서를 선다.
    """
    from aot.aot_flask.extensions import db
    from aot.databases.models import GeoJournal
    from aot.utils.timekit import utc_now

    def _work():
        with app.app_context():
            try:
                with _BUILD_LOCK:
                    row = GeoJournal.query.filter_by(
                        unique_id=journal_uuid).first()
                    if row is None or row.status not in ('pending', 'running'):
                        return          # 지워졌거나 이미 끝났다
                    row.status = 'running'
                    row.started_at = utc_now().replace(tzinfo=None)
                    db.session.commit()

                    data = build_journal_for_target(
                        row.target_type, row.target_id,
                        row.period_start, row.period_end,
                        measurements=measurements, granularity=granularity)

                    # 오래 걸리는 작업이라 **행을 다시 읽는다** — 그 사이
                    # 지워졌을 수 있다(선례의 "the row may have changed").
                    row = GeoJournal.query.filter_by(
                        unique_id=journal_uuid).first()
                    if row is None:
                        return
                    title, summary = summarize_for_card(data)
                    row.data = journal_to_jsonable(data)
                    row.tz_name = (data.get('target') or {}).get('tz_name')
                    row.title = title[:160]
                    row.summary = summary
                    row.error_message = None
                    row.status = 'done'
                    db.session.commit()
                    app.logger.info('[journal] built %s (%s, %d buckets)',
                                    journal_uuid, data.get('granularity'),
                                    len(data.get('buckets') or []))
            except Exception as exc:
                app.logger.exception('[journal] build failed for %s',
                                     journal_uuid)
                try:
                    row = GeoJournal.query.filter_by(
                        unique_id=journal_uuid).first()
                    if row is not None:
                        row.status = 'error'
                        row.error_message = str(exc)[:200]
                        db.session.commit()
                except Exception:
                    pass
            finally:
                db.session.remove()

    if wait:
        # 부르는 쪽이 오래 사는 프로세스가 아닐 때(MCP stdio)는 **여기서
        # 끝낸다.** 스레드로 띄우면 연결이 끊기는 순간 프로세스와 함께 죽고,
        # 행은 영영 'running' 으로 남는다(실측: MCP 로 만든 일지가 5분 뒤에도
        # running, 버킷 0). `reclaim_stale_builds` 가 나중에 error 로 회수해
        # 주지만 그것은 청소이지 생성이 아니다.
        _work()
        return
    threading.Thread(target=_work, daemon=True,
                     name='journal_%s' % str(journal_uuid)[:8]).start()


def start_journal_build(journal_uuid, measurements=None, granularity=None,
                        wait=False):
    """요청 스레드에서 부른다 — 앱 객체를 잡아 백그라운드로 넘긴다.

    `current_app` 은 요청 컨텍스트에 매여 있어 스레드로 그대로 넘기면 안 된다
    (선례가 `_get_current_object()` 를 쓰는 이유).

    `measurements`(고른 측정값)는 **행에 저장하지 않고 클로저로 넘긴다.**
    스레드가 같은 프로세스 안에서 돌기 때문이고, 새 컬럼과 마이그레이션을
    만들 이유가 없다.

    ⚠ `wait=True` 는 **스레드를 띄우지 않고 여기서 끝낸다.** 부르는 쪽이
    오래 사는 프로세스가 아닐 때(MCP stdio 는 연결이 끊기면 프로세스가 죽는다)
    필요하다 — 그때 백그라운드 스레드는 시작하자마자 함께 죽고, 행은 영영
    'running' 으로 남는다. 재시작으로 중단된 빌드는 재시도하지 않고 `error` 로
    회수되므로(§13d) 나중에 다시 읽을 일도 없다. **무엇을 실었는가는 완성된
    스냅샷(`data['measurements']`)에 남는다** — 그쪽이 문서의 기록이다.
    """
    from flask import current_app

    _run_journal_build(current_app._get_current_object(), journal_uuid,
                       measurements=measurements, granularity=granularity,
                       wait=wait)
