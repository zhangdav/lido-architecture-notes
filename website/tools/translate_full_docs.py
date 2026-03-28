from __future__ import annotations

from pathlib import Path
import re
import time
from deep_translator import GoogleTranslator

root = Path('/Users/zhangdavid/lido-architecture-notes/website')
zh = root / 'i18n/zh-Hans/docusaurus-plugin-content-docs/current'
en = root / 'docs'

files = [
    ('00-overview.md','00-overview.md'),
    ('01-deposit-flow.md','01-deposit-flow.md'),
    ('02-module-lifecycle.md','02-module-lifecycle.md'),
    ('03-oracle-system.md','03-oracle-system.md'),
    ('04-accounting-oracle.md','04-accounting-oracle.md'),
    ('05-withdrawal-flow.md','05-withdrawal-flow.md'),
    ('06-fee-model.md','06-fee-model.md'),
    ('07-exit-bus-oracle.md','07-exit-bus-oracle.md'),
]

tr = GoogleTranslator(source='zh-CN', target='en')
inline_code = re.compile(r'`[^`]*`')
url = re.compile(r'https?://\S+')


def protect(s: str):
    slots = []
    def repl(m):
        slots.append(m.group(0))
        return f'__P{len(slots)-1}__'
    s = inline_code.sub(repl, s)
    s = url.sub(repl, s)
    return s, slots


def unprotect(s: str, slots):
    for i, v in enumerate(slots):
        s = s.replace(f'__P{i}__', v)
    return s


def translate_text(text: str) -> str:
    if not text.strip():
        return text
    p, slots = protect(text)
    if len(p) > 1200:
        parts = re.split(r'(\n\n+)', p)
        out = []
        for part in parts:
            if not part:
                continue
            if part.startswith('\n'):
                out.append(part)
                continue
            out.append(translate_text(part))
        return unprotect(''.join(out), slots)

    for _ in range(4):
        try:
            res = tr.translate(p)
            if res is None:
                res = p
            return unprotect(res, slots)
        except Exception:
            time.sleep(0.8)
    return unprotect(p, slots)


def translate_md(md: str) -> str:
    lines = md.splitlines()
    out = []
    in_code = False
    in_math = False
    for line in lines:
        s = line.strip()
        if s.startswith('```'):
            in_code = not in_code
            out.append(line)
            continue
        if s == '$$':
            in_math = not in_math
            out.append(line)
            continue
        if in_code or in_math:
            out.append(line)
            continue

        m = re.match(r'^(\s*#{1,6}\s+)(.*)$', line)
        if m:
            out.append(m.group(1) + translate_text(m.group(2)))
            continue
        m = re.match(r'^(\s*>\s?)(.*)$', line)
        if m:
            out.append(m.group(1) + translate_text(m.group(2)))
            continue
        m = re.match(r'^(\s*[-*+]\s+)(.*)$', line)
        if m:
            out.append(m.group(1) + translate_text(m.group(2)))
            continue
        m = re.match(r'^(\s*\d+\.\s+)(.*)$', line)
        if m:
            out.append(m.group(1) + translate_text(m.group(2)))
            continue
        out.append(translate_text(line))
    return '\n'.join(out) + '\n'


def main():
    for src_name, dst_name in files:
        md = (zh / src_name).read_text(encoding='utf-8')
        translated = translate_md(md)
        (en / dst_name).write_text(translated, encoding='utf-8')
        print(f'done {dst_name}', flush=True)


if __name__ == '__main__':
    main()
