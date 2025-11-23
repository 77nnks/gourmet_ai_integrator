# modules/utils.py
import math
import re
import os


# Google Places Photo URL 生成
def build_photo_url(photo_reference, maxwidth=800):
    key = os.getenv("GOOGLE_API_KEY")
    return (
        "https://maps.googleapis.com/maps/api/place/photo"
        f"?maxwidth={maxwidth}&photo_reference={photo_reference}&key={key}"
    )


# 店タイプ → アイコン
TYPE_ICON = {
    "cafe": "☕",
    "coffee": "☕",
    "bar": "🍺",
    "ramen": "🍜",
    "yakiniku": "🍖",
    "sushi": "🍣",
    "restaurant": "🍽️",
    "french": "🥐",
    "italian": "🍝",
    "izakaya": "🍶",
    "fastfood": "🍔",
    "bistro": "🥗",
}

# サブタイプ → アイコン
SUBTYPE_ICON = {
    "スイーツ": "🍰",
    "軽食": "🥪",
    "デート": "💑",
    "おしゃれ": "✨",
    "静か": "🤫",
    "カジュアル": "🙂",
    "居酒屋": "🍶",
}

# ★評価テキスト
def build_rating_stars(rating):
    if not rating:
        return "評価なし"

    stars = "★" * int(round(rating))
    empty = "☆" * (5 - int(round(rating)))
    return f"{stars}{empty}  {rating}"

# -----------------------------------------------
# Google price_level → 日本語料金表記に変換
# -----------------------------------------------
def convert_price_level(price_level: int | None) -> str:
    """
    Google Places API の price_level (0〜4) を
    日本語の料金帯テキストに変換する
    """

    if price_level is None:
        return "情報なし"

    mapping = {
        0: "￥0〜",
        1: "￥〜1,000",
        2: "￥1,000〜2,000",
        3: "￥2,000〜5,000",
        4: "￥5,000〜",
    }

    return mapping.get(price_level, "情報なし")


# -----------------------------------------------
# 緯度経度から距離（km）を計算
# -----------------------------------------------
def calc_distance(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """
    緯度経度 (lat, lng) から距離(km)を算出する。
    Haversine 公式を使用。
    """

    R = 6371  # 地球の半径(km)

    d_lat = math.radians(lat2 - lat1)
    d_lng = math.radians(lng2 - lng1)

    a = (
        math.sin(d_lat / 2) ** 2 +
        math.cos(math.radians(lat1)) *
        math.cos(math.radians(lat2)) *
        math.sin(d_lng / 2) ** 2
    )

    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# -----------------------------------------------
# 数字抽出（LINEの簡易記録などに使用可能）
# -----------------------------------------------
def extract_number(text: str):
    """文字列から最初に見つかった数字を抽出して数値として返す"""
    match = re.search(r"(\d+)", text)
    if not match:
        return None
    return int(match.group(1))


# -----------------------------------------------
# 非数字部分（食べ物名など）だけ抽出
# -----------------------------------------------
def extract_text_without_numbers(text: str) -> str:
    """数字を除いた純粋なテキストを返す"""
    return re.sub(r"\d+", "", text).strip()


# -----------------------------------------------
# テキストを上限文字数で切る（AI出力等の保険）
# -----------------------------------------------
def trim_text(text: str, max_len: int = 1900) -> str:
    """長すぎるテキストを Discord/LINE 制限用にトリム"""
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


# -----------------------------------------------
# 住所 or 位置情報の抽出（必要なら拡張する）
# -----------------------------------------------
def parse_location_query(message: str) -> str:
    """
    LINE/Discord の入力から「場所検索用のクエリ文字列」を抽出。
    例：'スタバ 東京' → 'スタバ 東京'
    """
    return message.strip()
