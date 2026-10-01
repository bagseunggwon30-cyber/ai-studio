"""AI Studio 감독 프로그램.

    python studio.py init       제품 저장소와 첫 작업 준비
    python studio.py serve      대시보드 열기 (http://127.0.0.1:8765)
    python studio.py doctor     도구·로그인 점검
    python studio.py selftest core-courier   신뢰 테스트 자가 점검
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from studio.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
