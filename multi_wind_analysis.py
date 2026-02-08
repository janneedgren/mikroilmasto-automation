#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Multi-wind tulosten analyysi ja vertailu.

Analysoi usean tuulensuunnan simuloinnit ja tuottaa rakennusfysikaalisesti
relevantit kriittiset pisteet:

1. VUOTUINEN SADERASITUS (WDR) - kumulatiivinen
   - Missä julkisivu kastuu eniten vuoden aikana
   - Kaava: Σ(paino × v × Cp) kun Cp > 0
   
2. VIISTOSADERASITUS - maksimi  
   - Pahin yksittäinen saderasitustilanne
   - Kaava: max(v × Cp) kun Cp > 0
   
3. KOSTEUSRISKI (ylipaine) - maksimi Cp
   - Missä kosteus tunkeutuu rakenteisiin
   - Kaava: max(Cp)
   
4. KONVEKTIIVINEN JÄÄHTYMINEN - painotettu keskiarvo
   - Missä julkisivu jäähtyy eniten (pitkäaikaisvaikutus)
   - Kaava: Σ(paino × √k × v)

5. TUULISUUS/VIIHTYVYYS - painotettu keskiarvo
   - Tyypillinen tuulisuus jalankulkutasolla
   - Kaava: Σ(paino × v)
