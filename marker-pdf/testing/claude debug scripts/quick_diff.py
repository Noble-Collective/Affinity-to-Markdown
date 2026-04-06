"""Quick diff: find all differences between output (17) and (20)"""
f17 = open(r"C:\Users\Steve\Affinity-to-Markdown\marker-pdf\testing\2026-04-03 HomeStead-Interior-Affinity Design-v1.001 (17).md", encoding="utf-8").readlines()
f20 = open(r"C:\Users\Steve\Affinity-to-Markdown\marker-pdf\testing\2026-04-03 HomeStead-Interior-Affinity Design-v1.001 (20).md", encoding="utf-8").readlines()

import difflib
diff = list(difflib.unified_diff(f17, f20, fromfile="(17)", tofile="(20)", lineterm="", n=2))
for line in diff[:200]:
    print(line)
print(f"\nTotal diff lines: {len(diff)}")
