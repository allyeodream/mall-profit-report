import requests
import json
import os
from datetime import datetime, timedelta

# =============================
# 설정값
# =============================
CLIENT_ID = "SzSf7z1hDSMW7vPXHOExoD"
CLIENT_SECRET = "wvQ7TNzkEl1itP1MTSbWVD"
MALL_ID = "tpgus432"
RAILWAY_API_TOKEN = os.environ.get("RAILWAY_API_TOKEN")
SERVICE_ID = os.environ.get("RAILWAY_SERVICE_ID")
ENVIRONMENT_ID = os.environ.get("RAILWAY_ENVIRONMENT_ID")

SHIPPING_COST = 3000
FREE_SHIPPING_MIN = 70000
PG_FEE_RATE = 0.022
VAT_RATE = 0.1

MONTHLY_FIXED_COSTS = {
    "카페24_이용료": 0,
    "기타_SaaS": 0,
}

MANUAL_COST = {
    3441: 22000,
}

def update_railway_variable(key, value):
    """Railway 환경변수 자동 업데이트"""
    if not RAILWAY_API_TOKEN or not SERVICE_ID or not ENVIRONMENT_ID:
        print("⚠️ Railway API 설정 없음 - 변수 업데이트 건너뜀")
        return False

    query = """
    mutation variableUpsert($input: VariableUpsertInput!) {
        variableUpsert(input: $input)
    }
    """
    variables = {
        "input": {
            "serviceId": SERVICE_ID,
            "environmentId": ENVIRONMENT_ID,
            "name": key,
            "value": value
        }
    }
    headers = {
        "Authorization": "Bearer " + RAILWAY_API_TOKEN,
        "Content-Type": "application/json"
    }
    r = requests.post(
        "https://backboard.railway.com/graphql/v2",
        json={"query": query, "variables": variables},
        headers=headers
    )
    if r.status_code == 200:
        print("✅ Railway 변수 업데이트 성공: " + key)
        return True
    else:
        print("❌ Railway 변수 업데이트 실패: " + str(r.text))
        return False

def get_tokens():
    access = os.environ.get("ACCESS_TOKEN")
    refresh = os.environ.get("REFRESH_TOKEN")
    return access, refresh

def refresh_access_token(refresh_token):
    url = "https://" + MALL_ID + ".cafe24api.com/api/v2/oauth/token"
    response = requests.post(url,
        auth=(CLIENT_ID, CLIENT_SECRET),
        data={"grant_type": "refresh_token", "refresh_token": refresh_token}
    )
    data = response.json()
    if "access_token" in data:
        new_access = data["access_token"]
        new_refresh = data.get("refresh_token", refresh_token)
        # Railway 변수 자동 업데이트
        update_railway_variable("ACCESS_TOKEN", new_access)
        update_railway_variable("REFRESH_TOKEN", new_refresh)
        return new_access
    return None

def get_products(token):
    url = "https://" + MALL_ID + ".cafe24api.com/api/v2/admin/products"
    headers = {
        "Authorization": "Bearer " + token,
        "Content-Type": "application/json",
        "X-Cafe24-Api-Version": "2025-12-01"
    }
    params = {"limit": 200, "fields": "product_no,product_name,price,supply_price"}
    r = requests.get(url, headers=headers, params=params)
    products = r.json().get("products", [])
    cost_map = {}
    for p in products:
        no = p["product_no"]
        supply = float(p.get("supply_price") or 0)
        cost_map[no] = MANUAL_COST.get(no, supply)
    return cost_map

def get_orders(token, days=1):
    today = datetime.now()
    start = (today - timedelta(days=days)).strftime("%Y-%m-%d")
    end = today.strftime("%Y-%m-%d")
    url = "https://" + MALL_ID + ".cafe24api.com/api/v2/admin/orders"
    headers = {
        "Authorization": "Bearer " + token,
        "Content-Type": "application/json",
        "X-Cafe24-Api-Version": "2025-12-01"
    }
    params = {"start_date": start, "end_date": end, "limit": 100}
    r = requests.get(url, headers=headers, params=params)
    return r.json().get("orders", [])

def get_order_items(token, order_id):
    url = "https://" + MALL_ID + ".cafe24api.com/api/v2/admin/orders/" + str(order_id) + "/items"
    headers = {
        "Authorization": "Bearer " + token,
        "Content-Type": "application/json",
        "X-Cafe24-Api-Version": "2025-12-01"
    }
    r = requests.get(url, headers=headers)
    return r.json().get("items", [])

def get_daily_fixed_cost():
    total = sum(MONTHLY_FIXED_COSTS.values())
    return round(total / 30)

def calc_profit(order, items, cost_map):
    payment = float(order.get("payment_amount") or 0)
    if payment == 0:
        return None

    total_cost = 0
    for item in items:
        product_no = item.get("product_no")
        qty = int(item.get("quantity") or 1)
        cost = cost_map.get(product_no, 0)
        cost_with_vat = cost * (1 + VAT_RATE)
        total_cost += cost_with_vat * qty

    shipping = 0 if payment >= FREE_SHIPPING_MIN else SHIPPING_COST
    pg_fee = payment * PG_FEE_RATE
    profit = payment - total_cost - shipping - pg_fee

    return {
        "주문일": order.get("order_date", "")[:10],
        "주문번호": order.get("order_id", ""),
        "매출": payment,
        "원가_부가세포함": round(total_cost),
        "택배비": shipping,
        "PG수수료": round(pg_fee),
        "순수익": round(profit),
        "순이익률": round((profit / payment * 100), 1) if payment > 0 else 0
    }

def main():
    _, refresh_token = get_tokens()

    if not refresh_token:
        print("오류: REFRESH_TOKEN 환경변수가 없습니다.")
        return

    print("토큰 갱신 중...")
    token = refresh_access_token(refresh_token)
    if not token:
        print("오류: 토큰 갱신 실패")
        return

    print("✅ 토큰 갱신 성공")
    print("상품 원가 불러오는 중...")
    cost_map = get_products(token)

    print("오늘 주문 데이터 불러오는 중...")
    orders = get_orders(token, days=1)

    results = []
    for order in orders:
        items = get_order_items(token, order["order_id"])
        result = calc_profit(order, items, cost_map)
        if result:
            results.append(result)

    today_str = datetime.now().strftime("%m월 %d일")
    total_sales = sum(r["매출"] for r in results)
    total_cost = sum(r["원가_부가세포함"] for r in results)
    total_shipping = sum(r["택배비"] for r in results)
    total_pg = sum(r["PG수수료"] for r in results)
    daily_fixed = get_daily_fixed_cost()
    total_profit = sum(r["순수익"] for r in results) - daily_fixed

    print("\n📊 [" + today_str + " 리포트]")
    print("💰 매출        " + f"{int(total_sales):>12,}원")
    print("📦 원가(부가세포함) " + f"{int(total_cost):>8,}원")
    print("🚚 택배비       " + f"{int(total_shipping):>12,}원")
    print("💳 PG수수료     " + f"{int(total_pg):>12,}원")
    print("🏢 고정비용     " + f"{int(daily_fixed):>12,}원")
    print("─────────────────────────────")
    print("✅ 순수익       " + f"{int(total_profit):>12,}원")
    if total_sales > 0:
        print("📈 순이익률     " + f"{round(total_profit/total_sales*100, 1)}%")

if __name__ == "__main__":
    main()
