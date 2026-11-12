# Segurança

## A chave da API

- A chave lê-se **apenas** da variável de ambiente `ANTHROPIC_API_KEY`. Nunca é escrita em ficheiros, nem mostrada nos printouts de debug.
- Não guardes a chave em ficheiros deste repositório. O `.gitignore` ignora `.env`, `*.key` e `*.pem` como segunda linha de defesa.
- Se uma chave for exposta por engano (num commit, num print, num chat), **revoga-a de imediato** na Claude Console e cria outra. Apagar o commit não chega: o histórico do Git e as cópias já feitas mantêm-na.

## A ferramenta `calcular`

A expressão vem do modelo, e indiretamente do utilizador, por isso é tratada como entrada não confiável:

- Não usa `eval()`. A expressão é analisada como árvore sintática (`ast`) e só são aceites números e operadores aritméticos.
- Limites contra bloqueios de CPU e memória: 300 caracteres por expressão, expoente máximo de 1000 e nenhum número, mesmo intermédio, acima de 10^100.
- Qualquer erro é devolvido ao modelo como `is_error`, sem derrubar o agente.

Estes limites estão cobertos por `testes/test_calculadora.py`.

## Relatórios do QA

`qa.py` grava em `qa_relatorios/` as entradas e as respostas completas do modelo. A pasta está no `.gitignore`. Se acrescentares casos de teste com dados reais, não publiques os relatórios.

## Reportar um problema

Abre uma issue sem incluir chaves, nem dados pessoais. Para algo sensível, usa "Report a vulnerability" no separador Security do GitHub.
