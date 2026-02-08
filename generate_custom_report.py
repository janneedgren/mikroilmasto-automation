#!/usr/bin/env python3
"""
MikroilmastoCFD - Custom Report Generator

Generoi räätälöidyn PDF-raportin JSON-konfiguraation perusteella.

Käyttö:
    python generate_custom_report.py config.json --results results/wind_180deg
    python generate_custom_report.py config.json --results results/combined --output custom_report.pdf

Konfiguraatiotiedosto (JSON):
{
    "title": "Tuulianalyysi - Projektin nimi",
    "language": "fi",
    "author": "Tekijä",
    "sections": [
        {"type": "cover"},
        {"type": "image", "file": "velocity_streamlines.png", "caption": "Nopeuskenttä"},
        {"type": "summary"},
        {"type": "settings"}
    ]
}
"""

import argparse
import json
from pathlib import Path
from typing import Dict, List, Optional, Any
import datetime

# Matplotlib backend
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

# Värit (sama kuin generate_report.py)
DARK_BLUE = '#1a365d'
LIGHT_BLUE = '#e6f0ff'
TEXT_DARK = '#2d3748'
TEXT_GRAY = '#718096'
REPORT_DPI = 150


# =============================================================================
# SAATAVILLA OLEVAT VISUALISOINTITYYPIT
# =============================================================================

AVAILABLE_VISUALIZATIONS = {
    # Peruskentät
    'velocity': {
        'patterns': ['velocity.png', 'velocity_magnitude.png', '*velocity*.png'],
        'description_fi': 'Nopeuskenttä',
        'description_en': 'Velocity field',
        'category': 'basic'
    },
    'velocity_streamlines': {
        'patterns': ['velocity_streamlines.png', '*velocity*streamlines*.png'],
        'description_fi': 'Nopeuskenttä ja virtaviivat',
        'description_en': 'Velocity field with streamlines',
        'category': 'basic'
    },
    'pressure': {
        'patterns': ['pressure.png', '*pressure*.png'],
        'description_fi': 'Painekenttä',
        'description_en': 'Pressure field',
        'category': 'basic'
    },
    'pressure_streamlines': {
        'patterns': ['pressure_streamlines.png', '*pressure*streamlines*.png'],
        'description_fi': 'Painekenttä ja virtaviivat',
        'description_en': 'Pressure field with streamlines',
        'category': 'basic'
    },
    
    # Turbulenssi
    'turbulence_k': {
        'patterns': ['turbulence_k.png', '*turbulence*k*.png', '*tke*.png'],
        'description_fi': 'Turbulenttinen kineettinen energia (k)',
        'description_en': 'Turbulent kinetic energy (k)',
        'category': 'turbulence'
    },
    'turbulence_omega': {
        'patterns': ['turbulence_omega.png', '*turbulence*omega*.png'],
        'description_fi': 'Spesifinen dissipaationopeus (ω)',
        'description_en': 'Specific dissipation rate (ω)',
        'category': 'turbulence'
    },
    'turbulence_nu': {
        'patterns': ['turbulence_nu.png', '*turbulence*nu*.png', '*nu_t*.png'],
        'description_fi': 'Turbulentti viskositeetti (νt)',
        'description_en': 'Turbulent viscosity (νt)',
        'category': 'turbulence'
    },
    
    # Mukavuus / comfort
    'comfort': {
        'patterns': ['comfort*.png', '*lawson*.png'],
        'description_fi': 'Tuulimukavuus (Lawson)',
        'description_en': 'Wind comfort (Lawson)',
        'category': 'comfort'
    },
    'u_tau': {
        'patterns': ['u_tau*.png', '*friction_velocity*.png'],
        'description_fi': 'Kitkanopeus (u*)',
        'description_en': 'Friction velocity (u*)',
        'category': 'comfort'
    },
    
    # Combined / multi-wind
    'combined_wdr': {
        'patterns': ['combined_wdr*.png', '*wdr_moisture*.png'],
        'description_fi': 'Viistosateen kosteusindeksi',
        'description_en': 'Wind-driven rain moisture index',
        'category': 'combined'
    },
    'combined_pressure_max': {
        'patterns': ['combined_pressure_max*.png', '*pressure_max*.png'],
        'description_fi': 'Maksimipaine (kaikki suunnat)',
        'description_en': 'Maximum pressure (all directions)',
        'category': 'combined'
    },
    'combined_pressure_min': {
        'patterns': ['combined_pressure_min*.png', '*pressure_min*.png'],
        'description_fi': 'Minimipaine (kaikki suunnat)',
        'description_en': 'Minimum pressure (all directions)',
        'category': 'combined'
    },
    'velocity_weighted': {
        'patterns': ['velocity_weighted*.png', '*weighted_velocity*.png'],
        'description_fi': 'Painotettu nopeuskenttä',
        'description_en': 'Weighted velocity field',
        'category': 'combined'
    },
    'energy_index': {
        'patterns': ['energy_index*.png', '*building_energy*.png'],
        'description_fi': 'Rakennusten energiaindeksi',
        'description_en': 'Building energy index',
        'category': 'combined'
    },
    
    # Muut
    'nested_comparison': {
        'patterns': ['nested_comparison.png'],
        'description_fi': 'Hilavertailu (harva/tiheä)',
        'description_en': 'Grid comparison (coarse/fine)',
        'category': 'grid'
    },
    'adaptive_grid': {
        'patterns': ['*adaptive_grid.png'],
        'description_fi': 'Adaptiivinen laskentahila',
        'description_en': 'Adaptive computational grid',
        'category': 'grid'
    },
    'wind_rose': {
        'patterns': ['wind_rose.png', '*tuuliruusu*.png'],
        'description_fi': 'Tuuliruusu',
        'description_en': 'Wind rose',
        'category': 'weather'
    },
    'critical_points': {
        'patterns': ['kriittiset_pisteet.png', 'critical_points.png', 'building_ids.png'],
        'description_fi': 'Kriittiset pisteet',
        'description_en': 'Critical points',
        'category': 'buildings'
    },
    'target_detail': {
        'patterns': ['target_detail.png'],
        'description_fi': 'Kohderakennus – lähikuva',
        'description_en': 'Target building – detail view',
        'category': 'buildings'
    },
}


