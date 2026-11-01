# -*- coding: utf-8 -*-
"""도메인 표면 응답의 '행동'과 '말하기' 나누기 — 설계 plans/mcp_act_say_split_design.md §2.

AI 에게 가는 응답을 세 칸으로 나눈다.

- data — 사실. 지금 칸 그대로(해석 규칙은 `_reading` 만).
- ``next`` — AI 가 다음에 할 호출(기계용). 사용자에게 말하지 않는다.
  ``call``(지금 할 호출) · ``after_user``(사용자가 답한 뒤 할 호출) · ``resend`` · ``why``(짧은 기계 이유) ·
  ``map_time``(지도 시간 — 보이는 시각과, 답이 다른 시각을 말할 때의 호출. 못 옮겼으면 ``{moved: False, why}``).
- ``say`` — 사용자에게 꼭 전할 뜻(있을 때만). ``tell``(전할 사실) · ``ask``(물을 것 — 묻고 기다린다) · ``avoid``(하지 말 말 한 낱말).
  이름·장소·시각만 담는다. id·도구 이름·호출 문법은 넣지 않는다.

규약 세 줄(overview 머리·서버 안내문에 한 번): next 는 하되 말하지 않는다 / say 는 그 뜻을 사용자 언어로 /
say.ask 는 묻고 기다린 뒤 next.after_user.

**바꾸는 곳은 도메인 틀의 출구 한 곳**(`dispatch._run_call`)이고 시범 op(`PILOT`)에만 켠다. 안쪽 도구의 칸 이름
(`_reading`·`note`·`ask_user`·`card_hint` …)은 인앱 AI 가 읽으므로 그대로 두고, 외부 MCP 의 도메인 표면만 새 계약을
받는다(§2-4). 승인 대기(pending_approval) 응답은 op 와 상관없이 계약을 받는다(2단계, `approval_body`) — 승인 흐름
자체(토큰·만료·되읽기·승인 = 실행)는 그대로이고 글이 놓이는 칸만 바뀐다.

모양: ``status`` → ``say`` → ``next`` → 나머지 data. say 를 맨 앞에 두는 것은 효과 때문이 아니라 응답 상한으로 목록을
자를 때 위쪽이 안전하고, 긴 글 가운데 묻히지 않고, 시험하기 쉬워서다(§8).
"""
import json
import re

#: 계약을 받는 시범 op(사용자 결정 2026-10-29).
PILOT = frozenset({
    ('control', 'confirm'),         # 승인 결과(3단계, 2026-10-29) — 승인 대기의 짝
    ('find', 'resolve'),
    ('screen', 'act'),
    ('overview', 'failure'),
    ('record', 'note_add'),
    ('weather', 'forecast'),
})

#: 승인 대기(2단계, 2026-10-29 사용자 결정) — op 와 상관없이 모든 쓰기·제어의 승인 대기 응답에 계약을 건다.
#: claude.ai 는 서버 안내문(SPEAKING 의 "승인은 한 번, 되읽고, 다시 묻지 않는다")을 모델에 주지 않는다 — 응답이 그 규칙을 전한다.
PENDING = 'pending_approval'

#: 안쪽 안내문 끝의 '말하지 마라' 꼬리 — 규약 1 이 대신하므로 시범 op 응답에서는 뗀다.
_TAIL = re.compile(r"\s*(?:Internal note:|Do not tell the user about this)[^\n]*$")
#: 후보 되묻기의 화면 안내(틀이 값을 못 넣는다) — 기계 이유로 옮긴다.
_SCREEN_SHOT = re.compile(r"\s*If more than one screen is open,.*$")
#: say.ask 에 싣는 후보 수 — say 는 짧게(25단어 안팎).
_ASK_MAX = 4


def applies(tool, op):
    return (tool, op) in PILOT


def shape(out, tool, op):
    """시범 op 의 응답과 모든 승인 대기 응답을 계약 모양으로. JSON 사전이 아니면 그대로."""
    try:
        body = json.loads(out[0]['text'])
    except (TypeError, ValueError, KeyError, IndexError):
        return out
    if not isinstance(body, dict):
        return out
    if body.get('status') == PENDING:
        if not _is_framed_approval(body):
            return out
        body = approval_body(body)
    elif applies(tool, op):
        body = shape_body(body, tool, op)
    elif _has_card_hint(body):
        body = _drop_card_hint(body, tool, op)
    else:
        return out
    return [dict(out[0], text=json.dumps(body, ensure_ascii=False, default=str))] + list(out[1:])


