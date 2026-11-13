# coding=utf-8
"""장치 종류 어휘의 별칭 계층 — 정본 7종으로 수렴시킨다.

정본: `VALID_DEVICE_KINDS` / `device_binding.device_kind_models()`
(input·output·device·function·pid·trigger·conditional). 코드베이스에는 같은
낱말이 다른 뜻으로 쓰이는 어휘가 있다 — 이 모듈이 그 차이를 한곳에 모은다.

  - 전역 별칭(정본과 충돌하지 않는다): 'custom_controller'→'device',
    'generic_function'→'function'.
  - 문맥 별칭 `vocabulary='geo'`(지도 UI·`/api/geo/device/location`): 여기서만
    'function' 이 CustomController 를 뜻한다. 전역 별칭으로 만들면 정본의
    'function'(=Function)과 충돌하므로 문맥 이름을 받는 변환으로 둔다.

동작을 바꾸지 않는다: 각 호출 자리의 dict 는 전환 전과 키·값이 같다.
"""
from aot.databases.geo_integrity_ddl import VALID_DEVICE_KINDS

#: 정본 7종 — `device_binding.device_kind_models()` 와 같은 출처·같은 순서.
CANONICAL_KINDS = VALID_DEVICE_KINDS

#: 어느 문맥에서나 같은 뜻인 별칭.
KIND_ALIASES = {
    'custom_controller': 'device',
    'generic_function': 'function',
}

#: 문맥별 별칭 — 전역 별칭을 덮어쓴다. 값은 정본 종류.
VOCABULARY_ALIASES = {
    'geo': {
        'device': 'device',
        'function': 'device',      # 지도에서 'function' 은 CustomController
        'custom': 'device',
        'generic_function': 'function',
    },
}


def canonical_kind(name, *, vocabulary=None):
    """어휘 `name` 을 정본 종류로. 모르면 ValueError."""
    key = str(name).strip().lower() if name is not None else ''
    if vocabulary is not None:
        try:
            table = VOCABULARY_ALIASES[vocabulary]
        except KeyError:
            raise ValueError('unknown vocabulary: %r' % (vocabulary,))
        if key in table:
            return table[key]
    if key in KIND_ALIASES:
        return KIND_ALIASES[key]
    if key in CANONICAL_KINDS:
        return key
    raise ValueError('unknown device kind: %r' % (name,))


def models_for(names, *, vocabulary=None):
    """`names`(그 자리의 어휘)를 키로, 정본 모델을 값으로 하는 dict.

    키 순서는 `names` 순서 그대로다. 그 자리만의 추가 키('camera',
    'program')는 호출 쪽에서 덧붙인다.
    """
    from aot.space.device_binding import device_kind_models
    canonical = dict(device_kind_models())
    return {n: canonical[canonical_kind(n, vocabulary=vocabulary)]
            for n in names}
