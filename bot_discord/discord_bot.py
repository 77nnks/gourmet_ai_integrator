# bot_discord/discord_bot.py

import os
import json
import discord
from discord import app_commands
from discord.ui import Button, View

# ====== 共通モジュール ======
from modules import (
    search_candidates,
    get_place_details,
    summarize_reviews,
    infer_store_type,
    infer_recommendation,
    classify_tags,
    upsert_store,
    build_page_url,
    convert_price_level,
    calc_distance,
)

# ====== Discord Bot 本体 ======
class MyBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        await self.tree.sync()
        print("Slash Commands Synced!")

bot = MyBot()


# --------------------------------------
# Embed 作成
# --------------------------------------
def build_embed(details, summary, tags, store_type, recs, notion_url):
    embed = discord.Embed(
        title=f"📍 {details['name']}",
        url=notion_url,
        description=summary,
        color=0x00AAFF
    )

    embed.add_field(name="タグ", value=", ".join(tags) or "なし", inline=False)
    embed.add_field(name="店タイプ", value=store_type.get("type", ""), inline=True)
    embed.add_field(name="サブタイプ", value=store_type.get("subtype", ""), inline=True)
    embed.add_field(name="おすすめ", value=", ".join(recs) or "不明", inline=False)
    embed.add_field(name="住所", value=details.get("formatted_address", "不明"), inline=False)

    if details.get("opening_hours", {}).get("weekday_text"):
        embed.add_field(
            name="営業時間",
            value="\n".join(details["opening_hours"]["weekday_text"]),
            inline=False
        )

    if details.get("url"):
        embed.add_field(name="Google Maps", value=details["url"], inline=False)

    return embed


# --------------------------------------
# 店保存処理（AI & Notion）
# --------------------------------------
async def process_save(interaction, place_id, comment):

    await interaction.followup.send("⏳ AI分析中...")

    details = get_place_details(place_id)

    summary = summarize_reviews(details.get("reviews", []))
    tags = classify_tags(details["name"], details.get("types", []), summary)
    store_type = infer_store_type(details.get("types", []), summary)
    recs = infer_recommendation(details.get("types", []), summary, details["name"])

    page_id = upsert_store(details, summary, tags, store_type, recs, comment)
    notion_url = build_page_url(page_id)

    embed = build_embed(details, summary, tags, store_type, recs, notion_url)
    await interaction.followup.send(embed=embed)


# --------------------------------------
# 候補選択 UI
# --------------------------------------
class PlaceButton(Button):
    def __init__(self, label, place_id, callback, comment):
        super().__init__(label=label, style=discord.ButtonStyle.primary)
        self.place_id = place_id
        self._callback = callback
        self.comment = comment

    async def callback(self, interaction):
        await interaction.response.defer()
        await self._callback(interaction, self.place_id, self.comment)


class PlaceSelectView(View):
    def __init__(self, candidates, callback, comment):
        super().__init__(timeout=60)
        for c in candidates[:6]:
            self.add_item(
                PlaceButton(
                    label=c["name"],
                    place_id=c["place_id"],
                    callback=callback,
                    comment=comment
                )
            )


# --------------------------------------
# /save コマンド
# --------------------------------------
@bot.tree.command(name="save", description="飲食店を保存（AI解析＋Notion）")
async def save(interaction, query: str, comment: str | None = None):
    await interaction.response.defer(ephemeral=False)

    candidates = search_candidates(query)

    if not candidates:
        await interaction.followup.send("❌ 店舗が見つかりませんでした。")
        return

    # 複数候補 → 選択
    if len(candidates) > 1:

        async def on_select(inter, selected_pid, comment_local):
            await process_save(inter, selected_pid, comment_local)

        view = PlaceSelectView(candidates, on_select, comment)
        await interaction.followup.send(
            "🔎 複数の候補が見つかりました。選択してください。",
            view=view
        )
        return

    # 1件 → そのまま保存
    await process_save(interaction, candidates[0]["place_id"], comment)


# --------------------------------------
# /nearby コマンド
# --------------------------------------
def fetch_all_notion_entries():
    """
    全店舗データを Notion DB から取得
    """
    import requests

    url = f"https://api.notion.com/v1/databases/{os.getenv('MAIN_DATABASE_ID')}/query"
    headers = {
        "Authorization": f"Bearer {os.getenv('NOTION_API_KEY')}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28"
    }

    results = []
    payload = {}

    while True:
        r = requests.post(url, headers=headers, data=json.dumps(payload)).json()
        results.extend(r.get("results", []))

        if not r.get("has_more"):
            break

        payload = {"start_cursor": r.get("next_cursor")}

    return results


@bot.tree.command(name="nearby", description="近くのおすすめ店舗（距離＋タグ＋評価）")
async def nearby(interaction, location: str, conditions: str = ""):
    await interaction.response.defer(ephemeral=False)

    import requests

    cond_words = [c.lower() for c in conditions.split() if c.strip()]

    # 住所 → 緯度経度
    geo_url = (
        "https://maps.googleapis.com/maps/api/geocode/json"
        f"?address={location}&language=ja&key={os.getenv('GOOGLE_API_KEY')}"
    )
    geo_res = requests.get(geo_url).json()

    if not geo_res.get("results"):
        await interaction.followup.send("❌ 現在地を解析できません。")
        return

    loc = geo_res["results"][0]["geometry"]["location"]
    lat0, lng0 = loc["lat"], loc["lng"]

    entries = fetch_all_notion_entries()

    scored = []
    for e in entries:
        props = e["properties"]

        lat = props.get("lat", {}).get("number")
        lng = props.get("lng", {}).get("number")
        if lat is None or lng is None:
            continue

        distance = calc_distance(lat0, lng0, lat, lng)

        tags = [t["name"].lower() for t in props.get("Tags", {}).get("multi_select", [])]

        score = 0
        for cond in cond_words:
            if cond in tags:
                score += 1

        rating = props.get("評価", {}).get("number")
        if rating:
            score += (rating - 3.0) * 0.5

        scored.append({
            "entry": e,
            "distance": distance,
            "score": score
        })

    ranked = sorted(scored, key=lambda x: (-x["score"], x["distance"]))[:3]

    if not ranked:
        await interaction.followup.send("❌ 条件に合う店がありません")
        return

    for item in ranked:
        e = item["entry"]
        props = e["properties"]

        name = props["店名"]["title"][0]["text"]["content"]
        notion_url = build_page_url(e["id"])
        embed = discord.Embed(
            title=f"📍 {name}",
            url=notion_url,
            description=f"距離：{item['distance']:.2f} km\nスコア：{item['score']:.2f}",
            color=0x00AA88
        )
        embed.add_field(name="評価", value=f"{props.get('評価', {}).get('number', 'N/A')}★")
        embed.add_field(name="料金", value=convert_price_level(props.get("料金", {}).get("number")))
        embed.add_field(
            name="タグ",
            value=", ".join([t["name"] for t in props.get("Tags", {}).get("multi_select", [])]) or "なし",
            inline=False
        )

        await interaction.followup.send(embed=embed)


# --------------------------------------
# Railway 用起動関数
# --------------------------------------
def start_discord_bot():
    token = os.getenv("DISCORD_BOT_TOKEN")
    print("[Discord BOT] Starting...")
    bot.run(token)
