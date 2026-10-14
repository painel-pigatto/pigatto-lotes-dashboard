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
  - Vendas dos últimos 12 meses (ListarPedidos, endpoint produtos/pedido):
    só pedidos faturados e não cancelados. Endpoint e campos conferidos contra
    a conta real em 14/10/2026.
"""

import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

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

ORDEM_RISCO = ["Perda provável", "Risco parcial", "Sem giro", "Vende a tempo"]


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
    hoje = datetime.now(ZoneInfo("America/Sao_Paulo")).date()
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


_cache_produto: dict = {}


def buscar_produto(n_cod_produto):
    """Consulta família e unidade de um produto no Omie (com cache em memória por execução)."""
    if n_cod_produto in _cache_produto:
        return _cache_produto[n_cod_produto]
    try:
        data = omie_call("geral/produtos", "ConsultarProduto", {"codigo_produto": n_cod_produto})
        familia = data.get("descricao_familia") or "Outras"
        unidade = (data.get("unidade") or "").strip()
    except Exception:  # noqa: BLE001 - não deixar uma falha pontual derrubar a execução inteira
        familia, unidade = "Outras", ""
    if familia not in FAMILIAS_CONHECIDAS:
        familia = "Outras"
    _cache_produto[n_cod_produto] = (familia, unidade)
    return familia, unidade


def classificar_risco(saldo: float, saldo_em_risco: float, sem_giro: bool) -> str:
    if sem_giro:
        return "Sem giro"
    if saldo_em_risco <= 0:
        return "Vende a tempo"
    if saldo_em_risco >= 0.5 * saldo:
        return "Perda provável"
    return "Risco parcial"


def calcular_cobertura(lotes: list, qtd_por_produto: dict) -> None:
    """
    Projeta, pelo ritmo médio de venda dos últimos 12 meses, quanto do saldo de
    cada lote deve vencer sem ser vendido. Supõe que os lotes de um mesmo
    produto saem na ordem de validade (o que vence antes sai antes) e que a
    capacidade de venda não usada até um lote vencer passa para o próximo.
    """
    por_produto: dict = {}
    for lote in lotes:
        por_produto.setdefault(lote["n_cod_produto"], []).append(lote)

    for n_cod, lotes_prod in por_produto.items():
        venda_dia = qtd_por_produto.get(n_cod, 0) / JANELA_VENDAS_DIAS
        vendido_antes = 0.0
        for lote in sorted(lotes_prod, key=lambda l: l["dias_restantes"]):
            saldo = float(lote["saldo"])
            lote["venda_media_dia"] = round(venda_dia, 3)
            if venda_dia <= 0:
                lote["dias_para_vender"] = None
                lote["saldo_em_risco"] = round(saldo, 2)
            else:
                capacidade = venda_dia * lote["dias_restantes"] - vendido_antes
                vendido = min(saldo, max(0.0, capacidade))
                lote["dias_para_vender"] = round((vendido_antes + saldo) / venda_dia)
                lote["saldo_em_risco"] = round(saldo - vendido, 2)
                vendido_antes += vendido
            lote["risco"] = classificar_risco(saldo, lote["saldo_em_risco"], venda_dia <= 0)


def buscar_vendas_12_meses(produtos_n_cod: set):
    """
    Soma a quantidade vendida nos últimos 12 meses por produto. Nenhum dado de
    cliente é lido para o painel.

    Endpoint produtos/pedido, chamada ListarPedidos (validado contra a conta
    real em 14/10/2026). Considera apenas pedidos faturados e não cancelados.
    """
    hoje = datetime.now(ZoneInfo("America/Sao_Paulo")).date()
    desde = hoje - timedelta(days=JANELA_VENDAS_DIAS)

    qtd_por_produto: dict = {}

    pagina = 1
    while True:
        data = omie_call(
            "produtos/pedido",
            "ListarPedidos",
            {
                "pagina": pagina,
                "registros_por_pagina": 100,
                "apenas_importado_api": "N",
                "filtrar_por_data_de": desde.strftime("%d/%m/%Y"),
                "filtrar_por_data_ate": hoje.strftime("%d/%m/%Y"),
            },
        )
        pedidos = data.get("pedido_venda_produto", []) or []
        if not pedidos:
            break

        for pedido in pedidos:
            # Só conta venda efetiva: pedido faturado e não cancelado.
            info = pedido.get("infoCadastro", {}) or {}
            if info.get("cancelado") == "S" or info.get("faturado") != "S":
                continue
            for item in pedido.get("det", []) or []:
                prod = item.get("produto", {}) or {}
                n_cod = prod.get("codigo_produto")
                if n_cod not in produtos_n_cod:
                    continue
                qtd = float(prod.get("quantidade", 0) or 0)
                qtd_por_produto[n_cod] = qtd_por_produto.get(n_cod, 0) + qtd

        total_paginas = data.get("total_de_paginas", pagina)
        if pagina >= total_paginas:
            break
        pagina += 1

    return qtd_por_produto


def montar_dashboard():
    # Lotes vencidos ficam fora do painel: são tratados pela operação no e-mail
    # interno de vencidos, não pelo comercial.
    lotes = [l for l in buscar_lotes() if not l["vencido"]]

    for lote in lotes:
        lote["familia"], lote["unidade"] = buscar_produto(lote["n_cod_produto"])
        lote["urgencia"] = bucket_urgencia(lote["dias_restantes"])

    produtos_n_cod = {l["n_cod_produto"] for l in lotes if l["n_cod_produto"] is not None}

    try:
        qtd_por_produto = buscar_vendas_12_meses(produtos_n_cod)
    except Exception as exc:  # noqa: BLE001
        print(f"ERRO: falha ao buscar vendas dos últimos 12 meses ({exc}). "
              f"Sem vendas a projeção de risco ficaria errada; data.json não foi atualizado.",
              file=sys.stderr)
        raise SystemExit(1)  # sem vendas a projeção de risco ficaria errada; melhor falhar visível

    calcular_cobertura(lotes, qtd_por_produto)

    # KPIs — só contagens de lotes: somar saldos misturaria kg, litros e bisnagas.
    contagem_risco = {r: 0 for r in ORDEM_RISCO}
    for lote in lotes:
        contagem_risco[lote["risco"]] += 1
    kpis = {
        "lotes_a_vencer_90d": len(lotes),
        "urgencia_30d": len([l for l in lotes if l["dias_restantes"] <= 30]),
        "lotes_perda_provavel": contagem_risco["Perda provável"],
        "lotes_risco_parcial": contagem_risco["Risco parcial"],
        "lotes_sem_giro": contagem_risco["Sem giro"],
        "lotes_vende_a_tempo": contagem_risco["Vende a tempo"],
    }

    # Por família
    contagem_familia = {f: 0 for f in FAMILIAS_CONHECIDAS + ["Outras"]}
    for lote in lotes:
        contagem_familia[lote["familia"]] = contagem_familia.get(lote["familia"], 0) + 1
    por_familia = [{"familia": f, "qtd_lotes": contagem_familia[f]} for f in FAMILIAS_CONHECIDAS + ["Outras"]]

    # Por urgência
    ordem_urgencia = ["≤ 30 dias", "31–60 dias", "61–90 dias"]
    contagem_urgencia = {u: 0 for u in ordem_urgencia}
    for lote in lotes:
        contagem_urgencia[lote["urgencia"]] += 1
    por_urgencia = [{"situacao": u, "qtd_lotes": contagem_urgencia[u]} for u in ordem_urgencia]

    por_risco = [{"risco": r, "qtd_lotes": contagem_risco[r]} for r in ORDEM_RISCO]

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
                "unidade": l["unidade"],
                "venda_media_dia": l["venda_media_dia"],
                "dias_para_vender": l["dias_para_vender"],
                "saldo_em_risco": l["saldo_em_risco"],
                "risco": l["risco"],
            }
            for l in lotes
        ),
        key=lambda x: (ORDEM_RISCO.index(x["risco"]), x["dias_restantes"]),
    )

    return {
        "gerado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "janela_dias": JANELA_DIAS,
        "kpis": kpis,
        "por_familia": por_familia,
        "por_urgencia": por_urgencia,
        "por_risco": por_risco,
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
