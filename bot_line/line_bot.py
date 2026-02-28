# bot_line/line_bot.py
import os
import threading
import math
from flask import Flask, request, abort
from linebot.models import LocationMessage

from linebot import LineBotApi, WebhookHandler
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage,
    PostbackEvent, FlexSendMessage,
)

# 共通モジュール
from modules import (
    search_candidates, search_nearby, get_place_details,
    summarize_reviews, infer_store_type,
    infer_recommendation, classify_tags,
    upsert_store, build_page_url,
    build_photo_url, TYPE_ICON, SUBTYPE_ICON,
    build_rating_stars, calc_distance,
)

app = Flask(__name__)

LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# ======================
# 状態管理
# ======================
user_state = {}   # user_id : { mode, place_id, details, summary, tags, store_type, recs }


# ======================
# 1. 候補一覧 Flex（キャンセル付き）
# ======================
def build_candidates_flex(candidates):
    bubbles = []

    # 候補
    for c in candidates[:10]:
        bubble = {
            "type": "bubble",
            "size": "micro",
            "body": {
                "type": "box",
                "layout": "vertical",
                "spacing": "sm",
                "contents": [
                    {"type": "text", "text": c["name"], "weight": "bold", "size": "md", "wrap": True},
                    {"type": "text", "text": c["address"], "size": "sm", "color": "#777777", "wrap": True},
                ]
            },
            "footer": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {
                        "type": "button",
                        "style": "primary",
                        "height": "sm",
                        "action": {
                            "type": "postback",
                            "label": "このお店にする",
                            "data": f"SELECT_PLACE|{c['place_id']}"
                        }
                    }
                ]
            }
        }
        bubbles.append(bubble)

    # キャンセル
    cancel_bubble = {
        "type": "bubble",
        "size": "micro",
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {"type": "text", "text": "キャンセル", "weight": "bold", "size": "md"},
                {"type": "text", "text": "選択をやり直す場合はこちら", "size": "sm", "color": "#777777"},
            ]
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "button",
                    "style": "secondary",
                    "action": {
                        "type": "postback",
                        "label": "キャンセル",
                        "data": "CANCEL_SELECT"
                    }
                }
            ]
        }
    }

    bubbles.append(cancel_bubble)

    return {"type": "carousel", "contents": bubbles}


# ======================
# 2. 店舗情報 Flex（写真つき）
# ======================
def build_store_info_flex(details, summary, tags, store_type, recs, place_id):

    # アイコン
    type_icon = TYPE_ICON.get(store_type.get("type", "").lower(), "🍽")
    subtype_icon = SUBTYPE_ICON.get(store_type.get("subtype", ""), "✨")

    # タグとおすすめ
    tag_text = ", ".join(tags) if tags else "なし"
    rec_text = ", ".join(recs) if recs else "不明"

    # ★評価
    rating_stars = build_rating_stars(details.get("rating"))

    # 店舗写真
    photo_url = None
    photos = details.get("photos")
    if photos:
        photo_url = build_photo_url(photos[0].get("photo_reference"))

    bubble = {
        "type": "bubble",
        "size": "mega",
        "hero": {
            "type": "image",
            "url": photo_url or "https://via.placeholder.com/1024x512?text=No+Image",
            "size": "full",
            "aspectRatio": "20:13",
            "aspectMode": "cover",
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "md",
            "contents": [
                {"type": "text", "text": details["name"], "weight": "bold", "size": "xl", "wrap": True},
                {"type": "text", "text": details.get("formatted_address", "住所不明"), "size": "sm", "color": "#777777", "wrap": True},
                {"type": "text", "text": f"評価：{rating_stars}", "size": "sm", "wrap": True},
                {"type": "separator"},
                {"type": "text", "text": f"{type_icon} 店タイプ：{store_type.get('type')}", "wrap": True},
                {"type": "text", "text": f"{subtype_icon} サブタイプ：{store_type.get('subtype')}", "wrap": True},
                {"type": "text", "text": f"おすすめ：{rec_text}", "wrap": True},
                {"type": "text", "text": f"タグ：{tag_text}", "wrap": True},
                {"type": "separator"},
                {"type": "text", "text": summary, "size": "sm", "wrap": True},
            ]
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "button",
                    "style": "primary",
                    "action": {
                        "type": "postback",
                        "label": "感想を書いて保存する",
                        "data": f"SAVE_WITH_COMMENT|{place_id}"
                    }
                },
                {
                    "type": "button",
                    "style": "primary",
                    "color": "#4444FF",
                    "action": {
                        "type": "postback",
                        "label": "保存（感想なし）",
                        "data": f"SAVE_NO_COMMENT|{place_id}"
                    }
                },
                {
                    "type": "button",
                    "style": "secondary",
                    "action": {
                        "type": "postback",
                        "label": "保存しない",
                        "data": f"SAVE_NO|{place_id}"
                    }
                }
            ]
        }
    }

    return bubble


