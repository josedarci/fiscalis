<p align="center">
  <img src="static/fiscalis-logo.png" alt="Fiscalis — Inteligência Tributária" width="720">
</p>

<h1 align="center">Fiscalis — Calculadora de Impostos</h1>

<p align="center">
  MVP web para consultar uma estimativa de carga tributária de produtos pela API do IBPT,
  com histórico persistido em MySQL.
</p>

## Sobre o projeto

O Fiscalis recebe os dados de um produto, consulta a API de Produtos do IBPT (De Olho no Imposto), mostra as alíquotas retornadas e calcula os valores aproximados sobre o preço informado. As consultas são registradas em MySQL para consulta posterior.

> Os valores são estimativas informativas. Confirme a tributação aplicável com um profissional contábil e consulte a documentação e as condições de uso do IBPT.

## Tecnologias

- Python 3.11 e FastAPI
- MySQL 8.0
- Docker Compose
- Tailwind CSS via CDN e JavaScript
- API de Produtos do IBPT

## O que é necessário

1. **Docker Desktop** atualizado no macOS ou Windows, ou Docker Engine com o plugin Docker Compose v2 no Linux.
2. Conexão com a internet para baixar as imagens/dependências e consultar o IBPT.
3. **Token e CNPJ habilitados para uso na API do IBPT.** Eles são informados no formulário da aplicação; o token não é salvo no histórico. O CNPJ é persistido junto com a consulta.
4. A porta `8000` disponível no computador.

Não é necessário instalar Python nem MySQL no computador para executar a versão com Docker Compose.

## Como instalar e executar

### 1. Instale e verifique o Docker

Instale o Docker Desktop (macOS/Windows) ou Docker Engine e Docker Compose v2 (Linux). Inicie o Docker Desktop, se aplicável, e confirme no terminal:

```bash
docker --version
docker compose version
```

### 2. Clone o repositório

```bash
git clone https://github.com/josedarci/fiscalis.git
cd fiscalis
```

### 3. Inicie o sistema

Na raiz do projeto, execute o único comando de inicialização:

```bash
docker compose up --build
```

Na primeira execução, o Docker baixa as imagens, instala as dependências Python e cria os containers. O serviço web aguarda o MySQL ficar pronto e cria a tabela `consultas_tributos` automaticamente.

Quando o log indicar que o Uvicorn está em execução, abra:

**http://localhost:8000**

Para executar em segundo plano, use `docker compose up --build -d`. Consulte os logs com `docker compose logs -f app`.

### Configuração opcional de banco

O Compose usa valores de desenvolvimento local para inicializar sem configuração adicional. Para personalizá-los, crie um arquivo `.env` na raiz (não o publique) e defina, por exemplo:

```dotenv
MYSQL_DATABASE=db_tributos_app
MYSQL_USER=fiscalis
MYSQL_PASSWORD=troque-esta-senha
MYSQL_ROOT_PASSWORD=troque-a-senha-root
```

As credenciais acima são apenas um exemplo para desenvolvimento. Troque-as antes de expor o serviço ou reutilizar o banco fora da máquina local. O arquivo `.env` é ignorado pelo Git.

## Como usar

1. Acesse `http://localhost:8000`.
2. Informe um token e CNPJ válidos para consulta no IBPT.
3. Preencha o código/NCM, UF, descrição e valor do produto. Unidade de medida, GTIN e exceção também podem ser informados.
4. Selecione **Consultar estimativa**.
5. Confira as alíquotas Nacional/Federal, Estadual, Municipal e Importado, a estimativa financeira calculada sobre o valor informado e a fonte apresentada pela API.
6. Consulte as buscas anteriores em **Histórico recente** ou use **Atualizar**.

O formulário não guarda o token no navegador nem o envia ao banco de dados. O CNPJ é gravado na tabela de histórico. Não use credenciais reais em computadores compartilhados.

### Consultar a tabela IBPT local

