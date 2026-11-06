"""Testes da consolidação: regras do MEI congelado, validações e revisões."""

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.consolidar import ErroValidacao, comparar, consolidar, gravar  # noqa: E402

CFG = {"ano_inicio": 2023, "mei_congelado_ate": 2024, "incluir_bolsas": False}


def _meses(ini, fim):
    return pd.period_range(ini, fim, freq="M").astype(str)


@pytest.fixture
def raiz(tmp_path):
    ent, man = tmp_path / "dados" / "entrada", tmp_path / "dados" / "manual"
    ent.mkdir(parents=True)
    man.mkdir(parents=True)
    comps = _meses("2022-11", "2025-03")
    pd.DataFrame({"competencia": comps, "admissoes": 0, "desligamentos": 0,
                  "saldo": 10, "estoque": 0}).to_csv(ent / "caged_pi_mensal.csv", index=False)
    pd.DataFrame({"competencia": _meses("2023-01", "2025-03"), "abertos_mei": 5,
                  "fechados_mei": 2, "saldo_mei": 3}).to_csv(ent / "mei_pi_mensal.csv",
                                                            index=False)
    pd.DataFrame({"ano": [2023, 2024], "mei": [100, 200]}).to_csv(
        man / "mei_mapa_empresas.csv", index=False)
    pd.DataFrame({"ano": [2023, 2024, 2025], "concursados": [7, 8, 9]}).to_csv(
        man / "concursados.csv", index=False)
    pd.DataFrame({"ano": [2023, 2024, 2025], "bolsas": [1, 1, 1]}).to_csv(
        man / "bolsas.csv", index=False)
    return tmp_path


def test_mei_congelado_e_dump(raiz):
    r = consolidar(raiz, CFG)
    a = r.anual.set_index("ano")
    # 2023 e 2024 vêm do painel; 2025 do dump (3 meses x 3)
    assert a.loc[2023, "mei"] == 100 and a.loc[2023, "mei_fonte"] == "mapa_empresas"
    assert a.loc[2024, "mei"] == 200
    assert a.loc[2025, "mei"] == 9 and a.loc[2025, "mei_fonte"] == "cnpj"
    # CAGED começa em jan/2023, mesmo com dados anteriores no contrato
    assert a.loc[2023, "caged"] == 120 and a.loc[2025, "meses_caged"] == 3
    assert a.loc[2025, "total"] == 30 + 9 + 9
    assert "bolsas" not in r.anual.columns
    # o mensal só traz MEI nos meses do dump
    assert r.mensal.set_index("competencia").loc["2024-12", "mei"] is pd.NA
    assert r.mensal.set_index("competencia").loc["2025-01", "mei"] == 3


def test_bolsas_quando_incluidas(raiz):
    r = consolidar(raiz, dict(CFG, incluir_bolsas=True))
    assert r.anual.set_index("ano").loc[2025, "total"] == 30 + 9 + 9 + 1


def test_buraco_no_caged_bloqueia(raiz):
    p = raiz / "dados" / "entrada" / "caged_pi_mensal.csv"
    df = pd.read_csv(p)
    df[df.competencia != "2024-06"].to_csv(p, index=False)
    with pytest.raises(ErroValidacao, match="2024-06"):
        consolidar(raiz, CFG)


def test_ano_congelado_faltando_bloqueia(raiz):
    p = raiz / "dados" / "manual" / "mei_mapa_empresas.csv"
    pd.DataFrame({"ano": [2023], "mei": [100]}).to_csv(p, index=False)
    with pytest.raises(ErroValidacao, match="2024"):
        consolidar(raiz, CFG)


def test_competencias_diferentes_geram_aviso(raiz):
    p = raiz / "dados" / "entrada" / "mei_pi_mensal.csv"
    df = pd.read_csv(p)
    df[df.competencia <= "2025-02"].to_csv(p, index=False)
    r = consolidar(raiz, CFG)
    assert any("MEI até 2025-02" in a for a in r.avisos)


def test_revisao_de_ano_fechado(raiz):
    r = consolidar(raiz, CFG)
    anterior = r.anual.copy()
    anterior.loc[anterior.ano == 2023, "caged"] = 100  # agora é 120: +20%
    anterior.loc[anterior.ano == 2025, "caged"] = 1  # ano corrente não avisa
    _, avisos = comparar(anterior, r.anual, limite_pct=2.0)
    assert avisos == ["caged 2023 mudou +20.0% (100 -> 120)"]


def test_gravar(raiz):
    r = consolidar(raiz, CFG)
    gravar(raiz, r)
    out = raiz / "dados" / "consolidado"
    assert (out / "oportunidades_anual.csv").exists()
    assert b"\r\n" not in (out / "oportunidades_mensal.csv").read_bytes()
