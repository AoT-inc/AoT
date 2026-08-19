# coding=utf-8
"""대지/구역 도형을 두둑(식생 구획)으로 분할한다 — 순수 기하 계산.

설계 정본: docs/design/geo-vegetation-plot.md

## 왜 필요한가

`create_plot` 은 GeoJSON 폴리곤을 받는데, **LLM 은 구역이 지도 어디에 있는지
알 방법이 없다** — 어떤 도구도 구역 경계 폴리곤을 내주지 않는다. 그래서 좌표를
지어내면 엉뚱한 자리에 저장되고, 실패했다고 말해주지도 않는다(구역 밖이면
`zone_uuid` 가 null 로 남을 뿐이다).

여기서는 **사람이 이미 그려 둔 도형**(site/zone)을 입력으로 받아 서버가 나눈다.
LLM 이 만드는 숫자는 간격 하나뿐이고, 좌표는 하나도 만들지 않는다.

## 방향 — 기본은 가장 긴 변을 따른다

농경지는 대체로 직각을 선호하지만 대지가 비정형인 경우가 많다. 그럴 때 축(정북)
기준으로 자르면 두둑이 밭을 비스듬히 가로질러 자투리만 잔뜩 생긴다. 실제 농사는
**밭의 긴 방향을 따라** 두둑을 놓는다.

그 방향은 `dimensions()` 가 쓰는 것과 같은 **최소회전 외접사각형**에서 나온다 —
그 사각형의 긴 변이 곧 밭의 지배 방향이다. 방향을 그렇게 잡으면 비정형 가장자리는
교차 연산이 알아서 잘라내므로, 예외 처리를 따로 쓸 일이 없다.

### `orientation` — 기본값이 모드에 따라 갈린다

`strip_width_cm`(두둑 폭 지정)은 고랑 방향이 곧 배수·농기계 작업 방향이라 긴 변을
따르는 것이 실제로 맞다 — **주어지면(단독이든 `parts` 와 조합이든) 기본값은
`'long'`이다.**

`parts`(단순 N등분, "이 구역에 작물 5개 나눠 심기")는 두둑 개념이 없다. 긴 변을
그대로 따르면 조각이 가늘고 길어진다(2,618㎡ 구역을 5등분한 실사례: 6.43m×81.7m,
비율 12.7:1) — 서로 다른 작물을 나눠 심을 구획을 원했을 뿐인데 관리하기 불편한
모양이 나온다. 그래서 **`strip_width_cm` 이 없을 때(순수 `parts` 등분, 또는
`widths_cm` 만 준 경우)는 기본값이 `'short'` 다** — 짧은 변을 눕혀 그 반대쪽을
등분한다(같은 예: 6.43m×81.7m → 16.4m×32m, 비율 2:1). `orientation` 을 직접
주면(둘 중 어느 값이든) 그 값이 항상 이긴다 — 이 기본값 분기는 **생략했을 때만**
적용된다.

이 분기는 `split_shape()` 하나에만 있다 — 호출자(REST `routes_geo_plot.py`,
MCP `aot_data_tool_service.py`)는 `orientation` 을 생략(`None`)으로 그냥 통과시켜야
한다. 예전에는 두 호출자가 각자 `'long'` 을 하드코딩해 두어(두 곳이 따로 놀 여지가
있었다), 이제 여기 한 곳만 정본이다.

### `angle_deg` — `orientation` 을 덮어쓰는 임의 각도

긴 변/짧은 변 두 프리셋으로는 부족한 경우가 있다 — 지도에서 구역 중심을 지나는
기준선을 눈으로 보면서 원하는 각도로 돌려 나누고 싶을 때다(지도 UI 참조:
`aot-geo-plot.js`). `angle_deg` 를 주면 `_longest_edge_angle()`/
`orientation` 계산을 건너뛰고 그 각도를 조각이 놓이는 방향(elongation
axis)으로 그대로 쓴다 — `info['orientation_deg']` 와 같은 좌표계(로컬 평면에서
동쪽=0°, 반시계 방향)다. **`orientation` 과 동시에 주어지면 `angle_deg` 가
이긴다** — `orientation` 은 조용히 무시된다. 유효 범위는 `0 <= angle_deg < 180`
(축은 180도 주기이므로 그 밖의 값은 의미가 중복된다).

## 하지 않는 것

- **공원식 둘레 식재는 다루지 않는다.** 구역 둘레로 나무·꽃을 심고 내부는 규칙이
  없는 경우가 흔한데, 그것은 "분할" 이 아니라 배치이고 규칙이 사람마다 다르다.
  가이드로만 남기고 도구로 만들지 않는다(설계 문서 참조).
- **저장하지 않는다.** 여기서 나온 폴리곤은 제안일 뿐이고, 사람이 지도에서 보고
  적용해야 실제 구획이 된다.
"""
import logging
import math

