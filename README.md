# site-generator

A zero-dependency static site generator. One plaintext content file + a cards
file produce a full Netlify-ready site from a reusable HTML/CSS scaffold.

## Quick start

```bash
python generate.py content/bryant.txt --cards content/bryant.cards.txt --out dist/bryant
cd dist/bryant && python -m http.server 8000
```

Open http://localhost:8000.

## Repo layout

```
site-generator/
├── template-site/          # HTML/CSS scaffold with {{tokens}}
│   ├── card.html           # single-card fragment
│   ├── index.html
│   ├── about.html
│   ├── services.html
│   ├── contact.html
│   ├── thank-you.html
│   ├── css/
│   └── images/
├── content/
│   ├── bryant.txt          # site-wide fields
│   └── bryant.cards.txt    # one card per section, split by `---`
└── generate.py
```

## Content file grammar

```
# comments start with #

business_name: Bryant Piano Service     # single-line scalar
email: hello@example.com

about_bio >>>                           # multi-line block
I'm a piano technician based in Cambridge.

A blank line inside the block becomes a new paragraph.
<<<

bullets:                                # bullet list
- First item
- Second item
```

Quoted strings (`"..."` / `'...'`) are supported when you need leading/trailing
whitespace or embedded colons to survive parsing.

## Cards file grammar

Same grammar as the content file, plus: a line containing only `---` separates
cards. Each card may set any subset of:

- `name` (heading)
- `intro` (paragraph under the heading)
- `bullets` (list)
- `price` (small price label above the heading)

Missing fields are simply omitted from the rendered card.

## Template tokens

In any template file under `template-site/`:

- `{{business_name}}`, `{{email}}`, ... — any scalar from the content file
- `{{about_bio_html}}` — any multi-line block rendered as `<p>...</p>` per
  paragraph. Append `_html` to any multi-line key.
- `{{card_1}}`, `{{card_2}}`, ... — Nth rendered card, or empty string if
  the cards file has fewer than N cards. Include as many slots as you
  want to support.

Column span for cards is chosen automatically: 1 card = col-12,
2 = col-6, 3 = col-4, 4 = col-3, 5+ = col-4 wrapping. Override with
`cards_per_row: 3` in the content file.

## Adding pages

1. Drop a new `foo.html` into `template-site/` using `{{tokens}}` as
   needed.
2. Add `foo` to the `pages` list in `generate.py`.
3. Add a link to it in the nav/footer of the other templates.

## Adding a new site

1. Copy `content/bryant.txt` and `content/bryant.cards.txt` to new
   files (e.g. `content/acme.txt`, `content/acme.cards.txt`).
2. Edit the field values.
3. Swap the images in `template-site/images/` or a per-site image
   folder (pass `--templates` to point at an alternate scaffold).
4. Regenerate: `python generate.py content/acme.txt --cards content/acme.cards.txt --out dist/acme`.

## Deploying to Netlify

The output of `--out` is pure static files. Either:

- Point Netlify's publish directory at `dist/<site>/` in a separate repo that
  only contains the generated output, or
- Keep source + output together and set a Netlify build command
  (`python generate.py content/<site>.txt --cards content/<site>.cards.txt --out dist/<site>`)
  with publish directory `dist/<site>/`.
