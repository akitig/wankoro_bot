# Runtime JSON worktree分離計画

## 目的と適用範囲

この文書は、Git worktree内でGit追跡中のmutable runtime JSONを、コードの
checkout・pull・deployから独立した保存先へ安全に移すための計画です。この計画を
追加する変更では、JSON、`.env`、Git index、systemd Unit、稼働プロセスを変更しません。

対象は単一のsystem-level systemd serviceとして動く、現在のわんころBotです。
SQLite移行や複数プロセス対応は対象外です。

## 現状構成

### データ分類と参照箇所

| データ | 現行Config | 読み書き箇所 | 不存在時の初期値 | Git状態 |
|---|---|---|---|---|
| VALORANT診断完了 | `VALO_CHECK_DATA_PATH` | `services/valocheck_service.py` | `{}` | 追跡中 |
| おみくじポイント | `OMIKUJI_POINTS_PATH` | `cogs/2026_omikuji_gacha.py` | `{}` | 追跡中 |
| 除夜の鐘state | `JOYA_DATA_PATH` | `cogs/2026_joya_gacha.py` | `{"guilds": {}, "users": {}}` | 追跡中 |
| Xmas state | `XMAS_GACHA_STATE` | `cogs/2025_xmas_gacha.py` | `{"orig_nick": {}, "panel_message_id": 0}` | 追跡中 |
| VALORANT map BAN | Config内固定 `valomap_bans.json` | `cogs/valomap.py` | `{"bans": []}` | 未追跡・ignore済み |

静的master dataである `data/valo_questions.json`、`data/valo_intro.json`、
`data/2025_xmas_gacha.csv` は移行対象ではなく、引き続きGitで管理します。

JSON I/Oは `utils/json_store.py` ではなく `storage/json_store.py` に集約されています。
UTF-8、親ディレクトリ作成、一時ファイル、`fsync()`、`os.replace()`を使用します。
不存在時だけ各機能のデフォルトを返し、不正JSONは無言で初期化せず例外にします。

### 現行パスの注意点

- `XMAS_GACHA_STATE` の既定値は本番worktree内の絶対パスです。
- `VALO_CHECK_DATA_PATH` と `OMIKUJI_POINTS_PATH` の既定値はworktree相対です。
- `JOYA_DATA_PATH` の既定値 `data/joya_state.json` は、追跡中の
  `data/2026_joya_state.json` と名前が異なります。
- `valomap_bans.json` には現在、環境変数overrideがありません。
- 本番 `.env` には各path用の設定キーが存在しますが、この調査では秘密保持のため
  値を読み出していません。移行前に実プロセスの解決済みパスを別途確認します。

### 問題点

`.gitignore` は未追跡ファイルの追加を防ぐだけで、既にindexへ登録された4ファイルを
保護しません。checkout、pull、reset、archive展開、worktree全体の同期により、Botが
更新した本番データがリポジトリ版へ戻る可能性があります。また、コードとデータの
ロールバック単位が分離されていません。

## 保存先の選択

### 比較

| 観点 | 案A: `RUNTIME_DATA_DIR` | 案B: XDG data directory | 案C: `StateDirectory=` |
|---|---|---|---|
| 実装 | 明示的で単純 | fallback解決が必要 | Configが`STATE_DIRECTORY`を読む対応が必要 |
| systemd | `EnvironmentFile`と相性良好 | system serviceではHOME依存が不明瞭 | system-level Unitと最も相性が良い |
| User service | 利用可能 | 最適 | user serviceでは保存先・挙動がsystem serviceと異なる |
| system service | directory作成を別途管理 | 推奨しにくい | `/var/lib`をsystemdが管理 |
| 権限 | 運用者が作成・chmod | ユーザー所有で容易 | systemdがUser/Groupに合わせて作成 |
| バックアップ | パスが明示的 | HOME配下の除外に注意 | `/var/lib/wankoro-bot`を明示的に対象化しやすい |
| 開発・CI | tmp pathを指定しやすい | 開発に自然 | CIではUnitがないため単独では使えない |
| ロールバック | envを旧pathへ戻せる | HOME解決差に注意 | Unit/envを旧pathへ戻せる。データは別保護が必要 |
| 複数環境 | 環境ごとに値を変更 | ユーザーごとに分離 | Unit instanceや名称設計が必要 |

### 推奨

本番は案Cを推奨します。

```ini
[Service]
StateDirectory=wankoro-bot
StateDirectoryMode=0700
```

system-level Unitでは保存先が `/var/lib/wankoro-bot` となり、systemdが
`User=akitig`（Group未指定ならprimary group）で書き込めるよう管理します。
推奨構成は次のとおりです。

```text
/var/lib/wankoro-bot/
├── valo_check_completed.json
├── 2026_omikujii_points.json
├── 2026_joya_state.json
├── xmas_gacha_state.json
└── valomap_bans.json
```

directory modeは `0700`、JSONは新規作成時 `0600` を推奨します。既存
`save_json_atomic()`は置換時に既存modeを保持します。バックアップ先も管理者と
サービス所有者以外が読めない `0700` / `0600` とします。

