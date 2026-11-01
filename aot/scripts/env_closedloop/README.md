# 통합환경제어 폐루프 시뮬레이터 (Phase 0)

현장(김제 육묘장3·영양 육묘장)의 실내 센서는 다른 장치의 **거울**이라 제어 명령에 반응하지
않는다(개루프). 그래서 목표 추종·헌팅·안전 동작 같은 **닫힌 고리 품질**은 현장 기록으로
판단할 수 없다. 이 하네스는 진짜 `env_coordinator`(`CustomModule`)를 **명령에 반응하는 가짜
온실**에 물려 돌린다. 이후 단계(버그 수정, psychro 통합, 센서 상태 분류, 폭염 보호, 차광·팬·
분무·물 공급 개선)는 모두 여기서 코드 판 A/B 로 검증한다.

## 구성

| 파일 | 하는 일 |
|---|---|
| `aot/functions/utils/env_control/sim/plant.py` | 시설 참값 모델(열·수분·CO₂·열질량·젖음 수지 + 장치 물리). DB 시설 정의에서 치수·장치를 직접 읽는다(`facility_from_db`). |
| `aot/functions/utils/env_control/sim/scenarios.py` | 외기 시나리오(합성·김제 실측)와 고장 주입. 씨앗 고정 — 같은 이름이면 같은 값. |
| `aot/functions/utils/env_control/sim/storm.py` | 극한 기상 외기 생성기(키프레임 + 씨앗 고정 난류, 60 s 격자). `scenarios.STORM` 묶음이 쓴다. |
| `aot/functions/utils/env_control/sim/metrics.py` | 추적 → KPI. 온·습도는 **참값**(시설 상태)으로 잰다. 극한 기상 지표(`storm_kpis`)도 여기. |
| `closedloop.py` | 컨테이너 안에서 도는 하네스(측정 읽기·데몬 RPC·시계만 갈아끼운다). |
| `run.sh` | 시나리오 × DB 변형을 `aot_ai` 컨테이너로 병렬 실행하고 비교표를 찍는다. |
| `compare.py` | 결과 폴더 하나면 KPI 표, 둘이면 A→B 표. `--storm` 은 극한 기상 열. |
| `timeline.py` | trace 한 건(또는 두 코드 판 나란히)에서 극적인 순간(최대풍·호우·낙폭·두절 …)의 사이클 시간표를 뽑는다. |
| `make_gimje_fans_db.py` | 김제 스냅숏 사본에 가상 흡기·배기팬을 붙인다(실험용 DB 변형 `fans`). `--roles circulation_fan` 이면 가상 순환팬 1대만(변형 `circfan`, 밤 이슬 순환팬 시험). |
| `make_gimje_screens_db.py` | 김제 스냅숏(또는 팬 사본)에 가상 차광막·보온커튼(`actuator_paired`, 주행 240 s)을 붙인다(`screens`·`fans_screens`). `--binary` 면 주행 시간을 적지 않아 코디네이터가 0/100 으로만 쓴다(`screens_binary`). |

현장 데이터(DB 스냅숏·실측 외기)는 저장소 밖에 둔다. 기본 위치:
`/Users/gwansuk/Github/AoT_dev/env-replay/gimje/`
(`aot_local/databases/aot.db.snap`, `aot_local/databases/aot_fans.db.snap`, `timeseries.json`).

## 실행

```bash
cd aot/scripts/env_closedloop

# 0) 가상 팬 DB 변형 만들기(한 번)
G=/Users/gwansuk/Github/AoT_dev/env-replay/gimje/aot_local/databases
python3 make_gimje_fans_db.py --src $G/aot.db.snap --dst $G/aot_fans.db.snap

# 0'') 가상 순환팬 DB 변형(밤 이슬 순환팬, 근거 59) — 원본 사본에 순환팬 1대(10200 m³/h)
python3 make_gimje_fans_db.py --roles circulation_fan --src $G/aot.db.snap --dst $G/aot_circfan.db.snap

# 0') 가상 스크린 DB 변형(원본 스냅숏은 건드리지 않는다 — 사본만 만든다)
python3 make_gimje_screens_db.py --src $G/aot.db.snap --dst $G/aot_screens.db.snap
python3 make_gimje_screens_db.py --src $G/aot.db.snap --dst $G/aot_screens_binary.db.snap --binary
python3 make_gimje_screens_db.py --src $G/aot_fans.db.snap --dst $G/aot_fans_screens.db.snap

# 1) 코디네이터가 장치를 어떻게 적재하는지 확인(팬이 intake_fan/exhaust_fan 으로 잡히는가)
./run.sh -o /tmp/sim_verify -d fans --verify normal

# 2) 기본 묶음(BASELINE 20개 — 실내 두절 sensor_indoor_blind_day·_dusk 포함) × 두 DB 변형
./run.sh -o /tmp/sim_base -d both baseline

# 3) 다른 코드 판(워크트리)으로 같은 것을 돌리고 비교
./run.sh -o /tmp/sim_fix -c /path/to/other/worktree -d both baseline
python3 compare.py /tmp/sim_base /tmp/sim_fix            # 칸: 같으면 값, 다르면 A→B
python3 compare.py /tmp/sim_base /tmp/sim_fix --md --actuators
```

