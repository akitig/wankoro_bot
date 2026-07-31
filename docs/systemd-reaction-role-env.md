# systemd向けReaction Role環境変数の移行手順

## 背景と原因

`wankorobot.service`はsystemdの`EnvironmentFile`として`.env`を読み込みます。
systemdが環境変数名として受け付けるのは、ASCIIの英字・数字・アンダースコアで
構成された名前です。従来のReaction Role設定には日本語を含むキーがあったため、
systemdはそれらを無効な代入として無視し、次の警告を記録していました。

```text
Ignoring invalid environment assignment
```

一方、Botの起動後には`python-dotenv`が同じ`.env`を読み込みます。
`python-dotenv`では日本語を含む従来キーも読み込めたため、systemdが拒否した設定を
Pythonプロセス側で偶然補完できていました。この挙動に依存すると、systemdの警告が
残るうえ、起動方法によってReaction Role設定の読込結果が変わります。

## キー名の移行対応表

Discord上のロール名や絵文字名は変更せず、環境変数のキー名だけを次のように
ASCIIへ変更します。

| 旧キー | 新キー |
|---|---|
| `RR_VALO民` | `RR_GAME_VALO` |
| `RR_EFT民` | `RR_GAME_EFT` |
| `RR_SF6民` | `RR_GAME_SF6` |
| `RR_モンハン民` | `RR_GAME_MONSTER_HUNTER` |
| `RR_OW民` | `RR_GAME_OW2` |
| `RR_APEX民` | `RR_GAME_APEX` |

値の`emoji_id:role_id`は一切変更しません。たとえば、次の移行では右辺を
完全に同一のまま維持します。

```dotenv
# 移行前
RR_VALO民=emoji_id:role_id

# 移行後
RR_GAME_VALO=emoji_id:role_id
```

## 本番`.env`の移行手順

以下はレビューと作業承認後に、VPSのリポジトリルートで運用者が実施する手順です。
本PRでは`.env`、systemd、稼働中サービスを変更しません。

### 1. `.env`をバックアップする

現在の所有者・権限を維持したバックアップを作成します。

```bash
cp -a .env ".env.backup.$(date +%Y%m%d_%H%M%S)"
```

バックアップが存在し、元の`.env`と同じく第三者から読み取れない権限であることを
確認します。バックアップにもTokenが含まれるため、Gitへ追加してはいけません。

```bash
ls -l .env .env.backup.*
```

### 2. vimでキー名だけを置換する

```bash
vim .env
```

vimのコマンドモードで、次の置換を1行ずつ実行します。各パターンは行頭と`=`までを
対象にしているため、右辺の`emoji_id:role_id`を変更しません。

```vim
:%s/^RR_VALO民=/RR_GAME_VALO=/
:%s/^RR_EFT民=/RR_GAME_EFT=/
:%s/^RR_SF6民=/RR_GAME_SF6=/
:%s/^RR_モンハン民=/RR_GAME_MONSTER_HUNTER=/
:%s/^RR_OW民=/RR_GAME_OW2=/
:%s/^RR_APEX民=/RR_GAME_APEX=/
```

差分を目視確認してから保存します。

```vim
:wq
```

旧キーと新キーを併存させてはいけません。併存すると、Botが同じ絵文字IDに対する
設定を複数回読み込み、環境変数の走査順によって後の値で上書きされる可能性が
あります。6項目すべてについて、旧キーがなく新キーが1件だけ存在する状態にします。

値を表示せずキー名だけを確認する場合は、次を使用します。

```bash
awk -F= '/^[^#[:space:]][^=]*=/{print $1}' .env | sort
```

### 3. 承認済み手順でサービスを再起動する

`.env`の確認後、通常の変更管理・作業承認に従って再起動します。

```bash
sudo systemctl restart wankorobot.service
sudo systemctl status wankorobot.service --no-pager
```

`active (running)`であることを確認します。起動に失敗した場合はそれ以上の操作を
続けず、ログを確認し、必要に応じてバックアップから`.env`を復元します。

## 再起動後の確認

### systemd警告が0件であること

再起動した時刻以降のjournalを対象に確認します。`YYYY-MM-DD HH:MM:SS`は実際の
再起動直前の時刻へ置き換えます。

```bash
journalctl -u wankorobot.service \
  --since "YYYY-MM-DD HH:MM:SS" \
  --no-pager |
grep -F -c "Ignoring invalid environment assignment"
```

出力が`0`であることを確認します。過去のjournalには移行前の警告が残るため、
必ず`--since`で今回の再起動以降に範囲を限定します。

あわせて、Reaction Roleの読込失敗やPython例外がないことを確認します。

```bash
journalctl -u wankorobot.service \
  --since "YYYY-MM-DD HH:MM:SS" \
  --no-pager
```

### Discord上の動作確認

対象のReaction Roleメッセージで、ゲーム用の6絵文字をそれぞれ確認します。

1. 絵文字へリアクションを追加し、従来と同じロールが付与されること。
2. 同じリアクションを削除し、付与されたロールが解除されること。
3. Discord上のロール名、絵文字、メッセージ表示が移行前と変わっていないこと。
4. VALORANTランク用Reaction Roleにも影響がないこと。

systemd警告が0件であり、Discord上のロール付与・解除が従来どおり動作することを
確認できた時点で移行完了です。
