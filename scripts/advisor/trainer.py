"""
关系顾问训练器模块

功能：
- 使用 QLoRA 微调 Qwen3-8B 模型，训练关系顾问的本地推理能力
- 支持两种训练后端：
  1. hf: 标准 HuggingFace + BitsAndBytes + PEFT（兼容性好）
  2. unsloth: Unsloth FastLanguageModel（约 60% 显存节省，2x 训练速度）
- 单 GPU (RTX 5070 Ti 16GB) 串行执行
- 训练完成后显式卸载模型并清理显存

处理流程：
1. 加载基座模型（Qwen3-8B）+ 4-bit 量化
2. 配置 LoRA 适配器（r=32, alpha=64, target_modules=[q,k,v]_proj）
3. 加载训练数据（JSONL messages 格式）
4. 使用 SFTTrainer 进行微调
5. 保存 LoRA 适配器权重
6. 卸载模型并清理 GPU 显存

输入：
- JSONL 训练数据文件（messages 格式，由 TrainingFormatter 生成）
- 训练配置（TrainingConfig）

输出：
- LoRA 适配器权重（保存到 output_dir）
- 训练日志和指标

依赖：
- transformers: 模型加载和训练
- peft: LoRA/QLoRA 适配器
- bitsandbytes: 4-bit 量化
- trl: SFTTrainer
- unsloth (可选): 加速训练后端
- torch: GPU 管理

使用示例：
    from scripts.advisor.trainer import AdvisorTrainer
    
    trainer = AdvisorTrainer(config)
    trainer.train('training_data.jsonl')
    trainer.unload_model()  # 训练完成后必须调用

性能参考（RTX 5070 Ti 16GB）：
- hf 后端：约 2-3 小时/epoch（100 样本，max_seq_length=2048）
- unsloth 后端：约 1-1.5 小时/epoch（同等条件）
- 显存占用：约 12-14GB（4-bit 量化 + 梯度检查点）

注意事项：
- 训练完成后必须调用 unload_model() 释放显存
- unsloth 后端需要额外安装 unsloth 包
- 梯度累积步数 = 16，等效批次大小 = 1 × 16 = 16
- 建议使用 gradient_checkpointing 节省显存

作者：forcifer
更新于：2026-02-15
"""

import gc
import json
import os
from pathlib import Path
from typing import Optional

# Unsloth 必须在 trl/transformers/peft 之前导入以确保优化生效
try:
    import unsloth  # noqa: F401
    _UNSLOTH_AVAILABLE = True
except ImportError:
    _UNSLOTH_AVAILABLE = False

import torch
from datasets import Dataset
from trl import SFTConfig, SFTTrainer


