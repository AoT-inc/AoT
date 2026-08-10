// 노트 위젯 문구 번역.
//
// **자체 사전을 만들지 않는다.** 앱 전역 카탈로그(window.AOT_I18N — layout 이
// /api/v1/locale/js 로 싣는다)를 그대로 쓴다. 이 위젯만 사전을 따로 들면 같은
// 문장이 두 벌이 되고, 언어를 하나 늘릴 때 여기만 조용히 빠진다. 실제로 이
// 드로어는 통합 전까지 문구가 전부 영어 하드코딩이라, 바깥 화면이 전부
// 한국어인데 노트를 열면 갑자기 영어가 나왔다.
//
// msgid 는 다른 화면과 같은 규칙 — 영어 원문. 새 문구를 넣으면 babel 추출
// 대상이 아니므로(.jsx 는 추출 설정에 없다) ko/ja .po 에 직접 넣어야 한다.

export function t(key) {
  const fn = typeof window !== 'undefined' && window._
  if (typeof fn === 'function') {
    const out = fn(key)
    if (out) return out
  }
  return key
}

// 자리표시자가 있는 문구: t('{n} 개') 꼴. 카탈로그 문자열에도 같은 {이름} 을 남긴다.
export function tf(key, vars) {
  let out = t(key)
  Object.keys(vars || {}).forEach((k) => {
    out = out.split('{' + k + '}').join(String(vars[k]))
  })
  return out
}

// 화면 언어 코드 — <html lang> 이 정본이고, 없으면 브라우저 설정.
export function uiLocale() {
  if (typeof document !== 'undefined') {
    const lang = document.documentElement && document.documentElement.lang
    if (lang) return lang
  }
  if (typeof navigator !== 'undefined' && navigator.language) return navigator.language
  return 'en'
}

// "3시간 전" 같은 상대 시각.
//
// date-fns 의 formatDistanceToNow 를 쓰던 자리다. 그쪽은 언어마다 locale 객체를
// import 해야 해서, 언어를 늘릴 때마다 번들에 사전을 하나씩 더 넣어야 한다.
// Intl.RelativeTimeFormat 은 브라우저가 이미 들고 있는 것이라 번들이 늘지 않고
// 앱이 지원하는 20여 개 언어가 배선 없이 함께 따라온다.
const _UNITS = [
  ['year',   365 * 24 * 60 * 60 * 1000],
  ['month',   30 * 24 * 60 * 60 * 1000],
  ['day',          24 * 60 * 60 * 1000],
  ['hour',              60 * 60 * 1000],
  ['minute',                 60 * 1000],
]

export function relativeTime(date) {
  const ms = date.getTime() - Date.now()
  const abs = Math.abs(ms)
  try {
    const rtf = new Intl.RelativeTimeFormat(uiLocale(), { numeric: 'auto' })
    for (let i = 0; i < _UNITS.length; i++) {
      const [unit, size] = _UNITS[i]
      if (abs >= size) return rtf.format(Math.round(ms / size), unit)
    }
    return rtf.format(Math.round(ms / 1000), 'second')
  } catch (e) {
    // Intl 이 없거나 lang 이 이상한 값일 때 — 날짜라도 보여준다.
    return date.toLocaleString()
  }
}

// 노트가 매달린 대상의 종류를 사람이 읽을 말로. targetType 은 호출부(지도 위젯·
// 설정 페이지)가 넘기는 내부 식별자라 그대로 띄우면 'GeoShape' 같은 것이 뜬다.
const _TARGET_LABELS = {
  GeoShape:    'Zone',
  GeoFacility: 'Facility',
  site:        'Site',
  zone:        'Zone',
  facility:    'Facility',
  device:      'Device',
  aot_device:  'Device',
  input:       'Input',
  output:      'Output',
  function:    'Function',
  pid:         'PID',
  map_location: 'Location',
}

export function targetTypeLabel(type) {
  const msgid = _TARGET_LABELS[type]
  return msgid ? t(msgid) : String(type || '')
}
