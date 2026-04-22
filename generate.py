#!/usr/bin/env python3
"""
Static site generator driven by a single plaintext content file.
Reads templates from ./template-site/ and writes a rendered site to the
--out directory.

Grammar:
  # line comment
  key: value                 single-line scalar
  key >>>                    start multi-line block
  ...                        block body (newlines preserved; blank lines
  <<<                        separate paragraphs)
  key:                       start a bullet list
  - item                     each bullet
  - item
  ---                        on its own line, separates records

File structure:
  The first record (everything before the first `---`) is global content:
  scalars, `nav:`, `pages:`. Every record after that is either a section
  (rendered into pages by `type:`) or a card (`type: card` with a unique
  `name:`, referenced by `cards`-type sections).

Tokens in templates:
  {{key}}                    substitute raw value
  {{key_html}}               substitute multi-line block rendered as
                             <p>paragraph</p><p>paragraph</p>
  {{nav}} / {{footer}}       rendered nav/footer partials (on page templates)
  {{sections}}               concatenated sections for this page
  {{cards_html}}             (inside a cards-type section) rendered cards

Run:
  python generate.py content/bryant.txt --out dist/bryant
"""

import argparse
import re
import shutil
import sys
import time
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=None)
def _read_template(path: Path) -> str:
    return path.read_text(encoding='utf-8')


def _parse_block(lines: list[str]) -> dict:
    """Parse a list of lines (one 'block' in the grammar). Used for the
    whole content file and for each record between --- markers."""
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


def parse_records(path: Path) -> list[dict]:
    """Parse a file into a list of records separated by '---' lines.
    The first record is the global content block (scalars, nav, pages);
    every record after that is a section or card."""
    text = path.read_text(encoding='utf-8')
    groups: list[list[str]] = [[]]
    for line in text.splitlines():
        if line.strip() == '---':
            groups.append([])
        else:
            groups[-1].append(line)
    records = []
    for lines in groups:
        if not any(l.strip() and not l.strip().startswith('#') for l in lines):
            continue
        records.append(_parse_block(lines))
    return records


_MD_LINK_RE = re.compile(r'\[([^\]]+)\]\(([^)]+)\)')


def markdown_links(text: str) -> str:
    """Turn `[label](href)` into `<a class="link" href="href" ...>label</a>`.
    External URLs (http/https) also get `target="_blank" rel="noopener"`.
    HTML `<a>` tags in content are left untouched."""
    if not text or '[' not in text:
        return text

    def sub(m: re.Match) -> str:
        label = m.group(1)
        href = m.group(2)
        is_ext = href.startswith(('http://', 'https://'))
        attrs = ' target="_blank" rel="noopener"' if is_ext else ''
        return f'<a class="link" href="{href}"{attrs}>{label}</a>'

    return _MD_LINK_RE.sub(sub, text)


def paragraphs_html(text: str) -> str:
    """Render a multi-line block as <p>para</p><p>para</p> (paragraphs
    separated by blank lines). Single paragraphs become one <p>."""
    if not text:
        return ''
    paragraphs = re.split(r'\n\s*\n', text.strip())
    return '\n'.join(f'<p>{p.strip()}</p>' for p in paragraphs if p.strip())


def render_li(items: list[str]) -> str:
    """Render a bullet list as `<li>...</li>` runs, with markdown link
    expansion applied to each item."""
    return ''.join(f'<li>{markdown_links(x)}</li>' for x in items)


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
    """Render one card using the card partial. Optional fields with no
    value render to empty strings."""
    intro = markdown_links(card.get('intro', ''))
    bullets = card.get('bullets') or []
    price = markdown_links(card.get('price', ''))
    name = markdown_links(card.get('name', ''))

    intro_block = f'<p>{intro}</p>' if intro else ''
    bullets_block = f'<ul>{render_li(bullets)}</ul>' if bullets else ''
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


