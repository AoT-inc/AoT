"""naive DB 열과 aware utc_now() 를 직접 비교·뺄셈하면 TypeError (11-03 get_screen 실패)."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FILES = [
    'aot/tools/data_tools/system.py',
    'aot/aot_flask/routes_notice.py',
    'aot/aot_flask/utils/utils_notice.py',
    'aot/ai/services/ai_facility_learning_service.py',
]
# aware utc_now() 를 *_at 열과 바로 잇는 식 (naive_utc 로 감싸지 않은 것)
BAD = re.compile(r'(?<!naive_utc\()(?<!_tk_naive_utc\()utc_now\(\)\s*-\s*\w+\.\w+_at\b'
                 r'|\w+\.\w+_at\s*<=?\s*utc_now\(\)')


def test_no_aware_now_against_naive_columns():
    hits = []
    for f in FILES:
        for n, line in enumerate((ROOT / f).read_text().splitlines(), 1):
            if BAD.search(line):
                hits.append('%s:%d %s' % (f, n, line.strip()))
    assert not hits, hits
