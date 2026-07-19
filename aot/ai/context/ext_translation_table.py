# coding=utf-8
"""
ext_translation_table.py — Static Korean-to-English mapping tables.

Implements NRM-04 (013_DATA_SOURCES.yaml):
    Korean-language API responses (EXT-KR-01, EXT-KR-02, EXT-KR-03)
    are translated at ingestion time via static mapping tables.
    Raw Korean text is never written to context module fields.

Phase 2a scope: crop names, growth stages, pest/disease names.
Phase 2b scope: LLM-based translation for free-text guidance fields.
"""

# ---------------------------------------------------------------------------
# @ANCHOR: CROP_NAME_MAP
# Source: EXT-KR-01 (SmartFarm), EXT-KR-02 (Nongsaro)
# Maps Korean crop name strings → internal English crop_id
# ---------------------------------------------------------------------------
CROP_NAME_MAP: dict[str, str] = {
    # Fruiting vegetables (과채류)
    "토마토":      "tomato",
    "방울토마토":  "cherry_tomato",
    "파프리카":    "paprika",
    "피망":        "bell_pepper",
    "오이":        "cucumber",
    "가지":        "eggplant",
    "호박":        "zucchini",
    "애호박":      "zucchini",
    "수박":        "watermelon",
    "멜론":        "melon",
    "딸기":        "strawberry",
    "고추":        "chili_pepper",
    "청고추":      "green_pepper",

    # Leafy vegetables (엽채류)
    "상추":        "lettuce",
    "양상추":      "romaine_lettuce",
    "시금치":      "spinach",
    "배추":        "napa_cabbage",
    "양배추":      "cabbage",
    "케일":        "kale",
    "청경채":      "bok_choy",
    "쑥갓":        "crown_daisy",
    "깻잎":        "perilla",

    # Root vegetables (근채류)
    "무":          "radish",
    "당근":        "carrot",
    "감자":        "potato",
    "고구마":      "sweet_potato",

    # Herbs & others
    "바질":        "basil",
    "파슬리":      "parsley",
    "로즈마리":    "rosemary",
    "민트":        "mint",
    "파":          "green_onion",
    "마늘":        "garlic",

    # Flowers & ornamentals (화훼류)
    "장미":        "rose",
    "국화":        "chrysanthemum",
    "카네이션":    "carnation",
    "거베라":      "gerbera",
    "난":          "orchid",
    "난초":        "orchid",
}

# ---------------------------------------------------------------------------
# @ANCHOR: GROWTH_STAGE_MAP
# Source: EXT-KR-01 (SmartFarm Productivity Model)
# Maps Korean growth stage strings → internal English stage_id
# ---------------------------------------------------------------------------
GROWTH_STAGE_MAP: dict[str, str] = {
    # Seedling / propagation
    "육묘기":      "seedling",
    "발아기":      "germination",
    "파종기":      "sowing",

    # Transplanting
    "정식기":      "transplanting",
    "이식기":      "transplanting",

    # Vegetative growth
    "생장기":      "vegetative",
    "영양생장기":  "vegetative",
    "초기생장":    "vegetative_early",
    "후기생장":    "vegetative_late",

    # Reproductive stages
    "개화기":      "flowering",
    "화아분화기":  "flower_initiation",
    "착과기":      "fruit_set",
    "비대기":      "fruit_development",
    "결실기":      "fruiting",

    # Harvest
    "수확기":      "harvest",
    "수확전기":    "pre_harvest",
    "수확후기":    "post_harvest",
}

# ---------------------------------------------------------------------------
# @ANCHOR: PEST_NAME_MAP
# Source: EXT-KR-03 (National Pest Management System)
# Maps Korean pest/disease name strings → internal English pest_id
# ---------------------------------------------------------------------------
PEST_NAME_MAP: dict[str, str] = {
    # Fungal diseases (곰팡이병)
    "흰가루병":         "powdery_mildew",
    "잿빛곰팡이병":     "gray_mold",
    "노균병":           "downy_mildew",
    "역병":             "late_blight",
    "탄저병":           "anthracnose",
    "시들음병":         "fusarium_wilt",
    "균핵병":           "sclerotinia_rot",
    "잎마름병":         "leaf_blight",
    "점무늬병":         "leaf_spot",
    "검은무늬병":       "black_spot",

    # Bacterial diseases (세균병)
    "세균성점무늬병":   "bacterial_leaf_spot",
    "풋마름병":         "bacterial_wilt",
    "무름병":           "soft_rot",

    # Viral diseases (바이러스병)
    "토마토황화잎말림바이러스": "tomato_yellow_leaf_curl_virus",
    "오이모자이크바이러스":     "cucumber_mosaic_virus",
    "고추모자이크바이러스":     "pepper_mosaic_virus",

    # Insects / mites (해충)
    "진딧물":           "aphid",
    "온실가루이":       "whitefly",
    "응애":             "spider_mite",
    "점박이응애":       "two_spotted_spider_mite",
    "총채벌레":         "thrips",
    "잎굴파리":         "leafminer",
    "담배거세미나방":   "tobacco_armyworm",
    "파밤나방":         "beet_armyworm",
    "뿌리혹선충":       "root_knot_nematode",
    "온실총채벌레":     "western_flower_thrips",
    "목화진딧물":       "cotton_aphid",
    "복숭아혹진딧물":   "green_peach_aphid",
}

# ---------------------------------------------------------------------------
# @ANCHOR: SEVERITY_MAP
# Source: EXT-KR-03, EXT-GL-02
# Maps Korean severity strings → internal English severity levels
# ---------------------------------------------------------------------------
SEVERITY_MAP: dict[str, str] = {
    "심각":   "critical",
    "위험":   "critical",
    "경보":   "warning",
    "경고":   "warning",
    "주의":   "info",
    "관찰":   "info",
    "정상":   "normal",
}

# ---------------------------------------------------------------------------
# @ANCHOR: TRANSLATE_KR
# Public helper — used by Phase 2a external data clients at ingestion time.
# ---------------------------------------------------------------------------
_TABLE_REGISTRY: dict[str, dict[str, str]] = {
    "crop":         CROP_NAME_MAP,
    "growth_stage": GROWTH_STAGE_MAP,
    "pest":         PEST_NAME_MAP,
    "severity":     SEVERITY_MAP,
}


def translate_kr(text: str, domain: str) -> str:
    """
    Translate a Korean API response value to its internal English ID.

    Args:
        text   : Korean string from API response (e.g. "토마토", "개화기")
        domain : Translation domain — 'crop' | 'growth_stage' | 'pest' | 'severity'

    Returns:
        English internal ID if found, else the original text unchanged.
        The original text is returned (not None) so callers can log unmapped values.
    """
    table = _TABLE_REGISTRY.get(domain, {})
    return table.get(text.strip(), text)
