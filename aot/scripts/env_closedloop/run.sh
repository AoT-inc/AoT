#!/bin/bash
# 통합환경제어 폐루프 시뮬레이션 — 시나리오 × DB 변형을 컨테이너(aot_ai)로 돌린다.
#
# 사용법:
#   run.sh -o <결과폴더> [-c <코드폴더>] [-d orig|fans|both] [-j 동시실행수]
#          [-s <현장폴더>] [--verify] <시나리오|묶음 ...>
#   묶음 이름: baseline(기본 20개) · storm(극한 기상 10개 — 태풍·스콜·폭염 열대야·푄·늦서리·안개·
#   예보 강수·관측소 두절·밤 두절) · all(전부). 묶음과 시나리오 이름을 섞어 줄 수 있다(예: storm normal).
#
#   -c  시험할 코드(저장소 루트). 기본: 이 스크립트가 든 저장소. 다른 워크트리를 주면 A/B.
#   -d  DB 변형. orig = 현장 스냅숏(aot.db.snap), fans = 가상 터널팬 사본(aot_fans.db.snap,
#       make_gimje_fans_db.py 로 만든다), screens = 가상 차광막·보온커튼(부분 개도, aot_screens.db.snap),
#       screens_binary = 같은 스크린을 0/100 으로만(aot_screens_binary.db.snap), fans_screens = 팬 +
#       스크린(aot_fans_screens.db.snap), screens_heated(_binary) = 스크린 + 가상 난방기
#       — 스크린 변형은 make_gimje_screens_db.py 로 만든다. circfan = 가상 순환팬 1대만(aot_circfan.db.snap,
#       make_gimje_fans_db.py --roles circulation_fan — 밤 이슬 순환팬 시험).
#       쉼표로 여럿(예: orig,screens), both = orig,fans. 기본 orig.
#   -s  현장 폴더(DB 스냅숏·실측 외기). 기본 /Users/gwansuk/Github/AoT_dev/env-replay/gimje
#   -j  동시 컨테이너 수(기본 3 — 컨테이너 하나가 앱 전체를 띄운다).
#   --verify  코디네이터가 적재한 프로필(종류·풍량·어댑터)만 찍고 끝낸다.
#
# 시설 모델·시나리오·지표는 **이 스크립트가 든 저장소의 판**을 쓴다(<결과폴더>/.harness 로
# 복사해 컨테이너에 넣는다). -c 로 준 코드가 바뀌어도 시설은 같다 — 그래야 A/B 가 성립한다.
# DB 는 매 실행 원본 스냅숏에서 컨테이너 /tmp 로 복사해 쓴다(현장 파일은 읽기 전용 마운트).
# 로그는 /tmp/aot_local/logs 로 보낸다 — 코드 폴더 루트에 logs/ 를 만들지 않게.
# 컨테이너 하나가 앱 전체(~300 MB)를 띄운다. Docker 메모리가 작으면 -j 를 줄일 것
# (실패한 조합은 같은 -o 로 그 시나리오만 다시 돌리면 된다).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../../.." && pwd)"
CODE="$REPO"
OUT=""
SITE="/Users/gwansuk/Github/AoT_dev/env-replay/gimje"
DBV="orig"
JOBS=3
VERIFY=0
SCEN=()
while [ $# -gt 0 ]; do
  case "$1" in
    -c) CODE="$(cd "$2" && pwd)"; shift 2;;
    -o) OUT="$2"; shift 2;;
    -s) SITE="$(cd "$2" && pwd)"; shift 2;;
    -d) DBV="$2"; shift 2;;
    -j) JOBS="$2"; shift 2;;
    --verify) VERIFY=1; shift;;
    -h|--help) sed -n '2,20p' "$0"; exit 0;;
    *) SCEN+=("$1"); shift;;
  esac
done
[ -n "$OUT" ] || { echo "-o <결과폴더> 가 필요합니다"; exit 2; }
mkdir -p "$OUT"
OUT="$(cd "$OUT" && pwd)"

