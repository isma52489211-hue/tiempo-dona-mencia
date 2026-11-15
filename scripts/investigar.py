"""Investigación de fiabilidad: compara la lluvia de varias fuentes alrededor de Doña Mencía.
Guarda todo en analisis/investigacion.json. No lo usa la app."""
import json, math, os, time, unicodedata, urllib.request, urllib.error, urllib.parse
from datetime import date, timedelta

KEY = os.environ.get("AEMET_API_KEY", "").strip()
OUT = os.path.join(os.path.dirname(__file__), "..", "analisis", "investigacion.json")
DM = (37.5561, -4.3539)
TODAY = date.today()
P_START = date(2025, 9, 1)            # campaña anterior + actual
YEST = TODAY - timedelta(days=1)
LOG = []


def log(*a):
    m = " ".join(str(x) for x in a); print(m); LOG.append(m)


def http(url, headers=None, tries=4):
    for k in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "tiempo-dona-mencia", **(headers or {})})
            with urllib.request.urlopen(req, timeout=90) as r:
                raw = r.read()
            for enc in ("utf-8", "latin-1"):
                try:
                    return json.loads(raw.decode(enc))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    pass
            return {"_raw": raw[:300].decode("latin-1")}
        except urllib.error.HTTPError as e:
            body = e.read()[:300].decode("latin-1", "ignore")
            if e.code in (429,) or e.code >= 500:
                time.sleep(20 * (k + 1)); continue
            return {"_error": e.code, "_body": body}
        except Exception as e:
            time.sleep(10 * (k + 1)); err = str(e)
    return {"_error": "sin respuesta"}


def aemet(path):
    meta = http("https://opendata.aemet.es/opendata/api" + path, {"api_key": KEY})
    time.sleep(1.3)
    if not isinstance(meta, dict) or meta.get("estado") != 200:
        return []
    d = http(meta["datos"]); time.sleep(1.3)
    return d if isinstance(d, list) else []


def num(v):
    if v is None: return None
    v = str(v).strip().replace(",", ".")
    if v.lower() == "ip": return 0.0
    try: return float(v)
    except ValueError: return None


def dms(v):
    try:
        v = v.strip(); h = v[-1]; v = v[:-1]
        x = int(v[:-4]) + int(v[-4:-2]) / 60 + int(v[-2:]) / 3600
        return -x if h in "SW" else x
    except Exception:
        return None


def km(a, b):
    R = 6371; la1, lo1, la2, lo2 = map(math.radians, (*a, *b))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def norm(s):
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().upper()


res = {"generated": TODAY.isoformat(), "log": LOG}

# ---------- 1. Estaciones de AEMET cercanas ----------
inv = aemet("/valores/climatologicos/inventarioestaciones/todasestaciones")
near = []
for s in inv:
    la, lo = dms(s.get("latitud", "")), dms(s.get("longitud", ""))
    if la is None: continue
    d = km(DM, (la, lo))
    if d <= 40:
        near.append({"id": s["indicativo"], "name": s["nombre"], "prov": s.get("provincia"), "alt": s.get("altitud"),
                     "lat": round(la, 4), "lon": round(lo, 4), "km": round(d, 1)})
near.sort(key=lambda s: s["km"])
res["aemet_stations"] = near
log("AEMET estaciones a <40 km:", len(near))

res["aemet_daily"] = {}
for s in near[:14]:
    days = {}
    d0 = P_START
    while d0 <= YEST:
        d1 = min(d0 + timedelta(days=170), YEST)
        for r in aemet(f"/valores/climatologicos/diarios/datos/fechaini/{d0}T00:00:00UTC/fechafin/{d1}T23:59:59UTC/estacion/{s['id']}"):
            p = num(r.get("prec"))
            if r.get("fecha") and p is not None: days[r["fecha"]] = p
        d0 = d1 + timedelta(days=1)
    res["aemet_daily"][s["id"]] = days
    log(s["id"], s["name"], s["km"], "km · días con dato:", len(days))

# ---------- 2. Histórico largo de la estación de Doña Mencía ----------
long = {}
d0 = date(2010, 1, 1)
while d0 < P_START:
    d1 = min(d0 + timedelta(days=170), P_START - timedelta(days=1))
    for r in aemet(f"/valores/climatologicos/diarios/datos/fechaini/{d0}T00:00:00UTC/fechafin/{d1}T23:59:59UTC/estacion/5427X"):
        p = num(r.get("prec"))
        if r.get("fecha") and p is not None: long[r["fecha"]] = p
    d0 = d1 + timedelta(days=1)
res["aemet_5427X_long"] = long
log("5427X histórico, días:", len(long), "desde", min(long) if long else None)

# ---------- 3. Red de la Junta (RIA) ----------
RIA = "https://www.juntadeandalucia.es/agriculturaypesca/ifapa/riaws"
ria = {"probe": {}}
for path in ["/estaciones", "/estaciones/14", "/estaciones/23"]:
    r = http(RIA + path, {"Accept": "application/json"})
    ria["probe"][path] = r if isinstance(r, list) else r
