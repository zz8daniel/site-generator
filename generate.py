#!/usr/bin/env python3
"""
Static site generator driven by a plaintext content file plus an optional
cards file. Reads templates from ./template-site/ and writes a rendered
site to the --out directory.

Grammar (both content and cards files):
  # line comment
  key: value                 single-line scalar
  key >>>                    start multi-line block
  ...                        block body (newlines preserved; blank lines
  <<<                        separate paragraphs)
  key:                       start a bullet list
  - item                     each bullet
  - item

Cards file only:
  ---                        on its own line, separates cards

Tokens in templates:
  {{key}}                    substitute raw value
  {{key_html}}               substitute multi-line block rendered as
                             <p>paragraph</p><p>paragraph</p>
  {{card_1}}, {{card_2}}...  substitute Nth rendered card, or empty

Run:
  python generate.py content/bryant.txt --cards content/bryant.cards.txt --out dist/bryant
"""

import argparse
import re
import shutil
import sys
from pathlib import Path


def parse(path: Path) -> dict:
    """Parse a content file into a dict of {key: value}.

    Values are one of:
      - str (scalar or multi-line block, newlines preserved)
      - list[str] (bullet list)
    """
    lines = path.read_text(encoding='utf-8').splitlines()
    return _parse_block(lines)


def _parse_block(lines: list[str]) -> dict:
    """Parse a list of lines (one 'block' in the grammar). Used for the
    whole content file and for each card section between --- markers."""
    data: dict = {}
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Comments and blank lines
        if not stripped or stripped.startswith('#'):
            i += 1
            continue

        # Multi-line block: `key >>>` ... `<<<`
        m = re.match(r'^([A-Za-z_][A-Za-z0-9_]*)\s*>>>\s*$', line)
        if m:
            key = m.group(1)
            i += 1
            body = []
            while i < len(lines) and lines[i].strip() != '<<<':
                body.append(lines[i])
                i += 1
            if i >= len(lines):
                raise ValueError(f"unclosed >>> block for key '{key}'")
            data[key] = '\n'.join(body).strip('\n')
            i += 1  # skip the <<<
            continue

        # Bullet list: `key:` on its own, followed by `- item` lines
        m = re.match(r'^([A-Za-z_][A-Za-z0-9_]*):\s*$', line)
        if m and i + 1 < len(lines) and lines[i + 1].lstrip().startswith('- '):
            key = m.group(1)
            items = []
            i += 1
            while i < len(lines) and lines[i].lstrip().startswith('- '):
                items.append(lines[i].lstrip()[2:].strip())
                i += 1
            data[key] = items
            continue

        # Scalar: `key: value`
        m = re.match(r'^([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$', line)
        if m:
            key = m.group(1)
            value = m.group(2).strip()
            # Optional surrounding quotes (for values with leading/trailing
            # whitespace or colons that would otherwise confuse readers)
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                value = value[1:-1]
            data[key] = value
            i += 1
            continue

        raise ValueError(f"unrecognized line {i+1}: {line!r}")

    return data


def parse_cards(path: Path) -> list[dict]:
    """Parse a cards file into a list of card dicts. Cards separated by
    a line containing only '---'."""
    text = path.read_text(encoding='utf-8')
    # Strip comment-only lines before splitting so a leading '# ...' block
    # isn't glued to the first card.
    sections: list[list[str]] = [[]]
    for line in text.splitlines():
        if line.strip() == '---':
            sections.append([])
        else:
            sections[-1].append(line)
    cards = []
    for lines in sections:
        # Skip entirely empty/comment-only sections
        if not any(l.strip() and not l.strip().startswith('#') for l in lines):
            continue
        cards.append(_parse_block(lines))
    return cards


def paragraphs_html(text: str) -> str:
    """Render a multi-line block as <p>para</p><p>para</p> (paragraphs
    separated by blank lines). Single paragraphs become one <p>."""
    if not text:
        return ''
    paragraphs = re.split(r'\n\s*\n', text.strip())
    return '\n'.join(f'<p>{p.strip()}</p>' for p in paragraphs if p.strip())


def auto_col_span(n_cards: int) -> int:
    """12-column grid span per card, by card count."""
    if n_cards <= 0:
        return 12
    if n_cards == 1:
        return 12
    if n_cards == 2:
        return 6
    if n_cards == 3:
        return 4
    if n_cards == 4:
        return 3
    # 5+ cards: wrap at 3-per-row (col-4)
    return 4


