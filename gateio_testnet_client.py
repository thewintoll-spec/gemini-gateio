import gate_api
from gate_api.exceptions import ApiException, GateApiException
import os

# gateio_info.txt에서 가져온 정보
TESTNET_API_URL = "https://api-testnet.gateapi.io/api/v4"
API_KEY = "cb872a645c4afcdf0de204cf34eae039"
SECRET_KEY = "b9c41e0ef773e1504ec69159e3cceaea43d3adf6fd98f4fbeac1c443981eeeca"

def setup_gateio_client():
    """
    Gate.io API 클라이언트를 설정하고 반환합니다.
    """
    config = gate_api.Configuration(
        host=TESTNET_API_URL,
        key=API_KEY,
        secret=SECRET_KEY
    )
    # 전역 설정을 변경하여 Testnet URL을 사용하도록 합니다.
    gate_api.Configuration.set_default(config)
    
    # Configuration이 올바르게 설정되었는지 확인
    print(f"API Host: {config.host}")

    return config

def test_api_connection(config):
    """
    API 연결을 테스트하고 계정 잔고 및 BTC/USDT 가격을 조회합니다.
    """
    print("\n--- Gate.io Testnet API 연결 테스트 시작 ---")
    try:
        # 지갑 API 클라이언트 초기화
        wallet_api = gate_api.WalletApi(gate_api.ApiClient(config))
        # list_payment_currencies는 더 이상 사용되지 않거나 Testnet에 없는 API일 수 있습니다.
        # 대신 list_spot_accounts를 사용하여 계정 정보를 확인합니다.

        # 현물 API 클라이언트 초기화
        spot_api = gate_api.SpotApi(gate_api.ApiClient(config))
        # 계정 잔고 조회
        spot_accounts = spot_api.list_spot_accounts()
        print("\n--- 현물 계정 잔고 조회 ---")
        has_balance = False
        for account in spot_accounts:
            if float(account.available) > 0 or float(account.locked) > 0:
                print(f"  {account.currency}: 사용 가능 {account.available}, 잠김 {account.locked}")
                has_balance = True
        if not has_balance:
            print("  사용 가능한 현물 계정 잔고가 없습니다. Testnet에서 자산을 입금해야 할 수 있습니다.")
            print("  (참고: Gate.io Testnet은 일반적으로 사전 충전된 계정을 제공하지 않으므로 직접 Testnet 자산을 입금해야 합니다.)")


        # BTC/USDT 티커 정보 조회
        tickers = spot_api.list_tickers(currency_pair='BTC_USDT')
        print("\n--- BTC_USDT 현재 가격 조회 ---")
        if tickers:
            ticker = tickers[0]
            # 올바른 속성 이름 사용: highest_bid, lowest_ask
            print(f"  BTC_USDT 현재가: {ticker.last}, 최고 매수호가: {ticker.highest_bid}, 최저 매도호가: {ticker.lowest_ask}")
        else:
            print("  BTC_USDT 티커 정보를 찾을 수 없습니다.")

        print("\n--- API 연결 테스트 성공 ---")

    except GateApiException as e:
        print(f"\n--- Gate.io API 오류 발생 ---")
        print(f"  Status: {e.status}")
        print(f"  Reason: {e.reason}")
        print(f"  Body: {e.body}")
        print("\n--- API 연결 테스트 실패 ---")
    except ApiException as e:
        print(f"\n--- 일반 API 오류 발생 ---")
        print(f"  Exception when calling Gate.io API: {e}")
        print("\n--- API 연결 테스트 실패 ---")
    except Exception as e:
        print(f"\n--- 예기치 않은 오류 발생 ---")
        print(f"  오류: {e}")
        print("\n--- API 연결 테스트 실패 ---")

if __name__ == "__main__":
    config = setup_gateio_client()
    test_api_connection(config)
