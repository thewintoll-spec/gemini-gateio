import gate_api
from gate_api.exceptions import ApiException, GateApiException
import time
import os
import datetime

# gateio_info.txt에서 가져온 정보
TESTNET_API_URL = "https://api-testnet.gateapi.io/api/v4"
API_KEY = "cb872a645c4afcdf0de204cf34eae039"
SECRET_KEY = "b9c41e0ef773e1504ec69159e3cceaea43d3adf6fd98f4fbeac1c443981eeeca"

# 거래 설정
CURRENCY_PAIR = 'BTC_USDT'
TRADE_AMOUNT_USDT = 10  # 매매에 사용할 USDT 금액 (Testnet이므로 작은 금액으로 테스트)
INTERVAL_SECONDS = 60 # 1분마다 전략 실행

# 전략 관련 (BNF 괴리율 전략)
# 25주기 이동평균선을 기준으로 가격의 괴리율을 이용해 매매합니다.
BNF_MA_PERIOD = 25  # BNF가 주로 참고한 것으로 알려진 25주기 이동평균
DEVIATION_BUY_THRESHOLD = -5.0  # MA 대비 -5% 이하로 가격이 하락하면 매수
DEVIATION_SELL_THRESHOLD = -1.0 # 매수 후, 가격이 MA 대비 -1% 수준까지 회복하면 매도
klines_data = [] # 캔들 데이터를 저장할 리스트

def setup_gateio_client():
    """
    Gate.io API 클라이언트를 설정하고 반환합니다.
    """
    config = gate_api.Configuration(
        host=TESTNET_API_URL,
        key=API_KEY,
        secret=SECRET_KEY
    )
    gate_api.Configuration.set_default(config)
    print(f"API Host: {config.host}")
    return config

def get_klines(spot_api, currency_pair, interval='1m', limit=100):
    """
    캔들 데이터를 가져옵니다.
    """
    try:
        # get_candlesticks는 Unix 타임스탬프를 사용합니다.
        # Gate.io API는 interval에 '1m', '5m', '15m', '30m', '1h', '4h', '8h', '1d', '7d' 등을 지원합니다.
        klines = spot_api.list_candlesticks(currency_pair=currency_pair, interval=interval, limit=limit)
        return klines
    except GateApiException as e:
        print(f"Gate.io API 오류 발생 (get_klines): {e.label}, {e.message}")
        return None
    except Exception as e:
        print(f"캔들 데이터 가져오는 중 오류 발생: {e}")
        return None

def calculate_ma(data, period):
    """
    이동 평균을 계산합니다.
    데이터는 종가(close price) 리스트여야 합니다.
    """
    if len(data) < period:
        return None
    return sum(data[-period:]) / period

