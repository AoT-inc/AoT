```markdown
## 실시간 측정

페이지: `추가기능 -> 실시간 측정`

`실시간 측정` 페이지는 사용자가 AoT에 로그인한 후 처음으로 보게 되는 페이지입니다. 이 페이지는 입력 및 함수 컨트롤러에서 수집 중인 현재 측정값을 표시합니다. `실시간` 페이지에 아무것도 표시되지 않는 경우, 입력 또는 함수 컨트롤러가 올바르게 구성되고 활성화되었는지 확인하십시오. 데이터는 측정 데이터베이스에서 페이지로 자동으로 업데이트됩니다.

## 비동기 그래프

페이지: `추가기능 -> 그래프`

비동기 그래프는 비교적 긴 기간(주/월/년)에 걸친 데이터 세트를 보기 위해 유용한 그래픽 데이터 디스플레이입니다. 이는 동기 그래프로 보기에는 데이터 및 프로세서 집약적일 수 있습니다. 시간 프레임을 선택하면 해당 시간 범위의 데이터가 로드됩니다(존재하는 경우). 첫 번째 뷰는 선택한 전체 데이터 세트의 뷰가 됩니다. 각 뷰/확대 시 700개의 데이터 포인트가 로드됩니다. 선택한 시간 범위에 대해 기록된 데이터 포인트가 700개를 초과하는 경우, 해당 시간 범위의 포인트를 평균화하여 700개의 포인트가 생성됩니다. 이를 통해 대규모 데이터 세트를 탐색하는 데 필요한 데이터 양이 크게 줄어듭니다. 예를 들어, 4개월 분량의 데이터가 모두 다운로드된다면 10메가바이트가 될 수 있습니다. 그러나 4개월 범위를 볼 때 10메가바이트의 모든 데이터 포인트를 보는 것은 불가능하며, 포인트의 집계는 불가피합니다. 비동기 데이터 로딩을 통해 사용자는 보는 데이터만 다운로드합니다. 따라서 그래프를 로드할 때마다 10메가바이트를 다운로드하는 대신 약 50kb만 다운로드되며, 새로운 확대 수준이 선택될 때마다 추가로 약 50kb가 다운로드됩니다.

!!! 참고
  그래프는 측정값이 필요하므로 데이터를 표시하려면 적어도 하나의 입력/출력/함수 등이 추가되고 활성화되어야 합니다.

## 대시보드

페이지: `대시보드`

대시보드는 다양한 대시보드 위젯 덕분에 데이터를 보기 위해서나 시스템을 조작하기 위해 사용할 수 있습니다. 여러 대시보드를 생성할 수 있으며, 배열 변경을 방지하기 위해 잠글 수도 있습니다.

## 위젯

위젯은 대시보드의 요소로, 데이터 보기(차트, 지표, 게이지 등) 또는 시스템과 상호작용(출력 조작, PWM 듀티 사이클 변경, 데이터베이스 쿼리 또는 수정 등)과 같은 다양한 용도로 사용됩니다. 위젯은 드래그 앤 드롭으로 쉽게 재배치 및 크기 조정이 가능합니다. 지원되는 위젯의 전체 목록은 [지원되는 위젯](Supported-Widgets.md)을 참조하십시오.

### 사용자 정의 위젯

AoT에는 사용자 정의 위젯을 AoT 시스템에서 사용할 수 있도록 하는 사용자 정의 위젯 가져오기 시스템이 있습니다. 사용자 정의 위젯은 `[기어 아이콘] -> 구성 -> 사용자 정의 위젯` 페이지에서 업로드할 수 있습니다. 가져온 후에는 `설정 -> 위젯` 페이지에서 사용할 수 있습니다.

작동하는 모듈을 개발한 경우, [새 GitHub 이슈 생성](https://github.com/aot-inc/AoT/issues/new?assignees=&labels=&template=feature-request.md&title=New%20Module) 또는 풀 리퀘스트를 고려해 보십시오. 그러면 기본 제공 세트에 포함될 수 있습니다.

적절한 형식의 예는 [AoT/aot/widgets](https://github.com/aot-inc/AoT/tree/master/aot/widgets/) 디렉토리에 있는 기본 제공 위젯 모듈을 열어 확인할 수 있습니다. 또한 [AoT/aot/widgets/examples](https://github.com/aot-inc/AoT/tree/master/aot/widgets/examples) 디렉토리에서 사용자 정의 위젯 예제를 확인할 수 있습니다.

사용자 정의 위젯 모듈을 생성하려면 특정 자바스크립트의 배치 및 실행이 필요할 수 있습니다. 이를 위해 각 모듈에서 몇 가지 변수가 생성되었으며, 여러 위젯이 표시되는 대시보드 페이지의 간략한 구조를 따릅니다.
```

```angular2html
<html>
<head>
  <title>Title</title>
  <script>
    {{ widget_1_dashboard_head }}
    {{ widget_2_dashboard_head }}
  </script>
</head>
<body>

<div id="widget_1">
  <div id="widget_1_titlebar">{{ widget_dashboard_title_bar }}</div>
  {{ widget_1_dashboard_body }}
  <script>
    $(document).ready(function() {
      {{ widget_1_dashboard_js_ready_end }}
    });
  </script>
</div>

<div id="widget_2">
  <div id="widget_2_titlebar">{{ widget_dashboard_title_bar }}</div>
  {{ widget_2_dashboard_body }}
  <script>
    $(document).ready(function() {
      {{ widget_2_dashboard_js_ready_end }}
    });
  </script>
</div>

<script>
  {{ widget_1_dashboard_js }}
  {{ widget_2_dashboard_js }}

  $(document).ready(function() {
    {{ widget_1_dashboard_js_ready }}
    {{ widget_2_dashboard_js_ready }}
  });
</script>

</body>
</html>
```
