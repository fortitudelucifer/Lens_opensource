"""评测 Harness（M1 MVP）

对应文档：
- plan_v6/评测Harness_Trace与消融开关_接口契约.md（§12 最小施工清单 / §13 实验协议）
- plan_v6/preregistration.md（MRT 预注册）

模块：
- ablation: 消融开关 + 合格决策点规则 + 决策点随机化（AblationContext）
- tracer:   统一 Trace 落盘（公开/私有分库，H1）+ 事后抽取器 + run manifest（H2）
- metrics:  合格点占比（availability）+ 六维分布 + 臂平衡 + 近端结局差 报告

定位：先做「可行性预实验」——只验管道、估 availability 与效应量输入，**不下有效性结论**。
"""

from scripts.advisor.eval.ablation import AblationContext, extract_sixdim

__all__ = ["AblationContext", "extract_sixdim"]
