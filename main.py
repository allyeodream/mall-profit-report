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
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

SHIPPING_COST_ACTUAL = 1980    # 실제 택배비 (부가세 포함)
SHIPPING_FEE_CHARGED = 3000    # 고객한테 받는 택배비
FREE_SHIPPING_MIN = 70000      # 무료배송 기준금액
PG_FEE_RATE = 0.022            # PG수수료 (나중에 디테일하게 수정)
VAT_RATE = 0.1                 # 부가세 10%

MONTHLY_FIXED_COSTS = {
    "카페24_이용료": 0,
    "기타_SaaS": 0,
}

MANUAL_COST = {
    3441: 22000,
}

def get_tokens_from_supabase():
    """Supabase에서 토큰 읽기"""
    print("SUPABASE_URL:", SUPABASE_URL)
    print("SUPABASE_KEY:", SUPABASE_KEY[:10] if SUPABASE_KEY else None)
    try:
        url = SUPABASE_URL + "/rest/v1/tokens?id=eq.1&select=access_token,refresh_token"
        headers = {
            "apikey": SUPABASE_KEY,
            "Authorization": "Bearer " + SUPABASE_KEY
        }
        r = requests.get(url, headers=headers)
        data = r.json()
        if data and len(data) > 0:
            return data[0]["access_token"], data[0]["refresh_token"]
    except Exception as e:
        print("⚠️ Supabase 토큰 읽기 실패: " + str(e))
    return None, None

def save_tokens_to_supabase(access_token, refresh_token):
    """Supabase에 토큰 저장"""
    try:
        url = SUPABASE_URL + "/rest/v1/tokens?id=eq.1"
        headers = {
            "apikey": SUPABASE_KEY,
            "Authorization": "Bearer " + SUPABASE_KEY,
            "Content-Type": "application/json",
            "Prefer": "return=minimal"
        }
        data = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "updated_at": datetime.now().isoformat()
        }
        r = requests.patch(url, headers=headers, json=data)
        if r.status_code in [200, 204]:
            print("✅ Supabase 토큰 저장 성공")
            return True
        else:
            print("⚠️ Supabase 토큰 저장 실패: " + str(r.text))
            return False
    except Exception as e:
        print("⚠️ Supabase 토큰 저장 오류: " + str(e))
        return False

def get_valid_token():
    access_token, refresh_token = get_tokens_from_supabase()

    if not refresh_token:
        access_token = os.environ.get("ACCESS_TOKEN")
        refresh_token = os.environ.get("REFRESH_TOKEN")

    if refresh_token:
        url = "https://" + MALL_ID + ".cafe24api.com/api/v2/oauth/token"
        try:
            response = requests.post(url,
                auth=(CLIENT_ID, CLIENT_SECRET),
                data={"grant_type": "refresh_token", "refresh_token": refresh_token}
            )
            data = response.json()
            if "access_token" in data:
                new_access = data["access_token"]
                new_refresh = data.get("refresh_token", refresh_token)
                save_tokens_to_supabase(new_access, new_refresh)
                print("✅ 토큰 갱신 성공")
                return new_access
        except Exception as e:
            print("⚠️ 토큰 갱신 오류: " + str(e))

    if access_token:
        print("⚠️ 기존 토큰으로 시도...")
        return access_token

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
        supply = float(item.get("supply_price") or 0)
        if supply == 0:
            supply = cost_map.get(product_no, 0)
        cost_with_vat = supply * (1 + VAT_RATE)
        total_cost += cost_with_vat * qty

    # 택배비: 7만원 이상이면 내가 1980원 부담, 미만이면 3000원 받고 1980원 냄
    if payment >= FREE_SHIPPING_MIN:
        shipping_net = SHIPPING_COST_ACTUAL          # 1980원 비용
    else:
        shipping_net = SHIPPING_COST_ACTUAL - SHIPPING_FEE_CHARGED  # -1020원 (이득)

    pg_fee = payment * PG_FEE_RATE
    profit = payment - total_cost - shipping_net - pg_fee

    return {
        "주문일": order.get("order_date", "")[:10],
        "주문번호": order.get("order_id", ""),
        "매출": payment,
        "원가_부가세포함": round(total_cost),
        "택배비_순": round(shipping_net),
        "PG수수료": round(pg_fee),
        "순수익": round(profit),
        "순이익률": round((profit / payment * 100), 1) if payment > 0 else 0
    }

def main():
    token = get_valid_token()
    if not token:
        print("오류: 토큰 없음")
        return

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
    total_shipping = sum(r["택배비_순"] for r in results)
    total_pg = sum(r["PG수수료"] for r in results)
    daily_fixed = get_daily_fixed_cost()
    total_profit = sum(r["순수익"] for r in results) - daily_fixed

    print("\n📊 [" + today_str + " 리포트]")
    print("💰 매출        " + f"{int(total_sales):>12,}원")
    print("📦 원가(부가세포함) " + f"{int(total_cost):>8,}원")
    print("🚚 택배비(순)   " + f"{int(total_shipping):>12,}원")
    print("💳 PG수수료     " + f"{int(total_pg):>12,}원")
    print("🏢 고정비용     " + f"{int(daily_fixed):>12,}원")
    print("─────────────────────────────")
    print("✅ 순수익       " + f"{int(total_profit):>12,}원")
    if total_sales > 0:
        print("📈 순이익률     " + f"{round(total_profit/total_sales*100, 1)}%")

if __name__ == "__main__":
    main()
