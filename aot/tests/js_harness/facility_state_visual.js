// 시설 3D 상태 적용기(resolveFittingState / applyRuntime / tick)를 실제 three.js 로 돌려 본다.
// 사용: node facility_state_visual.js <AoT_facility 폴더>   → 결과를 JSON 한 줄로 낸다.
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const dir = process.argv[2];
globalThis.window = globalThis;
globalThis.self = globalThis;
vm.runInThisContext(fs.readFileSync(path.join(dir, 'three.min.js'), 'utf8'));
// 번들(facility-3d)과 같은 순서 — parametric 이 먼저 있어야 외피가 판으로 쪼개진다.
vm.runInThisContext(fs.readFileSync(path.join(dir, 'core', 'parametric.js'), 'utf8'));
vm.runInThisContext(fs.readFileSync(path.join(dir, 'core', 'layout-mesh.js'), 'utf8'));
vm.runInThisContext(fs.readFileSync(path.join(dir, 'aot-facility-3d.js'), 'utf8'));
const A = window.AoTFacility3D;
const out = {};
const near = (a, b, e = 1e-6) => Math.abs(a - b) < e;

// ── 리졸버 ───────────────────────────────────────────────────────────────
const rt = {
  actuator_states: {
    thermal_curtain_motor: { output_uuid: 'o-slot', on: true, percent: 40, control_type: 'value' },
    side: { output_uuid: 'o-win', on: true, percent: 30, control_type: 'pwm' },
    fan1: { output_uuid: 'o-fan', on: false, percent: null, control_type: 'binary' },
  },
};
out.byId = A.resolveFittingState({ kind: 'window', actuator_id: 'o-win' }, rt);
out.idBeatsSlot = A.resolveFittingState({ kind: 'curtain', actuator_id: 'o-fan' }, rt);
out.slotFallback = A.resolveFittingState({ kind: 'curtain' }, rt);
out.unbound = A.resolveFittingState({ kind: 'window' }, rt);
out.noRuntime = A.resolveFittingState({ kind: 'window', actuator_id: 'o-win' }, null);
out.stale = A.resolveFittingState({ kind: 'window', actuator_id: 'o-win' }, Object.assign({ stale: true }, rt));
out.missing = A.resolveFittingState({ kind: 'window', actuator_id: 'nope' }, rt);
out.binaryOn = A.resolveFittingState({ kind: 'fan', actuator_id: 'x' },
  { actuator_states: { a: { output_uuid: 'x', on: true, percent: null, control_type: 'binary' } } });

// ── 각도 ─────────────────────────────────────────────────────────────────
out.angles = {
  pwm30: A.hingeAngleDeg('window', out.byId),
  binaryOn: A.hingeAngleDeg('door', out.binaryOn),
  off: A.hingeAngleDeg('window', out.idBeatsSlot),
  unknown: A.hingeAngleDeg('window', out.noRuntime),
};

// ── 장면 도우미 ──────────────────────────────────────────────────────────
function box(root, spec, size, pos, euler) {
  const g = new THREE.BoxGeometry(size[0], size[1], size[2]);
  const m = new THREE.Mesh(g, new THREE.MeshStandardMaterial({ color: 0x7ec8e3, transparent: true, opacity: 0.28 }));
  m.position.set(...pos); if (euler) m.rotation.set(...euler);
  m.name = 'fitting:' + spec.id; m.userData.fittingSpec = spec;
  const e = new THREE.LineSegments(new THREE.EdgesGeometry(g), new THREE.LineBasicMaterial({ color: 0x263238 }));
  e.position.copy(m.position); e.quaternion.copy(m.quaternion); e.name = 'edges:fitting:' + spec.id;
  root.add(m); root.add(e);
  return { m, e };
}
const world = (obj, v) => { obj.updateMatrixWorld(true); return v.clone().applyMatrix4(obj.matrixWorld); };
const st = (id, on, pct, type) => ({ actuator_states: { s: { output_uuid: id, on, percent: pct, control_type: type || 'pwm' } } });

// ── 창: 윗변 모서리 피벗 ─────────────────────────────────────────────────
{
  const root = new THREE.Group();
  const { m, e } = box(root, { id: 'w', kind: 'window', actuator_id: 'u-w' }, [2, 1, 0.1], [3, 2, 1], [0, Math.PI / 2, 0]);
  const top = new THREE.Vector3(0, 0.5, 0), bottom = new THREE.Vector3(0, -0.5, 0);
  const top0 = world(m, top), bot0 = world(m, bottom);
  A.applyRuntime(root, null, st('u-w', true, 100), { motion: false });
  const top1 = world(m, top), bot1 = world(m, bottom);
  const edgesTop = world(e, top);
  out.window = {
    topFixed: top0.distanceTo(top1) < 1e-6,
    edgesFollow: edgesTop.distanceTo(top1) < 1e-6,
    bottomMoved: bot0.distanceTo(bot1),
    expectedChord: 2 * Math.sin(Math.PI / 8),            // 45도 현
    centerMoved: m.position.distanceTo(new THREE.Vector3(3, 2, 1)) > 0.01,
  };
  A.applyRuntime(root, null, st('u-w', false, 0), { motion: false });
  out.window.closedBack = world(m, bottom).distanceTo(bot0) < 1e-6;
  A.applyRuntime(root, null, st('u-w', true, 50), { motion: false });
  const half = world(m, bottom).distanceTo(bot0);
  out.window.halfChord = half; out.window.halfExpected = 1 * 2 * Math.sin((22.5 * Math.PI / 180) / 2);
}

// ── 문: 세로변 피벗, 90도 ────────────────────────────────────────────────
{
  const root = new THREE.Group();
  const { m } = box(root, { id: 'd', kind: 'door', actuator_id: 'u-d' }, [1, 2, 0.1], [0, 1, 0]);
  const hinge = new THREE.Vector3(-0.5, 0, 0), free = new THREE.Vector3(0.5, 0, 0);
  const h0 = world(m, hinge);
  A.applyRuntime(root, null, st('u-d', true, null, 'binary'), { motion: false });
  const f1 = world(m, free);
  out.door = { hingeFixed: h0.distanceTo(world(m, hinge)) < 1e-6, freeZ: f1.z, freeX: f1.x };
}

// ── 천장 커튼: 열림 비율만큼 가장자리로 ──────────────────────────────────
{
  const root = new THREE.Group();
  const { m, e } = box(root, { id: 'c', kind: 'curtain', actuator_id: 'u-c' }, [10, 0.02, 20], [5, 3, 10]);
  A.applyRuntime(root, null, st('u-c', true, 100), { motion: false });
  const L = root.getObjectByName('fitting:c:L'), R = root.getObjectByName('fitting:c:R');
  out.curtainOpen = { mainHidden: m.scale.x < 1e-3, foldW: L && L.scale.x, lx: L && L.position.x, rx: R && R.position.x,
    hasEdges: !!root.getObjectByName('edges:fitting:c:L') };
  out.curtainFoldD = { sd: L.scale.z, d: 20, h: L.scale.y };
  A.applyRuntime(root, null, st('u-c', true, 50), { motion: false });
  out.curtainHalf = { foldW: L.scale.x, expected: 5 * 0.5 + 1.0 * 0.5 };
  A.applyRuntime(root, null, st('u-c', false, 0), { motion: false });
  out.curtainClosed = { mainScale: m.scale.x, foldHidden: L.scale.x < 1e-3 };
}

