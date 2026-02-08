#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FMI tuulensuunta-analyysi CFD-simulointeja varten.

Hakee Ilmatieteen laitoksen avoimesta datasta tuulitilastot ja laskee
pääasiallisen tuulensuunnan eri paikkakunnille Suomessa.

Käyttö:
    python fmi_wind_analysis.py --city Helsinki
    python fmi_wind_analysis.py --city Oulu --year 2023
    python fmi_wind_analysis.py --city Tampere --months 1,2,12  # Talvikuukaudet
    python fmi_wind_analysis.py --list-stations  # Listaa sääasemat
    python fmi_wind_analysis.py --city Helsinki --plot  # Tuuliruusu

FMI Open Data API:
    https://opendata.fmi.fi/
    
Tuulensuunta meteorologisessa konventiossa:
    - 0° = pohjoisesta
    - 90° = idästä
    - 180° = etelästä
    - 270° = lännestä
    
CFD-simuloinnissa käytetään matemaattista konventiota:
    - 0° = idästä (positiivinen x-akseli)
    - 90° = pohjoisesta (positiivinen y-akseli)
    
Tämä työkalu muuntaa automaattisesti CFD-konventioon.
"""

import argparse
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import xml.etree.ElementTree as ET

try:
    import requests
    import numpy as np
except ImportError as e:
    print(f"VIRHE: Tarvittava kirjasto puuttuu: {e}")
    print("Asenna: pip install requests numpy")
    sys.exit(1)


# FMI sääasemat ja niiden FMISID:t
# https://opendata.fmi.fi/meta?observableProperty=observation&param=winddirection
FMI_STATIONS = {
    # Etelä-Suomi
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
    
    # Länsi-Suomi
    'Pori': {'fmisid': 101267, 'name': 'Pori lentoasema'},
    'Rauma': {'fmisid': 101061, 'name': 'Rauma Kylmäpihlaja'},
    'Vaasa': {'fmisid': 101462, 'name': 'Vaasa lentoasema'},
    'Seinäjoki': {'fmisid': 101486, 'name': 'Seinäjoki Pelmaa'},
    'Kokkola': {'fmisid': 101479, 'name': 'Kokkola Tankar'},
    
    # Itä-Suomi
    'Kuopio': {'fmisid': 101570, 'name': 'Kuopio lentoasema'},
    'Joensuu': {'fmisid': 101632, 'name': 'Joensuu Linnunlahti'},
    'Jyväskylä': {'fmisid': 101339, 'name': 'Jyväskylä lentoasema'},
    'Mikkeli': {'fmisid': 101398, 'name': 'Mikkeli lentoasema'},
    'Savonlinna': {'fmisid': 101436, 'name': 'Savonlinna lentoasema'},
    'Lappeenranta': {'fmisid': 101237, 'name': 'Lappeenranta lentoasema'},
    
    # Pohjois-Suomi
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


def fetch_fmi_wind_data(fmisid: int, start_date: datetime, end_date: datetime) -> List[Dict]:
    """
    Hakee tuulidata FMI Open Data API:sta.
    
    Args:
        fmisid: FMI sääaseman ID
        start_date: Alkupäivämäärä
        end_date: Loppupäivämäärä
        
    Returns:
        Lista dictionaryja: [{'time': datetime, 'direction': float, 'speed': float}, ...]
    """
    # FMI WFS API endpoint
    base_url = "https://opendata.fmi.fi/wfs"
    
    # Parametrit - haetaan tuulensuunta (WD_PT1H_AVG), nopeus (WS_PT1H_AVG) ja puuska (WG_PT1H_MAX)
    params = {
        'service': 'WFS',
        'version': '2.0.0',
        'request': 'GetFeature',
        'storedquery_id': 'fmi::observations::weather::hourly::simple',
        'fmisid': fmisid,
        'starttime': start_date.strftime('%Y-%m-%dT00:00:00Z'),
        'endtime': end_date.strftime('%Y-%m-%dT23:59:59Z'),
        'parameters': 'WD_PT1H_AVG,WS_PT1H_AVG,WG_PT1H_MAX',
        'timestep': '60',  # 60 minuuttia = tuntidata
    }
    
    try:
        response = requests.get(base_url, params=params, timeout=60)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"VIRHE: FMI API kutsu epäonnistui: {e}")
        return []
    
    # Parsitaan XML
    try:
        root = ET.fromstring(response.content)
    except ET.ParseError as e:
        print(f"VIRHE: XML parsinta epäonnistui: {e}")
        return []
    
    # Namespace
    ns = {
        'wfs': 'http://www.opengis.net/wfs/2.0',
        'BsWfs': 'http://xml.fmi.fi/schema/wfs/2.0',
        'gml': 'http://www.opengis.net/gml/3.2'
    }
    
    # Kerää data
    data = {}  # time -> {'direction': float, 'speed': float}
    
    for member in root.findall('.//BsWfs:BsWfsElement', ns):
        time_elem = member.find('BsWfs:Time', ns)
        param_elem = member.find('BsWfs:ParameterName', ns)
        value_elem = member.find('BsWfs:ParameterValue', ns)
        
        if time_elem is None or param_elem is None or value_elem is None:
            continue
        
        try:
            time_str = time_elem.text
            param_name = param_elem.text
            value = float(value_elem.text) if value_elem.text and value_elem.text != 'NaN' else None
        except (ValueError, TypeError):
            continue
        
        if value is None:
            continue
        
        # Parsitaan aika
        try:
            dt = datetime.fromisoformat(time_str.replace('Z', '+00:00'))
        except ValueError:
            continue
        
        time_key = dt.isoformat()
        if time_key not in data:
            data[time_key] = {'time': dt, 'direction': None, 'speed': None, 'gust': None}
        
        if param_name == 'WD_PT1H_AVG':
            data[time_key]['direction'] = value
        elif param_name == 'WS_PT1H_AVG':
            data[time_key]['speed'] = value
        elif param_name == 'WG_PT1H_MAX':
            data[time_key]['gust'] = value
    
    # Suodata pois epätäydelliset havainnot
    result = []
    for entry in data.values():
        if entry['direction'] is not None and entry['speed'] is not None:
            result.append(entry)
    
    return sorted(result, key=lambda x: x['time'])


def analyze_wind_directions(data: List[Dict], 
                           months: Optional[List[int]] = None,
                           use_gust: bool = False) -> Dict:
    """
    Analysoi tuulensuuntajakauma.
    
    Args:
        data: Lista tuulidatasta
        months: Rajoita tiettyihin kuukausiin (1-12), None = kaikki
        use_gust: Jos True, käytä puuskahuippuja keskiarvojen sijaan (storm mode)
        
    Returns:
        Dict analyysin tuloksista
    """
    if months:
        data = [d for d in data if d['time'].month in months]
    
    if not data:
        return None
    
    directions = np.array([d['direction'] for d in data])
    speeds = np.array([d['speed'] for d in data])
    
    # Gust-arvot (voi olla None joissain havainnoissa)
    gusts = np.array([d.get('gust') if d.get('gust') is not None else d['speed'] for d in data])
    
    # Suodata pois nollanopeudet (tyyni)
    mask = speeds > 0.5
    directions = directions[mask]
    speeds = speeds[mask]
    gusts = gusts[mask]
    
    if len(directions) == 0:
        return None
    
    # Valitse käytettävä nopeusdata (storm mode käyttää gust-arvoja)
    if use_gust:
        analysis_speeds = gusts
    else:
        analysis_speeds = speeds
    
    # Laske suuntajakauma 16 sektoriin (22.5° per sektori)
    n_sectors = 16
    sector_size = 360 / n_sectors
    sector_counts = np.zeros(n_sectors)
    sector_speeds = [[] for _ in range(n_sectors)]
    sector_gusts = [[] for _ in range(n_sectors)]
    
    for direction, speed, gust in zip(directions, speeds, gusts):
        sector = int((direction + sector_size / 2) % 360 / sector_size)
        sector_counts[sector] += 1
        sector_speeds[sector].append(speed)
        sector_gusts[sector].append(gust)
    
    # Prosentit
    total = len(directions)
    sector_percents = sector_counts / total * 100
    
    # Keskimääräiset nopeudet per sektori
    sector_avg_speeds = []
    sector_avg_gusts = []
    for speeds_list, gusts_list in zip(sector_speeds, sector_gusts):
        if speeds_list:
            sector_avg_speeds.append(np.mean(speeds_list))
            sector_avg_gusts.append(np.mean(gusts_list))
        else:
            sector_avg_speeds.append(0)
            sector_avg_gusts.append(0)
    
    # Pääsuunta (yleisin)
    main_sector = np.argmax(sector_counts)
    main_direction_meteo = main_sector * sector_size
    
    # Keskimääräinen tuulensuunta (vektorikeskiarvo)
    # Muunna radiaaneiksi ja laske yksikköympyrällä
    dir_rad = np.radians(directions)
    mean_x = np.mean(np.cos(dir_rad))
    mean_y = np.mean(np.sin(dir_rad))
    mean_direction_meteo = (np.degrees(np.arctan2(mean_y, mean_x)) + 360) % 360
    
    # Muunna CFD-konventioon (0° = idästä, 90° = pohjoisesta)
    # Meteorologinen: 0° = pohjoisesta, myötäpäivään
    # CFD/matematiikka: 0° = idästä, vastapäivään
    # Kaava: CFD = 90 - meteo (ja normalisoi 0-360)
    main_direction_cfd = (90 - main_direction_meteo + 360) % 360
    mean_direction_cfd = (90 - mean_direction_meteo + 360) % 360
    
    # Tuulisuunnan nimi
    direction_names = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE',
                       'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW']
    main_direction_name = direction_names[main_sector]
    
    return {
        'n_observations': len(directions),
        'main_direction_meteo': main_direction_meteo,
        'main_direction_cfd': main_direction_cfd,
        'main_direction_name': main_direction_name,
        'main_direction_percent': sector_percents[main_sector],
        'mean_direction_meteo': mean_direction_meteo,
        'mean_direction_cfd': mean_direction_cfd,
        'mean_speed': np.mean(analysis_speeds),  # Käyttää gust-arvoja jos use_gust=True
        'mean_speed_avg': np.mean(speeds),       # Aina keskituuli
        'mean_gust': np.mean(gusts),             # Aina puuskahuippu
        'max_speed': np.max(speeds),
        'max_gust': np.max(gusts),
        'sector_percents': sector_percents.tolist(),
        'sector_avg_speeds': sector_avg_gusts if use_gust else sector_avg_speeds,
        'sector_avg_speeds_mean': sector_avg_speeds,
        'sector_avg_gusts': sector_avg_gusts,
        'calm_percent': (1 - mask.sum() / len(mask)) * 100 if len(mask) > 0 else 0,
        'use_gust': use_gust,
    }


def plot_wind_rose(analysis: Dict, title: str, output_path: str = None):
    """
    Piirtää tuuliruusun.
    
    Args:
        analysis: Analyysin tulokset
        title: Otsikko
        output_path: Tallennuspolku (None = näytä)
    """
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("VAROITUS: matplotlib ei saatavilla, tuuliruusua ei piirretä")
        return
    
    # Sektorien suunnat (meteorologinen konventio, pohjoisesta myötäpäivään)
    n_sectors = 16
    angles = np.linspace(0, 2 * np.pi, n_sectors, endpoint=False)
    # Käännä niin että 0° = pohjoinen ja myötäpäivään
    angles = np.pi / 2 - angles
    
    percents = np.array(analysis['sector_percents'])
    speeds = np.array(analysis['sector_avg_speeds'])
    
    # Luo polaarinen kuvaaja
    fig, ax = plt.subplots(subplot_kw={'projection': 'polar'}, figsize=(10, 10))
    
    # Aseta pohjoinen ylös
    ax.set_theta_zero_location('N')
    ax.set_theta_direction(-1)  # Myötäpäivään
    
    # Pylväiden leveys
    width = 2 * np.pi / n_sectors * 0.8
    
    # Värit nopeuden mukaan
    colors = plt.cm.YlOrRd(speeds / max(speeds) if max(speeds) > 0 else speeds)
    
    # Piirrä pylväät
    bars = ax.bar(angles, percents, width=width, bottom=0, 
                  color=colors, edgecolor='black', linewidth=0.5, alpha=0.8)
    
    # Suuntanimet
    ax.set_xticks(np.linspace(0, 2 * np.pi, 8, endpoint=False))
    ax.set_xticklabels(['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'])
    
    # Otsikko
    ax.set_title(f"{title}\n"
                f"Pääsuunta: {analysis['main_direction_name']} "
                f"({analysis['main_direction_percent']:.1f}%)\n"
                f"Keskinopeus: {analysis['mean_speed']:.1f} m/s | "
                f"Havaintoja: {analysis['n_observations']}", 
                fontsize=12, fontweight='bold', pad=20)
    
    # Colorbar
    sm = plt.cm.ScalarMappable(cmap='YlOrRd', 
                                norm=plt.Normalize(0, max(speeds) if max(speeds) > 0 else 1))
    sm.set_array([])
    cbar = plt.colorbar(sm, ax=ax, shrink=0.8, pad=0.1)
    cbar.set_label('Keskinopeus [m/s]')
    
    plt.tight_layout()
    
    if output_path:
        plt.savefig(output_path, dpi=150, bbox_inches='tight')
        print(f"Tuuliruusu tallennettu: {output_path}")
    else:
        plt.show()
    
    plt.close(fig)


def print_analysis(city: str, station_name: str, analysis: Dict, months: List[int] = None):
    """Tulostaa analyysin tulokset."""
    print("\n" + "=" * 60)
    print(f"TUULENSUUNTA-ANALYYSI: {city}")
    if analysis.get('use_gust'):
        print("*** STORM MODE: Käytetään puuskahuippuja (gust) ***")
    print("=" * 60)
    print(f"Sääasema: {station_name}")
    if months:
        month_names = ['', 'tammi', 'helmi', 'maalis', 'huhti', 'touko', 'kesä',
                       'heinä', 'elo', 'syys', 'loka', 'marras', 'joulu']
        months_str = ', '.join([month_names[m] for m in months])
        print(f"Kuukaudet: {months_str}")
    print(f"Havaintoja: {analysis['n_observations']}")
    print()
    
    print("PÄÄASIALLISET TUULENSUUNNAT:")
    print("-" * 40)
    print(f"  Yleisin suunta: {analysis['main_direction_name']} "
          f"({analysis['main_direction_percent']:.1f}% ajasta)")
    print(f"    - Meteorologinen: {analysis['main_direction_meteo']:.0f}°")
    print(f"    - CFD-simulointi: {analysis['main_direction_cfd']:.0f}°")
    print()
    print(f"  Keskimääräinen suunta:")
    print(f"    - Meteorologinen: {analysis['mean_direction_meteo']:.0f}°")
    print(f"    - CFD-simulointi: {analysis['mean_direction_cfd']:.0f}°")
    print()
    
    print("TUULEN NOPEUS:")
    print("-" * 40)
    print(f"  Keskinopeus (avg): {analysis.get('mean_speed_avg', analysis['mean_speed']):.1f} m/s")
    print(f"  Puuskahuippu (gust): {analysis.get('mean_gust', analysis['mean_speed']):.1f} m/s")
    if analysis.get('use_gust'):
        print(f"  >> Simuloinnissa käytetään: {analysis['mean_speed']:.1f} m/s (gust)")
    else:
        print(f"  >> Simuloinnissa käytetään: {analysis['mean_speed']:.1f} m/s (avg)")
    print(f"  Maksimi (avg): {analysis['max_speed']:.1f} m/s")
    print(f"  Maksimi (gust): {analysis.get('max_gust', analysis['max_speed']):.1f} m/s")
    print(f"  Tyyntä (< 0.5 m/s): {analysis['calm_percent']:.1f}% ajasta")
    print()
    
    # Top 5 suunnat
    print("TOP 5 TUULENSUUNNAT:")
    print("-" * 40)
    direction_names = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE',
                       'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW']
    sorted_indices = np.argsort(analysis['sector_percents'])[::-1]
    for i, idx in enumerate(sorted_indices[:5]):
        pct = analysis['sector_percents'][idx]
        speed = analysis['sector_avg_speeds'][idx]
        meteo_deg = idx * 22.5
        cfd_deg = (90 - meteo_deg + 360) % 360
        print(f"  {i+1}. {direction_names[idx]:3s}: {pct:5.1f}%  "
              f"(keskinopeus {speed:.1f} m/s, CFD: {cfd_deg:.0f}°)")
    
    print()
    print("CFD-SIMULOINTIIN:")
    print("-" * 40)
    print(f"  Suositeltu inlet_direction: {analysis['main_direction_cfd']:.0f}°")
    print(f"  Suositeltu inlet_velocity: {analysis['mean_speed']:.1f} m/s")
    print()
    print("  JSON-esimerkki:")
    print(f'    "boundary_conditions": {{')
    print(f'      "inlet_velocity": {analysis["mean_speed"]:.1f},')
    print(f'      "inlet_direction": {analysis["main_direction_cfd"]:.0f}')
    print(f'    }}')
    print("=" * 60)


def list_stations():
    """Listaa saatavilla olevat sääasemat."""
    print("\n" + "=" * 60)
    print("SAATAVILLA OLEVAT SÄÄASEMAT")
    print("=" * 60)
    
    # Ryhmittele alueittain
    regions = {
        'Etelä-Suomi': ['Helsinki', 'Helsinki-Vantaa', 'Espoo', 'Turku', 'Tampere', 
                        'Lahti', 'Hämeenlinna', 'Kotka', 'Porvoo', 'Hanko'],
        'Länsi-Suomi': ['Pori', 'Rauma', 'Vaasa', 'Seinäjoki', 'Kokkola'],
        'Itä-Suomi': ['Kuopio', 'Joensuu', 'Jyväskylä', 'Mikkeli', 'Savonlinna', 'Lappeenranta'],
        'Pohjois-Suomi': ['Oulu', 'Rovaniemi', 'Kajaani', 'Kemi', 'Sodankylä', 
                          'Ivalo', 'Utsjoki', 'Muonio', 'Enontekiö'],
    }
    
    for region, cities in regions.items():
        print(f"\n{region}:")
        print("-" * 40)
        for city in cities:
            if city in FMI_STATIONS:
                station = FMI_STATIONS[city]
                print(f"  {city:20s} - {station['name']}")
    
    print("\n" + "=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description='FMI tuulensuunta-analyysi CFD-simulointeja varten',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Esimerkkejä:
  python fmi_wind_analysis.py --city Helsinki
  python fmi_wind_analysis.py --city Oulu --year 2023
  python fmi_wind_analysis.py --city Tampere --months 12,1,2  # Talvi
  python fmi_wind_analysis.py --city Turku --months 6,7,8    # Kesä
  python fmi_wind_analysis.py --list-stations
  python fmi_wind_analysis.py --city Helsinki --plot --output tuuliruusu.png

Tuulensuunnat:
  Meteorologinen konventio: 0° = pohjoisesta, myötäpäivään
  CFD-konventio: 0° = idästä, vastapäivään (matemaattinen)
  
  Työkalu muuntaa automaattisesti CFD-konventioon.
        """
    )
    
    parser.add_argument('--city', '-c', type=str, 
                        help='Kaupunki (esim. Helsinki, Oulu, Tampere)')
    parser.add_argument('--year', '-y', type=int, default=None,
                        help='Vuosi (oletus: edellinen vuosi)')
    parser.add_argument('--months', '-m', type=str, default=None,
                        help='Kuukaudet pilkulla erotettuna (esim. 12,1,2 = talvi)')
    parser.add_argument('--plot', '-p', action='store_true',
                        help='Piirrä tuuliruusu')
    parser.add_argument('--output', '-o', type=str, default=None,
                        help='Tallenna tuuliruusu tiedostoon')
    parser.add_argument('--list-stations', '-l', action='store_true',
                        help='Listaa saatavilla olevat sääasemat')
    parser.add_argument('--json', action='store_true',
                        help='Tulosta tulokset JSON-muodossa')
    parser.add_argument('--storm-mode', '--gust', action='store_true',
                        help='Käytä puuskahuippuja (gust) keskiarvojen sijaan - myrskyolosuhteet')
    
    args = parser.parse_args()
    
    # Listaa asemat
    if args.list_stations:
        list_stations()
        return
    
    # Tarkista kaupunki
    if not args.city:
        print("VIRHE: Anna kaupunki --city parametrilla")
        print("Käytä --list-stations nähdäksesi saatavilla olevat kaupungit")
        sys.exit(1)
    
    # Etsi kaupunki (case-insensitive)
    city_lower = args.city.lower()
    city = None
    for c in FMI_STATIONS:
        if c.lower() == city_lower:
            city = c
            break
    
    if city is None:
        print(f"VIRHE: Kaupunkia '{args.city}' ei löydy")
        print("Käytä --list-stations nähdäksesi saatavilla olevat kaupungit")
        sys.exit(1)
    
    station = FMI_STATIONS[city]
    
    # Vuosi
    if args.year:
        year = args.year
    else:
        year = datetime.now().year - 1  # Edellinen vuosi (täysi data)
    
    # Kuukaudet
    months = None
    if args.months:
        try:
            months = [int(m.strip()) for m in args.months.split(',')]
            for m in months:
                if m < 1 or m > 12:
                    raise ValueError(f"Virheellinen kuukausi: {m}")
        except ValueError as e:
            print(f"VIRHE: Virheelliset kuukaudet: {e}")
            sys.exit(1)
    
    # Aikaväli
    start_date = datetime(year, 1, 1)
    end_date = datetime(year, 12, 31)
    
    print(f"\nHaetaan tuulidata: {city} ({station['name']})")
    print(f"Aikaväli: {start_date.strftime('%Y-%m-%d')} - {end_date.strftime('%Y-%m-%d')}")
    
    # Hae data kuukausittain (API rajoitukset)
    all_data = []
    for month in range(1, 13):
        if months and month not in months:
            continue
        
        month_start = datetime(year, month, 1)
        if month == 12:
            month_end = datetime(year, 12, 31)
        else:
            month_end = datetime(year, month + 1, 1) - timedelta(days=1)
        
        print(f"  Haetaan {month_start.strftime('%Y-%m')}...", end=' ', flush=True)
        
        month_data = fetch_fmi_wind_data(station['fmisid'], month_start, month_end)
        all_data.extend(month_data)
        print(f"{len(month_data)} havaintoa")
    
    if not all_data:
        print("VIRHE: Dataa ei saatu haettua")
        sys.exit(1)
    
    print(f"\nYhteensä {len(all_data)} havaintoa")
    
    # Analysoi (storm-mode käyttää gust-arvoja)
    use_gust = getattr(args, 'storm_mode', False)
    if use_gust:
        print("\n*** STORM MODE: Käytetään puuskahuippuja (gust) ***")
    analysis = analyze_wind_directions(all_data, months, use_gust=use_gust)
    
    if analysis is None:
        print("VIRHE: Analyysi epäonnistui (ei riittävästi dataa)")
        sys.exit(1)
    
    # Tulosta
    if args.json:
        import json
        result = {
            'city': city,
            'station': station['name'],
            'year': year,
            'months': months,
            **analysis
        }
        print(json.dumps(result, indent=2))
    else:
        print_analysis(city, station['name'], analysis, months)
    
    # Tuuliruusu
    if args.plot or args.output:
        months_str = ""
        if months:
            months_str = f" (kuukaudet {','.join(map(str, months))})"
        title = f"{city} - Tuuliruusu {year}{months_str}"
        plot_wind_rose(analysis, title, args.output)


if __name__ == '__main__':
    main()
