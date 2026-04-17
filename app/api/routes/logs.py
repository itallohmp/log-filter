from fastapi import APIRouter, Query, HTTPException
from fastapi.responses import FileResponse

from app.services.log_service import LogService
from app.repositories.log_repository import LogRepository

router = APIRouter()
service = LogService(LogRepository())

@router.get("/health")
def health():
    return {"status": "ok"}

@router.get("/")
def root():
    return FileResponse("static/index.html")

@router.get("/rotas")
def listar_rotas():
    try:
        return service.listar_rotas()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/logs")
def get_logs(limit: int = Query(50, ge=1, le=1000)):
    try:
        return service.buscar_logs_recentes(limit)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))

@router.get("/logs/raw")
def logs_raw(limit: int = Query(50, ge=1, le=1000)):
    try:
        return service.buscar_logs_raw(limit)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))