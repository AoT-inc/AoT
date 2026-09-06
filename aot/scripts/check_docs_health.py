#!/usr/bin/env python3
"""사용자 매뉴얼(mkdocs) 회귀 방지 게이트.

**왜 있는가.** docs/ 는 두 갈래로 망가진다.

  1. 손으로 쓴 문서가 앱 코드와 따로 논다 — 템플릿의 `manual_url('Foo/#bar')`
     가 가리키는 페이지·앵커가 실제로는 없거나(링크만 걸고 문서는 안 씀),
     ko/ja 로 "번역"은 했지만 실제로는 en 폴백보다도 내용이 적다(부분번역을
     완료로 착각한 상태로 커밋 — 과거 일본어 부분번역 5쪽 사고).
  2. `docs/Supported-*.md` 6종은 `aot/scripts/generate_manual_*.py` 의 산출물인데,
     코드가 바뀐 뒤 재생성 없이 손으로 고치거나 그냥 방치하면 문서가 코드와
     드리프트한다. 재생성해서 git diff 가 나면 그 드리프트다.

검사 5종 (이름 -> --skip/--only 에 쓰는 키):
  links    앱 템플릿의 manual_url('...') 인자 전부를 mkdocs 빌드 산출물과 대조:
           그 페이지가 있는가, '#앵커'가 있으면 그 앵커도 있는가.
           `minify_html: true` 라 산출물의 id 속성은 따옴표가 없다(id=foo) —
           앵커 검사는 따옴표를 가정하지 않는다.
  i18n     ko/ja 빌드 산출물 <article> 본문 분량을 같은 페이지의 en 산출물과
           비교해 60% 미만이면 실패. 지표는 언어별로 다르다: ko 는 띄어쓰기가
           있어 '단어 수'(공백 분리)가 맞고, ja 는 단어 경계가 공백이 아니라서
           같은 지표를 쓰면 완전히 번역된 페이지도 대량 오탐한다(실측:
           Supported-Widgets.ja 완역본이 단어-수 기준 48%로 걸림) — ja 는
           공백을 뺀 글자 수로 비교한다.
  drift    Supported-* 생성기 6종을 실제로 재실행해 git diff 가 비어야 한다.
           MQTT 액션의 `Default Value: client_XXXXXXXX` 는 실행마다 난수라
           비교 전에 정규화한다(그러지 않으면 항상 헛실패).
  version  mkdocs.yml 의 extra.version 과 aot/config/__init__.py 의
           AOT_VERSION 이 같아야 한다(과거 태그·문서 버전 불일치 이력).
  images   docs/**/*.md 가 참조하는 images/... 실물이 전부 있어야 한다.

CI 에 건 것은 links·i18n·version·images 뿐이다. drift 는 aot 전체(입력/출력/
함수/액션/위젯 파서)를 import 하는데, 그 경로가 requirements.txt 전체(numpy,
influxdb_client, opencv-python-headless 등 120여 개)를 요구한다 — 이 저장소의
다른 CI 잡이 이미 그 설치를 하고 있어, 문서 워크플로에 통째로 다시 물리면
push 마다 무거워지고, 이 게이트를 새로 붙이는 지금 그 전체 설치가 이
GitHub Actions 러너에서 실제로 매끈히 되는지 실측하지 않은 채로 걸면(로컬
macOS 확인만으로는 보증이 안 된다) 처음부터 빨간 CI 를 만들 위험이 있다.
그래서 drift 는 로컬 전용으로 남긴다 — 아래 --only/--skip 로 언제든 켤 수 있다.

사용:
    python3 aot/scripts/check_docs_health.py                 # links·i18n·version·images
    python3 aot/scripts/check_docs_health.py --all            # drift 포함 전부
    python3 aot/scripts/check_docs_health.py --only drift     # drift 만
    python3 aot/scripts/check_docs_health.py --skip i18n      # 일부 생략
    python3 aot/scripts/check_docs_health.py --build-dir DIR  # mkdocs build 결과 재사용
                                                                # (없으면 임시 디렉터리에 직접 빌드)

종료 코드: 0 = 전부 통과, 1 = 위반 발견, 2 = 검사 자체를 못 돌림(빌드 실패 등).
"""
import argparse
import glob
import html
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DOCS = os.path.join(ROOT, "docs")
TEMPLATES = os.path.join(ROOT, "aot", "aot_flask", "templates")
MKDOCS_YML = os.path.join(ROOT, "mkdocs.yml")

