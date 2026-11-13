# 대시보드 리소스 측정 도구

서버(라즈베리 파이 / 일반 PC) × 클라이언트(저·고사양 폰·PC) × 회선(LAN·WiFi·LTE) 조건별로
대시보드가 쓰는 리소스를 재서, 어떤 위젯을 몇 명까지 어떤 회선에서 제공할지 정하는 근거를 만든다.
방법과 판단 기준의 근거는 제안서(`.local/reports/dashboard-resource-measurement-20261108.md`, 2·3·6·7절)다.

배포되는 앱 코드가 아니다 — 개발 도구다. 앱 이미지에는 `aot/tests/` 가 함께 실리지만 어떤 모듈도
앱이 import 하지 않는다. 브라우저(`playwright`)와 부하 재생(`locust`)은 쓰는 모듈 안에서만 늦게
import 한다. `locust` 는 저장소 의존성이 아니므로 **저장소 밖 가상환경**에 설치한다.

## 구성

| 파일 | 하는 일 |
|---|---|
| `profiles.py` | 프로필 대시보드 8개를 HTTP 로 만든다(멱등). 대상 서버 URL 을 인자로 받는다 |
| `runner.py` | 한 조건을 N 번 재서 중앙값·사분위 범위·HAR 를 남긴다. 다중 탭·가시성 검사 포함 |
| `matrix.py` | 조건 격자(프로필 × 회선 × 감속 × 캐시)를 차례로 돌린다. 끊겨도 이어 돈다 |
| `server_sampler.py` | 서버 표본 수집기 — 로컬 `docker stats`, 원격 `ssh` + `pidstat`/`iostat`/`vcgencmd` |
| `loadgen.py`, `locustfile.py` | HAR 에서 요청 패턴을 뽑아 locust 로 동시 사용자 N 명을 재생 |
| `aggregate.py` | 결과를 조건별 표(마크다운 + JSON)로 모으고 임계값과 비교해 통과/경고/불통을 매긴다 |
| `config/thresholds.json` | 판단 기준(제안서 6절). 숫자는 여기서만 고친다 |
| `config/conditions.json` | 회선(LAN·WiFi·LTE·저속 LTE)과 기기 화면 정의 |
| `test_*.py` | 순수 계산·파서 단위 시험(브라우저·서버 없이 돈다) |

결과는 전부 `.local/bench/` 아래에 쌓인다(git·docker 에서 무시되는 경로). **세션 쿠키·비밀번호는 디스크에
쓰지 않는다** — HAR 는 쓴 직후 쿠키·인증 머리글을 지운다.

## 준비

```bash
# 클라이언트 기기(측정 실행기를 돌리는 기기)에 한 번
pip install playwright && python3 -m playwright install chromium
# 부하 재생에만 필요 — 저장소 밖에
python3 -m venv ~/.venvs/aot-bench && ~/.venvs/aot-bench/bin/pip install locust
export AOT_BENCH_LOCUST=~/.venvs/aot-bench/bin/locust
```

계정은 `--user/--password` 또는 환경변수 `AOT_BENCH_USER`/`AOT_BENCH_PASSWORD` 로 준다.
주지 않으면 E2E 픽스처 계정(`aot/tests/e2e/fixtures.py`)을 쓴다 — **E2E 스택(8085)에만 있는 계정**이다.

## 1. 프로필 대시보드 만들기

```bash
python3 -m aot.tests.dashboard_bench.profiles --url http://127.0.0.1:8085          # E2E 스택
python3 -m aot.tests.dashboard_bench.profiles --url http://맥미니 --user ... --password ...
```

| 키 | 구성 | 의도 |
|---|---|---|
| `P0` | 위젯 0 | 공통 셸 비용 |
| `P1` | 측정값 6 + 지표 2 + 게이지 2 + 출력(PWM) 2 | 현장 폰 확인용 최소 구성 |
| `P2` | P1 + 차트 3 + 타이머 1 + 시퀀스 1 | 일반 운영 화면 |
| `P3` | P2 + 지도 1 + 시설 3D 1 + 카메라 1(1초 갱신) | 상한선 확인 |
| `I-chart` `I-map` `I-facility` `I-camera` | P0 + 그 위젯 한 종류 | 위젯별 증분 비용 |

