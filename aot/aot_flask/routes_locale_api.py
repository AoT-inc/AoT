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
        # Prevent caching so language switches are immediate, or use Vary
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        return response
    except Exception as e:
        return Response(f"console.error('Error loading translations: {str(e)}');", mimetype='application/javascript')
