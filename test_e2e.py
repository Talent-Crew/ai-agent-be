import asyncio
import websockets
import json
import requests
import base64
import time

# 🌍 CONFIGURATION
API_BASE = "http://localhost:8000/interviews"
DJANGO_WS = "ws://localhost:8000/ws/interview"
CENTRIFUGO_WS = "ws://localhost:8001/connection/websocket"

async def run_test():
    print("🏗️  Step 1: Creating Session and Fetching Tokens...")
    try:
        # 1. Setup Session
        setup_resp = requests.post(f"{API_BASE}/test/setup/")
        setup_resp.raise_for_status()
        session_id = setup_resp.json()['session_id']
        
        # 2. Get Auth Token
        token_data = requests.get(f"{API_BASE}/token/{session_id}/").json()
        token = token_data['token']
        channel = token_data['channel']
        print(f"✅ Session: {session_id}")
        print(f"✅ Channel: {channel}")
    except Exception as e:
        print(f"❌ Setup Failed: {e}")
        return

    try:
        # 🚀 Connect to both Django (for Mic) and Centrifugo (for Speaker)
        async with websockets.connect(f"{DJANGO_WS}/{session_id}/") as django_ws, \
                   websockets.connect(CENTRIFUGO_WS) as centri_ws:
            
            # --- CENTRIFUGO HANDSHAKE ---
            print("🔐 Authenticating with Centrifugo...")
            await centri_ws.send(json.dumps({
                "connect": {"token": token},
                "id": 1
            }))
            
            conn_res = json.loads(await centri_ws.recv())
            if "error" in conn_res:
                print(f"❌ Centrifugo Auth Error: {conn_res['error']}")
                return
            print("✅ Centrifugo Authenticated.")

            # Subscribe to the channel
            await centri_ws.send(json.dumps({
                "subscribe": {"channel": channel},
                "id": 2
            }))
            print(f"👂 Subscribed to {channel}")

            # --- REAL-TIME STREAMING SIMULATION ---
            print("\n🎤 Step 2: Streaming 3 seconds of 'Fake Speech'...")
            
            # 16kHz 16-bit PCM = 32,000 bytes per second
            # 20ms chunk = 640 bytes
            chunk_size = 640
            total_duration = 3.0 # seconds
            num_chunks = int(total_duration / 0.02)

            for i in range(num_chunks):
                # We use a simple square wave or alternating pattern to trick VAD
                # 640 bytes per 20ms
                if i % 2 == 0:
                    dummy_chunk = b'\x08\x00' * 320  # Low amplitude buzz
                else:
                    dummy_chunk = b'\xf8\xff' * 320  # Inverse
                
                await django_ws.send(dummy_chunk)
                
                # Sleep exactly 20ms to simulate real-time mic hardware
                await asyncio.sleep(0.02)
                
                if i % 50 == 0:
                    print(f"   [Mic] Sent {i*20}ms of audio data...")

            print("✅ Streaming finished. Waiting for Gemini & Deepgram Aura response...")

            # --- LISTEN FOR RESPONSE ---
            start_time = time.time()
            chunks_received = 0
            
            while time.time() - start_time < 15:
                try:
                    # Centrifugo v5 pushes come as async messages
                    raw_push = await asyncio.wait_for(centri_ws.recv(), timeout=1.0)
                    push = json.loads(raw_push)

                    # Centrifugo V5 Push Structure: result -> pub -> data
                    # Or check for 'push' key depending on protocol version
                    msg_data = push.get("result", {}).get("pub", {}).get("data", {})
                    if not msg_data:
                        msg_data = push.get("push", {}).get("pub", {}).get("data", {})

                    if msg_data.get("type") == "text_message":
                        print(f"\n🤖 [AI TEXT]: {msg_data.get('message')}")
                    
                    elif msg_data.get("type") == "tts_audio":
                        chunks_received += 1
                        if chunks_received == 1:
                            print("🎵 [AUDIO] First chunk received! AI is speaking.")
                
                except asyncio.TimeoutError:
                    continue

            if chunks_received > 0:
                print(f"\n✨ TEST PASSED: Received {chunks_received} audio chunks from the relay.")
            else:
                print("\n⚠️ TEST COMPLETED: No audio received. Check if Gemini found a response.")

    except Exception as e:
        print(f"❌ Test Failure: {e}")

if __name__ == "__main__":
    asyncio.run(run_test())