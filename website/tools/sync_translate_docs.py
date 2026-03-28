from __future__ import annotations

from pathlib import Path
import re
import time
from deep_translator import GoogleTranslator

ROOT = Path('/Users/zhangdavid/lido-architecture-notes')
WEBSITE = ROOT / 'website'
SRC_DOCS = ROOT / 'docs'
ZH_DST = WEBSITE / 'i18n/zh-Hans/docusaurus-plugin-content-docs/current'
EN_DST = WEBSITE / 'docs'

MAP = [
    ('00_lido_overview.md', '00-overview.md'),
    ('01_deposit_flow.md', '01-deposit-flow.md'),
    ('02_module_lifecycle.md', '02-module-lifecycle.md'),
    ('03_oracle_system.md', '03-oracle-system.md'),
    ('04_accounting_oracle.md', '04-accounting-oracle.md'),
    ('05_withdrawal_flow.md', '05-withdrawal-flow.md'),
    ('06_fee_model.md', '06-fee-model.md'),
    ('07_exit_bus_oracle.md', '07-exit-bus-oracle.md'),
]

translator = GoogleTranslator(source='zh-CN', target='en')

INLINE_CODE_RE = re.compile(r'`[^`]*`')
URL_RE = re.compile(r'https?://\S+')


def normalize_md(text: str) -> str:
    text = text.replace('./diagrams/', '/img/diagrams/')
    text = text.replace('../diagrams/', '/img/diagrams/')
    text = text.replace('<br>', '<br />')
    return text


def protect_segments(s: str):
    slots: list[str] = []

    def repl(m):
        idx = len(slots)
        slots.append(m.group(0))
        return f'__P{idx}__'

    s2 = INLINE_CODE_RE.sub(repl, s)
    s2 = URL_RE.sub(repl, s2)
    return s2, slots


def unprotect_segments(s: str, slots: list[str]) -> str:
    for i, v in enumerate(slots):
        s = s.replace(f'__P{i}__', v)
    return s


def translate_line(line: str, in_code: bool, in_math: bool) -> str:
    raw = line.rstrip('\n')
    if in_code or in_math:
        return raw
    if raw.strip() == '':
        return raw

    m = re.match(r'^(\s*#{1,6}\s+)(.*)$', raw)
    if m:
        prefix, content = m.group(1), m.group(2)
        return prefix + translate_text(content)

    m = re.match(r'^(\s*>\s?)(.*)$', raw)
    if m:
        prefix, content = m.group(1), m.group(2)
        if content.strip() == '':
            return raw
        return prefix + translate_text(content)

    m = re.match(r'^(\s*[-*+]\s+)(.*)$', raw)
    if m:
        prefix, content = m.group(1), m.group(2)
        return prefix + translate_text(content)

    m = re.match(r'^(\s*\d+\.\s+)(.*)$', raw)
    if m:
        prefix, content = m.group(1), m.group(2)
        return prefix + translate_text(content)

    return translate_text(raw)


def translate_text(text: str) -> str:
    stripped = text.strip()
    if stripped == '' or all(ch in '-_=*`~>' for ch in stripped):
        return text

    protected, slots = protect_segments(text)
    out = protected

    # Skip likely code-like lines even outside fenced blocks
    if re.search(r'->|::|\{|\}|\(|\)|\[|\]|;|\$\$', protected) and re.search(r'[A-Za-z_]{2,}', protected):
        return text

    for _ in range(3):
        try:
            translated = translator.translate(protected)
            out = translated
            break
        except Exception:
            time.sleep(0.6)
    out = unprotect_segments(out, slots)
    return out


def make_english(md: str) -> str:
    lines = md.splitlines()
    out: list[str] = []
    in_code = False
    in_math = False

    for line in lines:
        stripped = line.strip()
        if stripped.startswith('```'):
            in_code = not in_code
            out.append(line)
            continue
        if stripped == '$$':
            in_math = not in_math
            out.append(line)
            continue

        out.append(translate_line(line + '\n', in_code, in_math))

    return '\n'.join(out) + '\n'


def main():
    for src_name, dst_name in MAP:
        src = SRC_DOCS / src_name
        zh_dst = ZH_DST / dst_name
        en_dst = EN_DST / dst_name

        text = src.read_text(encoding='utf-8')
        text = normalize_md(text)
        zh_dst.write_text(text, encoding='utf-8')

        en_text = make_english(text)
        en_dst.write_text(en_text, encoding='utf-8')
        print(f'processed {src_name}')


if __name__ == '__main__':
    main()
