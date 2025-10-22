#!/usr/bin/env python3
# venv環境 (source venv/bin/activate) で実行
# pip install --upgrade websockets

import asyncio
import websockets
import sys

# --- WebSocketサーバ設定 ---
WEBSOCKET_HOST = '0.0.0.0' # すべてのIFで待ち受け
WEBSOCKET_PORT = 8765      # 待ち受けポート

print("--- WebSocket エコーサーバ ---")
print(f"サーバ: ws://{WEBSOCKET_HOST}:{WEBSOCKET_PORT}")
print("-" * 22)

async def echo_handler(websocket):
    """
    クライアント接続時のハンドラ。
    TEXTはprintし、BINARY(音声)はそのままエコーバックする。
    """
    print(f"クライアント {websocket.remote_address} が接続しました。")
    
    try:
        # 接続されたクライアントからのメッセージを非同期で待機
        async for message in websocket:
            
            if isinstance(message, str):
                # 1. TEXTデータが送られてきた場合
                print(f"受信 (TEXT): {message.strip()}")
            
            elif isinstance(message, bytes):
                # 2. BINARY (音声) データが送られてきた場合
                # そのまま同じ接続先に送り返す (エコーバック)
                await websocket.send(message)
            
            else:
                print("不明な形式のメッセージを受信。無視します。")
                
    except websockets.exceptions.ConnectionClosed:
        print(f"クライアント {websocket.remote_address} が切断しました。")
    except Exception as e:
        print(f"ハンドラで予期せぬエラー: {e}", file=sys.stderr)
    finally:
        print(f"クライアント {websocket.remote_address} との接続を終了しました。")


async def main():
    """
    WebSocketサーバを起動するメイン関数。
    """
    print("Ctrl+C で停止します。")
    
    async with websockets.serve(echo_handler, WEBSOCKET_HOST, WEBSOCKET_PORT):
        await asyncio.Future()  # 実行を継続

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nサーバを停止します。")
