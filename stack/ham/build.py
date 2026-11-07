#!/usr/bin/env python3
"""Ham radio pack: offline radio reference -> one small searchable ZIM.

Hand-written pages (pages/*.html: band privileges, calling frequencies, phonetics/Q-codes/RST,
emergency nets, marine VHF) are wrapped as-is. Everything else is fetched at build time from the
authoritative source and rendered, so it is never typed from memory:
  - FCC Part 97 (whole part) and the FRS/GMRS/MURS/CB/marine sections of Parts 95 and 80, from eCFR;
  - NOAA Weather Radio transmitters near HOME, from the NWS station data.
If eCFR has amended a section the hand-written band page was checked against, the build says so
and the page carries a warning until CHECKED below is updated.

  HOME_LOC="39.83,-98.58,Lebanon KS" CALL=N0CALL python3 build.py /srv/prepper/ham /srv/prepper/zim
Needs zim-tools (zimwriterfs) and internet at build time.
"""
import datetime, html, json, math, os, re, shutil, struct, subprocess, sys, urllib.request, zlib

HERE = os.path.dirname(os.path.abspath(__file__))
DATA, ZIMDIR = sys.argv[1], sys.argv[2]
SITE = os.path.join(DATA, ".site")
NAME = "prepper-ham_en_all"
_h = os.environ.get("HOME_LOC", "39.83,-98.58,the middle of the USA").split(",", 2)   # lat,lon,place name
HOME, PLACE = (float(_h[0]), float(_h[1])), (_h[2] if len(_h) > 2 else "your area")
CALL = os.environ.get("CALL", "")
NWR_KM = 160
UA = {"User-Agent": "prepper-ham-build (offline reference)", "Accept-Encoding": "gzip"}
# Last amendment cited by each eCFR section, as of when pages/bands.html was checked against it.
CHECKED = {"97.301": "91 FR 1430, Jan. 14, 2026", "97.303": "91 FR 1430, Jan. 14, 2026", "97.305": "91 FR 1431, Jan. 14, 2026",
           "97.307": "91 FR 1431, Jan. 14, 2026", "97.313": "91 FR 1431, Jan. 14, 2026"}

def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r:
        body = r.read()
        return (zlib.decompress(body, 31) if r.headers.get("Content-Encoding") == "gzip" else body).decode("utf-8")

# --- eCFR ---------------------------------------------------------------------------------------
title47 = next(t for t in json.loads(get("https://www.ecfr.gov/api/versioner/v1/titles.json"))["titles"] if t["number"] == 47)
ASOF = title47["up_to_date_as_of"]
xml = {p: get(f"https://www.ecfr.gov/api/versioner/v1/full/{ASOF}/title-47.xml?part={p}") for p in (97, 95, 80)}

def sec(n):
    return re.search(r'<DIV8 N="%s".*?</DIV8>' % re.escape(n), xml[int(n.split(".")[0])], re.S).group(0)

def ecfr_html(x):
    """eCFR XML is nearly HTML: map its tags, keep tables, drop metadata attributes."""
    x = re.sub(r'<DIV[5-7] [^>]*>\s*<HEAD>(.*?)</HEAD>', r'<section><h2>\1</h2>', x, flags=re.S)
    x = re.sub(r'<DIV[89] N="([^"]*)"[^>]*>\s*<HEAD>(.*?)</HEAD>',
               lambda m: f'<section id="s{m[1].replace(".", "-")}"><h3>{m[2]}</h3>', x, flags=re.S)
    x = re.sub(r'</DIV[5-9]>', '</section>', x)
    x = re.sub(r'<(CITA|SOURCE|AUTH|EDNOTE)[^>]*>(.*?)</\1>', r'<p class="cita">\2</p>', x, flags=re.S)
    x = re.sub(r'<E T="[^"]*">', '<em>', x).replace('</E>', '</em>')
    x = re.sub(r'<(/?)HED>', r'<\1b>', x); x = re.sub(r'<PSPACE>', '<p>', x).replace('</PSPACE>', '</p>')
    x = re.sub(r'<(/?)NOTE>', r'<\1div>', x)
    x = re.sub(r'<(/?)(DIV|TABLE|THEAD|TBODY|TFOOT|TR|TD|TH|P|I|HEAD)\b[^>]*?(/?)>',
               lambda m: f'<{m[1]}{ {"HEAD": "h4"}.get(m[2], m[2].lower()) }{m[3]}>', x)
    return x.replace('<td/>', '<td></td>')

