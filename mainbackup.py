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