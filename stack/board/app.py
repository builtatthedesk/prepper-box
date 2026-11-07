"""Notice board: short notes and a file drop for anyone on the hotspot/LAN. Python stdlib only.

Served by nginx under /board/ (so every link here is relative). Data in /data (= $DATA/board):
notes.jsonl, one note per line, and files/. Uploads are raw request bodies (POST upload?name=..,
sent by the page's JS), capped per file and in total. Downloads are always attachments with
nosniff + CSP sandbox, so nothing uploaded can run as a page on this origin. No delete.
"""
import html, json, os, re, shutil, string, threading, time, unicodedata, urllib.parse
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

DATA = os.environ.get("BOARD_DATA", "/data")
FILES, NOTES = os.path.join(DATA, "files"), os.path.join(DATA, "notes.jsonl")
MAX_FILE, MAX_TOTAL, MIN_FREE = 50 * 2**20, 5 * 2**30, 2 * 2**30   # bytes
MAX_NOTE, MAX_NAME, SHOW_NOTES, MAX_NOTES_BYTES = 2000, 40, 300, 2 * 2**20
MAX_COUNT = 2000   # files; each also counts as at least 4 KB toward MAX_TOTAL
LOCK = threading.Lock()
reserved = 0       # bytes of uploads in progress, so parallel uploads can't overrun the caps
os.makedirs(FILES, exist_ok=True)
for f in os.listdir(FILES):   # uploads cut short by a restart
    if f.startswith(".part-"): os.remove(os.path.join(FILES, f))

def safe_name(n):
    """Basename only, ASCII letters/digits and . - _ ( ) space; no leading dots; <= 100 chars."""
    n = unicodedata.normalize("NFKD", n).encode("ascii", "ignore").decode()
    n = re.sub(r"[^A-Za-z0-9._\- ()]+", "_", n.replace("\\", "/").split("/")[-1])
    n = re.sub(r"\s+", " ", n).strip(" .")
    stem, ext = os.path.splitext(n)
    return (stem[:90] + ext[:10]).strip(" .") or "file"

def listing():
    return sorted((e for e in os.scandir(FILES) if e.is_file() and not e.name.startswith(".")),
                  key=lambda e: -e.stat().st_mtime)

def notes():
    try:
        with open(NOTES, encoding="utf-8") as f:
            lines = f.readlines()[-SHOW_NOTES:]
    except FileNotFoundError:
        return []
    out = []
    for l in lines:
        try: out.append(json.loads(l))
        except ValueError: pass   # a torn line must not take the page down
    return out[::-1]

def size(n):
    return (f"{n / 2**30:.1f} GB" if n >= 2**30 else f"{n / 2**20:.1f} MB" if n >= 2**20
            else f"{-(-n // 1024)} KB")

def esc(s):
    return html.escape(s, quote=True)

PAGE = string.Template("""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Notice Board</title><style>
:root { --bg:#f6f5f1; --fg:#1d1d1b; --muted:#5d5b55; --card:#fff; --line:#dedbd2; --accent:#2f6b3a; }
@media (prefers-color-scheme: dark) { :root { --bg:#161714; --fg:#ecebe6; --muted:#a8a69e; --card:#20221e; --line:#34372f; --accent:#7cc38a; } }
* { box-sizing:border-box } body { margin:0; background:var(--bg); color:var(--fg); font:16px/1.5 system-ui, sans-serif }
main { max-width:760px; margin:0 auto; padding:28px 16px } h1 { margin:0 0 4px; font-size:26px } h2 { font-size:19px; margin:28px 0 10px }
p.sub, small, .meta { color:var(--muted) } a { color:var(--accent) } a.back { color:var(--muted); font-size:14px }
input, textarea, button { font:inherit; padding:10px; border:1px solid var(--line); border-radius:8px; background:var(--card); color:inherit }
textarea { width:100%; min-height:80px } form { display:flex; flex-wrap:wrap; gap:8px; margin-bottom:6px }
button { background:var(--accent); color:#fff; border:0; cursor:pointer } input[name=name] { flex:1; min-width:140px }
.note { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:12px 14px; margin-bottom:10px }
.note p { margin:4px 0 0; white-space:pre-wrap; overflow-wrap:anywhere } ul { padding-left:20px } li { margin:4px 0; overflow-wrap:anywhere }
</style></head><body><main>
<a class="back" href="/">&larr; Home</a>
<h1>Notice Board</h1>
<p class="sub">Leave a message or share a file with everyone connected to this box. Anyone here can read
everything, so don't post private information.</p>
<h2>Post a note</h2>
<form method="post" action="note"><textarea name="text" maxlength="$max_note" required placeholder="Your message"></textarea>
<input name="name" maxlength="$max_name" placeholder="Your name (optional)"><button>Post</button></form>
<h2>Files</h2>
<form id="up"><input type="file" id="file" multiple required><button>Upload</button></form>
<small id="upmsg">Up to $max_file per file. $used of $total used.</small>
<ul>$files</ul>
<h2>Notes</h2>
$notes
</main><script>
for (const t of document.querySelectorAll("time")) t.textContent = new Date(t.dateTime).toLocaleString();
const up = document.getElementById("up"), msg = document.getElementById("upmsg");
up.onsubmit = async (e) => {
  e.preventDefault();
  for (const f of document.getElementById("file").files) {
    if (f.size > $max_bytes || !f.size) { msg.textContent = f.name + ": " + (f.size ? "file too big ($max_file limit)" : "empty file"); return; }
    msg.textContent = "Uploading " + f.name + "...";
    const r = await fetch("upload?name=" + encodeURIComponent(f.name), { method: "POST", body: f }).catch(() => null);
    if (!r || !r.ok) { msg.textContent = f.name + ": upload failed: " + (!r ? "no connection" :
                       r.status == 413 ? "file too big ($max_file limit)" : await r.text()); return; }
  }
  location.reload();
};
</script></body></html>""")

