# coding=utf-8
"""앱이 **실제로 등록한** 라우트 목록을 JSON 으로 내놓는다 (컨테이너 안에서 실행).

    docker compose -f docker/docker-compose.e2e.yml exec -T aot-app \
        python -m aot.tests.e2e.dump_routes /app/aot_local/e2e_routes.json

**stdout 으로 내보내지 않는다.** `create_app()` 이 부팅 로그를 stdout 으로
쏟기 때문에 JSON 과 섞인다(2026-09-17 실제로 겪음). 파일로 쓰고 읽는다.

소스를 grep 하지 않고 `app.url_map` 을 쓰는 이유: 블루프린트가 조건부로
등록되거나 데코레이터로 경로가 붙는 경우까지 포함해, 돌고 있는 앱의 진짜
표면을 얻기 위해서다. 새 페이지를 추가하면 다음 실행부터 자동으로 검사
대상이 된다 — L0 의 핵심 가치가 이것이다.
"""
import json
import sys


def collect():
    from aot.aot_flask.app import create_app
    from aot.config import ProdConfig

    app = create_app(ProdConfig)
    routes = []
    for rule in app.url_map.iter_rules():
        methods = sorted(rule.methods - {'HEAD', 'OPTIONS'})
        routes.append({
            'rule': str(rule),
            'endpoint': rule.endpoint,
            'methods': methods,
            # <int:id> 같은 변수부가 있으면 그대로는 못 부른다 — 테스트가
            # 건너뛸지 값을 채울지 판단하도록 표시만 해 둔다.
            'has_args': bool(rule.arguments),
            'arguments': sorted(rule.arguments),
        })
    routes.sort(key=lambda r: r['rule'])
    return routes


if __name__ == '__main__':
    out_path = sys.argv[1] if len(sys.argv) > 1 else '/app/aot_local/e2e_routes.json'
    routes = collect()
    with open(out_path, 'w') as f:
        json.dump(routes, f, ensure_ascii=False, indent=0)
    sys.stderr.write(f'라우트 {len(routes)}개를 {out_path} 에 썼습니다\n')
