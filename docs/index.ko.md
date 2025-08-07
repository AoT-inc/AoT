description: AoT, 오픈 소스 환경 모니터링 및 제어 시스템에 대한 문서입니다.

## AoT 환경 모니터링 및 제어 시스템

AoT는 [라즈베리 파이](https://en.wikipedia.org/wiki/Raspberry_Pi) 및 기타 싱글 보드 컴퓨터(SBC)에서 실행되도록 설계된 오픈 소스 소프트웨어입니다. 환경을 감지하고 조작하기 위해 입력과 출력을 흥미로운 방식으로 결합합니다.

### 정보

AoT의 기능, 사용 중인 프로젝트, 스크린샷 및 기타 정보는 [README](https://github.com/aot-inc/AoT#uses)를 참조하세요.

### 사전 요구 사항

*   싱글 보드 컴퓨터 (권장: [라즈베리 파이](https://www.raspberrypi.org/), 모든 버전: Zero, 1, 2, 3, 또는 4)
*   Debian 기반 운영 체제
*   인터넷 연결

### 설치

부팅 후 로그인한 상태에서 다음 명령어를 실행하여 AoT 설치를 시작하세요:

```bash
curl -L https://aot-inc.github.io/AoT/install | bash
```

> ⚠️ 위 명령어는 AoT와 종속 항목을 자동으로 설치합니다.  
> 원격 스크립트를 실행하기 전에 출처를 신뢰할 수 있는지 확인하세요.

설치가 완료되면 SBC의 IP 주소를 웹 브라우저에 입력하여 설정을 완료하세요:

```
https://<your-device-ip>
```

예를 들어, SBC의 IP가 `192.168.0.101`이라면 다음과 같이 입력합니다:
```
https://192.168.0.101
```

### 지원

*   [GitHub의 AoT](https://github.com/aot-inc/AoT)
*   [AoT 위키](https://github.com/aot-inc/AoT/wiki)
*   [AoT API](https://aot-inc.github.io/AoT/aot-api.html)

### 기부

스폰서가 되세요: [github.com/sponsors/aot-inc](https://github.com/sponsors/aot-inc)

---

### 기반 프로젝트

AoT는 Kyle Gabriel이 개발한 오픈소스 프로젝트 [Mycodo](https://github.com/kizniche/Mycodo)를 기반으로 포크 및 수정되었습니다.  
본 프로젝트는 [MIT 라이선스](https://github.com/aot-inc/AoT/blob/main/LICENSE)에 따라 배포됩니다.
