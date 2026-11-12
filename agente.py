"""
agente.py — um agente que lê texto livre, descobre que contas tem de fazer
e devolve os resultados.

Os três ingredientes de um agente estão marcados no código:

    [1] SYSTEM PROMPT  -> o "papel" e as regras do agente
    [2] TOOLS          -> o que o agente pode FAZER (aqui: calcular)
    [3] ENVIRONMENT    -> onde as ferramentas correm e o que devolvem
                          (aqui: o teu computador, a correr Python)

E o motor que os liga:

    [4] O CICLO (agent loop) -> pergunta ao modelo, executa as ferramentas
                                que ele pedir, devolve os resultados, repete.

Utilização:
    python3 agente.py                      # modo interativo (pede o texto)
    python3 agente.py "Quanto é 2+3*4?"    # uma só pergunta
    python3 agente.py --silencioso         # sem printouts de debug
    python3 agente.py --json               # mostra também o JSON trocado com a API
"""

import argparse
import json
import os
import re
import sys
import time

from calculadora import ErroCalculo, calcular

MODELO_POR_OMISSAO = os.environ.get("AGENTE_MODELO", "claude-sonnet-5-5")
MAX_ITERACOES = 10

# ─────────────────────────────────────────────────────────────────────────────
# [1] SYSTEM PROMPT
# ─────────────────────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """\
És um agente de cálculo. Recebes um texto em português que pode conter
problemas de matemática, contas explícitas, números soltos ou nenhuma conta.

O teu trabalho:
1. Lê o texto e identifica que contas são realmente pedidas. Ignora números
   que não fazem parte de nenhuma conta (moradas, datas, telefones, idades
   que não entram no problema).
2. Antes de cada chamada à ferramenta, escreve uma frase curta a explicar o
   que vais calcular e porquê.
3. Usa SEMPRE a ferramenta `calcular` para qualquer conta, por mais simples
   que seja. Nunca faças contas de cabeça.
4. Converte números escritos por extenso em algarismos (ex.: "vinte e três"
   -> 23) e percentagens em decimais (ex.: 23% -> 0.23).
5. Se a ferramenta devolver um erro, corrige a expressão e tenta de novo,
   ou explica porque a conta não é possível.
6. Se o texto for ambíguo, escolhe a interpretação mais razoável e diz qual
   escolheste.

Formato da resposta final:
- Explica em poucas linhas as contas que fizeste e o resultado de cada uma.
- Termina SEMPRE com uma linha exatamente neste formato:
    RESULTADO FINAL: <valor>
  em que <valor> é o número pedido, com ponto decimal e sem separador de
  milhares nem unidades (ex.: RESULTADO FINAL: 1061.21).
- Se forem pedidos vários resultados independentes, separa-os com ponto e
  vírgula, pela ordem em que aparecem no texto (ex.: RESULTADO FINAL: 60; 63).
- Se não houver nenhuma conta a fazer, ou se a conta for impossível, escreve:
    RESULTADO FINAL: nenhum
