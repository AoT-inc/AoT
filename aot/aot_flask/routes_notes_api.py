from flask import Blueprint, jsonify, request, current_app
from flask_babel import gettext as _
from flask_login import login_required, current_user
from datetime import datetime
from aot.utils.time_utils import utc_now, api_iso
import uuid
from sqlalchemy import or_
from aot.databases.models import Notes, NoteTags
from aot.aot_flask.extensions import db
from aot.aot_flask.utils import utils_general
from aot.config import PATH_NOTE_ATTACHMENTS

blueprint = Blueprint('routes_notes_api', __name__)

# Fallback map from upload MIME type → extension, used when the filename has no
# usable extension (e.g. a non-ASCII name that secure_filename strips bare).
_MIME_TO_EXT = {
    'image/jpeg': 'jpg', 'image/jpg': 'jpg', 'image/png': 'png',
    'image/gif': 'gif', 'image/webp': 'webp', 'image/bmp': 'bmp',
    'image/svg+xml': 'svg', 'image/heic': 'heic', 'image/heif': 'heif',
    'video/mp4': 'mp4', 'video/quicktime': 'mov', 'video/x-msvideo': 'avi',
    'video/webm': 'webm', 'application/pdf': 'pdf', 'text/plain': 'txt',
    'text/csv': 'csv',
}

def resolve_target_gps(target_type, target_id):
    """대상의 대표 좌표 (lat, lng). 못 구하면 (None, None).

    **좌표 해석을 여기 하나로 둔다.** 두 벌로 두면 한쪽에만 종류가 추가되고,
    그 경로로 남긴 노트만 좌표 없이 저장된다.
    에러가 안 나므로 몇 달 뒤 공간 질의에서 "그때 노트가 안 잡힌다" 로 나타난다.

    좌표가 필요한 이유는 대상이 **사라져도 자리는 남기 때문**이다. 식생 구획은
    몇 달 뒤 종료되지만 그 자리를 다시 물을 일이 있고(연작 장해·윤작),
    그때 노트를 찾는 근거는 좌표뿐이다.
    """
    if not target_id:
        return None, None

    if target_type == 'facility':
        try:
            from aot.databases.models import GeoFacility
            from aot.aot_flask.geo.facility_io import _geometry_centroid
            facility = GeoFacility.query.filter_by(unique_id=target_id).first()
            if facility and facility.shape:
                geom = (facility.shape.feature or {}).get('geometry')
                centroid = _geometry_centroid(geom)
                if centroid:
                    return centroid[0], centroid[1]
        except Exception as _e:
            current_app.logger.warning(f"facility centroid lookup failed: {_e}")
        return None, None

    if target_type == 'plot':
        try:
            from aot.databases.models import GeoPlot
            from aot.aot_flask.geo import plot_context
            from shapely.geometry import shape as _shapely_shape
            row = GeoPlot.query.filter_by(unique_id=target_id).first()
            if row is not None:
                geom = plot_context.geometry_of(row)
                if geom.get('type') in ('Polygon', 'MultiPolygon'):
                    # centroid 가 아니라 representative_point — 오목한 두둑에서
                    # centroid 는 구획 밖으로 나간다.
                    pt = _shapely_shape(geom).representative_point()
                    return pt.y, pt.x
        except Exception as _e:
            current_app.logger.warning(f"plot centroid lookup failed: {_e}")
        return None, None

    return None, None


def _display_name_for_target(tid):
    """노트가 붙은 대상의 사람이 읽을 이름. 못 찾으면 None.

    도형·식생·시설·장치가 각각 다른 테이블이라 한 곳에서 훑는다 — 부르는
    자리마다 따로 찾으면 어느 한 종류가 조용히 빠지고, 그 노트만 출처 없이
    목록에 섞인다.
    """
    if not tid:
        return None
    try:
        from aot.databases.models import GeoShape, GeoPlot, GeoFacility
        sh = GeoShape.query.filter_by(unique_id=tid).first()
        if sh is not None:
            feat = sh.feature if isinstance(sh.feature, dict) else {}
            props = (feat.get('properties') or {})
            return (props.get('name') or props.get('label')
                    or props.get('title') or None)
        pl = GeoPlot.query.filter_by(unique_id=tid).first()
        if pl is not None:
            return pl.name or pl.subject
        fac = GeoFacility.query.filter_by(unique_id=tid).first()
        if fac is not None:
            return getattr(fac, 'name', None)
        from aot.databases.models import Input, Output
        for model in (Input, Output):
            row = model.query.filter_by(unique_id=tid).first()
            if row is not None:
                return row.name
    except Exception:
        pass
    return None


