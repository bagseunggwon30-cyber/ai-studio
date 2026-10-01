"""QR 코드 만들기 (표준 라이브러리만): 휴대폰 짝짓기 주소를 PC 화면에 QR로 보여 준다.

바이트 모드, 오류 정정 M, 버전 1~10 (바이트 213자까지 — 짝짓기 주소는 100자 안팎). 결과는 SVG 글.
만드는 순서는 ISO/IEC 18004를 따른다: 데이터 비트 → 블록 나누기·리드-솔로몬 → 섞기 → 모듈 배치 → 마스크(벌점이 가장 적은 것) → 형식·버전 정보.
"""

from __future__ import annotations

# 버전별 (전체 코드워드 수, 블록마다 오류 정정 코드워드 수, 블록 수) — 오류 정정 M
_M = {1: (26, 10, 1), 2: (44, 16, 1), 3: (70, 26, 1), 4: (100, 18, 2), 5: (134, 24, 2), 6: (172, 16, 4), 7: (196, 18, 4),
      8: (242, 22, 4), 9: (292, 22, 5), 10: (346, 26, 5)}
_ALIGN = {1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30], 6: [6, 34], 7: [6, 22, 38], 8: [6, 24, 42], 9: [6, 26, 46],
          10: [6, 28, 50]}
_ECL_M = 0  # 형식 정보의 오류 정정 비트 (L=1, M=0, Q=3, H=2)


class QrError(ValueError):
    pass


# ---------------------------------------------------------------- 리드-솔로몬 (GF(256), 원시 다항식 0x11D)
def _gf_mul(x: int, y: int) -> int:
    z = 0
    for i in reversed(range(8)):
        z = (z << 1) ^ ((z >> 7) * 0x11D)
        z ^= ((y >> i) & 1) * x
    return z


def _rs_divisor(degree: int) -> list[int]:
    result = [0] * (degree - 1) + [1]
    root = 1
    for _ in range(degree):
        for j in range(degree):
            result[j] = _gf_mul(result[j], root)
            if j + 1 < degree:
                result[j] ^= result[j + 1]
        root = _gf_mul(root, 0x02)
    return result


def rs_remainder(data: list[int], degree: int) -> list[int]:
    divisor = _rs_divisor(degree)
    result = [0] * degree
    for b in data:
        factor = b ^ result.pop(0)
        result.append(0)
        for i, coef in enumerate(divisor):
            result[i] ^= _gf_mul(coef, factor)
    return result


# ---------------------------------------------------------------- 데이터 → 코드워드
def _data_codewords(data: bytes, version: int) -> list[int]:
    total, ec_len, blocks = _M[version]
    capacity = total - ec_len * blocks  # 데이터 코드워드 수
    bits: list[int] = []

    def put(value: int, n: int) -> None:
        bits.extend((value >> i) & 1 for i in reversed(range(n)))

    put(0b0100, 4)  # 바이트 모드
    put(len(data), 8 if version < 10 else 16)
    for b in data:
        put(b, 8)
    cap_bits = capacity * 8
    if len(bits) > cap_bits:
        raise QrError("글이 너무 길어요.")
    put(0, min(4, cap_bits - len(bits)))  # 끝 표시
    put(0, (-len(bits)) % 8)
    words = [int("".join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8)]
    pad = 0xEC
    while len(words) < capacity:
        words.append(pad)
        pad ^= 0xEC ^ 0x11
    return words


