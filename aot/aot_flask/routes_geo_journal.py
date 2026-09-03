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


def _download_stem(row):
    """일지 행 → 내려받을 파일 이름의 몸통 — `YYYYMM_대상명`.

    ## 왜 uuid 가 아니라 이 형식인가

    예전에는 `journal-7944978c.md` 처럼 uuid 앞자리를 썼고, PDF 는 브라우저가
    `document.title`("AoT 설원6 - AoT 26.09.01")에서 따 갔다. 둘 다 **여러
    작기를 내려받으면 무엇이 무엇인지 알 수 없다** — 파일 이름은 폴더에서
    다시 열어 보지 않고도 골라낼 수 있어야 한다.

    `YYYYMM` 은 **기간 시작**이다(만든 날이 아니다) — 같은 구획을 나중에 다시
    뽑아도 같은 작기면 같은 이름이 나오는 편이 정렬에 맞는다.

    ⚠ 파일 이름에 못 쓰는 글자는 털어낸다. 한글은 그대로 둔다 — 대상 이름이
      한국어인 것이 정상이고, 로마자로 옮기면 사람이 못 알아본다.
    """
    stem = row.period_start.strftime('%Y%m') if row.period_start else ''
    name = (row.title or '').strip()
    # 경로 구분자·제어문자·따옴표류만 막는다(윈도·맥·리눅스 공통 금지 문자).
    for bad in '/\\:*?"<>|\r\n\t':
        name = name.replace(bad, '')
    name = ' '.join(name.split())          # 연속 공백 정리
    name = name.replace(' ', '_')
    if not name:
        name = 'journal'
    return ('%s_%s' % (stem, name)) if stem else name


