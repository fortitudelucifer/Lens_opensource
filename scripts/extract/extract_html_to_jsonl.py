"""
extract_html_to_jsonl.py
从微信导出的 HTML 文件中提取 chatMessages 数组，并从 CSV 补充元数据字段，
转换为 P1_messages_raw.jsonl

数据源说明：
- HTML: 消息内容完整（小程序详情、引用消息、文件信息等）
- CSV: 元数据完整（localId, TalkerId, Sender, Remark, NickName, StrTime）

合并策略：以 HTML 为主，通过 timestamp+type+is_send 匹配 CSV 补充元数据

输出字段规范（与 demo 工作空间一致）：
- seq_in_html: HTML 中的消息序号（从 0 开始）
- msg_uid: P1:{MsgSvrID}
- MsgSvrID: 服务器消息ID
- token: 消息 token
- ts: Unix 时间戳
- time_local: 本地时间字符串 (YYYY-MM-DD HH:MM:SS)
- speaker: ME/OTHER
- type: 消息类型
- sub_type: 子类型
- modality: 模态类型 (text/image/voice/video/sticker/link_or_file/location/contact/system)
- text_raw: 原始文本内容
- media_path: 媒体文件路径
- voice_length: 语音时长（毫秒）
- voice_to_text: 语音转文字
- quote_svrid: 引用消息的 MsgSvrID（仅 sub_type=57）
- quote_type: 引用消息的类型（仅 sub_type=57）
- quote_text: 引用消息的文本（仅 sub_type=57）

依赖: pip install json5
"""
import json
import re
import csv
import sys
import argparse
from pathlib import Path
from datetime import datetime
from html import unescape

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

try:
    import json5
except ImportError:
    print("Error: json5 not installed. Run: pip install json5")
    sys.exit(1)

from _common.path_utils import get_export_dir, get_messages_path, get_workspace_name, get_root


def find_export_files(export_dir: Path) -> tuple[Path, Path]:
    """
    自动查找导出目录中的 HTML 和 CSV 文件
    返回 (html_path, csv_path)
    """
    if not export_dir.exists():
        raise FileNotFoundError(f"Export directory not found: {export_dir}")
    
    html_files = list(export_dir.glob("*.html"))
    csv_files = list(export_dir.glob("*.csv"))
    
    if not html_files:
        raise FileNotFoundError(f"No HTML files found in {export_dir}")
    if not csv_files:
        raise FileNotFoundError(f"No CSV files found in {export_dir}")
    
    # 优先选择同名的 HTML 和 CSV
    html_files.sort()
    csv_files.sort()
    
    html_path = html_files[0]
    csv_path = csv_files[0]
    
    # 尝试找同名文件
    html_stem = html_path.stem
    for csv_file in csv_files:
        if csv_file.stem == html_stem:
            csv_path = csv_file
            break
    
    return html_path, csv_path


def _find_array_start(html: str) -> int:
    """找到 chatMessages = [ 的 '[' 位置"""
    m = re.search(r'\bchatMessages\b\s*=\s*\[', html)
    if not m:
        raise ValueError("找不到 'chatMessages = ['")
    return m.end() - 1


def _extract_bracket_balanced(html: str, start_idx: int) -> str:
    """从 start_idx 开始做括号配对抽取"""
    if start_idx < 0 or start_idx >= len(html) or html[start_idx] != '[':
        raise ValueError("start_idx 必须指向 '['")

    depth = 0
    in_str = False
    str_ch = ""
    escape = False

    for i in range(start_idx, len(html)):
        ch = html[i]
        if in_str:
            if escape:
                escape = False
                continue
            if ch == '\\':
                escape = True
                continue
            if ch == str_ch:
                in_str = False
                str_ch = ""
            continue
        if ch == '"' or ch == "'":
            in_str = True
            str_ch = ch
            continue
        if ch == '[':
            depth += 1
        elif ch == ']':
            depth -= 1
            if depth == 0:
                return html[start_idx:i+1]

    raise ValueError("括号配对失败")


def extract_chatmessages_array(html_path: Path) -> list[dict]:
    """从 HTML 文件中提取 chatMessages 数组"""
    print(f"  Reading HTML file: {html_path}")
    html = html_path.read_text(encoding="utf-8", errors="replace")
    print(f"  HTML size: {len(html):,} bytes")
    
    print("  Finding chatMessages array...")
    start = _find_array_start(html)
    
    print("  Extracting array (bracket-balanced)...")
    arr_text = _extract_bracket_balanced(html, start)
    print(f"  Array text size: {len(arr_text):,} bytes")

    print("  Parsing with json5...")
    data = json5.loads(arr_text)
    if not isinstance(data, list):
        raise TypeError(f"解析结果不是list，而是 {type(data)}")
    
    return data


