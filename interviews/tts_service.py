"""
Kokoro TTS Service for Real-time Audio Streaming
Integrates with hexgrad/Kokoro-82M-v0.19 model
"""

import asyncio
import torch
import numpy as np
import soundfile as sf
from io import BytesIO
from transformers import AutoTokenizer, AutoModelForCausalLM
from typing import AsyncGenerator, Optional
import logging

logger = logging.getLogger(__name__)


class KokoroTTSService:
    """
    Singleton service for Kokoro TTS inference with GPU acceleration.
    Generates female voice audio and streams it in real-time chunks.
    """
    
    _instance: Optional['KokoroTTSService'] = None
    _initialized: bool = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        """Initialize Kokoro TTS model (runs only once via singleton)."""
        if not self._initialized:
            logger.info("🎤 Initializing Kokoro-TTS Service...")
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
            self.model_id = "hexgrad/Kokoro-82M-v0.19"
            self.sample_rate = 24000  # Kokoro native sample rate
            self.target_sample_rate = 16000  # Frontend expects 16kHz
            self.chunk_samples = 4096  # ~256ms at 16kHz
            
            # Female voice selection
            self.voice_id = "af_bella"  # Female voice (adjust based on model voices)
            
            try:
                logger.info(f"📥 Loading Kokoro model from {self.model_id}...")
                self.model = self._load_kokoro_model()
                self.tokenizer = AutoTokenizer.from_pretrained(
                    self.model_id,
                    trust_remote_code=True
                )
                KokoroTTSService._initialized = True
                logger.info(f"✅ Kokoro-TTS loaded successfully on {self.device}")
            except Exception as e:
                logger.error(f"❌ Failed to load Kokoro model: {e}")
                raise
    
    def _load_kokoro_model(self):
        """Load Kokoro model with proper configuration."""
        try:
            # Try loading with Kokoro-specific approach
            # Note: Kokoro might have custom model class, adjust if needed
            from transformers import AutoModel
            
            model = AutoModel.from_pretrained(
                self.model_id,
                torch_dtype=torch.float16 if self.device == "cuda" else torch.float32,
                device_map="auto" if self.device == "cuda" else None,
                trust_remote_code=True
            )
            
            if self.device == "cpu":
                model = model.to(self.device)
            
            model.eval()
            return model
            
        except Exception as e:
            logger.warning(f"AutoModel failed, trying direct import: {e}")
            # Fallback: If Kokoro has custom model class
            raise NotImplementedError(
                "Kokoro model loading requires model-specific implementation. "
                "Check hexgrad/Kokoro-82M-v0.19 documentation for correct loading method."
            )
    
    async def generate_audio_chunks(
        self, 
        text: str, 
        voice: Optional[str] = None
    ) -> AsyncGenerator[bytes, None]:
        """
        Generate audio from text and yield chunks for real-time streaming.
        
        Args:
            text: Text to convert to speech
            voice: Voice ID (defaults to female voice)
        
        Yields:
            PCM 16-bit audio chunks at 16kHz
        """
        voice = voice or self.voice_id
        
        try:
            logger.info(f"🎵 Generating audio for: '{text[:50]}...'")
            
            # Run inference in thread pool to avoid blocking event loop
            audio_array = await asyncio.to_thread(
                self._synthesize_audio, text, voice
            )
            
            # Resample to 16kHz if needed
            if self.sample_rate != self.target_sample_rate:
                audio_array = await asyncio.to_thread(
                    self._resample_audio, audio_array
                )
            
            # Convert to PCM 16-bit format
            pcm_data = self._convert_to_pcm16(audio_array)
            
            # Stream in chunks
            total_bytes = len(pcm_data)
            chunk_size = self.chunk_samples * 2  # 2 bytes per sample (16-bit)
            
            for i in range(0, total_bytes, chunk_size):
                chunk = pcm_data[i:i + chunk_size]
                yield chunk
                
                # Small delay to simulate real-time streaming
                await asyncio.sleep(0.01)
            
            logger.info("✅ Audio generation complete")
            
        except Exception as e:
            logger.error(f"❌ Audio generation failed: {e}")
            raise
    
    def _synthesize_audio(self, text: str, voice: str) -> np.ndarray:
        """
        Core synthesis function (runs in thread pool).
        
        Note: This is a placeholder implementation.
        Actual Kokoro API may differ - adjust based on model documentation.
        """
        try:
            with torch.no_grad():
                # Tokenize input text
                inputs = self.tokenizer(
                    text,
                    return_tensors="pt",
                    padding=True,
                    truncation=True,
                    max_length=512
                ).to(self.device)
                
                # Generate audio
                # Note: Adjust this based on actual Kokoro model API
                # This is a generic placeholder
                outputs = self.model.generate(
                    **inputs,
                    voice_preset=voice,  # May need adjustment
                    do_sample=True,
                    max_length=1024
                )
                
                # Extract audio waveform
                # Note: Output format depends on Kokoro's implementation
                if hasattr(outputs, 'audio'):
                    audio = outputs.audio
                elif isinstance(outputs, torch.Tensor):
                    audio = outputs
                else:
                    audio = outputs[0]
                
                # Convert to numpy
                audio_np = audio.cpu().numpy().squeeze()
                
                return audio_np
                
        except Exception as e:
            logger.error(f"Synthesis error: {e}")
            # Generate silent audio as fallback
            return np.zeros(int(self.sample_rate * 2), dtype=np.float32)
    
    def _resample_audio(self, audio: np.ndarray) -> np.ndarray:
        """Resample audio from native rate to 16kHz."""
        from scipy import signal
        
        # Calculate resampling ratio
        ratio = self.target_sample_rate / self.sample_rate
        num_samples = int(len(audio) * ratio)
        
        # Resample using scipy
        resampled = signal.resample(audio, num_samples)
        
        return resampled.astype(np.float32)
    
    def _convert_to_pcm16(self, audio: np.ndarray) -> bytes:
        """Convert float32 audio to PCM 16-bit bytes."""
        # Normalize to [-1, 1]
        if audio.max() > 1.0 or audio.min() < -1.0:
            audio = audio / np.max(np.abs(audio))
        
        # Convert to 16-bit PCM
        pcm16 = (audio * 32767).astype(np.int16)
        
        return pcm16.tobytes()
    
    async def text_to_audio_stream(self, text: str) -> AsyncGenerator[bytes, None]:
        """
        Main public API: Convert text to streaming audio chunks.
        
        Args:
            text: Text to speak
        
        Yields:
            PCM 16-bit audio chunks ready for WebSocket transmission
        """
        async for chunk in self.generate_audio_chunks(text):
            yield chunk
    
    def cleanup(self):
        """Release model resources."""
        if hasattr(self, 'model'):
            del self.model
            del self.tokenizer
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            logger.info("🧹 Kokoro TTS resources cleaned up")


# Singleton instance getter
def get_tts_service() -> KokoroTTSService:
    """Get or create TTS service singleton."""
    return KokoroTTSService()
