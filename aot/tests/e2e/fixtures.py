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
# `.invalid` 는 예약 TLD 지만 폼의 이메일 검증기가 거부한다 — 그러면 사용자
# 설정 저장이 **폼 전체 거부**로 막혀, 언어·배율을 바꾸는 여정이 통째로
# 실패한다(2026-09-18 실측). `example.com` 도 예약 도메인이라 메일이 실제로
# 나가지 않으면서 검증은 통과한다.
ADMIN_EMAIL = 'e2e-admin@example.com'

GUEST_USER = 'e2eguest'
GUEST_PASS = 'e2epass1234'
GUEST_EMAIL = 'e2e-guest@example.com'

# 보기 권한만 있는 사용자(Monitor) — 게스트와 달리 화면은 열리고 **쓰기만**
# 막혀야 한다. 거절 가지에 숨은 결함은 이 역할로만 드러난다.
MONITOR_USER = 'e2emonitor'
MONITOR_PASS = 'e2epass1234'
MONITOR_EMAIL = 'e2e-monitor@example.com'

# 편집자(Editor) — 설정·제어는 되지만 사용자 관리는 안 된다. 관리자 전용 경계
# (설정 가져오기 등)를 확인하는 데 쓴다.
EDITOR_USER = 'e2eeditor'
EDITOR_PASS = 'e2epass1234'
EDITOR_EMAIL = 'e2e-editor@example.com'

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

# 공지 — 작성한 것이 대시보드 위젯까지 가는지 보는 데 쓴다.
# 시설 — 만들고 다시 열어 확인하는 데 쓴다.
FACILITY_NAME = 'E2E Facility'
FACILITY_DELETE_NAME = 'E2E Facility To Delete'   # 삭제 검사 전용

# 에너지 사용량 — 계산이 맞는지 손으로 검산할 수 있는 값.
ENERGY_OUTPUT_AMPS = 2.0            # E2E Virtual Multi 채널 0 의 전류
ENERGY_OUTPUT_SEC_ON = 3600         # 지난 하루 켜져 있던 시간(1시간)
ENERGY_INPUT_AMPS = 2.0             # 전류 측정값(일정)
ENERGY_INPUT_MEASUREMENT = 'E2E Current'   # 전류 측정 채널 이름

# 카메라 — 장치 없이 촬영까지 가도록 앱이 내놓는 정적 이미지를 URL 카메라로 찍는다.
CAMERA_NAME = 'E2E Camera'
GEO_LAYER_NAME = 'E2E OSM Layer'
METHOD_NAME = 'E2E Method'

# MCP 서버 — 앱에 들어 있는 AoT MCP 서버를 한 번 더 등록한다(인증을 끈 채로).
MCP_SERVER_NAME = 'E2E MCP Server'
MCP_SERVER_COMMAND = '/usr/local/bin/python /app/aot/aot_mcp_server.py'
MCP_SERVER_ENV = '{"AOT_MCP_REQUIRE_AUTH": "0"}'
CAMERA_IMAGE_URL = 'http://127.0.0.1/static/img/aot-hero-dashboard-v2.jpg'

# 일정 — 달력에 뜨는지 보는 데 쓴다.
SCHEDULE_TITLE = 'E2E Scheduled Run'

# AI 승인 대기 — 모두 E2E Virtual Multi 를 켜 달라는 요청이다. 검사마다 상태를
# 바꾸므로(승인·거부) 한 건을 나눠 쓰지 않고 쓰임새별로 따로 둔다.
APPROVAL_FOR_APPROVE = 'E2E Approval Approve'
APPROVAL_FOR_REJECT = 'E2E Approval Reject'
APPROVAL_FOR_GUEST = 'E2E Approval Guest'

NOTICE_TITLE = 'E2E Notice Post'
NOTICE_BODY = 'E2E 공지 본문 — 종단 검사가 만든 글입니다.'

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