"""

# ─────────────────────────────────────────────────────────────────────────────
# [2] TOOLS — a descrição que o MODELO lê para decidir quando usar a ferramenta
# ─────────────────────────────────────────────────────────────────────────────
FERRAMENTAS = [
    {
        "name": "calcular",
        "description": (
            "Avalia uma expressão aritmética e devolve o resultado exato. "
            "Usa-a para TODAS as contas. Aceita números com ponto decimal, "
            "os operadores + - * / // % ** e parênteses. Atenção: % é o resto "
            "da divisão, não percentagem; para 23% usa 0.23. "
            "Exemplo: '(800 * 1.23) - 15'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "expressao": {
                    "type": "string",
                    "description": "A expressão a calcular, ex.: '3 * 12 - 5'.",
                },
                "motivo": {
                    "type": "string",
                    "description": "Em poucas palavras, o que esta conta representa no problema.",
                },
            },
            "required": ["expressao", "motivo"],
        },
    }
]


# ─────────────────────────────────────────────────────────────────────────────
# [3] ENVIRONMENT — o código que corre do nosso lado quando o modelo pede
# ─────────────────────────────────────────────────────────────────────────────
def executar_ferramenta(nome: str, argumentos: dict):
    """Devolve (texto_do_resultado, é_erro)."""
    if nome != "calcular":
        return f"Ferramenta desconhecida: {nome}", True
    try:
        return str(calcular(argumentos.get("expressao", ""))), False
    except ErroCalculo as erro:
        return f"ERRO: {erro}", True
    except Exception as erro:  # defesa em profundidade: nunca deixar a ferramenta derrubar o agente
        return f"ERRO inesperado na ferramenta: {type(erro).__name__}", True


# ─────────────────────────────────────────────────────────────────────────────
# Printouts de debug (só para ilustrar como o agente "pensa")
# ─────────────────────────────────────────────────────────────────────────────
class Debug:
    CORES = {
        "titulo": "\033[1;36m", "pedido": "\033[1;34m", "resposta": "\033[1;35m",
        "ferramenta": "\033[1;33m", "ok": "\033[1;32m", "erro": "\033[1;31m",
        "cinza": "\033[2m", "fim": "\033[0m",
    }

    def __init__(self, ativo=True, json_completo=False):
        self.ativo = ativo
        self.json_completo = json_completo
        self.cor = sys.stdout.isatty() and not os.environ.get("NO_COLOR")

    def _c(self, nome, texto):
        if not self.cor:
            return texto
        return f"{self.CORES[nome]}{texto}{self.CORES['fim']}"

    def __call__(self, texto="", cor=None):
        if self.ativo:
            print(self._c(cor, texto) if cor else texto)

    def bloco(self, texto, prefixo="   │ "):
        if self.ativo:
            for linha in str(texto).splitlines() or [""]:
                print(self._c("cinza", prefixo) + linha)

    def json(self, titulo, dados):
        if self.ativo and self.json_completo:
            self(f"   {titulo}:", "cinza")
            self.bloco(json.dumps(dados, ensure_ascii=False, indent=2, default=str))


def _resumir(texto, limite=200):
    texto = " ".join(str(texto).split())
    return texto if len(texto) <= limite else texto[: limite - 1] + "…"


def _para_json(conteudo):
    """Converte os blocos do SDK em dicionários simples (para mostrar)."""
    if isinstance(conteudo, str):
        return conteudo
    return [b.model_dump() if hasattr(b, "model_dump") else b for b in conteudo]


# ─────────────────────────────────────────────────────────────────────────────
# Leitura da linha "RESULTADO FINAL: ..." (usada também pelo QA)
# ─────────────────────────────────────────────────────────────────────────────
_PADRAO_RESULTADO = re.compile(r"RESULTADO FINAL\s*:\s*(.+)", re.IGNORECASE)


def extrair_resultado(texto: str):
    """
    Devolve (formato_ok, valores):
      - (True, [60.0, 63.0])  para "RESULTADO FINAL: 60; 63"
      - (True, None)          para "RESULTADO FINAL: nenhum"
      - (False, None)         se a linha não existir ou não for legível
    """
    encontrados = _PADRAO_RESULTADO.findall(texto or "")
    if not encontrados:
        return False, None
    valor = encontrados[-1].strip().strip("*`. ")
    if valor.lower().startswith("nenhum"):
        return True, None
    valores = []
    for parte in valor.split(";"):
        parte = parte.strip().replace(" ", "").replace("€", "")
        if "," in parte and "." not in parte:   # 21,5 -> 21.5
            parte = parte.replace(",", ".")
        numero = re.search(r"-?\d+(?:\.\d+)?", parte)
        if not numero:
            return False, None
        valores.append(float(numero.group()))
    return True, valores


# ─────────────────────────────────────────────────────────────────────────────
# [4] O CICLO DO AGENTE
# ─────────────────────────────────────────────────────────────────────────────
def executar_agente(texto, modelo=MODELO_POR_OMISSAO, cliente=None,
                    verbose=True, json_completo=False, max_iteracoes=MAX_ITERACOES):
    """Corre o agente sobre um texto e devolve um dicionário com tudo o que aconteceu."""
    if cliente is None:
        import anthropic
        cliente = anthropic.Anthropic(max_retries=4)

    dbg = Debug(verbose, json_completo)
    inicio = time.time()
    chamadas = []          # todas as chamadas à ferramenta (para o QA)
    tokens_in = tokens_out = 0
    resposta_final = ""
    parou_por = "limite_iteracoes"

    # A "memória" do agente é só esta lista: a conversa até agora.
    mensagens = [{"role": "user", "content": texto}]

    dbg()
    dbg("══════════════════════ INÍCIO DO AGENTE ══════════════════════", "titulo")
    dbg(f"Modelo: {modelo}   |   Máximo de iterações: {max_iteracoes}")
    dbg("System prompt (as regras que o modelo recebe em CADA chamada):", "cinza")
    dbg.bloco(SYSTEM_PROMPT.strip())
    dbg(f"Ferramentas disponíveis: {', '.join(f['name'] for f in FERRAMENTAS)}", "cinza")

    iteracao = 0
    for iteracao in range(1, max_iteracoes + 1):
        dbg()
        dbg(f"━━━━━━━━━━━━━━━━━━━━━━━━ Iteração {iteracao} ━━━━━━━━━━━━━━━━━━━━━━━━", "titulo")

        # ── 1. Enviar a conversa ao Claude ──────────────────────────────────
        ultima = mensagens[-1]
        dbg(f"→ PEDIDO ao Claude  ({len(mensagens)} mensagem(ns) na conversa)", "pedido")
        if isinstance(ultima["content"], str):
            dbg.bloco(f"última mensagem [{ultima['role']}]: \"{_resumir(ultima['content'])}\"")
        else:
            dbg.bloco(f"última mensagem [{ultima['role']}]: {len(ultima['content'])} resultado(s) de ferramenta")
        dbg.json("mensagens enviadas", [{"role": m["role"], "content": _para_json(m["content"])} for m in mensagens])

        t0 = time.time()
        resposta = cliente.messages.create(
            model=modelo,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            tools=FERRAMENTAS,
            messages=mensagens,
        )
        duracao = time.time() - t0
        tokens_in += resposta.usage.input_tokens
        tokens_out += resposta.usage.output_tokens

        # ── 2. Ver o que o Claude respondeu ─────────────────────────────────
        dbg(f"← RESPOSTA do Claude  ({duracao:.1f} s, "
            f"{resposta.usage.input_tokens} tokens entrada / {resposta.usage.output_tokens} saída)", "resposta")
        dbg.bloco(f"stop_reason: {resposta.stop_reason}"
                  + ("   (quer usar uma ferramenta)" if resposta.stop_reason == "tool_use"
                     else "   (terminou, sem mais pedidos)" if resposta.stop_reason == "end_turn" else ""))
        for bloco in resposta.content:
            if bloco.type == "text" and bloco.text.strip():
                dbg.bloco("💭 texto:")
                dbg.bloco(bloco.text.strip(), prefixo="   │    ")
            elif bloco.type == "tool_use":
                dbg.bloco(f"🔧 pede ferramenta: {bloco.name}({json.dumps(bloco.input, ensure_ascii=False)})")
        dbg.json("resposta completa", resposta.model_dump())

        # A resposta do modelo entra na conversa (o modelo não tem memória própria).
        mensagens.append({"role": "assistant", "content": resposta.content})

        # ── 3. Terminou? ─────────────────────────────────────────────────────
        if resposta.stop_reason != "tool_use":
            resposta_final = "\n".join(b.text for b in resposta.content if b.type == "text").strip()
            parou_por = resposta.stop_reason
            break

        # ── 4. Executar localmente as ferramentas pedidas ────────────────────
        resultados = []
        for bloco in resposta.content:
            if bloco.type != "tool_use":
                continue
            resultado, e_erro = executar_ferramenta(bloco.name, bloco.input)
            chamadas.append({
                "expressao": bloco.input.get("expressao"),
                "motivo": bloco.input.get("motivo"),
                "resultado": resultado,
                "erro": e_erro,
            })
            dbg(f"⚙  EXECUÇÃO LOCAL: {bloco.name}(\"{bloco.input.get('expressao')}\")", "ferramenta")
            dbg.bloco(f"motivo indicado pelo modelo: {bloco.input.get('motivo', '—')}")
            dbg.bloco(f"resultado: {resultado}", prefixo="   └ ")
            resultados.append({
                "type": "tool_result",
                "tool_use_id": bloco.id,
                "content": resultado,
                "is_error": e_erro,
            })

        # ── 5. Devolver os resultados ao Claude e repetir ───────────────────
        mensagens.append({"role": "user", "content": resultados})
        dbg(f"↩  {len(resultados)} resultado(s) devolvido(s) ao Claude como tool_result. Volta ao início do ciclo.", "cinza")

    formato_ok, valores = extrair_resultado(resposta_final)
    total = time.time() - inicio

    dbg()
    dbg("═══════════════════════ FIM DO AGENTE ═══════════════════════", "titulo")
    dbg(f"Iterações: {iteracao}  |  Chamadas à ferramenta: {len(chamadas)}  |  "
        f"Tokens: {tokens_in} entrada / {tokens_out} saída  |  Tempo: {total:.1f} s", "cinza")
    if parou_por == "limite_iteracoes":
        dbg("⚠ O agente atingiu o limite de iterações sem terminar.", "erro")
    if not formato_ok:
        dbg("⚠ A resposta não terminou com 'RESULTADO FINAL: ...'.", "erro")

    return {
        "resposta": resposta_final,
        "formato_ok": formato_ok,
        "valores": valores,
        "chamadas": chamadas,
        "iteracoes": iteracao,
        "parou_por": parou_por,
        "tokens_entrada": tokens_in,
        "tokens_saida": tokens_out,
        "duracao_s": round(total, 2),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Programa interativo
# ─────────────────────────────────────────────────────────────────────────────
def _verificar_chave():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Falta a variável ANTHROPIC_API_KEY. No terminal, faz:\n"
              '    export ANTHROPIC_API_KEY="sk-ant-..."')
        sys.exit(1)


def _mostrar(resultado):
    print()
    print("┌─ RESPOSTA DO AGENTE " + "─" * 40)
    for linha in (resultado["resposta"] or "(sem texto)").splitlines():
        print("│ " + linha)
    print("└" + "─" * 61)


def main():
    parser = argparse.ArgumentParser(description="Agente que resolve contas escritas em texto livre.")
    parser.add_argument("texto", nargs="*", help="texto a resolver (se omitido, entra em modo interativo)")
    parser.add_argument("--modelo", default=MODELO_POR_OMISSAO)
    parser.add_argument("--silencioso", action="store_true", help="esconde os printouts de debug")
    parser.add_argument("--json", action="store_true", help="mostra também o JSON completo trocado com a API")
    args = parser.parse_args()

    _verificar_chave()
    import anthropic
    cliente = anthropic.Anthropic(max_retries=4)

    def correr(texto):
        try:
            r = executar_agente(texto, modelo=args.modelo, cliente=cliente,
                                verbose=not args.silencioso, json_completo=args.json)
            _mostrar(r)
        except anthropic.APIError as erro:
            print(f"\nErro da API: {erro}")

    if args.texto:
        correr(" ".join(args.texto))
        return

    print("Agente de cálculo. Escreve um texto com contas e carrega em Enter.")
    print("Para sair: escreve 'sair' ou carrega em Ctrl+D.")
    while True:
        try:
            texto = input("\n📝 O teu texto: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nAté à próxima.")
            break
        if not texto:
            continue
        if texto.lower() in {"sair", "exit", "quit"}:
            print("Até à próxima.")
            break
        correr(texto)


if __name__ == "__main__":
    main()
