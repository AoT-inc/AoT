# coding=utf-8
# @manual ai/overview#ai-cards
"""AI 카드의 영상 링크 (2026-10-21, P5) — 인식·정규화·포스터·재생 가능 판정.

서버는 영상 본문을 받지 않는다(5 MiB 상한 밖). 카드에는 **영상 타일**만 남는다 — 링크 한 줄과
제공처 표기, 그리고 가능하면 서버가 받아 다시 인코딩한 포스터(JPEG).

  제공처   인식(호스트 정확 일치)                         저장 주소(서버가 새로 만든다)
  youtube  youtube.com·www.·m. 의 /watch?v=ID·/shorts/ID·    https://www.youtube.com/watch?v=ID (쇼츠는 …/shorts/ID)
           /embed/ID·/live/ID, youtu.be/ID  (ID 11자)
  vimeo    vimeo.com/<숫자>[/<hash>], player.vimeo.com/video/<숫자>   https://vimeo.com/<id>[/<hash>]
  direct   check_url 통과 + 경로가 .mp4 .webm .mov            check_url 정규형(서명 쿼리 유지)
  web      그 밖의 https 웹페이지 링크(2026-10-22)            check_url 정규형 — og:image 가 있을 때만 타일

보안 원칙:
  - 인식은 호스트 정확 일치 + ID 정규식 fullmatch 다(`youtube.com.evil.com`·`evilyoutube.com`·
    userinfo·http·IP 리터럴은 모두 check_url 이나 호스트 비교에서 떨어진다). 저장 주소는 입력을
    그대로 쓰지 않고 ID 로 **다시 조립**하므로 공격자 쿼리가 따라오지 않는다(direct 는 예외).
  - 서버 요청은 포스터·oEmbed 뿐이고 모두 `ai_card_fetch.fetch` 를 지난다(SSRF 방어·슬롯·시간 30/일
    100 한도·감사 한 행) — `allow_hosts` 로 첫 홉과 모든 리다이렉트 홉을 고정 호스트 안에 가둔다.
  - direct 링크는 **서버가 아무 요청도 하지 않는다**. 뷰어 안 재생 가능 여부(playable)만
    resolve_public(DNS, 연결 없음)으로 판정한다.
  - 임베드(iframe)는 사용자 승인(2026-10-22)으로 **YouTube 만** 켠다(AI_CARD_VIDEO_EMBED). 프런트는 [여기서 재생]을
    누른 뒤에만 youtube-nocookie.com/embed/ID 를 sandbox iframe 으로 만든다 — 클릭 전 외부 요청 0.
"""
import collections
import json
import logging
import re
import time
from urllib.parse import parse_qs, quote, urlsplit

logger = logging.getLogger(__name__)

#: 뷰어 안 임베드 재생(2026-10-22 사용자 승인). 켜면 YouTube 영상 항목에 embed:true 가 붙는다(Vimeo 는 새 탭만).
AI_CARD_VIDEO_EMBED = True

POSTER_MAX_BYTES = 1024 * 1024
OEMBED_MAX_BYTES = 64 * 1024
PLAYABLE_EXTS = ('mp4', 'webm')
_DIRECT_EXTS = ('.mp4', '.webm', '.mov')
NAME_MAX = 120
#: 웹페이지 링크 타일(provider='web', 저장 종류는 영상 타일과 같은 'video' 행 — 포스터·url·host 를 쓰는
#: 같은 모양이라 읽기·삭제·노트·공지 경로를 그대로 탄다). 페이지에서 og:image 를 못 받으면 타일을 만들지
#: 않고 링크로 남긴다. 페이지는 앞 256 KiB 만 보고(og 태그는 <head> 에 있다), 이미지는 포스터와 같은
#: 상한·재인코드를 지난다. 페이지·이미지 호스트는 임의의 공개 주소라 allow_hosts 가 없다 — SSRF 방어는
#: fetch 의 1~9단계(공인 IP 만·검증 IP 직접 연결·리다이렉트 홉마다 재검증)가 맡는다.
WEB_MAX = 3
PAGE_MAX_BYTES = 256 * 1024
_NOT_PAGE_EXTS = ('.pdf', '.zip', '.gz', '.tar', '.csv', '.xls', '.xlsx', '.doc', '.docx', '.ppt',
                  '.pptx', '.hwp', '.hwpx', '.txt', '.json', '.xml', '.mp3', '.wav', '.apk', '.exe',
                  '.dmg', '.svg', '.ico')
