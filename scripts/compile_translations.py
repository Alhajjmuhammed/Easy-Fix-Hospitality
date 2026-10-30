"""Compile locale/*/LC_MESSAGES/django.po → django.mo without GNU gettext (not installed on Windows).

Run after editing a .po file:   python scripts/compile_translations.py
The .mo files are committed, so the server needs nothing extra.
Supports the subset of the .po format used here: msgctxt-free entries, msgid/msgstr (multi-line),
and msgid_plural/msgstr[n]. Fuzzy entries are skipped.
"""
import ast
import struct
import sys
from pathlib import Path


def parse_po(text):
    entries, cur, field, fuzzy = [], {}, None, False

    def flush():
        nonlocal cur, fuzzy
        if 'msgid' in cur and not fuzzy:
            entries.append(cur)
        cur, fuzzy = {}, False

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            flush()
            field = None
            continue
        if line.startswith('#,') and 'fuzzy' in line:
            fuzzy = True
            continue
        if line.startswith('#'):
            continue
        if line.startswith('"'):
            cur[field] += ast.literal_eval(line)
            continue
        key, _, value = line.partition(' ')
        if key in ('msgctxt', 'msgid', 'msgid_plural', 'msgstr') or key.startswith('msgstr['):
            if key in ('msgctxt', 'msgid') and 'msgid' in cur:
                flush()
            field = key
            cur[field] = ast.literal_eval(value)
    flush()
    return entries


def build_mo(entries):
    catalog = {}
    for e in entries:
        prefix = e['msgctxt'] + '\x04' if 'msgctxt' in e else ''   # {% translate "x" context "y" %}
        if 'msgid_plural' in e:
            forms = [e[k] for k in sorted(k for k in e if k.startswith('msgstr['))]
            if any(forms):
                catalog[prefix + e['msgid'] + '\0' + e['msgid_plural']] = '\0'.join(forms)
        elif e.get('msgstr') or e['msgid'] == '':
            catalog[prefix + e['msgid']] = e.get('msgstr', '')
    keys = sorted(catalog)
    ids = b''.join(k.encode() + b'\0' for k in keys)
    strs = b''.join(catalog[k].encode() + b'\0' for k in keys)
    n = len(keys)
    start = 7 * 4 + 16 * n
    offsets, o = [], 0
    for k in keys:
        offsets.append((len(k.encode()), start + o))
        o += len(k.encode()) + 1
    t_offsets, o = [], 0
    for k in keys:
        v = catalog[k].encode()
        t_offsets.append((len(v), start + len(ids) + o))
        o += len(v) + 1
    out = struct.pack('Iiiiiii', 0x950412de, 0, n, 7 * 4, 7 * 4 + 8 * n, 0, 0)
    out += b''.join(struct.pack('ii', ln, off) for ln, off in offsets)
    out += b''.join(struct.pack('ii', ln, off) for ln, off in t_offsets)
    return out + ids + strs


def main():
    """django.po (header + shared words) plus every locale/<lang>/parts/*.po (one per area, so
    several people can work at once) are merged into LC_MESSAGES/django.mo."""
    root = Path(__file__).resolve().parent.parent / 'locale'
    problems = 0
    for po in root.glob('*/LC_MESSAGES/django.po'):
        sources = [po] + sorted((po.parent.parent / 'parts').glob('*.po'))
        merged, seen = [], {}
        for src in sources:
            for e in parse_po(src.read_text(encoding='utf-8')):
                key = (e['msgctxt'] + '\x04' if 'msgctxt' in e else '') + e['msgid'] + \
                    ('\0' + e['msgid_plural'] if 'msgid_plural' in e else '')
                if key in seen:
                    if seen[key][1] != e.get('msgstr') and key:
                        problems += 1
                        print(f'  CONFLICT {key!r}: {seen[key][0].name} vs {src.name}')
                    continue
                seen[key] = (src, e.get('msgstr'))
                merged.append(e)
        po.with_suffix('.mo').write_bytes(build_mo(merged))
        print(f'{po.relative_to(root.parent)} + {len(sources) - 1} part file(s): '
              f'{sum(1 for e in merged if e.get("msgstr"))} translations')
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main())
