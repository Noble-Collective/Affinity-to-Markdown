"""Test _callout_regex on Steve's Python 3.14"""
import re, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from run import _callout_regex

ct = "Relationship with God best outfits us for our parenting vocation."
rx = _callout_regex(ct)
print(f"Python: {sys.version}")
print(f"re.escape(' '): {repr(re.escape(' '))}")
print(f"Pattern (first 80): {rx.pattern[:80]}")
text = "Relationship with God best outfits us for our parenting vocation"
print(f"Match plain: {bool(rx.search(text))}")
text2 = "blah\n\nRelationship with God best outfits us for our parenting vocation blah"
print(f"Match newline: {bool(rx.search(text2))}")
