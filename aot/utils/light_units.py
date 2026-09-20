# coding=utf-8
"""빛 측정 단위 → PPFD 환산. 순수 단위 환산이라 geo·journal 어디에도 속하지
않는다 — `plot_context.dli_accumulated` 와 `plot_journal` 의 일지 집계가
**같은 표**를 봐야 하므로 둘 다 내려다보는 여기에 둔다.
"""

#: 단위 → `(PPFD 환산계수, 가정이 들어갔는가)`.
#:
#: DLI(mol/m²/일)는 PPFD(µmol/m²/s)를 하루 동안 적분한 값이다. 센서가 무엇을
#: 내느냐에 따라 환산이 **완전히 다르다**:
#:
#: - `umol_m2_s` — 이미 PPFD 다. **곱하면 안 된다.** 여기에 W/m² 계수를 곱하면
#:   값이 두 배가 되는데, 숫자가 그럴듯해서 틀린 줄 모른다.
#: - `W_m2` — 전천일사(단파 전체). PAR 은 그 45% 가량이고 PAR 1 W/m² ≈
#:   4.57 µmol/m²/s 이므로 ≈ ×2.06. **가정이 둘 들어간 값이다**(PAR 비율·광원이
#:   태양광이라는 것) — 그래서 화면이 "추정" 이라고 말해야 한다.
#: - `lux`/`klux` — 사람 눈 기준 밝기라 스펙트럼에 크게 좌우된다. 태양광 기준
#:   대략 ×0.0185 인데 LED 보광 아래서는 크게 틀린다. 쓰되 추정으로 표시한다.
#:
#: ⚠ 모르는 단위는 **환산하지 않는다.** 그럴듯한 계수를 지어내면 DLI 가 나오고,
#:   나오는 순간 사람은 그것을 믿는다.
LIGHT_UNITS_TO_PPFD = {
    'umol_m2_s': (1.0, False),
    'W_m2': (2.06, True),
    'lux': (0.0185, True),
    'klux': (18.5, True),
}


def ppfd_factor(unit):
    """빛 단위 → `(계수, 추정인가)`. 모르면 `(None, None)`."""
    found = LIGHT_UNITS_TO_PPFD.get(str(unit or ''))
    return found if found else (None, None)
