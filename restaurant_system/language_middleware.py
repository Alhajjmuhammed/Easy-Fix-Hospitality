"""Website language: English unless the person chose Kiswahili.

Deliberately NOT Django's LocaleMiddleware: that one follows the browser's language, which would
suddenly switch existing users' pages. Here the language only changes when someone picks it
(saved on their account, or in the session before they log in).
"""
from django.utils import translation

SUPPORTED = ('en', 'sw')
SESSION_KEY = 'site_language'


def language_for(request):
    user = getattr(request, 'user', None)
    if user is not None and user.is_authenticated:
        lang = getattr(user, 'language', '') or 'en'
    else:
        session = getattr(request, 'session', None)
        lang = session.get(SESSION_KEY, 'en') if session is not None else 'en'
    return lang if lang in SUPPORTED else 'en'


class UserLanguageMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        lang = language_for(request)
        translation.activate(lang)
        request.LANGUAGE_CODE = lang
        try:
            response = self.get_response(request)
        finally:
            translation.deactivate()
        response.headers.setdefault('Content-Language', lang)
        return response
