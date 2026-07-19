# -*- coding: utf-8 -*-
#
# utils_notes_report.py - Period/tag based Note PDF report generation
#
# Builds a formatted PDF report from notes filtered by a time period
# (weekly / monthly / custom range) and tags. Uses reportlab's built-in Adobe
# Korean CID fonts (HYSMyeongJo-Medium / HYGothic-Medium) so CJK text renders
# without bundling any external TTF font.
#
import io
import logging
import os
import socket
from datetime import datetime, time as dt_time, timedelta

from flask import flash
from flask_babel import gettext, lazy_gettext

from aot.config import AOT_VERSION
from aot.config import PATH_NOTE_ATTACHMENTS
from aot.databases.models import NoteTags
from aot.aot_flask.utils.utils_notes import datetime_time_to_utc
from aot.aot_flask.utils.utils_notes import notes_filter
from aot.utils.time_utils import get_local_now
from aot.utils.time_utils import to_local

logger = logging.getLogger(__name__)

# Image attachment extensions that can be embedded in the PDF
_IMAGE_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp')

# Body font (Myeongjo) and heading font (Gothic). Falls back to Helvetica if the
# reportlab Korean CID fonts are unavailable for any reason.
FONT_BODY = 'Helvetica'
FONT_HEAD = 'Helvetica-Bold'
_fonts_registered = False


def _register_korean_fonts():
    """Register reportlab's built-in Adobe Korean CID fonts once."""
    global FONT_BODY, FONT_HEAD, _fonts_registered
    if _fonts_registered:
        return
    _fonts_registered = True
    try:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont
        pdfmetrics.registerFont(UnicodeCIDFont('HYSMyeongJo-Medium'))
        pdfmetrics.registerFont(UnicodeCIDFont('HYGothic-Medium'))
        FONT_BODY = 'HYSMyeongJo-Medium'
        FONT_HEAD = 'HYGothic-Medium'
    except Exception:
        logger.exception("Korean CID font registration failed; falling back to Helvetica")


#
# Period resolution
#

# (value, label) choices exposed to the form/UI
PERIOD_CHOICES = [
    ('this_week', lazy_gettext('This Week (weekly)')),
    ('last_week', lazy_gettext('Last Week')),
    ('this_month', lazy_gettext('This Month (monthly)')),
    ('last_month', lazy_gettext('Last Month')),
    ('last_7_days', lazy_gettext('Last 7 Days')),
    ('last_30_days', lazy_gettext('Last 30 Days')),
    ('custom', lazy_gettext('Custom Range')),
    ('all', lazy_gettext('All Time')),
]


def resolve_period(period, start_str='', end_str=''):
    """
    Resolve a period selector into local-time (start, end) datetime bounds and a
    human-readable label.

    Returns (start_local, end_local, label). start_local/end_local are naive
    datetimes in the configured facility timezone. Either bound may be None,
    meaning "unbounded" (used by the 'all' period and partial custom ranges).
    """
    now_local = get_local_now()
    today = now_local.date()

    def day_start(d):
        return datetime.combine(d, dt_time.min)

    def day_end(d):
        return datetime.combine(d, dt_time.max)

    if period == 'this_week':
        monday = today - timedelta(days=today.weekday())
        return day_start(monday), day_end(today), gettext('This Week')

    if period == 'last_week':
        this_monday = today - timedelta(days=today.weekday())
        last_monday = this_monday - timedelta(days=7)
        last_sunday = this_monday - timedelta(days=1)
        return day_start(last_monday), day_end(last_sunday), gettext('Last Week')

    if period == 'this_month':
        first = today.replace(day=1)
        return day_start(first), day_end(today), today.strftime('%Y-%m')

    if period == 'last_month':
        first_this = today.replace(day=1)
        last_month_end = first_this - timedelta(days=1)
        first_last = last_month_end.replace(day=1)
        return (day_start(first_last), day_end(last_month_end),
                last_month_end.strftime('%Y-%m'))

    if period == 'last_7_days':
        start = today - timedelta(days=6)
        return day_start(start), day_end(today), gettext('Last 7 Days')

    if period == 'last_30_days':
        start = today - timedelta(days=29)
        return day_start(start), day_end(today), gettext('Last 30 Days')

    if period == 'custom':
        start_local = _parse_date(start_str, end_of_day=False)
        end_local = _parse_date(end_str, end_of_day=True)
        label_parts = []
        if start_local:
            label_parts.append(start_local.strftime('%Y-%m-%d'))
        if end_local:
            label_parts.append(end_local.strftime('%Y-%m-%d'))
        label = ' ~ '.join(label_parts) if label_parts else gettext('Custom')
        return start_local, end_local, label

    # 'all' or unknown
    return None, None, gettext('All Time')


