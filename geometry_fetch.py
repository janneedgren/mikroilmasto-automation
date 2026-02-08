#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Geometrian tuonti MML/OSM-hybridillä ja zone editorin luonti.

Käyttää parhaita lähteitä:
- MML: Rakennukset, korkeudet, tiet, tonttirajat
- OSM: Kasvillisuus (kattavampi)

Käyttö:
    # Osoitteella (suositus)
    python geometry_fetch.py -a "Mannerheimintie 1, Helsinki" -o mansku.json
    
    # Koordinaateilla
    python geometry_fetch.py --lat 61.0045 --lon 24.1005 --radius 300 -o parola.json
    
    # Ilman zone editoria
    python geometry_fetch.py -a "Tampere" -o tampere.json --no-editor
    
    # Vain MML (ei OSM kasvillisuutta)
    python geometry_fetch.py -a "Oulu" -o oulu.json --no-hybrid
    
    # Konfiguraatiotiedostosta (useita sijainteja)
    python geometry_fetch.py --config locations.json

Vaatii:
    - MML API-avain (ympäristömuuttuja MML_API_KEY)
    - pip install requests pyproj shapely osmnx geopandas
"""

import argparse
import json
import sys
import os
from pathlib import Path

# Lisää geometry-kansio polkuun
script_dir = Path(__file__).parent
sys.path.insert(0, str(script_dir))
sys.path.insert(0, str(script_dir / "geometry"))


def check_api_key():
    """Tarkista MML API-avain."""
    api_key = os.environ.get('MML_API_KEY')
    if not api_key:
        print("=" * 60)
        print("VIRHE: MML API-avain puuttuu!")
        print("=" * 60)
        print("\nAseta ympäristömuuttuja MML_API_KEY:")
        print("  export MML_API_KEY='avaimesi'")
        print("\nRekisteröidy ilmaiseksi:")
        print("  https://www.maanmittauslaitos.fi/rajapinnat/api-avaimen-ohje")
        print()
        return False
    return True


def generate_zone_editor(geometry_path: Path) -> Path:
    """
    Luo zone editor HTML-tiedoston geometriatiedoston viereen.
    
    Args:
        geometry_path: Polku geometriatiedostoon
    
    Returns:
        Polku luotuun HTML-tiedostoon tai None
    """
    # Etsi zone_editor.py - pääkansio ensin
    search_paths = [
        script_dir / "zone_editor.py",
        Path.cwd() / "zone_editor.py",
        script_dir / "geometry" / "zone_editor.py",
        Path.cwd() / "geometry" / "zone_editor.py",
    ]
    
    zone_editor_path = None
    for path in search_paths:
        if path.exists():
            zone_editor_path = path
            break
    
    if zone_editor_path is None:
        print(f"  ⚠ zone_editor.py ei löydy")
        return None
    
    # Tuo moduuli
    sys.path.insert(0, str(zone_editor_path.parent))
    
    try:
        import zone_editor
        
        # Lataa geometria
        with open(geometry_path, 'r', encoding='utf-8') as f:
            geometry = json.load(f)
        
        # Luo editor HTML - oikea funktionimi
        editor_filename = geometry_path.stem + "_editor.html"
        editor_path = geometry_path.parent / editor_filename
        
        # generate_html_editor(geometry, output_path, zones=None, roads=None)
        zone_editor.generate_html_editor(
            geometry,
            str(editor_path)
        )
        
        return editor_path
        
    except Exception as e:
        print(f"  ⚠ Zone editor luonti epäonnistui: {e}")
        return None


def process_single_location(args):
    """Käsittele yksittäinen sijainti."""
    
    # Tuo MML import
    try:
        from geometry.mml_import import fetch_mml_geometry, save_geometry
    except ImportError:
        try:
            from mml_import import fetch_mml_geometry, save_geometry
        except ImportError as e:
            print(f"VIRHE: mml_import.py ei löydy: {e}")
            print("Varmista että geometry/mml_import.py on olemassa")
            sys.exit(1)
    
    # Määritä tulostiedosto
    if args.output is None:
        if args.address:
            safe_name = args.address.split(',')[0].replace(' ', '_').lower()
            args.output = f"{safe_name}.json"
        else:
            args.output = f"geometry_{args.lat:.4f}_{args.lon:.4f}.json"
    
    # Määritä tuloskansio
    output_path = Path(args.output)
    if not output_path.is_absolute() and '/' not in args.output and '\\' not in args.output:
        # Oletuskansio
        output_dir = Path(args.output_dir) if args.output_dir else Path(".")
        output_path = output_dir / args.output
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Hae geometria
    try:
        config = fetch_mml_geometry(
            address=args.address,
            lat=args.lat,
            lon=args.lon,
            radius=args.radius,
            include_cadastre=not args.no_cadastre,
            hybrid_mode=not args.no_hybrid
        )
    except Exception as e:
        print(f"\nVIRHE: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    
    if config is None:
        print("\nVIRHE: Geometrian haku epäonnistui")
        sys.exit(1)
    
    # Tallenna
    save_geometry(config, str(output_path))
    
    # Luo zone editor
    editor_path = None
    if not args.no_editor:
        print("\nLuodaan zone editor...")
        editor_path = generate_zone_editor(output_path)
        if editor_path:
            print(f"  ✓ Zone editor: {editor_path}")
    
    # Simuloi jos pyydetty
    if args.simulate:
        run_simulation(output_path, args)
    
    # Yhteenveto
    print("\n" + "=" * 60)
    print("VALMIS")
    print("=" * 60)
    print(f"Geometria: {output_path}")
    if editor_path:
        print(f"Zone editor: {editor_path}")
    
    if not args.simulate:
        print(f"\nSimuloi komennolla:")
        print(f"  python main.py --geometry {output_path}")
        if editor_path:
            print(f"\nMuokkaa alueita selaimessa:")
            print(f"  open {editor_path}")


def run_simulation(geometry_path: Path, args):
    """Aja simulaatio."""
    print("\n" + "=" * 60)
    print("SIMULAATIO")
    print("=" * 60)
    
    try:
        from geometry.loader import load_geometry
        from solvers.cfd_solver import CFDSolver
        from utils.visualization import generate_all_plots
        from utils.comfort import comfort_report
        
        # Lataa ja ratkaise
        config = load_geometry(str(geometry_path))
        solver = CFDSolver.from_config(config)
        solver.solve(verbose=True, max_iterations=args.iterations)
        
        # Tulokset
        output_dir = Path("output") / geometry_path.stem
        output_dir.mkdir(parents=True, exist_ok=True)
        
        vel = solver.get_velocity_magnitude()
        mask = ~solver.solid_mask & ~solver.porous_mask
        print("\n" + comfort_report(vel, mask, "Koko alue"))
        
        # Visualisoinnit
        print("\nLuodaan visualisoinnit...")
        generate_all_plots(solver, str(output_dir), prefix=geometry_path.stem)
        
        print(f"\nTulokset: {output_dir}/")
        
    except ImportError as e:
        print(f"VIRHE: Simulaatio vaatii lisämoduuleja: {e}")
    except Exception as e:
        print(f"VIRHE: Simulaatio epäonnistui: {e}")


def load_config_file(config_path: str) -> tuple:
    """Lataa konfiguraatiotiedosto."""
    with open(config_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    if isinstance(data, list):
        return data, {}, {}
    elif isinstance(data, dict):
        locations = data.get('locations', [data])
        defaults = data.get('defaults', {})
        simulation = data.get('simulation', {})
        return locations, defaults, simulation
    else:
        raise ValueError("Konfiguraation tulee olla lista tai objekti")


def process_config_file(args):
    """Käsittele konfiguraatiotiedosto (useita sijainteja)."""
    
    locations, defaults, sim_config = load_config_file(args.config)
    
    print("=" * 60)
    print(f"KONFIGURAATIO: {args.config}")
    print("=" * 60)
    print(f"Sijainteja: {len(locations)}")
    
    # Tuo MML import
    try:
        from geometry.mml_import import fetch_mml_geometry, save_geometry
    except ImportError:
        from mml_import import fetch_mml_geometry, save_geometry
    
    successful = []
    failed = []
    
    for i, loc in enumerate(locations, 1):
        addr_display = loc.get('address') or f"{loc.get('lat')}, {loc.get('lon')}"
        print(f"\n{'─' * 60}")
        print(f"[{i}/{len(locations)}] {addr_display}")
        print("─" * 60)
        
        # Yhdistä oletukset
        radius = loc.get('radius', defaults.get('radius', 300))
        hybrid = not loc.get('no_hybrid', defaults.get('no_hybrid', False))
        cadastre = not loc.get('no_cadastre', defaults.get('no_cadastre', False))
        
        output_file = loc.get('output')
        if not output_file:
            addr = loc.get('address', '')
            if addr:
                safe_name = addr.split(',')[0].replace(' ', '_').lower()
                output_file = f"{safe_name}.json"
            else:
                output_file = f"geometry_{loc.get('lat'):.4f}_{loc.get('lon'):.4f}.json"
        
        output_dir = loc.get('output_dir', defaults.get('output_dir', '.'))
        output_path = Path(output_dir) / output_file
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            config = fetch_mml_geometry(
                address=loc.get('address'),
                lat=loc.get('lat'),
                lon=loc.get('lon'),
                radius=radius,
                include_cadastre=cadastre,
                hybrid_mode=hybrid
            )
            
            if config is None:
                raise ValueError("Geometrian haku epäonnistui")
            
            save_geometry(config, str(output_path))
            
            # Zone editor
            no_editor = loc.get('no_editor', defaults.get('no_editor', False))
            if not no_editor:
                editor_path = generate_zone_editor(output_path)
                if editor_path:
                    print(f"    Zone editor: {editor_path}")
            
            successful.append(str(output_path))
            print(f"  ✓ Tallennettu: {output_path}")
            
        except Exception as e:
            print(f"  ✗ VIRHE: {e}")
            failed.append(loc)
    
    # Yhteenveto
    print("\n" + "=" * 60)
    print("YHTEENVETO")
    print("=" * 60)
    print(f"Onnistuneet: {len(successful)}/{len(locations)}")
    for path in successful:
        print(f"  ✓ {path}")
    
    if failed:
        print(f"\nEpäonnistuneet: {len(failed)}")
        for loc in failed:
            failed_addr = loc.get('address') or f"{loc.get('lat')}, {loc.get('lon')}"
            print(f"  ✗ {failed_addr}")


def main():
    parser = argparse.ArgumentParser(
        description='Hae rakennusgeometria MML/OSM-hybridillä CFD-simulaatioon',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Esimerkkejä:
  # Osoitteella (suositus)
  python geometry_fetch.py -a "Mannerheimintie 1, Helsinki" -o mansku.json
  
  # Koordinaateilla
  python geometry_fetch.py --lat 61.0045 --lon 24.1005 -r 300 -o parola.json
  
  # Suurempi alue
  python geometry_fetch.py -a "Kamppi, Helsinki" --radius 500 -o kamppi.json
  
  # Ilman zone editoria
  python geometry_fetch.py -a "Tampere" -o tampere.json --no-editor
  
  # Vain MML (ei OSM kasvillisuutta)
  python geometry_fetch.py -a "Oulu" -o oulu.json --no-hybrid
  
  # Ilman tonttirajoja
  python geometry_fetch.py -a "Turku" -o turku.json --no-cadastre
  
  # Hae ja simuloi suoraan
  python geometry_fetch.py -a "Espoo" -o espoo.json --simulate
  
  # Konfiguraatiotiedostosta (useita sijainteja)
  python geometry_fetch.py --config locations.json

Konfiguraatiotiedoston muoto (JSON):
  {
    "locations": [
      {"address": "Osoite 1", "radius": 200, "output": "kohde1.json"},
      {"lat": 60.17, "lon": 24.94, "radius": 300, "output": "kohde2.json"}
    ],
    "defaults": {"radius": 300, "no_hybrid": false, "no_editor": false}
  }

Datan lähteet:
  MML (Maanmittauslaitos):
    - Rakennukset (geometria + korkeudet)
    - Tiet (bufferoitu polygoneiksi)
    - Tonttirajat (kiinteistörekisteri)
  
  OSM (OpenStreetMap):
    - Kasvillisuus (metsät, puistot, pellot - kattavampi)
    - Vesialueet

API-avain:
  export MML_API_KEY='avaimesi'
  Rekisteröidy: https://www.maanmittauslaitos.fi/rajapinnat/api-avaimen-ohje
        """
    )
    
    # Konfiguraatiotiedosto
    parser.add_argument('--config', '-c', type=str,
                        help='JSON-konfiguraatiotiedosto (useita sijainteja)')
    
    # Sijainti (kuten osm_fetch.py)
    loc_group = parser.add_argument_group('Sijainti (valitse toinen)')
    loc_group.add_argument('--lat', type=float, help='Leveysaste (WGS84)')
    loc_group.add_argument('--lon', type=float, help='Pituusaste (WGS84)')
    loc_group.add_argument('--address', '-a', type=str, 
                           help='Osoite (geokoodataan automaattisesti)')
    
    # Asetukset
    parser.add_argument('--radius', '-r', type=float, default=300,
                        help='Hakusäde metreinä (oletus: 300)')
    parser.add_argument('--output', '-o', type=str, default=None,
                        help='Tulostiedosto (.json)')
    parser.add_argument('--output-dir', type=str, default=None,
                        help='Tuloskansio (oletus: nykyinen)')
    
    # Hybridiasetukset
    parser.add_argument('--no-hybrid', action='store_true',
                        help='Käytä vain MML:ää (ei OSM kasvillisuutta)')
    parser.add_argument('--no-cadastre', action='store_true',
                        help='Älä hae tonttirajoja')
    parser.add_argument('--no-editor', action='store_true',
                        help='Älä luo zone editor HTML-tiedostoa')
    
    # Simulaatio
    parser.add_argument('--simulate', '-s', action='store_true',
                        help='Aja simulaatio heti tuonnin jälkeen')
    parser.add_argument('--iterations', '-i', type=int, default=400,
                        help='Simulaation iteraatiot (oletus: 400)')
    
    args = parser.parse_args()
    
    # Tarkista API-avain
    if not check_api_key():
        sys.exit(1)
    
    # Konfiguraatiotiedosto
    if args.config:
        process_config_file(args)
        return
    
    # Tarkista sijainti
    if args.address is None and (args.lat is None or args.lon is None):
        parser.error("Anna osoite TAI --lat ja --lon TAI --config")
    
    # Käsittele yksittäinen sijainti
    process_single_location(args)


if __name__ == '__main__':
    main()
