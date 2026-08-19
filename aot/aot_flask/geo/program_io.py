# coding=utf-8
"""관리 프로그램의 쓰기 경로 — 생성·복제·수정·삭제.

식생만이 아니라 가축·시설물·도로도 같은 구조로 다룬다(`kind`).

설계 정본: docs/design/program-layer.md

불변식을 **여기 한 곳에서** 강제한다. 라우트와 AI 도구가 각자 검증하면 새 진입점이
생길 때마다 조용히 빠진다(식생 구획의 `plot_io` 와 같은 구조).

## 여기서 지키는 것

- **내장·외부는 고칠 수 없다.** 업그레이드나 외부 갱신이 그 수정을 덮어써 조용히
  되돌아간다. 고치고 싶으면 복제한다.
- **참조 중인 프로그램은 지울 수 없다.** 지우면 그 작기가 "무엇을 목표로 길렀나" 의
  근거를 잃는다. 화면은 `missing` 으로 버텨 주지만, 그것은 사고를 견디는 장치이지
  정상 경로가 아니다.
- **내용이 실제로 바뀔 때만 버전을 올린다.** 저장 버튼을 눌렀다는 이유로 올리면
  구획이 고정해 둔 버전과의 차이가 의미를 잃는다.
"""
import logging

from aot.aot_flask.extensions import db
from aot.databases.models import GeoProgram

logger = logging.getLogger(__name__)

_VALID_SOURCES = ('builtin', 'external', 'user', 'ai')

# 대상 종류 — **좁게 시작한다.** `other` 가 있어 새 종류가 필요할 때 코드를 고치지
# 않고도 담긴다. 정말 자주 쓰이면 그때 이름을 준다.
VALID_KINDS = ('vegetation', 'livestock', 'facility', 'other')


def _clean_stages(stages):
    """단계 목록 검증·정규화 → (stages, error).

    `days` 는 **그 단계의 길이**다. `None`(끝까지)을 허용하되 마지막이 아닌 자리에
    두면 그 뒤 단계는 영원히 오지 않으므로 거절한다 — 저장은 되고 화면만 이상해지는
    종류의 실수다.
    """
    if not isinstance(stages, list) or not stages:
        return None, '단계를 하나 이상 넣어야 합니다'

    out = []
    for i, st in enumerate(stages):
        if not isinstance(st, dict):
            return None, '단계 %d 의 형식이 올바르지 않습니다' % (i + 1)
        key = (st.get('key') or '').strip()
        name = (st.get('name') or '').strip()
        if not key:
            return None, '단계 %d 에 key 가 없습니다' % (i + 1)
        days = st.get('days')
        if days in ('', None):
            days = None
        else:
            try:
                days = int(days)
            except (TypeError, ValueError):
                return None, '단계 %d 의 기간이 숫자가 아닙니다' % (i + 1)
            if days <= 0:
                return None, '단계 %d 의 기간은 1일 이상이어야 합니다' % (i + 1)
        if days is None and i != len(stages) - 1:
            return None, ('기간을 비운 단계("끝까지")는 마지막에만 올 수 있습니다 '
                          '— %d번째 단계 뒤의 단계는 시작되지 않습니다' % (i + 1))
        entry = {'key': key, 'name': name or key, 'days': days}

        targets, terr = _clean_targets(st.get('targets'))
        if terr:
            return None, '단계 %d: %s' % (i + 1, terr)
        if targets:
            entry['targets'] = targets

        # 적산온도 목표(P4). `days` 와 같은 규약 — **그 단계의 길이**이지
        # 누적값이 아니다. 두 뜻이 섞이면 마지막 단계만 맞고 나머지가 다
        # 어긋나는데, 화면에서는 "단계가 이상하다" 로만 보인다.
        if st.get('gdd') not in (None, ''):
            try:
                gdd = float(st['gdd'])
            except (TypeError, ValueError):
                return None, '단계 %d 의 적산온도가 숫자가 아닙니다' % (i + 1)
            if gdd <= 0:
                return None, ('단계 %d 의 적산온도는 0보다 커야 합니다'
                              % (i + 1))
            entry['gdd'] = gdd

        # 자원(관수·시비) — 이 단계에 쓰는 Function 목록(P6).
        funcs, ferr = _clean_stage_functions(st.get('functions'))
        if ferr:
            return None, '단계 %d: %s' % (i + 1, ferr)
        if funcs:
            entry['functions'] = funcs

        # 이후 단계가 쓸 필드는 있으면 그대로 보존한다(모르는 키를 버리지 않는다).
        for extra in ('tasks',):
            if st.get(extra) is not None:
                entry[extra] = st[extra]
        out.append(entry)
    return out, None


