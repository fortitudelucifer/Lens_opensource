"""
LinkHandler - 链接分享处理器

处理 sub_type=5 的链接分享消息，提取链接 URL、标题和类型分类。

链接分享包含以下信息：
- link_url: 链接 URL
- link_title: 链接标题
- link_type: 链接类型分类（根据 URL 匹配 linkfile.yaml 中的规则）

Requirements: 3.1, 3.2
"""

from typing import Dict, Any, List

from scripts.linkfile.handlers.base import SubTypeHandler


class LinkHandler(SubTypeHandler):
    """
    处理 sub_type=5 的链接分享
    
    链接分享是微信中分享的网页链接，包含 URL 和标题。处理器会根据 URL 
    匹配 linkfile.yaml 中定义的 link_type_rules 规则，对链接进行分类。
    
    支持的链接类型包括：
    - wechat_article: 微信公众号文章
    - bilibili_video: B站视频
    - meituan_poi: 美团餐厅
    - dianping_poi: 大众点评
    - netease_music: 网易云音乐
    - qq_music: QQ音乐
    - douyin_video: 抖音视频
    - zhihu_article: 知乎
    - weibo_post: 微博
    - map_location: 高德地图位置
    - web_link: 普通网页链接（默认）
    
    Args:
        link_type_rules: 链接类型规则列表，格式为：
            [
                {"pattern": "mp.weixin.qq.com", "type": "wechat_article"},
                {"pattern": "bilibili.com", "type": "bilibili_video"},
                {"pattern": "*", "type": "web_link"}  # 默认类型
            ]
    
    Example:
        >>> rules = [
        ...     {"pattern": "mp.weixin.qq.com", "type": "wechat_article"},
        ...     {"pattern": "*", "type": "web_link"}
        ... ]
        >>> handler = LinkHandler(link_type_rules=rules)
        >>> msg = {
        ...     'msg_uid': 'P1:123',
        ...     'sub_type': 5,
        ...     'link_url': 'https://mp.weixin.qq.com/s/abc123',
        ...     'link_title': '一篇公众号文章'
        ... }
        >>> result = handler.extract(msg, {})
        >>> result['link_sub_type']
        'link'
        >>> result['link_type']
        'wechat_article'
    """
    
    def __init__(self, link_type_rules: List[Dict[str, str]]):
        """
        初始化 LinkHandler
        
        Args:
            link_type_rules: 链接类型规则列表，每个规则包含：
                - pattern: URL 匹配模式（字符串包含匹配，"*" 表示默认匹配）
                - type: 链接类型标识符
        """
        self.link_type_rules = link_type_rules or []
    
    @property
    def sub_types(self) -> List[int]:
        """返回此处理器支持的 sub_type 列表"""
        return [5]
    
    @property
    def link_sub_type(self) -> str:
        """返回统一的 link_sub_type 值"""
        return "link"
    
    def extract(self, msg: Dict[str, Any], html_quote_lookup: Dict[str, Any]) -> Dict[str, Any]:
        """
        提取链接分享字段
        
        从消息中提取 link_url 和 link_title 字段，并根据 URL 匹配规则
        确定 link_type。
        
        Args:
            msg: 原始消息记录，包含：
                - msg_uid: 消息唯一标识
                - sub_type: 应为 5
                - link_url: 链接 URL
                - link_title: 链接标题
                
            html_quote_lookup: HTML 解析的引用信息查找表（此处理器不使用）
                
        Returns:
            Dict[str, Any]: 提取的字段字典
                {
                    "link_sub_type": "link",
                    "link_url": str,         # 链接 URL
                    "link_title": str,       # 链接标题
                    "link_type": str         # 链接类型分类
                }
        """
        link_url = msg.get("link_url", "") or ""
        link_title = msg.get("link_title", "") or ""
        
        return {
            "link_sub_type": self.link_sub_type,
            "link_url": link_url,
            "link_title": link_title,
            "link_type": self._classify_link_type(link_url),
        }
    
    def _classify_link_type(self, url: str) -> str:
        """
        根据 URL 匹配链接类型规则
        
        按顺序检查 URL 是否包含规则中的 pattern。如果 pattern 是 "*"，
        则作为默认匹配（通常放在规则列表最后）。
        
        匹配逻辑：
        1. 遍历 link_type_rules 列表
        2. 对于每个规则，检查 URL 是否包含 pattern
        3. 如果 pattern 是 "*"，则无条件匹配
        4. 返回第一个匹配规则的 type
        5. 如果没有任何匹配，返回 "web_link" 作为默认值
        
        Args:
            url: 链接 URL
            
        Returns:
            str: 链接类型标识符
            
        Example:
            >>> handler = LinkHandler([
            ...     {"pattern": "mp.weixin.qq.com", "type": "wechat_article"},
            ...     {"pattern": "*", "type": "web_link"}
            ... ])
            >>> handler._classify_link_type("https://mp.weixin.qq.com/s/abc")
            'wechat_article'
            >>> handler._classify_link_type("https://example.com")
            'web_link'
        """
        if not url:
            return "web_link"
        
        for rule in self.link_type_rules:
            pattern = rule.get("pattern", "")
            link_type = rule.get("type", "web_link")
            
            # "*" 作为默认匹配（通配符）
            if pattern == "*":
                return link_type
            
            # 检查 URL 是否包含 pattern
            if pattern and pattern in url:
                return link_type
        
        # 如果没有任何规则匹配，返回默认类型
        return "web_link"
