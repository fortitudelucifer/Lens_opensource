"""
匿名化工具模块 (Anonymization Utilities)

功能：
- 统一的姓名匿名化处理（ME/OTHER 替换）
- 支持引用消息中的说话人前缀匿名化
- 支持撤回消息的匿名化
- 使用 configs/anonymization.yaml 配置姓名映射

核心功能：
1. 说话人前缀匿名化：anonymize_speaker_prefix()
   - "UserB：是考在职吗" → "OTHER: 是考在职吗"
   - "UserA：并不是" → "ME: 并不是"

2. 文本匿名化：anonymize_text()
   - 替换文本中所有出现的真实姓名为 ME/OTHER

3. 撤回消息匿名化：anonymize_recalled_message()
   - '"UserB 南开大学" recalled a message' → 'OTHER recalled a message'

4. 统一入口：anonymize_message_text()
   - 根据消息类型自动选择合适的匿名化策略

配置文件：
- configs/anonymization.yaml:
  ```yaml
  me_names:
    - "UserA"
    - "usera"
  other_names:
    - UserB
    - 张三
  ```

使用示例：
    from scripts._common.anonymizer import (
        anonymize_speaker_prefix,
        anonymize_text,
        anonymize_message_text
    )
    
    # Example:
    #     >>> text = "OTHER：你好"
    #     >>> result = anonymize_speaker_prefix(text)
    #     # 输出: "OTHER: 你好"
    
    #     # 通用文本匿名化
    #     text = "OTHER recalled a message"
    #     result = anonymize_text(text)
    #     # 输出: "OTHER recalled a message"
    
    #     # 统一入口（自动选择策略）
    #     result = anonymize_message_text(text, msg_type=0)
    
    # 依赖：
    # - yaml: 配置文件解析
    # - re: 正则表达式
    
    # 作者：[Author]
    # 项目：wechatDHA - 微信聊天记录多模态处理流水线
    # 更新于：2026-02-02
"""
import re
import yaml
from pathlib import Path
from typing import List, Optional

# ========== Configuration Loading ==========
_config = None
_config_path = Path(__file__).resolve().parents[2] / "configs" / "anonymization.yaml"

def load_config(config_path: Optional[Path] = None) -> dict:
    """
    加载匿名化配置
    
    Args:
        config_path: 配置文件路径（可选，默认使用 configs/anonymization.yaml）
    
    Returns:
        dict: 配置字典，包含 me_names 和 other_names
    
    Raises:
        FileNotFoundError: 如果配置文件不存在
    
    Example:
        >>> config = load_config()
        >>> print(config['me_names'])
        ['UserA', 'usera']
    """
    global _config
    if _config is not None and config_path is None:
        return _config
    
    path = config_path or _config_path
    if not path.exists():
        raise FileNotFoundError(f"Anonymization config not found: {path}")
    
    with open(path, "r", encoding="utf-8") as f:
        _config = yaml.safe_load(f)
    
    return _config

def get_me_names() -> List[str]:
    """
    获取 ME 姓名列表
    
    Returns:
        List[str]: ME 的所有姓名变体（例如：['UserA', 'usera']）
    """
    config = load_config()
    return config.get("me_names", [])

def get_other_names() -> List[str]:
    """
    获取 OTHER 姓名列表
    
    Returns:
        List[str]: OTHER 的所有姓名（例如：['UserB', '张三']）
    """
    config = load_config()
    return config.get("other_names", [])

# ========== Anonymization Functions ==========

def anonymize_speaker_prefix(text: str) -> str:
    """
    匿名化引用消息中的说话人前缀
    
    处理引用消息中的"姓名："或"姓名:"前缀，替换为 ME/OTHER。
    
    Args:
        text: 输入文本（例如："UserB：是考在职吗"）
    
    Returns:
        str: 匿名化后的文本（例如："OTHER: 是考在职吗"）
    
    Example:
        >>> text = "UserB：是考在职吗"
        >>> print(anonymize_speaker_prefix(text))
        OTHER: 是考在职吗
        
        >>> text = "UserA：并不是"
        >>> print(anonymize_speaker_prefix(text))
        ME: 并不是
        
        >>> # 未知说话人默认为 OTHER（保护隐私）
        >>> text = "未知人：你好"
        >>> print(anonymize_speaker_prefix(text))
        OTHER: 你好
    """
    if not text:
        return text
    
    # Pattern: Any characters before Chinese/English colon at the start
    pattern = r'^([^：:]+)[：:]'
    match = re.match(pattern, text)
    
    if not match:
        return text
    
    speaker_name = match.group(1).strip()
    rest_of_text = text[match.end():].strip()
    
    # Check if speaker is ME
    me_names = get_me_names()
    for name in me_names:
        if speaker_name.lower() == name.lower():
            return f"ME: {rest_of_text}"
    
    # Check if speaker is OTHER
    other_names = get_other_names()
    for name in other_names:
        if speaker_name == name:
            return f"OTHER: {rest_of_text}"
    
    # Default to OTHER for unknown speakers (safer for privacy)
    return f"OTHER: {rest_of_text}"


