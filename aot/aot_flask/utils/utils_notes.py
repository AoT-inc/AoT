# -*- coding: utf-8 -*-
import csv
import glob
import io
import logging
import os
import shutil
import socket
import time
import uuid
import zipfile
from datetime import datetime
from PIL import Image
import pillow_heif

# Register HEIF opener for Pillow
pillow_heif.register_heif_opener()

from flask import flash, request
from flask import url_for
from flask_login import current_user
from flask_babel import gettext
from werkzeug.utils import secure_filename
from sqlalchemy import or_

from aot.config import INSTALL_DIRECTORY
from aot.config import PATH_NOTE_ATTACHMENTS
from aot.config_translations import TRANSLATIONS
from aot.databases import set_uuid
from aot.databases.models import NoteTags
from aot.databases.models import Notes
from aot.aot_flask.extensions import db
from aot.aot_flask.utils.utils_general import delete_entry_with_id
from aot.aot_flask.utils.utils_general import flash_success_errors
from aot.utils.system_pi import assure_path_exists

logger = logging.getLogger(__name__)

def process_note_attachment(file_storage, note_unique_id):
    """
    Process uploaded note attachment:
    1. Secure filename
    2. Convert HEIC to JPG
    3. Resize images > 1920px (maintain aspect ratio)
    4. Handle animated GIFs (preserve original)
    """
    filename = secure_filename(file_storage.filename)
    name, ext = os.path.splitext(filename)
    ext_lower = ext.lower()
    
    # Determine save filename (HEIC -> JPG)
    if ext_lower in ['.heic', '.heif']:
        save_filename = "{pre}_{name}.jpg".format(pre=note_unique_id, name=name)
        is_heic = True
    else:
        save_filename = "{pre}_{name}".format(pre=note_unique_id, name=filename)
        is_heic = False
        
    save_path = os.path.join(PATH_NOTE_ATTACHMENTS, save_filename)
    
    try:
        # Attempt to open as image
        image = Image.open(file_storage)
        
        # Check for animated GIF - save original to preserve animation
        if getattr(image, "is_animated", False):
            file_storage.seek(0)
            file_storage.save(save_path)
            return save_filename

        # Image Processing needed if:
        # 1. It's HEIC (needs conversion)
        # 2. It's too large (needs resizing)
        
        max_dimension = 1920
        width, height = image.size
        needs_resize = width > max_dimension or height > max_dimension
        
        if is_heic or needs_resize:
            # Convert to RGB if needed (required for JPG)
            if image.mode != 'RGB':
                image = image.convert('RGB')
                
            if needs_resize:
                ratio = min(max_dimension / width, max_dimension / height)
                new_size = (int(width * ratio), int(height * ratio))
                image = image.resize(new_size, Image.Resampling.LANCZOS)
            
            # Save processed image
            # Force JPG for HEIC, otherwise try to keep original format or default to JPEG
            if is_heic:
                image.save(save_path, "JPEG", quality=85)
            else:
                # If original format is available, use it, else generic save
                save_format = image.format if image.format else "JPEG"
                image.save(save_path, format=save_format, quality=85)
        else:
            # No processing needed, save original stream
            file_storage.seek(0)
            file_storage.save(save_path)
            
    except Exception as e:
        # Not an image or error during processing -> Save original file
        # logger.debug(f"File {filename} is not an image or processing failed: {e}")
        file_storage.seek(0)
        file_storage.save(save_path)
        
    return save_filename

#
# Tags
#

def tag_add(form):
    action = '{action} {controller}'.format(
        action=TRANSLATIONS['add']['title'],
        controller=TRANSLATIONS['tag']['title'])
    error = []

    disallowed_tag_names = ['device_id', 'unit', 'channel']

    if not form.tag_name.data:
        error.append("Tag name is empty")
    if ' ' in form.tag_name.data:
        error.append("Tag name cannot contain spaces")
    elif form.tag_name.data in disallowed_tag_names:
        error.append("Tag name cannot be from this list: {}".format(disallowed_tag_names))

    if NoteTags.query.filter(NoteTags.name == form.tag_name.data).count():
        error.append("Tag already exists")

    if not error:
        new_tag = NoteTags()
        new_tag.name = form.tag_name.data
        new_tag.save()

    flash_success_errors(error, action, url_for('routes_page.page_notes'))


