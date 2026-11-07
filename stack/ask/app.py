"""Ask the Library: answer a question from the offline Kiwix library with the local LLM.

Search Kiwix full text -> read the top articles -> keep the passages that best match the
question -> the model answers from those passages only, citing [1], [2]... Python stdlib only.
POST /api {"q": "..."} streams: one JSON line of sources, then the answer text.
"""
import html, json, os, re, time, urllib.parse, urllib.request
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

KIWIX = os.environ.get("KIWIX", "http://kiwix:8080")
OLLAMA = os.environ.get("OLLAMA", "http://ollama:11434")
MODEL = os.environ.get("MODEL", "llama3.2:3b")
ARTICLES, PASSAGES, PASSAGE_WORDS = 3, 3, 100   # ~300 words of context: CPU prompt eval is ~15 tok/s
STOP = set("""a an the and or of to in on at for from by with without is are was were be been being do does did
how what why when where which who whom can could should would will i me my we you your it its this that these
those there their them they he she his her if then than so as about into out up down over under any some""".split())

def get(url, timeout=30):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")

_books = {"t": 0, "names": []}
def english_books():
    # Kiwix refuses to search across books in different languages (400), and the TED-Ed ZIM is
    # multilingual. So search names only the English-only books; refreshed every 10 min so new
    # downloads join automatically.
    if time.time() - _books["t"] > 600 or not _books["names"]:
        try:
            xml = get(f"{KIWIX}/catalog/v2/entries?count=1000")
        except Exception:   # Kiwix blip (e.g. restarting for a new ZIM): keep the last list
            _books["t"] = time.time() - 540   # retry in a minute, not on every question
            return _books["names"]
        names = []
        for e in re.findall(r"<entry>(.*?)</entry>", xml, re.S):
            lang = re.search(r"<language>(.*?)</language>", e)
            link = re.search(r'href="/content/([^"/]+)', e)
            if lang and link and lang.group(1) == "eng":
                names.append(link.group(1))
        _books.update(t=time.time(), names=names)
    return _books["names"]

def keywords(q):
    return [w for w in re.findall(r"[a-z0-9']+", q.lower()) if w not in STOP and len(w) > 1]

def search(q):
    # "how do I can tomatoes" -> canning, not the filler word "can"
    q = re.sub(r"(?i)\b(i|to|you|we) can\b", r"\1 canning", q)
    kw = keywords(q)
    items = []
    # Two queries, merged in order: all keywords (precise), then the 3 longest (broader).
    for pattern in dict.fromkeys([" ".join(kw) or q, " ".join(sorted(kw, key=len)[-3:])]):
        params = [("pattern", pattern), ("format", "xml"), ("pageLength", 8)]
        params += [("books.name", n) for n in english_books()]
        xml = get(f"{KIWIX}/search?{urllib.parse.urlencode(params)}")
        items += re.findall(r"<item>.*?<title>(.*?)</title>.*?<link>(.*?)</link>.*?<book>.*?<title>(.*?)</title>", xml, re.S)
    seen, out = set(), []
    for title, link, book in items:
        t = html.unescape(title)
        if t.lower() in seen:            # same article in two books (WikiMed + Wikipedia)
            continue
        seen.add(t.lower()); out.append({"title": t, "link": html.unescape(link), "book": html.unescape(book)})
    return out[:ARTICLES]

def paragraphs(page):
    page = re.sub(r"(?is)<(script|style|table|nav|sup)[^>]*>.*?</\1>", " ", page)
    # \b so "<li" doesn't match "<link ...>" in the page head
    paras = [m[1] for m in re.findall(r"(?is)<(p|li)\b[^>]*>(.*?)</\1>", page)]
    out = []
    for p in paras:
        words = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", p))).strip().split()
        if len(words) < 12:
            continue
        # Long paragraphs (scanned PDFs are often one block per page) -> overlapping windows,
        # so the how-to part deep in an article can be picked, not just its opening lines.
        step = PASSAGE_WORDS * 3 // 4
        for k in range(0, max(1, len(words) - PASSAGE_WORDS // 4), step):
            out.append(" ".join(words[k:k + PASSAGE_WORDS]))
    return out

def context(q, hits):
    kw = set(keywords(q))
    scored = []
    for i, h in enumerate(hits):
        try:
            paras = paragraphs(get(KIWIX + h["link"]))
        except Exception:
            continue
        for j, p in enumerate(paras[:200]):
            words = set(re.findall(r"[a-z0-9']+", p.lower()))
            score = len(kw & words) + (1.5 if j < 2 else 0) - i * 0.5   # favour leads + top hits
            scored.append((score, i, p))
    scored.sort(key=lambda s: -s[0])
    return [(i, p) for _, i, p in scored[:PASSAGES]]

SYSTEM = """You answer questions using ONLY the numbered library excerpts the user gives you.
Write a practical answer of 3 to 8 sentences or short steps, and put the excerpt number in
brackets after each fact, like [1]. If the excerpts do not answer the question, say so plainly
instead of guessing. For medical emergencies, say to get professional help when possible."""
USER = "Library excerpts:\n\n{ctx}\n\nQuestion: {q}"

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def do_GET(self):
        body = open(os.path.join(os.path.dirname(__file__), "index.html"), "rb").read()
        self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

    def do_POST(self):
        q = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}").get("q", "").strip()[:500]
        self.send_response(200); self.send_header("Content-Type", "text/plain; charset=utf-8"); self.end_headers()
        def send(s):
            self.wfile.write(s.encode()); self.wfile.flush()
        try:
            hits = search(q)
            passages = context(q, hits) if hits else []
            send(json.dumps({"sources": hits}) + "\n")
            if not passages:
                send("Nothing in the library matched that. Try different words."); return
            ctx = "\n\n".join(f"[{i + 1}] ({hits[i]['title']}) {p}" for i, p in passages)
            req = urllib.request.Request(f"{OLLAMA}/api/chat", method="POST",
                data=json.dumps({"model": MODEL, "stream": True,
                                 "messages": [{"role": "system", "content": SYSTEM},
                                              {"role": "user", "content": USER.format(ctx=ctx, q=q)}],
                                 "options": {"num_ctx": 2048, "temperature": 0.2}}).encode())
            answer = ""
            with urllib.request.urlopen(req, timeout=600) as r:
                for line in r:
                    if line.strip():
                        piece = json.loads(line).get("message", {}).get("content", "")
                        answer += piece; send(piece)
            # Small models sometimes invent citations; say so rather than let it pass.
            valid = {i + 1 for i, _ in passages}
            cited = {int(n) for n in re.findall(r"\[(\d+)\]", answer)}
            if cited - valid or not cited:
                send("\n\n⚠ This answer cites sources that weren't provided (or none at all). "
                     "Treat it with caution and read the sources below.")
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            send(f"\n[error: {e}]")

ThreadingHTTPServer(("", 8000), H).serve_forever()
