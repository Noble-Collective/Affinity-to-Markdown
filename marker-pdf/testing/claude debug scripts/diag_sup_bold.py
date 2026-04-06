"""Check bold vs non-bold superscripts in latest output"""
import os, re

BASE = os.path.dirname(__file__)
mds = sorted([f for f in os.listdir(BASE) if f.endswith('.md') and not f.endswith('.raw.md')],
             key=lambda f: os.path.getmtime(os.path.join(BASE, f)))
latest = os.path.join(BASE, mds[-1])

with open(latest, encoding='utf-8') as f:
    content = f.read()

bold_sup = re.findall(r'\*\*<sup>.+?</sup>\*\*', content)
plain_sup = re.findall(r'(?<!\*\*)<sup>.+?</sup>(?!\*\*)', content)

with open(os.path.join(BASE, "diag_sup_bold.txt"), "w", encoding="utf-8") as out:
    out.write(f"Bold superscripts (**<sup>X</sup>**): {len(bold_sup)}\n")
    for s in bold_sup[:20]:
        out.write(f"  {s}\n")
    out.write(f"\nPlain superscripts (<sup>X</sup>): {len(plain_sup)}\n")
    for s in plain_sup[:20]:
        out.write(f"  {s}\n")
    
    # Also check for any remaining **digit** patterns that might be verse numbers
    bold_nums = re.findall(r'\*\*\d+[:\d\-]*\*\*', content)
    out.write(f"\nBold digit-only patterns (**N**): {len(bold_nums)}\n")
    for s in bold_nums[:20]:
        out.write(f"  {s}\n")

print("Written to testing/diag_sup_bold.txt")
