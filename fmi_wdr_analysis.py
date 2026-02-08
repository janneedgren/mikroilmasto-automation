#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FMI Viistosadeanalyysi (Wind-Driven Rain, WDR) - ISO 15927-3

Hakee Ilmatieteen laitoksen avoimesta datasta tuntitason tuuli- ja sadedata
ja laskee ISO 15927-3 / BS 8104 mukaisen viistosadeindeksin.

Käyttö:
    python fmi_wdr_analysis.py --city Helsinki
    python fmi_wdr_analysis.py --city Helsinki --years 10
    python fmi_wdr_analysis.py --city Oulu --output wdr_data.json

ISO 15927-3 kaava:
    WDR = (2/9) × Σ(v × r^0.88 × cos(D - θ))
    
    missä:
    - v = tuulen nopeus [m/s]
    - r = sateen intensiteetti [mm/h]
    - D = tuulen suunta [°]
    - θ = seinän suunta [°]
    
    Tulos on litraa/m² vuodessa kullekin ilmansuunnalle.

BS 8104 rasitusluokat (spell index, l/m²):
    - Sheltered (suojaisa): < 33
    - Moderate (kohtalainen): 33–56.5
    - Severe (ankara): 56.5–100
    - Very severe (erittäin ankara): > 100

Viitteet:
    - ISO 15927-3:2009 Hygrothermal performance of buildings
    - BS 8104:1992 Code of practice for assessing exposure of walls to wind-driven rain
    - Blocken & Carmeliet (2004) A review of wind-driven rain research

FMI Open Data API:
    https://opendata.fmi.fi/
