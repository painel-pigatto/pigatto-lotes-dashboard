# Painel Comercial — Produtos a Vencer (Grupo Pigatto)

Painel interno, **protegido por senha**, com os lotes que vencem nos próximos
90 dias, o risco de cada um vencer sem ser vendido, o CMC, a perda estimada em
R$ e os potenciais clientes de cada produto. Publicado no GitHub Pages e
atualizado automaticamente uma vez por dia via GitHub Actions, puxando os
dados direto da API do Omie.

> **Como a senha protege os dados.** O site é estático e o repositório é
> público, então os dados nunca são publicados abertos: o workflow grava
> `docs/data.enc.json` criptografado com AES-256-GCM (chave derivada da senha
> por PBKDF2-SHA256, 600 mil iterações). O navegador só consegue abrir os
> dados com a senha. A senha fica apenas no secret `PAINEL_SENHA`.
>
> **Complementar aos e-mails de alerta.** Os rascunhos quinzenais de e-mail
> continuam sendo gerados pela tarefa agendada do Claude. A política comercial
> de descontos fica só no e-mail interno, não neste painel.

## Estrutura do repositório

```
.
├── .github/workflows/update-dashboard.yml   # roda 1x por dia (e sob demanda)
├── scripts/
│   ├── fetch_omie_data.py                   # busca dados no Omie e gera docs/data.enc.json
│   └── requirements.txt
└── docs/
    ├── index.html                           # o dashboard em si (HTML/CSS/JS puro, sem build)
    └── data.enc.json                        # dados criptografados gerados pelo workflow
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
   - Crie `PAINEL_SENHA` com a senha do painel (mínimo 12 caracteres; use
     4 ou mais palavras aleatórias, ex.: `cobalto-janela-tigre-mesa`).

3. **Habilite permissão de escrita para o GitHub Actions** (necessária para o
   workflow conseguir fazer commit do `docs/data.enc.json` atualizado):
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
   workflow**. Confira os logs e abra o painel com a senha.

6. Depois disso, o workflow roda sozinho **todo dia antes das 08:00 (horário
   de Brasília)** — agendado para 07:15 porque o GitHub atrasa o início em
   15–25 min. Também pode ser disparado manualmente a qualquer momento pela
   mesma tela de Actions. Páginas que ficam abertas (ex.: TV) buscam os dados
   novos sozinhas a cada 30 min.

## O que este dashboard mostra (e o que não mostra)

Mostra, agregado e atualizado automaticamente:
- 6 indicadores (lotes a vencer em 90 dias, urgência ≤30 dias, perda
  provável, risco parcial, sem giro em 12 meses, vende a tempo);
- tabela de risco por família, com a perda estimada de cada uma;
- uma tabela com todos os lotes (produto, família, lote, validade, dias para
  vencer, saldo, venda média por dia, dias para vender, saldo em risco e
  classificação de risco), com busca e filtros por família, prazo e risco.

**Como o risco é calculado:** para cada produto, a venda média diária vem dos
pedidos faturados e não cancelados dos últimos 12 meses. Supondo que o lote que
vence antes sai antes, o script projeta quanto do saldo de cada lote ainda
sobra na data de validade ("saldo em risco"). Classificação: *Perda provável*
(sobra ≥ 50% do saldo), *Risco parcial* (sobra algo), *Vende a tempo*, *Sem
giro* (nenhuma venda em 12 meses).

**Lotes já vencidos não aparecem no painel**: ficam só no e-mail interno
de vencidos, tratado pela operação. É uma projeção pela média: não
prevê sazonalidade nem pedidos pontuais.

**Potenciais clientes:** escolha um produto (ou clique numa linha da tabela)
para ver quem o comprou nos últimos 12 meses — razão social, cidade,
quantidade, última compra, vendedor, contato, telefone e e-mail (cadastro do
Omie). **CMC e perda estimada** vêm da posição de estoque do Omie
(`ListarPosEstoque`); produtos sem CMC aparecem com "—" e ficam fora do total.

## Pontos de atenção antes de confiar 100% nos números

- A busca de **lotes** (`ListarLotes`) e de **família do produto**
  (`ConsultarProduto`) replica exatamente a lógica já validada e em produção
  na tarefa agendada de e-mail (mesma janela de 90 dias, mesmo critério de
  saldo, mesmos buckets de urgência) — alto grau de confiança.
- A busca de **vendas dos últimos 12 meses** (`ListarPedidos`, endpoint
  `produtos/pedido`) foi conferida contra a conta real em 14/10/2026 e conta
  só pedidos faturados e não cancelados. Se essa busca falhar, o workflow fica
  vermelho e o `data.enc.json` anterior é mantido, para não publicar risco errado.
- O CMC (`ListarPosEstoque`, campo `nCMC`), os dados de cliente
  (`ConsultarCliente`) e os vendedores (`ListarVendedores`) ainda não foram
  conferidos contra a conta real. Na primeira execução, compare 2 ou 3
  produtos com o Omie; se o log mostrar "AVISO: ListarPosEstoque sem campo
  nCMC", o nome do campo precisa de ajuste.

## Segurança

- A chave do Omie nunca aparece em nenhum arquivo deste repositório — só
  existe como Secret do GitHub, acessível apenas durante a execução do
  workflow.
- Os dados (clientes, custos) só existem no repositório criptografados.
  Quem não tem a senha vê apenas a tela de login.
- **Troque a senha sempre que alguém do time sair da empresa**: altere o
  secret `PAINEL_SENHA` e rode o workflow. Versões antigas de
  `data.enc.json` continuam no histórico do Git cifradas com a senha
  antiga — por isso a troca deve ser imediata e a senha antiga nunca
  reaproveitada.
- Compartilhe a senha só por canal interno. Para controle individual de
  acesso (login por e-mail, registro de quem acessou), a evolução natural é
  Cloudflare Pages + Cloudflare Access.

## Rotina de alerta por e-mail

A definição da tarefa agendada que gera os rascunhos quinzenais de alerta de vencimento (Gmail) está versionada em [`rotina/`](rotina/README.md).
