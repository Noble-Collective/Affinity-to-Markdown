"""Test relaxed regex on the 'eventually' case"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from run import _callout_regex, _callout_regex_relaxed

ct = "The aim of parenting is to release the next generation into the world, rooted in uncompromising godliness and fervent faith."
body = "The aim of parenting is to eventually release the next generation into the world, rooted in uncompromising godliness and fervent faith."

rx = _callout_regex(ct)
print(f"Standard regex match: {bool(rx.search(body))}")

rx2 = _callout_regex_relaxed(ct)
if rx2:
    print(f"Relaxed regex match: {bool(rx2.search(body))}")
    m = rx2.search(body)
    if m:
        print(f"Matched text: {m.group()[:80]}...")
else:
    print("Relaxed regex returned None")
