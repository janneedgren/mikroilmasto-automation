#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Geometriatiedoston visualisointi.

Näyttää JSON-geometrian kuvana ilman simulaatiota.
Näyttää jokaisen esteen ID:n visualisoinnissa.

Käyttö:
    python view_geometry.py geometry.json
    python view_geometry.py geometry.json --output kuva.png
    python view_geometry.py geometry.json --no-show --output kuva.png
    python view_geometry.py geometry.json --ids              # Rakennusten ID:t
    python view_geometry.py geometry.json --ids-veg          # Kasvillisuuden ID:t
    python view_geometry.py geometry.json --ids-all          # Kaikkien ID:t
    python view_geometry.py geometry.json --ids --labels     # Näytä ID:t ja nimet
"""

import argparse
import json
import sys
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, Polygon, Circle, PathPatch
from matplotlib.path import Path as MplPath


def load_json(filepath):
    """Lataa JSON-tiedosto. Käsittelee myös NaN-arvot jotka eivät ole validia JSONia."""
    import re
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Korvaa NaN -> null (JSON-yhteensopiva)
    content = re.sub(r'\bNaN\b', 'null', content)
    
    return json.loads(content)


def _generate_id(obs_type: str, index: int) -> str:
    """Generoi ID jos sitä ei ole."""
    prefixes = {
        'building': 'B',
        'rotated_building': 'R',
        'polygon_building': 'P',
        'tree': 'T',
        'tree_zone': 'Z',
        'vegetation_zone': 'V',
        'water_zone': 'W'
    }
    prefix = prefixes.get(obs_type, 'X')
    return f"{prefix}{index:03d}"


def plot_geometry(data, title=None, show_grid=True, show_labels=False, show_ids=False, show_arrow=True,
                  show_ids_buildings=False, show_ids_vegetation=False):
    """
    Piirtää geometrian.
    
    Args:
        data: JSON-data dict
        title: Otsikko (oletus: tiedoston nimi)
        show_grid: Näytä ruudukko
        show_labels: Näytä rakennusten nimet
        show_ids: Näytä rakennusten ID:t (taaksepäin yhteensopiva)
        show_arrow: Näytä tuulinuoli
        show_ids_buildings: Näytä rakennusten ID:t
        show_ids_vegetation: Näytä kasvillisuuden/vesialueiden ID:t
    
    Returns:
        fig, ax
    """
    # Ratkaise ID-näkyvyys: --ids = rakennukset (taaksepäin yhteensopiva)
    ids_buildings = show_ids_buildings or show_ids
    ids_vegetation = show_ids_vegetation
    fig, ax = plt.subplots(figsize=(14, 10))
    
    # Alueen koko
    width = data['domain']['width']
    height = data['domain']['height']
    
    # Laskurit
    n_buildings = 0
    n_trees = 0
    n_rotated = 0
    n_polygons = 0
    n_tree_zones = 0
    n_vegetation_zones = 0
    n_water_zones = 0
    
    # Laskurit ID:iden generointiin
    type_counters = {
        'building': 1,
        'rotated_building': 1,
        'polygon_building': 1,
        'tree': 1,
        'tree_zone': 1,
        'vegetation_zone': 1,
        'water_zone': 1
    }
    
    # Piirra esteet
    for obs in data.get('obstacles', []):
        obs_type = obs.get('type', 'building')
        name = obs.get('name', '')
        
        # Hae tai generoi ID
        obs_id = obs.get('id', '')
        if not obs_id:
            obs_id = _generate_id(obs_type, type_counters.get(obs_type, 1))
            type_counters[obs_type] = type_counters.get(obs_type, 1) + 1
        
        if obs_type == 'building':
            rect = Rectangle(
                (obs['x_min'], obs['y_min']),
                obs['x_max'] - obs['x_min'],
                obs['y_max'] - obs['y_min'],
                facecolor='#4a4a4a',
                edgecolor='black',
                linewidth=1.2,
                alpha=0.85,
                zorder=10
            )
            ax.add_patch(rect)
            n_buildings += 1
            
            cx = (obs['x_min'] + obs['x_max']) / 2
            cy = (obs['y_min'] + obs['y_max']) / 2
            
            # Laske rakennuksen koko (pidempi sivu)
            bldg_width = obs['x_max'] - obs['x_min']
            bldg_height = obs['y_max'] - obs['y_min']
            bldg_size = max(bldg_width, bldg_height)
            
            # Näytä ID ja/tai nimi
            _add_label(ax, cx, cy, obs_id, name, ids_buildings, show_labels, building_size=bldg_size)
        
        elif obs_type == 'rotated_building':
            # Laske kulmat
            import numpy as np
            cx, cy = obs['x_center'], obs['y_center']
            w, h = obs['width'], obs['height']
            angle = np.radians(obs.get('angle', 0))
            
            cos_a, sin_a = np.cos(angle), np.sin(angle)
            hw, hh = w/2, h/2
            
            corners = []
            for dx, dy in [(-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)]:
                x = cx + dx * cos_a - dy * sin_a
                y = cy + dx * sin_a + dy * cos_a
                corners.append((x, y))
            
            poly = Polygon(corners, facecolor='#5a5a8a', edgecolor='black',
                          linewidth=1.2, alpha=0.85, zorder=10)
            ax.add_patch(poly)
            n_rotated += 1
            
            # Rakennuksen koko (pidempi sivu)
            bldg_size = max(w, h)
            
            # Näytä ID ja/tai nimi
            _add_label(ax, cx, cy, obs_id, name, ids_buildings, show_labels, building_size=bldg_size)
        
        elif obs_type == 'polygon_building':
            vertices = obs['vertices']
            poly = Polygon(vertices, facecolor='#6a6a6a', edgecolor='black',
                          linewidth=1.2, alpha=0.85, zorder=10)
            ax.add_patch(poly)
            n_polygons += 1
            
            import numpy as np
            xs = [v[0] for v in vertices]
            ys = [v[1] for v in vertices]
            cx = np.mean(xs)
            cy = np.mean(ys)
            
            # Laske rakennuksen koko (bounding boxin pidempi sivu)
            bldg_size = max(max(xs) - min(xs), max(ys) - min(ys))
            
            # Näytä ID ja/tai nimi
            _add_label(ax, cx, cy, obs_id, name, ids_buildings, show_labels, building_size=bldg_size)
        
        elif obs_type == 'tree':
            circle = Circle(
                (obs['x_center'], obs['y_center']),
                obs.get('radius', 4),
                facecolor='#228b22',
                edgecolor='#145214',
                linewidth=0.5,
                alpha=0.6
            )
            ax.add_patch(circle)
            n_trees += 1
            
            # Puille ei näytetä ID:tä (liian pieniä kohteita)
            # Näytetään vain nimi jos erikseen pyydetty
            if show_labels and name:
                _add_label(ax, obs['x_center'], obs['y_center'], 
                          '', name, False, True, color='darkgreen')
        
        elif obs_type == 'tree_zone':
            # Metsäalue - vihreä läpinäkyvä polygoni
            vertices = obs['vertices']
            porosity = obs.get('porosity', 0.4)
            holes = obs.get('holes', [])
            
            # Väri ja läpinäkyvyys huokoisuuden mukaan
            # Tiheämpi metsä (pieni porosity) = tummempi vihreä
            green_intensity = int(100 + porosity * 80)  # 100-180
            facecolor = f'#{20:02x}{green_intensity:02x}{20:02x}'
            alpha = 0.7 - porosity * 0.3  # 0.4-0.7
            
            # Jos on reikiä, käytä PathPatch
            if holes:
                # Rakenna Path reikien kanssa
                codes = [MplPath.MOVETO] + [MplPath.LINETO] * (len(vertices) - 1) + [MplPath.CLOSEPOLY]
                all_verts = vertices + [vertices[0]]  # Sulje ulkoreuna
                
                for hole in holes:
                    codes += [MplPath.MOVETO] + [MplPath.LINETO] * (len(hole) - 1) + [MplPath.CLOSEPOLY]
                    all_verts += hole + [hole[0]]  # Sulje reikä
                
                path = MplPath(all_verts, codes)
                poly = PathPatch(path, facecolor=facecolor, edgecolor='#0d5d0d',
                                linewidth=1.5, alpha=alpha, linestyle='--', zorder=1)
            else:
                poly = Polygon(vertices, facecolor=facecolor, edgecolor='#0d5d0d',
                              linewidth=1.5, alpha=alpha, linestyle='--', zorder=1)
            ax.add_patch(poly)
            n_tree_zones += 1
            
            import numpy as np
            xs = [v[0] for v in vertices]
            ys = [v[1] for v in vertices]
            cx = np.mean(xs)
            cy = np.mean(ys)
            
            # Laske alueen koko
            zone_size = max(max(xs) - min(xs), max(ys) - min(ys))
            
            # Näytä ID ja/tai nimi
            if ids_vegetation or show_labels:
                _add_label(ax, cx, cy, obs_id, name, ids_vegetation, show_labels, 
                          color='white', building_size=zone_size, is_zone=True)
        
        elif obs_type == 'vegetation_zone':
            # Kasvillisuusalue - vaaleanvihreä/keltainen polygoni
            vertices = obs['vertices']
            porosity = obs.get('porosity', 0.9)
            veg_height = obs.get('height', 0.5)
            veg_type = obs.get('vegetation_type', 'grass')
            holes = obs.get('holes', [])
            
            # Väri kasvillisuustyypin mukaan
            veg_colors = {
                'grass': '#90EE90',       # Vaaleanvihreä
                'meadow': '#9ACD32',      # Kellanvihreä
                'farmland': '#FFE082',    # Kirkas kellertävä (pelto)
                'park': '#98FB98',        # Haalea vihreä
                'garden': '#8FBC8F',      # Tumman merenvihreä
                'grassland': '#7CFC00',   # Nurmikkovihreä
                'heath': '#BC8F8F',       # Ruusunruskea
                'wetland': '#5F9EA0',     # Sinivihreä
                'golf_course': '#00FA9A', # Keskimerenvihreä
                'vineyard': '#6B8E23',    # Oliivinvihreä
                'allotments': '#556B2F',  # Tumma oliivinvihreä
            }
            facecolor = veg_colors.get(veg_type, '#90EE90')
            
            # Läpinäkyvyys korkeuden mukaan (matala = läpinäkyvämpi)
            alpha = min(0.3 + veg_height * 0.2, 0.7)
            
            # Reunaviivan tyyli korkeuden mukaan
            linestyle = ':' if veg_height < 0.3 else '-.' if veg_height < 1.0 else '--'
            
            # Jos on reikiä, käytä PathPatch
            if holes:
                # Rakenna Path reikien kanssa
                codes = [MplPath.MOVETO] + [MplPath.LINETO] * (len(vertices) - 1) + [MplPath.CLOSEPOLY]
                all_verts = vertices + [vertices[0]]  # Sulje ulkoreuna
                
                for hole in holes:
                    codes += [MplPath.MOVETO] + [MplPath.LINETO] * (len(hole) - 1) + [MplPath.CLOSEPOLY]
                    all_verts += hole + [hole[0]]  # Sulje reikä
                
                path = MplPath(all_verts, codes)
                poly = PathPatch(path, facecolor=facecolor, edgecolor='#2E8B57',
                                linewidth=1.0, alpha=alpha, linestyle=linestyle, zorder=1)
            else:
                poly = Polygon(vertices, facecolor=facecolor, edgecolor='#2E8B57',
                              linewidth=1.0, alpha=alpha, linestyle=linestyle, zorder=1)
            ax.add_patch(poly)
            n_vegetation_zones += 1
            
            import numpy as np
            xs = [v[0] for v in vertices]
            ys = [v[1] for v in vertices]
            cx = np.mean(xs)
            cy = np.mean(ys)
            
            # Laske alueen koko
            zone_size = max(max(xs) - min(xs), max(ys) - min(ys))
            
            # Näytä ID ja/tai nimi
            if ids_vegetation or show_labels:
                _add_label(ax, cx, cy, obs_id, name, ids_vegetation, show_labels, 
                          color='darkgreen', building_size=zone_size, is_zone=True)
        
        elif obs_type == 'water_zone':
            # Vesialue - sininen polygoni
            vertices = obs['vertices']
            water_type = obs.get('water_type', 'water')
            holes = obs.get('holes', [])
            
            # Väri vesityypin mukaan
            water_colors = {
                'water': '#4169E1',       # Kuninkaansininen
                'lake': '#4682B4',        # Teräksensininen
                'pond': '#87CEEB',        # Taivaansininen
                'river': '#1E90FF',       # Dodgerinsininen
                'reservoir': '#5F9EA0',   # Sinivihreä
                'basin': '#87CEFA',       # Vaaleansininen
            }
            facecolor = water_colors.get(water_type, '#4169E1')
            
            # Vesialueet näytetään hieman läpinäkyvinä
            alpha = 0.6
            
            # Jos on reikiä, käytä PathPatch
            if holes:
                codes = [MplPath.MOVETO] + [MplPath.LINETO] * (len(vertices) - 1) + [MplPath.CLOSEPOLY]
                all_verts = vertices + [vertices[0]]
                
                for hole in holes:
                    codes += [MplPath.MOVETO] + [MplPath.LINETO] * (len(hole) - 1) + [MplPath.CLOSEPOLY]
                    all_verts += hole + [hole[0]]
                
                path = MplPath(all_verts, codes)
                poly = PathPatch(path, facecolor=facecolor, edgecolor='#000080',
                                linewidth=1.5, alpha=alpha, zorder=0)
            else:
                poly = Polygon(vertices, facecolor=facecolor, edgecolor='#000080',
                              linewidth=1.5, alpha=alpha, zorder=0)
            ax.add_patch(poly)
            n_water_zones += 1
            
            import numpy as np
            xs = [v[0] for v in vertices]
            ys = [v[1] for v in vertices]
            cx = np.mean(xs)
            cy = np.mean(ys)
            
            # Laske alueen koko
            zone_size = max(max(xs) - min(xs), max(ys) - min(ys))
            
            # Näytä ID ja/tai nimi
            if ids_vegetation or show_labels:
                _add_label(ax, cx, cy, obs_id, name, ids_vegetation, show_labels, 
                          color='navy', building_size=zone_size, is_zone=True)
    
    # Piirrä tiet (jos saatavilla)
    n_roads = 0
    for road in data.get('roads', []):
        if 'vertices' in road:
            vertices = road['vertices']
            road_name = road.get('name', '')
            road_id = road.get('id', f'R{n_roads + 1}')
            highway_type = road.get('highway_type', 'residential')
            
            # Väri tietyypin mukaan
            road_colors = {
                'primary': '#505050', 'secondary': '#585858', 'tertiary': '#606060',
                'residential': '#686868', 'service': '#707070', 'living_street': '#686868',
                'footway': '#888888', 'cycleway': '#808080', 'path': '#909090'
            }
            facecolor = road_colors.get(highway_type, '#686868')
            
            poly = Polygon(vertices, facecolor=facecolor, edgecolor='#404040',
                          linewidth=0.8, alpha=0.85, zorder=5)
            ax.add_patch(poly)
            n_roads += 1
            
            # Näytä nimi jos pyydetty
            if show_labels and road_name:
                import numpy as np
                xs = [v[0] for v in vertices]
                ys = [v[1] for v in vertices]
                cx = np.mean(xs)
                cy = np.mean(ys)
                ax.text(cx, cy, road_name[:15], ha='center', va='center',
                       fontsize=6, color='white', alpha=0.8)
    
    # Piirrä muokattavat alueet (jos saatavilla)
    n_editable_zones = 0
    zone_type_colors = {
        'unknown': '#cccccc', 'grass': '#90EE90', 'garden': '#98FB98',
        'parking': '#808080', 'paved': '#696969', 'forest': '#228B22',
        'hedge': '#006400', 'water': '#4169E1', 'farmland': '#FFE082'
    }
    
    for zone in data.get('editable_zones', []):
        if 'vertices' in zone:
            vertices = zone['vertices']
            zone_id = zone.get('id', f'Z{n_editable_zones + 1}')
            zone_type = zone.get('zone_type', 'unknown')
            
            facecolor = zone_type_colors.get(zone_type, '#cccccc')
            alpha = 0.3 if zone_type == 'unknown' else 0.5
            linestyle = ':' if zone_type == 'unknown' else '-'
            
            poly = Polygon(vertices, facecolor=facecolor, edgecolor='#666666',
                          linewidth=1.0, alpha=alpha, linestyle=linestyle, zorder=1)
            ax.add_patch(poly)
            n_editable_zones += 1
            
            # Näytä ID
            if ids_vegetation:
                import numpy as np
                xs = [v[0] for v in vertices]
                ys = [v[1] for v in vertices]
                cx = np.mean(xs)
                cy = np.mean(ys)
                _add_label(ax, cx, cy, zone_id, '', True, False, 
                          color='#333333', building_size=max(max(xs)-min(xs), max(ys)-min(ys)),
                          is_zone=True)
    
    # Akseliasetukset
    ax.set_xlim(0, width)
    ax.set_ylim(0, height)
    ax.set_aspect('equal')
    ax.set_xlabel('x [m]', fontsize=11)
    ax.set_ylabel('y [m]', fontsize=11)
    
    if show_grid:
        ax.grid(True, alpha=0.3, linestyle='--')
    
    # Otsikko
    if title is None:
        title = data.get('name', 'Geometria')
    
    # Tilastot otsikkoon
    total_obs = n_buildings + n_rotated + n_polygons
    subtitle = f"Alue: {width:.0f}m × {height:.0f}m | Rakennuksia: {total_obs}"
    if n_roads > 0:
        subtitle += f" | Teitä: {n_roads}"
    if n_trees > 0:
        subtitle += f" | Puita: {n_trees}"
    if n_tree_zones > 0:
        subtitle += f" | Metsäalueita: {n_tree_zones}"
    if n_vegetation_zones > 0:
        subtitle += f" | Kasvillisuutta: {n_vegetation_zones}"
    if n_water_zones > 0:
        subtitle += f" | Vesialueita: {n_water_zones}"
    if n_editable_zones > 0:
        subtitle += f" | Muokattavia: {n_editable_zones}"
    
    ax.set_title(f"{title}\n{subtitle}", fontsize=12, fontweight='bold')
    
    # Tuulinuoli (valinnainen)
    if show_arrow:
        inlet_v = data.get('boundary_conditions', {}).get('inlet_velocity', 5.0)
        inlet_dir = data.get('boundary_conditions', {}).get('inlet_direction', 0.0)
        
        # Laske nuolen suunta (0 = idästä, 90 = etelästä, 180 = lännestä, 270 = pohjoisesta)
        import numpy as np
        arrow_angle = np.radians(inlet_dir)
        arrow_dx = np.cos(arrow_angle) * width * 0.08
        arrow_dy = np.sin(arrow_angle) * width * 0.08
        
        arrow_x = width * 0.07
        arrow_y = height - 15
        
        ax.annotate('', xy=(arrow_x + arrow_dx, arrow_y + arrow_dy), 
                    xytext=(arrow_x, arrow_y),
                    arrowprops=dict(arrowstyle='->', color='blue', lw=2.5))
        ax.text(arrow_x + arrow_dx/2, arrow_y + arrow_dy/2 + 8, 
                f'Tuuli {inlet_v} m/s\n({inlet_dir:.0f}°)', 
                ha='center', fontsize=9, color='blue', fontweight='bold')
    
    # Legenda
    legend_elements = []
    if n_buildings > 0:
        legend_elements.append(
            Rectangle((0,0), 1, 1, facecolor='#4a4a4a', edgecolor='black', 
                      label=f'Rakennukset ({n_buildings})')
        )
    if n_rotated > 0:
        legend_elements.append(
            Rectangle((0,0), 1, 1, facecolor='#5a5a8a', edgecolor='black',
                      label=f'Vinot rakennukset ({n_rotated})')
        )
    if n_polygons > 0:
        legend_elements.append(
            Rectangle((0,0), 1, 1, facecolor='#6a6a6a', edgecolor='black',
                      label=f'Monikulmiot ({n_polygons})')
        )
    if n_roads > 0:
        legend_elements.append(
            Rectangle((0,0), 1, 1, facecolor='#686868', edgecolor='#404040',
                      alpha=0.85, label=f'Tiet ({n_roads})')
        )
    if n_tree_zones > 0:
        legend_elements.append(
            Rectangle((0,0), 1, 1, facecolor='#147814', edgecolor='#0d5d0d',
                      alpha=0.5, linestyle='--',
                      label=f'Metsäalueet ({n_tree_zones})')
        )
    if n_vegetation_zones > 0:
        legend_elements.append(
            Rectangle((0,0), 1, 1, facecolor='#90EE90', edgecolor='#2E8B57',
                      alpha=0.4, linestyle=':',
                      label=f'Kasvillisuus ({n_vegetation_zones})')
        )
    if n_water_zones > 0:
        legend_elements.append(
            Rectangle((0,0), 1, 1, facecolor='#4169E1', edgecolor='#000080',
                      alpha=0.6,
                      label=f'Vesialueet ({n_water_zones})')
        )
    if n_editable_zones > 0:
        legend_elements.append(
            Rectangle((0,0), 1, 1, facecolor='#cccccc', edgecolor='#666666',
                      alpha=0.3, linestyle=':',
                      label=f'Muokattavat ({n_editable_zones})')
        )
    if n_trees > 0:
        legend_elements.append(
            Circle((0,0), 1, facecolor='#228b22', edgecolor='#145214',
                   label=f'Puut ({n_trees})')
        )
    
    if legend_elements:
        ax.legend(handles=legend_elements, loc='upper right', fontsize=9)
    
    # Info-laatikko
    nx = data['domain'].get('nx', '?')
    ny = data['domain'].get('ny', '?')
    info_text = f"Hila: {nx} × {ny}"
    if 'metadata' in data:
        meta = data['metadata']
        if 'source' in meta:
            info_text += f"\nLähde: {meta['source']}"
    
    ax.text(0.02, 0.02, info_text, transform=ax.transAxes,
            fontsize=9, verticalalignment='bottom',
            bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8))
    
    plt.tight_layout()
    
    return fig, ax


def _add_label(ax, cx, cy, obs_id, name, show_ids, show_labels, color='white', building_size=None,
               is_zone=False):
    """
    Lisää ID ja/tai nimi esteeseen.
    
    Args:
        ax: Matplotlib axis
        cx, cy: Keskipiste
        obs_id: Esteen ID
        name: Esteen nimi
        show_ids: Näytä ID
        show_labels: Näytä nimi
        color: Tekstin väri
        building_size: Rakennuksen/alueen koko (pituus metreinä) skaalausta varten
        is_zone: True jos kasvillisuus/vesialue (pienempi fontti, min_size suodatus)
    """
    if not show_ids and not show_labels:
        return
    
    # Kasvillisuusalueilla: ohita liian pienet alueet (vältetään tukkoisuus)
    if is_zone and building_size is not None and building_size < 8:
        return
    
    # Rakenna teksti
    parts = []
    if show_ids:
        parts.append(obs_id)
    if show_labels and name:
        parts.append(name[:12])  # Rajoita nimen pituus
    
    if not parts:
        return
    
    text = '\n'.join(parts)
    
    # Laske fonttikoko rakennuksen koon perusteella
    if building_size is not None and building_size > 0:
        import numpy as np
        # Log-skaalaus: 10m rakennus -> 8pt, skaalataan siitä
        scale = np.log10(max(building_size, 1)) / np.log10(10)
        base_size = 6 if is_zone else (8 if not show_labels else 7)
        fontsize = base_size * (0.7 + 0.3 * scale)
        max_size = 9 if is_zone else 12
        fontsize = np.clip(fontsize, 5, max_size)
    else:
        fontsize = 6 if is_zone else (7 if show_labels else 8)
    
    # Lisää tausta luettavuuden parantamiseksi
    bbox_props = dict(
        boxstyle='round,pad=0.2',
        facecolor='black' if color == 'white' else 'white',
        alpha=0.5 if is_zone else 0.6,
        edgecolor='none'
    )
    
    # Zona-labelit: clip akseleihin (estää vuotamisen kuvan ulkopuolelle)
    zorder = 15 if not is_zone else 12
    ax.text(cx, cy, text, ha='center', va='center',
           fontsize=fontsize, color=color, fontweight='bold',
           bbox=bbox_props, clip_on=True, zorder=zorder)


def print_obstacle_list(data):
    """
    Tulostaa listan esteistä ja niiden ID:istä.
    
    Args:
        data: JSON-data dict
    """
    print("\n" + "="*60)
    print("ESTEET")
    print("="*60)
    
    # Laskurit ID:iden generointiin
    type_counters = {
        'building': 1,
        'rotated_building': 1,
        'polygon_building': 1,
        'tree': 1,
        'tree_zone': 1,
        'vegetation_zone': 1,
        'water_zone': 1
    }
    
    for i, obs in enumerate(data.get('obstacles', [])):
        obs_type = obs.get('type', 'building')
        name = obs.get('name', '')
        
        # Hae tai generoi ID
        obs_id = obs.get('id', '')
        if not obs_id:
            obs_id = _generate_id(obs_type, type_counters.get(obs_type, 1))
            type_counters[obs_type] = type_counters.get(obs_type, 1) + 1
        
        # Laske sijainti
        if obs_type in ['building']:
            cx = (obs['x_min'] + obs['x_max']) / 2
            cy = (obs['y_min'] + obs['y_max']) / 2
            size = f"{obs['x_max']-obs['x_min']:.1f}×{obs['y_max']-obs['y_min']:.1f}m"
        elif obs_type in ['rotated_building']:
            cx = obs['x_center']
            cy = obs['y_center']
            size = f"{obs['width']:.1f}×{obs['height']:.1f}m @ {obs['angle']:.0f}°"
        elif obs_type == 'polygon_building':
            import numpy as np
            cx = np.mean([v[0] for v in obs['vertices']])
            cy = np.mean([v[1] for v in obs['vertices']])
            size = f"{len(obs['vertices'])} vertices"
        elif obs_type == 'tree':
            cx = obs['x_center']
            cy = obs['y_center']
            size = f"r={obs['radius']:.1f}m"
        elif obs_type == 'tree_zone':
            import numpy as np
            cx = np.mean([v[0] for v in obs['vertices']])
            cy = np.mean([v[1] for v in obs['vertices']])
            porosity = obs.get('porosity', 0.4)
            size = f"{len(obs['vertices'])} verts, por={porosity:.2f}"
        elif obs_type == 'vegetation_zone':
            import numpy as np
            cx = np.mean([v[0] for v in obs['vertices']])
            cy = np.mean([v[1] for v in obs['vertices']])
            porosity = obs.get('porosity', 0.9)
            veg_height = obs.get('height', 0.5)
            veg_type = obs.get('vegetation_type', 'grass')
            size = f"{veg_type}, h={veg_height:.1f}m, por={porosity:.2f}"
        elif obs_type == 'water_zone':
            import numpy as np
            cx = np.mean([v[0] for v in obs['vertices']])
            cy = np.mean([v[1] for v in obs['vertices']])
            water_type = obs.get('water_type', 'water')
            size = f"{water_type}, {len(obs['vertices'])} verts"
        else:
            cx, cy = 0, 0
            size = "?"
        
        # Tulosta rivi
        name_str = f'"{name}"' if name else ""
        print(f"  {obs_id:6s}  {obs_type:18s}  ({cx:7.1f}, {cy:7.1f})  {size:20s}  {name_str}")
    
    print("="*60)


def main():
    parser = argparse.ArgumentParser(
        description='Visualisoi CFD-geometriatiedosto',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Esimerkkejä:
  python view_geometry.py examples/u_shaped_courtyard.json
  python view_geometry.py toolontori.json --output toolontori.png
  python view_geometry.py geometry.json --ids              # Rakennusten ID:t
  python view_geometry.py geometry.json --ids-veg          # Kasvillisuuden ID:t
  python view_geometry.py geometry.json --ids-all          # Kaikkien ID:t
  python view_geometry.py geometry.json --ids --labels     # ID:t ja nimet
  python view_geometry.py geometry.json --list             # Listaa esteet
  python view_geometry.py geometry.json --no-show -o kuva.png
        """
    )
    
    parser.add_argument('geometry', type=str, help='JSON-geometriatiedosto')
    parser.add_argument('--output', '-o', type=str, default=None,
                        help='Tallenna kuva tiedostoon')
    parser.add_argument('--no-show', action='store_true',
                        help='Älä näytä ikkunassa (vain tallenna)')
    parser.add_argument('--labels', '-l', action='store_true',
                        help='Näytä rakennusten nimet')
    parser.add_argument('--ids', '-i', action='store_true',
                        help='Näytä rakennusten ID:t')
    parser.add_argument('--ids-veg', action='store_true',
                        help='Näytä kasvillisuuden/vesialueiden ID:t')
    parser.add_argument('--ids-all', action='store_true',
                        help='Näytä kaikkien esteiden ID:t (rakennukset + kasvillisuus)')
    parser.add_argument('--list', action='store_true',
                        help='Tulosta lista esteistä ja niiden ID:istä')
    parser.add_argument('--no-grid', action='store_true',
                        help='Piilota ruudukko')
    parser.add_argument('--no-arrow', action='store_true',
                        help='Piilota tuulinuoli')
    parser.add_argument('--title', '-t', type=str, default=None,
                        help='Mukautettu otsikko')
    parser.add_argument('--dpi', type=int, default=150,
                        help='Kuvan resoluutio (oletus: 150)')
    
    args = parser.parse_args()
    
    # Tarkista tiedosto
    geom_path = Path(args.geometry)
    if not geom_path.exists():
        print(f"VIRHE: Tiedostoa ei löydy: {geom_path}")
        sys.exit(1)
    
    # Lataa
    print(f"Ladataan: {geom_path}")
    data = load_json(geom_path)
    
    # Tilastot
    n_obs = len(data.get('obstacles', []))
    width = data['domain']['width']
    height = data['domain']['height']
    print(f"  Alue: {width:.0f}m × {height:.0f}m")
    print(f"  Esteitä: {n_obs}")
    
    # Tulosta lista jos pyydetty
    if args.list:
        print_obstacle_list(data)
    
    # Backend
    if args.no_show or args.output:
        matplotlib.use('Agg')
    
    # Piirra
    fig, ax = plot_geometry(
        data,
        title=args.title,
        show_grid=not args.no_grid,
        show_labels=args.labels,
        show_ids=args.ids,
        show_arrow=not args.no_arrow,
        show_ids_buildings=args.ids_all,
        show_ids_vegetation=args.ids_veg or args.ids_all
    )
    
    # Tallenna
    if args.output:
        output_path = Path(args.output)
        plt.savefig(output_path, dpi=args.dpi, bbox_inches='tight')
        print(f"Tallennettu: {output_path}")
    
    # Näytä
    if not args.no_show and not args.output:
        plt.show()
    elif not args.no_show and args.output:
        plt.show()
    
    plt.close(fig)


if __name__ == '__main__':
    main()