_OG_NAMES = frozenset({'og:image', 'og:image:url', 'og:image:secure_url', 'twitter:image'})

_YT_HOSTS = frozenset({'youtube.com', 'www.youtube.com', 'm.youtube.com'})
_YT_ID = re.compile(r'[A-Za-z0-9_-]{11}')
_YT_PATH = re.compile(r'/(?:shorts|embed|live)/([A-Za-z0-9_-]{11})/?')
_YT_SHORT_PATH = re.compile(r'/([A-Za-z0-9_-]{11})/?')
_VIMEO_PATH = re.compile(r'/([0-9]{1,12})(?:/([0-9a-f]{6,20}))?/?')
_VIMEO_PLAYER_PATH = re.compile(r'/video/([0-9]{1,12})/?')

#: 포스터·oEmbed 를 받을 수 있는 고정 호스트(리다이렉트 포함).
YOUTUBE_POSTER_HOSTS = frozenset({'img.youtube.com', 'i.ytimg.com'})
VIMEO_OEMBED_HOSTS = frozenset({'vimeo.com'})
VIMEO_POSTER_HOSTS = frozenset({'i.vimeocdn.com'})

Video = collections.namedtuple('Video', 'provider url host id name')
Poster = collections.namedtuple('Poster', 'jpeg title attempts')

PROVIDER_LABEL = {'youtube': 'YouTube', 'vimeo': 'Vimeo', 'direct': 'MP4', 'web': 'web'}


def _label_name(name):
    from aot.utils.ai_screen_cards import clean_line
    return clean_line(name, NAME_MAX)


def parse_video_url(raw):
    """URL 문자열 → Video(provider, 저장 주소, 호스트, ID, 이름) 또는 None(영상 모양이 아님).
    DNS·네트워크 없음. https·userinfo 없음·IP 리터럴 없음은 check_url 이 먼저 거른다."""
    from aot.utils import ai_card_fetch as fetcher
    try:
        target = fetcher.check_url(raw)
    except fetcher.FetchError:
        return None
    parts = urlsplit(target.url)
    host, path = target.host, parts.path
    if host in _YT_HOSTS:
        vid, shorts = None, False
        if path in ('/watch', '/watch/'):
            vals = parse_qs(parts.query, keep_blank_values=False).get('v') or []
            if vals and _YT_ID.fullmatch(vals[0]):
                vid = vals[0]
        else:
            m = _YT_PATH.fullmatch(path)
            vid = m.group(1) if m else None
            shorts = bool(m) and path.startswith('/shorts/')
        if vid:
            # 쇼츠는 /shorts/ID 로 남긴다 — 뷰어가 이 주소로 세로(9:16) 재생 상자를 고른다.
            return Video('youtube', ('https://www.youtube.com/shorts/%s' if shorts
                                     else 'https://www.youtube.com/watch?v=%s') % vid,
                         'www.youtube.com', vid, 'YouTube video')
    elif host == 'youtu.be':
        m = _YT_SHORT_PATH.fullmatch(path)
        if m:
            vid = m.group(1)
            return Video('youtube', 'https://www.youtube.com/watch?v=%s' % vid,
                         'www.youtube.com', vid, 'YouTube video')
    elif host == 'vimeo.com':
        m = _VIMEO_PATH.fullmatch(path)
        if m:
            vid = m.group(1) + ('/' + m.group(2) if m.group(2) else '')
            return Video('vimeo', 'https://vimeo.com/%s' % vid, 'vimeo.com', vid,
                         'Vimeo video')
    elif host == 'player.vimeo.com':
        m = _VIMEO_PLAYER_PATH.fullmatch(path)
        if m:
            return Video('vimeo', 'https://vimeo.com/%s' % m.group(1), 'vimeo.com',
                         m.group(1), 'Vimeo video')
    if path.lower().endswith(_DIRECT_EXTS):
        name = _label_name(fetcher.name_from_url(target.url) or '') or 'video'
        return Video('direct', target.url, host, '', name)
    return None


