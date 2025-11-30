import gate_api
from gate_api.exceptions import ApiException, GateApiException
import time
import os
import datetime
import pandas as pd
import pandas_ta as ta

# --- 설정 ---
TESTNET_API_URL = "https://api-testnet.gateapi.io/api/v4"
API_KEY = "cb872a645c4afcdf0de204cf34eae039"
SECRET_KEY = "b9c41e0ef773e1504ec69159e3cceaea43d3adf6fd98f4fbeac1c443981eeeca"
SETTLE_CURRENCY = 'usdt'
CONTRACT = 'BTC_USDT'
LEVERAGE = 10
INTERVAL_SECONDS = 60 # 1분 간격으로 전략 실행
CANDLE_INTERVAL = '5m' # 5분봉 사용
CANDLE_LIMIT = 100 # 최근 100개 캔들 데이터 사용

# 전략 파라미터 (조정 가능)
ADX_THRESHOLD = 25 # ADX가 이 값보다 높으면 추세장, 낮으면 횡보장
FAST_EMA_PERIOD = 9
SLOW_EMA_PERIOD = 21
BB_PERIOD = 20
BB_STD = 2


def setup_gateio_client():
    config = gate_api.Configuration(host=TESTNET_API_URL, key=API_KEY, secret=SECRET_KEY)
    gate_api.Configuration.set_default(config)
    print(f"API Host: {config.host}")
    return config

def log_trade(order, contract):
    file_exists = os.path.isfile('trade_history.csv')
    with open('trade_history.csv', 'a', newline='') as f:
        if not file_exists:
            f.write("Timestamp,Type,Size,Price,Contract\n")
        
        # order.size는 문자열로 들어올 수 있으므로 float로 변환하여 부호 확인
        order_size_float = float(order.size)
        trade_type = "EXIT" if order.is_close else ("LONG" if order_size_float > 0 else "SHORT")
        
        # order.fill_price가 None일 경우를 대비하여 처리 (시장가 주문 즉시 체결시 필요)
        fill_price = order.fill_price if order.fill_price is not None else "N/A"

        log_entry = f"{datetime.datetime.now().isoformat()},{trade_type},{order.size},{fill_price},{contract}\n"
        f.write(log_entry)

def log_pnl(position):
    file_exists = os.path.isfile('pnl_over_time.csv')
    with open('pnl_over_time.csv', 'a', newline='') as f:
        if not file_exists:
            f.write("Timestamp,UnrealisedPNL,Size,EntryPrice,Contract\n")
        
        # position 객체가 None일 수 있으므로 확인
        if position and float(position.size) != 0:
            pnl = position.unrealised_pnl
            size = position.size
            entry_price = position.entry_price
        else:
            pnl, size, entry_price = 0, 0, 0
            
        log_entry = f"{datetime.datetime.now().isoformat()},{pnl},{size},{entry_price},{CONTRACT}\n"
        f.write(log_entry)

