Action은 컨트롤러(즉 Input, Conditional, Trigger 컨트롤러)에 추가하여 부가 기능을 제공하거나 AoT의 다른 부분과 상호작용하는 방법을 제공합니다. Action은 설계 방식에 따라 하나 이상의 컨트롤러 유형에서 동작할 수 있습니다.

지원되는 Action의 전체 목록은 [Supported Actions](Supported-Actions.md)를 참고하세요.

## Custom Actions

AoT에는 사용자가 직접 만든 Action을 AoT 시스템에서 사용할 수 있게 해주는 Custom Action 가져오기 시스템이 있습니다. Custom Action은 `[Gear Icon] -> Configure -> Custom Actions` 페이지에서 업로드할 수 있습니다. 가져오기 후에는 `Setup -> Function` 페이지에서 사용할 수 있습니다.

동작하는 Action 모듈을 개발하셨다면 [새 GitHub 이슈 생성](https://github.com/AoT-inc/AoT/issues/new?assignees=&labels=&template=feature-request.md&title=New%20Module)이나 풀 리퀘스트를 고려해 주세요. 내장 세트에 포함될 수 있습니다.

올바른 형식의 예시는 [AoT/aot/actions](https://github.com/AoT-inc/AoT/tree/main/aot/actions/) 디렉터리에 있는 내장 모듈 중 아무것이나 열어 확인하세요.

또한 [AoT/aot/actions/examples](https://github.com/AoT-inc/AoT/tree/main/aot/actions/examples) 디렉터리에도 예시 Custom Action이 있습니다.

추가로, 내장 세트에 포함되지 않은 Custom Module을 위한 별도의 github 저장소를 [aot-inc/AoT-custom](https://github.com/AoT-inc/AoT-custom)에 두고 있습니다.
