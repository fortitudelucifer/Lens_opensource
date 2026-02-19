# -*- coding: utf-8 -*-
"""
图片压缩器

将图片的 caption 和 ocr_text 压缩为简洁摘要
支持敏感内容标签保留

输入：
  - artifacts/before_merge/image/image_caption_v1.jsonl
  - artifacts/before_merge/image/image_ocr_v1.jsonl
输出：artifacts/before_merge/image/image_compressed.jsonl
"""

import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import yaml


@dataclass
class ImageConfig:
    """图片压缩配置"""
    enabled: bool = True
    target_length: int = 80
    preserve_sensitive_labels: bool = True
    detailed_sensitive_description: bool = True


class ImageCompressor:
    """图片压缩器：Caption+OCR 合并 + 规则压缩"""
    
    def __init__(self, config_path: str = "configs/compression.yaml", model=None):
        self.config = self._load_config(config_path)
        self.image_config = self._parse_image_config()
        self.model = model  # 可选的 LLM 模型
        
        # 统计信息
        self.stats = {
            "total": 0,
            "compressed": 0,
            "sensitive_count": 0,
            "text_primary_count": 0,
            "avg_compression_ratio": 0.0,
            "total_original_length": 0,
            "total_compressed_length": 0
        }
    
    def _load_config(self, config_path: str) -> dict:
        """加载配置文件"""
        path = Path(config_path)
        if not path.exists():
            print(f"[WARN] 配置文件不存在: {config_path}")
            return {}
        
        with open(path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    
    def _parse_image_config(self) -> ImageConfig:
        """解析图片压缩配置"""
        cfg = self.config.get('image', {})
        level = self.config.get('default_level', 'balanced')
        target_lengths = cfg.get('target_length', {})
        sensitive_cfg = cfg.get('sensitive_content', {})
        
        return ImageConfig(
            enabled=cfg.get('enabled', True),
            target_length=target_lengths.get(level, 80),
            preserve_sensitive_labels=sensitive_cfg.get('preserve_labels', True),
            detailed_sensitive_description=sensitive_cfg.get('detailed_description', True)
        )
    
    def compress(self, image_data: Dict, ocr_data: Optional[Dict] = None) -> Dict:
        """
        压缩单个图片
        
        Args:
            image_data: 图片 caption 数据
            ocr_data: 图片 OCR 数据（可选）
        
        Returns:
            压缩后的数据
        """
        self.stats["total"] += 1
        
        caption = image_data.get('caption', '')
        content_type = image_data.get('content_type', 'TYPE_C_NORMAL')
        route_class = image_data.get('route_class', 'VISUAL_PRIMARY')
        
        # 获取 OCR 文字
        ocr_text = ''
        if ocr_data:
            ocr_text = ocr_data.get('full_text', '')
        
        # TEXT_PRIMARY 且无 caption 时，基于 OCR 生成 summary
        if route_class == 'TEXT_PRIMARY' and not caption and ocr_text:
            self.stats["text_primary_count"] += 1
            image_summary = self._generate_text_primary_summary(ocr_text)
            scene_focus = 'document'
            emotion_atmosphere = '中性'
            intent = '分享'
            
            # 计算压缩比
            original_length = len(ocr_text)
            compressed_length = len(image_summary)
            compression_ratio = original_length / compressed_length if compressed_length > 0 else 1.0
            
            self.stats["total_original_length"] += original_length
            self.stats["total_compressed_length"] += compressed_length
            self.stats["compressed"] += 1
            
            return {
                "msg_uid": image_data.get('msg_uid'),
                "schema_version": "image_compressed_v1",
                "image_summary": image_summary,
                "content_type": content_type,
                "route_class": route_class,
                "scene_focus": scene_focus,
                "emotion_atmosphere": emotion_atmosphere,
                "intent": intent,
                "compression_ratio": round(compression_ratio, 2),
                "original_length": original_length,
                "compressed_length": compressed_length,
                "is_compressed": True,
                "image_path": image_data.get('image_path'),
                "triage_confidence": image_data.get('triage_confidence'),
                "metadata": image_data.get('metadata')
            }
        
        # 判断图片重点
        scene_focus = self._classify_focus(caption, ocr_text, content_type, route_class)
        
        # 合并并压缩
        image_summary = self._merge_and_compress(
            caption, ocr_text, content_type, route_class, scene_focus
        )
        
        # 提取情绪氛围和意图
        emotion_atmosphere = self._extract_emotion(caption)
        intent = self._extract_intent(caption)
        
        # 处理敏感内容
        if content_type in ['TYPE_A_NSFW', 'TYPE_B_GORE']:
            self.stats["sensitive_count"] += 1
            if self.image_config.preserve_sensitive_labels:
                image_summary = f"[{content_type}] {image_summary}"
        
        if route_class == 'TEXT_PRIMARY':
            self.stats["text_primary_count"] += 1
        
        # 计算压缩比
        original_length = len(caption) + len(ocr_text)
        compressed_length = len(image_summary)
        compression_ratio = original_length / compressed_length if compressed_length > 0 else 1.0
        
        self.stats["total_original_length"] += original_length
        self.stats["total_compressed_length"] += compressed_length
        self.stats["compressed"] += 1
        
        return {
            "msg_uid": image_data.get('msg_uid'),
            "schema_version": "image_compressed_v1",
            "image_summary": image_summary,
            "content_type": content_type,
            "route_class": route_class,
            "scene_focus": scene_focus,
            "emotion_atmosphere": emotion_atmosphere,
            "intent": intent,
            "compression_ratio": round(compression_ratio, 2),
            "original_length": original_length,
            "compressed_length": compressed_length,
            # 保留原始字段
            "image_path": image_data.get('image_path'),
            "triage_confidence": image_data.get('triage_confidence'),
            "metadata": image_data.get('metadata')
        }
    
    def _classify_focus(self, caption: str, ocr_text: str, 
                        content_type: str, route_class: str) -> str:
        """
        判断图片重点
        
        Returns:
            'scene': 风景/场景
            'person': 人物
            'object': 物品
            'food': 美食
            'document': 文档/截图
            'other': 其他
        """
        # 根据 route_class 判断
        if route_class == 'TEXT_PRIMARY':
            return 'document'
        
        # 提取 caption 前 100 字进行分类（避免长文本干扰）
        caption_head = caption[:100] if len(caption) > 100 else caption
        
        # 美食关键词 - 需要更精确的匹配
        food_keywords = ['美食', '食物', '火锅', '烧烤', '炒菜', '点心', '甜点', 
                        '蛋糕', '面条', '米饭', '汤', '饮料', '咖啡', '奶茶']
        if any(kw in caption_head for kw in food_keywords):
            return 'food'
        
        # 人物关键词 - 需要更精确
        person_keywords = ['自拍', '合影', '人物', '肖像', '面部', '表情']
        if any(kw in caption_head for kw in person_keywords):
            return 'person'
        
        # 风景关键词
        scene_keywords = ['风景', '景色', '天空', '大海', '山峰', '森林', '公园', 
                         '建筑', '城市', '街道', '夜景']
        if any(kw in caption_head for kw in scene_keywords):
            return 'scene'
        
        # 物品关键词
        object_keywords = ['物品', '产品', '商品', '包装', '手机', '电脑', '汽车']
        if any(kw in caption_head for kw in object_keywords):
            return 'object'
        
        return 'other'
    
    def _merge_and_compress(self, caption: str, ocr_text: str, 
                            content_type: str, route_class: str,
                            scene_focus: str) -> str:
        """
        合并 caption 和 OCR，并压缩
        
        策略：
        - TEXT_PRIMARY: 优先保留 OCR 文字
        - VISUAL_PRIMARY: 优先保留 caption
        - 敏感内容: 如实描述特征
        """
        target_length = self.image_config.target_length
        
        # 提取 caption 中的关键信息
        summary_parts = []
        
        # 1. 提取场景类型（只有明确分类时才添加前缀）
        focus_map = {
            'food': '美食照片',
            'person': '人物照片',
            'scene': '风景照片',
            'object': '物品照片',
            'document': '文档截图'
        }
        if scene_focus in focus_map:
            summary_parts.append(focus_map[scene_focus])
        
        # 2. 提取关键内容
        key_content = self._extract_key_content(caption, scene_focus)
        if key_content:
            summary_parts.append(key_content)
        
        # 3. 处理 OCR 文字
        if ocr_text and route_class in ['TEXT_PRIMARY', 'HYBRID_TEXT_MAIN']:
            # 文字为主的图片，保留更多 OCR 内容
            ocr_summary = self._summarize_ocr(ocr_text, target_length // 2)
            if ocr_summary:
                summary_parts.append(f"文字内容: {ocr_summary}")
        elif ocr_text and len(ocr_text) > 10:
            # 有少量文字
            ocr_brief = ocr_text[:30].replace('\n', ' ')
            if len(ocr_text) > 30:
                ocr_brief += '...'
            summary_parts.append(f"(含文字: {ocr_brief})")
        
        # 4. 合并（不再强制截断，保留完整信息）
        summary = '，'.join(filter(None, summary_parts))
        
        # 注意：不再强制截断，target_length 仅作为参考
        # 如果需要限制长度，应在上游 VLM 生成时控制
        
        return summary if summary else '图片'
    
    def _extract_key_content(self, caption: str, scene_focus: str) -> str:
        """从 caption 中提取关键内容，保留更多细节"""
        key_elements = []
        
        # 1. 提取 **关键人物、动作或物体** 或 **关键物体** 部分的内容
        # 匹配格式: "2. **关键人物、动作或物体**：图片中展示了..."
        key_section_patterns = [
            r'\*\*关键(?:人物、动作或)?物体\*\*[：:]\s*([\s\S]*?)(?=\n\d+\.\s*\*\*|\n\n\d+\.|\Z)',
            r'\*\*关键物体\*\*[：:]\s*([\s\S]*?)(?=\n\d+\.\s*\*\*|\n\n\d+\.|\Z)',
        ]
        
        for pattern in key_section_patterns:
            key_match = re.search(pattern, caption)
            if key_match:
                key_section = key_match.group(1)
                # 提取列表项（以 - 开头的行）
                items = re.findall(r'-\s*([^\n]+)', key_section)
                if items:
                    for item in items[:4]:  # 最多取4个列表项
                        item = item.strip()
                        # 清理 markdown 和多余文字
                        item = re.sub(r'\*\*[^*]+\*\*[：:]?\s*', '', item)
                        item = item.strip()
                        if len(item) > 5 and len(item) < 80:
                            key_elements.append(item)
                else:
                    # 没有列表项，直接提取描述文字
                    desc = key_section.strip()
                    # 提取第一句有意义的描述
                    sentences = re.split(r'[。\n]', desc)
                    for sent in sentences[:2]:
                        sent = sent.strip()
                        if len(sent) > 10 and len(sent) < 80:
                            key_elements.append(sent)
                break
        
        # 2. 提取 **画面中的关键物体** 部分
        visual_section_pattern = r'\*\*画面中的关键物体\*\*[：:]\s*([\s\S]*?)(?=\n\d+\.\s*\*\*|\n\n\d+\.|\Z)'
        visual_match = re.search(visual_section_pattern, caption)
        if visual_match:
            visual_section = visual_match.group(1)
            items = re.findall(r'-\s*([^\n]+)', visual_section)
            for item in items[:3]:
                item = item.strip()
                if len(item) > 5 and len(item) < 80:
                    key_elements.append(item)
        
        # 3. 提取具体食材/物品名称（作为补充）
        if scene_focus == 'food':
            food_patterns = [
                r'主要食材包括([^。\n]{5,40})',
                r'食材有([^。\n]{5,40})',
            ]
            for pattern in food_patterns:
                match = re.search(pattern, caption)
                if match:
                    food_desc = match.group(1).strip()
                    if food_desc not in key_elements:
                        key_elements.append(f"食材: {food_desc}")
                    break
        
        # 4. 提取场景描述（如果关键元素不够）
        if len(key_elements) < 2:
            scene_patterns = [
                r'展示了([^。\n]{10,50})',
                r'记录了([^。\n]{10,50})',
                r'拍摄的是([^。\n]{10,50})',
            ]
            for pattern in scene_patterns:
                match = re.search(pattern, caption)
                if match:
                    scene_desc = match.group(1).strip()
                    # 清理 markdown 格式
                    scene_desc = re.sub(r'\*\*[^*]+\*\*', '', scene_desc)
                    scene_desc = re.sub(r'\d+\.\s*', '', scene_desc)
                    scene_desc = scene_desc.strip('，。、 -')
                    if scene_desc and scene_desc not in key_elements and len(scene_desc) > 5:
                        key_elements.append(scene_desc)
                    break
        
        # 5. 提取第一句核心描述作为兜底
        if not key_elements:
            # 尝试提取第一段有意义的描述
            first_para = caption.split('\n')[0]
            # 清理模板文字和 markdown
            first_para = re.sub(r'这张图片是|这是一张|图片中|照片中|具体来说[：:]?', '', first_para)
            first_para = re.sub(r'\*\*[^*]+\*\*', '', first_para)
            first_para = re.sub(r'\d+\.\s*', '', first_para)
            first_para = first_para.strip('，。、 -')
            if len(first_para) > 10 and len(first_para) < 60:
                key_elements.append(first_para)
        
        # 去重并组合
        seen = set()
        unique_elements = []
        for elem in key_elements:
            # 清理每个元素
            elem_clean = elem.strip('，。、 -')
            elem_clean = re.sub(r'\*\*[^*]+\*\*', '', elem_clean)  # 移除残留的 markdown
            elem_clean = elem_clean.strip()
            if elem_clean and elem_clean not in seen and len(elem_clean) > 2:
                seen.add(elem_clean)
                unique_elements.append(elem_clean)
        
        if unique_elements:
            # 组合所有关键元素（不再强制截断）
            result = '，'.join(unique_elements[:5])  # 最多取5个元素
            return result
        
        # 最后兜底：清理后的 caption（不再强制截断）
        clean_caption = re.sub(r'\*\*[^*]+\*\*', '', caption)
        clean_caption = re.sub(r'\d+\.\s*', '', clean_caption)
        clean_caption = re.sub(r'这张图片是|这是一张|图片中|照片中|具体来说[：:]?', '', clean_caption)
        clean_caption = clean_caption.strip('，。、 -\n')
        # 取第一段有意义的内容
        first_meaningful = clean_caption.split('\n')[0] if clean_caption else ''
        return first_meaningful if first_meaningful else '图片'
    
    def _summarize_ocr(self, ocr_text: str, max_length: int) -> str:
        """压缩 OCR 文字"""
        # 移除多余的空白和换行
        text = re.sub(r'\s+', ' ', ocr_text).strip()
        
        # 截断
        if len(text) > max_length:
            text = text[:max_length-3] + '...'
        
        return text
    
    def _extract_emotion(self, caption: str) -> str:
        """提取情绪氛围"""
        emotion_keywords = {
            '欢乐': ['开心', '快乐', '高兴', '愉快', '欢乐', '笑', '幸福'],
            '温馨': ['温馨', '温暖', '舒适', '惬意', '美好', '甜蜜'],
            '严肃': ['严肃', '正式', '庄重', '认真'],
            '紧张': ['紧张', '焦虑', '担心', '害怕'],
            '悲伤': ['悲伤', '难过', '伤心', '哭'],
            '平静': ['平静', '安静', '宁静', '淡然']
        }
        
        for emotion, keywords in emotion_keywords.items():
            if any(kw in caption for kw in keywords):
                return emotion
        
        return '中性'
    
    def _extract_intent(self, caption: str) -> str:
        """提取发送意图"""
        intent_keywords = {
            '分享日常': ['分享', '记录', '日常', '生活'],
            '展示成果': ['展示', '成果', '完成', '做好'],
            '求助': ['求助', '帮忙', '怎么', '如何'],
            '炫耀': ['炫耀', '厉害', '牛', '棒'],
            '记录': ['记录', '留念', '纪念']
        }
        
        for intent, keywords in intent_keywords.items():
            if any(kw in caption for kw in keywords):
                return intent
        
        return '分享'
    
    def _generate_text_primary_summary(self, ocr_text: str) -> str:
        """
        为 TEXT_PRIMARY 图片生成 summary
        
        策略：
        1. 识别文档类型
        2. 判断是功能性截图还是情感/观点类
        3. 功能性：简洁标签 + 关键词
        4. 情感类：保留核心表达
        """
        # 清理 OCR 文本
        text = re.sub(r'\s+', ' ', ocr_text).strip()
        
        # 识别文档类型
        doc_type = self._classify_document_type(text)
        
        # 判断是否为情感/观点类内容
        is_emotional = self._is_emotional_content(text, doc_type)
        
        if is_emotional:
            # 情感类：保留核心表达
            key_content = self._extract_emotional_content(text)
        else:
            # 功能性：简洁关键词
            key_content = self._extract_functional_keywords(text, doc_type)
        
        # 组合 summary
        if key_content:
            return f"[{doc_type}] {key_content}"
        else:
            # 兜底
            return f"[{doc_type}] 截图"
    
    def _is_emotional_content(self, text: str, doc_type: str) -> bool:
        """判断是否为情感/观点类内容"""
        # 情感类文档类型
        emotional_types = ['聊天截图', '社交截图', '日常分享']
        if doc_type not in emotional_types:
            return False
        
        # 情感关键词
        emotional_markers = [
            '开心', '难过', '伤心', '高兴', '感动', '生气', '害怕',
            '喜欢', '讨厌', '爱', '恨', '想念', '期待', '失望',
            '太棒了', '真好', '好美', '好可爱', '好难', '好累',
            '哈哈', '呜呜', '嘻嘻', '哭', '笑', '感觉',
            '！！', '？？', '...', '～',
        ]
        
        # 名言关键词（这些内容值得保留）
        famous_markers = [
            '此心光明', '知行合一', '致良知', '亦复何言',
            '立德', '立功', '立言', '心之本体', '阳明',
        ]
        
        # 引号内容（支持多种引号格式）
        has_quotes = bool(re.search(r'[""「」『』"\']', text))
        
        # 感叹句
        has_exclamation = text.count('！') >= 2 or text.count('!') >= 2
        
        # 包含情感词
        has_emotional_words = any(kw in text for kw in emotional_markers)
        
        # 包含名言
        has_famous_words = any(kw in text for kw in famous_markers)
        
        return has_quotes or has_exclamation or has_emotional_words or has_famous_words
    
    def _extract_emotional_content(self, text: str) -> str:
        """提取情感/观点类内容的核心表达"""
        result_parts = []
        
        # 1. 优先提取名言/金句（这些是最有价值的）
        famous_phrases = [
            '此心光明', '知行合一', '致良知', '亦复何言',
            '立德立功立言', '天下无不可化之人', '心之本体',
        ]
        for phrase in famous_phrases:
            if phrase in text:
                result_parts.append(f'"{phrase}"')
                if len(result_parts) >= 2:
                    break
        
        # 2. 提取感叹句
        if not result_parts:
            exclamations = re.findall(r'([^。！？\n]{5,30}[！!]{1,3})', text)
            for exc in exclamations[:1]:
                exc = exc.strip()
                if len(exc) > 5:
                    result_parts.append(exc)
        
        # 3. 提取带情感词的句子
        if not result_parts:
            emotional_patterns = [
                r'(今天[^。\n]{5,30})',
                r'(好[开高难累美可]{1}[^。\n]{3,20})',
                r'(特别[^。\n]{3,20})',
                r'(真的[^。\n]{3,20})',
                r'(感觉[^。\n]{5,30})',
            ]
            for pattern in emotional_patterns:
                match = re.search(pattern, text)
                if match:
                    result_parts.append(match.group(1).strip())
                    break
        
        # 4. 提取引号内的短内容（过滤掉太长的）
        if not result_parts:
            # 匹配短引号内容
            short_quotes = re.findall(r'[""「」『』"]([^""「」『』"]{2,15})[""「」『』"]', text)
            for q in short_quotes[:2]:
                q = q.strip()
                if len(q) >= 2 and q not in str(result_parts):
                    result_parts.append(f'"{q}"')
        
        if result_parts:
            result = '，'.join(result_parts)
            if len(result) > 50:
                result = result[:47] + '...'
            return result
        
        # 兜底：取有意义的片段
        return self._extract_functional_keywords(text, '日常分享')
    
    def _extract_functional_keywords(self, text: str, doc_type: str) -> str:
        """提取功能性截图的关键词"""
        keywords = []
        
        # 品牌/App名称
        brand_patterns = [
            r'(携程|美团|饿了么|淘宝|京东|社交媒体|微博|抖音|CHAT_APP)',
            r'(GRE|雅思|托福|考满分|扇贝|百词斩)',
            r'(Kindle|得到|喜马拉雅|网易云)',
            r'(霸王茶姬|喜茶|奈雪|瑞幸|星巴克)',
        ]
        for pattern in brand_patterns:
            matches = re.findall(pattern, text)
            keywords.extend(matches[:2])
        
        # 地点名称
        place_patterns = [
            r'(CITY_LIST)',
            r'([^\s]{2,4}(?:区|市|县|镇|街|路|广场|公园|景区|酒店))',
        ]
        for pattern in place_patterns:
            matches = re.findall(pattern, text)
            for m in matches[:1]:
                if m not in keywords:
                    keywords.append(m)
        
        # 主题词（根据类型）
        if doc_type == '英语学习':
            topic_matches = re.findall(r'(单词|词汇|阅读|写作|听力|口语|语法)', text)
            keywords.extend(topic_matches[:1])
        elif doc_type == '旅游信息':
            topic_matches = re.findall(r'(门票|酒店|机票|游船|景点|攻略)', text)
            keywords.extend(topic_matches[:1])
        elif doc_type == '美食分享':
            topic_matches = re.findall(r'(外卖|订单|菜单|餐厅|美食)', text)
            keywords.extend(topic_matches[:1])
        
        # 去重并组合
        seen = set()
        unique_keywords = []
        for kw in keywords:
            if kw and kw not in seen:
                seen.add(kw)
                unique_keywords.append(kw)
        
        if unique_keywords:
            result = '、'.join(unique_keywords[:3])
            # 添加后缀
            suffix_map = {
                '英语学习': '学习内容',
                '旅游信息': '旅游信息',
                '美食分享': '美食内容',
                '购物截图': '购物信息',
                '学习资料': '学习资料',
            }
            suffix = suffix_map.get(doc_type, '截图')
            return f"{result}{suffix}" if result else suffix
        
        # 兜底：提取中文词组
        chinese_words = re.findall(r'[\u4e00-\u9fa5]{2,8}', text)
        if chinese_words:
            # 过滤常见无意义词
            stopwords = {'说点什么', '评论', '点赞', '分享', '发送', '取消', '确定', '返回', '搜索',
                        '相关', '图片', '截图', '内容', '信息', '订单', '详情', '查看', '更多',
                        '下一步', '上一步', '提交', '保存', '删除', '编辑', '设置', '帮助'}
            # 过滤太短或太长的词
            meaningful = [w for w in chinese_words 
                         if w not in stopwords 
                         and 2 <= len(w) <= 6
                         and not re.match(r'^[\d一二三四五六七八九十]+$', w)][:3]
            if meaningful:
                return '、'.join(meaningful)
        
        return '截图'
    
    def _classify_document_type(self, text: str) -> str:
        """识别文档类型"""
        text_lower = text.lower()
        
        # 聊天截图
        if any(kw in text for kw in ['CHAT_APP', '聊天', '消息', '对话', '群聊']):
            return '聊天截图'
        
        # 英语学习 - 放在学习资料前面，更精确
        if any(kw in text_lower for kw in ['单词', '词汇', '英语', '雅思', 'ielts', 'toefl', '托福', 
                                            'vocabulary', 'writing task', '剑雅', '真题', 'cambridge']):
            return '英语学习'
        
        # 学习资料
        if any(kw in text for kw in ['雨课堂', '课程', '学习', '笔记', '教材', '讲义', '作业']):
            return '学习资料'
        
        # 旅游信息
        if any(kw in text for kw in ['携程', '旅游', '景点', '门票', '酒店', '机票', '游船']):
            return '旅游信息'
        
        # 社交截图
        if any(kw in text for kw in ['评论', '点赞', '分享', '朋友圈', '社交媒体', '短视频', '社交平台']):
            return '社交截图'
        
        # 美食分享
        if any(kw in text for kw in ['美食', '餐厅', '菜单', '点餐', '外卖', '饿了么', '美团']):
            return '美食分享'
        
        # 购物截图
        if any(kw in text for kw in ['购物', '淘宝', '京东', '价格', '订单', '商品', '优惠']):
            return '购物截图'
        
        # 兜底：日常分享
        return '日常分享'
    
    def _extract_document_key_content(self, text: str) -> str:
        """从文档 OCR 中提取关键内容"""
        # 移除常见的 UI 元素文字
        ui_patterns = [
            r'评论', r'点赞', r'分享', r'收藏', r'转发',
            r'发送', r'取消', r'确定', r'返回',
            r'\d{1,2}:\d{2}', r'\d{4}-\d{2}-\d{2}',  # 时间日期
        ]
        
        clean_text = text
        for pattern in ui_patterns:
            clean_text = re.sub(pattern, ' ', clean_text)
        
        # 清理多余空格
        clean_text = re.sub(r'\s+', ' ', clean_text).strip()
        
        # 提取有意义的片段（长度 > 5 的连续文字）
        segments = []
        for seg in re.split(r'[。\n，、；]', clean_text):
            seg = seg.strip()
            if len(seg) > 5 and len(seg) < 50:
                # 过滤纯数字或纯符号
                if re.search(r'[\u4e00-\u9fa5a-zA-Z]{2,}', seg):
                    segments.append(seg)
        
        if segments:
            # 取前 2 个有意义的片段
            result = '，'.join(segments[:2])
            if len(result) > 60:
                result = result[:57] + '...'
            return result
        
        # 兜底：返回清理后的前 50 字
        if len(clean_text) > 50:
            return clean_text[:47] + '...'
        return clean_text if clean_text else ''
    
    def get_stats(self) -> Dict:
        """获取统计信息"""
        stats = self.stats.copy()
        if stats["total_compressed_length"] > 0:
            stats["avg_compression_ratio"] = round(
                stats["total_original_length"] / stats["total_compressed_length"], 2
            )
        return stats


def load_image_data(caption_path: str, ocr_path: str) -> Tuple[List[Dict], Dict[str, Dict]]:
    """
    加载图片数据
    
    Returns:
        (caption_list, ocr_dict)
        ocr_dict: msg_uid -> ocr_data
    """
    captions = []
    with open(caption_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                captions.append(json.loads(line))
    
    ocr_dict = {}
    ocr_path = Path(ocr_path)
    if ocr_path.exists():
        with open(ocr_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    data = json.loads(line)
                    msg_uid = data.get('msg_uid')
                    if msg_uid:
                        ocr_dict[msg_uid] = data
    
    return captions, ocr_dict


def save_compressed(images: List[Dict], output_path: str):
    """保存压缩结果"""
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        for image in images:
            f.write(json.dumps(image, ensure_ascii=False) + '\n')
