# modules/notion_client.py
import os
import json
import requests
from typing import List, Dict, Optional

NOTION_API_KEY = os.getenv("NOTION_API_KEY")
NOTION_DB_ID = os.getenv("MAIN_DATABASE_ID")
NOTION_VERSION = "2022-06-28"


# -----------------------------------------------
# Helper：Notion API 共通ヘッダ
# -----------------------------------------------
def _headers():
    return {
        "Authorization": f"Bearer {NOTION_API_KEY}",
        "Content-Type": "application/json",
        "Notion-Version": NOTION_VERSION,
    }


# -----------------------------------------------
# Helper：Notion ページURL生成
# -----------------------------------------------
def build_page_url(page_id: str) -> str:
    """Notion のページURL（ID のハイフンを除去）を生成"""
    return f"https://www.notion.so/{page_id.replace('-', '')}"


# -----------------------------------------------
# Check：place_id から既存ページ検索
# -----------------------------------------------
def find_page_by_place_id(place_id: str) -> Optional[str]:
    """place_id が一致する Notion ページを返す（なければ None）"""

    query = {
        "filter": {
            "property": "place_id",
            "rich_text": {"equals": place_id}
        }
    }

    url = f"https://api.notion.com/v1/databases/{NOTION_DB_ID}/query"
    res = requests.post(url, headers=_headers(), data=json.dumps(query)).json()

    results = res.get("results", [])
    if not results:
        return None

    return results[0]["id"]


# -----------------------------------------------
# ページ作成 or 更新（Upsert）
# -----------------------------------------------
def upsert_store(
    details: dict,
    summary: str,
    tags: List[str],
    store_type: Dict[str, str],
    recommendations: List[str],
    comment: Optional[str] = None,
) -> str:
    """
    NotionDB に飲食店データを Upsert（Insert or Update）する。
    Discord と LINE 両方から利用可能。
    """

    place_id = details["place_id"]
    page_id = find_page_by_place_id(place_id)

    # --------- 保存データ（Notion properties）---------
    hours = details.get("opening_hours", {}).get("weekday_text", [])
    hours_text = "\n".join(hours)

    geo = details.get("geometry", {}).get("location", {})

    props = {
        "店名": {
            "title": [{"text": {"content": details["name"]}}]
        },
        "住所": {
            "rich_text": [{"text": {"content": details.get("formatted_address", "")}}]
        },
        "評価": {"number": details.get("rating")},
        "料金": {"number": details.get("price_level")},
        "営業時間": {"rich_text": [{"text": {"content": hours_text}}]},
        "URL": {"url": details.get("url")},
        "公式サイト": {"url": details.get("website")},
        "lat": {"number": geo.get("lat")},
        "lng": {"number": geo.get("lng")},
        "place_id": {"rich_text": [{"text": {"content": place_id}}]},
        "印象": {"rich_text": [{"text": {"content": summary}}]},
        "感想": {"rich_text": [{"text": {"content": comment or ""}}]},
        "店タイプ": {"select": {"name": store_type.get("type", "")}},
        "サブタイプ": {"rich_text": [{"text": {"content": store_type.get("subtype", "")}}]},
        "おすすめメニュー": {
            "rich_text": [
                {"text": {"content": ", ".join(recommendations)}}
            ]
        },
        "Tags": {"multi_select": [{"name": t} for t in tags]},
    }

    # --------- 既存 → 更新 ---------
    if page_id:
        url = f"https://api.notion.com/v1/pages/{page_id}"
        body = {"properties": props}

        requests.patch(url, headers=_headers(), data=json.dumps(body))
        return page_id

    # --------- 新規作成 ---------
    create_body = {
        "parent": {"database_id": NOTION_DB_ID},
        "properties": props
    }

    res = requests.post(
        "https://api.notion.com/v1/pages",
        headers=_headers(),
        data=json.dumps(create_body)
    ).json()

    return res["id"]
