"""
qa.py — "QA Control": valida o agente ANTES de o pôr a funcionar.

Etapas:
  1. Testes unitários da ferramenta (sem API, determinísticos).
  2. Verificação do ambiente (chave, pacote, ligação ao modelo).
  3. Bateria de testes: cada caso corre N vezes contra o modelo real.
     Em cada execução verifica-se:
       • execução   — correu sem erro e terminou antes do limite de iterações
       • formato    — terminou com "RESULTADO FINAL: ..."
       • valor      — o resultado bate com o esperado (dentro da tolerância)
       • ferramenta — usou (ou não usou) a ferramenta, conforme o caso
       • origem     — o valor final saiu de uma chamada à ferramenta,
                      e não de uma conta "de cabeça"
  4. Consistência: as N repetições do mesmo caso dão o mesmo resultado?
  5. Decisão: APROVADO só se
       • todos os testes unitários passarem,
       • a taxa de execuções certas for ≥ limiar (omissão: 90%),
       • os casos críticos passarem em TODAS as repetições,
       • nenhum caso falhar em todas as repetições.

Utilização:
    python3 qa.py                    # 3 repetições por caso
    python3 qa.py --repeticoes 5     # mais repetições = mais confiança
    python3 qa.py --rapido           # 1 repetição (só para iterar no prompt)
    python3 qa.py --caso iva         # corre só os casos cujo id contém 'iva'
    python3 qa.py --verbose          # mostra o raciocínio do agente em cada execução

Código de saída: 0 = APROVADO, 1 = REPROVADO (útil para CI, ex.: GitHub Actions).
"""

import argparse
import json
import os
import sys
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)

from agente import MODELO_POR_OMISSAO, executar_agente  # noqa: E402

COR = sys.stdout.isatty() and not os.environ.get("NO_COLOR")


def c(texto, codigo):
    return f"\033[{codigo}m{texto}\033[0m" if COR else texto


VERDE, VERMELHO, AMARELO, CIANO, CINZA = "1;32", "1;31", "1;33", "1;36", "2"
OK, KO = c("✔", VERDE), c("✘", VERMELHO)


def titulo(texto):
    print()
    print(c(f"■ {texto}", CIANO))
    print(c("─" * 72, CINZA))


# ─────────────────────────────────────────────────────────────────────────────
# Etapa 1 — testes unitários
# ─────────────────────────────────────────────────────────────────────────────
def etapa_testes_unitarios():
    titulo("1. Testes unitários da ferramenta 'calcular' (sem API)")
    suite = unittest.defaultTestLoader.discover(os.path.join(AQUI, "testes"), pattern="test_*.py")
    resultado = unittest.TextTestRunner(stream=open(os.devnull, "w"), verbosity=0).run(suite)
    falhas = resultado.failures + resultado.errors
    for teste, _ in falhas:
        print(f"  {KO} {teste.id()}")
    passou = resultado.wasSuccessful()
    print(f"  {OK if passou else KO} {resultado.testsRun - len(falhas)}/{resultado.testsRun} testes passaram")
    return passou, {"total": resultado.testsRun, "falhas": len(falhas)}


# ─────────────────────────────────────────────────────────────────────────────
# Etapa 2 — ambiente
# ─────────────────────────────────────────────────────────────────────────────
def etapa_ambiente(modelo):
    titulo("2. Verificação do ambiente")
    try:
        import anthropic
        print(f"  {OK} pacote anthropic {anthropic.__version__}")
    except ImportError:
        print(f"  {KO} pacote 'anthropic' não instalado (python3 -m pip install anthropic)")
        return None
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print(f"  {KO} variável ANTHROPIC_API_KEY não definida")
        return None
    print(f"  {OK} ANTHROPIC_API_KEY definida")
    cliente = anthropic.Anthropic(max_retries=4)
    try:
        cliente.messages.create(model=modelo, max_tokens=5,
                                messages=[{"role": "user", "content": "ok"}])
        print(f"  {OK} ligação ao modelo {modelo}")
    except anthropic.APIError as erro:
        print(f"  {KO} não foi possível usar o modelo {modelo}: {erro}")
        return None
    return cliente


