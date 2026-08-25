# coding=utf-8
"""서드파티 고지가 실물과 어긋나지 않게 한다.

이 파일이 존재하는 이유는 두 번의 실패다.

  1. `THIRD-PARTY-LICENSES.md` 는 2026-07-25 에 한 번 만들어졌지만 저장소에
     들어오지 못했다 — 루트 `.gitignore` 가 화이트리스트 방식(`/*` 전부 무시)
     이라 `!/이름` 을 넣지 않으면 조용히 미추적된다. 아무도 몰랐다.
  2. `gridstack-all.js` 는 첫 줄에서 `gridstack-all.js.LICENSE.txt` 를
     가리키는데 그 파일이 vendoring 될 때 따라오지 않았다. 배포물이 있지도
     않은 고지를 가리키고 있었다.

둘 다 "사람이 안 보면 안 걸리는" 종류라 검사로 고정한다.
"""
import os
import re
import subprocess
import unittest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
_NOTICE = os.path.join(_ROOT, 'THIRD-PARTY-LICENSES.md')

# 고지가 다뤄야 하는 자산. 벤더 디렉터리와, 그 밖에 흩어져 있는 반입 파일들.
_VENDOR_DIRS = (
    'aot/aot_flask/static/js/vendor',
    'aot/aot_flask/static/vendor',
)
_VENDOR_STRAYS = (
    'aot/aot_flask/static/js/common/turf.min.js',
    'aot/aot_flask/static/js/widgets/AoT_facility/three.min.js',
    'aot/aot_flask/static/js/widgets/AoT_facility/three-mesh-bvh.js',
    'aot/aot_flask/static/css/gridstack.css',
)


# 라이브러리를 식별하지 못하는 경로 조각. 이것들을 토큰으로 쓰면 문서 아무
# 곳에나 있는 'vendor' 같은 낱말에 걸려 **검사가 전부 통과한다**(역검증에서
# 실제로 그랬다 — maplibre 언급을 전부 지워도 통과했다).
_GENERIC_SEGMENTS = frozenset((
    '', 'aot', 'aot_flask', 'static', 'js', 'css', 'vendor', 'widgets',
    'common', 'map', 'webfonts', 'dist',
))


def _tracked(paths):
    """git 이 추적하는 파일만. 추적 안 되는 것은 배포되지 않으므로 고지 대상이
    아니다(node_modules 가 여기서 걸러진다)."""
    try:
        out = subprocess.run(['git', 'ls-files', '--'] + list(paths),
                             cwd=_ROOT, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return [p for p in out.stdout.splitlines() if p.strip()]


class TestNoticeExists(unittest.TestCase):
    def test_the_file_is_present(self):
        self.assertTrue(os.path.exists(_NOTICE),
                        'THIRD-PARTY-LICENSES.md 가 없다 — 한 번 유실된 적이 있다')

    def test_git_actually_tracks_it(self):
        """루트 .gitignore 는 화이트리스트다. `!/THIRD-PARTY-LICENSES.md` 가
        빠지면 파일은 있는데 배포되지 않는다 — 정확히 지난번 실패다."""
        tracked = _tracked(['THIRD-PARTY-LICENSES.md'])
        if tracked is None:
            self.skipTest('git 을 쓸 수 없는 환경')
        self.assertEqual(tracked, ['THIRD-PARTY-LICENSES.md'],
                         '.gitignore 화이트리스트에 !/THIRD-PARTY-LICENSES.md 를 넣을 것')

    def test_the_readme_points_at_it(self):
        with open(os.path.join(_ROOT, 'README.rst'), encoding='utf-8') as f:
            self.assertIn('THIRD-PARTY-LICENSES.md', f.read())


class TestNoticeMatchesReality(unittest.TestCase):
    def setUp(self):
        if not os.path.exists(_NOTICE):
            self.skipTest('고지 파일 없음')
        with open(_NOTICE, encoding='utf-8') as f:
            self.text = f.read()

    def test_every_vendored_asset_is_covered(self):
        """라이브러리를 새로 반입하고 고지를 빠뜨리면 여기서 걸린다.

        파일 하나하나가 아니라 **이름이 언급되었는지**를 본다 — 소스맵이나
        Highcharts 처럼 파일이 여럿인 라이브러리를 한 줄로 적을 수 있어야 한다.
        """
        files = _tracked(list(_VENDOR_DIRS) + list(_VENDOR_STRAYS))
        if files is None:
            self.skipTest('git 을 쓸 수 없는 환경')
        self.assertTrue(files, '벤더 파일을 하나도 못 찾았다 — 경로 목록을 확인할 것')

        uncovered = []
        for path in files:
            if path.endswith(('.map', '.LICENSE.txt')):
                continue
            name = os.path.basename(path)
            stem = re.split(r'[-.]\d|\.min|\.js$|\.css$', name)[0]
            # 상위 디렉터리를 **끝까지** 훑는다. 바로 위 디렉터리만 보면
            # `fontawesome-5.11.2/webfonts/fa-solid-900.woff2` 가 'webfonts'
            # 로만 판정돼, 라이브러리 이름으로 덮여 있는데도 누락으로 잡힌다.
            ancestors = [seg for seg in os.path.dirname(path).split(os.sep)
                         if seg not in _GENERIC_SEGMENTS]
            tokens = [name, stem] + ancestors
            # 대소문자를 맞추지 않는다 — 파일명은 소문자, 문서는 고유명사
            # 표기(Highcharts)라 그대로 비교하면 전부 누락으로 잡힌다.
            lowered = self.text.lower()
            if any(t and t.lower() in lowered for t in tokens):
                continue
            uncovered.append(path)

        self.assertEqual([], uncovered,
                         '고지에 없는 반입 자산: %s' % uncovered)

    def test_referenced_paths_exist(self):
        """없는 파일을 가리키는 고지는 고지가 아니다."""
        missing = []
        for path in re.findall(r'`([a-zA-Z0-9_./-]+/[a-zA-Z0-9_./-]+)`', self.text):
            if path.endswith('/'):
                continue
            for base in ('aot/aot_flask/static/', ''):
                if os.path.exists(os.path.join(_ROOT, base + path)):
                    break
            else:
                missing.append(path)
        self.assertEqual([], missing, '고지가 가리키는데 없는 경로: %s' % missing)

    def test_the_highcharts_commercial_caveat_survives(self):
        """Highcharts 는 오픈소스가 아니다. 상업 재배포에는 별도 라이선스가
        필요하다는 경고가 사라지면, 그것을 모르고 재배포하는 사람이 생긴다."""
        self.assertIn('Highcharts', self.text)
        self.assertIn('상용', self.text)

    def test_data_source_credits_are_linked_not_duplicated(self):
        """자료 출처는 성격이 달라 문서가 따로 있다 — 두 곳에 적으면 갈라진다."""
        self.assertIn('#data-credits', self.text)


if __name__ == '__main__':
    unittest.main()
