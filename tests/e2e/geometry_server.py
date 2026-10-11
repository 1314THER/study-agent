"""Private temporary server for the geometry browser test. Never uses live data."""
import os
from pathlib import Path
import socket
import sys
import tempfile

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
with tempfile.TemporaryDirectory(prefix="study-geometry-browser-") as directory:
    os.environ.update(STUDY_AGENT_DATA_DIR=directory,STUDY_AGENT_JOB_DIR=directory+"/jobs",
                      STUDY_AGENT_LOG_DIR=directory+"/logs",STUDY_AUTH_ENABLED="0")
    from backend.main import app
    from backend import database, teach, solver
    from tests.geometry_cases import corpus_ellipse, corpus_pyramid, construction_case, prepared
    from fastapi.responses import HTMLResponse
    import uvicorn
    database.init_db()
    fixtures={}
    for name,factory in (("ellipse",corpus_ellipse),("pyramid",corpus_pyramid),
                         ("fold",lambda:construction_case("fold")),("section",lambda:construction_case("section")),
                         ("locus",lambda:construction_case("locus"))):
        question,answer=prepared(factory);database.save_question(question,answer)
        fixtures[name]={"question":question,"answer":answer}
    def offline_checker(*args,**kwargs):
        return '{"is_correct":true,"feedback":"本步正确，进入下一步。"}',{}
    def no_model(*args,**kwargs):
        raise AssertionError("Browser test attempted a paid model call")
    teach.call_deepseek=offline_checker
    solver.call_deepseek=no_model
    # Add routes before the application's catch-all static mount.
    from fastapi import APIRouter
    router=APIRouter()
    @router.get("/__geometry-fixtures")
    def fixture_data():return fixtures
    @router.get("/__geometry-smoke.html",response_class=HTMLResponse)
    def test_page():
        return """<!doctype html><html lang="zh"><head><meta name="viewport" content="width=device-width,initial-scale=1"><script src="/geometry.js"></script><link rel="stylesheet" href="/geometry.css"></head><body><main id="result" style="max-width:700px;margin:auto"></main></body></html>"""
    static=app.router.routes.pop();app.include_router(router);app.router.routes.append(static)
    sock=socket.socket();sock.bind(("127.0.0.1",0));sock.listen(128)
    print("GEOMETRY_PORT="+str(sock.getsockname()[1]),flush=True)
    uvicorn.Server(uvicorn.Config(app,log_level="warning")).run(sockets=[sock])
