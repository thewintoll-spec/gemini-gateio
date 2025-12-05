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
LEVERAGE = 10
INTERVAL_SECONDS = 60 # 매매 로직 실행 주기 (초)
CANDLE_INTERVAL = '5m' # 5분봉 사용
CANDLE_LIMIT = 100 # 최근 100개 캔들 데이터 사용
TOP_N_CONTRACTS = 10 # 거래량 상위 N개 코인을 거래 대상으로 선정

# 전략 파라미터
ADX_THRESHOLD = 25
FAST_EMA_PERIOD = 9
SLOW_EMA_PERIOD = 21
BNF_EMA_PERIOD = 25
BNF_DEVIATION_PERCENT = 1.5

def setup_gateio_client():
    config = gate_api.Configuration(host=TESTNET_API_URL, key=API_KEY, secret=SECRET_KEY)
    gate_api.Configuration.set_default(config)
    print(f"API Host: {config.host}")
    return config

def get_top_traded_contracts(futures_api, settle, n=10):
    """24시간 거래대금 기준 상위 N개 코인 목록을 반환합니다."""
    print(f"\n--- 거래량 상위 {n}개 코인 조회 시작 ---")
    try:
        all_tickers = futures_api.list_futures_tickers(settle=settle)
        # 24시간 거래대금(volume_24h_usd)을 기준으로 내림차순 정렬 (None 값은 0으로 처리)
        sorted_tickers = sorted(all_tickers, key=lambda x: float(x.volume_24h_usd or 0), reverse=True)
        
        # ASCII 이름만 가진 코인을 필터링
        top_n_names = []
        for t in sorted_tickers:
            if t.contract.isascii():
                top_n_names.append(t.contract)
            if len(top_n_names) == n:
                break
        
        print(f"거래량 상위 {n}개 코인 (ASCII 필터링): {top_n_names}")
        return top_n_names
    except ApiException as e:
        print(f"Gate.io API 오류 (상위 코인 조회): {e}")
    except Exception as e:
        print(f"오류 (상위 코인 조회): {e}")
    return []

def log_trade(order, contract):
    file_exists = os.path.isfile('trade_history.csv')
    with open('trade_history.csv', 'a', newline='', encoding='utf-8') as f:
        if not file_exists:
            f.write("Timestamp,Type,Size,Price,Contract\n")
        order_size_float = float(order.size)
        trade_type = "EXIT" if order.is_close else ("LONG" if order_size_float > 0 else "SHORT")
        fill_price = order.fill_price if order.fill_price is not None else "N/A"
        log_entry = f"{datetime.datetime.now().isoformat()},{trade_type},{order.size},{fill_price},{contract}\n"
        f.write(log_entry)

def log_pnl(position, contract):
    file_exists = os.path.isfile('pnl_over_time.csv')
    with open('pnl_over_time.csv', 'a', newline='', encoding='utf-8') as f:
        if not file_exists:
            f.write("Timestamp,UnrealisedPNL,Size,EntryPrice,Contract\n")
        if position and float(position.size) != 0:
            pnl, size, entry_price = (position.unrealised_pnl, position.size, position.entry_price)
        else:
            pnl, size, entry_price = 0, 0, 0
        log_entry = f"{datetime.datetime.now().isoformat()},{pnl},{size},{entry_price},{contract}\n"
        f.write(log_entry)

class GateioFuturesClient:
    def __init__(self, config):
        self.futures_api = gate_api.FuturesApi(gate_api.ApiClient(config))

    def get_balance(self):
        try:
            account = self.futures_api.list_futures_accounts(settle=SETTLE_CURRENCY)
            return float(account.available)
        except Exception as e:
            print(f"잔고 조회 중 오류: {e}")
            return 0.0

    def get_position(self, contract):
        try:
            return self.futures_api.get_position(settle=SETTLE_CURRENCY, contract=contract)
        except GateApiException as e:
            if e.label != 'POSITION_NOT_FOUND':
                print(f"{contract} 포지션 조회 중 API 오류: {e.label}")
        except Exception as e:
            print(f"{contract} 포지션 조회 중 오류: {e}")
        return None

    def create_order(self, contract, size, is_close=False):
        try:
            order_size = str(int(float(size)))
            order_req = gate_api.FuturesOrder(contract=contract, size=order_size, price='0', tif='ioc', is_close=is_close)
            created_order = self.futures_api.create_futures_order(settle=SETTLE_CURRENCY, futures_order=order_req)
            print(f"  --> 주문 생성: {contract}, Size: {order_size}, status: {created_order.status}")
            log_trade(created_order, contract)
            return created_order
        except Exception as e:
            print(f"  --> {contract} 주문 생성 중 오류: {e}")
        return None

    def close_position(self, contract):
        try:
            print(f"  --> {contract} 포지션 청산 시도...")
            order_req = gate_api.FuturesOrder(contract=contract, size="0", tif='ioc', is_close=True)
            created_order = self.futures_api.create_futures_order(settle=SETTLE_CURRENCY, futures_order=order_req)
            log_trade(created_order, contract)
            return created_order
        except Exception as e:
            print(f"  --> {contract} 포지션 청산 중 오류: {e}")
        return None
        
    def get_candlesticks(self, contract):
        try:
            klines = self.futures_api.list_futures_candlesticks(settle=SETTLE_CURRENCY, contract=contract, interval=CANDLE_INTERVAL, limit=CANDLE_LIMIT)
            klines.reverse()
            return klines
        except Exception as e:
            print(f"캔들 데이터 조회 중 오류 ({contract}): {e}")
        return []

