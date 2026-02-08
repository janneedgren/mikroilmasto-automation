#!/usr/bin/env python3
"""
MikroilmastoCFD — Taso 1: Maastokorkeuden analyysi
====================================================

Hakee MML KM2 korkeusaineiston simulointialueelle,
laskee korkeusprofiilit tuulensuunnittain ja analysoi
kasvillisuuden h_eff-korjauksen sekä vesialueiden vaikutuksen.

Käyttö:
    python3 terrain_analysis.py <geometry.json>
    python3 terrain_analysis.py  # demo kaikilla esimerkeillä

Tuomas / Loopshore Oy
"""

import json
import math
import os
import sys
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.gridspec import GridSpec
from matplotlib.colors import LightSource
from pyproj import Transformer

# ETRS-TM35FIN (EPSG:3067) ↔ WGS84 (EPSG:4326)
TRANSFORMER_TO_ETRS = Transformer.from_crs("EPSG:4326", "EPSG:3067", always_xy=True)
TRANSFORMER_TO_WGS = Transformer.from_crs("EPSG:3067", "EPSG:4326", always_xy=True)


# =============================================================================
# 1. GEOMETRIA-JSON:N LUKEMINEN
# =============================================================================

class SimulationGeometry:
    """Jäsentää MikroilmastoCFD:n geometria-JSON:n."""
    
    def __init__(self, json_path):
        with open(json_path) as f:
            self.data = json.load(f)
        
        self.name = self.data.get('name', os.path.basename(json_path))
        self.meta = self.data.get('metadata', {})
        self.domain = self.data['domain']
        
        # Keskipiste
        self.center_lat = (self.data.get('center_lat') or 
                           self.meta.get('center_lat'))
        self.center_lon = (self.data.get('center_lon') or 
                           self.meta.get('center_lon'))
        
        # ETRS-TM35FIN offset (uusi formaatti)
        self.offset_x = self.meta.get('domain_offset_x')
        self.offset_y = self.meta.get('domain_offset_y')
        
        # Jos ei offsetia → laske lat/lon:sta
        if self.offset_x is None or self.offset_y is None:
            cx_etrs, cy_etrs = TRANSFORMER_TO_ETRS.transform(
                self.center_lon, self.center_lat)
            self.offset_x = cx_etrs - self.domain['width'] / 2
            self.offset_y = cy_etrs - self.domain['height'] / 2
        
        # Jäsennä esteet
        self._parse_obstacles()
        self._parse_zones()
    
    def _parse_obstacles(self):
        """Lajittele esteet tyypin mukaan."""
        self.buildings = []
        self.vegetation = []
        self.water_areas = []
        
        for obs in self.data.get('obstacles', []):
            otype = obs.get('type', '')
            if otype == 'polygon_building':
                self.buildings.append(obs)
            elif otype in ('tree_zone', 'vegetation_zone', 'forest_zone'):
                self.vegetation.append(obs)
            elif 'water' in otype:
                self.water_areas.append(obs)
    
    def _parse_zones(self):
        """Jäsennä muokattavat alueet (tonttirajat)."""
        self.editable_zones = self.data.get('editable_zones', [])
    
    def local_to_etrs(self, x_local, y_local):
        """Muunna simulointikoordinaatit ETRS-TM35FIN:iin."""
        return (x_local + self.offset_x, 
                y_local + self.offset_y)
    
    def etrs_to_local(self, x_etrs, y_etrs):
        """Muunna ETRS-TM35FIN simulointikoordinaateiksi."""
        return (x_etrs - self.offset_x,
                y_etrs - self.offset_y)
    
    @property
    def center_etrs(self):
        """Simulointialueen keskipiste ETRS-TM35FIN:ssä."""
        cx = self.domain['width'] / 2
        cy = self.domain['height'] / 2
        return self.local_to_etrs(cx, cy)
    
    @property
    def domain_bounds_etrs(self):
        """Simulointialueen rajat ETRS-TM35FIN:ssä (xmin, ymin, xmax, ymax)."""
        xmin, ymin = self.local_to_etrs(0, 0)
        xmax, ymax = self.local_to_etrs(self.domain['width'], 
                                         self.domain['height'])
        return (xmin, ymin, xmax, ymax)
    
    @property
    def extended_bounds_etrs(self):
        """Laajennetut rajat (2x) korkeusprofiileille."""
        xmin, ymin, xmax, ymax = self.domain_bounds_etrs
        w = xmax - xmin
        h = ymax - ymin
        margin = max(w, h) * 0.5  # 50% marginaali profiileille
        return (xmin - margin, ymin - margin,
                xmax + margin, ymax + margin)
    
    def find_target_building(self):
        """Etsi kohderakennus (lähinnä keskipistettä)."""
        cx = self.domain['width'] / 2
        cy = self.domain['height'] / 2
        
        best = None
        best_dist = float('inf')
        
        for b in self.buildings:
            verts = b['vertices']
            bx = sum(v[0] for v in verts) / len(verts)
            by = sum(v[1] for v in verts) / len(verts)
            dist = math.sqrt((bx - cx)**2 + (by - cy)**2)
            if dist < best_dist:
                best_dist = dist
                best = b
        
        if best:
            verts = best['vertices']
            best['_center_local'] = (
                sum(v[0] for v in verts) / len(verts),
                sum(v[1] for v in verts) / len(verts)
            )
            best['_center_etrs'] = self.local_to_etrs(*best['_center_local'])
        
        return best
    
    def get_vegetation_centers_etrs(self):
        """Kasvillisuusalueiden keskipisteet ETRS-koordinaateissa."""
        results = []
        for veg in self.vegetation:
            verts = veg['vertices']
            cx = sum(v[0] for v in verts) / len(verts)
            cy = sum(v[1] for v in verts) / len(verts)
            ex, ey = self.local_to_etrs(cx, cy)
            results.append({
                'name': veg.get('name', ''),
                'type': veg.get('vegetation_type', 'unknown'),
                'height': veg.get('height', 0),
                'LAI': veg.get('LAI_2D', veg.get('LAI', 0)),
                'local_center': (cx, cy),
                'etrs_center': (ex, ey),
            })
        return results
    
    def get_water_polygons_local(self):
        """Vesialueiden polygonit lokaalissa koordinaatistossa."""
        results = []
        for w in self.water_areas:
            verts = np.array(w['vertices'])
            results.append({
                'name': w.get('name', 'Vesialue'),
                'type': w.get('water_type', 'water'),
                'vertices': verts,
            })
        return results
    
    def summary(self):
        """Tulosta yhteenveto geometriasta."""
        print(f"\n{'='*60}")
        print(f"  {self.name}")
        print(f"{'='*60}")
        print(f"  Keskipiste:  {self.center_lat:.6f}°N, {self.center_lon:.6f}°E")
        ce = self.center_etrs
        print(f"  ETRS-TM35:   E {ce[0]:.0f}, N {ce[1]:.0f}")
        print(f"  Domain:      {self.domain['width']:.0f} × {self.domain['height']:.0f} m")
        print(f"  Rakennukset: {len(self.buildings)}")
        print(f"  Kasvillisuus:{len(self.vegetation)}")
        print(f"  Vesialueet:  {len(self.water_areas)}")
        if self.water_areas:
            for w in self.water_areas:
                print(f"    - {w.get('name', '?')} ({w.get('water_type', '?')})")
        print(f"  Tontit:      {len(self.editable_zones)}")
        
        target = self.find_target_building()
        if target:
            tc = target['_center_local']
            print(f"  Kohde:       {target.get('id', '?')} "
                  f"({tc[0]:.0f}, {tc[1]:.0f}) h={target.get('height', '?')}m")


# =============================================================================
# 2. MML KM2 -KORKEUSAINEISTON HAKU
# =============================================================================