// ── 팬: 날개 + 모션 ──────────────────────────────────────────────────────
{
  const root = new THREE.Group();
  box(root, { id: 'f', kind: 'fan', actuator_id: 'u-f' }, [1, 1, 0.3], [0, 2, 0]);
  const r1 = A.applyRuntime(root, null, st('u-f', true, null, 'binary'), { motion: true });
  const bl = root.getObjectByName('fitting:f:blades');
  const r0 = bl.rotation.z;
  const more = A.tick(root, 50);
  const spun = bl.rotation.z !== r0;
  const r2 = A.applyRuntime(root, null, st('u-f', true, null, 'binary'), { motion: false });
  const stillMore = A.tick(root, 50);
  A.applyRuntime(root, null, st('u-f', false, 0, 'binary'), { motion: true });
  out.fan = { animating: r1.animating, visible: true, more, spun, reducedAnimating: r2.animating, reducedTick: stillMore, hiddenWhenOff: bl.visible === false,
    tickAfterOff: A.tick(root, 50) };
}

// ── 모름은 반투명, 히터는 emissive ───────────────────────────────────────
{
  const root = new THREE.Group();
  const { m, e } = box(root, { id: 'h', kind: 'heater', actuator_id: 'u-h' }, [1, 1, 1], [0, 0, 0]);
  m.material.emissive = new THREE.Color(0); m.material.emissiveIntensity = 0;
  A.applyRuntime(root, null, null, { motion: false });
  const dim = m.material.opacity;
  A.applyRuntime(root, null, st('u-h', true, null, 'binary'), { motion: false, onColor: 0x123456 });
  out.heater = { dim, base: 0.28, onEmissive: m.material.emissiveIntensity, opacityRestored: near(m.material.opacity, 0.28),
    outline: e.material.color.getHex() };
  A.applyRuntime(root, null, st('u-h', false, 0, 'binary'), { motion: false });
  out.heater.offEmissive = m.material.emissiveIntensity; out.heater.offOutline = e.material.color.getHex();
}

// ── 관수: 켜지면 물 부피 ─────────────────────────────────────────────────
{
  const root = new THREE.Group();
  const cone = new THREE.Mesh(new THREE.ConeGeometry(0.06, 0.18, 8), new THREE.MeshStandardMaterial());
  cone.name = 'fitting:i'; cone.position.set(1, 2, 1); cone.rotation.z = Math.PI;
  cone.userData.fittingSpec = { id: 'i', kind: 'irrigation_device', actuator_id: 'u-i', radius_m: 5 };
  root.add(cone);
  const r = A.applyRuntime(root, null, st('u-i', true, null, 'binary'), { motion: true });
  const w = root.getObjectByName('fitting:i:water');
  out.water = { exists: !!w, visible: w && w.visible, animating: r.animating, geo: w && w.geometry.type, color: w && w.material.color.getHex() };
  A.applyRuntime(root, null, st('u-i', false, 0, 'binary'), { motion: true });
  out.water.hiddenOff = w.visible === false;
  cone.visible = false;
  A.applyRuntime(root, null, st('u-i', true, null, 'binary'), { motion: true });
  out.water.hiddenByCategory = w.visible === false;
}

// ── 개폐 방식(open_mode): 미닫이·들창·권취, 없는 값은 힌지 ─────────────────
{
  // 법선 -X 벽(x=-5)의 측창 3 x 1.2. rotation.y = -90도 → 국소 +Z 가 세계 -X.
  const mk = (mode) => {
    const root = new THREE.Group();
    const spec = { id: 'o' + mode, kind: 'side_window', actuator_id: 'u-o', open_mode: mode };
    const { m, e } = box(root, spec, [3, 1.2, 0.1], [-5, 1.8, 10], [0, -Math.PI / 2, 0]);
    return { root, m, e };
  };
  const centre = new THREE.Vector3(0, 0, 0), top = new THREE.Vector3(0, 0.6, 0), bottom = new THREE.Vector3(0, -0.6, 0);
  const sz = { w: 3, h: 1.2, d: 0.1 };
  out.openMode = {};
  {   // slide — 폭 방향으로 w x r, 회전 없음, 외곽선 동행, 되돌림·반복 적용 누적 없음
    const { root, m, e } = mk('slide');
    const c0 = world(m, centre), q0 = m.quaternion.clone();
    const xAxis = new THREE.Vector3(1, 0, 0).applyQuaternion(q0);
    A.applyRuntime(root, null, st('u-o', true, 50), { motion: false });
    const c1 = world(m, centre), d = c1.clone().sub(c0);
    out.openMode.slide = {
      moved: d.length(), expected: sz.w * 0.5,
      alongWidth: Math.abs(d.clone().normalize().dot(xAxis)),
      noTurn: m.quaternion.angleTo(q0) < 1e-9,
      edgesFollow: world(e, centre).distanceTo(c1) < 1e-9,
    };
    A.applyRuntime(root, null, st('u-o', false, 0), { motion: false });
    out.openMode.slide.back = world(m, centre).distanceTo(c0) < 1e-9;
    A.applyRuntime(root, null, st('u-o', true, 50), { motion: false });
    A.applyRuntime(root, null, st('u-o', true, 50), { motion: false });
    out.openMode.slide.noAccumulate = Math.abs(world(m, centre).distanceTo(c0) - sz.w * 0.5) < 1e-9;
  }
  {   // lift — 국소 +Y(= 세계 +Y) 로 h x r
    const { root, m } = mk('lift');
    const c0 = world(m, centre);
    A.applyRuntime(root, null, st('u-o', true, 100), { motion: false });
    const d = world(m, centre).sub(c0);
    out.openMode.lift = { dy: d.y, dx: d.x, dz: d.z, expected: sz.h };
    A.applyRuntime(root, null, st('u-o', false, 0), { motion: false });
    out.openMode.lift.back = world(m, centre).distanceTo(c0) < 1e-9;
  }
  {   // roll — 윗변 고정, 높이 (1-r), 아랫변 바깥에 원통 뭉치가 r 에 따라 굵어진다
    const { root, m, e } = mk('roll');
    const top0 = world(m, top), bot0 = world(m, bottom), c0 = world(m, centre);
    A.applyRuntime(root, null, st('u-o', true, 50), { motion: false });
    const roll = root.getObjectByName('fitting:oroll:roll');
    const top1 = world(m, top), bot1 = world(m, bottom);
    out.openMode.roll = {
      topFixed: top0.distanceTo(top1) < 1e-9,
      scaleY: m.scale.y, edgesScaleY: e.scale.y,
      bottomRose: bot1.y - bot0.y, expectedRise: sz.h * 0.5,
      hasRoll: !!roll, isCylinder: roll && roll.geometry.type,
      r50: roll && roll.scale.x, len: roll && roll.scale.y,
      atBottomEdge: roll && Math.abs(roll.position.y - bot1.y) < 1e-9,
      outside: roll && roll.position.x < bot1.x - 1e-6,       // 벽 법선이 -X 다
      expectedR50: A.rollRadius(sz, 0.5), expectedR100: A.rollRadius(sz, 1),
    };
    A.applyRuntime(root, null, st('u-o', true, 100), { motion: false });
    out.openMode.roll.r100 = roll.scale.x;
    A.applyRuntime(root, null, st('u-o', false, 0), { motion: false });
    out.openMode.roll.back = world(m, centre).distanceTo(c0) < 1e-9 && m.scale.y === 1 && roll.scale.x < 1e-3;
    const n = root.children.length;
    A.applyRuntime(root, null, st('u-o', true, 100), { motion: false });
    A.applyRuntime(root, null, st('u-o', false, 0), { motion: false });
    out.openMode.roll.countStable = root.children.length === n;
  }
  {   // 모르는 값 = 힌지(측창 60도, 윗변 피벗)
    const { root, m } = mk('bogus');
    const top0 = world(m, top), bot0 = world(m, bottom);
    A.applyRuntime(root, null, st('u-o', true, 100), { motion: false });
    out.openMode.fallback = {
      topFixed: top0.distanceTo(world(m, top)) < 1e-9,
      bottomMoved: world(m, bottom).distanceTo(bot0),
      expectedChord: 2 * sz.h * Math.sin((60 * Math.PI / 180) / 2),
    };
  }
}

