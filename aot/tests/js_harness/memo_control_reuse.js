// 노트 버튼(createMemoControl)을 가짜 DOM·가짜 지도로 두 번 쓴다. 인자: 소스 파일 경로.
// 결과(JSON): 첫·둘째 클릭이 각각 open-notes 를 쐈는가.
const fs = require('fs');
const el = () => {
  const o = { style: {}, children: [], listeners: {}, classList: { add() {}, remove() {}, toggle() {} },
    setAttribute() {}, appendChild(c) { this.children.push(c); return c; }, remove() {},
    addEventListener(n, f) { this.listeners[n] = f; } };
  return o;
};
const events = [];
global.window = global;
global.document = { createElement: el, createElementNS: el, body: el() };
global.CustomEvent = function (n, d) { this.type = n; this.detail = d.detail; };
global.dispatchEvent = (e) => { events.push(e.type); };
global.maplibregl = {};
global.setTimeout = (f) => 0;
vm = require('vm');
vm.runInThisContext(fs.readFileSync(process.argv[2], 'utf8'));
const C = window.AoTMapCustomControls;
const clicks = {};
const map = { getContainer: () => el(), on(n, f) { clicks[n] = f; }, off(n, f) { if (clicks[n] === f) delete clicks[n]; } };
const ctl = C.createMemoControl(map, {});
const btn = ctl.container.children[0];
const out = [];
for (let i = 0; i < 2; i++) {
  btn.listeners.click({ preventDefault() {}, stopPropagation() {} });
  const before = events.length;
  if (clicks.click) clicks.click({ lngLat: { lat: 36, lng: 127 } });
  out.push(events.length > before);
}
console.log(JSON.stringify(out));
