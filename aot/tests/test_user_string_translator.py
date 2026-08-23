# coding=utf-8
"""사용자 지정 문자열 번역기의 계약을 지킨다.

이 기능이 잘못 도는 방식은 셋뿐이고, 셋 다 조용히 일어난다.

1. **시스템 문구를 함께 바꾼다.** 사용자가 출력 이름을 "Pump" 나 "온도"로
   지어 두면, 그 문자열이 사전에 들어가는 순간 같은 단어를 쓰는 UI 문구까지
   번역기가 다시 건드린다(이미 gettext 가 번역해 둔 것을). 그래서 gettext
   카탈로그와 충돌하는 키는 사전에 들어가면 안 된다.

2. **기계 식별자를 번역한다.** DevEUI·UUID·IP·경로는 사람이 읽는 이름이
   아니다. 번역되면 화면의 값이 틀린 값이 된다.

3. **엔진 응답을 무비판적으로 받는다.** 개수가 어긋나거나 JSON 이 아닌 응답을
   그대로 쓰면 이름이 서로 뒤바뀐 채 저장되고, 캐시라 영구히 남는다.

설계: docs/design/user-string-live-translation.md
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from aot.ai.services import user_string_translator as ust


class TestNormalize(unittest.TestCase):
    """정규화는 조회 키를 만들 뿐, 이름을 바꾸지 않는다."""

    def test_trims_and_collapses_whitespace(self):
        self.assertEqual(ust.normalize('  1번   하우스 '), '1번 하우스')

    def test_preserves_case_and_punctuation(self):
        # 대소문자·문장부호는 이름의 정체성이다. 건드리면 다른 이름이 된다.
        self.assertEqual(ust.normalize('Zone-A (North)'), 'Zone-A (North)')

    def test_empty_and_none(self):
        self.assertEqual(ust.normalize(''), '')
        self.assertEqual(ust.normalize(None), '')

    def test_hash_is_stable_across_equivalent_spacing(self):
        self.assertEqual(ust.text_hash('1번  하우스'), ust.text_hash('1번 하우스'))

    def test_hash_differs_for_different_names(self):
        self.assertNotEqual(ust.text_hash('1번 하우스'), ust.text_hash('2번 하우스'))


class TestScriptDetection(unittest.TestCase):
    def test_hangul(self):
        self.assertEqual(ust.detect_script_lang('동편 밸브'), 'ko')

    def test_kana(self):
        self.assertEqual(ust.detect_script_lang('ハウス'), 'ja')

    def test_cyrillic(self):
        self.assertEqual(ust.detect_script_lang('Теплица'), 'ru')

    def test_latin_is_not_guessed(self):
        # 라틴 문자는 수십 개 언어가 공유한다. 틀린 단정보다 'auto' 가 낫다.
        self.assertEqual(ust.detect_script_lang('Greenhouse 1'), 'auto')

    def test_cjk_ideographs_are_not_guessed(self):
        # 한자만으로는 zh 와 ja 를 가를 수 없다.
        self.assertEqual(ust.detect_script_lang('温室'), 'auto')

    def test_digits_only(self):
        self.assertEqual(ust.detect_script_lang('12345'), 'auto')


class TestStructuralSkip(unittest.TestCase):
    """기계 식별자와 내용 없는 문자열은 번역하지 않는다."""

    def _skipped(self, text):
        ok, reason = ust.is_structurally_translatable(text)
        return (not ok, reason)

    def test_translates_a_normal_name(self):
        ok, _ = ust.is_structurally_translatable('1번 하우스 온습도')
        self.assertTrue(ok)

    def test_skips_uuid(self):
        skipped, reason = self._skipped('3f2504e0-4f89-11d3-9a0c-0305e82c3301')
        self.assertTrue(skipped)
        self.assertEqual(reason, 'identifier')

    def test_skips_deveui(self):
        skipped, reason = self._skipped('AC1F09FFFE0812B4')
        self.assertTrue(skipped)
        self.assertEqual(reason, 'identifier')

    def test_skips_mac_address(self):
        self.assertTrue(self._skipped('b8:27:eb:1a:2b:3c')[0])

    def test_skips_ipv4(self):
        self.assertTrue(self._skipped('192.168.0.14')[0])

    def test_skips_path(self):
        self.assertTrue(self._skipped('/var/lib/aot/aot.db')[0])

    def test_skips_url(self):
        self.assertTrue(self._skipped('https://example.com/x')[0])

    def test_skips_email(self):
        self.assertTrue(self._skipped('someone@example.com')[0])

    def test_skips_single_character(self):
        self.assertTrue(self._skipped('A')[0])

    def test_skips_digits_and_symbols_only(self):
        self.assertTrue(self._skipped('12.5 %')[0])
        self.assertTrue(self._skipped('---')[0])

    def test_skips_overlong_text(self):
        self.assertTrue(self._skipped('가' * (ust.MAX_LENGTH + 1))[0])

    def test_keeps_name_that_merely_contains_digits(self):
        # "1번 하우스" 는 숫자를 포함할 뿐 숫자가 아니다.
        ok, _ = ust.is_structurally_translatable('1번 하우스')
        self.assertTrue(ok)


class TestCatalogCollision(unittest.TestCase):
    """이미 gettext 가 번역하는 문자열은 사전에서 뺀다 — 이중 번역 방지."""

    def test_system_word_collides(self):
        # 'Temperature' 는 소스에 있는 문구다. 사용자가 장치를 그렇게 이름
        # 지었다 해도 사전에 넣으면 UI 문구까지 함께 바뀐다.
        self.assertTrue(ust.collides_with_catalog('Temperature', 'ko'))

    def test_translated_word_collides(self):
        # msgstr 쪽도 본다: 한국어 화면에서 '온도' 는 시스템 문구의 결과값이다.
        self.assertTrue(ust.collides_with_catalog('온도', 'ko'))

    def test_user_specific_name_does_not_collide(self):
        self.assertFalse(ust.collides_with_catalog('1번 하우스 동편 상단', 'ko'))

    def test_catalog_is_nonempty(self):
        # 카탈로그 로드가 조용히 실패하면 위의 두 검사가 무의미해진다.
        self.assertGreater(len(ust.catalog_terms('ko')), 100)


class TestResponseParsing(unittest.TestCase):
    """엔진 응답은 믿지 않는다. 어긋나면 저장하지 않는다."""

    def test_plain_json_array(self):
        self.assertEqual(
            ust._parse_response('["1号ハウス", "東側バルブ"]', 2),
            ['1号ハウス', '東側バルブ'])

    def test_fenced_json(self):
        raw = '```json\n["A", "B"]\n```'
        self.assertEqual(ust._parse_response(raw, 2), ['A', 'B'])

    def test_array_embedded_in_prose(self):
        raw = 'Here you go:\n["A", "B"]\nHope that helps!'
        self.assertEqual(ust._parse_response(raw, 2), ['A', 'B'])

    def test_rejects_wrong_count(self):
        # 개수가 어긋나면 이름이 서로 밀려 저장된다 — 캐시라 영구히 남는다.
        self.assertIsNone(ust._parse_response('["A"]', 2))

    def test_rejects_non_string_items(self):
        self.assertIsNone(ust._parse_response('["A", 3]', 2))

    def test_rejects_object(self):
        self.assertIsNone(ust._parse_response('{"a": "b"}', 1))

    def test_rejects_garbage(self):
        self.assertIsNone(ust._parse_response('sorry, I cannot do that', 1))

    def test_rejects_empty(self):
        self.assertIsNone(ust._parse_response('', 1))
        self.assertIsNone(ust._parse_response(None, 1))


class TestSourceRegistry(unittest.TestCase):
    """번역 대상 목록은 명시적이어야 한다 — 빠뜨림도, 넘침도 사고다."""

    def test_registry_references_real_models(self):
        from aot.databases import models
        for model_name, field, _domain in ust.SOURCE_SPECS:
            model = getattr(models, model_name, None)
            self.assertIsNotNone(model, f"{model_name} 모델이 없다")
            self.assertTrue(hasattr(model, field),
                            f"{model_name}.{field} 필드가 없다")

    def test_sensitive_fields_are_excluded(self):
        # 사람 이름·자격증명 라벨·권한 식별자는 번역하면 해가 된다.
        forbidden = {'User', 'APIKey', 'UserAPIKey', 'Role', 'MCPServer'}
        listed = {name for name, _f, _d in ust.SOURCE_SPECS}
        self.assertEqual(listed & forbidden, set())



class TestFormSafety(unittest.TestCase):
    """편집 폼은 절대 번역하지 않는다 — 이 검사가 무너지면 데이터가 파괴된다.

    이름 입력칸에 번역본이 들어간 채로 사용자가 저장하면 DB 의 원문이 번역본으로
    덮여 영구 소실된다. 되돌릴 수 없다. 치환기가 폼 컨트롤을 건너뛴다는 것을
    소스 수준에서 고정한다.
    """

    @classmethod
    def setUpClass(cls):
        path = os.path.join(os.path.dirname(__file__), '..', 'aot_flask',
                            'static', 'js', 'common', 'aot-user-i18n.js')
        with open(path, encoding='utf-8') as fh:
            cls.source = fh.read()

    def test_form_controls_are_in_skip_list(self):
        skip_block = self.source.split('var SKIP_TAGS = {')[1].split('};')[0]
        for tag in ('INPUT', 'TEXTAREA', 'SELECT', 'OPTION'):
            self.assertIn(tag, skip_block,
                          f"{tag} 가 치환 제외 목록에 없다 — 저장 시 원문이 파괴된다")

    def test_contenteditable_is_excluded(self):
        self.assertIn('isContentEditable', self.source)

    def test_value_property_is_never_assigned(self):
        # `el.value = ...` 가 등장하면 폼 값을 쓰고 있다는 뜻이다.
        self.assertNotIn('.value =', self.source)

    def test_translatable_attributes_are_display_only(self):
        attrs = self.source.split('var TRANSLATABLE_ATTRS = [')[1].split(']')[0]
        # placeholder/value 는 입력과 관계된 속성이라 손대지 않는다.
        self.assertNotIn('value', attrs)
        self.assertIn('title', attrs)


class TestDatabaseRoundTrip(unittest.TestCase):
    """적재 → 조회 → 사전 생성의 왕복."""

    @classmethod
    def setUpClass(cls):
        from flask import Flask
        from aot.config import AOT_DB_PATH
        from aot.aot_flask.extensions import db
        import aot.databases.models  # noqa: F401

        cls.app = Flask(__name__)
        cls.app.config['SQLALCHEMY_DATABASE_URI'] = AOT_DB_PATH
        cls.app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        db.init_app(cls.app)
        cls.ctx = cls.app.app_context()
        cls.ctx.push()
        db.create_all()

    @classmethod
    def tearDownClass(cls):
        cls.ctx.pop()

    def setUp(self):
        from aot.aot_flask.extensions import db
        from aot.databases.models.user_string_translation import \
            UserStringTranslation
        UserStringTranslation.query.delete()
        db.session.commit()

    def test_enqueue_then_lookup_is_empty_until_translated(self):
        from aot.databases.models.user_string_translation import (
            STATUS_DONE, UserStringTranslation)
        from aot.aot_flask.extensions import db

        ust.enqueue({'1번 하우스': 'zone'}, 'ja')
        # 아직 번역 전 — 조회에 잡히면 안 된다.
        self.assertEqual(ust.lookup(['1번 하우스'], 'ja'), {})

        row = UserStringTranslation.query.filter_by(target_lang='ja').first()
        row.translated_text = '1号ハウス'
        row.status = STATUS_DONE
        db.session.commit()

        self.assertEqual(ust.lookup(['1번 하우스'], 'ja'),
                         {'1번 하우스': '1号ハウス'})

    def test_enqueue_is_idempotent(self):
        from aot.databases.models.user_string_translation import \
            UserStringTranslation
        self.assertEqual(ust.enqueue({'동편 밸브': 'device'}, 'ja'), 1)
        self.assertEqual(ust.enqueue({'동편 밸브': 'device'}, 'ja'), 0)
        self.assertEqual(
            UserStringTranslation.query.filter_by(target_lang='ja').count(), 1)

    def test_identifiers_are_stored_as_skipped(self):
        from aot.databases.models.user_string_translation import (
            STATUS_SKIPPED, UserStringTranslation)
        ust.enqueue({'AC1F09FFFE0812B4': 'device'}, 'ja')
        row = UserStringTranslation.query.filter_by(target_lang='ja').first()
        self.assertEqual(row.status, STATUS_SKIPPED)
        self.assertEqual(row.engine, 'identifier')

    def test_catalog_collision_is_stored_as_skipped(self):
        from aot.databases.models.user_string_translation import (
            STATUS_SKIPPED, UserStringTranslation)
        ust.enqueue({'Temperature': 'device'}, 'ko')
        row = UserStringTranslation.query.filter_by(target_lang='ko').first()
        self.assertEqual(row.status, STATUS_SKIPPED)
        self.assertEqual(row.engine, 'catalog_collision')

    def test_same_language_is_skipped(self):
        from aot.databases.models.user_string_translation import (
            STATUS_SKIPPED, UserStringTranslation)
        # 한국어 이름을 한국어로 번역할 이유가 없다.
        ust.enqueue({'남쪽 온실 상단': 'zone'}, 'ko')
        row = UserStringTranslation.query.filter_by(target_lang='ko').first()
        self.assertEqual(row.status, STATUS_SKIPPED)
        self.assertEqual(row.engine, 'same_language')

    def test_build_catalog_separates_done_from_pending(self):
        from aot.databases.models.user_string_translation import (
            STATUS_DONE, UserStringTranslation)
        from aot.aot_flask.extensions import db

        ust.enqueue({'1번 하우스': 'zone', '동편 밸브': 'device'}, 'ja')
        row = UserStringTranslation.query.filter_by(
            source_text='1번 하우스', target_lang='ja').first()
        row.translated_text = '1号ハウス'
        row.status = STATUS_DONE
        db.session.commit()

        catalog = ust.build_catalog('ja')
        self.assertEqual(catalog['entries'], {'1번 하우스': '1号ハウス'})
        self.assertEqual(catalog['pending'], ['동편 밸브'])

    def test_skipped_entries_never_reach_the_browser(self):
        # skipped 는 사전에도, pending 에도 나오면 안 된다 — 브라우저가 계속
        # 물어보게 되고 매번 LLM 호출을 유발한다.
        ust.enqueue({'AC1F09FFFE0812B4': 'device'}, 'ja')
        catalog = ust.build_catalog('ja')
        self.assertEqual(catalog['entries'], {})
        self.assertEqual(catalog['pending'], [])

    def test_fingerprint_changes_when_a_translation_lands(self):
        from aot.databases.models.user_string_translation import (
            STATUS_DONE, UserStringTranslation)
        from aot.aot_flask.extensions import db

        ust.enqueue({'1번 하우스': 'zone'}, 'ja')
        before = ust.catalog_fingerprint('ja')

        row = UserStringTranslation.query.filter_by(target_lang='ja').first()
        row.translated_text = '1号ハウス'
        row.status = STATUS_DONE
        db.session.commit()

        self.assertNotEqual(before, ust.catalog_fingerprint('ja'))

    def test_translation_never_writes_back_to_source_models(self):
        """번역이 원본 이름을 건드리지 않는다 — 이 기능의 제1 원칙."""
        from aot.databases.models import Input
        from aot.databases.models.user_string_translation import (
            STATUS_DONE, UserStringTranslation)
        from aot.aot_flask.extensions import db

        probe = Input(name='1번 하우스 온습도', unique_id='test-input-ust')
        db.session.add(probe)
        db.session.commit()

        ust.enqueue({'1번 하우스 온습도': 'device'}, 'ja')
        row = UserStringTranslation.query.filter_by(target_lang='ja').first()
        row.translated_text = '1号ハウス温湿度'
        row.status = STATUS_DONE
        db.session.commit()

        db.session.expire_all()
        stored = Input.query.filter_by(unique_id='test-input-ust').first()
        self.assertEqual(stored.name, '1번 하우스 온습도')

        Input.query.filter_by(unique_id='test-input-ust').delete()
        db.session.commit()

if __name__ == '__main__':
    unittest.main()
