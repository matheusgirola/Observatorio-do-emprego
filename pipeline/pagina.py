"""
Dados, tabelas e gráficos da página do Observatório (index.qmd).

A página só lê o que a pipeline grava:
    dados/consolidado/   oportunidades_anual.csv, oportunidades_mensal.csv, metadados.json
    dados/entrada/       caged_*.csv, projecao_*.csv/json
    dados/manual/        mei_mapa_empresas.csv, concursados.csv
    config/pipeline.yml  meta e regras

Cores: ordem categórica fixa da paleta de referência (CAGED azul, MEI laranja,
concursados/terceira série verde-água); o leque da projeção é a rampa
sequencial do azul. Texto sempre nas tintas neutras, nunca na cor da série.
"""

from __future__ import annotations

import html
import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import yaml

RAIZ = Path(__file__).resolve().parent.parent
DADOS = RAIZ / "dados"

SERIE = {"caged": "#2a78d6", "mei": "#eb6834", "concursados": "#1baf7a"}
AREA = {"Piauí": "#2a78d6", "Nordeste": "#eb6834", "Brasil": "#1baf7a"}
AZUL = {"100": "#cde2fb", "200": "#9ec5f4", "450": "#2a78d6", "600": "#184f95"}
TINTA = {"primaria": "#0b0b0b", "secundaria": "#52514e", "muda": "#8a8984",
         "grade": "#e6e5e1"}
NOMES = {"caged": "Emprego formal (CAGED)", "mei": "MEI", "concursados": "Concursados",
         "bolsas": "Bolsas de estudo"}
MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov",
         "dez"]
MESES_LONGOS = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho",
                "agosto", "setembro", "outubro", "novembro", "dezembro"]


# --------------------------------------------------------------------- formato
def fmt(n: float, dec: int = 0) -> str:
    """Número no padrão brasileiro: 112.949 / 63,8."""
    s = f"{n:,.{dec}f}"
    return s.replace(",", "§").replace(".", ",").replace("§", ".")


def fmt_prob(p: float) -> str:
    """Probabilidade em %: inteira no meio da escala e com uma casa perto dos
    extremos, para 0,996 não virar um "100%" que sugere certeza."""
    if p in (0.0, 1.0):
        return f"{fmt(100 * p)}%"
    if 0.02 < p < 0.98:
        return f"{fmt(100 * p)}%"
    return f"{fmt(min(max(100 * p, 0.1), 99.9), 1)}%"


def fmt_sinal(n: float) -> str:
    return ("+" if n > 0 else "") + fmt(n)


def mes_curto(comp: str) -> str:
    ano, mes = comp.split("-")
    return f"{MESES[int(mes) - 1]}/{ano}"


def mes_longo(comp: str) -> str:
    ano, mes = comp.split("-")
    return f"{MESES_LONGOS[int(mes) - 1]} de {ano}"


def data_br(iso: str) -> str:
    """'2026-10-11' ou '2026-11-06T10:04:25-03:00' -> '11/10/2026'."""
    if not iso:
        return ""
    a, m, d = iso[:10].split("-")
    return f"{d}/{m}/{a}"


def _data(comp: pd.Series) -> pd.Series:
    return pd.to_datetime(comp + "-01")


# ---------------------------------------------------------------------- dados
@dataclass
class Dados:
    cfg: dict
    meta: dict
    anual: pd.DataFrame
    mensal: pd.DataFrame
    caged: pd.DataFrame
    municipios: pd.DataFrame
    comparativo: pd.DataFrame
    mei_mapa: pd.DataFrame
    concursados: pd.DataFrame
    proj_mensal: pd.DataFrame | None
    proj_anual: pd.DataFrame | None
    proj: dict | None


