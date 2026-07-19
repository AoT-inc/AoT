# 브라우저 캐시 완전 삭제 가이드

## 문제 상황
- 데이터베이스에 7개의 Input이 정상적으로 저장되어 있음 ✅
- 서버 코드가 7개의 Input을 정상적으로 필터링함 ✅
- 하지만 브라우저에서 Input이 표시되지 않음 ❌

## 원인
브라우저가 오래된 템플릿 파일을 캐시하고 있습니다.

## 해결 방법

### 1단계: 서버 재시작 (필수!)
```bash
# 서버를 완전히 종료하고 재시작
# Ctrl+C로 종료 후 다시 시작
```

서버를 재시작해야 다음 설정이 적용됩니다:
- `app.config['TEMPLATES_AUTO_RELOAD'] = True`
- `app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0`

### 2단계: 브라우저 캐시 완전 삭제

#### Chrome/Edge (Mac)
1. **Cmd + Shift + Delete** 누르기
2. "기간" → "전체 기간" 선택
3. "캐시된 이미지 및 파일" 체크
4. "인터넷 사용 기록" 체크 (선택사항)
5. "데이터 삭제" 클릭

#### Safari (Mac)
1. **Cmd + Option + E** 누르기 (캐시 비우기)
2. 또는 Safari → 환경설정 → 고급 → "메뉴 막대에서 개발자용 메뉴 보기" 체크
3. 개발자용 → 캐시 비우기

#### Firefox (Mac)
1. **Cmd + Shift + Delete** 누르기
2. "시간 범위" → "전체" 선택
3. "캐시" 체크
4. "지금 지우기" 클릭

### 3단계: 페이지 강제 새로고침
- **Mac**: **Cmd + Shift + R**
- **Windows**: **Ctrl + Shift + R**

이 방법은 일반 새로고침(F5)과 달리 캐시를 무시하고 서버에서 새로운 파일을 가져옵니다.

### 4단계: 페이지 소스 확인
1. 페이지에서 우클릭 → "페이지 소스 보기"
2. `<div class="grid-stack aot-entry-container">` 검색
3. 그 안에 7개의 `<div class="grid-stack-item">` 요소가 있어야 함

**예상되는 HTML:**
```html
<div class="grid-stack aot-entry-container">
  <div id="gridstack_input_7b8fadd5-2a0d-4525-8642-0383e85ed755" class="grid-stack-item" ...>
    ...
  </div>
  <div id="gridstack_input_3620c895-7efe-41a6-b68a-543ee54a71fe" class="grid-stack-item" ...>
    ...
  </div>
  <!-- ... 총 7개 ... -->
</div>
```

**만약 비어있다면:**
```html
<div class="grid-stack aot-entry-container">
  <!-- 아무것도 없음 -->
</div>
```
→ 여전히 오래된 템플릿이 캐시되어 있는 것입니다.

### 5단계: 추가 조치 (문제가 계속되면)

#### A. 시크릿/프라이빗 모드로 테스트
- Chrome: **Cmd + Shift + N**
- Safari: **Cmd + Shift + N**
- Firefox: **Cmd + Shift + P**

시크릿 모드는 캐시를 사용하지 않으므로, 여기서 Input이 표시되면 캐시 문제가 확실합니다.

#### B. 다른 브라우저로 테스트
- Chrome에서 안 되면 Safari나 Firefox로 테스트
- 다른 브라우저에서 되면 원래 브라우저의 캐시 문제

#### C. 브라우저 개발자 도구 사용
1. **F12** 또는 **Cmd + Option + I** (개발자 도구 열기)
2. **Network** 탭 선택
3. "Disable cache" 체크박스 활성화
4. 페이지 새로고침

#### D. 서버 로그 확인
서버 터미널에서 다음 로그를 확인:
```
[DEBUG] Current tab: Input (ID: 7d653b43-aa9a-4634-9786-6f641fe3b125)
[DEBUG] Filtered input_dev count: 7
[DEBUG]   - Input: OpenWeather (ID: 7b8fadd5-2a0d-4525-8642-0383e85ed755)
[DEBUG]   - Input: OpenWeather (ID: 3620c895-7efe-41a6-b68a-543ee54a71fe)
...
```

이 로그가 보이면 서버는 정상적으로 작동하고 있는 것입니다.

### 6단계: 최종 확인
Input 페이지에서:
1. 7개의 OpenWeather Input이 모두 표시되어야 함
2. 각 Input에 설정 버튼이 있어야 함
3. 새로운 Input을 추가하고 새로고침해도 사라지지 않아야 함

## 문제가 계속되면

다음 정보를 제공해주세요:
1. 서버를 재시작했는지 여부
2. 브라우저 캐시를 삭제했는지 여부
3. 페이지 소스에서 `<div class="grid-stack aot-entry-container">` 안의 내용
4. 서버 로그에 "[DEBUG]" 메시지가 있는지 여부
5. 시크릿 모드에서 테스트한 결과

## 요약
✅ 데이터베이스: 정상 (7개 Input 저장됨)
✅ 서버 코드: 정상 (7개 Input 필터링됨)
✅ 템플릿 파일: 정상 (올바른 변수 사용)
❌ 브라우저: 오래된 캐시 사용 중

**해결책: 서버 재시작 + 브라우저 캐시 완전 삭제 + 강제 새로고침**
