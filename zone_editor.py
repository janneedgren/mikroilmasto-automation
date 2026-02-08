#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Geometrian alueeditori - tunnistaa ja muokkaa rakennusten välisiä alueita.

Ominaisuudet:
- Hakee tiet OSM:stä
- Tunnistaa rakennusten ja teiden väliset "välialueet"
- Luo HTML-pohjaisen interaktiivisen editorin
- Tallentaa muokatun geometrian JSON-tiedostoon

Käyttö:
    # Luo editori olemassaolevalle geometrialle
    python zone_editor.py geometry.json --output editor.html
    
    # Hae tiet ja luo välialueet
    python zone_editor.py geometry.json --fetch-roads --output editor.html
    
    # Tallenna muokattu geometria (editorista exportattu JSON)
    python zone_editor.py geometry.json --apply-edits edits.json --output updated.json
"""

import argparse
import json
import sys
from pathlib import Path
from typing import List, Dict, Tuple, Optional, Any
import numpy as np


# ============================================================================
# POLYGONIEN KULMIEN PYÖRISTYS
# ============================================================================

def smooth_polygon_corners(vertices: List[Tuple[float, float]], 
                           radius: float = 5.0,
                           angle_threshold: float = 120.0,
                           points_per_corner: int = 4) -> List[Tuple[float, float]]:
    """
    Pyöristää polygonin terävät kulmat.
    
    Käyttää Chaikin-tyyppistä lähestymistapaa: terävissä kulmissa
    lisätään kaareva segmentti kulmapisteen sijaan.
    
    Args:
        vertices: Alkuperäiset polygonin kulmat [(x1,y1), (x2,y2), ...]
        radius: Pyöristyssäde metreinä (oletus 5m)
        angle_threshold: Kulmakynnys asteina - alle tämän pyöristetään (oletus 120°)
        points_per_corner: Pisteiden määrä pyöristetyssä kulmassa
        
    Returns:
        Uudet kulmat pyöristyksellä
        
    Note:
        - Pyöristys tehdään vain kulmille joiden sisäkulma < angle_threshold
        - Säde rajoitetaan automaattisesti ettei ylitä sivun pituutta
        - Hyvin pienet polygonit (<3 kulmaa) palautetaan sellaisenaan
    """
    if len(vertices) < 3:
        return vertices
    
    n = len(vertices)
    smoothed = []
    
    for i in range(n):
        # Edellinen, nykyinen ja seuraava piste
        p_prev = np.array(vertices[(i - 1) % n])
        p_curr = np.array(vertices[i])
        p_next = np.array(vertices[(i + 1) % n])
        
        # Vektorit edelliseen ja seuraavaan
        v1 = p_prev - p_curr
        v2 = p_next - p_curr
        
        len1 = np.linalg.norm(v1)
        len2 = np.linalg.norm(v2)
        
        # Jos sivut liian lyhyitä, ohita pyöristys
        if len1 < 1e-6 or len2 < 1e-6:
            smoothed.append(tuple(p_curr))
            continue
        
        # Normalisoidut suuntavektorit
        v1_norm = v1 / len1
        v2_norm = v2 / len2
        
        # Laske kulma vektoreiden välillä (sisäkulma)
        dot = np.clip(np.dot(v1_norm, v2_norm), -1.0, 1.0)
        angle_rad = np.arccos(dot)
        angle_deg = np.degrees(angle_rad)
        
        # Pyöristä vain terävät kulmat (sisäkulma < threshold)
        if angle_deg < angle_threshold:
            # Rajoita säde sivujen pituuden mukaan (max 40% lyhyemmästä sivusta)
            max_radius = 0.4 * min(len1, len2)
            actual_radius = min(radius, max_radius)
            
            if actual_radius < 0.5:  # Liian pieni säde, ohita
                smoothed.append(tuple(p_curr))
                continue
            
            # Laske pisteet pyöristettyyn kulmaan
            # Aloituspiste: actual_radius matkan päässä kulmasta kohti edellistä
            start_point = p_curr + v1_norm * actual_radius
            # Lopetuspiste: actual_radius matkan päässä kulmasta kohti seuraavaa
            end_point = p_curr + v2_norm * actual_radius
            
            # Luo kaari aloitus- ja lopetuspisteen välille
            # Käytetään yksinkertaista lineaarista interpolaatiota kaarelle
            for j in range(points_per_corner + 1):
                t = j / points_per_corner
                # Bezier-tyyppinen interpolaatio (quadratic)
                # Kontrollipiste on alkuperäinen kulmapiste
                point = (1 - t)**2 * start_point + 2 * (1 - t) * t * p_curr + t**2 * end_point
                smoothed.append(tuple(point))
        else:
            # Tylppä kulma, säilytä alkuperäinen
            smoothed.append(tuple(p_curr))
    
    return smoothed


def _smooth_and_format_vertices(vertices: List) -> List[List[float]]:
    """
    Pyöristää polygonin kulmat ja formatoi vertices listaksi.
    
    Args:
        vertices: Lista koordinaatteja [(x,y), ...] tai [[x,y], ...]
        
    Returns:
        Pyöristetyt vertices muodossa [[x, y], ...]
    """
    # Muunna tupleiksi jos lista
    if len(vertices) < 3:
        return [[round(v[0], 1), round(v[1], 1)] for v in vertices]
    
    vertices_tuples = [(float(v[0]), float(v[1])) for v in vertices]
    
    # Pyöristä kulmat
    smoothed = smooth_polygon_corners(
        vertices_tuples,
        radius=3.0,            # 3m pyöristyssäde
        angle_threshold=100.0,  # Pyöristä alle 100° kulmat
        points_per_corner=3     # 3 pistettä per pyöristys
    )
    
    # Formatoi ja palauta
    return [[round(v[0], 1), round(v[1], 1)] for v in smoothed]


# Vakiot - LAI-pohjaiset aluetyypit
# LAI = Leaf Area Index, porosity lasketaan: exp(-LAI * 0.5)
# Arvot kesätilanteelle (talvelle omat kertoimet)

ZONE_TYPES = {
    # === EI KASVILLISUUTTA ===
    'unknown': {'color': '#cccccc', 'name': 'Tuntematon', 'LAI': None, 'LAI_winter': None, 'height': 0, 'category': 'Muu'},
    'paved': {'color': '#696969', 'name': 'Päällystetty', 'LAI': None, 'LAI_winter': None, 'height': 0, 'category': 'Muu'},
    'parking': {'color': '#808080', 'name': 'Pysäköinti', 'LAI': None, 'LAI_winter': None, 'height': 0, 'category': 'Muu'},
    'water': {'color': '#4169E1', 'name': 'Vesi', 'LAI': None, 'LAI_winter': None, 'height': 0, 'category': 'Vesi'},
    'lake': {'color': '#4682B4', 'name': 'Järvi', 'LAI': None, 'LAI_winter': None, 'height': 0, 'category': 'Vesi'},
    'pond': {'color': '#87CEEB', 'name': 'Lampi', 'LAI': None, 'LAI_winter': None, 'height': 0, 'category': 'Vesi'},
    'river': {'color': '#1E90FF', 'name': 'Joki', 'LAI': None, 'LAI_winter': None, 'height': 0, 'category': 'Vesi'},
    'reservoir': {'color': '#5F9EA0', 'name': 'Tekoallas', 'LAI': None, 'LAI_winter': None, 'height': 0, 'category': 'Vesi'},
    'bare_soil': {'color': '#8B7355', 'name': 'Paljas maa', 'LAI': 0, 'LAI_winter': 0, 'height': 0, 'category': 'Muu'},
    
    # === METSÄT (FMI 10m korjatut LAI_2D arvot) ===
    # Korjaus: korkea kasvillisuus (h≥10m) → LAI_2D = LAI_3D × ylikierto_kerroin
    'forest_spruce': {'color': '#0B3B0B', 'name': 'Kuusikko (tiheä)', 'LAI': 2.34, 'LAI_winter': 2.05, 'height': 22, 'category': 'Metsä'},
    'forest_pine': {'color': '#1C5E1C', 'name': 'Mäntymetsä', 'LAI': 1.76, 'LAI_winter': 1.60, 'height': 18, 'category': 'Metsä'},
    'forest_conifer': {'color': '#145214', 'name': 'Havumetsä (seka)', 'LAI': 1.92, 'LAI_winter': 1.76, 'height': 18, 'category': 'Metsä'},
    'forest_deciduous': {'color': '#228B22', 'name': 'Lehtimetsä', 'LAI': 1.93, 'LAI_winter': 0.18, 'height': 15, 'category': 'Metsä'},
    'forest_mixed': {'color': '#2E8B2E', 'name': 'Sekametsä', 'LAI': 1.75, 'LAI_winter': 1.05, 'height': 15, 'category': 'Metsä'},
    'forest_sparse': {'color': '#4A7C4A', 'name': 'Harva metsä', 'LAI': 1.35, 'LAI_winter': 0.68, 'height': 10, 'category': 'Metsä'},
    'forest_young': {'color': '#5C9E5C', 'name': 'Taimikko', 'LAI': 1.20, 'LAI_winter': 0.20, 'height': 4, 'category': 'Metsä'},
    'forest_park': {'color': '#3D8B3D', 'name': 'Puistometsä', 'LAI': 1.43, 'LAI_winter': 0.41, 'height': 12, 'category': 'Metsä'},
    'forest_natural': {'color': '#0D4D0D', 'name': 'Luonnonmetsä', 'LAI': 1.96, 'LAI_winter': 0.98, 'height': 25, 'category': 'Metsä'},
    
    # === PUISTOT JA VIHERALUEET (FMI 10m korjatut LAI_2D arvot) ===
    # Korjaus: matala kasvillisuus (h<10m) → LAI_2D = LAI_3D × (h / 10m)
    'park': {'color': '#6DBE6D', 'name': 'Puisto (oletus)', 'LAI': 1.58, 'LAI_winter': 0.48, 'height': 10, 'category': 'Puisto'},
    'park_lawn': {'color': '#90EE90', 'name': 'Puisto (nurmikko)', 'LAI': 0.03, 'LAI_winter': 0.02, 'height': 0.1, 'category': 'Puisto'},
    'park_sparse': {'color': '#7CCD7C', 'name': 'Puisto (harvat puut)', 'LAI': 1.13, 'LAI_winter': 0.36, 'height': 10, 'category': 'Puisto'},
    'park_dense': {'color': '#548B54', 'name': 'Puisto (tiheä)', 'LAI': 1.84, 'LAI_winter': 0.61, 'height': 12, 'category': 'Puisto'},
    'playground': {'color': '#8FBC8F', 'name': 'Leikkipuisto', 'LAI': 0.60, 'LAI_winter': 0.30, 'height': 3, 'category': 'Puisto'},
    'cemetery': {'color': '#6B8E6B', 'name': 'Hautausmaa', 'LAI': 1.43, 'LAI_winter': 0.61, 'height': 12, 'category': 'Puisto'},
    'golf_green': {'color': '#00FF7F', 'name': 'Golfviheriö', 'LAI': 0.01, 'LAI_winter': 0.01, 'height': 0.01, 'category': 'Puisto'},
    'golf_fairway': {'color': '#7CFC00', 'name': 'Golfväylä', 'LAI': 0.01, 'LAI_winter': 0.01, 'height': 0.05, 'category': 'Puisto'},
    'golf_rough': {'color': '#9ACD32', 'name': 'Golfrough', 'LAI': 0.04, 'LAI_winter': 0.02, 'height': 0.2, 'category': 'Puisto'},
    
    # === PELLOT JA MAATALOUS (FMI 10m korjatut LAI_2D arvot) ===
    'field_grain': {'color': '#DAA520', 'name': 'Viljakasvusto', 'LAI': 0.36, 'LAI_winter': 0, 'height': 0.8, 'category': 'Pelto'},
    'field_stubble': {'color': '#D2B48C', 'name': 'Sänkipelto', 'LAI': 0.01, 'LAI_winter': 0.01, 'height': 0.15, 'category': 'Pelto'},
    'field_plowed': {'color': '#8B4513', 'name': 'Kynnetty pelto', 'LAI': 0, 'LAI_winter': 0, 'height': 0, 'category': 'Pelto'},
    'field_grass': {'color': '#7CFC00', 'name': 'Nurmirehupelto', 'LAI': 0.16, 'LAI_winter': 0.04, 'height': 0.4, 'category': 'Pelto'},
    'pasture': {'color': '#9ACD32', 'name': 'Laidun', 'LAI': 0.05, 'LAI_winter': 0.02, 'height': 0.2, 'category': 'Pelto'},
    'field_potato': {'color': '#556B2F', 'name': 'Peruna/juurekset', 'LAI': 0.14, 'LAI_winter': 0, 'height': 0.4, 'category': 'Pelto'},
    'field_rapeseed': {'color': '#FFD700', 'name': 'Rapsi', 'LAI': 0.54, 'LAI_winter': 0, 'height': 1.2, 'category': 'Pelto'},
    
    # === PENSAAT JA MATALA KASVILLISUUS (FMI 10m korjatut LAI_2D arvot) ===
    'hedge_deciduous': {'color': '#006400', 'name': 'Pensasaita (lehti)', 'LAI': 0.90, 'LAI_winter': 0.16, 'height': 2.0, 'category': 'Pensas'},
    'hedge_conifer': {'color': '#004200', 'name': 'Pensasaita (havu)', 'LAI': 1.38, 'LAI_winter': 1.38, 'height': 2.5, 'category': 'Pensas'},
    'shrub_berry': {'color': '#8B0000', 'name': 'Marjapensaat', 'LAI': 0.42, 'LAI_winter': 0.06, 'height': 1.2, 'category': 'Pensas'},
    'shrub_natural': {'color': '#4A6741', 'name': 'Luonnonpensaikko', 'LAI': 1.20, 'LAI_winter': 0.30, 'height': 3, 'category': 'Pensas'},
    'juniper': {'color': '#3B5323', 'name': 'Kataja-alue', 'LAI': 0.70, 'LAI_winter': 0.70, 'height': 2, 'category': 'Pensas'},
    'meadow_natural': {'color': '#BDB76B', 'name': 'Luonnon niitty', 'LAI': 0.15, 'LAI_winter': 0.03, 'height': 0.5, 'category': 'Pensas'},
    'meadow_maintained': {'color': '#C5D86D', 'name': 'Hoidettu niitty', 'LAI': 0.07, 'LAI_winter': 0.02, 'height': 0.3, 'category': 'Pensas'},
    
    # === KOSTEIKOT (FMI 10m korjatut LAI_2D arvot) ===
    'wetland_reed': {'color': '#4682B4', 'name': 'Ruovikko', 'LAI': 1.25, 'LAI_winter': 0.50, 'height': 2.5, 'category': 'Kosteikko'},
    'wetland_horsetail': {'color': '#5F9EA0', 'name': 'Kortteikko', 'LAI': 0.25, 'LAI_winter': 0.07, 'height': 0.7, 'category': 'Kosteikko'},
    'bog_open': {'color': '#8FBC8F', 'name': 'Avosuo', 'LAI': 0.06, 'LAI_winter': 0.02, 'height': 0.3, 'category': 'Kosteikko'},
    'bog_forest': {'color': '#2F4F4F', 'name': 'Räme/korpi', 'LAI': 1.80, 'LAI_winter': 1.13, 'height': 10, 'category': 'Kosteikko'},
    'shore_vegetation': {'color': '#3CB371', 'name': 'Rantakasvillisuus', 'LAI': 0.60, 'LAI_winter': 0.15, 'height': 1.5, 'category': 'Kosteikko'},
    
    # === RAKENNETTU YMPÄRISTÖ (FMI 10m korjatut LAI_2D arvot) ===
    'street_trees': {'color': '#6B8E23', 'name': 'Katupuurivi', 'LAI': 1.13, 'LAI_winter': 0.23, 'height': 10, 'category': 'Rakennettu'},
    'yard_lawn': {'color': '#98FB98', 'name': 'Piha (nurmikko)', 'LAI': 0.02, 'LAI_winter': 0.01, 'height': 0.08, 'category': 'Rakennettu'},
    'yard_mixed': {'color': '#7FBF7F', 'name': 'Piha (pensaat+nurmi)', 'LAI': 0.42, 'LAI_winter': 0.18, 'height': 1.2, 'category': 'Rakennettu'},
    'green_roof_sedum': {'color': '#9DC183', 'name': 'Viherkatto (sedum)', 'LAI': 0.03, 'LAI_winter': 0.02, 'height': 0.1, 'category': 'Rakennettu'},
    'green_roof_grass': {'color': '#90EE90', 'name': 'Viherkatto (nurmi)', 'LAI': 0.05, 'LAI_winter': 0.03, 'height': 0.15, 'category': 'Rakennettu'},
}

def lai_to_porosity(lai: float, k: float = 0.6) -> float:
    """Muuntaa LAI huokoisuudeksi: porosity = exp(-LAI * k)"""
    if lai is None or lai <= 0:
        return None
    import math
    return math.exp(-lai * k)


def load_geometry(filepath: str) -> Dict:
    """Lataa geometriatiedosto."""
    import re
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    content = re.sub(r'\bNaN\b', 'null', content)
    return json.loads(content)


def save_geometry(data: Dict, filepath: str):
    """Tallentaa geometriatiedoston."""
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"Tallennettu: {filepath}")


def fetch_roads_from_osm(lat: float, lon: float, radius: float) -> List[Dict]:
    """
    Hakee tiet OpenStreetMapista.
    
    Returns:
        Lista teistä: [{'id': 'R1', 'name': 'Tuohitie', 'vertices': [...], 'width': 6.0}, ...]
    """
    try:
        import osmnx as ox
        import geopandas as gpd
        from shapely.geometry import LineString, Polygon
        from shapely.ops import transform
        import pyproj
    except ImportError:
        print("VIRHE: Asenna kirjastot: pip install osmnx geopandas shapely pyproj")
        return []
    
    print(f"  Haetaan teitä OSM:stä ({lat:.4f}, {lon:.4f}, r={radius}m)...")
    
    # Hae tiet
    road_tags = {
        'highway': ['residential', 'service', 'unclassified', 'tertiary', 
                    'secondary', 'primary', 'living_street', 'pedestrian',
                    'footway', 'cycleway', 'path', 'track']
    }
    
    try:
        roads_gdf = ox.features_from_point((lat, lon), tags=road_tags, dist=radius)
    except Exception as e:
        print(f"  Teiden haku epäonnistui: {e}")
        return []
    
    if len(roads_gdf) == 0:
        print("  Ei teitä alueella")
        return []
    
    # Koordinaattimuunnos
    wgs84 = pyproj.CRS('EPSG:4326')
    utm = pyproj.CRS(f'EPSG:326{int((lon + 180) / 6) + 1}')
    transformer = pyproj.Transformer.from_crs(wgs84, utm, always_xy=True)
    
    # Keskipisteen UTM-koordinaatit
    center_e, center_n = transformer.transform(lon, lat)
    
    roads = []
    road_widths = {
        'primary': 10.0, 'secondary': 8.0, 'tertiary': 7.0,
        'residential': 6.0, 'service': 4.0, 'living_street': 5.0,
        'unclassified': 5.0, 'pedestrian': 3.0, 'footway': 2.0,
        'cycleway': 2.5, 'path': 1.5, 'track': 3.0
    }
    
    for idx, (osm_id, row) in enumerate(roads_gdf.iterrows()):
        geom = row.geometry
        if geom is None or geom.is_empty:
            continue
        
        # Hae tien tyyppi ja nimi
        highway_type = row.get('highway', 'residential')
        if isinstance(highway_type, list):
            highway_type = highway_type[0]
        name = row.get('name', '')
        if isinstance(name, list):
            name = name[0] if name else ''
        
        width = road_widths.get(highway_type, 5.0)
        
        # Muunna viiva polygoniksi (buffer)
        if geom.geom_type == 'LineString':
            # Muunna UTM:ään
            coords_utm = [transformer.transform(x, y) for x, y in geom.coords]
            # Muunna paikallisiksi (keskipiste = origo)
            coords_local = [(x - center_e, y - center_n) for x, y in coords_utm]
            
            # Luo bufferoitu polygoni
            line_local = LineString(coords_local)
            buffered = line_local.buffer(width / 2, cap_style=2)  # Flat cap
            
            if buffered.is_empty:
                continue
            
            # Hae polygonin koordinaatit
            if buffered.geom_type == 'Polygon':
                vertices = list(buffered.exterior.coords)[:-1]  # Poista viimeinen (sama kuin ensimmäinen)
            else:
                continue
            
            roads.append({
                'id': f'R{idx + 1}',
                'type': 'road',
                'name': name or f'Tie {idx + 1}',
                'highway_type': highway_type,
                'width': width,
                'vertices': [[round(v[0], 2), round(v[1], 2)] for v in vertices],
                'is_solid': False  # Tiet eivät ole kiinteitä esteitä
            })
    
    print(f"  Löytyi {len(roads)} tietä")
    return roads


def identify_zones(
    geometry: Dict,
    resolution: float = 1.0,
    min_zone_area: float = 25.0
) -> List[Dict]:
    """
    Tunnistaa tonttikohtaiset alueet Voronoi-tyylisellä jaolla.
    
    Algoritmi:
    1. Merkitse rakennukset, tiet ja kasvillisuus maskiin
    2. Käytä watershed-jakoa: jokainen rakennus "omistaa" lähimmän alueen
    3. Tiet ja kasvillisuus toimivat rajoina jotka erottavat tontit
    4. Boundary tracing luo tarkat polygonit ilman päällekkäisyyksiä
    
    Args:
        geometry: Geometriadata
        resolution: Hilan resoluutio m/pikseli (oletus: 1.0, pienempi=tarkempi)
        min_zone_area: Minimialue m² (pienempiä ei huomioida)
    
    Returns:
        Lista tunnistetuista alueista (yksi per tontti)
    """
    from scipy import ndimage
    
    width = geometry['domain']['width']
    height = geometry['domain']['height']
    
    # Luo hilat
    nx = int(width / resolution)
    ny = int(height / resolution)
    
    # Maski: True = este (rakennus tai tie)
    obstacle_mask = np.zeros((ny, nx), dtype=bool)  # Vain rakennukset
    road_mask = np.zeros((ny, nx), dtype=bool)
    vegetation_mask = np.zeros((ny, nx), dtype=bool)  # Kasvillisuus/vesi - poistetaan lopussa
    
    # Rakennusten keskipisteet ja ID:t watershed-siemeniä varten
    building_seeds = []  # [(y, x, building_id), ...]
    building_id = 0  # Kasvaa kun rakennus löytyy
    
    # Merkitse rakennukset JA kasvillisuusalueet JA vesialueet
    for obs in geometry.get('obstacles', []):
        obs_type = obs.get('type', 'building')
        
        # Kasvillisuusalueet ja vesialueet - merkitään omaan maskiin
        # HUOM: Nämä EI estä tonttien muodostumista, vaan poistetaan vain lopputuloksesta
        if obs_type in ['tree_zone', 'vegetation_zone', 'water_zone']:
            if 'vertices' in obs:
                vertices = np.array(obs['vertices'])
                _fill_polygon(vegetation_mask, vertices, resolution)
            continue
        
        # Ohita yksittäiset puut (liian pieniä)
        if obs_type == 'tree':
            continue
        
        # Kasvatetaan ID:tä kun rakennus löytyy
        building_id += 1
        
        if 'vertices' in obs:
            vertices = np.array(obs['vertices'])
            _fill_polygon(obstacle_mask, vertices, resolution)
            
            # Laske keskipiste siementä varten
            cx = vertices[:, 0].mean() / resolution
            cy = vertices[:, 1].mean() / resolution
            cx = int(np.clip(cx, 0, nx - 1))
            cy = int(np.clip(cy, 0, ny - 1))
            building_seeds.append((cy, cx, building_id))
            
        elif 'x_min' in obs:
            x_min = int(obs['x_min'] / resolution)
            x_max = int(obs['x_max'] / resolution)
            y_min = int(obs['y_min'] / resolution)
            y_max = int(obs['y_max'] / resolution)
            obstacle_mask[max(0, y_min):min(ny, y_max), max(0, x_min):min(nx, x_max)] = True
            
            cx = (x_min + x_max) // 2
            cy = (y_min + y_max) // 2
            cx = int(np.clip(cx, 0, nx - 1))
            cy = int(np.clip(cy, 0, ny - 1))
            building_seeds.append((cy, cx, building_id))
        
        elif 'x_center' in obs and 'y_center' in obs:
            # Rotated building - luo suorakulmio ja pyöritä
            x_c = obs['x_center']
            y_c = obs['y_center']
            w = obs.get('width', 10)
            h = obs.get('height', 10)
            angle = obs.get('angle', 0)
            
            # Luo kulmat
            cos_a = np.cos(np.radians(angle))
            sin_a = np.sin(np.radians(angle))
            hw, hh = w / 2, h / 2
            
            corners = [
                (-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)
            ]
            
            vertices = []
            for dx, dy in corners:
                rx = dx * cos_a - dy * sin_a + x_c
                ry = dx * sin_a + dy * cos_a + y_c
                vertices.append([rx, ry])
            
            vertices = np.array(vertices)
            _fill_polygon(obstacle_mask, vertices, resolution)
            
            cx = int(np.clip(x_c / resolution, 0, nx - 1))
            cy = int(np.clip(y_c / resolution, 0, ny - 1))
            building_seeds.append((cy, cx, building_id))
    
    # Merkitse tiet (nämä toimivat rajoina)
    for road in geometry.get('roads', []):
        if 'vertices' in road:
            vertices = np.array(road['vertices'])
            _fill_polygon(road_mask, vertices, resolution)
    
    # Esteet Voronoi-laskennassa: VAIN rakennukset ja tiet
    # Kasvillisuus/vesi EI estä tonttien muodostumista!
    all_obstacles_for_voronoi = obstacle_mask | road_mask
    
    # Merkitse reunat esteiksi
    border = 2
    all_obstacles_for_voronoi[:border, :] = True
    all_obstacles_for_voronoi[-border:, :] = True
    all_obstacles_for_voronoi[:, :border] = True
    all_obstacles_for_voronoi[:, -border:] = True
    
    print(f"  Rakennuksia: {len(building_seeds)}, Tiet: {road_mask.sum()} pikseliä, Kasvillisuus/vesi: {vegetation_mask.sum()} pikseliä")
    
    if len(building_seeds) == 0:
        print("  Ei rakennuksia - ei voida luoda tontteja")
        return []
    
    # === VORONOI/WATERSHED JAKO ===
    # Luo siemenmaski: jokainen rakennus saa oman ID:n
    seed_mask = np.zeros((ny, nx), dtype=np.int32)
    
    # Laajenna rakennukset hieman siemeniksi (jotta watershed lähtee rakennuksen sisältä)
    building_id_counter = 0
    for obs in geometry.get('obstacles', []):
        obs_type = obs.get('type', 'building')
        if obs_type in ['tree', 'tree_zone', 'vegetation_zone', 'water_zone']:
            continue
        
        building_id_counter += 1
        
        temp_mask = np.zeros((ny, nx), dtype=bool)
        if 'vertices' in obs:
            vertices = np.array(obs['vertices'])
            _fill_polygon(temp_mask, vertices, resolution)
        elif 'x_min' in obs:
            x_min = int(obs['x_min'] / resolution)
            x_max = int(obs['x_max'] / resolution)
            y_min = int(obs['y_min'] / resolution)
            y_max = int(obs['y_max'] / resolution)
            temp_mask[max(0, y_min):min(ny, y_max), max(0, x_min):min(nx, x_max)] = True
        elif 'x_center' in obs and 'y_center' in obs:
            # Rotated building
            x_c = obs['x_center']
            y_c = obs['y_center']
            w = obs.get('width', 10)
            h = obs.get('height', 10)
            angle = obs.get('angle', 0)
            
            cos_a = np.cos(np.radians(angle))
            sin_a = np.sin(np.radians(angle))
            hw, hh = w / 2, h / 2
            
            corners = [(-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)]
            vertices = []
            for dx, dy in corners:
                rx = dx * cos_a - dy * sin_a + x_c
                ry = dx * sin_a + dy * cos_a + y_c
                vertices.append([rx, ry])
            
            vertices = np.array(vertices)
            _fill_polygon(temp_mask, vertices, resolution)
        
        # Merkitse tämän rakennuksen alue omalla ID:llä
        if temp_mask.any():
            seed_mask[temp_mask] = building_id_counter
    
    # Laske etäisyys lähimpään esteeseen (rakennukseen)
    # Käytetään tätä watershed-painotukseen
    distance = ndimage.distance_transform_edt(~obstacle_mask)
    
    # Tiet toimivat "vedenjakajina" - aseta niille korkea "pato"
    # Tämä estää alueiden yhdistymisen tien yli
    distance[road_mask] = 0
    
    # Watershed-jako käyttäen etäisyysmuunnosta
    # Käytämme yksinkertaistettua versiota: laajenna siemeniä iteratiivisesti
    # kunnes ne kohtaavat (raja = puoliväli) tai törmäävät tiehen
    
    zone_labels = _watershed_from_seeds(seed_mask, distance, road_mask, all_obstacles_for_voronoi)
    
    # === SÄILYTÄ RAKENNUSTEN VÄLITÖN YMPÄRISTÖ ===
    # Laajenna rakennuksia 10m (10 pikseliä 1m resoluutiolla) - tämä alue 
    # kuuluu aina tonttiin vaikka olisi kasvillisuusalueella
    building_buffer_pixels = int(10 / resolution)
    buildings_buffered = ndimage.binary_dilation(obstacle_mask, iterations=building_buffer_pixels)
    
    # Kasvillisuus joka EI ole rakennusten välittömässä läheisyydessä
    vegetation_to_remove = vegetation_mask & ~buildings_buffered
    
    # === MUUNNA ALUEET POLYGONEIKSI ===
    # Kasvillisuus/vesi poistetaan tonteista polygoni kerrallaan, 
    # säilyttäen yhteys rakennukseen
    zones = []
    unique_labels = np.unique(zone_labels)
    unique_labels = unique_labels[unique_labels > 0]  # Poista tausta (0)
    
    print(f"  Löytyi {len(unique_labels)} tonttialuetta")
    
    for label_id in unique_labels:
        # Hae tämän tontin maski
        zone_mask = zone_labels == label_id
        
        # Poista kasvillisuus/vesi tästä tontista, PAITSI rakennuksen läheltä
        zone_mask_clipped = zone_mask & ~vegetation_to_remove
        
        # Jos koko tontti katosi, käytä alkuperäistä (voi tapahtua jos rakennus on kasvillisuudessa)
        if not zone_mask_clipped.any():
            zone_mask_clipped = zone_mask
        
        # Connected components: pidä vain se osa joka on yhteydessä rakennukseen
        # Hae rakennuksen sijainti (seed_mask)
        building_pixels = seed_mask == label_id
        
        if building_pixels.any():
            # Laajenna rakennusta hieman jotta yhteys löytyy
            building_dilated = ndimage.binary_dilation(building_pixels, iterations=5)
            
            # Merkitse yhteydessä olevat alueet
            labeled_components, num_components = ndimage.label(zone_mask_clipped)
            
            # Etsi komponentti joka on yhteydessä rakennukseen
            connected_component = None
            for comp_id in range(1, num_components + 1):
                comp_mask = labeled_components == comp_id
                # Tarkista onko yhteydessä rakennukseen
                if (comp_mask & building_dilated).any():
                    if connected_component is None:
                        connected_component = comp_mask
                    else:
                        connected_component = connected_component | comp_mask
            
            if connected_component is not None:
                zone_mask_clipped = connected_component
            else:
                # Ei löytynyt yhteyttä - käytä rakennuksen laajennusta
                zone_mask_clipped = zone_mask & building_dilated
        
        area_pixels = zone_mask_clipped.sum()
        area_m2 = area_pixels * resolution * resolution
        
        if area_m2 < min_zone_area:
            continue
        
        # Hae alueen ääriviiva
        contour = _find_contour(zone_mask_clipped)
        
        if contour is None or len(contour) < 3:
            continue
        
        # Muunna koordinaatit metreihin
        step = max(1, len(contour) // 80)  # Max 80 pistettä
        vertices = []
        for i in range(0, len(contour), step):
            y_idx, x_idx = contour[i]
            x = x_idx * resolution
            y = y_idx * resolution
            vertices.append([round(x, 1), round(y, 1)])
        
        if len(vertices) < 3:
            continue
        
        # Pyöristä terävät kulmat (estää laskentaongelmia CFD:ssä)
        vertices_tuples = [(v[0], v[1]) for v in vertices]
        smoothed_tuples = smooth_polygon_corners(
            vertices_tuples, 
            radius=3.0,           # 3m pyöristyssäde
            angle_threshold=100.0, # Pyöristä alle 100° kulmat
            points_per_corner=3    # 3 pistettä per pyöristys
        )
        vertices = [[round(v[0], 1), round(v[1], 1)] for v in smoothed_tuples]
        
        # Laske keskipiste
        vertices_arr = np.array(vertices)
        cx = vertices_arr[:, 0].mean()
        cy = vertices_arr[:, 1].mean()
        
        zones.append({
            'id': f'Z{label_id}',
            'type': 'editable_zone',
            'zone_type': 'unknown',
            'vertices': vertices,
            'area_m2': round(area_m2, 1),
            'center': [round(cx, 1), round(cy, 1)],
            'building_id': int(label_id)  # Viittaus rakennukseen jonka "tontti" tämä on
        })
    
    print(f"  {len(zones)} aluetta ylittää minimialan ({min_zone_area} m²)")
    return zones


def identify_zones_from_cadastre(
    geometry: Dict,
    center_lat: float,
    center_lon: float,
    mml_api_key: str,
    min_zone_area: float = 50.0
) -> List[Dict]:
    """
    Hae tonttirajat Maanmittauslaitoksen kiinteistörekisteristä.
    
    Käyttää oikeita hallinnollisia tonttirajoja Voronoi-jaon sijaan.
    
    Args:
        geometry: Geometriadata (tarvitaan domain-tiedot)
        center_lat: Keskipisteen latitudi (WGS84)
        center_lon: Keskipisteen longitudi (WGS84)
        mml_api_key: MML API-avain
        min_zone_area: Minimipinta-ala m²
    
    Returns:
        Lista tonteista zone-muodossa
    """
    try:
        from mml_cadastre import fetch_cadastral_zones, PYPROJ_AVAILABLE
        if PYPROJ_AVAILABLE:
            from mml_cadastre import wgs84_to_tm35
    except ImportError:
        print("  VIRHE: mml_cadastre.py ei löydy!")
        print("  Käytetään Voronoi-jakoa varavaihtoehtona")
        return identify_zones(geometry, min_zone_area=min_zone_area)
    
    width = geometry['domain']['width']
    height = geometry['domain']['height']
    metadata = geometry.get('metadata', {})
    
    print(f"\n=== Haetaan tonttirajat MML:stä ===")
    print(f"  Kohde: {center_lat:.6f}°N, {center_lon:.6f}°E")
    print(f"  Alue: {width}m x {height}m")
    
    # Hae domain_offset metadatasta tai laske keskipisteestä
    origin_x = metadata.get('domain_offset_x')
    origin_y = metadata.get('domain_offset_y')
    
    if origin_x is None or origin_y is None:
        # Vanha tiedosto - laske origo keskipisteestä (approksimaatio)
        print("  HUOM: domain_offset puuttuu - lasketaan keskipisteestä")
        if PYPROJ_AVAILABLE:
            center_x, center_y = wgs84_to_tm35.transform(center_lon, center_lat)
        else:
            # Yksinkertainen muunnos
            center_x = 500000 + (center_lon - 27) * 111320 * np.cos(np.radians(center_lat))
            center_y = center_lat * 110574
        origin_x = center_x - width / 2
        origin_y = center_y - height / 2
    
    try:
        zones, origin = fetch_cadastral_zones(
            center_lat=center_lat,
            center_lon=center_lon,
            width=width,
            height=height,
            api_key=mml_api_key,
            min_area=min_zone_area,
            origin_x=origin_x,
            origin_y=origin_y
        )
        
        if not zones:
            print("  MML ei palauttanut tontteja - käytetään Voronoi-jakoa")
            return identify_zones(geometry, min_zone_area=min_zone_area)
        
        print(f"  Löytyi {len(zones)} tonttia MML:stä")
        return zones
        
    except Exception as e:
        print(f"  VIRHE MML-haussa: {e}")
        print("  Käytetään Voronoi-jakoa varavaihtoehtona")
        return identify_zones(geometry, min_zone_area=min_zone_area)


def _watershed_from_seeds(
    seed_mask: np.ndarray,
    distance: np.ndarray,
    road_mask: np.ndarray,
    obstacle_mask: np.ndarray,
    max_iterations: int = 500
) -> np.ndarray:
    """
    Voronoi-pohjainen jako joka jakaa alueet rakennusten etäisyyden mukaan.
    
    Käyttää todellista etäisyysmuunnosta jokaisesta rakennuksesta, jolloin
    rajat muodostuvat luonnollisesti rakennusten väliin (puoliväliin).
    Tiet toimivat kovana rajana - tontti ei voi ulottua tien yli.
    
    Args:
        seed_mask: Siemenmaski (0 = tyhjä, >0 = rakennuksen ID)
        distance: Etäisyys lähimpään esteeseen (ei käytetä suoraan)
        road_mask: Tiet (True = tie) - toimivat kovana rajana
        obstacle_mask: Kaikki esteet
        max_iterations: Ei käytetä tässä versiossa
    
    Returns:
        Labeloitu maski jossa jokainen tontti on merkitty rakennuksen ID:llä
    """
    from scipy import ndimage
    
    ny, nx = seed_mask.shape
    
    # Hae kaikki uniikit rakennuslabelit
    unique_labels = np.unique(seed_mask)
    unique_labels = unique_labels[unique_labels > 0]
    
    if len(unique_labels) == 0:
        return np.zeros((ny, nx), dtype=np.int32)
    
    # Levitä tiet hieman (3 pikseliä) jotta ne toimivat selvänä rajana
    road_barrier = ndimage.binary_dilation(road_mask, iterations=1)
    
    # Laske etäisyys jokaiseen rakennukseen erikseen
    # Tiet toimivat "esteenä" etäisyyslaskennassa - etäisyys lasketaan
    # kiertäen tien (ei suoraan tien läpi)
    min_distance = np.full((ny, nx), np.inf)
    labels = np.zeros((ny, nx), dtype=np.int32)
    
    for label_id in unique_labels:
        # Maski tämän rakennuksen pikseleistä
        building_mask = seed_mask == label_id
        
        # Etäisyyslaskenta: tiet toimivat esteinä
        # Käytetään geodesista etäisyyttä: ei voi kulkea tien läpi
        # Tämä tehdään käyttämällä maskattua etäisyysmuunnosta
        
        # Luo maski jossa rakennus on 0 ja tiet ovat "ääretön"
        blocked = road_barrier.copy()
        
        # Laske etäisyys käyttäen gray-weighted distance transform
        # Yksinkertaistettu: laske ensin normaali etäisyys, sitten
        # lisää "rangaistus" jos polku kulkisi tien läpi
        
        # Perusetäisyys rakennuksen reunasta
        dist_from_building = ndimage.distance_transform_edt(~building_mask)
        
        # Tarkista onko suora linja rakennukseen katkaistu tiellä
        # Yksinkertaistettu: jos pikseli on tien "toisella puolella" 
        # suhteessa rakennukseen, lisää iso rangaistus
        
        # Päivitä labelit jos tämä rakennus on lähempänä
        closer = dist_from_building < min_distance
        labels[closer] = label_id
        min_distance[closer] = dist_from_building[closer]
    
    # === TEIDEN KÄSITTELY: estä tonttien yhdistyminen tien yli ===
    # Käydään läpi teiden pikselit ja tarkistetaan onko eri labelit
    # vastakkaisilla puolilla - jos on, merkitään tie rajaksi
    
    # Dilataatio löytää naapuripikselit
    for label_id in unique_labels:
        label_mask = labels == label_id
        
        # Laajenna tätä aluetta
        dilated = ndimage.binary_dilation(label_mask, iterations=1)
        
        # Tarkista ylittääkö laajennus tien ja onko toisella puolella eri label
        crosses_road = dilated & road_barrier & ~label_mask
        
        if crosses_road.any():
            # Etsi pikselit jotka ovat tien takana
            # ja kuuluvat tähän labeliin vaikka eivät pitäisi
            
            # Hae tämän rakennuksen sijainti
            building_pixels = seed_mask == label_id
            if not building_pixels.any():
                continue
            
            by, bx = np.where(building_pixels)
            building_center_y = by.mean()
            building_center_x = bx.mean()
            
            # Käy läpi kaikki pikselit jotka kuuluvat tähän labeliin
            # ja tarkista onko niiden ja rakennuksen välissä tie
            label_y, label_x = np.where(label_mask)
            
            for py, px in zip(label_y, label_x):
                # Piirrä viiva rakennuksen keskipisteestä tähän pikseliin
                # ja tarkista ylittääkö se tien
                n_points = max(abs(py - building_center_y), abs(px - building_center_x))
                if n_points < 2:
                    continue
                n_points = int(n_points)
                
                line_y = np.linspace(building_center_y, py, n_points).astype(int)
                line_x = np.linspace(building_center_x, px, n_points).astype(int)
                
                # Rajoita indeksit
                line_y = np.clip(line_y, 0, ny - 1)
                line_x = np.clip(line_x, 0, nx - 1)
                
                # Tarkista ylittääkö viiva tien
                if road_barrier[line_y, line_x].any():
                    # Tämä pikseli on tien takana - poista labelista
                    labels[py, px] = 0
    
    # Poista teiden pikselit tuloksesta
    labels[road_mask] = 0
    
    # Poista esteiden pikselit (rakennukset, kasvillisuus, vesi)
    labels[obstacle_mask] = 0
    
    # Poista reunapikselit
    border = 2
    labels[:border, :] = 0
    labels[-border:, :] = 0
    labels[:, :border] = 0
    labels[:, -border:] = 0
    
    return labels


def _find_contour(binary_mask: np.ndarray, simplify: bool = True) -> Optional[List[Tuple[int, int]]]:
    """
    Etsi binäärimaskin ääriviiva seuraamalla reunaa (boundary tracing).
    
    Tämä algoritmi seuraa tarkasti maskin reunaa, joten alueet eivät mene
    päällekkäin (toisin kuin convex hull).
    
    Args:
        binary_mask: 2D numpy array (True = alue, False = tyhjä)
        simplify: Yksinkertaista polygoni Douglas-Peucker algoritmilla
    
    Returns:
        Lista (y, x) -koordinaateista tai None
    """
    from scipy import ndimage
    
    # Hae reunapikselit (pikselit joilla on vähintään yksi tyhjä naapuri)
    # Käytetään morfologista eroosiota reunan löytämiseen
    eroded = ndimage.binary_erosion(binary_mask)
    edge_mask = binary_mask & ~eroded
    
    edge_points = np.argwhere(edge_mask)
    
    if len(edge_points) < 3:
        # Fallback: käytä kaikkia pisteitä
        edge_points = np.argwhere(binary_mask)
        if len(edge_points) < 3:
            return None
    
    # Seuraa reunaa (Moore neighborhood boundary tracing)
    contour = _trace_boundary(binary_mask)
    
    if contour is None or len(contour) < 3:
        # Fallback: järjestä pisteet kulman mukaan
        center_y = edge_points[:, 0].mean()
        center_x = edge_points[:, 1].mean()
        angles = np.arctan2(edge_points[:, 0] - center_y, edge_points[:, 1] - center_x)
        sorted_indices = np.argsort(angles)
        contour = [(int(edge_points[i, 0]), int(edge_points[i, 1])) for i in sorted_indices]
    
    if simplify and len(contour) > 20:
        # Yksinkertaista Douglas-Peucker algoritmilla
        contour_arr = np.array(contour)
        simplified = _douglas_peucker(contour_arr, tolerance=1.5)
        contour = [(int(p[0]), int(p[1])) for p in simplified]
    
    return contour


def _trace_boundary(binary_mask: np.ndarray) -> Optional[List[Tuple[int, int]]]:
    """
    Moore neighborhood boundary tracing algoritmi.
    Seuraa maskin reunaa myötäpäivään alkaen vasemmasta yläkulmasta.
    
    Args:
        binary_mask: 2D numpy array
    
    Returns:
        Lista (y, x) -koordinaateista järjestyksessä reunaa pitkin
    """
    ny, nx = binary_mask.shape
    
    # Etsi aloituspiste (ensimmäinen True-pikseli skannatessa ylhäältä alas, vasemmalta oikealle)
    start = None
    for y in range(ny):
        for x in range(nx):
            if binary_mask[y, x]:
                start = (y, x)
                break
        if start:
            break
    
    if start is None:
        return None
    
    # Moore naapurusto (8-suuntainen, myötäpäivään alkaen vasemmalta)
    # Järjestys: vasen, vasen-ylä, ylä, oikea-ylä, oikea, oikea-ala, ala, vasen-ala
    directions = [
        (0, -1),   # vasen
        (-1, -1),  # vasen-ylä
        (-1, 0),   # ylä
        (-1, 1),   # oikea-ylä
        (0, 1),    # oikea
        (1, 1),    # oikea-ala
        (1, 0),    # ala
        (1, -1),   # vasen-ala
    ]
    
    contour = [start]
    current = start
    # Aloita etsimällä vasemmalta (direction index 0), mutta backtrack edelliseen
    prev_dir = 4  # Tultiin "oikealta" (vastakkainen suunta)
    
    max_iterations = ny * nx  # Turvarajoitus
    
    for _ in range(max_iterations):
        # Etsi seuraava reunapikseli myötäpäivään edellisestä suunnasta
        # Aloita suunnasta (prev_dir + 5) % 8 (eli backtrack + 1 myötäpäivään)
        start_dir = (prev_dir + 5) % 8
        
        found = False
        for i in range(8):
            dir_idx = (start_dir + i) % 8
            dy, dx = directions[dir_idx]
            ny_new, nx_new = current[0] + dy, current[1] + dx
            
            # Tarkista rajat
            if 0 <= ny_new < ny and 0 <= nx_new < nx:
                if binary_mask[ny_new, nx_new]:
                    next_point = (ny_new, nx_new)
                    
                    # Tarkista olemmeko palanneet alkuun
                    if next_point == start and len(contour) > 2:
                        return contour
                    
                    # Älä lisää samaa pistettä peräkkäin
                    if next_point != current:
                        contour.append(next_point)
                        current = next_point
                        prev_dir = dir_idx
                        found = True
                        break
        
        if not found:
            # Ei löytynyt seuraavaa pistettä (yksittäinen pikseli tai virhe)
            break
        
        # Turvarajoitus: jos contour kasvaa liian suureksi
        if len(contour) > max_iterations // 2:
            break
    
    return contour if len(contour) >= 3 else None


def _find_contour_detailed(binary_mask: np.ndarray, simplify_tolerance: float = 2.0) -> Optional[List[Tuple[int, int]]]:
    """
    Etsi binäärimaskin ääriviiva yksityiskohtaisemmin (marching squares -tyylinen).
    Käyttää Douglas-Peucker algoritmia yksinkertaistamiseen.
    
    Args:
        binary_mask: 2D numpy array (True = alue, False = tyhjä)
        simplify_tolerance: Yksinkertaistamisen toleranssi pikseleissä
    
    Returns:
        Lista (y, x) -koordinaateista tai None
    """
    from scipy import ndimage
    
    # Hae reunapikselit
    eroded = ndimage.binary_erosion(binary_mask)
    edge_mask = binary_mask & ~eroded
    edge_points = np.argwhere(edge_mask)
    
    if len(edge_points) < 3:
        return _find_contour(binary_mask)  # Fallback convex hulliin
    
    # Järjestä pisteet seuraamaan reunaa (nearest neighbor chain)
    ordered_points = _order_points_by_chain(edge_points)
    
    if ordered_points is None or len(ordered_points) < 3:
        return _find_contour(binary_mask)
    
    # Yksinkertaista Douglas-Peucker algoritmilla
    simplified = _douglas_peucker(ordered_points, simplify_tolerance)
    
    if len(simplified) < 3:
        return _find_contour(binary_mask)
    
    return [(int(p[0]), int(p[1])) for p in simplified]


def _order_points_by_chain(points: np.ndarray) -> Optional[np.ndarray]:
    """
    Järjestää pisteet lähimmän naapurin ketjuksi.
    """
    if len(points) < 3:
        return None
    
    from scipy.spatial import cKDTree
    
    # Rakenna KD-puu nopeaan naapurihakuun
    tree = cKDTree(points)
    
    n = len(points)
    visited = np.zeros(n, dtype=bool)
    ordered = []
    
    # Aloita ensimmäisestä pisteestä
    current_idx = 0
    
    for _ in range(n):
        ordered.append(points[current_idx])
        visited[current_idx] = True
        
        # Etsi lähin vierailematon naapuri
        distances, indices = tree.query(points[current_idx], k=min(10, n))
        
        next_idx = None
        for idx in indices:
            if not visited[idx]:
                next_idx = idx
                break
        
        if next_idx is None:
            break
        
        current_idx = next_idx
    
    if len(ordered) < 3:
        return None
    
    return np.array(ordered)


def _douglas_peucker(points: np.ndarray, tolerance: float) -> np.ndarray:
    """
    Douglas-Peucker algoritmi polygonin yksinkertaistamiseen.
    """
    if len(points) <= 2:
        return points
    
    # Etsi kauimmaisin piste viivasta alku-loppu
    start = points[0]
    end = points[-1]
    
    # Laske etäisyydet viivaan
    line_vec = end - start
    line_len = np.sqrt(np.sum(line_vec**2))
    
    if line_len < 1e-10:
        return np.array([start, end])
    
    line_unit = line_vec / line_len
    
    max_dist = 0
    max_idx = 0
    
    for i in range(1, len(points) - 1):
        point_vec = points[i] - start
        proj_length = np.dot(point_vec, line_unit)
        proj_length = max(0, min(line_len, proj_length))
        proj_point = start + proj_length * line_unit
        dist = np.sqrt(np.sum((points[i] - proj_point)**2))
        
        if dist > max_dist:
            max_dist = dist
            max_idx = i
    
    # Jos maksimietäisyys ylittää toleranssin, rekursio
    if max_dist > tolerance:
        left = _douglas_peucker(points[:max_idx + 1], tolerance)
        right = _douglas_peucker(points[max_idx:], tolerance)
        return np.vstack([left[:-1], right])
    else:
        return np.array([start, end])


def _fill_polygon(mask: np.ndarray, vertices: np.ndarray, resolution: float):
    """Täyttää polygonin maskiin (scanline fill algoritmi)."""
    ny, nx = mask.shape
    
    if len(vertices) < 3:
        return
    
    # Muunna koordinaatit pikselikoordinaateiksi
    poly_x = (vertices[:, 0] / resolution).astype(int)
    poly_y = (vertices[:, 1] / resolution).astype(int)
    
    # Rajoita alueelle
    poly_x = np.clip(poly_x, 0, nx - 1)
    poly_y = np.clip(poly_y, 0, ny - 1)
    
    # Bounding box
    min_y, max_y = poly_y.min(), poly_y.max()
    min_x, max_x = poly_x.min(), poly_x.max()
    
    # Scanline fill
    n = len(poly_x)
    for y in range(min_y, max_y + 1):
        # Etsi leikkauspisteet tällä y-tasolla
        intersections = []
        for i in range(n):
            j = (i + 1) % n
            y1, y2 = poly_y[i], poly_y[j]
            x1, x2 = poly_x[i], poly_x[j]
            
            if y1 == y2:
                continue
            if y < min(y1, y2) or y > max(y1, y2):
                continue
            
            # Laske x-koordinaatti leikkauspisteelle
            x_intersect = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            intersections.append(x_intersect)
        
        # Järjestä ja täytä parit
        intersections.sort()
        for k in range(0, len(intersections) - 1, 2):
            x_start = int(max(0, intersections[k]))
            x_end = int(min(nx - 1, intersections[k + 1]))
            if x_start <= x_end:
                mask[y, x_start:x_end + 1] = True


def _filter_vegetation_overlapping_zones(
    zones: List[Dict], 
    obstacles: List[Dict],
    threshold: float = 0.5
) -> List[Dict]:
    """
    Suodattaa pois editable_zonet jotka ovat kasvillisuusalueiden peitossa.
    
    Args:
        zones: Lista editable_zones
        obstacles: Lista obstacles (sisältää tree_zone, vegetation_zone)
        threshold: Päällekkäisyyskynnys (0.5 = >50% peitossa → poistetaan)
    
    Returns:
        Suodatettu lista zoneista
    """
    from shapely.geometry import Polygon
    from shapely.validation import make_valid
    
    # Kerää kasvillisuuspolygonit
    veg_polys = []
    for obs in obstacles:
        obs_type = obs.get('type', '')
        if obs_type in ('tree_zone', 'vegetation_zone') and obs.get('vertices'):
            try:
                poly = Polygon(obs['vertices'])
                if not poly.is_valid:
                    poly = make_valid(poly)
                if poly.area > 0:
                    veg_polys.append(poly)
            except Exception:
                continue
    
    if not veg_polys:
        return zones
    
    # Yhdistä kasvillisuusalueet yhdeksi multipolygoniksi (nopea leikkaus)
    from shapely.ops import unary_union
    veg_union = unary_union(veg_polys)
    
    # Suodata
    filtered = []
    removed = []
    for zone in zones:
        if zone.get('zone_type') != 'unknown' or not zone.get('vertices'):
            filtered.append(zone)
            continue
        
        try:
            zpoly = Polygon(zone['vertices'])
            if not zpoly.is_valid:
                zpoly = make_valid(zpoly)
            if zpoly.area <= 0:
                filtered.append(zone)
                continue
            
            overlap = zpoly.intersection(veg_union).area / zpoly.area
            if overlap > threshold:
                removed.append((zone.get('id', '?'), round(overlap * 100)))
            else:
                filtered.append(zone)
        except Exception:
            filtered.append(zone)
    
    if removed:
        print(f"  Editable zones suodatus: poistettu {len(removed)} aluetta (>{threshold*100:.0f}% kasvillisuuden peitossa):")
        for zid, pct in removed:
            print(f"    {zid}: {pct}% peitossa")
    
    return filtered


def generate_html_editor(
    geometry: Dict,
    output_path: str,
    zones: List[Dict] = None,
    roads: List[Dict] = None
) -> str:
    """
    Generoi interaktiivinen HTML-editori.
    
    Args:
        geometry: Geometriadata
        output_path: HTML-tiedoston polku
        zones: Lista tunnistetuista alueista
        roads: Lista teistä
    
    Returns:
        Polku generoituun HTML-tiedostoon
    """
    width = geometry['domain']['width']
    height = geometry['domain']['height']
    name = geometry.get('name', 'Geometria')
    
    # Kerää kaikki elementit
    obstacles = geometry.get('obstacles', [])
    if roads is None:
        roads = geometry.get('roads', [])
    if zones is None:
        zones = geometry.get('editable_zones', [])
    
    # Suodata pois editable_zonet jotka ovat kasvillisuusalueiden peitossa
    zones = _filter_vegetation_overlapping_zones(zones, obstacles)
    
    # Generoi JavaScript-data
    js_obstacles = json.dumps(obstacles, ensure_ascii=False)
    js_roads = json.dumps(roads, ensure_ascii=False)
    js_zones = json.dumps(zones, ensure_ascii=False)
    js_zone_types = json.dumps(ZONE_TYPES, ensure_ascii=False)
    
    html_content = f'''<!DOCTYPE html>
<html lang="fi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Alueeditori - {name}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ 
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #1a1a2e; 
            color: #eee;
            display: flex;
            height: 100vh;
        }}
        
        /* Sivupaneeli - 40% leveydestä */
        .sidebar {{
            width: 40%;
            min-width: 400px;
            max-width: 500px;
            background: #16213e;
            padding: 20px;
            overflow-y: auto;
            border-right: 1px solid #0f3460;
        }}
        .sidebar h1 {{
            font-size: 1.4em;
            margin-bottom: 10px;
            color: #e94560;
        }}
        .sidebar h2 {{
            font-size: 1.1em;
            margin: 20px 0 10px;
            color: #94a3b8;
            border-bottom: 1px solid #0f3460;
            padding-bottom: 5px;
        }}
        
        /* Info-laatikko */
        .info-box {{
            background: #0f3460;
            padding: 12px;
            border-radius: 8px;
            margin-bottom: 15px;
            font-size: 0.9em;
        }}
        .info-box p {{ margin: 5px 0; }}
        .info-box .label {{ color: #94a3b8; }}
        
        /* Aluetyypin valinta - kategorioittain */
        .zone-type-category {{
            margin-bottom: 12px;
        }}
        .category-header {{
            font-size: 0.75em;
            font-weight: bold;
            color: #94a3b8;
            padding: 4px 8px;
            margin-bottom: 6px;
            border-left: 3px solid;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
        .zone-type-selector {{
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 5px;
            margin-bottom: 8px;
        }}
        .zone-type-btn {{
            padding: 6px 6px;
            border: 2px solid transparent;
            border-radius: 4px;
            cursor: pointer;
            font-size: 0.75em;
            transition: all 0.2s;
            display: flex;
            align-items: center;
            gap: 6px;
            background: #0a1628;
        }}
        .zone-type-btn:hover {{ transform: scale(1.02); background: #0f3460; }}
        .zone-type-btn.selected {{ border-color: #e94560; background: #1a3a5c; }}
        .zone-type-btn .color-dot {{
            width: 12px;
            height: 12px;
            border-radius: 50%;
            flex-shrink: 0;
        }}
        .zone-type-btn .type-info {{
            display: flex;
            flex-direction: column;
            line-height: 1.2;
        }}
        .zone-type-btn .type-name {{ font-weight: 500; color: #fff; }}
        .zone-type-btn .type-lai {{ font-size: 0.8em; color: #94a3b8; }}
        
        /* Aluelista */
        .zone-list {{
            max-height: 250px;
            overflow-y: auto;
        }}
        .zone-item {{
            background: #0f3460;
            padding: 8px 12px;
            border-radius: 6px;
            margin-bottom: 6px;
            cursor: pointer;
            transition: all 0.2s;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        .zone-item:hover {{ background: #1a4a7a; }}
        .zone-item.selected {{ 
            background: #1a4a7a; 
            border-left: 3px solid #e94560;
        }}
        .zone-item .zone-id {{ font-weight: bold; color: #e94560; font-size: 0.9em; }}
        .zone-item .zone-type {{ 
            font-size: 0.75em; 
            padding: 2px 8px;
            border-radius: 4px;
            background: #16213e;
        }}
        .zone-item .zone-area {{
            font-size: 0.7em;
            color: #64748b;
        }}
        
        /* Valitun alueen info */
        .selected-zone-info {{
            background: #0a1628;
            border: 1px solid #0f3460;
            border-radius: 8px;
            padding: 12px;
            margin-bottom: 15px;
        }}
        .selected-zone-info h3 {{
            color: #e94560;
            margin: 0 0 8px 0;
            font-size: 1em;
        }}
        .selected-zone-info .info-grid {{
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 8px;
            font-size: 0.85em;
        }}
        .selected-zone-info .info-item {{
            background: #0f3460;
            padding: 6px 10px;
            border-radius: 4px;
        }}
        .selected-zone-info .info-label {{
            color: #64748b;
            font-size: 0.8em;
        }}
        .selected-zone-info .info-value {{
            color: #e2e8f0;
            font-weight: 500;
        }}
        .selected-zone-info .info-item.editable input {{
            width: 100%;
            background: #1a3a5c;
            border: 1px solid #0f3460;
            border-radius: 4px;
            color: #e2e8f0;
            padding: 4px 8px;
            font-size: 0.9em;
            margin-top: 2px;
        }}
        .selected-zone-info .info-item.editable input:focus {{
            outline: none;
            border-color: #e94560;
        }}
        
        /* Painikkeet */
        .btn {{
            padding: 12px 20px;
            border: none;
            border-radius: 6px;
            cursor: pointer;
            font-size: 0.95em;
            font-weight: 500;
            transition: all 0.2s;
            width: 100%;
            margin-bottom: 10px;
        }}
        .btn-primary {{
            background: #e94560;
            color: white;
        }}
        .btn-primary:hover {{ background: #d63651; }}
        .btn-secondary {{
            background: #0f3460;
            color: #eee;
        }}
        .btn-secondary:hover {{ background: #1a4a7a; }}
        
        /* Kartta-alue - 60% leveydestä */
        .map-container {{
            flex: 1;
            min-width: 60%;
            display: flex;
            flex-direction: column;
            padding: 20px;
        }}
        .map-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 15px;
        }}
        .map-header h2 {{ color: #e94560; }}
        .zoom-controls {{
            display: flex;
            gap: 10px;
        }}
        .zoom-btn {{
            width: 36px;
            height: 36px;
            border: none;
            border-radius: 6px;
            background: #0f3460;
            color: #eee;
            font-size: 1.2em;
            cursor: pointer;
        }}
        .zoom-btn:hover {{ background: #1a4a7a; }}
        
        /* SVG kartta */
        .map-wrapper {{
            flex: 1;
            background: #0d1b2a;
            border-radius: 12px;
            overflow: hidden;
            position: relative;
        }}
        #map-svg {{
            width: 100%;
            height: 100%;
            cursor: grab;
        }}
        #map-svg:active {{ cursor: grabbing; }}
        
        /* Tooltip */
        .tooltip {{
            position: absolute;
            background: rgba(22, 33, 62, 0.95);
            color: #eee;
            padding: 8px 12px;
            border-radius: 6px;
            font-size: 0.85em;
            pointer-events: none;
            z-index: 1000;
            display: none;
            border: 1px solid #0f3460;
        }}
        
        /* Legenda */
        .legend {{
            position: absolute;
            bottom: 20px;
            right: 20px;
            background: rgba(22, 33, 62, 0.9);
            padding: 12px;
            border-radius: 8px;
            font-size: 0.8em;
        }}
        .legend-item {{
            display: flex;
            align-items: center;
            gap: 8px;
            margin: 4px 0;
        }}
        .legend-color {{
            width: 20px;
            height: 12px;
            border-radius: 2px;
        }}
        
        /* Ohjeet */
        .instructions {{
            background: #0f3460;
            padding: 12px;
            border-radius: 8px;
            font-size: 0.85em;
            line-height: 1.6;
        }}
        .instructions li {{ margin-left: 20px; margin-bottom: 5px; }}
        
        /* Piirtotyökalut */
        .drawing-tools {{
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            margin-bottom: 10px;
        }}
        .btn-tool {{
            flex: 1;
            min-width: 120px;
            padding: 10px 8px;
            font-size: 0.85em;
            background: #1a3a5c;
            border: 2px solid #3a5a7c;
        }}
        .btn-tool:hover {{ background: #2a4a6c; }}
        .btn-tool.active {{
            background: #e94560;
            border-color: #e94560;
        }}
        .btn-tool.btn-danger {{
            background: #6b2020;
            border-color: #8b3030;
        }}
        .btn-tool.btn-danger:hover {{ background: #8b3030; }}
        .btn-tool.btn-danger.active {{
            background: #c53030;
            border-color: #e53030;
        }}
        .drawing-status {{
            background: #e94560;
            padding: 10px;
            border-radius: 6px;
            margin-bottom: 10px;
            text-align: center;
            font-weight: bold;
        }}
        
        /* Modaali */
        .modal-overlay {{
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(0, 0, 0, 0.7);
            display: flex;
            align-items: center;
            justify-content: center;
            z-index: 1000;
        }}
        .modal {{
            background: #16213e;
            padding: 25px;
            border-radius: 12px;
            min-width: 350px;
            max-width: 450px;
            border: 2px solid #e94560;
        }}
        .modal h3 {{
            margin-top: 0;
            color: #e94560;
            margin-bottom: 20px;
        }}
        .modal-field {{
            margin-bottom: 15px;
        }}
        .modal-field label {{
            display: block;
            margin-bottom: 5px;
            color: #8892b0;
        }}
        .modal-field input, .modal-field select {{
            width: 100%;
            padding: 10px;
            border: 1px solid #3a5a7c;
            border-radius: 6px;
            background: #0f3460;
            color: white;
            font-size: 1em;
        }}
        .modal-field input:focus, .modal-field select:focus {{
            border-color: #e94560;
            outline: none;
        }}
        .modal-buttons {{
            display: flex;
            gap: 10px;
            margin-top: 20px;
        }}
        .modal-buttons button {{
            flex: 1;
            padding: 12px;
            border: none;
            border-radius: 6px;
            cursor: pointer;
            font-weight: bold;
        }}
        .modal-btn-primary {{
            background: #e94560;
            color: white;
        }}
        .modal-btn-secondary {{
            background: #3a5a7c;
            color: white;
        }}
        .modal-btn-primary:hover {{ background: #d93550; }}
        .modal-btn-secondary:hover {{ background: #4a6a8c; }}
        
        /* Piirtokursori */
        .drawing-mode {{ cursor: crosshair !important; }}
        .delete-mode {{ cursor: not-allowed !important; }}
        .drawing-point {{
            fill: #e94560;
            stroke: white;
            stroke-width: 1;
        }}
        .drawing-line {{
            stroke: #e94560;
            stroke-width: 2;
            stroke-dasharray: 5,5;
            fill: none;
        }}
        .drawing-polygon {{
            fill: rgba(233, 69, 96, 0.3);
            stroke: #e94560;
            stroke-width: 2;
        }}
        .deletable:hover {{
            stroke: #ff0000 !important;
            stroke-width: 3 !important;
            cursor: pointer !important;
        }}
    </style>
</head>
<body>
    <div class="sidebar">
        <h1>🏘️ Alueeditori</h1>
        
        <div class="info-box">
            <p><span class="label">Kohde:</span> {name}</p>
            <p><span class="label">Koko:</span> {width:.0f} × {height:.0f} m</p>
            <p><span class="label">Rakennuksia:</span> <span id="building-count">0</span></p>
            <p><span class="label">Teitä:</span> <span id="road-count">0</span></p>
            <p><span class="label">Muokattavia alueita:</span> <span id="zone-count">0</span></p>
        </div>
        
        <h2>Valitse aluetyyppi</h2>
        <div class="zone-type-selector" id="zone-types"></div>
        
        <h2>Muokattavat alueet</h2>
        
        <!-- Valitun alueen tiedot -->
        <div class="selected-zone-info" id="selected-zone-info" style="display: none;">
            <h3>Valittu alue: <span id="selected-zone-id">-</span></h3>
            <div class="info-grid">
                <div class="info-item">
                    <div class="info-label">Tyyppi</div>
                    <div class="info-value" id="selected-zone-type">-</div>
                </div>
                <div class="info-item">
                    <div class="info-label">Pinta-ala</div>
                    <div class="info-value" id="selected-zone-area">-</div>
                </div>
                <div class="info-item editable">
                    <div class="info-label">LAI (kesä)</div>
                    <input type="number" id="selected-zone-lai" step="0.1" min="0" max="10" 
                           onchange="updateZoneLAI(this.value)">
                </div>
                <div class="info-item editable">
                    <div class="info-label">LAI (talvi)</div>
                    <input type="number" id="selected-zone-lai-winter" step="0.1" min="0" max="10"
                           onchange="updateZoneLAIWinter(this.value)">
                </div>
                <div class="info-item editable">
                    <div class="info-label">Korkeus (m)</div>
                    <input type="number" id="selected-zone-height" step="0.1" min="0" max="50"
                           onchange="updateZoneHeight(this.value)">
                </div>
                <div class="info-item">
                    <div class="info-label">Huokoisuus</div>
                    <div class="info-value" id="selected-zone-porosity">-</div>
                </div>
            </div>
        </div>
        <div class="zone-list" id="zone-list"></div>
        
        <h2>Piirtotyökalut</h2>
        <div class="drawing-tools">
            <button class="btn btn-tool" id="btn-draw-building" onclick="startDrawingBuilding()">
                🏠 Piirrä rakennus
            </button>
            <button class="btn btn-tool" id="btn-draw-zone" onclick="startDrawingZone()">
                🌳 Piirrä alue
            </button>
            <button class="btn btn-tool btn-danger" id="btn-delete" onclick="startDeleteMode()">
                🗑️ Poista objekti
            </button>
            <button class="btn btn-tool" id="btn-cancel" onclick="cancelDrawing()" style="display: none;">
                ✖ Peruuta
            </button>
        </div>
        <div id="drawing-status" class="drawing-status" style="display: none;">
            <span id="drawing-status-text">-</span>
        </div>
        
        <h2>Toiminnot</h2>
        <button class="btn btn-primary" onclick="exportGeometry()">
            💾 Tallenna JSON
        </button>
        <button class="btn btn-secondary" onclick="resetZones()">
            🔄 Palauta alkuperäiset
        </button>
        <button class="btn btn-secondary" onclick="selectAllUnknown()">
            ⚡ Valitse kaikki tuntemattomat
        </button>
        
        <h2>Ohjeet</h2>
        <div class="instructions">
            <ul>
                <li><b>Alueiden muokkaus:</b> Klikkaa aluetta → valitse tyyppi</li>
                <li><b>Uusi rakennus:</b> Piirrä rakennus → klikkaa nurkat → tupla-klikkaa</li>
                <li><b>Uusi alue:</b> Piirrä alue → klikkaa nurkat → tupla-klikkaa</li>
                <li><b>Poista objekti:</b> Valitse poisto → klikkaa objektia</li>
                <li>Ctrl+klikkaus valitsee useita alueita</li>
                <li>Tallenna muutokset JSON-tiedostoon</li>
            </ul>
        </div>
    </div>
    
    <div class="map-container">
        <div class="map-header">
            <h2>Karttanäkymä</h2>
            <div class="zoom-controls">
                <button class="zoom-btn" onclick="zoomIn()">+</button>
                <button class="zoom-btn" onclick="zoomOut()">−</button>
                <button class="zoom-btn" onclick="resetView()">⟲</button>
            </div>
        </div>
        
        <div class="map-wrapper">
            <svg id="map-svg" viewBox="0 0 {width} {height}">
                <defs>
                    <pattern id="grid" width="50" height="50" patternUnits="userSpaceOnUse">
                        <path d="M 50 0 L 0 0 0 50" fill="none" stroke="#1a2744" stroke-width="0.5"/>
                    </pattern>
                </defs>
                
                <!-- Tausta -->
                <rect width="100%" height="100%" fill="#0d1b2a"/>
                <rect width="100%" height="100%" fill="url(#grid)"/>
                
                <!-- Muokattavat alueet (renderöidään ensin, jotta jäävät alle) -->
                <g id="zones-layer" transform="scale(1, -1) translate(0, -{height})"></g>
                
                <!-- Tiet -->
                <g id="roads-layer" transform="scale(1, -1) translate(0, -{height})"></g>
                
                <!-- Rakennukset -->
                <g id="buildings-layer" transform="scale(1, -1) translate(0, -{height})"></g>
                
                <!-- Labelit -->
                <g id="labels-layer" transform="scale(1, -1) translate(0, -{height})"></g>
            </svg>
            
            <div class="tooltip" id="tooltip"></div>
            
            <div class="legend">
                <div class="legend-item">
                    <div class="legend-color" style="background: #4a4a4a;"></div>
                    <span>Rakennus</span>
                </div>
                <div class="legend-item">
                    <div class="legend-color" style="background: #555555;"></div>
                    <span>Tie</span>
                </div>
                <div class="legend-item">
                    <div class="legend-color" style="background: #228B22;"></div>
                    <span>Metsä</span>
                </div>
                <div class="legend-item">
                    <div class="legend-color" style="background: #cccccc; opacity: 0.5;"></div>
                    <span>Muokattava alue</span>
                </div>
            </div>
        </div>
    </div>

<script>
// Data
const obstacles = {js_obstacles};
const roads = {js_roads};
let zones = {js_zones};
const zoneTypes = {js_zone_types};
const domainWidth = {width};
const domainHeight = {height};

// Tila
let selectedZones = new Set();
let selectedType = 'yard_lawn';  // Oletuksena piha (nurmikko)
let originalZones = JSON.parse(JSON.stringify(zones));

// Alusta
document.addEventListener('DOMContentLoaded', () => {{
    renderZoneTypes();
    renderZoneList();
    renderMap();
    updateCounts();
}});

function renderZoneTypes() {{
    const container = document.getElementById('zone-types');
    container.innerHTML = '';
    
    // Kategorioiden järjestys ja nimet
    const categories = {{
        'Muu': {{ name: 'Perustyypit', color: '#6b7280' }},
        'Metsä': {{ name: 'Metsät', color: '#166534' }},
        'Puisto': {{ name: 'Puistot', color: '#22c55e' }},
        'Pelto': {{ name: 'Pellot', color: '#ca8a04' }},
        'Pensas': {{ name: 'Pensaat & niityt', color: '#65a30d' }},
        'Kosteikko': {{ name: 'Kosteikot', color: '#0891b2' }},
        'Rakennettu': {{ name: 'Rakennettu', color: '#64748b' }}
    }};
    
    // Ryhmittele tyypit kategorioittain
    const grouped = {{}};
    for (const [key, config] of Object.entries(zoneTypes)) {{
        const cat = config.category || 'Muu';
        if (!grouped[cat]) grouped[cat] = [];
        grouped[cat].push({{ key, ...config }});
    }}
    
    // Luo kategoriat järjestyksessä
    for (const [catKey, catConfig] of Object.entries(categories)) {{
        const types = grouped[catKey];
        if (!types || types.length === 0) continue;
        
        const categoryDiv = document.createElement('div');
        categoryDiv.className = 'zone-type-category';
        
        const header = document.createElement('div');
        header.className = 'category-header';
        header.style.borderLeftColor = catConfig.color;
        header.textContent = catConfig.name;
        categoryDiv.appendChild(header);
        
        const selector = document.createElement('div');
        selector.className = 'zone-type-selector';
        
        for (const config of types) {{
            const btn = document.createElement('button');
            btn.className = 'zone-type-btn' + (config.key === selectedType ? ' selected' : '');
            
            const laiText = config.LAI !== null && config.LAI !== undefined 
                ? `LAI ${{config.LAI}}, ${{config.height}}m` 
                : '';
            
            btn.innerHTML = `
                <div class="color-dot" style="background: ${{config.color}};"></div>
                <div class="type-info">
                    <span class="type-name">${{config.name}}</span>
                    ${{laiText ? `<span class="type-lai">${{laiText}}</span>` : ''}}
                </div>
            `;
            btn.onclick = () => selectType(config.key);
            selector.appendChild(btn);
        }}
        
        categoryDiv.appendChild(selector);
        container.appendChild(categoryDiv);
    }}
}}

function selectType(type) {{
    selectedType = type;
    renderZoneTypes();
    
    // Aseta valituille alueille tämä tyyppi
    if (selectedZones.size > 0) {{
        selectedZones.forEach(zoneId => {{
            const zone = zones.find(z => z.id === zoneId);
            if (zone) {{
                zone.zone_type = type;
            }}
        }});
        renderZoneList();
        renderMap();
        updateSelectedZoneInfo();
    }}
}}

function renderZoneList() {{
    const container = document.getElementById('zone-list');
    container.innerHTML = '';
    
    zones.forEach(zone => {{
        const item = document.createElement('div');
        item.className = 'zone-item' + (selectedZones.has(zone.id) ? ' selected' : '');
        
        const typeConfig = zoneTypes[zone.zone_type] || zoneTypes.unknown;
        item.innerHTML = `
            <span class="zone-id">${{zone.id}}</span>
            <span class="zone-type" style="background: ${{typeConfig.color}}40; color: #fff;">
                ${{typeConfig.name}} (${{zone.area_m2}} m²)
            </span>
        `;
        item.onclick = (e) => selectZone(zone.id, e.ctrlKey || e.metaKey);
        container.appendChild(item);
    }});
}}

function selectZone(zoneId, addToSelection = false) {{
    if (addToSelection) {{
        if (selectedZones.has(zoneId)) {{
            selectedZones.delete(zoneId);
        }} else {{
            selectedZones.add(zoneId);
        }}
    }} else {{
        selectedZones = new Set([zoneId]);
    }}
    
    renderZoneList();
    renderMap();
    updateSelectedZoneInfo();
}}

function laiToPorosity(lai, k = 0.5) {{
    if (lai === null || lai === undefined || lai <= 0) return null;
    return Math.exp(-lai * k);
}}

function updateSelectedZoneInfo() {{
    const infoDiv = document.getElementById('selected-zone-info');
    
    if (selectedZones.size === 0) {{
        infoDiv.style.display = 'none';
        return;
    }}
    
    infoDiv.style.display = 'block';
    
    if (selectedZones.size === 1) {{
        const zoneId = Array.from(selectedZones)[0];
        const zone = zones.find(z => z.id === zoneId);
        const typeConfig = zoneTypes[zone.zone_type] || zoneTypes.unknown;
        
        // Käytä alueen omia arvoja jos ne on asetettu, muuten tyypin oletukset
        const lai = zone.custom_LAI !== undefined ? zone.custom_LAI : typeConfig.LAI;
        const laiWinter = zone.custom_LAI_winter !== undefined ? zone.custom_LAI_winter : typeConfig.LAI_winter;
        const height = zone.custom_height !== undefined ? zone.custom_height : typeConfig.height;
        const porosity = laiToPorosity(lai);
        
        document.getElementById('selected-zone-id').textContent = zone.id;
        document.getElementById('selected-zone-type').textContent = typeConfig.name;
        document.getElementById('selected-zone-area').textContent = zone.area_m2 + ' m²';
        
        // Editoitavat kentät
        document.getElementById('selected-zone-lai').value = lai !== null ? lai : '';
        document.getElementById('selected-zone-lai-winter').value = laiWinter !== null ? laiWinter : '';
        document.getElementById('selected-zone-height').value = height !== null ? height : '';
        
        document.getElementById('selected-zone-porosity').textContent = porosity !== null ? (porosity * 100).toFixed(0) + ' %' : '-';
    }} else {{
        // Useampi alue valittu
        document.getElementById('selected-zone-id').textContent = selectedZones.size + ' aluetta';
        document.getElementById('selected-zone-type').textContent = 'Useita';
        
        // Laske yhteispinta-ala
        let totalArea = 0;
        selectedZones.forEach(id => {{
            const zone = zones.find(z => z.id === id);
            if (zone) totalArea += zone.area_m2;
        }});
        document.getElementById('selected-zone-area').textContent = totalArea.toFixed(0) + ' m²';
        document.getElementById('selected-zone-lai').value = '';
        document.getElementById('selected-zone-lai-winter').value = '';
        document.getElementById('selected-zone-height').value = '';
        document.getElementById('selected-zone-porosity').textContent = '-';
    }}
}}

function updateZoneLAI(value) {{
    const lai = parseFloat(value);
    selectedZones.forEach(zoneId => {{
        const zone = zones.find(z => z.id === zoneId);
        if (zone) {{
            zone.custom_LAI = isNaN(lai) ? undefined : lai;
        }}
    }});
    updateSelectedZoneInfo();
}}

function updateZoneLAIWinter(value) {{
    const lai = parseFloat(value);
    selectedZones.forEach(zoneId => {{
        const zone = zones.find(z => z.id === zoneId);
        if (zone) {{
            zone.custom_LAI_winter = isNaN(lai) ? undefined : lai;
        }}
    }});
}}

function updateZoneHeight(value) {{
    const height = parseFloat(value);
    selectedZones.forEach(zoneId => {{
        const zone = zones.find(z => z.id === zoneId);
        if (zone) {{
            zone.custom_height = isNaN(height) ? undefined : height;
        }}
    }});
    updateSelectedZoneInfo();
}}

function renderMap() {{
    // Renderöi alueet
    const zonesLayer = document.getElementById('zones-layer');
    zonesLayer.innerHTML = '';
    
    zones.forEach(zone => {{
        const typeConfig = zoneTypes[zone.zone_type] || zoneTypes.unknown;
        const isSelected = selectedZones.has(zone.id);
        
        const points = zone.vertices.map(v => v.join(',')).join(' ');
        const polygon = document.createElementNS('http://www.w3.org/2000/svg', 'polygon');
        polygon.setAttribute('points', points);
        polygon.setAttribute('fill', typeConfig.color);
        polygon.setAttribute('fill-opacity', isSelected ? '0.8' : '0.4');
        polygon.setAttribute('stroke', isSelected ? '#e94560' : typeConfig.color);
        polygon.setAttribute('stroke-width', isSelected ? '3' : '1');
        polygon.setAttribute('cursor', 'pointer');
        polygon.dataset.id = zone.id;
        polygon.dataset.name = `${{zone.id}}: ${{typeConfig.name}}`;
        polygon.onclick = (e) => {{
            e.stopPropagation();
            if (drawingMode === 'delete') return;  // Delete-moodi käsitellään erikseen
            selectZone(zone.id, e.ctrlKey || e.metaKey);
        }};
        polygon.onmouseenter = (e) => showTooltip(e, `${{zone.id}}: ${{typeConfig.name}} (${{zone.area_m2}} m²)`);
        polygon.onmouseleave = hideTooltip;
        zonesLayer.appendChild(polygon);
    }});
    
    // Renderöi tiet
    const roadsLayer = document.getElementById('roads-layer');
    roadsLayer.innerHTML = '';
    
    roads.forEach(road => {{
        if (!road.vertices) return;
        const points = road.vertices.map(v => v.join(',')).join(' ');
        const polygon = document.createElementNS('http://www.w3.org/2000/svg', 'polygon');
        polygon.setAttribute('points', points);
        polygon.setAttribute('fill', '#555555');
        polygon.setAttribute('fill-opacity', '0.9');
        polygon.setAttribute('stroke', '#333333');
        polygon.setAttribute('stroke-width', '1');
        polygon.onmouseenter = (e) => showTooltip(e, `${{road.name || road.id}}`);
        polygon.onmouseleave = hideTooltip;
        roadsLayer.appendChild(polygon);
    }});
    
    // Renderöi rakennukset
    const buildingsLayer = document.getElementById('buildings-layer');
    buildingsLayer.innerHTML = '';
    
    obstacles.forEach(obs => {{
        const obsType = obs.type || 'building';
        
        if (obsType === 'tree' || obsType === 'tree_zone' || obsType === 'vegetation_zone') {{
            // Kasvillisuus
            if (obs.vertices) {{
                const points = obs.vertices.map(v => v.join(',')).join(' ');
                const polygon = document.createElementNS('http://www.w3.org/2000/svg', 'polygon');
                polygon.setAttribute('points', points);
                polygon.dataset.id = obs.id || '';
                polygon.dataset.name = obs.name || obs.id || 'Kasvillisuus';
                
                if (obsType === 'tree_zone') {{
                    polygon.setAttribute('fill', '#228B22');
                    polygon.setAttribute('fill-opacity', '0.6');
                    polygon.setAttribute('stroke', '#145214');
                }} else if (obsType === 'vegetation_zone') {{
                    const vegType = obs.vegetation_type || 'grass';
                    const colors = {{
                        'grass': '#90EE90', 'farmland': '#FFE082', 
                        'meadow': '#9ACD32', 'park': '#98FB98'
                    }};
                    polygon.setAttribute('fill', colors[vegType] || '#90EE90');
                    polygon.setAttribute('fill-opacity', '0.5');
                    polygon.setAttribute('stroke', '#228B22');
                }}
                polygon.setAttribute('stroke-width', '1');
                polygon.setAttribute('stroke-dasharray', '4,2');
                buildingsLayer.appendChild(polygon);
            }}
        }} else if (obsType === 'water_zone') {{
            // Vesialue
            if (obs.vertices) {{
                const points = obs.vertices.map(v => v.join(',')).join(' ');
                const polygon = document.createElementNS('http://www.w3.org/2000/svg', 'polygon');
                polygon.setAttribute('points', points);
                polygon.dataset.id = obs.id || '';
                polygon.dataset.name = obs.name || obs.id || 'Vesialue';
                
                const waterType = obs.water_type || 'water';
                const colors = {{
                    'water': '#4169E1', 'lake': '#4682B4', 
                    'pond': '#87CEEB', 'river': '#1E90FF', 'reservoir': '#5F9EA0'
                }};
                polygon.setAttribute('fill', colors[waterType] || '#4169E1');
                polygon.setAttribute('fill-opacity', '0.6');
                polygon.setAttribute('stroke', '#000080');
                polygon.setAttribute('stroke-width', '1.5');
                buildingsLayer.appendChild(polygon);
            }}
        }} else {{
            // Rakennus
            let points;
            if (obs.vertices) {{
                points = obs.vertices.map(v => v.join(',')).join(' ');
            }} else if (obs.x_min !== undefined) {{
                const x1 = obs.x_min, y1 = obs.y_min;
                const x2 = obs.x_max, y2 = obs.y_max;
                points = `${{x1}},${{y1}} ${{x2}},${{y1}} ${{x2}},${{y2}} ${{x1}},${{y2}}`;
            }} else {{
                return;
            }}
            
            const polygon = document.createElementNS('http://www.w3.org/2000/svg', 'polygon');
            polygon.setAttribute('points', points);
            polygon.setAttribute('fill', '#4a4a4a');
            polygon.setAttribute('stroke', '#222222');
            polygon.setAttribute('stroke-width', '1');
            polygon.dataset.id = obs.id || '';
            polygon.dataset.name = obs.name || obs.id || 'Rakennus';
            polygon.onmouseenter = (e) => showTooltip(e, obs.name || obs.id || 'Rakennus');
            polygon.onmouseleave = hideTooltip;
            buildingsLayer.appendChild(polygon);
        }}
    }});
    
    // Renderöi labelit
    const labelsLayer = document.getElementById('labels-layer');
    labelsLayer.innerHTML = '';
    
    zones.forEach(zone => {{
        if (!zone.center) return;
        const text = document.createElementNS('http://www.w3.org/2000/svg', 'text');
        text.setAttribute('x', zone.center[0]);
        text.setAttribute('y', zone.center[1]);
        text.setAttribute('text-anchor', 'middle');
        text.setAttribute('dominant-baseline', 'middle');
        text.setAttribute('fill', '#ffffff');
        text.setAttribute('font-size', '10');
        text.setAttribute('font-weight', 'bold');
        text.setAttribute('transform', `scale(1, -1) translate(0, ${{-2 * zone.center[1]}})`);
        text.setAttribute('pointer-events', 'none');
        text.textContent = zone.id;
        labelsLayer.appendChild(text);
    }});
}}

function showTooltip(e, text) {{
    const tooltip = document.getElementById('tooltip');
    tooltip.textContent = text;
    tooltip.style.display = 'block';
    tooltip.style.left = (e.clientX + 10) + 'px';
    tooltip.style.top = (e.clientY + 10) + 'px';
}}

function hideTooltip() {{
    document.getElementById('tooltip').style.display = 'none';
}}

function updateCounts() {{
    const buildings = obstacles.filter(o => 
        !['tree', 'tree_zone', 'vegetation_zone', 'water_zone'].includes(o.type || 'building')
    ).length;
    document.getElementById('building-count').textContent = buildings;
    document.getElementById('road-count').textContent = roads.length;
    document.getElementById('zone-count').textContent = zones.length;
}}

function selectAllUnknown() {{
    selectedZones = new Set(
        zones.filter(z => z.zone_type === 'unknown').map(z => z.id)
    );
    renderZoneList();
    renderMap();
}}

function resetZones() {{
    if (confirm('Palauta kaikki alueet alkuperäisiin asetuksiin?')) {{
        zones = JSON.parse(JSON.stringify(originalZones));
        selectedZones = new Set();
        renderZoneList();
        renderMap();
    }}
}}

function exportGeometry() {{
    // Luo uusi geometria muokatuilla alueilla
    // Lisätään LAI_2D, LAI_2D_winter ja height arvot jokaiselle alueelle
    const exportZones = zones.map(zone => {{
        const typeConfig = zoneTypes[zone.zone_type] || zoneTypes.unknown;
        
        // Käytä custom-arvoja jos asetettu, muuten tyypin oletukset
        const lai = zone.custom_LAI !== undefined ? zone.custom_LAI : typeConfig.LAI;
        const laiWinter = zone.custom_LAI_winter !== undefined ? zone.custom_LAI_winter : typeConfig.LAI_winter;
        const height = zone.custom_height !== undefined ? zone.custom_height : typeConfig.height;
        
        // Laske porosity (Beer-Lambert, k=0.5)
        const porosity = lai > 0 ? Math.exp(-lai * 0.5) : null;
        
        return {{
            ...zone,
            vegetation_type: zone.zone_type,
            name: typeConfig.name,
            LAI_2D: lai,
            LAI_2D_winter: laiWinter,
            height: height,
            porosity: porosity !== null ? Math.round(porosity * 1000) / 1000 : null
        }};
    }});
    
    const exportData = {{
        zones: exportZones,
        roads: roads,
        timestamp: new Date().toISOString()
    }};
    
    // Lataa tiedosto
    const blob = new Blob([JSON.stringify(exportData, null, 2)], {{type: 'application/json'}});
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'zone_edits.json';
    a.click();
    URL.revokeObjectURL(url);
}}

// Zoom ja pan
let viewBox = {{x: 0, y: 0, w: domainWidth, h: domainHeight}};
let isPanning = false;
let startPoint = {{x: 0, y: 0}};

const svg = document.getElementById('map-svg');

svg.addEventListener('mousedown', (e) => {{
    if (e.target === svg || e.target.tagName === 'rect') {{
        isPanning = true;
        startPoint = {{x: e.clientX, y: e.clientY}};
    }}
}});

svg.addEventListener('mousemove', (e) => {{
    if (!isPanning) return;
    
    const dx = (e.clientX - startPoint.x) * viewBox.w / svg.clientWidth;
    const dy = (e.clientY - startPoint.y) * viewBox.h / svg.clientHeight;
    
    viewBox.x -= dx;
    viewBox.y += dy;  // Y käännetty
    
    startPoint = {{x: e.clientX, y: e.clientY}};
    updateViewBox();
}});

svg.addEventListener('mouseup', () => {{ isPanning = false; }});
svg.addEventListener('mouseleave', () => {{ isPanning = false; }});

svg.addEventListener('wheel', (e) => {{
    e.preventDefault();
    const scale = e.deltaY > 0 ? 1.1 : 0.9;
    
    const rect = svg.getBoundingClientRect();
    const mx = (e.clientX - rect.left) / rect.width;
    const my = (e.clientY - rect.top) / rect.height;
    
    const newW = viewBox.w * scale;
    const newH = viewBox.h * scale;
    
    viewBox.x += (viewBox.w - newW) * mx;
    viewBox.y += (viewBox.h - newH) * (1 - my);
    viewBox.w = newW;
    viewBox.h = newH;
    
    updateViewBox();
}});

function updateViewBox() {{
    svg.setAttribute('viewBox', `${{viewBox.x}} ${{viewBox.y}} ${{viewBox.w}} ${{viewBox.h}}`);
}}

function zoomIn() {{
    viewBox.x += viewBox.w * 0.1;
    viewBox.y += viewBox.h * 0.1;
    viewBox.w *= 0.8;
    viewBox.h *= 0.8;
    updateViewBox();
}}

function zoomOut() {{
    viewBox.x -= viewBox.w * 0.125;
    viewBox.y -= viewBox.h * 0.125;
    viewBox.w *= 1.25;
    viewBox.h *= 1.25;
    updateViewBox();
}}

function resetView() {{
    viewBox = {{x: 0, y: 0, w: domainWidth, h: domainHeight}};
    updateViewBox();
}}

// ============================================================================
// PIIRTOTYÖKALUT - Rakennusten ja alueiden lisääminen/poistaminen
// ============================================================================

let drawingMode = null;  // 'building', 'zone', 'delete' tai null
let drawingPoints = [];
let drawingGroup = null;
let newBuildings = [];  // Uudet rakennukset
let deletedObjects = new Set();  // Poistettujen objektien ID:t

function startDrawingBuilding() {{
    setDrawingMode('building');
    showDrawingStatus('Klikkaa kartalla rakennuksen nurkkia. Tupla-klikkaa lopettaaksesi.');
}}

function startDrawingZone() {{
    setDrawingMode('zone');
    showDrawingStatus('Klikkaa kartalla alueen nurkkia. Tupla-klikkaa lopettaaksesi.');
}}

function startDeleteMode() {{
    setDrawingMode('delete');
    showDrawingStatus('Klikkaa poistettavaa rakennusta tai aluetta.');
    enableDeleteMode();
}}

function setDrawingMode(mode) {{
    // Poista edellinen moodi
    cancelDrawing(false);
    
    drawingMode = mode;
    drawingPoints = [];
    
    // Päivitä painikkeiden tila
    document.querySelectorAll('.btn-tool').forEach(btn => btn.classList.remove('active'));
    if (mode === 'building') document.getElementById('btn-draw-building').classList.add('active');
    if (mode === 'zone') document.getElementById('btn-draw-zone').classList.add('active');
    if (mode === 'delete') document.getElementById('btn-delete').classList.add('active');
    
    // Näytä peruuta-painike
    document.getElementById('btn-cancel').style.display = mode ? 'block' : 'none';
    
    // Aseta kursori
    const mapWrapper = document.querySelector('.map-wrapper');
    mapWrapper.classList.remove('drawing-mode', 'delete-mode');
    if (mode === 'building' || mode === 'zone') mapWrapper.classList.add('drawing-mode');
    if (mode === 'delete') mapWrapper.classList.add('delete-mode');
    
    // Luo piirtoryhmä
    if (mode === 'building' || mode === 'zone') {{
        drawingGroup = document.createElementNS('http://www.w3.org/2000/svg', 'g');
        drawingGroup.id = 'drawing-group';
        svg.appendChild(drawingGroup);
    }}
}}

function cancelDrawing(hideStatus = true) {{
    drawingMode = null;
    drawingPoints = [];
    
    // Poista piirtoryhmä
    const group = document.getElementById('drawing-group');
    if (group) group.remove();
    
    // Poista aktiivisuus painikkeista
    document.querySelectorAll('.btn-tool').forEach(btn => btn.classList.remove('active'));
    document.getElementById('btn-cancel').style.display = 'none';
    
    // Poista kursorit
    const mapWrapper = document.querySelector('.map-wrapper');
    mapWrapper.classList.remove('drawing-mode', 'delete-mode');
    
    // Poista delete-moodin kuuntelijat
    disableDeleteMode();
    
    if (hideStatus) hideDrawingStatus();
}}

function showDrawingStatus(text) {{
    const statusDiv = document.getElementById('drawing-status');
    const statusText = document.getElementById('drawing-status-text');
    statusDiv.style.display = 'block';
    statusText.textContent = text;
}}

function hideDrawingStatus() {{
    document.getElementById('drawing-status').style.display = 'none';
}}

// SVG klikkauskäsittelijä
svg.addEventListener('click', function(e) {{
    if (!drawingMode || drawingMode === 'delete') return;
    
    // Laske koordinaatit
    const pt = svg.createSVGPoint();
    pt.x = e.clientX;
    pt.y = e.clientY;
    const svgP = pt.matrixTransform(svg.getScreenCTM().inverse());
    
    // Muunna y-koordinaatti (SVG:ssä y kasvaa alas, meillä ylös)
    const x = svgP.x;
    const y = domainHeight - svgP.y;
    
    drawingPoints.push([x, y]);
    updateDrawingPreview();
    
    showDrawingStatus(`${{drawingPoints.length}} pistettä. Tupla-klikkaa lopettaaksesi.`);
}});

// Tupla-klikkaus lopettaa piirron
svg.addEventListener('dblclick', function(e) {{
    if (!drawingMode || drawingMode === 'delete') return;
    if (drawingPoints.length < 3) {{
        alert('Tarvitaan vähintään 3 pistettä!');
        return;
    }}
    
    e.preventDefault();
    
    if (drawingMode === 'building') {{
        showBuildingModal();
    }} else if (drawingMode === 'zone') {{
        showZoneModal();
    }}
}});

function updateDrawingPreview() {{
    if (!drawingGroup) return;
    drawingGroup.innerHTML = '';
    
    // Piirrä pisteet
    drawingPoints.forEach((p, i) => {{
        const circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
        circle.setAttribute('cx', p[0]);
        circle.setAttribute('cy', domainHeight - p[1]);
        circle.setAttribute('r', 1.5 / (viewBox.w / domainWidth));
        circle.classList.add('drawing-point');
        drawingGroup.appendChild(circle);
    }});
    
    // Piirrä viivat
    if (drawingPoints.length > 1) {{
        let pathD = `M ${{drawingPoints[0][0]}} ${{domainHeight - drawingPoints[0][1]}}`;
        for (let i = 1; i < drawingPoints.length; i++) {{
            pathD += ` L ${{drawingPoints[i][0]}} ${{domainHeight - drawingPoints[i][1]}}`;
        }}
        pathD += ' Z';
        
        const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        path.setAttribute('d', pathD);
        path.classList.add('drawing-polygon');
        drawingGroup.appendChild(path);
    }}
}}

// ============================================================================
// MODAALIT
// ============================================================================

function showBuildingModal() {{
    const modal = document.createElement('div');
    modal.className = 'modal-overlay';
    modal.id = 'building-modal';
    modal.innerHTML = `
        <div class="modal">
            <h3>🏠 Uusi rakennus</h3>
            <div class="modal-field">
                <label>Rakennuksen nimi:</label>
                <input type="text" id="building-name" placeholder="esim. Uusi kerrostalo" value="">
            </div>
            <div class="modal-field">
                <label>Korkeus (m):</label>
                <input type="number" id="building-height" value="10" min="1" max="200" step="0.5">
            </div>
            <div class="modal-field">
                <label>Tyyppi:</label>
                <select id="building-type">
                    <option value="building">Rakennus</option>
                    <option value="building_planned">Suunniteltu rakennus</option>
                </select>
            </div>
            <div class="modal-buttons">
                <button class="modal-btn-secondary" onclick="closeBuildingModal()">Peruuta</button>
                <button class="modal-btn-primary" onclick="saveBuildingFromModal()">Tallenna</button>
            </div>
        </div>
    `;
    document.body.appendChild(modal);
    document.getElementById('building-name').focus();
}}

function closeBuildingModal() {{
    const modal = document.getElementById('building-modal');
    if (modal) modal.remove();
    cancelDrawing();
}}

function saveBuildingFromModal() {{
    const name = document.getElementById('building-name').value || 'Uusi rakennus';
    const height = parseFloat(document.getElementById('building-height').value) || 10;
    const type = document.getElementById('building-type').value;
    
    // Luo uusi rakennus
    const newId = 'NEW_' + (newBuildings.length + 1);
    const building = {{
        id: newId,
        type: type,
        name: name,
        vertices: drawingPoints.map(p => [Math.round(p[0] * 10) / 10, Math.round(p[1] * 10) / 10]),
        height: height,
        is_solid: true,
        source: 'zone_editor_drawn'
    }};
    
    newBuildings.push(building);
    obstacles.push(building);
    
    closeBuildingModal();
    renderMap();
    updateCounts();
    
    showDrawingStatus(`Rakennus "${{name}}" lisätty! (${{drawingPoints.length}} kulmaa, ${{height}}m)`);
    setTimeout(hideDrawingStatus, 3000);
}}

function showZoneModal() {{
    const modal = document.createElement('div');
    modal.className = 'modal-overlay';
    modal.id = 'zone-modal';
    
    // Luo tyyppivalikko
    let typeOptions = '';
    for (const [key, config] of Object.entries(zoneTypes)) {{
        if (config.LAI !== null && config.LAI !== undefined) {{
            typeOptions += `<option value="${{key}}">${{config.name}} (LAI ${{config.LAI}})</option>`;
        }}
    }}
    
    modal.innerHTML = `
        <div class="modal">
            <h3>🌳 Uusi kasvillisuusalue</h3>
            <div class="modal-field">
                <label>Alueen tyyppi:</label>
                <select id="zone-type-select">
                    ${{typeOptions}}
                </select>
            </div>
            <div class="modal-field">
                <label>Korkeus (m) - voi muokata:</label>
                <input type="number" id="zone-height" value="10" min="0" max="50" step="0.5">
            </div>
            <div class="modal-buttons">
                <button class="modal-btn-secondary" onclick="closeZoneModal()">Peruuta</button>
                <button class="modal-btn-primary" onclick="saveZoneFromModal()">Tallenna</button>
            </div>
        </div>
    `;
    document.body.appendChild(modal);
    
    // Päivitä korkeus kun tyyppi vaihtuu
    document.getElementById('zone-type-select').addEventListener('change', function() {{
        const type = this.value;
        const config = zoneTypes[type];
        if (config && config.height) {{
            document.getElementById('zone-height').value = config.height;
        }}
    }});
    // Triggeröi kerran
    document.getElementById('zone-type-select').dispatchEvent(new Event('change'));
}}

function closeZoneModal() {{
    const modal = document.getElementById('zone-modal');
    if (modal) modal.remove();
    cancelDrawing();
}}

function saveZoneFromModal() {{
    const zoneType = document.getElementById('zone-type-select').value;
    const height = parseFloat(document.getElementById('zone-height').value) || 10;
    const config = zoneTypes[zoneType] || {{}};
    
    // Laske pinta-ala
    const vertices = drawingPoints.map(p => [Math.round(p[0] * 10) / 10, Math.round(p[1] * 10) / 10]);
    const area = calculatePolygonArea(vertices);
    
    // Luo uusi alue
    const newId = 'ZONE_' + (zones.length + 1);
    const zone = {{
        id: newId,
        type: 'editable_zone',
        zone_type: zoneType,
        vertices: vertices,
        area_m2: Math.round(area * 10) / 10,
        center: calculateCenter(vertices),
        source: 'zone_editor_drawn'
    }};
    
    zones.push(zone);
    
    closeZoneModal();
    renderMap();
    renderZoneList();
    updateCounts();
    
    showDrawingStatus(`Alue "${{config.name || zoneType}}" lisätty! (${{Math.round(area)}} m²)`);
    setTimeout(hideDrawingStatus, 3000);
}}

function calculatePolygonArea(vertices) {{
    let area = 0;
    const n = vertices.length;
    for (let i = 0; i < n; i++) {{
        const j = (i + 1) % n;
        area += vertices[i][0] * vertices[j][1];
        area -= vertices[j][0] * vertices[i][1];
    }}
    return Math.abs(area) / 2;
}}

function calculateCenter(vertices) {{
    const cx = vertices.reduce((sum, v) => sum + v[0], 0) / vertices.length;
    const cy = vertices.reduce((sum, v) => sum + v[1], 0) / vertices.length;
    return [Math.round(cx * 10) / 10, Math.round(cy * 10) / 10];
}}

// ============================================================================
// POISTOTOIMINTO
// ============================================================================

function enableDeleteMode() {{
    // Lisää delete-kuuntelijat rakennuksiin
    document.querySelectorAll('#buildings-layer polygon, #buildings-layer rect').forEach(el => {{
        el.classList.add('deletable');
        el.addEventListener('click', handleDeleteClick);
    }});
    
    // Lisää delete-kuuntelijat vyöhykkeisiin
    document.querySelectorAll('#zones-layer polygon').forEach(el => {{
        el.classList.add('deletable');
        el.addEventListener('click', handleDeleteClick);
    }});
}}

function disableDeleteMode() {{
    document.querySelectorAll('.deletable').forEach(el => {{
        el.classList.remove('deletable');
        el.removeEventListener('click', handleDeleteClick);
    }});
}}

function handleDeleteClick(e) {{
    e.stopPropagation();
    
    const objectId = e.target.dataset.id;
    if (!objectId) return;
    
    const objectName = e.target.dataset.name || objectId;
    
    if (confirm(`Poistetaanko "${{objectName}}"?`)) {{
        deleteObject(objectId);
    }}
}}

function deleteObject(objectId) {{
    // Poista rakennuksista
    const buildingIndex = obstacles.findIndex(o => o.id === objectId);
    if (buildingIndex >= 0) {{
        obstacles.splice(buildingIndex, 1);
        deletedObjects.add(objectId);
    }}
    
    // Poista vyöhykkeistä
    const zoneIndex = zones.findIndex(z => z.id === objectId);
    if (zoneIndex >= 0) {{
        zones.splice(zoneIndex, 1);
        deletedObjects.add(objectId);
    }}
    
    cancelDrawing();
    renderMap();
    renderZoneList();
    updateCounts();
    
    showDrawingStatus(`Objekti "${{objectId}}" poistettu.`);
    setTimeout(hideDrawingStatus, 3000);
}}

// ============================================================================
// PÄIVITETTY EXPORT - sisältää uudet rakennukset ja poistetut
// ============================================================================

const originalExportGeometry = exportGeometry;
exportGeometry = function() {{
    const output = {{
        name: '{name}',
        width: domainWidth,
        height: domainHeight,
        obstacles: obstacles.filter(o => !deletedObjects.has(o.id)),
        roads: roads,
        editable_zones: zones,
        new_buildings: newBuildings,
        deleted_objects: Array.from(deletedObjects),
        edited_at: new Date().toISOString()
    }};
    
    const json = JSON.stringify(output, null, 2);
    const blob = new Blob([json], {{type: 'application/json'}});
    const url = URL.createObjectURL(blob);
    
    const a = document.createElement('a');
    a.href = url;
    a.download = 'zone_edited.json';
    a.click();
    
    URL.revokeObjectURL(url);
}};
</script>
</body>
</html>
'''
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html_content)
    
    print(f"HTML-editori luotu: {output_path}")
    return output_path


def apply_zone_edits(geometry: Dict, edits_file: str, season: str = 'summer') -> Dict:
    """
    Soveltaa editorista viedyt muutokset geometriaan.
    
    Args:
        geometry: Alkuperäinen geometria
        edits_file: Polku zone_edits.json-tiedostoon
        season: 'summer' (oletus) tai 'winter' - kumman LAI-arvon käyttää
    
    Returns:
        Päivitetty geometria
    """
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    
    with open(edits_file, 'r', encoding='utf-8') as f:
        edits = json.load(f)
    
    use_winter = season.lower() == 'winter'
    if use_winter:
        print("Käytetään talvi-LAI arvoja")
    
    # Kerää rakennuspolygonit leikkausta varten
    building_polys = []
    for obs in geometry.get('obstacles', []):
        if obs.get('type') in ['polygon_building', 'building', 'polygon']:
            try:
                verts = obs.get('vertices', [])
                if len(verts) >= 3:
                    poly = Polygon(verts)
                    if poly.is_valid and poly.area > 0:
                        # Pieni puskuri välttämään reunaongelmia
                        building_polys.append(poly.buffer(0.5))
            except:
                pass
    
    # Yhdistä rakennukset yhdeksi leikkausalueeksi
    if building_polys:
        buildings_union = unary_union(building_polys)
        print(f"Leikataan kasvillisuusalueista {len(building_polys)} rakennusta")
    else:
        buildings_union = None
    
    # Päivitä tai lisää muokattavat alueet
    # Huom: zone_edited.json voi sisältää 'editable_zones' tai 'zones'
    edited_zones = edits.get('editable_zones', edits.get('zones', []))
    edited_roads = edits.get('roads', [])
    deleted_objects = set(edits.get('deleted_objects', []))
    new_buildings = edits.get('new_buildings', [])
    
    print(f"  Muokattuja alueita: {len(edited_zones)}")
    print(f"  Teitä: {len(edited_roads)}")
    print(f"  Poistettuja objekteja: {len(deleted_objects)}")
    print(f"  Uusia rakennuksia: {len(new_buildings)}")
    
    # Poista merkityt objektit alkuperäisestä geometriasta
    if deleted_objects:
        original_count = len(geometry.get('obstacles', []))
        geometry['obstacles'] = [
            obs for obs in geometry.get('obstacles', [])
            if obs.get('id') not in deleted_objects
        ]
        removed = original_count - len(geometry['obstacles'])
        print(f"  Poistettu {removed} objektia")
    
    # Muunna muokatut alueet vegetation_zone tai muiksi tyypeiksi
    new_obstacles = []
    
    for zone in edited_zones:
        zone_type = zone.get('zone_type', 'unknown')
        
        # Ohita tuntemattomat, päällystetyt ja vesialueet (ei vaikuta simulaatioon)
        if zone_type in ['unknown', 'paved', 'parking', 'water', 'lake', 'pond', 'river', 'reservoir']:
            continue
        
        type_config = ZONE_TYPES.get(zone_type, {})
        
        # Valitse LAI vuodenajan mukaan
        if use_winter:
            # Talvi: käytä LAI_winter, tai zone_edits.json:sta custom_LAI_winter
            lai = zone.get('LAI_winter') if zone.get('LAI_winter') is not None else type_config.get('LAI_winter')
            # Fallback kesäarvoon jos talviarvoa ei ole
            if lai is None:
                lai = zone.get('LAI') if zone.get('LAI') is not None else type_config.get('LAI')
        else:
            # Kesä: käytä LAI
            lai = zone.get('LAI') if zone.get('LAI') is not None else type_config.get('LAI')
        
        # Custom-arvojen tuki (editorista muokatut)
        if zone.get('custom_LAI') is not None:
            lai = zone.get('custom_LAI')
        
        lai_winter = zone.get('LAI_winter') if zone.get('LAI_winter') is not None else type_config.get('LAI_winter')
        height = zone.get('height') if zone.get('height') is not None else type_config.get('height', 0.5)
        
        # Custom height
        if zone.get('custom_height') is not None:
            height = zone.get('custom_height')
        
        # Ohita jos ei LAI:ta (ei vaikuta simulaatioon)
        if lai is None or lai <= 0:
            continue
        
        # Laske porosity LAI:sta (k=0.5 vastaa obstacles.py:tä)
        import math
        porosity = math.exp(-0.5 * lai)
        porosity = max(0.01, min(0.99, porosity))
        
        # Laske drag_coefficient LAI:sta (sama kaava kuin obstacles.py)
        # drag = Cd_leaf * LAI * (1 - porosity), missä Cd_leaf ≈ 0.2
        drag_coefficient = 0.2 * lai * (1.0 - porosity)
        drag_coefficient = max(0.01, min(2.0, drag_coefficient))
        
        # Hae alkuperäiset vertices
        zone_vertices = zone['vertices']
        
        # Leikkaa rakennukset pois kasvillisuusalueesta
        if buildings_union is not None:
            try:
                zone_poly = Polygon(zone_vertices)
                
                # Korjaa mahdollinen invalidi polygoni
                if not zone_poly.is_valid:
                    zone_poly = zone_poly.buffer(0)
                
                if zone_poly.is_valid and not zone_poly.is_empty and zone_poly.area > 0:
                    # Leikkaa rakennukset pois
                    clipped = zone_poly.difference(buildings_union)
                    
                    if clipped.is_empty:
                        continue  # Koko alue oli rakennusten alla
                    
                    # Käsittele tulos (voi olla MultiPolygon)
                    if clipped.geom_type == 'Polygon':
                        polys_to_add = [clipped]
                    elif clipped.geom_type == 'MultiPolygon':
                        polys_to_add = list(clipped.geoms)
                    else:
                        continue
                    
                    # Luo obstacle jokaiselle osalle
                    for i, poly in enumerate(polys_to_add):
                        if poly.area < 1.0:  # Ohita pienet palat
                            continue
                        
                        # Muunna coordinates listaksi (exterior)
                        exterior_coords = list(poly.exterior.coords)[:-1]
                        
                        # Käsittele reiät (interiors) - rakennukset jotka jäävät sisään
                        holes = []
                        for interior in poly.interiors:
                            hole_coords = [[c[0], c[1]] for c in list(interior.coords)[:-1]]
                            if len(hole_coords) >= 3:
                                holes.append(hole_coords)
                        
                        obs_id = zone['id'] if i == 0 else f"{zone['id']}_{i}"
                        
                        new_obs = {
                            'id': obs_id,
                            'type': 'vegetation_zone',
                            'vegetation_type': zone_type,
                            'name': type_config.get('name', zone_type),
                            'vertices': _smooth_and_format_vertices(exterior_coords),
                            'LAI': lai,
                            'LAI_winter': lai_winter,
                            'porosity': round(porosity, 4),
                            'drag_coefficient': round(drag_coefficient, 4),
                            'height': height,
                            'is_solid': False,
                            'source': 'zone_editor',
                            'season': season
                        }
                        
                        # Lisää reiät jos niitä on
                        if holes:
                            new_obs['holes'] = holes
                        
                        new_obstacles.append(new_obs)
                    continue  # Siirrytään seuraavaan alueeseen
            except Exception as e:
                # Jos leikkaus epäonnistuu, käytä alkuperäistä
                pass
        
        # Ei leikkausta tai leikkaus epäonnistui - käytä alkuperäistä
        new_obs = {
            'id': zone['id'],
            'type': 'vegetation_zone',
            'vegetation_type': zone_type,
            'name': type_config.get('name', zone_type),
            'vertices': _smooth_and_format_vertices(zone_vertices),
            'LAI': lai,
            'LAI_winter': lai_winter,
            'porosity': round(porosity, 4),
            'drag_coefficient': round(drag_coefficient, 4),
            'height': height,
            'is_solid': False,
            'source': 'zone_editor',
            'season': season
        }
        new_obstacles.append(new_obs)
    
    # Lisää tiet geometriaan
    geometry['roads'] = edited_roads
    
    # Lisää uudet rakennukset
    if new_buildings:
        for bldg in new_buildings:
            new_bldg = {
                'id': bldg.get('id', f"NEW_{len(geometry['obstacles'])}"),
                'type': 'polygon_building',
                'vertices': bldg.get('vertices', []),
                'height': bldg.get('height', 10),
                'name': bldg.get('name', ''),
                'source': 'zone_editor'
            }
            geometry['obstacles'].append(new_bldg)
        print(f"  Lisätty {len(new_buildings)} uutta rakennusta")
    
    # Leikkaa rakennukset myös ALKUPERÄISISTÄ tree_zone ja vegetation_zone alueista
    if buildings_union is not None:
        updated_obstacles = []
        clipped_count = 0
        
        for obs in geometry['obstacles']:
            obs_type = obs.get('type', '')
            
            # Leikkaa vain kasvillisuus- ja vesialueet (ei rakennuksia)
            if obs_type in ['tree_zone', 'vegetation_zone', 'water_zone']:
                try:
                    verts = obs.get('vertices', [])
                    if len(verts) >= 3:
                        obs_poly = Polygon(verts)
                        
                        # Korjaa mahdollinen invalidi polygoni
                        if not obs_poly.is_valid:
                            obs_poly = obs_poly.buffer(0)
                        
                        if obs_poly.is_valid and not obs_poly.is_empty and obs_poly.area > 0:
                            clipped = obs_poly.difference(buildings_union)
                            
                            if clipped.is_empty:
                                continue  # Koko alue oli rakennusten alla
                            
                            if clipped.geom_type == 'Polygon':
                                polys = [clipped]
                            elif clipped.geom_type == 'MultiPolygon':
                                polys = list(clipped.geoms)
                            else:
                                updated_obstacles.append(obs)
                                continue
                            
                            for i, poly in enumerate(polys):
                                if poly.area < 1.0:
                                    continue
                                exterior_coords = list(poly.exterior.coords)[:-1]
                                
                                # Käsittele reiät
                                holes = []
                                for interior in poly.interiors:
                                    hole_coords = [[c[0], c[1]] for c in list(interior.coords)[:-1]]
                                    if len(hole_coords) >= 3:
                                        holes.append(hole_coords)
                                
                                new_obs = obs.copy()
                                new_obs['vertices'] = [[c[0], c[1]] for c in exterior_coords]
                                if holes:
                                    new_obs['holes'] = holes
                                if i > 0:
                                    new_obs['id'] = f"{obs['id']}_{i}"
                                updated_obstacles.append(new_obs)
                            clipped_count += 1
                            continue
                except:
                    pass
            
            # Muu este (rakennus tms.) - säilytä sellaisenaan
            updated_obstacles.append(obs)
        
        geometry['obstacles'] = updated_obstacles
        if clipped_count > 0:
            print(f"Leikattiin {clipped_count} alkuperäistä kasvillisuusaluetta")
    
    # Lisää uudet kasvillisuusalueet esteisiin
    geometry['obstacles'].extend(new_obstacles)
    
    # Päivitä metadata
    if 'metadata' not in geometry:
        geometry['metadata'] = {}
    geometry['metadata']['zone_editor_applied'] = True
    geometry['metadata']['zones_added'] = len(new_obstacles)
    
    print(f"Sovellettiin {len(new_obstacles)} aluetta geometriaan")
    return geometry


def main():
    parser = argparse.ArgumentParser(
        description='Geometrian alueeditori - tunnistaa ja muokkaa rakennusten välisiä alueita',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Esimerkkejä:
  # Luo HTML-editori olemassaolevalle geometrialle
  python zone_editor.py geometry.json --output editor.html
  
  # Hae tiet OSM:stä ja tunnista välialueet
  python zone_editor.py geometry.json --fetch-roads --identify-zones --output editor.html
  
  # Sovella muokatut alueet (kesä, oletus)
  python zone_editor.py geometry.json --apply-edits zone_edits.json --output updated_geometry.json
  
  # Sovella muokatut alueet (talvi)
  python zone_editor.py geometry.json --apply-edits zone_edits.json --winter --output winter_geometry.json
        '''
    )
    
    parser.add_argument('geometry', help='JSON-geometriatiedosto')
    parser.add_argument('--output', '-o', required=True,
                        help='Tulostiedosto (HTML tai JSON)')
    parser.add_argument('--fetch-roads', action='store_true',
                        help='Hae tiet OpenStreetMapista')
    parser.add_argument('--identify-zones', action='store_true',
                        help='Tunnista rakennusten väliset alueet')
    parser.add_argument('--mml-api-key', type=str,
                        help='MML API-avain (käytä oikeita tonttirajoja Voronoi-jaon sijaan)')
    parser.add_argument('--lat', type=float,
                        help='Keskipisteen latitudi (WGS84) - MML-hakua varten')
    parser.add_argument('--lon', type=float,
                        help='Keskipisteen longitudi (WGS84) - MML-hakua varten')
    parser.add_argument('--apply-edits', type=str,
                        help='Sovella muokatut alueet (zone_edits.json)')
    parser.add_argument('--winter', action='store_true',
                        help='Käytä talvi-LAI arvoja (oletus: kesä)')
    parser.add_argument('--min-zone-area', type=float, default=25.0,
                        help='Minimialue tunnistukselle (m², oletus: 25)')
    parser.add_argument('--resolution', type=float, default=1.0,
                        help='Aluetunnistuksen resoluutio (m, oletus: 1.0, pienempi=tarkempi)')
    
    args = parser.parse_args()
    
    # Lataa geometria
    geom_path = Path(args.geometry)
    if not geom_path.exists():
        print(f"VIRHE: Tiedostoa ei löydy: {geom_path}")
        sys.exit(1)
    
    print(f"Ladataan: {geom_path}")
    geometry = load_geometry(str(geom_path))
    
    print(f"  Alue: {geometry['domain']['width']:.0f} × {geometry['domain']['height']:.0f} m")
    print(f"  Esteitä: {len(geometry.get('obstacles', []))}")
    
    # Sovella muokatut alueet
    if args.apply_edits:
        season = 'winter' if args.winter else 'summer'
        print(f"\nSovelletaan muokatut alueet: {args.apply_edits}")
        print(f"  Vuodenaika: {season}")
        geometry = apply_zone_edits(geometry, args.apply_edits, season=season)
        save_geometry(geometry, args.output)
        return
    
    # Hae tiet
    roads = geometry.get('roads', [])
    if args.fetch_roads:
        meta = geometry.get('metadata', {})
        lat = meta.get('center_lat')
        lon = meta.get('center_lon')
        
        # Käytä domain-kokoa säteenä (ei metadata.radius_m joka voi olla pienempi)
        domain_width = geometry['domain']['width']
        domain_height = geometry['domain']['height']
        radius = max(domain_width, domain_height) / 2 + 50  # +50m marginaali
        
        if lat and lon:
            print(f"\nHaetaan teitä OSM:stä (säde {radius:.0f}m)...")
            roads = fetch_roads_from_osm(lat, lon, radius)
            geometry['roads'] = roads
        else:
            print("VAROITUS: Geometriasta puuttuu koordinaatit (center_lat/lon)")
    
    # Tunnista alueet
    zones = geometry.get('editable_zones', [])
    if args.identify_zones:
        # Hae koordinaatit: komentoriviparametrit > JSON päätaso > metadata
        lat = args.lat or geometry.get('center_lat')
        lon = args.lon or geometry.get('center_lon')
        
        # Fallback: metadata-kenttä (vanhemmat tiedostot)
        if not lat or not lon:
            metadata = geometry.get('metadata', {})
            lat = lat or metadata.get('center_lat')
            lon = lon or metadata.get('center_lon')
        
        # MML API-avain: komentoriviparametri tai ympäristömuuttuja
        import os
        mml_key = args.mml_api_key or os.environ.get('MML_API_KEY')
        
        # Käytä MML-rajoja jos API-avain on saatavilla
        if mml_key and lat and lon:
            print(f"\nHaetaan oikeat tonttirajat MML:stä...")
            zones = identify_zones_from_cadastre(
                geometry,
                center_lat=lat,
                center_lon=lon,
                mml_api_key=mml_key,
                min_zone_area=args.min_zone_area
            )
        else:
            if not mml_key:
                print("INFO: MML API-avain ei saatavilla - käytetään Voronoi-jakoa")
                print("  (Aseta MML_API_KEY ympäristömuuttuja tai anna --mml-api-key)")
            elif not (lat and lon):
                print("VAROITUS: Koordinaatit puuttuvat - käytetään Voronoi-jakoa")
                print("  (Anna --lat ja --lon parametrit tai lisää center_lat/center_lon JSON:iin)")
            print(f"\nTunnistetaan tontit Voronoi-jaolla...")
            zones = identify_zones(
                geometry,
                resolution=args.resolution,
                min_zone_area=args.min_zone_area
            )
        geometry['editable_zones'] = zones
    
    # Luo HTML-editori
    if args.output.endswith('.html'):
        print(f"\nLuodaan HTML-editori...")
        generate_html_editor(geometry, args.output, zones, roads)
    else:
        # Tallenna päivitetty geometria
        save_geometry(geometry, args.output)
    
    print("\nValmis!")


if __name__ == '__main__':
    main()
