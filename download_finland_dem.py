#!/usr/bin/env python3
"""
MikroilmastoCFD — Suomen korkeusmalli (KM10) lataus
=====================================================

Lataa MML:n 2 m korkeusmalli (KM2) koko Suomen alueelle,
skaalaa paikallisesti 10 m:iin ja tallentaa yhteen GeoTIFF-tiedostoon.

MML:n WCS ei tue palvelinpuolista skaalausta, joten lataus tapahtuu
natiivilla 2 m resoluutiolla pienissä paloissa (10 km × 10 km) ja
pienennetään paikallisesti 5× (2m → 10m).

Käyttö:
    python download_finland_dem.py
    python download_finland_dem.py --output ./finland_dem_10m.tif
    python download_finland_dem.py --tile-size 100  # 100 km × 100 km tiilet
    python download_finland_dem.py --resume          # jatka keskeytettyä latausta

Vaatimukset:
    - MML_API_KEY ympäristömuuttuja (ilmainen: https://www.maanmittauslaitos.fi/rajapinnat/api-avaimen-ohje)
    - rasterio, numpy, requests

Tuomas / Loopshore Oy
"""

import argparse
import json
import math
import os
import sys
import time
import tempfile
import shutil
from pathlib import Path

import numpy as np

# =============================================================================
# Suomen rajat ETRS-TM35FIN:ssä (EPSG:3067)
# =============================================================================
FINLAND_BOUNDS = {
    'E_min': 60_000,
    'E_max': 780_000,
    'N_min': 6_600_000,
    'N_max': 7_800_000,
}

MML_WCS_URL = ("https://avoin-karttakuva.maanmittauslaitos.fi/"
               "ortokuvat-ja-korkeusmallit/wcs/v2")

COVERAGE_IDS = [
    'korkeusmalli_10m',
    'korkeusmalli__korkeusmalli_10m',
    'korkeusmalli_2m',
    'korkeusmalli__korkeusmalli_2m',
]

DEFAULT_OUTPUT = Path(__file__).parent / 'finland_dem_10m.tif'
DEFAULT_TILE_SIZE_KM = 50
TARGET_RESOLUTION = 10.0
MAX_WCS_SPAN_M = 10_000  # 10 km per WCS-pyyntö (2m: 5000×5000 = 25M px)


def get_api_key():
    key = os.environ.get('MML_API_KEY')
    if not key:
        config_path = Path.home() / '.mikrocfd' / 'config.json'
        if config_path.exists():
            try:
                with open(config_path) as f:
                    key = json.load(f).get('mml_api_key')
            except Exception:
                pass
    return key


def discover_coverage_id(api_key):
    import requests
    print("  Haetaan saatavilla olevat CoverageId:t...")
    try:
        resp = requests.get(MML_WCS_URL, params={
            'service': 'WCS', 'version': '2.0.1',
            'request': 'GetCapabilities', 'api-key': api_key,
        }, timeout=30)
        if resp.status_code == 200:
            import re
            ids = re.findall(r'<(?:wcs:)?CoverageId>([^<]+)', resp.text)
            km_ids = [i for i in ids if 'korkeus' in i.lower() or 'dem' in i.lower()]
            if km_ids:
                print(f"  ℹ Korkeusmallit: {km_ids}")
                return km_ids
    except Exception as e:
        print(f"  ⚠ GetCapabilities: {e}")
    return []


# =============================================================================
# WCS: yksittäinen pyyntö (natiivi resoluutio, ei skaalausta)
# =============================================================================