"""

import numpy as np
import json
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from datetime import datetime


def load_simulation_results(sim_dir: Path) -> Dict[str, np.ndarray]:
    """Lataa yhden simuloinnin tulokset."""
    results = {}
    
    # Etsi fine-hakemisto jos nested
    if (sim_dir / 'fine').exists():
        data_dir = sim_dir / 'fine'
    else:
        data_dir = sim_dir
    
    # Lataa kentät
    for field in ['velocity_magnitude', 'u', 'v', 'p', 'k', 'omega', 'nu_t', 'u_tau']:
        filepath = data_dir / f'{field}.npy'
        if filepath.exists():
            results[field] = np.load(filepath)
    
    # Koordinaatit ja maski
    for field in ['X', 'Y', 'solid_mask']:
        filepath = data_dir / f'{field}.npy'
        if filepath.exists():
            results[field] = np.load(filepath)
    
    # Domain info
    domain_path = data_dir / 'domain.json'
    if domain_path.exists():
        with open(domain_path, 'r') as f:
            results['domain'] = json.load(f)
    
    # Buildings info
    buildings_path = data_dir / 'buildings.json'
    if buildings_path.exists():
        with open(buildings_path, 'r') as f:
            results['buildings'] = json.load(f)
    
    return results


def get_building_perimeter_mask(X: np.ndarray, Y: np.ndarray, 
                                 solid_mask: np.ndarray, building: Dict,
                                 margin: float = 3.0) -> np.ndarray:
    """
    Luo maski rakennuksen reunan ympärille (julkisivualue).
    """
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
    
    # Julkisivualue = lähellä rakennusta mutta ei sisällä
    near_building = (
        (X >= x_min - margin) & (X <= x_max + margin) &
        (Y >= y_min - margin) & (Y <= y_max + margin)
    )
    
    perimeter_mask = near_building & (~solid_mask)
    
    return perimeter_mask, (x_min, x_max, y_min, y_max)


def find_critical_point(field: np.ndarray, X: np.ndarray, Y: np.ndarray,
                        mask: np.ndarray, mode: str = 'max') -> Dict:
    """Etsi kriittinen piste kentästä."""
    masked_field = field.copy()
    if mode == 'max':
        masked_field[~mask] = -np.inf
        idx = np.unravel_index(np.argmax(masked_field), masked_field.shape)
    else:
        masked_field[~mask] = np.inf
        idx = np.unravel_index(np.argmin(masked_field), masked_field.shape)
    
    return {
        'value': float(field[idx]),
        'x': float(X[idx]),
        'y': float(Y[idx]),
        'i': int(idx[0]),
        'j': int(idx[1])
    }


def analyze_building_critical_points(all_results: Dict[float, Dict], building: Dict) -> Dict:
    """Analysoi yhden rakennuksen kriittiset pisteet kaikista suunnista."""
    
    first_result = next(iter(all_results.values()))
    X = first_result.get('X')
    Y = first_result.get('Y')
    solid_mask = first_result.get('solid_mask')
    
    if X is None or Y is None or solid_mask is None:
        return {}
    
    perimeter_mask, bounds = get_building_perimeter_mask(X, Y, solid_mask, building)
    
    b_id = building.get('id', 0)
    b_name = building.get('name', f'Rakennus {b_id}')
    
    analysis = {
        'id': b_id,
        'name': b_name,
        'bounds': {'x_min': bounds[0], 'x_max': bounds[1], 'y_min': bounds[2], 'y_max': bounds[3]},
        'by_direction': {},
        'critical_points': {}
    }
    
    directions = []
    weights = []
    velocity_fields = []
    pressure_fields = []
    wdr_fields = []
    convection_fields = []
    
    for direction, results in all_results.items():
        weight = results.get('weight_normalized', results.get('weight', 0.25))
        dir_name = results.get('direction_name', f'{direction}°')
        
        directions.append(direction)
        weights.append(weight)
        
        v = results.get('velocity_magnitude', np.zeros_like(X))
        p = results.get('p', np.zeros_like(X))
        k = np.maximum(results.get('k', np.zeros_like(X)), 0)
        
        velocity_fields.append(v)
        pressure_fields.append(p)
        wdr = v * np.maximum(p, 0)
        wdr_fields.append(wdr)
        conv = np.sqrt(k) * v
        convection_fields.append(conv)
        
        analysis['by_direction'][dir_name] = {
            'direction_cfd': direction,
            'weight': results.get('weight', 0),
            'weight_normalized': weight,
            'max_velocity': float(np.max(v[perimeter_mask])) if perimeter_mask.any() else 0,
            'max_pressure': float(np.max(p[perimeter_mask])) if perimeter_mask.any() else 0,
            'max_wdr': float(np.max(wdr[perimeter_mask])) if perimeter_mask.any() else 0,
            'max_convection': float(np.max(conv[perimeter_mask])) if perimeter_mask.any() else 0
        }
    
    weights = np.array(weights)
    
    # === 1. VUOTUINEN SADERASITUS ===
    cumulative_wdr = sum(w * wdr for w, wdr in zip(weights, wdr_fields))
    wdr_point = find_critical_point(cumulative_wdr, X, Y, perimeter_mask, 'max')
    
    i, j = wdr_point['i'], wdr_point['j']
    wdr_contributions = [(w * wdr[i, j], d, all_results[d]['direction_name']) 
                         for w, wdr, d in zip(weights, wdr_fields, directions)]
    wdr_contributions.sort(reverse=True)
    
    analysis['critical_points']['annual_rain_load'] = {
        'description': 'Vuotuinen saderasitus (WDR)',
        'method': 'KUMULATIIVINEN: Σ(paino × v × Cp⁺)',
        'rationale': 'Julkisivun kokonaiskostuminen vuoden aikana.',
        'value': round(wdr_point['value'], 2),
        'unit': 'm/s (suhteellinen)',
        'x': round(wdr_point['x'], 1),
        'y': round(wdr_point['y'], 1),
        'top_contributors': [
            {'direction': name, 'contribution': round(val, 2), 
             'percent': round(val/wdr_point['value']*100, 0) if wdr_point['value'] > 0 else 0}
            for val, _, name in wdr_contributions[:3]
        ]
    }
    
    # === 2. VIISTOSADERASITUS ===
    max_wdr_per_dir = []
    for wdr, d in zip(wdr_fields, directions):
        point = find_critical_point(wdr, X, Y, perimeter_mask, 'max')
        point['direction'] = d
        point['direction_name'] = all_results[d]['direction_name']
        max_wdr_per_dir.append(point)
    
    worst_wdr = max(max_wdr_per_dir, key=lambda x: x['value'])
    
    analysis['critical_points']['driving_rain'] = {
        'description': 'Viistosaderasitus (pahin tapaus)',
        'method': 'MAKSIMI: max(v × Cp⁺)',
        'rationale': 'Suurin hetkellinen saderasitus - kriittinen liitosten tiiveyden kannalta.',
        'value': round(worst_wdr['value'], 2),
        'unit': 'm/s (suhteellinen)',
        'x': round(worst_wdr['x'], 1),
        'y': round(worst_wdr['y'], 1),
        'critical_direction': worst_wdr['direction_name'],
        'all_directions': [
            {'direction': p['direction_name'], 'value': round(p['value'], 2)}
            for p in sorted(max_wdr_per_dir, key=lambda x: -x['value'])
        ]
    }
    
    # === 3. KOSTEUSRISKI ===
    max_cp_per_dir = []
    for p, d in zip(pressure_fields, directions):
        point = find_critical_point(p, X, Y, perimeter_mask, 'max')
        point['direction'] = d
        point['direction_name'] = all_results[d]['direction_name']
        max_cp_per_dir.append(point)
    
    worst_cp = max(max_cp_per_dir, key=lambda x: x['value'])
    
    analysis['critical_points']['moisture_risk'] = {
        'description': 'Kosteusriski (ylipaine)',
        'method': 'MAKSIMI: max(Cp)',
        'rationale': 'Ylipaine työntää kosteutta rakenteisiin saumoista ja raoista.',
        'value': round(worst_cp['value'], 3),
        'unit': 'Cp [-]',
        'x': round(worst_cp['x'], 1),
        'y': round(worst_cp['y'], 1),
        'critical_direction': worst_cp['direction_name'],
        'all_directions': [
            {'direction': p['direction_name'], 'value': round(p['value'], 3)}
            for p in sorted(max_cp_per_dir, key=lambda x: -x['value'])
        ]
    }
    
    # === 4. KONVEKTIIVINEN JÄÄHTYMINEN ===
    weighted_conv = sum(w * conv for w, conv in zip(weights, convection_fields))
    conv_point = find_critical_point(weighted_conv, X, Y, perimeter_mask, 'max')
    
    i, j = conv_point['i'], conv_point['j']
    conv_contributions = [(w * conv[i, j], d, all_results[d]['direction_name']) 
                          for w, conv, d in zip(weights, convection_fields, directions)]
    conv_contributions.sort(reverse=True)
    
    analysis['critical_points']['convective_cooling'] = {
        'description': 'Konvektiivinen jäähtyminen',
        'method': 'PAINOTETTU KESKIARVO: Σ(paino × √k × v)',
        'rationale': 'Pitkäaikainen lämpöhäviö ja pintakondenssiriski.',
        'value': round(conv_point['value'], 2),
        'unit': '√(m²/s²)·m/s',
        'x': round(conv_point['x'], 1),
        'y': round(conv_point['y'], 1),
        'top_contributors': [
            {'direction': name, 'contribution': round(val, 2)}
            for val, _, name in conv_contributions[:3]
        ]
    }
    
    # === 5. TUULIALTISTUS ===
    weighted_vel = sum(w * v for w, v in zip(weights, velocity_fields))
    vel_point = find_critical_point(weighted_vel, X, Y, perimeter_mask, 'max')
    
    max_vel_per_dir = []
    for v, d in zip(velocity_fields, directions):
        point = find_critical_point(v, X, Y, perimeter_mask, 'max')
        point['direction'] = d
        point['direction_name'] = all_results[d]['direction_name']
        max_vel_per_dir.append(point)
    
    worst_vel = max(max_vel_per_dir, key=lambda x: x['value'])
    
    analysis['critical_points']['wind_exposure'] = {
        'description': 'Tuulialtistus',
        'method': 'PAINOTETTU KA (tyypillinen) + MAKSIMI (pahin)',
        'rationale': 'Keskiarvo = viihtyvyys, Maksimi = turvallisuus ja rakennerasitus.',
        'typical_value': round(vel_point['value'], 2),
        'typical_x': round(vel_point['x'], 1),
        'typical_y': round(vel_point['y'], 1),
        'max_value': round(worst_vel['value'], 2),
        'max_x': round(worst_vel['x'], 1),
        'max_y': round(worst_vel['y'], 1),
        'max_direction': worst_vel['direction_name'],
        'unit': 'm/s'
    }
    
    return analysis


def analyze_multi_wind_results(results_dir: Path, metadata: Dict) -> Dict:
    """Analysoi multi-wind tulokset."""
    
    simulations = metadata.get('simulations', [])
    sim_results = metadata.get('results', [])
    
    all_results = {}
    for sim in sim_results:
        if not sim.get('converged', False):
            continue
        
        direction = sim['direction']
        sim_dir = Path(sim['output_dir'])
        
        if sim_dir.exists():
            all_results[direction] = load_simulation_results(sim_dir)
            all_results[direction]['weight'] = sim['weight']
            all_results[direction]['direction_name'] = next(
                (s.get('direction_name', f"{direction}°") 
                 for s in simulations if s['inlet_direction'] == direction),
                f"{direction}°"
            )
    
    if not all_results:
        print("Ei onnistuneita simulointeja analysoitavaksi")
        return {}
    
    total_weight = sum(r['weight'] for r in all_results.values())
    for r in all_results.values():
        r['weight_normalized'] = r['weight'] / total_weight
    
    first_result = next(iter(all_results.values()))
    
    # Käsittele buildings-data: voi olla dict {'buildings': [...]} tai suoraan lista [...]
    buildings_data = first_result.get('buildings', [])
    if isinstance(buildings_data, dict):
        buildings = buildings_data.get('buildings', [])
    elif isinstance(buildings_data, list):
        buildings = buildings_data
    else:
        buildings = []
    
    if not buildings:
        print("Rakennuksia ei löydy tuloksista")
        return {}
    
    print(f"\nAnalysoidaan {len(all_results)} simulointia, {len(buildings)} rakennusta...")
    
    analysis = {
        'metadata': {
            'created': datetime.now().isoformat(),
            'city': metadata.get('city', 'Tuntematon'),
            'total_simulation_time': metadata.get('total_time', 0),
            'directions': [all_results[d]['direction_name'] for d in all_results.keys()],
            'direction_degrees': list(all_results.keys()),
            'weights': [all_results[d]['weight'] for d in all_results.keys()],
            'total_weight_percent': total_weight * 100
        },
        'methodology': {
            'annual_rain_load': {
                'name': 'Vuotuinen saderasitus',
                'method': 'Kumulatiivinen',
                'formula': 'Σ(paino × v × max(Cp, 0))',
                'use_case': 'Julkisivun kokonaiskostuminen, materiaalin vanheneminen'
            },
            'driving_rain': {
                'name': 'Viistosaderasitus',
                'method': 'Maksimi',
                'formula': 'max(v × max(Cp, 0))',
                'use_case': 'Saumojen ja liitosten tiiveys, hetkellinen rasitus'
            },
            'moisture_risk': {
                'name': 'Kosteusriski',
                'method': 'Maksimi',
                'formula': 'max(Cp)',
                'use_case': 'Kosteuden tunkeutuminen rakenteisiin'
            },
            'convective_cooling': {
                'name': 'Konvektiivinen jäähtyminen',
                'method': 'Painotettu keskiarvo',
                'formula': 'Σ(paino × √k × v)',
                'use_case': 'Energiankulutus, pintakondenssi'
            },
            'wind_exposure': {
                'name': 'Tuulialtistus',
                'method': 'Painotettu ka + Maksimi',
                'formula': 'Σ(paino × v) ja max(v)',
                'use_case': 'Viihtyvyys, turvallisuus'
            }
        },
        'buildings': []
    }
    
    for building in buildings:
        building_analysis = analyze_building_critical_points(all_results, building)
        if building_analysis:
            analysis['buildings'].append(building_analysis)
    
    return analysis


def create_analysis_report(analysis: Dict) -> str:
    """Luo luettava tekstiraportti."""
    
    lines = []
    
    lines.append("=" * 100)
    lines.append("MULTI-WIND ANALYYSI - RAKENNUSFYSIKAALISET KRIITTISET PISTEET")
    lines.append("=" * 100)
    
    meta = analysis.get('metadata', {})
    lines.append(f"\nKohde: {meta.get('city', 'Tuntematon')}")
    lines.append(f"Luotu: {meta.get('created', '')[:19]}")
    lines.append(f"Simulointiaika: {meta.get('total_simulation_time', 0):.0f} s")
    
    lines.append(f"\nSimuloidut tuulensuunnat:")
    for name, deg, w in zip(meta.get('directions', []), 
                            meta.get('direction_degrees', []),
                            meta.get('weights', [])):
        lines.append(f"  • {name} (CFD {deg:.0f}°) - paino {w:.1%}")
    lines.append(f"  Yhteensä: {meta.get('total_weight_percent', 0):.1f}% vuotuisesta tuulesta")
    
    lines.append("\n" + "=" * 100)
    lines.append("ANALYYSIMENETELMÄT JA PERUSTEET")
    lines.append("=" * 100)
    
    lines.append("""
