# CLAUDE.md — Gourmet AI Integrator

このファイルは、このコードベースで作業するAIアシスタント（Claudeなど）向けのガイドを提供します。

---

## プロジェクト概要

**Gourmet AI Integrator** は、以下を統合したマルチプラットフォームのレストラン発見・管理ボットです：

- **Discord** と **LINE** のチャットインターフェース
- **Google Places API** によるレストランデータ取得
- **OpenAI GPT-4o-mini** によるAI分析・情報補完
- **Notion** による永続的なレストランデータベース

ユーザーはDiscordまたはLINE上でレストランを検索し、AI生成のサマリーやタグを取得してNotionに保存、位置情報に基づいたおすすめを受け取ることができます。

---

## リポジトリ構成

```
gourmet_ai_integrator/
├── main.py                    # エントリーポイント：Discord（スレッド）+ LINE（Flask）を起動
├── Procfile                   # デプロイ設定（Railway/Heroku）: `web: python main.py`
├── requirements.txt           # Pythonの依存パッケージ（バージョン未固定）
│
├── bot_discord/
│   └── discord_bot.py         # Discordスラッシュコマンドボット（266行）
│
├── bot_line/
│   └── line_bot.py            # LINE Webhook用 Flaskサーバー（725行）
│
└── modules/
    ├── __init__.py             # モジュール関数のバレルエクスポート
    ├── ai_processing.py        # OpenAI GPT-4o-mini ラッパー
    ├── google_api.py           # Google Places / Geocoding API呼び出し
    ├── notion_client.py        # Notion データベース CRUD 操作
    └── utils.py                # 共有ヘルパー（アイコン、距離計算、フォーマット）
```

---

## アーキテクチャ

### 起動フロー（`main.py`）

1. Discordボットを**デーモンスレッド**で起動（`start_discord_bot()`）
2. LINE Flask アプリを**メインスレッド**で起動（ポートは`PORT`環境変数、デフォルト`8080`）
3. 両ボットは同じ `modules/` レイヤーを共有

### モジュールの責務

| モジュール | 責務 |
|---|---|
| `ai_processing.py` | 全OpenAI API呼び出し。構造化JSONを返す |
| `google_api.py` | Google Places テキスト検索・詳細取得、Geocoding |
| `notion_client.py` | Notionデータベースの読み書き（`place_id`でupsert） |
| `utils.py` | 写真URL生成、店舗タイプアイコン、評価星表示、料金テキスト、Haversine距離計算 |

### データフロー（レストランを保存する場合）

```
ユーザーコマンド → Google Places 検索 → 候補選択
    → Google Places 詳細取得 → OpenAI 分析（サマリー・タイプ・おすすめ・タグ）
    → Notion upsert（place_idで重複防止）
    → ユーザーへ確認メッセージ
```

---

## 主要機能

### Discord ボット（`bot_discord/discord_bot.py`）

**スラッシュコマンド：**
- `/save <query> [comment]` — レストランを検索し、AI情報を付加してNotionに保存
- `/nearby <location> [conditions]` — 指定場所の近くにある保存済みレストランを距離・評価・条件でスコアリングして表示

**UIパターン：**
- Discord `app_commands`（スラッシュコマンド）
- `discord.ui.View` + `discord.ui.Button` による候補選択UI
- `discord.Embed` によるリッチな結果表示
- 長時間処理のタイムアウト回避に `interaction.response.defer()` を使用

### LINE ボット（`bot_line/line_bot.py`）

**会話モード（ユーザーごとのステートマシン）：**
- `search` — テキストによるレストラン検索
- `recommend` — 位置情報ベースのおすすめ（GPS座標を受け付け）
- `await_save` — ユーザーの保存確認待ち
- `waiting_comment` — 保存前のコメント入力待ち

**状態管理：**
```python
user_state = {}  # user_idをキーとするDict。モードと保留中データを保持
```

