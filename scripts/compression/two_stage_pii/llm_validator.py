# -*- coding: utf-8 -*-
"""
LLM 验证器

使用 Qwen2.5-7B-Instruct-AWQ 批量验证候选词是否为真实人名。
"""

import gc
import json
import re
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple
from tqdm import tqdm

from .models import CandidateList, CandidateWord, ValidationResult


class LLMValidator:
    """使用 LLM 批量验证候选词"""
    
    # 分类 Prompt 模板
    CLASSIFICATION_PROMPT = """你是一个中文人名识别专家。请判断以下词汇是否为中国人的真实姓名。

对于每个词汇，请分类为以下类别之一：
- real_name: 真实的中国人名（如"张三"、"王小明"、"刘德华"、"李四"、"王五"）
- pronoun: 代词或称谓（如"朋友"、"同学"、"老师"、"阿姨"、"哥哥"）
- animal: 动物名或宠物名（如"猫咪"、"小狗"、"小白兔"）
- common: 常见词汇、地名、公司名等非人名（如"北京"、"公司"、"时间"、"乌当"、"花溪"）
- uncertain: 无法确定，需要人工审核

待分类词汇列表：
{candidates}

请以 JSON 格式返回分类结果，格式如下：
```json
{{
  "real_name": ["词1", "词2"],
  "pronoun": ["词3"],
  "animal": ["词4"],
  "common": ["词5", "词6"],
  "uncertain": ["词7"]
}}
```

重要规则：
1. 每个词汇必须且只能出现在一个类别中
2. 只有独立的人名才归类为 real_name，例如：
   - "李四" → real_name（独立人名）
   - "王五" → real_name（独立人名）
   - "小五" → real_name（昵称形式的人名）
3. 以下情况不是人名，应归类为 common：
   - 以"和"开头的词组（如"和老师"、"和李四"、"和他们"）→ common
   - 以"有"开头的词组（如"有老师"）→ common
   - 地名（如"北京"、"上海"、"朝阳"、"海淀"、"洪崖洞"、"李子坝"）→ common
   - 公司名、品牌名（如"金吉列"、"华樱"）→ common
   - 包含动词的词组（如"能提拔"、"方满意"）→ common
4. 称谓词归类为 pronoun：
   - "老师"、"同学"、"阿姨"、"哥哥"、"姐姐"、"老公"、"老婆" → pronoun
5. 动物名归类为 animal：
   - "小白兔"、"猫咪"、"小狗" → animal

请直接返回 JSON，不要有其他内容。"""

    def __init__(self, 
                 model_path: str = "/data/models/Qwen2.5-7B-Instruct-AWQ",
                 device: str = "cuda"):
        """
        初始化验证器
        
        Args:
            model_path: LLM 模型路径（AWQ 量化）
            device: 设备（cuda/cpu）
        """
        self.model_path = model_path
        self.device = device
        self.model = None
        self.tokenizer = None
        self._loaded = False
    
    def load_model(self):
        """加载模型到 GPU"""
        if self._loaded:
            return
        
        print(f"[INFO] 加载模型: {self.model_path}")
        
        try:
            from transformers import AutoModelForCausalLM, AutoTokenizer
            from pathlib import Path
            
            # 检查是否为本地路径
            is_local = Path(self.model_path).exists()
            
            self.tokenizer = AutoTokenizer.from_pretrained(
                self.model_path,
                trust_remote_code=True,
                local_files_only=is_local
            )
            
            self.model = AutoModelForCausalLM.from_pretrained(
                self.model_path,
                device_map="auto",
                trust_remote_code=True,
                local_files_only=is_local
            )
            
            self._loaded = True
            print(f"[INFO] 模型加载完成")
            
        except Exception as e:
            print(f"[ERROR] 模型加载失败: {e}")
            raise
    
    def unload_model(self):
        """卸载模型释放显存"""
        if not self._loaded:
            return
        
        print(f"[INFO] 卸载模型...")
        
        if self.model is not None:
            del self.model
            self.model = None
        
        if self.tokenizer is not None:
            del self.tokenizer
            self.tokenizer = None
        
        self._loaded = False
        
        # 清理显存
        gc.collect()
        try:
            import torch
            torch.cuda.empty_cache()
        except:
            pass
        
        print(f"[INFO] 模型已卸载")
    
    def _build_prompt(self, candidates: List[str]) -> str:
        """构建分类 Prompt"""
        candidates_str = "\n".join(f"- {c}" for c in candidates)
        return self.CLASSIFICATION_PROMPT.format(candidates=candidates_str)
    
    def _parse_response(self, response: str, candidates: List[str]) -> dict:
        """
        解析 LLM 响应
        
        Args:
            response: LLM 返回的文本
            candidates: 原始候选词列表
        
        Returns:
            分类结果字典
        """
        result = {
            'real_name': [],
            'pronoun': [],
            'animal': [],
            'common': [],
            'uncertain': [],
        }
        
        try:
            # 尝试提取 JSON
            json_match = re.search(r'\{[\s\S]*\}', response)
            if json_match:
                parsed = json.loads(json_match.group())
                
                # 映射字段名
                field_mapping = {
                    'real_name': 'real_name',
                    'real_names': 'real_name',
                    'pronoun': 'pronoun',
                    'pronouns': 'pronoun',
                    'animal': 'animal',
                    'animals': 'animal',
                    'common': 'common',
                    'common_words': 'common',
                    'uncertain': 'uncertain',
                }
                
                for key, target in field_mapping.items():
                    if key in parsed and isinstance(parsed[key], list):
                        result[target].extend(parsed[key])
                
                # 检查是否有遗漏的候选词
                classified = set()
                for category in result.values():
                    classified.update(category)
                
                missing = set(candidates) - classified
                if missing:
                    result['uncertain'].extend(list(missing))
                
        except json.JSONDecodeError as e:
            print(f"[WARN] JSON 解析失败: {e}")
            # 解析失败，所有候选词标记为 uncertain
            result['uncertain'] = candidates
        
        return result
    
    def _call_llm(self, prompt: str, max_new_tokens: int = 1024) -> str:
        """
        调用 LLM 生成响应
        
        Args:
            prompt: 输入 Prompt
            max_new_tokens: 最大生成 token 数
        
        Returns:
            生成的文本
        """
        if not self._loaded:
            self.load_model()
        
        messages = [
            {"role": "system", "content": "你是一个专业的中文人名识别助手。"},
            {"role": "user", "content": prompt}
        ]
        
        text = self.tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True
        )
        
        model_inputs = self.tokenizer([text], return_tensors="pt").to(self.device)
        
        import torch
        with torch.no_grad():
            generated_ids = self.model.generate(
                **model_inputs,
                max_new_tokens=max_new_tokens,
                do_sample=False,
                pad_token_id=self.tokenizer.eos_token_id,
            )
        
        generated_ids = [
            output_ids[len(input_ids):] 
            for input_ids, output_ids in zip(model_inputs.input_ids, generated_ids)
        ]
        
        response = self.tokenizer.batch_decode(generated_ids, skip_special_tokens=True)[0]
        return response
    
    def validate_batch(self, 
                       candidates: List[CandidateWord], 
                       batch_size: int = 50,
                       show_progress: bool = True) -> ValidationResult:
        """
        批量验证候选词
        
        Args:
            candidates: 候选词列表
            batch_size: 每批处理数量
            show_progress: 是否显示进度条
        
        Returns:
            ValidationResult: 验证结果
        """
        result = ValidationResult(
            validation_time=datetime.now().isoformat(),
            total_candidates=len(candidates),
        )
        
        if not candidates:
            return result
        
        # 分批处理
        batches = self._split_batches([c.text for c in candidates], batch_size)
        
        iterator = tqdm(batches, desc="LLM 验证") if show_progress else batches
        
        for batch in iterator:
            try:
                prompt = self._build_prompt(batch)
                response = self._call_llm(prompt)
                parsed = self._parse_response(response, batch)
                
                result.real_names.extend(parsed['real_name'])
                result.pronouns.extend(parsed['pronoun'])
                result.animal_names.extend(parsed['animal'])
                result.common_words.extend(parsed['common'])
                result.uncertain.extend(parsed['uncertain'])
                result.llm_calls += 1
                
            except Exception as e:
                print(f"[ERROR] 批次处理失败: {e}")
                # 失败的批次标记为 uncertain
                result.uncertain.extend(batch)
                result.llm_calls += 1
        
        return result
    
    def _split_batches(self, items: List[str], batch_size: int) -> List[List[str]]:
        """将列表分割为批次"""
        batches = []
        for i in range(0, len(items), batch_size):
            batches.append(items[i:i + batch_size])
        return batches
    
    def validate_single(self, candidate: str) -> str:
        """
        验证单个候选词（用于测试）
        
        Args:
            candidate: 候选词
        
        Returns:
            分类结果（real_name/pronoun/animal/common/uncertain）
        """
        prompt = self._build_prompt([candidate])
        response = self._call_llm(prompt)
        parsed = self._parse_response(response, [candidate])
        
        for category, words in parsed.items():
            if candidate in words:
                return category
        
        return 'uncertain'


