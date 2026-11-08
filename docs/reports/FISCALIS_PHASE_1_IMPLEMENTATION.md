# Fiscalis — Fase 1: Relatório de implementação

**Status:** `PHASE_1_READY_FOR_REVIEW`
**Escopo:** consolidação do backend operacional, validações, integração IBPT, persistência e testes.
**CT-01:** não iniciada; esta execução foi interrompida na Fase 1 conforme a preferência escolhida pelo usuário.

## 1. Estado do Git

### Baseline da Fase 1

- Branch: `main`; working tree limpo.
- HEAD: `d1324da` (`Add product tax quote simulation`).
- Commits anteriores: `bb91a7e` e `7301b02`.
- `python3 -m unittest discover -s tests -v`: 16 testes passaram, mas os testes importavam `app.py` e `services.*`, não o backend executado pelo Docker.
- `docker compose config --quiet`: passou.
- `docker compose ps`: aplicação ativa e MySQL saudável.
- A leitura inicial do MySQL encontrou zero registros e os índices `PRIMARY` e `idx_consultas_criado`.

### Baseline da CT-01 antes de retomarmos a Fase 1

O branch continuava em `main`, sem commits novos, mas já havia alterações não commitadas da Fase 1 em `Dockerfile`, `README.md`, `app.py`, `main.py` e `static/tabela.js`. A suíte antiga executou 16 testes e teve 15 erros, principalmente porque ainda construía o modelo sem credenciais e esperava os símbolos do backend legado. `docker compose config --quiet` passou. O container ativo era a imagem anterior às alterações locais; o endpoint `/health` retornou `404`.

### Estado final

- Branch `main`, HEAD ainda `d1324da`; nenhuma alteração foi commitada ou enviada.
- As alterações locais estão listadas na seção 2, incluindo este relatório.
- `git diff --check` passou.

## 2. Arquivos alterados

- `main.py` — backend canônico, validações, parsing IBPT, inicialização por schema e persistência.
- `app.py` — fachada para a aplicação canônica e reexportação de símbolos legados.
- `Dockerfile` — inclui `schema.sql` na imagem.
- `docker-compose.yml` — encaminha credenciais IBPT opcionais do ambiente.
- `README.md` — documenta validações, comportamento dos erros, fallback de ambiente e inicialização do schema.
- `static/tabela.js` — cálculo monetário com inteiros em centavos e arredondamento explícito.
- `tests/test_backend.py` — cobertura do backend `main:app`, sem chamadas externas ou acesso ao banco de desenvolvimento.
- `tests/test_table_math.js` — teste de cenários federal Nacional/Importado e arredondamento.
- `docs/reports/FISCALIS_PHASE_1_IMPLEMENTATION.md` — este relatório.

`schema.sql` não foi alterado: passou a ser a fonte de definição de tabela consumida pelo backend.

## 3. Problemas corrigidos

### Backend operacional e compatibilidade

- O Docker executa `uvicorn main:app`; agora `app.py` reexporta a mesma aplicação e não mantém uma segunda implementação de rotas.
- Permanecem disponíveis aliases e helpers legados em `app.py`; configurações `MYSQL_*` também são aceitas como fallback às variáveis `DB_*`.
- O modelo aceita `codigo`, `NCM` e `ncm`, preserva zeros à esquerda e rejeita aliases conflitantes.
- Credenciais informadas no corpo da requisição têm precedência. Para clientes locais que as omitem, `IBPT_TOKEN` e `IBPT_CNPJ` podem ser lidos do ambiente/arquivo `.env`.
- A rota `/health` agora existe no backend efetivamente executado pelo Docker.

### Validação de entradas

- NCM de produto exige exatamente oito dígitos; a validação é sintática e não afirma que o NCM exista nem confirma sua classificação fiscal.
- UF é normalizada para maiúsculas e validada contra as 27 siglas brasileiras.
- CNPJ aceita 14 dígitos ou formato pontuado equivalente e verifica os dígitos verificadores.
- Valor é convertido para `Decimal` e deve ser positivo e finito.
- Campos opcionais mantêm limites de formato; exceção não pode ser negativa.
- Tipos de produto `0`/`1` são aceitos como inteiros ou texto. Contexto de serviço (`2`, `serviço` ou equivalentes) retorna `422`: o endpoint consultado é o de produtos e não foi assumido suporte a serviços. A simulação de serviços baseada no CSV local permanece disponível.

### Resposta IBPT e cálculo

- Percentuais são normalizados como `Decimal`; zero é uma alíquota válida, enquanto campos ausentes permanecem ausentes.
- Respostas sem percentuais utilizáveis, malformadas, não finitas ou com alíquotas negativas são rejeitadas com `502` e não chegam à persistência.
- Timeout retorna `504`; falhas de conexão/HTTP ou resposta inválida retornam `502`; falha de persistência retorna `503`.
- A interface calcula em centavos com `BigInt` e arredondamento half-up. Nacional e Importado continuam sendo cenários federais alternativos, nunca somados entre si.

## 4. Persistência e schema

