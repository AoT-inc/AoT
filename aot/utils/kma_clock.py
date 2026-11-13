"""기상청(KMA) 원천 데이터의 시계 — 외부 계약상 KST 인 곳을 한 군데로 모은다.

기상청 API 허브(`sfc_nc_var.php` 의 `tm1`/`tm2` 와 응답의 시각, 단기예보 `forecast.json` 의
시간대 키가 없는 옛 파일)는 **발표처가 정한 한국 표준시**로 말한다. 이것은 장치·장소의 설정이
아니라 외부 계약이다 — 사용자의 장소 시간대와 섞지 말고, 요청·응답을 해석하는 자리에서만
이 모듈을 거친다. 결과를 *보여 주거나 날짜로 접는* 자리는 장소 시간대(`timekit.tz_of`)를 쓴다.
"""
from datetime import datetime

from aot.utils.timekit import to_tz, wall_to_utc

KMA_TZ_NAME = 'Asia/Seoul'   # tz-ok: 기상청 API 가 정한 원천 시계(외부 계약) — 이 상수 한 곳만


def kma_wall(value) -> datetime:
    """순간(epoch·datetime·ISO) → 기상청 요청에 쓰는 KST 벽시계(naive)."""
    return to_tz(value, KMA_TZ_NAME).replace(tzinfo=None)


def kma_wall_to_utc(wall) -> datetime:
    """기상청이 준 KST 벽시계(naive datetime 또는 문자열) → 순간(UTC aware)."""
    return wall_to_utc(wall, KMA_TZ_NAME)
