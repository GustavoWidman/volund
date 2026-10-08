"""Independent exact arithmetic oracle, never linked into a candidate.

Small test answers use a deliberately direct predicate/filter implementation.
Large fixture answers use separately written prefix totals and a segment-tree
range minimum/maximum query, cross-checked against filtering during generation.
"""
from bisect import bisect_left
from collections import defaultdict
import hashlib
import struct

ALL = (1 << 32) - 1
U64 = (1 << 64) - 1
I32_MIN, I32_MAX = -(1 << 31), (1 << 31) - 1
EVENT = struct.Struct('<QIi')
QUERY = struct.Struct('<QQII')
RESULT = struct.Struct('<Qqii')


def aggregate(values):
    return (len(values), sum(values), min(values), max(values)) if values else (0, 0, 0, 0)


def direct(events, queries):
    return [aggregate([v for t, s, v in events if lo <= t < hi and (stream == ALL or s == stream)])
            for lo, hi, stream, reserved in queries]


class RangeTable:
    def __init__(self, pairs):
        pairs = sorted(pairs)
        self.timestamps = [p[0] for p in pairs]
        self.prefix = [0]
        n = len(pairs)
        self.n = n
        self.mins = [I32_MAX] * (2 * n)
        self.maxs = [I32_MIN] * (2 * n)
        for i, (_, value) in enumerate(pairs):
            self.prefix.append(self.prefix[-1] + value)
            self.mins[n + i] = self.maxs[n + i] = value
        for i in range(n - 1, 0, -1):
            self.mins[i] = min(self.mins[2*i], self.mins[2*i+1])
            self.maxs[i] = max(self.maxs[2*i], self.maxs[2*i+1])

    def query(self, lo, hi):
        left = bisect_left(self.timestamps, lo)
        right = bisect_left(self.timestamps, hi)
        count = right - left
        if not count:
            return (0, 0, 0, 0)
        total = self.prefix[right] - self.prefix[left]
        left += self.n
        right += self.n
        minimum, maximum = I32_MAX, I32_MIN
        while left < right:
            if left & 1:
                minimum, maximum = min(minimum, self.mins[left]), max(maximum, self.maxs[left])
                left += 1
            if right & 1:
                right -= 1
                minimum, maximum = min(minimum, self.mins[right]), max(maximum, self.maxs[right])
            left //= 2
            right //= 2
        return (count, total, minimum, maximum)


def indexed(events, queries):
    requested = {q[2] for q in queries}
    pairs = defaultdict(list)
    for timestamp, stream, value in events:
        if stream in requested:
            pairs[stream].append((timestamp, value))
        if ALL in requested:
            pairs[ALL].append((timestamp, value))
    tables = {stream: RangeTable(values) for stream, values in pairs.items()}
    return [tables[stream].query(lo, hi) if stream in tables else (0, 0, 0, 0)
            for lo, hi, stream, reserved in queries]


def encode_input(events, queries):
    return b'RQENG001' + struct.pack('<QQ', len(events), len(queries)) + b''.join(EVENT.pack(*e) for e in events) + b''.join(QUERY.pack(*q) for q in queries)


def decode_input(data):
    if len(data) < 24 or data[:8] != b'RQENG001':
        raise ValueError('invalid input fixture header')
    n, q = struct.unpack_from('<QQ', data, 8)
    if n > 1000000 or q > 4096 or len(data) != 24 + 16*n + 24*q:
        raise ValueError('invalid fixture length/count')
    return ([EVENT.unpack_from(data, 24 + 16*i) for i in range(n)],
            [QUERY.unpack_from(data, 24 + 16*n + 24*i) for i in range(q)])


def encode_expected(results):
    return b'RQOUT001' + struct.pack('<Q', len(results)) + b''.join(RESULT.pack(*r) for r in results)


def decode_expected(data):
    if len(data) < 16 or data[:8] != b'RQOUT001':
        raise ValueError('invalid output fixture header')
    q, = struct.unpack_from('<Q', data, 8)
    if len(data) != 16 + 24*q:
        raise ValueError('invalid output fixture length')
    return [RESULT.unpack_from(data, 16 + 24*i) for i in range(q)]


def sha256(data):
    return hashlib.sha256(data).hexdigest()
