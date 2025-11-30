# Gate.io 선물 자동매매 봇

이 프로젝트는 Gate.io 선물 거래소 테스트넷에서 BTC/USDT 무기한 선물을 거래하는 자동매매 봇입니다. 시장 상황에 따라 추세 추종 전략과 역추세(평균 회귀) 전략을 자동으로 전환하는 하이브리드 전략을 사용합니다.

## 주요 기능

- **하이브리드 전략**: 시장의 추세 강도에 따라 매매 전략을 동적으로 변경합니다.
- **시장 상황 판단**: ADX(Average Directional Index) 지표를 사용하여 현재 시장이 '추세장'인지 '횡보장'인지 판단합니다.
- **추세 추종 전략**: 추세장에서는 두 지수이동평균(EMA)의 교차(골든크로스/데드크로스)를 매매 신호로 사용합니다.
- **역추세 전략**: 횡보장에서는 볼린저 밴드(Bollinger Bands)의 상단/하단 이탈을 반대매매 신호로 사용합니다.
- **자동 로깅**: 모든 거래 내역과 미실현 손익을 CSV 파일(`trade_history.csv`, `pnl_over_time.csv`)에 자동으로 기록합니다.

## 사전 준비

- Python 3.x
- 다음 Python 라이브러리가 필요합니다.
  - `gate-api-python`
  - `pandas`
  - `pandas-ta`

## 설치 및 설정

1.  **라이브러리 설치:**
    터미널(명령 프롬프트)에 다음 명령어를 입력하여 필요한 라이브러리를 설치합니다.

    ```sh
    pip install gate-api-python pandas pandas-ta
    ```

2.  **API 키 설정:**
    `gateio_futures_bot.py` 파일을 열어 상단에 있는 다음 변수에 자신의 Gate.io API 키와 시크릿 키를 입력합니다.

    **경고:** 이 코드는 테스트용이며, 실제 돈으로 거래할 경우 보안에 매우 주의해야 합니다. API 키를 코드에 직접 하드코딩하는 것은 위험하므로, 환경 변수나 다른 보안 설정 방법을 사용하는 것을 권장합니다.

    ```python
    API_KEY = "YOUR_API_KEY"
    SECRET_KEY = "YOUR_SECRET_KEY"
    ```

## 설정 값 변경

`gateio_futures_bot.py` 파일 상단에서 주요 파라미터를 수정하여 봇의 행동을 변경할 수 있습니다.

- `CONTRACT`: 거래할 선물 계약 (예: `'BTC_USDT'`)
- `LEVERAGE`: 레버리지 배율 (예: `10`)
- `INTERVAL_SECONDS`: 봇이 다음 행동을 하기까지 대기하는 시간 (초)
- `CANDLE_INTERVAL`: 분석에 사용할 캔들(봉)의 시간 단위 (예: `'5m'`, `'1h'`)
- `ADX_THRESHOLD`: 추세장과 횡보장을 나누는 ADX 기준 값 (값이 클수록 더 강한 추세만 인정)
- `FAST_EMA_PERIOD`, `SLOW_EMA_PERIOD`: 추세 추종 전략에서 사용할 두 이동평균선의 기간
- `BB_PERIOD`, `BB_STD`: 역추세 전략에서 사용할 볼린저 밴드의 기간과 표준편차
- `TRADE_SIZE`: 한 번에 거래할 계약의 수량 (예: `0.001`은 0.001 BTC)

## 실행 방법

봇을 실행하려면 터미널에 다음 명령어를 입력하세요. 봇은 설정된 `INTERVAL_SECONDS` 간격으로 계속해서 시장을 분석하고 거래를 시도합니다.

```sh
python gateio_futures_bot.py
```

봇을 중지하려면 터미널에서 `Ctrl + C`를 누르세요.

## 생성되는 파일

- `trade_history.csv`: 모든 거래(진입/청산) 기록이 저장됩니다.
- `pnl_over_time.csv`: 매 실행 간격마다의 미실현 손익(Unrealised PNL)이 기록됩니다.
- `output.log`: 봇의 모든 동작 로그가 기록됩니다. (현재는 터미널 출력과 동일)
