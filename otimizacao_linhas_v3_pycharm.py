# -*- coding: utf-8 -*-
"""
==============================================================================
OTIMIZAÇÃO DE LINHAS DE PROTEÇÃO CONTRA INCÊNDIO — FPSO/PLATAFORMA
Versão PyCharm / Execução Local  ·  v3.1  ·  Mai/2026
==============================================================================

Todos os dados de entrada (Marlim, Tupi, ou qualquer outra plataforma) são
lidos exclusivamente do arquivo Excel indicado em XLSX_PATH.
O código não contém nenhum dado de plataforma embutido.

ARQUIVOS DO PROJETO
-------------------
  otimizacao_linhas_v3_pycharm.py   — script principal (este arquivo)
  manual_consumers_config.py        — alocação manual de consumidores por linha
  marlim_data_estruturado.xlsx      — dados de entrada Marlim
  tupi_data_estruturado.xlsx        — dados de entrada Tupi (preencher valores reais)

MODOS DE EXECUÇÃO
-----------------
  DIRETO  — Pipeline completo (carga → GA → exportação).
             Saída: resultados/detalhamento_direto_<plataforma>.xlsx

  ETAPAS  — Fases independentes com checkpointing em pickle:
               Etapa 1: Posicionamento das linhas
               Etapa 2: Distribuições de espuma/água
               Etapa 3: Algoritmo Genético
               Etapa 4: Pós-processamento + exportação
             Saída: resultados/detalhamento_etapas_<plataforma>.xlsx

  MANUAL  — Calcula peso/custo/distâncias a partir da alocação definida em
             manual_consumers_config.py, sem GA.
             Saída: resultados/detalhamento_manual_<plataforma>.xlsx

ESTRUTURA DO EXCEL (abas obrigatórias)
---------------------------------------
  Resumo, Modules_Areas, Modules_Demand, Modules_Fuel,
  Modules_Distribution, Coamings_Areas, Coamings_Demand,
  Coamings_Distribution, Hydrants, Water_Monitors,
  Water_Diameters, Foam_Diameters, Parameters

  A aba Parameters deve conter as colunas "parameter" e "value".
  Chaves obrigatórias: veja PARAMETROS_OBRIGATORIOS na Seção 3.

DEPENDÊNCIAS
------------
  pip install deap pathos numpy pandas matplotlib openpyxl
==============================================================================
"""

# ==============================================================================
# SEÇÃO 0 — CONFIGURAÇÃO CENTRAL
# (ajuste apenas este bloco; não é necessário editar mais nada abaixo)
# ==============================================================================

# Caminho para o arquivo Excel da plataforma a simular.
# Marlim → 'marlim_data_estruturado.xlsx'
# Tupi   → 'tupi_data_estruturado.xlsx'
XLSX_PATH = 'marlim_data_estruturado.xlsx'

# Configurações de linhas de água.
# None  → usa o valor definido na aba Parameters do Excel.
# lista → usa esses valores (ex.: [10, 11, 12] compara três configurações).
LINHAS_AGUA_OVERRIDE = None       # Ex.: [12]  ou  [10, 11, 12, 13, 14, 15]

# Modo de execução
MODO_EXECUCAO = 'DIRETO'          # 'DIRETO' | 'ETAPAS' | 'MANUAL'

# Número de sementes do GA por configuração (mais seeds = mais robusto, mais lento)
N_SEEDS_GA = 1

# Tamanho do GA — reduzir para rodar no Streamlit Community Cloud
# PyCharm local : valores padrão abaixo
# Community Cloud: o app Streamlit substitui por valores menores (~150 pop, 25 gen)
GA_CONFIG = {
    'water_pop': 500,   # WaterDistribution: população
    'water_gen': 80,    # WaterDistribution: gerações
    'foam_pop':  500,   # FoamDistribution: população
    'foam_gen':  40,    # FoamDistribution: gerações
    'pos_pop':   300,   # LinesPosition: população
    'pos_gen':   80,    # LinesPosition: gerações
}

# Pastas de saída
PASTA_SAIDA      = 'resultados'
PASTA_CHECKPOINT = 'checkpoints'

# Gráficos
SALVAR_GRAFICOS  = True           # Salva PNGs em PASTA_SAIDA
MOSTRAR_GRAFICOS = False          # plt.show() interativo

# Parâmetros de pressão (análise de casos críticos — Seção 11)
PUMP_X_POSITION       = 0.0
PRESSAO_BICO_MONITOR  = 7.0      # bar
PRESSAO_BICO_HIDRANTE = 4.0      # bar
ELEVACAO_M_03         = 25.0     # m
ELEVACAO_OFFLOADING   = 15.0     # m
ELEVACAO_HELIDECK     = 20.0     # m
FITTING_MARGIN        = 1.2      # fator de majoração de comprimento para fittings

# Comprimentos de referência para cálculo de peso/custo
AVG_BRANCH_LENGTH = 10.0         # m — comprimento médio de ramal de equipamento
MAIN_LINE_LENGTH  = 54.0         # m — comprimento de cada trecho de linha principal

# ==============================================================================
# MODO MANUAL — consumidores definidos em manual_consumers_config.py
# Edite aquele arquivo para alterar a alocação sem tocar neste script.
# ==============================================================================
try:
    from manual_consumers_config import MANUAL_CONSUMERS, MANUAL_WATER_LINES
except ImportError:
    MANUAL_CONSUMERS   = {}
    MANUAL_WATER_LINES = 12
    print('⚠️  manual_consumers_config.py não encontrado. '
          'Modo MANUAL não estará disponível.')

# ==============================================================================
# FIM DA CONFIGURAÇÃO CENTRAL
# ==============================================================================


# ==============================================================================
# SEÇÃO 1 — IMPORTAÇÕES
# ==============================================================================
import os
import copy
import time
import pickle
import random
import functools
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')          # backend não-interativo — obrigatório sem display gráfico
import matplotlib.pyplot as plt
import matplotlib.patches as patches

from deap import tools, base, creator, algorithms
from multiprocessing.pool import ThreadPool

warnings.filterwarnings('ignore')

os.makedirs(PASTA_SAIDA,      exist_ok=True)
os.makedirs(PASTA_CHECKPOINT, exist_ok=True)


# ==============================================================================
# SEÇÃO 2 — UTILITÁRIOS INTERNOS
# ==============================================================================

def _salvar_figura(fig, nome: str):
    if SALVAR_GRAFICOS:
        path = os.path.join(PASTA_SAIDA, f'{nome}.png')
        # Não usar bbox_inches='tight': patches fora do xlim/ylim (ex.: typo no Excel
        # com limits max = 24095 em vez de 240.95) expandem o bounding box para
        # dezenas de milhares de pixels e causam ValueError no Agg renderer.
        try:
            fig.savefig(path, dpi=120)
        except ValueError as e:
            print(f'   ⚠️  Não foi possível salvar o gráfico ({e}). '
                  'Verifique se há coordenadas incorretas nos dados do Excel '
                  '(ex.: limits max = 24095 em vez de 240.95 para M-10C).')
        else:
            print(f'   💾 Gráfico: {path}')
    if MOSTRAR_GRAFICOS:
        plt.show()
    plt.close(fig)


def _display(df: pd.DataFrame, titulo: str = ''):
    if titulo:
        print(f'\n{titulo}')
    print(df.to_string(index=False))
    print()


def _salvar_checkpoint(obj, nome: str):
    path = os.path.join(PASTA_CHECKPOINT, f'{nome}.pkl')
    with open(path, 'wb') as f:
        pickle.dump(obj, f)
    print(f'   💾 Checkpoint: {path}')


def _carregar_checkpoint(nome: str):
    path = os.path.join(PASTA_CHECKPOINT, f'{nome}.pkl')
    if not os.path.exists(path):
        raise FileNotFoundError(f'Checkpoint não encontrado: {path}')
    with open(path, 'rb') as f:
        return pickle.load(f)


# ==============================================================================
# SEÇÃO 3 — CARREGAMENTO DE DADOS A PARTIR DO EXCEL
# ==============================================================================

PARAMETROS_OBRIGATORIOS = [
    'platform_info', 'foam_lines_quantity', 'water_lines_quantity',
    'constant_HW', 'velocity_m_s', 'offloading_monitors', 'main_deck_monitors',
    'helideck_monitor', 'foam_offloading_flow', 'foam_main_deck_flow',
    'foam_distance_lines', 'dimensioning_length_m',
    'min_pressure', 'max_pressure', 'convertion_rate',
]


def load_data_from_excel(xlsx_path: str) -> dict:
    """
    Carrega todos os dados de entrada do arquivo Excel estruturado.
    Funciona para qualquer plataforma (Marlim, Tupi, etc.) desde que
    o Excel siga a estrutura de abas documentada no cabeçalho deste arquivo.
    Não há dados de plataforma embutidos no código.
    """
    xlsx_path = Path(xlsx_path)
    if not xlsx_path.exists():
        raise FileNotFoundError(
            f'Arquivo não encontrado: {xlsx_path}\n'
            'Verifique o caminho em XLSX_PATH e se o arquivo está no '
            'diretório de trabalho do PyCharm.')

    print(f'📂 Lendo Excel: {xlsx_path.resolve()}')

    df_parameters           = pd.read_excel(xlsx_path, sheet_name='Parameters')
    df_modules_areas        = pd.read_excel(xlsx_path, sheet_name='Modules_Areas')
    df_modules_demand       = pd.read_excel(xlsx_path, sheet_name='Modules_Demand')
    df_modules_fuel         = pd.read_excel(xlsx_path, sheet_name='Modules_Fuel')
    df_modules_distribution = pd.read_excel(xlsx_path, sheet_name='Modules_Distribution')
    df_coamings_areas       = pd.read_excel(xlsx_path, sheet_name='Coamings_Areas')
    df_coamings_demand      = pd.read_excel(xlsx_path, sheet_name='Coamings_Demand')
    df_coamings_distribution= pd.read_excel(xlsx_path, sheet_name='Coamings_Distribution')
    df_hydrants             = pd.read_excel(xlsx_path, sheet_name='Hydrants')
    df_water_monitors       = pd.read_excel(xlsx_path, sheet_name='Water_Monitors')
    df_water_diameters      = pd.read_excel(xlsx_path, sheet_name='Water_Diameters')
    df_foam_diameters       = pd.read_excel(xlsx_path, sheet_name='Foam_Diameters')

    # ---- parâmetros escalares -----------------------------------------------
    params = dict(zip(
        df_parameters['parameter'].astype(str).str.strip(),
        df_parameters['value']))

    faltando = [k for k in PARAMETROS_OBRIGATORIOS if k not in params]
    if faltando:
        raise KeyError(f'Parâmetros ausentes na aba Parameters: {faltando}')

    raw_pi = params['platform_info']
    if isinstance(raw_pi, str):
        platform_info = tuple(float(v.strip()) for v in raw_pi.split(','))
    else:
        try:
            df_resumo = pd.read_excel(xlsx_path, sheet_name='Resumo')
            x0 = df_resumo.loc[df_resumo['Item'].str.contains('início X', na=False), 'Valor'].iloc[0]
            x1 = df_resumo.loc[df_resumo['Item'].str.contains('fim X',    na=False), 'Valor'].iloc[0]
            platform_info = (float(x0), float(x1))
        except Exception:
            raise ValueError(
                'Não foi possível ler platform_info. '
                'Use o formato "14.9, 295.85" na aba Parameters.')

    foam_lines_quantity = int(float(params['foam_lines_quantity']))

    raw_wl = params['water_lines_quantity']
    if isinstance(raw_wl, str):
        water_lines_quantity = [
            int(float(v.strip()))
            for v in raw_wl.replace('[', '').replace(']', '').split(',')
            if v.strip()]
    else:
        water_lines_quantity = [int(float(raw_wl))]

    constant_HW           = float(params['constant_HW'])
    velocity_m_s          = float(params['velocity_m_s'])
    offloading_monitors   = int(float(params['offloading_monitors']))
    main_deck_monitors    = int(float(params['main_deck_monitors']))
    helideck_monitor      = int(float(params['helideck_monitor']))
    foam_offloading_flow  = float(params['foam_offloading_flow'])
    foam_main_deck_flow   = float(params['foam_main_deck_flow'])
    foam_distance_lines   = float(params['foam_distance_lines'])
    dimensioning_length_m = float(params['dimensioning_length_m'])
    min_pressure          = float(params['min_pressure'])
    max_pressure          = float(params['max_pressure'])
    convertion_rate       = float(params['convertion_rate'])

    # ---- distribuição dos módulos -------------------------------------------
    modules_distribution = (
        df_modules_distribution
        .drop(columns=['deck_row'], errors='ignore')
        .map(lambda x: None if pd.isna(x) else x)
        .values.tolist()
    )

    # ---- áreas dos módulos --------------------------------------------------
    modules_areas = {
        'modules':    df_modules_areas['modules'].astype(str).tolist(),
        'length (m)': df_modules_areas['length (m)'].astype(float).tolist(),
        'limits':     list(zip(df_modules_areas['limits min'].astype(float),
                               df_modules_areas['limits max'].astype(float))),
        'limits y':   list(zip(df_modules_areas['limits y min'].astype(float),
                               df_modules_areas['limits y max'].astype(float))),
    }
    if 'position' in df_modules_areas.columns:
        modules_areas['position'] = df_modules_areas['position'].astype(float).tolist()

    # ---- módulos com combustível --------------------------------------------
    modules_w_fuel = dict(zip(
        df_modules_fuel['module'].astype(str),
        df_modules_fuel['has_fuel'].astype(bool)))

    # ---- distribuição dos coamings ------------------------------------------
    coamings_distribution = (
        df_coamings_distribution
        .drop(columns=['side_row'], errors='ignore')
        .map(lambda x: None if pd.isna(x) else x)
        .values.tolist()
    )

    # ---- áreas dos coamings -------------------------------------------------
    coamings_areas = {
        'coamings':   df_coamings_areas['coamings'].astype(str).tolist(),
        'shipside':   df_coamings_areas['shipside'].astype(str).tolist(),
        'length (m)': df_coamings_areas['length (m)'].astype(float).tolist(),
        'width (m)':  df_coamings_areas['width (m)'].astype(float).tolist(),
        'area (m2)':  df_coamings_areas['area (m2)'].astype(float).tolist(),
        'limits':     list(zip(df_coamings_areas['limits min'].astype(float),
                               df_coamings_areas['limits max'].astype(float))),
        'position':   df_coamings_areas['position'].astype(float).tolist(),
    }

    # ---- demandas -----------------------------------------------------------
    modules_df_demand  = df_modules_demand.copy()
    coamings_df_demand = df_coamings_demand.copy()

    # ---- hidrantes ----------------------------------------------------------
    hydrants = dict(zip(
        df_hydrants['zone'].astype(str),
        df_hydrants['hydrants_quantity'].astype(int)))

    # ---- monitores e diâmetros ----------------------------------------------
    water_monitors_flow = df_water_monitors.copy()
    water_monitors_flow['water flow (m3/h)'] = (
        water_monitors_flow['water flow (m3/h)'].astype(float))

    water_diameters = df_water_diameters.copy()
    water_diameters['dn(in)']  = water_diameters['dn(in)'].astype(float)
    water_diameters['din(mm)'] = water_diameters['din(mm)'].astype(float)
    water_diameters['weight']  = water_diameters['weight'].astype(float)

    foam_diameters = df_foam_diameters.copy()
    foam_diameters['dn(in)']  = foam_diameters['dn(in)'].astype(float)
    foam_diameters['din(mm)'] = foam_diameters['din(mm)'].astype(float)

    print(f'   ✅ Dados carregados — '
          f'{len(modules_areas["modules"])} módulos, '
          f'{len(coamings_areas["coamings"])} coamings')
    print(f'   Platform: {platform_info}  |  '
          f'Configs de linhas: {water_lines_quantity}')

    return {
        'platform_info':         platform_info,
        'foam_lines_quantity':   foam_lines_quantity,
        'water_lines_quantity':  water_lines_quantity,
        'modules_distribution':  modules_distribution,
        'modules_areas':         modules_areas,
        'modules_w_fuel':        modules_w_fuel,
        'coamings_distribution': coamings_distribution,
        'coamings_areas':        coamings_areas,
        'modules_df_demand':     modules_df_demand,
        'coamings_df_demand':    coamings_df_demand,
        'hydrants':              hydrants,
        'constant_HW':           constant_HW,
        'velocity_m_s':          velocity_m_s,
        'water_monitors_flow':   water_monitors_flow,
        'water_diameters':       water_diameters,
        'foam_diameters':        foam_diameters,
        'offloading_monitors':   offloading_monitors,
        'main_deck_monitors':    main_deck_monitors,
        'helideck_monitor':      helideck_monitor,
        'foam_offloading_flow':  foam_offloading_flow,
        'foam_main_deck_flow':   foam_main_deck_flow,
        'foam_distance_lines':   foam_distance_lines,
        'dimensioning_length_m': dimensioning_length_m,
        'min_pressure':          min_pressure,
        'max_pressure':          max_pressure,
        'convertion_rate':       convertion_rate,
    }


