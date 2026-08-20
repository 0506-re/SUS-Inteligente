# SUS-Inteligente

Plataforma de triagem e gestão assistida por IA para apoiar a rede pública de saúde (SUS) — Enterprise Challenge FIAP x Oracle, 2026.

**Equipe (Grupo 51):** Guilherme Francisco (569145), Rafael Canto Xavier (572513), Renata Cristina de Oliveira (569564)

## O que este repositório contém

Pipeline de dados e modelagem analítica, dividido em 3 camadas:

* **Bronze** — ingestão bruta de 3 fontes públicas: SIH/SUS (internações), CNES (estabelecimentos) e Leitos (capacidade hospitalar)
* **Silver** — limpeza de tipos, padronização e chaves de junção entre as fontes
* **Gold** — indicadores agregados: sazonalidade, volume e permanência por município, capacidade e ranking de pressão assistencial

Em cima disso, um notebook de EDA + modelagem (clusterização de municípios por perfil de pressão assistencial + regressão com explicabilidade de variáveis).

### Camada de consulta em linguagem natural (Select AI)

Além do pipeline bronze/silver/gold (rodado localmente/Colab com DuckDB), os indicadores da camada **gold** são carregados no **Oracle Autonomous Database** como uma **external table**, atendendo ao requisito do desafio de uma fonte de dados lida diretamente como tabela pelo banco. Sobre essa tabela, usamos o **Select AI** da Oracle para permitir perguntas em linguagem natural (ex.: "quais os 5 municípios com maior volume de internações?").

> O uso de **Databricks** para ingestão está descrito na seção de arquitetura como evolução planejada — priorizamos o pipeline DuckDB (já testado) para garantir uma entrega funcional dentro do prazo, e o Databricks fica como próxima etapa caso haja tempo hábil.

## Como rodar

Recomendado: Google Colab (ambiente já testado). Também funciona local com Python 3.10+.

1. Clone o repositório:
   ```
   git clone https://github.com/0506-re/SUS-Inteligente.git
   ```
2. Instale as dependências:
   ```
   pip install -r requirements.txt
   ```
   No Colab, cada comando vai numa célula separada, com `!` na frente:
   ```
   !pip install -r requirements.txt
   ```
   Depois de instalar, reinicie o runtime (`Runtime → Restart runtime`) antes de rodar o pipeline — pacotes novos só carregam depois do restart.
3. Rode o pipeline de ingestão:
   ```
   python pipeline_completo_v3.py
   ```
4. Rode a EDA e a modelagem:
   ```
   python eda_modelagem.py
   ```

## Estrutura

```
SUS-Inteligente/
├── README.md
├── requirements.txt
├── pipeline_completo_v3.py       # bronze -> silver -> gold
├── eda_modelagem.py              # EDA + clusterização + regressão
├── data/
│   ├── bronze/
│   ├── silver/
│   └── gold/
└── docs/
    └── eda/                      # gráficos gerados (PNG)
```

## Limitações conhecidas da fonte de dados

* **SIH/SUS**: a fonte usada pela biblioteca `pysus` só tem 4 dos 12 meses de 2024 disponíveis para SP (fevereiro, junho, agosto, dezembro) — limitação da fonte, não do pipeline.
* **CNES (API)**: os dados de estabelecimento vêm de uma amostra de 300 registros (a API pública não pagina corretamente); usado apenas para enriquecimento (nome/endereço), não como lista exaustiva.
* **Leitos**: cobertura completa para SP — é a fonte de capacidade usada nos indicadores.
* **Suprimentos/insumos hospitalares**: a proposta original (Sprint 1) previa direcionar o atendimento também de acordo com a disponibilidade de recursos/suprimentos (ex.: materiais, medicamentos) de cada unidade. Após pesquisa, não foram encontrados dados públicos e estruturados sobre suprimentos hospitalares no SUS com granularidade suficiente para esse uso — por isso, essa dimensão não foi incorporada ao MVP da Sprint 2. O indicador de pressão assistencial usado hoje considera apenas leitos e volume de internações; suprimentos ficam como evolução futura caso uma fonte confiável seja identificada.
* O indicador "internações por leito" é um proxy relativo de pressão assistencial entre municípios, não uma taxa de ocupação real.