def _wcs_request(api_key, coverage_id, e_min, n_min, e_max, n_max, timeout=120):
    """Yksittäinen WCS GetCoverage. Palauttaa (data, transform, crs) tai None."""
    import requests
    import rasterio

    params = {
        'service': 'WCS', 'version': '2.0.1', 'request': 'GetCoverage',
        'CoverageId': coverage_id,
        'subset': [f'E({e_min:.0f},{e_max:.0f})', f'N({n_min:.0f},{n_max:.0f})'],
        'format': 'image/tiff',
        'api-key': api_key,
    }

    try:
        resp = requests.get(MML_WCS_URL, params=params, timeout=timeout)
    except Exception:
        return None

    if resp.status_code != 200:
        return None

    content = resp.content
    if content[:4] not in (b'II*\x00', b'MM\x00*'):
        return None

    with tempfile.NamedTemporaryFile(suffix='.tif', delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        with rasterio.open(tmp_path) as src:
            data = src.read(1).astype(np.float32)
            transform = src.transform
            crs = src.crs
            if src.nodata is not None:
                data[data == src.nodata] = np.nan
            if np.count_nonzero(~np.isnan(data)) == 0:
                return None
            return data, transform, crs
    finally:
        os.unlink(tmp_path)


# =============================================================================
# Iso tiili → alitiilet + paikallinen skaalaus
# =============================================================================

def fetch_tile(api_key, coverage_id, e_min, n_min, e_max, n_max,
               target_resolution=TARGET_RESOLUTION,
               max_wcs_span_m=MAX_WCS_SPAN_M,
               timeout=120, verbose=False):
    """
    Lataa DEM-tiili kohderesoluutiolla.

    Jakaa ison tiilen automaattisesti pienempiin WCS-pyyntöihin
    ja skaalaa natiividatan paikallisesti (joka N. pikseli).
    """
    import rasterio
    from rasterio.transform import Affine

    tile_w = e_max - e_min
    tile_h = n_max - n_min
    out_nx = int(round(tile_w / target_resolution))
    out_ny = int(round(tile_h / target_resolution))
    if out_nx == 0 or out_ny == 0:
        return None

    # Jako alitiileihin
    n_sub_e = max(1, math.ceil(tile_w / max_wcs_span_m))
    n_sub_n = max(1, math.ceil(tile_h / max_wcs_span_m))
    sub_w = tile_w / n_sub_e
    sub_h = tile_h / n_sub_n
    total_subs = n_sub_e * n_sub_n

    if verbose and total_subs > 1:
        print(f"[{n_sub_e}×{n_sub_n} sub] ", end='', flush=True)

    output = np.full((out_ny, out_nx), np.nan, dtype=np.float32)
    any_data = False
    crs_out = None
    subs_ok = 0

    for si in range(n_sub_e):
        for sj in range(n_sub_n):
            se_min = e_min + si * sub_w
            sn_min = n_min + sj * sub_h
            se_max = min(se_min + sub_w, e_max)
            sn_max = min(sn_min + sub_h, n_max)

            result = _wcs_request(api_key, coverage_id,
                                  se_min, sn_min, se_max, sn_max, timeout)
            if result is None:
                continue

            sub_data, sub_tf, crs_out = result
            any_data = True
            subs_ok += 1

            native_res = abs(sub_tf.a)
            factor = max(1, int(round(target_resolution / native_res)))

            # Paikallinen skaalaus
            sub_ds = sub_data[::factor, ::factor]

            # Sijoitus tulostaulukkoon (rivi 0 = pohjoinen)
            out_col = int(round((se_min - e_min) / target_resolution))
            out_row = int(round((n_max - sn_max) / target_resolution))
            ds_h, ds_w = sub_ds.shape

            r0 = max(0, out_row)
            c0 = max(0, out_col)
            r1 = min(r0 + ds_h, out_ny)
            c1 = min(c0 + ds_w, out_nx)
            ch = r1 - r0
            cw = c1 - c0

            if ch > 0 and cw > 0:
                output[r0:r1, c0:c1] = sub_ds[:ch, :cw]

    if not any_data:
        return None

    if verbose and total_subs > 1:
        print(f"({subs_ok}/{total_subs} osui) ", end='', flush=True)

    out_transform = Affine(target_resolution, 0, e_min,
                           0, -target_resolution, n_max)
    return output, out_transform, crs_out


# =============================================================================
# Tiiliruudukko
# =============================================================================

def generate_tile_grid(tile_size_km):
    tile_size_m = tile_size_km * 1000
    tiles = []
    e = FINLAND_BOUNDS['E_min']
    while e < FINLAND_BOUNDS['E_max']:
        n = FINLAND_BOUNDS['N_min']
        while n < FINLAND_BOUNDS['N_max']:
            tiles.append((e, n,
                          min(e + tile_size_m, FINLAND_BOUNDS['E_max']),
                          min(n + tile_size_m, FINLAND_BOUNDS['N_max']),
                          f"E{e//1000:04d}_N{n//1000:05d}"))
            n += tile_size_m
        e += tile_size_m
    return tiles


def find_max_wcs_span(api_key, coverage_id, test_center=(383_000, 6_672_000)):
    """Testaa kasvavia WCS-pyyntökokoja."""
    cx, cy = test_center
    for span_km in [20, 10, 5, 2]:
        span_m = span_km * 1000
        h = span_m // 2
        try:
            result = _wcs_request(api_key, coverage_id,
                                  cx - h, cy - h, cx + h, cy + h, timeout=60)
            if result is not None:
                d, tf, _ = result
                print(f"  ✓ Max WCS: {span_km} km × {span_km} km "
                      f"({d.shape[1]}×{d.shape[0]} px @ {abs(tf.a):.0f}m)")
                return span_m
        except Exception:
            continue
    print(f"  ⚠ Käytetään 2 km")
    return 2000


# =============================================================================
# Lataus
# =============================================================================

def download_tiles(api_key, coverage_id, tiles, tile_dir,
                   target_resolution=TARGET_RESOLUTION,
                   max_wcs_span_m=MAX_WCS_SPAN_M, resume=True):
    import rasterio

    tile_dir = Path(tile_dir)
    tile_dir.mkdir(parents=True, exist_ok=True)

    total = len(tiles)
    downloaded = []
    skipped_existing = 0
    skipped_empty = 0
    failed = 0

    status_path = tile_dir / '_download_status.json'
    empty_tiles = set()
    if resume and status_path.exists():
        try:
            with open(status_path) as f:
                empty_tiles = set(json.load(f).get('empty_tiles', []))
        except Exception:
            pass

    subs_per_tile = math.ceil(50_000 / max_wcs_span_m) ** 2
    print(f"\n{'='*60}")
    print(f"  Ladataan {total} tiiltä ({target_resolution:.0f} m resoluutio)")
    print(f"  WCS-alitiiliä per tiili: {subs_per_tile}")
    print(f"  Hakemisto: {tile_dir}")
    print(f"{'='*60}\n")

    t_start = time.time()
    bytes_total = 0
    tiles_with_data = 0

    for i, (e_min, n_min, e_max, n_max, tile_name) in enumerate(tiles, 1):
        tile_path = tile_dir / f"{tile_name}.tif"

        if resume and tile_path.exists() and tile_path.stat().st_size > 100:
            downloaded.append(tile_path)
            skipped_existing += 1
            continue

        if resume and tile_name in empty_tiles:
            skipped_empty += 1
            continue

        # Aika-arvio
        elapsed = time.time() - t_start
        active = i - skipped_existing - skipped_empty
        if active > 2 and tiles_with_data > 0:
            avg = elapsed / active
            remaining = (total - i) * avg
            eta_str = f"  [~{remaining/60:.0f} min]"
        else:
            eta_str = ""

        print(f"  [{i:3d}/{total}] {tile_name}  "
              f"E={e_min/1000:.0f}–{e_max/1000:.0f}  "
              f"N={n_min/1000:.0f}–{n_max/1000:.0f}  ", end='', flush=True)

        try:
            result = fetch_tile(api_key, coverage_id, e_min, n_min, e_max, n_max,
                               target_resolution=target_resolution,
                               max_wcs_span_m=max_wcs_span_m, verbose=True)

            if result is None:
                print("⬜ tyhjä")
                empty_tiles.add(tile_name)
                skipped_empty += 1
            else:
                data, transform, crs = result
                ny, nx = data.shape
                tiles_with_data += 1

                with rasterio.open(
                    tile_path, 'w', driver='GTiff',
                    height=ny, width=nx, count=1, dtype='float32',
                    crs=crs, transform=transform,
                    compress='lzw', predictor=3, tiled=True,
                    blockxsize=256, blockysize=256, nodata=np.nan,
                ) as dst:
                    dst.write(data, 1)

                file_size = tile_path.stat().st_size
                bytes_total += file_size
                valid_pct = np.count_nonzero(~np.isnan(data)) / data.size * 100

                print(f"✓ {nx}×{ny}  {file_size/1024:.0f} KB  "
                      f"({valid_pct:.0f}% maata){eta_str}")
                downloaded.append(tile_path)

        except Exception as e:
            print(f"✗ {e}")
            failed += 1

        if i % 5 == 0:
            with open(status_path, 'w') as f:
                json.dump({'empty_tiles': list(empty_tiles),
                           'coverage_id': coverage_id,
                           'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')}, f)

    with open(status_path, 'w') as f:
        json.dump({'empty_tiles': list(empty_tiles), 'completed': True,
                   'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')}, f)

    elapsed_total = time.time() - t_start
    print(f"\n{'='*60}")
    print(f"  Valmis: {elapsed_total/60:.1f} min")
    print(f"  Ladattu:  {len(downloaded)} tiiltä ({bytes_total/1024/1024:.1f} MB)")
    print(f"  Ohitettu: {skipped_existing} (ladattu) + {skipped_empty} (tyhjä)")
    print(f"  Virheet:  {failed}")
    print(f"{'='*60}\n")
    return downloaded