def execute_trade_strategy(config):
    """
    BNF 괴리율 트레이딩 전략을 실행하고 주문을 제출합니다.
    """
    spot_api = gate_api.SpotApi(gate_api.ApiClient(config))

    print(f"\n[{datetime.datetime.now()}] --- BNF 괴리율 전략 실행 ---")

    try:
        # 1. 최신 캔들 데이터 가져오기
        all_klines = get_klines(spot_api, CURRENCY_PAIR, interval='1m', limit=BNF_MA_PERIOD + 5) # 여유분 포함
        if not all_klines or len(all_klines) < BNF_MA_PERIOD:
            print(f"  [{CURRENCY_PAIR}] 이동 평균 계산에 필요한 캔들 데이터 부족 ({len(all_klines) if all_klines else 0}/{BNF_MA_PERIOD})")
            return

        # 종가(close price)만 추출하여 역순으로 정렬 (최신 데이터가 마지막에 오도록)
        close_prices = [float(kline[2]) for kline in reversed(all_klines)]

        # 2. 25주기 이동 평균 계산
        ma25 = calculate_ma(close_prices, BNF_MA_PERIOD)

        if ma25 is None:
            print(f"  [{CURRENCY_PAIR}] 이동 평균 계산 실패 (데이터 부족 또는 오류)")
            return

        current_price = close_prices[-1]
        
        # 3. 괴리율 계산
        deviation = ((current_price - ma25) / ma25) * 100
        print(f"  [{CURRENCY_PAIR}] 현재가: {current_price:.2f}, 25-MA: {ma25:.2f}, 괴리율: {deviation:.2f}%")

        # 4. 매매 신호 확인
        # 잔고 조회
        spot_accounts = spot_api.list_spot_accounts()
        usdt_balance_obj = [acc for acc in spot_accounts if acc.currency == 'USDT']
        btc_balance_obj = [acc for acc in spot_accounts if acc.currency == 'BTC']
        
        usdt_balance = float(usdt_balance_obj[0].available) if usdt_balance_obj else 0.0
        btc_balance = float(btc_balance_obj[0].available) if btc_balance_obj else 0.0

        print(f"  현재 잔고: USDT {usdt_balance:.2f}, BTC {btc_balance:.8f}")

        # 매수 신호: 괴리율이 매수 임계치(-5%) 이하이고, 매수할 USDT가 충분할 때
        if deviation <= DEVIATION_BUY_THRESHOLD and usdt_balance >= TRADE_AMOUNT_USDT:
            buy_amount_btc = TRADE_AMOUNT_USDT / current_price
            
            order = gate_api.Order(
                currency_pair=CURRENCY_PAIR,
                side='buy',
                amount=str(round(buy_amount_btc, 8)),
                price=str(current_price),
                type='market'
            )
            
            # 실제 주문 시 주석 해제
            # real_order = spot_api.create_order(order)
            print(f"  [매수 신호 발생] 괴리율({deviation:.2f}%) <= 임계치({DEVIATION_BUY_THRESHOLD}%)")
            print(f"  > 매수 주문 시도: {TRADE_AMOUNT_USDT} USDT ({buy_amount_btc:.8f} BTC)")
            # print(f"  매수 주문 제출: {real_order}")

        # 매도 신호: 괴리율이 매도 임계치(-1%) 이상으로 회복했고, 판매할 BTC가 충분할 때
        elif deviation >= DEVIATION_SELL_THRESHOLD and btc_balance * current_price >= TRADE_AMOUNT_USDT:
            sell_amount_btc = btc_balance
            
            order = gate_api.Order(
                currency_pair=CURRENCY_PAIR,
                side='sell',
                amount=str(round(sell_amount_btc, 8)),
                price=str(current_price),
                type='market'
            )
            
            # 실제 주문 시 주석 해제
            # real_order = spot_api.create_order(order)
            print(f"  [매도 신호 발생] 괴리율({deviation:.2f}%) >= 임계치({DEVIATION_SELL_THRESHOLD}%)")
            print(f"  > 매도 주문 시도: {sell_amount_btc:.8f} BTC (전량)")
            # print(f"  매도 주문 제출: {real_order}")
        else:
            print("  매매 신호 없음 (관망)")

    except GateApiException as e:
        print(f"  Gate.io API 오류 발생 (execute_trade_strategy): {e.label}, {e.message}")
    except ApiException as e:
        print(f"  API 오류 발생 (execute_trade_strategy): {e}")
    except Exception as e:
        print(f"  예기치 않은 오류 발생 (execute_trade_strategy): {e}")

if __name__ == "__main__":
    config = setup_gateio_client()

    print("\n--- Gate.io 자동매매 봇 시작 (Testnet) ---")
    print(f"매매 쌍: {CURRENCY_PAIR}")
    print(f"실행 주기: {INTERVAL_SECONDS}초")
    print("주의: 실제 주문이 아닌, 시뮬레이션 및 로깅만 수행합니다 (주석 처리된 주문 제출 코드 확인).")
    print("실제 주문을 원하시면 'order_api.create_order(order)' 주석을 해제하세요.")

    while True:
        execute_trade_strategy(config)
        print(f"\n{INTERVAL_SECONDS}초 대기 중...")
        time.sleep(INTERVAL_SECONDS)