# ==============================================================================
# SEÇÃO 4 — POSICIONAMENTO DE LINHAS (LinesPosition)
# ==============================================================================

class LinesPosition:

    @staticmethod
    def set_module_positions(module_areas: dict, offset: float = 15.0) -> dict:
        module_areas['position'] = [
            max(0.0, float(np.round(lim[0] - offset, 2)))
            for lim in module_areas['limits']]
        return module_areas

    @staticmethod
    def get_lines_position(total_length, foam_lines_quantity, water_lines_quantity,
                           modules_matrix, modules_areas, modules_w_fuel,
                           foam_matrix, foam_areas, foam_distance_lines=10):
        espaco = total_length[1] - total_length[0]
        if (water_lines_quantity - 1) * 10.0 > espaco:
            print(f'   ❌ Inviável: {water_lines_quantity} linhas × 10 m > {espaco:.1f} m')
            return None, None

        foam_areas = LinesPosition._calc_limits(foam_areas, foam_matrix, total_length)
        risk_zone, risk_limit = LinesPosition._risk_zone(
            modules_matrix, modules_w_fuel, modules_areas, total_length)

        if risk_zone == 'Stern side':
            stern = water_lines_quantity // 2 + 1
            bow   = water_lines_quantity - stern
        else:
            bow   = water_lines_quantity // 2 + 1
            stern = water_lines_quantity - bow

        foam_pos_ref = LinesPosition._initial_pos(
            foam_lines_quantity, foam_areas, foam_matrix, foam_distance_lines)

        plat = {'total_length': total_length, 'risk_limit': risk_limit,
                'risk_zone': risk_zone, 'bow_num_lines': bow,
                'stern_num_lines': stern, 'water_lines': water_lines_quantity}
        allowed = {'min': min(foam_areas['length (m)']) / 2,
                   'max': min(foam_areas['length (m)'])}

        random.seed(35)
        water_pos = LinesPosition._run_ga(plat, modules_areas, modules_matrix, allowed)

        for i in range(len(water_pos) - 1):
            if water_pos[i + 1] - water_pos[i] < 9.9:
                print('   ❌ GA não encontrou solução com 10 m mínimos entre linhas.')
                return None, None

        foam_pos  = foam_pos_ref[::-1]
        water_pos = water_pos[::-1]
        fig = LinesPosition._plot(foam_pos, water_pos, plat, foam_areas, foam_matrix, modules_areas)
        _salvar_figura(fig, f'layout_{water_lines_quantity}L')
        return foam_pos, water_pos

    # ---- helpers privados ----------------------------------------------------

    @staticmethod
    def _calc_limits(foam_areas, coamings_matrix, total_length):
        n = len(foam_areas['coamings'])
        foam_areas['limits']   = [0] * n
        foam_areas['position'] = [0] * n
        for row in coamings_matrix:
            last = total_length[1]
            for key in row[::-1]:
                idx  = foam_areas['coamings'].index(key)
                lng  = foam_areas['length (m)'][idx]
                lim  = (float(np.round(last - lng, 2)), float(np.round(last, 2)))
                last -= lng
                foam_areas['limits'][idx]   = lim
                foam_areas['position'][idx] = max(0.0, float(np.round(lim[0] - 15.0, 2)))
        return foam_areas

    @staticmethod
    def _risk_zone(modules_matrix, modules_w_fuel, module_areas, total_length):
        mid = len(modules_matrix[0]) / 2
        bow = stern = risk_limit = 0
        for mod, (xi, xs) in zip(module_areas['modules'], module_areas['limits']):
            if mod in modules_matrix[-1] and xs >= sum(total_length) / 2:
                risk_limit = xi
        for row in modules_matrix:
            for j, mod in enumerate(row):
                if mod and mod in modules_w_fuel:
                    if j < mid: bow   += 1
                    else:       stern += 1
        return ('Bow side' if bow > stern else 'Stern side'), risk_limit

    @staticmethod
    def _initial_pos(n_lines, foam_areas, foam_matrix, dist=10.0):
        fm  = foam_matrix[-1][::-1]
        pos = []
        for i in range(n_lines):
            if i < len(fm):
                idx = foam_areas['coamings'].index(fm[i])
                pos.append(foam_areas['limits'][idx][1] - dist)
            elif i == len(fm):
                idx = foam_areas['coamings'].index(fm[-1])
                pos.append(foam_areas['limits'][idx][0] + dist)
            else:
                mid = len(fm) // 2 + 1
                pos.append((pos[mid] + pos[mid + 1]) / 2)
        return sorted(pos)

    @staticmethod
    def _run_ga(plat, modules_areas, modules_matrix, allowed):
        for name in ['FitnessMin', 'Individual']:
            if name in creator.__dict__: delattr(creator, name)
        creator.create('FitnessMin', base.Fitness, weights=(-1.0,))
        creator.create('Individual', list, fitness=creator.FitnessMin)
        tb = base.Toolbox()
        n  = plat['water_lines']
        for i in range(n):
            tb.register(f'wp_{i}', random.uniform,
                        plat['total_length'][0], plat['total_length'][1])
        tb.register('individual', tools.initCycle, creator.Individual,
                    [getattr(tb, f'wp_{i}') for i in range(n)], n=1)
        tb.register('population', tools.initRepeat, list, tb.individual)
        tb.register('evaluate', LinesPosition._eval, plat, allowed, modules_areas, modules_matrix)
        tb.register('mate',   tools.cxTwoPoint)
        tb.register('mutate', LinesPosition._mutate, plat)
        tb.register('select', tools.selTournament, tournsize=3)
        pop = tb.population(n=GA_CONFIG['pos_pop'])
        hof = tools.HallOfFame(1)
        algorithms.eaSimple(pop, tb, cxpb=0.9, mutpb=0.3,
                            ngen=GA_CONFIG['pos_gen'], halloffame=hof, verbose=False)
        return sorted([float(np.round(p, 2)) for p in hof[0]])

    @staticmethod
    def _eval(plat, allowed, modules_areas, modules_matrix, individual):
        pen  = 0
        mlen = [modules_areas['length (m)'][modules_areas['modules'].index(modules_matrix[-1][i])]
                for i in [0, -1]]
        fw = sorted([float(np.round(p, 2)) for p in individual])
        lo, hi = plat['total_length']
        for p in fw:
            if not (lo <= p <= hi): pen += hi
        if not (lo + mlen[0]/3 <= fw[0]  <= lo + mlen[0]*7/8):    pen += 5 * fw[0]
        if not (hi - mlen[-1]*7/8 <= fw[-1] <= hi - mlen[-1]/3):  pen += fw[-1]
        for i in range(len(fw) - 1):
            d = fw[i+1] - fw[i]
            if d < 10.0: pen += 10000 * (10.0 - d)
            if not (allowed['min'] < d < allowed['max']): pen += 6 * allowed['max']
        rl = plat['risk_limit']
        if plat['stern_num_lines'] > plat['bow_num_lines']:
            r = sum(1 for p in fw if p >= rl); l = len(fw) - r
        else:
            l = sum(1 for p in fw if p <= rl); r = len(fw) - l
        pen += abs(l - plat['bow_num_lines'])   * 30
        pen += abs(r - plat['stern_num_lines']) * 30
        return (pen,)

    @staticmethod
    def _mutate(plat, individual, indpb=0.1, mu=0):
        sigma = plat['total_length'][1] * 0.05
        for i in range(plat['water_lines']):
            if random.random() < indpb:
                individual[i] = max(0, min(
                    individual[i] + random.gauss(mu, sigma), plat['total_length'][1]))
        return (individual,)

    @staticmethod
    def _plot(foam_pos, water_pos, plat, foam_areas, foam_matrix, module_area):
        mh       = 25
        y_min_up = min(y for y, _ in module_area['limits y'])
        y_max_up = max(y for _, y in module_area['limits y'])
        fig, ax  = plt.subplots(figsize=(18, 9))

        cur_y = y_min_up - 2.75 * mh
        for row in foam_matrix[::-1]:
            for c in row:
                ic  = foam_areas['coamings'].index(c)
                lng = foam_areas['length (m)'][ic]
                xi, xs = foam_areas['limits'][ic]
                ax.add_patch(patches.Rectangle((xi, cur_y), lng, mh,
                    edgecolor='navy', facecolor='skyblue', alpha=0.7, lw=2))
                ax.text((xi+xs)/2, cur_y+mh/2, f'{c}\n({lng}m)',
                    ha='center', va='center', fontsize=11, color='navy', weight='bold')
            cur_y += mh

        yl_min = y_min_up - 2.75*mh - 3
        yl_max = y_min_up - 0.75*mh + 3
        for i, p in enumerate(foam_pos):
            ax.vlines(p, yl_min, yl_max, color='blue', lw=3,
                      label='Foam Lines' if i == 0 else '')
            ax.text(p, yl_max+1, f'L{i+1}\n{p:.1f}m', ha='center', va='bottom',
                    fontsize=12, color='blue', fontweight='bold',
                    bbox=dict(boxstyle='round,pad=0.3', facecolor='lightblue', alpha=0.7))

        for im, mod in enumerate(module_area['modules']):
            lng    = module_area['length (m)'][im]
            xi, xs = module_area['limits'][im]
            yi, ys = module_area['limits y'][im]
            ax.add_patch(patches.Rectangle((xi, yi), lng, abs(yi-ys),
                edgecolor='darkred', facecolor='salmon', alpha=0.7, lw=2))
            ax.text((xi+xs)/2, (yi+ys)/2, f'{mod}\n({lng}m)',
                ha='center', va='center', fontsize=11, color='darkred', weight='bold')

        for i, p in enumerate(water_pos):
            ax.vlines(p, y_min_up-3, y_max_up+3, color='red', lw=3,
                      label='Firewater lines' if i == 0 else '')
            ax.text(p, y_max_up+4, f'L{i+1}\n{p:.1f}m', ha='center', va='bottom',
                    fontsize=12, color='red', fontweight='bold',
                    bbox=dict(boxstyle='round,pad=0.3', facecolor='lightcoral', alpha=0.7))

        ax.vlines(plat['risk_limit'], yl_min, y_max_up+4, color='dimgray',
                  linestyle='--', lw=2.5, label=f'Risk Limit ({plat["risk_limit"]:.1f} m)')
        lo, hi = plat['total_length']
        mx = (hi-lo)*0.08
        ax.set_xlim(lo-mx, hi+mx)
        ax.set_ylim(y_min_up-3.2*mh, y_max_up+2*mh)
        ax.set_xlabel('Platform Length (m)', fontsize=16, fontweight='bold', labelpad=15)
        ax.set_ylabel('Platform Cross-Section', fontsize=16, fontweight='bold', labelpad=15)
        ax.set_yticks([])
        ax.set_title('Location of Foam and Firewater Protection Lines',
                     fontsize=20, pad=30, fontweight='bold')
        ax.legend(loc='upper right', fontsize=13, framealpha=0.95, edgecolor='black', fancybox=True)
        ax.grid(True, axis='x', linestyle=':', alpha=0.4, linewidth=1.5)
        plt.subplots_adjust(left=0.1, right=0.95, top=0.92, bottom=0.1)
        return fig