- 이름은 `BENCH <키>`. 다시 실행하면 `BENCH ` 로 시작하는 대시보드를 지우고 새로 만든다. 다른 대시보드는 건드리지 않는다.
- **데이터가 실제로 들어오게** 한다. 벤치 전용 입력 둘(`BENCH CPU` = CPU 부하, `BENCH DISK` = 남은 디스크 —
  하드웨어도 추가 패키지도 필요 없는 드라이버)을 만들어 10초 주기로 활성화하고, 측정·지표·게이지·차트가 거기 묶인다.
  출력 위젯은 PWM 출력(파이썬 코드 PWM, 부족하면 만든다)에, 타이머는 온오프 출력에, 시퀀스는 시퀀스 함수에 묶는다.
  지도는 서버에 이미 있는 지도를 쓴다(없으면 건너뛰고 알린다). 시설 위젯은 시설이 없으면 그 지도 위에 작은 온실 하나를 만든다.
- **카메라**: 앱의 정적 이미지(`/static/img/aot-hero-dashboard-v2.jpg`, 약 527KB)를 URL 카메라로 찍어 둔다.
  모던 카메라 위젯(`AoT_camera`, 스냅숏 1초)을 먼저 시도하고, 서버가 의존성(`onvif-zeep`) 때문에 거부하면 옛 카메라
  위젯으로 바꾼다 — 옛 위젯은 URL 카메라로 사진을 못 얻어 이미지 전송량이 빠지므로 **결과표의 `I-camera` 숫자를 해석할 때 어느
  위젯이 쓰였는지 `profiles.json` 의 `widgets` 에서 확인**한다.
- 새 위젯 종류를 처음 쓰면 서버가 화면 새로고침(`/reload_flask`, 프런트엔드 재시작)을 요구한다. 스크립트가 요청하고 기다린다.
  재시작 정책이 없는 스택(E2E 8085)은 프런트엔드가 내려간 채 남을 수 있다 → `docker start aot-e2e-aot-app-1`. `--no-reload` 로 건너뛸 수 있다.
- 8084(개발 서버)는 거부한다. 쓰기 시험은 E2E 스택(8085)이나 측정 전용 서버에서만 한다.
- 만든 목록은 `.local/bench/profiles.json`. 측정 실행기가 프로필 키를 이 파일에서 경로로 바꾼다. 서버마다 따로 만들고 `--out` 으로 구분한다.

## 2. 측정 실행기

```bash
python3 -m aot.tests.dashboard_bench.runner --url http://서버 --profile P2 \
    --net lte --cpu 4 --cache cold --repeat 5 --dwell 300 --server-label pc
```

| 인자 | 뜻 |
|---|---|
| `--profile` | `P0…P3`, `I-*`, 또는 `/dashboard/<id>` |
| `--net` | `lan`(1ms/95M) `wifi`(10ms/50M) `lte`(70ms/12M) `lte_slow`(150ms/3M) `none` |
| `--cpu` | CDP CPU 감속 배율(1=없음). 실기기 대조로 보정한 값을 쓴다(S5) |
| `--cache` | `cold`(첫 방문) / `warm`(감속 없이 한 번 읽어 캐시를 채운 뒤 측정) |
| `--repeat` | 반복 횟수(기본 5) |
| `--dwell` | 첫 로드 뒤 켜 둔 시간(초) |
| `--tabs` | 동시 탭 수. 탭마다 독립된 컨텍스트(쿠키·캐시 따로) |
| `--device` | `desktop`(1440×900) / `phone`(390×844 모바일) |
| `--exposure` | `all`(기본): 화면 밖 위젯도 폴링하게 뷰포트를 문서 높이까지 늘림 = 상한. `fold`: 첫 화면만 = 실사용 |

**`--exposure` 를 반드시 알고 쓴다.** `aot-poll-visibility.js` 가 화면 밖 위젯의 인터벌을 멈춘다(IntersectionObserver,
위아래 300px 여유). 그래서 긴 대시보드를 폰에서 열면 첫 화면의 위젯만 폴링한다. 서버·회선의 상한을 재려면 `all`,
실제 사용자가 보는 값을 재려면 `fold` 로 두 번 잰다. 둘 다 결과 파일의 조건 이름에 들어간다.

지표(결과 `*.summary.json` 의 `stats`, 각 `median`/`q1`/`q3`/`iqr`):
`lcp_ms` `fcp_ms` `tbt_ms`(FCP~로드+여유 구간) `longtask_total_ms` `heap_end_mb` `heap_max_mb`
`main_cpu_avg_pct`(켜 둔 구간의 메인 스레드 사용률 — CPU 감속 상태 기준) `first_requests` `first_bytes`
`steady_requests` `poll_requests_per_min` `poll_mb_per_hour`(켜 둔 구간 전송량을 시간당으로 환산) `ratio_304`
`ttfb_p50_ms` `ttfb_p95_ms`(클라이언트에서 본 첫 바이트까지).
"첫 로드"는 `load` 이벤트 + `--settle`(5초)까지의 요청이고 그 뒤가 "켜 둔 구간"이다.