_LABEL_MD = re.compile(r'!?\[([^\]\n]{1,300})\]\(')
_LABEL_LEAD = re.compile(r'^[\s>*#+\-•·]+|^\d{1,2}[.)]\s+')


def label_near(text, pos, url=None, default=None):
    """링크 바로 곁의 설명 글 — 타일 제목으로 쓴다(AI 가 본문에 쓴 `[설명](주소)` 또는 줄 끝의 `설명: 주소`).
    pos 는 find_body_media 가 준 오프셋(`[`·`!` 또는 맨 주소의 시작), url 은 그 원본 주소. 문장 중간에 낀
    맨 주소(뒤에 글이 이어짐)나 쓸 만한 글이 없으면 default."""
    if not isinstance(text, str) or pos < 0 or pos > len(text):
        return default
    m = _LABEL_MD.match(text, pos)
    if m:
        raw = m.group(1)
    else:
        end = text.find('\n', pos)
        rest = text[pos + len(url or ''):end if end >= 0 else len(text)]
        if url is None or rest.strip(' \t.,;:)!?*_') != '':
            return default
        start = text.rfind('\n', 0, pos) + 1
        raw = text[start:pos]
        for _ in range(3):                 # 목록 기호·굵게 표시를 앞뒤에서 벗긴다
            raw = _LABEL_LEAD.sub('', raw)
        raw = raw.replace('**', '').replace('__', '').rstrip(' \t:：-–—*_')
    raw = re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', raw)   # 안쪽 링크는 글만
    name = _label_name(raw.strip())
    return name if name and len(name) >= 2 else default


def parse_web_url(raw):
    """일반 웹페이지 링크 → Video('web', 정규형 주소, 호스트, '', 호스트 이름) 또는 None(https·공인 호스트
    모양이 아님). DNS·네트워크 없음."""
    from aot.utils import ai_card_fetch as fetcher
    try:
        target = fetcher.check_url(raw)
    except fetcher.FetchError:
        return None
    return Video('web', target.url, target.host, '', _label_name(target.host) or target.host)


def url_ext(url):
    """주소 경로의 소문자 확장자('mp4' …) 또는 ''."""
    try:
        path = urlsplit(url or '').path.lower()
    except ValueError:
        return ''
    return path.rsplit('.', 1)[-1] if '.' in path.rsplit('/', 1)[-1] else ''


def find_body_media(text, image_limit, video_limit, exclude=(), link_limit=0):
    """본문의 이미지·영상 후보를 등장 순서대로 [(오프셋, 'image'|'video', 원본 주소)].

    이미지 = `![](url)`(확장자 무관)·`[글](url)`·맨 주소(이미지 확장자만), 영상 = parse_video_url 이
    받는 주소. 영상 모양 주소는 `![](…)` 여도 이미지로 보지 않는다. 같은 주소는 한 번만. 종류별
    한도를 채우면 그 종류는 더 담지 않는다(가져오기 시도 수의 상한을 지키려는 것). exclude 는 이미
    명시 attach 로 쓴 주소(원본·정규화) — 중복으로 치고 건너뛴다."""
    from aot.utils import ai_card_fetch as fetcher
    out, seen = [], set(exclude)
    n_img = n_vid = n_link = 0
    if not isinstance(text, str):
        return out
    for pos, url, forced in fetcher.iter_md_links(text):
        if n_img >= image_limit and n_vid >= video_limit and n_link >= link_limit:
            break
        if url in seen:
            continue
        video = parse_video_url(url)
        if video is not None:
            if n_vid >= video_limit or video.url in seen \
                    or (video.provider == 'youtube'
                        and 'https://www.youtube.com/watch?v=%s' % video.id in seen):
                continue
            seen.update((url, video.url))
            if video.provider == 'youtube':   # 같은 영상의 watch·shorts 주소는 한 타일로
                seen.add('https://www.youtube.com/watch?v=%s' % video.id)
            out.append((pos, 'video', url))
            n_vid += 1
            continue
        if forced or fetcher._has_image_ext(url):
            if n_img >= image_limit:
                continue
            seen.add(url)
            out.append((pos, 'image', url))
            n_img += 1
            continue
        if n_link >= link_limit or url.split('#', 1)[0].split('?', 1)[0].lower().endswith(_NOT_PAGE_EXTS):
            continue
        web = parse_web_url(url)
        if web is None or web.url in seen:
            continue
        seen.update((url, web.url))
        out.append((pos, 'link', url))
        n_link += 1
    return out


