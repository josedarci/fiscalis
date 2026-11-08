"use strict";

const states = [
  "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS",
  "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC",
  "SP", "SE", "TO",
];
const form = document.getElementById("comparison-form");
const ufOptions = document.getElementById("uf-options");
const ufError = document.getElementById("uf-error");
const compareSubmit = document.getElementById("compare-submit");
const comparisonStatus = document.getElementById("comparison-status");
const comparisonResults = document.getElementById("comparison-results");
const comparisonSummary = document.getElementById("comparison-summary");
const comparabilityWarning = document.getElementById("comparability-warning");
const comparisonChart = document.getElementById("comparison-chart");
const comparisonCards = document.getElementById("comparison-cards");
const historyStatus = document.getElementById("history-status");
const historyList = document.getElementById("history-list");
const historyNcm = document.getElementById("history-ncm");
const historyUf = document.getElementById("history-uf");
const historyDate = document.getElementById("history-date");
const historyScenario = document.getElementById("history-scenario");
let historyRows = [];

const labels = {
  uf: "UF",
  status: "Status",
  comparabilidade: "Comparabilidade",
  Federal: "Federal",
  Estadual: "Estadual",
  Municipal: "Municipal",
  total_estimado: "Total estimado",
  percentual_total: "Percentual total",
  Fonte: "Fonte",
  Versao: "Versão",
  VigenciaInicio: "Início da vigência",
  VigenciaFim: "Fim da vigência",
  erro: "Erro",
};

function appendText(parent, tag, className, value) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  element.textContent = value == null ? "—" : String(value);
  parent.append(element);
  return element;
}

function displayValue(value, key) {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "object") {
    try {
      return JSON.stringify(value);
    } catch {
      return "[valor indisponível]";
    }
  }
  if (key === "total_estimado" && value !== "" && Number.isFinite(Number(value))) {
    return new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" }).format(Number(value));
  }
  return String(value);
}

function addDefinition(parent, key, value, className = "") {
  const wrapper = document.createElement("div");
  wrapper.className = className;
  const term = document.createElement("dt");
  term.className = "text-xs font-semibold uppercase tracking-wide text-slate-500";
  term.textContent = labels[key] || key;
  const description = document.createElement("dd");
  description.className = "mt-1 break-words text-sm text-slate-800";
  description.textContent = displayValue(value, key);
  wrapper.append(term, description);
  parent.append(wrapper);
}

function makeErrorMessage(body, fallback) {
  if (body && typeof body === "object") {
    const message = body.detail ?? body.erro ?? body.message;
    if (message !== undefined && message !== null) return displayValue(message);
  }
  return fallback;
}

for (const state of states) {
  const label = document.createElement("label");
  label.className = "flex min-h-11 items-center gap-2 rounded-lg border border-slate-200 px-3 py-2 text-sm hover:bg-slate-50";
  const checkbox = document.createElement("input");
  checkbox.type = "checkbox";
  checkbox.name = "ufs";
  checkbox.value = state;
  checkbox.className = "h-4 w-4 accent-teal-700";
  label.append(checkbox, document.createTextNode(state));
  ufOptions.append(label);
}

document.getElementById("select-all-ufs").addEventListener("click", () => {
  ufOptions.querySelectorAll('input[name="ufs"]').forEach((input) => { input.checked = true; });
  ufError.classList.add("hidden");
});
document.getElementById("deselect-all-ufs").addEventListener("click", () => {
  ufOptions.querySelectorAll('input[name="ufs"]').forEach((input) => { input.checked = false; });
  ufError.classList.add("hidden");
});