# =============================================================================
# APUFUNKTIOT
# =============================================================================

def find_image(results_dir: Path, patterns: List[str]) -> Optional[Path]:
    """Etsii kuvatiedoston usealla patternilla."""
    # Etsi fine-kansiosta ensin, sitten pääkansiosta
    search_dirs = [
        results_dir / 'fine',
        results_dir,
        results_dir / 'data',
    ]
    
    for search_dir in search_dirs:
        if not search_dir.exists():
            continue
        for pattern in patterns:
            matches = list(search_dir.glob(pattern))
            if matches:
                return matches[0]
    
    return None


def load_metadata(results_dir: Path) -> Dict:
    """Lataa metadata eri lähteistä."""
    metadata = {}
    
    # Kokeile eri metadata-tiedostoja
    candidates = [
        results_dir / 'domain.json',
        results_dir / 'fine' / 'domain.json',
        results_dir / 'simulation_metadata.json',
        results_dir.parent / 'multi_wind_metadata.json',
    ]
    
    for candidate in candidates:
        if candidate.exists():
            try:
                with open(candidate, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                metadata.update(data)
            except:
                pass
    
    return metadata


def get_text(key: str, lang: str, custom_texts: Dict = None) -> str:
    """Hakee käännetyn tekstin."""
    texts = {
        'fi': {
            'summary': 'Yhteenveto',
            'simulation_settings': 'Simuloinnin tiedot',
            'results': 'Tulokset',
            'wind_direction': 'Tuulensuunta',
            'wind_speed': 'Tuulennopeus',
            'grid': 'Laskentahila',
            'cells': 'solua',
            'page': 'Sivu',
            'generated': 'Luotu',
        },
        'en': {
            'summary': 'Summary',
            'simulation_settings': 'Simulation Settings',
            'results': 'Results',
            'wind_direction': 'Wind direction',
            'wind_speed': 'Wind speed',
            'grid': 'Computational grid',
            'cells': 'cells',
            'page': 'Page',
            'generated': 'Generated',
        }
    }
    
    # Custom texts override
    if custom_texts and key in custom_texts:
        return custom_texts[key]
    
    return texts.get(lang, texts['fi']).get(key, key)


# =============================================================================
# SIVUJEN GENEROINTI
# =============================================================================

def add_cover_page(pdf: PdfPages, config: Dict, metadata: Dict):
    """Lisää kansilehti."""
    fig, ax = plt.subplots(figsize=(8.27, 11.69))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis('off')
    
    title = config.get('title', 'CFD-tuulianalyysi')
    subtitle = config.get('subtitle', '')
    author = config.get('author', '')
    date = config.get('date', datetime.datetime.now().strftime('%d.%m.%Y'))
    
    # Otsikko
    ax.text(0.5, 0.6, title, ha='center', va='center', 
            fontsize=24, fontweight='bold', color=DARK_BLUE)
    
    if subtitle:
        ax.text(0.5, 0.52, subtitle, ha='center', va='center', 
                fontsize=14, color=TEXT_GRAY)
    
    # Metadata
    y_pos = 0.35
    if author:
        ax.text(0.5, y_pos, author, ha='center', va='center', fontsize=12)
        y_pos -= 0.04
    
    ax.text(0.5, y_pos, date, ha='center', va='center', fontsize=12, color=TEXT_GRAY)
    
    # Logo/footer
    ax.text(0.5, 0.08, 'MikroilmastoCFD', ha='center', va='center', 
            fontsize=10, color=TEXT_GRAY, style='italic')
    
    pdf.savefig(fig)
    plt.close(fig)


def add_image_page(pdf: PdfPages, img_path: Path, caption: str, 
                   section: str = None, description: str = None):
    """Lisää kuvasivu."""
    fig, ax = plt.subplots(figsize=(8.27, 11.69))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis('off')
    
    y_top = 0.95
    
    # Osion otsikko
    if section:
        ax.fill_between([0.05, 0.95], y_top - 0.02, y_top + 0.02, 
                       color=LIGHT_BLUE, alpha=1.0)
        ax.text(0.5, y_top, section, ha='center', va='center', 
                fontsize=12, fontweight='bold', color=DARK_BLUE)
        y_top -= 0.06
    
    # Kuvateksti
    if caption:
        ax.text(0.5, y_top, caption, ha='center', va='center', 
                fontsize=11, fontweight='bold')
        y_top -= 0.03
    
    # Kuva
    try:
        img = plt.imread(str(img_path))
        img_ax = fig.add_axes([0.05, 0.12, 0.9, y_top - 0.15])
        img_ax.imshow(img)
        img_ax.axis('off')
    except Exception as e:
        ax.text(0.5, 0.5, f'Kuvaa ei voitu ladata:\n{img_path.name}\n{e}', 
                ha='center', va='center', fontsize=10, color='red')
    
    # Kuvaus
    if description:
        ax.text(0.5, 0.08, description, ha='center', va='center', 
                fontsize=9, color=TEXT_GRAY, style='italic',
                wrap=True)
    
    pdf.savefig(fig)
    plt.close(fig)


def add_two_images_page(pdf: PdfPages, img1_path: Path, img2_path: Path,
                        caption1: str, caption2: str, section: str = None):
    """Lisää sivu kahdella kuvalla."""
    fig, axes = plt.subplots(2, 1, figsize=(8.27, 11.69))
    
    for i, (ax, img_path, caption) in enumerate([(axes[0], img1_path, caption1), 
                                                   (axes[1], img2_path, caption2)]):
        ax.axis('off')
        
        if img_path and img_path.exists():
            try:
                img = plt.imread(str(img_path))
                ax.imshow(img)
                ax.set_title(caption, fontsize=10, fontweight='bold', pad=5)
            except:
                ax.text(0.5, 0.5, f'Kuvaa ei voitu ladata', ha='center', va='center')
        else:
            ax.text(0.5, 0.5, f'Kuva puuttuu', ha='center', va='center', color='gray')
    
    plt.tight_layout()
    pdf.savefig(fig)
    plt.close(fig)


def add_text_page(pdf: PdfPages, title: str, content: str, lang: str = 'fi'):
    """Lisää tekstisivu."""
    fig, ax = plt.subplots(figsize=(8.27, 11.69))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis('off')
    
    # Otsikko
    ax.text(0.5, 0.92, title, ha='center', va='center', 
            fontsize=14, fontweight='bold', color=DARK_BLUE)
    
    # Sisältö
    ax.text(0.08, 0.85, content, ha='left', va='top', 
            fontsize=10, wrap=True, linespacing=1.5)
    
    pdf.savefig(fig)
    plt.close(fig)


def add_settings_page(pdf: PdfPages, metadata: Dict, config: Dict):
    """Lisää simuloinnin tiedot -sivu."""
    lang = config.get('language', 'fi')
    
    fig, ax = plt.subplots(figsize=(8.27, 11.69))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis('off')
    
    title = get_text('simulation_settings', lang)
    ax.text(0.5, 0.92, title, ha='center', va='center', 
            fontsize=14, fontweight='bold', color=DARK_BLUE)
    
    y_pos = 0.85
    
    # Tuulensuunta
    direction = metadata.get('inlet_direction', metadata.get('wind_direction', 0))
    velocity = metadata.get('inlet_velocity', 5.0)
    
    # CFD -> meteo
    meteo_deg = (270 - direction + 360) % 360
    dirs = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 
           'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW']
    idx = int((meteo_deg + 11.25) / 22.5) % 16
    dir_name = dirs[idx]
    
    ax.text(0.1, y_pos, f"{get_text('wind_direction', lang)}: {dir_name} ({direction:.0f}° CFD)", 
            ha='left', va='top', fontsize=11)
    y_pos -= 0.04
    
    ax.text(0.1, y_pos, f"{get_text('wind_speed', lang)}: {velocity:.1f} m/s", 
            ha='left', va='top', fontsize=11)
    y_pos -= 0.04
    
    # Hila
    nx = metadata.get('nx')
    ny = metadata.get('ny')
    dx = metadata.get('dx')
    
    if nx and ny:
        cells = nx * ny
        grid_str = f"{nx} × {ny} ({cells:,} {get_text('cells', lang)})"
        if dx:
            grid_str += f", dx={dx:.2f} m"
        ax.text(0.1, y_pos, f"{get_text('grid', lang)}: {grid_str}", 
                ha='left', va='top', fontsize=11)
        y_pos -= 0.04
    
    # Turbulenssimalli
    turb = metadata.get('turbulence_model', 'SST k-ω')
    if lang == 'fi':
        ax.text(0.1, y_pos, f"Turbulenssimalli: {turb}", ha='left', va='top', fontsize=11)
    else:
        ax.text(0.1, y_pos, f"Turbulence model: {turb}", ha='left', va='top', fontsize=11)
    
    pdf.savefig(fig)
    plt.close(fig)