class TradingBot:
    def __init__(self, config, contracts_to_trade):
        self.client = GateioFuturesClient(config)
        self.contracts = contracts_to_trade
        self.leverage = LEVERAGE
        self.adx_threshold = ADX_THRESHOLD
        self.fast_ema_period = FAST_EMA_PERIOD
        self.slow_ema_period = SLOW_EMA_PERIOD
        self.bnf_ema_period = BNF_EMA_PERIOD
        self.bnf_deviation = BNF_DEVIATION_PERCENT

        print("\n--- 레버리지 설정 시작 ---")
        for contract in self.contracts:
            try:
                self.client.futures_api.update_position_leverage(
                    settle=SETTLE_CURRENCY, contract=contract, leverage=str(self.leverage)
                )
                print(f"  {contract}: 레버리지 {self.leverage}x 설정 완료.")
            except Exception as e:
                print(f"  {contract}: 레버리지 설정 중 오류: {e}")
        print("--- 레버리지 설정 완료 ---\n")

    def run_strategy_for_contract(self, contract, total_open_positions):
        print(f"--- [{contract}] 트레이딩 전략 실행 ---")
        
        position = self.client.get_position(contract)
        log_pnl(position, contract)
        position_size = float(position.size) if position else 0

        klines = self.client.get_candlesticks(contract)
        if not klines or len(klines) < max(self.bnf_ema_period, self.slow_ema_period, 14):
            print(f"  [{contract}] 기술적 지표 계산에 필요한 데이터 부족.")
            return

        df = pd.DataFrame([{'open': float(k.o), 'high': float(k.h), 'low': float(k.l), 'close': float(k.c), 'volume': float(k.v)} for k in klines])
        df.ta.adx(length=14, append=True)
        df.ta.ema(length=self.fast_ema_period, append=True)
        df.ta.ema(length=self.slow_ema_period, append=True)
        df.ta.ema(length=self.bnf_ema_period, append=True)
        
        required_cols = ['ADX_14', f'EMA_{self.fast_ema_period}', f'EMA_{self.slow_ema_period}', f'EMA_{self.bnf_ema_period}']
        if not all(col in df.columns for col in required_cols):
            print(f"  [{contract}] 오류: 일부 기술적 지표가 DataFrame에 추가되지 않았습니다.")
            return

        adx_series = df['ADX_14'].dropna()
        if adx_series.empty:
            print(f"  [{contract}] ADX 계산에 유효한 데이터가 부족하여 건너뜁니다.")
            return
            
        last_adx = adx_series.iloc[-1]
        market_regime = "TRENDING" if last_adx > self.adx_threshold else "RANGING"
        print(f"  [시장 분석] ADX(14): {last_adx:.2f}, 현재 시장: {market_regime}")

        # 포지션이 있을 경우, 청산 로직을 먼저 확인
        if position_size != 0:
            if market_regime == "TRENDING":
                self.execute_trend_exit(df, contract, position_size)
            else:
                self.execute_bnf_exit(df, contract, position_size)
        
        # 포지션이 없을 경우, 진입 로직 확인
        else:
            if total_open_positions >= 2:
                print("  [포트폴리오] 최대 보유 포지션(2개)에 도달하여 신규 진입하지 않습니다.")
                return

            margin_percent = 0.50 if total_open_positions == 0 else 0.95
            
            balance = self.client.get_balance()
            current_price = df['close'].iloc[-1]
            trade_size = 0
            if balance > 0 and current_price > 0:
                margin_to_use = balance * margin_percent
                target_nominal_value = margin_to_use * self.leverage
                trade_size = target_nominal_value / current_price # 계약 단위가 1 USD라고 가정

            if trade_size < 1:
                print(f"  [경고] 계산된 주문 수량({trade_size:.4f})이 1보다 작아 주문을 실행하지 않습니다.")
                return
            
            print(f"  [자금 관리] 총 보유 포지션: {total_open_positions}개 -> {margin_percent*100}% 마진 사용 (주문 수량: {trade_size:.4f})")

            if market_regime == "TRENDING":
                self.execute_trend_entry(df, contract, trade_size)
            else:
                self.execute_bnf_entry(df, contract, trade_size)


    def execute_trend_exit(self, df, contract, position_size):
        last_ema_fast = df[f'EMA_{self.fast_ema_period}'].iloc[-1]
        last_ema_slow = df[f'EMA_{self.slow_ema_period}'].iloc[-1]
        prev_ema_fast = df[f'EMA_{self.fast_ema_period}'].iloc[-2]
        prev_ema_slow = df[f'EMA_{self.slow_ema_period}'].iloc[-2]

        if position_size > 0 and last_ema_fast < last_ema_slow and prev_ema_fast >= prev_ema_slow:
            print(f"  [추세-청산] 데드 크로스! 기존 롱 포지션 청산.")
            self.client.close_position(contract)
        elif position_size < 0 and last_ema_fast > last_ema_slow and prev_ema_fast <= prev_ema_slow:
            print(f"  [추세-청산] 골든 크로스! 기존 숏 포지션 청산.")
            self.client.close_position(contract)

    def execute_trend_entry(self, df, contract, trade_size):
        last_ema_fast = df[f'EMA_{self.fast_ema_period}'].iloc[-1]
        last_ema_slow = df[f'EMA_{self.slow_ema_period}'].iloc[-1]
        prev_ema_fast = df[f'EMA_{self.fast_ema_period}'].iloc[-2]
        prev_ema_slow = df[f'EMA_{self.slow_ema_period}'].iloc[-2]
        
        print(f"  [추세-진입] EMA_Fast: {last_ema_fast:.2f}, EMA_Slow: {last_ema_slow:.2f}")

        if last_ema_fast > last_ema_slow and prev_ema_fast <= prev_ema_slow:
            print(f"  --> 골든 크로스! 롱 포지션 진입. Size: {trade_size:.4f}")
            self.client.create_order(contract, trade_size)
        elif last_ema_fast < last_ema_slow and prev_ema_fast >= prev_ema_slow:
            print(f"  --> 데드 크로스! 숏 포지션 진입. Size: {-trade_size:.4f}")
            self.client.create_order(contract, -trade_size)
        else:
            print("  --> 추세 전략: 진입 신호 없음.")

    def execute_bnf_exit(self, df, contract, position_size):
        last_close = df['close'].iloc[-1]
        ema_bnf = df[f'EMA_{self.bnf_ema_period}'].dropna().iloc[-1]
        
        if position_size > 0 and last_close > ema_bnf:
            print("  --> BNF: 평균 회귀! 롱 포지션 청산.")
            self.client.close_position(contract)
        elif position_size < 0 and last_close < ema_bnf:
            print("  --> BNF: 평균 회귀! 숏 포지션 청산.")
            self.client.close_position(contract)

    def execute_bnf_entry(self, df, contract, trade_size):
        last_close = df['close'].iloc[-1]
        ema_bnf = df[f'EMA_{self.bnf_ema_period}'].dropna().iloc[-1]
        upper_band_price = ema_bnf * (1 + self.bnf_deviation / 100)
        lower_band_price = ema_bnf * (1 - self.bnf_deviation / 100)
        
        print(f"  [BNF-진입] 현재가: {last_close:.2f}, {self.bnf_ema_period}-EMA: {ema_bnf:.2f}")

        if last_close < lower_band_price:
            print(f"  --> BNF: 과매도! 롱 포지션 진입. Size: {trade_size:.4f}")
            self.client.create_order(contract, trade_size)
        elif last_close > upper_band_price:
            print(f"  --> BNF: 과매수! 숏 포지션 진입. Size: {-trade_size:.4f}")
            self.client.create_order(contract, -trade_size)
        else:
            print("  --> BNF 횡보 전략: 진입 신호 없음.")

    def run(self):
        # 1. 전체 포지션 현황 파악
        open_positions = []
        for contract in self.contracts:
            pos = self.client.get_position(contract)
            if pos and float(pos.size) != 0:
                open_positions.append(pos)
            time.sleep(0.1) # API 호출 간 짧은 딜레이

        total_open_positions = len(open_positions)
        print(f"\n[포트폴리오 현황] 총 보유 포지션: {total_open_positions}개")
        for pos in open_positions:
            print(f"  - {pos.contract}: {pos.size} 계약")

        # 2. 각 코인에 대한 전략 실행
        for contract in self.contracts:
            self.run_strategy_for_contract(contract, total_open_positions)
            time.sleep(0.5) # 각 코인별 API 호출 사이에 약간의 딜레이

if __name__ == "__main__":
    client_config = setup_gateio_client()
    futures_api_client = gate_api.FuturesApi(gate_api.ApiClient(client_config))
    
    while True:
        # 하루에 한 번, 거래량 상위 코인 목록을 가져옴
        daily_contracts = get_top_traded_contracts(futures_api_client, SETTLE_CURRENCY, TOP_N_CONTRACTS)
        
        if not daily_contracts:
            print("거래 대상 코인을 가져오지 못했습니다. 60분 후 다시 시도합니다.")
            time.sleep(3600)
            continue

        bot = TradingBot(client_config, daily_contracts)
        
        # 24시간 동안 1분(60초) 주기로 실행 (24 * 60 = 1440회)
        for i in range(24 * 60):
            print(f"\n--- [Cycle {i+1}/{24*60}] ---")
            bot.run()
            print(f"\n{INTERVAL_SECONDS}초 대기 중...")
            time.sleep(INTERVAL_SECONDS)