def shape_body(body, tool, op):
    say = {}
    nxt = body.pop('next') if isinstance(body.get('next'), dict) else {}
    nxt = dict(nxt)
    _disambiguation(body, say, nxt)
    _not_found(body, say, nxt)
    handler = _BY_OP.get((tool, op))
    if handler is not None:
        handler(body, say, nxt)
    _card_hint_to_next(body, nxt, tool, op)
    _strip_tails(body)
    return _pack(body, say, nxt)


def _pack(body, say, nxt):
    """status → say → next → data 순서."""
    out = {'status': body.pop('status', None) or 'success'}
    if say:
        out['say'] = {k: v for k, v in say.items() if v}
    if nxt:
        out['next'] = nxt
    out.update(body)
    return out


def _strip_tails(body):
    for k, v in list(body.items()):
        if isinstance(v, str) and ('Internal note:' in v or 'Do not tell the user' in v):
            body[k] = _TAIL.sub('', v)


def _cue(c):
    return str(c.get('path') or c.get('name') or '?')


def _which(cands):
    names = [_cue(c) for c in cands[:_ASK_MAX] if isinstance(c, dict)]
    more = "; …" if len(cands) > _ASK_MAX else ""
    return "Which one: %s%s?" % ("; ".join(names), more)


def _cand_hints(cands):
    """후보 정렬이 알게 된 것(기계 이유) — 되묻기 문장에서 떼어 낸다."""
    hints = []
    if cands and isinstance(cands[0], dict) and cands[0].get('on_screen'):
        hints.append("the first is on the dashboard the user is viewing")
    kinds = {c.get('kind') for c in cands if isinstance(c, dict)}
    if 'widget' in kinds and len(kinds) > 1:
        hints.append("a graph is the widget")
    return hints


def _disambiguation(body, say, nxt):
    """되묻기(needs_disambiguation + candidates) → say.ask(후보 이름·경로) + next.after_user."""
    cands = body.get('candidates')
    if body.get('status') != 'needs_disambiguation' or not isinstance(cands, list) or not cands:
        return
    say['ask'] = _which(cands)
    body.pop('message', None)
    old_why = nxt.pop('why', '') or ''
    hints = _cand_hints(cands)
    shot = _SCREEN_SHOT.search(old_why)
    if shot:
        hints.append("several screens open: add screen='<id>' from screen_view op=current")
    if any(isinstance(c, dict) and c.get('resend') for c in cands):
        nxt['after_user'] = "send the chosen candidate's resend"
    else:
        nxt['after_user'] = "call again with target=<the chosen candidate's id>"
    if hints:
        nxt['why'] = "; ".join(hints)


def _not_found(body, say, nxt):
    """모르는 이름(unknown_target). 비슷한 이름이 있으면 고르지 않고 묻는다(status=not_found)."""
    if body.get('reason_code') != 'unknown_target':
        return
    key = 'error' if isinstance(body.get('error'), str) else 'message'
    text = body.get(key) if isinstance(body.get(key), str) else ''
    why = nxt.get('why')
    if why and text.endswith(why):
        # 틀이 이유를 메시지 끝에도 붙여 둔다(`plan`) — next.why 에 있으니 사실만 남긴다.
        text = text[:-len(why)].rstrip()
    fact = text.split(' Similar names:')[0].strip()
    if text:
        body[key] = fact
    near = body.get('similar')
    if isinstance(near, list) and near:
        body['status'] = 'not_found'
        names = [str(s.get('name')) for s in near[:_ASK_MAX] if isinstance(s, dict) and s.get('name')]
        say['ask'] = "Did you mean %s?" % " or ".join("'%s'" % n for n in names)
        nxt.setdefault('after_user', "call again with target=<the chosen similar id>")
        nxt.setdefault('why', "not picked - the word may be misheard; if it is the user's own name for it, "
                              "record op=alias_add saves it when they ask")
    elif not nxt.get('resend') and fact:
        say['tell'] = fact.split(' — ')[0].rstrip('.') + '.'


# ── op 별 ──────────────────────────────────────────────────────────────────

