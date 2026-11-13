// 지도 디자인의 위치 시트 서랍(aot-geo-location-sheet.js)을 가짜 DOM·jQuery·지도로 돌려
// 검색 버튼 → 서랍 → 시트 → 닫기 흐름과 '보이는 영역 중심'을 확인한다.
// 사용: node geo_design_location_sheet.js <aot-map-here.js> <aot-geo-location-sheet.js>  → 결과를 JSON 한 줄로 낸다.
const fs = require('fs');
global.window = global;

function node(tag) {
  let text = '';
  return { tag, children: [], hidden: false, disabled: false, value: '', className: '', listeners: {},
    get textContent() { return text; }, set textContent(v) { text = v; this.children = []; },
    addEventListener(t, f) { this.listeners[t] = f; }, appendChild(c) { this.children.push(c); return c; },
    setAttribute() {}, focus() { focused.push(this.sel || this.className); } };
}
const focused = [];
global.localStorage = { getItem: () => null, setItem() {} };
global.matchMedia = () => ({ matches: true });
global.getComputedStyle = () => ({ getPropertyValue: () => '' });
global.showToast = () => {};
const fetches = [];
global.fetch = (url, init) => {
  fetches.push([(init && init.method) || 'GET', url, init && init.body]);
  let body = { ok: true, address: '1 Main St' };
  if (url === '/api/geo/favorites') { body = { ok: true, favorites: [] }; }
  if (url === '/api/geo/search') { body = { ok: true, results: [{ name: 'Town Hall', address: 'Town Hall, 1 Rd', lat: '36.1', lng: '127.1' }] }; }
  return Promise.resolve({ json: () => Promise.resolve(body) });
};

// ── 가짜 서랍 ──
const sels = {};
const body = {
  innerHTML: '',
  querySelector(sel) { if (!sels[sel]) { sels[sel] = node('q'); sels[sel].sel = sel; } return sels[sel]; }
};
let shown = false, dialogRect = { left: 700, right: 1000, top: 0, bottom: 600 };
const drawer = {
  id: 'geo-location-drawer',
  classList: { contains: (c) => c === 'show' && shown },
  querySelector(sel) {
    if (sel === '.modal-body') { return body; }
    if (sel === '.modal-dialog') { return { getBoundingClientRect: () => dialogRect }; }
    return body.querySelector(sel);
  }
};
const btn = { listeners: {}, addEventListener(t, f) { this.listeners[t] = f; } };
const events = {};   // 'hide' / 'hidden' / 'shown' → [fn]
const modalCalls = [];
function $(el) {
  return {
    on(name, fn) { const k = name.split('.')[0]; (events[k] = events[k] || []).push(fn); return this; },
    one(name, fn) { const k = name.split('.')[0]; (events[k] = events[k] || []).push(function once(ev) { events[k] = events[k].filter((f) => f !== once); fn(ev); }); return this; },
    off(name) { if (name === '.aotLocSheet') { events.hide = []; events.hidden = []; } return this; },
    modal(cmd) {
      modalCalls.push(cmd);
      if (cmd === 'show') { shown = true; (events.shown || []).slice().forEach((f) => f({ target: drawer })); }
      if (cmd === 'hide') {
        (events.hide || []).slice().forEach((f) => f({ target: drawer }));
        shown = false;
        (events.hidden || []).slice().forEach((f) => f({ target: drawer }));
      }
    }
  };
}
global.jQuery = $;
global.document = {
  hidden: false, documentElement: {}, createElement: node,
  getElementById: (id) => (id === 'tool-search' ? btn : id === 'geo-location-drawer' ? drawer : null)
};

eval(fs.readFileSync(process.argv[2], 'utf8'));
eval(fs.readFileSync(process.argv[3], 'utf8'));

const flights = [];
global.innerWidth = 1000; global.innerHeight = 600;
let cTop = 0;
const container = { getBoundingClientRect: () => ({ left: 0, top: cTop, right: 1000, bottom: cTop + 600, width: 1000, height: 600 }) };
const map = {
  getContainer: () => container, getCenter: () => ({ lat: 36.5, lng: 127.5 }), getZoom: () => 15,
  unproject: (p) => ({ lng: p[0], lat: p[1] }),
  on() {}, once() {}, getStyle: () => ({}), getSource: () => null, addSource() {}, addLayer() {},
  getLayer: () => null, removeLayer() {}, removeSource() {}, getCanvas: () => ({ style: {} }),
  flyTo(o) { flights.push(o); }
};
const tick = () => new Promise((r) => setTimeout(r, 10));

