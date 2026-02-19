"""
训练数据格式化器模块

功能：
- 将对话文本和 LLM 分析结果转换为 SFT 训练格式（JSONL messages 或 Alpaca 格式）
- 生成供人工审核的 Markdown 文件（分批次，每批 15 个样本）
- 解析审核后的 Markdown 文件，提取审核状态和修改后的分析结果
- 导出最终训练数据（支持仅导出已审核样本）
- 三种 Agent 类型的专用系统提示词（neutral/supportive/psychoanalytic）

处理流程：
1. format_sample(): 将单个对话+分析组装为 SFT 训练样本
   - 选择对应 Agent 类型的系统提示词
   - 调用 format_analysis_text() 将分析字典格式化为结构化文本
   - 输出 messages 数组（system + user + assistant）
2. generate_review_markdown(): 批量生成审核 Markdown 文件
   - 按 samples_per_file 分批
   - 每个样本包含对话原文、分析结果和审核复选框
3. parse_reviewed_markdown(): 解析审核后的 Markdown
   - 提取审核状态（已审核/未审核）
   - 解析可能被人工修改的分析文本
4. export_training_data(): 导出最终 JSONL 训练数据

输入：
- 对话文本（conversation_text）
- 分析结果字典（analysis_features）
- Agent 类型（neutral/supportive/psychoanalytic）

输出：
- JSONL 训练数据文件（messages 格式或 Alpaca 格式）
- Markdown 审核文件（供人工审核）

依赖：
- tqdm: 进度条显示

使用示例：
    from scripts.advisor.formatter import TrainingFormatter
    
    formatter = TrainingFormatter({'samples_per_file': 15})
    
    # 生成审核文件
    files = formatter.generate_review_markdown(samples, 'review_dir/', 'neutral')
    
    # 解析审核结果
    reviewed = formatter.parse_reviewed_markdown('review_dir/reviewed_batch_001.md')
    
    # 导出训练数据
    formatter.export_training_data(reviewed, 'training.jsonl', only_reviewed=True)

注意事项：
- format_analysis_text 对所有字段（含扩展字段）始终输出，缺失时使用默认值
- 精神分析类型（psychoanalytic）直接使用 raw_response，不做结构化格式化
- 审核 Markdown 中的复选框 [x] 表示已审核，[ ] 表示未审核
- export_training_data 的 only_reviewed=True 可过滤未审核样本

作者：forcifer
更新于：2026-02-15
"""

import json
import re
from pathlib import Path
from typing import Optional
from tqdm import tqdm


# 系统提示词
SYSTEM_PROMPTS = {
    'neutral': """你是一位专业的关系顾问，擅长分析情侣/伴侣之间的对话，提供客观、专业的评价和建议。
你的分析应该保持中立，不偏袒任何一方，对双方的问题都要指出。""",

    'supportive': """你是一位支持性的关系顾问，你的首要任务是理解和支持用户（ME）的感受。
你会首先验证用户的情感体验，从用户的角度理解问题，同时保持基本的客观性。""",

    'psychoanalytic': """你是一位精神分析取向的关系顾问，精通客体关系理论和拉康派精神分析。
你会分析双方的依附风格、防御机制、欲望结构和无意识动态，提供深度心理分析。""",
}


