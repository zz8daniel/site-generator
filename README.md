# site-generator

A zero-dependency static site generator. One plaintext content file
produces a full Netlify-ready site from a reusable HTML/CSS scaffold.

## Quick start

```bash
python generate.py content/bryant.txt --out dist/bryant
cd dist/bryant && netlify dev
```

Open the URL Netlify prints (typically http://localhost:8888). If you
don't have the Netlify CLI, `python -m http.server 8000` also works —
pretty URLs like `/contact` resolve because pages are written as
`<stem>/index.html`.

Pass `--watch` to rebuild on every save.

## Repo layout

```
site-generator/
├── template-site/          # HTML/CSS scaffold with {{tokens}}
│   ├── layout.html         # the single page shell
│   ├── netlify.toml        # copied into each dist/<name>/ output
│   ├── partials/           # nav.html, footer.html, card.html
│   ├── sections/           # one fragment per section type
│   ├── css/
│   └── images/
├── content/
│   ├── bryant.txt          # one file per site, everything inside
│   └── alvarez.txt
└── generate.py
```

## The one content file

Every site is described by a single `content/<name>.txt`. Records are
separated by `---` on its own line:

1. **First record** — global content: scalars, `nav:`, `pages:`.
2. **Every record after that** — either a *section* (`type: <fragment>`,
   rendered into a page) or a *card* (`type: card` with a unique
   `name:`, pulled in by name from a `cards`-type section).

Sketch:

```
business_name: Bryant Piano Service
email: hello@example.com

nav:
- Home | /#top
- Contact | /contact

pages:
- index   | Bryant Piano Service | Professional piano tuning.
- contact | Contact - Bryant

---

type: hero
id: top
title_line1: Bryant Piano
title_line2: Service
subtitle: Tuning & repair in Cambridge, MA.
button_label: Book Now
button_href: {{booking_url}}

---

type: cards
id: services
theme: light
heading: Services
cards:
- Standard Tuning
- Advanced Service

---

type: card
name: Standard Tuning
intro: Professional aural tuning.
bullets:
- Equal temperament
- Historic temperaments

---

type: card
name: Advanced Service
intro: "Full regulation, plus tuning."
bullets:
- Has not been serviced in 2+ years
```

## Grammar

```
# line comment
key: value                 single-line scalar
key >>>                    start multi-line block (paragraphs separated
...                        by blank lines; newlines preserved)
<<<
key:                       start a bullet list
- item
- item
---                        separates records (standalone on its own line)
```

Quoted strings (`"..."` / `'...'`) are supported when you need leading/
trailing whitespace or embedded colons to survive parsing.

Inside any value, `{{token}}` expands against the global content (so
`button_href: {{booking_url}}` works inside a section). `[label](href)`
becomes an anchor tag.

## Template tokens

Inside `template-site/layout.html`:

- `{{title}}`, `{{description}}` — from the matching `pages:` entry
- `{{nav}}`, `{{footer}}` — rendered partials
- `{{sections}}` — concatenated sections for this page

Inside `template-site/sections/<type>.html`:

- `{{<field>}}` — any field from the section record (section fields
  win over globals)
- `{{<field>_html}}` — multi-line block rendered as `<p>...</p>` per
  paragraph
- `{{<field>_li}}` — bullet list rendered as `<li>...</li>` runs
- `{{cards_html}}` — (inside a `cards` section) the rendered cards
- `{{<foo>_attrs}}` — auto-derived from any `<foo>_href` field; adds
  `target="_blank" rel="noopener"` when the URL is external

Common optional fields default to empty so fragments can reference
them unconditionally: `id`, `theme`, `eyebrow`, `alt`.

## Pages

A `pages:` entry is `stem | title | description`. The `index` stem
renders as `dist/<name>/index.html`; every other stem renders as
`<stem>/index.html` (pretty-URL friendly).

Section records default to `page: index`. Add `page: contact` (etc.)
to route a section to a different page.

## Cards

Define each card once as a `type: card` record with a unique `name:`.
A `cards`-type section references them in order via a bullet list:

```
type: cards
heading: Services
cards:
- Standard Tuning
- Advanced Service
```

Column span is auto-chosen from count (1→12, 2→6, 3→4, 4→3, 5+→4
wrapping). Override with `cards_per_row: 3` on the section.

## Adding a new site

```bash
cp content/bryant.txt content/acme.txt
# edit fields; swap template-site/images/*.jpg if desired
python generate.py content/acme.txt --out dist/acme
```

Pass `--templates path/to/other/template-site` to point at an
alternate scaffold (e.g., different images per site).

## Deploying to Netlify

`dist/<name>/` is pure static files, ready to deploy. Either point
Netlify's publish directory at it directly, or set a build command:

```
python generate.py content/<name>.txt --out dist/<name>
```

with publish directory `dist/<name>/`. `netlify.toml` is copied into
each output directory automatically.
