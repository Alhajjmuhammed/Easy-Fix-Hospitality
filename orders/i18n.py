"""Kiswahili for texts the server sends itself (push notifications, SMS).

The English text is the key; a text without a translation goes out in English. Placeholders use
str.format names: tr('sw', 'Table for {party} on {when}', party=4, when='…').
Please have a native speaker review these.
"""

SW = {
    # Push: order status (customer)
    'Order Confirmed ✅': 'Oda Imethibitishwa ✅',
    'Your order has been confirmed and will be prepared shortly.': 'Oda yako imethibitishwa na itaandaliwa hivi punde.',
    'Being Prepared 👨‍🍳': 'Inaandaliwa 👨‍🍳',
    'Your order is now being prepared.': 'Oda yako inaandaliwa sasa.',
    'Order Ready 🍽️': 'Oda Iko Tayari 🍽️',
    'Your order is ready and will be served shortly.': 'Oda yako iko tayari na italetwa hivi punde.',
    'Your order is ready for pickup.': 'Oda yako iko tayari kuchukuliwa.',
    'Your order is ready and will be handed to the rider shortly.': 'Oda yako iko tayari na itakabidhiwa kwa msafirishaji hivi punde.',
    'Served 🎉': 'Imeletwa 🎉',
    'Your order has been served. Enjoy your meal!': 'Oda yako imeletwa. Karibu chakula!',
    'On the Way 🛵': 'Iko Njiani 🛵',
    'Your order is out for delivery.': 'Oda yako iko njiani kukufikia.',
    'Delivered ✅': 'Imefikishwa ✅',
    'Your order has been delivered. Enjoy!': 'Oda yako imefikishwa. Karibu!',
    'Order Cancelled ❌': 'Oda Imeghairiwa ❌',
    'Your order has been cancelled.': 'Oda yako imeghairiwa.',
    # Push: reservations (customer)
    'Reservation Confirmed ✅': 'Nafasi Imethibitishwa ✅',
    'Your table for {party} on {when} is confirmed.': 'Meza yako ya {party} tarehe {when} imethibitishwa.',
    'Reservation Not Available': 'Nafasi Haipatikani',
    'Sorry, we could not confirm your table for {when}.': 'Samahani, hatukuweza kuthibitisha meza yako ya {when}.',
    'Reservation Cancelled': 'Nafasi Imeghairiwa',
    'Your reservation for {when} has been cancelled.': 'Nafasi yako ya {when} imeghairiwa.',
    '{n} people': 'watu {n}',
    # Push: rating reply (customer)
    'The restaurant replied 💬': 'Mgahawa umejibu 💬',
    # SMS (customer) — kept short and plain (one SMS part)
    '{name}: order #{number} confirmed.': '{name}: oda #{number} imethibitishwa.',
    '{name}: order #{number} is ready for pickup.': '{name}: oda #{number} iko tayari kuchukuliwa.',
    '{name}: order #{number} is on the way.': '{name}: oda #{number} iko njiani.',
    '{name}: order #{number} delivered. Enjoy!': '{name}: oda #{number} imefikishwa. Karibu!',
    '{name}: received {currency} {amount} for order #{number}. Thank you!':
        '{name}: tumepokea {currency} {amount} kwa oda #{number}. Asante!',
    '{name}: table for {party} on {when} confirmed.': '{name}: meza ya watu {party} tarehe {when} imethibitishwa.',
    '{name}: sorry, we cannot confirm your table for {when}.': '{name}: samahani, hatuwezi kuthibitisha meza yako ya {when}.',
    '{name}: your booking for {when} is cancelled.': '{name}: nafasi yako ya {when} imeghairiwa.',
}

SW_DAYS = {'Mon': 'Jumatatu', 'Tue': 'Jumanne', 'Wed': 'Jumatano', 'Thu': 'Alhamisi', 'Fri': 'Ijumaa',
           'Sat': 'Jumamosi', 'Sun': 'Jumapili'}
SW_MONTHS = {'Jan': 'Jan', 'Feb': 'Feb', 'Mar': 'Mac', 'Apr': 'Apr', 'May': 'Mei', 'Jun': 'Jun', 'Jul': 'Jul',
             'Aug': 'Ago', 'Sep': 'Sep', 'Oct': 'Okt', 'Nov': 'Nov', 'Dec': 'Des'}


def language_of(user):
    lang = getattr(user, 'language', '') or 'en'
    return lang if lang in ('en', 'sw') else 'en'


def tr(language, text, **params):
    if language == 'sw':
        text = SW.get(text, text)
    try:
        return text.format(**params) if params else text
    except (KeyError, IndexError, ValueError):
        return text


def when_text(language, dt_local, fmt='%a %d %b, %H:%M'):
    """'Fri 07 Nov, 19:00' → 'Ijumaa 07 Nov, 19:00' in Kiswahili."""
    text = dt_local.strftime(fmt)
    if language == 'sw':
        for en, sw in SW_DAYS.items():
            text = text.replace(en, sw)
        for en, sw in SW_MONTHS.items():
            text = text.replace(en, sw)
    return text