HAR 는 `.local/bench/results/<서버>/har/<조건>/runN_tabK.har`(본문 제외, 쿠키·인증 머리글 제거).
외부(CDN) 요청은 기본으로 막고 막은 호스트를 결과에 적는다(`--allow-external` 로 풀 수 있다).
인터넷이 안 되는 현장 LAN 에서 외부 자원이 어떻게 되는지는 이 차단 목록이 곧 단서다.

### 다중 탭과 가시성 검사

```bash
python3 -m aot.tests.dashboard_bench.runner --url http://서버 --profile P2 --tabs 5 --dwell 120 --repeat 3 --server-label pc
```

탭마다 `Emulation.setFocusEmulationEnabled` 로 초점·가시성을 고정한다(헤드풀 브라우저에서는 `--rotate-front` 를
더하면 탭을 돌려가며 `bring_to_front`). 실행이 끝나면 **탭마다** 검사한다: `visibilityState` 가 `visible` 인가,
켜 둔 구간에 폴링이 한 건이라도 잡혔는가. 하나라도 어긋나면 `visibility_ok=false` 이고 어느 탭인지(`hidden_tabs`,
`dead_tabs`) 결과에 남는다 — 그 실행의 폴링 수치는 숨은 탭이 멈춰 낮게 잡힌 것일 수 있으니 믿지 않는다.
시범 측정에서는 이 처리가 없어 5탭의 백그라운드 폴링이 잡히지 않았다.

### 조건 격자

```bash
python3 -m aot.tests.dashboard_bench.matrix --url http://서버 --server-label pc \
    --profiles P0,P1,P2,P3 --nets lan,lte --cpus 1,4 --repeat 5 --dwell 300 --dry-run   # 시간 추정만
```

`--dry-run` 을 빼면 돈다. 이미 결과가 있는 조건은 건너뛴다(`--force` 로 다시).

## 3. 서버 표본 수집기 — 서버와 클라이언트는 다른 기기에서

한 기기에서 서버와 브라우저를 같이 돌리면 부하가 섞인다. 서버 쪽 표본은 **서버 옆(또는 서버에 ssh 로 닿는 제3의 기기)** 에서
따로 돌리고, 측정 실행기와 같은 시간대에 걸리게 시작한다. 결과 파일 이름을 `<조건>.server.csv` 로 맞추면 집계기가 알아서 붙인다.

```bash
# PC(docker) — 서버 기기에서
python3 -m aot.tests.dashboard_bench.server_sampler docker \
    --containers aot-app,aot_daemon,influxdb --duration 400 --interval 2 \
    --out .local/bench/results/pc/P2__lte__cpu4__cold__tabs1__desktop__all.server.csv

# 파이(원격) — 읽기 전용 명령만 ssh 로 흘려 보낸다. 사용자 승인을 받은 뒤에만.
python3 -m aot.tests.dashboard_bench.server_sampler ssh --host aot@파이주소 --pattern gunicorn \
    --duration 400 --interval 5 --out .local/bench/results/pi/P2__lte__cpu4__cold__tabs1__desktop__all.server.csv
```

원격은 `pidstat -h -u -r -p <gunicorn PID>`(없으면 `ps`), `iostat -dx -y`(SD 카드), `vcgencmd measure_temp` /
`get_throttled`(파이), `/proc/stat`(시스템 전체 CPU)를 고르게 뽑는다. 원격에는 아무것도 설치·저장하지 않는다.
같은 기기 연기 측정에서는 측정 실행기가 `--sample-docker 컨테이너,…` 로 대신 뽑아 줄 수도 있다(서버·클라이언트가 섞이는 방식이라 연기용이다).

## 4. 동시 사용자 부하 재생(10·20명)

```bash
# 측정 실행기가 남긴 HAR 에서 패턴(첫 로드 + 폴링 주기)을 뽑는다
python3 -m aot.tests.dashboard_bench.loadgen extract \
    --har .local/bench/results/pc/har/<조건>/run1_tab0.har --out .local/bench/pattern_P2.json
# 10명으로 60초, 20명으로도
python3 -m aot.tests.dashboard_bench.loadgen run --url http://서버 --pattern .local/bench/pattern_P2.json \
    --users 10 --duration 60 --label pc_P2_u10 --out .local/bench/results/pc \
    --cookie-pool 10 --warmup 30      # 정상 부하: 로그인 N 번만, 30초 예열 뒤 측정
```

사용자 한 명 = 로그인 → 첫 로드 요청을 순서대로 → 폴링을 각자 주기로(시작 시점은 흩뜨림). 브라우저가 아니므로 클라이언트
렌더 비용은 없고 **서버 쪽 처리량·응답 시간**만 본다(6개 병렬 연결 같은 브라우저 동작도 흉내 내지 않는다 — 첫 로드는 순차).

