"""
Atualiza o Observatório do Emprego de ponta a ponta.

    python pipeline/atualizar.py                 # CAGED + MEI + consolidar + revisar
    python pipeline/atualizar.py --sem-publicar  # para antes de publicar
    python pipeline/atualizar.py --etapas consolidar,revisar
    python pipeline/atualizar.py --com-cnpj --mes 2026-11   # baixa e converte o dump antes
    python pipeline/atualizar.py --sem-projecao  # pula a projeção (~30-60 min)

Etapas, nesta ordem:
  caged       roda `exportar.py` do relatorio-emprego-formal (planilha mais recente
              em data/) e grava os contratos em dados/entrada
  mei         roda `uv run cnpj-observatorio` no Montar-BaseDados-CNPJ (dump mais
              recente em E:/cnpj); com --com-cnpj, antes baixa e converte o mês
  consolidar  junta contratos e manuais em dados/consolidado e valida
  projecao    roda o Projecao-empregos-Piaui em modo mensal (meta de config/pipeline.yml)
              e copia projecao_mensal.csv, projecao_anual.csv e projecao_resumo.json
  revisar     mostra o antes/depois, renderiza a página e pergunta se publica
  publicar    commita dados e página e roda `quarto publish gh-pages`

Uma etapa que falha interrompe a execução sem tocar no consolidado anterior.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import yaml

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from pipeline.consolidar import ErroValidacao, comparar, consolidar, gravar  # noqa: E402

ETAPAS = ("caged", "mei", "consolidar", "projecao", "revisar", "publicar")
ENTRADA = RAIZ / "dados" / "entrada"
LOGS = RAIZ / "logs"
ARQUIVOS_SITE = ["index.qmd", "_quarto.yml", "styles.css"]


class Log:
    def __init__(self):
        LOGS.mkdir(exist_ok=True)
        self.arquivo = LOGS / f"{datetime.now():%Y-%m-%d_%H%M%S}.log"

    def __call__(self, msg: str = "") -> None:
        print(msg, flush=True)
        with open(self.arquivo, "a", encoding="utf-8") as fp:
            fp.write(msg + "\n")


def rodar(cmd: list[str], cwd: Path, log: Log, env: dict | None = None) -> None:
    log(f"  $ {' '.join(map(str, cmd))}   (em {cwd})")
    proc = subprocess.Popen(
        cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", env=env,
    )
    assert proc.stdout is not None
    for linha in proc.stdout:
        log("    " + linha.rstrip())
    if proc.wait() != 0:
        raise SystemExit(f"falhou (código {proc.returncode}): {' '.join(map(str, cmd))}")


def etapa_caged(cfg: dict, args, log: Log) -> None:
    repo = Path(cfg["repositorios"]["caged"])
    rodar([cfg.get("python_caged", "python"), "exportar.py", "--saida", str(ENTRADA)],
          repo, log)


def etapa_mei(cfg: dict, args, log: Log) -> None:
    repo = Path(cfg["repositorios"]["cnpj"])
    dados = Path(cfg["cnpj_dados"])
    if not dados.exists():
        raise SystemExit(
            f"{dados} não está acessível (HD externo desconectado?). Conecte o HD ou "
            f"rode com --etapas sem 'mei' para manter o MEI da última execução."
        )
    if args.com_cnpj:
        if not args.mes:
            raise SystemExit("--com-cnpj exige --mes AAAA-MM")
        rodar(["uv", "run", "cnpj-baixar", "--destino", str(dados), "--mes", args.mes],
              repo, log)
        rodar(["uv", "run", "cnpj-converter", "--dados", str(dados), "--mes", args.mes,
               "--tmp", "C:/temp/cnpj", "--memoria", "8GB", "--threads", "4"], repo, log)
    cmd = ["uv", "run", "cnpj-observatorio", "--dados", str(dados), "--saida", str(ENTRADA)]
    if cfg.get("cnpj_tmp"):
        cmd += ["--tmp", cfg["cnpj_tmp"]]
    rodar(cmd, repo, log)


CONTRATOS_PROJECAO = ("projecao_mensal.csv", "projecao_anual.csv", "projecao_resumo.json")


def etapa_projecao(cfg: dict, args, log: Log) -> None:
    if args.sem_projecao:
        log("  --sem-projecao: mantida a projeção da última execução")
        return
    repo = Path(cfg["repositorios"]["projecao"]) / "Projecao-R"
    env = dict(os.environ, PROJ_FONTE="observatorio", PROJ_MODO="mensal",
               PROJ_OBSERVATORIO=str(RAIZ))
    rodar([cfg["rscript"], "R/99_executar_tudo.R"], repo, log, env=env)
    origem = repo / "saidas" / "observatorio"
    for nome in CONTRATOS_PROJECAO:
        shutil.copy2(origem / nome, ENTRADA / nome)
    resumo = json.loads((ENTRADA / "projecao_resumo.json").read_text(encoding="utf-8"))
    meta = json.loads((RAIZ / "dados" / "consolidado" / "metadados.json")
                      .read_text(encoding="utf-8"))
    for fonte in ("caged", "mei"):
        if resumo[f"competencia_{fonte}"] != meta[f"competencia_{fonte}"]:
            raise SystemExit(
                f"a projeção partiu de {fonte.upper()} {resumo[f'competencia_{fonte}']}, "
                f"mas o consolidado está em {meta[f'competencia_{fonte}']}"
            )
    log(f"  P(meta {resumo['meta']:,.0f} até {resumo['fim_meta']}) = "
        f"{100 * resumo['p_meta']:.1f}%  (IC {100 * resumo['ic_inf']:.1f}%"
        f"–{100 * resumo['ic_sup']:.1f}%); total mediano no fim: "
        f"{resumo['total_fim_mediana']:,.0f}".replace(",", "."))


def _anual_publicado() -> pd.DataFrame | None:
    p = RAIZ / "dados" / "consolidado" / "oportunidades_anual.csv"
    return pd.read_csv(p) if p.exists() else None


def etapa_consolidar(cfg: dict, args, log: Log) -> None:
    anterior = _anual_publicado()
    try:
        r = consolidar(RAIZ, cfg)
    except ErroValidacao as e:
        raise SystemExit(f"validação: {e}") from e
    tabela, avisos_rev = comparar(anterior, r.anual, float(cfg["limite_revisao_pct"]))
    r.avisos += avisos_rev
    gravar(RAIZ, r)
    log(f"  CAGED até {r.meta['competencia_caged']}, MEI até {r.meta['competencia_mei']}")
    log("  " + tabela.to_string().replace("\n", "\n  "))
    for a in r.avisos:
        log(f"  aviso: {a}")


def etapa_revisar(cfg: dict, args, log: Log) -> None:
    rodar(["quarto", "render"], RAIZ, log)
    log(f"  página renderizada em {RAIZ / '_site' / 'index.html'}")
    if args.sem_publicar:
        log("  --sem-publicar: página renderizada localmente, nada publicado")
        args.publicar_ok = False
        return
    resp = input("\nConferiu o antes/depois e a página renderizada? Publicar? [s/N] ")
    args.publicar_ok = resp.strip().lower() in ("s", "sim", "y")


def etapa_publicar(cfg: dict, args, log: Log) -> None:
    if not getattr(args, "publicar_ok", False):
        log("  publicação não confirmada; nada foi enviado")
        return
    meta = pd.read_json(RAIZ / "dados" / "consolidado" / "metadados.json", typ="series")
    msg = f"Atualiza dados: CAGED {meta['competencia_caged']}, MEI {meta['competencia_mei']}"
    rodar(["git", "add", "dados", "config", "pipeline", "tests", *ARQUIVOS_SITE], RAIZ, log)
    if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=RAIZ).returncode != 0:
        rodar(["git", "commit", "-m", msg], RAIZ, log)
    rodar(["quarto", "publish", "gh-pages", "--no-prompt", "--no-render"], RAIZ, log)


FUNCOES = {
    "caged": etapa_caged,
    "mei": etapa_mei,
    "consolidar": etapa_consolidar,
    "projecao": etapa_projecao,
    "revisar": etapa_revisar,
    "publicar": etapa_publicar,
}


def main(argv: list[str] | None = None) -> int:
    for fluxo in (sys.stdout, sys.stderr):
        try:
            fluxo.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--etapas", default=",".join(ETAPAS),
                    help=f"lista separada por vírgula (padrão: {','.join(ETAPAS)})")
    ap.add_argument("--sem-publicar", action="store_true",
                    help="renderiza a página mas não pergunta nem publica")
    ap.add_argument("--com-cnpj", action="store_true",
                    help="baixa e converte o dump do CNPJ antes do MEI (~40 min)")
    ap.add_argument("--mes", help="AAAA-MM do dump a baixar com --com-cnpj")
    ap.add_argument("--sem-projecao", action="store_true",
                    help="não roda a projeção (mantém a da última execução)")
    ap.add_argument("--config", default=str(RAIZ / "config" / "pipeline.yml"))
    args = ap.parse_args(argv)

    etapas = [e.strip() for e in args.etapas.split(",") if e.strip()]
    desconhecidas = set(etapas) - set(ETAPAS)
    if desconhecidas:
        ap.error(f"etapas desconhecidas: {', '.join(sorted(desconhecidas))}")
    if "revisar" not in etapas and "publicar" in etapas:
        ap.error("'publicar' exige 'revisar' (a confirmação acontece lá)")
    for ferramenta in ("quarto", "uv", "git"):
        if shutil.which(ferramenta) is None:
            ap.error(f"'{ferramenta}' não está no PATH")

    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    log = Log()
    log(f"Observatório do Emprego: {', '.join(etapas)}  (log em {log.arquivo})")
    for nome in ETAPAS:
        if nome in etapas:
            log(f"\n== {nome}")
            FUNCOES[nome](cfg, args, log)
    log("\nconcluído")
    return 0


if __name__ == "__main__":
    sys.exit(main())
