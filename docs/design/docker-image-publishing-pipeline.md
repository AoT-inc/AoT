# 도커 이미지 발행 파이프라인 설계

작성 2026-07-20. 목적: 도커 배포를 **버전 태그가 붙은 사전빌드 이미지**로 전환해,
업그레이드를 `docker compose pull && docker compose up -d`로 수행 가능하게 한다.
(인앱 GitHub 업그레이드는 베어메탈 전용 — [docker-image 검토](../../.local/plans/version_tag_reconciliation.md) 및
`project_inapp_github_upgrade_bugs` 참조.)

---

## 1. 배경 / 현재 상태

- `docker/Dockerfile`: `python:3.11-slim` + `COPY . .` (코드 이미지에 구움) + `pip install requirements`.
  `.dockerignore`는 화이트리스트(aot/·alembic_db/·install/만) → 이미지 클린(.git/.local/node_modules 제외).
- `docker/docker-compose.yml`: `image: aot_ai` + `build:` + **`../:/app` 소스 bind-mount** → 실행 코드는
  호스트 체크아웃(이미지의 구운 코드를 덮어씀). 즉 지금은 "개발/셀프호스트" 구성.
- 마이그레이션: `aot/aot_flask/app.py:324-326`이 기동 시 `alembic_upgrade_db(app)` 자동 실행
  → **이미지가 새로 떠도 볼륨 DB를 자동 마이그레이션**(파이프라인의 핵심 관건이 이미 해결됨).
- 라이브 데이터: named volume `aot_data`(`/app/aot_local/databases`, AOT_LOCAL_DIR). 이미지 교체와 무관하게 보존.
- 버전 정본: `aot/config/__init__.py`의 `AOT_VERSION`(현재 26.07.3). `release_helper.py`가 범프.
- 대상 아키텍처: Debian x86(**amd64**), 라즈베리파이(**arm64**), macOS 도커(arm64/amd64).

## 2. 설계 결정

| 항목 | 결정 | 근거 |
|---|---|---|
| 레지스트리 | **GHCR** `ghcr.io/aot-inc/aot` | 공개 무료, `GITHUB_TOKEN`로 인증(별도 시크릿 불필요), 공개 레포와 동거 |
| 멀티아치 | **linux/amd64 + linux/arm64** | RPi(arm64)·Mac(arm64)·Debian(amd64) 모두 커버. buildx+QEMU |
| 버전 정본 | **config `AOT_VERSION`** (git 태그 `vX.Y.Z`와 동기, release_helper가 보장) | 26.07 처럼 **0-패딩** 유지 필요 → semver 파싱(07→7) 회피 위해 config에서 직접 추출 |
| 이미지 태그 | `X.Y.Z`(정확판), `X.Y`(마이너), `latest`, `sha-<short>` | 핀 고정·롤백·추적 |
| 발행 트리거 | git 태그 `v*.*.*` push + 수동(`workflow_dispatch`) | 릴리스와 결합, 필요시 수동 재빌드 |
| 마이그레이션 | 앱 기동 시 자동(app.py) — 별도 엔트리포인트 불필요 | 볼륨 DB 자동 upgrade, 호스트 런처 의존 제거 |
| 롤백 | 이전 태그로 `AOT_IMAGE_TAG` 핀 후 `up -d` | 데이터는 볼륨에 보존, 스키마는 하위호환 마이그레이션 전제 |

**Non-goal**: 기존 dev 구성(bind-mount) 폐지 아님 — dev(bind)와 prod(image) **두 compose 병존**.

## 3. CI 워크플로 (`.github/workflows/docker-publish.yml` — 드롭인 준비본)

```yaml
name: Publish Docker image

on:
  push:
    tags: ['v*.*.*']       # 릴리스 태그에 발행
  workflow_dispatch:        # 수동 재빌드

permissions:
  contents: read
  packages: write           # GHCR push

jobs:
  build-and-push:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      # 0-패딩 유지 위해 config에서 직접 버전 추출 (semver 정규화 회피)
      - name: Derive version
        id: ver
        run: |
          V=$(grep -m1 "AOT_VERSION = " aot/config/__init__.py | sed -E "s/.*'([0-9.]+)'.*/\1/")
          MM=$(echo "$V" | cut -d. -f1-2)
          echo "version=$V"     >> "$GITHUB_OUTPUT"
          echo "majorminor=$MM" >> "$GITHUB_OUTPUT"

      - uses: docker/setup-qemu-action@v3      # arm64 에뮬레이션
      - uses: docker/setup-buildx-action@v3

      - name: Log in to GHCR
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Metadata (labels)
        id: meta
        uses: docker/metadata-action@v5
        with:
          images: ghcr.io/${{ github.repository_owner }}/aot
          tags: |
            type=raw,value=${{ steps.ver.outputs.version }}
            type=raw,value=${{ steps.ver.outputs.majorminor }}
            type=raw,value=latest
            type=sha,format=short

      - name: Build & push (multi-arch)
        uses: docker/build-push-action@v6
        with:
          context: .
          file: docker/Dockerfile
          platforms: linux/amd64,linux/arm64
          push: true
          tags: ${{ steps.meta.outputs.tags }}
          labels: ${{ steps.meta.outputs.labels }}
          cache-from: type=gha
          cache-to: type=gha,mode=max
```

