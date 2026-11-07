#!/usr/bin/env python3
"""Fetch public-domain USGS aerial imagery (USGSImageryOnly) for a bbox into MBTiles.
   python3 get-satellite.py OUT.mbtiles MINLON MINLAT MAXLON MAXLAT MAXZOOM
   SERVICE=USGSTopo python3 get-satellite.py ...   # USGS topo map tiles instead
Resumable (skips tiles already stored). 4 parallel requests, polite retry/backoff.
Then: pmtiles convert OUT.mbtiles OUT.pmtiles"""
import math, os, sqlite3, sys, time, urllib.error, urllib.request, concurrent.futures as cf

SERVICE = os.environ.get("SERVICE", "USGSImageryOnly")
URL = f"https://basemap.nationalmap.gov/arcgis/rest/services/{SERVICE}/MapServer/tile/{{z}}/{{y}}/{{x}}"
out, w, s, e, n, maxz = sys.argv[1], *map(float, sys.argv[2:6]), int(sys.argv[6])

def tile(lon, lat, z):
    k = 2 ** z
    x = int((lon + 180) / 360 * k)
    y = int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * k)
    return min(x, k - 1), min(y, k - 1)

db = sqlite3.connect(out)
db.executescript("""CREATE TABLE IF NOT EXISTS metadata (name TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS tiles (zoom_level INT, tile_column INT, tile_row INT, tile_data BLOB,
  PRIMARY KEY (zoom_level, tile_column, tile_row));""")
for k, v in {"name": SERVICE, "format": "jpg", "type": "baselayer", "minzoom": "0",
             "maxzoom": str(maxz), "bounds": f"{w},{s},{e},{n}",
             "attribution": "USGS The National Map (public domain)"}.items():
    db.execute("INSERT OR REPLACE INTO metadata VALUES (?,?)", (k, v))
have = {(z, x, (2 ** z - 1) - r) for z, x, r in db.execute("SELECT zoom_level,tile_column,tile_row FROM tiles")}

todo = []
for z in range(maxz + 1):
    x0, y0 = tile(w, n, z); x1, y1 = tile(e, s, z)
    todo += [(z, x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1) if (z, x, y) not in have]
print(f"{len(have)} stored, {len(todo)} to fetch", flush=True)

def get(t):
    z, x, y = t
    for attempt in range(6):
        try:
            req = urllib.request.Request(URL.format(z=z, x=x, y=y), headers={"User-Agent": "prepper-offline-cache/1.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return t, r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:            # no imagery at this tile/zoom (USGS cache stops at z16)
                return t, None
            time.sleep(2 ** attempt)
        except Exception:
            time.sleep(2 ** attempt)
    return t, None

done = fail = 0
with cf.ThreadPoolExecutor(4) as ex:
    for (z, x, y), data in ex.map(get, todo):
        if data and data[:2] == b"\xff\xd8":       # JPEG only; skip error pages/blank
            db.execute("INSERT OR REPLACE INTO tiles VALUES (?,?,?,?)", (z, x, (2 ** z - 1) - y, data))
        else:
            fail += 1
        done += 1
        if done % 1000 == 0:
            db.commit(); print(f"{done}/{len(todo)} (fail {fail})", flush=True)
db.commit()
print(f"ok {done} fetched, {fail} failed", flush=True)