def last_amended(n):   # "[54 FR 25857, ...; 91 FR 1430, Jan. 14, 2026]" -> "91 FR 1430, Jan. 14, 2026"
    c = re.findall(r"\[([^\[\]]*FR[^\[\]]*)\]", sec(n))
    return c[-1].split(";")[-1].strip() if c else None

changed = [n for n, c in CHECKED.items() if last_amended(n) != c]
for n in changed:
    print(f"!! eCFR § {n} last amended {last_amended(n)}; pages/bands.html was checked against {CHECKED[n]}. Review it.", flush=True)

def rows(section):   # table rows of an eCFR section -> lists of cell texts
    return [[html.unescape(re.sub(r"<[^>]+>", "", c)).strip() for c in re.findall(r"<TD[^>]*>(.*?)</TD>|<TD[^>]*/>", r, re.S)]
            for r in re.findall(r"<TR>(.*?)</TR>", section, re.S)]

def mhz(text):
    return re.findall(r"\b(\d{3}\.\d{3,4})\b", re.sub(r"<[^>]+>", "", text))

# --- channel tables, straight from Part 95 ----------------------------------------------------------
frs = [r for r in rows(sec("95.563")) if len(r) == 2 and r[0].isdigit()]
gmrs = {k: mhz(re.search(r"\(%s\).*?</P>" % k, sec("95.1763"), re.S).group(0)) for k in "abcd"}
murs = mhz(sec("95.2763"))
cb = [r for r in rows(sec("95.963")) if len(r) == 2 and r[0].isdigit()]
assert len(frs) == 22 and len(cb) == 40 and len(murs) == 5 and [len(v) for v in gmrs.values()] == [8, 7, 8, 7], "eCFR layout changed"
rep_in = dict(zip(gmrs["a"], gmrs["c"]))   # 462 MHz main channel -> its 467 MHz repeater input

def frs_row(ch, f):
    f = f"{float(f):.4f}"
    if f in gmrs["a"]: use = "FRS 2 W / GMRS 50 W main channel"; rin = f"{ch}R: repeater output; input {rep_in[f]}"
    elif f in gmrs["b"]: use, rin = "FRS 2 W / GMRS 5 W ERP interstitial", ""
    else: use, rin = "FRS 0.5 W / GMRS 0.5 W ERP (handhelds only)", ""
    return f"<tr><td>{ch}</td><td>{f}</td><td>{use}</td><td>{rin}</td></tr>"

channels = (
    "<h1>FRS, GMRS, MURS and CB channels</h1><p class='meta'>Channel tables generated from the eCFR text of "
    f"47 CFR Part 95 as of {ASOF}; the rule text follows each table.</p>"
    "<h2>FRS / GMRS (UHF, 462/467 MHz, FM)</h2><p>FRS needs no license; GMRS needs an FCC license (no exam) "
    "that covers the holder's family. Channel numbers are the FRS numbers in § 95.563; most radios use them.</p>"
    "<table><tr><th>Ch</th><th>MHz</th><th>Power limit (§ 95.567, § 95.1767)</th><th>GMRS repeater</th></tr>"
    + "".join(frs_row(c, f) for c, f in frs) + "</table>"
    + "".join(ecfr_html(sec(n)) for n in ("95.563", "95.567", "95.1763", "95.1767"))
    + "<h2>MURS (VHF, no license)</h2><table><tr><th>Ch</th><th>MHz</th></tr>"
    + "".join(f"<tr><td>{i}</td><td>{f}</td></tr>" for i, f in enumerate(murs, 1))
    + "</table><p>2 W transmitter output (§ 95.2767).</p>" + "".join(ecfr_html(sec(n)) for n in ("95.2763", "95.2767"))
    + "<h2>CB (27 MHz, no license)</h2><p><b>Channel 9 is for emergencies and traveler assistance only</b> "
    "(§ 95.931). Channel 19 is the customary highway channel (custom, not a rule). 4 W AM/FM carrier, 12 W PEP SSB (§ 95.967).</p>"
    "<table><tr><th>Ch</th><th>MHz</th></tr>" + "".join(f"<tr><td>{c}</td><td>{f}</td></tr>" for c, f in cb) + "</table>"
    + "".join(ecfr_html(sec(n)) for n in ("95.963", "95.967", "95.931")))