# 단계별 목표 — 키와 범위를 여기서 못 박는다.
#
# **어휘를 고정하는 이유**: 화면·AI·(나중의) 제어가 같은 키를 읽어야 한다. 자유
# dict 로 두면 `temp`/`temperature`/`t_day` 가 섞여 들어오고, 그것을 읽는 쪽이
# 각자 추측하게 된다 — 이 저장소가 반복해서 겪은 실패다.
#
# 범위는 **틀린 값을 막기 위한 것이지 정답을 정하는 것이 아니다.** 사람이 아는
# 재배 방식이 표준과 다를 수 있으므로 넓게 잡는다.
# 단위는 여기서 한 벌만 정한다 — 화면이 각자 들고 있으면 항목을 늘릴 때
# 한쪽만 늘어난다(키 어휘를 서버에 못 박은 것과 같은 이유).
# 자원 역할. **좁게 시작한다** — 어휘는 한 번 퍼지면 되돌리기 어렵다.
# 'other' 가 있으므로 새 역할이 필요할 때 코드를 고치지 않고도 담을 수 있고,
# 정말 자주 쓰이면 그때 이름을 준다(`GeoProgram.kind` 와 같은 태도).
_RESOURCE_ROLES = ('irrigation', 'fertigation', 'other')

_TARGET_UNITS = {
    'temp_day': '\u00b0C', 'temp_night': '\u00b0C', 'rh': '%',
    'co2': 'ppm', 'dli': 'mol/m\u00b2/d', 'vpd': 'kPa',
}

_TARGET_FIELDS = {
    'temp_day':   (-30.0, 60.0),   # °C
    'temp_night': (-30.0, 60.0),   # °C
    'rh':         (0.0, 100.0),    # %
    'co2':        (0.0, 5000.0),   # ppm
    'dli':        (0.0, 80.0),     # mol/m²/day
    'vpd':        (0.0, 10.0),     # kPa
}


def _clean_targets(targets):
    """단계 목표 검증 → (dict|None, error).

    빈 값은 **넣지 않는다**(`None` 으로 채우지 않는다) — 키가 있는데 값이 없으면
    읽는 쪽이 "0" 인지 "미지정" 인지 구분할 수 없다.

    ⚠ 이 값은 지금 **표시·조언용**이다. 제어에 자동 반영되지 않는다(그 연결은
    `suggest`/`apply` 모드에서 사람이 켠다 — docs/design/program-layer.md).
    """
    if targets in (None, '', {}):
        return None, None
    if not isinstance(targets, dict):
        return None, '목표 형식이 올바르지 않습니다'

    out = {}
    for key, value in targets.items():
        if key not in _TARGET_FIELDS:
            return None, '알 수 없는 목표 항목: %s' % key
        if value in (None, ''):
            continue
        try:
            num = float(value)
        except (TypeError, ValueError):
            return None, '%s 값이 숫자가 아닙니다' % key
        lo, hi = _TARGET_FIELDS[key]
        if not (lo <= num <= hi):
            return None, '%s 값이 범위를 벗어납니다 (%g~%g)' % (key, lo, hi)
        out[key] = num
    return (out or None), None




