from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import paramiko
import subprocess
import re
import glob
import os

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
# FILTRO DE LOGS
# -------------------------------

@app.get("/logs/filter")
def filter_logs(
    router_ip: str = "172.16.10.1",
    client_ip: str | None = None,
    porta: str | None = None,
    data: str | None = None,
    year: str = "2026",
    month: str = "03",
    day: str = "11",
    keyword: str | None = None,
    limit: int = 50
):
    script_download = "/home/plog/venv/logs/modulos/script-download-logs.sh"
    script_descompacta = "/home/plog/venv/logs/modulos/script-descompacta-log.sh"

    path = f"/home/plog/venv/logs/{router_ip}/{year}/{month}/{day}"

    try:
        print("Buscando logs em:", path)

        arquivos_bz = glob.glob(f"{path}/*.bz")
        arquivos_log = glob.glob(f"{path}/*.log")

        # Se não tiver nenhum log, tenta baixar
        if not arquivos_bz and not arquivos_log:
            print("Logs não encontrados, baixando...")
            subprocess.run(
                ["bash", script_download, router_ip, year, month, day],
                check=True,
                timeout=120
            )
            arquivos_bz = glob.glob(f"{path}/*.bz")
            arquivos_log = glob.glob(f"{path}/*.log")

        if not arquivos_bz and not arquivos_log:
            return {"erro": "Nenhum log encontrado"}

        # Se só existir .bz, descompacta e atualiza lista de .log
        if arquivos_bz and not arquivos_log:
            print("Descompactando arquivos .bz...")
            subprocess.run(
                ["bash", script_descompacta, router_ip, year, month, day],
                check=True,
                timeout=120
            )
            arquivos_log = glob.glob(f"{path}/*.log")

        if not arquivos_log:
            return {"erro": "Nenhum log encontrado após descompactar"}

        # -----------------------------
        # Raciocínio do .log: sempre grep
        # -----------------------------
        print("Usando logs descompactados (.log)")
        arquivos = arquivos_log[:50]
        arquivos_str = " ".join(arquivos)

        if keyword:
            cmd = f"grep '{keyword}' {arquivos_str} | tail -n {limit}"
        else:
            cmd = f"tail -n {limit} {arquivos_str}"

        print("Executando:", cmd)

        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30
        )

        linhas = result.stdout.splitlines()
        processados = []

        for line in linhas:
            if client_ip and client_ip not in line:
                continue
            if porta and f":{porta}" not in line:
                continue
            if data and data not in line:
                continue

            parsed = parse_log_line(line)
            if parsed:
                processados.append(parsed)
            else:
                processados.append({"linha": line})

        return {
            "logs": processados,
            "raw_logs": linhas
        }

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