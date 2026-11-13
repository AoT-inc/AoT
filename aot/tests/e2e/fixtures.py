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
# 설비 작동 상태 검사 전용 — 팬을 따로 켜고 꺼도 다른 검사가 쓰는 출력에 닿지 않는다.
OUTPUT_STATE_FAN = 'E2E State Fan'

FUNCTION_CONDITIONAL = 'E2E Conditional'

# 시퀀스 — 단계 순서가 저장되는지 보는 데 쓴다.
FUNCTION_SEQUENCE = 'E2E Sequence'
SEQUENCE_STEPS = ('E2E Step One', 'E2E Step Two', 'E2E Step Three')

# 제어 폐루프(L3) — 데몬이 **실제로 돌리는** 시퀀스. 위 시퀀스는 단계 순서 화면용이라
# 돌릴 수 있는 모양이 아니다. E2E Virtual Multi 의 채널 1 만 쓴다(채널 0 은 에너지·
# 제어 검사, 채널 2 는 타이머 검사가 쓴다).
SEQUENCE_RUN = 'E2E Run Sequence'
SEQUENCE_RUN_STEP = 'E2E Run Step'
SEQUENCE_RUN_CHANNEL = 1
SEQUENCE_RUN_STEP_SEC = 30
SEQUENCE_RUN_PERIOD_SEC = 60
CONTROL_DASHBOARD = 'E2E Control Dashboard'
TIMER_CHANNEL = 2

# 시퀀스 위젯의 그룹 드래그 — 그룹은 한 블록으로만 움직여야 한다. 돌리지 않는
# 시퀀스라(꺼 둔 채) 채널은 상관없다. 단계는 (표시 이름, 그룹 이름) — 빈 그룹 = 단독.
GROUP_SEQUENCE = 'E2E Group Sequence'
GROUP_NAME = 'E2E Pair'
GROUP_SEQUENCE_STEPS = (
    ('E2E Solo First', ''),
    ('E2E Pair A', GROUP_NAME),
    ('E2E Pair B', GROUP_NAME),
    ('E2E Solo Last', ''),
)
GROUP_DASHBOARD = 'E2E Group Dashboard'

DASHBOARD = 'E2E Dashboard'

# 지도 위젯 렌더 검사 — 시설이 놓인 지도를 보여 주는 대시보드.
MAP_DASHBOARD = 'E2E Map Dashboard'
TWO_MAP_DASHBOARD = 'E2E Two Map Dashboard'
RASTER_DASHBOARD = 'E2E Raster Base Dashboard'
RASTER_BASE_A = 'E2E Raster Base A'
RASTER_BASE_B = 'E2E Raster Base B'
MAP_FACILITY = 'E2E Map Facility'
# 시설 위젯(3D 모형) 검사 — 설비 작동 상태 표시(J-state)가 쓴다.
FACILITY_DASHBOARD = 'E2E Facility Widget Dashboard'
FACILITY_STATE_NAME = 'E2E State Facility'
# 레이아웃형 시설(layout) 외피 개구 검사 — 자유 평면 벽·박공·평지붕의 창 구멍.
FACILITY_LAYOUT_NAME = 'E2E Layout Facility'
MAP_STATE_DASHBOARD = 'E2E Map State Dashboard'
# 시설·지도 중심(시드의 부지·구역 옆). 카메라가 시설 위에 있어야 3D 가 화면에 들어온다.
MAP_FACILITY_CENTER = (127.0025, 37.0005)
# 시설 밖 출력 마커(팬)와 그 담당 구역 — 지도 장치 상태 검사(J-state 지도 장치)가 쓴다.
# 시드 시설(중심)과 상태 검사 시설(동쪽 0.0002) 둘 다와 겹치지 않게 서쪽에 둔다.
MAP_DEVICE_MARKER = (127.0021, 37.0005)
DEVICE_AREA_NAME = 'E2E Fan Area'
# 라벨 마스터(show_labels)를 끈 지도 — 장치가 점 마커로 그려지는 화면. 위젯 옵션 서버 기본은
# show_labels=True 이고 show_device_labels 는 그 값을 따르므로, 점 마커를 보려면 마스터를 꺼야 한다.
MAP_DOT_DASHBOARD = 'E2E Map Dot Dashboard'

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

# 물 회로 지형(DEM) 바꾸기 — 합성 고도 타일 서버(`dem_server.py`, 컴포즈 서비스 dem-tiles)에서 받는 두 입력.
# 지금 쓰는 DEM 은 완만한 경사, 비교 후보는 가파른 경사다.
DEM_GENTLE = 'E2E DEM Gentle'
DEM_STEEP = 'E2E DEM Steep'
DEM_TILE_BASE = 'http://dem-tiles:8099'
DEM_MAX_ZOOM = 14

# 구획 — 일지·목표 화면이 고르는 대상.
GEO_PLOT = 'E2E Plot'
GEO_PLOT_SUBJECT = 'E2E Crop'

# 시드가 만드는 개수 — 테스트가 "몇 개여야 하는가"를 여기서 읽는다.
EXPECTED_INPUTS = 2
EXPECTED_OUTPUTS = 3
EXPECTED_OUTPUT_MULTI_CHANNELS = 3
