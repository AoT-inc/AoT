# coding=utf-8
# @manual ai/overview#ai-cards
"""AI 카드 첨부 파일 — 검사·저장·정리 (2026-10-19, P1).

screen_action(action='post', attach={name, text|b64|ref|url}) 의 파일을 받아 검사하고
PATH_AI_CARD_FILES 아래에 둔다. 서빙은 /api/v1/ai-inbox/<id>/file|thumb|text 만 한다
(static 아래에 두지 않는다 — 로그인 없이 노출된다).

보안 원칙(계약 ⑤):
  - 확장자 화이트리스트 + 매직바이트 교차 검사 + **서버가 정한 MIME**(받은 MIME 무시).
    svg·html·xml·js·office·heic·영상은 저장하지 않는다.
  - 디스크 이름은 uuid4 + 검증된 확장자. **입력으로 경로를 만들지 않는다.** 읽을 때도
    DB 값을 realpath 로 풀어 PATH_AI_CARD_FILES 아래인지 확인한다(resolve).
  - 외부 URL 은 P4 의 `url` 만 가져온다(ai_card_fetch — https·공인 IP 로 고정 연결·검사표
    전체가 거기 있다). 가져온 바이트도 이 파일의 검사·저장 경로를 **그대로** 지난다.
    ref 는 목록에서 고른 값으로만 경로를 만들고 키 주인이 볼 수 있는 것만 **복사**한다.
  - 이미지는 Pillow 로 열어 검증하고(픽셀 상한) 섬네일을 JPEG 로 다시 만든다(EXIF 제거).

P2: `.html` 은 kind 'artifact'(정적 HTML 카드)로 받는다 — 512 KiB 상한, UTF-8·NUL 검사,
`<meta http-equiv=refresh>` 거부. 저장·서빙은 같은 경로지만 서빙은 `/artifact`(불투명
출처 iframe + 응답 CSP sandbox)뿐이고 `/file` 은 언제나 attachment 다. 노트·공지로는
복사하지 않는다(COPY_SAFE_EXTS·notice_ext). `.htm`·svg 는 계속 거부.
"""
import base64
import binascii
import html as _html
import io
import json
import logging
import os
import re
import shutil
import threading
import uuid

from aot.config import (PATH_AI_CARD_FILES, PATH_NOTE_ATTACHMENTS,
                        PATH_NOTICE_ATTACHMENTS)

logger = logging.getLogger(__name__)