def carregar(raiz: Path = RAIZ) -> Dados:
    d = raiz / "dados"
    ler = lambda p: pd.read_csv(p, dtype={"competencia": str})  # noqa: E731
    proj_ok = (d / "entrada" / "projecao_resumo.json").exists()
    return Dados(
        cfg=yaml.safe_load((raiz / "config" / "pipeline.yml").read_text(encoding="utf-8")),
        meta=json.loads((d / "consolidado" / "metadados.json").read_text(encoding="utf-8")),
        anual=pd.read_csv(d / "consolidado" / "oportunidades_anual.csv"),
        mensal=ler(d / "consolidado" / "oportunidades_mensal.csv"),
        caged=ler(d / "entrada" / "caged_pi_mensal.csv"),
        municipios=ler(d / "entrada" / "caged_municipios_mensal.csv"),
        comparativo=ler(d / "entrada" / "caged_comparativo_estoque.csv"),
        mei_mapa=pd.read_csv(d / "manual" / "mei_mapa_empresas.csv"),
        concursados=pd.read_csv(d / "manual" / "concursados.csv"),
        proj_mensal=ler(d / "entrada" / "projecao_mensal.csv") if proj_ok else None,
        proj_anual=pd.read_csv(d / "entrada" / "projecao_anual.csv") if proj_ok else None,
        proj=json.loads((d / "entrada" / "projecao_resumo.json").read_text(encoding="utf-8"))
        if proj_ok else None,
    )


def projecao_valida(d: Dados) -> bool:
    """A projeção só aparece se partiu da mesma competência do consolidado."""
    return d.proj is not None and all(
        d.proj[f"competencia_{f}"] == d.meta[f"competencia_{f}"] for f in ("caged", "mei")
    )


def acumulado_realizado(d: Dados) -> pd.DataFrame:
    """
    Total acumulado mês a mês desde o início da meta. CAGED e o MEI do dump são
    mensais; o MEI congelado (Mapa de Empresas) e os concursados são anuais e,
    só para desenhar a linha, são distribuídos igualmente pelos meses do ano
    (nos fins de ano o acumulado é exato).
    """
    m = d.mensal.copy()
    m["ano"] = m.competencia.str[:4].astype(int)
    meses_no_ano = m.groupby("ano").competencia.transform("count")
    mapa = d.mei_mapa.set_index("ano")["mei"]
    conc = d.concursados.set_index("ano")["concursados"]
    mei = m.mei.astype("Float64")
    congelado = m.ano <= int(d.cfg["mei_congelado_ate"])
    mei[congelado] = m.ano[congelado].map(mapa) / meses_no_ano[congelado]
    total = (m.caged.astype(float) + mei.fillna(0).astype(float)
             + m.ano.map(conc).fillna(0) / meses_no_ano)
    return pd.DataFrame({"competencia": m.competencia, "acumulado": total.cumsum()})


# ------------------------------------------------------------------- gráficos
CONFIG_PLOTLY = {"displayModeBar": False, "responsive": True}
# Mesma pilha do tema cosmo do Quarto: o Plotly não herda a fonte da página.
FONTE = ("Source Sans Pro, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, "
         "'Helvetica Neue', Arial, sans-serif")


def _layout(fig: go.Figure, altura: int = 380, titulo_y: str = "") -> go.Figure:
    fig.update_layout(
        height=altura,
        margin=dict(l=8, r=8, t=36, b=8),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=FONTE, size=13, color=TINTA["secundaria"]),
        separators=",.",
        hovermode="x unified",
        hoverlabel=dict(bgcolor="white", font_color=TINTA["primaria"]),
        legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="left", x=0,
                    font_color=TINTA["primaria"], title_text=""),
    )
    fig.update_xaxes(showgrid=False, linecolor=TINTA["grade"], ticks="",
                     tickformat="%Y", dtick="M12", ticklabelmode="period")
    fig.update_yaxes(gridcolor=TINTA["grade"], zeroline=True,
                     zerolinecolor=TINTA["muda"], zerolinewidth=1, tickformat=",.0f",
                     title_text=titulo_y, title_font_size=12)
    return fig


def fig_mensal(d: Dados) -> go.Figure:
    m = d.mensal.copy()
    x = _data(m.competencia)
    rot = m.competencia.map(mes_curto)
    fig = go.Figure()
    for col in ("caged", "mei"):
        fig.add_bar(
            x=x, y=m[col], name=NOMES[col], marker_color=SERIE[col],
            marker_line=dict(width=1, color="white"), customdata=rot,
            hovertemplate=f"{NOMES[col]}: %{{y:,.0f}}<extra></extra>",
        )
    fig.update_layout(barmode="relative", bargap=0.25)
    _layout(fig, titulo_y="oportunidades no mês")
    fig.update_xaxes(hoverformat="%m/%Y")
    return fig