ALL_CHECKS = ["links", "anchors", "i18n", "drift", "version", "images"]
CI_CHECKS = ["links", "anchors", "i18n", "version", "images"]  # drift 제외 - 위 docstring 참고

# 알려진 미해결 manual_url() 항목 - 문서가 아직 없어 실패로 세지 않는 것들.
# 지금은 없음: 항목을 추가할 때 왜 미해결인지, 언제 지울지 주석으로 남길 것.
KNOWN_PENDING_LINKS = set()

LANGS = ["ko", "ja"]  # en 은 기준(baseline)이라 별도로 검사하지 않는다.

GENERATORS = [
    "generate_manual_inputs.py",
    "generate_manual_outputs.py",
    "generate_manual_functions.py",
    "generate_manual_actions.py",
    "generate_manual_widgets.py",
    "generate_manual_inputs_by_measure.py",
]
# git pathspec has no brace-expansion (that's a shell-ism) - a single
# "docs/Supported-{A,B}*.md" string is a literal pattern to git and matches
# nothing, which would make every git-diff-based comparison below silently
# compare "" to "" and always report success. Pass one glob per generator
# instead; "Supported-Inputs*.md" also matches "Supported-Inputs-By-
# Measurement*.md", which is harmless (git de-duplicates overlapping paths).
GENERATED_DOCS_PATTERNS = [
    "docs/Supported-Inputs*.md",
    "docs/Supported-Outputs*.md",
    "docs/Supported-Functions*.md",
    "docs/Supported-Actions*.md",
    "docs/Supported-Widgets*.md",
]

# 여러 Input/Output/Action 모듈이 `random_alphanumeric()`(aot/utils/utils.py)로
# 옵션 기본값을 실행마다 새로 뽑는다 - 실측(연속 재실행 diff)으로 확인된 것 3종:
#   client_XXXXXXXX          MQTT 계열 다수(client_{8}) - aot/outputs/*mqtt*.py,
#                             aot/inputs/mqtt_paho*.py, aot/actions/*mqtt_publish.py 등
#   aot_rak3172hb_XXXXXX     aot/inputs/chirpstack_rak3172_valve_hb.py (client_{6})
#   Default Value: 18###     aot/outputs/on_off_kasa_*.py의 asyncio RPC 포트
#                             (18000 + randint(0, 900)) - 값 자체보다 "asyncio RPC
#                             server" 문구가 붙은 줄에서만 정규화해, 우연히 같은
#                             범위의 숫자를 쓰는 무관한 옵션까지 지워버리지 않는다.
# 비교 전에 정규화하지 않으면 재생성할 때마다 실제로는 바뀐 게 없어도 드리프트로 보인다.
_CLIENT_ID_RE = re.compile(r"\bclient_[A-Za-z0-9]{8}\b")
_RAK3172HB_ID_RE = re.compile(r"\baot_rak3172hb_[A-Za-z0-9]{6}\b")
_KASA_RPC_PORT_RE = re.compile(
    r"(Default Value: )\d+(</td><td>[^<]*asyncio RPC server)")


_DIFF_INDEX_LINE_RE = re.compile(r"^index [0-9a-f]+\.\.[0-9a-f]+.*$", re.M)


def _normalize_random_defaults(text):
    text = _CLIENT_ID_RE.sub("client_NORMALIZED", text)
    text = _RAK3172HB_ID_RE.sub("aot_rak3172hb_NORMALIZED", text)
    text = _KASA_RPC_PORT_RE.sub(r"\g<1>PORT_NORMALIZED\g<2>", text)
    # A byte-for-byte-different file (only its random defaults differ) still
    # gets a different git blob SHA, so `git diff`'s "index aaaa..bbbb" header
    # line would keep the two snapshots looking different even after the
    # content-level substitutions above. Strip it too - it carries no content.
    text = _DIFF_INDEX_LINE_RE.sub("index NORMALIZED", text)
    return text


def git(*args, cwd=ROOT):
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    return r.stdout


def rel(path):
    return os.path.relpath(path, ROOT).replace(os.sep, "/")


# --------------------------------------------------------------------------
# links: 템플릿 manual_url() <-> mkdocs 빌드 산출물
# --------------------------------------------------------------------------

_MANUAL_URL_RE = re.compile(r"""manual_url\((['"])(.*?)\1\)""")


