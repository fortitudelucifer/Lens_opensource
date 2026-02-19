"""
extract_quote_info.py
Extract quote/reference message information from HTML and update P1_messages_raw.jsonl.

Type 49, sub_type 57 messages contain:
- svrid: The MsgSvrID of the referenced message
- refermsg_type: The type of the referenced message
- refer_text: The text content of the referenced message (prefixed with speaker name)
"""
import json
import re
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from _common.path_utils import get_export_dir, get_messages_path, get_workspace_name
from _common.anonymizer import anonymize_speaker_prefix


def find_html_file():
    """
    自动查找导出目录中的 HTML 文件
    优先查找与工作空间名称匹配的文件，否则返回第一个 .html 文件
    """
    export_dir = get_export_dir()
    
    if not export_dir.exists():
        raise FileNotFoundError(f"Export directory not found: {export_dir}")
    
    html_files = list(export_dir.glob("*.html"))
    
    if not html_files:
        raise FileNotFoundError(f"No HTML files found in {export_dir}")
    
    # 如果只有一个 HTML 文件，直接返回
    if len(html_files) == 1:
        return html_files[0]
    
    # 多个文件时，返回第一个（按字母顺序）
    html_files.sort()
    print(f"  Found {len(html_files)} HTML files, using: {html_files[0].name}")
    return html_files[0]


def extract_messages_from_html(html_path):
    """Extract all message JSON objects from the HTML file."""
    with open(html_path, "r", encoding="utf-8") as f:
        content = f.read()
    
    # Find all JSON message objects in the HTML
    # The format is: {"type": 49, "sub_type": 57, ...},
    pattern = r'\{"type":\s*\d+,\s*"sub_type":\s*\d+[^}]+\}'
    matches = re.findall(pattern, content)
    
    messages = []
    for match in matches:
        try:
            # Clean up the JSON string
            msg = json.loads(match)
            messages.append(msg)
        except json.JSONDecodeError:
            continue
    
    return messages


def build_quote_lookup(html_messages):
    """Build a lookup dict from MsgSvrID -> quote info for type 49, sub_type 57 messages."""
    lookup = {}
    for msg in html_messages:
        if msg.get("type") == 49 and msg.get("sub_type") == 57:
            msg_svr_id = msg.get("MsgSvrID")
            if msg_svr_id:
                # Anonymize the quote text
                raw_quote_text = msg.get("refer_text")
                anonymized_quote_text = anonymize_speaker_prefix(raw_quote_text)
                
                lookup[msg_svr_id] = {
                    "quote_svrid": msg.get("svrid"),  # Referenced message ID
                    "quote_type": msg.get("refermsg_type"),  # Type of referenced message
                    "quote_text": anonymized_quote_text,  # Anonymized text of referenced message
                }
    return lookup


def main():
    print(f"Workspace: {get_workspace_name()}")
    
    print("Finding HTML file...")
    html_file = find_html_file()
    print(f"  Using: {html_file}")
    
    messages_file = get_messages_path()
    print(f"  Messages file: {messages_file}")
    
    print("Loading HTML file...")
    html_messages = extract_messages_from_html(html_file)
    print(f"  Extracted {len(html_messages)} messages from HTML.")
    
    print("Building quote lookup...")
    quote_lookup = build_quote_lookup(html_messages)
    print(f"  Found {len(quote_lookup)} messages with quote info.")
    
    print("Loading existing messages...")
    messages = []
    with open(messages_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    messages.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    print(f"  Loaded {len(messages)} messages.")
    
    # Update messages with quote info
    updated_count = 0
    for msg in messages:
        msg_uid = msg.get("msg_uid", "")
        # Extract MsgSvrID from msg_uid (format: "P1:1234567890")
        if ":" in msg_uid:
            msg_svr_id = msg_uid.split(":")[1]
        else:
            msg_svr_id = msg.get("MsgSvrID")
        
        if msg_svr_id and msg_svr_id in quote_lookup:
            quote_info = quote_lookup[msg_svr_id]
            msg["quote_svrid"] = quote_info["quote_svrid"]
            msg["quote_type"] = quote_info["quote_type"]
            msg["quote_text"] = quote_info["quote_text"]
            updated_count += 1
    
    print(f"  Updated {updated_count} messages with quote info.")
    
    # Write back
    print("Writing updated messages...")
    with open(messages_file, "w", encoding="utf-8") as f:
        for msg in messages:
            f.write(json.dumps(msg, ensure_ascii=False) + "\n")
    
    print(f"Done. Wrote {len(messages)} messages to: {messages_file}")
    
    # Show some examples
    if updated_count > 0:
        print("\nExample updated messages:")
        count = 0
        for msg in messages:
            if "quote_text" in msg and msg.get("quote_text"):
                print(f"  - [{msg.get('msg_uid')}] text_raw: {msg.get('text_raw')[:50] if msg.get('text_raw') else ''}")
                print(f"    quote_text: {msg.get('quote_text')[:50] if msg.get('quote_text') else ''}")
                count += 1
                if count >= 3:
                    break


if __name__ == "__main__":
    main()