극한 기상 묶음(`storm`, 아래 '극한 기상 시나리오'):

```bash
./run.sh -o /tmp/sim_storm -d orig,fans,screens -j 1 storm             # 10개 × 변형 3개
./run.sh -o /tmp/sim_storm_fix -c /path/to/other/worktree -d orig,fans,screens -j 1 storm
python3 compare.py /tmp/sim_storm /tmp/sim_storm_fix --storm             # A→B, 극한 기상 열
python3 timeline.py /tmp/sim_storm/typhoon__orig.trace.json --events     # 극적인 순간의 시간표
python3 timeline.py /tmp/sim_storm/typhoon__orig.trace.json --b /tmp/sim_storm_fix/typhoon__orig.trace.json --events
```

묶음 이름(`baseline`·`storm`·`all`)은 시나리오 이름과 섞어 줄 수 있다(`run.sh … storm normal`).
`screens`·`fans_screens` 변형은 위 `make_gimje_screens_db.py` 로 만들어 현장 폴더(`-s`)에 둔다.

시나리오 이름: `python3 -c "import sys; sys.path.insert(0,'../../..'); from aot.functions.utils.env_control.sim import scenarios as S; print(S.names())"`
(`baseline` = `S.BASELINE`, `all` = 전부).

환경변수로 덮어쓰기: `SIM_HOURS`(길이), `SIM_PERIOD`(코디네이터 주기, 기본 DB 값 600 s),
`SIM_DT`(시설 적분 스텝, 기본 10 s), `SIM_WARMUP_H`(지표에서 뺄 앞부분, 기본 1 h),
`SIM_DLI_TARGET`(구획 DLI 목표 mol/m²/d — 김제 스냅숏엔 없어 차광 '빛 지킴' 을 시험할 때 준다),
`SIM_COORD`(코디네이터 id 앞부분, 기본 김제 `5a853a0c`), `SIM_KEEP_FOREIGN=1`(아래 참고).

`-d` 는 쉼표로 여럿을 준다(예: `-d orig,screens,screens_binary`).

잎 VPD(2026-10-09, `leaf_vpd`): `SIM_VPD_BASIS=air|leaf` 면 시설의 바닥·작물 열질량 온도 `Tm` 을
가상 엽온 센서로 코디네이터의 `leaf_temp_signal` 에 묶고 `vpd_target_basis` 를 그 값으로 둔다(비우면
묶지 않는다 — 옛 코드 판은 속성을 받아도 쓰지 않으므로 기준선이 된다). 지표 `leafVPD`(평균 잎 VPD) ·
`leaf±tol%`·`leaf±2tol%`(잎 VPD 가 **정한** 목표 ± 허용 오차 안에 있던 몫 — 잎 기준이면 옮기기 전 목표)
· `leaf_minus_air_C` · `vpd_basis_fallback_cycles`. Tm 은 덩어리 온도라 실제 잎보다 느리다 — A/B 차이를 볼 것.

스크린 지표(2026-10-09): `DLI_frac` — 날마다 작물이 받은 광 ÷ min(스크린을 다 걷었다면 받았을 광,
코디네이터의 DLI 목표), 가장 나쁜 날(목표를 모르면 걷었을 광이 기준). `shade mv/h`·`shade mv/d`(하루
최대 이동) · `curt rev/h` · `dawn drop`(일출 ±1 h 실내 최저가 일출 1 h 전보다 내려간 폭, 날 중 최대).
시나리오 `hot_dry_overcast`(운량 0.85 — 일사 맑은 날의 약 0.57) · `cold_humid_dawn`(−2~8 °C, 밤 RH 95 %,
맑은 일출).

