"""QR 코드 (휴대폰 짝짓기): 리드-솔로몬·형식·버전 정보가 표준 값과 같은지, 모양이 맞는지."""

import unittest

from studio import qr


class Qr(unittest.TestCase):
    def test_reed_solomon_matches_the_standard_example(self):
        # 'HELLO WORLD' 1-M (표준 해설서의 예)
        data = [32, 91, 11, 120, 209, 114, 220, 77, 67, 64, 236, 17, 236, 17, 236, 17]
        self.assertEqual(qr.rs_remainder(data, 10), [196, 35, 39, 119, 235, 215, 231, 226, 93, 23])

    def test_format_and_version_bits(self):
        self.assertEqual(format(qr._format_bits(0), "015b"), "101010000010010")  # M, 마스크 0
        self.assertEqual(format(qr._format_bits(1), "015b"), "101000100100101")  # M, 마스크 1
        self.assertEqual(format(qr._format_bits(4), "015b"), "100010111111001")  # M, 마스크 4
        self.assertEqual(qr._version_bits(7), 0x07C94)

    def test_matrix_shape_and_function_patterns(self):
        url = "http://192.168.0.10:8766/m#pair=ABCD-EFGH"
        m = qr.matrix(url)
        n = len(m)
        self.assertEqual(n, 17 + 4 * 3)  # 41바이트 → 버전 3 (M은 42바이트까지)
        for r0, c0 in ((0, 0), (0, n - 7), (n - 7, 0)):  # 찾기 패턴 7x7: 테두리·가운데 3x3 어둡고 그 사이 밝음
            self.assertTrue(all(m[r0][c0 + i] and m[r0 + 6][c0 + i] for i in range(7)))
            self.assertFalse(m[r0 + 1][c0 + 1])
            self.assertTrue(m[r0 + 3][c0 + 3])
        self.assertEqual([m[6][c] for c in range(8, n - 8)], [c % 2 == 0 for c in range(8, n - 8)])  # 타이밍
        self.assertTrue(m[n - 8][8])  # 늘 어두운 칸
        # 형식 정보 두 벌이 같다
        first = [m[i][8] for i in range(6)] + [m[7][8], m[8][8], m[8][7]] + [m[8][14 - i] for i in range(9, 15)]
        second = [m[8][n - 1 - i] for i in range(8)] + [m[n - 15 + i][8] for i in range(8, 15)]
        self.assertEqual(first, second)
        self.assertIn(int("".join("1" if b else "0" for b in reversed(first)), 2), [qr._format_bits(k) for k in range(8)])
        long_url = "https://desktop-abc123.tail1a2b3c.ts.net/m#pair=" + "X" * 120
        self.assertEqual(len(qr.matrix(long_url)), 17 + 4 * 9)  # 168바이트 → 버전 9 (버전 정보가 붙는다)
        with self.assertRaises(qr.QrError):
            qr.matrix("x" * 300)

    def test_reads_back(self):
        """표준 순서를 거꾸로 따라 읽는다: 형식 정보 → 마스크 벗기기 → 코드워드 읽기 → 블록 풀기 → 리드-솔로몬 확인 → 글."""
        for text in ("http://192.168.0.10:8766/m#pair=ABCD-EFGH", "https://pc.tail1a2b3c.ts.net/m#pair=" + "가나다" * 10, "y" * 150, "x"):
            m = qr.matrix(text)
            n = len(m)
            version = (n - 17) // 4
            fmt = [m[i][8] for i in range(6)] + [m[7][8], m[8][8], m[8][7]] + [m[8][14 - i] for i in range(9, 15)]
            bits = sum(1 << i for i, b in enumerate(fmt) if b)
            mask = next(k for k in range(8) if qr._format_bits(k) == bits)
            grid = qr._Grid(version)
            grid.functions()  # 어느 칸이 기능 칸인지만 쓴다
            rule = qr._Grid(version)
            rule.functions()
            flip = rule.masked(mask)  # 데이터 칸이 모두 밝은 격자에 마스크를 씌우면 뒤집히는 칸만 어둡다
            unmasked = [[m[r][c] ^ (not grid.fixed[r][c] and flip[r][c]) for c in range(n)] for r in range(n)]
            stream = []
            right = n - 1
            while right >= 1:
                if right == 6:
                    right = 5
                upward = ((right + 1) & 2) == 0
                for vert in range(n):
                    r = n - 1 - vert if upward else vert
                    for j in range(2):
                        c = right - j
                        if not grid.fixed[r][c]:
                            stream.append(unmasked[r][c])
                right -= 2
            total, ec_len, nblocks = qr._M[version]
            words = [int("".join("1" if b else "0" for b in stream[i * 8:i * 8 + 8]), 2) for i in range(total)]
            short = total // nblocks - ec_len
            n_short = nblocks - total % nblocks
            sizes = [short + (0 if i < n_short else 1) for i in range(nblocks)]
            blocks = [[] for _ in range(nblocks)]
            k = 0
            for i in range(short + 1):
                for b in range(nblocks):
                    if i < sizes[b]:
                        blocks[b].append(words[k])
                        k += 1
            ecs = [[] for _ in range(nblocks)]
            for i in range(ec_len):
                for b in range(nblocks):
                    ecs[b].append(words[k])
                    k += 1
            for b in range(nblocks):
                self.assertEqual(qr.rs_remainder(blocks[b], ec_len), ecs[b])
            data = [x for blk in blocks for x in blk]
            bitstr = "".join(format(x, "08b") for x in data)
            self.assertEqual(bitstr[:4], "0100")
            count_len = 8 if version < 10 else 16
            count = int(bitstr[4:4 + count_len], 2)
            raw = bytes(int(bitstr[4 + count_len + i * 8:4 + count_len + i * 8 + 8], 2) for i in range(count))
            self.assertEqual(raw.decode("utf-8"), text)

    def test_svg(self):
        text = qr.svg("hi")
        self.assertTrue(text.startswith('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 29 29"'))
        self.assertIn('fill="#000"', text)


if __name__ == "__main__":
    unittest.main()