# =============================================================================
# Yhdistäminen
# =============================================================================

def merge_tiles(tile_paths, output_path, cleanup_tiles=False):
    import rasterio
    from rasterio.merge import merge

    if not tile_paths:
        print("  ⚠ Ei tiiliä!")
        return False

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"  Yhdistetään {len(tile_paths)} tiiltä → {output_path}")

    t0 = time.time()
    datasets = []
    for tp in sorted(tile_paths):
        try:
            datasets.append(rasterio.open(tp))
        except Exception as e:
            print(f"  ⚠ {tp.name}: {e}")

    if not datasets:
        return False

    mosaic, out_transform = merge(datasets, nodata=np.nan)
    meta = datasets[0].meta.copy()
    meta.update({
        'driver': 'GTiff', 'height': mosaic.shape[1], 'width': mosaic.shape[2],
        'transform': out_transform, 'count': 1, 'dtype': 'float32',
        'nodata': np.nan, 'compress': 'lzw', 'predictor': 3,
        'tiled': True, 'blockxsize': 512, 'blockysize': 512,
    })

    tmp = output_path.with_suffix('.tmp.tif')
    with rasterio.open(tmp, 'w', **meta) as dst:
        dst.write(mosaic[0], 1)
        dst.update_tags(
            DESCRIPTION='MML korkeusmalli Suomi 10m (2m → 10m lokaali skaalaus)',
            SOURCE='Maanmittauslaitos WCS', CRS='EPSG:3067', HEIGHT_SYSTEM='N2000',
            GENERATOR='MikroilmastoCFD', DOWNLOAD_DATE=time.strftime('%Y-%m-%d'))

    for ds in datasets:
        ds.close()
    shutil.move(str(tmp), str(output_path))

    fs = output_path.stat().st_size
    vp = np.count_nonzero(~np.isnan(mosaic[0]))
    tp = mosaic[0].size
    print(f"  ✓ {time.time()-t0:.0f}s | {fs/1024/1024:.0f} MB | "
          f"{mosaic.shape[2]:,}×{mosaic.shape[1]:,} px | "
          f"{vp/tp*100:.0f}% maata | "
          f"h: {np.nanmin(mosaic[0]):.1f}–{np.nanmax(mosaic[0]):.1f} m")

    if cleanup_tiles:
        for p in tile_paths:
            try: p.unlink()
            except: pass

    return True