@blueprint.route('/notes/target/<target_id>', methods=['GET'])
@login_required
def api_notes_target_get(target_id):
    """Get notes for a specific target (device, etc.).

    `?descendants=1` 이면 **그 안에서 쓴 노트 전부**를 함께 낸다(구역·시설·
    장치·식생). 컨테이너를 열었을 때 자기 것만 보이면 대부분 비어 있다 —
    실측(2026-08-18 김제): 필지 '3포장' 자체 노트 0건, 그 아래 16건.
    AI(`search_notes`)는 이미 자손을 훑고 있어서 **화면과 AI 가 다른 답**을
    하고 있었다.

    각 노트에 `target_name` 이 실린다 — 어느 구역·구획 것인지 구분되지 않으면
    합쳐 놓은 것이 오히려 혼란이 된다.
    """
    try:
        want_desc = request.args.get('descendants') in ('1', 'true', 'True')
        target_ids = [target_id]
        if want_desc:
            try:
                from aot.databases.models import GeoShape
                from aot.utils.geo_hierarchy import descendant_target_ids
                sh = GeoShape.query.filter_by(unique_id=target_id).first()
                if sh is None:
                    # 시설은 정체성이 둘이다 — 노트는 GeoFacility uuid 에
                    # 붙는데 기하는 도형 쪽이라, 도형으로 옮겨 풀어야 자손이 나온다.
                    from aot.databases.models import GeoFacility
                    fac = GeoFacility.query.filter_by(unique_id=target_id).first()
                    if fac is not None:
                        sh = GeoShape.query.filter_by(
                            unique_id=getattr(fac, 'shape_uuid', None)).first()
                if sh is not None:
                    more, _bd = descendant_target_ids(sh, include_self=False)
                    target_ids.extend(more)
            except Exception:
                current_app.logger.exception('notes: 자손 확장 실패')

        # [Fix] Filter by target_id.
        # Note: notes table now has target_id column
        notes = (Notes.query.filter(Notes.target_id.in_(target_ids))
                 .order_by(Notes.date_time.desc()).all())

        # All notes here share one target → its location tz. Emit it so the frontend
        # can render note times in that entity's local clock (AoTTz.formatDevice),
        # consistent with how the entity's schedules display. §7
        location_tz = None
        try:
            from aot.utils.device_tz import resolve_location_tz
            location_tz = str(resolve_location_tz(target_id))
        except Exception:
            location_tz = None

        # 구간→예정 링크를 **함께** 싣는다. 별도 조회로 두면 노트 수만큼
        # 왕복이 생기고(30건이면 30회), 목록이 먼저 그려진 뒤 하이라이트가
        # 뒤늦게 얹혀 글이 한 번 튄다.
        links_by_note = {}
        try:
            from aot.aot_flask import note_links
            links_by_note = note_links.links_for_notes(notes)
        except Exception:
            current_app.logger.exception('notes: 링크 조회 실패')

        result = []
        for n in notes:
            result.append({
                'unique_id': n.unique_id,
                'note': n.note,
                'date_time': api_iso(n.date_time) if n.date_time else "", # UTC+offset ISO so frontend parses absolute instant correctly
                'date_tz': location_tz,  # note's location tz for device-local display
                # [Fix] Return Author Name if available, else fallback to Note Name (Title)
                'user': n.author.name if n.author else (n.name or '?'), 
                'files': n.files,
                'tags': n.tags,
                'links': links_by_note.get(n.unique_id, []),
                # 어느 대상 것인지. 자손까지 합쳐 보여줄 때 이것이 없으면
                # 합친 목록이 오히려 혼란이 된다.
                'target_id': n.target_id,
                'target_name': (_display_name_for_target(n.target_id)
                                if n.target_id != target_id else None),
            })
            
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

from aot.aot_flask.extensions import db, csrf

