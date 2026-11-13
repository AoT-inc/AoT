// 압력 표시 하네스 — 실제 aot-geo-water-pressure.js 를 읽어 돌린다.
// 사용: node geo_water_pressure.js <aot-geo-water-pressure.js 경로> → JSON 한 줄
'use strict';
const api = require(process.argv[2]);
const tr = (s) => s;                                   // 번역 없이 영어 원문

const full = { level: 'L1', network: 0, bar_min: 1.73, bar_max: 2.41, pump_lpm: 396.7, pump_head_m: 32.04,
    flow_ratio_min: 0.87, worst_nozzle: 'n-7', assumptions: ['elevation-flat'] };
const partial = Object.assign({}, full, { level: 'L1-partial', bound: 'flow-upper', excluded_ratio: 0.115, excluded_m: 21.3,
    missing_pipes: 4, diameter_ratio: 0.885, missing: [{ pipe: 'a', length_m: 2 }],
    warn: ['source-over-demand'], source_lpm: 290, source_ratio: 0.731 });
const none = { level: 'L0', network: 1, why: ['no-pump', 'pipe-diameter-unknown', 'nozzle-flow-unknown', 'network-loop'], missing_pipes: 3 };
const perfect = Object.assign({}, full, { flow_ratio_min: 1.0 });

const area = (id, name, pressure, circuits) => ({ id, name, pressure, circuits: circuits || [] });
const report = (areas) => ({ areas });

const out = {};
out.describeFull = api.describe(full);
out.describePartial = api.describe(partial);
out.describeNone = api.describe(none);
out.perfectHidesWeakest = api.describe(perfect).weakest;
out.noWorstHidesWeakest = api.describe(Object.assign({}, full, { worst_nozzle: undefined })).weakest;
out.empty = [api.render(null, { _: tr }), api.render({ areas: [] }, { _: tr }), api.render({ areas: [area('z', 'Z', [])] }, { _: tr })];

const render = (r) => api.render(r, { _: tr });
out.fullHtml = render(report([area('z1', 'Zone 1', [full])]));
out.partialHtml = render(report([area('z1', 'Zone 138-3-1', [partial])]));
out.noneHtml = render(report([area('z2', 'Zone 2', [none])]));
out.xss = render(report([area('z"<', '<b>x</b>', [full])]));
out.twoCircuits = render(report([area('z3', 'Zone 3', [Object.assign({}, full, { network: 0 }), Object.assign({}, none, { network: 1 })],
    [{ network: 0, sources: [{ name: 'Well A' }] }, { network: 1, sources: [] }])]));
out.moreReasons = render(report([area('z4', 'Z4', [{ level: 'L0', why: ['no-pump', 'multiple-pumps', 'pump-curve-unknown', 'nozzle-flow-unknown', 'nozzle-pressure-unknown'] }])]));
out.unknownReason = render(report([area('z5', 'Z5', [{ level: 'L0', why: ['brand-new-code'] }])]));
out.translated = api.render(report([area('z1', 'Zone 1', [full])]), { _: (s) => '[' + s + ']' });
// 푼 회로인데 압력이 비어 있다(실데이터: 나주 138-3-2·133-1 — 노즐이 모두 펌프 위쪽) — '계산됨' 으로 쓰면 안 된다
const hollow = { level: 'L1', network: 0, bar_min: null, bar_max: null, pump_lpm: 0, pump_head_m: 47.9, flow_ratio_min: null };
out.hollow = api.describe(hollow);
out.hollowHtml = render(report([area('z6', 'Z6', [hollow])]));

// ── 지형(T4): 상태 4종. 구역 하나(회로 둘) + 구간표 ──
const segs = [
    { pipe: 'm1', s_a: 0, s_b: 0.5, flow_lpm: 612, horizontal_m: 41.0, slant_m: 43.2, grade_pct: 8.4, loss_m: 0.9 },
    { pipe: 'm1', s_a: 0.5, s_b: 1, flow_lpm: 420, horizontal_m: 38.5, slant_m: 39.0, grade_pct: -4.9, loss_m: 0.6 },
    { pipe: 'b1', s_a: 0, s_b: 1, flow_lpm: 48, horizontal_m: 55.0, slant_m: null, grade_pct: null, loss_m: 0.3 },
];
const withSegs = Object.assign({}, full, { segments: segs });
const terr = (state, extra) => Object.assign({ state, version: 'v', cell_m: 4.8, dem_name: 'Hill DEM', computed_at: '2026-11-03T09:00:00+09:00',
    kinds: { m1: 'main', b1: 'branch' }, pipes: {},
    totals: { horizontal_m: 812.4, slant_m: 846.7, unknown_pipes: 0 } }, extra || {});
