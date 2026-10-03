"""Run only after the owner approves the exact Soyun project scope."""
from pathlib import Path
import argparse
import json
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from studio.config import load_config
from studio.supervisor_setup import default_paths, provision


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--owner-approved",action="store_true")
    parser.add_argument("--port",type=int)
    args=parser.parse_args()
    if not args.owner_approved:parser.error("소윤이 연결 토큰과 프로젝트 범위에 대한 CEO 승인이 필요합니다.")
    config,credential=default_paths()
    port=args.port or load_config(ROOT).port
    print(json.dumps(provision(ROOT,config,credential,port),ensure_ascii=False))


if __name__ == "__main__":main()
