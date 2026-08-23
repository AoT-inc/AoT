# coding=utf-8
"""지도 위젯 시설 모달이 **내부 키를 그대로 보이지 않는지** 지킨다.

프론트의 라벨 표는 서버가 보내는 어휘를 그대로 받아야 하는데, 둘이 갈려도
에러가 나지 않는다 — 라벨이 없으면 키를 그대로 그리기 때문이다. 2026-08-20
화면에 `cooler 100%` · `fogger 86%` · `heater 0%` 가 그대로 떴다(프론트 표에는
`heating`/`cooling`/`humidifier` 라고 적혀 있었고 커튼만 우연히 일치했다).

문구도 같이 본다: 라벨을 추가하고 번역을 빠뜨리면 그 자리만 영어로 남는다.
"""
import json
import os
import re
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.join(_HERE, '..')
_POPUP = os.path.join(_ROOT, 'aot_flask', 'static', 'js', 'widgets',
                      'AoT_map', 'aot-map-popup.js')
_KO = os.path.join(_ROOT, 'aot_flask', 'translations', 'ko',
                   'LC_MESSAGES', 'messages.po')


def _read(path):
    with open(path, encoding='utf-8') as fh:
        return fh.read()


def _js_map(name):
    """`var <name> = { a: 'A', ... };` → dict."""
    src = _read(_POPUP)
    body = src.split('var %s = {' % name, 1)[1].split('};', 1)[0]
    return dict(re.findall(r"(\w+)\s*:\s*'([^']*)'", body))


class TestKindLabelsMatchServer(unittest.TestCase):

    def test_every_server_kind_has_a_label(self):
        """서버 어휘(`_KIND_CAPABILITIES`)의 종류는 전부 라벨이 있어야 한다."""
        from aot.functions.custom_functions.env_coordinator_impl._function_info \
            import _KIND_CAPABILITIES
        labels = _js_map('_KIND_LABELS')
        missing = sorted(set(_KIND_CAPABILITIES) - set(labels))
        self.assertEqual([], missing,
                         '라벨 없는 종류 — 화면에 내부 키가 그대로 뜬다: %s' % missing)

    def test_no_invented_kinds(self):
        """서버가 보내지 않는 종류를 프론트가 지어내지 않는다 — 있으면 그 표를
        보고 "이런 장치도 있나" 로 읽게 되고, 진짜 어휘와 갈린 채 방치된다."""
        from aot.functions.custom_functions.env_coordinator_impl._function_info \
            import _KIND_CAPABILITIES
        labels = _js_map('_KIND_LABELS')
        extra = sorted(set(labels) - set(_KIND_CAPABILITIES))
        self.assertEqual([], extra, '서버에 없는 종류: %s' % extra)

    def test_mode_and_kind_labels_are_translated(self):
        """운전 모드·장치 종류 라벨은 화면 맨 앞에 나오는 문구다. 번역이 없으면
        한국어 화면에 영어 단어만 남는다(2026-08-20 'Conservation · Partial
        Control')."""
        po = _read(_KO)
        for name in ('_MODE_LABELS', '_KIND_LABELS', '_LIMIT_LABELS'):
            for key, msgid in _js_map(name).items():
                needle = 'msgid "%s"\nmsgstr "' % msgid
                self.assertIn(needle, po, '%s: %r 번역 없음' % (name, msgid))
                after = po.split(needle, 1)[1].split('"', 1)[0]
                self.assertTrue(after.strip(),
                                '%s: %r 번역이 비어 있다' % (name, msgid))


