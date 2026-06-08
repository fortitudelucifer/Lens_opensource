#!/usr/bin/env python3
"""
文档专家模块 (Document Expert Module)

功能：
- 文档/截图/政治符号分析
- 使用 Pixtral 12B (GGUF) via llama-cpp-python
- 强 OCR 能力，适合文字密集型图片

专业化场景：
- 文字密集型图片（聊天记录、网页截图、文章）
- 政治符号、仇恨言论识别
- 文档结构理解
- 表格、图表分析

模型配置：
- 模型：Pixtral 12B (GGUF Q5_K_M 量化)
- Vision Encoder：mmproj-Pixtral-12B-2409-Q8_0.gguf
- 显存占用：约 8-10GB
- 推理引擎：llama-cpp-python

5070 Ti 兼容性：
- 使用 compute_89 (Ada Lovelace) 兼容编译
- 编译命令：CMAKE_ARGS='-DGGML_CUDA=on -DCMAKE_CUDA_ARCHITECTURES=89'

Chat Template 补丁：
- 问题：Pixtral GGUF 的 chat_template 使用 Go 模板语法 ({{ .System }})
- 冲突：llama-cpp-python 期望 Jinja2 语法
- 解决：猴子补丁 SafeJinja2ChatFormatter，解析失败时使用默认模板

Prompt 设计：
- 五个维度：文字内容、文档类型、关键信息、情感倾向、敏感内容
- 完整转录所有可见文字
- 提取关键信息点（日期、人名、数字、网址）
- 标记敏感词汇或符号

使用示例：
    from scripts.image.experts.doc_expert import DocExpert
    
    expert = DocExpert()
    caption, metadata = expert.generate_caption(
        image_path="/path/to/screenshot.png",
        max_tokens=1024,
        temperature=0.6
    )
    
    print(caption)  # 详细的文档分析
    expert.unload()

配置参数：
- model_dir: 模型目录（默认：/data/models/pixtral-12b-gguf）
- n_gpu_layers: GPU 层数（-1 = 全部加载到 GPU）
- n_ctx: 上下文长度（默认：4096）

依赖：
- llama-cpp-python: GGUF 模型推理（需要 CUDA 编译）
- PIL: 图片加载
- base64: 图片编码

安装 llama-cpp-python：
    CMAKE_ARGS='-DGGML_CUDA=on -DCMAKE_CUDA_ARCHITECTURES=89' \
    pip install llama-cpp-python --force-reinstall --no-cache-dir

作者：[Author]
项目：wechatDHA - 微信聊天记录多模态处理流水线
更新于：2026-02-02
"""

import os
import sys
import gc
import logging
from pathlib import Path
from typing import Dict, Any, Tuple, Optional
import base64

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def _patch_llama_cpp_chat_template():
    """
    猴子补丁: 修复 Pixtral GGUF 的 chat_template 解析错误
    
    问题: Pixtral GGUF 的 chat_template 使用 Go 模板语法 ({{ .System }})
          而 llama-cpp-python 期望 Jinja2 语法，导致解析失败
    
    解决: 创建一个安全的 Jinja2ChatFormatter，在解析失败时使用默认模板
    """
    try:
        import llama_cpp.llama_chat_format as chat_format_module
        
        # 检查是否已经打过补丁
        if hasattr(chat_format_module, '_pixtral_patched'):
            return
        
        OriginalJinja2ChatFormatter = chat_format_module.Jinja2ChatFormatter
        
        class SafeJinja2ChatFormatter(OriginalJinja2ChatFormatter):
            def __init__(self, *args, **kwargs):
                try:
                    super().__init__(*args, **kwargs)
                except Exception as e:
                    logger.warning(f"跳过无效的 chat_template: {str(e)[:50]}...")
                    self.template = "{% for message in messages %}{{ message['content'] }}{% endfor %}"
                    from jinja2.sandbox import ImmutableSandboxedEnvironment
                    self._environment = ImmutableSandboxedEnvironment(
                        trim_blocks=True, lstrip_blocks=True
                    ).from_string(self.template)
        
        chat_format_module.Jinja2ChatFormatter = SafeJinja2ChatFormatter
        chat_format_module._pixtral_patched = True
        logger.info("已应用 Pixtral chat_template 兼容补丁")
        
    except ImportError:
        logger.warning("llama_cpp 未安装，跳过补丁")


