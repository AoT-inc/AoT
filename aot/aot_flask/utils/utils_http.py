# -*- coding: utf-8 -*-
"""주기 폴링 JSON 응답용 조건부 요청(ETag/304) 헬퍼.

대시보드 위젯은 같은 엔드포인트를 5~30초마다 다시 부르는데, 실측해 보면 폴링
사이에 응답 바이트가 그대로인 경우가 대부분이다. 그래도 폰은 매번 라디오를 깨우고,
같은 JSON 을 다시 파싱하고, 화면을 다시 계산한다 — 모바일 발열의 가장 큰 원인이었다
(`.local/reports/mobile-battery-heat-audit-20260813.md`).

`json_conditional()` 은 응답 바이트의 해시를 ETag 로 달고, 클라이언트가 같은 값을
`If-None-Match` 로 돌려주면 **304(본문 0바이트)** 를 준다. 서버 DB 작업은 그대로
든다 — 줄이는 것은 회선과 단말이다.

**주의 — `Response.make_conditional(request)` 를 그냥 쓰면 안 된다.**
Flask-Compress(1.14)가 응답을 압축하면서 ETag 를 `"<hash>:br"` 로 고쳐 내보낸다.
클라이언트는 그 값을 그대로 돌려주는데 서버가 계산하는 것은 접미사 없는 `"<hash>"`
라 **절대 일치하지 않는다.** 에러도 경고도 없이 항상 200 이 나가므로, ETag 를
붙여 놓고 아무것도 아껴지지 않는 상태로 조용히 굴러간다. 실제로 그렇게 됐었다.
`incoming_etags()` 가 그 접미사(와 `W/` 접두사)를 벗기는 것이 이 모듈의 핵심이다.
"""
import hashlib

from flask import current_app


def incoming_etags(req):
    """`If-None-Match` 토큰들을 '알맹이 해시' 집합으로 정규화한다.

    벗기는 것 둘:
      - `W/` 약한 검증자 접두사
      - Flask-Compress 가 압축하며 붙이는 `:gzip` / `:br` / `:deflate` 접미사
    """
    raw = req.headers.get('If-None-Match', '')
    out = set()
    for token in raw.split(','):
        token = token.strip()
        if not token:
            continue
        if token.startswith('W/'):
            token = token[2:]
        token = token.strip('"')
        out.add(token.split(':', 1)[0])
    return out


def json_conditional(response, req):
    """이미 만들어진 JSON 응답에 ETag 를 달고, 일치하면 304 로 바꿔 돌려준다.

    Args:
        response: `jsonify(...)` 결과 (본문이 확정된 상태여야 한다).
        req: 현재 `flask.request`.

    Returns:
        200 응답(ETag 포함) 또는 본문 없는 304.

    `no-cache` 는 "캐시하되 매번 재검증"이다(no-store 아님). 다만 클라이언트는
    브라우저 HTTP 캐시가 조건부 요청을 가로채지 않도록 `cache:'no-store'` 로 부르고
    `If-None-Match` 를 직접 실어야 한다 — 그래야 304 가 JS 까지 올라와서 갱신 자체를
    건너뛸 수 있다. 브라우저에 맡기면 캐시본이 200 으로 둔갑해 파싱을 그대로 한다.
    """
    etag = hashlib.sha1(response.get_data()).hexdigest()

    if etag in incoming_etags(req):
        not_modified = current_app.response_class(status=304)
        not_modified.set_etag(etag)
        not_modified.cache_control.no_cache = True
        not_modified.cache_control.private = True
        return not_modified

    response.set_etag(etag)
    response.cache_control.no_cache = True
    response.cache_control.private = True
    return response
