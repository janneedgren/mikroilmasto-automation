#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MikroilmastoCFD - QA Dashboard

Generoi interaktiivisen HTML-dashboardin kasvillisuusalueiden
validointitilastoista.

Käyttö:
    from qa.dashboard import update_dashboard, generate_dashboard_html
    
    # Päivitä dashboard QA-lokin perusteella
    update_dashboard(qa_dir)
    
    # Tai generoi HTML suoraan
    html = generate_dashboard_html(qa_logger)

Tuomas Alinikula, Loopshore Oy, 2026
"""

import datetime
import json
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from qa.logger import QALogger


def update_dashboard(qa_dir: Path) -> None:
    """
    Päivittää QA-dashboardin HTML-tiedoston.
    
    Args:
        qa_dir: Hakemisto jossa qa_master_log.json sijaitsee
    """
    try:
        from qa.logger import QALogger
        qa = QALogger(output_dir=str(qa_dir), log_name="qa_master_log")
        
        dashboard_path = qa_dir / "qa_dashboard.html"
        html = generate_dashboard_html(qa)
        
        with open(dashboard_path, 'w', encoding='utf-8') as f:
            f.write(html)
            
    except Exception as e:
        print(f"  [QA] Dashboard-päivitys epäonnistui: {e}")


def generate_dashboard_html(qa: 'QALogger') -> str:
    """
    Generoi interaktiivinen HTML-dashboard.
    
    Args:
        qa: QALogger-instanssi josta data haetaan
        
    Returns:
        HTML-merkkijono
    """
    entries = qa.log_entries
    summary = qa.get_summary()
    
    # Kerää kasvillisuusdata visualisointia varten
    veg_data = []
    for entry in entries:
        sim_id = entry.get('simulation_id', '')
        project = entry.get('project_name', sim_id)
        timestamp = entry.get('timestamp', '')[:10]  # Päivämäärä
        
        for zone in entry.get('vegetation_validation', []):
            # Ohita ei-kasvillisuustyypit (vesi, tiet yms.)
            _zt = (zone.get('zone_type', '') or '').lower()
            _exclude = ['road', 'lake', 'water', 'pond', 'river', 'reservoir',
                        'parking', 'asphalt', 'sand', 'bare', 'wetland', 'reed']
            if any(ex in _zt for ex in _exclude):
                continue
            veg_data.append({
                'project': project,
                'date': timestamp,
                'zone_type': zone.get('zone_type', 'unknown'),
                'TI_mean': zone.get('TI_mean', 0),
                'TI_min': zone.get('TI_p5', zone.get('TI_min', 0)),
                'TI_max': zone.get('TI_p95', zone.get('TI_max', 0)),
                'omega_mean': zone.get('omega_mean', 0),
                'k_over_U2': zone.get('k_over_U2_mean', 0),
                'h_c_mean': zone.get('h_c_mean', None),
                'LAI': zone.get('LAI', 0),
                'height': zone.get('height', 0),
            })
    
    # Kirjallisuusarvot vertailuun - omega [1/s]
    # Lähteet: 
    #   - Tiheä metsä: Finnigan (2000), Sogachev (2006), Katul et al. (2004)
    #   - Pensaat: Shaw & Schumann (1992)
    #   - Muut: Johdettu fysikaalisista periaatteista (LAI, drag, TKE-tuotanto)
    literature_omega = {
        # Tiheä metsä (LAI 5-8) - vahva kirjallisuuspohja
        'dense_forest': {
            'min': 0.5, 'max': 3.0, 'typical_min': 0.8, 'typical_max': 2.0,
            'label': 'Tiheä metsä', 
            'source': 'Finnigan (2000), Sogachev (2006)',
            'source_type': 'literature'
        },
        'forest': {
            'min': 0.5, 'max': 3.0, 'typical_min': 0.8, 'typical_max': 2.0,
            'label': 'Metsä', 
            'source': 'Finnigan (2000), Sogachev (2006)',
            'source_type': 'literature'
        },
        'tree_zone': {
            'min': 0.5, 'max': 3.0, 'typical_min': 0.8, 'typical_max': 2.0,
            'label': 'Puusto', 
            'source': 'Finnigan (2000)',
            'source_type': 'literature'
        },
        # Harva puusto (LAI 1-3) - johdettu: pienempi LAI → vähemmän drag
        'sparse_forest': {
            'min': 0.3, 'max': 2.0, 'typical_min': 0.5, 'typical_max': 1.5,
            'label': 'Harva puusto',
            'source': 'Johdettu (LAI-skaalaus)',
            'source_type': 'derived'
        },
        'sparse_trees': {
            'min': 0.3, 'max': 2.0, 'typical_min': 0.5, 'typical_max': 1.5,
            'label': 'Harva puusto',
            'source': 'Johdettu (LAI-skaalaus)',
            'source_type': 'derived'
        },
        # Puisto / sekapuusto (LAI 2-4)
        'park': {
            'min': 0.4, 'max': 2.5, 'typical_min': 0.6, 'typical_max': 1.8,
            'label': 'Puisto',
            'source': 'Johdettu (metsä/pensas interpolointi)',
            'source_type': 'derived'
        },
        # Pensaat (LAI 2-4) - kirjallisuuspohja
        'shrub': {
            'min': 0.5, 'max': 4.0, 'typical_min': 0.8, 'typical_max': 2.5,
            'label': 'Pensaat',
            'source': 'Shaw & Schumann (1992)',
            'source_type': 'literature'
        },
        'scrub': {
            'min': 0.5, 'max': 4.0, 'typical_min': 0.8, 'typical_max': 2.5,
            'label': 'Pensaikko',
            'source': 'Shaw & Schumann (1992)',
            'source_type': 'literature'
        },
        # Pensaat + nurmi (LAI 1-3) - johdettu
        'shrub_grass': {
            'min': 0.8, 'max': 5.0, 'typical_min': 1.2, 'typical_max': 3.5,
            'label': 'Pensaat+nurmi',
            'source': 'Johdettu (yhdistelmä)',
            'source_type': 'derived'
        },
        # Puut + pensaat sekatyyppi
        'mixed': {
            'min': 0.4, 'max': 3.5, 'typical_min': 0.7, 'typical_max': 2.2,
            'label': 'Puu+pensas',
            'source': 'Johdettu (yhdistelmä)',
            'source_type': 'derived'
        },
        'tree_shrub': {
            'min': 0.4, 'max': 3.5, 'typical_min': 0.7, 'typical_max': 2.2,
            'label': 'Puu+pensas',
            'source': 'Johdettu (yhdistelmä)',
            'source_type': 'derived'
        },
        # Nurmi (LAI 1-3) - johdettu: matala k, nopea dissipation
        'grass': {
            'min': 2.0, 'max': 10.0, 'typical_min': 3.0, 'typical_max': 7.0,
            'label': 'Nurmi',
            'source': 'Johdettu (matala TKE, nopea ε)',
            'source_type': 'derived'
        },
        'lawn': {
            'min': 2.0, 'max': 10.0, 'typical_min': 3.0, 'typical_max': 7.0,
            'label': 'Nurmikko',
            'source': 'Johdettu (matala TKE, nopea ε)',
            'source_type': 'derived'
        },
    }
    
    # Kirjallisuusarvot h_c:lle [W/m²K] - konvektiivinen lämmönsiirtokerroin
    # Perustuu EN ISO 6946 h_c = f(v) -kaavaan ja tyypillisiin tuulen 
    # vaimentumiskertoimiin kasvillisuudessa (U_ref = 3-10 m/s)
    # Lähteet:
    #   - EN ISO 6946:2017 (lämmönsiirtokerroin tuulennopeudesta)
    #   - Blocken et al. (2009) Wind-driven rain & convection
    #   - Jürges (1924) Forced convection correlation
    literature_hc = {
        'dense_forest': {
            'min': 5.0, 'max': 14.0, 'typical_min': 6.0, 'typical_max': 10.0,
            'label': 'Tiheä metsä',
            'source': 'EN ISO 6946 + Blocken (2009)',
            'source_type': 'derived'
        },
        'forest': {
            'min': 6.0, 'max': 16.0, 'typical_min': 7.0, 'typical_max': 12.0,
            'label': 'Metsä',
            'source': 'EN ISO 6946 + Blocken (2009)',
            'source_type': 'derived'
        },
        'tree_zone': {
            'min': 6.0, 'max': 16.0, 'typical_min': 7.0, 'typical_max': 12.0,
            'label': 'Puusto',
            'source': 'EN ISO 6946',
            'source_type': 'derived'
        },
        'sparse_forest': {
            'min': 8.0, 'max': 20.0, 'typical_min': 9.0, 'typical_max': 16.0,
            'label': 'Harva puusto',
            'source': 'EN ISO 6946 (johdettu)',
            'source_type': 'derived'
        },
        'sparse_trees': {
            'min': 8.0, 'max': 20.0, 'typical_min': 9.0, 'typical_max': 16.0,
            'label': 'Harva puusto',
            'source': 'EN ISO 6946 (johdettu)',
            'source_type': 'derived'
        },
        'park': {
            'min': 10.0, 'max': 24.0, 'typical_min': 11.0, 'typical_max': 18.0,
            'label': 'Puisto',
            'source': 'EN ISO 6946 (johdettu)',
            'source_type': 'derived'
        },
        'shrub': {
            'min': 7.0, 'max': 18.0, 'typical_min': 8.0, 'typical_max': 14.0,
            'label': 'Pensaat',
            'source': 'EN ISO 6946 (johdettu)',
            'source_type': 'derived'
        },
        'scrub': {
            'min': 7.0, 'max': 18.0, 'typical_min': 8.0, 'typical_max': 14.0,
            'label': 'Pensaikko',
            'source': 'EN ISO 6946 (johdettu)',
            'source_type': 'derived'
        },
        'shrub_grass': {
            'min': 8.0, 'max': 22.0, 'typical_min': 10.0, 'typical_max': 18.0,
            'label': 'Pensaat+nurmi',
            'source': 'EN ISO 6946 (johdettu)',
            'source_type': 'derived'
        },
        'mixed': {
            'min': 8.0, 'max': 20.0, 'typical_min': 9.0, 'typical_max': 16.0,
            'label': 'Sekatyyppi',
            'source': 'EN ISO 6946 (johdettu)',
            'source_type': 'derived'
        },
        'tree_shrub': {
            'min': 8.0, 'max': 20.0, 'typical_min': 9.0, 'typical_max': 16.0,
            'label': 'Puu+pensas',
            'source': 'EN ISO 6946 (johdettu)',
            'source_type': 'derived'
        },
        'grass': {
            'min': 14.0, 'max': 35.0, 'typical_min': 16.0, 'typical_max': 28.0,
            'label': 'Nurmi',
            'source': 'EN ISO 6946 (johdettu)',
            'source_type': 'derived'
        },
        'lawn': {
            'min': 14.0, 'max': 35.0, 'typical_min': 16.0, 'typical_max': 28.0,
            'label': 'Nurmikko',
            'source': 'EN ISO 6946 (johdettu)',
            'source_type': 'derived'
        },
    }
    
    # Kirjallisuusarvot TI:lle [%] - box chart -muodossa
    literature_ti = {
        'dense_forest': {
            'min': 8, 'max': 22, 'typical_min': 10, 'typical_max': 20,
            'label': 'Tiheä metsä', 'source': 'Finnigan (2000)', 'source_type': 'literature'
        },
        'forest': {
            'min': 8, 'max': 22, 'typical_min': 10, 'typical_max': 20,
            'label': 'Metsä', 'source': 'Finnigan (2000)', 'source_type': 'literature'
        },
        'tree_zone': {
            'min': 8, 'max': 22, 'typical_min': 10, 'typical_max': 20,
            'label': 'Puusto', 'source': 'Finnigan (2000)', 'source_type': 'literature'
        },
        'sparse_forest': {
            'min': 6, 'max': 20, 'typical_min': 8, 'typical_max': 18,
            'label': 'Harva puusto', 'source': 'Johdettu (LAI-skaalaus)', 'source_type': 'derived'
        },
        'sparse_trees': {
            'min': 6, 'max': 20, 'typical_min': 8, 'typical_max': 18,
            'label': 'Harva puusto', 'source': 'Johdettu (LAI-skaalaus)', 'source_type': 'derived'
        },
        'park': {
            'min': 8, 'max': 24, 'typical_min': 10, 'typical_max': 22,
            'label': 'Puisto', 'source': 'Johdettu (interpolointi)', 'source_type': 'derived'
        },
        'shrub': {
            'min': 12, 'max': 32, 'typical_min': 15, 'typical_max': 30,
            'label': 'Pensaat', 'source': 'Shaw & Schumann (1992)', 'source_type': 'literature'
        },
        'scrub': {
            'min': 12, 'max': 32, 'typical_min': 15, 'typical_max': 30,
            'label': 'Pensaikko', 'source': 'Shaw & Schumann (1992)', 'source_type': 'literature'
        },
        'shrub_grass': {
            'min': 10, 'max': 27, 'typical_min': 12, 'typical_max': 25,
            'label': 'Pensaat+nurmi', 'source': 'Johdettu (yhdistelmä)', 'source_type': 'derived'
        },
        'mixed': {
            'min': 10, 'max': 27, 'typical_min': 12, 'typical_max': 25,
            'label': 'Sekatyyppi', 'source': 'Johdettu (yhdistelmä)', 'source_type': 'derived'
        },
        'tree_shrub': {
            'min': 10, 'max': 27, 'typical_min': 12, 'typical_max': 25,
            'label': 'Puu+pensas', 'source': 'Johdettu (yhdistelmä)', 'source_type': 'derived'
        },
        'grass': {
            'min': 3, 'max': 17, 'typical_min': 5, 'typical_max': 15,
            'label': 'Nurmi', 'source': 'Johdettu (matala TKE)', 'source_type': 'derived'
        },
        'lawn': {
            'min': 3, 'max': 17, 'typical_min': 5, 'typical_max': 15,
            'label': 'Nurmikko', 'source': 'Johdettu (matala TKE)', 'source_type': 'derived'
        },
    }
    
    # Kerää rakennusten pintatilastot
    building_data = []
    for entry in entries:
        sim_id = entry.get('simulation_id', '')
        project = entry.get('project_name', sim_id)
        for bld in entry.get('building_surface', []):
            if bld.get('h_c_mean') is not None:
                building_data.append({
                    'project': project,
                    'name': bld.get('building_id', 'unknown'),
                    'is_target': bld.get('is_target', False),
                    'n_wall_cells': bld.get('n_wall_cells', 0),
                    'h_c_mean': bld.get('h_c_mean', 0),
                    'h_c_min': bld.get('h_c_min', 0),
                    'h_c_max': bld.get('h_c_max', 0),
                    'h_c_p5': bld.get('h_c_p5', 0),
                    'h_c_p95': bld.get('h_c_p95', 0),
                    'u_tau_mean': bld.get('u_tau_mean', 0),
                })
    
    # Kirjallisuusarvot TI:lle [%] ja k/U²
    # Samat lähteet kuin omega-arvoille
    literature = {
        'dense_forest': {'TI': [10, 20], 'omega': [0.5, 3.0], 'k_over_U2': [0.02, 0.08], 'h_c': [5, 14], 'source': 'Finnigan (2000), Sogachev (2006)'},
        'forest': {'TI': [10, 20], 'omega': [0.5, 3.0], 'k_over_U2': [0.02, 0.08], 'h_c': [6, 16], 'source': 'Finnigan (2000), Sogachev (2006)'},
        'tree_zone': {'TI': [10, 20], 'omega': [0.5, 3.0], 'k_over_U2': [0.02, 0.08], 'h_c': [6, 16], 'source': 'Finnigan (2000)'},
        'sparse_forest': {'TI': [8, 18], 'omega': [0.3, 2.0], 'k_over_U2': [0.015, 0.06], 'h_c': [8, 20], 'source': 'Johdettu (LAI-skaalaus)'},
        'sparse_trees': {'TI': [8, 18], 'omega': [0.3, 2.0], 'k_over_U2': [0.015, 0.06], 'h_c': [8, 20], 'source': 'Johdettu (LAI-skaalaus)'},
        'park': {'TI': [10, 22], 'omega': [0.4, 2.5], 'k_over_U2': [0.02, 0.07], 'h_c': [10, 24], 'source': 'Johdettu (interpolointi)'},
        'shrub': {'TI': [15, 30], 'omega': [0.5, 4.0], 'k_over_U2': [0.03, 0.10], 'h_c': [7, 18], 'source': 'Shaw & Schumann (1992)'},
        'scrub': {'TI': [15, 30], 'omega': [0.5, 4.0], 'k_over_U2': [0.03, 0.10], 'h_c': [7, 18], 'source': 'Shaw & Schumann (1992)'},
        'shrub_grass': {'TI': [12, 25], 'omega': [0.8, 5.0], 'k_over_U2': [0.02, 0.08], 'h_c': [8, 22], 'source': 'Johdettu (yhdistelmä)'},
        'mixed': {'TI': [12, 25], 'omega': [0.4, 3.5], 'k_over_U2': [0.02, 0.08], 'h_c': [8, 20], 'source': 'Johdettu (yhdistelmä)'},
        'tree_shrub': {'TI': [12, 25], 'omega': [0.4, 3.5], 'k_over_U2': [0.02, 0.08], 'h_c': [8, 20], 'source': 'Johdettu (yhdistelmä)'},
        'grass': {'TI': [5, 15], 'omega': [2.0, 10.0], 'k_over_U2': [0.01, 0.04], 'h_c': [14, 35], 'source': 'Johdettu (matala TKE)'},
        'lawn': {'TI': [5, 15], 'omega': [2.0, 10.0], 'k_over_U2': [0.01, 0.04], 'h_c': [14, 35], 'source': 'Johdettu (matala TKE)'},
    }
    
    # Kerää järjestelmätiedot (viimeisimmästä simuloinnista)
    system_info = {}
    if entries:
        for entry in reversed(entries):
            if 'system' in entry and entry['system']:
                system_info = entry['system']
                break
    
    # Muodosta järjestelmätiedot HTML:ää varten
    sys_os = system_info.get('os', 'N/A')
    sys_cpu = system_info.get('cpu_name', system_info.get('processor', 'N/A'))
    sys_cores = system_info.get('cpu_count', 'N/A')
    sys_ram = system_info.get('ram_total_gb', 'N/A')
    sys_gpu = system_info.get('gpu_name', 'Ei GPU:ta / Ei tunnistettu')
    sys_gpu_mem = system_info.get('gpu_memory', '')
    sys_python = system_info.get('python_version', 'N/A')
    sys_numpy = system_info.get('numpy_version', 'N/A')
    sys_numba = system_info.get('numba_version', 'N/A')
    
    # Generoi simulointirivit
    simulation_rows = _generate_simulation_rows(entries[-20:])
    
    html = f'''<!DOCTYPE html>
<html lang="fi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>MikroilmastoCFD - QA Validointi Dashboard</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ 
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #f5f7fa;
            color: #333;
            line-height: 1.6;
        }}
        .header {{
            background: linear-gradient(135deg, #1a1a2e 0%, #16a085 100%);
            color: white;
            padding: 2rem;
            text-align: center;
        }}
        .header h1 {{ font-size: 2rem; margin-bottom: 0.5rem; }}
        .header p {{ opacity: 0.9; }}
        .container {{ max-width: 1400px; margin: 0 auto; padding: 2rem; }}
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 1rem;
            margin-bottom: 2rem;
        }}
        .stat-card {{
            background: white;
            border-radius: 12px;
            padding: 1.5rem;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            text-align: center;
        }}
        .stat-card .value {{ font-size: 2.5rem; font-weight: bold; color: #16a085; }}
        .stat-card .label {{ color: #666; font-size: 0.9rem; }}
        .card {{
            background: white;
            border-radius: 12px;
            padding: 1.5rem;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            margin-bottom: 1.5rem;
        }}
        .card h2 {{ 
            font-size: 1.2rem; 
            margin-bottom: 1rem; 
            padding-bottom: 0.5rem;
            border-bottom: 2px solid #16a085;
        }}
        .chart-container {{ position: relative; height: 350px; }}
        table {{ width: 100%; border-collapse: collapse; font-size: 0.9rem; }}
        th, td {{ padding: 0.75rem; text-align: left; border-bottom: 1px solid #eee; }}
        th {{ background: #f8f9fa; font-weight: 600; }}
        tr:hover {{ background: #f8f9fa; }}
        .status-ok {{ color: #27ae60; }}
        .status-warn {{ color: #f39c12; }}
        .status-bad {{ color: #e74c3c; }}
        .literature-note {{
            background: #e8f6f3;
            border-left: 4px solid #16a085;
            padding: 1rem;
            margin-top: 1rem;
            font-size: 0.85rem;
        }}
        .two-col {{ display: grid; grid-template-columns: 1fr 1fr; gap: 1.5rem; }}
        @media (max-width: 900px) {{ .two-col {{ grid-template-columns: 1fr; }} }}
        .badge {{
            display: inline-block;
            padding: 0.2rem 0.6rem;
            border-radius: 12px;
            font-size: 0.75rem;
            font-weight: 600;
        }}
        .badge-forest {{ background: #27ae60; color: white; }}
        .badge-shrub {{ background: #f39c12; color: white; }}
        .badge-grass {{ background: #3498db; color: white; }}
        .updated {{ text-align: center; color: #999; font-size: 0.8rem; margin-top: 2rem; }}
        .system-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 0.75rem;
        }}
        .system-item {{
            display: flex;
            justify-content: space-between;
            padding: 0.5rem 0;
            border-bottom: 1px solid #eee;
        }}
        .system-item:last-child {{ border-bottom: none; }}
        .system-label {{ color: #666; }}
        .system-value {{ font-weight: 600; color: #1a1a2e; }}
        .legend-custom {{
            display: flex;
            flex-wrap: wrap;
            gap: 1rem;
            margin-top: 0.5rem;
            font-size: 0.85rem;
        }}
        .legend-item {{
            display: flex;
            align-items: center;
            gap: 0.3rem;
        }}
        .legend-box {{
            width: 16px;
            height: 16px;
            border-radius: 3px;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>🌿 MikroilmastoCFD - QA Dashboard</h1>
        <p>Kasvillisuusalueiden validointitilastot</p>
    </div>
    
    <div class="container">
        <!-- Tilastot -->
        <div class="stats-grid">
            <div class="stat-card">
                <div class="value">{summary.get('total_simulations', 0)}</div>
                <div class="label">Simulointeja</div>
            </div>
            <div class="stat-card">
                <div class="value">{len(veg_data)}</div>
                <div class="label">Kasvillisuusalueita</div>
            </div>
            <div class="stat-card">
                <div class="value">{len(set(d['zone_type'] for d in veg_data))}</div>
                <div class="label">Aluetyyppejä</div>
            </div>
            <div class="stat-card">
                <div class="value">{sys_cores}</div>
                <div class="label">CPU-ytimiä</div>
            </div>
        </div>
        
        <!-- Kuvaajat -->
        <div class="two-col">
            <div class="card">
                <h2>📊 TI vs. Kirjallisuus (aluetyypeittäin)</h2>
                <div class="chart-container">
                    <canvas id="tiChart"></canvas>
                </div>
                <div class="legend-custom">
                    <div class="legend-item"><div class="legend-box" style="background:#3498db;"></div> Tyypillinen (P25-P75)</div>
                    <div class="legend-item"><div class="legend-box" style="background:#f39c12;"></div> Minimi</div>
                    <div class="legend-item"><div class="legend-box" style="background:#e74c3c;"></div> Maksimi</div>
                    <div class="legend-item"><div class="legend-box" style="background:rgba(39,174,96,0.5); border: 2px solid #27ae60;"></div> 📚 Kirjallisuus</div>
                    <div class="legend-item"><div class="legend-box" style="background:rgba(155,89,182,0.5); border: 2px dashed #9b59b6;"></div> 📐 Johdettu</div>
                </div>
                <div class="literature-note">
                    <strong>📚 Kirjallisuuslähteet:</strong> Metsä TI 10–20% (Finnigan 2000), 
                    Pensaikko TI 15–30% (Shaw & Schumann 1992)<br>
                    <strong>📐 Johdetut arvot:</strong> Harva puusto, puisto, nurmi - johdettu LAI-skaalauksella
                </div>
            </div>
            
            <div class="card">
                <h2>📊 ω vs. Kirjallisuus (aluetyypeittäin)</h2>
                <div class="chart-container">
                    <canvas id="omegaChart"></canvas>
                </div>
                <div class="legend-custom">
                    <div class="legend-item"><div class="legend-box" style="background:#3498db;"></div> Tyypillinen (P25-P75)</div>
                    <div class="legend-item"><div class="legend-box" style="background:#f39c12;"></div> Minimi</div>
                    <div class="legend-item"><div class="legend-box" style="background:#e74c3c;"></div> Maksimi</div>
                    <div class="legend-item"><div class="legend-box" style="background:rgba(39,174,96,0.5); border: 2px solid #27ae60;"></div> 📚 Kirjallisuus</div>
                    <div class="legend-item"><div class="legend-box" style="background:rgba(155,89,182,0.5); border: 2px dashed #9b59b6;"></div> 📐 Johdettu</div>
                </div>
                <div class="literature-note">
                    <strong>📚 Kirjallisuuslähteet:</strong> Metsä/puusto: Finnigan (2000), Sogachev (2006), Katul et al. (2004); 
                    Pensaat: Shaw & Schumann (1992)<br>
                    <strong>📐 Johdetut arvot:</strong> Harva puusto, puisto, nurmi, sekatyypit - johdettu LAI-skaalauksella ja fysikaalisilla periaatteilla
                </div>
            </div>
        </div>
        
        <!-- h_c kaavio - kasvillisuus -->
        <div class="card">
            <h2>📊 h<sub>c</sub> — Kasvillisuusalueen lämmönsiirtokerroin vs. Kirjallisuus</h2>
            <div class="chart-container">
                <canvas id="hcChart"></canvas>
            </div>
            <div class="legend-custom">
                <div class="legend-item"><div class="legend-box" style="background:#3498db;"></div> Tyypillinen (P25-P75)</div>
                <div class="legend-item"><div class="legend-box" style="background:#f39c12;"></div> Minimi</div>
                <div class="legend-item"><div class="legend-box" style="background:#e74c3c;"></div> Maksimi</div>
                <div class="legend-item"><div class="legend-box" style="background:rgba(155,89,182,0.5); border: 2px dashed #9b59b6;"></div> 📐 Johdettu</div>
            </div>
            <div class="literature-note">
                <strong>📐 Lämmönsiirtokerroin:</strong> h<sub>c</sub> = 4 + 4v (v ≤ 5 m/s), h<sub>c</sub> = 7.1v<sup>0.78</sup> (v &gt; 5 m/s) — EN ISO 6946:2017<br>
                <strong>Lähteet:</strong> EN ISO 6946:2017, Blocken et al. (2009), Jürges (1924)
            </div>
        </div>
        
        <!-- h_c kaavio - rakennuspinnat -->
        <div class="card" id="bldHcSection">
            <h2>🏢 Rakennuspinnan lämmönsiirtokerroin h<sub>c</sub> (u<sub>τ</sub>-menetelmä)</h2>
            <div class="chart-container">
                <canvas id="bldHcChart"></canvas>
            </div>
            <div class="literature-note">
                <strong>Laskenta:</strong> h<sub>c</sub> = ρ·c<sub>p</sub>·u<sub>τ</sub> / T<sup>+</sup>, missä u<sub>τ</sub> = C<sub>μ</sub><sup>0.25</sup>·√k (SST k-ω)<br>
                T<sup>+</sup> Jayatilleken (1969) termisestä seinäfunktiosta (Pr = 0.71)<br>
                <strong>Viitteet:</strong> EN ISO 6946 h<sub>c,e</sub> ≈ 20 W/m²K, Blocken et al. (2009): 5–40 W/m²K, 
                Defraeye et al. (2011), Hagishima & Tanimoto (2003)
            </div>
        </div>
        
        <!-- Validointitaulukko -->
        <div class="card">
            <h2>✅ Validointi vs. Kirjallisuusarvot</h2>
            <table>
                <thead>
                    <tr>
                        <th>Suure</th>
                        <th>Simuloitu</th>
                        <th>Kirjallisuus</th>
                        <th>Lähde</th>
                        <th>Tila</th>
                    </tr>
                </thead>
                <tbody id="validationTable">
                </tbody>
            </table>
        </div>
        
        <!-- Järjestelmätiedot -->
        <div class="card">
            <h2>💻 Järjestelmätiedot</h2>
            <div class="system-grid">
                <div class="system-item">
                    <span class="system-label">Käyttöjärjestelmä</span>
                    <span class="system-value">{sys_os}</span>
                </div>
                <div class="system-item">
                    <span class="system-label">CPU</span>
                    <span class="system-value">{sys_cpu}</span>
                </div>
                <div class="system-item">
                    <span class="system-label">CPU-ytimet</span>
                    <span class="system-value">{sys_cores}</span>
                </div>
                <div class="system-item">
                    <span class="system-label">RAM</span>
                    <span class="system-value">{sys_ram} GB</span>
                </div>
                <div class="system-item">
                    <span class="system-label">GPU</span>
                    <span class="system-value">{sys_gpu} {sys_gpu_mem}</span>
                </div>
                <div class="system-item">
                    <span class="system-label">Python</span>
                    <span class="system-value">{sys_python}</span>
                </div>
                <div class="system-item">
                    <span class="system-label">NumPy</span>
                    <span class="system-value">{sys_numpy}</span>
                </div>
                <div class="system-item">
                    <span class="system-label">Numba</span>
                    <span class="system-value">{sys_numba}</span>
                </div>
            </div>
        </div>
        
        <!-- Simulointiloki -->
        <div class="card">
            <h2>📋 Viimeisimmät simuloinnit</h2>
            <table>
                <thead>
                    <tr>
                        <th>Päivämäärä</th>
                        <th>Projekti</th>
                        <th>Tyyppi</th>
                        <th>Kasv.alueet</th>
                        <th>TI (ka.)</th>
                        <th>Kesto</th>
                        <th>Konvergenssi</th>
                    </tr>
                </thead>
                <tbody>
                    {simulation_rows}
                </tbody>
            </table>
        </div>
        
        <p class="updated">Päivitetty: {datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</p>
    </div>
    
    <script>
        const vegData = {json.dumps(veg_data)};
        const literature = {json.dumps(literature)};
        const literatureOmega = {json.dumps(literature_omega)};
        const literatureHc = {json.dumps(literature_hc)};
        const literatureTi = {json.dumps(literature_ti)};
        const buildingData = {json.dumps(building_data)};
        
        // TI Chart - luodaan createBoxChart-kutsulla myöhemmin
        const tiCtx = document.getElementById('tiChart').getContext('2d');
        
        // ================================================================
        // OMEGA CHART - Aluetyypeittäin (uusi toteutus)
        // ================================================================
        const omegaCtx = document.getElementById('omegaChart').getContext('2d');
        
        // Aggregoi data aluetyypin mukaan
        function aggregateByZoneType(data, valueKey) {{
            const grouped = {{}};
            const excludeTypes = ['road', 'lake', 'water', 'pond', 'river', 'parking', 'sand', 'bare', 'wetland', 'reed'];
            
            data.forEach(d => {{
                // Kategorisoi zone_type
                let category = (d.zone_type || '').toLowerCase();
                let litKey = d.zone_type;
                
                // Ohita ei-kasvillisuustyypit
                if (excludeTypes.some(ex => category.includes(ex))) return;
                
                // Ohita null/undefined arvot
                const val = d[valueKey];
                if (val === null || val === undefined) return;
                
                // Tiheä metsä
                if (category.includes('dense') && (category.includes('forest') || category.includes('tree'))) {{
                    category = 'Tiheä metsä';
                    litKey = 'dense_forest';
                }}
                // Harva puusto
                else if (category.includes('sparse') && (category.includes('forest') || category.includes('tree'))) {{
                    category = 'Harva puusto';
                    litKey = 'sparse_forest';
                }}
                // Puisto
                else if (category.includes('park') || category.includes('puisto')) {{
                    category = 'Puisto';
                    litKey = 'park';
                }}
                // Puu + pensas sekatyyppi
                else if ((category.includes('tree') && category.includes('shrub')) || 
                         (category.includes('puu') && category.includes('pensas'))) {{
                    category = 'Puu+pensas';
                    litKey = 'tree_shrub';
                }}
                // Pensaat + nurmi
                else if ((category.includes('shrub') && category.includes('grass')) ||
                         (category.includes('pensas') && category.includes('nurm'))) {{
                    category = 'Pensaat+nurmi';
                    litKey = 'shrub_grass';
                }}
                // Yleinen metsä/puusto
                else if (category.includes('tree') || category.includes('forest') || category.includes('metsa')) {{
                    category = 'Metsä/Puusto';
                    litKey = 'forest';
                }}
                // Pensaat
                else if (category.includes('shrub') || category.includes('scrub') || category.includes('pensas')) {{
                    category = 'Pensaat';
                    litKey = 'shrub';
                }}
                // Nurmi
                else if (category.includes('grass') || category.includes('lawn') || category.includes('nurm')) {{
                    category = 'Nurmi';
                    litKey = 'grass';
                }}
                // Piha-alueet (tarkista ennen mixed koska yard_mixed → Piha)
                else if (category.includes('yard') || category.includes('piha')) {{
                    category = 'Piha';
                    litKey = 'shrub_grass';
                }}
                // Sekatyyppi (yleinen)
                else if (category.includes('mixed') || category.includes('seka')) {{
                    category = 'Sekatyyppi';
                    litKey = 'mixed';
                }}
                // Tuntematon → ohita
                else {{
                    return;
                }}
                
                if (!grouped[category]) {{
                    grouped[category] = {{values: [], litKey: litKey}};
                }}
                grouped[category].values.push(val);
            }});
            
            return grouped;
        }}
        
        // Laske tilastot (min, p25, p75, max)
        function calcStats(values) {{
            if (values.length === 0) return null;
            const sorted = [...values].sort((a, b) => a - b);
            const n = sorted.length;
            
            let min = sorted[0];
            let p25 = sorted[Math.floor(n * 0.25)] || sorted[0];
            let median = sorted[Math.floor(n * 0.5)] || sorted[0];
            let p75 = sorted[Math.ceil(n * 0.75) - 1] || sorted[n-1];
            let max = sorted[n - 1];
            const mean = values.reduce((a, b) => a + b, 0) / n;
            
            // Kun n < 3, persentiilit kollapsoituvat → palkit näkymättömiä
            // Lisää minimipaksuus ±5% keskiarvosta (vähintään ±0.1)
            if (n <= 2) {{
                const spread = Math.max(mean * 0.05, 0.1);
                if (p25 === min) p25 = Math.max(min, mean - spread);
                if (p75 === max) p75 = Math.min(max, mean + spread);
                // Varmista järjestys
                if (p25 > median) p25 = median;
                if (p75 < median) p75 = median;
                // Varmista min/max eri kuin p25/p75
                if (min === p25) min = Math.max(0, p25 - spread);
                if (max === p75) max = p75 + spread;
            }}
            
            return {{ min, p25, median, p75, max, mean, count: n }};
        }}
        
        const grouped = aggregateByZoneType(vegData, 'omega_mean');
        
        // ================================================================
        // Uudelleenkäytettävä kaavio-funktio (floating bars + dynaaminen min)
        // ================================================================
        function createBoxChart(ctx, grouped, litData, yLabel, yUnit, defaultMax) {{
            const categories = Object.keys(grouped);
            const labels = [];
            const allData = [];
            
            categories.forEach(cat => {{
                const groupInfo = grouped[cat];
                const stats = calcStats(groupInfo.values);
                if (stats) {{
                    labels.push(cat + ' (sim.)');
                    allData.push(stats);
                    
                    const litKey = groupInfo.litKey;
                    if (litData[litKey]) {{
                        const lit = litData[litKey];
                        const sourceType = lit.source_type || 'unknown';
                        const sourceIcon = sourceType === 'literature' ? '📚' : '📐';
                        labels.push(lit.label + ' ' + sourceIcon);
                        allData.push({{
                            min: lit.min, p25: lit.typical_min,
                            p75: lit.typical_max, max: lit.max,
                            isLiterature: true, sourceType: sourceType, source: lit.source
                        }});
                    }}
                }}
            }});
            
            if (categories.length === 0) {{
                const defaultTypes = ['forest', 'sparse_forest', 'park', 'shrub', 'shrub_grass', 'grass'];
                defaultTypes.forEach(litKey => {{
                    if (litData[litKey]) {{
                        const lit = litData[litKey];
                        const sourceType = lit.source_type || 'unknown';
                        const sourceIcon = sourceType === 'literature' ? '📚' : '📐';
                        labels.push(lit.label + ' ' + sourceIcon);
                        allData.push({{
                            min: lit.min, p25: lit.typical_min,
                            p75: lit.typical_max, max: lit.max,
                            isLiterature: true, sourceType: sourceType, source: lit.source
                        }});
                    }}
                }});
            }}
            
            if (allData.length === 0) return;
            
            // Dynaaminen y-akselin minimi — ei aloiteta nollasta
            const globalMin = Math.min(...allData.map(d => d ? d.min : Infinity));
            const yMin = globalMin > 2 ? Math.floor(globalMin * 0.8) : 0;
            
            // Floating bars: [low, high] per segmentti
            new Chart(ctx, {{
                type: 'bar',
                data: {{
                    labels: labels,
                    datasets: [
                        {{
                            label: 'Min → P25',
                            data: allData.map(d => d ? [d.min, d.p25] : [0, 0]),
                            backgroundColor: allData.map(d => {{
                                if (!d || !d.isLiterature) return '#f39c12';
                                return d.sourceType === 'literature' ? 'rgba(39,174,96,0.3)' : 'rgba(155,89,182,0.3)';
                            }}),
                            borderColor: allData.map(d => {{
                                if (!d || !d.isLiterature) return '#d68910';
                                return d.sourceType === 'literature' ? '#27ae60' : '#9b59b6';
                            }}),
                            borderWidth: 1,
                        }},
                        {{
                            label: 'P25 → P75 (tyypillinen)',
                            data: allData.map(d => d ? [d.p25, d.p75] : [0, 0]),
                            backgroundColor: allData.map(d => {{
                                if (!d || !d.isLiterature) return '#3498db';
                                return d.sourceType === 'literature' ? 'rgba(39,174,96,0.5)' : 'rgba(155,89,182,0.5)';
                            }}),
                            borderColor: allData.map(d => {{
                                if (!d || !d.isLiterature) return '#2980b9';
                                return d.sourceType === 'literature' ? '#27ae60' : '#9b59b6';
                            }}),
                            borderWidth: 1,
                        }},
                        {{
                            label: 'P75 → Max',
                            data: allData.map(d => d ? [d.p75, d.max] : [0, 0]),
                            backgroundColor: allData.map(d => {{
                                if (!d || !d.isLiterature) return '#e74c3c';
                                return d.sourceType === 'literature' ? 'rgba(39,174,96,0.3)' : 'rgba(155,89,182,0.3)';
                            }}),
                            borderColor: allData.map(d => {{
                                if (!d || !d.isLiterature) return '#c0392b';
                                return d.sourceType === 'literature' ? '#27ae60' : '#9b59b6';
                            }}),
                            borderWidth: 1,
                        }}
                    ]
                }},
                options: {{
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {{
                        legend: {{ display: false }},
                        tooltip: {{
                            callbacks: {{
                                label: function(context) {{
                                    const idx = context.dataIndex;
                                    const d = allData[idx];
                                    if (!d) return '';
                                    if (d.isLiterature) {{
                                        const typeLabel = d.sourceType === 'literature' ? 'Kirjallisuus' : 'Johdettu';
                                        return [
                                            `${{typeLabel}}:`,
                                            `  Min: ${{d.min.toFixed(1)}} ${{yUnit}}`,
                                            `  Tyypillinen: ${{d.p25.toFixed(1)}}–${{d.p75.toFixed(1)}} ${{yUnit}}`,
                                            `  Max: ${{d.max.toFixed(1)}} ${{yUnit}}`,
                                            `  Lähde: ${{d.source}}`
                                        ];
                                    }}
                                    return [
                                        `Simuloitu (n=${{d.count}}):`,
                                        `  Min: ${{d.min.toFixed(1)}} ${{yUnit}}`,
                                        `  P25: ${{d.p25.toFixed(1)}} ${{yUnit}}`,
                                        `  Mediaani: ${{d.median.toFixed(1)}} ${{yUnit}}`,
                                        `  P75: ${{d.p75.toFixed(1)}} ${{yUnit}}`,
                                        `  Max: ${{d.max.toFixed(1)}} ${{yUnit}}`,
                                        `  Ka: ${{d.mean.toFixed(1)}} ${{yUnit}}`
                                    ];
                                }}
                            }}
                        }}
                    }},
                    scales: {{
                        x: {{ 
                            stacked: true,
                            ticks: {{ maxRotation: 45, minRotation: 45 }}
                        }},
                        y: {{ 
                            title: {{ display: true, text: yLabel }}, 
                            min: yMin,
                            max: Math.max(defaultMax, ...allData.map(d => d ? d.max : 0)) * 1.15
                        }}
                    }}
                }}
            }});
        }}
        
        // TI chart
        createBoxChart(tiCtx, aggregateByZoneType(vegData, 'TI_mean'), literatureTi, 'TI [%]', '%', 35);
        
        // Omega chart
        createBoxChart(omegaCtx, aggregateByZoneType(vegData, 'omega_mean'), literatureOmega, 'ω [1/s]', '1/s', 10);
        
        // h_c kasvillisuus chart
        const hcCtx = document.getElementById('hcChart').getContext('2d');
        createBoxChart(hcCtx, aggregateByZoneType(vegData, 'h_c_mean'), literatureHc, 'h_c [W/m²K]', 'W/m²K', 30);
        
        // ================================================================
        // RAKENNUS h_c KAAVIO (u_tau -menetelmä)
        // ================================================================
        const bldSection = document.getElementById('bldHcSection');
        if (buildingData.length > 0) {{
            const bldCtx = document.getElementById('bldHcChart').getContext('2d');
            
            // Referenssilinja EN ISO 6946
            const refLine = Array(buildingData.length).fill(20);
            
            new Chart(bldCtx, {{
                type: 'bar',
                data: {{
                    labels: buildingData.map(d => d.name + (d.is_target ? ' ⭐' : '')),
                    datasets: [
                        {{
                            label: 'h_c P5–P95',
                            data: buildingData.map(d => [d.h_c_p5, d.h_c_p95]),
                            backgroundColor: buildingData.map(d => d.is_target 
                                ? 'rgba(231,76,60,0.25)' : 'rgba(52,152,219,0.25)'),
                            borderColor: buildingData.map(d => d.is_target 
                                ? '#c0392b' : '#2980b9'),
                            borderWidth: 1,
                            barPercentage: 0.6,
                        }},
                        {{
                            label: 'h_c keskiarvo',
                            data: buildingData.map(d => [d.h_c_mean - 0.3, d.h_c_mean + 0.3]),
                            backgroundColor: buildingData.map(d => d.is_target 
                                ? 'rgba(231,76,60,0.9)' : 'rgba(52,152,219,0.9)'),
                            borderColor: buildingData.map(d => d.is_target 
                                ? '#c0392b' : '#2980b9'),
                            borderWidth: 1,
                            barPercentage: 0.9,
                        }},
                        {{
                            type: 'line',
                            label: 'EN ISO 6946 h_c,e ≈ 20 W/m²K',
                            data: refLine,
                            borderColor: '#27ae60',
                            borderWidth: 2,
                            borderDash: [6, 4],
                            pointRadius: 0,
                            fill: false,
                        }}
                    ]
                }},
                options: {{
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {{
                        legend: {{ display: true, position: 'bottom', labels: {{ font: {{ size: 11 }} }} }},
                        tooltip: {{
                            callbacks: {{
                                label: function(ctx) {{
                                    const i = ctx.dataIndex;
                                    const d = buildingData[i];
                                    if (!d) return '';
                                    if (ctx.dataset.type === 'line') return 'EN ISO 6946: 20 W/m²K';
                                    return [
                                        `h_c ka: ${{d.h_c_mean.toFixed(1)}} W/m²K`,
                                        `P5–P95: ${{d.h_c_p5.toFixed(1)}}–${{d.h_c_p95.toFixed(1)}} W/m²K`,
                                        `Min–Max: ${{d.h_c_min.toFixed(1)}}–${{d.h_c_max.toFixed(1)}} W/m²K`,
                                        `u_τ ka: ${{d.u_tau_mean.toFixed(3)}} m/s`,
                                        `Seinäsoluja: ${{d.n_wall_cells}}`
                                    ];
                                }}
                            }}
                        }}
                    }},
                    scales: {{
                        x: {{ 
                            stacked: true,
                            ticks: {{ maxRotation: 45, minRotation: 45 }}
                        }},
                        y: {{ 
                            title: {{ display: true, text: 'h_c [W/m²K]' }},
                            min: Math.max(0, Math.floor(Math.min(...buildingData.map(d => d.h_c_p5)) * 0.8)),
                            max: Math.max(35, Math.max(...buildingData.map(d => d.h_c_p95)) * 1.15)
                        }}
                    }}
                }}
            }});
        }} else {{
            bldSection.innerHTML = '<h2>🏢 Rakennuspinnan h<sub>c</sub></h2><p style="color:#999;text-align:center;padding:2rem;">Ei rakennusdataa — lisää <code>qa.extract_building_surface_statistics(solver, config)</code> simulointikoodiin</p>';
        }}
        
        // Validation table
        function generateValidationTable() {{
            const tbody = document.getElementById('validationTable');
            
            const tiGrouped = aggregateByZoneType(vegData, 'TI_mean');
            const omegaGrouped = aggregateByZoneType(vegData, 'omega_mean');
            const hcGrouped = aggregateByZoneType(vegData, 'h_c_mean');
            
            const rows = [];
            
            // Validointirajat aluetyypeittäin
            const validationLimits = {{
                'dense_forest': {{ TI: [10, 20], omega: [0.5, 3.0], h_c: [5, 14], label: 'Tiheä metsä', source_TI: 'Finnigan (2000)', source_omega: 'Sogachev (2006)', source_hc: 'EN ISO 6946 + Blocken (2009)' }},
                'forest': {{ TI: [10, 20], omega: [0.5, 3.0], h_c: [6, 16], label: 'Metsä', source_TI: 'Finnigan (2000)', source_omega: 'Sogachev (2006)', source_hc: 'EN ISO 6946' }},
                'sparse_forest': {{ TI: [8, 18], omega: [0.3, 2.0], h_c: [8, 20], label: 'Harva puusto', source_TI: 'Johdettu', source_omega: 'Johdettu', source_hc: 'EN ISO 6946' }},
                'park': {{ TI: [10, 22], omega: [0.4, 2.5], h_c: [10, 24], label: 'Puisto', source_TI: 'Johdettu', source_omega: 'Johdettu', source_hc: 'EN ISO 6946' }},
                'shrub': {{ TI: [15, 30], omega: [0.5, 4.0], h_c: [7, 18], label: 'Pensaat', source_TI: 'Shaw & Schumann', source_omega: 'Shaw & Schumann', source_hc: 'EN ISO 6946' }},
                'shrub_grass': {{ TI: [12, 25], omega: [0.8, 5.0], h_c: [8, 22], label: 'Piha/Pensaat+nurmi', source_TI: 'Johdettu', source_omega: 'Johdettu', source_hc: 'EN ISO 6946' }},
                'grass': {{ TI: [5, 15], omega: [2.0, 10.0], h_c: [14, 35], label: 'Nurmi', source_TI: 'Johdettu', source_omega: 'Johdettu', source_hc: 'EN ISO 6946' }},
                'mixed': {{ TI: [12, 25], omega: [0.4, 3.5], h_c: [8, 20], label: 'Sekatyyppi', source_TI: 'Johdettu', source_omega: 'Johdettu', source_hc: 'EN ISO 6946' }}
            }};
            
            Object.keys(tiGrouped).forEach(category => {{
                const tiInfo = tiGrouped[category];
                const omegaInfo = omegaGrouped[category];
                const hcInfo = hcGrouped ? hcGrouped[category] : null;
                const litKey = tiInfo.litKey;
                const limits = validationLimits[litKey] || validationLimits['mixed'];
                
                const tiVals = tiInfo.values;
                const omegaVals = omegaInfo ? omegaInfo.values : [];
                const hcVals = hcInfo ? hcInfo.values.filter(v => v !== null && v !== undefined) : [];
                
                if (tiVals.length > 0) {{
                    const tiMin = Math.min(...tiVals);
                    const tiMax = Math.max(...tiVals);
                    const tiRange = tiVals.length === 1 ? `${{tiMin.toFixed(1)}}%` : `${{tiMin.toFixed(1)}}-${{tiMax.toFixed(1)}}%`;
                    const tiOk = tiMin >= limits.TI[0] && tiMax <= limits.TI[1];
                    rows.push([`TI: ${{category}}`, `${{tiRange}} (n=${{tiVals.length}})`, `${{limits.TI[0]}}-${{limits.TI[1]}}%`, limits.source_TI, tiOk]);
                }}
                
                if (omegaVals.length > 0) {{
                    const omegaMin = Math.min(...omegaVals);
                    const omegaMax = Math.max(...omegaVals);
                    const omegaRange = omegaVals.length === 1 ? `${{omegaMin.toFixed(2)}} 1/s` : `${{omegaMin.toFixed(2)}}-${{omegaMax.toFixed(2)}} 1/s`;
                    const omegaOk = omegaMin >= limits.omega[0] && omegaMax <= limits.omega[1];
                    rows.push([`ω: ${{category}}`, `${{omegaRange}} (n=${{omegaVals.length}})`, `${{limits.omega[0]}}-${{limits.omega[1]}} 1/s`, limits.source_omega, omegaOk]);
                }}
                
                if (hcVals.length > 0 && limits.h_c) {{
                    const hcMin = Math.min(...hcVals);
                    const hcMax = Math.max(...hcVals);
                    const hcRange = hcVals.length === 1 ? `${{hcMin.toFixed(1)}} W/m²K` : `${{hcMin.toFixed(1)}}-${{hcMax.toFixed(1)}} W/m²K`;
                    const hcOk = hcMin >= limits.h_c[0] && hcMax <= limits.h_c[1];
                    rows.push([`h_c: ${{category}}`, `${{hcRange}} (n=${{hcVals.length}})`, `${{limits.h_c[0]}}-${{limits.h_c[1]}} W/m²K`, limits.source_hc, hcOk]);
                }}
            }});
            
            // Rakennus h_c validointi
            if (buildingData.length > 0) {{
                const targetBld = buildingData.find(d => d.is_target) || buildingData[0];
                const hcRange = `${{targetBld.h_c_p5.toFixed(1)}}–${{targetBld.h_c_p95.toFixed(1)}} W/m²K`;
                const hcOk = targetBld.h_c_mean >= 5 && targetBld.h_c_mean <= 40;
                rows.push([
                    `🏢 h_c: ${{targetBld.name}}`, 
                    `${{hcRange}} (ka ${{targetBld.h_c_mean.toFixed(1)}})`,
                    '8–35 W/m²K', 
                    'EN ISO 6946 + Blocken (2009)',
                    hcOk
                ]);
            }}
            
            if (rows.length === 0) {{
                tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;color:#999;">Ei kasvillisuusdataa vielä</td></tr>';
                return;
            }}
            
            tbody.innerHTML = rows.map(r => `
                <tr>
                    <td>${{r[0]}}</td>
                    <td><strong>${{r[1]}}</strong></td>
                    <td>${{r[2]}}</td>
                    <td>${{r[3]}}</td>
                    <td class="${{r[4] ? 'status-ok' : 'status-warn'}}">${{r[4] ? '✓ OK' : '⚠ Tarkista'}}</td>
                </tr>
            `).join('');
        }}
        
        generateValidationTable();
    </script>
</body>
</html>'''
    
    return html


def _generate_simulation_rows(entries: list) -> str:
    """
    Generoi simulointirivit HTML-taulukkoon.
    
    Args:
        entries: Lista simulointimerkinnöistä
        
    Returns:
        HTML-merkkijono taulukon riveistä
    """
    rows = []
    for entry in reversed(entries):
        timestamp = entry.get('timestamp', '')[:10]
        project = entry.get('project_name', entry.get('simulation_id', '-'))[:25]
        sim_type = entry.get('simulation', {}).get('simulation_type', 'standard')
        veg_zones = entry.get('vegetation_validation', [])
        n_zones = len(veg_zones)
        
        ti_mean = '-'
        if veg_zones:
            ti_vals = [z.get('TI_mean', 0) for z in veg_zones]
            ti_mean = f"{sum(ti_vals)/len(ti_vals):.1f}%"
        
        duration = entry.get('duration_seconds', 0)
        if duration >= 3600:
            duration_str = f"{duration/3600:.1f}h"
        elif duration >= 60:
            duration_str = f"{duration/60:.1f}min"
        else:
            duration_str = f"{duration:.0f}s"
        
        conv = entry.get('convergence', {})
        conv_status = '✓' if conv.get('converged', True) else '✗'
        conv_class = 'status-ok' if conv.get('converged', True) else 'status-bad'
        
        rows.append(f'''<tr>
            <td>{timestamp}</td>
            <td>{project}</td>
            <td>{sim_type}</td>
            <td>{n_zones}</td>
            <td>{ti_mean}</td>
            <td>{duration_str}</td>
            <td class="{conv_class}">{conv_status}</td>
        </tr>''')
    
    return '\n'.join(rows) if rows else '<tr><td colspan="7" style="text-align:center;color:#999;">Ei simulointeja vielä</td></tr>'
