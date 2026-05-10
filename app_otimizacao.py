# app_otimizacao.py
# -*- coding: utf-8 -*-
"""
Otimização de Linhas de Proteção Contra Incêndio — Interface Streamlit
Deploy: Streamlit Community Cloud  |  Versão 1.0  |  Mai/2026
"""

import os, sys, io, copy, time, tempfile, traceback, warnings
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import streamlit as st

warnings.filterwarnings('ignore')

# ── Configuração da página ─────────────────────────────────────────────────────
st.set_page_config(
    page_title="Otimização de Linhas FPSO",
    page_icon="🔥",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── CSS mínimo ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
  [data-testid="stSidebar"] { min-width: 320px; }
  .metric-card { background:#f0f4f8; border-radius:8px; padding:12px 16px; margin-bottom:8px; }
  .metric-label { font-size:12px; color:#555; margin-bottom:2px; }
  .metric-value { font-size:22px; font-weight:600; }
  .metric-sub   { font-size:11px; color:#888; margin-top:2px; }
  .ok  { color:#3B6D11; } .warn { color:#854F0B; } .err { color:#A32D2D; }
  div[data-testid="stTabs"] button { font-size:14px; }
</style>
""", unsafe_allow_html=True)

# ── Diretório temporário persistente na sessão ────────────────────────────────
if 'tmp_dir' not in st.session_state:
    st.session_state.tmp_dir   = tempfile.mkdtemp()
    st.session_state.resultados= os.path.join(st.session_state.tmp_dir, 'resultados')
    st.session_state.checkpts  = os.path.join(st.session_state.tmp_dir, 'checkpoints')
    os.makedirs(st.session_state.resultados, exist_ok=True)
    os.makedirs(st.session_state.checkpts,   exist_ok=True)

TMP     = st.session_state.tmp_dir
RES_DIR = st.session_state.resultados
CHK_DIR = st.session_state.checkpts

# ── Importa módulo do algoritmo ────────────────────────────────────────────────
@st.cache_resource(show_spinner=False)
def _import_algo():
    """Importa e configura o módulo do algoritmo uma única vez por sessão."""
    import importlib.util, types

    path = os.path.join(os.path.dirname(__file__), 'otimizacao_linhas_v3_pycharm.py')
    spec = importlib.util.spec_from_file_location('algo', path)
    mod  = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

try:
    algo = _import_algo()
except Exception as e:
    st.error(f"Erro ao importar o módulo do algoritmo:\n\n```\n{e}\n```")
    st.stop()

# Patch de paths e flags de I/O para Streamlit
algo.PASTA_SAIDA      = RES_DIR
algo.PASTA_CHECKPOINT = CHK_DIR
algo.SALVAR_GRAFICOS  = False   # figuras capturadas em memória
algo.MOSTRAR_GRAFICOS = False

# Captura de figuras em memória (em vez de salvar em disco)
_figs: dict = {}
def _salvar_figura_st(fig, nome):
    _figs[nome] = fig
    # não fecha — Streamlit precisa do objeto
algo._salvar_figura = _salvar_figura_st

# ── Helpers de UI ─────────────────────────────────────────────────────────────
def kpi(label, value, sub='', color=''):
    color_cls = f'class="{color}"' if color else ''
    st.markdown(f"""
    <div class="metric-card">
      <div class="metric-label">{label}</div>
      <div class="metric-value" {color_cls}>{value}</div>
      {'<div class="metric-sub">' + sub + '</div>' if sub else ''}
    </div>""", unsafe_allow_html=True)

def fig_to_bytes(fig):
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=120, bbox_inches='tight')
    buf.seek(0)
    return buf.read()

def excel_to_bytes(df_dict: dict) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='openpyxl') as w:
        for sheet, df in df_dict.items():
            df.to_excel(w, sheet_name=sheet, index=False)
    buf.seek(0)
    return buf.read()

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.image("https://upload.wikimedia.org/wikipedia/commons/thumb/8/8b/Petrobras_logo.svg/320px-Petrobras_logo.svg.png",
             width=140)
    st.title("🔥 Otimização de Linhas")
    st.caption("Proteção Contra Incêndio — FPSO")
    st.divider()

    # ── Upload Excel ──────────────────────────────────────────────────────────
    st.subheader("📂 Dados de entrada")
    xlsx_file = st.file_uploader(
        "Arquivo Excel da plataforma",
        type=['xlsx'],
        help="Estrutura obrigatória: abas Modules_Areas, Coamings_Areas, Hydrants, Parameters, etc."
    )

    # ── Modo ──────────────────────────────────────────────────────────────────
    st.subheader("⚙️ Configuração")
    modo = st.radio(
        "Modo de execução",
        ["DIRETO (GA)", "MANUAL"],
        help="DIRETO: algoritmo genético otimiza a alocação.\nMANUAL: alocação prescrita via manual_consumers_config.py"
    )
    modo_key = 'DIRETO' if 'DIRETO' in modo else 'MANUAL'

    if modo_key == 'DIRETO':
        linhas_agua = st.slider("Linhas de água", 10, 15, 12)
        n_seeds     = st.slider("Seeds do GA", 1, 3, 1,
                                help="Cada seed é uma execução independente. Mais seeds = melhor resultado, mais tempo.")

        st.subheader("☁️ Modo Community Cloud")
        cloud_mode = st.toggle(
            "Reduzir tamanho do GA",
            value=True,
            help="Ativado: GA rápido (~30s) para Community Cloud.\nDesativado: GA completo (~3-5 min) para servidor dedicado."
        )
        if cloud_mode:
            st.info("GA reduzido: 150 ind × 25 ger\n\nResultado pode ser subótimo — use servidor dedicado para produção.")
        else:
            st.warning("GA completo: 500 ind × 80 ger\n\nPode exceder o timeout do Community Cloud (60s).")
    else:
        st.info("A alocação é lida de `manual_consumers_config.py`.\n\nPara alterar, edite o arquivo e faça redeploy.")
        linhas_agua = None
        n_seeds     = 1
        cloud_mode  = False

    st.divider()
    executar = st.button("▶ Executar", type="primary", use_container_width=True,
                         disabled=(xlsx_file is None))
    if xlsx_file is None:
        st.caption("⬆ Carregue o Excel para habilitar.")

# ── Área principal ────────────────────────────────────────────────────────────
st.title("Otimização de Linhas de Proteção — FPSO")

if xlsx_file is None:
    # ── Landing page ──────────────────────────────────────────────────────────
    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("""
        **📂 1. Carregue o Excel**
        Faça upload do arquivo estruturado da plataforma (Marlim, Tupi ou outra).
        O Excel deve conter as abas: `Modules_Areas`, `Coamings_Areas`, `Hydrants`,
        `Water_Monitors`, `Water_Diameters`, `Foam_Diameters`, `Parameters`.
        """)
    with col2:
        st.markdown("""
        **⚙️ 2. Configure o modo**
        - **DIRETO**: o Algoritmo Genético aloca módulos e coamings às linhas,
          minimizando o peso total de tubulação (kg).
        - **MANUAL**: alocação prescrita por engenharia via `manual_consumers_config.py`.
        """)
    with col3:
        st.markdown("""
        **📊 3. Analise os resultados**
        - Peso total por componente (linhas + ramais)
        - Diâmetros por linha com análise de monotonicidade
        - Layout das linhas na plataforma
        - Download do Excel detalhado
        """)
    st.divider()
    st.markdown("""
    #### Estrutura de abas obrigatórias no Excel

    | Aba | Conteúdo |
    |---|---|
    | `Parameters` | Parâmetros escalares: `platform_info`, `water_lines_quantity`, `constant_HW`, etc. |
    | `Modules_Areas` | Geometria dos módulos (limites X/Y, comprimento) |
    | `Modules_Demand` | Demanda mínima de firewater por módulo (m³/h, diâmetro nominal) |
    | `Modules_Fuel` | Flag de presença de combustível por módulo |
    | `Modules_Distribution` | Matriz de disposição dos módulos por deck |
    | `Coamings_Areas` | Geometria dos coamings (diques) |
    | `Coamings_Demand` | Demanda de firewater e espuma por coaming |
    | `Coamings_Distribution` | Matriz de disposição dos coamings por lado |
    | `Hydrants` | Quantidade de hidrantes por zona |
    | `Water_Monitors` | Vazão dos monitores (main deck, offloading, helideck, hydrant) |
    | `Water_Diameters` | Tabela de diâmetros nominais com peso (kg/m) |
    | `Foam_Diameters` | Tabela de diâmetros para linhas de espuma |
    """)
    st.stop()

# ── Execução ──────────────────────────────────────────────────────────────────
if executar:
    _figs.clear()

    # Salva Excel em arquivo temporário
    xlsx_path = os.path.join(TMP, xlsx_file.name)
    with open(xlsx_path, 'wb') as f:
        f.write(xlsx_file.read())

    # Configura GA_CONFIG
    if modo_key == 'DIRETO':
        if cloud_mode:
            algo.GA_CONFIG = {'water_pop':150,'water_gen':25,
                              'foam_pop':150, 'foam_gen':15,
                              'pos_pop':100,  'pos_gen':30}
        else:
            algo.GA_CONFIG = {'water_pop':500,'water_gen':80,
                              'foam_pop':500, 'foam_gen':40,
                              'pos_pop':300,  'pos_gen':80}

    # Patch globals
    algo.XLSX_PATH            = xlsx_path
    algo.MODO_EXECUCAO        = modo_key
    algo.LINHAS_AGUA_OVERRIDE = [linhas_agua] if linhas_agua else None
    algo.N_SEEDS_GA           = n_seeds

    # Importa manual_consumers se disponível
    try:
        from manual_consumers_config import MANUAL_CONSUMERS, MANUAL_WATER_LINES
        algo.MANUAL_CONSUMERS   = MANUAL_CONSUMERS
        algo.MANUAL_WATER_LINES = MANUAL_WATER_LINES
    except ImportError:
        algo.MANUAL_CONSUMERS   = {}
        algo.MANUAL_WATER_LINES = 12

    resultado = {}
    erro      = None

    with st.status("⚙️ Executando otimização...", expanded=True) as status:
        try:
            t0   = time.time()
            data = algo.load_data_from_excel(xlsx_path)
            st.write("✅ Excel carregado")

            modules_areas_base = data['modules_areas']
            water_lines_list   = algo.LINHAS_AGUA_OVERRIDE or data['water_lines_quantity']
            plataforma_tag     = os.path.splitext(xlsx_file.name)[0].split('_')[0].upper()

            if modo_key == 'MANUAL':
                # ── MANUAL ────────────────────────────────────────────────────
                xlsx_saida = f'detalhamento_manual_{plataforma_tag}.xlsx'
                algo.PASTA_SAIDA = RES_DIR
                df_mc = algo.executar_modo_manual(data, xlsx_saida)
                resultado['modo']       = 'MANUAL'
                resultado['df_mc']      = df_mc
                resultado['xlsx_saida'] = os.path.join(RES_DIR, xlsx_saida)
                st.write("✅ Modo MANUAL concluído")

            else:
                # ── DIRETO ────────────────────────────────────────────────────
                store   = algo.GAResultsStore()
                results = {}

                for wl in water_lines_list:
                    st.write(f"🔧 Processando {wl} linhas...")
                    ma, fp, wp = algo._prep_posicoes(wl, modules_areas_base, data)
                    if fp is None:
                        st.warning(f"Sem solução viável para {wl} linhas.")
                        continue
                    st.write(f"   ✅ Posicionamento concluído")

                    foam_dist, df_dem, valid_lines = algo._calc_dist(wl, ma, fp, wp, data)
                    st.write(f"   ✅ Distribuições calculadas")

                    fc, costs = algo._rodar_ga(wl, ma, wp, df_dem, valid_lines, data, store)
                    if fc is None:
                        st.warning(f"GA sem solução viável para {wl} linhas.")
                        continue
                    st.write(f"   ✅ GA concluído — {sum(c < np.inf for c in costs)} seed(s) viáveis")

                    post = algo.postprocess(
                        fc, df_dem, ma, data['coamings_areas'],
                        data['modules_df_demand'], data['coamings_df_demand'],
                        wp, data['water_monitors_flow'], data['water_diameters'],
                        data['constant_HW'], data['dimensioning_length_m'],
                        data['min_pressure'], data['max_pressure'],
                        data['velocity_m_s'], data['convertion_rate'])
                    algo._atualizar_store(store, wl, post, df_dem, wp, fp, foam_dist, ma)
                    results[wl] = {'post': post, 'df_dem': df_dem, 'wp': wp, 'ma': ma}
                    st.write(f"   ✅ Peso = {post['total_weight']/1000:.3f} ton")

                xlsx_saida = f'detalhamento_direto_{plataforma_tag}.xlsx'
                algo.exportar_excel(
                    store, modules_areas_base, data['coamings_areas'],
                    data['modules_df_demand'], data['coamings_df_demand'],
                    data['water_diameters'], xlsx_nome=xlsx_saida)

                resultado['modo']       = 'DIRETO'
                resultado['store']      = store
                resultado['results']    = results
                resultado['data']       = data
                resultado['xlsx_saida'] = os.path.join(RES_DIR, xlsx_saida)
                resultado['plataforma'] = plataforma_tag

            resultado['tempo'] = time.time() - t0
            resultado['figs']  = dict(_figs)
            st.session_state['resultado'] = resultado
            status.update(label=f"✅ Concluído em {resultado['tempo']:.1f} s", state="complete")

        except Exception as e:
            erro = traceback.format_exc()
            status.update(label="❌ Erro durante a execução", state="error")

    if erro:
        st.error("Erro durante a execução:")
        st.code(erro)
        st.stop()

# ── Exibe resultados ──────────────────────────────────────────────────────────
if 'resultado' not in st.session_state:
    st.stop()

res  = st.session_state['resultado']
modo_res = res['modo']

# ── KPIs de topo ─────────────────────────────────────────────────────────────
st.divider()

if modo_res == 'DIRETO':
    store   = res['store']
    results = res['results']
    data    = res['data']
    summ    = store.summary_table()

    col1, col2, col3, col4 = st.columns(4)
    best_cfg = store.configs[0] if store.configs else {}
    w_tot  = best_cfg.get('total_weight', 0) / 1000
    w_lin  = best_cfg.get('lines_weight', 0) / 1000
    w_ram  = best_cfg.get('adv_weight',   0) / 1000
    mono   = best_cfg.get('mono_params',  {})
    mr     = mono.get('mono_ratio', None)
    nb     = mono.get('n_breaks', None)

    with col1: kpi("Peso total (ton)", f"{w_tot:.3f}", f"Linhas: {w_lin:.2f} + Ramais: {w_ram:.2f}", "ok" if w_tot < 150 else "warn")
    with col2: kpi("Seeds viáveis", f"{len(best_cfg.get('viable_weights',[]))}/{algo.N_SEEDS_GA}")
    with col3: kpi("Melhor peso GA (ton)", f"{best_cfg.get('best_weight_kg',0)/1000:.3f}",
                   "Ramais mód/coam + linhas princ.", "ok")
    with col4: kpi("Monotonicidade",
                   f"{mr:.4f}" if mr is not None else "—",
                   f"Quebras: {nb}" if nb is not None else "",
                   "ok" if nb == 0 else "warn")

else:  # MANUAL
    df_mc = res['df_mc']
    dm    = df_mc['nominal diameter (in)'].values
    dd    = np.diff(dm)
    n_brk = int(np.sum(dd < 0))
    mr    = float(np.sum(dd >= 0)) / len(dd) if len(dd) else 1.0
    w_tot = df_mc['Peso Total Linha (ton)'].sum() if 'Peso Total Linha (ton)' in df_mc.columns else 0

    col1, col2, col3, col4 = st.columns(4)
    with col1: kpi("Linhas configuradas", str(len(df_mc)))
    with col2: kpi("Hidrantes totais", str(int(df_mc['hydrants'].sum())), "referência: 286")
    with col3: kpi("Monotonicidade", f"{mr:.4f}", f"Quebras: {n_brk}",
                   "ok" if n_brk == 0 else "err")
    with col4: kpi("Peso total (ton)", f"{w_tot:.3f}" if w_tot else "—")

# ── Tabs de resultados ────────────────────────────────────────────────────────
tabs = st.tabs(["📊 Resultados", "📐 Diâmetros", "🗺️ Layout", "⬇ Exportar"])

# ══ TAB 1 — Resultados ═══════════════════════════════════════════════════════
with tabs[0]:
    if modo_res == 'DIRETO':
        st.subheader("Resumo comparativo de configurações")
        st.dataframe(summ, use_container_width=True)

        for wl, r in results.items():
            with st.expander(f"📋 {wl} linhas — consumidores por linha", expanded=len(results)==1):
                fc = r['post']['df_consumers']
                # Converte listas para strings para exibição
                fc_show = fc.copy()
                for col in ['consumer modules','consumer coamings']:
                    if col in fc_show.columns:
                        fc_show[col] = fc_show[col].apply(lambda x: ', '.join(x) if isinstance(x, list) else x)
                st.dataframe(fc_show, use_container_width=True)

        # Análise de pressão
        st.subheader("🚒 Análise de pressão — casos críticos")
        try:
            with io.StringIO() as buf:
                import contextlib
                old_stdout = sys.stdout
                sys.stdout = buf
                algo.analisar_pressao(
                    store, modules_areas_base if 'modules_areas_base' in dir() else data['modules_areas'],
                    data['water_monitors_flow'],
                    data['modules_df_demand'],
                    data['water_diameters'])
                sys.stdout = old_stdout
                txt = buf.getvalue()
            st.code(txt)
        except Exception:
            st.info("Análise de pressão disponível após execução completa.")

    else:  # MANUAL
        st.subheader("Alocação de consumidores")
        df_show = res['df_mc'].copy()
        for col in ['consumer modules','consumer coamings']:
            if col in df_show.columns:
                df_show[col] = df_show[col].apply(lambda x: ', '.join(x) if isinstance(x, list) else str(x))
        st.dataframe(df_show, use_container_width=True)

# ══ TAB 2 — Diâmetros ════════════════════════════════════════════════════════
with tabs[1]:
    st.subheader("Diâmetros das linhas principais e monotonicidade")

    if modo_res == 'DIRETO' and results:
        for wl, r in results.items():
            fc    = r['post']['df_consumers']
            diam_l= list(fc['nominal diameter (in)'].values)
            labels= list(fc['lines'].values)
            mono  = algo.calcular_monotonicidade(diam_l, label=f'{wl} Linhas')
            fig   = algo.plotar_diametros_linhas(diam_l, labels,
                        titulo=f'Diâmetros — {wl} Linhas',
                        nome_arquivo=f'diam_{wl}L', mono_params=mono)
            st.pyplot(fig, use_container_width=True)
            plt.close(fig)

            col1, col2, col3, col4 = st.columns(4)
            col1.metric("mono_ratio",   f"{mono['mono_ratio']:.4f}")
            col2.metric("Quebras",      mono['n_breaks'])
            col3.metric("Queda total",  f"{mono['total_drop']:.1f}\"")
            col4.metric("Maior queda",  f"{mono['max_drop']:.1f}\"")
            st.divider()

    elif modo_res == 'MANUAL':
        df_mc  = res['df_mc']
        diam_l = list(df_mc['nominal diameter (in)'].values)
        labels = list(df_mc['lines'].values)
        mono   = algo.calcular_monotonicidade(diam_l, label='MANUAL')
        fig    = algo.plotar_diametros_linhas(diam_l, labels,
                    titulo='Diâmetros — MANUAL',
                    nome_arquivo='diam_manual', mono_params=mono)
        st.pyplot(fig, use_container_width=True)
        plt.close(fig)

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("mono_ratio",  f"{mono['mono_ratio']:.4f}")
        col2.metric("Quebras",     mono['n_breaks'])
        col3.metric("Queda total", f"{mono['total_drop']:.1f}\"")
        col4.metric("Maior queda", f"{mono['max_drop']:.1f}\"")

        if mono['n_breaks'] > 0:
            st.warning(
                f"Quebras detectadas em: {', '.join([f'L{i+1}→L{i+2}' for i in mono['breaks_idx']])}. "
                "A solução manual tem diâmetros fora de sequência nessas linhas, o que pode indicar "
                "que a alocação de consumidores gera vazões não-crescentes nesses trechos.")

# ══ TAB 3 — Layout ═══════════════════════════════════════════════════════════
with tabs[2]:
    st.subheader("Layout das linhas na plataforma")
    figs_layout = {k: v for k, v in res['figs'].items() if k.startswith('layout')}
    if figs_layout:
        for nome, fig in figs_layout.items():
            st.pyplot(fig, use_container_width=True)
    else:
        st.info("O gráfico de layout é gerado apenas no modo DIRETO (requer o posicionamento pelo GA).")

# ══ TAB 4 — Exportar ═════════════════════════════════════════════════════════
with tabs[3]:
    st.subheader("Download dos resultados")

    # Excel principal
    xlsx_path = res.get('xlsx_saida', '')
    if xlsx_path and os.path.exists(xlsx_path):
        with open(xlsx_path, 'rb') as f:
            xlsx_bytes = f.read()
        st.download_button(
            label="⬇ Excel detalhado",
            data=xlsx_bytes,
            file_name=os.path.basename(xlsx_path),
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )

    # Figuras individuais
    if res['figs']:
        st.divider()
        st.markdown("**Gráficos individuais (PNG)**")
        cols = st.columns(min(len(res['figs']), 3))
        for i, (nome, fig) in enumerate(res['figs'].items()):
            with cols[i % 3]:
                img_bytes = fig_to_bytes(fig)
                st.download_button(
                    label=f"⬇ {nome}.png",
                    data=img_bytes,
                    file_name=f"{nome}.png",
                    mime="image/png",
                    use_container_width=True,
                )

    # Resumo CSV (para MANUAL)
    if modo_res == 'MANUAL':
        st.divider()
        df_mc = res['df_mc']
        df_show = df_mc.copy()
        for col in ['consumer modules','consumer coamings']:
            if col in df_show.columns:
                df_show[col] = df_show[col].apply(lambda x: ', '.join(x) if isinstance(x, list) else str(x))
        csv = df_show.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="⬇ Alocação Manual (CSV)",
            data=csv,
            file_name="alocacao_manual.csv",
            mime="text/csv",
            use_container_width=True,
        )

# ── Footer ────────────────────────────────────────────────────────────────────
st.divider()
st.caption(
    f"🕐 Execução em {res.get('tempo',0):.1f} s  |  "
    f"Modo: {modo_res}  |  "
    "Otimização de Linhas de Proteção Contra Incêndio — FPSO/Plataforma  |  "
    "PUC-Rio / ECOA — PETROBRAS"
)
