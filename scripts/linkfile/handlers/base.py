"""
Linkfile 子类型处理器抽象基类 (SubType Handler Base Class)

功能：
- 定义所有 linkfile 子类型处理器的统一接口
- 每个处理器负责处理特定的 sub_type 消息
- 提取相应的元数据字段

支持的子类型：
- sub_type=57: 引用消息 (QuoteHandler)
- sub_type=5: 链接分享 (LinkHandler)
- sub_type=6: 文件传输 (FileHandler)
- sub_type=33,36: 小程序 (MiniprogramHandler)
- sub_type=51: 视频号 (VideoChannelHandler)
- sub_type=19: 聊天记录分享 (ChatHistoryHandler)

设计模式：
- 使用抽象基类（ABC）定义统一接口
- 每个子类型处理器继承 SubTypeHandler
- 实现三个抽象方法/属性：sub_types, link_sub_type, extract()

使用示例：
    from scripts.linkfile.handlers.base import SubTypeHandler
    
    class QuoteHandler(SubTypeHandler):
        @property
        def sub_types(self) -> List[int]:
            return [57]
        
        @property
        def link_sub_type(self) -> str:
            return "quote"
        
        def extract(self, msg, html_quote_lookup):
            return {"link_sub_type": "quote", ...}

依赖：
- abc: 抽象基类
- typing: 类型提示

作者：[Author]
项目：wechatDHA - 微信聊天记录多模态处理流水线
更新于：2026-02-02

Requirements: 1.1 - 子类型统一处理
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List


class SubTypeHandler(ABC):
    """
    子类型处理器抽象基类
    
    所有 linkfile 子类型处理器都需要继承此类并实现以下抽象方法/属性：
    - sub_types: 返回此处理器支持的 sub_type 列表
    - link_sub_type: 返回统一的 link_sub_type 值
    - extract(): 从消息中提取特定字段
    
    Example:
        >>> class QuoteHandler(SubTypeHandler):
        ...     @property
        ...     def sub_types(self) -> List[int]:
        ...         return [57]
        ...     
        ...     @property
        ...     def link_sub_type(self) -> str:
        ...         return "quote"
        ...     
        ...     def extract(self, msg, html_quote_lookup):
        ...         return {"link_sub_type": "quote", ...}
    """
    
    @property
    @abstractmethod
    def sub_types(self) -> List[int]:
        """
        返回此处理器支持的 sub_type 列表
        
        一个处理器可以支持多个 sub_type，例如 MiniprogramHandler 
        同时支持 sub_type=33 和 sub_type=36。
        
        Returns:
            List[int]: 支持的 sub_type 值列表
            
        Example:
            >>> handler = QuoteHandler()
            >>> handler.sub_types
            [57]
        """
        pass
    
    @property
    @abstractmethod
    def link_sub_type(self) -> str:
        """
        返回统一的 link_sub_type 值
        
        此值用于标识消息的子类型分类，会写入输出记录的 link_sub_type 字段。
        可选值：quote, link, file, miniprogram, video_channel, chat_history, unknown
        
        Returns:
            str: 统一的子类型标识符
            
        Example:
            >>> handler = LinkHandler(link_type_rules=[])
            >>> handler.link_sub_type
            'link'
        """
        pass
    
    @abstractmethod
    def extract(self, msg: Dict[str, Any], html_quote_lookup: Dict[str, Any]) -> Dict[str, Any]:
        """
        从消息中提取特定字段
        
        每个子类型处理器需要实现此方法，从原始消息中提取该子类型特有的字段。
        返回的字典应包含 link_sub_type 字段以及该子类型的特定字段。
        
        Args:
            msg: 原始消息记录，包含以下常用字段：
                - msg_uid: 消息唯一标识
                - MsgSvrID: 服务器消息 ID
                - type: 消息类型（应为 49）
                - sub_type: 消息子类型
                - link_url: 链接 URL（如有）
                - link_title: 链接标题（如有）
                - media_path: 媒体文件路径（如有）
                - text_raw: 原始文本内容
                
            html_quote_lookup: HTML 解析的引用信息查找表
                - 键为 MsgSvrID，值为解析出的引用信息
                - 主要用于 QuoteHandler 获取引用消息的详细信息
                
        Returns:
            Dict[str, Any]: 提取的字段字典，必须包含：
                - link_sub_type: 子类型标识符
                - 其他子类型特定字段
                
        Example:
            >>> handler = QuoteHandler()
            >>> msg = {'msg_uid': 'P1:123', 'sub_type': 57, ...}
            >>> html_quote_lookup = {'123': {'quote_svrid': '456', ...}}
            >>> result = handler.extract(msg, html_quote_lookup)
            >>> result['link_sub_type']
            'quote'
        """
        pass