def fetch_mml_elevation_wcs(bounds_etrs, resolution=2.0):
    """
    Hae MML KM2 korkeusmalli WCS-rajapinnasta.
    
    API-avain luetaan automaattisesti ympäristömuuttujasta MML_API_KEY.
    
    Parameters
    ----------
    bounds_etrs : tuple
        (xmin, ymin, xmax, ymax) ETRS-TM35FIN koordinaateissa
    resolution : float
        Hilakoko metreinä (2.0 = KM2)
    
    Returns
    -------
    elevation : np.ndarray (ny, nx)
        Korkeus merenpinnasta [m]
    x_coords : np.ndarray
        ETRS itä-koordinaatit
    y_coords : np.ndarray
        ETRS pohjoinen-koordinaatit
    """
    import requests
    
    api_key = os.environ.get('MML_API_KEY')
    if not api_key:
        print("  [WARN] MML_API_KEY ympäristömuuttujaa ei löydy")
        return None, None, None
    
    xmin, ymin, xmax, ymax = bounds_etrs
    
    # MML WCS endpoint (api-key URL-polkuun, ei query-parametriksi)
    base_url = ("https://avoin-karttakuva.maanmittauslaitos.fi/"
                "ortokuvat-ja-korkeusmallit/wcs/v2")
    
    # Kokeile useita CoverageId-muotoja (MML:n dokumentaatio vaihtelee)
    coverage_ids = [
        'korkeusmalli_2m',
        'korkeusmalli__korkeusmalli_2m',
    ]
    
    for cov_id in coverage_ids:
        params = {
            'service': 'WCS',
            'version': '2.0.1',
            'request': 'GetCoverage',
            'CoverageId': cov_id,
            'subset': [f'E({xmin:.0f},{xmax:.0f})', 
                       f'N({ymin:.0f},{ymax:.0f})'],
            'format': 'image/tiff',
            'api-key': api_key,
        }
        
        try:
            resp = requests.get(base_url, params=params, timeout=60)
            
            # Tarkista HTTP-virhe
            if resp.status_code != 200:
                print(f"  [DEBUG] WCS HTTP {resp.status_code} (CoverageId={cov_id})")
                continue
            
            # Tarkista onko vastaus TIFF (magic bytes: II*\0 tai MM\0*)
            content = resp.content
            is_tiff = (content[:4] in (b'II*\x00', b'MM\x00*'))
            
            if not is_tiff:
                # API palautti XML-virheen tai muun ei-TIFF-vastauksen
                content_type = resp.headers.get('Content-Type', '?')
                preview = content[:500].decode('utf-8', errors='replace')
                print(f"  [DEBUG] WCS vastaus ei ole TIFF (CoverageId={cov_id})")
                print(f"          Content-Type: {content_type}")
                print(f"          Alku: {preview[:200]}...")
                
                # Jos XML sisältää ExceptionReport, näytä virheilmoitus
                if b'ExceptionReport' in content or b'Exception' in content:
                    import re
                    match = re.search(r'<[^>]*ExceptionText[^>]*>([^<]+)', 
                                      content.decode('utf-8', errors='replace'))
                    if match:
                        print(f"          WCS-virhe: {match.group(1).strip()}")
                continue
            
            # Tallenna väliaikaiseksi GeoTIFF:ksi ja lue
            import tempfile
            import rasterio
            
            with tempfile.NamedTemporaryFile(suffix='.tif', delete=False) as tmp:
                tmp.write(content)
                tmp_path = tmp.name
            
            with rasterio.open(tmp_path) as src:
                elevation = src.read(1).astype(float)
                transform = src.transform
                nodata = src.nodata
                ny, nx = elevation.shape
                
                x_coords = np.array([transform.c + i * transform.a 
                                     for i in range(nx)])
                y_coords = np.array([transform.f + j * transform.e 
                                     for j in range(ny)])
                
                # Käsittele nodata → NaN
                if nodata is not None:
                    elevation[elevation == nodata] = np.nan
                # MML:n korkeusmallissa 0.0 voi olla nodata (meri)
                # Helsinki: maanpinta > 0, joten 0.0 on turvallista tulkita NaN:iksi
                elevation[elevation <= 0.0] = np.nan
                
                # Varmista y_coords nousevassa järjestyksessä (searchsorted vaatii)
                if len(y_coords) > 1 and y_coords[0] > y_coords[-1]:
                    y_coords = y_coords[::-1]
                    elevation = elevation[::-1, :]
            
            os.unlink(tmp_path)
            
            print(f"  ✓ MML WCS: {nx}×{ny} pikseliä (CoverageId={cov_id})")
            return elevation, x_coords, y_coords
            
        except ImportError:
            print("  [WARN] rasterio ei asennettu, käytetään synteettistä dataa")
            return None, None, None
        except Exception as e:
            print(f"  [WARN] MML WCS -haku epäonnistui (CoverageId={cov_id}): {e}")
            continue
    
    # Kaikki CoverageId-vaihtoehdot kokeiltu — kokeile vielä DescribeCoverage
    print("  [DEBUG] Haetaan saatavilla olevat CoverageId:t...")
    try:
        desc_params = {
            'service': 'WCS',
            'version': '2.0.1',
            'request': 'GetCapabilities',
            'api-key': api_key,
        }
        resp = requests.get(base_url, params=desc_params, timeout=30)
        if resp.status_code == 200:
            import re
            ids = re.findall(r'<(?:wcs:)?CoverageId>([^<]+)', resp.text)
            if ids:
                # Suodata vain korkeusmalli-tyyppiset
                km_ids = [i for i in ids if 'korkeus' in i.lower() or 'dem' in i.lower() or 'km' in i.lower()]
                if km_ids:
                    print(f"          Korkeusmallit: {km_ids[:5]}")
                else:
                    print(f"          Kaikki CoverageId:t ({len(ids)}): {ids[:10]}")
    except Exception:
        pass
    
    print("  [WARN] MML WCS ei palauttanut kelvollista korkeusdataa")
    return None, None, None


def generate_synthetic_elevation(bounds_etrs, resolution=2.0, 
                                 base_height=50.0, terrain_type='gentle'):
    """
    Generoi synteettinen korkeusdata testausta varten.
    Käytetään kun MML-data ei ole saatavilla.
    
    terrain_type:
        'flat'    - tasainen (±1m)
        'gentle'  - loivat kumpuilut (±5m)
        'hilly'   - mäkinen (±15m)
        'coastal' - rantarinne (0→20m)
    """
    xmin, ymin, xmax, ymax = bounds_etrs
    nx = int((xmax - xmin) / resolution)
    ny = int((ymax - ymin) / resolution)
    
    x_coords = np.linspace(xmin, xmax, nx)
    y_coords = np.linspace(ymin, ymax, ny)
    
    X, Y = np.meshgrid(x_coords, y_coords)
    
    # Normalisoi 0-1 alueelle
    Xn = (X - xmin) / (xmax - xmin)
    Yn = (Y - ymin) / (ymax - ymin)
    
    if terrain_type == 'flat':
        Z = base_height + 0.5 * np.sin(Xn * 3) + 0.3 * np.cos(Yn * 4)
    
    elif terrain_type == 'gentle':
        Z = (base_height 
             + 4.0 * np.sin(Xn * 2 * np.pi * 0.8) * np.cos(Yn * 2 * np.pi * 0.6)
             + 2.5 * np.sin(Xn * 2 * np.pi * 1.5 + 0.5) 
             + 1.5 * np.cos(Yn * 2 * np.pi * 1.2 + 0.3))
    
    elif terrain_type == 'hilly':
        Z = (base_height
             + 12.0 * np.sin(Xn * 2 * np.pi * 0.5) * np.cos(Yn * 2 * np.pi * 0.4)
             + 6.0 * np.sin(Xn * 2 * np.pi * 1.2 + 1.0)
             + 4.0 * np.cos(Yn * 2 * np.pi * 0.8 + 0.5))
    
    elif terrain_type == 'coastal':
        # Meri vasemmalla (pieni x), rinne nousee oikealle
        Z = base_height * Xn**0.6
        Z += 2.0 * np.sin(Yn * 2 * np.pi * 1.5)  # Poikittaista vaihtelua
        # Meri: alle 1m → 0 (vedenpinta)
        Z = np.where(Z < 1.0, 0.0, Z)
    
    return Z, x_coords, y_coords


# =============================================================================
# 3. KORKEUSPROFIILIN LASKENTA
# =============================================================================

def compute_terrain_profile(elevation, x_coords, y_coords,
                            origin_x, origin_y, wind_dir_deg,
                            max_distance=None, step=2.0):
    """
    Laske korkeusprofiili kohderakennuksesta tuulen yläpuolelle JA alapuolelle.
    
    Parameters
    ----------
    origin_x, origin_y : float
        Kohderakennuksen ETRS-koordinaatit
    wind_dir_deg : float
        Meteorologinen tuulen suunta [°] (0=N, 90=E, 180=S, 270=W)
    max_distance : float
        Profiilin pituus [m] (oletus: puolet alue-dimensiosta)
    
    Returns
    -------
    dict:
        'upwind_dist': etäisyydet tuulen yläpuolelle [m]
        'upwind_z': korkeudet [m]
        'downwind_dist': etäisyydet tuulen alapuolelle [m]
        'downwind_z': korkeudet [m]
        'z_origin': kohteen korkeus [m]
    """
    if max_distance is None:
        extent_x = x_coords[-1] - x_coords[0]
        extent_y = y_coords[-1] - y_coords[0]
        max_distance = max(extent_x, extent_y) * 0.45
    
    # Tuulen suunta → yksikkövektori
    wind_rad = math.radians(wind_dir_deg)
    # Meteorologinen konventio: θ = suunta MISTÄ tuuli tulee
    # Upwind-suunta (kohti tuulen lähdettä):
    #   0° (N): upwind = pohjoiseen (+y) → sin(0)=0, cos(0)=1 ✓
    #   270° (W): upwind = länteen (-x) → sin(270)=-1, cos(270)=0 ✓
    dx_up = math.sin(wind_rad)
    dy_up = math.cos(wind_rad)
    
    def sample_profile(dx, dy, max_d):
        distances = np.arange(0, max_d, step)
        heights = np.full_like(distances, np.nan)
        
        for i, d in enumerate(distances):
            px = origin_x + d * dx
            py = origin_y + d * dy
            
            # Bilineaarinen interpolaatio
            ix = np.searchsorted(x_coords, px) - 1
            iy = np.searchsorted(y_coords, py) - 1
            
            if 0 <= ix < len(x_coords)-1 and 0 <= iy < len(y_coords)-1:
                fx = (px - x_coords[ix]) / (x_coords[ix+1] - x_coords[ix])
                fy = (py - y_coords[iy]) / (y_coords[iy+1] - y_coords[iy])
                h00 = elevation[iy, ix]
                h10 = elevation[iy, ix+1]
                h01 = elevation[iy+1, ix]
                h11 = elevation[iy+1, ix+1]
                vals = np.array([h00, h10, h01, h11])
                if np.all(np.isnan(vals)):
                    heights[i] = np.nan
                elif np.any(np.isnan(vals)):
                    # Keskiarvo valideista naapureista
                    heights[i] = np.nanmean(vals)
                else:
                    heights[i] = (h00*(1-fx)*(1-fy) + h10*fx*(1-fy) +
                                 h01*(1-fx)*fy + h11*fx*fy)
        
        # Täytä NaN:t viimeisellä tunnetulla
        mask = ~np.isnan(heights)
        if np.any(mask):
            last_valid = heights[mask][-1]
            heights[~mask] = last_valid
        
        return distances, heights
    
    upwind_dist, upwind_z = sample_profile(dx_up, dy_up, max_distance)
    downwind_dist, downwind_z = sample_profile(-dx_up, -dy_up, max_distance)
    
    z_origin = upwind_z[0] if len(upwind_z) > 0 else 0.0
    
    return {
        'direction': wind_dir_deg,
        'upwind_dist': upwind_dist,
        'upwind_z': upwind_z,
        'downwind_dist': downwind_dist,
        'downwind_z': downwind_z,
        'z_origin': z_origin,
    }