def _screen_act(body, say, nxt):
    st = body.get('status')
    note = body.get('note') if isinstance(body.get('note'), str) else None
    if st == 'needs_confirmation':
        body.pop('ask_user', None)
        body.pop('note', None)
        where, what = body.get('screen'), body.get('action')
        if where or what:
            say['ask'] = "Do this on %s: %s?" % (where or 'that screen', what or 'this')
        token = body.get('confirm_token')
        if token:
            nxt['after_user'] = "screen(op='act', confirm_token='%s')" % token
        if note and 'Allow' in note:
            nxt['why'] = "an Allow card is also on that screen; a tap there runs it without another call"
        elif note:
            nxt['why'] = "still waiting for the user's OK"
    elif st == 'sent':
        body.pop('note', None)
        nxt['why'] = "not confirmed yet (usually runs in seconds); read screen_view before sending it again"
    elif st == 'queued':
        body.pop('note', None)
        tell = "Queued: it runs when that screen is open again, within 10 minutes."
        if body.get('link'):
            tell += " On a phone, tap the link to open it."
        say.update(tell=tell, avoid='done')
    elif st in ('rejected', 'expired'):
        body.pop('note', None)
        if st == 'expired':
            say['tell'] = "Not done: the screen did not pick it up in time."
        else:
            say['tell'] = re.sub(r"\s*Ask again.*$", "", note or "Not done.").strip()
        say['avoid'] = 'done'
    elif st == 'partial':
        say.update(tell="Only partly done: %s." % (body.get('done') or 'see the result'), avoid='done')
    elif st == 'success':
        if body.pop('say', None):
            # 지도 시간 이동 뒤 — "옮겼다고 말하지 마라" 는 규약 1 이 대신한다. 답을 비우지 않게 할 일은 남긴다(10-24 실측).
            nxt['why'] = "map time is set; answer with the values you already read"
        if note and 'loading' in note:
            body.pop('note', None)
            nxt['why'] = "the page is loading; screen_view may show the old page for a few seconds"
        if body.get('center_note'):
            say['tell'] = "Opened, but the map did not move: no position is known for it."
    elif body.get('reason_code') == 'settings_dialog_open':
        m = re.search(r"\('([^']*)'\)", body.get('error') or '')
        say['tell'] = "Not changed: the settings window%s is open on that screen." % (
            " '%s'" % m.group(1) if m else "")
        say['ask'] = "Close it? Unsaved values are lost."
        say['avoid'] = 'done'
        nxt['after_user'] = "screen(op='act', action='close_modal'), then the same call again"
        body['error'] = "A settings window is open on that screen, so the page was not changed."


#: overview.failure — MCP 서버 상태를 이 프로세스에서 못 읽은 줄(모름, 오프라인 아님).
_MCP_UNKNOWN = 'not readable from this process'
_NO_CAUSE = 'Could not identify a specific error cause.'


def _failure(body, say, nxt):
    summary = body.get('failure_summary')
    if not isinstance(summary, list):
        return
    unknown = any(isinstance(s, str) and _MCP_UNKNOWN in s for s in summary)
    real = [s for s in summary if not (isinstance(s, str) and (_MCP_UNKNOWN in s or s == _NO_CAUSE))]
    body['failure_summary'] = real
    if unknown:
        body['mcp_state'] = 'unknown'
        say['avoid'] = 'offline'
    if real:
        return
    # 실패 기록이 없다 — 권고 문장(서버 재시작 …)은 과장 답을 부른다(재시험 19번). 빼고 사실만.
    body.pop('recommendation', None)
    if unknown:
        body['status'] = 'unknown'
        say['tell'] = ("No recent failures on record; the MCP server state can't be read here - "
                       "unknown, not offline.")


def _note_add(body, say, nxt):
    body.pop('note_hint', None)
    tells = []
    if body.get('no_location'):
        tells.append("Saved as a general memo with no place.")
    skipped = body.get('attach_skipped')
    if skipped:
        n = len(skipped) if isinstance(skipped, (list, tuple)) else skipped
        tells.append("%s link(s) were not attached." % n)
    if tells:
        say['tell'] = " ".join(tells)


#: PR① — 카드 안내(`card_hint`)는 행동이다. 호출 한 줄로 옮긴다("말하지 마라" 꼬리는 규약 1 이 대신한다).
CARD_CALL = "screen(op='card', title='<place> forecast', message='<one-line conclusion, max 5 lines>')"