def anonymize_text(text: str) -> str:
    """
    替换文本中所有出现的真实姓名为 ME/OTHER
    
    用于通用文本匿名化（例如："UserB recalled a message"）。
    优先替换 OTHER 姓名（通常更长、更具体），然后替换 ME 姓名。
    
    Args:
        text: 输入文本
    
    Returns:
        str: 匿名化后的文本
    
    Example:
        >>> text = "UserB recalled a message"
        >>> print(anonymize_text(text))
        OTHER recalled a message
        
        >>> text = "UserA 发送了一条消息"
        >>> print(anonymize_text(text))
        ME 发送了一条消息
        
        >>> # 多次出现
        >>> text = "UserB给UserB发消息"
        >>> print(anonymize_text(text))
        OTHER给OTHER发消息
    """
    if not text:
        return text
    
    result = text
    
    # Replace OTHER names first (usually longer, more specific)
    other_names = get_other_names()
    for name in sorted(other_names, key=len, reverse=True):
        # Use word boundary-like matching for Chinese
        # For names like "张三", replace directly
        result = result.replace(name, "OTHER")
    
    # Replace ME names
    me_names = get_me_names()
    for name in sorted(me_names, key=len, reverse=True):
        # Case-insensitive replacement for ME names
        pattern = re.compile(re.escape(name), re.IGNORECASE)
        result = pattern.sub("ME", result)
    
    return result


def anonymize_recalled_message(text: str) -> str:
    """
    专门处理撤回消息的匿名化
    
    处理 'XXX recalled a message' 模式，提取姓名并替换为 ME/OTHER。
    
    Args:
        text: 输入文本（例如：'"UserB 某大学" recalled a message'）
    
    Returns:
        str: 匿名化后的文本（例如：'OTHER recalled a message'）
    
    Example:
        >>> text = '"UserB 某大学 本科某高校" recalled a message'
        >>> print(anonymize_recalled_message(text))
        OTHER recalled a message
        
        >>> text = '"UserA" recalled a message'
        >>> print(anonymize_recalled_message(text))
        ME recalled a message
        
        >>> # 未知姓名默认为 OTHER
        >>> text = '"未知人" recalled a message'
        >>> print(anonymize_recalled_message(text))
        OTHER recalled a message
    """
    if not text:
        return text
    
    # Pattern: "name" recalled a message (with escaped quotes)
    pattern = r'\\?"([^"]+)\\?" recalled a message'
    
    def replace_name(match):
        name = match.group(1)
        # Check if name matches any OTHER names
        other_names = get_other_names()
        for other_name in other_names:
            if other_name in name:
                return 'OTHER recalled a message'
        # Check if name matches any ME names
        me_names = get_me_names()
        for me_name in me_names:
            if me_name.lower() in name.lower():
                return 'ME recalled a message'
        # Default to OTHER
        return 'OTHER recalled a message'
    
    return re.sub(pattern, replace_name, text)


# ========== High-level API ==========

def anonymize_message_text(text: str, modality: str = None, msg_type: int = None) -> str:
    """
    消息文本匿名化的统一入口
    
    根据消息类型/模态自动选择合适的匿名化策略：
    - msg_type=0（系统消息）：使用 anonymize_recalled_message()
    - 其他类型：使用 anonymize_text()
    
    Args:
        text: 输入文本
        modality: 模态类型（可选，暂未使用）
        msg_type: 消息类型（0=系统消息，1=文本消息，3=图片消息，等）
    
    Returns:
        str: 匿名化后的文本
    
    Example:
        >>> # 系统消息（撤回）
        >>> text = '"UserB" recalled a message'
        >>> print(anonymize_message_text(text, msg_type=0))
        OTHER recalled a message
        
        >>> # 普通文本消息
        >>> text = "UserB说：你好"
        >>> print(anonymize_message_text(text, msg_type=1))
        OTHER说：你好
    """
    if not text:
        return text
    
    # Type 0 is typically system messages like "recalled a message"
    if msg_type == 0:
        return anonymize_recalled_message(text)
    
    # For other types, do general text anonymization
    return anonymize_text(text)
