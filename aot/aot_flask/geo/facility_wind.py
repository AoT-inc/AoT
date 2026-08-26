# coding=utf-8
"""
facility_wind.py — 자연환기 풍압 시뮬레이션 (D1).

개구부(vent_openings)별 풍압계수(Cp)와 유효 환기량을 계산한다.
물리 모델: 개구부 세계좌표 법선 × 풍향벡터 내적 → Cp → Q = Cd·A·V·√|Cp|

좌표 규약
---------
- 지도 2D: X = 동(East), Y = 북(North)
- facility orientation_deg: 시계방향(북 기준) — Three.js Y축 회전과 동일
- 기상 wind_dir_deg: 기상 표준(0=북풍·북에서 불어옴, 90=동풍)

개구부 face 레이블 → 로컬 법선(orientation=0 기준)
  'south' → 세계 (0, -1)   'north' → (0, +1)
  'east'  → (+1, 0)         'west'  → (-1, 0)
  'roof'  → (0,  0) [수직   사용하지 않음 — 별도 처리]

@phase active
"""
import math
from typing import Optional

# ── 물리 상수 ────────────────────────────────────────────────────────────────
Cd  = 0.60   # 개구부 방류계수 (discharge coefficient, windows/vents)
RHO = 1.20   # 공기 밀도 kg/m³ (20°C, 해면 기준)

# 이 미만이면 무풍으로 보고 풍향 가중치를 걸지 않는다 [m/s].
# 풍압 ∝ ρv²/2 이므로 0.5 m/s 에서 약 0.15 Pa — 개구부 개도를 80% 깎을 근거가
# 못 된다. 사람이 "바람이 없다" 고 말하는 구간과도 대체로 맞는다(蒲福 0~1).
WIND_BIAS_MIN_MS = 0.5

# 풍압계수 기준값 (직사각형 온실 경험식, ASHRAE 2009)
Cp_WINDWARD = 0.60   # 풍상면(windward): 양압
Cp_LEEWARD  = 0.30   # 풍하면(leeward):  부압

# 로컬 face → 2D 단위 법선 (orientation_deg=0 기준, 외향)
# X=동, Y=북 지도 좌표계
_FACE_LOCAL_NORMAL = {
    'north': (0.0,  1.0),
    'south': (0.0, -1.0),
    'east':  (1.0,  0.0),
    'west':  (-1.0, 0.0),
}


def _rotate_2d(nx, ny, angle_deg_cw):
    """시계방향 angle_deg_cw 만큼 2D 벡터 회전 (지도 방위 기준)."""
    rad = math.radians(angle_deg_cw)
    cos_a, sin_a = math.cos(rad), math.sin(rad)
    return (nx * cos_a + ny * sin_a,
            -nx * sin_a + ny * cos_a)


def _world_normal(face: Optional[str], orientation_deg: float):
    """face 레이블 + orientation_deg → 세계 좌표 2D 법선 (단위벡터)."""
    local = _FACE_LOCAL_NORMAL.get(face or '')
    if local is None:
        return None  # 'roof' 등 수직면 제외
    return _rotate_2d(local[0], local[1], orientation_deg)


