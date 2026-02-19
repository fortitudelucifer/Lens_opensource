# -*- coding: utf-8 -*-
"""
隐私保护层

实现 PII 检测和匿名化
支持 L1 可逆匿名化和 L2 不可逆匿名化

架构（2026-02-06 简化）：
- 两阶段 PII 检测（推荐）：高精度人名检测
- 规则引擎：电话、邮箱、身份证、CHAT_APP_ID 等
- 配置映射：已知人名和地名

注意：GLiNER 已废弃，因中文误检率高。
详见 scripts/compression/two_stage_pii.py

用法：
    from scripts.compression.privacy_shield import PrivacyShield
    
    # 推荐：使用两阶段 PII 检测
    shield = PrivacyShield(use_two_stage_pii=True)
    
    # L1 可逆匿名化
    anonymized = shield.anonymize_l1(message)
    
    # L2 不可逆匿名化
    anonymized = shield.anonymize_l2(message)
"""

import json
import re
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from datetime import datetime
import yaml

# 尝试导入两阶段 PII 检测器
try:
    from scripts.compression.two_stage_pii.scanner import TwoStagePIIScanner
    HAS_TWO_STAGE_PII = True
except ImportError:
    try:
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).parent.parent.parent))
        from scripts.compression.two_stage_pii.scanner import TwoStagePIIScanner
        HAS_TWO_STAGE_PII = True
    except ImportError:
        HAS_TWO_STAGE_PII = False
        TwoStagePIIScanner = None


@dataclass
class PIIMatch:
    """PII 匹配结果"""
    type: str           # 类型：phone, email, id_card, chat_app_id, name
    value: str          # 原始值
    start: int          # 起始位置
    end: int            # 结束位置
    replacement: str    # 替换值
    confidence: float = 1.0  # 置信度
    source: str = 'regex'    # 检测来源


@dataclass
class AnonymizationConfig:
    """匿名化配置"""
    # L1 配置
    l1_enabled: bool = True
    vault_path: str = "local_secrets/identity_map.json"
    encryption: bool = True
    
    # L2 配置
    l2_enabled: bool = True
    preserve_relative_time: bool = True
    preserve_period: bool = True
    preserve_day_type: bool = True
    location_level: str = "city"
    
    # L2 云端训练专用配置
    timestamp_shift_enabled: bool = True
    shift_days: int = 100  # 时间戳偏移天数
    relative_time_enabled: bool = True
    
    # PII 模式
    pii_patterns: Dict[str, str] = field(default_factory=dict)
    
    # 别名组
    alias_groups: Dict[str, List[str]] = field(default_factory=dict)


