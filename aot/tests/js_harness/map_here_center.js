// aot-map-here.js 를 가짜 지도·시트로 돌려 위치 시트의 길 다섯(기기 위치 밖 넷)과 검색·즐겨찾기를 확인한다.
// 사용: node map_here_center.js <aot-map-here.js 경로>   → 결과를 JSON 한 줄로 낸다.
const fs = require('fs');
const calls = [];
global.window = global;
function node(tag) {
  let text = '';
  return { tag, children: [], hidden: false, disabled: false, value: '', className: '', listeners: {},
    // 실제 DOM 처럼 textContent 를 쓰면 자식이 비워진다
    get textContent() { return text; }, set textContent(v) { text = v; this.children = []; },
    addEventListener(t, f) { this.listeners[t] = f; }, appendChild(c) { this.children.push(c); return c; },
    setAttribute() {}, focus() { calls.push(['focus', this.sel || this.className]); } };
}
const store = {};
global.localStorage = { getItem: (k) => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = String(v); } };
let touch = false;
global.matchMedia = (q) => ({ matches: q.indexOf('hover: hover') >= 0 ? !touch : false });
global.document = { hidden: false, documentElement: {}, createElement: node };
global.getComputedStyle = () => ({ getPropertyValue: () => '' });
global.showToast = (m) => calls.push(['toast', m]);
let favorites = [{ id: 7, name: 'Barn', lat: 35.0, lng: 126.0, address: 'Barn Rd', shared: true, mine: true },
                 { id: 9, name: 'Shed', lat: 34.0, lng: 125.0, address: '', shared: true, mine: false }];
global.fetch = (url, init) => {
  const method = (init && init.method) || 'GET';
  calls.push(['fetch', method, url, init && init.body]);
  let body = { ok: true, address: '1 Main St' };
  if (url === '/api/geo/favorites' && method === 'GET') { body = { ok: true, favorites: favorites }; }
  if (url === '/api/geo/favorites' && method === 'POST') {
    const d = JSON.parse(init.body);
    favorites = favorites.concat([{ id: 8, name: d.name, lat: d.lat, lng: d.lng, address: d.address }]);
    body = { ok: true, created: true };
  }
  if (url.indexOf('/api/geo/favorites/') === 0 && method === 'DELETE') { favorites = favorites.filter((f) => f.id !== 7); body = { ok: true }; }
  if (url.indexOf('/api/geo/favorites/7') === 0 && method === 'PATCH') { Object.assign(favorites.find((f) => f.id === 7), JSON.parse(init.body)); body = { ok: true }; }
  if (url === '/api/geo/favorites/7/move') {
    const i = favorites.findIndex((f) => f.id === 7), j = JSON.parse(init.body).direction === 'down' ? i + 1 : i - 1;
    [favorites[i], favorites[j]] = [favorites[j], favorites[i]]; body = { ok: true, favorites: favorites };
  }
  if (url.indexOf('/api/geo/around') === 0) { body = { ok: true, inside: ['3포장 > 3-1'], edge: [], near: [{ name: '밸브1', m: 18 }] }; }
  if (url === '/api/geo/search') {
    body = { ok: true, results: [{ name: 'Town Hall', address: 'Town Hall, 1 Rd', lat: '36.1', lng: '127.1' },
                                  { name: 'Bad', lat: 'x', lng: 1 }] };
  }
  return Promise.resolve({ json: () => Promise.resolve(body) });
};
eval(fs.readFileSync(process.argv[2], 'utf8'));