def derive_phone_fields(content: dict) -> None:
    """If `phone:` is set, populate `phone_display` and `phone_dial`
    unless they're already set (explicit overrides win).

    Input is either E.164 (`+16177105598`) or a NANP-assumed digit
    string (`6177105598`, `1-617-710-5598`). Other country codes get
    a minimal `+CC NNNNN` display; override `phone_display` for
    locale-specific formatting."""
    phone = content.get('phone')
    if not phone:
        return
    digits = re.sub(r'\D', '', phone)
    if phone.strip().startswith('+'):
        country, national = digits[:-10], digits[-10:]
    elif len(digits) == 11 and digits.startswith('1'):
        country, national = '1', digits[1:]
    elif len(digits) == 10:
        country, national = '1', digits
    else:
        return  # can't confidently parse; require overrides
    content.setdefault('phone_dial', f'+{country}{national}')
    if country == '1' and len(national) == 10:
        content.setdefault(
            'phone_display',
            f'({national[:3]}) {national[3:6]}-{national[6:]}')
    else:
        content.setdefault('phone_display', f'+{country} {national}')


def build_base_context(content: dict) -> dict:
    """Flatten the parsed content dict into {token: string} for template
    substitution. Lists render as <li> runs; multi-line blocks get an
    `_html` companion rendered as <p>-wrapped paragraphs."""
    ctx: dict = {}
    for k, v in content.items():
        if isinstance(v, list):
            ctx[k] = render_li(v)
            ctx[f'{k}_li'] = ctx[k]
        else:
            expanded = markdown_links(v)
            ctx[k] = expanded
            ctx[f'{k}_html'] = paragraphs_html(expanded)
    return ctx


def render_nav_items(items: list[str], ctx: dict) -> str:
    """Render `Label | href | flags` entries as <li> rows.
    Flags is optional comma-separated: `external`, `button`."""
    out = []
    for item in items:
        parts = [p.strip() for p in item.split('|')]
        label = parts[0]
        href = parts[1] if len(parts) > 1 else '#'
        flags = set(f.strip() for f in parts[2].split(',')) if len(parts) > 2 else set()
        # Allow tokens like {{booking_url}} inside hrefs.
        href = _substitute(href, ctx, strict=False)
        cls = ' class="btn-nav"' if 'button' in flags else ''
        attrs = ' target="_blank" rel="noopener"' if 'external' in flags else ''
        out.append(f'<li><a href="{href}"{cls}{attrs}>{label}</a></li>')
    return '\n        '.join(out)


def render_section(section: dict, tpl_dir: Path, base_ctx: dict,
                    cards_by_name: dict) -> str:
    """Render one section record against its fragment template."""
    stype = section.get('type')
    if not stype:
        raise ValueError(f"section missing required 'type' field: {section!r}")
    frag_path = tpl_dir / 'sections' / f'{stype}.html'
    if not frag_path.exists():
        raise FileNotFoundError(
            f"no section template at {frag_path} for type '{stype}'")
    frag = _read_template(frag_path)

    # Section-local ctx: global + section fields (section wins). Field
    # values pass through substitution so `{{booking_url}}` etc. expand.
    local = dict(base_ctx)
    # Common optional fields — default to empty so templates can
    # reference them without every section having to set them.
    for opt in ('id', 'theme', 'eyebrow', 'alt'):
        local.setdefault(opt, '')

    # Cards section: look up referenced cards by name, render into
    # {{cards_html}}. Skip the `cards` field in the generic loop below
    # so its raw name list doesn't leak into the template context.
    cards_html = ''
    if stype == 'cards':
        names = section.get('cards') or []
        if not isinstance(names, list):
            raise ValueError(
                "cards section 'cards' must be a bullet list of card names")
        cards = []
        for n in names:
            if n not in cards_by_name:
                raise KeyError(f"cards section references unknown card {n!r}")
            cards.append(cards_by_name[n])
        cps = section.get('cards_per_row')
        col_span = int(cps) if cps else auto_col_span(len(cards))
        card_tpl = _read_template(tpl_dir / 'partials' / 'card.html')
        cards_html = '\n'.join(
            render_card(c, col_span, card_tpl) for c in cards)
    local['cards_html'] = cards_html

    for k, v in section.items():
        if k == 'type' or (k == 'cards' and stype == 'cards'):
            continue
        if isinstance(v, list):
            local[k] = render_li(v)
            local[f'{k}_li'] = local[k]
        else:
            expanded = _substitute(v, base_ctx, strict=False)
            # `*_href` stays raw (it's a URL, not prose); everything else
            # gets markdown-link expansion.
            if not k.endswith('_href'):
                expanded = markdown_links(expanded)
            local[k] = expanded
            local[f'{k}_html'] = paragraphs_html(expanded)
            # Auto-derive `{{<foo>_attrs}}` for any `<foo>_href` field so
            # external URLs open in a new tab and internal ones don't.
            if k.endswith('_href'):
                is_external = expanded.startswith(('http://', 'https://'))
                local[f'{k[:-5]}_attrs'] = (
                    ' target="_blank" rel="noopener"' if is_external else '')

    return _substitute(frag, local, strict=True)


