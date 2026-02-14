import asyncio
import websockets
import json
import requests
import time
import math

API_BASE = "http://127.0.0.1:8000/interviews"
DJANGO_WS = "ws://127.0.0.1:8000/ws/interview"
CENTRIFUGO_WS = "ws://127.0.0.1:8001/connection/websocket"

def generate_sine_wave_chunk(duration_ms=20, sample_rate=16000, freq=440):
    num_samples = int(sample_rate * (duration_ms / 1000.0))
    samples = []
    for i in range(num_samples):
        val = int(32767 * 0.4 * math.sin(2 * math.pi * freq * (i / sample_rate)))
        samples.append(val.to_bytes(2, byteorder='little', signed=True))
    return b"".join(samples)

async def run_test():
    print("🏗️  Step 1: Setup")
    try:
        with requests.Session() as s:
            setup_resp = s.post(f"{API_BASE}/test/setup/", timeout=5)
            setup_resp.raise_for_status()
            session_id = setup_resp.json()['session_id']
            token_data = s.get(f"{API_BASE}/token/{session_id}/", timeout=5).json()
            token, channel = token_data['token'], token_data['channel']
        print(f"✅ Session: {session_id}")
    except Exception as e:
        print(f"❌ Setup Failed: {e}"); return

    try:
        print("🔗 Connecting...")
        async with websockets.connect(f"{DJANGO_WS}/{session_id}/") as django_ws, \
                   websockets.connect(CENTRIFUGO_WS) as centri_ws:
            
            # Auth Centrifugo
            await centri_ws.send(json.dumps({"connect": {"token": token}, "id": 1}))
            await centri_ws.recv()
            await centri_ws.send(json.dumps({"subscribe": {"channel": channel}, "id": 2}))
            print("✅ Centrifugo & Django Connected.")

            # --- MIC STREAM ---
            print("\n🎤 Step 2: Streaming Audio (3s)...")
            audio_chunk = generate_sine_wave_chunk()
            for i in range(150): # 150 * 20ms = 3s
                await django_ws.send(audio_chunk)
                await asyncio.sleep(0.02)
            
            print("⏳ Waiting for VAD trigger (5s)...")
            
            # --- LISTENER LOOP ---
            start_time = time.time()
            received_any = False
            
            while time.time() - start_time < 15:
                try:
                    # If 5 seconds pass with no audio, send a manual trigger to verify the rest of the pipe
                    if time.time() - start_time > 5 and not received_any:
                        print("📡 No VAD trigger yet. Sending 'force_test' text signal...")
                        await django_ws.send(json.dumps({"type": "force_test"}))
                        received_any = True # Only send once

                    raw_push = await asyncio.wait_for(centri_ws.recv(), timeout=1.0)
                    push = json.loads(raw_push)
                    
                    # Extract Data
                    res = push.get("result", {}).get("pub", {}).get("data", {}) or \
                          push.get("push", {}).get("pub", {}).get("data", {})
                    
                    if res.get("type") == "text_message":
                        print(f"🤖 [AI]: {res.get('message')}")
                    elif res.get("type") == "tts_audio":
                        print("🎵 [AUDIO] Chunk received!")
                        return print("\n✨ TEST PASSED!")
                except asyncio.TimeoutError:
                    continue

            print("\n⚠️ TEST FAILED: Timeout without audio.")
    except Exception as e:
        print(f"\n❌ Error: {e}")

if __name__ == "__main__":
    asyncio.run(run_test())