const els = {};
const root = { querySelector(sel) { if (!els[sel]) { els[sel] = node('q'); els[sel].sel = sel; } return els[sel]; } };
const handlers = {};
const sources = {};
const flights = [];
const map = {
  getCenter: () => ({ lat: 36.5, lng: 127.5 }), getZoom: () => 15,
  on() {}, once(ev, f) { handlers[ev] = f; },
  getStyle: () => ({}), getSource: (id) => sources[id], addSource(id, s) { sources[id] = { setData() {}, s }; },
  addLayer() {}, getLayer: () => null, removeLayer() {}, removeSource(id) { delete sources[id]; },
  getCanvas: () => ({ style: {} }), flyTo(o) { flights.push(o.center); }
};
let opened = 0;
const viewLog = [];
const ctl = AoTMapHere.attach(map, {
  uid: 'w1',
  openPanel() { opened++; return { getElement: () => root, on() {}, remove() {} }; },
  // 위젯의 '보이는 영역 중심' — 시트가 열린 뒤의 값이어야 한다(열린 수를 같이 남겨 순서를 본다)
  viewCenter() { viewLog.push(opened); return { lat: 36.7, lng: 127.7 }; }
});
const fire = (n) => n.listeners.click({ stopPropagation() {}, preventDefault() {} });
const tick = () => new Promise((r) => setTimeout(r, 10));