from aot.aot_flask.geo import plot_context

logger = logging.getLogger(__name__)

# 자투리 기준. 긴 방향 길이가 이보다 짧은 조각은 두둑으로 치지 않는다 —
# 비정형 대지의 뾰족한 끝에서 30cm 짜리 삼각형이 나오는 것을 "두둑 1개" 로
# 세면 개수와 식재량이 모두 부풀어 오른다.
_MIN_BED_LENGTH_M = 2.0

# 분할 상한. 사람이 지도에서 확인해야 하는 제안이므로, 실수로 폭 1cm 를 넣어
# 수천 개가 만들어지는 것을 막는다. 넘으면 잘라내지 않고 **거부한다** — 조용히
# 자르면 사용자는 자기가 본 것이 전부인 줄 안다.
_MAX_STRIPS = 200

# parts 등분에서 이 비율을 넘으면 note 에 경고를 붙인다. strip_width_cm(두둑)
# 경로는 원래 가늘고 길게 나오는 것이 정상이라 대상이 아니다 — parts 모드에서만 쓴다.
_ASPECT_RATIO_WARNING = 4.0


def _longest_edge_angle(rect):
    """최소회전 사각형 → 가장 긴 변의 방위각(도, 반시계).

    사각형의 첫 세 꼭짓점이 인접한 두 변을 준다. 긴 쪽을 고른다.
    """
    c = list(rect.exterior.coords)
    if len(c) < 3:
        return None
    e1 = (c[1][0] - c[0][0], c[1][1] - c[0][1])
    e2 = (c[2][0] - c[1][0], c[2][1] - c[1][1])
    long_e = e1 if (e1[0] ** 2 + e1[1] ** 2) >= (e2[0] ** 2 + e2[1] ** 2) else e2
    return math.degrees(math.atan2(long_e[1], long_e[0]))


