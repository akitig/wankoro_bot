# systemdをプロジェクト固有venvへ移行する手順

## 目的と変更範囲

わんころBotのPythonバージョンやアプリケーション動作を変更せず、system Pythonへ
直接インストールされた依存関係ではなく、プロジェクトルートの`.venv`から起動します。
変更するUnit設定は`ExecStart`のPython実行ファイルだけです。

この文書を追加する変更では、本番Unit、`.env`、Botプロセス、runtime JSONを変更
しません。以下の本番操作は、レビューと作業承認を終えた後に運用者が実施します。

## 調査時点の構成

2026-07-31に確認したホストの`python3`はPython 3.10.12です。
`/etc/systemd/system/wankorobot.service`の有効な設定は次のとおりです。

```ini
[Unit]
Description=Discord Bot - WankoroBot（灯麗会）
After=network.target

[Service]
User=akitig
WorkingDirectory=/home/akitig/Desktop/Bot/Toureikai/Wankorobot
ExecStart=/usr/bin/python3 /home/akitig/Desktop/Bot/Toureikai/Wankorobot/main.py
Restart=always
RestartSec=5
EnvironmentFile=/home/akitig/Desktop/Bot/Toureikai/Wankorobot/.env
StandardOutput=append:/home/akitig/Desktop/Bot/Toureikai/Wankorobot/bot.log
StandardError=append:/home/akitig/Desktop/Bot/Toureikai/Wankorobot/bot.err

[Install]
WantedBy=multi-user.target
```

現在の`ExecStart`はsystem Pythonの`/usr/bin/python3`を使用しています。

## 本番移行前の準備と確認

プロジェクトルートへ移動し、現在のPythonが3.10系であることを確認します。
異なるバージョンが表示された場合はvenvを作らず、移行を中止してください。

```bash
cd /home/akitig/Desktop/Bot/Toureikai/Wankorobot
python3 --version
test "$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')" = "3.10"
```

`.venv`がGit管理対象外であることを確認し、仮想環境と依存関係を構築します。

```bash
git check-ignore -v .venv/
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python --version
.venv/bin/python -m pip check
```

Botを起動せずに構文とimportを確認します。import確認では本番Tokenを使用せず、
ダミーの必須IDをプロセスにだけ渡します。

```bash
.venv/bin/python -m compileall -q main.py cogs
env GUILD_ID=1 APPLICATION_ID=1 DISCORD_TOKEN=not-used \
  .venv/bin/python -c 'import importlib, main; [importlib.import_module(name) for name in main.COGS]'
git status --short
```

ここまででエラーがある場合、Unitは編集せず、`.venv`を作り直すか原因を解消します。

## systemd移行手順

Unitをタイムスタンプ付きでバックアップしてから編集します。

```bash
sudo cp -a /etc/systemd/system/wankorobot.service \
  "/etc/systemd/system/wankorobot.service.backup.$(date +%Y%m%d_%H%M%S)"
sudoedit /etc/systemd/system/wankorobot.service
```

次の1行だけを変更します。

```diff
-ExecStart=/usr/bin/python3 /home/akitig/Desktop/Bot/Toureikai/Wankorobot/main.py
+ExecStart=/home/akitig/Desktop/Bot/Toureikai/Wankorobot/.venv/bin/python /home/akitig/Desktop/Bot/Toureikai/Wankorobot/main.py
```

`User`、`WorkingDirectory`、`EnvironmentFile`、`Restart`、`RestartSec`、
`StandardOutput`、`StandardError`を含む他の設定は変更しません。保存後、差分を
確認してから、承認済みのメンテナンス時間帯に反映します。

```bash
sudo diff -u /etc/systemd/system/wankorobot.service.backup.YYYYMMDD_HHMMSS \
  /etc/systemd/system/wankorobot.service
sudo systemd-analyze verify /etc/systemd/system/wankorobot.service
sudo systemctl daemon-reload
sudo systemctl restart wankorobot.service
```

## 移行後の確認

再起動時刻を記録し、サービス、実プロセスのPython、起動ログを確認します。

```bash
sudo systemctl status wankorobot.service --no-pager
sudo systemctl show wankorobot.service -p MainPID -p ExecStart -p WorkingDirectory
pid="$(systemctl show wankorobot.service -p MainPID --value)"
readlink -f "/proc/$pid/exe"
sudo journalctl -u wankorobot.service --since "YYYY-MM-DD HH:MM:SS" --no-pager
```

`active (running)`であり、`/proc/<MainPID>/exe`がプロジェクトの
`.venv/bin/python`が参照するPython実行ファイルであること、Cogのロード失敗や
Python例外がないことを確認します。続いてDiscord上で既存コマンドとReaction Roleを
代表1件ずつ確認し、コマンド名、表示、権限、応答が移行前と同じであることを確認します。

## ロールバック

起動失敗、import失敗、またはDiscord上の挙動差があれば、追加変更を続けず、
バックアップUnitを復元します。

```bash
sudo cp -a /etc/systemd/system/wankorobot.service.backup.YYYYMMDD_HHMMSS \
  /etc/systemd/system/wankorobot.service
sudo systemctl daemon-reload
sudo systemctl restart wankorobot.service
sudo systemctl status wankorobot.service --no-pager
sudo journalctl -u wankorobot.service --since "YYYY-MM-DD HH:MM:SS" --no-pager
```

復元後の`ExecStart`が`/usr/bin/python3`であり、Botが従来どおり動作することを
確認します。`.venv`はUnitから参照されなくなるため、原因調査が終わるまで残して
構いません。削除してもruntime JSONや`.env`には影響しません。