주의:
- GHCR 패키지는 최초 1회 **가시성(public) 설정** 필요(레포 → Packages → 공개 전환), 또는 org 정책.
- arm64는 QEMU 에뮬 빌드라 시간 김(수 분). 필요시 `runs-on` arm 러너로 분리 가능.
- `git 태그 vX.Y.Z`는 반드시 `release_helper.py`로 config를 먼저 26.07.3에 맞춘 뒤 생성(정본 일치).

## 4. 프로덕션 compose (`docker/docker-compose.prod.yml` — 드롭인 준비본)

dev compose와의 차이: `build:`/`../:/app` 소스 마운트 **제거**, `image:`를 GHCR로, 데이터는 named volume만.

```yaml
name: aot
services:
  aot-app:
    image: ghcr.io/aot-inc/aot:${AOT_IMAGE_TAG:-latest}
    command: gunicorn -c /app/install/gunicorn_conf.py --bind 0.0.0.0:80 aot.start_flask_ui:app
    ports:
      - "8084:80"
    volumes:
      - aot_data:/app/aot_local                 # 라이브 DB/secret/kma (보존)
      - flask_session:/app/aot/databases/flask_session
      - aot_logs:/var/log/aot
    environment:
      - PYTHONPATH=/app
      - DOCKER_CONTAINER=TRUE
      - AOT_LOCAL_DIR=/app/aot_local
    restart: unless-stopped
    depends_on: [influxdb]

  aot_daemon:
    image: ghcr.io/aot-inc/aot:${AOT_IMAGE_TAG:-latest}
    command: python aot/aot_daemon.py
    volumes:
      - aot_data:/app/aot_local
      - aot_logs:/var/log/aot
    environment:
      - PYTHONPATH=/app
      - DOCKER_CONTAINER=TRUE
      - AOT_LOCAL_DIR=/app/aot_local
    restart: unless-stopped
    depends_on: [influxdb]

  influxdb:
    image: influxdb:2.7
    volumes:
      - influxdb_data:/var/lib/influxdb2
    restart: unless-stopped

volumes:
  aot_data:
  flask_session:
  aot_logs:
  influxdb_data:
```

`.env` (사용자가 버전 핀):
```
AOT_IMAGE_TAG=26.07.3
```

업그레이드:
```bash
# .env 의 AOT_IMAGE_TAG 를 새 버전으로 올리거나 latest 유지
docker compose -f docker/docker-compose.prod.yml pull
docker compose -f docker/docker-compose.prod.yml up -d
# 앱 기동 시 alembic 자동 마이그레이션. 데이터는 볼륨에 보존.
```
롤백: `.env`의 태그를 이전 값으로 되돌리고 `pull && up -d`.

## 5. 인앱 안내 갱신 (후속)

`routes_admin.admin_upgrade`의 도커 안내는 현재 "git pull + up --build"만 안내.
이미지 발행 활성화 후, 두 배포형을 함께 안내하도록 문구 갱신:
- dev(bind-mount): 호스트 `git pull` + `docker compose up -d`
- prod(image): `docker compose -f ...prod.yml pull && up -d`
(현 dev/prod 판별은 env로 구분 어려움 → 두 방법 병기 권장. 새 msgid라 i18n 추출 필요.)

## 6. 데이터/마이그레이션 안전성

- 이미지 교체는 **코드만** 바꾸고, DB/secret/kma는 `aot_data` 볼륨에 남음 → 데이터 손실 없음.
- 앱 기동 시 `alembic_upgrade_db`가 볼륨 DB를 head로 올림. **하위호환 마이그레이션 전제**(롤백 시 새 스키마를 구 이미지가 읽어야 하므로, 파괴적 스키마 변경은 major 경계에서).
- influxdb 데이터는 `influxdb_data` 볼륨.

## 7. 롤아웃 단계

1. **선결**: GitHub 이전 + `v26.07.3` 태그 발행(현재 대기 중인 3단계). 워크플로는 GitHub에서만 동작.
2. `.github/workflows/docker-publish.yml` 추가 → 태그 push 시 GHCR에 26.07.3 멀티아치 이미지 발행.
3. GHCR 패키지 public 전환.
4. `docker/docker-compose.prod.yml` + `.env.example` 추가, 매뉴얼에 이미지 업그레이드 절차 문서화.
5. 자기 서버(로컬·koat)는 dev(bind) 유지 or prod 전환 선택. 공개 사용자는 prod 권장.
6. 인앱 도커 안내 문구 갱신(5절).

## 8. 미결 결정 사항

- [ ] 레지스트리: GHCR 확정? (대안 Docker Hub `aotinc/aot`)
- [ ] 아키텍처: amd64+arm64 확정? (armv7 32bit RPi도 필요하면 linux/arm/v7 추가 — 빌드시간·호환성 비용 큼)
- [ ] 자기 서버(koat 등)를 prod(image)로 전환할지, dev(bind) 유지할지
- [ ] `latest` 태그 운영 정책(항상 최신 vs 안정판만)
- [ ] influxdb/logs를 named volume로 통일할지(현 dev는 host bind)

## 9. 관련 문서
- 버전/태그 정합: `.local/plans/version_tag_reconciliation.md`
- 인앱 업그레이드 버그/게이팅: 커밋 cefe847, 4481e0c