# =============================================================================
# 4. PROFIILIANALYYSI: SPEED-UP, FETCH, H_EFF
# =============================================================================

def _classify_terrain_form(profile, delta_z, L_slope):
    """
    Luokittele maastomuoto profiilin symmetrian perusteella.
    
    Eurocode EN 1991-1-4 (Annex A.3) erottelee:
      - hill/ridge (mäki/harju): symmetrinen, tuuli kiihtyy huipulla
      - escarpment (jyrkänne):   epäsymmetrinen, tasanne huipulla
    
    Erottelu perustuu downwind-puolen kaltevuuteen suhteessa
    upwind-puoleen. Mäessä molemmat puolet laskevat, jyrkänteessä
    downwind-puoli on suhteellisen tasainen.
    
    Returns
    -------
    str: 'hill' tai 'escarpment'
    """
    downwind_z = profile['downwind_z']
    downwind_d = profile['downwind_dist']
    z_origin = profile['z_origin']
    
    valid_dw = ~np.isnan(downwind_z)
    if not np.any(valid_dw) or len(downwind_d) < 3:
        # Ei downwind-dataa → oletus konservatiivinen (mäki)
        return 'hill'
    
    # Tutki downwind-puolen pudotusta samalla etäisyydellä kuin upwind-nousu
    check_dist = min(L_slope, downwind_d[-1]) if L_slope > 0 else 100.0
    dw_mask = (downwind_d > 0) & (downwind_d <= check_dist) & valid_dw
    
    if not np.any(dw_mask):
        return 'hill'
    
    z_min_dw = np.min(downwind_z[dw_mask])
    dz_drop_dw = z_origin - z_min_dw  # positiivinen = laskee
    
    # Symmetriasuhde: downwind-pudotus / upwind-nousu
    # > 0.5 → mäki (molemmat puolet laskevat/nousevat merkittävästi)
    # ≤ 0.5 → escarpment (tasanne tai loiva lasku downwindissä)
    if delta_z > 0:
        symmetry_ratio = dz_drop_dw / delta_z
    else:
        symmetry_ratio = 0.0
    
    if symmetry_ratio > 0.5:
        return 'hill'
    else:
        return 'escarpment'


def analyze_profile(profile, water_polygons_etrs=None, 
                    vegetation_zones_etrs=None,
                    origin_x=0, origin_y=0, z0_land=0.1):
    """
    Analysoi korkeusprofiilin vaikutukset tuulen nopeuteen.
    
    Speed-up-laskenta kolmiportaisesti:
    
    1. H/L < 0.05 → ei merkittävää maastovaikutusta
    2. 0.05 ≤ H/L < 0.3 → Jackson-Hunt (1975) lineaarinen teoria:
           s = A × (H/L)
       missä A = 2.0 (mäki/harju) tai A = 1.2 (jyrkänne)
    3. H/L ≥ 0.3 → Eurocode EN 1991-1-4 / RIL orografia:
           Le = H / 0.3  (efektiivinen rinnepituus)
           s = A × 0.3   (saturoituu ylärajaan)
       Tämä vastaa RIL:n tuulikuormaohjetta jyrkille rinteille.
    4. H/L > ~1.0 → cliff-varoitus (käsitellään analyze_downwind_terrain:ssa)
    
    Maastomuodon A-kerroin (EN 1991-1-4 Annex A.3):
      - Mäki/harju (hill/ridge):     A = 2.0
      - Jyrkänne (escarpment/cliff): A = 1.2
    
    Returns
    -------
    dict:
        'speed_up': rinteen kiihtymiskerroin (1 + s)
        'fractional_speed_up': fraktionaalinen speed-up s
        'H_eff': efektiivinen korkeusero [m]
        'L_slope': todellinen rinteen pituus [m]
        'L_effective': efektiivinen rinnepituus Le [m] (= L tai H/0.3)
        'slope': todellinen H/L
        'slope_effective': laskennallinen H/Le (≤ 0.3)
        'terrain_form': 'hill' tai 'escarpment'
        'speed_up_coeff': käytetty A-kerroin (2.0 tai 1.2)
        'speed_up_method': menetelmän nimi
        'z_origin': kohteen korkeus [m]
        'z_upwind_min': matalin kohta tuulen yläpuolella [m]
        'delta_z_max': suurin korkeusero [m]
    """
    z_origin = profile['z_origin']
    upwind_z = profile['upwind_z']
    upwind_d = profile['upwind_dist']
    
    # Oletustulos (NaN-profiili tai ei dataa)
    null_result = {
        'speed_up': 1.0,
        'fractional_speed_up': 0.0,
        'H_eff': 0.0,
        'L_slope': 0.0,
        'L_effective': 0.0,
        'slope': 0.0,
        'slope_effective': 0.0,
        'terrain_form': 'flat',
        'speed_up_coeff': 0.0,
        'speed_up_method': 'none',
        'z_origin': z_origin if not np.isnan(z_origin) else 0.0,
        'z_upwind_min': z_origin if not np.isnan(z_origin) else 0.0,
        'delta_z_max': 0.0,
    }
    
    # Suodata NaN:t pois
    valid = ~np.isnan(upwind_z)
    if not np.any(valid):
        return null_result
    
    # Etsi merkittävin korkeusero upwind-puolelta
    z_min_upwind = np.nanmin(upwind_z)
    idx_min = np.nanargmin(upwind_z)
    
    # Korkeusero (H) ja rinteen pituus (L)
    delta_z = z_origin - z_min_upwind
    L_slope = upwind_d[idx_min] if idx_min > 0 else 1.0
    
    # --- Speed-up: kolmiportainen menetelmä ---
    if L_slope <= 10 or delta_z <= 1.0:
        # Liian pieni rinne → ei maastovaikutusta
        return {
            **null_result,
            'z_origin': z_origin,
            'z_upwind_min': z_min_upwind,
            'H_eff': delta_z,
            'L_slope': L_slope,
            'L_effective': L_slope,
        }
    
    slope = delta_z / L_slope  # Todellinen H/L
    
    # Luokittele maastomuoto (mäki vs. jyrkänne)
    terrain_form = _classify_terrain_form(profile, delta_z, L_slope)
    
    # A-kerroin: EN 1991-1-4 Annex A.3
    #   Mäki/harju:  A = 2.0  (virtaus kiihtyy symmetrisesti)
    #   Jyrkänne:    A = 1.2  (irtoaminen yläreunassa syö energiaa)
    A_coeff = 2.0 if terrain_form == 'hill' else 1.2
    
    if slope < 0.05:
        # Hyvin loiva rinne → ei merkittävää efektiä
        s = 0.0
        L_eff = L_slope
        slope_eff = slope
        method = 'none'
    
    elif slope < 0.3:
        # Jackson-Hunt lineaarinen alue
        s = A_coeff * slope
        L_eff = L_slope
        slope_eff = slope
        method = 'jackson_hunt'
    
    else:
        # Eurocode EN 1991-1-4 / RIL: efektiivinen rinnepituus
        # Le = H / 0.3 → laskennallinen kaltevuus Φ = H/Le = 0.3
        # Speed-up saturoituu: s = A × 0.3
        L_eff = delta_z / 0.3
        slope_eff = 0.3
        s = A_coeff * 0.3
        method = 'eurocode_ril'
    
    speed_up = 1.0 + s
    
    return {
        'speed_up': speed_up,
        'fractional_speed_up': s,
        'H_eff': delta_z,
        'L_slope': L_slope,
        'L_effective': L_eff,
        'slope': slope,
        'slope_effective': slope_eff,
        'terrain_form': terrain_form,
        'speed_up_coeff': A_coeff,
        'speed_up_method': method,
        'z_origin': z_origin,
        'z_upwind_min': z_min_upwind,
        'delta_z_max': delta_z,
    }


# =============================================================================
# 4B. VESIALUEEN TUNNISTUS JA MAASTOKORJAUKSET
# =============================================================================

def create_water_mask(geometry, x_coords, y_coords):
    """
    Luo 2D-vesialuemaskin OSM-pohjaisista vesialuepolygoneista.
    
    Vesialueet tulevat suoraan geometria-JSON:n water_areas-esteistä
    (OSM: natural=water, waterway=*, natural=coastline).
    
    Parameters
    ----------
    geometry : SimulationGeometry
    x_coords, y_coords : np.ndarray
        DEM-hilan ETRS-TM35FIN koordinaatit
    
    Returns
    -------
    mask : np.ndarray (bool), shape (ny, nx)
        True = vesialue
    """
    from matplotlib.path import Path
    
    ny, nx = len(y_coords), len(x_coords)
    mask = np.zeros((ny, nx), dtype=bool)
    
    water_polys = geometry.get_water_polygons_local()
    if not water_polys:
        return mask
    
    # Hila-pisteet (meshgrid lasketaan kerran)
    xx, yy = np.meshgrid(x_coords, y_coords)
    points = np.column_stack([xx.ravel(), yy.ravel()])
    
    for wp in water_polys:
        verts_etrs = np.array([geometry.local_to_etrs(v[0], v[1])
                               for v in wp['vertices']])
        if len(verts_etrs) < 3:
            continue
        path = Path(verts_etrs)
        in_poly = path.contains_points(points).reshape((ny, nx))
        mask |= in_poly
    
    return mask