@blueprint.route('/notes/create', methods=['POST'])
@login_required
@csrf.exempt
def api_notes_create():
    """Create a new note via API"""
    try:
        if not utils_general.user_has_permission('edit_settings'):
            return jsonify({'error': 'Permission Denied'}), 403
        
        # [Fix] Robust Data Extraction: Check both Form and JSON
        data = {}
        
        # 1. Attempt to gather Form Data (works for multipart/form-data and x-www-form-urlencoded)
        if request.form:
            data.update(request.form.to_dict())
            
        # 2. Attempt to gather JSON (if payload looks like JSON or if Form was empty)
        # Note: get_json(silent=True) returns None if parsing fails or not JSON
        json_val = request.get_json(silent=True) 
        if json_val:
            data.update(json_val)

        target_id = data.get('target_id')
        target_type = data.get('target_type')
        note_text = data.get('note')
        gps_lat = data.get('gps_lat')
        gps_lng = data.get('gps_lng')

        if gps_lat is None:
            gps_lat, gps_lng = resolve_target_gps(target_type, target_id)
        category = data.get('category', 'general')
        priority = int(data.get('priority', 0))
        
        # Handle File Uploads
        uploaded_files_paths = []
        if 'files' in request.files:
            files = request.files.getlist('files')
            for file in files:
                if file.filename:
                    # Save file logic (Simplified for MVP, save to static/uploads/notes)
                    import os
                    from werkzeug.utils import secure_filename
                    
                    # Derive the extension from the ORIGINAL filename, then fall
                    # back to the MIME type. secure_filename() strips non-ASCII
                    # names (e.g. Korean "사진.jpg") down to "jpg" with no dot,
                    # which then failed this check — so never trust its base for
                    # the extension.
                    orig_name = file.filename or ''
                    ext = orig_name.rsplit('.', 1)[1].lower() if '.' in orig_name else ''
                    if not ext:
                        ext = _MIME_TO_EXT.get((file.mimetype or '').lower(), '')

                    # [Security] Validate File Extension
                    ALLOWED_EXTENSIONS = {
                        'png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'svg',
                        'heic', 'heif',
                        'mp4', 'mov', 'avi', 'webm',
                        'txt', 'pdf', 'csv', 'xls', 'xlsx', 'doc', 'docx'
                    }
                    if ext not in ALLOWED_EXTENSIONS:
                        return jsonify({'error': f'File type not allowed: {orig_name or "unknown"}'}), 400

                    # Store under a clean UUID name + validated extension. The
                    # secure_filename base is empty for non-ASCII names, so we do
                    # NOT append it (that produced extension-less, broken files).
                    unique_id = str(uuid.uuid4())
                    unique_filename = f"{unique_id}.{ext}"
                    
                    # Create YYYY/MM directory structure (UTC for stable bucketing)
                    now = utc_now()
                    relative_path = os.path.join(now.strftime('%Y'), now.strftime('%m'))
                    full_upload_path = os.path.join(PATH_NOTE_ATTACHMENTS, relative_path)
                    
                    # Ensure path exists
                    if not os.path.exists(full_upload_path):
                        os.makedirs(full_upload_path, exist_ok=True)
                    
                    file_path = os.path.join(full_upload_path, unique_filename)
                    file.save(file_path)
                    
                    # Store relative path in DB (e.g., 2026/01/uuid_filename.jpg)
                    db_stored_path = os.path.join(relative_path, unique_filename)
                    uploaded_files_paths.append(db_stored_path)

        if not note_text and not uploaded_files_paths:
             return jsonify({'error': 'Note content or file required'}), 400

        # [Revised] Tag Resolution Logic
        # Incoming 'tags' is a string of names (e.g., "widget, Sensor A")
        # We need to store comma-separated unique_ids.
        tag_names = [t.strip() for t in data.get('tags', '').split(',') if t.strip()]
        if not tag_names:
            tag_names = ['widget']
            
        resolved_tag_ids = []
        for t_name in tag_names:
            existing_tag = NoteTags.query.filter_by(name=t_name).first()
            if existing_tag:
                resolved_tag_ids.append(existing_tag.unique_id)
            else:
                # Auto-create missing tag
                new_tag = NoteTags(name=t_name)
                # Note: NoteTags has unique_id with default=set_uuid
                db.session.add(new_tag)
                db.session.flush() # To get the generated unique_id
                resolved_tag_ids.append(new_tag.unique_id)


        # [Smart Subject] If name is generic or empty, extract from note body
        name_input = data.get('name', '').strip()
        final_name = name_input
        generic_titles = [_("New Note"), "Quick Note", "User"]
        if not final_name or any(gt in final_name for gt in generic_titles):
            body = note_text.strip() if note_text else ""
            if body:
                first_line = body.split('\n')[0].strip()
                if len(first_line) > 50:
                    first_line = first_line[:47] + "..."
                if first_line:
                    final_name = first_line
                elif not final_name:
                    final_name = _("New Note")
            elif not final_name:
                final_name = _("New Note")


        new_note = Notes(
            name=final_name,
            date_time=utc_now(),
            note=note_text.strip() if note_text else "",
            target_id=target_id,
            target_type=target_type,
            files=','.join(uploaded_files_paths) if uploaded_files_paths else None,
            unique_id=str(uuid.uuid4()),
            tags=','.join(resolved_tag_ids),
            gps_lat=gps_lat,
            gps_lng=gps_lng,
            category=category,
            priority=priority,
            # [Fix] Save User ID
            user_id=current_user.id if current_user.is_authenticated else None
        )
        
        db.session.add(new_note)
        db.session.commit()
        
        return jsonify({'ok': True, 'unique_id': new_note.unique_id})
        
    except Exception as e:
        import traceback
        error_msg = f"API Notes Create Error: {str(e)}\n{traceback.format_exc()}"
        try:
            current_app.logger.error(error_msg)
        except:
            pass
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

