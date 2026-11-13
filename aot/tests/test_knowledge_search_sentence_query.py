"""문장형 질문이 매뉴얼의 흔한 낱말에 끌려가지 않는지(희귀도 가중) 고정한다."""
from aot.ai.services import knowledge_search as ks


def _sec(file, heading, content, origin='manual'):
    return {'file': file, 'heading': heading, 'content': content,
            'keywords': '', 'origin': origin, 'tags': []}


def test_rare_domain_word_beats_common_stems(monkeypatch):
    manual = [_sec('Integrations.ko.md', '캘린더 동기화',
                   '언제부터 어떻게 해야 하나 동기화가 생기고 설정하는 방법 ' * 5)
              for _ in range(6)]
    memo = _sec('초피 메모', '초피나무 병해충', '잎 뒷면에 녹병 증상이 생긴다', 'library')
    monkeypatch.setattr(ks, '_build_index', lambda: manual)
    for fn in ('_load_library_sections',):
        monkeypatch.setattr(ks, fn, lambda: [memo])
    for fn in ('_load_external_authority_sections', '_load_semantic_note_sections',
               '_load_program_stage_sections'):
        monkeypatch.setattr(ks, fn, lambda: [])
    hits = ks.search('잎 뒷면에 녹병 언제부터 생기고 어떻게 해야 하나', top_k=1)
    assert hits and hits[0]['heading'] == '초피나무 병해충'


def test_question_words_are_dropped():
    toks = ks._tokenize('어떻게 해야 하나 녹병')
    assert '어떻' not in toks and '녹병' in toks


def test_particles_are_stripped_but_original_token_is_kept():
    toks = ks._tokenize('초피나무 가지치기는 언제 하나요')
    assert '가지치기' in toks and '가지치기는' in toks
    assert '초피나무' in toks
    # 남는 글자가 둘 미만이면 떼지 않는다
    assert ks._strip_particle('오이') == '오이'
    assert ks._strip_particle('녹병이') == '녹병'


def _patch_index(monkeypatch, manual, lib=()):
    monkeypatch.setattr(ks, '_build_index', lambda: list(manual))
    monkeypatch.setattr(ks, '_load_library_sections', lambda: list(lib))
    for fn in ('_load_external_authority_sections', '_load_semantic_note_sections',
               '_load_program_stage_sections'):
        monkeypatch.setattr(ks, fn, lambda: [])


def test_stem_only_match_is_flagged_as_no_core_match(monkeypatch):
    manual = [_sec('guide/g14.ko.md', '세 가지', '확인할 세 가지를 본다')]
    _patch_index(monkeypatch, manual)
    hits = ks.search('초피나무 가지치기는 언제 하나요', top_k=3)
    assert hits and ks.lacks_core_match('초피나무 가지치기는 언제 하나요', hits)
    text = ks.search_as_text('초피나무 가지치기는 언제 하나요')
    assert "'초피나무' 에 대한 내용이 없습니다" in text


def test_domain_note_matches_core_word_and_has_no_notice(monkeypatch):
    memo = _sec('초피 메모', '초피나무 가지치기', '잎 나기 전 겨울에 전정한다', 'library')
    _patch_index(monkeypatch, [_sec('guide/g14.ko.md', '세 가지', '세 가지를 본다')], [memo])
    q = '초피나무 가지치기는 언제 하나요'
    hits = ks.search(q, top_k=1)
    assert hits[0]['heading'] == '초피나무 가지치기'
    assert not ks.lacks_core_match(q, hits)
    assert '내용이 없습니다' not in ks.search_as_text(q, top_k=1)


def test_non_hangul_query_is_never_flagged(monkeypatch):
    _patch_index(monkeypatch, [_sec('a.md', 'x', 'unrelated')])
    assert ks.lacks_core_match('how to prune', []) is False


def test_verb_ending_and_known_words_do_not_trigger_notice(monkeypatch):
    manual = [_sec('guide/g05.ko.md', '입력 추가하기', '센서를 추가하는 방법. 알아볼 것이 생기면 본다')]
    _patch_index(monkeypatch, manual)
    for q in ('센서를 추가하려면 어떻게 하나요', '추가할 것을 알아보려면 어떻게 하나요'):
        hits = ks.search(q, top_k=3)
        assert hits and not ks.lacks_core_match(q, hits), q