class PrivacyShield:
    """隐私保护层：PII 检测和匿名化"""
    
    def __init__(self, config_path: str = "configs/compression.yaml",
                 anonymization_config_path: str = "configs/anonymization.yaml",
                 use_two_stage_pii: bool = False,
                 confirmed_names_path: str = "configs/confirmed_names.yaml"):
        """
        初始化隐私保护层
        
        Args:
            config_path: 压缩配置文件路径
            anonymization_config_path: 匿名化配置文件路径
            use_two_stage_pii: 是否使用两阶段 PII 检测（推荐）
            confirmed_names_path: 确认人名列表路径（两阶段 PII 用）
        """
        self.config = self._load_config(config_path)
        self.anon_config = self._load_anonymization_config(anonymization_config_path)
        self.shield_config = self._parse_shield_config()
        
        # 实体映射表（用于一致性伪匿名化）
        self._entity_map: Dict[str, str] = {}
        self._entity_counter = 0
        
        # 加载已有的映射表
        self._load_identity_map()
        
        # 对话基准时间戳（用于计算相对时间）
        self._base_timestamp: Optional[int] = None
        
        # 地名映射表
        self._location_mapping = self.anon_config.get('location_mapping', {})
        
        # 两阶段 PII 检测器
        self._two_stage_scanner: Optional['TwoStagePIIScanner'] = None
        self._use_two_stage_pii = use_two_stage_pii and HAS_TWO_STAGE_PII
        
        if self._use_two_stage_pii:
            confirmed_path = Path(confirmed_names_path)
            if confirmed_path.exists():
                try:
                    self._two_stage_scanner = TwoStagePIIScanner(
                        config_path=config_path,
                        confirmed_names_path=str(confirmed_path),
                    )
                    print("[INFO] 已启用两阶段 PII 检测")
                except Exception as e:
                    print(f"[WARN] 两阶段 PII 检测初始化失败: {e}")
                    self._use_two_stage_pii = False
            else:
                print(f"[WARN] 确认人名列表不存在: {confirmed_path}")
                print("[INFO] 请先运行 'python scripts/compression/two_stage_pii.py scan' 生成")
                self._use_two_stage_pii = False
        
        if not self._use_two_stage_pii:
            print("[INFO] 使用规则引擎进行 PII 检测")
        
        # 统计信息
        self.stats = {
            "total_processed": 0,
            "pii_detected": 0,
            "names_replaced": 0,
            "phones_replaced": 0,
            "emails_replaced": 0,
            "locations_replaced": 0,
            "timestamps_generalized": 0,
            "timestamps_shifted": 0,
            "two_stage_detections": 0
        }
    
    def _load_config(self, config_path: str) -> dict:
        """加载压缩配置"""
        path = Path(config_path)
        if not path.exists():
            return {}
        with open(path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    
    def _load_anonymization_config(self, config_path: str) -> dict:
        """加载匿名化配置"""
        path = Path(config_path)
        if not path.exists():
            return {}
        with open(path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    
    def _parse_shield_config(self) -> AnonymizationConfig:
        """解析隐私保护配置"""
        anon_cfg = self.config.get('anonymization', {})
        l1_cfg = anon_cfg.get('l1', {})
        l2_cfg = anon_cfg.get('l2', {})
        
        # L2 云端训练专用配置
        l2_cloud_cfg = self.anon_config.get('l2_cloud', {})
        ts_shift_cfg = l2_cloud_cfg.get('timestamp_shift', {})
        rel_time_cfg = l2_cloud_cfg.get('relative_time', {})
        
        # 默认 PII 模式
        default_patterns = {
            'phone': r'1[3-9]\d{9}',
            'email': r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}',
            'id_card': r'\d{17}[\dXx]',
            'chat_app_id': r'wxid_[a-zA-Z0-9]+'
        }
        
        pii_patterns = l2_cfg.get('pii_patterns', default_patterns)
        
        # 构建别名组
        alias_groups = {}
        me_names = self.anon_config.get('me_names', [])
        other_names = self.anon_config.get('other_names', [])
        
        if me_names:
            alias_groups['ME'] = me_names
        if other_names:
            alias_groups['OTHER'] = other_names
        
        return AnonymizationConfig(
            l1_enabled=l1_cfg.get('enabled', True),
            vault_path=l1_cfg.get('vault_path', 'local_secrets/identity_map.json'),
            encryption=l1_cfg.get('encryption', True),
            l2_enabled=l2_cfg.get('enabled', True),
            preserve_relative_time=l2_cfg.get('timestamp', {}).get('preserve_relative', True),
            preserve_period=l2_cfg.get('timestamp', {}).get('preserve_period', True),
            preserve_day_type=l2_cfg.get('timestamp', {}).get('preserve_day_type', True),
            location_level=l2_cfg.get('location', {}).get('level', 'city'),
            timestamp_shift_enabled=ts_shift_cfg.get('enabled', True),
            shift_days=ts_shift_cfg.get('shift_days', 100),
            relative_time_enabled=rel_time_cfg.get('enabled', True),
            pii_patterns=pii_patterns,
            alias_groups=alias_groups
        )
    
    def _load_identity_map(self):
        """加载已有的身份映射表"""
        vault_path = Path(self.shield_config.vault_path)
        if vault_path.exists():
            try:
                with open(vault_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self._entity_map = data.get('entity_map', {})
                    self._entity_counter = data.get('counter', 0)
            except Exception as e:
                print(f"[WARN] 加载身份映射表失败: {e}")
    
    def _save_identity_map(self):
        """保存身份映射表"""
        vault_path = Path(self.shield_config.vault_path)
        vault_path.parent.mkdir(parents=True, exist_ok=True)
        
        data = {
            'entity_map': self._entity_map,
            'counter': self._entity_counter,
            'updated_at': datetime.now().isoformat()
        }
        
        with open(vault_path, 'w', encoding='utf-8') as f:
            json.dump(data, ensure_ascii=False, indent=2, fp=f)
    
    def detect_pii(self, text: str) -> List[PIIMatch]:
        """
        检测文本中的 PII
        
        检测优先级：
        1. 两阶段 PII 检测（如果启用）- 基于确认人名列表的精确匹配
        2. 规则引擎（正则 + 配置映射）
        
        Args:
            text: 输入文本
        
        Returns:
            PII 匹配列表
        """
        matches = []
        
        # 获取排除模式
        exclude_patterns = self.anon_config.get('exclude_patterns', [])
        
        # 优先使用两阶段 PII 检测
        if self._use_two_stage_pii and self._two_stage_scanner is not None:
            scanner_matches = self._two_stage_scanner.detect(text)
            
            for sm in scanner_matches:
                # 获取替换值
                replacement = self._get_replacement_for_type(sm.type, sm.value)
                
                matches.append(PIIMatch(
                    type=sm.type.lower(),
                    value=sm.value,
                    start=sm.start,
                    end=sm.end,
                    replacement=replacement,
                    confidence=sm.confidence,
                    source='two_stage_pii'
                ))
                
                self.stats["two_stage_detections"] += 1
            
            # 两阶段检测只处理确认人名，me_names/other_names 仍需规则引擎
            # 注意：skip_names=False 以确保 me_names/other_names 被处理
            rule_matches = self._detect_pii_by_rules(text, exclude_patterns, skip_names=False)
            matches.extend(rule_matches)
        else:
            # 使用规则引擎
            matches = self._detect_pii_by_rules(text, exclude_patterns)
        
        # 去重：两阶段检测 + 规则引擎可能在同一位置重复检测同一名字
        # 不去重会导致双重替换 bug（如 "双双" → "OTHERHER"）
        seen_positions = set()
        deduped = []
        for m in matches:
            pos_key = (m.start, m.end)
            if pos_key not in seen_positions:
                seen_positions.add(pos_key)
                deduped.append(m)
        matches = deduped
        
        # 按位置排序（从后往前替换）
        matches.sort(key=lambda x: x.start, reverse=True)
        
        return matches
    
    def _detect_pii_by_rules(self, text: str, exclude_patterns: List[str], 
                              skip_names: bool = False) -> List[PIIMatch]:
        """
        规则引擎 PII 检测
        
        Args:
            text: 输入文本
            exclude_patterns: 排除模式列表
            skip_names: 是否跳过人名检测（两阶段 PII 模式下使用）
        
        Returns:
            PII 匹配列表
        """
        matches = []
        
        # 正则检测
        for pii_type, pattern in self.shield_config.pii_patterns.items():
            for match in re.finditer(pattern, text):
                matches.append(PIIMatch(
                    type=pii_type,
                    value=match.group(),
                    start=match.start(),
                    end=match.end(),
                    replacement=self._get_replacement(pii_type, match.group())
                ))
        
        # 检测名字（如果未跳过）
        if not skip_names:
            for alias, names in self.shield_config.alias_groups.items():
                for name in names:
                    for match in re.finditer(re.escape(name), text):
                        # 检查是否在排除列表中
                        start, end = match.start(), match.end()
                        # 扩展上下文检查（前后各取几个字符）
                        context_start = max(0, start - 5)
                        context_end = min(len(text), end + 5)
                        context = text[context_start:context_end]
                        
                        # 检查是否匹配排除模式
                        # 只排除包含当前名字的排除模式（如 "李雷" 包含 "李"）
                        should_exclude = False
                        for exclude in exclude_patterns:
                            # 只有当排除模式包含当前名字，且排除模式出现在上下文中时才排除
                            if name in exclude and exclude in context:
                                should_exclude = True
                                break
                        
                        if not should_exclude:
                            matches.append(PIIMatch(
                                type='name',
                                value=match.group(),
                                start=match.start(),
                                end=match.end(),
                                replacement=alias
                            ))
        
        return matches
    
    def _get_replacement_for_type(self, pii_type: str, value: str) -> str:
        """
        根据 PII 类型获取替换值
        
        Args:
            pii_type: PII 类型（大写）
            value: 原始值
        
        Returns:
            替换值
        """
        # 先检查是否是已知别名
        alias = self._resolve_alias(value)
        if alias:
            return alias
        
        type_map = {
            'PHONE': '[电话号码]',
            'EMAIL': '[邮箱]',
            'ID_CARD': '[身份证号]',
            'CHAT_APP_ID': '[CHAT_APP_ID]',
            'PERSON': self._pseudonymize(value, 'person'),
            'LOCATION': '[地点]',
            'ORG': '[组织]',
            'DATE': '[日期]',
        }
        
        return type_map.get(pii_type.upper(), f'[{pii_type}]')
    
    def _get_replacement(self, pii_type: str, value: str) -> str:
        """获取 PII 替换值"""
        if pii_type == 'phone':
            return '[电话号码]'
        elif pii_type == 'email':
            return '[邮箱]'
        elif pii_type == 'id_card':
            return '[身份证号]'
        elif pii_type == 'chat_app_id':
            return '[CHAT_APP_ID]'
        else:
            return f'[{pii_type}]'
    
    def _resolve_alias(self, name: str) -> Optional[str]:
        """
        解析别名，返回统一的代号
        
        Args:
            name: 名字或别名
        
        Returns:
            统一代号（如 'ME', 'OTHER'）或 None
        """
        for alias, names in self.shield_config.alias_groups.items():
            if name in names:
                return alias
        return None
    
    def _pseudonymize(self, entity: str, entity_type: str = 'person') -> str:
        """
        一致性伪匿名化
        
        Args:
            entity: 实体值
            entity_type: 实体类型
        
        Returns:
            伪匿名化后的代号
        """
        # 先检查是否是已知别名
        alias = self._resolve_alias(entity)
        if alias:
            return alias
        
        # 检查是否已有映射
        key = f"{entity_type}:{entity}"
        if key in self._entity_map:
            return self._entity_map[key]
        
        # 创建新映射
        self._entity_counter += 1
        pseudonym = f"[{entity_type.upper()}_{self._entity_counter}]"
        self._entity_map[key] = pseudonym
        
        return pseudonym

    def _anonymize_recall_message(self, text: str) -> str:
        """
        特殊处理撤回消息的匿名化
        
        撤回消息格式：
        - "You recalled a message." -> 保持不变（ME 撤回）
        - "\"昵称\" recalled a message" -> "OTHER recalled a message"
        - "你撤回了一条消息" -> 保持不变（ME 撤回）
        - "\"昵称\" 撤回了一条消息" -> "OTHER 撤回了一条消息"
        
        Args:
            text: 撤回消息文本
        
        Returns:
            匿名化后的文本
        """
        # 英文格式
        en_pattern = r'\\?"([^"]+)\\?"\s*recalled a message'
        en_match = re.search(en_pattern, text)
        if en_match:
            return 'OTHER recalled a message'
        
        # 中文格式
        cn_pattern = r'\\?"([^"]+)\\?"\s*撤回了一条消息'
        cn_match = re.search(cn_pattern, text)
        if cn_match:
            return 'OTHER 撤回了一条消息'
        
        return text
    
    def _is_recall_message(self, text: str) -> bool:
        """判断是否是撤回消息"""
        if not text:
            return False
        return ('recalled a message' in text.lower() or 
                '撤回了一条消息' in text or 
                '你撤回' in text or 
                'You recalled' in text)
    
    def anonymize_l1(self, message: Dict) -> Dict:
        """
        L1 可逆匿名化
        
        - 替换 PII（保留映射表）
        - 替换名字为代号
        - 保留时间戳
        
        Args:
            message: 消息数据
        
        Returns:
            匿名化后的消息
        """
        self.stats["total_processed"] += 1
        result = message.copy()
        
        # 特殊处理：撤回消息不走 PII 检测，直接替换昵称
        text_raw = result.get('text_raw', '')
        if self._is_recall_message(text_raw):
            result['text_raw'] = self._anonymize_recall_message(text_raw)
            return result
        
        # 处理文本字段
        text_fields = [
            # 基础文本
            'text_raw', 'text', 'punct_text',
            # 图片相关
            'image_summary', 'image_caption', 'image_ocr_text',
            # 视频相关
            'video_summary', 'video_voice_to_text',
            # 语音相关
            'voice_to_text',
            # 表情包相关
            'sticker_caption', 'sticker_ocr_text',
            # 引用/链接相关
            'link_quote_text', 'link_title', 'quote_text'
        ]
        
        for field in text_fields:
            if field in result and result[field]:
                # 跳过 time_gap 类型消息的 text_raw 字段
                if field == 'text_raw' and result.get('type') == 'time_gap':
                    continue
                    
                text = result[field]
                
                # 对于引用字段，保护 ME:/OTHER: 前缀
                prefix = ""
                if field == 'link_quote_text':
                    if text.startswith('ME: '):
                        prefix = 'ME: '
                        text = text[4:]
                    elif text.startswith('OTHER: '):
                        prefix = 'OTHER: '
                        text = text[7:]
                
                # 对于 quote_text 字段，处理 "昵称：" 格式的前缀
                # 格式如 "USER_A：xxx" 或 "USER_B：xxx"
                if field == 'quote_text':
                    # 检查是否有中文冒号分隔的前缀
                    colon_pos = text.find('：')
                    if colon_pos > 0 and colon_pos < 30:  # 前缀不应太长
                        potential_name = text[:colon_pos]
                        # 检查是否是已知的 ME 或 OTHER 名字
                        if potential_name in self.shield_config.alias_groups.get('ME', []):
                            prefix = 'ME：'
                            text = text[colon_pos + 1:]
                        elif potential_name in self.shield_config.alias_groups.get('OTHER', []):
                            prefix = 'OTHER：'
                            text = text[colon_pos + 1:]
                
                pii_matches = self.detect_pii(text)
                
                for match in pii_matches:
                    text = text[:match.start] + match.replacement + text[match.end:]
                    
                    # 统计：name 和 person 都算人名
                    if match.type in ('name', 'person'):
                        self.stats["names_replaced"] += 1
                    elif match.type == 'phone':
                        self.stats["phones_replaced"] += 1
                    elif match.type == 'email':
                        self.stats["emails_replaced"] += 1
                    
                    self.stats["pii_detected"] += 1
                
                result[field] = prefix + text
        
        # 保存映射表
        self._save_identity_map()
        
        return result
    
    def anonymize_l2(self, message: Dict) -> Dict:
        """
        L2 不可逆匿名化（云端训练用）
        
        - 替换 PII（不保留映射）
        - 时间戳泛化（只保留相对时间和时段）
        - 时间戳偏移（防止通过时间定位真实事件）
        - 相对时间计算（相对于对话开始的天数）
        - 地点降精度
        
        Args:
            message: 消息数据
        
        Returns:
            匿名化后的消息
        """
        # 先执行 L1 匿名化
        result = self.anonymize_l1(message)
        
        # 时间戳处理
        if 'ts' in result:
            original_ts = result['ts']
            
            # 1. 时间戳泛化（时段、工作日）
            result['ts_generalized'] = self._generalize_timestamp(original_ts)
            self.stats["timestamps_generalized"] += 1
            
            # 2. 时间戳偏移（云端训练专用）
            if self.shield_config.timestamp_shift_enabled:
                shift_seconds = self.shield_config.shift_days * 24 * 3600
                result['ts_shifted'] = original_ts - shift_seconds
                self.stats["timestamps_shifted"] += 1
            
            # 3. 相对时间计算（云端训练专用）
            if self.shield_config.relative_time_enabled:
                if self._base_timestamp is None:
                    self._base_timestamp = original_ts
                
                relative_seconds = original_ts - self._base_timestamp
                day_index = relative_seconds // (24 * 3600)
                result['day_index'] = day_index
                result['ts_relative'] = f"第{day_index + 1}天"
        
        if 'time_local' in result:
            result['time_generalized'] = self._generalize_time_local(result['time_local'])
        
        # L2 专用：地名替换
        l2_cloud_cfg = self.anon_config.get('l2_cloud', {})
        loc_replace_cfg = l2_cloud_cfg.get('location_replacement', {})
        if loc_replace_cfg.get('enabled', False) and self._location_mapping:
            result = self._replace_locations(result)
        
        return result
    
    def _replace_locations(self, message: Dict) -> Dict:
        """替换文本中的地名"""
        result = message.copy()
        
        text_fields = [
            'text_raw', 'voice_to_text', 'image_summary', 'video_summary',
            'link_quote_text', 'link_title', 'image_caption',
            'image_ocr_text', 'video_voice_to_text'
        ]
        
        for field in text_fields:
            if field in result and result[field]:
                text = result[field]
                
                # 保护 ME:/OTHER: 前缀
                prefix = ""
                if field == 'link_quote_text':
                    if text.startswith('ME: '):
                        prefix = 'ME: '
                        text = text[4:]
                    elif text.startswith('OTHER: '):
                        prefix = 'OTHER: '
                        text = text[7:]
                
                replacements = []
                
                # 按地名长度降序排序
                for loc in sorted(self._location_mapping.keys(), key=len, reverse=True):
                    start = 0
                    while True:
                        pos = text.find(loc, start)
                        if pos == -1:
                            break
                        overlap = False
                        for r_start, r_end, _ in replacements:
                            if not (pos + len(loc) <= r_start or pos >= r_end):
                                overlap = True
                                break
                        if not overlap:
                            replacements.append((pos, pos + len(loc), self._location_mapping[loc]))
                            self.stats["locations_replaced"] += 1
                        start = pos + 1
                
                # 从后往前替换
                replacements.sort(key=lambda x: x[0], reverse=True)
                for start, end, replacement in replacements:
                    text = text[:start] + replacement + text[end:]
                
                result[field] = prefix + text
        
        return result
    
    def set_base_timestamp(self, ts: int):
        """设置对话基准时间戳"""
        self._base_timestamp = ts
    
    def reset_base_timestamp(self):
        """重置基准时间戳"""
        self._base_timestamp = None
    
    def _generalize_timestamp(self, ts: int) -> Dict:
        """泛化时间戳"""
        dt = datetime.fromtimestamp(ts)
        
        hour = dt.hour
        if 0 <= hour < 6:
            period = '凌晨'
        elif 6 <= hour < 12:
            period = '上午'
        elif 12 <= hour < 18:
            period = '下午'
        else:
            period = '晚上'
        
        day_type = '周末' if dt.weekday() >= 5 else '工作日'
        
        return {
            'period': period,
            'day_type': day_type,
            'hour_range': f"{(hour // 3) * 3}-{(hour // 3) * 3 + 3}时"
        }
    
    def _generalize_time_local(self, time_local: str) -> str:
        """泛化本地时间字符串"""
        try:
            dt = datetime.strptime(time_local, '%Y-%m-%d %H:%M:%S')
            hour = dt.hour
            
            if 0 <= hour < 6:
                period = '凌晨'
            elif 6 <= hour < 12:
                period = '上午'
            elif 12 <= hour < 18:
                period = '下午'
            else:
                period = '晚上'
            
            day_type = '周末' if dt.weekday() >= 5 else '工作日'
            
            return f"{day_type} {period}"
        except:
            return time_local
    
    def get_stats(self) -> Dict:
        """获取统计信息"""
        return self.stats.copy()
    
    def unload_models(self):
        """卸载模型，释放显存（保留接口兼容性）"""
        pass


def main():
    """测试隐私保护层"""
    print("=" * 60)
    print("隐私保护层测试")
    print("=" * 60)
    
    shield = PrivacyShield()
    
    # 测试 PII 检测
    test_text = "我的电话是PHONE_PLACEHOLDER，邮箱是example@domain.com，CHAT_APP是wxid_example123"
    matches = shield.detect_pii(test_text)
    
    print(f"\n原文: {test_text}")
    print("检测结果:")
    for match in matches:
        print(f"  [{match.source}] {match.type}: {match.value} -> {match.replacement}")
    
    # 测试匿名化
    test_message = {
        'text_raw': '我的电话是PHONE_PLACEHOLDER',
        'ts': 1752503924,
        'time_local': '2025-07-14 22:38:44'
    }
    
    print("\n=== L1 匿名化测试 ===")
    l1_result = shield.anonymize_l1(test_message.copy())
    print(f"原文: {test_message['text_raw']}")
    print(f"L1: {l1_result['text_raw']}")
    
    print("\n=== L2 匿名化测试 ===")
    l2_result = shield.anonymize_l2(test_message.copy())
    print(f"L2: {l2_result['text_raw']}")
    print(f"时间泛化: {l2_result.get('ts_generalized')}")
    
    print("\n=== 统计 ===")
    import json
    print(json.dumps(shield.get_stats(), indent=2, ensure_ascii=False))
    
    print("\n提示：人名检测建议使用两阶段 PII 检测")
    print("运行: python scripts/compression/two_stage_pii.py scan")


if __name__ == '__main__':
    main()
