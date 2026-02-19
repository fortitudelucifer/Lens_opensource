#!/bin/bash
# Agent SFT 数据生成流水线
# 
# 用法：
#   ./run_agent_sft_pipeline.sh           # 生成 L1 和 L2
#   ./run_agent_sft_pipeline.sh --only l1 # 只生成 L1
#   ./run_agent_sft_pipeline.sh --only l2 # 只生成 L2
#   ./run_agent_sft_pipeline.sh --skip-postprocess  # 跳过后处理（使用已有的 processed 文件）

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 默认参数
ONLY=""
SKIP_POSTPROCESS=false
TIMELINE_DIR="timeline_out"

# 解析参数
while [[ $# -gt 0 ]]; do
    case $1 in
        --only)
            ONLY="$2"
            shift 2
            ;;
        --skip-postprocess)
            SKIP_POSTPROCESS=true
            shift
            ;;
        --timeline-dir)
            TIMELINE_DIR="$2"
            shift 2
            ;;
        -h|--help)
            echo "用法: $0 [选项]"
            echo ""
            echo "选项:"
            echo "  --only l1|l2        只生成指定级别的数据"
            echo "  --skip-postprocess  跳过时间轴后处理步骤"
            echo "  --timeline-dir DIR  指定时间轴目录（默认: timeline_out）"
            echo "  -h, --help          显示帮助信息"
            exit 0
            ;;
        *)
            echo -e "${RED}未知参数: $1${NC}"
            exit 1
            ;;
    esac
done

echo -e "${GREEN}=== Agent SFT 数据生成流水线 ===${NC}"
echo ""

# 检查输入文件
INPUT_FILE="${TIMELINE_DIR}/enriched_full.jsonl"
if [ ! -f "$INPUT_FILE" ]; then
    echo -e "${RED}[ERROR] 输入文件不存在: $INPUT_FILE${NC}"
    echo "请先运行多模态处理流水线生成时间轴数据"
    exit 1
fi

# Step 1: 时间轴后处理
if [ "$SKIP_POSTPROCESS" = false ]; then
    echo -e "${YELLOW}[1/6] 时间轴后处理...${NC}"
    conda run -n CHAT_APP_DHA python scripts/timeline/postprocess_timeline.py \
        --input "${TIMELINE_DIR}/enriched_full.jsonl" \
        --output "${TIMELINE_DIR}/enriched_full_processed.jsonl"
    echo ""
else
    echo -e "${YELLOW}[1/6] 跳过时间轴后处理（使用已有文件）${NC}"
    if [ ! -f "${TIMELINE_DIR}/enriched_full_processed.jsonl" ]; then
        echo -e "${RED}[ERROR] enriched_full_processed.jsonl 不存在${NC}"
        exit 1
    fi
    echo ""
fi

# L1 分支
if [ -z "$ONLY" ] || [ "$ONLY" = "l1" ]; then
    # Step 2: L1 字段精简
    echo -e "${YELLOW}[2/6] L1 字段精简...${NC}"
    conda run -n CHAT_APP_DHA python scripts/compression/sft_trimmer.py --l1 \
        --input-dir "${TIMELINE_DIR}" \
        --output-dir "${TIMELINE_DIR}"
    echo ""

    # Step 3: L1 SFT 优化
    echo -e "${YELLOW}[3/6] L1 SFT 优化...${NC}"
    conda run -n CHAT_APP_DHA python scripts/compression/sft_optimizer.py \
        --input "${TIMELINE_DIR}/enriched_full_anonymized_l1_sft.jsonl" \
        --output "${TIMELINE_DIR}/agent_sft_l1.jsonl" \
        --level l1 \
        --id-mapping "${TIMELINE_DIR}/id_mapping_l1.jsonl"
    echo ""
else
    echo -e "${YELLOW}[2/6] 跳过 L1 字段精简（--only l2）${NC}"
    echo -e "${YELLOW}[3/6] 跳过 L1 SFT 优化（--only l2）${NC}"
    echo ""
fi