def add_overviews(output_path):
    import rasterio
    from rasterio.enums import Resampling
    print(f"  Lisätään overviewt...")
    with rasterio.open(output_path, 'r+') as dst:
        dst.build_overviews([2, 4, 8, 16, 32], Resampling.average)
        dst.update_tags(ns='rio_overview', resampling='average')
    print(f"  ✓ {output_path.stat().st_size/1024/1024:.0f} MB")


def verify_output(output_path):
    import rasterio
    print(f"\n  Tarkistus...")
    with rasterio.open(output_path) as src:
        print(f"    {src.width:,}×{src.height:,} @ "
              f"{abs(src.transform.a):.0f}m | {src.crs}")
        from rasterio.windows import from_bounds
        try:
            w = from_bounds(380_000, 6_670_000, 385_000, 6_675_000, src.transform)
            d = src.read(1, window=w)
            v = np.count_nonzero(~np.isnan(d))
            if v > 0:
                print(f"    Helsinki: {v} px, h={np.nanmean(d):.1f}m ✓")
        except: pass
    return True


# =============================================================================
# terrain_analysis.py -integraatio
# =============================================================================

def load_dem_for_bounds(dem_path, bounds_etrs):
    """Lataa DEM-data simulointialueen rajoilla (windowed read)."""
    import rasterio
    from rasterio.windows import from_bounds

    dem_path = Path(dem_path)
    if not dem_path.exists():
        return None, None, None

    xmin, ymin, xmax, ymax = bounds_etrs
    with rasterio.open(dem_path) as src:
        window = from_bounds(xmin, ymin, xmax, ymax, src.transform)
        window = window.round_offsets().round_lengths()
        data = src.read(1, window=window).astype(float)
        wt = src.window_transform(window)
        ny, nx = data.shape
        x_coords = np.array([wt.c + i * wt.a for i in range(nx)])
        y_coords = np.array([wt.f + j * wt.e for j in range(ny)])
        if src.nodata is not None:
            data[np.isclose(data, src.nodata)] = np.nan
        data[data <= -9990] = np.nan
        if len(y_coords) > 1 and y_coords[0] > y_coords[-1]:
            y_coords = y_coords[::-1]
            data = data[::-1, :]

    if np.count_nonzero(~np.isnan(data)) == 0:
        return None, None, None

    print(f"  ✓ DEM cache: {nx}×{ny}, h={np.nanmin(data):.1f}–{np.nanmax(data):.1f}m")
    return data, x_coords, y_coords