┌──────────────────────────┬──────────────────────┬────────────────────────────────────────────────┐
│ KRIITTINEN SUURE         │ MENETELMÄ            │ PERUSTELU                                      │
├──────────────────────────┼──────────────────────┼────────────────────────────────────────────────┤
│ 1. Vuotuinen saderasitus │ KUMULATIIVINEN       │ Julkisivun kokonaiskostuminen vuoden aikana.   │
│    (WDR-indeksi)         │ Σ(paino × v × Cp⁺)   │ Vaikuttaa materiaalin vanhenemiseen ja homee-  │
│                          │                      │ seen. Pitkäaikainen vaurioitumisriski.         │
├──────────────────────────┼──────────────────────┼────────────────────────────────────────────────┤
│ 2. Viistosaderasitus     │ MAKSIMI              │ Pahin hetkellinen saderasitus. Kriittinen      │
│    (pahin tapaus)        │ max(v × Cp⁺)         │ saumojen, liitosten ja pellitysten kannalta.   │
│                          │                      │ Yksikin voimakas myrsky voi aiheuttaa vuodon.  │
├──────────────────────────┼──────────────────────┼────────────────────────────────────────────────┤
│ 3. Kosteusriski          │ MAKSIMI              │ Suurin ylipaine työntää kosteutta rakenteen    │
│    (ylipaine Cp)         │ max(Cp)              │ sisään saumoista ja raoista. Erityisen         │
│                          │                      │ kriittinen tuuletetuilla julkisivuilla.        │
├──────────────────────────┼──────────────────────┼────────────────────────────────────────────────┤
│ 4. Konvekt. jäähtyminen  │ PAINOTETTU KA        │ Pitkäaikainen lämpöhäviö. Turbulentti virtaus  │
│    (√k × v)              │ Σ(paino × √k × v)    │ tehostaa lämmönsiirtoa. Vaikuttaa energia-     │
│                          │                      │ kulutukseen ja pintakondenssiriskiin.          │
├──────────────────────────┼──────────────────────┼────────────────────────────────────────────────┤
│ 5. Tuulialtistus         │ PAIN. KA + MAKSIMI   │ Keskiarvo = tyypillinen viihtyvyys.            │
│    (nopeus v)            │ Σ(paino×v) & max(v)  │ Maksimi = turvallisuus ja rakennerasitus.      │
└──────────────────────────┴──────────────────────┴────────────────────────────────────────────────┘
""")
    
    lines.append("=" * 100)
    lines.append("RAKENNUSKOHTAISET KRIITTISET PISTEET")
    lines.append("=" * 100)
    
    for building in analysis.get('buildings', []):
        b_id = building.get('id', 0)
        b_name = building.get('name', f'Rakennus {b_id}')
        
        lines.append(f"\n{'━' * 100}")
        lines.append(f"RAKENNUS #{b_id}: {b_name}")
        lines.append(f"{'━' * 100}")
        
        cps = building.get('critical_points', {})
        
        if 'annual_rain_load' in cps:
            cp = cps['annual_rain_load']
            lines.append(f"\n  📍 1. VUOTUINEN SADERASITUS")
            lines.append(f"     Sijainti: ({cp['x']:.1f}, {cp['y']:.1f}) m")
            lines.append(f"     Arvo: {cp['value']:.2f} {cp['unit']}")
            lines.append(f"     Menetelmä: {cp['method']}")
            if 'top_contributors' in cp:
                lines.append(f"     Kontribuutiot:")
                for c in cp['top_contributors']:
                    lines.append(f"       - {c['direction']}: {c['contribution']:.2f} ({c['percent']:.0f}%)")
        
        if 'driving_rain' in cps:
            cp = cps['driving_rain']
            lines.append(f"\n  📍 2. VIISTOSADERASITUS (pahin)")
            lines.append(f"     Sijainti: ({cp['x']:.1f}, {cp['y']:.1f}) m")
            lines.append(f"     Arvo: {cp['value']:.2f} {cp['unit']}")
            lines.append(f"     Kriittinen suunta: {cp['critical_direction']}")
            if 'all_directions' in cp:
                lines.append(f"     Kaikki suunnat:")
                for d in cp['all_directions']:
                    marker = " ◄" if d['direction'] == cp['critical_direction'] else ""
                    lines.append(f"       - {d['direction']}: {d['value']:.2f}{marker}")
        
        if 'moisture_risk' in cps:
            cp = cps['moisture_risk']
            lines.append(f"\n  📍 3. KOSTEUSRISKI (ylipaine)")
            lines.append(f"     Sijainti: ({cp['x']:.1f}, {cp['y']:.1f}) m")
            lines.append(f"     Arvo: Cp = {cp['value']:.3f}")
            lines.append(f"     Kriittinen suunta: {cp['critical_direction']}")
            if 'all_directions' in cp:
                lines.append(f"     Kaikki suunnat:")
                for d in cp['all_directions']:
                    marker = " ◄" if d['direction'] == cp['critical_direction'] else ""
                    lines.append(f"       - {d['direction']}: Cp = {d['value']:.3f}{marker}")
        
        if 'convective_cooling' in cps:
            cp = cps['convective_cooling']
            lines.append(f"\n  📍 4. KONVEKTIIVINEN JÄÄHTYMINEN")
            lines.append(f"     Sijainti: ({cp['x']:.1f}, {cp['y']:.1f}) m")
            lines.append(f"     Arvo: {cp['value']:.2f} {cp['unit']}")
            lines.append(f"     Menetelmä: {cp['method']}")
            if 'top_contributors' in cp:
                lines.append(f"     Kontribuutiot:")
                for c in cp['top_contributors']:
                    lines.append(f"       - {c['direction']}: {c['contribution']:.2f}")
        
        if 'wind_exposure' in cps:
            cp = cps['wind_exposure']
            lines.append(f"\n  📍 5. TUULIALTISTUS")
            lines.append(f"     Tyypillinen: {cp['typical_value']:.2f} {cp['unit']} @ ({cp['typical_x']:.1f}, {cp['typical_y']:.1f})")
            lines.append(f"     Maksimi:     {cp['max_value']:.2f} {cp['unit']} @ ({cp['max_x']:.1f}, {cp['max_y']:.1f}) [{cp['max_direction']}]")
        
        by_dir = building.get('by_direction', {})
        if by_dir:
            lines.append(f"\n  Yhteenveto suunnittain:")
            lines.append(f"  {'Suunta':<12} {'Paino':>8} {'v_max':>10} {'Cp_max':>10} {'WDR':>10} {'Conv':>10}")
            lines.append(f"  {'-'*62}")
            for dir_name, data in by_dir.items():
                lines.append(f"  {dir_name:<12} {data['weight_normalized']:>7.1%} "
                           f"{data['max_velocity']:>9.2f} {data['max_pressure']:>9.3f} "
                           f"{data['max_wdr']:>9.2f} {data['max_convection']:>9.2f}")
    
    lines.append("\n" + "=" * 100)
    lines.append("SUOSITUKSET")
    lines.append("=" * 100)
    
    lines.append("""
