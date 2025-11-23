# bot_line/line_bot.py
import os
import json
from flask import Flask, request, abort

from linebot import LineBotApi, WebhookHandler
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage,
    PostbackEvent, FlexSendMessage,
)

# 共通モジュール
from modules import (
    search_candidates, get_place_details,
    summarize_reviews, infer_store_type,
    infer_recommendation, classify_tags,
    upsert_store, build_page_url,
    build_photo_url, TYPE_ICON, SUBTYPE_ICON,
    build_rating_stars
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

    # ---- キャンセル ----
    if data == "CANCEL_SELECT":
        user_state.pop(user_id, None)
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage("キャンセルしました。別のお店名を入力してください！")
        )
        return

    # ---- 店選択 ----
    if data.startswith("SELECT_PLACE|"):
        _, place_id = data.split("|")

        details = get_place_details(place_id)
        summary = summarize_reviews(details.get("reviews", []))
        tags = classify_tags(details["name"], details.get("types", []), summary)
        store_type = infer_store_type(details.get("types", []), summary)
        recs = infer_recommendation(details.get("types", []), summary, details["name"])

        user_state[user_id] = {
            "mode": "await_save",
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

    # ---- 保存しない ----
    if data.startswith("SAVE_NO"):
        user_state.pop(user_id, None)
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage("了解しました。また別のお店を検索してくださいね！")
        )
        return

    # ---- 保存（感想なし） ----
    if data.startswith("SAVE_NO_COMMENT|"):
        _, place_id = data.split("|")
        state = user_state[user_id]

        page_id = upsert_store(
            state["details"], state["summary"],
            state["tags"], state["store_type"],
            state["recs"], ""
        )
        url = build_page_url(page_id)

        user_state.pop(user_id, None)
        line_bot_api.reply_message(event.reply_token, TextSendMessage(f"保存しました！\n{url}"))
        return

    # ---- 感想あり保存モードへ ----
    if data.startswith("SAVE_WITH_COMMENT|"):
        user_state[user_id]["mode"] = "waiting_comment"

        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage("📝 感想を入力してください。\n不要なら「スキップ」と送ってください。")
        )
        return


# ======================
# 4. Text Message
# ======================
@handler.add(MessageEvent, message=TextMessage)
def handle_text_message(event):
    user_id = event.source.user_id
    text = event.message.text.strip()

    # ---- 感想入力 ----
    if user_id in user_state and user_state[user_id]["mode"] == "waiting_comment":

        state = user_state[user_id]
        comment = "" if text.lower() == "スキップ" else text

        page_id = upsert_store(
            state["details"], state["summary"],
            state["tags"], state["store_type"],
            state["recs"], comment
        )
        url = build_page_url(page_id)

        user_state.pop(user_id, None)
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(f"保存しました！\n{url}")
        )
        return

    # ---- 通常検索 ----
    user_state.pop(user_id, None)

    candidates = search_candidates(text)
    if not candidates:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage("❌ 店舗が見つかりませんでした。")
        )
        return

    flex = build_candidates_flex(candidates)
    line_bot_api.reply_message(
        event.reply_token,
        FlexSendMessage(alt_text="候補一覧", contents=flex)
    )


# ======================
# Flask Run
# ======================
def start_line_bot():
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))

if __name__ == "__main__":
    start_line_bot()
