"""
关系顾问 Agent 运行脚本包

包含完整的训练流水线脚本（按执行顺序）：

_00_verify_environment.py  - 验证训练环境（依赖、CUDA、基座模型）
_01_extract_conversations.py - 从 SFT 数据提取对话片段
_02_generate_analysis.py   - 调用 LLM API 生成关系分析
_02b_model_comparison.py   - 多模型对比评测（5 chunks × 8 backends）
_02c_fusion_pipeline.py    - 多专家并行融合流水线（DeepSeek+GLM+Kimi → Qwen MoA）
_02c_rerun_moa.py          - MoA 重融合/修复（复用已有分析）
_03_export_for_review.py   - 导出审核用 Markdown 文件
_03b_ai_review.py          - AI 辅助审核（5 维度评分 + 补齐）
_04_import_reviewed.py     - 导入人工审核结果
_05_format_training_data.py - 格式化 SFT 训练数据
_05b_filter_split_training.py - 过滤 + 分层采样划分 train/val/test
_05c_deanonymize_training.py - 反匿名化训练数据（Strategy B）
_06_train_model.py         - QLoRA 模型训练
_07_run_inference.py       - 模型推理（交互/单条/批量）
_07b_eval_compare.py       - 模型评估对比（HF vs Unsloth）
_08_run_dialogue.py        - 实时对话（listen/consult 模式）
_09_build_graph.py         - 构建 GraphRAG 向量索引
_10_augment_data.py        - 数据增强与多教师蒸馏
"""
