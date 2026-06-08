"""
test_link_handler.py
LinkHandler 链接分享处理器的单元测试

测试内容：
1. 基本属性测试（sub_types, link_sub_type）
2. 链接字段提取（link_url, link_title）
3. 链接类型分类（_classify_link_type）
4. 边界情况处理

运行方式：
    python tests/test_link_handler.py
    pytest tests/test_link_handler.py -v

Requirements: 3.1, 3.2
"""

import unittest

from scripts.linkfile.handlers.link_handler import LinkHandler


# 测试用的链接类型规则（模拟 linkfile.yaml 配置）
TEST_LINK_TYPE_RULES = [
    {"pattern": "surl.amap.com", "type": "map_location"},
    {"pattern": "mp.weixin.qq.com", "type": "wechat_article"},
    {"pattern": "meishi.meituan.com", "type": "meituan_poi"},
    {"pattern": "dianping.com", "type": "dianping_poi"},
    {"pattern": "music.163.com", "type": "netease_music"},
    {"pattern": "y.qq.com", "type": "qq_music"},
    {"pattern": "bilibili.com", "type": "bilibili_video"},
    {"pattern": "douyin.com", "type": "douyin_video"},
    {"pattern": "zhihu.com", "type": "zhihu_article"},
    {"pattern": "weibo.com", "type": "weibo_post"},
    {"pattern": "*", "type": "web_link"},  # 默认类型
]


class TestLinkHandlerProperties(unittest.TestCase):
    """测试 LinkHandler 基本属性"""
    
    def setUp(self):
        self.handler = LinkHandler(link_type_rules=TEST_LINK_TYPE_RULES)
    
    def test_sub_types(self):
        """测试 sub_types 返回 [5]"""
        self.assertEqual(self.handler.sub_types, [5])
    
    def test_link_sub_type(self):
        """测试 link_sub_type 返回 'link'"""
        self.assertEqual(self.handler.link_sub_type, "link")
    
    def test_init_with_rules(self):
        """测试初始化时传入规则"""
        rules = [{"pattern": "example.com", "type": "example"}]
        handler = LinkHandler(link_type_rules=rules)
        self.assertEqual(handler.link_type_rules, rules)
    
    def test_init_with_empty_rules(self):
        """测试初始化时传入空规则列表"""
        handler = LinkHandler(link_type_rules=[])
        self.assertEqual(handler.link_type_rules, [])
    
    def test_init_with_none_rules(self):
        """测试初始化时传入 None"""
        handler = LinkHandler(link_type_rules=None)
        self.assertEqual(handler.link_type_rules, [])