1. No menu superior, clique em **Tabela IBPT** ou abra `http://localhost:8000/tabela`.
2. Clique no seletor de arquivo e escolha o CSV `TabelaIBPT...csv` baixado do portal IBPT.
3. Use a busca para filtrar por NCM, descrição, vigência, alíquota ou ramo estimado.
4. Selecione um **Ramo do produto** para filtrar por categoria aproximada derivada do capítulo NCM; o número de produtos aparece ao lado de cada opção.
5. Combine a categoria com a busca de texto. Clique no título de uma coluna para ordenar; clique novamente para inverter a ordem.
6. Use os controles de paginação para navegar pelos resultados e escolha exibir 25, 50 ou 100 linhas por página.

O CSV é lido localmente pelo navegador: seu conteúdo não é enviado ao servidor nem incluído no repositório. O ramo é uma organização aproximada dos capítulos NCM, não identifica oficialmente a atividade da empresa, e produtos podem ser usados em vários setores. Baixe a tabela atualizada pelo canal oficial do IBPT e confira a versão e vigência antes de usar os valores.

## API HTTP

### `POST /api/consultar-imposto`

Exemplo de corpo JSON:

```json
{
  "token": "SEU_TOKEN_IBPT",
  "cnpj": "12345678000199",
  "codigo": "01012100",
  "uf": "SP",
  "descricao": "Produto de exemplo",
  "unidadeMedida": "UN",
  "valor": 100.00,
  "gtin": "",
  "ex": 0
}
```

O campo `codigo` também pode ser informado como `NCM`. A resposta inclui o identificador salvo e os percentuais de tributos retornados pelo IBPT. Erros de validação, indisponibilidade da API externa e falhas no banco são informados com status HTTP apropriado.

### `GET /api/historico`

Retorna até as 50 consultas mais recentes, incluindo NCM, descrição, valor, alíquotas, fonte, data e CNPJ usado. Para testar os endpoints, acesse também a documentação interativa em **http://localhost:8000/docs**.

## Dados persistidos

O MySQL cria a tabela `consultas_tributos` na inicialização. Cada consulta salva:

- CNPJ, UF, código NCM, descrição e valor informado;
- alíquotas Nacional, Estadual, Municipal e Importado;
- fonte da informação e data/hora da consulta.

O token do IBPT não é salvo. Os dados permanecem em um volume Docker chamado `mysql_data`, inclusive ao recriar os containers.

## Parar, reiniciar e apagar os dados

```bash
# Parar e remover os containers, mantendo os dados do volume
docker compose down

# Reiniciar a aplicação
docker compose up --build
```

Para apagar permanentemente também o histórico e demais dados MySQL:

```bash
docker compose down -v
```

> O comando `down -v` remove o volume persistente e não pode ser desfeito.

## Estrutura principal

```text
.
├── .dockerignore
├── .env.example
├── Dockerfile
├── LICENSE
├── README.md
├── docker-compose.yml
├── index.html
├── main.py
├── requirements.txt
├── schema.sql
├── tabela.html
└── static/
    ├── fiscalis-logo.png
    └── tabela.js
```

Os diretórios `services/` e `tests/` também contêm a implementação modular anterior e seus testes automatizados.

## Execução local sem Docker (opcional)

A execução recomendada é com Docker Compose. Para executar o FastAPI diretamente, é necessário instalar Python 3.11, instalar e iniciar um servidor MySQL 8.0, criar o banco e exportar `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER` e `DB_PASSWORD`. Depois:

```bash
python3.11 -m venv .venv
source .venv/bin/activate          # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn main:app --reload
```

O servidor local ficará disponível em `http://localhost:8000`. As variáveis de banco precisam estar definidas no ambiente antes de iniciar.

## Licença e uso

O código deste projeto está sob a licença [MIT](./LICENSE). A licença do projeto não substitui nem altera os termos de uso da API do IBPT. Este repositório contém um MVP de referência; avalie segurança, disponibilidade, proteção de dados e requisitos fiscais antes de qualquer uso em produção.

## Ajuda na aplicação

Na interface, clique em **Ajuda** no topo da página para abrir a central de ajuda em uma janela modal. Ela explica o preenchimento do formulário, os campos, a estimativa, o histórico, erros comuns e como encerrar o aplicativo sem apagar os dados.
