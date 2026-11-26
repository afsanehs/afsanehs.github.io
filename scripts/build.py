#!/usr/bin/env python3
"""Build the photo blog.

    python3 scripts/build.py ~/Desktop/photo-blog   # import photo folders, then render pages
    python3 scripts/build.py                        # re-render pages from posts.json only

Each folder in the source becomes one post. Folder names look like
"Boston (USA) - 2022" -> title "Boston", location "Boston, USA", year 2022. Exact dates come
from the photos themselves.

Photos are rotated upright, converted to sRGB, resized, and stripped of ALL
metadata (including GPS location) before they are written to photos/.

To change a post's title, location (shown at the top, e.g. "Boston, Massachusetts")
or caption, edit posts.json and re-run. The title is only shown when it differs
from the city in the location (e.g. "L'Aquarium de Paris").
Re-importing keeps those edits; it only refreshes the photo list.

Needs ImageMagick 7 (`magick`) with HEIC support.
"""
import concurrent.futures
import datetime
import hashlib
import html
import json
import os
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "posts.json"
PHOTOS = ROOT / "photos"
SRGB = "/System/Library/ColorSync/Profiles/sRGB Profile.icc"

SITE_URL = "https://afsanehs.github.io/"
BLOG_TITLE = "Afsaneh Samet"
BLOG_DESC = "Photo blog"
AVATAR = "assets/avatar.jpg"

IMAGE_EXT = {".jpg", ".jpeg", ".heic", ".heif", ".png"}
LARGE = 1600   # long edge of the full-size image (lightbox, single photos)
SMALL = 800    # long edge of the image used in photoset rows
COLUMN = 500   # width of the post column in CSS px, for srcset sizes (old Tumblr: 500)
PHOTOSET_MAX = 10  # old Tumblr photosets held at most 10 photos

MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]


# ---------------------------------------------------------------- helpers

def esc(s):
    return html.escape(str(s), quote=True)


def pretty(s):
    return s.replace("'", "’")


