# coding=utf-8
"""측정값 신선도 판정의 정본 — 장치가 자기 유효 수명을 갖는다 (p6_55).

## 왜 한 곳인가

"이 값이 아직 쓸 만한가" 를 묻는 자리가 다섯이다(시설 센서 · 대지 요약 ·
`/data_batch` · AI 날씨 도구 · 지도 위젯). 다섯이 각자 규칙을 들고 있으면
갈라지고, 갈라지면 같은 센서가 화면마다 다른 상태로 보인다 — 이 도메인이
이미 크게 데인 실패가 "읽는 경로마다 기준이 다름" 이다.

그래서 **DB 를 읽는 자리와 우선순위를 정하는 자리는 여기 하나뿐**이다.
배수·하한·상한은 자리마다 근거가 달라 인자로 받는다(아래 참조).

## 우선순위

    장치값(Input.max_age_s)  >  호출자 요청  >  주기 파생  >  하한

장치가 비어 있으면(NULL) p6_55 이전과 **완전히 같이** 동작한다. 업그레이드로
조용히 달라지는 설치가 없다는 뜻이고, 이것이 이 컬럼을 nullable 로 둔 이유다.

## 두 갈래 — 판정과 창은 규칙이 다르다

| | 함수 | 장치값의 뜻 |
|---|---|---|
| **판정** | `effective_max_age` | "이보다 오래됐으면 안 쓴다" — 그대로 이긴다 |
| **창** | `widen_window` | "적어도 이만큼은 되돌아봐라" — **넓히기만** 한다 |

창을 좁히면 안 된다. `/data_batch` 의 계약이 "요청창이 하한" 이라, 장치값으로
좁히면 사용자가 30일을 요청해도 1시간만 보게 된다 — 그래프가 통째로 빈다.
반대로 판정에서 넓히기만 하면 제어의 안전 결정(`requested`)을 장치가 못 좁혀
"오래된 값으로는 작동하지 않는다" 는 뜻이 무의미해진다.

## 배수를 여기서 통일하지 않는 이유

자리마다 근거가 실측으로 다르다 — 표시 경로는 3배(표본 2회 유실까지),
시설 센서와 지도 위젯은 2배(1회). 하나로 합치면 그 근거가 사라지고, 다음
사람이 "왜 3인가" 를 물을 자리가 없어진다. 인자로 받아 호출부에 남긴다.
"""

import logging
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# (주기, 장치 명시 max_age) — 둘 다 모를 수 있다.
Freshness = Tuple[Optional[float], Optional[int]]

UNKNOWN: Freshness = (None, None)


def freshness_by_device(device_ids) -> Dict[str, Freshness]:
    """{Input.unique_id: (주기(초), max_age_s(초) or None)} — IN 조회 1회.

    **DB·앱 컨텍스트 없이도 도는 것이 계약이다.** 호출부 중 일부는 그것 없이
    단위 테스트되고(시설 센서 모듈), 실패하면 호출자가 자기 기본값으로
    떨어지는 것이 맞다 — 신선도를 모른다고 화면 전체가 죽어서는 안 된다.

    `max_age_s` 는 p6_55 에서 생겼다. **컬럼이 없는 DB 에서도 돌아야 한다**
    (업그레이드 전 설치). 그래서 조회가 실패하면 주기만으로 다시 시도한다 —
    한 번에 실패로 처리하면 업그레이드 도중의 설치가 신선도 판정을 통째로
    잃는다.

    Input 만 대상이다 — Output/Function/PID 의 주기는 "센서가 언제 값을
    낼지" 와 의미가 달라 판정 근거가 되지 않는다. 종류를 미리 가릴 필요는
    없다: Input 이 아니면 아무 행도 안 나와 자연히 미지가 된다.
    """
    ids = sorted({i for i in (device_ids or []) if i})
    if not ids:
        return {}

    # ⚠ **`Input.query` 만으로는 데몬에서 아무것도 못 읽는다.** 그것은 Flask
    #   앱 컨텍스트를 요구하는데 데몬 프로세스에는 그것이 없어, 아래 `except`
    #   가 조용히 삼키고 `{}` 를 돌려준다. 그러면 호출자는 "이 장치를 모른다"
    #   로 읽고 자기 기본값으로 떨어진다 — 즉 **`Input.max_age_s` 와
    #   `Input.period` 가 제어 경로에서 통째로 죽는다.** 화면에서는 잘 되므로
    #   증상이 "설정했는데 제어만 안 먹는다" 로 나타나고, 에러는 어디에도
    #   안 남는다(2026-08-28 실측: 데몬에서 `freshness_by_device()` → `{}`).
    #   데몬 안전 접근자를 **먼저** 쓰고 그것이 못 도는 자리(앱 컨텍스트만 있는
    #   단위 테스트)에서만 `Input.query` 로 떨어진다.
    for reader in (_rows_via_daemon, _rows_via_orm):
        try:
            rows = reader(ids)
        except Exception as exc:                             # noqa: BLE001
            logger.debug('[Freshness] 조회 실패(%s) — 다음 경로 시도: %s',
                         reader.__name__, exc)
            continue
        if rows:
            return rows
    logger.debug('[Freshness] 장치 신선도를 읽지 못했습니다 — 호출자 기본값 사용')
    return {}


