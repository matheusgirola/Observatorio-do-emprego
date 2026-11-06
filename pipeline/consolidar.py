"""
Consolidação dos dados do Observatório.

Junta os contratos dos produtores (dados/entrada) com os valores manuais
(dados/manual) e grava em dados/consolidado:

    oportunidades_mensal.csv  competencia, caged, mei, mei_fonte
    oportunidades_anual.csv   ano, meses_caged, caged, mei, mei_fonte, concursados,
                              [bolsas,] total
    metadados.json            competências de cada fonte e data da consolidação

Regras:
- CAGED: saldo mensal do PI (tabela 7.1 com ajustes), desde jan do ano_inicio.
- MEI: até `mei_congelado_ate`, o valor anual do painel Mapa de Empresas
  (manual); depois, o saldo mensal do dump do CNPJ (abertos - fechados MEI).
- Concursados e bolsas: anuais, manuais.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import pandas as pd


class ErroValidacao(RuntimeError):
    """Inconsistência que impede publicar."""


@dataclass
class Resultado:
    mensal: pd.DataFrame
    anual: pd.DataFrame
    meta: dict
    avisos: list[str] = field(default_factory=list)


def _ler(caminho: Path, **kw) -> pd.DataFrame:
    if not caminho.exists():
        raise ErroValidacao(f"arquivo ausente: {caminho}")
    return pd.read_csv(caminho, **kw)


def _ler_json(caminho: Path) -> dict:
    return json.loads(caminho.read_text(encoding="utf-8")) if caminho.exists() else {}


def _continua(competencias: pd.Series, nome: str) -> None:
    """Competências em sequência, sem buraco nem repetição."""
    c = competencias.tolist()
    if len(c) != len(set(c)):
        raise ErroValidacao(f"{nome}: competência repetida")
    esperado = pd.period_range(c[0], c[-1], freq="M").astype(str).tolist()
    if c != esperado:
        faltam = sorted(set(esperado) - set(c))
        raise ErroValidacao(f"{nome}: competências faltando: {', '.join(faltam)}")


def consolidar(raiz: Path, cfg: dict) -> Resultado:
    entrada, manual = raiz / "dados" / "entrada", raiz / "dados" / "manual"
    ano0 = int(cfg["ano_inicio"])
    congelado_ate = int(cfg["mei_congelado_ate"])
    avisos: list[str] = []

    # --- CAGED
    caged = _ler(entrada / "caged_pi_mensal.csv", dtype={"competencia": str})
    caged = caged[caged.competencia >= f"{ano0}-01"].sort_values("competencia")
    if caged.empty or caged.competencia.iloc[0] != f"{ano0}-01":
        raise ErroValidacao(f"CAGED não começa em {ano0}-01")
    _continua(caged.competencia, "CAGED")
    if caged.saldo.isna().any():
        raise ErroValidacao("CAGED: saldo vazio")

    # --- MEI do dump (a partir do ano seguinte ao congelado)
    mei = _ler(entrada / "mei_pi_mensal.csv", dtype={"competencia": str})
    mei = mei[mei.competencia >= f"{congelado_ate + 1}-01"].sort_values("competencia")
    if mei.empty or mei.competencia.iloc[0] != f"{congelado_ate + 1}-01":
        raise ErroValidacao(f"MEI do dump não começa em {congelado_ate + 1}-01")
    _continua(mei.competencia, "MEI")

    # --- MEI congelado (painel), anual
    mei_mapa = _ler(manual / "mei_mapa_empresas.csv").set_index("ano")["mei"]
    faltam = [a for a in range(ano0, congelado_ate + 1) if a not in mei_mapa.index]
    if faltam:
        raise ErroValidacao(f"mei_mapa_empresas.csv sem os anos {faltam}")

    # --- mensal: CAGED + MEI do dump nos meses em que ele vale
    mensal = caged[["competencia", "saldo"]].rename(columns={"saldo": "caged"})
    mensal = mensal.merge(
        mei[["competencia", "saldo_mei"]].rename(columns={"saldo_mei": "mei"}),
        on="competencia",
        how="outer",
    ).sort_values("competencia")
    mensal["mei_fonte"] = mensal.mei.notna().map({True: "cnpj", False: ""})
    mensal["mei"] = mensal.mei.astype("Int64")
    mensal["caged"] = mensal.caged.astype("Int64")

    # Competência comum: o total do ano corrente só soma meses que as duas
    # séries automáticas cobrem; o que sobra de uma delas fica visível no
    # mensal e vira aviso.
    fim_caged, fim_mei = caged.competencia.iloc[-1], mei.competencia.iloc[-1]
    if fim_caged != fim_mei:
        avisos.append(
            f"CAGED vai até {fim_caged} e MEI até {fim_mei}: o ano corrente "
            f"soma cada componente até a própria competência"
        )

    # --- anual
    mensal_ano = mensal.assign(ano=mensal.competencia.str[:4].astype(int))
    anos = sorted(mensal_ano.ano.unique())
    linhas = []
    for ano in anos:
        g = mensal_ano[mensal_ano.ano == ano]
        if ano <= congelado_ate:
            v_mei, fonte = int(mei_mapa[ano]), "mapa_empresas"
        else:
            v_mei, fonte = int(g.mei.sum()), "cnpj"
        linhas.append(
            {
                "ano": ano,
                "meses_caged": int(g.caged.notna().sum()),
                "caged": int(g.caged.sum()),
                "mei": v_mei,
                "mei_fonte": fonte,
            }
        )
    anual = pd.DataFrame(linhas)

    conc = _ler(manual / "concursados.csv").set_index("ano")["concursados"]
    anual["concursados"] = anual.ano.map(conc).fillna(0).astype(int)
    sem_conc = [a for a in anual.ano if a not in conc.index]
    if sem_conc:
        avisos.append(f"concursados.csv sem os anos {sem_conc} (contado como 0)")
    componentes = ["caged", "mei", "concursados"]
    if cfg.get("incluir_bolsas"):
        bolsas = _ler(manual / "bolsas.csv").set_index("ano")["bolsas"]
        anual["bolsas"] = anual.ano.map(bolsas).fillna(0).astype(int)
        componentes.append("bolsas")
    anual["total"] = anual[componentes].sum(axis=1)

    meta = {
        "data_consolidacao": datetime.now().astimezone().isoformat(timespec="seconds"),
        "competencia_caged": fim_caged,
        "competencia_mei": fim_mei,
        "mei_congelado_ate": congelado_ate,
        "componentes": componentes,
        "fontes": {
            "caged": _ler_json(entrada / "caged_meta.json"),
            "mei": _ler_json(entrada / "mei_meta.json"),
        },
    }
    return Resultado(mensal=mensal.reset_index(drop=True), anual=anual, meta=meta,
                     avisos=avisos)


def comparar(anterior: pd.DataFrame | None, atual: pd.DataFrame, limite_pct: float):
    """Tabela antes/depois por ano e avisos de revisão em anos já fechados."""
    cols = [c for c in atual.columns if c not in ("ano", "meses_caged", "mei_fonte")]
    if anterior is None or anterior.empty:
        return atual.set_index("ano")[cols], []
    a = anterior.set_index("ano")
    b = atual.set_index("ano")
    tabela = pd.concat(
        {c: pd.DataFrame({"antes": a.get(c), "depois": b[c]}) for c in cols}, axis=1
    )
    avisos = []
    ano_corrente = int(atual.ano.max())
    for ano in b.index:
        if ano >= ano_corrente or ano not in a.index:
            continue
        for c in cols:
            if c not in a.columns or pd.isna(a.at[ano, c]) or a.at[ano, c] == 0:
                continue
            pct = (b.at[ano, c] - a.at[ano, c]) / abs(a.at[ano, c]) * 100
            if abs(pct) > limite_pct:
                avisos.append(
                    f"{c} {ano} mudou {pct:+.1f}% ({int(a.at[ano, c])} -> "
                    f"{int(b.at[ano, c])})"
                )
    return tabela, avisos


def gravar(raiz: Path, r: Resultado) -> None:
    destino = raiz / "dados" / "consolidado"
    destino.mkdir(parents=True, exist_ok=True)
    for nome, df in (("oportunidades_mensal.csv", r.mensal),
                     ("oportunidades_anual.csv", r.anual)):
        tmp = destino / (nome + ".tmp")
        df.to_csv(tmp, index=False, lineterminator="\n", encoding="utf-8")
        tmp.replace(destino / nome)
    meta = dict(r.meta, avisos=r.avisos)
    (destino / "metadados.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
