# modules/google_api.py
import os
import requests

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
SEARCH_LANGUAGE = "ja"


# ---------------------------
# Text Search（店舗候補検索）
# ---------------------------
def search_candidates(query: str) -> list:
    """Google Places TextSearch API で店候補を検索"""

    url = (
        "https://maps.googleapis.com/maps/api/place/textsearch/json"
        f"?query={query}&language={SEARCH_LANGUAGE}&key={GOOGLE_API_KEY}"
    )

    res = requests.get(url)
    if res.status_code != 200:
        print(f"[Google TextSearch Error] HTTP {res.status_code}")
        return []

    data = res.json()
    status = data.get("status")
    if status not in ("OK", "ZERO_RESULTS"):
        print(f"[Google TextSearch Error] status={status}: {data.get('error_message', '')}")
        return []

    candidates = []
    for item in data.get("results", []):
        candidates.append({
            "name": item.get("name"),
            "place_id": item.get("place_id"),
            "address": item.get("formatted_address", "")
        })

    return candidates


# ---------------------------
# Nearby Search（近傍店舗検索）
# ---------------------------
def search_nearby(lat: float, lng: float, radius: int = 500) -> list:
    """Google Places Nearby Search API で近くの飲食店を検索"""

    url = (
        "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
        f"?location={lat},{lng}&radius={radius}&type=restaurant"
        f"&language={SEARCH_LANGUAGE}&key={GOOGLE_API_KEY}"
    )

    res = requests.get(url)
    if res.status_code != 200:
        print(f"[Google NearbySearch Error] HTTP {res.status_code}")
        return []

    data = res.json()
    status = data.get("status")
    if status not in ("OK", "ZERO_RESULTS"):
        print(f"[Google NearbySearch Error] status={status}: {data.get('error_message', '')}")
        return []

    candidates = []
    for item in data.get("results", []):
        candidates.append({
            "name": item.get("name"),
            "place_id": item.get("place_id"),
            "address": item.get("vicinity", "")
        })

    return candidates


# ---------------------------
# Geocoding（住所 → 緯度経度）
# ---------------------------
def geocode_address(address: str) -> dict | None:
    """住所文字列を緯度経度に変換する。失敗時は None を返す"""

    url = (
        "https://maps.googleapis.com/maps/api/geocode/json"
        f"?address={address}&language={SEARCH_LANGUAGE}&key={GOOGLE_API_KEY}"
    )

    res = requests.get(url)
    if res.status_code != 200:
        print(f"[Google Geocode Error] HTTP {res.status_code}")
        return None

    data = res.json()
    status = data.get("status")
    if status not in ("OK",):
        print(f"[Google Geocode Error] status={status}: {data.get('error_message', '')}")
        return None

    results = data.get("results")
    if not results:
        return None

    return results[0]["geometry"]["location"]  # {"lat": ..., "lng": ...}


# ---------------------------
# Details API（詳細取得）
# ---------------------------
def get_place_details(place_id: str) -> dict:
    """Google Places Details API で店舗の詳細情報を取得する"""

    url = (
        "https://maps.googleapis.com/maps/api/place/details/json"
        f"?place_id={place_id}"
        "&fields=name,place_id,formatted_address,opening_hours,"
        "website,url,rating,reviews,types,price_level,geometry,photos"
        f"&language={SEARCH_LANGUAGE}"
        f"&key={GOOGLE_API_KEY}"
    )

    res = requests.get(url)
    if res.status_code != 200:
        print(f"[Google Details Error] HTTP {res.status_code}")
        return {}

    data = res.json()
    status = data.get("status")
    if status != "OK":
        print(f"[Google Details Error] status={status}: {data.get('error_message', '')}")
        return {}

    return data.get("result", {})
