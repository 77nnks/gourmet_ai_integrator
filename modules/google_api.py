# modules/google_api.py
import os
import requests

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
SEARCH_LANGUAGE = "ja"


# ---------------------------
# Text Search（店舗候補検索）
# ---------------------------
def search_candidates(query: str):
    """Google Places TextSearch API で店候補を検索"""

    url = (
        "https://maps.googleapis.com/maps/api/place/textsearch/json"
        f"?query={query}&language={SEARCH_LANGUAGE}&key={GOOGLE_API_KEY}"
    )

    res = requests.get(url).json()

    candidates = []
    for item in res.get("results", []):
        candidates.append({
            "name": item.get("name"),
            "place_id": item.get("place_id"),
            "address": item.get("formatted_address", "")
        })

    return candidates


# ---------------------------
# Details API（詳細取得）
# ---------------------------
def get_place_details(place_id: str):
    """Google Places Details API で店舗詳細を取得"""

    url = (
        "https://maps.googleapis.com/maps/api/place/details/json"
        f"?place_id={place_id}"
        "&fields=name,place_id,formatted_address,opening_hours,"
        "website,url,rating,reviews,types,price_level,geometry"
        f"&language={SEARCH_LANGUAGE}"
        f"&key={GOOGLE_API_KEY}"
    )

    return requests.get(url).json().get("result", {})