# ─────────────────────────────────────────────────────────────────────────────
# Etapa 3 — avaliação de uma execução
# ─────────────────────────────────────────────────────────────────────────────
def _perto(a, b, tol):
    return abs(a - b) <= max(tol, 1e-9)


def _limpo(x):
    x = round(x, 4)
    return int(x) if float(x).is_integer() else x


def avaliar(caso, r):
    """Devolve um dicionário {verificação: (passou, detalhe)}."""
    tol = caso.get("tolerancia", 0)
    esperado = caso["esperado"]
    v = {}

    v["execução"] = (r["parou_por"] == "end_turn",
                     "ok" if r["parou_por"] == "end_turn" else f"parou por {r['parou_por']}")

    v["formato"] = (r["formato_ok"], "ok" if r["formato_ok"] else "sem 'RESULTADO FINAL' legível")

    obtido = r["valores"]
    if esperado is None:
        certo = r["formato_ok"] and obtido is None
    else:
        certo = (obtido is not None and len(obtido) == len(esperado)
                 and all(_perto(o, e, tol) for o, e in zip(obtido, esperado)))
    v["valor"] = (certo, f"esperado {esperado if esperado is not None else 'nenhum'}, "
                         f"obtido {obtido if obtido is not None else 'nenhum'}")

    n = len(r["chamadas"])
    deve = caso.get("deve_usar_ferramenta")
    if deve is True:
        v["ferramenta"] = (n > 0, f"{n} chamada(s)" + ("" if n else " — devia ter usado"))
    elif deve is False:
        v["ferramenta"] = (n == 0, f"{n} chamada(s)" + ("" if n == 0 else " — não devia ter usado"))

    if deve is True and esperado is not None and obtido is not None:
        da_ferramenta = []
        for ch in r["chamadas"]:
            if not ch["erro"]:
                try:
                    da_ferramenta.append(float(ch["resultado"]))
                except ValueError:
                    pass
        orfaos = [o for o in obtido
                  if not any(_perto(o, t, max(tol, 0.005)) for t in da_ferramenta)]
        v["origem"] = (not orfaos, "ok" if not orfaos else f"valor(es) {orfaos} não vieram da ferramenta")

    return v