class TrainingFormatter:
    """训练数据格式化器
    
    将对话和分析结果转换为 SFT 训练格式，支持人工审核流程。
    
    Attributes:
        format (str): 输出格式，'jsonl'（messages 数组）或 'alpaca'（instruction/input/output）
        samples_per_file (int): 每个审核 Markdown 文件包含的样本数
        stats (dict): 格式化统计（total/formatted/reviewed）
    
    Example:
        >>> formatter = TrainingFormatter({'format': 'jsonl', 'samples_per_file': 15})
        >>> sample = formatter.format_sample("对话内容", {"relationship_status": "冲突期"})
    """
    
    def __init__(self, config: Optional[dict] = None):
        """
        初始化格式化器
        
        Args:
            config: 配置字典，包含：
                - format: 输出格式 (jsonl/alpaca)
                - samples_per_file: 每个审核文件的样本数
        """
        config = config or {}
        self.format = config.get('format', 'jsonl')
        self.samples_per_file = config.get('samples_per_file', 15)
        
        self.stats = {
            'total': 0,
            'formatted': 0,
            'reviewed': 0,
        }
    
    def format_analysis_text(self, analysis: dict, agent_type: str = 'neutral') -> str:
        """
        将分析结果格式化为文本
        
        Args:
            analysis: 分析结果字典
            agent_type: Agent 类型
        
        Returns:
            格式化的分析文本
        """
        if agent_type == 'psychoanalytic':
            # 精神分析格式较为自由
            return analysis.get('raw_response', '')
        
        lines = []
        
        # ── 核心字段 (必须始终输出，缺失时用默认值) ──────────────
        lines.append(f"【关系状态】{analysis.get('relationship_status', '未知')}")
        lines.append(f"【沟通质量】{analysis.get('communication_quality', '未知')}")
        lines.append(f"【情绪平衡】{analysis.get('emotional_balance', '未知')}")
        
        # 情感验证（支持性 Agent 专用，neutral 不输出）
        if 'emotional_validation' in analysis:
            lines.append(f"【情感验证】{analysis['emotional_validation']}")
        
        # 关键问题
        issues = analysis.get('key_issues') or []
        lines.append("【问题】")
        if issues:
            for i, issue in enumerate(issues, 1):
                lines.append(f"{i}. {issue}")
        else:
            lines.append("1. 无明显问题")
        
        # 建议
        advices = analysis.get('advice') or []
        lines.append("【建议】")
        if advices:
            for i, adv in enumerate(advices, 1):
                lines.append(f"{i}. {adv}")
        else:
            lines.append("1. 保持现有良好沟通")
        
        # 批评
        crit = analysis.get('criticism', {})
        lines.append("【批评】")
        if isinstance(crit, dict):
            lines.append(f"- ME: {crit.get('ME', '无') or '无'}")
            lines.append(f"- OTHER: {crit.get('OTHER', '无') or '无'}")
        elif crit:
            lines.append(str(crit))
        else:
            lines.append("- ME: 无\n- OTHER: 无")
        
        # ── 扩展字段 (始终输出，None 时用默认值) ──────────────
        # 时间模式分析
        time_patterns = analysis.get('time_patterns') or []
        lines.append("【时间模式】")
        if time_patterns:
            for i, tp in enumerate(time_patterns, 1):
                lines.append(f"{i}. {tp}")
        else:
            lines.append("1. 无显著时间模式")
        
        # 冲突根源分析
        root_causes = analysis.get('conflict_root_causes') or []
        lines.append("【冲突根源】")
        if root_causes:
            for i, cr in enumerate(root_causes, 1):
                lines.append(f"{i}. {cr}")
        else:
            lines.append("1. 无明显冲突根源")
        
        # 多模态信号
        lines.append(f"【多模态信号】{analysis.get('multimodal_signals') or '无显著多模态信号'}")
        
        # 修复尝试
        lines.append(f"【修复尝试】{analysis.get('repair_attempts') or '无明显修复尝试'}")
        
        # 人格动态
        lines.append(f"【人格动态】{analysis.get('personality_dynamics') or '无显著人格动态特征'}")
        
        # 风险等级
        lines.append(f"【风险等级】{analysis.get('risk_level') or '无'}")
        
        # 整体评价
        lines.append(f"【评价】{analysis.get('overall_assessment', '无整体评价')}")
        
        return '\n'.join(lines)
    
    def format_sample(self, conversation: str, analysis: dict, agent_type: str = 'neutral') -> dict:
        """
        格式化单个训练样本
        
        Args:
            conversation: 对话文本
            analysis: 分析结果
            agent_type: Agent 类型
        
        Returns:
            格式化的训练样本
        """
        system_prompt = SYSTEM_PROMPTS.get(agent_type, SYSTEM_PROMPTS['neutral'])
        analysis_text = self.format_analysis_text(analysis, agent_type)
        
        if self.format == 'alpaca':
            return {
                'instruction': system_prompt + '\n\n请分析以下对话，提供关系状态、问题、建议、批评和整体评价。',
                'input': conversation,
                'output': analysis_text,
            }
        else:
            # JSONL 格式（messages 数组）
            return {
                'messages': [
                    {'role': 'system', 'content': system_prompt},
                    {'role': 'user', 'content': f'请分析以下对话：\n\n{conversation}'},
                    {'role': 'assistant', 'content': analysis_text},
                ]
            }
    
    def generate_review_markdown(self, samples: list[dict], output_dir: str, agent_type: str = 'neutral') -> list[str]:
        """
        生成供人工审核的 Markdown 文件
        
        Args:
            samples: 样本列表
            output_dir: 输出目录
            agent_type: Agent 类型
        
        Returns:
            生成的文件路径列表
        """
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        
        files = []
        batch_num = 1
        
        for i in range(0, len(samples), self.samples_per_file):
            batch = samples[i:i + self.samples_per_file]
            filename = f'review_batch_{batch_num:03d}_{agent_type}.md'
            filepath = output_path / filename
            
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(f'# 关系分析审核 - 批次 {batch_num} ({agent_type})\n\n')
                f.write('> 请审核以下分析结果，如有需要可直接修改。\n')
                f.write('> 审核完成后，将文件重命名为 `reviewed_batch_XXX.md`\n\n')
                f.write('---\n\n')
                
                for j, sample in enumerate(batch):
                    chunk_id = sample.get('chunk_id', f'sample_{i+j+1}')
                    conversation = sample.get('conversation', '')
                    analysis = sample.get('analysis_features', sample.get('analysis', {}))
                    
                    f.write(f'## 样本 {j+1}: {chunk_id}\n\n')
                    f.write('### 对话\n\n')
                    f.write('```\n')
                    f.write(conversation)
                    f.write('\n```\n\n')
                    
                    f.write('### 分析结果\n\n')
                    analysis_text = self.format_analysis_text(analysis, agent_type)
                    f.write(analysis_text)
                    f.write('\n\n')
                    
                    f.write('### 审核状态\n\n')
                    f.write('- [ ] 已审核\n')
                    f.write('- 审核备注：\n\n')
                    
                    f.write('---\n\n')
            
            files.append(str(filepath))
            batch_num += 1
        
        print(f"已生成 {len(files)} 个审核文件到 {output_dir}")
        return files
    
    def parse_reviewed_markdown(self, markdown_path: str) -> list[dict]:
        """
        解析审核后的 Markdown 文件
        
        Args:
            markdown_path: Markdown 文件路径
        
        Returns:
            解析后的样本列表
        """
        with open(markdown_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        samples = []
        
        # 按样本分割
        sample_pattern = r'## 样本 \d+: ([\w_]+)\n\n### 对话\n\n```\n(.*?)\n```\n\n### 分析结果\n\n(.*?)\n\n### 审核状态'
        matches = re.findall(sample_pattern, content, re.DOTALL)
        
        for chunk_id, conversation, analysis_text in matches:
            # 检查是否已审核
            reviewed_pattern = rf'## 样本 \d+: {chunk_id}.*?### 审核状态\n\n- \[(x|X)\] 已审核'
            is_reviewed = bool(re.search(reviewed_pattern, content, re.DOTALL))
            
            # 解析分析文本
            analysis = self._parse_analysis_text(analysis_text)
            
            samples.append({
                'chunk_id': chunk_id,
                'conversation': conversation.strip(),
                'analysis': analysis,
                'reviewed': is_reviewed,
            })
        
        self.stats['reviewed'] = sum(1 for s in samples if s['reviewed'])
        return samples
    
    def _parse_analysis_text(self, text: str) -> dict:
        """解析分析文本为字典
        
        使用正则表达式从格式化的分析文本中提取各字段值。
        支持单值字段（【关系状态】等）和列表字段（【问题】等）。
        
        Args:
            text (str): 格式化的分析文本
        
        Returns:
            dict: 解析后的分析字典，包含 raw_response 和各结构化字段
        """
        analysis = {'raw_response': text}
        
        patterns = {
            'relationship_status': r'【关系状态】(.+?)(?:\n|$)',
            'communication_quality': r'【沟通质量】(.+?)(?:\n|$)',
            'emotional_balance': r'【情绪平衡】(.+?)(?:\n|$)',
            'emotional_validation': r'【情感验证】(.+?)(?:\n|$)',
            'multimodal_signals': r'【多模态信号】(.+?)(?:\n|$)',
            'repair_attempts': r'【修复尝试】(.+?)(?:\n|$)',
            'personality_dynamics': r'【人格动态】(.+?)(?:\n|$)',
            'overall_assessment': r'【评价】(.+?)(?:\n|$)',
        }
        
        for key, pattern in patterns.items():
            match = re.search(pattern, text)
            if match:
                analysis[key] = match.group(1).strip()
        
        # 解析列表
        analysis['key_issues'] = self._extract_list_from_text(text, '【问题】')
        analysis['advice'] = self._extract_list_from_text(text, '【建议】')
        analysis['criticism'] = self._extract_criticism_from_text(text)
        analysis['time_patterns'] = self._extract_list_from_text(text, '【时间模式】')
        analysis['conflict_root_causes'] = self._extract_list_from_text(text, '【冲突根源】')
        
        return analysis
    
    def _extract_list_from_text(self, text: str, section_marker: str) -> list:
        """从文本中提取编号列表
        
        匹配 section_marker 后的 "1. xxx\\n2. xxx" 格式列表。
        
        Args:
            text (str): 完整分析文本
            section_marker (str): 段落标记（如 '【问题】'）
        
        Returns:
            list: 提取的列表项
        """
        items = []
        pattern = rf'{re.escape(section_marker)}\n((?:\d+\.\s*.+?\n?)+)'
        match = re.search(pattern, text)
        if match:
            list_text = match.group(1)
            for line in list_text.split('\n'):
                line = line.strip()
                if line and re.match(r'\d+\.', line):
                    item = re.sub(r'^\d+\.\s*', '', line)
                    if item:
                        items.append(item)
        return items
    
    def _extract_criticism_from_text(self, text: str) -> dict:
        """从文本中提取双方批评
        
        匹配 "- ME: xxx" 和 "- OTHER: xxx" 格式的批评文本。
        
        Args:
            text (str): 完整分析文本
        
        Returns:
            dict: {'ME': str, 'OTHER': str} 批评字典
        """
        criticism = {'ME': '', 'OTHER': ''}
        
        me_match = re.search(r'-\s*ME[：:]\s*(.+?)(?:\n|$)', text)
        if me_match:
            criticism['ME'] = me_match.group(1).strip()
        
        other_match = re.search(r'-\s*OTHER[：:]\s*(.+?)(?:\n|$)', text)
        if other_match:
            criticism['OTHER'] = other_match.group(1).strip()
        
        return criticism
    
    def export_training_data(self, samples: list[dict], output_path: str, agent_type: str = 'neutral', only_reviewed: bool = False) -> None:
        """
        导出训练数据
        
        Args:
            samples: 样本列表
            output_path: 输出文件路径
            agent_type: Agent 类型
            only_reviewed: 是否只导出已审核的样本
        """
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        
        exported = 0
        with open(path, 'w', encoding='utf-8') as f:
            for sample in tqdm(samples, desc="导出训练数据"):
                if only_reviewed and not sample.get('reviewed', False):
                    continue
                
                conversation = sample.get('conversation', '')
                analysis = sample.get('analysis_features', sample.get('analysis', {}))
                
                formatted = self.format_sample(conversation, analysis, agent_type)
                f.write(json.dumps(formatted, ensure_ascii=False) + '\n')
                exported += 1
        
        self.stats['formatted'] = exported
        print(f"已导出 {exported} 个训练样本到 {output_path}")
    
    def get_stats(self) -> dict:
        """获取格式化统计信息
        
        Returns:
            dict: 统计字典，包含：
                - total (int): 总样本数
                - formatted (int): 已格式化导出数
                - reviewed (int): 已审核数
        """
        return self.stats.copy()