def find_dem_file():
    for p in [
        Path(__file__).parent / 'finland_dem_10m.tif',
        Path(__file__).parent / 'data' / 'finland_dem_10m.tif',
        Path.home() / '.mikrocfd' / 'dem' / 'finland_dem_10m.tif',
        Path('finland_dem_10m.tif'),
    ]:
        if p.exists():
            return p
    return None


# =============================================================================
# Main
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='Lataa MML korkeusmalli koko Suomelle (10 m)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Toiminta: Lataa 2m datan 10km×10km paloissa, skaalaa paikallisesti → 10m.
API-avain: export MML_API_KEY=xxxx (ilmainen: maanmittauslaitos.fi)
""")
    parser.add_argument('-o', '--output', type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument('--tile-size', type=int, default=DEFAULT_TILE_SIZE_KM)
    parser.add_argument('--tile-dir', type=Path, default=None)
    parser.add_argument('--resume', action='store_true', default=True)
    parser.add_argument('--no-resume', action='store_true')
    parser.add_argument('--keep-tiles', action='store_true')
    parser.add_argument('--no-overviews', action='store_true')
    parser.add_argument('--tiles-only', action='store_true')
    parser.add_argument('--merge-only', action='store_true')
    parser.add_argument('--max-wcs-span', type=int, default=0,
                       help='Max WCS-pyyntökoko km (0=auto)')
    args = parser.parse_args()

    if args.no_resume:
        args.resume = False

    api_key = get_api_key()
    if not api_key:
        print("MML_API_KEY puuttuu! Aseta: export MML_API_KEY=xxxx")
        print("Ilmainen: https://www.maanmittauslaitos.fi/rajapinnat/api-avaimen-ohje")
        sys.exit(1)

    tile_dir = args.tile_dir or (args.output.parent / 'tiles')

    print("╔══════════════════════════════════════════════════════╗")
    print("║  MikroilmastoCFD — Suomen korkeusmalli              ║")
    print("║  WCS 2m → paikallinen skaalaus → 10m               ║")
    print("╚══════════════════════════════════════════════════════╝")
    print(f"  Kohde:  {TARGET_RESOLUTION:.0f} m | Tiilit: {args.tile_size} km")
    print(f"  Tulos:  {args.output}")

    coverage_id = None
    max_wcs_span_m = MAX_WCS_SPAN_M

    if not args.merge_only:
        import requests
        print(f"\n  Testataan WCS...")

        for cov_id in COVERAGE_IDS:
            try:
                r = _wcs_request(api_key, cov_id,
                                 383_000, 6_672_000, 384_000, 6_673_000, 30)
                if r:
                    d, tf, _ = r
                    nr = abs(tf.a)
                    print(f"  ✓ '{cov_id}' @ {nr:.0f}m ({d.shape[1]}×{d.shape[0]}, "
                          f"h={np.nanmean(d):.1f}m)")
                    coverage_id = cov_id
                    break
            except Exception as e:
                print(f"  ✗ '{cov_id}': {e}")

        if not coverage_id:
            for cov_id in discover_coverage_id(api_key):
                if cov_id in COVERAGE_IDS:
                    continue
                try:
                    r = _wcs_request(api_key, cov_id,
                                     383_000, 6_672_000, 384_000, 6_673_000, 30)
                    if r:
                        coverage_id = cov_id
                        print(f"  ✓ '{cov_id}'")
                        break
                except: pass

        if not coverage_id:
            print("  ✗ Ei toimivaa CoverageId:tä!")
            sys.exit(1)

        # Max WCS-pyyntökoko
        if args.max_wcs_span > 0:
            max_wcs_span_m = args.max_wcs_span * 1000
        else:
            print(f"\n  Tunnistetaan max WCS-pyyntökoko...")
            max_wcs_span_m = find_max_wcs_span(api_key, coverage_id)

        # Pipeline-testi
        print(f"\n  Pipeline-testi (10×10 km)...")
        tr = fetch_tile(api_key, coverage_id,
                        380_000, 6_670_000, 390_000, 6_680_000,
                        target_resolution=TARGET_RESOLUTION,
                        max_wcs_span_m=max_wcs_span_m, verbose=True)
        if tr:
            d, tf, _ = tr
            print(f"\n  ✓ {d.shape[1]}×{d.shape[0]} @ {abs(tf.a):.0f}m, "
                  f"h={np.nanmean(d):.1f}m")
        else:
            print(f"\n  ✗ Pipeline-testi epäonnistui!")
            sys.exit(1)

    # Tiiliruudukko
    tiles = generate_tile_grid(args.tile_size)
    subs = math.ceil(args.tile_size * 1000 / max_wcs_span_m) ** 2
    land = int(len(tiles) * 0.4)
    reqs = land * subs
    est_h = reqs * 3 / 3600

    print(f"\n  Tiiliä: {len(tiles)} | Maatiiliä: ~{land} | "
          f"WCS-pyyntöjä: ~{reqs} | Aika: ~{est_h:.1f}h")

    if not args.merge_only:
        downloaded = download_tiles(api_key, coverage_id, tiles, tile_dir,
                                    target_resolution=TARGET_RESOLUTION,
                                    max_wcs_span_m=max_wcs_span_m,
                                    resume=args.resume)
    else:
        downloaded = sorted(tile_dir.glob("E*_N*.tif"))
        print(f"  {len(downloaded)} tiiltä löydetty")

    if not downloaded:
        print("  ✗ Ei tiiliä!")
        sys.exit(1)

    if not args.tiles_only:
        success = merge_tiles(downloaded, args.output,
                              cleanup_tiles=not args.keep_tiles)
        if success and not args.no_overviews:
            add_overviews(args.output)
        if success:
            verify_output(args.output)
            print(f"\n  ✓ VALMIS: {args.output} "
                  f"({args.output.stat().st_size/1024/1024:.0f} MB)")


if __name__ == '__main__':
    main()