def _forecast(body, say, nxt):
    if body.pop('card_hint', None):
        nxt.setdefault('call', CARD_CALL)
    body.pop('time_hint', None)
    for row in body.get('results') or ():
        # 여러 장소를 펼쳐 읽은 응답 — 안쪽 결과마다 붙은 안내도 뗀다(카드 호출은 한 번이다).
        inner = row.get('result') if isinstance(row, dict) else None
        if isinstance(inner, dict) and inner.pop('card_hint', None):
            nxt.setdefault('call', CARD_CALL)


# ── 승인 대기 ───────────────────────────────────────────────────────────────
#
# 승인 흐름은 그대로다(토큰 발급·만료·되읽기·승인 = 실행 한 호출, `dispatch._approval_next`·`mcp_safety_gate.gate`).
# 바뀌는 것은 글이 놓이는 칸뿐이다: 되읽기·묻기는 say.ask, 승인 뒤 보낼 정확한 호출은 next.after_user, 안전 문장
# (요청은 승인이 아니다 · 대신 승인하지 않는다 · 한 번만 묻는다 · 대상을 고치면 거절하고 새로)은 next.why 로 옮긴다.
# 안쪽 칸 `_reading`(PENDING_READING — "됐다고 말하지 마라")은 인앱 AI 도 읽는 안전 문장이라 그대로 둔다.

#: 되읽기 끝의 묻는 말 — 사용자 언어로 옮기는 것은 규약(say = 그 뜻을 사용자 언어로)이다.
APPROVAL_ASK = "%s — if this is right, please approve."
#: 승인 안전 문장(옛 `_approval_next` 의 1_ask·2_answer·message 와 게이트 message 에서 옮김). 지우지 않는다.
APPROVAL_WHY = ("Ask once, then wait. Their request alone is not approval (it may name the wrong target); only a yes "
                "to this read-back counts - never approve for them. After the yes, send after_user at once, no second "
                "ask; it also runs it - report and stop. Target corrected: send if_no, then a new request.")
#: 되읽기의 'duration_seconds=30' 같은 인자 표기 → 'duration seconds 30'(say 에는 호출 문법을 싣지 않는다).
_ARG_EQ = re.compile(r"\b([a-z][a-z0-9]*(?:_[a-z0-9]+)+)=")


def _is_framed_approval(body):
    """도메인 틀이 승인 대기 다음 단계를 실은 응답인가(`dispatch._approval_next`)."""
    nxt = body.get('next')
    return bool(body.get('confirmation_id')) and isinstance(nxt, dict) and '2_answer' in nxt


def approval_body(body):
    cid = body['confirmation_id']
    old = body.pop('next')
    body.pop('message', None)
    read_back = body.pop('confirm_with_user', None)
    say = {'avoid': 'done'}
    if read_back:
        text = _ARG_EQ.sub(lambda m: m.group(1).replace('_', ' ') + ' ', str(read_back))
        say['ask'] = APPROVAL_ASK % text.strip()
    else:
        # 같은 번호로 다시 불렀는데 아직 승인 전 — 되읽기는 이미 했다.
        say['tell'] = "Still waiting for the user's approval."
    nxt = {
        'after_user': "control(op='confirm', target='%s', decision='approve')" % cid,
        'if_no': "control(op='confirm', target='%s', decision='reject')" % cid,
        'why': APPROVAL_WHY,
    }
    run = str(old.get('3_run') or '')
    if run:
        nxt['if_not_run'] = run.split(': ', 1)[-1]
    if 'same_arguments' in old:
        nxt['same_arguments'] = old['same_arguments']
    _strip_tails(body)
    return _pack(body, say, nxt)


#: 대상 여럿을 한 번에 건 요청(`Op.fan_write`)의 승인 대기 — 번호는 대상마다 하나, 승인은 한 번.
BATCH_AFTER = "control(op='confirm', confirmation_ids=%s, decision='%s')"