**로그인 속도 제한이 부하 시험을 가로막는다.** 앱은 로그인 경로에 IP당 시간당 300요청(`limiter.limit("300/hour")`,
워커 메모리)을 건다. locust 사용자는 모두 한 IP 라서, 단계를 연달아 돌리거나 80명이 한꺼번에 접속하면 제한에 걸려
`TooManyRedirects`·401 로 대량 실패한다(서버 포화가 아니다). 그래서 시나리오를 둘로 나눈다.

| 시나리오 | 옵션 | 무엇을 재나 |
|---|---|---|
| 정상 부하 | `--cookie-pool N` | 미리 N 번만 로그인해 세션 쿠키를 만들고 사용자들이 나눠 쓴다. 대시보드 첫 로드와 폴링만 본다 |
| 접속 폭주 | (기본) | 사용자마다 로그인한다. 로그인 비용(비밀번호 해시)과 제한을 잰다. 단계 사이에 제한이 쌓이지 않게 앱을 재시작한다 |

`--warmup 30` 은 측정 전에 몇 명(최대 5)이 같은 패턴을 돌며 템플릿·캐시를 데운다. 예열 결과는 `<라벨>.warmup_*`
파일로 따로 남고 집계기는 `*.load.json` 만 읽으므로 집계에서 빠진다. 쿠키 풀은 환경변수로만 locust 에 넘기고 디스크에 쓰지 않는다.

## 5. 집계

```bash
python3 -m aot.tests.dashboard_bench.aggregate --results .local/bench/results/pc --cores 8 --out .local/bench/report-pc
```

`<조건>.summary.json` 마다 한 줄, `*.load.json` 마다 한 줄. 임계값(`config/thresholds.json`):

| 지표 | 통과 | 경고 | 그 밖 |
|---|---|---|---|
| LCP | ≤ 2.5초 | ≤ 4초 | 불통 |
| TBT | ≤ 200ms | ≤ 600ms | 불통 |
| 켜 둔 메인 스레드 | ≤ 5% | ≤ 15% | 불통 |
| 시간당 폴링(LTE·저속 LTE 에서만) | ≤ 10MB | ≤ 30MB | 불통 |
| 서버 CPU 평균 | ≤ 50% | ≤ 80% | 불통 |
| 응답 p95 | ≤ 500ms | ≤ 1500ms | 불통 |
| 파이 스로틀 비트 | 0 | – | 불통 |

경고 구간(`warn`)은 제안서에 숫자가 없어 임시로 둔 값이다 — 결정 사항이다. 값이 없으면 판정에서 뺀다(`-`).
서버 CPU 는 컨테이너 CPU(코어 1개 = 100%)의 시각별 합을 `--cores` 로 나눈 전체 대비 %이고, ssh 표본이 있으면 `/proc/stat`
기반 시스템 전체 CPU 평균을 쓴다. 응답 p95 는 부하 재생 결과가 있으면 그 값, 없으면 클라이언트가 본 TTFB p95 다.

## 한계와 주의

- **하나의 8085 스택을 여럿이 쓴다.** E2E 시드(`aot.tests.e2e.seed`)는 첫 대시보드를 뺀 대시보드를 모두 지운다 — 누가
  다시 시드하면 `BENCH` 대시보드도 사라진다. 측정 도중 시드·E2E 가 돌지 않게 한다.
- **같은 기기 연기 측정의 수치는 절대값이 아니다.** 서버(docker)와 브라우저가 한 맥북을 나눈다. 도구가 도는지와 조건 간
  상대 차이만 본다. S2 이후는 서버와 클라이언트를 다른 기기에 둔다.
- CPU 감속 배율(4배·6배)은 임시 값이다. 실기기 1회 측정과 LCP·TBT 가 맞도록 보정해서 정한다(S5).
- 메인 스레드 사용률은 CDP `TaskDuration` 기반이라 감속 상태의 값이다. 배터리는 재지 않는다(실기기 `dumpsys batterystats`).
- 부하 재생은 렌더를 하지 않는다. 지도·3D 의 서버 쪽 요청(타일·시설 데이터)은 HAR 에 있는 만큼만 재생된다.
- 카메라 위젯의 1초 갱신은 위젯 구현이 정한다 — 이미지가 크면 앞 요청이 끝나야 다음이 나가 실제 주기가 1초보다 길 수 있다.
  실제로 몇 초마다 몇 바이트가 나갔는지는 결과의 `poll_by_url` 에서 본다.
