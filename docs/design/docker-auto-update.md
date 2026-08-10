# Docker 배포판 업데이트

네이티브 설치는 `aot_wrapper`(setuid) → `upgrade_commands.sh` 로 디스크의 설치본을
갈아치운다. Docker 배포판에는 `/opt/AoT` 도 systemd 도 없어서 그 경로가 통째로
없었고, 업그레이드 페이지는 "호스트에서 알아서 하라"는 안내문 하나였다.

이 문서는 그 자리를 메우는 구조를 기록한다. 관련 파일:

| 역할 | 파일 |
|---|---|
| 가용 버전 판정 | `aot/utils/registry_release_info.py`, `aot/utils/update_availability.py` |
| 앱↔업데이터 프로토콜 | `aot/utils/docker_update.py` |
| 헬스 게이트 | `GET /health` (`aot/aot_flask/routes_general.py`) |
| 실행 | `docker/updater/aot_docker_update.sh` |
| 사이드카 | `docker/updater/Dockerfile`, `docker/docker-compose.updater.yml` |
| 호스트 대안 | `install/aot-docker-update.service` / `.timer` |
| 백업 진입점 | `aot/utils/docker_backup_cli.py` |

---

## 1. 왜 이런 모양인가

### 1-1. 앱은 자기 자신을 업데이트할 수 없다
`docker compose up -d` 는 그 명령을 실행한 컨테이너까지 교체한다. 앱이 직접
부르면 명령이 중간에 죽는다. 그래서 **교체 대상 밖의 행위자**가 필요하다.
업데이터는 `docker-compose.updater.yml` 이라는 별도 파일에 있고, 자신은
`docker-compose.prod.yml` 만으로 `up -d` 를 돌린다 — 자기 서비스가 그 파일에
없으므로 compose 가 건드리지 않고, 자기가 수행하는 교체에서 살아남는다.

> **업데이터를 기본 compose 로 옮기지 말 것.** 옮기는 순간 업데이트 도중
> 자기 자신을 재생성하고 업데이트가 반토막 난다.

### 1-2. git 태그는 이미지 존재를 보장하지 않는다
릴리스 태그를 밀면 GitHub 태그는 즉시 생기지만 멀티아치 이미지는 수 분 뒤에
발행된다. 그 구간에서 "업데이트 있음"을 띄우면 `docker pull` 이 404 다.
그래서 Docker 에서는 **GHCR 태그 목록이 정본**이다(`registry_release_info.py`).
움직이는 태그(`latest`, `YY.MM`, `sha-*`)는 릴리스로 세지 않는다 — 가리키는
대상이 조용히 바뀌는 값을 버전 비교에 넣을 수 없다.

### 1-3. 이미지만 되돌리는 롤백은 롤백이 아니다
새 컨테이너가 뜨는 순간 alembic 이 스키마를 올린다. downgrade 는 대체로
미구현이므로, 이미지만 이전 태그로 되돌리면 **미래 스키마 위에서 옛 코드가
돈다.** 롤백은 반드시 *이미지 태그 + DB 스냅샷* 쌍이다.

### 1-4. compose 의 상대 바인드 경로는 호스트 경로다
`docker-compose.prod.yml` 은 `../aot/inputs/custom_inputs` 같은 상대 바인드를
갖는다. compose 는 이를 **compose 파일이 있는 디렉터리 기준으로 해석해 호스트
데몬에 그대로 넘긴다.** 그래서 사이드카는 호스트의 프로젝트 디렉터리를
**동일한 절대 경로**로 마운트해야 한다(`AOT_PROJECT_DIR`). 다른 경로에 마운트하면
존재하지 않는 호스트 경로를, 운이 나쁘면 존재하는 엉뚱한 경로를 바인드한다.
같은 이유로 스크립트는 `--project-directory` 를 넘기지 않는다.

### 1-5. 농장 제어기다
데몬을 먼저 `stop` 해서 `stop_grace_period: 180s` 를 온전히 쓰게 한다. 그 시간은
출력에 Shutdown State 를 보내고 감사 로그를 flush 하는 데 쓰인다. 이걸 중간에
자르면 밸브가 열린 채 남는다.

---

## 2. 프로토콜

공유 볼륨(`aot_data`)의 한 디렉터리로만 통신한다. 앱은 `/app/aot_local/update/`,
업데이터는 `/state/update/` 로 같은 곳을 본다.

| 파일 | 방향 | 내용 |
|---|---|---|
| `request.json` | 앱 → 업데이터 | `{id, action, target, requested_by, requested_at}` |
| `status.json` | 업데이터 → 앱 | `{id, state, target, from_version, previous_tag, backup, message, updated_at}` |
| `heartbeat.json` | 업데이터 → 앱 | `{timestamp}` — 120초 넘으면 "없음"으로 본다 |
| `update.log` | 업데이터 → 앱 | 업그레이드 페이지가 tail 하는 로그 |
| `updater.lock` | 업데이터 | 디렉터리 잠금(중복 실행 방지) |

