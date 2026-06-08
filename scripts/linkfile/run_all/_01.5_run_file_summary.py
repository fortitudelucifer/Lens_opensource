#!/usr/bin/env python3
"""
Linkfile 文件摘要生成步骤

功能：
- 为 PDF 文件生成内容摘要（使用 Qwen2.5-VL-7B）
- 为 Word 文件生成内容摘要（使用 python-docx + Qwen2.5-VL-7B）
- 为 TXT 文件生成内容摘要（直接读取文本）
- 为 ZIP 文件生成文件列表摘要
- 更新 linkfile_extract_v1.jsonl，添加 file_summary 字段
- 支持 --force 参数强制重新生成摘要

处理流程：
1. 加载 linkfile_extract_v1.jsonl 中的 file 类型记录
2. 对每个文件：
   a. PDF: 使用 pdf2image 转为图片 → Qwen2.5-VL-7B 分析
   b. Word (.docx): 使用 python-docx 提取文本 → Qwen2.5-VL-7B 总结
   c. TXT: 直接读取文本内容（前 2000 字符）
   d. ZIP: 提取文件列表（不解压分析内容）
3. 生成摘要并更新记录
4. 保存更新后的 linkfile_extract_v1.jsonl

PDF 分析策略：
- 使用 pdf2image 将 PDF 转为图片（最多 3 页）
- 分析前 2 页（通常包含最重要的信息）
- 结合文件名推断文档类型和主题
- 提取关键信息（日期、人名、机构、金额等）
- 生成 100-200 字的简洁摘要

Word 分析策略：
- 使用 python-docx 提取文档文本
- 提取前 2000 字符作为上下文
- 使用 Qwen2.5-VL-7B 生成摘要
- 保留文档结构信息（标题、段落数等）

TXT 分析策略：
- 直接读取文本内容
- 提取前 2000 字符
- 不使用 LLM，直接作为摘要
- 适合简单文本文件

ZIP 分析策略：
- 仅提取文件列表（不解压分析内容）
- 尝试修复编码问题（Windows 中文 ZIP 常见问题）
- 最多显示 20 个文件
- 根据文件名推断内容

模型配置：
- 模型：Qwen2.5-VL-7B (4-bit)
- 显存占用：~4.5GB
- OCR 能力强，中文支持优秀
- 适合文档分析和内容理解

支持的文件类型：
- PDF: 使用 VLM 分析内容
- Word (.docx): 使用 python-docx + VLM 分析
- TXT: 直接读取文本
- ZIP: 仅提取文件列表

输入：
- artifacts/before_merge/linkfile/linkfile_extract_v1.jsonl: 提取结果
- raw/file/*.pdf, *.docx, *.txt, *.zip: 文件

输出：
- artifacts/before_merge/linkfile/linkfile_extract_v1.jsonl: 更新后的提取结果
  * 添加 file_summary 字段（摘要文本）
  * 添加 file_summary_meta 字段（元数据）

依赖：
- pdf2image: PDF 转图片（需要 poppler-utils）
- python-docx: Word 文档解析
- transformers: Qwen2.5-VL-7B 模型
- qwen_vl_utils: Qwen VL 工具
- scripts/image/experts/image_utils.py: 图片预处理

使用示例：
    # 生成摘要（跳过已有摘要的记录）
    python scripts/linkfile/run_all/_01.5_run_file_summary.py
    
    # 强制重新生成所有摘要
    python scripts/linkfile/run_all/_01.5_run_file_summary.py --force

输出统计：
- 更新的文件记录数
- 摘要生成成功/失败数

作者：[Author]
更新于：2026-02-02
"""

import gc
import json
import logging
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import torch
from PIL import Image
from transformers import AutoModelForImageTextToText, AutoProcessor, BitsAndBytesConfig
from qwen_vl_utils import process_vision_info
from tqdm import tqdm

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts._common.path_utils import (
    get_file_dir,
    get_linkfile_before_merge,
    get_root,
    load_linkfile_config,
)
from scripts.image.experts.image_utils import resize_if_needed

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# =============================================================================
# Word 和 TXT 处理
# =============================================================================