def identify_water_on_profile(profile, water_mask, x_coords, y_coords,
                               origin_x, origin_y):
    """
    Tunnista vesialueet korkeusprofiilin upwind-puolelta.
    
    Etsii yhtenäiset vesijaksot profiililla ja palauttaa tärkeimmän
    (suurin fetch) tiedot sisäisen rajakerroksen laskentaan.
    
    Parameters
    ----------
    profile : dict
        compute_terrain_profile():n palauttama profiili
    water_mask : np.ndarray (bool)
        create_water_mask():n palauttama maski
    x_coords, y_coords : np.ndarray
        DEM-hilan koordinaatit
    origin_x, origin_y : float
        Kohderakennuksen ETRS-koordinaatit
    
    Returns
    -------
    dict:
        has_water : bool
        d_land : float        - etäisyys lähimmästä rantaviivasta kohteeseen [m]
        fetch_water : float   - suurimman vesijakson fetch-pituus [m]
        fetch_total : float   - kaikkien vesijaksojen yhteispituus [m]
        z_water : float       - vesipinnan korkeus [m mpy]
        water_segments : list  - kaikki vesijaksot [{d_start, d_end, fetch, z_water}]
    """
    upwind_d = profile['upwind_dist']
    upwind_z = profile['upwind_z']
    wind_dir = profile['direction']
    
    # Upwind-suunnan yksikkövektori (sama kuin compute_terrain_profile)
    wind_rad = math.radians(wind_dir)
    dx_up = math.sin(wind_rad)
    dy_up = math.cos(wind_rad)
    
    # Näytteistä vesimaskia upwind-profiilin pisteissä
    upwind_water = np.zeros(len(upwind_d), dtype=bool)
    for i, d in enumerate(upwind_d):
        px = origin_x + d * dx_up
        py = origin_y + d * dy_up
        ix = np.searchsorted(x_coords, px) - 1
        iy = np.searchsorted(y_coords, py) - 1
        if 0 <= ix < len(x_coords) and 0 <= iy < len(y_coords):
            upwind_water[i] = water_mask[iy, ix]
    
    if not np.any(upwind_water):
        return {
            'has_water': False,
            'd_land': 0.0,
            'fetch_water': 0.0,
            'fetch_total': 0.0,
            'z_water': 0.0,
            'water_segments': [],
        }
    
    # Etsi yhtenäiset vesijaksot (transitiot)
    padded = np.concatenate([[False], upwind_water, [False]])
    transitions = np.diff(padded.astype(int))
    starts = np.where(transitions == 1)[0]
    ends = np.where(transitions == -1)[0]
    
    segments = []
    for s, e in zip(starts, ends):
        s_idx = min(s, len(upwind_d) - 1)
        e_idx = min(e - 1, len(upwind_d) - 1)
        d_start = float(upwind_d[s_idx])
        d_end = float(upwind_d[e_idx])
        fetch = d_end - d_start
        
        # Vesipinnan korkeus (keskiarvo jaksolla)
        seg_mask = (upwind_d >= d_start) & (upwind_d <= d_end)
        z_vals = upwind_z[seg_mask]
        z_vals = z_vals[~np.isnan(z_vals)]
        z_seg = float(np.mean(z_vals)) if len(z_vals) > 0 else 0.0
        
        segments.append({
            'd_start': d_start,
            'd_end': d_end,
            'fetch': float(max(fetch, 0.0)),
            'z_water': z_seg,
        })
    
    if not segments:
        return {
            'has_water': False,
            'd_land': 0.0,
            'fetch_water': 0.0,
            'fetch_total': 0.0,
            'z_water': 0.0,
            'water_segments': [],
        }
    
    # d_land = lyhin etäisyys rantaviivasta kohteeseen (lähimmän jakson alku)
    d_land = min(s['d_start'] for s in segments)
    
    # Pääjakso: suurin yhtenäinen fetch
    main_seg = max(segments, key=lambda s: s['fetch'])
    
    return {
        'has_water': True,
        'd_land': float(d_land),
        'fetch_water': main_seg['fetch'],
        'fetch_total': float(sum(s['fetch'] for s in segments)),
        'z_water': main_seg['z_water'],
        'water_segments': segments,
    }


def analyze_downwind_terrain(profile, building_height):
    """
    Analysoi maastonmuodot rakennuksen tuulen alapuolella (downwind)
    ja upwind-puolen jyrkkyys.
    
    Käsitellyt tapaukset:
    
    1. Jyrkkä lasku downwind (rakennus kallion reunalla)
       → Maasto putoaa wake-alueella. Tuuli "näkee" rakennuksen
         korkeampana koska wake ulottuu syvemmälle.
       → h_eff_building = h_building + Δz_drop
       → Esim: 12m talo, 8m pudotus → h_eff = 20m
    
    2. Jyrkkä nousu downwind (kallioseinä taakse)
       → Canyon-efekti: virtaus kiihtyy rakennuksen ja seinämän välissä
       → Recirculation-vyöhyke muuttuu
       → Merkitään varoitus, konservatiivinen käsittely
    
    3. Upwind cliff (erittäin jyrkkä nousu edessä)
       → Jackson-Hunt hajoaa kun H/L > 0.5
       → Virtaus irtoaa yläreunassa → recirculation
       → Merkitään cliff_upwind, speed-up saturoituu
    
    Parameters
    ----------
    profile : dict
        compute_terrain_profile():n palauttama profiili
    building_height : float
        Rakennuksen nimellinen korkeus [m]
    
    Returns
    -------
    dict:
        dz_drop : float        - pudotus wake-alueella [m] (positiivinen = alas)
        dz_rise_down : float   - nousu downwindissa [m] (positiivinen = ylös)
        h_eff_building : float - efektiivinen rakennuskorkeus [m]
        cliff_drop : bool      - jyrkkä pudotus havaittu (>5m/50m)
        cliff_upwind : bool    - jyrkkä kallio upwindissa (H/L > 0.5)
        canyon : bool          - canyon-efekti (pudotus + nousu)
        drop_slope : float     - pudotuksen kaltevuus [H/L]
        terrain_note : str     - selkokielinen kuvaus
    """
    downwind_d = profile['downwind_dist']
    downwind_z = profile['downwind_z']
    upwind_d = profile['upwind_dist']
    upwind_z = profile['upwind_z']
    z_origin = profile['z_origin']
    
    # Oletustulos
    result = {
        'dz_drop': 0.0,
        'dz_rise_down': 0.0,
        'h_eff_building': building_height,
        'cliff_drop': False,
        'cliff_upwind': False,
        'canyon': False,
        'drop_slope': 0.0,
        'terrain_note': '',
    }
    
    # --- Downwind-analyysi ---
    # Wake-alue ulottuu tyypillisesti 3-8× rakennuskorkeuden päähän.
    # Analysoidaan lähialue (0...5×h) ja kaukoalue (5×h...200m).
    wake_near = max(5.0 * building_height, 50.0)
    wake_far = max(wake_near, 200.0)
    
    valid_down = ~np.isnan(downwind_z)
    if not np.any(valid_down) or len(downwind_d) < 3:
        return result
    
    # Lähialueen pudotus (wake-vyöhyke)
    near_mask = (downwind_d > 0) & (downwind_d <= wake_near) & valid_down
    if np.any(near_mask):
        z_min_near = np.min(downwind_z[near_mask])
        dz_near = z_origin - z_min_near  # positiivinen = alas
        
        # Missä matalin kohta sijaitsee?
        idx_min_near = np.argmin(
            np.where(near_mask, downwind_z, np.inf))
        d_at_min = downwind_d[idx_min_near]
        
        if dz_near > 2.0 and d_at_min > 5.0:
            drop_slope = dz_near / d_at_min
            result['dz_drop'] = float(dz_near)
            result['drop_slope'] = float(drop_slope)
            
            # Efektiivinen rakennuskorkeus:
            # Tuuli "näkee" rakennuksen + pudotuksen, mutta ei täyttä
            # pudotusta koska wake hajautuu. Painokerroin: 
            # lähellä (d < 2×h) → 80% pudotuksesta,
            # kauempana (d > 5×h) → 30%.
            if d_at_min < 2.0 * building_height:
                drop_weight = 0.8
            elif d_at_min < 5.0 * building_height:
                drop_weight = 0.5
            else:
                drop_weight = 0.3
            
            dz_eff = dz_near * drop_weight
            result['h_eff_building'] = building_height + dz_eff
            
            # Jyrkkä pudotus = cliff
            if drop_slope > 0.10:  # >10% kaltevuus
                result['cliff_drop'] = True
    
    # Nousu downwind-puolella (kallioseinä tai mäki takana)
    far_mask = (downwind_d > 10.0) & (downwind_d <= wake_far) & valid_down
    if np.any(far_mask):
        z_max_far = np.max(downwind_z[far_mask])
        dz_rise = z_max_far - z_origin  # positiivinen = ylös
        
        if dz_rise > 3.0:
            result['dz_rise_down'] = float(dz_rise)
            
            # Canyon: pudotus + nousu → virtaus puristuu
            if result['dz_drop'] > 3.0 and dz_rise > 3.0:
                result['canyon'] = True
    
    # --- Upwind cliff -tunnistus ---
    # Etsi erittäin jyrkät nousut lähellä kohdetta
    near_up_mask = (upwind_d > 0) & (upwind_d <= 100.0) & (~np.isnan(upwind_z))
    if np.any(near_up_mask):
        # Tarkista onko lähellä (< 100m) erittäin jyrkkä pudotus (= cliff upwindissa)
        z_min_near_up = np.min(upwind_z[near_up_mask])
        dz_cliff = z_origin - z_min_near_up
        idx_min_up = np.argmin(np.where(near_up_mask, upwind_z, np.inf))
        d_cliff = upwind_d[idx_min_up]
        
        if dz_cliff > 3.0 and d_cliff > 0 and d_cliff < 100.0:
            cliff_slope = dz_cliff / d_cliff
            if cliff_slope > 0.5:
                result['cliff_upwind'] = True
    
    # --- Selkokielinen kuvaus ---
    notes = []
    if result['cliff_drop']:
        notes.append(
            f"Jyrkkä pudotus taakse: {result['dz_drop']:.1f}m "
            f"(kaltevuus {result['drop_slope']:.2f})")
    elif result['dz_drop'] > 2.0:
        notes.append(f"Loiva lasku taakse: {result['dz_drop']:.1f}m")
    
    if result['canyon']:
        notes.append(
            f"Canyon-efekti: pudotus {result['dz_drop']:.1f}m + "
            f"nousu {result['dz_rise_down']:.1f}m")
    elif result['dz_rise_down'] > 3.0:
        notes.append(f"Nousu taakse: {result['dz_rise_down']:.1f}m")
    
    if result['cliff_upwind']:
        notes.append("Jyrkkä kallio upwindissa (H/L > 0.5)")
    
    if result['h_eff_building'] > building_height * 1.1:
        notes.append(
            f"h_eff: {building_height:.0f}m → {result['h_eff_building']:.1f}m "
            f"(+{result['h_eff_building'] - building_height:.1f}m)")
    
    result['terrain_note'] = '; '.join(notes) if notes else 'Tasainen'
    
    return result


