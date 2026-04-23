#!/usr/bin/env python3
"""
Download INEGI CEM (Continuo de Elevaciones Mexicano) state-level DEMs
for Yucatan Peninsula states using the CEM portal's internal API.

Downloads 15m resolution CEM GeoTIFF files for: Campeche, Quintana Roo, Yucatan.
These are the state-level CEM products (not the per-tile 5m LiDAR DEMs).
"""
import urllib.request
import json
import os
import sys

BASE = "https://www.inegi.org.mx/app/geo2/elevacionesmex"
HEADERS = {"User-Agent": "Mozilla/5.0"}
OUTDIR = "data/inegi_dem"

# State codes: Campeche=04, Quintana Roo=23, Yucatan=31
STATES = {"04": "Campeche", "23": "Quintana_Roo", "31": "Yucatan"}


def api_get(path):
    """GET from the CEM portal API."""
    url = f"{BASE}/{path}"
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8-sig"))


def download_file(url, dest):
    """Download a file with progress."""
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=300) as resp:
        total = resp.headers.get("Content-Length")
        total = int(total) if total else None
        downloaded = 0
        with open(dest, "wb") as f:
            while True:
                chunk = resp.read(8192)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                if total:
                    pct = downloaded * 100 // total
                    print(f"\r  {downloaded // 1024}KB / {total // 1024}KB ({pct}%)", end="", flush=True)
                else:
                    print(f"\r  {downloaded // 1024}KB", end="", flush=True)
    print()


def main():
    os.makedirs(OUTDIR, exist_ok=True)

    # Step 1: Get available versions
    print("Fetching CEM versions...")
    versions = api_get("api/versiones")
    print(f"  Available versions: {json.dumps(versions, indent=2, ensure_ascii=False)}")

    if not versions:
        print("ERROR: No versions returned. Portal may be down.")
        sys.exit(1)

    # Use latest version
    latest = versions[-1] if isinstance(versions, list) else versions
    version_id = latest.get("id", latest.get("version", 1))
    print(f"  Using version: {latest}")

    # Step 2: Get available resolutions
    print("\nFetching resolutions...")
    resolutions = api_get(f"api/resoluciones?version={version_id}")
    print(f"  Available resolutions: {json.dumps(resolutions, indent=2, ensure_ascii=False)}")

    # Step 3: For each state, get file list and download
    for state_code, state_name in STATES.items():
        print(f"\n{'='*60}")
        print(f"Processing {state_name} (code {state_code})...")

        # Get file listings for this state at 15m resolution (CEM state download)
        try:
            files = api_get(f"api/archivo?version={version_id}&opcion=15&clave={state_code}")
            if not files:
                print(f"  No files found for {state_name}")
                continue

            print(f"  Found {len(files)} files:")
            for f_info in files:
                print(f"    - {f_info.get('titulo_archivo', f_info.get('nom_archivo', 'unknown'))}")
                print(f"      URL: {f_info.get('url_archivo', 'N/A')}")
                print(f"      File: {f_info.get('nom_archivo', 'N/A')}")
                print(f"      Size: {f_info.get('size_archivo', 'N/A')}")
                print(f"      Type: {f_info.get('tipo_archivo', 'N/A')}")

                # Build download URL
                url_base = f_info.get("url_archivo", "")
                nom = f_info.get("nom_archivo", "")

                if not url_base or not nom:
                    print("      SKIP: missing URL or filename")
                    continue

                if "DownloadFile.do" in url_base:
                    # State-level CEM download
                    dl_url = url_base.replace(
                        "DownloadFile.do",
                        f"DownloadFile.do?file={nom}&res=15&entidad={state_name.replace('_', ' ')}"
                    )
                else:
                    # Direct file download via proxy
                    dl_url = f"{BASE}/api/download?url={urllib.parse.quote(url_base + nom)}"

                dest = os.path.join(OUTDIR, f"{state_name}_{nom}")
                if os.path.exists(dest):
                    print(f"      Already exists: {dest}")
                    continue

                print(f"      Downloading: {dl_url}")
                try:
                    download_file(dl_url, dest)
                    print(f"      Saved: {dest} ({os.path.getsize(dest) // 1024}KB)")
                except Exception as e:
                    print(f"      DOWNLOAD FAILED: {e}")
                    if os.path.exists(dest):
                        os.remove(dest)

        except Exception as e:
            print(f"  ERROR fetching file list: {e}")

    # Also try to get the 10k tile index for future use
    print(f"\n{'='*60}")
    print("Fetching 1:10,000 tile formats...")
    try:
        fmt = api_get("getFormato10k.do")
        print(f"  10k formats: {json.dumps(fmt, indent=2, ensure_ascii=False)}")
    except Exception as e:
        print(f"  Could not fetch 10k formats: {e}")

    print("\nDone!")


if __name__ == "__main__":
    main()