**요청은 명령이 아니라 데이터다.** 버전 번호 하나만 담고, 이미지·레지스트리·
셸 명령을 담을 수 없다. 업데이터는 레포지토리를 하드코딩하고 태그를
`^[0-9]{2}\.[0-9]{2}\.[0-9]+$` 로 재검증한다. 볼륨에 쓸 수 있는 누군가가
"아무 이미지나 이 호스트에서 실행"으로 승격하지 못하게 하려는 것이다.
검증은 앱(`docker_update.valid_target`)과 업데이터(`valid_target`) 양쪽에 있다.

상태 기계: `requested → backing_up → pulling → restarting → verifying →
done | failed | failed_rolled_back`.
`status.json` 의 `id` 가 처리 완료 표식이다 — `request.json` 의 `id` 와 같으면
이미 처리한 요청이므로 다시 돌지 않는다.

---

## 3. 실행 순서

1. **선행 점검** — Docker 접근, compose 파일 존재, `/health` 로 현재 버전·스키마
   리비전 확보. **여기서 버전을 못 읽으면 업데이트를 거부한다.** "전"을 모르면
   교체 성공과 무변화를 구분할 수 없고 롤백 검증도 불가능하다.
2. **백업** — `docker exec <app> python -m aot.utils.docker_backup_cli --create`.
   여유 공간(50MB 하한)을 먼저 본다. 백업 경로를 `status.json` 에 기록한다.
3. **pull** — `docker pull ghcr.io/aot-inc/aot:<target>`.
4. **목표 스키마 확인** — 새 이미지에 `ALEMBIC_VERSION` 을 물어본다
   (`docker run --rm --entrypoint python …`). 실패해도 업데이트를 막지는 않고
   버전만 검증한다.
5. **태그 교체** — `docker/.env` 에 `AOT_IMAGE_TAG` 를 쓰고
   `AOT_IMAGE_TAG_PREV` 를 남긴다. 되돌아갈 곳의 유일한 기록이라 프로세스가
   죽어도 살아남아야 한다.
6. **재생성** — 데몬 먼저 graceful stop → `up -d aot-app aot_daemon aot_mcp`.
7. **헬스 게이트** — `/health` 가 **목표 버전 + 목표 스키마 리비전**을 보고할
   때까지 최대 `AOT_HEALTH_TIMEOUT`(기본 300초). "200 응답"만으로는 안 된다 —
   롤백 중인 옛 컨테이너도, 마이그레이션이 실패한 새 컨테이너도 200 을 준다.
8. **실패 시 롤백** — 태그 되돌리기 → 재생성 → 옛 버전으로 헬스 확인.
   그래도 안 뜨면 **DB 스냅샷까지 복원**하고 다시 확인한다. 그것도 실패하면
   `failed` 로 남기고 백업 경로를 적어 사람에게 넘긴다.
9. **정리** — `AOT_UPDATE_PRUNE=1` 일 때만 지난 이미지를 지운다. **기본은 끔**:
   직전 이미지는 롤백이 쓰는 물건이다.

---

## 4. 헬스 엔드포인트

`GET /health` 는 공개다(로그인 화면 이전에도 답해야 한다). 익명 응답은
`{"status":"ok","docker":true}` 뿐이고, **버전과 스키마 리비전은 로그인 세션
또는 `AOT_HEALTH_KEY` 헤더**를 요구한다. 농장 제어기의 정확한 빌드 식별자는
익명에게 줄 물건이 아니다.

그래서 사이드카/타이머 양쪽 다 `AOT_HEALTH_KEY` 가 필요하다. 없으면 업데이터는
"버전을 못 읽었다"며 **업데이트를 거부한다** — 추측으로 진행하지 않는다.

`AOT_HEALTH_KEY` 는 `docker-compose.prod.yml`(기본 파일)에 선언돼 있다.
오버레이에만 두면 안 된다: 업데이터는 기본 파일만으로 `aot-app` 을 재생성하므로,
오버레이 전용 값은 **헬스 게이트가 필요한 바로 그 순간에 사라진다.**

---

## 5. 설치

### 5-1. 사이드카 (컨테이너가 컨테이너를 다룬다)

`docker/.env` 에 두 값을 넣는다:
```
AOT_PROJECT_DIR=/opt/AoT
AOT_HEALTH_KEY=<openssl rand -hex 24>
```
그리고:
```bash
docker compose -f docker/docker-compose.prod.yml \
               -f docker/docker-compose.updater.yml up -d
```

`/var/run/docker.sock` 은 호스트의 root 다. 사이드카는 의도적으로 작고
(`docker:28-cli` + curl + compose + 스크립트 하나) AoT 레포지토리만 pull 하지만,
소켓은 소켓이다. **이 거래를 받아들일 때만 켤 것.** GHCR 에 발행하지 않고
로컬 빌드로만 두는 것도 같은 이유다 — 남이 만든 특권 이미지를 돌리지 않게.

### 5-2. 호스트 systemd 타이머 (특권 컨테이너 없이)

