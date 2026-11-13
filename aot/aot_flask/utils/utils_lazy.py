# coding=utf-8
"""처음 쓰일 때 계산하는 값 — 설정 모달 조각 요청(`*_type=options`)용.

모달 템플릿은 수십 개 조각을 포함하고, 그중 대부분은 장치 종류에 따라 일부만 실제로 쓴다. 그런데 핸들러는 요청마다
모든 선택지 목록(`choices_*`)·전체 테이블 조회를 먼저 만들어 템플릿에 넘겼다. 이 래퍼는 템플릿이 그 변수를 처음
순회·인덱싱할 때 한 번 계산하므로, 쓰지 않는 값은 만들지 않는다.
`|tojson` 처럼 파이썬 기본 타입을 요구하는 곳에는 쓰지 말 것(직렬화되지 않는다).
"""


class Lazy:
    __slots__ = ('_fn', '_val', '_done')

    def __init__(self, fn):
        self._fn = fn
        self._val = None
        self._done = False

    @property
    def value(self):
        if not self._done:
            self._val = self._fn()
            self._done = True
            self._fn = None
        return self._val

    def __iter__(self):
        return iter(self.value)

    def __len__(self):
        return len(self.value)

    def __getitem__(self, key):
        return self.value[key]

    def __contains__(self, item):
        return item in self.value

    def __bool__(self):
        return bool(self.value)

    def __getattr__(self, name):
        # 슬롯 이름은 위에서 처리된다. 나머지(.items/.get/.query 등)는 실제 값으로 넘긴다.
        if name.startswith('__'):
            raise AttributeError(name)
        return getattr(self.value, name)

    def __repr__(self):
        return repr(self.value)


def val(x):
    """Lazy 면 계산한 값, 아니면 그대로."""
    return x.value if isinstance(x, Lazy) else x
