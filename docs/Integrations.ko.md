# 외부 연동 (Integrations)

페이지: `설정 -> 외부 연동`

외부 연동 페이지는 AoT를 외부 서비스와 연결합니다. 현재는 [스케줄러(Scheduler)](ai/scheduler.md)와 개인 Google 캘린더 간의 양방향 동기화 하나가 있습니다. 사용자는 각자 자신의 Google 계정을 연결하며, 그 전에 관리자가 Google Cloud Console에 AoT를 OAuth 애플리케이션으로 등록하고 발급받은 클라이언트 자격 증명을 이 페이지에 입력해야 합니다.

---

## 관리자 설정: Google OAuth 클라이언트 { #google-oauth-setup }

누구든 계정을 연결하려면 먼저 관리자가 이 페이지의 **Google OAuth Configuration**(Admin) 영역에서 인스턴스 전역 Google OAuth 클라이언트를 설정해야 합니다. 이 설정이 끝나기 전에는 다른 사용자에게 "Google Calendar is not configured yet. Ask an administrator to configure it."(아직 설정되지 않았습니다. 관리자에게 문의하세요) 메시지만 표시됩니다.

1. [Google Cloud Console](https://console.cloud.google.com/)에서 프로젝트를 만들거나 선택하고 **Google Calendar API**를 활성화합니다.
2. 자격 증명 유형 **OAuth 2.0 클라이언트 ID**, 애플리케이션 유형 **웹 애플리케이션**으로 만듭니다.
3. 이 페이지에서 **Public Base URL**(예: `https://your-aot-domain`)을 먼저 입력합니다 — AoT가 이 값으로 고정된 콜백 주소를 계산해 필드 바로 아래 `<Public Base URL>/oauth/google/callback` 형태로 보여줍니다.
4. 이 주소를 그대로 Google Cloud Console의 OAuth 클라이언트 **승인된 리디렉션 URI**에 등록합니다.
5. Google Cloud Console에서 발급받은 **OAuth Client ID**와 **OAuth Client Secret**을 이 페이지의 해당 항목에 입력하고 **저장(Save)**합니다.

<table>
<thead>
<tr class="header">
<th>설정</th>
<th>설명</th>
</tr>
</thead>
<tbody>
<tr>
<td>Public Base URL</td>
<td>이 AoT 인스턴스의 외부 접속 기본 주소. OAuth 리디렉션 URI를 계산하는 데만 쓰이며, Google Cloud Console에 등록한 주소와 정확히 일치해야 합니다.</td>
</tr>
<tr>
<td>OAuth Client ID / OAuth Client Secret</td>
<td>위에서 만든 웹 애플리케이션 OAuth 클라이언트의 자격 증명 한 쌍.</td>
</tr>
<tr>
<td>Google Picker API Key</td>
<td>선택 항목. AI 라이브러리의 Google Drive 소스(파일 선택기)를 쓸 때만 필요한, 별도의 비-비밀(non-secret) Cloud Console API 키(Picker API 활성화)입니다. 위의 OAuth Client Secret과는 다른 값입니다.</td>
</tr>
</tbody>
</table>

이 세 값은 환경 변수(`GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`, `OAUTH_PUBLIC_BASE_URL`)로도 인스턴스 전역에 지정할 수 있으며, 이 경우 위 입력 필드보다 우선합니다 — 배포 설정을 통해 여러 서버가 같은 클라이언트를 공유할 때 유용합니다. 값이 환경 변수에서 온 경우 화면에 그렇게 표시됩니다.

계정을 연결하면 다음 권한(scope)을 요청합니다: 이벤트를 읽고 쓰기 위한 **캘린더(Calendar)** 전체 접근, 연결된 계정을 표시하기 위한 **이메일(email)**, **openid**, 그리고 사용자가 직접 선택한 파일에만 한정된 Drive 접근(`drive.file`, 캘린더 동기화가 아니라 AI 라이브러리의 Google Drive 소스에서만 사용).

---

## 계정 연결 { #connecting }

관리자가 위 설정을 마치면, 이 페이지의 **Google Calendar** 영역에서 **Connect Google Calendar**를 클릭합니다. Google 동의 화면으로 이동하며, 접근을 허용하면 이 페이지로 돌아와 **Connected(연결됨)** 상태와 연결된 계정의 이메일이 표시됩니다.

AoT가 사용자 개입 없이 계속 동기화하려면 Google이 refresh token을 내려줘야 합니다. 만약 내려주지 않는다면(과거에 접근을 허용했다가 완전히 해제하지 않은 계정에서 발생할 수 있음), AoT는 Google 계정의 타사 접근 권한에서 AoT를 제거한 뒤 다시 연결하라는 오류를 표시합니다.

---

## 무엇을, 어떻게 동기화하는가 { #sync-direction }

AoT는 [스케줄러(Scheduler)](ai/scheduler.md)의 작업 카테고리별로 사용자 계정에 Google 캘린더 3개를 각각 만들어, 개인 일정과 AoT 일정이 섞이지 않게 합니다.

<table>
<thead>
<tr class="header">
<th>Google 캘린더</th>
<th>AoT 카테고리</th>
<th>Google에서 만든 새 이벤트가 AoT 작업이 되는가?</th>
</tr>
</thead>
<tbody>
<tr>
<td>AoT · AI</td>
<td>AI가 작성한 작업</td>
<td>아니요 — AI가 자신의 작업을 직접 생성합니다. 수정·취소만 되돌아 동기화됩니다.</td>
</tr>
<tr>
<td>AoT · 사용자</td>
<td>사람이 하는 작업</td>
<td>예 — 일반 작업(Pending)으로 생성됩니다.</td>
</tr>
<tr>
<td>AoT · 장치</td>
<td>장치 제어 작업</td>
<td>예 — 초안(Draft) 상태의 장치 제어 작업으로 생성되며, 실행되려면 스케줄러의 통상적인 승인 절차를 거쳐야 합니다. Google 이벤트가 장치를 직접 작동시키는 일은 없습니다.</td>
</tr>
</tbody>
</table>

각 이벤트는 위치·장치·상태·메모 등 일정 내용을 사람이 읽고 고칠 수 있는 `항목: 값` 형태의 구조화된 텍스트로 이벤트 설명(description)에 담아 사용자의 화면 언어로 쓰고 읽습니다. Google에서 이 텍스트(또는 이벤트 시각)를 수정하고 동기화하면 해당 AoT 작업에 그대로 반영됩니다.

- **AoT → Google (push)**: 동기화 대상 상태(Pending, Running, Completed, Failed)인 모든 작업이 각자의 카테고리 캘린더에 생성·갱신됩니다.
- **Google → AoT (pull)**: 이미 동기화된 이벤트의 수정·시간 변경·취소는 해당 AoT 작업에 반영되며, 사용자/장치 캘린더의 새 이벤트는 위 표대로 새 작업을 만듭니다.
- **동기화 방향 표시**: **AoT → Google** / **Google → AoT**로 표시되며, 기본값은 둘 다 켜져 있는 완전한 양방향입니다.
- **충돌**: 같은 작업/이벤트가 양쪽에서 바뀌었다면 더 최근에 수정된 쪽이 반영됩니다.

동기화는 약 15분마다 백그라운드에서 자동으로 실행되며, **Sync Now**로 즉시 실행할 수도 있습니다. **Last Synced**는 가장 최근 실행 시각(UTC)을 보여주고, 실패했을 경우(예: Google 쪽에서 접근 권한을 해제한 경우) **Error** 표시가 함께 나타납니다.

---

## 연결 해제 { #disconnecting }

**Disconnect**를 누르면 백그라운드 동기화가 중지되고, Google 쪽 접근 권한을 최선을 다해 해제(revoke)한 뒤, AoT에 남아 있던 이 연결과 이벤트 매핑 기록을 삭제합니다. 이미 Google 캘린더에 만들어진 이벤트는 **삭제되지 않습니다** — 더 이상 필요 없다면 Google 캘린더에서 직접 지워야 합니다.

---

## 보안 { #security }

Google의 refresh token과 access token은 사용자별로 암호화되어 저장되며, 데이터베이스 어디에도 평문 자격 증명이 남지 않습니다. 관리자가 설정하는 OAuth 클라이언트 자격 증명은 인스턴스 전역 값으로 계정을 연결하는 모든 사용자가 함께 쓰지만, 각 사용자 자신의 연결과 토큰은 본인만 접근할 수 있습니다.

---

## 관련 페이지

- [스케줄러(Scheduler)](ai/scheduler.md) — 이 연동이 동기화하는 작업 원장입니다.