def split_into_batches(items: List[str], batch_size: int) -> List[List[str]]:
    """
    将列表分割为批次（独立函数，用于测试）
    
    Args:
        items: 输入列表
        batch_size: 批次大小
    
    Returns:
        批次列表
    """
    batches = []
    for i in range(0, len(items), batch_size):
        batches.append(items[i:i + batch_size])
    return batches


def parse_llm_response(response: str, candidates: List[str]) -> dict:
    """
    解析 LLM 响应（独立函数，用于测试）
    
    Args:
        response: LLM 返回的文本
        candidates: 原始候选词列表
    
    Returns:
        分类结果字典
    """
    result = {
        'real_name': [],
        'pronoun': [],
        'animal': [],
        'common': [],
        'uncertain': [],
    }
    
    try:
        # 尝试提取 JSON
        json_match = re.search(r'\{[\s\S]*\}', response)
        if not json_match:
            # 没有找到 JSON，所有候选词标记为 uncertain
            result['uncertain'] = list(candidates)
            return result
        
        parsed = json.loads(json_match.group())
        
        # 映射字段名
        field_mapping = {
            'real_name': 'real_name',
            'real_names': 'real_name',
            'pronoun': 'pronoun',
            'pronouns': 'pronoun',
            'animal': 'animal',
            'animals': 'animal',
            'common': 'common',
            'common_words': 'common',
            'uncertain': 'uncertain',
        }
        
        for key, target in field_mapping.items():
            if key in parsed and isinstance(parsed[key], list):
                result[target].extend(parsed[key])
        
        # 检查是否有遗漏的候选词
        classified = set()
        for category in result.values():
            classified.update(category)
        
        missing = set(candidates) - classified
        if missing:
            result['uncertain'].extend(list(missing))
            
    except json.JSONDecodeError:
        # 解析失败，所有候选词标记为 uncertain
        result['uncertain'] = list(candidates)
    
    return result
