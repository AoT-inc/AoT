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
_VIZ_CSS = os.path.join(_ROOT, 'aot_flask', 'static', 'css', 'components',
                        'aot-dataviz.css')


def _read(path):
    with open(path, encoding='utf-8') as fh:
        return fh.read()


def _js_map(name):
    """`var <name> = { a: 'A', ... };` → dict."""
    src = _read(_POPUP)
    body = src.split('var %s = {' % name, 1)[1].split('};', 1)[0]
    return dict(re.findall(r"(\w+)\s*:\s*'([^']*)'", body))


def _po_entries(po):
    """`.po` 를 훑어 (msgid, msgstr) 를 낸다 — **접힌 여러 줄을 이어 붙인다.**

    표준 라이브러리만 쓴다. fuzzy 는 건너뛴다(사람이 확인하지 않은 추측이라
    화면에 나가지 않는다 — `check_po_mo_sync.py` 와 같은 판단).
    """
    import re as _re
    out = []
    cur, key, fuzzy = {'msgid': [], 'msgstr': []}, None, False

    def flush():
        if key and cur['msgid'] and not fuzzy:
            mid, msg = ''.join(cur['msgid']), ''.join(cur['msgstr'])
            if mid and msg:
                out.append((mid, msg))

    for line in po.split('\n'):
        t = line.strip()
        if t.startswith('#'):
            if t.startswith('#,') and 'fuzzy' in t:
                fuzzy = True
            continue
        if not t:
            flush()
            cur, key, fuzzy = {'msgid': [], 'msgstr': []}, None, False
            continue
        m = _re.match(r'(msgid|msgstr)(?:\[\d+\])?\s+"(.*)"$', t)
        if m:
            key = 'msgid' if m.group(1) == 'msgid' else 'msgstr'
            cur[key].append(m.group(2))
            continue
        m = _re.match(r'"(.*)"$', t)
        if m and key:
            cur[key].append(m.group(1))
    flush()
    return out


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


def _env_row_builder():
    """[현황] 환경 한 줄을 만드는 **구간 전체**(`envRowSpec` + `_envNowRowHtml`).

    ⚠ 한 함수만 잘라 보면 안 된다. 이 빌더는 2026-09 에 둘로 갈렸고(축·목표를
    정하는 `envRowSpec` 과 그것을 그리는 `_envNowRowHtml`), 그때부터 아래 두
    검사가 **규칙이 깨져서가 아니라 코드가 옮겨져서** 빨간불이었다. 규칙은
    "이 줄이 목표를 값 옆에 세우고 축을 밴드 표에서 얻는가" 이지 "그 문장이 어느
    함수 안에 있는가" 가 아니다.
    """
    src = _read(_POPUP)
    start = src.index('function envRowSpec(')
    # 끝은 `_envNowRowHtml` **다음**의 최상위 함수다(들여쓰기 2칸 = IIFE 최상위).
    end = src.index('\n  function ', src.index('function _envNowRowHtml('))
    return src[start:end]


