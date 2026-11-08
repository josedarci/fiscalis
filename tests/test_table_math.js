"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const test = require("node:test");
const vm = require("node:vm");

class TestElement {
  constructor() {
    this.children = [];
    this.listeners = new Map();
    this.attributes = new Map();
    this.value = "";
    this.checked = false;
    this.isConnected = true;
    this.tokens = new Set();
    this.classList = {
      add: (...tokens) => tokens.forEach((token) => this.tokens.add(token)),
      remove: (...tokens) => tokens.forEach((token) => this.tokens.delete(token)),
      contains: (token) => this.tokens.has(token),
      toggle: (token, force) => {
        const enabled = force ?? !this.tokens.has(token);
        if (enabled) this.tokens.add(token);
        else this.tokens.delete(token);
        return enabled;
      },
    };
  }

  get textContent() {
    return (this._text ?? "") + this.children.map((child) => child.textContent).join("");
  }

  set textContent(value) {
    this._text = String(value);
    this.children = [];
  }

  append(...children) {
    this.children.push(...children);
  }

  replaceChildren(...children) {
    this._text = "";
    this.children = children;
  }

  addEventListener(name, callback) {
    this.listeners.set(name, callback);
  }

  setAttribute(name, value) {
    this.attributes.set(name, value);
  }

  showModal() {}

  close() {}

  focus() {}
}

function runQuoteScenarios() {
  const elements = new Map();
  const document = {
    getElementById(id) {
      if (!elements.has(id)) elements.set(id, new TestElement());
      return elements.get(id);
    },
    createElement() {
      return new TestElement();
    },
    createElementNS() {
      return new TestElement();
    },
    createTextNode(value) {
      const element = new TestElement();
      element.textContent = value;
      return element;
    },
  };
  const context = { document, TestElement };
  vm.createContext(context);
  const source = fs.readFileSync("static/tabela.js", "utf8");
  vm.runInContext(
    `${source}
const item = {
  codigo: "01012100",
  descricao: "Produto",
  tipo: "0",
  nacionalfederal: "10",
  importadosfederal: "20",
  estadual: "2.5",
  municipal: "1"
};
openServiceQuote(item, new TestElement());
servicePriceInput.value = "100.00";
federalScenarioSelect.value = "nacional";
renderServiceQuote();
const national = {
  federalRate: serviceBreakdown.children[0].children[1].children[0].textContent,
  taxTotal: document.getElementById("service-tax-total").textContent,
  grandTotal: document.getElementById("service-grand-total").textContent
};
federalScenarioSelect.value = "importado";
renderServiceQuote();
const imported = {
  federalRate: serviceBreakdown.children[0].children[1].children[0].textContent,
  taxTotal: document.getElementById("service-tax-total").textContent,
  grandTotal: document.getElementById("service-grand-total").textContent
};
const rounding = {
  halfCentBase: amountInCents("0.005").toString(),
  halfCentTax: taxInCents(amountInCents("0.20"), parseDecimal("2.5", true)).toString()
};
globalThis.quoteResults = { national, imported, rounding };
`,
    context,
  );
  return context.quoteResults;
}

test("national and imported federal rates are alternative calculation scenarios", () => {
  const { national, imported, rounding } = runQuoteScenarios();

  assert.equal(national.federalRate, "10,00%");
  assert.ok(national.taxTotal.includes("R$"));
  assert.ok(national.taxTotal.includes("13,50"));
  assert.ok(national.grandTotal.includes("113,50"));
  assert.equal(imported.federalRate, "20,00%");
  assert.ok(imported.taxTotal.includes("23,50"));
  assert.ok(imported.grandTotal.includes("123,50"));
  assert.equal(rounding.halfCentBase, "1");
  assert.equal(rounding.halfCentTax, "1");
});
