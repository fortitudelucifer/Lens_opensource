"""
文本规范化工具模块 (Text Normalization Utilities)

功能：
- 繁简转换（OpenCC）
- 标点符号规范化（去重、清洗）
- 可控纠错（专名修正、同音错修正）
- 保守式标点修复（避免误伤真实疑问句）

核心功能：
1. 繁简转换：to_simplified() - 使用 OpenCC 进行短语级转换
2. 标点处理：strip_punc(), dedup_punc() - 配合 ct-punc 使用
3. 专名修正：apply_patches() - 修正 ASR 常见错误（云顶之翼→云顶之弈）
4. 标点修复：fix_false_question() - 修正"什么的？"→"什么的。"

使用场景：
1. 语音转写后处理：
   - FunASR/Whisper 输出 → strip_punc() → ct-punc → dedup_punc()
   - 专名修正：apply_patches() 修正"云顶之翼"等常见错误
   
2. 文本清洗：
   - 繁体转简体：to_simplified()
   - 标点去重：dedup_punc()

3. Pipeline 辅助：
   - prepare_for_punc() - 一键准备文本用于 ct-punc

处理流程：
```
原始文本 → to_simplified() → strip_punc() → ct-punc → dedup_punc() → apply_patches() → fix_false_question()
```

依赖：
- opencc-python-reimplemented: 繁简转换（可选，未安装时跳过）
- re: 正则表达式

作者：[Author]
项目：wechatDHA - 微信聊天记录多模态处理流水线
更新于：2026-02-02
"""
import re
from typing import Dict, List, Tuple, Optional

# --------
# OpenCC (繁->简)
# --------
_cc = None
def to_simplified(text: str) -> str:
    """
    繁体中文转简体中文（使用 OpenCC）
    
    使用 OpenCC 的 't2s' 配置，支持短语级转换和地区习惯用语。
    如果 OpenCC 未安装或运行异常，返回原文（不阻塞主流程）。
    
    Args:
        text: 输入文本（可能包含繁体字）
    
    Returns:
        str: 简体中文文本
    
    Example:
        >>> text = "雲頂之弈"
        >>> print(to_simplified(text))
        云顶之弈
        
        >>> # 短语级转换
        >>> text = "軟體工程師"
        >>> print(to_simplified(text))
        软件工程师
    """
    global _cc
    t = (text or "").strip()
    if not t:
        return t
    try:
        if _cc is None:
            from opencc import OpenCC
            _cc = OpenCC("t2s")
        return _cc.convert(t)
    except Exception:
        # 若未安装 OpenCC 或运行异常，直接返回原文（不阻塞主流程）
        return t

# --------
# Punctuation normalize (给 ct-punc 前清洗 & 后去重)
# --------
PUNC_RE = re.compile(r'[，。？！；：、,.!?;:"“”‘’（）()【】\[\]{}<>《》…]+')

