#!/usr/bin/env python3
"""
Image Loader Module - Phase 1

Provides safe image loading with:
- Magic bytes detection (zero-trust)
- PIL validation
- QC field generation
- Long image detection
"""

import os
import sys
from pathlib import Path
from typing import Optional, Dict, Any, Tuple
from PIL import Image
import json

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts._common.path_utils import get_path

# Try to import magic, fallback to basic detection
try:
    import magic
    HAS_MAGIC = True
except ImportError:
    HAS_MAGIC = False
    print("Warning: python-magic not installed, using basic format detection")


# Magic bytes signatures
MAGIC_SIGNATURES = {
    b'\xff\xd8\xff': ('image/jpeg', '.jpg'),
    b'\x89PNG\r\n\x1a\n': ('image/png', '.png'),
    b'GIF87a': ('image/gif', '.gif'),
    b'GIF89a': ('image/gif', '.gif'),
    b'RIFF': ('image/webp', '.webp'),  # WebP uses RIFF container
    b'BM': ('image/bmp', '.bmp'),
}


def detect_format_magic(file_path: str) -> Tuple[str, str]:
    """
    Detect image format using magic bytes (zero-trust).
    Returns (mime_type, extension).
    """
    if HAS_MAGIC:
        try:
            mime = magic.from_file(file_path, mime=True)
            ext_map = {
                'image/jpeg': '.jpg',
                'image/png': '.png',
                'image/gif': '.gif',
                'image/webp': '.webp',
                'image/bmp': '.bmp',
            }
            ext = ext_map.get(mime, '.unknown')
            return mime, ext
        except Exception:
            pass
    
    # Fallback: check magic bytes manually
    try:
        with open(file_path, 'rb') as f:
            header = f.read(16)
        
        for sig, (mime, ext) in MAGIC_SIGNATURES.items():
            if header.startswith(sig):
                # Special handling for WebP
                if sig == b'RIFF' and b'WEBP' in header[:12]:
                    return 'image/webp', '.webp'
                elif sig != b'RIFF':
                    return mime, ext
        
        return 'application/octet-stream', '.unknown'
    except Exception:
        return 'application/octet-stream', '.unknown'


def check_orientation_needed(boxes: list, img_w: int, img_h: int, threshold: float = 0.6) -> bool:
    """
    Check if image needs rotation based on text box dimensions.
    
    Logic: If a significant portion of text boxes are 'tall/vertical' (H > W),
    it might indicate the image is rotated 90 degrees.
    
    Args:
        boxes: List of boxes from PaddleOCR det
        img_w: Image width
        img_h: Image height
        threshold: Ratio of vertical boxes to trigger rotation
        
    Returns:
        bool: True if rotation is recommended
    """
    if not boxes or len(boxes) < 3:
        return False
        
    vertical_box_count = 0
    
    for box in boxes:
        # PaddleOCR format: [[x1,y1], [x2,y2], [x3,y3], [x4,y4]] OR [points, [text, conf]]
        points = box
        if len(box) == 2 and isinstance(box[0], list):
            points = box[0]
        
        # Calculate W and H of the box
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        w = max(xs) - min(xs)
        h = max(ys) - min(ys)
        
        # Vertical box: Height > 1.2 * Width
        if h > w * 1.2:
            vertical_box_count += 1
            
    vertical_ratio = vertical_box_count / len(boxes)
    return vertical_ratio > threshold