def correr_uma(caso, repeticao, cliente, modelo, verbose):
    try:
        r = executar_agente(caso["entrada"], modelo=modelo, cliente=cliente, verbose=verbose)
        verif = avaliar(caso, r)
        erro = None
    except Exception as e:  # erro de API, rede, etc.
        r, verif, erro = None, {"execução": (False, f"{type(e).__name__}: {e}")}, str(e)
    passou = all(ok for ok, _ in verif.values())
    return {
        "id": caso["id"], "repeticao": repeticao, "passou": passou,
        "verificacoes": {k: {"ok": ok, "detalhe": d} for k, (ok, d) in verif.items()},
        "valores": r["valores"] if r else None,
        "chamadas": r["chamadas"] if r else [],
        "iteracoes": r["iteracoes"] if r else None,
        "tokens_entrada": r["tokens_entrada"] if r else 0,
        "tokens_saida": r["tokens_saida"] if r else 0,
        "duracao_s": r["duracao_s"] if r else 0,
        "resposta": r["resposta"] if r else None,
        "erro": erro,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Programa principal
# ─────────────────────────────────────────────────────────────────────────────
def main():
    p = argparse.ArgumentParser(description="QA Control do agente de cálculo.")
    p.add_argument("--repeticoes", type=int, default=3, help="execuções por caso (omissão: 3)")
    p.add_argument("--rapido", action="store_true", help="atalho para --repeticoes 1")
    p.add_argument("--caso", help="corre só os casos cujo id contém este texto")
    p.add_argument("--modelo", default=MODELO_POR_OMISSAO)
    p.add_argument("--limiar", type=float, default=0.90,
                   help="taxa mínima de execuções certas para aprovar (omissão: 0.90)")
    p.add_argument("--paralelo", type=int, default=4, help="execuções em simultâneo (omissão: 4)")
    p.add_argument("--verbose", action="store_true", help="mostra os printouts do agente (força --paralelo 1)")
    p.add_argument("--bateria", default=os.path.join(AQUI, "testes", "bateria.json"))
    args = p.parse_args()
    if args.rapido:
        args.repeticoes = 1
    if args.verbose:
        args.paralelo = 1

    print(c("╔════════════════════════════════════════════════════════════════════╗", CIANO))
    print(c("║                QA CONTROL — agente de cálculo                      ║", CIANO))
    print(c("╚════════════════════════════════════════════════════════════════════╝", CIANO))
    print(f"Modelo: {args.modelo}  |  Repetições por caso: {args.repeticoes}  |  Limiar: {args.limiar:.0%}")

    relatorio = {"data": datetime.now().isoformat(timespec="seconds"), "modelo": args.modelo,
                 "repeticoes": args.repeticoes, "limiar": args.limiar}
    razoes = []

    # 1
    unit_ok, relatorio["testes_unitarios"] = etapa_testes_unitarios()
    if not unit_ok:
        razoes.append("os testes unitários da ferramenta falharam")
        return decidir(razoes, relatorio, parar=True)

    # 2
    cliente = etapa_ambiente(args.modelo)
    if cliente is None:
        razoes.append("o ambiente não está pronto")
        return decidir(razoes, relatorio, parar=True)

    # 3
    with open(args.bateria, encoding="utf-8") as f:
        casos = json.load(f)["casos"]
    if args.caso:
        casos = [k for k in casos if args.caso in k["id"]]
        if not casos:
            print(f"Nenhum caso com '{args.caso}' no id.")
            return 1

    titulo(f"3. Bateria de testes ({len(casos)} casos × {args.repeticoes} = "
           f"{len(casos) * args.repeticoes} execuções)")
    trabalho = [(k, rep) for k in casos for rep in range(1, args.repeticoes + 1)]
    execucoes, lock, feitas = [], threading.Lock(), 0
    t0 = time.time()

    def registar(e):
        nonlocal feitas
        with lock:
            feitas += 1
            execucoes.append(e)
            falhadas = [k for k, x in e["verificacoes"].items() if not x["ok"]]
            info = (f"{len(e['chamadas'])} chamada(s), {e['iteracoes'] or '-'} iter, {e['duracao_s']:.1f}s"
                    if not e["erro"] else e["erro"][:60])
            print(f"  [{feitas:>3}/{len(trabalho)}] {OK if e['passou'] else KO} "
                  f"{e['id']:<22} rep {e['repeticao']}  "
                  f"{c(info, CINZA)}"
                  + ("" if e["passou"] else "  " + c("falhou: " + ", ".join(falhadas), VERMELHO)))

    if args.paralelo > 1:
        with ThreadPoolExecutor(max_workers=args.paralelo) as pool:
            futuros = [pool.submit(correr_uma, k, rep, cliente, args.modelo, False) for k, rep in trabalho]
            for fut in as_completed(futuros):
                registar(fut.result())
    else:
        for k, rep in trabalho:
            registar(correr_uma(k, rep, cliente, args.modelo, args.verbose))

    # 4
    titulo("4. Resultados por caso e consistência")
    print(f"  {'caso':<22} {'categoria':<18} {'certas':>7}  {'estado':<10} resultados obtidos")
    por_caso, estaveis = [], 0
    for k in casos:
        ex = [e for e in execucoes if e["id"] == k["id"]]
        certas = sum(e["passou"] for e in ex)
        distintos = {json.dumps([_limpo(x) for x in e["valores"]] if e["valores"] else "nenhum") for e in ex}
        consistente = len(distintos) == 1
        estaveis += consistente
        if certas == len(ex):
            estado = c("ESTÁVEL", VERDE)
        elif certas == 0:
            estado = c("FALHA", VERMELHO)
        else:
            estado = c("INSTÁVEL", AMARELO)
        marca = c(" (crítico)", CINZA) if k.get("critico") else ""
        print(f"  {k['id']:<22} {k['categoria']:<18} {certas:>3}/{len(ex):<3}  {estado:<10} "
              f"{', '.join(sorted(distintos))}{marca}")
        for e in ex:   # mostra o detalhe das falhas
            for nome, x in e["verificacoes"].items():
                if not x["ok"]:
                    print(c(f"      rep {e['repeticao']} · {nome}: {x['detalhe']}", CINZA))
        por_caso.append({"id": k["id"], "certas": certas, "total": len(ex),
                         "consistente": consistente, "critico": bool(k.get("critico"))})
        if certas == 0:
            razoes.append(f"o caso '{k['id']}' falhou em todas as repetições")
        elif k.get("critico") and certas < len(ex):
            razoes.append(f"o caso crítico '{k['id']}' falhou em {len(ex) - certas} de {len(ex)} execuções")

    total = len(execucoes)
    certas = sum(e["passou"] for e in execucoes)
    taxa = certas / total if total else 0
    consistencia = estaveis / len(casos) if casos else 0
    tokens_in = sum(e["tokens_entrada"] for e in execucoes)
    tokens_out = sum(e["tokens_saida"] for e in execucoes)
    chamadas = [len(e["chamadas"]) for e in execucoes if not e["erro"]]
    duracoes = [e["duracao_s"] for e in execucoes if not e["erro"]]

    titulo("5. Métricas")
    print(f"  Taxa de sucesso       {taxa:>7.1%}   ({certas}/{total} execuções certas, mínimo {args.limiar:.0%})")
    print(f"  Consistência          {consistencia:>7.1%}   ({estaveis}/{len(casos)} casos com o mesmo resultado em todas as repetições)")
    if chamadas:
        print(f"  Chamadas à ferramenta {sum(chamadas) / len(chamadas):>7.1f}   em média por execução")
        print(f"  Tempo por execução    {sum(duracoes) / len(duracoes):>6.1f}s   em média (total do QA: {time.time() - t0:.0f}s)")
    print(f"  Tokens                {tokens_in:>7}   entrada  /  {tokens_out} saída")

    if taxa < args.limiar:
        razoes.append(f"a taxa de sucesso ({taxa:.1%}) está abaixo do limiar ({args.limiar:.0%})")

    relatorio.update({"taxa_sucesso": taxa, "consistencia": consistencia,
                      "tokens_entrada": tokens_in, "tokens_saida": tokens_out,
                      "por_caso": por_caso, "execucoes": execucoes})
    return decidir(razoes, relatorio)


def decidir(razoes, relatorio, parar=False):
    aprovado = not razoes
    relatorio["aprovado"] = aprovado
    relatorio["razoes"] = razoes

    pasta = os.path.join(AQUI, "qa_relatorios")
    os.makedirs(pasta, exist_ok=True)
    ficheiro = os.path.join(pasta, f"qa_{datetime.now():%Y%m%d_%H%M%S}.json")
    with open(ficheiro, "w", encoding="utf-8") as f:
        json.dump(relatorio, f, ensure_ascii=False, indent=2)

    titulo("Decisão" if not parar else "Decisão (QA interrompido)")
    if aprovado:
        print(c("  ✔ APROVADO — o agente pode ser ligado.", VERDE))
    else:
        print(c("  ✘ REPROVADO — não ligar o agente. Razões:", VERMELHO))
        for r in razoes:
            print(f"    • {r}")
    print(c(f"\n  Relatório completo: {os.path.relpath(ficheiro)}", CINZA))
    return 0 if aprovado else 1


if __name__ == "__main__":
    sys.exit(main())
