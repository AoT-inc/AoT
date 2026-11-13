// 대지 가져오기 서랍의 '주소 줄 → 위치 시트(pick 모드)' 흐름(aot-geo-parcel-pick.js + aot-map-here.js)을
// 가짜 DOM·jQuery·지도로 돌린다. 시트가 서랍 안 카드로 열리는지, 담기·노트가 꺼지는지, onPick 에 좌표·주소가 실리는지,
// 줄에 주소가 채워지는지(쉼표 포함 주소는 한 주소로 표시), 서랍이 닫히면 시트가 접히는지 확인한다.
// 사용: node geo_design_parcel_pick.js <aot-map-here.js> <aot-geo-location-sheet.js> <aot-geo-parcel-pick.js> → JSON 한 줄.
const fs = require('fs');
global.window = global;

function classList(owner) {
  return { add(c) { const s = new Set((owner.className || '').split(/\s+/).filter(Boolean)); s.add(c); owner.className = [...s].join(' '); },
    remove(c) { owner.className = (owner.className || '').split(/\s+/).filter((x) => x && x !== c).join(' '); },
    contains(c) { return (owner.className || '').split(/\s+/).includes(c); } };
}
function node(tag) {
  let text = '';
  const n = { tag, children: [], hidden: false, disabled: false, value: '', className: '', listeners: {}, attrs: {},
    get textContent() { return text; }, set textContent(v) { text = v; this.children = []; },
    addEventListener(t, f) { this.listeners[t] = f; }, appendChild(c) { this.children.push(c); return c; },
    setAttribute(k, v) { this.attrs[k] = v; }, getAttribute(k) { return this.attrs[k]; },
    removeAttribute(k) { delete this.attrs[k]; }, hasAttribute(k) { return k in this.attrs; },
    focus() {} };
  n.classList = classList(n);
  return n;
}
global.localStorage = { getItem: () => null, setItem() {} };
global.matchMedia = () => ({ matches: false });          // 손가락 화면 — 키보드가 뜨지 않게 초점을 주지 않는다
global.getComputedStyle = () => ({ getPropertyValue: () => '' });
global.showToast = () => {};
const fetches = [];
global.fetch = (url, init) => {
  fetches.push([(init && init.method) || 'GET', url, init && init.body]);
  let body = { ok: true, address: '서울특별시 강남구 역삼동 808', type: 'parcel', provider: 'gis_vworld' };
  if (url === '/api/geo/favorites') { body = { ok: true, favorites: [{ id: 'f1', name: 'Barn', address: 'Barn Rd', lat: 36.2, lng: 127.2, mine: true, shared: false }] }; }
  if (url === '/api/geo/search') { body = { ok: true, results: [{ name: 'Town Hall', address: '1, Main St, Springfield', lat: '36.1', lng: '127.1' }] }; }
  if (String(url).indexOf('/api/geo/around') === 0) { body = { ok: false }; }
  return Promise.resolve({ json: () => Promise.resolve(body) });
};

// ── 가짜 서랍·카드·주소 줄 ──
const sels = {};
const body = {
  innerHTML: '',
  querySelector(sel) { if (!sels[sel]) { sels[sel] = node('q'); sels[sel].sel = sel; } return sels[sel]; }
};
const host = { hidden: true, scrolled: 0, scrollIntoView() { this.scrolled++; },
  querySelector(sel) { return sel === '.aot-parcel-pick-body' ? body : null; },
  querySelectorAll() { return []; } };
function makeRow() {
  const input = node('input'), pin = node('button'), row = node('div');
  row.className = 'parcel-addr-row aot-parcel-addr-row';
  pin.className = 'btn-parcel-addr-pick';
  row.querySelector = (sel) => (sel === '.parcel-addr-input' ? input : sel === '.btn-parcel-addr-pick' ? pin : null);
  row.input = input; row.pin = pin;
  return row;
}
const row1 = makeRow(), row2 = makeRow();
const drawerListeners = {};
let drawerShown = true;
const drawer = {
  id: 'modal-parcel-import',
  classList: { contains: (c) => c === 'show' && drawerShown },
  addEventListener(t, f) { drawerListeners[t] = f; },
  querySelector(sel) { return sel === '.modal-dialog' ? { getBoundingClientRect: () => ({ left: 700, right: 1000, top: 0, bottom: 600 }) } : null; },
  querySelectorAll(sel) { return sel.indexOf('btn-parcel-addr-pick.is-on') >= 0 ? [row1.pin, row2.pin].filter((b) => b.classList.contains('is-on')) : []; }
};
const events = {};
global.jQuery = function () {
  return { on(name, fn) { const k = name.split('.')[0]; (events[k] = events[k] || []).push(fn); return this; } };
};
global.document = {
  hidden: false, documentElement: {}, createElement: node,
  getElementById: (id) => (id === 'modal-parcel-import' ? drawer : id === 'parcel-pick-sheet' ? host : null)
};