def load_csv_metadata(csv_path: Path) -> dict[str, dict]:
    """从 CSV 文件加载元数据，以 timestamp_type_is_send 为 key"""
    print(f"  Reading CSV file: {csv_path}")
    metadata = {}
    
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            key = f"{row.get('CreateTime', '')}_{row.get('Type', '')}_{row.get('IsSender', '')}"
            metadata[key] = {
                'localId': row.get('localId', ''),
                'TalkerId': row.get('TalkerId', ''),
                'Sender': row.get('Sender', ''),
                'Remark': row.get('Remark', ''),
                'NickName': row.get('NickName', ''),
                'StrTime': row.get('StrTime', ''),
            }
    
    print(f"  Loaded {len(metadata):,} CSV records")
    return metadata


def get_modality(msg_type: int, sub_type: int) -> str:
    """根据消息类型返回模态"""
    if msg_type == 1:
        return "text"
    elif msg_type == 3:
        return "image"
    elif msg_type == 34:
        return "voice"
    elif msg_type == 43:
        return "video"
    elif msg_type == 47:
        return "sticker"
    elif msg_type == 48:
        return "location"
    elif msg_type == 42:
        return "contact"
    elif msg_type == 49:
        return "link_or_file"
    elif msg_type in [0, 10000]:
        return "system"
    else:
        return "unknown"


def normalize_message(msg: dict, seq: int, csv_meta: dict, me_names: set) -> dict:
    """
    标准化消息格式，与 demo 工作空间一致
    """
    # 解码 HTML 实体
    text = msg.get('text', '')
    if isinstance(text, str):
        text = unescape(text)
    
    msg_type = msg.get('type', 0)
    sub_type = msg.get('sub_type', 0)
    is_send = msg.get('is_send', 0)
    timestamp = msg.get('timestamp', 0)
    msg_svr_id = str(msg.get('MsgSvrID', ''))
    
    # 计算 time_local
    time_local = ""
    if timestamp:
        try:
            dt = datetime.fromtimestamp(timestamp)
            time_local = dt.strftime('%Y-%m-%d %H:%M:%S')
        except:
            pass
    
    # 从 CSV 获取发送者信息，判断 speaker
    csv_key = f"{timestamp}_{msg_type}_{is_send}"
    speaker = "ME" if is_send == 1 else "OTHER"
    
    if csv_key in csv_meta:
        meta = csv_meta[csv_key]
        sender_name = meta.get('Remark', '') or meta.get('NickName', '')
        if sender_name in me_names:
            speaker = "ME"
    
    # 特殊处理：撤回消息需要根据 text_raw 内容判断 speaker
    if msg_type in [0, 10000] and text:
        if 'You recalled' in text or '你撤回' in text:
            # "You recalled a message" 或 "你撤回了一条消息" 表示我撤回的
            speaker = "ME"
        elif ('recalled a message' in text or '撤回了一条消息' in text) and ('\"' in text or '"' in text):
            # "\"某人\" recalled a message" 或 "\"某人\" 撤回了一条消息" 表示对方撤回的
            speaker = "OTHER"
    
    # 基础字段
    result = {
        'seq_in_html': seq,
        'msg_uid': f"P1:{msg_svr_id}" if msg_svr_id else None,
        'MsgSvrID': msg_svr_id,
        'token': msg.get('token', ''),
        'ts': timestamp,
        'time_local': time_local,
        'speaker': speaker,
        'type': msg_type,
        'sub_type': sub_type,
        'modality': get_modality(msg_type, sub_type),
        'text_raw': text,
        'media_path': None,
        'voice_length': None,
        'voice_to_text': None,
    }
    
    # 根据消息类型设置 media_path 和其他字段
    def normalize_path(p):
        """标准化路径，去掉 ./ 前缀，添加 raw/ 前缀"""
        if not p:
            return None
        # 去掉 ./ 前缀
        if p.startswith('./'):
            p = p[2:]
        # 添加 raw/ 前缀
        if not p.startswith('raw/') and not p.startswith('http'):
            p = f"raw/{p}"
        return p
    
    if msg_type == 3:  # 图片
        result['media_path'] = normalize_path(text)
        result['text_raw'] = result['media_path']
    
    elif msg_type == 34:  # 语音
        result['media_path'] = normalize_path(text)
        result['text_raw'] = result['media_path']
        result['voice_length'] = msg.get('voice_length', 0)
        result['voice_to_text'] = msg.get('voice_to_text', '')
    
    elif msg_type == 43:  # 视频
        result['media_path'] = normalize_path(text)
        result['text_raw'] = result['media_path']
    
    elif msg_type == 47:  # 表情包
        # 表情包 URL 在 text 字段
        result['media_path'] = normalize_path(text)
        result['text_raw'] = result['media_path']
    
    elif msg_type == 49:  # 复合消息
        if sub_type == 57:  # 引用/回复
            result['quote_svrid'] = msg.get('svrid', '')
            result['quote_type'] = msg.get('refermsg_type')
            refer_text = msg.get('refer_text', '')
            if isinstance(refer_text, str):
                refer_text = unescape(refer_text)
            result['quote_text'] = refer_text
            # 引用消息的 text_raw 是回复内容（纯文本，不是路径）
            result['text_raw'] = text if text else None
            result['media_path'] = None  # 引用消息没有媒体文件
        
        elif sub_type == 6:  # 文件
            file_name = msg.get('file_name', '')
            result['text_raw'] = normalize_path(text)
            result['media_path'] = result['text_raw']
            result['file_name'] = file_name
            result['file_size'] = msg.get('file_size', '')
        
        elif sub_type in [5, 33, 36, 51, 19]:  # 链接/小程序/视频号/合并转发
            result['text_raw'] = msg.get('title', '') or text
            result['link_url'] = msg.get('url', '')
            result['link_title'] = msg.get('title', '')
            if sub_type in [33, 36]:
                result['miniprogram_appid'] = msg.get('appid', '')
    
    elif msg_type == 48:  # 位置
        result['location_x'] = msg.get('x')
        result['location_y'] = msg.get('y')
        result['location_label'] = msg.get('label', '')
        result['location_poiname'] = msg.get('poiname', '')
    
    elif msg_type == 42:  # 名片
        result['contact_nickname'] = msg.get('nickname', '')
        result['contact_username'] = msg.get('username', '')
    
    return result


