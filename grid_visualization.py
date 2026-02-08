#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Laskentahilan visualisointi MikroilmastoCFD:lle.

Generoi havainnollistavan kuvan nested grid -laskentahilasta:
- Karkea hila (koko domain)
- Tiheä hila (tihennysalue)
- Rakennukset (kohde + muut)
- Kasvillisuus/viheralueet
- Lähikuva kohderakennuksen kulmasta

Käyttö:
  A) Dataohjautuvasti simuloinnin tuloksista:
     from grid_visualization import generate_grid_from_simulation
     generate_grid_from_simulation(results_dir, output_path)
     
  B) Demo/esimerkki:
     python grid_visualization.py
"""

import json
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import Rectangle, Polygon as MplPolygon, ConnectionPatch
from matplotlib.lines import Line2D
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def _get_vegetation_color(veg_type: str):
    """Palauta (facecolor, edgecolor) kasvillisuustyypille."""
    _COLORS = {
        'road': ('#909090', '#606060'),
        'road_surface': ('#909090', '#606060'),
        'water': ('#a8d4f0', '#4a90c4'),
        'farmland': ('#FFE082', '#DAA520'),
        'yard_lawn': ('#98FB98', '#6BBF6B'),
        'yard_mixed': ('#7FBF7F', '#5A9A5A'),
        'park_lawn': ('#90EE90', '#68C968'),
        'park': ('#6DBE6D', '#4A9A4A'),
        'meadow_natural': ('#BDB76B', '#8E8B4D'),
        'bare_soil': ('#8B7355', '#6B5335'),
    }
    if veg_type in _COLORS:
        return _COLORS[veg_type]
    vt = veg_type.lower()
    if 'forest' in vt or 'tree' in vt or 'wood' in vt:
        return ('#228b22', '#1a6b1a')
    if 'park' in vt or 'lawn' in vt or 'garden' in vt:
        return ('#90EE90', '#68C968')
    if 'road' in vt or 'parking' in vt or 'asphalt' in vt:
        return ('#909090', '#606060')
    if 'water' in vt:
        return ('#a8d4f0', '#4a90c4')
    return ('#228b22', '#1a6b1a')


def generate_grid_visualization(
    buildings: List[Dict],
    output_path: str,
    domain_x_min: float = 0, domain_x_max: float = 400,
    domain_y_min: float = 0, domain_y_max: float = 400,
    dx_coarse: float = 1.0,
    refinement: int = 4,
    fine_x_min: float = None, fine_x_max: float = None,
    fine_y_min: float = None, fine_y_max: float = None,
    porous_zones: List[Dict] = None,
    target_building_id: int = None,
    lang: str = 'fi',
    dpi: int = 150,
):
    """
    Generoi laskentahilan visualisointi.
    
    Args:
        buildings: Lista rakennusdictejä (vertices/x_min/x_max, is_target, is_solid)
        output_path: Tallennuspolku (.png)
        domain_*: Karkean hilan domain-rajat
        dx_coarse: Karkean hilan solukoko [m]
        refinement: Tihennyskerroin
        fine_*: Tiheän hilan rajat
        porous_zones: Kasvillisuusalueet
        lang: 'fi' tai 'en'
        dpi: Kuvan resoluutio
    
    Returns:
        output_path jos onnistui, None muuten
    """
    if porous_zones is None:
        porous_zones = []
    
    dx_fine = dx_coarse / refinement
    
    # Näyttöarvot - pyöristetty järkevästi
    def _fmt_dx(val):
        """Muotoile solukoko: 2.01005 -> '2.0', 0.50251 -> '0.50'"""
        if abs(val - round(val, 1)) < 0.02:
            return f'{val:.1f}'
        else:
            return f'{val:.2f}'
    
    dc = _fmt_dx(dx_coarse)
    df = _fmt_dx(dx_fine)
    
    # Käännökset
    if lang == 'en':
        txt_coarse = f'Coarse grid: {dc}m \u00d7 {dc}m'
        txt_fine = f'Fine grid: {df}m \u00d7 {df}m  ({refinement}\u00d7 refinement)'
        txt_target = 'TARGET'
        txt_inset_title = f'Close-up: {df}m \u00d7 {df}m cells'
        txt_scale = '1 m'
        lbl_target = 'Target building'
        lbl_other = 'Other building'
        lbl_vegetation = 'Vegetation'
        lbl_fine_grid = f'Fine grid ({df}m)'
        lbl_coarse_grid = f'Coarse grid ({dc}m)'
        lbl_fine_border = 'Fine grid boundary'
        txt_title = f'Computational grid \u2013 coarse {dc}m + fine {df}m ({refinement}\u00d7 refinement)'
        txt_info_fmt = 'Fine grid: {nx} \u00d7 {ny} = {n:,} cells\nResolution: {fine} m (target) / {coarse} m (surroundings)\nRefinement factor: {ref}\u00d7'
    else:
        txt_coarse = f'Karkea hila: {dc}m \u00d7 {dc}m'
        txt_fine = f'Tihe\u00e4 hila: {df}m \u00d7 {df}m  ({refinement}\u00d7 tihennys)'
        txt_target = 'KOHDE'
        txt_inset_title = f'L\u00e4hikuva: {df}m \u00d7 {df}m solut'
        txt_scale = '1 m'
        lbl_target = 'Kohderakennus'
        lbl_other = 'Muu rakennus'
        lbl_vegetation = 'Kasvillisuus'
        lbl_fine_grid = f'Tihe\u00e4 hila ({df}m)'
        lbl_coarse_grid = f'Karkea hila ({dc}m)'
        lbl_fine_border = f'Tihe\u00e4n hilan raja'
        txt_title = f'Laskentahila \u2013 karkea {dc}m + tihe\u00e4 {df}m ({refinement}\u00d7 tihennys)'
        txt_info_fmt = 'Tihe\u00e4 hila: {nx} \u00d7 {ny} = {n:,} solua\nResoluutio: {fine} m (kohde) / {coarse} m (ymp\u00e4rist\u00f6)\nTihennyskerroin: {ref}\u00d7'
    # Suodata rakennukset
    solid_buildings = []
    target_bldg = None
    for i, b in enumerate(buildings):
        btype = b.get('type', 'building')
        is_solid = b.get('is_solid', True)
        if btype in ['tree_zone', 'vegetation_zone', 'tree'] or not is_solid:
            continue
        solid_buildings.append(b)
        if b.get('is_target', False) or i == target_building_id:
            target_bldg = b
    
    # Fine grid -koot
    if fine_x_min is not None:
        nx_fine = int((fine_x_max - fine_x_min) / dx_fine)
        ny_fine = int((fine_y_max - fine_y_min) / dx_fine)
        n_cells = nx_fine * ny_fine
    else:
        nx_fine = ny_fine = n_cells = 0
    
    # Näkyvä alue
    if fine_x_min is not None:
        margin = max(5, (fine_x_max - fine_x_min) * 0.03)
        view_x_min = fine_x_min - margin
        view_x_max = fine_x_max + margin
        view_y_min = fine_y_min - margin
        view_y_max = fine_y_max + margin
    else:
        view_x_min, view_x_max = domain_x_min, domain_x_max
        view_y_min, view_y_max = domain_y_min, domain_y_max
    
    # === Kuva ===
    fig, ax = plt.subplots(figsize=(14, 10))
    ax.set_facecolor('white')
    
    # Karkea hila
    for x in np.arange(domain_x_min, domain_x_max + dx_coarse, dx_coarse):
        if view_x_min <= x <= view_x_max:
            ax.axvline(x, color='#d0d0d0', linewidth=0.3, zorder=1)
    for y in np.arange(domain_y_min, domain_y_max + dx_coarse, dx_coarse):
        if view_y_min <= y <= view_y_max:
            ax.axhline(y, color='#d0d0d0', linewidth=0.3, zorder=1)
    
    # Tiheä hila
    if fine_x_min is not None:
        step_show = max(1, int(0.5 / dx_fine))
        for x in np.arange(fine_x_min, fine_x_max + dx_fine, dx_fine * step_show):
            ax.plot([x, x], [fine_y_min, fine_y_max], color='#7fb8e0',
                    linewidth=0.35, zorder=2)
        for y in np.arange(fine_y_min, fine_y_max + dx_fine, dx_fine * step_show):
            ax.plot([fine_x_min, fine_x_max], [y, y], color='#7fb8e0',
                    linewidth=0.35, zorder=2)
    
    # Kasvillisuus jätetty pois hilavisualisoinnista selkeyden vuoksi
    
    # Rakennukset
    for b in solid_buildings:
        is_target = (b is target_bldg)
        fc = '#1a365d' if is_target else '#4a5568'
        ec = '#e53e3e' if is_target else '#2d3748'
        lw = 2.5 if is_target else 0.8
        z = 11 if is_target else 10
        
        if 'vertices' in b and b['vertices']:
            poly = MplPolygon(b['vertices'], facecolor=fc, edgecolor=ec,
                             linewidth=lw, zorder=z)
            ax.add_patch(poly)
            if is_target:
                verts = np.array(b['vertices'])
                cx, cy = verts[:, 0].mean(), verts[:, 1].mean()
                ax.text(cx, cy, txt_target, ha='center', va='center',
                       fontsize=13, fontweight='bold', color='white', zorder=12)
        elif 'x_min' in b:
            rect = Rectangle(
                (b['x_min'], b['y_min']),
                b['x_max'] - b['x_min'], b['y_max'] - b['y_min'],
                facecolor=fc, edgecolor=ec, linewidth=lw, zorder=z)
            ax.add_patch(rect)
            if is_target:
                cx = (b['x_min'] + b['x_max']) / 2
                cy = (b['y_min'] + b['y_max']) / 2
                ax.text(cx, cy, txt_target, ha='center', va='center',
                       fontsize=13, fontweight='bold', color='white', zorder=12)
    
    # Tiheän hilan raja (punainen katkoviiva)
    if fine_x_min is not None:
        border = Rectangle(
            (fine_x_min, fine_y_min),
            fine_x_max - fine_x_min, fine_y_max - fine_y_min,
            facecolor='none', edgecolor='#e53e3e',
            linewidth=2.0, linestyle='--', zorder=15)
        ax.add_patch(border)
    
    # Tekstit
    ax.text(view_x_min + 2, view_y_max - 2,
            txt_coarse, fontsize=9, color='#4a5568', fontweight='bold',
            bbox=dict(boxstyle='round,pad=0.3', facecolor='#bee3f8',
                     edgecolor='#90caf9', alpha=0.8),
            va='top', zorder=20)
    
    if fine_x_min is not None:
        # Sijoita fine-teksti fine-alueen yläreunaan, mutta varmista ettei mene coarse-tekstin päälle
        fine_label_y = min(fine_y_max + 1.5, view_y_max - 6)
        ax.text(fine_x_min + 2, fine_label_y,
                txt_fine, fontsize=9, color='#e53e3e', fontweight='bold',
                bbox=dict(boxstyle='round,pad=0.3', facecolor='white',
                         edgecolor='#e53e3e', alpha=0.9),
                zorder=20)
        
        info_text = txt_info_fmt.format(
            nx=nx_fine, ny=ny_fine, n=n_cells,
            fine=df, coarse=dc, ref=refinement)
        ax.text(view_x_max - 2, view_y_max - 2,
                info_text, fontsize=8, ha='right', va='top',
                bbox=dict(boxstyle='round,pad=0.4', facecolor='#c6f6d5',
                         edgecolor='#68d391', alpha=0.85),
                zorder=20)
    
    # === Lähikuva (inset) kohderakennuksen kulmasta ===
    if target_bldg and fine_x_min is not None:
        if 'vertices' in target_bldg and target_bldg['vertices']:
            verts = np.array(target_bldg['vertices'])
            t_x_min, t_y_min = verts[:, 0].min(), verts[:, 1].min()
            t_x_max, t_y_max = verts[:, 0].max(), verts[:, 1].max()
        else:
            t_x_min = target_bldg['x_min']
            t_y_min = target_bldg['y_min']
            t_x_max = target_bldg['x_max']
            t_y_max = target_bldg['y_max']
        
        # Inset ~7m × 7m kohderakennuksen kulmasta
        inset_size = max(5, min(10, 3.0 / dx_fine * dx_fine))
        
        # Insetin sisältö: kohderakennuksen todellinen kulma
        if 'vertices' in target_bldg and target_bldg['vertices']:
            verts_arr = np.array(target_bldg['vertices'])
            cx = (t_x_min + t_x_max) / 2
            cy = (t_y_min + t_y_max) / 2
            # Etsi vertex lähinnä vasenta yläkulmaa
            scores = -(verts_arr[:, 0] - cx) + (verts_arr[:, 1] - cy)
            best_idx = np.argmax(scores)
            corner_x = verts_arr[best_idx, 0]
            corner_y = verts_arr[best_idx, 1]
        else:
            corner_x = t_x_min
            corner_y = t_y_max
        
        ix_min = corner_x - inset_size * 0.5
        ix_max = corner_x + inset_size * 0.5
        iy_min = corner_y - inset_size * 0.5
        iy_max = corner_y + inset_size * 0.5
        
        # Sijoita inset tiheän verkon vasempaan alareunaan, kohderakennuksen viereen
        # Lasketaan sijainti akseli-koordinaateissa (0-1)
        view_x_range = view_x_max - view_x_min
        view_y_range = view_y_max - view_y_min
        
        # Insetin koko akseli-koordinaateissa (neliö)
        inset_ax_size = 0.28  # 28% plotin leveydestä
        
        # Sijoita fine-alueen vasempaan alareunaan
        fine_x_frac = (fine_x_min - view_x_min) / view_x_range
        fine_y_frac = (fine_y_min - view_y_min) / view_y_range
        
        # Pieni offset fine-reunasta sisäänpäin
        inset_x0 = fine_x_frac + 0.01
        inset_y0 = fine_y_frac + 0.01
        
        ax_inset = ax.inset_axes([inset_x0, inset_y0, inset_ax_size, inset_ax_size])
        ax_inset.set_zorder(50)
        
        ax_inset.set_facecolor('white')
        for spine in ax_inset.spines.values():
            spine.set_linewidth(2)
            spine.set_color('#2d3748')
        
        # Tiheä hila
        for x in np.arange(ix_min, ix_max + dx_fine, dx_fine):
            ax_inset.axvline(x, color='#90caf9', linewidth=0.5, zorder=1)
        for y in np.arange(iy_min, iy_max + dx_fine, dx_fine):
            ax_inset.axhline(y, color='#90caf9', linewidth=0.5, zorder=1)
        
        # Karkea hila (musta katkoviiva)
        for x in np.arange(np.floor(ix_min / dx_coarse) * dx_coarse,
                           ix_max + dx_coarse, dx_coarse):
            ax_inset.axvline(x, color='black', linewidth=1.0, linestyle='--', zorder=2)
        for y in np.arange(np.floor(iy_min / dx_coarse) * dx_coarse,
                           iy_max + dx_coarse, dx_coarse):
            ax_inset.axhline(y, color='black', linewidth=1.0, linestyle='--', zorder=2)
        
        # Solukeskipisteet (maskattu rakennusten sisältä)
        ccx_arr = np.arange(ix_min + dx_fine/2, ix_max, dx_fine)
        ccy_arr = np.arange(iy_min + dx_fine/2, iy_max, dx_fine)
        ccx, ccy = np.meshgrid(ccx_arr, ccy_arr)
        
        inside_mask = np.zeros_like(ccx, dtype=bool)
        for b in solid_buildings:
            if 'vertices' in b and b['vertices']:
                from matplotlib.path import Path as MplPath
                verts_b = np.array(b['vertices'])
                path = MplPath(verts_b)
                pts = np.column_stack([ccx.ravel(), ccy.ravel()])
                inside_mask |= path.contains_points(pts).reshape(ccx.shape)
            elif 'x_min' in b:
                inside_mask |= (
                    (ccx >= b['x_min']) & (ccx <= b['x_max']) &
                    (ccy >= b['y_min']) & (ccy <= b['y_max']))
        
        ax_inset.plot(ccx[~inside_mask].ravel(), ccy[~inside_mask].ravel(),
                     'k.', markersize=1.5, zorder=3)
        
        # Rakennukset lähikuvassa (yksivärisenä ilman hilaa)
        for b in solid_buildings:
            is_t = (b is target_bldg)
            fc_i = '#1a365d' if is_t else '#4a5568'
            ec_i = '#e53e3e' if is_t else '#2d3748'
            lw_i = 2 if is_t else 1
            if 'vertices' in b and b['vertices']:
                poly = MplPolygon(b['vertices'], facecolor=fc_i, edgecolor=ec_i,
                                 linewidth=lw_i, clip_on=True, zorder=5)
                ax_inset.add_patch(poly)
            elif 'x_min' in b:
                rect = Rectangle(
                    (b['x_min'], b['y_min']),
                    b['x_max'] - b['x_min'], b['y_max'] - b['y_min'],
                    facecolor=fc_i, edgecolor=ec_i,
                    linewidth=lw_i, clip_on=True, zorder=5)
                ax_inset.add_patch(rect)
        
        ax_inset.set_xlim(ix_min, ix_max)
        ax_inset.set_ylim(iy_min, iy_max)
        ax_inset.set_aspect('equal')
        ax_inset.set_xlabel('x [m]', fontsize=7)
        ax_inset.set_ylabel('y [m]', fontsize=7)
        ax_inset.tick_params(labelsize=7)
        ax_inset.set_title(txt_inset_title, fontsize=8,
                           bbox=dict(boxstyle='round,pad=0.2', facecolor='white',
                                     edgecolor='#cbd5e0', alpha=0.95))
        
        # 1m mittakaavapalkki
        bar_x = ix_min + (ix_max - ix_min) * 0.05
        bar_y = iy_max - (iy_max - iy_min) * 0.08
        ax_inset.plot([bar_x, bar_x + 1.0], [bar_y, bar_y], 'k-', linewidth=2)
        ax_inset.text(bar_x + 0.5, bar_y + (iy_max - iy_min) * 0.04,
                     txt_scale, ha='center', fontsize=7, fontweight='bold')
        
        # Inset-alueen rajaus pääkuvassa
        inset_highlight = Rectangle(
            (ix_min, iy_min), ix_max - ix_min, iy_max - iy_min,
            facecolor='none', edgecolor='#e53e3e',
            linewidth=1.0, linestyle=':', zorder=14)
        ax.add_patch(inset_highlight)
        
        try:
            con1 = ConnectionPatch(
                xyA=(ix_min, iy_max), coordsA=ax.transData,
                xyB=(ix_min, iy_max), coordsB=ax_inset.transData,
                color='#e53e3e', linewidth=0.8, alpha=0.5)
            con2 = ConnectionPatch(
                xyA=(ix_max, iy_max), coordsA=ax.transData,
                xyB=(ix_max, iy_max), coordsB=ax_inset.transData,
                color='#e53e3e', linewidth=0.8, alpha=0.5)
            fig.add_artist(con1)
            fig.add_artist(con2)
        except Exception:
            pass
    
    # === LEGENDA ===
    legend_elements = [
        mpatches.Patch(facecolor='#1a365d', edgecolor='#e53e3e', linewidth=2,
                       label=lbl_target),
        mpatches.Patch(facecolor='#4a5568', edgecolor='#2d3748',
                       label=lbl_other),
    ]
    legend_elements.extend([
        Line2D([0], [0], color='#90caf9', linewidth=1.0, label=lbl_fine_grid),
        Line2D([0], [0], color='#cccccc', linewidth=1.0, label=lbl_coarse_grid),
        Line2D([0], [0], color='#e53e3e', linewidth=2, linestyle='--',
               label=lbl_fine_border),
    ])
    
    leg = ax.legend(handles=legend_elements, loc='lower right', fontsize=8,
                    framealpha=0.95, edgecolor='#cbd5e0', fancybox=True)
    leg.set_zorder(30)  # Korkeampi kuin katkoviiva (15)
    
    # Akselit
    ax.set_xlim(view_x_min, view_x_max)
    ax.set_ylim(view_y_min, view_y_max)
    ax.set_aspect('equal')
    ax.set_xlabel('x [m]')
    ax.set_ylabel('y [m]')
    ax.set_title(txt_title, fontsize=14, fontweight='bold')
    
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        plt.tight_layout()
    plt.savefig(output_path, dpi=dpi, bbox_inches='tight', facecolor='white')
    plt.close()
    print(f"  \u2713 {Path(output_path).name}")
    return str(output_path)


# ============================================================================
# Simulaatiodatasta generointi
# ============================================================================

def generate_grid_from_simulation(results_dir, output_path=None, lang='fi', dpi=150):
    """
    Generoi hilavisualisointi simuloinnin tuloshakemistosta.
    
    Lukee metadata.json / multi_wind_metadata.json ja buildings.json.
    
    Args:
        results_dir: Tuloshakemisto (esim. results/case1/ tai results/case1/combined/)
        output_path: Tallennuspolku (oletus: results_dir/grid_visualization.png)
        lang: 'fi' tai 'en'
        dpi: Kuvan resoluutio
        
    Returns:
        output_path jos onnistui, None muuten
    """
    results_dir = Path(results_dir)
    
    if output_path is None:
        output_path = results_dir / 'grid_visualization.png'
    
    # Etsi metadata
    metadata = None
    for mp in [results_dir / 'multi_wind_metadata.json',
               results_dir.parent / 'multi_wind_metadata.json',
               results_dir / 'metadata.json',
               results_dir / 'data' / 'metadata.json']:
        if mp.exists():
            with open(mp, 'r') as f:
                metadata = json.load(f)
            break
    
    # Fallback: Luo metadata domain.json-tiedostoista
    if metadata is None:
        domain_json_candidates = [
            results_dir / 'domain.json',
            results_dir / 'fine' / 'domain.json',
            results_dir / 'data' / 'domain.json',
        ]
        for domain_candidate in domain_json_candidates:
            if domain_candidate.exists():
                try:
                    with open(domain_candidate, 'r', encoding='utf-8') as f:
                        domain_data = json.load(f)
                    
                    metadata = {
                        'wind_direction': domain_data.get('inlet_direction', 0),
                        'inlet_velocity': domain_data.get('inlet_velocity', 5.0),
                        'domain': {
                            'x_min': domain_data.get('x_offset', 0),
                            'y_min': domain_data.get('y_offset', 0),
                            'width': domain_data.get('width'),
                            'height': domain_data.get('height'),
                        },
                        'grid': {
                            'nx': domain_data.get('nx'),
                            'ny': domain_data.get('ny'),
                            'dx': domain_data.get('dx'),
                            'dy': domain_data.get('dy'),
                            'width': domain_data.get('width'),
                            'height': domain_data.get('height'),
                        }
                    }
                    
                    # Tarkista onko nested grid - etsi coarse/fine domain.json
                    coarse_domain = results_dir / 'coarse' / 'domain.json'
                    fine_domain = results_dir / 'fine' / 'domain.json'
                    
                    if coarse_domain.exists() and fine_domain.exists():
                        try:
                            with open(coarse_domain, 'r', encoding='utf-8') as f:
                                coarse_data = json.load(f)
                            with open(fine_domain, 'r', encoding='utf-8') as f:
                                fine_data = json.load(f)
                            
                            fine_x_min = fine_data.get('x_offset', 0)
                            fine_y_min = fine_data.get('y_offset', 0)
                            fine_x_max = fine_x_min + fine_data.get('width', 0)
                            fine_y_max = fine_y_min + fine_data.get('height', 0)
                            
                            coarse_dx = coarse_data.get('dx', 2.0)
                            fine_dx = fine_data.get('dx', 0.5)
                            refinement = round(coarse_dx / fine_dx) if fine_dx > 0 else 4
                            
                            metadata['nested_grid_settings'] = {
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
                            
                            # Päivitä domain coarse-tiedoista (koko laskenta-alue)
                            metadata['domain'] = {
                                'x_min': coarse_data.get('x_offset', 0),
                                'y_min': coarse_data.get('y_offset', 0),
                                'width': coarse_data.get('width'),
                                'height': coarse_data.get('height'),
                            }
                            
                            print(f"  Nested grid tiedot luettu domain.json-tiedostoista")
                        except Exception as e:
                            print(f"  Varoitus: Nested grid tietojen lukeminen epäonnistui: {e}")
                    
                    print(f"  Metadata luotu: {domain_candidate}")
                    break
                except Exception as e:
                    print(f"  Varoitus: domain.json lukeminen epäonnistui: {e}")
    
    if metadata is None:
        print(f"  ⚠ Metadataa ei löydy, hilavisualisointia ei voida generoida")
        return None
    
    # Nested grid -asetukset
    nested_settings = metadata.get('nested_grid_settings', {})
    if not nested_settings:
        print(f"  \u26a0 Nested grid -asetuksia ei l\u00f6ydy, hilavisualisointia ei generoida")
        return None
    
    fine_region = nested_settings.get('fine_region', {})
    coarse_dx = nested_settings.get('coarse_dx', 1.0)
    refinement = nested_settings.get('refinement_factor', 4)
    
    domain = metadata.get('domain', {})
    domain_x_min = domain.get('x_min', 0)
    domain_x_max = domain.get('x_max', domain.get('width', 400))
    domain_y_min = domain.get('y_min', 0)
    domain_y_max = domain.get('y_max', domain.get('height', 400))
    
    # Etsi buildings.json
    buildings = []
    bpaths = [results_dir / 'buildings.json',
              results_dir / 'data' / 'buildings.json']
    if 'combined' in str(results_dir):
        for wd in sorted(results_dir.parent.glob("wind_*")):
            bpaths.append(wd / 'fine' / 'buildings.json')
            bpaths.append(wd / 'buildings.json')
    else:
        bpaths.insert(0, results_dir / 'fine' / 'buildings.json')
    
    for bp in bpaths:
        if bp.exists():
            with open(bp, 'r') as f:
                bdata = json.load(f)
            buildings = bdata.get('buildings', []) if isinstance(bdata, dict) else bdata
            break
    
    if not buildings:
        print(f"  \u26a0 Rakennuksia ei l\u00f6ydy, hilavisualisointia ei generoida")
        return None
    
    # Etsi kasvillisuusalueet
    porous_zones = []
    ppaths = [results_dir / 'porous_zones.json',
              results_dir / 'data' / 'porous_zones.json']
    if 'combined' in str(results_dir):
        for wd in sorted(results_dir.parent.glob("wind_*")):
            ppaths.append(wd / 'fine' / 'porous_zones.json')
            ppaths.append(wd / 'porous_zones.json')
    else:
        ppaths.insert(0, results_dir / 'fine' / 'porous_zones.json')
    
    for pp in ppaths:
        if pp.exists():
            try:
                with open(pp, 'r') as f:
                    pdata = json.load(f)
                if isinstance(pdata, list):
                    porous_zones = pdata
                elif isinstance(pdata, dict):
                    porous_zones = pdata.get('zones', pdata.get('porous_zones', []))
            except Exception:
                pass
            break
    
    return generate_grid_visualization(
        buildings=buildings,
        output_path=str(output_path),
        domain_x_min=domain_x_min, domain_x_max=domain_x_max,
        domain_y_min=domain_y_min, domain_y_max=domain_y_max,
        dx_coarse=coarse_dx, refinement=refinement,
        fine_x_min=fine_region.get('x_min'),
        fine_x_max=fine_region.get('x_max'),
        fine_y_min=fine_region.get('y_min'),
        fine_y_max=fine_region.get('y_max'),
        porous_zones=porous_zones,
        lang=lang, dpi=dpi,
    )


# ============================================================================
# Demo
# ============================================================================

def generate_demo():
    """Generoi esimerkkikuva kovakoodatuilla arvoilla."""
    buildings = [
        {'x_min': 153, 'y_min': 248, 'x_max': 181, 'y_max': 264, 'is_solid': True},
        {'x_min': 197, 'y_min': 249, 'x_max': 239, 'y_max': 262, 'is_solid': True},
        {'x_min': 252, 'y_min': 245, 'x_max': 282, 'y_max': 265, 'is_solid': True},
        {'x_min': 147, 'y_min': 222, 'x_max': 163, 'y_max': 236, 'is_solid': True},
        {'x_min': 197, 'y_min': 210, 'x_max': 207, 'y_max': 218, 'is_solid': True},
        {'x_min': 225, 'y_min': 185, 'x_max': 253, 'y_max': 199, 'is_solid': True},
        {'x_min': 248, 'y_min': 175, 'x_max': 262, 'y_max': 193, 'is_solid': True},
        {'x_min': 265, 'y_min': 218, 'x_max': 275, 'y_max': 233, 'is_solid': True},
        {'x_min': 158, 'y_min': 170, 'x_max': 170, 'y_max': 186, 'is_solid': True},
        {'x_min': 271, 'y_min': 163, 'x_max': 281, 'y_max': 171, 'is_solid': True},
        {'x_min': 183, 'y_min': 196, 'x_max': 268, 'y_max': 218,
         'is_solid': True, 'is_target': True},
    ]
    
    porous_zones = [
        {'x_min': 180, 'y_min': 222, 'x_max': 196, 'y_max': 245, 'type': 'park'},
        {'x_min': 222, 'y_min': 227, 'x_max': 235, 'y_max': 240, 'type': 'yard_lawn'},
        {'x_min': 176, 'y_min': 170, 'x_max': 186, 'y_max': 178, 'type': 'park_lawn'},
        {'x_min': 222, 'y_min': 163, 'x_max': 232, 'y_max': 170, 'type': 'yard_lawn'},
    ]
    
    generate_grid_visualization(
        buildings=buildings,
        output_path='laskentahila_esimerkki.png',
        domain_x_min=140, domain_x_max=280,
        domain_y_min=160, domain_y_max=270,
        dx_coarse=1.0, refinement=4,
        fine_x_min=148, fine_x_max=275,
        fine_y_min=163, fine_y_max=262,
        porous_zones=porous_zones, dpi=150,
    )


if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1:
        results_dir = sys.argv[1]
        lang = sys.argv[2] if len(sys.argv) > 2 else 'fi'
        generate_grid_from_simulation(results_dir, lang=lang)
    else:
        generate_demo()
