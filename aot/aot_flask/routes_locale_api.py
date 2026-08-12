from flask import Blueprint, jsonify, session, request
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