# L2 分支
if [ -z "$ONLY" ] || [ "$ONLY" = "l2" ]; then
    # Step 4: L2 匿名化
    echo -e "${YELLOW}[4/6] L2 匿名化（使用两阶段 PII）...${NC}"
    conda run -n CHAT_APP_DHA python scripts/timeline/run_anonymization.py \
        --level l2 \
        --input "${TIMELINE_DIR}/enriched_full_processed.jsonl" \
        --output-dir "${TIMELINE_DIR}" \
        --two-stage-pii
    echo ""

    # Step 5: L2 字段精简
    echo -e "${YELLOW}[5/6] L2 字段精简...${NC}"
    conda run -n CHAT_APP_DHA python scripts/compression/sft_trimmer.py --l2 \
        --input-dir "${TIMELINE_DIR}" \
        --output-dir "${TIMELINE_DIR}"
    echo ""

    # Step 6: L2 SFT 优化
    echo -e "${YELLOW}[6/6] L2 SFT 优化...${NC}"
    conda run -n CHAT_APP_DHA python scripts/compression/sft_optimizer.py \
        --input "${TIMELINE_DIR}/enriched_full_anonymized_l2_sft.jsonl" \
        --output "${TIMELINE_DIR}/agent_sft_l2.jsonl" \
        --level l2 \
        --id-mapping "${TIMELINE_DIR}/id_mapping_l2.jsonl"
    echo ""
else
    echo -e "${YELLOW}[4/6] 跳过 L2 匿名化（--only l1）${NC}"
    echo -e "${YELLOW}[5/6] 跳过 L2 字段精简（--only l1）${NC}"
    echo -e "${YELLOW}[6/6] 跳过 L2 SFT 优化（--only l1）${NC}"
    echo ""
fi

# Step 7: 质量验证
echo -e "${YELLOW}[7/7] 数据质量验证...${NC}"
VALIDATE_LEVEL="all"
if [ "$ONLY" = "l1" ]; then
    VALIDATE_LEVEL="l1"
elif [ "$ONLY" = "l2" ]; then
    VALIDATE_LEVEL="l2"
fi

conda run -n CHAT_APP_DHA python scripts/compression/validate_sft_quality.py \
    --level "$VALIDATE_LEVEL" \
    --input-dir "${TIMELINE_DIR}" \
    --config configs/anonymization.yaml

VALIDATE_EXIT_CODE=$?
echo ""

if [ $VALIDATE_EXIT_CODE -ne 0 ]; then
    echo -e "${RED}[ERROR] 数据质量验证失败！${NC}"
    echo "请检查上述报告中的问题并修复后重新运行"
    exit 1
fi

echo -e "${GREEN}=== 完成 ===${NC}"
echo ""
echo "输出文件："
if [ -z "$ONLY" ] || [ "$ONLY" = "l1" ]; then
    echo "  - L1 本地训练: ${TIMELINE_DIR}/agent_sft_l1.jsonl"
fi
if [ -z "$ONLY" ] || [ "$ONLY" = "l2" ]; then
    echo "  - L2 云端训练: ${TIMELINE_DIR}/agent_sft_l2.jsonl"
fi
echo ""

# 显示文件大小
echo "文件大小："
if [ -z "$ONLY" ] || [ "$ONLY" = "l1" ]; then
    if [ -f "${TIMELINE_DIR}/agent_sft_l1.jsonl" ]; then
        L1_SIZE=$(du -h "${TIMELINE_DIR}/agent_sft_l1.jsonl" | cut -f1)
        L1_LINES=$(wc -l < "${TIMELINE_DIR}/agent_sft_l1.jsonl")
        echo "  - agent_sft_l1.jsonl: ${L1_SIZE} (${L1_LINES} 条消息)"
    fi
fi
if [ -z "$ONLY" ] || [ "$ONLY" = "l2" ]; then
    if [ -f "${TIMELINE_DIR}/agent_sft_l2.jsonl" ]; then
        L2_SIZE=$(du -h "${TIMELINE_DIR}/agent_sft_l2.jsonl" | cut -f1)
        L2_LINES=$(wc -l < "${TIMELINE_DIR}/agent_sft_l2.jsonl")
        echo "  - agent_sft_l2.jsonl: ${L2_SIZE} (${L2_LINES} 条消息)"
    fi
fi

echo ""
echo -e "${GREEN}✅ 所有步骤完成，数据质量验证通过！${NC}"