# =============================================================================
# PÄÄFUNKTIO
# =============================================================================

def generate_custom_report(config_path: Path, results_dir: Path, 
                           output_path: Path = None) -> str:
    """
    Generoi räätälöidyn PDF-raportin.
    
    Args:
        config_path: Polku JSON-konfiguraatiotiedostoon
        results_dir: Polku tuloskansion
        output_path: Polku tuloste-PDF:lle (valinnainen)
    
    Returns:
        Polku luotuun PDF-tiedostoon
    """
    # Lataa konfiguraatio
    with open(config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)
    
    # Lataa metadata
    metadata = load_metadata(results_dir)
    
    # Määritä output
    if output_path is None:
        output_name = config.get('output_name', 'custom_report.pdf')
        output_path = results_dir / output_name
    
    lang = config.get('language', 'fi')
    
    print(f"\n{'='*60}")
    print(f"  MikroilmastoCFD - Custom Report Generator")
    print(f"{'='*60}")
    print(f"  Konfiguraatio: {config_path}")
    print(f"  Tuloskansio: {results_dir}")
    print(f"  Kieli: {lang}")
    print(f"  Output: {output_path}")
    print(f"{'='*60}\n")
    
    # Luo PDF
    with PdfPages(str(output_path)) as pdf:
        sections = config.get('sections', [])
        section_num = 0
        
        for section in sections:
            section_type = section.get('type', 'image')
            
            # =================================================================
            # COVER - Kansilehti
            # =================================================================
            if section_type == 'cover':
                add_cover_page(pdf, config, metadata)
                print(f"  ✓ Kansilehti")
            
            # =================================================================
            # IMAGE - Yksittäinen kuva
            # =================================================================
            elif section_type == 'image':
                file_spec = section.get('file', '')
                caption = section.get('caption', '')
                description = section.get('description', '')
                section_title = section.get('section')
                
                # Jos file on visualisointityyppi, hae patterns
                if file_spec in AVAILABLE_VISUALIZATIONS:
                    viz = AVAILABLE_VISUALIZATIONS[file_spec]
                    patterns = viz['patterns']
                    if not caption:
                        caption = viz.get(f'description_{lang}', viz.get('description_fi', file_spec))
                else:
                    patterns = [file_spec]
                
                img_path = find_image(results_dir, patterns)
                
                if img_path:
                    section_num += 1
                    section_label = f"{section_num}. {section_title}" if section_title else None
                    add_image_page(pdf, img_path, caption, section_label, description)
                    print(f"  ✓ {img_path.name}")
                else:
                    print(f"  ⚠ Kuvaa ei löytynyt: {file_spec}")
            
            # =================================================================
            # TWO_IMAGES - Kaksi kuvaa samalla sivulla
            # =================================================================
            elif section_type == 'two_images':
                file1 = section.get('file1', '')
                file2 = section.get('file2', '')
                caption1 = section.get('caption1', '')
                caption2 = section.get('caption2', '')
                section_title = section.get('section')
                
                # Hae kuvat
                def get_patterns(file_spec):
                    if file_spec in AVAILABLE_VISUALIZATIONS:
                        return AVAILABLE_VISUALIZATIONS[file_spec]['patterns']
                    return [file_spec]
                
                img1 = find_image(results_dir, get_patterns(file1))
                img2 = find_image(results_dir, get_patterns(file2))
                
                if img1 or img2:
                    section_num += 1
                    add_two_images_page(pdf, img1, img2, caption1, caption2, section_title)
                    print(f"  ✓ Kaksi kuvaa: {file1}, {file2}")
            
            # =================================================================
            # TEXT - Tekstisivu
            # =================================================================
            elif section_type == 'text':
                title = section.get('title', '')
                content = section.get('content', '')
                add_text_page(pdf, title, content, lang)
                print(f"  ✓ Tekstisivu: {title}")
            
            # =================================================================
            # SETTINGS - Simuloinnin tiedot
            # =================================================================
            elif section_type == 'settings':
                add_settings_page(pdf, metadata, config)
                print(f"  ✓ Simuloinnin tiedot")
            
            # =================================================================
            # AUTO_IMAGES - Automaattinen kuvien haku kategorian mukaan
            # =================================================================
            elif section_type == 'auto_images':
                category = section.get('category', 'basic')
                max_images = section.get('max', 10)
                
                count = 0
                for viz_name, viz_info in AVAILABLE_VISUALIZATIONS.items():
                    if viz_info.get('category') != category:
                        continue
                    if count >= max_images:
                        break
                    
                    img_path = find_image(results_dir, viz_info['patterns'])
                    if img_path:
                        section_num += 1
                        caption = viz_info.get(f'description_{lang}', viz_info.get('description_fi', viz_name))
                        add_image_page(pdf, img_path, caption)
                        print(f"  ✓ [auto] {img_path.name}")
                        count += 1
    
    print(f"\n  ✓ Raportti luotu: {output_path}")
    return str(output_path)


