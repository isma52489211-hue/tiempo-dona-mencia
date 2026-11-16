import json,urllib.request,urllib.parse,time
B="https://api.open-meteo.com/v1/forecast"
P={"latitude":37.5553,"longitude":-4.3592,"timezone":"Europe/Madrid","forecast_days":4,"daily":"precipitation_sum,precipitation_probability_max"}
M=["best_match","ecmwf_ifs","ecmwf_ifs025","icon_seamless","meteofrance_seamless","gfs_seamless","ukmo_seamless","jma_seamless","gem_seamless","knmi_seamless","dmi_seamless","italia_meteo_arpae_icon_2i"]
out={}
for m in M:
    try:
        r=json.load(urllib.request.urlopen(B+"?"+urllib.parse.urlencode({**P,"models":m}),timeout=60))
        out[m]=r["daily"]
    except Exception as e: out[m]=str(e)[:150]
    time.sleep(.5)
try:
    r=json.load(urllib.request.urlopen("https://ensemble-api.open-meteo.com/v1/ensemble?"+urllib.parse.urlencode({"latitude":37.5553,"longitude":-4.3592,"timezone":"Europe/Madrid","forecast_days":4,"hourly":"precipitation","models":"ecmwf_ifs025"}),timeout=60))
    out["ensemble_ecmwf"]=r["hourly"]
except Exception as e: out["ensemble_ecmwf"]=str(e)[:150]
json.dump(out,open("analisis/prevision.json","w"))