def _clean_stage_functions(value):
    """단계의 자원 함수 목록 검증 → (list|None, error).

    `[{'id': <unique_id>, 'role': 'irrigation'|'fertigation'|'other'}]`.

    **실존하지 않는 함수는 저장 시점에 거절한다** — 죽은 참조를 받아 두면 나중에
    화면이 "자원이 있는데 안 돈다" 를 만나고, 그때는 원인이 프로그램인지 함수인지
    알 수 없다(목표 곡선과 같은 규율).

    이미 저장된 뒤에 함수가 지워지는 것은 막을 수 없다. 그쪽은 조용히 빼지 않고
    화면이 "없는 함수" 로 보인다(`plot_context.stage_resources`).
    """
    if value in (None, '', []):
        return None, None
    if not isinstance(value, list):
        return None, '자원 형식이 올바르지 않습니다'

    from aot.databases.models import Conditional, CustomController, PID, Trigger

    out = []
    seen = set()
    for item in value:
        if isinstance(item, str):
            item = {'id': item}
        if not isinstance(item, dict):
            return None, '자원 항목 형식이 올바르지 않습니다'
        fid = (item.get('id') or '').strip()
        if not fid:
            continue
        if fid in seen:
            continue                       # 같은 함수를 두 번 적어도 한 번만
        role = (item.get('role') or 'other').strip()
        if role not in _RESOURCE_ROLES:
            return None, '알 수 없는 자원 역할: %s' % role
        found = False
        for model in (CustomController, Conditional, Trigger, PID):
            if model.query.filter_by(unique_id=fid).first() is not None:
                found = True
                break
        if not found:
            return None, '함수를 찾을 수 없습니다: %s' % fid
        seen.add(fid)
        out.append({'id': fid, 'role': role})
    return (out or None), None


def _check_t_base(photo):
    """`photosynthesis.T_base` 가 있으면 숫자·범위인지 본다 → error|None.

    GDD 의 기준온도다. 틀린 값이 들어가면 적산이 통째로 어긋나는데 **에러가 나지
    않는다** — 단계가 너무 빨리 넘어가거나 영영 안 넘어갈 뿐이다. 범위는 틀린
    값을 막기 위한 것이지 정답을 정하는 것이 아니다(작물마다 다르다).
    """
    if not isinstance(photo, dict) or photo.get('T_base') in (None, ''):
        return None
    try:
        val = float(photo['T_base'])
    except (TypeError, ValueError):
        return '기준온도(T_base)가 숫자가 아닙니다'
    if not (-20.0 <= val <= 40.0):
        return '기준온도(T_base)가 범위를 벗어납니다 (-20~40)'
    return None


def _clean_target_methods(methods):
    """목표 곡선 참조 검증 → (dict|None, error).

    `{목표항목: Method.unique_id}`. 항목 어휘는 단계 목표와 **같아야 한다** —
    화면·해석이 두 어휘를 각자 기억하게 되면 한쪽만 고쳐진다.

    **실존하지 않는 Method 는 거절한다.** 죽은 참조를 두면 나중에 목표를 읽는
    쪽이 "곡선이 있는데 값이 안 나온다" 를 만나고, 그때는 원인이 프로그램인지
    함수인지 알 수 없다.
    """
    if methods in (None, '', {}):
        return None, None
    if not isinstance(methods, dict):
        return None, '목표 곡선 형식이 올바르지 않습니다'

    from aot.databases.models import Method

    out = {}
    for key, value in methods.items():
        if key not in _TARGET_FIELDS:
            return None, '알 수 없는 목표 항목: %s' % key
        uuid = (value or '').strip() if isinstance(value, str) else value
        if not uuid:
            continue
        if Method.query.filter_by(unique_id=uuid).first() is None:
            return None, '메서드를 찾을 수 없습니다: %s' % uuid
        out[key] = uuid
    return (out or None), None


