# 센서 보정 매뉴얼

보정은 센서가 정확하고 신뢰할 수 있는 측정값을 제공하도록 보장합니다. 이 매뉴얼은 AoT 시스템에서 가장 널리 쓰이는 센서, 특히 Atlas Scientific EZO 회로의 보정 절차를 다룹니다.

## Atlas Scientific EZO Circuits (pH, EC, DO, ORP)

Atlas Scientific 센서는 구조화된 1점, 2점, 3점 보정 과정을 지원합니다.

> [!IMPORTANT]
> 보정 단계는 항상 올바른 순서로 수행하세요: **Mid** -> **Low** -> **High**.

### 보정 단계

1.  **Clear Calibration**: 시작하기 전에 **Clear Calibration** 버튼으로 기존 보정 데이터를 지우는 것을 권장합니다.
2.  **Temperature Compensation (선택)**: 별도의 온도 센서가 있다면 보정 중 온도 변화를 보정하는 데 사용할 수 있습니다. 이렇게 하면 가장 높은 정확도를 얻을 수 있습니다.
3.  **Mid-Point Calibration**: 프로브를 Mid 용액(예: pH 7.00)에 담급니다. 측정값이 안정될 때까지 기다린 후(1~2분) **Calibrate Mid**를 클릭합니다.
4.  **Low-Point Calibration**: 프로브를 헹군 뒤 Low 용액(예: pH 4.00)에 담급니다. 안정될 때까지 기다린 후 **Calibrate Low**를 클릭합니다.
5.  **High-Point Calibration**: 프로브를 헹군 뒤 High 용액(예: pH 10.00)에 담급니다. 안정될 때까지 기다린 후 **Calibrate High**를 클릭합니다.

### 검증

**Daemon Log**(`[Manage] -> AoT Logs -> Daemon Log`)에서 **Slope**와 **Calibrated?** 메시지를 확인하여 보정 상태를 검증할 수 있습니다.

- 기울기(slope)가 100%에 가까우면 프로브가 정상이며 보정이 성공했음을 나타냅니다.
- `Cal,?` 명령은 보정된 점의 개수를 반환합니다.

## 연동 펌프 보정 (Peristaltic Pump)

연동 펌프(정량 주입 펌프)는 초당 또는 회전당 이동하는 액체량을 결정하기 위해 보정이 필요합니다.

1.  일정 시간(예: 60초) 동안 펌핑된 액체량을 측정합니다.
2.  측정된 부피를 펌프 출력 설정의 **Calibration** 필드에 입력합니다.
3.  이렇게 하면 AoT가 부피 기준으로 정확하게 정량 주입할 수 있습니다(예: "Pump 10ml").

---

> [!NOTE]
> AI 에이전트를 위한 구조화된 보정 명령과 절차 세부사항은 `ai_docs/calibration.json`에서 확인할 수 있습니다.
