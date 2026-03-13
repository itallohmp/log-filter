document.addEventListener("DOMContentLoaded", function () {

    document.getElementById("btnBuscar").addEventListener("click", buscarLogs);

});

async function buscarLogs() {

    const lines = document.getElementById("lines").value;
    const keyword = document.getElementById("keyword").value;
    const ip = document.getElementById("ip").value;
    const porta = document.getElementById("porta").value;
    const data = document.getElementById("data").value;

    let url = `/logs/filter?limit=${lines}`;

    if (keyword) {
        url += `&keyword=${encodeURIComponent(keyword)}`;
    }

    if (ip) {
        url += `&client_ip=${encodeURIComponent(ip)}`;
    }

    if (porta) {
        url += `&porta=${encodeURIComponent(porta)}`;
    }

    if (data) {
        url += `&data=${encodeURIComponent(data)}`;
    }

    console.log("URL chamada:", url);  // ajuda a debugar

    const resp = await fetch(url);
    const result = await resp.json();

    const tbody = document.querySelector("#tabelaLogs tbody");
    tbody.innerHTML = "";

    const logs = result.logs || [];

    if (logs.length > 0) {

        logs.forEach(log => {

            const row = `
            <tr>
                <td>${log.data}</td>
                <td>${log.protocolo}</td>
                <td>${log.origem}</td>
                <td>${log.nat}</td>
                <td>${log.destino}</td>
                <td>${log.destino_final}</td>
            </tr>
            `;

            tbody.innerHTML += row;

        });

    } else {

        tbody.innerHTML = `<tr><td colspan="6">Nenhum log encontrado</td></tr>`;

    }

}