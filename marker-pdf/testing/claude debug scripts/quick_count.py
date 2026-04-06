"""Quick count of callout tags in latest output"""
import os, re
BASE = os.path.dirname(__file__)
for name in ['raw_processed.md', '(34).md', '(33).md', '(32).md']:
    path = os.path.join(BASE, f"2026-04-03 HomeStead-Interior-Affinity Design-v1.001 {name}" if '(' in name else os.path.join(BASE, f"2026-04-03 HomeStead-Interior-Affinity Design-v1.001.{name}"))
    if os.path.exists(path):
        with open(path, encoding='utf-8') as f:
            content = f.read()
        tags = re.findall(r'<Callout>', content)
        believers = 'For all believers' in content and '<Callout>' in content[content.index('For all believers')-50:content.index('For all believers')+200] if 'For all believers' in content else False
        print(f"{os.path.basename(path)}: {len(tags)} <Callout> tags, believers tagged: {believers}")
        break