# ======================
# 3. Postback Handler
# ======================
@handler.add(PostbackEvent)
def handle_postback(event):
    user_id = event.source.user_id
    data = event.postback.data

    # ===========================================
    # 🔄【共通キャンセル処理】Postback版
    # ===========================================
    if data in ["CANCEL", "CANCEL_SELECT"]:
        user_state.pop(user_id, None)
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage("🔄 キャンセルしたよ！また気になるお店を教えてね💗")
        )
        return

    # ---- 店選択 ----
    if data.startswith("SELECT_PLACE|"):
        _, place_id = data.split("|")

        # （1）まず即返信（LINEはこれを待っている）
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="🔎 店舗情報を読み込み中…少々お待ちください!!")
        )

        # （2）重たい処理はスレッドで別実行
        threading.Thread(
            target=process_store_selection_async,
            args=(user_id, place_id)
        ).start()
        return

    # ---- 保存（感想なし） ----
    if data.startswith("SAVE_NO_COMMENT|"):
        # ① まず「保存中…」を即返す
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="📝 保存処理中…少々お待ちください!!")
        )

        # ② 処理はスレッドで実行（タイムアウト防止）
        threading.Thread(
            target=process_save_no_comment_async,
            args=(user_id,)
        ).start()
        return

    # ---- 保存しない ----
    if data.startswith("SAVE_NO"):
        user_state.pop(user_id, None)
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage("了解！また別のお店を検索してね！")
        )
        return

    # ---- 感想あり保存モードへ ----
    if data.startswith("SAVE_WITH_COMMENT|"):
        # セッションが切れている場合の安全チェック
        if user_id not in user_state:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage("❌ セッションが切れています。もう一度検索してください。")
            )
            return

        user_state[user_id]["mode"] = "waiting_comment"

        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage("📝 感想を入力してください！\n不要なら「スキップ」と送ってね！")
        )
        return


# ======================
# 4. Text Message
# ======================
@handler.add(MessageEvent, message=TextMessage)
def handle_text_message(event):
    user_id = event.source.user_id
    text = event.message.text.strip()

    # ===========================================
    # 🔄【共通キャンセル処理】Text版
    # ===========================================
    if text in ["キャンセル", "cancel", "やめる", "中止", "リセット"]:
        user_state.pop(user_id, None)
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage("🔄 キャンセルしたよ！またお店を検索してね💗")
        )
        return

    # ===========================================
    # ① 🔍検索（リッチメニュー） → 検索モードに入る
    # ===========================================
    if text.startswith("🔍検索"):
        user_state[user_id] = {"mode": "search"}
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage("🔍 店名で検索するよ！\n調べたいお店の名前を送ってね。")
        )
        return

    # ===========================================
    # 📍近くのおすすめ（リッチメニュー）
    # ===========================================
    if text.startswith("📍近くのおすすめ"):
        user_state[user_id] = {"mode": "recommend"}
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(
                "📍 おすすめ検索モードだよ！\n"
                "まず『位置情報』を送ってね。\n"
                "（＋ → 位置情報 → 現在地 を送信）"
            )
        )
        return

    # ===========================================
    # ② 感想入力モード（SAVE_WITH_COMMENT）
    # ===========================================
    if user_state.get(user_id, {}).get("mode") == "waiting_comment":
        comment = "" if text.lower() == "スキップ" else text

        # 即返信（LINEの制約）
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage("📝 保存処理中…少々お待ちください!!")
        )

        # 保存処理は非同期で実行
        threading.Thread(
            target=process_save_with_comment_async,
            args=(user_id, comment)
        ).start()
        return

    # ===========================================
    # ③ 通常の店名検索（モード＝search のとき）
    # ===========================================
    if user_state.get(user_id, {}).get("mode") == "search":
        query = text

        # 即返信
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage("🔎 店舗検索中…少々お待ちください!!")
        )

        # 非同期検索
        threading.Thread(
            target=process_candidate_search_async,
            args=(user_id, query)
        ).start()

        # 検索後はモードクリア（次の動作のため）
        user_state.pop(user_id, None)
        return

    # ===========================================
    # おすすめ検索：シチュエーション受信
    # ===========================================
    if user_state.get(user_id, {}).get("mode") == "recommend":
        state = user_state.get(user_id, {})

        # 位置情報がまだの場合
        if "lat" not in state:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(
                    "📍 まず位置情報を送ってね！\n"
                    "（＋ → 位置情報 → 現在地）"
                )
            )
            return

        # シチュエーションを保存
        situation = text
        user_state[user_id]["situation"] = situation

        # 即時応答
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage("🔎 おすすめ店舗を検索中…少々お待ちください！")
        )

        # 非同期処理
        threading.Thread(
            target=process_recommend_search_async,
            args=(user_id,)
        ).start()
        return

    # ===========================================
    # ④ モードがない場合 → 既存処理（店名検索として扱う）
    # ===========================================
    user_state.pop(user_id, None)

    query = text

    # 即返信
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage("🔎 店舗検索中…少々お待ちください!!")
    )

    # 非同期検索
    threading.Thread(
        target=process_candidate_search_async,
        args=(user_id, query)
    ).start()