def render_card(card: dict, col_span: int, card_tpl: str) -> str:
    """Render one card using the card.html fragment. Optional fields
    with no value render to empty strings."""
    intro = card.get('intro', '')
    bullets = card.get('bullets') or []
    price = card.get('price', '')
    name = card.get('name', '')

    intro_block = f'<p>{intro}</p>' if intro else ''
    bullets_block = ''
    if bullets:
        lis = ''.join(f'<li>{b}</li>' for b in bullets)
        bullets_block = f'<ul>{lis}</ul>'
    price_block = f'<p class="card__price">{price}</p>' if price else ''

    return _substitute(card_tpl, {
        'col_span': str(col_span),
        'name': name,
        'intro_block': intro_block,
        'bullets_block': bullets_block,
        'price_block': price_block,
    }, strict=True)


def _substitute(tpl: str, ctx: dict, strict: bool) -> str:
    """Replace every {{key}} with ctx[key]. If strict, raise on missing
    keys; otherwise replace with empty string."""
    missing: list[str] = []

    def sub(m: re.Match) -> str:
        key = m.group(1)
        if key in ctx:
            return str(ctx[key])
        if strict:
            missing.append(key)
        return ''

    out = re.sub(r'\{\{([A-Za-z_][A-Za-z0-9_]*)\}\}', sub, tpl)
    if missing:
        raise KeyError(f"missing template values: {sorted(set(missing))}")
    return out


def build_context(content: dict, cards: list[dict], card_tpl: str) -> dict:
    """Flatten the parsed content + rendered cards into a single dict
    of {token_name: string_value} for template substitution."""
    ctx: dict = {}

    # Scalars and lists from content. Strings pass through; lists render
    # as <li> items when requested via {{key_li}}.
    for k, v in content.items():
        if isinstance(v, list):
            ctx[k] = ''.join(f'<li>{x}</li>' for x in v)
            ctx[f'{k}_li'] = ctx[k]
        else:
            ctx[k] = v
            # Multi-line blocks also get a paragraph-rendered companion.
            ctx[f'{k}_html'] = paragraphs_html(v)

    # Rendered card slots. Unused slots (card_N past the card count) are
    # empty strings — templates can include extra {{card_N}} tokens safely.
    col = content.get('cards_per_row')
    col_span = int(col) if col else auto_col_span(len(cards))
    for i, card in enumerate(cards, start=1):
        ctx[f'card_{i}'] = render_card(card, col_span, card_tpl)

    return ctx


def copy_static(src: Path, out: Path) -> None:
    """Copy template-site/css and template-site/images verbatim to out."""
    for sub in ('css', 'images'):
        s = src / sub
        d = out / sub
        if s.exists():
            if d.exists():
                shutil.rmtree(d)
            shutil.copytree(s, d)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[1])
    ap.add_argument('content', help='path to the content file')
    ap.add_argument('--cards', help='path to the cards file (optional)')
    ap.add_argument('--out', required=True, help='output directory')
    ap.add_argument('--templates', default='template-site',
                    help='path to template directory (default: ./template-site)')
    args = ap.parse_args()

    content_path = Path(args.content)
    tpl_dir = Path(args.templates)
    out_dir = Path(args.out)

    content = parse(content_path)
    cards = parse_cards(Path(args.cards)) if args.cards else []
    card_tpl = (tpl_dir / 'card.html').read_text(encoding='utf-8')

    ctx = build_context(content, cards, card_tpl)

    # Extra card slots referenced in pages but not present in cards file
    # render to empty strings (non-strict substitution only for card_N).
    max_card_slot = 99  # well above any reasonable page count
    for i in range(1, max_card_slot + 1):
        ctx.setdefault(f'card_{i}', '')

    out_dir.mkdir(parents=True, exist_ok=True)
    pages = ['index', 'about', 'services', 'contact', 'thank-you']
    for page in pages:
        src = tpl_dir / f'{page}.html'
        tpl = src.read_text(encoding='utf-8')
        try:
            rendered = _substitute(tpl, ctx, strict=True)
        except KeyError as e:
            print(f"error rendering {page}.html: {e}", file=sys.stderr)
            return 1
        (out_dir / f'{page}.html').write_text(rendered, encoding='utf-8')
        print(f"wrote {out_dir / (page + '.html')}")

    copy_static(tpl_dir, out_dir)
    print(f"copied css/ and images/ to {out_dir}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
