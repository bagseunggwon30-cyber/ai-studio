"""Disposable supervisor MVP demo. Uses fake models and a temporary company only."""
from pathlib import Path
import argparse
import hashlib
import json
import shutil
import sys
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from tests.helpers import TempStudio
from studio.server import StudioServer
from studio.supervisor import Supervisor
from studio.util import atomic_write_json


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--port",type=int,default=8797)
    args=parser.parse_args()
    company=TempStudio()
    company.cfg.fake_runtimes=True
    company.engine.set_self_learning(False)
    company.cfg.name = "연습용 · 외부 감독 MVP"
    shutil.copytree(ROOT/"ui",company.root/"ui",ignore=shutil.ignore_patterns(".DS_Store"))
    token="fixture-only-supervisor-demo-"+"x"*32
    atomic_write_json(company.cfg.data_dir/"supervisors.json",{"enabled":True,"clients":[{"id":"demo","enabled":True,"token_sha256":hashlib.sha256(token.encode()).hexdigest(),"projects":{"demo":{"read":True,"write":True,"paths":["docs/**"]}}}]})
    api=Supervisor(company.engine)
    request={"operation":"submit","project":"demo","key":"demo-request","payload":{"title":"외부 감독 요청 · 정답 파일","brief":"docs/answer.txt에 42 저장","requirements":[{"id":"A1","text":"정답 파일과 검사 근거가 있어야 함","evidence":[{"type":"file","path":"docs/answer.txt"},{"type":"test","name":"answer_is_42"}]}]}}
    tid=api.call("Bearer "+token,request)["task"]["id"]
    company.engine._run_build(company.store.get(tid))
    company.engine._current = None
    server=StudioServer(company.cfg,company.store,company.engine,args.port)
    company.store.acquire_process_lock()
    print(json.dumps({"url":f"http://127.0.0.1:{args.port}/#view=board","task":tid,"status":company.store.get(tid).status,"mode":"fake","temporary_root":str(company.root)},ensure_ascii=False),flush=True)
    company.engine.start()
    try:server.serve_forever(poll_interval=.2)
    except KeyboardInterrupt:pass
    finally:
        server.server_close();company.engine.shutdown(None);company.store.release_process_lock();company.close()


if __name__=="__main__":main()