#: 지도에 **자기 표시가 이미 있는** 대상의 노트는 핀을 만들지 않는다.
#
# 구획·시설·구역·대지는 지도에 도형으로 그려져 있고, 그 도형을 누르면 모달에서
# 노트를 본다. 거기에 핀을 하나 더 얹으면 같은 자리를 두 번 가리키면서 지도만
# 어지럽힌다 — 사용자가 만들지 않은 표시이므로 지울 방법도 마땅치 않다.
#
# **좌표 자체는 계속 저장한다.** 좌표의 목적은 표시가 아니라 **대상이 사라져도
# 자리는 남기는 것**이다(식생 구획은 몇 달 뒤 종료되지만 그 자리를 다시 물을
# 일이 있고, 그때 노트를 찾는 근거는 좌표뿐이다 — resolve_target_gps 주석).
# 그래서 저장이 아니라 **노출**에서 가른다.
#
# 화이트리스트인 이유: 새 대상 종류가 생길 때 기본값이 "핀 없음" 이어야 한다.
# 블랙리스트로 두면 종류를 하나 추가할 때마다 여기 넣는 것을 기억해야 하고,
# 빠뜨리면 그 종류만 조용히 핀이 돋는다(지금 plot 이 그랬다).
_PIN_TARGET_TYPES = (
    'map_location',   # 사용자가 지도를 찍어 만든 노트 — 핀이 유일한 위치 표현
)


