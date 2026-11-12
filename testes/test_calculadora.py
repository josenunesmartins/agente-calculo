"""
Testes unitários da ferramenta `calcular`.

Não usam a API: testam só o código determinístico. Se isto falhar, o
problema está no nosso código, não no modelo.

    python3 -m unittest testes/test_calculadora.py -v
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from calculadora import ErroCalculo, calcular  # noqa: E402


class TestContas(unittest.TestCase):
    def test_operacoes_basicas(self):
        self.assertEqual(calcular("1234 + 5678"), 6912)
        self.assertEqual(calcular("10 - 15"), -5)
        self.assertEqual(calcular("6 * 7"), 42)
        self.assertEqual(calcular("86 / 4"), 21.5)

    def test_prioridade_e_parenteses(self):
        self.assertEqual(calcular("2 + 3 * 4"), 14)
        self.assertEqual(calcular("(2 + 3) * 4"), 20)

    def test_potencia_e_resto(self):
        self.assertEqual(calcular("2 ** 10"), 1024)
        self.assertEqual(calcular("17 % 5"), 2)
        self.assertEqual(calcular("17 // 5"), 3)

    def test_decimais_arrumados(self):
        self.assertEqual(calcular("0.1 + 0.2"), 0.3)
        self.assertEqual(calcular("800 * 1.23"), 984)
        self.assertIsInstance(calcular("12 / 4"), int)

    def test_simbolos_humanos(self):
        self.assertEqual(calcular("(2 + 3) × 4"), 20)
        self.assertEqual(calcular("10 ÷ 4"), 2.5)
        self.assertEqual(calcular("2 ^ 3"), 8)

    def test_negativos(self):
        self.assertEqual(calcular("-5 + 3"), -2)


class TestErros(unittest.TestCase):
    def test_divisao_por_zero(self):
        with self.assertRaises(ErroCalculo):
            calcular("10 / 0")

    def test_sintaxe_invalida(self):
        for expr in ["2 +", "21,5 * 2", "", "   "]:
            with self.subTest(expr=expr), self.assertRaises(ErroCalculo):
                calcular(expr)

    def test_expoente_gigante(self):
        with self.assertRaises(ErroCalculo):
            calcular("9 ** 9 ** 9")

    def test_numeros_gigantes(self):
        """Evitam bloqueios de CPU/memória e erros ao converter para texto."""
        for expr in ["(9 ** 999) ** 999", "((9 ** 999) ** 999) ** 999",
                     "9 ** 999 * 9 ** 999", "1" + "0" * 150, "10 ** 101", "(10 ** 60) * (10 ** 60)"]:
            with self.subTest(expr=expr), self.assertRaises(ErroCalculo):
                calcular(expr)

    def test_limite_aceita_numeros_normais(self):
        self.assertEqual(calcular("10 ** 100"), 10 ** 100)
        self.assertEqual(calcular("2 ** -2"), 0.25)

    def test_zero_elevado_a_negativo(self):
        with self.assertRaises(ErroCalculo):
            calcular("0 ** -1")

    def test_expressao_demasiado_longa(self):
        with self.assertRaises(ErroCalculo):
            calcular("1+" * 200 + "1")


class TestSeguranca(unittest.TestCase):
    """O mais importante: nada que não seja aritmética pode ser executado."""

    def test_recusa_codigo(self):
        perigosas = [
            "__import__('os').system('ls')",
            "open('/etc/passwd').read()",
            "print(1)",
            "x",
            "[1, 2, 3]",
            "'texto' * 3",
            "lambda: 1",
            "True + 1",
            "(1).__class__",
        ]
        for expr in perigosas:
            with self.subTest(expr=expr), self.assertRaises(ErroCalculo):
                calcular(expr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
