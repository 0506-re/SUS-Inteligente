"""
Pipeline completo — SUS+ Inteligente

Roda as 3 camadas em sequência. Cada camada também pode ser chamada
isoladamente (útil se só quiser re-rodar uma parte específica).

Como rodar:
    pip install pysus requests pandas pyarrow duckdb scikit-learn
    python pipeline_completo.py

Estrutura de saída:
    data/bronze/   -> dados brutos, como vieram de cada fonte
    data/silver/   -> dados tratados, tipados, com chaves de junção prontas
    data/gold/     -> indicadores agregados, prontos para dashboard/modelo

Decisões e limitações conhecidas (documentadas ao longo do código):
    - SIH: só 4 dos 12 meses de 2024 disponíveis na fonte usada pelo
      pysus (fev, jun, ago, dez) — limitação da fonte, não do pipeline.
    - CNES (API): amostra de 300 estabelecimentos (paginação) — usado só
      como enriquecimento (nome/endereço), não como lista completa.
    - Leitos: cobertura completa de SP — fonte principal de capacidade.
    - UF_ZI (SIH) é código de MUNICÍPIO (6 dígitos), não de UF — usar
      os 2 primeiros dígitos para identificar a UF.
"""

import os
import json
import glob as globmod
import requests
import duckdb
import pandas as pd


UF = "SP"
ANO = 2024
MESES = [2, 6, 8, 12]  # meses confirmados como disponíveis na fonte do SIH

BRONZE_DIR = "data/bronze"
SILVER_DIR = "data/silver"
GOLD_DIR = "data/gold"
for d in [f"{BRONZE_DIR}/sih", f"{BRONZE_DIR}/cnes", f"{BRONZE_DIR}/leitos",
          f"{BRONZE_DIR}/auxiliares", SILVER_DIR, GOLD_DIR]:
    os.makedirs(d, exist_ok=True)

# Mapeamento oficial IBGE de UF -> código numérico
CODIGO_UF = {
    "RO": 11, "AC": 12, "AM": 13, "RR": 14, "PA": 15, "AP": 16, "TO": 17,
    "MA": 21, "PI": 22, "CE": 23, "RN": 24, "PB": 25, "PE": 26, "AL": 27,
    "SE": 28, "BA": 29, "MG": 31, "ES": 32, "RJ": 33, "SP": 35, "PR": 41,
    "SC": 42, "RS": 43, "MS": 50, "MT": 51, "GO": 52, "DF": 53,
}

LEITOS_URL = "https://s3.sa-east-1.amazonaws.com/ckan.saude.gov.br/Leitos_SUS/Leitos_2024.csv"



# CAMADA BRONZE — ingestão bruta de cada fonte

def bronze_sih():
    """SIH/SUS (grupo RD — internações), baixado mês a mês e filtrado
    por UF/competência direto na consulta (não confiamos no caminho de
    cache do pysus, que mistura grupos e execuções anteriores)."""
    from pysus import sih

    aa = str(ANO)[2:]
    arquivos_encontrados = []
    for m in MESES:
        padrao_nome = f"RD{UF}{aa}{m:02d}.parquet"
        print(f"[bronze/sih] baixando {UF} {ANO}-{m:02d} ...")
        sih(state=UF, year=ANO, month=m)
        achados = globmod.glob(os.path.expanduser(f"~/**/{padrao_nome}"), recursive=True)
        if not achados:
            print(f"  [AVISO] {padrao_nome} não disponível na fonte — pulando")
            continue
        arquivos_encontrados.append(achados[0])
        print(f"  OK: {achados[0]}")

    if not arquivos_encontrados:
        raise FileNotFoundError("Nenhum mês do SIH disponível para o recorte configurado.")

    colunas = ["UF_ZI", "ANO_CMPT", "MES_CMPT", "MUNIC_RES", "MUNIC_MOV",
               "DT_INTER", "DT_SAIDA", "DIAS_PERM", "VAL_TOT", "IDADE",
               "SEXO", "DIAG_PRINC", "CNES"]
    lista_arquivos_sql = ", ".join(f"'{p}'" for p in arquivos_encontrados)
    colunas_sql = ", ".join(colunas)
    out_path = f"{BRONZE_DIR}/sih/sih_{UF}_{ANO}.parquet"
    codigo_uf = str(CODIGO_UF[UF])
    meses_sql = ", ".join(f"'{m:02d}'" for m in MESES)

    con = duckdb.connect()
    con.execute(f"""
        COPY (
            SELECT {colunas_sql}
            FROM read_parquet([{lista_arquivos_sql}], union_by_name=True)
            WHERE SUBSTR(UF_ZI, 1, 2) = '{codigo_uf}'
              AND ANO_CMPT = '{ANO}'
              AND MES_CMPT IN ({meses_sql})
        ) TO '{out_path}' (FORMAT PARQUET)
    """)
    total = con.sql(f"SELECT COUNT(*) FROM read_parquet('{out_path}')").fetchone()[0]
    con.close()
    print(f"[bronze/sih] OK — {total} registros salvos em {out_path}\n")


