# coding=utf-8
"""L1 이 열어 볼 페이지와, 페이지마다 살아 있어야 하는 앵커.

**대상 선정은 자동이다.** 라우트 덤프에서 인자 없는 GET 을 가져와 아래
`NOT_A_PAGE` 로 거른다. 새 페이지를 추가하면 다음 실행부터 자동으로 검사
대상이 되고, 아무도 이 파일을 고치지 않아도 "부팅이 깨진 화면"은 걸린다.

`ANCHORS` 는 **선택**이다. 적어 둔 페이지는 그 요소가 실제로 그려졌는지까지
본다. 회귀가 잦았던 화면부터 채워 나간다.
"""

# 페이지가 아닌 것(JSON API·HTML 조각·파일). 접두사로 거른다.
#
# 새 라우트가 생기면 자동으로 L1 대상이 된다. 그것이 페이지가 아니면 여기에
# 추가한다 — 귀찮아 보이지만, 새 표면이 생겼다는 사실을 한 번은 보게 만드는
# 것이 목적이다.
NOT_A_PAGE = (
    '/api/', '/static/', '/widget_', '/widget/', '/dashboard_widget',
    '/logview/data', '/admin/upgrade_state', '/admin/upgrade_status',
    '/admin/dependency_status',
    # JSON·파일 응답
    '/brand-image', '/csrf-token', '/custom.css', '/favicon', '/robots.txt',
    '/health', '/daemonactive', '/inputstate', '/outputstate',
    '/outputcommcapable', '/ram', '/time', '/sun_bands', '/tab/list',
    '/remote_get_inputs', '/notice/api/', '/camera/detect',
    '/settings/custom_ui/presets', '/geo/input/options', '/geo/layer/options',
    '/geo/journal/plot_history', '/geo/journal/target_info',
    '/geo/model_assets',
    # 리디렉션 전용
    '/index_page', '/location/entry', '/auth/', '/oauth/',
)

# 로그인한 사용자가 열면 되돌려지는 화면 — 부팅 판정 대상이 아니다.
# (L0 가 익명 상태에서 200 을 주는지 이미 확인한다.)
NOT_WHILE_LOGGED_IN = (
    '/login', '/login_password', '/login_totp', '/login_keypad',
    '/login_keypad_code/', '/create_admin', '/forgot_password',
    '/reset_password',
)

# 부팅 판정에서 제외할 경로 — L0 의 SKIP_GET 과 같은 사유.
SKIP = (
    '/logout', '/login/google/start', '/oauth/google/start',
    '/api/export_import/export_influxdb', '/api/export_import/export_settings',
    '/audit_log/export', '/logview/download', '/admin/backup',
)

# 페이지별 앵커: 경로 → CSS 선택자들. 전부 존재하고 높이가 0 이 아니어야 한다.
#
# 회귀가 잦았던 화면부터 적는다(§계획서 1-3). `data-testid` 가 붙기 전까지는
# 구조적으로 안정된 선택자만 쓴다 — 스타일 클래스는 리팩터마다 바뀌므로
# 앵커로 쓰지 않는다.
ANCHORS = {
    '/': ['nav.main-navbar'],
    '/live': ['nav.main-navbar'],
    '/geo/design': ['nav.main-navbar'],
    '/geo/facility': ['nav.main-navbar'],
    '/input': ['nav.main-navbar'],
    '/output': ['nav.main-navbar'],
    '/function': ['nav.main-navbar'],
    '/notes': ['nav.main-navbar'],
    '/settings/general': ['nav.main-navbar'],
}


def is_page(rule):
    if rule in SKIP or rule in NOT_WHILE_LOGGED_IN:
        return False
    return not any(rule.startswith(p) for p in NOT_A_PAGE)


def page_rules(routes):
    """검사 대상 페이지 경로 목록."""
    rules = sorted({
        r['rule'] for r in routes
        if 'GET' in r['methods'] and not r['has_args'] and is_page(r['rule'])
    })
    return rules
