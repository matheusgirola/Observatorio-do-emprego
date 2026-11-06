"""Testes da página: números coerentes com o consolidado e peças que montam."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline import pagina as P  # noqa: E402


def test_formatos():
    assert P.fmt(112949) == "112.949"
    assert P.fmt(63.825, 1) == "63,8"
    assert P.fmt_sinal(-1013) == "-1.013" and P.fmt_sinal(783) == "+783"
    assert P.mes_curto("2026-09") == "set/2026"
    assert P.mes_longo("2026-03") == "março de 2026"
    assert P.data_br("2026-11-06T10:04:25-03:00") == "06/11/2026"


@pytest.fixture(scope="module")
def d():
    return P.carregar()


def test_acumulado_fecha_com_a_tabela_anual(d):
    """Nos fins de ano (e no último mês) a linha do realizado é exata."""
    ac = P.acumulado_realizado(d).set_index("competencia").acumulado
    anual = d.anual.set_index("ano").total.cumsum()
    for ano in d.anual.ano:
        fim = f"{ano}-12" if f"{ano}-12" in ac.index else ac.index[-1]
        assert ac[fim] == pytest.approx(anual[ano])


def test_destaques_batem_com_o_consolidado(d):
    valor, _, _ = P.destaques(d)[0]
    assert valor == P.fmt(d.anual.total.sum())


def test_territorios_somam_o_estado(d):
    t = P.territorios(d)
    caged = d.caged[d.caged.competencia >= d.municipios.competencia.min()].saldo.sum()
    assert t.saldo.sum() == caged


def test_pecas_montam(d):
    for fig in (P.fig_mensal(d), P.fig_trajetoria(d), P.fig_comparativo(d)):
        assert len(fig.data) > 0
    for tab in (P.tabela_anual(d), P.tabela_territorios(d), P.tabela_municipios(d)):
        assert tab.startswith('<div class="tabela-rolagem">')
    if P.projecao_valida(d):
        assert "Faixa de 80%" in P.tabela_projecao(d)
