# -*- coding: utf-8 -*-
"""
两阶段 PII 匿名化 - 数据模型

定义候选词、验证结果、确认人名等核心数据结构。
"""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set
import yaml


@dataclass
class CandidateWord:
    """候选词数据结构"""
    text: str                              # 候选词文本
    frequency: int = 1                     # 出现频次
    contexts: List[str] = field(default_factory=list)  # 示例上下文（最多 3 个）
    source_fields: Set[str] = field(default_factory=set)  # 来源字段
    
    def add_context(self, context: str, max_contexts: int = 3):
        """添加上下文示例"""
        if len(self.contexts) < max_contexts and context not in self.contexts:
            # 截取上下文，避免过长
            if len(context) > 100:
                context = context[:100] + "..."
            self.contexts.append(context)
    
    def to_dict(self) -> dict:
        """转换为字典（用于 YAML 序列化）"""
        return {
            'text': self.text,
            'frequency': self.frequency,
            'contexts': self.contexts,
            'source_fields': list(self.source_fields),
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'CandidateWord':
        """从字典创建（用于 YAML 反序列化）"""
        return cls(
            text=data['text'],
            frequency=data.get('frequency', 1),
            contexts=data.get('contexts', []),
            source_fields=set(data.get('source_fields', [])),
        )


@dataclass
class CandidateList:
    """候选词列表"""
    candidates: Dict[str, CandidateWord] = field(default_factory=dict)  # text -> CandidateWord
    total_texts_scanned: int = 0          # 扫描的文本总数
    total_messages_scanned: int = 0       # 扫描的消息总数
    extraction_time: str = ""             # 提取时间
    source_file: str = ""                 # 源文件路径

    def add_candidate(self, text: str, context: str = "", source_field: str = ""):
        """添加或更新候选词"""
        if text in self.candidates:
            self.candidates[text].frequency += 1
            self.candidates[text].add_context(context)
            if source_field:
                self.candidates[text].source_fields.add(source_field)
        else:
            candidate = CandidateWord(text=text)
            candidate.add_context(context)
            if source_field:
                candidate.source_fields.add(source_field)
            self.candidates[text] = candidate
    
    def to_list(self) -> List[CandidateWord]:
        """按频次降序返回候选词列表"""
        return sorted(self.candidates.values(), key=lambda x: -x.frequency)
    
    def __len__(self) -> int:
        return len(self.candidates)
    
    def save(self, path: str):
        """保存到 YAML 文件"""
        data = {
            'version': '1.0',
            'extraction_time': self.extraction_time or datetime.now().isoformat(),
            'source_file': self.source_file,
            'total_messages_scanned': self.total_messages_scanned,
            'total_texts_scanned': self.total_texts_scanned,
            'total_candidates': len(self.candidates),
            'candidates': [c.to_dict() for c in self.to_list()],
        }
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    
    @classmethod
    def load(cls, path: str) -> 'CandidateList':
        """从 YAML 文件加载"""
        with open(path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        
        result = cls(
            total_texts_scanned=data.get('total_texts_scanned', 0),
            total_messages_scanned=data.get('total_messages_scanned', 0),
            extraction_time=data.get('extraction_time', ''),
            source_file=data.get('source_file', ''),
        )
        
        for item in data.get('candidates', []):
            candidate = CandidateWord.from_dict(item)
            result.candidates[candidate.text] = candidate
        
        return result


@dataclass
class ValidationResult:
    """LLM 验证结果"""
    real_names: List[str] = field(default_factory=list)      # 真实人名
    pronouns: List[str] = field(default_factory=list)        # 代词/称谓
    animal_names: List[str] = field(default_factory=list)    # 动物名
    common_words: List[str] = field(default_factory=list)    # 常见词
    uncertain: List[str] = field(default_factory=list)       # 不确定（需人工审核）
    validation_time: str = ""                                # 验证时间
    llm_calls: int = 0                                       # LLM 调用次数
    total_candidates: int = 0                                # 总候选词数
    
    def all_classified(self) -> List[str]:
        """返回所有已分类的词汇"""
        return (self.real_names + self.pronouns + 
                self.animal_names + self.common_words + self.uncertain)
    
    def save(self, path: str):
        """保存到 YAML 文件"""
        data = {
            'version': '1.0',
            'validation_time': self.validation_time or datetime.now().isoformat(),
            'llm_calls': self.llm_calls,
            'total_candidates': self.total_candidates,
            'statistics': {
                'real_names': len(self.real_names),
                'pronouns': len(self.pronouns),
                'animal_names': len(self.animal_names),
                'common_words': len(self.common_words),
                'uncertain': len(self.uncertain),
            },
            'real_names': self.real_names,
            'pronouns': self.pronouns,
            'animal_names': self.animal_names,
            'common_words': self.common_words,
            'uncertain': self.uncertain,
        }
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    
    @classmethod
    def load(cls, path: str) -> 'ValidationResult':
        """从 YAML 文件加载"""
        with open(path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        
        return cls(
            real_names=data.get('real_names', []),
            pronouns=data.get('pronouns', []),
            animal_names=data.get('animal_names', []),
            common_words=data.get('common_words', []),
            uncertain=data.get('uncertain', []),
            validation_time=data.get('validation_time', ''),
            llm_calls=data.get('llm_calls', 0),
            total_candidates=data.get('total_candidates', 0),
        )


@dataclass
class ConfirmedName:
    """确认的人名"""
    text: str                              # 人名文本
    category: str = "real_name"            # 类别：real_name, nickname, alias
    frequency: int = 0                     # 出现频次
    alias: Optional[str] = None            # 预设别名（ME/OTHER/PERSON_N）
    contexts: List[str] = field(default_factory=list)  # 示例上下文
    
    def to_dict(self) -> dict:
        """转换为字典"""
        result = {
            'text': self.text,
            'category': self.category,
            'frequency': self.frequency,
        }
        if self.alias:
            result['alias'] = self.alias
        if self.contexts:
            result['contexts'] = self.contexts
        return result
    
    @classmethod
    def from_dict(cls, data: dict) -> 'ConfirmedName':
        """从字典创建"""
        return cls(
            text=data['text'],
            category=data.get('category', 'real_name'),
            frequency=data.get('frequency', 0),
            alias=data.get('alias'),
            contexts=data.get('contexts', []),
        )


@dataclass
class ConfirmedNames:
    """确认人名配置"""
    version: str = "1.0"
    generated_at: str = ""
    source_file: str = ""
    confirmed_names: List[ConfirmedName] = field(default_factory=list)
    excluded: List[dict] = field(default_factory=list)  # 排除列表
    pending_review: List[dict] = field(default_factory=list)  # 待审核列表
    
    @property
    def names(self) -> List[ConfirmedName]:
        """获取所有确认的人名（别名属性）"""
        return self.confirmed_names
    
    def get_all_names(self) -> List[str]:
        """获取所有确认的人名文本"""
        return [n.text for n in self.confirmed_names]
    
    def get_name_to_alias_map(self) -> Dict[str, str]:
        """获取人名到别名的映射"""
        return {n.text: n.alias for n in self.confirmed_names if n.alias}
    
    def add_name(self, name_or_text, category: str = "real_name", 
                 frequency: int = 0, alias: Optional[str] = None,
                 contexts: List[str] = None):
        """添加确认的人名
        
        Args:
            name_or_text: ConfirmedName 对象或人名文本
            category: 类别（仅当 name_or_text 是字符串时使用）
            frequency: 频次（仅当 name_or_text 是字符串时使用）
            alias: 别名（仅当 name_or_text 是字符串时使用）
            contexts: 上下文列表（仅当 name_or_text 是字符串时使用）
        """
        if isinstance(name_or_text, ConfirmedName):
            self.confirmed_names.append(name_or_text)
        else:
            name = ConfirmedName(
                text=name_or_text,
                category=category,
                frequency=frequency,
                alias=alias,
                contexts=contexts or [],
            )
            self.confirmed_names.append(name)
    
    def remove_name(self, text: str) -> bool:
        """移除人名"""
        for i, name in enumerate(self.confirmed_names):
            if name.text == text:
                self.confirmed_names.pop(i)
                return True
        return False
    
    def save(self, path: str):
        """保存到 YAML 文件"""
        data = {
            'version': self.version,
            'generated_at': self.generated_at or datetime.now().isoformat(),
            'source_file': self.source_file,
            'confirmed_names': [n.to_dict() for n in self.confirmed_names],
            'excluded': self.excluded,
            'pending_review': self.pending_review,
        }
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    
    @classmethod
    def load(cls, path: str) -> 'ConfirmedNames':
        """从 YAML 文件加载"""
        with open(path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        
        result = cls(
            version=data.get('version', '1.0'),
            generated_at=data.get('generated_at', ''),
            source_file=data.get('source_file', ''),
            excluded=data.get('excluded', []),
            pending_review=data.get('pending_review', []),
        )
        
        for item in data.get('confirmed_names', []):
            result.confirmed_names.append(ConfirmedName.from_dict(item))
        
        return result
    
    @classmethod
    def exists(cls, path: str) -> bool:
        """检查配置文件是否存在"""
        return Path(path).exists()
