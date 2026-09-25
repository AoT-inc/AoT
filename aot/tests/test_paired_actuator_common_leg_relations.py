# coding=utf-8
"""`paired_actuator_common.parse_leg_ref`/`paired_leg_relations` 순수 로직 테스트.

이 파싱은 데몬 쪽 인터락 가드(`controller_output.py`)와 출력 페이지의 "짝
액추에이터가 사용 중" 표시(`routes_output.py`) 양쪽이 그대로 재사용한다 —
여기서만 지키면 두 소비자가 저마다 다시 구현하다 갈리는 일이 없다.
"""
import pytest

from aot.outputs.paired_actuator_common import (
    parse_leg_ref,
    paired_leg_relations,
)


@pytest.fixture
def app(tmp_path, monkeypatch):
    """`db_retrieve_table_daemon` 이 읽는 파일과 Flask 세션이 같은 파일을 보게 한다.

    `fetch_paired_leg_relations()` 는 `db_retrieve_table_daemon` 을 거치고,
    그 함수는 `aot.utils.database.AOT_DB_PATH`(conftest 가 세션 전체에 하나
    만들어 둔 임시 DB)를 직접 연다 — 그대로 두면 이 파일이 만든 행을 다른
    테스트가 공유 DB 에서 보게 되거나(순서 의존), 그 반대로 여기서 남은
    행이 다른 파일의 가정을 깬다. 그래서 이 테스트 전용 sqlite 파일을 새로
    만들고, `AOT_DB_PATH` 를 그쪽으로 잠깐 돌린다 — Flask 세션과
    `db_retrieve_table_daemon` 이 같은(하지만 이 테스트만의) 파일을 보되,
    세션 공유 DB 는 건드리지 않는다.
    """
    from aot.aot_flask.app import create_app
    from aot.aot_flask.extensions import db
    from aot.config import ProdConfig

    db_file = tmp_path / "paired_leg_relations.db"
    db_uri = f"sqlite:///{db_file}"
    monkeypatch.setattr('aot.utils.database.AOT_DB_PATH', db_uri)

    class _Config(ProdConfig):
        SQLALCHEMY_DATABASE_URI = db_uri

    application = create_app(config=_Config)
    with application.app_context():
        db.create_all()
    yield application
    with application.app_context():
        db.session.remove()


class TestParseLegRef:
    def test_empty_ref_is_unresolved(self):
        assert parse_leg_ref('', {}) == ('', 0)
        assert parse_leg_ref(None, {}) == ('', 0)

    def test_legacy_bare_output_id_is_channel_zero(self):
        assert parse_leg_ref('output-1', {}) == ('output-1', 0)

    def test_output_id_comma_channel_uid_resolves_via_map(self):
        uid_map = {'chan-uid-9': 3}
        assert parse_leg_ref('output-1,chan-uid-9', uid_map) == ('output-1', 3)

    def test_channel_uid_not_in_map_falls_back_to_channel_zero(self):
        assert parse_leg_ref('output-1,unknown-uid', {}) == ('output-1', 0)

    def test_select_channel_dict_form(self):
        ref = {'device_id': 'output-1', 'channel_id': 'chan-uid-9'}
        assert parse_leg_ref(ref, {'chan-uid-9': 2}) == ('output-1', 2)

    def test_select_channel_dict_with_no_device_is_unresolved(self):
        assert parse_leg_ref({'device_id': None, 'channel_id': None}, {}) == ('', 0)


