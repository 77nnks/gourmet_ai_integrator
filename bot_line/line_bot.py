# bot_line/line_bot.py
import os
import json
from flask import Flask, request, abort

from linebot import LineBotApi, WebhookHandler
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage,
    PostbackEvent, FlexSendMessage, QuickReply, QuickReplyButton,
    PostbackAction
)

# 共通モジュール
from modules import (
    search_candidates, get_place_details,
    summarize_reviews, infer_store_type, infer_recommendation, classify_tags,
    upsert_store, build_page_url
)

app = Flask(__name__)

LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)


# =====================================================
#  会話状態を保存（最小限の簡易ステート管理）
# =====================================================
user_state = {}  # user_id : { "mode": "waiting_comment", "place_id": "xxxx" }


# =====================================================
#  Webhook
# =====================================================
@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get("X-Line-Signature")
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except Exception as e:
        print("ERROR:", e)
        abort(400)

    return "OK"


# =====================================================
#  Flex：候補リスト
# =====================================================
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
                        "wrap": True,
                        "color": "#777777"
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
                            "label": "この店にする",
                            "data": f"SELECT_PLACE|{c['place_id']}"
                        }
                    }
                ]
            }
        }
        bubbles.append(bubble)

    return {
        "type": "carousel",
        "contents": bubbles
    }


# =====================================================
#  Flex：最終結果（登録完了）
# =====================================================
def build_result_flex(details, summary, tags, store_type, recs, notion_url):

    like_tags = ", ".join(tags) if tags else "なし"
    rec_text = ", ".join(recs) if recs else "不明"

    bubble = {
        "type": "bubble",
        "size": "mega",
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
                    "wrap": True
                },
                {
                    "type": "text",
                    "text": details.get("formatted_address", "住所不明"),
                    "size": "sm",
                    "wrap": True,
                    "color": "#666666"
                },
                {
                    "type": "separator"
                },
                {
                    "type": "text",
                    "text": f"店タイプ：{store_type.get('type','')}",
                    "size": "md",
                    "wrap": True
                },
                {
                    "type": "text",
                    "text": f"サブタイプ：{store_type.get('subtype','')}",
                    "size": "sm",
                    "wrap": True
                },
                {
                    "type": "text",
                    "text": f"おすすめ：{rec_text}",
                    "wrap": True
                },
                {
                    "type": "text",
                    "text": f"タグ：{like_tags}",
                    "wrap": True
                },
                {
                    "type": "separator"
                },
                {
                    "type": "text",
                    "text": summary,
                    "wrap": True,
                    "size": "sm"
                }
            ]
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "button",
                    "style": "link",
                    "action": {
                        "type": "uri",
                        "label": "Notion を開く",
                        "uri": notion_url
                    }
                }
            ]
        }
    }

    return bubble


# =====================================================
#  Postback（店が選ばれた）
# =====================================================
@handler.add(PostbackEvent)
def handle_postback(event):

    data = event.postback.data

    # -------------------------------
    # 店選択 SELECT_PLACE
    # -------------------------------
    if data.startswith("SELECT_PLACE"):
        _, place_id = data.split("|")

        # 感想待ちモードへ
        user_state[event.source.user_id] = {
            "mode": "waiting_comment",
            "place_id": place_id
        }

        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(
                text="📝 感想があれば入力してください。\n不要なら「スキップ」と入力してください。"
            )
        )


# =====================================================
#  メッセージ（テキスト）
# =====================================================
@handler.add(MessageEvent, message=TextMessage)
def handle_text_message(event):

    user_id = event.source.user_id
    text = event.message.text.strip()

    # ------------------------
    # 1. 感想入力ステップ
    # ------------------------
    if user_id in user_state and user_state[user_id]["mode"] == "waiting_comment":

        place_id = user_state[user_id]["place_id"]
        comment = "" if text.lower() == "スキップ" else text

        # 状態クリア
        del user_state[user_id]

        # ---- AI + Notion 登録 ----
        details = get_place_details(place_id)

        summary = summarize_reviews(details.get("reviews", []))
        tags = classify_tags(details["name"], details.get("types", []), summary)
        store_type = infer_store_type(details.get("types", []), summary)
        recs = infer_recommendation(details.get("types", []), summary, details["name"])

        page_id = upsert_store(details, summary, tags, store_type, recs, comment)
        notion_url = build_page_url(page_id)

        result_flex = build_result_flex(details, summary, tags, store_type, recs, notion_url)

        line_bot_api.reply_message(
            event.reply_token,
            FlexSendMessage(alt_text="登録が完了しました", contents=result_flex)
        )
        return

    # ------------------------
    # 2. 通常検索モード
    # ------------------------
    query = text
    candidates = search_candidates(query)

    if not candidates:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="❌ 店舗が見つかりませんでした。")
        )
        return

    flex = build_candidates_flex(candidates)

    line_bot_api.reply_message(
        event.reply_token,
        FlexSendMessage(alt_text="候補一覧", contents=flex)
    )


# =====================================================
#  Flask RUN
# =====================================================
def start_line_bot():
    app.run(host="0.0.0.0", port=8080)


if __name__ == "__main__":
    start_line_bot()
