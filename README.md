# Otimização de Linhas de Proteção Contra Incêndio — FPSO

Interface Streamlit para o algoritmo de otimização de linhas de firewater em plataformas offshore.

## Arquivos do projeto

```
app_otimizacao.py                  ← Interface Streamlit (este app)
otimizacao_linhas_v3_pycharm.py    ← Algoritmo principal (GA + hidráulica)
manual_consumers_config.py         ← Alocação manual de consumidores (MARLIM)
marlim_data_estruturado.xlsx       ← Dados de entrada — Marlim
tupi_data_estruturado.xlsx         ← Template de dados — Tupi (preencher)
requirements.txt                   ← Dependências Python
.streamlit/config.toml             ← Configurações do Streamlit
```

## Deploy no Streamlit Community Cloud

1. **Crie um repositório no GitHub** com todos os arquivos acima.

2. **Acesse** [share.streamlit.io](https://share.streamlit.io) e faça login com sua conta GitHub.

3. **Clique em "New app"** e configure:
   - Repository: `seu-usuario/seu-repo`
   - Branch: `main`
   - Main file path: `app_otimizacao.py`

4. **Clique em "Deploy"** — o app estará disponível em:
   ```
   https://seu-usuario-seu-repo-app-otimizacao.streamlit.app
   ```

## Uso do app

### Modo DIRETO (GA)
1. Faça upload do Excel da plataforma (Marlim ou Tupi)
2. Selecione **DIRETO**
3. Configure: número de linhas de água e seeds do GA
4. Ative **"Reduzir tamanho do GA"** para Community Cloud (mais rápido, menos preciso)
5. Clique **Executar**

### Modo MANUAL
1. Edite `manual_consumers_config.py` com a alocação desejada
2. Faça commit no GitHub (o app usa a versão do repositório)
3. Faça upload do Excel e selecione **MANUAL**
4. Clique **Executar**

## Limitações do Community Cloud

| Recurso | Community Cloud | Servidor dedicado |
|---|---|---|
| CPU | Compartilhada (~1 core) | Dedicada |
| RAM | 1 GB | Ilimitado |
| Timeout por request | ~60 s | Ilimitado |
| GA completo (500×80) | ❌ Timeout | ✅ |
| GA reduzido (150×25) | ✅ ~30 s | ✅ |
| Dados sensíveis | ⚠ Público | ✅ Privado |

Para produção com dados reais da Petrobras, recomenda-se servidor interno com acesso via VPN.

## Configuração do GA

O tamanho do GA é controlado pela variável `GA_CONFIG` em `otimizacao_linhas_v3_pycharm.py`:

```python
# Valores padrão (PyCharm local)
GA_CONFIG = {
    'water_pop': 500, 'water_gen': 80,   # WaterDistribution
    'foam_pop':  500, 'foam_gen': 40,    # FoamDistribution
    'pos_pop':   300, 'pos_gen': 80,     # LinesPosition
}

# O app Streamlit substitui automaticamente para:
GA_CONFIG = {
    'water_pop': 150, 'water_gen': 25,
    'foam_pop':  150, 'foam_gen': 15,
    'pos_pop':   100, 'pos_gen': 30,
}
```

## Dependências

```bash
pip install streamlit deap numpy pandas matplotlib openpyxl
```

## Execução local

```bash
streamlit run app_otimizacao.py
```

O navegador abre automaticamente em `http://localhost:8501`.