@blueprint.route('/notes/geo', methods=['GET'])
@login_required
def api_notes_geo_get():
    """Get notes that have GPS coordinates (for map display), excluding hidden ones"""
    try:
        # Resolve 'map_hidden' tag ID
        hidden_tag = NoteTags.query.filter_by(name='map_hidden').first()
        hidden_tag_id = hidden_tag.unique_id if hidden_tag else None

        # Filter where gps_lat is NOT NULL
        # [Fix] Filter out notes with map_hidden tag
        query = Notes.query.filter(Notes.gps_lat.isnot(None), Notes.gps_lng.isnot(None))

        # 자기 도형이 있는 대상의 노트는 뺀다(위 _PIN_TARGET_TYPES 주석).
        # target_type 이 비어 있는 노트는 남긴다 — 가리킬 도형이 없으므로
        # 핀이 그 노트의 유일한 위치 표현이다.
        query = query.filter(or_(
            Notes.target_type.is_(None),
            Notes.target_type == '',
            Notes.target_type.in_(_PIN_TARGET_TYPES),
        ))

        if hidden_tag_id:
            # Naive text match for UUID in comma-separated list
            # Ideally we'd use a many-to-many table, but current implementation uses Text column
            query = query.filter(Notes.tags.notlike(f"%{hidden_tag_id}%"))
            
        notes = query.order_by(Notes.date_time.desc()).all()
        
        # Prepare tag lookup
        all_tags = {t.unique_id: t.name for t in NoteTags.query.all()}

        result = []
        for n in notes:
            tag_ids = [t.strip() for t in (n.tags or "").split(',') if t.strip()]
            tag_objects = [{'unique_id': tid, 'name': all_tags.get(tid, 'Unknown')} for tid in tag_ids]
            
            result.append({
                'unique_id': n.unique_id,
                'note': n.note,
                'date_time': api_iso(n.date_time) if n.date_time else "",
                # [Fix] Return Author Name
                'user': n.author.name if n.author else (n.name or '?'),
                'files': n.files,
                'tags': n.tags,
                'tag_list': tag_objects, # [New] Detailed tag info
                'target_id': n.target_id,
                'target_type': n.target_type,
                'gps_lat': n.gps_lat,
                'gps_lng': n.gps_lng,
                'category': n.category,
                'priority': n.priority
            })
            
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@blueprint.route('/notes/toggle_map_visibility', methods=['POST'])
@login_required
@csrf.exempt
def api_notes_toggle_map_visibility():
    """Toggle visibility of notes on map (Grouped by target_id)"""
    try:
        data = request.get_json(force=True, silent=True) or {}
        unique_id = data.get('unique_id')
        visible = data.get('visible') # boolean
        
        if not unique_id:
            return jsonify({'error': 'unique_id required'}), 400
            
        # 1. Find the reference note
        ref_note = Notes.query.filter_by(unique_id=unique_id).first()
        if not ref_note:
            return jsonify({'error': 'Note not found'}), 404
            
        target_id = ref_note.target_id
        if not target_id:
             # If no target_id, just toggle this note
             target_notes = [ref_note]
        else:
             # Toggle all notes at this location
             target_notes = Notes.query.filter_by(target_id=target_id).all()
             
        # 2. Get/Create 'map_hidden' tag
        hidden_tag = NoteTags.query.filter_by(name='map_hidden').first()
        if not hidden_tag:
            hidden_tag = NoteTags(name='map_hidden')
            db.session.add(hidden_tag)
            db.session.flush()
        
        hidden_id = hidden_tag.unique_id
        
        # 3. Update tags for each note
        for note in target_notes:
            current_tags = [t.strip() for t in (note.tags or "").split(',') if t.strip()]
            
            if visible:
                # Remove hidden tag
                if hidden_id in current_tags:
                    current_tags.remove(hidden_id)
            else:
                # Add hidden tag
                if hidden_id not in current_tags:
                    current_tags.append(hidden_id)
            
            note.tags = ','.join(current_tags)
            
        db.session.commit()
        
        return jsonify({'ok': True, 'count': len(target_notes), 'visible': visible})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

# ─── 노트 구간 → 예정 (링크로 잇는다) ──────────────────────────────────────
#
# **진입점은 노트 하나다.** 예전에는 쓰기 전에 "노트인가 일정인가" 를 골라야
# 했는데, 그 구분은 저장 테이블 이름이지 사람이 아는 구분이 아니다. 이제
# 사용자는 노트만 쓰고, 쓴 뒤에 한 구간을 골라 시각을 준다.
#
# 정본 로직(재탐색·자가 치유·고아 판정)은 `aot/aot_flask/note_links.py` 하나에
# 있다 — 여기서 다시 구현하지 말 것.

@blueprint.route('/notes/<note_id>/links', methods=['GET'])
@login_required
def api_note_links(note_id):
    """이 노트에 걸린 예정들 (구간 위치 포함)."""
    from aot.aot_flask import note_links
    note = Notes.query.filter_by(unique_id=note_id).first()
    if not note:
        return jsonify({'error': 'Note not found'}), 404
    return jsonify({'ok': True, 'links': note_links.links_for_note(note)})


