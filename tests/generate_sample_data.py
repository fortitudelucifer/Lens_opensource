import os
import json
import wave
import struct
import math
from pathlib import Path
from PIL import Image

def create_sample_structure(base_dir):
    """Create the directory structure for sample data."""
    raw_dir = base_dir / "raw"
    dirs = [
        raw_dir / "image" / "2025-01",
        raw_dir / "voice" / "2025-01",
        raw_dir / "video" / "2025-01",
        raw_dir / "sticker" / "2025-01",
        raw_dir / "file" / "2025-01",
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)
    return raw_dir

def create_dummy_image(path):
    """Create a simple RGB image."""
    img = Image.new('RGB', (100, 100), color = 'red')
    img.save(path)
    print(f"Created dummy image: {path}")

def create_dummy_audio(path, duration_sec=1):
    """Create a simple sine wave audio file (WAV)."""
    # FunASR/Whisper can usually handle WAV even if extension is mp3 in some contexts, 
    # but the pipeline expects .mp3. FFMPEG is usually needed for MP3 encoding.
    # We will save as .wav and rename to .mp3 for testing purposes if the pipeline relies on extension,
    # or just keep as .wav if pipeline supports it. The pipeline globs *.mp3.
    # Let's try to save as .wav but name it .mp3, sophisticated decoders might detect format from header.
    # If not, this might fail, but it's a start.
    
    # Actually, simpler: write silence or noise.
    sample_rate = 16000
    n_frames = int(sample_rate * duration_sec)
    
    with wave.open(str(path), 'w') as obj:
        obj.setnchannels(1) # mono
        obj.setsampwidth(2) # 2 bytes
        obj.setframerate(sample_rate)
        
        # Generate silence/sine
        data = bytearray()
        for i in range(n_frames):
            value = int(32767.0 * math.sin(2.0 * math.pi * 400.0 * i / sample_rate))
            data.extend(struct.pack('<h', value))
            
        obj.writeframes(data)
    print(f"Created dummy audio: {path}")

def create_dummy_jsonl(raw_dir):
    """Create P1_messages_raw.jsonl with sample data."""
    messages = [
        {
            "seq_in_html": 1,
            "msg_uid": "P1:1001",
            "MsgSvrID": "1001",
            "token": "token1",
            "ts": 1735689600, # 2025-01-01 00:00:00
            "time_local": "2025-01-01 00:00:00",
            "speaker": "ME",
            "type": 1,
            "sub_type": 0,
            "modality": "text",
            "text_raw": "Hello, this is a test message.",
            "media_path": None
        },
        {
            "seq_in_html": 2,
            "msg_uid": "P1:1002",
            "MsgSvrID": "1002",
            "token": "token2",
            "ts": 1735689610,
            "time_local": "2025-01-01 00:00:10",
            "speaker": "OTHER",
            "type": 1,
            "sub_type": 0,
            "modality": "text",
            "text_raw": "Hi there! This is a reply.",
            "media_path": None
        },
        {
            "seq_in_html": 3,
            "msg_uid": "P1:1003",
            "MsgSvrID": "1003",
            "token": "token3",
            "ts": 1735689620,
            "time_local": "2025-01-01 00:00:20",
            "speaker": "ME",
            "type": 3,
            "sub_type": 0,
            "modality": "image",
            "text_raw": "raw/image/2025-01/test_image.jpg",
            "media_path": "raw/image/2025-01/test_image.jpg"
        },
        {
            "seq_in_html": 4,
            "msg_uid": "P1:1004",
            "MsgSvrID": "1004",
            "token": "token4",
            "ts": 1735689630,
            "time_local": "2025-01-01 00:00:30",
            "speaker": "OTHER",
            "type": 34,
            "sub_type": 0,
            "modality": "voice",
            "text_raw": "raw/voice/2025-01/test_voice.mp3",
            "media_path": "raw/voice/2025-01/test_voice.mp3",
            "voice_length": 1000
        }
    ]
    
    jsonl_path = raw_dir / "P1_messages_raw.jsonl"
    with open(jsonl_path, 'w', encoding='utf-8') as f:
        for msg in messages:
            f.write(json.dumps(msg, ensure_ascii=False) + "\n")
    print(f"Created dummy jsonl: {jsonl_path}")

def main():
    base_dir = Path("tests/sample_data")
    if base_dir.exists():
        import shutil
        shutil.rmtree(base_dir)
    
    raw_dir = create_sample_structure(base_dir)
    
    # Create media files
    create_dummy_image(raw_dir / "image/2025-01/test_image.jpg")
    
    # Note: Saving as .mp3 but content is WAV. Most decoders handle this.
    # If strict MP3 decoding is required, this might fail in the pipeline.
    create_dummy_audio(raw_dir / "voice/2025-01/test_voice.mp3") 
    
    # Create metadata
    create_dummy_jsonl(raw_dir)
    
    print("\nSample data generation complete at tests/sample_data/")
    print("You can verify the pipeline using:")
    print("python run_all_pipelines.py --root tests/sample_data --dry-run")

if __name__ == "__main__":
    main()
