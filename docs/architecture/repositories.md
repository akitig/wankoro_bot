# Repository architecture

## 1. Repository層の目的

Repositoryは、永続化の詳細をServiceの業務判断から分離する境界です。現在の
runtime stateはJSONですが、読込・更新・atomic保存をRepositoryへ集約し、Serviceが
JSONのkeyや保存形式を直接扱わないようにします。この境界により、将来SQLiteへ
段階的に差し替える場合もDiscord側の処理から独立して変更できます。

Repositoryは保存先の`Path`だけを受け取り、Discordオブジェクトや`Config`には依存
しません。不要なABC、Protocol、DIコンテナは導入せず、実際に必要な永続化APIを
小さく保ちます。

## 2. 依存方向

```text
Cog
↓
Service
↓
Repository
↓
storage/json_store.py
```

依存は上から下への一方向です。下位層は上位層をimportしません。

## 3. 各層の責務

- **Cog**: Slash Command、イベント、Interaction、Button、ViewなどDiscord UIの境界を
  担い、業務処理をServiceへ委譲します。
- **Service**: 業務ルール、判定、Discord API操作、Embed生成、業務Loggingを担当し、
  永続状態の取得・更新・保存はRepository APIを利用します。
- **Repository**: 永続状態、JSON key、初期構造、読込・更新・保存、既存fallbackと
  例外伝播を所有します。raw state全体は必要以上に公開しません。
- **storage**: UTF-8 JSONの読込とatomic writeという汎用I/Oを提供します。不正JSONや
  I/O失敗の低レベルLoggingを担当します。

## 4. Repositoryごとの担当

- **JoyaRepository**: Guild/User state、回数、winner、panel、cooldownの永続化。
- **OmikujiRepository**: User IDごとのポイント、初期化、増減、下限、全resetの永続化。
- **XmasRepository**: 元nicknameとpanel message IDのruntime state永続化。
- **ValomapRepository**: VALORANTマップのBAN setと追加・解除・全解除の永続化。
- **ValocheckRepository**: 診断完了recordと質問・introのraw JSON読込。
- **BumpPanelRepository**: BUMP成功時刻、次回可能時刻、panel message IDの永続化。
- **AvailabilityPollRepository**: active poll、匿名集計用回答、抽選済み次回時刻、
  pause/skip制御の永続化。

BUMPパネルは成功時に次回可能時刻を計算し、その時刻まで単一taskで1回だけ待機します。
常時ポーリングやDISBOARDコマンドの自動実行、ユーザー代理Interactionは行いません。
Command IDが未設定の場合は、ユーザーへ`/bump`の手動選択を案内します。

Availability pollの公開Embedは人数と足跡だけを表示します。回答変更のためRepositoryには
User IDを文字列keyとして保存します。回答者情報は管理専用Discord監査ログにのみ表示し、
通常ログや公開pollには出しません。平日は夜、土日・日本の祝日は昼と夜のwindowを使い、
各次回時刻を一度だけ抽選・保存して単一scheduler taskで待機します。常時ポーリングは
行いません。pause、skip、抽選済みnext runは再起動後も復元されます。

景品CSV、確率、cutoff、スコア、Role判定、マップAPI取得などの業務ルールは、それぞれ
Serviceの責務です。

## 5. 禁止事項

Repositoryでは次を禁止します。

- `discord`、`Config`、Service、Cog、`aiohttp`、他Repositoryのimport
- 環境変数の読込や`get_config()`の呼出し
- Embed生成、Command処理、InteractionやRoleの操作
- storage層と同じ例外の重複Logging
- raw state全体の無制限な公開
- JSON本文、回答、score、User ID、nicknameなどprivate runtime dataのログ出力

また、CogとServiceは`storage.json_store`を直接importせず、ServiceはCogをimport
しません。

## 6. JSON互換性

Repositoryへの分離や内部整理だけを理由に、既存JSONのschema、field、key型、初期値を
変更してはいけません。ファイル不存在時のfallback、不正JSONの伝播またはfallback、
保存タイミングと順序も各機能の既存契約を維持します。

保存には`storage.json_store.save_json_atomic()`を使い、親ディレクトリ作成と失敗時の
既存ファイル保護を維持します。schema versionなどのfield追加は、互換性とmigrationが
別途設計された変更でのみ行います。

runtime JSONはdeployment-owned dataです。テストは`tmp_path`を使い、本番data pathを
読込・更新しません。runtime JSONやatomic writeの一時ファイルはGitへ追加しません。

## 7. SQLite移行時

SQLite実装へ移行する場合は、現在Serviceが利用するRepository APIを互換境界とします。
既存JSONからのmigration手順、transaction、同時実行時のlocking、失敗時のrollback、
schema version、移行前backupを事前に設計します。

原則としてJSONとSQLiteのdual-writeは避けます。検証可能なmigration、読込先の切替、
rollback確認という段階移行を行い、各段階で保存タイミングと業務上の原子性を確認します。
複数Repositoryを一括で置換せず、機能単位のreview可能な変更に分けます。

## 8. 新しいRepositoryを追加する条件

新しいRepositoryは、実際に永続化する状態があり、Serviceとの間に永続化境界が必要な
場合だけ追加します。将来使うかもしれない空Repositoryや、単なる形式統一を目的とした
Repositoryは作りません。追加時は小さいAPI、runtime data分類、JSON互換性、例外方針、
atomic保存、Architecture testを同時に定義します。