def bronze_cnes(meta_registros=300):
    """CNES via API pública — amostra (a API não pagina corretamente, então
    filtramos localmente pelo campo codigo_uf que vem em cada registro)."""
    url = "https://apidadosabertos.saude.gov.br/cnes/estabelecimentos"
    codigo_uf_alvo = CODIGO_UF[UF]
    registros_da_uf, total_varrido, offset_atual = [], 0, 0
    assinatura_anterior = None

    print(f"[bronze/cnes] consultando API, filtrando localmente por UF={UF} ...")
    for _ in range(100):
        params = {"uf": UF, "codigo_uf": codigo_uf_alvo, "limit": 200, "offset": offset_atual}
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        registros = data.get("estabelecimentos", data) if isinstance(data, dict) else data
        if not registros:
            break
        assinatura_atual = json.dumps(registros[0], sort_keys=True)
        if assinatura_atual == assinatura_anterior:
            break
        assinatura_anterior = assinatura_atual

        total_varrido += len(registros)
        registros_da_uf.extend([r for r in registros if r.get("codigo_uf") == codigo_uf_alvo])
        offset_atual += len(registros)
        if len(registros_da_uf) >= meta_registros:
            break

    out_json = f"{BRONZE_DIR}/cnes/cnes_{UF}_raw.json"
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(registros_da_uf, f, ensure_ascii=False, indent=2)
    df = pd.json_normalize(registros_da_uf)
    out_parquet = f"{BRONZE_DIR}/cnes/cnes_{UF}.parquet"
    df.to_parquet(out_parquet, index=False)
    print(f"[bronze/cnes] OK — {len(df)} estabelecimentos salvos em {out_parquet}\n")


def bronze_leitos():
    """Dataset nacional de Leitos (Latin-1 -> UTF-8 em streaming, depois
    filtrado por UF/competência) — cobertura completa para a UF."""
    caminho_utf8 = f"{BRONZE_DIR}/leitos/_leitos_{ANO}_utf8_raw.csv"
    if not os.path.exists(caminho_utf8):
        print(f"[bronze/leitos] baixando Leitos {ANO} (Latin-1 -> UTF-8) ...")
        resp = requests.get(LEITOS_URL, stream=True, timeout=120)
        resp.raise_for_status()
        with open(caminho_utf8, "w", encoding="utf-8", newline="") as f_out:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                f_out.write(chunk.decode("latin-1"))
    else:
        print(f"[bronze/leitos] usando cache: {caminho_utf8}")

    comp_sql = ", ".join(str(ANO * 100 + m) for m in MESES)
    out_path = f"{BRONZE_DIR}/leitos/leitos_{UF}_{ANO}.parquet"
    con = duckdb.connect()
    con.execute(f"""
        COPY (
            SELECT COMP, UF, MUNICIPIO, CNES, NOME_ESTABELECIMENTO,
                   LEITOS_EXISTENTES, LEITOS_SUS, UTI_TOTAL_EXIST, UTI_TOTAL_SUS
            FROM read_csv_auto('{caminho_utf8}')
            WHERE UF = '{UF}' AND COMP IN ({comp_sql})
        ) TO '{out_path}' (FORMAT PARQUET)
    """)
    total = con.sql(f"SELECT COUNT(*) FROM read_parquet('{out_path}')").fetchone()[0]
    con.close()
    print(f"[bronze/leitos] OK — {total} registros salvos em {out_path}\n")



