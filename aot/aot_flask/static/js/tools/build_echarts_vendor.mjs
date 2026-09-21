/**
 * build_echarts_vendor.mjs — Apache ECharts 맞춤 빌드를 vendor/ 에 만든다.
 *
 *   cd aot/aot_flask/static/js && node tools/build_echarts_vendor.mjs
 *
 * 왜 맞춤 빌드인가: 배포판 전체(echarts.min.js)는 gzip 368KB 인데, AoT 가 쓰는
 * 차트·컴포넌트만 담으면 그 3분의 2 쯤이 된다. 공식 CDN 에 이 조합의 파일은 없으므로
 * 위젯 의존성처럼 "없으면 받아 설치"로 둘 수 없다 — 산출물을 저장소에 넣고 이
 * 스크립트로 다시 만든다(Apache-2.0 이라 함께 배포할 수 있다).
 *
 * 하는 일:
 *   1. 임시 폴더에 echarts@VERSION 을 npm 으로 받는다(zrender·tslib 는 따라온다).
 *   2. 아래 USE 목록만 esbuild 로 묶어 window.echarts 를 정의하는 IIFE 로 만든다.
 *   3. 라이선스 고지 파일(ECharts LICENSE·NOTICE, 포함된 d3 코드의 LICENSE-d3,
 *      zrender LICENSE)을 산출물 옆에 복사한다.
 *
 * 목록을 바꿨으면 THIRD-PARTY-LICENSES.md 의 ECharts 항목도 같이 고칠 것.
 * esbuild 는 이 폴더의 node_modules 에서 온다(npm run install:all).
 */
import { execFileSync } from 'node:child_process';
import { copyFileSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import * as esbuild from 'esbuild';

const VERSION = '6.1.0';
const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const OUT_DIR = join(ROOT, 'vendor', `echarts-${VERSION}`);
const OUT = join(OUT_DIR, 'echarts.aot.min.js');

// AoT 가 쓰는 것. 시계열·게이지·이벤트 표시 화면을 덮는다.
const USE = {
  'echarts/charts': ['LineChart', 'BarChart', 'ScatterChart', 'GaugeChart'],
  'echarts/components': [
    'GridComponent',          // 직교 좌표
    'DataZoomComponent',      // 하단 미니맵 슬라이더 + 끌어 확대(navigator 대체)
    'TooltipComponent',
    'AxisPointerComponent',   // 세로 십자선(crosshair)
    'LegendComponent',
    'MarkLineComponent',      // 기준선(plotLines)
    'MarkAreaComponent',      // 구간 음영(plotBands, 야간 음영)
    'MarkPointComponent',     // 이벤트 표시(flags)
    'GraphicComponent',       // 단위 제목(axisAdjust)
    'ToolboxComponent'        // PNG 저장(exporting)
  ],
  'echarts/renderers': ['CanvasRenderer']
};

const names = Object.values(USE).flat();
const entry =
  "import * as echarts from 'echarts/core';\n" +
  Object.entries(USE).map(([mod, list]) => `import { ${list.join(', ')} } from '${mod}';`).join('\n') +
  `\necharts.use([${names.join(', ')}]);\n` +
  'window.echarts = echarts;\n';

const tmp = mkdtempSync(join(tmpdir(), 'aot-echarts-'));
try {
  execFileSync('npm', ['install', '--no-save', '--no-package-lock', '--no-audit', '--no-fund',
                       '--prefix', tmp, `echarts@${VERSION}`], { stdio: 'inherit' });
  const nm = join(tmp, 'node_modules');
  const ver = (p) => JSON.parse(readFileSync(join(nm, p, 'package.json'), 'utf8')).version;
  if (ver('echarts') !== VERSION) throw new Error(`echarts ${ver('echarts')} != ${VERSION}`);

  const banner =
    '/*! Apache ECharts ' + VERSION + ' — AoT 맞춤 빌드 (tools/build_echarts_vendor.mjs)\n' +
    ' * Licensed under the Apache License, Version 2.0.\n' +
    ' * 고지 전문: static/js/vendor/echarts-' + VERSION + '/ 의 LICENSE, NOTICE,\n' +
    ' *   LICENSE-zrender (zrender ' + ver('zrender') + ', BSD-3-Clause),\n' +
    ' *   LICENSE-d3 (d3.js 에서 온 코드, BSD-3-Clause). tslib ' + ver('tslib') + ' (0BSD) 포함.\n' +
    ' * 담은 것: ' + names.join(', ') + '\n */';

  const res = await esbuild.build({
    stdin: { contents: entry, resolveDir: tmp, sourcefile: 'echarts-aot-entry.js' },
    bundle: true,
    minify: true,
    format: 'iife',
    target: 'es2017',
    legalComments: 'none',
    banner: { js: banner },
    write: false,
    logLevel: 'error'
  });
  mkdirSync(OUT_DIR, { recursive: true });
  writeFileSync(OUT, res.outputFiles[0].text);

  copyFileSync(join(nm, 'echarts', 'LICENSE'), join(OUT_DIR, 'LICENSE'));
  copyFileSync(join(nm, 'echarts', 'NOTICE'), join(OUT_DIR, 'NOTICE'));
  copyFileSync(join(nm, 'echarts', 'licenses', 'LICENSE-d3'), join(OUT_DIR, 'LICENSE-d3'));
  copyFileSync(join(nm, 'zrender', 'LICENSE'), join(OUT_DIR, 'LICENSE-zrender'));

  console.log(`echarts ${VERSION} (zrender ${ver('zrender')}) -> ${OUT} ` +
              `(${(res.outputFiles[0].contents.length / 1024).toFixed(1)} KB)`);
} finally {
  rmSync(tmp, { recursive: true, force: true });
}