function renderComparison(data) {
  const results = Array.isArray(data?.resultados) ? data.resultados : [];
  const comparable = data?.comparabilidade === "COMPARABLE";
  const lowerUf = comparable ? data?.resumo?.menor_uf : null;
  comparisonResults.classList.remove("hidden");
  comparisonSummary.textContent = [
    `Cenário: ${displayValue(data?.cenario)}`,
    `Comparabilidade: ${displayValue(data?.comparabilidade)}`,
    `Menor UF: ${displayValue(data?.resumo?.menor_uf)}`,
    `Maior UF: ${displayValue(data?.resumo?.maior_uf)}`,
  ].join(" · ");

  const historyBlocked = data?.history_status === "BLOCKED_LICENSE";
  comparabilityWarning.classList.toggle("hidden", comparable && !historyBlocked);
  comparabilityWarning.textContent = [
    !comparable
      ? "Os resultados não foram considerados comparáveis pela API. Não há destaque de menor UF nem gráfico comparativo."
      : "",
    historyBlocked
      ? "Esta comparação não foi salva nem pode ser reproduzida; o armazenamento de dados IBPT aguarda confirmação dos termos de licença."
      : "",
  ].filter(Boolean).join(" ");

  comparisonCards.replaceChildren();
  for (const result of results) {
    const card = document.createElement("article");
    const isComparable = comparable && result?.comparabilidade === "COMPARABLE";
    card.className = `rounded-2xl bg-white p-5 shadow-sm ring-1 ${isComparable && result?.uf === lowerUf ? "ring-2 ring-teal-600" : "ring-slate-200"}`;
    const heading = document.createElement("div");
    heading.className = "flex flex-wrap items-center justify-between gap-2";
    appendText(heading, "h3", "text-lg font-bold", `UF ${displayValue(result?.uf)}`);
    if (isComparable && result?.uf === lowerUf) {
      appendText(heading, "span", "rounded-full bg-teal-100 px-3 py-1 text-xs font-bold text-teal-900", "Menor estimativa");
    }
    card.append(heading);
    const definitionList = document.createElement("dl");
    definitionList.className = "mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2";
    for (const [key, value] of Object.entries(result || {})) {
      if (key !== "uf") addDefinition(definitionList, key, value);
    }
    card.append(definitionList);
    comparisonCards.append(card);
  }
  renderChart(results, comparable);
}

