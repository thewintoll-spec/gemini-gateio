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

# 고정된 거래 코인 목록 (사용자 요청)
CONTRACTS_TO_TRADE = ['BTC_USDT', 'ETH_USDT', 'XRP_USDT', 'SOL_USDT', 'SUI_USDT', 'LINK_USDT', 'DOGE_USDT']

# 계약별 승수 (contract multiplier) - Gate.io API 문서 기반
# 1 계약이 몇 코인 단위를 의미하는지
CONTRACT_MULTIPLIERS = {
    'BTC_USDT': 0.0001,
    'ETH_USDT': 0.001,
    'XRP_USDT': 1,
    'SOL_USDT': 0.1,
    'SUI_USDT': 1,
    'LINK_USDT': 0.1,
    'DOGE_USDT': 10,
}

# 계약별 승수 (contract multiplier) - Gate.io API 문서 기반
# 1 계약이 몇 코인 단위를 의미하는지
CONTRACT_MULTIPLIERS = {
    'BTC_USDT': 0.0001,
    'ETH_USDT': 0.001,
    'XRP_USDT': 1,
    'SOL_USDT': 0.1,
    'SUI_USDT': 1,
    'LINK_USDT': 0.1,
    'DOGE_USDT': 10,
}

# 계약별 승수 (contract multiplier) - Gate.io API 문서 기반
# 1 계약이 몇 코인 단위를 의미하는지
CONTRACT_MULTIPLIERS = {
    'BTC_USDT': 0.0001,
    'ETH_USDT': 0.001,
    'XRP_USDT': 1,
    'SOL_USDT': 0.1,
    'SUI_USDT': 1,
    'LINK_USDT': 0.1,
    'DOGE_USDT': 10,
}

# 계약별 승수 (contract multiplier) - Gate.io API 문서 기반
# 1 계약이 몇 코인 단위를 의미하는지
CONTRACT_MULTIPLIERS = {
    'BTC_USDT': 0.0001,
    'ETH_USDT': 0.001,
    'XRP_USDT': 1,
    'SOL_USDT': 0.1,
    'SUI_USDT': 1,
    'LINK_USDT': 0.1,
    'DOGE_USDT': 10,
}

# 전략 파라미터 (BNF 강화 버전)
ADX_THRESHOLD = 25
FAST_EMA_PERIOD = 9
SLOW_EMA_PERIOD = 21
BNF_EMA_PERIOD = 25
BNF_DEVIATION_PERCENT = 20.0 # BNF 전략용 이격도 (%) (20%로 상향 조정)
RSI_PERIOD = 14
RSI_OVERSOLD_THRESHOLD = 30
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9
STOP_LOSS_CANDLE_COUNT = 5 # 손절선 계산에 사용할 최근 캔들 개수 (직전 5개 캔들의 최저점)

