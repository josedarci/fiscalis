"use strict";

const fileInput = document.getElementById("csv-file");
const fileStatus = document.getElementById("file-status");
const fileError = document.getElementById("file-error");
const searchInput = document.getElementById("table-search");
const pageSizeSelect = document.getElementById("page-size");
const tableHead = document.getElementById("table-head");
const tableBody = document.getElementById("table-body");
const emptyState = document.getElementById("empty-state");
const resultCount = document.getElementById("result-count");
const pageIndicator = document.getElementById("page-indicator");
const firstPageButton = document.getElementById("first-page");
const previousPageButton = document.getElementById("previous-page");
const nextPageButton = document.getElementById("next-page");
const lastPageButton = document.getElementById("last-page");

const COLUMN_LABELS = {
  codigo: "Código / NCM",
  ex: "Exceção",
  tipo: "Tipo",
  descricao: "Descrição",
  nacionalfederal: "Nacional Federal (%)",
  importadosfederal: "Importados Federal (%)",
  estadual: "Estadual (%)",
  municipal: "Municipal (%)",
  vigenciainicio: "Início da vigência",
  vigenciafim: "Fim da vigência",
  chave: "Chave",
  versao: "Versão",
  fonte: "Fonte",
};
const NUMERIC_COLUMNS = new Set([
  "ex",
  "tipo",
  "nacionalfederal",
  "importadosfederal",
  "estadual",
  "municipal",
]);
const DATE_COLUMNS = new Set(["vigenciainicio", "vigenciafim"]);
const state = {
  columns: [],
  rows: [],
  filteredRows: [],
  page: 1,
  pageSize: 50,
  sortColumn: "codigo",
  sortDirection: "asc",
};

function parseDelimited(text, delimiter = ";") {
  const rows = [];
  let row = [];
  let value = "";
  let quoted = false;

  for (let index = 0; index < text.length; index += 1) {
    const character = text[index];
    if (quoted) {
      if (character === '"' && text[index + 1] === '"') {
        value += '"';
        index += 1;
      } else if (character === '"') {
        quoted = false;
      } else {
        value += character;
      }
    } else if (character === '"' && value.length === 0) {
      quoted = true;
    } else if (character === delimiter) {
      row.push(value);
      value = "";
    } else if (character === "\n" || character === "\r") {
      if (character === "\r" && text[index + 1] === "\n") index += 1;
      row.push(value);
      value = "";
      if (row.some((cell) => cell.length > 0)) rows.push(row);
      row = [];
    } else {
      value += character;
    }
  }

  if (value.length > 0 || row.length > 0) {
    row.push(value);
    if (row.some((cell) => cell.length > 0)) rows.push(row);
  }
  if (quoted) throw new Error("O CSV tem um campo entre aspas que não foi fechado.");
  return rows;
}