def split_shape(shape_or_geom, parts=None, strip_width_cm=None, widths_cm=None,
                edge_margin_m=0, min_bed_length_m=_MIN_BED_LENGTH_M,
                orientation=None, angle_deg=None):
    """도형을 띠 폴리곤 목록으로 → `(strips, info)` 또는 `(None, 오류문구)`.

    **조각 하나가 무엇인지는 호출자가 정한다.** 구역을 세 작물로 나누는 것과
    두둑마다 따로 기록하는 것은 같은 연산이고 굵기만 다르다.

    - `parts=1`            → **나누지 않는다.** 구역 전체가 구획 하나가 된다
      (가장자리 여백을 줬으면 그만큼 안으로 들어온 하나). 밭 하나를 통째로 한
      작기로 쓰는 것이 가장 흔한 경우인데, 예전에는 2 이상만 받아서 그 사람이
      이 도구를 아예 못 썼다 — 도형을 손으로 다시 그려야 했다.
    - `parts=3`            → 3등분. 조각 하나가 작기 하나(GeoPlot 한 행).
    - `strip_width_cm=160` → 1.6m 띠. 두둑 단위로 관리할 때.
    - `parts=5, strip_width_cm=160` → **둘 다 주면 균등분할이 아니다.** 정확히
      5개, 정확히 1.6m 폭으로 자르고, `5×1.6m` 을 채우고 남는 치수는 도형
      전체가 아니라 짧은 축 양쪽 여백으로 돌린다 — "몇 개를, 얼마 간격으로"
      직접 정할 때 쓴다(예: 재식 간격이 이미 정해진 5줄만 자르고 나머지는
      통로로 남기기). 개수만 주면 짧은 축을 정확히 등분하고(남는 폭 없음),
      폭만 주면 그 폭으로 채울 수 있는 만큼 자동으로 개수를 낸다(`floor`).
    - `widths_cm=[200, 500, 300]` → **조각마다 다른 폭.** 위 세 가지는 전부
      "같은 폭 N개" 라는 전제가 있는데, 등분으로 시작한 뒤 특정 조각만 넓히거나
      좁히고 싶을 때는 그 전제가 맞지 않는다. 이 리스트를 주면 `parts`/
      `strip_width_cm` 는 무시하고 순서대로 그 폭으로 자른다 — 합이 짧은 축보다
      작으면 남는 만큼 양쪽 여백(다른 모드와 같은 규칙), 크면 거부한다. 지도
      UI 는 등분 결과의 개별 폭을 그대로 이 리스트에 채워 넣고 시작한다(기본은
      균등, 그 다음 사용자가 조각별로 조정).

    적어도 하나는 줘야 한다 — 셋 다 없으면 무엇을 원하는지 알 수 없으므로
    거부한다. 기본값을 정해 두면 사용자가 말하지 않은 굵기로 나뉜 제안을
    보게 된다.

    Parameters
    ----------
    shape_or_geom : GeoShape 행 또는 GeoJSON geometry dict
    parts         : 등분 수, 또는 (strip_width_cm 과 함께 줄 때) 정확한
        조각 개수 (1 이상 정수 — `1` 은 나누지 않고 구역 전체를 하나로).
        `widths_cm` 이 있으면 무시된다.
    strip_width_cm: 띠 폭 (cm). 두둑 간격으로 쓸 때는 고랑 포함 값. `parts`
        와 함께 주면 그 폭으로 정확히 `parts` 개를 자른다. `widths_cm` 이
        있으면 무시된다.
    widths_cm     : 조각별 폭(cm) 리스트, 순서대로 적용. 1개 이상, 각 값은
        0보다 커야 한다(1개면 그 폭짜리 조각 하나 — `parts=1` 에서 시작해
        개별 폭 조정을 켠 경우가 그렇다). 주어지면 `parts`/`strip_width_cm`
        보다 우선한다.
    edge_margin_m : 도형 경계에서 안쪽으로 뺄 여백 (m). 농기계 선회 공간. 옛
        이름 `edge_margin_cm`(단위 cm)에서 이 이름으로 바뀌었다 — 단위만
        조용히 바꾸면 옛 호출자가 100배 잘못된 여백을 아무 에러 없이 받게
        되므로, 이름을 함께 바꿔 옛 키워드를 그대로 쓰면 `TypeError` 로
        확실히 실패하게 했다.
    min_bed_length_m : 이보다 짧은 조각은 버린다.
    orientation   : `'long'` 또는 `'short'`. 어느 변을 따라 조각이 놓이는지 —
        모듈 docstring의 "`orientation` — 기본값이 모드에 따라 갈린다" 참조.
        생략(`None`)하면 `strip_width_cm` 이 주어졌는지에 따라 `'long'`(주어짐)
        또는 `'short'`(안 주어짐, 순수 `parts`/`widths_cm`)로 자동 결정된다.
    angle_deg     : 조각이 놓이는 방향을 각도(도, 0≤값<180)로 직접 지정.
        주어지면 `orientation` 을 무시하고 이 각도를 쓴다 — 모듈 docstring의
        "`angle_deg` — `orientation` 을 덮어쓰는 임의 각도" 참조.

    Returns
    -------
    strips : [{'geometry': GeoJSON Polygon, 'index': int, 'length_m': float,
               'area_m2': float}, ...] — 긴 축을 따라 놓이고 짧은 축 순서로 번호.
    info : {'orientation', 'orientation_deg', 'strip_width_cm', 'strip_widths_m',
            'edge_margin_m', 'count', 'source_area_m2', 'covered_area_m2',
            'dropped', 'aspect_ratio', 'note'}
    """
    from shapely import affinity
    from shapely.geometry import box, mapping
    from shapely.ops import transform

    geom = (shape_or_geom if isinstance(shape_or_geom, dict)
            else plot_context.geometry_of(shape_or_geom))
    if not geom:
        return None, 'no polygon to split'

    has_widths = widths_cm is not None
    if not has_widths and parts is None and strip_width_cm is None:
        return None, ('give parts (how many pieces), strip_width_cm (how wide '
                      'each piece is), both together (an exact count at an '
                      'exact width — the leftover space becomes margin), or '
                      'widths_cm (a list of per-piece widths)')
    widths_list_cm = None
    if has_widths:
        try:
            widths_list_cm = [float(w) for w in widths_cm]
        except (TypeError, ValueError):
            return None, 'widths_cm must be a list of numbers in centimeters'
        if not widths_list_cm:
            return None, 'widths_cm must have at least 1 piece'
        if any(w <= 0 for w in widths_list_cm):
            return None, 'each width in widths_cm must be greater than 0'
    elif parts is not None:
        try:
            parts = int(parts)
        except (TypeError, ValueError):
            return None, 'parts must be a whole number'
        # 1 은 "나누지 않는다" 는 뜻으로 받는다 — 구역 전체를 구획 하나로 쓴다.
        # 예전에는 2 이상만 받아서, 밭 하나를 통째로 한 작기로 쓰려는 사람이
        # 이 도구를 쓸 수 없었다(도형을 손으로 다시 그려야 했다). 가장자리
        # 여백을 주면 그만큼 안으로 들어온 하나가 나온다.
        if parts < 1:
            return None, 'parts must be 1 or more'
    try:
        margin_m = float(edge_margin_m or 0)
    except (TypeError, ValueError):
        return None, 'edge_margin_m must be a number in meters'
    if margin_m < 0:
        return None, 'edge_margin_m cannot be negative'
    if orientation:
        orientation = orientation.strip().lower()
    else:
        # 생략(None/'')이면 모드로 정한다 — strip_width_cm 이 있으면(단독이든
        # parts 와 조합이든) 고랑 방향이 곧 작업 방향이라 'long', 없으면(순수
        # parts 등분 또는 widths_cm 단독) 두둑 개념이 없으므로 'short'. 모듈
        # docstring "orientation — 기본값이 모드에 따라 갈린다" 참조.
        orientation = 'long' if strip_width_cm is not None else 'short'
    if orientation not in ('long', 'short'):
        return None, "orientation must be 'long' or 'short'"
    if angle_deg is not None:
        try:
            angle_deg = float(angle_deg)
        except (TypeError, ValueError):
            return None, 'angle_deg must be a number in degrees'
        if not (0 <= angle_deg < 180):
            return None, 'angle_deg must be 0 or more and less than 180'

    to_m, from_m, _lat0 = plot_context.local_frame(geom)
    if to_m is None:
        return None, 'could not project the shape'
    poly = plot_context._shapely(geom)
    if poly is None or poly.is_empty:
        return None, 'no polygon to split'
    plane = transform(to_m, poly)

    # 여백은 **안쪽으로 파고드는 버퍼**다. 외접사각형에서 빼면 비정형 대지의
    # 오목한 곳에서는 여백이 실제로 남지 않는다.
    if margin_m > 0:
        plane = plane.buffer(-margin_m)
        if plane.is_empty:
            return None, ('edge_margin_m %.1f m leaves nothing of this shape'
                          % margin_m)

    try:
        import warnings
        with warnings.catch_warnings():
            warnings.filterwarnings('ignore', category=RuntimeWarning,
                                    message='.*oriented_envelope.*')
            rect = plane.minimum_rotated_rectangle
    except Exception as exc:
        logger.warning('plot_split: 외접사각형 실패: %s', exc)
        return None, 'could not find the shape orientation'
    if angle_deg is not None:
        # 사용자가 준 각도가 이긴다 — orientation 은 여기서부터 쓰이지 않는다.
        angle = angle_deg
    else:
        angle = _longest_edge_angle(rect) if hasattr(rect, 'exterior') else None
        if angle is None:
            return None, 'shape has no area to split'
        if orientation == 'short':
            # 인접한 변은 서로 수직이다 — 90도 돌리면 짧은 변이 눕는 방향이 된다.
            angle = (angle + 90.0) % 360.0

    # 긴 축을 수평으로 눕힌다(orientation='short' 면 짧은 축). 이후 자르기는 수평 띠 = 긴 방향을 따르는 조각이다.
    origin = rect.centroid
    flat = affinity.rotate(plane, -angle, origin=origin)
    minx, miny, maxx, maxy = flat.bounds
    across = maxy - miny
    if across <= 0:
        return None, 'shape has no width to split'

    # 조각마다 폭이 다를 수 있으므로 **리스트**로 통일한다 — 등분·자동폭·
    # 조합·개별폭 네 가지가 전부 "조각별 폭 목록 + 시작 오프셋" 이라는 같은
    # 모양으로 수렴한다. 등분/자동폭/조합은 지금까지처럼 전부 같은 값을
    # 반복할 뿐이다.
    exact_both = (not has_widths) and parts is not None and strip_width_cm is not None
    # widths_cm 마지막 조각이 잘렸으면(아래) 원래 요청값을 note 에 남기려고
    # 별도로 들고 있는다. 잘리지 않았으면 None.
    widths_clamped_from_m = None
    if has_widths:
        step_list_m = [w / 100.0 for w in widths_list_cm]
        needed_m = sum(step_list_m)
        # 조각당 0.5cm 허용오차 — UI 가 이 함수의 균등분할 결과
        # (strip_widths_m, cm 로 반올림)를 그대로 되돌려보내는 왕복 경로가
        # 있다. cm 반올림 자체가 조각마다 최대 0.5cm 오차를 낼 수 있으므로
        # (예: 22.734m → "2273cm"), N 조각이면 합산 오차가 N*0.5cm 까지
        # 쌓일 수 있다 — 그 정도는 "도형과 같은 폭" 으로 봐야지 초과로 보면
        # 안 된다.
        if needed_m > across + 0.005 * len(step_list_m):
            # **마지막 조각만** 남는 자리에 맞춰 줄인다 — 조각을 하나씩
            # 늘려가며 입력하다 마지막 값이 커서 넘친 경우, 거부하는 대신
            # "들어갈 수 있는 만큼 최대로" 잘라 준다. 앞선 조각들만으로도
            # 이미 도형을 넘으면(마지막을 0으로 줄여도 안 들어가면) 그건
            # "마지막이 커서" 가 아니라 애초에 안 맞는 요청이므로 그대로
            # 거부한다.
            others_m = sum(step_list_m[:-1])
            remaining_m = across - others_m
            if remaining_m <= 0:
                return None, ('the requested widths add up to %.1f m, but '
                              'the shape is only %.1f m across its short axis'
                              % (needed_m, across))
            widths_clamped_from_m = step_list_m[-1]
            step_list_m[-1] = remaining_m
            needed_m = others_m + remaining_m
        # 남는 폭은 양쪽에 반씩 — 한쪽으로 몰면 밭 한 변에만 자투리가 붙는다.
        # (마지막 조각을 잘라 딱 맞춘 경우 남는 폭은 0에 가깝다.)
        offset = max(0.0, (across - needed_m) / 2.0)
        count = len(step_list_m)
        # `step_m`(단일 값)은 나머지 모드와의 하위 호환용 요약치일 뿐이다 —
        # 실제 조각별 폭은 아래 `info['strip_widths_m']` 를 본다.
        step_m = needed_m / count
    elif exact_both:
        try:
            step_m = float(strip_width_cm) / 100.0
        except (TypeError, ValueError):
            return None, 'strip_width_cm must be a number in centimeters'
        if step_m <= 0:
            return None, 'strip_width_cm must be greater than 0'
        count = parts
        needed_m = count * step_m
        if needed_m > across:
            return None, ('%d pieces at %.0f cm each need %.1f m, but the '
                          'shape is only %.1f m across its short axis'
                          % (count, step_m * 100, needed_m, across))
        # 남는 폭은 양쪽에 반씩 — 한쪽으로 몰면 밭 한 변에만 자투리가 붙는다.
        offset = (across - needed_m) / 2.0
        step_list_m = [step_m] * count
    elif parts is not None:
        count = parts
        step_m = across / float(parts)
        offset = 0.0          # 등분은 남는 폭이 없다
        step_list_m = [step_m] * count
    else:
        try:
            step_m = float(strip_width_cm) / 100.0
        except (TypeError, ValueError):
            return None, 'strip_width_cm must be a number in centimeters'
        if step_m <= 0:
            return None, 'strip_width_cm must be greater than 0'
        if across < step_m:
            return None, ('the shape is only %.1f m across its short axis, '
                          'less than one %.0f cm strip'
                          % (across, step_m * 100))
        count = int(across // step_m)
        # 남는 폭은 양쪽에 반씩 — 한쪽으로 몰면 밭 한 변에만 자투리가 붙는다.
        offset = (across - count * step_m) / 2.0
        step_list_m = [step_m] * count

    if count > _MAX_STRIPS:
        return None, ('that would be %d pieces, more than this tool will '
                      'propose (%d). Use fewer parts or a wider strip.'
                      % (count, _MAX_STRIPS))

    strips, dropped, covered = [], 0, 0.0
    y_cursor = miny + offset
    for i, h in enumerate(step_list_m):
        y0 = y_cursor
        y_cursor += h
        band = box(minx - 1.0, y0, maxx + 1.0, y0 + h)
        piece = flat.intersection(band)
        if piece.is_empty:
            dropped += 1
            continue
        # 오목한 대지에서는 한 띠가 여러 조각으로 끊긴다. 끊긴 것은 **각각 다른
        # 구획**이다 — 하나로 묶으면 "길이 67m" 이 실제로는 30m 짜리 둘인 상태가
        # 되어 식재량이 맞지 않는다.
        #
        # ⚠ 이 변수를 `parts` 로 쓰지 말 것. 파라미터 `parts` 를 덮어써서 두 번째
        #   반복부터 등분 수가 사라진다(each_input 클로버 버그와 같은 형태).
        pieces = (list(piece.geoms) if piece.geom_type.startswith('Multi')
                  else [piece])
        for part in pieces:
            if part.geom_type != 'Polygon' or part.is_empty:
                continue
            px0, _py0, px1, _py1 = part.bounds
            length_m = px1 - px0
            if length_m < min_bed_length_m:
                dropped += 1
                continue
            back = affinity.rotate(part, angle, origin=origin)
            lonlat = transform(from_m, back)
            area = plot_context.shapely_area_m2(lonlat)
            covered += area
            strips.append({
                'index': len(strips) + 1,
                'geometry': mapping(lonlat),
                'length_m': round(length_m, 1),
                'area_m2': round(area, 1),
            })

    if not strips:
        return None, ('nothing usable came out — every strip was shorter than '
                      '%.1f m' % min_bed_length_m)

    source_area = plot_context.shapely_area_m2(poly)

    # 종횡비는 parts(등분) 모드에서만 낸다. strip_width_cm(두둑)는 가늘고 긴 것이
    # 정상 설계라 경고 대상이 아니다 — 모듈 docstring "orientation" 절 참조.
    #
    # `parts == 1`(구역 전체를 하나로)도 대상이 아니다. 그 종횡비는 나눈 결과가
    # 아니라 **밭 자체의 모양**이고, "짧은 변으로 바꿔 보라" 는 조언은 나눌 것이
    # 없는데 할 말이 아니다.
    aspect_ratio = None
    if parts is not None and parts > 1 and step_m > 0:
        lens_sorted = sorted(s['length_m'] for s in strips)
        aspect_ratio = round(lens_sorted[len(lens_sorted) // 2] / step_m, 1)

    if angle_deg is not None:
        note = ('Pieces follow a custom %.0f deg direction. Irregular edges '
               'are clipped, so pieces differ in length; %d were dropped as '
               'too short. covered_area_m2 is the ground the pieces cover, '
               'NOT the plantable area — furrows are not subtracted.'
               % (angle % 180.0, dropped))
        if aspect_ratio is not None and aspect_ratio > _ASPECT_RATIO_WARNING:
            note += (" Pieces are long and narrow (%.1f:1) at this angle."
                     % aspect_ratio)
    else:
        side_desc = "shortest" if orientation == 'short' else "longest"
        note = ('Pieces follow the shape\'s %s side (%.0f deg). Irregular '
               'edges are clipped, so pieces differ in length; %d were dropped '
               'as too short. covered_area_m2 is the ground the pieces cover, '
               'NOT the plantable area — furrows are not subtracted.'
               % (side_desc, angle % 180.0, dropped))
        if aspect_ratio is not None and aspect_ratio > _ASPECT_RATIO_WARNING:
            if orientation == 'long':
                note += (" Pieces are long and narrow (%.1f:1) — for squarer "
                         "plots better suited to splitting between subjects, pass "
                         "orientation='short'." % aspect_ratio)
            else:
                note += (" Pieces are long and narrow (%.1f:1) even along the "
                         "shortest side — the shape itself is elongated."
                         % aspect_ratio)

    if exact_both:
        note += (" %d pieces at exactly %.0f cm were requested — the leftover "
                 "%.1f m across the short axis is unused margin, split evenly "
                 "on both sides." % (count, step_m * 100, across - count * step_m))
    if has_widths and widths_clamped_from_m is not None:
        note += (" %d pieces with custom widths were requested (%s cm), but "
                 "the last one (%.0f cm) did not fit — it was shortened to "
                 "%.0f cm, the most that fits within the shape's %.1f m short "
                 "axis." % (count, ', '.join('%.0f' % w for w in widths_list_cm),
                            widths_clamped_from_m * 100, step_list_m[-1] * 100,
                            across))
    elif has_widths:
        note += (" %d pieces with custom widths were requested (%s cm) — the "
                 "leftover %.1f m across the short axis is unused margin, "
                 "split evenly on both sides."
                 % (count, ', '.join('%.0f' % w for w in widths_list_cm),
                    across - needed_m))

    info = {
        'orientation': 'custom' if angle_deg is not None else orientation,
        'orientation_deg': round(angle % 180.0, 1),
        'strip_width_m': round(step_m, 2),
        # 조각별 폭(m) — 등분·자동폭·조합 모드도 항상 낸다(전부 같은 값의
        # 반복이지만). 지도 UI 가 "기본은 균등 등분, 그 다음 조각마다 폭을
        # 조정" 흐름을 만들 때, 모드에 관계없이 이 리스트 하나로 시작 값을
        # 채우면 된다 — widths_cm 로 다시 보낼 때도 이 값을 그대로 쓰면 된다.
        'strip_widths_m': [round(h, 2) for h in step_list_m],
        'edge_margin_m': round(margin_m, 2),
        'count': len(strips),
        'source_area_m2': round(source_area, 1),
        # **덮은 면적**이지 심는 면적이 아니다. 띠는 도형을 빈틈없이 덮으므로
        # 이 값은 도형 면적에 가깝다. 고랑을 뺀 실제 식재 면적은 계산하지
        # 않는다 — 고랑 폭을 모르는 것이 이 설계의 선택이기 때문이다.
        'covered_area_m2': round(covered, 1),
        'dropped': dropped,
        'aspect_ratio': aspect_ratio,
        'note': note,
        # widths_cm 의 마지막 조각이 남는 자리에 맞게 줄었으면 그 원래 요청값
        # (cm) — UI 가 "요청한 그대로가 아니라 들어가는 만큼만 잘렸다" 는
        # 것을 알릴 때 쓴다. 안 잘렸으면 None.
        'widths_clamped_from_cm': (
            round(widths_clamped_from_m * 100)
            if widths_clamped_from_m is not None else None),
    }
    return strips, info