def extract_word_text(docx_path: Path, max_chars: int = 2000) -> str:
    """
    从 Word 文档提取文本
    
    Args:
        docx_path: Word 文件路径
        max_chars: 最大提取字符数
        
    Returns:
        提取的文本内容
    """
    try:
        from docx import Document
    except ImportError:
        logger.error("python-docx 未安装，请运行: pip install python-docx")
        return "[无法读取 Word 文件: python-docx 未安装]"
    
    try:
        doc = Document(docx_path)
        
        # 提取所有段落文本
        paragraphs = []
        for para in doc.paragraphs:
            text = para.text.strip()
            if text:
                paragraphs.append(text)
        
        full_text = "\n".join(paragraphs)
        
        # 截取前 max_chars 字符
        if len(full_text) > max_chars:
            return full_text[:max_chars] + "..."
        else:
            return full_text
            
    except Exception as e:
        logger.error(f"  Word 文档读取失败: {e}")
        return f"[无法读取 Word 文件: {e}]"


def read_txt_file(txt_path: Path, max_chars: int = 2000) -> str:
    """
    读取 TXT 文件内容
    
    Args:
        txt_path: TXT 文件路径
        max_chars: 最大读取字符数
        
    Returns:
        文件内容
    """
    try:
        # 尝试多种编码
        encodings = ['utf-8', 'gbk', 'gb2312', 'utf-16']
        
        for encoding in encodings:
            try:
                with open(txt_path, 'r', encoding=encoding) as f:
                    content = f.read(max_chars + 100)  # 多读一点以便截断
                    
                    if len(content) > max_chars:
                        return content[:max_chars] + "..."
                    else:
                        return content
            except (UnicodeDecodeError, UnicodeError):
                continue
        
        # 所有编码都失败
        return "[无法读取 TXT 文件: 编码识别失败]"
        
    except Exception as e:
        logger.error(f"  TXT 文件读取失败: {e}")
        return f"[无法读取 TXT 文件: {e}]"


# =============================================================================
# PDF 处理
# =============================================================================

def pdf_to_images(pdf_path: Path, max_pages: int = 5, dpi: int = 150) -> List[Path]:
    """
    将 PDF 转换为图片
    
    Args:
        pdf_path: PDF 文件路径
        max_pages: 最大处理页数
        dpi: 图片分辨率
        
    Returns:
        临时图片文件路径列表
    """
    try:
        from pdf2image import convert_from_path
    except ImportError:
        logger.error("pdf2image 未安装，请运行: pip install pdf2image")
        logger.error("还需要安装 poppler: sudo apt-get install poppler-utils")
        return []
    
    try:
        # 转换 PDF 为图片
        images = convert_from_path(
            pdf_path,
            dpi=dpi,
            first_page=1,
            last_page=max_pages,
        )
        
        # 保存为临时文件
        temp_paths = []
        temp_dir = Path(tempfile.gettempdir()) / "linkfile_pdf"
        temp_dir.mkdir(parents=True, exist_ok=True)
        
        for i, img in enumerate(images):
            temp_path = temp_dir / f"{pdf_path.stem}_page_{i+1}.jpg"
            img.save(temp_path, "JPEG", quality=85)
            temp_paths.append(temp_path)
            
        logger.info(f"  PDF 转换完成: {len(temp_paths)} 页")
        return temp_paths
        
    except Exception as e:
        logger.error(f"  PDF 转换失败: {e}")
        return []


def get_zip_file_list(zip_path: Path, max_files: int = 20) -> str:
    """
    获取 ZIP 文件的内容列表
    
    Args:
        zip_path: ZIP 文件路径
        max_files: 最大显示文件数
        
    Returns:
        文件列表字符串
    """
    import zipfile
    
    try:
        with zipfile.ZipFile(zip_path, 'r') as zf:
            file_list = zf.namelist()
            
            # 过滤掉目录和隐藏文件
            files = [f for f in file_list if not f.endswith('/') and not f.startswith('__MACOSX')]
            
            # 尝试修复编码问题（Windows 中文 ZIP 常见问题）
            decoded_files = []
            for f in files:
                try:
                    # 尝试 cp437 -> utf-8 转换（Windows ZIP 常见编码）
                    decoded = f.encode('cp437').decode('utf-8')
                except (UnicodeDecodeError, UnicodeEncodeError):
                    try:
                        # 尝试 gbk 解码
                        decoded = f.encode('cp437').decode('gbk')
                    except:
                        decoded = f  # 保持原样
                decoded_files.append(decoded)
            
            if len(decoded_files) > max_files:
                display_files = decoded_files[:max_files]
                return f"包含 {len(decoded_files)} 个文件:\n" + "\n".join(f"- {f}" for f in display_files) + f"\n... 等 {len(decoded_files) - max_files} 个文件"
            else:
                return f"包含 {len(decoded_files)} 个文件:\n" + "\n".join(f"- {f}" for f in decoded_files)
                
    except Exception as e:
        logger.error(f"  ZIP 读取失败: {e}")
        return f"[无法读取 ZIP 文件: {e}]"