def tag_rename(form):
    action = '{action} {controller}'.format(
        action=TRANSLATIONS['rename']['title'],
        controller=TRANSLATIONS['tag']['title'])
    error = []

    mod_tag = NoteTags.query.filter(NoteTags.unique_id == form.tag_unique_id.data).first()

    if not form.rename.data:
        error.append("Tag name is empty")
    if ' ' in form.rename.data:
        error.append("Tag name cannot contain spaces")

    if NoteTags.query.filter(NoteTags.name == form.rename.data).count():
        error.append("Tag already exists")

    if not error:
        mod_tag.name = form.rename.data
        db.session.commit()

    flash_success_errors(error, action, url_for('routes_page.page_notes'))


def tag_del(form):
    action = '{action} {controller}'.format(
        action=TRANSLATIONS['delete']['title'],
        controller=TRANSLATIONS['tag']['title'])
    error = []

    if Notes.query.filter(Notes.tags.ilike("%{0}%".format(form.tag_unique_id.data))).first():
        error.append("Cannot delete tag because it's currently assicuated with at least one note")

    if not error:
        delete_entry_with_id(NoteTags, form.tag_unique_id.data)

    flash_success_errors(error, action, url_for('routes_page.page_notes'))


#
# Notes
#

def note_add(form):
    action = '{action} {controller}'.format(
        action=TRANSLATIONS['add']['title'],
        controller=TRANSLATIONS['note']['title'])
    error = []
    list_tags = []

    new_note = Notes()
    # Always assign a unique_id at the start to ensure consistency
    new_note.unique_id = set_uuid()
    if current_user.is_authenticated:
        new_note.user_id = current_user.id

    # Relaxed validation: Name and tags are optional. Only note or files are required.
    if not form.note.data and not form.files.data:
        error.append("Note or attachment must be present")

    try:
        for each_tag in form.note_tags.data:
            # Try to find by unique_id first
            check_tag = NoteTags.query.filter(or_(
                NoteTags.unique_id == each_tag,
                NoteTags.name == each_tag
            )).first()
            
            if check_tag:
                list_tags.append(check_tag.unique_id)
            elif each_tag.strip():
                # Auto-create if it looks like a new tag name (not a UUID)
                # and doesn't exist yet as a name
                new_t = NoteTags(name=each_tag.strip())
                db.session.add(new_t)
                db.session.flush() # Get unique_id
                list_tags.append(new_t.unique_id)
        
        new_note.tags = ",".join(list_tags)
    except Exception as msg:
        error.append("Invalid tag format: {}".format(msg))

    if form.enter_custom_date_time.data:
        try:
            if form.date_time.data:
                new_note.date_time = datetime_time_to_utc(form.date_time.data)
            else:
                # Fallback if parsing failed but checkbox was checked
                new_note.date_time = datetime.utcnow()
        except Exception as msg:
            error.append("Error while parsing date/time: {}".format(msg))

    if form.files.data:
        assure_path_exists(PATH_NOTE_ATTACHMENTS)
        filename_list = []
        # Ensure we iterate over file objects (handled by MultipleFileField)
        for each_file in form.files.data:
            if not hasattr(each_file, 'filename') or not each_file.filename:
                continue
            
            saved_filename = process_note_attachment(each_file, new_note.unique_id)
            filename_list.append(saved_filename)
        
        if filename_list:
            new_note.files = ",".join(filename_list)

    if not error:
        # [Smart Subject] If name is generic or empty, extract from note body
        # Now handles "Quick Note" as well (common from widget)
        final_name = form.name.data.strip() if form.name.data else ""
        generic_titles = [_("New Note"), "Quick Note"]
        if not final_name or any(gt in final_name for gt in generic_titles):
            body = form.note.data.strip() if form.note.data else ""
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
        
        new_note.name = final_name
        new_note.note = form.note.data.strip() if form.note.data else ""
        new_note.save()

    flash_success_errors(error, action, url_for('routes_page.page_notes'))


