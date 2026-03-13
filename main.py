from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import StreamingResponse

import paramiko
import json, re, glob, os, math, subprocess
from datetime import datetime, time
from typing import Optional

app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

@app.get("/")
def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

# -------------------------------
# SSH LOG FETCH
# -------------------------------

def get_logs(limit: int = 50):

    hostname = "10.10.10.208"
    username = "plog"
    private_key_path = "/home/plog/.ssh/id_rsa"

    key = paramiko.RSAKey.from_private_key_file(private_key_path)

    with paramiko.SSHClient() as ssh:
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        ssh.connect(
            hostname=hostname,
            username=username,
            pkey=key,
            timeout=10
        )

        stdin, stdout, stderr = ssh.exec_command(
            f"tail -n {limit} /var/log/syslog"
        )

        logs = stdout.read().decode()

    return logs


# -------------------------------
# PARSE LOG
# -------------------------------

pattern = re.compile(
    r"\*(\w+\s+\d+\s+\d+:\d+:\d+\.\d+).*?"
    r"Created Translation\s+"
    r"(UDP|TCP)\s+"
    r"(\d+\.\d+\.\d+\.\d+:\d+)\s+"  # origem
    r"(\d+\.\d+\.\d+\.\d+:\d+)\s+"  # nat
    r"(\d+\.\d+\.\d+\.\d+:\d+)\s+"  # destino
    r"(\d+\.\d+\.\d+\.\d+:\d+)\s+"  # destino final
    r"\d+"
)


def parse_log_line(line: str):
    match = pattern.search(line)
    if not match:
        return None

    data, protocolo, origem, nat, destino, destino_final = match.groups()
    return {
        "data": data,
        "protocolo": protocolo,
        "origem": origem,
        "nat": nat,
        "destino": destino,
        "destino_final": destino_final
    }


# -------------------------------
# UTIL: parse hora string robusta
# -------------------------------

def parse_time_str(h: str) -> Optional[time]:

    if not h:
        return None
    for fmt in ("%H:%M", "%H:%M:%S", "%H:%M:%S.%f"):
        try:
            return datetime.strptime(h, fmt).time()
        except Exception:
            continue
    return None


# -------------------------------
# FILTRO DE LOGS (STREAMING)
# -------------------------------