def setup_gateio_client():
    config = gate_api.Configuration(host=TESTNET_API_URL, key=API_KEY, secret=SECRET_KEY)
    gate_api.Configuration.set_default(config)
    print(f"API Host: {config.host}")
    return config

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
        self.rsi_period = RSI_PERIOD
        self.rsi_oversold_threshold = RSI_OVERSOLD_THRESHOLD
        self.macd_fast = MACD_FAST
        self.macd_slow = MACD_SLOW
        self.macd_signal = MACD_SIGNAL
        self.stop_loss_candle_count = STOP_LOSS_CANDLE_COUNT

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
        if not klines or len(klines) < max(self.bnf_ema_period, self.slow_ema_period, self.rsi_period, self.macd_slow + self.macd_signal):
            print(f"  [{contract}] 기술적 지표 계산에 필요한 데이터 부족.")
            return

        df = pd.DataFrame([{'open': float(k.o), 'high': float(k.h), 'low': float(k.l), 'close': float(k.c), 'volume': float(k.v)} for k in klines])
        df.ta.adx(length=14, append=True)
        df.ta.ema(length=self.fast_ema_period, append=True)
        df.ta.ema(length=self.slow_ema_period, append=True)
        df.ta.ema(length=self.bnf_ema_period, append=True)
        df.ta.rsi(length=self.rsi_period, append=True)
        df.ta.macd(fast=self.macd_fast, slow=self.macd_slow, signal=self.macd_signal, append=True)
        
        required_cols = [
            'ADX_14', 
            f'EMA_{self.fast_ema_period}', f'EMA_{self.slow_ema_period}', f'EMA_{self.bnf_ema_period}',
            f'RSI_{self.rsi_period}',
            f'MACDh_{self.macd_fast}_{self.macd_slow}_{self.macd_signal}'
        ]
        if not all(col in df.columns for col in required_cols):
            print(f"  [{contract}] 오류: 일부 기술적 지표가 DataFrame에 추가되지 않았습니다. 컬럼: {df.columns.tolist()}")
            return

        adx_series = df['ADX_14'].dropna()
        if adx_series.empty:
            print(f"  [{contract}] ADX 계산에 유효한 데이터가 부족하여 건너킵니다.")
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
                
                # 코인별 계약 승수를 적용하여 실제 계약 수 계산
                contract_multiplier = CONTRACT_MULTIPLIERS.get(contract, 1) # 목록에 없으면 기본값 1 사용
                if contract_multiplier > 0:
                    # (총 포지션 가치 / 현재가) = 총 코인 수량
                    # (총 코인 수량) / (1계약당 코인 수) = 계약 수
                    trade_size_in_asset = target_nominal_value / current_price
                    trade_size = trade_size_in_asset / contract_multiplier
                else:
                    print(f"  [경고] {contract}의 계약 승수가 유효하지 않습니다: {contract_multiplier}")

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
        
        # 손익 실현 (가격이 25-EMA를 상향 돌파)
        if position_size > 0 and last_close > ema_bnf:
            print("  --> BNF: 평균 회귀! 롱 포지션 청산 (수익 실현).")
            self.client.close_position(contract)
        # 손절 (직전 5개 캔들의 최저가를 하향 이탈)
        elif position_size > 0 and last_close < df['low'].iloc[-self.stop_loss_candle_count:].min():
            print(f"  --> BNF: 손절! 직전 {self.stop_loss_candle_count}개 캔들 최저가 이탈.")
            self.client.close_position(contract)
        elif position_size < 0 and last_close < ema_bnf: # 숏 포지션 익절
            print("  --> BNF: 평균 회귀! 숏 포지션 청산.")
            self.client.close_position(contract)

    def execute_bnf_entry(self, df, contract, trade_size):
        last_close = df['close'].iloc[-1]
        ema_bnf = df[f'EMA_{self.bnf_ema_period}'].dropna().iloc[-1]
        rsi = df[f'RSI_{self.rsi_period}'].dropna().iloc[-1]
        macd_hist = df[f'MACDh_{self.macd_fast}_{self.macd_slow}_{self.macd_signal}'].dropna().iloc[-1]
        prev_macd_hist = df[f'MACDh_{self.macd_fast}_{self.macd_slow}_{self.macd_signal}'].dropna().iloc[-2]

        # 진입 조건 1: EMA 이격도 20% 이상 하락
        ema_deviation_condition = (last_close < ema_bnf * (1 - self.bnf_deviation / 100))
        # 진입 조건 2: RSI 30 미만
        rsi_condition = (rsi < self.rsi_oversold_threshold)
        # 진입 조건 3: MACD 히스토그램 상승 전환 (양수이면서 이전보다 커짐)
        macd_condition = (macd_hist > 0 and macd_hist > prev_macd_hist)
        
        print(f"  [BNF-진입] 현재가: {last_close:.2f}, {self.bnf_ema_period}-EMA: {ema_bnf:.2f}, RSI: {rsi:.2f}, MACDH: {macd_hist:.4f}")

        # 매수 포지션 진입 (롱만 고려)
        if ema_deviation_condition and rsi_condition and macd_condition:
            print(f"  --> BNF: 매수 진입 조건 충족! 롱 포지션 진입. Size: {trade_size:.4f}")
            self.client.create_order(contract, trade_size)
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
    
    while True:
        print("\n--- Gate.io 선물 자동매매 봇 시작 (Testnet) ---")
        print(f"정산 화폐: {SETTLE_CURRENCY}, 레버리지: {LEVERAGE}x")
        print(f"거래 대상 코인: {CONTRACTS_TO_TRADE}")

        bot = TradingBot(client_config, CONTRACTS_TO_TRADE)
        
        # 1분(60초) 주기로 무한 반복 실행
        print(f"\n매매 로직 {INTERVAL_SECONDS}초 주기로 반복 실행 중...")
        while True:
            bot.run()
            time.sleep(INTERVAL_SECONDS)