def find_manual_url_calls():
    """템플릿에서 manual_url('path[#anchor]') 인자를 전부 뽑는다.

    반환: {path_arg: [(템플릿파일, 라인번호), ...]}  - 같은 인자를 여러 템플릿이
    참조할 수 있어 파일마다 한 번씩 검사하지 않고 인자별로 묶는다.
    """
    calls = {}
    for path in glob.glob(os.path.join(TEMPLATES, "**", "*.html"), recursive=True):
        with open(path, encoding="utf-8") as f:
            for lineno, line in enumerate(f, 1):
                for m in _MANUAL_URL_RE.finditer(line):
                    arg = m.group(2)
                    calls.setdefault(arg, []).append((rel(path), lineno))
    return calls


def _page_dir_for_arg(build_dir, arg_path):
    """manual_url 인자(예: 'Functions/#conditional', '', 'API/')의 페이지 디렉터리."""
    page_path = arg_path.split("#", 1)[0]
    return os.path.join(build_dir, page_path) if page_path else build_dir


_ID_RE_CACHE = {}


def _has_anchor(html_text, anchor):
    """id=anchor 존재 여부. minify_html 이 따옴표를 지우므로(id=foo) 따옴표 유무
    양쪽 다 인식한다."""
    if anchor not in _ID_RE_CACHE:
        esc = re.escape(anchor)
        _ID_RE_CACHE[anchor] = re.compile(r'id=["\']?{}(?=["\'\s/>])'.format(esc))
    return bool(_ID_RE_CACHE[anchor].search(html_text))


def check_links(build_dir):
    problems = []
    calls = find_manual_url_calls()
    for arg, sites in sorted(calls.items()):
        if arg in KNOWN_PENDING_LINKS:
            continue
        page_path, _, anchor = arg.partition("#")
        page_dir = _page_dir_for_arg(build_dir, arg)
        index_html = os.path.join(page_dir, "index.html")
        if not os.path.isfile(index_html):
            where = "; ".join(f"{f}:{n}" for f, n in sites)
            problems.append(
                f"manual_url('{arg}') -> 빌드 산출물에 페이지 없음: {rel(index_html)} "
                f"(참조: {where})")
            continue
        if anchor:
            text = open(index_html, encoding="utf-8").read()
            if not _has_anchor(text, anchor):
                where = "; ".join(f"{f}:{n}" for f, n in sites)
                problems.append(
                    f"manual_url('{arg}') -> 페이지는 있으나 앵커 '#{anchor}' 없음: "
                    f"{rel(index_html)} (참조: {where})")
    return problems


# --------------------------------------------------------------------------
# i18n: ko/ja 페이지 분량이 en 대비 너무 적지 않은가
# --------------------------------------------------------------------------

_ARTICLE_RE = re.compile(r"<article[^>]*>(.*?)</article>", re.S)
_TAG_RE = re.compile(r"<[^>]+>")

# 번역본이 원문보다 이만큼도 안 되면 실패로 본다.
#
# 길이 비율은 언어마다 크게 달라 신뢰할 수 없다. 일본어 완역본이 영어의
# 57~60% 로 나오는 것이 정상이고(한자어 압축, 그대로 두는 기술 용어),
# 예전 임계값 60% 는 멀쩡한 완역 네 쪽을 부분번역으로 몰았다. 그래서
# 주 판정은 **구조 대조**로 한다 - 제목·표 행·목록 항목·코드 블록·문단
# 개수는 언어와 무관하게 원문과 같아야 한다. 길이는 "제목만 있고 본문이
# 비었다" 를 잡는 보조 지표로만, 아주 낮은 바닥에서 쓴다.
I18N_MIN_BLOCK_RATIO = 0.9
I18N_MIN_LENGTH_RATIO = 0.35

_BLOCK_PATTERNS = (
    ("제목", re.compile(r"<h[1-6][\s>]", re.I)),
    ("표 행", re.compile(r"<tr[\s>]", re.I)),
    ("목록 항목", re.compile(r"<li[\s>]", re.I)),
    ("코드 블록", re.compile(r"<pre[\s>]", re.I)),
    ("문단", re.compile(r"<p[\s>]", re.I)),
)


def _article_html(index_html_path):
    text = open(index_html_path, encoding="utf-8").read()
    m = _ARTICLE_RE.search(text)
    return m.group(1) if m else ""


def _article_text(index_html_path):
    body = _TAG_RE.sub(" ", _article_html(index_html_path))
    return html.unescape(body)


def _blocks(article_html):
    return {name: len(rx.findall(article_html)) for name, rx in _BLOCK_PATTERNS}


