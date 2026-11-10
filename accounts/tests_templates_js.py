"""A literal closing script tag inside inline JavaScript (even in a comment or string) ends the
<script> block early: the page's whole script dies with a SyntaxError. Every template must have
as many <script openings as </script closings."""
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


class TemplateScriptBalanceTests(SimpleTestCase):
    def test_script_tags_balanced(self):
        root = Path(settings.BASE_DIR) / 'templates'
        bad = []
        for path in root.rglob('*.html'):
            text = path.read_text(encoding='utf-8', errors='ignore')
            opened = len(re.findall(r'<script\b', text, re.I))
            closed = len(re.findall(r'</script', text, re.I))
            if opened != closed:
                bad.append(f'{path.relative_to(root)}: {opened} <script vs {closed} </script')
        self.assertEqual(bad, [])
