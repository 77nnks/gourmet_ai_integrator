# modules/ai_processing.py
import os
import json
from openai import OpenAI

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client_ai = OpenAI(api_key=OPENAI_API_KEY)


# -----------------------------------------------
# 共通：Chat Completion Wrapper（JSON強制返却）
# -----------------------------------------------
def _request_json(prompt: str):
    """OpenAI API に JSON形式で返すよう強制して送信"""
    res = client_ai.chat.completions.create(
        model="gpt-4o-mini",
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": "必ず JSON のみ返してください。"},
            {"role": "user", "content": prompt}
        ]
    )
    content = res.choices[0].message.content
    return json.loads(content)


# -----------------------------------------------
# AI：口コミ要約
# -----------------------------------------------
def summarize_reviews(reviews: list[str]) -> str:
    """口コミ一覧をまとめて '良い点/気になる点/まとめ' を生成"""

    texts = [r.get("text", "") for r in reviews if r.get("text")]
    joined = "\n".join(texts)

    prompt = f"""
以下の口コミ一覧を元に、良い点／気になる点／一言まとめ を生成してください。
出力(JSON):
{{
  "positive": ["...", "..."],
  "negative": ["..."],
  "conclusion": "..."
}}
口コミ:
{joined}
"""

    data = _request_json(prompt)

    summary = "【良い点】\n"
    summary += "\n".join([f"・{p}" for p in data.get("positive", [])])

    summary += "\n\n【気になる点】\n"
    summary += "\n".join([f"・{n}" for n in data.get("negative", [])])

    summary += "\n\n【まとめ】\n" + data.get("conclusion", "")

    return summary


# -----------------------------------------------
# AI：店タイプ（Select 用）
# -----------------------------------------------
def infer_store_type(types: list[str], summary: str) -> dict:
    """
    Google Types + 要約 から 店タイプ/サブタイプ を推論
    { "type": "cafe", "subtype": "スイーツとコーヒー" }
    """

    prompt = f"""
以下の情報から、「店タイプ（1語）」と「サブタイプ（短い説明）」を推論してください。

Google Types:
{types}

レビュー要約:
{summary}

出力(JSON):
{{
  "type": "cafe",
  "subtype": "コーヒーとスイーツ"
}}
"""

    return _request_json(prompt)


# -----------------------------------------------
# AI：おすすめメニュー
# -----------------------------------------------
def infer_recommendation(types: list[str], summary: str, name: str) -> list[str]:
    """
    店名 + Google Types + 要約からおすすめメニューを生成
    3件返す
    """

    prompt = f"""
以下の情報から、店のおすすめメニューを３つ推論してください。

店名: {name}
Google Types: {types}
レビュー要約: {summary}

出力(JSON):
{{"recommendations": ["○○", "○○", "○○"]}}
"""

    data = _request_json(prompt)
    return data.get("recommendations", [])


# -----------------------------------------------
# AI：タグ分類
# -----------------------------------------------
def classify_tags(name: str, types: list[str], summary: str) -> list[str]:
    """
    店情報から「訪問用途」や「雰囲気」などのタグを抽出。
    """

    prompt = f"""
以下の店情報から適切なタグ(雰囲気/用途/特徴など)を抽出してください。

店名: {name}
Google Types: {types}
レビュー要約:
{summary}

出力(JSON):
{{"tags": ["デート向け", "落ち着いた", "カフェ"]}}
"""

    data = _request_json(prompt)
    return data.get("tags", [])
