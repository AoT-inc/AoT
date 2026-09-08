# coding=utf-8
import json

from flask_babel import lazy_gettext

from aot.aot_flask.extensions import db
from aot.databases.models import NoticePost, GeoShape, GeoFacility, GeoPlot
from aot.utils.constraints_pass import constraints_pass_positive_value


def _shape_display_name(shape):
    """People-readable label for a site/zone GeoShape row, mirroring the name
    lookup routes_notes_api._display_name_for_target() uses for notes — falls
    back to the unique_id only if the shape has no name/label/title."""
    try:
        feat = shape.feature if isinstance(shape.feature, dict) else json.loads(shape.feature or '{}')
        props = (feat.get('properties') or {})
        return props.get('name') or props.get('label') or props.get('title') or shape.unique_id
    except Exception:
        return shape.unique_id


def _available_spaces():
    """Site/zone/facility/plot entities notes can be scoped to, for the
    settings modal's space picker (widget_dashboard_configure_options). Each
    entry is (type, unique_id, name), grouped by type in the select markup."""
    spaces = []
    for sh in GeoShape.query.filter(GeoShape.type.in_(('site', 'zone'))).order_by(GeoShape.type).all():
        if sh.unique_id:
            spaces.append((sh.type, sh.unique_id, _shape_display_name(sh)))
    for fac in GeoFacility.query.all():
        if fac.unique_id:
            spaces.append(('facility', fac.unique_id, getattr(fac, 'name', None) or fac.unique_id))
    for pl in GeoPlot.query.filter(GeoPlot.ended_on.is_(None)).all():
        if pl.unique_id:
            spaces.append(('plot', pl.unique_id, pl.name or pl.subject or pl.unique_id))
    return spaces


def generate_page_variables(widget_unique_id, widget_options):
    """Per-instance choice lists for the settings modal
    (widget_dashboard_configure_options): distinct notice category labels
    currently in use, and every site/zone/facility/plot notes can be scoped to."""
    rows = db.session.query(NoticePost.category).filter(
        NoticePost.category.isnot(None), NoticePost.category != '').distinct().order_by(NoticePost.category).all()
    return {
        'available_categories': [r[0] for r in rows],
        'available_spaces': _available_spaces(),
    }


def execute_at_modification(mod_widget, request_form, custom_options_json_presave, custom_options_json_postsave):
    """Every notice/notes option except refresh_seconds is hand-rendered in
    widget_dashboard_configure_options rather than declared: declared
    custom_options render as one flat framework-owned list, and there's no
    way to nest a subset of them inside a specific group container (the
    Notices/Notes split the settings modal needs) or give one a proper
    multi-select control (the category filter). So all of them are captured
    here directly from the settings form instead, same pattern AoT_graph.py
    uses for its per-series checkboxes."""
    allow_saving = True
    page_refresh = False

    def _bool(name):
        return request_form.get(name) == 'y'

    def _int(name, default):
        try:
            return int(request_form.get(name, default))
        except (TypeError, ValueError):
            return default

    custom_options_json_postsave['show_notice'] = _bool('show_notice')
    custom_options_json_postsave['post_count'] = _int('post_count', 3)
    custom_options_json_postsave['show_poll'] = _bool('show_poll')
    custom_options_json_postsave['show_reply_box'] = _bool('show_reply_box')
    custom_options_json_postsave['categories'] = request_form.getlist('categories')

    custom_options_json_postsave['show_notes'] = _bool('show_notes')
    custom_options_json_postsave['notes_post_count'] = _int('notes_post_count', 5)
    custom_options_json_postsave['notes_include_descendants'] = _bool('notes_include_descendants')
    notes_sort = request_form.get('notes_sort', 'date')
    custom_options_json_postsave['notes_sort'] = notes_sort if notes_sort in ('date', 'priority', 'category') else 'date'
    custom_options_json_postsave['notes_category_filter'] = (request_form.get('notes_category_filter') or '').strip()

    # notes_target arrives as "type::unique_id" (or empty if unset) so the
    # type and id can never drift out of sync in the saved options.
    notes_target = (request_form.get('notes_target') or '').strip()
    if '::' in notes_target:
        target_type, target_id = notes_target.split('::', 1)
    else:
        target_type, target_id = '', ''
    custom_options_json_postsave['notes_target_type'] = target_type
    custom_options_json_postsave['notes_target_id'] = target_id

    return allow_saving, page_refresh, mod_widget, custom_options_json_postsave


