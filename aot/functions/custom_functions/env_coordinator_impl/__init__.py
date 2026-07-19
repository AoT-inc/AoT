# coding=utf-8
"""
env_coordinator_impl — env_coordinator.py 구현 분리 패키지 (P2-3).

env_coordinator.py 는 AoT 함수 탐색기가 직접 로드하는 진입점이므로
파일명을 변경하거나 패키지로 전환할 수 없다.
구현 세부 사항을 이 패키지의 Mixin 클래스로 분리해 메인 파일을 간결하게 유지한다.

CustomModule 상속 구조:
    CustomModule(AbstractFunction,
                 ProfileLoaderMixin,
                 RuntimeStateMixin,
                 CycleMixin,
                 HelpersMixin)
"""
