# -*- coding: utf-8 -*-
"""
LLM PII 扫描器

使用小型 LLM (Qwen2.5-1.5B) 自动扫描聊天记录中的敏感信息
生成 anonymization.yaml 配置文件

特点：
1. 自动识别人名、地名、机构名
2. 智能生成替换映射（地名映射到附近城市）
3. 识别公众人物/历史人物并加入排除列表
4. 支持增量扫描

用法：
    python scripts/compression/llm_pii_scanner.py --scan
    python scripts/compression/llm_pii_scanner.py --generate-config
"""

import json
import argparse
import re
from pathlib import Path
from typing import Dict, List, Set, Tuple, Optional, Any
from dataclasses import dataclass, field
from collections import defaultdict
from tqdm import tqdm
import yaml
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer


# ============== 配置 ==============

# 地名映射表（真实地名 -> 替代地名）
# 映射到附近或同类型的城市
LOCATION_MAPPING_TEMPLATE = {
    # 一线城市互换
    "CITY_A": "CITY_B",
    "CITY_C": "CITY_D",
    "CITY_E": "CITY_F",
    "CITY_F": "CITY_E",
    # 西南地区
    "重庆": "成都",
    "成都": "重庆",
    "贵阳": "昆明",
    "昆明": "贵阳",
    # 华东地区示例
    "杭州": "宁波",
    "南京": "苏州",
    "苏州": "无锡",
    # 华中地区示例
    "武汉": "长沙",
    "长沙": "武汉",
    # 东北地区示例
    "沈阳": "大连",
    "大连": "沈阳",
    # 西北地区示例
    "西安": "兰州",
    # 省份映射示例（用户应替换为实际地名）
    "省份A": "省份B",
    "省份B": "省份A",
    "省份C": "省份D",
    "省份D": "省份C",
    "省份E": "省份F",
    "省份F": "省份E",
    "省份G": "省份H",
    "省份H": "省份G",
    "省份I": "省份J",
    "省份J": "省份I",
    "省份K": "省份L",
    "省份L": "省份K",
    # 国外地名示例（用户应替换为实际地名）
    "国家A": "国家B",
    "国家B": "国家A",
    "国家C": "国家D",
    "国家D": "国家C",
    "国家E": "国家F",
    "国家G": "国家H",
    "国家H": "国家G",
    "国家I": "国家J",
    "国家J": "国家I",
}

# 公众人物/历史人物（不应被替换）
PUBLIC_FIGURES = [
    # 历史人物
    "毛泽东", "周恩来", "邓小平", "江泽民", "胡锦涛", "习近平",
    "孙中山", "蒋介石", "李白", "杜甫", "苏轼", "王阳明",
    # 企业家
    "马云", "马化腾", "雷军", "任正非", "刘强东",
    # 其他公众人物
    "钟南山", "袁隆平",
]


@dataclass
class PIIEntity:
    """PII 实体"""
    text: str
    type: str  # person, location, organization, public_figure
    count: int = 1
    contexts: List[str] = field(default_factory=list)
    replacement: str = ""
    is_public_figure: bool = False


