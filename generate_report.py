#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CFD-simuloinnin PDF-raportin generointi.

Luo automaattisen raportin joka sisältää:
- Kohteen tiedot (osoite, kuvaus)
- Geometrian visualisointi
- Nested comparison (jos nested-simulointi)
- Kaikki fine-visualisoinnit

Käyttö:
    python generate_report.py results/case1/ --title "Rantalantie 8, Ulvila"
    python generate_report.py results/case1/ --geometry examples/area.json
"""

import argparse
import json
import sys
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Tuple

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
import matplotlib.image as mpimg


# ============================================================================
# MML (Maanmittauslaitos) Maastotietokanta - rakennusten korkeustiedot
# ============================================================================

# MML API-avain ympäristömuuttujasta (rekisteröidy: https://www.maanmittauslaitos.fi/rajapinnat/api-avaimen-ohje)
import os
MML_API_KEY = os.environ.get('MML_API_KEY', None)


def _get_vegetation_color(veg_type: str):
    """Palauta (facecolor, edgecolor, is_hard) kasvillisuustyypille.
    
    Värit vastaavat zone_editor.py ZONE_TYPES-värikarttaa.
    is_hard=True → tie/vesi (korkeampi alpha), False → kasvillisuus (matalampi alpha).
    
    Vihreän sävyt vaaleimmasta tummimpaan:
      yard_lawn  #98FB98 (nurmikko - vaalein)
      park_lawn  #90EE90 
      yard_mixed #7FBF7F (pensaat+nurmi)
      park       #6DBE6D
      forest     #228b22 (metsä - tummin, oletus)
    """
    # Suora haku yleisimmille tyypeille
    _DIRECT = {
        # Tiet - harmaa
        'road': ('#909090', '#606060', True),
        'road_surface': ('#909090', '#606060', True),
        # Vesi - sininen
        'water': ('#a8d4f0', '#4a90c4', True),
        'lake': ('#a8d4f0', '#4a90c4', True),
        'pond': ('#a8d4f0', '#4a90c4', True),
        'river': ('#a8d4f0', '#4a90c4', True),
        'reservoir': ('#a8d4f0', '#4a90c4', True),
        # Pellot - kellertävä
        'farmland': ('#FFE082', '#DAA520', False),
        'pasture': ('#9ACD32', '#6B8E23', False),
        # Pihat - vaaleat vihreät
        'yard_lawn': ('#98FB98', '#6BBF6B', False),       # Vaalein vihreä
        'yard_mixed': ('#7FBF7F', '#5A9A5A', False),      # Vaalea vihreä
        # Niityt - kellertävän vihreä
        'meadow_natural': ('#BDB76B', '#8E8B4D', False),
        'meadow_maintained': ('#C5D86D', '#9AAD4D', False),
        # Paljas maa - ruskea
        'bare_soil': ('#8B7355', '#6B5335', False),
        # Katupuut
        'street_trees': ('#6B8E23', '#4A6B13', False),
    }
    if veg_type in _DIRECT:
        return _DIRECT[veg_type]
    
    # Kategoriapohjainen tunnistus (prefix)
    if veg_type.startswith('field_'):
        return '#FFE082', '#DAA520', False            # Pelto
    if veg_type.startswith('park') or veg_type in ('playground', 'cemetery'):
        return '#6DBE6D', '#4A8E4A', False            # Puisto
    if veg_type.startswith('golf_'):
        return '#7CFC00', '#5CB200', False             # Golf
    if veg_type.startswith('hedge_') or veg_type.startswith('shrub_') or veg_type == 'juniper':
        return '#2E5E2E', '#1A4A1A', False             # Pensas
    if veg_type.startswith('wetland_') or veg_type.startswith('bog_') or veg_type == 'shore_vegetation':
        return '#5F9EA0', '#3D7F81', False             # Kosteikko
    if veg_type.startswith('green_roof_'):
        return '#9DC183', '#7AA060', False             # Viherkatto
    # Oletus: metsänvihreä
    return '#228b22', '#1a6b1a', False


def _sort_zones_for_drawing(porous_zones: list) -> list:
    """Lajittele kasvillisuusalueet piirtojärjestykseen.
    
    Kovat pinnat (tiet, vesi) piirretään VIIMEISENÄ jotta ne näkyvät
    kasvillisuusalueiden päällä eivätkä jää niiden peittoon.
    
    Järjestys: metsä/kasvillisuus → pihat → pellot → tiet → vesi
    """
    _HARD_TYPES = frozenset({
        'road', 'road_surface',
        'water', 'lake', 'pond', 'river', 'reservoir',
    })
    def _sort_key(zone):
        veg_type = zone.get('vegetation_type', zone.get('type', 'tree_zone'))
        if veg_type in _HARD_TYPES:
            return 1  # Piirretään viimeisenä (päällimmäiseksi)
        return 0      # Kasvillisuus ensin (alle)
    return sorted(porous_zones, key=_sort_key)


def fetch_building_heights_from_mml(
    center_lat: float,
    center_lon: float,
    domain_width: float,
    domain_height: float,
    timeout: float = 10.0,
    api_key: str = None
) -> Optional[Dict]:
    """
    Hakee rakennusten korkeustiedot Maanmittauslaitoksen Maastotietokanta-rajapinnasta.
    
    Käyttää avointa OGC API Features -rajapintaa:
    https://avoin-paikkatieto.maanmittauslaitos.fi/maastotiedot/features/v1/
    
    HUOM: Vaatii API-avaimen! Rekisteröidy ilmaiseksi:
    https://www.maanmittauslaitos.fi/rajapinnat/api-avaimen-ohje
    
    API-avain voidaan antaa:
    1. Ympäristömuuttujana MML_API_KEY
    2. Parametrina api_key
    
    Korkeustieto haetaan 'korkeus' tai 'kerrosluku' kentästä.
    Kerrosluvusta lasketaan arvio (kerros × 3m).
    
    Args:
        center_lat: Keskipisteen leveysaste (WGS84)
        center_lon: Keskipisteen pituusaste (WGS84)
        domain_width: Alueen leveys metreinä
        domain_height: Alueen korkeus metreinä
        timeout: API-kutsun aikakatkaisu sekunteina
        api_key: MML API-avain (valinnainen, oletuksena ympäristömuuttujasta)
        
    Returns:
        Dict jossa rakennusten korkeustiedot paikallisissa koordinaateissa:
        {
            'buildings': [
                {'x': float, 'y': float, 'height': float, 'mtk_id': str},
                ...
            ],
            'max_height': float,
            'source': 'MML Maastotietokanta'
        }
        tai None jos haku epäonnistui (verkkovirhe, ei dataa, ei API-avainta tms.)
    """
    # Käytä annettua avainta tai ympäristömuuttujaa
    key = api_key or MML_API_KEY
    if not key:
        print("  MML: API-avain puuttuu (aseta MML_API_KEY ympäristömuuttuja)")
        return None
    
    try:
        import requests
        import pyproj
    except ImportError:
        print("  Varoitus: requests tai pyproj ei asennettu, MML-haku ohitetaan")
        return None
    
    try:
        # WGS84 -> ETRS-TM35FIN (EPSG:3067) muunnos
        wgs84 = pyproj.CRS('EPSG:4326')
        tm35fin = pyproj.CRS('EPSG:3067')
        transformer_to_tm35 = pyproj.Transformer.from_crs(wgs84, tm35fin, always_xy=True)
        transformer_to_wgs = pyproj.Transformer.from_crs(tm35fin, wgs84, always_xy=True)
        
        # Muunna keskipiste ETRS-TM35FIN:iin
        center_e, center_n = transformer_to_tm35.transform(center_lon, center_lat)
        
        # Laske bbox (hieman laajempi kuin domain)
        margin = 50  # metriä
        half_w = domain_width / 2 + margin
        half_h = domain_height / 2 + margin
        
        bbox_min_e = center_e - half_w
        bbox_max_e = center_e + half_w
        bbox_min_n = center_n - half_h
        bbox_max_n = center_n + half_h
        
        # Muunna bbox WGS84:ään API:a varten (API käyttää WGS84 oletuksena)
        bbox_min_lon, bbox_min_lat = transformer_to_wgs.transform(bbox_min_e, bbox_min_n)
        bbox_max_lon, bbox_max_lat = transformer_to_wgs.transform(bbox_max_e, bbox_max_n)
        
        # MML Maastotiedot API
        api_url = f"https://avoin-paikkatieto.maanmittauslaitos.fi/maastotiedot/features/v1/collections/rakennus/items?api-key={key}"
        
        params = {
            'bbox': f"{bbox_min_lon},{bbox_min_lat},{bbox_max_lon},{bbox_max_lat}",
            'limit': 500,
            'f': 'json'
        }
        
        print(f"  Haetaan rakennusten korkeustiedot MML:stä...")
        response = requests.get(api_url, params=params, timeout=timeout)
        
        if response.status_code == 401:
            print(f"  Varoitus: MML API-avain virheellinen tai vanhentunut (401)")
            return None
        elif response.status_code != 200:
            print(f"  Varoitus: MML API palautti koodin {response.status_code}")
            return None
        
        data = response.json()
        features = data.get('features', [])
        
        if not features:
            print(f"  MML: Ei rakennuksia alueella")
            return None
        
        print(f"  MML: Löytyi {len(features)} rakennusta")
        
        # Parsitaan rakennusten tiedot
        buildings = []
        for feature in features:
            props = feature.get('properties', {})
            geom = feature.get('geometry', {})
            
            # Käytetään kohdeluokkaa korkeuden arviointiin
            # Kohdeluokan viimeinen numero kertoo kerroslukualueen:
            #   - päättyy 1 (esim. 42211) = 1-2 krs → 6 m
            #   - päättyy 2 (esim. 42212) = 3+ krs → 12 m
            #   - päättyy 0 tai muu = tuntematon → 8 m
            kohdeluokka = props.get('kohdeluokka')
            if kohdeluokka:
                last_digit = kohdeluokka % 10
                if last_digit == 1:
                    height = 6.0  # 1-2 kerrosta
                elif last_digit == 2:
                    height = 12.0  # 3+ kerrosta
                else:
                    height = 8.0  # tuntematon
            else:
                # Fallback jos kohdeluokkaa ei ole
                height = 8.0
            
            if height <= 0:
                continue
            
            # Hae keskipiste
            coords = geom.get('coordinates', [])
            if geom.get('type') == 'Point':
                lon, lat = coords[0], coords[1]
            elif geom.get('type') == 'Polygon' and coords:
                # Laske polygonin keskipiste
                ring = coords[0]
                lon = sum(c[0] for c in ring) / len(ring)
                lat = sum(c[1] for c in ring) / len(ring)
            else:
                continue
            
            # Muunna paikallisiin koordinaatteihin (keskipiste origossa)
            e, n = transformer_to_tm35.transform(lon, lat)
            local_x = e - center_e
            local_y = n - center_n
            
            buildings.append({
                'x': local_x,
                'y': local_y,
                'height': float(height),
                'mtk_id': str(props.get('mtk_id', '')),
                'kohdeluokka': props.get('kohdeluokka', 0)
            })
        
        if not buildings:
            print(f"  MML: Ei korkeustietoja saatavilla")
            return None
        
        max_height = max(b['height'] for b in buildings)
        print(f"  MML: {len(buildings)} rakennusta korkeustiedoilla, max {max_height:.1f} m")
        
        return {
            'buildings': buildings,
            'max_height': max_height,
            'source': 'MML Maastotietokanta'
        }
        
    except requests.exceptions.Timeout:
        print(f"  Varoitus: MML API aikakatkaisu ({timeout}s)")
        return None
    except requests.exceptions.RequestException as e:
        print(f"  Varoitus: MML API virhe: {e}")
        return None
    except Exception as e:
        print(f"  Varoitus: MML-haku epäonnistui: {e}")
        return None


def match_mml_heights_to_buildings(
    building_analysis: dict,
    mml_data: dict,
    match_radius: float = 15.0
) -> dict:
    """
    Yhdistää MML:n korkeustiedot building_analysis:n rakennuksiin.
    
    Käyttää lähimmän naapurin hakua: jokainen analysoitu rakennus
    yhdistetään lähimpään MML-rakennukseen jos etäisyys < match_radius.
    
    Args:
        building_analysis: analyze_buildings_from_results:n tulos
        mml_data: fetch_building_heights_from_mml:n tulos
        match_radius: Maksimietäisyys metreinä rakennusten matchaamiseen
        
    Returns:
        Päivitetty building_analysis jossa 'mml_height' kentät
    """
    if mml_data is None or 'buildings' not in mml_data:
        return building_analysis
    
    mml_buildings = mml_data['buildings']
    
    # Rakenna MML-rakennusten koordinaattilista
    mml_coords = np.array([[b['x'], b['y']] for b in mml_buildings])
    mml_heights = np.array([b['height'] for b in mml_buildings])
    mml_kohdeluokat = [b.get('kohdeluokka', 0) for b in mml_buildings]
    
    matched_count = 0
    
    for bldg in building_analysis['buildings']:
        # Rakennuksen keskipiste suhteessa fine_regioniin
        # Huom: building_analysis:n koordinaatit ovat hilakoordinaateissa
        # Tarvitaan muunnos paikallisiin metreihin
        
        center_x = bldg['center_x']
        center_y = bldg['center_y']
        
        # Laske etäisyydet kaikkiin MML-rakennuksiin
        distances = np.sqrt((mml_coords[:, 0] - center_x)**2 + 
                           (mml_coords[:, 1] - center_y)**2)
        
        min_idx = np.argmin(distances)
        min_dist = distances[min_idx]
        
        if min_dist <= match_radius:
            bldg['mml_height'] = float(mml_heights[min_idx])
            bldg['mml_kohdeluokka'] = mml_kohdeluokat[min_idx]
            bldg['mml_match_distance'] = float(min_dist)
            matched_count += 1
        else:
            bldg['mml_height'] = None
            bldg['mml_kohdeluokka'] = None
            bldg['mml_match_distance'] = None
    
    print(f"  MML: Yhdistettiin {matched_count}/{len(building_analysis['buildings'])} rakennusta")
    
    # Tunnista korkein rakennus (jos korkeusero > 2m)
    heights_with_id = [(b['id'], b.get('mml_height')) for b in building_analysis['buildings'] 
                       if b.get('mml_height') is not None]
    
    if len(heights_with_id) >= 2:
        sorted_heights = sorted(heights_with_id, key=lambda x: x[1], reverse=True)
        highest_id, highest_h = sorted_heights[0]
        second_h = sorted_heights[1][1]
        
        if highest_h - second_h > 2.0:
            # Merkitse korkein rakennus
            for bldg in building_analysis['buildings']:
                if bldg['id'] == highest_id:
                    bldg['is_highest'] = True
                    bldg['height_advantage'] = highest_h - second_h
                    print(f"  Korkein rakennus: #{highest_id} ({highest_h:.1f}m, +{highest_h - second_h:.1f}m)")
                else:
                    bldg['is_highest'] = False
        else:
            for bldg in building_analysis['buildings']:
                bldg['is_highest'] = False
    
    building_analysis['mml_data'] = mml_data
    return building_analysis


def save_mml_heights_to_json(building_analysis: dict, output_path: Path) -> bool:
    """
    Tallentaa MML-korkeustiedot JSON-tiedostoon.
    
    Tiedostomuoto:
    {
        "source": "MML Maastotietokanta",
        "fetch_date": "2026-01-24",
        "buildings": {
            "1": {"height_m": 12.0, "is_highest": true, "height_advantage_m": 3.5},
            "2": {"height_m": 8.5, "is_highest": false},
            ...
        },
        "statistics": {
            "total_buildings": 5,
            "buildings_with_height": 4,
            "max_height_m": 12.0,
            "min_height_m": 6.0,
            "mean_height_m": 8.5
        }
    }
    
    Args:
        building_analysis: analyze_building_loads:n tulos MML-tiedoilla
        output_path: Tulostiedoston polku
        
    Returns:
        True jos tallennus onnistui
    """
    if not building_analysis or 'buildings' not in building_analysis:
        return False
    
    # Kerää korkeustiedot
    heights_data = {
        "source": "MML Maastotietokanta (avoin-paikkatieto.maanmittauslaitos.fi)",
        "fetch_date": datetime.now().strftime("%Y-%m-%d"),
        "buildings": {},
        "statistics": {}
    }
    
    heights_list = []
    
    for bldg in building_analysis['buildings']:
        bldg_id = str(bldg['id'])
        mml_height = bldg.get('mml_height')
        
        if mml_height is not None:
            entry = {
                "height_m": round(mml_height, 1),
                "is_highest": bldg.get('is_highest', False)
            }
            
            if bldg.get('is_highest') and bldg.get('height_advantage'):
                entry["height_advantage_m"] = round(bldg['height_advantage'], 1)
            
            if bldg.get('mml_match_distance') is not None:
                entry["match_distance_m"] = round(bldg['mml_match_distance'], 1)
            
            heights_data["buildings"][bldg_id] = entry
            heights_list.append(mml_height)
    
    # Tilastot
    if heights_list:
        heights_data["statistics"] = {
            "total_buildings": len(building_analysis['buildings']),
            "buildings_with_height": len(heights_list),
            "max_height_m": round(max(heights_list), 1),
            "min_height_m": round(min(heights_list), 1),
            "mean_height_m": round(sum(heights_list) / len(heights_list), 1)
        }
    else:
        heights_data["statistics"] = {
            "total_buildings": len(building_analysis['buildings']),
            "buildings_with_height": 0
        }
    
    # Tallenna
    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(heights_data, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"  Varoitus: MML-korkeuksien tallennus epäonnistui: {e}")
        return False


def calculate_smart_dpi(grid_nx: int, grid_ny: int, 
                        figure_inches: float = 10.0,
                        min_dpi: int = 80, 
                        max_dpi: int = 200) -> int:
    """
    Laskee optimaalisen DPI:n hilakokon perusteella.
    
    Tavoite: 2-4 pikseliä per hilasolu
    - Liian pieni DPI → pikselöitynyt kuva
    - Liian suuri DPI → turha tiedostokoko, ei lisää informaatiota
    
    Args:
        grid_nx, grid_ny: Hilaverkon koko
        figure_inches: Kuvan koko tuumina (oletus 10")
        min_dpi: Minimi-DPI (oletus 80)
        max_dpi: Maksimi-DPI (oletus 200)
        
    Returns:
        Optimaalinen DPI
    """
    grid_size = max(grid_nx, grid_ny)
    ideal_dpi = int((grid_size / figure_inches) * 3)
    return max(min_dpi, min(ideal_dpi, max_dpi))


def get_smart_dpi_from_image(image_path: Path, figure_inches: float = 10.0) -> int:
    """
    Lukee kuvan koon ja laskee optimaalisen DPI:n.
    
    Args:
        image_path: Polku kuvaan
        figure_inches: Kuvan koko tuumina
        
    Returns:
        Optimaalinen DPI (tai oletus 150 jos ei voida lukea)
    """
    try:
        img = mpimg.imread(str(image_path))
        ny, nx = img.shape[:2]
        return calculate_smart_dpi(nx, ny, figure_inches)
    except:
        return 150  # Oletus


def get_smart_dpi_from_metadata(results_dir: Path, figure_inches: float = 10.0) -> int:
    """
    Lukee hilakokon metadata.json:sta ja laskee optimaalisen DPI:n.
    
    Args:
        results_dir: Tuloskansio
        figure_inches: Kuvan koko tuumina
        
    Returns:
        Optimaalinen DPI
    """
    results_dir = Path(results_dir)
    
    # Yritä lukea metadata eri paikoista
    metadata_files = [
        results_dir / 'domain.json',
        results_dir / 'data' / 'domain.json',
        results_dir / 'multi_wind_metadata.json',
        results_dir / 'metadata.json',
        results_dir / 'data' / 'metadata.json',
        results_dir.parent / 'multi_wind_metadata.json',  # combined/-kansion yläpuolelta
    ]
    
    for mf in metadata_files:
        if mf.exists():
            try:
                with open(mf, 'r') as f:
                    meta = json.load(f)
                nx = meta.get('nx', meta.get('grid_nx', 0))
                ny = meta.get('ny', meta.get('grid_ny', 0))
                if nx > 0 and ny > 0:
                    return calculate_smart_dpi(nx, ny, figure_inches)
            except:
                continue
    
    # Vaihtoehto: lue koko .npy-tiedostosta
    npy_files = list(results_dir.glob('data/*.npy')) + list(results_dir.glob('*.npy'))
    for npy_file in npy_files:
        try:
            arr = np.load(str(npy_file))
            if arr.ndim >= 2:
                ny, nx = arr.shape[:2]
                return calculate_smart_dpi(nx, ny, figure_inches)
        except:
            continue
    
    return 150  # Oletus


# ============================================================================
# RAPORTIN TYYLIMÄÄRITTELYT
# Yhtenäinen tyyli dokumentaation kanssa
# ============================================================================

# Globaali DPI-asetus (asetetaan generate_report() alussa)
REPORT_DPI = 150

# Värit (sama kuin dokumentaatiossa)
DARK_BLUE = '#1a5276'      # Tummansininen - otsikkotekstit
LIGHT_BLUE = '#d6eaf8'     # Vaaleansininen - otsikkotausta
ACCENT_BLUE = '#2874a6'    # Korostusväri - taulukot
TEXT_DARK = '#2c3e50'      # Tumma teksti
TEXT_GRAY = '#666666'      # Harmaa teksti

# Fontit
FONT_FAMILY = 'DejaVu Sans'  # Tukee skandinaavisia merkkejä
TITLE_SIZE = 14
SECTION_SIZE = 12
SUBSECTION_SIZE = 10
BODY_SIZE = 9
CAPTION_SIZE = 8


def set_report_style():
    """Asettaa matplotlib-tyylin raportille."""
    plt.rcParams.update({
        'font.family': 'sans-serif',
        'font.sans-serif': [FONT_FAMILY, 'Arial', 'Helvetica', 'DejaVu Sans'],
        'font.size': BODY_SIZE,
        'axes.titlesize': SECTION_SIZE,
        'axes.labelsize': BODY_SIZE,
        'xtick.labelsize': CAPTION_SIZE,
        'ytick.labelsize': CAPTION_SIZE,
        'legend.fontsize': CAPTION_SIZE,
        'figure.titlesize': TITLE_SIZE,
    })


# ============================================================================
# KÄÄNNÖKSET / TRANSLATIONS
# ============================================================================

TRANSLATIONS = {
    'fi': {
        # Kansilehti
        'title': 'CFD Tuulisuusanalyysi',
        'report_created': 'Raportti luotu',
        'footer': 'CFD Mikroilmastosimulointi',
        
        # Yhteenveto
        'summary': 'Yhteenveto',
        'site': 'Kohde',
        'conclusions': 'Johtopäätökset',
        'critical_buildings': 'Kriittisimmät rakennukset',
        'recommendations': 'Toimenpide-ehdotukset',
        'building_ids': 'Rakennusten tunnisteet',
        
        # Analyysitekstit
        'analyzed_buildings': 'Analysoitu {n} rakennusta CFD-simuloinnilla (SST k-ω turbulenssimalli)',
        'max_pressure': 'Suurin painerasitus: Rakennus #{id} ({dir}), Cp = {cp:.1f} → kosteusriski',
        'max_velocity': 'Suurin tuulinopeus: Rakennus #{id} ({dir}), v = {v:.1f} m/s → viistosade',
        'max_convection': 'Suurin konvektio: Rakennus #{id} ({dir}) → voimakas jäähtyminen',
        'max_heat_transfer': 'Suurin lämmönsiirto: Rakennus #{id} ({dir}), h = {h:.0f} W/(m²·K) → jäähtyminen',
        
        # Suositukset
        'check_joints': 'Rakennus #{id}: Tarkista {dir}julkisivun saumaukset (ylipaine Cp={cp:.1f})',
        'check_cladding': 'Rakennus #{id}: Tarkista tuulensuojan puoleiset pellitykset (alipaine Cp={cp:.1f})',
        'check_cooling': 'Rakennus #{id}: Huomioi {dir}nurkan jäähtyminen (kondenssi, pakkasvauriot)',
        
        # Osioiden otsikot
        'wind_directions': 'Tuulensuunnat',
        'calculation_area': 'Laskenta-alue',
        'calculation_area_and_grid': 'Laskenta-alue ja hila',
        'grid_comparison': 'Hilavertailu',
        'result_fields': 'Tuloskentät',
        'combined_fields': 'Yhdistetyt kuormituskentät (multi-wind)',
        
        # Kuvatekstit
        'figure': 'Kuva',
        'simulation_wind_direction': 'Simuloinnin tuulensuunta',
        'annual_wind_distribution': 'Paikkakunta - vuotuinen tuulijakauma (FMI)',
        'grid_comparison_coarse_fine': 'Hilavertailu (karkea vs. tiheä)',
        
        # Kriittiset pisteet
        'critical_points_legend': {
            'max_cp': 'Max Cp (ylipaine) - kosteusriski',
            'min_cp': 'Min Cp (alipaine) - imurasitus',
            'max_v': 'Max nopeus - viistosade',
            'max_conv': 'Max konvektio - jäähtyminen',
        },
        
        # Combined-taulukko
        'combined_table': {
            'title': 'Yhdistetyt kuormituskentät',
            'description': 'Yhdistetyt kuormituskentät kokoavat usean tuulensuunnan simulointitulokset yhteen,\njolloin saadaan kokonaiskuva rakennusten vuotuisesta rasituksesta.',
            'field': 'Kenttä',
            'calculation': 'Laskenta',
            'purpose': 'Käyttötarkoitus',
            'scale': 'Asteikko',
            'unit': 'Yksikkö',
            'wdr': 'Kosteusrasitus\n(WDR)',
            'wdr_calc': 'Σ(paino × v × Cp⁺)',
            'wdr_purpose': 'Julkisivun vuotuinen\nsaderasitus',
            'cp_max': 'Kriittinen ylipaine\n(Cp_max)',
            'cp_max_calc': 'max(Cp)',
            'cp_max_purpose': 'Kosteuden tunkeutuminen\nsaumoista ja pellitysten alta',
            'cp_min': 'Kriittinen alipaine\n(Cp_min)',
            'cp_min_calc': 'min(Cp)',
            'cp_min_purpose': 'Imuefekti, kiinnitysten\nrasitus, höyrytiiveys tärkeä',
            'cp_range': 'Paine-ero\n(ΔCp)',
            'cp_range_calc': 'max(Cp) - min(Cp)',
            'cp_range_purpose': 'Saumojen väsymisrasitus,\nhöyrynsulun vauriot',
            'velocity_typical': 'Tuulisuusvyöhykkeet\n(tyypillinen)',
            'velocity_typical_calc': 'Σ(paino × v)',
            'velocity_typical_purpose': 'Jalankulkutason\nviihtyvyys',
            'convection': 'Konvektiivinen\njäähtyminen',
            'convection_calc': 'Σ(paino × √k × v)',
            'convection_purpose': 'Energiankulutus,\nkondenssiriskit',
            'structural': 'Rakenteellinen\nkuormitus',
            'structural_calc': 'max(½ρv²)',
            'structural_purpose': 'Tuulikuorma\nmitoitus',
            'turbulence_intensity': 'Turbulenssi-\nintensiteetti (TI)',
            'turbulence_intensity_calc': 'Σ(paino × √(2k/3)/U)',
            'turbulence_intensity_purpose': 'Dynaamiset kuormat,\njalankulkijaviihtyvyys',
            'u_tau': 'Kitkanopeus\n(u_τ)',
            'u_tau_calc': 'Σ(paino × u_τ)',
            'u_tau_purpose': 'Pinnan lämmönsiirto,\nkosteuden kuivuminen',
        },
        
        # Visualisointien kuvaukset
        'viz_descriptions': {
            'velocity': 'Nopeuskenttä',
            'velocity_streamlines': 'Nopeuskenttä ja virtaviivat',
            'pressure': 'Painekenttä (Cp)',
            'pressure_streamlines': 'Painekenttä ja virtaviivat',
            'comfort': 'Tuulisuusvyöhykkeet (Lawsonin kriteerit)',
            'turbulence_k': 'Turbulenssin kineettinen energia (k)',
            'turbulence_TI': 'Turbulenssi-intensiteetti (TI)',
            'convection': 'Konvektiivinen jäähtyminen (√k × v)',
            'turbulence_nu': 'Turbulentti viskositeetti (ν_t)',
            'turbulence_omega': 'Spesifinen dissipaatio (ω)',
            'u_tau': 'Kitkanopeus (u_τ)',
            'nested_comparison': 'Karkean ja tiheän hilan vertailu',
            'geometry': 'Laskenta-alue ja rakennukset',
        },
        
        # Combined-kuvaukset
        'combined_descriptions': {
            'wdr': ('Julkisivun kosteusrasitus (WDR)', 
                   'Painotettu summa kaikista tuulensuunnista. Korkeat arvot indikoivat alueita,\njoissa julkisivu altistuu suurimmalle saderasitukselle vuoden aikana.'),
            'pressure_max': ('Kriittinen ylipaine (Cp_max)',
                           'Maksimi ylipaine kaikista tuulensuunnista painotettuna tuulen suhteellisella osuudella.\nKorkea ylipaine työntää kosteutta rakenteisiin saumoista ja liitoksista.\nKriittinen tuuletetuilla julkisivuilla.'),
            'pressure_min': ('Kriittinen alipaine (Cp_min)',
                           'Minimi paine (suurin alipaine) kaikista suunnista painotettuna tuulen suhteellisella osuudella.\nAlipaine imee kosteutta rakenteista ja rasittaa pellitysten ja kattorakenteiden kiinnityksiä.'),
            'pressure_range': ('Paine-ero (ΔCp = Cp_max - Cp_min)',
                             'Paine-eron vaihteluväli eri tuulensuunnista. Korkea arvo = alue altistuu sekä\nylipaineelle että alipaineelle → saumojen ja liitosten väsymisrasitus.'),
            'velocity_typical': ('Tuulisuusvyöhykkeet (tyypillinen)',
                               'Painotettu keskiarvo tuulinopeudesta 10m korkeudella.\n'
                               'Lawsonin kriteerit skaalattuna 10m korkeuteen (urbaani maasto, α=0.25):\n'
                               '• Rauhallinen: <2 m/s  • Miellyttävä: 2-4.5 m/s  • Kohtalainen: 4.5-7.5 m/s\n'
                               '• Tuulinen: 7.5-12 m/s  • Epämukava: >12 m/s'),
            'convection': ('Konvektiivinen jäähtyminen',
                         'Painotettu keskiarvo lämmönsiirrosta. Konvektioindeksi (√k × v) kuvaa julkisivun\njäähtymisintensiteettiä yhdistäen turbulenssin ja tuulennopeuden vaikutukset.\nKriittinen energiatehokkuudelle ja kylmäsilloille - korkeat arvot tehostavat\nlämpöhäviötä ja pakkasrapautumisriskiä tuulen puoleisilla julkisivuilla.\n\nHuom: Kasvillisuusalueilla (vihreä) ilma sekoittuu puustossa.\nReunapyörteet voivat tehostaa lähirakennusten jäähtymistä.'),
            'structural': ('Rakenteellinen kuormitus',
                         'Maksimi dynaaminen paine (½ρv²) kaikista suunnista. Käytetään\nrakenteellisessa mitoituksessa - pahin tapaus ratkaisee.'),
            'turbulence_intensity': ('Turbulenssi-intensiteetti (TI)',
                         'Painotettu keskiarvo turbulenssi-intensiteetistä. TI kuvaa tuulen puuskaisuutta\nsuhteessa keskituuleen. Korkeat arvot (>30%) rakennusten nurkilla ja vanoissa\naiheuttavat dynaamisia kuormituksia rakenteille ja epämukavuutta jalankulkijoille.\nEi suoraan korreloi jäähtymisen kanssa - katso konvektioindeksi.\n\nHuom: Kasvillisuusalueilla (vihreä) korkea turbulenssi kuvaa ilman sekoittumista puustossa.'),
            'u_tau': ('Kitkanopeus (u_τ)',
                         'Painotettu keskiarvo kitkanopeudesta. Kitkanopeus on suoraan kytköksissä pinnan\nlämmönsiirtokertoimeen (h ≈ ρ·cp·u_τ/T+) ja kuvaa seinän leikkausjännitystä.\n\n'
                         '• Konvektiivinen lämmönsiirto: Korkea u_τ → tehokkaampi lämmönsiirto pinnan ja ilman välillä\n'
                         '• Kosteuden kuivuminen: Korkea u_τ → nopeampi haihtuminen julkisivulta\n'
                         '• Painejakauma: Korkea u_τ → kiihtynyt virtaus, alipaine'),
        },
        
        # Energiaindeksi
        'energy_index': {
            'title': 'Rakennusten energiaindeksi',
            'description': 'Energiaindeksi kuvaa rakennuksen tuulialtistusta ja sen vaikutusta\nlämmitysenergian tarpeeseen. Indeksi 100 = alueen keskiarvo.\nLaskenta perustuu tuulianalyysistä saatavaan pintojen lämmönsiirtokertoimeen.',
            'table_title': 'Rakennusten energiatehokkuusvertailu',
            'building': 'Rakennus',
            'energy_idx': 'Energia-\nindeksi',
            'heat_loss': 'Suht.\nlämpöhäviö',
            'wind_class': 'Tuuli-\nluokka',
            'mean_conv': 'Keskim.\nkonvektio',
            'recommendation': 'Suositus',
            'classes': {
                'sheltered': 'suojaisa',
                'moderate_shelter': 'koht. suojaisa',
                'average': 'keskimäär.',
                'slightly_exposed': 'hieman tuulinen',
                'exposed': 'tuulinen',
                'very_exposed': 'erit. tuulinen',
            },
            'recommendations': {
                'sheltered': 'Erinomainen sijainti, ei toimenpiteitä',
                'moderate_shelter': 'Hyvä sijainti',
                'average': 'Normaali tilanne',
                'slightly_exposed': 'Normaali, tarkista tiiveys',
                'exposed': 'Harkitse tuulensuojausta',
                'very_exposed': 'Suositellaan tuulensuojausta',
            },
            'notes': [
                '• Energiaindeksi 100 = alueen keskimääräinen rakennus',
                '• Indeksi perustuu konvektiiviseen lämmönsiirtoon julkisivulla',
                '• Suhteellinen lämpöhäviö arvioi tuulen vaikutusta kokonaislämmitystarpeeseen',
                '• Tuulensuojaus voi vähentää lämmityskustannuksia erittäin tuulisilla rakennuksilla (>150)',
                '• Hieman tuulinen (108-125) vastaa tyypillisesti 2-5% lisäystä lämmityskuluissa',
            ],
        },
    },
    
    'en': {
        # Cover page
        'title': 'CFD Wind Analysis',
        'report_created': 'Report created',
        'footer': 'CFD Microclimate Simulation',
        
        # Summary
        'summary': 'Summary',
        'site': 'Site',
        'conclusions': 'Conclusions',
        'critical_buildings': 'Critical Buildings',
        'recommendations': 'Recommendations',
        'building_ids': 'Building Identifiers',
        
        # Analysis texts
        'analyzed_buildings': 'Analyzed {n} buildings with CFD simulation (SST k-ω turbulence model)',
        'max_pressure': 'Highest pressure load: Building #{id} ({dir}), Cp = {cp:.1f} → moisture risk',
        'max_velocity': 'Highest wind speed: Building #{id} ({dir}), v = {v:.1f} m/s → driving rain',
        'max_convection': 'Highest convection: Building #{id} ({dir}) → strong cooling',
        'max_heat_transfer': 'Highest heat transfer: Building #{id} ({dir}), h = {h:.0f} W/(m²·K) → cooling',
        
        # Recommendations
        'check_joints': 'Building #{id}: Check {dir} facade joints (overpressure Cp={cp:.1f})',
        'check_cladding': 'Building #{id}: Check leeward cladding (suction Cp={cp:.1f})',
        'check_cooling': 'Building #{id}: Note {dir} corner cooling (condensation, frost damage)',
        
        # Section titles
        'wind_directions': 'Wind Directions',
        'calculation_area': 'Calculation Domain',
        'calculation_area_and_grid': 'Calculation Domain and Grid',
        'grid_comparison': 'Grid Comparison',
        'result_fields': 'Result Fields',
        'combined_fields': 'Combined Load Fields (multi-wind)',
        
        # Figure captions
        'figure': 'Figure',
        'simulation_wind_direction': 'Simulation wind direction',
        'annual_wind_distribution': 'Location - annual wind distribution (FMI)',
        'grid_comparison_coarse_fine': 'Grid comparison (coarse vs. fine)',
        
        # Critical points legend
        'critical_points_legend': {
            'max_cp': 'Max Cp (overpressure) - moisture risk',
            'min_cp': 'Min Cp (suction) - suction load',
            'max_v': 'Max velocity - driving rain',
            'max_conv': 'Max convection - cooling',
        },
        
        # Combined table
        'combined_table': {
            'title': 'Combined Load Fields',
            'description': 'Combined load fields aggregate simulation results from multiple wind directions,\nproviding an overview of annual building loads.',
            'field': 'Field',
            'calculation': 'Calculation',
            'purpose': 'Purpose',
            'scale': 'Scale',
            'unit': 'Unit',
            'wdr': 'Moisture Load\n(WDR)',
            'wdr_calc': 'Σ(weight × v × Cp⁺)',
            'wdr_purpose': 'Annual facade\nrain exposure',
            'cp_max': 'Critical Overpressure\n(Cp_max)',
            'cp_max_calc': 'max(Cp)',
            'cp_max_purpose': 'Moisture penetration\nthrough joints',
            'cp_min': 'Critical Suction\n(Cp_min)',
            'cp_min_calc': 'min(Cp)',
            'cp_min_purpose': 'Suction effect,\nfastener stress',
            'cp_range': 'Pressure Range\n(ΔCp)',
            'cp_range_calc': 'max(Cp) - min(Cp)',
            'cp_range_purpose': 'Joint fatigue stress,\nvapor barrier damage',
            'velocity_typical': 'Wind Comfort\n(typical)',
            'velocity_typical_calc': 'Σ(weight × v)',
            'velocity_typical_purpose': 'Pedestrian level\ncomfort',
            'convection': 'Convective\nCooling',
            'convection_calc': 'Σ(weight × √k × v)',
            'convection_purpose': 'Energy consumption,\ncondensation risk',
            'structural': 'Structural\nLoading',
            'structural_calc': 'max(½ρv²)',
            'structural_purpose': 'Wind load\ndesign',
            'turbulence_intensity': 'Turbulence\nIntensity (TI)',
            'turbulence_intensity_calc': 'Σ(weight × √(2k/3)/U)',
            'turbulence_intensity_purpose': 'Dynamic loads,\npedestrian comfort',
            'u_tau': 'Friction Velocity\n(u_τ)',
            'u_tau_calc': 'Σ(weight × u_τ)',
            'u_tau_purpose': 'Surface heat transfer,\nmoisture drying',
        },
        
        # Visualization descriptions
        'viz_descriptions': {
            'velocity': 'Velocity field',
            'velocity_streamlines': 'Velocity field with streamlines',
            'pressure': 'Pressure field (Cp)',
            'pressure_streamlines': 'Pressure field with streamlines',
            'comfort': 'Wind comfort zones (Lawson criteria)',
            'turbulence_k': 'Turbulent kinetic energy (k)',
            'turbulence_TI': 'Turbulence intensity (TI)',
            'convection': 'Convective cooling (√k × v)',
            'turbulence_nu': 'Turbulent viscosity (ν_t)',
            'turbulence_omega': 'Specific dissipation (ω)',
            'u_tau': 'Friction velocity (u_τ)',
            'nested_comparison': 'Coarse and fine grid comparison',
            'geometry': 'Calculation domain and buildings',
        },
        
        # Combined descriptions
        'combined_descriptions': {
            'wdr': ('Facade Moisture Load (WDR)', 
                   'Weighted sum from all wind directions. High values indicate areas\nwhere facade is exposed to greatest rain load annually.'),
            'pressure_max': ('Critical Overpressure (Cp_max)',
                           'Maximum overpressure from all directions weighted by relative wind frequency.\nHigh overpressure pushes moisture into structures through joints.\nCritical for ventilated facades.'),
            'pressure_min': ('Critical Suction (Cp_min)',
                           'Minimum pressure (greatest suction) from all directions weighted by relative wind frequency.\nSuction pulls moisture from structures and stresses cladding and roofing fasteners.'),
            'pressure_range': ('Pressure Range (ΔCp = Cp_max - Cp_min)',
                             'Pressure variation range from different wind directions. High value = area exposed\nto both overpressure and suction → fatigue stress on joints and seals.'),
            'velocity_typical': ('Wind Comfort Zones (typical)',
                               'Weighted average wind speed at 10m height.\n'
                               'Lawson criteria scaled to 10m height (urban terrain, α=0.25):\n'
                               '• Calm: <2 m/s  • Pleasant: 2-4.5 m/s  • Moderate: 4.5-7.5 m/s\n'
                               '• Windy: 7.5-12 m/s  • Uncomfortable: >12 m/s'),
            'convection': ('Convective Cooling',
                         'Weighted average of heat transfer. Convection index (√k × v) describes\nfacade cooling intensity combining turbulence and wind speed effects.\nCritical for energy efficiency and thermal bridges - high values enhance\nheat loss and frost damage risk on windward facades.\n\nNote: In vegetation areas (green) air mixes within tree canopy.\nEdge vortices may enhance cooling of nearby buildings.'),
            'structural': ('Structural Loading',
                         'Maximum dynamic pressure (½ρv²) from all directions. Used in\nstructural design - worst case governs.'),
            'turbulence_intensity': ('Turbulence Intensity (TI)',
                         'Weighted average of turbulence intensity. TI describes wind gustiness relative\nto mean speed. High values (>30%) at building corners and wakes cause dynamic\nloads on structures and discomfort for pedestrians.\nDoes not directly correlate with cooling - see convection index.\n\nNote: In vegetation areas (green) high turbulence indicates air mixing within tree canopy.'),
            'u_tau': ('Friction Velocity (u_τ)',
                         'Weighted average of friction velocity. Friction velocity is directly linked to surface\nheat transfer coefficient (h ≈ ρ·cp·u_τ/T+) and describes wall shear stress.\n\n'
                         '• Convective heat transfer: High u_τ → more efficient heat transfer between surface and air\n'
                         '• Moisture drying: High u_τ → faster evaporation from facade\n'
                         '• Pressure distribution: High u_τ → accelerated flow, suction'),
        },
        
        # Energy index
        'energy_index': {
            'title': 'Building Energy Index',
            'description': 'Energy index describes building wind exposure and its effect on\nheating energy demand. Index 100 = area average.\nCalculation is based on surface heat transfer coefficients from wind analysis.',
            'table_title': 'Building Energy Efficiency Comparison',
            'building': 'Building',
            'energy_idx': 'Energy\nIndex',
            'heat_loss': 'Rel.\nHeat Loss',
            'wind_class': 'Wind\nClass',
            'mean_conv': 'Mean\nConvection',
            'recommendation': 'Recommendation',
            'classes': {
                'sheltered': 'sheltered',
                'moderate_shelter': 'mod. sheltered',
                'average': 'average',
                'slightly_exposed': 'slightly exposed',
                'exposed': 'exposed',
                'very_exposed': 'very exposed',
            },
            'recommendations': {
                'sheltered': 'Excellent location, no action needed',
                'moderate_shelter': 'Good location',
                'average': 'Normal situation',
                'slightly_exposed': 'Normal, check sealing',
                'exposed': 'Consider wind protection',
                'very_exposed': 'Wind protection recommended',
            },
            'notes': [
                '• Energy index 100 = average building in the area',
                '• Index based on convective heat transfer at facade',
                '• Relative heat loss estimates wind effect on total heating demand',
                '• Wind protection can reduce heating costs for very exposed buildings (>150)',
                '• Slightly exposed (108-125) typically corresponds to 2-5% increase in heating costs',
            ],
        },
    },
}


def get_text(key: str, lang: str = 'fi', **kwargs) -> str:
    """Hakee käännetyn tekstin."""
    texts = TRANSLATIONS.get(lang, TRANSLATIONS['fi'])
    text = texts.get(key, TRANSLATIONS['fi'].get(key, key))
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, ValueError):
            return text
    return text


def get_nested_text(keys: list, lang: str = 'fi') -> str:
    """Hakee sisäkkäisen käännöksen (esim. ['combined_table', 'field'])."""
    texts = TRANSLATIONS.get(lang, TRANSLATIONS['fi'])
    result = texts
    for key in keys:
        if isinstance(result, dict):
            result = result.get(key, TRANSLATIONS['fi'])
            for k in keys:
                if isinstance(result, dict):
                    result = result.get(k, k)
        else:
            break
    return result if isinstance(result, str) else str(keys[-1])


# Ilmansuuntien käännökset
DIRECTION_TRANSLATIONS = {
    'fi': {
        'north': 'pohjoinen',
        'northeast': 'koillinen',
        'east': 'itä',
        'southeast': 'kaakko',
        'south': 'etelä',
        'southwest': 'lounas',
        'west': 'länsi',
        'northwest': 'luode',
    },
    'en': {
        'north': 'north',
        'northeast': 'northeast',
        'east': 'east',
        'southeast': 'southeast',
        'south': 'south',
        'southwest': 'southwest',
        'west': 'west',
        'northwest': 'northwest',
    }
}


def translate_direction(direction: str, lang: str = 'fi') -> str:
    """Kääntää ilmansuunnan halutulla kielellä."""
    translations = DIRECTION_TRANSLATIONS.get(lang, DIRECTION_TRANSLATIONS['fi'])
    return translations.get(direction.lower(), direction)


def analyze_building_loads(results_dir: Path) -> dict:
    """
    Analysoi rakennuskohtaiset rasitukset numpy-datasta.
    
    Palauttaa dict:n jossa:
    - 'buildings': lista rakennusten tilastoista
    - 'top_pressure': eniten paineelle altistuva rakennus
    - 'top_velocity': eniten tuulelle altistuva rakennus
    - 'top_convection': eniten konvektiolle altistuva rakennus
    - 'critical_points': kriittiset pisteet (nurkat)
    - 'fine_region': tiheän hilan rajat (jos nested)
    - 'has_edge_buildings': onko reunarakennuksia
    """
    try:
        import numpy as np
        from scipy import ndimage
    except ImportError:
        return None
    
    # Tarkista onko kyseessä combined-kansio (multi-wind)
    is_combined = "combined" in str(results_dir)
    
    # Tiheän hilan rajat (nested-simuloinnissa)
    fine_region = None
    
    if is_combined:
        # Combined-kansiossa data on eri muodossa
        combined_data_files = ['X.npy', 'Y.npy', 'pressure_max.npy', 'velocity_weighted.npy', 
                               'solid_mask.npy', 'convection_weighted.npy']
        
        # Etsi data combined/data/ kansiosta
        data_dir = None
        for candidate in [results_dir / 'data', results_dir]:
            if all((candidate / f).exists() for f in combined_data_files):
                data_dir = candidate
                break
        
        if data_dir is None:
            return None
        
        # Lataa combined-datat
        X = np.load(data_dir / 'X.npy')
        Y = np.load(data_dir / 'Y.npy')
        p = np.load(data_dir / 'pressure_max.npy')  # Käytä max painetta
        vel = np.load(data_dir / 'velocity_weighted.npy')  # Painotettu nopeus
        solid_mask = np.load(data_dir / 'solid_mask.npy')
        
        # Konvektio - käytä suoraan jos saatavilla
        conv_file = data_dir / 'convection_weighted.npy'
        if conv_file.exists():
            convection_field = np.load(conv_file)
        else:
            convection_field = vel  # Fallback
        
        # Combined-datassa ei ole k-kenttää erikseen
        k = convection_field / (vel + 1e-10)  # Arvioi k konvektiosta
        k = np.maximum(k, 0) ** 2  # sqrt(k) * v = conv -> k = (conv/v)^2
        
        # Minimi paine (alipaine)
        p_min_file = data_dir / 'pressure_min.npy'
        p_min = np.load(p_min_file) if p_min_file.exists() else p
        
        # Kitkanopeus (painotettu) – saatavilla jos combined_visualizations tallensi sen
        u_tau_file = data_dir / 'u_tau_weighted.npy'
        u_tau = np.load(u_tau_file) if u_tau_file.exists() else None
        omega = None
        
        # Yritä määrittää tiheän hilan rajat combined-tapauksessa
        # Tiheän hilan alue = data-alueen rajat (koska combined data on jo tiheältä hilalta)
        fine_region = {
            'x_min': float(X.min()),
            'x_max': float(X.max()),
            'y_min': float(Y.min()),
            'y_max': float(Y.max()),
        }
        
    else:
        # Normaali single-wind data
        data_files = ['X.npy', 'Y.npy', 'p.npy', 'velocity_magnitude.npy', 'solid_mask.npy', 'k.npy']
        
        # Etsi data joko results_dir/fine/data/, results_dir/fine/, results_dir/data/ tai results_dir/ kansiosta
        data_dir = None
        for candidate in [results_dir / 'fine' / 'data', results_dir / 'fine', 
                          results_dir / 'data', results_dir]:
            if all((candidate / f).exists() for f in data_files):
                data_dir = candidate
                break
        
        if data_dir is None:
            return None
        
        # Lataa datat
        X = np.load(data_dir / 'X.npy')
        Y = np.load(data_dir / 'Y.npy')
        p = np.load(data_dir / 'p.npy')
        vel = np.load(data_dir / 'velocity_magnitude.npy')
        solid_mask = np.load(data_dir / 'solid_mask.npy')
        k = np.load(data_dir / 'k.npy')
        p_min = p  # Sama kenttä
        
        # Lataa u_tau jos saatavilla, muuten laske se k:sta
        u_tau_file = data_dir / 'u_tau.npy'
        if u_tau_file.exists():
            u_tau = np.load(u_tau_file)
        else:
            # Laske u_tau turbulenssikenttien avulla
            # u_tau = C_mu^0.25 * sqrt(k), missä C_mu = 0.09
            C_mu = 0.09
            u_tau = (C_mu ** 0.25) * np.sqrt(k)
        
        # Lataa omega jos saatavilla (tarkempaa lämmönsiirtoanalyysiä varten)
        omega_file = data_dir / 'omega.npy'
        omega = np.load(omega_file) if omega_file.exists() else None
        
        # Määritä tiheän hilan rajat (nested-simuloinnissa fine-kansion data)
        # Tiheän hilan alue = data-alueen rajat
        fine_region = {
            'x_min': float(X.min()),
            'x_max': float(X.max()),
            'y_min': float(Y.min()),
            'y_max': float(Y.max()),
        }
    
    # Yhdistä läheiset rakennusalueet morphological closing -operaatiolla
    # Tämä estää L-muotoisten rakennusten jakautumisen kahdeksi kun hila on karkea
    # Closing = dilation + erosion, yhdistää alueet joiden väli on < structure_size
    dx = abs(X[0, 1] - X[0, 0]) if X.shape[1] > 1 else 0.25
    closing_radius = max(1, int(1.5 / dx))  # ~1.5m säde (yhdistää < 3m välillä olevat)
    structure = ndimage.generate_binary_structure(2, 1)  # 4-connectivity
    # Käytä isompaa structurea lähempien alueiden yhdistämiseen
    structure_large = ndimage.iterate_structure(structure, closing_radius)
    solid_mask_closed = ndimage.binary_closing(solid_mask, structure=structure_large)
    
    # Tunnista yksittäiset rakennukset (suljetusta maskista)
    labeled_buildings, num_buildings = ndimage.label(solid_mask_closed)
    
    if num_buildings == 0:
        return None
    
    # Määritä marginaali reunatarkistukselle (rakennuksen pitää olla tämän verran
    # sisäpuolella ollakseen "luotettava")
    edge_margin = 2.0  # metriä
    
    # Analysoi jokainen rakennus
    building_stats = []
    has_edge_buildings = False
    
    for building_id in range(1, num_buildings + 1):
        bldg_mask = labeled_buildings == building_id
        
        # Laajenna rakennusta löytääksemme reunapikselit
        bldg_dilated = ndimage.binary_dilation(bldg_mask, iterations=2)
        bldg_edges = bldg_dilated & ~solid_mask
        
        if bldg_edges.sum() == 0:
            continue
        
        # Rakennuksen keskipiste ja bounding box
        bldg_coords = np.where(bldg_mask)
        center_x = X[bldg_coords].mean()
        center_y = Y[bldg_coords].mean()
        
        # Rakennuksen bounding box
        bldg_x_coords = X[bldg_coords]
        bldg_y_coords = Y[bldg_coords]
        bldg_x_min = bldg_x_coords.min()
        bldg_x_max = bldg_x_coords.max()
        bldg_y_min = bldg_y_coords.min()
        bldg_y_max = bldg_y_coords.max()
        
        # Tarkista onko rakennus laskenta-alueen reunalla
        # (ei kokonaan tiheän hilan sisällä)
        is_edge_building = False
        if fine_region is not None:
            # Rakennus on reunalla jos sen bounding box on lähellä tiheän hilan reunaa
            if (bldg_x_min < fine_region['x_min'] + edge_margin or
                bldg_x_max > fine_region['x_max'] - edge_margin or
                bldg_y_min < fine_region['y_min'] + edge_margin or
                bldg_y_max > fine_region['y_max'] - edge_margin):
                is_edge_building = True
                has_edge_buildings = True
        
        # Reunojen arvot
        edge_p = p[bldg_edges]
        edge_p_min = p_min[bldg_edges]  # Alipainekenttä (voi olla sama kuin p)
        edge_v = vel[bldg_edges]
        edge_k = k[bldg_edges]
        
        # Etsi maksimien ja minimien sijainnit
        edge_indices = np.where(bldg_edges)
        max_p_local_idx = np.argmax(edge_p)
        min_p_local_idx = np.argmin(edge_p_min)  # Alipaine (imu) - käytä p_min kenttää
        max_v_local_idx = np.argmax(edge_v)
        
        max_p_x = X[edge_indices[0][max_p_local_idx], edge_indices[1][max_p_local_idx]]
        max_p_y = Y[edge_indices[0][max_p_local_idx], edge_indices[1][max_p_local_idx]]
        min_p_x = X[edge_indices[0][min_p_local_idx], edge_indices[1][min_p_local_idx]]
        min_p_y = Y[edge_indices[0][min_p_local_idx], edge_indices[1][min_p_local_idx]]
        max_v_x = X[edge_indices[0][max_v_local_idx], edge_indices[1][max_v_local_idx]]
        max_v_y = Y[edge_indices[0][max_v_local_idx], edge_indices[1][max_v_local_idx]]
        
        # Määritä suunta keskipisteestä maksimiin (kulma)
        def get_direction(cx, cy, px, py):
            """Palauttaa ilmansuunnan englanniksi (käännetään myöhemmin tarvittaessa)."""
            import math
            angle = math.degrees(math.atan2(py - cy, px - cx))
            if -22.5 <= angle < 22.5:
                return "east"
            elif 22.5 <= angle < 67.5:
                return "northeast"
            elif 67.5 <= angle < 112.5:
                return "north"
            elif 112.5 <= angle < 157.5:
                return "northwest"
            elif angle >= 157.5 or angle < -157.5:
                return "west"
            elif -157.5 <= angle < -112.5:
                return "southwest"
            elif -112.5 <= angle < -67.5:
                return "south"
            else:
                return "southeast"
        
        # Etsi turbulenssin maksimin sijainti
        max_k_local_idx = np.argmax(edge_k)
        max_k_x = X[edge_indices[0][max_k_local_idx], edge_indices[1][max_k_local_idx]]
        max_k_y = Y[edge_indices[0][max_k_local_idx], edge_indices[1][max_k_local_idx]]
        
        # Laske konvektioindeksi: yhdistelmä nopeudesta ja turbulenssista
        # Konvektiivinen lämmönsiirtokerroin ~ sqrt(k) * v
        # Tämä kuvaa pinnan jäähtymispotentiaalia
        convection_index = np.sqrt(edge_k) * edge_v
        max_conv_local_idx = np.argmax(convection_index)
        max_conv_x = X[edge_indices[0][max_conv_local_idx], edge_indices[1][max_conv_local_idx]]
        max_conv_y = Y[edge_indices[0][max_conv_local_idx], edge_indices[1][max_conv_local_idx]]
        
        # Kitkanopeus u_tau analyysi (jos saatavilla)
        # u_tau kuvaa suoraan seinän leikkausjännitystä ja lämmönsiirtoa
        # Lämmönsiirtokerroin h ≈ ρ·c_p·u_tau / T+ (Reynolds-analogia)
        if u_tau is not None:
            edge_u_tau = u_tau[bldg_edges]
            max_u_tau_local_idx = np.argmax(edge_u_tau)
            max_u_tau_x = X[edge_indices[0][max_u_tau_local_idx], edge_indices[1][max_u_tau_local_idx]]
            max_u_tau_y = Y[edge_indices[0][max_u_tau_local_idx], edge_indices[1][max_u_tau_local_idx]]
            
            # Arvioi lämmönsiirtokerroin h [W/(m²·K)]
            # h ≈ ρ·c_p·u_tau / T+, missä T+ ≈ 2.5 (Pr=0.7, sileä pinta)
            # ρ ≈ 1.2 kg/m³, c_p ≈ 1005 J/(kg·K)
            rho = 1.2
            c_p = 1005
            T_plus = 2.5
            edge_h = rho * c_p * edge_u_tau / T_plus  # W/(m²·K)
            
            u_tau_stats = {
                'max_u_tau': float(edge_u_tau.max()),
                'mean_u_tau': float(edge_u_tau.mean()),
                'max_u_tau_location': (float(max_u_tau_x), float(max_u_tau_y)),
                'max_u_tau_direction': get_direction(center_x, center_y, max_u_tau_x, max_u_tau_y),
                # Lämmönsiirtokerroin
                'max_h': float(edge_h.max()),
                'mean_h': float(edge_h.mean()),
            }
            
            # Julkisivukohtainen keskimääräinen h (N/E/S/W)
            # Luokittele reunapikselit 4 pääilmansuuntaan keskipisteestä
            import math
            edge_x = X[edge_indices[0], edge_indices[1]]
            edge_y = Y[edge_indices[0], edge_indices[1]]
            facade_h = {'N': [], 'E': [], 'S': [], 'W': []}
            for i in range(len(edge_x)):
                angle = math.degrees(math.atan2(edge_y[i] - center_y, edge_x[i] - center_x))
                if 45 <= angle < 135:
                    facade_h['N'].append(edge_h[i])
                elif -45 <= angle < 45:
                    facade_h['E'].append(edge_h[i])
                elif -135 <= angle < -45:
                    facade_h['S'].append(edge_h[i])
                else:
                    facade_h['W'].append(edge_h[i])
            u_tau_stats['h_per_facade'] = {
                d: float(np.mean(vals)) if vals else None 
                for d, vals in facade_h.items()
            }
        else:
            u_tau_stats = {
                'max_u_tau': None,
                'mean_u_tau': None,
                'max_u_tau_location': None,
                'max_u_tau_direction': None,
                'max_h': None,
                'mean_h': None,
                'h_per_facade': None,
            }
        
        stats = {
            'id': building_id,
            'center_x': center_x,
            'center_y': center_y,
            'area_pixels': int(bldg_mask.sum()),
            'is_edge_building': is_edge_building,  # Onko laskenta-alueen reunalla
            # Paine (ylipaine = kosteuden tunkeutuminen)
            'max_pressure': float(edge_p.max()),
            'min_pressure': float(edge_p_min.min()),  # Käytä p_min kenttää
            'mean_pressure': float(edge_p.mean()),
            'max_p_location': (float(max_p_x), float(max_p_y)),
            'max_p_direction': get_direction(center_x, center_y, max_p_x, max_p_y),
            # Alipaine (imu = pellitysten rasitus)
            'min_p_location': (float(min_p_x), float(min_p_y)),
            'min_p_direction': get_direction(center_x, center_y, min_p_x, min_p_y),
            # Nopeus
            'max_velocity': float(edge_v.max()),
            'mean_velocity': float(edge_v.mean()),
            'max_v_location': (float(max_v_x), float(max_v_y)),
            'max_v_direction': get_direction(center_x, center_y, max_v_x, max_v_y),
            # Turbulenssi (k)
            'max_turbulence_k': float(edge_k.max()),
            'mean_turbulence_k': float(edge_k.mean()),
            'max_k_location': (float(max_k_x), float(max_k_y)),
            'max_k_direction': get_direction(center_x, center_y, max_k_x, max_k_y),
            # Konvektioindeksi (pinnan jäähtyminen/kosteussiirto)
            'max_convection_index': float(convection_index.max()),
            'mean_convection_index': float(convection_index.mean()),
            'max_conv_location': (float(max_conv_x), float(max_conv_y)),
            'max_conv_direction': get_direction(center_x, center_y, max_conv_x, max_conv_y),
            # Kitkanopeus ja lämmönsiirto (wall functions)
            **u_tau_stats,
        }
        building_stats.append(stats)
    
    if not building_stats:
        return None
    
    # Järjestä eri kriteerien mukaan
    by_pressure = sorted(building_stats, key=lambda x: x['max_pressure'], reverse=True)
    by_velocity = sorted(building_stats, key=lambda x: x['max_velocity'], reverse=True)
    by_turbulence = sorted(building_stats, key=lambda x: x['max_turbulence_k'], reverse=True)
    by_convection = sorted(building_stats, key=lambda x: x['max_convection_index'], reverse=True)
    
    # u_tau järjestys (jos saatavilla)
    if building_stats[0].get('max_u_tau') is not None:
        by_heat_transfer = sorted(building_stats, key=lambda x: x['max_h'] or 0, reverse=True)
    else:
        by_heat_transfer = []
    
    return {
        'buildings': building_stats,
        'num_buildings': num_buildings,
        'top_pressure': by_pressure[:5],
        'top_velocity': by_velocity[:5],
        'top_turbulence': by_turbulence[:5],
        'top_convection': by_convection[:5],
        'top_heat_transfer': by_heat_transfer[:5] if by_heat_transfer else None,
        'global_max_pressure': max(b['max_pressure'] for b in building_stats),
        'global_max_velocity': max(b['max_velocity'] for b in building_stats),
        'global_max_turbulence': max(b['max_turbulence_k'] for b in building_stats),
        'global_max_convection': max(b['max_convection_index'] for b in building_stats),
        'has_wall_functions': building_stats[0].get('max_u_tau') is not None,
        'has_edge_buildings': has_edge_buildings,  # Onko reunarakennuksia
        'fine_region': fine_region,  # Tiheän hilan rajat
        'data_dir': data_dir,
    }


def add_building_ids_to_image(img_path: Path, output_path: Path, building_analysis: dict) -> bool:
    """
    Lisää rakennusten ID-numerot olemassa olevaan kuvaan.
    
    Args:
        img_path: Alkuperäisen kuvan polku
        output_path: Tuloskuvan polku
        building_analysis: analyze_building_loads() palauttama dict
    
    Returns:
        True jos onnistui, False muuten
    """
    try:
        import numpy as np
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return False
    
    if not img_path.exists() or building_analysis is None:
        return False
    
    # Lataa kuva
    img = Image.open(img_path)
    draw = ImageDraw.Draw(img)
    
    # Yritä ladata fontti
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 14)
        font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 10)
    except:
        font = ImageFont.load_default()
        font_small = font
    
    # Lataa koordinaattidata skaalauksen laskemiseen
    data_dir = building_analysis.get('data_dir')
    if data_dir is None:
        return False
    
    X = np.load(data_dir / 'X.npy')
    Y = np.load(data_dir / 'Y.npy')
    
    # Kuvan koko ja datan koko
    img_width, img_height = img.size
    data_height, data_width = X.shape
    
    # Laske skaalaus (oletetaan että kuva vastaa dataa)
    # Huom: matplotlib-kuvissa on marginaalit, arvioidaan ne
    margin_left = int(img_width * 0.10)
    margin_right = int(img_width * 0.88)
    margin_bottom = int(img_height * 0.88)
    margin_top = int(img_height * 0.10)
    
    plot_width = margin_right - margin_left
    plot_height = margin_bottom - margin_top
    
    x_min, x_max = X.min(), X.max()
    y_min, y_max = Y.min(), Y.max()
    
    def data_to_pixel(data_x, data_y):
        """Muuntaa datakoordinaatit pikselikoordinaateiksi."""
        px = margin_left + (data_x - x_min) / (x_max - x_min) * plot_width
        # Y-akseli on käännetty kuvassa
        py = margin_bottom - (data_y - y_min) / (y_max - y_min) * plot_height
        return int(px), int(py)
    
    # Piirrä ID-numerot rakennusten keskipisteisiin
    for bldg in building_analysis['buildings']:
        cx, cy = data_to_pixel(bldg['center_x'], bldg['center_y'])
        
        # Piirrä tausta ID:lle (parempi näkyvyys)
        text = f"#{bldg['id']}"
        bbox = draw.textbbox((cx, cy), text, font=font)
        padding = 2
        draw.rectangle(
            [bbox[0] - padding, bbox[1] - padding, bbox[2] + padding, bbox[3] + padding],
            fill='white',
            outline='black'
        )
        draw.text((cx, cy), text, fill='black', font=font, anchor='mm')
    
    # Tallenna
    img.save(output_path)
    return True


def create_building_id_overlay(results_dir: Path, building_analysis: dict) -> Path:
    """
    Luo erillinen kuva jossa näkyy rakennusten ID-numerot ja kriittiset pisteet.
    
    Returns:
        Polku luotuun kuvaan tai None jos epäonnistui
    """
    try:
        import numpy as np
        from scipy import ndimage
    except ImportError:
        return None
    
    if building_analysis is None:
        return None
    
    data_dir = building_analysis.get('data_dir')
    if data_dir is None:
        return None
    
    # Tarkista onko kyseessä combined-data
    is_combined = "combined" in str(data_dir) or (data_dir / 'convection_weighted.npy').exists()
    
    # Lataa datat
    try:
        X = np.load(data_dir / 'X.npy')
        Y = np.load(data_dir / 'Y.npy')
        solid_mask = np.load(data_dir / 'solid_mask.npy')
        
        if is_combined:
            # Combined-data: käytä convection_weighted suoraan
            conv_file = data_dir / 'convection_weighted.npy'
            if conv_file.exists():
                convection = np.load(conv_file)
            else:
                vel = np.load(data_dir / 'velocity_weighted.npy')
                convection = vel
        else:
            vel = np.load(data_dir / 'velocity_magnitude.npy')
            k = np.load(data_dir / 'k.npy')
            convection = np.sqrt(k) * vel
    except FileNotFoundError as e:
        print(f"  Varoitus: Building ID overlay data puuttuu: {e}")
        return None
    
    convection[solid_mask] = np.nan
    
    # Lataa porous_mask (metsäalueet) jos saatavilla
    porous_mask = None
    porous_mask_file = data_dir / 'porous_mask.npy'
    if porous_mask_file.exists():
        porous_mask = np.load(porous_mask_file)
    
    # Lataa porous_zones.json (metsäalueiden polygonit) - tarkemmat reunat
    porous_zones = []
    porous_zones_paths = [
        data_dir / 'porous_zones.json',
        data_dir.parent / 'porous_zones.json',
        results_dir / 'porous_zones.json',
    ]
    
    # Combined-kansiossa etsi myös wind-kansioista
    if is_combined:
        parent_dir = data_dir.parent.parent  # combined/data -> combined -> parent
        wind_dirs = sorted(parent_dir.glob("wind_*"))
        for wind_dir in wind_dirs:
            porous_zones_paths.append(wind_dir / 'fine' / 'porous_zones.json')
            porous_zones_paths.append(wind_dir / 'porous_zones.json')
    
    for pz_path in porous_zones_paths:
        if pz_path.exists():
            import json
            with open(pz_path, 'r') as f:
                porous_zones = json.load(f)
            break
    
    # Luo kuva
    fig, ax = plt.subplots(figsize=(10, 10))
    
    # Piirrä konvektioindeksi taustalle (kuvaa pinnan jäähtymistä)
    conv_max = np.nanpercentile(convection, 98)
    im = ax.pcolormesh(X, Y, convection, cmap='YlOrRd', shading='auto', 
                       alpha=0.8, vmin=0, vmax=conv_max)
    
    # Piirrä kasvillisuusalueet ENSIN (jotta rakennukset piirtyvät päälle)
    # Metsät vihreällä, pellot kellertävällä
    # Ensisijaisesti käytä porous_zones polygoneja (tarkemmat reunat)
    if porous_zones:
        from matplotlib.patches import Polygon as MplPolygon
        for zone in _sort_zones_for_drawing(porous_zones):
            if 'vertices' in zone:
                verts = np.array(zone['vertices'])
                # Väri kasvillisuustyypin mukaan
                veg_type = zone.get('vegetation_type', zone.get('type', 'tree_zone'))
                facecolor, edgecolor, is_hard = _get_vegetation_color(veg_type)
                zone_alpha = 0.85 if is_hard else 0.6
                poly = MplPolygon(verts, facecolor=facecolor, edgecolor=edgecolor,
                                 linewidth=1, alpha=zone_alpha)
                ax.add_patch(poly)
    elif porous_mask is not None and porous_mask.any():
        # Fallback: käytä porous_mask:ia (sahalaitaiset reunat)
        ax.contourf(X, Y, porous_mask.astype(int), levels=[0.5, 1.5], 
                   colors=['#228b22'], alpha=0.6)
    
    # Piirrä rakennukset - käytä polygoneja jos saatavilla
    # Etsi buildings.json useasta paikasta (combined-datassa voi olla eri paikassa)
    buildings_file = None
    buildings_search_paths = [
        data_dir / 'buildings.json',                    # data/ -kansio
        data_dir.parent / 'buildings.json',             # combined/ -kansio
        results_dir / 'buildings.json',                 # results_dir
    ]
    
    # Combined-kansiossa etsi myös yksittäisten wind-kansioiden alta
    if is_combined:
        parent_dir = data_dir.parent.parent  # combined/data -> combined -> parent
        wind_dirs = sorted(parent_dir.glob("wind_*"))
        for wind_dir in wind_dirs:
            buildings_search_paths.append(wind_dir / 'fine' / 'buildings.json')
            buildings_search_paths.append(wind_dir / 'buildings.json')
    
    for search_path in buildings_search_paths:
        if search_path.exists():
            buildings_file = search_path
            break
    
    if buildings_file and buildings_file.exists():
        import json
        from matplotlib.patches import Polygon as MplPolygon
        
        with open(buildings_file, 'r') as f:
            buildings_data = json.load(f)
        
        # Käsittele mahdollinen dict-muoto
        if isinstance(buildings_data, dict):
            buildings_data = buildings_data.get('buildings', [])
        
        for bldg_data in buildings_data:
            # Suodata pois metsäalueet (tree_zone, vegetation_zone) - piirretään vain rakennukset
            bldg_type = bldg_data.get('type', 'building')
            is_solid = bldg_data.get('is_solid', True)
            
            # Ohita huokoiset esteet (metsät, kasvillisuus)
            if bldg_type in ['tree_zone', 'vegetation_zone', 'tree'] or not is_solid:
                continue
            
            if 'vertices' in bldg_data and bldg_data['vertices']:
                # Käytä polygonia
                poly = MplPolygon(bldg_data['vertices'], 
                                 facecolor='#404040', edgecolor='black',
                                 linewidth=1.5, alpha=0.95)
                ax.add_patch(poly)
            elif 'x_min' in bldg_data:
                # Fallback suorakaiteeseen
                from matplotlib.patches import Rectangle
                rect = Rectangle(
                    (bldg_data['x_min'], bldg_data['y_min']),
                    bldg_data['x_max'] - bldg_data['x_min'],
                    bldg_data['y_max'] - bldg_data['y_min'],
                    facecolor='#404040', edgecolor='black',
                    linewidth=1.5, alpha=0.95
                )
                ax.add_patch(rect)
    else:
        # Fallback: käytä solid_mask (sahalaitaiset reunat)
        ax.contourf(X, Y, solid_mask.astype(int), levels=[0.5, 1.5], colors=['#404040'], alpha=0.95)
    
    # Laske sopiva merkkikoko rakennusten koon perusteella
    # Käytetään rakennuksen "halkaisijaa" (sqrt(area)) skaalaamaan merkkejä
    def get_marker_size(bldg, base_size=8, min_size=5, max_size=18):
        """Laskee merkkikoon rakennuksen koon perusteella."""
        # Laske rakennuksen koko pikselien perusteella
        area_pixels = bldg.get('area_pixels', 100)
        
        # Muunna pikselit metreiksi (approx)
        dx = X[0, 1] - X[0, 0] if X.shape[1] > 1 else 1.0
        dy = Y[1, 0] - Y[0, 0] if Y.shape[0] > 1 else 1.0
        area_m2 = area_pixels * dx * dy
        
        # Rakennuksen "halkaisija" metreinä
        diameter = np.sqrt(area_m2)
        
        # Skaalaa merkkikoko: pienemmät rakennukset -> pienemmät merkit
        # Käytetään log-skaalaa tasaisempaan jakaumaan
        # Oletus: 10m rakennus -> base_size, skaalataan siitä
        scale = np.log10(max(diameter, 1)) / np.log10(10)  # 10m = 1.0
        size = base_size * (0.6 + 0.4 * scale)
        
        return np.clip(size, min_size, max_size)
    
    # Tarkista onko reunarakennuksia
    has_edge_buildings = building_analysis.get('has_edge_buildings', False)
    
    # Apufunktio: laske rakennuksen halkaisija metreinä
    def get_building_diameter(bldg):
        """Laskee rakennuksen arvioitu halkaisija metreinä."""
        area_pixels = bldg.get('area_pixels', 100)
        dx = X[0, 1] - X[0, 0] if X.shape[1] > 1 else 1.0
        dy = Y[1, 0] - Y[0, 0] if Y.shape[0] > 1 else 1.0
        area_m2 = area_pixels * abs(dx * dy)
        return np.sqrt(area_m2)
    
    # Apufunktio: laske ID:n sijainti pienille rakennuksille
    def get_id_position(bldg, critical_points, font_size):
        """
        Laskee ID-numeron sijainnin. Pienillä rakennuksilla siirtää ID:n ulkopuolelle.
        
        Args:
            bldg: Rakennuksen tiedot
            critical_points: Lista kriittisten pisteiden sijainneista [(x,y), ...]
            font_size: Fonttikoko
            
        Returns:
            (x, y, offset_applied) - koordinaatit ja tieto siirrettiinkö ID:tä
        """
        center_x = bldg['center_x']
        center_y = bldg['center_y']
        diameter = get_building_diameter(bldg)
        
        # Arvioi ID-tekstin koko metreinä (approx)
        # Kuvan skaalasta riippuen: fonttikoko 10 vastaa n. 3-5 metriä tyypillisessä kuvassa
        # Käytetään kuvan mittakaavaa
        x_range = X.max() - X.min()
        y_range = Y.max() - Y.min()
        
        # Arvioidaan että 10pt fontti vie noin 1/100 kuvan leveydestä
        # ID-tekstin leveys on noin 3-4 merkkiä (#XX)
        text_width_m = (font_size / 10) * (x_range / 80) * 4  # 4 merkkiä leveä teksti
        text_height_m = (font_size / 10) * (y_range / 80) * 1.5
        
        # Jos rakennuksen halkaisija on pienempi kuin ID-laatikon leveys * 1.5, siirretään ID ulos
        min_diameter_for_inside = text_width_m * 1.8
        
        if diameter >= min_diameter_for_inside:
            # Rakennus on riittävän iso - ID keskelle
            return center_x, center_y, False
        
        # Rakennus on pieni - siirretään ID ulkopuolelle
        # Valitaan paras suunta joka ei osu kriittisiin pisteisiin
        
        # Siirtoetäisyys: rakennuksen säde + tekstin leveys/2 + marginaali
        offset_dist = diameter / 2 + text_width_m / 2 + text_width_m * 0.3
        
        # Kandidaattisuunnat (oikea, ylä, vasen, ala, ja diagonaalit)
        candidates = [
            (offset_dist, 0),                    # oikea
            (0, offset_dist),                    # ylä
            (-offset_dist, 0),                   # vasen
            (0, -offset_dist),                   # ala
            (offset_dist * 0.7, offset_dist * 0.7),    # yläoikea
            (-offset_dist * 0.7, offset_dist * 0.7),   # ylävasen
            (offset_dist * 0.7, -offset_dist * 0.7),   # alaoikea
            (-offset_dist * 0.7, -offset_dist * 0.7),  # alavasen
        ]
        
        # Laske etäisyys kriittisiin pisteisiin jokaiselle kandidaatille
        best_pos = candidates[0]
        best_min_dist = 0
        
        for dx, dy in candidates:
            new_x = center_x + dx
            new_y = center_y + dy
            
            # Laske minimietäisyys kriittisiin pisteisiin
            min_dist_to_critical = float('inf')
            for cp in critical_points:
                if cp is not None:
                    dist = np.sqrt((new_x - cp[0])**2 + (new_y - cp[1])**2)
                    min_dist_to_critical = min(min_dist_to_critical, dist)
            
            # Valitse sijainti joka on kauimpana kriittisistä pisteistä
            if min_dist_to_critical > best_min_dist:
                best_min_dist = min_dist_to_critical
                best_pos = (dx, dy)
        
        return center_x + best_pos[0], center_y + best_pos[1], True
    
    # Apufunktio: ratkaise ID-laatikoiden päällekkäisyydet
    def resolve_id_overlaps(buildings, X, Y):
        """
        Ratkaisee ID-laatikoiden päällekkäisyydet siirtämällä päällekkäisiä ID:itä.
        
        Returns:
            Dict[id: (x, y, was_offset, leader_target)] - jokaisen ID:n lopullinen sijainti
        """
        x_range = X.max() - X.min()
        y_range = Y.max() - Y.min()
        
        # Arvioi ID-laatikon koko metreinä (approx)
        box_width = (x_range / 80) * 5   # ~5 merkkiä leveä (#XX)
        box_height = (y_range / 80) * 2  # korkeus
        
        # Laske ensin oletussijainnit
        positions = {}
        for bldg in buildings:
            bldg_id = bldg['id']
            
            # Hae kriittisten pisteiden sijainnit
            critical_pts = [
                bldg.get('max_p_location'),
                bldg.get('min_p_location'),
                bldg.get('max_v_location'),
                bldg.get('max_conv_location'),
            ]
            
            font_size = max(8, min(14, get_marker_size(bldg) * 1.2))
            x, y, was_offset = get_id_position(bldg, critical_pts, font_size)
            
            positions[bldg_id] = {
                'x': x, 'y': y, 
                'was_offset': was_offset,
                'center_x': bldg['center_x'],
                'center_y': bldg['center_y'],
                'diameter': get_building_diameter(bldg)
            }
        
        # Tarkista päällekkäisyydet ja siirrä
        def boxes_overlap(pos1, pos2, margin=0.3):
            """Tarkistaa menevätkö kaksi ID-laatikkoa päällekkäin."""
            dx = abs(pos1['x'] - pos2['x'])
            dy = abs(pos1['y'] - pos2['y'])
            return dx < box_width * (1 + margin) and dy < box_height * (1 + margin)
        
        # Iteroi kunnes ei päällekkäisyyksiä (max 10 kierrosta)
        for iteration in range(10):
            overlaps_found = False
            ids = list(positions.keys())
            
            for i, id1 in enumerate(ids):
                for id2 in ids[i+1:]:
                    pos1 = positions[id1]
                    pos2 = positions[id2]
                    
                    if boxes_overlap(pos1, pos2):
                        overlaps_found = True
                        
                        # Siirrä pienempi/myöhempi rakennus
                        # Priorisoi: isompi halkaisija pysyy paikallaan
                        if pos1['diameter'] >= pos2['diameter']:
                            move_id = id2
                        else:
                            move_id = id1
                        
                        pos_to_move = positions[move_id]
                        center_x = pos_to_move['center_x']
                        center_y = pos_to_move['center_y']
                        
                        # Kokeile eri suuntia
                        offset_dist = box_width * 1.5
                        candidates = [
                            (offset_dist, offset_dist * 0.5),    # yläoikea
                            (-offset_dist, offset_dist * 0.5),   # ylävasen
                            (offset_dist, -offset_dist * 0.5),   # alaoikea
                            (-offset_dist, -offset_dist * 0.5),  # alavasen
                            (offset_dist * 1.2, 0),              # oikea
                            (-offset_dist * 1.2, 0),             # vasen
                            (0, offset_dist),                    # ylä
                            (0, -offset_dist),                   # ala
                        ]
                        
                        # Etsi paras sijainti joka ei osu muihin
                        best_pos = None
                        best_min_dist = -1
                        
                        for dx, dy in candidates:
                            new_x = center_x + dx
                            new_y = center_y + dy
                            
                            # Laske minimietäisyys muihin ID-laatikoihin
                            min_dist = float('inf')
                            for other_id, other_pos in positions.items():
                                if other_id != move_id:
                                    dist = np.sqrt((new_x - other_pos['x'])**2 + (new_y - other_pos['y'])**2)
                                    min_dist = min(min_dist, dist)
                            
                            if min_dist > best_min_dist:
                                best_min_dist = min_dist
                                best_pos = (new_x, new_y)
                        
                        if best_pos:
                            positions[move_id]['x'] = best_pos[0]
                            positions[move_id]['y'] = best_pos[1]
                            positions[move_id]['was_offset'] = True
            
            if not overlaps_found:
                break
        
        return positions
    
    # Ratkaise ID-laatikoiden päällekkäisyydet ENNEN piirtoa
    id_positions = resolve_id_overlaps(building_analysis['buildings'], X, Y)
    
    # Selvitä näkymärajat etukäteen (tarvitaan reunarakennusten ID:iden suodatukseen)
    fine_region_cp = building_analysis.get('fine_region')
    if fine_region_cp:
        cp_margin = 10
        cp_xmin = fine_region_cp['x_min'] - cp_margin
        cp_xmax = fine_region_cp['x_max'] + cp_margin
        cp_ymin = fine_region_cp['y_min'] - cp_margin
        cp_ymax = fine_region_cp['y_max'] + cp_margin
    else:
        cp_xmin, cp_xmax = float(X.min()), float(X.max())
        cp_ymin, cp_ymax = float(Y.min()), float(Y.max())
    cp_id_margin_x = (cp_xmax - cp_xmin) * 0.03
    cp_id_margin_y = (cp_ymax - cp_ymin) * 0.03
    
    # Lisää ID-numerot ja kriittiset pisteet
    for bldg in building_analysis['buildings']:
        is_edge = bldg.get('is_edge_building', False)
        
        # Laske merkkikoko tälle rakennukselle
        marker_size = get_marker_size(bldg)
        edge_width = max(1, marker_size / 8)
        
        # Fonttikoko (skaalattu rakennuksen mukaan)
        font_size = max(8, min(14, marker_size * 1.2))
        
        # Hae ID:n sijainti esikäsitellystä listasta (päällekkäisyydet ratkaistu)
        bldg_id = bldg['id']
        id_pos = id_positions.get(bldg_id, {})
        id_x = id_pos.get('x', bldg['center_x'])
        id_y = id_pos.get('y', bldg['center_y'])
        id_was_offset = id_pos.get('was_offset', False)
        
        # Ohita ID jos se ei mahdu näkymään (reunarakennukset)
        if (id_x < cp_xmin + cp_id_margin_x or id_x > cp_xmax - cp_id_margin_x or
                id_y < cp_ymin + cp_id_margin_y or id_y > cp_ymax - cp_id_margin_y):
            continue
        
        # Jos ID siirrettiin, piirrä ohut viiva rakennuksen keskipisteeseen
        if id_was_offset:
            ax.plot([bldg['center_x'], id_x], [bldg['center_y'], id_y], 
                    color='#555555', linewidth=0.8, linestyle='-', alpha=0.7, zorder=1)
        
        # ID-numero (keskipisteeseen tai siirrettyyn sijaintiin)
        # Reunarakennuksilla eri tyyli (harmaampi, katkoviiva)
        # Korkeimmalla rakennuksella kultainen kehys
        is_highest = bldg.get('is_highest', False)
        height_advantage = bldg.get('height_advantage', 0)
        mml_height = bldg.get('mml_height')
        
        id_text = f"#{bldg['id']}*" if is_edge else f"#{bldg['id']}"
        
        if is_highest and mml_height:
            # Korkein rakennus: kultainen kehys ja korkeustieto
            height_text = f"{mml_height:.0f}m"
            ax.annotate(
                id_text, 
                (id_x, id_y),
                fontsize=font_size, fontweight='bold',
                ha='center', va='center',
                color='white',
                bbox=dict(boxstyle='round,pad=0.3', facecolor='#B8860B', 
                         edgecolor='gold', linewidth=2, alpha=0.95),
                zorder=12
            )
            # Lisää korkeustieto ID:n alapuolelle
            ax.annotate(
                f"↑ {height_text}",
                (id_x, id_y - font_size * 0.8),
                fontsize=font_size * 0.7, fontweight='bold',
                ha='center', va='top',
                color='gold',
                bbox=dict(boxstyle='round,pad=0.15', facecolor='#333333', 
                         edgecolor='gold', linewidth=1, alpha=0.9),
                zorder=11
            )
        elif is_edge:
            # Reunarakennukset: harmaampi tausta ja katkoviiva
            ax.annotate(
                id_text, 
                (id_x, id_y),
                fontsize=font_size, fontweight='bold',
                ha='center', va='center',
                color='white',
                bbox=dict(boxstyle='round,pad=0.3', facecolor='#666666', 
                         edgecolor='white', alpha=0.8, linestyle='dashed'),
                zorder=10
            )
        else:
            ax.annotate(
                id_text, 
                (id_x, id_y),
                fontsize=font_size, fontweight='bold',
                ha='center', va='center',
                color='white',
                bbox=dict(boxstyle='round,pad=0.3', facecolor='#333333', edgecolor='white', alpha=0.9),
                zorder=10
            )
        
        # Hae kriittisten pisteiden sijainnit
        p_loc = np.array(bldg['max_p_location'])
        v_loc = np.array(bldg['max_v_location'])
        c_loc = np.array(bldg['max_conv_location'])
        center = np.array([bldg['center_x'], bldg['center_y']])
        
        # Laske etäisyydet pisteiden välillä
        # Jos pisteet ovat liian lähellä toisiaan, siirretään niitä erilleen
        min_dist = marker_size * 0.15  # Minimietäisyys metreinä (skaalattu merkkikoon mukaan)
        
        def offset_if_close(loc1, loc2, center, min_dist):
            """Siirtää loc2:ta poispäin loc1:stä jos ne ovat liian lähellä."""
            dist = np.linalg.norm(loc2 - loc1)
            if dist < min_dist and dist > 0.01:
                # Siirretään poispäin rakennuksen keskipisteestä
                direction = loc2 - center
                if np.linalg.norm(direction) > 0.01:
                    direction = direction / np.linalg.norm(direction)
                else:
                    direction = np.array([1, 0])
                return loc2 + direction * min_dist
            elif dist < 0.01:
                # Pisteet samassa paikassa - siirretään kohtisuoraan
                direction = loc2 - center
                if np.linalg.norm(direction) > 0.01:
                    # Kohtisuora suunta
                    perp = np.array([-direction[1], direction[0]])
                    perp = perp / np.linalg.norm(perp)
                else:
                    perp = np.array([1, 0])
                return loc2 + perp * min_dist
            return loc2
        
        # Siirretään nopeuspistettä jos se on liian lähellä painepistettä
        v_loc_adj = offset_if_close(p_loc, v_loc, center, min_dist)
        
        # Siirretään konvektiopistettä jos se on liian lähellä kumpaakaan
        c_loc_adj = offset_if_close(p_loc, c_loc, center, min_dist)
        c_loc_adj = offset_if_close(v_loc_adj, c_loc_adj, center, min_dist)
        
        # Alipaineen sijainti (imu)
        min_p_loc = bldg.get('min_p_location', center)
        min_p_loc_adj = offset_if_close(p_loc, min_p_loc, center, min_dist)
        min_p_loc_adj = offset_if_close(v_loc_adj, min_p_loc_adj, center, min_dist)
        min_p_loc_adj = offset_if_close(c_loc_adj, min_p_loc_adj, center, min_dist)
        
        # Merkitse maksimipainepiste (punainen kolmio ylös) - ylipaine/kosteusriski
        ax.plot(p_loc[0], p_loc[1], 
                '^', color='#d62728', markersize=marker_size, 
                markeredgecolor='white', markeredgewidth=edge_width)
        
        # Merkitse minimipainepiste (syaani kolmio alas) - alipaine/imu
        ax.plot(min_p_loc_adj[0], min_p_loc_adj[1], 
                'v', color='#17becf', markersize=marker_size * 0.9, 
                markeredgecolor='white', markeredgewidth=edge_width)
        
        # Merkitse maksiminopeuspiste (tummansininen neliö)
        ax.plot(v_loc_adj[0], v_loc_adj[1], 
                's', color='#1f77b4', markersize=marker_size * 0.9, 
                markeredgecolor='white', markeredgewidth=edge_width)
        
        # Merkitse maksimikonvektiopiste (magenta/violetti timantti) - pinnan jäähtyminen
        ax.plot(c_loc_adj[0], c_loc_adj[1], 
                'D', color='#9467bd', markersize=marker_size * 0.85, 
                markeredgecolor='white', markeredgewidth=edge_width)
        
        # Merkitse maksilämmönsiirtopiste (oranssi tähti) - jos wall functions saatavilla
        h_loc_raw = bldg.get('max_u_tau_location')
        if h_loc_raw is not None and bldg.get('max_h') is not None:
            h_loc = np.array(h_loc_raw)
            h_loc_adj = offset_if_close(p_loc, h_loc, center, min_dist)
            h_loc_adj = offset_if_close(v_loc_adj, h_loc_adj, center, min_dist)
            h_loc_adj = offset_if_close(c_loc_adj, h_loc_adj, center, min_dist)
            h_loc_adj = offset_if_close(min_p_loc_adj, h_loc_adj, center, min_dist)
            ax.plot(h_loc_adj[0], h_loc_adj[1], 
                    '*', color='#ff7f0e', markersize=marker_size * 1.1, 
                    markeredgecolor='white', markeredgewidth=edge_width)
    
    # Lisää selite kuvan alalaitaan
    ax.plot([], [], '^', color='#d62728', markersize=10, markeredgecolor='white', 
            markeredgewidth=1.5, label='Max Cp (ylipaine) - kosteusriski')
    ax.plot([], [], 'v', color='#17becf', markersize=9, markeredgecolor='white', 
            markeredgewidth=1.5, label='Min Cp (alipaine) - imurasitus')
    ax.plot([], [], 's', color='#1f77b4', markersize=9, markeredgecolor='white', 
            markeredgewidth=1.5, label='Max nopeus - viistosade')
    ax.plot([], [], 'D', color='#9467bd', markersize=8, markeredgecolor='white', 
            markeredgewidth=1.5, label='Max konvektioindeksi (CI) – jäähtyminen')
    
    # Lisää lämmönsiirtoselite jos wall functions käytössä
    has_wall_funcs = building_analysis.get('has_wall_functions', False)
    if has_wall_funcs:
        ax.plot([], [], '*', color='#ff7f0e', markersize=10, markeredgecolor='white',
                markeredgewidth=1.5, label='Max lämmönsiirto h – W/(m²·K)')
    
    # Lisää huomautus reunarakennuksista jos niitä on
    if has_edge_buildings:
        ax.plot([], [], 's', color='#666666', markersize=8, markeredgecolor='white',
                markeredgewidth=1, linestyle='--', label='* Reunalla - suuntaa-antava')
    
    # Lisää huomautus korkeimmasta rakennuksesta jos sellainen löytyi
    has_highest = any(b.get('is_highest', False) for b in building_analysis['buildings'])
    if has_highest:
        ax.plot([], [], 's', color='#B8860B', markersize=8, markeredgecolor='gold',
                markeredgewidth=2, label='↑ Alueen korkein (MML)')
    
    # Laske legendin sarakkeet
    legend_items = 4  # Perussymbolit
    if has_edge_buildings:
        legend_items += 1
    if has_highest:
        legend_items += 1
    ncol = min(3, legend_items)
    
    ax.legend(loc='upper center', bbox_to_anchor=(0.5, -0.05), ncol=ncol, 
              fontsize=8, frameon=True, fancybox=True, shadow=True)
    
    ax.set_xlabel('x [m]')
    ax.set_ylabel('y [m]')
    ax.set_title('Rakennusten tunnisteet ja kriittiset pisteet', fontsize=12, fontweight='bold')
    ax.set_aspect('equal')
    
    # Rajaa kuva tiheän hilan alueelle (fine_region) - rakennukset näkyvät isompina
    fine_region = building_analysis.get('fine_region')
    if fine_region:
        margin = 10  # metriä marginaalia reunoille
        ax.set_xlim(fine_region['x_min'] - margin, fine_region['x_max'] + margin)
        ax.set_ylim(fine_region['y_min'] - margin, fine_region['y_max'] + margin)
    
    # Colorbar
    cbar = plt.colorbar(im, ax=ax, shrink=0.8)
    cbar.set_label('Konvektioindeksi √k·v (pinnan jäähtyminen)')
    
    # Tallenna - lisää tilaa alareunaan selitteelle
    plt.tight_layout()
    output_path = results_dir / 'building_ids.png'
    plt.savefig(output_path, dpi=REPORT_DPI, bbox_inches='tight')
    
    # Tallenna myös korkealla resoluutiolla erilliseen tiedostoon
    high_res_path = results_dir / 'kriittiset_pisteet.png'
    plt.savefig(high_res_path, dpi=300, bbox_inches='tight')
    print(f"  ✓ Kriittiset pisteet (300 dpi): {high_res_path.name}")
    
    plt.close(fig)
    
    return output_path


def create_target_building_detail(results_dir: Path, building_analysis: dict, margin: float = 10.0) -> Path:
    """
    Luo lähikuva kohderakennuksesta (is_target) kriittisine pisteineen.
    
    Näyttää vain kohderakennuksen ja sen välittömän ympäristön (margin metriä),
    isommilla symboleilla ja tarkemmilla annotaatioilla kuin yleiskuva.
    
    Args:
        results_dir: Tuloskansion polku
        building_analysis: Rakennusanalyysin tulokset
        margin: Marginaali kohderakennuksen ympärillä [m]
        
    Returns:
        Polku luotuun kuvaan tai None jos kohderakennusta ei löydy
    """
    try:
        import numpy as np
        from matplotlib.patches import Polygon as MplPolygon, FancyArrowPatch
    except ImportError:
        return None
    
    if building_analysis is None:
        return None
    
    # Etsi kohderakennus (is_target)
    target_bldg = None
    for bldg in building_analysis.get('buildings', []):
        if bldg.get('is_target', False):
            target_bldg = bldg
            break
    
    if target_bldg is None:
        print("  ℹ️ Kohderakennusta (is_target) ei löytynyt - ohitetaan lähikuva")
        return None
    
    data_dir = building_analysis.get('data_dir')
    if data_dir is None:
        return None
    
    # Lataa datat
    try:
        X = np.load(data_dir / 'X.npy')
        Y = np.load(data_dir / 'Y.npy')
        solid_mask = np.load(data_dir / 'solid_mask.npy')
        
        is_combined = "combined" in str(data_dir) or (data_dir / 'convection_weighted.npy').exists()
        
        if is_combined:
            conv_file = data_dir / 'convection_weighted.npy'
            if conv_file.exists():
                convection = np.load(conv_file)
            else:
                convection = np.load(data_dir / 'velocity_weighted.npy')
        else:
            vel = np.load(data_dir / 'velocity_magnitude.npy')
            k = np.load(data_dir / 'k.npy')
            convection = np.sqrt(k) * vel
    except FileNotFoundError as e:
        print(f"  Varoitus: Target detail data puuttuu: {e}")
        return None
    
    convection[solid_mask] = np.nan
    
    # Kohderakennuksen rajat
    if 'vertices' in target_bldg and target_bldg['vertices']:
        verts = np.array(target_bldg['vertices'])
        bldg_xmin, bldg_ymin = verts.min(axis=0)
        bldg_xmax, bldg_ymax = verts.max(axis=0)
    elif 'x_min' in target_bldg:
        bldg_xmin = target_bldg['x_min']
        bldg_xmax = target_bldg['x_max']
        bldg_ymin = target_bldg['y_min']
        bldg_ymax = target_bldg['y_max']
    else:
        # Fallback: arvioi rajat keskipisteestä ja pikselipinta-alasta
        cx = target_bldg['center_x']
        cy = target_bldg['center_y']
        # Arvioi koko pinta-alasta (neliöapproksimaatio)
        area_px = target_bldg.get('area_pixels', 100)
        # Hila-askel datasta
        dx_grid = abs(X[0, 1] - X[0, 0]) if X.shape[1] > 1 else 1.0
        half_side = np.sqrt(area_px) * dx_grid / 2
        half_side = max(half_side, 5.0)  # Vähintään 5m
        bldg_xmin = cx - half_side
        bldg_xmax = cx + half_side
        bldg_ymin = cy - half_side
        bldg_ymax = cy + half_side
    
    # Kuvan rajat = rakennus + margin
    view_xmin = bldg_xmin - margin
    view_xmax = bldg_xmax + margin
    view_ymin = bldg_ymin - margin
    view_ymax = bldg_ymax + margin
    
    bldg_width = bldg_xmax - bldg_xmin
    bldg_height = bldg_ymax - bldg_ymin
    
    # Luo kuva - aspect ratio rakennuksen mukaan
    view_w = view_xmax - view_xmin
    view_h = view_ymax - view_ymin
    fig_w = max(8, min(12, 8 * view_w / max(view_h, 1)))
    fig_h = max(8, min(12, 8 * view_h / max(view_w, 1)))
    fig, ax = plt.subplots(figsize=(fig_w, fig_h))
    
    # Piirrä konvektioindeksi taustalle
    conv_max = np.nanpercentile(convection, 98)
    im = ax.pcolormesh(X, Y, convection, cmap='YlOrRd', shading='auto',
                       alpha=0.8, vmin=0, vmax=conv_max)
    
    # Piirrä kasvillisuus (porous_zones)
    porous_zones = []
    porous_zones_paths = [
        data_dir / 'porous_zones.json',
        data_dir.parent / 'porous_zones.json',
        results_dir / 'porous_zones.json',
    ]
    if is_combined:
        parent_dir = data_dir.parent.parent
        for wind_dir in sorted(parent_dir.glob("wind_*")):
            porous_zones_paths.append(wind_dir / 'fine' / 'porous_zones.json')
            porous_zones_paths.append(wind_dir / 'porous_zones.json')
    
    for pz_path in porous_zones_paths:
        if pz_path.exists():
            import json
            with open(pz_path, 'r') as f:
                porous_zones = json.load(f)
            break
    
    if porous_zones:
        for zone in _sort_zones_for_drawing(porous_zones):
            if 'vertices' in zone:
                zone_verts = np.array(zone['vertices'])
                veg_type = zone.get('vegetation_type', zone.get('type', 'tree_zone'))
                facecolor, edgecolor, is_hard = _get_vegetation_color(veg_type)
                zone_alpha = 0.85 if is_hard else 0.6
                poly = MplPolygon(zone_verts, facecolor=facecolor, edgecolor=edgecolor,
                                 linewidth=1, alpha=zone_alpha)
                ax.add_patch(poly)
    
    # Piirrä kaikki rakennukset alueella
    buildings_file = None
    buildings_search_paths = [
        data_dir / 'buildings.json',
        data_dir.parent / 'buildings.json',
        results_dir / 'buildings.json',
    ]
    if is_combined:
        parent_dir = data_dir.parent.parent
        for wind_dir in sorted(parent_dir.glob("wind_*")):
            buildings_search_paths.append(wind_dir / 'fine' / 'buildings.json')
            buildings_search_paths.append(wind_dir / 'buildings.json')
    
    for search_path in buildings_search_paths:
        if search_path.exists():
            buildings_file = search_path
            break
    
    if buildings_file and buildings_file.exists():
        import json
        with open(buildings_file, 'r') as f:
            buildings_data = json.load(f)
        if isinstance(buildings_data, dict):
            buildings_data = buildings_data.get('buildings', [])
        
        for bldg_data in buildings_data:
            bldg_type = bldg_data.get('type', 'building')
            is_solid = bldg_data.get('is_solid', True)
            if bldg_type in ['tree_zone', 'vegetation_zone', 'tree'] or not is_solid:
                continue
            
            # Kohderakennus korostettu, muut himmeämpiä
            is_this_target = bldg_data.get('is_target', False)
            
            if 'vertices' in bldg_data and bldg_data['vertices']:
                if is_this_target:
                    # Kohderakennus: tumma täyttö, paksu punainen reunus
                    poly = MplPolygon(bldg_data['vertices'],
                                     facecolor='#505050', edgecolor='#c0392b',
                                     linewidth=3.0, alpha=0.95, zorder=5)
                else:
                    # Muut rakennukset: himmeämpi
                    poly = MplPolygon(bldg_data['vertices'],
                                     facecolor='#707070', edgecolor='#555555',
                                     linewidth=1.0, alpha=0.7, zorder=4)
                ax.add_patch(poly)
            elif 'x_min' in bldg_data:
                from matplotlib.patches import Rectangle
                fc = '#505050' if is_this_target else '#707070'
                ec = '#c0392b' if is_this_target else '#555555'
                lw = 3.0 if is_this_target else 1.0
                al = 0.95 if is_this_target else 0.7
                rect = Rectangle(
                    (bldg_data['x_min'], bldg_data['y_min']),
                    bldg_data['x_max'] - bldg_data['x_min'],
                    bldg_data['y_max'] - bldg_data['y_min'],
                    facecolor=fc, edgecolor=ec, linewidth=lw, alpha=al,
                    zorder=5 if is_this_target else 4)
                ax.add_patch(rect)
    else:
        ax.contourf(X, Y, solid_mask.astype(int), levels=[0.5, 1.5],
                   colors=['#404040'], alpha=0.95)
    
    # === Kriittiset pisteet (isot symbolit + älykkäät annotaatiot) ===
    center = np.array([target_bldg['center_x'], target_bldg['center_y']])
    ms = 16  # Iso merkkikoko
    ew = 2.0  # Paksu reunaviiva
    
    # Kriittiset sijainnit
    p_loc = np.array(target_bldg['max_p_location'])
    min_p_loc = np.array(target_bldg.get('min_p_location', center))
    v_loc = np.array(target_bldg['max_v_location'])
    c_loc = np.array(target_bldg['max_conv_location'])
    
    # Arvot annotaatioihin (huom: kenttänimet analyze_building_loads:sta)
    p_val = target_bldg.get('max_pressure', target_bldg.get('max_pressure_coeff', 0))
    min_p_val = target_bldg.get('min_pressure', target_bldg.get('min_pressure_coeff', 0))
    v_val = target_bldg.get('max_velocity', 0)
    conv_val = target_bldg.get('max_convection_index', target_bldg.get('max_convection', 0))
    h_val = target_bldg.get('max_h')  # W/(m²·K), None jos ei wall functions
    h_loc_raw = target_bldg.get('max_u_tau_location')
    
    # Rakennuksen puolidiagonaali - tämä kertoo kuinka kaukana reunat oikeasti ovat
    bldg_half_diag = np.sqrt(bldg_width**2 + bldg_height**2) / 2
    
    # Rakennuksen verteksit polygoni-tarkistukseen (tukee rotated-rakennuksia)
    from matplotlib.path import Path as MplPath
    bldg_polygon = None
    if 'vertices' in target_bldg and target_bldg['vertices']:
        bldg_polygon = MplPath(np.array(target_bldg['vertices']))
    
    # ---- Älykäs label-sijoittelu ----
    # Laske preferred_angle automaattisesti: suunta keskipisteestä → kriittinen piste
    def outward_angle(loc):
        """Laske ulossuuntainen kulma rakennuksen keskipisteestä."""
        dx = loc[0] - center[0]
        dy = loc[1] - center[1]
        if abs(dx) < 0.01 and abs(dy) < 0.01:
            return 0  # Fallback jos piste on keskellä
        return np.degrees(np.arctan2(dy, dx)) % 360
    
    critical_items = [
        {'name': 'Cp+', 'loc': p_loc, 'text': f'Cp+ = {p_val:.2f} [-]', 
         'color': '#d62728', 'marker': '^', 'ms_factor': 1.0,
         'preferred_angle': outward_angle(p_loc)},
        {'name': 'Cp-', 'loc': min_p_loc, 'text': f'Cp- = {min_p_val:.2f} [-]', 
         'color': '#17becf', 'marker': 'v', 'ms_factor': 0.95,
         'preferred_angle': outward_angle(min_p_loc)},
        {'name': 'v', 'loc': v_loc, 'text': f'v = {v_val:.1f} m/s', 
         'color': '#1f77b4', 'marker': 's', 'ms_factor': 0.95,
         'preferred_angle': outward_angle(v_loc)},
        {'name': 'CI', 'loc': c_loc, 'text': f'CI = {conv_val:.2f}', 
         'color': '#9467bd', 'marker': 'D', 'ms_factor': 0.9,
         'preferred_angle': outward_angle(c_loc)},
    ]
    
    # Lisää lämmönsiirtopiste jos wall functions -data saatavilla
    if h_val is not None and h_loc_raw is not None:
        h_loc = np.array(h_loc_raw)
        critical_items.append(
            {'name': 'h', 'loc': h_loc, 'text': f'h = {h_val:.0f} W/(m²·K)', 
             'color': '#ff7f0e', 'marker': '*', 'ms_factor': 1.1,
             'preferred_angle': outward_angle(h_loc)}
        )
    
    # Arvioi label-laatikon koko metreinä (näkymän suhteen)
    label_w = view_w * 0.16  # ~16% näkymän leveydestä (huomioi pitkät tekstit kuten "Cp- = -0.33 [-]")
    label_h = view_h * 0.06  # ~6% näkymän korkeudesta
    
    # Kandidaattikulmat (24 suuntaa, 15° välein → tarkempi sijoittelu)
    candidate_angles = list(range(0, 360, 15))
    
    # Useita etäisyyksiä: kokeile myös kauempia sijoituksia
    min_offset = bldg_half_diag * 0.5 + 3.0   # Vähimmäisetäisyys keskipisteestä
    base_offset = bldg_half_diag * 0.7 + 4.0  # Perusetäisyys
    far_offset = bldg_half_diag * 0.9 + 5.0   # Kaukainen vaihtoehto
    candidate_offsets = [base_offset, far_offset, min_offset]
    
    # Suojavyöhyke rakennuksen ympärillä (metreinä)
    bldg_clearance = label_w * 0.6 + 1.5  # Label-leveys + marginaali
    
    def label_box_overlaps(x1, y1, x2, y2, w, h, margin_factor=0.25):
        """Tarkista ovatko kaksi label-laatikkoa päällekkäin."""
        return (abs(x1 - x2) < w * (1 + margin_factor) and 
                abs(y1 - y2) < h * (1 + margin_factor))
    
    def label_on_building(lx, ly):
        """Tarkista osuuko label kohderakennuksen päälle tai liian lähelle.
        Käyttää polygonia jos saatavilla (tukee rotated-rakennuksia)."""
        # Tarkista label-laatikon 4 kulmapistettä + keskipiste
        hw, hh = label_w * 0.55, label_h * 0.55
        test_points = [
            (lx, ly), (lx - hw, ly - hh), (lx + hw, ly - hh),
            (lx - hw, ly + hh), (lx + hw, ly + hh),
        ]
        if bldg_polygon is not None:
            # Polygoni + clearance: laajennetaan tarkistusta
            for tx, ty in test_points:
                if bldg_polygon.contains_point((tx, ty)):
                    return True
            # Lisäksi: etäisyys polygonin reunasta
            # Arvioidaan bounding box + clearance
            return (lx > bldg_xmin - bldg_clearance and lx < bldg_xmax + bldg_clearance and
                    ly > bldg_ymin - bldg_clearance and ly < bldg_ymax + bldg_clearance and
                    bldg_polygon.contains_point((lx, ly)))
        else:
            # Axis-aligned bounding box + clearance
            return (lx > bldg_xmin - bldg_clearance and lx < bldg_xmax + bldg_clearance and
                    ly > bldg_ymin - bldg_clearance and ly < bldg_ymax + bldg_clearance)
    
    def label_near_building(lx, ly):
        """Tarkista onko label-laatikko lähellä rakennusta (pehmeä sakko)."""
        hw, hh = label_w * 0.55, label_h * 0.55
        expanded_clearance = bldg_clearance + 2.0  # Pehmeämpi vyöhyke
        if bldg_polygon is not None:
            corners = [(lx - hw, ly - hh), (lx + hw, ly - hh),
                       (lx - hw, ly + hh), (lx + hw, ly + hh)]
            for cx, cy in corners:
                if bldg_polygon.contains_point((cx, cy)):
                    return True
        return (lx > bldg_xmin - expanded_clearance and lx < bldg_xmax + expanded_clearance and
                ly > bldg_ymin - expanded_clearance and ly < bldg_ymax + expanded_clearance)
    
    def label_in_view(lx, ly):
        """Tarkista onko label kokonaan näkymäalueen sisällä (riittävällä marginaalilla)."""
        return (lx > view_xmin + label_w * 0.6 and lx < view_xmax - label_w * 0.85 and
                ly > view_ymin + label_h * 0.8 and ly < view_ymax - label_h * 0.8)
    
    # Kerää kaikkien markkerien sijainnit (label ei saa peittää näitä)
    all_marker_locs = [(item['loc'][0], item['loc'][1]) for item in critical_items]
    marker_radius = max(view_w, view_h) * 0.025
    
    # Laske optimaaliset label-sijainnit iteratiivisesti
    placed_labels = []  # [(x, y), ...]
    
    # Varaa h-taulukon alue (oikea yläkulma) jos se piirretään
    h_per_facade = target_bldg.get('h_per_facade')
    if h_per_facade is not None:
        # Taulukon koko akseli-koordinaateissa: ~18% leveydestä, ~20% korkeudesta
        # Sijainti oikea yläkulma → data-koordinaatit
        box_w = view_w * 0.18
        box_h = view_h * 0.20
        box_cx = view_xmax - box_w * 0.6   # Keskipiste x
        box_cy = view_ymax - box_h * 0.55  # Keskipiste y
        # Lisää useita pisteitä kattamaan taulukon alue
        placed_labels.append((box_cx, box_cy))
        placed_labels.append((box_cx - box_w * 0.3, box_cy))
        placed_labels.append((box_cx + box_w * 0.3, box_cy))
    
    for item in critical_items:
        loc = item['loc']
        preferred = item['preferred_angle']
        
        best_pos = None
        best_score = -float('inf')
        
        # Kokeile useita etäisyyksiä ja kulmia
        for off_dist in candidate_offsets:
            for angle in candidate_angles:
                rad = np.radians(angle)
                # Offset RAKENNUKSEN KESKIPISTEESTÄ ulossuuntaan
                # (ei kriittisestä pisteestä, koska piste on rakennuksen reunalla)
                lx = loc[0] + off_dist * np.cos(rad)
                ly = loc[1] + off_dist * np.sin(rad)
                
                # Pisteytys
                score = 0
                
                # 1. Onko näkymän sisällä? (erittäin kova rangaistus)
                if not label_in_view(lx, ly):
                    score -= 500
                
                # 2. Onko rakennuksen päällä tai liian lähellä? (erittäin kova rangaistus)
                if label_on_building(lx, ly):
                    score -= 300
                elif label_near_building(lx, ly):
                    score -= 80  # Pehmeä sakko lähelle jäämisestä
                
                # 3. Minimietäisyys jo sijoitettuihin labeleihin
                min_label_dist = float('inf')
                for (px, py) in placed_labels:
                    if label_box_overlaps(lx, ly, px, py, label_w, label_h):
                        score -= 300  # Iso sakko päällekkäisyydestä
                    dist = np.sqrt((lx - px)**2 + (ly - py)**2)
                    min_label_dist = min(min_label_dist, dist)
                
                # 4. Etäisyysbonus (kauempana muista labeleista = parempi)
                if min_label_dist < float('inf'):
                    score += min(min_label_dist / label_w, 3.0) * 10
                else:
                    score += 30  # Ensimmäinen label
                
                # 5. Bonus preferred-kulmalle (ulossuunta keskipisteestä)
                angle_diff = min(abs(angle - preferred), 360 - abs(angle - preferred))
                score += max(0, 15 - angle_diff / 12)
                
                # 6. Sakko jos label-bbox peittää minkä tahansa markkerin symbolin
                for (mx, my) in all_marker_locs:
                    if (abs(lx - mx) < label_w * 0.55 + marker_radius and
                            abs(ly - my) < label_h * 0.55 + marker_radius):
                        score -= 80
                
                # 7. Pieni bonus lyhyemmälle nuolelle (estetiikka)
                arrow_len = np.sqrt((lx - loc[0])**2 + (ly - loc[1])**2)
                score += max(0, 5 - arrow_len / view_w * 10)
                
                if score > best_score:
                    best_score = score
                    best_pos = (lx, ly)
        
        if best_pos is None:
            # Fallback: preferred angle, kaukaisella offsetilla
            rad = np.radians(preferred)
            best_pos = (loc[0] + far_offset * np.cos(rad), loc[1] + far_offset * np.sin(rad))
        
        # Clip näkymärajoihin (huomioidaan label-laatikon koko + mittakaavapalkki alh. vas.)
        clip_xmin = view_xmin + label_w * 0.65
        clip_xmax = view_xmax - label_w * 0.85  # Isompi marginaali oikealle (colorbar vie tilaa)
        clip_ymin = view_ymin + label_h * 1.0   # Mittakaavapalkki alavasemmalla
        clip_ymax = view_ymax - label_h * 0.85
        # Varaa h-taulukon alue oikeasta yläkulmasta
        if h_per_facade is not None:
            table_zone_xmin = view_xmax - view_w * 0.22
            table_zone_ymin = view_ymax - view_h * 0.26
            bx, by = best_pos
            if bx > table_zone_xmin and by > table_zone_ymin:
                # Siirrä pois taulukon alta
                clip_xmax = table_zone_xmin - label_w * 0.3
        text_x = np.clip(best_pos[0], clip_xmin, clip_xmax)
        text_y = np.clip(best_pos[1], clip_ymin, clip_ymax)
        
        placed_labels.append((text_x, text_y))
        item['label_pos'] = (text_x, text_y)
    
    # Piirrä kaikki kriittiset pisteet symboleilla ja optimoiduilla labeleilla
    for item in critical_items:
        loc = item['loc']
        lx, ly = item['label_pos']
        
        # Symboli (zorder=25: aina labeleiden päällä, ei peity)
        ax.plot(loc[0], loc[1], item['marker'], color=item['color'], 
                markersize=ms * item['ms_factor'],
                markeredgecolor='white', markeredgewidth=ew, zorder=25)
        
        # Annotaatio optimoidussa sijainnissa
        ax.annotate(
            item['text'], xy=(loc[0], loc[1]), xytext=(lx, ly),
            fontsize=9, fontweight='bold', color='white',
            bbox=dict(boxstyle='round,pad=0.4', facecolor=item['color'], 
                     edgecolor='white', alpha=0.95, linewidth=1.5),
            arrowprops=dict(arrowstyle='->', color=item['color'], lw=2.0,
                          connectionstyle='arc3,rad=0.15'),
            zorder=20
        )
    
    # ID-numero keskelle rakennusta
    bldg_id = target_bldg.get('id', '?')
    bldg_name = target_bldg.get('name', '')
    id_label = f"#{bldg_id}"
    if bldg_name:
        id_label += f"\n{bldg_name}"
    
    ax.annotate(
        id_label, (center[0], center[1]),
        fontsize=12, fontweight='bold', ha='center', va='center',
        color='white',
        bbox=dict(boxstyle='round,pad=0.4', facecolor='#c0392b',
                 edgecolor='white', linewidth=2, alpha=0.95),
        zorder=18
    )
    
    # Mittakaavapalkki
    scale_len = 5.0  # 5m
    if view_w > 40:
        scale_len = 10.0
    scale_x = view_xmin + 1.5
    scale_y = view_ymin + 1.5
    ax.plot([scale_x, scale_x + scale_len], [scale_y, scale_y],
            'k-', linewidth=3, zorder=20)
    ax.plot([scale_x, scale_x], [scale_y - 0.3, scale_y + 0.3],
            'k-', linewidth=2, zorder=20)
    ax.plot([scale_x + scale_len, scale_x + scale_len], [scale_y - 0.3, scale_y + 0.3],
            'k-', linewidth=2, zorder=20)
    ax.text(scale_x + scale_len / 2, scale_y + 0.8, f'{scale_len:.0f} m',
            ha='center', va='bottom', fontsize=9, fontweight='bold',
            bbox=dict(boxstyle='round,pad=0.2', facecolor='white', alpha=0.8),
            zorder=20)
    
    # Selite
    ax.plot([], [], '^', color='#d62728', markersize=12, markeredgecolor='white',
            markeredgewidth=1.5, label='Max Cp (ylipaine) – kosteusriski')
    ax.plot([], [], 'v', color='#17becf', markersize=11, markeredgecolor='white',
            markeredgewidth=1.5, label='Min Cp (alipaine) – imurasitus')
    ax.plot([], [], 's', color='#1f77b4', markersize=11, markeredgecolor='white',
            markeredgewidth=1.5, label='Max nopeus – viistosade')
    ax.plot([], [], 'D', color='#9467bd', markersize=10, markeredgecolor='white',
            markeredgewidth=1.5, label='Max konvektioindeksi (CI) – jäähtyminen')
    if h_val is not None:
        ax.plot([], [], '*', color='#ff7f0e', markersize=12, markeredgecolor='white',
                markeredgewidth=1.5, label='Max lämmönsiirto h – W/(m²·K)')
    
    ax.legend(loc='upper center', bbox_to_anchor=(0.5, -0.05), ncol=2,
              fontsize=9, frameon=True, fancybox=True, shadow=True)
    
    # Julkisivukohtainen h-taulukko (oikea yläkulma)
    h_per_facade = target_bldg.get('h_per_facade')
    if h_per_facade is not None:
        facade_labels = {'N': 'P', 'E': 'I', 'S': 'E', 'W': 'L'}  # fi: pohjoinen, itä, etelä, länsi
        lines = ['h̄ W/(m²·K):']
        for d in ['N', 'E', 'S', 'W']:
            val = h_per_facade.get(d)
            if val is not None:
                lines.append(f'  {facade_labels[d]}: {val:.0f}')
            else:
                lines.append(f'  {facade_labels[d]}: –')
        facade_text = '\n'.join(lines)
        ax.text(0.98, 0.98, facade_text, transform=ax.transAxes,
                fontsize=8, fontfamily='monospace', va='top', ha='right',
                multialignment='left',
                bbox=dict(boxstyle='round,pad=0.4', facecolor='white', 
                         edgecolor='#ff7f0e', linewidth=1.5, alpha=0.9),
                zorder=20)
    
    # Akselit ja otsikko
    ax.set_xlim(view_xmin, view_xmax)
    ax.set_ylim(view_ymin, view_ymax)
    ax.set_xlabel('x [m]')
    ax.set_ylabel('y [m]')
    ax.set_title(f'Kohderakennus #{bldg_id} – kriittiset pisteet (lähikuva)',
                 fontsize=13, fontweight='bold')
    ax.set_aspect('equal')
    
    # Colorbar
    cbar = plt.colorbar(im, ax=ax, shrink=0.8)
    cbar.set_label('Konvektioindeksi √k·v')
    
    # Tallenna
    plt.tight_layout()
    output_path = results_dir / 'target_detail.png'
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    print(f"  ✓ Kohderakennuksen lähikuva (300 dpi): {output_path.name}")
    
    plt.close(fig)
    return output_path


def find_images(results_dir: Path, pattern: str = "*.png") -> List[Path]:
    """Etsii kuvat hakemistosta."""
    images = list(results_dir.glob(pattern))
    return sorted(images)


def load_comfort_report(results_dir: Path) -> dict:
    """Lataa tuulisuusraportin tiedot."""
    report_data = {}
    
    # Yritä ladata nested-raportti ensin
    report_file = results_dir / "comfort_report_nested.txt"
    if not report_file.exists():
        report_file = results_dir / "comfort_report.txt"
    
    if report_file.exists():
        with open(report_file, 'r', encoding='utf-8') as f:
            content = f.read()
            report_data['content'] = content
            
            # Parsitaan perustiedot
            for line in content.split('\n'):
                if line.startswith('Tapaus:'):
                    report_data['name'] = line.split(':', 1)[1].strip()
                elif line.startswith('Kuvaus:'):
                    report_data['description'] = line.split(':', 1)[1].strip()
                elif line.startswith('Turbulenssimalli:'):
                    report_data['turbulence_model'] = line.split(':', 1)[1].strip()
    
    return report_data


def generate_wind_rose(geometry_path: Path, output_path: Path, results_dir: Path = None) -> bool:
    """
    Generoi tuuliruusu simuloinnin tuulensuunnasta.
    
    Piirtää yksinkertaisen tuuliruusun joka näyttää simuloinnin tuulen suunnan.
    
    Args:
        geometry_path: Geometriatiedosto josta luetaan tuulen suunta (fallback)
        output_path: Tuloskuvan polku
        results_dir: Tuloshakemisto josta luetaan domain.json (prioriteetti)
        
    Returns:
        True jos onnistui
    """
    import json
    import numpy as np
    
    inlet_velocity = 5.0
    inlet_direction = 0.0
    
    # Prioriteetti 1: Lue tuloshakemiston domain.json (multi-wind)
    if results_dir:
        # Kokeile fine/ ensin (nested grid)
        domain_paths = [
            results_dir / 'fine' / 'domain.json',
            results_dir / 'domain.json',
        ]
        for domain_path in domain_paths:
            if domain_path.exists():
                try:
                    with open(domain_path, 'r', encoding='utf-8') as f:
                        domain_data = json.load(f)
                    inlet_direction = domain_data.get('inlet_direction', inlet_direction)
                    inlet_velocity = domain_data.get('inlet_velocity', inlet_velocity)
                    print(f"  Tuuliruusu: luettu {domain_path.name} (dir={inlet_direction}°)")
                    break
                except Exception:
                    pass
    
    # Prioriteetti 2: Lue geometriatiedostosta (fallback)
    if inlet_direction == 0.0 and geometry_path and Path(geometry_path).exists():
        try:
            with open(geometry_path, 'r', encoding='utf-8') as f:
                geom_data = json.load(f)
            bc = geom_data.get('boundary_conditions', {})
            inlet_velocity = bc.get('inlet_velocity', inlet_velocity)
            inlet_direction = bc.get('inlet_direction', inlet_direction)
        except Exception as e:
            print(f"  Varoitus: Geometriatiedoston lukeminen epäonnistui: {e}")
    
    # Muunna CFD-suunta (0=idästä) meteorologiseksi (0=pohjoisesta)
    # CFD: 0° = virtaus itään, 90° = virtaus pohjoiseen
    # Tuulee päinvastaisesta suunnasta: meteo = (270 - cfd + 360) % 360
    meteo_direction = (270 - inlet_direction + 360) % 360
    
    # Tuulen suunta tarkoittaa "mistä tuulee", joten nuoli osoittaa minne tuuli menee
    # Nuolen suunta = meteo_direction + 180
    arrow_direction = (meteo_direction + 180) % 360
    
    # Suunnan nimi
    direction_names = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE',
                       'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW']
    sector_idx = int((meteo_direction + 11.25) % 360 / 22.5)
    direction_name = direction_names[sector_idx]
    
    # Luo tuuliruusu - pienempi koko sopimaan raporttiin
    fig, ax = plt.subplots(subplot_kw={'projection': 'polar'}, figsize=(5, 5))
    
    # Aseta pohjoinen ylös
    ax.set_theta_zero_location('N')
    ax.set_theta_direction(-1)  # Myötäpäivään
    
    # Piirrä kompassiruusu taustalle
    n_sectors = 16
    angles = np.linspace(0, 2 * np.pi, n_sectors, endpoint=False)
    
    # Taustasektorit
    width = 2 * np.pi / n_sectors
    for i, angle in enumerate(angles):
        color = '#e0e0e0' if i % 2 == 0 else '#f5f5f5'
        ax.bar(angle, 1, width=width, bottom=0, color=color, edgecolor='#cccccc', linewidth=0.5)
    
    # Tuulen suunta - pääsektori korostettuna
    wind_angle_rad = np.radians(meteo_direction)
    ax.bar(wind_angle_rad, 1, width=width, bottom=0, color='#3498db', 
           edgecolor='#2980b9', linewidth=2, alpha=0.8)
    
    # Nuoli osoittamaan tuulen suuntaa (mihin tuuli puhaltaa)
    arrow_rad = np.radians(arrow_direction)
    ax.annotate('', xy=(arrow_rad, 0.7), xytext=(arrow_rad, 0.1),
                arrowprops=dict(arrowstyle='->', color='#e74c3c', lw=3))
    
    # Suuntanimet
    ax.set_xticks(np.linspace(0, 2 * np.pi, 8, endpoint=False))
    ax.set_xticklabels(['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'], fontsize=10)
    
    # Poista säteen asteikko
    ax.set_yticks([])
    ax.set_ylim(0, 1.1)
    
    # Otsikko ja tiedot
    ax.set_title(f'Simuloinnin tuulensuunta\nTuulee {direction_name}:stä ({meteo_direction:.0f}°), {inlet_velocity:.1f} m/s',
                 fontsize=12, fontweight='bold', pad=20)
    
    # Selite
    ax.text(0.5, -0.12, f'CFD inlet_direction: {inlet_direction:.0f}° (virtauksen suunta)\n'
                        f'Meteorologinen: {meteo_direction:.0f}° (mistä tuulee)',
            transform=ax.transAxes, ha='center', fontsize=9, color='#666666')
    
    plt.tight_layout()
    
    try:
        plt.savefig(output_path, dpi=REPORT_DPI, bbox_inches='tight', facecolor='white')
        plt.close(fig)
        return True
    except Exception as e:
        print(f"  Varoitus: Tuuliruusun tallennus epäonnistui: {e}")
        plt.close(fig)
        return False


def generate_multi_wind_rose(simulations: list, output_path: Path, title: str = "Multi-wind") -> bool:
    """
    Generoi tuuliruusu joka näyttää kaikki simuloidut tuulensuunnat.
    
    Args:
        simulations: Lista simuloinneista [{'direction_name': 'S', 'inlet_direction': 90, 'weight': 0.1}, ...]
        output_path: Tuloskuvan polku
        title: Otsikko
        
    Returns:
        True jos onnistui
    """
    import numpy as np
    
    if not simulations:
        return False
    
    # Luo kuva
    fig, ax = plt.subplots(subplot_kw={'projection': 'polar'}, figsize=(6, 6))
    
    # Aseta pohjoinen ylös
    ax.set_theta_zero_location('N')
    ax.set_theta_direction(-1)  # Myötäpäivään
    
    # Piirrä kompassiruusu taustalle (vaalea)
    n_sectors = 16
    angles = np.linspace(0, 2 * np.pi, n_sectors, endpoint=False)
    sector_width = 2 * np.pi / n_sectors
    
    for i, angle in enumerate(angles):
        color = '#f5f5f5' if i % 2 == 0 else '#fafafa'
        ax.bar(angle, 1.0, width=sector_width, bottom=0, color=color, edgecolor='#e0e0e0', linewidth=0.5)
    
    # Värit suunnille - selkeästi erottuvat
    colors = ['#e74c3c', '#3498db', '#27ae60', '#9b59b6', '#f39c12', '#1abc9c', '#e67e22', '#34495e']
    
    # Piirrä simuloidut suunnat
    direction_names = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE',
                       'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW']
    
    legend_handles = []
    n_sims = len(simulations)
    
    # Järjestä painon mukaan (suurin ensin) jotta pienet näkyvät
    sorted_sims = sorted(enumerate(simulations), key=lambda x: x[1].get('weight', 0), reverse=True)
    
    # Maksimi paino skaalausta varten
    max_weight = max(s.get('weight', 0.1) for s in simulations)
    
    for orig_idx, sim in sorted_sims:
        inlet_dir = sim.get('inlet_direction', 0)
        weight = sim.get('weight', 0.1)
        
        # Muunna CFD -> meteorologinen
        meteo_direction = (270 - inlet_dir + 360) % 360
        
        # Suunnan nimi
        sector_idx = int((meteo_direction + 11.25) % 360 / 22.5)
        dir_name = sim.get('direction_name', direction_names[sector_idx])
        
        # Piirrä sektori
        wind_angle_rad = np.radians(meteo_direction)
        color = colors[orig_idx % len(colors)]
        
        # Korkeus painon mukaan (0.3 - 0.9)
        height = 0.3 + (weight / max_weight) * 0.6
        
        # Palkin leveys - kapeampi jos monta suuntaa lähellä
        bar_width = sector_width * 0.8
        
        # Piirrä palkki
        bar = ax.bar(wind_angle_rad, height, width=bar_width, bottom=0, 
                     color=color, edgecolor='white', linewidth=2, alpha=0.85)
        
        # Lisää suunnan nimi ja prosentti palkin päälle
        label_r = height + 0.08
        ax.text(wind_angle_rad, label_r, f"{dir_name}\n{weight:.0%}", 
                ha='center', va='bottom', fontsize=9, fontweight='bold', color=color)
        
        # Legend handle
        import matplotlib.patches as mpatches
        legend_handles.append(mpatches.Patch(color=color, label=f"{dir_name} ({weight:.0%})"))
    
    # Suuntanimet
    ax.set_xticks(np.linspace(0, 2 * np.pi, 8, endpoint=False))
    ax.set_xticklabels(['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'], fontsize=10)
    
    ax.set_yticks([])
    ax.set_ylim(0, 1.15)
    
    # Otsikko
    ax.set_title(f'Simuloidut tuulensuunnat\n({len(simulations)} suuntaa)',
                 fontsize=12, fontweight='bold', pad=20)
    
    # Selite
    ax.legend(handles=legend_handles, loc='lower center', bbox_to_anchor=(0.5, -0.15),
              ncol=min(4, len(simulations)), fontsize=9, frameon=False)
    
    plt.tight_layout()
    
    try:
        plt.savefig(output_path, dpi=REPORT_DPI, bbox_inches='tight', facecolor='white')
        plt.close(fig)
        return True
    except Exception as e:
        print(f"  Varoitus: Multi-wind tuuliruusun tallennus epäonnistui: {e}")
        plt.close(fig)
        return False


def find_city_from_geometry(geometry_path: Path) -> str:
    """
    Yrittää löytää lähimmän FMI-sääasemakaupungin geometriatiedostosta.
    
    Etsii järjestyksessä:
    1. Koordinaatit (lat/lon) -> lähin FMI-kaupunki
    2. metadata.city
    3. metadata.address / name -> tekstihaku
    
    Returns:
        Kaupungin nimi tai None
    """
    import math
    
    # FMI-sääasemien koordinaatit (lat, lon)
    FMI_CITIES = {
        'Helsinki': (60.17, 24.94),
        'Espoo': (60.21, 24.66),
        'Vantaa': (60.29, 25.04),
        'Turku': (60.45, 22.27),
        'Tampere': (61.50, 23.79),
        'Oulu': (65.01, 25.47),
        'Lahti': (60.98, 25.66),
        'Kuopio': (62.89, 27.68),
        'Jyväskylä': (62.24, 25.75),
        'Pori': (61.48, 21.80),
        'Joensuu': (62.60, 29.76),
        'Lappeenranta': (61.06, 28.19),
        'Rovaniemi': (66.50, 25.73),
        'Vaasa': (63.10, 21.62),
        'Kotka': (60.47, 26.95),
        'Mikkeli': (61.69, 27.27),
        'Hämeenlinna': (61.00, 24.44),
        'Porvoo': (60.39, 25.66),
        'Kokkola': (63.84, 23.13),
        'Seinäjoki': (62.79, 22.84),
        'Rauma': (61.13, 21.51),
        'Kajaani': (64.23, 27.73),
        'Savonlinna': (61.87, 28.88),
        'Kemi': (65.73, 24.56),
        'Hanko': (59.82, 22.97),
        'Sodankylä': (67.42, 26.59),
        'Ivalo': (68.66, 27.55),
        'Utsjoki': (69.91, 27.03),
        'Muonio': (67.94, 23.68),
        'Enontekiö': (69.05, 20.81),
    }
    
    def haversine_distance(lat1, lon1, lat2, lon2):
        """Laske etäisyys km (Haversine)."""
        R = 6371
        lat1_rad, lat2_rad = math.radians(lat1), math.radians(lat2)
        delta_lat = math.radians(lat2 - lat1)
        delta_lon = math.radians(lon2 - lon1)
        a = math.sin(delta_lat/2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lon/2)**2
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    
    def find_nearest_city(lat, lon):
        """Etsi lähin FMI-kaupunki."""
        nearest, min_dist = None, float('inf')
        for city, (clat, clon) in FMI_CITIES.items():
            dist = haversine_distance(lat, lon, clat, clon)
            if dist < min_dist:
                min_dist, nearest = dist, city
        return nearest, min_dist
    
    try:
        with open(geometry_path, 'r', encoding='utf-8') as f:
            geom_data = json.load(f)
    except:
        return None
    
    metadata = geom_data.get('metadata', {})
    
    # 1. Prioriteetti: Koordinaatit
    lat, lon = None, None
    
    # Eri formaatit metadatasta
    if 'lat' in metadata and 'lon' in metadata:
        lat, lon = float(metadata['lat']), float(metadata['lon'])
    elif 'latitude' in metadata and 'longitude' in metadata:
        lat, lon = float(metadata['latitude']), float(metadata['longitude'])
    elif 'center' in metadata:
        center = metadata['center']
        if isinstance(center, (list, tuple)) and len(center) >= 2:
            lat, lon = float(center[0]), float(center[1])
        elif isinstance(center, dict) and 'lat' in center:
            lat, lon = float(center['lat']), float(center['lon'])
    elif 'coordinates' in metadata:
        coords = metadata['coordinates']
        if isinstance(coords, (list, tuple)) and len(coords) >= 2:
            lat, lon = float(coords[0]), float(coords[1])
    
    # Jos koordinaatit löytyivät ja ovat Suomessa
    if lat is not None and lon is not None:
        if 59 <= lat <= 70 and 19 <= lon <= 32:
            city, dist = find_nearest_city(lat, lon)
            print(f"  Koordinaateista ({lat:.2f}, {lon:.2f}) -> {city} ({dist:.1f} km)")
            return city
    
    # 2. Fallback: Tekstihaku
    known_cities = list(FMI_CITIES.keys())
    
    # Pienemmät paikkakunnat -> lähin iso kaupunki
    city_mapping = {
        'ulvila': 'Pori', 'nakkila': 'Pori', 'harjavalta': 'Pori',
        'nokia': 'Tampere', 'pirkkala': 'Tampere', 'ylöjärvi': 'Tampere',
        'kerava': 'Helsinki', 'järvenpää': 'Helsinki', 'tuusula': 'Helsinki',
        'kirkkonummi': 'Helsinki', 'sipoo': 'Helsinki', 'nurmijärvi': 'Helsinki',
        'raisio': 'Turku', 'naantali': 'Turku', 'kaarina': 'Turku',
        'hollola': 'Lahti', 'nastola': 'Lahti',
        'imatra': 'Lappeenranta', 'hamina': 'Kotka', 'kouvola': 'Kotka',
        'iisalmi': 'Kuopio', 'varkaus': 'Kuopio',
        'tornio': 'Kemi', 'kemijärvi': 'Rovaniemi',
    }
    
    # Tarkista metadata.city
    if 'city' in metadata:
        city_val = metadata['city'].lower()
        if city_val in city_mapping:
            return city_mapping[city_val]
        return metadata['city']
    
    # Yhdistä tekstit
    address = metadata.get('address', '')
    name = geom_data.get('name', '')
    search_text = f"{address} {name}".lower()
    
    # Etsi pienemmät paikkakunnat
    for place, city in city_mapping.items():
        if place in search_text:
            print(f"  Tunnistettu: {place.title()} -> {city}")
            return city
    
    # Etsi isot kaupungit
    for city in known_cities:
        if city.lower() in search_text:
            return city
    
    return None


def generate_fmi_wind_rose(city: str, output_path: Path, year: int = None) -> bool:
    """
    Generoi FMI-tuuliruusu kaupungille.
    
    Hakee tuulidatan FMI:n avoimesta datasta ja piirtää tuuliruusun.
    Jos FMI-dataa ei saada, generoi placeholder-kuvan.
    
    Args:
        city: Kaupungin nimi
        output_path: Tuloskuvan polku
        year: Vuosi (oletus: edellinen vuosi)
        
    Returns:
        True jos onnistui
    """
    import numpy as np
    from datetime import datetime
    
    # FMI sääasemat
    FMI_STATIONS = {
        'Helsinki': {'fmisid': 100971, 'name': 'Helsinki Kaisaniemi'},
        'Helsinki-Vantaa': {'fmisid': 100968, 'name': 'Helsinki-Vantaa lentoasema'},
        'Espoo': {'fmisid': 100976, 'name': 'Espoo Tapiola'},
        'Vantaa': {'fmisid': 100968, 'name': 'Helsinki-Vantaa lentoasema'},
        'Turku': {'fmisid': 100949, 'name': 'Turku lentoasema'},
        'Tampere': {'fmisid': 101118, 'name': 'Tampere Härmälä'},
        'Lahti': {'fmisid': 101039, 'name': 'Lahti Laune'},
        'Hämeenlinna': {'fmisid': 101150, 'name': 'Hämeenlinna Lammi Pappila'},
        'Kotka': {'fmisid': 101030, 'name': 'Kotka Rankki'},
        'Porvoo': {'fmisid': 101023, 'name': 'Porvoo Kalbådagrund'},
        'Hanko': {'fmisid': 100946, 'name': 'Hanko Russarö'},
        'Pori': {'fmisid': 101267, 'name': 'Pori lentoasema'},
        'Rauma': {'fmisid': 101061, 'name': 'Rauma Kylmäpihlaja'},
        'Vaasa': {'fmisid': 101462, 'name': 'Vaasa lentoasema'},
        'Seinäjoki': {'fmisid': 101486, 'name': 'Seinäjoki Pelmaa'},
        'Kokkola': {'fmisid': 101479, 'name': 'Kokkola Tankar'},
        'Kuopio': {'fmisid': 101570, 'name': 'Kuopio lentoasema'},
        'Joensuu': {'fmisid': 101632, 'name': 'Joensuu Linnunlahti'},
        'Jyväskylä': {'fmisid': 101339, 'name': 'Jyväskylä lentoasema'},
        'Mikkeli': {'fmisid': 101398, 'name': 'Mikkeli lentoasema'},
        'Savonlinna': {'fmisid': 101436, 'name': 'Savonlinna lentoasema'},
        'Lappeenranta': {'fmisid': 101237, 'name': 'Lappeenranta lentoasema'},
        'Oulu': {'fmisid': 101799, 'name': 'Oulu lentoasema'},
        'Rovaniemi': {'fmisid': 101920, 'name': 'Rovaniemi lentoasema'},
        'Kajaani': {'fmisid': 101725, 'name': 'Kajaani lentoasema'},
        'Kemi': {'fmisid': 101846, 'name': 'Kemi-Tornio lentoasema'},
        'Sodankylä': {'fmisid': 101932, 'name': 'Sodankylä Tähtelä'},
        'Ivalo': {'fmisid': 101952, 'name': 'Ivalo lentoasema'},
        'Utsjoki': {'fmisid': 102035, 'name': 'Utsjoki Kevo'},
        'Muonio': {'fmisid': 101982, 'name': 'Muonio Alamuonio'},
        'Enontekiö': {'fmisid': 101976, 'name': 'Enontekiö Kilpisjärvi'},
    }
    
    # Tyypilliset tuulijakaumat Suomen kaupungeille (fallback)
    # Perustuu Ilmatieteen laitoksen pitkäaikaisiin tilastoihin
    # Formaatti: [N, NNE, NE, ENE, E, ESE, SE, SSE, S, SSW, SW, WSW, W, WNW, NW, NNW]
    TYPICAL_WIND_DISTRIBUTIONS = {
        'Helsinki': {'percents': [5, 4, 5, 6, 7, 7, 8, 8, 10, 9, 10, 8, 6, 4, 4, 5], 'mean_speed': 4.2},
        'Espoo': {'percents': [5, 4, 5, 6, 7, 7, 8, 8, 10, 9, 10, 8, 6, 4, 4, 5], 'mean_speed': 4.0},
        'Vantaa': {'percents': [5, 4, 5, 6, 7, 7, 8, 8, 10, 9, 10, 8, 6, 4, 4, 5], 'mean_speed': 4.0},
        'Turku': {'percents': [4, 3, 4, 5, 6, 7, 9, 10, 12, 10, 10, 7, 5, 3, 3, 4], 'mean_speed': 4.5},
        'Tampere': {'percents': [5, 4, 5, 5, 6, 7, 8, 9, 11, 10, 9, 7, 5, 4, 4, 5], 'mean_speed': 3.8},
        'Oulu': {'percents': [6, 5, 5, 5, 5, 6, 7, 8, 10, 10, 10, 8, 6, 4, 4, 5], 'mean_speed': 4.0},
        'Lahti': {'percents': [5, 4, 5, 6, 7, 7, 8, 8, 10, 9, 9, 7, 5, 4, 4, 5], 'mean_speed': 3.5},
        'Kuopio': {'percents': [5, 5, 5, 6, 6, 7, 8, 8, 10, 9, 9, 7, 5, 4, 4, 5], 'mean_speed': 3.6},
        'Jyväskylä': {'percents': [5, 5, 5, 6, 6, 7, 8, 8, 10, 9, 9, 7, 5, 4, 4, 5], 'mean_speed': 3.4},
        'Pori': {'percents': [4, 3, 4, 5, 6, 7, 9, 10, 12, 11, 10, 7, 5, 3, 3, 4], 'mean_speed': 4.8},
        'Vaasa': {'percents': [5, 4, 4, 5, 5, 6, 8, 10, 12, 11, 10, 7, 5, 3, 3, 4], 'mean_speed': 5.0},
        'Joensuu': {'percents': [5, 5, 5, 6, 6, 7, 8, 8, 10, 9, 9, 7, 5, 4, 4, 5], 'mean_speed': 3.4},
        'Lappeenranta': {'percents': [5, 5, 5, 6, 6, 7, 8, 8, 10, 9, 9, 7, 5, 4, 4, 5], 'mean_speed': 3.6},
        'Rovaniemi': {'percents': [6, 5, 5, 5, 5, 6, 7, 8, 10, 10, 10, 8, 6, 4, 4, 5], 'mean_speed': 3.5},
        'Kotka': {'percents': [5, 4, 5, 6, 7, 8, 9, 9, 10, 9, 9, 7, 5, 3, 3, 4], 'mean_speed': 4.5},
        'Mikkeli': {'percents': [5, 5, 5, 6, 6, 7, 8, 8, 10, 9, 9, 7, 5, 4, 4, 5], 'mean_speed': 3.4},
        'Hämeenlinna': {'percents': [5, 4, 5, 5, 6, 7, 8, 9, 11, 10, 9, 7, 5, 4, 4, 5], 'mean_speed': 3.6},
        'Porvoo': {'percents': [5, 4, 5, 6, 7, 7, 8, 8, 10, 9, 10, 8, 6, 4, 4, 5], 'mean_speed': 4.0},
        'Kokkola': {'percents': [5, 4, 4, 5, 5, 6, 8, 10, 12, 11, 10, 7, 5, 3, 3, 4], 'mean_speed': 4.8},
        'Seinäjoki': {'percents': [5, 4, 5, 5, 6, 7, 8, 9, 11, 10, 9, 7, 5, 4, 4, 5], 'mean_speed': 3.8},
        'Rauma': {'percents': [4, 3, 4, 5, 6, 7, 9, 10, 12, 11, 10, 7, 5, 3, 3, 4], 'mean_speed': 4.6},
        'Kajaani': {'percents': [5, 5, 5, 6, 6, 7, 8, 8, 10, 9, 9, 7, 5, 4, 4, 5], 'mean_speed': 3.4},
        'Savonlinna': {'percents': [5, 5, 5, 6, 6, 7, 8, 8, 10, 9, 9, 7, 5, 4, 4, 5], 'mean_speed': 3.4},
        'Kemi': {'percents': [6, 5, 5, 5, 5, 6, 7, 8, 10, 10, 10, 8, 6, 4, 4, 5], 'mean_speed': 4.2},
        'Hanko': {'percents': [4, 3, 4, 5, 6, 7, 9, 10, 12, 11, 11, 7, 5, 3, 3, 4], 'mean_speed': 5.5},
    }
    
    if city not in FMI_STATIONS:
        print(f"  Varoitus: Kaupunkia '{city}' ei löydy FMI-asemista")
        return False
    
    station = FMI_STATIONS[city]
    
    if year is None:
        year = datetime.now().year - 1
    
    # Yritä hakea data FMI:stä
    fmi_data_ok = False
    directions = None
    speeds = None
    
    try:
        import requests
        import xml.etree.ElementTree as ET
        from datetime import timedelta
        
        base_url = "https://opendata.fmi.fi/wfs"
        
        # Hae data kuukausittain (3 kuukautta riittää esimerkkiin)
        all_directions = []
        all_speeds = []
        
        for month in [1, 4, 7, 10]:  # Neljä vuodenaikaa
            start_date = datetime(year, month, 1)
            if month == 12:
                end_date = datetime(year, 12, 31)
            else:
                end_date = datetime(year, month + 1, 1) - timedelta(days=1)
            
            params = {
                'service': 'WFS',
                'version': '2.0.0',
                'request': 'GetFeature',
                'storedquery_id': 'fmi::observations::weather::hourly::simple',
                'fmisid': station['fmisid'],
                'starttime': start_date.strftime('%Y-%m-%dT00:00:00Z'),
                'endtime': end_date.strftime('%Y-%m-%dT23:59:59Z'),
                'parameters': 'WD_PT1H_AVG,WS_PT1H_AVG',
            }
            
            response = requests.get(base_url, params=params, timeout=30)
            if response.status_code != 200:
                continue
            
            # Parsitaan XML
            root = ET.fromstring(response.content)
            ns = {'BsWfs': 'http://xml.fmi.fi/schema/wfs/2.0'}
            
            data = {}
            for member in root.findall('.//BsWfs:BsWfsElement', ns):
                time_elem = member.find('BsWfs:Time', ns)
                param_elem = member.find('BsWfs:ParameterName', ns)
                value_elem = member.find('BsWfs:ParameterValue', ns)
                
                if time_elem is None or param_elem is None or value_elem is None:
                    continue
                
                try:
                    time_key = time_elem.text
                    param_name = param_elem.text
                    value = float(value_elem.text) if value_elem.text and value_elem.text != 'NaN' else None
                except:
                    continue
                
                if value is None:
                    continue
                
                if time_key not in data:
                    data[time_key] = {}
                
                if param_name == 'WD_PT1H_AVG':
                    data[time_key]['direction'] = value
                elif param_name == 'WS_PT1H_AVG':
                    data[time_key]['speed'] = value
            
            for entry in data.values():
                if 'direction' in entry and 'speed' in entry:
                    if entry['speed'] > 0.5:  # Suodata tyyni
                        all_directions.append(entry['direction'])
                        all_speeds.append(entry['speed'])
        
        if len(all_directions) >= 100:
            directions = np.array(all_directions)
            speeds = np.array(all_speeds)
            fmi_data_ok = True
        
    except Exception as e:
        pass  # Käytetään fallback-dataa
    
    # Jos FMI-data ei onnistunut, käytä tyypillistä jakaumaa
    if not fmi_data_ok:
        if city in TYPICAL_WIND_DISTRIBUTIONS:
            dist = TYPICAL_WIND_DISTRIBUTIONS[city]
            sector_percents = np.array(dist['percents'], dtype=float)
            mean_speed = dist['mean_speed']
            # Normalisoi prosentit
            sector_percents = sector_percents / sector_percents.sum() * 100
            data_source = "tyypillinen jakauma"
        else:
            # Oletus: Helsinki
            dist = TYPICAL_WIND_DISTRIBUTIONS['Helsinki']
            sector_percents = np.array(dist['percents'], dtype=float)
            mean_speed = dist['mean_speed']
            sector_percents = sector_percents / sector_percents.sum() * 100
            data_source = "tyypillinen jakauma (Helsinki)"
    else:
        # Laske suuntajakauma FMI-datasta
        n_sectors = 16
        sector_size = 360 / n_sectors
        sector_counts = np.zeros(n_sectors)
        
        for direction in directions:
            sector = int((direction + sector_size / 2) % 360 / sector_size)
            sector_counts[sector] += 1
        
        total = len(directions)
        sector_percents = sector_counts / total * 100
        mean_speed = np.mean(speeds)
        data_source = f"FMI {year}"
    
    # Piirrä tuuliruusu - pienempi koko sopimaan raporttiin
    n_sectors = 16
    fig, ax = plt.subplots(subplot_kw={'projection': 'polar'}, figsize=(5, 5))
    
    ax.set_theta_zero_location('N')
    ax.set_theta_direction(-1)
    
    angles = np.linspace(0, 2 * np.pi, n_sectors, endpoint=False)
    width = 2 * np.pi / n_sectors * 0.8
    
    # Värit prosenttiosuuden mukaan
    max_pct = max(sector_percents) if max(sector_percents) > 0 else 1
    colors = plt.cm.Blues(sector_percents / max_pct * 0.7 + 0.3)
    
    # Normalisoi korkeudeksi
    heights = sector_percents / max_pct
    
    bars = ax.bar(angles, heights, width=width, bottom=0,
                  color=colors, edgecolor='#2c3e50', linewidth=0.5, alpha=0.8)
    
    ax.set_xticks(np.linspace(0, 2 * np.pi, 8, endpoint=False))
    ax.set_xticklabels(['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'], fontsize=10)
    ax.set_yticks([])
    ax.set_ylim(0, 1.2)
    
    # Pääsuunta
    main_sector = np.argmax(sector_percents)
    main_direction = main_sector * (360 / n_sectors)
    direction_names = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE',
                       'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW']
    main_name = direction_names[main_sector]
    
    ax.set_title(f'{city} - Vuotuinen tuulijakauma\n'
                 f'Pääsuunta: {main_name} ({sector_percents[main_sector]:.0f}%), '
                 f'keskinopeus {mean_speed:.1f} m/s',
                 fontsize=11, fontweight='bold', pad=20)
    
    ax.text(0.5, -0.10, f'Lähde: Ilmatieteen laitos ({station["name"]})\n'
                        f'Data: {data_source}',
            transform=ax.transAxes, ha='center', fontsize=8, color='#666666')
    
    plt.tight_layout()
    
    try:
        plt.savefig(output_path, dpi=REPORT_DPI, bbox_inches='tight', facecolor='white')
        plt.close(fig)
        return True
    except Exception as e:
        print(f"  Varoitus: FMI-tuuliruusun tallennus epäonnistui: {e}")
        plt.close(fig)
        return False


def create_cover_image(results_dir: Path, building_analysis: dict) -> Path:
    """
    Luo kansilehden kuva kriittisistä pisteistä ilman colorbar-palkkia.
    
    Returns:
        Polku luotuun kuvaan tai None jos epäonnistui
    """
    try:
        import numpy as np
    except ImportError:
        return None
    
    if building_analysis is None:
        return None
    
    data_dir = building_analysis.get('data_dir')
    if data_dir is None:
        return None
    
    # Tarkista onko kyseessä combined-data
    is_combined = "combined" in str(data_dir) or (data_dir / 'convection_weighted.npy').exists()
    
    # Lataa datat
    try:
        X = np.load(data_dir / 'X.npy')
        Y = np.load(data_dir / 'Y.npy')
        solid_mask = np.load(data_dir / 'solid_mask.npy')
        
        if is_combined:
            # Combined-data: käytä convection_weighted suoraan
            conv_file = data_dir / 'convection_weighted.npy'
            if conv_file.exists():
                convection = np.load(conv_file)
            else:
                # Fallback: käytä velocity_weighted
                vel = np.load(data_dir / 'velocity_weighted.npy')
                convection = vel
        else:
            # Single-wind: laske konvektio
            vel = np.load(data_dir / 'velocity_magnitude.npy')
            k = np.load(data_dir / 'k.npy')
            convection = np.sqrt(k) * vel
    except FileNotFoundError as e:
        print(f"  Varoitus: Kansikuvan data puuttuu: {e}")
        return None
    
    convection[solid_mask] = np.nan
    
    # Lataa porous_mask (metsäalueet) jos saatavilla
    porous_mask = None
    porous_mask_file = data_dir / 'porous_mask.npy'
    if porous_mask_file.exists():
        porous_mask = np.load(porous_mask_file)
    
    # Lataa porous_zones.json (metsäalueiden polygonit)
    porous_zones = []
    porous_zones_paths = [
        data_dir / 'porous_zones.json',
        data_dir.parent / 'porous_zones.json',
        results_dir / 'porous_zones.json',
    ]
    
    # Combined-kansiossa etsi myös wind-kansioista (sama logiikka kuin buildings.json)
    if is_combined:
        parent_dir = data_dir.parent.parent
        wind_dirs = sorted(parent_dir.glob("wind_*"))
        for wind_dir in wind_dirs:
            porous_zones_paths.append(wind_dir / 'fine' / 'porous_zones.json')
            porous_zones_paths.append(wind_dir / 'porous_zones.json')
    
    for pz_path in porous_zones_paths:
        if pz_path.exists():
            import json
            with open(pz_path, 'r') as f:
                porous_zones = json.load(f)
            break
    
    # Luo kuva ilman colorbar-palkkia
    fig, ax = plt.subplots(figsize=(8, 6))
    
    # Piirrä konvektioindeksi taustalle
    conv_max = np.nanpercentile(convection, 98)
    ax.pcolormesh(X, Y, convection, cmap='YlOrRd', shading='auto', 
                  alpha=0.8, vmin=0, vmax=conv_max)
    
    # Piirrä kasvillisuusalueet ENSIN (jotta rakennukset piirtyvät päälle)
    # Metsät vihreällä, pellot kellertävällä
    # Ensisijaisesti käytä porous_zones polygoneja (tarkemmat reunat)
    if porous_zones:
        from matplotlib.patches import Polygon as MplPolygon
        for zone in _sort_zones_for_drawing(porous_zones):
            if 'vertices' in zone:
                verts = np.array(zone['vertices'])
                # Väri kasvillisuustyypin mukaan
                veg_type = zone.get('vegetation_type', zone.get('type', 'tree_zone'))
                facecolor, edgecolor, is_hard = _get_vegetation_color(veg_type)
                zone_alpha = 0.85 if is_hard else 0.6
                poly = MplPolygon(verts, facecolor=facecolor, edgecolor=edgecolor,
                                 linewidth=1, alpha=zone_alpha)
                ax.add_patch(poly)
    elif porous_mask is not None and porous_mask.any():
        # Fallback: käytä porous_mask:ia
        ax.contourf(X, Y, porous_mask.astype(int), levels=[0.5, 1.5], 
                   colors=['#228b22'], alpha=0.6)
    
    # Piirrä rakennukset - etsi buildings.json useasta paikasta
    buildings_file = None
    buildings_search_paths = [
        data_dir / 'buildings.json',
        data_dir.parent / 'buildings.json',
        results_dir / 'buildings.json',
    ]
    
    # Combined-kansiossa etsi myös wind-kansioista
    if is_combined:
        parent_dir = data_dir.parent.parent
        wind_dirs = sorted(parent_dir.glob("wind_*"))
        for wind_dir in wind_dirs:
            buildings_search_paths.append(wind_dir / 'fine' / 'buildings.json')
            buildings_search_paths.append(wind_dir / 'buildings.json')
    
    for search_path in buildings_search_paths:
        if search_path.exists():
            buildings_file = search_path
            break
    
    if buildings_file and buildings_file.exists():
        import json
        from matplotlib.patches import Polygon as MplPolygon
        
        with open(buildings_file, 'r') as f:
            buildings_data = json.load(f)
        
        if isinstance(buildings_data, dict):
            buildings_data = buildings_data.get('buildings', [])
        
        for bldg_data in buildings_data:
            # Suodata pois metsäalueet - piirretään vain rakennukset
            bldg_type = bldg_data.get('type', 'building')
            is_solid = bldg_data.get('is_solid', True)
            
            if bldg_type in ['tree_zone', 'vegetation_zone', 'tree'] or not is_solid:
                continue
            
            if 'vertices' in bldg_data and bldg_data['vertices']:
                poly = MplPolygon(bldg_data['vertices'], 
                                 facecolor='#404040', edgecolor='black',
                                 linewidth=1.5, alpha=0.95)
                ax.add_patch(poly)
    else:
        ax.contourf(X, Y, solid_mask.astype(int), levels=[0.5, 1.5], colors=['#404040'], alpha=0.95)
    
    # Ratkaise ID-laatikoiden päällekkäisyydet cover imagessa
    def resolve_cover_overlaps(buildings, X, Y):
        """Ratkaisee ID-laatikoiden päällekkäisyydet kansikuvassa."""
        x_range = X.max() - X.min()
        y_range = Y.max() - Y.min()
        
        # ID-laatikon koko (pienempi fontilla cover imagessa)
        box_width = (x_range / 80) * 4
        box_height = (y_range / 80) * 1.5
        
        # Laske oletussijainnit (keskipisteissä)
        positions = {}
        for bldg in buildings:
            bldg_id = bldg['id']
            positions[bldg_id] = {
                'x': bldg['center_x'],
                'y': bldg['center_y'],
                'was_offset': False,
                'area': bldg.get('area_pixels', 100)
            }
        
        def boxes_overlap(pos1, pos2, margin=0.3):
            dx = abs(pos1['x'] - pos2['x'])
            dy = abs(pos1['y'] - pos2['y'])
            return dx < box_width * (1 + margin) and dy < box_height * (1 + margin)
        
        # Iteroi kunnes ei päällekkäisyyksiä
        for iteration in range(10):
            overlaps_found = False
            ids = list(positions.keys())
            
            for i, id1 in enumerate(ids):
                for id2 in ids[i+1:]:
                    pos1 = positions[id1]
                    pos2 = positions[id2]
                    
                    if boxes_overlap(pos1, pos2):
                        overlaps_found = True
                        
                        # Siirrä pienempää rakennusta
                        if pos1['area'] >= pos2['area']:
                            move_id = id2
                        else:
                            move_id = id1
                        
                        pos_to_move = positions[move_id]
                        bldg_data = next(b for b in buildings if b['id'] == move_id)
                        center_x = bldg_data['center_x']
                        center_y = bldg_data['center_y']
                        
                        # Siirtosuunnat
                        offset_dist = box_width * 1.3
                        candidates = [
                            (offset_dist, offset_dist * 0.4),
                            (-offset_dist, offset_dist * 0.4),
                            (offset_dist, -offset_dist * 0.4),
                            (-offset_dist, -offset_dist * 0.4),
                            (offset_dist * 1.1, 0),
                            (-offset_dist * 1.1, 0),
                        ]
                        
                        best_pos = None
                        best_min_dist = -1
                        
                        for dx, dy in candidates:
                            new_x = center_x + dx
                            new_y = center_y + dy
                            
                            min_dist = float('inf')
                            for other_id, other_pos in positions.items():
                                if other_id != move_id:
                                    dist = np.sqrt((new_x - other_pos['x'])**2 + (new_y - other_pos['y'])**2)
                                    min_dist = min(min_dist, dist)
                            
                            if min_dist > best_min_dist:
                                best_min_dist = min_dist
                                best_pos = (new_x, new_y)
                        
                        if best_pos:
                            positions[move_id]['x'] = best_pos[0]
                            positions[move_id]['y'] = best_pos[1]
                            positions[move_id]['was_offset'] = True
            
            if not overlaps_found:
                break
        
        return positions
    
    # Selvitä näkymärajat reunarakennusten ID:iden suodatukseen
    cov_margin = 2
    cov_xmin = float(X.min()) - cov_margin
    cov_xmax = float(X.max()) + cov_margin
    cov_ymin = float(Y.min()) - cov_margin
    cov_ymax = float(Y.max()) + cov_margin
    cov_id_margin_x = (cov_xmax - cov_xmin) * 0.03
    cov_id_margin_y = (cov_ymax - cov_ymin) * 0.03
    
    # Laske päällekkäisyyksistä vapaat sijainnit
    id_positions = resolve_cover_overlaps(building_analysis['buildings'], X, Y)
    
    # Lisää ID-numerot ja kriittiset pisteet
    for bldg in building_analysis['buildings']:
        marker_size = 6  # Pienempi koko cover imagessa
        edge_width = 0.8
        
        # Hae ID:n sijainti esikäsitellystä listasta
        bldg_id = bldg['id']
        id_pos = id_positions.get(bldg_id, {})
        id_x = id_pos.get('x', bldg['center_x'])
        id_y = id_pos.get('y', bldg['center_y'])
        id_was_offset = id_pos.get('was_offset', False)
        
        # Ohita ID jos se ei mahdu näkymään (reunarakennukset)
        if (id_x < cov_xmin + cov_id_margin_x or id_x > cov_xmax - cov_id_margin_x or
                id_y < cov_ymin + cov_id_margin_y or id_y > cov_ymax - cov_id_margin_y):
            continue
        
        # Jos ID siirrettiin, piirrä ohut viiva rakennuksen keskipisteeseen
        if id_was_offset:
            ax.plot([bldg['center_x'], id_x], [bldg['center_y'], id_y], 
                    color='#555555', linewidth=0.6, linestyle='-', alpha=0.7, zorder=1)
        
        # ID-numero
        ax.annotate(
            f"#{bldg['id']}", 
            (id_x, id_y),
            fontsize=8, fontweight='bold',
            ha='center', va='center',
            color='white',
            bbox=dict(boxstyle='round,pad=0.2', facecolor='#333333', edgecolor='white', alpha=0.9),
            zorder=10
        )
        
        # Kriittiset pisteet
        p_loc = bldg['max_p_location']
        v_loc = bldg['max_v_location']
        c_loc = bldg['max_conv_location']
        min_p_loc = bldg.get('min_p_location', bldg['max_p_location'])
        
        # Maksimipaine (punainen kolmio ylös)
        ax.plot(p_loc[0], p_loc[1], '^', color='#d62728', markersize=marker_size, 
                markeredgecolor='white', markeredgewidth=edge_width)
        
        # Minimipaine (syaani kolmio alas)
        ax.plot(min_p_loc[0], min_p_loc[1], 'v', color='#17becf', markersize=marker_size * 0.9, 
                markeredgecolor='white', markeredgewidth=edge_width)
        
        # Maksiminopeus (sininen neliö)
        ax.plot(v_loc[0], v_loc[1], 's', color='#1f77b4', markersize=marker_size * 0.9, 
                markeredgecolor='white', markeredgewidth=edge_width)
        
        # Maksimikonvektio (violetti timantti)
        ax.plot(c_loc[0], c_loc[1], 'D', color='#9467bd', markersize=marker_size * 0.85, 
                markeredgecolor='white', markeredgewidth=edge_width)
    
    ax.set_aspect('equal')
    ax.axis('off')
    
    # Rajaa kuva domainin (hilan) alueelle - ei laajenneta viheralueiden ulkopuolelle
    margin = 5  # metriä marginaalia
    ax.set_xlim(float(X.min()) - margin, float(X.max()) + margin)
    ax.set_ylim(float(Y.min()) - margin, float(Y.max()) + margin)
    
    # Tallenna
    output_path = results_dir / 'cover_image.png'
    plt.savefig(output_path, dpi=REPORT_DPI, bbox_inches='tight', 
                facecolor='white', edgecolor='none', pad_inches=0.02)
    plt.close(fig)
    
    return output_path


def add_title_page(pdf: PdfPages, title: str, cover_image: Path = None, lang: str = 'fi'):
    """Lisää kansilehti mahdollisella kuvalla."""
    fig, ax = plt.subplots(figsize=(8.27, 11.69))  # A4
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis('off')
    
    # Vaaleansininen palkki ylhäällä
    ax.fill_between([0, 1], 0.88, 0.96, color=LIGHT_BLUE, alpha=1.0)
    
    # Otsikko
    ax.text(0.5, 0.92, get_text('title', lang), 
            ha='center', va='center', fontsize=24, fontweight='bold', color=DARK_BLUE)
    
    ax.text(0.5, 0.84, title, 
            ha='center', va='center', fontsize=16, color=TEXT_DARK)
    
    # Kuva keskellä jos saatavilla
    if cover_image and cover_image.exists():
        # Lataa ja näytä kuva
        img = mpimg.imread(str(cover_image))
        
        # Lisää kuva-akseli keskelle sivua (siirretty alaspäin jotta otsikko näkyy)
        ax_img = fig.add_axes([0.1, 0.18, 0.8, 0.52])  # [left, bottom, width, height]
        ax_img.imshow(img)
        ax_img.axis('off')
    
    # Päivämäärä
    date_str = datetime.now().strftime("%d.%m.%Y")
    y_date = 0.16 if cover_image else 0.45
    ax.text(0.5, y_date, f'{get_text("report_created", lang)}: {date_str}', 
            ha='center', va='center', fontsize=SUBSECTION_SIZE, color=TEXT_GRAY)
    
    # Footer
    ax.text(0.5, 0.06, get_text('footer', lang), 
            ha='center', va='center', fontsize=SUBSECTION_SIZE, style='italic', color=DARK_BLUE)
    
    pdf.savefig(fig)
    plt.close(fig)


def add_image_page(pdf: PdfPages, img_path: Path, caption: str, section: str = None,
                   description: str = None, scale: float = 1.0):
    """Lisää kuvasivu mahdollisella selitystekstillä.
    
    Args:
        scale: Kuvan skaalauskerroin (oletus 1.0, pienempi = pienempi kuva)
    """
    fig = plt.figure(figsize=(8.27, 11.69))  # A4
    
    # Pääakseli taustalle (määrittää sivun koon)
    ax_bg = fig.add_axes([0, 0, 1, 1])
    ax_bg.set_xlim(0, 1)
    ax_bg.set_ylim(0, 1)
    ax_bg.axis('off')
    
    # Lataa kuva
    img = mpimg.imread(str(img_path))
    
    # Kuva-akseli (pienempi jos on selitysteksti tai scale < 1)
    base_width = 0.84
    base_height = 0.60 if description else 0.72
    
    # Skaalaa kuvan koko
    img_width = base_width * scale
    img_height = base_height * scale
    img_left = (1 - img_width) / 2  # Keskitä
    img_bottom = 0.28 if description else 0.15
    # Nosta kuvaa ylemmäs jos se on pienempi
    if scale < 1.0:
        img_bottom += (base_height - img_height) / 2
    
    ax_img = fig.add_axes([img_left, img_bottom, img_width, img_height])
    ax_img.imshow(img)
    ax_img.axis('off')
    
    # Osion otsikko vaaleansinisellä taustalla
    if section:
        ax_bg.fill_between([0.05, 0.95], 0.915, 0.955, color=LIGHT_BLUE, alpha=1.0)
        ax_bg.text(0.5, 0.935, section, 
                ha='center', va='center', fontsize=TITLE_SIZE, fontweight='bold', color=DARK_BLUE)
    
    # Kuvateksti ja selitys
    if description:
        # Kuvateksti heti kuvan alla
        ax_bg.text(0.5, img_bottom - 0.02, caption, 
                ha='center', va='top', fontsize=10, color='gray')
        
        # Renderöi koko selitysteksti yhtenä tekstinä
        ax_bg.text(0.08, img_bottom - 0.06, description, 
                ha='left', va='top', fontsize=8, color='#333333',
                family='sans-serif', linespacing=1.4)
    else:
        # Kuvateksti heti kuvan alla
        ax_bg.text(0.5, img_bottom - 0.02, caption, 
                ha='center', va='top', fontsize=10, color='gray')
    
    pdf.savefig(fig)
    plt.close(fig)


def add_two_images_page(pdf: PdfPages, img1_path: Path, img2_path: Path, 
                        caption1: str, caption2: str, section: str = None,
                        description: str = None):
    """Lisää sivu kahdella kuvalla päällekkäin."""
    fig = plt.figure(figsize=(8.27, 11.69))  # A4
    
    # Pääakseli taustalle (määrittää sivun koon)
    ax_bg = fig.add_axes([0, 0, 1, 1])
    ax_bg.set_xlim(0, 1)
    ax_bg.set_ylim(0, 1)
    ax_bg.axis('off')
    
    # Osion otsikko vaaleansinisellä taustalla
    if section:
        ax_bg.fill_between([0.05, 0.95], 0.915, 0.955, color=LIGHT_BLUE, alpha=1.0)
        ax_bg.text(0.5, 0.935, section, 
                ha='center', va='center', fontsize=TITLE_SIZE, fontweight='bold', color=DARK_BLUE)
    
    # Ylempi kuva - pienempi ja ylempänä
    img1 = mpimg.imread(str(img1_path))
    ax1 = fig.add_axes([0.15, 0.54, 0.70, 0.34])
    ax1.imshow(img1)
    ax1.axis('off')
    ax1.set_title(caption1, fontsize=BODY_SIZE, color=TEXT_GRAY, pad=5)
    
    # Description kuvien väliin
    if description:
        desc_text = description.replace("Automaattisesti tuotu", "Geometria automaattisesti tuotu")
        ax_bg.text(0.5, 0.52, desc_text, 
                ha='center', va='top', fontsize=BODY_SIZE, color=TEXT_GRAY, style='italic')
    
    # Alempi kuva - pienempi
    img2 = mpimg.imread(str(img2_path))
    ax2 = fig.add_axes([0.15, 0.12, 0.70, 0.34])
    ax2.imshow(img2)
    ax2.axis('off')
    ax2.set_title(caption2, fontsize=BODY_SIZE, color=TEXT_GRAY, pad=5)
    
    pdf.savefig(fig)
    plt.close(fig)


def add_summary_page(pdf: PdfPages, title: str, report_data: dict, building_analysis: dict = None, 
                     dominance_data: list = None, lang: str = 'fi'):
    """Lisää yhteenvetosivu johtopäätöksillä ja toimenpide-ehdotuksilla."""
    fig, ax = plt.subplots(figsize=(8.27, 11.69))  # A4
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis('off')
    
    # Pääotsikko - vaaleansininen tausta
    ax.fill_between([0.05, 0.95], 0.94, 0.98, color=LIGHT_BLUE, alpha=1.0)
    ax.text(0.5, 0.96, f'1. {get_text("summary", lang)}', 
            ha='center', va='center', fontsize=TITLE_SIZE, fontweight='bold', color=DARK_BLUE)
    
    # Kohteen tiedot
    y_pos = 0.91
    ax.text(0.08, y_pos, f'{get_text("site", lang)}: {title}', 
            ha='left', va='top', fontsize=SUBSECTION_SIZE, color=TEXT_DARK)
    
    # Dominoiva tuulensuunta (jos multi-wind)
    if dominance_data and len(dominance_data) > 0:
        y_pos = 0.88
        if lang == 'en':
            dom_text = "Dominant wind direction: "
        else:
            dom_text = "Dominoiva tuulensuunta: "
        
        top_dir = dominance_data[0]
        dom_text += f"{top_dir['direction']:.0f}° ({top_dir['combined_impact']:.0f}% of area)"
        
        if len(dominance_data) > 1:
            second_dir = dominance_data[1]
            if lang == 'en':
                dom_text += f", secondary: {second_dir['direction']:.0f}° ({second_dir['combined_impact']:.0f}%)"
            else:
                dom_text += f", toissijainen: {second_dir['direction']:.0f}° ({second_dir['combined_impact']:.0f}%)"
        
        ax.text(0.08, y_pos, dom_text, 
                ha='left', va='top', fontsize=CAPTION_SIZE, style='italic', color=TEXT_GRAY)
        y_pos = 0.85
    else:
        y_pos = 0.87
    
    # 1.1 Johtopäätökset - alaosion otsikko
    ax.text(0.08, y_pos, f'1.1 {get_text("conclusions", lang)}', 
            ha='left', va='top', fontsize=SECTION_SIZE, fontweight='bold', color=DARK_BLUE)
    
    y_pos -= 0.03
    
    # Rakenna johtopäätökset rakennusanalyysin perusteella
    if building_analysis:
        top_p = building_analysis['top_pressure'][0]
        top_v = building_analysis['top_velocity'][0]
        top_conv = building_analysis['top_convection'][0]
        num_bldg = building_analysis['num_buildings']
        has_wf = building_analysis.get('has_wall_functions', False)
        
        # Käännä ilmansuunnat
        dir_p = translate_direction(top_p["max_p_direction"], lang)
        dir_v = translate_direction(top_v["max_v_direction"], lang)
        dir_conv = translate_direction(top_conv["max_conv_direction"], lang)
        
        conclusions = (
            f'• {get_text("analyzed_buildings", lang, n=num_bldg)}\n'
            f'• {get_text("max_pressure", lang, id=top_p["id"], dir=dir_p, cp=top_p["max_pressure"])}\n'
            f'• {get_text("max_velocity", lang, id=top_v["id"], dir=dir_v, v=top_v["max_velocity"])}\n'
        )
        
        # Lisää lämmönsiirto jos wall functions käytössä
        if has_wf and building_analysis.get('top_heat_transfer'):
            top_h = building_analysis['top_heat_transfer'][0]
            dir_h = translate_direction(top_h["max_u_tau_direction"], lang)
            conclusions += f'• {get_text("max_heat_transfer", lang, id=top_h["id"], dir=dir_h, h=top_h["max_h"])}'
        else:
            conclusions += f'• {get_text("max_convection", lang, id=top_conv["id"], dir=dir_conv)}'
    else:
        if lang == 'en':
            conclusions = (
                '• Wind analysis performed with CFD simulation (SST k-ω turbulence model)\n'
                '• Calculation domain fetched automatically from OpenStreetMap\n'
                '• Nested grid method used to refine around target building'
            )
        else:
            conclusions = (
                '• Tuulisuusanalyysi suoritettu CFD-simuloinnilla (SST k-ω turbulenssimalli)\n'
                '• Laskenta-alue haettu automaattisesti OpenStreetMapista\n'
                '• Nested grid -menetelmällä tarkennettu kohderakennuksen ympäristö'
            )
    
    ax.text(0.08, y_pos, conclusions, 
            ha='left', va='top', fontsize=BODY_SIZE, color=TEXT_DARK,
            linespacing=1.15)
    
    # Laske seuraavan osion y-positio johtopäätösten rivimäärän mukaan
    concl_lines = conclusions.count('\n') + 1
    y_pos -= (concl_lines * 0.022 + 0.015)
    
    # 1.2 Kriittisimmät rakennukset (jos analyysi saatavilla)
    if building_analysis and len(building_analysis['top_pressure']) > 1:
        ax.text(0.08, y_pos, f'1.2 {get_text("critical_buildings", lang)}', 
                ha='left', va='top', fontsize=SECTION_SIZE, fontweight='bold', color=DARK_BLUE)
        
        y_pos -= 0.025
        has_wf = building_analysis.get('has_wall_functions', False)
        
        if has_wf and building_analysis.get('top_heat_transfer'):
            # Taulukko lämmönsiirrolla
            if lang == 'en':
                critical_text = "           Pressure (Cp)   Velocity      Heat transfer h\n"
                critical_text += "           -------------   --------      ---------------\n"
            else:
                critical_text = "           Paine (Cp)      Nopeus        Lämmönsiirto h\n"
                critical_text += "           -----------     --------      --------------\n"
            for i in range(min(3, len(building_analysis['top_pressure']))):
                bp = building_analysis['top_pressure'][i]
                bv = building_analysis['top_velocity'][i]
                bh = building_analysis['top_heat_transfer'][i]
                critical_text += f"  {i+1}.      #{bp['id']:2d} Cp={bp['max_pressure']:5.1f}    #{bv['id']:2d} v={bv['max_velocity']:.1f}    #{bh['id']:2d} h={bh['max_h']:.0f} W/(m²K)\n"
            if lang == 'en':
                critical_text += "\n  h = convective heat transfer coefficient (Reynolds analogy)"
            else:
                critical_text += "\n  h = konvektiivinen lämmönsiirtokerroin (Reynolds-analogia)"
        else:
            # Taulukko konvektiolla
            if lang == 'en':
                critical_text = "           Pressure (Cp)   Velocity      Convection*\n"
                critical_text += "           -------------   --------      -----------\n"
            else:
                critical_text = "           Paine (Cp)      Nopeus        Konvektio*\n"
                critical_text += "           -----------     --------      -----------\n"
            for i in range(min(3, len(building_analysis['top_pressure']))):
                bp = building_analysis['top_pressure'][i]
                bv = building_analysis['top_velocity'][i]
                bc = building_analysis['top_convection'][i]
                bc_dir = translate_direction(bc['max_conv_direction'], lang)
                critical_text += f"  {i+1}.      #{bp['id']:2d} Cp={bp['max_pressure']:5.1f}    #{bv['id']:2d} v={bv['max_velocity']:.1f}    #{bc['id']:2d} ({bc_dir})\n"
            if lang == 'en':
                critical_text += "\n  * Convection = surface cooling/moisture transfer (√k × v)"
            else:
                critical_text += "\n  * Konvektio = pinnan jäähtyminen/kosteussiirto (√k × v)"
        
        ax.text(0.08, y_pos, critical_text, 
                ha='left', va='top', fontsize=CAPTION_SIZE, color=TEXT_DARK,
                family='monospace', linespacing=1.1)
        
        # Laske seuraavan osion positio taulukon koon mukaan
        table_lines = critical_text.count('\n') + 1
        y_pos -= (table_lines * 0.018 + 0.02)
    else:
        y_pos -= 0.04
    
    # 1.3 Toimenpide-ehdotukset
    section_num = '1.3' if building_analysis else '1.2'
    ax.text(0.08, y_pos, f'{section_num} {get_text("recommendations", lang)}', 
            ha='left', va='top', fontsize=SECTION_SIZE, fontweight='bold', color=DARK_BLUE)
    
    y_pos -= 0.025
    
    # Räätälöidyt suositukset jos analyysi saatavilla
    if building_analysis:
        top_p = building_analysis['top_pressure'][0]
        top_conv = building_analysis['top_convection'][0]
        # Etsi suurin alipaine (min_pressure on negatiivinen)
        by_suction = sorted(building_analysis['buildings'], key=lambda x: x['min_pressure'])
        top_suction = by_suction[0]
        
        # Käännä ilmansuunnat
        dir_p = translate_direction(top_p["max_p_direction"], lang)
        dir_conv = translate_direction(top_conv["max_conv_direction"], lang)
        
        recommendations = (
            f'• {get_text("check_joints", lang, id=top_p["id"], dir=dir_p, cp=top_p["max_pressure"])}\n'
            f'• {get_text("check_cladding", lang, id=top_suction["id"], cp=top_suction["min_pressure"])}\n'
            f'• {get_text("check_cooling", lang, id=top_conv["id"], dir=dir_conv)}'
        )
    else:
        if lang == 'en':
            recommendations = (
                '• Check windward facade joints (overpressure → moisture)\n'
                '• Check leeward cladding and connections (suction)\n'
                '• Note acceleration zones between buildings (enhanced convection)'
            )
        else:
            recommendations = (
                '• Tarkista tuulen puoleisten julkisivujen saumaukset (ylipaine → kosteus)\n'
                '• Tarkista tuulensuojan puoleiset pellitykset ja liitokset (alipaine)\n'
                '• Huomioi rakennusten väliset kiihtymisalueet (tehostunut konvektio)'
            )
    
    ax.text(0.08, y_pos, recommendations, 
            ha='left', va='top', fontsize=BODY_SIZE, color=TEXT_DARK,
            linespacing=1.2)
    
    # Laske seuraavan osion y-positio suositusten rivimäärän mukaan
    rec_lines = recommendations.count('\n') + 1
    y_pos -= (rec_lines * 0.022 + 0.02)
    
    # 1.4 Suunnittelusuositukset (kategorisoidut) - allekkain
    ax.text(0.08, y_pos, '1.4 Suunnittelusuositukset' if building_analysis else '1.3 Suunnittelusuositukset', 
            ha='left', va='top', fontsize=11, fontweight='bold')
    
    y_pos -= 0.025
    
    # Julkisivusuunnittelu
    ax.text(0.08, y_pos, 'JULKISIVUSUUNNITTELU', 
            ha='left', va='top', fontsize=8, fontweight='bold', color='#2980b9')
    facade_text = (
        '• Tarkista saumat ja liitokset viistosaderasituksen max-kohdissa\n'
        '• Varmista riittävä limityspituus pellityksissä kosteusriskialueilla\n'
        '• Lisätiivistys ylipainealueille (Cp > 0.5)'
    )
    ax.text(0.08, y_pos - 0.015, facade_text, 
            ha='left', va='top', fontsize=8, color='#333333', linespacing=1.2)
    
    y_pos -= 0.07
    
    # Energiatehokkuus
    ax.text(0.08, y_pos, 'ENERGIATEHOKKUUS', 
            ha='left', va='top', fontsize=8, fontweight='bold', color='#27ae60')
    energy_text = (
        '• Tehosta lämmöneristystä konvektiivisen jäähtymisen kriittisissä pisteissä\n'
        '• Tarkista ikkunoiden ja ovien tiiveys tuulialtistuksen maksimikohdissa'
    )
    ax.text(0.08, y_pos - 0.015, energy_text, 
            ha='left', va='top', fontsize=8, color='#333333', linespacing=1.2)
    
    y_pos -= 0.055
    
    # Huolto ja ylläpito
    ax.text(0.08, y_pos, 'HUOLTO JA YLLÄPITO', 
            ha='left', va='top', fontsize=8, fontweight='bold', color='#e67e22')
    maintenance_text = (
        '• Priorisoi tarkastukset vuotuisen saderasituksen suurimpiin pisteisiin\n'
        '• Seuraa erityisesti kosteusriskialueiden kuntoa'
    )
    ax.text(0.08, y_pos - 0.015, maintenance_text, 
            ha='left', va='top', fontsize=8, color='#333333', linespacing=1.2)
    
    # Huomautus - omalle riville
    y_pos -= 0.065
    ax.text(0.08, y_pos, 'Huomautus:', 
            ha='left', va='top', fontsize=8, fontweight='bold', color='#666666')
    
    note = (
        'Analyysi perustuu stationääriseen 2D CFD-simulointiin. Simuloitava alue valitaan kohdetta laajemmaksi,\n'
        'jotta rakennukset ja muut esteet tuottavat halutulla alueella realistisen tuuli- ja painejakauman.'
    )
    ax.text(0.08, y_pos - 0.018, note, 
            ha='left', va='top', fontsize=7, color='#666666', style='italic',
            linespacing=1.2)
    
    pdf.savefig(fig)
    plt.close(fig)


def add_text_page(pdf: PdfPages, title: str, content: str):
    """Lisää tekstisivu."""
    fig, ax = plt.subplots(figsize=(8.27, 11.69))  # A4
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis('off')
    
    # Otsikko
    ax.text(0.08, 0.93, title, 
            ha='left', va='top', fontsize=14, fontweight='bold')
    
    # Sisältö - rajoita rivien pituutta
    lines = content.split('\n')
    text_content = '\n'.join(lines[:40])  # Rajoita rivimäärää
    
    # Lisätty väliä otsikon ja sisällön väliin (0.88 -> 0.85)
    ax.text(0.08, 0.85, text_content, 
            ha='left', va='top', fontsize=8, family='monospace',
            linespacing=1.3)
    
    pdf.savefig(fig)
    plt.close(fig)


def add_simulation_settings_page(pdf: PdfPages, metadata: dict, section_num: int, lang: str = 'fi',
                                   geometry_data: dict = None, report_data: dict = None):
    """
    Lisää simuloinnin tiedot -sivu multi-wind-raporttiin.
    
    Args:
        pdf: PdfPages-objekti
        metadata: multi_wind_metadata.json sisältö
        section_num: Osion numero
        lang: Kieli 'fi' tai 'en'
        geometry_data: Geometriatiedoston sisältö (valinnainen)
        report_data: report_data.json sisältö (valinnainen)
    """
    fig, ax = plt.subplots(figsize=(8.27, 11.69))  # A4
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis('off')
    
    # Osion otsikko
    if lang == 'en':
        title = f"{section_num}. Simulation Settings"
        subtitle_case = "Simulation Case"
        subtitle_grid_nested = "Grid Settings (Nested Grid)"
        subtitle_grid_standard = "Grid Settings"
        subtitle_location = "Location and Weather Station"
        subtitle_directions = "Simulated Wind Directions"
        subtitle_north = "North Wind for Cooling Analysis"
        col_headers = ['#', 'Direction', 'Angle', 'Weight', 'Speed']
        total_label = "Total"
        north_added = "North wind added for cooling risk analysis"
        north_weight_label = "North cooling weight combined"
        no_north = "North wind not separately added"
        city_label = "City"
        station_label = "Weather station"
        case_label = "Case"
        desc_label = "Description"
        turb_label = "Turbulence model"
        fine_area_label = "Fine grid area"
        refinement_label = "Refinement factor"
        coarse_grid_label = "Coarse grid"
        fine_grid_label = "Fine grid"
        cells_label = "cells"
        grid_label = "Grid"
    else:
        title = f"{section_num}. Simuloinnin tiedot"
        subtitle_case = "Simuloitava tapaus"
        subtitle_grid_nested = "Hila-asetukset (Nested Grid)"
        subtitle_grid_standard = "Hila-asetukset"
        subtitle_location = "Sijainti ja sääasema"
        subtitle_directions = "Simuloidut tuulensuunnat"
        subtitle_north = "Pohjoistuuli jäähtymisanalyysiin"
        col_headers = ['#', 'Suunta', 'Kulma', 'Paino', 'Nopeus']
        total_label = "Yhteensä"
        north_added = "Pohjoistuuli lisätty jäähtymisriskin vuoksi"
        north_weight_label = "Pohjoistuulen jäähtymispaino yhdistetty"
        no_north = "Pohjoistuulta ei lisätty erikseen"
        city_label = "Kaupunki"
        station_label = "Sääasema"
        case_label = "Tapaus"
        desc_label = "Kuvaus"
        turb_label = "Turbulenssimalli"
        fine_area_label = "Tiheä alue"
        refinement_label = "Tihennyskerroin"
        coarse_grid_label = "Karkea hila"
        fine_grid_label = "Tiheä hila"
        cells_label = "solua"
        grid_label = "Hila"
    
    y_pos = 0.92
    
    # Pääotsikko
    ax.text(0.08, y_pos, title, ha='left', va='top', fontsize=14, fontweight='bold', color=DARK_BLUE)
    y_pos -= 0.05
    
    # --- TAPAUS JA KUVAUS ---
    case_name = metadata.get('name') or (geometry_data.get('name') if geometry_data else None)
    case_desc = metadata.get('description') or (geometry_data.get('description') if geometry_data else None)
    
    if case_name or case_desc:
        ax.text(0.08, y_pos, subtitle_case, ha='left', va='top', fontsize=11, fontweight='bold')
        y_pos -= 0.025
        
        if case_name:
            ax.text(0.10, y_pos, f"{case_label}: {case_name}", ha='left', va='top', fontsize=10)
            y_pos -= 0.022
        
        if case_desc:
            # Rajoita kuvauksen pituutta
            desc_short = case_desc[:100] + "..." if len(case_desc) > 100 else case_desc
            ax.text(0.10, y_pos, f"{desc_label}: {desc_short}", ha='left', va='top', fontsize=9, 
                   color=TEXT_GRAY, wrap=True)
            y_pos -= 0.03
        
        y_pos -= 0.01
    
    # --- HILA-ASETUKSET ---
    nested_settings = metadata.get('nested_grid_settings') or (report_data.get('nested_grid') if report_data else None)
    turb_model = metadata.get('turbulence_model', 'sst')
    
    # Valitse otsikko nested/standard grid mukaan
    subtitle_grid = subtitle_grid_nested if nested_settings else subtitle_grid_standard
    ax.text(0.08, y_pos, subtitle_grid, ha='left', va='top', fontsize=11, fontweight='bold')
    y_pos -= 0.025
    
    # Turbulenssimalli
    turb_display = {'sst': 'SST k-ω', 'k-epsilon': 'k-ε', 'k-omega': 'k-ω'}.get(turb_model, turb_model.upper())
    ax.text(0.10, y_pos, f"{turb_label}: {turb_display}", ha='left', va='top', fontsize=10)
    y_pos -= 0.022
    
    if nested_settings:
        # Tiheä alue
        fine_region = nested_settings.get('fine_region')
        if fine_region:
            fine_x = f"x=[{fine_region.get('x_min', 0):.0f}, {fine_region.get('x_max', 0):.0f}]"
            fine_y = f"y=[{fine_region.get('y_min', 0):.0f}, {fine_region.get('y_max', 0):.0f}]"
            ax.text(0.10, y_pos, f"{fine_area_label}: {fine_x}, {fine_y}", ha='left', va='top', fontsize=10)
            y_pos -= 0.022
        
        # Tihennyskerroin
        refinement = nested_settings.get('refinement_factor', 4)
        ax.text(0.10, y_pos, f"{refinement_label}: {refinement}×", ha='left', va='top', fontsize=10)
        y_pos -= 0.022
        
        # Karkea hila
        coarse_nx = nested_settings.get('coarse_nx')
        coarse_ny = nested_settings.get('coarse_ny')
        coarse_dx = nested_settings.get('coarse_dx')
        if coarse_nx and coarse_ny:
            coarse_cells = coarse_nx * coarse_ny
            coarse_str = f"{coarse_nx} × {coarse_ny} ({coarse_cells:,} {cells_label})"
            if coarse_dx:
                coarse_str += f", dx={coarse_dx:.2f} m"
            ax.text(0.10, y_pos, f"{coarse_grid_label}: {coarse_str}", ha='left', va='top', fontsize=10)
            y_pos -= 0.022
        
        # Tiheä hila
        fine_nx = nested_settings.get('fine_nx')
        fine_ny = nested_settings.get('fine_ny')
        fine_dx = nested_settings.get('fine_dx')
        if fine_nx and fine_ny:
            fine_cells = fine_nx * fine_ny
            fine_str = f"{fine_nx} × {fine_ny} ({fine_cells:,} {cells_label})"
            if fine_dx:
                fine_str += f", dx={fine_dx:.2f} m"
            ax.text(0.10, y_pos, f"{fine_grid_label}: {fine_str}", ha='left', va='top', fontsize=10)
            y_pos -= 0.022
    else:
        # Tavallinen hila (ei nested)
        grid_info = metadata.get('grid', {})
        if grid_info:
            nx = grid_info.get('nx')
            ny = grid_info.get('ny')
            dx = grid_info.get('dx')
            if nx and ny:
                cells = nx * ny
                grid_str = f"{nx} × {ny} ({cells:,} {cells_label})"
                if dx:
                    grid_str += f", dx={dx:.2f} m"
                ax.text(0.10, y_pos, f"{grid_label}: {grid_str}", ha='left', va='top', fontsize=10)
                y_pos -= 0.022
    
    y_pos -= 0.02
    
    # --- SIJAINTI JA SÄÄASEMA ---
    ax.text(0.08, y_pos, subtitle_location, ha='left', va='top', fontsize=11, fontweight='bold')
    y_pos -= 0.025
    
    city = metadata.get('city') or 'Tuntematon'
    ax.text(0.10, y_pos, f"{city_label}: {city}", ha='left', va='top', fontsize=10)
    y_pos -= 0.04
    
    # --- POHJOISTUULI (vain multi-wind raportissa) ---
    simulations = metadata.get('simulations', [])
    is_multi_wind = len(simulations) > 1
    
    if is_multi_wind:
        ax.text(0.08, y_pos, subtitle_north, ha='left', va='top', fontsize=11, fontweight='bold')
        y_pos -= 0.025
        
        include_north = metadata.get('include_north', False)
        north_info = metadata.get('north_cooling_merged', {})
        
        if include_north and north_info:
            ax.text(0.10, y_pos, f"• {north_added}", ha='left', va='top', fontsize=9)
            y_pos -= 0.02
            
            merged_from = north_info.get('merged_from', [])
            if merged_from:
                merged_str = ', '.join(merged_from)
                cooling_weight = north_info.get('cooling_weight', 0)
                ax.text(0.10, y_pos, f"• {north_weight_label}: {merged_str} ({cooling_weight:.1%})", 
                       ha='left', va='top', fontsize=9)
                y_pos -= 0.02
        else:
            ax.text(0.10, y_pos, f"• {no_north}", ha='left', va='top', fontsize=9)
            y_pos -= 0.02
        
        y_pos -= 0.02
    
    # --- SIMULOIDUT TUULENSUUNNAT ---
    ax.text(0.08, y_pos, subtitle_directions, ha='left', va='top', fontsize=11, fontweight='bold')
    y_pos -= 0.03
    
    simulations = metadata.get('simulations', [])
    
    # Jos ei simulations-listaa mutta on yksittäinen tuulensuunta
    if not simulations and (metadata.get('wind_direction') is not None or metadata.get('inlet_direction') is not None):
        direction = metadata.get('wind_direction', metadata.get('inlet_direction', 0))
        velocity = metadata.get('inlet_velocity', 5.0)
        
        # Muunna CFD-asteet meteorologisiksi
        meteo_deg = (270 - direction + 360) % 360
        dirs = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 
               'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW']
        idx = int((meteo_deg + 11.25) / 22.5) % 16
        dir_name = dirs[idx]
        
        if lang == 'en':
            ax.text(0.10, y_pos, f"Single direction simulation:", ha='left', va='top', fontsize=10, fontweight='bold')
        else:
            ax.text(0.10, y_pos, f"Yhden suunnan simulointi:", ha='left', va='top', fontsize=10, fontweight='bold')
        y_pos -= 0.025
        
        if lang == 'en':
            ax.text(0.10, y_pos, f"• Direction: {dir_name} ({direction:.0f}° CFD / {meteo_deg:.0f}° meteo)", ha='left', va='top', fontsize=10)
        else:
            ax.text(0.10, y_pos, f"• Suunta: {dir_name} ({direction:.0f}° CFD / {meteo_deg:.0f}° meteo)", ha='left', va='top', fontsize=10)
        y_pos -= 0.022
        
        if lang == 'en':
            ax.text(0.10, y_pos, f"• Wind speed: {velocity:.1f} m/s", ha='left', va='top', fontsize=10)
        else:
            ax.text(0.10, y_pos, f"• Tuulennopeus: {velocity:.1f} m/s", ha='left', va='top', fontsize=10)
        y_pos -= 0.022
        
        # Hilan tiedot on nyt Hila-asetukset -osiossa, ei tarvitse toistaa tässä
    
    elif simulations:
        # Taulukko
        # Sarakkeiden x-positiot
        col_x = [0.10, 0.20, 0.35, 0.50, 0.65]
        
        # Otsikkorivi
        for i, header in enumerate(col_headers):
            weight = 'bold' if i == 0 else 'normal'
            ax.text(col_x[i], y_pos, header, ha='left', va='top', fontsize=9, fontweight='bold')
        y_pos -= 0.025
        
        # Viiva otsikon alle
        ax.axhline(y=y_pos + 0.01, xmin=0.08, xmax=0.80, color='gray', linewidth=0.5)
        y_pos -= 0.005
        
        # Datarivit
        total_weight = 0
        for i, sim in enumerate(simulations, 1):
            direction_name = sim.get('direction_name', f"{sim.get('inlet_direction', 0):.0f}°")
            angle = sim.get('inlet_direction', 0)
            weight = sim.get('weight', 0)
            speed = sim.get('inlet_velocity', 0)
            total_weight += weight
            
            # Yhdistetty-merkintä jos merged_from löytyy
            merged_info = ""
            if 'merged_from' in sim:
                merged_info = f" *"
            
            row_data = [
                f"{i}.",
                f"{direction_name}{merged_info}",
                f"{angle:.0f}°",
                f"{weight:.1%}",
                f"{speed:.1f} m/s"
            ]
            
            for j, val in enumerate(row_data):
                ax.text(col_x[j], y_pos, val, ha='left', va='top', fontsize=9)
            y_pos -= 0.022
        
        # Viiva summan ylle
        ax.axhline(y=y_pos + 0.01, xmin=0.08, xmax=0.80, color='gray', linewidth=0.5)
        y_pos -= 0.005
        
        # Yhteensä-rivi
        ax.text(col_x[0], y_pos, "", ha='left', va='top', fontsize=9)
        ax.text(col_x[1], y_pos, total_label, ha='left', va='top', fontsize=9, fontweight='bold')
        ax.text(col_x[2], y_pos, f"{len(simulations)} kpl", ha='left', va='top', fontsize=9)
        ax.text(col_x[3], y_pos, f"{total_weight:.1%}", ha='left', va='top', fontsize=9, fontweight='bold')
        y_pos -= 0.03
        
        # Selite merged-suunnille
        has_merged = any('merged_from' in s for s in simulations)
        if has_merged:
            if lang == 'en':
                ax.text(0.10, y_pos, "* Merged from nearby directions", ha='left', va='top', fontsize=8, style='italic')
            else:
                ax.text(0.10, y_pos, "* Yhdistetty läheisistä suunnista", ha='left', va='top', fontsize=8, style='italic')
    
    pdf.savefig(fig)
    plt.close(fig)


def parse_comfort_report(filepath: Path) -> Dict:
    """
    Parsii comfort_report.txt tiedoston ja palauttaa arvot dictinä.
    
    Args:
        filepath: Polku comfort_report.txt tiedostoon
        
    Returns:
        Dict arvoista: {'mean': float, 'max': float, 'pct_calm': float, ...}
    """
    result = {}
    
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        lines = content.split('\n')
        for line in lines:
            line = line.strip()
            
            # Keskiarvo
            if 'Keskiarvo:' in line:
                try:
                    val = line.split(':')[1].strip().replace('m/s', '').strip()
                    result['mean'] = float(val)
                except:
                    pass
            
            # Maksimi
            elif 'Maksimi:' in line:
                try:
                    val = line.split(':')[1].strip().replace('m/s', '').strip()
                    result['max'] = float(val)
                except:
                    pass
            
            # Rauhallinen
            elif 'Rauhallinen' in line and '%' in line:
                try:
                    val = line.split(':')[1].strip().replace('%', '').strip()
                    result['pct_calm'] = float(val)
                except:
                    pass
            
            # Miellyttävä
            elif 'Miellyttävä' in line and '%' in line:
                try:
                    val = line.split(':')[1].strip().replace('%', '').strip()
                    result['pct_pleasant'] = float(val)
                except:
                    pass
            
            # Kohtalainen
            elif 'Kohtalainen' in line and '%' in line:
                try:
                    val = line.split(':')[1].strip().replace('%', '').strip()
                    result['pct_moderate'] = float(val)
                except:
                    pass
            
            # Tuulinen
            elif 'Tuulinen' in line and '%' in line:
                try:
                    val = line.split(':')[1].strip().replace('%', '').strip()
                    result['pct_windy'] = float(val)
                except:
                    pass
            
            # Epämukava
            elif 'Epämukava' in line and '%' in line:
                try:
                    val = line.split(':')[1].strip().replace('%', '').strip()
                    result['pct_uncomfortable'] = float(val)
                except:
                    pass
    
    except Exception as e:
        pass
    
    return result


def load_weighted_comfort_stats(results_dir: Path) -> Tuple[Dict, str]:
    """
    Lataa comfort_report.txt tiedostot kaikista tuulensuunnista ja laskee painotetut arvot.
    
    Args:
        results_dir: Multi-wind tulosten päähakemisto
        
    Returns:
        (weighted_stats, report_text) - painotetut tilastot ja raporttiteksti
    """
    results_dir = Path(results_dir)
    
    # Lataa metadata painojen saamiseksi
    metadata_path = results_dir / 'multi_wind_metadata.json'
    if not metadata_path.exists():
        # Yritä parent-kansiosta (jos ollaan combined/-kansiossa)
        metadata_path = results_dir.parent / 'multi_wind_metadata.json'
    
    if not metadata_path.exists():
        return {}, ""
    
    try:
        with open(metadata_path, 'r', encoding='utf-8') as f:
            metadata = json.load(f)
    except:
        return {}, ""
    
    # Kerää tuulensuuntien tiedot
    all_stats = []
    total_weight = 0.0
    
    for sim in metadata.get('results', []):
        if not sim.get('converged', False):
            continue
        
        direction = sim.get('direction', 0)
        weight = sim.get('weight', 0.1)
        sim_dir = Path(sim.get('output_dir', ''))
        
        # Etsi comfort_report.txt
        comfort_files = [
            sim_dir / 'fine' / 'comfort_report.txt',
            sim_dir / 'comfort_report.txt',
            sim_dir / 'fine' / 'comfort_report_nested.txt',
            sim_dir / 'comfort_report_nested.txt',
        ]
        
        stats = None
        for cf in comfort_files:
            if cf.exists():
                stats = parse_comfort_report(cf)
                if stats:
                    break
        
        if stats and 'mean' in stats:
            stats['weight'] = weight
            stats['direction'] = direction
            all_stats.append(stats)
            total_weight += weight
    
    if not all_stats or total_weight < 0.01:
        return {}, ""
    
    # Laske painotetut keskiarvot
    weighted = {
        'mean': 0.0,
        'max': 0.0,
        'pct_calm': 0.0,
        'pct_pleasant': 0.0,
        'pct_moderate': 0.0,
        'pct_windy': 0.0,
        'pct_uncomfortable': 0.0,
    }
    
    for stats in all_stats:
        w = stats['weight'] / total_weight
        for key in weighted.keys():
            if key in stats:
                weighted[key] += stats[key] * w
    
    # Etsi painotettu maksimi (suurin yksittäisistä maksimoista)
    weighted['max'] = max(s.get('max', 0) for s in all_stats)
    
    # Generoi raporttiteksti samassa formaatissa kuin comfort_report.txt
    report_text = (
        f"=== Tuulisuusraportti: Painotettu (kaikki suunnat) ===\n\n"
        f"  Keskiarvo: {weighted['mean']:.2f} m/s\n"
        f"  Maksimi:   {weighted['max']:.2f} m/s\n\n"
        f"Tuulisuusvyöhykkeet:\n"
        f"  Rauhallinen (<1.5 m/s):  {weighted['pct_calm']:.1f}%\n"
        f"  Miellyttävä (1.5-3 m/s): {weighted['pct_pleasant']:.1f}%\n"
        f"  Kohtalainen (3-5 m/s):   {weighted['pct_moderate']:.1f}%\n"
        f"  Tuulinen (5-8 m/s):      {weighted['pct_windy']:.1f}%\n"
        f"  Epämukava (>8 m/s):      {weighted['pct_uncomfortable']:.1f}%"
    )
    
    return weighted, report_text


def add_windiness_analysis_page(pdf: PdfPages, section_num: int, lang: str = 'fi',
                                 results_dir: Path = None, single_direction_stats: Dict = None,
                                 wind_direction: str = None):
    """
    Lisää tuulisuusanalyysisivu (Lawsonin kriteerit) raporttiin.
    
    Näyttää kolme taulukkoa:
    1. Alkuperäiset Lawsonin kriteerit (2m jalankulkijataso)
    2. Skaalatut kriteerit simuloinnin korkeuteen (10m, urbaani α=0.25)
    3. Simuloinnin tulokset
    
    Args:
        pdf: PdfPages-objekti
        section_num: Osion numero
        lang: Kieli 'fi' tai 'en'
        results_dir: Tuloskansio painotetun raportin lataamiseen (multi-wind)
        single_direction_stats: Dict yksittäisen suunnan statistiikoista (yksittäinen suunta)
        wind_direction: Tuulensuunnan nimi (esim. "SW (45°)")
    """
    fig, ax = plt.subplots(figsize=(8.27, 11.69))  # A4
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis('off')
    
    y_pos = 0.94
    
    # Tekstit kieliversioittain
    if lang == 'en':
        title = f"{section_num}. Wind Comfort Analysis"
        subtitle_original = "Lawson Criteria - Original (2m pedestrian level)"
        subtitle_scaled = "Lawson Criteria - Scaled to 10m height (urban terrain, α=0.25)"
        subtitle_results = "Simulation Results"
        
        zone_names = ['Calm', 'Pleasant', 'Moderate', 'Windy', 'Uncomfortable']
        col_headers_original = ['Zone', 'Speed limit', 'Description']
        col_headers_scaled = ['Zone', 'Speed limit (10m)', 'Scaling factor']
        col_headers_results = ['Zone', 'Speed range', 'Area percentage']
        
        descriptions_original = [
            'Suitable for long-term sitting',
            'Suitable for short-term standing',
            'Suitable for walking',
            'Windy, short exposure only',
            'Avoid long exposure'
        ]
        
        scale_note = "Scaling factor: (10m / 2m)^0.25 ≈ 1.5"
    else:
        title = f"{section_num}. Tuulisuusanalyysi"
        subtitle_original = "Lawsonin kriteerit - Alkuperäiset (2m jalankulkijataso)"
        subtitle_scaled = "Lawsonin kriteerit - Skaalattu 10m korkeuteen (urbaani maasto, α=0.25)"
        subtitle_results = "Simuloinnin tulokset"
        
        zone_names = ['Rauhallinen', 'Miellyttävä', 'Kohtalainen', 'Tuulinen', 'Epämukava']
        col_headers_original = ['Vyöhyke', 'Nopeusraja', 'Kuvaus']
        col_headers_scaled = ['Vyöhyke', 'Nopeusraja (10m)', 'Skaalauskerroin']
        col_headers_results = ['Vyöhyke', 'Nopeusalue', 'Osuus alueesta']
        
        descriptions_original = [
            'Sopii pitkäaikaiseen istuskeluun',
            'Sopii lyhytaikaiseen seisoskeluun',
            'Sopii kävelyyn',
            'Tuulinen, vain lyhyt oleskelu',
            'Vältä pitkää oleskelua'
        ]
        
        scale_note = "Skaalauskerroin: (10m / 2m)^0.25 ≈ 1.5"
    
    # Alkuperäiset raja-arvot (2m)
    limits_2m = ['< 1.5 m/s', '1.5 - 3 m/s', '3 - 5 m/s', '5 - 8 m/s', '> 8 m/s']
    
    # Skaalatut raja-arvot (10m, kerroin 1.5)
    limits_10m = ['< 2.0 m/s', '2.0 - 4.5 m/s', '4.5 - 7.5 m/s', '7.5 - 12 m/s', '> 12 m/s']
    scale_factors = ['×1.5', '×1.5', '×1.5', '×1.5', '×1.5']
    
    # Pääotsikko
    ax.text(0.08, y_pos, title, ha='left', va='top', fontsize=14, fontweight='bold', color=DARK_BLUE)
    y_pos -= 0.045
    
    # ========== TAULUKKO 1: Alkuperäiset Lawsonin kriteerit ==========
    ax.text(0.08, y_pos, subtitle_original, ha='left', va='top', fontsize=10, fontweight='bold')
    y_pos -= 0.025
    
    # Taulukon parametrit
    row_height = 0.022
    col_widths_orig = [0.18, 0.15, 0.45]
    col_starts_orig = [0.08, 0.26, 0.41]
    
    # Otsikkorivi
    for i, (header, x) in enumerate(zip(col_headers_original, col_starts_orig)):
        if i == 2:  # Kuvaus-sarake - vasemmalle tasattu kuten data
            ax.text(x + 0.01, y_pos, header, ha='left', va='center', 
                    fontsize=8, fontweight='bold', color='white',
                    bbox=dict(boxstyle='square,pad=0.3', facecolor=DARK_BLUE, edgecolor='none'))
        else:
            ax.text(x + col_widths_orig[i]/2, y_pos, header, ha='center', va='center', 
                    fontsize=8, fontweight='bold', color='white',
                    bbox=dict(boxstyle='square,pad=0.3', facecolor=DARK_BLUE, edgecolor='none'))
    y_pos -= row_height + 0.005
    
    # Datarivit
    for i, (zone, limit, desc) in enumerate(zip(zone_names, limits_2m, descriptions_original)):
        bg_color = '#f8f9fa' if i % 2 == 0 else 'white'
        # Tausta
        ax.fill_between([col_starts_orig[0] - 0.01, col_starts_orig[-1] + col_widths_orig[-1] + 0.01], 
                        y_pos - row_height/2, y_pos + row_height/2, color=bg_color, alpha=0.5)
        # Tekstit
        ax.text(col_starts_orig[0] + col_widths_orig[0]/2, y_pos, zone, ha='center', va='center', fontsize=8)
        ax.text(col_starts_orig[1] + col_widths_orig[1]/2, y_pos, limit, ha='center', va='center', fontsize=8, family='monospace')
        ax.text(col_starts_orig[2] + 0.01, y_pos, desc, ha='left', va='center', fontsize=8)
        y_pos -= row_height
    
    y_pos -= 0.02
    
    # ========== TAULUKKO 2: Skaalatut kriteerit ==========
    ax.text(0.08, y_pos, subtitle_scaled, ha='left', va='top', fontsize=10, fontweight='bold')
    y_pos -= 0.025
    
    col_widths_scaled = [0.18, 0.20, 0.18]
    col_starts_scaled = [0.08, 0.26, 0.46]
    
    # Otsikkorivi
    for i, (header, x) in enumerate(zip(col_headers_scaled, col_starts_scaled)):
        ax.text(x + col_widths_scaled[i]/2, y_pos, header, ha='center', va='center', 
                fontsize=8, fontweight='bold', color='white',
                bbox=dict(boxstyle='square,pad=0.3', facecolor='#2874a6', edgecolor='none'))
    y_pos -= row_height + 0.005
    
    # Datarivit
    for i, (zone, limit, factor) in enumerate(zip(zone_names, limits_10m, scale_factors)):
        bg_color = '#eaf2f8' if i % 2 == 0 else 'white'
        ax.fill_between([col_starts_scaled[0] - 0.01, col_starts_scaled[-1] + col_widths_scaled[-1] + 0.01], 
                        y_pos - row_height/2, y_pos + row_height/2, color=bg_color, alpha=0.5)
        ax.text(col_starts_scaled[0] + col_widths_scaled[0]/2, y_pos, zone, ha='center', va='center', fontsize=8)
        ax.text(col_starts_scaled[1] + col_widths_scaled[1]/2, y_pos, limit, ha='center', va='center', fontsize=8, family='monospace', fontweight='bold')
        ax.text(col_starts_scaled[2] + col_widths_scaled[2]/2, y_pos, factor, ha='center', va='center', fontsize=8, color='#666666')
        y_pos -= row_height
    
    # Skaalausnote
    ax.text(0.08, y_pos - 0.005, scale_note, ha='left', va='top', fontsize=7, style='italic', color='#666666')
    y_pos -= 0.035
    
    # ========== TAULUKKO 3: Simuloinnin tulokset ==========
    # Hae tulokset
    stats = None
    dir_name = ""
    
    if single_direction_stats:
        stats = single_direction_stats
        dir_name = wind_direction or ""
    elif results_dir:
        weighted_stats, _ = load_weighted_comfort_stats(results_dir)
        if weighted_stats:
            stats = weighted_stats
            dir_name = "Painotettu (kaikki suunnat)" if lang == 'fi' else "Weighted (all directions)"
    
    if stats:
        result_title = f"{subtitle_results}"
        if dir_name:
            result_title += f" - {dir_name}"
        
        ax.text(0.08, y_pos, result_title, ha='left', va='top', fontsize=10, fontweight='bold')
        y_pos -= 0.025
        
        col_widths_results = [0.18, 0.20, 0.18]
        col_starts_results = [0.08, 0.26, 0.46]
        
        # Otsikkorivi
        for i, (header, x) in enumerate(zip(col_headers_results, col_starts_results)):
            ax.text(x + col_widths_results[i]/2, y_pos, header, ha='center', va='center', 
                    fontsize=8, fontweight='bold', color='white',
                    bbox=dict(boxstyle='square,pad=0.3', facecolor='#148f77', edgecolor='none'))
        y_pos -= row_height + 0.005
        
        # Tulokset skaalatulla asteikolla (10m)
        result_ranges = limits_10m
        result_values = [
            stats.get('pct_calm', 0),
            stats.get('pct_pleasant', 0),
            stats.get('pct_moderate', 0),
            stats.get('pct_windy', 0),
            stats.get('pct_uncomfortable', 0)
        ]
        
        # Värit tulosten mukaan
        result_colors = ['#27ae60', '#2ecc71', '#f1c40f', '#e67e22', '#e74c3c']
        
        for i, (zone, rng, val, color) in enumerate(zip(zone_names, result_ranges, result_values, result_colors)):
            bg_color = '#e8f8f5' if i % 2 == 0 else 'white'
            ax.fill_between([col_starts_results[0] - 0.01, col_starts_results[-1] + col_widths_results[-1] + 0.01], 
                            y_pos - row_height/2, y_pos + row_height/2, color=bg_color, alpha=0.5)
            ax.text(col_starts_results[0] + col_widths_results[0]/2, y_pos, zone, ha='center', va='center', fontsize=8)
            ax.text(col_starts_results[1] + col_widths_results[1]/2, y_pos, rng, ha='center', va='center', fontsize=8, family='monospace')
            # Prosenttiarvo värikoodattuna
            ax.text(col_starts_results[2] + col_widths_results[2]/2, y_pos, f'{val:.1f}%', 
                    ha='center', va='center', fontsize=9, fontweight='bold', color=color)
            y_pos -= row_height
        
        # Yhteenveto
        y_pos -= 0.01
        mean_val = stats.get('mean', 0)
        max_val = stats.get('max', 0)
        if lang == 'en':
            summary = f"Mean: {mean_val:.1f} m/s  |  Maximum: {max_val:.1f} m/s"
        else:
            summary = f"Keskiarvo: {mean_val:.1f} m/s  |  Maksimi: {max_val:.1f} m/s"
        ax.text(0.08, y_pos, summary, ha='left', va='top', fontsize=9, fontweight='bold', color=DARK_BLUE)
        y_pos -= 0.04
    
    pdf.savefig(fig)
    plt.close(fig)


def add_building_physics_page(pdf: PdfPages, section_num: int, lang: str = 'fi'):
    """
    Lisää Rakennusfysiikan tulkinta -sivu raporttiin.
    
    Tämä sivu selittää tuulianalyysin tulosten merkityksen rakennusfysiikan kannalta.
    
    Args:
        pdf: PdfPages-objekti
        section_num: Osion numero
        lang: Kieli 'fi' tai 'en'
    """
    fig, ax = plt.subplots(figsize=(8.27, 11.69))  # A4
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis('off')
    
    y_pos = 0.94
    
    # Tekstit kieliversioittain
    if lang == 'en':
        title = f"{section_num}. Building Physics Interpretation"
        
        section1_title = "Wind Effects on Building Envelope"
        section1_items = [
            ("Overpressure (Cp > 0)", "Windward facade → moisture through joints"),
            ("Suction (Cp < 0)", "Leeward side and roof → cladding loads, vapor barrier critical"),
            ("High velocity zones", "Corners and gaps → enhanced cooling, driving rain"),
            ("Sheltered zones", "Building wakes → reduced cooling, moisture accumulation"),
        ]
        
        section2_title = "Convective Heat Transfer"
        section2_intro = "Convection index (√k × v) describes surface cooling intensity:"
        section2_items = [
            ("High convection", "Rapid cooling → condensation risk, frost damage"),
            ("High turbulence", "Enhances heat and moisture transfer"),
            ("Temperature correction", "North winds weighted higher (colder air)"),
        ]
        
        section3_title = "Friction Velocity and Surface Heat Transfer"
        section3_intro = "Friction velocity (u_τ) links directly to heat transfer coefficient:"
        section3_items = [
            ("Heat transfer", "h ≈ ρ·cp·u_τ/T+ — higher u_τ = more efficient transfer"),
            ("Moisture drying", "High u_τ → faster evaporation from facade"),
            ("Pressure distribution", "High u_τ → accelerated flow, local suction"),
        ]
        
        section4_title = "Turbulence Intensity"
        section4_intro = "TI describes wind gustiness relative to mean speed:"
        section4_items = [
            ("Dynamic loads", "High TI (>30%) → fatigue stress on joints"),
            ("Pedestrian comfort", "High TI causes discomfort at moderate speeds"),
            ("Heat transfer peaks", "Gustiness enhances momentary transfers"),
        ]
        
    else:
        title = f"{section_num}. Rakennusfysiikan tulkinta"
        
        section1_title = "Tuulen vaikutukset rakennuksen vaippaan"
        section1_items = [
            ("Ylipaine (Cp > 0)", "Tuulen puoli → kosteus tunkeutuu saumoista"),
            ("Alipaine (Cp < 0)", "Suojan puoli ja katto → imurasitus, höyrynsulku kriittinen"),
            ("Korkea nopeus", "Nurkat ja välit → tehostunut jäähtyminen, viistosade"),
            ("Suojaisat vyöhykkeet", "Rakennusten takana → vähemmän jäähtymistä"),
        ]
        
        section2_title = "Konvektiivinen lämmönsiirto"
        section2_intro = "Konvektioindeksi (√k × v) kuvaa pinnan jäähtymisintensiteettiä:"
        section2_items = [
            ("Korkea konvektio", "Nopea jäähtyminen → kondenssi, pakkasrapautuminen"),
            ("Korkea turbulenssi", "Tehostaa lämmön- ja kosteuden siirtoa"),
            ("Lämpötilakorjaus", "Pohjoistuulet painotetaan (kylmempi ilma)"),
        ]
        
        section3_title = "Kitkanopeus ja pinnan lämmönsiirto"
        section3_intro = "Kitkanopeus (u_τ) kytkeytyy suoraan lämmönsiirtokertoimeen:"
        section3_items = [
            ("Lämmönsiirto", "h ≈ ρ·cp·u_τ/T+ — korkeampi u_τ = tehokkaampi siirto"),
            ("Kuivuminen", "Korkea u_τ → nopeampi haihtuminen julkisivulta"),
            ("Painejakauma", "Korkea u_τ → kiihtynyt virtaus, alipaine"),
        ]
        
        section4_title = "Turbulenssi-intensiteetti"
        section4_intro = "TI kuvaa tuulen puuskaisuutta suhteessa keskinopeuteen:"
        section4_items = [
            ("Dynaamiset kuormat", "Korkea TI (>30%) → väsymisrasitus saumoille"),
            ("Jalankulkijaviihtyvyys", "Korkea TI → epämukavuutta kohtuullisillakin nopeuksilla"),
            ("Lämmönsiirron huiput", "Puuskaisuus tehostaa hetkellisiä siirtoja"),
        ]
    
    # Otsikko vaaleansinisellä taustalla
    header_y = 0.94
    ax.fill_between([0.05, 0.95], header_y - 0.025, header_y + 0.015, 
                    color=LIGHT_BLUE, alpha=1.0)
    ax.text(0.5, header_y - 0.005, title, 
            ha='center', va='center', fontsize=TITLE_SIZE, fontweight='bold', color=DARK_BLUE)
    
    y_pos = 0.87
    
    # Apufunktio osion piirtämiseen
    def draw_section(y, section_title, items, intro=None):
        ax.text(0.08, y, section_title, ha='left', va='top', fontsize=11, fontweight='bold', color=DARK_BLUE)
        y -= 0.035
        
        if intro:
            ax.text(0.08, y, intro, ha='left', va='top', fontsize=9, style='italic', color='#555555')
            y -= 0.03
        
        for label, description in items:
            # Yhdistä label ja description yhdeksi tekstiksi
            full_text = f"• {label}: {description}"
            ax.text(0.10, y, full_text, ha='left', va='top', fontsize=9, color='#333333')
            y -= 0.04  # Riittävä väli seuraavaan
        
        return y - 0.01  # Lisätila osioiden väliin
    
    # Piirrä osiot
    y_pos = draw_section(y_pos, section1_title, section1_items)
    y_pos = draw_section(y_pos, section2_title, section2_items, section2_intro)
    y_pos = draw_section(y_pos, section3_title, section3_items, section3_intro)
    y_pos = draw_section(y_pos, section4_title, section4_items, section4_intro)
    
    pdf.savefig(fig)
    plt.close(fig)


def add_wind_direction_analysis_page(pdf: PdfPages, dominance_data: list, section_num: int, lang: str = 'fi'):
    """
    Lisää tuulensuunta-analyysisivu, joka näyttää dominoivat tuulensuunnat taulukkona.
    
    Args:
        pdf: PdfPages-objekti
        dominance_data: Lista tuulensuunta-analyysin tuloksista
        section_num: Osion numero
        lang: Kieli 'fi' tai 'en'
    """
    if not dominance_data:
        return
    
    fig, ax = plt.subplots(figsize=(8.27, 11.69))  # A4
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis('off')
    
    # Osion otsikko
    if lang == 'en':
        title = f"{section_num}. Wind Direction Dominance Analysis"
        description = (
            "This table shows which wind directions have the greatest impact on the area. "
            "The analysis is based on comparing maximum pressure and velocity fields from each simulated direction."
        )
        col_headers = ['Direction', 'Weight\n(frequency)', 'Pressure\ndominance', 'Velocity\ndominance', 'Combined\nimpact']
        interpretation_title = "Interpretation"
        interpretations = [
            "• Pressure dominance: Percentage of area where this direction causes maximum surface pressure",
            "• Velocity dominance: Percentage of area where this direction causes maximum wind speed",
            "• Combined impact: Average of pressure and velocity dominance - indicates overall criticality",
            "• Weight: Annual frequency of wind from this direction (from meteorological data)"
        ]
        key_findings_title = "Key Findings"
    else:
        title = f"{section_num}. Tuulensuuntien dominanssianalyysi"
        description = (
            "Taulukko näyttää mitkä tuulensuunnat vaikuttavat eniten alueella. "
            "Analyysi perustuu maksimipaine- ja nopeuskenttien vertailuun kustakin simuloidusta suunnasta."
        )
        col_headers = ['Suunta', 'Paino\n(esiintyvyys)', 'Paine-\ndominanssi', 'Nopeus-\ndominanssi', 'Yhdistetty\nvaikutus']
        interpretation_title = "Tulkinta"
        interpretations = [
            "• Painedominanssi: Osuus alueesta, jossa tämä suunta aiheuttaa maksimipaineen",
            "• Nopeusdominanssi: Osuus alueesta, jossa tämä suunta aiheuttaa maksiminopeuden", 
            "• Yhdistetty vaikutus: Paine- ja nopeusdominanssin keskiarvo - kuvaa kokonaiskriittisyyttä",
            "• Paino: Tuulen vuotuinen esiintyvyys tästä suunnasta (säähavainnoista)"
        ]
        key_findings_title = "Keskeiset havainnot"
    
    # Otsikko vaaleansinisellä taustalla
    header_y = 0.94
    ax.fill_between([0.05, 0.95], header_y - 0.025, header_y + 0.015, 
                    color=LIGHT_BLUE, alpha=1.0)
    ax.text(0.5, header_y - 0.005, title, 
            ha='center', va='center', fontsize=TITLE_SIZE, fontweight='bold', color=DARK_BLUE)
    
    # Kuvaus
    ax.text(0.08, 0.88, description,
            ha='left', va='top', fontsize=BODY_SIZE, style='italic', color=TEXT_GRAY,
            wrap=True)
    
    # Taulukko
    table_y_start = 0.82
    row_height = 0.035
    col_widths = [0.14, 0.16, 0.16, 0.16, 0.16]
    col_starts = [0.10]
    for w in col_widths[:-1]:
        col_starts.append(col_starts[-1] + w)
    
    # Otsikkorivi
    for col_idx, header in enumerate(col_headers):
        ax.text(col_starts[col_idx] + col_widths[col_idx]/2, table_y_start,
                header, ha='center', va='top', fontsize=CAPTION_SIZE, fontweight='bold',
                color=DARK_BLUE)
    
    # Vaakaviiva otsikon alla
    ax.plot([0.08, 0.90], [table_y_start - 0.025, table_y_start - 0.025], 
            color=ACCENT_BLUE, linewidth=1)
    
    # Datarivit
    for row_idx, item in enumerate(dominance_data[:8]):  # Max 8 suuntaa
        y = table_y_start - 0.035 - row_idx * row_height
        
        # Taustaväri joka toiselle riville
        if row_idx % 2 == 0:
            ax.fill_between([0.08, 0.90], y - row_height/2 + 0.005, y + row_height/2 - 0.005,
                           color='#f8f9fa', alpha=0.8)
        
        # Suunta (asteina ja suuntana)
        direction_deg = item.get('direction', 0)
        direction_name = item.get('direction_name', '')
        if not direction_name:
            # Muunna CFD-asteet meteorologisiksi (kompassi)
            # CFD: 0°=W-tuuli, 90°=S-tuuli, 180°=E-tuuli, 270°=N-tuuli
            # Meteo: 0°=N-tuuli, 90°=E-tuuli, 180°=S-tuuli, 270°=W-tuuli
            meteo_deg = (270 - direction_deg + 360) % 360
            dirs = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 
                   'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW']
            idx = int((meteo_deg + 11.25) / 22.5) % 16
            direction_name = dirs[idx]
        
        ax.text(col_starts[0] + col_widths[0]/2, y, 
                f"{direction_deg:.0f}° ({direction_name})",
                ha='center', va='center', fontsize=CAPTION_SIZE)
        
        # Paino (prosentteina)
        weight = item.get('weight', 0)
        ax.text(col_starts[1] + col_widths[1]/2, y, 
                f"{weight*100:.1f}%",
                ha='center', va='center', fontsize=CAPTION_SIZE)
        
        # Painedominanssi
        p_dom = item.get('pressure_dominant_pct', 0)
        color = '#c0392b' if p_dom > 20 else '#27ae60' if p_dom < 10 else TEXT_DARK
        ax.text(col_starts[2] + col_widths[2]/2, y, 
                f"{p_dom:.1f}%",
                ha='center', va='center', fontsize=CAPTION_SIZE, color=color, fontweight='bold' if p_dom > 20 else 'normal')
        
        # Nopeusdominanssi
        v_dom = item.get('velocity_dominant_pct', 0)
        color = '#c0392b' if v_dom > 20 else '#27ae60' if v_dom < 10 else TEXT_DARK
        ax.text(col_starts[3] + col_widths[3]/2, y, 
                f"{v_dom:.1f}%",
                ha='center', va='center', fontsize=CAPTION_SIZE, color=color, fontweight='bold' if v_dom > 20 else 'normal')
        
        # Yhdistetty vaikutus
        combined = item.get('combined_impact', 0)
        color = '#c0392b' if combined > 20 else '#27ae60' if combined < 10 else TEXT_DARK
        ax.text(col_starts[4] + col_widths[4]/2, y, 
                f"{combined:.1f}%",
                ha='center', va='center', fontsize=CAPTION_SIZE, color=color, fontweight='bold' if combined > 20 else 'normal')
    
    # Vaakaviiva taulukon alla
    table_end_y = table_y_start - 0.035 - len(dominance_data[:8]) * row_height
    ax.plot([0.08, 0.90], [table_end_y + 0.015, table_end_y + 0.015], 
            color=ACCENT_BLUE, linewidth=0.5)
    
    # Tulkinta-osio
    interp_y = table_end_y - 0.03
    ax.text(0.08, interp_y, interpretation_title,
            ha='left', va='top', fontsize=SUBSECTION_SIZE, fontweight='bold', color=DARK_BLUE)
    
    interp_text = '\n'.join(interpretations)
    ax.text(0.08, interp_y - 0.025, interp_text,
            ha='left', va='top', fontsize=CAPTION_SIZE, color=TEXT_DARK, linespacing=1.4)
    
    # Keskeiset havainnot
    findings_y = interp_y - 0.15
    ax.text(0.08, findings_y, key_findings_title,
            ha='left', va='top', fontsize=SUBSECTION_SIZE, fontweight='bold', color=DARK_BLUE)
    
    # Generoi havainnot datasta
    if dominance_data:
        top = dominance_data[0]
        top_deg = top['direction']
        top_impact = top.get('combined_impact', 0)
        
        # Muunna CFD-asteet meteorologisiksi (kompassi)
        top_meteo = (270 - top_deg + 360) % 360
        dirs = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 
               'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW']
        top_idx = int((top_meteo + 11.25) / 22.5) % 16
        top_name = dirs[top_idx]
        top_dir = f"{top_deg:.0f}° ({top_name})"
        
        if lang == 'en':
            finding1 = f"• Most critical wind direction: {top_dir} (combined impact {top_impact:.1f}%)"
            if len(dominance_data) > 1:
                second = dominance_data[1]
                sec_deg = second['direction']
                sec_meteo = (270 - sec_deg + 360) % 360
                sec_idx = int((sec_meteo + 11.25) / 22.5) % 16
                sec_name = dirs[sec_idx]
                finding2 = f"• Secondary direction: {sec_deg:.0f}° ({sec_name}) ({second.get('combined_impact', 0):.1f}%)"
            else:
                finding2 = ""
            
            # Laske onko paineen vai nopeuden mukaan kriittisempi
            if top.get('pressure_dominant_pct', 0) > top.get('velocity_dominant_pct', 0):
                finding3 = f"• Primary concern: Surface pressure loading (moisture penetration risk)"
            else:
                finding3 = f"• Primary concern: Wind velocity (convective cooling, driving rain)"
        else:
            finding1 = f"• Kriittisin tuulensuunta: {top_dir} (yhdistetty vaikutus {top_impact:.1f}%)"
            if len(dominance_data) > 1:
                second = dominance_data[1]
                sec_deg = second['direction']
                sec_meteo = (270 - sec_deg + 360) % 360
                sec_idx = int((sec_meteo + 11.25) / 22.5) % 16
                sec_name = dirs[sec_idx]
                finding2 = f"• Toissijainen suunta: {sec_deg:.0f}° ({sec_name}) ({second.get('combined_impact', 0):.1f}%)"
            else:
                finding2 = ""
            
            if top.get('pressure_dominant_pct', 0) > top.get('velocity_dominant_pct', 0):
                finding3 = f"• Ensisijainen huoli: Pintapainerasitus (kosteuden tunkeutumisriski)"
            else:
                finding3 = f"• Ensisijainen huoli: Tuulinopeus (konvektiivinen jäähtyminen, viistosade)"
        
        findings_text = finding1
        if finding2:
            findings_text += '\n' + finding2
        findings_text += '\n' + finding3
        
        ax.text(0.08, findings_y - 0.025, findings_text,
                ha='left', va='top', fontsize=BODY_SIZE, color=TEXT_DARK, linespacing=1.3)
    
    pdf.savefig(fig)
    plt.close(fig)


def add_combined_summary_table(pdf: PdfPages, section_title: str, combined_data: dict = None, lang: str = 'fi'):
    """
    Lisää yhteenvetotaulukko yhdistettyjen kuormituskenttien selitteistä.
    
    Args:
        pdf: PdfPages-objekti
        section_title: Osion otsikko
        combined_data: Simuloinnista lasketut arvot (valinnainen)
        lang: Kieli 'fi' tai 'en'
    """
    fig, ax = plt.subplots(figsize=(8.27, 11.69))  # A4
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis('off')
    
    # Osion otsikko vaaleansinisellä taustalla (dokumentaation tyyli)
    header_y = 0.94
    ax.fill_between([0.05, 0.95], header_y - 0.025, header_y + 0.015, 
                    color=LIGHT_BLUE, alpha=1.0)
    ax.text(0.5, header_y - 0.005, section_title, 
            ha='center', va='center', fontsize=TITLE_SIZE, fontweight='bold', color=DARK_BLUE)
    
    # Selitysteksti
    ct = TRANSLATIONS[lang]['combined_table']
    ax.text(0.08, 0.88, ct['description'],
            ha='left', va='top', fontsize=SUBSECTION_SIZE, style='italic', color=TEXT_GRAY)
    
    # Taulukon data kielen mukaan
    table_data = [
        [ct['field'], ct['calculation'], ct['purpose'], ct['scale'], ct['unit']],
        [ct['wdr'], ct['wdr_calc'], ct['wdr_purpose'], '0 – 25', 'WDR index' if lang == 'en' else 'WDR-indeksi'],
        [ct['cp_max'], ct['cp_max_calc'], ct['cp_max_purpose'], '0 – 1.5', 'Cp [-]'],
        [ct['cp_min'], ct['cp_min_calc'], ct['cp_min_purpose'], '-3 – 0', 'Cp [-]'],
        [ct['cp_range'], ct['cp_range_calc'], ct['cp_range_purpose'], '0 – 5', 'ΔCp [-]'],
        [ct['velocity_typical'], ct['velocity_typical_calc'], ct['velocity_typical_purpose'], '0 – 15', 'm/s'],
        [ct['convection'], ct['convection_calc'], ct['convection_purpose'], '0 – 8', '√(m²/s²)·m/s'],
        [ct['structural'], ct['structural_calc'], ct['structural_purpose'], '0 – 1000', 'Pa'],
        [ct['turbulence_intensity'], ct['turbulence_intensity_calc'], ct['turbulence_intensity_purpose'], '0 – 150', 'TI [%]'],
        [ct['u_tau'], ct['u_tau_calc'], ct['u_tau_purpose'], '0 – 0.03', 'm/s'],
    ]
    
    # Piirrä taulukko
    table_y_start = 0.82
    row_height = 0.052  # Pienempi rivikorkeus koska enemmän rivejä (11 kpl)
    col_widths = [0.18, 0.18, 0.24, 0.12, 0.13]
    col_starts = [0.08]
    for w in col_widths[:-1]:
        col_starts.append(col_starts[-1] + w)
    
    for row_idx, row in enumerate(table_data):
        y = table_y_start - row_idx * row_height
        
        # Otsikkorivi - tummansininen
        if row_idx == 0:
            ax.fill_between([0.08, 0.93], y - row_height + 0.01, y + 0.01, 
                           color=DARK_BLUE, alpha=1.0)
            text_color = 'white'
            fontweight = 'bold'
            fontsize = 9
        else:
            # Vuorotteleva tausta
            bg_color = '#f8f9fa' if row_idx % 2 == 0 else '#ffffff'
            ax.fill_between([0.08, 0.93], y - row_height + 0.01, y + 0.01, 
                           color=bg_color, alpha=1.0)
            text_color = '#2c3e50'
            fontweight = 'normal'
            fontsize = 8
        
        # Solujen reunat
        for col_idx, (col_start, col_width) in enumerate(zip(col_starts, col_widths)):
            ax.plot([col_start, col_start], [y - row_height + 0.01, y + 0.01], 
                   color='#bdc3c7', linewidth=0.5)
        ax.plot([0.93, 0.93], [y - row_height + 0.01, y + 0.01], 
               color='#bdc3c7', linewidth=0.5)
        ax.plot([0.08, 0.93], [y - row_height + 0.01, y - row_height + 0.01], 
               color='#bdc3c7', linewidth=0.5)
        
        # Teksti
        for col_idx, (text, col_start, col_width) in enumerate(zip(row, col_starts, col_widths)):
            ax.text(col_start + col_width/2, y - row_height/2 + 0.01, text,
                   ha='center', va='center', fontsize=fontsize, 
                   fontweight=fontweight, color=text_color,
                   linespacing=1.1)
    
    # Taulukon ylä- ja alareunat
    ax.plot([0.08, 0.93], [table_y_start + 0.01, table_y_start + 0.01], 
           color='#2874a6', linewidth=1.5)
    final_y = table_y_start - len(table_data) * row_height + 0.01
    ax.plot([0.08, 0.93], [final_y, final_y], 
           color='#2874a6', linewidth=1.5)
    
    # Selitteet alla
    notes_y = final_y - 0.04
    if lang == 'en':
        ax.text(0.08, notes_y, 
                'Notes:', 
                ha='left', va='top', fontsize=9, fontweight='bold', color='#2c3e50')
        
        notes = [
            '• Cp = pressure coefficient, dimensionless ratio of local pressure to dynamic wind pressure',
            '• WDR = Wind-Driven Rain, index combining wind speed and direction',
            '• Positive Cp (overpressure) occurs on windward facades',
            '• Negative Cp (suction) occurs on leeward side and roofs',
            '• Weighted sum accounts for annual probability of each wind direction',
        ]
    else:
        ax.text(0.08, notes_y, 
                'Selitteet:', 
                ha='left', va='top', fontsize=9, fontweight='bold', color='#2c3e50')
        
        notes = [
            '• Cp = painekerroin, dimensioton suure joka kuvaa paikallisen paineen suhdetta tuulen dynaamiseen paineeseen',
            '• WDR = Wind-Driven Rain, viistosateen indeksi joka yhdistää tuulen nopeuden ja suunnan',
            '• Positiivinen Cp (ylipaine) esiintyy tuulen puoleisilla julkisivuilla',
            '• Negatiivinen Cp (alipaine) esiintyy suojan puolella ja katoilla',
            '• Painotettu summa huomioi kunkin tuulensuunnan esiintymistodennäköisyyden vuodessa',
        ]
    
    for i, note in enumerate(notes):
        ax.text(0.08, notes_y - 0.03 - i * 0.025, note,
               ha='left', va='top', fontsize=8, color='#555555')
    
    pdf.savefig(fig)
    plt.close(fig)


def add_energy_index_page(pdf: PdfPages, energy_stats: List[Dict], section_num: int = None, lang: str = 'fi'):
    """
    Lisää energiaindeksisivu raporttiin.
    
    Args:
        pdf: PdfPages-objekti
        energy_stats: Lista rakennusten energiatilastoista
        section_num: Osion numero (valinnainen)
        lang: Kieli 'fi' tai 'en'
    """
    if not energy_stats:
        return
    
    fig, ax = plt.subplots(figsize=(8.27, 11.69))  # A4
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis('off')
    
    ei = TRANSLATIONS[lang]['energy_index']
    
    # Osion otsikko vaaleansinisellä taustalla (lisää numero jos annettu)
    header_y = 0.94
    ax.fill_between([0.05, 0.95], header_y - 0.025, header_y + 0.015, 
                    color=LIGHT_BLUE, alpha=1.0)
    title_text = f"{section_num}. {ei['table_title']}" if section_num else ei['table_title']
    ax.text(0.5, header_y - 0.005, title_text, 
            ha='center', va='center', fontsize=TITLE_SIZE, fontweight='bold', color=DARK_BLUE)
    
    # Selitysteksti
    ax.text(0.08, 0.88, ei['description'],
            ha='left', va='top', fontsize=SUBSECTION_SIZE, style='italic', color=TEXT_GRAY)
    
    # Taulukon data - näytä KAIKKI rakennukset järjestettynä label_id:n mukaan
    # (jos yli 15, jaetaan useammalle sivulle myöhemmin)
    display_stats = sorted(energy_stats, key=lambda x: x.get('label_id', x.get('id', 0)))
    
    # Rajoita 15 rakennukseen per sivu
    max_rows = 15
    if len(display_stats) > max_rows:
        display_stats = display_stats[:max_rows]
    
    # Taulukon otsikkorivi
    table_data = [[
        ei['building'],
        ei['energy_idx'],
        ei['heat_loss'],
        ei['wind_class'],
        ei['recommendation']
    ]]
    
    # Dataa rivit
    for b in display_stats:
        # Laske wind_class dynaamisesti energy_index perusteella
        # Tämä varmistaa että luokitus on synkassa värikoodauksen kanssa
        energy_idx = b.get('energy_index', 100)
        if energy_idx > 150:
            wind_class = 'very_exposed'
        elif energy_idx > 125:
            wind_class = 'exposed'
        elif energy_idx > 108:
            wind_class = 'slightly_exposed'
        elif energy_idx < 80:
            wind_class = 'sheltered'
        elif energy_idx < 95:
            wind_class = 'moderate_shelter'
        else:
            wind_class = 'average'
        
        class_name = ei['classes'].get(wind_class, wind_class)
        recommendation = ei['recommendations'].get(wind_class, '')
        
        # Käytä label_id:tä jos saatavilla, muuten id
        display_id = b.get('label_id', b.get('id', '?'))
        
        table_data.append([
            f"#{display_id}",
            f"{b.get('energy_index', 100):.0f}",
            f"{b.get('relative_heat_loss', 100):.0f}%",
            class_name,
            recommendation
        ])
    
    # Piirrä taulukko - levennetty suositussarake
    table_y_start = 0.82
    row_height = 0.038  # Pienempi rivikorkeus
    col_widths = [0.08, 0.10, 0.10, 0.16, 0.41]  # Levennetty suositus
    col_starts = [0.08]
    for w in col_widths[:-1]:
        col_starts.append(col_starts[-1] + w)
    
    for row_idx, row in enumerate(table_data):
        y = table_y_start - row_idx * row_height
        
        # Otsikkorivi
        if row_idx == 0:
            ax.fill_between([0.08, 0.93], y - row_height + 0.005, y + 0.005, 
                           color=DARK_BLUE, alpha=1.0)
            text_color = 'white'
            fontweight = 'bold'
            fontsize = 8
            is_target = False
        else:
            # Värikoodaus energiaindeksin mukaan
            # Lievennetyt rajat: 108/125/150 (realistisempi fysiikan näkökulmasta)
            energy_idx = display_stats[row_idx - 1].get('energy_index', 100)
            is_target = display_stats[row_idx - 1].get('is_target', False)
            
            if energy_idx > 150:
                bg_color = '#ffcccc'  # punainen - erittäin tuulinen (>50% yli keskiarvon)
            elif energy_idx > 125:
                bg_color = '#ffe6cc'  # oranssi - tuulinen (25-50% yli)
            elif energy_idx > 108:
                bg_color = '#fff5cc'  # keltainen - hieman tuulinen (8-25% yli)
            elif energy_idx < 80:
                bg_color = '#ccffcc'  # vihreä - suojaisa (>20% alle)
            elif energy_idx < 95:
                bg_color = '#e6ffcc'  # vaaleanvihreä - koht. suojaisa (5-20% alle)
            else:
                bg_color = '#f8f9fa'  # harmaa - keskimääräinen (±8%)
            
            # Kohderakennus korostetaan reunaviivalla
            if is_target:
                ax.fill_between([0.08, 0.93], y - row_height + 0.005, y + 0.005, 
                               color=bg_color, alpha=0.9)
                # Korostusreuna
                ax.plot([0.08, 0.93], [y + 0.005, y + 0.005], color=DARK_BLUE, linewidth=2)
                ax.plot([0.08, 0.93], [y - row_height + 0.005, y - row_height + 0.005], color=DARK_BLUE, linewidth=2)
            else:
                ax.fill_between([0.08, 0.93], y - row_height + 0.005, y + 0.005, 
                               color=bg_color, alpha=0.7)
            
            text_color = '#2c3e50'
            fontweight = 'bold' if is_target else 'normal'
            fontsize = 8
        
        # Solujen reunat
        for col_start in col_starts:
            ax.plot([col_start, col_start], [y - row_height + 0.005, y + 0.005], 
                   color='#bdc3c7', linewidth=0.5)
        ax.plot([0.93, 0.93], [y - row_height + 0.005, y + 0.005], 
               color='#bdc3c7', linewidth=0.5)
        ax.plot([0.08, 0.93], [y - row_height + 0.005, y - row_height + 0.005], 
               color='#bdc3c7', linewidth=0.5)
        
        # Teksti
        for col_idx, (text, col_start, col_width) in enumerate(zip(row, col_starts, col_widths)):
            ha = 'left' if col_idx == 4 else 'center'  # Suositus vasemmalle
            x_offset = 0.01 if col_idx == 4 else col_width/2
            # Kohderakennuksen ID:n perään tähti
            if row_idx > 0 and col_idx == 0 and is_target:
                text = text + " ★"
            ax.text(col_start + x_offset, y - row_height/2 + 0.005, text,
                   ha=ha, va='center', fontsize=fontsize, 
                   fontweight=fontweight, color=text_color)
    
    # Taulukon reunat
    ax.plot([0.08, 0.93], [table_y_start + 0.005, table_y_start + 0.005], 
           color='#2874a6', linewidth=1.5)
    final_y = table_y_start - len(table_data) * row_height + 0.005
    ax.plot([0.08, 0.93], [final_y, final_y], 
           color='#2874a6', linewidth=1.5)
    
    # Väriselite heti taulukon alla (ilman "Värikoodit:" otsikkoa)
    legend_y = final_y - 0.018
    
    # Päivitetyt raja-arvot: 80/95/108/125/150
    colors = [
        ('#ccffcc', '< 80', 'Suojaisa' if lang == 'fi' else 'Sheltered'),
        ('#e6ffcc', '80-95', 'Koht. suoj.' if lang == 'fi' else 'Mod. shelt.'),
        ('#f8f9fa', '95-108', 'Keskim.' if lang == 'fi' else 'Average'),
        ('#fff5cc', '108-125', 'Hiem. tuul.' if lang == 'fi' else 'Sl. exp.'),
        ('#ffe6cc', '125-150', 'Tuulinen' if lang == 'fi' else 'Exposed'),
        ('#ffcccc', '> 150', 'Erit. tuul.' if lang == 'fi' else 'Very exp.'),
    ]
    
    # Kaikki värit ja kohderakennus yhdelle riville
    start_x = 0.08
    spacing = 0.115  # Hieman tiukempi väli koska 6 väriä
    for i, (color, range_txt, label) in enumerate(colors):
        x = start_x + i * spacing
        ax.fill_between([x, x + 0.012], legend_y - 0.012, legend_y - 0.022,
                       color=color, alpha=0.8)
        ax.text(x + 0.015, legend_y - 0.017, f"{label} ({range_txt})",
               ha='left', va='center', fontsize=5.5, color='#555555')
    
    # Kohderakennuksen selite samalle riville, lopussa
    target_buildings = [b for b in energy_stats if b.get('is_target', False)]
    if target_buildings:
        target_x = start_x + 6 * spacing  # 7. elementti rivillä
        ax.text(target_x, legend_y - 0.017, "★ = Kohderakennus" if lang == 'fi' else "★ = Target building",
               ha='left', va='center', fontsize=5.5, fontweight='bold', color=DARK_BLUE)
    
    # Yhteenveto (lähempänä)
    summary_y = legend_y - 0.040
    
    # Laske tilastot (lievennetyt rajat: 108/125/150)
    very_exposed = [b for b in energy_stats if b.get('energy_index', 100) > 150]
    exposed = [b for b in energy_stats if 125 < b.get('energy_index', 100) <= 150]
    slightly_exposed = [b for b in energy_stats if 108 < b.get('energy_index', 100) <= 125]
    sheltered = [b for b in energy_stats if b.get('energy_index', 100) < 80]
    
    if lang == 'en':
        summary_title = "Summary:"
        summary_text = f"• {len(energy_stats)} buildings analyzed\n"
        if very_exposed:
            ids = ', '.join(f"#{b.get('label_id', b.get('id', '?'))}" for b in very_exposed[:5])
            summary_text += f"• Very exposed ({len(very_exposed)}): {ids}\n"
        if exposed:
            ids = ', '.join(f"#{b.get('label_id', b.get('id', '?'))}" for b in exposed[:5])
            summary_text += f"• Exposed ({len(exposed)}): {ids}\n"
        if slightly_exposed:
            ids = ', '.join(f"#{b.get('label_id', b.get('id', '?'))}" for b in slightly_exposed[:5])
            summary_text += f"• Slightly exposed ({len(slightly_exposed)}): {ids}\n"
        if sheltered:
            ids = ', '.join(f"#{b.get('label_id', b.get('id', '?'))}" for b in sheltered[:5])
            summary_text += f"• Well sheltered ({len(sheltered)}): {ids}"
    else:
        summary_title = "Yhteenveto:"
        summary_text = f"• {len(energy_stats)} rakennusta analysoitu\n"
        if very_exposed:
            ids = ', '.join(f"#{b.get('label_id', b.get('id', '?'))}" for b in very_exposed[:5])
            summary_text += f"• Erittäin tuulisia ({len(very_exposed)}): {ids}\n"
        if exposed:
            ids = ', '.join(f"#{b.get('label_id', b.get('id', '?'))}" for b in exposed[:5])
            summary_text += f"• Tuulisia ({len(exposed)}): {ids}\n"
        if slightly_exposed:
            ids = ', '.join(f"#{b.get('label_id', b.get('id', '?'))}" for b in slightly_exposed[:5])
            summary_text += f"• Hieman tuulisia ({len(slightly_exposed)}): {ids}\n"
        if sheltered:
            ids = ', '.join(f"#{b.get('label_id', b.get('id', '?'))}" for b in sheltered[:5])
            summary_text += f"• Suojaisia ({len(sheltered)}): {ids}"
    
    ax.text(0.08, summary_y, summary_title, 
            ha='left', va='top', fontsize=10, fontweight='bold', color='#2c3e50')
    ax.text(0.08, summary_y - 0.025, summary_text.strip(),
            ha='left', va='top', fontsize=9, color='#555555', linespacing=1.3)
    
    # Selitteet
    notes_y = summary_y - 0.12
    ax.text(0.08, notes_y, 
            'Selitteet:' if lang == 'fi' else 'Notes:', 
            ha='left', va='top', fontsize=9, fontweight='bold', color='#2c3e50')
    
    for i, note in enumerate(ei['notes']):
        ax.text(0.08, notes_y - 0.025 - i * 0.022, note,
               ha='left', va='top', fontsize=8, color='#555555')
    
    pdf.savefig(fig)
    plt.close(fig)


def _generate_report_filename(title: str, results_path: Path, is_multi_wind: bool, 
                               multi_wind_metadata_path: Path = None,
                               geometry_path: str = None) -> str:
    """
    Generoi kuvaava tiedostonimi raportille.
    
    Muoto: MikroilmastoCFD_[tyyppi]_[osoite]_[kaupunki].pdf
    
    Esimerkkejä:
        MikroilmastoCFD_multiwind_prikaatinkatu_3_mikkeli.pdf
        MikroilmastoCFD_lansi_prikaatinkatu_3_mikkeli.pdf
    
    Args:
        title: Raportin otsikko (yleensä osoite)
        results_path: Tuloskansion polku
        is_multi_wind: Onko multi-wind simulointi
        multi_wind_metadata_path: Multi-wind metadatan polku
        geometry_path: Geometriatiedoston polku
        
    Returns:
        Tiedostonimi (str)
    """
    import re
    import json
    
    # Ilmansuuntien käännökset (CFD-asteet -> suomenkielinen nimi + englanninkielinen lyhenne)
    DIRECTION_NAMES = {
        0: 'lansiW', 45: 'lounasSW', 90: 'etelaS', 135: 'kaakkoSE',
        180: 'itaE', 225: 'koillinenNE', 270: 'pohjoinenN', 315: 'luodeNW',
        # Välisuunnat
        22: 'lansilounasWSW', 67: 'etelalounasSSW', 112: 'etelakaakkoSSE', 157: 'itakaakkoESE',
        202: 'itakoillinenENE', 247: 'pohjoiskoillinenNNE', 292: 'pohjoisluodeNNW', 337: 'lansiluodeWNW',
    }
    
    def normalize_name(text: str) -> str:
        """Normalisoi teksti tiedostonimeen sopivaksi."""
        if not text:
            return ""
        # Pienet kirjaimet
        text = text.lower()
        # Korvaa skandit
        text = text.replace('ä', 'a').replace('ö', 'o').replace('å', 'a')
        # Korvaa välilyönnit ja erikoismerkit alaviivalla
        text = re.sub(r'[^\w]+', '_', text)
        # Poista peräkkäiset alaviivat
        text = re.sub(r'_+', '_', text)
        # Poista alku- ja loppuviivat
        text = text.strip('_')
        return text
    
    def get_direction_name(angle: float) -> str:
        """Muunna CFD-kulma suomenkieliseksi ilmansuunnaksi."""
        # Pyöristä lähimpään 22.5 asteen kerrannaiseen
        normalized = round(angle / 22.5) * 22.5 % 360
        # Etsi lähin tunnettu suunta
        closest = min(DIRECTION_NAMES.keys(), key=lambda x: abs(x - normalized))
        return DIRECTION_NAMES.get(closest, f"{int(angle)}")
    
    # Perusosa
    prefix = "MikroilmastoCFD"
    
    # Määritä tyyppi
    if is_multi_wind:
        sim_type = "multiwind"
    else:
        # Yksittäinen suunta - etsi kulma domain.json:sta
        sim_type = "tuulianalyysi"  # Oletus
        domain_path = results_path / "domain.json"
        if not domain_path.exists():
            # Kokeile data/ -kansiosta
            domain_path = results_path / "data" / "domain.json"
        if not domain_path.exists():
            # Kokeile fine/ -kansiosta (nested)
            domain_path = results_path / "fine" / "domain.json"
        
        if domain_path.exists():
            try:
                with open(domain_path, 'r') as f:
                    domain_data = json.load(f)
                inlet_dir = domain_data.get('inlet_direction', None)
                if inlet_dir is not None:
                    sim_type = get_direction_name(float(inlet_dir))
            except:
                pass
    
    # Osoite ja kaupunki - yritä ensin geometriatiedostosta
    address = ""
    city = ""
    
    if geometry_path:
        geom_path = Path(geometry_path)
        if geom_path.exists():
            try:
                with open(geom_path, 'r', encoding='utf-8') as f:
                    geom_data = json.load(f)
                
                # Osoite/nimi
                if 'name' in geom_data and geom_data['name']:
                    address = normalize_name(geom_data['name'])
                
                # Kaupunki metadatasta
                if 'metadata' in geom_data:
                    meta = geom_data['metadata']
                    if 'city' in meta and meta['city']:
                        city = normalize_name(meta['city'])
                    # Vaihtoehtoinen: address-kenttä
                    if not address and 'address' in meta and meta['address']:
                        address = normalize_name(meta['address'])
            except:
                pass
    
    # Fallback: yritä titlesta
    if not address and title:
        # Yritä erottaa osoite ja kaupunki
        # Ohita tunnetut suffiksit kuten "Multi-wind"
        ignored_suffixes = ['multi-wind', 'multi_wind', 'multiwind', 'cfd', 'analyysi', 'analysis']
        
        if ',' in title:
            parts = title.split(',', 1)
            address = normalize_name(parts[0])
            if not city and len(parts) > 1:
                potential_city = normalize_name(parts[1])
                if potential_city not in ignored_suffixes:
                    city = potential_city
        elif ' - ' in title:
            parts = title.split(' - ', 1)
            address = normalize_name(parts[0])
            if not city and len(parts) > 1:
                potential_city = normalize_name(parts[1])
                if potential_city not in ignored_suffixes:
                    city = potential_city
        else:
            address = normalize_name(title)
    
    # HUOM: Ei haeta kaupunkia multi_wind_metadata:sta tiedostonimeen,
    # koska se on FMI-säädatan lähde (esim. "Pori") eikä kohteen sijainti.
    # Kaupunki tulee vain geometriasta tai titlesä.
    
    # Rakenna tiedostonimi
    # Lisää kaupunki vain jos se tulee geometriasta/titlesta JA ei ole jo osoitteessa
    parts = [prefix, sim_type]
    if address:
        parts.append(address)
        # Lisää kaupunki vain jos se ei ole jo osoitteessa
        if city and city not in address:
            parts.append(city)
    elif city:
        # Jos osoitetta ei ole, lisää kaupunki
        parts.append(city)
    
    filename = '_'.join(parts) + '.pdf'
    
    return filename


def _find_or_generate_grid_visualization(results_path: Path, lang: str = 'fi', dpi: int = 150) -> Path:
    """
    Etsi olemassa oleva grid_visualization.png tai generoi se.
    
    Etsii ensin tuloshakemistosta ja sen ylähakemistoista.
    Jos ei löydy, yrittää generoida metadatasta ja buildings.json:sta.
    
    Returns:
        Path-olio jos löytyi/generoitiin, None muuten
    """
    results_path = Path(results_path)
    
    # Etsi olemassa oleva kuva
    search_paths = [
        results_path / 'grid_visualization.png',
    ]
    # Combined-kansiossa etsi myös wind-kansioista
    if 'combined' in str(results_path):
        parent_dir = results_path.parent
        for wind_dir in sorted(parent_dir.glob("wind_*")):
            search_paths.append(wind_dir / 'grid_visualization.png')
    
    for sp in search_paths:
        if sp.exists():
            return sp
    
    # Ei löytynyt - yritä generoida
    try:
        from grid_visualization import generate_grid_from_simulation
        output = results_path / 'grid_visualization.png'
        result = generate_grid_from_simulation(
            results_dir=str(results_path),
            output_path=str(output),
            lang=lang,
            dpi=dpi
        )
        if result and Path(result).exists():
            return Path(result)
    except ImportError:
        print(f"  ⚠ grid_visualization.py ei löydy, hilavisualisointia ei generoida")
    except Exception as e:
        print(f"  ⚠ Hilavisualisoinnin generointi epäonnistui: {e}")
    
    return None


def generate_report(results_dir: str, 
                    output_path: str = None,
                    title: str = None,
                    geometry_path: str = None,
                    lang: str = 'fi'):
    """
    Generoi PDF-raportin simuloinnin tuloksista.
    
    Args:
        results_dir: Tuloskansio
        output_path: PDF-tiedoston polku (oletus: results_dir/report.pdf)
        title: Raportin otsikko (oletus: kohteen nimi)
        geometry_path: Geometriatiedosto (oletus: etsitään automaattisesti)
        lang: Kieli 'fi' tai 'en' (oletus: 'fi')
    """
    global REPORT_DPI
    
    results_path = Path(results_dir)
    
    if not results_path.exists():
        raise FileNotFoundError(f"Tuloskansiota ei löydy: {results_path}")
    
    # Aseta älykäs DPI hilakokon perusteella
    REPORT_DPI = get_smart_dpi_from_metadata(results_path)
    print(f"  Kuva-DPI: {REPORT_DPI} (automaattinen)")
    
    # Aseta raportin tyyli
    set_report_style()
    
    # Lataa raporttitiedot
    report_data = load_comfort_report(results_path)
    
    # Määritä otsikko
    if title is None:
        title = report_data.get('name', results_path.name)
    
    # Tarkista onko multi-wind simulointi
    multi_wind_metadata_path = results_path.parent / "multi_wind_metadata.json"
    is_multi_wind_sim = "combined" in str(results_path) and multi_wind_metadata_path.exists()
    
    # Määritä output - luo kuvaava tiedostonimi
    if output_path is None:
        # Muodosta tiedostonimi: MikroilmastoCFD_[tyyppi]_[osoite]_[kaupunki].pdf
        report_filename = _generate_report_filename(
            title=title,
            results_path=results_path,
            is_multi_wind=is_multi_wind_sim,
            multi_wind_metadata_path=multi_wind_metadata_path,
            geometry_path=geometry_path
        )
        # Raportti tallentuu tuloskansion sisään (combined/ tai suuntakansio)
        # create_delivery_folder kopioi sen asiakaskansioon
        output_path = results_path / report_filename
    else:
        output_path = Path(output_path)
    
    lang_name = 'English' if lang == 'en' else 'Suomi'
    print(f"Generoidaan raportti: {output_path} ({lang_name})")
    print(f"  Otsikko: {title}")
    
    # Kuvatekstit kielen mukaan
    if lang == 'en':
        captions = {
            'velocity': 'Velocity field',
            'velocity_streamlines': 'Velocity field with streamlines',
            'pressure': 'Pressure field (Cp)',
            'pressure_streamlines': 'Pressure field with streamlines',
            'comfort': 'Wind comfort zones (Lawson criteria)',
            'turbulence_k': 'Turbulent kinetic energy (k)',
            'turbulence_TI': 'Turbulence intensity (TI)',
            'convection': 'Convective cooling (√k × v)',
            'turbulence_nu': 'Turbulent viscosity (ν_t)',
            'turbulence_omega': 'Specific dissipation (ω)',
            'u_tau': 'Friction velocity (u_τ)',
            'nested_comparison': 'Coarse and fine grid comparison',
            'adaptive_grid': 'Adaptive computational grid',
            'geometry': 'Calculation domain and buildings'
        }
    else:
        captions = {
            'velocity': 'Nopeuskenttä',
            'velocity_streamlines': 'Nopeuskenttä ja virtaviivat',
            'pressure': 'Painekenttä (Cp)',
            'pressure_streamlines': 'Painekenttä ja virtaviivat',
            'comfort': 'Tuulisuusvyöhykkeet (Lawsonin kriteerit)',
            'turbulence_k': 'Turbulenssin kineettinen energia (k)',
            'turbulence_TI': 'Turbulenssi-intensiteetti (TI)',
            'convection': 'Konvektiivinen jäähtyminen (√k × v)',
            'turbulence_nu': 'Turbulentti viskositeetti (ν_t)',
            'turbulence_omega': 'Spesifinen dissipaatio (ω)',
            'u_tau': 'Kitkanopeus (u_τ)',
            'nested_comparison': 'Karkean ja tiheän hilan vertailu',
            'adaptive_grid': 'Adaptiivinen laskentahila',
            'geometry': 'Laskenta-alue ja rakennukset'
        }
    
    # Selitystekstit (dokumentaation kappaleesta 7)
    if lang == 'en':
        descriptions = {
            'turbulence_k': (
                'Practical interpretation in building physics:\n'
                '• Heat and moisture transfer: High k → turbulence enhances convection,\n'
                '  convective flows can cool surfaces and moisture can enter through joints\n'
                '• Comfort: High k → gustiness, uncomfortable wind conditions\n'
                '• Mixing: High k → efficient ventilation and dispersion'
            ),
            'turbulence_TI': (
                'Turbulence intensity (TI) describes wind gustiness relative to mean wind speed.\n'
                'High values (>30%) at building corners and wakes cause dynamic loads on structures\n'
                'and discomfort for pedestrians. Does not directly correlate with cooling - see convection index.\n\n'
                'Note: Vegetation areas (green) show high turbulence due to air mixing within the canopy.'
            ),
            'convection': (
                'Convection index (√k × v) describes facade cooling intensity by combining turbulence\n'
                'and wind speed effects. Critical for energy efficiency and thermal bridges -\n'
                'high values enhance heat loss and frost damage risk on windward facades.\n\n'
                'Note: Vegetation areas (green) show air mixing within the canopy.\n'
                'Edge turbulence can enhance cooling of nearby buildings.'
            ),
            'turbulence_omega': (
                'Practical interpretation in building physics:\n'
                '• Eddy size: Low ω → large eddies transport heat and moisture,\n'
                '  high ω → small eddies enhance local heat transfer\n'
                '• Wall proximity: ω increases near surfaces → intensive convection\n'
                '• Time scale: τ = 1/ω is the characteristic turbulence time scale'
            ),
            'turbulence_nu': (
                'Practical interpretation in building physics:\n'
                '• Mixing: High ν_t → effective turbulent mixing\n'
                '• Heat and moisture transfer: High ν_t → enhanced convective transfer,\n'
                '  convective flows can cool surfaces and moisture can enter through joints\n'
                '• Wakes: Highest values in wake regions behind buildings'
            ),
            'u_tau': (
                'Practical interpretation in building physics:\n'
                '• Convective heat transfer: High u_τ → more efficient heat transfer between surface and air\n'
                '• Moisture drying: High u_τ → faster evaporation from facade\n'
                '• Pressure distribution: High u_τ → accelerated flow, low pressure\n'
                '• Wall force: Doubling u_τ → force quadruples'
            ),
            'y_plus': (
                'Practical interpretation in building physics:\n'
                '• y+ < 5 → within viscous sublayer (accurate resolution)\n'
                '• y+ = 30-300 → wall functions region (recommended)\n'
                '• y+ > 300 → too far from wall, inaccurate'
            ),
            'comfort': (
                'Lawson wind comfort criteria:\n'
                '• Sitting: Below 4 m/s → suitable for long-term sitting\n'
                '• Standing: 4-6 m/s → suitable for short stops\n'
                '• Walking: 6-8 m/s → suitable for walking\n'
                '• Uncomfortable: Above 8 m/s → windy environment\n\n'
                'Note: Thresholds are scaled from 10m reference height to pedestrian level (2m)\n'
                'using atmospheric boundary layer profile (power law, α=0.25 for urban terrain).'
            ),
            'pressure': (
                'Practical interpretation in building physics:\n'
                '• Cp > 0: Overpressure (windward) → overpressure carries moisture,\n'
                '  moisture can enter structures e.g. under cladding\n'
                '• Cp < 0: Suction (leeward, roof)\n'
                '• Cp ≈ -0.5...-1.5: Typical suction behind building'
            ),
            'velocity': (
                'Practical interpretation in building physics:\n'
                '• Acceleration: High velocities between buildings and at corners can cool surfaces\n'
                '• Sheltered areas: Low velocities behind buildings, less convective cooling\n'
                '• Facade stress: High velocity enhances driving rain penetration\n'
                '• Ventilation: Velocity differences create pressure differences affecting building pressure distribution'
            )
        }
    else:
        descriptions = {
            'turbulence_k': (
                'Käytännön tulkinta rakennusfysiikassa:\n'
                '• Lämmön- ja kosteuden siirto: Korkea k → turbulenssi tehostaa konvektiota,\n'
                '  konvektiovirtaukset voivat viilentää pintoja ja kosteus pääsee liitoksista sisään\n'
                '• Viihtyvyys: Korkea k → puuskaisuus, epämiellyttävä tuulisuus\n'
                '• Sekoittuminen: Korkea k → tehokas ilmanvaihto ja hajonta'
            ),
            'turbulence_TI': (
                'Turbulenssi-intensiteetti (TI) kuvaa tuulen puuskaisuutta suhteessa keskituuleen.\n'
                'Korkeat arvot (>30%) rakennusten nurkilla ja vanoissa aiheuttavat dynaamisia\n'
                'kuormituksia rakenteille ja epämukavuutta jalankulkijoille.\n'
                'Ei suoraan korreloi jäähtymisen kanssa - katso konvektioindeksi.\n\n'
                'Huom: Kasvillisuusalueilla (vihreä) korkea turbulenssi kuvaa ilman sekoittumista puustossa.'
            ),
            'convection': (
                'Konvektioindeksi (√k × v) kuvaa julkisivun jäähtymisintensiteettiä yhdistäen\n'
                'turbulenssin ja tuulennopeuden vaikutukset. Kriittinen energiatehokkuudelle\n'
                'ja kylmäsilloille - korkeat arvot tehostavat lämpöhäviötä ja pakkasrapautumisriskiä\n'
                'tuulen puoleisilla julkisivuilla.\n\n'
                'Huom: Kasvillisuusalueilla (vihreä) ilma sekoittuu puustossa.\n'
                'Reunapyörteet voivat tehostaa lähirakennusten jäähtymistä.'
            ),
            'turbulence_omega': (
                'Käytännön tulkinta rakennusfysiikassa:\n'
                '• Pyörteiden koko: Matala ω → suuret pyörteet kuljettavat lämpöä ja kosteutta,\n'
                '  korkea ω → pienet pyörteet tehostavat paikallista lämmönsiirtoa\n'
                '• Seinän läheisyys: ω kasvaa pintojen lähellä → intensiivinen konvektio\n'
                '• Aikaskaala: τ = 1/ω on turbulenssin karakteristinen aikaskaala'
            ),
            'turbulence_nu': (
                'Käytännön tulkinta rakennusfysiikassa:\n'
                '• Sekoittuminen: Korkea ν_t → tehokas turbulentti sekoittuminen\n'
                '• Lämmön- ja kosteuden siirto: Korkea ν_t → tehostunut konvektiivinen siirto,\n'
                '  konvektiovirtaukset voivat viilentää pintoja ja kosteus pääsee liitoksista sisään\n'
                '• Vanat: Korkeimmat arvot rakennusten takana vana-alueilla'
            ),
            'u_tau': (
                'Käytännön tulkinta rakennusfysiikassa:\n'
                '• Konvektiivinen lämmönsiirto: Korkea u_τ → tehokkaampi lämmönsiirto pinnan ja ilman välillä\n'
                '• Kosteuden kuivuminen: Korkea u_τ → nopeampi haihtuminen julkisivulta\n'
                '• Painejakauma: Korkea u_τ → kiihtynyt virtaus, alipaine\n'
                '• Seinävoima: u_τ:n kaksinkertaistuessa → voima nelinkertaistuu'
            ),
            'y_plus': (
                'Käytännön tulkinta rakennusfysiikassa:\n'
                '• y+ < 5 → viskoosin alikerroksen sisällä (tarkka resoluutio)\n'
                '• y+ = 30-300 → wall functions -alue (suositeltu)\n'
                '• y+ > 300 → liian kaukana seinästä, epätarkka'
            ),
            'comfort': (
                'Lawsonin tuulisuuskriteerit:\n'
                '• Istuskelu: Alle 4 m/s → sopii pitkään oleskeluun\n'
                '• Seisoskelu: 4-6 m/s → sopii lyhyeen pysähtymiseen\n'
                '• Kävely: 6-8 m/s → sopii ohikulkuun\n'
                '• Epämukava: Yli 8 m/s → tuulinen ympäristö\n\n'
                'Huom: Raja-arvot on skaalattu 10m referenssikorkeudelta jalankulkijatasolle (2m)\n'
                'käyttäen ilmakehän rajakerrosprofiilia (potenssilaki, α=0.25 urbaanille maastolle).'
            ),
            'pressure': (
                'Käytännön tulkinta rakennusfysiikassa:\n'
                '• Cp > 0: Ylipaine (tuulen puoli) → ylipaine kuljettaa mukanaan kosteutta,\n'
                '  kosteus pääsee esim. pellityksen alta rakenteisiin\n'
                '• Cp < 0: Alipaine (suojan puoli, katto)\n'
                '• Cp ≈ -0.5...-1.5: Tyypillinen alipaine rakennuksen takana'
            ),
            'velocity': (
                'Käytännön tulkinta rakennusfysiikassa:\n'
                '• Kiihtyminen: Rakennusten välissä ja kulmissa nopeat ilmavirtaukset voivat jäähdyttää pintoja\n'
                '• Suojaisat alueet: Rakennusten takana matalat nopeudet, vähemmän konvektiivista jäähtymistä\n'
                '• Julkisivurasitus: Korkea nopeus tehostaa viistosateen tunkeutumista rakenteisiin\n'
                '• Ilmanvaihto: Nopeuserot luovat paine-eroja jotka vaikuttavat rakennuksen painejakaumaan'
            )
        }
    
    def get_caption(img_path):
        name_lower = img_path.stem.lower()
        for key, text in captions.items():
            if key.lower() in name_lower:
                return text
        return img_path.stem.replace('_', ' ').title()
    
    def get_description(img_path):
        """Palauttaa selitystekstin kuvalle jos saatavilla."""
        name_lower = img_path.stem.lower()
        for key, text in descriptions.items():
            if key.lower() in name_lower:
                return text
        return None
    
    # Luo PDF
    with PdfPages(str(output_path)) as pdf:
        
        # Analysoi rakennuskohtaiset rasitukset ensin (tarvitaan kansilehteen)
        building_analysis = analyze_building_loads(results_path)
        if building_analysis:
            print(f"  ✓ Rakennusanalyysi: {building_analysis['num_buildings']} rakennusta")
        
        # Yritä hakea rakennusten korkeustiedot
        # 1. Ensin tarkistetaan onko geometriatiedostossa jo height_mml kentät
        # 2. Jos ei, haetaan MML:stä
        
        # Etsi geometriatiedosto (tarvitaan myös simuloinnin tiedot -sivulle)
        geom_file_for_mml = geometry_path
        if not geom_file_for_mml:
            # Etsi automaattisesti - suosi tiedostoja joissa on 'obstacles' kenttä
            search_dirs = [results_path, results_path.parent, results_path.parent.parent,
                          Path('examples/OSMgeometry'),
                          Path(__file__).parent / 'examples' / 'OSMgeometry']
            excluded_names = ['config', 'metadata', 'domain', 'multi_wind', 'direction_dominance',
                            'building_heights', 'building_energy', 'wind_stats']
            
            candidates = []
            for sd in search_dirs:
                if sd.exists():
                    for jf in sd.glob('*.json'):
                        name_lower = jf.name.lower()
                        if any(ex in name_lower for ex in excluded_names):
                            continue
                        candidates.append(jf)
            
            # Valitse ensimmäinen jolla on obstacles-kenttä
            for candidate in candidates:
                try:
                    with open(candidate, 'r', encoding='utf-8') as f:
                        test_data = json.load(f)
                    if 'obstacles' in test_data and len(test_data.get('obstacles', [])) > 0:
                        geom_file_for_mml = str(candidate)
                        break
                except Exception:
                    continue
            
            # Fallback: ensimmäinen JSON-kandidaatti (vanha toiminta)
            if not geom_file_for_mml and candidates:
                geom_file_for_mml = str(candidates[0])
        
        if building_analysis:
            geom_meta = None
            geom_data = None
            geom_obstacles = None
            
            # Lataa geometria
            if geom_file_for_mml:
                try:
                    with open(geom_file_for_mml, 'r', encoding='utf-8') as f:
                        geom_data = json.load(f)
                    geom_meta = geom_data.get('metadata', {})
                    geom_obstacles = geom_data.get('obstacles', [])
                    domain = geom_data.get('domain', {})
                except Exception as e:
                    print(f"  Varoitus: Geometrian lataus epäonnistui: {e}")
                    geom_meta = None
            
            # Siirrä is_target geometriasta building_analysis:iin (spatiaalinen matching)
            if geom_obstacles and building_analysis:
                target_obs = None
                for obs in geom_obstacles:
                    if obs.get('is_target', False):
                        target_obs = obs
                        break
                
                if target_obs is not None:
                    matched = False
                    
                    # Laske kohderakennuksen keskipiste geometriasta
                    target_points = (target_obs.get('vertices') or 
                                    target_obs.get('points') or 
                                    target_obs.get('polygon') or [])
                    tx = np.mean([pt[0] for pt in target_points]) if target_points else None
                    ty = np.mean([pt[1] for pt in target_points]) if target_points else None
                    
                    # 1. Yritä suoraa spatiaalista matchausta (sama koordinaatisto)
                    if tx is not None:
                        best_bldg = None
                        best_dist = float('inf')
                        for bldg in building_analysis['buildings']:
                            d = np.sqrt((bldg['center_x'] - tx)**2 + (bldg['center_y'] - ty)**2)
                            if d < best_dist:
                                best_dist = d
                                best_bldg = bldg
                        
                        if best_bldg and best_dist < 20.0:
                            best_bldg['is_target'] = True
                            matched = True
                            print(f"  ✓ Kohderakennus: #{best_bldg['id']} (geom: {target_obs.get('id')}, etäisyys: {best_dist:.1f}m)")
                    
                    # 2. Yritä koordinaattioffsetilla (nested-hila lokaalissa koordinaatistossa)
                    # Fine-gridi voi käyttää lokaaleja koordinaatteja (0-based) kun geometria 
                    # on domain-koordinaateissa (0-400m). Offset = fine_grid_origin.
                    if not matched and tx is not None and building_analysis.get('fine_region'):
                        fr = building_analysis['fine_region']
                        # Jos fine-grid alkaa läheltä nollaa mutta geometria on isommissa koordinaateissa,
                        # lasketaan offset domain-tiedoista
                        domain_info = geom_data.get('domain', {}) if geom_data else {}
                        domain_w = domain_info.get('width', 0)
                        
                        if fr['x_min'] < 10 and domain_w > fr['x_max'] * 1.5:
                            # Fine grid on lokaalissa koordinaatistossa
                            # Offset arvioidaan: kohteen sijainti geometriassa - fine grid keskipiste
                            # Koska hila on keskitetty kohteeseen, offset ≈ geometria_center - fine_center
                            fine_cx = (fr['x_min'] + fr['x_max']) / 2
                            fine_cy = (fr['y_min'] + fr['y_max']) / 2
                            
                            # Kokeillaan: transformoi geometriakoordinaatit lokaaliin
                            # B58 domain (200,200), fine grid (0-193), fine center (97,97)
                            # → offset = 200 - 97 = 103 → local_x = 200 - 103 = 97
                            # Tämä on likiarvo, koska hila ei aina ole täsmälleen keskitetty
                            offset_x = tx - fine_cx
                            offset_y = ty - fine_cy
                            tx_local = tx - offset_x  # = fine_cx
                            ty_local = ty - offset_y  # = fine_cy
                            
                            best_bldg = None
                            best_dist = float('inf')
                            for bldg in building_analysis['buildings']:
                                d = np.sqrt((bldg['center_x'] - tx_local)**2 + (bldg['center_y'] - ty_local)**2)
                                if d < best_dist:
                                    best_dist = d
                                    best_bldg = bldg
                            
                            if best_bldg and best_dist < 25.0:
                                best_bldg['is_target'] = True
                                matched = True
                                print(f"  ✓ Kohderakennus: #{best_bldg['id']} (geom: {target_obs.get('id')}, offset-match, etäisyys: {best_dist:.1f}m)")
                    
                    # 3. Fallback: lähin rakennus hilan keskipisteeseen
                    # Nested-hila on aina keskitetty kohderakennuksen ympärille,
                    # joten lähinnä keskipistettä oleva rakennus on kohde.
                    if not matched and building_analysis.get('fine_region'):
                        fr = building_analysis['fine_region']
                        cx = (fr['x_min'] + fr['x_max']) / 2
                        cy = (fr['y_min'] + fr['y_max']) / 2
                        
                        best_bldg = None
                        best_dist = float('inf')
                        for bldg in building_analysis['buildings']:
                            d = np.sqrt((bldg['center_x'] - cx)**2 + (bldg['center_y'] - cy)**2)
                            if d < best_dist:
                                best_dist = d
                                best_bldg = bldg
                        
                        if best_bldg and best_dist < 50.0:
                            best_bldg['is_target'] = True
                            matched = True
                            print(f"  ✓ Kohderakennus: #{best_bldg['id']} (geom: {target_obs.get('id')}, hilan keskipiste, etäisyys: {best_dist:.1f}m)")
                    
                    # 4. ID-pohjainen matching (B58 → 58, viimeisenä koska building_analysis ID:t ovat juoksevia)
                    if not matched:
                        target_id = target_obs.get('id', '')
                        target_id_num = target_id.lstrip('B') if target_id.startswith('B') else target_id
                        
                        for bldg in building_analysis['buildings']:
                            bldg_id = str(bldg['id'])
                            if bldg_id == target_id_num or bldg_id == target_id:
                                bldg['is_target'] = True
                                matched = True
                                print(f"  ✓ Kohderakennus: #{bldg['id']} (ID-match: {target_id})")
                                break
                    
                    if not matched:
                        print(f"  ⚠ Kohderakennusta ({target_obs.get('id')}) ei voitu yhdistää building_analysis:iin")
                else:
                    print(f"  ℹ️ Geometriassa ei is_target-merkintää ({len(geom_obstacles)} rakennusta)")
            elif not geom_obstacles:
                if geom_file_for_mml:
                    print(f"  ℹ️ Geometriatiedostossa ei obstacles-kenttää: {Path(geom_file_for_mml).name}")
            
            # Tarkista onko geometriassa jo korkeustiedot (height_mml kentät)
            heights_from_geom = False
            if geom_obstacles:
                # Luo mapping ID -> height_mml
                height_map = {}
                for obs in geom_obstacles:
                    obs_id = obs.get('id', '')
                    # Poista mahdollinen etuliite (B1 -> 1)
                    if obs_id.startswith('B'):
                        obs_id = obs_id[1:]
                    height_mml = obs.get('height_mml')
                    if height_mml is not None:
                        height_map[obs_id] = height_mml
                
                if height_map:
                    print(f"  ✓ Korkeudet geometriatiedostosta: {len(height_map)} rakennusta")
                    heights_from_geom = True
                    
                    # Lisää korkeudet building_analysis:iin
                    for bldg in building_analysis['buildings']:
                        bldg_id = str(bldg['id'])
                        if bldg_id in height_map:
                            bldg['mml_height'] = height_map[bldg_id]
                            bldg['mml_match_distance'] = 0.0  # Täsmällinen match
                    
                    # Tunnista korkein rakennus
                    heights_with_id = [(b['id'], b.get('mml_height')) for b in building_analysis['buildings'] 
                                      if b.get('mml_height') is not None]
                    
                    if len(heights_with_id) >= 2:
                        sorted_heights = sorted(heights_with_id, key=lambda x: x[1], reverse=True)
                        highest_id, highest_h = sorted_heights[0]
                        second_h = sorted_heights[1][1]
                        
                        if highest_h - second_h > 2.0:
                            for bldg in building_analysis['buildings']:
                                if bldg['id'] == highest_id:
                                    bldg['is_highest'] = True
                                    bldg['height_advantage'] = highest_h - second_h
                                    print(f"  Korkein rakennus: #{highest_id} ({highest_h:.1f}m, +{highest_h - second_h:.1f}m)")
                                else:
                                    bldg['is_highest'] = False
                        else:
                            for bldg in building_analysis['buildings']:
                                bldg['is_highest'] = False
            
            # Jos geometriassa ei ollut korkeuksia, hae MML:stä
            if not heights_from_geom and geom_meta and 'center_lat' in geom_meta and 'center_lon' in geom_meta:
                try:
                    mml_data = fetch_building_heights_from_mml(
                        center_lat=geom_meta['center_lat'],
                        center_lon=geom_meta['center_lon'],
                        domain_width=domain.get('width', 600),
                        domain_height=domain.get('height', 600),
                        timeout=10.0
                    )
                    
                    if mml_data:
                        building_analysis = match_mml_heights_to_buildings(
                            building_analysis, mml_data, match_radius=15.0
                        )
                        
                        # Tallenna korkeudet JSON-tiedostoon jatkokäyttöä varten
                        mml_json_path = results_path / 'building_heights_mml.json'
                        if save_mml_heights_to_json(building_analysis, mml_json_path):
                            print(f"  ✓ MML-korkeudet tallennettu: {mml_json_path.name}")
                except Exception as e:
                    print(f"  Varoitus: MML-korkeushaku epäonnistui: {e}")
        
        # Luo kansilehden kuva kriittisistä pisteistä
        cover_image = None
        if building_analysis:
            cover_image = create_cover_image(results_path, building_analysis)
            if cover_image:
                print(f"  ✓ Kansilehden kuva luotu")
        
        # Lataa dominoiva suunta -data (multi-wind)
        dominance_data = None
        dominance_path = results_path / 'direction_dominance.json'
        if dominance_path.exists():
            try:
                with open(dominance_path, 'r', encoding='utf-8') as f:
                    dom_json = json.load(f)
                dominance_data = dom_json.get('directions', [])
            except:
                pass
        
        # 1. Kansilehti (nyt kuvalla)
        add_title_page(pdf, title, cover_image, lang=lang)
        print("  ✓ Kansilehti")
        
        # 2. Yhteenveto
        add_summary_page(pdf, title, report_data, building_analysis, dominance_data, lang=lang)
        print("  ✓ Yhteenveto")
        
        # 2b. Rakennusten tunnisteet -kuva (jos analyysi onnistui)
        building_ids_img = None
        if building_analysis:
            building_ids_img = create_building_id_overlay(results_path, building_analysis)
            if building_ids_img and building_ids_img.exists():
                # Käytetään "Kriittiset pisteet" otsikkoa kummassakin raportissa
                critical_title = 'Kriittiset pisteet' if lang == 'fi' else 'Critical Points'
                building_ids_caption = f'{get_text("figure", lang)}: {critical_title}'
                building_ids_section = f'1.4 {critical_title}'
                if lang == 'en':
                    building_ids_desc = (
                        'Background shows convection index (√k·v) - dark color = strong cooling.\n'
                        'Symbols indicate critical points for each building.\n'
                        'Legend at bottom of image.'
                    )
                else:
                    building_ids_desc = (
                        'Taustalla konvektioindeksi (√k·v) - tumma väri = voimakas jäähtyminen.\n'
                        'Symbolit osoittavat kunkin rakennuksen kriittisimmät pisteet.\n'
                        'Selite kuvan alalaidassa.'
                    )
                add_image_page(pdf, building_ids_img,
                              building_ids_caption,
                              building_ids_section,
                              description=building_ids_desc)
                print(f"  ✓ Kriittiset pisteet: {building_ids_img.name}")
        
        # 2c. Kohderakennuksen lähikuva (is_target)
        if building_analysis:
            target_detail_img = create_target_building_detail(results_path, building_analysis)
            if target_detail_img and target_detail_img.exists():
                detail_title = 'Kohderakennus – lähikuva' if lang == 'fi' else 'Target Building – Detail View'
                detail_caption = f'{get_text("figure", lang)}: {detail_title}'
                detail_section = f'1.5 {detail_title}'
                has_wf = building_analysis.get('has_wall_functions', False)
                if lang == 'en':
                    detail_desc = (
                        'Detailed view of the target building with 10 m margins. '
                        'Symbols show critical points:\n'
                        'pressure (Cp), velocity, '
                        'convection index CI = √k × v (turbulence intensity × wind speed)'
                    )
                    if has_wf:
                        detail_desc += (
                            ' and heat transfer\ncoefficient h [W/(m²·K)].\n'
                            'The design reference value per EN ISO 6946 is $h_e$ = 25 W/(m²·K) '
                            '($R_{se}$ = 0.04 m²·K/W),\n'
                            'corresponding to approx. 4 m/s wind speed. '
                            'Values exceeding this indicate higher actual heat loss than assumed in U-value calculations.'
                        )
                    else:
                        detail_desc += '.\nAnnotated values indicate magnitude at each critical point.'
                else:
                    detail_desc = (
                        'Kohderakennuksen lähikuva 10 m marginaalilla. '
                        'Symbolit osoittavat kriittiset pisteet:\n'
                        'Paine (Cp), nopeus, '
                        'konvektioindeksi CI = √k × v (turbulenssin voimakkuus × tuulennopeus)'
                    )
                    if has_wf:
                        detail_desc += (
                            ' ja lämmönsiirtokerroin h [W/(m²·K)].\n'
                            'RakMK:n / EN ISO 6946 mukainen ulkopinnan suunnitteluarvo on '
                            '$h_e$ = 25 W/(m²·K) ($R_{se}$ = 0,04 m²·K/W),\n'
                            'mikä vastaa n. 4 m/s tuulennopeutta. '
                            'Tämän ylittävät arvot tarkoittavat, että todellinen lämpöhäviö on U-arvolaskentaa suurempi.'
                        )
                    else:
                        detail_desc += '.\nAnnotaatiot näyttävät kunkin pisteen arvon.'
                add_image_page(pdf, target_detail_img,
                              detail_caption,
                              detail_section,
                              description=detail_desc)
                print(f"  ✓ Kohderakennuksen lähikuva: {target_detail_img.name}")
        
        # Tarkista onko multi-wind simulointi (combined-kansio)
        # Tämä tarvitaan sekä tuuliruusun generointiin että combined-osion näyttämiseen
        multi_wind_metadata_path = results_path.parent / "multi_wind_metadata.json"
        is_multi_wind = "combined" in str(results_path) and multi_wind_metadata_path.exists()
        
        # Yritä löytää geometriatiedosto automaattisesti jos ei annettu (tarvitaan tuuliruusulle)
        if not geometry_path:
            # Etsi .json tiedostoja eri paikoista
            search_paths = [
                results_path,                          # Tuloskansio
                results_path.parent,                   # Tuloskansion yläkansio
                Path('examples/OSMgeometry'),          # Oletus OSM-geometriakansio
                Path(__file__).parent / 'examples' / 'OSMgeometry',  # Suhteessa skriptiin
            ]
            
            json_files = []
            for sp in search_paths:
                if sp.exists():
                    json_files.extend(sp.glob('*.json'))
            
            # Suosi tiedostoja joiden nimi ei ole config/settings
            for jf in json_files:
                if 'config' not in jf.name.lower() and 'settings' not in jf.name.lower():
                    geometry_path = str(jf)
                    print(f"  Löytyi geometria: {jf}")
                    break
        
        # Tuuliruusut
        if geometry_path:
            wind_rose_path = results_path / "wind_rose.png"
            city = None  # Alustetaan city
            
            if is_multi_wind:
                # Multi-wind: generoi tuuliruusu kaikilla simuloiduilla suunnilla
                try:
                    with open(multi_wind_metadata_path, 'r', encoding='utf-8') as f:
                        multi_metadata = json.load(f)
                    simulations = multi_metadata.get('simulations', [])
                    city = multi_metadata.get('city', None)
                    
                    if generate_multi_wind_rose(simulations, wind_rose_path):
                        print(f"  ✓ Multi-wind tuuliruusu generoitu: {wind_rose_path.name}")
                except Exception as e:
                    print(f"  Varoitus: Multi-wind tuuliruusu epäonnistui: {e}")
                    # Fallback: yksittäinen tuuliruusu
                    generate_wind_rose(Path(geometry_path), wind_rose_path, results_dir=results_path)
            else:
                # Normaali: yksittäinen tuulensuunta
                if generate_wind_rose(Path(geometry_path), wind_rose_path, results_dir=results_path):
                    print(f"  ✓ Tuuliruusu generoitu: {wind_rose_path.name}")
            
            # Hae FMI-tuuliruusu kaupungin perusteella
            fmi_wind_rose_path = results_path / "fmi_wind_rose.png"
            
            if not city:
                city = find_city_from_geometry(Path(geometry_path))
            if not city:
                city = 'Helsinki'
                print(f"  Kaupunkia ei tunnistettu, käytetään Helsinkiä")
            else:
                print(f"  Kaupunki: {city}")
            
            # Etsi valmis tuuliruusu kansiosta analysisreportfiles/fmi_tuuliruusut/
            # Tiedostonimet: helsinki_tuuliruusu.png, tampere_tuuliruusu.png jne.
            city_filename = city.lower().replace('ä', 'a').replace('ö', 'o').replace(' ', '_')
            
            # Etsi kansiosta eri sijainneista
            fmi_search_paths = [
                Path(__file__).parent / 'analysisreportfiles' / 'fmi_tuuliruusut',
                Path('analysisreportfiles') / 'fmi_tuuliruusut',
                Path.cwd() / 'analysisreportfiles' / 'fmi_tuuliruusut',
            ]
            
            fmi_source_found = False
            for search_path in fmi_search_paths:
                source_file = search_path / f'{city_filename}_tuuliruusu.png'
                if source_file.exists():
                    # Kopioi valmis tuuliruusu tuloshakemistoon
                    import shutil
                    shutil.copy(source_file, fmi_wind_rose_path)
                    print(f"  ✓ FMI-tuuliruusu (valmis): {source_file.name}")
                    fmi_source_found = True
                    break
            
            # Jos valmista ei löydy, generoi uusi
            if not fmi_source_found:
                if generate_fmi_wind_rose(city, fmi_wind_rose_path):
                    print(f"  ✓ FMI-tuuliruusu generoitu: {fmi_wind_rose_path.name}")
        
        # 3. Nested comparison
        nested_img = results_path / "nested_comparison.png"
        
        # Jos nested_comparison ei ole combined-kansiossa, etsi se wind_*-kansioista
        if not nested_img.exists() and "combined" in str(results_path):
            parent_dir = results_path.parent
            wind_dirs = sorted(parent_dir.glob("wind_*"))
            for wind_dir in wind_dirs:
                candidate = wind_dir / "nested_comparison.png"
                if candidate.exists():
                    nested_img = candidate
                    print(f"  Käytetään hilavertailua: {candidate.relative_to(parent_dir)}")
                    break
        
        wind_rose_img = results_path / "wind_rose.png"
        fmi_wind_rose_img = results_path / "fmi_wind_rose.png"
        
        # Käännökset kuvateksteille
        fig_text = get_text('figure', lang)
        
        # Jos molemmat tuuliruusut löytyvät, yhdistä samalle sivulle
        if wind_rose_img.exists() and fmi_wind_rose_img.exists():
            if lang == 'en':
                wr_caption1 = f"{fig_text} 1: Simulation wind direction"
                wr_caption2 = f"{fig_text} 2: Location - annual wind distribution (FMI)"
                wr_section = f"2. {get_text('wind_directions', lang)}"
                wr_desc = (
                    'Simulation wind direction (top) and annual wind distribution\n'
                    'for the location (bottom, Finnish Meteorological Institute).'
                )
            else:
                wr_caption1 = f"{fig_text} 1: Simuloinnin tuulensuunta"
                wr_caption2 = f"{fig_text} 2: Paikkakunta - vuotuinen tuulijakauma (FMI)"
                wr_section = f"2. {get_text('wind_directions', lang)}"
                wr_desc = (
                    'Simuloinnin tuulensuunta (ylhäällä) ja paikkakunnan vuotuinen\n'
                    'tuulijakauma (alhaalla, Ilmatieteen laitos).'
                )
            
            add_two_images_page(pdf, wind_rose_img, fmi_wind_rose_img,
                               wr_caption1, wr_caption2, wr_section, description=wr_desc)
            print(f"  ✓ Tuuliruusut (yhdistetty sivu)")
            img_num = 3
            section_num = 3
            
            # Hilavertailu jos löytyy
            if nested_img.exists():
                if lang == 'en':
                    grid_caption = f"{fig_text} {img_num}: Coarse and fine grid comparison"
                    grid_section = f"{section_num}. {get_text('grid_comparison', lang)}"
                else:
                    grid_caption = f"{fig_text} {img_num}: Karkean ja tiheän hilan vertailu"
                    grid_section = f"{section_num}. {get_text('grid_comparison', lang)}"
                
                add_image_page(pdf, nested_img, grid_caption, grid_section)
                print(f"  ✓ Nested comparison: {nested_img.name}")
                img_num += 1
                
                # Hilavisualisointi (laskentahila)
                grid_viz_img = _find_or_generate_grid_visualization(results_path, lang=lang, dpi=REPORT_DPI)
                if grid_viz_img:
                    if lang == 'en':
                        gv_caption = f"{fig_text} {img_num}: Computational grid structure"
                    else:
                        gv_caption = f"{fig_text} {img_num}: Laskentahilan rakenne"
                    add_image_page(pdf, grid_viz_img, gv_caption, grid_section)
                    print(f"  ✓ Hilavisualisointi: {grid_viz_img.name}")
                    img_num += 1
                
                section_num += 1
                
        # Jos vain simuloinnin tuuliruusu löytyy (ei FMI-ruusua)
        elif wind_rose_img.exists():
            if lang == 'en':
                wr_caption = f"{fig_text} 1: Simulation wind direction"
                wr_section = "2. Wind direction"
            else:
                wr_caption = f"{fig_text} 1: Simuloinnin tuulensuunta"
                wr_section = "2. Tuulensuunta"
            
            add_image_page(pdf, wind_rose_img, wr_caption, wr_section)
            print(f"  ✓ Tuuliruusu")
            img_num = 2
            section_num = 3
            
            # Lisää nested comparison erikseen jos löytyy
            if nested_img.exists():
                if lang == 'en':
                    grid_caption = f"{fig_text} {img_num}: Coarse and fine grid comparison"
                    grid_section = f"{section_num}. {get_text('grid_comparison', lang)}"
                else:
                    grid_caption = f"{fig_text} {img_num}: Karkean ja tiheän hilan vertailu"
                    grid_section = f"{section_num}. {get_text('grid_comparison', lang)}"
                
                add_image_page(pdf, nested_img, grid_caption, grid_section)
                print(f"  ✓ Nested comparison: {nested_img.name}")
                img_num += 1
                
                # Hilavisualisointi (laskentahila)
                grid_viz_img = _find_or_generate_grid_visualization(results_path, lang=lang, dpi=REPORT_DPI)
                if grid_viz_img:
                    if lang == 'en':
                        gv_caption = f"{fig_text} {img_num}: Computational grid structure"
                    else:
                        gv_caption = f"{fig_text} {img_num}: Laskentahilan rakenne"
                    add_image_page(pdf, grid_viz_img, gv_caption, grid_section)
                    print(f"  ✓ Hilavisualisointi: {grid_viz_img.name}")
                    img_num += 1
                
                section_num += 1
        elif nested_img.exists():
            # Vain hilavertailu
            if lang == 'en':
                grid_caption = f"{fig_text} 1: Coarse and fine grid comparison"
                grid_section = f"2. {get_text('grid_comparison', lang)}"
            else:
                grid_caption = f"{fig_text} 1: Karkean ja tiheän hilan vertailu"
                grid_section = f"2. {get_text('grid_comparison', lang)}"
            
            add_image_page(pdf, nested_img, grid_caption, grid_section)
            print(f"  ✓ Nested comparison: {nested_img.name}")
            img_num = 2
            
            # Hilavisualisointi (laskentahila)
            grid_viz_img = _find_or_generate_grid_visualization(results_path, lang=lang, dpi=REPORT_DPI)
            if grid_viz_img:
                if lang == 'en':
                    gv_caption = f"{fig_text} {img_num}: Computational grid structure"
                else:
                    gv_caption = f"{fig_text} {img_num}: Laskentahilan rakenne"
                add_image_page(pdf, grid_viz_img, gv_caption, grid_section)
                print(f"  ✓ Hilavisualisointi: {grid_viz_img.name}")
                img_num += 1
            
            section_num = 3
        else:
            # Ei tuuliruusua eikä hilakuvaa
            img_num = 1
            section_num = 2
            print(f"  ⚠ Tuuliruusua tai hilakuvaa ei löytynyt")
        
        # 3b. Adaptiivinen hila (jos käytössä)
        adaptive_img = None
        for pattern in ['*adaptive_grid.png', '*_adaptive_grid.png']:
            adaptive_imgs = list(results_path.glob(pattern))
            if adaptive_imgs:
                adaptive_img = adaptive_imgs[0]
                break
        
        if adaptive_img and adaptive_img.exists():
            add_image_page(pdf, adaptive_img,
                          f"Kuva {img_num}: Vasemmalla seinäetäisyys, oikealla adaptiivinen hila (tiheämpi lähellä rakennuksia)",
                          f"{section_num}. Adaptiivinen laskentahila")
            print(f"  ✓ Adaptiivinen hila: {adaptive_img.name}")
            img_num += 1
            section_num += 1
        
        # 4. Fine-visualisoinnit (nested) tai päätulokset (adaptive/standard)
        fine_dir = results_path / "fine"
        fine_images = []
        section_title = "Tiheän hilan tulokset"
        
        # Diagnostiikkakuvat jotka ohitetaan raportissa
        # turbulence_k: kineettinen energia ei ole rakennusfysikaalinen suure - TI ja konvektio riittävät
        diagnostic_patterns = ['blending', 'y_plus', 'f1_', 'f2_', '_f1', '_f2', 'omega', 'nu_t', 'turbulence_nu', 'turbulence_k']
        
        # Kuvat jotka ohitetaan raportissa (mutta pidetään visualisoinneissa)
        # Painekuva ja nopeuskuva ilman virtaviivoja korvattu virtaviivallisilla versioilla
        report_excluded_exact = ['pressure.png', 'velocity.png']  # Täsmälliset tiedostonimet
        
        # Tarkista onko kyseessä combined-kansio (multi-wind)
        is_combined_folder = "combined" in str(results_path) and is_multi_wind
        
        if fine_dir.exists():
            all_fine_images = find_images(fine_dir, "*.png")
            # Suodata pois diagnostiikkakuvat ja raportista poistetut kuvat
            for img in all_fine_images:
                name_lower = img.name.lower()
                # Ohita diagnostiikkakuvat
                if any(diag in name_lower for diag in diagnostic_patterns):
                    continue
                # Ohita raportista poistetut kuvat (esim. pressure.png ilman streamlines)
                if any(img.name.lower().endswith(excl.lower()) for excl in report_excluded_exact):
                    continue
                fine_images.append(img)
            print(f"  Fine-kansio löytyi: {len(fine_images)} kuvaa (suodatettu {len(all_fine_images) - len(fine_images)} diagnostiikkakuvaa)")
        elif is_combined_folder:
            # Combined-kansiossa kuvat ovat suoraan päähakemistossa
            # Näitä käsitellään myöhemmin combined-osiossa, joten tässä ei tehdä mitään
            print(f"  Combined-kansio: kuvat käsitellään combined-osiossa")
        else:
            print(f"  ⚠ fine/ -kansiota ei löydy, etsitään päähakemistosta")
            # Etsi päähakemistosta tuloskuvia
            all_imgs = find_images(results_path, "*.png")
            
            # Suodata pois jo käsitellyt kuvat ja hallintakuvat
            excluded = ['nested_comparison', 'adaptive_grid', 'geometry_view', 
                       'coarse_cropped', 'comparison', 'combined_', 'wind_rose',
                       'fmi_wind_rose', 'building_ids', 'kriittiset_pisteet',
                       'grid_visualization']
            
            for img in all_imgs:
                name_lower = img.name.lower()
                # Ohita excluded-lista
                if any(ex in name_lower for ex in excluded):
                    continue
                # Ohita raportista poistetut kuvat (esim. pressure.png ilman streamlines)
                if any(img.name.lower().endswith(excl.lower()) for excl in report_excluded_exact):
                    continue
                # Hyväksy fine-kuvat tai tuloskuvat (velocity, pressure, comfort, turbulence, convection, wall functions)
                if ('fine' in name_lower or 
                    'velocity' in name_lower or 
                    'pressure' in name_lower or
                    'comfort' in name_lower or
                    'turbulence' in name_lower or
                    'convection' in name_lower or
                    'u_tau' in name_lower):
                    # Ohita diagnostiikkakuvat
                    if not any(diag in name_lower for diag in diagnostic_patterns):
                        fine_images.append(img)
            
            print(f"  Löytyi {len(fine_images)} tuloskuvaa päähakemistosta")
            
            # Adaptiivisessa simuloinnissa käytä eri otsikkoa
            if adaptive_img:
                section_title = "Simuloinnin tulokset"
        
        if fine_images:
            # Järjestä kuvat (vain rakennusfysikaalisesti merkitykselliset)
            # HUOM: omega ja nu_t poistettu - ne ovat turbulenssimallin sisäisiä parametreja
            # HUOM: pressure ja velocity poistettu - käytetään vain streamlines-versioita
            order = ['velocity_streamlines', 'pressure_streamlines', 
                    'comfort', 'turbulence_TI', 'convection',
                    'u_tau', 'adaptive_grid']
            
            def sort_key(path):
                name = path.stem.lower()
                for i, key in enumerate(order):
                    if key in name:
                        return i
                return 100
            
            fine_images.sort(key=sort_key)
            
            first_fine = True
            for img_path in fine_images:
                section = f"{section_num}. {section_title}" if first_fine else None
                first_fine = False
                
                add_image_page(pdf, img_path,
                              f"Kuva {img_num}: {get_caption(img_path)}",
                              section,
                              description=get_description(img_path))
                print(f"  ✓ {img_path.name}")
                img_num += 1
        
        # 5b. Combined visualisaatiot (VAIN multi-wind simuloinneille)
        # Yksittäisen tuulensuunnan raporttiin ei lisätä combined-osioita
        if is_multi_wind:
            combined_images = []
            
            # Lisää ensin kriittisten pisteiden visualisointi jos löytyy
            critical_points_path = results_path / 'kriittiset_pisteet.png'
            if not critical_points_path.exists():
                # Yritä myös englanninkielistä nimeä
                critical_points_path = results_path / 'critical_points.png'
            
            # Sama kuvaus kuin yksittäisen suunnan raportissa
            if lang == 'en':
                critical_points_desc = (
                    'Background shows convection index (√k·v) - dark color = strong cooling.\n'
                    'Symbols indicate critical points for each building.\n'
                    'Legend at bottom of image.'
                )
            else:
                critical_points_desc = (
                    'Taustalla konvektioindeksi (√k·v) - tumma väri = voimakas jäähtyminen.\n'
                    'Symbolit osoittavat kunkin rakennuksen kriittisimmät pisteet.\n'
                    'Selite kuvan alalaidassa.'
                )
            
            # HUOM: Kriittiset pisteet on jo kappaleessa 1.4, ei lisätä uudelleen tähän
            # if critical_points_path.exists():
            #     critical_title = 'Kriittiset pisteet' if lang == 'fi' else 'Critical Points'
            #     combined_images.append((critical_points_path, critical_title, critical_points_desc))
            
            # Käytä TRANSLATIONS-sanakirjaa combined-kuvauksiin
            combined_desc = TRANSLATIONS[lang]['combined_descriptions']
            combined_viz_files = [
                ('combined_wdr_moisture.png', *combined_desc['wdr']),
                ('combined_pressure_max.png', *combined_desc['pressure_max']),
                ('combined_pressure_min.png', *combined_desc['pressure_min']),
                ('combined_pressure_range.png', *combined_desc['pressure_range']),
                ('combined_velocity_typical.png', *combined_desc['velocity_typical']),
                ('combined_convection.png', *combined_desc['convection']),
                ('combined_structural.png', *combined_desc['structural']),
                ('combined_turbulence_intensity.png', *combined_desc['turbulence_intensity']),
                ('combined_u_tau.png', *combined_desc['u_tau']),
            ]
            
            # Lisää ISO 15927-3 WDR-visualisointi jos --wdr käytössä
            wdr_absolute_path = results_path / 'wdr_absolute.png'
            if wdr_absolute_path.exists():
                wdr_title = 'Viistosadeindeksi ISO 15927-3 (WDR)' if lang == 'fi' else 'Wind-Driven Rain Index ISO 15927-3 (WDR)'
                wdr_desc = ('Absoluuttinen viistosaderasitus l/m²/vuosi FMI-säädatasta ja CFD-painejakaumasta.\n'
                           'BS 8104 rasitusluokat: Suojaisa (<33), Kohtalainen (33-56.5), Ankara (56.5-100), Erittäin ankara (>100).'
                           if lang == 'fi' else
                           'Absolute wind-driven rain exposure l/m²/year from FMI weather data and CFD pressure distribution.\n'
                           'BS 8104 exposure classes: Sheltered (<33), Moderate (33-56.5), Severe (56.5-100), Very severe (>100).')
                combined_images.append((wdr_absolute_path, wdr_title, wdr_desc))
            
            for viz_file, caption, description in combined_viz_files:
                viz_path = results_path / viz_file
                if viz_path.exists():
                    combined_images.append((viz_path, caption, description))
            
            # Lisää energiaindeksisivu ENNEN combined-taulukkoa jos data saatavilla
            energy_index_path = results_path / 'building_energy_index.json'
            if energy_index_path.exists():
                try:
                    with open(energy_index_path, 'r', encoding='utf-8') as f:
                        energy_data = json.load(f)
                    energy_stats = energy_data.get('buildings', [])
                    
                    if energy_stats:
                        section_num += 1
                        add_energy_index_page(pdf, energy_stats, section_num=section_num, lang=lang)
                        print(f"  ✓ Energiaindeksitaulukko ({len(energy_stats)} rakennusta)")
                except Exception as e:
                    print(f"  Varoitus: Energiaindeksin lataus epäonnistui: {e}")
            
            # Lisää tuulensuunta-analyysisivu jos data saatavilla
            if dominance_data and len(dominance_data) > 1:
                section_num += 1
                add_wind_direction_analysis_page(pdf, dominance_data, section_num, lang=lang)
                print(f"  ✓ Tuulensuunta-analyysitaulukko ({len(dominance_data)} suuntaa)")
                
                # Lisää dominoivien tuulensuuntien visualisoinnit (top 2)
                # Haetaan wind-kansioiden polut multi_wind_metadata.json:sta
                multi_wind_metadata_path = results_path.parent / "multi_wind_metadata.json"
                if multi_wind_metadata_path.exists():
                    try:
                        with open(multi_wind_metadata_path, 'r', encoding='utf-8') as f:
                            mw_metadata = json.load(f)
                        
                        # Käydään läpi top 2 dominoivaa suuntaa
                        for rank, dom_dir in enumerate(dominance_data[:2], 1):
                            target_direction = dom_dir.get('direction', 0)
                            
                            # Etsi vastaava simulointi metadatasta
                            for sim in mw_metadata.get('results', []):
                                sim_direction = sim.get('direction', -999)
                                if abs(sim_direction - target_direction) < 1 and sim.get('converged', False):
                                    sim_dir = Path(sim.get('output_dir', ''))
                                    fine_dir = sim_dir / 'fine'
                                    
                                    if fine_dir.exists():
                                        # Etsi kaikki 4 kuvaa: velocity, velocity_streamlines, pressure, pressure_streamlines
                                        vel_img = None
                                        vel_stream_img = None
                                        pres_img = None
                                        pres_stream_img = None
                                        
                                        for img_file in fine_dir.glob('*.png'):
                                            name_lower = img_file.name.lower()
                                            # Virtaviivakuvat
                                            if 'velocity_streamlines' in name_lower or 'velocity_stream' in name_lower:
                                                vel_stream_img = img_file
                                            elif 'pressure_streamlines' in name_lower or 'pressure_stream' in name_lower:
                                                pres_stream_img = img_file
                                            # Pelkät kentät (ei streamlines nimessä)
                                            elif 'velocity' in name_lower and 'streamlines' not in name_lower and 'comfort' not in name_lower:
                                                vel_img = img_file
                                            elif 'pressure' in name_lower and 'streamlines' not in name_lower:
                                                pres_img = img_file
                                        
                                        # Hae suunnan nimi
                                        dir_name = dom_dir.get('direction_name', '')
                                        if not dir_name:
                                            # Muunna CFD-asteet meteorologisiksi (kompassi)
                                            # CFD: 0°=W-tuuli, 90°=S-tuuli, 180°=E-tuuli, 270°=N-tuuli
                                            # Meteo: 0°=N-tuuli, 90°=E-tuuli, 180°=S-tuuli, 270°=W-tuuli
                                            meteo_deg = (270 - target_direction + 360) % 360
                                            dirs = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 
                                                   'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW']
                                            idx = int((meteo_deg + 11.25) / 22.5) % 16
                                            dir_name = dirs[idx]
                                        
                                        rank_text = "Dominoiva" if rank == 1 else "Toissijainen"
                                        rank_text_en = "Dominant" if rank == 1 else "Secondary"
                                        impact_pct = dom_dir.get('combined_impact', 0)
                                        
                                        # 1. Nopeuskenttä + virtaviivat
                                        if vel_stream_img and vel_stream_img.exists():
                                            if lang == 'en':
                                                caption = f"{rank_text_en} direction {target_direction:.0f}° ({dir_name}) - Velocity field with streamlines"
                                                desc = f"Velocity field with streamlines for the {rank_text_en.lower()} wind direction.\nThis direction accounts for {impact_pct:.0f}% of the total wind impact on the area."
                                            else:
                                                caption = f"{rank_text} suunta {target_direction:.0f}° ({dir_name}) - Nopeuskenttä + virtaviivat"
                                                desc = f"Nopeuskenttä virtaviivoin {rank_text.lower()}lle tuulensuunnalle.\nTämä suunta vastaa {impact_pct:.0f}% alueen kokonaistuulirasituksesta."
                                            
                                            add_image_page(pdf, vel_stream_img,
                                                          f"Kuva {img_num}: {caption}",
                                                          section=None,
                                                          description=desc)
                                            print(f"  ✓ {rank_text} suunta {target_direction:.0f}° - nopeuskenttä + virtaviivat")
                                            img_num += 1
                                        
                                        # 2. Pelkkä nopeuskenttä - OHITETTU
                                        # Käytetään vain virtaviivallista versiota (velocity_streamlines)
                                        # if vel_img and vel_img.exists():
                                        #     ... (poistettu)
                                        
                                        # 3. Painekenttä + virtaviivat
                                        if pres_stream_img and pres_stream_img.exists():
                                            if lang == 'en':
                                                caption = f"{rank_text_en} direction {target_direction:.0f}° ({dir_name}) - Pressure field with streamlines"
                                                desc = f"Pressure coefficient (Cp) field with streamlines for the {rank_text_en.lower()} wind direction.\nPositive values indicate overpressure, negative values indicate suction."
                                            else:
                                                caption = f"{rank_text} suunta {target_direction:.0f}° ({dir_name}) - Painekenttä + virtaviivat"
                                                desc = f"Painekerroin (Cp) virtaviivoin {rank_text.lower()}lle tuulensuunnalle.\nPositiiviset arvot = ylipaine, negatiiviset = alipaine (imu)."
                                            
                                            add_image_page(pdf, pres_stream_img,
                                                          f"Kuva {img_num}: {caption}",
                                                          section=None,
                                                          description=desc)
                                            print(f"  ✓ {rank_text} suunta {target_direction:.0f}° - painekenttä + virtaviivat")
                                            img_num += 1
                                        
                                        # 4. Pelkkä painekenttä - OHITETTU
                                        # Käytetään vain virtaviivallista versiota (pressure_streamlines)
                                        # Vanhan koodin tilalla kommentti
                                        # if pres_img and pres_img.exists():
                                        #     ... (poistettu)
                                    
                                    break  # Löytyi vastaava simulointi
                    except Exception as e:
                        print(f"  Varoitus: Dominoivien suuntien visualisointien lataus epäonnistui: {e}")
            
            if combined_images:
                section_num += 1
                
                # Lisää yhteenvetotaulukko
                section_title = f"{section_num}. {get_text('combined_fields', lang)}"
                add_combined_summary_table(pdf, section_title, lang=lang)
                print(f"  ✓ Yhdistettyjen kenttien yhteenvetotaulukko")
                
                print(f"  Lisätään {len(combined_images)} yhdistettyä visualisointia...")
                
                for viz_path, caption, description in combined_images:
                    # Osion otsikko on jo taulukkosivulla, ei toisteta
                    add_image_page(pdf, viz_path,
                                  f"Kuva {img_num}: {caption}",
                                  section=None,
                                  description=description)
                    print(f"  ✓ {viz_path.name}")
                    img_num += 1
        
        # 5. Tuulisuusanalyysi (Lawsonin kriteerit) - AINA combined-raportissa
        if is_multi_wind:
            section_num += 1
            # Välitä multi_wind kansio painotetun raportin lataamiseen
            multi_wind_dir = results_path.parent if 'combined' in str(results_path) else results_path
            add_windiness_analysis_page(pdf, section_num, lang=lang, results_dir=multi_wind_dir)
            print(f"  ✓ Tuulisuusanalyysi (Lawsonin kriteerit)")
        else:
            # Yksittäisen suunnan raportti - käytä samaa sivupohjaa kuin combined
            section_num += 1
            
            # Parsii comfort_report.txt tilastot
            single_stats = None
            wind_dir_name = ""
            
            # Etsi comfort_report tiedosto
            comfort_file = None
            for cf_candidate in [
                results_path / 'fine' / 'comfort_report_nested.txt',
                results_path / 'fine' / 'comfort_report.txt',
                results_path / 'comfort_report_nested.txt',
                results_path / 'comfort_report.txt',
            ]:
                if cf_candidate.exists():
                    comfort_file = cf_candidate
                    break
            
            if comfort_file:
                single_stats = parse_comfort_report(comfort_file)
            
            # Hae tuulensuunnan nimi metadatasta tai kansion nimestä
            if report_data.get('metadata'):
                meta = report_data['metadata']
                direction = meta.get('wind_direction', meta.get('direction', 0))
                # Muunna CFD-asteet meteorologisiksi
                meteo_deg = (270 - direction + 360) % 360
                dirs = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 
                       'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW']
                idx = int((meteo_deg + 11.25) / 22.5) % 16
                wind_dir_name = f"{dirs[idx]} ({direction:.0f}°)"
            elif 'wind_' in str(results_path):
                # Yritä parseia kansion nimestä
                folder_name = results_path.name
                if folder_name.startswith('wind_'):
                    try:
                        direction = float(folder_name.replace('wind_', '').replace('deg', ''))
                        meteo_deg = (270 - direction + 360) % 360
                        dirs = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 
                               'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW']
                        idx = int((meteo_deg + 11.25) / 22.5) % 16
                        wind_dir_name = f"{dirs[idx]} ({direction:.0f}°)"
                    except:
                        wind_dir_name = folder_name
            
            add_windiness_analysis_page(pdf, section_num, lang=lang, 
                                       single_direction_stats=single_stats,
                                       wind_direction=wind_dir_name)
            print(f"  ✓ Tuulisuusanalyysi (Lawsonin kriteerit)")
        
        # Rakennusfysiikan tulkinta -sivu
        section_num += 1
        add_building_physics_page(pdf, section_num, lang=lang)
        print(f"  ✓ Rakennusfysiikan tulkinta")
        
        # 6. Simuloinnin tiedot
        if is_multi_wind and multi_wind_metadata_path.exists():
            # Multi-wind raportti - käytä multi_wind_metadata.json
            try:
                with open(multi_wind_metadata_path, 'r', encoding='utf-8') as f:
                    multi_metadata = json.load(f)
                
                # Varmista että city on metadatassa
                if not multi_metadata.get('city'):
                    if city:
                        multi_metadata['city'] = city
                    elif geometry_path:
                        found_city = find_city_from_geometry(Path(geometry_path))
                        multi_metadata['city'] = found_city or 'Tuntematon'
                
                # Lataa geometriadata jos saatavilla
                geom_data_for_settings = None
                if geom_file_for_mml:
                    try:
                        with open(geom_file_for_mml, 'r', encoding='utf-8') as f:
                            geom_data_for_settings = json.load(f)
                    except:
                        pass
                
                section_num += 1
                add_simulation_settings_page(pdf, multi_metadata, section_num, lang=lang,
                                           geometry_data=geom_data_for_settings, report_data=report_data)
                print(f"  ✓ Simuloinnin tiedot")
            except Exception as e:
                print(f"  Varoitus: Reunaehtojen lisäys epäonnistui: {e}")
        else:
            # Yksittäisen suunnan raportti - etsi metadata tai luo domain.json:sta
            single_metadata = None
            single_metadata_path = None
            
            # Etsi metadata eri paikoista
            for meta_candidate in [
                results_path / 'simulation_metadata.json',
                results_path / 'metadata.json',
                results_path / 'fine' / 'simulation_metadata.json',
                results_path / 'fine' / 'metadata.json',
                results_path.parent / 'multi_wind_metadata.json',
            ]:
                if meta_candidate.exists():
                    single_metadata_path = meta_candidate
                    break
            
            # Jos ei löytynyt metadata-tiedostoa, yritä luoda domain.json:sta
            if not single_metadata_path:
                domain_json_candidates = [
                    results_path / 'domain.json',
                    results_path / 'fine' / 'domain.json',
                    results_path / 'data' / 'domain.json',
                ]
                for domain_candidate in domain_json_candidates:
                    if domain_candidate.exists():
                        try:
                            with open(domain_candidate, 'r', encoding='utf-8') as f:
                                domain_data = json.load(f)
                            
                            # Luo metadata domain.json:sta
                            single_metadata = {
                                'name': report_data.get('name', results_path.name) if report_data else results_path.name,
                                'description': report_data.get('description', '') if report_data else '',
                                'turbulence_model': report_data.get('turbulence_model', 'SST k-ω') if report_data else 'SST k-ω',
                                'wind_direction': domain_data.get('inlet_direction', 0),
                                'inlet_velocity': domain_data.get('inlet_velocity', 5.0),
                                'city': city or (report_data.get('city') if report_data else None) or 'Tuntematon',
                                'grid': {
                                    'nx': domain_data.get('nx'),
                                    'ny': domain_data.get('ny'),
                                    'dx': domain_data.get('dx'),
                                    'dy': domain_data.get('dy'),
                                    'width': domain_data.get('width'),
                                    'height': domain_data.get('height'),
                                }
                            }
                            
                            # Tarkista onko nested grid - etsi coarse/fine tiedostot
                            coarse_domain = results_path / 'coarse' / 'domain.json'
                            fine_domain = results_path / 'fine' / 'domain.json'
                            
                            if coarse_domain.exists() and fine_domain.exists():
                                try:
                                    with open(coarse_domain, 'r', encoding='utf-8') as f:
                                        coarse_data = json.load(f)
                                    with open(fine_domain, 'r', encoding='utf-8') as f:
                                        fine_data = json.load(f)
                                    
                                    # Laske fine region
                                    fine_x_min = fine_data.get('x_offset', 0)
                                    fine_y_min = fine_data.get('y_offset', 0)
                                    fine_x_max = fine_x_min + fine_data.get('width', 0)
                                    fine_y_max = fine_y_min + fine_data.get('height', 0)
                                    
                                    # Laske refinement factor
                                    coarse_dx = coarse_data.get('dx', 2.0)
                                    fine_dx = fine_data.get('dx', 0.5)
                                    refinement = round(coarse_dx / fine_dx) if fine_dx > 0 else 4
                                    
                                    single_metadata['nested_grid_settings'] = {
                                        'fine_region': {
                                            'x_min': fine_x_min,
                                            'x_max': fine_x_max,
                                            'y_min': fine_y_min,
                                            'y_max': fine_y_max,
                                        },
                                        'refinement_factor': refinement,
                                        'coarse_nx': coarse_data.get('nx'),
                                        'coarse_ny': coarse_data.get('ny'),
                                        'coarse_dx': coarse_dx,
                                        'fine_nx': fine_data.get('nx'),
                                        'fine_ny': fine_data.get('ny'),
                                        'fine_dx': fine_dx,
                                    }
                                    print(f"  Nested grid tiedot löytynyt")
                                except Exception as e:
                                    print(f"  Varoitus: Nested grid tietojen lukeminen epäonnistui: {e}")
                            
                            print(f"  Metadata luotu domain.json:sta: {domain_candidate}")
                            break
                        except Exception as e:
                            print(f"  Varoitus: domain.json lukeminen epäonnistui: {e}")
            
            if single_metadata_path and not single_metadata:
                try:
                    with open(single_metadata_path, 'r', encoding='utf-8') as f:
                        single_metadata = json.load(f)
                except Exception as e:
                    print(f"  Varoitus: Metadata-tiedoston lukeminen epäonnistui: {e}")
            
            # Varmista että city on metadatassa (käytä aiemmin tunnistettua city-muuttujaa)
            if single_metadata and not single_metadata.get('city'):
                if city:
                    single_metadata['city'] = city
                elif geometry_path:
                    found_city = find_city_from_geometry(Path(geometry_path))
                    single_metadata['city'] = found_city or 'Tuntematon'
            
            if single_metadata:
                # Lataa geometriadata jos saatavilla
                geom_data_for_settings = None
                if geom_file_for_mml:
                    try:
                        with open(geom_file_for_mml, 'r', encoding='utf-8') as f:
                            geom_data_for_settings = json.load(f)
                    except:
                        pass
                
                section_num += 1
                add_simulation_settings_page(pdf, single_metadata, section_num, lang=lang,
                                           geometry_data=geom_data_for_settings, report_data=report_data)
                print(f"  ✓ Simuloinnin tiedot")
            else:
                print(f"  Huom: Simuloinnin tietoja ei löytynyt (metadata/domain.json puuttuu)")
    
    print(f"\n  ✓ Raportti luotu: {output_path}")
    return str(output_path)


def main():
    parser = argparse.ArgumentParser(
        description='Generoi PDF-raportti CFD-simuloinnin tuloksista',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Esimerkkejä:
  python generate_report.py results/case1/
  python generate_report.py results/case1/ --title "Rantalantie 8, Ulvila"
  python generate_report.py results/case1/ --geometry examples/area.json
  python generate_report.py results/case1/ -o raportti.pdf
  python generate_report.py results/case1/ --lang en  # English report
        """
    )
    
    parser.add_argument('results_dir', help='Tuloskansio')
    parser.add_argument('--output', '-o', help='PDF-tiedoston polku')
    parser.add_argument('--title', '-t', help='Raportin otsikko')
    parser.add_argument('--geometry', '-g', help='Geometriatiedosto (.json)')
    parser.add_argument('--lang', '-l', choices=['fi', 'en'], default='fi',
                        help='Raportin kieli: fi (suomi) tai en (englanti)')
    
    args = parser.parse_args()
    
    try:
        generate_report(
            results_dir=args.results_dir,
            output_path=args.output,
            title=args.title,
            geometry_path=args.geometry,
            lang=args.lang
        )
    except Exception as e:
        print(f"VIRHE: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