def _world_normal_from_sn(surface_normal, orientation_deg: float):
    """3D surface_normal [nx, ny, nz] → 세계 좌표 2D 법선. **좌표 규약의 정본.**

    model +X → 지도 East, model +Z → 지도 South. 추가 부호 반전은 **없다.**

    ## 미러 보정이 있었고, 지금은 없다 (2026-08-26 현장 재확인)

    한때 "3D 미리보기에서 만든 것을 지도에 배치하면 X축이 미러된다" 는 실제
    문제가 있었고, 그 보정으로 `_side_world_normal` 이 X 부호를 뒤집었다.
    그 뒤 지도 렌더러의 변환(`aot-facility-map-3d.js` `_buildTransform`)이
    정리되면서 미러가 사라졌는데, **보정만 남았다.**

    남은 동안 풍향 가중치가 정확히 반대로 돌았다 — 실측(방위 11.5° · 5 m/s):
    동풍에서 동쪽을 보는 측창이 0.2 로 깎이고 서쪽 창이 0.98 을 받았다.
    정책("windward 높게, leeward 낮게")과 정반대다.

    ⚠ **부호는 코드로 판정할 수 없다.** 직사각형 시설은 미러해도 footprint 가
      똑같아서, 좌우가 다른 내용물(측창)이 있어야만 드러난다. 변환 행렬을 읽는
      것도, git 이력(스쿼시)도 근거가 못 된다 — **현장에서 만들어 보고 지도와
      대조하는 것**만이 답한다. 2026-08-26 에 그렇게 확인했다: 일치한다.

    ⚠ **여기가 유일한 자리다.** 예전에는 이 함수와 `_side_world_normal` 이
      같은 필드에 **반대 규약**을 적어 두고 있었다(전자는 "반전 없이", 후자는
      뒤집기). 그러면 환기량 계산과 풍향 가중치가 한 시설에서 서로 다른 방향을
      가리키는데, 화면에는 아무 신호도 없다. 부호를 바꿔야 하면 여기만 고친다.
    """
    if not (isinstance(surface_normal, (list, tuple)) and len(surface_normal) >= 3):
        return None
    nx = float(surface_normal[0])
    nz = float(surface_normal[2])
    if abs(nx) < 1e-6 and abs(nz) < 1e-6:
        return None  # 수직면(지붕) — 지붕 취급
    return _rotate_2d(nx, nz, orientation_deg)


def _wind_from_vector(wind_dir_deg: float):
    """기상 풍향 → 풍원 방향 단위벡터 (from 방향, 기상 표준).

    wind_dir_deg=0  (북풍, 북에서 불어옴) → (0, 1) : 북쪽을 가리킴
    wind_dir_deg=90 (동풍)               → (1, 0)
    """
    rad = math.radians(wind_dir_deg)
    return (math.sin(rad), math.cos(rad))


def compute_natural_ventilation(
    vent_openings: list,
    wind_speed_ms: float,
    wind_dir_deg: float,
    orientation_deg: float = 0.0,
    volume_m3: float = 1.0,
    opening_pct: float = 100.0,
) -> dict:
    """개구부별 풍압 환기량 계산 (D1 핵심 함수).

    Parameters
    ----------
    vent_openings   : compute_capacity() 의 vent_openings[] 리스트
    wind_speed_ms   : 풍속 m/s
    wind_dir_deg    : 기상 표준 풍향 (0=북풍, 90=동풍, 180=남풍, 270=서풍)
    orientation_deg : 시설 방위각 (시계방향, 북 기준) — facility.geometry_3d.orientation_deg
    volume_m3       : 시설 체적 (ACH 환산용)
    opening_pct     : 개구부 개방률 0~100% (운영 상태 반영)

    Returns
    -------
    {
      'effective_ach'   : float,           # 자연환기 ACH (1/h)
      'inflow_m3h'      : float,
      'outflow_m3h'     : float,
      'openings'        : [                # 개구부별 상세
          {
            'id'         : str,
            'face'       : str,            # 로컬 face 레이블
            'world_face' : str,            # 세계좌표 방향 레이블
            'area_m2'    : float,
            'cp'         : float,          # 풍압계수 (양=풍상, 음=풍하)
            'flow_m3h'   : float,          # 시간당 통기량 (방향 무관 절대값)
            'direction'  : str,            # 'in' | 'out' | 'calm'
            'actuator_id': str | None,
          }
        ],
      'method'  : 'cp_pressure',
      'inputs'  : { wind_speed_ms, wind_dir_deg, orientation_deg, opening_pct },
    }
    """
    open_ratio = max(0.0, min(1.0, opening_pct / 100.0))
    wind_vec   = _wind_from_vector(wind_dir_deg)  # 풍원 방향 단위벡터

    results = []
    total_inflow_m3s  = 0.0
    total_outflow_m3s = 0.0

    for vo in vent_openings:
        face = vo.get('face')
        area = float(vo.get('area_m2') or 0.0) * open_ratio
        if area <= 0:
            results.append({**_null_opening(vo), 'direction': 'calm'})
            continue

        wn = _world_normal(face, orientation_deg)
        if wn is None:
            wn = _world_normal_from_sn(vo.get('surface_normal'), orientation_deg)
        if wn is None:
            # 지붕 개구부 — 단순 고정 환기율 (풍속 비례, 방향 무관)
            flow_m3s = Cd * area * wind_speed_ms * 0.20  # 지붕계수 0.20
            results.append({
                'id':          vo.get('id'),
                'face':        face,
                'world_face':  'roof',
                'area_m2':     round(area, 3),
                'cp':          0.20,
                'flow_m3h':    round(flow_m3s * 3600, 1),
                'direction':   'mixed',
                'actuator_id': vo.get('actuator_id'),
            })
            total_inflow_m3s  += flow_m3s * 0.5
            total_outflow_m3s += flow_m3s * 0.5
            continue

        # 풍압계수: cos(α) = n · wind_from_vector  (내적)
        cos_alpha = wn[0] * wind_vec[0] + wn[1] * wind_vec[1]

        if cos_alpha > 1e-4:
            # 풍상면 — 양압, 내부로 유입
            cp        = Cp_WINDWARD * cos_alpha
            direction = 'in'
        elif cos_alpha < -1e-4:
            # 풍하면 — 부압(흡인), 내부에서 유출
            cp        = -Cp_LEEWARD * abs(cos_alpha)  # 음수
            direction = 'out'
        else:
            # 풍향과 평행 (90°) → 압력 거의 없음
            cp        = 0.0
            direction = 'calm'

        # Q = Cd · A · V · √|Cp|
        flow_m3s = Cd * area * wind_speed_ms * math.sqrt(abs(cp)) if cp != 0 else 0.0

        if direction == 'in':
            total_inflow_m3s  += flow_m3s
        elif direction == 'out':
            total_outflow_m3s += flow_m3s

        results.append({
            'id':          vo.get('id'),
            'face':        face,
            'world_face':  _label_world_face(wn),
            'area_m2':     round(area, 3),
            'cp':          round(cp, 3),
            'flow_m3h':    round(flow_m3s * 3600, 1),
            'direction':   direction,
            'actuator_id': vo.get('actuator_id'),
        })

    # 교차환기 유효량 = min(inflow, outflow) — 보존 법칙
    effective_m3s = min(total_inflow_m3s, total_outflow_m3s)
    effective_ach = (effective_m3s * 3600 / volume_m3) if volume_m3 > 0 else 0.0

    return {
        'effective_ach':  round(effective_ach, 2),
        'inflow_m3h':     round(total_inflow_m3s  * 3600, 1),
        'outflow_m3h':    round(total_outflow_m3s * 3600, 1),
        'openings':       results,
        'method':         'cp_pressure',
        'inputs': {
            'wind_speed_ms':   wind_speed_ms,
            'wind_dir_deg':    wind_dir_deg,
            'orientation_deg': orientation_deg,
            'opening_pct':     opening_pct,
        },
    }


