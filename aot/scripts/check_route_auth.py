#!/usr/bin/env python3
# coding=utf-8
"""라우트 인증 게이트 점검 — 로그인 없이 접근 가능한 엔드포인트를 찾는다.

AoT에는 전역 `before_request` 인증 강제가 없다. 각 뷰가 개별적으로
`@flask_login.login_required`(또는 `@login_required`, `@auth_admin`)를 붙이는
구조라, 하나 빠뜨려도 아무 데서도 드러나지 않는다 — 그래서 정적으로 대조한다.

`check_static_refs.py`와 같은 자리에 두고 같은 방식으로 쓴다:

    python3 aot/scripts/check_route_auth.py          # 종료코드 0 = 문제 없음
    python3 aot/scripts/check_route_auth.py --all    # 공개 허용 목록까지 전부 출력

의도적으로 공개인 라우트는 아래 PUBLIC_ROUTES 에 사유와 함께 등록한다.
새 라우트를 인증 없이 추가하면 이 스크립트가 실패하므로, 공개가 맞다면
목록에 사유를 적어 넣어야 한다(리뷰 지점을 강제하는 것이 목적).

AST 로 파싱하므로 문자열 grep 과 달리 주석·문자열 안의 유사 패턴에 속지 않는다.
"""
import argparse
import ast
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCAN_DIR = os.path.join(REPO_ROOT, 'aot')

# 인증 게이트로 인정하는 데코레이터 이름
AUTH_DECORATORS = {
    'login_required',            # from flask_login import login_required
    'flask_login.login_required',
    'auth_admin',                # 원격/관리 전용 래퍼
}

# 라우트 등록 데코레이터
ROUTE_DECORATORS = {'route', 'blueprint.route', 'app.route'}

# 데코레이터 대신 본문 첫머리에서 권한을 확인하는 관용구도 인증 게이트로 인정한다.
# utils_general.user_has_permission() 은 익명 사용자에 대해 False 를 반환하므로
# (routes 대부분이 쓰는 `if not user_has_permission(...): return redirect(...)`
# 패턴), 데코레이터만 보면 이런 뷰가 전부 미보호로 오탐된다.
BODY_AUTH_CALLS = {
    'user_has_permission',
    'utils_general.user_has_permission',
}

# 인증 없이 공개하는 것이 의도된 라우트: rule -> 사유
# 새 항목을 넣을 때는 "왜 공개여도 되는가"를 반드시 적을 것.
PUBLIC_ROUTES = {
    # 인증 자체를 수행하는 화면 — 로그인해야 볼 수 있으면 로그인이 불가능하다
    '/login': '로그인 진입점',
    '/login_password': '비밀번호 로그인 폼',
    '/login_keypad': '키패드 로그인 폼',
    '/login_keypad_code/': '키패드 코드 입력(빈 값)',
    '/login_keypad_code/<code>': '키패드 코드 검증',
    '/login_totp': '2단계 인증 입력 — 비밀번호 검증 후 단계이나 아직 미로그인 상태',
    '/login/google/start': 'Google 로그인 시작',
    '/login/google/callback': 'Google 로그인 콜백',
    '/create_admin': '최초 관리자 생성(관리자가 없을 때만 동작)',
    '/forgot_password': '비밀번호 재설정 요청',
    '/reset_password': '비밀번호 재설정 수행(코드로 인증)',

    # 서버 간 호출 — 자체 자격증명으로 인증한다
    '/newremote/': '원격관리 등록: 사용자명+비밀번호로 인증 후 토큰 발급',
    '/remote_login': '원격관리 로그인: 발급 토큰으로 인증',

    # 정적/공개 자원
    '/favicon.png': '파비콘',
    '/robots.txt': '크롤러 지침',

    # 헬스체크 — 컨테이너 교체 중 "새 빌드가 실제로 서빙하는가"를 물어야 하는
    # 자리라 로그인 세션을 전제할 수 없다. 익명 응답은 {status, docker} 뿐이고
    # 버전·스키마 리비전은 로그인 세션 또는 AOT_HEALTH_KEY 를 요구한다.
    '/health': '헬스체크(익명은 생존여부만, 상세는 인증/키 필요)',

    # 세션 부수 기능
    '/csrf-token': 'CSRF 토큰 재서명 — 세션이 이미 가진 비밀을 갱신할 뿐 새 권한 없음',
    '/logout': 'flask_login.login_required 가 붙어 있으나 목록 유지(가독성)',

    # 로그인 전에도 동작해야 하는 표시 계층
    '/': '랜딩 — 로그인 여부에 따라 분기',
    '/index_page': '랜딩 분기 처리',
    '/custom.css': '테마 CSS — 로그인 화면에도 적용되어야 한다',
    '/api/v1/locale': '현재 언어 조회 — 로그인 화면의 언어 선택에 필요',
    '/api/v1/locale/set': '언어 변경(세션 값만 바꾼다) — 로그인 전 언어 선택 지원',
    '/api/v1/locale/js': 'JS 번역 사전 — 로그인 화면에서도 로드된다',

    # 법적 고지 — 로그인 없이 열람 가능해야 한다
    '/privacy-policy': '개인정보처리방침',
    '/terms-of-service': '이용약관',

    # 외부 인증 콜백 — 아직 세션이 없는 상태로 돌아온다
    '/oauth/google/callback': 'Google OAuth 콜백(state 로 검증)',

    # 위젯 타이머 동기화용 공개 엔드포인트(이름에 _public 명시).
    # 노출 정보는 "해당 출력이 언제 켜졌는가/얼마나 켜져 있었는가"로 한정되며
    # 제어 기능은 없다. 키오스크·공개 대시보드에서 로그인 없이 쓰도록 만든 것.
    # 주의: 아래 두 규칙은 사실상 동일한 URL 이 서로 다른 파일에 중복 등록된
    # 상태다(routes_output.py / routes_general.py). 블루프린트 등록 순서에 따라
    # 한쪽이 가려지므로 정리가 필요하다 — 별도 이슈.
    '/output_started_at_public/<device_unique_id>/<channel_id>':
        '위젯 타이머 동기화(중복 등록 — 정리 필요)',
    '/output_started_at_public/<string:device_unique_id>/<string:channel_id>':
        '위젯 타이머 동기화(중복 등록 — 정리 필요)',
    '/output_last_duration_public/<unique_id>/<channel>':
        '위젯 타이머 동기화 — 마지막 동작 시간',
}


