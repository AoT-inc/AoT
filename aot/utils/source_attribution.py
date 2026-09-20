# coding=utf-8
"""
source_attribution.py — 출처 표시 의무를 조회 응답에 싣는다.

## 왜 별도 모듈인가

라이브러리가 붙인 공개 자료 상당수가 **CC BY** 다(FAO ECOCROP, Open-Meteo,
그 아래 기상청들). CC BY 는 "자료를 표시하는 자리 옆에" 출처를 밝히라고
요구한다 — Open-Meteo 는 문구까지 지정한다("Weather data by Open-Meteo.com"
+ 링크).

AoT 에서 그 자료가 **실제로 표시되는 자리**는 두 곳이다:

  1. AI 의 답변 — 사용자가 값을 보는 곳이 여기다.
  2. 라이브러리 화면의 소스 카드.

②는 화면이 그리면 되지만 ①은 그럴 수 없다. 답변을 쓰는 것은 모델이고,
모델은 **조회 응답에 실린 것만** 안다. 그래서 출처 문구를 응답에 싣는다.

그런데 문구만 실으면 부족하다 — 참조표 경로는 이미 `attribution` 을 싣고
있었지만 "이걸 답변에 적으라" 고는 말하지 않았고, 그러면 모델은 그것을 그냥
메타데이터로 읽는다. 의무를 **말해야** 지켜진다. 두 조회 경로(참조표·API)가
같은 문구로 같은 의무를 싣도록 여기 한 곳에 둔다.

## 왜 preset 기본값을 두는가

운영자가 출처 문구를 직접 타이핑해야 한다면 대부분 비워 둘 것이고, 그러면
라이선스를 어긴 채로 돌아간다. 내장 프리셋은 어느 자료인지 우리가 아니까
기본값을 채워 준다. 운영자가 고칠 수 있다(설정 모달의 Attribution 칸).
"""

# 프리셋별 기본 출처 표기. **문구를 임의로 줄이지 말 것** — Open-Meteo 는
# licence 페이지에서 이 문장과 링크를 명시적으로 요구한다.
PRESET_ATTRIBUTION = {
    'ext_openmeteo': {
        'attribution': 'Weather data by Open-Meteo.com (CC BY 4.0)',
        'source_url': 'https://open-meteo.com/',
    },
}

# 응답에 함께 싣는 한 줄. 이것이 없으면 모델은 attribution 을 그냥
# 메타데이터로 읽고 답변에 옮기지 않는다.
ATTRIBUTION_NOTE = ("Licence requires this credit wherever these values appear — "
                    "include it in your answer.")


def defaults_for(preset_key):
    """프리셋의 기본 출처 표기(없으면 빈 dict)."""
    return dict(PRESET_ATTRIBUTION.get(preset_key) or {})


def apply(payload, config, preset_key=None):
    """조회 응답에 출처 표기와 그 의무를 싣는다.

    운영자가 소스에 적은 값이 이긴다 — 프리셋 기본값은 비어 있을 때만 쓴다.
    `caveat` 은 라이선스가 아니라 자료 해석 주의사항이지만, 같은 자리에서
    같은 방식으로 실리므로 함께 다룬다.

    표기가 하나도 없으면 아무것도 더하지 않는다 — 빈 필드를 실으면 응답만
    커지고 모델은 "출처 없음" 을 출처로 읽는다.
    """
    config = config or {}
    fallback = defaults_for(preset_key)

    for key in ('attribution', 'source_url', 'caveat'):
        value = (config.get(key) or '').strip() or (fallback.get(key) or '').strip()
        if value:
            payload[key] = value

    if payload.get('attribution'):
        payload['attribution_note'] = ATTRIBUTION_NOTE
    return payload
