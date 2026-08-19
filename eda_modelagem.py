"""
EDA + Modelagem — SUS+ Inteligente

Gera os gráficos de EDA (sazonalidade, ranking, distribuição, correlação)
e os dois modelos analíticos combinados no plano: clusterização (padrões/
agrupamentos) + regressão (explicabilidade). Salva os PNGs prontos para
colar direto nos slides 9 e 10 do PPT.

Como rodar:
    pip install duckdb pandas matplotlib scikit-learn
    python eda_modelagem.py
"""

import os
import duckdb
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import train_test_split
from sklearn.metrics import r2_score, mean_absolute_error

GOLD_DIR = "data/gold"
SILVER_DIR = "data/silver"
OUT_DIR = "docs/eda"
os.makedirs(OUT_DIR, exist_ok=True)

con = duckdb.connect()
plt.rcParams["figure.dpi"] = 120


# 1) EDA — Sazonalidade

print("1) Gráfico de sazonalidade ...")
saz = con.sql(f"SELECT * FROM read_parquet('{GOLD_DIR}/sazonalidade_mensal.parquet') ORDER BY mes_competencia").df()
nomes_mes = {"02": "Fev", "06": "Jun", "08": "Ago", "12": "Dez"}
saz["mes_label"] = saz["mes_competencia"].map(nomes_mes)

fig, ax = plt.subplots(figsize=(7, 4))
ax.bar(saz["mes_label"], saz["total_internacoes"], color="#028090")
ax.set_title("Internações por mês — SP, 2024 (meses disponíveis)")
ax.set_ylabel("Total de internações")
for i, v in enumerate(saz["total_internacoes"]):
    ax.text(i, v + 2000, f"{v:,}".replace(",", "."), ha="center", fontsize=9)
plt.tight_layout()
plt.savefig(f"{OUT_DIR}/01_sazonalidade.png")
plt.close()
print(f"  salvo em {OUT_DIR}/01_sazonalidade.png")
print("  NOTA: só 4 meses não-consecutivos disponíveis na fonte — mencionem")
print("  isso no slide (limitação da fonte, não do pipeline).\n")


# 2) EDA — Ranking (top 15 municípios por pressão assistencial)

print("2) Gráfico de ranking ...")
rank = con.sql(f"""
    SELECT municipio_codigo, internacoes_por_leito, total_internacoes
    FROM read_parquet('{GOLD_DIR}/indicador_capacidade_municipio.parquet')
    WHERE internacoes_por_leito IS NOT NULL
    ORDER BY internacoes_por_leito DESC
    LIMIT 15
""").df()

fig, ax = plt.subplots(figsize=(7, 5))
ax.barh(rank["municipio_codigo"].astype(str), rank["internacoes_por_leito"], color="#00A896")
ax.invert_yaxis()
ax.set_xlabel("Internações por leito (proxy de pressão assistencial)")
ax.set_title("Top 15 municípios — maior pressão assistencial")
plt.tight_layout()
plt.savefig(f"{OUT_DIR}/02_ranking_municipios.png")
plt.close()
print(f"  salvo em {OUT_DIR}/02_ranking_municipios.png")
print("  NOTA: rótulos são código IBGE — quando o CSV de população entrar,")
print("  ele também traz nome do município, dá pra trocar o rótulo depois.\n")


# 3) EDA — Distribuição de permanência e outliers (longa permanência)

print("3) Distribuição de permanência hospitalar ...")
percentis = con.sql(f"""
    SELECT
        MIN(dias_permanencia) AS minimo,
        APPROX_QUANTILE(dias_permanencia, 0.5)  AS mediana,
        APPROX_QUANTILE(dias_permanencia, 0.9)  AS p90,
        APPROX_QUANTILE(dias_permanencia, 0.99) AS p99,
        MAX(dias_permanencia) AS maximo,
        COUNT(*) FILTER (WHERE dias_permanencia > 90) AS internacoes_longa_permanencia
    FROM read_parquet('{SILVER_DIR}/internacoes.parquet')
""").df()
print(percentis.to_string(index=False))

hist_data = con.sql(f"""
    SELECT LEAST(dias_permanencia, 60) AS dias_capado
    FROM read_parquet('{SILVER_DIR}/internacoes.parquet')
    USING SAMPLE 50000  -- amostra para o histograma, não precisa do 1M de linhas
""").df()

