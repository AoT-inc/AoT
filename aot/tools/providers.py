# coding=utf-8
"""도구 계층(aot/tools)이 내장 AI 패키지(aot/ai)에서 받아야 하는 기능을
**이름 있는 콜백**으로 정의하는 레지스트리.

ARCHITECTURE.md §4 규칙 3: 도구 계층은 aot.ai 를 직접 import 하지 않는다.
필요한 것은 여기 등록된 콜백을 통해서만 받는다 — `tools-no-ai` 가드
(aot/scripts/check_import_layers.py)가 이 경계를 강제한다.

등록은 이 모듈이 아니라 `aot/ai/services/tool_providers.py::bind_all()` 이
한다. `aot/ai/__init__.py` 가 import 될 때 자동으로 그 함수를 부른다 — 즉
누군가 `import aot.ai` 를 (직접이든, `aot.ai.*` 하위 모듈을 import 해서
간접이든) 한 번이라도 하면 이 레지스트리가 채워진다.

**조용히 우회하지 않는다.** `get()` 이 미등록 이름을 받으면 None 을 돌려주는
대신 `ProviderNotBound` 를 낸다 — 조용한 None 은 의존을 감추는 것과 같고,
문자열 경로 지연 import 로 에두르는 것도 마찬가지로 금지한다(설계 노트
P1-1b 참조).
"""

_REGISTRY = {}

# 실제로 쓰이는 프로바이더 이름 전체 — 문서 겸 `bind_all()` 완결성 테스트가
# 참조하는 목록. 새 프로바이더를 추가하면 여기도 같이 늘린다.
PROVIDER_NAMES = (
    'spatial_hierarchy',
    'device_zone_map',
    'job_scheduler',
    'anomaly_summary',
    'knowledge_search',
    'knowledge_library_populated',
    'knowledge_shelve',
    'domain_module',
    'source_sync',
    'tool_access_allowed',
    'mcp_active_server_ids',
    'reverse_lookup',
    'action_service',
    'data_source_query',
    'smartfarmkorea',
)


class ProviderNotBound(RuntimeError):
    """요청한 프로바이더가 아직 등록되지 않았다.

    가장 흔한 원인은 `aot.ai` 가 (직접이든 간접이든) 이 프로세스에서 한 번도
    import 되지 않은 것이다 — 실제 배포·앱 진입점은 항상 import 하므로,
    이 예외를 보는 자리는 대개 `aot.tools` 만 단독으로 로드한 스크립트나
    테스트다.
    """

    def __init__(self, name):
        super().__init__(
            "ProviderNotBound: %r — import aot.ai to bind the in-app providers"
            % (name,))
        self.name = name


def register(name, fn):
    """콜백을 이름으로 등록한다. 같은 이름 재등록은 이전 값을 덮어쓴다
    (재바인딩·테스트에서 필요)."""
    _REGISTRY[name] = fn


def get(name):
    """등록된 콜백을 돌려준다. 없으면 `ProviderNotBound`."""
    try:
        return _REGISTRY[name]
    except KeyError:
        raise ProviderNotBound(name) from None


def is_bound(name):
    """등록 여부만 확인한다(예외 없이) — 선택적 기능에 쓴다."""
    return name in _REGISTRY


def bound_names():
    """지금 등록된 이름의 스냅샷(정렬됨) — 진단·테스트용."""
    return tuple(sorted(_REGISTRY.keys()))


def _reset_for_tests():
    """테스트 전용: 레지스트리를 완전히 비운다. 프로덕션 코드에서 부르지
    말 것 — teardown 에서 반드시 `bind_all()` 로 복원해야 한다."""
    _REGISTRY.clear()