def _en_pages(build_dir):
    """en 트리(=build_dir 최상위, ko/ja 서브트리 제외)의 모든 index.html 페이지 경로(상대)."""
    pages = []
    for index_html in glob.glob(os.path.join(build_dir, "**", "index.html"), recursive=True):
        relp = os.path.relpath(index_html, build_dir)
        top = relp.split(os.sep, 1)[0]
        if top in LANGS:
            continue
        pages.append(os.path.dirname(relp))  # '' for the root page
    return pages


def check_i18n(build_dir):
    problems = []
    for page in _en_pages(build_dir):
        en_index = os.path.join(build_dir, page, "index.html")
        en_html = _article_html(en_index)
        en_blocks = _blocks(en_html)
        en_text = _article_text(en_index)
        en_words = len(en_text.split())
        en_chars = len(re.sub(r"\s", "", en_text))
        if en_words == 0:
            continue  # 빈 페이지(리다이렉트 등) - 비교 대상 아님
        page_label = page if page else "(root)"

        for lang in LANGS:
            lang_index = os.path.join(build_dir, lang, page, "index.html")
            if not os.path.isfile(lang_index):
                # mkdocs-static-i18n 이 페이지를 언어별로 안 만들었다면 그 자체가
                # 이상 상황이지만, 이 검사의 관심사는 아니다.
                continue
            lang_html = _article_html(lang_index)
            if lang_html == en_html:
                continue  # 번역 파일이 없어 en 으로 폴백된 페이지 - 부분번역이 아니다

            lang_blocks = _blocks(lang_html)
            missing = []
            for name, en_n in en_blocks.items():
                if en_n < 3:
                    continue  # 표본이 너무 작아 비율 판정이 무의미하다
                got = lang_blocks[name]
                if got < en_n * I18N_MIN_BLOCK_RATIO:
                    missing.append(f"{name} {got}/{en_n}")
            if missing:
                problems.append(
                    f"{lang}/{page_label} 이 원문의 구조를 다 담지 못했다("
                    + ", ".join(missing) +
                    ") - 절이나 표 행이 빠진 부분번역 의심")
                continue

            lang_text = _article_text(lang_index)
            if lang == "ja":
                # 일본어는 단어 경계가 공백이 아니다. 글자 수로 본다.
                ratio = (len(re.sub(r"\s", "", lang_text)) / en_chars) if en_chars else 1.0
                metric = "글자 수"
            else:
                ratio = (len(lang_text.split()) / en_words) if en_words else 1.0
                metric = "단어 수"
            if ratio < I18N_MIN_LENGTH_RATIO:
                problems.append(
                    f"{lang}/{page_label} 은 구조는 맞는데 본문이 en 대비 "
                    f"{ratio:.0%}({metric} 기준, 바닥 {I18N_MIN_LENGTH_RATIO:.0%})밖에 "
                    f"안 된다 - 제목만 옮기고 본문을 비워 둔 것은 아닌지 볼 것")
    return problems


# --------------------------------------------------------------------------
# drift: Supported-*.md 생성기 재실행 결과가 커밋된 것과 같은가
# --------------------------------------------------------------------------

_DIFF_FILE_SPLIT_RE = re.compile(r"^diff --git a/(\S+) b/\S+$", re.M)


def _diff_by_file(diff_text):
    """`git diff` 출력을 {파일경로: 그 파일의 diff 블록} 으로 쪼갠다."""
    parts = _DIFF_FILE_SPLIT_RE.split(diff_text)
    # parts = ['', file1, block1, file2, block2, ...]
    out = {}
    for i in range(1, len(parts), 2):
        out[parts[i]] = parts[i + 1]
    return out


def _snapshot_generated():
    """생성 대상 파일들의 현재 내용을 기억해 둔다.

    생성기는 docs/ 안의 고정 경로에 직접 쓴다. 검사 때문에 워킹트리가
    더러워지면 안 되므로(난수 client id 탓에 매 실행마다 diff 가 생긴다),
    검사 전 내용을 담아 두고 검사 뒤 그대로 되돌린다.
    """
    import glob
    snap = {}
    for pattern in GENERATED_DOCS_PATTERNS:
        for path in glob.glob(os.path.join(ROOT, pattern)):
            with open(path, "rb") as f:
                snap[path] = f.read()
    return snap