- `schema.sql` é a fonte única da definição da tabela `consultas_tributos`.
- No startup, o backend carrega o arquivo e executa apenas instruções `CREATE TABLE IF NOT EXISTS`; ignora `CREATE DATABASE` e `USE`, pois o Compose já seleciona/cria o banco.
- Schema ausente/malformado gera erro operacional explícito.
- Não foram executados `ALTER`, `DROP`, `TRUNCATE`, migrações destrutivas ou comandos que removam volumes.
- O volume do ambiente permaneceu intacto. A subida final recriou apenas o container web; `fiscalis-db-1` permaneceu ativo e saudável.
- Foi feito também um teste isolado com MySQL 8.0.46: inicialização do schema, inserção de um registro sintético, reinício do container de teste e leitura do mesmo registro. O teste usou bind mount temporário separado do volume do projeto; container, rede e diretório temporários foram removidos ao final.

### Diferença de índices remanescente

A definição inline anterior tinha `idx_consultas_criado (criado_em, id)`. O `schema.sql` existente define `idx_consultas_tributos_criado (criado_em, id)` e `idx_consultas_tributos_codigo_uf (codigo_ncm, uf)`. Em um banco existente, `CREATE TABLE IF NOT EXISTS` não altera a tabela nem seus índices; portanto, o índice antigo continua nesse banco. Não foi feita migração porque não é necessária para o comportamento atual e alteraria o schema existente. Bancos novos recebem os índices de `schema.sql`.

## 5. Contratos HTTP

- `POST /api/consultar-imposto`: caminho e formato de resposta do backend Docker preservados. Entradas inválidas retornam `422`; respostas externas sem dados utilizáveis não são salvas. Os cenários de alíquota zero continuam válidos.
- `GET /api/historico`: preservado, com limite máximo de 50 registros; `limit` inválido retorna `422`, falha de banco retorna `503`.
- `GET /health`: disponível no backend operacional.
- A API documentada pelo OpenAPI contém `/api/consultar-imposto`, `/api/historico` e `/health`. Rotas HTML permanecem fora do schema OpenAPI.
- Para o backend Docker, credenciais enviadas pelo formulário mantêm precedência sobre as variáveis opcionais.

## 6. Testes e comandos executados

| Comando/verificação | Resultado |
|---|---|
| `python3 -m unittest discover -s tests -v` | 20 testes passaram |
| `node --test tests/test_table_math.js` | 1 teste passou |
| `node --check static/tabela.js` | Passou |
| `python3 -m py_compile main.py app.py tests/test_backend.py` | Passou |
| `git diff --check` | Passou |
| `docker compose config --quiet` | Passou |
| `docker compose build app` | Imagem construída |
| `docker compose up --build -d` | Aplicação recriada; MySQL não foi recriado |
| `docker compose ps` | `fiscalis-app-1` ativo; `fiscalis-db-1` saudável |
| `docker compose logs --tail=100 app` | Startup completo e Uvicorn ativo |
| `GET /health` | `200`, `{"status":"ok"}` |
| `GET /` e `GET /tabela` | Ambos `200` |
| `GET /openapi.json` | OpenAPI 3.1.0 com as rotas esperadas |
| POST local com NCM, CNPJ ou UF inválidos | `422`; rejeitado antes de chamada externa |
| Teste isolado MySQL com reinício | Registro sintético preservado após reinício |

Os testes automatizados mockam `requests.get`, conexão MySQL e startup; nenhuma consulta real ao IBPT foi feita. O smoke test Docker usou somente entradas inválidas, portanto também não chamou o IBPT nem gravou histórico no banco do projeto.

O teste JavaScript executa a lógica existente da interface e confirma, para preço de R$ 100,00, estimativas de R$ 13,50 no cenário Nacional e R$ 23,50 no Importado, totalizando R$ 113,50 e R$ 123,50, respectivamente. Também verifica arredondamento half-up de meio centavo.

## 7. Limitações e riscos remanescentes

- O histórico contém CNPJ e não possui autenticação/autorização. O Compose continua vinculando a porta do serviço a `127.0.0.1`; não publicar nem expor endpoints de histórico sem controles de acesso.
- O MySQL do projeto estava vazio no baseline. A preservação após reinício foi exercitada em banco isolado com registro sintético, não com registros reais do ambiente.
- Não foi feita consulta real à API do IBPT nem afirmada qualquer alíquota. Os testes cobrem respostas mockadas.
- O Pylance do workspace usa `/opt/homebrew/bin/python3`, cujo ambiente não resolve as dependências do projeto. `python3` no terminal executou a suíte e a compilação, e o container Python 3.11 foi construído e inicializado. Não alterei a seleção de interpretador do VS Code; diagnósticos de tipo pelo Pylance permanecem não verificados.
- O ambiente local exibiu `RequestsDependencyWarning` sobre detector de charset ausente; não impediu os testes.
- Índices de bancos preexistentes não são atualizados automaticamente, conforme descrito na seção 4.

## 8. Recomendações para a próxima fase

1. Revisar e aprovar esta Fase 1 antes de iniciar CT-01.
2. Manter a API de histórico restrita ao ambiente local até existir autenticação e autorização adequadas.
3. Antes de CT-01, verificar documentalmente metadados, licença e condições de retenção/redistribuição do IBPT; campos não documentados devem permanecer desconhecidos.
4. Se a evolução do schema existente for necessária, apresentar e testar uma migração aditiva separada, sem alterar dados históricos por inferência.
