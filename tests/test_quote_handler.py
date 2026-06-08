"""
test_quote_handler.py
QuoteHandler 引用消息处理器的单元测试

测试内容：
1. 基本属性测试（sub_types, link_sub_type）
2. 从 html_quote_lookup 提取引用信息
3. 从消息本身提取引用信息（已预处理）
4. speaker 前缀匿名化
5. 边界情况处理

运行方式：
    python tests/test_quote_handler.py
    pytest tests/test_quote_handler.py -v

Requirements: 2.1, 2.2, 2.3
"""

import unittest
from unittest.mock import patch

from scripts.linkfile.handlers.quote_handler import QuoteHandler


class TestQuoteHandlerProperties(unittest.TestCase):
    """测试 QuoteHandler 基本属性"""
    
    def setUp(self):
        self.handler = QuoteHandler()
    
    def test_sub_types(self):
        """测试 sub_types 返回 [57]"""
        self.assertEqual(self.handler.sub_types, [57])
    
    def test_link_sub_type(self):
        """测试 link_sub_type 返回 'quote'"""
        self.assertEqual(self.handler.link_sub_type, "quote")


class TestQuoteHandlerExtractFromLookup(unittest.TestCase):
    """测试从 html_quote_lookup 提取引用信息"""
    
    def setUp(self):
        self.handler = QuoteHandler()
    
    def test_extract_from_lookup_basic(self):
        """测试从 lookup 提取基本引用信息"""
        msg = {
            "msg_uid": "P1:123456",
            "MsgSvrID": "123456",
            "sub_type": 57,
        }
        html_quote_lookup = {
            "123456": {
                "quote_svrid": "789012",
                "quote_type": 1,
                "quote_text": "ME: 原始消息内容",
            }
        }
        
        result = self.handler.extract(msg, html_quote_lookup)
        
        self.assertEqual(result["link_sub_type"], "quote")
        self.assertEqual(result["quote_svrid"], "789012")
        self.assertEqual(result["quote_type"], 1)
        self.assertEqual(result["quote_text"], "ME: 原始消息内容")
    
    def test_extract_from_lookup_with_msg_uid_format(self):
        """测试使用 msg_uid 格式 (P1:MsgSvrID) 查找"""
        msg = {
            "msg_uid": "P1:999888",
            "sub_type": 57,
        }
        html_quote_lookup = {
            "999888": {
                "quote_svrid": "111222",
                "quote_type": 3,
                "quote_text": "OTHER: 图片消息",
            }
        }
        
        result = self.handler.extract(msg, html_quote_lookup)
        
        self.assertEqual(result["quote_svrid"], "111222")
        self.assertEqual(result["quote_type"], 3)
        self.assertEqual(result["quote_text"], "OTHER: 图片消息")
    
    def test_extract_not_in_lookup(self):
        """测试 lookup 中不存在时返回 None 值"""
        msg = {
            "msg_uid": "P1:123456",
            "sub_type": 57,
        }
        html_quote_lookup = {}  # 空 lookup
        
        result = self.handler.extract(msg, html_quote_lookup)
        
        self.assertEqual(result["link_sub_type"], "quote")
        self.assertIsNone(result["quote_svrid"])
        self.assertIsNone(result["quote_type"])
        self.assertIsNone(result["quote_text"])


class TestQuoteHandlerExtractFromMessage(unittest.TestCase):
    """测试从消息本身提取引用信息（已预处理）"""
    
    def setUp(self):
        self.handler = QuoteHandler()
    
    def test_extract_from_message_fields(self):
        """测试从消息字段提取（已通过 extract_quote_info.py 预处理）"""
        msg = {
            "msg_uid": "P1:123456",
            "sub_type": 57,
            "quote_svrid": "789012",
            "quote_type": 1,
            "quote_text": "ME: 已匿名化的文本",
        }
        html_quote_lookup = {}  # 空 lookup，应该从消息本身获取
        
        result = self.handler.extract(msg, html_quote_lookup)
        
        self.assertEqual(result["quote_svrid"], "789012")
        self.assertEqual(result["quote_type"], 1)
        self.assertEqual(result["quote_text"], "ME: 已匿名化的文本")
    
    def test_lookup_priority_over_message(self):
        """测试 lookup 优先级高于消息字段"""
        msg = {
            "msg_uid": "P1:123456",
            "sub_type": 57,
            "quote_svrid": "old_id",
            "quote_type": 99,
            "quote_text": "旧文本",
        }
        html_quote_lookup = {
            "123456": {
                "quote_svrid": "new_id",
                "quote_type": 1,
                "quote_text": "ME: 新文本",
            }
        }
        
        result = self.handler.extract(msg, html_quote_lookup)
        
        # 应该使用 lookup 中的值
        self.assertEqual(result["quote_svrid"], "new_id")
        self.assertEqual(result["quote_type"], 1)
        self.assertEqual(result["quote_text"], "ME: 新文本")