def _disposition(stem, ext):
    """`Content-Disposition` 헤더 — 한글 파일명을 살린다.

    ⚠ HTTP 헤더는 **latin-1** 이라 `filename="설원6.md"` 는 그대로 못 싣는다
      (WSGI 가 인코딩에서 죽거나 글자가 깨진다). RFC 5987 의 `filename*` 로
      UTF-8 을 실어 보내고, 그것을 모르는 옛 클라이언트를 위해 ASCII 로만
      추린 `filename=` 을 함께 둔다 — 둘 다 있으면 최신 브라우저는 `filename*`
      을 고른다.
    """
    from urllib.parse import quote

    import re

    # 비-ASCII 를 걷어내면 `[관찰]` 이 `[]` 처럼 껍데기만 남는다 — 기호가
    # 이어진 자리를 밑줄 하나로 접어 읽을 수 있는 이름으로 만든다.
    ascii_stem = ''.join(c if (c.isascii() and c.isalnum()) else '_'
                         for c in stem)
    ascii_stem = re.sub(r'_+', '_', ascii_stem).strip('_') or 'journal'
    return ('attachment; filename="%s.%s"; filename*=UTF-8\'\'%s.%s'
            % (ascii_stem, ext, quote(stem, safe=''), ext))


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

    # 대지·구역 목록을 **농장(지도)별로** 묶는다.
    #
    # ⚠ 예전에는 템플릿이 "직전 항목과 `kind` 가 다르면 새 optgroup" 으로
    #   갈랐는데, `area_choices()` 는 이름순으로 정렬해 내므로 대지·구역이
    #   번갈아 나와 **20개 항목이 9개 그룹으로 쪼개졌다**(실측).
    #   그리고 사람이 기대하는 묶음은 종류가 아니라 농장이다 — 정작 농장
    #   이름은 그룹 머리가 아니라 항목 텍스트의 접두사에 들어가 있었다.
    #   한 농장 안에서는 대지(구역을 품는 쪽)를 먼저 놓는다.
    grouped = {}
    for choice in device_membership.area_choices():
        grouped.setdefault(choice.get('map_name') or '', []).append(choice)
    area_groups = []
    for map_name in sorted(grouped):
        items = sorted(grouped[map_name],
                       key=lambda c: (0 if c.get('kind') == 'site' else 1,
                                      str(c.get('shape_name') or c.get('item'))))
        area_groups.append((map_name, items))

    return render_template('pages/geo/journal.html',
                           journals=journals,
                           area_groups=area_groups)


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

    # 실을 측정값. **없으면 `None`** = 기본 규칙(진단 채널만 뺀다)이고, 빈
    # 리스트는 "아무것도 고르지 않았다" 라 그대로 거절한다 — 둘을 같게 다루면
    # 전부 끄고 만든 사람이 왜 빈 문서를 받았는지 알 수 없다.
    raw_meas = data.get('measurements')
    if isinstance(raw_meas, str):
        raw_meas = [m for m in raw_meas.split(',') if m.strip()]
    elif raw_meas is not None and not isinstance(raw_meas, (list, tuple)):
        raw_meas = None
    measurements = None
    if raw_meas is not None:
        measurements = [str(m).strip() for m in raw_meas if str(m).strip()]
        if not measurements:
            return _reject(gettext("Pick at least one measurement."))

    # 저장 단위. **없으면 예전과 같이 시스템이 정한다**(일 단위, 예산을 넘기면
    # 주간). 굵게 고르면 저장 문서와 화면이 그만큼 작아진다 — 다만 센서를 읽는
    # 양은 줄지 않는다(어느 단위든 시간별로 읽어 접는다). 화면이 그렇게 말한다.
    gran = (data.get('granularity') or '').strip() or None
    if gran is not None and gran not in ('day', 'week', 'month'):
        return _reject(gettext("Pick daily, weekly or monthly."))

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
            target_type, target_id, start, end, measurements=measurements)
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
    plot_journal.start_journal_build(row.unique_id,
                                     measurements=measurements,
                                     granularity=gran)

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

    if fmt in ('md', 'json', 'csv', 'odt') and not row.is_ready():
        # 아직 없는 문서를 빈 파일로 내려보내지 않는다 — 사용자는 그것을
        # "내용이 없는 일지" 로 읽는다.
        #
        # ⚠ 여기서 `_reject`(리다이렉트)를 쓰면 **다운로드를 요청했는데
        #   리다이렉트 본문에 409 가 붙은 응답**이 나간다. `format=md|json` 은
        #   명시적인 파일 요청이므로 기계가 읽을 수 있는 형태로 답한다.
        return jsonify({'ok': False, 'status': row.status,
                        'message': gettext(
                            "This journal is still being generated.")}), 409

    stem = _download_stem(row)

    if fmt == 'json':
        from flask import Response
        import json as _json
        body = _json.dumps(row.data, ensure_ascii=False, indent=2)
        return Response(
            body, mimetype='application/json',
            headers={'Content-Disposition': _disposition(stem, 'json')})

    # 열람 단위(§E) — 저장된 것보다 **굵게만** 볼 수 있다. 저장 단위보다 잘게
    # 요구하면 `fold_buckets` 가 그대로 돌려준다(없는 정보를 지어내지 않는다).
    stored = (row.data or {}).get('granularity') or 'day'
    view_gran = (request.args.get('granularity') or stored).lower()
    if view_gran not in plot_journal.VIEW_GRANULARITIES:
        view_gran = stored

    if fmt == 'md':
        from flask import Response
        text = plot_journal.render_plot_journal_markdown(
            row.data, granularity=view_gran)
        return Response(
            text, mimetype='text/markdown',
            headers={'Content-Disposition': _disposition(stem, 'md')})

    if fmt == 'csv':
        from flask import Response
        text = plot_journal.render_plot_journal_csv(
            row.data, granularity=view_gran)
        # ⚠ BOM 을 붙인다. 붙이지 않으면 Excel 이 UTF-8 을 못 알아보고 한글
        #   열·센서 이름이 전부 깨진다 — 표 계산으로 쓰라고 낸 파일이
        #   표 계산에서 못 읽히는 것이 이 형식의 가장 흔한 실패다.
        return Response(
            '\ufeff' + text, mimetype='text/csv',
            headers={'Content-Disposition': _disposition(stem, 'csv')})

    if fmt == 'odt':
        from flask import Response
        blob = plot_journal.render_plot_journal_odt(
            row.data, granularity=view_gran)
        return Response(
            blob, mimetype='application/vnd.oasis.opendocument.text',
            headers={'Content-Disposition': _disposition(stem, 'odt')})

    # caveat 키 → 뷰어 언어 문장. 여기서 번역하는 이유는 §7 의 title/summary
    # 와 같다 — 저장 시점 언어로 굳지 않게 열람할 때마다 만든다.
    #
    # `target_kind_label` 도 같은 이유로 여기서 만든다 — 저장된 `kind`
    # (원문 코드값)만 스냅샷에 있고, 사람이 읽는 라벨은 `_target_summary()`
    # 가 실행되는 백그라운드 생성 스레드에 요청 컨텍스트가 없어 저장 시점에
    # 만들면 영어로 굳는다(실제 브라우저 검증으로 발견).
    caveat_texts = {}
    glossary = []
    target_kind_label = None
    view_buckets = []
    stage_sections = []
    if row.is_ready():
        for key in (row.data.get('caveats') or []):
            caveat_texts[key] = plot_journal.caveat_text(key)
        target = row.data.get('target') or {}
        target_kind_label = plot_journal._target_kind_label(
            target.get('type'), target.get('kind'))

        # 접기·묶기는 **열람할 때마다 하는 순수 계산**이다 — 저장된 스냅샷은
        # 그대로 두므로 JSON·MCP 내보내기는 원본 그대로다(§C·§E).
        folded = plot_journal.fold_buckets(
            row.data.get('buckets') or [], to=view_gran, granularity=stored)
        for bucket in folded:
            view_buckets.append(dict(bucket, env_groups=(
                plot_journal.group_env_rows(bucket.get('env') or []))))

        # 단계별 실제 기록(지침 + 목표 대비 실측 + 노트 + 사진). 저장된 버킷을
        # 단계 구간으로 갈라 붙이는 순수 계산이라, 이 기능 이전에 만들어진
        # 일지도 열기만 하면 채워진다.
        stage_sections = plot_journal.stage_sections(row.data)

        # 용어집도 **열람 시점 계산**이다. 저장하면 생성 시점의 언어로 굳는다
        # (`caveat_text` 와 같은 이유), 그리고 이 기능 이전에 만든 일지도
        # 열기만 하면 설명이 붙는다.
        glossary = plot_journal.glossary_terms(row.data)

    # 저장 단위보다 잘게는 못 보므로 그 선택지는 **아예 내주지 않는다** —
    # 눌러도 아무 일 없는 버튼을 두면 고장으로 읽힌다.
    order = {'day': 0, 'week': 1, 'month': 2, 'all': 3}
    available = [g for g in plot_journal.VIEW_GRANULARITIES
                 if order[g] >= order.get(stored, 0)]

    return render_template('pages/geo/journal_view.html', journal=row,
                           caveat_texts=caveat_texts,
                           glossary=glossary,
                           target_kind_label=target_kind_label,
                           view_buckets=view_buckets,
                           stage_sections=stage_sections,
                           print_filename=stem,
                           # 16방위 이름은 번역 대상이라 요청 시점에 만든다.
                           compass=plot_journal.compass_label,
                           runtime_text=plot_journal.runtime_text,
                           view_granularity=view_gran,
                           granularities=available)