class TestLinkHandlerExtract(unittest.TestCase):
    """测试 LinkHandler.extract() 方法"""
    
    def setUp(self):
        self.handler = LinkHandler(link_type_rules=TEST_LINK_TYPE_RULES)
    
    def test_extract_basic(self):
        """测试基本链接提取"""
        msg = {
            "msg_uid": "P1:123456",
            "sub_type": 5,
            "link_url": "https://mp.weixin.qq.com/s/abc123",
            "link_title": "一篇公众号文章",
        }
        
        result = self.handler.extract(msg, {})
        
        self.assertEqual(result["link_sub_type"], "link")
        self.assertEqual(result["link_url"], "https://mp.weixin.qq.com/s/abc123")
        self.assertEqual(result["link_title"], "一篇公众号文章")
        self.assertEqual(result["link_type"], "wechat_article")
    
    def test_extract_bilibili_link(self):
        """测试 B 站链接提取"""
        msg = {
            "msg_uid": "P1:123456",
            "sub_type": 5,
            "link_url": "https://www.bilibili.com/video/BV1234567890",
            "link_title": "【视频】有趣的内容",
        }
        
        result = self.handler.extract(msg, {})
        
        self.assertEqual(result["link_type"], "bilibili_video")
        self.assertEqual(result["link_title"], "【视频】有趣的内容")
    
    def test_extract_unknown_link(self):
        """测试未知链接类型（应返回 web_link）"""
        msg = {
            "msg_uid": "P1:123456",
            "sub_type": 5,
            "link_url": "https://example.com/page",
            "link_title": "示例页面",
        }
        
        result = self.handler.extract(msg, {})
        
        self.assertEqual(result["link_type"], "web_link")
    
    def test_extract_empty_url(self):
        """测试空 URL"""
        msg = {
            "msg_uid": "P1:123456",
            "sub_type": 5,
            "link_url": "",
            "link_title": "无链接标题",
        }
        
        result = self.handler.extract(msg, {})
        
        self.assertEqual(result["link_url"], "")
        self.assertEqual(result["link_type"], "web_link")
    
    def test_extract_none_url(self):
        """测试 None URL"""
        msg = {
            "msg_uid": "P1:123456",
            "sub_type": 5,
            "link_url": None,
            "link_title": "无链接标题",
        }
        
        result = self.handler.extract(msg, {})
        
        self.assertEqual(result["link_url"], "")
        self.assertEqual(result["link_type"], "web_link")
    
    def test_extract_missing_url(self):
        """测试缺少 link_url 字段"""
        msg = {
            "msg_uid": "P1:123456",
            "sub_type": 5,
            "link_title": "只有标题",
        }
        
        result = self.handler.extract(msg, {})
        
        self.assertEqual(result["link_url"], "")
        self.assertEqual(result["link_type"], "web_link")
    
    def test_extract_empty_title(self):
        """测试空标题"""
        msg = {
            "msg_uid": "P1:123456",
            "sub_type": 5,
            "link_url": "https://example.com",
            "link_title": "",
        }
        
        result = self.handler.extract(msg, {})
        
        self.assertEqual(result["link_title"], "")
    
    def test_extract_none_title(self):
        """测试 None 标题"""
        msg = {
            "msg_uid": "P1:123456",
            "sub_type": 5,
            "link_url": "https://example.com",
            "link_title": None,
        }
        
        result = self.handler.extract(msg, {})
        
        self.assertEqual(result["link_title"], "")
    
    def test_extract_missing_title(self):
        """测试缺少 link_title 字段"""
        msg = {
            "msg_uid": "P1:123456",
            "sub_type": 5,
            "link_url": "https://example.com",
        }
        
        result = self.handler.extract(msg, {})
        
        self.assertEqual(result["link_title"], "")
    
    def test_extract_ignores_html_quote_lookup(self):
        """测试 extract 不使用 html_quote_lookup"""
        msg = {
            "msg_uid": "P1:123456",
            "sub_type": 5,
            "link_url": "https://example.com",
            "link_title": "标题",
        }
        html_quote_lookup = {
            "123456": {"some": "data"}
        }
        
        result = self.handler.extract(msg, html_quote_lookup)
        
        # 结果应该与空 lookup 相同
        self.assertEqual(result["link_sub_type"], "link")
        self.assertEqual(result["link_url"], "https://example.com")