def _parse_date(value, end_of_day=False):
    """Parse a YYYY-MM-DD (or with time) string into a naive local datetime."""
    if not value:
        return None
    value = value.strip()
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d'):
        try:
            dt = datetime.strptime(value, fmt)
            if fmt == '%Y-%m-%d' and end_of_day:
                dt = datetime.combine(dt.date(), dt_time.max)
            return dt
        except ValueError:
            continue
    return None


#
# Note selection
#

def select_notes_for_report(form, start_local, end_local):
    """
    Filter notes by the form's tag/text filters (via notes_filter) and by the
    resolved local date range. Returns an ordered list of Notes (oldest first,
    so the report reads chronologically).
    """
    error = []
    error, notes = notes_filter(error, form)

    # Convert local bounds -> naive UTC to compare against stored UTC date_time
    from aot.databases.models import Notes
    if start_local is not None:
        notes = notes.filter(Notes.date_time >= datetime_time_to_utc(start_local))
    if end_local is not None:
        notes = notes.filter(Notes.date_time <= datetime_time_to_utc(end_local))

    return notes.order_by(Notes.date_time.asc()).all()


def _tag_names(note, tag_lookup):
    """Resolve a note's comma-separated tag ids/names into display names."""
    names = []
    for raw in (note.tags or '').split(','):
        raw = raw.strip()
        if not raw or raw in ('map_hidden',):
            continue
        names.append(tag_lookup.get(raw, raw))
    return [n for n in names if n and n != 'map_hidden']


#
# PDF generation
#

def generate_notes_pdf(notes, period_label, report_title=None, tag_label=''):
    """
    Render the given notes into a formatted PDF report and return a BytesIO.
    """
    _register_korean_fonts()

    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (Image, Paragraph, SimpleDocTemplate,
                                    Spacer, Table, TableStyle)

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=18 * mm, bottomMargin=18 * mm,
        title=report_title or gettext('Notes Report'))

    styles = getSampleStyleSheet()
    style_title = ParagraphStyle(
        'ReportTitle', parent=styles['Title'], fontName=FONT_HEAD,
        fontSize=20, leading=26, alignment=TA_CENTER, spaceAfter=2)
    style_sub = ParagraphStyle(
        'ReportSub', parent=styles['Normal'], fontName=FONT_BODY,
        fontSize=10, leading=14, alignment=TA_CENTER, textColor=colors.HexColor('#666666'))
    style_section = ParagraphStyle(
        'Section', parent=styles['Heading2'], fontName=FONT_HEAD,
        fontSize=12, leading=16, textColor=colors.HexColor('#2c3e50'),
        spaceBefore=10, spaceAfter=4)
    style_note_head = ParagraphStyle(
        'NoteHead', parent=styles['Normal'], fontName=FONT_HEAD,
        fontSize=11, leading=15, textColor=colors.HexColor('#1a1a1a'))
    style_meta = ParagraphStyle(
        'NoteMeta', parent=styles['Normal'], fontName=FONT_BODY,
        fontSize=8, leading=11, textColor=colors.HexColor('#888888'))
    style_body = ParagraphStyle(
        'NoteBody', parent=styles['Normal'], fontName=FONT_BODY,
        fontSize=10, leading=15, alignment=TA_LEFT, spaceBefore=2)

    tag_lookup = {t.unique_id: t.name for t in NoteTags.query.all()}
    for t in NoteTags.query.all():
        tag_lookup[t.name] = t.name

    elements = []

    # --- Header ---
    elements.append(Paragraph(_esc(report_title or gettext('Notes Report')), style_title))
    sub_bits = [gettext('Period: %(label)s', label=period_label)]
    if tag_label:
        sub_bits.append(gettext('Tags: %(label)s', label=tag_label))
    sub_bits.append(gettext('Generated: %(dt)s', dt=get_local_now().strftime('%Y-%m-%d %H:%M')))
    sub_bits.append(gettext('%(num)d notes', num=len(notes)))
    elements.append(Paragraph(_esc('  |  '.join(sub_bits)), style_sub))
    elements.append(Spacer(1, 4 * mm))
    elements.append(_hr(colors.HexColor('#cccccc')))
    elements.append(Spacer(1, 4 * mm))

    if not notes:
        elements.append(Paragraph(gettext('No notes match the selected criteria.'), style_body))
        doc.build(elements)
        buffer.seek(0)
        return buffer

    # --- Notes grouped by local day ---
    current_day = None
    avail_width = doc.width

    for note in notes:
        local_dt = to_local(note.date_time)
        day_key = local_dt.strftime('%Y-%m-%d (%a)') if local_dt else gettext('No date')
        if day_key != current_day:
            current_day = day_key
            elements.append(Paragraph(_esc(day_key), style_section))
            elements.append(_hr(colors.HexColor('#e6e6e6'), thickness=0.5))
            elements.append(Spacer(1, 2 * mm))

        time_str = local_dt.strftime('%H:%M') if local_dt else ''
        subject = (note.name or gettext('Untitled')).strip()
        elements.append(Paragraph('{}  {}'.format(time_str, _esc(subject)), style_note_head))

        names = _tag_names(note, tag_lookup)
        meta_bits = []
        if names:
            meta_bits.append(gettext('Tags: %(names)s', names=', '.join(names)))
        author = note.author.name if note.author else None
        if author:
            meta_bits.append(gettext('Author: %(author)s', author=author))
        if meta_bits:
            elements.append(Paragraph(_esc('   '.join(meta_bits)), style_meta))

        body = (note.note or '').strip()
        if body:
            elements.append(Paragraph(_esc(body).replace('\n', '<br/>'), style_body))

        # Embed image attachments (up to 4 per note, in a row)
        img_flowables = _build_image_row(note, avail_width, Image, Table, TableStyle, mm)
        if img_flowables:
            elements.append(Spacer(1, 2 * mm))
            elements.append(img_flowables)

        elements.append(Spacer(1, 5 * mm))

    def _footer(canvas, doc_):
        canvas.saveState()
        canvas.setFont(FONT_BODY, 7)
        canvas.setFillColor(colors.HexColor('#999999'))
        footer_txt = gettext(
            'AoT %(ver)s  ·  %(host)s  ·  Page %(page)s',
            ver=AOT_VERSION, host=socket.gethostname(), page=doc_.page)
        canvas.drawCentredString(A4[0] / 2.0, 10 * mm, footer_txt)
        canvas.restoreState()

    doc.build(elements, onFirstPage=_footer, onLaterPages=_footer)
    buffer.seek(0)
    return buffer


