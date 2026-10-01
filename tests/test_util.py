"""공용 도우미: 원자적 쓰기가 다른 스레드의 읽기와 겹쳐도 실패하지 않아야 한다 (Windows)."""

import tempfile
import threading
import unittest
from pathlib import Path

from tests.helpers import ROOT  # noqa: F401  (sys.path 준비)
from studio.util import atomic_write_json, read_json


class AtomicWrite(unittest.TestCase):
    def test_replace_waits_for_open_reader(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "T0001.json"
            atomic_write_json(path, {"v": 1})
            # 화면 요청이 파일을 읽고 있는 상황: 열어 둔 채 0.3초 뒤에 닫는다
            handle = open(path, encoding="utf-8")
            timer = threading.Timer(0.3, handle.close)
            timer.start()
            try:
                atomic_write_json(path, {"v": 2})
            finally:
                timer.join()
                handle.close()
            self.assertEqual(read_json(path), {"v": 2})
            self.assertEqual([p.name for p in Path(d).iterdir()], ["T0001.json"], "임시 파일이 남지 않는다")


if __name__ == "__main__":
    unittest.main()