# CAMADA SILVER — limpeza de tipos e chaves de junção

def silver_transformar():
    con = duckdb.connect()

    print("[silver] internações ...")
    con.execute(f"""
        COPY (
            SELECT
                TRY_CAST(CNES AS INTEGER) AS cnes,
                TRY_CAST(MUNIC_RES AS INTEGER) AS municipio_residencia,
                TRY_CAST(MUNIC_MOV AS INTEGER) AS municipio_estabelecimento,
                TRY_CAST(strptime(DT_INTER, '%Y%m%d') AS DATE) AS data_internacao,
                TRY_CAST(strptime(DT_SAIDA, '%Y%m%d') AS DATE) AS data_saida,
                TRY_CAST(DIAS_PERM AS INTEGER) AS dias_permanencia,
                TRY_CAST(VAL_TOT AS DOUBLE) AS valor_total,
                TRY_CAST(IDADE AS INTEGER) AS idade,
                CASE SEXO WHEN '1' THEN 'Masculino' WHEN '3' THEN 'Feminino' ELSE 'Ignorado' END AS sexo,
                DIAG_PRINC AS diagnostico_principal,
                ANO_CMPT AS ano_competencia,
                MES_CMPT AS mes_competencia
            FROM read_parquet('{BRONZE_DIR}/sih/sih_{UF}_{ANO}.parquet')
            WHERE TRY_CAST(DIAS_PERM AS INTEGER) >= 0 AND TRY_CAST(VAL_TOT AS DOUBLE) >= 0
        ) TO '{SILVER_DIR}/internacoes.parquet' (FORMAT PARQUET)
    """)

    print("[silver] capacidade por estabelecimento ...")
    con.execute(f"""
        COPY (
            SELECT
                TRY_CAST(CNES AS INTEGER) AS cnes,
                ANY_VALUE(NOME_ESTABELECIMENTO) AS nome_estabelecimento,
                ANY_VALUE(MUNICIPIO) AS municipio_nome,
                ROUND(AVG(LEITOS_EXISTENTES)) AS leitos_existentes_media,
                ROUND(AVG(LEITOS_SUS)) AS leitos_sus_media,
                ROUND(AVG(UTI_TOTAL_EXIST)) AS uti_existentes_media,
                ROUND(AVG(UTI_TOTAL_SUS)) AS uti_sus_media,
                COUNT(*) AS meses_com_dado
            FROM read_parquet('{BRONZE_DIR}/leitos/leitos_{UF}_{ANO}.parquet')
            GROUP BY TRY_CAST(CNES AS INTEGER)
        ) TO '{SILVER_DIR}/capacidade_estabelecimento.parquet' (FORMAT PARQUET)
    """)

    print("[silver] estabelecimentos enriquecidos (CNES/API) ...")
    con.execute(f"""
        COPY (
            SELECT
                codigo_cnes AS cnes, nome_fantasia, codigo_municipio AS municipio_codigo,
                bairro_estabelecimento AS bairro,
                estabelecimento_possui_atendimento_hospitalar AS possui_hospitalar,
                estabelecimento_possui_centro_cirurgico AS possui_centro_cirurgico,
                latitude_estabelecimento_decimo_grau AS latitude,
                longitude_estabelecimento_decimo_grau AS longitude
            FROM read_parquet('{BRONZE_DIR}/cnes/cnes_{UF}.parquet')
        ) TO '{SILVER_DIR}/estabelecimentos_enriquecido.parquet' (FORMAT PARQUET)
    """)

    print("[silver] crosswalk CNES -> município (derivado do SIH) ...")
    con.execute(f"""
        COPY (
            SELECT DISTINCT cnes, municipio_estabelecimento AS municipio_codigo
            FROM read_parquet('{SILVER_DIR}/internacoes.parquet')
            WHERE cnes IS NOT NULL AND municipio_estabelecimento IS NOT NULL
        ) TO '{SILVER_DIR}/crosswalk_cnes_municipio.parquet' (FORMAT PARQUET)
    """)
    con.close()
    print("[silver] concluído\n")


