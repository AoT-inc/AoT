# -*- coding: utf-8 -*-
"""모듈 import 시점에 굳지 않는 조합 라벨 헬퍼.

``f"{lazy_gettext('A')} ({lazy_gettext('B')})"`` 나 ``"{} ({})".format(lazy_gettext(..), ..)``
는 모듈이 처음 import 될 때 ``str()`` 이 실행돼, 그 시점의 기본 로케일(영어)로 라벨이
영구히 굳는다. flask_babel 의 ``LazyString`` 은 결과를 캐시하지 않으므로, 조합 전체를
한 겹 더 lazy 로 감싸면 요청마다 그 요청의 로케일로 다시 계산된다.
"""
from flask_babel.speaklater import LazyString


def lazy_join(*parts):
    """lazy_gettext() 값과 리터럴 문자열을 이어 붙이되, 접근할 때마다 계산한다."""
    return LazyString(lambda: ''.join(str(p) for p in parts))


def lazy_format(template, *args, **kwargs):
    """``template.format(*args, **kwargs)`` 를 접근할 때마다 계산한다.

    template 자체가 lazy_gettext() 여도 된다(번역된 템플릿을 쓴다).
    """
    def _render():
        return str(template).format(
            *[str(a) if isinstance(a, LazyString) else a for a in args],
            **{k: str(v) if isinstance(v, LazyString) else v
               for k, v in kwargs.items()})
    return LazyString(_render)