## 극한 기상 시나리오 (`storm` 묶음)

한국·일본 기후의 급변 날씨 열 가지. 외기는 `sim/storm.py` 가 키프레임(평균 경로) + 씨앗 고정 난류로
만든다 — 같은 이름이면 언제나 같은 값. 격자는 60 s(스콜 앞머리의 20 분 15 K 하강을 담으려고).

| 이름 | 길이 | 내용 |
|---|---|---|
| `typhoon` | 48 h | 서해안 통과(위험반원): 기압 1004→958 hPa, 평균풍속 4→25 m/s(돌풍 ~35), 풍향 동→남동→남→남서→서→북서 시계 방향 회전, 호우 띠 10~50 mm/h, RH 95~99 %, 일사 3~10 %; 9/7 아침에 개어 덥고 습한 맑은 날(33 °C) |
| `squall_heat` | 34 h | 폭염 오후(34.8 °C) 16:10 열대류 스콜: 돌풍전선(풍속 1→16 m/s·풍향 SW→NNW), 20 분에 15 K 하강, 30 분 호우(~60 mm/h), 17:30 이후 다시 해; 이튿날 맑고 덥다 |
| `heatwave_tropical_night` | 72 h | 3 일 36→37.5→38 °C, 열대야(밤 최저 27.2~28.4 °C), 밤 RH 90 % 이상 |
| `foehn_dry_wind` | 36 h | 푄: 낮 30 °C·RH 15~20 %·풍속 ~10 m/s 정속(ENE)·강일사, 밤에도 24 °C·RH 20 %대 |
| `cold_snap_frost` | 36 h | 맑은 낮 18 °C → 바람 없는 맑은 밤 복사냉각 −4 °C(새벽) → 이튿날 아침 쾌청 |
| `fog_morning_overcast` | 30 h | 02시에 끼어 11시까지 RH 100 %·일사 10 %·시정 120 m, 11시에 갑자기 걷혀 강한 햇볕 |
| `rain_gauge_vs_forecast` | 30 h | 덥고 맑은 날. 실측 강우계 0, 예보 모델(Open-Meteo, **백업 순위**)이 낮 12~17시 0.5~1.8 mm/h |
| `rain_gauge_vs_forecast_primary` | 30 h | 같되 예보 모델 센서를 순위 표시 없이(= 메인) 묶음 — 예전에는 강우계 0 과 모델 값이 평균됐다(2026-10-10 부터 신선한 실측이 있으면 실측만) |
| `sensor_storm_outage` | 48 h | `typhoon` + 실외 관측소 두절 두 번(h 4~6: 첫 강우 띠 직전·창 열려 있음·직전 값 온화 / h 19~21: 최대풍 한복판), `outdoor_stale` |
| `sensor_outage_night` | 24 h | 흐리고 고요한 습한 가을 밤(김제 10/10 꼴): 닫힌 집 RH 90~95 % 로 습도 상한이 야간 파킹을 풀어 창이 열린 채 22:30~01:30 실외 관측소 두절(`outdoor_stale`), 00:00~03:30 이슬비 0.6~1.5 mm/h — 두절 제습 닫기(근거 58)가 23:00 이후 창을 단계로 닫는가 |

**제어기에 나가는 실외 측정은 측정기답게 가공한다**(시나리오 `params`; 기존 시나리오엔 없어 결과가 안 바뀐다):
`wind_avg_s`(풍속을 직전 N 초 평균으로 — AWS 10 분 평균), `rain_accum_s`(`강수15분` 을 직전 15 분 누적 mm
로 — 순간 강우율/4 가 아니다). 시설 물리는 순간 풍속·강우율·돌풍을 그대로 쓴다. 제어기는 돌풍·시정
채널이 없다(지표용).

**예보 모델 입력(출처 표식)**: 제어기의 실외 읽기(`read_outdoor_sensors`)는 드라이버의 `data_origin: 'model'`
로 출처를 가른다(2026-10-10 부터 같은 순위 안에서도 실측 먼저, 강우는 순위를 넘어 실측 먼저 — 강우 값은
mm/h 로 맞춘다: KMA `강수15분` ×4). 그래서 시나리오가 `extra_sensors` 로 Open-Meteo 형 입력
(`OPEN_METEO_FORECAST`, 채널 `rain`/mm)을 컨테이너 DB 사본에 **실외 센서 피팅**으로 붙이고(순위
`backup`|`primary`), 하네스가 그 채널에 시나리오의 `fc_rain` 을 낸다. 실측 강우계(KMA)는 따로 0 을 낸다.