// ── 흐름 띠: 팬·히터가 켜졌을 때만, 정면(+Z = 법선) 쪽으로 1.5배 ─────────
{
  const root = new THREE.Group();
  // rotation.y = +90도 → 국소 +Z 가 세계 +X
  const { m } = box(root, { id: 'fb', kind: 'fan', actuator_id: 'u-fb' }, [1, 1, 0.3], [0, 2, 0], [0, Math.PI / 2, 0]);
  A.applyRuntime(root, null, st('u-fb', false, 0, 'binary'), { motion: true });
  const none = root.getObjectByName('fitting:fb:band');
  const r1 = A.applyRuntime(root, null, st('u-fb', true, null, 'binary'), { motion: true });
  const band = root.getObjectByName('fitting:fb:band');
  const mat = band.children[0].material;
  const off0 = mat.map.offset.y;
  A.tick(root, 50);
  root.updateMatrixWorld(true);        // 띠는 자식이라 부모 행렬까지 갱신해야 세계 좌표가 맞다
  const tip = world(band, new THREE.Vector3(0, 0, band.children[0].scale.z / 2));
  out.band = {
    noneWhenOff: !none, exists: !!band, visible: band.visible, isChild: band.parent === m,
    planes: band.children.length, len: band.children[0].scale.z, expectedLen: 1.5,
    tipX: tip.x, expectedTipX: 0.15 + 1.5, tipY: tip.y,
    color: mat.color.getHex(), fanColor: m.material.color.getHex(),
    translucent: mat.transparent && mat.opacity < 0.5,
    flows: mat.map.offset.y !== off0, animating: r1.animating,
  };
  A.applyRuntime(root, null, st('u-fb', false, 0, 'binary'), { motion: true });
  out.band.hiddenOff = band.visible === false;
  // reduced motion: 띠는 보이되 흐르지 않는다
  A.applyRuntime(root, null, st('u-fb', true, null, 'binary'), { motion: false });
  const off1 = mat.map.offset.y, more = A.tick(root, 50);
  out.band.staticWhenReduced = band.visible && mat.map.offset.y === off1 && more === false;
}
{
  const root = new THREE.Group();
  const { m } = box(root, { id: 'hb', kind: 'heater', actuator_id: 'u-hb' }, [0.6, 0.6, 0.6], [2, 1, 2]);
  m.material.emissive = new THREE.Color(0); m.material.emissiveIntensity = 0;
  A.applyRuntime(root, null, st('u-hb', true, null, 'binary'), { motion: false });
  const band = root.getObjectByName('fitting:hb:band');
  out.heaterBand = { exists: !!band, visible: !!(band && band.visible), emissive: m.material.emissiveIntensity };
  A.applyRuntime(root, null, st('u-hb', false, 0, 'binary'), { motion: false });
  out.heaterBand.hiddenOff = band.visible === false;
}

// ── 분무(mist) 머리: 넓고 낮은 안개 원반 ──────────────────────────────────
{
  const root = new THREE.Group();
  const cone = new THREE.Mesh(new THREE.ConeGeometry(0.06, 0.18, 8), new THREE.MeshStandardMaterial());
  cone.name = 'fitting:mi'; cone.position.set(1, 2, 1); cone.rotation.z = Math.PI;
  cone.userData.fittingSpec = { id: 'mi', kind: 'irrigation_device', actuator_id: 'u-mi', sub_type: 'mist', radius_m: 2 };
  root.add(cone);
  const r = A.applyRuntime(root, null, st('u-mi', true, null, 'binary'), { motion: true });
  const w = root.getObjectByName('fitting:mi:water');
  out.mist = { exists: !!w, geo: w.geometry.type, R: w.scale.x, H: w.scale.y, belowHead: w.position.y < 2 - 0.09,
    opacity: w.material.opacity, color: w.material.color.getHex(), animating: r.animating };
  A.applyRuntime(root, null, st('u-mi', false, 0, 'binary'), { motion: true });
  out.mist.hiddenOff = w.visible === false;
}

// ── 방식이 바뀌면 옛 뭉치는 숨고, 모름이면 뭉치도 반투명 ────────────────────
{
  const root = new THREE.Group();
  const spec = { id: 'sw', kind: 'side_window', actuator_id: 'u-sw', open_mode: 'roll' };
  const { m } = box(root, spec, [3, 1.2, 0.1], [-5, 1.8, 10], [0, -Math.PI / 2, 0]);
  A.applyRuntime(root, null, st('u-sw', true, 100), { motion: false });
  const roll = root.getObjectByName('fitting:sw:roll');
  const shownRoll = roll.scale.x > 1e-3, rollOpacityOn = roll.material.opacity;
  A.applyRuntime(root, null, null, { motion: false });                 // 모름
  const rollOpacityUnknown = roll.material.opacity, mainOpacityUnknown = m.material.opacity;
  spec.open_mode = 'hinge';                                              // 설계에서 방식을 바꿈(재빌드 전)
  A.applyRuntime(root, null, st('u-sw', true, 100), { motion: false });
  out.modeSwitch = { shownRoll, rollOpacityOn, rollOpacityUnknown, mainOpacityUnknown,
    rollHiddenAfterSwitch: roll.scale.x < 1e-3, hingeTurned: m.quaternion.angleTo(new THREE.Quaternion().setFromEuler(new THREE.Euler(0, -Math.PI / 2, 0))) > 0.1 };
}

// ── disposeParts: 부속의 자체 자원만 해제, 공유 자원은 남긴다 ────────────────
{
  const root = new THREE.Group();
  box(root, { id: 'dr', kind: 'side_window', actuator_id: 'u-dr', open_mode: 'roll' }, [3, 1.2, 0.1], [0, 1, 0]);
  box(root, { id: 'df', kind: 'fan', actuator_id: 'u-df' }, [1, 1, 0.3], [2, 2, 0]);
  const cone = new THREE.Mesh(new THREE.ConeGeometry(0.06, 0.18, 8), new THREE.MeshStandardMaterial());
  cone.name = 'fitting:dm'; cone.position.set(1, 2, 1);
  cone.userData.fittingSpec = { id: 'dm', kind: 'irrigation_device', actuator_id: 'u-dm', sub_type: 'mist', radius_m: 2 };
  root.add(cone);
  const rt = { actuator_states: { a: { output_uuid: 'u-dr', on: true, percent: 100, control_type: 'pwm' },
    b: { output_uuid: 'u-df', on: true, control_type: 'binary' }, c: { output_uuid: 'u-dm', on: true, control_type: 'binary' } } };
  A.applyRuntime(root, null, rt, { motion: false });
  const roll = root.getObjectByName('fitting:dr:roll'), band = root.getObjectByName('fitting:df:band');
  const blades = root.getObjectByName('fitting:df:blades'), water = root.getObjectByName('fitting:dm:water');
  const freed = [];
  const watch = (x, tag) => x.addEventListener('dispose', () => freed.push(tag));
  watch(roll.geometry, 'roll.geo'); watch(roll.material, 'roll.mat');
  watch(band.children[0].material, 'band.mat'); watch(band.children[0].geometry, 'band.geoShared');
  watch(band.children[0].material.map, 'band.texShared');
  watch(blades.children[0].geometry, 'blades.geo'); watch(blades.children[0].material, 'blades.mat');
  watch(water.geometry, 'water.discShared'); watch(water.material, 'water.matClone'); watch(water.material.map, 'water.texShared');
  const main = root.getObjectByName('fitting:dr'); watch(main.geometry, 'main.geo');
  A.disposeParts(root);
  out.disposeParts = { freed: freed.sort() };
}

