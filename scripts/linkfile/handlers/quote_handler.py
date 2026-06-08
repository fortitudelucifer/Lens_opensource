"""
QuoteHandler - 引用消息处理器

处理 sub_type=57 的引用消息，提取被引用消息的元数据。

引用消息包含以下信息：
- quote_svrid: 被引用消息的 MsgSvrID
- quote_type: 被引用消息的类型
- quote_text: 被引用消息的文本内容（已匿名化 speaker 前缀）

Requirements: 2.1, 2.2, 2.3
"""

from typing import Dict, Any, List

from scripts.linkfile.handlers.base import SubTypeHandler
from scripts._common.anonymizer import anonymize_speaker_prefix


class QuoteHandler(SubTypeHandler):
    """
    处理 sub_type=57 的引用消息
    
    引用消息是微信中对其他消息的引用/回复，包含被引用消息的 ID、类型和文本内容。
    处理器会从 html_quote_lookup 中获取引用信息，并对 quote_text 中的 speaker 前缀
    进行匿名化处理。
    
    Example:
        >>> handler = QuoteHandler()
        >>> msg = {'msg_uid': 'P1:123', 'MsgSvrID': '123', 'sub_type': 57}
        >>> html_quote_lookup = {
        ...     '123': {
        ...         'quote_svrid': '456',
        ...         'quote_type': 1,
        ...         'quote_text': 'UserB：原始消息内容'
        ...     }
        ... }
        >>> result = handler.extract(msg, html_quote_lookup)
        >>> result['link_sub_type']
        'quote'
        >>> result['quote_text']
        'OTHER: 原始消息内容'
    """
    
    @property
    def sub_types(self) -> List[int]:
        """返回此处理器支持的 sub_type 列表"""
        return [57]
    
    @property
    def link_sub_type(self) -> str:
        """返回统一的 link_sub_type 值"""
        return "quote"
    
    def extract(self, msg: Dict[str, Any], html_quote_lookup: Dict[str, Any]) -> Dict[str, Any]:
        """
        提取引用消息字段
        
        从 html_quote_lookup 中获取引用信息。如果消息已经包含引用字段（可能是
        之前通过 extract_quote_info.py 处理过），则直接使用这些字段。
        
        Args:
            msg: 原始消息记录，包含：
                - msg_uid: 消息唯一标识（格式：P1:MsgSvrID）
                - MsgSvrID: 服务器消息 ID
                - sub_type: 应为 57
                - quote_svrid: 被引用消息 ID（如已存在）
                - quote_type: 被引用消息类型（如已存在）
                - quote_text: 被引用消息文本（如已存在）
                
            html_quote_lookup: HTML 解析的引用信息查找表
                - 键为 MsgSvrID
                - 值为包含 quote_svrid, quote_type, quote_text 的字典
                
        Returns:
            Dict[str, Any]: 提取的字段字典
                {
                    "link_sub_type": "quote",
                    "quote_svrid": str,      # 被引用消息的 MsgSvrID
                    "quote_type": int,       # 被引用消息的类型
                    "quote_text": str        # 被引用消息的文本（已匿名化 speaker 前缀）
                }
        """
        result = {
            "link_sub_type": self.link_sub_type,
            "quote_svrid": None,
            "quote_type": None,
            "quote_text": None,
        }
        
        # 获取 MsgSvrID 用于查找引用信息
        msg_svr_id = self._get_msg_svr_id(msg)
        
        # 优先从 html_quote_lookup 获取引用信息
        if msg_svr_id and msg_svr_id in html_quote_lookup:
            quote_info = html_quote_lookup[msg_svr_id]
            result["quote_svrid"] = quote_info.get("quote_svrid")
            result["quote_type"] = quote_info.get("quote_type")
            # quote_text 可能已经在 build_quote_lookup 中匿名化过
            # 但为了安全起见，再次调用 anonymize_speaker_prefix
            raw_quote_text = quote_info.get("quote_text", "")
            result["quote_text"] = self._anonymize_quote_text(raw_quote_text)
        
        # 如果 html_quote_lookup 中没有，尝试从消息本身获取（可能已预处理）
        elif msg.get("quote_svrid") is not None:
            result["quote_svrid"] = msg.get("quote_svrid")
            result["quote_type"] = msg.get("quote_type")
            raw_quote_text = msg.get("quote_text", "")
            result["quote_text"] = self._anonymize_quote_text(raw_quote_text)
        
        return result
    
    def _get_msg_svr_id(self, msg: Dict[str, Any]) -> str:
        """
        从消息中提取 MsgSvrID
        
        msg_uid 格式为 "P1:MsgSvrID"，需要提取冒号后的部分。
        如果 msg_uid 不存在或格式不对，则尝试直接获取 MsgSvrID 字段。
        
        Args:
            msg: 原始消息记录
            
        Returns:
            str: MsgSvrID，如果无法获取则返回空字符串
        """
        msg_uid = msg.get("msg_uid", "")
        if ":" in msg_uid:
            return msg_uid.split(":")[1]
        return msg.get("MsgSvrID", "")
    
    def _anonymize_quote_text(self, text: str) -> str:
        """
        匿名化 quote_text 中的 speaker 前缀
        
        如果文本已经是 "ME: xxx" 或 "OTHER: xxx" 格式，则不再处理。
        否则调用 anonymize_speaker_prefix 进行匿名化。
        
        Args:
            text: 原始 quote_text
            
        Returns:
            str: 匿名化后的文本
        """
        if not text:
            return text
        
        # 检查是否已经匿名化（以 "ME: " 或 "OTHER: " 开头）
        if text.startswith("ME: ") or text.startswith("OTHER: "):
            return text
        
        return anonymize_speaker_prefix(text)
