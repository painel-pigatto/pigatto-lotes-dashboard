#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Busca dados de lotes a vencer/vencidos e vendas dos últimos 12 meses direto da
API do Omie, agrega tudo (SEM nenhum dado de cliente individual: nome, telefone,
e-mail ou razão social nunca entram neste arquivo) e grava docs/data.json, que é
o arquivo que o dashboard estático (docs/index.html) lê para se desenhar.

Este script roda dentro do GitHub Action `.github/workflows/update-dashboard.yml`,
uma vez por dia. As credenciais do Omie vêm das variáveis de ambiente
OMIE_APP_KEY e OMIE_APP_SECRET (configuradas como Secrets do repositório — ver
README.md). Nunca imprime essas credenciais em log nenhum.

IMPORTANTE — status de cada parte desta integração:
  - Lotes (ListarLotes) e família do produto (ConsultarProduto): lógica
    replicada da rotina já em produção (tarefa agendada de e-mail do Grupo
    Pigatto), mesmos parâmetros e mesma regra de negócio (janela de 90 dias,
    saldo > 0, buckets de urgência).
  - Vendas dos últimos 12 meses (ListarPedidos): construído a partir da
    documentação pública da API do Omie, mas AINDA NÃO testado contra a conta
    real do Grupo Pigatto (esta sessão não tem a chave do Omie para testar).
    Rode manualmente uma vez (aba Actions > Atualizar Dashboard de Lotes a
    Vencer > Run workflow) e confira o resultado em docs/data.json e os logs
    da execução antes de confiar cegamente nos números de venda. Se os nomes
    de campo da resposta de ListarPedidos na sua conta forem diferentes do que
    está aqui, ajuste a função `buscar_vendas_12_meses` — os pontos de atenção
    estão comentados no código.
