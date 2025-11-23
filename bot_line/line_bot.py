# bot_line/line_bot.py
import os
import json
from flask import Flask, request, abort

from linebot import LineBotApi, WebhookHandler
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage,
    PostbackEvent, FlexSendMessage
)

# 共通モジュール
from modules import (
    search_candidates, get_place_details,
    summarize_reviews, infer_store_type, infer_recommendation,
    classify_tags, upsert_store, build_page_url,
    build_photo_url, TYPE_ICON, SUBTYPE_ICON, build_rating_stars
)

app = Flask(__name__)

LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)


# ======================
# LINE Webhook
# ======================
@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature')
    body = request.get_data(as_text=True)

    if signature is None:
        abort(400, "X-Line-Signature missing")

    try:
        handler.handle(body, signature)
    except Exception as e:
        print("LINE ERROR:", e)
        abort(400)

    return "OK", 200


# ======================
# 状態管理
# ======================
user_state = {}   # user_id : { mode, place_id, details... }


# ======================
# Flex：候補一覧
# ======================
def build_candidates_flex(candidates):
    bubbles = []

    for c in candidates[:10]:
        bubble = {
            "type": "bubble",
            "size": "micro",
            "body": {
                "type": "box",
                "layout": "vertical",
                "spacing": "sm",
                "contents": [
                    {
                        "type": "text",
                        "text": c["name"],
                        "weight": "bold",
                        "size": "md",
                        "wrap": True
                    },
                    {
                        "type": "text",
                        "text": c["address"],
                        "size": "sm",
                        "color": "#777777",
                        "wrap": True
                    }
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

    return {"type": "carousel", "contents": bubbles}


# ======================
# Flex：店舗情報（AI解析＋写真＋評価＋アイコン）
# ======================
def build_store_info_flex(details, summary, tags, store_type, recs, place_id):

    # 🔹 写真
    photos = details.get("photos", [])
    photo_url = "https://via.placeholder.com/800x500?text=No+Image"
    if photos:
        ref = photos[0].get("photo_reference")
        if ref:
            photo_url = build_photo_url(ref)

    # 🔹 店タイプアイコン
    t = store_type.get("type", "")
    type_icon = TYPE_ICON.get(t.lower(), "🍽️")

    # 🔹 サブタイプアイコン
    subt = store_type.get("subtype", "")
    subtype_icon = "✨"
    for k, v in SUBTYPE_ICON.items():
        if k in subt:
            subtype_icon = v
            break

    # 🔹 ★評価
    rating = details.get("rating")
    rating_text = build_rating_stars(rating)

    tag_text = ", ".join(tags) if tags else "なし"
    rec_text = ", ".join(recs) if recs else "不明"

    bubble = {
        "type": "bubble",
        "hero": {
            "type": "image",
            "url": photo_url,
            "size": "full",
            "aspectRatio": "20:13",
            "aspectMode": "cover"
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "md",
            "contents": [
                {
                    "type": "text",
                    "text": details["name"],
                    "weight": "bold",
                    "size": "xl",
                    "wrap": True,
                },
                {
                    "type": "text",
                    "text": details.get("formatted_address", "住所不明"),
                    "size": "sm",
                    "color": "#777777",
                    "wrap": True,
                },
                {
                    "type": "text",
                    "text": rating_text,
                    "size": "md",
                    "wrap": True,
                    "margin": "md"
                },
                {"type": "separator"},
                {
                    "type": "text",
                    "text": f"{type_icon} 店タイプ：{t}",
                    "wrap": True,
                    "margin": "md"
                },
                {
                    "type": "text",
                    "text": f"{subtype_icon} サブタイプ：{subt}",
                    "wrap": True
                },
                {
                    "type": "text",
                    "text": f"おすすめ：{rec_text}",
                    "wrap": True
                },
                {
                    "type": "text",
                    "text": f"タグ：{tag_text}",
                    "wrap": True
                },
                {"type": "separator"},
                {
                    "type": "text",
                    "text": summary,
                    "size": "sm",
                    "wrap": True
                }
            ]
        },
        "footer": {
            "type": "box",
            "layout": "horizontal",
            "contents": [
                {
                    "type": "button",
                    "style": "primary",
                    "action": {
                        "type": "postback",
                        "label": "感想を書く",
                        "data": f"SAVE_YES|{place_id}"
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
# Postback Event
# ======================
@handler.add(PostbackEvent)
def handle_postback(event):
    user_id = event.source.user_id
    data = event.postback.data

    # --- 店選択 ---
    if data.startswith("SELECT_PLACE"):
        _, place_id = data.split("|")

        # AI解析
        details = get_place_details(place_id)
        summary = summarize_reviews(details.get("reviews", []))
        tags = classify_tags(details["name"], details.get("types", []), summary)
        store_type = infer_store_type(details.get("types", []), summary)
        recs = infer_recommendation(details.get("types", []), summary, details["name"])

        # 状態保持
        user_state[user_id] = {
            "mode": "await_save_decision",
            "place_id": place_id,
            "details": details,
            "summary": summary,
            "tags": tags,
            "store_type": store_type,
            "recs": recs,
        }

        flex = build_store_info_flex(details, summary, tags, store_type, recs, place_id)
        line_bot_api.reply_message(
            event.reply_token,
            FlexSendMessage(alt_text="店舗情報", contents=flex)
        )
        return

    # --- 保存しない ---
    if data.startswith("SAVE_NO"):
        user_state.pop(user_id, None)
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="了解しました。また別のお店を検索してくださいね！")
        )
        return

    # --- 保存する → 感想入力 ---
    if data.startswith("SAVE_YES"):
        user_state[user_id]["mode"] = "waiting_comment"

        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="📝 感想を入力してください。\n不要な場合は「スキップ」と送ってください。")
        )
        return


# ======================
# Text メッセージ
# ======================
@handler.add(MessageEvent, message=TextMessage)
def handle_text_message(event):

    user_id = event.source.user_id
    text = event.message.text.strip()

    # --- 感想入力 ---
    if user_id in user_state and user_state[user_id]["mode"] == "waiting_comment":

        state = user_state[user_id]
        details = state["details"]
        summary = state["summary"]
        tags = state["tags"]
        store_type = state["store_type"]
        recs = state["recs"]

        comment = "" if text.lower() == "スキップ" else text

        # Notion 保存
        page_id = upsert_store(details, summary, tags, store_type, recs, comment)
        notion_url = build_page_url(page_id)

        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=f"保存しました！\n{notion_url}")
        )

        user_state.pop(user_id, None)
        return

    # --- 通常検索 ---
    user_state.pop(user_id, None)

    query = text
    candidates = search_candidates(query)

    if not candidates:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="❌ 店舗が見つかりませんでした。")
        )
        return

    # 丁寧フロー
    messages = [
        TextSendMessage(text="🔎 どのお店にしますか？"),
        FlexSendMessage(
            alt_text="候補一覧",
            contents=build_candidates_flex(candidates)
        )
    ]

    line_bot_api.reply_message(event.reply_token, messages)


# ======================
# Flask RUN
# ======================
def start_line_bot():
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))


if __name__ == "__main__":
    start_line_bot()
