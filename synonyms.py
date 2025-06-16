from typing import List
from deep_translator import GoogleTranslator

# 1) Define tu lista base en español (o en tu idioma principal)
BASE_SYNONYMS = [
    "distribuidores de ascensores",
    "revendedores de ascensores",
    "mayoristas de ascensores",
    "fabricantes de ascensores",
    "ascensoristas",
    "proveedores de ascensores",
    "distribuidores de salvaescaleras",
    "proveedores de plataformas elevadoras",
    "distribuidores de elevadores residenciales",
    "distribuidores de elevadores para discapacitados",
    "proveedores de equipos de accesibilidad",
]

# 2) Selecciona los códigos ISO 639-1 de los idiomas que quieras cubrir
TARGET_LANGS = [
    "en","es","fr","de","it","pt","ru",
    "zh-cn","zh-tw","ja","ar","nl",
    "hi","bn","pa","ur","jv","ko",
    "vi","ta","te","mr","tr","sv",
    "no","da","fi","el","he","cs",
    "pl","hu","ro","sk","sl","hr",
    "sr","bg","uk","th","id","ms",
    # …añade más códigos según necesidades
]

def build_query_synonyms(base_list: List[str], target_codes: List[str]) -> List[str]:
    all_syns = set()
    for term in base_list:
        all_syns.add(term.strip().lower())
        for code in target_codes:
            try:
                tr = GoogleTranslator(source='auto', target=code).translate(term)
                all_syns.add(tr.strip().lower())
            except Exception:
                # Si falla la traducción para ese idioma, lo ignoramos
                pass
    # Devolver como lista ordenada (opcional)
    return sorted(all_syns)

# Generar la lista definitiva al importarse el módulo
QUERY_SYNONYMS = build_query_synonyms(BASE_SYNONYMS, TARGET_LANGS)