JULKISIVUSUUNNITTELU:
  • Tarkista saumat ja liitokset kohdissa joissa viistosaderasitus on suurin
  • Varmista riittävä limityspituus pellityksissä kosteusriskialueilla
  • Harkitse lisätiivistystä ylipainealueille (Cp > 0.5)

ENERGIATEHOKKUUS:
  • Tehosta lämmöneristystä konvektiivisen jäähtymisen kriittisissä pisteissä
  • Tarkista ikkunoiden ja ovien tiiveys tuulialtistuksen maksimikohdissa

HUOLTO JA YLLÄPITO:
  • Priorisoi tarkastukset vuotuisen saderasituksen suurimpiin pisteisiin
  • Seuraa erityisesti kosteusriskialueiden kuntoa
""")
    
    return "\n".join(lines)


def save_analysis_results(analysis: Dict, output_dir: Path):
    """Tallenna analyysin tulokset."""
    
    output_dir.mkdir(parents=True, exist_ok=True)
    
    with open(output_dir / 'multi_wind_analysis.json', 'w', encoding='utf-8') as f:
        json.dump(analysis, f, ensure_ascii=False, indent=2)
    
    report = create_analysis_report(analysis)
    with open(output_dir / 'multi_wind_analysis.txt', 'w', encoding='utf-8') as f:
        f.write(report)
    
    print(report)
    print(f"\n{'='*60}")
    print(f"Tulokset tallennettu:")
    print(f"  {output_dir / 'multi_wind_analysis.json'}")
    print(f"  {output_dir / 'multi_wind_analysis.txt'}")


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Analysoi multi-wind tulokset')
    parser.add_argument('results_dir', help='Multi-wind tuloshakemisto')
    
    args = parser.parse_args()
    
    results_dir = Path(args.results_dir)
    
    metadata_path = results_dir / 'multi_wind_metadata.json'
    if not metadata_path.exists():
        print(f"VIRHE: {metadata_path} ei löydy")
        exit(1)
    
    with open(metadata_path, 'r', encoding='utf-8') as f:
        metadata = json.load(f)
    
    analysis = analyze_multi_wind_results(results_dir, metadata)
    
    combined_dir = results_dir / 'combined'
    save_analysis_results(analysis, combined_dir)