function normalizeText(value) {
  return String(value ?? "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLocaleLowerCase("pt-BR");
}

function dateValue(value) {
  const match = /^(\d{2})\/(\d{2})\/(\d{4})$/.exec(value);
  return match ? Date.UTC(Number(match[3]), Number(match[2]) - 1, Number(match[1])) : Number.NaN;
}

function compareRows(left, right, column) {
  const leftValue = left[column] ?? "";
  const rightValue = right[column] ?? "";
  if (!leftValue && !rightValue) return 0;
  if (!leftValue) return 1;
  if (!rightValue) return -1;

  if (NUMERIC_COLUMNS.has(column)) {
    const leftNumber = Number(leftValue.replace(",", "."));
    const rightNumber = Number(rightValue.replace(",", "."));
    if (Number.isFinite(leftNumber) && Number.isFinite(rightNumber)) {
      return leftNumber - rightNumber;
    }
  }
  if (DATE_COLUMNS.has(column)) {
    const difference = dateValue(leftValue) - dateValue(rightValue);
    if (Number.isFinite(difference)) return difference;
  }
  return leftValue.localeCompare(rightValue, "pt-BR", {
    numeric: true,
    sensitivity: "base",
  });
}

function updateButtons(pageCount) {
  const hasRows = state.filteredRows.length > 0;
  firstPageButton.disabled = !hasRows || state.page <= 1;
  previousPageButton.disabled = !hasRows || state.page <= 1;
  nextPageButton.disabled = !hasRows || state.page >= pageCount;
  lastPageButton.disabled = !hasRows || state.page >= pageCount;
}

function renderTable() {
  const query = normalizeText(searchInput.value.trim());
  state.filteredRows = state.rows.filter((row) =>
    !query || state.columns.some((column) => normalizeText(row[column]).includes(query)),
  );
  state.filteredRows.sort((left, right) => {
    const result = compareRows(left, right, state.sortColumn);
    return state.sortDirection === "asc" ? result : -result;
  });

  const pageCount = Math.ceil(state.filteredRows.length / state.pageSize);
  state.page = pageCount ? Math.min(state.page, pageCount) : 1;
  const start = (state.page - 1) * state.pageSize;
  const pageRows = state.filteredRows.slice(start, start + state.pageSize);
  tableBody.replaceChildren();

  for (const row of pageRows) {
    const tableRow = document.createElement("tr");
    tableRow.className = "odd:bg-white even:bg-slate-50 hover:bg-teal-50";
    for (const column of state.columns) {
      const cell = document.createElement("td");
      cell.className = "border-b border-slate-100 px-3 py-2 align-top text-slate-700";
      if (column === "descricao") cell.classList.add("min-w-64", "whitespace-normal");
      else cell.classList.add("whitespace-nowrap");
      cell.textContent = row[column] ?? "";
      tableRow.append(cell);
    }
    tableBody.append(tableRow);
  }

  emptyState.classList.toggle("hidden", pageRows.length > 0);
  emptyState.textContent = state.rows.length
    ? "Nenhum registro corresponde à pesquisa."
    : "A tabela aparecerá aqui após carregar o arquivo.";
  resultCount.textContent = state.rows.length
    ? `${state.filteredRows.length.toLocaleString("pt-BR")} resultado(s) de ${state.rows.length.toLocaleString("pt-BR")} registro(s)`
    : "Carregue um CSV para começar.";
  pageIndicator.textContent = `Página ${pageCount ? state.page : 0} de ${pageCount}`;
  updateButtons(pageCount);
}

function renderHeaders() {
  const row = document.createElement("tr");
  for (const column of state.columns) {
    const heading = document.createElement("th");
    heading.scope = "col";
    heading.className = "whitespace-nowrap border-b border-slate-300 px-3 py-3 text-left font-semibold";
    const sortButton = document.createElement("button");
    sortButton.type = "button";
    sortButton.className = "inline-flex items-center gap-1 text-left hover:text-teal-800 focus:outline-none focus:ring-2 focus:ring-teal-600";
    const label = COLUMN_LABELS[column] ?? column;
    sortButton.textContent = `${label}${state.sortColumn === column ? (state.sortDirection === "asc" ? " ↑" : " ↓") : " ↕"}`;
    heading.setAttribute(
      "aria-sort",
      state.sortColumn === column
        ? (state.sortDirection === "asc" ? "ascending" : "descending")
        : "none",
    );
    sortButton.addEventListener("click", () => {
      if (state.sortColumn === column) {
        state.sortDirection = state.sortDirection === "asc" ? "desc" : "asc";
      } else {
        state.sortColumn = column;
        state.sortDirection = "asc";
      }
      renderHeaders();
      state.page = 1;
      renderTable();
    });
    heading.append(sortButton);
    row.append(heading);
  }
  tableHead.replaceChildren(row);
}

async function loadCsv(file) {
  fileError.classList.add("hidden");
  fileError.textContent = "";
  fileStatus.textContent = "Lendo arquivo local...";
  try {
    const buffer = await file.arrayBuffer();
    const text = new TextDecoder("windows-1252").decode(buffer).replace(/^\uFEFF/, "");
    const matrix = parseDelimited(text);
    if (matrix.length < 2) throw new Error("O arquivo não contém linhas de dados.");

    const columns = matrix[0].map((column) => column.trim().toLocaleLowerCase("pt-BR"));
    for (const required of ["codigo", "descricao", "nacionalfederal", "estadual"]) {
      if (!columns.includes(required)) {
        throw new Error("Esse arquivo não parece ser uma tabela IBPT válida (faltam colunas esperadas).");
      }
    }

    const rows = matrix.slice(1).map((cells) =>
      Object.fromEntries(columns.map((column, index) => [column, cells[index]?.trim() ?? ""])),
    );
    state.columns = columns;
    state.rows = rows;
    state.page = 1;
    state.pageSize = Number(pageSizeSelect.value);
    state.sortColumn = columns.includes("codigo") ? "codigo" : columns[0];
    state.sortDirection = "asc";
    searchInput.disabled = false;
    pageSizeSelect.disabled = false;
    renderHeaders();
    renderTable();
    fileStatus.textContent = `${file.name} — ${rows.length.toLocaleString("pt-BR")} registros carregados localmente.`;
  } catch (error) {
    state.columns = [];
    state.rows = [];
    state.filteredRows = [];
    tableHead.replaceChildren();
    tableBody.replaceChildren();
    searchInput.disabled = true;
    pageSizeSelect.disabled = true;
    resultCount.textContent = "Carregue um CSV para começar.";
    pageIndicator.textContent = "Página 0 de 0";
    updateButtons(0);
    emptyState.classList.remove("hidden");
    emptyState.textContent = "Não foi possível carregar os dados.";
    fileStatus.textContent = "Arquivo não carregado.";
    fileError.textContent = error instanceof Error ? error.message : "Não foi possível ler o arquivo.";
    fileError.classList.remove("hidden");
  }
}

fileInput.addEventListener("change", () => {
  const [file] = fileInput.files ?? [];
  if (file) loadCsv(file);
});
searchInput.addEventListener("input", () => {
  state.page = 1;
  renderTable();
});
pageSizeSelect.addEventListener("change", () => {
  state.pageSize = Number(pageSizeSelect.value);
  state.page = 1;
  renderTable();
});
firstPageButton.addEventListener("click", () => {
  state.page = 1;
  renderTable();
});
previousPageButton.addEventListener("click", () => {
  state.page = Math.max(1, state.page - 1);
  renderTable();
});
nextPageButton.addEventListener("click", () => {
  state.page += 1;
  renderTable();
});
lastPageButton.addEventListener("click", () => {
  state.page = Math.ceil(state.filteredRows.length / state.pageSize);
  renderTable();
});