(async () => {
  const out = {};
  // 1) 시트 기능 옵션 — 기본은 노트·머리글 포함, 끄면 빠진다
  let html = '';
  const dflt = AoTMapHere.attach(map, { uid: 'd', openPanel(h) { html = h; return { getElement: () => body, on() {}, remove() {} }; } });
  dflt.startSearch(); await tick();
  out.default_has_note = html.indexOf('aot-here-note') >= 0;
  out.default_has_header = html.indexOf('aot-sensor-popup-header') >= 0;
  dflt.clear();

  // 2) 부품이 없으면 붙지 않는다
  out.no_drawer = AoTGeoLocationSheet.init(map, { buttonId: 'x', drawerId: 'y' });

  // 3) 검색 버튼 → 서랍이 열리고 시트가 들어간다(노트·머리글 없음, 즐겨찾기 목록은 기존 길)
  const ctl = AoTGeoLocationSheet.init(map, { buttonId: 'tool-search', drawerId: 'geo-location-drawer', uid: 'geo-design' });
  out.attached = !!ctl;
  btn.listeners.click(); await tick();
  out.opened = shown;
  out.sheet_in_drawer = body.innerHTML.indexOf('aot-here-sheet') >= 0;
  out.note_off = body.innerHTML.indexOf('aot-here-note') < 0;
  out.header_off = body.innerHTML.indexOf('aot-sensor-popup-header') < 0 && body.innerHTML.indexOf('aot-modal-heading') < 0;
  out.keeps_favorites_and_star = body.innerHTML.indexOf('aot-here-favs') >= 0 && body.innerHTML.indexOf('aot-here-fav') >= 0;
  out.fav_call = fetches.filter((f) => f[1] === '/api/geo/favorites').map((f) => f[0]);
  out.focus_after_shown = focused.indexOf('.aot-here-q') >= 0;

  // 4) 검색 → 결과를 고르면 설계 지도가 flyTo 한다(서랍은 열린 채)
  sels['.aot-here-q'].value = 'town';
  sels['.aot-here-go'].listeners.click({ stopPropagation() {}, preventDefault() {} }); await tick();
  out.search_post = fetches.filter((f) => f[1] === '/api/geo/search').map((f) => JSON.parse(f[2]));
  sels['.aot-here-results'].children[0].children[0].listeners.click({ stopPropagation() {}, preventDefault() {} }); await tick();
  out.fly = flights.length ? { center: flights[0].center, zoom: flights[0].zoom } : null;
  out.snap = AoTMapHere.snapshot(['geo-design']);
  out.still_open = shown;

  // 5) 보이는 영역 중심 — 오른쪽 서랍은 뺀다, 아래 시트(폰)도 뺀다, 전부 덮으면 캔버스 중심
  out.center_right = AoTGeoLocationSheet.visibleCenter(map, drawer);
  dialogRect = { left: 0, right: 1000, top: 400, bottom: 600 };
  out.center_bottom = AoTGeoLocationSheet.visibleCenter(map, drawer);
  dialogRect = { left: 0, right: 1000, top: 0, bottom: 600 };
  out.center_cover = AoTGeoLocationSheet.visibleCenter(map, drawer);
  dialogRect = { left: 700, right: 1000, top: 0, bottom: 600 };
  shown = false;
  out.center_closed = AoTGeoLocationSheet.visibleCenter(map, drawer);
  shown = true;

  // 5-1) 폰에서 페이지를 스크롤해 지도 위쪽 절반이 화면 밖이면 화면에 보이는 아래쪽 절반의 중심
  cTop = -300;
  out.center_scrolled = AoTGeoLocationSheet.visibleCenter(map, drawer);
  cTop = 0;

  // 6) 버튼을 다시 누르면 닫히고, 닫히면 시트가 꺼진다(표식·AI 공유 해제)
  btn.listeners.click(); await tick();
  out.closed = !shown;
  out.snap_after_close = AoTMapHere.snapshot(['geo-design']);
  out.body_emptied = body.innerHTML === '';

  // 7) 다른 서랍이 열려 이 서랍이 닫혀도(×·한 번에 하나 규칙) 같다 — 다시 열면 새 시트
  btn.listeners.click(); await tick();
  out.reopened = shown && body.innerHTML.indexOf('aot-here-sheet') >= 0;
  (events.hide || []).slice().forEach((f) => f({ target: drawer }));   // 부트스트랩이 닫는 신호만
  out.snap_after_external_hide = AoTMapHere.snapshot(['geo-design']);
  console.log(JSON.stringify(out));
})();
