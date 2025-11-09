# 🐶 わんころBot — Discord Bot

**わんころBot** は、Discord サーバーのために設計された  
管理補助・参加導線・ゲームロール・VALORANT支援などを統合管理するマルチBotです。  

---

## 🌸 機能一覧

### 🏠 1. 新規参加者のウェルカムシステム
> ファイル：`cogs/welcome.py`

新規メンバーが参加すると、自動で専用チャンネル（`welcome-ユーザー名`）を作成し、  
Botが以下の手順でオンボーディングを行います。

- 会長の挨拶メッセージとクイズ形式の自己紹介（年齢／性別／活動時間帯）  
- ランダムに担当スタッフを自動アサイン  
- 管理者コマンド `/welcome @ユーザー` でも手動作成可  
- 完了後 `/ok` コマンドでチャンネルを `log` カテゴリへ移動  

#### 📘 関連コマンド
| コマンド | 内容 |
|-----------|------|
| `/welcome @ユーザー` | 指定メンバーのウェルカム部屋を作成 |
| `/ok` | 現在のチャンネルを `log` カテゴリに移動 |

---

### 🏷️ 2. リアクションロール管理
> ファイル：`cogs/reaction_roles.py`

リアクションを押すだけでロールが自動付与／削除される仕組み。  
管理者はスラッシュコマンドから、ロール選択メッセージを生成可能です。

#### ⚙️ 対応機能
- `/rrcreate`：ゲーム別ロール（VALO民／EFT民／SF6民など）  
- `/rrcreate_valorank`：VALORANTランクロール（Iron〜Radiant）  
- `/rrstatus`：登録済み絵文字とロールの一覧確認  
- `/rrreload`：`.env` の設定を再読み込み  

#### 🎮 絵文字とロール対応表
| 絵文字名 | ロール名 |
|-----------|-----------|
| :valo: | VALO民 |
| :tarkov: | EFT民 |
| :st6: | SF6民 |
| :mh: | モンハン民 |
| :ow2: | OW民 |
| :apex: | APEX民 |

---

### 🎯 3. VALORANT マップ管理コマンド群
> ファイル：`cogs/valomap.py`

Riot 公開APIを使用し、現在のVALORANTコンペマップを自動取得。  
マップのBAN／抽選／プール管理が可能です。

#### 🧩 主なコマンド
| コマンド | 機能 |
|-----------|------|
| `/valomap` | 全マップを一覧表示（BAN済みは❌打消し線） |
| `/valomappool` | BANされていないマップのみを表示 |
| `/valomapselect` | BANされていないマップからランダム選出 |
| `/valomapban` | ドロップダウンUIでBAN設定 |
| `/valomapclear` | すべてのBANを解除 |
| `/valocustom` | すべてのVALORANT系コマンドの説明を表示 |

BAN設定は `valomap_bans.json` に永続保存され、Bot再起動後も保持されます。

---

### ⚙️ 4. メイン実行構成
> ファイル：`main.py`

Bot全体のエントリーポイント。  
`.env` の設定を読み込み、以下の3つのCogを起動します。

```bash
cogs/welcome
cogs/reaction_roles
cogs/valomap
```

起動時には全スラッシュコマンドを自動同期し、  
権限エラーやロード失敗もコンソールに出力されます。

---

## 📦 セットアップ手順

### 1. 必要パッケージのインストール
```bash
pip install -U discord.py aiohttp python-dotenv
```

### 2. `.env` を設定
```env
DISCORD_TOKEN=xxxxxxxxxxxxxxxx
APPLICATION_ID=xxxxxxxxxxxxxxxx
GUILD_ID=xxxxxxxxxxxxxxxx

# 管理権限
ADMIN_ID=xxxxxxxxxxxxxxxx
MANAGER_ROLE_IDS=1111111111,2222222222

# ウェルカム担当ロール
ROLE_A=1111111111
ROLE_B=2222222222
ROLE_C=3333333333

# カテゴリ名・ログ設定
LEAVE_LOG_CHANNEL_ID=4444444444

# リアクションロール設定例
REACTION_ROLE_MESSAGE_ID=5555555555
RR_VALO民=123456789012345678:987654321098765432
```

---

## 🚀 実行方法

### ローカルで動かす
```bash
python3 main.py
```

### systemd サービスで常駐起動（例）
`/etc/systemd/system/wankorobot.service` に以下を作成：

```ini
[Unit]
Description=Discord Bot - WankoroBot（灯麗会）
After=network.target

[Service]
ExecStart=/usr/bin/python3 /home/akitig/Desktop/Bot/Toureikai/Wankorobot/main.py
WorkingDirectory=/home/akitig/Desktop/Bot/Toureikai/Wankorobot
Restart=always
User=akitig

[Install]
WantedBy=multi-user.target
```

有効化と起動：
```bash
sudo systemctl enable wankorobot
sudo systemctl start wankorobot
sudo journalctl -u wankorobot -f
```

---

## 🧠 技術概要

| 項目 | 内容 |
|------|------|
| 言語 | Python 3.10+ |
| ライブラリ | discord.py v2.x / aiohttp / python-dotenv |
| データ保存 | JSON・.env |
| 実行方式 | systemd 常駐 or CLI実行 |
| 構造 | Cog構成（`welcome` / `reaction_roles` / `valomap`） |

---

## 💬 作者・クレジット

**開発者：** あきと（[@akitig](https://akitiger.com)）  
**サーバー：** 秘密   
**Bot名：** わんころBot 🐶  

> “礼儀と遊び心を両立するサーバーのために。”

---

## 🕯️ ライセンス
MIT License  
© 2025 Akitig