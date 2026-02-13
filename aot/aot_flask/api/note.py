# coding=utf-8
import logging
import traceback

import flask_login
from flask_accept import accept
from flask_restx import Resource, abort, fields
from flask_babel import gettext as _

from aot.databases.models import NoteTags
from aot.databases.models import Notes
from aot.aot_flask.api import api, default_responses
from aot.aot_flask.utils import utils_general

logger = logging.getLogger(__name__)

ns_note = api.namespace(
    'notes', description='Note operations')

note_create_fields = ns_note.model('Note Creation Fields', {
    'tags': fields.String(
        description='List of tag names, separated by commas',
        required=True,
        example='tag1,tag2,tag3'),
    'name': fields.String(
        description='The note name.',
        required=True,
        example='Note Name'),
    'note': fields.String(
        description='The note text.',
        required=True,
        example='My Note.'),
    'target_id': fields.String(
        description='The unique_id of the target entity (device, site, zone)',
        required=False,
        example='uuid-string'),
    'target_type': fields.String(
        description='The type of the target entity',
        required=False,
        example='device'),
    'gps_lat': fields.Float(
        description='GPS Latitude',
        required=False,
        example=37.12345),
    'gps_lng': fields.Float(
        description='GPS Longitude',
        required=False,
        example=127.12345)
})


@ns_note.route('/create')
@ns_note.doc(
    security='apikey',
    responses=default_responses
)
class MeasurementsCreate(Resource):
    """Interacts with Notes in the SQL database."""

    @accept('application/vnd.aot.v1+json')
    @ns_note.expect(note_create_fields)
    @flask_login.login_required
    def post(self):
        """Create a note."""
        if not utils_general.user_has_permission('edit_controllers'):
            abort(403)

        tags = None
        name = None
        note = None
        target_id = None
        target_type = None
        gps_lat = None
        gps_lng = None

        if ns_note.payload:
            if 'tags' in ns_note.payload:
                tags = ns_note.payload["tags"]
                if tags is not None:
                    try:
                        tags = tags.split(",")
                    except Exception:
                        abort(422, message='tags must represent comma separated tags')

            if 'name' in ns_note.payload:
                name = ns_note.payload["name"]
                if name is not None:
                    try:
                        name = str(name)
                    except Exception:
                        abort(422, message='name must represent a string')

            if 'note' in ns_note.payload:
                note = ns_note.payload["note"]
                if note is not None:
                    try:
                        note = str(note)
                    except Exception:
                        abort(422, message='note must represent a string')

            if 'target_id' in ns_note.payload:
                target_id = ns_note.payload["target_id"]

            if 'target_type' in ns_note.payload:
                target_type = ns_note.payload["target_type"]

            if 'gps_lat' in ns_note.payload:
                gps_lat = ns_note.payload["gps_lat"]

            if 'gps_lng' in ns_note.payload:
                gps_lng = ns_note.payload["gps_lng"]

        try:
            error = []
            list_tags = []

            new_note = Notes()

            for each_tag in tags:
                check_tag = NoteTags.query.filter(
                    NoteTags.unique_id == each_tag).first()
                if not check_tag:
                    error.append("Invalid tag: {}".format(each_tag))
                else:
                    list_tags.append(check_tag.unique_id)
            new_note.tags = ",".join(list_tags)

            if not error:
                # [Smart Subject] If name is generic or empty, extract from note body
                final_name = name.strip() if name else ""
                if not final_name or final_name == _("New Note"):
                    body = note.strip() if note else ""
                    if body:
                        # Take the first line, limit to 50 chars
                        first_line = body.split('\n')[0].strip()
                        if len(first_line) > 50:
                            first_line = first_line[:47] + "..."
                        final_name = first_line if first_line else _("New Note")
                    else:
                        final_name = _("New Note")
                
                new_note.name = final_name
                new_note.note = note
                new_note.target_id = target_id
                new_note.target_type = target_type
                new_note.gps_lat = gps_lat
                new_note.gps_lng = gps_lng
                new_note.save()
            else:
                abort(500,
                      message=f'Errors: {", ".join(error)}')

            return {'message': 'Success'}, 200
        except Exception:
            abort(500,
                  message='An exception occurred',
                  error=traceback.format_exc())


@ns_note.route('/target/<string:target_id>')
class NotesByTarget(Resource):
    """Get notes for a specific target."""

    @accept('application/vnd.aot.v1+json')
    @flask_login.login_required
    def get(self, target_id):
        """Get all notes associated with a specific target_id."""
        try:
            notes = Notes.query.filter_by(target_id=target_id).order_by(Notes.date_time.desc()).all()
            
            result = []
            for n in notes:
                result.append({
                    'unique_id': n.unique_id,
                    'date_time': n.date_time.isoformat(),
                    'name': n.name,
                    'note': n.note,
                    'tags': n.tags,
                    'files': n.files,
                    'target_id': n.target_id,
                    'target_type': n.target_type,
                    'gps_lat': n.gps_lat,
                    'gps_lng': n.gps_lng
                })
            
            return result, 200
        except Exception:
            abort(500, message='An exception occurred', error=traceback.format_exc())


@ns_note.route('/geo')
class NotesGeo(Resource):
    """Get notes that have GPS coordinates."""

    @ns_note.doc(responses=default_responses)
    @flask_login.login_required
    def get(self):
        """Get all notes with GPS coordinates for map display"""
        try:
            notes = Notes.query.filter(Notes.gps_lat.isnot(None), Notes.gps_lng.isnot(None)).order_by(Notes.date_time.desc()).all()
            
            result = []
            for n in notes:
                result.append({
                    'unique_id': n.unique_id,
                    'note': n.note,
                    'date_time': n.date_time.isoformat(),
                    'user': n.author.name if n.author else (n.name or '?'),
                    'files': n.files,
                    'tags': n.tags,
                    'target_id': n.target_id,
                    'target_type': n.target_type,
                    'gps_lat': n.gps_lat,
                    'gps_lng': n.gps_lng
                })
            return result, 200
        except Exception:
            abort(500, message='An exception occurred', error=traceback.format_exc())

@ns_note.route('/tags')
class NoteTagsList(Resource):
    """Get all note tags."""

    @ns_note.doc(responses=default_responses)
    @flask_login.login_required
    def get(self):
        """Get all available note tags"""
        try:
            tags = NoteTags.query.all()
            result = [{'unique_id': t.unique_id, 'name': t.name} for t in tags]
            return result, 200
        except Exception:
            abort(500, message='An exception occurred', error=traceback.format_exc())
