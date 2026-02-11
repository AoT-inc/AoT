from flask import Blueprint, jsonify, request, current_app
from flask_babel import gettext as _
from flask_login import login_required, current_user
from datetime import datetime
import uuid
from aot.databases.models import Notes, NoteTags
from aot.aot_flask.extensions import db
from aot.aot_flask.utils import utils_general
from aot.config import PATH_NOTE_ATTACHMENTS

blueprint = Blueprint('routes_notes_api', __name__)

@blueprint.route('/notes/target/<target_id>', methods=['GET'])
@login_required
def api_notes_target_get(target_id):
    """Get notes for a specific target (device, etc.)"""
    try:
        # [Fix] Filter by target_id.
        # Note: notes table now has target_id column
        notes = Notes.query.filter_by(target_id=target_id).order_by(Notes.date_time.desc()).all()
        
        result = []
        for n in notes:
            result.append({
                'unique_id': n.unique_id,
                'note': n.note,
                'date_time': n.date_time.isoformat() if n.date_time else "", # React expects 'date_time'
                # [Fix] Return Author Name if available, else fallback to Note Name (Title)
                'user': n.author.name if n.author else (n.name or '?'), 
                'files': n.files,
                'tags': n.tags
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
                    
                    filename = secure_filename(file.filename)
                    
                    # [Security] Validate File Extension
                    ALLOWED_EXTENSIONS = {
                        'png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'svg',
                        'mp4', 'mov', 'avi', 'webm',
                        'txt', 'pdf', 'csv', 'xls', 'xlsx', 'doc', 'docx'
                    }
                    if '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS:
                        pass
                    else:
                        return jsonify({'error': f'File type not allowed: {filename}'}), 400

                    # Using UUID to avoid collisions
                    unique_id = str(uuid.uuid4())
                    unique_filename = f"{unique_id}_{filename}"
                    
                    # Create YYYY/MM directory structure
                    now = datetime.now()
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
            date_time=datetime.now(),
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
        
        if hidden_tag_id:
            # Naive text match for UUID in comma-separated list
            # Ideally we'd use a many-to-many table, but current implementation uses Text column
            query = query.filter(Notes.tags.notlike(f"%{hidden_tag_id}%"))
            
        notes = query.order_by(Notes.date_time.desc()).all()
        
        result = []
        for n in notes:
            result.append({
                'unique_id': n.unique_id,
                'note': n.note,
                'date_time': n.date_time.isoformat() if n.date_time else "",
                # [Fix] Return Author Name
                'user': n.author.name if n.author else (n.name or '?'),
                'files': n.files,
                'tags': n.tags,
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
            
        db.session.commit()
        return jsonify({'ok': True, 'unique_id': unique_id})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@blueprint.route('/notes/delete/<unique_id>', methods=['DELETE', 'POST'])
@login_required
def api_notes_delete(unique_id):
    """Delete a note"""
    try:
        if not utils_general.user_has_permission('edit_settings'):
            return jsonify({'error': 'Permission Denied'}), 403

        note = Notes.query.filter_by(unique_id=unique_id).first()
        if not note:
            return jsonify({'error': 'Note not found'}), 404
            
        db.session.delete(note)
        db.session.commit()
        return jsonify({'ok': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500
