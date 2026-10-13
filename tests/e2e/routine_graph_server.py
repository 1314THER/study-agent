"""Browser fixture server: temporary ledger and catalogue, no model calls."""
import os
from pathlib import Path
import socket
import sys
import tempfile

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
with tempfile.TemporaryDirectory(prefix='study-graph-browser-') as directory:
    os.environ.update(STUDY_AGENT_DATA_DIR=directory,STUDY_AGENT_JOB_DIR=directory+'/jobs',
                      STUDY_AGENT_LOG_DIR=directory+'/logs',STUDY_AUTH_ENABLED='0',STUDY_LOCAL_CODEX='0')
    from backend.main import app
    from backend import question_pool as pool, routine_review as rr, routine_classification as rc
    from tests.test_routine_review import CONFIG, fake
    import uvicorn
    pool.import_records({'name':'图谱测试原卷','kind':'json','revision':'1'},[
        {'source_key':str(i),'question':f'集合 A={{1,{i+1}}} 的子集有多少个？','solution':'每个元素取或不取。',
         'answer':'4','categories':['集合与逻辑用语'],'completeness':'complete','raw':{}} for i in range(1,32)])
    store=rr.get_store();run=store.create('browser-graph-run',rc.load_catalog(),CONFIG,pool.storage_path())
    rr.execute_run(store,run['run_id'],fake)
    sock=socket.socket();sock.bind(('127.0.0.1',0));sock.listen(128)
    print('GRAPH_PORT='+str(sock.getsockname()[1]),flush=True)
    uvicorn.Server(uvicorn.Config(app,log_level='warning')).run(sockets=[sock])
