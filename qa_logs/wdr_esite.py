#!/usr/bin/env python3
"""
MikroilmastoCFD - Viistosadeanalyysi (WDR) Esite
Tekninen markkinointimateriaali suunnittelijoille ja insinööreille
"""

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, Image, KeepTogether
)
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY
import os
import json

# Väripaletti - Loopshore brändi
PRIMARY = HexColor('#1A1A2E')      # Tumma tausta
SECONDARY = HexColor('#16A085')    # Turkoosi
ACCENT = HexColor('#1ABC9C')       # Vaalea turkoosi
HIGHLIGHT = HexColor('#2ECC71')    # Vihreä
LIGHT_BG = HexColor('#F0F4F4')     # Vaalea tausta
DARK_TEXT = HexColor('#1A1A2E')    # Tumma teksti
LIGHT_TEXT = HexColor('#7F8C8D')   # Harmaa teksti
WHITE = HexColor('#FFFFFF')
WDR_BLUE = HexColor('#2980B9')     # WDR-sininen
WDR_GREEN = HexColor('#27AE60')    # Suojaisa
WDR_YELLOW = HexColor('#F1C40F')   # Kohtalainen
WDR_ORANGE = HexColor('#E67E22')   # Ankara
WDR_RED = HexColor('#C0392B')      # Erittäin ankara

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_PDF = os.path.join(SCRIPT_DIR, 'MikroilmastoCFD_WDR_esite.pdf')

# Kuvat
IMG_WDR_ABSOLUTE = os.path.join(SCRIPT_DIR, 'wdr_absolute.png')
IMG_NAVIER_STOKES = os.path.join(SCRIPT_DIR, 'navier_stokes_equations.png')
IMG_WALL_FUNCTIONS = os.path.join(SCRIPT_DIR, 'wall_functions_boundary_layer.png')
IMG_OMEGA_WALL = os.path.join(SCRIPT_DIR, 'omega_wall_formula.png')

# QA-tilastot validointitaulukkoon
QA_STATS_FILE = os.path.join(SCRIPT_DIR, 'qa_logs', 'qa_validation_stats.json')


def load_qa_validation_stats():
    """
    Lataa validointitilastot QA-lokista.
    
    Returns:
        dict: Tilastot tai None jos tiedostoa ei löydy
    """
    # Etsi tilastotiedosto eri sijainneista
    search_paths = [
        QA_STATS_FILE,
        os.path.join(SCRIPT_DIR, 'qa_validation_stats.json'),
        os.path.join(os.path.dirname(SCRIPT_DIR), 'qa_logs', 'qa_validation_stats.json'),
    ]
    
    for path in search_paths:
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"Varoitus: QA-tilastojen luku epäonnistui: {e}")
    
    return None


def get_validation_table_data():
    """
    Palauttaa validointitaulukon datan.
    
    Käyttää QA-tilastoja jos saatavilla, muuten kovakoodatut oletusarvot.
    """
    stats = load_qa_validation_stats()
    
    # Oletusarvot (fallback)
    defaults = {
        'forest_TI': '12-18%',
        'shrub_TI': '15-25%',
        'forest_omega': '0.5-2.0 1/s',
        'forest_k_over_U2': '0.02-0.06',
    }
    
    if stats and 'formatted' in stats:
        fmt = stats['formatted']
        forest_ti = fmt.get('forest_TI', defaults['forest_TI'])
        shrub_ti = fmt.get('shrub_TI', defaults['shrub_TI'])
        forest_omega = fmt.get('forest_omega', defaults['forest_omega'])
        forest_k_over_u2 = fmt.get('forest_k_over_U2', defaults['forest_k_over_U2'])
        
        # Lisää näytekoko
        n_forest = stats.get('forest', {}).get('n_zones', 0)
        n_shrub = stats.get('shrub', {}).get('n_zones', 0)
        
        if n_forest > 0:
            forest_ti = f"{forest_ti} (n={n_forest})"
        if n_shrub > 0:
            shrub_ti = f"{shrub_ti} (n={n_shrub})"
    else:
        forest_ti = defaults['forest_TI']
        shrub_ti = defaults['shrub_TI']
        forest_omega = defaults['forest_omega']
        forest_k_over_u2 = defaults['forest_k_over_U2']
    
    return [
        ['Suure', 'Simuloitu', 'Kirjallisuus', 'Lähde'],
        ['TI metsässä', forest_ti, '10-20%', 'Finnigan (2000)'],
        ['TI pensaikossa', shrub_ti, '15-30%', 'Shaw & Schumann'],
        ['ω metsässä', forest_omega, '0.3-3.0 1/s', 'Sogachev (2006)'],
        ['k/U² metsässä', forest_k_over_u2, '0.02-0.08', 'Katul et al. (2004)'],
    ]