class TestOverviewReadsServerFields(unittest.TestCase):
    """서버가 보내는 키를 화면이 실제로 읽는지 — 이름이 갈리면 그 값은 영영
    안 뜨는데 에러는 나지 않는다."""

    def test_photosynthesis_reads_crop_not_subject(self):
        src = _read(_POPUP)
        self.assertIn('ph.crop', src,
                      '서버는 photo.crop 으로 보낸다 — subject 만 읽으면 작물명이 안 뜬다')

    def test_status_tab_keeps_only_what_answers_now(self):
        """[현황]은 "지금 어떤가 · 무엇이 움직이나" 만 답한다.

        목표 목록·날짜·운전 모드는 그 질문에 답하지 않으면서 칸을 차지했다
        (2026-08-20 사용자 지적). 목표는 **값 옆**으로, 게이트는 제어 상태로
        갔고 나머지는 뺐다.
        """
        body = _read(_POPUP).split('function buildOverviewSection', 1)[1].split(
            '\n  function ', 1)[0]
        for gone in ("_t('Status Summary')", '_MODE_LABELS', 'summary.trend',
                     'aot-coord-plot', "_t('Deviation from target')",
                     'feedforward'):
            self.assertNotIn(gone, body, '[현황]에 남아 있다: %s' % gone)

    def test_target_sits_next_to_the_value(self):
        """25.1°C 만 보면 좋은지 나쁜지 모르고, 목표만 표로 보면 지금 어떤지
        모른다 — 둘은 붙어 있어야 뜻이 생긴다.

        2026-08-20 부터 그 자리는 **밴드 바**다: 목표는 축 위 자기 위치에 눈금
        라벨로 서고(`at`), 편차는 마커가 목표에서 얼마나 떨어져 있는지로 보인다.
        그래서 `opts.deviation`(작은 글씨 한 줄)은 더 이상 읽지 않는다 — 축이
        같은 말을 더 잘 하고, 줄이 하나 줄어든다.
        """
        body = _read(_POPUP).split('function _envNowRowHtml', 1)[1].split(
            '\n  function ', 1)[0]
        self.assertIn('opts.targets', body)
        self.assertIn('_NOW_TO_TARGET', body)
        # 목표는 **위치**로 말한다 — 값만 적고 자리를 안 주면 축 위 어디를
        # 가리키는지 알 수 없다.
        self.assertIn('at: anchorAt', body)

    def test_env_axis_comes_from_the_band_table(self):
        """축과 적정 구간은 **밴드 색과 같은 표**에서 온다.

        화면이 범위를 따로 들면 라벨 색과 축이 갈린다. 단위 환산(bandValue)도
        같이 써야 Pa 로 저장된 VPD 의 마커가 제자리에 선다.
        """
        body = _read(_POPUP).split('function _envNowRowHtml', 1)[1].split(
            '\n  function ', 1)[0]
        self.assertIn('bandScale', body)
        self.assertIn('bandValue', body)
        # 축을 모르는 지표는 **지어내지 않는다** — 머리줄만 낸다.
        self.assertIn('V.value(', body)

    def test_control_status_leads_with_why(self):
        """숫자를 늘어놓기 전에 **왜 그런지**를 먼저 말한다 — 설비 한계와 안전
        게이트가 그 이유다. 둘 다 장치 목록보다 앞이어야 한다."""
        body = _read(_POPUP).split("_t('Control Status')", 1)[1].split(
            '\n  function ', 1)[0]
        i_strain = body.index("_t('Not keeping up')")
        i_gate = body.index("_t('Safety Gate')")
        i_kinds = body.index("_t('Device opening')")
        self.assertLess(i_strain, i_kinds, '한계 경고가 장치 목록 뒤에 있다')
        self.assertLess(i_gate, i_kinds, '게이트가 장치 목록 뒤에 있다')

    def test_dates_are_not_repeated_next_to_the_axis(self):
        """시작일은 [구획] 의 기간 축이 보인다. 축이 있는데 같은 날짜를 표로 또
        적으면 읽을 것만 늘어난다(2026-08-20)."""
        src = _read(_POPUP)
        body = src.split('function buildOverviewSection', 1)[1].split(
            '\n  function ', 1)[0]
        for gone in ('sch.plot', 'sch.stage', 'sch.start'):
            self.assertNotIn(gone, body, '축과 겹치는 날짜가 남아 있다: %s' % gone)
        # 제어 종료일도 뺐다 — 남은 날수는 오늘 할 일을 바꾸지 않고, 실제로
        # 멈추면 "응답 없음 · 비활성" 이 말한다.
        self.assertNotIn("_t('Stop Control On')", body)

    def test_disabled_photosynthesis_says_nothing(self):
        """꺼진 기능은 설정이지 상태가 아니다 — [현황]에서 자리를 차지할 이유가
        없다."""
        src = _read(_POPUP)
        body = src.split('function buildOverviewSection', 1)[1].split(
            '\n  function ', 1)[0]
        self.assertIn('if (ph.enabled && phRows) {', body)
        self.assertNotIn('Photosynthesis-oriented control is off', body)

    def test_plot_block_shows_what_is_growing(self):
        """구획 블록이 대상과 단계를 말해야 한다 — 서버는 계속 보내는데 화면이
        안 그리던 자리다."""
        src = _read(_POPUP)
        body = src.split('function buildFacilityPlotsHtml', 1)[1].split(
            '\n  function ', 1)[0]
        self.assertIn('stage', body)