fig, ax = plt.subplots(figsize=(7, 4))
ax.hist(hist_data["dias_capado"], bins=30, color="#02C39A", edgecolor="white")
ax.set_title("Distribuição de permanência hospitalar (capado em 60 dias p/ visualização)")
ax.set_xlabel("Dias de permanência")
ax.set_ylabel("Frequência (amostra)")
plt.tight_layout()
plt.savefig(f"{OUT_DIR}/03_distribuicao_permanencia.png")
plt.close()
print(f"  salvo em {OUT_DIR}/03_distribuicao_permanencia.png")
print(f"  Outliers de longa permanência (>90 dias): {int(percentis['internacoes_longa_permanencia'][0])} "
      f"internações — provavelmente psiquiátricas/crônicas. Mencionem no slide.\n")


# 4) Base para modelagem — carrega indicador por município 

df = con.sql(f"SELECT * FROM read_parquet('{GOLD_DIR}/indicador_capacidade_municipio.parquet')").df()
df = df.dropna(subset=["leitos_existentes_total"]).copy()
print(f"Base para modelagem: {len(df)} municípios com capacidade identificada\n")


# 5) Clusterização — padrões/agrupamentos de municípios

print("5) Clusterização (K-Means, 3 perfis) ...")
features_cluster = ["total_internacoes", "permanencia_media_dias", "internacoes_por_leito"]
X = df[features_cluster].fillna(0)
X_scaled = StandardScaler().fit_transform(X)

kmeans = KMeans(n_clusters=3, random_state=42, n_init=10)
df["cluster"] = kmeans.fit_predict(X_scaled)

# nomeia os clusters pela pressão média (internacoes_por_leito) — do maior
# pro menor: Alta pressão / Estável / Capacidade ociosa
ordem_clusters = df.groupby("cluster")["internacoes_por_leito"].mean().sort_values(ascending=False).index
nomes_cluster = {ordem_clusters[0]: "Alta pressão", ordem_clusters[1]: "Estável", ordem_clusters[2]: "Capacidade ociosa"}
df["perfil"] = df["cluster"].map(nomes_cluster)

print(df.groupby("perfil")[features_cluster].mean().round(1))
print()
print(df["perfil"].value_counts())

fig, ax = plt.subplots(figsize=(7, 5))
cores = {"Alta pressão": "#D64545", "Estável": "#028090", "Capacidade ociosa": "#02C39A"}
for perfil, grupo in df.groupby("perfil"):
    ax.scatter(grupo["leitos_existentes_total"], grupo["total_internacoes"],
               label=perfil, color=cores[perfil], alpha=0.7, s=40)
ax.set_xlabel("Leitos existentes (total)")
ax.set_ylabel("Total de internações (4 meses)")
ax.set_title("Perfis de municípios — clusterização por pressão assistencial")
ax.legend()
plt.tight_layout()
plt.savefig(f"{OUT_DIR}/04_clusterizacao.png")
plt.close()
print(f"  salvo em {OUT_DIR}/04_clusterizacao.png\n")


# 6) Regressão + explicabilidade — o que mais pesa no volume de
#    internações de um município

print("6) Regressão (Random Forest) + explicabilidade ...")
features_reg = ["leitos_existentes_total", "leitos_sus_total", "estabelecimentos_distintos", "permanencia_media_dias"]
X_reg = df[features_reg].fillna(0)
y_reg = df["total_internacoes"]

X_train, X_test, y_train, y_test = train_test_split(X_reg, y_reg, test_size=0.2, random_state=42)
modelo = RandomForestRegressor(n_estimators=200, random_state=42, max_depth=6)
modelo.fit(X_train, y_train)
y_pred = modelo.predict(X_test)

print(f"  R² (teste): {r2_score(y_test, y_pred):.3f}")
print(f"  MAE (teste): {mean_absolute_error(y_test, y_pred):,.0f} internações\n")

importancias = pd.Series(modelo.feature_importances_, index=features_reg).sort_values(ascending=False)
print("Importância das variáveis (explicabilidade):")
print(importancias.round(3).to_string())

fig, ax = plt.subplots(figsize=(6, 4))
importancias.plot(kind="barh", ax=ax, color="#028090")
ax.invert_yaxis()
ax.set_title("O que mais influencia o volume de internações de um município")
ax.set_xlabel("Importância relativa")
plt.tight_layout()
plt.savefig(f"{OUT_DIR}/05_explicabilidade.png")
plt.close()
print(f"\n  salvo em {OUT_DIR}/05_explicabilidade.png")

# salva a base final com cluster para usar no dashboard
df.to_csv(f"{GOLD_DIR}/municipios_com_cluster.csv", index=False)
print(f"\nBase final com clusters salva em {GOLD_DIR}/municipios_com_cluster.csv")
print("Gráficos prontos em docs/eda/ — já podem colar nos slides 9 e 10.")