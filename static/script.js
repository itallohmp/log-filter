// script.js
// Leitura em streaming NDJSON do backend e renderização incremental na tabela.
// Mantém mudanças mínimas na UI e usa AbortController para cancelar fetch anterior.

let currentPage = 1;
let currentTotalPages = 1;
let currentController = null;

document.addEventListener("DOMContentLoaded", function () {
    document.getElementById("btnBuscar").addEventListener("click", () => buscarLogs(1));
    // opcional: buscar ao carregar com valores padrão
    // buscarLogs(1);
});

function buildUrl(page = 1) {
    const pageSize = document.getElementById("pageSize").value;
    const keyword = document.getElementById("keyword").value;
    const ip = document.getElementById("ip").value;
    const porta = document.getElementById("porta").value;
    const day = document.getElementById("day").value;       // YYYY-MM-DD
    const hourFrom = document.getElementById("hour_from").value; // HH:MM
    const hourTo = document.getElementById("hour_to").value;     // HH:MM

    let url = `/logs/filter?page=${page}&page_size=${pageSize}`;

    if (keyword) url += `&keyword=${encodeURIComponent(keyword)}`;
    if (ip) url += `&client_ip=${encodeURIComponent(ip)}`;
    if (porta) url += `&porta=${encodeURIComponent(porta)}`;
    if (day) {
        const [year, month, dayPart] = day.split("-");
        url += `&year=${encodeURIComponent(year)}&month=${encodeURIComponent(month)}&day=${encodeURIComponent(dayPart)}`;
    }
    if (hourFrom) url += `&hour_from=${encodeURIComponent(hourFrom)}`;
    if (hourTo) url += `&hour_to=${encodeURIComponent(hourTo)}`;

    return url;
}

function clearTable() {
    const tbody = document.querySelector("#tabelaLogs tbody");
    tbody.innerHTML = "";
}

function appendRow(obj) {
    const tbody = document.querySelector("#tabelaLogs tbody");
    // se o objeto for apenas {linha: "..."} mostramos a linha crua na primeira coluna
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

// simples escape para evitar injeção de HTML
function escapeHtml(s) {
    if (!s && s !== 0) return "";
    return String(s)
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
    const prevDisabled = page <= 1 ? "disabled" : "";
    const nextDisabled = page >= totalPages ? "disabled" : "";

    pagination.innerHTML = `
        Página ${page} de ${totalPages || 1}
        <button id="btnPrev" ${prevDisabled}>Anterior</button>
        <button id="btnNext" ${nextDisabled}>Próxima</button>
    `;

    document.getElementById("btnPrev").addEventListener("click", () => {
        if (page > 1) buscarLogs(page - 1);
    });
    document.getElementById("btnNext").addEventListener("click", () => {
        if (page < totalPages) buscarLogs(page + 1);
    });
}

async function buscarLogs(page = 1) {
    // cancela fetch anterior se existir
    if (currentController) {
        currentController.abort();
        currentController = null;
    }

    clearTable();
    document.getElementById("status").textContent = "Carregando...";
    const url = buildUrl(page);
    console.log("URL chamada:", url);

    currentController = new AbortController();
    const signal = currentController.signal;

    try {
        const resp = await fetch(url, { signal });

        if (!resp.ok) {
            const text = await resp.text();
            document.getElementById("status").textContent = `Erro: ${resp.status}`;
            console.error("Resposta não OK:", resp.status, text);
            return;
        }

        // O backend envia NDJSON (uma linha JSON por resultado).
        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let { value: chunk, done } = await reader.read();
        let buffer = "";
        let receivedCount = 0;

        // Se o backend não retorna total, tentamos inferir total_pages a partir do page_size
        const pageSize = parseInt(document.getElementById("pageSize").value, 10);
        let totalPagesGuess = page; // fallback

        while (!done) {
            buffer += decoder.decode(chunk, { stream: true });

            // processa linhas completas (separadas por \n)
            let lines = buffer.split("\n");
            // mantém o último pedaço (pode ser parcial)
            buffer = lines.pop();

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

            // ler próximo chunk
            ({ value: chunk, done } = await reader.read());
        }

        // processa qualquer resto no buffer
        if (buffer) {
            const trimmed = buffer.trim();
            if (trimmed) {
                try {
                    const obj = JSON.parse(trimmed);
                    appendRow(obj);
                    receivedCount++;
                } catch (e) {
                    console.warn("Erro ao parsear buffer final:", e, trimmed);
                }
            }
        }

        // Como o backend não envia total, assumimos que se recebeu menos que pageSize então é última página.
        if (receivedCount < pageSize) {
            totalPagesGuess = page;
        } else {
            // não sabemos total real; permitir próxima página
            totalPagesGuess = page + 1;
        }

        renderPagination(page, totalPagesGuess);
        document.getElementById("status").textContent = `Recebidos ${receivedCount} linhas.`;
    } catch (err) {
        if (err.name === "AbortError") {
            document.getElementById("status").textContent = "Busca cancelada.";
            console.log("Fetch abortado.");
        } else {
            document.getElementById("status").textContent = "Erro ao buscar logs.";
            console.error("Erro no fetch:", err);
        }
    } finally {
        currentController = null;
    }
}