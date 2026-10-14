# Painel Comercial — Produtos a Vencer (Grupo Pigatto)

Dashboard público, estático e **anonimizado** (sem nome/telefone/e-mail de
cliente) com os lotes a vencer/vencidos e as vendas dos últimos 12 meses,
publicado no GitHub Pages e atualizado automaticamente uma vez por dia via
GitHub Actions, puxando os dados direto da API do Omie.

> **Complementar aos e-mails de alerta.** Os rascunhos quinzenais de e-mail
> (90 dias e vencidos) continuam sendo gerados normalmente pela tarefa
> agendada do Claude — eles seguem como o alerta urgente que vai para a caixa
> de entrada. Este dashboard é a visão completa, detalhada e sempre
> atualizada, para quem quiser consultar a qualquer momento sem esperar o
> próximo e-mail. Os clientes candidatos a contatar por produto, com nome,
> telefone e e-mail, continuam só na planilha interna do Google Sheets — de
> propósito, não entram aqui por serem dados comerciais sensíveis.

## Estrutura do repositório

```
.
├── .github/workflows/update-dashboard.yml   # roda 1x por dia (e sob demanda)
├── scripts/
│   ├── fetch_omie_data.py                   # busca dados no Omie e gera docs/data.json
│   └── requirements.txt
└── docs/
    ├── index.html                           # o dashboard em si (HTML/CSS/JS puro, sem build)
    └── data.json                            # dados gerados pelo workflow (tem um exemplo aqui agora)
```

## Passo a passo para publicar

1. **Crie o repositório no GitHub** (pode ser público) e envie todo este
   conteúdo para ele (`git init`, `git add .`, `git commit`, `git remote add
   origin ...`, `git push`).

2. **Cadastre as credenciais do Omie como Secrets do repositório** — nunca
   deixe a chave em um arquivo versionado:
   - Vá em **Settings → Secrets and variables → Actions → New repository
     secret**.
   - Crie `OMIE_APP_KEY` com o App Key da integração "OMIE — Grupo Pigatto".
   - Crie `OMIE_APP_SECRET` com o App Secret correspondente.

3. **Habilite permissão de escrita para o GitHub Actions** (necessária para o
   workflow conseguir fazer commit do `docs/data.json` atualizado):
   - **Settings → Actions → General → Workflow permissions** → selecione
     **"Read and write permissions"** → Salvar.

4. **Habilite o GitHub Pages**:
   - **Settings → Pages → Build and deployment → Source**: "Deploy from a
     branch".
   - **Branch**: `main` (ou a branch padrão do seu repositório), pasta
     **`/docs`**.
   - Salve. O GitHub mostra a URL pública (algo como
     `https://SEU-USUARIO.github.io/SEU-REPOSITORIO/`) em alguns minutos.

5. **Rode o workflow manualmente uma vez** antes de esperar pelo agendamento
   automático: aba **Actions → Atualizar Dashboard de Lotes a Vencer → Run
   workflow**. Confira os logs e o conteúdo gerado em `docs/data.json`.

6. Depois disso, o workflow roda sozinho **todo dia às 08:00 (horário de
   Brasília)** e também pode ser disparado manualmente a qualquer momento pela
   mesma tela de Actions.

## O que este dashboard mostra (e o que não mostra)

Mostra, agregado e atualizado automaticamente:
- 6 indicadores (lotes a vencer em 90 dias, vencidos, urgência ≤30 dias,
  perda provável, risco parcial, sem giro em 12 meses);
- gráficos de lotes por família, por prazo e por risco de perda;
- uma tabela com todos os lotes (produto, família, lote, validade, dias para
  vencer, saldo, venda média por dia, dias para vender, saldo em risco e
  classificação de risco), com busca e filtros por família, prazo e risco.

**Como o risco é calculado:** para cada produto, a venda média diária vem dos
pedidos faturados e não cancelados dos últimos 12 meses. Supondo que o lote que
vence antes sai antes, o script projeta quanto do saldo de cada lote ainda
sobra na data de validade ("saldo em risco"). Classificação: *Perda provável*
(sobra ≥ 50% do saldo), *Risco parcial* (sobra algo), *Vende a tempo*, *Sem
giro* (nenhuma venda em 12 meses) e *Vencido*. É uma projeção pela média: não
prevê sazonalidade nem pedidos pontuais.

**Nunca mostra** nome, telefone, e-mail ou razão social de nenhum cliente —
isso ficou de fora de propósito, porque este dashboard é público. Essa parte
(quem contatar para cada produto) continua só na planilha interna "Produtos a
vencer" no Google Sheets, de acesso restrito ao Grupo Pigatto.

## Pontos de atenção antes de confiar 100% nos números

- A busca de **lotes** (`ListarLotes`) e de **família do produto**
  (`ConsultarProduto`) replica exatamente a lógica já validada e em produção
  na tarefa agendada de e-mail (mesma janela de 90 dias, mesmo critério de
  saldo, mesmos buckets de urgência) — alto grau de confiança.
- A busca de **vendas dos últimos 12 meses** (`ListarPedidos`, endpoint
  `produtos/pedido`) foi conferida contra a conta real em 14/10/2026 e conta
  só pedidos faturados e não cancelados. Se essa busca falhar, o workflow fica
  vermelho e o `data.json` anterior é mantido, para não publicar risco errado.
- O `docs/data.json` incluído agora é um **exemplo** (`"exemplo": true`), só
  para o dashboard não ficar em branco antes da primeira execução real. Ele
  tem os mesmos números já verificados na planilha interna em 09/10/2026. O
  banner laranja no topo do dashboard desaparece sozinho assim que o workflow
  gerar dados reais (que não têm o campo `"exemplo"`).

## Segurança

- A chave do Omie nunca aparece em nenhum arquivo deste repositório — só
  existe como Secret do GitHub, acessível apenas durante a execução do
  workflow.
- Nenhum dado de cliente (nome/telefone/e-mail) é buscado ou gravado por este
  script — a função de vendas só soma quantidades e conta códigos internos de
  cliente para gerar uma contagem (nunca grava o código em si no JSON
  público).
- Se decidir restringir o acesso ao dashboard mais adiante (em vez de
  público-anonimizado), as opções mais simples são: tornar o repositório
  privado e publicar o Pages via GitHub Enterprise (permite Pages privado), ou
  colocar o `docs/` atrás de um proxy simples com autenticação (ex.:
  Cloudflare Access na frente do domínio do GitHub Pages).

## Rotina de alerta por e-mail

A definição da tarefa agendada que gera os rascunhos quinzenais de alerta de vencimento (Gmail) está versionada em [`rotina/`](rotina/README.md).