def _apply_fields(row, data):
    """수정 가능한 필드만 반영 → 내용이 바뀌었으면 True."""
    changed = False
    if 'kind' in data:
        kind = (data.get('kind') or '').strip()
        if kind not in VALID_KINDS:
            return None, '대상 종류 허용값 아님: %r' % kind
        if row.kind != kind:
            row.kind = kind
            changed = True

    for field in ('name', 'variety', 'notes', 'source_note'):
        if field not in data:
            continue
        value = data.get(field)
        if isinstance(value, str):
            value = value.strip()
        value = value or None
        if field == 'name' and not value:
            return None, '이름은 비울 수 없습니다'
        if getattr(row, field) != value:
            setattr(row, field, value)
            changed = True

    if 'stages' in data:
        stages, err = _clean_stages(data.get('stages'))
        if err:
            return None, err
        if row.stage_list() != stages:
            row.stages = stages
            changed = True

    if 'targets_methods' in data:
        tm, terr = _clean_target_methods(data.get('targets_methods'))
        if terr:
            return None, terr
        if (row.targets_methods or None) != tm:
            row.targets_methods = tm
            changed = True

    if 'auto_advance' in data:
        row.auto_advance = bool(data.get('auto_advance'))

    if 'photosynthesis' in data:
        photo = data.get('photosynthesis') or None
        perr = _check_t_base(photo)
        if perr:
            return None, perr
        if (row.photosynthesis or None) != photo:
            row.photosynthesis = photo
            changed = True
    return changed, None


def create_program(data, source='user'):
    """새 프로그램 → (dict, error).

    `source='ai'` 는 `reviewed_at` 이 비어 있으므로 **제어에 쓰이지 않는다**
    (모델 `usable_for_control`). AI 가 지어낸 단계 기간과 목표가 곧바로 온실
    설정이 되지 않게 하는 유일한 장치라, 여기서 자동으로 채우지 않는다.
    """
    if source not in _VALID_SOURCES:
        return None, 'source 허용값 아님: %r' % source

    name = (data.get('name') or '').strip()
    # `crop` 도 받는다 — AI 도구·옛 호출부가 그 이름을 쓴다. 저장은 `subject` 다.
    subject = (data.get('subject') or data.get('crop') or '').strip()
    kind = (data.get('kind') or 'vegetation').strip()
    if not name:
        return None, '이름이 필요합니다'
    if not subject:
        return None, '대상이 필요합니다'
    if kind not in VALID_KINDS:
        return None, '대상 종류 허용값 아님: %r' % kind

    stages, err = _clean_stages(data.get('stages'))
    if err:
        return None, err

    tmethods, err = _clean_target_methods(data.get('targets_methods'))
    if err:
        return None, err

    row = GeoProgram(
        name=name, subject=subject, kind=kind,
        variety=(data.get('variety') or '').strip() or None,
        source=source,
        source_ref=(data.get('source_ref') or None),
        source_note=(data.get('source_note') or None),
        derived_from=(data.get('derived_from') or None),
        stages=stages,
        targets_methods=tmethods,
        photosynthesis=data.get('photosynthesis') or None,
        auto_advance=bool(data.get('auto_advance')),
        notes=(data.get('notes') or None),
        version=1)
    try:
        db.session.add(row)
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        logger.error('[CropProgram] 생성 실패: %s', exc)
        return None, str(exc)
    return to_dict(row), None


def clone_program(program_uuid, data=None):
    """기존 프로그램을 **복제**해 내 것으로 만든다 → (dict, error).

    내장·외부를 고치는 유일한 방법이다. `derived_from` 은 **출처 기록**이지
    링크가 아니다 — 원본이 바뀌어도 복제본은 따라가지 않는다(따라가면 "내 것" 이
    아니게 된다).
    """
    data = data or {}
    src = GeoProgram.query.filter_by(unique_id=program_uuid).first()
    if src is None:
        return None, '프로그램을 찾을 수 없습니다: %s' % program_uuid

    payload = {
        'name': data.get('name') or ('%s (사본)' % src.name),
        'subject': data.get('subject') or data.get('crop') or src.subject,
        'kind': data.get('kind') or src.kind,
        'variety': data.get('variety', src.variety),
        'stages': data.get('stages') or src.stage_list(),
        'photosynthesis': data.get('photosynthesis') or src.photosynthesis,
        'targets_methods': data.get('targets_methods') or src.targets_methods,
        'notes': data.get('notes', src.notes),
        'derived_from': src.unique_id,
    }
    return create_program(payload, source='user')