def _is_roof_opening(vo) -> bool:
    """천창(지붕 개구부) 여부 판정.

    천창은 부력/굴뚝 환기로 풍향과 무관하게 내부 열기를 배출한다.
    판정 우선순위:
      1) face == 'roof'
      2) kind == 'window'  (천창. 측창은 'side_window')
      3) surface_normal 의 수직(y) 성분이 있고 수평 북남(z)≈0 인 경사면
    """
    if (vo.get('face') or '').lower() == 'roof':
        return True
    if (vo.get('kind') or '').lower() == 'window':
        return True
    sn = vo.get('surface_normal')
    if isinstance(sn, (list, tuple)) and len(sn) >= 3:
        try:
            if abs(float(sn[1])) > 1e-6 and abs(float(sn[2])) < 1e-6:
                return True
        except (TypeError, ValueError):
            pass
    return False


def _side_world_normal(vo, orientation_deg: float):
    """측창의 세계좌표 2D 법선.

    좌표 규약은 `_world_normal_from_sn` 하나가 정한다 — **여기서 부호를 따로
    정하지 말 것.** 예전에는 이 함수가 X 를 뒤집고 그쪽은 안 뒤집어서, 환기량
    계산과 풍향 가중치가 한 시설에서 서로 다른 방향을 가리켰다(2026-08-26).

    surface_normal 이 없으면 face 레이블로 폴백한다 — 그 라벨은 이미 지도
    기준이다. 둘 다 없으면 None.
    """
    sn = vo.get('surface_normal')
    if isinstance(sn, (list, tuple)) and len(sn) >= 3:
        try:
            nx = float(sn[0])
            nz = float(sn[2])
        except (TypeError, ValueError):
            nx = nz = 0.0
        if abs(nx) >= 1e-6 or abs(nz) >= 1e-6:
            return _world_normal_from_sn(sn, orientation_deg)
    # 폴백: face 레이블 (이미 지도 기준이라 추가 반전 없음)
    return _world_normal(vo.get('face'), orientation_deg)