def _restore_generated(snap):
    """_snapshot_generated() 시점으로 되돌린다. 그 뒤 생긴 파일은 지운다."""
    import glob
    seen = set()
    for pattern in GENERATED_DOCS_PATTERNS:
        for path in glob.glob(os.path.join(ROOT, pattern)):
            seen.add(path)
            if path not in snap:
                os.remove(path)
            else:
                with open(path, "rb") as f:
                    if f.read() == snap[path]:
                        continue
                with open(path, "wb") as f:
                    f.write(snap[path])
    for path, data in snap.items():
        if path not in seen:
            with open(path, "wb") as f:
                f.write(data)


def check_drift():
    """생성기를 다시 돌려 나온 내용이 지금 파일과 같은지 본다.

    diff 텍스트가 아니라 **파일 내용**을 정규화해 비교한다. 매 실행마다
    달라지는 난수(MQTT/RAK3172 client id, Kasa asyncio RPC 포트)는 정규화로
    지우므로 그것만 다른 경우는 통과한다. 검사가 끝나면 파일을 원래대로
    되돌려 워킹트리를 더럽히지 않는다.
    """
    snap = _snapshot_generated()
    for gen in GENERATORS:
        r = subprocess.run(
            [sys.executable, os.path.join(ROOT, "aot", "scripts", gen)],
            cwd=ROOT, capture_output=True, text=True)
        if r.returncode != 0:
            _restore_generated(snap)
            return None, [
                f"{gen} 실행 실패(exit {r.returncode}):\n{r.stderr[-2000:]}"
            ]

    after = _snapshot_generated()
    problems = []

    changed = sorted(
        rel(path) for path in (set(snap) & set(after))
        if _normalize_random_defaults(snap[path].decode("utf-8", "replace"))
        != _normalize_random_defaults(after[path].decode("utf-8", "replace"))
    )
    if changed:
        problems.append(
            "생성기를 재실행하니 다음 파일의 내용이 달라졌다(난수 기본값은 "
            "정규화해 제외): " + ", ".join(changed) +
            " - 재생성해서 커밋할 것 (python3 aot/scripts/generate_manual_*.py).")

    created = sorted(rel(path) for path in (set(after) - set(snap)))
    if created:
        problems.append(
            "생성기가 저장소에 없는 새 파일을 만들었다(추가 후 커밋 필요): " +
            ", ".join(created))

    _restore_generated(snap)
    return True, problems


# --------------------------------------------------------------------------
# version: mkdocs.yml extra.version <-> AOT_VERSION
# --------------------------------------------------------------------------

def check_version():
    import yaml
    with open(MKDOCS_YML, encoding="utf-8") as f:
        mkdocs_conf = yaml.safe_load(f)
    mkdocs_version = str(mkdocs_conf.get("extra", {}).get("version", "")).strip()

    config_path = os.path.join(ROOT, "aot", "config", "__init__.py")
    text = open(config_path, encoding="utf-8").read()
    m = re.search(r"""^AOT_VERSION\s*=\s*['"]([^'"]+)['"]""", text, re.M)
    aot_version = m.group(1) if m else None

    if not mkdocs_version or not aot_version:
        return [f"버전 문자열을 못 찾음: mkdocs.yml extra.version={mkdocs_version!r}, "
                f"AOT_VERSION={aot_version!r}"]
    if mkdocs_version != aot_version:
        return [f"버전 불일치: mkdocs.yml extra.version={mkdocs_version!r} != "
                f"aot/config/__init__.py AOT_VERSION={aot_version!r}"]
    return []


# --------------------------------------------------------------------------
# images: docs/**/*.md 의 images/... 참조가 실물을 가리키는가
# --------------------------------------------------------------------------

_IMG_REF_RE = re.compile(r"""\(((?:\.\./)*images/[^)\s]+)\)|src=["\']((?:\.\./)*images/[^"\']+)["\']""")


def check_images():
    problems = []
    for md_path in glob.glob(os.path.join(DOCS, "**", "*.md"), recursive=True):
        text = open(md_path, encoding="utf-8").read()
        for m in _IMG_REF_RE.finditer(text):
            ref = m.group(1) or m.group(2)
            resolved = os.path.normpath(os.path.join(os.path.dirname(md_path), ref))
            if not os.path.isfile(resolved):
                problems.append(f"{rel(md_path)}: 이미지 없음 -> {ref} (찾은 경로: {rel(resolved)})")
    return problems



# --------------------------------------------------------------------------
# anchors: 문서 사이 링크가 가리키는 앵커가 그 언어 판에도 있는가
# --------------------------------------------------------------------------