class GateioFuturesClient:
    def __init__(self, config):
        self.futures_api = gate_api.FuturesApi(gate_api.ApiClient(config))
        self.contract = CONTRACT

    def get_balance(self):
        try:
            account = self.futures_api.list_futures_accounts(settle=SETTLE_CURRENCY)
            return float(account.available)
        except GateApiException as e:
            print(f"잔고 조회 중 API 오류: {e.label}, {e.message}")
        except Exception as e:
            print(f"잔고 조회 중 예기치 않은 오류: {e}")
        return 0.0

    def get_position(self):
        try:
            position = self.futures_api.get_position(settle=SETTLE_CURRENCY, contract=self.contract)
            return position
        except GateApiException as e:
            if e.label == 'POSITION_NOT_FOUND':
                return None
            print(f"포지션 조회 중 API 오류: {e.label}, {e.message}")
        except Exception as e:
            print(f"포지션 조회 중 예기치 않은 오류: {e}")
        return None

    def get_order_book(self):
        try:
            return self.futures_api.list_futures_order_book(settle=SETTLE_CURRENCY, contract=self.contract)
        except GateApiException as e:
            print(f"오더북 조회 중 API 오류: {e.label}, {e.message}")
        except Exception as e:
            print(f"오더북 조회 중 예기치 않은 오류: {e}")
        return None

    def create_order(self, contract, size, price, tif='gtc', is_close=False):
        """
        선물 시장가 주문을 생성합니다. (tif='ioc' 즉시 체결 또는 취소)
        size는 양수면 LONG, 음수면 SHORT
        is_close=True이면 포지션 청산 주문
        """
        try:
            # API는 size를 정수 형태의 문자열로 받으므로, 항상 정수로 변환
            order_size = str(int(float(size)))
            if order_size == '0':
                print(f"  --> 주문 수량이 0이므로 주문을 생성하지 않습니다.")
                return None

            # 시장가 주문은 price를 0으로 설정
            order_req = gate_api.FuturesOrder(contract=contract, size=order_size, price='0', tif='ioc', is_close=is_close)
            created_order = self.futures_api.create_futures_order(settle=SETTLE_CURRENCY, futures_order=order_req)
            print(f"  --> 주문 생성: {contract}, Size: {order_size}, status: {created_order.status}, fill_price: {created_order.fill_price}")
            log_trade(created_order, contract)
            return created_order
        except GateApiException as e:
            print(f"  --> 주문 생성 중 API 오류: {e.label}, {e.message}")
        except Exception as e:
            print(f"  --> 주문 생성 중 예기치 않은 오류: {e}")
        return None

    def close_position(self, contract, current_position_size):
        try:
            if float(current_position_size) != 0:
                print(f"  --> 기존 포지션 청산 시도: {contract}, Size: {current_position_size}")
                # 현재 포지션의 반대 방향으로 주문을 넣어 청산
                close_size = -float(current_position_size)
                close_order = self.create_order(contract, close_size, price='0', is_close=True)
                if close_order and close_order.status == 'filled':
                    print(f"  --> 포지션 청산 완료. 청산 가격: {close_order.fill_price}")
                    return True
            return False
        except Exception as e:
            print(f"  --> 포지션 청산 중 오류: {e}")
            return False

    def get_candlesticks(self, contract, interval=CANDLE_INTERVAL, limit=CANDLE_LIMIT):
        try:
            klines = self.futures_api.list_futures_candlesticks(settle=SETTLE_CURRENCY, contract=contract, interval=interval, limit=limit)
            # Gate.io API는 가장 최근 캔들이 리스트의 첫 번째로 오므로, 시간 순서대로 정렬 (오름차순)
            klines.reverse()
            return klines
        except GateApiException as e:
            print(f"캔들 데이터 조회 중 API 오류: {e.label}, {e.message}")
        except Exception as e:
            print(f"캔들 데이터 조회 중 예기치 않은 오류: {e}")
        return []