def fig_trajetoria(d: Dados) -> go.Figure:
    real = acumulado_realizado(d)
    meta = float(d.cfg["meta"]["valor"])
    fig = go.Figure()
    if projecao_valida(d):
        p = d.proj_mensal.copy()
        ultimo = real.iloc[-1]
        ancora = pd.DataFrame([{"competencia": ultimo.competencia,
                                **{c: ultimo.acumulado for c in p.columns if c != "competencia"}}])
        p = pd.concat([ancora, p], ignore_index=True)
        xp = _data(p.competencia)
        for lo, hi, cor, nome in (("q05", "q95", AZUL["100"], "Faixa de 90%"),
                                  ("q10", "q90", AZUL["200"], "Faixa de 80%")):
            fig.add_scatter(x=xp, y=p[hi], mode="lines", line_width=0, showlegend=False,
                            hoverinfo="skip")
            fig.add_scatter(x=xp, y=p[lo], mode="lines", line_width=0, fill="tonexty",
                            fillcolor=cor, name=nome, hoverinfo="skip")
        fig.add_scatter(
            x=xp, y=p.mediana, mode="lines", name="Projeção (mediana)",
            line=dict(color=AZUL["450"], width=2, dash="dash"),
            customdata=p[["q10", "q90"]],
            hovertemplate="Projeção: %{y:,.0f} (80%: %{customdata[0]:,.0f} a "
                          "%{customdata[1]:,.0f})<extra></extra>",
        )
    fig.add_scatter(x=_data(real.competencia), y=real.acumulado, mode="lines",
                    name="Realizado", line=dict(color=AZUL["600"], width=2),
                    hovertemplate="Realizado: %{y:,.0f}<extra></extra>")
    fig.add_hline(y=meta, line=dict(color=TINTA["secundaria"], width=1, dash="dot"),
                  annotation_text=f"Meta: {fmt(meta)}", annotation_position="top left",
                  annotation_font_color=TINTA["secundaria"])
    _layout(fig, altura=420, titulo_y="acumulado desde jan/2023")
    fig.update_xaxes(hoverformat="%m/%Y")
    return fig


def fig_comparativo(d: Dados) -> go.Figure:
    c = d.comparativo.copy()
    base = c[c.competencia == c.competencia.min()].set_index("area")["estoque"]
    c["indice"] = c.estoque / c.area.map(base) * 100
    fig = go.Figure()
    for area in ("Piauí", "Nordeste", "Brasil"):
        s = c[c.area == area]
        fig.add_scatter(x=_data(s.competencia), y=s.indice, mode="lines", name=area,
                        line=dict(color=AREA[area], width=2),
                        hovertemplate=f"{area}: %{{y:,.1f}}<extra></extra>")
    _layout(fig, titulo_y=f"estoque, {mes_curto(c.competencia.min())} = 100")
    fig.update_yaxes(tickformat=",.0f", zeroline=False)
    fig.update_xaxes(hoverformat="%m/%Y")
    return fig


# -------------------------------------------------------------------- tabelas
def _tabela(cabecalho: list[str], linhas: list[list[str]], classes: str = "",
            destaque_ultima: bool = False, legenda: str = "") -> str:
    th = "".join(f"<th>{html.escape(c)}</th>" for c in cabecalho)
    corpo = []
    for i, ln in enumerate(linhas):
        cls = ' class="total"' if destaque_ultima and i == len(linhas) - 1 else ""
        corpo.append(f"<tr{cls}>" + "".join(f"<td>{c}</td>" for c in ln) + "</tr>")
    cap = f"<caption>{legenda}</caption>" if legenda else ""
    return (f'<div class="tabela-rolagem"><table class="table tabela-obs {classes}">{cap}'
            f"<thead><tr>{th}</tr></thead><tbody>{''.join(corpo)}</tbody></table></div>")


def tabela_anual(d: Dados) -> str:
    a = d.anual
    comps = [c for c in ("caged", "mei", "concursados", "bolsas") if c in a.columns]
    ultimo_ano = int(a.ano.max())
    comp_final = d.meta["competencia_caged"]
    linhas = []
    for _, r in a.iterrows():
        rot = str(int(r.ano))
        if int(r.ano) == ultimo_ano and r.meses_caged < 12:
            rot += f" <span class='nota'>(até {mes_curto(comp_final)})</span>"
        linhas.append([rot] + [fmt(r[c]) for c in comps] + [f"<b>{fmt(r.total)}</b>"])
    linhas.append(["<b>Total</b>"] + [f"<b>{fmt(a[c].sum())}</b>" for c in comps]
                  + [f"<b>{fmt(a.total.sum())}</b>"])
    return _tabela(["Ano"] + [NOMES[c] for c in comps] + ["Total"], linhas,
                   classes="numerica", destaque_ultima=True)


