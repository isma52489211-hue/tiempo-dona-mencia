"""Descarga la lluvia medida por AEMET en la estación de Doña Mencía y la guarda en data/aemet.json.

- Valores diarios oficiales (climatológicos): llegan con unos días de retraso.
- Observaciones horarias de las últimas horas: se van acumulando ejecución tras ejecución
  para cubrir los días que aún no tienen valor diario oficial.
Si la clave falla o caduca, se guarda el estado para que la app siga funcionando con el modelo.
"""
import json, os, sys, time, unicodedata, urllib.request, urllib.error
from datetime import datetime, date, timedelta, timezone
from zoneinfo import ZoneInfo

API = "https://opendata.aemet.es/opendata/api"
KEY = os.environ.get("AEMET_API_KEY", "").strip()
OUT = os.path.join(os.path.dirname(__file__), "..", "data", "aemet.json")
TZ = ZoneInfo("Europe/Madrid")
START_MONTH = 9


def norm(s):
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().upper()


def get(url, tries=4):
    for k in range(tries):
        try:
            req = urllib.request.Request(url, headers={"api_key": KEY, "Accept": "application/json", "User-Agent": "tiempo-dona-mencia"})
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = r.read()
            for enc in ("utf-8", "latin-1"):
                try:
                    return json.loads(raw.decode(enc))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
            raise ValueError("Respuesta no válida de AEMET")
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise PermissionError(f"AEMET rechaza la clave (HTTP {e.code}). Puede haber caducado.")
            if e.code == 429 or e.code >= 500:
                time.sleep(15 * (k + 1)); continue
            raise
        except (urllib.error.URLError, TimeoutError):
            time.sleep(10 * (k + 1))
    raise RuntimeError("AEMET no responde")


def api(path):
    meta = get(f"{API}{path}")
    estado = meta.get("estado")
    if estado == 401:
        raise PermissionError(meta.get("descripcion") or "Clave no válida o caducada")
    if estado == 404:
        return []
    if estado != 200 or not meta.get("datos"):
        raise RuntimeError(f"AEMET: {meta.get('descripcion') or meta}")
    time.sleep(1.5)
    return get(meta["datos"])


def num(v):
    if v is None:
        return None
    v = str(v).strip().replace(",", ".")
    if v.lower() == "ip":       # inapreciable
        return 0.0
    try:
        return float(v)
    except ValueError:
        return None             # "Acum" u otros: sin dato fiable ese día


def dms(v):
    try:
        v = v.strip(); h = v[-1]; v = v[:-1]
        d, m, s = int(v[:-4]), int(v[-4:-2]), int(v[-2:])
        x = d + m / 60 + s / 3600
        return round(-x if h in "SW" else x, 4)
    except Exception:
        return None


def main():
    try:
        old = json.load(open(OUT, encoding="utf-8"))
    except Exception:
        old = {}
    out = {"updated": datetime.now(timezone.utc).isoformat(timespec="minutes"), "status": "ok",
           "station": old.get("station"), "daily": old.get("daily", {}), "obsHourly": old.get("obsHourly", {})}
    if not KEY:
        out["status"] = "no_key"; out["message"] = "Falta el secreto AEMET_API_KEY"
        return finish(out)
    try:
        # 1) estación de Doña Mencía (solo la primera vez o si falta)
        if not out["station"]:
            inv = api("/valores/climatologicos/inventarioestaciones/todasestaciones")
            cands = [s for s in inv if "MENCIA" in norm(s.get("nombre"))]
            out["candidates"] = cands
            if not cands:
                out["status"] = "no_station"; out["message"] = "No hay estación de AEMET con ese nombre"
                return finish(out)
            s = sorted(cands, key=lambda s: "CORDOBA" not in norm(s.get("provincia")))[0]
            out["station"] = {"id": s.get("indicativo"), "name": s.get("nombre"), "province": s.get("provincia"),
                              "altitude": s.get("altitud"), "lat": dms(s.get("latitud", "")), "lon": dms(s.get("longitud", ""))}
        sid = out["station"]["id"]

        # 2) valores diarios oficiales desde el inicio de la campaña (y la anterior, para comparar)
        today = datetime.now(TZ).date()
        cstart = date(today.year if today.month >= START_MONTH else today.year - 1, START_MONTH, 1)
        start = date(cstart.year - 1, START_MONTH, 1)
        d0 = start
        while d0 <= today:
            d1 = min(d0 + timedelta(days=170), today)
            rows = api(f"/valores/climatologicos/diarios/datos/fechaini/{d0}T00:00:00UTC/fechafin/{d1}T23:59:59UTC/estacion/{sid}")
            for r in rows or []:
                p = num(r.get("prec"))
                if r.get("fecha") and p is not None:
                    out["daily"][r["fecha"]] = p
            d0 = d1 + timedelta(days=1)

        # 3) observaciones horarias recientes (se acumulan entre ejecuciones)
        try:
            for r in api(f"/observacion/convencional/datos/estacion/{sid}") or []:
                p = num(r.get("prec"))
                if r.get("fint") and p is not None:
                    out["obsHourly"][r["fint"]] = p
        except RuntimeError as e:
            out["obsMessage"] = str(e)
        cutoff = (datetime.now(timezone.utc) - timedelta(days=21)).strftime("%Y-%m-%dT%H")
        out["obsHourly"] = {k: v for k, v in sorted(out["obsHourly"].items()) if k >= cutoff}
        by_day = {}
        for k, v in out["obsHourly"].items():
            t = datetime.fromisoformat(k.replace("Z", "+00:00"))
            if t.tzinfo is None:
                t = t.replace(tzinfo=timezone.utc)
            dl = (t - timedelta(seconds=1)).astimezone(TZ).date().isoformat()   # la hora acumula lo caído antes de 'fint'
            by_day[dl] = round(by_day.get(dl, 0) + v, 1)
        out["obsDaily"] = by_day
        out["daily"] = dict(sorted(out["daily"].items()))
        out["lastDaily"] = max(out["daily"]) if out["daily"] else None
    except PermissionError as e:
        out["status"] = "key_error"; out["message"] = str(e)
    except Exception as e:
        out["status"] = "error"; out["message"] = str(e)[:300]
    return finish(out)


def finish(out):
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(json.dumps({k: out.get(k) for k in ("status", "message", "station", "lastDaily")}, ensure_ascii=False))
    print("dias oficiales:", len(out.get("daily", {})), "| horas observadas:", len(out.get("obsHourly", {})))
    if out["status"] in ("key_error", "no_key"):
        sys.exit(1)   # que el fallo se vea en GitHub (y llegue el aviso por correo)


if __name__ == "__main__":
    main()
