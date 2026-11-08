"use strict";

const form = document.getElementById("consulta-form");
const submitButton = document.getElementById("submit-button");
const submitLabel = document.getElementById("submit-label");
const submitSpinner = document.getElementById("submit-spinner");
const formError = document.getElementById("form-error");
const resultPlaceholder = document.getElementById("result-placeholder");
const resultContent = document.getElementById("result-content");
const resultProduct = document.getElementById("result-product");
const taxBreakdown = document.getElementById("tax-breakdown");
const estimatedTotal = document.getElementById("estimated-total");
const resultSource = document.getElementById("result-source");
const historyStatus = document.getElementById("history-status");
const historyList = document.getElementById("history-list");
const refreshHistoryButton = document.getElementById("refresh-history");

const taxFields = [
  ["Nacional", "Nacional"],
  ["Estadual", "Estadual"],
  ["Municipal", "Municipal"],
  ["Importado", "Importado"],
];
const currencyFormatter = new Intl.NumberFormat("pt-BR", {
  style: "currency",
  currency: "BRL",
});
const percentFormatter = new Intl.NumberFormat("pt-BR", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 4,
});

function formatCurrency(value) {
  if (value === null || value === undefined || value === "") return "Não informado";
  const number = Number(value);
  return Number.isFinite(number) ? currencyFormatter.format(number) : "Não informado";
}

function formatPercent(value) {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? `${percentFormatter.format(number)}%` : null;
}

function setFormError(message) {
  formError.textContent = message;
  formError.hidden = !message;
}

function markFieldInvalid(field, message) {
  const error = document.getElementById(`${field.id}-error`);
  field.setAttribute("aria-invalid", "true");
  if (error) {
    error.textContent = message;
    error.hidden = false;
  }
}

function clearFieldError(field) {
  field.removeAttribute("aria-invalid");
  const error = document.getElementById(`${field.id}-error`);
  if (error) {
    error.textContent = "";
    error.hidden = true;
  }
}

function validateForm() {
  const fields = {
    codigo: form.elements.codigo,
    uf: form.elements.uf,
    descricao: form.elements.descricao,
    valor: form.elements.valor,
    ex: form.elements.ex,
    unidadeMedida: form.elements.unidadeMedida,
    gtin: form.elements.gtin,
  };
  Object.values(fields).forEach(clearFieldError);
  setFormError("");
  let firstInvalid = null;

  const fail = (field, message) => {
    markFieldInvalid(field, message);
    firstInvalid ??= field;
  };

  if (!/^\d{8}$/.test(fields.codigo.value.trim())) {
    fail(fields.codigo, "Informe um NCM com exatamente 8 dígitos.");
  }
  if (!fields.uf.value) fail(fields.uf, "Selecione uma UF.");
  if (!fields.descricao.value.trim()) {
    fail(fields.descricao, "Informe a descrição do produto.");
  } else if (fields.descricao.value.trim().length > 255) {
    fail(fields.descricao, "A descrição deve ter no máximo 255 caracteres.");
  }
  const price = Number(fields.valor.value);
  if (!fields.valor.value || !Number.isFinite(price) || price <= 0) {
    fail(fields.valor, "Informe um valor de entrada maior que zero.");
  }
  if (fields.unidadeMedida.value.trim().length > 20) {
    fail(fields.unidadeMedida, "A unidade de medida deve ter até 20 caracteres.");
  }
  if (fields.gtin.value.trim().length > 20) {
    fail(fields.gtin, "O GTIN deve ter até 20 caracteres.");
  }
  if (fields.ex.value !== "" && (!/^\d+$/.test(fields.ex.value) || Number(fields.ex.value) < 0)) {
    fail(fields.ex, "A exceção deve ser um número inteiro igual ou maior que zero.");
  }
  if (firstInvalid) firstInvalid.focus();
  return !firstInvalid;
}

function setLoading(loading) {
  submitButton.disabled = loading;
  submitSpinner.hidden = !loading;
  submitLabel.textContent = loading ? "Consultando..." : "Consultar estimativa";
}

function showPendingResult(message) {
  resultContent.hidden = true;
  resultPlaceholder.textContent = message;
  resultPlaceholder.hidden = false;
}

