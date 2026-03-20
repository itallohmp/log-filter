
from fastapi import FastAPI, Query
from fastapi.staticfiles import StaticFiles

from fastapi.middleware.cors import CORSMiddleware


from controllers import router

app = FastAPI(root_path="/api")

BASE_LOGS = "/home/plog/venv/logs"

app.mount("/static", StaticFiles(directory="static"), name="static")


app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


app.include_router(router)