def slugify(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = re.sub(r"['’]", "", s.lower())
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def run(cmd):
    return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout


def parse_folder(name):
    m = re.match(r"^(.*?)\s*\(([^)]*)\)\s*-\s*(\d{4})\s*$", name)
    if m:
        return m[1].strip(), m[2].strip(), int(m[3])
    m = re.match(r"^(.*?)\s*-\s*(\d{4})\s*$", name)
    if m:
        return m[1].strip(), "", int(m[2])
    return name.strip(), "", None


# ---------------------------------------------------------------- import

def exif_taken(path):
    try:
        out = run(["magick", "identify", "-format", "%[EXIF:DateTimeOriginal]\n", str(path)])
    except subprocess.CalledProcessError:
        return None
    for line in out.splitlines():
        m = re.match(r"(\d{4}):(\d{2}):(\d{2}) (\d{2}):(\d{2}):(\d{2})", line.strip())
        if m:
            return "{}-{}-{}T{}:{}:{}".format(*m.groups())
    return None


def size_of(path):
    w, h = run(["magick", "identify", "-format", "%w %h", str(path)]).split()
    return int(w), int(h)


def process_photo(src, slug, stem):
    out_dir = PHOTOS / slug
    out_dir.mkdir(parents=True, exist_ok=True)
    large = out_dir / f"{stem}-l.jpg"
    small = out_dir / f"{stem}-s.jpg"
    fresh = (large.exists() and small.exists()
             and large.stat().st_mtime >= src.stat().st_mtime)
    if not fresh:
        cmd = ["magick", str(src), "-auto-orient"]
        if os.path.exists(SRGB):
            cmd += ["-profile", SRGB]
        cmd += ["-strip",
                "-resize", f"{LARGE}x{LARGE}>", "-quality", "82", "-interlace", "JPEG",
                "-sampling-factor", "4:2:0", "-write", str(large),
                "-resize", f"{SMALL}x{SMALL}>", "-quality", "80", str(small)]
        subprocess.run(cmd, check=True, capture_output=True,
                       env={**os.environ, "MAGICK_THREAD_LIMIT": "1"})
    w, h = size_of(large)
    sw, sh = size_of(small)
    return {
        "original": src.name,
        "large": large.relative_to(ROOT).as_posix(),
        "small": small.relative_to(ROOT).as_posix(),
        "w": w, "h": h, "sw": sw, "sh": sh,
        "taken": exif_taken(src),
    }


def import_source(src_dir, data):
    by_source = {p["source"]: p for p in data["posts"]}
    used_slugs = {p["slug"] for p in data["posts"]}
    folders = sorted(d for d in src_dir.iterdir() if d.is_dir() and not d.name.startswith("."))
    if not folders:
        sys.exit(f"No photo folders found in {src_dir}")

    jobs = []  # (post, src, stem)
    for folder in folders:
        title, place, year = parse_folder(folder.name)
        post = by_source.get(folder.name)
        if post is None:
            base = slugify(f"{title} {year or ''}") or "post"
            slug, k = base, 2
            while slug in used_slugs:
                slug, k = f"{base}-{k}", k + 1
            used_slugs.add(slug)
            post = {"slug": slug, "source": folder.name, "title": title,
                    "location": f"{title}, {place}" if place else title,
                    "year": year, "caption": "",
                    "photos": []}
            data["posts"].append(post)
        post["year"] = year
        stems = set()
        files = sorted(f for f in folder.iterdir()
                       if f.is_file() and f.suffix.lower() in IMAGE_EXT)
        post["_jobs"] = []
        for f in files:
            stem = base = slugify(f.stem) or "photo"
            k = 2
            while stem in stems:
                stem, k = f"{base}-{k}", k + 1
            stems.add(stem)
            jobs.append((post, f, stem))
        print(f"  {folder.name}: {len(files)} photos")

    print(f"Processing {len(jobs)} photos…")
    with concurrent.futures.ThreadPoolExecutor(max_workers=os.cpu_count() or 4) as ex:
        futures = [(post, ex.submit(process_photo, f, post["slug"], stem)) for post, f, stem in jobs]
        for post, fut in futures:
            post["_jobs"].append(fut.result())

    for post in data["posts"]:
        if "_jobs" not in post:
            continue
        photos = post.pop("_jobs")
        photos.sort(key=lambda p: (p["taken"] is None, p["taken"] or "", p["original"]))
        post["photos"] = photos
        keep = {Path(p["large"]).name for p in photos} | {Path(p["small"]).name for p in photos}
        for f in (PHOTOS / post["slug"]).iterdir():
            if f.name not in keep:
                f.unlink()


# ---------------------------------------------------------------- render

def post_dates(post):
    days = sorted(p["taken"][:10] for p in post["photos"] if p.get("taken"))
    if post.get("year"):
        in_year = [d for d in days if d.startswith(str(post["year"]))]
        days = in_year or days
    if not days:
        return None, None
    return datetime.date.fromisoformat(days[0]), datetime.date.fromisoformat(days[-1])


def fmt_range(a, b, short=False):
    if a is None:
        return ""
    M = [m[:3] for m in MONTHS] if short else MONTHS
    if a == b:
        return f"{M[a.month - 1]} {a.day}, {a.year}"
    if (a.year, a.month) == (b.year, b.month):
        return f"{M[a.month - 1]} {a.day}–{b.day}, {a.year}"
    if a.year == b.year:
        return f"{M[a.month - 1]} {a.day} – {M[b.month - 1]} {b.day}, {a.year}"
    return f"{M[a.month - 1]} {a.day}, {a.year} – {M[b.month - 1]} {b.day}, {b.year}"


def row_sizes(photos):
    n = len(photos)
    if n <= 2:
        return [n] if n else []
    first = 1 if photos[0]["w"] >= photos[0]["h"] else 2
    sizes, left, nxt = [first], n - first, (2 if first == 1 else 3)
    while left > 0:
        k = min(nxt, left)
        sizes.append(k)
        left -= k
        nxt = 5 - nxt  # alternate 2 and 3
    if sizes[-1] == 1:
        prev = sizes[-2]
        sizes[-2:] = {1: [2], 2: [3], 3: [2, 2]}[prev]
    return sizes


def render_photoset(post, eager):
    """Old-Tumblr photoset: at most 10 photos shown; the 10th tile says +N and
    the rest are only reachable in the lightbox."""
    photos, out, i = post["photos"], [], 0
    total = len(photos)
    shown = photos[:PHOTOSET_MAX]
    label = pretty(post["title"])
    for size in row_sizes(shown):
        row = shown[i:i + size]
        ars = [p["w"] / p["h"] for p in row]
        total_ar = sum(ars)
        items = []
        for p, ar in zip(row, ars):
            i += 1
            share = ar / total_ar
            sizes_attr = f"(max-width: 540px) {round(share * 100)}vw, {round(COLUMN * share)}px"
            loading = 'fetchpriority="high"' if eager and i == 1 else 'loading="lazy"'
            more = total - PHOTOSET_MAX if (i == PHOTOSET_MAX and total > PHOTOSET_MAX) else 0
            cls, extra = ("ph more", f' data-more="+{more}"') if more else ("ph", "")
            items.append(
                f'<a class="{cls}" href="{esc(p["large"])}" style="flex-grow:{ar:.4f}"{extra}>'
                f'<img src="{esc(p["small"])}" srcset="{esc(p["small"])} {p["sw"]}w, {esc(p["large"])} {p["w"]}w" '
                f'sizes="{sizes_attr}" width="{p["sw"]}" height="{p["sh"]}" {loading} decoding="async" '
                f'alt="{esc(label)}, photo {i} of {total}"></a>')
        out.append('<div class="row">' + "".join(items) + "</div>")
    rest = "".join(
        f'<a class="ph" href="{esc(p["large"])}" data-small="{esc(p["small"])}" '
        f'aria-label="{esc(label)}, photo {k} of {total}" hidden></a>'
        for k, p in enumerate(photos[PHOTOSET_MAX:], start=PHOTOSET_MAX + 1))
    return '<div class="photoset">' + "".join(out) + rest + "</div>"


def render_post(post, eager):
    start, _ = post_dates(post)
    n = len(post["photos"])
    slug = esc(post["slug"])
    when = fmt_range(start, start) if start else str(post.get("year") or "")  # start date only
    when = f'<a href="#{slug}"><time datetime="{start.isoformat()}">{when}</time></a>' if start else when
    title = pretty(post["title"])
    location = pretty(post.get("location") or post["title"])
    city = location.split(",")[0].strip()
    body = []
    if title != city:  # e.g. a venue like "L'Aquarium de Paris"
        body.append(f'<p class="where"><b>{esc(title)}</b></p>')
    if post.get("caption"):
        body.append(f'<p class="caption">{esc(post["caption"])}</p>')
    body = ('\n      <div class="post-body">\n        ' + "\n        ".join(body) + "\n      </div>") if body else ""
    label = location if title == city else f"{title}, {location}"
    return f"""
    <article class="post" id="{slug}" data-label="{esc(label)}">
      <header class="post-head">
        <h2 class="post-location"><a href="#{slug}">{esc(location)}</a></h2>
      </header>
      {render_photoset(post, eager)}{body}
      <footer class="post-foot">
        <span>{when}</span>
        <span class="count">{n} photo{'s' if n != 1 else ''}</span>
      </footer>
    </article>"""


def asset_version(name):
    return hashlib.sha1((ROOT / name).read_bytes()).hexdigest()[:8]


def page(title, path, og_image, current, body, script=False):
    css_v = asset_version("style.css")
    here = ' aria-current="page"'
    nav = "".join(
        f'<a href="{href}"{here if key == current else ""}>{label}</a>'
        for key, href, label in (("posts", "./", "Posts"), ("archive", "archive.html", "Archive")))
    og = f'<meta property="og:image" content="{SITE_URL}{esc(og_image)}">' if og_image else ""
    js = f'\n  <script src="blog.js?v={asset_version("blog.js")}" defer></script>' if script else ""
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{esc(title)}</title>
  <meta name="description" content="{esc(BLOG_DESC)}">
  <meta property="og:title" content="{esc(title)}">
  <meta property="og:description" content="{esc(BLOG_DESC)}">
  <meta property="og:type" content="website">
  <meta property="og:url" content="{SITE_URL}{path}">
  {og}
  <meta name="twitter:card" content="summary_large_image">
  <link rel="icon" href="favicon.svg" type="image/svg+xml">
  <link rel="stylesheet" href="style.css?v={css_v}">{js}
</head>
<body>
  <div class="layout">
    <header class="sidebar">
      <a class="avatar" href="./"><img src="{AVATAR}" alt="" width="96" height="96"></a>
      <p class="blog-title"><a href="./">{esc(BLOG_TITLE)}</a></p>
      <p class="desc">{esc(BLOG_DESC)}</p>
      <nav class="links" aria-label="Site">{nav}</nav>
    </header>
    <main>{body}
    </main>
  </div>
  <button class="to-top" type="button" aria-label="Back to top">↑</button>
</body>
</html>
"""


LIGHTBOX = """
  <dialog class="lightbox" aria-label="Photo viewer">
    <div class="lb-stage"><img alt=""></div>
    <button class="lb-btn lb-close" type="button" aria-label="Close">✕</button>
    <button class="lb-btn lb-prev" type="button" aria-label="Previous photo">‹</button>
    <button class="lb-btn lb-next" type="button" aria-label="Next photo">›</button>
    <p class="lb-caption"><span class="lb-label"></span> · <span class="lb-count"></span></p>
  </dialog>"""


def render(data):
    posts = [p for p in data["posts"] if p["photos"]]

    def sort_key(p):
        start, _ = post_dates(p)
        return start or datetime.date(p.get("year") or 1900, 1, 1)

    posts.sort(key=sort_key, reverse=True)

    og_image = posts[0]["photos"][0]["large"] if posts else None

    # index.html
    body = ("".join(render_post(p, eager=(i == 0)) for i, p in enumerate(posts)))
    html_out = page(BLOG_TITLE, "", og_image, "posts", body, script=True)
    html_out = html_out.replace("\n</body>", LIGHTBOX + "\n</body>")
    (ROOT / "index.html").write_text(html_out)

    # archive.html: one square tile per post, grouped by year
    years = {}
    for p in posts:
        start, _ = post_dates(p)
        y = start.year if start else p.get("year") or "Undated"
        years.setdefault(y, []).append((p, start))
    sections = []
    for y, items in years.items():
        tiles = []
        for p, start in items:
            cover = p["photos"][0]
            when = f"{MONTHS[start.month - 1][:3]} {start.year}" if start else ""
            n = len(p["photos"])
            tiles.append(
                f'<a class="tile" href="./#{esc(p["slug"])}">'
                f'<img src="{esc(cover["small"])}" alt="" loading="lazy" decoding="async">'
                f'<span class="tile-info"><b>{esc(pretty(p["title"]))}</b>'
                f'{esc(when)} · {n} photo{"s" if n != 1 else ""}</span></a>')
        sections.append(f'\n      <section><h2 class="archive-year">{esc(y)}</h2>'
                        f'<div class="grid">{"".join(tiles)}</div></section>')
    body = '\n      <h1 class="page-title">Archive</h1>' + "".join(sections)
    html_out = page(f"Archive · {BLOG_TITLE}", "archive.html", og_image, "archive", body, script=True)
    (ROOT / "archive.html").write_text(html_out)
    print(f"Rendered {len(posts)} posts → index.html, archive.html")


def main():
    data = json.loads(DATA.read_text()) if DATA.exists() else {"posts": []}
    if len(sys.argv) > 1:
        src = Path(sys.argv[1]).expanduser()
        if not src.is_dir():
            sys.exit(f"Not a folder: {src}")
        print(f"Importing from {src}")
        import_source(src, data)
        DATA.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    render(data)


if __name__ == "__main__":
    main()
