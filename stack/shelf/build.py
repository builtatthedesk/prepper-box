#!/usr/bin/env python3
"""The manuals shelf: public-domain survival/medical/preparedness/plant PDFs -> one searchable ZIM.

Downloads each PDF in manifest.tsv from archive.org into <data>/pdf (resumable), OCRs any
scanned one into <data>/ocr, splits each book into sections at its PDF bookmarks (or every
6 pages when it has none), and writes one HTML page per section with a link to the original
PDF page (served by nginx at /shelf/). Kiwix full-text search and Ask the Library read it
like any other book.

  python3 build.py /srv/prepper/shelf /srv/prepper/zim
Needs poppler-utils, ocrmypdf and zim-tools (zimwriterfs).
"""
import datetime, html, os, re, shutil, struct, subprocess, sys, urllib.parse, urllib.request, zlib

HERE = os.path.dirname(os.path.abspath(__file__))
DATA, ZIMDIR = sys.argv[1], sys.argv[2]
PDF, OCR, SITE = (os.path.join(DATA, d) for d in ("pdf", "ocr", ".site"))
NAME = "prepper-manuals_en_all"
CHUNK = 6   # pages per section for books without bookmarks

def run(*cmd):
    return subprocess.run(cmd, capture_output=True, text=True, errors="replace").stdout

def slug(t):
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", t.lower())).strip("-")[:70] or "section"

books = []
for line in open(os.path.join(HERE, "manifest.tsv"), encoding="utf-8"):
    if line.strip() and not line.startswith("#"):
        ident, fname, shelf, title = line.rstrip("\n").split("\t")
        books.append(dict(id=ident, src=fname, shelf=shelf, title=title, pdf=ident + ".pdf"))

# --- download + OCR --------------------------------------------------------------------------
os.makedirs(PDF, exist_ok=True); os.makedirs(OCR, exist_ok=True)
for b in books:
    path = os.path.join(PDF, b["pdf"])
    if not os.path.exists(path):
        url = f"https://archive.org/download/{b['id']}/{urllib.parse.quote(b['src'])}"
        print("download", b["title"], flush=True)
        try:
            urllib.request.urlretrieve(url, path + ".part"); os.rename(path + ".part", path)
        except Exception as e:   # archive.org hiccup: build without it, picked up on the next run
            print(f"!! skipped {b['title']}: {e}", flush=True); b["skip"] = True; continue
    m = re.search(r"Pages:\s+(\d+)", run("pdfinfo", path))
    if not m:   # unreadable PDF: build without it
        print(f"!! skipped {b['title']}: pdfinfo failed", flush=True); b["skip"] = True; continue
    n = int(m.group(1))
    b["pages"] = n
    # Scanned book (little text per page) -> OCR once into ocr/.
    text = path
    if len(run("pdftotext", "-l", str(min(n, 30)), path, "-").split()) < 40 * min(n, 30):
        ocr = os.path.join(OCR, b["pdf"])
        if not os.path.exists(ocr):
            print("ocr", b["title"], flush=True)
            subprocess.run(["ocrmypdf", "-q", "--skip-text", "--continue-on-soft-render-error", "--output-type", "pdf",
                            path, ocr + ".part"], check=False)
            if os.path.exists(ocr + ".part"): os.rename(ocr + ".part", ocr)
        if os.path.exists(ocr): text = ocr
    b["text"] = text
books = [b for b in books if not b.get("skip")]

# --- sections ---------------------------------------------------------------------------------
def outline(pdf):
    xml = run("pdftohtml", "-xml", "-i", "-stdout", "-f", "1", "-l", "1", pdf)
    return [(int(p), html.unescape(re.sub(r"<[^>]+>", "", t)).strip())
            for p, t in re.findall(r'<item page="(\d+)">(.*?)</item>', xml, re.S)]

def clean(text):
    lines = [l.strip() for l in text.splitlines() if not re.fullmatch(r"\s*[\divxlc-]{1,6}\s*", l, re.I)]
    paras = re.split(r"\n\s*\n", "\n".join(lines))
    return [re.sub(r"\s+", " ", re.sub(r"-\n(?=[a-z])", "", p)).strip() for p in paras if len(p.split()) > 2]

sections = []
for b in books:
    n, first = b["pages"], {}
    for page, label in outline(os.path.join(PDF, b["pdf"])):
        if 1 <= page <= n and label: first.setdefault(page, label)   # first (outermost) bookmark on a page
    if len(first) < 3:   # no usable bookmarks
        first = {p: f"Pages {p}–{min(p + CHUNK - 1, n)}" for p in range(1, n + 1, CHUNK)}
    starts = sorted(first) + [n + 1]
    if starts[0] > 1: first[1] = "Front matter"; starts.insert(0, 1)
    b["sections"] = []
    for k, page in enumerate(starts[:-1]):
        end = max(page, starts[k + 1] - 1)
        paras = clean(run("pdftotext", "-f", str(page), "-l", str(end), b["text"], "-"))
        if not paras: continue
        s = dict(book=b, name=first[page], page=page, end=end, paras=paras)
        sections.append(s); b["sections"].append(s)
    print(f"{b['title']}: {n} pages, {len(b['sections'])} sections"
          f"{' (OCR)' if b['text'] != os.path.join(PDF, b['pdf']) else ''}", flush=True)