const withTerrain = (t, brief) => ({ areas: [Object.assign(area('z1', 'Zone 1', [brief || withSegs]), t ? { terrain: t } : {})] });
out.tNoKey = render(withTerrain(null, full));
out.tNone = render(withTerrain({ state: 'none' }, full));
out.tWarming = render(withTerrain(terr('warming', { totals: { horizontal_m: 812.4, slant_m: 812.4, unknown_pipes: 1 }, dem_name: null, computed_at: null }), full));
out.tPartial = render(withTerrain(terr('partial', { totals: { horizontal_m: 812.4, slant_m: 840.1, unknown_pipes: 2 } })));
out.tReady = render(withTerrain(terr('ready')));
out.tReadyOpen = api.render(withTerrain(terr('ready')), { _: tr, open: new Set(['design-pressure-seg-z1-0']) });
out.tReadyNoSegs = render(withTerrain(terr('ready'), full));
out.tNoneLevel = render(withTerrain(terr('ready'), none));
out.tTwoCircuits = render({ areas: [Object.assign(area('z3', 'Zone 3', [Object.assign({}, withSegs, { network: 0 }), Object.assign({}, withSegs, { network: 1 })],
    [{ network: 0, sources: [{ name: 'Well A' }] }, { network: 1, sources: [{ name: 'Well B' }] }]), { terrain: terr('ready') })] });
out.tDescribe = [api.describeTerrain(null), api.describeTerrain({ state: 'none' }), api.describeTerrain(terr('warming')).slant,
    api.describeTerrain(terr('ready')).slant];
out.tTranslated = api.render(withTerrain(terr('ready')), { _: (s) => '[' + s + ']' });
// ── 지형 바꾸기(T6) ──
const cands = [{ id: 'b', name: 'Mapterhorn' }, { id: 'c', name: 'MapTiler' }];
const sw = (extra) => Object.assign({ loaded: true, current: { id: 'a', name: 'AWS' }, candidates: cands, switched: null, pick: null, preview: null }, extra || {});
const swHtml = (x) => api.render(withTerrain(terr('ready')), { _: tr, terrainSwitch: sw(x) });
const swSolo = (x, deps) => api.terrainSwitchHtml(sw(x), tr, deps && deps.open);
const result = {
    totals: { pipes: 3, horizontal_m: 412.0, slant_before: 421.6, slant_after: 430.2, unknown_before: 0, unknown_after: 2 },
    cell_m: 3.0, dem_state: 'partial',
    areas: [{ id: 'z1', name: 'Plot 3', circuits: [{ level_before: 'L1', level_after: 'L1-partial', bar_before: [0.78, 1.12], bar_after: [0.71, 1.07],
        flow_pct_before: 95, flow_pct_after: 91 }] }],
    segments: [{ pipe: 'm1', kind: 'main', s_a: 12, s_b: 47.5, horizontal_m: 35.5, slant_before: 36.1, slant_after: 38.0, grade_before: 8.0, grade_after: 12.1, loss_before: 0.4, loss_after: 0.6 },
        { pipe: 'b1', kind: 'branch', s_a: 0, s_b: 18, horizontal_m: 18.0, slant_before: null, slant_after: null, grade_before: null, grade_after: null, loss_before: null, loss_after: null }],
    segments_total: 7 };
out.swNoKey = render(withTerrain(terr('ready')));
out.swIdle = swSolo();
out.swNothing = [api.terrainSwitchHtml(null, tr), api.terrainSwitchHtml({ loaded: false }, tr),
    api.terrainSwitchHtml(sw({ candidates: [] }), tr), api.terrainSwitchHtml(sw({ current: null, candidates: [] , switched: null}), tr)];
out.swNoCurrent = swSolo({ current: null });
out.swInReport = swHtml();
out.swWarming = swSolo({ pick: 'b', preview: { state: 'warming' } });
out.swReady = swSolo({ pick: 'b', preview: { state: 'ready', result } });
out.swReadyOpen = swSolo({ pick: 'b', preview: { state: 'ready', result } }, { open: new Set(['design-terrain-switch-seg']) });
out.swFailed = ['timeout', 'no-sampler', 'not-found', 'error'].map(r => swSolo({ pick: 'b', preview: { state: 'failed', reason: r } }));
out.swEmpty = swSolo({ pick: 'b', preview: { state: 'empty' } });
out.swSwitched = swSolo({ switched: { from: { id: 'a', name: 'AWS' }, to: { id: 'b', name: 'Mapterhorn' }, at: 1762233600 } });
out.swSwitchedFromNone = swSolo({ current: { id: 'b', name: 'Mapterhorn' }, candidates: [], switched: { from: null, to: { id: 'b', name: 'Mapterhorn' }, at: null } });
out.swXss = swSolo({ candidates: [{ id: 'x"<', name: '<b>x</b>' }], pick: 'x"<', preview: { state: 'warming' } });
out.swNoBefore = swSolo({ pick: 'b', preview: { state: 'ready', result: Object.assign({}, result, { totals: { pipes: 3, horizontal_m: 412.0, slant_before: null, slant_after: 430.2, unknown_before: null, unknown_after: 0 }, areas: [], segments: [] }) } });
out.swTranslated = api.terrainSwitchHtml(sw({ pick: 'b', preview: { state: 'ready', result } }), (s) => '[' + s + ']');
console.log(JSON.stringify(out));
