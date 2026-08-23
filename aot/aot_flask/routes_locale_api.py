import flask_login
from flask import Blueprint, current_app, jsonify, session, request
from flask_babel import get_locale

blueprint = Blueprint('routes_locale_api', __name__)

@blueprint.route('/api/v1/locale', methods=['GET'])
def get_current_locale():
    """Returns the current locale as determined by Flask-Babel"""
    return jsonify({
        'locale': str(get_locale()),
        'supported_locales': ['ko', 'en', 'ja', 'de', 'es', 'fr', 'id', 'it', 'nn', 'nl', 'pl', 'pt', 'ru', 'sr', 'sv', 'tr', 'zh']
    })

@blueprint.route('/api/v1/locale/set', methods=['POST'])
def set_current_locale():
    """Force sets the locale in the session (if supported)"""
    data = request.get_json(silent=True) or {}
    new_locale = data.get('locale')
    if new_locale:
        session['language'] = new_locale
        return jsonify({'ok': True, 'locale': new_locale})
    return jsonify({'error': 'No locale provided'}), 400

@blueprint.route('/api/v1/locale/js', methods=['GET'])
def get_js_translations():
    """
    Returns the current locale's translation catalog as a JavaScript file.
    This allows the frontend to have access to all translations without
    hardcoding them in the HTML.
    """
    from flask import Response
    from flask_babel import get_translations
    import json

    try:
        translations = get_translations()
        # Access the internal catalog. safe_access logic
        catalog = {}
        if hasattr(translations, '_catalog'):
            catalog = translations._catalog
        
        # JSON dump the catalog
        json_catalog = json.dumps(catalog, ensure_ascii=False)
        
        # Create JS content
        js_content = f"window.AOT_I18N = {json_catalog};"
        
        response = Response(js_content, mimetype='application/javascript')
        # 언어별로 캐시 (10분). 카탈로그가 500KB 대라 캐시 자체는 유지해야 한다.
        #
        # Vary 에 Accept-Language 가 필수다 — get_locale() 의 마지막 폴백이
        # Accept-Language 라서 이 응답은 그 헤더로 내용이 갈린다. 예전에는 Cookie 만
        # 있어서, 아이폰 시스템 언어를 바꿔도(쿠키는 그대로) 캐시가 옛 언어 카탈로그를
        # 최대 10분 그대로 내줬다. 서버 렌더 HTML 은 no-cache 라 즉시 새 언어로 바뀌므로
        # 한 화면에 두 언어가 섞여 보였다.
        #
        # 무효화의 정본은 layout 이 붙이는 ?lang= 지문이고(계정 언어 변경처럼
        # Accept-Language 도 쿠키도 안 바뀌는 경로를 그쪽이 덮는다), 이 Vary 는
        # 중간 프록시(엣지) 대응이다. 둘 다 필요하다.
        response.headers['Cache-Control'] = 'private, max-age=600'
        response.headers['Vary'] = 'Cookie, Accept-Language'
        return response
    except Exception as e:
        return Response(f"console.error('Error loading translations: {str(e)}');", mimetype='application/javascript')


# ---------------------------------------------------------------------------
# 사용자 지정 문자열 번역 — docs/design/user-string-live-translation.md
#
# gettext 카탈로그(위의 /locale/js)는 소스에 박힌 문구만 덮는다. 사용자가 지은
# 이름은 DB 원문 그대로 나가므로, 다국어 계정으로 열면 한 화면에 두 언어가
# 섞인다. 아래 두 라우트가 그 이름들의 번역 사전을 브라우저로 나른다.
# ---------------------------------------------------------------------------

def _translation_target_lang():
    """번역 대상 언어. 꺼져 있거나 판정 불가면 None."""
    try:
        import flask_login
        from aot.ai.services import user_string_translator as ust

        if not ust.is_enabled():
            return None

        # 사용자별 토글 — NULL 은 "전역 설정을 따른다".
        try:
            user = flask_login.current_user
            if user is not None and getattr(user, 'is_authenticated', False):
                pref = getattr(user, 'translate_user_strings', None)
                if pref is False:
                    return None
        except Exception:
            pass

        return str(get_locale())
    except Exception:
        return None