def free_name(raw):
    """safe_name(raw), or "x (2).txt", "x (3).txt"... if taken; always a fixed point of safe_name."""
    stem, ext = os.path.splitext(safe_name(raw))
    for k in range(1, MAX_COUNT + 2):
        suffix = f" ({k})" if k > 1 else ""
        name = safe_name(stem[:90 - len(suffix)].rstrip(" .") + suffix + ext)
        if not os.path.exists(os.path.join(FILES, name)): return name
    raise OSError("no free name")

class H(BaseHTTPRequestHandler):
    timeout = 60   # a stalled client (slowloris) frees its thread instead of holding it forever
    def log_message(self, *a): pass

    def reply(self, code, body=b"", ctype="text/plain; charset=utf-8", headers=()):
        if isinstance(body, str): body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in headers: self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD": self.wfile.write(body)

    def do_GET(self):
        path = urllib.parse.urlsplit(self.path).path
        if path.startswith("/files/"):
            name = urllib.parse.unquote(path[7:])
            p = os.path.join(FILES, name)
            if name != safe_name(name) or not os.path.isfile(p):
                return self.reply(404, "not found")
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Disposition", f"attachment; filename=\"{name}\"")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "sandbox")
            self.send_header("Content-Length", str(os.path.getsize(p))); self.end_headers()
            if self.command != "HEAD":
                with open(p, "rb") as f: shutil.copyfileobj(f, self.wfile)
            return
        if path != "/":
            return self.reply(404, "not found")
        files = listing()
        self.reply(200, PAGE.substitute(
            max_note=MAX_NOTE, max_name=MAX_NAME, max_bytes=MAX_FILE, max_file=size(MAX_FILE), total=size(MAX_TOTAL),
            used=size(sum(e.stat().st_size for e in files)),
            files="".join(f"<li><a href=\"files/{urllib.parse.quote(e.name)}\" download>{esc(e.name)}</a> "
                          f"<small>{size(e.stat().st_size)}</small></li>" for e in files) or "<li><small>No files yet.</small></li>",
            notes="".join(f"<div class=\"note\"><div class=\"meta\"><b>{esc(n['name'] or 'Anonymous')}</b> &middot; "
                          f"<time datetime=\"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(n['t']))}\">"
                          f"{time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime(n['t']))}</time></div><p>{esc(n['text'])}</p></div>"
                          for n in notes()) or "<p><small>No notes yet.</small></p>"),
            "text/html; charset=utf-8",
            [("Content-Security-Policy", "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'"),
             ("Cache-Control", "no-store")])

    do_HEAD = do_GET

    def do_POST(self):
        url = urllib.parse.urlsplit(self.path)
        n = int(self.headers.get("Content-Length") or -1)
        if url.path == "/note":
            if n < 0: return self.reply(411, "length required")
            if not 0 < n <= 4 * MAX_NOTE * 3:
                return self.reply(413, "note too long")
            form = urllib.parse.parse_qs(self.rfile.read(n).decode("utf-8", "replace"))
            text = form.get("text", [""])[0].strip()[:MAX_NOTE]
            name = re.sub(r"\s+", " ", form.get("name", [""])[0]).strip()[:MAX_NAME]
            if text:
                with LOCK:
                    if os.path.exists(NOTES) and os.path.getsize(NOTES) > MAX_NOTES_BYTES:   # keep the newest half
                        lines = open(NOTES, encoding="utf-8").readlines()
                        with open(NOTES + ".tmp", "w", encoding="utf-8") as f: f.writelines(lines[len(lines) // 2:])
                        os.replace(NOTES + ".tmp", NOTES)
                    with open(NOTES, "a", encoding="utf-8") as f:
                        f.write(json.dumps({"t": int(time.time()), "name": name, "text": text}) + "\n")
            return self.reply(303, "", headers=[("Location", "./")])
        if url.path == "/upload":
            self.close_connection = True   # on refusal the unread body must not be parsed as a request
            raw = urllib.parse.parse_qs(url.query).get("name", [""])[0]
            global reserved
            if n < 0: return self.reply(411, "length required")
            if n == 0: return self.reply(400, "empty file")
            if n > MAX_FILE: return self.reply(413, f"file too big (limit {size(MAX_FILE)})")
            with LOCK:
                files = listing()
                if len(files) >= MAX_COUNT: return self.reply(507, f"board is full ({MAX_COUNT} files)")
                used = sum(max(e.stat().st_size, 4096) for e in files) + reserved
                if used + n > MAX_TOTAL: return self.reply(507, f"board is full ({size(MAX_TOTAL)} limit)")
                if shutil.disk_usage(DATA).free - reserved - n < MIN_FREE: return self.reply(507, "disk is nearly full")
                reserved += n
                tmp = os.path.join(FILES, f".part-{os.getpid()}-{threading.get_ident()}")
            try:
                with open(tmp, "wb") as f:
                    left = n
                    while left:
                        chunk = self.rfile.read(min(left, 2**20))
                        if not chunk: raise ConnectionError("upload cut short")
                        f.write(chunk); left -= len(chunk)
                with LOCK:
                    name = free_name(raw)
                    os.rename(tmp, os.path.join(FILES, name))
            except Exception as e:
                if os.path.exists(tmp): os.remove(tmp)
                return self.reply(400, f"upload failed: {e}")
            finally:
                with LOCK: reserved -= n
            return self.reply(201, json.dumps({"name": name}), "application/json")
        self.reply(404, "not found")

ThreadingHTTPServer(("", 8000), H).serve_forever()
