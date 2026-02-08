#!/usr/bin/env python3
"""
Testaa osoitteiden puhdistustoiminnallisuus
"""

import re

def clean_address_for_osm(address: str) -> str:
    """
    Puhdista osoite OpenStreetMap-hakua varten poistamalla huoneistotunnukset.
    """
    # Poista huoneistotunnukset eri muodoissa:
    # 1. Kirjain + välilyönti + numerot: " A 5", " B 12"
    cleaned = re.sub(r'\s+[A-ZÅÄÖ]\s+\d+\b', ' ', address)

    # 2. Kirjain + numerot ilman välilyöntiä: " A5", " B12"
    cleaned = re.sub(r'\s+[A-ZÅÄÖ]\d+\b', ' ', cleaned)

    # 3. Porrastunnukset: " 1A", " 2B" jne.
    cleaned = re.sub(r'\s+\d+[A-ZÅÄÖ]\b', ' ', cleaned)

    # 4. Yksittäinen kirjain: " A", " B" (vain jos ei ole osa kaupungin nimeä)
    cleaned = re.sub(r'\s+[A-ZÅÄÖ]\b(?=\s)', ' ', cleaned)

    # Poista ylimääräiset välilyönnit
    cleaned = ' '.join(cleaned.split())

    return cleaned


# Testitapaukset
test_cases = [
    ("Hämeenkatu 13 A5 Tampere", "Hämeenkatu 13 Tampere"),
    ("Mannerheimintie 5 B 12 Helsinki", "Mannerheimintie 5 Helsinki"),
    ("Kalevankatu 3 1A Turku", "Kalevankatu 3 Turku"),
    ("Keskuskatu 10 Oulu", "Keskuskatu 10 Oulu"),
    ("Iso Roobertinkatu 4 A 1 Helsinki", "Iso Roobertinkatu 4 Helsinki"),
    ("Lönnrotinkatu 27 B 25 Helsinki", "Lönnrotinkatu 27 Helsinki"),
    ("Aleksanterinkatu 15 A Helsinki", "Aleksanterinkatu 15 Helsinki"),
    ("Kauppakatu 5 Jyväskylä", "Kauppakatu 5 Jyväskylä"),
]

print("="*70)
print("OSOITTEIDEN PUHDISTUSTESTI")
print("="*70)

all_passed = True
for original, expected in test_cases:
    result = clean_address_for_osm(original)
    passed = result == expected
    all_passed = all_passed and passed

    status = "✓" if passed else "✗"
    print(f"\n{status} {original}")
    print(f"  Expected: {expected}")
    print(f"  Got:      {result}")
    if not passed:
        print(f"  ERROR: Mismatch!")

print("\n" + "="*70)
if all_passed:
    print("✓ Kaikki testit läpäisty!")
else:
    print("✗ Jotkut testit epäonnistuivat")
print("="*70)