def compute_direction_corrections(profile_analysis, water_info, 
                                   downwind_info, z0_land=0.1,
                                   L_ibl=200.0, U_ratio_cap=4.0):
    """
    Yhdistä kaikki suuntakohtaiset korjauskertoimet.
    
    Kokonaiskerroin:
        U_effective(θ) = U_ref × speed_up(θ) × water_factor(θ)
        h_eff_building(θ) = h_nom + Δz_downwind_drop(θ)
    
    Parameters
    ----------
    profile_analysis : dict
        analyze_profile():n tulos (speed_up, delta_z_max, jne.)
    water_info : dict
        identify_water_on_profile():n tulos
    downwind_info : dict
        analyze_downwind_terrain():n tulos
    z0_land : float
        Maa-alueen aerodynaaminen karheus [m]
    L_ibl : float
        Sisäisen rajakerroksen kehityspituus [m] (100-300m)
    U_ratio_cap : float
        Fysikaalinen yläraja U_ratio-kertoimelle
    
    Returns
    -------
    dict:
        speed_up : float        - rinteen speed-up (1 + s)
        water_factor : float    - vesialueen nopeuskerroin (≥1.0)
        U_ratio : float         - kokonaiskerroin U_eff / U_ref
        h_eff_building : float  - efektiivinen rakennuskorkeus [m]
        cliff_warning : bool    - varoitus epätyypillisestä maastosta
        breakdown : dict        - osatekijöiden erittelyt
    """
    speed_up = profile_analysis['speed_up']
    cliff_upwind = downwind_info.get('cliff_upwind', False)
    
    # --- Vesialueen vaikutus ---
    if water_info['has_water'] and water_info['fetch_water'] > 50.0:
        z0_water = 0.001  # Sileä vedenpinta
        z_ref = 10.0      # FMI mittauskorkeus
        
        # Logaritmisen tuuliprofiilin suhde
        U_water_ratio = (math.log(z_ref / z0_water) /
                         math.log(z_ref / z0_land))
        
        # Sisäinen rajakerros: fetch maalla vesialueen jälkeen
        # vaimentaa efektiä eksponentiaalisesti
        d_land = water_info['d_land']
        f_water = max(0.0, 1.0 - d_land / L_ibl)
        
        # Fetchi vaikuttaa myös: pitkä fetch → täysi efekti,
        # lyhyt fetch → rajattu efekti
        fetch_factor = min(1.0, water_info['fetch_water'] / 500.0)
        f_water *= fetch_factor
        
        water_factor = 1.0 + f_water * (U_water_ratio - 1.0)
    else:
        water_factor = 1.0
        U_water_ratio = 1.0
        f_water = 0.0
    
    # --- Yhdistelmä ---
    U_ratio = speed_up * water_factor
    
    # Cliff-varoitus: Jackson-Hunt ei päde, saturointi
    cliff_warning = cliff_upwind or downwind_info.get('canyon', False)
    if cliff_upwind:
        # Speed-up on jo saturoinut analyze_profile():ssa,
        # mutta lisätään selkeä merkintä
        pass
    
    # Fysikaalinen yläraja
    U_ratio = min(U_ratio, U_ratio_cap)
    
    return {
        'speed_up': speed_up,
        'water_factor': water_factor,
        'U_ratio': U_ratio,
        'h_eff_building': downwind_info['h_eff_building'],
        'cliff_warning': cliff_warning,
        'breakdown': {
            'fractional_speed_up': profile_analysis['fractional_speed_up'],
            'delta_z_upwind': profile_analysis['delta_z_max'],
            'slope_H_over_L': profile_analysis['slope'],
            'slope_effective': profile_analysis.get('slope_effective', profile_analysis['slope']),
            'L_effective': profile_analysis.get('L_effective', profile_analysis['L_slope']),
            'terrain_form': profile_analysis.get('terrain_form', 'unknown'),
            'speed_up_coeff': profile_analysis.get('speed_up_coeff', 2.0),
            'speed_up_method': profile_analysis.get('speed_up_method', 'jackson_hunt'),
            'water_fetch': water_info.get('fetch_water', 0.0),
            'water_d_land': water_info.get('d_land', 0.0),
            'water_U_ratio': U_water_ratio if water_info['has_water'] else None,
            'water_f_blend': f_water,
            'dz_drop_downwind': downwind_info['dz_drop'],
            'dz_rise_downwind': downwind_info['dz_rise_down'],
            'cliff_upwind': cliff_upwind,
            'canyon': downwind_info.get('canyon', False),
            'terrain_note': downwind_info['terrain_note'],
        },
    }


def compute_vegetation_h_eff(geometry, elevation, x_coords, y_coords):
    """
    Laske kasvillisuusalueiden efektiivinen korkeus suhteessa kohteeseen.
    
    Returns
    -------
    list of dict: kasvillisuusalueet h_eff-korjauksilla
    """
    target = geometry.find_target_building()
    if not target:
        return []
    
    tx_etrs, ty_etrs = target['_center_etrs']
    
    # Kohteen maastonkorkeus
    ix_t = np.argmin(np.abs(x_coords - tx_etrs))
    iy_t = np.argmin(np.abs(y_coords - ty_etrs))
    z_target = elevation[iy_t, ix_t]
    
    veg_centers = geometry.get_vegetation_centers_etrs()
    results = []
    
    for vc in veg_centers:
        ex, ey = vc['etrs_center']
        
        # Kasvillisuuden maastonkorkeus
        ix_v = np.argmin(np.abs(x_coords - ex))
        iy_v = np.argmin(np.abs(y_coords - ey))
        z_veg_ground = elevation[iy_v, ix_v]
        
        # Korkeusero
        delta_z = z_veg_ground - z_target
        h_tree = vc['height']
        h_eff = max(0.0, h_tree + delta_z)
        
        # LAI-korjaus
        lai_original = vc['LAI']
        h_ref = 10.0  # FMI mittauskorkeus
        
        # Alkuperäinen LAI_2D (ilman korkeuskorjausta)
        lai_base = lai_original
        
        # Korjattu LAI_2D
        if h_tree > 0 and lai_original > 0:
            # Skaalaa suhteessa: h_eff/h_tree
            scale = min(h_eff / max(h_tree, 0.1), 2.0)  # Max 2x
            lai_corrected = lai_original * scale
        else:
            lai_corrected = lai_original
            scale = 1.0
        
        results.append({
            **vc,
            'z_ground': z_veg_ground,
            'z_target': z_target,
            'delta_z': delta_z,
            'h_eff': h_eff,
            'lai_original': lai_original,
            'lai_corrected': lai_corrected,
            'correction_scale': scale,
        })
    
    return results


# =============================================================================
# 5. KOKONAISANALYYSI
# =============================================================================

