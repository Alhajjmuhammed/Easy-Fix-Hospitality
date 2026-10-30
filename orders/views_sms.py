"""SMS settings page (owners): Africa's Talking account, which texts to send, test message, log."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from .models_sms import SmsAccount, SmsLog
from . import sms as svc


@login_required
def sms_settings(request):
    user = request.user
    if not svc.sms_enabled():
        messages.info(request, 'SMS messages are not available yet.')
        return redirect('restaurant:home')
    if not user.is_any_owner():
        messages.error(request, 'Only restaurant owners can set up SMS.')
        return redirect('restaurant:home')
    from cashier.loyalty import business_owner
    business = business_owner(user)
    can_edit = business == user
    account = SmsAccount.objects.filter(owner=business).first() or SmsAccount(owner=business)

    if request.method == 'POST':
        if not can_edit:
            messages.error(request, 'SMS is set up by the main restaurant owner.')
            return redirect('orders:sms_settings')
        creds = account.credentials
        username = (request.POST.get('username') or '').strip()[:100]
        api_key = (request.POST.get('api_key') or '').strip().replace('\x00', '')[:200]
        creds['username'] = username
        if api_key:                                   # empty = keep the saved key
            creds['api_key'] = api_key
        account.credentials = creds
        account.sender_id = (request.POST.get('sender_id') or '').strip()[:11]
        account.environment = 'live' if request.POST.get('environment') == 'live' else 'sandbox'
        account.events = [k for k, _ in SmsAccount.EVENTS if request.POST.get(f'event_{k}') == 'on']
        account.enabled = request.POST.get('enabled') == 'on'
        if account.enabled and not (creds.get('username') and creds.get('api_key')):
            account.enabled = False
            messages.warning(request, 'Saved, but switched off until the username and API key are filled in.')
        account.save()
        if request.POST.get('action') == 'test':
            log = svc.send(business, 'test', request.POST.get('test_phone', ''),
                           'Test message from your restaurant system. SMS is working!', force=True)
            if log is None:
                messages.error(request, 'Test not sent: switch SMS on, fill in the account and enter a valid '
                                        'phone number of your country.')
            else:
                log.refresh_from_db()
                if log.status == 'sent':
                    messages.success(request, f'Test message sent to {log.to}.')
                else:
                    messages.error(request, f'Test message failed: {log.error or "not sent"}')
        else:
            messages.success(request, 'SMS settings saved.')
        return redirect('orders:sms_settings')

    return render(request, 'orders/sms_settings.html', {
        'account': account,
        'can_edit': can_edit,
        'username': account.credentials.get('username', ''),
        'key_saved': bool(account.credentials.get('api_key')),
        'events': [(k, label, k in (account.events or [])) for k, label in SmsAccount.EVENTS],
        # Customers' numbers and texts: only for the owner who runs the account (not other branches)
        'logs': SmsLog.objects.filter(account=account)[:30] if account.pk and can_edit else [],
    })