def find_video_links(text, limit):
    """본문에서 영상으로 보이는 주소를 앞에서부터 limit 개: [(오프셋, 원본 주소)]."""
    if limit <= 0:
        return []
    return [(pos, url) for pos, kind, url in find_body_media(text, 0, limit)
            if kind == 'video']


# ── 포스터 ──────────────────────────────────────────────────────────────────

def fetch_poster(video, user, gate=None):
    """영상 하나의 포스터를 받아 Poster(jpeg 또는 None, 제목 또는 None, [(Attempt, 크기)]) 로.

    gate: 가져오기 시도 한 번마다 먼저 부르는 함수 — False 면 그 시도를 하지 않는다(post 하나의
    시도 예산 안에서만 받으려는 것; Vimeo 는 oEmbed 와 포스터 두 번이다).

    실패는 올리지 않는다 — 카드는 포스터 없이 영상 타일(아이콘)로 저장한다. 시도마다 감사 한 행이
    생기며(`fetch` 가 만든다), 성공한 시도의 `finish('ok', …)` 는 카드가 생긴 뒤 호출자가 한다."""
    from aot.utils import ai_card_fetch as fetcher
    from aot.utils import ai_card_files as files
    attempts = []
    title = None
    gate = gate or (lambda: True)
    try:
        if video.provider == 'youtube':
            if not gate():
                return Poster(None, None, attempts)
            got = fetcher.fetch('https://img.youtube.com/vi/%s/hqdefault.jpg' % video.id,
                                user, POSTER_MAX_BYTES, YOUTUBE_POSTER_HOSTS)
            attempts.append((got.attempt, len(got.data)))
        elif video.provider == 'vimeo':
            if not gate():
                return Poster(None, None, attempts)
            api = 'https://vimeo.com/api/oembed.json?url=' + quote(video.url, safe='')
            meta = fetcher.fetch(api, user, OEMBED_MAX_BYTES, VIMEO_OEMBED_HOSTS)
            attempts.append((meta.attempt, len(meta.data)))
            thumb_url, title = _parse_oembed(meta.data)
            if thumb_url is None:
                meta.attempt.finish('mismatch', len(meta.data))
                return Poster(None, None, attempts)
            if not gate():
                return Poster(None, title, attempts)
            got = fetcher.fetch(thumb_url, user, POSTER_MAX_BYTES, VIMEO_POSTER_HOSTS)
            attempts.append((got.attempt, len(got.data)))
        elif video.provider == 'web':
            if not gate():
                return Poster(None, None, attempts)
            page = fetcher.fetch(video.url, user, PAGE_MAX_BYTES, None, True)
            attempts.append((page.attempt, len(page.data)))
            image_url, title = parse_og(page.data, video.url)
            if image_url is None:
                page.attempt.finish('mismatch', len(page.data))
                return Poster(None, title, attempts)
            if not gate():
                return Poster(None, title, attempts)
            got = fetcher.fetch(image_url, user, POSTER_MAX_BYTES)
            attempts.append((got.attempt, len(got.data)))
        else:
            return Poster(None, None, attempts)
        ext = fetcher.sniff_ext(got.data)
        if ext not in (('jpg', 'webp', 'png') if video.provider == 'web' else ('jpg', 'webp')):
            got.attempt.finish('mismatch', len(got.data))
            return Poster(None, title, attempts)
        try:
            _mime, _kind, thumb = files.inspect_bytes(ext, got.data)
        except files.FileError:
            got.attempt.finish('mismatch', len(got.data))
            return Poster(None, title, attempts)
        return Poster(thumb, title, attempts)
    except files.FileError:                 # FetchError 포함 — 시도는 fetch 가 이미 기록했다
        return Poster(None, title, attempts)
    except Exception:
        logger.exception('[ai_card_video] 포스터 가져오기 예상 밖 오류')
        return Poster(None, title, attempts)


