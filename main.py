# main.py
import os
import threading

# Discord Bot 起動関数
from bot_discord.discord_bot import start_discord_bot

# LINE Bot の Flask アプリ
from bot_line.line_bot import app as line_app


def run_line_bot():
    """
    LINE Bot（Flask）を起動する。
    Railway では自動で PORT が割り当てられる。
    """
    port = int(os.getenv("PORT", 8080))
    print(f"[LINE BOT] Starting Flask server on port {port}")
    line_app.run(host="0.0.0.0", port=port)


def main():
    print("=== Gourmet AI Integrator Starting ===")

    # ----------------------------
    # Discord Bot をサブスレッドで起動
    # ----------------------------
    print("[Discord BOT] Starting...")
    discord_thread = threading.Thread(target=start_discord_bot)
    discord_thread.daemon = True
    discord_thread.start()

    # ----------------------------
    # LINE Bot（Flask）をメインで起動
    # ----------------------------
    print("[LINE BOT] Starting Flask app...")
    run_line_bot()


if __name__ == "__main__":
    main()
