#!/usr/bin/env python3
# Python3でvenv環境を使うこと
# (alsaaudioがディストリのものでは挙動がおかしいため)
# venv環境を用意して以下を実行
# pip install --upgrade pyalsaaudio websockets

import alsaaudio
import asyncio
import websockets
import sys

# --- ALSAデバイス設定 (環境に合わせて変更) ---
INPUT_DEVICE = 'plughw:1,0'  
OUTPUT_DEVICE = 'plughw:1,0' 

# --- オーディオ設定 (クライアントと一致させる) ---
CHANNELS = 1              
RATE = 16000               # 16kHz (ここを 8000 に変更してもOK)
FORMAT = alsaaudio.PCM_FORMAT_S16_LE  # slin (16ビット符号付きリトルエンディアン)

# --- チャンクサイズ設定 (20ms固定) ---
# 20msペーシングを守ること
BYTES_PER_FRAME = (16 // 8) * CHANNELS
PERIOD_SIZE = int(RATE * 0.020)

# --- WebSocketサーバ設定 ---
WEBSOCKET_HOST = '0.0.0.0' # すべてのIFで待ち受け
WEBSOCKET_PORT = 8765      # 待ち受けポート

# MEDIA_START受信後、ANSWERを送信するまでの遅延 (秒)
ANSWER_DELAY = 3.0 


print("--- オーディオ設定 ---")
print(f"デバイス (IN): {INPUT_DEVICE}")
print(f"デバイス (OUT): {OUTPUT_DEVICE}")
print(f"レート: {RATE} Hz")
print(f"フォーマット: {FORMAT} (S16_LE)")
print(f"チャンネル: {CHANNELS}")
print(f"ピリオドサイズ: {PERIOD_SIZE} フレーム (={int(PERIOD_SIZE/RATE*1000)}ms)")
print(f"チャンクサイズ: {PERIOD_SIZE * BYTES_PER_FRAME} バイト")
print(f"ANSWER遅延: {ANSWER_DELAY} 秒")
print("-" * 22)


async def alsa_to_websocket(websocket, inp):
    """
    ALSA入力(inp)からオーディオを読み取り、WebSocketに送信するタスク。
    """
    print("ALSA->WebSocket タスクを開始します。")
    try:
        while True:
            length, data = await asyncio.to_thread(inp.read)

            if length > 0:
                await websocket.send(data)
            elif length < 0:
                print(f"ALSA読み取りエラー: {length}", file=sys.stderr)
                break
                
    except websockets.exceptions.ConnectionClosed:
        print("クライアントが切断しました (ALSA->WS)。")
    except Exception as e:
        print(f"ALSA->WSタスクで予期せぬエラー: {e}", file=sys.stderr)


async def send_answer_after_delay(websocket, delay):
    """
    指定された遅延の後、"ANSWER" TEXTフレームを送信するコルーチン。
    """
    try:
        await asyncio.sleep(delay)
        print(f"送信 (TEXT): ANSWER (遅延 {delay}秒後)")
        await websocket.send("ANSWER")
    except asyncio.CancelledError:
        # メインのハンドラが終了した際にキャンセルされる
        print("ANSWER送信タスクがキャンセルされました。")
    except websockets.exceptions.ConnectionClosed:
        print("ANSWER送信前にクライアントが切断しました。")
    except Exception as e:
        print(f"ANSWER送信中にエラー: {e}", file=sys.stderr)


async def websocket_to_alsa(websocket, outp):
    """
    WebSocketからバイナリデータを受信し、ALSA出力(outp)に書き込むタスク。
    MEDIA_STARTを受信したらANSWERをスケジュールする。
    """
    print("WebSocket->ALSA タスクを開始します。")
    answer_task = None # ANSWER送信タスクを管理

    try:
        # WebSocketからメッセージを非同期でイテレート
        async for message in websocket:
            
            if isinstance(message, bytes):
                # オーディオデータはALSAへ (ブロッキング)
                await asyncio.to_thread(outp.write, message)
                
            elif isinstance(message, str):
                # TEXTデータ処理
                print(f"受信したTEXTデータ: {message}")
                
                # "MEDIA_START" を受信し、まだANSWERタスクが起動していない場合
                if message.startswith("MEDIA_START") and not answer_task:
                    print(f"MEDIA_STARTを検出。{ANSWER_DELAY}秒後に 'ANSWER' を送信予約します。")
                    # ANSWER送信タスクを非同期で起動 (受信ループをブロックしない)
                    answer_task = asyncio.create_task(
                        send_answer_after_delay(websocket, ANSWER_DELAY)
                    )
            else:
                print("不明な形式のメッセージを受信。無視します。")
                
    except websockets.exceptions.ConnectionClosed:
        print("クライアントが切断しました (WS->ALSA)。")
    except Exception as e:
        print(f"WS->ALSAタスクで予期せぬエラー: {e}", file=sys.stderr)
    finally:
        # このタスクが終了する際、スケジュールされたANSWERタスクが
        # まだ実行中ならキャンセルする
        if answer_task and not answer_task.done():
            answer_task.cancel()


async def audio_handler(websocket):
    """
    WebSocketクライアント接続時のメインハンドラ。
    """
    print(f"クライアント {websocket.remote_address} が接続しました。")
    inp = None
    outp = None
    
    try:
        # 1. ALSA入力デバイスを初期化
        inp = alsaaudio.PCM(
            type=alsaaudio.PCM_CAPTURE,
            mode=alsaaudio.PCM_NORMAL,
            channels=CHANNELS,
            rate=RATE,
            format=FORMAT,
            periodsize=PERIOD_SIZE,
            device=INPUT_DEVICE
        )
        
        # 2. ALSA出力デバイスを初期化
        outp = alsaaudio.PCM(
            type=alsaaudio.PCM_PLAYBACK,
            mode=alsaaudio.PCM_NORMAL,
            channels=CHANNELS,
            rate=RATE,
            format=FORMAT,
            periodsize=PERIOD_SIZE,
            device=OUTPUT_DEVICE
        )
        print("ALSAデバイスを開きました。双方向ストリーミングを開始します。")

        # 3. 2つのタスク (読み取り/書き込み) を作成
        task_read = asyncio.create_task(alsa_to_websocket(websocket, inp))
        task_write = asyncio.create_task(websocket_to_alsa(websocket, outp))

        # 4. どちらかのタスクが終了するまで待機 (切断時など)
        done, pending = await asyncio.wait(
            [task_read, task_write],
            return_when=asyncio.FIRST_COMPLETED,
        )

        # 5. 残ったタスクをキャンセル
        for task in pending:
            task.cancel()

    except alsaaudio.ALSAAudioError as e:
        print(f"ALSA初期化エラー: {e}", file=sys.stderr)
        print("デバイスがビジーか、設定がサポートされていません。")
    except Exception as e:
        print(f"ハンドラで予期せぬエラー: {e}", file=sys.stderr)
        
    finally:
        # 6. クリーンアップ
        if inp:
            inp.close()
        if outp:
            outp.close()
        print(f"クライアント {websocket.remote_address} との接続を終了。ALSAデバイスを閉じました。")


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
