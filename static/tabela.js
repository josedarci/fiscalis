"use strict";

const fileInput = document.getElementById("csv-file");
const fileStatus = document.getElementById("file-status");
const fileError = document.getElementById("file-error");
const searchInput = document.getElementById("table-search");
const businessFilter = document.getElementById("business-filter");
const itemTypeFilter = document.getElementById("item-type-filter");
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
const serviceDialog = document.getElementById("service-dialog");
const serviceQuoteForm = document.getElementById("service-quote-form");
const servicePriceInput = document.getElementById("service-sale-price");
const serviceQuoteError = document.getElementById("service-quote-error");
const serviceQuoteResult = document.getElementById("service-quote-result");
const serviceBreakdown = document.getElementById("service-tax-breakdown");
const currencyFormatter = new Intl.NumberFormat("pt-BR", {
  style: "currency",
  currency: "BRL",
});
const percentFormatter = new Intl.NumberFormat("pt-BR", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 4,
});
let selectedService = null;
let serviceCheckbox = null;

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
const BUSINESS_SEGMENTS = [
  { first: 1, last: 5, label: "Agropecuária e produtos de origem animal" },
  { first: 6, last: 14, label: "Agricultura e produtos vegetais" },
  { first: 15, last: 24, label: "Alimentos, bebidas e tabaco" },
  { first: 25, last: 27, label: "Mineração, combustíveis e energia" },
  { first: 28, last: 38, label: "Químicos, farmacêuticos e cosméticos" },
  { first: 39, last: 40, label: "Plásticos e borracha" },
  { first: 41, last: 43, label: "Couro, peles e artigos relacionados" },
  { first: 44, last: 49, label: "Madeira, papel e impressos" },
  { first: 50, last: 63, label: "Têxtil, vestuário e confecções" },
  { first: 64, last: 67, label: "Calçados e acessórios" },
  { first: 68, last: 70, label: "Construção, cerâmica, pedras e vidro" },
  { first: 71, last: 71, label: "Joalheria e metais preciosos" },
  { first: 72, last: 83, label: "Metais, siderurgia e metalurgia" },
  { first: 84, last: 85, label: "Máquinas, eletrônicos e equipamentos elétricos" },
  { first: 86, last: 89, label: "Transporte, veículos e navegação" },
  { first: 90, last: 92, label: "Instrumentos, saúde, óptica e música" },
  { first: 93, last: 93, label: "Segurança e armamentos" },
  { first: 94, last: 96, label: "Móveis, brinquedos e produtos diversos" },
  { first: 97, last: 97, label: "Arte, antiguidades e colecionáveis" },
];
const state = {
  columns: [],
  rows: [],
  filteredRows: [],
  page: 1,
  pageSize: 50,
  sortColumn: "codigo",
  sortDirection: "asc",
  segments: new Map(),
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

function segmentForNcm(code) {
  const chapterText = /^\d{2}/.exec(String(code ?? "").trim())?.[0];
  if (!chapterText) return "Não classificado";
  const chapter = Number(chapterText);
  const segment = BUSINESS_SEGMENTS.find(
    (item) => chapter >= item.first && chapter <= item.last,
  );
  return segment?.label ?? "Não classificado";
}

function renderBusinessOptions(rows) {
  state.segments = new Map();
  for (const row of rows) {
    const segment = segmentForNcm(row.codigo);
    row._segment = segment;
    state.segments.set(segment, (state.segments.get(segment) ?? 0) + 1);
  }

  businessFilter.replaceChildren();
  const allOption = document.createElement("option");
  allOption.value = "";
  allOption.textContent = `Todos os ramos (${rows.length.toLocaleString("pt-BR")})`;
  businessFilter.append(allOption);

  const orderedSegments = BUSINESS_SEGMENTS
    .map((item) => item.label)
    .filter((label) => state.segments.has(label));
  if (state.segments.has("Não classificado")) {
    orderedSegments.push("Não classificado");
  }
  for (const segment of orderedSegments) {
    const option = document.createElement("option");
    option.value = segment;
    option.textContent = `${segment} (${state.segments.get(segment).toLocaleString("pt-BR")})`;
    businessFilter.append(option);
  }
  businessFilter.value = "";
  businessFilter.disabled = rows.length === 0;
}

function renderItemTypeOptions(rows, hasTypeColumn) {
  const counts = new Map();
  for (const row of rows) {
    const type = row.tipo?.trim() || "";
    counts.set(type, (counts.get(type) ?? 0) + 1);
  }

  itemTypeFilter.replaceChildren();
  const allOption = document.createElement("option");
  allOption.value = "";
  allOption.textContent = `Todos os tipos (${rows.length.toLocaleString("pt-BR")})`;
  itemTypeFilter.append(allOption);

  if (counts.has("2")) {
    const serviceOption = document.createElement("option");
    serviceOption.value = "2";
    serviceOption.textContent = `Serviços (${counts.get("2").toLocaleString("pt-BR")})`;
    itemTypeFilter.append(serviceOption);
  }

  const nonServiceCount = rows.length - (counts.get("2") ?? 0);
  if (nonServiceCount > 0) {
    const otherOption = document.createElement("option");
    otherOption.value = "not-2";
    otherOption.textContent = `Produtos e outros (${nonServiceCount.toLocaleString("pt-BR")})`;
    itemTypeFilter.append(otherOption);
  }

  itemTypeFilter.value = "";
  itemTypeFilter.disabled = !hasTypeColumn || rows.length === 0;
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

function formatRate(value) {
  if (value === undefined || value === null || value.trim() === "") return null;
  const rate = Number(value.replace(",", "."));
  return Number.isFinite(rate) ? rate : null;
}

function roundedCurrency(value) {
  return Math.round((value + Number.EPSILON) * 100) / 100;
}

function addBreakdownRow(label, rateText, amountText) {
  const row = document.createElement("div");
  row.className = "flex flex-wrap items-center justify-between gap-x-4 gap-y-1 py-3";
  const name = document.createElement("dt");
  name.className = "text-sm font-medium text-slate-700";
  name.textContent = label;
  const values = document.createElement("dd");
  values.className = "flex flex-wrap items-baseline gap-x-3 text-right";
  const rate = document.createElement("span");
  rate.className = "text-xs text-slate-500";
  rate.textContent = rateText;
  const amount = document.createElement("strong");
  amount.className = "text-sm font-semibold text-slate-900";
  amount.textContent = amountText;
  values.append(rate, amount);
  row.append(name, values);
  serviceBreakdown.append(row);
}

function renderServiceQuote() {
  serviceQuoteError.classList.add("hidden");
  serviceQuoteError.textContent = "";
  const price = Number(servicePriceInput.value);
  if (!Number.isFinite(price) || price <= 0) {
    serviceQuoteResult.classList.add("hidden");
    serviceQuoteError.textContent = "Informe um valor de venda maior que zero.";
    serviceQuoteError.classList.remove("hidden");
    servicePriceInput.focus();
    return;
  }

  const taxes = [
    { key: "nacionalfederal", label: "Federal (nacional)" },
    { key: "estadual", label: "Estadual" },
    { key: "municipal", label: "Municipal" },
  ];
  let taxTotal = 0;
  let availableTaxes = 0;
  serviceBreakdown.replaceChildren();

  for (const tax of taxes) {
    const rate = formatRate(selectedService[tax.key]);
    if (rate === null) {
      addBreakdownRow(tax.label, "Percentual não informado", "Não calculado");
      continue;
    }
    const amount = roundedCurrency(price * rate / 100);
    taxTotal = roundedCurrency(taxTotal + amount);
    availableTaxes += 1;
    addBreakdownRow(
      tax.label,
      `${percentFormatter.format(rate)}%`,
      currencyFormatter.format(amount),
    );
  }

  document.getElementById("service-base-price").textContent = currencyFormatter.format(price);
  document.getElementById("service-tax-total").textContent = availableTaxes
    ? currencyFormatter.format(taxTotal)
    : "Não disponível";
  document.getElementById("service-grand-total").textContent = availableTaxes
    ? currencyFormatter.format(roundedCurrency(price + taxTotal))
    : currencyFormatter.format(price);
  document.getElementById("service-estimate-note").textContent = availableTaxes < taxes.length
    ? "Estimativa parcial: um ou mais percentuais não estavam disponíveis no arquivo. O total simulado soma apenas os valores calculados."
    : "O cálculo aplica cada percentual ao valor de venda informado e soma os valores estimados, arredondados para centavos. A alíquota de importados não é usada para este serviço.";
  serviceQuoteResult.classList.remove("hidden");
}

function openServiceQuote(row, checkbox) {
  selectedService = row;
  serviceCheckbox = checkbox;
  document.getElementById("service-dialog-description").textContent = row.descricao ?? "Serviço";
  document.getElementById("service-dialog-code").textContent =
    `Código ${row.codigo ?? "—"} · Exceção ${row.ex || "0"} · Tipo serviço`;
  servicePriceInput.value = "";
  serviceQuoteError.classList.add("hidden");
  serviceQuoteResult.classList.add("hidden");
  serviceDialog.showModal();
  servicePriceInput.focus();
}

serviceQuoteForm.addEventListener("submit", (event) => {
  event.preventDefault();
  renderServiceQuote();
});
document.getElementById("service-dialog-close").addEventListener("click", () => {
  serviceDialog.close();
});
serviceDialog.addEventListener("click", (event) => {
  if (event.target === serviceDialog) serviceDialog.close();
});
serviceDialog.addEventListener("close", () => {
  if (serviceCheckbox?.isConnected) serviceCheckbox.checked = false;
  selectedService = null;
  serviceCheckbox = null;
});

function renderTable() {
  const query = normalizeText(searchInput.value.trim());
  const selectedSegment = businessFilter.value;
  const selectedType = itemTypeFilter.value;
  state.filteredRows = state.rows.filter((row) =>
    (!selectedType || (selectedType === "2" ? row.tipo?.trim() === "2" : row.tipo?.trim() !== "2"))
      && (!selectedSegment || row._segment === selectedSegment)
      && (
        !query
        || normalizeText(row._segment).includes(query)
        || state.columns.some((column) => normalizeText(row[column]).includes(query))
      ),
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
  const hasServiceType = state.columns.includes("tipo")
    && state.rows.some((row) => row.tipo?.trim() === "2");

  for (const row of pageRows) {
    const tableRow = document.createElement("tr");
    tableRow.className = "odd:bg-white even:bg-slate-50 hover:bg-teal-50";
    if (hasServiceType) {
      const selectCell = document.createElement("td");
      selectCell.className = "border-b border-slate-100 px-3 py-2 text-center";
      if (row.tipo?.trim() === "2") {
        const checkbox = document.createElement("input");
        checkbox.type = "checkbox";
        checkbox.className = "h-4 w-4 cursor-pointer rounded border-slate-300 text-teal-700 focus:ring-teal-600";
        checkbox.setAttribute("aria-label", `Simular valor para o serviço ${row.codigo}: ${row.descricao}`);
        checkbox.addEventListener("change", () => {
          if (checkbox.checked) openServiceQuote(row, checkbox);
        });
        selectCell.append(checkbox);
      } else {
        selectCell.textContent = "—";
        selectCell.classList.add("text-slate-300");
      }
      tableRow.append(selectCell);
    }
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
  const hasServiceType = state.columns.includes("tipo")
    && state.rows.some((item) => item.tipo?.trim() === "2");
  if (hasServiceType) {
    const selectHeading = document.createElement("th");
    selectHeading.scope = "col";
    selectHeading.className = "whitespace-nowrap border-b border-slate-300 px-3 py-3 text-center font-semibold";
    selectHeading.textContent = "Simular serviço";
    row.append(selectHeading);
  }
  for (const column of state.columns) {
    const heading = document.createElement("th");
    heading.scope = "col";
    heading.className = "whitespace-nowrap border-b border-slate-300 px-3 py-3 text-left font-semibold";
    const sortButton = document.createElement("button");
    sortButton.type = "button";
    sortButton.className = "inline-flex items-center gap-1.5 rounded-sm text-left hover:text-teal-800 focus:outline-none focus:ring-2 focus:ring-teal-600";
    const label = COLUMN_LABELS[column] ?? column;
    const isSortedColumn = state.sortColumn === column;
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    const icon = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    icon.setAttribute("viewBox", "0 0 16 16");
    icon.setAttribute("width", "14");
    icon.setAttribute("height", "14");
    icon.setAttribute("fill", "none");
    icon.setAttribute("stroke", "currentColor");
    icon.setAttribute("stroke-width", "1.5");
    icon.setAttribute("stroke-linecap", "round");
    icon.setAttribute("stroke-linejoin", "round");
    icon.setAttribute("aria-hidden", "true");
    if (!isSortedColumn) {
      icon.classList.add("text-slate-400");
      path.setAttribute("d", "M5 6l3-3 3 3M5 10l3 3 3-3");
    } else if (state.sortDirection === "asc") {
      icon.classList.add("text-teal-700");
      path.setAttribute("d", "M5 10l3-3 3 3");
    } else {
      icon.classList.add("text-teal-700");
      path.setAttribute("d", "M5 6l3 3 3-3");
    }
    icon.append(path);
    sortButton.append(document.createTextNode(label), icon);
    sortButton.setAttribute(
      "aria-label",
      isSortedColumn
        ? `Ordenar por ${label} em ordem ${state.sortDirection === "asc" ? "decrescente" : "crescente"}`
        : `Ordenar por ${label}`,
    );
    heading.setAttribute(
      "aria-sort",
      isSortedColumn ? (state.sortDirection === "asc" ? "ascending" : "descending") : "none",
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
    renderBusinessOptions(rows);
    renderItemTypeOptions(rows, columns.includes("tipo"));
    searchInput.disabled = false;
    pageSizeSelect.disabled = false;
    renderHeaders();
    renderTable();
    fileStatus.textContent = `${file.name} — ${rows.length.toLocaleString("pt-BR")} registros carregados localmente.`;
  } catch (error) {
    state.columns = [];
    state.rows = [];
    state.filteredRows = [];
    state.segments.clear();
    tableHead.replaceChildren();
    tableBody.replaceChildren();
    searchInput.disabled = true;
    businessFilter.disabled = true;
    itemTypeFilter.disabled = true;
    businessFilter.replaceChildren();
    itemTypeFilter.replaceChildren();
    const allOption = document.createElement("option");
    allOption.value = "";
    allOption.textContent = "Todos os ramos";
    businessFilter.append(allOption);
    const allTypesOption = document.createElement("option");
    allTypesOption.value = "";
    allTypesOption.textContent = "Todos os tipos";
    itemTypeFilter.append(allTypesOption);
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
businessFilter.addEventListener("change", () => {
  state.page = 1;
  renderTable();
});
itemTypeFilter.addEventListener("change", () => {
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