def load_image_safe(
    file_path: str,
    max_pixels: int = 200_000_000,  # ~200MP limit
    auto_rotate: bool = False,
    ocr_boxes: list = None  # Optional: pre-computed OCR boxes for rotation check
) -> Tuple[Optional[Image.Image], Dict[str, Any]]:
    """
    Safely load an image with full QC information.
    
    Args:
        file_path: Path to image file
        max_pixels: Max pixels limit (decompression bomb protection)
        auto_rotate: If True, auto-rotate image based on text orientation detection
        ocr_boxes: Pre-computed OCR detection boxes for rotation check
    
    Returns:
        (image, qc_dict) - image is None if decode fails
    """
    qc = {
        'ok': False,
        'file_path': file_path,
        'original_ext': Path(file_path).suffix.lower(),
        'detected_mime': None,
        'detected_ext': None,
        'format_mismatch': False,
        'width': None,
        'height': None,
        'megapixels': None,
        'is_long_image': False,
        'was_rotated': False,
        'rotation_angle': 0,
        'decode_error': None,
    }
    
    # Check file exists
    if not os.path.exists(file_path):
        qc['decode_error'] = 'file_not_found'
        return None, qc
    
    # Detect format via magic bytes
    detected_mime, detected_ext = detect_format_magic(file_path)
    qc['detected_mime'] = detected_mime
    qc['detected_ext'] = detected_ext
    qc['format_mismatch'] = (qc['original_ext'] != detected_ext)
    
    # Check if it's an image mime type
    if not detected_mime.startswith('image/'):
        qc['decode_error'] = f'not_an_image: {detected_mime}'
        return None, qc
    
    # Try to load with PIL
    try:
        # Set max pixels to avoid decompression bomb
        Image.MAX_IMAGE_PIXELS = max_pixels
        
        img = Image.open(file_path)
        img.load()  # Force load to catch truncated images
        
        # Get dimensions
        qc['width'] = img.size[0]
        qc['height'] = img.size[1]
        qc['megapixels'] = round(img.size[0] * img.size[1] / 1_000_000, 2)
        
        # Check for long image
        ratio = max(img.size) / min(img.size) if min(img.size) > 0 else 0
        qc['is_long_image'] = (ratio > 5.0) or (max(img.size) > 4096)
        
        # Convert to RGB for consistency
        if img.mode != 'RGB':
            img = img.convert('RGB')
        
        # Auto-rotate if enabled and OCR boxes provided
        if auto_rotate and ocr_boxes:
            need_rotation = check_orientation_needed(ocr_boxes, img.size[0], img.size[1])
            if need_rotation:
                # Rotate 90 degrees counter-clockwise (most common case for sideways text)
                img = img.rotate(90, expand=True)
                qc['was_rotated'] = True
                qc['rotation_angle'] = 90
                # Update dimensions after rotation
                qc['width'] = img.size[0]
                qc['height'] = img.size[1]
        
        qc['ok'] = True
        return img, qc
        
    except Image.DecompressionBombError:
        qc['decode_error'] = 'decompression_bomb'
        return None, qc
    except Exception as e:
        qc['decode_error'] = str(e)[:100]
        return None, qc


def get_image_path(media_path: str, raw_dir: Optional[str] = None) -> str:
    """
    Convert relative media_path to absolute path.
    media_path format: ./image/2025-06/xxx.jpg
    """
    if raw_dir is None:
        raw_dir = get_path('raw')
    
    # Handle paths relative to project root (starting with raw/)
    if media_path.startswith('raw/'):
        project_root = os.path.dirname(raw_dir.rstrip('/'))
        return os.path.join(project_root, media_path)
    
    # Handle relative paths (./image/... or image/...)
    if media_path.startswith('./'):
        media_path = media_path[2:]
    
    return os.path.join(raw_dir, media_path)


def append_error_log(error_entry: Dict[str, Any], log_path: Optional[str] = None):
    """Append an error entry to logs/errors.jsonl"""
    if log_path is None:
        log_path = os.path.join(get_path('root'), 'logs', 'errors.jsonl')
    
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    
    with open(log_path, 'a', encoding='utf-8') as f:
        f.write(json.dumps(error_entry, ensure_ascii=False) + '\n')


if __name__ == '__main__':
    # Test with a sample image
    from scripts._common.path_utils import PATHS
    raw_dir = PATHS.get('dirs', {}).get('raw', '/data/demo/raw')
    test_path = f"{raw_dir}/image/test.jpg"
    
    print(f"Testing loader with: {test_path}")
    img, qc = load_image_safe(test_path)
    
    print(f"\nQC Results:")
    for k, v in qc.items():
        print(f"  {k}: {v}")
    
    if img:
        print(f"\nImage loaded successfully: {img.size}, mode={img.mode}")
