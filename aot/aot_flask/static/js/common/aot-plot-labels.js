/* 구획의 "대상"·"품종" 라벨 — **대상 종류(kind)에 따라 달라진다.**
 *
 * 한 벌만 둔다. 이 두 칸은 다섯 화면에 나온다(geo/design · 지도 위젯 모달의
 * 표시와 편집 · 시설 편집기 · 설정 > 프로그램). 화면마다 라벨을 적으면 종류를
 * 하나 늘릴 때 한쪽만 늘어난다 — 이 저장소가 반복해서 겪은 실패다.
 *
 * ## 왜 종류마다 다른가
 *
 * "품종" 은 생물에만 맞는 말이다. 도로·철길·시설물을 관리하는 화면이 품종을
 * 물으면 그 화면은 그냥 틀린 말을 한다. 반대로 전부 중립어("세부 구분")로
 * 통일하면 농가에게는 관공서 말투가 된다.
 *
 * "대상" 도 약하다 — 무엇을 적는 칸인지 말하지 않아, 구획 이름과 헷갈린다.
 *
 *   종류        대상 라벨    품종 라벨    쉬는 기간의 기본 이름
 *   식생        품목         품종         휴경
 *   가축        품목         품종         비움
 *   시설        시설물       규격         미사용
 *   기타        대상         세부 구분    쉬는 중
 *
 * **"휴경" 은 중립어가 아니다** — 경작(耕)을 전제한 말이라 축사·시설에는 그냥
 * 틀리다. 반대로 넷을 "쉬는 중" 으로 통일하면 농가 화면이 관공서 말투가 된다.
 * 이 표가 있는 이유가 그것이다.
 *
 * ## msgid 는 뜻이 겹치지 않는 것으로 고른다
 *
 * `Structure`(구조) · `Type`(유형) · `Model`(모델) 은 이미 다른 뜻으로 번역돼
 * 있다. 그것을 빌려 쓰면 화면에 엉뚱한 한국어가 뜨는데 영어로는 맞아 보여
 * 리뷰에서 안 보인다(`Period`="주기" · `Stage`="단" 과 같은 계열).
 */
(function (root) {
  'use strict';

  var SUBJECT = {
    vegetation: 'Item',
    livestock: 'Item',
    facility: 'Structure item',
    other: 'What is here'
  };
  var VARIETY = {
    vegetation: 'Variety',
    livestock: 'Variety',
    facility: 'Spec',
    other: 'Subtype'
  };
  // 작기를 끝내고 그 자리를 쉬게 할 때의 **기본 이름**. 고쳐 쓸 수 있는 값이라
  // 데이터에 박히는 것은 사람이 확인한 뒤다.
  var RESTING = {
    vegetation: 'Fallow',
    livestock: 'Empty period',
    // `Not in use` 를 쓰지 않는다 — 이미 "사용 중이 아님" 으로 번역돼 있어
    // 구획 이름 자리에 문장이 들어간다(파일 머리 "msgid 는 뜻이 겹치지 않는
    // 것으로" 참조).
    facility: 'Vacant',
    other: 'Resting'
  };

  function _t(key) {
    var fn = root._;
    return (typeof fn === 'function') ? fn(key) : key;
  }

  root.AoTPlotLabels = {
    /** 대상 칸의 라벨. 모르는 종류는 중립어로 떨어진다. */
    subject: function (kind) {
      return _t(SUBJECT[kind] || SUBJECT.other);
    },
    /** 품종 칸의 라벨. */
    variety: function (kind) {
      return _t(VARIETY[kind] || VARIETY.other);
    },
    /** 쉬는 기간의 기본 이름. */
    resting: function (kind) {
      return _t(RESTING[kind] || RESTING.other);
    },
    SUBJECT_KEYS: SUBJECT,
    VARIETY_KEYS: VARIETY,
    RESTING_KEYS: RESTING
  };
})(typeof window !== 'undefined' ? window : this);