"""

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import xml.etree.ElementTree as ET

try:
    import requests
    import numpy as np
except ImportError as e:
    print(f"VIRHE: Tarvittava kirjasto puuttuu: {e}")
    print("Asenna: pip install requests numpy")
    sys.exit(1)


# FMI sääasemat (vain asemat joilla on sademittaus PRA_PT1H_ACC)
# Lentoasemat ovat luotettavimpia - niillä on aina täysi mittausvarustus
# Koordinaatit (lat, lon) lisätty lähimmän aseman hakua varten
FMI_STATIONS = {
    # Etelä-Suomi (pääkaupunkiseutu ja rannikko)
    'Helsinki': {'fmisid': 100971, 'name': 'Helsinki Kaisaniemi', 'lat': 60.175, 'lon': 24.944},
    'Helsinki-Vantaa': {'fmisid': 100968, 'name': 'Helsinki-Vantaa lentoasema', 'lat': 60.327, 'lon': 24.957},
    'Vantaa': {'fmisid': 100968, 'name': 'Helsinki-Vantaa lentoasema', 'lat': 60.327, 'lon': 24.957},
    'Espoo': {'fmisid': 100968, 'name': 'Helsinki-Vantaa lentoasema', 'lat': 60.327, 'lon': 24.957},
    'Turku': {'fmisid': 100949, 'name': 'Turku lentoasema', 'lat': 60.514, 'lon': 22.262},
    'Tampere': {'fmisid': 101124, 'name': 'Tampere-Pirkkala lentoasema', 'lat': 61.415, 'lon': 23.604},
    'Lahti': {'fmisid': 101150, 'name': 'Hämeenlinna Lammi Pappila', 'lat': 61.058, 'lon': 25.028},
    'Hämeenlinna': {'fmisid': 101150, 'name': 'Hämeenlinna Lammi Pappila', 'lat': 61.058, 'lon': 25.028},
    'Kotka': {'fmisid': 101030, 'name': 'Kotka Rankki', 'lat': 60.375, 'lon': 26.955},
    'Porvoo': {'fmisid': 101004, 'name': 'Helsinki Kumpula', 'lat': 60.203, 'lon': 24.961},
    'Hanko': {'fmisid': 100946, 'name': 'Hanko Russarö', 'lat': 59.773, 'lon': 22.950},
    
    # Länsi-Suomi
    'Pori': {'fmisid': 101267, 'name': 'Pori lentoasema', 'lat': 61.462, 'lon': 21.802},
    'Rauma': {'fmisid': 101267, 'name': 'Pori lentoasema', 'lat': 61.462, 'lon': 21.802},
    'Vaasa': {'fmisid': 101462, 'name': 'Vaasa lentoasema', 'lat': 63.042, 'lon': 21.762},
    'Seinäjoki': {'fmisid': 101486, 'name': 'Seinäjoki Pelmaa', 'lat': 62.941, 'lon': 22.492},
    'Kokkola': {'fmisid': 101662, 'name': 'Kruunupyy lentoasema', 'lat': 63.722, 'lon': 23.143},
    
    # Itä-Suomi
    'Kuopio': {'fmisid': 101570, 'name': 'Kuopio lentoasema', 'lat': 63.007, 'lon': 27.798},
    'Joensuu': {'fmisid': 101632, 'name': 'Joensuu Linnunlahti', 'lat': 62.600, 'lon': 29.760},
    'Jyväskylä': {'fmisid': 101339, 'name': 'Jyväskylä lentoasema', 'lat': 62.400, 'lon': 25.678},
    'Mikkeli': {'fmisid': 101398, 'name': 'Mikkeli lentoasema', 'lat': 61.686, 'lon': 27.202},
    'Savonlinna': {'fmisid': 101436, 'name': 'Savonlinna lentoasema', 'lat': 61.943, 'lon': 28.930},
    'Lappeenranta': {'fmisid': 101237, 'name': 'Lappeenranta lentoasema', 'lat': 61.044, 'lon': 28.153},
    
    # Pohjois-Suomi
    'Oulu': {'fmisid': 101799, 'name': 'Oulu lentoasema', 'lat': 64.928, 'lon': 25.374},
    'Rovaniemi': {'fmisid': 101920, 'name': 'Rovaniemi lentoasema', 'lat': 66.560, 'lon': 25.830},
    'Kajaani': {'fmisid': 101725, 'name': 'Kajaani lentoasema', 'lat': 64.285, 'lon': 27.687},
    'Kemi': {'fmisid': 101846, 'name': 'Kemi-Tornio lentoasema', 'lat': 65.779, 'lon': 24.582},
    'Sodankylä': {'fmisid': 101932, 'name': 'Sodankylä Tähtelä', 'lat': 67.368, 'lon': 26.629},
    'Ivalo': {'fmisid': 101952, 'name': 'Ivalo lentoasema', 'lat': 68.607, 'lon': 27.405},
    'Utsjoki': {'fmisid': 102035, 'name': 'Utsjoki Kevo', 'lat': 69.757, 'lon': 27.012},
    'Muonio': {'fmisid': 101982, 'name': 'Muonio Alamuonio', 'lat': 67.943, 'lon': 23.680},
    'Enontekiö': {'fmisid': 101976, 'name': 'Enontekiö Kilpisjärvi', 'lat': 69.046, 'lon': 20.788},
}


def find_nearest_wdr_station(lat: float, lon: float) -> Tuple[str, float]:
    """
    Etsii lähimmän WDR-sääaseman koordinaattien perusteella.
    
    Args:
        lat: Leveysaste (WGS84)
        lon: Pituusaste (WGS84)
        
    Returns:
        Tuple (kaupungin_nimi, etäisyys_km)
    """
    # Haversine-kaava etäisyyden laskemiseen
    def haversine(lat1, lon1, lat2, lon2):
        R = 6371  # Maan säde km
        dlat = np.radians(lat2 - lat1)
        dlon = np.radians(lon2 - lon1)
        a = np.sin(dlat/2)**2 + np.cos(np.radians(lat1)) * np.cos(np.radians(lat2)) * np.sin(dlon/2)**2
        return 2 * R * np.arcsin(np.sqrt(a))
    
    # Etsi uniikki lista asemista (ei duplikaatteja)
    unique_stations = {}
    for city, info in FMI_STATIONS.items():
        fmisid = info['fmisid']
        if fmisid not in unique_stations:
            unique_stations[fmisid] = (city, info)
    
    # Laske etäisyydet
    nearest_city = None
    min_distance = float('inf')
    
    for city, info in unique_stations.values():
        dist = haversine(lat, lon, info['lat'], info['lon'])
        if dist < min_distance:
            min_distance = dist
            nearest_city = city
    
    return nearest_city, round(min_distance, 1)

# BS 8104 / ISO 15927-3 rasitusluokat (annual index, l/m²/vuosi)
WDR_EXPOSURE_CLASSES = {
    'sheltered': {'max': 33, 'label_fi': 'Suojaisa', 'label_en': 'Sheltered'},
    'moderate': {'max': 56.5, 'label_fi': 'Kohtalainen', 'label_en': 'Moderate'},
    'severe': {'max': 100, 'label_fi': 'Ankara', 'label_en': 'Severe'},
    'very_severe': {'max': 9999, 'label_fi': 'Erittain ankara', 'label_en': 'Very severe'},
}

# 16 ilmansuuntaa (meteorologinen konventio: 0° = N, myötäpäivään)
DIRECTION_NAMES = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE',
                   'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW']


def fetch_fmi_rain_wind_data(fmisid: int, start_date: datetime, end_date: datetime) -> List[Dict]:
    """
    Hakee tuntitason tuuli- ja sadedata FMI Open Data API:sta.
    
    Käyttää hourly::simple querya joka palauttaa:
        - WD_PT1H_AVG: Tuulen suunta (tunnin keskiarvo) [°]
        - WS_PT1H_AVG: Tuulen nopeus (tunnin keskiarvo) [m/s]
        - PRA_PT1H_ACC: Sademäärä (tunnin kertymä) [mm]
    
    Args:
        fmisid: FMI sääaseman ID
        start_date: Alkupäivämäärä
        end_date: Loppupäivämäärä
        
    Returns:
        Lista dictionaryja: [{'time': datetime, 'direction': float, 'speed': float, 'rain': float}, ...]
    """
    base_url = "https://opendata.fmi.fi/wfs"
    
    params = {
        'service': 'WFS',
        'version': '2.0.0',
        'request': 'GetFeature',
        'storedquery_id': 'fmi::observations::weather::hourly::simple',
        'fmisid': fmisid,
        'starttime': start_date.strftime('%Y-%m-%dT00:00:00Z'),
        'endtime': end_date.strftime('%Y-%m-%dT23:59:59Z'),
        'parameters': 'WD_PT1H_AVG,WS_PT1H_AVG,PRA_PT1H_ACC',
    }
    
    try:
        response = requests.get(base_url, params=params, timeout=60)
        
        if response.status_code != 200:
            # Älä tulosta virhettä joka kuukaudelle, vain kerran
            return []
            
        response.raise_for_status()
        
        # Parsitaan XML - BsWfsElement formaatti
        root = ET.fromstring(response.content)
        
        data = {}
        
        # Etsi kaikki BsWfsElement elementit
        for member in root.findall('.//{http://xml.fmi.fi/schema/wfs/2.0}BsWfsElement'):
            time_elem = member.find('{http://xml.fmi.fi/schema/wfs/2.0}Time')
            param_elem = member.find('{http://xml.fmi.fi/schema/wfs/2.0}ParameterName')
            value_elem = member.find('{http://xml.fmi.fi/schema/wfs/2.0}ParameterValue')
            
            if time_elem is None or param_elem is None or value_elem is None:
                continue
            
            try:
                time_str = time_elem.text
                param_name = param_elem.text
                value_text = value_elem.text
                
                # Ohita NaN arvot
                if value_text is None or value_text == 'NaN':
                    continue
                    
                value = float(value_text)
            except (ValueError, TypeError):
                continue
            
            try:
                dt = datetime.fromisoformat(time_str.replace('Z', '+00:00'))
            except ValueError:
                continue
            
            time_key = dt.isoformat()
            if time_key not in data:
                data[time_key] = {'time': dt, 'direction': None, 'speed': None, 'rain': None}
            
            # Uudet parametrinimet
            if param_name == 'WD_PT1H_AVG':
                data[time_key]['direction'] = value
            elif param_name == 'WS_PT1H_AVG':
                data[time_key]['speed'] = value
            elif param_name == 'PRA_PT1H_ACC':
                # Tunnin kertymä [mm] = intensiteetti [mm/h]
                data[time_key]['rain'] = max(0, value)  # Varmista ei-negatiivinen
        
        # Suodata: tarvitaan kaikki kolme arvoa
        result = []
        for entry in data.values():
            if (entry['direction'] is not None and 
                entry['speed'] is not None and 
                entry['rain'] is not None):
                result.append(entry)
        
        return sorted(result, key=lambda x: x['time'])
        
    except requests.exceptions.RequestException as e:
        return []
    except ET.ParseError as e:
        return []


def calculate_wdr_iso15927(data: List[Dict], wall_directions: Optional[List[float]] = None) -> Dict:
    """
    Laskee ISO 15927-3 mukaisen WDR-indeksin.
    
    ISO 15927-3 kaava:
        I_WDR = (2/9) × Σ(v × r^0.88 × cos(D - θ))
        
    Yksinkertaistettu versio (ei terrain/obstruction kertoimia):
        WDR = 0.222 × Σ(v × r^0.88 × cos(D - θ))
        
    missä summataan kaikki tunnit joilla cos(D - θ) > 0 (tuuli seinää kohti).
    
    Args:
        data: Lista tuntidatasta [{'direction': °, 'speed': m/s, 'rain': mm/h}, ...]
        wall_directions: Seinien suunnat meteorologisessa konventiossa [°]
                        Oletus: 16 pääilmansuuntaa
    
    Returns:
        Dict WDR-analyysin tuloksista
    """
    if wall_directions is None:
        # 16 pääilmansuuntaa (seinä osoittaa tähän suuntaan)
        wall_directions = [i * 22.5 for i in range(16)]
    
    if not data:
        return None
    
    # Suodata sadehavaintoihin (rain > 0)
    rain_data = [d for d in data if d['rain'] > 0 and d['speed'] > 0.5]
    
    if not rain_data:
        return {
            'total_hours': len(data),
            'rain_hours': 0,
            'annual_precipitation_mm': 0,
            'wdr_by_direction': {name: 0 for name in DIRECTION_NAMES},
            'max_wdr': 0,
            'max_wdr_direction': 'N',
            'exposure_class': 'sheltered',
        }
    
    # Laske kokonaissademäärä
    total_rain_mm = sum(d['rain'] for d in rain_data)
    years = len(data) / (365.25 * 24)  # Vuosien määrä
    annual_rain_mm = total_rain_mm / years if years > 0 else total_rain_mm
    
    # Laske WDR jokaiselle seinäsuunnalle
    wdr_by_direction = {}
    
    for i, wall_dir in enumerate(wall_directions):
        dir_name = DIRECTION_NAMES[i] if i < len(DIRECTION_NAMES) else f"{wall_dir:.0f}°"
        
        wdr_sum = 0
        for entry in rain_data:
            wind_dir = entry['direction']  # Mistä tuulee (meteorologinen)
            v = entry['speed']
            r = entry['rain']
            
            # Kulma tuulen ja seinän normaalin välillä
            # Seinä osoittaa suuntaan wall_dir, normaali = wall_dir
            # Tuuli tulee suunnasta wind_dir
            # Tuuli osuu seinään kun se tulee seinän puolelta
            angle_diff = np.radians(wind_dir - wall_dir)
            cos_angle = np.cos(angle_diff)
            
            # Vain positiivinen osuus (tuuli seinää kohti)
            if cos_angle > 0:
                # ISO 15927-3: WDR = (2/9) × v × r^0.88
                wdr_contribution = 0.222 * v * (r ** 0.88) * cos_angle
                wdr_sum += wdr_contribution
        
        # Muunna vuotuiseksi (l/m²/vuosi)
        wdr_annual = wdr_sum / years if years > 0 else wdr_sum
        wdr_by_direction[dir_name] = round(wdr_annual, 1)
    
    # Etsi maksimi
    max_dir = max(wdr_by_direction, key=wdr_by_direction.get)
    max_wdr = wdr_by_direction[max_dir]
    
    # Määritä rasitusluokka
    exposure_class = 'very_severe'
    for cls_name, cls_data in WDR_EXPOSURE_CLASSES.items():
        if max_wdr <= cls_data['max']:
            exposure_class = cls_name
            break
    
    return {
        'total_hours': len(data),
        'rain_hours': len(rain_data),
        'rain_percent': round(100 * len(rain_data) / len(data), 1),
        'years_analyzed': round(years, 1),
        'annual_precipitation_mm': round(annual_rain_mm, 0),
        'wdr_by_direction': wdr_by_direction,
        'max_wdr': max_wdr,
        'max_wdr_direction': max_dir,
        'exposure_class': exposure_class,
        'exposure_class_fi': WDR_EXPOSURE_CLASSES[exposure_class]['label_fi'],
        'exposure_class_en': WDR_EXPOSURE_CLASSES[exposure_class]['label_en'],
    }


def get_wdr_for_cfd(wdr_analysis: Dict) -> Dict:
    """
    Muuntaa WDR-analyysin CFD-simuloinnin käyttöön.
    
    Palauttaa suuntakohtaiset WDR-kertoimet (normalisoitu maksimiin).
    
    Args:
        wdr_analysis: calculate_wdr_iso15927() tulos
        
    Returns:
        Dict CFD-käyttöön:
        {
            'wdr_factors': {direction: factor},  # 0-1 normalisoitu
            'wdr_absolute': {direction: l/m²/yr},  # Absoluuttiset arvot
            'max_wdr': float,
            'exposure_class': str,
        }
    """
    wdr_abs = wdr_analysis['wdr_by_direction']
    max_wdr = wdr_analysis['max_wdr']
    
    # Normalisoi 0-1 välille
    wdr_factors = {}
    for dir_name, wdr_val in wdr_abs.items():
        wdr_factors[dir_name] = round(wdr_val / max_wdr, 3) if max_wdr > 0 else 0
    
    return {
        'wdr_factors': wdr_factors,
        'wdr_absolute': wdr_abs,
        'max_wdr_lm2_year': max_wdr,
        'exposure_class': wdr_analysis['exposure_class'],
        'exposure_class_fi': wdr_analysis['exposure_class_fi'],
        'annual_precipitation_mm': wdr_analysis['annual_precipitation_mm'],
    }


def fetch_multi_year_data(city: str, years: int = 10, verbose: bool = True) -> Tuple[List[Dict], Dict]:
    """
    Hakee usean vuoden tuntitason sadetuulidata.
    
    ISO 15927-3 suosittaa vähintään 10 vuoden dataa.
    
    Args:
        city: Kaupungin nimi
        years: Vuosien määrä (oletus 10)
        verbose: Tulosta edistyminen
        
    Returns:
        Tuple (data_list, coverage_info)
        - data_list: Lista kaikista havainnoista
        - coverage_info: Dict vuosikohtaisesta kattavuudesta
    """
    if city not in FMI_STATIONS:
        raise ValueError(f"Kaupunkia '{city}' ei löydy. Käytä list_stations().")
    
    station = FMI_STATIONS[city]
    fmisid = station['fmisid']
    
    current_year = datetime.now().year
    all_data = []
    coverage = {}
    
    for year in range(current_year - years, current_year):
        if verbose:
            print(f"  Haetaan vuosi {year}...", end=' ', flush=True)
        
        year_data = []
        for month in range(1, 13):
            month_start = datetime(year, month, 1)
            if month == 12:
                month_end = datetime(year, 12, 31)
            else:
                month_end = datetime(year, month + 1, 1) - timedelta(days=1)
            
            month_data = fetch_fmi_rain_wind_data(fmisid, month_start, month_end)
            year_data.extend(month_data)
        
        # Tallenna vuosikohtainen kattavuus
        expected_hours = 8760 if year % 4 != 0 else 8784  # Karkausvuosi
        rain_hours = sum(1 for d in year_data if d['rain'] > 0)
        coverage[year] = {
            'hours': len(year_data),
            'expected': expected_hours,
            'coverage_pct': round(100 * len(year_data) / expected_hours, 1) if expected_hours > 0 else 0,
            'rain_hours': rain_hours,
            'valid': len(year_data) > expected_hours * 0.5  # Yli 50% = validi
        }
        
        if verbose:
            print(f"{len(year_data)} tuntia, {rain_hours} sadetuntia")
        
        all_data.extend(year_data)
    
    # Yhteenveto
    valid_years = sum(1 for y in coverage.values() if y['valid'])
    total_coverage = round(100 * len(all_data) / (years * 8766), 1)
    
    coverage_info = {
        'years_requested': years,
        'years_with_data': valid_years,
        'total_hours': len(all_data),
        'total_coverage_pct': total_coverage,
        'by_year': coverage
    }
    
    if verbose and valid_years < years:
        missing = years - valid_years
        print(f"\n  ⚠ HUOM: {missing} vuotta puuttuvaa/vajavaista dataa")
        if valid_years < 5:
            print(f"  ⚠ VAROITUS: Vain {valid_years} vuotta validia dataa - tulokset epävarmoja!")
    
    return all_data, coverage_info


def analyze_city_wdr(city: str, years: int = 10, verbose: bool = True) -> Dict:
    """
    Tekee täydellisen WDR-analyysin kaupungille.
    
    Args:
        city: Kaupungin nimi
        years: Analysoitavien vuosien määrä
        verbose: Tulosta edistyminen
        
    Returns:
        Täydellinen WDR-analyysi
    """
    if verbose:
        print(f"\nWDR-analyysi: {city}")
        print(f"ISO 15927-3 mukainen viistosadeindeksi")
        print("=" * 50)
    
    # Hae data
    data, coverage_info = fetch_multi_year_data(city, years, verbose)
    
    if not data:
        raise ValueError(f"Dataa ei saatu haettua kaupungille {city}")
    
    if verbose:
        print(f"\nYhteensä {len(data)} tuntihavaintoa")
    
    # Laske WDR
    wdr_analysis = calculate_wdr_iso15927(data)
    
    if wdr_analysis is None:
        raise ValueError("WDR-analyysi epäonnistui")
    
    # Lisää metadata
    wdr_analysis['city'] = city
    wdr_analysis['station'] = FMI_STATIONS[city]['name']
    wdr_analysis['analysis_date'] = datetime.now().isoformat()
    wdr_analysis['method'] = 'ISO 15927-3'
    wdr_analysis['data_coverage'] = coverage_info
    
    return wdr_analysis


def print_wdr_analysis(analysis: Dict):
    """Tulostaa WDR-analyysin tulokset."""
    print("\n" + "=" * 60)
    print(f"WDR-ANALYYSI: {analysis['city']}")
    print(f"Sääasema: {analysis['station']}")
    print("=" * 60)
    
    print(f"\nDatan laajuus:")
    print(f"  Vuosia analysoitu: {analysis['years_analyzed']}")
    print(f"  Tuntihavaintoja: {analysis['total_hours']:,}")
    print(f"  Sadetunteja: {analysis['rain_hours']:,} ({analysis['rain_percent']:.1f}%)")
    print(f"  Vuotuinen sademäärä: {analysis['annual_precipitation_mm']:.0f} mm")
    
    print(f"\nWDR-indeksi (l/m²/vuosi) suunnittain:")
    print("-" * 40)
    
    wdr = analysis['wdr_by_direction']
    # Järjestä suurimmasta pienimpään
    sorted_dirs = sorted(wdr.items(), key=lambda x: x[1], reverse=True)
    
    for dir_name, wdr_val in sorted_dirs:
        bar = "█" * int(wdr_val / 5)  # Visuaalinen palkki
        print(f"  {dir_name:4s}: {wdr_val:6.1f} {bar}")
    
    print(f"\nMaksimi WDR: {analysis['max_wdr']:.1f} l/m²/vuosi ({analysis['max_wdr_direction']})")
    print(f"Rasitusluokka: {analysis['exposure_class_fi']} ({analysis['exposure_class_en']})")
    
    print(f"\nBS 8104 / ISO 15927-3 rasitusluokat:")
    print("  Suojaisa (Sheltered):      < 33 l/m²/vuosi")
    print("  Kohtalainen (Moderate):    33–56.5 l/m²/vuosi")
    print("  Ankara (Severe):           56.5–100 l/m²/vuosi")
    print("  Erittäin ankara (Very severe): > 100 l/m²/vuosi")
    
    print("=" * 60)


def save_wdr_data(analysis: Dict, output_path: str):
    """Tallentaa WDR-analyysin JSON-tiedostoon."""
    # Lisää CFD-käyttöön sopiva data
    cfd_data = get_wdr_for_cfd(analysis)
    analysis['cfd'] = cfd_data
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(analysis, f, ensure_ascii=False, indent=2, default=str)
    
    print(f"\nTallennettu: {output_path}")


def load_wdr_data(input_path: str, city: str = None, lat: float = None, lon: float = None) -> Dict:
    """
    Lataa WDR-analyysi JSON-tiedostosta.
    
    Tukee kahta formaattia:
    1. Yksittäisen kaupungin tiedosto (fmi_wdr_helsinki.json)
    2. Kaikkien kaupunkien tiedosto (fmi_wdr_all_cities.json) + city/koordinaatit
    
    Jos kaupunkia ei löydy mutta koordinaatit on annettu, käytetään lähintä asemaa.
    
    Args:
        input_path: Polku JSON-tiedostoon
        city: Kaupungin nimi (vaaditaan jos all_cities-tiedosto, ellei koordinaatteja)
        lat: Leveysaste (WGS84) - käytetään jos city ei löydy
        lon: Pituusaste (WGS84) - käytetään jos city ei löydy
        
    Returns:
        Dict WDR-analyysista (sisältää 'nearest_station' ja 'distance_km' jos käytetty koordinaatteja)
    """
    with open(input_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # Tarkista onko all_cities-formaatti
    if 'cities' in data and '_metadata' in data:
        # All cities -tiedosto
        available_cities = list(data['cities'].keys())
        
        # 1. Kokeile ensin suoraa kaupunkihakua
        if city is not None:
            city_lower = city.lower()
            for c, info in data['cities'].items():
                if c.lower() == city_lower:
                    info['city'] = c
                    return info
        
        # 1.5 Jos ei löydy suoraan, tarkista fallback-mappaus
        if city is not None and '_fallback_cities' in data.get('_metadata', {}):
            # Etsi fallback case-insensitive
            fallback_map = data['_metadata']['_fallback_cities']
            fallback_city = None
            for orig, fb in fallback_map.items():
                if orig.lower() == city.lower():
                    fallback_city = fb
                    break
            
            if fallback_city and fallback_city in data['cities']:
                info = data['cities'][fallback_city].copy()
                info['city'] = fallback_city
                info['requested_city'] = city
                info['is_fallback'] = True
                info['note'] = f"Käytetään lähintä saatavilla olevaa asemaa ({fallback_city})"
                print(f"  WDR: {city} -> käytetään {fallback_city}")
                return info
        
        # 2. Jos kaupunkia ei löydy, käytä koordinaatteja ja etsi lähin SAATAVILLA OLEVA asema
        if lat is not None and lon is not None:
            # Etsi lähin asema niistä jotka ovat JSON-tiedostossa
            def haversine(lat1, lon1, lat2, lon2):
                R = 6371
                dlat = np.radians(lat2 - lat1)
                dlon = np.radians(lon2 - lon1)
                a = np.sin(dlat/2)**2 + np.cos(np.radians(lat1)) * np.cos(np.radians(lat2)) * np.sin(dlon/2)**2
                return 2 * R * np.arcsin(np.sqrt(a))
            
            nearest_city = None
            min_distance = float('inf')
            
            for avail_city in available_cities:
                # Hae koordinaatit FMI_STATIONS:sta
                if avail_city in FMI_STATIONS:
                    station_info = FMI_STATIONS[avail_city]
                    dist = haversine(lat, lon, station_info['lat'], station_info['lon'])
                    if dist < min_distance:
                        min_distance = dist
                        nearest_city = avail_city
            
            if nearest_city is not None:
                info = data['cities'][nearest_city].copy()
                info['city'] = nearest_city
                info['nearest_station'] = nearest_city
                info['distance_km'] = round(min_distance, 1)
                info['original_query'] = city if city else f"({lat:.3f}, {lon:.3f})"
                print(f"  WDR: Käytetään lähintä saatavilla olevaa asemaa: {nearest_city} ({min_distance:.1f} km)")
                return info
        
        # 3. Jos city annettu mutta ei löydy, ja ei koordinaatteja -> virhe
        if city is not None:
            available = ', '.join(sorted(data['cities'].keys()))
            raise ValueError(f"Kaupunkia '{city}' ei löydy. Saatavilla: {available}")
        
        raise ValueError("city tai (lat, lon) vaaditaan all_cities-tiedostolle")
    
    # Yksittäisen kaupungin tiedosto
    return data


def load_all_cities_wdr_data(input_path: str) -> Dict:
    """
    Lataa kaikkien kaupunkien WDR-data.
    
    Args:
        input_path: Polku fmi_wdr_all_cities.json tiedostoon
        
    Returns:
        Dict kaikista kaupungeista
    """
    with open(input_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def get_exposure_class(wdr_value: float) -> Tuple[str, str, str]:
    """
    Palauttaa WDR-arvon rasitusluokan.
    
    Args:
        wdr_value: WDR-indeksi (l/m²/vuosi tai suhteellinen)
        
    Returns:
        (class_key, label_fi, label_en)
    """
    for cls_name, cls_data in WDR_EXPOSURE_CLASSES.items():
        if wdr_value <= cls_data['max']:
            return cls_name, cls_data['label_fi'], cls_data['label_en']
    return 'very_severe', 'Erittäin ankara', 'Very severe'


def main():
    parser = argparse.ArgumentParser(
        description='FMI Viistosadeanalyysi (WDR) - ISO 15927-3',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Esimerkkejä:
  python fmi_wdr_analysis.py --city Helsinki
  python fmi_wdr_analysis.py --city Helsinki --years 10
  python fmi_wdr_analysis.py --city Oulu --output wdr_oulu.json
  python fmi_wdr_analysis.py --list-stations

WDR-indeksi (Wind-Driven Rain):
  ISO 15927-3 mukainen viistosadeindeksi kuvaa julkisivuun
  kohdistuvaa vuotuista saderasitusta (l/m²/vuosi).
  
  Indeksi lasketaan yhdistämällä tuulen nopeus, suunta ja
  sateen intensiteetti tuntitason havainnoista.

Rasitusluokat (BS 8104):
  Suojaisa:         < 33 l/m²/vuosi
  Kohtalainen:      33–56.5 l/m²/vuosi
  Ankara:           56.5–100 l/m²/vuosi
  Erittäin ankara:  > 100 l/m²/vuosi
        """
    )
    
    parser.add_argument('--city', '-c', type=str,
                        help='Kaupunki (esim. Helsinki, Oulu, Tampere)')
    parser.add_argument('--years', '-y', type=int, default=10,
                        help='Analysoitavien vuosien määrä (oletus: 10, ISO 15927-3 suositus)')
    parser.add_argument('--output', '-o', type=str, default=None,
                        help='Tallenna tulokset JSON-tiedostoon')
    parser.add_argument('--list-stations', '-l', action='store_true',
                        help='Listaa saatavilla olevat sääasemat')
    parser.add_argument('--json', action='store_true',
                        help='Tulosta tulokset JSON-muodossa (stdout)')
    parser.add_argument('--quiet', '-q', action='store_true',
                        help='Hiljainen tila (vain JSON-tulostus)')
    
    args = parser.parse_args()
    
    # Listaa asemat
    if args.list_stations:
        print("\nSaatavilla olevat sääasemat:")
        print("=" * 50)
        for city, station in sorted(FMI_STATIONS.items()):
            print(f"  {city:20s} - {station['name']}")
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
    
    # Tee analyysi
    verbose = not args.quiet and not args.json
    analysis = analyze_city_wdr(city, args.years, verbose)
    
    # Tulosta
    if args.json:
        cfd_data = get_wdr_for_cfd(analysis)
        analysis['cfd'] = cfd_data
        print(json.dumps(analysis, indent=2, default=str))
    elif not args.quiet:
        print_wdr_analysis(analysis)
    
    # Tallenna
    if args.output:
        save_wdr_data(analysis, args.output)


if __name__ == '__main__':
    main()