@blueprint.route('/notes/<note_id>/schedule', methods=['POST'])
@login_required
@csrf.exempt
def api_note_schedule(note_id):
    """선택한 구간을 예정으로 만든다.

    본문: `{start, end, text, date:'YYYY-MM-DD', time?:'HH:MM', worker?}`

    **내용을 따로 받지 않는다** — 사용자가 이미 고른 텍스트가 곧 내용이다.
    그것이 이 방식의 요점이고, 여기서 별도 입력을 받기 시작하면 노트와 일정이
    다시 서로 다른 글이 된다.

    대상(어디)은 **노트에서 승계한다.** 노트가 구획에 붙어 있으면 그 예정도
    같은 구획에 붙는다 — 사용자가 장소를 다시 고를 일이 없다.
    """
    if not utils_general.user_has_permission('edit_settings'):
        return jsonify({'error': 'Permission Denied'}), 403

    note = Notes.query.filter_by(unique_id=note_id).first()
    if not note:
        return jsonify({'error': 'Note not found'}), 404

    data = request.get_json(silent=True) or {}
    text = (data.get('text') or '').strip()
    date_str = (data.get('date') or '').strip()
    if not text:
        return jsonify({'ok': False, 'message': _('Select some text first')}), 400
    if not date_str:
        return jsonify({'ok': False, 'message': _('Enter a date')}), 400

    try:
        start = int(data.get('start') or 0)
        end = int(data.get('end') or 0)
    except (TypeError, ValueError):
        start = end = 0
    body = note.note or ''
    # 클라이언트가 준 offset 을 믿지 않는다 — 그 사이에 다른 창에서 노트가
    # 바뀌었을 수 있다. 실제 본문에서 확인하고, 어긋나면 텍스트로 다시 찾는다.
    if not (0 <= start < end <= len(body) and body[start:end] == text):
        idx = body.find(text)
        if idx < 0:
            return jsonify({'ok': False,
                            'message': _('That text is no longer in the note')}), 409
        start, end = idx, idx + len(text)

    from aot.aot_flask.routes_geo import (_create_human_schedule,
                                          _schedule_target_label)
    from aot.databases.models import NoteScheduleLink

    target_id = note.target_id or 'none'
    label, kind = _schedule_target_label(target_id)
    if label is None:
        # 대상이 없는(또는 이미 사라진) 노트도 예정을 가질 수 있다 — 그 경우
        # 장소 없는 일정이 된다. 거절하면 "어디" 를 안 적었다는 이유로 "언제"
        # 를 못 적게 된다.
        target_id, label, kind = 'none', (note.name or _('Note')), 'general'

    resp = _create_human_schedule(
        target_id, kind, label, date_str,
        (data.get('time') or '').strip(), text,
        (data.get('worker') or '').strip())
    payload = resp[0] if isinstance(resp, tuple) else resp
    body_json = payload.get_json() if hasattr(payload, 'get_json') else {}
    if not body_json.get('ok'):
        return resp

    try:
        link = NoteScheduleLink(
            note_id=note.unique_id, job_uid=body_json['job_id'],
            start_offset=start, end_offset=end, text_snapshot=text)
        db.session.add(link)
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception('note_links: 링크 생성 실패')
        return jsonify({'ok': False, 'message': str(exc)}), 500

    from aot.aot_flask import note_links as _nl
    return jsonify({'ok': True, 'link_id': link.unique_id,
                    'links': _nl.links_for_note(note)})


@blueprint.route('/notes/link/<link_id>', methods=['DELETE', 'POST'])
@login_required
@csrf.exempt
def api_note_link_delete(link_id):
    """링크를 끊는다. `?cancel_job=1` 이면 예정도 취소한다.

    **기본은 예정을 남기는 것.** 이미 잡힌 약속이 글 편집으로 조용히 사라지면
    안 된다 — 사람이 그러라고 말했을 때만 취소한다.
    """
    if not utils_general.user_has_permission('edit_settings'):
        return jsonify({'error': 'Permission Denied'}), 403

    from aot.aot_flask import note_links
    from aot.databases.models import NoteScheduleLink
    link = NoteScheduleLink.query.filter_by(unique_id=link_id).first()
    if not link:
        return jsonify({'error': 'Link not found'}), 404
    cancel = (request.args.get('cancel_job') in ('1', 'true', 'True')
              or (request.get_json(silent=True) or {}).get('cancel_job') is True)
    try:
        note_links.unlink(link, cancel_job=cancel)
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception('note_links: 링크 해제 실패')
        return jsonify({'ok': False, 'message': str(exc)}), 500
    return jsonify({'ok': True, 'cancelled': bool(cancel)})