WIDGET_INFORMATION = {
    'widget_name_unique': 'widget_notice',
    'widget_name': lazy_gettext('Notice & Notes Board'),
    'widget_library': '',
    'no_class': True,
    'mobile_full_width': True,  # Always takes the full row (single widget per line) on mobile.

    'message': lazy_gettext('Displays the latest notice board post titles and/or the notes written '
                'in a chosen site, zone, plot, or facility (and everything nested under it). '
                'Clicking a notice opens the full post (content, poll, replies, acknowledge) in a '
                'popup; clicking a note opens it in the shared notes panel. Users with write '
                'permission can also create, edit, and delete posts directly from the widget.'),

    'dependencies_module': [],

    'widget_width': 6,
    'widget_height': 8,

    'generate_page_variables': generate_page_variables,
    'execute_at_modification': execute_at_modification,

    'custom_options': [
        # No header before this one — it belongs with the framework's own
        # "기본 설정" (Name/Tab/Drag handle) group, same as any other widget's
        # refresh interval. (Reverted the 'General' header added earlier:
        # user confirmed refresh_seconds is a basic/system-level setting,
        # not something that needed separating out.)
        {
            'id': 'refresh_seconds',
            'type': 'integer',
            'default_value': 60,
            'constraints_pass': constraints_pass_positive_value,
            'name': lazy_gettext('Refresh (seconds)'),
            'phrase': lazy_gettext('How often to refresh the notice/notes lists')
        },
    ],

    # Everything below is hand-rendered rather than declared, so the Notices
    # and Notes options can each sit inside their own container (declared
    # custom_options render as one flat framework-owned list — there's no way
    # to nest a subset of them under a group) and the category filter can be
    # a proper multi-select instead of one toggle per category. Markup/CSS
    # classes are the same ones Custom_Options.html itself uses for these
    # option kinds (aot-modal-option-row/-label/-control, btn-toggle,
    # aot-modern-input/-select, selectpicker) so this looks identical to any
    # other widget's settings — see AoT_plot.py for the same modal-chrome
    # convention. Values are captured in execute_at_modification() (same
    # pattern AoT_graph.py uses for its per-series checkboxes).
    'widget_dashboard_configure_options': """
<div class="aot-modal-section-title">{{_('Notices')}}</div>
<div class="aot-modal-container">
  <div class="aot-modal-option-row">
    <label class="aot-modal-option-label" title="{{_('Display the notice board section')}}">{{_('Show Notices')}}<span class="fas fa-info-circle aot-option-tip" aria-hidden="true"></span></label>
    <div class="aot-modal-option-control">
      <label class="btn-toggle mb-0">
        <input id="show_notice" name="show_notice" type="checkbox" value="y" class="btn-toggle-input"{% if widget_options.get('show_notice', True) %} checked{% endif %}>
        <div class="btn-toggle-slider"><div class="btn-toggle-thumb"></div></div>
      </label>
    </div>
  </div>
  <div class="aot-modal-option-row" data-depends-on="show_notice">
    <label class="aot-modal-option-label" title="{{_('How many of the latest notices to display')}}">{{_('Number of Notices')}}<span class="fas fa-info-circle aot-option-tip" aria-hidden="true"></span></label>
    <div class="aot-modal-option-control">
      <input class="form-control aot-modern-input" id="post_count" name="post_count" type="number" value="{{ widget_options.get('post_count', 3) }}">
    </div>
  </div>
  <div class="aot-modal-option-row" data-depends-on="show_notice">
    <label class="aot-modal-option-label" title="{{_('Allow voting on polls from the post popup')}}">{{_('Show Poll Voting')}}<span class="fas fa-info-circle aot-option-tip" aria-hidden="true"></span></label>
    <div class="aot-modal-option-control">
      <label class="btn-toggle mb-0">
        <input id="show_poll" name="show_poll" type="checkbox" value="y" class="btn-toggle-input"{% if widget_options.get('show_poll', True) %} checked{% endif %}>
        <div class="btn-toggle-slider"><div class="btn-toggle-thumb"></div></div>
      </label>
    </div>
  </div>
  <div class="aot-modal-option-row" data-depends-on="show_notice">
    <label class="aot-modal-option-label" title="{{_('Allow sending a reply from the post popup')}}">{{_('Show Reply Box')}}<span class="fas fa-info-circle aot-option-tip" aria-hidden="true"></span></label>
    <div class="aot-modal-option-control">
      <label class="btn-toggle mb-0">
        <input id="show_reply_box" name="show_reply_box" type="checkbox" value="y" class="btn-toggle-input"{% if widget_options.get('show_reply_box', True) %} checked{% endif %}>
        <div class="btn-toggle-slider"><div class="btn-toggle-thumb"></div></div>
      </label>
    </div>
  </div>
  <div class="aot-modal-option-row" data-depends-on="show_notice">
    <label class="aot-modal-option-label" title="{{_('Only show posts in the selected categories. If none are selected, posts of every category are shown.')}}">{{_('Category Filter')}}<span class="fas fa-info-circle aot-option-tip" aria-hidden="true"></span></label>
    <div class="aot-modal-option-control">
      {% if widget_variables.get('available_categories') %}
      <select class="form-control aot-modern-select selectpicker" id="categories" name="categories" title="{{_('Select')}}" multiple data-size="auto" data-selected-text-format="static" data-style="btn-white" data-container="body">
        {% for cat in widget_variables.get('available_categories', []) %}
        <option value="{{cat}}"{% if cat in widget_options.get('categories', []) %} selected{% endif %}>{{cat}}</option>
        {% endfor %}
      </select>
      {% else %}
      <div class="text-muted small">{{_('No categories yet. Set one when creating a post to filter by it here.')}}</div>
      {% endif %}
    </div>
  </div>
</div>

<div class="aot-modal-section-title">{{_('Notes')}}</div>
<div class="aot-modal-container">
  <div class="aot-modal-option-row">
    <label class="aot-modal-option-label" title="{{_('Display notes matching the filter below')}}">{{_('Show Notes List')}}<span class="fas fa-info-circle aot-option-tip" aria-hidden="true"></span></label>
    <div class="aot-modal-option-control">
      <label class="btn-toggle mb-0">
        <input id="show_notes" name="show_notes" type="checkbox" value="y" class="btn-toggle-input"{% if widget_options.get('show_notes', False) %} checked{% endif %}>
        <div class="btn-toggle-slider"><div class="btn-toggle-thumb"></div></div>
      </label>
    </div>
  </div>
  <div class="aot-modal-option-row" data-depends-on="show_notes">
    <label class="aot-modal-option-label" title="{{_('How many of the latest notes to display')}}">{{_('Number of Notes')}}<span class="fas fa-info-circle aot-option-tip" aria-hidden="true"></span></label>
    <div class="aot-modal-option-control">
      <input class="form-control aot-modern-input" id="notes_post_count" name="notes_post_count" type="number" value="{{ widget_options.get('notes_post_count', 5) }}">
    </div>
  </div>
  <div class="aot-modal-option-row" data-depends-on="show_notes">
    <label class="aot-modal-option-label" title="{{_('Also show notes written in zones/plots/facilities/devices nested under the chosen space')}}">{{_('Include Nested Spaces')}}<span class="fas fa-info-circle aot-option-tip" aria-hidden="true"></span></label>
    <div class="aot-modal-option-control">
      <label class="btn-toggle mb-0">
        <input id="notes_include_descendants" name="notes_include_descendants" type="checkbox" value="y" class="btn-toggle-input"{% if widget_options.get('notes_include_descendants', True) %} checked{% endif %}>
        <div class="btn-toggle-slider"><div class="btn-toggle-thumb"></div></div>
      </label>
    </div>
  </div>
  <div class="aot-modal-option-row" data-depends-on="show_notes">
    <label class="aot-modal-option-label" title="{{_('How to order the note list')}}">{{_('Sort Notes By')}}<span class="fas fa-info-circle aot-option-tip" aria-hidden="true"></span></label>
    <div class="aot-modal-option-control">
      {% set notes_sort_current = widget_options.get('notes_sort', 'date') %}
      <select class="form-control aot-modern-select" id="notes_sort" name="notes_sort">
        <option value="date"{% if notes_sort_current == 'date' %} selected{% endif %}>{{_('Newest First')}}</option>
        <option value="priority"{% if notes_sort_current == 'priority' %} selected{% endif %}>{{_('Priority')}}</option>
        <option value="category"{% if notes_sort_current == 'category' %} selected{% endif %}>{{_('Category')}}</option>
      </select>
    </div>
  </div>
  <div class="aot-modal-option-row" data-depends-on="show_notes">
    <label class="aot-modal-option-label" title="{{_('Only show notes whose category or tags contain this text (optional)')}}">{{_('Note Category/Tag Contains')}}<span class="fas fa-info-circle aot-option-tip" aria-hidden="true"></span></label>
    <div class="aot-modal-option-control">
      <input class="form-control aot-modern-input" id="notes_category_filter" name="notes_category_filter" type="text" value="{{ widget_options.get('notes_category_filter', '') }}">
    </div>
  </div>
  <div class="aot-modal-option-row" data-depends-on="show_notes">
    <label class="aot-modal-option-label" title="{{_('Notes written in this site/zone/plot/facility (and, if "Include Nested Spaces" above is on, everything nested under it) are shown.')}}">{{_('Notes Filter')}}<span class="fas fa-info-circle aot-option-tip" aria-hidden="true"></span></label>
    <div class="aot-modal-option-control">
      {% if widget_variables.get('available_spaces') %}
      <select class="form-control aot-modern-select selectpicker" id="notes_target" name="notes_target" data-live-search="true" data-size="8" data-container="body" data-style="btn-white" aria-label="{{_('Notes Filter')}}">
        <option value="">{{_('None selected')}}</option>
        {% set current = widget_options.get('notes_target_type', '') ~ '::' ~ widget_options.get('notes_target_id', '') %}
        {% for space_type, space_id, space_name in widget_variables.get('available_spaces', []) %}
        <option value="{{space_type}}::{{space_id}}"{% if (space_type ~ '::' ~ space_id) == current %} selected{% endif %}>{%- if space_type == 'site' %}{{_('Site')}}{% elif space_type == 'zone' %}{{_('Zone')}}{% elif space_type == 'facility' %}{{_('Facility')}}{% else %}{{_('Plot')}}{% endif %}: {{space_name}}</option>
        {% endfor %}
      </select>
      {% else %}
      <div class="text-muted small">{{_('No sites, zones, plots, or facilities exist yet.')}}</div>
      {% endif %}
    </div>
  </div>
</div>""",

    'widget_dashboard_head': """{% if "aot_notice_render" not in dashboard_dict %}
  <script src="{{ asset('app-notice-render') }}"></script>
  {% set _dummy = dashboard_dict.update({"aot_notice_render": 1}) %}
{% endif %}
{#- 섹션 제목(.aot-ov-card-title)과 빈 상태 문구(.aot-ov-muted)는 지도·시설
    모달이 쓰는 것과 같은 공용 파일이다(AoT_plot.py와 동일한 로드 가드).
    개별 공지/노트 카드 자체(.aot-notice-widget-card, 아래 <style>)는 이
    위젯만의 것이다 — `.aot-ov-block`/`.aot-ov-note`(요약 패널·미리보기
    2개용, 대시보드 위젯 안에서는 의도적으로 테두리/배경 대비가 없다)를
    여러 항목을 스크롤하는 목록에 그대로 썼더니 항목 사이 경계가 전혀
    안 보였다(2026-09-08 사용자 지적: "컨테이너도 없고"). 그래서 카드
    자체는 새로 두되, 값은 전부 공용 토큰(--aot-radius-sm·--aot-space-*
    등)에서 가져온다. -#}
{% if "css_sensor_label" not in dashboard_dict %}
<link rel="stylesheet" href="{{ url_for('static', filename='css/widget/aot-sensor-label.css') }}">
{% set _dummy = dashboard_dict.update({"css_sensor_label": 1}) %}
{% endif %}
<style>
  /* Fills #container-graph exactly (100% + overflow:hidden) so this widget's
     own content can never exceed the gridstack card's box. Without this, the
     scrollable list + the footer below it (two block siblings) add up to
     more than 100% height, tripping GridStack's own
     .grid-stack-item-content{overflow-y:auto} on top of our inner scroll —
     a double scrollbar that persists no matter how large the card is resized. */
  .aot-notice-widget-outer { height: 100%; display: flex; flex-flow: column; overflow: hidden; }
  /* 공지·노트를 각각 독립 스크롤 영역(flex:1 1 0 두 개)으로 나눴던 첫 시도는
     위젯을 낮게 줄이면 스크롤바가 두 개 생겨 어느 쪽을 스크롤하는지, 어느
     쪽이 얼마나 남았는지 가늠할 수 없는 상태가 됐다(2026-09-08 사용자 지적:
     "스크롤이 2개 생기고 제대로 제어할 수 없는 상태"). 스크롤 영역을 하나로
     합친다 — 공지 카드 다음에 노트 카드가 이어지는 한 목록으로 보이고, 위젯이
     아무리 낮아져도 스크롤바는 항상 하나뿐이다.
     min-height:0 은 그래도 필요하다 — flex 아이템의 기본 min-height 는
     "auto"(내용의 자연 높이)라, 이것이 없으면 이 컨테이너가 내용보다 작게
     줄어들기를 거부하고 overflow-y:auto 가 아예 작동하지 않는다. */
  .aot-notice-widget-container { padding: var(--aot-space-2); flex: 1 1 auto; min-height: 0; overflow-y: auto; }
  /* 개별 공지/노트를 다시 카드로 되돌린다(2026-09-08) — 앞서 한 줄짜리
     미리보기 행(.aot-ov-note)으로 바꿨더니 이 위젯 안에서는 두 섹션이
     경계 없이 이어붙어 "컨테이너가 없다" 로 읽혔다. `.aot-ov-block` 은
     대시보드 위젯 안에서 테두리·배경 대비를 일부러 안 쓰는 컴포넌트라
     (AoT_plot.py 주석 2026-09-05: 카드 사이 구분선을 넣었다 뺐다 결국
     "위젯 내부는 배경 기본색 한 겹" 으로 정착) 요약 패널 한두 개에는
     맞지만, 여러 개를 스크롤하는 목록에는 경계가 필요하다. 값 자체는
     테두리·라운드·여백을 전부 토큰(--aot-radius-sm·--aot-space-2 등)에서
     가져와 다른 카드와 같은 척도를 쓴다 — 리터럴 픽셀값을 쓰지 않는다.

     ⚠ 좌우 패딩은 --aot-space-4(16px) — space-3(12px)이 아니다. 위
     `.aot-ov-card-title` 의 좌우 패딩이 바로 이 값이고, 그 클래스 자신의
     주석이 "박스 내부 여백과 같은 값이어야 제목이 그 아래 박스 첫 줄과
     같은 세로선에서 시작한다" 고 못박고 있다(aot-sensor-label.css:507).
     `.aot-ov-block` 을 버리고 제목만 재사용하면서 카드 쪽에 임의로
     space-3 을 넣었더니 정확히 그 정렬이 깨졌다(2026-09-08 사용자 지적:
     "제목부터 쭉 내려가면서 왼쪽 정렬이 하나도 안 됨"). 진짜 공용
     스타일을 썼다면 애초에 어긋날 수 없었던 값이다. */
  .aot-notice-widget-card {
    border: 1px solid var(--aot-border-neutral);
    border-radius: var(--aot-radius-sm);
    padding: var(--aot-space-2) var(--aot-space-4);
    margin-bottom: var(--aot-space-2);
    background: var(--aot-surface-card);
  }
  .aot-notice-widget-card:last-child { margin-bottom: 0; }
  .aot-notice-widget-card-title {
    font-weight: 700; font-size: var(--aot-font-size-sm); color: var(--aot-color-text-primary);
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }
  /* 카테고리를 알약 배지로 감싸지 않는다 — 배지는 자기 안쪽 여백
     (padding)이 있어 그 글자만 카드 제목·다른 텍스트와 다른 세로선에서
     시작한다(2026-09-08 사용자 지적: "알약 문자는 문자 아니냐" ·
     "그냥 알약으로 싸지 마"). 카테고리·날짜·대상명 전부 같은 줄의 평문. */
  .aot-notice-widget-card-meta {
    font-size: var(--aot-font-size-2xs); color: var(--aot-color-text-secondary);
    margin-top: var(--aot-space-1);
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }
  .aot-notice-widget-open, .aot-notice-widget-note-open { cursor: pointer; }
  .aot-notice-widget-open:hover, .aot-notice-widget-note-open:hover { border-color: var(--aot-border-strong, #ced4da); }
  /* 공지 카드 마지막 것과 "노트" 제목 사이 간격이 0px였다(둘 다 자기
     여백을 안 가짐 — .aot-ov-card-title는 margin-top이 없고, 마지막
     카드는 :last-child로 margin-bottom을 지운다). AoT_plot.py가 쓰는
     .aot-ov-block은 margin-bottom:16px(--aot-space-4)로 다음 제목과의
     간격을 스스로 만드는데, 그 대신 개별 카드를 쓰면서 이 몫이 빠졌다
     (2026-09-08 사용자 지적: "노트와 공지 사이에 여백이 없어서 답답해").
     같은 값을 제목 쪽 margin-top으로 준다 — 첫 제목("공지")은 컨테이너
     자체 패딩이 이미 있으니 0. */
  .aot-notice-widget-container > .aot-ov-card-title { margin-top: var(--aot-space-4); }
  .aot-notice-widget-container > .aot-ov-card-title:first-child { margin-top: 0; }

  /* 상세 팝업 본문은 이제 .aot-ov-block(공용 카드)로 감싼다 — 목록의
     짧은 미리보기와 달리 여긴 글 전체를 읽는 자리라 컨테이너가 있어야
     한다(2026-09-08 사용자 지적: "텍스트를 컨테이너로 감싸야할 것
     같아"). 여기 아래 규칙은 .aot-ov-block 위에 얹혀 글자 크기·줄간격만
     오버라이드한다(카드 자체의 배경·테두리·둥근모서리·안여백은 그대로). */
  .aot-notice-widget-modal-body {
    font-size: var(--aot-font-size-sm); line-height: 1.6; white-space: normal;
    color: var(--aot-color-text-primary, #212529);
  }
  .aot-notice-widget-modal-body .aot-notice-embed-video iframe { width: 100%; max-width: 480px; aspect-ratio: 16/9; border-radius: 0.5rem; }
  .aot-notice-widget-modal-body .aot-notice-embed-image img { max-width: 100%; border-radius: 0.5rem; }
  .aot-notice-link-preview {
    display: flex; align-items: center; gap: 0.6rem;
    border: 1px solid var(--aot-border-neutral, #dee2e6);
    border-radius: 0.6rem; padding: 0.5rem 0.75rem; margin-top: 0.5rem;
    text-decoration: none; color: inherit; max-width: 100%;
  }
  .aot-notice-link-preview:hover { background: var(--aot-surface-body, #f8f9fa); }
  .aot-notice-link-preview-image { width: 48px; height: 48px; object-fit: cover; border-radius: 0.4rem; flex-shrink: 0; }
  .aot-notice-link-preview-text { display: flex; flex-direction: column; overflow: hidden; }
  .aot-notice-link-preview-title { font-weight: 700; font-size: var(--aot-font-size-sm); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .aot-notice-link-preview-desc { font-size: var(--aot-font-size-xs); color: var(--aot-color-text-secondary, #6c757d); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .aot-notice-link-preview-domain { font-size: var(--aot-font-size-2xs); color: var(--aot-color-text-secondary, #6c757d); margin-top: 2px; }
  .aot-notice-widget-poll-row {
    display: flex; align-items: center; justify-content: space-between;
    font-size: var(--aot-font-size-sm); padding: 0.4rem 0.6rem; border: 1px solid var(--aot-border-neutral, #dee2e6);
    border-radius: 0.5rem; margin-bottom: 0.35rem; cursor: pointer;
  }
  .aot-notice-widget-poll-row.selected { border-color: var(--aot-btn-bg-primary, #13261B); background: var(--aot-surface-body, #f8f9fa); }
  .aot-notice-widget-poll-bar-track { height: 5px; border-radius: 3px; background: var(--aot-surface-body, #e9ecef); margin-top: 3px; overflow: hidden; }
  .aot-notice-widget-poll-bar-fill { height: 100%; background: var(--aot-btn-bg-primary, #13261B); }
  .aot-notice-widget-reply-item { padding: 0.4rem 0; border-bottom: 1px solid var(--aot-border-neutral, #f1f1f1); font-size: var(--aot-font-size-sm); }
  .aot-notice-widget-reply-meta { font-size: var(--aot-font-size-2xs); color: var(--aot-color-text-secondary, #6c757d); }
  .aot-notice-widget-reply-input-row { display: flex; gap: 6px; margin-top: 0.5rem; }
  .aot-notice-widget-reply-input-row input { flex: 1; }

  textarea.aot-notice-textarea {
    border-radius: 8px !important;
    border: 1px solid var(--aot-border-neutral) !important;
    outline: none !important;
    white-space: normal !important;
    overflow-wrap: break-word !important;
    overflow-x: hidden !important;
    overflow-y: hidden !important;
    resize: none !important;
    min-height: 120px;
  }
  textarea.aot-notice-textarea:focus {
    /* Shared focus: --aot-input-focus-border (brand deep green) + --aot-focus-ring.
       Until 2026-09 that token held the brand yellow, so this block kept its own
       grey border; the token was fixed, so the exception is gone. */
    border-color: var(--aot-input-focus-border) !important;
    box-shadow: 0 0 0 0.15rem var(--aot-focus-ring) !important;
    outline: none !important;
  }

  /* Class selector (not ID) because widget_dashboard_head is rendered once per
     widget TYPE, not per instance — the per-widget unique_id template variable
     isn't in scope here, so a per-instance ID override can't be used. Widened
     to match the same body-editing need as the full notice page's compose modal. */
  .notice-widget-compose-modal .modal-dialog {
    max-width: 820px !important;
  }
</style>""",

    'widget_dashboard_title_bar': """{#- 이름은 셸이 렌더한다. 여기는 제목줄 오른쪽 도구만. -#}
{% if permission_edit_settings and widget_options.get('show_notice', True) %}
<div class="widget-map-controls" id="notice-widget-header-controls-{{each_widget.unique_id}}">
    <a class="aot-w-tool widget-map-ctrl-btn" id="notice-widget-new-btn-{{each_widget.unique_id}}"
       role="button" tabindex="0" aria-label="{{_('New Post')}}" title="{{_('New Post')}}">
        <i class="fas fa-plus"></i>
    </a>
</div>
{% endif %}
""",

    'widget_dashboard_body': """
{% set aot_show_notice = widget_options.get('show_notice', True) %}
{% set aot_show_notes = widget_options.get('show_notes', False) %}
<div class="aot-notice-widget-outer">
  <div class="aot-notice-widget-container">
  {% if aot_show_notice %}
    {% if aot_show_notes %}<div class="aot-ov-card-title">{{_('Notices')}}</div>{% endif %}
    <div id="notice-widget-{{each_widget.unique_id}}">
      <div class="aot-ov-muted">{{_('Loading...')}}</div>
    </div>
  {% endif %}
  {% if aot_show_notes %}
    {% if aot_show_notice %}<div class="aot-ov-card-title">{{_('Notes')}}</div>{% endif %}
    <div id="notice-widget-notes-{{each_widget.unique_id}}">
      <div class="aot-ov-muted">{{_('Loading...')}}</div>
    </div>
  {% endif %}
  {% if not aot_show_notice and not aot_show_notes %}
    <div class="aot-ov-muted">{{_('Nothing selected — turn on "Show Notices" and/or "Show Notes" in the widget settings.')}}</div>
  {% endif %}
  </div>
</div>

<div class="modal fade aot-option-modal" id="notice-widget-modal-{{each_widget.unique_id}}" tabindex="-1" role="dialog" aria-hidden="true">
  <div class="modal-dialog" role="document">
    <div class="modal-content">
      <div class="modal-header">
        <h5 class="modal-title" id="notice-widget-modal-title-{{each_widget.unique_id}}"></h5>
        <button type="button" class="close" data-dismiss="modal" aria-label="{{_('Close')}}">
          <span aria-hidden="true">&times;</span>
        </button>
      </div>
      <div class="modal-body" id="notice-widget-modal-content-{{each_widget.unique_id}}"></div>
      <div class="modal-footer">
        <button type="button" class="btn aot-pill-btn aot-pill-btn-primary notice-widget-view-edit-btn d-none">{{_('Edit')}}</button>
        <button type="button" class="btn aot-pill-btn aot-pill-btn-danger notice-widget-view-delete-btn d-none">{{_('Delete')}}</button>
        <button type="button" class="btn aot-pill-btn aot-pill-btn-primary notice-widget-view-ack-btn">{{_('Acknowledge')}}</button>
        <button type="button" class="btn aot-pill-btn" data-dismiss="modal">{{_('Close')}}</button>
      </div>
    </div>
  </div>
</div>

{% if permission_edit_settings %}
<div class="modal fade aot-option-modal notice-widget-compose-modal" id="notice-widget-compose-modal-{{each_widget.unique_id}}" tabindex="-1" role="dialog" aria-hidden="true">
  <div class="modal-dialog" role="document">
    <div class="modal-content">
      <form id="notice-widget-compose-form-{{each_widget.unique_id}}" enctype="multipart/form-data">
        <div class="modal-header">
          <h5 class="modal-title notice-widget-compose-modal-title">{{_('New Notice')}}</h5>
          <button type="button" class="close" data-dismiss="modal" aria-label="{{_('Close')}}">
            <span aria-hidden="true">&times;</span>
          </button>
        </div>
        <div class="modal-body">
          <input type="hidden" name="notice_unique_id" class="notice-widget-compose-id-input" value="">
          <input type="hidden" name="deleted_files" class="notice-widget-compose-deleted-files" value="">
          <input type="hidden" name="set_expire" value="y" class="notice-widget-compose-set-expire" disabled>
          <input type="hidden" name="expire_at" value="" class="notice-widget-compose-expire-at" disabled>

          <div class="aot-modal-container">
            <div class="aot-modal-option-row aot-full-width-row">
              <label class="aot-modal-option-label">{{_('Title')}}</label>
              <div class="aot-modal-option-control">
                <input type="text" name="title" class="aot-modern-input notice-widget-compose-title" style="width:100%;">
              </div>
            </div>
            <div class="aot-modal-option-row aot-full-width-row">
              <label class="aot-modal-option-label">{{_('Content')}}</label>
              <div class="aot-modal-option-control">
                <textarea name="body" class="aot-modern-input aot-notice-textarea notice-widget-compose-body" style="width:100%; height:auto;" rows="6" placeholder="{{_('Markdown supported: **bold**, *italic*. Links, YouTube, and image URLs are auto-detected.')}}"></textarea>
              </div>
            </div>
            <div class="aot-modal-option-row aot-full-width-row">
              <label class="aot-modal-option-label">{{_('Category')}}</label>
              <div class="aot-modal-option-control">
                <input type="text" name="category" class="aot-modern-input notice-widget-compose-category" style="width:100%;" list="notice-widget-category-list-{{each_widget.unique_id}}" placeholder="{{_('Optional')}}">
                <datalist id="notice-widget-category-list-{{each_widget.unique_id}}">
                  {% for cat in widget_variables.get('available_categories', []) %}
                  <option value="{{cat}}">
                  {% endfor %}
                </datalist>
              </div>
            </div>
            <div class="aot-modal-option-row aot-full-width-row d-none notice-widget-compose-current-attachments-row">
              <label class="aot-modal-option-label">{{_('Current Attachments')}}</label>
              <div class="aot-modal-option-control notice-widget-compose-current-attachments" style="flex-wrap:wrap; justify-content:flex-start;"></div>
            </div>
            <div class="aot-modal-option-row aot-full-width-row">
              <label class="aot-modal-option-label">{{_('Attachments')}}</label>
              <div class="aot-modal-option-control">
                <input type="file" name="files" multiple style="width:100%;">
              </div>
            </div>
          </div>

          <button type="button" class="btn aot-pill-btn mb-2 mt-2 notice-widget-poll-toggle-btn">{{_('Add Poll')}}</button>
          <div class="aot-modal-container d-none notice-widget-poll-section">
            <div class="d-flex justify-content-between align-items-center">
              <div class="aot-modal-section-title" style="margin-top:0.6rem;">{{_('Poll')}}</div>
              <button type="button" class="btn aot-pill-btn notice-widget-poll-remove-btn">{{_('Remove Poll')}}</button>
            </div>
            <div class="aot-modal-option-row aot-full-width-row">
              <label class="aot-modal-option-label">{{_('Question')}}</label>
              <div class="aot-modal-option-control">
                <input type="text" name="poll_question" class="aot-modern-input notice-widget-compose-poll-question" style="width:100%;">
              </div>
            </div>
            <div class="aot-modal-option-row">
              <label class="aot-modal-option-label">{{_('Allow Multiple Choices')}}</label>
              <div class="aot-modal-option-control">
                <input type="checkbox" name="poll_multi" class="notice-widget-compose-poll-multi">
              </div>
            </div>
            <div class="notice-widget-poll-options-container">
              <div class="aot-modal-option-row aot-full-width-row"><input type="text" name="poll_option" class="aot-modern-input" placeholder="{{_('Option 1')}}" style="width:100%;"></div>
              <div class="aot-modal-option-row aot-full-width-row"><input type="text" name="poll_option" class="aot-modern-input" placeholder="{{_('Option 2')}}" style="width:100%;"></div>
            </div>
            <button type="button" class="btn aot-pill-btn mt-1 mb-2 notice-widget-poll-add-option-btn">{{_('Add Option')}}</button>
          </div>

          <div class="aot-modal-container mt-2 notice-widget-compose-pin-row d-none">
            <div class="aot-modal-option-row">
              <label class="aot-modal-option-label">{{_('Pin to Top')}}</label>
              <div class="aot-modal-option-control">
                <input type="checkbox" name="pinned" class="notice-widget-compose-pinned">
              </div>
            </div>
          </div>
        </div>
        <div class="modal-footer">
          <button type="button" class="btn aot-pill-btn" data-dismiss="modal">{{_('Cancel')}}</button>
          <button type="button" class="btn aot-pill-btn aot-pill-btn-danger d-none notice-widget-compose-delete-btn">{{_('Delete')}}</button>
          <button type="submit" class="btn aot-pill-btn aot-pill-btn-primary notice-widget-compose-save-btn">{{_('Save')}}</button>
        </div>
      </form>
    </div>
  </div>
</div>
{% endif %}
""",

    'widget_dashboard_js': """
var NOTICE_WIDGET_PARTICIPATED_TPL = "{{ _('%(n)s participated', n='__N__') }}";
var NOTICE_WIDGET_ACKNOWLEDGED_TPL = "{{ _('%(n)s acknowledged', n='__N__') }}";

function aotNoticeWidgetAutosize(el) {
  if (!el) { return; }
  el.style.height = 'auto';
  el.style.height = el.scrollHeight + 'px';
}

function aotNoticeWidgetRenderList(widgetId, data) {
  var esc = AoTNoticeRender.escapeHtml;
  var $container = $('#notice-widget-' + widgetId);
  if (!data.posts.length) {
    $container.html('<div class="aot-ov-muted">{{_('No notices yet.')}}</div>');
    return;
  }
  var html = '';
  data.posts.forEach(function (post) {
    html += '<div class="aot-notice-widget-card aot-notice-widget-open" data-post="' + post.unique_id + '">' +
      '<div class="aot-notice-widget-card-title">' +
      (post.pinned ? '[{{_('Pinned')}}] ' : '') +
      esc(post.title) + '</div>' +
      '<div class="aot-notice-widget-card-meta">' +
      (post.category ? esc(post.category) + ' \\u00b7 ' : '') +
      esc(post.date_time) +
      '</div>' +
      '</div>';
  });
  $container.html(html);
}

function aotNoticeWidgetFetchList(widgetId, limit, categories) {
  var url = '/notice/api/latest?limit=' + limit;
  if (categories && categories.length) {
    url += '&categories=' + encodeURIComponent(categories.join(','));
  }
  $.ajax({
    url: url,
    method: 'GET',
    success: function (data) { aotNoticeWidgetRenderList(widgetId, data); }
  });
}

// 노트 카드는 공지 카드와 같은 골격(.aot-notice-widget-card 등)을 그대로
// 쓴다 — 한 위젯 안에서 두 소스가 다른 카드 모양이면 그 자체가 혼란이다.
function aotNoticeWidgetRenderNotesList(widgetId, notes, limit, sort, categoryFilter) {
  var esc = AoTNoticeRender.escapeHtml;
  var $container = $('#notice-widget-notes-' + widgetId);
  var filtered = notes;
  if (categoryFilter) {
    var needle = categoryFilter.toLowerCase();
    filtered = notes.filter(function (n) {
      return ((n.category || '') + ' ' + (n.tags || '')).toLowerCase().indexOf(needle) !== -1;
    });
  }
  if (sort === 'priority') {
    filtered = filtered.slice().sort(function (a, b) { return (b.priority || 0) - (a.priority || 0); });
  } else if (sort === 'category') {
    filtered = filtered.slice().sort(function (a, b) { return (a.category || '').localeCompare(b.category || ''); });
  }
  // 'date' 는 서버가 이미 최신순으로 준다(추가 정렬 불필요).
  filtered = filtered.slice(0, limit);
  if (!filtered.length) {
    $container.html('<div class="aot-ov-muted">{{_('No notes yet.')}}</div>');
    return;
  }
  var html = '';
  filtered.forEach(function (n) {
    var text = String(n.note || '').replace(/\\s+/g, ' ').trim();
    if (!text) { text = '{{_('(Attachment only)')}}'; }
    html += '<div class="aot-notice-widget-card aot-notice-widget-note-open" data-target="' + esc(n.target_id) + '" data-target-type="' + esc(n.target_type || 'unknown') + '" data-name="' + esc(n.target_name || '') + '">' +
      '<div class="aot-notice-widget-card-title">' + esc(text) + '</div>' +
      '<div class="aot-notice-widget-card-meta">' +
      (n.category ? esc(n.category) + ' \\u00b7 ' : '') +
      esc(n.date_time) +
      (n.target_name ? ' \\u00b7 ' + esc(n.target_name) : '') +
      '</div>' +
      '</div>';
  });
  $container.html(html);
}

function aotNoticeWidgetFetchNotesList(widgetId, targetType, targetId, includeDescendants, limit, sort, categoryFilter) {
  if (!targetId) {
    $('#notice-widget-notes-' + widgetId).html(
      '<div class="aot-ov-muted">{{_('Choose a space in the widget settings to show notes.')}}</div>');
    return;
  }
  var url = '/notes/target/' + encodeURIComponent(targetId) + (includeDescendants ? '?descendants=1' : '');
  $.ajax({
    url: url,
    method: 'GET',
    success: function (notes) {
      if (notes && notes.error) { return; }
      aotNoticeWidgetRenderNotesList(widgetId, notes, limit, sort, categoryFilter);
    }
  });
}

function aotNoticeWidgetBuildModalBody(post, showPoll, showReply, currentUserId, isAdmin) {
  var esc = AoTNoticeRender.escapeHtml;
  var html = '<div class="small text-muted mb-2">' +
    (post.category ? esc(post.category) + ' &middot; ' : '') +
    esc(post.author) + ' &middot; ' + esc(post.date_time) + '</div>';
  html += '<div class="aot-ov-block aot-notice-widget-modal-body">' + AoTNoticeRender.renderNoticeBody(post.body || '') + '</div>';

  if (showPoll && post.poll) {
    html += '<div class="aot-notice-widget-poll mt-3" data-multi="' + post.poll.multi + '">';
    html += '<div class="font-weight-bold mb-1">' + esc(post.poll.question) + '</div>';
    post.poll.options.forEach(function (opt) {
      var pct = post.poll.voter_count ? Math.round(opt.count / post.poll.voter_count * 100) : 0;
      html += '<div class="aot-notice-widget-poll-row' + (opt.selected ? ' selected' : '') + '" data-option="' + opt.unique_id + '">' +
        '<div style="flex:1;"><div>' + esc(opt.label) + '</div>' +
        '<div class="aot-notice-widget-poll-bar-track"><div class="aot-notice-widget-poll-bar-fill" style="width:' + pct + '%;"></div></div></div>' +
        '<div class="small text-muted ml-3">' + opt.count + '</div></div>';
    });
    html += '<div class="small text-muted mt-1">' + NOTICE_WIDGET_PARTICIPATED_TPL.replace('__N__', post.poll.voter_count) + '</div>';
    if (!post.poll.closed) {
      html += '<button type="button" class="btn aot-pill-btn aot-pill-btn-primary btn-sm mt-2 aot-notice-widget-vote-btn" data-post="' + post.unique_id + '">{{_('Vote')}}</button>';
    }
    html += '</div>';
  }

  html += '<div class="small text-muted mt-3">' + NOTICE_WIDGET_ACKNOWLEDGED_TPL.replace('__N__', post.ack_count) + '</div>';

  html += '<div class="mt-3"><div class="font-weight-bold mb-2">{{_('Replies')}} (' + post.replies.length + ')</div>';
  html += '<div class="aot-notice-widget-reply-list">';
  post.replies.forEach(function (reply) {
    html += '<div class="aot-notice-widget-reply-item" data-reply="' + reply.unique_id + '">' +
      '<div class="aot-notice-widget-reply-meta">' + esc(reply.author) + ' &middot; ' + esc(reply.date_time);
    if (isAdmin || reply.user_id === currentUserId) {
      html += ' <a href="#" class="text-danger ml-1 aot-notice-widget-reply-delete" data-reply="' + reply.unique_id + '">{{_('Delete')}}</a>';
    }
    html += '</div><div style="white-space:pre-wrap;">' + esc(reply.body) + '</div></div>';
  });
  html += '</div>';

  if (showReply) {
    html += '<div class="aot-notice-widget-reply-input-row">' +
      '<input type="text" class="aot-modern-input aot-notice-widget-modal-reply-input" placeholder="{{_('Write a reply...')}}">' +
      '<button type="button" class="btn aot-pill-btn aot-pill-btn-primary aot-notice-widget-modal-reply-btn" data-post="' + post.unique_id + '">{{_('Reply')}}</button>' +
      '</div>';
  }
  html += '</div>';

  return html;
}

function aotNoticeWidgetOpenModal(widgetId, postId, showPoll, showReply, currentUserId, isAdmin) {
  $.ajax({
    url: '/notice/api/' + postId,
    method: 'GET',
    success: function (post) {
      if (post.error) { showToast(post.error, 'error'); return; }
      var $modal = $('#notice-widget-modal-' + widgetId);
      $modal.data('current-post', post.unique_id);
      $modal.find('.notice-widget-view-edit-btn').toggleClass('d-none', !post.can_manage);
      $modal.find('.notice-widget-view-delete-btn').toggleClass('d-none', !post.can_manage);
      $modal.find('.notice-widget-view-ack-btn')
        .data('post', post.unique_id)
        .prop('disabled', post.has_acked)
        .text(post.has_acked ? '{{_('Acknowledged')}}' : '{{_('Acknowledge')}}');
      $('#notice-widget-modal-title-' + widgetId).text(post.title);
      var $content = $('#notice-widget-modal-content-' + widgetId);
      $content.html(aotNoticeWidgetBuildModalBody(post, showPoll, showReply, currentUserId, isAdmin));
      AoTNoticeRender.hydrateLinkPreviews($content.get(0));
      $modal.modal('show');
    }
  });
}

function aotNoticeWidgetResetCompose(widgetId) {
  var $form = $('#notice-widget-compose-form-' + widgetId);
  $form.get(0).reset();
  $form.find('.notice-widget-compose-id-input').val('');
  $form.find('.notice-widget-compose-deleted-files').val('');
  $form.find('.notice-widget-compose-set-expire').prop('disabled', true);
  $form.find('.notice-widget-compose-expire-at').prop('disabled', true).val('');
  $form.find('.notice-widget-compose-current-attachments').empty();
  $form.find('.notice-widget-compose-current-attachments-row').addClass('d-none');
  $form.find('.notice-widget-compose-pin-row').addClass('d-none');
  $form.find('.notice-widget-poll-section').addClass('d-none');
  $form.find('.notice-widget-poll-toggle-btn').removeClass('d-none');
  $form.find('.notice-widget-poll-options-container').html(
    '<div class="aot-modal-option-row aot-full-width-row"><input type="text" name="poll_option" class="aot-modern-input" placeholder="{{_('Option 1')}}" style="width:100%;"></div>' +
    '<div class="aot-modal-option-row aot-full-width-row"><input type="text" name="poll_option" class="aot-modern-input" placeholder="{{_('Option 2')}}" style="width:100%;"></div>'
  );
  $form.find('.notice-widget-compose-delete-btn').addClass('d-none');
  $('#notice-widget-compose-modal-' + widgetId + ' .notice-widget-compose-modal-title').text('{{_('New Notice')}}');
  aotNoticeWidgetAutosize($form.find('.notice-widget-compose-body').get(0));
}

function aotNoticeWidgetOpenComposeCreate(widgetId, isAdmin) {
  aotNoticeWidgetResetCompose(widgetId);
  if (isAdmin) {
    $('#notice-widget-compose-form-' + widgetId).find('.notice-widget-compose-pin-row').removeClass('d-none');
  }
  $('#notice-widget-compose-modal-' + widgetId).modal('show');
}

function aotNoticeWidgetOpenComposeEdit(widgetId, postId, isAdmin) {
  $.ajax({
    url: '/notice/api/' + postId,
    method: 'GET',
    success: function (post) {
      if (post.error) { showToast(post.error, 'error'); return; }
      aotNoticeWidgetResetCompose(widgetId);
      var esc = AoTNoticeRender.escapeHtml;
      var $form = $('#notice-widget-compose-form-' + widgetId);

      $form.find('.notice-widget-compose-id-input').val(post.unique_id);
      $form.find('.notice-widget-compose-title').val(post.title);
      $form.find('.notice-widget-compose-category').val(post.category || '');
      var $body = $form.find('.notice-widget-compose-body');
      $body.val(post.body || '');
      aotNoticeWidgetAutosize($body.get(0));

      if (post.expire_at) {
        $form.find('.notice-widget-compose-set-expire').prop('disabled', false);
        $form.find('.notice-widget-compose-expire-at').prop('disabled', false).val(post.expire_at);
      }

      if (isAdmin) {
        $form.find('.notice-widget-compose-pin-row').removeClass('d-none');
        $form.find('.notice-widget-compose-pinned').prop('checked', !!post.pinned);
      }

      if (post.files && post.files.length) {
        var $current = $form.find('.notice-widget-compose-current-attachments');
        post.files.forEach(function (f) {
          var displayName = f.substring(f.indexOf('_') + 1);
          $current.append(
            '<span class="badge badge-light border mr-1 mb-1" data-file="' + f + '">' +
            '<a href="/notice_attachment/' + f + '" target="_blank">' + esc(displayName) + '</a>' +
            ' <a href="#" class="text-danger ml-1 notice-widget-compose-remove-attachment" data-file="' + f + '">&times;</a>' +
            '</span>'
          );
        });
        $form.find('.notice-widget-compose-current-attachments-row').removeClass('d-none');
      }

      if (post.poll) {
        $form.find('.notice-widget-poll-section').removeClass('d-none');
        $form.find('.notice-widget-poll-toggle-btn').addClass('d-none');
        $form.find('.notice-widget-compose-poll-question').val(post.poll.question);
        $form.find('.notice-widget-compose-poll-multi').prop('checked', !!post.poll.multi);
        var $opts = $form.find('.notice-widget-poll-options-container');
        $opts.empty();
        post.poll.options.forEach(function (opt) {
          $opts.append(
            '<div class="aot-modal-option-row aot-full-width-row"><input type="text" name="poll_option" class="aot-modern-input" style="width:100%;" value="' +
            esc(opt.label) + '"></div>');
        });
      }

      $form.find('.notice-widget-compose-delete-btn').removeClass('d-none').data('post', post.unique_id);
      $('#notice-widget-compose-modal-' + widgetId + ' .notice-widget-compose-modal-title').text('{{_('Edit Notice')}}');
      $('#notice-widget-compose-modal-' + widgetId).modal('show');
    }
  });
}

function aotNoticeWidgetInit(widgetId, limit, refreshSeconds, showPoll, showReply, currentUserId, isAdmin, categories, showNotice, notesOpts) {
  if (showNotice) {
    aotNoticeWidgetFetchList(widgetId, limit, categories);
  }
  if (notesOpts && notesOpts.show) {
    aotNoticeWidgetFetchNotesList(widgetId, notesOpts.targetType, notesOpts.targetId,
      notesOpts.includeDescendants, notesOpts.limit, notesOpts.sort, notesOpts.categoryFilter);
  }
  // Store the refresh interval per widget and clear the previous one so a
  // live-preview re-init (option change without page reload) doesn't stack
  // duplicate fetch intervals.
  window._notice_intervals = window._notice_intervals || {};
  if (window._notice_intervals[widgetId]) { clearInterval(window._notice_intervals[widgetId]); }
  window._notice_intervals[widgetId] = setInterval(function () {
    if (showNotice) { aotNoticeWidgetFetchList(widgetId, limit, categories); }
    if (notesOpts && notesOpts.show) {
      aotNoticeWidgetFetchNotesList(widgetId, notesOpts.targetType, notesOpts.targetId,
        notesOpts.includeDescendants, notesOpts.limit, notesOpts.sort, notesOpts.categoryFilter);
    }
  }, refreshSeconds * 1000);

  var $list = $('#notice-widget-' + widgetId);
  var $notesList = $('#notice-widget-notes-' + widgetId);
  var $modal = $('#notice-widget-modal-' + widgetId);
  var $modalContent = $('#notice-widget-modal-content-' + widgetId);
  var $composeForm = $('#notice-widget-compose-form-' + widgetId);

  // Idempotent re-init: clear this widget's previously bound handlers (namespace
  // .aotnw) before re-binding, so a live-preview re-init doesn't double-bind on
  // the modals that fixModalZIndex moved to <body> (and thus survive a body swap).
  $list.off('.aotnw'); $notesList.off('.aotnw'); $modal.off('.aotnw'); $modalContent.off('.aotnw');
  $composeForm.off('.aotnw'); $('#notice-widget-new-btn-' + widgetId).off('.aotnw');

  $list.on('click.aotnw', '.aot-notice-widget-open', function (e) {
    e.preventDefault();
    aotNoticeWidgetOpenModal(widgetId, $(this).data('post'), showPoll, showReply, currentUserId, isAdmin);
  });

  // 노트는 별도 모달을 만들지 않는다 — 앱 전체가 공유하는 노트 패널 하나로
  // 넘긴다(진입점은 AoTNotesBlock 이 쓰는 것과 같은 'open-notes' 이벤트 하나).
  $notesList.on('click.aotnw', '.aot-notice-widget-note-open', function () {
    var $el = $(this);
    window.dispatchEvent(new CustomEvent('open-notes', { detail: {
      targetId: $el.data('target'),
      targetType: $el.data('target-type') || 'unknown',
      name: $el.data('name') || ''
    } }));
  });

  $modalContent.on('click.aotnw', '.aot-notice-widget-poll-row', function () {
    var $poll = $(this).closest('.aot-notice-widget-poll');
    var isMulti = $poll.data('multi') === true || $poll.data('multi') === 'true';
    if (isMulti) {
      $(this).toggleClass('selected');
    } else {
      $poll.find('.aot-notice-widget-poll-row').removeClass('selected');
      $(this).addClass('selected');
    }
  });

  $modalContent.on('click.aotnw', '.aot-notice-widget-vote-btn', function () {
    var postId = $(this).data('post');
    var $poll = $(this).closest('.aot-notice-widget-poll');
    var optionIds = [];
    $poll.find('.aot-notice-widget-poll-row.selected').each(function () {
      optionIds.push($(this).data('option'));
    });
    if (!optionIds.length) { return; }
    $.ajax({
      url: '/notice/api/' + postId + '/vote',
      method: 'POST',
      contentType: 'application/json',
      data: JSON.stringify({ option_ids: optionIds }),
      success: function () {
        showToast('{{_('Vote submitted')}}', 'success');
        aotNoticeWidgetOpenModal(widgetId, postId, showPoll, showReply, currentUserId, isAdmin);
      },
      error: function (xhr) {
        var msg = (xhr.responseJSON && xhr.responseJSON.error) || '{{_('Action failed')}}';
        showToast(msg, 'error');
      }
    });
  });

  $modalContent.on('click.aotnw', '.aot-notice-widget-modal-reply-btn', function () {
    var postId = $(this).data('post');
    var $input = $(this).closest('.aot-notice-widget-reply-input-row').find('.aot-notice-widget-modal-reply-input');
    var body = $input.val().trim();
    if (!body) { return; }
    $.ajax({
      url: '/notice/api/' + postId + '/reply',
      method: 'POST',
      contentType: 'application/json',
      data: JSON.stringify({ body: body }),
      success: function () {
        showToast('{{_('Reply added')}}', 'success');
        aotNoticeWidgetOpenModal(widgetId, postId, showPoll, showReply, currentUserId, isAdmin);
      },
      error: function (xhr) {
        var msg = (xhr.responseJSON && xhr.responseJSON.error) || '{{_('Action failed')}}';
        showToast(msg, 'error');
      }
    });
  });

  $modalContent.on('click.aotnw', '.aot-notice-widget-reply-delete', function (e) {
    e.preventDefault();
    var replyId = $(this).data('reply');
    var postId = $modal.data('current-post');
    $.ajax({
      url: '/notice/api/reply/' + replyId + '/delete',
      method: 'POST',
      success: function () {
        showToast('{{_('Reply deleted')}}', 'success');
        aotNoticeWidgetOpenModal(widgetId, postId, showPoll, showReply, currentUserId, isAdmin);
      },
      error: function (xhr) {
        var msg = (xhr.responseJSON && xhr.responseJSON.error) || '{{_('Action failed')}}';
        showToast(msg, 'error');
      }
    });
  });

  // View-modal footer: Edit / Delete (shown only when post.can_manage — author or admin)
  $modal.on('click.aotnw', '.notice-widget-view-edit-btn', function () {
    var postId = $modal.data('current-post');
    $modal.modal('hide');
    aotNoticeWidgetOpenComposeEdit(widgetId, postId, isAdmin);
  });
  $modal.on('click.aotnw', '.notice-widget-view-delete-btn', function () {
    var postId = $modal.data('current-post');
    if (!confirm('{{_('Delete this notice?')}}')) { return; }
    $.ajax({
      url: '/notice/api/' + postId + '/delete',
      method: 'POST',
      success: function () {
        showToast('{{_('Notice deleted')}}', 'success');
        $modal.modal('hide');
        aotNoticeWidgetFetchList(widgetId, limit, categories);
      },
      error: function (xhr) {
        var msg = (xhr.responseJSON && xhr.responseJSON.error) || '{{_('Action failed')}}';
        showToast(msg, 'error');
      }
    });
  });
  $modal.on('click.aotnw', '.notice-widget-view-ack-btn', function () {
    var postId = $(this).data('post');
    $.ajax({
      url: '/notice/api/' + postId + '/ack',
      method: 'POST',
      success: function () {
        showToast('{{_('Acknowledged')}}', 'success');
        aotNoticeWidgetOpenModal(widgetId, postId, showPoll, showReply, currentUserId, isAdmin);
      },
      error: function (xhr) {
        var msg = (xhr.responseJSON && xhr.responseJSON.error) || '{{_('Action failed')}}';
        showToast(msg, 'error');
      }
    });
  });

  // "New Post" button (permission-gated in the template; harmless no-op if absent)
  $('#notice-widget-new-btn-' + widgetId).on('click.aotnw', function () {
    aotNoticeWidgetOpenComposeCreate(widgetId, isAdmin);
  });

  if ($composeForm.length) {
    $composeForm.find('textarea.aot-notice-textarea').on('input.aotnw', function () { aotNoticeWidgetAutosize(this); });
    AoTNoticeRender.bindPasteFormatting('textarea.aot-notice-textarea', $composeForm.get(0));

    $composeForm.find('.notice-widget-poll-toggle-btn').on('click.aotnw', function () {
      $composeForm.find('.notice-widget-poll-section').removeClass('d-none');
      $(this).addClass('d-none');
    });
    $composeForm.find('.notice-widget-poll-remove-btn').on('click.aotnw', function () {
      $composeForm.find('.notice-widget-poll-section').addClass('d-none');
      $composeForm.find('.notice-widget-poll-section input[type="text"]').val('');
      $composeForm.find('.notice-widget-poll-section input[type="checkbox"]').prop('checked', false);
      $composeForm.find('.notice-widget-poll-toggle-btn').removeClass('d-none');
    });
    $composeForm.find('.notice-widget-poll-add-option-btn').on('click.aotnw', function () {
      var count = $composeForm.find('.notice-widget-poll-options-container .aot-modal-option-row').length + 1;
      $composeForm.find('.notice-widget-poll-options-container').append(
        '<div class="aot-modal-option-row aot-full-width-row"><input type="text" name="poll_option" class="aot-modern-input" placeholder="{{_('Option')}} ' + count + '" style="width:100%;"></div>'
      );
    });

    $composeForm.on('click.aotnw', '.notice-widget-compose-remove-attachment', function (e) {
      e.preventDefault();
      var file = $(this).data('file');
      var $deleted = $composeForm.find('.notice-widget-compose-deleted-files');
      var list = $deleted.val() ? $deleted.val().split(',') : [];
      if (list.indexOf(file) === -1) { list.push(file); }
      $deleted.val(list.join(','));
      $(this).closest('[data-file]').fadeOut(200, function () { $(this).remove(); });
    });

    $composeForm.find('.notice-widget-compose-delete-btn').on('click.aotnw', function () {
      var postId = $(this).data('post');
      if (!confirm('{{_('Delete this notice?')}}')) { return; }
      $.ajax({
        url: '/notice/api/' + postId + '/delete',
        method: 'POST',
        success: function () {
          showToast('{{_('Notice deleted')}}', 'success');
          $('#notice-widget-compose-modal-' + widgetId).modal('hide');
          aotNoticeWidgetFetchList(widgetId, limit, categories);
        },
        error: function (xhr) {
          var msg = (xhr.responseJSON && xhr.responseJSON.error) || '{{_('Action failed')}}';
          showToast(msg, 'error');
        }
      });
    });

    $composeForm.on('submit.aotnw', function (e) {
      e.preventDefault();
      var formEl = this;
      var id = $(formEl).find('.notice-widget-compose-id-input').val();
      var url = id ? ('/notice/api/' + id + '/edit') : '/notice/api/create';
      var formData = new FormData(formEl);
      $.ajax({
        url: url,
        method: 'POST',
        data: formData,
        processData: false,
        contentType: false,
        success: function (res) {
          if (res.error) {
            showToast(res.error, 'error');
            return;
          }
          showToast(id ? '{{_('Notice updated')}}' : '{{_('Notice created')}}', 'success');
          $('#notice-widget-compose-modal-' + widgetId).modal('hide');
          aotNoticeWidgetFetchList(widgetId, limit, categories);
        },
        error: function (xhr) {
          var msg = (xhr.responseJSON && xhr.responseJSON.error) || '{{_('Save failed')}}';
          showToast(msg, 'error');
        }
      });
    });
  }
}
""",

    'widget_dashboard_js_ready': """<!-- No JS ready content -->""",

    'widget_dashboard_js_ready_end': """
aotNoticeWidgetInit(
  '{{each_widget.unique_id}}',
  {{widget_options.get('post_count', 3)}},
  {{widget_options['refresh_seconds']}},
  {{widget_options.get('show_poll', True)|lower}},
  {{widget_options.get('show_reply_box', True)|lower}},
  {{ current_user.id if current_user.is_authenticated else 'null' }},
  {{ 'true' if current_user.is_authenticated and current_user.role_id == 1 else 'false' }},
  {{ widget_options.get('categories', []) | tojson }},
  {{widget_options.get('show_notice', True)|lower}},
  {
    show: {{widget_options.get('show_notes', False)|lower}},
    targetType: {{ widget_options.get('notes_target_type', '') | tojson }},
    targetId: {{ widget_options.get('notes_target_id', '') | tojson }},
    includeDescendants: {{widget_options.get('notes_include_descendants', True)|lower}},
    limit: {{widget_options.get('notes_post_count', 5)}},
    sort: {{ widget_options.get('notes_sort', 'date') | tojson }},
    categoryFilter: {{ widget_options.get('notes_category_filter', '') | tojson }}
  }
);
"""
}