def strip_punc(text: str) -> str:
    """
    移除现有标点符号（用于 ct-punc 前清洗）
    
    避免 ct-punc 添加标点后出现双重标点（例如："你好，，"）。
    
    Args:
        text: 输入文本
    
    Returns:
        str: 移除标点后的文本
    
    Example:
        >>> text = "你好，世界！"
        >>> print(strip_punc(text))
        你好 世界
        
        >>> # 配合 ct-punc 使用
        >>> raw = "你好世界"
        >>> clean = strip_punc(raw)
        >>> # 然后送入 ct-punc 添加标点
    """
    t = (text or "").strip()
    t = PUNC_RE.sub(" ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t

def dedup_punc(text: str) -> str:
    """
    去重重复标点符号（用于 ct-punc 后清洗）
    
    修正 ct-punc 可能产生的重复标点（例如："你好，，世界"→"你好，世界"）。
    
    Args:
        text: 输入文本
    
    Returns:
        str: 去重后的文本
    
    Example:
        >>> text = "你好，，世界。。"
        >>> print(dedup_punc(text))
        你好，世界。
        
        >>> # 配合 ct-punc 使用
        >>> # ct-punc 输出 → dedup_punc() → 最终文本
    """
    t = (text or "").strip()
    t = re.sub(r'([，。？！；：、])\1+', r'\1', t)
    t = re.sub(r'([,.!?;:])\1+', r'\1', t)
    t = re.sub(r'[，,]{2,}', '，', t)
    t = re.sub(r'[。\.]{2,}', '。', t)
    return t

# --------
# Patch rules (可控纠错 + 记录日志)
# --------
DEFAULT_PATCH_MAP: Dict[str, str] = {
    # FunASR/Whisper 专名错误修正
    "云顶之翼": "云顶之弈",
    "金灿铲": "金铲铲",

    # 同音错修正（保留在这里，方便全局复用）
    "醒久了": "醒酒了",
    "很适很适": "很湿很湿",
}

def apply_patches(text: str, patch_map: Optional[Dict[str, str]] = None) -> Tuple[str, List[dict]]:
    """
    应用字符串替换补丁（可控纠错）
    
    用于修正 ASR 常见错误（专名、同音错等）。
    返回修正后的文本和修正日志。
    
    Args:
        text: 输入文本
        patch_map: 替换映射字典（默认使用 DEFAULT_PATCH_MAP）
    
    Returns:
        Tuple[str, List[dict]]: (修正后的文本, 修正日志)
        修正日志格式：[{"from": "...", "to": "...", "count": n}, ...]
    
    Example:
        >>> text = "我在玩云顶之翼"
        >>> fixed, logs = apply_patches(text)
        >>> print(fixed)
        我在玩云顶之弈
        >>> print(logs)
        [{"from": "云顶之翼", "to": "云顶之弈", "count": 1}]
        
        >>> # 自定义补丁
        >>> custom_map = {"错字": "正字"}
        >>> fixed, logs = apply_patches(text, patch_map=custom_map)
    """
    patch_map = patch_map or DEFAULT_PATCH_MAP
    t = text or ""
    logs: List[dict] = []
    for a, b in patch_map.items():
        if a in t:
            n = t.count(a)
            t = t.replace(a, b)
            logs.append({"from": a, "to": b, "count": n})
    return t, logs

# --------
# Conservative punctuation fix (专治“什么的。”被打成“什么的？”这类)
# --------
_SHENME_DE_PATTERNS = [
    re.compile(r"(什么的)\?$"),
    re.compile(r"(什么之类的)\?$"),
    re.compile(r"(之类的)\?$"),
]

def fix_false_question(text: str) -> Tuple[str, List[dict]]:
    """
    保守式标点修复（修正误判的疑问句）
    
    只处理句末的问号，且命中特定"非疑问语气"短语（例如："什么的？"→"什么的。"）。
    保持窄范围修复，避免误伤真实疑问句。
    
    Args:
        text: 输入文本
    
    Returns:
        Tuple[str, List[dict]]: (修正后的文本, 修正日志)
        修正日志格式：[{"rule": "...", "from": "...", "to": "..."}, ...]
    
    Example:
        >>> text = "买点水果什么的？"
        >>> fixed, logs = fix_false_question(text)
        >>> print(fixed)
        买点水果什么的。
        >>> print(logs)
        [{"rule": "fix_false_question_shenme_de", "from": "...", "to": "..."}]
        
        >>> # 真实疑问句不会被修改
        >>> text = "你要买什么？"
        >>> fixed, logs = fix_false_question(text)
        >>> print(fixed)
        你要买什么？
    """
    t = (text or "").strip()
    logs: List[dict] = []
    if not t:
        return t, logs

    # 只处理句末的问号，且命中特定“非疑问语气”短语
    if t.endswith("?") or t.endswith("？"):
        # 统一用中文问号判断
        t_norm = t[:-1] + "？"
        for pat in _SHENME_DE_PATTERNS:
            if pat.search(t_norm):
                fixed = t_norm[:-1] + "。"
                logs.append({"rule": "fix_false_question_shenme_de", "from": t, "to": fixed})
                return fixed, logs

    return t, logs

# --------
# Pipeline helper
# --------
def prepare_for_punc(raw_text: str, simplify: bool = True) -> Tuple[str, dict]:
    """
    准备文本用于 ct-punc（一键清洗）
    
    执行：繁简转换（可选）+ 标点清洗
    
    Args:
        raw_text: 原始文本
        simplify: 是否执行繁简转换（默认 True）
    
    Returns:
        Tuple[str, dict]: (清洗后的文本, 元数据)
        元数据包含：{"simplified": bool} 表示是否执行了繁简转换
    
    Example:
        >>> raw = "雲頂之弈，真好玩！"
        >>> clean, meta = prepare_for_punc(raw)
        >>> print(clean)
        云顶之弈 真好玩
        >>> print(meta)
        {"simplified": True}
        
        >>> # 跳过繁简转换
        >>> clean, meta = prepare_for_punc(raw, simplify=False)
    """
    t = raw_text or ""
    meta = {"simplified": False}
    if simplify:
        t2 = to_simplified(t)
        meta["simplified"] = (t2 != t)
        t = t2
    t = strip_punc(t)
    return t, meta