def render_sections_for_page(sections: list[dict], page: str,
                              tpl_dir: Path, base_ctx: dict,
                              cards_by_name: dict) -> str:
    page_sections = [s for s in sections if s.get('page', 'index') == page]
    return '\n'.join(
        render_section(s, tpl_dir, base_ctx, cards_by_name)
        for s in page_sections
    )


def copy_static(src: Path, out: Path) -> None:
    """Copy css/ and images/ from template dir to out, plus netlify.toml
    if present."""
    for sub in ('css', 'images'):
        s = src / sub
        d = out / sub
        if s.exists():
            if d.exists():
                shutil.rmtree(d)
            shutil.copytree(s, d)
    toml = src / 'netlify.toml'
    if toml.exists():
        shutil.copy2(toml, out / 'netlify.toml')


def parse_pages(content: dict) -> list[dict]:
    """Parse the `pages:` list from content into dicts with
    {stem, title, description}. Each line: `stem | title | description`
    (description optional)."""
    items = content.get('pages') or []
    if not isinstance(items, list):
        raise ValueError("content 'pages' must be a bullet list")
    out = []
    for item in items:
        parts = [p.strip() for p in item.split('|')]
        if len(parts) < 2:
            raise ValueError(
                f"page entry needs at least `stem | title`: {item!r}")
        out.append({
            'stem': parts[0],
            'title': parts[1],
            'description': parts[2] if len(parts) > 2 else '',
        })
    return out