class TradingBot:
    def __init__(self, config):
        self.client = GateioFuturesClient(config)
        self.contract = CONTRACT
        self.leverage = LEVERAGE
        self.adx_threshold = ADX_THRESHOLD
        self.fast_ema_period = FAST_EMA_PERIOD
        self.slow_ema_period = SLOW_EMA_PERIOD
        self.bb_period = BB_PERIOD
        self.bb_std = BB_STD
        
        # 이전 캔들 데이터 (이동평균 교차 감지용)
        self.prev_ema_fast = None
        self.prev_ema_slow = None
        
        # 잔고 및 레버리지 설정
        try:
            self.client.futures_api.update_position_leverage(
                settle=SETTLE_CURRENCY, contract=self.contract, leverage=str(self.leverage)
            )
            print(f"  레버리지 {self.leverage}x 설정 완료.")
        except GateApiException as e:
            print(f"  레버리지 설정 중 API 오류: {e.label}, {e.message}")
        except Exception as e:
            print(f"  레버리지 설정 중 예기치 않은 오류: {e}")

    def display_current_position(self):
        print("\n  --- 포지션 정보 조회 ---")
        position = self.client.get_position()
        log_pnl(position)
        if position and float(position.size) != 0:
            print(f"    계약: {position.contract}, 포지션 규모: {position.size} 계약, 진입 가격: {position.entry_price} USDT")
            print(f"    레버리지: {position.leverage}x, 마진: {float(position.margin):.4f} USDT")
            print(f"    미실현 손익: {float(position.unrealised_pnl):.4f} USDT, 실현 손익: {float(position.realised_pnl):.4f} USDT")
            return position
        else:
            print("    현재 활성화된 포지션이 없습니다.")
            return None

    def execute_trend_strategy(self, df, position_size, trade_size):
        last_adx = df['ADX_14'].iloc[-1]
        last_ema_fast = df[f'EMA_{self.fast_ema_period}'].iloc[-1]
        last_ema_slow = df[f'EMA_{self.slow_ema_period}'].iloc[-1]
        
        # 이전 캔들 데이터를 사용하여 교차 발생 여부 확인
        prev_ema_fast = df[f'EMA_{self.fast_ema_period}'].iloc[-2]
        prev_ema_slow = df[f'EMA_{self.slow_ema_period}'].iloc[-2]

        print(f"  [추세 전략] ADX: {last_adx:.2f}, EMA_Fast: {last_ema_fast:.2f}, EMA_Slow: {last_ema_slow:.2f}")

        # 롱 포지션 진입/청산
        if last_ema_fast > last_ema_slow and prev_ema_fast <= prev_ema_slow: # 골든 크로스 발생
            if position_size == 0:
                print(f"  --> 골든 크로스 발생! 롱 포지션 진입 시도. Size: {trade_size}")
                self.client.create_order(self.contract, trade_size, price='0')
            elif position_size < 0:
                print(f"  --> 골든 크로스 발생! 기존 숏 포지션 청산 후 롱 포지션 진입 시도. Size: {trade_size}")
                if self.client.close_position(self.contract, position_size):
                    self.client.create_order(self.contract, trade_size, price='0')
        
        # 숏 포지션 진입/청산
        elif last_ema_fast < last_ema_slow and prev_ema_fast >= prev_ema_slow: # 데드 크로스 발생
            if position_size == 0:
                print(f"  --> 데드 크로스 발생! 숏 포지션 진입 시도. Size: {-trade_size}")
                self.client.create_order(self.contract, -trade_size, price='0')
            elif position_size > 0:
                print(f"  --> 데드 크로스 발생! 기존 롱 포지션 청산 후 숏 포지션 진입 시도. Size: {-trade_size}")
                if self.client.close_position(self.contract, position_size):
                    self.client.create_order(self.contract, -trade_size, price='0')
        else:
            print("  --> 추세 전략: 매매 신호 없음.")


    def execute_mean_reversion_strategy(self, df, position_size, trade_size):
        last_adx = df['ADX_14'].dropna().iloc[-1]
        last_close = df['close'].iloc[-1]
        
        bb_std_float = float(self.bb_std)
        # 표준 컬럼 이름과 이상하게 생성된 컬럼 이름을 모두 준비
        std_bbl_col = f'BBL_{self.bb_period}_{bb_std_float}'
        std_bbm_col = f'BBM_{self.bb_period}_{bb_std_float}'
        std_bbu_col = f'BBU_{self.bb_period}_{bb_std_float}'
        
        mangled_bbl_col = f'BBL_{self.bb_period}_{bb_std_float}_{bb_std_float}'
        mangled_bbm_col = f'BBM_{self.bb_period}_{bb_std_float}_{bb_std_float}'
        mangled_bbu_col = f'BBU_{self.bb_period}_{bb_std_float}_{bb_std_float}'

        # DataFrame에 실제 있는 컬럼 이름으로 접근
        if mangled_bbl_col in df.columns:
            bbl_col, bbm_col, bbu_col = mangled_bbl_col, mangled_bbm_col, mangled_bbu_col
        else:
            bbl_col, bbm_col, bbu_col = std_bbl_col, std_bbm_col, std_bbu_col
            
        last_bb_lower = df[bbl_col].iloc[-1]
        last_bb_upper = df[bbu_col].iloc[-1]
        last_bb_middle = df[bbm_col].iloc[-1]
        
        # 이전 캔들 데이터를 사용하여 교차 발생 여부 확인
        prev_close = df['close'].iloc[-2]

        print(f"  [횡보 전략] ADX: {last_adx:.2f}, 현재가: {last_close:.2f}, BB_Lower: {last_bb_lower:.2f}, BB_Upper: {last_bb_upper:.2f}")

        # 롱 포지션 진입/청산
        if last_close < last_bb_lower and prev_close >= last_bb_lower: # 가격이 하단 밴드를 하향 돌파
            if position_size == 0:
                print(f"  --> 볼린저밴드 하단 이탈! 롱 포지션 진입 시도. Size: {trade_size}")
                self.client.create_order(self.contract, trade_size, price='0')
            elif position_size < 0: # 숏 포지션 보유 중이면 청산 후 롱 진입
                print(f"  --> 볼린저밴드 하단 이탈! 기존 숏 포지션 청산 후 롱 포지션 진입 시도. Size: {trade_size}")
                if self.client.close_position(self.contract, position_size):
                    self.client.create_order(self.contract, trade_size, price='0')
        elif position_size > 0 and last_close > last_bb_middle: # 롱 포지션 보유 중 가격이 중간 밴드를 상향 돌파
            print("  --> 볼린저밴드 중간선 돌파! 기존 롱 포지션 청산 시도.")
            self.client.close_position(self.contract, position_size)

        # 숏 포지션 진입/청산
        elif last_close > last_bb_upper and prev_close <= last_bb_upper: # 가격이 상단 밴드를 상향 돌파
            if position_size == 0:
                print(f"  --> 볼린저밴드 상단 이탈! 숏 포지션 진입 시도. Size: {-trade_size}")
                self.client.create_order(self.contract, -trade_size, price='0')
            elif position_size > 0: # 롱 포지션 보유 중이면 청산 후 숏 진입
                print(f"  --> 볼린저밴드 상단 이탈! 기존 롱 포지션 청산 후 숏 포지션 진입 시도. Size: {-trade_size}")
                if self.client.close_position(self.contract, position_size):
                    self.client.create_order(self.contract, -trade_size, price='0')
        elif position_size < 0 and last_close < last_bb_middle: # 숏 포지션 보유 중 가격이 중간 밴드를 하향 돌파
            print("  --> 볼린저밴드 중간선 하향 돌파! 기존 숏 포지션 청산 시도.")
            self.client.close_position(self.contract, position_size)
        else:
            print("  --> 횡보 전략: 매매 신호 없음.")

    def run(self):
        print(f"\n[{datetime.datetime.now()}] --- 선물 트레이딩 전략 실행 ---")
        
        position = self.display_current_position()
        position_size = float(position.size) if position else 0

        klines = self.client.get_candlesticks(self.contract, CANDLE_INTERVAL, CANDLE_LIMIT)
        if not klines or len(klines) < max(self.bb_period, self.slow_ema_period, 14, 2):
            print(f"  [{self.contract}] 기술적 지표 계산에 필요한 데이터 부족.")
            return

        df = pd.DataFrame([
            {'open': float(k.o), 'high': float(k.h), 'low': float(k.l), 'close': float(k.c), 'volume': float(k.v)}
            for k in klines
        ])

        df.ta.adx(length=14, append=True)
        df.ta.ema(length=self.fast_ema_period, append=True)
        df.ta.ema(length=self.slow_ema_period, append=True)
        df.ta.bbands(length=self.bb_period, std=self.bb_std, append=True)
        
        # 동적 주문 수량 계산
        trade_size = 0
        if position_size == 0:
            balance = self.client.get_balance()
            current_price = df['close'].iloc[-1]
            if balance > 0 and current_price > 0:
                # 사용 가능한 잔고의 95%를 증거금으로 사용
                margin_to_use = balance * 0.95
                # 레버리지를 적용한 총 포지션 가치
                target_nominal_value = margin_to_use * self.leverage
                # 1 계약(contract)의 가치는 0.0001 BTC. 이를 USDT로 환산.
                # 총 포지션 가치를 (현재가 * 0.0001)로 나누어 계약 수 계산
                # контракт 당 0.0001 BTC
                contract_value_in_usdt = current_price * 0.0001 
                if contract_value_in_usdt > 0:
                    trade_size = int(target_nominal_value / contract_value_in_usdt)

        print(f"  [주문 수량 계산] 사용 가능 잔고: {self.client.get_balance():.2f} USDT, 계산된 주문 수량: {trade_size} 계약")
        
        if position_size == 0 and trade_size < 1:
            print("  [경고] 계산된 주문 수량이 1계약보다 작아 주문을 실행하지 않습니다.")
            return

        bb_std_float = float(self.bb_std)
        required_cols_mangled = [
            'ADX_14', f'EMA_{self.fast_ema_period}', f'EMA_{self.slow_ema_period}', 
            f'BBL_{self.bb_period}_{bb_std_float}_{bb_std_float}', 
            f'BBU_{self.bb_period}_{bb_std_float}_{bb_std_float}', 
            f'BBM_{self.bb_period}_{bb_std_float}_{bb_std_float}'
        ]
        required_cols_std = [
            'ADX_14', f'EMA_{self.fast_ema_period}', f'EMA_{self.slow_ema_period}', 
            f'BBL_{self.bb_period}_{bb_std_float}', f'BBU_{self.bb_period}_{bb_std_float}', f'BBM_{self.bb_period}_{bb_std_float}'
        ]
        
        if not (all(col in df.columns for col in required_cols_mangled) or all(col in df.columns for col in required_cols_std)):
            print("  [오류] 일부 기술적 지표가 DataFrame에 추가되지 않았습니다. 컬럼:", df.columns.tolist())
            return
            
        last_adx = df['ADX_14'].dropna().iloc[-1]
        market_regime = "TRENDING" if last_adx > self.adx_threshold else "RANGING"

        print(f"  [시장 분석] ADX(14): {last_adx:.2f}, 현재 시장: {market_regime}")

        if market_regime == "TRENDING":
            print("  --> 추세 추종 전략 실행 중...")
            self.execute_trend_strategy(df, position_size, trade_size)
        else: # RANGING
            print("  --> 횡보장 역추세 전략 실행 중...")
            self.execute_mean_reversion_strategy(df, position_size, trade_size)

        print("  --- 전략 실행 완료 ---")

    def run_original_strategy(self):
        """
        기존의 단기 매매/스캘핑 전략 (주문장 및 VWAP 기반)
        """
        print(f"\n[{datetime.datetime.now()}] --- 선물 트레이딩 전략 실행 (기존 전략) ---")
        position = None
        try:
            position = self.client.futures_api.get_position(settle=SETTLE_CURRENCY, contract=self.contract)
        except GateApiException as e:
            if e.label != 'POSITION_NOT_FOUND': raise

        current_position_size = float(position.size) if position else 0

        # VWAP 신호 계산 (예시, 실제 로직은 더 복잡할 수 있음)
        order_book = self.client.get_order_book()
        if not order_book:
            print("  오더북 데이터 부족.")
            return

        # 간단한 VWAP 계산 (가중 평균 계산에 필요한 데이터가 제한적이므로 단순화)
        mid_price = (float(order_book.bids[0].p) + float(order_book.asks[0].p)) / 2
        best_ask = float(order_book.asks[0].p)
        best_bid = float(order_book.bids[0].p)
        
        # 여기서는 단순화를 위해 mid_price를 VWAP 신호로 가정
        # 실제 전략에서는 historical data와 volume을 사용하여 VWAP을 계산해야 함
        vwap_signal = mid_price # 임시 신호

        print(f"  현재가: {mid_price:.2f}, Best Ask: {best_ask:.2f}, Best Bid: {best_bid:.2f}")

        if current_position_size == 0:
            futures_account = self.client.futures_api.list_futures_accounts(settle=SETTLE_CURRENCY)
            available_balance_usdt = float(futures_account.available) if futures_account else 0
            
            # TODO: 실제 사용 가능한 마진과 레버리지를 고려하여 적절한 계약 수량 계산
            # 이 부분은 단순화를 위해 하드코딩된 trade_size를 사용하거나,
            # 포지션 가치를 기준으로 계산해야 합니다.
            
            # 예시: 사용 가능한 잔고의 5%를 마진으로 사용한다고 가정
            margin_to_use_percentage = 0.05
            margin_amount = available_balance_usdt * margin_to_use_percentage
            
            # target_size = (margin_amount * self.leverage) / mid_price
            # trade_size_calculated = max(0.001, round(target_size / 0.001) * 0.001) # 최소 0.001 BTC 계약

            calculated_size = self.trade_size # 기존의 고정된 trade_size 사용
            
            if vwap_signal > mid_price * 1.0001: # 단순 예시: 가격이 VWAP보다 높으면 롱
                print(f"  [신호: 매수] 신규 롱 포지션 진입 시도. Size: {calculated_size}")
                self.client.create_order(self.contract, calculated_size, price='0')
            elif vwap_signal < mid_price * 0.9999: # 단순 예시: 가격이 VWAP보다 낮으면 숏
                print(f"  [신호: 매도] 신규 숏 포지션 진입 시도. Size: {-calculated_size}")
                self.client.create_order(self.contract, -calculated_size, price='0')
            else:
                print("  매매 신호 없음 (VWAP).")
        elif current_position_size > 0: # 롱 포지션 보유 중
            # TODO: 익절/손절 로직 추가
            # 여기서는 단순히 특정 이익 또는 손실 시 청산하도록 가정
            print("  롱 포지션 보유 중... 익절/손절 대기.")
            # if best_bid > float(position.entry_price) * (1 + 0.001): # 0.1% 익절
            #     print("  롱 포지션 익절! 청산 시도.")
            #     self.client.close_position(self.contract, current_position_size)
            # elif best_bid < float(position.entry_price) * (1 - 0.002): # 0.2% 손절
            #     print("  롱 포지션 손절! 청산 시도.")
            #     self.client.close_position(self.contract, current_position_size)

        elif current_position_size < 0: # 숏 포지션 보유 중
            # TODO: 익절/손절 로직 추가
            print("  숏 포지션 보유 중... 익절/손절 대기.")
            # if best_ask < float(position.entry_price) * (1 - 0.001): # 0.1% 익절
            #     print("  숏 포지션 익절! 청산 시도.")
            #     self.client.close_position(self.contract, current_position_size)
            # elif best_ask > float(position.entry_price) * (1 + 0.002): # 0.2% 손절
            #     print("  숏 포지션 손절! 청산 시도.")
            #     self.client.close_position(self.contract, current_position_size)
        print("  --- 전략 실행 완료 (기존 전략) ---")

if __name__ == "__main__":
    config = setup_gateio_client()
    print("\n--- Gate.io 선물 자동매매 봇 시작 (Testnet) ---")
    print(f"정산 화폐: {SETTLE_CURRENCY}, 계약: {CONTRACT}, 레버리지: {LEVERAGE}x")
    
    bot = TradingBot(config)
    while True:
        bot.run() # 새롭게 구현된 하이브리드 전략 실행
        print(f"\n{INTERVAL_SECONDS}초 대기 중...")
        time.sleep(INTERVAL_SECONDS)