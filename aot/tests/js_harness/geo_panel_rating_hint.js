// 설계 패널 부품 정격 입력의 '값 출처' 문구 하네스 — 실제 aot-geo-panel.js 를 읽어 `_appendPartRatings` 가 만든 마크업 위에서
// 입력 처리기를 돌린다. DOM 은 이 하네스의 작은 모의다(태그·class·id·텍스트만): 문구를 찾는 선택자가 실제 마크업에 닿는지가 시험 대상이다.
// 사용: node geo_panel_rating_hint.js <aot-geo-panel.js 경로> → JSON 한 줄
'use strict';
const fs = require('fs');
const vm = require('vm');

class El {
    constructor(tag, attrs) { this.tagName = tag; this.attrs = attrs || {}; this.children = []; this.parent = null; this.text = ''; this.listeners = {}; this._value = this.attrs.value; }
    get className() { return this.attrs.class || ''; }
    set className(v) { this.attrs.class = v; }
    get id() { return this.attrs.id; }
    get value() { return this._value == null ? '' : String(this._value); }
    set value(v) { this._value = v; }
    get textContent() { return this.text + this.children.map(c => c.textContent).join(''); }
    set textContent(v) { this.text = String(v); this.children = []; }
    get firstChild() { return this.children[0] || null; }
    get childrenCount() { return this.children.length; }
    set innerHTML(html) { this.children = []; this.text = ''; parse(html, this); }
    addEventListener(name, fn) { (this.listeners[name] = this.listeners[name] || []).push(fn); }
    fire(name) { (this.listeners[name] || []).forEach(fn => fn.call(this, {})); }
    insertBefore(node) { node.parent = this; this.children.unshift(node); }
    classes() { return this.className.split(/\s+/).filter(Boolean); }
    matches(simple) {
        if (simple[0] === '#') return this.id === simple.slice(1);
        if (simple[0] === '.') return this.classes().includes(simple.slice(1));
        return this.tagName === simple;
    }
    closest(sel) { for (let e = this; e; e = e.parent) if (e.matches(sel)) return e; return null; }
    all(out) { this.children.forEach(c => { out.push(c); c.all(out); }); return out; }
    querySelector(sel) {
        const parts = sel.split(/\s+/);
        const last = parts[parts.length - 1];
        for (const e of this.all([])) {
            if (!e.matches(last)) continue;
            let ok = true, at = e.parent;
            for (let i = parts.length - 2; i >= 0 && ok; i--) {
                while (at && at !== this.parent && !at.matches(parts[i])) at = at.parent;
                ok = !!at && at !== this.parent;
                if (ok) at = at.parent;
            }
            if (ok) return e;
        }
        return null;
    }
}

function parse(html, root) {
    const VOID = new Set(['input', 'br', 'img']);
    const re = /<(\/?)([a-zA-Z][a-zA-Z0-9]*)([^>]*)>|([^<]+)/g;
    let m, cur = root;
    while ((m = re.exec(html))) {
        if (m[4] !== undefined) { if (m[4].trim()) cur.text += m[4].trim(); continue; }
        if (m[1]) { if (cur.parent) cur = cur.parent; continue; }
        const attrs = {};
        m[3].replace(/([a-zA-Z-]+)="([^"]*)"/g, (_x, k, v) => { attrs[k] = v; });
        const el = new El(m[2].toLowerCase(), attrs);
        el.parent = cur; cur.children.push(el);
        if (!VOID.has(el.tagName) && !m[3].endsWith('/')) cur = el;
    }
}

const container = new El('div');
const window_ = {
    AOT_EQUIPMENT_PARTS: { ratings: { pump: [{ key: 'rated_lpm', label: 'Rated flow', unit: 'L/min', step: 1 }] } },
    AoTEquipmentPart: { isPart: () => true, labelOf: () => 'Pump', refreshLabel: () => {} },
};
const document_ = { createElement: tag => new El(tag) };
const sandbox = { window: window_, document: document_, _: s => s, console, setTimeout, clearTimeout };
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(process.argv[2], 'utf8') + '\nthis.__Panel = AoTGeoPanel;', sandbox);

const panel = Object.create(sandbox.__Panel.prototype);
const props = { aot_type: 'equipment', sub_type: 'pump', node_id: 'n1' };
panel.selectedFeature = { properties: props };
panel.currentMode = 'equipment';
panel.geoDesign = { dirtyNodeIds: new Set(), saveDesign() {}, activeLayer: null };
panel._partDeviceHtml = () => '';
let dirty = 0;
panel._markPartDirty = () => { dirty += 1; };

panel._appendPartRatings(container);
const wrap = container.children[0];
const input = wrap.querySelector('#part-rating-rated_lpm');
const hintOf = () => {
    const row = input.closest('.aot-modal-option-row');
    const h = row && row.querySelector('.aot-modal-option-label .aot-modal-body-text');
    return h ? h.textContent : null;
};
const out = { initial: hintOf() };
input.value = '30'; input.fire('input'); out.afterInput = hintOf(); out.value = props.rated_lpm;
input.value = ''; input.fire('input'); out.afterClear = hintOf(); out.cleared = !('rated_lpm' in props);
out.dirty = dirty;
// 다시 골랐을 때(저장된 값으로 다시 그림)
props.rated_lpm = 12;
const again = new El('div'); panel._appendPartRatings(again);
const row2 = again.children[0].querySelector('#part-rating-rated_lpm').closest('.aot-modal-option-row');
out.reselected = row2.querySelector('.aot-modal-option-label .aot-modal-body-text').textContent;
console.log(JSON.stringify(out));