`/home/akitig/.local/share/wankoro-bot` は、案Bの既定値として開発環境や
user serviceでは妥当です。ただし現行はsystem-level serviceなので、本番の第一候補
にはしません。案Aは緊急override、段階移行、複数instanceの明示分離に適しています。

## 将来のConfig変更案

コード対応PRでは、既存の個別path設定を壊さず、次の優先順位でruntime rootを解決します。

1. 明示的な `RUNTIME_DATA_DIR`
2. systemdが `StateDirectory=` から提供する `STATE_DIRECTORY`
3. `XDG_DATA_HOME/wankoro-bot`
4. `~/.local/share/wankoro-bot`

個別設定 `VALO_CHECK_DATA_PATH`、`OMIKUJI_POINTS_PATH`、`JOYA_DATA_PATH`、
`XMAS_GACHA_STATE` が設定されている場合は、後方互換のためroot派生値より優先します。
Valomapには同じrootから派生するConfig pathを追加します。master dataの
`VALO_CHECK_QUESTIONS_PATH`、`VALO_CHECK_INTRO_PATH`、`XMAS_GACHA_CSV` はruntime rootへ
移しません。

本番切替では、個別pathを一度に次へ変更する方法が最も監査しやすい案です。

```env
RUNTIME_DATA_DIR=/var/lib/wankoro-bot
VALO_CHECK_DATA_PATH=/var/lib/wankoro-bot/valo_check_completed.json
OMIKUJI_POINTS_PATH=/var/lib/wankoro-bot/2026_omikujii_points.json
JOYA_DATA_PATH=/var/lib/wankoro-bot/2026_joya_state.json
XMAS_GACHA_STATE=/var/lib/wankoro-bot/xmas_gacha_state.json
```

実装後にroot派生が十分検証されるまでは個別pathを残します。`.env.example`には値のない
秘密ではなくpath例だけを記載します。本番 `.env` は引き続きmode `0600`とします。

## 段階的な移行順序

### 1. コード対応PR

1. runtime root解決とValomap path overrideをConfigへ追加する。
2. 個別path設定との後方互換をテストする。
3. 全runtimeテストを `tmp_path` のみで実行する。
4. import、pytest、Ruff、compileall、pip checkをTokenなしで通す。
5. この段階では既定の本番pathもGit indexも変更しない。

### 2. 移行前確認

運用者は、実際に解決される旧pathを秘密値やJSON内容を表示せず確認します。特に
JOYAのファイル名差異を推測で処理しません。対象ごとに所有者、mode、容量、更新時刻、
SHA-256を記録します。

JSON構文は内容を標準出力へ出さず検証します。

```bash
.venv/bin/python -c 'import json, pathlib, sys; [json.load(p.open(encoding="utf-8")) for p in map(pathlib.Path, sys.argv[1:])]' \
  OLD_VALO OLD_OMIKUJI OLD_JOYA OLD_XMAS
sha256sum OLD_VALO OLD_OMIKUJI OLD_JOYA OLD_XMAS > runtime-before.sha256
```

`OLD_*` は確認済みの絶対パスへ置き換えます。未解決の変数やglobをコピー・削除
コマンドへ渡しません。

### 3. バックアップと復元試験

1. 承認済みメンテナンス開始時刻を記録する。
2. Botを停止して全writerを止める。想定停止時間は5〜15分だが、検証不合格時は
   再開せずロールバックする。
3. mode `0700` の日時付きバックアップdirectoryへ4ファイルと、存在する場合は
   `valomap_bans.json`をコピーする。
4. コピー前後のSHA-256が一致することを確認する。
5. バックアップを別の一時directoryへ復元し、JSON構文、schema、件数を検証する。

内容や個人IDを表示せず、最低限次を確認します。

- VALORANT診断: top-levelがobject、各recordがobject、record件数
- おみくじ: top-levelがobject、keyが数字文字列、valueが整数、ユーザー件数
- 除夜の鐘: `guilds`と`users`がobject、各件数
- Xmas: `orig_nick`がobject、`panel_message_id`が整数、guild/user件数
- Valomap: `bans`がlist、要素数

バックアップの復元試験に成功するまでコピー工程へ進みません。バックアップは暗号化・
アクセス制限された別媒体にも保持します。

### 4. 新保存先の作成とコピー

Unitへ `StateDirectory=wankoro-bot` と `StateDirectoryMode=0700` を追加する案を
レビューし、反映後にsystemdがdirectoryを作成したことを確認します。代替として事前に
作成する場合は、owner/groupをservice userにしmodeを `0700` とします。

Botを停止したまま、旧ファイルを新しい確定名へコピーします。移動や削除はしません。
新旧のSHA-256、JSON構文、schema、件数、owner、modeを再確認します。新ファイルは
`0600`とします。

### 5. Unitと環境設定の切替

1. Unitと `.env` をそれぞれ日時付きでバックアップする。
2. Unitには `StateDirectory` / `StateDirectoryMode` だけを追加し、既存の
   `User`、`WorkingDirectory`、`ExecStart`、`EnvironmentFile`、restart、ログ設定を
   意図せず変更しない。
