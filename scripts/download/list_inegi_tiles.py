#!/usr/bin/env python3
"""
Query the INEGI API to find available LiDAR DEM tiles for Yucatan Peninsula states.
Based on the mx-lidar project (github.com/iandees/mx-lidar).
"""
import urllib.request
import json
import re
import sys

# API endpoint from mx-lidar project
API_URL = "http://en.www.inegi.org.mx/app/api/productos/interna_v1/slcComponente/obtenCartasBuscador"

# Theme code for 1:10,000 LiDAR DEMs
TEMA = "MAP0701000000"
ESCALA = "1:10 000"

# INEGI state codes
STATES = {
    "04": "Campeche",
    "23": "Quintana Roo",
    "31": "Yucatan",
}

# Regex to find terrain DEM download URLs (from mx-lidar)
URL_PATTERN = re.compile(r'href="(https?://[0-9a-zA-Z_\./]*Terreno[0-9a-zA-Z_\./]*_b\.zip)"')

all_urls = []

for state_code, state_name in STATES.items():
    page = 1
    state_urls = []
    while True:
        params = json.dumps({
            "entidad": state_code,
            "municipio": "",
            "localidad": "",
            "tema": TEMA,
            "escala": ESCALA,
            "titgen": "",
            "edicion": "",
            "formato": "",
            "buscar": "",
            "adv": False,
            "rango": "",
            "tipoB": 2,
            "orden": 4,
            "pagina": page,
            "tamano": 100,
            "ordenDesc": True,
        }).encode("utf-8")

        try:
            req = urllib.request.Request(
                API_URL,
                data=params,
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Content-Type": "application/json",
                },
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = resp.read().decode("utf-8-sig")
                data = json.loads(body)
        except Exception as e:
            # Try GET with query params as fallback
            qs = (
                f"?entidad={state_code}&municipio=&localidad=&tema={TEMA}"
                f"&titgen=&escala=1:10+000&edicion=&formato=&buscar="
                f"&adv=false&rango=&tipoB=2&orden=4&pagina={page}&tamano=100&ordenDesc=true"
            )
            try:
                req = urllib.request.Request(
                    API_URL + qs,
                    headers={"User-Agent": "Mozilla/5.0"},
                )
                with urllib.request.urlopen(req, timeout=30) as resp:
                    body = resp.read().decode("utf-8-sig")
                    data = json.loads(body)
            except Exception as e2:
                print(f"Error fetching {state_name} page {page}: {e2}", file=sys.stderr)
                print(f"  (first error: {e})", file=sys.stderr)
                break

        registros = data.get("registros", [])
        total = data.get("numResultados", 0)

        if page == 1:
            print(f"{state_name} ({state_code}): {total} total results", file=sys.stderr)

        if not registros:
            break

        for r in registros:
            # Search for download URLs in the record
            record_str = json.dumps(r)
            urls = URL_PATTERN.findall(record_str)
            for u in urls:
                state_urls.append(u)

            # Also check explicit download fields
            for key in ("url_descarga", "descarga", "urlDescarga", "url"):
                if key in r and r[key]:
                    val = r[key]
                    if "Terreno" in val and val.endswith(".zip"):
                        state_urls.append(val)

        if len(registros) < 100:
            break
        page += 1

    print(f"  Found {len(state_urls)} DEM URLs for {state_name}", file=sys.stderr)
    all_urls.extend([(state_name, u) for u in state_urls])

print(f"\nTotal DEM download URLs: {len(all_urls)}", file=sys.stderr)

# Save URLs to file
with open("data/inegi_dem/download_urls.txt", "w") as f:
    for state, url in all_urls:
        f.write(f"{state}\t{url}\n")

# Also dump first few records for debugging
print("\nFirst 3 URLs:" if all_urls else "\nNo URLs found.", file=sys.stderr)
for state, url in all_urls[:3]:
    print(f"  [{state}] {url}", file=sys.stderr)

# If no URLs found via regex, dump raw sample for debugging
if not all_urls:
    print("\nDumping sample record structure for debugging...", file=sys.stderr)
    # Re-fetch one page for Yucatan to show structure
    qs = (
        "?entidad=31&municipio=&localidad=&tema=MAP0701000000"
        "&titgen=&escala=1:10+000&edicion=&formato=&buscar="
        "&adv=false&rango=&tipoB=2&orden=4&pagina=1&tamano=2&ordenDesc=true"
    )
    try:
        req = urllib.request.Request(
            API_URL + qs,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8-sig")
            data = json.loads(body)
            if data.get("registros"):
                print(json.dumps(data["registros"][0], indent=2, ensure_ascii=False), file=sys.stderr)
            else:
                print(json.dumps(data, indent=2, ensure_ascii=False)[:2000], file=sys.stderr)
    except Exception as e:
        print(f"Debug fetch failed: {e}", file=sys.stderr)
