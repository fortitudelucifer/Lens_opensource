"""
内容类型处理器模块 (Content Handlers Module)

功能：
- 处理视频号和聊天记录分享两种内容类型
- VideoChannelHandler: 处理 sub_type=51 的视频号消息
- ChatHistoryHandler: 处理 sub_type=19 的聊天记录分享消息

视频号 (sub_type=51)：
- 微信视频号内容分享
- 提取字段：content_title（视频号内容标题）

聊天记录分享 (sub_type=19)：
- 微信聊天记录合并转发
- 提取字段：content_title（聊天记录标题）

使用示例：
    from scripts.linkfile.handlers.content_handler import VideoChannelHandler
    
    handler = VideoChannelHandler()
    msg = {'msg_uid': 'P1:123', 'sub_type': 51, 'link_title': '视频标题'}
    result = handler.extract(msg, {})
    print(result['content_title'])  # 视频标题

依赖：
- scripts.linkfile.handlers.base: SubTypeHandler 抽象基类

作者：[Author]
项目：wechatDHA - 微信聊天记录多模态处理流水线
更新于：2026-02-02
"""

from typing import Any, Dict, List

from scripts.linkfile.handlers.base import SubTypeHandler


class VideoChannelHandler(SubTypeHandler):
    """处理 sub_type=51 的视频号消息"""
    
    @property
    def sub_types(self) -> List[int]:
        return [51]
    
    @property
    def link_sub_type(self) -> str:
        return "video_channel"
    
    def extract(self, msg: Dict[str, Any], html_quote_lookup: Dict[str, Any]) -> Dict[str, Any]:
        """
        提取视频号字段
        
        Returns:
            {
                "link_sub_type": "video_channel",
                "content_title": str     # 视频号内容标题
            }
        """
        return {
            'link_sub_type': self.link_sub_type,
            'content_title': msg.get('link_title', ''),
        }


class ChatHistoryHandler(SubTypeHandler):
    """处理 sub_type=19 的聊天记录分享消息"""
    
    @property
    def sub_types(self) -> List[int]:
        return [19]
    
    @property
    def link_sub_type(self) -> str:
        return "chat_history"
    
    def extract(self, msg: Dict[str, Any], html_quote_lookup: Dict[str, Any]) -> Dict[str, Any]:
        """
        提取聊天记录分享字段
        
        Returns:
            {
                "link_sub_type": "chat_history",
                "content_title": str     # 聊天记录标题
            }
        """
        return {
            'link_sub_type': self.link_sub_type,
            'content_title': msg.get('link_title', ''),
        }
