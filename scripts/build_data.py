# -*- coding: utf-8 -*-
"""GTFS-JP → docs/data.json 前処理スクリプト（Python標準ライブラリのみ）

gtfs/ にある GTFS-JP zip を読み、アプリが使う軽量JSONを生成する。
使い方: python scripts/build_data.py
"""
import csv
import io
import json
import re
import sys
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GTFS_DIR = ROOT / "gtfs"
OUT_PATH = ROOT / "docs" / "data.json"

# ダイヤ区分: 0=平日, 1=土曜, 2=日祝
CLASS_NAMES = ["平日", "土曜", "日祝"]
BASE_SERVICE_PREFIX = {"1_平日": 0, "4_土曜": 1, "2_日祝": 2}


def find_zip():
    zips = sorted(GTFS_DIR.glob("*.zip"))
    if not zips:
        sys.exit(f"エラー: {GTFS_DIR} に GTFS zip がありません")
    if len(zips) > 1:
        print(f"警告: zip が複数あります。最初の {zips[0].name} を使います")
    return zips[0]


def read_csv(zf, name):
    """zip 内の CSV を DictReader で読む（BOM対応）"""
    with zf.open(name) as f:
        yield from csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig"))


def time_to_min(hms):
    """"HH:MM:SS" → 深夜0時からの分数（24時超え表記もそのまま扱える）"""
    h, m, _s = hms.split(":")
    return int(h) * 60 + int(m)


def classify_service(service_id, cal_row):
    """service_id を 平日/土曜/日祝 の3区分に分類。(区分, 基本サービスか) を返す"""
    for prefix, cls in BASE_SERVICE_PREFIX.items():
        if service_id == prefix:
            return cls, True
        if service_id.startswith(prefix):
            return cls, False
    # プレフィックスで判定できない場合は calendar.txt の曜日パターンで最も近い区分に寄せる
    if cal_row:
        days = [int(cal_row[d]) for d in (
            "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")]
        scores = [sum(days[0:5]), days[5], days[6]]
        return scores.index(max(scores)), False
    return 0, False