class TestPairedLegRelations:
    def test_open_close_pair_points_at_each_other(self):
        rows = [('valve-1', {
            'output_open_id': 'open-relay', 'output_close_id': 'close-relay',
        })]
        relations = paired_leg_relations(rows, {}, output_names={'valve-1': '측창'})

        open_entries = relations[('open-relay', 0)]
        assert len(open_entries) == 1
        assert open_entries[0]['owner_id'] == 'valve-1'
        assert open_entries[0]['owner_name'] == '측창'
        assert open_entries[0]['leg'] == 'open'
        assert open_entries[0]['partners'] == [('close-relay', 0)]

        close_entries = relations[('close-relay', 0)]
        assert close_entries[0]['leg'] == 'close'
        assert close_entries[0]['partners'] == [('open-relay', 0)]

    def test_owner_name_falls_back_to_id_when_missing(self):
        rows = [('valve-1', {'output_open_id': 'open-relay', 'output_close_id': 'close-relay'})]
        relations = paired_leg_relations(rows, {})
        assert relations[('open-relay', 0)][0]['owner_name'] == 'valve-1'

    def test_bus_selectors_sharing_the_same_open_close_pair_are_each_others_partners(self):
        rows = [
            ('member-1', {
                'output_open_id': 'bus-open', 'output_close_id': 'bus-close',
                'selector_output_id': 'sel-1',
            }),
            ('member-2', {
                'output_open_id': 'bus-open', 'output_close_id': 'bus-close',
                'selector_output_id': 'sel-2',
            }),
        ]
        relations = paired_leg_relations(rows, {})

        sel1_partners = relations[('sel-1', 0)][0]['partners']
        sel2_partners = relations[('sel-2', 0)][0]['partners']
        assert sel1_partners == [('sel-2', 0)]
        assert sel2_partners == [('sel-1', 0)]
        assert relations[('sel-1', 0)][0]['leg'] == 'selector'

        # 같은 bus-open 다리 자체는 여전히 open/close 관계만 갖는다 — 두
        # 멤버가 공유해도 항목이 두 배로 늘지 않는다(같은 owner 가 없다).
        assert len(relations[('bus-open', 0)]) == 2

    def test_selectors_on_different_buses_do_not_interact(self):
        rows = [
            ('member-1', {
                'output_open_id': 'bus-a-open', 'output_close_id': 'bus-a-close',
                'selector_output_id': 'sel-1',
            }),
            ('member-2', {
                'output_open_id': 'bus-b-open', 'output_close_id': 'bus-b-close',
                'selector_output_id': 'sel-2',
            }),
        ]
        relations = paired_leg_relations(rows, {})
        assert relations[('sel-1', 0)][0]['partners'] == []
        assert relations[('sel-2', 0)][0]['partners'] == []

    def test_malformed_custom_options_row_is_skipped(self):
        rows = [('valve-1', None), ('valve-2', {'output_open_id': 'open-relay'})]
        relations = paired_leg_relations(rows, {})
        # valve-1(None) 은 무시되고, open 만 있는 valve-2 는 partners 없이 등록된다.
        assert relations[('open-relay', 0)][0]['partners'] == []


class TestFetchPairedLegRelationsFromDb:
    """`fetch_paired_leg_relations()` 는 위 순수 함수를 실제 DB 에서 조립한다.

    `db_retrieve_table_daemon` 은 `aot.config.AOT_DB_PATH` (세션 전체가 공유하는
    conftest 임시 DB) 를 직접 연다 — 그래서 여기서는 `test_duplication_
    reference_integrity.py` 처럼 별도 sqlite 파일을 만들지 않고, `ProdConfig`
    를 그대로 써서 Flask 세션이 같은 파일을 보게 한다.
    """

    def test_open_close_and_selector_wired_from_real_rows(self, app):
        from aot.aot_flask.extensions import db
        from aot.databases import set_uuid
        from aot.databases.models import Output, OutputChannel
        from aot.outputs.paired_actuator_common import (
            PAIRED_ACTUATOR_OUTPUT_TYPES, fetch_paired_leg_relations)
        import json

        with app.app_context():
            owner = Output(unique_id=set_uuid())
            owner.name = '측창'
            owner.output_type = sorted(PAIRED_ACTUATOR_OUTPUT_TYPES)[0]
            db.session.add(owner)

            unrelated = Output(unique_id=set_uuid())
            unrelated.name = '무관한 출력'
            unrelated.output_type = 'virtual_on_off_single'
            db.session.add(unrelated)
            db.session.commit()

            open_relay = OutputChannel(unique_id=set_uuid())
            open_relay.output_id = 'open-relay-output'
            open_relay.channel = 0
            db.session.add(open_relay)
            db.session.commit()

            ch = OutputChannel(unique_id=set_uuid())
            ch.output_id = owner.unique_id
            ch.channel = 0
            ch.custom_options = json.dumps({
                'output_open_id': f'open-relay-output,{open_relay.unique_id}',
                'output_close_id': 'close-relay-output',
            })
            db.session.add(ch)
            db.session.commit()

            relations = fetch_paired_leg_relations()

            entries = relations[('open-relay-output', 0)]
            assert len(entries) == 1
            assert entries[0]['owner_id'] == owner.unique_id
            assert entries[0]['leg'] == 'open'
            assert entries[0]['partners'] == [('close-relay-output', 0)]
            # 무관한 on/off 출력은 짝 액추에이터 타입이 아니므로 관계에 안 끼어든다.
            assert all(
                e['owner_id'] != unrelated.unique_id
                for entries_ in relations.values() for e in entries_)
            db.session.remove()

    def test_no_paired_actuators_returns_empty_map(self, app):
        from aot.aot_flask.extensions import db
        from aot.databases import set_uuid
        from aot.databases.models import Output
        from aot.outputs.paired_actuator_common import fetch_paired_leg_relations

        with app.app_context():
            out = Output(unique_id=set_uuid())
            out.name = '평범한 출력'
            out.output_type = 'virtual_on_off_single'
            db.session.add(out)
            db.session.commit()

            assert fetch_paired_leg_relations() == {}
            db.session.remove()