def tabela_projecao(d: Dados) -> str:
    p = d.proj_anual
    linhas = []
    for _, r in p.iterrows():
        rot = str(int(r.ano))
        if r.realizado > 0:
            rot += " <span class='nota'>(realizado + projetado)</span>"
        linhas.append([rot, f"<b>{fmt(r.mediana)}</b>", f"{fmt(r.q10)} a {fmt(r.q90)}"])
    return _tabela(["Ano", "Projeção (mediana)", "Faixa de 80%"], linhas,
                   classes="numerica")


def territorios(d: Dados) -> pd.DataFrame:
    m = d.municipios
    t = m.groupby("territorio", as_index=False).saldo.sum().sort_values("saldo",
                                                                         ascending=False)
    t["pct"] = t.saldo / t.saldo.sum() * 100
    return t


def tabela_territorios(d: Dados) -> str:
    t = territorios(d)
    linhas = [[html.escape(r.territorio), fmt_sinal(r.saldo), fmt(r.pct, 1) + "%"]
              for r in t.itertuples()]
    linhas.append(["<b>Piauí</b>", f"<b>{fmt_sinal(t.saldo.sum())}</b>", "<b>100,0%</b>"])
    return _tabela(["Território de desenvolvimento", "Saldo de empregos formais",
                    "% do estado"], linhas, classes="numerica", destaque_ultima=True)


def tabela_municipios(d: Dados, maiores: bool = True, n: int = 10) -> str:
    m = (d.municipios.groupby(["municipio", "territorio"], as_index=False).saldo.sum()
         .sort_values("saldo", ascending=not maiores).head(n))
    linhas = [[html.escape(r.municipio), f"<span class='nota'>{html.escape(r.territorio)}"
               "</span>", fmt_sinal(r.saldo)] for r in m.itertuples()]
    return _tabela(["Município", "Território", "Saldo"], linhas, classes="numerica")


# ------------------------------------------------------------------ destaques
def cruzamento_meta(d: Dados, coluna: str = "mediana") -> str | None:
    """Primeira competência em que o quantil `coluna` do acumulado projetado
    alcança a meta (None se não alcança no horizonte). Com q10, é o mês até o
    qual 90% das trajetórias já chegaram lá."""
    if not projecao_valida(d):
        return None
    meta = float(d.cfg["meta"]["valor"])
    if d.proj["realizado"] >= meta:
        return d.meta["competencia_caged"]
    p = d.proj_mensal
    acima = p.competencia[p[coluna] >= meta]
    return acima.iloc[0] if len(acima) else None


def destaques(d: Dados) -> list[tuple[str, str, str]]:
    """(valor, rótulo, detalhe) dos cartões do topo."""
    ini = d.cfg["meta"]["inicio"]
    comp = d.meta["competencia_caged"]
    ult = d.mensal[d.mensal.competencia == comp].iloc[0]
    no_mes = int(ult.caged) + (0 if pd.isna(ult.mei) else int(ult.mei))
    cards = [
        (fmt(d.anual.total.sum()), f"oportunidades desde {mes_curto(ini)}",
         f"até {mes_curto(comp)}"),
        (fmt_sinal(no_mes), f"em {mes_curto(comp)}",
         f"{fmt_sinal(int(ult.caged))} empregos formais e "
         f"{fmt_sinal(0 if pd.isna(ult.mei) else int(ult.mei))} MEI"),
    ]
    if projecao_valida(d):
        p = d.proj
        cards.append((fmt_prob(p["p_meta"]),
                      f"de chance de chegar a {fmt(p['meta'] / 1000)} mil",
                      f"até {mes_curto(p['fim_meta'])}"))
        cards.append((fmt(p["total_fim_mediana"] / 1000) + " mil",
                      f"projetado para {mes_curto(p['fim_meta'])}",
                      f"80%: {fmt(p['total_fim_q10'] / 1000)} a "
                      f"{fmt(p['total_fim_q90'] / 1000)} mil"))
    return cards


def html_destaques(d: Dados) -> str:
    itens = "".join(
        f'<div class="kpi"><div class="kpi-valor">{v}</div>'
        f'<div class="kpi-rotulo">{html.escape(r)}</div>'
        f'<div class="kpi-detalhe">{html.escape(det)}</div></div>'
        for v, r, det in destaques(d)
    )
    return f'<div class="kpis">{itens}</div>'