class TestNoInventedMeasurement(unittest.TestCase):
    """없는 측정을 기본값으로 지어내지 않는다 — 한 화면이 두 소리를 낸다."""

    def test_co2_has_no_default(self):
        src = _read(os.path.join(_ROOT, 'functions', 'utils', 'env_control',
                                 'situation.py'))
        self.assertIn("'CO2_int': internal.get('CO2'),", src,
                      "CO2 측정이 없을 때 400 을 지어내면 편차가 서고, 광합성 "
                      "블록은 같은 값을 '없음' 으로 보인다")


class TestInformationOrder(unittest.TestCase):
    """[현황]의 순서는 **개념 계층**이다 — 위치·시간 → 데이터 → 제어 → 기록물.

    큰 것에서 작은 것으로, 상위에서 하위로. 예전에는 "얼마나 행동을 부르는가"
    로 정렬했는데, 그 판단이 바뀔 때마다 순서가 흔들렸다. 계층은 안 흔들리고,
    **시설과 노지에 그대로 같이** 적용된다(사용자가 옮겨 다녀도 같은 자리에서
    같은 것을 찾는다).
    """

    _VEC = os.path.join(_ROOT, 'aot_flask', 'static', 'js', 'widgets',
                        'AoT_map', 'aot-map-widget-vector.js')

    def test_facility_layers_in_order(self):
        js = _read(self._VEC)
        body = js.split('var ovHtml =', 1)[1].split('var ovSame', 1)[0]
        i_hz = body.index('buildHazardsHtml')
        i_plots = body.index('data-slot="plots"')
        i_now = body.index('data-slot="now"')
        i_irr = body.index('buildIrrigationHtml')
        i_ctrl = body.index('buildOverviewSection')
        self.assertLess(i_hz, i_plots, '날씨(지역)가 구획(시설)보다 뒤에 있다')
        self.assertLess(i_plots, i_now, '위치·시간 층이 데이터 층보다 뒤에 있다')
        self.assertLess(i_now, i_irr, '데이터 층이 제어 층보다 뒤에 있다')
        self.assertLess(i_irr, i_ctrl, '마지막 관수는 제어 층 맨 위다')

    def test_zone_uses_the_same_layers(self):
        js = _read(_POPUP)
        body = js.split('function buildZoneStatusHtml', 1)[1].split(
            '\n  function ', 1)[0]
        i_plots = body.index('buildZonePlotsHtml')
        i_now = body.index('buildEnvNowHtml')
        i_rec = body.index('buildRecordBlock')
        self.assertLess(i_plots, i_now, '노지도 위치·시간 → 데이터 순이어야 한다')
        self.assertLess(i_now, i_rec)

    def test_async_blocks_have_fixed_slots(self):
        """자리를 먼저 깔지 않으면 **도착 순서가 배치를 정한다** — 응답이 늦는
        날에는 순서가 뒤바뀌고, 그러면 "환경 블록이 첫 자식" 같은 가정에 기대는
        코드가 생긴다."""
        js = _read(self._VEC)
        self.assertIn("pane.querySelector('[data-slot=\"now\"]')", js)
        self.assertIn("pane.querySelector('[data-slot=\"plots\"]')", js)