class TestQuoteHandlerAnonymization(unittest.TestCase):
    """测试 speaker 前缀匿名化"""
    
    def setUp(self):
        self.handler = QuoteHandler()
    
    def test_already_anonymized_me(self):
        """测试已匿名化的 ME 前缀不再处理"""
        msg = {"msg_uid": "P1:123", "sub_type": 57}
        html_quote_lookup = {
            "123": {
                "quote_svrid": "456",
                "quote_type": 1,
                "quote_text": "ME: 已匿名化",
            }
        }
        
        result = self.handler.extract(msg, html_quote_lookup)
        self.assertEqual(result["quote_text"], "ME: 已匿名化")
    
    def test_already_anonymized_other(self):
        """测试已匿名化的 OTHER 前缀不再处理"""
        msg = {"msg_uid": "P1:123", "sub_type": 57}
        html_quote_lookup = {
            "123": {
                "quote_svrid": "456",
                "quote_type": 1,
                "quote_text": "OTHER: 已匿名化",
            }
        }
        
        result = self.handler.extract(msg, html_quote_lookup)
        self.assertEqual(result["quote_text"], "OTHER: 已匿名化")
    
    @patch('scripts.linkfile.handlers.quote_handler.anonymize_speaker_prefix')
    def test_unanonymized_text_calls_anonymizer(self, mock_anonymize):
        """测试未匿名化的文本会调用 anonymize_speaker_prefix"""
        mock_anonymize.return_value = "OTHER: 匿名化后的文本"
        
        msg = {"msg_uid": "P1:123", "sub_type": 57}
        html_quote_lookup = {
            "123": {
                "quote_svrid": "456",
                "quote_type": 1,
                "quote_text": "李维彦：原始文本",  # 未匿名化
            }
        }
        
        result = self.handler.extract(msg, html_quote_lookup)
        
        mock_anonymize.assert_called_once_with("李维彦：原始文本")
        self.assertEqual(result["quote_text"], "OTHER: 匿名化后的文本")
    
    def test_empty_quote_text(self):
        """测试空 quote_text 不会出错"""
        msg = {"msg_uid": "P1:123", "sub_type": 57}
        html_quote_lookup = {
            "123": {
                "quote_svrid": "456",
                "quote_type": 1,
                "quote_text": "",
            }
        }
        
        result = self.handler.extract(msg, html_quote_lookup)
        self.assertEqual(result["quote_text"], "")
    
    def test_none_quote_text(self):
        """测试 None quote_text 不会出错"""
        msg = {"msg_uid": "P1:123", "sub_type": 57}
        html_quote_lookup = {
            "123": {
                "quote_svrid": "456",
                "quote_type": 1,
                "quote_text": None,
            }
        }
        
        result = self.handler.extract(msg, html_quote_lookup)
        self.assertIsNone(result["quote_text"])


