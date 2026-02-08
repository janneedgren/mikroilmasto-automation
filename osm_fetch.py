#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OSM-geometrian tuonti komentoriviltä tai konfiguraatiotiedostosta.

Käyttö:
    # Koordinaateilla
    python osm_fetch.py --lat 61.0045 --lon 24.1005 --radius 300 --output parola.json
    
    # Osoitteella
    python osm_fetch.py --address "Mannerheimintie 1, Helsinki" --radius 200 --output keskusta.json
    
    # Konfiguraatiotiedostosta
    python osm_fetch.py --config locations.json
    
    # Simuloi suoraan
    python osm_fetch.py --lat 60.1699 --lon 24.9384 --radius 150 --simulate
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


def load_config_file(config_path: str) -> tuple:
    """
    Lataa konfiguraatiotiedosto.
    
    Tiedostomuoto (JSON):
    {
        "locations": [
            {
                "address": "Mannerheimintie 1, Helsinki",
                "radius": 200,
                "output": "mansku.json",
                "name": "Mannerheimintie",
                "velocity": 5.0
            },
            {
                "lat": 61.0045,
                "lon": 24.1005,
                "radius": 300,
                "output": "parola.json"
            }
        ],
        "defaults": {
            "radius": 250,
            "velocity": 5.0,
            "resolution": 1.0,
            "no_trees": false,
            "no_forests": false,
            "no_vegetation": false,
            "min_forest_area": 100.0,
            "min_vegetation_area": 50.0
        },
        "simulation": {
            "enabled": true,
            "iterations": 500,
            "turbulence": "sst",
            "wall_functions": true,
            "auto_nested": true,
            "nested_margin": 15,
            "refinement": 4,
            "match_scale": true,
            "crop": 50
        }
    }
    """
    with open(config_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # Tukee sekä listaa että objektia jossa "locations"
    if isinstance(data, list):
        return data, {}, {}
    elif isinstance(data, dict):
        locations = data.get('locations', [data])  # Yksittäinen sijainti tai lista
        defaults = data.get('defaults', {})
        simulation = data.get('simulation', {})
        return locations, defaults, simulation
    else:
        raise ValueError("Konfiguraatiotiedoston tulee olla lista tai objekti")


def main():
    parser = argparse.ArgumentParser(
        description='Tuo rakennusgeometria OpenStreetMapista CFD-simulaatioon',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Esimerkkejä:
  # Parolan kasarmi koordinaateilla
  python osm_fetch.py --lat 61.0045 --lon 24.1005 --radius 300 -o parola.json
  
  # Helsingin keskusta osoitteella
  python osm_fetch.py --address "Rautatientori, Helsinki" --radius 200 -o rautatientori.json
  
  # Konfiguraatiotiedostosta (useita sijainteja kerralla)
  python osm_fetch.py --config locations.json
  
  # Hae ja simuloi suoraan
  python osm_fetch.py --lat 60.1699 --lon 24.9384 --radius 150 --simulate
  
  # Ilman puita, tarkempi hila
  python osm_fetch.py --address "Kamppi, Helsinki" -r 250 --no-trees --resolution 0.5 -o kamppi.json
  
  # Vain rakennukset (ei metsää, ei kasvillisuutta, ei puita)
  python osm_fetch.py --address "Pasila, Helsinki" -r 300 --no-trees --no-forests --no-vegetation -o pasila.json
  
  # Metsäalueet mukaan, mutta ei matala kasvillisuutta
  python osm_fetch.py --lat 61.0 --lon 24.1 -r 400 --no-vegetation --min-forest-area 200 -o maaseutu.json

Konfiguraatiotiedoston muoto (JSON):
  {
    "locations": [
      {"address": "Osoite 1", "radius": 200, "output": "kohde1.json"},
      {"lat": 60.17, "lon": 24.94, "radius": 150, "output": "kohde2.json"}
    ],
    "defaults": {"radius": 250, "velocity": 5.0, "no_forests": false, "no_vegetation": false}
  }
        """
    )
    
    # Konfiguraatiotiedosto
    parser.add_argument('--config', '-c', type=str, 
                        help='JSON-konfiguraatiotiedosto (useita sijainteja)')
    
    # Sijainti
    loc_group = parser.add_argument_group('Sijainti (valitse toinen)')
    loc_group.add_argument('--lat', type=float, help='Leveysaste (WGS84)')
    loc_group.add_argument('--lon', type=float, help='Pituusaste (WGS84)')
    loc_group.add_argument('--address', '-a', type=str, help='Osoite (geokoodataan automaattisesti)')
    
    # Asetukset
    parser.add_argument('--radius', '-r', type=float, default=300,
                        help='Hakusäde metreinä (oletus: 300)')
    parser.add_argument('--output', '-o', type=str, default=None,
                        help='Tulostiedosto (oletus: osm_geometry.json)')
    parser.add_argument('--name', '-n', type=str, default=None,
                        help='Tapauksen nimi')
    
    # Simulaatioasetukset
    parser.add_argument('--velocity', '-v', type=float, default=5.0,
                        help='Tuulen nopeus m/s (oletus: 5.0)')
    parser.add_argument('--resolution', type=float, default=1.0,
                        help='Hilaresoluutio m/solu (oletus: 1.0)')
    parser.add_argument('--no-trees', action='store_true',
                        help='Älä hae yksittäisiä puita')
    parser.add_argument('--no-forests', action='store_true',
                        help='Älä hae metsäalueita (tree_zone)')
    parser.add_argument('--no-vegetation', action='store_true',
                        help='Älä hae kasvillisuusalueita (vegetation_zone)')
    parser.add_argument('--no-roads', action='store_true',
                        help='Älä hae teitä')
    parser.add_argument('--min-area', type=float, default=20.0,
                        help='Minimi rakennuskoko m² (oletus: 20)')
    parser.add_argument('--min-forest-area', type=float, default=100.0,
                        help='Minimi metsäalueen koko m² (oletus: 100)')
    parser.add_argument('--min-vegetation-area', type=float, default=50.0,
                        help='Minimi kasvillisuusalueen koko m² (oletus: 50)')
    
    # Toiminnot
    parser.add_argument('--simulate', '-s', action='store_true',
                        help='Aja simulaatio heti tuonnin jälkeen')
    parser.add_argument('--iterations', '-i', type=int, default=400,
                        help='Simulaation iteraatiot (oletus: 400)')
    parser.add_argument('--no-zone-editor', action='store_true',
                        help='Älä luo zone editor HTML-tiedostoa')
    
    args = parser.parse_args()
    
    # Jos konfiguraatiotiedosto annettu, käsittele se
    if args.config:
        process_config_file(args)
        return
    
    # Tarkista sijainti
    if args.address is None and (args.lat is None or args.lon is None):
        parser.error("Anna joko --address TAI --lat ja --lon TAI --config")
    
    # Käsittele yksittäinen sijainti
    process_single_location(args)


def generate_zone_editor(geometry_path: Path, identify_zones: bool = True) -> Path:
    """
    Luo zone editor HTML-tiedoston geometriatiedoston viereen.
    
    Args:
        geometry_path: Polku geometriatiedostoon
        identify_zones: Tunnista alueet automaattisesti
    
    Returns:
        Polku luotuun HTML-tiedostoon
    """
    # Etsi zone_editor.py useista sijainneista - pääkansio ensin
    script_dir = Path(__file__).parent
    search_paths = [
        script_dir / "zone_editor.py",
        Path.cwd() / "zone_editor.py",
        script_dir / "geometry" / "zone_editor.py",
        script_dir.parent / "geometry" / "zone_editor.py",
        Path.cwd() / "geometry" / "zone_editor.py",
    ]
    
    zone_editor_path = None
    for path in search_paths:
        if path.exists():
            zone_editor_path = path
            break
    
    if zone_editor_path is None:
        print(f"  ⚠ zone_editor.py ei löydy. Tarkistetut sijainnit:")
        for p in search_paths[:3]:
            print(f"    - {p}")
        return None
    
    # Lisää hakemisto polkuun ja tuo moduuli
    zone_editor_dir = zone_editor_path.parent
    if str(zone_editor_dir) not in sys.path:
        sys.path.insert(0, str(zone_editor_dir))
    
    try:
        from zone_editor import load_geometry, identify_zones as detect_zones, generate_html_editor
    except ImportError as e:
        print(f"  ⚠ zone_editor.py tuonti epäonnistui: {e}")
        return None
    
    # Määritä tulostiedosto samaan kansioon
    editor_path = geometry_path.with_suffix('.html')
    
    # Jos editor.html on jo olemassa, käytä editor_zones.html
    if editor_path.exists():
        editor_path = geometry_path.parent / "editor_zones.html"
    
    try:
        # Lataa geometria
        geometry = load_geometry(str(geometry_path))
        
        # Tunnista alueet
        zones = []
        if identify_zones:
            zones = detect_zones(geometry, resolution=1.0, min_zone_area=25.0)
        
        # Luo HTML (funktio kirjoittaa tiedoston ja palauttaa polun)
        generate_html_editor(geometry, str(editor_path), zones=zones)
        
        return editor_path
        
    except Exception as e:
        print(f"  ⚠ Zone editor -luonti epäonnistui: {e}")
        import traceback
        traceback.print_exc()
        return None


def process_config_file(args):
    """Käsittelee konfiguraatiotiedoston useilla sijainneilla."""
    config_path = Path(args.config)
    if not config_path.exists():
        print(f"VIRHE: Konfiguraatiotiedostoa ei löydy: {config_path}")
        sys.exit(1)
    
    print("="*60)
    print("OSM-GEOMETRIAN TUONTI (KONFIGURAATIOTIEDOSTOSTA)")
    print("="*60)
    print(f"Konfiguraatio: {config_path}")
    
    try:
        locations, defaults, sim_config = load_config_file(str(config_path))
    except Exception as e:
        print(f"VIRHE: Konfiguraation lukeminen epäonnistui: {e}")
        sys.exit(1)
    
    print(f"Sijainteja: {len(locations)}")
    if defaults:
        print(f"Oletukset: {defaults}")
    if sim_config:
        print(f"Simulaatioasetukset: {sim_config}")
    
    # Tuo OSM-moduuli
    try:
        from geometry.osm_import import fetch_geometry_from_osm, save_osm_geometry
    except ImportError as e:
        print("VIRHE: OSM-tuonti vaatii lisäkirjastoja:")
        print("  pip install osmnx geopandas shapely pyproj --break-system-packages")
        sys.exit(1)
    
    # Käsittele jokainen sijainti
    successful = []
    failed = []
    
    for i, loc in enumerate(locations, 1):
        print(f"\n{'='*60}")
        print(f"SIJAINTI {i}/{len(locations)}")
        print("="*60)
        
        # Yhdistä oletukset ja sijainnin asetukset
        lat = loc.get('lat')
        lon = loc.get('lon')
        address = loc.get('address')
        radius = loc.get('radius', defaults.get('radius', 300))
        velocity = loc.get('velocity', defaults.get('velocity', 5.0))
        resolution = loc.get('resolution', defaults.get('resolution', 1.0))
        no_trees = loc.get('no_trees', defaults.get('no_trees', False))
        no_forests = loc.get('no_forests', defaults.get('no_forests', False))
        no_vegetation = loc.get('no_vegetation', defaults.get('no_vegetation', False))
        no_roads = loc.get('no_roads', defaults.get('no_roads', False))
        min_area = loc.get('min_area', defaults.get('min_area', 20.0))
        min_forest_area = loc.get('min_forest_area', defaults.get('min_forest_area', 100.0))
        min_vegetation_area = loc.get('min_vegetation_area', defaults.get('min_vegetation_area', 50.0))
        name = loc.get('name')
        output = loc.get('output')
        
        # Tarkista sijainti
        if address is None and (lat is None or lon is None):
            print(f"  OHITETAAN: Anna joko 'address' tai 'lat'+'lon'")
            failed.append(loc)
            continue
        
        # Määritä tulostiedosto
        if output is None:
            if address:
                safe_name = address.split(',')[0].replace(' ', '_').lower()
                output = f"{safe_name}_osm.json"
            else:
                output = f"osm_{lat:.4f}_{lon:.4f}.json"
        
        print(f"  Sijainti: {address or f'{lat}, {lon}'}")
        print(f"  Säde: {radius} m")
        print(f"  Tulos: {output}")
        
        try:
            config = fetch_geometry_from_osm(
                lat=lat,
                lon=lon,
                address=address,
                radius=radius,
                include_trees=not no_trees,
                include_forests=not no_forests,
                include_vegetation=not no_vegetation,
                include_roads=not no_roads,
                inlet_velocity=velocity,
                grid_resolution=resolution,
                name=name,
                min_building_area=min_area,
                min_forest_area=min_forest_area,
                min_vegetation_area=min_vegetation_area
            )
            
            # Tallenna
            # Jos output sisältää jo hakemistopolun, käytä sitä suoraan
            if '/' in output or '\\' in output:
                output_path = Path(output)
            else:
                output_path = Path("examples/OSMgeometry") / output
            output_path.parent.mkdir(parents=True, exist_ok=True)
            save_osm_geometry(config, str(output_path))
            
            # Luo zone editor HTML
            if not args.no_zone_editor:
                editor_path = generate_zone_editor(output_path, identify_zones=True)
                if editor_path:
                    print(f"    Zone editor: {editor_path}")
            
            successful.append(str(output_path))
            print(f"  ✓ Tallennettu: {output_path}")
            
        except Exception as e:
            print(f"  ✗ VIRHE: {e}")
            failed.append(loc)
    
    # Yhteenveto
    print("\n" + "="*60)
    print("YHTEENVETO")
    print("="*60)
    print(f"Onnistuneet: {len(successful)}/{len(locations)}")
    for path in successful:
        print(f"  ✓ {path}")
    
    if failed:
        print(f"\nEpäonnistuneet: {len(failed)}")
        for loc in failed:
            print(f"  ✗ {loc.get('address') or str(loc.get('lat')) + ', ' + str(loc.get('lon'))}")
    
    # Simuloi jos pyydetty (joko komentorivillä tai konfiguraatiossa)
    run_simulation = args.simulate or sim_config.get('enabled', False)
    
    if run_simulation and successful:
        print("\n" + "="*60)
        print("SIMULAATIOT")
        print("="*60)
        
        # Simulaatioparametrit (konfiguraatio > komentorivi > oletus)
        iterations = sim_config.get('iterations', args.iterations)
        turbulence = sim_config.get('turbulence', 'sst')
        wall_functions = sim_config.get('wall_functions', True)  # Oletus: päällä
        auto_nested = sim_config.get('auto_nested', True)  # Oletus: päällä
        nested_margin = sim_config.get('nested_margin', 10)
        refinement = sim_config.get('refinement', 4)
        match_scale = sim_config.get('match_scale', True)  # Oletus: päällä
        crop = sim_config.get('crop', 50)  # Oletus: 50m (auto-crop vasemmalle)
        adaptive = sim_config.get('adaptive', None)
        
        print(f"Asetukset:")
        print(f"  Iteraatiot: {iterations}")
        print(f"  Turbulenssimalli: {turbulence}")
        print(f"  Wall functions: {wall_functions}")
        if auto_nested:
            print(f"  Auto-nested: kyllä (margin={nested_margin}m, refinement={refinement}x)")
            if match_scale:
                print(f"  Match-scale: kyllä")
        if adaptive:
            print(f"  Adaptive: {adaptive}")
        if crop:
            print(f"  Crop: {crop}m (vasen reuna: auto k-kentästä)")
        
        # Simuloi jokainen geometria
        for geom_path in successful:
            print(f"\n{'-'*60}")
            print(f"Simuloidaan: {geom_path}")
            print("-"*60)
            
            # Rakenna komentorivi main.py:lle
            # Huom: main.py:ssä auto-nested ja wall-functions ovat oletuksena päällä
            cmd = [
                sys.executable, 'main.py',
                '--geometry', geom_path,
                '--iterations', str(iterations),
                '--turbulence', turbulence
            ]
            
            # Wall functions (oletus päällä main.py:ssä)
            if not wall_functions:
                cmd.append('--no-wall-functions')
            
            # Auto-nested (oletus päällä main.py:ssä)
            if auto_nested:
                cmd.extend(['--nested-margin', str(nested_margin)])
                cmd.extend(['--refinement', str(refinement)])
                if match_scale:
                    cmd.append('--match-scale')
            else:
                cmd.append('--no-auto-nested')
                if adaptive:
                    cmd.extend(['--adaptive', str(adaptive)])
            
            if crop:
                cmd.extend(['--crop', str(crop)])
            
            # Tuloskansio
            output_dir = Path("output") / Path(geom_path).stem
            cmd.extend(['--output', str(output_dir)])
            
            print(f"Komento: {' '.join(cmd)}")
            
            import subprocess
            try:
                result = subprocess.run(cmd, check=True)
                print(f"✓ Valmis: {output_dir}/")
            except subprocess.CalledProcessError as e:
                print(f"✗ Simulaatio epäonnistui: {e}")


def process_single_location(args):
    """Käsittelee yksittäisen sijainnin (alkuperäinen toiminnallisuus)."""
    # Tuo OSM-moduuli
    try:
        from geometry.osm_import import fetch_geometry_from_osm, save_osm_geometry
    except ImportError as e:
        print("VIRHE: OSM-tuonti vaatii lisäkirjastoja:")
        print("  pip install osmnx geopandas shapely pyproj --break-system-packages")
        sys.exit(1)
    
    # Määritä tulostiedosto
    if args.output is None:
        if args.address:
            safe_name = args.address.split(',')[0].replace(' ', '_').lower()
            args.output = f"{safe_name}_osm.json"
        else:
            args.output = f"osm_{args.lat:.4f}_{args.lon:.4f}.json"
    
    # Hae geometria
    print("="*60)
    print("OSM-GEOMETRIAN TUONTI")
    print("="*60)
    
    try:
        config = fetch_geometry_from_osm(
            lat=args.lat,
            lon=args.lon,
            address=args.address,
            radius=args.radius,
            include_trees=not args.no_trees,
            include_forests=not args.no_forests,
            include_vegetation=not args.no_vegetation,
            include_roads=not args.no_roads,
            inlet_velocity=args.velocity,
            grid_resolution=args.resolution,
            name=args.name,
            min_building_area=args.min_area,
            min_forest_area=args.min_forest_area,
            min_vegetation_area=args.min_vegetation_area
        )
    except Exception as e:
        print(f"\nVIRHE: {e}")
        print("\nMahdollisia syitä:")
        print("  - Ei verkkoyhteyttä")
        print("  - Osoitetta ei löydy")
        print("  - Overpass API ei vastaa")
        sys.exit(1)
    
    # Tallenna
    # Jos output sisältää jo hakemistopolun, käytä sitä suoraan
    if '/' in args.output or '\\' in args.output:
        output_path = Path(args.output)
    else:
        output_path = Path("examples/OSMgeometry") / args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    save_osm_geometry(config, str(output_path))
    
    # Luo zone editor HTML
    editor_path = None
    if not args.no_zone_editor:
        print("\nLuodaan zone editor...")
        editor_path = generate_zone_editor(output_path, identify_zones=True)
        if editor_path:
            print(f"  ✓ Zone editor: {editor_path}")
    
    # Simuloi jos pyydetty
    if args.simulate:
        print("\n" + "="*60)
        print("SIMULAATIO")
        print("="*60)
        
        from geometry.loader import load_geometry
        from solvers.cfd_solver import CFDSolver
        from utils.visualization import generate_all_plots
        from utils.comfort import comfort_report
        
        # Lataa ja ratkaise
        config_obj = load_geometry(str(output_path))
        solver = CFDSolver.from_config(config_obj)
        solver.solve(verbose=True, max_iterations=args.iterations)
        
        # Tulokset
        output_dir = Path("output") / output_path.stem
        output_dir.mkdir(parents=True, exist_ok=True)
        
        vel = solver.get_velocity_magnitude()
        mask = ~solver.solid_mask & ~solver.porous_mask
        print("\n" + comfort_report(vel, mask, "Koko alue"))
        
        # Visualisoinnit
        print("\nLuodaan visualisoinnit...")
        generate_all_plots(solver, str(output_dir), prefix=output_path.stem)
        
        print(f"\nTulokset: {output_dir}/")
    
    print("\n" + "="*60)
    print("VALMIS")
    print("="*60)
    print(f"Geometria: {output_path}")
    if editor_path:
        print(f"Zone editor: {editor_path}")
    if not args.simulate:
        print(f"\nSimuloi komennolla:")
        print(f"  python main.py --geometry {output_path}")
        if editor_path:
            print(f"\nMuokkaa alueita selaimessa:")
            print(f"  avaa {editor_path}")


if __name__ == '__main__':
    main()