class TestLinkHandlerClassifyLinkType(unittest.TestCase):
    """测试 LinkHandler._classify_link_type() 方法"""
    
    def setUp(self):
        self.handler = LinkHandler(link_type_rules=TEST_LINK_TYPE_RULES)
    
    def test_classify_wechat_article(self):
        """测试微信公众号文章分类"""
        url = "https://mp.weixin.qq.com/s/abc123def456"
        self.assertEqual(self.handler._classify_link_type(url), "wechat_article")
    
    def test_classify_bilibili_video(self):
        """测试 B 站视频分类"""
        url = "https://www.bilibili.com/video/BV1234567890"
        self.assertEqual(self.handler._classify_link_type(url), "bilibili_video")
    
    def test_classify_meituan_poi(self):
        """测试美团餐厅分类"""
        url = "https://meishi.meituan.com/i/poi/123456"
        self.assertEqual(self.handler._classify_link_type(url), "meituan_poi")
    
    def test_classify_dianping_poi(self):
        """测试大众点评分类"""
        url = "https://www.dianping.com/shop/123456"
        self.assertEqual(self.handler._classify_link_type(url), "dianping_poi")
    
    def test_classify_netease_music(self):
        """测试网易云音乐分类"""
        url = "https://music.163.com/song?id=123456"
        self.assertEqual(self.handler._classify_link_type(url), "netease_music")
    
    def test_classify_qq_music(self):
        """测试 QQ 音乐分类"""
        url = "https://y.qq.com/n/ryqq/songDetail/123456"
        self.assertEqual(self.handler._classify_link_type(url), "qq_music")
    
    def test_classify_douyin_video(self):
        """测试抖音视频分类"""
        url = "https://www.douyin.com/video/123456"
        self.assertEqual(self.handler._classify_link_type(url), "douyin_video")
    
    def test_classify_zhihu_article(self):
        """测试知乎分类"""
        url = "https://www.zhihu.com/question/123456"
        self.assertEqual(self.handler._classify_link_type(url), "zhihu_article")
    
    def test_classify_weibo_post(self):
        """测试微博分类"""
        url = "https://weibo.com/123456/abc"
        self.assertEqual(self.handler._classify_link_type(url), "weibo_post")
    
    def test_classify_map_location(self):
        """测试高德地图位置分类"""
        url = "https://surl.amap.com/abc123"
        self.assertEqual(self.handler._classify_link_type(url), "map_location")
    
    def test_classify_unknown_url(self):
        """测试未知 URL 返回默认类型"""
        url = "https://example.com/page"
        self.assertEqual(self.handler._classify_link_type(url), "web_link")
    
    def test_classify_empty_url(self):
        """测试空 URL 返回默认类型"""
        self.assertEqual(self.handler._classify_link_type(""), "web_link")
    
    def test_classify_none_url(self):
        """测试 None URL 返回默认类型（通过 extract 处理后为空字符串）"""
        # 注意：_classify_link_type 直接接收字符串，None 会导致错误
        # 但在 extract 中已经处理为空字符串
        self.assertEqual(self.handler._classify_link_type(""), "web_link")
    
    def test_classify_priority_order(self):
        """测试规则按优先级顺序匹配"""
        # 创建一个包含多个可能匹配的规则
        rules = [
            {"pattern": "example.com/special", "type": "special"},
            {"pattern": "example.com", "type": "general"},
            {"pattern": "*", "type": "default"},
        ]
        handler = LinkHandler(link_type_rules=rules)
        
        # 应该匹配第一个规则
        url = "https://example.com/special/page"
        self.assertEqual(handler._classify_link_type(url), "special")
        
        # 应该匹配第二个规则
        url = "https://example.com/other"
        self.assertEqual(handler._classify_link_type(url), "general")
    
    def test_classify_without_wildcard_rule(self):
        """测试没有通配符规则时返回默认值"""
        rules = [
            {"pattern": "example.com", "type": "example"},
        ]
        handler = LinkHandler(link_type_rules=rules)
        
        # 不匹配任何规则，应返回默认 web_link
        url = "https://other.com/page"
        self.assertEqual(handler._classify_link_type(url), "web_link")
    
    def test_classify_with_empty_rules(self):
        """测试空规则列表时返回默认值"""
        handler = LinkHandler(link_type_rules=[])
        
        url = "https://example.com/page"
        self.assertEqual(handler._classify_link_type(url), "web_link")
    
    def test_classify_rule_with_empty_pattern(self):
        """测试规则中 pattern 为空时跳过"""
        rules = [
            {"pattern": "", "type": "empty"},
            {"pattern": "example.com", "type": "example"},
            {"pattern": "*", "type": "default"},
        ]
        handler = LinkHandler(link_type_rules=rules)
        
        # 空 pattern 应该被跳过
        url = "https://example.com/page"
        self.assertEqual(handler._classify_link_type(url), "example")
    
    def test_classify_rule_missing_type(self):
        """测试规则缺少 type 字段时使用默认值"""
        rules = [
            {"pattern": "example.com"},  # 缺少 type
            {"pattern": "*", "type": "default"},
        ]
        handler = LinkHandler(link_type_rules=rules)
        
        url = "https://example.com/page"
        # 缺少 type 时使用 web_link 作为默认值
        self.assertEqual(handler._classify_link_type(url), "web_link")


