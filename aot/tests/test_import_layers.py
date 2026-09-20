# coding=utf-8
"""패키지 간 import 방향 검사(ARCHITECTURE.md §4) — CI/훅과 같은 진입점.

실제 검사 로직은 aot/scripts/check_import_layers.py 하나뿐이다(pre-commit
훅과 Import Layers CI 워크플로가 그 스크립트를 직접 부른다). 이 테스트는
그 모듈을 import 해서 워킹트리에 baseline 을 벗어나는 새 위반이 없는지만
확인한다 — 네트워크도 DB 도 필요 없다. 실제 규칙(무엇이 금지되는가)이나
baseline 값 자체를 다시 구현하지 않는다: 그러면 로직이 두 곳에 생겨
드리프트만 는다(test_env_summary.py 가 check_alembic_head 를 부르는 것과
같은 이유).
"""
from aot.scripts import check_import_layers as _import_layers


def test_no_new_import_layer_violations():
    new, _resolved = _import_layers.run_checks()
    assert not new, (
        'baseline 에 없는 새 import 방향 위반: '
        f'{sorted(new)} — ARCHITECTURE.md §4 참고, 되돌릴 수 없다면 검토 후 '
        'import_layers_baseline.txt 를 갱신하세요.'
    )
