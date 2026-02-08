#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WDR-CFD Integraatio - ISO 15927-3 mukainen viistosadeanalyysi CFD:n kanssa

Yhdistää FMI:n tuntitason sade-tuulidatan CFD-simuloinnin painekertoimiin
ja tuottaa absoluuttisen WDR-indeksin (l/m²/vuosi) jokaiselle pisteelle.

ISO 15927-3 kaava CFD:n kanssa:
    WDR_abs = (2/9) × Σ_θ [ WDR_fmi(θ) × Cp(θ) × A(θ) ]
    
    missä:
    - WDR_fmi(θ) = FMI:n viistosade suunnasta θ [l/m²/vuosi]
    - Cp(θ) = CFD:n painekerroin suunnasta θ (normalisoitu 0-1)
    - A(θ) = Altistuskerroin (cos(tuulen suunta - seinän normaali))

Käyttö:
    from wdr_cfd_integration import calculate_absolute_wdr
    
    wdr_absolute = calculate_absolute_wdr(
        cfd_results=multi_wind_results,
        wdr_data=fmi_wdr_analysis,
        output_dir=Path('results')
    )
"""

import json
import numpy as np
from pathlib import Path
from typing import Dict, Optional, Tuple
from datetime import datetime

# Importoi WDR-analyysi
try:
    from fmi_wdr_analysis import (
        analyze_city_wdr, 
        load_wdr_data, 
        save_wdr_data,
        get_exposure_class,
        WDR_EXPOSURE_CLASSES,
        DIRECTION_NAMES
    )
except ImportError:
    # Fallback jos ajetaan erikseen
    pass


def direction_to_index(direction_deg: float) -> int:
    """
    Muuntaa CFD-suunnan (0° = E, 90° = N) 16-sektorin indeksiksi.
    
    Args:
        direction_deg: CFD-suunta asteina
        
    Returns:
        Indeksi 0-15 (N, NNE, NE, ...)
    """
    # CFD -> meteorologinen: meteo = 90 - cfd
    meteo_deg = (90 - direction_deg + 360) % 360
    
    # Pyöristä lähimpään 22.5° sektoriin
    index = int((meteo_deg + 11.25) / 22.5) % 16
    return index


def index_to_direction_name(index: int) -> str:
    """Palauttaa suunnan nimen indeksistä."""
    names = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE',
             'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW']
    return names[index % 16]


def calculate_absolute_wdr(
    cfd_results: Dict[float, Dict],
    wdr_data: Dict,
    solid_mask: np.ndarray,
    output_dir: Optional[Path] = None
) -> Dict:
    """
    Laskee absoluuttisen WDR-indeksin (l/m²/vuosi) yhdistämällä
    FMI-viistosadedatan ja CFD-painekertoimet.
    
    Args:
        cfd_results: Dict[cfd_direction: simulation_results]
                     Jokainen results sisältää 'p' (Cp-kenttä), 'velocity_magnitude' jne.
        wdr_data: FMI WDR-analyysin tulos (from fmi_wdr_analysis.py)
        solid_mask: Kiinteiden esteiden maski (True = solid)
        output_dir: Hakemisto tulosten tallennukseen
        
    Returns:
        Dict sisältäen:
        - wdr_absolute: np.ndarray, WDR l/m²/vuosi jokaisessa pisteessä
        - wdr_by_direction: Dict[direction: np.ndarray]
        - max_wdr: float, maksimi WDR
        - exposure_class: str, rasitusluokka
        - statistics: Dict, tilastot
    """
    
    # Hae FMI WDR-arvot suunnittain
    fmi_wdr = wdr_data.get('wdr_by_direction', {})
    if not fmi_wdr:
        raise ValueError("FMI WDR-data puuttuu tai on tyhjä")
    
    # Hae ensimmäinen CFD-tulos referenssiksi
    first_dir = next(iter(cfd_results.keys()))
    first_result = cfd_results[first_dir]
    shape = first_result['p'].shape if 'p' in first_result else None
    
    if shape is None:
        raise ValueError("CFD-tuloksissa ei ole painekenttää (p)")
    
    # Alusta kumulatiivinen WDR-kenttä
    wdr_cumulative = np.zeros(shape)
    wdr_by_direction = {}
    
    # Käy läpi kaikki simuloidut suunnat
    for cfd_dir, results in cfd_results.items():
        # Etsi vastaava FMI WDR-suunta
        dir_index = direction_to_index(cfd_dir)
        dir_name = index_to_direction_name(dir_index)
        
        # FMI WDR tälle suunnalle [l/m²/vuosi]
        fmi_wdr_value = fmi_wdr.get(dir_name, 0)
        
        # CFD painekerroin (Cp) - käytä vain ylipainetta (Cp > 0)
        cp = results.get('p', np.zeros(shape))
        cp_positive = np.maximum(cp, 0)
        
        # Normalisoi Cp (0-1 välille, maksimi = 1)
        cp_max = np.max(cp_positive)
        if cp_max > 0:
            cp_normalized = cp_positive / cp_max
        else:
            cp_normalized = cp_positive
        
        # WDR tälle suunnalle = FMI_WDR × Cp_normalized
        # Tämä skaalaa FMI:n tasaisen arvon CFD:n painejakauman mukaan
        wdr_direction = fmi_wdr_value * cp_normalized
        
        # Merkitse solid-alueet nollaksi
        wdr_direction[solid_mask] = 0
        
        wdr_by_direction[dir_name] = wdr_direction
        wdr_cumulative += wdr_direction
    
    # Laske statistiikat (ei solid-alueita)
    valid_mask = ~solid_mask
    wdr_valid = wdr_cumulative[valid_mask]
    
    max_wdr = float(np.max(wdr_valid)) if wdr_valid.size > 0 else 0
    mean_wdr = float(np.mean(wdr_valid)) if wdr_valid.size > 0 else 0
    
    # Percentiilit
    if wdr_valid.size > 0:
        p90 = float(np.percentile(wdr_valid, 90))
        p95 = float(np.percentile(wdr_valid, 95))
        p99 = float(np.percentile(wdr_valid, 99))
    else:
        p90 = p95 = p99 = 0
    
    # Rasitusluokka maksimin perusteella
    exposure_class, class_fi, class_en = get_exposure_class(max_wdr)
    
    result = {
        'wdr_absolute': wdr_cumulative,
        'wdr_by_direction': wdr_by_direction,
        'max_wdr': max_wdr,
        'mean_wdr': mean_wdr,
        'percentile_90': p90,
        'percentile_95': p95,
        'percentile_99': p99,
        'exposure_class': exposure_class,
        'exposure_class_fi': class_fi,
        'exposure_class_en': class_en,
        'unit': 'l/m²/vuosi',
        'method': 'ISO 15927-3 + CFD',
        'fmi_source': wdr_data.get('city', 'unknown'),
        'fmi_years': wdr_data.get('years_analyzed', 0),
    }
    
    # Tallenna jos hakemisto annettu
    if output_dir:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Tallenna .npy tiedostot data-kansioon (yhtenäinen rakenne muiden kenttien kanssa)
        data_dir = output_dir / 'data'
        data_dir.mkdir(parents=True, exist_ok=True)
        
        # Tallenna WDR-kenttä
        np.save(data_dir / 'wdr_absolute.npy', wdr_cumulative)
        
        # Tallenna suuntakohtaiset kentät
        for dir_name, wdr_field in wdr_by_direction.items():
            np.save(data_dir / f'wdr_{dir_name}.npy', wdr_field)
        
        # Tallenna metadata (JSON pysyy combined-kansiossa kuten muutkin)
        # Suodata pois numpy-arrayt ja dictit jotka sisältävät numpy-arrayt
        def is_json_serializable(v):
            if isinstance(v, np.ndarray):
                return False
            if isinstance(v, dict):
                # Tarkista sisältääkö dict numpy-arrayt
                for val in v.values():
                    if isinstance(val, np.ndarray):
                        return False
            return True
        
        metadata = {k: v for k, v in result.items() if is_json_serializable(v)}
        metadata['timestamp'] = datetime.now().isoformat()
        
        with open(output_dir / 'wdr_analysis.json', 'w', encoding='utf-8') as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)
    
    return result


def calculate_building_wdr_statistics(
    wdr_field: np.ndarray,
    X: np.ndarray,
    Y: np.ndarray,
    solid_mask: np.ndarray,
    buildings: list,
    margin: float = 2.0
) -> Dict:
    """
    Laskee WDR-tilastot jokaiselle rakennukselle erikseen.
    
    Args:
        wdr_field: Absoluuttinen WDR-kenttä [l/m²/vuosi]
        X, Y: Koordinaattimatriisit
        solid_mask: Kiinteiden esteiden maski
        buildings: Lista rakennuksista
        margin: Etäisyys rakennuksen reunasta [m]
        
    Returns:
        Dict rakennusten WDR-statistiikoista
    """
    results = {}
    
    for building in buildings:
        b_id = building.get('id', 0)
        b_name = building.get('name', f'Rakennus {b_id}')
        
        # Rakennuksen rajat
        if 'vertices' in building:
            verts = np.array(building['vertices'])
            x_min, x_max = verts[:, 0].min(), verts[:, 0].max()
            y_min, y_max = verts[:, 1].min(), verts[:, 1].max()
        else:
            x_min = building.get('x_min', building.get('x', 0))
            x_max = building.get('x_max', x_min + building.get('width', 10))
            y_min = building.get('y_min', building.get('y', 0))
            y_max = building.get('y_max', y_min + building.get('height', 10))
        
        # Julkisivualue (lähellä rakennusta, ei sisällä)
        near_mask = (
            (X >= x_min - margin) & (X <= x_max + margin) &
            (Y >= y_min - margin) & (Y <= y_max + margin) &
            (~solid_mask)
        )
        
        if not near_mask.any():
            continue
        
        wdr_values = wdr_field[near_mask]
        
        # Etsi maksimikohta
        max_idx = np.argmax(wdr_field * near_mask.astype(float) - 
                          (~near_mask).astype(float) * 1e10)
        max_i, max_j = np.unravel_index(max_idx, wdr_field.shape)
        
        results[b_id] = {
            'name': b_name,
            'max_wdr': float(np.max(wdr_values)),
            'mean_wdr': float(np.mean(wdr_values)),
            'max_location': {
                'x': float(X[max_i, max_j]),
                'y': float(Y[max_i, max_j])
            },
            'exposure_class': get_exposure_class(float(np.max(wdr_values)))[0],
            'exposure_class_fi': get_exposure_class(float(np.max(wdr_values)))[1],
        }
    
    return results


def get_wdr_exposure_legend() -> Dict:
    """
    Palauttaa WDR-rasitusluokkien legendin visualisointia varten.
    
    Returns:
        Dict legendin tiedoista
    """
    return {
        'title_fi': 'Viistosateen rasitusluokat (ISO 15927-3 / BS 8104)',
        'title_en': 'Wind-Driven Rain Exposure Classes (ISO 15927-3 / BS 8104)',
        'classes': [
            {'range': '< 33', 'class': 'sheltered', 'fi': 'Suojaisa', 'en': 'Sheltered', 'color': '#2ecc71'},
            {'range': '33–56.5', 'class': 'moderate', 'fi': 'Kohtalainen', 'en': 'Moderate', 'color': '#f1c40f'},
            {'range': '56.5–100', 'class': 'severe', 'fi': 'Ankara', 'en': 'Severe', 'color': '#e67e22'},
            {'range': '> 100', 'class': 'very_severe', 'fi': 'Erittäin ankara', 'en': 'Very severe', 'color': '#e74c3c'},
        ],
        'unit': 'l/m²/vuosi',
        'note_fi': 'Vuotuinen viistosadeindeksi kuvaa julkisivuun kohdistuvaa saderasitusta.',
        'note_en': 'Annual wind-driven rain index describes rain exposure on facade.',
    }


def create_wdr_colormap():
    """
    Luo WDR-visualisointiin sopiva värikartta rasitusluokkien mukaan.
    
    Returns:
        matplotlib colormap ja normalisointi
    """
    try:
        import matplotlib.pyplot as plt
        from matplotlib.colors import LinearSegmentedColormap, BoundaryNorm
        
        # Rajat: 0, 33, 56.5, 100, 200
        boundaries = [0, 33, 56.5, 100, 200]
        
        # Värit: vihreä -> keltainen -> oranssi -> punainen
        colors = ['#2ecc71', '#f1c40f', '#e67e22', '#e74c3c']
        
        cmap = LinearSegmentedColormap.from_list('wdr_exposure', colors, N=256)
        norm = BoundaryNorm(boundaries, cmap.N, clip=True)
        
        return cmap, norm, boundaries
        
    except ImportError:
        return None, None, None


if __name__ == '__main__':
    # Testikäyttö
    print("WDR-CFD Integraatio")
    print("=" * 50)
    print("Käyttö:")
    print("  from wdr_cfd_integration import calculate_absolute_wdr")
    print()
    print("  wdr_result = calculate_absolute_wdr(")
    print("      cfd_results=multi_wind_results,")
    print("      wdr_data=fmi_wdr_analysis,")
    print("      solid_mask=solid_mask,")
    print("      output_dir=Path('results')")
    print("  )")