# --- NOAA Weather Radio near home -------------------------------------------------------------------
nwr = json.loads(re.search(r"=\s*(\[.*\])", get("https://www.weather.gov/source/nwr/JS/ccl-data.js"), re.S).group(1))
def km(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (*a, *b))
    return 6371 * 2 * math.asin(math.sqrt(math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2))
near = sorted(((km(HOME, (float(s["lat"]), float(s["lon"]))), s) for s in nwr if s.get("lat") and s.get("lon")), key=lambda x: x[0])
near = [(d, s) for d, s in near if d <= NWR_KM]
weather = (
    "<h1>NOAA Weather Radio</h1><p class='meta'>From the National Weather Service NWR station data, fetched "
    f"{datetime.date.today()}. Transmitters within {NWR_KM} km of {PLACE}, nearest first.</p>"
    "<p>NWR broadcasts on seven VHF FM channels: " + ", ".join(sorted({s['freq'] for s in nwr if s.get('freq')})) + " MHz. "
    "A scanner, a ham handheld with wide receive, or a weather radio picks them up. Weather radios with SAME "
    "alerting can be set to sound only for the counties you choose, using the 6-digit SAME codes below.</p>"
    "<table><tr><th>km</th><th>Call</th><th>MHz</th><th>Transmitter</th><th>Watts</th><th>Status</th><th>Counties (SAME code)</th></tr>"
    + "".join(f"<tr><td>{d:.0f}</td><td>{html.escape(s['callsign'])}</td><td><b>{html.escape(s['freq'])}</b></td>"
              f"<td>{html.escape(s['sitename'])}, {html.escape(s['sitestate'])} ({html.escape(s.get('siteloc', ''))})</td>"
              f"<td>{html.escape(s.get('power', ''))}</td><td>{html.escape(s.get('status', ''))}</td><td><small>"
              + ", ".join(f"{html.escape(c['county'])} {c['st']} ({c['same']})" for c in s.get("counties", []))
              + "</small></td></tr>" for d, s in near) + "</table>")

# --- site ---------------------------------------------------------------------------------------------
shutil.rmtree(SITE, ignore_errors=True); os.makedirs(SITE)
open(os.path.join(SITE, "style.css"), "w").write(
    """body{margin:0;font:16px/1.55 system-ui,sans-serif;color:#222;background:#fbfaf6}main{max-width:860px;margin:0 auto;padding:24px 16px}
h1{font-size:26px;margin:0 0 6px}h2{font-size:20px;margin-top:30px}h3{font-size:17px;margin-top:24px}h4{font-size:15px}
.meta,.cita,small{color:#666;font-size:14px}a{color:#2f6b3a}table{border-collapse:collapse;margin:10px 0;font-size:15px}
td,th{border:1px solid #ccc;padding:4px 8px;vertical-align:top;text-align:left}th{background:#eee}
.warn{background:#fff3cd;border:1px solid #e0c060;padding:10px 14px;border-radius:6px}.src{font-size:14px}
nav{font:14px system-ui,sans-serif;margin-bottom:14px}""")

PAGES = [("bands.html", "Band privileges by license class"), ("calling.html", "Calling and simplex frequencies"),
         ("phonetics.html", "Phonetic alphabet, Q-codes and RST"), ("emergency.html", "Emergency nets and messages"),
         ("channels.html", "FRS, GMRS, MURS and CB channels"), ("marine.html", "Marine VHF channels"),
         ("weather.html", "NOAA Weather Radio"), ("part97.html", "FCC Part 97 (full text)")]

