# coding=utf-8
# 도구 계층(aot/tools)이 쓰는 프로바이더를 여기서 바인딩한다.
#
# aot.tools 는 aot.ai 를 직접 import 하지 않는다(ARCHITECTURE.md §4 규칙 3,
# `tools-no-ai` 가드). 대신 aot/tools/providers.py 의 레지스트리를 통해서만
# 이 패키지의 기능을 받는데, 그 등록은 **aot.ai 가 import 되는 시점에** 이
# __init__ 이 해 준다 — aot.ai 를 직접이든(`import aot.ai`) 간접이든
# (`from aot.ai.services.X import Y`) import 하기만 하면 패키지 __init__ 이
# 먼저 실행되므로 항상 이 바인딩이 먼저 끝난다.
#
# 지연 import 인 이유: 여기서 `aot.ai.services.tool_providers` 를 최상위로
# import 하면, 그 모듈이 (지연 import 로) 참조하는 서비스 모듈들이 순환
# import 를 만들 여지가 생긴다 — 그 서비스 모듈들 상당수가 결국 `aot.ai`
# 패키지 자체를 거슬러 import 하기 때문이다. 함수 안에서 부르면 __init__ 이
# 이미 끝난 뒤에 안전하게 그 체인이 돈다.


def _bind_tool_providers():
    from aot.ai.services.tool_providers import bind_all
    bind_all()


_bind_tool_providers()