**새 고장** `outdoor_stale`: 두절 직전 표본이 값도 시각도 굳는다. `max_age` 를 주고 읽는 경로는 값 없음으로
보고, 안 주는 경로는 낡은 값을 그대로 받는다(규칙 A 시험). `target` 은 쉼표로 쓴 채널 키(비우면 전부).

**극한 기상 지표**(`metrics.storm_kpis`, `compare.py --storm`; 외기 시계열이 있는 모든 추적에 붙는다):

| 키 | 뜻 |
|---|---|
| `max_wind_open` · `max_gust_open` | 환기창이 조금이라도(>0.5 %) 열려 있던 동안의 최대 10 분 평균 풍속 · 최대 돌풍 |
| `open_gust15_min` · `open_wind12_min` | 열려 있으면서 돌풍 > 15 m/s · 10 분 평균 ≥ 12 m/s(코디네이터 강풍 문턱)인 분 |
| `hazard_min` · `open_in_hazard_min` | 위험(10 분 평균 ≥ 12 m/s 또는 비 ≥ 2 mm/h = 15 분 0.5 mm)인 분 · 그때 열려 있던 분 |
| `rain_open_min` · `heavy_rain_open_min` · `rain_intrusion_mm` | 비 온 채 열린 분 · 호우(≥10 mm/h)에 열린 분 · 열린 면적비 가중 강우량 mm(들이침 지수) |
| `open_up_hazard_cnt` | 참값이 위험한 순간에 나간 "더 열기" 명령 수 |
| `outage_min` · `open_in_outage_hazard_min` · `open_up_in_outage_cnt` | 실외 두절 분 · 두절 중 위험한데 열려 있던 분 · 두절 중 더 열라는 명령 수(규칙 A 위반 후보) |
| `vent_rev_storm_max_per_h` · `vent_moves_storm` · `storm_hours` | 폭풍 구간(돌풍>15 또는 비≥10, 앞뒤 30 분)에서 환기창 명령 방향 반전의 최대 시간당 속도(1 h 슬라이딩) · 이동 수 · 구간 길이 |
| `T_drop_max_20min` · `T_drop_events` | 실내(참값) 20 분 최대 하강 K · 3 K 이상 사건 수 |
| `ext_T_drop_max_20min` · `ext_T_drop_events` | 같은 것을 실외(8 K/30 분 이상 사건) |
| `frost_min` · `frost_degmin` · `crop_frost_min` | 실내 기온 < 0 °C 분 · 도분 · 작물 열질량 < 0 °C 분 |
| `crop_wet_night_min` | 일사 0(밤)인 동안 잎·트레이가 젖어 있던 분(`leaf_wet` 문턱) |
| `T_night_mean` · `T_night_min` · `RH_night_mean` | 밤(일사 0) 실내 평균·최저 기온, 평균 RH |
| `VPD_max` · `vpd_gt2_min` · `RH_min` | 건조 지표 |
| `fog_in_ext_fog_min` | 분무가 돌던 분 중 외기 RH ≥ 98 %(안개)인 분 |

시설 물리 한계: 비가 창으로 들이치는 양·피복 젖음의 냉각·돌풍의 구조 하중은 없다. 들이침은 위
지수로, 풍압 위험은 `max_wind_open`/`open_gust15_min` 으로 간접 판정한다.

결과: `<결과폴더>/<시나리오>__<변형>.trace.json`(사이클·세밀 기록·dispatch 전부),
`.summary.json`(KPI), `.log`(컨테이너 출력). `<결과폴더>/.harness/` 에 그 실행에 쓴 시설
모델·시나리오·지표 사본이 남는다.

## 무엇을 갈아끼우는가

`env-replay/gimje/replay_gimje.py` 와 같은 원칙 — 제어 로직은 한 줄도 다시 쓰지 않는다.

- **측정 읽기**: `aot.utils.influx.get_last_measurement` 와 `facility_sensors` 의 같은 이름.
  실내/실외 구분은 시설 통합(`get_facility_integration`)의 `sensors_resolved`(실내)·
  `sensors_outdoor`(실외)에 걸린 장치의 **모든 채널**이다(DeviceMeasurements.measurement 로
  키를 정한다 — 온도·습도·VPD·이슬점·풍향·풍속·강수15분(mm)·강수 유무·기압·시정 …).
  실외 시각은 5 분 격자(KMA 주기), 실내는 사이클 시각 − 10 s. `max_age` 를 존중한다.