_DANGLING_ANCHOR_RE = re.compile(
    r"Doc file '(?P<src>[^']+)' contains a link '(?P<link>[^']+)', "
    r"but the doc '(?P<dst>[^']+)' does not contain an anchor '(?P<anchor>[^']+)'")


def check_anchors(build_log):
    """mkdocs 가 알려 주는 '문서에 그 앵커가 없다' 를 실패로 올린다.

    영어 제목은 자동 슬러그가 링크와 맞지만, 같은 자리의 한국어/일본어 제목은
    슬러그가 달라져 링크가 조용히 깨진다. mkdocs 는 이걸 INFO 로만 흘리므로
    아무도 보지 않는다. 고치는 법은 대상 제목에 명시 앵커를 다는 것:
    `## 에너지 사용 설정 { #energy-usage-settings }`
    """
    problems = []
    for m in _DANGLING_ANCHOR_RE.finditer(build_log or ""):
        problems.append(
            f"{m.group('src')} 의 링크 '{m.group('link')}' 가 가리키는 앵커 "
            f"'{m.group('anchor')}' 가 {m.group('dst')} 에 없다 - 그 제목에 "
            f"명시 앵커를 달 것")
    return problems


# --------------------------------------------------------------------------
# 빌드
# --------------------------------------------------------------------------

def build_docs(out_dir):
    r = subprocess.run(
        ["mkdocs", "build", "-d", out_dir, "--clean"],
        cwd=ROOT, capture_output=True, text=True)
    return r.returncode == 0, r.stdout + r.stderr


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", metavar="CHECK[,CHECK...]",
                     help="이 검사들만 실행 (기본: " + ",".join(CI_CHECKS) + ")")
    ap.add_argument("--skip", metavar="CHECK[,CHECK...]", help="이 검사들을 생략")
    ap.add_argument("--all", action="store_true",
                     help="drift 를 포함해 5종 전부 실행 (기본은 CI 세트 4종)")
    ap.add_argument("--build-dir", metavar="DIR",
                     help="이미 만든 mkdocs build 결과를 재사용(links/i18n 용). "
                          "생략하면 임시 디렉터리에 직접 빌드한다.")
    args = ap.parse_args()

    checks = list(ALL_CHECKS) if args.all else list(CI_CHECKS)
    if args.only:
        wanted = [c.strip() for c in args.only.split(",") if c.strip()]
        unknown = [c for c in wanted if c not in ALL_CHECKS]
        if unknown:
            ap.error(f"알 수 없는 검사: {', '.join(unknown)} (선택: {', '.join(ALL_CHECKS)})")
        checks = wanted
    if args.skip:
        skip = {c.strip() for c in args.skip.split(",")}
        checks = [c for c in checks if c not in skip]

    total_problems = 0
    tmp_build_dir = None
    build_log = ""

    try:
        build_dir = args.build_dir
        needs_build = any(c in checks for c in ("links", "anchors", "i18n"))
        if needs_build and not build_dir:
            tmp_build_dir = tempfile.mkdtemp(prefix="aot-docs-health-")
            build_dir = tmp_build_dir
            print(f"[build] mkdocs build -d {build_dir}")
            ok, log = build_docs(build_dir)
            build_log = log
            if not ok:
                print("FAIL: mkdocs build 실패\n" + log[-4000:])
                return 2

        for name in checks:
            print(f"\n=== {name} ===")
            if name == "links":
                problems = check_links(build_dir)
            elif name == "anchors":
                if not build_log:
                    ok, build_log = build_docs(build_dir or tempfile.mkdtemp(
                        prefix="aot-docs-health-anchors-"))
                problems = check_anchors(build_log)
            elif name == "i18n":
                problems = check_i18n(build_dir)
            elif name == "drift":
                ran, problems = check_drift()
                if ran is None:
                    print("FAIL: " + "\n".join(problems))
                    return 2
            elif name == "version":
                problems = check_version()
            elif name == "images":
                problems = check_images()
            else:
                continue

            if problems:
                total_problems += len(problems)
                for p in problems:
                    print(f"  - {p}")
                print(f"FAIL: {name} 위반 {len(problems)}건")
            else:
                print(f"OK: {name}")
    finally:
        if tmp_build_dir:
            shutil.rmtree(tmp_build_dir, ignore_errors=True)

    print()
    if total_problems:
        print(f"FAIL: 총 위반 {total_problems}건.")
        return 1
    print("OK: 전부 통과.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
