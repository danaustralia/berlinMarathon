from pathlib import Path
import re

root = Path(__file__).resolve().parents[1] / 'public'
patterns = [r'RunnerID', r'BibNumber', r'raw\.githubusercontent', r'BM_export_']
failed = False
for path in root.rglob('*'):
    if not path.is_file():
        continue
    try:
        text = path.read_text(encoding='utf-8')
    except UnicodeDecodeError:
        continue
    for pat in patterns:
        if re.search(pat, text, flags=re.I):
            print(f'FAIL {path.relative_to(root)} contains /{pat}/')
            failed = True
if failed:
    raise SystemExit(1)
print('PASS: public/ contains no raw runner identifiers or raw-CSV links.')
