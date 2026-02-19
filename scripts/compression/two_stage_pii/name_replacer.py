# -*- coding: utf-8 -*-
"""
人名替换器

基于确认人名列表进行精确字符串匹配替换。
支持一致性映射（ME/OTHER/PERSON_N）和长度优先替换策略。
"""

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import yaml

from .models import ConfirmedName, ConfirmedNames


@dataclass
class Replacement:
    """替换记录"""
    original: str       # 原始人名
    replacement: str    # 替换代号
    start: int          # 起始位置
    end: int            # 结束位置


class NameReplacer:
    """基于确认列表的精确人名替换"""
    
    def __init__(self, 
                 confirmed_names_path: Optional[str] = None,
                 anonymization_config_path: str = "configs/anonymization.yaml",
                 identity_map_path: str = "local_secrets/identity_map.json"):
        """
        初始化替换器
        
        Args:
            confirmed_names_path: 确认人名列表路径（可选，可后续加载）
            anonymization_config_path: 匿名化配置路径
            identity_map_path: 身份映射持久化路径
        """
        self.confirmed_names_path = confirmed_names_path
        self.anonymization_config_path = anonymization_config_path
        self.identity_map_path = identity_map_path
        
        # 确认人名列表（按长度降序排列）
        self.confirmed_names: List[ConfirmedName] = []
        
        # 身份映射：原始人名 -> 替换代号
        self.identity_map: Dict[str, str] = {}
        
        # 下一个 PERSON_N 编号
        self._next_person_id = 1
        
        # 从 anonymization.yaml 加载的特殊映射
        self.me_names: Set[str] = set()      # 映射到 ME 的名字
        self.other_names: Set[str] = set()   # 映射到 OTHER 的名字
        
        # 加载配置
        self._load_anonymization_config()
        self._load_identity_map()
        
        # 如果提供了确认人名路径，加载它
        if confirmed_names_path:
            self.load_confirmed_names(confirmed_names_path)
    
    def _load_anonymization_config(self):
        """从 anonymization.yaml 加载特殊映射"""
        config_path = Path(self.anonymization_config_path)
        if not config_path.exists():
            print(f"[WARN] 匿名化配置不存在: {config_path}")
            return
        
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
            
            # 加载 ME 映射
            if 'me_names' in config:
                self.me_names = set(config['me_names'])
            
            # 加载 OTHER 映射
            if 'other_names' in config:
                self.other_names = set(config['other_names'])
                
        except Exception as e:
            print(f"[WARN] 加载匿名化配置失败: {e}")
    
    def _load_identity_map(self):
        """加载持久化的身份映射"""
        map_path = Path(self.identity_map_path)
        if not map_path.exists():
            return
        
        try:
            with open(map_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            self.identity_map = data.get('mappings', {})
            self._next_person_id = data.get('next_person_id', 1)
            
        except Exception as e:
            print(f"[WARN] 加载身份映射失败: {e}")
    
    def save_identity_map(self):
        """保存身份映射到文件"""
        map_path = Path(self.identity_map_path)
        map_path.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            data = {
                'mappings': self.identity_map,
                'next_person_id': self._next_person_id,
                'updated_at': datetime.now().isoformat(),
            }
            
            with open(map_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                
        except Exception as e:
            print(f"[ERROR] 保存身份映射失败: {e}")
    
    def load_confirmed_names(self, path: str):
        """
        加载确认人名列表
        
        只加载 category == "real_name" 的条目
        
        Args:
            path: 确认人名列表路径
        """
        self.confirmed_names_path = path
        
        confirmed = ConfirmedNames.load(path)
        
        # 只保留真实人名，并去重
        seen_names = set()
        real_names = []
        for name in confirmed.names:
            if name.category == "real_name" and name.text not in seen_names:
                real_names.append(name)
                seen_names.add(name.text)
        
        # 按长度降序排列（长名字优先替换）
        self.confirmed_names = sorted(
            real_names,
            key=lambda x: len(x.text),
            reverse=True
        )
        
        print(f"[INFO] 加载 {len(self.confirmed_names)} 个确认人名")
    
    def get_replacement(self, name: str) -> str:
        """
        获取人名的替换代号
        
        Args:
            name: 原始人名
        
        Returns:
            替换代号 (ME/OTHER/PERSON_N)
        """
        # 检查是否已有映射
        if name in self.identity_map:
            return self.identity_map[name]
        
        # 检查是否是 ME
        if name in self.me_names:
            replacement = "ME"
        # 检查是否是 OTHER
        elif name in self.other_names:
            replacement = "OTHER"
        # 分配新的 PERSON_N
        else:
            replacement = f"PERSON_{self._next_person_id}"
            self._next_person_id += 1
        
        # 保存映射
        self.identity_map[name] = replacement
        
        return replacement
    
    def replace_names(self, text: str) -> Tuple[str, List[Replacement]]:
        """
        替换文本中的人名
        
        使用标记-替换两阶段策略，避免重叠问题。
        
        Args:
            text: 输入文本
        
        Returns:
            (替换后的文本, 替换记录列表)
        """
        if not text or not self.confirmed_names:
            return text, []
        
        # 阶段1：在原始文本上找出所有匹配位置
        matches: List[Tuple[int, int, str]] = []  # (start, end, name)
        
        for confirmed in self.confirmed_names:
            name = confirmed.text
            start = 0
            while True:
                pos = text.find(name, start)
                if pos == -1:
                    break
                
                end_pos = pos + len(name)
                
                # 检查是否与已有匹配重叠
                overlaps = False
                for m_start, m_end, _ in matches:
                    if not (end_pos <= m_start or pos >= m_end):
                        overlaps = True
                        break
                
                if not overlaps:
                    matches.append((pos, end_pos, name))
                
                start = pos + 1
        
        # 按位置排序
        matches.sort(key=lambda x: x[0])
        
        # 阶段2：从后向前替换（避免位置偏移）
        result = text
        replacements: List[Replacement] = []
        
        for start, end, name in reversed(matches):
            replacement_code = self.get_replacement(name)
            replacement_text = f"[{replacement_code}]"
            result = result[:start] + replacement_text + result[end:]
            
            replacements.append(Replacement(
                original=name,
                replacement=replacement_code,
                start=start,
                end=start + len(replacement_text),
            ))
        
        # 反转 replacements 使其按位置正序
        replacements.reverse()
        
        return result, replacements
    
    def replace_names_batch(self, texts: List[str]) -> List[Tuple[str, List[Replacement]]]:
        """
        批量替换文本中的人名
        
        Args:
            texts: 输入文本列表
        
        Returns:
            [(替换后的文本, 替换记录列表), ...]
        """
        return [self.replace_names(text) for text in texts]
    
    def get_all_mappings(self) -> Dict[str, str]:
        """获取所有身份映射"""
        return dict(self.identity_map)
    
    def set_mapping(self, name: str, replacement: str):
        """
        手动设置映射
        
        Args:
            name: 原始人名
            replacement: 替换代号
        """
        self.identity_map[name] = replacement
    
    def clear_mappings(self):
        """清除所有映射"""
        self.identity_map.clear()
        self._next_person_id = 1


def replace_names_in_text(text: str, 
                          confirmed_names: List[str],
                          identity_map: Dict[str, str] = None) -> Tuple[str, Dict[str, str]]:
    """
    独立函数：替换文本中的人名（用于测试）
    
    使用标记-替换两阶段策略，避免重叠问题。
    
    Args:
        text: 输入文本
        confirmed_names: 确认人名列表
        identity_map: 已有的身份映射（可选）
    
    Returns:
        (替换后的文本, 更新后的身份映射)
    """
    if identity_map is None:
        identity_map = {}
    
    if not text or not confirmed_names:
        return text, identity_map
    
    # 按长度降序排列
    sorted_names = sorted(confirmed_names, key=len, reverse=True)
    
    # 分配 PERSON_N 编号
    next_id = 1
    for existing_replacement in identity_map.values():
        if existing_replacement.startswith("PERSON_"):
            try:
                num = int(existing_replacement.split("_")[1])
                next_id = max(next_id, num + 1)
            except:
                pass
    
    # 为所有名字预分配映射
    for name in sorted_names:
        if name not in identity_map:
            identity_map[name] = f"PERSON_{next_id}"
            next_id += 1
    
    # 阶段1：找出所有匹配位置（在原始文本上）
    matches: List[Tuple[int, int, str]] = []  # (start, end, name)
    
    for name in sorted_names:
        start = 0
        while True:
            pos = text.find(name, start)
            if pos == -1:
                break
            
            end_pos = pos + len(name)
            
            # 检查是否与已有匹配重叠
            overlaps = False
            for m_start, m_end, _ in matches:
                if not (end_pos <= m_start or pos >= m_end):
                    overlaps = True
                    break
            
            if not overlaps:
                matches.append((pos, end_pos, name))
            
            start = pos + 1
    
    # 按位置排序
    matches.sort(key=lambda x: x[0])
    
    # 阶段2：从后向前替换（避免位置偏移）
    result = text
    for start, end, name in reversed(matches):
        replacement_text = f"[{identity_map[name]}]"
        result = result[:start] + replacement_text + result[end:]
    
    return result, identity_map


def get_replacement_for_name(name: str,
                             identity_map: Dict[str, str],
                             me_names: Set[str] = None,
                             other_names: Set[str] = None) -> Tuple[str, Dict[str, str]]:
    """
    独立函数：获取人名的替换代号（用于测试）
    
    Args:
        name: 原始人名
        identity_map: 身份映射
        me_names: ME 名字集合
        other_names: OTHER 名字集合
    
    Returns:
        (替换代号, 更新后的身份映射)
    """
    if me_names is None:
        me_names = set()
    if other_names is None:
        other_names = set()
    
    # 检查已有映射
    if name in identity_map:
        return identity_map[name], identity_map
    
    # 确定替换代号
    if name in me_names:
        replacement = "ME"
    elif name in other_names:
        replacement = "OTHER"
    else:
        # 计算下一个 PERSON_N
        next_id = 1
        for existing in identity_map.values():
            if existing.startswith("PERSON_"):
                try:
                    num = int(existing.split("_")[1])
                    next_id = max(next_id, num + 1)
                except:
                    pass
        replacement = f"PERSON_{next_id}"
    
    # 更新映射
    identity_map = dict(identity_map)
    identity_map[name] = replacement
    
    return replacement, identity_map
