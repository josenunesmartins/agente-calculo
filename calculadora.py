"""
calculadora.py — a FERRAMENTA do agente.

Esta é a parte "mecânica" e determinística: recebe uma expressão aritmética
em texto (ex.: "(120 * 0.23) + 15") e devolve o resultado.

Porque não usar eval()?
    eval("__import__('os').system('rm -rf ~')") executaria esse código.
    Como a expressão vem do modelo (e, indiretamente, do utilizador),
    nunca a executamos como código Python. Em vez disso, analisamos a
    árvore sintática (ast) e só aceitamos números e operadores aritméticos.
"""

import ast
import math
import operator as op

# Operadores permitidos. Tudo o que não estiver aqui é recusado.
OPERADORES_BINARIOS = {
    ast.Add: op.add,        # +
    ast.Sub: op.sub,        # -
    ast.Mult: op.mul,       # *
    ast.Div: op.truediv,    # /
    ast.FloorDiv: op.floordiv,  # //
    ast.Mod: op.mod,        # %  (resto da divisão, não percentagem!)
    ast.Pow: op.pow,        # **
}
OPERADORES_UNARIOS = {
    ast.USub: op.neg,       # -x
    ast.UAdd: op.pos,       # +x
}

TAMANHO_MAXIMO = 300        # caracteres
EXPOENTE_MAXIMO = 1000      # evita 9**9**9 bloquear o computador
DIGITOS_MAXIMOS = 100       # nenhum número (nem intermédio) pode passar de 10**100
LIMITE = 10 ** DIGITOS_MAXIMOS


class ErroCalculo(ValueError):
    """Erro com uma mensagem clara, que é devolvida ao modelo."""


def _normalizar(expressao: str) -> str:
    """Aceita alguns símbolos 'humanos' que o modelo possa enviar."""
    return (
        expressao.replace("×", "*")
        .replace("÷", "/")
        .replace("^", "**")
        .replace("−", "-")   # sinal de menos tipográfico
        .strip()
    )


def _verificar_tamanho(valor):
    """Recusa números gigantes: protegem contra bloqueios por excesso de CPU/memória."""
    if isinstance(valor, (int, float)) and abs(valor) > LIMITE:
        raise ErroCalculo(f"Número demasiado grande (o limite é 10^{DIGITOS_MAXIMOS}).")
    return valor


def _potencia_segura(base, expoente):
    """Estima o tamanho do resultado ANTES de calcular a potência."""
    if abs(expoente) > EXPOENTE_MAXIMO:
        raise ErroCalculo(f"Expoente demasiado grande ({expoente}).")
    if abs(base) > 1 and expoente > 0 and expoente * math.log10(abs(base)) > DIGITOS_MAXIMOS:
        raise ErroCalculo(f"Número demasiado grande (o limite é 10^{DIGITOS_MAXIMOS}).")
    if base == 0 and expoente < 0:
        raise ErroCalculo("Divisão por zero: a conta não tem resultado.")
    return base ** expoente


def _avaliar(no):
    if isinstance(no, ast.Constant) and isinstance(no.value, (int, float)) \
            and not isinstance(no.value, bool):
        return _verificar_tamanho(no.value)

    if isinstance(no, ast.BinOp) and type(no.op) in OPERADORES_BINARIOS:
        esquerda = _avaliar(no.left)
        direita = _avaliar(no.right)
        if isinstance(no.op, ast.Pow):
            return _verificar_tamanho(_potencia_segura(esquerda, direita))
        if isinstance(no.op, (ast.Div, ast.FloorDiv, ast.Mod)) and direita == 0:
            raise ErroCalculo("Divisão por zero: a conta não tem resultado.")
        return _verificar_tamanho(OPERADORES_BINARIOS[type(no.op)](esquerda, direita))

    if isinstance(no, ast.UnaryOp) and type(no.op) in OPERADORES_UNARIOS:
        return OPERADORES_UNARIOS[type(no.op)](_avaliar(no.operand))

    raise ErroCalculo(
        f"Elemento não permitido na expressão: {type(no).__name__}. "
        "Só são aceites números, + - * / // % ** e parênteses."
    )


def _arrumar(valor):
    """6.0 -> 6 ; 0.1+0.2 -> 0.3 (remove o ruído de vírgula flutuante)."""
    if isinstance(valor, complex):
        raise ErroCalculo("O resultado não é um número real.")
    if isinstance(valor, float):
        if math.isinf(valor) or math.isnan(valor):
            raise ErroCalculo("O resultado não é um número finito.")
        valor = round(valor, 10)
        if valor.is_integer():
            return int(valor)
    return valor


def calcular(expressao: str):
    """Avalia uma expressão aritmética de forma segura. Lança ErroCalculo."""
    if not isinstance(expressao, str) or not expressao.strip():
        raise ErroCalculo("A expressão está vazia.")
    if len(expressao) > TAMANHO_MAXIMO:
        raise ErroCalculo(f"Expressão demasiado longa (máx. {TAMANHO_MAXIMO}).")

    texto = _normalizar(expressao)
    try:
        arvore = ast.parse(texto, mode="eval")
    except SyntaxError:
        raise ErroCalculo(
            f"Sintaxe inválida: {expressao!r}. Usa ponto como separador "
            "decimal (ex.: 2.5) e os operadores + - * / ** e parênteses."
        )
    try:
        return _arrumar(_avaliar(arvore.body))
    except ErroCalculo:
        raise
    except (OverflowError, ArithmeticError, ValueError, RecursionError, MemoryError) as erro:
        raise ErroCalculo(f"Erro aritmético: {type(erro).__name__}")


if __name__ == "__main__":
    # Pequena demonstração: python3 calculadora.py "2 + 3 * 4"
    import sys
    expr = " ".join(sys.argv[1:]) or "(2 + 3) * 4"
    try:
        print(f"{expr} = {calcular(expr)}")
    except ErroCalculo as e:
        print(f"Erro: {e}")