def process_messages(html_messages: list[dict], csv_meta: dict, me_names: set) -> list[dict]:
    """处理所有消息"""
    result = []
    for seq, msg in enumerate(html_messages):
        normalized = normalize_message(msg, seq, csv_meta, me_names)
        result.append(normalized)
    return result


def clean_surrogates(obj):
    """递归清理字符串中的代理字符"""
    if isinstance(obj, str):
        return obj.encode('utf-8', errors='surrogatepass').decode('utf-8', errors='replace')
    elif isinstance(obj, dict):
        return {k: clean_surrogates(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [clean_surrogates(item) for item in obj]
    return obj


def write_jsonl(messages: list[dict], out_path: Path) -> None:
    """将消息列表写入 JSONL 文件"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        for obj in messages:
            cleaned = clean_surrogates(obj)
            f.write(json.dumps(cleaned, ensure_ascii=False) + "\n")


def analyze_messages(messages: list[dict]) -> dict:
    """分析消息统计信息"""
    stats = {
        "total": len(messages),
        "by_type": {},
        "by_sub_type": {},
        "by_modality": {},
        "by_speaker": {},
        "date_range": {"min": None, "max": None},
    }
    
    for msg in messages:
        msg_type = msg.get("type", "unknown")
        stats["by_type"][msg_type] = stats["by_type"].get(msg_type, 0) + 1
        
        if msg_type == 49:
            sub_type = msg.get("sub_type", "unknown")
            stats["by_sub_type"][sub_type] = stats["by_sub_type"].get(sub_type, 0) + 1
        
        modality = msg.get("modality", "unknown")
        stats["by_modality"][modality] = stats["by_modality"].get(modality, 0) + 1
        
        speaker = msg.get("speaker", "unknown")
        stats["by_speaker"][speaker] = stats["by_speaker"].get(speaker, 0) + 1
        
        time_local = msg.get("time_local", "")
        if time_local:
            date_str = time_local[:10]
            if stats["date_range"]["min"] is None or date_str < stats["date_range"]["min"]:
                stats["date_range"]["min"] = date_str
            if stats["date_range"]["max"] is None or date_str > stats["date_range"]["max"]:
                stats["date_range"]["max"] = date_str
    
    return stats


def print_stats(stats: dict):
    """打印统计信息"""
    print(f"\n=== 消息统计 ===")
    print(f"总消息数: {stats['total']:,}")
    
    print(f"\n按 type 分布:")
    type_names = {
        0: "系统消息(旧)", 1: "文本", 3: "图片", 34: "语音", 42: "名片",
        43: "视频", 47: "表情包", 48: "位置", 49: "复合消息", 10000: "系统消息",
    }
    for t, count in sorted(stats["by_type"].items(), key=lambda x: -x[1]):
        name = type_names.get(t, "")
        print(f"  type {t} ({name}): {count:,}")
    
    if stats["by_sub_type"]:
        print(f"\ntype 49 的 sub_type 分布:")
        sub_type_names = {
            5: "链接分享", 6: "文件传输", 8: "GIF表情", 19: "合并转发",
            33: "小程序(分享)", 36: "小程序(卡片)", 51: "视频号", 57: "引用/回复",
        }
        for st, count in sorted(stats["by_sub_type"].items(), key=lambda x: -x[1]):
            name = sub_type_names.get(st, "")
            print(f"  sub_type {st} ({name}): {count:,}")
    
    print(f"\n按 modality 分布:")
    for m, count in sorted(stats["by_modality"].items(), key=lambda x: -x[1]):
        print(f"  {m}: {count:,}")
    
    print(f"\n按 speaker 分布:")
    for s, count in sorted(stats["by_speaker"].items(), key=lambda x: -x[1]):
        print(f"  {s}: {count:,}")
    
    if stats["date_range"]["min"]:
        print(f"\n日期范围: {stats['date_range']['min']} ~ {stats['date_range']['max']}")


def main():
    parser = argparse.ArgumentParser(description="从微信导出HTML+CSV提取消息到JSONL")
    parser.add_argument("--html", type=str, help="指定HTML文件路径")
    parser.add_argument("--csv", type=str, help="指定CSV文件路径")
    parser.add_argument("--output", type=str, help="指定输出JSONL路径")
    parser.add_argument("--dry-run", action="store_true", help="仅分析，不写入文件")
    parser.add_argument("--no-csv", action="store_true", help="不使用CSV补充元数据")
    parser.add_argument("--me-names", type=str, default="Me,MyNickName", 
                        help="我的名称列表，逗号分隔（用于判断 speaker）")
    args = parser.parse_args()
    
    print(f"=== HTML+CSV to JSONL Extractor ===")
    print(f"Workspace: {get_workspace_name()}")
    print(f"Root: {get_root()}")
    
    export_dir = get_export_dir()
    print(f"\nExport directory: {export_dir}")
    
    # 确定文件路径
    if args.html:
        html_path = Path(args.html)
        csv_path = Path(args.csv) if args.csv else None
    else:
        html_path, csv_path = find_export_files(export_dir)
    
    print(f"HTML file: {html_path}")
    if csv_path and not args.no_csv:
        print(f"CSV file: {csv_path}")
    
    out_path = Path(args.output) if args.output else get_messages_path()
    print(f"Output file: {out_path}")
    
    # 解析 me_names
    me_names = set(n.strip() for n in args.me_names.split(',') if n.strip())
    print(f"ME names: {me_names}")
    
    # 提取 HTML 消息
    print(f"\n--- Extracting from HTML ---")
    html_messages = extract_chatmessages_array(html_path)
    print(f"  Extracted {len(html_messages):,} messages from HTML")
    
    # 加载 CSV 元数据
    csv_meta = {}
    if csv_path and not args.no_csv:
        print(f"\n--- Loading CSV metadata ---")
        csv_meta = load_csv_metadata(csv_path)
    
    # 处理消息
    print(f"\n--- Processing messages ---")
    messages = process_messages(html_messages, csv_meta, me_names)
    print(f"  Processed {len(messages):,} messages")
    
    # 分析统计
    stats = analyze_messages(messages)
    print_stats(stats)
    
    # 显示示例
    if messages:
        print(f"\n--- Sample messages ---")
        print(f"First message keys: {list(messages[0].keys())}")
        
        for msg in messages[:20]:
            if msg.get("type") == 1:
                print(f"\nSample text message:")
                print(f"  seq_in_html: {msg.get('seq_in_html')}")
                print(f"  msg_uid: {msg.get('msg_uid')}")
                print(f"  time_local: {msg.get('time_local')}")
                print(f"  speaker: {msg.get('speaker')}")
                print(f"  modality: {msg.get('modality')}")
                text = msg.get('text_raw', '')
                print(f"  text_raw: {text[:80]}{'...' if len(str(text)) > 80 else ''}")
                break
    
    # 写入文件
    if args.dry_run:
        print(f"\n[Dry run] Would write {len(messages):,} messages to: {out_path}")
    else:
        print(f"\n--- Writing JSONL ---")
        write_jsonl(messages, out_path)
        print(f"Done. Wrote {len(messages):,} messages to: {out_path}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
