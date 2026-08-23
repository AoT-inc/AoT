/*
 * aot-user-i18n.js — 사용자 지정 이름의 화면 번역.
 *
 * gettext 는 소스에 박힌 문구만 덮는다. 사용자가 지은 이름(장치명·구역명·
 * 작물명)은 DB 원문 그대로 나오므로, 다국어 계정으로 열면 한 화면에 두 언어가
 * 섞인다. 이 스크립트가 서버 사전을 받아 화면의 그 이름들만 바꾼다.
 *
 * 설계: docs/design/user-string-live-translation.md
 *
 * 두 가지를 절대 하지 않는다.
 *
 * 1. **폼 컨트롤을 건드리지 않는다.** 이름 입력칸에 번역본이 들어간 채로
 *    사용자가 저장하면 DB 의 원문이 번역본으로 덮여 영구 소실된다. 되돌릴 수
 *    없는 데이터 파괴다. input/textarea/select/contenteditable 은 구조적으로
 *    제외한다.
 * 2. **부분 문자열을 바꾸지 않는다.** 텍스트 노드 전체가 사전 키와 정확히
 *    같을 때만 치환한다. 부분 치환은 오탐이 너무 쉽다.
 */
(function () {
  'use strict';

  var DICT = window.AOT_USER_I18N || {};
  var PENDING = new Set(window.AOT_USER_I18N_PENDING || []);
  var LANG = window.AOT_USER_I18N_LANG || null;

  var STORAGE_KEY = 'aot_user_i18n_off';
  var REQUEST_URL = '/api/v1/locale/user_strings/translate';
  var REQUEST_DEBOUNCE_MS = 400;
  var REQUEST_MAX_ITEMS = 100;

  // 번역을 바꿔치기하는 동안 자기 자신이 만든 변경을 다시 처리하지 않기 위한 빗장.
  var applying = false;

  // 되돌리기용 기록: [{node, original}]. 텍스트 노드에는 속성을 달 수 없어
  // 원문을 DOM 에 보관할 수 없으므로 여기에 들고 있는다.
  var textRecords = [];
  var attrRecords = [];

  // 이미 확인한 텍스트 노드 — 다시 훑지 않는다(폴링 위젯에서 특히 중요).
  var seen = new WeakSet();

  // 아직 번역본이 없어서 서버에 물어볼 문자열.
  var askQueue = new Set();
  var askTimer = null;
  var asked = new Set();

  // 번역 대상에서 통째로 빼는 태그. select 는 값이 아니라 표시 텍스트만
  // 바뀌더라도, 그 텍스트로 옵션을 찾는 코드가 있어 위험하다.
  var SKIP_TAGS = {
    SCRIPT: 1, STYLE: 1, NOSCRIPT: 1, TEXTAREA: 1, INPUT: 1, SELECT: 1,
    OPTION: 1, OPTGROUP: 1, CODE: 1, PRE: 1, KBD: 1, SAMP: 1, SVG: 1
  };

  // 사용자 이름이 들어갈 수 있고, 바꿔도 값이 아니라 설명인 속성만 고른다.
  var TRANSLATABLE_ATTRS = ['title', 'aria-label', 'data-original-title'];

  function isOff() {
    try {
      return window.localStorage.getItem(STORAGE_KEY) === '1';
    } catch (e) {
      return false;
    }
  }

  function setOff(off) {
    try {
      if (off) {
        window.localStorage.setItem(STORAGE_KEY, '1');
      } else {
        window.localStorage.removeItem(STORAGE_KEY);
      }
    } catch (e) { /* 저장 못 해도 이번 세션에는 반영된다 */ }
  }

  /* 이 요소 아래는 번역하지 않는다. */
  function isSkipped(el) {
    for (var node = el; node && node.nodeType === 1; node = node.parentElement) {
      if (SKIP_TAGS[node.tagName]) { return true; }
      if (node.isContentEditable) { return true; }
      if (node.getAttribute && (
            node.getAttribute('translate') === 'no' ||
            node.hasAttribute('data-no-translate'))) {
        return true;
      }
      if (node.classList && node.classList.contains('no-translate')) {
        return true;
      }
    }
    return false;
  }

  /* 서버 사전과 같은 정규화 — 앞뒤 공백 제거 + 연속 공백 축약. */
  function normalize(text) {
    return text.replace(/\s+/g, ' ').trim();
  }

  function queueAsk(text) {
    if (asked.has(text) || askQueue.has(text)) { return; }
    askQueue.add(text);
    if (askTimer) { return; }
    askTimer = window.setTimeout(flushAsk, REQUEST_DEBOUNCE_MS);
  }

  function flushAsk() {
    askTimer = null;
    if (!askQueue.size || !LANG) { return; }

    var texts = Array.from(askQueue).slice(0, REQUEST_MAX_ITEMS);
    texts.forEach(function (t) {
      askQueue.delete(t);
      asked.add(t);        // 응답이 비어도 다시 조르지 않는다.
    });

    fetch(REQUEST_URL, {
      method: 'POST',
      credentials: 'same-origin',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({texts: texts})
    }).then(function (res) {
      return res.ok ? res.json() : null;
    }).then(function (data) {
      if (!data || !data.entries) { return; }
      var added = 0;
      Object.keys(data.entries).forEach(function (source) {
        if (!DICT[source]) {
          DICT[source] = data.entries[source];
          PENDING.delete(source);
          added += 1;
        }
      });
      if (added && !isOff()) {
        // 새 번역이 들어왔으니 아직 원문인 자리를 다시 훑는다.
        seen = new WeakSet();
        translateSubtree(document.body);
      }
      if (askQueue.size) { flushAsk(); }
    }).catch(function () {
      /* 번역이 안 되면 원문이 그대로 남는다 — 화면은 정상이다. */
    });
  }

  /* 텍스트 노드 하나를 처리한다. */
  function handleTextNode(node) {
    if (seen.has(node)) { return; }
    seen.add(node);

    var raw = node.nodeValue;
    if (!raw) { return; }

    var text = normalize(raw);
    if (text.length < 2) { return; }

    var translated = DICT[text];
    if (translated) {
      if (translated === raw) { return; }
      textRecords.push({node: node, original: raw});
      node.nodeValue = raw.replace(text, translated);
      return;
    }

    // 아직 번역본이 없다 — 이 이름이 화면에 실제로 보였을 때만 요청한다.
    if (PENDING.has(text)) { queueAsk(text); }
  }

  function handleAttributes(el) {
    for (var i = 0; i < TRANSLATABLE_ATTRS.length; i++) {
      var attr = TRANSLATABLE_ATTRS[i];
      if (!el.hasAttribute(attr)) { continue; }
      var raw = el.getAttribute(attr);
      if (!raw) { continue; }
      var text = normalize(raw);
      if (text.length < 2) { continue; }
      var translated = DICT[text];
      if (translated && translated !== raw) {
        attrRecords.push({el: el, attr: attr, original: raw});
        el.setAttribute(attr, translated);
      } else if (!translated && PENDING.has(text)) {
        queueAsk(text);
      }
    }
  }

  function translateSubtree(root) {
    if (!root || isOff()) { return; }
    if (!Object.keys(DICT).length && !PENDING.size) { return; }

    applying = true;
    try {
      if (root.nodeType === 3) {
        if (root.parentElement && !isSkipped(root.parentElement)) {
          handleTextNode(root);
        }
        return;
      }
      if (root.nodeType !== 1 && root.nodeType !== 9) { return; }
      if (root.nodeType === 1 && isSkipped(root)) { return; }

      var walker = document.createTreeWalker(
        root, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT, {
          acceptNode: function (node) {
            if (node.nodeType === 1) {
              return SKIP_TAGS[node.tagName] || node.isContentEditable ||
                     (node.classList && node.classList.contains('no-translate')) ||
                     node.hasAttribute('data-no-translate') ||
                     node.getAttribute('translate') === 'no'
                ? NodeFilter.FILTER_REJECT
                : NodeFilter.FILTER_ACCEPT;
            }
            return NodeFilter.FILTER_ACCEPT;
          }
        });

      var node;
      while ((node = walker.nextNode())) {
        if (node.nodeType === 3) {
          handleTextNode(node);
        } else {
          handleAttributes(node);
        }
      }

      if (root.nodeType === 1) { handleAttributes(root); }
    } finally {
      applying = false;
    }
  }

  function restoreAll() {
    applying = true;
    try {
      textRecords.forEach(function (rec) {
        if (rec.node && rec.node.isConnected) { rec.node.nodeValue = rec.original; }
      });
      attrRecords.forEach(function (rec) {
        if (rec.el && rec.el.isConnected) { rec.el.setAttribute(rec.attr, rec.original); }
      });
    } finally {
      textRecords = [];
      attrRecords = [];
      seen = new WeakSet();
      applying = false;
    }
  }

  /* DOM 에서 떨어져 나간 기록을 정리한다 — 위젯이 자주 다시 그리는 화면 대비. */
  function pruneRecords() {
    if (textRecords.length > 5000) {
      textRecords = textRecords.filter(function (r) {
        return r.node && r.node.isConnected;
      });
    }
    if (attrRecords.length > 5000) {
      attrRecords = attrRecords.filter(function (r) {
        return r.el && r.el.isConnected;
      });
    }
  }

  var observer = null;
  var queuedRoots = [];
  var frame = null;

  // requestAnimationFrame 이 아니라 타이머를 쓴다. 대시보드는 여러 탭으로 열어
  // 두고 위젯이 폴링으로 계속 DOM 을 바꾸는데, 숨은 탭에서는 rAF 가 멈춘다.
  // 그러면 큐가 하루 종일 쌓였다가 탭을 전환하는 순간 한꺼번에 처리되어
  // 원문이 한 프레임 비친다. 타이머는 숨은 탭에서도 큐를 비운다.
  var SCHEDULE_MS = 16;

  function drainQueue() {
    frame = null;
    var roots = queuedRoots;
    queuedRoots = [];
    for (var i = 0; i < roots.length; i++) {
      if (roots[i] && roots[i].isConnected !== false) { translateSubtree(roots[i]); }
    }
    pruneRecords();
  }

  function startObserver() {
    if (observer || !window.MutationObserver) { return; }
    observer = new MutationObserver(function (mutations) {
      if (applying || isOff()) { return; }
      for (var i = 0; i < mutations.length; i++) {
        var m = mutations[i];
        if (m.type === 'childList') {
          for (var j = 0; j < m.addedNodes.length; j++) {
            queuedRoots.push(m.addedNodes[j]);
          }
        } else if (m.type === 'characterData') {
          queuedRoots.push(m.target);
        } else if (m.type === 'attributes' && m.target) {
          queuedRoots.push(m.target);
        }
      }
      if (queuedRoots.length && !frame) {
        frame = window.setTimeout(drainQueue, SCHEDULE_MS);
      }
    });
    observer.observe(document.body, {
      childList: true,
      subtree: true,
      characterData: true,
      attributes: true,
      attributeFilter: TRANSLATABLE_ATTRS
    });
  }

  /* 네비바의 원문/번역 전환 항목을 잇는다. 없으면 아무 일도 하지 않는다. */
  function bindToggle() {
    var link = document.getElementById('aot-user-i18n-toggle');
    if (!link) { return; }

    function paint() {
      var showing = !isOff();
      // 번역이 보이는 중이면 "원문 보기"를, 원문이 보이는 중이면 "번역 보기"를
      // 제시한다 — 라벨은 현재 상태가 아니라 누르면 일어날 일을 말한다.
      link.textContent = showing
        ? link.getAttribute('data-label-hide')
        : link.getAttribute('data-label-show');
    }

    link.addEventListener('click', function (ev) {
      ev.preventDefault();
      window.AoTUserI18n.toggle();
      paint();
    });
    // 이 항목은 시스템 문구다 — 사용자 문자열 치환기가 건드리지 않게 막는다.
    link.setAttribute('data-no-translate', '');
    paint();
  }

  function init() {
    if (!document.body) { return; }
    if (!LANG) { return; }              // 기능이 꺼져 있다
    bindToggle();
    if (isOff()) { startObserver(); return; }
    translateSubtree(document.body);
    startObserver();
  }

  window.AoTUserI18n = {
    /** 번역 표시 여부. */
    isEnabled: function () { return !!LANG && !isOff(); },

    /** 원문 ↔ 번역 전환. 브라우저 번역기의 "원문 보기"와 같은 역할. */
    toggle: function () {
      if (!LANG) { return false; }
      var nowOff = !isOff();
      setOff(nowOff);
      if (nowOff) {
        restoreAll();
      } else {
        seen = new WeakSet();
        translateSubtree(document.body);
      }
      document.dispatchEvent(new CustomEvent('aot-user-i18n-toggled', {
        detail: {enabled: !nowOff}
      }));
      return !nowOff;
    },

    /** 사전에 있는 원문이면 번역본을, 없으면 원문을 돌려준다. */
    translate: function (text) {
      if (!text || isOff()) { return text; }
      return DICT[normalize(text)] || text;
    },

    /** 직접 그린 영역을 즉시 처리하고 싶을 때. */
    refresh: function (root) {
      seen = new WeakSet();
      translateSubtree(root || document.body);
    },

    _dict: function () { return DICT; }
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