def run_terrain_analysis(geometry, elevation, x_coords, y_coords,
                         wind_directions=None, z0_land=0.1):
    """
    Suorita kokonaisanalyysi yhdelle kohteelle.
    
    Laskee jokaiselle tuulensuunnalle:
    - Korkeusprofiili (upwind + downwind)
    - Speed-up (Jackson-Hunt)
    - Vesialueen altistus (OSM-pohjaiset vesialueet, fetch, IBL-blending)
    - Downwind-maaston vaikutus (cliff drop, canyon, h_eff_building)
    - Yhdistetty korjauskerroin U_ratio(θ) ja h_eff_building(θ)
    
    Parameters
    ----------
    geometry : SimulationGeometry
    elevation : np.ndarray
    x_coords, y_coords : np.ndarray
    wind_directions : list of float
        Tuulensuunnat (oletus: 8 pääsuuntaa)
    z0_land : float
        Maa-alueen aerodynaaminen karheus [m] (oletus 0.1)
    
    Returns
    -------
    dict: Kaikki analyysitulokset
    """
    if wind_directions is None:
        wind_directions = [0, 45, 90, 135, 180, 225, 270, 315]
    
    target = geometry.find_target_building()
    if not target:
        print("  [WARN] Kohderakennusta ei löydetty!")
        return None
    
    tx_etrs, ty_etrs = target['_center_etrs']
    building_height = target.get('height', 10.0)
    
    # Vesialue-maski (OSM-pohjaiset polygonit)
    has_water_areas = len(geometry.water_areas) > 0
    if has_water_areas:
        water_mask = create_water_mask(geometry, x_coords, y_coords)
        water_pixel_count = np.sum(water_mask)
        print(f"   Vesialue-maski: {water_pixel_count} pikseliä "
              f"({len(geometry.water_areas)} polygonia)")
    else:
        water_mask = np.zeros((len(y_coords), len(x_coords)), dtype=bool)
    
    # Korkeusprofiilit + analyysit + korjaukset
    profiles = {}
    analyses = {}
    water_analyses = {}
    downwind_analyses = {}
    corrections = {}
    
    for wind_dir in wind_directions:
        # Korkeusprofiili
        prof = compute_terrain_profile(
            elevation, x_coords, y_coords,
            tx_etrs, ty_etrs, wind_dir
        )
        profiles[wind_dir] = prof
        
        # Speed-up (upwind rinne)
        ana = analyze_profile(prof)
        analyses[wind_dir] = ana
        
        # Vesialueen tunnistus upwind-profiililla
        w_info = identify_water_on_profile(
            prof, water_mask, x_coords, y_coords, tx_etrs, ty_etrs)
        water_analyses[wind_dir] = w_info
        
        # Downwind-maasto (pudotus, canyon, cliff)
        dw_info = analyze_downwind_terrain(prof, building_height)
        downwind_analyses[wind_dir] = dw_info
        
        # Yhdistetyt korjauskertoimet
        corr = compute_direction_corrections(
            ana, w_info, dw_info, z0_land=z0_land)
        corrections[wind_dir] = corr
    
    # Kasvillisuuden h_eff
    veg_heff = compute_vegetation_h_eff(geometry, elevation, x_coords, y_coords)
    
    # Yhteenveto
    z_target = analyses[0]['z_origin']
    max_U_ratio_dir = max(corrections, key=lambda d: corrections[d]['U_ratio'])
    max_U_ratio = corrections[max_U_ratio_dir]['U_ratio']
    max_speedup_dir = max(analyses, key=lambda d: analyses[d]['speed_up'])
    max_speedup = analyses[max_speedup_dir]['speed_up']
    max_delta_z = max(a['delta_z_max'] for a in analyses.values())
    
    # Merkittävät vesivaikutukset
    significant_water = {d: w for d, w in water_analyses.items()
                         if w['has_water'] and w['fetch_water'] > 100}
    
    # Merkittävät downwind-efektit
    significant_downwind = {d: dw for d, dw in downwind_analyses.items()
                            if dw['dz_drop'] > 3.0 or dw['canyon']
                            or dw['cliff_upwind']}
    
    # Varoitukset
    warnings = []
    for d, corr in corrections.items():
        if corr['cliff_warning']:
            dir_label = {0:'N', 45:'NE', 90:'E', 135:'SE',
                         180:'S', 225:'SW', 270:'W', 315:'NW'}.get(d, f'{d}°')
            note = corr['breakdown']['terrain_note']
            warnings.append(f"  {dir_label}: {note}")
    
    # Kasvillisuuden korkeuserot
    if veg_heff:
        significant_veg = [v for v in veg_heff 
                          if abs(v['delta_z']) > 2.0 and v['height'] > 3.0]
    else:
        significant_veg = []
    
    return {
        'geometry': geometry,
        'target': target,
        'z_target': z_target,
        'building_height': building_height,
        'profiles': profiles,
        'analyses': analyses,
        'water_analyses': water_analyses,
        'downwind_analyses': downwind_analyses,
        'corrections': corrections,
        'veg_heff': veg_heff,
        'significant_veg': significant_veg,
        'significant_water': significant_water,
        'significant_downwind': significant_downwind,
        'max_speedup': max_speedup,
        'max_speedup_dir': max_speedup_dir,
        'max_U_ratio': max_U_ratio,
        'max_U_ratio_dir': max_U_ratio_dir,
        'max_delta_z': max_delta_z,
        'wind_directions': wind_directions,
        'warnings': warnings,
    }


# =============================================================================
# 6. VISUALISOINTI
# =============================================================================

