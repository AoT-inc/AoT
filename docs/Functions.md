페이지: `설정 -> 기능`

지원되는 기능의 전체 목록은 [지원되는 기능](Supported-Functions.md)을 참조하세요.

기능 컨트롤러는 종종 입력 및 출력을 사용하는 작업을 수행합니다.

!!! 참고
    "마지막"은 기능이 데이터베이스에서 마지막(최신) 측정값만 가져온다는 것을 의미합니다. "과거"는 기능이 설정된 "최대 연령(초)"까지 현재부터 모든 측정값을 가져온다는 것을 의미합니다(예: 측정값이 10초마다 수집되고 최대 연령이 60초로 설정된 경우, 평균적으로 기능이 작동하는 데 6개의 측정값이 반환됩니다).

## 사용자 정의 기능

AoT에는 사용자 생성 기능을 AoT 시스템에서 사용할 수 있도록 하는 사용자 정의 기능 가져오기 시스템이 있습니다. 사용자 정의 기능은 `[톱니바퀴 아이콘] -> 구성 -> 사용자 정의 기능` 페이지에서 업로드할 수 있습니다. 가져온 후에는 `설정 -> 기능` 페이지에서 사용할 수 있습니다.

작동하는 기능 모듈을 개발한 경우, [새 GitHub 이슈 생성](https://github.com/aot-inc/AoT/issues/new?assignees=&labels=&template=feature-request.md&title=New%20Module) 또는 풀 리퀘스트를 고려해 보세요. 해당 모듈이 기본 제공 세트에 포함될 수 있습니다.

적절한 포맷팅 예제를 보려면 디렉토리 [AoT/aot/functions](https://github.com/aot-inc/AoT/tree/master/aot/functions/)에 있는 기본 제공 모듈을 열어보세요.

또한, 디렉토리 [AoT/aot/functions/examples](https://github.com/aot-inc/AoT/tree/master/aot/functions/examples)에는 사용자 정의 기능 예제가 포함되어 있습니다.

기본 제공 세트에 포함되지 않은 사용자 정의 모듈에 전념하는 또 다른 GitHub 저장소는 [aot-inc/AoT-custom](https://github.com/aot-inc/AoT-custom)에서 확인할 수 있습니다.

새로운 측정값/단위가 필요한 기능의 경우, `[톱니바퀴 아이콘] -> 구성 -> 측정값` 페이지에서 추가할 수 있습니다.

## PID 컨트롤러

[비례-적분-미분(PID) 컨트롤러](https://en.wikipedia.org/wiki/PID_controller)는 시스템 제어를 위해 산업 전반에서 사용되는 제어 루프 피드백 메커니즘입니다. 이는 온도와 같은 측정 가능한 조건을 효율적으로 원하는 상태로 가져가고, 오버슈트와 진동을 최소화하며 그 상태를 유지합니다. 잘 조정된 PID 컨트롤러는 설정값에 빠르게 도달하고, 오버슈트를 최소화하며, 설정값을 적은 진동으로 유지합니다.

PID 설정은 PID가 활성화된 동안 변경할 수 있으며, 새로운 설정은 즉시 적용됩니다. 컨트롤러가 일시 중지된 동안 설정이 변경되면, 컨트롤러가 작동을 재개할 때 변경된 값이 사용됩니다.

### PID 컨트롤러 옵션

<table>
<thead>
<tr class="header">
<th>설정</th>
<th>설명</th>
</tr>
</thead>
<tbody>
<tr>
<td>활성화/비활성화</td>
<td>특정 PID 컨트롤러를 켜거나 끕니다.</td>
</tr>
<tr>
<td>일시 중지</td>
<td>일시 중지 상태에서는 제어 변수가 업데이트되지 않으며 PID가 관련 출력을 켜지 않습니다. 현재 PID 출력 값을 잃지 않고 설정을 변경할 수 있습니다.</td>
</tr>
<tr>
<td>유지</td>
<td>유지 상태에서는 제어 변수가 업데이트되지 않지만 PID가 관련 출력을 켭니다. 현재 PID 출력 값을 잃지 않고 설정을 변경할 수 있습니다.</td>
</tr>
<tr>
<td>재개</td>
<td>유지 또는 일시 중지 상태에서 PID 컨트롤러를 재개합니다.</td>
</tr>
<tr>
<td>방향</td>
<td>조절하려는 방향입니다. 예를 들어 온도를 올리기만 하면 된다면 "상승"으로 설정하고, 상승 및 하강 모두 필요하다면 "양방향"으로 설정합니다.</td>
</tr>
<tr>
<td>주기</td>
<td>PID가 측정을 수행하고 업데이트되며 출력을 조정하는 간격입니다.</td>
</tr>
<tr>
<td>시작 오프셋 (초)</td>
<td>첫 계산/측정을 시도하기 전에 대기할 시간입니다.</td>
</tr>
<tr>
<td>최대 연령</td>
<td>센서 측정값의 최대 허용 연령(초)입니다. 측정값이 이 연령보다 오래되었으면 측정값이 무시되고 PID는 출력을 작동시키지 않습니다. 이는 PID가 최신 측정값만 사용하도록 보장하는 안전 장치입니다.</td>
</tr>
<tr>
<td>설정값</td>
<td>환경을 조절하려는 특정 값입니다. 예를 들어 습도를 60%로 조절하려면 60을 입력합니다.</td>
</tr>
<tr>
<td>밴드 (+/- 설정값)</td>
<td>히스테리시스 옵션입니다. 0이 아닌 값으로 설정하면 설정값이 밴드로 변환됩니다. 밴드의 최대값은 설정값+밴드, 최소값은 설정값-밴드입니다. 상승 시 밴드 최대값을 초과하면 PID는 대기하고, 조건이 밴드 최소값 아래로 떨어지면 조절을 재개합니다. 하강 시 밴드 최소값 아래로 떨어지면 PID는 대기하고, 조건이 밴드 최대값 위로 올라가면 조절을 재개합니다. 양방향으로 설정하면 밴드의 외부 최소 및 최대값에서만 조절이 이루어지며 밴드 내에서는 중지됩니다. 히스테리시스를 비활성화하려면 0으로 설정합니다.</td>
</tr>
<tr>
<td>하강을 음수로 저장</td>
<td>체크하면 모든 출력 변수(PID 및 출력 지속 시간/듀티 사이클)가 측정값 데이터베이스에 음수 값으로 저장됩니다. 이는 PID가 현재 상승 중인지 하강 중인지 그래프에 표시하는 데 유용합니다. 모든 값을 양수로 저장하려면 비활성화합니다.</td>
</tr>
<tr>
<td>K<sub>P</sub> 게인</td>
<td>비례 계수(0 이상). 오류의 현재 값을 고려합니다. 예를 들어 오류가 크고 양수일 경우 제어 출력도 크고 양수가 됩니다.</td>
</tr>
<tr>
<td>K<sub>I</sub> 게인</td>
<td>적분 계수(0 이상). 오류의 과거 값을 고려합니다. 예를 들어 현재 출력이 충분히 강하지 않으면 오류의 적분이 시간이 지남에 따라 누적되고 컨트롤러는 더 강한 동작을 적용합니다.</td>
</tr>
<tr>
<td>K<sub>D</sub> 게인</td>
<td>미분 계수(0 이상). 현재 변화율을 기반으로 오류의 예측된 미래 값을 고려합니다.</td>
</tr>
<tr>
<td>적분기 최소값</td>
<td>Ki_total을 계산할 때 허용되는 적분기의 최소값입니다. (Ki_total = Ki * 적분기; PID 출력 = Kp_total + Ki_total + Kd_total)</td>
</tr>
<tr>
<td>적분기 최대값</td>
<td>Ki_total을 계산할 때 허용되는 적분기의 최대값입니다. (Ki_total = Ki * 적분기; PID 출력 = Kp_total + Ki_total + Kd_total)</td>
</tr>
<tr>
<td>출력 (상승/하강)</td>
<td>특정 환경 조건을 상승 또는 하강시키는 출력입니다. 예를 들어 온도를 상승시키는 경우 히팅 패드나 코일일 수 있습니다.</td>
</tr>
<tr>
<td>최소 켜짐 지속 시간, 듀티 사이클 또는 양 (상승/하강)</td>
<td>PID 출력이 Output (하강)을 켜기 전에 도달해야 하는 최소값입니다. PID 출력이 이 값보다 작으면 지속 시간 출력은 켜지지 않으며 PWM 출력은 Always Min이 활성화되지 않는 한 꺼집니다.</td>
</tr>
<tr>
<td>최대 켜짐 지속 시간, 듀티 사이클 또는 양 (상승/하강)</td>
<td>Output (상승)에 설정할 수 있는 최대 지속 시간, 볼륨 또는 듀티 사이클입니다. PID 출력이 이 값을 초과하면 여기 설정된 최대값이 사용됩니다.</td>
</tr>
<tr>
<td>최소 꺼짐 지속 시간 (상승/하강)</td>
<td>켜짐/꺼짐(지속 시간) 출력의 경우, 출력이 다시 켜지기 전에 꺼져 있어야 하는 최소 시간입니다. 이는 빠른 전원 사이클링으로 인해 손상될 수 있는 장치(예: 냉장고)에 유용합니다.</td>
</tr>
<tr>
<td>항상 최소 (상승/하강)</td>
<td>PWM 출력 전용. 활성화하면 듀티 사이클이 최소값 아래로 설정되지 않습니다.</td>
</tr>
<tr>
<td>설정값 추적 방법</td>
<td>시간에 따라 설정값을 변경하는 방법을 설정합니다.</td>
</tr>
</tbody>
</table>
</tbody>
</table>

### PID 출력 계산

PID 컨트롤러는 지속 시간, 볼륨 또는 PWM 듀티 사이클과 같은 다양한 출력 유형을 제어할 수 있습니다. 대부분의 출력 유형에서는 PID 출력(제어 변수)이 비례적으로 작동합니다(예: ``출력 지속 시간 = PID 제어 변수``). 그러나 듀티 사이클을 출력할 때는 ``듀티 사이클 = (제어 변수 / 주기) * 100``으로 계산됩니다.

!!! 참고
    제어 변수 = P 출력 + I 출력 + D 출력. 듀티 사이클은 0 - 100 % 범위와 설정된 최소 듀티 사이클 및 최대 듀티 사이클 내에서 제한됩니다. 출력 지속 시간은 설정된 최소 켜짐 지속 시간 및 최대 켜짐 지속 시간에 의해 제한되며, 출력 볼륨도 유사하게 제한됩니다.

### PID 튜닝

PID 튜닝은 사용되는 출력 장치와 제어 대상 환경 또는 시스템에 따라 복잡한 과정이 될 수 있습니다. 큰 변동이 있는 시스템은 안정적인 시스템보다 제어하기 더 어렵습니다. 마찬가지로 적합하지 않은 출력 장치는 PID 튜닝을 어렵게 하거나 불가능하게 만들 수 있습니다. PID 컨트롤러의 작동 방식과 튜닝 이론을 배우면 PID 컨트롤러를 더 잘 운영할 수 있을 뿐만 아니라 시스템 개발, 출력 장치 선택 및 구현에도 도움이 됩니다.

#### PID 튜닝 리소스

- [수비드 PID 튜닝과 예상치 못한 전기 화재](https://hackaday.io/project/11997-aot-environmental-regulation-system/log/45733-sous-vide-pid-tuning-and-the-unexpected-electrical-fire)

#### PID 제어 이론

PID 컨트롤러는 단순한 제어부터 복잡한 제어까지 처리할 수 있는 능력으로 인해 산업 환경에서 가장 일반적으로 사용되는 규제 컨트롤러입니다. PID 컨트롤러는 비례, 적분, 미분의 세 가지 경로를 가집니다.

**P**(비례)는 오차를 K<sub>P</sub> 상수로 곱하여 출력 값을 생성합니다. 오차가 클수록 비례 출력도 커집니다.

**I**(적분)는 오차를 K<sub>I</sub>로 곱한 후 이를 적분합니다(K<sub>I</sub> · 1/s). 시간이 지남에 따라 오차가 변화하면 적분은 이를 지속적으로 합산하고 K<sub>I</sub> 상수로 곱합니다. 적분은 제어 시스템에서 지속적인 오차를 제거하는 데 사용됩니다. K<sub>P</sub>만 사용하여 출력이 지속적인 오차를 생성하는 경우(즉, 센서 측정값이 설정값에 도달하지 못하는 경우), 적분은 출력 값을 증가시켜 오차를 줄이고 설정값에 도달하도록 합니다.

**D**(미분)는 오차를 K<sub>D</sub>로 곱한 후 이를 미분합니다(K<sub>D</sub> · s). 시간이 지남에 따라 오차 변화율이 달라지면 출력 신호도 변화합니다. 오차 변화가 빠를수록 미분 경로가 커지며 출력 변화율을 감소시킵니다. 이는 설정값의 오버슈트와 언더슈트(진동)를 줄이는 효과를 가집니다.

![PID 애니메이션](images/PID-Animation.gif)

K<sub>P</sub>, K<sub>I</sub>, K<sub>D</sub> 게인은 P, I, D 변수가 최종 PID 출력 값에 얼마나 영향을 미치는지를 결정합니다. 예를 들어, 게인 값이 클수록 해당 변수가 출력에 미치는 영향이 커집니다.

![PID 방정식](images/PID-Equation.jpg)

PID 컨트롤러의 출력은 여러 방식으로 사용할 수 있습니다. 간단한 사용 사례는 이 값을 주기적 간격(Period) 동안 출력이 켜지는 시간(초)으로 사용하는 것입니다. 예를 들어, 주기가 30초로 설정된 경우 PID 방정식은 원하는 측정값과 실제 측정값을 사용하여 매 30초마다 PID 출력을 계산합니다. 이 주기 동안 출력이 켜지는 시간이 길수록 시스템에 더 큰 영향을 미칩니다. 예를 들어, 출력이 매 30초마다 15초 동안 켜져 있으면 50 % 듀티 사이클이며, 출력이 매 30초마다 30초 동안 켜져 있으면 100 % 듀티 사이클로 시스템에 두 배의 영향을 미칩니다. PID 컨트롤러는 실제 측정값이 원하는 측정값과 얼마나 차이가 나는지(오차)를 기반으로 출력을 계산합니다. 오차가 증가하거나 지속되면 출력이 증가하여 주기 내에서 출력이 더 오래 켜지게 되고, 이는 일반적으로 측정 조건을 변경하여 오차를 줄이는 결과를 가져옵니다. 오차가 줄어들면 제어 변수가 감소하여 출력이 더 짧은 시간 동안 켜지게 됩니다. 잘 조정된 PID 컨트롤러의 궁극적인 목표는 실제 측정값을 설정값으로 빠르게 가져가고, 오버슈트를 최소화하며, 설정값을 최소한의 진동으로 유지하는 것입니다.

온도를 예로 들면, 프로세스 변수(PV)는 측정된 온도, 설정값(SP)은 원하는 온도, 그리고 오차(e)는 측정된 온도와 원하는 온도 간의 차이를 나타냅니다(즉, 실제 온도가 너무 높거나 낮은 정도를 나타냄). 이 오차는 PID의 세 가지 구성 요소 각각에 의해 조작되어 조작 변수(MV) 또는 제어 변수(CV)라고 불리는 출력을 생성합니다. 각 경로가 출력 값에 기여하는 정도를 제어하기 위해 각 경로는 게인(K<sub>P</sub>, K<sub>I</sub>, K<sub>D</sub>)으로 곱해집니다. 게인을 조정하면 시스템이 각 경로에 얼마나 민감하게 반응하는지가 영향을 받습니다. 세 경로를 모두 합산하면 PID 출력이 생성됩니다. 게인을 0으로 설정하면 해당 경로는 출력에 기여하지 않으며 사실상 꺼진 상태가 됩니다.

출력은 여러 방식으로 사용될 수 있지만, 이 컨트롤러는 출력을 사용하여 측정된 값(PV)에 영향을 미치도록 설계되었습니다. 이 피드백 루프는 *적절히 튜닝된* PID 컨트롤러를 통해 짧은 시간 안에 설정값에 도달하고, 진동을 최소화하며, 방해 요소에 빠르게 반응할 수 있습니다.

따라서 온도를 조절하려는 경우, 센서는 온도 센서가 되고 피드백 장치는 가열 및 냉각이 가능한 장치가 됩니다. 온도가 설정값보다 낮으면 출력 값이 양수가 되어 히터가 작동합니다. 온도는 원하는 온도를 향해 상승하며, 이로 인해 오차가 감소하고 더 낮은 출력이 생성됩니다. 이 피드백 루프는 오차가 0에 도달할 때까지 계속됩니다(이 시점에서 출력은 0이 됩니다). 온도가 설정값을 초과하여 계속 상승하는 경우(허용 가능한 범위 내일 수 있음), PID는 음수 출력을 생성하여 냉각 장치가 온도를 다시 낮추고 오차를 줄이도록 할 수 있습니다. 온도가 냉각 장치의 도움 없이도 자연적으로 낮아질 수 있다면, 냉각 장치를 생략하고 시스템을 단순화할 수 있습니다.

K<sub>P</sub>, K<sub>I</sub>, K<sub>D</sub>를 효과적으로 활용하는 컨트롤러를 구현하는 것은 어려울 수 있으며, 종종 불필요하기도 합니다. 예를 들어, K<sub>I</sub>와 K<sub>D</sub>를 0으로 설정하면 해당 경로가 꺼지고 매우 간단한 P 컨트롤러가 생성됩니다. 또한 PI 컨트롤러도 인기가 많습니다. K<sub>P</sub>만 활성화된 상태로 시작한 후 K<sub>P</sub>와 K<sub>I</sub>를 실험적으로 조합해 보고, 마지막으로 세 가지를 모두 사용하는 것을 권장합니다. 시스템은 공기 공간의 부피, 단열 정도, 연결된 장치의 영향 정도 등 다양한 요인에 따라 달라지므로, 각 경로는 실험을 통해 효과적인 출력을 생성하도록 조정해야 합니다.

#### 빠른 설정 예제

이 예제 설정은 특정 방향으로의 조절을 구성하는 방법을 보여주기 위한 것이며, K<sub>P</sub>, K<sub>I</sub>, K<sub>D</sub> 게인을 구성하기 위한 이상적인 값을 달성하려는 것이 아닙니다. PID 값을 결정하기 위해 개발된 다양한 기술과 방법을 다루는 온라인 리소스가 많이 있으므로([여기](http://robotics.stackexchange.com/questions/167/what-are-good-strategies-for-tuning-pid-loops), [여기](http://innovativecontrols.com/blog/basics-tuning-pid-loops), [여기](https://hennulat.wordpress.com/2011/01/12/pid-loop-tuning-101/), [여기](http://eas.uccs.edu/wang/ECE4330F12/PID-without-a-PhD.pdf), [여기](http://www.atmel.com/Images/doc2558.pdf)), 변수를 이해하고 효과적으로 구현하기 위해 자체 연구와 실험을 수행하는 것이 필수적입니다.

PID 값의 변동성을 단순히 예로 들자면, 한 설정에서는 온도 PID 값(상승 조절)이 K<sub>P</sub> = 30, K<sub>I</sub> = 1.0, K<sub>D</sub> = 0.5였고, 습도 PID 값(상승 조절)이 K<sub>P</sub> = 1.0, K<sub>I</sub> = 0.2, K<sub>D</sub> = 0.5였습니다. 또한, 이러한 값이 최적은 아니었지만 환경 챔버 조건에서는 잘 작동했습니다.

#### 정확한 온도 조절

이 시스템은 두 개의 조절 장치(하나는 가열, 다른 하나는 냉각)를 사용하여 특정 온도로 온도를 올리고 내리도록 설정합니다.

센서를 추가한 다음, 각 센서에 적합한 장치와 핀/주소를 저장하고 센서를 활성화합니다.

두 개의 출력을 추가한 다음, 각 GPIO와 On Trigger 상태를 저장합니다.

PID를 추가한 다음, 새로 생성된 센서를 선택합니다. *설정값(Setpoint)*을 원하는 온도로 변경하고, *조절 방향(Regulate Direction)*을 "양방향(Both)"으로 설정합니다. *상승 출력(Raise Output)*을 가열 장치에 연결된 릴레이로 설정하고, *하강 릴레이(Lower Relay)*를 냉각 장치에 연결된 릴레이로 설정합니다.

K<sub>P</sub> = 1, K<sub>I</sub> = 0, K<sub>D</sub> = 0으로 설정한 다음 PID를 활성화합니다.

온도가 설정값보다 낮으면 PID 컨트롤러가 결정한 간격에 따라 히터가 활성화되어 온도가 설정값까지 상승합니다. 온도가 설정값(또는 설정값 + 버퍼)보다 높아지면 냉각 장치가 활성화되어 온도가 설정값으로 돌아갑니다. 온도가 설정값에 도달하지 않는 경우, K<sub>P</sub> 값을 증가시키고 시스템에 미치는 영향을 확인합니다. *읽기 간격(Read Interval)*과 K<sub>P</sub>만 조정하여 적절한 조절을 달성하기 위해 실험해 보세요. K<sub>P</sub>만으로 작동하는 조절이 이루어질 때까지 K<sub>I</sub>와 K<sub>D</sub>는 0으로 유지하세요.

6~12시간의 시간 범위에서 그래프를 확인하여 온도가 설정값에 얼마나 잘 조절되는지 확인하세요. "잘 조절된다"는 것은 특정 응용 프로그램과 허용 오차에 따라 다릅니다. 대부분의 PID 컨트롤러 응용 프로그램에서는 적절한 온도가 합리적인 시간 내에 도달하고 설정값 주변에서 진동이 적은 것을 선호합니다.

조절이 이루어진 후, K<sub>P</sub>를 약간(~25%) 줄이고 K<sub>I</sub>를 낮은 값(예: 0.1 또는 0.01)으로 증가시키며 PID를 시작하고 컨트롤러가 얼마나 잘 조절하는지 관찰하세요. K<sub>I</sub>를 천천히 증가시켜 조절이 빠르고 진동이 적어지도록 만드세요. 이 시점에서 시스템과 K<sub>D</sub> 값을 실험할 준비가 되었으며, K<sub>P</sub>와 K<sub>I</sub>가 조정된 후 K<sub>D</sub>를 실험해 보세요.

#### 고온 조절

양방향 조절이 필요하지 않은 경우 시스템을 단순화할 수 있습니다. 예를 들어, 냉각이 불필요한 경우 이를 시스템에서 제거하고 상승 조절만 사용할 수 있습니다.

[정확한 온도 조절](Functions.md#exact-temperature-regulation) 예제와 동일한 구성을 사용하되, *조절 방향(Regulate Direction)*을 "상승(Raise)"으로 변경하고 "하강 릴레이(Down Relay)" 섹션은 건드리지 마세요.

## PID 자동 튜닝

!!! 경고
    이 기능은 실험적입니다. PID의 이론, 작동 방식 및 튜닝에 익숙해진 후 사용하는 것이 좋습니다.

자동 튜닝 기능은 PID 컨트롤러에서 사용할 적절한 Kp, Ki, Kd 게인을 결정하는 데 유용한 독립형 컨트롤러입니다. 자동 튜너는 출력을 조작하고 특정 환경/시스템에서 측정된 반응을 분석합니다. PID 게인을 계산하기 위해 충분한 데이터를 수집하려면 선택한 출력으로 시스템을 여러 번 교란해야 합니다. 이 기능을 사용하려면 측정값과 측정된 특정 조건을 조정할 수 있는 출력을 선택하세요. 그런 다음, 노이즈 밴드와 출력 단계를 구성하고 기능을 활성화합니다. 자동 튜너의 로그는 데몬 로그(`[톱니바퀴 아이콘] -> AoT 로그 -> 데몬 로그`)에 나타납니다. 자동 튜닝이 수행되는 동안, 대시보드 그래프를 생성하여 측정값과 출력을 포함시키는 것이 좋습니다. 이를 통해 PID 자동 튜너가 수행하는 작업과 구성된 자동 튜닝 설정에서 발생할 수 있는 문제를 확인할 수 있습니다. 자동 튜닝이 완료되는 데 시간이 오래 걸리는 경우, 조작 중인 시스템에 충분한 안정성이 없어 신뢰할 수 있는 PID 게인 세트를 계산하지 못할 수 있습니다. 이는 시스템에 너무 많은 교란이 있거나 조건이 너무 빠르게 변하여 일관된 측정값 진동을 얻을 수 없는 경우일 수 있습니다. 이 경우, 시스템을 수정하여 안정성을 높이고 일관된 측정값 진동을 생성하도록 시도하세요. 자동 튜닝이 성공적으로 완료되면, PID 컨트롤러가 이를 처리할 수 있도록 교란을 다시 도입하여 추가 튜닝을 수행할 수 있습니다.

<table>
<thead>
<tr class="header">
<th>설정</th>
<th>설명</th>
</tr>
</thead>
<tbody>
<tr>
<td>측정값</td>
<td>출력이 영향을 미칠 특정 조건을 측정하는 입력 또는 기능 측정값입니다. 예를 들어, 온도 측정값일 수 있으며 출력은 히터일 수 있습니다.</td>
</tr>
<tr>
<td>출력</td>
<td>측정값에 영향을 미칠 출력입니다. 자동 튜닝 기능은 이 출력을 주기적으로 켜서 측정값이 설정값을 초과하도록 합니다.</td>
</tr>
<tr>
<td>주기</td>
<td>출력이 켜지는 간격입니다. 이는 PID 컨트롤러에 사용할 주기와 동일하게 설정해야 합니다. 다른 주기는 자동 튜닝이 생성하는 PID 게인에 큰 영향을 미칠 수 있습니다.</td>
</tr>
<tr>
<td>설정값</td>
<td>원하는 측정 조건 값입니다. 예를 들어, 온도를 측정하는 경우, 현재 온도보다 몇 도 높은 값으로 설정하여 출력이 활성화될 때 온도가 설정값을 초과하도록 해야 합니다.</td>
</tr>
<tr>
<td>노이즈 밴드</td>
<td>출력이 꺼지기 전에 측정 조건이 설정값을 초과해야 하는 범위입니다. 또한, 출력이 다시 켜지기 전에 측정 조건이 설정값 아래로 떨어져야 하는 범위입니다.</td>
</tr>
<tr>
<td>출력 단계</td>
<td>PID 주기마다 출력이 켜지는 시간(초)입니다. 예를 들어, 50% 출력으로 자동 튜닝하려면 출력 단계를 PID 주기의 절반 값으로 설정하세요.</td>
</tr>
<tr>
<td>방향</td>
<td>출력이 측정값에 영향을 미치는 방향입니다. 예를 들어, 히터는 온도를 올리고, 냉각기는 온도를 낮춥니다.</td>
</tr>
</tbody>
</table>

일반적인 그래프 출력은 다음과 같습니다:

![PID 자동 튜닝 출력](images/Autotune-Output-Example.png)

그리고 일반적인 데몬 로그 출력은 다음과 같습니다:

```console
2018-08-04 23:32:20,876 - aot.pid_3b533dff - INFO - Activated in 187.2 ms
2018-08-04 23:32:20,877 - aot.pid_autotune - INFO - PID Autotune started
2018-08-04 23:33:50,823 - aot.pid_autotune - INFO -
2018-08-04 23:33:50,830 - aot.pid_autotune - INFO - Cycle: 19
2018-08-04 23:33:50,831 - aot.pid_autotune - INFO - switched state: relay step down
2018-08-04 23:33:50,832 - aot.pid_autotune - INFO - input: 32.52
2018-08-04 23:36:00,854 - aot.pid_autotune - INFO -
2018-08-04 23:36:00,860 - aot.pid_autotune - INFO - Cycle: 45
2018-08-04 23:36:00,862 - aot.pid_autotune - INFO - found peak: 34.03
2018-08-04 23:36:00,863 - aot.pid_autotune - INFO - peak count: 1
2018-08-04 23:37:20,802 - aot.pid_autotune - INFO -
2018-08-04 23:37:20,809 - aot.pid_autotune - INFO - Cycle: 61
2018-08-04 23:37:20,810 - aot.pid_autotune - INFO - switched state: relay step up
2018-08-04 23:37:20,811 - aot.pid_autotune - INFO - input: 31.28
2018-08-04 23:38:30,867 - aot.pid_autotune - INFO -
2018-08-04 23:38:30,874 - aot.pid_autotune - INFO - Cycle: 75
2018-08-04 23:38:30,876 - aot.pid_autotune - INFO - found peak: 32.17
2018-08-04 23:38:30,878 - aot.pid_autotune - INFO - peak count: 2
2018-08-04 23:38:40,852 - aot.pid_autotune - INFO -
2018-08-04 23:38:40,858 - aot.pid_autotune - INFO - Cycle: 77
2018-08-04 23:38:40,860 - aot.pid_autotune - INFO - switched state: relay step down
2018-08-04 23:38:40,861 - aot.pid_autotune - INFO - input: 32.85
2018-08-04 23:40:50,834 - aot.pid_autotune - INFO -
2018-08-04 23:40:50,835 - aot.pid_autotune - INFO - Cycle: 103
2018-08-04 23:40:50,836 - aot.pid_autotune - INFO - found peak: 33.93
2018-08-04 23:40:50,836 - aot.pid_autotune - INFO - peak count: 3
2018-08-04 23:42:05,799 - aot.pid_autotune - INFO -
2018-08-04 23:42:05,805 - aot.pid_autotune - INFO - Cycle: 118
2018-08-04 23:42:05,806 - aot.pid_autotune - INFO - switched state: relay step up
2018-08-04 23:42:05,807 - aot.pid_autotune - INFO - input: 31.27
2018-08-04 23:43:15,816 - aot.pid_autotune - INFO -
2018-08-04 23:43:15,822 - aot.pid_autotune - INFO - Cycle: 132
2018-08-04 23:43:15,824 - aot.pid_autotune - INFO - found peak: 32.09
2018-08-04 23:43:15,825 - aot.pid_autotune - INFO - peak count: 4
2018-08-04 23:43:25,790 - aot.pid_autotune - INFO -
2018-08-04 23:43:25,796 - aot.pid_autotune - INFO - Cycle: 134
2018-08-04 23:43:25,797 - aot.pid_autotune - INFO - switched state: relay step down
2018-08-04 23:43:25,798 - aot.pid_autotune - INFO - input: 32.76
2018-08-04 23:45:30,802 - aot.pid_autotune - INFO -
2018-08-04 23:45:30,808 - aot.pid_autotune - INFO - Cycle: 159
2018-08-04 23:45:30,810 - aot.pid_autotune - INFO - found peak: 33.98
2018-08-04 23:45:30,811 - aot.pid_autotune - INFO - peak count: 5
2018-08-04 23:45:30,812 - aot.pid_autotune - INFO -
2018-08-04 23:45:30,814 - aot.pid_autotune - INFO - amplitude: 0.9099999999999989
2018-08-04 23:45:30,815 - aot.pid_autotune - INFO - amplitude deviation: 0.06593406593406595
2018-08-04 23:46:40,851 - aot.pid_autotune - INFO -
2018-08-04 23:46:40,857 - aot.pid_autotune - INFO - Cycle: 173
2018-08-04 23:46:40,858 - aot.pid_autotune - INFO - switched state: relay step up
2018-08-04 23:46:40,859 - aot.pid_autotune - INFO - input: 31.37
2018-08-04 23:47:55,860 - aot.pid_autotune - INFO -
2018-08-04 23:47:55,866 - aot.pid_autotune - INFO - Cycle: 188
2018-08-04 23:47:55,868 - aot.pid_autotune - INFO - found peak: 32.36
2018-08-04 23:47:55,869 - aot.pid_autotune - INFO - peak count: 6
2018-08-04 23:47:55,870 - aot.pid_autotune - INFO -
2018-08-04 23:47:55,871 - aot.pid_autotune - INFO - amplitude: 0.9149999999999979
2018-08-04 23:47:55,872 - aot.pid_autotune - INFO - amplitude deviation: 0.032786885245900406
2018-08-04 23:47:55,873 - aot.pid_3b533dff - INFO - time:  16 min
2018-08-04 23:47:55,874 - aot.pid_3b533dff - INFO - state: succeeded
2018-08-04 23:47:55,874 - aot.pid_3b533dff - INFO -
2018-08-04 23:47:55,875 - aot.pid_3b533dff - INFO - rule: ziegler-nichols
2018-08-04 23:47:55,876 - aot.pid_3b533dff - INFO - Kp: 0.40927018474290117
2018-08-04 23:47:55,877 - aot.pid_3b533dff - INFO - Ki: 0.05846588600007114
2018-08-04 23:47:55,879 - aot.pid_3b533dff - INFO - Kd: 0.7162385434443115
2018-08-04 23:47:55,880 - aot.pid_3b533dff - INFO -
2018-08-04 23:47:55,881 - aot.pid_3b533dff - INFO - rule: tyreus-luyben
2018-08-04 23:47:55,887 - aot.pid_3b533dff - INFO - Kp: 0.3162542336649691
2018-08-04 23:47:55,889 - aot.pid_3b533dff - INFO - Ki: 0.010165091543194185
2018-08-04 23:47:55,890 - aot.pid_3b533dff - INFO - Kd: 0.7028026111719073
2018-08-04 23:47:55,891 - aot.pid_3b533dff - INFO -
2018-08-04 23:47:55,892 - aot.pid_3b533dff - INFO - rule: ciancone-marlin
2018-08-04 23:47:55,892 - aot.pid_3b533dff - INFO - Kp: 0.21083615577664605
2018-08-04 23:47:55,893 - aot.pid_3b533dff - INFO - Ki: 0.06626133746674728
2018-08-04 23:47:55,893 - aot.pid_3b533dff - INFO - Kd: 0.3644161687558038
2018-08-04 23:47:55,894 - aot.pid_3b533dff - INFO -
2018-08-04 23:47:55,894 - aot.pid_3b533dff - INFO - rule: pessen-integral
2018-08-04 23:47:55,895 - aot.pid_3b533dff - INFO - Kp: 0.49697093861638
2018-08-04 23:47:55,895 - aot.pid_3b533dff - INFO - Ki: 0.0887428626786794
2018-08-04 23:47:55,896 - aot.pid_3b533dff - INFO - Kd: 1.04627757151908
2018-08-04 23:47:55,896 - aot.pid_3b533dff - INFO -
2018-08-04 23:47:55,897 - aot.pid_3b533dff - INFO - rule: some-overshoot
2018-08-04 23:47:55,898 - aot.pid_3b533dff - INFO - Kp: 0.23191977135431066
2018-08-04 23:47:55,898 - aot.pid_3b533dff - INFO - Ki: 0.03313066873337365
2018-08-04 23:47:55,899 - aot.pid_3b533dff - INFO - Kd: 1.0823160212047374
2018-08-04 23:47:55,899 - aot.pid_3b533dff - INFO -
2018-08-04 23:47:55,900 - aot.pid_3b533dff - INFO - rule: no-overshoot
2018-08-04 23:47:55,900 - aot.pid_3b533dff - INFO - Kp: 0.1391518628125864
2018-08-04 23:47:55,901 - aot.pid_3b533dff - INFO - Ki: 0.01987840124002419
2018-08-04 23:47:55,901 - aot.pid_3b533dff - INFO - Kd: 0.6493896127228425
2018-08-04 23:47:55,902 - aot.pid_3b533dff - INFO -
2018-08-04 23:47:55,902 - aot.pid_3b533dff - INFO - rule: brewing
2018-08-04 23:47:55,903 - aot.pid_3b533dff - INFO - Kp: 5.566074512503456
2018-08-04 23:47:55,904 - aot.pid_3b533dff - INFO - Ki: 0.11927040744014512
2018-08-04 23:47:55,904 - aot.pid_3b533dff - INFO - Kd: 4.101408080354794
```

## 조건부 기능

조건부 기능은 사용자가 생성한 Python 코드를 기반으로 간단한 작업부터 복잡한 작업까지 수행하는 데 사용됩니다. 조건부 기능은 Python 3 코드를 실행하고, 코드 내에서 AoT와 상호작용하기 위해 조건(Conditions) 및 [작업(Actions)](Actions.md)을 사용할 수 있도록 합니다. 조건은 일반적으로 AoT에서 데이터를 가져오는 데 사용되며(예: 입력 측정값), 작업은 AoT에 영향을 미치는 데 사용됩니다(예: 출력 작동 또는 PID 컨트롤러 일시 중지). 추가한 각 조건과 작업은 Python 코드에서 사용하는 방법을 보여주는 설명과 예제 코드를 제공합니다.

!!! 참고
    `Timeout`은 `Run Python Code`가 실행되는 데 걸리는 시간보다 길게 설정해야 합니다(`Timeout`이 너무 짧게 설정되면 코드의 일부만 실행될 수 있습니다).

!!! 참고
    `Period`는 `Run Python Code`가 실행되는 데 걸리는 시간보다 길게 설정해야 합니다. 그렇지 않으면 이전 실행이 끝나기 전에 코드가 다시 실행됩니다.

!!! 참고
    코드는 AoT가 실행되는 동일한 Python 가상 환경 내에서 실행됩니다. 따라서 코드에서 Python 라이브러리를 사용하려면 해당 환경에 라이브러리를 설치해야 합니다. 이 가상 환경은 `/opt/AoT/env`에 위치하며, 예를 들어 "my_library"를 pip로 설치하려면 `sudo /opt/AoT/env/bin/pip install my_library`를 실행하면 됩니다.

### 조건부 옵션

<table>
<thead>
<tr class="header">
<th>설정</th>
<th>설명</th>
</tr>
</thead>
<tbody>
<tr>
<td>Python 코드 가져오기</td>
<td>Python 라이브러리를 가져오는 데 사용되는 Python 3 코드입니다. 이는 조건부 기능 코드가 생성될 때 클래스가 생성되기 전에 실행됩니다.</td>
</tr>
<tr>
<td>Python 코드 초기화</td>
<td>클래스의 초기화 중에 실행되는 Python 3 코드입니다(__init__() 내에서 실행). 여기에서 클래스 내에서 사용할 변수를 초기화합니다.</td>
</tr>
<tr>
<td>Python 코드 실행</td>
<td>설정된 주기마다 실행되는 Python 3 코드입니다. 여기에서 조건과 작업이 실행됩니다. 조건 또는 작업이 추가되면 각 조건 또는 작업에 대해 실행할 수 있는 함수가 해당 조건 또는 작업 위에 표시됩니다.</td>
</tr>
<tr>
<td>Python 코드 상태</td>
<td>다른 컨트롤러 및 위젯에 정보를 전달할 수 있는 딕셔너리를 반환할 수 있습니다. 예를 들어, 기능 상태 위젯은 대시보드에 이 정보를 표시합니다. 정보를 반환하지 않으려면 이 코드를 제거할 수 있습니다.</td>
</tr>
<tr>
<td>주기(초)</td>
<td>`Run Python Code`가 실행되는 주기(초)입니다.</td>
</tr>
<tr>
<td>시작 오프셋(초)</td>
<td>조건부 기능이 활성화된 후 처음 실행되기 전에 대기할 시간(초)입니다.</td>
</tr>
<tr>
<td>로그 레벨: 디버그</td>
<td>데몬 로그에 디버그 라인을 표시합니다.</td>
</tr>
<tr>
<td>메시지에 코드 포함</td>
<td>작업에 전달되는 메시지(self.message)에 Python 코드를 포함합니다.</td>
</tr>
</tbody>
</table>
</tr>
</tbody>
</table>

조건은 `Run Python Code` 내에서 사용할 수 있는 함수로, 특정 정보를 반환합니다.

<table>
<thead>
<tr class="header">
<th>조건</th>
<th>설명</th>
</tr>
</thead>
<tbody>
<tr>
<td>측정값 (단일, 최신)</td>
<td>입력 또는 장치에서 최신 측정값을 가져옵니다. 최대 연령(초)을 설정하여 값을 허용할 시간을 제한할 수 있습니다. 최신 값이 이 기간보다 오래된 경우, "None"이 반환됩니다.</td>
</tr>
<tr>
<td>측정값 (단일, 과거, 평균)</td>
<td>입력 또는 장치에서 과거 측정값을 가져온 후 평균을 계산합니다. 최대 연령(초)을 설정하여 값을 허용할 시간을 제한할 수 있습니다. 모든 값이 이 기간보다 오래된 경우, "None"이 반환됩니다.</td>
</tr>
<tr>
<td>측정값 (단일, 과거, 합계)</td>
<td>입력 또는 장치에서 과거 측정값을 가져온 후 합계를 계산합니다. 최대 연령(초)을 설정하여 값을 허용할 시간을 제한할 수 있습니다. 모든 값이 이 기간보다 오래된 경우, "None"이 반환됩니다.</td>
</tr>
<tr>
<td>측정값 (다중, 과거)</td>
<td>입력 또는 장치에서 과거 측정값을 가져옵니다. 최대 연령(초)을 설정하여 값을 허용할 시간을 제한할 수 있습니다. 이 기간 내에 값을 찾을 수 없는 경우, "None"이 반환됩니다. 이는 "측정값 (단일)" 조건과 다르게 'time' 및 'value' 키 쌍을 포함한 딕셔너리 목록을 반환합니다.</td>
</tr>
<tr>
<td>GPIO 상태</td>
<td>현재 GPIO 상태를 가져오며, HIGH일 경우 1, LOW일 경우 0을 반환합니다. 최신 값이 이 기간보다 오래된 경우, "None"이 반환됩니다.</td>
</tr>
<tr>
<td>출력 상태</td>
<td>출력이 현재 켜져 있으면 'on', 꺼져 있으면 'off'를 반환합니다.</td>
</tr>
<tr>
<td>출력 켜짐 지속 시간</td>
<td>출력이 현재 켜져 있는 시간을 초 단위로 반환합니다. 꺼져 있으면 0을 반환합니다.</td>
</tr>
<tr>
<td>컨트롤러 실행 상태</td>
<td>컨트롤러가 활성 상태이면 True, 비활성 상태이면 False를 반환합니다.</td>
</tr>
<tr>
<td>최대 연령 (초)</td>
<td>측정값이 가질 수 있는 최대 연령(초)입니다. 마지막 측정값이 이보다 오래된 경우, 측정값 대신 "None"이 반환됩니다.</td>
</tr>
</tbody>
</table>

### 조건부 설정 가이드

Python 3 환경에서 이러한 조건부 기능이 실행됩니다. Python 코드 내에서 다음 함수를 사용할 수 있습니다.

!!! 참고
    Python 코드 들여쓰기는 반드시 4개의 공백을 사용해야 합니다(2개의 공백, 탭 등은 사용할 수 없습니다).

```markdown
### 조건부 함수 사용 예제

다음은 조건부 함수에서 사용할 수 있는 몇 가지 예제입니다. 각 `self.condition("ID")`은 해당 조건의 최신 측정값을 반환하며, 설정된 최대 연령(Max Age) 내에 있는 경우에만 값을 반환합니다.

```python
# 예제 1: 측정값이 None인 경우
# 입력이 작동하지 않을 때 이메일 알림 작업을 실행하는 데 유용합니다.
if self.condition("asdf1234") is None:
    self.run_all_actions()  # 모든 작업 실행

# 예제 2: 두 개의 측정값 조건 테스트
measure_1 = self.condition("asdf1234")
measure_2 = self.condition("hjkl5678")
if None not in [measure_1, measure_2]:
    # 두 측정값이 모두 None이 아닌 경우
    if measure_1 < 20 and measure_2 > 10:
        self.run_all_actions()  # 모든 작업 실행

# 예제 3: 두 측정값과 측정값 합계 테스트
measure_1 = self.condition("asdf1234")
measure_2 = self.condition("hjkl5678")
if None not in [measure_1, measure_2]:
    sum_ = measure_1 + measure_2
    if measure_1 > 2 and 10 < measure_2 < 23 and sum_ < 30.5:
        self.run_all_actions()

# 예제 4: 조건 결합
measurement = self.condition("asdf1234")
if measurement is not None and 20 < measurement < 30:  # 조건 결합
    self.run_all_actions()

# 예제 5: 두 측정값 테스트
# Edge Input을 0 또는 1에서 True 또는 False로 변환
measure_1 = self.condition("asdf1234")
measure_2 = self.condition("hjkl5678")
if None not in [measure_1, measure_2]:
    if bool(measure_1) and measure_2 > 10:
        self.run_all_actions()

# 예제 6: "or" 조건 및 반올림된 측정값 테스트
measure_1 = self.condition("asdf1234")
measure_2 = self.condition("hjkl5678")
if None not in [measure_1, measure_2]:
    if measure_1 > 20 or int(round(measure_2)) in [20, 21, 22]:
        self.run_all_actions()

# 예제 7: self를 사용하여 여러 실행 간 변수 저장
measurement = self.condition("asdf1234")
if not hasattr(self, "stored_measurement"):  # 변수 초기화
    self.stored_measurement = measurement
if measurement is not None:
    if abs(measurement - self.stored_measurement) > 10:
        self.run_all_actions()  # 차이가 10보다 큰 경우
    self.stored_measurement = measurement  # 측정값 저장
```

위 예제는 조건부 함수의 기본적인 사용법을 보여줍니다. 필요에 따라 코드를 수정하여 특정 요구 사항에 맞게 조정하세요.
```

```python
# 예제 1: 측정값이 None인 경우
# 입력이 작동하지 않을 때 이메일 알림 작업을 실행하는 데 유용합니다.
if self.condition("asdf1234") is None:
    self.run_all_actions()  # 모든 작업 실행

# 예제 2: 두 개의 측정값 조건 테스트
measure_1 = self.condition("asdf1234")
measure_2 = self.condition("hjkl5678")
if None not in [measure_1, measure_2]:
    # 두 측정값이 모두 None이 아닌 경우
    if measure_1 < 20 and measure_2 > 10:
        # measure_1이 20보다 작고 measure_2가 10보다 큰 경우
        self.run_all_actions()  # 모든 작업 실행

# 예제 3: 두 측정값과 측정값 합계 테스트
measure_1 = self.condition("asdf1234")
measure_2 = self.condition("hjkl5678")
if None not in [measure_1, measure_2]:
    sum_ = measure_1 + measure_2
    if measure_1 > 2 and 10 < measure_2 < 23 and sum_ < 30.5:
        self.run_all_actions()

# 예제 4: 조건 결합
measurement = self.condition("asdf1234")
if measurement is not None and 20 < measurement < 30:  # 조건 결합
    self.run_all_actions()

# 예제 5: 두 측정값 테스트
# Edge Input을 0 또는 1에서 True 또는 False로 변환
measure_1 = self.condition("asdf1234")
measure_2 = self.condition("hjkl5678")
if None not in [measure_1, measure_2]:
    if bool(measure_1) and measure_2 > 10:
        self.run_all_actions()

# 예제 6: "or" 조건 및 반올림된 측정값 테스트
measure_1 = self.condition("asdf1234")
measure_2 = self.condition("hjkl5678")
if None not in [measure_1, measure_2]:
    if measure_1 > 20 or int(round(measure_2)) in [20, 21, 22]:
        self.run_all_actions()

# 예제 7: self를 사용하여 여러 실행 간 변수 저장
measurement = self.condition("asdf1234")
if not hasattr(self, "stored_measurement"):  # 변수 초기화
    self.stored_measurement = measurement
if measurement is not None:
    if abs(measurement - self.stored_measurement) > 10:
        self.run_all_actions()  # 차이가 10보다 큰 경우
    self.stored_measurement = measurement  # 측정값 저장
```
"측정값 (다중)" 조건은 설정된 최대 연령(Max Age) 내에서 마지막 측정값뿐만 아니라 과거의 특정 값이 저장되었는지 확인하려는 경우 유용합니다. 이는 각 숫자 값이 확인해야 할 서로 다른 경고를 나타내는 경고 시스템이 있는 경우, 과거 값 중 특정 값이 발생했는지 확인하는 데 사용할 수 있습니다. 아래는 지난 30분(최대 연령: 1800초) 동안의 모든 측정값을 가져와 반환된 목록에서 "119"와 같은 값이 있는지 확인하는 예제입니다. "119"가 존재하면 작업이 실행되고 `break`를 사용하여 `for` 루프를 종료합니다.

```python
# 예제 1: 지난 30분 동안의 측정값에서 특정 값 찾기 (최대 연령: 1800초)
measurements = self.condition_dict("asdf1234")
if measurements:  # 목록이 비어 있지 않은 경우
    for each_measure in measurements:  # 목록의 각 측정값을 반복
        if each_measure['value'] == 119:
            self.logger.info("119 경고가 타임스탬프 {time}에서 발견되었습니다.".format(
                time=each_measure['time']))
            self.run_all_actions()
            break  # for 루프 종료
```

고급 조건부 `Run Python Code` 예제:

이 예제들은 위의 초급 예제를 확장하여 특정 작업을 활성화합니다. 다음 예제에서는 조건부 기능의 `Actions` 섹션에서 찾을 수 있는 ID를 참조하는 작업을 사용합니다. 두 개의 예제 작업 ID가 사용됩니다: "qwer1234" 및 "uiop5678". 추가로, self.run_all_actions()는 여기서 사용되며, 생성된 순서대로 모든 작업을 실행합니다.

```python
# 예제 1
measurement = self.condition("asdf1234")
if measurement is None:
    self.run_action("qwer1234")
elif measurement > 23:
    self.run_action("uiop5678")
else:
    self.run_all_actions()

# 예제 2: 두 개의 측정값 테스트
measure_1 = self.condition("asdf1234")
measure_2 = self.condition("hjkl5678")
if None not in [measure_1, measure_2]:
    if measure_1 < 20 and measure_2 > 10:
        self.run_action("qwer1234")
        self.run_action("uiop5678")

# 예제 3: 두 개의 측정값과 측정값 합계 테스트
measure_1 = self.condition("asdf1234")
measure_2 = self.condition("hjkl5678")
if None not in [measure_1, measure_2]:
    sum_ = measure_1 + measure_2
    if measure_1 > 2 and 10 < measure_2 < 23 and sum_ < 30.5:
        self.run_action("qwer1234")
    else:
        self.run_action("uiop5678")

# 예제 4: 하나의 조건으로 결합
measurement = self.condition("asdf1234")
if measurement is not None and 20 < measurement < 30:
    self.run_action("uiop5678")

# 예제 5: 두 개의 측정값 테스트, Edge 입력을 0/1에서 True/False로 변환
measure_1 = self.condition("asdf1234")
measure_2 = self.condition("hjkl5678")
if None not in [measure_1, measure_2]:
    if bool(measure_1) and measure_2 > 10:
        self.run_all_actions()

# 예제 6: "or" 조건 및 반올림된 측정값 테스트
measure_1 = self.measure("asdf1234")
measure_2 = self.measure("hjkl5678")
if None not in [measure_1, measure_2]:
    if measure_1 > 20 or int(round(measure_2)) in [20, 21, 22]:
        self.run_action("qwer1234")
        if measure_1 > 30:
            self.run_action("uiop5678")
```

작업이 메시지(E-Mail 또는 Note)를 수신하는 유형인 경우, 이 메시지에 추가 정보를 포함하도록 수정할 수 있습니다. 이를 통해 새로운 정보가 Note, E-Mail 등으로 전달되기 전에 함수에 전달됩니다. 이를 수행하려면 문자열을 변수 `self.message`에 추가하고, 이를 `self.run_action()` 또는 `self.run_all_actions()`의 `message` 매개변수에 추가하세요. 아래는 몇 가지 예제입니다. `=` 대신 `+=`를 사용하여 문자열을 변수 `self.message`에 추가하는 점에 유의하세요. 이는 기존 값을 덮어쓰지 않고 추가합니다.

```python
# 예제 1
measurement = self.measure("asdf1234")
if measurement is None and measurement > 23:
    self.message += "측정값은 {}".format(measurement)
    self.run_action("uiop5678", message=self.message)

# 예제 2
measure_1 = self.measure("asdf1234")
measure_2 = self.measure("hjkl5678")
if None not in [measure_1, measure_2]:
    if measure_1 < 20 and measure_2 > 10:
        self.message += "측정값 1: {m1}, 측정값 2: {m2}".format(
            m1=measure_1, m2=measure_2)
        self.run_all_actions(message=self.message)
```

로깅은 `self.logger`를 사용하여 데몬 로그에 메시지를 기록하는 데도 사용할 수 있습니다. 로깅 수준에는 "info", "warning", "error", "debug"가 포함됩니다. 디버그 로그 라인은 입력의 로깅 수준이 "Debug"로 설정된 경우에만 데몬 로그에 나타납니다.

```python
# 예제 1
measurement = self.measure("asdf1234")
if measurement is None and measurement > 23:
    self.logger.error("경고, 측정값은 {}".format(measurement))
    self.message += "측정값은 {}".format(measurement)
    self.run_action("uiop5678", message=self.message)
```

조건부를 활성화하기 전에 모든 가능한 시나리오를 철저히 탐색하고 충돌을 제거하는 구성을 계획하는 것이 좋습니다. 일부 장치나 출력은 빠르게 켜고 끄는 경우 비정상적으로 반응하거나 실패할 수 있습니다. 따라서 장치를 출력에 연결하기 전에 구성을 시험 실행해 보세요.

## 트리거

트리거 컨트롤러는 출력이 켜지거나 꺼지는 것, GPIO 핀이 전압 상태를 변경하는 것(에지 감지, 상승 또는 하강), 다양한 타이머(지속 시간, 시간 간격, 특정 시간 등)를 포함한 시간 이벤트, 또는 특정 위도와 경도의 일출/일몰 시간과 같은 이벤트가 트리거될 때 작업을 실행합니다. 트리거가 구성되면, 해당 이벤트가 트리거될 때 실행할 [작업](Actions.md)을 원하는 만큼 추가하세요.

### 출력 (켜짐/꺼짐) 옵션

출력 상태를 모니터링합니다.

<table>
<thead>
<tr class="header">
<th>설정</th>
<th>설명</th>
</tr>
</thead>
<tbody>
<tr>
<td>출력 조건</td>
<td>상태 변경을 모니터링할 출력입니다.</td>
</tr>
<tr>
<td>상태 조건</td>
<td>출력 상태가 켜짐(On) 또는 꺼짐(Off)으로 변경되면 조건이 트리거됩니다. "켜짐(모든 지속 시간)"을 선택하면 출력이 켜지는 시간이 얼마든지 조건이 트리거되며, "켜짐"만 선택하면 출력이 설정된 "지속 시간(초)" 동안 켜질 때만 조건이 트리거됩니다.</td>
</tr>
<tr>
<td>지속 시간 조건 (초)</td>
<td>"켜짐"이 선택된 경우, 출력이 특정 지속 시간(초) 동안 켜질 때만 조건이 트리거되도록 설정할 수 있습니다.</td>
</tr>
</tbody>
</table>

### 출력 (PWM) 옵션

PWM 출력 상태를 모니터링합니다.

<table>
<thead>
<tr class="header">
<th>설정</th>
<th>설명</th>
</tr>
</thead>
<tbody>
<tr>
<td>출력 조건</td>
<td>상태 변경을 모니터링할 출력입니다.</td>
</tr>
<tr>
<td>상태 조건</td>
<td>출력의 듀티 사이클이 설정된 값보다 크거나, 작거나, 같을 때 조건부 작업이 트리거됩니다.</td>
</tr>
<tr>
<td>듀티 사이클 조건 (%)</td>
<td>출력의 듀티 사이클을 비교할 기준 값입니다.</td>
</tr>
</tbody>
</table>
</table>

### 에지 옵션

핀 상태의 상승 및/또는 하강 에지를 모니터링합니다.

<table>
<thead>
<tr class="header">
<th>설정</th>
<th>설명</th>
</tr>
</thead>
<tbody>
<tr>
<td>에지 감지 시</td>
<td>상태 변화가 감지되면 조건이 트리거됩니다. LOW(0볼트)에서 HIGH(3.5볼트)로 상태가 변경될 때 상승 에지, HIGH(3.3볼트)에서 LOW(0볼트)로 상태가 변경될 때 하강 에지, 또는 상승 및 하강 모두를 선택할 수 있습니다.</td>
</tr>
</tbody>
</table>

### PWM 메서드 실행 옵션

지속 시간 메서드를 선택하면 선택한 PWM 출력에 메서드에서 지정한 듀티 사이클이 설정됩니다.

<table>
<thead>
<tr class="header">
<th>설정</th>
<th>설명</th>
</tr>
</thead>
<tbody>
<tr>
<td>지속 시간 메서드</td>
<td>사용할 메서드를 선택합니다.</td>
</tr>
<tr>
<td>PWM 출력</td>
<td>사용할 PWM 출력을 선택합니다.</td>
</tr>
<tr>
<td>주기(초)</td>
<td>듀티 사이클을 계산할 시간 간격을 선택한 다음, PWM 출력에 적용합니다.</td>
</tr>
<tr>
<td>주기마다 트리거</td>
<td>주기마다 조건부 작업을 트리거합니다.</td>
</tr>
<tr>
<td>활성화 시 트리거</td>
<td>조건부가 활성화될 때 조건부 작업을 트리거합니다.</td>
</tr>
</tbody>
</table>

### 일출/일몰 옵션

위도와 경도를 기준으로 일출 또는 일몰(또는 해당 시간의 오프셋) 시 이벤트를 트리거합니다.

<table>
<thead>
<tr class="header">
<th>설정</th>
<th>설명</th>
</tr>
</thead>
<tbody>
<tr>
<td>일출 또는 일몰</td>
<td>조건부를 트리거할 시점을 선택합니다. 일출 또는 일몰 중 하나를 선택합니다.</td>
</tr>
<tr>
<td>위도(소수점)</td>
<td>일출/일몰의 위도를 소수점 형식으로 입력합니다.</td>
</tr>
<tr>
<td>경도(소수점)</td>
<td>일출/일몰의 경도를 소수점 형식으로 입력합니다.</td>
</tr>
<tr>
<td>천정각</td>
<td>태양의 천정각을 설정합니다.</td>
</tr>
<tr>
<td>날짜 오프셋(일)</td>
<td>일출/일몰 시간에 대한 날짜 오프셋을 설정합니다(양수 또는 음수).</td>
</tr>
<tr>
<td>시간 오프셋(분)</td>
<td>일출/일몰 시간에 대한 시간 오프셋을 설정합니다(양수 또는 음수).</td>
</tr>
</tbody>
</table>

### 타이머 (지속 시간) 옵션

타이머를 실행하여 설정된 주기마다 조건부 작업을 트리거합니다.

<table>
<thead>
<tr class="header">
<th>설정</th>
<th>설명</th>
</tr>
</thead>
<tbody>
<tr>
<td>주기 (초)</td>
<td>조건부 작업을 트리거하는 시간 간격(초)입니다.</td>
</tr>
<tr>
<td>시작 오프셋 (초)</td>
<td>조건부가 활성화된 후 첫 번째 트리거가 실행되기까지 대기할 시간(초)을 설정합니다.</td>
</tr>
</tbody>
</table>

### 타이머 (일일 특정 시간) 옵션

매일 특정 시간에 조건부 작업을 트리거하는 타이머를 실행합니다.

<table>
<thead>
<tr class="header">
<th>설정</th>
<th>설명</th>
</tr>
</thead>
<tbody>
<tr>
<td>시작 시간 (HH:MM)</td>
<td>조건부 작업을 트리거할 시간을 "HH:MM" 형식으로 설정합니다. HH는 시간을, MM은 분을 나타내며, 24시간 형식으로 입력합니다.</td>
</tr>
</tbody>
</table>

### 타이머 (일일 시간 범위) 옵션

설정된 시작 시간과 종료 시간 사이에서 특정 주기로 조건부 작업을 트리거하는 타이머를 실행합니다. 예를 들어, 시작 시간을 10:00, 종료 시간을 11:00, 주기를 120초로 설정하면, 10시부터 11시 사이에 120초마다 조건부 작업이 트리거됩니다.

이 기능은 특정 시간 동안 출력이 켜져 있어야 하며, 단순한 특정 시간 타이머가 전원 장애로 인해 사이클이 중단되는 것을 방지하고자 할 때 유용합니다. 예를 들어, 시작 -> 종료 시간 동안 몇 분마다 출력을 켜도록 설정하면, 해당 시간 동안 출력이 유지되도록 보장할 수 있습니다.

<table>
<thead>
<tr class="header">
<th>설정</th>
<th>설명</th>
</tr>
</thead>
<tbody>
<tr>
<td>시작 시간 (HH:MM)</td>
<td>조건부 작업을 트리거할 시작 시간을 "HH:MM" 형식으로 설정합니다. HH는 시간을, MM은 분을 나타내며, 24시간 형식으로 입력합니다.</td>
</tr>
<tr>
<td>종료 시간 (HH:MM)</td>
<td>조건부 작업을 트리거할 종료 시간을 "HH:MM" 형식으로 설정합니다. HH는 시간을, MM은 분을 나타내며, 24시간 형식으로 입력합니다.</td>
</tr>
<tr>
<td>주기 (초)</td>
<td>조건부 작업을 트리거하는 시간 간격(초)입니다.</td>
</tr>
</tbody>
</table>

## Trigger - Sequence

Trigger - Sequence 기능은 여러 액션을 정해진 순서와 시간 간격에 따라 순차적으로 실행할 수 있게 해줍니다.

### 주요 개념 및 동작 방식

- **순차 실행 (Sequential Execution)**: 등록된 액션들을 설정된 GridStack 위치(`position`) 순서대로 실행합니다.
- **실행 모드 (Modes)**:
    - **Single (기본값)**: 각 단계마다 독립적인 기간을 적용합니다. 
        - **계산식**: `총 활성 시간 = Head Overlap + Base Duration + Tail Overlap`
        - **동작**: 이전 단계가 끝나기 `Overlap` 초 전에 다음 단계가 시작되어 부드러운 전환을 지원합니다.
    - **Total (Full-span)**: 전체 시퀀스가 실행되는 동안 계속 켜져 있어야 하는 액션(예: 메인 펌프)에 사용됩니다. 시퀀스의 시작부터 마지막 `Single` 액션이 종료될 때까지 유지됩니다.
- **동적 기간 (Dynamic Duration)**:
    - `action_duration_id` 옵션을 통해 특정 입력(Input)의 측정값을 실행 시간으로 사용할 수 있습니다.
    - 형식: `Input_UUID` 또는 `Input_UUID,Measurement_UUID`.
    - 유효성: `time_offset_minutes` 내의 최신 측정값만 사용하며, 없을 경우 설정된 기본 `action_duration`을 사용합니다.
- **오버랩 (Overlaps)**:
    - `output_duration` 설정값을 사용하여 단계 사이의 전환 시간을 결정합니다.
    - 첫 번째 액션은 `Tail Overlap`만, 중간 액션은 `Head & Tail Overlap`을, 마지막 액션은 `Head Overlap`만 가집니다.
- **제약 사항 (Window & Latency)**:
    - **Execution Window**: `timer_start_time` ~ `timer_end_time` 사이에만 시퀀스가 시작되거나 실행됩니다. 범위를 벗어나면 강제 종료됩니다.
    - **Start Latency**: 트리거(활성화) 발생 후 실제 시퀀스 시작까지의 대기 시간(`timer_start_offset`)을 초 단위로 설정합니다.

### 설정 옵션 명세

| 설정 키 | 설명 |
| :--- | :--- |
| `period` | 전체 시퀀스 사이클의 반복 주기 (초 단위). |
| `output_duration` | 액션 간의 오버랩 시간 (초 단위). |
| `timer_start_offset` | 활성화 후 시퀀스 시작까지의 지연 시간. |
| `time_offset_minutes` | 동적 기간 측정값의 최대 유효 시간 (분 단위). |
| `enabled` | 개별 액션의 활성화 여부. |
| `sequence_mode` | 'single' 또는 'total' 선택. |
| `action_duration` | 해당 단계의 기본 실행 시간 (초 단위). |
| `action_duration_id` | 동적 실행 시간을 가져올 장치/측정값 ID. |
