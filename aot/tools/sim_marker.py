"""시뮬레이션 장치 표시 판별 (표시 전용).

운영 화면·조회 응답에서 시뮬레이션 장치(SIM 난방기, 테스트 드라이버 센서 등)가
실제 장치와 섞여 구분이 안 되는 문제를 줄이기 위한 공용 판별 함수다.
모델·마이그레이션 없이 드라이버 식별자와 이름 접두만 본다.

**표시만 한다.** 평균·침묵·경보 계산, placement 분류, 환경제어는 이 함수를
쓰지 않는다. (후속 과제: 사용자가 장치에 명시적으로 "시뮬레이션" 을 지정하는
설정 칸 — 실제 드라이버에 SIM 이름을 붙인 기상대 등은 이름만으로 확정 못 한다.)
"""
import re

#: 테스트 전용 드라이버 — 확정 시뮬레이션 (aot_test_input_save_value.py).
SIM_DRIVERS = frozenset({'TEST_SAVE_VALUE'})

#: 가상 출력 드라이버 접두 — 실제 장비의 대용일 수 있어 시뮬레이션 단정은 아니다.
VIRTUAL_OUTPUT_PREFIX = 'virtual_on_off'

# 이름 맨 앞 단어가 SIM/Simulator/Simulated... 일 때만 (Similar, Simple 은 아님).
_SIM_NAME = re.compile(r'^\s*(?:sim|simulat\w*)\b', re.IGNORECASE)


def is_simulated(kind, driver, name):
    """(simulated, basis) 를 돌려준다.

    - ('input' 의 TEST_SAVE_VALUE 등) 테스트 드라이버 → (True, 'driver_test')
    - 이름 맨 앞 단어가 SIM/Simulator... → (True, 'name_prefix')   보조 신호
    - 가상 출력(virtual_on_off_*) → (None, 'driver_virtual')  단정 아님
    - 그 밖 → (None, None)
    """
    drv = (driver or '')
    if drv in SIM_DRIVERS:
        return True, 'driver_test'
    if name and _SIM_NAME.match(str(name)):
        return True, 'name_prefix'
    if kind == 'output' and str(drv).startswith(VIRTUAL_OUTPUT_PREFIX):
        return None, 'driver_virtual'
    return None, None


def sim_fields(kind, driver, name):
    """응답에 덧붙일 필드 dict. 해당 없으면 빈 dict (응답 크기 최소).

    simulated:true + sim_basis(근거), 가상 출력은 virtual:true.
    """
    sim, basis = is_simulated(kind, driver, name)
    out = {}
    if sim:
        out['simulated'] = True
        out['sim_basis'] = basis
    if kind == 'output' and str(driver or '').startswith(VIRTUAL_OUTPUT_PREFIX):
        out['virtual'] = True
    return out


def tag_sim(entry, kind, driver, name):
    """entry(dict)에 sim_fields 를 병합하고 entry 를 돌려준다."""
    entry.update(sim_fields(kind, driver, name))
    return entry
