"""
小程序处理器模块 (Miniprogram Handler Module)

功能：
- 处理 sub_type=33, 36 的小程序消息
- 提取小程序 AppID 和名称
- 支持从多个来源提取 AppID（XML、URL、直接字段）

小程序类型：
- sub_type=33: 小程序分享
- sub_type=36: 小程序卡片

提取字段：
- link_url: 小程序链接
- link_title: 小程序标题
- miniprogram_appid: 小程序 AppID（wx... 或 gh_...）
- miniprogram_name: 小程序名称（从映射表获取）

AppID 提取策略：
1. 直接字段：msg['miniprogram_appid']
2. XML 内容：从 text_raw 中的 XML 提取（<appid>、<username>）
3. URL 参数：从 link_url 中提取

AppID 格式：
- 正式 AppID：wx + 16位十六进制（例如：wx1234567890abcdef）
- 原始 ID：gh_ + 12位十六进制（例如：gh_1234567890ab）

使用示例：
    from scripts.linkfile.handlers.miniprogram_handler import MiniprogramHandler
    
    # 小程序名称映射表
    miniprogram_apps = {
        'wx1234567890abcdef': '微信读书',
        'gh_1234567890ab': '腾讯文档'
    }
    
    handler = MiniprogramHandler(miniprogram_apps)
    msg = {
        'msg_uid': 'P1:123',
        'sub_type': 33,
        'link_title': '分享的小程序',
        'text_raw': '<appid>wx1234567890abcdef</appid>'
    }
    result = handler.extract(msg, {})
    print(result['miniprogram_name'])  # 微信读书

依赖：
- scripts.linkfile.handlers.base: SubTypeHandler 抽象基类
- re: 正则表达式（AppID 提取）
- urllib.parse: URL 解析

作者：[Author]
项目：wechatDHA - 微信聊天记录多模态处理流水线
更新于：2026-02-02
"""

from typing import Any, Dict, List

from scripts.linkfile.handlers.base import SubTypeHandler


class MiniprogramHandler(SubTypeHandler):
    """处理 sub_type=33, 36 的小程序消息"""
    
    def __init__(self, miniprogram_apps: Dict[str, str] = None):
        """
        初始化小程序处理器
        
        Args:
            miniprogram_apps: AppID 到小程序名称的映射表
        """
        self.miniprogram_apps = miniprogram_apps or {}
    
    @property
    def sub_types(self) -> List[int]:
        return [33, 36]
    
    @property
    def link_sub_type(self) -> str:
        return "miniprogram"
    
    def extract(self, msg: Dict[str, Any], html_quote_lookup: Dict[str, Any]) -> Dict[str, Any]:
        """
        提取小程序字段
        
        Returns:
            {
                "link_sub_type": "miniprogram",
                "link_url": str,             # 小程序链接
                "link_title": str,           # 小程序标题
                "miniprogram_appid": str,    # 小程序 AppID
                "miniprogram_name": str      # 小程序名称（从映射表获取）
            }
        """
        link_url = msg.get('link_url', '')
        link_title = msg.get('link_title', '')
        
        # 尝试从 text_raw 或其他字段提取 AppID
        appid = self._extract_appid(msg)
        
        # 从映射表获取小程序名称
        miniprogram_name = self.miniprogram_apps.get(appid, '') if appid else ''
        
        return {
            'link_sub_type': self.link_sub_type,
            'link_url': link_url,
            'link_title': link_title,
            'miniprogram_appid': appid,
            'miniprogram_name': miniprogram_name,
        }
    
    def _extract_appid(self, msg: Dict[str, Any]) -> str:
        """
        从消息中提取小程序 AppID
        
        尝试从以下位置提取：
        1. msg['miniprogram_appid'] 字段（如果存在）
        2. msg['text_raw'] 中的 XML 内容
        3. msg['link_url'] 中的参数
        
        Returns:
            AppID 字符串，未找到时返回空字符串
        """
        # 1. 直接字段
        if msg.get('miniprogram_appid'):
            return msg['miniprogram_appid']
        
        # 2. 从 text_raw 中提取（通常是 XML 格式）
        text_raw = msg.get('text_raw', '')
        if text_raw:
            appid = self._extract_appid_from_xml(text_raw)
            if appid:
                return appid
        
        # 3. 从 link_url 中提取
        link_url = msg.get('link_url', '')
        if link_url:
            appid = self._extract_appid_from_url(link_url)
            if appid:
                return appid
        
        return ''
    
    def _extract_appid_from_xml(self, text: str) -> str:
        """从 XML 文本中提取 AppID"""
        import re
        
        # 匹配 <weappinfo><username>gh_xxx</username> 或 <appid>wx...</appid>
        patterns = [
            r'<appid><!\[CDATA\[(wx[a-f0-9]+)\]\]></appid>',
            r'<appid>(wx[a-f0-9]+)</appid>',
            r'<username><!\[CDATA\[(gh_[a-f0-9]+)\]\]></username>',
            r'<username>(gh_[a-f0-9]+)</username>',
            r'appid="(wx[a-f0-9]+)"',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(1)
        
        return ''
    
    def _extract_appid_from_url(self, url: str) -> str:
        """从 URL 中提取 AppID"""
        import re
        from urllib.parse import parse_qs, urlparse
        
        # 尝试从 URL 参数中提取
        try:
            parsed = urlparse(url)
            params = parse_qs(parsed.query)
            if 'appid' in params:
                return params['appid'][0]
        except Exception:
            pass
        
        # 尝试从 URL 路径中匹配
        match = re.search(r'(wx[a-f0-9]{16})', url)
        if match:
            return match.group(1)
        
        return ''