function appendTaxRow(list, label, rate, amount) {
  const row = document.createElement("div");
  row.className = "flex items-start justify-between gap-3 rounded-lg border border-slate-100 px-3 py-3";
  const name = document.createElement("dt");
  name.className = "text-sm font-medium text-slate-700";
  name.textContent = label;
  const values = document.createElement("dd");
  values.className = "text-right";
  const percent = document.createElement("span");
  percent.className = "block text-sm font-semibold text-slate-900";
  percent.textContent = rate === null ? "Percentual não informado" : rate;
  const money = document.createElement("span");
  money.className = "mt-0.5 block text-xs text-slate-500";
  money.textContent = amount === null ? "Valor não calculado" : formatCurrency(amount);
  values.append(percent, money);
  row.append(name, values);
  list.append(row);
}

function renderResult(result, submitted) {
  taxBreakdown.replaceChildren();
  resultProduct.textContent = `${submitted.codigo} · ${submitted.uf} · ${submitted.descricao}`;
  let total = 0;
  let knownRates = 0;

  taxFields.forEach(([key, label]) => {
    const formattedRate = formatPercent(result[key]);
    const numericRate = result[key] === null || result[key] === undefined || result[key] === ""
      ? null
      : Number(result[key]);
    const amount = numericRate !== null && Number.isFinite(numericRate)
      ? submitted.price * numericRate / 100
      : null;
    if (amount !== null) {
      total += amount;
      knownRates += 1;
    }
    appendTaxRow(taxBreakdown, label, formattedRate, amount);
  });

  estimatedTotal.textContent = knownRates ? formatCurrency(total) : "Não disponível";
  if (knownRates > 0 && knownRates < taxFields.length) {
    const note = document.createElement("span");
    note.textContent = " (parcial: nem todos os percentuais foram informados)";
    estimatedTotal.append(note);
  }
  resultSource.textContent = result.Fonte ? `Fonte informada: ${String(result.Fonte)}` : "";
  resultPlaceholder.hidden = true;
  resultContent.hidden = false;
}

function friendlyError(status, body) {
  if (status === 422 && Array.isArray(body?.detail)) {
    const first = body.detail.find((item) => typeof item?.msg === "string");
    if (first?.msg) {
      const messages = {
        "codigo/NCM deve conter exatamente oito dígitos.": "O NCM deve conter exatamente 8 dígitos.",
        "valor deve ser um número positivo.": "O valor de entrada deve ser maior que zero.",
        "descricao não pode ser vazia.": "Informe a descrição do produto.",
      };
      return messages[first.msg] || "Confira os dados informados e tente novamente.";
    }
  }
  if (typeof body?.detail === "string") {
    const detail = body.detail;
    if (detail.includes("Tempo esgotado")) return "A consulta demorou mais do que o esperado. Tente novamente.";
    if (detail.includes("Não foi possível conectar") || detail.includes("Falha ao consultar")) {
      return "Não foi possível concluir a consulta externa. Tente novamente em instantes.";
    }
    if (detail.includes("banco de dados") || detail.includes("banco")) {
      return "O serviço está temporariamente indisponível para registrar a consulta.";
    }
    if (detail.includes("configuração") || detail.includes("variável")) {
      return "O serviço ainda não está configurado para realizar consultas. Tente novamente mais tarde.";
    }
    if (detail.includes("NCM") || detail.includes("UF") || detail.includes("valor")) return detail;
  }
  if (status === 422) return "Confira os dados informados e tente novamente.";
  if (status === 503) return "O serviço está temporariamente indisponível. Tente novamente mais tarde.";
  if (status === 504) return "A consulta demorou mais do que o esperado. Tente novamente.";
  return "Não foi possível realizar a consulta. Tente novamente mais tarde.";
}