class TestOverviewReadsServerFields(unittest.TestCase):
    """서버가 보내는 키를 화면이 실제로 읽는지 — 이름이 갈리면 그 값은 영영
    안 뜨는데 에러는 나지 않는다."""

    def test_photosynthesis_title_carries_no_crop_name(self):
        """제목에 작물·구획 이름을 붙이지 않는다 (2026-08-26).

        그 이름은 [구획] 카드가 이미 말하고, 사용자가 지은 **데이터**라
        번역되지 않는다 — 한국어 화면에 "광합성 · クサイチゴ" 처럼 다른
        언어가 섞여 보였다.
        """
        src = _read(_POPUP)
        self.assertNotIn('ph.crop || ph.subject', src,
                         '작물명을 제목에 다시 붙이고 있다')

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
        body = _env_row_builder()
        self.assertIn('opts.targets', body)
        self.assertIn('_NOW_TO_TARGET', body)
        # 목표는 **위치**로 말한다 — 값만 적고 자리를 안 주면 축 위 어디를
        # 가리키는지 알 수 없다. 이름 앞의 한정자(`s.`)는 보지 않는다 — 그것을
        # 박아 두면 함수를 가를 때마다 규칙이 아니라 표기가 깨진다.
        self.assertRegex(body, r'at:\s*(?:\w+\.)?anchorAt')

    def test_env_axis_comes_from_the_band_table(self):
        """축과 적정 구간은 **밴드 색과 같은 표**에서 온다.

        화면이 범위를 따로 들면 라벨 색과 축이 갈린다. 단위 환산(bandValue)도
        같이 써야 Pa 로 저장된 VPD 의 마커가 제자리에 선다.
        """
        body = _env_row_builder()
        self.assertIn('bandScale', body)
        self.assertIn('bandValue', body)
        # 축을 모르는 지표는 **지어내지 않는다** — 머리줄만 낸다.
        self.assertIn('V.value(', body)

    def test_control_status_is_problem_signals_only(self):
        """[현황]의 '제어 상태' 는 **문제 신호만** 낸다 (2026-08-26).

        예전에는 여기에 '장치별 개도'(`outputs_by_kind` = 종류별 **평균**)가
        함께 있었는데, [시설 세부]의 장치별 카드와 **같은 그림**이라 사용자가
        무엇이 다른지 알 수 없었다. 게다가 평균이라 측창 우 100% · 천창 0% 가
        "개구부 50%" 한 줄로 뭉쳐 아무것도 말하지 않았다.

        남는 것은 못 따라감과 안전 게이트뿐이고, 둘 다 없으면 카드가 나오지
        않는다 — 이상이 없다는 것을 한 줄로 적어 봐야 판단은 바뀌지 않는다.
        """
        body = _read(_POPUP).split("_t('Control Status')", 1)[1].split(
            '\n  function ', 1)[0]
        # 못 따라감은 **문장 자체**로 말한다 — 두 칸이던 시절의 '못 따라감'
        # 이름 칸은 뒤 문장과 같은 말을 두 번 하게 돼 걷어냈다(2026-08-26).
        self.assertIn("is off target and there is no device here", body)
        self.assertIn("_t('Safety Gate')", body)
        self.assertNotIn("_t('Device opening')", body,
                         '종류별 평균 목록이 되살아났다 — [시설 세부]와 겹친다')
        self.assertNotIn('outputs_by_kind', body)
        # 카드를 감추는 판정은 제목보다 **앞**에서 나므로 함수 전체에서 본다.
        fn = _read(_POPUP).split('function buildOverviewSection', 1)[1].split(
            '\n  function ', 1)[0]
        self.assertIn('_hasCtrl', fn, '문제가 없을 때 카드를 감추지 않는다')

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
        없다.

        2026-08-26: 광합성 줄은 [환경] 카드로 들어갔다(`buildEnvNowHtml`).
        그 줄들도 전부 "지금 값 / 목표" 라 [환경]과 같은 질문에 답하는데
        카드만 갈라져 있었다.
        """
        src = _read(_POPUP)
        body = src.split('function buildEnvNowHtml', 1)[1].split(
            '\n  function ', 1)[0]
        self.assertIn('if (_ph.enabled && _V) {', body)
        # ⚠ 손수 만든 `.aot-ov-row` 가 아니라 **공용 프리미티브**여야 한다
        # (components/aot-dataviz.css 규약) — 축이 있으면 band, 없으면 value.
        # 손수 짜면 같은 카드 안에서 글자 크기·간격·구분선이 위 측정줄과 갈린다.
        self.assertIn('_V.band(', body)
        self.assertIn('_V.value(', body)
        # 여는 태그로만 본다 — `aot-ov-card-title--row`(제목 클래스)와
        # 규약을 설명하는 주석 문구까지 걸리면 검사가 제 뜻을 잃는다.
        self.assertNotIn('<div class="aot-ov-row"', body,
                         '카드 안에서 공용 줄 대신 자체 마크업을 쓰고 있다')
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
        i_ctrl = body.index('buildOverviewSection')
        self.assertLess(i_hz, i_plots, '날씨(지역)가 구획(시설)보다 뒤에 있다')
        self.assertLess(i_plots, i_now, '위치·시간 층이 데이터 층보다 뒤에 있다')
        self.assertLess(i_now, i_ctrl, '데이터 층이 제어 층보다 뒤에 있다')
        # ⚠ **관수 카드의 자리는 여기서 정하지 않는다.** 한때 이 검사가
        #   "[현황]에 있으면 안 된다" 를 주장했는데(제어 정보니까 [시설 세부]
        #   라는 판단), 그 이동이 연동 안 된 시설에서 관수 상태를 통째로
        #   없앤다는 것이 나중에 드러났다. 계약은
        #   `test_irrigation_status.py` 하나가 갖는다 — 같은 사실을 두 곳이
        #   주장하면 되돌릴 때 한쪽만 고쳐져 서로 반대를 말하게 된다
        #   (2026-08-26 실제로 그 상태가 됐다).
        i_irr = body.index('buildIrrigationHtml')
        self.assertLess(i_now, i_irr, '데이터 층이 제어 층보다 뒤에 있다')
        self.assertLess(i_irr, i_ctrl, '직전에 한 일이 지금 하는 일보다 뒤에 있다')
        # 마지막 작동은 **그 장치 트랙 바로 아래**다(2026-08-26 재배치).
        # 한 줄로 맨 위에 두면 어느 장치 이야기인지 이름으로 이어붙여야 했다.
        detail = _read(_POPUP).split(
            'function buildFacilityDetailSection', 1)[1].split(
            '\n  function ', 1)[0]
        # 근거는 **모든 장치**가 갖는 `/runtime` 의 last_run_at 이다. 예전에는
        # 관수 payload(`opts.irrigation`) 하나만 보고 이름이 맞는 한 대에만
        # 붙였는데, 같은 목록의 나머지는 그 칸이 비어 "왜 이것만 나오나" 가
        # 됐다(2026-08-26 지적). 쉬는 장치일수록 이 값이 필요하다.
        self.assertIn('lv.last_run_at', detail,
                      '[시설 세부]가 장치별 마지막 작동을 말하지 않는다')
        self.assertNotIn('opts.irrigation', detail,
                         '관수 한 대만 특별대우하던 경로가 되돌아왔다')
        # 마지막 작동은 그 장치 줄의 **3행 왼쪽**이다 — 별도 줄로 내면 장치
        # 하나가 두 줄을 차지해 목록이 늘어진다(2026-08-26 재배치).
        # ⚠ `scaleNote`(오른쪽)가 아니다. 거기는 면적 몫이고, 마지막 작동은
        #   왼쪽 정렬이라야 다른 줄의 3행과 시작점이 맞는다.
        # ⚠⚠ **`scale` 배열도 아니다.** 그것은 *축의 눈금*이라, 목표가 0%/100%
        #   인 줄에서는 그쪽 끝 항목을 CSS 가 감춘다(is-anchor-start/end) —
        #   창이 다 열린 동안에만 '마지막 작동' 이 사라졌다(2026-08-26).
        self.assertIn("left.push(_t('Last run')", detail,
                      '마지막 작동이 3행 왼쪽이 아니다')
        self.assertIn('scaleLead: lead', detail,
                      '마지막 작동이 축 눈금 자리로 되돌아갔다 — 그 자리는 '
                      '목표가 축 끝에 붙는 줄에서 감춰진다')

    def test_onoff_devices_are_measured_on_the_time_axis(self):
        """on/off 장치의 "얼마나" 는 **지난 24시간 가동률**이지 지금의 0/100 이
        아니다.

        예전에는 켜진 장치를 100%, 꺼진 장치를 0% 로 놓고 평균을 내 '가동 출력'
        막대를 그렸다 — 난방기 하나가 켜진 상태가 "33%" 로 나와, 셋이 3분의
        1씩 돌고 있다는 뜻으로 읽혔다(2026-08-26 지적). 그런 일은 일어나지
        않는다: 그 장치에는 중간값이 없다.
        """
        detail = _read(_POPUP).split(
            'function buildFacilityDetailSection', 1)[1].split(
            '\n  function ', 1)[0]
        self.assertIn("lv.control_type === 'binary'", detail,
                      '장치 종류를 가리지 않고 한 축으로 그리고 있다')
        self.assertIn('duty_24h_s', detail, '가동률(시간축)을 읽지 않는다')
        # ⚠ 골격은 다른 줄과 **똑같다** — 축만 바뀌고 자리는 그대로다.
        #   3행 오른쪽은 언제나 「지금 값 / 전체」이고(개구부의 면적과 같은
        #   자리), 왼쪽은 마지막 작동이다. 작동 시간을 왼쪽에 몰아넣었더니
        #   오른쪽이 비어 그 줄만 다른 규칙으로 섰다(2026-08-26 지적).
        self.assertIn('scaleNote: rightNote', detail,
                      '3행 오른쪽이 「지금 값 / 축의 끝」 자리가 아니다')
        self.assertIn('_dutyOf(', detail)
        self.assertNotIn("h of the last 24 h", detail,
                         '작동 시간이 3행 왼쪽으로 되돌아갔다')
        # 집계 막대는 **같은 단위로 더해지는 무리**에만 — 환기는 m² 로 더해지고
        # 냉난방·가습은 공통 단위가 없다.
        self.assertNotIn("_t('Output in use')", detail,
                         '뜻 없는 평균 막대가 되살아났다')
        self.assertNotIn('_hvacRows', detail)

    def test_run_time_is_compared_against_the_device_own_history(self):
        """작동 시간에는 **견줄 기준**이 있어야 한다 (2026-08-26).

        "24시간 중 0.6시간" 은 아무 말도 하지 않는다 — 난방기의 하루 0.6시간은
        여름이면 흔한 일이고 겨울이면 고장 신호다. 24시간은 비교 기준이 아니라
        그냥 하루의 길이다. 기준은 그 장치 자신의 최근 실적(7일 일평균·최대)
        에서 온다.

        기록이 모자라면 **막대를 그리지 않는다** — 없는 축을 지어내면 바로 그
        24시간짜리 거짓말로 되돌아간다.
        """
        js = _read(_POPUP)
        fn = js.split('function _dutyOf', 1)[1].split('\n    function ', 1)[0]
        self.assertIn('duty_avg_s', fn, '평소(일평균) 기준을 읽지 않는다')
        self.assertIn('hasBase', fn)
        self.assertIn('Math.ceil(Math.max(avgH, h))', fn,
                      '축의 끝은 기준을 올림한 시간이어야 한다 — 눈금이 딱 '
                      '떨어져야 길이를 어림할 수 있고, 오늘이 기준을 넘으면 '
                      '축도 따라 올라가야 세로선이 축을 안 뚫는다')
        detail = js.split('function buildFacilityDetailSection', 1)[1].split(
            '\n  function ', 1)[0]
        self.assertIn('(duty && duty.hasBase) ? duty.h : null', detail,
                      '기준 없이 값을 그리고 있다')
        # ⚠ **밴드다, 불릿이 아니다.** 이 모달의 환경 줄이 전부 밴드라 사용자는
        #   초록을 "기준 구간", 세로선을 "지금" 으로 읽는다. 불릿(막대=값,
        #   눈금=목표)으로 그렸더니 정확히 반대로 읽혔다(2026-08-26 지적).
        self.assertIn('V.band({ label: label', detail,
                      'on/off 줄이 불릿으로 되돌아갔다 — 초록과 세로선의 뜻이 '
                      '같은 화면의 환경 줄과 반대가 된다')
        # 초록은 **왼쪽 끝부터 평소까지** 채운 길이다 — 그 길이가 기준이고,
        # 세로선이 그보다 왼쪽이면 평소보다 덜 돌았다.
        self.assertIn('okMin: (duty && duty.hasBase) ? 0 : undefined', detail)
        self.assertIn('okMax: (duty && duty.hasBase) ? duty.avgH', detail)
        # ⚠ 이 줄이 답하는 것은 "얼마나 일했나" 다. 1행만 순간 상태(켜짐/꺼짐)
        #   를 말하면 값과 축이 서로 다른 것을 가리킨다(2026-08-26 지적).
        self.assertIn("valueText: (duty ? duty.h.toFixed(1)", detail,
                      '1행 값이 오늘 누적 시간이 아니다')

    def test_baseline_excludes_the_day_in_progress(self):
        """아직 안 끝난 하루를 지난 날들과 같은 무게로 섞으면 기준이 아침마다
        낮아진다 — 그러면 "평소보다 많다" 가 오후에 저절로 참이 된다."""
        src = _read(os.path.join(_ROOT, 'aot_flask', 'routes_geo.py'))
        self.assertIn('daily[:-1]', src, '진행 중인 하루가 기준에 섞여 있다')
        self.assertIn('len(past) >= 2', src,
                      '하루치로 "평소" 를 만들고 있다')

    def test_duty_cycle_is_served_only_for_onoff_devices(self):
        """비례 장치(개도·PWM)는 지금 개도가 이미 "얼마나" 다 — 거기까지 이력을
        캐면 폴링마다 조회만 늘어난다."""
        src = _read(os.path.join(_ROOT, 'aot_flask', 'routes_geo.py'))
        self.assertIn("_history_cached(uuid, ctrl_type == 'binary')", src)
        self.assertIn("'duty_24h_s'", src)
        # 기준도 서버가 만든다 — 화면이 축을 지어내지 않도록.
        self.assertIn("'duty_avg_s'", src)

    def test_problem_sentences_use_one_shared_style(self):
        """못 따라감·안전 게이트는 **문장**이지 「이름 | 값」이 아니다.

        `.aot-ov-row` 의 오른쪽 칸에 넣었더니 우측 정렬로 들쭉날쭉 접혔다 —
        "수분(VPD)가 목표를 벗어났는데 이를 / 움직일 장치가 없습니다"
        (2026-08-26 영양 지적). [시설 세부]의 설명 문구와 **같은 성격의 글**
        이므로 같은 `.aot-ov-why` 를 쓴다. 화면마다 다른 모양으로 서면
        사용자는 둘이 다른 것인 줄 안다.
        """
        js = _read(_POPUP)
        for cls in ('aot-ov-strain', 'aot-ov-gate'):
            self.assertIn('aot-ov-why ' + cls, js,
                          '%s 가 공용 문장 스타일을 쓰지 않는다' % cls)
            self.assertNotIn('aot-ov-row ' + cls, js,
                             '%s 가 「이름 | 값」 두 칸으로 되돌아갔다' % cls)

    def test_every_strain_reason_has_a_message(self):
        """서버가 내는 못 따라감 근거는 **전부** 화면에 문장이 있어야 한다.

        `limit_breached`(선을 넘은 채 유지)를 추가하면서 그 분기를 안 만들면
        화면은 마지막 `else`(설비 한계) 문구를 대신 쓴다 — 제어 중심이 그
        방향을 요구하지도 않는데 "최대 출력인데 목표를 못 맞춘다" 는 거짓말이
        된다(2026-08-26).

        `saturated` 하나만 `else` 를 쓴다. 그 밖의 근거는 자기 분기를 가져야
        한다 — 새 근거가 조용히 남의 문구를 물려받지 않도록.
        """
        import re as _re
        src = _read(os.path.join(_ROOT, 'functions', 'custom_functions',
                                 'env_coordinator_impl', '_cycle_mixin.py'))
        block = src.split('def _assess_strain', 1)[1].split('\n    def ', 1)[0]
        # 근거는 두 모양으로 쓰인다: `'reason': 'x'` 와 조건식
        # `'reason': ('a' if … else 'b')`. 둘 다 걷는다.
        served = set(_re.findall(r"'reason':\s*'([a-z_]+)'", block))
        for a, b in _re.findall(
                r"'reason':\s*\('([a-z_]+)' if [^)]*else '([a-z_]+)'\)", block):
            served |= {a, b}
        self.assertIn('limit_breached', served, '새 근거가 서버에서 사라졌다')
        popup = _read(_POPUP)
        for r in sorted(served - {'saturated'}):
            self.assertIn("strain.reason === '%s'" % r, popup,
                          '못 따라감 근거 %r 에 자기 문장이 없다 — 다른 근거의 '
                          '문구가 대신 쓰인다' % r)
        # 마지막 else 가 설비 한계라는 것도 함께 고정한다.
        self.assertIn('at full output for %(min)s min', popup)

    def test_every_gate_reason_has_a_sentence(self):
        """안전 게이트 사유는 **전부** 화면에 문장이 있어야 한다 (2026-08-26).

        게이트가 걸리면 코디네이터는 L1~L3 앞에서 반환하므로 요약의 환경 값이
        갱신되지 않는다. 예전에는 화면이 그걸 "자동 제어가 응답하지 않습니다"
        로 읽어, 가장 알려야 할 순간에 정반대를 말했다 — 제어는 매 사이클 정상
        실행 중이고 이유도 분명한데(비·돌풍·폭염) 사용자는 고장으로 읽는다.
        게다가 **진짜로 죽었을 때와 구분되지 않았다**(실측: 강우 게이트 45분).

        표에 없는 사유가 오면 코드(`rain` 등)가 그대로 화면에 뜬다.
        """
        import re as _re
        src = _read(os.path.join(_ROOT, 'functions', 'utils', 'env_control',
                                 'safety_gates.py'))
        served = set(_re.findall(r"reasons\.append\('([a-z_]+)'\)", src))
        self.assertTrue(served, '게이트 사유를 하나도 못 찾았다 — 검사가 헛돈다')
        labels = _js_map('_GATE_REASON_TEXT')
        missing = sorted(served - set(labels))
        self.assertEqual([], missing,
                         '게이트 사유에 문장이 없다 — 내부 코드가 화면에 뜬다: %s'
                         % missing)

    def test_gate_stop_is_not_reported_as_no_response(self):
        """게이트로 멈춘 것과 죽은 것은 **다른 사실**이다."""
        js = _read(_POPUP)
        body = js.split('function buildOverviewSection', 1)[1].split(
            '\n  function ', 1)[0]
        self.assertIn('summary.gate_only', body,
                      '게이트 정지를 응답 없음과 구분하지 않는다')
        # 환경 값을 지금 값으로 읽지 않도록 함께 말한다.
        # ⚠ **위치를 가리키는 말('아래'·'위')을 쓰지 말 것.** 이 카드는 [환경]
        #   뒤에 오므로 '아래' 는 방향이 반대였고(2026-08-26 지적), 카드 순서는
        #   시설 구성에 따라 달라진다 — 위치를 가리키는 말은 언젠가 틀린다.
        self.assertIn('Environment readings were taken just before this.', body)
        self.assertNotIn('Readings below', js, '위치를 가리키는 문구가 남아 있다')
        # ⚠ **'게이트' 는 코드의 이름이지 사용자의 말이 아니다** (2026-08-26 지적).
        #   "게이트가 걸리다" 는 엔지니어만 알아듣는다. 영어 msgid 는 소스의
        #   어휘라 그대로 두더라도, **화면에 나가는 번역**에는 쓰지 않는다.
        for name in _js_map('_GATE_REASON_TEXT').values():
            self.assertNotIn('gate', name.lower(),
                             '사용자 문구에 내부 용어가 들어 있다: %r' % name)
        # 같은 안내를 [시설 세부]에 다시 얹지 않는다 — 그 탭에는 그 문장을
        # 뒷받침할 맥락이 없어 "설명 없이 놓인 문구" 로 읽힌다. 장치가 왜 그
        # 값인지는 각 카드의 근거(reason 12)가 말한다.
        detail = js.split('function buildFacilityDetailSection', 1)[1].split(
            '\n  function ', 1)[0]
        self.assertNotIn('_GATE_REASON_TEXT', detail,
                         '중요한 안내가 두 탭에서 두 번 나온다')
        # 서버가 그 표식을 실제로 싣는지도 함께 고정한다 — 한쪽만 있으면 조용하다.
        src = _read(os.path.join(_ROOT, 'functions', 'custom_functions',
                                 'env_coordinator_impl', '_cycle_mixin.py'))
        self.assertIn("'gate_only': True", src)
        self.assertIn('_write_gate_only_summary(gate_result', src,
                      '게이트 조기 종료 경로가 요약을 안 쓴다')

    def test_no_korean_string_says_gate(self):
        """한국어 화면에 '게이트' 가 나오면 안 된다 (2026-08-26 지적).

        엔지니어만 알아듣는 말이다. 실제로 "안전 게이트가 잡고 있습니다" 가
        시설 모달에 그대로 떠 있었다.

        ⚠ LoRaWAN **게이트웨이**와 502 Bad Gateway 는 다른 것이라 제외한다 —
          그쪽은 사용자도 그 이름으로 부르는 장비·프로토콜 용어다.

        ⚠ **한 줄짜리만 보면 안 된다.** `.po` 는 긴 문구를 여러 줄로 접으므로
          `msgid "..."\nmsgstr "..."` 로 훑으면 **긴 문구가 통째로 안 보인다** —
          그리고 내부 용어가 들어가기 쉬운 것은 짧은 라벨이 아니라 긴 설명이다.
          실제로 그 상태에서 '안전 게이트' 4건이 통과하고 있었다(2026-08-27).
          같은 맹점이 이 세션에서 중복 항목을 만든 적도 있다.
        """
        bad = []
        for mid, msg in _po_entries(_read(_KO)):
            if '게이트' not in msg:
                continue
            if '게이트웨이' in msg or 'Gateway' in mid or 'gateway' in mid:
                continue
            bad.append((mid[:60], msg[:60]))
        self.assertEqual([], bad, '한국어 화면 문구에 내부 용어: %s' % bad)

    def test_every_override_reason_has_a_label(self):
        """서버가 강제한 근거는 **전부** 화면에 문장이 있어야 한다 (2026-08-26).

        값과 근거가 서로 다른 시점을 가리키던 것을 고치면서, 이제 오버라이드가
        값을 바꾼 줄은 **그쪽 근거**(문자열)를 싣는다. 표에 없는 이름이 오면
        화면은 그 장치에 대해 아무 설명도 못 한다 — 그런데 오답이 아니라
        **침묵**이라 아무도 눈치채지 못한다.
        """
        import re as _re
        src = _read(os.path.join(_ROOT, 'functions', 'custom_functions',
                                 'env_coordinator_impl', '_cycle_mixin.py'))
        served = set(_re.findall(r"'reason':\s*'([a-z_]+)'", src))
        # 진단용(화면의 이 표를 안 지나간다)은 뺀다.
        served -= {'no_actuator', 'saturated'}
        labels = _js_map('_REASON_TEXT')
        missing = sorted(served - set(labels))
        self.assertEqual([], missing,
                         '강제 근거에 문장이 없다 — 그 장치만 조용해진다: %s'
                         % missing)

    def test_scale_annotations_are_not_hidden_as_axis_labels(self):
        """3행의 덧말(왼쪽 `lead` · 오른쪽 `note`)은 **축 라벨이 아니다.**

        `is-anchor-start/end` 는 "기준 라벨이 가리는 축 끝을 감춘다" 는 규칙인데,
        덧말까지 걸리면 **목표가 0%/100% 인 줄에서만** 그 글자가 사라진다 —
        창이 다 열린 동안에만 '마지막 작동' 이 안 보였다(2026-08-26). 조건이
        값에 달려 있어 한 번 보고 넘어가면 정상으로 읽힌다.
        """
        css = _read(_VIZ_CSS)
        for rule in ('.aot-viz-scale.is-anchor-start > span:first-child',
                     '.aot-viz-scale.is-anchor-end   > span:last-child'):
            i = css.index(rule)
            line = css[i:css.index('\n', i)]
            for keep in ('.aot-viz-scale-lead', '.aot-viz-scale-note'):
                self.assertIn(':not(' + keep + ')', line,
                              '덧말이 축 라벨로 취급돼 감춰진다: ' + rule)

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


class TestNoBareCallsToExportOnlyNames(unittest.TestCase):
    """모듈 내부 이름은 `_x`, 공개 이름은 `x` 다 — 내부에서 `x()` 를 부르면
    **ReferenceError** 다.

    2026-08-26 실제로 그랬다. [시설 세부] 탭이 코디네이터 없는 시설에서
    `emptyBlock(...)` 을 불렀는데(정의된 이름은 `_emptyBlock`), 그 자리는
    **코디네이터가 없을 때만** 지나는 이른 반환이라 연동된 시설에서는 멀쩡했다.

    던져진 예외는 `_render` 를 부르는 `.then()` 안에서 **처리되지 않은 거부**가
    되어 조용히 사라지고, 그 뒤 줄이 통째로 실행되지 않았다 — 현재환경·구획·
    기록·[개요] 렌더가 전부 그 아래에 있어서 **탭 세 개가 함께 비었다.**
    콘솔을 열지 않으면 원인이 어디에도 안 보인다.
    """

    def test_module_never_calls_an_export_only_name(self):
        import re
        src = _read(_POPUP)
        defined = set(re.findall(r'\n  function ([A-Za-z_$][\w$]*)\s*\(', src))
        defined |= set(re.findall(r'\n  var ([A-Za-z_$][\w$]*)\s*=', src))
        # 공개 객체가 `이름: _내부이름` 으로 내보내는 것들.
        exported = dict(re.findall(
            r'\n    ([A-Za-z_$][\w$]*):\s*(_[A-Za-z_$][\w$]*),', src))
        offenders = []
        for pub, priv in exported.items():
            if pub in defined:
                continue          # 같은 이름이 내부에도 있으면 안전하다
            for m in re.finditer(r'(?<![.\w$])' + re.escape(pub) + r'\s*\(', src):
                offenders.append('%d행: %s() → %s() 여야 한다'
                                 % (src[:m.start()].count('\n') + 1, pub, priv))
        self.assertEqual([], offenders, '\n'.join(offenders))



class TestSentenceRowsDoNotSplitTheirLabel(unittest.TestCase):
    """문장을 값으로 갖는 줄은 이름 칸이 쪼개지면 안 된다.

    `.aot-ov-row` 는 flex 라 좁아지면 **양쪽을 함께** 줄인다. 값이 숫자면 줄
    것이 없어 이름은 멀쩡한데, 값이 문장이면 이름까지 눌려 낱말 한가운데가
    갈라진다. 실측(300px 폭): 이름 칸이 36px·2줄이 되어 "못 따라감" 이
    "못 따 / 라감" 으로 보였다. 규칙을 넣은 뒤 63px·1줄이다.

    ⚠ **긴 문장은 이 문법을 아예 떠났다**(2026-08-26 영양 지적). 두 칸으로
      버티게 해도 오른쪽 칸이 우측 정렬로 들쭉날쭉 접힌다 — 못 따라감·안전
      게이트는 `.aot-ov-why` 한 문단으로 옮겼다. 여기 남는 것은 **값이 짧은**
      줄뿐이다(위험 칩 "강풍 · 오늘 21시").
    """

    _CSS = os.path.join(_ROOT, 'aot_flask', 'static', 'css', 'widget',
                        'aot-sensor-label.css')

    def test_sentence_rows_keep_their_label_on_one_line(self):
        css = _read(self._CSS)
        # 이름은 줄이지 않는다.
        block = css.split('.aot-hz {', 1)[1].split('\n}', 3)
        self.assertIn('flex-wrap: wrap', block[0])
        self.assertIn('white-space: nowrap', block[1])
        # 문장은 자리가 모자라면 자기 줄로 내려간다(basis 아래로 눌리면 wrap).
        self.assertIn('flex: 1 1 14em', block[2])

    def test_every_sentence_row_class_is_covered(self):
        """값이 **짧은 문장**인 줄을 새로 만들면 이 명부에도 넣을 것.

        빠뜨리면 증상이 조용하다 — 넓은 화면에서는 멀쩡하고, 좁은 폭에서만
        낱말이 갈라진다. 자동 판정은 두지 않는다: "이 값이 문장인가" 는
        마크업이 말해 주지 않고 사람이 아는 것이다.

        값이 **긴 문장**이면 이 명부가 아니라 `.aot-ov-why` 다.
        """
        css = _read(self._CSS)
        popup = _read(_POPUP)
        for cls in ('aot-hz',):
            self.assertIn(cls, popup, '%s 를 쓰는 자리가 사라졌다' % cls)
            self.assertIn('.%s > span:first-child' % cls, css,
                          '%s 가 문장 줄 규칙 명부에 없다' % cls)


class TestDetailDomainsMatchServer(unittest.TestCase):
    """[시설 세부]의 카드 구분은 **제어기의 도메인**과 같아야 한다.

    이 탭은 "왜 이렇게 하고 있나" 에 답하는 자리이고, 그 "왜" 의 경계가 곧
    부하분담 도메인이다 — 창끼리는 서로의 기여를 보고 조율하지만 공조는 그것을
    모른다(`types.ACTUATOR_DOMAIN`, 2026-08-26).

    갈리면 조용하다. 화면은 여전히 카드를 그리고 장치도 어딘가에 들어가지만,
    **설명하는 무리와 제어기가 실제로 묶는 무리가 달라진다** — 사용자는 같이
    움직일 것이라 기대한 장치들이 따로 노는 것을 보게 된다.
    """

    def _js_domains(self):
        """`var _catOrder = [...]` → {kind: domain_key}."""
        src = _read(_POPUP)
        body = src.split('var _catOrder = [', 1)[1].split('\n      ];', 1)[0]
        out = {}
        for key, kinds in re.findall(
                r"key:\s*'(\w+)'.*?kinds:\s*(\[[^\]]*\]|null)", body, re.S):
            if kinds == 'null':
                continue
            for k in re.findall(r"'(\w+)'", kinds):
                out[k] = key
        return out

    def test_kind_domain_assignment_matches(self):
        from aot.functions.utils.env_control.types import ACTUATOR_DOMAIN
        js = self._js_domains()
        for kind, dom in js.items():
            self.assertEqual(
                ACTUATOR_DOMAIN.get(kind), dom,
                "'%s' 이 화면에서는 '%s', 제어기에서는 '%s' 다" % (
                    kind, dom, ACTUATOR_DOMAIN.get(kind)))

    def test_every_load_sharing_domain_is_shown(self):
        """명부에 없는 도메인이 생기면 그 장치들이 'Other' 로 뭉친다."""
        from aot.functions.utils.env_control.types import ACTUATOR_DOMAIN
        js_doms = set(self._js_domains().values()) | {'aux'}
        missing = set(ACTUATOR_DOMAIN.values()) - js_doms
        self.assertFalse(
            missing, '화면에 없는 도메인: %s' % sorted(missing))



_WIDGET = os.path.join(_ROOT, 'aot_flask', 'static', 'js', 'widgets',
                       'AoT_map', 'aot-map-widget-vector.js')


class TestDetailTabHiddenWithoutCoordinator(unittest.TestCase):
    """[시설 세부] 탭은 **연동이 없으면 감춘다**.

    이 탭이 낼 것은 전부 env_coordinator 사이클에서 온다. 연동이 없으면
    "아직 설명할 제어 사이클이 없습니다" 한 줄만 남는데, 그것은 눌러 봐야
    알 수 있는 빈 방이다.

    판정 자체는 화면에서 확인했다. 여기서 지키는 것은 **판정의 근거와
    배선**이다 — 어느 쪽이 조용히 어긋나도 증상이 "탭이 이상하게 나온다"
    라서 원인에 닿기 어렵다.
    """

    def setUp(self):
        self.src = _read(_WIDGET)

    def test_the_call_lives_in_one_helper(self):
        # 두 자리(팝업 열기 · 응답 처리)가 각자 클래스를 만지면 한쪽만
        # 고쳐진 채 갈린다. 토글은 헬퍼 하나가 한다.
        self.assertEqual(
            1, self.src.count('function _applyDetailTabVisibility('),
            '[시설 세부] 표시 판정은 헬퍼 하나여야 한다')

    def test_both_paths_apply_it(self):
        # 응답 처리만 있으면 연동 없는 시설을 열 때마다 탭이 잠깐 보였다
        # 사라지고, 팝업 열기만 있으면 연동을 새로 붙여도 반영되지 않는다.
        self.assertGreaterEqual(
            self.src.count('_applyDetailTabVisibility('), 3,
            '정의 + 팝업 열기 + 응답 처리 = 최소 3회')

    def test_the_verdict_is_linkage_not_freshness(self):
        # stale 로 감추면 사이클이 한 번 늦을 때마다 탭이 사라졌다 나타나
        # 탭 목록이 흔들린다. env_summary 의 `function` 이 곧 연동 여부다.
        m = re.search(r'var _hasCoord = ([^;]+);', self.src)
        self.assertIsNotNone(m, '_hasCoord 판정을 찾지 못했다')
        expr = m.group(1)
        self.assertIn('.function', expr)
        self.assertNotIn('stale', expr,
                         '신선도로 감추면 탭 목록이 흔들린다')

    def test_hiding_an_open_tab_falls_back(self):
        # 저장된 popup_default_tab 이 'detail' 이면 감춘 탭이 열린 채
        # 시작한다 — 되돌리지 않으면 모달이 통째로 빈 화면이 된다.
        body = self.src.split('function _applyDetailTabVisibility(', 1)[1]
        body = body.split('\n        function ', 1)[0]
        self.assertIn('activateSection', body)
        self.assertIn("'overview'", body)


class TestBandAnchorIsAnAxisValue(unittest.TestCase):
    """`band()` 의 눈금 `at` 은 **축 위의 값**이지 백분율이 아니다.

    `band()` 는 `pct(it.at, o.min, o.max)` 로 환산한다. 백분율을 넘기면 그
    숫자가 다시 값으로 읽혀 라벨이 엉뚱한 자리에 선다 — 광량 줄이 실제로
    그랬다(구간 80~720 의 한가운데 20% 를 넘겼더니 축 0~2000 위의 값 20,
    즉 1% 자리에 붙어 카드 왼쪽 끝으로 갔다).

    **에러가 나지 않는다**는 것이 이 실수의 전부다. 두 수 모두 유효한
    숫자라 그림은 그려지고, 다른 줄과 나란히 놓고 봐야 어긋난 것이 보인다.
    """

    def test_no_anchor_at_is_computed_as_a_percentage(self):
        src = _read(_POPUP)
        bad = []
        for m in re.finditer(r'\bat:\s*([^,\n}]+)', src):
            expr = m.group(1)
            if '100' in expr:
                line = src.count('\n', 0, m.start()) + 1
                bad.append('%s:%d  at: %s' % (
                    os.path.basename(_POPUP), line, expr.strip()))
        self.assertEqual([], bad,
                         '눈금 at 은 축 위의 값이어야 한다(백분율 금지):\n'
                         + '\n'.join(bad))

class TestTheJsTranslationCatalogIsVersioned(unittest.TestCase):
    """`/api/v1/locale/js` 는 **버전 쿼리 없이 부르면 안 된다** (2026-08-27).

    그 응답은 `max-age=600` 이라, URL 이 그대로면 브라우저가 **10분 동안 옛
    카탈로그**를 쓴다. 번역을 추가하고 서버를 재시작해도 화면 일부만 영어로
    남고 **에러가 없어서** 원인이 어디에도 안 드러난다 — 실측으로 확인했다:
    서버 응답에는 새 문구가 있는데 화면에는 영어였다.

    같은 파일의 `user_strings.js` 는 처음부터 지문(`user_i18n_fingerprint`)을
    달고 있었다. 이쪽만 빠져 있었다.
    """

    def test_the_script_tag_carries_a_build_id(self):
        import os
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for name in ('layout_default.html', 'layout.html'):
            path = os.path.join(here, 'aot_flask', 'templates', name)
            with open(path, encoding='utf-8') as fh:
                src = fh.read()
            i = src.find('get_js_translations')
            self.assertNotEqual(i, -1, '%s 가 카탈로그를 안 부른다' % name)
            tag = src[i:src.find('>', i)]
            self.assertIn('static_build_id', tag,
                          '%s: 카탈로그 URL 에 버전이 없다 — 10분간 옛 번역이 '
                          '나간다' % name)


if __name__ == '__main__':
    unittest.main()