@blueprint.route('/api/v1/locale/user_strings.js', methods=['GET'])
@flask_login.login_required
def get_user_string_catalog():
    """사용자 지정 이름의 번역 사전을 JS 로 내려준다.

    바로 위 gettext 카탈로그(`/locale/js`)와 달리 **로그인이 필요하다** — 이쪽은
    장치명·구역명·작물명, 즉 그 농장의 사용자 데이터를 담는다. 로그인 화면에서
    쓸 일도 없다(layout 은 인증 후에만 렌더된다).

    `AOT_USER_I18N` 은 확정된 번역, `AOT_USER_I18N_PENDING` 은 "번역 대상이지만
    아직 번역본이 없는" 원문이다. 브라우저는 pending 문자열을 화면에서 실제로
    만났을 때만 번역을 요청한다 — 보이지도 않는 이름을 미리 번역하느라 호출을
    쓰지 않기 위해서다.

    실패해도 화면은 원문으로 정상 동작해야 하므로, 어떤 오류에서도 빈 사전을
    돌려주고 끝낸다.
    """
    from flask import Response
    import json

    empty = ("window.AOT_USER_I18N = {};"
             "window.AOT_USER_I18N_PENDING = [];"
             "window.AOT_USER_I18N_LANG = null;")

    lang = _translation_target_lang()
    if not lang:
        response = Response(empty, mimetype='application/javascript')
        response.headers['Cache-Control'] = 'private, max-age=60'
        response.headers['Vary'] = 'Cookie, Accept-Language'
        return response

    try:
        from aot.ai.services import user_string_translator as ust
        catalog = ust.build_catalog(lang)
        js = (
            f"window.AOT_USER_I18N = "
            f"{json.dumps(catalog['entries'], ensure_ascii=False)};"
            f"window.AOT_USER_I18N_PENDING = "
            f"{json.dumps(catalog['pending'], ensure_ascii=False)};"
            f"window.AOT_USER_I18N_LANG = {json.dumps(lang)};"
        )
    except Exception:
        current_app.logger.exception("user_strings.js: build_catalog failed")
        js = empty

    response = Response(js, mimetype='application/javascript')
    # 무효화의 정본은 layout 이 붙이는 ?v= 지문이다. 위의 카탈로그 라우트와 같은
    # 이유로 Vary 에 Accept-Language 가 필요하다(엣지 캐시 대응).
    response.headers['Cache-Control'] = 'private, max-age=300'
    response.headers['Vary'] = 'Cookie, Accept-Language'
    return response


@blueprint.route('/api/v1/locale/user_strings/translate', methods=['POST'])
@flask_login.login_required
def translate_user_strings():
    """화면에 실제로 보이는 미번역 문자열을 즉시 번역한다.

    로그인이 필요하다 — 이 경로는 LLM 호출을 유발하므로, 열어 두면 비용을
    태우는 데 쓰일 수 있다.

    브라우저가 pending 문자열을 DOM 에서 만났을 때 부르는 경로다.
    """
    lang = _translation_target_lang()
    if not lang:
        return jsonify({'entries': {}, 'pending': [], 'enabled': False})

    data = request.get_json(silent=True) or {}
    texts = data.get('texts') or []
    if not isinstance(texts, list):
        return jsonify({'error': 'texts must be a list'}), 400

    # 한 번에 받는 양을 제한한다 — 요청 하나가 LLM 호출을 무한히 유발하면 안 된다.
    texts = [t for t in texts if isinstance(t, str)][:100]
    if not texts:
        return jsonify({'entries': {}, 'pending': [], 'enabled': True})

    try:
        from aot.ai.services import user_string_translator as ust
        result = ust.translate_now(texts, lang)
    except Exception:
        current_app.logger.exception("translate_user_strings failed")
        return jsonify({'entries': {}, 'pending': texts, 'enabled': True})

    result['enabled'] = True
    return jsonify(result)