MAX_FILE_BYTES = 5 * 1024 * 1024            # 디코드 후
MAX_B64_CHARS = -(-MAX_FILE_BYTES // 3) * 4 + 64   # 디코드 전 길이 선검사
USER_QUOTA_BYTES = 100 * 1024 * 1024        # 사용자당 살아 있는 파일 합계
FILES_PER_DAY = 20                          # 사용자당 24시간 파일 카드
MIN_FREE_BYTES = 500 * 1024 * 1024          # 디스크 여유가 이보다 적으면 거부
NAME_MAX = 120
MAX_IMAGE_PIXELS = 40_000_000
#: WebP 는 Pillow 가 풀 때 전체 크기 사본을 여러 벌 만든다(40M 픽셀 한 장에 RSS 약 +660 MB,
#: 줄여서 풀 방법이 없다) — 16M 픽셀(4000×4000)로 따로 묶는다(P1 보안 리뷰 M2).
WEBP_MAX_PIXELS = 16_000_000
THUMB_SIDE = 320
#: 아티팩트(HTML) 카드 상한 — 디코드 전 길이도 이 값으로 먼저 거른다.
ARTIFACT_MAX_BYTES = 512 * 1024
ORPHAN_AGE_S = 3600
#: viz 카드(.viz) — AI가 조회한 값을 게이지/미니그래프로. 스펙은 작은 JSON이고 파일로
#: 저장하지 않는다(attachment 의 spec 칸에만 든다). 임의 HTML이 아니라 숫자+짧은 문자열뿐이라
#: 수신함이 인라인으로 그릴 수 있다(artifact 의 sandbox iframe 과 다른 길).
VIZ_MAX_BYTES = 8 * 1024          # 스펙 원문 상한(디코드 전/후 둘 다 이 값으로 거른다)
VIZ_MAX_POINTS = 48              # spark 점 개수 상한 — 카드·렌더 비용을 묶는다
VIZ_LABEL_MAX = 40
VIZ_UNIT_MAX = 12
VIZ_VALUETEXT_MAX = 16
VIZ_SPAN_MAX = 24               # spark 바닥 기간 라벨(예: "지난 6시간") — 선택, 짧은 글자만
#: P5 — 카드당 첨부(파일+영상 합계)·카드 디코드 합계·본문 승격 수·영상 타일 수·한 post 의 가져오기 시간.
CARD_MAX_ATTACH = 8
CARD_MAX_BYTES = 20 * 1024 * 1024
PROMOTE_MAX = 4
VIDEO_MAX = 4
POST_FETCH_BUDGET_S = 30

#: 확장자 → (서버가 정한 MIME, kind). 여기에 없으면 거부.
ALLOWED = {
    'png': ('image/png', 'image'), 'jpg': ('image/jpeg', 'image'),
    'jpeg': ('image/jpeg', 'image'), 'gif': ('image/gif', 'image'),
    'webp': ('image/webp', 'image'),
    'pdf': ('application/pdf', 'file'),
    'csv': ('text/csv', 'file'), 'txt': ('text/plain', 'file'),
    'md': ('text/markdown', 'file'), 'json': ('application/json', 'file'),
    # P2 — 정적 HTML 카드. 서버 MIME 은 text/html 이지만 /file 은 언제나 attachment 다.
    'html': ('text/html', 'artifact'),
}
TEXT_EXTS = frozenset({'csv', 'txt', 'md', 'json', 'html'})
#: 노트로 **복사해도 되는** 확장자. ALLOWED 에 html 이 들어오면서 copy_to_notes 가 html 을
#: 자동으로 받지 않게 따로 둔다(아티팩트는 [노트로 저장] 이 본문만 저장한다).
COPY_SAFE_EXTS = frozenset(ALLOWED) - {'html'}
#: 공지 첨부 허용 목록(utils_notice.ALLOWED_ATTACHMENT_EXTENSIONS 중 AI 카드가 낼 수 있는 것).
#: 공지 첨부 서빙에는 sandbox 가 없어 html 을 넣으면 저장형 XSS 다 — 거부한다.
NOTICE_EXTS = frozenset({'png', 'jpg', 'jpeg', 'gif', 'webp', 'pdf', 'txt', 'csv'})
#: 공지 허용 목록 밖이지만 글자뿐이라 .txt 로 바꿔 복사하는 확장자.
NOTICE_AS_TXT = frozenset({'md', 'json'})
_PIL_FORMAT = {'png': 'PNG', 'jpg': 'JPEG', 'jpeg': 'JPEG', 'gif': 'GIF', 'webp': 'WEBP'}
_MAGIC = {'png': (b'\x89PNG\r\n\x1a\n',), 'jpg': (b'\xff\xd8\xff',),
          'jpeg': (b'\xff\xd8\xff',), 'gif': (b'GIF87a', b'GIF89a'),
          'pdf': (b'%PDF-',)}

#: `<meta http-equiv="refresh">` — 프레임이 스스로 다른 주소로 가는 길(엔티티 우회까지
#: 보려고 HTML 엔티티를 풀어 본다). 공백을 **먼저 모두 지운 글**에 건다 — 예전 식
#: `http-equiv\s*=\s*['"]?\s*refresh` 는 이어진 \s* 두 개가 되짚기를 일으켜 `http-equiv=`
#: 뒤 공백 40 KB 에 15초, 512 KiB 면 수십 분 GIL 을 잡았다(P2 보안 리뷰 M3). 지금은 선형.
_META_REFRESH = re.compile(r'http-equiv=[\'"]?refresh', re.I)
_WS = re.compile(r'\s+')


def _redirects(text):
    """html 이 meta refresh 로 스스로 이동하려 하는가(원문·엔티티 푼 글 둘 다, 공백 무시)."""
    return any(_META_REFRESH.search(_WS.sub('', t)) for t in (text, _html.unescape(text)))


_DATA_PREFIX = re.compile(r'^\s*data:[^,]*,', re.I)
_URL_START = re.compile(r'^\s*(?:https?:|file:|//)', re.I)
_HTTPS_START = re.compile(r'^https://', re.I)


class FileError(Exception):
    """사용자(AI)에게 그대로 돌려줄 수 있는 검사 실패 문구."""


# ── 이름·크기 표기 ───────────────────────────────────────────────────────────

def split_name(raw_name):
    """원본 이름 → (표시 이름 ≤120자, 소문자 확장자). 경로 부분과 제어·양방향 문자는 뗀다.
    확장자가 없으면 FileError."""
    from aot.utils.ai_screen_cards import clean_line
    base = str(raw_name or '').replace('\\', '/').rsplit('/', 1)[-1]
    base = clean_line(base, 400)
    if '.' not in base:
        raise FileError("attach name needs an extension (allowed: %s)." % allowed_list())
    stem, ext = base.rsplit('.', 1)
    ext = ext.strip().lower()
    stem = stem.strip() or 'file'
    if len(ext) > 10:
        raise FileError("attach name needs an extension (allowed: %s)." % allowed_list())
    stem = stem[:max(1, NAME_MAX - len(ext) - 1)]
    return '%s.%s' % (stem, ext), ext


def allowed_list():
    return ' '.join(sorted(ALLOWED))


def human_size(n):
    n = int(n or 0)
    if n >= 1024 * 1024:
        return '%.1f MB' % (n / 1024 / 1024)
    return '%d KB' % max(1, round(n / 1024))


# ── 검사 ────────────────────────────────────────────────────────────────────

def _too_large(max_bytes):
    if max_bytes < 1024 * 1024:
        return FileError("html is larger than %d KB." % (max_bytes // 1024))
    return FileError("attach is larger than %d MB." % (max_bytes // 1024 // 1024))


def decode_b64(value, max_bytes=MAX_FILE_BYTES):
    """base64 문자열 → 바이트. 길이를 먼저 거르고 validate=True 로 푼다.
    max_bytes 는 디코드 후 상한(html 은 512 KiB) — 디코드 전 길이도 이 값에서 구한다."""
    if not isinstance(value, str):
        raise FileError("attach b64 must be a string.")
    max_chars = -(-max_bytes // 3) * 4 + 64
    if len(value) > max_chars + 4096:          # 접두·공백 여유는 아래에서 다시 센다
        raise _too_large(max_bytes)
    value = _DATA_PREFIX.sub('', value, count=1)
    value = ''.join(value.split())
    if len(value) > max_chars:
        raise _too_large(max_bytes)
    try:
        data = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        raise FileError("attach b64 is not valid base64.")
    return data


def inspect_bytes(ext, data):
    """확장자·내용 교차 검사. (mime, kind, 섬네일 바이트 또는 None) 을 돌려준다.
    어긋나면 FileError."""
    if ext not in ALLOWED:
        raise FileError("attach file type not allowed: .%s (allowed: %s)."
                        % (ext[:10], allowed_list()))
    if not data:
        raise FileError("attach is empty.")
    if len(data) > MAX_FILE_BYTES:
        raise FileError("attach is larger than %d MB." % (MAX_FILE_BYTES // 1024 // 1024))
    mime, kind = ALLOWED[ext]
    mismatch = FileError("attach content does not match .%s." % ext)
    if ext in TEXT_EXTS:
        if b'\x00' in data:
            raise mismatch
        try:
            text = data.decode('utf-8-sig')
        except UnicodeDecodeError:
            raise mismatch
        if ext == 'json':
            try:
                json.loads(text)
            except ValueError:
                raise mismatch
        if ext == 'html':
            if len(data) > ARTIFACT_MAX_BYTES:
                raise _too_large(ARTIFACT_MAX_BYTES)
            if _redirects(text):
                raise FileError("html must not redirect.")
        return mime, kind, None
    if ext == 'webp':
        if not (data[:4] == b'RIFF' and data[8:12] == b'WEBP'):
            raise mismatch
    elif not data.startswith(_MAGIC[ext]):
        raise mismatch
    if kind == 'image':
        return mime, kind, _make_thumb(ext, data)
    return mime, kind, None


#: 동시에 풀 수 있는 큰 이미지 수(프로세스당). 40M 픽셀 RGBA 한 장은 풀기만 해도
#: 160 MB 다 — 예전 순서(풀기 → 전체 크기 RGBA·RGB 변환 → 축소)는 150 KB 짜리 PNG
#: 하나로 RSS 가 약 480 MB 늘었고, 검사에 떨어진 요청은 한도에 세지 않아 되풀이할
#: 수 있었다(P1 보안 리뷰 M2). 지금은 먼저 줄이고 바꾸며, 이 슬롯으로 동시 수를 묶는다.
DECODE_SLOTS = 2
DECODE_WAIT_S = 30
_decode_slots = threading.BoundedSemaphore(DECODE_SLOTS)


def _make_thumb(ext, data):
    """Pillow 로 열어 검증하고 긴 변 320px JPEG(q80, EXIF 없음)를 돌려준다."""
    import warnings
    try:
        from PIL import Image
    except ImportError:                               # pragma: no cover - 배포에는 있다
        raise FileError("image could not be read.")
    if not _decode_slots.acquire(timeout=DECODE_WAIT_S):
        raise FileError("The AoT server is busy reading other images. Try again shortly.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            img = Image.open(io.BytesIO(data))
            fmt = 'JPEG' if img.format == 'MPO' else img.format   # 휴대폰 인물 사진은 MPO 로 열린다
            if fmt != _PIL_FORMAT[ext]:
                raise FileError("attach content does not match .%s." % ext)
            w, h = img.size
            cap = WEBP_MAX_PIXELS if fmt == 'WEBP' else MAX_IMAGE_PIXELS
            if w <= 0 or h <= 0 or w * h > cap:
                raise FileError("image could not be read.")
            if fmt == 'JPEG':
                img.draft('RGB', (THUMB_SIDE, THUMB_SIDE))   # DCT 축소 디코드(1/2~1/8)
            img.load()                                # 첫 프레임까지 실제로 풀어 본다
            alpha = img.mode in ('RGBA', 'LA', 'PA') or \
                (img.mode == 'P' and 'transparency' in img.info)
            if max(img.size) > THUMB_SIDE * 4 and img.mode not in ('RGB', 'L'):
                # 알파·팔레트 축소는 Pillow 가 안에서 전체 크기 사본(RGBa 등)을 만든다 —
                # 가까운 점으로 섬네일 4배까지 먼저 줄여 그 사본을 작게 묶는다.
                ratio = THUMB_SIDE * 4 / float(max(img.size))
                img = img.resize((max(1, int(img.width * ratio)),
                                  max(1, int(img.height * ratio))), Image.NEAREST)
            if img.mode not in ('RGB', 'RGBA', 'L', 'LA'):
                img = img.convert('RGBA' if alpha else 'RGB')
            img.thumbnail((THUMB_SIDE, THUMB_SIDE))   # 전체 크기 변환 없이 먼저 줄인다
            if alpha:
                rgba = img.convert('RGBA')
                flat = Image.new('RGB', rgba.size, (255, 255, 255))
                flat.paste(rgba, mask=rgba.split()[-1])
                img = flat
            else:
                img = img.convert('RGB')
            out = io.BytesIO()
            img.save(out, 'JPEG', quality=80)         # 새 이미지라 EXIF 는 따라오지 않는다
            return out.getvalue()
    except FileError:
        raise
    except Exception:                                 # 깨진 파일·폭탄·Pillow 오류 전부
        raise FileError("image could not be read.")
    finally:
        _decode_slots.release()


def parse_attach(attach):
    """attach 인자 → (이름 또는 None, 'text'|'b64'|'ref'|'url', 값). 모양이 틀리면 FileError.
    url 은 https 만 받는다(검사는 ai_card_fetch.check_url). 문자열 attach 가 `https://…` 면
    {url} 로 받고, `http:`·`file:`·`//` 는 모양 문구다."""
    from aot.utils.ai_card_fetch import MSG_SHAPE
    shape = "attach must be an object {name, text|b64|ref|url}."
    one = "attach needs exactly one of text, b64, ref, url."
    link = "put https links in attach.url."
    if isinstance(attach, str):
        raw = attach.strip()
        if raw.startswith('{'):
            try:
                attach = json.loads(raw)
            except ValueError:
                raise FileError(shape)
        elif _HTTPS_START.match(raw):
            attach = {'url': attach}               # 공백이 끼면 check_url 이 거부한다
        elif _URL_START.match(raw):
            raise FileError(MSG_SHAPE)
        else:
            raise FileError(one)
    if not isinstance(attach, dict):
        raise FileError(shape)
    if any(attach.get(k) not in (None, '') for k in ('uri', 'href', 'path')):
        raise FileError(link)
    given = [k for k in ('text', 'b64', 'ref', 'url') if attach.get(k) not in (None, '')]
    if len(given) != 1:
        raise FileError(one)
    key = given[0]
    value = attach[key]
    if key == 'ref' and (not isinstance(value, str) or _URL_START.match(value)):
        raise FileError(link)
    if key == 'b64' and isinstance(value, str) and re.match(r'^\s*(?:https?:|file:)', value, re.I):
        raise FileError(link)
    if key == 'text' and not isinstance(value, str):
        raise FileError("attach text must be a string.")
    if key == 'url' and not isinstance(value, str):
        raise FileError(MSG_SHAPE)
    name = attach.get('name')
    return (str(name) if name not in (None, '') else None), key, value


def parse_attach_list(attach):
    """attach 인자(객체 | 배열 | JSON 객체·배열 문자열 | https 문자열) → [(이름, 키, 값), …].

    배열은 최대 CARD_MAX_ATTACH(8)개. 배열 원소의 모양 오류는 `attach[2]: …` 처럼 번호를
    붙여 알린다. 한 개짜리는 예전과 같은 문구를 그대로 낸다."""
    if isinstance(attach, str) and attach.lstrip().startswith('['):
        try:
            attach = json.loads(attach)
        except ValueError:
            raise FileError("attach must be an object {name, text|b64|ref|url} or a list of them.")
    if isinstance(attach, (list, tuple)):
        if not attach:
            raise FileError("attach list is empty.")
        if len(attach) > CARD_MAX_ATTACH:
            raise FileError("attach: at most %d items." % CARD_MAX_ATTACH)
        out = []
        for idx, one in enumerate(attach):
            try:
                out.append(parse_attach(one))
            except FileError as exc:
                raise FileError("attach[%d]: %s" % (idx, exc))
        return out
    return [parse_attach(attach)]


def item_ext(name, key, value):
    """파싱한 attach 항목의 확장자 추측(이름 → url 이름). 모르면 None — html 단독 검사용."""
    if key == 'url' and isinstance(value, str):
        from aot.utils.ai_card_fetch import name_from_url
        return _name_ext(name) or _name_ext(name_from_url(value))
    return _name_ext(name)


# ── 경로 ────────────────────────────────────────────────────────────────────

def _root():
    return os.path.realpath(PATH_AI_CARD_FILES)


def _under(path, root):
    try:
        return os.path.commonpath([path, root]) == root
    except ValueError:
        return False


def resolve(rel_path):
    """DB 에 든 상대경로 → 실제 파일 경로. 저장 디렉터리 밖이거나 파일이 아니면 None.
    (심볼릭 링크·'..' 로 벗어난 값은 realpath 로 걸러진다.)"""
    if not rel_path or not isinstance(rel_path, str):
        return None
    root = _root()
    path = os.path.realpath(os.path.join(root, rel_path))
    if path == root or not _under(path, root) or not os.path.isfile(path):
        return None
    return path


def thumb_rel(rel_path):
    """원본 상대경로에서 섬네일 상대경로('YYYY/MM/uuid_t.jpg')를 만든다."""
    return rel_path.rsplit('.', 1)[0] + '_t.jpg'


def read_stored(rel_path, limit=MAX_FILE_BYTES):
    """저장된 파일의 바이트(최대 limit). 없거나 경로가 어긋나면 None."""
    path = resolve(rel_path)
    if path is None:
        return None
    try:
        with open(path, 'rb') as fh:
            return fh.read(limit + 1)[:limit]
    except OSError:
        return None


def disk_free(path=None):
    probe = path or PATH_AI_CARD_FILES
    while probe and not os.path.exists(probe):
        parent = os.path.dirname(probe)
        if parent == probe:
            break
        probe = parent
    try:
        return shutil.disk_usage(probe).free
    except OSError:
        return MIN_FREE_BYTES      # 못 재면 막지 않는다


def check_disk():
    if disk_free() < MIN_FREE_BYTES:
        raise FileError("Not enough disk space on the AoT server to store a file.")


# ── 저장 ────────────────────────────────────────────────────────────────────

def store(ext, data, thumb, now):
    """바이트를 `YYYY/MM/uuid.ext`(+ `uuid_t.jpg`)로 쓰고 상대경로를 돌려준다.
    `.part` 로 쓴 뒤 rename 하고 0o640 으로 둔다. 실패하면 쓴 것을 지우고 올린다."""
    root = _root()
    folder_rel = '%s/%s' % (now.strftime('%Y'), now.strftime('%m'))
    folder = os.path.join(root, folder_rel)
    os.makedirs(folder, mode=0o750, exist_ok=True)
    stem = str(uuid.uuid4())
    rel = '%s/%s.%s' % (folder_rel, stem, ext)
    made = []
    try:
        _write(os.path.join(folder, stem + '.part'), os.path.join(folder, stem + '.' + ext),
               data, made)
        if thumb:
            _write(os.path.join(folder, stem + '_t.part'),
                   os.path.join(folder, stem + '_t.jpg'), thumb, made)
    except Exception:
        for p in made:
            _unlink(p)
        raise
    return rel


def store_poster(jpeg, now):
    """영상 포스터(서버가 다시 인코딩한 JPEG)를 `YYYY/MM/uuid_t.jpg` 로 쓰고 상대경로를 돌려준다.
    원본 파일은 없다. `.part` 로 쓴 뒤 rename, 0o640. 실패하면 쓴 것을 지우고 올린다."""
    root = _root()
    folder_rel = '%s/%s' % (now.strftime('%Y'), now.strftime('%m'))
    folder = os.path.join(root, folder_rel)
    os.makedirs(folder, mode=0o750, exist_ok=True)
    stem = str(uuid.uuid4())
    made = []
    try:
        _write(os.path.join(folder, stem + '_t.part'), os.path.join(folder, stem + '_t.jpg'),
               jpeg, made)
    except Exception:
        for p in made:
            _unlink(p)
        raise
    return '%s/%s_t.jpg' % (folder_rel, stem)


def _write(part, final, data, made):
    made.append(part)
    fd = os.open(part, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o640)
    with os.fdopen(fd, 'wb') as fh:
        fh.write(data)
    os.replace(part, final)
    made.append(final)
    os.chmod(final, 0o640)


def _unlink(path):
    try:
        os.unlink(path)
    except OSError:
        pass


def remove_files(rel_paths):
    """상대경로(와 섬네일)의 파일을 지운다. 없으면 무시. 저장 디렉터리 밖은 건드리지 않는다."""
    root = _root()
    for rel in rel_paths:
        if not rel or not isinstance(rel, str):
            continue
        for r in (rel, thumb_rel(rel)):
            path = os.path.realpath(os.path.join(root, r))
            if path != root and _under(path, root):
                _unlink(path)


def sweep_orphans(referenced, now_ts=None, referenced_thumbs=()):
    """어느 행도 가리키지 않고 1시간 지난 파일과 `.part` 를 지운다. 지운 수.
    `referenced` 는 DB 의 file_path 집합(카드 칸 ∪ 첨부 path), `referenced_thumbs` 는 첨부의
    thumb 값(영상 포스터 포함)을 그대로 둔다. 심볼릭 링크는 따라가지 않는다."""
    import time
    now_ts = now_ts or time.time()
    keep = set()
    for rel in referenced:
        if rel:
            keep.add(rel)
            keep.add(thumb_rel(rel))
    for rel in referenced_thumbs:
        if rel:
            keep.add(rel)
    root = _root()
    if not os.path.isdir(root):
        return 0
    removed = 0
    for dirpath, _dirs, names in os.walk(root, followlinks=False):
        for name in names:
            path = os.path.join(dirpath, name)
            if os.path.islink(path):
                continue
            rel = os.path.relpath(path, root).replace(os.sep, '/')
            try:
                old = now_ts - os.path.getmtime(path) >= ORPHAN_AGE_S
            except OSError:
                continue
            if old and (name.endswith('.part') or rel not in keep):
                _unlink(path)
                removed += 1
    return removed


# ── ref (복사 원본) ─────────────────────────────────────────────────────────

def _no_ref():
    return FileError("attach ref was not found. Use note:<note_id>/<file from "
                     "search_notes files> or card:<card id>.")


def read_ref(user, ref, user_id):
    """`note:<note_id>/<files 항목>` 또는 `card:<id>` → (파일 이름, 바이트).

    note: 노트의 files 목록에 **있는 값**으로만 경로를 만들고(get_note_attachment 와 같은
    대조), 키 주인이 그 노트의 대상을 볼 수 있어야 한다. card: 키 주인의 살아 있는 파일
    카드. 어느 쪽이든 못 찾은 이유를 구분해 알리지 않는다(존재 노출 금지)."""
    ref = str(ref or '').strip()
    if ref.startswith('note:'):
        return _read_note_ref(user, ref[5:])
    if ref.startswith('card:'):
        return _read_card_ref(user_id, ref[5:])
    raise _no_ref()


def _read_note_ref(user, rest):
    from aot.databases.models import Notes
    note_id, _sep, wanted = rest.partition('/')
    note_id, wanted = note_id.strip(), wanted.strip()
    if not note_id or not wanted:
        raise _no_ref()
    note = Notes.query.filter(Notes.unique_id == note_id).first()
    if note is None or note.is_archived:
        raise _no_ref()
    if note.target_id:
        from aot.aot_flask.access import scope
        try:
            if not scope.can_operate_uuid(note.target_id, user=user):
                raise _no_ref()
        except FileError:
            raise
        except Exception:
            logger.exception('[ai_card_files] 노트 가시성 판정 실패 — 거부로 닫는다')
            raise _no_ref()
    available = [f.strip() for f in (note.files or '').split(',') if f.strip()]
    if wanted not in available:
        raise _no_ref()
    root = os.path.realpath(PATH_NOTE_ATTACHMENTS)
    path = os.path.realpath(os.path.join(root, wanted))
    if path == root or not _under(path, root) or not os.path.isfile(path):
        raise _no_ref()
    return os.path.basename(wanted), _read_limited(path)


def _read_card_ref(user_id, ident):
    from aot.utils import ai_screen_cards as cards
    card, _err = cards.find_card(user_id, ident.strip())
    first = cards.first_file(card) if card is not None else None
    if first is None or not first.path:
        raise _no_ref()
    path = resolve(first.path)
    if path is None:
        raise _no_ref()
    return first.name or os.path.basename(path), _read_limited(path)


def _read_limited(path):
    try:
        if os.path.getsize(path) > MAX_FILE_BYTES:
            raise FileError("attach is larger than %d MB." % (MAX_FILE_BYTES // 1024 // 1024))
        with open(path, 'rb') as fh:
            return fh.read(MAX_FILE_BYTES + 1)
    except OSError:
        raise _no_ref()


def _name_ext(name):
    try:
        return split_name(name)[1] if name else None
    except FileError:
        return None


def _viz_num(v):
    """유한한 실수만 받는다(bool·NaN·Inf·문자열 거부)."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    f = float(v)
    if f != f or f in (float('inf'), float('-inf')):
        return None
    return f


def _viz_str(v, limit):
    if v is None:
        return None
    s = str(v).strip()
    return s[:limit] if s else None


def parse_viz_spec(data):
    """.viz 첨부(JSON bytes 또는 str) → 정규화된 스펙 dict. 모양이 틀리면 FileError.

    숫자만·짧은 문자열만 받는다 — 수신함(aot-ai-caption.js)이 AoTViz 로 인라인 렌더하고,
    라벨·값 글자는 AoTViz 가 esc 처리한다. 임의 HTML 이 아니므로 sandbox 없이 그릴 수 있다.
    점 개수(spark)에 상한을 둬 카드·렌더 비용을 묶는다."""
    if isinstance(data, (bytes, bytearray)):
        if len(data) > VIZ_MAX_BYTES:
            raise FileError("viz spec is larger than %d KB." % (VIZ_MAX_BYTES // 1024))
        try:
            text = bytes(data).decode('utf-8-sig')
        except UnicodeDecodeError:
            raise FileError("viz spec must be UTF-8 JSON.")
    else:
        text = str(data)
    try:
        spec = json.loads(text)
    except ValueError:
        raise FileError("viz spec must be a JSON object.")
    if not isinstance(spec, dict):
        raise FileError("viz spec must be a JSON object.")
    kind = spec.get('viz')
    if kind not in ('gauge', 'spark'):
        raise FileError('viz must be "gauge" or "spark".')
    out = {'viz': kind}
    for src, dst, lim in (('label', 'label', VIZ_LABEL_MAX),
                          ('unit', 'unit', VIZ_UNIT_MAX),
                          ('valueText', 'valueText', VIZ_VALUETEXT_MAX)):
        s = _viz_str(spec.get(src), lim)
        if s:
            out[dst] = s
    if kind == 'gauge':
        value = _viz_num(spec.get('value'))
        lo = _viz_num(spec.get('min'))
        hi = _viz_num(spec.get('max'))
        if value is None or lo is None or hi is None:
            raise FileError("gauge needs numeric value, min, max.")
        if lo == hi:
            raise FileError("gauge min and max must differ.")
        out.update(value=value, min=lo, max=hi)
    # 적정 범위(선택) — 게이지는 녹색 호, 미니그래프는 옅은 초록 면으로 그린다.
    for k in ('okMin', 'okMax'):
        n = _viz_num(spec.get(k))
        if n is not None:
            out[k] = n
    if kind == 'spark':
        raw = spec.get('points')
        if not isinstance(raw, list):
            raise FileError("spark needs a points list.")
        pts = [_viz_num(v) for v in raw]
        if any(p is None for p in pts):
            raise FileError("spark points must all be finite numbers.")
        if len(pts) < 2:
            raise FileError("spark needs at least 2 points.")
        if len(pts) > VIZ_MAX_POINTS:
            raise FileError("spark allows at most %d points." % VIZ_MAX_POINTS)
        out['points'] = pts
        span = _viz_str(spec.get('span'), VIZ_SPAN_MAX)   # 선택 — 바닥에 적을 기간 라벨
        if span:
            out['span'] = span
    return out


def viz_bytes(spec):
    """정규화된 스펙 → 저장용 캐논 JSON bytes(크기 계산·attachment.spec 칸)."""
    return json.dumps(spec, ensure_ascii=False, separators=(',', ':')).encode('utf-8')


def prepare(attach, user, user_id):
    """attach 인자를 검사해 저장 준비물을 돌려준다.

    {'name','ext','mime','kind','data','thumb','fetch'} — 아직 아무것도 쓰지 않았다.
    `fetch` 는 url 로 받았을 때만 든 ai_card_fetch.Attempt(감사 한 행) 다 — 호출자가 카드를
    만든 뒤 `finish('ok', 크기, 카드 uuid)`, 실패하면 `finish('store')` 를 부른다."""
    name, key, value = parse_attach(attach)
    limit = MAX_FILE_BYTES
    url_ext = None
    if key == 'url':
        from aot.utils.ai_card_fetch import name_from_url
        url_ext = _name_ext(name_from_url(value)) if isinstance(value, str) else None
    if (_name_ext(name) or url_ext) == 'html':   # html 은 받기·디코드 전에 더 작은 상한으로 거른다
        limit = ARTIFACT_MAX_BYTES
    attempt = None
    if key == 'ref':
        ref_name, data = read_ref(user, value, user_id)
        name = name or ref_name
    elif key == 'b64':
        data = decode_b64(value, max_bytes=limit)
    elif key == 'url':
        from aot.utils.ai_card_fetch import fetch, sniff_ext
        got = fetch(value, user, limit)
        data, attempt = got.data, got.attempt
        name = name or got.name_hint
    else:
        if len(value) > limit:           # 글자 수 ≤ 바이트 수 — 인코드 전에 거른다
            raise _too_large(limit)
        data = value.encode('utf-8')
    try:
        if not name and key == 'url':
            guessed = sniff_ext(data)
            name = 'download.%s' % guessed if guessed else None
        if not name:
            raise FileError("attach needs a name like report.csv.")
        display, ext = split_name(name)
        if ext == 'viz':
            if key == 'url':
                raise FileError("viz spec must be sent inline, not by url.")
            spec = parse_viz_spec(data)
            return {'name': display, 'ext': 'viz', 'mime': 'application/json',
                    'kind': 'viz', 'data': viz_bytes(spec), 'thumb': None,
                    'fetch': attempt, 'spec': spec}
        mime, kind, thumb = inspect_bytes(ext, data)
    except FileError:
        if attempt is not None:
            attempt.finish('mismatch', len(data))
        raise
    return {'name': display, 'ext': ext, 'mime': mime, 'kind': kind,
            'data': data, 'thumb': thumb, 'fetch': attempt}


# ── 노트로 저장 (복사) ──────────────────────────────────────────────────────

def copy_to_notes(rel_path, display_name, now):
    """카드 파일을 노트 첨부 폴더(PATH_NOTE_ATTACHMENTS/YYYY/MM/새uuid.ext)로 **복사**하고
    노트 files 에 넣을 상대경로를 돌려준다. 원본이 없거나 확장자가 허용 밖이면 None."""
    src = resolve(rel_path)
    ext = rel_path.rsplit('.', 1)[-1].lower() if rel_path and '.' in rel_path else ''
    if src is None or ext not in COPY_SAFE_EXTS:
        return None
    folder_rel = '%s/%s' % (now.strftime('%Y'), now.strftime('%m'))
    folder = os.path.join(os.path.realpath(PATH_NOTE_ATTACHMENTS), folder_rel)
    os.makedirs(folder, exist_ok=True)
    stem = str(uuid.uuid4())
    part = os.path.join(folder, stem + '.part')
    final = os.path.join(folder, '%s.%s' % (stem, ext))
    try:
        shutil.copyfile(src, part)
        os.replace(part, final)
        os.chmod(final, 0o640)
    except OSError:
        _unlink(part)
        _unlink(final)
        return None
    return '%s/%s.%s' % (folder_rel, stem, ext)


def remove_note_copies(rel_paths):
    """copy_to_notes 가 만든 복사본을 지운다(노트 생성이 실패했을 때)."""
    root = os.path.realpath(PATH_NOTE_ATTACHMENTS)
    for rel in rel_paths or ():
        path = os.path.realpath(os.path.join(root, rel))
        if path != root and _under(path, root):
            _unlink(path)


# ── 공지로 게시 (복사) ──────────────────────────────────────────────────────

def notice_ext(ext):
    """카드 파일의 확장자 → 공지 첨부 확장자. md·json 은 'txt', html·그 밖은 None(거부)."""
    ext = (ext or '').lower()
    if ext in NOTICE_EXTS:
        return ext
    if ext in NOTICE_AS_TXT:
        return 'txt'
    return None


def notice_file_name(post_uuid, display_name, ext, index=0):
    """공지 첨부 파일 이름 `<post_uuid>_<secure_filename(이름)|ai-file>.<ext>` — 공지 쪽
    기존 규칙(`<post uuid>_<이름>`)과 같은 접두. 입력으로 경로를 만들지 않는다
    (secure_filename 은 `/`·`..`·공백·한글을 모두 떼고, 남는 게 없으면 'ai-file').
    여러 첨부(index ≥ 1)는 이름이 겹쳐 덮어쓰지 않게 `-<index>` 를 붙인다."""
    from werkzeug.utils import secure_filename
    stem = str(display_name or '').rsplit('.', 1)[0]
    stem = secure_filename(stem).strip('._-')[:80] or 'ai-file'
    if index:
        stem = '%s-%d' % (stem, int(index))
    return '%s_%s.%s' % (post_uuid, stem, ext)


def copy_to_notice(rel_path, display_name, post_uuid, index=0):
    """카드 파일을 공지 첨부 폴더(PATH_NOTICE_ATTACHMENTS, 평평한 이름)로 **복사**하고 공지
    files 에 넣을 파일 이름을 돌려준다. `.part` 로 쓴 뒤 rename, 0o640. 이미지 축소는 하지
    않는다(이미 검사한 5 MiB 이하 파일). 원본이 없으면 None, 허용 밖이면 FileError.
    실패하면 쓴 것을 지우고 None — 호출자가 공지를 만들지 않는다."""
    ext = rel_path.rsplit('.', 1)[-1].lower() if rel_path and '.' in rel_path else ''
    out_ext = notice_ext(ext)
    if out_ext is None:
        raise FileError("file_not_allowed")
    src = resolve(rel_path)
    if src is None:
        return None
    root = os.path.realpath(PATH_NOTICE_ATTACHMENTS)
    os.makedirs(root, exist_ok=True)
    name = notice_file_name(post_uuid, display_name, out_ext, index)
    final = os.path.realpath(os.path.join(root, name))
    if final == root or not _under(final, root) or os.path.dirname(final) != root:
        return None
    part = final + '.part'
    try:
        shutil.copyfile(src, part)
        os.replace(part, final)
        os.chmod(final, 0o640)
    except OSError:
        _unlink(part)
        _unlink(final)
        return None
    return name


def remove_notice_copies(names):
    """copy_to_notice 가 만든 복사본을 지운다(공지 생성이 실패했을 때)."""
    root = os.path.realpath(PATH_NOTICE_ATTACHMENTS)
    for name in names or ():
        path = os.path.realpath(os.path.join(root, name))
        if path != root and _under(path, root):
            _unlink(path)
            _unlink(path + '.part')