def main():
    zip_path = find_zip()
    print(f"読み込み: {zip_path.name}")
    zf = zipfile.ZipFile(zip_path)

    # --- calendar: サービス区分の分類 ---
    calendar = {r["service_id"]: r for r in read_csv(zf, "calendar.txt")}
    service_class = {}
    warnings = []
    for sid, row in calendar.items():
        cls, is_base = classify_service(sid, row)
        service_class[sid] = cls
        if not is_base:
            warnings.append(f"特殊ダイヤ '{sid}' を「{CLASS_NAMES[cls]}」区分に寄せました"
                            f"（運行日は calendar_dates 限定の可能性あり）")

    # ダイヤ有効期限 = end_date の最大値
    expires = max(r["end_date"] for r in calendar.values())

    # --- calendar_dates: 例外日 → ダイヤ区分の辞書 ---
    # 基本3サービスの「追加(exception_type=1)」を日付→区分として採用する
    # （例: 祝日は 1_平日 が削除され 2_日祝 が追加される）
    holiday_map = {}
    removed_only = defaultdict(set)
    for r in read_csv(zf, "calendar_dates.txt"):
        sid, date, ex = r["service_id"], r["date"], r["exception_type"]
        if sid not in BASE_SERVICE_PREFIX:
            continue  # 特殊ダイヤの例外日はアプリの区分判定には使わない
        if ex == "1":
            cls = BASE_SERVICE_PREFIX[sid]
            if date in holiday_map and holiday_map[date] != cls:
                warnings.append(f"例外日 {date} に複数区分の追加があり矛盾（{holiday_map[date]} vs {cls}）")
            holiday_map[date] = cls
        else:
            removed_only[date].add(sid)
    for date, sids in sorted(removed_only.items()):
        if date not in holiday_map:
            warnings.append(f"例外日 {date}: {sorted(sids)} が運休だが代替の追加なし（この日は該当区分の便が実際は走らない）")

    # --- stops: 連番ID振り直し ＋ 同名グループ化 ---
    stops_raw = list(read_csv(zf, "stops.txt"))

    # 読み仮名（translations.txt の ja-Hrkt）
    kana_by_stop = {}
    try:
        for r in read_csv(zf, "translations.txt"):
            if (r.get("table_name") == "stops" and r.get("field_name") == "stop_name"
                    and r.get("language") == "ja-Hrkt"):
                key = r.get("record_id") or r.get("field_value") or ""
                if key:
                    kana_by_stop[key] = r["translation"]
    except KeyError:
        pass

    group_index = {}   # stop_name → group idx
    groups = []        # [name, kana]
    stop_int = {}      # 元stop_id → 連番int
    stops_out = []     # [group_idx, platform_label]
    for s in stops_raw:
        if s.get("location_type") not in ("", "0"):
            continue  # 乗降できない駅・エリアは除外
        name = s["stop_name"]
        if name not in group_index:
            group_index[name] = len(groups)
            groups.append([name, kana_by_stop.get(s["stop_id"], "")])
        gi = group_index[name]
        if not groups[gi][1] and kana_by_stop.get(s["stop_id"]):
            groups[gi][1] = kana_by_stop[s["stop_id"]]
        stop_int[s["stop_id"]] = len(stops_out)
        stops_out.append([gi, s.get("platform_code", "") or ""])

    # --- trips: 行き先・系統番号 ---
    trips_meta = {}
    for t in read_csv(zf, "trips.txt"):
        sid = t["service_id"]
        if sid not in service_class:
            cls, _ = classify_service(sid, None)
            service_class[sid] = cls
            warnings.append(f"calendar.txt に無いサービス '{sid}' を「{CLASS_NAMES[cls]}」に分類")
        trips_meta[t["trip_id"]] = (service_class[sid], t.get("trip_headsign", ""))

    # --- stop_times: 便ごとの時刻列 ---
    badge_re = re.compile(r"^[\[［]([^\]］]+)[\]］]")
    trip_stops = defaultdict(list)   # trip_id → [(seq, stop_int, dep_min, dep-arr)]
    trip_badge = {}                  # trip_id → 系統番号（先頭停留所の stop_headsign から抽出）
    skipped = 0
    for r in read_csv(zf, "stop_times.txt"):
        tid = r["trip_id"]
        sid = r["stop_id"]
        if tid not in trips_meta or sid not in stop_int:
            skipped += 1
            continue
        dep = time_to_min(r["departure_time"])
        arr = time_to_min(r["arrival_time"])
        trip_stops[tid].append((int(r["stop_sequence"]), stop_int[sid], dep, dep - arr))
        if tid not in trip_badge:
            m = badge_re.match(r.get("stop_headsign", "") or "")
            trip_badge[tid] = m.group(1) if m else ""

    # 文字列テーブル（系統番号・行き先）で重複を除く
    badge_table, badge_idx = [], {}
    head_table, head_idx = [], {}

    def intern(table, index, s):
        if s not in index:
            index[s] = len(table)
            table.append(s)
        return index[s]

    trips_out = []
    for tid, rows in trip_stops.items():
        rows.sort()
        cls, headsign = trips_meta[tid]
        flat = []
        for _seq, si, dep, d in rows:
            flat.extend((si, dep, d))
        trips_out.append([
            cls,
            intern(badge_table, badge_idx, trip_badge.get(tid, "")),
            intern(head_table, head_idx, headsign),
            flat,
        ])
    # 始発時刻順に並べておく（アプリ側の表示が安定する）
    trips_out.sort(key=lambda t: (t[0], t[3][1] if len(t[3]) > 1 else 0))

    feed_version = ""
    try:
        for r in read_csv(zf, "feed_info.txt"):
            feed_version = r.get("feed_version", "")
            break
    except KeyError:
        pass

    data = {
        "v": feed_version,        # フィードのバージョン表記
        "ex": expires,            # ダイヤ有効期限 YYYYMMDD
        "hd": holiday_map,        # 例外日 YYYYMMDD → ダイヤ区分(0/1/2)
        "g": groups,              # バス停名グループ [名前, かな]
        "s": stops_out,           # 停留所 [グループidx, のりば番号] （配列位置=連番ID）
        "b": badge_table,         # 系統番号文字列テーブル
        "h": head_table,          # 行き先文字列テーブル
        "t": trips_out,           # 便 [区分, 系統idx, 行き先idx, [停idx,出発分,出発-到着,...]]
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))

    # --- ビルドログ ---
    size = OUT_PATH.stat().st_size
    cls_count = Counter(t[0] for t in trips_out)
    print(f"出力: {OUT_PATH}")
    print(f"サイズ: {size / 1024:.0f} KB ({size:,} bytes)")
    print(f"バス停: {len(stops_out)} 箇所（名前グループ {len(groups)} 件、かな付き {sum(1 for g in groups if g[1])} 件）")
    print(f"便数: {len(trips_out)} "
          f"（平日 {cls_count[0]} / 土曜 {cls_count[1]} / 日祝 {cls_count[2]}）")
    print(f"例外日: {len(holiday_map)} 日 / ダイヤ有効期限: {expires}")
    if skipped:
        print(f"警告: stop_times {skipped} 行を不明な trip/stop のためスキップ")
    for w in warnings:
        print(f"警告: {w}")


if __name__ == "__main__":
    main()