def batch_pending(asked, refused):
    """`dispatch._fan_write` 의 결과 → 응답 블록. asked: 승인 대기가 된 대상들(이름·경로·번호·되읽기),
    refused: 안쪽 도구가 거절한 대상들. 모양은 다른 승인 대기와 같다: status → say → next → data."""
    if not asked:
        why = [r.get('message') for r in refused if r.get('message')]
        body = {'status': 'refused',
                'reason_code': next((r['reason_code'] for r in refused if r.get('reason_code')),
                                    'not_requested'),
                'message': "Nothing was run or asked: " + (why[0] if why else "every target was refused."),
                'results': refused}
        return [{"type": "text", "text": json.dumps(body, ensure_ascii=False, default=str)}]
    ids = [a['confirmation_id'] for a in asked]
    lines = []
    for a in asked:
        line = str(a.get('read_back') or a.get('name') or '?')
        if a.get('path') and a['path'] != a.get('name'):
            line += " (%s)" % a['path']
        lines.append(_ARG_EQ.sub(lambda m: m.group(1).replace('_', ' ') + ' ', line))
    say = {'avoid': 'done',
           'ask': APPROVAL_ASK % ("%d outputs: %s" % (len(asked), "; ".join(lines)))}
    if refused:
        say['tell'] = "Not asked for %s: %s" % (
            ", ".join(str(r.get('name') or '?') for r in refused),
            str(refused[0].get('message') or 'refused')[:160])
    nxt = {'after_user': BATCH_AFTER % (json.dumps(ids), 'approve'),
           'if_no': BATCH_AFTER % (json.dumps(ids), 'reject'),
           'why': APPROVAL_WHY + " One yes covers all the listed ids; send it once."}
    body = {'status': PENDING, 'say': say, 'next': nxt,
            'confirmation_ids': ids,
            'targets': [{k: a.get(k) for k in ('name', 'path', 'confirmation_id')} for a in asked]}
    if refused:
        body['not_requested'] = refused
    return [{"type": "text", "text": json.dumps(body, ensure_ascii=False, default=str)}]


# ── 승인 결과(control.confirm) ──────────────────────────────────────────────
#
# 승인 = 실행 한 호출(2026-10-25)의 결과다. 승인 흐름은 그대로이고(`tool_execution._respond_to_confirmation`·
# `_run_after_approval`), 그 응답의 message("결과를 알려라 + 다시 부르지 마라 + Internal note …")를 say(사람에게 전할 결과)와
# next(다시 부르지 않음·다시 묻지 않음)로 나눈다. 안쪽 칸(_reading·execution·executed·unconfirmed)은 그대로 둔다.

#: 끝난 결정 — 다시 부르지도, 다시 묻지도 않는다.
CONFIRM_DONE = "finished: do not call the operation again and do not ask for approval again"
#: 승인됐는데 서버가 실행하지 않은 옛 경로(실행 신원 없음) — 같은 operation 을 그 번호로 다시 부른다.
CONFIRM_RUN = "run it now: the same operation with the same arguments and _confirmation_id='%s'"
#: 사용자에게 알릴 사실로 쓰는 오류(인자 오류는 기계 이유로 남긴다).
_CONFIRM_FACTS = {
    'already_decided': "It was already handled.",
    'insufficient_role': "This connection may not approve requests.",
    'group_scope_denied': "Not approved: the user's permissions do not cover that target.",
    'tool_profile': "Not approved: that kind of work is off for this connection.",
}


def _one_confirm(r):
    """승인 결과 한 건 → (say 조각, next 이유, 분류). 분류: done/rejected/not_run/unknown/run/error/None."""
    st, new = r.get('status'), r.get('new_status')
    msg = r.get('message') if isinstance(r.get('message'), str) else ''
    if st == 'success' and new == 'approved':
        if 'executed' not in r:
            return None, CONFIRM_RUN % r.get('confirmation_id'), 'run'
        r.pop('message', None)
        if r.get('executed'):
            return "Approved and done - give the result from execution.", CONFIRM_DONE, 'done'
        if r.get('unconfirmed'):
            return ("Approved and sent, but whether it ran is unknown - check its state before saying it did.",
                    "do not resend it; read its state first; do not ask for approval again", 'unknown')
        return ("Approved, but it did not run - say why, from execution.",
                "do not retry on your own and do not ask for approval again", 'not_run')
    if st == 'success' and new == 'rejected':
        r.pop('message', None)
        return "Rejected - nothing was done.", CONFIRM_DONE, 'rejected'
    if st in ('error', 'refused'):
        if 'expired' in msg:
            return ("The approval expired - nothing was done.",
                    "if the user still wants it, make the request again (a new read-back)", 'error')
        fact = _CONFIRM_FACTS.get(r.get('reason_code'))
        if fact:
            return fact, CONFIRM_DONE, 'error'
    return None, None, None


