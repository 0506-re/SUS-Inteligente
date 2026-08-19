# SUS-Inteligente

Plataforma de triagem e gestão assistida por IA para apoiar a rede pública de saúde (SUS) — Enterprise Challenge FIAP x Oracle, 2026.

**Equipe (Grupo 51):** Guilherme Francisco (569145), Rafael Canto Xavier (572513), Renata Cristina de Oliveira (569564)

## O que este repositório contém

Pipeline de dados e modelagem analítica, dividido em 3 camadas:

- **Bronze** — ingestão bruta de 3 fontes públicas: SIH/SUS (internações), CNES (estabelecimentos) e Leitos (capacidade hospitalar)
- **Silver** — limpeza de tipos, padronização e chaves de junção entre as fontes
- **Gold** — indicadores agregados: sazonalidade, volume e permanência por município, capacidade e ranking de pressão assistencial

Em cima disso, um notebook de EDA + modelagem (clusterização de municípios por perfil de pressão assistencial + regressão com explicabilidade de variáveis).

## Como rodar

Recomendado: Google Colab (ambiente já testado). Também funciona local com Python 3.10+.

Depois:
No Colab, cada comando vai numa célula separada, com `!` na frente do `pip install`:
Depois de instalar, reinicie o runtime (`Runtime → Restart runtime`) antes de rodar o pipeline — pacotes novos só carregam depois do restart.

## Estrutura

## Limitações conhecidas da fonte de dados

- **SIH/SUS**: a fonte usada pela biblioteca `pysus` só tem 4 dos 12 meses de 2024 disponíveis para SP (fevereiro, junho, agosto, dezembro) — limitação da fonte, não do pipeline.
- **CNES (API)**: os dados de estabelecimento vêm de uma amostra de 300 registros (a API pública não pagina corretamente); usado apenas para enriquecimento (nome/endereço), não como lista exaustiva.
- **Leitos**: cobertura completa para SP — é a fonte de capacidade usada nos indicadores.
- O indicador "internações por leito" é um proxy relativo de pressão assistencial entre municípios, não uma taxa de ocupação real.