def plot_terrain_overview(result, elevation, x_coords, y_coords, output_path):
    """
    Päävisualisointi: korkeuskartta + profiilit + yhteenveto.
    """
    geom = result['geometry']
    target = result['target']
    
    fig = plt.figure(figsize=(20, 14))
    gs = GridSpec(2, 3, figure=fig, hspace=0.3, wspace=0.3)
    
    fig.suptitle(f'Maastoanalyysi: {geom.name}', 
                 fontsize=14, fontweight='bold', y=0.98)
    
    # ---- 1. Korkeuskartta ----
    ax1 = fig.add_subplot(gs[0, 0:2])
    
    # Hillshade
    ls = LightSource(azdeg=315, altdeg=45)
    extent = [x_coords[0], x_coords[-1], y_coords[0], y_coords[-1]]
    
    # Korkeuskartta
    im = ax1.imshow(elevation, origin='lower', extent=extent,
                    cmap='terrain', alpha=0.8)
    
    # Hillshade päällä
    hs = ls.hillshade(elevation, vert_exag=5, dx=x_coords[1]-x_coords[0],
                      dy=y_coords[1]-y_coords[0])
    ax1.imshow(hs, origin='lower', extent=extent, cmap='gray', alpha=0.3)
    
    plt.colorbar(im, ax=ax1, label='Korkeus [m mpy]', shrink=0.8)
    
    # Simulointialueen rajat
    bounds = geom.domain_bounds_etrs
    rect = mpatches.Rectangle(
        (bounds[0], bounds[1]), 
        bounds[2]-bounds[0], bounds[3]-bounds[1],
        linewidth=2, edgecolor='red', facecolor='none', 
        linestyle='--', label='Simulointialue')
    ax1.add_patch(rect)
    
    # Kohderakennus
    tx, ty = target['_center_etrs']
    ax1.plot(tx, ty, 'r*', markersize=15, zorder=10, label='Kohde')
    
    # Kasvillisuusalueet (joilla merkittävä korkeusero)
    for vc in result.get('significant_veg', []):
        ex, ey = vc['etrs_center']
        color = '#E74C3C' if vc['delta_z'] < -3 else '#27AE60'
        ax1.plot(ex, ey, 'o', color=color, markersize=6, zorder=8)
        ax1.annotate(f'Δz={vc["delta_z"]:+.0f}m', (ex, ey),
                    fontsize=6, color=color, xytext=(3, 3),
                    textcoords='offset points')
    
    # Vesialueet
    for w in geom.get_water_polygons_local():
        verts_etrs = np.array([geom.local_to_etrs(v[0], v[1]) 
                               for v in w['vertices']])
        polygon = plt.Polygon(verts_etrs, alpha=0.3, fc='#3498DB', 
                             ec='#2980B9', lw=1)
        ax1.add_patch(polygon)
    
    # Profiilisuunnat
    prof_len = max(geom.domain['width'], geom.domain['height']) * 0.5
    for wind_dir in result['wind_directions']:
        rad = math.radians(wind_dir)
        dx = -math.sin(rad) * prof_len
        dy = -math.cos(rad) * prof_len
        alpha = 0.5 if result['analyses'][wind_dir]['speed_up'] > 1.05 else 0.15
        ax1.plot([tx, tx+dx], [ty, ty+dy], '-', 
                color='#E74C3C', alpha=alpha, lw=1)
        ax1.text(tx+dx*1.05, ty+dy*1.05, f'{wind_dir}°', 
                fontsize=7, ha='center', alpha=alpha+0.2)
    
    ax1.set_xlabel('ETRS-TM35FIN East [m]')
    ax1.set_ylabel('ETRS-TM35FIN North [m]')
    ax1.set_title('Korkeuskartta ja simulointialue')
    ax1.legend(loc='upper left', fontsize=8)
    ax1.set_aspect('equal')
    
    # ---- 2. Tuulensuuntakohtaiset kertoimet (polaarikaavio) ----
    ax2 = fig.add_subplot(gs[0, 2], projection='polar')
    
    dirs_rad = [math.radians(d) for d in result['wind_directions']]
    speedups = [result['analyses'][d]['speed_up'] for d in result['wind_directions']]
    u_ratios = [result['corrections'][d]['U_ratio'] for d in result['wind_directions']]
    
    # Sulje ympyrä
    dirs_rad_closed = dirs_rad + [dirs_rad[0]]
    speedups_closed = speedups + [speedups[0]]
    u_ratios_closed = u_ratios + [u_ratios[0]]
    
    # U_ratio (kokonaiskerroin) — täytetty
    ax2.plot(dirs_rad_closed, u_ratios_closed, 's-', color='#8E44AD',
            lw=2, markersize=4, label='U_ratio (kokon.)')
    ax2.fill(dirs_rad_closed, u_ratios_closed, alpha=0.10, color='#8E44AD')
    
    # Speed-up (pelkkä rinne) — viiva
    ax2.plot(dirs_rad_closed, speedups_closed, 'o--', color='#E74C3C', 
            lw=1.5, markersize=4, alpha=0.7, label='Speed-up (rinne)')
    
    # Referenssiympyrä 1.0
    theta_ref = np.linspace(0, 2*np.pi, 100)
    ax2.plot(theta_ref, np.ones_like(theta_ref), '--', color='gray', 
            alpha=0.5, lw=1)
    
    ax2.set_theta_zero_location('N')
    ax2.set_theta_direction(-1)
    ax2.set_thetagrids([0, 45, 90, 135, 180, 225, 270, 315],
                        ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'])
    ax2.set_title('Korjauskertoimet suunnittain', fontsize=10, 
                  fontweight='bold', pad=15)
    ax2.set_rlabel_position(22.5)
    ax2.legend(fontsize=7, loc='lower right')
    
    # Annotoi max U_ratio
    max_idx = np.argmax(u_ratios)
    ax2.annotate(f'×{u_ratios[max_idx]:.2f}', 
                xy=(dirs_rad_closed[max_idx], u_ratios[max_idx]),
                fontsize=9, fontweight='bold', color='#8E44AD',
                xytext=(10, 10), textcoords='offset points')
    
    # ---- 3. Kriittisin profiili ----
    ax3 = fig.add_subplot(gs[1, 0:2])
    
    # Piirretään 2-3 kriittisintä profiilia (järjestetty U_ratio:n mukaan)
    sorted_dirs = sorted(result['wind_directions'],
                        key=lambda d: result['corrections'][d]['U_ratio'],
                        reverse=True)
    
    colors_prof = ['#E74C3C', '#3498DB', '#27AE60', '#F39C12']
    dir_labels = {0: 'N', 45: 'NE', 90: 'E', 135: 'SE',
                  180: 'S', 225: 'SW', 270: 'W', 315: 'NW'}
    
    z_target = result['z_target']
    
    for i, wind_dir in enumerate(sorted_dirs[:4]):
        prof = result['profiles'][wind_dir]
        ana = result['analyses'][wind_dir]
        corr = result['corrections'][wind_dir]
        w_info = result['water_analyses'][wind_dir]
        color = colors_prof[i]
        label_str = dir_labels.get(wind_dir, f'{wind_dir}°')
        
        # Legendateksti
        parts = [f'{label_str} (U×{corr["U_ratio"]:.2f}']
        if w_info['has_water']:
            parts.append(f'vesi:{w_info["fetch_water"]:.0f}m')
        parts.append(f'Δz={ana["delta_z_max"]:.1f}m)')
        legend_text = ', '.join(parts)
        
        # Upwind (positiivinen etäisyys)
        ax3.plot(prof['upwind_dist'], prof['upwind_z'], '-',
                color=color, lw=2, label=legend_text)
        # Downwind (negatiivinen etäisyys)
        ax3.plot(-prof['downwind_dist'], prof['downwind_z'], '-',
                color=color, lw=2, alpha=0.4)
        
        # Merkitse vesialueet profiililla
        for seg in w_info.get('water_segments', []):
            ax3.axvspan(seg['d_start'], seg['d_end'],
                       alpha=0.15, color='#3498DB')
    
    # Kohde
    ax3.axvline(x=0, color='red', ls=':', alpha=0.5)
    ax3.plot(0, z_target, 'r*', markersize=15, zorder=10)
    ax3.annotate(f'Kohde\n{z_target:.1f}m mpy', (0, z_target),
                xytext=(10, 15), textcoords='offset points',
                fontsize=9, fontweight='bold', color='red')
    
    ax3.set_xlabel('Etäisyys kohteesta [m] (← tuulen alapuoli | tuulen yläpuoli →)')
    ax3.set_ylabel('Korkeus [m mpy]')
    ax3.set_title('Korkeusprofiilit kriittisimmistä tuulensuunnista')
    ax3.legend(fontsize=8, loc='best')
    ax3.grid(True, alpha=0.2)
    
    # ---- 4. Yhteenvetotaulukko ----
    ax4 = fig.add_subplot(gs[1, 2])
    ax4.axis('off')
    
    # Tuulensuuntakohtainen taulukko
    lines = []
    lines.append(f"YHTEENVETO: {geom.name}")
    lines.append("━" * 48)
    lines.append(f"Kohteen korkeus: {z_target:.1f} m mpy")
    bh = result.get('building_height', 0)
    if bh > 0:
        lines.append(f"Rakennuksen korkeus: {bh:.0f} m")
    lines.append(f"")
    lines.append(f"{'Suunta':>6} {'Δz':>5} {'S-up':>5} {'Vesi':>5} {'U_rat':>6} {'h_eff':>5}")
    lines.append(f"{'─'*6:>6} {'─'*5:>5} {'─'*5:>5} {'─'*5:>5} {'─'*6:>6} {'─'*5:>5}")
    
    for d in result['wind_directions']:
        a = result['analyses'][d]
        c = result['corrections'][d]
        w = result['water_analyses'][d]
        dl = dir_labels.get(d, f'{d}°')
        marker = ''
        if c['U_ratio'] > 1.10:
            marker = ' ◄'
        if c['cliff_warning']:
            marker += '⚠'
        
        w_str = f'{c["water_factor"]:.2f}' if w['has_water'] else '—'
        h_str = f'{c["h_eff_building"]:.0f}' if c['h_eff_building'] != bh else '—'
        
        lines.append(
            f"{dl:>6} {a['delta_z_max']:>4.1f}m "
            f"×{a['speed_up']:.2f} "
            f"{w_str:>5} "
            f"×{c['U_ratio']:.2f} "
            f"{h_str:>5}{marker}")
    
    lines.append(f"")
    lines.append(f"Max U_ratio: ×{result['max_U_ratio']:.3f} "
                 f"({dir_labels.get(result['max_U_ratio_dir'], '?')})")
    lines.append(f"Max speed-up: ×{result['max_speedup']:.3f} "
                 f"({dir_labels.get(result['max_speedup_dir'], '?')})")
    lines.append(f"Max Δz: {result['max_delta_z']:.1f} m")
    
    # Vesialueet
    sig_water = result.get('significant_water', {})
    if sig_water:
        lines.append(f"")
        lines.append(f"VESIALUEEN ALTISTUS:")
        lines.append(f"{'─'*48}")
        for d, w in sig_water.items():
            dl = dir_labels.get(d, f'{d}°')
            c = result['corrections'][d]
            lines.append(
                f"  {dl}: fetch {w['fetch_water']:.0f}m, "
                f"d={w['d_land']:.0f}m "
                f"→ ×{c['water_factor']:.2f}")
    elif geom.water_areas:
        lines.append(f"")
        lines.append(f"Vesialue: ei merkittävää altistusta")
    
    # Downwind-efektit
    sig_dw = result.get('significant_downwind', {})
    if sig_dw:
        lines.append(f"")
        lines.append(f"MAASTOEFEKTIT:")
        lines.append(f"{'─'*48}")
        for d, dw in sig_dw.items():
            dl = dir_labels.get(d, f'{d}°')
            lines.append(f"  {dl}: {dw['terrain_note']}")
    
    # Kasvillisuuden korkeuskorjaukset
    sig_veg = result.get('significant_veg', [])
    if sig_veg:
        lines.append(f"")
        lines.append(f"KASVILLISUUS (|Δz| > 2m):")
        lines.append(f"{'─'*48}")
        for v in sig_veg[:6]:
            lines.append(
                f"  {v['name'][:18]:18s} h={v['height']:.0f}m "
                f"Δz={v['delta_z']:+.1f}m → h_eff={v['h_eff']:.1f}m")
    
    text = '\n'.join(lines)
    ax4.text(0.02, 0.98, text, transform=ax4.transAxes,
            fontsize=7.5, fontfamily='monospace', va='top',
            bbox=dict(boxstyle='round', facecolor='#F8F9FA', 
                     edgecolor='#DEE2E6', alpha=0.9))
    
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  Kuva: {output_path}")


# =============================================================================
# 7. MAIN
# =============================================================================

def analyze_single_site(json_path, output_dir=None, terrain_type='gentle'):
    """Suorita analyysi yhdelle kohteelle."""
    
    if output_dir is None:
        output_dir = os.path.dirname(os.path.abspath(json_path))
    
    # 1. Lue geometria
    print(f"\n1. Luetaan geometria: {os.path.basename(json_path)}")
    geom = SimulationGeometry(json_path)
    geom.summary()
    
    # 2. Hae/generoi korkeusdata
    print(f"\n2. Korkeusdata...")
    bounds = geom.extended_bounds_etrs
    print(f"   Alue: E {bounds[0]:.0f}–{bounds[2]:.0f}, "
          f"N {bounds[1]:.0f}–{bounds[3]:.0f}")
    print(f"   Koko: {(bounds[2]-bounds[0]):.0f} × {(bounds[3]-bounds[1]):.0f} m")
    
    # Yritä MML
    elevation, x_coords, y_coords = None, None, None
    try:
        elevation, x_coords, y_coords = fetch_mml_elevation_wcs(bounds)
    except Exception:
        pass
    
    if elevation is None:
        print(f"   → Generoidaan synteettinen data ({terrain_type})")
        # Arvioi base_height sijainnin perusteella
        base_heights = {
            'kerava': 40.0,
            'tampere': 85.0,
            'hyvink': 90.0,
        }
        name_lower = geom.name.lower()
        base_h = 50.0
        for key, h in base_heights.items():
            if key in name_lower:
                base_h = h
                break
        
        elevation, x_coords, y_coords = generate_synthetic_elevation(
            bounds, resolution=5.0, base_height=base_h,
            terrain_type=terrain_type
        )
    
    print(f"   DEM: {elevation.shape[1]} × {elevation.shape[0]} pikseliä")
    print(f"   Korkeus: {np.nanmin(elevation):.1f} – {np.nanmax(elevation):.1f} m")
    
    # 3. Suorita analyysi
    print(f"\n3. Lasketaan korkeusprofiilit (8 suuntaa)...")
    result = run_terrain_analysis(geom, elevation, x_coords, y_coords)
    
    if result is None:
        print("   [ERROR] Analyysi epäonnistui")
        return None
    
    # 4. Tulosta tulokset
    print(f"\n4. Tulokset:")
    print(f"   Kohteen korkeus: {result['z_target']:.1f} m mpy")
    print(f"   Rakennuksen korkeus: {result['building_height']:.1f} m")
    print(f"   Suurin korkeusero: {result['max_delta_z']:.1f} m")
    print(f"   Suurin speed-up: ×{result['max_speedup']:.3f} "
          f"(suunta {result['max_speedup_dir']}°)")
    print(f"   Suurin U_ratio: ×{result['max_U_ratio']:.3f} "
          f"(suunta {result['max_U_ratio_dir']}°)")
    
    dir_labels = {0: 'N', 45: 'NE', 90: 'E', 135: 'SE',
                  180: 'S', 225: 'SW', 270: 'W', 315: 'NW'}
    
    print(f"\n   {'Suunta':>6} {'Δz':>6} {'H/L':>6} {'Speed-up':>9} "
          f"{'Vesi':>6} {'U_ratio':>8} {'h_eff':>6} {'Menetelmä':>12} {'Huom':>5}")
    for d in result['wind_directions']:
        a = result['analyses'][d]
        c = result['corrections'][d]
        w = result['water_analyses'][d]
        dw = result['downwind_analyses'][d]
        dl = dir_labels.get(d, f'{d}°')
        
        flag = ' ◄' if c['U_ratio'] > 1.10 else ''
        w_str = f'{w["fetch_water"]:.0f}m' if w['has_water'] else '—'
        h_str = f'{c["h_eff_building"]:.0f}m' if c['h_eff_building'] != result['building_height'] else '—'
        warn = '⚠' if c['cliff_warning'] else ''
        
        # Menetelmä-sarake: method + terrain_form
        method = a.get('speed_up_method', '?')
        form = a.get('terrain_form', '?')
        if method == 'none' or method == 'flat':
            method_str = '—'
        elif method == 'eurocode_ril':
            method_str = f'EC/{form[:4]}'
        elif method == 'jackson_hunt':
            method_str = f'JH/{form[:4]}'
        else:
            method_str = method[:8]
        
        print(f"   {dl:>6} {a['delta_z_max']:>5.1f}m "
              f"{a['slope']:>6.3f} ×{a['speed_up']:>7.3f} "
              f"{w_str:>6} ×{c['U_ratio']:>6.3f} "
              f"{h_str:>6} {method_str:>12} {warn}{flag}")
    
    # Vesialueen vaikutukset
    if result['significant_water']:
        print(f"\n   Vesialueen altistus:")
        for d, w in result['significant_water'].items():
            dl = dir_labels.get(d, f'{d}°')
            c = result['corrections'][d]
            print(f"     {dl}: fetch {w['fetch_water']:.0f}m, "
                  f"d_land {w['d_land']:.0f}m → "
                  f"water_factor ×{c['water_factor']:.3f}")
    
    # Downwind-efektit
    if result['significant_downwind']:
        print(f"\n   Maastovaikutus (downwind):")
        for d, dw in result['significant_downwind'].items():
            dl = dir_labels.get(d, f'{d}°')
            print(f"     {dl}: {dw['terrain_note']}")
    
    # Varoitukset
    if result['warnings']:
        print(f"\n   ⚠ Varoitukset:")
        for w in result['warnings']:
            print(f"   {w}")
    
    if result['significant_veg']:
        print(f"\n   Kasvillisuus (merkittävä Δz):")
        for v in result['significant_veg'][:5]:
            print(f"   {v['name'][:20]:20s} h={v['height']:.0f}m "
                  f"Δz={v['delta_z']:+.1f}m → h_eff={v['h_eff']:.1f}m "
                  f"LAI: {v['lai_original']:.2f}→{v['lai_corrected']:.2f}")
    
    # 5. Visualisoi
    print(f"\n5. Piirretään visualisointi...")
    site_name = os.path.splitext(os.path.basename(json_path))[0]
    output_path = os.path.join(output_dir, f'terrain_{site_name}.png')
    plot_terrain_overview(result, elevation, x_coords, y_coords, output_path)
    
    return result


def plot_comparison(results, output_dir):
    """Vertaile kohteita keskenään."""
    
    fig, axes = plt.subplots(1, len(results), figsize=(7*len(results), 6))
    if len(results) == 1:
        axes = [axes]
    
    fig.suptitle('Maastoanalyysin vertailu — kohteet', 
                 fontsize=14, fontweight='bold')
    
    dir_labels = {0: 'N', 45: 'NE', 90: 'E', 135: 'SE',
                  180: 'S', 225: 'SW', 270: 'W', 315: 'NW'}
    
    for i, (path, result) in enumerate(results.items()):
        ax = axes[i]
        
        geom = result['geometry']
        dirs = result['wind_directions']
        speedups = [result['analyses'][d]['speed_up'] for d in dirs]
        delta_zs = [result['analyses'][d]['delta_z_max'] for d in dirs]
        
        x_pos = np.arange(len(dirs))
        labels = [dir_labels.get(d, f'{d}°') for d in dirs]
        
        bars_su = ax.bar(x_pos - 0.2, [(s-1)*100 for s in speedups], 0.35,
                        label='Speed-up [%]', color='#E74C3C', alpha=0.7)
        
        ax2 = ax.twinx()
        bars_dz = ax2.bar(x_pos + 0.2, delta_zs, 0.35,
                         label='Δz [m]', color='#3498DB', alpha=0.7)
        
        ax.set_xticks(x_pos)
        ax.set_xticklabels(labels, fontsize=8)
        ax.set_ylabel('Speed-up [%]', color='#E74C3C')
        ax2.set_ylabel('Δz [m]', color='#3498DB')
        ax.set_title(f'{geom.name}\n(z={result["z_target"]:.0f}m mpy)',
                    fontsize=10, fontweight='bold')
        ax.grid(True, alpha=0.2, axis='y')
        ax.axhline(y=0, color='gray', lw=0.5)
        
        # Yhdistetty legenda
        if i == 0:
            lines1, labels1 = ax.get_legend_handles_labels()
            lines2, labels2 = ax2.get_legend_handles_labels()
            ax.legend(lines1 + lines2, labels1 + labels2, 
                     fontsize=7, loc='upper right')
    
    plt.tight_layout()
    outpath = os.path.join(output_dir, 'terrain_comparison.png')
    plt.savefig(outpath, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"\nVertailu: {outpath}")


def main():
    """Komentorivi-käyttöliittymä."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='MikroilmastoCFD — Maastokorkeuden analyysi',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Esimerkkejä:
  python3 terrain_analysis.py --input kohde.json
  python3 terrain_analysis.py --input kohde.json --output ./tulokset/
  python3 terrain_analysis.py --input a.json b.json c.json --output ./vertailu/
  python3 terrain_analysis.py --input kohde.json --synthetic hilly

API-avain luetaan automaattisesti ympäristömuuttujasta MML_API_KEY.
Jos MML-data ei ole saatavilla, käytetään synteettistä maastomallia.
        """)
    
    parser.add_argument('--input', '-i', nargs='+', required=True,
                        help='Geometria-JSON tiedosto(t)')
    parser.add_argument('--output', '-o', default='.',
                        help='Tuloskansio (oletus: nykyinen hakemisto)')
    parser.add_argument('--synthetic', '-s', 
                        choices=['flat', 'gentle', 'hilly', 'coastal'],
                        default='gentle',
                        help='Synteettisen maastomallin tyyppi fallbackina '
                             '(oletus: gentle)')
    parser.add_argument('--directions', '-d', type=int, default=8,
                        choices=[4, 8, 16],
                        help='Tuulensuuntien määrä (oletus: 8)')
    parser.add_argument('--resolution', '-r', type=float, default=2.0,
                        help='DEM-resoluutio metreinä (oletus: 2.0)')
    
    args = parser.parse_args()
    
    # Luo tuloskansio
    os.makedirs(args.output, exist_ok=True)
    
    # Tarkista MML_API_KEY
    api_key = os.environ.get('MML_API_KEY')
    if api_key:
        print(f"MML_API_KEY: löydetty ({len(api_key)} merkkiä)")
    else:
        print("MML_API_KEY: ei asetettu — käytetään synteettistä dataa")
    
    # Aja analyysit
    results = {}
    for json_path in args.input:
        if not os.path.exists(json_path):
            print(f"\n[ERROR] Tiedostoa ei löydy: {json_path}")
            continue
        
        result = analyze_single_site(
            json_path, 
            output_dir=args.output,
            terrain_type=args.synthetic
        )
        if result:
            results[json_path] = result
    
    # Vertailukuva jos useita kohteita
    if len(results) > 1:
        plot_comparison(results, args.output)
    
    print(f"\nValmis. Tulokset kansiossa: {os.path.abspath(args.output)}")
    return results


if __name__ == '__main__':
    main()