class DocExpert:
    """
    文档专家模型 - 使用 Pixtral 12B (GGUF via llama-cpp-python)
    
    显存占用约 8-10GB (Q5_K_M 量化)
    """
    
    PROMPT_ZH = """请仔细分析这张文档/截图图片，详细提取以下信息：

1. 【文字内容】完整转录图片中所有可见的文字内容
2. 【文档类型】判断文档类型（如聊天记录、网页截图、文章、表格等）
3. 【关键信息】提取关键信息点（日期、人名、数字、网址等）
4. 【情感倾向】分析文字内容的情感倾向
5. 【敏感内容】标记任何敏感词汇或符号（如政治符号、仇恨言论）

请用中文详细描述。"""

    def __init__(
        self,
        model_dir: str = "/data/models/pixtral-12b-gguf",
        n_gpu_layers: int = -1,  # -1 = 全部加载到 GPU
        n_ctx: int = 4096,
    ):
        self.model_dir = Path(model_dir)
        self.model_path = self.model_dir / "Pixtral-12B-2409-Q5_K_M.gguf"
        self.mmproj_path = self.model_dir / "mmproj-Pixtral-12B-2409-Q8_0.gguf"
        self.n_gpu_layers = n_gpu_layers
        self.n_ctx = n_ctx
        
        self._llm = None
        self._chat_handler = None
        
        logger.info(f"DocExpert 初始化: {self.model_path}")
        logger.info(f"  Vision encoder: {self.mmproj_path}")
        
    def _load_model(self):
        """延迟加载模型"""
        if self._llm is not None:
            return
            
        # 检查文件存在
        if not self.model_path.exists():
            raise FileNotFoundError(f"模型文件不存在: {self.model_path}")
        if not self.mmproj_path.exists():
            raise FileNotFoundError(f"Vision encoder 不存在: {self.mmproj_path}")
            
        logger.info(f"加载 Pixtral 12B GGUF...")
        
        try:
            # 应用 chat_template 兼容补丁 (Pixtral GGUF 使用 Go 模板语法)
            _patch_llama_cpp_chat_template()
            
            from llama_cpp import Llama
            from llama_cpp.llama_chat_format import Llava15ChatHandler
            
            # 创建 vision chat handler
            self._chat_handler = Llava15ChatHandler(
                clip_model_path=str(self.mmproj_path),
                verbose=False
            )
            
            # 加载 LLM (5070 Ti 使用 compute_89 兼容编译)
            self._llm = Llama(
                model_path=str(self.model_path),
                chat_handler=self._chat_handler,
                chat_format="llava-1-5",  # 使用 llava-1-5 格式
                n_gpu_layers=self.n_gpu_layers,
                n_ctx=self.n_ctx,
                verbose=False,
            )
            
            logger.info("Pixtral 12B 加载完成 (5070 Ti compute_89 兼容)")
            
        except ImportError as e:
            logger.error(f"llama-cpp-python 未安装: {e}")
            raise ImportError(
                "请安装 llama-cpp-python: "
                "CMAKE_ARGS='-DGGML_CUDA=on -DCMAKE_CUDA_ARCHITECTURES=89' "
                "pip install llama-cpp-python --force-reinstall --no-cache-dir"
            )
    
    def _image_to_data_uri(self, image_path: str) -> str:
        """将图片转换为 data URI"""
        import mimetypes
        mime_type, _ = mimetypes.guess_type(image_path)
        if mime_type is None:
            mime_type = "image/jpeg"
        with open(image_path, 'rb') as f:
            b64 = base64.b64encode(f.read()).decode('utf-8')
        return f"data:{mime_type};base64,{b64}"
    
    def generate_caption(
        self,
        image_path: str,
        prompt: str = None,
        max_tokens: int = 1024,
        temperature: float = 0.6,
    ) -> Tuple[str, Dict[str, Any]]:
        """
        生成文档描述
        
        Args:
            image_path: 图片路径
            prompt: 自定义 prompt（可选）
            max_tokens: 最大生成 token 数
            temperature: 生成温度
            
        Returns:
            Tuple of (caption, metadata)
        """
        try:
            self._load_model()
            
            # 准备消息
            image_uri = self._image_to_data_uri(image_path)
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": image_uri}},
                        {"type": "text", "text": prompt or self.PROMPT_ZH}
                    ]
                }
            ]
            
            # 生成
            response = self._llm.create_chat_completion(
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            
            caption = response['choices'][0]['message']['content']
            metadata = {
                "model": "pixtral-12b-gguf",
                "expert_type": "doc",
                "via_llama_cpp": True,
                "prompt_tokens": response.get('usage', {}).get('prompt_tokens', 0),
                "completion_tokens": response.get('usage', {}).get('completion_tokens', 0),
            }
            
            return caption, metadata
            
        except Exception as e:
            logger.error(f"DocExpert 处理失败: {e}")
            return f"[ERROR] {str(e)}", {"error": str(e)}
    
    def unload(self):
        """卸载模型释放显存"""
        if self._llm is not None:
            del self._llm
            self._llm = None
        if self._chat_handler is not None:
            del self._chat_handler
            self._chat_handler = None
        gc.collect()
        
        # 清理 CUDA 缓存
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except:
            pass
            
        logger.info("DocExpert 已卸载")


# === 测试 ===
if __name__ == '__main__':
    print("=" * 60)
    print("测试 DocExpert (Pixtral 12B GGUF)")
    print("=" * 60)
    
    expert = DocExpert()
    
    # 检查模型文件
    print(f"\n模型文件:")
    print(f"  LLM: {expert.model_path} ({'✅' if expert.model_path.exists() else '❌'})")
    print(f"  Vision: {expert.mmproj_path} ({'✅' if expert.mmproj_path.exists() else '❌'})")
    
    # 如果有测试图片 - 使用文档截图
    test_path = "/data/demo/tests/manual_images/screenshot.png"
    if os.path.exists(test_path):
        print(f"\n处理测试图片: {test_path}")
        caption, meta = expert.generate_caption(test_path)
        print(f"\n描述 ({len(caption)} 字符):\n{caption[:500]}...")
        print(f"\n元数据: {meta}")
        
        # 卸载
        expert.unload()
    else:
        print(f"测试图片不存在: {test_path}")
    
    print("\n测试完成。")