def list_visualizations():
    """Listaa saatavilla olevat visualisointityypit."""
    print("\n" + "="*70)
    print("  SAATAVILLA OLEVAT VISUALISOINTITYYPIT")
    print("="*70 + "\n")
    
    categories = {}
    for name, info in AVAILABLE_VISUALIZATIONS.items():
        cat = info.get('category', 'other')
        if cat not in categories:
            categories[cat] = []
        categories[cat].append((name, info))
    
    for cat, items in sorted(categories.items()):
        print(f"  [{cat.upper()}]")
        for name, info in items:
            desc = info.get('description_fi', name)
            patterns = ', '.join(info['patterns'][:2])
            print(f"    {name:25} - {desc}")
            print(f"    {' '*25}   patterns: {patterns}")
        print()


def create_example_config(output_path: Path):
    """Luo esimerkkikonfiguraatiotiedosto."""
    example = {
        "title": "Tuulianalyysi - Esimerkkiprojekti",
        "subtitle": "CFD-simuloinnin tulokset",
        "author": "MikroilmastoCFD",
        "language": "fi",
        "output_name": "custom_report.pdf",
        "sections": [
            {
                "type": "cover"
            },
            {
                "type": "image",
                "file": "velocity_streamlines",
                "caption": "Nopeuskenttä ja virtaviivat",
                "section": "Tulokset"
            },
            {
                "type": "image",
                "file": "pressure_streamlines",
                "caption": "Painekenttä ja virtaviivat"
            },
            {
                "type": "two_images",
                "file1": "turbulence_k",
                "file2": "turbulence_omega",
                "caption1": "Turbulenttinen kineettinen energia (k)",
                "caption2": "Spesifinen dissipaationopeus (ω)"
            },
            {
                "type": "image",
                "file": "comfort",
                "caption": "Tuulimukavuus (Lawsonin kriteerit)"
            },
            {
                "type": "text",
                "title": "Johtopäätökset",
                "content": "Tähän voi kirjoittaa vapaamuotoista tekstiä raporttiin."
            },
            {
                "type": "settings"
            }
        ]
    }
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(example, f, ensure_ascii=False, indent=2)
    
    print(f"  ✓ Esimerkkikonfiguraatio luotu: {output_path}")


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='MikroilmastoCFD - Custom Report Generator',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Esimerkkejä:
  # Generoi raportti konfiguraation mukaan
  python generate_custom_report.py config.json --results results/wind_180deg
  
  # Listaa saatavilla olevat visualisointityypit
  python generate_custom_report.py --list
  
  # Luo esimerkkikonfiguraatio
  python generate_custom_report.py --create-example example_config.json
        """
    )
    
    parser.add_argument('config', nargs='?', type=str,
                        help='Polku JSON-konfiguraatiotiedostoon')
    parser.add_argument('--results', '-r', type=str,
                        help='Polku tuloskansion')
    parser.add_argument('--output', '-o', type=str,
                        help='Polku tuloste-PDF:lle')
    parser.add_argument('--list', '-l', action='store_true',
                        help='Listaa saatavilla olevat visualisointityypit')
    parser.add_argument('--create-example', '-c', type=str, metavar='FILE',
                        help='Luo esimerkkikonfiguraatiotiedosto')
    
    args = parser.parse_args()
    
    # Listaa visualisoinnit
    if args.list:
        list_visualizations()
        return
    
    # Luo esimerkki
    if args.create_example:
        create_example_config(Path(args.create_example))
        return
    
    # Generoi raportti
    if not args.config:
        parser.print_help()
        print("\n  VIRHE: Anna konfiguraatiotiedosto tai käytä --list / --create-example")
        return
    
    if not args.results:
        parser.print_help()
        print("\n  VIRHE: Anna tuloskansio --results parametrilla")
        return
    
    config_path = Path(args.config)
    results_dir = Path(args.results)
    output_path = Path(args.output) if args.output else None
    
    if not config_path.exists():
        print(f"  VIRHE: Konfiguraatiotiedostoa ei löydy: {config_path}")
        return
    
    if not results_dir.exists():
        print(f"  VIRHE: Tuloskansiota ei löydy: {results_dir}")
        return
    
    generate_custom_report(config_path, results_dir, output_path)


if __name__ == '__main__':
    main()