// ── 지정 없는 설비는 건드리지 않는다 ─────────────────────────────────────
{
  const root = new THREE.Group();
  const { m } = box(root, { id: 'z', kind: 'window' }, [1, 1, 0.1], [0, 0, 0]);
  A.applyRuntime(root, null, null, { motion: false });
  out.untouched = { opacity: m.material.opacity, pos: m.position.toArray() };
}
// ── 외피 개구: 측벽 구멍 · 지붕 (s,z) 격자 구멍 ─────────────────────────────
{
  const Pm = window.AoTParametric;
  const mat = new THREE.MeshBasicMaterial();
  const base = { unitCount: 1, unitWidth: 10, effectiveSpacing: 0, meshBayCount: 1, span: 10, eaveH: 3, ridgeH: 6, length: 20, material: mat };
  const byName = (g, n) => g.getObjectByName(n);
  // 삼각형 무게중심 목록 — 구멍 안에는 하나도 없어야 하고(삼각형은 구멍을 덮지 않는다), 옆에는 있어야 한다.
  // ShapeGeometry(벽·마구리)는 인덱스를 쓰고 지붕 격자는 쓰지 않는다 — 둘 다 삼각형 단위로 읽는다.
  const tris = (mesh) => {
    const g = mesh.geometry, p = g.attributes.position, idx = g.index, n = idx ? idx.count : p.count, o = [];
    const at = (k) => (idx ? idx.getX(k) : k);
    for (let i = 0; i < n; i += 3) {
      const a = at(i), b = at(i + 1), c = at(i + 2);
      o.push([(p.getX(a) + p.getX(b) + p.getX(c)) / 3, (p.getY(a) + p.getY(b) + p.getY(c)) / 3, (p.getZ(a) + p.getZ(b) + p.getZ(c)) / 3]);
    }
    return o;
  };
  const inBox = (t, x0, x1, y0, y1, z0, z1) => t[0] > x0 && t[0] < x1 && t[1] > y0 && t[1] < y1 && t[2] > z0 && t[2] < z1;

  {   // 아치 측창 2개(-X 벽) → 그 벽 holes 2. 두께 0.5 창은 벽에서 0.3 떨어져도 구멍, 보강 외피(1 m 밖)의 창은 아님.
    const fits = [
      { kind: 'side_window', position: { x: -0.05, y: 1.8, z: 5 }, size: { w: 3, h: 1.2, d: 0.1 }, surface_normal: [-1, 0, 0] },
      { kind: 'side_window', position: { x: -0.05, y: 1.8, z: 14 }, size: { w: 3, h: 1.2, d: 0.1 }, surface_normal: [-1, 0, 0] },
      { kind: 'window', position: { x: 10.3, y: 1.5, z: 10 }, size: { w: 2, h: 1, d: 0.5 }, surface_normal: [1, 0, 0] },
      { kind: 'window', position: { x: 11.05, y: 1.5, z: 4 }, size: { w: 2, h: 1, d: 0.1 }, surface_normal: [1, 0, 0] },
      { kind: 'fan', position: { x: -0.15, y: 2, z: 3 }, size: { w: 1, h: 1, d: 0.3 }, surface_normal: [-1, 0, 0] },
      { kind: 'door', position: { x: 5, y: 1, z: -0.05 }, size: { w: 1, h: 2, d: 0.1 }, surface_normal: [0, 0, -1] },
    ];
    const op = Pm.coverOpeningsFromFittings(fits);
    const g = Pm.buildOuterCoverPanels(Object.assign({ roofType: 'arch', openings: op }, base));
    const neg = byName(g, 'outer_cover_u0_x_neg'), pos = byName(g, 'outer_cover_u0_x_pos');
    const wt = tris(neg);
    out.coverWalls = {
      walls: op.walls.length, caps: op.caps.length, roof: op.roof.length,
      negHoles: neg.userData.holes, posHoles: pos.userData.holes,
      capHoles: byName(g, 'outer_cover_u0_y_neg').userData.holes, roofHoles: byName(g, 'outer_cover_u0_roof').userData.holes,
      names: g.children.filter(c => c.isMesh).map(c => c.name).sort(),
      insideHole: wt.filter(t => inBox(t, -1, 1, 1.3, 2.3, 3.6, 6.4)).length + wt.filter(t => inBox(t, -1, 1, 1.3, 2.3, 12.6, 15.4)).length,
      wallTris: wt.length,
    };
  }
  {   // 박공 천창 2개(양 경사, sides 배치) → 경사에 구멍, 정점(x≈5)엔 없음
    const sn = Math.sqrt(34);
    const fits = [
      { kind: 'window', position: { x: 3, y: 4.8, z: 10 }, size: { w: 15, h: 1.8, d: 0.06 }, surface_normal: [-3 / sn, 5 / sn, 0] },
      { kind: 'window', position: { x: 7, y: 4.8, z: 10 }, size: { w: 15, h: 1.8, d: 0.06 }, surface_normal: [3 / sn, 5 / sn, 0] },
    ];
    const op = Pm.coverOpeningsFromFittings(fits);
    const g = Pm.buildOuterCoverPanels(Object.assign({ roofType: 'gable', openings: op }, base));
    const roof = byName(g, 'outer_cover_u0_roof'), rt = tris(roof);
    const lines = byName(g, 'outer_cover_u0_roof_holes');
    out.coverGable = {
      roofOpenings: op.roof.length, holes: roof.userData.holes,
      inLeft: rt.filter(t => inBox(t, 2.4, 3.6, 0, 10, 3, 17)).length,
      inRight: rt.filter(t => inBox(t, 6.4, 7.6, 0, 10, 3, 17)).length,
      ridge: rt.filter(t => inBox(t, 4.2, 5.8, 5.0, 10, 3, 17)).length,
      ends: rt.filter(t => inBox(t, 2.4, 3.6, 0, 10, 0, 2.4)).length + rt.filter(t => inBox(t, 2.4, 3.6, 0, 10, 17.6, 20)).length,
      eaves: rt.filter(t => inBox(t, 0, 1.5, 0, 10, 0, 20)).length,
      maxY: Math.max(...rt.map(t => t[1])),
      outline: lines ? lines.geometry.attributes.position.count : 0,
      sameEdgeMat: !!lines && lines.material === g.children.find(c => c.isLineSegments && c !== lines).material,
    };
  }
  {   // flat 지붕: 법선 없는 용마루 천창(w 는 x, d 는 z) → 정점 띠에 구멍, 옆·수직 띠는 그대로. 공중의 창은 구멍 아님.
    const fits = [
      { kind: 'window', position: { x: 5, y: 5.97, z: 10 }, size: { w: 0.8, h: 0.06, d: 15 }, surface_normal: null },
      { kind: 'window', position: { x: 5, y: 1.5, z: 10 }, size: { w: 1, h: 1, d: 0.1 }, surface_normal: null },
    ];
    const op = Pm.coverOpeningsFromFittings(fits);
    const g = Pm.buildOuterCoverPanels(Object.assign({ roofType: 'flat', openings: op }, base));
    const roof = byName(g, 'outer_cover_u0_roof'), rt = tris(roof);
    out.coverFlat = {
      roofOpenings: op.roof.length, holes: roof.userData.holes,
      inHole: rt.filter(t => inBox(t, 4.65, 5.35, 5.9, 7, 3, 17)).length,
      beside: rt.filter(t => inBox(t, 1, 4, 5.9, 7, 3, 17)).length,
      riser: rt.filter(t => t[0] < 0.01 && t[1] > 3 && t[1] < 6).length,
    };
  }
  {   // 마구리 창 윗변이 처마보다 높다(아치 가장자리) → 구멍 윗변을 그 x 구간의 단면 높이 아래로 자른다. 겹치는 창 둘 = 구멍 하나.
    const fits = [
      { kind: 'window', position: { x: 1.5, y: 3, z: -0.05 }, size: { w: 2, h: 4, d: 0.1 }, surface_normal: [0, 0, -1] },     // y 1~5, x 0.5~2.5
      { kind: 'door', position: { x: 5, y: 1, z: -0.05 }, size: { w: 1, h: 2, d: 0.1 }, surface_normal: [0, 0, -1] },
      { kind: 'door', position: { x: 5.4, y: 1.2, z: -0.05 }, size: { w: 1, h: 2, d: 0.1 }, surface_normal: [0, 0, -1] },     // 앞 문과 겹침
      { kind: 'side_window', position: { x: -0.05, y: 1.8, z: 5 }, size: { w: 3, h: 1.2, d: 0.1 }, surface_normal: [-1, 0, 0] },
      { kind: 'side_window', position: { x: -0.05, y: 2.0, z: 6 }, size: { w: 3, h: 1.2, d: 0.1 }, surface_normal: [-1, 0, 0] }, // 위 창과 겹침
    ];
    const op = Pm.coverOpeningsFromFittings(fits);
    const g = Pm.buildOuterCoverPanels(Object.assign({ roofType: 'arch', openings: op }, base));
    const cap = byName(g, 'outer_cover_u0_y_neg'), p = cap.geometry.attributes.position;
    let maxHoleY = -Infinity, nan = false;
    for (let i = 0; i < p.count; i++) { if (!isFinite(p.getX(i)) || !isFinite(p.getY(i))) nan = true; }
    // 구멍 꼭짓점은 정확히 x=0.5·2.5 에 있다(바깥 윤곽의 베지에 분할점은 그 x 에 떨어지지 않는다). 그중 y 최대 = 잘린 윗변
    for (let i = 0; i < p.count; i++) { const x = p.getX(i), y = p.getY(i); if ((Math.abs(x - 0.5) < 1e-6 || Math.abs(x - 2.5) < 1e-6) && y > 0.5) maxHoleY = Math.max(maxHoleY, y); }
    // 아치(3차 베지에) x=0.5 의 높이 — 18분할 폴리라인은 그보다 약간 낮다
    const archY = (x) => { let lo = 0, hi = 1; for (let k = 0; k < 40; k++) { const t = (lo + hi) / 2, u = 1 - t; const xx = 3 * u * t * t * 10 + t * t * t * 10; if (xx < x) lo = t; else hi = t; } const t = (lo + hi) / 2, u = 1 - t; return u * u * u * 3 + 3 * u * u * t * 6 + 3 * u * t * t * 6 + t * t * t * 3; };
    out.coverCap = {
      caps: op.caps.length, holes: cap.userData.holes, nan, triangles: cap.geometry.index ? cap.geometry.index.count / 3 : 0,
      maxHoleY, archYAtEdge: archY(0.5),
      wallHoles: byName(g, 'outer_cover_u0_x_neg').userData.holes, wallRects: op.walls.length,
    };
  }
  {   // gable2(한 동에 박공 둘) 천창: 첫 경사(t=0.15)에 구멍, 그 옆 경사는 그대로
    const n = Math.sqrt(3 * 3 + 2.5 * 2.5);
    const fits = [{ kind: 'window', position: { x: 1.5, y: 4.8, z: 10 }, size: { w: 15, h: 1.0, d: 0.06 }, surface_normal: [-3 / n, 2.5 / n, 0] }];
    const op = Pm.coverOpeningsFromFittings(fits);
    const g = Pm.buildOuterCoverPanels(Object.assign({ roofType: 'gable2', openings: op }, base));
    const roof = byName(g, 'outer_cover_u0_roof'), rt = tris(roof);
    out.coverGable2 = { holes: roof.userData.holes,
      inHole: rt.filter(t => inBox(t, 1.3, 1.7, 0, 10, 3, 17)).length,
      nextSlope: rt.filter(t => inBox(t, 3, 4.5, 0, 10, 3, 17)).length,
      lowNearValley: rt.filter(t => inBox(t, 3, 7, 0, 4.5, 3, 17)).length, maxY: Math.max(...rt.map(t => t[1])) };
  }
  {   // 멀티 베이(연동 2칸, 간격 1 m, 박공): 둘째 칸 천창 → 그 칸만 뚫리고 첫째 칸·홈통 띠는 그대로
    const sn = Math.sqrt(34);
    const fits = [{ kind: 'window', position: { x: 14, y: 4.8, z: 10 }, size: { w: 15, h: 1.8, d: 0.06 }, surface_normal: [-3 / sn, 5 / sn, 0] }];
    const op = Pm.coverOpeningsFromFittings(fits);
    const g = Pm.buildOuterCoverPanels(Object.assign({}, base, { roofType: 'gable', openings: op, meshBayCount: 2, unitWidth: 21, effectiveSpacing: 1 }));
    const roof = byName(g, 'outer_cover_u0_roof'), rt = tris(roof);
    out.coverMultiBay = { holes: roof.userData.holes,
      inHole: rt.filter(t => inBox(t, 13.4, 14.6, 0, 10, 3, 17)).length,
      bay0: rt.filter(t => inBox(t, 2.4, 3.6, 0, 10, 3, 17)).length,
      gutter: rt.filter(t => inBox(t, 10.05, 10.95, 2.9, 3.1, 0, 20)).length,
      maxX: (() => { const p = roof.geometry.attributes.position; let m = -Infinity; for (let i = 0; i < p.count; i++) m = Math.max(m, p.getX(i)); return m; })() };
  }
  {   // 동 간격 0.4 m 인 두 동: 틈에 놓인 창(x=10.1)은 가까운 동의 벽 하나만 뚫는다(허용 오차 < 간격/2)
    const fits = [{ kind: 'window', position: { x: 10.1, y: 1.5, z: 10 }, size: { w: 2, h: 1, d: 0.3 }, surface_normal: [1, 0, 0] }];
    const op = Pm.coverOpeningsFromFittings(fits);
    const g = Pm.buildOuterCoverPanels(Object.assign({}, base, { roofType: 'arch', openings: op, unitCount: 2, effectiveSpacing: 0.4 }));
    out.coverGap = { u0pos: byName(g, 'outer_cover_u0_x_pos').userData.holes, u1neg: byName(g, 'outer_cover_u1_x_neg').userData.holes,
      u1pos: byName(g, 'outer_cover_u1_x_pos').userData.holes };
  }
  {   // 겹치는 천창 둘(아치) → 지붕 구멍 하나로 병합, 테두리 선 하나 분
    const fits = [
      { kind: 'window', position: { x: 3.0, y: 4.89, z: 8 }, size: { w: 6, h: 1.0, d: 0.06 }, surface_normal: [-0.229, 0.973, 0] },
      { kind: 'window', position: { x: 3.0, y: 4.89, z: 12 }, size: { w: 6, h: 1.0, d: 0.06 }, surface_normal: [-0.229, 0.973, 0] },
    ];
    const op = Pm.coverOpeningsFromFittings(fits);
    const g = Pm.buildOuterCoverPanels(Object.assign({ roofType: 'arch', openings: op }, base));
    const lines = byName(g, 'outer_cover_u0_roof_holes');
    const lp = lines.geometry.attributes.position; let inner = 0;
    for (let i = 0; i < lp.count; i += 2) { const z = (lp.getZ(i) + lp.getZ(i + 1)) / 2; if (Math.abs(lp.getZ(i) - lp.getZ(i + 1)) < 1e-6 && z > 5.5 && z < 14.5) inner++; }
    out.coverRoofMerge = { rects: op.roof.length, holes: byName(g, 'outer_cover_u0_roof').userData.holes, innerZLines: inner };
  }
  {   // 시설 전체(buildFacilityMesh, 지도가 쓰는 경로): 아치 천창 1 + 측창 1 → 판 이름·구멍 수
    const fac = {
      unique_id: 'h', bay_count: 1, structure: 'single',
      geometry_3d: { span_width_m: 10, eave_height_m: 3, ridge_height_m: 6, length_m: 20, roof_type: 'arch' },
      envelope: { layers: [{ id: 'outer', type: 'full', role: 'outer', cover: 'vinyl_single' }] },
      fittings: [
        { id: 'sw', kind: 'side_window', position: { x: -0.05, y: 1.8, z: 10 }, size: { w: 3, h: 1.2, d: 0.1 }, surface_normal: [-1, 0, 0] },
        { id: 'rv', kind: 'window', position: { x: 3.0, y: 4.89, z: 10 }, size: { w: 6, h: 1.0, d: 0.06 }, surface_normal: [-0.229, 0.973, 0] },
      ],
    };
    const g = A.buildFacilityMesh(fac, {});
    const names = []; g.traverse(o => { if (o.isMesh && o.name.indexOf('outer_cover_') === 0) names.push(o.name); });
    const roof = g.getObjectByName('outer_cover_u0_roof'), rt = tris(roof);
    out.coverFacility = {
      names: names.sort(), negHoles: g.getObjectByName('outer_cover_u0_x_neg').userData.holes, roofHoles: roof.userData.holes,
      inHole: rt.filter(t => inBox(t, 2.7, 3.3, 0, 10, 7.5, 12.5)).length,
      beside: rt.filter(t => inBox(t, 4.5, 7, 0, 10, 7.5, 12.5)).length,
      legacyShell: !!g.getObjectByName('outer_cover_0'),
    };
  }

  // ── 레이아웃형 시설(layout) 외피 개구 ────────────────────────────────────
  {
    const LM = window.AoTLayoutMesh;
    const MATS = { cover: () => new THREE.MeshBasicMaterial(), floor: () => new THREE.MeshBasicMaterial() };
    const mk = (layout, fittings) => LM.build(layout, { MAT: MATS, buildShape: window.AoTParametric.buildMultiSpanShape, fittings });
    const mesh = (lm, name) => lm.shell.getObjectByName(name);
    const holesOf = (lm, name) => { const m = mesh(lm, name); return m ? m.userData.holes : null; };
    const area = (m) => {
      const p = m.geometry.attributes.position, v = (k) => new THREE.Vector3(p.getX(k), p.getY(k), p.getZ(k));
      let a = 0;
      for (let i = 0; i < p.count; i += 3) a += v(i + 1).sub(v(i)).cross(v(i + 2).sub(v(i))).length() / 2;
      return a;
    };
    const nanIn = (m) => Array.from(m.geometry.attributes.position.array).some(v => !isFinite(v));
    const L1 = [{ id: 'g', elevation_m: 0, height_m: 3 }];
    const L2 = L1.concat([{ id: 'u', elevation_m: 3, height_m: 3 }]);
    const rectBlock = (id, lv, x0, z0, x1, z1, roof) => ({ id, level_id: lv, outline: [[x0, z0], [x1, z0], [x1, z1], [x0, z1]], roof: roof || { type: 'flat' } });

    {   // 박공(용마루 z) 10×20: 측벽 창·박공 끝 창(지붕선에서 멈춤)·경사 천창 각 1, 공중에 뜬 상자는 아님
      const layout = { levels: L1, blocks: [rectBlock('b', 'g', 0, 0, 10, 20, { type: 'gable', rise_m: 2, ridge_axis: 'z' })] };
      const fit = [
        { id: 'sw', kind: 'side_window', position: { x: -0.05, y: 1.5, z: 10 }, size: { w: 2, h: 1, d: 0.1 }, surface_normal: [-1, 0, 0] },
        { id: 'ew', kind: 'window', position: { x: 1, y: 3, z: -0.05 }, size: { w: 2, h: 4, d: 0.1 }, surface_normal: [0, 0, -1] },
        { id: 'rv', kind: 'window', position: { x: 2.5, y: 4, z: 10 }, size: { w: 2, h: 1, d: 0.06 }, surface_normal: [-0.371, 0.928, 0] },
        { id: 'fl', kind: 'window', position: { x: 5, y: 1.5, z: 5 }, size: { w: 2, h: 1, d: 0.06 }, surface_normal: [-0.371, 0.928, 0] },
      ];
      const lm = mk(layout, fit), plain = mk(layout, []);
      const wt = tris(mesh(lm, 'outer_cover_b_walls')), ct = tris(mesh(lm, 'outer_cover_b_gable')), rt = tris(mesh(lm, 'outer_cover_b_roof'));
      out.layoutGable = {
        walls: holesOf(lm, 'outer_cover_b_walls'), gable: holesOf(lm, 'outer_cover_b_gable'), roof: holesOf(lm, 'outer_cover_b_roof'),
        plain: [holesOf(plain, 'outer_cover_b_walls'), holesOf(plain, 'outer_cover_b_gable'), holesOf(plain, 'outer_cover_b_roof')],
        wallInHole: wt.filter(t => inBox(t, -0.1, 0.1, 1.1, 1.9, 9.1, 10.9)).length,
        wallBeside: wt.filter(t => inBox(t, -0.1, 0.1, 0, 3, 11.5, 20)).length,
        capInHole: ct.filter(t => inBox(t, 0.1, 1.9, 1.1, 2.9, -0.1, 0.1)).length,
        capMaxY: Math.max.apply(null, Array.from(mesh(lm, 'outer_cover_b_gable').geometry.attributes.position.array).filter((v, i) => i % 3 === 1)),
        wallArea: area(mesh(lm, 'outer_cover_b_walls')), plainWallArea: area(mesh(plain, 'outer_cover_b_walls')),
        capNaN: nanIn(mesh(lm, 'outer_cover_b_gable')),
        roofInHole: rt.filter(t => inBox(t, 2.1, 2.9, 3.5, 4.5, 9.1, 10.9)).length,
        roofOtherSlope: rt.filter(t => inBox(t, 5.5, 10, 3, 5.1, 9.1, 10.9)).length,
        roofLines: !!lm.shell.getObjectByName('layout_roof_holes_b'),
        roofMaxY: Math.max.apply(null, rt.map(t => t[1])),
      };
    }
    {   // 평지붕 자유 평면(사선 벽): 사선 벽 창 1·평지붕 천창 1
      const ring = [[0, 0], [10, 0], [14, 8], [0, 8]];
      const L = Math.hypot(4, 8), n = [8 / L, -4 / L];      // (10,0)→(14,8) 의 바깥(+x 쪽)
      const layout = { levels: L1, blocks: [{ id: 'd', level_id: 'g', outline: ring, roof: { type: 'flat' } }] };
      const fit = [
        { id: 'dw', kind: 'window', position: { x: 12 + n[0] * 0.05, y: 1.5, z: 4 + n[1] * 0.05 }, size: { w: 2, h: 1, d: 0.1 }, surface_normal: [n[0], 0, n[1]] },
        { id: 'sk', kind: 'window', position: { x: 5, y: 3.03, z: 3 }, size: { w: 2, h: 2, d: 0.06 }, surface_normal: [0, 1, 0] },
      ];
      const lm = mk(layout, fit);
      const wt = tris(mesh(lm, 'outer_cover_d_walls')), rt = tris(mesh(lm, 'outer_cover_d_roof'));
      out.layoutFree = {
        walls: holesOf(lm, 'outer_cover_d_walls'), roof: holesOf(lm, 'outer_cover_d_roof'),
        wallInHole: wt.filter(t => Math.hypot(t[0] - 12, t[2] - 4) < 0.8 && t[1] > 1.1 && t[1] < 1.9).length,
        roofInHole: rt.filter(t => inBox(t, 4.1, 5.9, 2.9, 3.1, 2.1, 3.9)).length,
        roofKept: rt.filter(t => inBox(t, 7, 13, 2.9, 3.1, 0, 8)).length,
      };
    }
    {   // 맞닿은 두 덩어리의 공유 변·위아래 층: 창은 제 구간 하나만 뚫는다
      const layout = { levels: L2, blocks: [
        rectBlock('a', 'g', 0, 0, 10, 10), rectBlock('c', 'g', 10, 0, 20, 10), rectBlock('t', 'u', 0, 0, 10, 10)] };
      const fit = [
        { id: 'sh', kind: 'window', position: { x: 10, y: 1.5, z: 5 }, size: { w: 2, h: 1, d: 0.1 }, surface_normal: [1, 0, 0] },
        { id: 'up', kind: 'window', position: { x: -0.05, y: 4.5, z: 5 }, size: { w: 2, h: 1, d: 0.1 }, surface_normal: [-1, 0, 0] },
      ];
      const lm = mk(layout, fit);
      out.layoutStack = { a: holesOf(lm, 'outer_cover_a_walls'), c: holesOf(lm, 'outer_cover_c_walls'), t: holesOf(lm, 'outer_cover_t_walls') };
      // 같은 외피 종류는 재질 하나, dispose() 는 이 빌드의 재질을 모두 놓는다
      const mats = new Set(); let disposed = 0;
      lm.shell.traverse(o => { if (o.material) mats.add(o.material); });
      if (lm.floor) mats.add(lm.floor.material);
      mats.forEach(m => m.addEventListener('dispose', () => { disposed++; }));
      const covers = new Set(['a', 'c', 't'].map(id => mesh(lm, 'outer_cover_' + id + '_walls').material));
      lm.dispose();
      out.layoutMats = { coverMats: covers.size, total: mats.size, disposed };
    }
    {   // 아치(용마루 x): 꼭대기 천창(법선 수직 → 폭 X, 높이 Z)
      const layout = { levels: L1, blocks: [rectBlock('r', 'g', 0, 0, 20, 8, { type: 'arch', rise_m: 2, ridge_axis: 'x' })] };
      const lm0 = mk(layout, []);
      const top = Math.max.apply(null, tris(mesh(lm0, 'outer_cover_r_roof')).map(t => t[1]));
      const fit = [{ id: 'ap', kind: 'window', position: { x: 10, y: top + 0.03, z: 4 }, size: { w: 3, h: 1, d: 0.06 }, surface_normal: [0, 1, 0] }];
      const lm = mk(layout, fit), rt = tris(mesh(lm, 'outer_cover_r_roof'));
      out.layoutArchX = {
        roof: holesOf(lm, 'outer_cover_r_roof'),
        inHole: rt.filter(t => inBox(t, 8.6, 11.4, top - 0.3, top + 0.1, 3.6, 4.4)).length,
        alongRidge: rt.filter(t => inBox(t, 12, 20, top - 0.3, top + 0.1, 3.6, 4.4)).length,
      };
    }
    {   // 지도 경로(buildFacilityMesh): 모형 시설도 저장된 창으로 구멍
      const fac = { unique_id: 'lf', layout: { levels: L1, blocks: [rectBlock('m', 'g', 0, 0, 10, 20)] },
        fittings: [{ id: 'mw', kind: 'side_window', position: { x: -0.05, y: 1.5, z: 10 }, size: { w: 2, h: 1, d: 0.1 }, surface_normal: [-1, 0, 0] }] };
      const g = A.buildFacilityMesh(fac, {});
      const w = g.getObjectByName('outer_cover_m_walls');
      out.layoutFacility = { walls: w ? w.userData.holes : null };
    }
  }
}