# ======================
# 店舗名から候補一覧検索（Google検索 → Flex生成 → push_message）
# ======================
def process_candidate_search_async(user_id, query):
    candidates = search_candidates(query)

    if not candidates:
        line_bot_api.push_message(
            user_id,
            TextSendMessage(text="❌ 店舗が見つからなかったよ…もう一度試してね！")
        )
        return

    flex = build_candidates_flex(candidates)

    line_bot_api.push_message(
        user_id,
        FlexSendMessage(alt_text="候補一覧", contents=flex)
    )

# ======================
# 店舗選択後の本処理（AI解析 → Flex生成 → push_message）
# ======================
def process_store_selection_async(user_id, place_id):
    # 情報取得 & AI解析
    details = get_place_details(place_id)
    summary = summarize_reviews(details.get("reviews", []))
    tags = classify_tags(details["name"], details.get("types", []), summary)
    store_type = infer_store_type(details.get("types", []), summary)
    recs = infer_recommendation(details.get("types", []), summary, details["name"])

    # 状態保存
    user_state[user_id] = {
        "mode": "await_save",
        "place_id": place_id,
        "details": details,
        "summary": summary,
        "tags": tags,
        "store_type": store_type,
        "recs": recs,
    }

    # Flexを作る
    flex = build_store_info_flex(details, summary, tags, store_type, recs, place_id)

    # pushで最終結果を送信
    line_bot_api.push_message(
        user_id,
        FlexSendMessage(alt_text="店舗情報", contents=flex)
    )


# ======================
# コメントなし保存処理（Notion保存 → push_message）
# ======================
def process_save_no_comment_async(user_id):
    state = user_state.get(user_id)
    if not state:
        return

    page_id = upsert_store(
        state["details"], state["summary"],
        state["tags"], state["store_type"],
        state["recs"], ""
    )

    notion_url = build_page_url(page_id)

    line_bot_api.push_message(
        user_id,
        TextSendMessage(text=f"✔ 保存が完了しました！\n{notion_url}")
    )

    # 状態クリア
    user_state.pop(user_id, None)


# ======================
# コメントあり保存処理（Notion保存 → push_message）
# ======================
def process_save_with_comment_async(user_id, comment):
    state = user_state.get(user_id)
    if not state:
        return

    page_id = upsert_store(
        state["details"], state["summary"],
        state["tags"], state["store_type"],
        state["recs"], comment,
    )

    url = build_page_url(page_id)

    line_bot_api.push_message(
        user_id,
        TextSendMessage(text=f"✔ コメント付きで保存したよ！\n{url}")
    )

    user_state.pop(user_id, None)


# ======================
# 位置情報の受信ハンドラー
# ======================
@handler.add(MessageEvent, message=LocationMessage)
def handle_location(event):
    user_id = event.source.user_id

    lat = event.message.latitude
    lng = event.message.longitude

    # おすすめ検索モードでのみ受付
    if user_state.get(user_id, {}).get("mode") != "recommend":
        return

    # 位置情報保存
    user_state[user_id]["lat"] = lat
    user_state[user_id]["lng"] = lng

    # 次はシチュエーション入力
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(
            "📌 位置情報ありがとう！\n"
            "次にシチュエーションを教えてね。\n"
            "例：デート / 静か / 一人 / 友達 / 作業 など"
        )
    )


