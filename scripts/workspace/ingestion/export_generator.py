"""
export_generator.py
从 P1_messages_raw.jsonl 生成 export/ 目录下的 CSV、HTML、MD 文件

功能：
- generate_csv(): 生成兼容现有 export 格式的 CSV
- generate_markdown(): 按日期分组生成 Markdown
- generate_html(): 生成包含 chatMessages 数组的 HTML（可被 extract_html_to_jsonl.py 解析）

运行方式：
    python -m pytest tests/workspace/ingestion/test_export_generator.py -v
"""

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Optional


class ExportGenerator:
    """从 P1_messages_raw.jsonl 生成 export/ 文件"""

    # ── CSV ────────────────────────────────────────────────────────────

    CSV_COLUMNS = [
        "localId", "TalkerId", "Type", "SubType", "IsSender",
        "CreateTime", "Status", "StrContent", "StrTime",
        "Remark", "NickName", "Sender",
    ]

    def generate_csv(self, records: list[dict], output_path: Path) -> None:
        """生成 CSV（兼容现有 export 格式）

        字段映射：
        - localId   → seq_in_html 或行索引
        - TalkerId  → 1 (ME) / 2 (OTHER)
        - Type      → type
        - SubType   → sub_type
        - IsSender  → 1 (ME) / 0 (OTHER)
        - CreateTime→ ts
        - Status    → 0
        - StrContent→ text_raw
        - StrTime   → time_local 或从 ts 格式化
        - Remark / NickName / Sender → speaker 名称部分
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=self.CSV_COLUMNS)
            writer.writeheader()

            for idx, rec in enumerate(records):
                is_me = self._is_me(rec.get("speaker", ""))
                speaker_name = self._extract_speaker_name(rec.get("speaker", ""))
                str_time = rec.get("time_local", "") or self._format_ts(rec.get("ts"))

                row = {
                    "localId": rec.get("seq_in_html", idx) if rec.get("seq_in_html", -1) >= 0 else idx,
                    "TalkerId": 1 if is_me else 2,
                    "Type": rec.get("type", 0),
                    "SubType": rec.get("sub_type", 0),
                    "IsSender": 1 if is_me else 0,
                    "CreateTime": rec.get("ts", 0),
                    "Status": 0,
                    "StrContent": rec.get("text_raw", ""),
                    "StrTime": str_time,
                    "Remark": speaker_name,
                    "NickName": speaker_name,
                    "Sender": speaker_name,
                }
                writer.writerow(row)

    # ── Markdown ───────────────────────────────────────────────────────

    def generate_markdown(self, records: list[dict], output_path: Path) -> None:
        """生成 Markdown（按日期分组）

        格式：
        ## YYYY-MM-DD
        **HH:MM:SS 说话人**: 消息内容
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # 按日期分组
        groups: dict[str, list[dict]] = {}
        for rec in records:
            ts = rec.get("ts", 0)
            date_str = self._format_date(ts)
            groups.setdefault(date_str, []).append(rec)

        lines: list[str] = []
        for date_str in sorted(groups.keys()):
            lines.append(f"## {date_str}\n")
            for rec in groups[date_str]:
                time_str = self._format_time(rec.get("ts", 0))
                speaker = self._extract_speaker_name(rec.get("speaker", ""))
                content = rec.get("text_raw", "")
                lines.append(f"**{time_str} {speaker}**: {content}\n")
            lines.append("")  # 日期组之间空行

        output_path.write_text("\n".join(lines), encoding="utf-8")

    # ── HTML ───────────────────────────────────────────────────────────

    def generate_html(self, records: list[dict], output_path: Path) -> None:
        """生成 HTML（包含 chatMessages 数组）

        生成的 HTML 包含 `var chatMessages = [...]`，
        可被现有 extract_html_to_jsonl.py 的 extract_chatmessages_array() 解析。
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # 构建 chatMessages 数组
        chat_messages = []
        for idx, rec in enumerate(records):
            msg = self._record_to_chat_message(rec, idx)
            chat_messages.append(msg)

        # 序列化为 JSON（ensure_ascii=False 保留中文）
        messages_json = json.dumps(chat_messages, ensure_ascii=False, indent=2)

        html_content = self._build_html(messages_json)
        output_path.write_text(html_content, encoding="utf-8")

    # ── 内部方法 ───────────────────────────────────────────────────────

    @staticmethod
    def _is_me(speaker: str) -> bool:
        """判断 speaker 是否为 ME"""
        return speaker == "ME"

    @staticmethod
    def _extract_speaker_name(speaker: str) -> str:
        """从 speaker 字段提取显示名称

        ME → ME
        OTHER → OTHER
        OTHER:张三 → 张三
        """
        if speaker.startswith("OTHER:"):
            return speaker[6:]
        return speaker

    @staticmethod
    def _format_ts(ts: Optional[int]) -> str:
        """将 Unix 时间戳格式化为 YYYY-MM-DD HH:MM:SS"""
        if not ts or not isinstance(ts, int) or ts <= 0:
            return ""
        try:
            return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
        except (OSError, ValueError, OverflowError):
            return ""

    @staticmethod
    def _format_date(ts: int) -> str:
        """从时间戳提取日期 YYYY-MM-DD"""
        if not ts or not isinstance(ts, int) or ts <= 0:
            return "1970-01-01"
        try:
            return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
        except (OSError, ValueError, OverflowError):
            return "1970-01-01"

    @staticmethod
    def _format_time(ts: int) -> str:
        """从时间戳提取时间 HH:MM:SS"""
        if not ts or not isinstance(ts, int) or ts <= 0:
            return "00:00:00"
        try:
            return datetime.fromtimestamp(ts).strftime("%H:%M:%S")
        except (OSError, ValueError, OverflowError):
            return "00:00:00"

    @staticmethod
    def _record_to_chat_message(rec: dict, idx: int) -> dict:
        """将 CanonicalMessage 记录转换为 chatMessages 数组元素

        生成的字段与 extract_html_to_jsonl.py 的 normalize_message() 期望的输入一致：
        - type, sub_type, is_send, timestamp, MsgSvrID, token, text
        """
        is_me = rec.get("speaker", "") == "ME"

        msg: dict = {
            "type": rec.get("type", 0),
            "sub_type": rec.get("sub_type", 0),
            "is_send": 1 if is_me else 0,
            "timestamp": rec.get("ts", 0),
            "MsgSvrID": rec.get("MsgSvrID", ""),
            "token": rec.get("token", ""),
            "text": rec.get("text_raw", ""),
        }

        # 语音附加字段
        if rec.get("voice_length") is not None:
            msg["voice_length"] = rec["voice_length"]
        if rec.get("voice_to_text") is not None:
            msg["voice_to_text"] = rec["voice_to_text"]

        # 引用消息附加字段 (sub_type=57)
        if rec.get("quote_svrid") is not None:
            msg["svrid"] = rec["quote_svrid"]
        if rec.get("quote_type") is not None:
            msg["refermsg_type"] = rec["quote_type"]
        if rec.get("quote_text") is not None:
            msg["refer_text"] = rec["quote_text"]

        # 文件附加字段 (sub_type=6)
        if rec.get("file_name") is not None:
            msg["file_name"] = rec["file_name"]
        if rec.get("file_size") is not None:
            msg["file_size"] = rec["file_size"]

        # 链接/小程序附加字段
        if rec.get("link_url") is not None:
            msg["url"] = rec["link_url"]
        if rec.get("link_title") is not None:
            msg["title"] = rec["link_title"]
        if rec.get("miniprogram_appid") is not None:
            msg["appid"] = rec["miniprogram_appid"]

        # 位置附加字段
        if rec.get("location_x") is not None:
            msg["x"] = rec["location_x"]
        if rec.get("location_y") is not None:
            msg["y"] = rec["location_y"]
        if rec.get("location_label") is not None:
            msg["label"] = rec["location_label"]

        # 名片附加字段
        if rec.get("contact_nickname") is not None:
            msg["nickname"] = rec["contact_nickname"]
        if rec.get("contact_username") is not None:
            msg["username"] = rec["contact_username"]

        return msg

    @staticmethod
    def _build_html(messages_json: str) -> str:
        """构建包含 chatMessages 的 HTML 文档"""
        return (
            "<!DOCTYPE html>\n"
            "<html>\n"
            "<head><meta charset=\"utf-8\"><title>Chat Export</title></head>\n"
            "<body>\n"
            "<script>\n"
            f"var chatMessages = {messages_json};\n"
            "</script>\n"
            "</body>\n"
            "</html>\n"
        )
