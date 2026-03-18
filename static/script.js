

const API_PREFIX = "/api"; 
let currentPage = 1;
let currentTotalPages = 1;
let currentController = null;

document.addEventListener("DOMContentLoaded", async function () {
  await carregarRotas();

  const btn = document.getElementById("btnBuscar");
  if (btn) {
    btn.addEventListener("click", () => buscarLogs(1));
  }
});

function buildUrl(page = 1) {
  const pageSize = document.getElementById("pageSize")?.value || "100";
  const keyword = document.getElementById("keyword")?.value.trim() || "";
  const ip = document.getElementById("ip")?.value.trim() || "";
  const porta = document.getElementById("porta")?.value.trim() || "";
  const day = document.getElementById("day")?.value || ""; // 
  const hourFrom = document.getElementById("hour_from")?.value || ""; 
  const hourTo = document.getElementById("hour_to")?.value || ""; 
  const ipRota = document.getElementById("ip_rota")?.value.trim() || "";

  if (!ipRota) {
    throw new Error("Seleciona uma origem.");
  }

  const params = new URLSearchParams();
  params.set("ip_rota", ipRota);
  params.set("pagina", String(page));
  params.set("tamanho_pagina", String(pageSize));

  if (keyword) params.set("palavra_chave", keyword);
  if (ip) params.set("ip_nat", ip);
  if (porta) params.set("porta_nat", porta);

  if (day) {
    const [year, month, dayPart] = day.split("-");
    if (year) params.set("ano", year);
    if (month) params.set("mes", month.padStart(2, "0"));
    if (dayPart) params.set("dia", dayPart.padStart(2, "0"));
  }

  if (hourFrom) params.set("hora_de", hourFrom);
  if (hourTo) params.set("hora_ate", hourTo);

  return `${API_PREFIX}/logs/filter?${params.toString()}`;
}

function clearTable() {
  const tbody = document.querySelector("#tabelaLogs tbody");
  if (tbody) tbody.innerHTML = "";
}

function appendRow(obj) {
  const tbody = document.querySelector("#tabelaLogs tbody");
  if (!tbody) return;

  const data = obj.data || "";
  const protocolo = obj.protocolo || "";
  const origem = obj.origem || (obj.linha ? obj.linha : "");
  const nat = obj.nat || "";
  const destino = obj.destino || "";
  const destino_final = obj.destino_final || "";

  const tr = document.createElement("tr");
  tr.innerHTML = `
    <td>${escapeHtml(data)}</td>
    <td>${escapeHtml(protocolo)}</td>
    <td>${escapeHtml(origem)}</td>
    <td>${escapeHtml(nat)}</td>
    <td>${escapeHtml(destino)}</td>
    <td>${escapeHtml(destino_final)}</td>
  `;
  tbody.appendChild(tr);
}

function escapeHtml(value) {
  if (value === null || value === undefined) return "";
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function renderPagination(page, totalPages) {
  currentPage = page;
  currentTotalPages = totalPages || 1;

  const pagination = document.getElementById("pagination");
  if (!pagination) return;

  const prevDisabled = page <= 1 ? "disabled" : "";
  const nextDisabled = page >= totalPages ? "disabled" : "";

  pagination.innerHTML = `
    Página ${page} de ${totalPages || 1}
    <button id="btnPrev" ${prevDisabled}>Anterior</button>
    <button id="btnNext" ${nextDisabled}>Próxima</button>
  `;

  const btnPrev = document.getElementById("btnPrev");
  const btnNext = document.getElementById("btnNext");

  if (btnPrev) {
    btnPrev.addEventListener("click", () => {
      if (page > 1) buscarLogs(page - 1);
    });
  }

  if (btnNext) {
    btnNext.addEventListener("click", () => {
      if (page < totalPages) buscarLogs(page + 1);
    });
  }
}

async function buscarLogs(page = 1) {
  if (currentController) {
    currentController.abort();
    currentController = null;
  }

  clearTable();

  const statusEl = document.getElementById("status");
  if (statusEl) statusEl.textContent = "Carregando...";

  let url;
  try {
    url = buildUrl(page);
  } catch (err) {
    if (statusEl) statusEl.textContent = err.message;
    alert(err.message);
    return;
  }

  console.log("URL chamada:", url);

  currentController = new AbortController();
  const signal = currentController.signal;

  try {
    const resp = await fetch(url, {
      signal,
      headers: {
        "Accept": "application/x-ndjson"
      }
    });

    if (!resp.ok) {
      const text = await resp.text();
      console.error("Resposta não OK:", resp.status, text);

      if (statusEl) {
        statusEl.textContent = `Erro ${resp.status}`;
      }

      try {
        const json = JSON.parse(text);
        if (json.erro) {
          alert(json.erro);
          if (statusEl) statusEl.textContent = json.erro;
        }
      } catch {
      }

      return;
    }

    if (!resp.body) {
      if (statusEl) statusEl.textContent = "Resposta sem corpo.";
      return;
    }

    const reader = resp.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";
    let receivedCount = 0;

    const pageSize = parseInt(document.getElementById("pageSize")?.value || "100", 10);
    let totalPagesGuess = page;

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      const lines = buffer.split("\n");
      buffer = lines.pop() || "";

      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed) continue;

        try {
          const obj = JSON.parse(trimmed);
          appendRow(obj);
          receivedCount++;
        } catch (e) {
          console.warn("Erro ao parsear linha NDJSON:", e, trimmed);
        }
      }
    }

    // processa sobra final do buffer
    if (buffer.trim()) {
      try {
        const obj = JSON.parse(buffer.trim());
        appendRow(obj);
        receivedCount++;
      } catch (e) {
        console.warn("Erro ao parsear buffer final:", e, buffer);
      }
    }

    if (receivedCount < pageSize) {
      totalPagesGuess = page;
    } else {
      totalPagesGuess = page + 1;
    }

    renderPagination(page, totalPagesGuess);

    if (statusEl) {
      statusEl.textContent = `Recebidos ${receivedCount} linhas.`;
    }
  } catch (err) {
    if (err.name === "AbortError") {
      if (statusEl) statusEl.textContent = "Busca cancelada.";
      console.log("Fetch abortado.");
    } else {
      if (statusEl) statusEl.textContent = "Erro ao buscar logs.";
      console.error("Erro no fetch:", err);
    }
  } finally {
    currentController = null;
  }
}

async function carregarRotas() {
  const select = document.getElementById("ip_rota");
  if (!select) return;

  select.innerHTML = `<option value="">Carregando rotas...</option>`;

  try {
    const resp = await fetch(`${API_PREFIX}/rotas`);

    if (!resp.ok) {
      const text = await resp.text();
      throw new Error(`Erro HTTP ${resp.status}: ${text}`);
    }

    const data = await resp.json();
    const rotas = Array.isArray(data.rotas) ? data.rotas : [];

    select.innerHTML = `<option value="">Seleciona uma origem</option>`;

    if (rotas.length === 0) {
      select.innerHTML = `<option value="">Nenhuma rota encontrada</option>`;
      return;
    }

    for (const rota of rotas) {
      const option = document.createElement("option");
      option.value = rota;
      option.textContent = rota;
      select.appendChild(option);
    }
  } catch (err) {
    console.error("Erro ao carregar rotas:", err);
    select.innerHTML = `<option value="">Erro ao carregar rotas</option>`;
  }
}