def update_program(program_uuid, data):
    """수정 → (dict, error). 내장·외부는 거절한다."""
    row = GeoProgram.query.filter_by(unique_id=program_uuid).first()
    if row is None:
        return None, '프로그램을 찾을 수 없습니다: %s' % program_uuid
    if not row.is_editable():
        return None, ('내장·외부 프로그램은 직접 고칠 수 없습니다. '
                      '복제한 뒤 고치세요.')

    changed, err = _apply_fields(row, data)
    if err:
        db.session.rollback()
        return None, err

    # 사람이 AI 프로그램을 확인했다는 표시. 이게 있어야 제어에 쓸 수 있다.
    if data.get('reviewed') is True and row.reviewed_at is None:
        from aot.utils.time_utils import utc_now
        row.reviewed_at = utc_now()
        changed = True

    if changed:
        # 내용이 실제로 바뀔 때만 올린다 — 저장 버튼을 눌렀다는 이유로 올리면
        # 구획이 고정해 둔 버전과의 차이가 의미를 잃는다.
        row.version = (row.version or 1) + 1
    try:
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        logger.error('[CropProgram] 수정 실패: %s', exc)
        return None, str(exc)
    return to_dict(row), None


def delete_program(program_uuid):
    """삭제 → (dict, error). **쓰는 구획이 있으면 거절한다.**

    지우면 그 작기가 "무엇을 목표로 길렀나" 의 근거를 잃는다. 화면은 `missing`
    으로 버티지만 그것은 사고를 견디는 장치이지 정상 경로가 아니다. 정말 지우려면
    구획에서 프로그램을 먼저 해제한다.
    """
    from aot.databases.models import GeoPlot

    row = GeoProgram.query.filter_by(unique_id=program_uuid).first()
    if row is None:
        return None, '프로그램을 찾을 수 없습니다: %s' % program_uuid

    used = GeoPlot.query.filter_by(program_uuid=program_uuid).count()
    if used:
        return None, ('이 프로그램을 쓰는 구획이 %d 건 있습니다. '
                      '먼저 그 구획에서 프로그램을 해제하세요.' % used)
    try:
        db.session.delete(row)
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        return None, str(exc)
    return {'ok': True, 'deleted': program_uuid}, None


def to_dict(row, with_stages=True):
    """API 응답 형태. 목록에서는 `with_stages=False` 로 단계를 뺀다."""
    out = {
        'unique_id': row.unique_id,
        'name': row.name,
        'kind': row.kind,
        'subject': row.subject,
        'variety': row.variety,
        'source': row.source,
        'source_ref': row.source_ref,
        'source_note': row.source_note,
        'derived_from': row.derived_from,
        'reviewed_at': row.reviewed_at.isoformat() if row.reviewed_at else None,
        'version': row.version,
        'stage_count': len(row.stage_list()),
        'total_days': row.total_days(),
        'editable': row.is_editable(),
        'usable_for_control': row.usable_for_control(),
        'notes': row.notes,
    }
    # 곡선 유무는 목록에서도 보여야 한다 — "이 프로그램은 값이 변한다" 는 사실이
    # 단계 수만큼이나 중요하다.
    out['target_methods'] = row.targets_methods or {}
    if with_stages:
        out['stages'] = row.stage_list()
        out['photosynthesis'] = row.photosynthesis
    out['auto_advance'] = bool(getattr(row, 'auto_advance', False))
    return out