def build(content_path: Path, tpl_dir: Path, out_dir: Path,
          *, copy_static_files: bool = True) -> int:
    # Template cache is per-build: content edits shouldn't see stale
    # template contents on the next watch-mode rebuild.
    _read_template.cache_clear()
    records = parse_records(content_path)
    if not records:
        print(f"error: {content_path} is empty", file=sys.stderr)
        return 1
    # First record = global content (scalars, nav, pages). Remaining
    # records split into sections (rendered into pages) and cards
    # (indexed by name, pulled in by cards-type sections).
    content = records[0]
    sections: list[dict] = []
    cards_by_name: dict = {}
    for rec in records[1:]:
        if rec.get('type') == 'card':
            name = rec.get('name')
            if not name:
                raise ValueError(f"card record missing 'name' field: {rec!r}")
            if name in cards_by_name:
                raise ValueError(f"duplicate card name: {name!r}")
            cards_by_name[name] = rec
        else:
            sections.append(rec)
    derive_phone_fields(content)
    cs = content.setdefault('color_scheme', 'light')
    if cs not in ('light', 'dark', 'auto'):
        print(f"error: color_scheme must be 'light', 'dark', or 'auto'; got {cs!r}",
              file=sys.stderr)
        return 1
    base_ctx = build_base_context(content)

    # Nav + footer partials rendered once into tokens available on every page.
    nav_items = content.get('nav') or []
    if isinstance(nav_items, list):
        base_ctx['nav_items'] = render_nav_items(nav_items, base_ctx)
        base_ctx['footer_nav_items'] = base_ctx['nav_items']
    for partial in ('nav', 'footer'):
        p = tpl_dir / 'partials' / f'{partial}.html'
        if p.exists():
            base_ctx[partial] = _substitute(
                _read_template(p), base_ctx, strict=True)

    out_dir.mkdir(parents=True, exist_ok=True)
    pages = parse_pages(content)
    if not pages:
        print("error: content file has no `pages:` list", file=sys.stderr)
        return 1
    layout_tpl = _read_template(tpl_dir / 'layout.html')
    for page in pages:
        stem = page['stem']
        page_ctx = dict(base_ctx)
        page_ctx['title'] = page['title']
        page_ctx['description'] = page['description']
        page_ctx['sections'] = render_sections_for_page(
            sections, stem, tpl_dir, base_ctx, cards_by_name)
        out_path = (out_dir / 'index.html' if stem == 'index'
                    else out_dir / stem / 'index.html')
        try:
            rendered = _substitute(layout_tpl, page_ctx, strict=True)
        except KeyError as e:
            print(f"error rendering {out_path}: {e}", file=sys.stderr)
            return 1
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(rendered, encoding='utf-8')
        print(f"wrote {out_path}")

    if copy_static_files:
        copy_static(tpl_dir, out_dir)
        print(f"copied css/ and images/ to {out_dir}")
    return 0


def snapshot_mtimes(content_dir: Path, tpl_dir: Path) -> dict:
    """Collect {path: mtime} for every source file the build might read:
    all .txt in the content dir, plus .html/.css under the template dir.
    Binary assets (images) aren't watched — they're only copied on demand."""
    paths: set[Path] = set(content_dir.glob('*.txt'))
    if tpl_dir.exists():
        for pattern in ('*.html', '*.css'):
            paths.update(tpl_dir.rglob(pattern))
    return {p: p.stat().st_mtime for p in paths if p.exists()}


def watch_and_build(content_path: Path, tpl_dir: Path, out_dir: Path) -> int:
    content_dir = content_path.parent
    css_dir = tpl_dir / 'css'
    last = snapshot_mtimes(content_dir, tpl_dir)
    rc = build(content_path, tpl_dir, out_dir)
    print(f"watching {tpl_dir}/ and {content_dir}/*.txt — Ctrl+C to stop")
    try:
        while True:
            time.sleep(0.5)
            current = snapshot_mtimes(content_dir, tpl_dir)
            if current == last:
                continue
            changed = {p for p in set(current) | set(last)
                       if current.get(p) != last.get(p)}
            print(f"\nchange detected: {', '.join(sorted(str(p) for p in changed))}")
            last = current
            # Skip the css/images copy on content-only edits — otherwise
            # rmtree+copytree fires on every keystroke save, which also
            # kicks the netlify dev file watcher.
            copy_css = any(css_dir in p.parents for p in changed)
            try:
                build(content_path, tpl_dir, out_dir,
                      copy_static_files=copy_css)
            except Exception as e:
                print(f"build error: {e}", file=sys.stderr)
    except KeyboardInterrupt:
        print("\nstopped.")
        return rc


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[1])
    ap.add_argument('content', help='path to the content file')
    ap.add_argument('--out', required=True, help='output directory')
    ap.add_argument('--templates', default='template-site',
                    help='path to template directory (default: ./template-site)')
    ap.add_argument('--watch', action='store_true',
                    help='rebuild on file change until interrupted')
    args = ap.parse_args()

    content_path = Path(args.content)
    tpl_dir = Path(args.templates)
    out_dir = Path(args.out)

    if args.watch:
        return watch_and_build(content_path, tpl_dir, out_dir)
    return build(content_path, tpl_dir, out_dir)


if __name__ == '__main__':
    sys.exit(main())