// ── 열린 창 강조 · 켜짐 색 기본값 · 히터 화살표(시설 가운데) ─────────────────
{
  const root = new THREE.Group();
  const { m, e } = box(root, { id: 'ow', kind: 'side_window', actuator_id: 'u-ow' }, [3, 1.2, 0.1], [0, 1.5, 5], [0, -Math.PI / 2, 0]);
  const base = m.material.color.getHex();
  A.applyRuntime(root, null, st('u-ow', true, 50), { motion: false });
  const on = { panel: m.material.color.getHex(), edge: e.material.color.getHex(), depthTest: e.material.depthTest,
    opacity: e.material.opacity, order: e.renderOrder };
  A.applyRuntime(root, null, st('u-ow', true, 0), { motion: false });     // 켜졌지만 0% = 닫힘
  const zero = { panel: m.material.color.getHex(), depthTest: e.material.depthTest };
  A.applyRuntime(root, null, st('u-ow', false, 0), { motion: false });
  out.openTint = { base, on, zero, off: { panel: m.material.color.getHex(), edge: e.material.color.getHex(),
    depthTest: e.material.depthTest, order: e.renderOrder } };
}
{
  const root = new THREE.Group();
  // 외피: x 0~20, z 0~20 상자 → 가운데 (10, ·, 10)
  const cover = new THREE.Mesh(new THREE.BoxGeometry(20, 4, 20), new THREE.MeshStandardMaterial());
  cover.position.set(10, 2, 10); cover.name = 'outer_cover_0'; root.add(cover);
  // 서쪽 벽(x=0)에 붙인 히터 — 놓은 면의 바깥 법선 -X 를 정면으로 받았다(rotation.y = -90도 → 국소 +Z 가 세계 -X)
  const { m } = box(root, { id: 'ha', kind: 'heater', actuator_id: 'u-ha' }, [0.6, 0.6, 0.4], [0.3, 1, 4], [0, -Math.PI / 2, 0]);
  const baseColor = m.material.color.getHex();
  A.applyRuntime(root, null, st('u-ha', true, null, 'binary'), { motion: false });
  const g = root.getObjectByName('fitting:ha:band');
  root.updateMatrixWorld(true);
  const o = world(g, new THREE.Vector3(0, 0, 0)), tip = world(g, new THREE.Vector3(0, 0, g.userData.len));
  const d = tip.clone().sub(o); const toC = new THREE.Vector3(10, 1, 10).sub(o);
  out.heatArrow = {
    planes: g.children.length, len: g.userData.len, flatY: Math.abs(d.y) < 1e-6,
    cos: d.clone().setY(0).normalize().dot(toC.setY(0).normalize()),
    bodyOn: m.material.color.getHex(), emissiveOn: m.material.emissive.getHex(),
    arrowColor: g.children[0].material.color.getHex(), arrowOpacity: g.children[0].material.opacity,
  };
  A.applyRuntime(root, null, st('u-ha', false, 0, 'binary'), { motion: false });
  out.heatArrow.offHidden = g.visible === false;
  out.heatArrow.bodyOff = m.material.color.getHex() === baseColor;
  out.heatArrow.emissiveOff = m.material.emissive.getHex();
}