ria_st = []
for path in ["/estaciones/14", "/estaciones/23", "/estaciones"]:
    r = ria["probe"].get(path)
    if isinstance(r, list):
        for s in r:
            try:
                la, lo = float(s.get("latitud") or s.get("lat")), float(s.get("longitud") or s.get("lon"))
            except Exception:
                la = lo = None
                for k in ("latitud", "longitud"):
                    pass
            ria_st.append({**{k: s.get(k) for k in ("codigoEstacion", "nombre", "altitud", "latitud", "longitud")},
                           "prov": (s.get("provincia") or {}).get("id") if isinstance(s.get("provincia"), dict) else s.get("provincia"),
                           "raw_keys": list(s.keys())})
        if ria_st: break
ria["stations"] = ria_st[:200]
log("RIA estaciones leídas:", len(ria_st))
ria["daily"] = {}
# coordenadas RIA vienen como texto tipo 37º33'20'' N: intentamos convertir
def ria_coord(v):
    if v is None: return None
    try: return float(v)
    except Exception: pass
    import re
    m = re.findall(r"[\d.]+", str(v))
    if len(m) >= 3:
        x = float(m[0]) + float(m[1]) / 60 + float(m[2]) / 3600
        return -x if ("W" in str(v).upper() or "O" in str(v).upper().split()[-1:]) else x
    return None
cands = []
for s in ria_st:
    la, lo = ria_coord(s.get("latitud")), ria_coord(s.get("longitud"))
    if la and lo:
        if lo > 0: lo = -lo
        s["lat_dec"], s["lon_dec"], s["km"] = round(la, 4), round(lo, 4), round(km(DM, (la, lo)), 1)
        cands.append(s)
cands.sort(key=lambda s: s["km"])
ria["near"] = cands[:6]
for s in cands[:6]:
    prov, cod = s.get("prov"), s.get("codigoEstacion")
    got = None
    for path in [f"/datosdiarios/forceEt0/{prov}/{cod}/{P_START}/{YEST}", f"/datosdiarios/{prov}/{cod}/{P_START}/{YEST}/true", f"/datosdiarios/{prov}/{cod}/{P_START}/{YEST}"]:
        r = http(RIA + path, {"Accept": "application/json"})
        if isinstance(r, list) and r:
            got = {x.get("fecha", "")[:10]: x.get("precipitacion") for x in r}
            s["path_ok"] = path; break
        s.setdefault("errors", []).append({path: r if not isinstance(r, list) else "vacío"})
    if got: ria["daily"][f"{prov}-{cod}"] = got
    log("RIA", s.get("nombre"), s.get("km"), "km · días:", len(got or {}))
res["ria"] = ria

# ---------- 4. Modelos (Open-Meteo) en Doña Mencía y en cada estación ----------
pts = [{"id": "DM", "lat": DM[0], "lon": DM[1]}] + [{"id": s["id"], "lat": s["lat"], "lon": s["lon"]} for s in near[:8]]
for s in ria["near"][:3]:
    if s.get("lat_dec"): pts.append({"id": "RIA-" + str(s.get("codigoEstacion")), "lat": s["lat_dec"], "lon": s["lon_dec"]})
HF = ["best_match", "ecmwf_ifs025", "icon_seamless", "meteofrance_seamless", "gfs_seamless", "ukmo_seamless"]
AR = ["era5", "era5_land", "era5_seamless", "ecmwf_ifs"]
res["models"] = {}
for p in pts:
    res["models"][p["id"]] = {}
    for base, models, end in (("https://historical-forecast-api.open-meteo.com/v1/forecast", HF, YEST),
                              ("https://archive-api.open-meteo.com/v1/archive", AR, YEST)):
        for m in models:
            q = urllib.parse.urlencode({"latitude": p["lat"], "longitude": p["lon"], "start_date": P_START, "end_date": end,
                                        "daily": "precipitation_sum", "timezone": "Europe/Madrid", "models": m})
            r = http(f"{base}?{q}"); time.sleep(0.4)
            if isinstance(r, dict) and r.get("daily"):
                res["models"][p["id"]][m] = dict(zip(r["daily"]["time"], r["daily"]["precipitation_sum"]))
            else:
                log("modelo sin datos", p["id"], m, str(r)[:120])
    log("modelos", p["id"], list(res["models"][p["id"]].keys()))

# ERA5 largo en Doña Mencía, para comparar con el histórico de la estación
q = urllib.parse.urlencode({"latitude": DM[0], "longitude": DM[1], "start_date": "2010-01-01", "end_date": str(P_START - timedelta(days=1)),
                            "daily": "precipitation_sum", "timezone": "Europe/Madrid", "models": "era5"})
r = http("https://archive-api.open-meteo.com/v1/archive?" + q)
if isinstance(r, dict) and r.get("daily"): res["era5_long_DM"] = dict(zip(r["daily"]["time"], r["daily"]["precipitation_sum"]))

os.makedirs(os.path.dirname(OUT), exist_ok=True)
json.dump(res, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
log("hecho")
