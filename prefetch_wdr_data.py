#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FMI WDR Pre-fetch - Hae kaikkien kaupunkien viistosadedata etukäteen

Hakee ISO 15927-3 mukaisen WDR-datan kaikille Suomen kaupungeille
ja tallentaa yhteen JSON-tiedostoon. Tämä säästää aikaa simuloinneissa,
koska FMI-hakua ei tarvitse tehdä joka kerta.

Käyttö:
    python prefetch_wdr_data.py
    python prefetch_wdr_data.py --years 5  # Nopeampi (5 vuotta)
    python prefetch_wdr_data.py --output wdr_data.json

Hakuaika: ~2-4 min/kaupunki, yhteensä ~1-2 tuntia (10 vuoden data)
Tulostiedosto: ~100-150 KB
"""

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

# Importoi WDR-analyysi
try:
    from fmi_wdr_analysis import (
        analyze_city_wdr,
        FMI_STATIONS,
        WDR_EXPOSURE_CLASSES
    )
except ImportError:
    print("VIRHE: fmi_wdr_analysis.py ei löydy")
    print("       Varmista että tiedosto on samassa hakemistossa")
    sys.exit(1)


def prefetch_all_cities(years: int = 10, output_path: str = None) -> dict:
    """
    Hakee WDR-datan kaikille kaupungeille.
    
    Args:
        years: Analysoitavien vuosien määrä
        output_path: Tulostiedoston polku (oletus: fmi_wdr_all_cities.json)
        
    Returns:
        Dict kaikista WDR-analyyseista
    """
    if output_path is None:
        output_path = f"fmi_wdr_all_cities_{years}y.json"
    
    # Uniikki lista kaupungeista (jotkut jakavat sääaseman)
    cities = list(FMI_STATIONS.keys())
    
    print("="*60)
    print("FMI WDR PRE-FETCH")
    print("="*60)
    print(f"Kaupunkeja: {len(cities)}")
    print(f"Vuosia: {years}")
    print(f"Arvioitu aika: {len(cities) * 3:.0f} min ({len(cities) * 3 / 60:.1f} h)")
    print(f"Tulostiedosto: {output_path}")
    print("="*60)
    
    all_data = {
        '_metadata': {
            'description': 'FMI WDR-data kaikille Suomen kaupungeille (ISO 15927-3)',
            'years_analyzed': years,
            'created': datetime.now().isoformat(),
            'exposure_classes': {
                k: {'max': v['max'], 'label_fi': v['label_fi'], 'label_en': v['label_en']}
                for k, v in WDR_EXPOSURE_CLASSES.items()
            },
            'unit': 'l/m2/vuosi',
            'method': 'ISO 15927-3: WDR = (2/9) * sum(v * r^0.88 * cos(D - theta))'
        },
        'cities': {}
    }
    
    start_time = time.time()
    successful = 0
    failed = []
    
    # Cache jo haetuille asemille (fmisid -> analysis)
    fmisid_cache = {}
    
    for i, city in enumerate(cities, 1):
        fmisid = FMI_STATIONS[city]['fmisid']
        
        print(f"\n[{i}/{len(cities)}] {city}")
        print("-" * 40)
        
        # Jos sama asema on jo haettu, käytä välimuistia
        if fmisid in fmisid_cache:
            cached = fmisid_cache[fmisid]
            all_data['cities'][city] = cached.copy()
            all_data['cities'][city]['note'] = f"Sama asema kuin {cached['_source_city']}"
            print(f"  -> Käytetään välimuistia ({cached['_source_city']})")
            successful += 1
            continue
        
        city_start = time.time()
        
        try:
            analysis = analyze_city_wdr(city, years=years, verbose=True)
            
            # Tallenna vain oleelliset kentät (säästä tilaa)
            coverage = analysis.get('data_coverage', {})
            city_data = {
                'station': analysis.get('station'),
                'years_analyzed': analysis.get('years_analyzed'),
                'years_with_valid_data': coverage.get('years_with_data', analysis.get('years_analyzed')),
                'data_coverage_pct': coverage.get('total_coverage_pct', 100),
                'total_hours': analysis.get('total_hours'),
                'rain_hours': analysis.get('rain_hours'),
                'rain_percent': analysis.get('rain_percent'),
                'annual_precipitation_mm': analysis.get('annual_precipitation_mm'),
                'wdr_by_direction': analysis.get('wdr_by_direction'),
                'max_wdr': analysis.get('max_wdr'),
                'max_wdr_direction': analysis.get('max_wdr_direction'),
                'exposure_class': analysis.get('exposure_class'),
                'exposure_class_fi': analysis.get('exposure_class_fi'),
                'exposure_class_en': analysis.get('exposure_class_en'),
                '_source_city': city,  # Merkitään alkuperäinen kaupunki välimuistia varten
            }
            
            all_data['cities'][city] = city_data
            
            # Tallenna välimuistiin tätä fmisid:tä varten
            fmisid_cache[fmisid] = city_data
            
            city_time = time.time() - city_start
            print(f"\n✓ {city}: {analysis.get('max_wdr', 0):.1f} l/m2/vuosi "
                  f"({analysis.get('exposure_class_fi', '?')}) - {city_time:.1f}s")
            successful += 1
            
        except Exception as e:
            print(f"\n✗ {city}: VIRHE - {e}")
            failed.append(city)
        
        # Tallenna välitulos (varmuuskopio)
        if i % 5 == 0:
            temp_path = output_path.replace('.json', '_temp.json')
            import codecs
            with codecs.open(temp_path, 'w', 'utf-8') as f:
                json.dump(all_data, f, ensure_ascii=False, indent=2)
            print(f"\n  [Välitallennus: {temp_path}]")
    
    # Lopullinen tallennus
    total_time = time.time() - start_time
    
    all_data['_metadata']['fetch_time_seconds'] = round(total_time, 1)
    all_data['_metadata']['successful_cities'] = successful
    all_data['_metadata']['failed_cities'] = failed
    
    # Käytetään codecs-moduulia UTF-8 enkoodauksen varmistamiseksi
    import codecs
    with codecs.open(output_path, 'w', 'utf-8') as f:
        json.dump(all_data, f, ensure_ascii=False, indent=2)
    
    # Yhteenveto
    print("\n" + "="*60)
    print("VALMIS")
    print("="*60)
    print(f"Onnistuneet: {successful}/{len(cities)}")
    if failed:
        print(f"Epäonnistuneet: {', '.join(failed)}")
    print(f"Kokonaisaika: {total_time/60:.1f} min")
    print(f"Tallennettu: {output_path}")
    
    # Tiedostokoko
    file_size = Path(output_path).stat().st_size
    print(f"Tiedostokoko: {file_size/1024:.1f} KB")
    
    # Poista temp-tiedosto
    temp_path = output_path.replace('.json', '_temp.json')
    if Path(temp_path).exists():
        Path(temp_path).unlink()
    
    return all_data


def print_summary(data_path: str):
    """Tulostaa yhteenvedon WDR-datasta."""
    with open(data_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    print("\n" + "="*60)
    print("WDR-DATA YHTEENVETO")
    print("="*60)
    
    meta = data.get('_metadata', {})
    print(f"Vuosia: {meta.get('years_analyzed', '?')}")
    print(f"Luotu: {meta.get('created', '?')}")
    print(f"Kaupunkeja: {len(data.get('cities', {}))}")
    
    print("\n" + "-"*60)
    print(f"{'Kaupunki':<20} {'WDR max':<12} {'Suunta':<8} {'Luokka'}")
    print("-"*60)
    
    cities = data.get('cities', {})
    sorted_cities = sorted(cities.items(), key=lambda x: x[1].get('max_wdr', 0), reverse=True)
    
    for city, info in sorted_cities:
        max_wdr = info.get('max_wdr', 0)
        direction = info.get('max_wdr_direction', '?')
        exposure = info.get('exposure_class_fi', '?')
        print(f"{city:<20} {max_wdr:>8.1f}    {direction:<8} {exposure}")
    
    print("-"*60)
    
    # Rasitusluokkien jakauma
    exposure_counts = {}
    for city, info in cities.items():
        exp = info.get('exposure_class', 'unknown')
        exposure_counts[exp] = exposure_counts.get(exp, 0) + 1
    
    print("\nRasitusluokkien jakauma:")
    for exp, count in sorted(exposure_counts.items()):
        label = WDR_EXPOSURE_CLASSES.get(exp, {}).get('label_fi', exp)
        print(f"  {label}: {count} kaupunkia")


def main():
    parser = argparse.ArgumentParser(
        description='Hae WDR-data kaikille Suomen kaupungeille etukäteen',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Esimerkkejä:
  python prefetch_wdr_data.py                    # 10 vuoden data (oletus)
  python prefetch_wdr_data.py --years 5          # 5 vuoden data (nopeampi)
  python prefetch_wdr_data.py --summary data.json  # Näytä yhteenveto

Hakuaika:
  - 10 vuotta: ~1-2 tuntia
  - 5 vuotta: ~30-60 min
  
Tulostiedosto: ~100-150 KB (kaikki kaupungit)
        """
    )
    
    parser.add_argument('--years', '-y', type=int, default=10,
                        help='Analysoitavien vuosien määrä (oletus: 10)')
    parser.add_argument('--output', '-o', type=str, default=None,
                        help='Tulostiedoston nimi (oletus: fmi_wdr_all_cities_<N>y.json)')
    parser.add_argument('--summary', '-s', type=str, default=None,
                        help='Näytä yhteenveto olemassa olevasta tiedostosta')
    
    args = parser.parse_args()
    
    if args.summary:
        print_summary(args.summary)
        return
    
    prefetch_all_cities(years=args.years, output_path=args.output)


if __name__ == '__main__':
    main()