# ==============================================================================
# SEÇÃO 5 — CÁLCULO HIDRÁULICO (Hazen-Williams)
# ==============================================================================

def find_diameters(pipe_diameter, flow_m3_h, flow_L_min, constant_HW,
                   dimensioning_length_m, min_pressure, max_pressure,
                   max_velocity, penalities, mono_range):
    Q_m3   = flow_m3_h[:, np.newaxis]
    Q_lmin = flow_L_min[:, np.newaxis]
    D_mm   = pipe_diameter['din(mm)'].values[np.newaxis, :]
    DN_in  = pipe_diameter['dn(in)'].values

    pdrop = ((6.05e5 * Q_lmin**1.85) / (constant_HW**1.85 * D_mm**4.87)) * dimensioning_length_m
    vel   = (4 * Q_m3) / (np.pi * (D_mm/1000)**2) / 3600

    diameters = []
    hyd_pen = mono_pen = 0

    for i in range(len(flow_m3_h)):
        vp  = (pdrop[i] >= min_pressure) & (pdrop[i] <= max_pressure)
        vv  = vel[i] <= max_velocity
        opt = np.where(vp & vv)[0]
        if opt.size:
            idx = opt[0]
        else:
            vpi = np.where(vp)[0]
            if vpi.size:
                idx = vpi[np.argmin(np.abs(vel[i, vpi] - max_velocity))]
            else:
                idx = np.argmin(np.minimum(np.abs(pdrop[i]-min_pressure),
                                           np.abs(pdrop[i]-max_pressure)))
            hyd_pen += penalities[0] * DN_in[idx]
        diameters.append(DN_in[idx])

    diff = np.diff(diameters)
    mono = np.sum(np.abs(diff[diff < 0]))
    if not (0 <= mono <= mono_range):
        mono_pen = penalities[1]*np.std(diameters) + (penalities[2]*mono)**2
    return hyd_pen, mono_pen, mono, diameters


def calc_hazen_williams(flow_m3h, diam_in, length_m, water_diameters,
                        hw_c=150, fitting_margin=FITTING_MARGIN):
    if not (length_m and diam_in and flow_m3h): return 0.0
    try:
        diam_mm = water_diameters.loc[water_diameters['dn(in)']==diam_in, 'din(mm)'].iloc[0]
    except Exception:
        diam_mm = diam_in * 25.4
    return ((6.05e5 * (flow_m3h/0.06)**1.85) /
            (hw_c**1.85 * diam_mm**4.87)) * length_m * fitting_margin


# ==============================================================================
# SEÇÃO 6 — DISTRIBUIÇÃO DE ESPUMA (FoamDistribution)
# ==============================================================================

