# coding=utf-8
"""
seed_crop_presets.py — Photosynthesis model 5-crop preset을 FunctionCropPreset에 시드.

기존 레코드는 덮어쓰지 않음 (신규 추가만).
참조: aot/functions/utils/env_control/photosynthesis.py CROP_PRESETS
"""
import os
import sys
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
logger = logging.getLogger(__name__)

# ── Preset 데이터 (photosynthesis.CROP_PRESETS와 동기화) ───────────────────
_CROP_PRESETS = {
    'tomato': {
        'display_name': '토마토',
        'A_max':    25.0,
        'K_L':      120.0,
        'K_C':      700.0,
        'T_opt':    24.0,
        'T_sigma':   6.0,
        'VPD_half':  1.2,
        'T_base':   10.0,
        'dli_target': 22.0,
        'gdd_daily':  14.0,
        'vpd_target': 1.0,
        'co2_target': 900.0,
        'temp_min':   12.0,
        'temp_max':   32.0,
        'notes':    '방울·대과 공용. 야간 16°C 이상 유지 권장.',
    },
    'lettuce': {
        'display_name': '상추',
        'A_max':    18.0,
        'K_L':       80.0,
        'K_C':      500.0,
        'T_opt':    20.0,
        'T_sigma':   5.0,
        'VPD_half':  0.8,
        'T_base':    5.0,
        'dli_target': 14.0,
        'gdd_daily':  16.0,
        'vpd_target': 0.8,
        'co2_target': 800.0,
        'temp_min':   4.0,
        'temp_max':   27.0,
        'notes':    '엽채류 공용. 저광도·저온 적응성 높음.',
    },
    'cucumber': {
        'display_name': '오이',
        'A_max':    28.0,
        'K_L':      150.0,
        'K_C':      800.0,
        'T_opt':    26.0,
        'T_sigma':   5.0,
        'VPD_half':  1.4,
        'T_base':   12.0,
        'dli_target': 22.0,
        'gdd_daily':  14.0,
        'vpd_target': 0.9,
        'co2_target': 1000.0,
        'temp_min':   14.0,
        'temp_max':   34.0,
        'notes':    '고온·고습 적응. VPD 1.0~1.8 kPa 범위 유지.',
    },
    'strawberry': {
        'display_name': '딸기',
        'A_max':    20.0,
        'K_L':      100.0,
        'K_C':      600.0,
        'T_opt':    22.0,
        'T_sigma':   5.0,
        'VPD_half':  1.0,
        'T_base':    5.0,
        'dli_target': 17.0,
        'gdd_daily':  13.0,
        'vpd_target': 0.8,
        'co2_target': 800.0,
        'temp_min':   4.0,
        'temp_max':   28.0,
        'notes':    '촉성재배 기준. 개화기 야간 8°C 이상 필요.',
    },
    'pepper': {
        'display_name': '파프리카',
        'A_max':    22.0,
        'K_L':      130.0,
        'K_C':      750.0,
        'T_opt':    25.0,
        'T_sigma':   5.0,
        'VPD_half':  1.3,
        'T_base':   12.0,
        'dli_target': 22.0,
        'gdd_daily':  15.0,
        'vpd_target': 1.0,
        'co2_target': 900.0,
        'temp_min':   12.0,
        'temp_max':   32.0,
        'notes':    '착색기 온도 편차 최소화 권장.',
    },
}


def seed_crop_presets():
    try:
        from aot.databases.utils import session_scope
        from aot.config import AOT_DB_PATH
        from aot.databases.models.function_cumulative import FunctionCropPreset
    except ImportError as exc:
        logger.warning('seed_crop_presets: DB 임포트 실패 — %s', exc)
        print(f'[SKIP] seed_crop_presets import error: {exc}')
        return

    seeded = skipped = backfilled = 0

    with session_scope(AOT_DB_PATH) as sess:
        existing_keys = {
            row.crop_key
            for row in sess.query(FunctionCropPreset.crop_key).all()
        }

        for key, data in _CROP_PRESETS.items():
            if key in existing_keys:
                skipped += 1
                # 신규 필드(DLI/GDD) 백필 — 미설정(0/None)일 때만, 커스터마이즈 보존
                row = sess.query(FunctionCropPreset).filter_by(crop_key=key).first()
                if row is not None:
                    if not getattr(row, 'dli_target', 0):
                        row.dli_target = data.get('dli_target', 0.0)
                        backfilled += 1
                    if not getattr(row, 'gdd_daily', 0):
                        row.gdd_daily = data.get('gdd_daily', 0.0)
                    for _f in ('vpd_target', 'co2_target', 'temp_min', 'temp_max'):
                        if not getattr(row, _f, 0):
                            setattr(row, _f, data.get(_f, 0.0))
                continue

            row = FunctionCropPreset(
                crop_key=key,
                display_name=data['display_name'],
                A_max=data['A_max'],
                K_L=data['K_L'],
                K_C=data['K_C'],
                T_opt=data['T_opt'],
                T_sigma=data['T_sigma'],
                VPD_half=data['VPD_half'],
                T_base=data['T_base'],
                dli_target=data.get('dli_target', 0.0),
                gdd_daily=data.get('gdd_daily', 0.0),
                vpd_target=data.get('vpd_target', 0.0),
                co2_target=data.get('co2_target', 0.0),
                temp_min=data.get('temp_min', 0.0),
                temp_max=data.get('temp_max', 0.0),
                notes=data.get('notes', ''),
            )
            sess.add(row)
            seeded += 1

        sess.commit()

    print(f'[crop_presets] seeded={seeded}, skipped={skipped}, dli/gdd backfilled={backfilled}')
    logger.info('seed_crop_presets: seeded=%d, skipped=%d, backfilled=%d',
                seeded, skipped, backfilled)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    seed_crop_presets()