form.addEventListener("input", (event) => {
  if (event.target instanceof HTMLElement) clearFieldError(event.target);
});
form.addEventListener("change", (event) => {
  if (event.target instanceof HTMLElement) clearFieldError(event.target);
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!validateForm()) return;

  const formData = new FormData(form);
  const price = Number(formData.get("valor"));
  const payload = {
    codigo: String(formData.get("codigo")).trim(),
    uf: String(formData.get("uf")),
    descricao: String(formData.get("descricao")).trim(),
    valor: String(formData.get("valor")).trim(),
  };
  const unidadeMedida = String(formData.get("unidadeMedida")).trim();
  const gtin = String(formData.get("gtin")).trim();
  const ex = String(formData.get("ex")).trim();
  if (unidadeMedida) payload.unidadeMedida = unidadeMedida;
  if (gtin) payload.gtin = gtin;
  if (ex) payload.ex = Number(ex);

  setLoading(true);
  setFormError("");
  showPendingResult("Consultando os percentuais. Aguarde...");
  try {
    const response = await fetch("/api/consultar-imposto", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(payload),
    });
    const body = await response.json().catch(() => null);
    if (!response.ok) {
      showPendingResult("A consulta não foi concluída. Revise os dados ou tente novamente.");
      setFormError(friendlyError(response.status, body));
      return;
    }
    if (!body || typeof body !== "object" || !taxFields.some(([key]) => body[key] !== undefined)) {
      showPendingResult("A resposta do serviço não continha uma estimativa válida.");
      setFormError("Não foi possível interpretar o resultado. Tente novamente mais tarde.");
      return;
    }
    renderResult(body, { ...payload, price });
    await loadHistory();
  } catch {
    showPendingResult("A consulta não foi concluída. Verifique sua conexão e tente novamente.");
    setFormError("Não foi possível conectar ao serviço. Verifique sua conexão e tente novamente.");
  } finally {
    setLoading(false);
  }
});

function historyValue(row, key) {
  return row[key] === null || row[key] === undefined || row[key] === "" ? null : row[key];
}

function addHistoryField(card, label, value) {
  const line = document.createElement("p");
  line.className = "text-sm leading-6 text-slate-600";
  const title = document.createElement("span");
  title.className = "font-medium text-slate-700";
  title.textContent = `${label}: `;
  const text = document.createElement("span");
  text.textContent = value === null || value === undefined || value === "" ? "—" : String(value);
  line.append(title, text);
  card.append(line);
}

function renderHistory(rows) {
  historyList.replaceChildren();
  if (!rows.length) {
    historyStatus.textContent = "Nenhuma consulta encontrada.";
    return;
  }
  historyStatus.textContent = `${rows.length} ${rows.length === 1 ? "consulta encontrada" : "consultas encontradas"}.`;
  rows.forEach((row) => {
    const card = document.createElement("article");
    card.className = "min-w-0 rounded-xl border border-slate-200 p-4";
    const heading = document.createElement("h3");
    heading.className = "mb-2 break-words font-semibold text-slate-900";
    heading.textContent = `${historyValue(row, "codigo") ?? "NCM não informado"} · ${historyValue(row, "uf") ?? "UF não informada"}`;
    card.append(heading);
    addHistoryField(card, "Descrição", historyValue(row, "descricao"));
    addHistoryField(card, "Valor de entrada", formatCurrency(historyValue(row, "valor")));
    addHistoryField(card, "Data", formatDate(historyValue(row, "criado_em")));

    const rates = document.createElement("div");
    rates.className = "mt-3 grid grid-cols-2 gap-x-3 gap-y-1 border-t border-slate-100 pt-3";
    taxFields.forEach(([key, label]) => {
      const rate = document.createElement("p");
      rate.className = "text-xs leading-5 text-slate-500";
      rate.textContent = `${label}: ${formatPercent(historyValue(row, key.toLowerCase())) ?? "—"}`;
      rates.append(rate);
    });
    card.append(rates);
    if (historyValue(row, "fonte")) addHistoryField(card, "Fonte", historyValue(row, "fonte"));
    historyList.append(card);
  });
}

function formatDate(value) {
  if (!value) return "—";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? String(value) : new Intl.DateTimeFormat("pt-BR", {
    dateStyle: "short",
    timeStyle: "short",
  }).format(parsed);
}

async function loadHistory() {
  refreshHistoryButton.disabled = true;
  historyStatus.textContent = "Carregando histórico...";
  try {
    const response = await fetch("/api/historico", {
      headers: { Accept: "application/json" },
    });
    const body = await response.json().catch(() => null);
    if (!response.ok || !Array.isArray(body)) {
      historyList.replaceChildren();
      historyStatus.textContent = response.ok
        ? "Não foi possível interpretar o histórico."
        : "Não foi possível carregar o histórico. Tente novamente.";
      return;
    }
    renderHistory(body);
  } catch {
    historyList.replaceChildren();
    historyStatus.textContent = "Não foi possível conectar para carregar o histórico.";
  } finally {
    refreshHistoryButton.disabled = false;
  }
}

refreshHistoryButton.addEventListener("click", loadHistory);
loadHistory();