eval(fs.readFileSync(process.argv[2], 'utf8'));
eval(fs.readFileSync(process.argv[3], 'utf8'));
eval(fs.readFileSync(process.argv[4], 'utf8'));

global.innerWidth = 1000; global.innerHeight = 600;
const container = { getBoundingClientRect: () => ({ left: 0, top: 0, right: 1000, bottom: 600, width: 1000, height: 600 }) };
const flights = [], sources = {}, layers = {};
const map = {
  getContainer: () => container, getCenter: () => ({ lat: 36.5, lng: 127.5 }), getZoom: () => 15,
  unproject: (p) => ({ lng: p[0], lat: p[1] }),
  // 지도 디자인의 지도는 호환 래퍼 — 원본(source)을 지우는 removeSource 가 없다. 원본이 남아도 표식이 다시 그려져야 한다.
  on() {}, once() {}, getStyle: () => ({}),
  getSource: (id) => (sources[id] ? { setData() {} } : null), addSource(id) { sources[id] = true; },
  addLayer(l) { layers[l.id] = true; }, getLayer: (id) => (layers[id] ? {} : null), removeLayer(id) { delete layers[id]; },
  getCanvas: () => ({ style: {} }),
  flyTo(o) { flights.push(o); }
};
const tick = () => new Promise((r) => setTimeout(r, 10));
const click = (sel) => sels[sel].listeners.click({ stopPropagation() {}, preventDefault() {} });