class TestLinkHandlerEdgeCases(unittest.TestCase):
    """测试边界情况"""
    
    def setUp(self):
        self.handler = LinkHandler(link_type_rules=TEST_LINK_TYPE_RULES)
    
    def test_url_with_query_params(self):
        """测试带查询参数的 URL"""
        msg = {
            "msg_uid": "P1:123456",
            "sub_type": 5,
            "link_url": "https://mp.weixin.qq.com/s?__biz=abc&mid=123&idx=1",
            "link_title": "带参数的文章",
        }
        
        result = self.handler.extract(msg, {})
        
        self.assertEqual(result["link_type"], "wechat_article")
    
    def test_url_with_fragment(self):
        """测试带锚点的 URL"""
        msg = {
            "msg_uid": "P1:123456",
            "sub_type": 5,
            "link_url": "https://www.zhihu.com/question/123456#answer-789",
            "link_title": "带锚点的问题",
        }
        
        result = self.handler.extract(msg, {})
        
        self.assertEqual(result["link_type"], "zhihu_article")
    
    def test_url_case_sensitivity(self):
        """测试 URL 大小写敏感性"""
        # URL 中的域名部分通常不区分大小写
        msg = {
            "msg_uid": "P1:123456",
            "sub_type": 5,
            "link_url": "https://MP.WEIXIN.QQ.COM/s/abc123",
            "link_title": "大写域名",
        }
        
        result = self.handler.extract(msg, {})
        
        # 当前实现是大小写敏感的，大写不匹配
        # 如果需要不区分大小写，需要修改实现
        self.assertEqual(result["link_type"], "web_link")
    
    def test_url_with_subdomain(self):
        """测试带子域名的 URL"""
        msg = {
            "msg_uid": "P1:123456",
            "sub_type": 5,
            "link_url": "https://m.bilibili.com/video/BV123",
            "link_title": "移动端 B 站",
        }
        
        result = self.handler.extract(msg, {})
        
        # bilibili.com 应该匹配
        self.assertEqual(result["link_type"], "bilibili_video")
    
    def test_special_characters_in_title(self):
        """测试标题中的特殊字符"""
        msg = {
            "msg_uid": "P1:123456",
            "sub_type": 5,
            "link_url": "https://example.com",
            "link_title": "标题包含<script>alert('xss')</script>",
        }
        
        result = self.handler.extract(msg, {})
        
        # 应该原样保留标题
        self.assertEqual(result["link_title"], "标题包含<script>alert('xss')</script>")
    
    def test_unicode_in_url(self):
        """测试 URL 中的 Unicode 字符"""
        msg = {
            "msg_uid": "P1:123456",
            "sub_type": 5,
            "link_url": "https://example.com/路径/页面",
            "link_title": "中文路径",
        }
        
        result = self.handler.extract(msg, {})
        
        self.assertEqual(result["link_url"], "https://example.com/路径/页面")
    
    def test_very_long_url(self):
        """测试超长 URL"""
        long_path = "a" * 1000
        msg = {
            "msg_uid": "P1:123456",
            "sub_type": 5,
            "link_url": f"https://example.com/{long_path}",
            "link_title": "超长链接",
        }
        
        result = self.handler.extract(msg, {})
        
        self.assertEqual(len(result["link_url"]), 1000 + len("https://example.com/"))


# =============================================================================
# 运行测试
# =============================================================================

if __name__ == "__main__":
    unittest.main(verbosity=2)