def parse_og(data, page_url):
    """웹페이지 앞부분 → (이미지 주소 또는 None, 제목 또는 None). 같은 이름의 태그가 여럿이면 **마지막**을
    먼저 보고(사이트 공통 로고가 먼저, 그 페이지의 것이 뒤에 오는 곳이 많다), 그 값이 무효(따옴표가 깨진
    마크업 등)이면 앞의 유효한 값으로 물러난다. 이미지 주소는 페이지 주소 기준 절대 https 로 바꾸고(http 는
    https 로 올린다 — 안 되면 받기에서 떨어진다), 따옴표·공백 등 위험 글자나 2048 자 초과는 버린다.
    값은 화면 속성에 들어가지 않는다(서버가 받아 재인코드한 포스터만 쓴다)."""
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(data.decode('utf-8', 'ignore'), 'html.parser')
    except Exception:
        return None, None
    images, title = [], None
    for tag in soup.find_all('meta'):
        key = (tag.get('property') or tag.get('name') or '').strip().lower()
        val = (tag.get('content') or '').strip()
        if not val:
            continue
        if key in _OG_NAMES:
            images.append(val)
        elif key in ('og:title', 'twitter:title'):
            title = val
    if not images and soup.title and soup.title.string:
        title = title or soup.title.string
    name = (_label_name(title) or None) if isinstance(title, str) else None
    for image in reversed(images):
        absolute = _og_image_url(image, page_url)
        if absolute:
            return absolute, name
    return None, name


def _og_image_url(image, page_url):
    from urllib.parse import urljoin
    if len(image) > 2048:
        return None
    try:
        absolute = urljoin(page_url, image)
    except ValueError:
        return None
    if absolute.startswith('http://'):
        absolute = 'https://' + absolute[len('http://'):]
    if not absolute.startswith('https://') or len(absolute) > 2048 \
            or any(ch in '"\'<>`\\ \t\r\n\f\v' for ch in absolute):
        return None
    return absolute


def _parse_oembed(data):
    """oEmbed JSON → (thumbnail_url 또는 None, 제목 또는 None). 모양·호스트가 틀리면 (None, None)."""
    from aot.utils import ai_card_fetch as fetcher
    try:
        doc = json.loads(data.decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        return None, None
    if not isinstance(doc, dict):
        return None, None
    thumb = doc.get('thumbnail_url')
    if not isinstance(thumb, str):
        return None, None
    try:
        target = fetcher.check_url(thumb)
    except fetcher.FetchError:
        return None, None
    if target.host not in VIMEO_POSTER_HOSTS:
        return None, None
    title = doc.get('title')
    return thumb, (_label_name(title) if isinstance(title, str) else None) or None


# ── 재생 가능 판정 ──────────────────────────────────────────────────────────

def judge_playable(video, user, over=None):
    """post 때 **한 번만** 부르는 판정(결과는 첨부 행의 playable 에 저장 — 목록·화면 명령·to_item 은
    DNS 를 하지 않는다): direct 이고 확장자가 mp4·webm 이고 호스트가 공인 IP 로만 풀릴 때 True.
    서버는 연결하지 않는다(DNS 만). 공용 DNS 실행기(2스레드)를 막지 않게 가져오기와 같은 규칙 안에서
    돈다 — 슬롯 2개·사용자당 동시 1건(바쁘면 False), post 가져오기 시간 예산(over() 가 참이면 False),
    DNS 2초. 사설로 풀리는 이름·실패는 False(새 탭 링크만)."""
    if video.provider != 'direct' or url_ext(video.url) not in PLAYABLE_EXTS or not video.host:
        return False
    if over is not None and over():
        return False
    from aot.utils import ai_card_fetch as fetcher
    try:
        with fetcher._admission(getattr(user, 'id', None)):
            fetcher.resolve_public(video.host, time.monotonic() + fetcher.DNS_S)
        return True
    except fetcher.FetchError:
        return False