class FoamDistribution:

    @staticmethod
    def get_foam_distribution(foam_df, foam_areas, foam_lines_position,
                              foam_lines_quantity, foam_offloading_monitors,
                              foam_offloading_flow, foam_main_deck_monitors,
                              foam_main_deck_flow, df_diameters, constant_HW,
                              dimensioning_length_m, velocity_m_s,
                              min_pressure, max_pressure, convertion_rate):
        consumers = [[] for _ in range(foam_lines_quantity)]
        demand    = np.zeros(foam_lines_quantity)

        for idx, coam in enumerate(foam_areas['coamings']):
            xi, _ = foam_areas['limits'][idx]
            lines  = [i for i, p in enumerate(foam_lines_position) if p <= xi]
            vl     = lines[0] if lines else foam_lines_quantity - 1
            consumers[vl].append(coam)
            demand[vl] += foam_df.loc[
                foam_df['coamings'] == coam,
                'foam concentrate + hydraulic imbalance (m3/h)'].iloc[0]

        dist_off = [foam_offloading_monitors//2
                    if i in [0, foam_lines_quantity-1] else 0
                    for i in range(foam_lines_quantity)]
        demand  += np.array([dist_off[i]*foam_offloading_flow for i in range(foam_lines_quantity)])

        random.seed(42)
        dist_main, demand_line = FoamDistribution._run_ga(
            demand, foam_main_deck_flow, foam_main_deck_monitors,
            foam_lines_quantity, df_diameters, constant_HW, dimensioning_length_m,
            velocity_m_s, min_pressure, max_pressure, convertion_rate)

        return {
            'lines':                 [f'L{i+1}' for i in range(foam_lines_quantity)],
            'monitors (main deck)':  dist_main,
            'monitors (offloading)': dist_off,
            'consumer coamings':     consumers,
            'Ql (L/min)':            [demand_line[i]/convertion_rate for i in range(foam_lines_quantity)],
            'Ql (m3/h)':             demand_line,
        }

    @staticmethod
    def _run_ga(flow_lines, main_flow, main_monitors, n_lines,
                df_diam, hw, dim_len, vel, pmin, pmax, cvt):
        for name in ['FitnessMin', 'Individual']:
            if name in creator.__dict__: delattr(creator, name)
        creator.create('FitnessMin', base.Fitness, weights=(-1.0,))
        creator.create('Individual', list, fitness=creator.FitnessMin)
        tb = base.Toolbox()
        tb.register('attr', random.randint, 1, int(main_monitors//4))
        tb.register('individual', tools.initRepeat, creator.Individual, tb.attr, n=n_lines)
        tb.register('population', tools.initRepeat, list, tb.individual)
        tb.register('evaluate', FoamDistribution._eval,
                    flow_lines=flow_lines, main_flow=main_flow,
                    n_monitors=main_monitors, df_diam=df_diam,
                    hw=hw, dim_len=dim_len, vel=vel, pmin=pmin, pmax=pmax, cvt=cvt)
        tb.register('mate',   tools.cxTwoPoint)
        tb.register('mutate', tools.mutUniformInt, low=1, up=int(main_monitors//4), indpb=0.1)
        tb.register('select', tools.selTournament, tournsize=5)
        pop = tb.population(n=GA_CONFIG['foam_pop'])
        hof = tools.HallOfFame(1)
        algorithms.eaSimple(pop, tb, cxpb=0.85, mutpb=0.15,
                            ngen=GA_CONFIG['foam_gen'], halloffame=hof, verbose=False)
        mon = np.array(hof[0])
        return mon.tolist(), mon * main_flow + np.array(flow_lines)

    @staticmethod
    def _eval(individual, flow_lines, main_flow, n_monitors,
              df_diam, hw, dim_len, vel, pmin, pmax, cvt):
        pen = 0
        mon = np.array(individual)
        dmd = mon * main_flow + np.array(flow_lines)
        if mon[0] < 2 or mon[-1] < 2: pen += 20
        if sum(mon) != n_monitors: pen += 30*abs(sum(mon)-n_monitors)
        hp, mp, _, _ = find_diameters(df_diam, dmd, dmd/cvt, hw, dim_len, pmin, pmax, vel,
                                      [1000, 0, 10], 0.5)
        return (pen + mp + hp,)


# ==============================================================================
# SEÇÃO 7 — DISTRIBUIÇÃO DE MONITORES DE ÁGUA (MonitorDistribution)
# ==============================================================================

class MonitorDistribution:

    @staticmethod
    def get_monitor_distribution(module_area, modules_w_fuel, n,
                                  water_pos, monitors_flows,
                                  total_monitor_main, total_monitor_offloading,
                                  total_monitor_helideck, hydrants):
        main_per = total_monitor_main // (n - 1)
        off_line  = n - total_monitor_offloading / 2
        heli_line = n - total_monitor_helideck

        dist_main = [main_per if i < n-1 else 0 for i in range(n)]
        dist_off  = [1 if (i < total_monitor_offloading/2 or i >= off_line) else 0 for i in range(n)]
        dist_heli = [total_monitor_helideck//3 if i >= heli_line else 0 for i in range(n)]
        flows_mf  = monitors_flows['water flow (m3/h)'].values

        if isinstance(hydrants, int):
            dist_hyd = [50 if i > heli_line else (hydrants-100)//(n-2) for i in range(n)]
            if sum(dist_hyd) < hydrants:
                dist_hyd[-2] += (hydrants - sum(dist_hyd)) // 2
                dist_hyd[-1] += hydrants - sum(dist_hyd)
            flows = [dist_main[i]*flows_mf[0] + dist_off[i]*flows_mf[1] +
                     dist_heli[i]*flows_mf[2] + dist_hyd[i]*flows_mf[3] for i in range(n)]
            hyd_map = {f'L{i+1}': '-' for i in range(n)}

        elif isinstance(hydrants, dict):
            valid_lines, last_mods = MonitorDistribution._constraints(
                module_area, water_pos, modules_w_fuel)
            hyd_mod    = {k: v for k, v in hydrants.items() if k in modules_w_fuel}
            hyd_nonmod = {k: v for k, v in hydrants.items() if k not in modules_w_fuel}
            dist_hyd, hyd_map, _, valid_lines = MonitorDistribution._hyd_modules(
                module_area, water_pos, n, valid_lines, last_mods, hyd_mod)
            dist_hyd, hyd_map, _ = MonitorDistribution._hyd_nonmodules(
                n, hyd_nonmod, dist_hyd, hyd_map, {f'L{i+1}': [] for i in range(n)})
            flows = [dist_main[i]*flows_mf[0] + dist_off[i]*flows_mf[1] +
                     dist_heli[i]*flows_mf[2] + dist_hyd[i]*flows_mf[3] for i in range(n)]

        return ({'lines': [f'L{i+1}' for i in range(n)],
                 'monitors (main deck)':     dist_main,
                 'monitors (offloading)':    dist_off,
                 'monitors (helideck)':      dist_heli,
                 'hydrants':                 dist_hyd,
                 'minimum waterflow (m3/h)': flows},
                hyd_map,
                valid_lines)

    @staticmethod
    def _constraints(module_area, water_pos, modules_w_fuel):
        last_mods, valid_lines = [], {}
        for idx, mod in enumerate(module_area['modules']):
            if mod in modules_w_fuel and modules_w_fuel[mod]:
                xi = module_area['limits'][idx][0]
                lines = [i+1 for i, p in enumerate(water_pos) if p <= xi]
                if len(lines) <= 1: last_mods.append(mod)
                else:               valid_lines[mod] = lines
        return valid_lines, last_mods

    @staticmethod
    def _hyd_modules(module_area, water_pos, n, valid_lines, last_mods, hydrants):
        line_dist = {k: 0 for k in hydrants}
        min_len   = min(module_area['length (m)'])

        for idx, mod in enumerate(module_area['modules']):
            if mod not in hydrants: continue
            pos  = module_area['position'][idx]
            dist = [abs(p - pos) for p in water_pos]
            im   = dist.index(min(dist))
            if im == 0:
                line_dist[mod] = (im, im+1)
            elif im == n-1:
                line_dist[mod] = (im-2, im-1) if mod in last_mods else (im-1, im)
            else:
                nxt = min(dist[im-1], dist[im+1])
                ni  = dist.index(nxt)
                if water_pos[ni] < module_area['limits'][idx][0] and mod in valid_lines:
                    ni = im-1
                line_dist[mod] = (im, ni)

        darr = [0]*n; zmap = {f'L{i+1}': [] for i in range(n)}; qmap = {f'L{i+1}': [] for i in range(n)}
        for mod, (l1, l2) in line_dist.items():
            idx = module_area['modules'].index(mod)
            lng = module_area['length (m)'][idx]
            qty = hydrants[mod]
            if lng < 2*min_len:
                c1, c2 = qty//2, qty-qty//2
                for li, ci in [(l1,c1),(l2,c2)]:
                    darr[li]+=ci; zmap[f'L{li+1}'].append(f'Hydrant {mod}'); qmap[f'L{li+1}'].append(ci)
            else:
                xi, xs = module_area['limits'][idx]
                in_l = [i for i,p in enumerate(water_pos) if xi<=p<=xs]
                rem = qty; cur = len(in_l)
                for li in in_l:
                    c=rem//cur; darr[li]+=c; zmap[f'L{li+1}'].append(f'Hydrant {mod}'); qmap[f'L{li+1}'].append(c); rem-=c; cur-=1
        return darr, zmap, qmap, valid_lines

    @staticmethod
    def _hyd_nonmodules(n, hydrants, darr, zmap, qmap):
        for key, val in hydrants.items():
            if key in ['Forecastle','Boatswains']:
                darr[0]+=val//2; darr[1]+=val-val//2
                zmap['L1'].append(f'Hydrant {key}'); qmap['L1'].append(val//2)
                zmap['L2'].append(f'Hydrant {key}'); qmap['L2'].append(val-val//2)
            elif key == 'Main deck':
                rem=val; cur=n
                for i in range(n):
                    c=rem//cur; darr[i]+=c; zmap[f'L{i+1}'].append(f'Hydrant {key}'); qmap[f'L{i+1}'].append(c); rem-=c; cur-=1
            else:
                li=n-2; darr[li]+=val//2; darr[li+1]+=val-val//2
                zmap[f'L{li+1}'].append(f'Hydrant {key}'); qmap[f'L{li+1}'].append(val//2)
                zmap[f'L{li+2}'].append(f'Hydrant {key}'); qmap[f'L{li+2}'].append(val-val//2)
        return darr, zmap, qmap


# ==============================================================================
# SEÇÃO 8 — DISTRIBUIÇÃO DE ÁGUA (WaterDistribution + GA)
# ==============================================================================

class GAResultsStore:
    def __init__(self):
        self.configs: list[dict] = []

    def add_config(self, label, n_lines, convergence_data, result_weights, final_metrics=None):
        viable  = [w for w in result_weights if w < np.inf]
        best    = min(viable) if viable else np.inf
        best_s  = result_weights.index(best) if viable else -1
        cfg = {'label': label, 'n_lines': n_lines, 'convergence_data': convergence_data,
               'viable_weights': viable, 'best_weight_kg': best, 'best_seed': best_s}
        if final_metrics: cfg.update(final_metrics)
        self.configs.append(cfg)
        print(f'   📦 Store: "{label}" — {len(viable)} viáveis, '
              f'melhor={best/1000:.3f} ton')

    def summary_table(self) -> pd.DataFrame:
        rows = []
        for cfg in self.configs:
            vw  = cfg['viable_weights']
            row = {'Configuração':    cfg['label'],
                   'N Linhas':        cfg['n_lines'],
                   'Seeds Viáveis':   len(vw),
                   'Melhor Peso (ton)': round(cfg['best_weight_kg']/1000, 3) if vw else np.inf,
                   'Melhor Seed':     cfg['best_seed']+1 if vw else -1}
            for k, rk in [('total_dist',   'Dist Total (km)'),
                           ('total_weight', 'Peso Total (ton)'),
                           ('lines_weight', 'Peso Linhas (ton)'),
                           ('adv_weight',   'Peso Ramais (ton)')]:
                if k in cfg:
                    row[rk] = round(cfg[k]/1000, 3)
            rows.append(row)
        return pd.DataFrame(rows).sort_values('Melhor Peso (ton)').reset_index(drop=True) if rows else pd.DataFrame()


class WaterDistribution:
    HYDRAULIC_PENALTY_WEIGHT    = 1_000_000
    MONOTONICITY_PENALTY_WEIGHT = 100_000
    MONOTONICITY_TOLERANCE      = 0.5

    @staticmethod
    def _create_ind(valid_lines_values):
        return [random.choice(lines) for lines in valid_lines_values]

    @staticmethod
    def _mutate(individual, valid_lines, indpb=0.15):
        for i, lines in enumerate(valid_lines):
            if len(lines) > 1 and random.random() < indpb:
                individual[i] = random.choice(lines)
        return (individual,)

    @staticmethod
    def _build_demand(adv_names, df_adv, df_mod, df_com, lines_init):
        dmd, dia = [], []
        hd_m = 'nominal diameter (in)' in df_mod.columns
        hd_c = 'nominal diameter (in)' in df_com.columns
        for z in adv_names:
            m = df_adv.loc[df_adv['zone']==z, 'minimum waterflow (m3/h)']
            dmd.append(float(m.iloc[0]) if not m.empty else 0.0)
            dm = df_mod.loc[df_mod['zone']==z, 'nominal diameter (in)'] if hd_m else pd.Series(dtype=float)
            dc = df_com.loc[df_com['coamings']==z, 'nominal diameter (in)'] if hd_c else pd.Series(dtype=float)
            dia.append(float(dm.iloc[0]) if not dm.empty else
                       float(dc.iloc[0]) if not dc.empty else 0.0)
        return (np.array(dmd), np.array(dia), np.array(lines_init, dtype=float))

    @staticmethod
    def _line_demand(individual, dmd_arr, lines_base):
        ld = lines_base.copy()
        np.add.at(ld, np.array(individual)-1, dmd_arr)
        return ld

    @staticmethod
    def _mono(diam_line):
        dd = np.diff(np.array(diam_line, dtype=float))
        if not len(dd): return True, 1.0, dd
        return bool(np.all(dd>=0)), int(np.sum(dd>=0))/len(dd), dd

    @staticmethod
    def _branch_weight_kg(individual, adv_pos, lines_pos, diam_weights_arr):
        """Peso (kg) dos ramais — totalmente vetorizado com array kg/m pré-calculado."""
        idx  = np.array(individual) - 1
        dist = np.abs(adv_pos - lines_pos[idx])
        w    = np.where(diam_weights_arr > 0, dist * diam_weights_arr, dist)
        return float(np.sum(w)), float(np.sum(dist))

    @staticmethod
    def _line_weight_kg(diam_list, wd_lookup, main_len=MAIN_LINE_LENGTH):
        """Peso (kg) das linhas principais — dict lookup pré-computado."""
        return sum(main_len * wd_lookup.get(float(dm), 0.0) for dm in diam_list)

    @staticmethod
    def _eval_weight(individual, dmd_arr, lines_base, diam_weights_arr, n,
                     adv_pos, lines_pos, adv_names, wd_lookup, params):
        """
        Objetivo: minimizar peso total (kg) = ramais + linhas principais.
        Uma única chamada a find_diameters por indivíduo; sem pandas no hot path.
        """
        ld = WaterDistribution._line_demand(individual, dmd_arr, lines_base)
        hp, _, _, diam_l = find_diameters(
            params['df_diameters'], ld, ld / params['convertion_rate'],
            params['constant_HW'], params['dimensioning_length'],
            params['min_pressure'], params['max_pressure'],
            params['velocity'], [1000, 8, 10], 1)
        ok, mv, dd = WaterDistribution._mono(diam_l)

        branch_w, _ = WaterDistribution._branch_weight_kg(
            individual, adv_pos, lines_pos, diam_weights_arr)
        line_w   = WaterDistribution._line_weight_kg(diam_l, wd_lookup)
        total_w  = branch_w + line_w          # kg — objetivo real

        if hp > 0 or not ok or mv < (1.0 - WaterDistribution.MONOTONICITY_TOLERANCE):
            mono_pen = WaterDistribution.MONOTONICITY_PENALTY_WEIGHT * (
                float(np.sum(np.abs(np.minimum(dd, 0)))) +
                max(0.0, (1.0 - WaterDistribution.MONOTONICITY_TOLERANCE) - mv) +
                int(np.sum(dd < 0)))
            return (WaterDistribution.HYDRAULIC_PENALTY_WEIGHT * hp + mono_pen + total_w,)

        return (total_w,)

    @staticmethod
    def _checkout(individual, dmd_arr, lines_base, n, params):
        """Validação pós-GA: verifica factibilidade hidráulica e monotonicidade."""
        ld = WaterDistribution._line_demand(individual, dmd_arr, lines_base)
        hp, _, _, diam = find_diameters(
            params['df_diameters'], ld, ld/params['convertion_rate'],
            params['constant_HW'], params['dimensioning_length'],
            params['min_pressure'], params['max_pressure'],
            params['velocity'], [1000, 8, 10], 1)
        ok, mv, _ = WaterDistribution._mono(diam)
        return (hp == 0) and ok and (mv >= 1.0 - WaterDistribution.MONOTONICITY_TOLERANCE)

    @staticmethod
    def _get_constraints(coam_area, mod_area, water_pos, df_adv):
        last_mods, adv_pos, valid_lines = [], {}, {}
        eligible = lambda xi: [i+1 for i,p in enumerate(water_pos) if p<=xi]
        for idx, mod in enumerate(mod_area['modules']):
            if mod not in df_adv['zone'].values: continue
            adv_pos[mod] = mod_area['position'][idx]
            lines = eligible(mod_area['limits'][idx][0])
            if not lines: last_mods.append(mod)
            else:         valid_lines[mod] = lines
        for idx, com in enumerate(coam_area['coamings']):
            adv_pos[com] = coam_area['position'][idx]
            lines = eligible(coam_area['limits'][idx][0])
            if not lines: last_mods.append(com)
            else:         valid_lines[com] = lines
        return valid_lines, adv_pos, last_mods

    @staticmethod
    def _consumer_df(consumer_zone, adv_names, n, mod_area, last_mods, flow_m3h, flow_lmin):
        ld = {f'L{l}': {'m':[],'c':[]} for l in range(1,n+1)}
        for adv, line in zip(adv_names, consumer_zone):
            k = f'L{line}'
            if adv in mod_area.get('modules',[]): ld[k]['m'].append(adv)
            else:                                  ld[k]['c'].append(adv)
        for adv in last_mods:
            k = f'L{n}'
            if adv in mod_area.get('modules',[]): ld[k]['m'].append(adv)
            else:                                  ld[k]['c'].append(adv)
        return pd.DataFrame([{
            'lines': f'L{l}',
            'consumer modules':   ld[f'L{l}']['m'],
            'consumer coamings':  ld[f'L{l}']['c'],
            'needed flow (m3/h)': round(float(flow_m3h[l-1]),4),
            'needed flow (L/min)':round(float(flow_lmin[l-1]),4),
        } for l in range(1,n+1)])

    @staticmethod
    def _total_weight(df_dem, mod_area, water_pos, coam_area,
                      df_mod, df_com, params, water_diameters):
        """Peso total real (kg) = linhas principais + ramais de módulos/coamings."""
        wd_lookup = dict(zip(water_diameters['dn(in)'].astype(float),
                             water_diameters['weight'].astype(float)))
        _, _, _, diam_l = find_diameters(
            params['df_diameters'],
            df_dem['needed flow (m3/h)'].values,
            df_dem['needed flow (m3/h)'].values / params['convertion_rate'],
            params['constant_HW'], params['dimensioning_length'],
            params['min_pressure'], params['max_pressure'],
            params['velocity'], [1000, 8, 10], 1)
        lp     = np.array(water_pos)
        line_w = WaterDistribution._line_weight_kg(diam_l, wd_lookup)
        branch_w = tot_dist = 0.0
        hd_m = 'nominal diameter (in)' in df_mod.columns
        hd_c = 'nominal diameter (in)' in df_com.columns
        for _, row in df_dem.iterrows():
            li = int(row['lines'].split('L')[1])
            for mod in row['consumer modules']:
                d = abs(lp[li-1] - mod_area['position'][mod_area['modules'].index(mod)])
                tot_dist += d
                if hd_m:
                    dm = df_mod.loc[df_mod['zone']==mod, 'nominal diameter (in)']
                    if not dm.empty and dm.iloc[0] > 0:
                        branch_w += d * wd_lookup.get(float(dm.iloc[0]), 0.0); continue
                branch_w += d
            for com in row['consumer coamings']:
                d = abs(lp[li-1] - coam_area['position'][coam_area['coamings'].index(com)])
                tot_dist += d
                if hd_c:
                    dc = df_com.loc[df_com['coamings']==com, 'nominal diameter (in)']
                    if not dc.empty and dc.iloc[0] > 0:
                        branch_w += d * wd_lookup.get(float(dc.iloc[0]), 0.0); continue
                branch_w += d
        return line_w + branch_w, tot_dist, line_w, branch_w

    @staticmethod
    def run_single_ga(mod_area, df_adv, df_mod, df_com, adv_pos, valid_lines,
                      demands_df, n, water_pos, pipe_diam, hw, dim_len, cvt, vel, pmin, pmax):
        adv_names     = list(valid_lines.keys())
        dmd_arr, dia_arr, lines_base = WaterDistribution._build_demand(
            adv_names, df_adv, df_mod, df_com, demands_df['minimum waterflow (m3/h)'].values)
        adv_pos_arr   = np.array([adv_pos[z] for z in adv_names])
        lines_pos_arr = np.array(water_pos)
        params = dict(df_diameters=pipe_diam, dimensioning_length=dim_len,
                      constant_HW=hw, convertion_rate=cvt, velocity=vel,
                      min_pressure=pmin, max_pressure=pmax)

        # Pré-computa lookup de peso (kg/m) por diâmetro — elimina pandas no hot path
        wd_lookup       = dict(zip(pipe_diam['dn(in)'].astype(float),
                                   pipe_diam['weight'].astype(float)))
        diam_weights_arr = np.array([wd_lookup.get(float(dm), 0.0) for dm in dia_arr])

        for name in ['FitnessMin', 'Individual']:
            if name in creator.__dict__: delattr(creator, name)
        creator.create('FitnessMin', base.Fitness, weights=(-1.0,))
        creator.create('Individual', list, fitness=creator.FitnessMin)
        tb = base.Toolbox()
        tb.register('attr', WaterDistribution._create_ind, list(valid_lines.values()))
        tb.register('individual', tools.initIterate, creator.Individual, tb.attr)
        tb.register('population', tools.initRepeat, list, tb.individual)
        pool = ThreadPool()
        tb.register('map', pool.map)
        # Objetivo único: peso em kg (ramais + linhas). Sem DeltaPenalty separado.
        tb.register('evaluate', functools.partial(
            WaterDistribution._eval_weight,
            dmd_arr=dmd_arr, lines_base=lines_base,
            diam_weights_arr=diam_weights_arr, n=n,
            adv_pos=adv_pos_arr, lines_pos=lines_pos_arr, adv_names=adv_names,
            wd_lookup=wd_lookup, params=params))
        tb.register('mate',   tools.cxTwoPoint)
        tb.register('mutate', WaterDistribution._mutate,
                    valid_lines=list(valid_lines.values()), indpb=0.15)
        tb.register('select', tools.selTournament, tournsize=5)
        stats = tools.Statistics(lambda ind: ind.fitness.values)
        stats.register('avg', np.mean); stats.register('min', np.min)
        pop = tb.population(n=GA_CONFIG['water_pop'])
        hof = tools.HallOfFame(3)
        pop, log = algorithms.eaMuPlusLambda(
            pop, tb, mu=GA_CONFIG['water_pop'], lambda_=GA_CONFIG['water_pop'],
            cxpb=0.80, mutpb=0.15,
            ngen=GA_CONFIG['water_gen'], stats=stats, halloffame=hof, verbose=False)
        pool.close(); pool.join()
        gen, mn, av = log.select('gen', 'min', 'avg')
        return hof[0], list(gen), list(mn), list(av)

    @staticmethod
    def get_consumer_modules(valid_lines_ls, module_area, coaming_area,
                              df_mod, df_com, demands_df, n, water_pos,
                              pipe_diam, hw, dim_len, cvt, vel, pmin, pmax,
                              n_seeds=5, store=None, label=None):
        lbl = label or f'{n} Linhas'
        df_com_ = df_com.rename(columns={
            'coamings':'zone', 'firewater demand (m3/h)':'minimum waterflow (m3/h)'})
        df_adv = pd.concat([
            df_mod[['zone','minimum waterflow (m3/h)']],
            df_com_[['zone','minimum waterflow (m3/h)']],
        ]).reset_index(drop=True)

        valid_lines, adv_pos, last_mods = WaterDistribution._get_constraints(
            coaming_area, module_area, water_pos, df_adv)
        if valid_lines_ls: valid_lines.update(valid_lines_ls)

        lk   = f'L{n}'
        ldmd = float(demands_df.loc[demands_df['lines']==lk,'minimum waterflow (m3/h)'].iloc[0])
        for adv in last_mods:
            m = df_adv.loc[df_adv['zone']==adv,'minimum waterflow (m3/h)']
            if not m.empty: ldmd += float(m.iloc[0])
        demands_df = demands_df.copy()
        demands_df.loc[demands_df['lines']==lk,'minimum waterflow (m3/h)'] = ldmd

        adv_names = list(valid_lines.keys())
        dmd_arr, dia_arr, lines_base = WaterDistribution._build_demand(
            adv_names, df_adv, df_mod, df_com, demands_df['minimum waterflow (m3/h)'].values)
        params = dict(df_diameters=pipe_diam, dimensioning_length=dim_len,
                      constant_HW=hw, convertion_rate=cvt, velocity=vel,
                      min_pressure=pmin, max_pressure=pmax)
        chk = functools.partial(WaterDistribution._checkout, dmd_arr=dmd_arr,
                                lines_base=lines_base, n=n, params=params)

        min_weight = np.inf; best_fc = None
        result_weights = []; conv_data = []

        for i in range(n_seeds):
            random.seed(i); np.random.seed(i)
            print(f'   🌱 [{lbl}] Seed {i+1}/{n_seeds}')
            cz, gen, mn, av = WaterDistribution.run_single_ga(
                module_area, df_adv, df_mod, df_com, adv_pos, valid_lines,
                demands_df, n, water_pos, pipe_diam, hw, dim_len, cvt, vel, pmin, pmax)

            if chk(cz):
                flow = lines_base.copy()
                np.add.at(flow, np.array(cz)-1, dmd_arr)
                cdf = WaterDistribution._consumer_df(
                    cz, adv_names, n, module_area, last_mods,
                    flow, np.round(flow/cvt, 2))
                tw, td, lw, bw = WaterDistribution._total_weight(
                    cdf, module_area, water_pos, coaming_area,
                    df_mod, df_com, params, pipe_diam)
                result_weights.append(tw)
                conv_data.append({'seed_idx':i, 'gen':gen, 'min_vals':mn, 'avg_vals':av,
                                  'total_weight_kg':tw, 'viable':True})
                if tw < min_weight: min_weight=tw; best_fc=cdf
            else:
                result_weights.append(np.inf)
                conv_data.append({'seed_idx':i, 'gen':gen, 'min_vals':mn, 'avg_vals':av,
                                  'total_weight_kg':np.inf, 'viable':False})

        if best_fc is not None and store is not None:
            store.add_config(lbl, n, conv_data, result_weights)
        return best_fc, result_weights


# ==============================================================================
# SEÇÃO 9 — PÓS-PROCESSAMENTO (pesos, distâncias, custos)
# ==============================================================================

def postprocess(final_consumers, df_demand, modules_areas, coamings_areas,
                df_mod, df_com, water_pos, water_monitors_flow, water_diameters,
                constant_HW, dimensioning_length_m, min_pressure, max_pressure,
                velocity_m_s, convertion_rate,
                avg_branch=AVG_BRANCH_LENGTH, main_len=MAIN_LINE_LENGTH):
    flows_e = water_monitors_flow['water flow (m3/h)'].values
    _, _, _, deq = find_diameters(water_diameters, flows_e, flows_e/convertion_rate,
                                  constant_HW, avg_branch, min_pressure, max_pressure,
                                  velocity_m_s, [1,1,1], 1)
    EQUIP = {'monitors (main deck)': deq[0], 'monitors (offloading)': deq[1],
             'monitors (helideck)':  deq[2], 'hydrants': deq[3]}

    _, _, _, diam_l = find_diameters(
        water_diameters, final_consumers['needed flow (m3/h)'].values,
        final_consumers['needed flow (L/min)'].values,
        constant_HW, dimensioning_length_m, min_pressure, max_pressure,
        velocity_m_s, [1,1,1], 1)
    fc = final_consumers.copy()
    fc['nominal diameter (in)'] = diam_l

    w_adv=w_lines=tot_dist=costo=0.0
    for _, row in fc.iterrows():
        ln  = row['lines']
        li  = int(ln.split('L')[1])
        pos = water_pos[li-1]
        lr  = df_demand[df_demand['lines']==ln].iloc[0]
        for key, deq_v in EQUIP.items():
            qtd = lr.get(key, 0)
            if qtd>0 and deq_v>0:
                ws = water_diameters.loc[water_diameters['dn(in)']==deq_v,'weight']
                if not ws.empty:
                    dt=qtd*avg_branch; tot_dist+=dt; w_adv+=dt*ws.iloc[0]; costo+=dt*(0.0254*deq_v)**1.5
        dm = row['nominal diameter (in)']
        if dm>0:
            ws = water_diameters.loc[water_diameters['dn(in)']==dm,'weight']
            if not ws.empty: w_lines+=main_len*ws.iloc[0]; costo+=main_len*(0.0254*dm)**1.5
        for mod in row['consumer modules']:
            idx=modules_areas['modules'].index(mod); d=abs(pos-modules_areas['position'][idx]); tot_dist+=d
            dm2=df_mod.loc[df_mod['zone']==mod,'nominal diameter (in)'].iloc[0]
            if dm2>0:
                ws=water_diameters.loc[water_diameters['dn(in)']==dm2,'weight']
                if not ws.empty: w_adv+=d*ws.iloc[0]; costo+=d*(0.0254*dm2)**1.5
        for com in row['consumer coamings']:
            idx=coamings_areas['coamings'].index(com); d=abs(pos-coamings_areas['position'][idx]); tot_dist+=d
            dc2=df_com.loc[df_com['coamings']==com,'nominal diameter (in)'].iloc[0]
            if dc2>0:
                ws=water_diameters.loc[water_diameters['dn(in)']==dc2,'weight']
                if not ws.empty: w_adv+=d*ws.iloc[0]; costo+=d*(0.0254*dc2)**1.5
    return {'total_dist':tot_dist,'total_weight':w_adv+w_lines,'lines_weight':w_lines,
            'adv_weight':w_adv,'costo_final':costo,'df_consumers':fc.copy(),'equip_pipe_diam':EQUIP,
            'diameters_main': diam_l}


# ==============================================================================
# SEÇÃO 9B — MONOTONICIDADE: PARÂMETROS E GRÁFICO DE BARRAS
# ==============================================================================

def calcular_monotonicidade(diam_list: list, label: str = '') -> dict:
    """
    Calcula indicadores de monotonicidade da sequência de diâmetros
    das linhas principais.

    Parâmetros retornados
    ---------------------
    mono_ratio   : fração de pares consecutivos não-decrescentes  (0–1; 1 = perfeito)
    n_breaks     : número de inversões (quedas de diâmetro)
    total_drop   : soma total das reduções em polegadas
    max_drop     : maior queda individual em polegadas
    is_monotone  : bool — True se sem inversões
    breaks_idx   : índices (base 0) onde ocorrem inversões
    """
    d  = np.array(diam_list, dtype=float)
    dd = np.diff(d)
    breaks_idx   = list(np.where(dd < 0)[0])
    n_breaks     = len(breaks_idx)
    total_drop   = float(np.sum(np.abs(dd[dd < 0])))
    max_drop     = float(np.max(np.abs(dd[dd < 0]))) if n_breaks > 0 else 0.0
    mono_ratio   = float(np.sum(dd >= 0)) / len(dd) if len(dd) > 0 else 1.0
    is_monotone  = n_breaks == 0

    result = {
        'label':       label,
        'diameters':   diam_list,
        'mono_ratio':  round(mono_ratio, 4),
        'n_breaks':    n_breaks,
        'total_drop':  round(total_drop, 2),
        'max_drop':    round(max_drop, 2),
        'is_monotone': is_monotone,
        'breaks_idx':  breaks_idx,
    }

    # Impressão resumida
    status = '✅ Monotônica' if is_monotone else f'⚠️  {n_breaks} quebra(s)'
    print(f'\n   Monotonicidade [{label}]: {status}')
    print(f'      Índice (mono_ratio)  : {mono_ratio:.4f}  '
          f'({mono_ratio*100:.1f}% dos pares não-decrescentes)')
    print(f'      Quebras              : {n_breaks}')
    if n_breaks:
        print(f'      Queda total (in)     : {total_drop:.2f}')
        print(f'      Maior queda (in)     : {max_drop:.2f}')
        print(f'      Pares com queda      : '
              f'{[f"L{i+1}→L{i+2}" for i in breaks_idx]}')
    return result


def plotar_diametros_linhas(diam_list: list, lines_labels: list,
                             titulo: str, nome_arquivo: str,
                             mono_params: dict = None):
    """
    Gráfico de barras dos diâmetros das linhas principais com visualização
    de monotonicidade.

    Barras verdes  → diâmetro ≥ anterior  (monótono)
    Barras vermelhas → diâmetro < anterior (inversão)
    Barra cinza    → L1 (sem comparação anterior)
    """
    n      = len(diam_list)
    labels = lines_labels if lines_labels else [f'L{i+1}' for i in range(n)]
    d      = np.array(diam_list, dtype=float)
    dd     = np.diff(d)

    # Cores por barra
    cores = []
    for i in range(n):
        if i == 0:
            cores.append('#888780')        # cinza — sem comparação
        elif dd[i-1] >= 0:
            cores.append('#639922')        # verde — não-decrescente
        else:
            cores.append('#E24B4A')        # vermelho — inversão

    fig, ax = plt.subplots(figsize=(14, 6))

    bars = ax.bar(labels, d, color=cores, edgecolor='white',
                  linewidth=0.8, width=0.65, zorder=3)

    # Anotações no topo de cada barra
    for bar, val, cor in zip(bars, d, cores):
        ax.text(bar.get_x() + bar.get_width()/2,
                bar.get_height() + 0.08,
                f'{val:.0f}"',
                ha='center', va='bottom', fontsize=12, fontweight='500',
                color='#3B3B3A')

    # Linha de tendência ideal (sequência ordenada)
    d_sorted = np.sort(d)
    ax.step(np.arange(n) - 0.32, d_sorted, where='post',
            color='#378ADD', linewidth=1.8, linestyle='--',
            alpha=0.6, label='Sequência monotônica ideal', zorder=4)

    # Legenda de monotonicidade
    if mono_params:
        mr   = mono_params['mono_ratio']
        nb   = mono_params['n_breaks']
        td   = mono_params['total_drop']
        info = (f'Mono ratio: {mr:.3f}  |  '
                f'Quebras: {nb}  |  '
                f'Queda total: {td:.1f}"')
        ax.text(0.02, 0.97, info,
                transform=ax.transAxes, fontsize=11,
                va='top', ha='left',
                bbox=dict(boxstyle='round,pad=0.4',
                          facecolor='#F1EFE8', alpha=0.85,
                          edgecolor='#B4B2A9'))

    # Legenda de cores
    from matplotlib.patches import Patch
    legenda = [
        Patch(facecolor='#639922', label='Não-decrescente ✓'),
        Patch(facecolor='#E24B4A', label='Inversão ✗'),
        Patch(facecolor='#888780', label='L1 (referência)'),
    ]
    ax.legend(handles=legenda + [
        plt.Line2D([0], [0], color='#378ADD', lw=1.8,
                   linestyle='--', label='Ideal monotônica')],
        loc='upper left', fontsize=11, framealpha=0.9)

    # Eixos e estilo
    ax.set_xlabel('Linha de proteção', fontsize=14, fontweight='500', labelpad=10)
    ax.set_ylabel('Diâmetro nominal (in)', fontsize=14, fontweight='500', labelpad=10)
    ax.set_title(titulo, fontsize=16, fontweight='500', pad=18)
    ax.set_ylim(0, max(d) * 1.22)
    ax.yaxis.set_major_locator(plt.MultipleLocator(2))
    ax.grid(axis='y', linestyle=':', alpha=0.45, linewidth=1.2, zorder=0)
    ax.set_axisbelow(True)
    plt.tight_layout()

    _salvar_figura(fig, nome_arquivo)
    return fig

def exportar_excel(store, modules_areas_base, coamings_areas, df_mod, df_com,
                   water_diameters, xlsx_nome='detalhamento_linhas.xlsx',
                   avg_branch=AVG_BRANCH_LENGTH, main_len=MAIN_LINE_LENGTH):
    nome  = os.path.join(PASTA_SAIDA, xlsx_nome)
    abas  = 0
    dfs   = {}   # acumula DataFrames antes de abrir o writer

    for cfg in store.configs:
        if not cfg['viable_weights'] or 'df_consumers' not in cfg:
            continue

        # Usa modules_areas salvo no store (já tem 'position' calculado)
        ma_cfg = cfg.get('modules_areas', modules_areas_base)

        fc    = cfg['df_consumers']
        wpos  = cfg['water_position']
        ddm   = cfg.get('df_demand_per_lines', pd.DataFrame())
        EQUIP = cfg.get('equip_pipe_diam', {})
        rows  = []

        for _, row in fc.iterrows():
            ln  = row['lines']
            li  = int(ln.replace('L', '')) - 1
            pos = wpos[li]
            dm  = row['nominal diameter (in)']

            ml_w = ml_c = 0.0
            if dm > 0:
                ws = water_diameters.loc[water_diameters['dn(in)'] == dm, 'weight']
                if not ws.empty:
                    ml_w = (main_len * ws.iloc[0]) / 1000
                    ml_c = main_len * (0.0254 * dm) ** 1.5

            al = aw = ac = 0.0
            for mod in row['consumer modules']:
                if mod not in ma_cfg['modules']:
                    continue
                idx = ma_cfg['modules'].index(mod)
                if 'position' not in ma_cfg or idx >= len(ma_cfg['position']):
                    continue
                d   = abs(pos - ma_cfg['position'][idx])
                al += d
                dm2_s = df_mod.loc[df_mod['zone'] == mod, 'nominal diameter (in)']
                if dm2_s.empty:
                    continue
                dm2 = dm2_s.iloc[0]
                if dm2 > 0:
                    ws = water_diameters.loc[water_diameters['dn(in)'] == dm2, 'weight']
                    if not ws.empty:
                        aw += (d * ws.iloc[0]) / 1000
                        ac += d * (0.0254 * dm2) ** 1.5

            for com in row['consumer coamings']:
                if com not in coamings_areas['coamings']:
                    continue
                idx = coamings_areas['coamings'].index(com)
                d   = abs(pos - coamings_areas['position'][idx])
                al += d
                dc2_s = df_com.loc[df_com['coamings'] == com, 'nominal diameter (in)']
                if dc2_s.empty:
                    continue
                dc2 = dc2_s.iloc[0]
                if dc2 > 0:
                    ws = water_diameters.loc[water_diameters['dn(in)'] == dc2, 'weight']
                    if not ws.empty:
                        aw += (d * ws.iloc[0]) / 1000
                        ac += d * (0.0254 * dc2) ** 1.5

            el = ew = ec = 0.0
            if not ddm.empty and EQUIP:
                lr = ddm[ddm['lines'] == ln]
                if not lr.empty:
                    lr = lr.iloc[0]
                    for ek, deq_v in EQUIP.items():
                        qtd = lr.get(ek, 0)
                        if qtd > 0 and deq_v > 0:
                            ws = water_diameters.loc[water_diameters['dn(in)'] == deq_v, 'weight']
                            if not ws.empty:
                                dt  = qtd * avg_branch
                                el += dt
                                ew += (dt * ws.iloc[0]) / 1000
                                ec += dt * (0.0254 * deq_v) ** 1.5

            rows.append({
                'Linha':                      ln,
                'Módulos':                    ', '.join(row['consumer modules']) or '-',
                'Coamings':                   ', '.join(row['consumer coamings']) or '-',
                'Diâm. Principal (in)':       dm,
                'Compr. Principal (m)':       main_len,
                'Compr. Ramais Mód/Coam (m)': round(al, 2),
                'Compr. Ramais Equip (m)':    round(el, 2),
                'Peso Principal (ton)':       round(ml_w, 4),
                'Peso Ramais Mód/Coam (ton)': round(aw, 4),
                'Peso Ramais Equip (ton)':    round(ew, 4),
                'Peso Total Linha (ton)':     round(ml_w + aw + ew, 4),
                'Custo Principal':            round(ml_c, 4),
                'Custo Ramais Mód/Coam':      round(ac, 4),
                'Custo Ramais Equip':         round(ec, 4),
                'Custo Total Linha':          round(ml_c + ac + ec, 4),
            })

        df_d = pd.DataFrame(rows)
        if df_d.empty:
            continue

        # Linha de totais — colunas numéricas somadas, textuais com marcador
        tot = df_d.select_dtypes(include='number').sum()
        tot_row = {col: tot[col] if col in tot.index else '-' for col in df_d.columns}
        tot_row['Linha']                    = 'TOTAL GERAL'
        tot_row['Módulos']                  = '-'
        tot_row['Coamings']                 = '-'
        tot_row['Diâm. Principal (in)']     = '-'
        tot_row['Compr. Principal (m)']     = '-'

        # Garante dtype object para permitir mistura de string e número
        df_d = df_d.astype(object)
        df_d = pd.concat([df_d, pd.DataFrame([tot_row])], ignore_index=True)
        dfs[cfg['label'].replace(' ', '_')] = df_d
        abas += 1

    dfs['Resumo_Geral'] = store.summary_table()

    if abas == 0 and dfs.get('Resumo_Geral') is not None and dfs['Resumo_Geral'].empty:
        print('\n⚠️ Nenhuma configuração viável para exportar.')
        return

    with pd.ExcelWriter(nome, engine='openpyxl') as writer:
        for sheet_name, df_sheet in dfs.items():
            if df_sheet is not None and not (hasattr(df_sheet, 'empty') and df_sheet.empty):
                df_sheet.to_excel(writer, sheet_name=sheet_name, index=False)

    print(f'\n✅ Excel exportado: {nome}')


# ==============================================================================
# SEÇÃO 11 — ANÁLISE DE PRESSÃO (CASOS CRÍTICOS)
# ==============================================================================

def analisar_pressao(store, modules_areas, water_monitors_flow,
                     modules_df_demand, water_diameters):
    configs = [c for c in store.configs if c['viable_weights']]
    if not configs:
        print('⚠️ Nenhuma configuração viável para análise de pressão.')
        return
    print('\n' + '='*80 + '\n🚒 ANÁLISE DE PRESSÃO — CASOS CRÍTICOS\n' + '='*80)
    for cfg in configs:
        fc  = cfg['df_consumers']
        dd  = cfg['df_demand_per_lines']
        wp  = cfg['water_position']
        eq  = cfg.get('equip_pipe_diam', {})
        # usa modules_areas salvo no store (já tem 'position' calculado)
        ma  = cfg.get('modules_areas', modules_areas)
        print(f'\n  🔹 {cfg["label"]}')
        qb  = 1200.0

        # Case 01 — offloading mais distante
        off = dd[dd['monitors (offloading)'] > 0].copy()
        if not off.empty:
            off['pos'] = off['lines'].apply(lambda x: wp[int(x.replace('L', '')) - 1])
            off['d']   = abs(off['pos'] - PUMP_X_POSITION)
            a   = off.loc[off['d'].idxmax()]
            dm  = fc.loc[fc['lines'] == a['lines'], 'nominal diameter (in)'].iloc[0] * 2
            qr  = water_monitors_flow.loc[
                water_monitors_flow['monitor cannon'] == 'offloading', 'water flow (m3/h)'].iloc[0]
            dr  = eq.get('monitors (offloading)', 4.0)
            p   = (calc_hazen_williams(qb, dm, a['d'], water_diameters) +
                   calc_hazen_williams(qr, dr, 10.0, water_diameters) +
                   ELEVACAO_OFFLOADING / 10 + PRESSAO_BICO_MONITOR)
            print(f'     🌊 CASE 01 (Offloading) — Linha {a["lines"]} | P = {p:.2f} bar')

        # Case 02 — M-03
        modref = 'M-03'
        if modref in ma.get('modules', []):
            for idx2, row in fc.iterrows():
                if modref in row['consumer modules']:
                    pos2 = wp[idx2]
                    dm2  = row['nominal diameter (in)'] * 1.5
                    im   = ma['modules'].index(modref)
                    dx   = abs(pos2 - ma['position'][im])
                    yi, ys = ma['limits y'][im]
                    dy   = abs((yi + ys) / 2)
                    qr   = water_monitors_flow.loc[
                        water_monitors_flow['monitor cannon'] == 'hydrant', 'water flow (m3/h)'].iloc[0]
                    dr   = modules_df_demand.loc[
                        modules_df_demand['zone'] == modref, 'nominal diameter (in)'].iloc[0]
                    p2   = (calc_hazen_williams(qb, dm2, abs(pos2 - PUMP_X_POSITION), water_diameters) +
                            calc_hazen_williams(qr, dr, 15 + dy + dx, water_diameters) +
                            ELEVACAO_M_03 / 10 + PRESSAO_BICO_HIDRANTE)
                    print(f'     🚒 CASE 02 ({modref})     — Linha {row["lines"]} | P = {p2:.2f} bar')
                    break

        # Case 03 — helideck mais distante
        heli = dd[dd['monitors (helideck)'] > 0].copy()
        if not heli.empty:
            heli['pos'] = heli['lines'].apply(lambda x: wp[int(x.replace('L', '')) - 1])
            heli['d']   = abs(heli['pos'] - PUMP_X_POSITION)
            a3  = heli.loc[heli['d'].idxmax()]
            dm3 = fc.loc[fc['lines'] == a3['lines'], 'nominal diameter (in)'].iloc[0] * 2
            qr3 = water_monitors_flow.loc[
                water_monitors_flow['monitor cannon'] == 'helideck', 'water flow (m3/h)'].iloc[0]
            dr3 = eq.get('monitors (helideck)', 4.0)
            p3  = (calc_hazen_williams(qb, dm3, a3['d'], water_diameters) +
                   calc_hazen_williams(qr3, dr3, 10.0, water_diameters) +
                   ELEVACAO_HELIDECK / 10 + PRESSAO_BICO_MONITOR)
            print(f'     🚁 CASE 03 (Helideck)  — Linha {a3["lines"]} | P = {p3:.2f} bar')


# ==============================================================================
# SEÇÃO 12 — MODO MANUAL
# ==============================================================================

def executar_modo_manual(data: dict, xlsx_nome: str = 'detalhamento_manual.xlsx'):
    """
    Calcula diâmetros, pesos e custos para a alocação definida em
    manual_consumers_config.py.

    Distribuição de hidrantes: usa exatamente o mesmo MonitorDistribution
    do DIRETO/ETAPAS (posições das linhas extraídas de MANUAL_CONSUMERS).
    Módulos e coamings: alocação manual (config).
    Monitores (main deck / offloading / helideck): alocação manual (config).
    """
    if not MANUAL_CONSUMERS:
        print('⚠️ MANUAL_CONSUMERS está vazio. Preencha manual_consumers_config.py.')
        return

    print('\n🔧 MODO MANUAL\n')

    # ── dados base ──────────────────────────────────────────────────────────
    n       = MANUAL_WATER_LINES
    wmon    = data['water_monitors_flow']
    wdiam   = data['water_diameters']
    df_mod  = data['modules_df_demand']
    df_com  = data['coamings_df_demand']
    coam_a  = data['coamings_areas']
    hw      = data['constant_HW']
    vel     = data['velocity_m_s']
    dim_len = data['dimensioning_length_m']
    pmin    = data['min_pressure']
    pmax    = data['max_pressure']
    cvt     = data['convertion_rate']

    expected = [f'L{i}' for i in range(1, n + 1)]
    missing  = [l for l in expected if l not in MANUAL_CONSUMERS]
    if missing:
        raise ValueError(f'Linhas sem consumidores definidos: {missing}')

    # ── posições das linhas (extraídas do config) ────────────────────────────
    water_pos = [
        float(MANUAL_CONSUMERS[ln].get('water_position', 0.0))
        for ln in expected
    ]
    print(f'   Posições das linhas (m): {[round(p,1) for p in water_pos]}')

    # ── distribui hidrantes com o MESMO algoritmo do DIRETO/ETAPAS ──────────
    ma = copy.deepcopy(data['modules_areas'])
    ma = LinesPosition.set_module_positions(ma, offset=15.0)

    dist_auto, hyd_map, _ = MonitorDistribution.get_monitor_distribution(
        module_area          = ma,
        modules_w_fuel       = data['modules_w_fuel'],
        n                    = n,
        water_pos            = water_pos,
        monitors_flows       = wmon,
        total_monitor_main   = data['main_deck_monitors'],
        total_monitor_offloading = data['offloading_monitors'],
        total_monitor_helideck   = data['helideck_monitor'],
        hydrants             = data['hydrants'],
    )
    # dict: linha → qtd hidrantes
    hyd_por_linha = dict(zip(dist_auto['lines'], dist_auto['hydrants']))
    print(f'   Hidrantes por linha (auto): {hyd_por_linha}')
    print(f'   Total hidrantes           : {sum(hyd_por_linha.values())} '
          f'(referência: {sum(data["hydrants"].values())})')

    # ── vazões por equipamento ───────────────────────────────────────────────
    def mflow(name):
        return float(wmon.loc[wmon['monitor cannon'] == name, 'water flow (m3/h)'].iloc[0])

    EF = {
        'monitors_main_deck':  mflow('main deck'),
        'monitors_offloading': mflow('offloading'),
        'monitors_helideck':   mflow('helideck'),
        'hydrants':            mflow('hydrant'),
    }

    # diâmetros de ramal para cada tipo de equipamento
    fq  = np.array(list(EF.values()))
    _, _, _, deq = find_diameters(
        wdiam, fq, fq / cvt, hw, AVG_BRANCH_LENGTH, pmin, pmax, vel, [1, 1, 1], 1)
    ED = dict(zip(EF.keys(), deq))

    # ── monta tabela linha por linha ─────────────────────────────────────────
    rows = []
    for ln in expected:
        c    = MANUAL_CONSUMERS[ln]
        flow = 0.0

        # monitores — alocação manual do config
        n_main = int(c.get('monitors_main_deck',  0))
        n_off  = int(c.get('monitors_offloading', 0))
        n_heli = int(c.get('monitors_helideck',   0))
        flow  += n_main * EF['monitors_main_deck']
        flow  += n_off  * EF['monitors_offloading']
        flow  += n_heli * EF['monitors_helideck']

        # hidrantes — distribuição automática (idêntico ao DIRETO)
        n_hyd  = int(hyd_por_linha.get(ln, 0))
        flow  += n_hyd * EF['hydrants']

        # módulos — alocação manual do config
        for mod in c.get('modules', []):
            m = df_mod.loc[df_mod['zone'] == mod, 'minimum waterflow (m3/h)']
            if not m.empty:
                flow += float(m.iloc[0])

        # coamings — alocação manual do config
        for com in c.get('coamings', []):
            m = df_com.loc[df_com['coamings'] == com, 'firewater demand (m3/h)']
            if not m.empty:
                flow += float(m.iloc[0])

        rows.append({
            'lines':               ln,
            'line_number':         int(ln.replace('L', '')),
            'consumer modules':    c.get('modules',  []),
            'consumer coamings':   c.get('coamings', []),
            'monitors_main_deck':  n_main,
            'monitors_offloading': n_off,
            'monitors_helideck':   n_heli,
            'hydrants':            n_hyd,
            'needed flow (m3/h)':  round(flow, 4),
            'needed flow (L/min)': round(flow / cvt, 4),
            'water_position':      water_pos[int(ln.replace('L', '')) - 1],
        })

    df_mc = pd.DataFrame(rows).sort_values('line_number').reset_index(drop=True)

    # ── diâmetros das linhas principais ─────────────────────────────────────
    _, _, _, diam_l = find_diameters(
        wdiam,
        df_mc['needed flow (m3/h)'].values,
        df_mc['needed flow (L/min)'].values,
        hw, dim_len, pmin, pmax, vel, [1, 1, 1], 1)
    df_mc['nominal diameter (in)'] = diam_l
    df_mc['diameter_diff']         = np.append(np.diff(diam_l), np.nan)

    # ── análise e gráfico de monotonicidade ──────────────────────────────────
    plataforma_tag = Path(XLSX_PATH).stem.split('_')[0].upper()
    mono = calcular_monotonicidade(
        list(diam_l),
        label=f'MANUAL {MANUAL_WATER_LINES}L — {plataforma_tag}')
    plotar_diametros_linhas(
        list(diam_l),
        lines_labels=df_mc['lines'].tolist(),
        titulo=f'Diâmetros das Linhas Principais — MANUAL {MANUAL_WATER_LINES}L',
        nome_arquivo=f'diametros_manual_{MANUAL_WATER_LINES}L',
        mono_params=mono)

    # ── pesos detalhados linha por linha ────────────────────────────────────
    wd_lookup = dict(zip(wdiam['dn(in)'].astype(float), wdiam['weight'].astype(float)))

    # Diâmetros de ramal para equipamentos (monitores + hidrantes)
    EQUIP_KEY = {
        'monitors (main deck)':  'monitors_main_deck',
        'monitors (offloading)': 'monitors_offloading',
        'monitors (helideck)':   'monitors_helideck',
        'hydrants':              'hydrants',
    }
    fq_equip = np.array(list(EF.values()))
    _, _, _, deq_equip = find_diameters(
        wdiam, fq_equip, fq_equip / cvt, hw, AVG_BRANCH_LENGTH, pmin, pmax, vel, [1, 1, 1], 1)
    EQUIP_DIAM = {
        'monitors_main_deck':  deq_equip[0],
        'monitors_offloading': deq_equip[1],
        'monitors_helideck':   deq_equip[2],
        'hydrants':            deq_equip[3],
    }

    det_rows = []
    w_lines = w_adv = tot_dist = 0.0

    for _, row in df_mc.iterrows():
        ln  = row['lines']
        li  = int(ln.replace('L', '')) - 1
        pos = water_pos[li]
        dm  = row['nominal diameter (in)']

        # Linha principal
        ml_w = ml_len = 0.0
        if dm > 0:
            ml_len  = MAIN_LINE_LENGTH
            ml_w    = ml_len * wd_lookup.get(float(dm), 0.0) / 1000  # ton
            w_lines += ml_w * 1000

        # Ramais módulos + coamings
        al = aw = 0.0
        mods_str  = ', '.join(row['consumer modules'])  or '-'
        coams_str = ', '.join(row['consumer coamings']) or '-'

        for mod in row['consumer modules']:
            if mod not in ma['modules']: continue
            idx = ma['modules'].index(mod)
            d   = abs(pos - ma['position'][idx])
            al += d; tot_dist += d
            dm2 = df_mod.loc[df_mod['zone'] == mod, 'nominal diameter (in)']
            if not dm2.empty and dm2.iloc[0] > 0:
                aw += d * wd_lookup.get(float(dm2.iloc[0]), 0.0) / 1000

        for com in row['consumer coamings']:
            if com not in coam_a['coamings']: continue
            idx = coam_a['coamings'].index(com)
            d   = abs(pos - coam_a['position'][idx])
            al += d; tot_dist += d
            dc2 = df_com.loc[df_com['coamings'] == com, 'nominal diameter (in)']
            if not dc2.empty and dc2.iloc[0] > 0:
                aw += d * wd_lookup.get(float(dc2.iloc[0]), 0.0) / 1000

        w_adv += aw * 1000

        # Ramais equipamentos (monitores + hidrantes)
        el = ew = 0.0
        for eq_col, deq_v in EQUIP_DIAM.items():
            qtd = int(row.get(eq_col, 0))
            if qtd > 0 and float(deq_v) > 0:
                dt  = qtd * AVG_BRANCH_LENGTH
                el += dt; tot_dist += dt
                ew += dt * wd_lookup.get(float(deq_v), 0.0) / 1000

        w_adv += ew * 1000

        det_rows.append({
            'Linha':                      ln,
            'Módulos':                    mods_str,
            'Coamings':                   coams_str,
            'Monitores MD':               int(row['monitors_main_deck']),
            'Monitores Off.':             int(row['monitors_offloading']),
            'Monitores Heli.':            int(row['monitors_helideck']),
            'Hidrantes':                  int(row['hydrants']),
            'Vazão (m³/h)':               round(row['needed flow (m3/h)'], 2),
            'Diâm. Principal (in)':       dm,
            'Compr. Principal (m)':       round(ml_len, 1),
            'Compr. Ramais Mód/Coam (m)': round(al, 2),
            'Compr. Ramais Equip (m)':    round(el, 2),
            'Peso Principal (ton)':       round(ml_w, 4),
            'Peso Ramais Mód/Coam (ton)': round(aw, 4),
            'Peso Ramais Equip (ton)':    round(ew, 4),
            'Peso Total Linha (ton)':     round(ml_w + aw + ew, 4),
        })

    df_det = pd.DataFrame(det_rows)

    # Linha de totais
    tot_row = df_det.select_dtypes(include='number').sum().to_dict()
    tot_row['Linha']                   = 'TOTAL GERAL'
    tot_row['Módulos']                 = '-'
    tot_row['Coamings']                = '-'
    tot_row['Diâm. Principal (in)']    = '-'
    df_det = pd.concat([df_det.astype(object),
                        pd.DataFrame([tot_row])],
                       ignore_index=True)

    w_total = w_lines + w_adv

    # ── impressão resumida ───────────────────────────────────────────────────
    _display(df_mc[['lines', 'monitors_main_deck', 'monitors_offloading',
                     'monitors_helideck', 'hydrants',
                     'needed flow (m3/h)', 'needed flow (L/min)',
                     'nominal diameter (in)', 'diameter_diff']],
             'Tabela de Diâmetros e Vazões — Modo Manual')

    print(f'\nMonitores main deck    : {df_mc["monitors_main_deck"].sum()} '
          f'(referência: {data["main_deck_monitors"]})')
    print(f'Monitores offloading   : {df_mc["monitors_offloading"].sum()} '
          f'(referência: {data["offloading_monitors"]})')
    print(f'Monitores helideck     : {df_mc["monitors_helideck"].sum()} '
          f'(referência: {data["helideck_monitor"]})')
    print(f'Hidrantes totais       : {df_mc["hydrants"].sum()} '
          f'(referência: {sum(data["hydrants"].values())})')
    print(f'\nPeso linhas principais : {w_lines/1000:.3f} ton')
    print(f'Peso ramais mód/coam   : {(w_adv - sum(r["Peso Ramais Equip (ton)"]*1000 for r in det_rows))/1000:.3f} ton')
    print(f'Peso ramais equip      : {sum(r["Peso Ramais Equip (ton)"]*1000 for r in det_rows)/1000:.3f} ton')
    print(f'Peso total             : {w_total/1000:.3f} ton')
    print(f'Distância total ramais : {tot_dist:.1f} m')

    # ── exporta Excel com detalhamento completo ──────────────────────────────
    caminho_xlsx = os.path.join(PASTA_SAIDA, xlsx_nome)

    # Aba de alocação (consumidores + diâmetros + vazões)
    cols_aloc = ['lines', 'consumer modules', 'consumer coamings',
                 'monitors_main_deck', 'monitors_offloading', 'monitors_helideck',
                 'hydrants', 'needed flow (m3/h)', 'needed flow (L/min)',
                 'nominal diameter (in)']
    df_aloc = df_mc[[c for c in cols_aloc if c in df_mc.columns]].copy()

    # Aba de resumo
    df_resumo = pd.DataFrame([{
        'Item':  'Peso linhas principais (ton)',  'Valor': round(w_lines/1000, 3)}, {
        'Item':  'Peso ramais mód/coam (ton)',
        'Valor': round(sum(r['Peso Ramais Mód/Coam (ton)'] for r in det_rows), 3)}, {
        'Item':  'Peso ramais equip (ton)',
        'Valor': round(sum(r['Peso Ramais Equip (ton)'] for r in det_rows), 3)}, {
        'Item':  'Peso total (ton)',              'Valor': round(w_total/1000, 3)}, {
        'Item':  'Distância total ramais (m)',    'Valor': round(tot_dist, 1)}, {
        'Item':  'Hidrantes totais',              'Valor': int(df_mc['hydrants'].sum())}, {
        'Item':  'mono_ratio',                    'Valor': mono['mono_ratio']}, {
        'Item':  'Quebras monotonicidade',        'Valor': mono['n_breaks']}, {
        'Item':  'Queda total diâm (in)',         'Valor': mono['total_drop']},
    ])

    with pd.ExcelWriter(caminho_xlsx, engine='openpyxl') as writer:
        df_det.to_excel(writer, sheet_name='Detalhamento', index=False)
        df_aloc.to_excel(writer, sheet_name='Alocacao_Consumidores', index=False)
        df_resumo.to_excel(writer, sheet_name='Resumo', index=False)

    print(f'\n✅ Excel exportado: {caminho_xlsx}')
    return df_mc


# ==============================================================================
# SEÇÃO 13 — ORQUESTRAÇÃO INTERNA
# ==============================================================================

def _prep_posicoes(wl, modules_areas_base, data):
    ma = copy.deepcopy(modules_areas_base)
    ma = LinesPosition.set_module_positions(ma, offset=15.0)
    fp, wp = LinesPosition.get_lines_position(
        data['platform_info'], data['foam_lines_quantity'], wl,
        data['modules_distribution'], ma, data['modules_w_fuel'],
        data['coamings_distribution'], data['coamings_areas'],
        data['foam_distance_lines'])
    return ma, fp, wp


def _calc_dist(wl, ma, fp, wp, data):
    foam_dist = FoamDistribution.get_foam_distribution(
        data['coamings_df_demand'], data['coamings_areas'], fp,
        data['foam_lines_quantity'],
        data['offloading_monitors'], data['foam_offloading_flow'],
        data['main_deck_monitors'],  data['foam_main_deck_flow'],
        data['foam_diameters'], data['constant_HW'],
        data['dimensioning_length_m'], data['velocity_m_s'],
        data['min_pressure'], data['max_pressure'], data['convertion_rate'])

    water_dist, hyd_map, valid_lines = MonitorDistribution.get_monitor_distribution(
        ma, data['modules_w_fuel'], wl, wp, data['water_monitors_flow'],
        data['main_deck_monitors'], data['offloading_monitors'],
        data['helideck_monitor'], data['hydrants'])

    df_dem = pd.DataFrame.from_dict(water_dist)
    df_dem.columns = [c.lower() for c in df_dem.columns]
    if isinstance(hyd_map.get('L1'), list):
        df_h = pd.DataFrame(hyd_map.items(), columns=['lines','consumer hydrants'])
        df_dem = pd.merge(df_dem, df_h, on='lines', how='left')
    return foam_dist, df_dem, valid_lines


def _rodar_ga(wl, ma, wp, df_dem, valid_lines, data, store):
    return WaterDistribution.get_consumer_modules(
        valid_lines_ls=valid_lines, module_area=ma,
        coaming_area=data['coamings_areas'],
        df_mod=data['modules_df_demand'], df_com=data['coamings_df_demand'],
        demands_df=df_dem.copy(), n=wl, water_pos=wp,
        pipe_diam=data['water_diameters'],
        hw=data['constant_HW'], dim_len=data['dimensioning_length_m'],
        cvt=data['convertion_rate'], vel=data['velocity_m_s'],
        pmin=data['min_pressure'], pmax=data['max_pressure'],
        n_seeds=N_SEEDS_GA, store=store, label=f'{wl} Linhas')


def _atualizar_store(store, wl, post, df_dem, wp, fp, foam_dist, ma):
    lbl      = f'{wl} Linhas'
    diam_l   = post['diameters_main']
    labels   = [f'L{i+1}' for i in range(wl)]

    # Monotonicidade
    mono = calcular_monotonicidade(diam_l, label=lbl)

    # Gráfico de barras
    plotar_diametros_linhas(
        diam_l, labels,
        titulo=f'Diâmetros das Linhas Principais — {lbl}',
        nome_arquivo=f'diametros_{wl}L',
        mono_params=mono)

    for cfg in store.configs:
        if cfg['label'] == lbl:
            cfg.update({'total_dist':     post['total_dist'],
                        'total_weight':   post['total_weight'],
                        'lines_weight':   post['lines_weight'],
                        'adv_weight':     post['adv_weight'],
                        'df_consumers':   post['df_consumers'].copy(),
                        'df_demand_per_lines': df_dem.copy(),
                        'water_position': copy.deepcopy(wp),
                        'foam_position':  copy.deepcopy(fp),
                        'equip_pipe_diam':post['equip_pipe_diam'],
                        'modules_areas':  copy.deepcopy(ma),
                        'foam_df_demand_per_lines': foam_dist,
                        'mono_params':    mono})
            break


def run_pipeline_etapas(water_lines, data, store, modules_areas_base):
    """Executa o pipeline completo para uma configuração no modo ETAPAS,
    com checkpoint entre cada etapa. Pode ser chamado individualmente."""
    lbl = f'{water_lines}L'
    print(f'\n  [Etapa 1] Posicionamento — {water_lines} linhas')
    ma, fp, wp = _prep_posicoes(water_lines, modules_areas_base, data)
    if fp is None: return
    _salvar_checkpoint({'ma':ma,'fp':fp,'wp':wp}, f'etapa1_{lbl}')

    print(f'  [Etapa 2] Distribuições — {water_lines} linhas')
    foam_dist, df_dem, valid_lines = _calc_dist(water_lines, ma, fp, wp, data)
    _salvar_checkpoint({'foam_dist':foam_dist,'df_dem':df_dem,'valid_lines':valid_lines}, f'etapa2_{lbl}')

    print(f'  [Etapa 3] GA — {water_lines} linhas')
    fc, costs = _rodar_ga(water_lines, ma, wp, df_dem, valid_lines, data, store)
    if fc is None: return
    _salvar_checkpoint({'fc':fc,'costs':costs}, f'etapa3_{lbl}')

    print(f'  [Etapa 4] Pós-processamento — {water_lines} linhas')
    post = postprocess(
        fc, df_dem, ma, data['coamings_areas'],
        data['modules_df_demand'], data['coamings_df_demand'],
        wp, data['water_monitors_flow'], data['water_diameters'],
        data['constant_HW'], data['dimensioning_length_m'],
        data['min_pressure'], data['max_pressure'],
        data['velocity_m_s'], data['convertion_rate'])
    _atualizar_store(store, water_lines, post, df_dem, wp, fp, foam_dist, ma)
    _salvar_checkpoint(post, f'etapa4_{lbl}')
    print(f'  ✅ {water_lines}L: Peso={post["total_weight"]/1000:.3f} ton | Custo={post["costo_final"]:.4f}')


# ==============================================================================
# SEÇÃO 14 — MAIN
# ==============================================================================

def main():
    print('='*80)
    print('  OTIMIZAÇÃO DE LINHAS DE PROTEÇÃO CONTRA INCÊNDIO')
    print(f'  Arquivo : {XLSX_PATH}')
    print(f'  Modo    : {MODO_EXECUCAO}')
    print('='*80)

    data               = load_data_from_excel(XLSX_PATH)
    modules_areas_base = data['modules_areas']
    water_lines_list   = LINHAS_AGUA_OVERRIDE or data['water_lines_quantity']

    # Nome da plataforma derivado do arquivo Excel (sem extensão)
    plataforma_tag = Path(XLSX_PATH).stem.split('_')[0].upper()
    print(f'\n   Plataforma: {plataforma_tag}')
    print(f'   Configurações de linhas a simular: {water_lines_list}\n')

    # Nomes de saída distintos por modo
    _xlsx_nome = {
        'DIRETO': f'detalhamento_direto_{plataforma_tag}.xlsx',
        'ETAPAS': f'detalhamento_etapas_{plataforma_tag}.xlsx',
        'MANUAL': f'detalhamento_manual_{plataforma_tag}.xlsx',
    }
    xlsx_saida = _xlsx_nome.get(MODO_EXECUCAO, 'detalhamento_linhas.xlsx')

    if MODO_EXECUCAO == 'MANUAL':
        executar_modo_manual(data, xlsx_saida)
        return

    store = GAResultsStore()
    t0    = time.time()

    if MODO_EXECUCAO == 'ETAPAS':
        for wl in water_lines_list:
            run_pipeline_etapas(wl, data, store, modules_areas_base)
    else:  # DIRETO
        print('🚀 Pipeline completo\n')
        for wl in water_lines_list:
            print(f'\n{"─"*60}\n  ▶ {wl} linhas de água\n{"─"*60}')
            ma, fp, wp = _prep_posicoes(wl, modules_areas_base, data)
            if fp is None: print(f'  ⏩ Pulando {wl} linhas.'); continue
            foam_dist, df_dem, valid_lines = _calc_dist(wl, ma, fp, wp, data)
            fc, costs = _rodar_ga(wl, ma, wp, df_dem, valid_lines, data, store)
            if fc is None: print(f'  ❌ GA sem solução viável.'); continue
            post = postprocess(
                fc, df_dem, ma, data['coamings_areas'],
                data['modules_df_demand'], data['coamings_df_demand'],
                wp, data['water_monitors_flow'], data['water_diameters'],
                data['constant_HW'], data['dimensioning_length_m'],
                data['min_pressure'], data['max_pressure'],
                data['velocity_m_s'], data['convertion_rate'])
            _atualizar_store(store, wl, post, df_dem, wp, fp, foam_dist, ma)
            print(f'\n  ✅ {wl} linhas: Dist={post["total_dist"]:.0f} m | '
                  f'Peso={post["total_weight"]/1000:.3f} ton')

    if store.configs:
        print('\n' + '='*60 + '\n📊 RESUMO COMPARATIVO\n' + '='*60)
        _display(store.summary_table())

    exportar_excel(store, modules_areas_base, data['coamings_areas'],
                   data['modules_df_demand'], data['coamings_df_demand'],
                   data['water_diameters'], xlsx_nome=xlsx_saida)
    analisar_pressao(store, modules_areas_base,
                     data['water_monitors_flow'],
                     data['modules_df_demand'],
                     data['water_diameters'])

    dt = time.time() - t0
    print(f'\n✅ Concluído em {int(dt//3600)}h {int((dt%3600)//60)}min {dt%60:.1f}s')


if __name__ == '__main__':
    main()