class AdvisorTrainer:
    """关系顾问训练器"""
    
    def __init__(self, config: Optional[dict] = None):
        """
        初始化训练器
        
        Args:
            config: 配置字典，包含：
                - base_model: 基座模型路径
                - output_dir: 输出目录
                - lora_r: LoRA rank
                - lora_alpha: LoRA alpha
                - learning_rate: 学习率
                - num_epochs: 训练轮数
                - batch_size: 批次大小
                - gradient_accumulation_steps: 梯度累积步数
                - max_seq_length: 最大序列长度
                - use_unsloth: 使用 Unsloth 后端 (节省 ~60% VRAM)
        """
        config = config or {}
        
        # 后端选择
        self.use_unsloth = config.get('use_unsloth', False)
        if self.use_unsloth and not _UNSLOTH_AVAILABLE:
            raise ImportError(
                "use_unsloth=True 但 unsloth 未安装。"
                "请使用 CHAT_APP_DHA_unsloth 环境: conda run -n CHAT_APP_DHA_unsloth ..."
            )
        
        # 模型配置
        self.base_model = config.get('base_model', '/data/models/Qwen3-8B-Instruct')
        self.output_dir = config.get('output_dir', 'advisor_out/models/relationship_advisor')
        
        # LoRA 配置（优化为 16GB 单卡，all linear layers + r=16）
        self.lora_r = config.get('lora_r', 16)
        self.lora_alpha = config.get('lora_alpha', 32)
        # Unsloth 要求 dropout=0 (已优化掉)
        self.lora_dropout = 0 if self.use_unsloth else config.get('lora_dropout', 0.05)
        self.target_modules = config.get('target_modules', [
            'q_proj', 'k_proj', 'v_proj', 'o_proj',
            'gate_proj', 'up_proj', 'down_proj',
        ])
        
        # 训练配置
        self.learning_rate = config.get('learning_rate', 1e-4)
        self.num_epochs = config.get('num_epochs', 5)
        self.batch_size = config.get('batch_size', 1)
        self.gradient_accumulation_steps = config.get('gradient_accumulation_steps', 8)
        self.max_seq_length = config.get('max_seq_length', 4096)
        self.warmup_ratio = config.get('warmup_ratio', 0.03)
        self.optimizer = config.get('optimizer', 'paged_adamw_32bit')
        
        # 量化配置
        self.use_4bit = config.get('use_4bit', True)
        self.bnb_4bit_compute_dtype = config.get('bnb_4bit_compute_dtype', 'bfloat16')
        self.bnb_4bit_quant_type = config.get('bnb_4bit_quant_type', 'nf4')
        
        # 显存优化
        self.use_gradient_checkpointing = config.get('use_gradient_checkpointing', True)
        
        # 保存配置
        self.save_steps = config.get('save_steps', 100)
        self.save_total_limit = config.get('save_total_limit', 3)
        self.logging_steps = config.get('logging_steps', 10)
        
        self.model = None
        self.tokenizer = None
        self._trainer = None
    
    def prepare_model(self):
        """准备模型和 tokenizer"""
        print(f"加载基座模型: {self.base_model}")
        print(f"后端: {'Unsloth' if self.use_unsloth else 'HuggingFace (vanilla)'}")
        
        if self.use_unsloth:
            return self._prepare_model_unsloth()
        else:
            return self._prepare_model_hf()
    
    def _prepare_model_unsloth(self):
        """使用 Unsloth 后端准备模型 (~60% VRAM 节省)"""
        from unsloth import FastLanguageModel
        
        self.model, self.tokenizer = FastLanguageModel.from_pretrained(
            model_name=self.base_model,
            max_seq_length=self.max_seq_length,
            load_in_4bit=self.use_4bit,
            dtype=None,  # auto detect
            local_files_only=True,  # 从本地加载，跳过 HF 网络检查
        )
        
        self.model = FastLanguageModel.get_peft_model(
            self.model,
            r=self.lora_r,
            lora_alpha=self.lora_alpha,
            lora_dropout=0,  # Unsloth 要求 dropout=0
            target_modules=self.target_modules,
            use_gradient_checkpointing="unsloth",  # Unsloth 优化的 gradient checkpointing
            random_state=42,
        )
        
        # 打印可训练参数
        self.model.print_trainable_parameters()
        
        return self.model, self.tokenizer
    
    def _prepare_model_hf(self):
        """使用标准 HuggingFace 后端准备模型"""
        from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
        from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
        
        # 量化配置
        if self.use_4bit:
            compute_dtype = getattr(torch, self.bnb_4bit_compute_dtype)
            bnb_config = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_quant_type=self.bnb_4bit_quant_type,
                bnb_4bit_compute_dtype=compute_dtype,
                bnb_4bit_use_double_quant=True,
            )
        else:
            bnb_config = None
        
        # 加载模型
        self.model = AutoModelForCausalLM.from_pretrained(
            self.base_model,
            quantization_config=bnb_config,
            device_map='auto',
            trust_remote_code=True,
            dtype=torch.bfloat16 if self.use_4bit else torch.float16,
        )
        
        # 加载 tokenizer
        self.tokenizer = AutoTokenizer.from_pretrained(
            self.base_model,
            trust_remote_code=True,
        )
        
        if self.tokenizer.pad_token is None:
            self.tokenizer.pad_token = self.tokenizer.eos_token
        
        # 准备模型进行 k-bit 训练
        if self.use_4bit:
            self.model = prepare_model_for_kbit_training(
                self.model,
                use_gradient_checkpointing=self.use_gradient_checkpointing,
            )
        
        # LoRA 配置
        lora_config = LoraConfig(
            r=self.lora_r,
            lora_alpha=self.lora_alpha,
            lora_dropout=self.lora_dropout,
            target_modules=self.target_modules,
            bias='none',
            task_type='CAUSAL_LM',
        )
        
        # 应用 LoRA
        self.model = get_peft_model(self.model, lora_config)
        
        # 打印可训练参数
        self.model.print_trainable_parameters()
        
        return self.model, self.tokenizer
    
    def prepare_dataset(self, data_path: str) -> Dataset:
        """
        准备训练数据集
        
        Args:
            data_path: 训练数据路径（JSONL 格式）
        
        Returns:
            HuggingFace Dataset 对象
        """
        print(f"加载训练数据: {data_path}")
        
        # 读取数据
        data = []
        with open(data_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    data.append(json.loads(line))
        
        print(f"加载了 {len(data)} 个训练样本")
        
        # 格式化为对话格式
        def format_sample(sample):
            messages = sample.get('messages', [])
            
            # 使用 tokenizer 的 chat template
            if hasattr(self.tokenizer, 'apply_chat_template'):
                text = self.tokenizer.apply_chat_template(
                    messages,
                    tokenize=False,
                    add_generation_prompt=False,
                )
            else:
                # 手动格式化
                text = ''
                for msg in messages:
                    role = msg['role']
                    content = msg['content']
                    if role == 'system':
                        text += f'<|im_start|>system\n{content}<|im_end|>\n'
                    elif role == 'user':
                        text += f'<|im_start|>user\n{content}<|im_end|>\n'
                    elif role == 'assistant':
                        text += f'<|im_start|>assistant\n{content}<|im_end|>\n'
            
            return {'text': text}
        
        # 创建数据集
        formatted_data = [format_sample(s) for s in data]
        dataset = Dataset.from_list(formatted_data)
        
        return dataset
    
    def train(self, data_path: str, eval_data_path: str = None, resume_from_checkpoint: bool = False):
        """
        执行训练
        
        Args:
            data_path: 训练数据路径
            eval_data_path: 验证数据路径（用于 val_loss 监控，可选）
            resume_from_checkpoint: 是否从断点继续训练
        """
        # 准备模型
        if self.model is None:
            self.prepare_model()
        
        # 准备数据集
        dataset = self.prepare_dataset(data_path)
        eval_dataset = self.prepare_dataset(eval_data_path) if eval_data_path else None
        
        # 创建输出目录
        output_dir = Path(self.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # 训练参数（trl >= 0.27: 使用 SFTConfig 代替 TrainingArguments）
        sft_kwargs = dict(
            output_dir=str(output_dir),
            num_train_epochs=self.num_epochs,
            per_device_train_batch_size=self.batch_size,
            gradient_accumulation_steps=self.gradient_accumulation_steps,
            learning_rate=self.learning_rate,
            warmup_ratio=self.warmup_ratio,
            logging_steps=self.logging_steps,
            save_steps=self.save_steps,
            save_total_limit=self.save_total_limit,
            fp16=False,
            bf16=True,
            optim=self.optimizer,
            lr_scheduler_type='cosine',
            report_to='tensorboard',
            max_grad_norm=0.3,
            group_by_length=True,
            # SFT 特有参数
            max_length=self.max_seq_length,
            dataset_text_field='text',
            packing=False,
        )
        # Unsloth 自行管理 gradient checkpointing，HF 需手动设置
        if not self.use_unsloth:
            sft_kwargs['gradient_checkpointing'] = self.use_gradient_checkpointing
            sft_kwargs['gradient_checkpointing_kwargs'] = {"use_reentrant": False}
        if eval_dataset is not None:
            sft_kwargs['eval_strategy'] = 'epoch'
            sft_kwargs['save_strategy'] = 'epoch'
            sft_kwargs['per_device_eval_batch_size'] = self.batch_size
            sft_kwargs['load_best_model_at_end'] = True
            sft_kwargs['metric_for_best_model'] = 'eval_loss'
            sft_kwargs['greater_is_better'] = False
        training_args = SFTConfig(**sft_kwargs)
        
        # 创建训练器（trl >= 0.27: tokenizer → processing_class）
        trainer_kwargs = dict(
            model=self.model,
            train_dataset=dataset,
            args=training_args,
            processing_class=self.tokenizer,
        )
        if eval_dataset is not None:
            trainer_kwargs['eval_dataset'] = eval_dataset
        self._trainer = SFTTrainer(**trainer_kwargs)
        
        # 开始训练
        print("\n开始训练...")
        print(f"输出目录: {output_dir}")
        print(f"训练轮数: {self.num_epochs}")
        print(f"有效批次大小: {self.batch_size * self.gradient_accumulation_steps}")
        if eval_dataset is not None:
            print(f"验证集大小: {len(eval_dataset)} (每 epoch 评估一次)")
        print()
        
        self._trainer.train(resume_from_checkpoint=resume_from_checkpoint)
        
        # 保存最终模型
        self.save_model()
        
        print("\n训练完成！")
        print("ℹ️  请调用 trainer.unload_model() 释放显存")
    
    def save_model(self):
        """保存 LoRA 权重"""
        output_dir = Path(self.output_dir)
        
        print(f"保存 LoRA 权重到: {output_dir}")
        
        # 保存 LoRA 权重
        self.model.save_pretrained(output_dir)
        
        # 保存 tokenizer
        self.tokenizer.save_pretrained(output_dir)
        
        print("保存完成！")
    
    def unload_model(self):
        """卸载模型释放显存（单 GPU 串行策略：训练完成后必须调用）"""
        if self._trainer is not None:
            del self._trainer
            self._trainer = None
        
        if self.model is not None:
            del self.model
            self.model = None
        
        if self.tokenizer is not None:
            del self.tokenizer
            self.tokenizer = None
        
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.synchronize()
            mem_gb = torch.cuda.memory_allocated() / 1e9
            print(f"模型已卸载，显存已释放 (剩余占用: {mem_gb:.3f}GB)")
        else:
            print("模型已卸载")