- **데몬 RPC**: `coord.control.output_on/off`. `_dispatch`(어댑터·모터 게이트·불감대)는 진짜다.
  value/pwm = 목표 개도, sec = 켬 시간, vol = mL. paired 장치의 `last_position_pct` 는 매
  사이클 **드라이버가 믿는 위치**로 DB 사본에 쓴다(고착 고장이면 실제와 갈린다).
- **시계**: `time.time/sleep`, `timekit.utc_now/now_utc`, 모듈 수준 `utc_now` 사본,
  `_helpers_mixin.datetime.now`, `aot.utils.method.datetime.now`(곡선 'method' 목표의 주차 —
  안 고정하면 VPD·온도 목표가 실행한 날의 실제 시각을 따라 흘러, 같은 코드를 이틀 간격으로
  돌려도 요약이 갈린다). 이 고정이 들어오기 전 결과 폴더와는 목표가 달라 직접 비교할 수 없다.
- influx 쓰기·`log_channels._safe_write` 는 막는다.
- **시설 밖 actuator_paired 출력 떼기**(기본): 예전 코디네이터의 자동 발견은 DB 전체에서 임자
  없는 paired 출력을 데려왔다(개발서버 스냅숏에는 `TEST 측창1~4` 등). 지금 코드는 시설 범위로
  거르므로(`_paired_outside_facility_scope`) 필요 없지만, 수정 전 코드 판과 A/B 를 맞추려고 기본은
  컨테이너 DB 사본에서 출력 형식을 바꿔 발견 대상에서 뺀다. `SIM_KEEP_FOREIGN=1` 이면 그대로 둔다
  (수정이 먹는지 볼 때).

## 시설 모델 요약

단일 구역, 상태 [공기 T, 습도비 w, CO₂, 바닥·작물 열질량 Tm, 잎·트레이 젖은 물].
환기 G = 누기 + 균형 팬 + √(자연환기² + 불균형 팬²). 자연환기 = 풍력(Cd·√Cw·u·A/2) +
굴뚝(Cd·A/3·√(g·H·ΔT/T)), 방충망 유효 0.7. 불균형 팬은 보충 개구가 좁으면 정압으로 풍량이
줄고(차단 정압 50 Pa), 창이 열린 만큼 일부가 단락된다(만개 시 40 %). 분무는
`psychro.evaporate`(η·분무량 vs 지나가는 공기의 포화 여유) — 못 날린 물은 작물 젖음으로
쌓였다가 젖은면 증발로 나간다. 증산 ∝ 흡수 일사 × f(VPD) + VPD 항(고VPD 기공 닫힘).
피복 결로는 피복 온도(실내·실외·하늘·일사 흡수의 가중) < 이슬점일 때.

DB 에서 읽는 것: 폭·길이·처마·용마루 → 바닥·체적·피복 면적, 피복 종류 → U·투과율, 측창
피팅 폭 × 감는 높이(envelope side_vent 단 높이) → 개구 면적, 모터 주행 시간, 분무 밸브가 물린
관수 레이어의 노즐 수·유량·방향(아래 향 = 습윤형 η 0.35), 팬 풍량(목록형 specs.airflow_cmh).
나머지는 `PlantParams` 기본값(근거는 필드 주석).

**제어기와 독립**: `effect_functions`·greybox 파라미터·`capacity_meta` 를 쓰지 않는다. 같은
가정을 공유하면 제어기의 착각이 시뮬레이터에서 "참" 이 된다.

## 한계

- 단일 구역(수평·수직 온도 분포 없음), 풍향 무관 환기(풍상·풍하 차등 없음).
- 터널팬의 길이 방향 기류는 단락 비율과 단면 풍속 기록으로만 근사한다.
- 작물 모델은 육묘 트레이 수준의 증산·광합성 근사다(생육·스트레스 누적 없음).
- 비가 창으로 들이치는 양은 세지 않는다(열린 채 비 온 시간만 센다).
- 일사는 맑은 하늘 × 운량. 김제 실측 시나리오는 일사 채널이 없어 습도·강수로 운량을 어림한다.
- 파라미터는 문헌값이다 — 현장 반응 데이터가 없어 보정하지 않았다(그래서 절댓값보다 **A/B
  차이**를 본다).