def note_mod(form):
    action = '{action} {controller}'.format(
        action=TRANSLATIONS['modify']['title'],
        controller=TRANSLATIONS['note']['title'])
    error = []
    list_tags = []

    mod_note = Notes.query.filter(
        Notes.unique_id == form.note_unique_id.data).first()

    # Relaxed validation for modifications
    if not form.note.data and not form.files.data and not mod_note.files:
        error.append("Note content or files cannot be entirely empty")

    try:
        for each_tag in form.note_tags.data:
            check_tag = NoteTags.query.filter(or_(
                NoteTags.unique_id == each_tag,
                NoteTags.name == each_tag
            )).first()
            
            if check_tag:
                list_tags.append(check_tag.unique_id)
            elif each_tag.strip():
                # Auto-create new tag
                new_t = NoteTags(name=each_tag.strip())
                db.session.add(new_t)
                db.session.flush()
                list_tags.append(new_t.unique_id)
    except Exception as msg:
        error.append("Invalid tag format: {}".format(msg))

    # [Fix] Date/Time parsing issue:
    # WTF-Form's date_time field might return None if format doesn't match exactly.
    # We try to parse the raw string from request.form as a fallback.
    # [Fix] Date/Time parsing issue:
    raw_date_time = request.form.get('date_time')
    if raw_date_time:
        raw_date_time = raw_date_time.strip()
        dt_obj = None
        formats_to_try = ['%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M']
        
        for fmt in formats_to_try:
            try:
                dt_obj = datetime.strptime(raw_date_time, fmt)
                # If parsed successfully, adding seconds if missing for UI consistency could be handled,
                # but backend just needs a datetime object.
                break
            except ValueError:
                continue
        
        if dt_obj:
            try:
                mod_note.date_time = datetime_time_to_utc(dt_obj)
            except Exception as e:
                 logger.error(f"Date time conversion error: {e}")
                 error.append(f"Error converting date/time: {e}")
        else:
             # All formats failed
             logger.error(f"Date time parse error for note {mod_note.id}: {raw_date_time}")
             error.append("Invalid date format. Use YYYY-MM-DD HH:MM:SS")
    elif form.date_time.data:
         # Fallback to form data if raw string was somehow missing but object exists (rare)
         try:
            mod_note.date_time = datetime_time_to_utc(form.date_time.data)
         except:
            error.append("Error while parsing date/time object")

    if form.files.data:
        assure_path_exists(PATH_NOTE_ATTACHMENTS)
        filename_list = mod_note.files.split(",") if mod_note.files else []
        
        for each_file in form.files.data:
            if not hasattr(each_file, 'filename') or not each_file.filename:
                continue

            saved_filename = process_note_attachment(each_file, mod_note.unique_id)
            filename_list.append(saved_filename)
        
        if filename_list:
            mod_note.files = ",".join(filename_list)

    if not error:
        # [Phase 3] Handle Deleted Files
        deleted_files_str = request.form.get('deleted_files', '')
        if deleted_files_str:
            deleted_list = deleted_files_str.split(',')
            current_files = mod_note.files.split(',') if mod_note.files else []
            updated_files = []
            
            for f in current_files:
                if f in deleted_list:
                    # Physically delete the file
                    file_path = os.path.join(PATH_NOTE_ATTACHMENTS, f)
                    if os.path.isfile(file_path):
                        try:
                            os.remove(file_path)
                        except Exception as e:
                            logger.error(f"Failed to delete file {file_path}: {e}")
                else:
                    updated_files.append(f)
            
            mod_note.files = ",".join(updated_files) if updated_files else None

        # [Smart Subject] Apply to modifications if title is empty or generic
        final_name = form.name.data.strip() if form.name.data else ""
        generic_titles = ["새 노트", "Quick Note"]
        if not final_name or any(gt in final_name for gt in generic_titles):
            body = form.note.data.strip() if form.note.data else ""
            if body:
                first_line = body.split('\n')[0].strip()
                if len(first_line) > 50:
                    first_line = first_line[:47] + "..."
                if first_line:
                    final_name = first_line
                elif not final_name:
                    final_name = "새 노트"
            elif not final_name:
                final_name = "새 노트"

        mod_note.name = final_name
        mod_note.tags = ",".join(list_tags)
        mod_note.note = form.note.data.strip() if form.note.data else ""
        db.session.commit()

    flash_success_errors(error, action, url_for('routes_page.page_notes'))


