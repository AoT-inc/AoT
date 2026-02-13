from flask_restx import Resource
from flask_babel import get_locale
from aot.aot_flask.api import api, default_responses

ns_locale = api.namespace('locale', description='Locale operations', path='/v1/locale')

@ns_locale.route('')
class CurrentLocale(Resource):
    @ns_locale.doc(responses=default_responses)
    def get(self):
        """Returns the current locale and supported locales"""
        return {
            'locale': str(get_locale()),
            'supported_locales': ['ko', 'en', 'ja', 'de', 'es', 'fr', 'id', 'it', 'nn', 'nl', 'pl', 'pt', 'ru', 'sr', 'sv', 'tr', 'zh']
        }
