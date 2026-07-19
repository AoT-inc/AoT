# coding=utf-8
"""
method_preset_seeder.py — 작물별 VPD Method 프리셋 시드 데이터를 DB에 임포트.

규칙:
  - is_seed=True 인 시드는 덮어쓰지 않는다 (신규 추가만).
  - 이미 같은 (crop, stage) 조합이 존재하면 스킵.
  - 호출: aot startup 또는 관리자 명령으로 실행.

경고 (사용자에게 표시):
  "프리셋은 시작점일 뿐입니다. 본 농가 환경에 맞게 반드시 조정하세요."
"""

import json
import os
import logging

logger = logging.getLogger(__name__)

_PRESET_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'method_presets')

_CROP_ORDER = ['tomato', 'strawberry', 'lettuce', 'paprika', 'pepper']


def seed_method_presets():
    """시드 파일에서 Method + MethodData 를 DB에 추가 (신규만)."""
    try:
        from aot.databases.utils import session_scope
        from aot.config import AOT_DB_PATH
        from aot.databases.models.method import Method, MethodData
        import uuid as _uuid
    except ImportError as exc:
        logger.warning('method_preset_seeder: DB 임포트 실패 — %s', exc)
        return

    preset_dir = os.path.abspath(_PRESET_DIR)
    if not os.path.isdir(preset_dir):
        logger.warning('method_preset_seeder: 프리셋 디렉터리 없음 — %s', preset_dir)
        return

    seeded = 0
    skipped = 0

    with session_scope(AOT_DB_PATH) as sess:
        # 기존 시드 이름 목록 (prefix "SEED: " 으로 구분)
        existing_names = {
            row.name for row in
            sess.query(Method.name).filter(Method.name.like('SEED:%')).all()
        }

        for crop in _CROP_ORDER:
            path = os.path.join(preset_dir, f'{crop}_vpd.json')
            if not os.path.isfile(path):
                continue
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    preset = json.load(f)
            except Exception as exc:
                logger.error('method_preset_seeder: %s 읽기 실패 — %s', path, exc)
                continue

            crop_name_ko = preset['meta'].get('name_ko', crop)
            for stage_key, stage in preset.get('stages', {}).items():
                name = f"SEED:{crop}:{stage_key}"
                if name in existing_names:
                    skipped += 1
                    continue

                display_name = (f"[시드] {crop_name_ko} — "
                                f"{stage.get('name_ko', stage_key)}")
                method_id = str(_uuid.uuid4())

                m = Method()
                m.unique_id   = method_id
                m.name        = name
                m.method_type = 'DailyMultiPoint'
                m.method_order = ''
                sess.add(m)

                md = MethodData()
                md.unique_id   = str(_uuid.uuid4())
                md.method_id   = method_id
                md.points_json = json.dumps(
                    stage['points_json'], ensure_ascii=False)
                sess.add(md)

                seeded += 1

        sess.commit()

    logger.info(
        'method_preset_seeder: 완료 — seeded=%d skipped=%d', seeded, skipped)
    return seeded, skipped


def get_preset_guide(crop: str, stage: str) -> dict:
    """crop/stage 에 대한 guide_T/RH 범위 반환. 프리셋 없으면 빈 dict."""
    path = os.path.join(os.path.abspath(_PRESET_DIR), f'{crop}_vpd.json')
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            preset = json.load(f)
        stage_data = preset.get('stages', {}).get(stage, {})
        return {
            'guide_T_min': stage_data.get('guide_T_min', 5),
            'guide_T_max': stage_data.get('guide_T_max', 40),
            'guide_RH_min': stage_data.get('guide_RH_min', 20),
            'guide_RH_max': stage_data.get('guide_RH_max', 95),
        }
    except Exception:
        return {}
