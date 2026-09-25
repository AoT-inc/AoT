경고(Alerts)는 시스템 상태를 사람에게 알려 주는 기능입니다. 예를 들어 센서 모니터링에서 측정값이 기준을 넘으면 사용자의 주의가 필요한 상황일 수 있습니다.

입력과 출력은 스스로 이메일을 보내지 **않습니다**. 입력이나 출력에는 이메일 옵션이 없습니다. 알림은 다음 경로 중 하나로 나갑니다.

- **조건부 기능의 이메일 보내기 액션.** 가장 일반적인 경로입니다. Conditional의 Python 코드가 조건(예: 측정값이 없거나 한계를 넘음)을 확인한 뒤 [이메일 보내기 액션](Actions.md)(또는 사진과 함께 이메일 보내기)을 호출합니다. [조건부 기능(Conditional)](Functions.md#conditional)를 참고하세요.
- **pH/EC 조절기 자체의 이메일 칸.** [pH/EC 조절 함수](Supported-Functions.md)는 pH가 위험 범위를 벗어나거나, EC가 너무 높거나, 최근 측정값을 찾지 못하면 자체 칸에 입력한 주소로 이메일을 보냅니다. 반복 방지 타이머도 자체적으로 갖고 있습니다.
- **AI 이상 징후 알림.** AI 자율 기능이 켜져 있으면 경고 수준 이상의 이상 징후를 관리자에게 이메일로 보냅니다.
- **사용자 정의 Python 코드.** 사용할 수 있는 위치에서는 원하는 다른 방식으로 알림을 보낼 수도 있습니다.

이 경로는 모두 [알림 설정](Configuration-Settings.md#alert-settings)에 입력한 SMTP 계정을 사용하므로, 먼저 그 화면에서 설정하고 테스트 이메일을 보내 확인하세요.

## 시간당 이메일 한도

이메일 보내기와 사진과 함께 이메일 보내기 액션은 알림 설정의 **시간당 최대 이메일 수**로 정한 한도를 함께 씁니다. 한도를 넘는 이메일은 대기열에 쌓이지 않고 버려지며, 한 시간이 지나도 나중에 보내지지 않습니다. 버려진 이메일마다 데몬 로그([로그 뷰](Log-Viewer.md))에 오류 줄이 남습니다. 한도에 걸려 메일이 오지 않으면 [진단 설정](Configuration-Settings.md#diagnostic-settings)의 **이메일 카운터 재설정**으로 카운터를 비우세요. SMTP 연결이나 로그인 실패도 로그 뷰의 **데몬** 소스에 기록됩니다.

## 조건이 풀릴 때까지 한 번만 보내기 { #send-once-latch }

Conditional은 확인할 때마다 실행되므로, 조건이 계속 참이면 확인할 때마다 이메일이 나가 시간당 한도를 금방 채웁니다. 기본 제공 옵션이 생기기 전까지는, 실행과 실행 사이에 유지되는 `self`에 표시(플래그)를 두어 이메일을 한 번만 보내고 조건이 끝난 뒤에야 표시를 지우세요.

```python
measurement = self.condition("asdf1234")

if not hasattr(self, "alert_sent"):  # 처음 실행할 때만
    self.alert_sent = False

if measurement is not None and measurement > 30:  # 알림 조건
    if not self.alert_sent:
        self.run_all_actions()  # 이메일을 한 번 보냄
        self.alert_sent = True
elif measurement is not None:  # 정상 범위로 돌아온 유효한 측정값
    self.alert_sent = False  # 다음 발생에 대비해 다시 무장
```

참고:

- 유효한 측정값이 들어왔을 때만 표시를 지웁니다. 입력이 값을 보고하지 않으면(`None`) 표시를 그대로 두므로, 센서가 잠깐 끊겨도 이메일이 다시 나가지 않습니다.
- 표시는 메모리에만 있습니다. 함수를 비활성화했다가 다시 켜거나 데몬을 재시작하면 지워지고, 다음 확인에서 조건이 참이면 이메일이 한 번 다시 나갑니다.
- 반대로 측정값이 없는 상황을 알리려면 조건을 `if measurement is None:`로 두고, 값이 돌아올 때 표시를 지웁니다.

이메일 설정에 대한 자세한 내용은 [알림 설정](Configuration-Settings.md#alert-settings)을 참고하세요.
