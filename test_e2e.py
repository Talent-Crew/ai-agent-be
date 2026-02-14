import asyncio
import websockets
import json
import requests
import time

# 🌍 SETTINGS
API_BASE = "http://localhost:8000/interviews/test/setup/"
WS_BASE = "ws://localhost:8000/ws/interview/"

async def run_e2e_test():
    print("🏗️  Step 1: Creating Job and Session via API...")
    try:
        response = requests.post(API_BASE)
        response.raise_for_status()
        session_id = response.json()['session_id']
        print(f"✅ Created Session: {session_id}")
    except Exception as e:
        print(f"❌ API Error: {e}")
        return

    ws_url = f"{WS_BASE}{session_id}/"
    print(f"🚀 Step 2: Connecting to WebSocket at {ws_url}...")

    try:
        async with websockets.connect(ws_url) as ws:
            print("✅ Connected to the Brain.")

            # 🎤 Simulate the candidate saying "Hello, I am ready."
            # In a real app, this is 16kHz PCM audio. 
            # Sending 0.5s of dummy audio data to "wake up" the VAD.
            dummy_audio = b'\x00' * 16000 
            await ws.send(dummy_audio)
            print("🎤 Sent initial audio stream...")

            # 👂 Listen for Gemini's reaction
            print("👂 Waiting for Gemini 3 to respond...")
            
            start_time = time.time()
            while time.time() - start_time < 15: # Listen for 15 seconds
                message = await ws.recv()
                
                if isinstance(message, bytes):
                    # We expect raw audio bytes back (Gemini's voice)
                    print(f"🎵 [AUDIO] Received {len(message)} bytes (Gemini is speaking!)")
                else:
                    # We expect JSON tool calls or text
                    data = json.loads(message)
                    print(f"🤖 [DATA] Gemini message: {json.dumps(data, indent=2)}")
                    
                    if "record_evidence" in str(data):
                        print("🔥 SUCCESS: Gemini triggered a Rubric Tool call!")

    except Exception as e:
        print(f"❌ WebSocket Error: {e}")

if __name__ == "__main__":
    asyncio.run(run_e2e_test())