# =============================================================================
# Qwen2.5-VL 文档分析
# =============================================================================

class FileSummarizer:
    """
    文件摘要生成器 - 使用 Qwen2.5-VL-7B (4-bit)
    显存占用约 4.5GB，OCR 能力强，中文支持优秀
    """
    
    PROMPT_PDF_TEMPLATE = """文件名：{filename}

请根据文件名和图片内容，分析这份 PDF 文档并生成一个简洁的摘要（100-200字）。

要求：
1. 首先理解文件名暗示的文档类型和主题
2. 结合图片内容，概括文档的主要内容和目的
3. 提取关键信息（如日期、人名、机构、金额等）
4. 确认文档类型是否与文件名一致

请用中文回答，直接输出摘要内容，不要添加额外的格式或标题。"""

    PROMPT_WORD_TEMPLATE = """文件名：{filename}

以下是 Word 文档的部分内容：

{content}

请根据文件名和文档内容，生成一个简洁的摘要（100-200字）。

要求：
1. 概括文档的主要内容和目的
2. 提取关键信息（如日期、人名、机构、金额等）
3. 确认文档类型是否与文件名一致

请用中文回答，直接输出摘要内容，不要添加额外的格式或标题。"""

    def __init__(self, model_path: str = "/data/models/qwen2.5-vl-7b/Qwen/Qwen2___5-VL-7B-Instruct"):
        self.model_path = model_path
        self._model = None
        self._processor = None
        
    def _load_model(self):
        """延迟加载模型"""
        if self._model is not None:
            return
            
        logger.info(f"加载 Qwen2.5-VL-7B (4-bit)...")
        
        # 4-bit 量化配置
        bnb_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_use_double_quant=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.bfloat16
        )
        
        self._model = AutoModelForImageTextToText.from_pretrained(
            self.model_path,
            device_map="auto",
            trust_remote_code=True,
            quantization_config=bnb_config
        )
        
        self._processor = AutoProcessor.from_pretrained(
            self.model_path, 
            trust_remote_code=True
        )
        
        logger.info("Qwen2.5-VL-7B 加载完成")
        
    def _do_inference(self, image_path: Path, prompt: str) -> str:
        """执行推理（图片输入）"""
        # 预处理：缩放大图以避免OOM
        img = resize_if_needed(str(image_path))
        
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": img},
                    {"type": "text", "text": prompt},
                ],
            }
        ]
        
        text = self._processor.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        image_inputs, video_inputs = process_vision_info(messages)
        inputs = self._processor(
            text=[text],
            images=image_inputs,
            videos=video_inputs,
            padding=True,
            return_tensors="pt",
        ).to(self._model.device)
        
        with torch.no_grad():
            generated_ids = self._model.generate(
                **inputs,
                max_new_tokens=512,
                temperature=0.3,
                top_p=0.9
            )
            
        generated_ids_trimmed = [
            out_ids[len(in_ids):] for in_ids, out_ids in zip(inputs.input_ids, generated_ids)
        ]
        output_text = self._processor.batch_decode(
            generated_ids_trimmed, 
            skip_special_tokens=True, 
            clean_up_tokenization_spaces=False
        )
        
        return output_text[0]
    
    def _do_text_inference(self, prompt: str) -> str:
        """执行推理（纯文本输入）"""
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                ],
            }
        ]
        
        text = self._processor.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        inputs = self._processor(
            text=[text],
            padding=True,
            return_tensors="pt",
        ).to(self._model.device)
        
        with torch.no_grad():
            generated_ids = self._model.generate(
                **inputs,
                max_new_tokens=512,
                temperature=0.3,
                top_p=0.9
            )
            
        generated_ids_trimmed = [
            out_ids[len(in_ids):] for in_ids, out_ids in zip(inputs.input_ids, generated_ids)
        ]
        output_text = self._processor.batch_decode(
            generated_ids_trimmed, 
            skip_special_tokens=True, 
            clean_up_tokenization_spaces=False
        )
        
        return output_text[0]
    
    def summarize_pdf(self, pdf_path: Path) -> Tuple[str, Dict[str, Any]]:
        """
        为 PDF 文件生成摘要
        
        Args:
            pdf_path: PDF 文件路径
            
        Returns:
            (摘要文本, 元数据)
        """
        # 转换 PDF 为图片
        image_paths = pdf_to_images(pdf_path, max_pages=3)
        
        if not image_paths:
            return "[PDF 转换失败]", {"error": "pdf_conversion_failed"}
        
        try:
            self._load_model()
            
            # 准备 prompt，加入文件名作为上下文
            filename = pdf_path.name
            prompt = self.PROMPT_PDF_TEMPLATE.format(filename=filename)
            
            # 分析第一页（通常包含最重要的信息）
            summaries = []
            
            for i, img_path in enumerate(image_paths[:2]):  # 最多分析前2页
                logger.info(f"  分析第 {i+1} 页...")
                try:
                    caption = self._do_inference(img_path, prompt)
                    summaries.append(caption)
                except Exception as e:
                    logger.error(f"  第 {i+1} 页分析失败: {e}")
            
            # 合并摘要
            if len(summaries) == 0:
                return "[分析失败]", {"error": "analysis_failed"}
            elif len(summaries) == 1:
                final_summary = summaries[0]
            else:
                # 多页时取第一页的摘要（通常最完整）
                final_summary = summaries[0]
            
            # 清理临时文件
            for img_path in image_paths:
                try:
                    img_path.unlink()
                except:
                    pass
            
            metadata = {
                "model": "qwen2.5-vl-7b-4bit",
                "pages_analyzed": len(summaries),
                "total_pages": len(image_paths),
                "filename_hint": filename,
            }
            
            return final_summary, metadata
            
        except Exception as e:
            logger.error(f"  PDF 分析失败: {e}")
            return f"[分析失败: {e}]", {"error": str(e)}
    
    def summarize_word(self, docx_path: Path) -> Tuple[str, Dict[str, Any]]:
        """
        为 Word 文件生成摘要
        
        Args:
            docx_path: Word 文件路径
            
        Returns:
            (摘要文本, 元数据)
        """
        # 提取文档文本
        content = extract_word_text(docx_path, max_chars=2000)
        
        if content.startswith("[无法读取"):
            return content, {"error": "word_extraction_failed"}
        
        try:
            self._load_model()
            
            # 准备 prompt
            filename = docx_path.name
            prompt = self.PROMPT_WORD_TEMPLATE.format(filename=filename, content=content)
            
            # 使用 LLM 生成摘要
            logger.info(f"  使用 LLM 生成摘要...")
            summary = self._do_text_inference(prompt)
            
            metadata = {
                "model": "qwen2.5-vl-7b-4bit",
                "content_length": len(content),
                "filename_hint": filename,
            }
            
            return summary, metadata
            
        except Exception as e:
            logger.error(f"  Word 分析失败: {e}")
            return f"[分析失败: {e}]", {"error": str(e)}
    
    def summarize_txt(self, txt_path: Path) -> Tuple[str, Dict[str, Any]]:
        """
        为 TXT 文件生成摘要（直接读取内容）
        
        Args:
            txt_path: TXT 文件路径
            
        Returns:
            (摘要文本, 元数据)
        """
        content = read_txt_file(txt_path, max_chars=2000)
        
        if content.startswith("[无法读取"):
            return content, {"error": "txt_read_failed"}
        
        # TXT 文件直接使用内容作为摘要，不使用 LLM
        txt_name = txt_path.stem
        summary = f"文本文件「{txt_name}」内容：\n{content}"
        
        metadata = {
            "model": "direct_read",
            "content_length": len(content),
            "file_type": "txt",
        }
        
        return summary, metadata
    
    def summarize_zip(self, zip_path: Path) -> Tuple[str, Dict[str, Any]]:
        """
        为 ZIP 文件生成摘要（仅列出内容）
        
        Args:
            zip_path: ZIP 文件路径
            
        Returns:
            (摘要文本, 元数据)
        """
        file_list = get_zip_file_list(zip_path)
        
        # 根据文件名推断内容
        zip_name = zip_path.stem
        summary = f"压缩包「{zip_name}」{file_list}"
        
        metadata = {
            "model": "rule_based",
            "file_type": "zip",
        }
        
        return summary, metadata
    
    def unload(self):
        """卸载模型释放显存"""
        if self._model is not None:
            del self._model
            self._model = None
        if self._processor is not None:
            del self._processor
            self._processor = None
            
        gc.collect()
        
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except:
            pass
            
        logger.info("FileSummarizer 已卸载")


