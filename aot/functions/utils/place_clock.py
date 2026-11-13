# coding=utf-8
"""Function 모듈이 사람에게 보이는 시각(LCD·OLED·파일명)을 장소 시계로 적는 입구.

`time.strftime(...)` 와 tz 없는 `datetime.fromtimestamp(...)` 는 컨테이너(대개 UTC)
시계로 적혀, 한국 현장의 화면이 아홉 시간 어긋난다. 시각은 `timekit` 의 `to_tz`
로 이 Function 이 걸린 장소(`where` = Function 의 unique_id)의 시계로 바꿔 적는다.
화면 폭이 좁은 곳(16x2)이 있어 시간대 라벨은 붙이지 않는다 — 라벨이 필요한 글(메시지)은
`timekit.format_labeled` 를 쓴다.
"""
from aot.utils.timekit import to_tz, utc_now

DISPLAY_FORMAT = '%Y-%m-%d %H:%M:%S'


def place_time_str(epoch, where, fmt=DISPLAY_FORMAT):
    """epoch(초) 를 `where` 장소의 시계로. 못 읽는 값이면 빈 문자열."""
    local = to_tz(epoch, where)
    return local.strftime(fmt) if local is not None else ''


def place_now_str(where, fmt=DISPLAY_FORMAT):
    """지금 시각을 `where` 장소의 시계로."""
    return to_tz(utc_now(), where).strftime(fmt)