"""

import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

OMIE_URL = "https://app.omie.com.br/api/v1/{path}/"
APP_KEY = os.environ.get("OMIE_APP_KEY", "").strip()
APP_SECRET = os.environ.get("OMIE_APP_SECRET", "").strip()

JANELA_DIAS = 90
JANELA_VENDAS_DIAS = 365
TIMEOUT = 30
MAX_TENTATIVAS = 3

# Agrupamento de família usado nos gráficos (mesmas famílias da planilha interna)
FAMILIAS_CONHECIDAS = [
    "Adesivos Estruturais",
    "Chemlok",
    "Marbocote",
    "Bio-Chem",
    "Silquim",
]


def omie_call(path: str, call: str, param: dict) -> dict:
    """Chamada genérica à API do Omie, com retry simples em erro de rede/5xx."""
    if not APP_KEY or not APP_SECRET:
        print(
            "ERRO: variáveis OMIE_APP_KEY / OMIE_APP_SECRET não configuradas. "
            "Configure-as em Settings > Secrets and variables > Actions do "
            "repositório (ver README.md).",
            file=sys.stderr,
        )
        sys.exit(1)

    body = {
        "call": call,
        "app_key": APP_KEY,
        "app_secret": APP_SECRET,
        "param": [param],
    }
    url = OMIE_URL.format(path=path)
    last_err = None
    for tentativa in range(1, MAX_TENTATIVAS + 1):
        try:
            resp = requests.post(url, json=body, timeout=TIMEOUT)
            if resp.status_code >= 500:
                raise RuntimeError(f"HTTP {resp.status_code} do Omie em {call}")
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, dict) and "faultstring" in data:
                raise RuntimeError(f"Omie retornou erro em {call}: {data['faultstring']}")
            return data
        except Exception as exc:  # noqa: BLE001 - queremos capturar qualquer falha de rede/parsing
            last_err = exc
            if tentativa < MAX_TENTATIVAS:
                time.sleep(2 * tentativa)
    raise RuntimeError(f"Falha ao chamar {call} após {MAX_TENTATIVAS} tentativas: {last_err}")


def parse_data_omie(data_str: str):
    """Datas do Omie vêm como dd/mm/aaaa."""
    if not data_str:
        return None
    try:
        return datetime.strptime(data_str, "%d/%m/%Y").date()
    except ValueError:
        return None


def buscar_lotes():
    """Retorna a lista de lotes com saldo > 0 dentro da janela de 90 dias + vencidos."""
    hoje = datetime.now(timezone.utc).date()
    limite_futuro = hoje + timedelta(days=JANELA_DIAS)

    lotes_relevantes = []
    pagina = 1
    while True:
        data = omie_call(
            "produtos/produtoslote",
            "ListarLotes",
            {"nPagina": pagina, "nRegPorPagina": 100},
        )
        lista = data.get("listaLotes", [])
        if not lista:
            break

        for item in lista:
            ident = item.get("ident", {})
            cod_produto = ident.get("cCodProduto")
            n_cod_prod = ident.get("nCodProd")
            descr_produto = ident.get("cDescrProduto")

            for lote in item.get("lotes", []) or []:
                saldo = lote.get("nSaldoLote", 0) or 0
                if saldo <= 0:
                    continue
                validade = parse_data_omie(lote.get("dDataValidade"))
                if validade is None:
                    continue
                if validade > limite_futuro:
                    continue  # fora da janela de 90 dias e não vencido o suficiente para interessar
                dias_restantes = (validade - hoje).days
                lotes_relevantes.append(
                    {
                        "produto": descr_produto,
                        "codigo_produto": cod_produto,
                        "n_cod_produto": n_cod_prod,
                        "lote": lote.get("cNumLote"),
                        "fabricacao": lote.get("dDataFabricacao"),
                        "validade": lote.get("dDataValidade"),
                        "dias_restantes": dias_restantes,
                        "saldo": saldo,
                        "vencido": dias_restantes < 0,
                    }
                )

        total_paginas = data.get("nTotPaginas", pagina)
        if pagina >= total_paginas:
            break
        pagina += 1

    return lotes_relevantes


def bucket_urgencia(dias_restantes: int) -> str:
    if dias_restantes < 0:
        return "Vencido"
    if dias_restantes <= 30:
        return "≤ 30 dias"
    if dias_restantes <= 60:
        return "31–60 dias"
    return "61–90 dias"


_cache_familia: dict = {}


def buscar_familia(n_cod_produto) -> str:
    """Consulta a família de um produto no Omie (com cache em memória por execução)."""
    if n_cod_produto in _cache_familia:
        return _cache_familia[n_cod_produto]
    try:
        data = omie_call("geral/produtos", "ConsultarProduto", {"codigo_produto": n_cod_produto})
        familia = data.get("descricao_familia") or "Outras"
    except Exception:  # noqa: BLE001 - não deixar uma falha pontual derrubar a execução inteira
        familia = "Outras"
    if familia not in FAMILIAS_CONHECIDAS:
        familia = "Outras"
    _cache_familia[n_cod_produto] = familia
    return familia


def buscar_vendas_12_meses(produtos_n_cod: set):
    """
    Soma a quantidade vendida nos últimos 12 meses e conta clientes distintos,
    por produto — SEM guardar nome/telefone/e-mail de nenhum cliente, só o
    código interno do cliente (nCodCliente) para poder contar distintos.

    ATENÇÃO: os nomes de parâmetro/campo abaixo seguem a documentação pública
    da API do Omie (módulo pedido/pedido, chamada ListarPedidos) mas NÃO foram
    testados contra a conta real do Grupo Pigatto nesta sessão (sem acesso à
    chave). Confira o primeiro resultado real e ajuste se necessário.
    """
    hoje = datetime.now(timezone.utc).date()
    desde = hoje - timedelta(days=JANELA_VENDAS_DIAS)

    qtd_por_produto: dict = {}
    clientes_por_produto: dict = {}

    pagina = 1
    while True:
        data = omie_call(
            "pedido/pedido",
            "ListarPedidos",
            {
                "pagina": pagina,
                "registros_por_pagina": 50,
                "apenas_importado_api": "N",
                "dDataEmiInicial": desde.strftime("%d/%m/%Y"),
                "dDataEmiFinal": hoje.strftime("%d/%m/%Y"),
            },
        )
        pedidos = data.get("pedido_venda_produto", []) or []
        if not pedidos:
            break

        for pedido in pedidos:
            cabecalho = pedido.get("cabecalho", {}) or {}
            cod_cliente = cabecalho.get("codigo_cliente")
            for item in pedido.get("det", []) or []:
                prod = item.get("produto", {}) or {}
                n_cod = prod.get("codigo_produto")
                if n_cod not in produtos_n_cod:
                    continue
                qtd = float(prod.get("quantidade", 0) or 0)
                qtd_por_produto[n_cod] = qtd_por_produto.get(n_cod, 0) + qtd
                clientes_por_produto.setdefault(n_cod, set())
                if cod_cliente is not None:
                    clientes_por_produto[n_cod].add(cod_cliente)

        total_paginas = data.get("total_de_paginas", pagina)
        if pagina >= total_paginas:
            break
        pagina += 1

    return qtd_por_produto, {k: len(v) for k, v in clientes_por_produto.items()}


def montar_dashboard():
    lotes = buscar_lotes()

    for lote in lotes:
        lote["familia"] = buscar_familia(lote["n_cod_produto"])
        lote["urgencia"] = bucket_urgencia(lote["dias_restantes"])

    produtos_n_cod = {l["n_cod_produto"] for l in lotes if l["n_cod_produto"] is not None}

    try:
        qtd_por_produto, clientes_por_produto = buscar_vendas_12_meses(produtos_n_cod)
    except Exception as exc:  # noqa: BLE001
        print(f"AVISO: falha ao buscar vendas dos últimos 12 meses ({exc}). "
              f"O dashboard será publicado sem os números de venda desta execução.",
              file=sys.stderr)
        qtd_por_produto, clientes_por_produto = {}, {}

    # KPIs
    lotes_a_vencer_90d = [l for l in lotes if not l["vencido"]]
    lotes_vencidos = [l for l in lotes if l["vencido"]]
    urgencia_30d = [l for l in lotes_a_vencer_90d if l["dias_restantes"] <= 30]

    # "clientes_candidatos_12m" é a SOMA da contagem de clientes distintos por
    # produto (não um total global deduplicado) — um mesmo cliente que compra
    # dois produtos diferentes a vencer conta uma vez em cada produto. Isso é
    # de propósito: não guardamos nenhum ID de cliente no JSON público, só a
    # contagem por produto, então não dá (nem deve) reconstruir a deduplicação
    # global aqui.
    kpis = {
        "lotes_a_vencer_90d": len(lotes_a_vencer_90d),
        "lotes_vencidos": len(lotes_vencidos),
        "urgencia_30d": len(urgencia_30d),
        "saldo_total_em_risco": round(sum(l["saldo"] for l in lotes), 2),
        "qtd_vendida_12m": round(sum(qtd_por_produto.values()), 2),
        "clientes_candidatos_12m": sum(clientes_por_produto.values()),
    }

    # Por família
    contagem_familia = {f: 0 for f in FAMILIAS_CONHECIDAS + ["Outras"]}
    for lote in lotes:
        contagem_familia[lote["familia"]] = contagem_familia.get(lote["familia"], 0) + 1
    por_familia = [{"familia": f, "qtd_lotes": contagem_familia[f]} for f in FAMILIAS_CONHECIDAS + ["Outras"]]

    # Por urgência
    ordem_urgencia = ["Vencido", "≤ 30 dias", "31–60 dias", "61–90 dias"]
    contagem_urgencia = {u: 0 for u in ordem_urgencia}
    for lote in lotes:
        contagem_urgencia[lote["urgencia"]] += 1
    por_urgencia = [{"situacao": u, "qtd_lotes": contagem_urgencia[u]} for u in ordem_urgencia]

    # Top produtos por quantidade vendida (12 meses)
    produtos_por_codigo = {l["n_cod_produto"]: l["produto"] for l in lotes}
    top_produtos = sorted(
        (
            {"produto": produtos_por_codigo.get(n_cod, str(n_cod)), "qtd_vendida_12m": round(qtd, 2)}
            for n_cod, qtd in qtd_por_produto.items()
        ),
        key=lambda x: x["qtd_vendida_12m"],
        reverse=True,
    )[:10]

    # Detalhe de lotes (produto/lote/datas — sem nenhum dado de cliente)
    detalhe_lotes = sorted(
        (
            {
                "produto": l["produto"],
                "familia": l["familia"],
                "lote": l["lote"],
                "fabricacao": l["fabricacao"],
                "validade": l["validade"],
                "dias_restantes": l["dias_restantes"],
                "situacao": l["urgencia"],
                "saldo": l["saldo"],
            }
            for l in lotes
        ),
        key=lambda x: x["dias_restantes"],
    )

    return {
        "gerado_em": datetime.now(timezone.utc).isoformat(timespec="seconds") + "Z",
        "janela_dias": JANELA_DIAS,
        "kpis": kpis,
        "por_familia": por_familia,
        "por_urgencia": por_urgencia,
        "top_produtos": top_produtos,
        "lotes": detalhe_lotes,
    }


def main():
    dashboard = montar_dashboard()
    out_path = os.path.join(os.path.dirname(__file__), "..", "docs", "data.json")
    out_path = os.path.abspath(out_path)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(dashboard, f, ensure_ascii=False, indent=2)
    print(f"OK: {out_path} gerado com {len(dashboard['lotes'])} lotes.")


if __name__ == "__main__":
    main()