def file_rename(form):
    action = '{action} {controller}'.format(
        action=TRANSLATIONS['rename']['title'],
        controller=gettext("File"))
    error = []

    if not form.note_unique_id.data:
        error.append("Unique id is empty")
    if not form.note_unique_id.data:
        error.append("New file name cannot be blank")

    mod_note = Notes.query.filter(
        Notes.unique_id == form.note_unique_id.data).first()
    files_list = mod_note.files.split(",")

    new_file_name = "{id}_{name}".format(
        id=form.note_unique_id.data,
        name=form.rename_name.data)

    if form.file_selected.data in files_list:
        # Replace old name with new name
        files_list[files_list.index(form.file_selected.data)] = new_file_name
    else:
        error.append("File not foun din note")

    if mod_note.files:
        try:
            full_file_path = os.path.join(
                PATH_NOTE_ATTACHMENTS, form.file_selected.data)
            new_file_path = os.path.join(PATH_NOTE_ATTACHMENTS, new_file_name)
            os.rename(full_file_path, new_file_path)
        except:
            error.append("Could not remove file from filesystem")

    if not error:
        mod_note.files = ",".join(files_list)
        db.session.commit()

    flash_success_errors(error, action, url_for('routes_page.page_notes'))


def file_del(form):
    action = '{action} {controller}'.format(
        action=TRANSLATIONS['delete']['title'],
        controller=gettext("File"))
    error = []

    if not form.note_unique_id.data:
        error.append("Unique id is empty")

    mod_note = Notes.query.filter(
        Notes.unique_id == form.note_unique_id.data).first()
    files_list = mod_note.files.split(",")

    if form.file_selected.data in files_list:
        try:
            files_list.remove(form.file_selected.data)
        except Exception as e:
            error.append(
                "Could not remove file from note: {}".format(e))

    if mod_note.files:
        try:
            full_file_path = os.path.join(PATH_NOTE_ATTACHMENTS, form.file_selected.data)
            os.remove(full_file_path)
        except Exception as e:
            error.append(
                "Could not remove file from filesystem: {}".format(e))

    if not error:
        mod_note.files = ",".join(files_list)
        db.session.commit()

    flash_success_errors(error, action, url_for('routes_page.page_notes'))


def note_del(form):
    action = '{action} {controller}'.format(
        action=TRANSLATIONS['delete']['title'],
        controller=TRANSLATIONS['note']['title'])
    error = []

    if not form.note_unique_id.data:
        error.append("Unique id is empty")

    note = Notes.query.filter(
        Notes.unique_id == form.note_unique_id.data).first()

    if note.files:
        delete_string = "{dir}/{id}*".format(
            dir=PATH_NOTE_ATTACHMENTS, id=form.note_unique_id.data)
        for filename in glob.glob(delete_string):
            os.remove(filename)

    if not error:
        delete_entry_with_id(Notes, form.note_unique_id.data)

    flash_success_errors(error, action, url_for('routes_page.page_notes'))


def notes_filter(error, form):
    notes = Notes.query

    if form.filter_tags.data:
        target_tags = []
        for each_tag_name in form.filter_tags.data.split(','):
            clean_name = each_tag_name.strip()
            if not clean_name:
                continue
            tag = NoteTags.query.filter(NoteTags.name == clean_name).first()
            if tag:
                target_tags.append(tag)
            else:
                target_tags.append({'name': clean_name, 'unique_id': None})

        tag_conditions = []
        for each_tag in target_tags:
            # Handle both dictionary (fallback) and NoteTags object
            tag_name = each_tag['name'] if isinstance(each_tag, dict) else each_tag.name
            tag_id = each_tag['unique_id'] if isinstance(each_tag, dict) else each_tag.unique_id
            
            # Helper to add 4-way matching for exact CSV item (prevents partial matches like 'widget' matching 'my_widget')
            def add_csv_match_conditions(conditions, val):
                if not val: return
                conditions.append(Notes.tags == val)
                conditions.append(Notes.tags.ilike('{0},%'.format(val)))
                conditions.append(Notes.tags.ilike('%,{0},%'.format(val)))
                conditions.append(Notes.tags.ilike('%,{0}'.format(val)))

            # Add conditions for Name
            add_csv_match_conditions(tag_conditions, tag_name)
            
            # Add conditions for ID (if exists)
            if tag_id:
                add_csv_match_conditions(tag_conditions, tag_id)
        
        if tag_conditions:
            notes = notes.filter(or_(*tag_conditions))

    if form.filter_notes.data:
        if '*' in form.filter_notes.data or '_' in form.filter_notes.data:
            looking_for = form.filter_notes.data.replace('_', '__') \
                .replace('*', '%') \
                .replace('?', '_')
        else:
            looking_for = '%{0}%'.format(form.filter_notes.data)
        notes = notes.filter(Notes.note.ilike(looking_for))

    if form.sort_direction.data == 'desc':
        if form.sort_by.data == 'id':
            notes = notes.order_by(Notes.id.desc())
        elif form.sort_by.data == 'name':
            notes = notes.order_by(Notes.name.desc())
        elif form.sort_by.data == 'date':
            notes = notes.order_by(Notes.date_time.desc())
        elif form.sort_by.data == 'tag':
            notes = notes.order_by(Notes.tags.desc())
        elif form.sort_by.data == 'file':
            notes = notes.order_by(Notes.files.desc())
        elif form.sort_by.data == 'note':
            notes = notes.order_by(Notes.note.desc())
    elif form.sort_direction.data == 'asc':
        if form.sort_by.data == 'id':
            notes = notes.order_by(Notes.id.asc())
        elif form.sort_by.data == 'name':
            notes = notes.order_by(Notes.name.asc())
        elif form.sort_by.data == 'date':
            notes = notes.order_by(Notes.date_time.asc())
        elif form.sort_by.data == 'tag':
            notes = notes.order_by(Notes.tags.asc())
        elif form.sort_by.data == 'file':
            notes = notes.order_by(Notes.files.asc())
        elif form.sort_by.data == 'note':
            notes = notes.order_by(Notes.note.asc())

    return error, notes