def wind_biased_opening(vent_openings, wind_dir_deg, orientation_deg=0.0,
                        wind_speed_ms=None):
    """각 개구부의 풍향 기여도(0.0~1.0) 반환 — env_coordinator 명령 가중치용.

    정책:
      - 무풍         : 전부 1.0 (아래 참조)
      - 천창(roof)   : 풍향 무관 → 1.0 (명령대로 개방, 내부 열기 배출 역할)
      - 측창(side)   : surface_normal(미러 보정) × 풍향 → windward 높게, leeward 낮게
                       weight = 0.2 + 0.8·max(0, cosα)  (leeward 최소 20% 유지)
      - 방향 불명    : 1.0 (반토막 금지 — 정보 없다고 환기를 절반으로 깎지 않음)

    ⚠ **바람이 없으면 가중치를 걸지 않는다** (2026-08-26). 이 가중치의 근거는
    풍압이므로 풍속이 0 이면 깎을 이유가 없다. 그런데 기상 소스는 무풍일 때
    풍향을 `0.0`(정북)으로 내보내는 일이 흔하고 — OpenWeather 가 그렇다 —
    `0.0` 은 `None` 이 아니라서 "정보 없음" 분기에도 안 걸린다. 그러면 북향이
    아닌 측창이 **영구히 leeward** 로 판정돼 하한 0.2 에 갇힌다.

    실측(2026-08-26 イチゴ): 풍속 0.0 m/s · 풍향 0.0° 인데 側面窓右 가 가중치
    0.2 를 받아, 코디네이터가 24.6% 를 명령해도 장치는 계속 5.0% 였다
    (24.6 × 0.2 = 4.92). 코디네이터는 24.6 이 나갔다고 믿으므로 적분이 영영
    수렴하지 못하고, 화면에서는 "창이 안 풀린다" 로 보인다.

    Args:
        wind_speed_ms: 풍속 [m/s]. None = 모름(가중치 적용 — 종전 동작).
                       WIND_BIAS_MIN_MS 미만이면 무풍으로 보고 전부 1.0.
    """
    if wind_speed_ms is not None and float(wind_speed_ms) < WIND_BIAS_MIN_MS:
        return {vo['actuator_id']: 1.0
                for vo in vent_openings if vo.get('actuator_id')}

    wind_vec = _wind_from_vector(wind_dir_deg)
    weights  = {}

    for vo in vent_openings:
        aid = vo.get('actuator_id')
        if not aid:
            continue

        # 천창: 풍향 무관 — 명령대로
        if _is_roof_opening(vo):
            weights[aid] = max(weights.get(aid, 0.0), 1.0)
            continue

        # 측창: 미러 보정된 법선으로 풍압 기여도 산출
        wn = _side_world_normal(vo, orientation_deg)
        if wn is None:
            # 방향 불명 → 반토막 금지
            weights[aid] = max(weights.get(aid, 0.0), 1.0)
            continue

        cos_alpha = wn[0] * wind_vec[0] + wn[1] * wind_vec[1]
        # [-1, 1] → [0.2, 1.0]  (leeward 최소 20% 유지 — 과압 방지)
        weight = 0.2 + 0.8 * max(0.0, cos_alpha)
        # 동일 actuator 에 여러 opening → 최대값 채택
        weights[aid] = max(weights.get(aid, 0.0), round(weight, 3))

    return weights


# ── 내부 헬퍼 ────────────────────────────────────────────────────────────────
def _null_opening(vo):
    return {
        'id':          vo.get('id'),
        'face':        vo.get('face'),
        'world_face':  vo.get('face'),
        'area_m2':     float(vo.get('area_m2') or 0),
        'cp':          0.0,
        'flow_m3h':    0.0,
        'actuator_id': vo.get('actuator_id'),
    }


def _label_world_face(wn):
    """세계좌표 법선 → 가장 가까운 방위 레이블."""
    nx, ny = wn
    if abs(ny) >= abs(nx):
        return 'north' if ny > 0 else 'south'
    return 'east' if nx > 0 else 'west'