// ── 상태 글자 자리: 벽 설비는 끝 벽마다, 그 밖은 가운데에 가까운 설비 자리 (common/sensor-label.js) ──
globalThis.document = globalThis.document || {};
vm.runInThisContext(fs.readFileSync(path.join(dir, '..', '..', 'common', 'sensor-label.js'), 'utf8'));
{
  const G = window.AoTSensorLabel.equipGroups;
  const at = (g) => [g.anchor.x, g.anchor.y, g.anchor.z];
  // 연동 3동(동 폭 8m) 천창 — 한 출력이 동마다 하나씩
  const roof = [0, 1, 2].map(i => ({ id: 'r' + i, kind: 'window', actuator_id: 'o-roof', position: { x: 4 + 8 * i, y: 4, z: 15 } }));
  // 대칭 복제 측창 — 양쪽 벽(x=0, x=24), 길이 방향 두 짝씩
  const side = [[-0.05, 10, -1], [-0.05, 20, -1], [24.05, 10, 1], [24.05, 20, 1]].map((p, i) =>
    ({ id: 's' + i, kind: 'side_window', actuator_id: 'o-side', position: { x: p[0], y: 1.5, z: p[1] }, surface_normal: [p[2], 0, 0] }));
  // 한 벽에만 있는 측창 줄
  const west = [5, 15, 25].map((z, i) => ({ id: 'w' + i, kind: 'side_window', actuator_id: 'o-west', position: [-0.05, 1.2, z], surface_normal: [-1, 0, 0] }));
  // 연동 3동(동 폭 8m)의 측창 — 동마다 양쪽 벽에 복제돼 안쪽 벽(x=8, 16)에도 놓였다. 법선이 없는 측창 하나는 따로.
  const conn = [];
  [0, 8, 16].forEach((x0, b) => {
    conn.push({ id: 'cw' + b, kind: 'side_window', actuator_id: 'o-conn', position: { x: x0 - 0.05, y: 1.5, z: 10 }, surface_normal: [-1, 0, 0] });
    conn.push({ id: 'ce' + b, kind: 'side_window', actuator_id: 'o-conn', position: { x: x0 + 8.05, y: 1.8, z: 10 }, surface_normal: [1, 0, 0] });
  });
  conn.push({ id: 'cr', kind: 'window', actuator_id: 'o-conn', position: { x: 12, y: 5, z: 10 }, surface_normal: [0, 1, 0] });   // 같은 출력의 천창
  // 복제한 단동 두 채(x 0~8, 10~18) — 마주 보는 벽(x=8, 10)이 아니라 좌우 끝 벽(x=0, 18)
  const twin = [[-0.05, -1], [8.05, 1], [9.95, -1], [18.05, 1]].map((p, i) =>
    ({ id: 't' + i, kind: 'side_window', actuator_id: 'o-twin', position: { x: p[0], y: 1.5, z: 5 + i }, surface_normal: [p[1], 0, 0] }));
  const bare = [{ id: 'b1', kind: 'side_window', actuator_id: 'o-bare', position: { x: 0, y: 1, z: 2 } },
                { id: 'b2', kind: 'side_window', actuator_id: 'o-bare', position: { x: 10, y: 1, z: 4 } }];
  const door = { id: 'd', kind: 'door', actuator_id: 'o-door', position: { x: 12, y: 1, z: 30.05 } };
  const fans = [{ id: 'f1', kind: 'fan', position: { x: 2, y: 2, z: 5 } }, { id: 'f2', kind: 'fan', position: { x: 22, y: 3, z: 25 } }];
  const noise = [{ id: 'sn', kind: 'sensor', actuator_id: 'o-roof', position: { x: 99, y: 9, z: 99 } }, { id: 'np', kind: 'window', actuator_id: 'o-roof' }];
  const gs = G([].concat(roof, side, west, [door], fans, noise, conn, twin, bare));
  const all = (g) => g.anchors.map(a => [a.x, a.y, a.z]);
  const by = {}; gs.forEach(g => { by[g.key] = { at: at(g), all: all(g), n: g.fittings.length, first: g.fittings[0].id }; });
  out.equipGroups = { keys: gs.map(g => g.key), by: by, empty: G(null).length };

  // 같은 벽·같은 높이에 놓인 서로 다른 출력(측면 보온커튼과 그 바깥 측창 — 6동 연동 육묘장 배치 그대로).
  // 커튼은 벽(x=0.12·41.88)과 천장에, 측창은 그 바깥(x=-1.02·43.03), 천창은 지붕 위.
  const curt = [[41.88, 2.25, 1], [0.12, 2.25, -1], [41.88, 0.75, 1], [0.12, 0.75, -1]].map((p, i) =>
    ({ id: 'cu' + i, kind: 'curtain', actuator_id: 'o-curt', position: [p[0], p[1], 19], surface_normal: [p[2], 0, 0] }))
    .concat([3.5, 10.5, 17.5, 24.5, 31.5, 38.5].map((x, i) => ({ id: 'cc' + i, kind: 'curtain', actuator_id: 'o-curt', position: [x, 2.54, 19] })));
  const roofW = [2.1, 9.1, 16.1, 23.1, 30.1, 37.1].map((x, i) =>
    ({ id: 'rw' + i, kind: 'window', actuator_id: 'o-rw', position: [x, 4.89, 19], surface_normal: [-0.3186, 0.9479, 0] }));
  const sideW = [[43.03, 2.25, 1], [-1.02, 2.25, -1], [43.03, 0.75, 1], [-1.02, 0.75, -1]].map((p, i) =>
    ({ id: 'sw' + i, kind: 'side_window', actuator_id: 'o-sw', position: [p[0], p[1], 19], surface_normal: [p[2], 0, 0] }));
  const gs2 = G([].concat(curt, roofW, sideW));
  const st = {}; gs2.forEach(g => { st[g.key] = g.anchors.map(a => [a.x, a.stack]); });
  // 위의 묶음들: 같은 서쪽 벽 가운데(z=15)에 놓인 o-side·o-west 만 쌓이고 떨어진 자리는 모두 0
  const st1 = {}; gs.forEach(g => { st1[g.key] = g.anchors.map(a => a.stack); });
  out.equipStack = { st: st, first: st1 };
}
console.log(JSON.stringify(out));
