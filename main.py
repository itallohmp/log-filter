# main.py
from fastapi import FastAPI, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware

import paramiko
import json, re, glob, os, subprocess
from datetime import datetime, time
from typing import Optional, Dict

app = FastAPI(root_path="/api")

# Servir estáticos localmente em dev
app.mount("/static", StaticFiles(directory="static"), name="static")

# CORS: ajuste as origins conforme seu frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

@app.get("/health")
def health():
    return JSONResponse({"status": "ok"})

# opcional em dev: servir index localmente
@app.get("/")
def root():
    return FileResponse("static/index.html")


# -------------------------------
# SSH LOG FETCH
# -------------------------------
def get_logs(limit: int = 50) -> str:
    hostname = "10.10.10.208"
    username = "plog"
    private_key_path = "/home/plog/.ssh/id_rsa"

    try:
        key = paramiko.RSAKey.from_private_key_file(private_key_path)
    except Exception as e:
        raise RuntimeError(f"Erro ao carregar chave privada: {e}")

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        ssh.connect(hostname=hostname, username=username, pkey=key, timeout=10)
        stdin, stdout, stderr = ssh.exec_command(f"tail -n {limit} /var/log/syslog")
        out = stdout.read().decode(errors="ignore")
        err = stderr.read().decode(errors="ignore")
        # aguarda código de saída do comando (não bloqueia se já finalizou)
        try:
            exit_status = stdout.channel.recv_exit_status()
        except Exception:
            exit_status = None

        if exit_status is not None and exit_status != 0:
            raise RuntimeError(f"Comando remoto retornou exit code {exit_status}: {err.strip()}")
        if err and not out:
            # caso haja stderr mas sem saída, reportar
            raise RuntimeError(f"Erro ao executar comando remoto: {err.strip()}")

        return out
    finally:
        try:
            ssh.close()
        except Exception:
            pass

# -------------------------------
# PARSE LOG
# -------------------------------
pattern = re.compile(
    r"\*(\w+\s+\d+\s+\d+:\d+:\d+\.\d+).*?"
    r"Created Translation\s+"
    r"(UDP|TCP)\s+"
    r"(\d+\.\d+\.\d+\.\d+:\d+)\s+"
    r"(\d+\.\d+\.\d+\.\d+:\d+)\s+"
    r"(\d+\.\d+\.\d+\.\d+:\d+)\s+"
    r"(\d+\.\d+\.\d+\.\d+:\d+)\s+"
    r"\d+"
)

def parse_log_line(line: str) -> Optional[Dict]:
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
def parse_time_str(h: Optional[str]) -> Optional[time]:
    if not h:
        return None
    for fmt in ("%H:%M", "%H:%M:%S", "%H:%M:%S.%f"):
        try:
            return datetime.strptime(h, fmt).time()
        except Exception:
            continue
    return None

# -------------------------------
# API: retornar logs parseados (SSH)
# -------------------------------
@app.get("/api/logs")
def api_get_logs(limit: int = Query(50, ge=1, le=1000)) -> JSONResponse:
    try:
        raw = get_logs(limit)
    except RuntimeError as e:
        return JSONResponse({"erro": str(e)}, status_code=502)
    parsed = []
    for line in raw.splitlines():
        p = parse_log_line(line)
        if p:
            parsed.append(p)
    return JSONResponse({"logs": parsed, "count": len(parsed)})

# -------------------------------
# LOGS DIRETO DO SSH (rota legacy)
# -------------------------------
@app.get("/logs")
def logs(limit: int = 50):
    try:
        raw_logs = get_logs(limit)
    except RuntimeError as e:
        return JSONResponse({"erro": str(e)}, status_code=502)
    linhas = raw_logs.splitlines()
    processados = []
    for line in linhas:
        parsed = parse_log_line(line)
        if parsed:
            processados.append(parsed)
    return {"raw_logs": linhas, "parsed_logs": processados}