def _build_image_row(note, avail_width, Image, Table, TableStyle, mm):
    """Build a single-row Table of up to 4 image thumbnails for a note."""
    if not note.files:
        return None
    image_paths = []
    for fname in note.files.split(','):
        fname = fname.strip()
        if not fname:
            continue
        ext = os.path.splitext(fname)[1].lower()
        if ext not in _IMAGE_EXTENSIONS:
            continue
        path = os.path.join(PATH_NOTE_ATTACHMENTS, fname)
        if os.path.isfile(path):
            image_paths.append(path)
        if len(image_paths) >= 4:
            break
    if not image_paths:
        return None

    from PIL import Image as PILImage
    cell_w = (avail_width / len(image_paths)) - (3 * mm)
    max_h = 45 * mm
    cells = []
    for path in image_paths:
        try:
            with PILImage.open(path) as im:
                iw, ih = im.size
            ratio = min(cell_w / iw, max_h / ih)
            w, h = iw * ratio, ih * ratio
            cells.append(Image(path, width=w, height=h))
        except Exception:
            logger.debug("Skipping unembeddable image: %s", path)
    if not cells:
        return None

    table = Table([cells], colWidths=[avail_width / len(cells)] * len(cells))
    table.setStyle(TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 3),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
    ]))
    return table


def _hr(color, thickness=1):
    """A thin horizontal rule flowable."""
    from reportlab.platypus import Table, TableStyle
    t = Table([['']], colWidths=['100%'], rowHeights=[1])
    t.setStyle(TableStyle([('LINEBELOW', (0, 0), (-1, -1), thickness, color)]))
    return t


def _esc(text):
    """Escape XML-special chars for reportlab Paragraph markup."""
    if text is None:
        return ''
    return (str(text)
            .replace('&', '&amp;')
            .replace('<', '&lt;')
            .replace('>', '&gt;'))


#
# Entry point used by the route
#

def export_notes_pdf(form):
    """
    Build a PDF report from the export form's period/tag selection.

    Returns (buffer, filename). On error, flashes the message and returns
    (None, None).
    """
    period = (form.report_period.data or 'this_month')
    start_str = form.report_date_start.data or ''
    end_str = form.report_date_end.data or ''
    report_title = (form.report_title.data or '').strip() or gettext('Notes Report')

    start_local, end_local, period_label = resolve_period(period, start_str, end_str)

    tag_label = (form.filter_tags.data or '').strip()

    try:
        notes = select_notes_for_report(form, start_local, end_local)
    except Exception as err:
        logger.exception("Failed selecting notes for PDF report")
        flash(gettext('Error querying notes for the report: %(err)s', err=err), 'error')
        return None, None

    if not notes:
        flash(gettext('No notes match the selected period/tags.'), 'error')
        return None, None

    try:
        buffer = generate_notes_pdf(
            notes, period_label, report_title=report_title, tag_label=tag_label)
    except Exception as err:
        logger.exception("Failed generating notes PDF report")
        flash(gettext('Error generating the PDF report: %(err)s', err=err), 'error')
        return None, None

    filename = 'AoT_Notes_Report_{ver}_{host}_{dt}.pdf'.format(
        ver=AOT_VERSION,
        host=socket.gethostname().replace(' ', ''),
        dt=get_local_now().strftime('%Y-%m-%d_%H-%M-%S'))

    return buffer, filename
