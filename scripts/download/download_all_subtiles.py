#!/usr/bin/env python3
"""
Download ALL 10k sub-tiles for the 50k sheets containing deep cenotes.
Each 50k sheet can have up to 32 sub-tiles (A1-A4, B1-B4, C1-C4, D1-D4, E1-E4, F1-F4, G1-G4, H1-H4).
"""
import urllib.request
import json
import os
import sys

OUTDIR = "data/inegi_5m"
os.makedirs(OUTDIR, exist_ok=True)

HEADERS = {"User-Agent": "Mozilla/5.0"}
API_URL = "https://www.inegi.org.mx/app/geo2/elevacionesmex/getF10KDescarga.do"

# 50k tiles containing deep cenotes
TILES_50K = ["F16C44", "F16C47", "F16C52", "F16C54", "F16C55",
             "F16C61", "F16C62", "F16C63", "F16C66", "F16C67",
             "F16C69", "F16C72", "F16C83"]

# Sub-tile suffixes: A-H rows, 1-4 columns
SUBTILES = [f"{letter}{num}" for letter in "ABCDEFGH" for num in "1234"]


def query_tile(cve):
    data = f"res=5&mod=T&cve={cve}".encode()
    req = urllib.request.Request(API_URL, data=data, headers={
        **HEADERS, "Content-Type": "application/x-www-form-urlencoded"
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode("utf-8-sig"))
            return result[0] if result else None
    except:
        return None


def download_file(url, dest):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=120) as resp:
        with open(dest, "wb") as f:
            while True:
                chunk = resp.read(8192)
                if not chunk:
                    break
                f.write(chunk)
        return os.path.getsize(dest)


def main():
    total_available = 0
    total_downloaded = 0
    total_skipped = 0

    for tile50k in TILES_50K:
        print(f"\n=== {tile50k} ===")
        for sub in SUBTILES:
            cve = f"{tile50k}{sub}"
            dest = os.path.join(OUTDIR, f"{cve}_terrain_5m_b.zip")

            if os.path.exists(dest) and os.path.getsize(dest) > 1000:
                total_skipped += 1
                continue

            info = query_tile(cve)
            if not info:
                continue

            total_available += 1
            url = info["url_descarga"] + "_b.zip"

            try:
                size = download_file(url, dest)
                if size < 1000:
                    os.remove(dest)
                    print(f"  {cve}: error (too small)")
                    continue
                total_downloaded += 1
                print(f"  {cve}: {size // 1024}KB")
            except Exception as e:
                print(f"  {cve}: FAILED {e}")
                if os.path.exists(dest):
                    os.remove(dest)

    print(f"\nDone: {total_downloaded} new downloads, {total_skipped} already had, {total_available} available")


if __name__ == "__main__":
    main()