def _confirm(body, say, nxt):
    results = body.get('results')
    if body.get('status') == 'batch_complete' and isinstance(results, list):
        counts = {}
        whys = []
        for r in results:
            if not isinstance(r, dict):
                continue
            _s, why, kind = _one_confirm(r)
            _strip_tails(r)
            if kind:
                counts[kind] = counts.get(kind, 0) + 1
            if why and why not in whys:
                whys.append(why)
        words = {'done': 'approved and done', 'rejected': 'rejected', 'not_run': 'approved but not run',
                 'unknown': 'approved, result unknown', 'run': 'approved', 'error': 'not handled'}
        parts = ["%d %s" % (counts[k], words[k]) for k in words if counts.get(k)]
        if parts:
            say['tell'] = "Of %d: %s - give each result." % (len(results), ", ".join(parts))
            if counts.get('not_run') or counts.get('unknown') or counts.get('error') or counts.get('rejected'):
                say['avoid'] = 'all done'
        if whys:
            nxt['why'] = "; ".join(whys)
        return
    tell, why, kind = _one_confirm(body)
    if tell:
        say['tell'] = tell
        if kind != 'done':
            say['avoid'] = 'done'
    if why:
        nxt['call' if kind == 'run' else 'why'] = why


# ── 옛 카드 안내(card_hint) ───────────────────────────────────────────────────
#
# 날씨·장소 요약 카드는 서버가 올린다(#370). 그 밖의 조회에 붙던 "Summary or weather answer: show one card now …"
# 안내는 도메인 표면에서는 뗀다 — 글로 시킨 카드 안내는 이행률을 바꾸지 못했다(설계 §8 실측: 안내 없음 45%, 끝 42%,
# 앞 40%). 서버 카드가 맡는 조회(server_card.OPS)에서 서버가 올리지 못한 경우만 계약의 next.call 로 남긴다(AI 가
# 올릴 길). 인앱 AI 는 이 출구를 지나지 않으므로 card_hint 를 그대로 받는다.

#: 서버가 카드를 맡는 조회 — `server_card.OPS` 와 같다(순환 import 를 피해 여기 적는다; 시험이 둘을 맞춰 본다).
SERVER_CARD_OPS = frozenset({('overview', 'place'), ('weather', 'now'), ('weather', 'forecast')})
#: 서버가 못 올린 요약 카드 — AI 가 올린다.
SUMMARY_CARD_CALL = "screen(op='card', title='<place> summary', message='<one-line conclusion, max 5 lines>')"


def _hint_rows(body):
    rows = [body]
    for row in body.get('results') or ():
        inner = row.get('result') if isinstance(row, dict) else None
        if isinstance(inner, dict):
            rows.append(inner)
    return rows


def _has_card_hint(body):
    return any('card_hint' in r for r in _hint_rows(body))


def _pop_card_hints(body):
    found = False
    for r in _hint_rows(body):
        if r.pop('card_hint', None) is not None:
            found = True
    return found


def _card_hint_to_next(body, nxt, tool, op):
    if _pop_card_hints(body) and (tool, op) in SERVER_CARD_OPS:
        nxt.setdefault('call', CARD_CALL if tool == 'weather' else SUMMARY_CARD_CALL)


def _drop_card_hint(body, tool, op):
    """시범 밖 op — 안내만 떼고 다른 칸은 손대지 않는다(서버 카드가 못 올린 경우만 next.call)."""
    nxt = {}
    _card_hint_to_next(body, nxt, tool, op)
    if nxt:
        old = body.get('next') if isinstance(body.get('next'), dict) else None
        if old is not None:
            old.update({k: v for k, v in nxt.items() if k not in old})
        else:
            body['next'] = nxt
    return body


_BY_OP = {
    ('control', 'confirm'): _confirm,
    ('screen', 'act'): _screen_act,
    ('overview', 'failure'): _failure,
    ('record', 'note_add'): _note_add,
    ('weather', 'forecast'): _forecast,
}
