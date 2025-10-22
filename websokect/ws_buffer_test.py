#!/usr/bin/env python3
# venv環境 (source venv/bin/activate) で実行
# pip install --upgrade pyalsaaudio websockets

import asyncio
import websockets
import sys

# --- 設定 ---
WEBSOCKET_HOST = '0.0.0.0' # すべてのIFで待ち受け
WEBSOCKET_PORT = 8765      # 待ち受けポート

# 送信するオーディオファイル (16kHz, 16bit, mono, raw)
# 簡単のためこのフォーマットのファイルを用意すること
AUDIO_FILE = 'output.slin16'

# 16kHz, 20ms のチャンクサイズ
# 16000 [サンプル/秒] * 0.020 [秒] = 320 [サンプル]
# 320 [サンプル] * 2 [バイト/サンプル] = 640 [バイト]
# 1パケット(1チャンク単位送り付けの場合)
#CHUNK_SIZE = 640
# 100パケット送り付け例
CHUNK_SIZE = 64000

print("--- バッファリングモード テストサーバ ---")
print(f"ファイル: {AUDIO_FILE}")
print(f"チャンクサイズ: {CHUNK_SIZE} バイト")
print(f"サーバ: ws://{WEBSOCKET_HOST}:{WEBSOCKET_PORT}")
print("-" * 22)


async def handle_incoming(websocket, can_send_event):
    """
    Asteriskからのメッセージを受信し、フロー制御を処理するタスク。
    音声データは読み捨てる。
    """
    print("[IN]  受信タスクを開始しました。")
    try:
        async for message in websocket:
            if isinstance(message, str):
                # --- TEXTメッセージ処理 ---
                print(f"[IN]  受信 (TEXT): {message.strip()}")
                
                if message == "MEDIA_XOFF":
                    print("[IN]  フロー制御: PAUSE (MEDIA_XOFF)")
                    can_send_event.clear()  # 送信タスクを一時停止
                    
                elif message == "MEDIA_XON":
                    print("[IN]  フロー制御: RESUME (MEDIA_XON)")
                    can_send_event.set()    # 送信タスクを再開
                
            elif isinstance(message, bytes):
                # --- BINARY (音声) データ処理 ---
                # 受信した音声データは読み捨てる
                pass
                
    except websockets.exceptions.ConnectionClosed:
        print("[IN]  クライアントが切断しました。")
    except Exception as e:
        print(f"[IN]  受信タスクでエラー: {e}", file=sys.stderr)
    finally:
        # このタスクが終了した場合 (切断など)、
        # 送信タスクが .wait() で止まらないようにイベントをセットする
        can_send_event.set()


async def send_audio_file(websocket, can_send_event):
    """
    オーディオファイルをチャンクごとに読み込み、Asteriskに送信するタスク。
    フロー制御イベントに従う。
    """
    print("[OUT] 送信タスクを開始しました。")
    try:
        # 1. バッファリング開始を通知
        print("[OUT] 送信 (TEXT): START_MEDIA_BUFFERING")
        await websocket.send("START_MEDIA_BUFFERING")

        # 2. オーディオファイルを開いて送信ループ開始
        with open(AUDIO_FILE, 'rb') as f:
            while True:
                # 3. フロー制御イベントを待機 (XOFFならここでブロック)
                await can_send_event.wait()
                
                # 4. ファイルから1チャンク読み込み
                data = f.read(CHUNK_SIZE)
                
                if not data:
                    # ファイル終端
                    print("[OUT] ファイルの送信が完了しました。")
                    break
                
                # 5. データを送信
                await websocket.send(data)
                
                # (重要) Asteriskのキューを溢れさせないよう、
                # チャンク送信ごとに少しだけイベントループに制御を戻す
                await asyncio.sleep(0) 

        # 6. バッファリング終了を通知
        print("[OUT] 送信 (TEXT): STOP_MEDIA_BUFFERING")
        await websocket.send("STOP_MEDIA_BUFFERING")

    except FileNotFoundError:
        print(f"[OUT] エラー: ファイル '{AUDIO_FILE}' が見つかりません。", file=sys.stderr)
    except websockets.exceptions.ConnectionClosed:
        print("[OUT] 送信中にクライアントが切断しました。")
    except Exception as e:
        print(f"[OUT] 送信タスクでエラー: {e}", file=sys.stderr)


async def audio_handler(websocket):
    """
    WebSocketクライアント接続時のメインハンドラ。
    """
    print(f"クライアント {websocket.remote_address} が接続しました。")
    
    # フロー制御のためのイベント (初期状態は "送信可")
    can_send_event = asyncio.Event()
    can_send_event.set()

    # 3. 2つのタスク (読み取り/書き込み) を作成
    task_read = asyncio.create_task(handle_incoming(websocket, can_send_event))
    task_write = asyncio.create_task(send_audio_file(websocket, can_send_event))

    # 4. どちらかのタスクが終了するまで待機 (切断時など)
    done, pending = await asyncio.wait(
        [task_read, task_write],
        return_when=asyncio.FIRST_COMPLETED,
    )

    # 5. 残ったタスクをキャンセル
    for task in pending:
        task.cancel()
            
    print(f"クライアント {websocket.remote_address} との接続を終了しました。")


async def main():
    """
    WebSocketサーバを起動するメイン関数。
    """
    print(f"WebSocketサーバを ws://{WEBSOCKET_HOST}:{WEBSOCKET_PORT} で起動します...")
    print("Ctrl+C で停止します。")
    
    async with websockets.serve(audio_handler, WEBSOCKET_HOST, WEBSOCKET_PORT):
        await asyncio.Future()  # 永久に実行

if __name__ == "__main__":
    if sys.version_info < (3, 9):
        print("このスクリプトは Python 3.9 以上 (asyncio.to_thread) が必要です。")
    else:
        try:
            asyncio.run(main())
        except KeyboardInterrupt:
            print("\nサーバを停止します。")
