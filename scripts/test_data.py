# -*- coding: utf-8 -*-
"""docs/data.json の不変条件テスト（Python標準ライブラリのみ）

ダイヤ改正で数値が変わっても壊れない「構造・整合性」の検査に限定する。
使い方: python scripts/test_data.py
"""
import json
import unittest
from pathlib import Path

DATA = json.load(open(Path(__file__).resolve().parent.parent / "docs" / "data.json",
                      encoding="utf-8"))


def find_trips(from_name, to_name, cls):
    """アプリの findTrips 相当（乗降制限・循環対応の再現）"""
    gidx = {g[0]: i for i, g in enumerate(DATA["g"])}
    fa = {si for si, s in enumerate(DATA["s"]) if s[0] == gidx[from_name]}
    ta = {si for si, s in enumerate(DATA["s"]) if s[0] == gidx[to_name]}
    out = []
    for tr in DATA["t"]:
        if tr[0] != cls:
            continue
        flat = tr[3]
        no_pu, no_do = set(), set()
        if len(tr) > 6:
            for v in tr[6]:
                (no_do if v & 1 else no_pu).add(v >> 1)
        pend = None
        for k in range(0, len(flat), 3):
            p = k // 3
            si, dep, dd = flat[k], flat[k + 1], flat[k + 2]
            if si in fa and p not in no_pu:
                pend = dep
            elif pend is not None and si in ta and p not in no_do:
                out.append((pend, dep - dd))
                pend = None
    return out


class TestDataJson(unittest.TestCase):
    def test_schema(self):
        for key in ("v", "ex", "exs", "hd", "op", "g", "s", "b", "h", "sv", "t"):
            self.assertIn(key, DATA)
        self.assertEqual(len(DATA["exs"]), len(DATA["op"]))
        for tr in DATA["t"]:
            self.assertIn(len(tr), (6, 7))

    def test_scale(self):
        """規模の下限（大量欠落の検知。改正で多少変動しても壊れない緩い値）"""
        self.assertGreater(len(DATA["g"]), 300)
        self.assertGreater(len(DATA["s"]), 600)
        self.assertGreater(len(DATA["t"]), 2000)

    def test_indices_valid(self):
        ns, nb, nh, nsv, nop = (len(DATA["s"]), len(DATA["b"]), len(DATA["h"]),
                                len(DATA["sv"]), len(DATA["op"]))
        ng = len(DATA["g"])
        for s in DATA["s"]:
            self.assertLess(s[0], ng)
        for tr in DATA["t"]:
            self.assertIn(tr[0], (0, 1, 2))
            self.assertLess(tr[1], nb)
            self.assertLess(tr[2], nh)
            self.assertLess(tr[4], nop)
            self.assertLess(tr[5], nsv)
            flat = tr[3]
            self.assertEqual(len(flat) % 3, 0)
            for k in range(0, len(flat), 3):
                self.assertLess(flat[k], ns)
            if len(tr) > 6:
                nstop = len(flat) // 3
                for v in tr[6]:
                    self.assertLess(v >> 1, nstop)

    def test_departure_monotonic(self):
        """便内の出発時刻は停車順に単調非減少（時刻の壊れ・分数化ミス検知）"""
        for tr in DATA["t"]:
            flat = tr[3]
            deps = [flat[k + 1] for k in range(0, len(flat), 3)]
            self.assertEqual(deps, sorted(deps), f"時刻が逆行: {deps[:6]}...")

    def test_holiday_map(self):
        for date, cls in DATA["hd"].items():
            self.assertRegex(date, r"^\d{8}$")
            self.assertIn(cls, (0, 1, 2))

    def test_known_pair(self):
        """主要区間（中心街→八戸駅）が3ダイヤすべてで検索できる"""
        for cls in (0, 1, 2):
            trips = find_trips("八戸中心街ターミナル（六日町）", "八戸駅", cls)
            self.assertGreater(len(trips), 0, f"区分{cls}で0便")
            for dep, arr in trips:
                self.assertGreaterEqual(arr, dep)

    def test_classes_populated(self):
        from collections import Counter
        c = Counter(tr[0] for tr in DATA["t"])
        for cls in (0, 1, 2):
            self.assertGreater(c[cls], 300, f"区分{cls}の便数が少なすぎる")


if __name__ == "__main__":
    unittest.main(verbosity=2)
