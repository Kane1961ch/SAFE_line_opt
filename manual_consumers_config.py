# -*- coding: utf-8 -*-
"""
==============================================================================
CONFIGURAÇÃO DE CONSUMIDORES — MODO MANUAL
Arquivo: manual_consumers_config.py
==============================================================================

NOMES DE ZONAS DE HIDRANTE
--------------------------
Os nomes em hydrant_zones devem ser EXATAMENTE os da aba Hydrants do Excel.

  Módulos  : M-01 M-03 M-05 M-05B M-06 M-08 M-09 M-10A M-10B M-10C
             M-11 M-12 M-13 M-13B M-14 M-15 M-15B M-16 M-16B M-17
  Gerais   : Boatswains  Forecastle  Main deck  Accomodation
             Engine_room  Helideck  Poop_deck  FW_pumps  Lifeboats

ZONAS COMPARTILHADAS
--------------------
Zonas como "Main deck" e "M-09" aparecem em múltiplas linhas (cobertura
de área). O script divide automaticamente a quantidade de cada zona pelo
número de linhas que a reclamam — o total permanece 286, igual ao DIRETO.

MAPEAMENTO APLICADO (nome original → nome Excel)
-------------------------------------------------
  "Boatswain"      → "Boatswains"
  "Main Deck"      → "Main deck"
  "Main Deck AFT"  → "Main deck"     (sem zona AFT separada)
  "M-10"           → "M-10A"         (genérico → M-10A)
  "Accommodations" → "Accomodation"  (grafia do Excel)
  "Engine Room"    → "Engine_room"
  "Poop Deck"      → "Poop_deck"
  "FW Pumps"       → "FW_pumps"
  "Lifeboat"       → "Lifeboats"
  "SV Platform"    → removido        (não existe na aba Hydrants)
==============================================================================
"""

PLATAFORMA         = 'MARLIM'
MANUAL_WATER_LINES = 12

MANUAL_CONSUMERS = {

    'L1': {
        'modules':             [],
        'coamings':            [],
        'hydrant_zones':       ['Boatswains', 'Forecastle', 'Main deck',
                                'M-01', 'M-03', 'M-06', 'M-08'],
        'monitors_main_deck':  1,
        'monitors_offloading': 1,
        'monitors_helideck':   0,
        'water_position':      276.0,
    },

    'L2': {
        'modules':             [],
        'coamings':            [],
        'hydrant_zones':       ['Boatswains', 'Forecastle', 'Main deck',
                                'M-01', 'M-03', 'M-06', 'M-08'],
        'monitors_main_deck':  1,
        'monitors_offloading': 1,
        'monitors_helideck':   0,
        'water_position':      255.0,
    },

    'L3': {
        'modules':             ['M-03'],
        'coamings':            ['N1-101C'],
        'hydrant_zones':       ['Main deck', 'M-05', 'M-05B', 'M-10B', 'M-10C'],
        'monitors_main_deck':  1,
        'monitors_offloading': 0,
        'monitors_helideck':   0,
        'water_position':      235.0,
    },

    'L4': {
        'modules':             [],
        'coamings':            ['N1-101A', 'N1-101D'],
        # 'M-10' original → 'M-10A' (zona genérica mapeada para M-10A)
        'hydrant_zones':       ['Main deck', 'M-05', 'M-05B', 'M-09', 'M-10A'],
        'monitors_main_deck':  1,
        'monitors_offloading': 0,
        'monitors_helideck':   0,
        'water_position':      210.0,
    },

    'L5': {
        'modules':             ['M-01'],
        'coamings':            [],
        'hydrant_zones':       ['M-09', 'Main deck', 'M-10A', 'M-16B'],
        'monitors_main_deck':  1,
        'monitors_offloading': 0,
        'monitors_helideck':   0,
        'water_position':      185.0,
    },

    'L6': {
        'modules':             ['M-05', 'M-10C'],
        'coamings':            [],
        'hydrant_zones':       ['M-09', 'M-10A', 'M-16B', 'Main deck'],
        'monitors_main_deck':  1,
        'monitors_offloading': 0,
        'monitors_helideck':   0,
        'water_position':      163.0,
    },

    'L7': {
        'modules':             ['M-08'],
        'coamings':            ['N1-101B'],
        'hydrant_zones':       ['M-09', 'Main deck', 'M-11', 'M-12', 'M-14', 'M-15'],
        'monitors_main_deck':  1,
        'monitors_offloading': 0,
        'monitors_helideck':   0,
        'water_position':      130.0,
    },

    'L8': {
        'modules':             ['M-05B', 'M-13B'],
        'coamings':            ['N1-101E'],
        # 'SV Platform' removido — zona não existe na aba Hydrants do Excel
        'hydrant_zones':       ['M-09', 'M-11', 'M-12', 'M-14', 'M-15', 'Main deck'],
        'monitors_main_deck':  1,
        'monitors_offloading': 0,
        'monitors_helideck':   0,
        'water_position':      105.0,
    },

    'L9': {
        'modules':             ['M-06', 'M-13'],
        'coamings':            ['N1-101G', 'N1-101J', 'N1-101P'],
        'hydrant_zones':       ['M-09', 'M-13', 'M-13B', 'M-15B', 'M-16', 'M-17',
                                'Main deck'],
        'monitors_main_deck':  1,
        'monitors_offloading': 0,
        'monitors_helideck':   0,
        'water_position':      80.0,
    },

    'L10': {
        'modules':             ['M-09', 'SDV'],
        'coamings':            ['N1-101F'],
        'hydrant_zones':       ['M-09', 'M-13', 'M-13B', 'M-15B', 'M-16', 'M-17',
                                'Main deck'],
        'monitors_main_deck':  1,
        'monitors_offloading': 0,
        'monitors_helideck':   1,
        'water_position':      56.0,
    },

    'L11': {
        'modules':             ['M-14'],
        'coamings':            ['N1-101K', 'N1-101L'],
        'hydrant_zones':       ['Accomodation', 'Engine_room', 'Helideck',
                                'Main deck', 'Poop_deck', 'FW_pumps', 'Lifeboats'],
        'monitors_main_deck':  1,
        'monitors_offloading': 1,
        'monitors_helideck':   1,
        'water_position':      35.0,
    },

    'L12': {
        'modules':             ['M-10A', 'M-10B', 'M-16B'],
        'coamings':            ['N1-101H', 'N1-101M', 'N1-101N'],
        # 'Main Deck AFT' → 'Main deck' (sem zona AFT separada no Excel)
        'hydrant_zones':       ['Accomodation', 'Engine_room', 'Helideck',
                                'Main deck', 'Poop_deck', 'Lifeboats', 'FW_pumps'],
        'monitors_main_deck':  0,
        'monitors_offloading': 1,
        'monitors_helideck':   1,
        'water_position':      20.0,
    },
}