@app.get("/logs/filter")
def filter_logs(
    ip_rota: str = "172.16.10.1",
    ip_nat: Optional[str] = None,
    porta_nat: Optional[str] = None,
    ano: str = "2026",
    mes: str = "03",
    dia: str = "11",
    hora_de: Optional[str] = None,
    hora_ate: Optional[str] = None,
    palavra_chave: Optional[str] = None,
    pagina: int = 1,
    tamanho_pagina: int = 100
):
    script_download = "/home/plog/venv/logs/modulos/script-download-logs.sh"
    script_descompacta = "/home/plog/venv/logs/modulos/script-descompacta-log.sh"

    caminho = f"/home/plog/venv/logs/{ip_rota}/{ano}/{mes}/{dia}"

    try:
        print("Buscando logs em:", caminho)

        arquivos_bz = glob.glob(f"{caminho}/*.bz")
        arquivos_log = glob.glob(f"{caminho}/*.log")

        if not arquivos_bz and not arquivos_log:
            print("Logs não encontrados, baixando...")
            subprocess.run(
                ["bash", script_download, ip_rota, ano, mes, dia],
                check=True,
                timeout=120
            )
            arquivos_bz = glob.glob(f"{caminho}/*.bz")
            arquivos_log = glob.glob(f"{caminho}/*.log")

        if not arquivos_bz and not arquivos_log:
            print("Nenhum arquivo de log encontrado após tentativa de download")
            return {"erro": "Nenhum log encontrado"}

        if arquivos_bz and not arquivos_log:
            print("Descompactando arquivos .bz...")
            subprocess.run(
                ["bash", script_descompacta, ip_rota, ano, mes, dia],
                check=True,
                timeout=120
            )
            arquivos_log = glob.glob(f"{caminho}/*.log")

        if not arquivos_log:
            print("Nenhum .log após descompactar")
            return {"erro": "Nenhum log encontrado após descompactar"}

        print("Usando logs descompactados (.log)")

        # -----------------------------
        # Ordenar arquivos numericamente por sufixo e selecionar por intervalo de horas
        # Arquivos esperados: 00.log ... 23.log
        # -----------------------------
        def chave_ordenacao_numerica(p):
            nome = os.path.basename(p)
            nums = re.findall(r"(\d+)", nome)
            if not nums:
                return nome
            return int(nums[-1])

        arquivos_ordenados = sorted(arquivos_log, key=chave_ordenacao_numerica)

        # se não houver filtro de hora, usa todos (limitado a 50)
        if not hora_de and not hora_ate:
            arquivos = arquivos_ordenados[:50]
        else:
            # extrai horas solicitadas (apenas a parte HH)
            try:
                hora_inicio = int(hora_de.split(":")[0]) if hora_de else 0
            except Exception:
                hora_inicio = 0
            try:
                hora_fim = int(hora_ate.split(":")[0]) if hora_ate else 23
            except Exception:
                hora_fim = 23

            if hora_inicio <= hora_fim:
                horas_incluir = set(range(hora_inicio, hora_fim + 1))
            else:
                horas_incluir = set(range(hora_inicio, 24)) | set(range(0, hora_fim + 1))

            def hora_do_arquivo(p):
                nome = os.path.basename(p)
                m = re.search(r"(\d{1,2})(?=\D*\.log$)", nome)
                if not m:
                    nums = re.findall(r"(\d+)", nome)
                    if not nums:
                        return None
                    return int(nums[-1]) % 24
                try:
                    return int(m.group(1)) % 24
                except Exception:
                    return None

            arquivos_filtrados = []
            for p in arquivos_ordenados:
                h = hora_do_arquivo(p)
                if h is None:
                    continue
                if h in horas_incluir:
                    arquivos_filtrados.append(p)

            arquivos = arquivos_filtrados[:50]

        print(f"Arquivos selecionados (ordenados): {arquivos}")

        # preparar filtros de hora
        hora_inicio_obj = parse_time_str(hora_de) if hora_de else None
        hora_fim_obj = parse_time_str(hora_ate) if hora_ate else None

        regex_palavra = None
        if palavra_chave:
            try:
                regex_palavra = re.compile(palavra_chave, re.IGNORECASE)
            except re.error:
                regex_palavra = re.compile(re.escape(palavra_chave), re.IGNORECASE)

        # Calculando paginação (skip/limit)
        indice_inicio = max(0, (pagina - 1) * tamanho_pagina)
        indice_fim = indice_inicio + tamanho_pagina

        print(f"Filtros: ip_nat={ip_nat}, porta_nat={porta_nat}, hora_de={hora_de}, hora_ate={hora_ate}, palavra_chave={palavra_chave}")
        print(f"Paginação: pagina={pagina}, tamanho_pagina={tamanho_pagina}, inicio={indice_inicio}, fim={indice_fim}")

        def stream_logs():
            contador_encontrados = 0

            # Iterando arquivo por arquivo na ordem correta e enviar resultados conforme encontrados
            for arquivo in arquivos:
                print("Lendo arquivo:", arquivo)
                try:
                    with open(arquivo, "r", errors="ignore") as fh:
                        for raw_line in fh:
                            line = raw_line.strip()
                            if not line:
                                continue

                            if regex_palavra and not regex_palavra.search(line):
                                continue

                            parseado = parse_log_line(line)

                            if not parseado:
                                if ip_nat or porta_nat:
                                    continue
                                hora_match = re.search(r"\b(\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?)\b", line)
                                if hora_match:
                                    hora_str = hora_match.group(1)
                                    hora_obj = parse_time_str(hora_str)
                                    if hora_obj:
                                        if hora_inicio_obj and hora_obj < hora_inicio_obj:
                                            continue
                                        if hora_fim_obj and hora_obj > hora_fim_obj:
                                            continue
                                parseado = {"linha": line}
                            else:
                                # filtro por NAT (ip_nat e porta_nat devem bater com parsed["nat"])
                                if ip_nat:
                                    nat_field = parseado.get("nat", "")
                                    nat_ip = nat_field.split(":")[0] if ":" in nat_field else nat_field
                                    if nat_ip != ip_nat:
                                        continue
                                if porta_nat:
                                    nat_field = parseado.get("nat", "")
                                    if ":" in nat_field:
                                        nat_port = nat_field.split(":")[1]
                                        if nat_port != porta_nat:
                                            continue
                                    else:
                                        continue

                                # filtro por hora usando o campo data (se disponível) ou buscando hora na linha
                                hora_obj = None
                                campo_data = parseado.get("data")
                                if campo_data:
                                    hora_match = re.search(r"(\d{2}:\d{2}:\d{2}(?:\.\d+)?)", campo_data)
                                    if hora_match:
                                        hora_obj = parse_time_str(hora_match.group(1))
                                if not hora_obj:
                                    hora_match = re.search(r"\b(\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?)\b", line)
                                    if hora_match:
                                        hora_obj = parse_time_str(hora_match.group(1))

                                if (hora_inicio_obj or hora_fim_obj) and hora_obj:
                                    if hora_inicio_obj and hora_obj < hora_inicio_obj:
                                        continue
                                    if hora_fim_obj and hora_obj > hora_fim_obj:
                                        continue
                                if (hora_inicio_obj or hora_fim_obj) and not hora_obj:
                                    continue

                            # chegou aqui: linha passou em todos os filtros
                            if contador_encontrados >= indice_inicio and contador_encontrados < indice_fim:
                                out_obj = parseado if isinstance(parseado, dict) else {"linha": line}
                                yield json.dumps(out_obj, ensure_ascii=False) + "\n"
                            contador_encontrados += 1

                            if contador_encontrados >= indice_fim:
                                print("Alcançado limite de paginação, finalizando stream.")
                                return

                except Exception as e:
                    print(f"Erro ao ler arquivo {arquivo}: {e}")
                    continue

            print("Fim dos arquivos. Total achados:", contador_encontrados)

        return StreamingResponse(stream_logs(), media_type="application/x-ndjson")

    except subprocess.TimeoutExpired:
        return {"erro": "Processamento demorou demais"}
    except subprocess.CalledProcessError as e:
        return {"erro": f"Erro ao executar script: {str(e)}"}
    except Exception as e:
        return {"erro": str(e)}

# -------------------------------
# LOGS DIRETO DO SSH
# -------------------------------

@app.get("/logs")
def logs(limit: int = 50):

    raw_logs = get_logs(limit)

    linhas = raw_logs.splitlines()

    processados = []

    for line in linhas:
        parsed = parse_log_line(line)
        if parsed:
            processados.append(parsed)

    return {
        "raw_logs": linhas,
        "parsed_logs": processados
    }