class LLMPIIScanner:
    """基于 LLM 的 PII 扫描器"""
    
    def __init__(self, model_path: str = "/data/models/Qwen2.5-1.5B-Instruct"):
        """
        初始化扫描器
        
        Args:
            model_path: LLM 模型路径
        """
        self.model_path = model_path
        self.model = None
        self.tokenizer = None
        self.entities: Dict[str, PIIEntity] = {}
        self.public_figures = set(PUBLIC_FIGURES)
        
        # 统计
        self.stats = {
            "total_scanned": 0,
            "llm_calls": 0,
            "persons_found": 0,
            "locations_found": 0,
            "organizations_found": 0,
            "public_figures_found": 0,
        }
    
    def load_model(self):
        """加载 LLM 模型"""
        if self.model is not None:
            return
        
        print(f"[INFO] 加载模型: {self.model_path}")
        
        self.tokenizer = AutoTokenizer.from_pretrained(
            self.model_path,
            trust_remote_code=True
        )
        
        self.model = AutoModelForCausalLM.from_pretrained(
            self.model_path,
            torch_dtype=torch.float16,
            device_map="auto",
            trust_remote_code=True
        )
        
        print("[INFO] 模型加载完成")
    
    def unload_model(self):
        """卸载模型释放显存"""
        if self.model is not None:
            del self.model
            del self.tokenizer
            self.model = None
            self.tokenizer = None
            
            import gc
            gc.collect()
            torch.cuda.empty_cache()
            print("[INFO] 模型已卸载")
    
    def _build_ner_prompt(self, text: str) -> str:
        """构建 NER 提示词"""
        return f"""请分析以下中文文本，识别其中的命名实体。

文本：
{text}

请按以下 JSON 格式输出识别结果：
{{
  "persons": ["人名1", "人名2"],
  "locations": ["地名1", "地名2"],
  "organizations": ["机构名1", "机构名2"],
  "public_figures": ["公众人物1"]
}}

规则：
1. persons: 普通人名（非公众人物）
2. locations: 地名（城市、省份、国家、景点等）
3. organizations: 机构名（公司、学校、政府机构等）
4. public_figures: 公众人物/历史人物（如毛泽东、马云等）

只输出 JSON，不要其他内容。"""
    
    def _call_llm(self, prompt: str) -> str:
        """调用 LLM"""
        self.stats["llm_calls"] += 1
        
        messages = [
            {"role": "system", "content": "你是一个专业的命名实体识别助手，擅长识别中文文本中的人名、地名、机构名。"},
            {"role": "user", "content": prompt}
        ]
        
        text = self.tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True
        )
        
        model_inputs = self.tokenizer([text], return_tensors="pt").to(self.model.device)
        
        with torch.no_grad():
            generated_ids = self.model.generate(
                **model_inputs,
                max_new_tokens=512,
                do_sample=False,
                temperature=0.1,
                pad_token_id=self.tokenizer.eos_token_id
            )
        
        generated_ids = [
            output_ids[len(input_ids):] 
            for input_ids, output_ids in zip(model_inputs.input_ids, generated_ids)
        ]
        
        response = self.tokenizer.batch_decode(generated_ids, skip_special_tokens=True)[0]
        return response
    
    def _parse_llm_response(self, response: str) -> Dict[str, List[str]]:
        """解析 LLM 响应"""
        try:
            # 尝试提取 JSON
            json_match = re.search(r'\{[^{}]*\}', response, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
        except json.JSONDecodeError:
            pass
        
        return {
            "persons": [],
            "locations": [],
            "organizations": [],
            "public_figures": []
        }
    
    def scan_text(self, text: str, use_llm: bool = True) -> Dict[str, List[str]]:
        """
        扫描文本中的 PII
        
        Args:
            text: 输入文本
            use_llm: 是否使用 LLM（否则使用规则）
        
        Returns:
            {type: [entities]}
        """
        if not text or len(text) < 5:
            return {}
        
        self.stats["total_scanned"] += 1
        
        if use_llm and self.model is not None:
            prompt = self._build_ner_prompt(text)
            response = self._call_llm(prompt)
            result = self._parse_llm_response(response)
        else:
            # 回退到规则匹配
            result = self._rule_based_scan(text)
        
        # 记录实体
        for entity_type, entities in result.items():
            for entity in entities:
                if not entity or len(entity) < 2:
                    continue
                
                is_public = entity_type == "public_figures" or entity in self.public_figures
                actual_type = "public_figure" if is_public else entity_type.rstrip('s')
                
                self._add_entity(entity, actual_type, text, is_public)
                
                # 更新统计
                if actual_type == "person":
                    self.stats["persons_found"] += 1
                elif actual_type == "location":
                    self.stats["locations_found"] += 1
                elif actual_type == "organization":
                    self.stats["organizations_found"] += 1
                elif actual_type == "public_figure":
                    self.stats["public_figures_found"] += 1
        
        return result
    
    def _rule_based_scan(self, text: str) -> Dict[str, List[str]]:
        """基于规则的扫描（LLM 不可用时的回退）"""
        result = {
            "persons": [],
            "locations": [],
            "organizations": [],
            "public_figures": []
        }
        
        # 检测公众人物
        for figure in self.public_figures:
            if figure in text:
                result["public_figures"].append(figure)
        
        # 检测地名（使用映射表中的地名）
        for loc in LOCATION_MAPPING_TEMPLATE.keys():
            if loc in text:
                result["locations"].append(loc)
        
        return result
    
    def _add_entity(self, text: str, entity_type: str, context: str, is_public: bool = False):
        """添加实体"""
        key = f"{entity_type}:{text}"
        
        if key in self.entities:
            self.entities[key].count += 1
            if len(self.entities[key].contexts) < 3:
                ctx = context[:100] if len(context) > 100 else context
                self.entities[key].contexts.append(ctx)
        else:
            ctx = context[:100] if len(context) > 100 else context
            self.entities[key] = PIIEntity(
                text=text,
                type=entity_type,
                count=1,
                contexts=[ctx],
                is_public_figure=is_public
            )
    
    def scan_jsonl(self, input_path: str, text_fields: List[str] = None,
                   sample_size: int = None, use_llm: bool = True):
        """
        扫描 JSONL 文件
        
        Args:
            input_path: 输入文件路径
            text_fields: 要扫描的文本字段
            sample_size: 采样大小（None 表示全量）
            use_llm: 是否使用 LLM
        """
        if text_fields is None:
            text_fields = [
                'text_raw', 'voice_to_text', 'image_summary', 'video_summary',
                'sticker_summary', 'link_quote_text', 'quote_text'
            ]
        
        # 加载模型
        if use_llm:
            self.load_model()
        
        # 读取文件
        with open(input_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        # 采样
        if sample_size and sample_size < len(lines):
            import random
            lines = random.sample(lines, sample_size)
        
        # 扫描
        for line in tqdm(lines, desc="LLM PII 扫描"):
            line = line.strip()
            if not line:
                continue
            
            try:
                msg = json.loads(line)
                
                # 合并所有文本字段
                texts = []
                for field in text_fields:
                    if field in msg and msg[field]:
                        texts.append(str(msg[field]))
                
                if texts:
                    combined_text = " ".join(texts)
                    # 限制长度避免 token 超限
                    if len(combined_text) > 500:
                        combined_text = combined_text[:500]
                    
                    self.scan_text(combined_text, use_llm=use_llm)
                    
            except json.JSONDecodeError:
                continue
        
        # 卸载模型
        if use_llm:
            self.unload_model()
    
    def generate_config(self, me_hint: str = None, other_hint: str = None) -> Dict[str, Any]:
        """
        生成匿名化配置
        
        Args:
            me_hint: ME 的名字提示（用于识别哪些是 ME）
            other_hint: OTHER 的名字提示
        
        Returns:
            配置字典
        """
        config = {
            "# 自动生成的匿名化配置": "",
            "# 请人工审核后使用": "",
            
            "me_names": [],
            "other_names": [],
            "me_alias": "ME",
            "other_alias": "OTHER",
            
            "exclude_patterns": [],
            
            "location_mapping": {},
            
            "l2_cloud": {
                "timestamp_shift": {
                    "enabled": True,
                    "shift_days": 100
                },
                "relative_time": {
                    "enabled": True
                }
            }
        }
        
        # 处理人名
        persons = []
        for key, entity in self.entities.items():
            if entity.type == "person":
                persons.append(entity)
        
        # 按出现次数排序
        persons.sort(key=lambda x: x.count, reverse=True)
        
        # 尝试识别 ME 和 OTHER
        if me_hint:
            for p in persons:
                if me_hint.lower() in p.text.lower():
                    config["me_names"].append(p.text)
        
        if other_hint:
            for p in persons:
                if other_hint.lower() in p.text.lower():
                    config["other_names"].append(p.text)
        
        # 如果没有提示，将高频人名列出供人工选择
        if not config["me_names"] and not config["other_names"]:
            config["# 请从以下人名中选择 ME 和 OTHER"] = ""
            config["detected_persons"] = [
                {"name": p.text, "count": p.count, "sample": p.contexts[0] if p.contexts else ""}
                for p in persons[:20]
            ]
        
        # 处理公众人物（加入排除列表）
        for key, entity in self.entities.items():
            if entity.type == "public_figure" or entity.is_public_figure:
                if entity.text not in config["exclude_patterns"]:
                    config["exclude_patterns"].append(entity.text)
        
        # 处理地名
        for key, entity in self.entities.items():
            if entity.type == "location":
                loc = entity.text
                if loc in LOCATION_MAPPING_TEMPLATE:
                    config["location_mapping"][loc] = LOCATION_MAPPING_TEMPLATE[loc]
                else:
                    # 未知地名，标记需要人工处理
                    config["location_mapping"][loc] = f"[需要映射: {loc}]"
        
        return config
    
    def export_config(self, output_path: str, me_hint: str = None, other_hint: str = None):
        """导出配置文件"""
        config = self.generate_config(me_hint, other_hint)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
        
        print(f"[INFO] 配置已保存到: {output_path}")
    
    def export_report(self, output_path: str):
        """导出扫描报告"""
        report = {
            "stats": self.stats,
            "entities": {}
        }
        
        # 按类型分组
        by_type = defaultdict(list)
        for key, entity in self.entities.items():
            by_type[entity.type].append({
                "text": entity.text,
                "count": entity.count,
                "contexts": entity.contexts,
                "is_public_figure": entity.is_public_figure
            })
        
        # 按出现次数排序
        for entity_type in by_type:
            by_type[entity_type].sort(key=lambda x: x["count"], reverse=True)
        
        report["entities"] = dict(by_type)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(report, ensure_ascii=False, indent=2, fp=f)
        
        print(f"[INFO] 报告已保存到: {output_path}")
    
    def get_stats(self) -> Dict:
        """获取统计信息"""
        return self.stats.copy()


def main():
    parser = argparse.ArgumentParser(description='LLM PII 扫描器')
    parser.add_argument('--scan', action='store_true', help='扫描时间轴文件')
    parser.add_argument('--input', '-i', type=str,
                        default='timeline_out/enriched_full_processed.jsonl',
                        help='输入文件路径')
    parser.add_argument('--sample', '-s', type=int, default=500,
                        help='采样大小（默认 500，设为 0 表示全量）')
    parser.add_argument('--no-llm', action='store_true',
                        help='不使用 LLM（仅规则匹配）')
    parser.add_argument('--me-hint', type=str, help='ME 的名字提示')
    parser.add_argument('--other-hint', type=str, help='OTHER 的名字提示')
    parser.add_argument('--report', '-r', type=str,
                        default='artifacts/llm_pii_report.json',
                        help='报告输出路径')
    parser.add_argument('--config', '-c', type=str,
                        default='artifacts/generated_anonymization.yaml',
                        help='配置输出路径')
    parser.add_argument('--model', '-m', type=str,
                        default='/data/models/Qwen2.5-1.5B-Instruct',
                        help='LLM 模型路径')
    
    args = parser.parse_args()
    
    scanner = LLMPIIScanner(model_path=args.model)
    
    if args.scan:
        print(f"[INFO] 扫描文件: {args.input}")
        sample_size = args.sample if args.sample > 0 else None
        
        scanner.scan_jsonl(
            args.input,
            sample_size=sample_size,
            use_llm=not args.no_llm
        )
        
        print("\n=== 扫描统计 ===")
        stats = scanner.get_stats()
        print(f"扫描消息数: {stats['total_scanned']}")
        print(f"LLM 调用次数: {stats['llm_calls']}")
        print(f"检测到人名: {stats['persons_found']}")
        print(f"检测到地名: {stats['locations_found']}")
        print(f"检测到机构: {stats['organizations_found']}")
        print(f"检测到公众人物: {stats['public_figures_found']}")
        
        # 导出报告和配置
        scanner.export_report(args.report)
        scanner.export_config(args.config, args.me_hint, args.other_hint)
        
        print("\n[INFO] 请审核生成的配置文件，确认后复制到 configs/anonymization.yaml")


if __name__ == '__main__':
    main()