**UIパターン：**
- LINE Flex Messages（Bubble + Carousel）によるリッチレイアウト
- Postbackアクションによるボタン駆動の状態遷移
- Webhookタイムアウト防止のため、スレッド内で `push_message` を使用
- LINEアプリからのGPS座標（位置情報メッセージ）に対応

---

## 外部サービスと必要な環境変数

全シークレットは `python-dotenv` でリポジトリ外の `.env` ファイルから読み込みます。

| 変数名 | サービス | 使用ファイル |
|---|---|---|
| `GOOGLE_API_KEY` | Google Places + Geocoding | `google_api.py` |
| `OPENAI_API_KEY` | OpenAI GPT-4o-mini | `ai_processing.py` |
| `DISCORD_BOT_TOKEN` | Discord API | `discord_bot.py` |
| `LINE_CHANNEL_ACCESS_TOKEN` | LINE Messaging API | `line_bot.py` |
| `LINE_CHANNEL_SECRET` | LINE Webhook検証 | `line_bot.py` |
| `NOTION_API_KEY` | Notion API | `notion_client.py` |
| `MAIN_DATABASE_ID` | Notionデータベース対象 | `notion_client.py` |
| `PORT` | Flaskサーバーポート | `main.py`（デフォルト：`8080`） |

---

## Notion データベーススキーマ

Notionデータベース（`MAIN_DATABASE_ID`）は以下のプロパティ構造を持ちます：

| プロパティ名 | 型 | 説明 |
|---|---|---|
| 店名 | Title | レストラン名 |
| 住所 | Rich Text | 住所 |
| 営業時間 | Rich Text | 営業時間 |
| 感想 | Rich Text | ユーザーコメント |
| サブタイプ | Rich Text | 店舗サブタイプ（AI推定） |
| 印象 | Rich Text | AIが生成した印象サマリー |
| 評価 | Number | Googleの評価（0〜5） |
| 料金 | Number | Googleの価格レベル（0〜4） |
| lat / lng | Number | 緯度・経度座標 |
| URL | URL | Google マップ URL |
| 公式サイト | URL | 公式ウェブサイト |
| 店タイプ | Select | 店舗タイプ（AI推定） |
| Tags | Multi-select | AIが生成したタグ |
| おすすめメニュー | Rich Text | AIが推薦するメニュー |
| place_id | Rich Text | Google Place ID（ユニークキーとして使用） |

---

## AI処理（`ai_processing.py`）

全OpenAI呼び出しは `gpt-4o-mini` を使用し、JSON出力を強制します（`response_format={"type": "json_object"}`）。

| 関数 | 入力 | 出力（JSONキー） |
|---|---|---|
| `summarize_reviews(reviews)` | レビューテキストのリスト | `positive`, `negative`, `conclusion` |
| `infer_store_type(types, summary)` | Google typesリスト + サマリー | `store_type`, `sub_type` |
| `infer_recommendation(types, summary, name)` | 上記 + 店名 | `recommendations`（3件のリスト） |
| `classify_tags(name, types, summary)` | 上記 | `tags`（文字列のリスト） |

全関数の共通パターン：プロンプトを構築 → `_request_json(prompt)` を呼び出す → パース済みdictを返す

---

## 規約とパターン

### 言語使い分け

- **UIテキスト**：日本語（ユーザー向けメッセージ、Notionフィールド名）
- **コード**：英語（関数名、変数名、コメントは主に英語）
- **絵文字**：ユーザー向けメッセージで積極的に使用（📍, 🔍, 🍽️, ☕, 🍣 など）

### 命名規則

- 関数・変数は Python の `snake_case`
- 定数はモジュールレベルのdict（アイコンマップ、タグマップなど）
- プライベートヘルパーはアンダースコアプレフィックス：`_request_json`, `_headers`

### 非同期処理 / スレッディング