class TestQuoteHandlerEdgeCases(unittest.TestCase):
    """测试边界情况"""
    
    def setUp(self):
        self.handler = QuoteHandler()
    
    def test_msg_uid_without_colon(self):
        """测试 msg_uid 不含冒号时使用 MsgSvrID"""
        msg = {
            "msg_uid": "123456",  # 无冒号
            "MsgSvrID": "123456",
            "sub_type": 57,
        }
        html_quote_lookup = {
            "123456": {
                "quote_svrid": "789",
                "quote_type": 1,
                "quote_text": "ME: 测试",
            }
        }
        
        result = self.handler.extract(msg, html_quote_lookup)
        self.assertEqual(result["quote_svrid"], "789")
    
    def test_missing_msg_uid_and_msg_svr_id(self):
        """测试缺少 msg_uid 和 MsgSvrID"""
        msg = {"sub_type": 57}
        html_quote_lookup = {
            "123": {"quote_svrid": "456", "quote_type": 1, "quote_text": "ME: 测试"}
        }
        
        result = self.handler.extract(msg, html_quote_lookup)
        
        # 无法查找，返回 None 值
        self.assertEqual(result["link_sub_type"], "quote")
        self.assertIsNone(result["quote_svrid"])
    
    def test_partial_quote_info_in_lookup(self):
        """测试 lookup 中只有部分字段"""
        msg = {"msg_uid": "P1:123", "sub_type": 57}
        html_quote_lookup = {
            "123": {
                "quote_svrid": "456",
                # 缺少 quote_type 和 quote_text
            }
        }
        
        result = self.handler.extract(msg, html_quote_lookup)
        
        self.assertEqual(result["quote_svrid"], "456")
        self.assertIsNone(result["quote_type"])
        self.assertEqual(result["quote_text"], "")  # 空字符串经过 _anonymize_quote_text
    
    def test_quote_type_zero(self):
        """测试 quote_type 为 0 的情况"""
        msg = {"msg_uid": "P1:123", "sub_type": 57}
        html_quote_lookup = {
            "123": {
                "quote_svrid": "456",
                "quote_type": 0,
                "quote_text": "ME: 系统消息",
            }
        }
        
        result = self.handler.extract(msg, html_quote_lookup)
        self.assertEqual(result["quote_type"], 0)


class TestGetMsgSvrId(unittest.TestCase):
    """测试 _get_msg_svr_id 辅助方法"""
    
    def setUp(self):
        self.handler = QuoteHandler()
    
    def test_extract_from_msg_uid_with_colon(self):
        """测试从 P1:MsgSvrID 格式提取"""
        msg = {"msg_uid": "P1:123456789"}
        result = self.handler._get_msg_svr_id(msg)
        self.assertEqual(result, "123456789")
    
    def test_extract_from_msg_svr_id_field(self):
        """测试从 MsgSvrID 字段提取"""
        msg = {"msg_uid": "no_colon", "MsgSvrID": "987654321"}
        result = self.handler._get_msg_svr_id(msg)
        self.assertEqual(result, "987654321")
    
    def test_empty_msg_uid(self):
        """测试空 msg_uid"""
        msg = {"msg_uid": "", "MsgSvrID": "123"}
        result = self.handler._get_msg_svr_id(msg)
        self.assertEqual(result, "123")
    
    def test_no_msg_uid_or_msg_svr_id(self):
        """测试无 msg_uid 和 MsgSvrID"""
        msg = {}
        result = self.handler._get_msg_svr_id(msg)
        self.assertEqual(result, "")


class TestAnonymizeQuoteText(unittest.TestCase):
    """测试 _anonymize_quote_text 辅助方法"""
    
    def setUp(self):
        self.handler = QuoteHandler()
    
    def test_empty_text(self):
        """测试空文本"""
        self.assertEqual(self.handler._anonymize_quote_text(""), "")
    
    def test_none_text(self):
        """测试 None"""
        self.assertIsNone(self.handler._anonymize_quote_text(None))
    
    def test_already_me_prefix(self):
        """测试已有 ME: 前缀"""
        text = "ME: 已匿名化的内容"
        self.assertEqual(self.handler._anonymize_quote_text(text), text)
    
    def test_already_other_prefix(self):
        """测试已有 OTHER: 前缀"""
        text = "OTHER: 已匿名化的内容"
        self.assertEqual(self.handler._anonymize_quote_text(text), text)
    
    @patch('scripts.linkfile.handlers.quote_handler.anonymize_speaker_prefix')
    def test_calls_anonymizer_for_unanonymized(self, mock_anonymize):
        """测试对未匿名化文本调用 anonymizer"""
        mock_anonymize.return_value = "OTHER: 结果"
        
        result = self.handler._anonymize_quote_text("张三：原始内容")
        
        mock_anonymize.assert_called_once_with("张三：原始内容")
        self.assertEqual(result, "OTHER: 结果")


# =============================================================================
# 运行测试
# =============================================================================

if __name__ == "__main__":
    unittest.main(verbosity=2)