# CAMADA GOLD — indicadores agregados

def gold_indicadores():
    con = duckdb.connect()

    print("[gold] sazonalidade mensal ...")
    con.execute(f"""
        COPY (
            SELECT mes_competencia, COUNT(*) AS total_internacoes,
                   ROUND(AVG(dias_permanencia), 1) AS permanencia_media_dias,
                   ROUND(AVG(valor_total), 2) AS valor_medio_aih,
                   SUM(valor_total) AS valor_total_periodo
            FROM read_parquet('{SILVER_DIR}/internacoes.parquet')
            GROUP BY mes_competencia ORDER BY mes_competencia
        ) TO '{GOLD_DIR}/sazonalidade_mensal.parquet' (FORMAT PARQUET)
    """)

    print("[gold] volume por município ...")
    con.execute(f"""
        COPY (
            SELECT municipio_estabelecimento AS municipio_codigo,
                   COUNT(*) AS total_internacoes,
                   ROUND(AVG(dias_permanencia), 1) AS permanencia_media_dias,
                   ROUND(AVG(idade), 1) AS idade_media,
                   ROUND(AVG(valor_total), 2) AS valor_medio_aih,
                   COUNT(DISTINCT cnes) AS estabelecimentos_distintos
            FROM read_parquet('{SILVER_DIR}/internacoes.parquet')
            WHERE municipio_estabelecimento IS NOT NULL
            GROUP BY municipio_estabelecimento
        ) TO '{GOLD_DIR}/volume_por_municipio.parquet' (FORMAT PARQUET)
    """)

    print("[gold] capacidade por município ...")
    con.execute(f"""
        COPY (
            SELECT cw.municipio_codigo,
                   SUM(cap.leitos_existentes_media) AS leitos_existentes_total,
                   SUM(cap.leitos_sus_media) AS leitos_sus_total,
                   SUM(cap.uti_existentes_media) AS uti_existentes_total,
                   COUNT(DISTINCT cap.cnes) AS estabelecimentos_com_leito
            FROM read_parquet('{SILVER_DIR}/capacidade_estabelecimento.parquet') cap
            JOIN read_parquet('{SILVER_DIR}/crosswalk_cnes_municipio.parquet') cw ON cap.cnes = cw.cnes
            GROUP BY cw.municipio_codigo
        ) TO '{GOLD_DIR}/capacidade_por_municipio.parquet' (FORMAT PARQUET)
    """)

    print("[gold] indicador de capacidade (ranking de pressão assistencial) ...")
    con.execute(f"""
        COPY (
            SELECT v.municipio_codigo, v.total_internacoes, v.permanencia_media_dias,
                   v.estabelecimentos_distintos, c.leitos_existentes_total, c.leitos_sus_total,
                   ROUND(v.total_internacoes / NULLIF(c.leitos_existentes_total, 0), 2) AS internacoes_por_leito
            FROM read_parquet('{GOLD_DIR}/volume_por_municipio.parquet') v
            LEFT JOIN read_parquet('{GOLD_DIR}/capacidade_por_municipio.parquet') c
              ON v.municipio_codigo = c.municipio_codigo
            ORDER BY internacoes_por_leito DESC NULLS LAST
        ) TO '{GOLD_DIR}/indicador_capacidade_municipio.parquet' (FORMAT PARQUET)
    """)
    con.close()
    print("[gold] concluído\n")


# =================================================================
if __name__ == "__main__":
    print("=" * 60)
    print("PIPELINE COMPLETO — SUS+ Inteligente (bronze -> silver -> gold)")
    print("=" * 60)

    print("\n--- BRONZE ---")
    bronze_sih()
    bronze_cnes()
    bronze_leitos()

    print("--- SILVER ---")
    silver_transformar()

    print("--- GOLD ---")
    gold_indicadores()

    print("Pipeline completo. Rodem eda_modelagem.py em seguida para os")
    print("gráficos e modelos.")