def _decorator_name(node):
    """데코레이터 AST 노드에서 점 표기 이름을 뽑는다."""
    if isinstance(node, ast.Call):
        node = node.func
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return '.'.join(reversed(parts))


def _has_body_auth_guard(func_node):
    """본문에서 user_has_permission() 계열 호출로 권한을 확인하는가."""
    for node in ast.walk(func_node):
        if isinstance(node, ast.Call) and _decorator_name(node) in BODY_AUTH_CALLS:
            return True
    return False


def _route_rules(node):
    """route 데코레이터에서 URL 규칙 문자열들을 뽑는다."""
    rules = []
    if isinstance(node, ast.Call) and node.args:
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            rules.append(first.value)
    return rules


def scan_file(path):
    """(rule, func_name, lineno, has_auth) 목록."""
    try:
        with open(path, encoding='utf-8') as fh:
            tree = ast.parse(fh.read(), filename=path)
    except (SyntaxError, UnicodeDecodeError):
        return []

    results = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue

        names = [_decorator_name(d) for d in node.decorator_list]
        route_rules = []
        for dec in node.decorator_list:
            if _decorator_name(dec) in ROUTE_DECORATORS:
                route_rules.extend(_route_rules(dec))

        if not route_rules:
            continue

        has_auth = (any(n in AUTH_DECORATORS for n in names)
                    or _has_body_auth_guard(node))
        for rule in route_rules:
            results.append((rule, node.name, node.lineno, has_auth))
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--all', action='store_true',
                        help='공개 허용 목록에 등록된 라우트까지 전부 출력')
    args = parser.parse_args()

    all_routes = []
    for root, dirs, files in os.walk(SCAN_DIR):
        dirs[:] = [d for d in dirs
                   if d not in ('__pycache__', 'node_modules', 'tests', 'static')]
        for name in files:
            if not name.endswith('.py'):
                continue
            path = os.path.join(root, name)
            rel = os.path.relpath(path, REPO_ROOT)
            for rule, func, lineno, has_auth in scan_file(path):
                all_routes.append((rule, func, rel, lineno, has_auth))

    unprotected = [r for r in all_routes if not r[4]]
    unknown = [r for r in unprotected if r[0] not in PUBLIC_ROUTES]
    known = [r for r in unprotected if r[0] in PUBLIC_ROUTES]

    print('스캔한 라우트: %d개 (인증 있음 %d / 없음 %d)'
          % (len(all_routes), len(all_routes) - len(unprotected), len(unprotected)))
    print('공개 허용 목록에 등록됨: %d / 미등록: %d' % (len(known), len(unknown)))

    if args.all and known:
        print('\n[의도된 공개 라우트]')
        for rule, func, rel, lineno, _ in sorted(known):
            print('  %-32s %s  (%s:%d)' % (rule, PUBLIC_ROUTES[rule], rel, lineno))

    if unknown:
        print('\n[!] 인증 데코레이터가 없고 공개 허용 목록에도 없는 라우트:')
        for rule, func, rel, lineno, _ in sorted(unknown):
            print('  %-40s %s()  %s:%d' % (rule, func, rel, lineno))
        print('\n각 항목을 확인하고, 공개가 맞다면 이 스크립트의 PUBLIC_ROUTES 에')
        print('사유와 함께 등록하십시오. 아니라면 인증 데코레이터를 추가하십시오.')
        return 1

    print('\nOK: 인증 게이트 없는 라우트가 전부 공개 허용 목록에 등록되어 있습니다.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