- Discord：長時間操作の前に `await interaction.response.defer()` を呼び出し、処理後に `interaction.followup.send()` を使用
- LINE：Webhookタイムアウトを超える操作は `threading.Thread(target=...).start()` でバックグラウンド実行
- Discordボット自体は `main.py` からデーモンスレッドとして起動

### エラーハンドリング

- APIエラーはボットレイヤーでキャッチし、ユーザーフレンドリーなメッセージを返す
- `find_page_by_place_id` でNotionの重複登録を防止（冪等なupsert）
- キャンセルコマンド時の状態クリーンアップ：`user_state.pop(user_id, None)`

### Google Places

- 検索は `language=ja`（日本語結果）を使用
- 詳細取得に含まれるフィールド：`name`, `formatted_address`, `geometry`, `rating`, `opening_hours`, `price_level`, `reviews`, `types`, `url`, `website`, `photos`
- 写真は `utils.get_photo_url(photo_reference, max_width=400)` で取得

---

## 開発ワークフロー

### ローカル実行

1. 必要な環境変数をすべて記載した `.env` を配置（上記テーブル参照）
2. 依存パッケージをインストール：
   ```bash
   pip install -r requirements.txt
   ```
3. アプリを起動：
   ```bash
   python main.py
   ```
4. LINE ボットの場合：ngrokなどでローカルFlaskサーバーを公開し、LINE DevelopersコンソールでWebhook URLを設定

### デプロイ

`Procfile` により **Railway** または **Heroku** へデプロイ：
```
web: python main.py
```
- プラットフォームのダッシュボードで全環境変数を設定
- LINE WebhookのURLは公開アクセス可能である必要がある

### 新機能を追加する場合

- **Discordコマンドを追加**：`discord_bot.py` に新しい `@tree.command` を追加し、長時間操作には `defer()` を使用
- **LINEフローを追加**：`user_state` に新しいモード文字列を追加し、`handle_message` 関数でハンドリング
- **AI分析を追加**：`ai_processing.py` に `_request_json` パターンに従った関数を追加
- **Notionフィールドを追加**：`notion_client.py` の `upsert_store` 関数内のプロパティdictを更新

### テストについて

現在、自動テストは存在しません。機能追加時は：
- 各チャットインターフェースから手動テストを実施
- Notion書き込みはNotionデータベースを直接確認
- `utils.py` や `ai_processing.py` の純粋関数に対して `pytest` テストの追加を検討

---

## 依存パッケージ

```
Flask            # LINE Webhook用 Webフレームワーク
line-bot-sdk     # LINE Messaging API クライアント
discord.py       # Discord ボットフレームワーク
requests         # Google/Notion API 用 HTTP クライアント
openai           # OpenAI API クライアント
python-dotenv    # .envファイルの読み込み
```

`requirements.txt` ではバージョンを**固定していません**。再現性が重要になった場合はバージョン固定を検討してください。

---

## よくあるハマりポイント

1. **LINE Webhookタイムアウト**：LINEは3秒以内の応答を要求します。AI処理やNotion書き込みなどの長時間操作は `reply_message` ではなく `push_message` を使ってバックグラウンドスレッドで実行してください。

2. **Discord インタラクションタイムアウト**：3秒以内に `defer()` を呼び出す必要があります。処理後は `followup.send()` を使用してください。

3. **Notionの重複防止**：保存前には必ず `find_page_by_place_id` を使用してください。upsert関数が挿入か更新かを自動判定します。

4. **Google Places 写真URL**：写真URLにはAPIキーが必要です。`utils.get_photo_url()` を使用し、URLを手動で構築しないでください。

5. **PORT変数**：Railway/HerokuはPORTを動的に注入します。デフォルトの`8080`はローカル開発専用です。

6. **日本語ロケール**：Google Placesのクエリは `language=ja` を使用しています。変更すると、日本語レビューテキストを前提としたAI分析プロンプトに影響します。
