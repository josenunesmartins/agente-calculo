# Agente de cálculo

Um agente que recebe texto livre, percebe que contas tem de fazer e devolve
os resultados. Serve para aprender como funciona um agente por dentro.

## Ficheiros

| Ficheiro | O que é |
|---|---|
| `agente.py` | O agente: system prompt, ferramenta, ciclo e modo interativo, com printouts de debug |
| `calculadora.py` | A ferramenta `calcular`: avalia expressões de forma segura (sem `eval`) |
| `testes/bateria.json` | 20 casos de teste com o resultado esperado |
| `testes/test_calculadora.py` | Testes unitários da ferramenta (não usam a API) |
| `qa.py` | QA Control: corre tudo e decide se o agente pode ser ligado |
| `qa_relatorios/` | Criada pelo QA, com um relatório JSON por execução (fora do Git) |
| `SECURITY.md` | Como a chave e a ferramenta estão protegidas |

## Os três ingredientes, no código

- **System prompt** → `SYSTEM_PROMPT` em `agente.py`: o papel e as regras.
- **Tools** → `FERRAMENTAS` em `agente.py`: a descrição que o modelo lê.
- **Environment** → `executar_ferramenta()` e `calculadora.py`: o código que
  corre no teu computador quando o modelo pede uma ferramenta.
- **O ciclo** → `executar_agente()`: pede, executa, devolve, repete.

## Preparar (uma vez)

```bash
cd ~/src/agente-calculo
python3 -m pip install -r requirements.txt
export ANTHROPIC_API_KEY="sk-ant-..."
```

## Ordem recomendada

```bash
# 1. Testes da ferramenta (grátis, sem API)
python3 -m unittest discover testes -v

# 2. QA Control antes de ligar o agente
python3 qa.py --rapido          # 1 repetição, ~20 chamadas, para ir afinando
python3 qa.py                   # 3 repetições, a validação "a sério"

# 3. Só depois de APROVADO, usar o agente
python3 agente.py
```

## Usar o agente

```bash
python3 agente.py                       # pede o texto; Enter para submeter; 'sair' para terminar
python3 agente.py "Quanto é 2+3*4?"     # uma só pergunta
python3 agente.py --json                # mostra também o JSON trocado com a API
python3 agente.py --silencioso          # só a resposta
python3 agente.py --modelo claude-haiku-5-5   # modelo mais rápido e barato
```

## O que o QA verifica

Em cada execução de cada caso:

- **execução**: terminou sem erro e antes do limite de iterações;
- **formato**: acabou com `RESULTADO FINAL: ...`;
- **valor**: o resultado bate com o esperado;
- **ferramenta**: usou (ou não usou) a ferramenta, conforme o caso;
- **origem**: o valor final saiu da ferramenta, e não de uma conta "de cabeça".

E por caso, ao longo das repetições, a **consistência** (deu sempre o mesmo resultado?).

O QA só **aprova** se: os testes unitários passarem, a taxa de sucesso for
≥ 90% (`--limiar`), os casos críticos passarem em todas as repetições e
nenhum caso falhar em todas as repetições. Devolve o código de saída 0 se
aprovar e 1 se reprovar, por isso pode ser usado num GitHub Actions.

## Experiências para aprender

1. Apaga a regra 3 do system prompt ("Usa SEMPRE a ferramenta") e corre o QA:
   a verificação **origem** começa a falhar.
2. Torna vaga a descrição da ferramenta e vê o efeito nos printouts.
3. Acrescenta casos teus a `testes/bateria.json`.
4. Compara modelos: `python3 qa.py --modelo claude-haiku-5-5` (o modelo por omissão é o Sonnet).

Cada execução do QA custa tokens: com 3 repetições são cerca de 60 execuções
do agente. Usa `--rapido` ou `--caso <id>` enquanto estás a afinar.

## Segurança

A chave da API lê-se só da variável `ANTHROPIC_API_KEY` e nunca entra no
repositório. A ferramenta não executa código e tem limites contra números
gigantes. Ver [SECURITY.md](SECURITY.md).

## Licença

MIT. Ver [LICENSE](LICENSE).