# --- HTML site --------------------------------------------------------------------------------
shutil.rmtree(SITE, ignore_errors=True); os.makedirs(SITE)
open(os.path.join(SITE, "style.css"), "w").write(
    """body{margin:0;font:17px/1.6 Georgia,serif;color:#222;background:#fbfaf6}main{max-width:720px;margin:0 auto;padding:24px 16px}
h1{font:600 26px/1.25 system-ui,sans-serif;margin:0 0 6px}.meta{color:#666;font:14px system-ui,sans-serif;margin-bottom:18px}
a{color:#2f6b3a}.orig{display:inline-block;margin:6px 0 18px;font:14px system-ui,sans-serif}
li{margin:3px 0}h2{font:600 19px system-ui,sans-serif;margin-top:28px}small{color:#777}""")
ORIG = ("<script>document.querySelectorAll('a.orig').forEach(a=>a.href='http://'+location.hostname+"
        "'/shelf/'+encodeURIComponent(a.dataset.pdf)+'#page='+a.dataset.page)</script>")

def page(path, title, body):
    with open(os.path.join(SITE, path), "w", encoding="utf-8") as f:
        f.write(f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" '
                f'content="width=device-width,initial-scale=1"><title>{html.escape(title)}</title>'
                f'<link rel="stylesheet" href="style.css"></head><body><main>{body}</main>{ORIG}</body></html>')

def orig(pdf, p, label):
    return f"<a class='orig' href='#' data-pdf='{html.escape(pdf)}' data-page='{p}'>{label} &rarr;</a>"

used = set()
for b in books:
    b["file"] = slug(b["title"]) + ".html"; used.add(b["file"][:-5])
for s in sections:
    base = slug(f"{s['book']['title'][:30]}-{s['name']}")
    f = base
    while f in used: f += "-2"
    used.add(f); s["file"] = f + ".html"
for b in books:
    for k, s in enumerate(b["sections"]):
        nav = " · ".join(x for x in [
            f"<a href='{b['sections'][k-1]['file']}'>&larr; previous</a>" if k else "",
            f"<a href='{b['file']}'>{html.escape(b['title'])}</a>",
            f"<a href='{b['sections'][k+1]['file']}'>next &rarr;</a>" if k + 1 < len(b["sections"]) else ""] if x)
        body = (f"<h1>{html.escape(s['name'])}</h1><div class='meta'>{html.escape(b['title'])} · {b['shelf']} · "
                f"pp. {s['page']}–{s['end']}</div>"
                + orig(b["pdf"], s["page"], "Open these pages in the original PDF (with pictures)")
                + "".join(f"<p>{html.escape(p)}</p>" for p in s["paras"]) + f"<p><small>{nav}</small></p>")
        page(s["file"], f"{s['name']} — {b['title']}", body)
    page(b["file"], b["title"], f"<h1>{html.escape(b['title'])}</h1><div class='meta'>{b['shelf']} · {b['pages']} pages · "
         f"<a href='index.html'>all manuals</a></div>" + orig(b["pdf"], 1, "Open the whole PDF")
         + "<ul>" + "".join(f"<li><a href='{s['file']}'>{html.escape(s['name'])}</a> <small>p. {s['page']}</small></li>"
                            for s in b["sections"]) + "</ul>")

shelves = {}
for b in books: shelves.setdefault(b["shelf"], []).append(b)
page("index.html", "Manuals Shelf",
     f"<h1>Manuals Shelf</h1><div class='meta'>{len(books)} survival, medical, preparedness and plant manuals · "
     f"{len(sections)} sections · use the search box above</div>"
     + "".join(f"<h2>{html.escape(k)}</h2><ul>" + "".join(
         f"<li><a href='{b['file']}'>{html.escape(b['title'])}</a> <small>{b['pages']} pp.</small></li>" for b in v) + "</ul>"
         for k, v in shelves.items()))

def png48(path):  # plain brown square illustration (zimwriterfs requires a 48x48 PNG)
    raw = b"".join(b"\x00" + bytes((122, 82, 48)) * 48 for _ in range(48))
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d))
    open(path, "wb").write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 48, 48, 8, 2, 0, 0, 0))
                           + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
png48(os.path.join(SITE, "icon.png"))

# --- ZIM --------------------------------------------------------------------------------------
out = os.path.join(ZIMDIR, ".dl", f"{NAME}_{datetime.date.today():%Y-%m}.zim")
os.makedirs(os.path.dirname(out), exist_ok=True)
if os.path.exists(out): os.remove(out)
subprocess.run(["zimwriterfs", "--welcome=index.html", "--illustration=icon.png", "--language=eng",
                "--title=Manuals Shelf", "--description=Survival, medical, preparedness and wild-plant manuals, searchable",
                "--creator=US Army, FEMA, USDA, Smithsonian, Hesperian and others", "--publisher=prepper", f"--name={NAME}",
                SITE, out], check=True)
for old in os.listdir(ZIMDIR):
    if old.startswith(NAME + "_") and old.endswith(".zim"):
        os.remove(os.path.join(ZIMDIR, old))
os.rename(out, os.path.join(ZIMDIR, os.path.basename(out)))
print(f"ok {len(books)} books, {len(sections)} sections -> {os.path.basename(out)}")