(async () => {
  const out = {};
  // 0) 손가락 화면(hover 없음·pointer coarse)에서는 검색칸에 초점을 두지 않는다 — iOS 가 키보드와 확대를 부른다
  touch = true;
  const t0 = calls.length;
  const touchCtl = AoTMapHere.attach(map, { uid: 'w9', openPanel() { return { getElement: () => root, on() {}, remove() {} }; } });
  await touchCtl.startSearch();
  out.touch_focus = calls.slice(t0).some((c) => c[0] === 'focus');
  touchCtl.clear();
  touch = false;
  calls.length = 0;
  // 1) 검색 버튼 진입 — 위치 권한 없이 열리고 검색칸에 초점, 즐겨찾기 목록을 불러온다
  await ctl.startSearch(); await tick();
  out.opened = opened;
  out.search_focus = calls.some((c) => c[0] === 'focus' && c[1].indexOf('aot-here-q') >= 0);
  out.fav_loaded = els['.aot-here-favs'].children.length;
  out.no_gps = calls.filter((c) => c[0] === 'fetch').every((c) => c[2].indexOf('/api/geo/address') < 0);
  out.snap_before = AoTMapHere.snapshot(['w1']);

  // 2) 주소 검색 → 결과(좌표가 깨진 것은 거른다) → 고르면 지도가 옮겨가고 알려진 주소로 자리가 선다
  els['.aot-here-q'].value = 'town';
  fire(els['.aot-here-go']); await tick();
  const results = els['.aot-here-results'].children;
  out.result_rows = results.length;
  fire(results[0].children[0]); await tick();            // 이름 부분을 누름
  out.flew_to = flights[flights.length - 1];
  out.search_snap = AoTMapHere.snapshot(['w1']);
  out.no_lookup_for_known_address = calls.filter((c) => c[0] === 'fetch' && c[2].indexOf('/api/geo/address') >= 0).length;

  // 3) 즐겨찾기에 담기 → 목록이 다시 불린다
  fire(els['.aot-here-fav']); await tick();
  out.post = calls.filter((c) => c[0] === 'fetch' && c[1] === 'POST' && c[2] === '/api/geo/favorites').map((c) => JSON.parse(c[3]));
  out.fav_rows_after_add = els['.aot-here-favs'].children.length;

  // 3-1) 자리 관계 줄(구획·가까운 장치) — 서버가 푼 이름
  out.around_text = els['.aot-here-around'].textContent;
  out.around_call = calls.filter((c) => c[0] === 'fetch' && c[2].indexOf('/api/geo/around') === 0).map((c) => c[2]);

  // 3-2) 편집 줄: 열기 → 이름 바꾸기 → 아래로 → 개인용으로
  const favBox = () => els['.aot-here-favs'];
  fire(favBox().children[0].children[0].children[1]); await tick();                  // [편집]
  let edit = favBox().children[0].children[1];
  out.edit_open = !!edit;
  const line = edit.children[0], acts = edit.children[1];
  line.children[0].value = 'Big Barn'; fire(line.children[1]); await tick();         // [저장]
  out.patch_name = calls.filter((c) => c[1] === 'PATCH').map((c) => c[3]);
  edit = favBox().children[0].children[1];
  const labels = edit.children[1].children.map((b) => b.textContent);
  out.edit_labels = labels;
  out.up_disabled = edit.children[1].children[0].disabled;
  fire(edit.children[1].children[1]); await tick();                                  // [아래로]
  out.order_after_move = favBox().children.map((w) => w.children[0].children[0].children[0].textContent);
  edit = favBox().children[1] && favBox().children[1].children[1];
  out.second_row_edit_open = !!edit;                                                 // 편집 중이던 줄(id 7)이 아래로 갔다
  const mineRow = favBox().children.find((w) => w.children[1]);
  fire(mineRow.children[1].children[1].children[2]); await tick();                   // [나만 보기]
  out.patch_shared = calls.filter((c) => c[1] === 'PATCH').map((c) => c[3]).slice(-1)[0];

  // 3-3) 최근 선택(검색 결과를 고르면 쌓인다) · 좌표 붙여넣기
  out.recent_stored = JSON.parse(store['aot_here_recent']).map((r) => r.name);
  els['.aot-here-q'].value = '36.6667, 129.1124'; fire(els['.aot-here-go']); await tick();
  out.coord_rows = els['.aot-here-results'].children.length;
  out.coord_search_calls = calls.filter((c) => c[0] === 'fetch' && c[2] === '/api/geo/search').length;
  els['.aot-here-q'].value = '129.1124, 36.6667'; fire(els['.aot-here-go']); await tick();   // 경도,위도 순서도 알아본다
  out.swapped = els['.aot-here-results'].children.length;
  els['.aot-here-q'].value = '95, 200'; fire(els['.aot-here-go']); await tick();
  out.out_of_range_goes_to_search = calls.filter((c) => c[0] === 'fetch' && c[2] === '/api/geo/search').length;

  // 4) 즐겨찾기 줄을 누르면 그 자리로
  fire(els['.aot-here-favs'].children[0].children[0].children[0]); await tick();
  out.fav_snap = AoTMapHere.snapshot(['w1']);

  // 5) 즐겨찾기 지우기
  const openWrap = els['.aot-here-favs'].children.find((w) => w.children[1]);          // 편집이 펼쳐진 줄
  const acts5 = openWrap.children[1].children[1].children;
  fire(acts5[acts5.length - 1]); await tick();                                         // [빼기]
  out.fav_rows_after_remove = els['.aot-here-favs'].children.length;

  // 6) 지도 중심 · 눌러 고르기 — 위젯이 준 보이는 영역 중심을 쓴다(캔버스 중심 36.5/127.5 가 아니라)
  fire(els['.aot-here-center']); await tick();
  out.center_snap = AoTMapHere.snapshot(['w1']);
  fire(els['.aot-here-pick']);
  handlers.click({ lngLat: { lat: 35.1, lng: 126.9 } }); await tick();
  out.pick_snap = AoTMapHere.snapshot(['w1']);

  out.view_log_before_close = viewLog.slice();
  ctl.clear();
  await ctl.startAtCenter();                                             // 닫힌 시트에서 시작 — 먼저 열고 나서 잰다
  out.cold_start_snap = AoTMapHere.snapshot(['w1']);
  out.view_log = viewLog.slice();
  out.again_opened = (await ctl.startAtCenter(), opened);              // 이미 열려 있으면 다시 열지 않는다
  const plain = AoTMapHere.attach(map, { uid: 'w2', openPanel() { return { getElement: () => root, on() {}, remove() {} }; } });
  await plain.startAtCenter();
  out.plain_snap = AoTMapHere.snapshot(['w2']);
  plain.clear();
  out.other_widget = AoTMapHere.snapshot(['zz']);
  ctl.clear();
  out.after_clear = AoTMapHere.snapshot(['w1']);
  console.log(JSON.stringify(out));
})();