def show_notes(form):
    error = []
    error, notes = notes_filter(error, form)

    for each_error in error:
        flash('Error: {}'.format(each_error), 'error')

    if not error:
        return notes


def export_notes(form):
    """
    Convert note table entries to CSV file, then zip CSV file and note attachments
    :param form: wtforms form object
    :return:
    """
    error = []
    attach_files = []

    error, notes = notes_filter(error, form)

    if notes.count() == 0:
        error.append("Cannot Export Notes: No notes were found with the current search filters.")

    date_time_now = datetime.now().strftime("%Y-%m-%d--%H-%M-%S")
    file_name = '{time}_{host}_notes_exported.csv'.format(time=date_time_now, host=socket.gethostname())
    full_path_csv = os.path.join('/var/tmp/', file_name)

    with open(full_path_csv, mode='w') as csv_file:
        cw = csv.writer(csv_file, delimiter=',', quotechar='"', quoting=csv.QUOTE_MINIMAL)
        cw.writerow(['ID', 'UUID', 'Time', 'Name', 'Note', 'Tags', 'Files'])
        for each_note in notes:
            tags = {}
            list_tag_id_names = []
            if each_note.tags:
                for each_tag_id in each_note.tags.split(','):
                    tag_obj = NoteTags.query.filter(
                        NoteTags.unique_id == each_tag_id).first()
                    if tag_obj:
                         tag_name = tag_obj.name
                         tags[each_tag_id] = tag_name
                         list_tag_id_names.append('{},{}'.format(each_tag_id, tag_name))

            cw.writerow([each_note.id,
                         each_note.unique_id,
                         each_note.date_time.strftime("%Y-%m-%d %H:%M:%S"),
                         each_note.name,
                         each_note.note,
                         ';'.join(list_tag_id_names),
                         each_note.files])
            if each_note.files:
                attach_files.append(each_note.files.split(','))

    # Zip csv file and attachments
    data = io.BytesIO()
    with zipfile.ZipFile(data, mode='w') as z:
        z.write(full_path_csv, file_name)
        for each_file_set in attach_files:
            for each_file in each_file_set:
                path_attachment = os.path.join(PATH_NOTE_ATTACHMENTS, each_file)
                if os.path.isfile(path_attachment):
                    z.write(path_attachment, os.path.join('/attachments', each_file))
                else:
                    try:
                         # Log warning or inform user? For now just skip to prevent crash
                         logger.warning(f"Skipping missing attachment: {path_attachment}")
                    except:
                         pass
    data.seek(0)

    os.remove(full_path_csv)

    if not error:
        return notes, data
    else:
        for each_error in error:
            flash('{}'.format(each_error), 'error')
        return notes, None


