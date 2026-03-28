from pathlib import Path
import re
import time
from deep_translator import GoogleTranslator

root = Path('/Users/zhangdavid/lido-architecture-notes/website/docs')
tr = GoogleTranslator(source='zh-CN', target='en')
han_re = re.compile(r'[\u4e00-\u9fff]')
inline_code = re.compile(r'`[^`]*`')


def protect(s: str):
    slots = []
    def repl(m):
        slots.append(m.group(0))
        return f'__P{len(slots)-1}__'
    return inline_code.sub(repl, s), slots


def unprotect(s: str, slots):
    for i, v in enumerate(slots):
        s = s.replace(f'__P{i}__', v)
    return s

for path in sorted(root.glob('*.md')):
    lines = path.read_text(encoding='utf-8').splitlines()
    changed = 0
    for i, line in enumerate(lines):
        if not han_re.search(line):
            continue
        p, slots = protect(line)
        out = p
        for _ in range(4):
            try:
                t = tr.translate(p)
                if t is not None:
                    out = t
                break
            except Exception:
                time.sleep(0.8)
        out = unprotect(out, slots)
        lines[i] = out
        changed += 1
    if changed:
        path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(path.name, changed)