같은 스크립트를 호스트에서 돌린다. 앱 쪽 동작은 완전히 동일하다.
```bash
cp install/aot-docker-update.{service,timer} /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now aot-docker-update.timer
```
`AOT_UPDATE_DIR` 을 볼륨 실제 경로로 맞춰야 한다:
```bash
docker volume inspect aot_aot_data --format '{{.Mountpoint}}'
```
타이머 주기는 **120초 미만**이어야 한다(`DOCKER_UPDATE_HEARTBEAT_MAX_AGE`).
넘기면 앱 입장에서 하트비트가 낡아 "업데이터 없음"과 구분되지 않고, 실행 사이에
원클릭 버튼이 사라진다.

### 5-3. 아무것도 안 켰을 때
업그레이드 페이지는 정확한 상태(현재/최신 버전, 이미지 발행 여부)를 보여주고
호스트에서 칠 명령을 안내한다. 버튼은 나오지 않는다 — 아무도 읽지 않는 요청
파일을 쓰는 버튼은 만들지 않는다.

---

## 6. 수동 조작

```bash
# 사이드카 안에서 상태만 보기
docker exec aot-aot_updater-1 aot_docker_update.sh --check

# 요청 파일 없이 특정 버전으로 즉시 업데이트(사이드카/호스트 공용)
docker/updater/aot_docker_update.sh --project-dir /opt/AoT --update 26.09.0
```

---

## 7. 자동 실행 (토글 + 시각)

`설정 > 업그레이드` 에서 **업데이트 자동 설치** 를 켜고 **업데이트 시각**을
지정하면, 매일 그 시각에 데몬이 확인해 발행된 새 버전이 있으면 설치를
요청한다. 설치 자체는 버튼을 눌렀을 때와 완전히 같은 경로다 — 백업, 교체,
검증, 실패 시 복구.

**판단은 데몬, 실행은 업데이터.** 데몬은 DB 를 보고 "지금 할 때인가, 할 것이
있는가"만 정하고 요청 파일을 쓴다. 특권을 가진 쪽은 계속 요청만 실행한다.

| 설정 | 컬럼 | 기본값 |
|---|---|---|
| 자동 설치 | `Misc.docker_auto_update` | 꺼짐 |
| 실행 시각 | `Misc.docker_auto_update_time` (`'HH:MM'`) | `03:00` |

마이그레이션은 `p6_30_docker_auto_update_20260810` 이다.

### 함정 세 가지 (전부 조용히 틀리는 종류)

- **시간대.** `time_utils.get_timezone_name()` 은 Flask 앱 컨텍스트가 없으면
  **조용히 UTC 로 폴백**하는데 데몬에는 컨텍스트가 없다. 그대로 두면 KST
  사용자가 03:00 이라고 입력하고 정오에 업데이트를 맞는다. 그래서 데몬은
  이미 손에 든 `Misc.timezone` 을 `next_scheduled_run(tz_name=...)` 로 넘기고,
  그 함수는 이름이 주어지면 pytz 로 직접 푼다.
- **경계.** 지금이 정확히 예약 시각이면 다음 실행은 **내일**이다. `<=` 가
  아니라 `<` 로 두면 방금 끝난 업데이트가 같은 분에 다시 자격을 얻는다.
- **재무장 시점.** 다음 실행 시각은 **무슨 일이 있어도 먼저** 전진시킨다.
  성공했을 때만 전진하면 실패한 날에는 데몬 루프가 도는 내내 재시도한다.

`aot/tests/test_docker_auto_update_schedule.py` 가 이 셋을 고정한다.

### 시각이 오면 하는 일

1. 이미 진행 중이면 건너뛴다.
2. **업데이터가 없으면 경고를 남기고 아무것도 하지 않는다** — 설치할 수단이
   없는데 요청 파일만 쌓는 것은 아무 의미가 없다.
3. 레지스트리를 확인한다. 최신이면 그렇다고 **INFO 로 남긴다** — 침묵은
   "확인했고 할 일이 없었다" 와 "일정이 아예 안 돈다" 를 구분해 주지 못한다.
4. 새 버전이 있으면 요청을 쓰고 감사로그(`system.upgrade_request`,
   `username='auto-update'`)를 남긴다.

설정을 저장하면 앱이 `refresh_daemon_misc_settings()` RPC 로 데몬에 알린다.
데몬은 일정을 메모리에 들고 있으므로, 이 통지가 없으면 변경이 다음 데몬
재시작까지 반영되지 않는다.

### 아직 없는 것

**작동 중이면 연기하지 않는다.** 지정한 시각이 되면 출력이 켜져 있든 시퀀스가
돌고 있든 컨테이너를 교체한다(데몬은 Shutdown State 를 보낼 시간을 갖지만,
그 시각에 진행 중이던 관수·보광은 중단된다). 그래서 **사람도 장비도 쉬는
시각을 고르는 것이 전제**다. 작동 중 연기, 채널 제한(patch 만), 메이저 버전
수동 승인은 아직 없다.