def _interleave(words: list[int], version: int) -> list[int]:
    total, ec_len, nblocks = _M[version]
    short_len = (total // nblocks) - ec_len  # 짧은 블록의 데이터 수 (긴 블록은 하나 더)
    n_short = nblocks - total % nblocks
    blocks, pos = [], 0
    for i in range(nblocks):
        n = short_len + (0 if i < n_short else 1)
        blocks.append(words[pos:pos + n])
        pos += n
    out = [b[i] for i in range(short_len + 1) for b in blocks if i < len(b)]
    ecs = [rs_remainder(b, ec_len) for b in blocks]
    out += [e[i] for i in range(ec_len) for e in ecs]
    return out


# ---------------------------------------------------------------- 모듈 배치
def _format_bits(mask: int) -> int:
    data = _ECL_M << 3 | mask
    rem = data
    for _ in range(10):
        rem = (rem << 1) ^ ((rem >> 9) * 0x537)
    return (data << 10 | rem) ^ 0x5412


def _version_bits(version: int) -> int:
    rem = version
    for _ in range(12):
        rem = (rem << 1) ^ ((rem >> 11) * 0x1F25)
    return version << 12 | rem


class _Grid:
    def __init__(self, version: int):
        self.v = version
        self.n = 17 + 4 * version
        self.dark = [[False] * self.n for _ in range(self.n)]
        self.fixed = [[False] * self.n for _ in range(self.n)]

    def set(self, r: int, c: int, dark: bool) -> None:
        self.dark[r][c] = dark
        self.fixed[r][c] = True

    def functions(self) -> None:
        n = self.n
        for i in range(n):  # 타이밍
            self.set(6, i, i % 2 == 0)
            self.set(i, 6, i % 2 == 0)
        for r0, c0 in ((0, 0), (0, n - 7), (n - 7, 0)):  # 찾기 패턴 + 구분선
            for dr in range(-1, 8):
                for dc in range(-1, 8):
                    r, c = r0 + dr, c0 + dc
                    if 0 <= r < n and 0 <= c < n:
                        d = max(abs(dr - 3), abs(dc - 3))
                        self.set(r, c, d != 2 and d != 4)
        pos = _ALIGN[self.v]
        for r in pos:  # 정렬 패턴 (찾기 패턴과 겹치는 세 곳은 빼고)
            for c in pos:
                if (r, c) in ((6, 6), (6, pos[-1]), (pos[-1], 6)):
                    continue
                for dr in range(-2, 3):
                    for dc in range(-2, 3):
                        self.set(r + dr, c + dc, max(abs(dr), abs(dc)) != 1)
        self.format(0)  # 자리만 잡아 둔다 (마스크를 고른 뒤 다시 쓴다)
        if self.v >= 7:
            bits = _version_bits(self.v)
            for i in range(18):
                bit = (bits >> i) & 1 == 1
                a, b = n - 11 + i % 3, i // 3
                self.set(b, a, bit)  # 오른쪽 위
                self.set(a, b, bit)  # 왼쪽 아래

    def format(self, mask: int) -> None:
        n, bits = self.n, _format_bits(mask)

        def bit(i: int) -> bool:
            return (bits >> i) & 1 == 1

        for i in range(6):
            self.set(i, 8, bit(i))
        self.set(7, 8, bit(6))
        self.set(8, 8, bit(7))
        self.set(8, 7, bit(8))
        for i in range(9, 15):
            self.set(8, 14 - i, bit(i))
        for i in range(8):
            self.set(8, n - 1 - i, bit(i))
        for i in range(8, 15):
            self.set(n - 15 + i, 8, bit(i))
        self.set(n - 8, 8, True)  # 늘 어두운 칸

    def place(self, codewords: list[int]) -> None:
        n, i, total = self.n, 0, len(codewords) * 8
        right = n - 1
        while right >= 1:
            if right == 6:
                right = 5
            upward = ((right + 1) & 2) == 0
            for vert in range(n):
                r = n - 1 - vert if upward else vert
                for j in range(2):
                    c = right - j
                    if not self.fixed[r][c] and i < total:
                        self.dark[r][c] = (codewords[i >> 3] >> (7 - (i & 7))) & 1 == 1
                        i += 1
            right -= 2

    def masked(self, mask: int) -> list[list[bool]]:
        rule = [lambda r, c: (r + c) % 2 == 0, lambda r, c: r % 2 == 0, lambda r, c: c % 3 == 0, lambda r, c: (r + c) % 3 == 0,
                lambda r, c: (r // 2 + c // 3) % 2 == 0, lambda r, c: r * c % 2 + r * c % 3 == 0,
                lambda r, c: (r * c % 2 + r * c % 3) % 2 == 0, lambda r, c: ((r + c) % 2 + r * c % 3) % 2 == 0][mask]
        return [[self.dark[r][c] ^ (not self.fixed[r][c] and rule(r, c)) for c in range(self.n)] for r in range(self.n)]


def _penalty(m: list[list[bool]]) -> int:
    n, score = len(m), 0
    lines = m + [list(col) for col in zip(*m)]
    finder_a = [True, False, True, True, True, False, True, False, False, False, False]
    finder_b = finder_a[::-1]
    for line in lines:
        run, prev = 0, None
        for x in line:  # 규칙 1: 같은 색이 5칸 넘게 이어짐
            run = run + 1 if x == prev else 1
            prev = x
            if run == 5:
                score += 3
            elif run > 5:
                score += 1
        for i in range(n - 10):  # 규칙 3: 찾기 패턴처럼 보이는 줄
            seg = line[i:i + 11]
            if seg == finder_a or seg == finder_b:
                score += 40
    for r in range(n - 1):  # 규칙 2: 2x2 같은 색
        for c in range(n - 1):
            if m[r][c] == m[r][c + 1] == m[r + 1][c] == m[r + 1][c + 1]:
                score += 3
    dark = sum(map(sum, m))  # 규칙 4: 어두운 칸 비율
    total = n * n
    score += ((abs(dark * 20 - total * 10) + total - 1) // total - 1) * 10
    return score


def matrix(text: str) -> list[list[bool]]:
    data = text.encode("utf-8")
    version = next((v for v in _M if len(data) + (2 if v < 10 else 3) <= _M[v][0] - _M[v][1] * _M[v][2]), None)
    if version is None:
        raise QrError("글이 너무 길어요 (213바이트까지).")
    grid = _Grid(version)
    grid.functions()
    grid.place(_interleave(_data_codewords(data, version), version))
    best, best_score = None, None
    for mask in range(8):
        grid.format(mask)
        m = grid.masked(mask)
        s = _penalty(m)
        if best_score is None or s < best_score:
            best, best_score = m, s
    return best  # type: ignore[return-value]


def svg(text: str, border: int = 4) -> str:
    m = matrix(text)
    n = len(m) + border * 2
    path = "".join(f"M{c + border},{r + border}h1v1h-1z" for r, row in enumerate(m) for c, d in enumerate(row) if d)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {n} {n}" shape-rendering="crispEdges">'
            f'<rect width="{n}" height="{n}" fill="#fff"/><path d="{path}" fill="#000"/></svg>')
