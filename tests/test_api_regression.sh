#!/bin/bash
# tests/test_api_regression.sh
# server.py 重构回归测试脚本（来自 research/big_plan/plan_v2/server_refactoring_plan.md §3.1）
# 用法: bash tests/test_api_regression.sh
# 前置: uvicorn scripts.advisor.api.server:app --port 8787 已运行

BASE="${BASE:-http://localhost:8787}"

echo "=== API 回归测试 ($BASE) ==="

PASS=0
FAIL=0

check() {
    if [ $? -eq 0 ]; then
        PASS=$((PASS+1))
    else
        FAIL=$((FAIL+1))
    fi
}

# 1. Health
echo -n "[health] "
curl -s "$BASE/api/health" | python3 -c "import sys,json; d=json.load(sys.stdin); assert d['status']=='ok'; print('✅')" && check || { echo "❌"; FAIL=$((FAIL+1)); }

# 2. Chat Session CRUD
echo -n "[chat-create] "
SID=$(curl -s -X POST "$BASE/api/chat/sessions" -H "Content-Type: application/json" -d '{"agent_type":"neutral"}' | python3 -c "import sys,json; print(json.load(sys.stdin).get('id',''))" 2>/dev/null)
if [ -n "$SID" ]; then echo "✅ $SID"; PASS=$((PASS+1)); else echo "❌"; FAIL=$((FAIL+1)); fi

echo -n "[chat-list] "
curl -s "$BASE/api/chat/sessions" | python3 -c "import sys,json; d=json.load(sys.stdin); assert isinstance(d,list); print(f'✅ {len(d)} sessions')" && check || { echo "❌"; FAIL=$((FAIL+1)); }

if [ -n "$SID" ]; then
    echo -n "[chat-get] "
    curl -s "$BASE/api/chat/sessions/$SID" | python3 -c "import sys,json; d=json.load(sys.stdin); assert d['id']=='$SID'; print('✅')" && check || { echo "❌"; FAIL=$((FAIL+1)); }

    echo -n "[chat-delete] "
    curl -s -X DELETE "$BASE/api/chat/sessions/$SID" | python3 -c "import sys,json; d=json.load(sys.stdin); assert '已删除' in d.get('message',''); print('✅')" && check || { echo "❌"; FAIL=$((FAIL+1)); }
fi

# 3. Arena
echo -n "[arena-sessions] "
curl -s "$BASE/api/arena/sessions" | python3 -c "import sys,json; d=json.load(sys.stdin); assert isinstance(d,list); print(f'✅ {len(d)} sessions')" && check || { echo "❌"; FAIL=$((FAIL+1)); }

echo -n "[arena-stats] "
curl -s "$BASE/api/arena/stats" | python3 -c "import sys,json; d=json.load(sys.stdin); assert 'ratings' in d; print('✅')" && check || { echo "❌"; FAIL=$((FAIL+1)); }

# 4. Assessment
echo -n "[assessment] "
curl -s "$BASE/api/assessment/questions" | python3 -c "import sys,json; d=json.load(sys.stdin); assert 'phq2' in d and 'gad2' in d; print('✅')" && check || { echo "❌"; FAIL=$((FAIL+1)); }

# 5. Models
echo -n "[models] "
curl -s "$BASE/api/models" | python3 -c "import sys,json; d=json.load(sys.stdin); assert 'backends' in d or isinstance(d, list) or isinstance(d, dict); print('✅')" && check || { echo "❌"; FAIL=$((FAIL+1)); }

# 6. RAG
echo -n "[rag-stats] "
curl -s "$BASE/api/rag/stats" | python3 -c "import sys,json; d=json.load(sys.stdin); assert 'total_chunks' in d or 'total' in d; print('✅')" && check || { echo "❌"; FAIL=$((FAIL+1)); }

# 7. Safety
echo -n "[safety-hotlines] "
curl -s "$BASE/api/safety/hotlines" | python3 -c "import sys,json; d=json.load(sys.stdin); assert 'hotlines' in d; print('✅')" && check || { echo "❌"; FAIL=$((FAIL+1)); }

echo -n "[safety-consent] "
curl -s "$BASE/api/safety/consent" | python3 -c "import sys,json; d=json.load(sys.stdin); assert 'first_use_consent' in d; print('✅')" && check || { echo "❌"; FAIL=$((FAIL+1)); }

# 8. Pipeline
echo -n "[pipeline] "
curl -s "$BASE/api/pipeline/status" | python3 -c "import sys,json; d=json.load(sys.stdin); print('✅')" && check || { echo "❌"; FAIL=$((FAIL+1)); }

# 9. Data Stats
echo -n "[data-stats] "
curl -s "$BASE/api/data/stats" | python3 -c "import sys,json; d=json.load(sys.stdin); print('✅')" && check || { echo "❌"; FAIL=$((FAIL+1)); }

# 10. Review
echo -n "[review-items] "
curl -s "$BASE/api/review/items?agent_type=neutral" | python3 -c "import sys,json; d=json.load(sys.stdin); print('✅')" && check || { echo "❌"; FAIL=$((FAIL+1)); }

echo ""
echo "=== 回归测试完成: $PASS passed, $FAIL failed ==="
exit $FAIL
