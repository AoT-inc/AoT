# coding=utf-8
"""처음 붙은 AI 가 걸린 두 자리(2026-10-19 리허설).

  1. 작물 현황: 시설을 지정하면 노지 구획이 `[]`/0 으로 나와 "노지에 구획이 없다"
     로 읽혔다. 이제 키를 빼고 다른 곳에 몇 건 있는지·어디서 보는지를 말한다.
     상한에 잘린 노지 구획도 이름은 남는다.
  2. 노트 사진: 파일 이름을 정확히 줘야만 열렸다. 하나뿐이면 이름 없이, 여럿이면
     목록과 함께 되묻고, 이름은 대소문자·공백·일부 일치로도 찾는다.

라이브 DB 를 쓰지 않는다(임시 sqlite, 임시 첨부 디렉터리).
"""
import os
import tempfile
import unittest
from datetime import date
from unittest import mock


def _square(x0, y0, size):
    return {'type': 'Polygon', 'coordinates': [[
        [x0, y0], [x0 + size, y0], [x0 + size, y0 + size], [x0, y0 + size],
        [x0, y0]]]}


def setUpModule():
    from flask import Flask
    from flask_babel import Babel
    from PIL import Image
    from aot.aot_flask.extensions import db
    import aot.databases.models  # noqa: F401
    from aot.databases.models import GeoFacility, GeoMap, GeoPlot, Notes

    global _tmp, _ctx, _att
    _tmp = tempfile.TemporaryDirectory()
    _att = os.path.join(_tmp.name, 'att')
    os.makedirs(_att)
    for n in ('Bed_A.JPG', 'bed_b.png', 'other.png', 'solo.png'):
        Image.new('RGB', (40, 30), (10, 120, 10)).save(
            os.path.join(_att, n), format='PNG' if n.endswith('png') else 'JPEG')
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = \
        'sqlite:///' + os.path.join(_tmp.name, 'crops.db')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    db.init_app(app)
    Babel(app)
    _ctx = app.app_context()
    _ctx.push()
    db.create_all()

    db.session.add(GeoMap(unique_id='map-cp', name='노지농장'))
    db.session.add(GeoFacility(unique_id='fac-cp', name='온실하나',
                               shape_uuid='shp-cp', geo_id='map-cp'))
    for i in range(14):
        db.session.add(GeoPlot(
            unique_id='cp-%02d' % i, geo_id='map-cp', subject='콩%02d' % i,
            started_on=date.today(),
            feature={'type': 'Feature', 'properties': {},
                     'geometry': _square(i * 0.001, 0.5, 0.0005)}))
    db.session.add(Notes(unique_id='note-one', name='하나', files='solo.png'))
    db.session.add(Notes(unique_id='note-many', name='여럿',
                         files='Bed_A.JPG,bed_b.png,other.png'))
    db.session.add(Notes(unique_id='note-none', name='없음', files=''))
    db.session.commit()


def tearDownModule():
    from aot.aot_flask.extensions import db
    db.session.remove()
    _ctx.pop()
    _tmp.cleanup()


def _S():
    from aot.tools.aot_data_tool_service import AoTDataToolService
    return AoTDataToolService


class CropStatusOpenFieldTest(unittest.TestCase):

    def test_facility_filter_does_not_pretend_there_are_no_open_plots(self):
        out = _S().get_crop_status(facility_name='온실하나')
        self.assertNotIn('open_field_plots', out)
        self.assertNotIn('plot_count', out)
        self.assertEqual(14, out['open_field_plots_elsewhere'])
        self.assertIn('find.plots', out['facility_filter_note'])

    def test_truncated_open_plots_keep_their_names(self):
        out = _S().get_crop_status(limit=4)
        self.assertEqual(4, len(out['open_field_plots']))
        self.assertEqual(14, out['plot_count'])
        self.assertEqual(10, len(out['open_field_rest']))
        shown = {p['subject'] for p in out['open_field_plots']}
        names = {r.split(' @ ')[0] for r in out['open_field_rest']}
        self.assertFalse(shown & names)
        self.assertEqual(14, len(shown | names))
        self.assertIn('find.plots', out['open_field_rest_note'])

    def test_complete_list_has_no_rest(self):
        out = _S().get_crop_status(limit=100)
        self.assertNotIn('open_field_rest', out)

    def test_rest_names_are_capped(self):
        with mock.patch.object(_S(), '_PLOT_REST_NAMES_MAX', 3):
            out = _S().get_crop_status(limit=4)
        self.assertEqual(4, len(out['open_field_rest']))
        self.assertEqual('... +7 more', out['open_field_rest'][-1])


class NoteAttachmentTest(unittest.TestCase):

    def _get(self, note_id, filename=None):
        with mock.patch('aot.config.PATH_NOTE_ATTACHMENTS', _att):
            return _S().get_note_attachment_tool(note_id=note_id, filename=filename)

    def test_single_attachment_opens_without_a_filename(self):
        out = self._get('note-one')
        self.assertEqual('success', out['status'], out)
        self.assertEqual('solo.png', out['filename'])
        self.assertTrue(out['_content_blocks'])

    def test_several_without_a_filename_lists_them(self):
        out = self._get('note-many')
        self.assertEqual('error', out['status'])
        self.assertEqual(['Bed_A.JPG', 'bed_b.png', 'other.png'], out['files'])
        self.assertNotIn('_content_blocks', out)

    def test_wrong_filename_lists_them_too(self):
        out = self._get('note-many', 'nope.png')
        self.assertEqual('error', out['status'])
        self.assertEqual(3, len(out['files']))

    def test_case_and_space_do_not_matter(self):
        out = self._get('note-many', '  bed_a.jpg ')
        self.assertEqual('success', out['status'], out)
        self.assertEqual('Bed_A.JPG', out['filename'])

    def test_unique_part_matches(self):
        out = self._get('note-many', 'other')
        self.assertEqual('other.png', out['filename'])

    def test_ambiguous_part_is_not_guessed(self):
        out = self._get('note-many', 'bed')
        self.assertEqual('error', out['status'])
        self.assertIn('more than one', out['message'])
        self.assertEqual(3, len(out['files']))

    def test_path_traversal_is_not_a_match(self):
        out = self._get('note-many', '../../etc/passwd')
        self.assertEqual('error', out['status'])

    def test_no_attachments_is_still_an_error(self):
        out = self._get('note-none')
        self.assertEqual('error', out['status'])


class NotePhotoSchemaTest(unittest.TestCase):

    def test_filename_stays_in_the_schema_but_is_not_required(self):
        from aot.tools.domain import surface
        from aot.tools.domain.registry import find_op
        from aot.tools.domain.registry_data import OPS
        o = find_op(OPS, 'records', 'note_attachment')
        self.assertNotIn('filename', o.required)
        got = {e['name']: e for e in surface.entries(OPS, lambda n: True, set())}
        self.assertIn('filename', got['records']['inputSchema']['properties'])
