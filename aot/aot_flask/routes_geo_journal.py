# coding=utf-8
"""구획·구역 일지(Journal) 라우트 — routes_geo 의 서브모듈.

routes_geo.py 맨 아래에서 import 되어 공유 blueprint 에 등록된다
(routes_geo_plot / routes_geo_iec 와 같은 방식).

설계 정본: 일지 기능 계획서 §8·§13

## 이 파일이 지키는 두 가지

1. **집계는 요청 스레드에서 돌지 않는다.** 채널마다 InfluxDB 쿼리가 나가는
   작업이라, 저사양 기기(라즈베리파이 — 데몬과 같은 기기 위에서 웹이 돈다)
   에서 요청 스레드로 돌리면 그동안 다른 요청과 데몬 동작이 함께 굶는다.
   `status='pending'` 행을 먼저 만들고 permalink 로 바로 보낸다.

2. **거절은 시작하기 전에 한다.** 범위가 너무 크면 400 으로 돌려보내고 집계를
   **아예 시작하지 않는다**. 몰래 일부만 잘라 보여주지 않는다 — 무엇을 뺐는지
   모르는 채로 "됐다" 고 말하는 것이 이 저장소가 반복해서 겪은 실패다.
"""
import logging
from datetime import datetime

from flask import (abort, flash, jsonify, redirect, render_template,
                   request, url_for)
from flask_babel import gettext
from flask_login import current_user, login_required

from aot.aot_flask.extensions import db
from aot.aot_flask.geo import plot_journal
from aot.aot_flask.routes_geo import blueprint  # noqa: E402
from aot.aot_flask.utils import utils_general
from aot.databases.models import GeoJournal

logger = logging.getLogger(__name__)

#: 카드 목록 상한. 페이지네이션은 이번 범위 밖 — 늘어나면 그때 붙인다.
_CARD_LIMIT = 50


