"""
Linkfile Handlers Module
子类型处理器目录，包含各种 sub_type 的专用处理器。

Handlers:
    SubTypeHandler - 抽象基类
    QuoteHandler - 引用消息处理器 (sub_type=57)
    LinkHandler - 链接分享处理器 (sub_type=5)
    FileHandler - 文件传输处理器 (sub_type=6)
    MiniprogramHandler - 小程序处理器 (sub_type=33, 36)
    VideoChannelHandler - 视频号处理器 (sub_type=51)
    ChatHistoryHandler - 聊天记录分享处理器 (sub_type=19)
"""

from scripts.linkfile.handlers.base import SubTypeHandler
from scripts.linkfile.handlers.quote_handler import QuoteHandler
from scripts.linkfile.handlers.link_handler import LinkHandler
from scripts.linkfile.handlers.file_handler import FileHandler
from scripts.linkfile.handlers.miniprogram_handler import MiniprogramHandler
from scripts.linkfile.handlers.content_handler import VideoChannelHandler, ChatHistoryHandler

__all__ = [
    'SubTypeHandler',
    'QuoteHandler',
    'LinkHandler',
    'FileHandler',
    'MiniprogramHandler',
    'VideoChannelHandler',
    'ChatHistoryHandler',
]