class TestActionButtons(unittest.TestCase):
    """**행동을 요구하는 요소는 블록의 오른쪽 아래에, 같은 모양으로.**

    예전에는 [노트 열기]가 제목 줄 오른쪽 위에 `.aot-ov-pill` 로, [구획 추가]가
    목록 아래에 `.aot-pill-btn` 으로 있었다 — 같은 모달 안에서 같은 무게의
    두 행동이 높이도 색도 자리도 달랐다. 자리는 `.aot-ov-actions` 하나,
    모양은 `.aot-ov-pill` 하나로 고정한다.
    """

    _SENSOR_LABEL = os.path.join(_ROOT, 'aot_flask', 'static', 'js', 'common',
                                 'sensor-label.js')
    _CSS = os.path.join(_ROOT, 'aot_flask', 'static', 'css', 'widget',
                        'aot-sensor-label.css')

    def test_notes_button_is_below_the_list_not_in_the_title(self):
        js = _read(self._SENSOR_LABEL)
        body = js.split('function notesBlockHtml', 1)[1].split(
            '\n  // 미리보기 목록', 1)[0]
        i_title = body.index("aot-ov-card-title")
        i_list = body.index('aot-ov-notes-list')
        i_btn = body.index('aot-ov-notes-open')
        self.assertLess(i_title, i_list)
        self.assertLess(i_list, i_btn, '노트 버튼이 목록보다 위에 있다')
        self.assertIn('aot-ov-actions', body, '행동 줄 없이 버튼만 있다')

    def test_both_buttons_use_the_same_component(self):
        notes = _read(self._SENSOR_LABEL).split(
            'function notesBlockHtml', 1)[1].split('\n  // 미리보기 목록', 1)[0]
        plots = _read(_POPUP).split(
            'function buildFacilityPlotsHtml', 1)[1].split(
            '\n  // 대상·품종 라벨', 1)[0]
        for name, body, cls in (('노트 열기', notes, 'aot-ov-notes-open'),
                                ('구획 추가', plots, 'aot-ov-plot-add')):
            row = [ln for ln in body.splitlines() if cls in ln]
            self.assertTrue(row, name + ' 버튼이 없다')
            line = row[0]
            self.assertIn('aot-ov-pill', line,
                          name + ' 버튼이 공용 알약 버튼이 아니다')
            self.assertNotIn('aot-pill-btn', line,
                             name + ' 버튼이 다른 컴포넌트를 쓴다')

    def test_plot_add_sits_in_an_action_row(self):
        plots = _read(_POPUP).split(
            'function buildFacilityPlotsHtml', 1)[1].split(
            '\n  // 대상·품종 라벨', 1)[0]
        i_row = plots.index('aot-ov-actions')
        i_btn = plots.index('aot-ov-plot-add')
        i_form = plots.index('aot-ov-plot-new-wrap')
        self.assertLess(i_row, i_btn, '버튼이 행동 줄 밖에 있다')
        self.assertLess(i_btn, i_form, '버튼이 접힌 폼보다 아래에 있다')

    def test_action_row_leaves_the_corner_radius_below(self):
        """버튼 아래 여백이 블록 모서리 반지름(16px)보다 작으면 버튼이 둥근
        모서리에 물린다. 여백은 블록 패딩이 맡으므로 행동 줄에 아래 여백을
        더하지 않는다 — 더하면 반대로 하단만 헐거워진다."""
        css = _read(self._CSS)
        block = css.split('.aot-ov-block {', 1)[1].split('}', 1)[0]
        self.assertIn('border-radius: 16px', block)
        self.assertIn('padding: var(--aot-space-4)', block)   # 16px
        row = css.split('.aot-ov-actions {', 1)[1].split('}', 1)[0]
        self.assertIn('justify-content: flex-end', row)
        margin = [ln for ln in row.splitlines() if 'margin' in ln][0]
        self.assertTrue(margin.rstrip().rstrip(';').endswith('0'),
                        '행동 줄에 아래 여백이 붙어 있다: ' + margin.strip())



    def test_no_button_lives_in_a_section_title_row(self):
        """제목 줄(`--row`)에 버튼을 다시 넣지 못하게 막는다.

        시설 [설명]·구획 [기본]·[단계 원장] 셋 다 제목 줄 오른쪽에 버튼이
        있었다. 하나씩 옮기면 다음에 만드는 사람이 남아 있는 것을 본보기로
        삼아 되돌아온다 — 남은 `--row` 는 값을 보이는 자리(센서 응답 n/m)
        뿐이어야 한다.
        """
        js = _read(_POPUP)
        for m in re.finditer(r'aot-ov-card-title--row', js):
            seg = js[m.end():m.end() + 900]
            seg = seg.split("'</div>'", 1)[0]
            self.assertNotIn('<button', seg,
                             '제목 줄에 버튼이 남아 있다: ' + seg[:120])

    def test_edit_buttons_sit_in_an_action_row(self):
        js = _read(_POPUP)
        # 접두사가 겹친다 — `aot-ov-desc-edit` 는 `…-editwrap` 에도 걸린다.
        # 따옴표까지 붙여 **버튼 클래스만** 찾는다.
        for cls, closer in (('aot-ov-desc-edit">', 'aot-ov-desc-editwrap'),
                            ('aot-ov-plot-edit">', 'aot-ov-plot-edit-wrap'),
                            ('aot-ov-plot-stage-undo">', 'aot-ov-row')):
            i = js.index(cls)
            head = js[max(0, i - 300):i]
            self.assertIn('aot-ov-actions', head,
                          cls + ' 가 행동 줄 밖에 있다')
            line = js[js.rindex('\n', 0, i) + 1:js.index('\n', i)]
            self.assertIn('aot-ov-pill', line, cls + ' 가 공용 알약 버튼이 아니다')
            self.assertLess(js.index(closer), i,
                            cls + ' 가 보기·폼보다 위에 있다')

    def test_wiring_hides_the_row_not_just_the_button(self):
        """버튼만 숨기면 빈 행이 남아 편집 중에만 블록 아래가 벌어진다."""
        vec = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js', 'widgets',
                                 'AoT_map', 'aot-map-widget-vector.js'))
        plot = _read(os.path.join(_ROOT, 'aot_flask', 'static', 'js', 'widgets',
                                  'AoT_map', 'aot-map-plot.js'))
        self.assertIn("descEditRow.style.display", vec)
        self.assertNotIn("descEdit.style.display", vec)
        self.assertIn("editRow.style.display", plot)
        self.assertNotIn("btnEdit.style.display", plot)


    def test_form_footers_put_cancel_before_save(self):
        """폼 푸터는 **오른쪽 끝이 기본 동작**이다 — [취소] [저장] 순.

        설명 편집만 거꾸로였다(저장·취소). 같은 모달 안에서 구획 편집·구획
        생성은 취소·저장이라, 같은 자리에 손이 가면 한 창에서는 저장되고
        다른 창에서는 취소된다.
        """
        js = _read(_POPUP)
        seen = 0
        for m in re.finditer(r'aot-ov-desc-actions', js):
            seg = js[m.end():m.end() + 1200].split("'</div>", 1)[0]
            if "_t('Save')" not in seg or "_t('Cancel')" not in seg:
                continue      # 확인/날짜만 있는 푸터
            seen += 1
            self.assertLess(seg.index("_t('Cancel')"), seg.index("_t('Save')"),
                            '저장이 취소보다 앞에 있다: ' + seg[:120])
        self.assertGreaterEqual(seen, 2, '검사한 폼 푸터가 너무 적다')

    def test_form_footers_use_the_same_component(self):
        """폼 푸터도 `.aot-ov-pill` 하나로. 예전에는 설명 폼만 `.aot-ov-pill`,
        구획 폼·단계 확인은 `.aot-pill-btn` 이라 같은 모달을 위아래로 훑으면
        버튼 높이가 두 종류였다. 기본 동작 하나만 `--primary` 로 강조한다."""
        js = _read(_POPUP)
        for m in re.finditer(r'aot-ov-desc-actions', js):
            seg = js[m.end():m.end() + 1200].split("'</div>", 1)[0]
            self.assertNotIn('aot-pill-btn', seg,
                             '폼 푸터가 다른 컴포넌트를 쓴다: ' + seg[:120])
            n = seg.count('aot-ov-pill--primary')
            self.assertLessEqual(n, 1,
                                 '기본 동작이 둘 이상 강조돼 있다: ' + seg[:120])

    def test_modal_footer_highlights_only_the_default_action(self):
        """모달 푸터도 같은 규칙 — 오른쪽 끝이 기본 동작이고 강조는 그 하나뿐.

        예약 모달은 [닫기]까지 primary 라 딥그린이 둘이었다. 같은 골격을 쓰는
        geo/design 구획 모달은 이미 취소=평범·저장=primary 다.
        """
        for path in (_POPUP,
                     os.path.join(_ROOT, 'aot_flask', 'static', 'js', 'geo',
                                  'design', 'aot-geo-plot.js')):
            js = _read(path)
            for m in re.finditer(r'class="modal-footer"', js):
                seg = js[m.end():m.end() + 900].split('</div>', 1)[0]
                self.assertLessEqual(
                    seg.count('aot-pill-btn-primary'), 1,
                    '푸터에 기본 동작이 둘 이상 강조돼 있다: ' + path)

    def test_end_plot_is_kept_away_from_save(self):
        """작기 종료는 되돌릴 수 없다 — [저장] 바로 옆에 두지 않는다."""
        js = _read(_POPUP)
        i_end = js.index('aot-ov-plot-end')
        i_save = js.index('aot-ov-plot-save')
        self.assertLess(i_end, i_save, '종료가 저장 뒤에 있다')
        line = js[js.rindex('\n', 0, i_end) + 1:i_end + 40]
        self.assertIn('aot-ov-pill--apart', js[i_end - 200:i_end],
                      '종료 버튼이 기본 동작에서 떨어져 있지 않다: ' + line)
        css = _read(self._CSS)
        apart = css.split('.aot-ov-pill--apart {', 1)[1].split('}', 1)[0]
        self.assertIn('margin-right: auto', apart)