def _parse_date(value):
    """'YYYY-MM-DD' → date | None."""
    if not value:
        return None
    try:
        return datetime.strptime(str(value)[:10], '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return None


def _reject(message, code=400):
    """폼 제출과 fetch 를 **같은 판정으로** 거절한다.

    화면이 폼을 쓰는지 fetch 를 쓰는지에 따라 게이트가 갈리면, 한쪽 경로에서만
    상한이 새어 나간다 — 이 저장소가 위젯 미인증 경로에서 겪은 것과 같은
    모양이다. 여기서 응답 형식만 바꾸고 판정은 한 곳에 둔다.
    """
    if request.accept_mimetypes.best == 'application/json' or request.is_json:
        return jsonify({'ok': False, 'message': message}), code
    flash(message, 'error')
    return redirect(url_for('routes_geo.geo_journal_hub')), code


@blueprint.route('/geo/journal/plot_history', methods=['GET'])
@login_required
def geo_journal_plot_history():
    """`?area_id=<GeoShape uuid>` → 그 자리의 작기 이력 → 대상 드릴다운(§7)이 쓴다.

    노지·시설 구분 없이 `plot_context.plots_overlapping()` 하나로 낸다 —
    `geometry_of()`가 시설 구획에 시설 외피를 파생해 주므로 시설 구획도 그대로
    잡힌다(§7, `facility_plot_history()`를 폐기한 이유).

    지도 기하가 아예 없는 시설(중심·치수 미입력)은 교차 판정에서 빠진다 —
    별도 조회 경로를 만들지 않고 `note` 로 그 사실만 알린다.
    """
    from aot.aot_flask.geo import plot_context
    from aot.databases.models import GeoShape

    area_id = (request.args.get('area_id') or '').strip()
    shape = GeoShape.query.filter_by(unique_id=area_id).first()
    if shape is None:
        return jsonify({'ok': False, 'message': gettext(
            "Could not find that area.")}), 404

    geom = plot_context.geometry_of(shape)
    pairs = plot_context.plots_overlapping(shape.geo_id, geom)

    plots = []
    for row, _overlap in pairs:
        end = row.ended_on or row.expected_end_on
        plots.append({
            'unique_id': row.unique_id,
            'label': row.name or row.subject,
            'variety': row.variety,
            'kind': row.kind or 'vegetation',
            'started_on': row.started_on.isoformat() if row.started_on else None,
            'ended_on': row.ended_on.isoformat() if row.ended_on else None,
            'expected_end_on': (row.expected_end_on.isoformat()
                                if row.expected_end_on else None),
            'ongoing': row.ended_on is None,
        })

    return jsonify({'ok': True, 'plots': plots,
                    'note': gettext(
                        "Facilities without a mapped location won't appear "
                        "here — add their location in Facility settings "
                        "first.")})


@blueprint.route('/geo/journal', methods=['GET'])
@login_required
def geo_journal_hub():
    """일지 허브 — 대상·기간 선택 폼 + 저장된 일지 카드 목록(최신순).

    진입할 때 **갇힌 'running' 행을 먼저 회수한다**(§13d). 빌드 중 프로세스가
    재시작되면 그 행이 영원히 'running' 으로 남아 "잠시 후 새로고침" 을 영원히
    말하게 되는데, 사용자가 그것을 알아챌 자리가 바로 이 목록이다.
    """
    try:
        reclaimed = plot_journal.reclaim_stale_builds()
        if reclaimed:
            logger.info('[journal] 중단된 빌드 %d건을 회수했습니다', reclaimed)
    except Exception:
        # 회수 실패가 목록 자체를 막지는 않는다 — 목록이 이 페이지의 본체다.
        logger.exception('[journal] 갇힌 빌드 회수 실패')

    # `data`(수 MB 가 될 수 있다)는 목록에 필요 없다 — 컬럼을 골라 읽는다.
    rows = (GeoJournal.query
            .with_entities(GeoJournal.unique_id, GeoJournal.title,
                           GeoJournal.summary, GeoJournal.status,
                           GeoJournal.period_start, GeoJournal.period_end,
                           GeoJournal.created_at)
            .order_by(GeoJournal.created_at.desc())
            .limit(_CARD_LIMIT).all())
    journals = [{'unique_id': r[0], 'title': r[1], 'summary': r[2],
                 'status': r[3], 'period_start': r[4], 'period_end': r[5],
                 'created_at': r[6]} for r in rows]

    from aot.aot_flask.geo import device_membership

    return render_template('pages/geo/journal.html',
                           journals=journals,
                           area_choices=device_membership.area_choices())


@blueprint.route('/geo/journal', methods=['POST'])
@login_required
def geo_journal_create():
    """일지 생성 — 검증 → pending 행 → 백그라운드 → permalink 로 리다이렉트.

    **행을 만들기 전에 검증한다.** 실패한 요청까지 행을 남기면 카드 목록이
    쓰레기로 쌓이고, 사용자는 자기가 만든 것과 시스템이 거절한 것을 구분하지
    못한다.
    """
    if not utils_general.user_has_permission('edit_plots'):
        return _reject(gettext("Permission Denied"), 403)

    data = request.get_json(silent=True) or request.form
    target_type = (data.get('target_type') or '').strip()
    target_id = (data.get('target_id') or '').strip()
    start = _parse_date(data.get('start'))
    end = _parse_date(data.get('end'))

    if target_type not in ('plot', 'zone', 'site'):
        return _reject(gettext("Select what the journal is about."))
    if not target_id:
        return _reject(gettext("Select what the journal is about."))
    if start is None or end is None:
        return _reject(gettext("Enter both a start and an end date."))
    if start > end:
        return _reject(gettext("The start date is after the end date."))

    # ── §13a 승인 게이트 — 여기서 거절하면 집계는 시작조차 하지 않는다 ────
    try:
        cost = plot_journal.estimate_journal_cost(
            target_type, target_id, start, end)
    except ValueError as exc:
        # ⚠ **내부 예외 문구를 그대로 내보내지 않는다.** 그 문자열은 한국어로
        #   박혀 있고(22개 로케일 중 하나만 맞다) uuid 까지 들어 있다. 사용자
        #   에게는 번역된 문장을, 원인은 로그에 남긴다.
        logger.info('[journal] 대상 해소 실패: %s', exc)
        return _reject(gettext("Could not find what this journal is about."))
    except Exception:
        logger.exception('[journal] 비용 산정 실패')
        return _reject(gettext("Could not read this target."), 500)

    if not cost['ok']:
        if cost['reason'] == 'period-too-long':
            msg = gettext(
                "That period is too long (%(days)s days). "
                "Try a shorter period.", days=cost['days'])
        elif cost['reason'] == 'too-many-channels':
            msg = gettext(
                "That selection has too many devices (%(n)s channels). "
                "Narrow the area, or pick a single plot instead.",
                n=cost['env_channels'] + cost['control_channels'])
        else:
            msg = gettext(
                "That selection would read too much data. "
                "Try a shorter period or a narrower area.")
        return _reject(msg)

    row = GeoJournal(
        target_type=target_type,
        target_id=target_id,
        period_start=start,
        period_end=end,
        title='',                       # 완성될 때 채운다(§7)
        status='pending',
        created_by=getattr(current_user, 'id', None))
    db.session.add(row)
    db.session.commit()

    # 커밋 뒤에 띄운다 — 백그라운드가 아직 없는 행을 읽으러 갈 수 있다.
    plot_journal.start_journal_build(row.unique_id)

    if request.is_json:
        return jsonify({'ok': True, 'unique_id': row.unique_id,
                        'url': url_for('routes_geo.geo_journal_view',
                                       journal_uuid=row.unique_id)})
    return redirect(url_for('routes_geo.geo_journal_view',
                            journal_uuid=row.unique_id))


@blueprint.route('/geo/journal/<string:journal_uuid>', methods=['GET'])
@login_required
def geo_journal_view(journal_uuid):
    """개별 일지 — `?format=html|md|json`(기본 html).

    **저장된 스냅샷을 읽기만 한다.** 다시 계산하지 않는 것이 이 기능의 계약이다
    (§1) — 나중에 배선이나 프로그램이 바뀌어도 저장된 일지는 그때 사실 그대로
    남아야 한다.
    """
    row = GeoJournal.query.filter_by(unique_id=journal_uuid).first()
    if row is None:
        return abort(404)

    fmt = (request.args.get('format') or 'html').lower()

    if fmt in ('md', 'json') and not row.is_ready():
        # 아직 없는 문서를 빈 파일로 내려보내지 않는다 — 사용자는 그것을
        # "내용이 없는 일지" 로 읽는다.
        #
        # ⚠ 여기서 `_reject`(리다이렉트)를 쓰면 **다운로드를 요청했는데
        #   리다이렉트 본문에 409 가 붙은 응답**이 나간다. `format=md|json` 은
        #   명시적인 파일 요청이므로 기계가 읽을 수 있는 형태로 답한다.
        return jsonify({'ok': False, 'status': row.status,
                        'message': gettext(
                            "This journal is still being generated.")}), 409

    if fmt == 'json':
        from flask import Response
        import json as _json
        body = _json.dumps(row.data, ensure_ascii=False, indent=2)
        return Response(
            body, mimetype='application/json',
            headers={'Content-Disposition':
                     'attachment; filename="journal-%s.json"' % journal_uuid[:8]})

    if fmt == 'md':
        from flask import Response
        text = plot_journal.render_plot_journal_markdown(row.data)
        return Response(
            text, mimetype='text/markdown',
            headers={'Content-Disposition':
                     'attachment; filename="journal-%s.md"' % journal_uuid[:8]})

    # caveat 키 → 뷰어 언어 문장. 여기서 번역하는 이유는 §7 의 title/summary
    # 와 같다 — 저장 시점 언어로 굳지 않게 열람할 때마다 만든다.
    caveat_texts = {}
    if row.is_ready():
        for key in (row.data.get('caveats') or []):
            caveat_texts[key] = plot_journal.caveat_text(key)

    return render_template('pages/geo/journal_view.html', journal=row,
                           caveat_texts=caveat_texts)
