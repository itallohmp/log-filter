from app.repositories.log_repository import LogRepository
from app.parsers.log_parser import parse_log_line

class LogService:
    def __init__(self, repository: LogRepository):
        self.repository = repository

    def listar_rotas(self):
        rotas = self.repository.list_rotas()
        return {
            "rotas": rotas,
            "count": len(rotas)
        }

    def buscar_logs_recentes(self, limit: int):
        raw = self.repository.get_remote_syslog(limit)

        logs = []
        for line in raw.splitlines():
            parseado = parse_log_line(line)
            if parseado:
                logs.append(parseado)

        return {
            "logs": logs,
            "count": len(logs)
        }

    def buscar_logs_raw(self, limit: int):
        raw = self.repository.get_remote_syslog(limit)
        linhas = raw.splitlines()

        processados = []
        for line in linhas:
            parseado = parse_log_line(line)
            if parseado:
                processados.append(parseado)

        return {
            "raw_logs": linhas,
            "parsed_logs": processados
        }