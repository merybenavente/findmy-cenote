#!/usr/bin/env python3
"""
Download 5m terrain DEM tiles from INEGI for tiles containing cenotes.
Queries getF10KDescarga.do API, then downloads BIL format files.
"""
import urllib.request
import json
import os
import sys

OUTDIR = "data/inegi_5m"
os.makedirs(OUTDIR, exist_ok=True)

HEADERS = {"User-Agent": "Mozilla/5.0"}

# All 10k tiles that contain cenotes from our analysis
TILES = [
    "F16C52A1", "F16C52A2", "F16C52B2", "F16C52E4", "F16C52F4",
    "F16C54D1", "F16C54D3", "F16C54E1", "F16C54F4",
    "F16C55D4", "F16C55E1", "F16C55E3",
    "F16C61A2", "F16C61A4", "F16C61B1", "F16C61B2", "F16C61B3", "F16C61B4",
    "F16C62F2", "F16C62F3", "F16C62F4",
    "F16C63D1", "F16C63D2", "F16C63D3", "F16C63D4",
    "F16C63F1", "F16C63F2", "F16C63F3", "F16C63F4",
    "F16C66A3", "F16C66A4", "F16C66B2", "F16C66B3", "F16C66B4",
    "F16C66C1", "F16C66C2", "F16C66C3", "F16C66C4",
    "F16C66D1", "F16C66D2", "F16C66D3", "F16C66D4",
    "F16C66E1", "F16C66E2", "F16C66F1", "F16C66F4",
    "F16C72F3", "F16C72F4",
    "F16C83A1", "F16C83A4",
    # Also add neighbor tiles of deep cenotes and tiles from 50k sheets
    # with deep cenotes that weren't matched above
    "F16C44A1", "F16C44A2", "F16C44A3", "F16C44A4",
    "F16C44B1", "F16C44B2", "F16C44B3", "F16C44B4",
    "F16C47A1", "F16C47A2", "F16C47A3", "F16C47A4",
    "F16C47B1", "F16C47B2", "F16C47B3", "F16C47B4",
    "F16C69A1", "F16C69A2", "F16C69A3", "F16C69A4",
    "F16C69B1", "F16C69B2", "F16C69B3", "F16C69B4",
]

API_URL = "https://www.inegi.org.mx/app/geo2/elevacionesmex/getF10KDescarga.do"


def query_tile(cve):
    """Query API for terrain 5m data for a given 10k tile."""
    data = f"res=5&mod=T&cve={cve}".encode()
    req = urllib.request.Request(API_URL, data=data, headers={
        **HEADERS, "Content-Type": "application/x-www-form-urlencoded"
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode("utf-8-sig"))
            return result[0] if result else None
    except Exception as e:
        print(f"  API error for {cve}: {e}", file=sys.stderr)
        return None


def download_file(url, dest):
    """Download with progress."""
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=120) as resp:
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
        return downloaded


def main():
    available = []
    not_available = []

    print(f"Querying {len(TILES)} tiles...")
    for i, cve in enumerate(TILES):
        info = query_tile(cve)
        if info:
            available.append((cve, info))
            print(f"  [{i+1}/{len(TILES)}] {cve}: AVAILABLE")
        else:
            not_available.append(cve)
            print(f"  [{i+1}/{len(TILES)}] {cve}: no data")

    print(f"\n{len(available)} tiles available, {len(not_available)} not available")
    print(f"Not available: {not_available}")

    # Download BIL format (smallest, ~3MB each)
    downloaded = 0
    for cve, info in available:
        url_base = info["url_descarga"]
        # Parse archivo field for BIL size: "|_b.zip,4.27 MB|_as.zip,8.58 MB|..."
        bil_suffix = "_b.zip"
        dl_url = url_base + bil_suffix
        dest = os.path.join(OUTDIR, f"{cve}_terrain_5m_b.zip")

        if os.path.exists(dest):
            print(f"  {cve}: already exists, skipping")
            downloaded += 1
            continue

        print(f"  Downloading {cve}...", end=" ", flush=True)
        try:
            size = download_file(dl_url, dest)
            print(f"{size // 1024}KB")
            downloaded += 1
        except Exception as e:
            print(f"FAILED: {e}")
            if os.path.exists(dest):
                os.remove(dest)

    print(f"\nDone! Downloaded {downloaded}/{len(available)} tiles to {OUTDIR}/")


if __name__ == "__main__":
    main()
