from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse, StreamingResponse

import glob
import json
import os
import re
import subprocess

from datetime import datetime
from typing import Optional

from main import (
    BASE_LOGS,
    SCRIPT_DOWNLOAD,
    SCRIPT_DESCOMPACTA,
    parse_log_line,
    parse_time_str,
)

router = APIRouter()


@router.get("/logs/filter")
def filter_logs(
    ip_rota: str = Query(..., description="Nome da pasta da rota"),
    ip_nat: Optional[str] = Query(None),
    porta_nat: Optional[str] = Query(None),
    ano: Optional[str] = Query(None),
    mes: Optional[str] = Query(None),
    dia: Optional[str] = Query(None),
    hora_de: Optional[str] = Query(None),
    hora_ate: Optional[str] = Query(None),
    palavra_chave: Optional[str] = Query(None),
    pagina: int = Query(1, ge=1),
    tamanho_pagina: int = Query(100, ge=1, le=1000)
):
    now = datetime.now()
    ano = ano or f"{now.year}"
    mes = (mes or f"{now.month}").zfill(2)
    dia = (dia or f"{now.day}").zfill(2)

    if "/" in ip_rota or "\\" in ip_rota or ".." in ip_rota:
        return JSONResponse({"erro": "Nome de rota inválido."}, status_code=400)

    pasta_rota = os.path.join(BASE_LOGS, ip_rota)

    if not os.path.isdir(pasta_rota):
        return JSONResponse(
            {"erro": f"A pasta da rota '{ip_rota}' não existe."},
            status_code=404
        )

    caminho = os.path.join(pasta_rota, ano, mes, dia)

    try:
        print("Buscando logs em:", caminho)

        arquivos_bz = glob.glob(os.path.join(caminho, "*.bz"))
        arquivos_log = glob.glob(os.path.join(caminho, "*.log"))

        if not arquivos_bz and not arquivos_log:
            print("Logs não encontrados localmente, executando script de download...")

            proc = subprocess.run(
                ["bash", SCRIPT_DOWNLOAD, ip_rota, ano, mes, dia],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=300,
                text=True,
                env=os.environ.copy()
            )

            print("download returncode:", proc.returncode)
            print("download stderr:", proc.stderr)

            arquivos_bz = glob.glob(os.path.join(caminho, "*.bz"))
            arquivos_log = glob.glob(os.path.join(caminho, "*.log"))

            if not arquivos_bz and not arquivos_log:
                return JSONResponse(
                    {
                        "erro": "Nenhum log encontrado após tentativa de download",
                        "detalhes": proc.stderr.strip()
                    },
                    status_code=404
                )

        if arquivos_bz and not arquivos_log:
            print("Descompactando arquivos .bz...")

            proc2 = subprocess.run(
                ["bash", SCRIPT_DESCOMPACTA, ip_rota, ano, mes, dia],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=300,
                text=True,
                env=os.environ.copy()
            )

            print("descompacta returncode:", proc2.returncode)
            print("descompacta stderr:", proc2.stderr)

            arquivos_log = glob.glob(os.path.join(caminho, "*.log"))

            if not arquivos_log:
                return JSONResponse(
                    {
                        "erro": "Nenhum .log após descompactar",
                        "detalhes": proc2.stderr.strip()
                    },
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

        print(
            f"Filtros: ip_nat={ip_nat}, porta_nat={porta_nat}, "
            f"hora_de={hora_de}, hora_ate={hora_ate}, palavra_chave={palavra_chave}"
        )
        print(
            f"Paginação: pagina={pagina}, tamanho_pagina={tamanho_pagina}, "
            f"inicio={indice_inicio}, fim={indice_fim}"
        )

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

                                hora_match = re.search(
                                    r"\b(\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?)\b",
                                    line
                                )
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
                                    hora_match = re.search(
                                        r"(\d{2}:\d{2}:\d{2}(?:\.\d+)?)",
                                        campo_data
                                    )
                                    if hora_match:
                                        hora_obj = parse_time_str(hora_match.group(1))

                                if not hora_obj:
                                    hora_match = re.search(
                                        r"\b(\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?)\b",
                                        line
                                    )
                                    if hora_match:
                                        hora_obj = parse_time_str(hora_match.group(1))

                                if (hora_inicio_obj or hora_fim_obj) and hora_obj:
                                    if hora_inicio_obj and hora_obj < hora_inicio_obj:
                                        continue
                                    if hora_fim_obj and hora_obj > hora_fim_obj:
                                        continue

                                if (hora_inicio_obj or hora_fim_obj) and not hora_obj:
                                    continue

                            if indice_inicio <= contador_encontrados < indice_fim:
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

        return StreamingResponse(
            stream_logs(),
            media_type="application/x-ndjson"
        )

    except subprocess.TimeoutExpired:
        return JSONResponse({"erro": "Processamento demorou demais"}, status_code=504)
    except Exception as e:
        return JSONResponse({"erro": str(e)}, status_code=500)