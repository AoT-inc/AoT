# coding=utf-8
from flask_babel import lazy_gettext

from aot.aot_flask.extensions import db
from aot.databases.models import NoticePost
from aot.utils.constraints_pass import constraints_pass_positive_value


def generate_page_variables(widget_unique_id, widget_options):
    """Distinct category labels currently in use, for the settings modal's
    category-filter checkbox list (widget_dashboard_configure_options)."""
    rows = db.session.query(NoticePost.category).filter(
        NoticePost.category.isnot(None), NoticePost.category != '').distinct().order_by(NoticePost.category).all()
    return {'available_categories': [r[0] for r in rows]}


def execute_at_modification(mod_widget, request_form, custom_options_json_presave, custom_options_json_postsave):
    """The category checkboxes aren't a declared custom_options entry (there's
    no fixed choice list to validate against — categories are freeform per
    post), so they're captured here directly from the settings form instead."""
    allow_saving = True
    page_refresh = False
    custom_options_json_postsave['categories'] = request_form.getlist('categories')
    return allow_saving, page_refresh, mod_widget, custom_options_json_postsave


WIDGET_INFORMATION = {
    'widget_name_unique': 'widget_notice',
    'widget_name': lazy_gettext('Notice Board'),
    'widget_library': '',
    'no_class': True,
    'mobile_full_width': True,  # Always takes the full row (single widget per line) on mobile.

    'message': lazy_gettext('Displays the latest notice board post titles. Clicking a title opens '
                'the full post (content, poll, replies, acknowledge) in a popup; all actions '
                'taken there are reflected on the actual post. Users with write permission can '
                'also create, edit, and delete posts directly from the widget.'),

    'dependencies_module': [],

    'widget_width': 6,
    'widget_height': 8,

    'generate_page_variables': generate_page_variables,
    'execute_at_modification': execute_at_modification,

    'custom_options': [
        {
            'id': 'post_count',
            'type': 'integer',
            'default_value': 3,
            'constraints_pass': constraints_pass_positive_value,
            'name': lazy_gettext('Number of Posts'),
            'phrase': lazy_gettext('How many of the latest notices to display')
        },
        {
            'id': 'refresh_seconds',
            'type': 'integer',
            'default_value': 60,
            'constraints_pass': constraints_pass_positive_value,
            'name': lazy_gettext('Refresh (seconds)'),
            'phrase': lazy_gettext('How often to refresh the notice list')
        },
        {
            'id': 'show_poll',
            'type': 'bool',
            'default_value': True,
            'name': lazy_gettext('Show Poll Voting'),
            'phrase': lazy_gettext('Allow voting on polls from the post popup')
        },
        {
            'id': 'show_reply_box',
            'type': 'bool',
            'default_value': True,
            'name': lazy_gettext('Show Reply Box'),
            'phrase': lazy_gettext('Allow sending a reply from the post popup')
        },
    ],

    # Not a declared custom_options entry: the choice list (categories currently
    # in use across posts) is dynamic, not a fixed set — populated per-instance
    # via generate_page_variables() and saved via execute_at_modification()
    # (same pattern AoT_graph.py uses for its per-series checkboxes).
    'widget_dashboard_configure_options': """
<div class="aot-modal-group-title">{{_('Category Filter')}}</div>
<div class="aot-modal-container">
  <div class="aot-modal-option-row aot-full-width-row">
    <div class="aot-modal-body-text">{{_('Only show posts in the selected categories. If none are selected, posts of every category are shown.')}}</div>
  </div>
  {% if widget_variables.get('available_categories') %}
    {% for cat in widget_variables.get('available_categories', []) %}
  <div class="aot-modal-option-row">
    <label class="aot-modal-option-label">{{cat}}</label>
    <div class="aot-modal-option-control">
      <label class="btn-toggle mb-0">
        <input type="checkbox" name="categories" value="{{cat}}" class="btn-toggle-input"{% if cat in widget_options.get('categories', []) %} checked{% endif %}>
        <div class="btn-toggle-slider">
          <div class="btn-toggle-thumb"></div>
        </div>
      </label>
    </div>
  </div>
    {% endfor %}
  {% else %}
  <div class="aot-modal-option-row aot-full-width-row">
    <div class="text-muted small">{{_('No categories yet. Set one when creating a post to filter by it here.')}}</div>
  </div>
  {% endif %}
</div>""",

    'widget_dashboard_head': """{% if "aot_notice_render" not in dashboard_dict %}
  <script src="{{ asset('app-notice-render') }}"></script>
  {% set _dummy = dashboard_dict.update({"aot_notice_render": 1}) %}
{% endif %}
<style>
  /* Fills #container-graph exactly (100% + overflow:hidden) so this widget's
     own content can never exceed the gridstack card's box. Without this, the
     scrollable list + the footer below it (two block siblings) add up to
     more than 100% height, tripping GridStack's own
     .grid-stack-item-content{overflow-y:auto} on top of our inner scroll —
     a double scrollbar that persists no matter how large the card is resized. */
  .aot-notice-widget-outer { height: 100%; display: flex; flex-flow: column; overflow: hidden; }
  .aot-notice-widget-container { padding: 8px; flex: 1 1 auto; overflow-y: auto; }
  .aot-notice-widget-post {
    border: 1px solid var(--border-neutral, #e9ecef);
    border-radius: 8px;
    padding: 8px;
    margin-bottom: 8px;
    background: var(--aot-surface-card, #fff);
  }
  .aot-notice-widget-post:last-child { margin-bottom: 0; }
  .aot-notice-widget-title {
    font-weight: 700; font-size: var(--aot-font-size-sm);
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }
  .aot-notice-widget-title a {
    color: inherit; text-decoration: none; cursor: pointer;
    display: block; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }
  .aot-notice-widget-title a:hover { text-decoration: underline; }
  .aot-notice-widget-meta { font-size: var(--aot-font-size-2xs); color: var(--aot-color-text-secondary, #6c757d); margin-top: 2px; }
  /* 분류 배지: 글자색을 본문색으로 올린다. 보조색(#5E6B64)을 밝은 칩 배경
     (#f1f3f5) 위 10.88px 로 쓰면 대비 4.41:1 로 AA(4.5:1)에 아슬하게 못 미쳤다.
     크기도 0.68rem 이라는 사다리 밖 값이었다 — 2xs(0.7rem)로 맞춘다. */
  .aot-notice-widget-category-badge {
    display: inline-block; font-size: var(--aot-font-size-2xs); font-weight: 700;
    padding: 0.1rem 0.5rem; border-radius: 9999px;
    background: var(--aot-surface-body, #f1f3f5); color: var(--aot-color-text-primary, #13261B);
  }

  .aot-notice-widget-modal-body {
    font-size: var(--aot-font-size-sm); line-height: 1.6; white-space: normal;
    color: var(--aot-color-text-primary, #212529);
  }
  .aot-notice-widget-modal-body .aot-notice-embed-video iframe { width: 100%; max-width: 480px; aspect-ratio: 16/9; border-radius: 0.5rem; }
  .aot-notice-widget-modal-body .aot-notice-embed-image img { max-width: 100%; border-radius: 0.5rem; }
  .aot-notice-link-preview {
    display: flex; align-items: center; gap: 0.6rem;
    border: 1px solid var(--border-neutral, #dee2e6);
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
    font-size: var(--aot-font-size-sm); padding: 0.4rem 0.6rem; border: 1px solid var(--border-neutral, #dee2e6);
    border-radius: 0.5rem; margin-bottom: 0.35rem; cursor: pointer;
  }
  .aot-notice-widget-poll-row.selected { border-color: var(--bd-tertiary, #13261B); background: var(--aot-surface-body, #f8f9fa); }
  .aot-notice-widget-poll-bar-track { height: 5px; border-radius: 3px; background: var(--aot-surface-body, #e9ecef); margin-top: 3px; overflow: hidden; }
  .aot-notice-widget-poll-bar-fill { height: 100%; background: var(--bd-tertiary, #13261B); }
  .aot-notice-widget-reply-item { padding: 0.4rem 0; border-bottom: 1px solid var(--border-neutral, #f1f1f1); font-size: var(--aot-font-size-sm); }
  .aot-notice-widget-reply-meta { font-size: var(--aot-font-size-2xs); color: var(--aot-color-text-secondary, #6c757d); }
  .aot-notice-widget-reply-input-row { display: flex; gap: 6px; margin-top: 0.5rem; }
  .aot-notice-widget-reply-input-row input { flex: 1; }

  textarea.aot-notice-textarea {
    border-radius: 8px !important;
    border: 1px solid var(--gray) !important;
    outline: none !important;
    white-space: normal !important;
    overflow-wrap: break-word !important;
    overflow-x: hidden !important;
    overflow-y: hidden !important;
    resize: none !important;
    min-height: 120px;
  }
  textarea.aot-notice-textarea:focus {
    /* Same neutral blue ring every modal already shows (--modal-focus-ring),
       WITHOUT swapping the border to the brand yellow .aot-modern-input uses —
       that yellow is reserved for buttons/actions, not text input borders. */
    border-color: var(--gray) !important;
    box-shadow: 0 0 0 0.15rem var(--modal-focus-ring) !important;
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
{% if permission_edit_settings %}
<div class="widget-map-controls" id="notice-widget-header-controls-{{each_widget.unique_id}}">
    <a class="aot-w-tool widget-map-ctrl-btn" id="notice-widget-new-btn-{{each_widget.unique_id}}"
       role="button" tabindex="0" aria-label="{{_('New Post')}}" title="{{_('New Post')}}">
        <i class="fas fa-plus"></i>
    </a>
</div>
{% endif %}
""",

    'widget_dashboard_body': """
<div class="aot-notice-widget-outer">
  <div id="notice-widget-{{each_widget.unique_id}}" class="aot-notice-widget-container">
    <div class="text-muted small">{{_('Loading...')}}</div>
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
    $container.html('<div class="text-muted small">{{_('No notices yet.')}}</div>');
    return;
  }
  var html = '';
  data.posts.forEach(function (post) {
    html += '<div class="aot-notice-widget-post">' +
      '<div class="aot-notice-widget-title"><a href="#" class="aot-notice-widget-open" data-post="' + post.unique_id + '">' +
      (post.pinned ? '[{{_('Pinned')}}] ' : '') +
      (post.category ? '<span class="aot-notice-widget-category-badge">' + esc(post.category) + '</span> ' : '') +
      esc(post.title) + '</a></div>' +
      '<div class="aot-notice-widget-meta">' + esc(post.date_time) + '</div>' +
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

function aotNoticeWidgetBuildModalBody(post, showPoll, showReply, currentUserId, isAdmin) {
  var esc = AoTNoticeRender.escapeHtml;
  var html = '<div class="small text-muted mb-2">' +
    (post.category ? '<span class="aot-notice-widget-category-badge mr-1">' + esc(post.category) + '</span>' : '') +
    esc(post.author) + ' &middot; ' + esc(post.date_time) + '</div>';
  html += '<div class="aot-notice-widget-modal-body">' + AoTNoticeRender.renderNoticeBody(post.body || '') + '</div>';

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

function aotNoticeWidgetInit(widgetId, limit, refreshSeconds, showPoll, showReply, currentUserId, isAdmin, categories) {
  aotNoticeWidgetFetchList(widgetId, limit, categories);
  // Store the refresh interval per widget and clear the previous one so a
  // live-preview re-init (option change without page reload) doesn't stack
  // duplicate fetch intervals.
  window._notice_intervals = window._notice_intervals || {};
  if (window._notice_intervals[widgetId]) { clearInterval(window._notice_intervals[widgetId]); }
  window._notice_intervals[widgetId] = setInterval(function () { aotNoticeWidgetFetchList(widgetId, limit, categories); }, refreshSeconds * 1000);

  var $list = $('#notice-widget-' + widgetId);
  var $modal = $('#notice-widget-modal-' + widgetId);
  var $modalContent = $('#notice-widget-modal-content-' + widgetId);
  var $composeForm = $('#notice-widget-compose-form-' + widgetId);

  // Idempotent re-init: clear this widget's previously bound handlers (namespace
  // .aotnw) before re-binding, so a live-preview re-init doesn't double-bind on
  // the modals that fixModalZIndex moved to <body> (and thus survive a body swap).
  $list.off('.aotnw'); $modal.off('.aotnw'); $modalContent.off('.aotnw');
  $composeForm.off('.aotnw'); $('#notice-widget-new-btn-' + widgetId).off('.aotnw');

  $list.on('click.aotnw', '.aot-notice-widget-open', function (e) {
    e.preventDefault();
    aotNoticeWidgetOpenModal(widgetId, $(this).data('post'), showPoll, showReply, currentUserId, isAdmin);
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
  {{widget_options['post_count']}},
  {{widget_options['refresh_seconds']}},
  {{widget_options['show_poll']|lower}},
  {{widget_options['show_reply_box']|lower}},
  {{ current_user.id if current_user.is_authenticated else 'null' }},
  {{ 'true' if current_user.is_authenticated and current_user.role_id == 1 else 'false' }},
  {{ widget_options.get('categories', []) | tojson }}
);
"""
}
