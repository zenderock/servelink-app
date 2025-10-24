#!/usr/bin/env python3
import sys
sys.path.insert(0, 'app')

from config import get_settings

settings = get_settings()

print("=== Test de chargement des logos des presets ===\n")

for preset in settings.presets:
    logo = preset.get("logo", "")
    print(f"Preset: {preset.get('name', 'Unknown')}")
    print(f"  Slug: {preset.get('slug', 'N/A')}")
    
    if logo:
        if logo.startswith("<"):
            print(f"  Logo: SVG inline ({len(logo)} caractères)")
        else:
            print(f"  Logo: Référence fichier '{logo}' (NON CHARGÉ)")
    else:
        print(f"  Logo: Aucun")
    print()

print("\n=== Vérification du preset Laravel ===")
laravel_preset = next((p for p in settings.presets if p.get('slug') == 'laravel'), None)
if laravel_preset:
    logo = laravel_preset.get('logo', '')
    if logo.startswith('<?xml') or logo.startswith('<svg'):
        print("✅ Le logo Laravel a été chargé avec succès depuis templates/icons/laravel.svg")
        print(f"   Taille: {len(logo)} caractères")
    else:
        print(f"❌ Le logo Laravel n'a pas été chargé: '{logo}'")
else:
    print("❌ Preset Laravel non trouvé")