function renderChart(results, comparable) {
  comparisonChart.replaceChildren();
  comparisonChart.classList.toggle("hidden", !comparable);
  if (!comparable) return;
  const comparableResults = results.filter((result) => result?.comparabilidade === "COMPARABLE");
  const amounts = comparableResults
    .map((result) => Number(result?.total_estimado))
    .filter((amount) => Number.isFinite(amount) && amount >= 0);
  const maxAmount = Math.max(0, ...amounts);
  const figure = document.createElement("figure");
  figure.setAttribute("aria-labelledby", "chart-heading");
  appendText(figure, "h3", "font-bold", "Estimativa total por UF").id = "chart-heading";
  const list = document.createElement("ul");
  list.className = "mt-3 space-y-3";
  for (const result of comparableResults) {
    const amount = Number(result?.total_estimado);
    if (!Number.isFinite(amount) || amount < 0) continue;
    const item = document.createElement("li");
    item.className = "grid grid-cols-[2.5rem_minmax(0,1fr)_auto] items-center gap-3";
    appendText(item, "span", "text-sm font-semibold", result?.uf ?? "—");
    const track = document.createElement("div");
    track.className = "bar-track";
    track.setAttribute("aria-hidden", "true");
    const fill = document.createElement("div");
    fill.className = "bar-fill";
    fill.style.width = `${maxAmount === 0 ? 0 : (amount / maxAmount) * 100}%`;
    track.append(fill);
    item.append(track);
    appendText(item, "span", "text-right text-sm tabular-nums", displayValue(result.total_estimado, "total_estimado"));
    list.append(item);
  }
  figure.append(list);
  comparisonChart.append(figure);
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const selectedUfs = [...ufOptions.querySelectorAll('input[name="ufs"]:checked')].map((input) => input.value);
  if (selectedUfs.length < 2 || selectedUfs.length > 27) {
    ufError.textContent = "Selecione entre 2 e 27 UFs para comparar.";
    ufError.classList.remove("hidden");
    return;
  }
  ufError.classList.add("hidden");
  comparisonResults.classList.add("hidden");
  comparisonStatus.textContent = "Comparando tributos...";
  compareSubmit.disabled = true;
  try {
    const values = new FormData(form);
    const payload = {
      token: String(values.get("token") || "").trim(),
      cnpj: String(values.get("cnpj") || "").trim(),
      codigo: String(values.get("codigo") || "").trim(),
      gtin: String(values.get("gtin") || ""),
      descricao: String(values.get("descricao") || "").trim(),
      valor: Number(values.get("valor")),
      cenario: String(values.get("cenario") || "nacional"),
      ufs: selectedUfs,
    };
    const response = await fetch("/api/comparar-tributos", {
      method: "POST",
      headers: { Accept: "application/json", "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const body = await response.json().catch(() => null);
    if (!response.ok) throw new Error(makeErrorMessage(body, "Não foi possível comparar as UFs. Tente novamente."));
    renderComparison(body);
    comparisonStatus.textContent = `${Array.isArray(body?.resultados) ? body.resultados.length : 0} resultado(s) recebido(s).`;
  } catch (error) {
    comparisonStatus.textContent = error instanceof Error ? error.message : "Não foi possível conectar para comparar as UFs.";
  } finally {
    compareSubmit.disabled = false;
  }
});

function historyValue(row, ...keys) {
  for (const key of keys) {
    if (row?.[key] !== undefined && row[key] !== null) return row[key];
  }
  return "";
}

function historyDateValue(row) {
  return historyValue(row, "criado_em", "data", "created_at");
}

function filteredHistory() {
  const ncm = historyNcm.value.trim().toLocaleLowerCase("pt-BR");
  const uf = historyUf.value;
  const date = historyDate.value;
  const scenario = historyScenario.value;
  return historyRows.filter((row) => {
    const code = String(historyValue(row, "codigo_ncm", "codigo", "ncm")).toLocaleLowerCase("pt-BR");
    const rowScenario = String(historyValue(row, "cenario", "scenario")).toLocaleLowerCase("pt-BR");
    const created = historyDateValue(row);
    const rowDate = created ? String(created).slice(0, 10) : "";
    return (!ncm || code.includes(ncm))
      && (!uf || String(historyValue(row, "uf")).toUpperCase() === uf)
      && (!date || rowDate === date)
      && (!scenario || rowScenario === scenario);
  });
}

function renderHistory() {
  historyList.replaceChildren();
  const rows = filteredHistory();
  historyStatus.textContent = rows.length ? `${rows.length} consulta(s) correspondente(s).` : "Nenhuma consulta encontrada para os filtros atuais.";
  for (const row of rows) {
    const item = document.createElement("li");
    item.className = "rounded-xl border border-slate-200 p-4";
    const heading = document.createElement("h3");
    heading.className = "font-semibold";
    heading.textContent = `${displayValue(historyValue(row, "codigo_ncm", "codigo"))} · ${displayValue(historyValue(row, "uf"))} · ${displayValue(historyValue(row, "descricao_produto", "descricao"))}`;
    item.append(heading);
    const summary = document.createElement("p");
    summary.className = "mt-1 text-sm text-slate-600";
    summary.textContent = `Valor base: ${displayValue(historyValue(row, "valor_unitario", "valor"))} · Cenário: ${displayValue(historyValue(row, "cenario", "scenario"))} · ${displayValue(historyDateValue(row))}`;
    item.append(summary);

    const disclosure = document.createElement("details");
    disclosure.className = "mt-3";
    const disclosureSummary = document.createElement("summary");
    disclosureSummary.className = "min-h-11 cursor-pointer py-2 text-sm font-semibold text-teal-800";
    disclosureSummary.textContent = "Detalhes da consulta";
    const details = document.createElement("dl");
    details.className = "grid gap-3 border-t border-slate-100 pt-3 sm:grid-cols-2";
    for (const [key, value] of Object.entries(row)) addDefinition(details, key, value);
    disclosure.append(disclosureSummary, details);
    item.append(disclosure);
    historyList.append(item);
  }
}

async function loadHistory() {
  document.getElementById("refresh-history").disabled = true;
  historyStatus.textContent = "Carregando histórico...";
  try {
    const response = await fetch("/api/historico?limit=50", { headers: { Accept: "application/json" } });
    const body = await response.json().catch(() => null);
    if (!response.ok || !Array.isArray(body)) {
      throw new Error(makeErrorMessage(body, "Não foi possível carregar o histórico. Tente novamente."));
    }
    historyRows = body;
    const ufs = [...new Set(body.map((row) => String(historyValue(row, "uf")).toUpperCase()).filter(Boolean))].sort();
    historyUf.replaceChildren(new Option("Todas", ""));
    for (const uf of ufs) historyUf.add(new Option(uf, uf));
    renderHistory();
  } catch (error) {
    historyRows = [];
    historyList.replaceChildren();
    historyStatus.textContent = error instanceof Error ? error.message : "Não foi possível conectar para carregar o histórico.";
  } finally {
    document.getElementById("refresh-history").disabled = false;
  }
}

for (const filter of [historyNcm, historyUf, historyDate, historyScenario]) {
  filter.addEventListener("input", renderHistory);
  filter.addEventListener("change", renderHistory);
}
document.getElementById("refresh-history").addEventListener("click", loadHistory);
loadHistory();
