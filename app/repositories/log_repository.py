import os
import glob
import subprocess
import paramiko

from app.core.config import (
    BASE_LOGS,
    SCRIPT_DOWNLOAD,
    SCRIPT_DESCOMPACTA,
    SSH_HOSTNAME,
    SSH_USERNAME,
    SSH_PRIVATE_KEY_PATH,
)

class LogRepository:
    def list_rotas(self) -> list[str]:
        ignorar = {"modulos"}

        return sorted(
            nome
            for nome in os.listdir(BASE_LOGS)
            if os.path.isdir(os.path.join(BASE_LOGS, nome)) and nome not in ignorar
        )

    def get_remote_syslog(self, limit: int = 50) -> str:
        key = paramiko.RSAKey.from_private_key_file(str(SSH_PRIVATE_KEY_PATH))

        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        try:
            ssh.connect(
                hostname=SSH_HOSTNAME,
                username=SSH_USERNAME,
                pkey=key,
                timeout=10
            )

            _, stdout, stderr = ssh.exec_command(f"tail -n {limit} /var/log/syslog")

            out = stdout.read().decode(errors="ignore")
            err = stderr.read().decode(errors="ignore")
            exit_status = stdout.channel.recv_exit_status()

            if exit_status != 0:
                raise RuntimeError(f"Erro no comando remoto: {err.strip()}")

            return out

        finally:
            ssh.close()