@blueprint.route('/geo/journal/<string:journal_uuid>', methods=['DELETE'])
@login_required
def geo_journal_delete(journal_uuid):
    """일지 하나 삭제.

    ## 왜 필요한가 (1차 범위에서 미룬 것을 되돌린 판단)

    초안은 삭제 UI 를 "이번 범위에서 의도적으로 미룬 것" 에 넣었는데, 실사용에서
    그 판단이 틀린 것으로 드러났다 — 기간을 잘못 잡아 **70% 가 "데이터 없음" 인
    문서**가 만들어졌고, 그것을 치울 방법이 없어 카드 목록에 영구히 남았다.
    되돌릴 수 없는 생성은 사용자가 시도 자체를 꺼리게 만든다.

    **노트도 함께 지운다** — `target_type='journal'` 로 붙은 추가 의견(§10)은
    그 일지가 사라지면 가리킬 대상이 없는 고아가 된다.
    """
    if not utils_general.user_has_permission('edit_plots'):
        return jsonify({'ok': False,
                        'message': gettext("Permission Denied")}), 403

    row = GeoJournal.query.filter_by(unique_id=journal_uuid).first()
    if row is None:
        return jsonify({'ok': False,
                        'message': gettext("Journal not found.")}), 404

    # ⚠ **거부·부재 판정이 부수 효과보다 먼저다.** 노트를 먼저 지우고 나서
    #   실패하면 일지는 남았는데 그 의견만 사라진 부분 변경이 된다.
    from aot.databases.models import Notes
    try:
        Notes.query.filter_by(target_type='journal',
                              target_id=journal_uuid).delete()
        db.session.delete(row)
        db.session.commit()
    except Exception:
        db.session.rollback()
        logger.exception('[journal] 삭제 실패: %s', journal_uuid)
        return jsonify({'ok': False, 'message': gettext(
            "Could not delete this journal.")}), 500

    return jsonify({'ok': True})