# =============================================================================
# 主流程
# =============================================================================

def load_extract_records(input_path: Path) -> List[Dict[str, Any]]:
    """加载提取记录"""
    records = []
    with open(input_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def save_extract_records(records: List[Dict[str, Any]], output_path: Path):
    """保存提取记录"""
    with open(output_path, "w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Generate file summaries for linkfile pipeline")
    parser.add_argument('--force', action='store_true', help='Force regenerate summaries even if they exist')
    args = parser.parse_args()
    
    logger.info("=" * 60)
    logger.info("Linkfile Pipeline - Step 1.5: File Summary")
    logger.info("=" * 60)
    
    # 加载配置
    config = load_linkfile_config()
    workspace_root = get_root()
    file_dir = get_file_dir()
    
    logger.info(f"Workspace: {workspace_root}")
    logger.info(f"File directory: {file_dir}")
    logger.info(f"Model: Qwen2.5-VL-7B (4-bit)")
    
    # 输入路径
    input_dir = get_linkfile_before_merge()
    input_filename = config.get('output_files', {}).get('extract', 'linkfile_extract_v1.jsonl')
    input_path = input_dir / input_filename
    
    if not input_path.exists():
        logger.error(f"Input file not found: {input_path}")
        logger.error("Please run _01_extract_and_anonymize.py first.")
        return
    
    logger.info(f"Loading from {input_path}...")
    records = load_extract_records(input_path)
    logger.info(f"  Loaded {len(records)} records")
    
    # 筛选 file 类型记录
    file_records = [r for r in records if r.get('link_sub_type') == 'file']
    logger.info(f"  Found {len(file_records)} file records")
    
    if not file_records:
        logger.info("No file records to process. Exiting.")
        return
    
    # 初始化摘要生成器
    summarizer = FileSummarizer()
    
    # 处理每个文件
    logger.info("Generating file summaries...")
    if args.force:
        logger.info("  --force mode: regenerating all summaries")
    updated_count = 0
    
    for record in tqdm(file_records, desc="Summarizing"):
        file_name = record.get('file_name', '')
        file_ext = record.get('file_ext', '').lower()
        media_path = record.get('media_path', '')
        
        # 跳过已有摘要的记录（除非 --force）
        if not args.force and record.get('file_summary'):
            logger.info(f"  跳过已有摘要: {file_name}")
            continue
        
        # 构建完整路径
        if media_path.startswith('raw/'):
            full_path = workspace_root / media_path
        else:
            full_path = workspace_root / 'raw' / media_path
        
        if not full_path.exists():
            # 尝试直接在 file 目录查找
            full_path = file_dir / file_name
        
        if not full_path.exists():
            logger.warning(f"  文件不存在: {file_name}")
            record['file_summary'] = f"[文件不存在: {file_name}]"
            continue
        
        logger.info(f"  处理: {file_name}")
        
        # 根据文件类型生成摘要
        if file_ext == 'pdf':
            summary, meta = summarizer.summarize_pdf(full_path)
        elif file_ext in ['docx', 'doc']:
            summary, meta = summarizer.summarize_word(full_path)
        elif file_ext == 'txt':
            summary, meta = summarizer.summarize_txt(full_path)
        elif file_ext == 'zip':
            summary, meta = summarizer.summarize_zip(full_path)
        else:
            summary = f"[不支持的文件类型: {file_ext}]"
            meta = {"error": "unsupported_type"}
        
        # 更新记录
        record['file_summary'] = summary
        record['file_summary_meta'] = meta
        updated_count += 1
        
        logger.info(f"    摘要: {summary[:100]}...")
    
    # 卸载模型
    summarizer.unload()
    
    # 保存更新后的记录
    logger.info(f"Saving to {input_path}...")
    save_extract_records(records, input_path)
    
    logger.info(f"Done. Updated {updated_count} file records with summaries.")


if __name__ == "__main__":
    main()
