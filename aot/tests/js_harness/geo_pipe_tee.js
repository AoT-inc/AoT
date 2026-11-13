// 배관 이음(T/엘보) 판정 하네스 — 실제 aot-geo-geometry.js 와 turf 를 읽어 돌린다.
// 사용: node geo_pipe_tee.js <aot-geo-geometry.js> <turf.min.js> → JSON 한 줄
'use strict';
const fs = require('fs'), vm = require('vm');
const sb = { console, setTimeout: () => 0, window: {} };
sb.globalThis = sb; vm.createContext(sb);
vm.runInContext(fs.readFileSync(process.argv[3], 'utf8'), sb);
sb.window.turf = sb.turf || sb.window.turf;
vm.runInContext(fs.readFileSync(process.argv[2], 'utf8') + '\n;this.G = AoTGeoGeometry;', sb);

const M = 1 / 111320;                              // 위도 1 m
const MX = M / Math.cos(35 * Math.PI / 180);       // 경도 1 m (실제 좌표 크기에서 돌려야 turf lineSplit 이 맞다)
function mk(id, sub, pts, drawId) {
  const coords = pts.map(p => [127 + p[0] * MX, 35 + p[1] * M]);
  const l = {
    feature: { type: 'Feature', properties: { node_id: id, sub_type: sub, _aot_draw_id: drawId || id }, geometry: { type: 'LineString', coordinates: coords } },
    toGeoJSON() { return JSON.parse(JSON.stringify(this.feature)); },
    setLatLngs(ll) { this.feature.geometry.coordinates = ll.map(p => [p.lng, p.lat]); },
  };
  return l;
}
function run(layers) {
  const dots = [];
  const parent = { dirtyNodeIds: new Set(), deletedNodeIds: new Set(), layerStorage: {}, saveDesign() {}, map: { fire() {} } };
  const g = new sb.G(parent);
  g._isInternalAction = true;           // 저장·이벤트 부작용 차단(실제 재구성 중과 같다)
  g.createConnectionDot = (lat, lng, t) => dots.push(t);
  g.removeLayerSafe = () => {};
  g.updatePipeLabels = () => {};
  for (let i = 0; i < layers.length; i++) for (let j = i + 1; j < layers.length; j++) g._detectConnectionBetween(layers[i], layers[j], true);
  return { dots: dots.sort(), lens: layers.map(l => l.feature.geometry.coordinates.length) };
}
const out = {};
// 1) 주관 A(0..100) 중간(50)에 주관 B 끝점이 닿음 — 다른 그리기
let A = mk('A', 'pipe_main', [[0, 0], [100, 0]]), B = mk('B', 'pipe_main', [[50, 40], [50, 0]]);
out.mainEndOnMainMid = run([A, B]); out.mainEndOnMainMid.A = A.feature.geometry.coordinates.length;
// 1b) 같은 그리기 id 를 공유(한 번에 그린 것이 쪼개진 경우)
A = mk('A', 'pipe_main', [[0, 0], [100, 0]], 'd1'); B = mk('B', 'pipe_main', [[50, 40], [50, 0]], 'd1');
out.mainEndOnMainMidSameDraw = run([A, B]);
// 1c) 짧은 쪽(위 10 m 안)이 닿음 — 대상 주관의 짧은 쪽이 잘리는지
A = mk('A', 'pipe_main', [[0, 0], [100, 0]]); B = mk('B', 'pipe_main', [[5, 40], [5, 0]]);
out.mainEndNearOtherEnd = run([A, B]); out.mainEndNearOtherEnd.Acoords = A.feature.geometry.coordinates.map(c => Math.round((c[0] - 127) / MX));
// 2) 끝점끼리 꺾임
A = mk('A', 'pipe_main', [[0, 0], [50, 0]], 'd1'); B = mk('B', 'pipe_main', [[50, 0], [50, 40]], 'd1');
out.mainElbow = run([A, B]);
// 2b) 끝점끼리 다른 그리기
A = mk('A', 'pipe_main', [[0, 0], [50, 0]]); B = mk('B', 'pipe_main', [[50, 0], [50, 40]]);
out.mainEndEndDiffDraw = run([A, B]);
// 3) 지관 끝이 주관 중간에 닿음 / 지관 꺾임 / 지관-지관 T
A = mk('A', 'pipe_main', [[0, 0], [100, 0]]); B = mk('B', 'pipe_branch', [[50, 30], [50, 0]]);
out.branchOnMain = run([A, B]);
A = mk('A', 'pipe_branch', [[0, 0], [50, 0]], 'd1'); B = mk('B', 'pipe_branch', [[50, 0], [50, 40]], 'd1');
out.branchElbow = run([A, B]);
A = mk('A', 'pipe_branch', [[0, 0], [100, 0]]); B = mk('B', 'pipe_branch', [[50, 30], [50, 0]]);
out.branchOnBranch = run([A, B]);
// 4) 한 번에 그린 주관이 고리를 돌아 자기 앞 구간 중간에 닿음(겹쳐 그리기) — 같은 그리기 id
{
  const s1 = mk('s1', 'pipe_main', [[0, 0], [100, 0]], 'd'), s2 = mk('s2', 'pipe_main', [[100, 0], [100, 50]], 'd');
  const s3 = mk('s3', 'pipe_main', [[100, 50], [30, 50]], 'd'), s4 = mk('s4', 'pipe_main', [[30, 50], [30, 0]], 'd');
  out.loopBack = run([s1, s2, s3, s4]);
  out.loopBack.s1 = s1.feature.geometry.coordinates.map(c => Math.round((c[0] - 127) / MX));
}
// 5) 다른 주관의 중간(30 m 지점)에 닿음 — 대상 주관이 잘리면 안 된다
A = mk('A', 'pipe_main', [[0, 0], [100, 0]]); B = mk('B', 'pipe_main', [[30, 40], [30, 0]]);
out.mainEndOn30 = run([A, B]); out.mainEndOn30.A = A.feature.geometry.coordinates.map(c => Math.round((c[0] - 127) / MX));
// 6) 주관이 다른 주관을 2 m 넘겨 그은 실수는 그대로 잘려 T 가 된다(기존 동작)
// 7) 재구성을 한 번 더 돌려도(저장 뒤 다시 읽을 때처럼) 같은 결과여야 한다
{
  const s1 = mk('s1', 'pipe_main', [[0, 0], [100, 0]], 'd'), s2 = mk('s2', 'pipe_main', [[100, 0], [100, 50]], 'd');
  const s3 = mk('s3', 'pipe_main', [[100, 50], [30, 50]], 'd'), s4 = mk('s4', 'pipe_main', [[30, 50], [30, 0]], 'd');
  run([s1, s2, s3, s4]);
  out.loopBackAgain = run([s1, s2, s3, s4]);
}
console.log(JSON.stringify(out));