def page(path, title, body):
    nav = "<nav><a href='index.html'>Ham radio pack</a> · " + " · ".join(
        f"<a href='{p}'>{html.escape(t.split(' (')[0])}</a>" for p, t in PAGES if p != path) + "</nav>"
    with open(os.path.join(SITE, path), "w", encoding="utf-8") as f:
        f.write(f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" '
                f'content="width=device-width,initial-scale=1"><title>{html.escape(title)}</title>'
                f'<link rel="stylesheet" href="style.css"></head><body><main>{nav}{body}</main></body></html>')

def frag(name):
    return open(os.path.join(HERE, "pages", name), encoding="utf-8").read()

warn = ("<p class='warn'>⚠ eCFR has amended " + ", ".join(f"§ {n}" for n in changed) + " since this page was checked. "
        "The full Part 97 text in this pack is current; trust it over this table.</p>") if changed else ""
page("bands.html", PAGES[0][1], warn + frag("bands.html"))
page("calling.html", PAGES[1][1], frag("calling.html"))
page("phonetics.html", PAGES[2][1], frag("phonetics.html"))
page("emergency.html", PAGES[3][1], frag("emergency.html")
     + "<h2>The rules (47 CFR, eCFR text)</h2>" + "".join(ecfr_html(sec(n)) for n in ("97.403", "97.405", "97.119")))
page("channels.html", PAGES[4][1], channels)
page("marine.html", PAGES[5][1], frag("marine.html") + ecfr_html(re.search(
    r'<P>\(f\) (?:<[^>]+>)?Frequencies in the 156-162 MHz band.*?(?=<P>\(g\))', sec("80.373"), re.S).group(0)))
page("weather.html", PAGES[6][1], weather)
p97 = ecfr_html(xml[97])
toc = "".join(f"<li><a href='#{i}'>{t}</a></li>" for i, t in re.findall(r'<section id="([^"]+)"><h3>(.*?)</h3>', p97))
page("part97.html", PAGES[7][1], f"<h1>47 CFR Part 97 — Amateur Radio Service</h1><p class='meta'>Full text from the "
     f"Electronic Code of Federal Regulations (ecfr.gov), up to date as of {ASOF}.</p><details><summary>Sections</summary>"
     f"<ul>{toc}</ul></details>{p97}")
page("index.html", "Ham Radio Pack",
     "<h1>Ham Radio Pack</h1><p class='meta'>Offline radio reference" + (f" for {CALL}" if CALL else "") + f", {PLACE}. Built "
     f"{datetime.date.today()}; FCC rules current as of {ASOF}.</p><ul>"
     + "".join(f"<li><a href='{p}'>{html.escape(t)}</a></li>" for p, t in PAGES) + "</ul>" + frag("sources.html"))

def png48(path):  # plain blue square illustration (zimwriterfs requires a 48x48 PNG)
    raw = b"".join(b"\x00" + bytes((40, 80, 140)) * 48 for _ in range(48))
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d))
    open(path, "wb").write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 48, 48, 8, 2, 0, 0, 0))
                           + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
png48(os.path.join(SITE, "icon.png"))

# --- ZIM ------------------------------------------------------------------------------------------------
out = os.path.join(ZIMDIR, ".dl", f"{NAME}_{datetime.date.today():%Y-%m}.zim")
os.makedirs(os.path.dirname(out), exist_ok=True)
if os.path.exists(out): os.remove(out)
subprocess.run(["zimwriterfs", "--welcome=index.html", "--illustration=icon.png", "--language=eng",
                "--title=Ham Radio Pack", "--description=US band plan, channels, Part 97, nets and weather radio",
                "--creator=FCC eCFR, NWS, ARRL (cited)", "--publisher=prepper", f"--name={NAME}",
                SITE, out], check=True)
for old in os.listdir(ZIMDIR):
    if old.startswith(NAME + "_") and old.endswith(".zim"):
        os.remove(os.path.join(ZIMDIR, old))
os.rename(out, os.path.join(ZIMDIR, os.path.basename(out)))
print(f"ok {len(PAGES) + 1} pages, {len(near)} NWR transmitters -> {os.path.basename(out)}")
