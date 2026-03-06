# v9
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

SHIPPING_COST_ACTUAL = 1980
SHIPPING_FEE_CHARGED = 3000
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

def get_tokens_from_supabase():
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

def get_orders(token, date_str):
    """결제일 기준으로 ±1일 범위에서 가져온 후 결제일로 필터링"""
    url = "https://" + MALL_ID + ".cafe24api.com/api/v2/admin/orders"
    headers = {
        "Authorization": "Bearer " + token,
        "Content-Type": "application/json",
        "X-Cafe24-Api-Version": "2025-12-01"
    }
    target = datetime.strptime(date_str, "%Y-%m-%d")
    start = (target - timedelta(days=1)).strftime("%Y-%m-%d")
    end = (target + timedelta(days=1)).strftime("%Y-%m-%d")

    params = {
        "start_date": start,
        "end_date": end,
        "limit": 100,
    }
    r = requests.get(url, headers=headers, params=params)
    all_orders = r.json().get("orders", [])

    # 결제일 기준으로 필터링
    filtered = [
        o for o in all_orders
        if o.get("payment_date", "")[:10] == date_str
    ]

    # 취소 주문 분리
    normal = [o for o in filtered if o.get("canceled") != "T"]
    canceled = [o for o in filtered if o.get("canceled") == "T"]

    print("결제일 기준 주문수: " + str(len(normal)) + "건 (취소: " + str(len(canceled)) + "건)")
    return normal, canceled

def get_refunds(token, date_str):
    try:
        url = "https://" + MALL_ID + ".cafe24api.com/api/v2/admin/refunds"
        headers = {
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json",
            "X-Cafe24-Api-Version": "2025-12-01"
        }
        params = {
            "start_date": date_str,
            "end_date": date_str,
            "limit": 100
        }
        r = requests.get(url, headers=headers, params=params, timeout=10)
        refunds = r.json().get("refunds", [])
        total_refund = sum(float(rf.get("actual_refund_amount") or 0) for rf in refunds)
        print("환불 건수: " + str(len(refunds)) + "건, 금액: " + str(round(total_refund)))
        return round(total_refund), len(refunds)
    except Exception as e:
        print("⚠️ 환불 데이터 오류: " + str(e))
        return 0, 0

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

def calc_payment(order):
    """실결제금액 계산
    - 일반 결제: payment_amount
    - 0원 결제(네이버페이 선불금): order_price_amount + shipping_fee
    - 취소 주문: initial_order_amount 기준
    """
    payment = float(order.get("payment_amount") or 0)
    if payment > 0:
        return payment

    # 취소 주문은 initial_order_amount 사용
    if order.get("canceled") == "T":
        initial = order.get("initial_order_amount", {})
        initial_pay = float(initial.get("payment_amount") or 0)
        if initial_pay > 0:
            return initial_pay
        return float(initial.get("order_price_amount") or 0) + float(initial.get("shipping_fee") or 0)

    # 네이버페이 선불금 등 0원 결제
    actual = order.get("actual_order_amount", {})
    order_price = float(actual.get("order_price_amount") or 0)
    shipping_fee = float(actual.get("shipping_fee") or 0)
    return order_price + shipping_fee

def calc_profit(order, items, cost_map):
    payment = calc_payment(order)
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

    actual = order.get("actual_order_amount", {})
    shipping_fee = float(actual.get("shipping_fee") or 0)

    if shipping_fee == 0:
        shipping_net = SHIPPING_COST_ACTUAL
    else:
        shipping_net = SHIPPING_COST_ACTUAL - shipping_fee

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

    yesterday = datetime.now() - timedelta(days=1)
    yesterday_str = yesterday.strftime("%Y-%m-%d")
    yesterday_display = yesterday.strftime("%m월 %d일")

    print("상품 원가 불러오는 중...")
    cost_map = get_products(token)

    print("어제(" + yesterday_display + ") 주문 데이터 불러오는 중...")
    normal_orders, canceled_orders = get_orders(token, yesterday_str)

    print("환불 데이터 불러오는 중...")
    total_refund, refund_count = get_refunds(token, yesterday_str)

    # 취소 금액 계산
    total_cancel = sum(calc_payment(o) for o in canceled_orders)
    cancel_count = len(canceled_orders)
    print("취소 건수: " + str(cancel_count) + "건, 금액: " + str(int(total_cancel)))

    # 정상 주문 처리
    results = []
    for order in normal_orders:
        try:
            items = get_order_items(token, order["order_id"])
            result = calc_profit(order, items, cost_map)
            if result:
                results.append(result)
        except Exception as e:
            print("⚠️ 주문 처리 오류: " + str(e))
            continue

    print("주문 처리 완료: " + str(len(results)) + "건")

    total_sales = sum(r["매출"] for r in results)
    total_cost = sum(r["원가_부가세포함"] for r in results)
    total_shipping = sum(r["택배비_순"] for r in results)
    total_pg = sum(r["PG수수료"] for r in results)
    daily_fixed = get_daily_fixed_cost()

    # 순매출 = 매출 - 환불 - 취소
    net_sales = total_sales - total_refund - total_cancel
    total_profit = net_sales - total_cost - total_shipping - total_pg - daily_fixed

    print("\n📊 [" + yesterday_display + " 리포트]")
    print("💰 매출        " + f"{int(total_sales):>12,}원  ({len(results)}건)")
    print("↩️  환불        " + f"{int(total_refund):>12,}원  ({refund_count}건)")
    print("❌ 취소        " + f"{int(total_cancel):>12,}원  ({cancel_count}건)")
    print("💰 순매출      " + f"{int(net_sales):>12,}원")
    print("─────────────────────────────")
    print("📦 원가(부가세포함) " + f"{int(total_cost):>8,}원")
    print("🚚 택배비(순)   " + f"{int(total_shipping):>12,}원")
    print("💳 PG수수료     " + f"{int(total_pg):>12,}원")
    print("🏢 고정비용     " + f"{int(daily_fixed):>12,}원")
    print("─────────────────────────────")
    print("✅ 순수익       " + f"{int(total_profit):>12,}원")
    if net_sales > 0:
        print("📈 순이익률     " + f"{round(total_profit/net_sales*100, 1)}%")

if __name__ == "__main__":
    main()