def _rows_via_daemon(ids) -> Dict[str, Freshness]:
    """데몬 경로 — 앱 컨텍스트 없이 돈다."""
    from aot.databases.models import Input
    from aot.utils.database import db_retrieve_table_daemon

    table = db_retrieve_table_daemon(Input)
    if table is None or isinstance(table, list):
        return {}                       # 조회 실패는 빈 결과로 온다(예외가 아니다)
    out: Dict[str, Freshness] = {}
    for row in table.filter(Input.unique_id.in_(ids)).all():
        # `max_age_s` 는 p6_55 에서 생겼다 — 컬럼이 없는 DB(업그레이드 전)에서는
        # 속성이 없을 수 있으므로 주기만이라도 살린다.
        out[row.unique_id] = (row.period, getattr(row, 'max_age_s', None))
    return out


def _rows_via_orm(ids) -> Dict[str, Freshness]:
    """Flask 경로 — 앱 컨텍스트가 있을 때."""
    from aot.databases.models import Input

    try:
        rows = Input.query.filter(Input.unique_id.in_(ids)).with_entities(
            Input.unique_id, Input.period, Input.max_age_s).all()
        return {uid: (period, max_age) for uid, period, max_age in rows}
    except Exception:                                        # noqa: BLE001
        rows = Input.query.filter(Input.unique_id.in_(ids)).with_entities(
            Input.unique_id, Input.period).all()
        return {uid: (period, None) for uid, period in rows}


def lookup(table: Dict[str, Freshness], device_id) -> Freshness:
    """`freshness_by_device` 결과에서 한 장치를 꺼낸다. 없으면 `(None, None)`.

    `table.get(id) or UNKNOWN` 을 호출부마다 쓰면 언젠가 한 곳이 `.get(id)` 만
    쓰고 None 을 튜플처럼 풀다 터진다.
    """
    return table.get(device_id) or UNKNOWN


def as_seconds(value) -> Optional[int]:
    """초 단위 정수로 바꾸되 **미지정을 보존한다**(`None` → `None`).

    `int(max_age)` 로 감싸는 호출부가 미지정을 0 이나 예외로 바꿔 버리는 것이
    이 모듈의 자동 경로를 막는 실제 원인이었다 — `requested=None` 분기에
    영영 도달하지 못한다. 변환을 한 곳에 둔다.

    `0` 은 '제한 없음' 이 아니라 **'안 정했다'** 다. `Input.max_age_s` 저장
    핸들러가 0 을 NULL 로 눕히는 것과 같은 판단이고, 반대로 읽으면 실수로 0 을
    넣은 장치의 값이 영원히 유효해져 몇 시간 전 값으로 장비가 움직인다.
    """
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return int(number) if number > 0 else None


def effective_max_age(requested: Optional[float],
                      period: Optional[float],
                      device_max_age: Optional[int] = None,
                      floor: int = 300,
                      factor: float = 2.0) -> int:
    """**판정**용 유효 수명(초) — "이보다 오래된 값은 안 쓴다".

    Args:
        requested:      호출자가 명시한 값. None 이면 "주기로 정해라"(표시 경로).
        period:         `Input.period`.
        device_max_age: `Input.max_age_s`. 있으면 **가장 먼저** 이긴다.
        floor:          주기 파생의 하한. 주기를 모를 때의 기본값이기도 하다.
        factor:         주기에 곱할 배수.

    장치값이 호출자 요청보다 앞이다. 제어(env_coordinator)도 숫자를 들고 올 수
    있으므로, 요청을 앞에 두면 제어 경로에서 장치별 설정이 통째로 무시된다
    — 그러면 컬럼을 만든 의미가 없다. 현장 센서는 갱신 주기가 제각각이라
    (LoRaWAN 하트비트 30~60분 · MQTT 60초 · 기상청 10분) 호출자가 든 숫자
    하나로 전부를 판정할 수 없다는 것이 이 순서의 근거다.
    """
    if device_max_age:
        try:
            return int(device_max_age)
        except (TypeError, ValueError):
            pass
    if requested is not None:
        try:
            return int(requested)
        except (TypeError, ValueError):
            pass
    if period:
        try:
            return int(max(floor, float(period) * factor))
        except (TypeError, ValueError):
            pass
    return int(floor)


def widen_window(requested: Optional[float],
                 period: Optional[float],
                 device_max_age: Optional[int] = None,
                 factor: float = 3.0,
                 cap: Optional[float] = None) -> Optional[float]:
    """**조회 창**(초) — "적어도 이만큼은 되돌아본다". 절대 좁히지 않는다.

    판정과 달리 장치값은 하한 후보 중 하나로만 참여한다. 사용자가 30일을
    요청했는데 장치가 1시간이라고 좁혀 버리면 그래프가 통째로 빈다 — 장치가
    말하는 것은 "이만큼은 봐야 값이 있다" 이지 "이보다 멀리 보지 말라" 가
    아니다.

    `requested` 가 숫자가 아니면 그대로 돌려준다(호출부의 '0' = 무제한 관례를
    여기서 해석하지 않는다).
    """
    try:
        req = float(requested)
    except (TypeError, ValueError):
        return requested
    if req <= 0:                     # '0' = 무제한 — 넓힐 것도 좁힐 것도 없다
        return requested
    floor = req
    if period:
        try:
            floor = max(floor, float(period) * factor)
        except (TypeError, ValueError):
            pass
    if device_max_age:
        try:
            floor = max(floor, float(device_max_age))
        except (TypeError, ValueError):
            pass
    if cap:
        floor = min(floor, float(cap))
    return floor