# ── 하네스 판을 결과 폴더에 고정 ─────────────────────────────────────────────
STAGE="$OUT/.harness"
rm -rf "$STAGE"; mkdir -p "$STAGE/envsim"
cp "$REPO"/aot/functions/utils/env_control/sim/*.py "$STAGE/envsim/"
cp "$REPO"/aot/functions/utils/env_control/psychro.py "$STAGE/envsim/_psychro.py"
cp "$HERE/closedloop.py" "$STAGE/"
HARNESS_REV="$(git -C "$REPO" rev-parse --short HEAD 2>/dev/null || echo '?')"
echo "$HARNESS_REV" > "$STAGE/HARNESS_REV"

CODE_REV="$(git -C "$CODE" rev-parse --short HEAD 2>/dev/null || echo '?')"
if [ -n "$(git -C "$CODE" status --porcelain -- aot 2>/dev/null | head -1)" ]; then
  CODE_REV="${CODE_REV}+dirty"
fi

if [ ${#SCEN[@]} -eq 0 ]; then SCEN=(baseline); fi
# 묶음 이름(baseline|storm|all)은 시나리오 목록으로 펼친다 — 섞어 줘도 된다.
STORM_TABLE=0
for a in "${SCEN[@]}"; do [ "$a" = "storm" ] && STORM_TABLE=1; done
EXPANDED=()
while IFS= read -r line; do [ -n "$line" ] && EXPANDED+=("$line"); done < <(
  PYTHONPATH="$STAGE" python3 -c "
import sys
import envsim.scenarios as S
seen = []
for a in sys.argv[1:]:
    for n in (S.group(a) if a in S.GROUP_NAMES else [a]):
        if n not in seen:
            seen.append(n)
print('\n'.join(seen))" "${SCEN[@]}")
SCEN=("${EXPANDED[@]}")
case "$DBV" in
  both) VARIANTS=(orig fans);;
  *) IFS=',' read -r -a VARIANTS <<< "$DBV";;
esac

dbfile() {
  case "$1" in
    orig) echo "aot.db.snap";;
    fans|circfan|screens|screens_binary|fans_screens|screens_heated|screens_heated_binary) echo "aot_$1.db.snap";;
    *) echo "$1";;
  esac
}

run_one() {
  local sc="$1" v="$2" f
  f="$(dbfile "$v")"
  [ -f "$SITE/aot_local/databases/$f" ] || { echo "DB 없음: $SITE/aot_local/databases/$f"; return 1; }
  docker run --rm \
    -e TZ=Asia/Seoul -e PYTHONUNBUFFERED=1 -e PYTHONPATH=/app \
    -e AOT_LOCAL_DIR=/tmp/aot_local -e INSTALL_TARGET=docker -e DOCKER_CONTAINER=TRUE \
    -e HARDWARE_PROFILE=LOW -e INFLUXDB_HOST=127.0.0.1 -e INFLUXDB_PORT=1 \
    -e SIM_SCENARIO="$sc" -e SIM_VARIANT="$v" -e SIM_OUT_DIR=/out -e SIM_SITE=/site \
    -e SIM_COORD="${SIM_COORD:-5a853a0c}" -e SIM_HOURS="${SIM_HOURS:-}" \
    -e SIM_PERIOD="${SIM_PERIOD:-}" -e SIM_DT="${SIM_DT:-}" -e SIM_WARMUP_H="${SIM_WARMUP_H:-}" \
    -e SIM_VERIFY="$VERIFY" -e SIM_CODE_REV="$CODE_REV" -e SIM_KEEP_FOREIGN="${SIM_KEEP_FOREIGN:-}" \
    -e SIM_DLI_TARGET="${SIM_DLI_TARGET:-}" -e SIM_VPD_BASIS="${SIM_VPD_BASIS:-}" \
    -v "$CODE":/app -v "$SITE":/site:ro -v "$STAGE":/harness:ro -v "$OUT":/out \
    -w /app aot_ai sh -c "
      mkdir -p /tmp/aot_local/databases /tmp/aot_local/logs
      cp /site/aot_local/databases/$f /tmp/aot_local/databases/aot.db
      exec python3 /harness/closedloop.py" > "$OUT/${sc}__${v}.log" 2>&1
}

echo "코드 $CODE ($CODE_REV)  하네스 $HARNESS_REV  현장 $SITE  → $OUT"
pids=()
for sc in "${SCEN[@]}"; do
  for v in "${VARIANTS[@]}"; do
    while [ "$(jobs -rp | wc -l | tr -d ' ')" -ge "$JOBS" ]; do sleep 2; done
    ( if run_one "$sc" "$v"; then echo "  끝 $sc/$v"; else echo "  실패 $sc/$v (로그 $OUT/${sc}__${v}.log)"; fi ) &
  done
done
wait
if [ "$VERIFY" = "1" ]; then
  for sc in "${SCEN[@]}"; do for v in "${VARIANTS[@]}"; do
    echo "== $sc/$v"; grep -A30 '코디네이터 프로필' "$OUT/${sc}__${v}.log" | grep -v ' - ' || true
  done; done
else
  python3 "$HERE/compare.py" "$OUT"
  if [ "$STORM_TABLE" = "1" ]; then
    echo; echo "── 극한 기상 지표 ──"
    python3 "$HERE/compare.py" "$OUT" --storm
  fi
fi
