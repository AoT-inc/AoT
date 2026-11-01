# -*- coding: utf-8 -*-
"""대상 별칭 등록·목록·지우기 — 표는 `aot.databases.models.target_alias`.

별칭은 사용자가 정하는 데이터다. AI 는 사용자가 "이걸 앞으로 OO 라고 불러" 라고 했을 때만
등록한다. 해석(`targets._alias_candidates`)이 이름보다 먼저 본다.

규칙:
- 같은 별칭(이름 열쇠가 같은 것)이 **다른** 대상에 이미 있으면 저장하지 않고 그 대상을
  알려 준다 — 한 별칭은 한 대상이다. 옮기려면 그 별칭을 지운 뒤 다시 등록한다.
  가리키던 대상이 지워진 별칭은 남아 있어도 막지 않는다(새 대상으로 바꾼다).
- 별칭이 다른 대상의 **이름**과 같으면 저장하되 경고한다 — 이제 그 말은 별칭의 대상이다.
"""
from aot.tools.domain import targets
from aot.tools.name_key import name_key

MAX_LEN = 80


def _brief(t):
    return {k: t.get(k) for k in ('kind', 'id', 'name', 'path')}


def _live(row):
    try:
        return targets._by_id(row.target_id)
    except targets._Refused:
        return {'kind': row.target_kind, 'id': row.target_id, 'name': row.target_id,
                'path': row.target_id}


def add(alias, target, user=None):
    """별칭 하나를 대상(해석 결과 dict)에 붙인다 → 응답 본문 dict."""
    from aot.aot_flask.extensions import db
    from aot.databases.models import TargetAlias
    text = ' '.join(str(alias or '').split())
    key = name_key(text)
    if not key:
        return {"status": "error", "reason_code": "bad_alias",
                "message": "alias is empty — nothing was saved."}
    if len(text) > MAX_LEN:
        return {"status": "error", "reason_code": "bad_alias",
                "message": "alias is longer than %d characters — nothing was saved." % MAX_LEN}
    try:
        clash = [t for t in targets._exact_candidates(text, ('widget', 'dashboard', 'tab'))
                 if t['id'] != target['id']]
    except targets._Refused:
        clash = []
    if key == name_key(target.get('name')) and not clash:
        # 제 이름과 같은 별칭은 다른 것과 겹칠 때만 뜻이 있다(위젯·시설 '육묘장').
        return {"status": "success", "already": True, "alias": text, "target": _brief(target),
                "message": "'%s' is already its name." % text}
    rows = TargetAlias.query.filter(TargetAlias.alias_key == key).all()
    if any(r.target_id == target['id'] for r in rows):
        return {"status": "success", "already": True, "alias": text, "target": _brief(target),
                "message": "'%s' already names it." % text}
    taken = [(r, t) for r, t in ((r, _live(r)) for r in rows) if t is not None]
    if taken:
        return {"status": "error", "reason_code": "alias_taken",
                "message": ("'%s' already names %s. Nothing was saved — tell the user. To move "
                            "it, delete that alias first, then add it again."
                            % (text, ", ".join(t['path'] or t['name'] for _r, t in taken))),
                "existing": [_brief(t) for _r, t in taken]}
    for r in rows:                                        # 대상이 지워진 별칭 — 바꾼다
        db.session.delete(r)
    db.session.add(TargetAlias(alias=text, alias_key=key, target_kind=target['kind'],
                               target_id=target['id'], created_by=user))
    db.session.commit()
    body = {"status": "success", "alias": text, "target": _brief(target)}
    if clash:
        body['warning'] = ("'%s' is also the name of %s — from now on it means %s." % (
            text, ", ".join(t['path'] or t['name'] for t in clash[:3]),
            target.get('path') or target.get('name')))
    return body


def listing(target=None):
    """별칭 목록 → 응답 본문 dict. target(해석 결과)을 주면 그 대상의 별칭만."""
    from aot.databases.models import TargetAlias
    q = TargetAlias.query
    if target is not None:
        q = q.filter(TargetAlias.target_id == target['id'])
    out = []
    for r in q.order_by(TargetAlias.alias_key).all():
        t = _live(r)
        item = {"alias": r.alias}
        if t is None:
            item.update(stale=True, target={'kind': r.target_kind, 'id': r.target_id})
        else:
            item['target'] = _brief(t)
        out.append(item)
    return {"status": "success", "count": len(out), "aliases": out}


def delete(alias, target=None):
    """별칭을 지운다 → 응답 본문 dict. target 을 주면 그 대상에 붙은 것만."""
    from aot.aot_flask.extensions import db
    from aot.databases.models import TargetAlias
    key = name_key(' '.join(str(alias or '').split()))
    q = TargetAlias.query.filter(TargetAlias.alias_key == key)
    if target is not None:
        q = q.filter(TargetAlias.target_id == target['id'])
    rows = q.all() if key else []
    if not rows:
        return {"status": "error", "reason_code": "alias_not_found",
                "message": "No alias '%s'%s — nothing was deleted." % (
                    alias, " on %s" % target.get('name') if target else "")}
    for r in rows:
        db.session.delete(r)
    db.session.commit()
    return {"status": "success", "deleted": [r.alias for r in rows]}