3. `.env` の個別runtime pathを新しい絶対パスへ変更する。
4. `systemd-analyze verify` とUnit差分確認を行う。
5. daemon-reload後にBotを一度だけ起動する。

systemd操作はこの文書作成PRでは実施せず、承認済み作業者が行います。

### 6. 再起動後の確認

- serviceが単一プロセスでactiveである
- Cogロード失敗、JSON decode error、permission errorがない
- 設定された全runtime pathが `/var/lib/wankoro-bot` 配下である
- 新pathだけが更新され、旧pathのmtimeとSHA-256が変わらない
- 一時ファイルを作成しatomic replaceできる所有権・modeである
- VALORANT診断完了件数、おみくじユーザー件数、除夜の鐘state、Xmas state、map BAN数が
  移行前と一致する

Discord上では、表示文言やデータを公開ログへ転記せず、権限のあるテスト担当者が
VALORANT診断の既存完了判定、おみくじポイント確認、除夜の鐘state表示・操作、Xmas
パネル復元、Valomap BAN表示を代表1件ずつ確認します。

## 新旧データの保持とロールバック

切替後は新pathだけをwriterとします。旧ファイルをfallbackとして自動読込する実装は、
split-brainと古いデータへの巻き戻りを招くため追加しません。

旧worktreeファイルと移行前バックアップは、最低でも7日間かつ正常な定期バックアップが
1回以上成功して復元確認が完了するまで、read-onlyの比較対象として保持します。旧pathを
deployで削除しません。

問題があればwriterを停止し、次の順で戻します。

1. 新path一式を追加バックアップし、障害調査用に保護する。
2. Unitと `.env` を移行前バックアップへ戻す。
3. 旧pathのSHA-256とJSON構文を確認する。
4. 旧pathを指す構成で一度だけ起動し、ログと件数を確認する。
5. 新pathのデータを旧pathへ自動でコピーしない。移行後に発生した更新を戻す必要が
   ある場合は、データ所有者の承認を得た個別リカバリーとして扱う。

コードのロールバックとデータのロールバックは独立して行います。Git checkoutや
リポジトリ内JSONをバックアップの代用にしません。

## Git追跡解除

追跡解除は、コード側の新保存先対応を先に本番投入し、新保存先で正常稼働、バックアップ、
復元試験、旧path非更新を確認した後の別PRでのみ実施します。実行前に本番JSONを再度
バックアップします。

将来の対象コマンド案は次のとおりです。今回は実行しません。

```bash
git rm --cached -- \
  data/valo_check_completed.json \
  data/2026_omikujii_points.json \
  data/2026_joya_state.json \
  data/xmas_gacha_state.json
git check-ignore -v -- \
  data/valo_check_completed.json \
  data/2026_omikujii_points.json \
  data/2026_joya_state.json \
  data/xmas_gacha_state.json
```

追跡解除PRをマージしたdeployでも旧ファイルを削除しません。ロールバック時も
`/var/lib/wankoro-bot` のJSONを保護し、Git版JSONを上書きしません。

## 開発環境とCI

開発環境は案Bの `${XDG_DATA_HOME:-$HOME/.local/share}/wankoro-bot`、またはテストごとの
一時directoryを使用します。CIは `tmp_path` と不存在時デフォルトだけで完結させ、
本番JSON、サンプルのユーザーID、Discord Tokenを必要としない構成を維持します。

個人データを含む本番JSONをリポジトリへ戻しません。通常はコードのデフォルト構造と
テストで初期schemaを定義できるため、runtimeサンプルJSONを追加しないことを推奨します。
運用ツールが実ファイルを必要とする場合だけ、実在ID・回答・nicknameを含まない
`*.example.json` をmaster dataとしてレビューします。

JSON不存在時は現在と同じ機能別デフォルトをmemoryへ読み込み、最初の正規保存時に
directoryとファイルを作ります。不正JSONは初期値で上書きせず起動・該当機能を失敗させ、
バックアップからの復旧を要求します。

追跡解除後はCIまたはpre-deploy checkで次を検証します。

```bash
test -z "$(git ls-files -- \
  data/valo_check_completed.json \
  data/2026_omikujii_points.json \
  data/2026_joya_state.json \
  data/xmas_gacha_state.json)"
git check-ignore -q -- data/valo_check_completed.json
```

加えて、commit前にruntime filename、Discord snowflakeらしいkey、回答・score・nicknameを
含む新規JSONがstagedされていないことを、人間が内容を公開せず確認します。

## 未確定事項と移行承認条件

- 本番 `.env` が現在解決している4ファイルの正確な絶対パス
- `JOYA_DATA_PATH` が追跡中ファイルと異なる可能性
- 現行 `valomap_bans.json` の有無と実パス
- バックアップ媒体、暗号化、保持期間、責任者
- 許容停止時間と作業日時
- production Unitを `.venv/bin/python` へ切り替える作業との実施順序
- `Group`を明示するか、`akitig`のprimary groupを継続するか
- log rotationとruntime backupの監視・失敗通知方法

これらが決まり、コード対応PR、復元試験、ロールバック演習が完了するまで、本番の通常
deployとGit追跡解除を行いません。