@blueprint.route('/notes/<note_id>/orphaned', methods=['POST'])
@login_required
@csrf.exempt
def api_note_orphaned(note_id):
    """이 본문으로 저장하면 구간이 사라지는 예정들. 본문: `{note: '...'}`

    **저장 전에** 부른다 — 저장한 뒤 물으면 사용자는 이미 없어진 글을 보며
    무엇을 지웠는지 기억해내야 한다.
    """
    from aot.aot_flask import note_links
    note = Notes.query.filter_by(unique_id=note_id).first()
    if not note:
        return jsonify({'error': 'Note not found'}), 404
    data = request.get_json(silent=True) or {}
    return jsonify({'ok': True,
                    'orphaned': note_links.orphaned_after_edit(
                        note, data.get('note') or '')})


@blueprint.route('/notes/tags', methods=['GET'])
@login_required
def api_notes_tags_get():
    """Get all available note tags"""
    try:
        tags = NoteTags.query.all()
        result = [{'unique_id': t.unique_id, 'name': t.name} for t in tags]
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
@blueprint.route('/notes/update/<unique_id>', methods=['POST'])
@login_required
@csrf.exempt
def api_notes_update(unique_id):
    """Update an existing note (e.g. rename)"""
    try:
        note = Notes.query.filter_by(unique_id=unique_id).first()
        if not note:
            return jsonify({'error': 'Note not found'}), 404
            
        data = request.get_json(force=True, silent=True) or {}
        
        # Update fields if provided
        if 'name' in data:
            note.name = data['name']
        if 'note' in data:
            note.note = data['note']
            
        # [New] Handle Unique Tag Update
        # If 'new_tag_name' is provided, we replace the "unique" tag (non-widget, non-hidden)
        if 'new_tag_name' in data:
            new_name = data['new_tag_name'].strip()
            if new_name:
                # 1. Resolve/Create new tag
                new_tag = NoteTags.query.filter_by(name=new_name).first()
                if not new_tag:
                    new_tag = NoteTags(name=new_name)
                    db.session.add(new_tag)
                    db.session.flush()
                new_tag_id = new_tag.unique_id
                
                # 2. Identify all notes to update (Propagation)
                # If the note belongs to a thread, update the whole thread.
                target_id = note.target_id
                if target_id:
                    target_notes = Notes.query.filter_by(target_id=target_id).all()
                else:
                    target_notes = [note]

                # 3. Update current tags for each note
                reserved_names = ['widget', 'map_hidden']
                reserved_ids = [t.unique_id for t in NoteTags.query.filter(NoteTags.name.in_(reserved_names)).all()]
                
                for n_to_upd in target_notes:
                    current_tag_ids = [t.strip() for t in (n_to_upd.tags or "").split(',') if t.strip()]
                    new_tag_list = []
                    unique_tag_found = False
                    
                    for tid in current_tag_ids:
                        if tid not in reserved_ids:
                            if not unique_tag_found:
                                new_tag_list.append(new_tag_id)
                                unique_tag_found = True
                        else:
                            new_tag_list.append(tid)
                    
                    if not unique_tag_found:
                        new_tag_list.append(new_tag_id)
                    
                    n_to_upd.tags = ','.join(new_tag_list)
            
        db.session.commit()
        return jsonify({'ok': True, 'unique_id': unique_id})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@blueprint.route('/notes/delete/<unique_id>', methods=['DELETE', 'POST'])
@login_required
@csrf.exempt
def api_notes_delete(unique_id):
    """Delete a note"""
    try:
        if not utils_general.user_has_permission('edit_settings'):
            return jsonify({'error': 'Permission Denied'}), 403

        note = Notes.query.filter_by(unique_id=unique_id).first()
        if not note:
            return jsonify({'error': 'Note not found'}), 404

        # 링크를 함께 걷는다 — 노트가 없으면 링크는 아무 데서도 안 읽히는 채
        # DB 에 영원히 남는다. 예정 자체는 남긴다(다른 결정이다).
        from aot.aot_flask import note_links
        note_links.drop_for_note(unique_id)

        db.session.delete(note)
        db.session.commit()
        return jsonify({'ok': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500
