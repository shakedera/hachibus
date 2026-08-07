# はちバス時刻表（市バス検索君）

八戸市営バスの GTFS-JP オープンデータを使った、個人用の時刻表検索 PWA。
乗車・降車バス停を指定した時刻検索と、定番ルートの次便を起動即表示する
ダッシュボードを持つ。GitHub Pages で公開し、スマホのホーム画面に追加して使う。

- サーバー不要（静的ファイルのみ）。アプリ本体は `docs/index.html` の単一ファイル
- データ出典: 八戸市交通部 GTFS-JP オープンデータ（CC BY 4.0）

## できること

- 起動して0タップで、定番ルートの次のバスまでの残り時間を表示（1分ごと自動更新）
- 乗車→降車バス停の時刻検索(部分一致・かな/カナ対応、のりば違いは統合)
- 「目的地から」ボタンで施設名から降車バス停を探せる
  (OpenStreetMap/Nominatimで施設検索 → 近い順5件をリスト・地図表示)
- 「今から / 出発 / 到着」の時刻指定と「平日 / 土曜 / 日祝」のダイヤ切替（祝日は自動判定）
- 検索結果の★で定番ルート登録（localStorage 保存、チップ長押しで削除）
- オフライン利用可（service worker によるキャッシュ）

## ダイヤ改正時の更新手順

1. GTFS-JP オープンデータ一覧サイト（bustime.jp の GTFS 一覧、または
   [GTFSデータリポジトリ](https://gtfs-data.jp/search?target_feed=hachinohe*hachinohe-citybus)）から
   八戸市営バスの最新 zip をダウンロードし、`gtfs/` に上書き配置する
   （zip はリネーム不要。`gtfs/` に zip が1つだけある状態にする）
2. `python scripts/build_data.py` を実行する
   （ビルドログにバス停数・便数・有効期限が出るので確認）
3. `docs/sw.js` の **3行目** のキャッシュバージョン番号を1つ上げる
   ```js
   const CACHE_NAME = "hachibus-v1";   // ← v2, v3… と上げる
   ```
4. `git add -A` → `git commit` → `git push`（GitHub Pages に自動反映）
5. スマホでアプリを開き直し、フッターの「ダイヤ有効期限」が更新されたことを確認する

※ 有効期限まで14日を切ると、アプリ上部に更新を促す警告バーが自動表示される。

## 他事業者データの統合（私的利用・公開しない）

南部バスなど、再配布可否が明示されていないGTFSデータは公開サイトに載せず、
自分の端末にだけ取り込んで使う:

1. データ入手（南部バスはジョルダン「公共交通データHUBシステム」 https://www.ptd-hs.jp/ に利用登録してダウンロード）
2. zip を `gtfs-private/` に置く（このフォルダは .gitignore 済みで push されない）
3. `python scripts/build_data.py` を実行 → リポジトリ直下に `private-data.json` が生成される（これも git 管理外）
4. `private-data.json` をスマホに送り（LINEのKeep・メール添付など）、
   アプリのフッター「統合データを取り込む」からファイルを選ぶ
5. 以後そのデータで検索される（フッターに「取り込みデータ使用中」と表示。
   「公開データに戻す」でいつでも市営バスのみに戻せる）

※ `gtfs/` にある市営バスデータ（CC BY 4.0）だけが GitHub Pages に公開される。

## 初回セットアップ（GitHub Pages）

1. このフォルダを GitHub リポジトリとして push する
2. GitHub の Settings → Pages → 「Build and deployment」で
   Branch: `main`、フォルダ: `/docs` を選んで保存
3. 公開された URL をスマホで開き、「ホーム画面に追加」で PWA としてインストール

## 構成

```
├── gtfs/                # GTFS-JP zip 置き場（手動配置）
├── scripts/
│   ├── build_data.py    # GTFS → docs/data.json 前処理（Python 3 標準ライブラリのみ）
│   └── make_icons.py    # PWAアイコン生成（Pillow 使用・通常は再実行不要）
└── docs/                # GitHub Pages 公開ディレクトリ
    ├── index.html       # アプリ本体（単一HTML・vanilla JS）
    ├── data.json        # 前処理済み時刻データ
    ├── manifest.json    # PWAマニフェスト
    ├── sw.js            # service worker（キャッシュバージョンはここ）
    └── icon-192.png / icon-512.png
```

## 技術

- 前処理: Python 3（標準ライブラリのみ。どのPCでも実行できる）
- アプリ: 単一HTML + vanilla JS（CDN・Webフォント不使用。
  地図のみ Leaflet 1.9.4 を `docs/vendor/` に同梱）
- 外部API: 施設検索に Nominatim（OpenStreetMap）、地図タイルに OSM を利用
  （どちらも「目的地から」機能のみ。時刻検索はオフラインで完結）
- データ: 停留所・便を整数ID化、時刻は深夜0時からの分数に圧縮した JSON（約700KB）
- テスト: `python scripts/test_data.py`（データの不変条件検査。push時にGitHub Actionsでも自動実行）

## ライセンス

- コード: MIT（[LICENSE](LICENSE)）
- 時刻表データ: 八戸市交通部 GTFS-JPオープンデータ（CC BY 4.0）を加工して作成

## 方針: ビルドレスを維持する

バンドラ・npm・フレームワークは導入しない。「どのPCでも python 1コマンド＋
git push で完結する」ことがこのアプリの壊れにくさの本体であり、
利用者1人・低頻度変更の規模では導入コストの方が大きい。
index.html が3,000行を超える規模の機能追加をするときに再検討する。

## 困ったとき

- 検索結果がおかしい → フッターの「公開データに戻す」→ 統合データを再取り込み
- エラーが出る → フッターの「エラーログ」でコピーして開発時のAIに貼り付ける
- iPhoneは「ホーム画面に追加」して使うこと（Safariのまま長期間放置すると
  端末内データが自動削除されることがある）

## 状態

- 開発完了・動作確認済み（2026-07-14）
- 現在のデータ: 令和8年4月改正ダイヤ（有効期限 2027-03-31）
- 利用者は開発者本人のみを想定