# ======================
# おすすめ検索本体（Nearby Search → AI解析 → Flex生成 → push_message）
# ======================
def process_recommend_search_async(user_id):
    state = user_state.get(user_id, {})
    if not state:
        return

    lat = state["lat"]
    lng = state["lng"]
    situation = state["situation"]

    # ① Google Places Nearby Search で近くの店を検索（半径500m）
    nearby_candidates = search_nearby(lat, lng, radius=500)

    if not nearby_candidates:
        line_bot_api.push_message(
            user_id,
            TextSendMessage("❌ 近くにおすすめできる店舗が見つからなかったよ…")
        )
        return

    ranked = []

    # ② 各店の詳細と推論（上位5件のみ）
    for c in nearby_candidates[:5]:
        details = get_place_details(c["place_id"])

        # GPT推論
        summary = summarize_reviews(details.get("reviews", []))
        tags = classify_tags(details["name"], details.get("types", []), summary)
        store_type = infer_store_type(details.get("types", []), summary)
        recs = infer_recommendation(details.get("types", []), summary, details["name"])

        # ③ Notion 保存（初回のみ）
        upsert_store(details, summary, tags, store_type, recs, "")

        # ④ スコア計算
        score = calc_recommend_score(details, store_type, tags, lat, lng, situation)

        # summaryもタプルに含めて使い回しを防ぐ（バグ修正）
        ranked.append((score, details, summary, tags, store_type, recs))

    # スコア順に並べる
    ranked.sort(reverse=True, key=lambda x: x[0])

    # ⑤ 上位3件を Flex Message で返す
    bubbles = []
    for _, details, summary, tags, store_type, recs in ranked[:3]:
        bubble = build_store_info_flex(
            details, summary, tags, store_type, recs, details["place_id"]
        )
        bubbles.append(bubble)

    line_bot_api.push_message(
        user_id,
        FlexSendMessage(
            alt_text="おすすめ店舗",
            contents={"type": "carousel", "contents": bubbles}
        )
    )

    # モードクリア
    user_state.pop(user_id, None)


# ======================
# スコア計算関数
# ======================
def calc_recommend_score(details, store_type, tags, user_lat, user_lng, situation):
    """
    details: get_place_details() の返却値
    store_type: infer_store_type() の返却値 { "type": "cafe", "subtype": "date" ... }
    tags: classify_tags() の返却値（リスト）
    user_lat, user_lng: ユーザー現在地
    situation: "デート" / "一人" / "静か" / "友達" / "作業" など
    """

    # ===============
    # ① Google評価 (0〜100)
    # ===============
    rating = details.get("rating", 0)  # 0〜5
    google_score = rating * 20         # 0〜100

    # ===============
    # ② 距離スコア (0〜100)
    # ===============
    lat = details["geometry"]["location"]["lat"]
    lng = details["geometry"]["location"]["lng"]

    # calc_distance は km を返すので ×1000 でメートルに変換（utils.py の重複実装を排除）
    d = calc_distance(user_lat, user_lng, lat, lng) * 1000

    if d <= 100:
        distance_score = 100
    elif d <= 300:
        distance_score = 80
    elif d <= 600:
        distance_score = 60
    elif d <= 1000:
        distance_score = 40
    else:
        distance_score = max(15, 10000 / d)

    # ===============
    # ③ シチュエーション適性スコア (0〜100)
    # ===============
    subtype = store_type.get("subtype", "")

    situation_map = {
        "デート": ["date", "romantic", "couple"],
        "静か": ["quiet", "study", "relax"],
        "作業": ["work", "study", "focus"],
        "一人": ["solo", "casual", "quiet"],
        "友達": ["friends", "group", "fun"]
    }

    if subtype in situation_map.get(situation, []):
        situation_score = 100
    else:
        situation_score = 50 if situation in subtype else 30

    # ===============
    # ④ あなたの個人評価 (0〜100) → NotionDBの値があれば付与
    # ===============
    user_score_raw = details.get("user_rating", 0)
    user_score = user_score_raw * 20  # 1〜5 → 20〜100

    # ===============
    # ⑤ 店タイプ一致スコア (0〜100)
    # ===============
    type_score = 100 if store_type.get("type") in tags else 50

    # ===============
    # ⑥ 最終スコア
    # ===============
    total_score = (
        google_score * 0.40 +
        situation_score * 0.30 +
        distance_score * 0.15 +
        user_score * 0.10 +
        type_score * 0.05
    )

    return total_score


# ======================
# LINE Webhook エンドポイント
# ======================
@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature")

    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except Exception as e:
        print("Error in callback:", e)
        abort(400)

    return "OK"


# ======================
# Flask Run
# ======================
def start_line_bot():
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))

if __name__ == "__main__":
    start_line_bot()
