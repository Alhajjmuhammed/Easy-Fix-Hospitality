from django.shortcuts import redirect
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .language_middleware import SESSION_KEY, SUPPORTED


@require_POST
def set_language(request):
    """English / Kiswahili switch: saved on the account (logged in) or in the session."""
    lang = request.POST.get('language')
    if lang in SUPPORTED:
        if request.user.is_authenticated:
            request.user.language = lang
            request.user.save(update_fields=['language'])
        request.session[SESSION_KEY] = lang
    nxt = request.POST.get('next') or request.META.get('HTTP_REFERER') or '/'
    if not url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        nxt = '/'
    return redirect(nxt)
