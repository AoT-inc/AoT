// 배관 관경 보조 계산 하네스 — 실제 aot-geo-pipe-diameters.js 를 읽어 돌린다.
// 사용: node geo_pipe_diameters.js <aot-geo-pipe-diameters.js 경로> → JSON 한 줄
'use strict';
const api = require(process.argv[2]);

const M = 1 / 111320;                       // 위도 1 m
const line = (id, sub, x0, x1, dia) => ({ id, sub, coords: [[x0 * M, 0], [x1 * M, 0]], diameter: dia == null ? null : dia });

// 줄기: A(40 m) - 이음 2 m 둘 - B(30 m) 가 한 줄로 이어지고, 중간에 지관 갈림이 있는 구조도 섞는다.
const trunk = [
    line('A', 'pipe_branch', 0, 40), line('38e9-76cc-6730-9d86', 'pipe_branch', 40, 42),
    line('00de-b04f-2ef7-8343', 'pipe_branch', 42.3, 44),      // 끝점이 0.3 m 어긋남 — 허용 안
    line('B', 'pipe_branch', 44, 74),
];
// 갈림: 한 점에 같은 종류 셋 → 거기서 멈춘다
const fork = [line('F1', 'pipe_branch', 0, 20), line('F2', 'pipe_branch', 20, 40), line('F3', 'pipe_branch', 20, 40.5), line('F4', 'pipe_branch', 20, 41)];
// 다른 종류는 건너가지 않는다
const mixed = [line('M1', 'pipe_branch', 0, 20), line('M2', 'pipe_main', 20, 40), line('M3', 'pipe_branch', 40, 60)];
// 1 m 어긋남은 이어진 것으로 보지 않는다
const gap = [line('G1', 'pipe_branch', 0, 20), line('G2', 'pipe_branch', 21, 40)];

const out = {};
out.parse = ['', ' ', '63', '0', '-5', 'abc', '0.5', '1'].map(v => { const r = api.parseDiameter(v); return r.error ? 'err' : (r.empty ? 'empty' : r.value); });
out.chain = api.chainFrom('38e9-76cc-6730-9d86', trunk).sort();
out.chainFromEnd = api.chainFrom('B', trunk).sort();
out.fork = api.chainFrom('F1', fork).sort();
out.forkBranch = api.chainFrom('F2', fork).sort();
out.mixed = api.chainFrom('M1', mixed).sort();
out.gap = api.chainFrom('G1', gap).sort();
out.unknown = api.chainFrom('nope', trunk);
out.shortest = api.pickShortest([{ id: 'long', lengthM: 40 }, { id: 'tiny', lengthM: 2 }, { id: 'mid', lengthM: 9 }]).id;
out.shortestNone = api.pickShortest([]);
const pipes = [line('x', 'pipe_main', 0, 50, 90), line('y', 'pipe_branch', 0, 30), line('z', 'pipe_branch', 0, 2)];
out.rowsEmptyUnknown = api.rowsFor(pipes, null, 'empty', 'long').map(r => r.id);          // 점검을 모르면 관경 칸이 빈 것
out.rowsEmptyServer = api.rowsFor(pipes, new Set(['z']), 'empty', 'long').map(r => r.id); // 서버가 말한 것만
out.rowsEmptyServerFilledSkip = api.rowsFor(pipes, new Set(['x', 'z']), 'empty', 'long').map(r => r.id); // 이미 입력했으면 뺀다
out.rowsAll = api.rowsFor(pipes, null, 'all', 'long').map(r => r.id);
out.rowsEmptyFirst = api.rowsFor(pipes, null, 'all', 'empty').map(r => r.id);
out.tol = api.ENDPOINT_TOL_M;

// ── 지형 길이(T4): 상태 4종 × 행 문구 ──
const tr = (s) => s;
const area = (state, pipes) => ({ terrain: { state, pipes } });
const P = { a: { horizontal_m: 100, slant_m: 104.2 }, b: { horizontal_m: 55, slant_m: null } };
out.terrainNone = [api.terrainFrom(null).state, api.terrainFrom({ areas: [{}] }).state, api.terrainFrom({ areas: [area('none', P)] }).state];
out.textNone = api.lengthText(api.terrainFrom(null), 'a', 100, tr);
const t = (state) => api.terrainFrom({ areas: [area(state, P)] });
out.textWarming = ['a', 'b', 'zzz'].map(id => api.lengthText(t('warming'), id, 7, tr));
out.textPartial = ['a', 'b', 'zzz'].map(id => api.lengthText(t('partial'), id, 7, tr));
out.textReady = ['a', 'b'].map(id => api.lengthText(t('ready'), id, 7, tr));
out.merge = (() => { const m = api.terrainFrom({ areas: [area('warming', { a: P.a }), area('ready', { a: { horizontal_m: 1, slant_m: 2 }, c: P.b })] });
    return { state: m.state, a: m.pipes.get('a').horizontal_m, c: m.pipes.has('c') }; })();
console.log(JSON.stringify(out));
