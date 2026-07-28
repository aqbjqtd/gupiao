#!/bin/bash
# K线接口冒烟测试 — 检测 Top 20 股票 K 线接口是否正常
# 退出码: 0=全部通过, 1=有失败

BASE_URL="${KLINE_SMOKE_URL:-http://localhost:18080}"
FAIL=0
TOTAL=0
ERRORS=""

# 获取 Top 20 股票代码
CODES=$(curl -sf "${BASE_URL}/api/stocks" | python3 -c "
import sys, json
try:
    stocks = json.load(sys.stdin)
    for s in stocks:
        print(s['code'])
except: pass
" 2>/dev/null)

if [ -z "$CODES" ]; then
    echo "❌ 无法获取股票列表（API 不可达）"
    exit 1
fi

for code in $CODES; do
    TOTAL=$((TOTAL + 1))
    HTTP=$(curl -sf -o /dev/null -w "%{http_code}" "${BASE_URL}/api/stocks/${code}/kline" 2>&1)
    if [ "$HTTP" != "200" ]; then
        FAIL=$((FAIL + 1))
        ERRORS="${ERRORS}  ❌ ${code} → HTTP ${HTTP}\n"
    fi
done

if [ $FAIL -eq 0 ]; then
    echo "✅ K线冒烟测试通过：${TOTAL}/${TOTAL} 只股票正常"
    exit 0
else
    echo "⚠️ K线冒烟测试异常：${FAIL}/${TOTAL} 只失败"
    echo -e "$ERRORS"
    exit 1
fi