# -------------------------------
# FILTRO DE LOGS (STREAMING NDJSON)
# -------------------------------
@app.get("/logs/filter")
def filter_logs(
    ip_rota: str = "172.16.10.1",
    ip_nat: Optional[str] = None,
    porta_nat: Optional[str] = None,
    ano: Optional[str] = None,
    mes: Optional[str] = None,
    dia: Optional[str] = None,
    hora_de: Optional[str] = None,
    hora_ate: Optional[str] = None,
    palavra_chave: Optional[str] = None,
    pagina: int = 1,
    tamanho_pagina: int = 100
):
    script_download = "/home/plog/venv/logs/modulos/script-download-logs.sh"
    script_descompacta = "/home/plog/venv/logs/modulos/script-descompacta-log.sh"

    now = datetime.now()
    ano = ano or f"{now.year}"
    mes = (mes or f"{now.month}").zfill(2)
    dia = (dia or f"{now.day}").zfill(2)

    caminho = f"/home/plog/venv/logs/{ip_rota}/{ano}/{mes}/{dia}"
    os.makedirs(caminho, exist_ok=True)

    try:
        print("Buscando logs em:", caminho)

        arquivos_bz = glob.glob(f"{caminho}/*.bz")
        arquivos_log = glob.glob(f"{caminho}/*.log")

        # tenta download se não houver arquivos locais
        if not arquivos_bz and not arquivos_log:
            print("Logs não encontrados localmente, executando script de download...")
            proc = subprocess.run(
                ["bash", script_download, ip_rota, ano, mes, dia],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=300,
                text=True,
                env=os.environ.copy()
            )
            print("download returncode:", proc.returncode)
            print("download stderr:", proc.stderr)
            arquivos_bz = glob.glob(f"{caminho}/*.bz")
            arquivos_log = glob.glob(f"{caminho}/*.log")

            if not arquivos_bz and not arquivos_log:
                return JSONResponse(
                    {"erro": "Nenhum log encontrado após tentativa de download", "detalhes": proc.stderr.strip()},
                    status_code=404
                )

        # se houver .bz, tenta descompactar
        if arquivos_bz and not arquivos_log:
            print("Descompactando arquivos .bz...")
            proc2 = subprocess.run(
                ["bash", script_descompacta, ip_rota, ano, mes, dia],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=300,
                text=True,
                env=os.environ.copy()
            )
            print("descompacta returncode:", proc2.returncode)
            print("descompacta stderr:", proc2.stderr)
            arquivos_log = glob.glob(f"{caminho}/*.log")

            if not arquivos_log:
                return JSONResponse(
                    {"erro": "Nenhum .log após descompactar", "detalhes": proc2.stderr.strip()},
                    status_code=404
                )

        if not arquivos_log:
            return JSONResponse({"erro": "Nenhum log disponível"}, status_code=404)

        def chave_ordenacao_numerica(p):
            nome = os.path.basename(p)
            nums = re.findall(r"(\d+)", nome)
            if not nums:
                return nome
            return int(nums[-1])

        arquivos_ordenados = sorted(arquivos_log, key=chave_ordenacao_numerica)

        # filtra por hora com wrap-around
        if not hora_de and not hora_ate:
            arquivos = arquivos_ordenados[:50]
        else:
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

        hora_inicio_obj = parse_time_str(hora_de) if hora_de else None
        hora_fim_obj = parse_time_str(hora_ate) if hora_ate else None

        regex_palavra = None
        if palavra_chave:
            try:
                regex_palavra = re.compile(palavra_chave, re.IGNORECASE)
            except re.error:
                regex_palavra = re.compile(re.escape(palavra_chave), re.IGNORECASE)

        indice_inicio = max(0, (pagina - 1) * tamanho_pagina)
        indice_fim = indice_inicio + tamanho_pagina

        print(f"Filtros: ip_nat={ip_nat}, porta_nat={porta_nat}, hora_de={hora_de}, hora_ate={hora_ate}, palavra_chave={palavra_chave}")
        print(f"Paginação: pagina={pagina}, tamanho_pagina={tamanho_pagina}, inicio={indice_inicio}, fim={indice_fim}")

        def stream_logs():
            contador_encontrados = 0
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
        return JSONResponse({"erro": "Processamento demorou demais"}, status_code=504)
    except Exception as e:
        return JSONResponse({"erro": str(e)}, status_code=500)

# -------------------------------
# LOGS DIRETO DO SSH (rota legacy)
# -------------------------------
def get_logs(limit: int = 50) -> str:
    import paramiko
    hostname = "10.10.10.208"
    username = "plog"
    private_key_path = "/home/plog/.ssh/id_rsa"

    try:
        key = paramiko.RSAKey.from_private_key_file(private_key_path)
    except Exception as e:
        raise RuntimeError(f"Erro ao carregar chave privada: {e}")

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        ssh.connect(hostname=hostname, username=username, pkey=key, timeout=10)
        stdin, stdout, stderr = ssh.exec_command(f"tail -n {limit} /var/log/syslog")
        out = stdout.read().decode(errors="ignore")
        err = stderr.read().decode(errors="ignore")
        try:
            exit_status = stdout.channel.recv_exit_status()
        except Exception:
            exit_status = None

        if exit_status is not None and exit_status != 0:
            raise RuntimeError(f"Comando remoto retornou exit code {exit_status}: {err.strip()}")
        if err and not out:
            raise RuntimeError(f"Erro ao executar comando remoto: {err.strip()}")

        return out
    finally:
        try:
            ssh.close()
        except Exception:
            pass

@app.get("/logs")
def logs(limit: int = 50):
    try:
        raw_logs = get_logs(limit)
    except RuntimeError as e:
        return JSONResponse({"erro": str(e)}, status_code=502)

    linhas = raw_logs.splitlines()
    processados = []
    for line in linhas:
        parsed = parse_log_line(line)
        if parsed:
            processados.append(parsed)
    return {"raw_logs": linhas, "parsed_logs": processados}