@blueprint.route('/geo/journal/target_info', methods=['GET'])
@login_required
def geo_journal_target_info():
    """`?target_type=&target_id=` → 그 대상의 **기간 하한과 측정값 선택지**.

    둘을 한 번에 내는 이유는 화면이 대상을 고를 때 **같은 시점에** 둘 다
    필요하기 때문이다 — 따로 두면 왕복이 둘이 되고, 한쪽만 실패했을 때
    화면이 어중간한 상태가 된다.

    ## 왜 필요한가

    구획은 `started_on`/`ended_on` 이 있어 기간을 자동으로 채울 수 있지만,
    대지·구역에는 그런 날짜가 없다. 그래서 사람이 감으로 기간을 넣었고 실측에서
    **10개 버킷 중 7개가 빈** 문서가 나왔다. 자료가 언제부터 있는지는 시스템이
    아는 사실이므로 사람에게 추측시킬 이유가 없다.

    첫 관측 시각만 알면 되므로 채널마다 `first()` 한 번씩만 묻는다. **실패하면
    조용히 비운다** — 이건 편의 기능이라, 못 채웠다고 생성을 막으면 원래 되던
    일이 안 되게 된다.
    """
    target_type = (request.args.get('target_type') or '').strip()
    target_id = (request.args.get('target_id') or '').strip()
    if target_type not in ('plot', 'zone', 'site') or not target_id:
        return jsonify({'ok': False, 'message': gettext(
            "Select what the journal is about.")}), 400

    try:
        first_at = plot_journal.first_data_at(target_type, target_id)
    except Exception:
        logger.exception('[journal] 자료 시작 시각 조회 실패: %s', target_id)
        first_at = None

    try:
        measurements = plot_journal.available_measurements(
            target_type, target_id)
    except Exception:
        logger.exception('[journal] 측정값 목록 조회 실패: %s', target_id)
        measurements = []

    # 실내 센서가 하나도 없는 구획이면 화면이 "포함할 **기상대** 측정값" 이라고
    # 말한다 — 어디서 잰 값인지가 고르는 판단에 들어간다.
    try:
        weather_only = plot_journal.measurements_are_weather_only(
            target_type, target_id)
    except Exception:
        weather_only = False

    return jsonify({'ok': True,
                    'first_date': first_at.isoformat() if first_at else None,
                    'weather_only': weather_only,
                    'measurements': measurements})
