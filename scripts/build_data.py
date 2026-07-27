# -*- coding: utf-8 -*-
"""GTFS-JP → data.json 前処理スクリプト（Python標準ライブラリのみ・複数事業者対応）

- gtfs/ にある zip（公開可能データ）から docs/data.json を生成する
- gtfs-private/ に zip があれば、gtfs/ と合わせた統合データを
  private-data.json（リポジトリ直下・git管理外）にも生成する。
  これは端末取り込み用で、GitHub には push しないこと（.gitignore 済み）

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
PRIVATE_DIR = ROOT / "gtfs-private"
PUBLIC_OUT = ROOT / "docs" / "data.json"
PRIVATE_OUT = ROOT / "private-data.json"

# ダイヤ区分: 0=平日, 1=土曜, 2=日祝
CLASS_NAMES = ["平日", "土曜", "日祝"]
BASE_SERVICE_PREFIX = {"1_平日": 0, "4_土曜": 1, "2_日祝": 2}

# 事業者名の短縮表示（バッジ用）
AGENCY_SHORT = {
    "八戸市交通部": "市営",
    "岩手県北自動車": "南部",
    "岩手県北自動車株式会社": "南部",
    "南部バス": "南部",
    "十和田観光電鉄": "十鉄",
    "十和田観光電鉄株式会社": "十鉄",
    "八戸市": "南郷",  # 南郷コミュニティバス（運行主体は八戸市）
}

BADGE_RE = re.compile(r"^[\[［]([^\]］]+)[\]］]")

# --- 事業者間の停留所名の表記揺れ吸収 ---
# 中心街ターミナルの呼び方は3社3様:
#   市営「八戸中心街ターミナル（八日町）」/ 南部「中心街ターミナル２番（八日町）」/
#   十鉄「八戸中心街ターミナル八日町２番」 → すべて市営表記に名寄せ
CENTER_LOCALITIES = ["三日町", "八日町", "中央通り", "朔日町", "六日町"]
# 同一地点で名前が異なる停留所（完全一致でのみ適用）
STOP_ALIAS = {
    "八戸駅前": "八戸駅",              # 南部バス→市営名
    "ラピアバスターミナル": "ラピアバスセンター",
    "八戸市民病院": "市民病院",        # 十鉄→市営名
}
import unicodedata


def normalize_stop_name(name):
    """グループ化用の停留所名と、名前から拾えたのりば番号を返す"""
    n = unicodedata.normalize("NFKC", name)
    if "中心街ターミナル" in n:
        for loc in CENTER_LOCALITIES:
            if loc in n:
                m = re.search(r"(\d+)番", n)
                return f"八戸中心街ターミナル（{loc}）", (m.group(1) if m else "")
    if name in STOP_ALIAS:
        return STOP_ALIAS[name], ""
    return name, ""


def read_csv(zf, name):
    with zf.open(name) as f:
        yield from csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig"))


def has_file(zf, name):
    return name in {i.filename for i in zf.infolist()}


def time_to_min(hms):
    h, m, _s = hms.split(":")
    return int(h) * 60 + int(m)


def service_classes(service_id, cal_row):
    """service_id → 該当するダイヤ区分の集合。

    市営バスの「1_平日」等はプレフィックスで1区分に確定。
    それ以外は calendar.txt の曜日パターンから該当区分すべてを返す
    （例: 十鉄「全日」→ {平日,土曜,日祝}、「日・祝運休」→ {平日,土曜}）。
    戻り値: (区分set, 基本サービスか, 警告文 or None)
    """
    for prefix, cls in BASE_SERVICE_PREFIX.items():
        if service_id == prefix:
            return {cls}, True, None
        if service_id.startswith(prefix):
            return {cls}, False, (
                f"特殊ダイヤ '{service_id}' を「{CLASS_NAMES[cls]}」区分に寄せました"
                f"（運行日は calendar_dates 限定の可能性あり）")
    if cal_row:
        days = [int(cal_row[d]) for d in (
            "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")]
        classes = set()
        if any(days[0:5]):
            classes.add(0)
        if days[5]:
            classes.add(1)
        if days[6]:
            classes.add(2)
        if classes:
            warn = None
            if days[0:5].count(1) not in (0, 5):
                warn = (f"サービス '{service_id}' は平日の一部曜日のみ運行"
                        f"（{''.join(map(str, days))}）ですが平日区分に含めました")
            return classes, False, warn
    return {0}, False, f"サービス '{service_id}' の曜日パターン不明のため平日に分類"


def load_feed(zip_path):
    """1つのGTFS zipを読み、正規化した中間表現を返す"""
    zf = zipfile.ZipFile(zip_path)
    feed = {"name": zip_path.name, "warnings": []}

    # 事業者名
    agency = ""
    if has_file(zf, "agency.txt"):
        for r in read_csv(zf, "agency.txt"):
            agency = r.get("agency_name", "")
            break
    feed["agency"] = agency
    feed["op"] = AGENCY_SHORT.get(agency, (agency or zip_path.stem)[:4])

    # calendar
    calendar = {}
    if has_file(zf, "calendar.txt"):
        calendar = {r["service_id"]: r for r in read_csv(zf, "calendar.txt")}
    feed["expires"] = max((r["end_date"] for r in calendar.values()), default="")

    svc_classes = {}
    is_base_feed = False
    for sid, row in calendar.items():
        classes, is_base, warn = service_classes(sid, row)
        svc_classes[sid] = classes
        if is_base:
            is_base_feed = True
        if warn:
            feed["warnings"].append(warn)
    feed["is_base_feed"] = is_base_feed

    # calendar_dates: 例外日（市営の基本3サービスのみ利用）
    holiday_map = {}
    if is_base_feed and has_file(zf, "calendar_dates.txt"):
        for r in read_csv(zf, "calendar_dates.txt"):
            sid, date, ex = r["service_id"], r["date"], r["exception_type"]
            if sid in BASE_SERVICE_PREFIX and ex == "1":
                holiday_map[date] = BASE_SERVICE_PREFIX[sid]
    feed["holiday_map"] = holiday_map

    # stops
    stops = {}
    for s in read_csv(zf, "stops.txt"):
        if s.get("location_type") not in ("", "0"):
            continue
        stops[s["stop_id"]] = {
            "name": s["stop_name"],
            "platform": s.get("platform_code", "") or "",
            "lat": s.get("stop_lat", ""), "lon": s.get("stop_lon", ""),
        }
    feed["stops"] = stops

    # 読み仮名
    kana = {}
    if has_file(zf, "translations.txt"):
        for r in read_csv(zf, "translations.txt"):
            if (r.get("table_name") == "stops" and r.get("field_name") == "stop_name"
                    and r.get("language") == "ja-Hrkt"):
                key = r.get("record_id") or r.get("field_value") or ""
                if key:
                    kana[key] = r["translation"]
    feed["kana"] = kana

    # routes（バッジのフォールバック用に route_short_name）
    route_short = {}
    if has_file(zf, "routes.txt"):
        for r in read_csv(zf, "routes.txt"):
            route_short[r["route_id"]] = r.get("route_short_name", "") or ""

    # trips
    trips_meta = {}
    for t in read_csv(zf, "trips.txt"):
        sid = t["service_id"]
        if sid not in svc_classes:
            classes, _b, warn = service_classes(sid, None)
            svc_classes[sid] = classes
            if warn:
                feed["warnings"].append(warn)
        trips_meta[t["trip_id"]] = (
            svc_classes[sid],
            t.get("trip_headsign", ""),
            route_short.get(t.get("route_id", ""), ""),
        )
    feed["trips_meta"] = trips_meta

    # stop_times
    trip_stops = defaultdict(list)
    trip_badge = {}
    skipped = 0
    for r in read_csv(zf, "stop_times.txt"):
        tid, sid = r["trip_id"], r["stop_id"]
        if tid not in trips_meta or sid not in stops:
            skipped += 1
            continue
        dep = time_to_min(r["departure_time"])
        arr = time_to_min(r["arrival_time"])
        trip_stops[tid].append((int(r["stop_sequence"]), sid, dep, dep - arr))
        if tid not in trip_badge:
            m = BADGE_RE.match(r.get("stop_headsign", "") or "")
            badge = m.group(1) if m else ""
            if re.fullmatch(r"\d+円", badge):
                badge = "循環" if "循環" in r.get("stop_headsign", "") else ""
            trip_badge[tid] = badge
    if skipped:
        feed["warnings"].append(f"stop_times {skipped} 行を不明な trip/stop のためスキップ")
    feed["trip_stops"] = trip_stops
    feed["trip_badge"] = trip_badge
    return feed


def build(zip_paths, out_path, label):
    feeds = [load_feed(p) for p in zip_paths]

    # 同一事業者のzipが複数あると全便が二重登録されるため停止（旧zipの消し忘れ対策）
    agencies = [fd["agency"] for fd in feeds]
    dups = sorted({a for a in agencies if agencies.count(a) > 1})
    if dups:
        sys.exit(f"エラー: 同じ事業者のzipが複数あります: {dups}（旧zipを削除してから再実行してください）")

    # 事業者テーブル（同名は統合）
    ops, op_idx = [], {}
    for fd in feeds:
        if fd["op"] not in op_idx:
            op_idx[fd["op"]] = len(ops)
            ops.append(fd["op"])
        fd["op_i"] = op_idx[fd["op"]]

    # バス停: 名前でグループ化（事業者をまたいで同名は統合）
    group_index, groups = {}, []
    stops_out = []
    stop_int = {}  # (feed_i, stop_id) → 連番int
    for fi, fd in enumerate(feeds):
        for sid, s in fd["stops"].items():
            name, plat_extra = normalize_stop_name(s["name"])
            if name not in group_index:
                group_index[name] = len(groups)
                groups.append([name, fd["kana"].get(sid, "")])
            gi = group_index[name]
            if not groups[gi][1] and fd["kana"].get(sid):
                groups[gi][1] = fd["kana"][sid]
            try:
                lat = round(float(s["lat"]), 5)
                lon = round(float(s["lon"]), 5)
            except ValueError:
                lat = lon = 0
            stop_int[(fi, sid)] = len(stops_out)
            stops_out.append([gi, s["platform"] or plat_extra, lat, lon])

    # 便（区分が複数あるサービスは各区分に展開する）
    badge_table, badge_idx = [], {}
    head_table, head_idx = [], {}

    def intern(table, index, s):
        if s not in index:
            index[s] = len(table)
            table.append(s)
        return index[s]

    trips_out = []
    for fi, fd in enumerate(feeds):
        for tid, rows in fd["trip_stops"].items():
            rows.sort()
            classes, headsign, route_short = fd["trips_meta"][tid]
            badge = fd["trip_badge"].get(tid, "") or route_short
            flat = []
            for _seq, sid, dep, d in rows:
                flat.extend((stop_int[(fi, sid)], dep, d))
            bi = intern(badge_table, badge_idx, badge)
            hi = intern(head_table, head_idx, headsign)
            for cls in sorted(classes):
                trips_out.append([cls, bi, hi, flat, fd["op_i"]])
    trips_out.sort(key=lambda t: (t[0], t[3][1] if len(t[3]) > 1 else 0))

    # 例外日辞書・有効期限（期限は全フィードの最小＝どれかが切れたら警告）
    holiday_map = {}
    for fd in feeds:
        holiday_map.update(fd["holiday_map"])
    expires = min((fd["expires"] for fd in feeds if fd["expires"]), default="")

    version = ""
    for fd, p in zip(feeds, zip_paths):
        if fd["is_base_feed"]:
            zf = zipfile.ZipFile(p)
            if has_file(zf, "feed_info.txt"):
                for r in read_csv(zf, "feed_info.txt"):
                    version = r.get("feed_version", "")
                    break

    data = {
        "v": version,          # 代表（市営）フィードのバージョン表記
        "ex": expires,         # ダイヤ有効期限 YYYYMMDD（全フィードの最小）
        "hd": holiday_map,     # 例外日 YYYYMMDD → ダイヤ区分(0/1/2)
        "op": ops,             # 事業者名テーブル（2件以上のときアプリがバッジ表示）
        "g": groups,           # バス停名グループ [名前, かな]
        "s": stops_out,        # 停留所 [グループidx, のりば, 緯度, 経度]
        "b": badge_table,      # 系統番号テーブル
        "h": head_table,       # 行き先テーブル
        "t": trips_out,        # 便 [区分, 系統idx, 行き先idx, [停idx,出発分,差分,...], 事業者idx]
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))

    size = out_path.stat().st_size
    cls_count = Counter(t[0] for t in trips_out)
    print(f"--- {label} → {out_path.name}")
    agencies = " / ".join(f"{fd['agency']}({fd['op']})" for fd in feeds)
    print(f"  事業者: {agencies}")
    print(f"  サイズ: {size / 1024:.0f} KB / バス停 {len(stops_out)}（グループ {len(groups)}） / "
          f"便 {len(trips_out)}（平日 {cls_count[0]} / 土曜 {cls_count[1]} / 日祝 {cls_count[2]}）")
    print(f"  例外日 {len(holiday_map)} 日 / 有効期限 {expires}")
    for fd in feeds:
        for w in fd["warnings"]:
            print(f"  警告[{fd['op']}]: {w}")


def main():
    public_zips = sorted(GTFS_DIR.glob("*.zip"))
    if not public_zips:
        sys.exit(f"エラー: {GTFS_DIR} に GTFS zip がありません")
    build(public_zips, PUBLIC_OUT, "公開用（市営バスのみ）")
    # 公開用に市営以外が混入していたら即停止（gtfs/ への誤配置による漏洩防止）
    with open(PUBLIC_OUT, encoding="utf-8") as f:
        pub_ops = json.load(f)["op"]
    if pub_ops != ["市営"]:
        PUBLIC_OUT.unlink()
        sys.exit(f"エラー: 公開用データに市営以外の事業者が混入: {pub_ops}（gtfs/ の中身を確認してください）")

    private_zips = sorted(PRIVATE_DIR.glob("*.zip")) if PRIVATE_DIR.exists() else []
    if private_zips:
        build(public_zips + private_zips, PRIVATE_OUT, "統合版（端末取り込み用・公開禁止）")
        print(f"※ {PRIVATE_OUT.name} は git 管理外です。スマホのアプリの"
              f"「データ取り込み」からこのファイルを読み込んでください")


if __name__ == "__main__":
    main()