if __name__ == '__main__':
    unittest.main()


class TestSentenceRowsDoNotSplitTheirLabel(unittest.TestCase):
    """문장을 값으로 갖는 줄은 이름 칸이 쪼개지면 안 된다.

    `.aot-ov-row` 는 flex 라 좁아지면 **양쪽을 함께** 줄인다. 값이 숫자면 줄
    것이 없어 이름은 멀쩡한데, 값이 문장이면 이름까지 눌려 낱말 한가운데가
    갈라진다. 실측(300px 폭): 이름 칸이 36px·2줄이 되어 "못 따라감" 이
    "못 따 / 라감" 으로 보였다. 규칙을 넣은 뒤 63px·1줄이다.
    """

    _CSS = os.path.join(_ROOT, 'aot_flask', 'static', 'css', 'widget',
                        'aot-sensor-label.css')

    def test_sentence_rows_keep_their_label_on_one_line(self):
        css = _read(self._CSS)
        # 이름은 줄이지 않는다.
        block = css.split('.aot-ov-strain,', 1)[1].split('\n}', 3)
        self.assertIn('flex-wrap: wrap', block[0])
        self.assertIn('white-space: nowrap', block[1])
        # 문장은 자리가 모자라면 자기 줄로 내려간다(basis 아래로 눌리면 wrap).
        self.assertIn('flex: 1 1 14em', block[2])

    def test_every_sentence_row_class_is_covered(self):
        """값이 **문장**인 줄을 새로 만들면 이 명부에도 넣을 것.

        빠뜨리면 증상이 조용하다 — 넓은 화면에서는 멀쩡하고, 좁은 폭에서만
        낱말이 갈라진다. 자동 판정은 두지 않는다: "이 값이 문장인가" 는
        마크업이 말해 주지 않고 사람이 아는 것이다.
        """
        css = _read(self._CSS)
        popup = _read(_POPUP)
        for cls in ('aot-ov-strain', 'aot-ov-gate', 'aot-hz'):
            self.assertIn(cls, popup, '%s 를 쓰는 자리가 사라졌다' % cls)
            self.assertIn('.%s > span:first-child' % cls, css,
                          '%s 가 문장 줄 규칙 명부에 없다' % cls)