const throwaway = () => ({ innerHTML: '', querySelector: () => node('q') });
(async () => {
  const out = {};
  // 0) 기본(위젯) 시트는 그대로 — 담기·노트가 있고 '이 주소 사용'은 없다
  let html = '';
  const dflt = AoTMapHere.attach(map, { uid: 'd', openPanel(h) { html = h; return { getElement: () => throwaway(), on() {}, remove() {} }; } });
  dflt.startSearch(); await tick();
  out.default_has_note = html.indexOf('aot-here-note') >= 0;
  out.default_has_fav = /aot-here-fav["\s]/.test(html);
  out.default_has_use = html.indexOf('aot-here-use') >= 0;
  dflt.clear();
  // 0-1) mode:'pick' 이라도 onPick 이 없으면 기본 시트다(조용히 빠지지 않게)
  const bare = AoTMapHere.attach(map, { uid: 'b', mode: 'pick', openPanel(h) { html = h; return { getElement: () => throwaway(), on() {}, remove() {} }; } });
  bare.startSearch(); await tick();
  out.bare_pick_is_default = html.indexOf('aot-here-note') >= 0 && html.indexOf('aot-here-use') < 0;
  bare.clear();

  // 1) 부품이 없으면 붙지 않는다
  out.no_host = AoTGeoParcelPick.init({ drawerId: 'x', sheetId: 'y', getMap: () => map });
  const filled = [];
  const pick = AoTGeoParcelPick.init({ drawerId: 'modal-parcel-import', sheetId: 'parcel-pick-sheet', uid: 'geo-design-parcel',
    getMap: () => map, onFill: (input, r) => filled.push({ value: input.value, r }) });
  out.attached = !!pick;
  out.no_map_no_open = (() => {
    const p = AoTGeoParcelPick.init({ drawerId: 'modal-parcel-import', sheetId: 'parcel-pick-sheet', getMap: () => null });
    p.toggle(row1); return host.hidden && !row1.classList.contains('is-picking');
  })();

  // 2) 줄의 [위치] → 시트가 서랍 안 카드로 열린다(노트·담기·머리글 없음, '이 주소 사용'이 있다), 그 줄이 표시된다
  pick.toggle(row1); await tick();
  out.opened_inline = host.hidden === false && body.innerHTML.indexOf('aot-here-sheet') >= 0;
  out.no_note = body.innerHTML.indexOf('aot-here-note') < 0;
  out.no_fav_add = !/aot-here-fav["\s]/.test(body.innerHTML);
  out.no_header = body.innerHTML.indexOf('aot-sensor-popup-header') < 0 && body.innerHTML.indexOf('aot-modal-heading') < 0;
  out.has_use = body.innerHTML.indexOf('aot-here-use') >= 0;
  out.keeps_pick_routes = ['aot-here-q', 'aot-here-gps', 'aot-here-center', 'aot-here-pick', 'aot-here-favs'].every((c) => body.innerHTML.indexOf(c) >= 0);
  out.row1_marked = row1.classList.contains('is-picking') && row1.pin.classList.contains('is-on') && row1.pin.getAttribute('aria-pressed') === 'true';
  out.scrolled_into_view = host.scrolled === 1;
  // 즐겨찾기 줄은 고르기만 — 편집 버튼 없음(줄 = 이름 하나)
  const favBox = sels['.aot-here-favs'];
  out.fav_rows = favBox.children.length;
  out.fav_row_has_edit = favBox.children[0].children[0].children.length > 1;

  // 3) 지도 중심 → 주소를 찾는 동안은 쓸 수 없고, 찾으면 쓸 수 있다
  click('.aot-here-center');
  out.use_disabled_while_looking = sels['.aot-here-use'].disabled === true;
  await tick();
  out.use_enabled_after_address = sels['.aot-here-use'].disabled === false;
  out.marker_layers = Object.keys(layers).length;
  out.address_get = fetches.filter((f) => f[1].indexOf('/api/geo/address') === 0).map((f) => f[0]);

  // 4) '이 주소 사용' → 줄에 주소가 채워지고 시트는 접힌다. onPick 에 좌표·주소가 실린다. 줄은 '고른 주소'로 표시된다
  click('.aot-here-use');
  out.filled = filled.length === 1 ? filled[0] : null;
  out.row1_value = row1.input.value;
  out.row1_picked = row1.input.hasAttribute('data-picked');
  out.sheet_closed = host.hidden === true;
  out.marker_cleared = Object.keys(layers).length === 0;
  out.row_unmarked = !row1.classList.contains('is-picking') && !row1.pin.classList.contains('is-on');

  // 5) 사람이 줄을 고치면 '고른 주소 그대로'가 아니다
  drawerListeners.input({ target: Object.assign(row1.input, { classList: { contains: (c) => c === 'parcel-addr-input' } }) });
  out.picked_cleared_on_edit = !row1.input.hasAttribute('data-picked');

  // 6) 검색 결과로 고르면 제공자가 준 주소(쉼표 포함)가 그대로 돌아온다. 다른 줄로 옮겨 갈 때 시트는 그대로다
  pick.toggle(row1); await tick();
  click('.aot-here-center');
  out.marker_layers_again = Object.keys(layers).length;     // 원본이 남은 채 다시 열어도 표식이 다시 얹힌다
  const opens = body.innerHTML;
  sels['.aot-here-q'].value = 'town';
  click('.aot-here-go'); await tick();
  out.search_post = fetches.filter((f) => f[1] === '/api/geo/search').map((f) => JSON.parse(f[2]));
  out.search_row_has_star = sels['.aot-here-results'].children[0].children.length > 1;
  sels['.aot-here-results'].children[0].children[0].listeners.click({ stopPropagation() {}, preventDefault() {} }); await tick();
  out.fly = flights.length ? { center: flights[0].center, zoom: flights[0].zoom } : null;
  pick.toggle(row2);                                                      // 줄 옮기기 — 시트 상태 유지, 표시만 이동
  out.retarget = !row1.classList.contains('is-picking') && row2.classList.contains('is-picking') && body.innerHTML === opens && pick.target() === row2;
  click('.aot-here-use');
  out.search_fill = { r1: row1.input.value, r2: row2.input.value, picked: row2.input.hasAttribute('data-picked') };
  out.search_payload = filled[1] && filled[1].r;

  // 7) 같은 줄의 [위치] 를 다시 누르면 접힌다. 서랍이 닫히면(×·다른 서랍) 시트가 접히고 주소 줄은 그대로다
  pick.toggle(row2); pick.toggle(row2);
  out.toggle_closes = host.hidden === true && pick.target() === null;
  pick.toggle(row1); await tick();
  out.reopened = host.hidden === false;
  (events.hide || []).forEach((f) => f({ target: drawer }));
  out.hide_closes = host.hidden === true && !row1.classList.contains('is-picking');
  out.rows_kept = row1.input.value !== '' && row2.input.value !== '';

  // 8) 즐겨찾기 담기 길은 한 번도 안 불렸다(읽기만)
  out.fav_calls = fetches.filter((f) => f[1] === '/api/geo/favorites').map((f) => f[0]);
  console.log(JSON.stringify(out));
})().catch((e) => { console.error(e); process.exit(1); });
