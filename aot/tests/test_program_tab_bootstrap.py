# coding=utf-8
"""프로그램 화면은 **탭이 없는 설치에서도** 쓸 수 있어야 한다.

이 화면의 편집은 전부 탭을 전제로 한다(`GeoProgram.tab_id`). 그런데 새 설치에는
`page_type='program'` 탭이 없다 — 다른 페이지는 장치를 **추가할 때**
`get_default_tab` 이 만들지만, 이 화면의 생성은 클라이언트 API 라 그 경로를
지나지 않는다. 그래서 처음 여는 사람은 탭도 없고 레거시 백필도 못 돌아,
**이름조차 저장되지 않는 화면**을 본다. 2026-08-23 koat 에서 실제로 그랬고,
사용자가 손으로 탭을 만들자 그때부터 동작했다.
"""
import os
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.join(_HERE, '..')


def _read(*parts):
    with open(os.path.join(_ROOT, *parts), encoding='utf-8') as fh:
        return fh.read()


def _fn(src, name):
    """`def <name>(` 부터 다음 최상위 `def`/`@` 까지."""
    head = src.split('def %s(' % name, 1)[1]
    out = []
    for line in head.split('\n'):
        if line.startswith(('def ', '@')) and out:
            break
        out.append(line)
    return '\n'.join(out)


class TestProgramPageBootstrapsItsTab(unittest.TestCase):

    def test_the_page_creates_the_default_tab_when_none_exists(self):
        body = _fn(_read('aot_flask', 'routes_geo.py'), 'page_programs')
        self.assertIn("TabService.get_default_tab('program')", body)
        # 부트스트랩은 `if current_tab:` **밖**에 있어야 한다 — 안에 두면
        # 만들려는 그것이 이미 있어야 만들어지는 순환이 된다.
        boot = body.split("current_tab = current_tab or", 1)[1] \
                   .split('if current_tab:', 1)[0]
        self.assertIn("get_default_tab('program')", boot)

    def test_it_asks_whether_any_tab_exists_not_whether_one_is_visible(self):
        """**보이는 탭이 없다**는 것과 **탭이 없다**는 것은 다르다.

        그룹 스코프로 남의 탭만 가려진 경우까지 새 탭을 만들면, 만들 권한이 없는
        사람의 화면에서 자원이 늘어난다.
        """
        body = _fn(_read('aot_flask', 'routes_geo.py'), 'page_programs')
        boot = body.split("current_tab = current_tab or", 1)[1] \
                   .split('if current_tab:', 1)[0]
        self.assertIn("TabService.get_tabs_for_page('program')", boot)
        self.assertNotIn("not TabService.visible_tabs_for_page('program')", boot)

    def test_the_client_no_longer_claims_a_null_tab_is_impossible(self):
        """옛 주석이 "null 로 남는 경우는 사실상 없다" 고 단언했고 그것이 틀렸다.

        문서가 거짓말을 하면 다음 사람이 그 자리를 의심하지 않는다.
        """
        js = _read('aot_flask', 'static', 'js', 'geo', 'program-settings.js')
        # 낱말이 아니라 **주장이 서 있는지**를 본다 — 지금 그 문장은 "틀렸다" 는
        # 정정과 함께만 나온다. 인용까지 금지하면 왜 틀렸는지 적을 수 없다
        # (같은 함정을 `descendants` 검사에서 한 번 겪었다).
        self.assertIn('null 로 남는 경우는 사실상 없다', js)
        self.assertIn('**틀렸다.**', js)


if __name__ == '__main__':
    unittest.main()