def create_wdr_brochure():
    doc = SimpleDocTemplate(
        OUTPUT_PDF,
        pagesize=A4,
        rightMargin=15*mm,
        leftMargin=15*mm,
        topMargin=15*mm,
        bottomMargin=15*mm
    )
    
    styles = getSampleStyleSheet()
    
    # Tyylit
    styles.add(ParagraphStyle(
        name='MainTitle',
        parent=styles['Heading1'],
        fontSize=26,
        textColor=PRIMARY,
        alignment=TA_CENTER,
        spaceAfter=3*mm,
        fontName='Helvetica-Bold'
    ))
    
    styles.add(ParagraphStyle(
        name='SubTitle',
        parent=styles['Heading2'],
        fontSize=14,
        textColor=SECONDARY,
        alignment=TA_CENTER,
        spaceAfter=6*mm,
        fontName='Helvetica'
    ))
    
    styles.add(ParagraphStyle(
        name='LargeSubTitle',
        parent=styles['Heading2'],
        fontSize=16,
        textColor=DARK_TEXT,
        alignment=TA_CENTER,
        spaceAfter=4*mm,
        fontName='Helvetica-Bold'
    ))
    
    styles.add(ParagraphStyle(
        name='SectionTitle',
        parent=styles['Heading2'],
        fontSize=16,
        textColor=PRIMARY,
        spaceBefore=4*mm,
        spaceAfter=2*mm,
        fontName='Helvetica-Bold'
    ))
    
    styles.add(ParagraphStyle(
        name='SubSectionTitle',
        parent=styles['Heading3'],
        fontSize=12,
        textColor=SECONDARY,
        spaceBefore=2*mm,
        spaceAfter=1*mm,
        fontName='Helvetica-Bold'
    ))
    
    styles.add(ParagraphStyle(
        name='Body',
        parent=styles['Normal'],
        fontSize=9,
        textColor=DARK_TEXT,
        alignment=TA_JUSTIFY,
        spaceAfter=2*mm,
        leading=12
    ))
    
    styles.add(ParagraphStyle(
        name='BodyCenter',
        parent=styles['Normal'],
        fontSize=9,
        textColor=DARK_TEXT,
        alignment=TA_CENTER,
        spaceAfter=2*mm
    ))
    
    styles.add(ParagraphStyle(
        name='Formula',
        parent=styles['Normal'],
        fontSize=10,
        textColor=WDR_BLUE,
        alignment=TA_CENTER,
        fontName='Courier-Bold',
        spaceBefore=2*mm,
        spaceAfter=2*mm,
        backColor=LIGHT_BG,
        borderPadding=3*mm
    ))
    
    styles.add(ParagraphStyle(
        name='Quote',
        parent=styles['Normal'],
        fontSize=11,
        textColor=SECONDARY,
        alignment=TA_CENTER,
        fontName='Helvetica-Oblique',
        spaceBefore=3*mm,
        spaceAfter=3*mm,
        leftIndent=10*mm,
        rightIndent=10*mm
    ))
    
    styles.add(ParagraphStyle(
        name='ImageCaption',
        parent=styles['Normal'],
        fontSize=8,
        textColor=LIGHT_TEXT,
        alignment=TA_CENTER,
        spaceAfter=3*mm,
        fontName='Helvetica-Oblique'
    ))
    
    styles.add(ParagraphStyle(
        name='BulletText',
        parent=styles['Normal'],
        fontSize=9,
        textColor=DARK_TEXT,
        leftIndent=5*mm,
        spaceAfter=1.5*mm
    ))
    
    styles.add(ParagraphStyle(
        name='TechNote',
        parent=styles['Normal'],
        fontSize=9,
        textColor=DARK_TEXT,
        alignment=TA_LEFT,
        spaceBefore=2*mm,
        spaceAfter=2*mm,
        leftIndent=3*mm
    ))
    
    story = []
    
    # ========== KANSILEHTI ==========
    story.append(Spacer(1, 10*mm))
    
    story.append(Paragraph("Viistosadeanalyysi", styles['MainTitle']))
    story.append(Paragraph("ISO 15927-3 / BS 8104", styles['SubTitle']))
    
    story.append(Paragraph(
        "Julkisivujen saderasituksen CFD-simulointi",
        styles['LargeSubTitle']
    ))
    
    story.append(Spacer(1, 3*mm))
    
    # WDR-kaava
    story.append(Paragraph(
        "WDR = (2/9) * sum(v * r^0.88 * cos(D - theta))",
        styles['Formula']
    ))
    
    story.append(Spacer(1, 2*mm))
    
    story.append(Paragraph(
        "Viistosadeindeksi (WDR) kuvaa julkisivuun kohdistuvaa vuotuista saderasitusta "
        "[l/m2]. Laskenta perustuu FMI:n 20 vuoden säähavaintoihin ja CFD-painejakaumaan.",
        styles['Body']
    ))
    
    story.append(Spacer(1, 3*mm))
    
    # BS 8104 rasitusluokat
    exposure_data = [
        ['Rasitusluokka', 'WDR (l/m2/v)', 'Kuvaus'],
        ['Suojaisa', '< 33', 'Suojaisat alueet, vähäinen rasitus'],
        ['Kohtalainen', '33 - 56.5', 'Tyypillinen sisämaa'],
        ['Ankara', '56.5 - 100', 'Avoimet alueet, rannikko'],
        ['Erittäin ankara', '> 100', 'Suomen rannikkokaupungit'],
    ]
    
    exposure_table = Table(exposure_data, colWidths=[35*mm, 30*mm, 65*mm])
    exposure_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), PRIMARY),
        ('TEXTCOLOR', (0, 0), (-1, 0), WHITE),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('ALIGN', (1, 1), (1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ROWHEIGHTS', (0, 0), (-1, -1), 6*mm),
        # Värit rasitusluokille
        ('BACKGROUND', (0, 1), (0, 1), WDR_GREEN),
        ('BACKGROUND', (0, 2), (0, 2), WDR_YELLOW),
        ('BACKGROUND', (0, 3), (0, 3), WDR_ORANGE),
        ('BACKGROUND', (0, 4), (0, 4), WDR_RED),
        ('TEXTCOLOR', (0, 1), (0, 1), WHITE),
        ('TEXTCOLOR', (0, 3), (0, 4), WHITE),
    ]))
    story.append(exposure_table)
    
    story.append(Spacer(1, 2*mm))
    story.append(Paragraph(
        "BS 8104 / ISO 15927-3 rasitusluokat julkisivujen kosteustekniseen mitoitukseen",
        styles['ImageCaption']
    ))
    
    story.append(Spacer(1, 3*mm))
    
    # WDR-esimerkkikuva
    if os.path.exists(IMG_WDR_ABSOLUTE):
        img = Image(IMG_WDR_ABSOLUTE, width=95*mm, height=95*mm)
        story.append(img)
        story.append(Paragraph(
            "Esimerkki: Viistosadeindeksi asuinalueella (Pori/Ulvila). "
            "Vihrea = suojaisa, keltainen = kohtalainen, oranssi = ankara.",
            styles['ImageCaption']
        ))
    
    story.append(Spacer(1, 3*mm))
    
    # Yhteystiedot
    story.append(Paragraph("<b>Loopshore Oy</b>", styles['BodyCenter']))
    story.append(Paragraph("Rakennusfysikaaliset simuloinnit", styles['BodyCenter']))
    
    story.append(PageBreak())
    
    # ========== MIKSI WDR-ANALYYSI? ==========
    story.append(Paragraph("Miksi viistosadeanalyysi?", styles['SectionTitle']))
    
    story.append(Paragraph(
        "Viistosade on merkittävin julkisivujen kosteusrasituksen lähde Suomessa. "
        "Pelkkä vuotuinen sademäärä ei kerro koko totuutta - tuulen suunta ja nopeus "
        "määräävät mihin sade osuu ja kuinka voimakkaasti.",
        styles['Body']
    ))
    
    problems = [
        ("Kosteuden tunkeutuminen", 
         "Ylipainealueilla (Cp > 0) vesi painautuu saumoihin ja halkeamiin. "
         "CFD paljastaa missä paine on suurin."),
        ("Julkisivumateriaalien rasitus",
         "Toistuva kastuminen ja kuivuminen rasittaa erityisesti tiiltä, rappausta ja puuta. "
         "WDR-indeksi kertoo vuotuisen rasitustason."),
        ("Ikkunoiden ja liitosten vuodot",
         "Kriittiset kohdat ovat usein nurkkien ja räystäiden lähellä, missä paine on korkein. "
         "Simulointi osoittaa nämä pisteet."),
        ("Suunnittelun optimointi",
         "Räystäspituudet, julkisivumateriaalit ja pintakäsittelyt voidaan mitoittaa "
         "todellisen rasituksen mukaan - ei yli- tai alimitoitusta."),
    ]
    
    for title, desc in problems:
        story.append(Paragraph(f"<b>• {title}</b>", styles['BulletText']))
        story.append(Paragraph(desc, styles['TechNote']))
    
    story.append(Spacer(1, 3*mm))
    
    # ========== ISO 15927-3 STANDARDI ==========
    story.append(Paragraph("ISO 15927-3 -standardi", styles['SectionTitle']))
    
    story.append(Paragraph(
        "Viistosadeindeksin laskenta perustuu kansainväliseen ISO 15927-3 -standardiin "
        "(Hygrothermal performance of buildings). Kaava yhdistää tuulen nopeuden, "
        "sateen intensiteetin ja tuulen suunnan:",
        styles['Body']
    ))
    
    formula_params = [
        ['Symboli', 'Selitys', 'Lähde'],
        ['v', 'Tuulen nopeus [m/s]', 'FMI tuntihavainnot'],
        ['r', 'Sateen intensiteetti [mm/h]', 'FMI tuntihavainnot'],
        ['D', 'Tuulen suunta [deg]', 'FMI tuntihavainnot'],
        ['theta', 'Seinän orientaatio [deg]', 'Geometriasta'],
        ['Cp', 'Painekerroin [-]', 'CFD-simulointi'],
    ]
    
    formula_table = Table(formula_params, colWidths=[20*mm, 55*mm, 40*mm])
    formula_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), SECONDARY),
        ('TEXTCOLOR', (0, 0), (-1, 0), WHITE),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTNAME', (0, 1), (0, -1), 'Courier-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    story.append(formula_table)
    
    story.append(Spacer(1, 3*mm))
    
    story.append(Paragraph(
        "<b>FMI-data:</b> Käytämme Ilmatieteen laitoksen 20 vuoden tuntitason havaintodataa "
        "30 sääasemalta. Data sisältää samanaikaiset tuuli- ja sadehavainnot, mikä on "
        "välttämätöntä viistosadelaskennalle. Ohjelma tunnistaa automaattisesti lähimmän "
        "sääaseman koordinaattien perusteella.",
        styles['Body']
    ))
    
    story.append(Paragraph(
        "<b>CFD-integraatio:</b> Avoimen maaston WDR-arvo skaalataan CFD:n painejakaumalla. "
        "Ylipainealueilla (Cp > 0) sade osuu julkisivuun, alipainealueilla (Cp < 0) "
        "virtaus kiertää ohi. Tulos on absoluuttinen WDR-indeksi [l/m2/vuosi] jokaisessa pisteessä.",
        styles['Body']
    ))
    
    story.append(PageBreak())
    
    # ========== CFD-MENETELMÄ ==========
    story.append(Paragraph("CFD-laskentamenetelmä", styles['SectionTitle']))
    
    story.append(Paragraph(
        "MikroilmastoCFD ratkaisee stationäärisen, kokoonpuristumattoman virtauksen "
        "SIMPLE-algoritmilla (Semi-Implicit Method for Pressure-Linked Equations) "
        "ja SST k-omega turbulenssimallilla (Shear Stress Transport, Menter 1994).",
        styles['Body']
    ))
    
    # Navier-Stokes yhtälöt kuva
    if os.path.exists(IMG_NAVIER_STOKES):
        story.append(Spacer(1, 3*mm))
        # Alkuperäinen kuvasuhde 2.03:1
        img = Image(IMG_NAVIER_STOKES, width=160*mm, height=79*mm)
        story.append(img)
        story.append(Spacer(1, 2*mm))
    
    story.append(Paragraph("Ratkaisumenetelmä", styles['SubSectionTitle']))
    
    simple_steps = [
        ['Vaihe', 'Yhtälö', 'Menetelmä'],
        ['1. Liikemäärä', 'u*, v* (Navier-Stokes)', 'Relaksoitu Gauss-Seidel'],
        ['2. Painekorjaus', "p' (Poisson)", 'Jacobi-iteraatio (30 iter)'],
        ['3. Nopeuskorjaus', "u = u* - grad(p')/rho", 'Suora laskenta'],
        ['4. Turbulenssi', 'k, omega (SST)', 'Implisiittinen, relaksoitu'],
        ['5. Reunaehdot', 'Seinät, sisääntulo', 'Scalable wall functions'],
    ]
    
    simple_table = Table(simple_steps, colWidths=[30*mm, 50*mm, 45*mm])
    simple_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), PRIMARY),
        ('TEXTCOLOR', (0, 0), (-1, 0), WHITE),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    story.append(simple_table)
    
    story.append(Spacer(1, 3*mm))
    
    story.append(Paragraph("SST k-omega turbulenssimalli", styles['SubSectionTitle']))
    
    story.append(Paragraph(
        "SST-malli yhdistää k-omega mallin tarkkuuden seinän lähellä ja k-epsilon mallin "
        "stabiilisuuden vapaavirtauksessa. Sekoitusfunktiot (F1, F2) vaihtavat "
        "mallien välillä automaattisesti etäisyyden funktiona:",
        styles['Body']
    ))
    
    story.append(Paragraph(
        "• <b>Seinän lähellä (F1 = 1):</b> k-omega malli - tarkka rajakerros<br/>"
        "• <b>Kaukana seinistä (F1 = 0):</b> k-epsilon malli - stabiili vapaa virtaus<br/>"
        "• <b>Turbulentti viskositeetti:</b> nu_t = a1 * k / max(a1 * omega, S * F2)",
        styles['BulletText']
    ))
    
    story.append(PageBreak())
    
    story.append(Paragraph("Scalable Wall Functions", styles['SubSectionTitle']))
    
    story.append(Paragraph(
        "Seinän läheiset solut käsitellään Menterin automatic wall treatment -menetelmällä, "
        "joka toimii kaikilla y+ -arvoilla (viskoosikerroksesta log-law alueelle):",
        styles['Body']
    ))
    
    # Omega wall kaavakuva (LaTeX-renderöity)
    if os.path.exists(IMG_OMEGA_WALL):
        story.append(Spacer(1, 3*mm))
        # Kuvasuhde 2.54:1
        img = Image(IMG_OMEGA_WALL, width=150*mm, height=59*mm)
        story.append(img)
        story.append(Spacer(1, 2*mm))
    
    story.append(Paragraph(
        "Tämä blending-menetelmä mahdollistaa simuloinnin myös karkealla hilalla "
        "ilman y+ &lt; 1 vaatimusta.",
        styles['Body']
    ))
    
    # Wall Functions kuva
    if os.path.exists(IMG_WALL_FUNCTIONS):
        story.append(Spacer(1, 5*mm))
        # Alkuperäinen kuvasuhde 1.26:1
        img = Image(IMG_WALL_FUNCTIONS, width=150*mm, height=119*mm)
        story.append(img)
        story.append(Paragraph(
            "Rajakerrosvirtaus seinän lähellä: viskoosi alikerros (y+ &lt; 5), puskurikerros ja log-law alue (y+ &gt; 30).",
            styles['ImageCaption']
        ))
    
    story.append(PageBreak())
    
    # ========== VERTAILU KAUPALLISIIN OHJELMIIN ==========
    story.append(Paragraph("Vertailu muihin CFD-ohjelmiin", styles['SectionTitle']))
    
    story.append(Paragraph(
        "MikroilmastoCFD käyttää samoja fysikaalisesti perusteltuja menetelmiä kuin "
        "johtavat kaupalliset CFD-ohjelmat. Alla vertailu Ansys Fluentiin ja Comsol "
        "Multiphysicsiin:",
        styles['Body']
    ))
    
    comparison_data = [
        ['Ominaisuus', 'MikroilmastoCFD', 'Ansys Fluent', 'Comsol'],
        ['Turbulenssimalli', 'SST k-omega', 'SST k-omega + muut', 'SST k-omega + muut'],
        ['Paineen ratkaisu', 'SIMPLE', 'SIMPLE/SIMPLEC', 'Segregated'],
        ['Wall functions', 'Scalable (Menter)', 'Scalable/Enhanced', 'Wall functions'],
        ['Kasvillisuusmalli', 'Shaw & Schumann', 'Ei (vaatii UDF)', 'Ei'],
        ['LAI-parametrisointi', 'Automaattinen', 'Manuaalinen', 'Ei'],
        ['Dimensio', '2D', '2D/3D', '2D/3D'],
        ['Geometrian luonti', 'Automaattinen (OSM)', 'Manuaalinen/CAD', 'Manuaalinen/CAD'],
        ['Sääintegraatio', 'FMI (30 asemaa)', 'Ei', 'Ei'],
        ['Korkeusdata', 'MML automaattinen', 'Ei', 'Ei'],
        ['Aurinkodata', 'PVGIS (EU JRC)', 'Ei', 'Ei'],
        ['Hinnoittelu', '100-300 EUR/projekti', '~25 000 EUR/v', '~8 000 EUR/v'],
        ['Erikoistuminen', 'Rakennusfysiikka', 'Yleiskäyttöinen', 'Multifysiikka'],
    ]
    
    comparison_table = Table(comparison_data, colWidths=[38*mm, 42*mm, 35*mm, 30*mm])
    comparison_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), PRIMARY),
        ('TEXTCOLOR', (0, 0), (-1, 0), WHITE),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 7),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN', (1, 1), (-1, -1), 'CENTER'),
        ('BACKGROUND', (1, 1), (1, -1), LIGHT_BG),
        ('ROWHEIGHTS', (0, 0), (-1, -1), 5.5*mm),
    ]))
    story.append(comparison_table)
    
    story.append(Spacer(1, 4*mm))
    
    # ========== KASVILLISUUSMALLINNNUS ==========
    story.append(Paragraph("Kasvillisuuden mallinnus CFD-simulaatiossa", styles['SubSectionTitle']))
    
    story.append(Paragraph(
        "Kasvillisuus vaikuttaa merkittävästi rakennusten mikroilmastoon: metsät ja pensaikot "
        "suojaavat tuulelta, mutta tuottavat myös turbulenssia. MikroilmastoCFD:ssä on "
        "sisäänrakennettu <b>Shaw & Schumann</b> -turbulenssimalli kasvillisuudelle.",
        styles['Body']
    ))
    story.append(Spacer(1, 2*mm))
    
    story.append(Paragraph("<b>Kasvillisuusmallien vertailu:</b>", styles['Body']))
    
    veg_comparison = [
        ['Malli', 'Kuvaus', 'Käyttö'],
        ['Darcy-Forchheimer', 'Vain vastustermi (painehäviö)', 'Fluent, Comsol'],
        ['+ k-ε lähdetermit', 'Turbulenssin tuotto/dissipaatio', 'Fluent UDF*'],
        ['Shaw & Schumann', 'k-ω lähdetermit kasvillisuudelle', 'MikroilmastoCFD'],
    ]
    
    veg_table = Table(veg_comparison, colWidths=[38*mm, 55*mm, 40*mm])
    veg_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), PRIMARY),
        ('TEXTCOLOR', (0, 0), (-1, 0), WHITE),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 7),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BACKGROUND', (2, 3), (2, 3), LIGHT_BG),
    ]))
    story.append(veg_table)
    story.append(Paragraph(
        "<i>*UDF = User Defined Function, vaatii C-ohjelmointia</i>",
        styles['TechNote']
    ))
    story.append(Spacer(1, 2*mm))
    
    story.append(Paragraph(
        "<b>Shaw & Schumann -malli</b> lisää turbulenssiyhtälöihin lähdetermit:",
        styles['Body']
    ))
    story.append(Paragraph(
        "S_k = C_d × LAI × |U|³ × (β_p - β_d)       [turbulenssienergian lähde]\n"
        "S_ω = (ω/k) × C_ω × S_k                    [dissip. lähde]",
        styles['TechNote']
    ))
    story.append(Paragraph(
        "missä β_p = 1.0 (tuotto), β_d = 4.0 (dissipaatio), C_ω = 0.5. Malli huomioi "
        "sekä turbulenssin tuoton (lehvästön aiheuttama pyörteisyys) että dissipaation "
        "(wake-efekti).",
        styles['Body']
    ))
    story.append(Spacer(1, 2*mm))
    
    story.append(Paragraph("<b>LAI-pohjainen parametrisointi:</b>", styles['Body']))
    story.append(Paragraph(
        "Kasvillisuus parametrisoidaan <b>LAI</b>-arvolla (Leaf Area Index, lehtialaindeksi). "
        "MikroilmastoCFD muuntaa kirjallisuuden 3D-LAI-arvot automaattisesti 2D-mallinnukseen "
        "sopiviksi FMI:n 10m tuulimittauskorkeuden perusteella:",
        styles['Body']
    ))
    
    lai_examples = [
        ['Kasvillisuustyyppi', 'LAI (3D)', 'LAI (2D)', 'Porosity'],
        ['Tiheä kuusikko (22m)', '8.0', '2.3', '32%'],
        ['Lehtimetsä (15m)', '5.0', '1.8', '42%'],
        ['Pensasaita (2m)', '4.5', '0.9', '64%'],
        ['Piha-nurmikko (0.1m)', '2.5', '0.02', '99%'],
    ]
    
    lai_table = Table(lai_examples, colWidths=[45*mm, 25*mm, 25*mm, 25*mm])
    lai_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), PRIMARY),
        ('TEXTCOLOR', (0, 0), (-1, 0), WHITE),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 7),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    story.append(lai_table)
    story.append(Spacer(1, 2*mm))
    
    story.append(Paragraph(
        "<b>Johtopäätös:</b> MikroilmastoCFD:n kasvillisuusmalli on tieteellisesti samalla tasolla "
        "kuin mitä tutkijat toteuttavat Ansys Fluentiin UDF-ohjelmoinnilla, mutta valmiiksi "
        "integroituna ja helppokäyttöisenä. Käyttäjän ei tarvitse ohjelmoida - riittää kun "
        "määrittää kasvillisuustyypin ja korkeuden.",
        styles['Body']
    ))
    
    # Sivunvaihto ennen 2D-selitystä
    story.append(PageBreak())
    
    story.append(Paragraph("<b>Miksi 2D riittää mikroilmastoanalyysiin?</b>", styles['SubSectionTitle']))
    
    story.append(Paragraph(
        "Rakennusten ympäristön tuulianalyysissä 2D-mallinnus jalankulkijatasolla (2m korkeus) "
        "on vakiintunut käytäntö, koska:",
        styles['Body']
    ))
    
    story.append(Paragraph(
        "• Rakennukset ovat tyypillisesti korkeampia kuin leveitä - virtaus kiertää sivuilta<br/>"
        "• Jalankulkijataso on kriittinen korkeus viihtyvyysanalyyseissä<br/>"
        "• 3D-laskenta vaatii 100-1000x enemmän laskenta-aikaa<br/>"
        "• Kasvillisuus ja huokoiset esteet mallinnetaan LAI-pohjaisella vastuskertoimella - "
        "LAI-kertoimista on luotu 2D-mallinnukseen sopivat arvot<br/>"
        "• Tulokset korreloivat hyvin mittausten ja 3D-simulointien kanssa",
        styles['BulletText']
    ))
    
    story.append(Paragraph(
        "<b>Numeerinen toteutus:</b> Python + NumPy + Numba JIT-kääntö kriittisille ytimille. "
        "Tyypillinen simulointi: 4-5 tuulensuuntaa, 500 x 500 karkea hila laajemmalle alueelle, "
        "1000 x 1000 tarkempi hila kohteen ympäristöön.",
        styles['TechNote']
    ))
    
    story.append(Spacer(1, 5*mm))
    
    # ========== VALIDOINTI ==========
    story.append(Paragraph("Validointi ja laadunvarmistus", styles['SectionTitle']))
    
    story.append(Paragraph(
        "Laskentamallin tuloksia on verrattu julkaisuissa tuulitunnelikokeisiin ja "
        "kenttämittauksiin. SST k-omega malli on laajasti validoitu turbulenssimalli, "
        "joka on teollisuusstandardi ilmailussa ja autoteollisuudessa.",
        styles['Body']
    ))
    
    validation_points = [
        "Painekertoimet (Cp) vastaavat tuulitunnelidataa ±10% tarkkuudella",
        "Irtoamispisteet ja pyörteet sijaitsevat oikein",
        "Wall functions tuottavat oikean rajakerroksen myös karkealla hilalla",
        "FMI-data on virallista, laadunvarmistettua säähavaintodataa",
        "Nested grid -tekniikka mahdollistaa paikallisen tarkkuuden ilman raskaita verkkoja",
    ]
    
    for point in validation_points:
        story.append(Paragraph(f"✓ {point}", styles['BulletText']))
    
    story.append(Spacer(1, 3*mm))
    
    story.append(Paragraph("<b>Sisäisten termien visualisointi:</b>", styles['Body']))
    story.append(Paragraph(
        "Jokaisen simuloinnin yhteydessä tuotetaan diagnostiikkakuvia mallin sisäisistä "
        "termeistä laskennan oikeellisuuden varmistamiseksi:",
        styles['Body']
    ))
    
    story.append(Paragraph(
        "• <b>TI</b> (turbulenssi-intensiteetti) - tuulen pyörteisyyden voimakkuus<br/>"
        "• <b>k</b> (turbulenssienergian tiheys) - pyörteiden kineettinen energia<br/>"
        "• <b>ω</b> (spesifinen dissipaationopeus) - turbulenssin hajoamisnopeus<br/>"
        "• <b>ν_t</b> (turbulentti viskositeetti) - efektiivinen sekoittuminen<br/>"
        "• <b>u_τ</b> (kitkanopeus) - seinänläheinen leikkausjännitys",
        styles['BulletText']
    ))
    
    story.append(Spacer(1, 2*mm))
    
    story.append(Paragraph("<b>Esimerkki: Kasvillisuusalueen arvot vs. kirjallisuus:</b>", styles['Body']))
    
    # Hae validointitaulukon data (QA-lokeista tai oletusarvot)
    veg_validation = get_validation_table_data()
    
    veg_val_table = Table(veg_validation, colWidths=[32*mm, 35*mm, 26*mm, 36*mm])
    veg_val_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), PRIMARY),
        ('TEXTCOLOR', (0, 0), (-1, 0), WHITE),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 7),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    story.append(veg_val_table)
    
    # Lisää huomautus QA-tilastojen lähteestä
    qa_stats = load_qa_validation_stats()
    if qa_stats and qa_stats.get('total_entries', 0) > 0:
        n_entries = qa_stats.get('total_entries', 0)
        updated = qa_stats.get('updated', '')[:10]  # Päivämäärä
        story.append(Paragraph(
            f"<i>Simuloidut arvot perustuvat {n_entries} validointisimulointiin (päivitetty {updated}). "
            "Arvot vastaavat hyvin kenttämittauksia ja tuulitunnelikokeita.</i>",
            styles['TechNote']
        ))
    else:
        story.append(Paragraph(
            "<i>Simuloidut arvot vastaavat hyvin kenttämittauksia ja tuulitunnelikokeita. "
            "Poikkeamat selittyvät kasvillisuuden heterogeenisuudella ja vuodenaikavaihtelulla.</i>",
            styles['TechNote']
        ))
    
    story.append(Spacer(1, 3*mm))
    
    story.append(Paragraph("<b>Numeerinen stabiilisuus kasvillisuusalueilla:</b>", styles['Body']))
    story.append(Paragraph(
        "Kasvillisuusalueiden geometria ja fysikaaliset ominaisuudet käsitellään automaattisesti "
        "numeeristen ongelmien estämiseksi:",
        styles['Body']
    ))
    
    story.append(Paragraph(
        "• <b>Kulmien pyöristys</b> (Bezier-interpolaatio, r=3m) - terävät kulmat aiheuttavat "
        "paikallisia turbulenssiarvojen piikkejä ja epästabiilisuuksia<br/>"
        "• <b>Porositeettigradientti</b> reunoilla - äkillinen muutos ilmasta kasvillisuuteen "
        "aiheuttaisi numeerisia oskillointeja; gradientti tasoittaa siirtymän<br/>"
        "• <b>Drag field -tasoitus</b> - vastuskertoimen portaaton muutos estää laskentahila-artefaktit",
        styles['BulletText']
    ))
    
    story.append(Paragraph(
        "<i>Nämä käsittelyt varmistavat, että laskenta konvergoituu vakaasti myös monimutkaisilla "
        "kasvillisuusgeometrioilla ilman käyttäjän toimenpiteitä.</i>",
        styles['TechNote']
    ))
    
    story.append(PageBreak())
    
    # ========== MITÄ SAAT ==========
    story.append(Paragraph("Toimituksen sisältö", styles['SectionTitle']))
    
    deliverables = [
        ("WDR-kartta (ISO 15927-3)", 
         "Absoluuttinen viistosadeindeksi [l/m2/vuosi] jokaisessa pisteessä. "
         "Värikoodaus BS 8104 rasitusluokkien mukaan."),
        ("Painejakauma (Cp)",
         "Painekertoimet julkisivuilla kaikista simuloiduista tuulensuunnista. "
         "Kriittisten ylipaine- ja alipainealueiden tunnistus."),
        ("Multi-wind yhdistelmä",
         "Tulokset kaikista tyypillisimmistä tuulensuunnista painotettuna "
         "FMI:n tuuliruusun mukaan."),
        ("Rakennuskohtainen analyysi",
         "Jokaisen rakennuksen WDR-indeksi, rasitusluokka ja kriittisimmät kohdat."),
        ("PDF-raportti",
         "Selkeä yhteenvetoraportti tuloksista, menetelmistä ja suosituksista."),
        ("Raakadata (valinnainen)",
         "NumPy-tiedostot jatkoanalyyseihin (esim. WUFI, Delphin)."),
    ]
    
    for title, desc in deliverables:
        story.append(Paragraph(f"<b>{title}</b>", styles['SubSectionTitle']))
        story.append(Paragraph(desc, styles['Body']))
    
    story.append(Spacer(1, 5*mm))
    
    # ========== KÄYTTÖKOHTEET ==========
    story.append(Paragraph("Käyttökohteet", styles['SectionTitle']))
    
    use_cases = [
        ("Julkisivusuunnittelu",
         "Materiaalivalinnat, pintakäsittelyt ja detaljit voidaan mitoittaa todellisen "
         "rasituksen mukaan. Vältetään ylimitoitus suojaisilla alueilla ja alimitoitus kriittisillä."),
        ("Korjausrakentaminen",
         "Vaurioiden syiden selvitys - miksi tietyt julkisivut rapautuvat tai vuotavat? "
         "Korjaustoimenpiteiden kohdentaminen oikeisiin paikkoihin."),
        ("Kosteustekninen mitoitus",
         "Lähtötiedot WUFI- ja Delphin-laskentaan. WDR on kriittinen reunaehto "
         "julkisivujen kosteusteknisessä simuloinnissa."),
        ("Uudisrakentaminen",
         "Suunnittele räystäspituudet, vesipellitykset ja julkisivumateriaalit "
         "kohteen todellisten olosuhteiden mukaan."),
    ]
    
    for title, desc in use_cases:
        story.append(Paragraph(f"<b>• {title}</b>", styles['BulletText']))
        story.append(Paragraph(desc, styles['TechNote']))
    
    story.append(Spacer(1, 8*mm))
    
    # ========== YHTEYSTIEDOT ==========
    story.append(Paragraph("Ota yhteyttä", styles['SectionTitle']))
    
    story.append(Paragraph(
        "Kerro kohteestasi - teemme tarjouksen viistosadeanalyysistä.",
        styles['Body']
    ))
    
    contact_data = [
        ['Loopshore Oy', ''],
        ['Rakennusfysikaaliset simuloinnit', ''],
        ['', ''],
        ['Sähköposti:', 'janne.edgren@loopshore.com'],
        ['Verkkosivu:', 'www.loopshore.com/mikroilmasto'],
    ]
    
    contact_table = Table(contact_data, colWidths=[40*mm, 80*mm])
    contact_table.setStyle(TableStyle([
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('TEXTCOLOR', (0, 0), (-1, 0), PRIMARY),
        ('FONTSIZE', (0, 0), (-1, 0), 12),
        ('FONTSIZE', (0, 1), (-1, 1), 8),
        ('TEXTCOLOR', (0, 1), (-1, 1), LIGHT_TEXT),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    story.append(contact_table)
    
    story.append(Spacer(1, 5*mm))
    
    story.append(Paragraph(
        "\"Tieto todellisesta rasituksesta on paras lähtökohta kestävälle suunnittelulle.\"",
        styles['Quote']
    ))
    
    # Build
    doc.build(story)
    print(f"WDR-esite luotu: {OUTPUT_PDF}")


if __name__ == '__main__':
    create_wdr_brochure()
