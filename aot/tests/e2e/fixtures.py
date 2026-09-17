# coding=utf-8
"""E2E 시드가 만드는 고정 픽스처의 **이름과 값**.

시드 스크립트(컨테이너 안에서 돈다)와 테스트(호스트에서 돈다)가 같은 사실을
봐야 하므로, 양쪽이 이 파일 하나만 import 한다. 여기 없는 값을 테스트에
직접 적지 않는다 — 적는 순간 시드와 테스트가 조용히 어긋난다.
"""

# 사용자 — `test_username()`/`test_password()` 가 영숫자만 허용하므로
# 하이픈·밑줄을 쓰지 않는다(3~64자).
ADMIN_USER = 'e2eadmin'
ADMIN_PASS = 'e2epass1234'
ADMIN_EMAIL = 'e2e-admin@example.invalid'

GUEST_USER = 'e2eguest'
GUEST_PASS = 'e2epass1234'
GUEST_EMAIL = 'e2e-guest@example.invalid'

# 장치 이름 — 화면에서 이 문자열로 찾는다.
INPUT_RAM = 'E2E RAM Input'
INPUT_CPU = 'E2E CPU Input'

OUTPUT_MULTI = 'E2E Virtual Multi'      # 채널 3개
OUTPUT_NOCHANNEL = 'E2E No Channel'     # 채널 0개 — 유형 D 회귀 재현용
OUTPUT_PWM = 'E2E PWM'

FUNCTION_CONDITIONAL = 'E2E Conditional'

# 시퀀스 — 단계 순서가 저장되는지 보는 데 쓴다.
FUNCTION_SEQUENCE = 'E2E Sequence'
SEQUENCE_STEPS = ('E2E Step One', 'E2E Step Two', 'E2E Step Three')

DASHBOARD = 'E2E Dashboard'

# 지도 도형 — 부지 하나와 그 안의 구역 하나.
GEO_SITE = 'E2E Site'
GEO_ZONE = 'E2E Zone'

# 구획 — 일지·목표 화면이 고르는 대상.
GEO_PLOT = 'E2E Plot'
GEO_PLOT_SUBJECT = 'E2E Crop'

# 시드가 만드는 개수 — 테스트가 "몇 개여야 하는가"를 여기서 읽는다.
EXPECTED_INPUTS = 2
EXPECTED_OUTPUTS = 3
EXPECTED_OUTPUT_MULTI_CHANNELS = 3