def import_notes(form):
    """
    Receive a zip file containing a CSV file and note attachments
    """
    action = '{action} {controller}'.format(
        action=gettext("Import"),
        controller=TRANSLATIONS['note']['title'])
    error = []

    upload_folder = os.path.join(INSTALL_DIRECTORY, 'upload')
    tmp_folder = os.path.join(upload_folder, 'aot_notes_tmp')

    try:
        if not form.notes_import_file.data:
            error.append('No file present')
        elif form.notes_import_file.data.filename == '':
            error.append('No file name')

        if not error:
            # Save file to upload directory
            filename = secure_filename(
                form.notes_import_file.data.filename)
            full_path = os.path.join(tmp_folder, filename)
            assure_path_exists(upload_folder)
            assure_path_exists(tmp_folder)
            form.notes_import_file.data.save(
                os.path.join(tmp_folder, filename))

            # Unzip file
            try:
                zip_ref = zipfile.ZipFile(full_path, 'r')
                zip_ref.extractall(tmp_folder)
                zip_ref.close()
            except Exception as err:
                logger.exception(1)
                error.append("Exception while extracting zip file: "
                             "{err}".format(err=err))

        if not error:
            found_csv = False
            for each_file in os.listdir(tmp_folder):
                if each_file.endswith('_notes_exported.csv') and not found_csv:
                    found_csv = True
                    count_notes = 0
                    count_notes_skipped = 0
                    count_attach = 0
                    logger.error(each_file)

                    file_csv = os.path.join(tmp_folder, each_file)
                    path_attachments = os.path.join(tmp_folder, 'attachments')

                    with open(file_csv, 'r' ) as theFile:
                        reader = csv.DictReader(theFile)
                        for line in reader:
                            if not Notes.query.filter(Notes.unique_id == line['UUID']).count():
                                count_notes += 1

                                new_note = Notes()
                                new_note.unique_id = line['UUID']
                                new_note.date_time = datetime.strptime(line['Time'], '%Y-%m-%d %H:%M:%S')
                                new_note.name = line['Name']
                                new_note.note = line['Note']

                                tag_ids = []
                                tags = {}
                                for each_tag in line['Tags'].split(';'):
                                    tags[each_tag.split(',')[0]] = each_tag.split(',')[1]
                                    tag_ids.append(each_tag.split(',')[0])

                                for each_tag_id, each_tag_name in tags.items():
                                    if (not NoteTags.query.filter(NoteTags.unique_id == each_tag_id).count() and
                                            not NoteTags.query.filter(NoteTags.name == each_tag_name).count()):
                                        new_tag = NoteTags()
                                        new_tag.unique_id = each_tag_id
                                        new_tag.name = each_tag_name
                                        new_tag.save()

                                    elif (not NoteTags.query.filter(NoteTags.unique_id == each_tag_id).count() and
                                            NoteTags.query.filter(NoteTags.name == each_tag_name).count()):
                                        new_tag = NoteTags()
                                        new_tag.unique_id = each_tag_id
                                        new_tag.name = each_tag_name + str(uuid.uuid4())[:8]
                                        new_tag.save()

                                new_note.tags = ','.join(tag_ids)
                                new_note.files = line['Files']
                                new_note.save()

                                for each_file_name in line['Files'].split(','):
                                    count_attach += 1
                                    os.rename(os.path.join(path_attachments, each_file_name),
                                              os.path.join(PATH_NOTE_ATTACHMENTS, each_file_name))
                            else:
                                count_notes_skipped += 1

                    if (count_notes + count_attach) == 0:
                        error.append("0 imported, {notes} skipped".format(
                            notes=count_notes_skipped))
                    else:
                        flash("Imported {notes} notes and {attach} "
                              "attachments".format(notes=count_notes,
                                                   attach=count_attach),
                              "success")

            if not found_csv:
                error.append("Cannot import notes: Could not find CSV file in ZIP archive.")

    except Exception as err:
        error.append("Exception: {}".format(err))
    finally:
        if os.path.isdir(tmp_folder):
            shutil.rmtree(tmp_folder)  # Delete tmp directory

    flash_success_errors(error, action, url_for('routes_page.page_export'))


def datetime_time_to_utc(datetime_time):
    if not datetime_time:
        return datetime.utcnow()
    try:
        timestamp = str(time.mktime(datetime_time.timetuple()))[:-2]
        return datetime.utcfromtimestamp(int(timestamp))
    except:
        return datetime.utcnow()


def get_note_tag_from_unique_id(tag_unique_id):
    if not tag_unique_id:
        return ""
    
    clean_id = tag_unique_id.strip()
    
    # 1. Try finding by Unique ID
    tag = NoteTags.query.filter(NoteTags.unique_id == clean_id).first()
    if tag and tag.name:
        return tag.name

    # 2. Try finding by Name (If stored as name directly)
    tag_by_name = NoteTags.query.filter(NoteTags.name == clean_id).first()
    if tag_by_name:
        return tag_by_name.name
        
    # 3. Fallback: Return the raw string (It might be a legacy text tag)
    return clean_id
