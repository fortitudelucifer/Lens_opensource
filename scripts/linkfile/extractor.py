"""
LinkfileExtractor - Linkfile 模态主提取器
负责路由 type=49 消息到对应的子类型处理器
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from scripts.linkfile.handlers import (
    SubTypeHandler,
    QuoteHandler,
    LinkHandler,
    FileHandler,
    MiniprogramHandler,
    VideoChannelHandler,
    ChatHistoryHandler,
)

logger = logging.getLogger(__name__)


class LinkfileExtractor:
    """Linkfile 模态主提取器"""
    
    # 公共字段列表（从原始消息复制）
    COMMON_FIELDS = [
        'msg_uid', 'MsgSvrID', 'token', 'seq_in_html',
        'ts', 'time_local', 'speaker', 'type', 'sub_type',
        'modality', 'media_path', 'text_raw',
    ]
    
    def __init__(self, config: Dict[str, Any], workspace_root: Path):
        """
        初始化提取器
        
        Args:
            config: linkfile.yaml 配置
            workspace_root: 工作空间根目录
        """
        self.config = config
        self.workspace_root = workspace_root
        self.handlers: Dict[int, SubTypeHandler] = {}
        self._register_handlers()
    
    def _register_handlers(self):
        """注册所有子类型处理器"""
        handlers: List[SubTypeHandler] = [
            QuoteHandler(),
            LinkHandler(self.config.get('link_type_rules', [])),
            FileHandler(
                self.config.get('file_categories', {}),
                self.workspace_root
            ),
            MiniprogramHandler(self.config.get('miniprogram_apps', {})),
            VideoChannelHandler(),
            ChatHistoryHandler(),
        ]
        
        for handler in handlers:
            for sub_type in handler.sub_types:
                self.handlers[sub_type] = handler
                logger.debug(f"Registered handler for sub_type={sub_type}: {handler.__class__.__name__}")
    
    def extract_all(
        self,
        messages: List[Dict[str, Any]],
        html_quote_lookup: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        处理所有 type=49 消息
        
        Args:
            messages: P1_messages_raw.jsonl 中 type=49 的消息列表
            html_quote_lookup: HTML 解析的引用信息查找表
            
        Returns:
            提取结果列表
        """
        results = []
        for msg in messages:
            result = self._extract_one(msg, html_quote_lookup)
            if result:
                results.append(result)
        return results
    
    def _extract_one(
        self,
        msg: Dict[str, Any],
        html_quote_lookup: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        处理单条消息
        
        Args:
            msg: 原始消息记录
            html_quote_lookup: HTML 解析的引用信息查找表
            
        Returns:
            提取结果字典，处理失败时返回 None
        """
        sub_type = msg.get('sub_type')
        msg_uid = msg.get('msg_uid', 'unknown')
        
        # 构建公共字段
        common = self._build_common_fields(msg)
        
        # 获取对应的处理器
        handler = self.handlers.get(sub_type)
        
        if handler is None:
            logger.warning(f"Unknown sub_type={sub_type} for msg_uid={msg_uid}")
            return {
                **common,
                'link_sub_type': 'unknown',
            }
        
        try:
            # 调用处理器提取特定字段
            specific = handler.extract(msg, html_quote_lookup)
            return {**common, **specific}
        except Exception as e:
            logger.error(f"Failed to extract msg_uid={msg_uid}: {e}")
            return {
                **common,
                'link_sub_type': 'error',
                'error_message': str(e),
            }
    
    def _build_common_fields(self, msg: Dict[str, Any]) -> Dict[str, Any]:
        """
        从原始消息构建公共字段
        
        Args:
            msg: 原始消息记录
            
        Returns:
            公共字段字典
        """
        result = {}
        for field in self.COMMON_FIELDS:
            if field in msg or field in ['media_path']:
                value = msg.get(field)
                # 清理 text_raw 和 media_path 中错误的 "raw/" 前缀
                # 这是引用消息（sub_type=57）中的数据问题
                if field in ('text_raw', 'media_path') and isinstance(value, str):
                    value = self._strip_raw_prefix(value)
                result[field] = value
        return result
    
    def _strip_raw_prefix(self, value: str) -> str:
        """
        去除字符串开头错误的 'raw/' 前缀
        
        对于引用消息，text_raw 和 media_path 可能被错误地加上了 'raw/' 前缀，
        例如 'raw/噢？是啥' 应该是 '噢？是啥'。
        
        但要注意保留真正的文件路径，如 'raw/file/xxx.pdf' 不应被处理。
        
        Args:
            value: 原始字符串
            
        Returns:
            清理后的字符串
        """
        if not value:
            return value
        
        # 如果以 'raw/' 开头，但后面不是有效的子目录（file/, image/, video/ 等）
        # 则认为是错误的前缀，需要去除
        if value.startswith('raw/'):
            # 检查是否是真正的文件路径（包含有效的子目录）
            valid_subdirs = ('file/', 'image/', 'video/', 'voice/', 'sticker/', 'avatar/', 'emoji/', 'export/')
            remainder = value[4:]  # 去掉 'raw/' 后的部分
            
            # 如果剩余部分以有效子目录开头，说明是真正的文件路径，保留
            if any(remainder.startswith(subdir) for subdir in valid_subdirs):
                return value
            
            # 否则去掉 'raw/' 前缀
            return remainder
        
        return value
    
    def get_supported_sub_types(self) -> List[int]:
        """返回支持的 sub_type 列表"""
        return list(self.handlers.keys())
