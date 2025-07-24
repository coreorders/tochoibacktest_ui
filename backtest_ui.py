import streamlit as st
import pybithumb
import pandas as pd
import datetime

# --- 1. 백테스팅 함수 정의 (Streamlit에 맞게 결과 반환으로 수정) ---
def run_backtest(ticker, interval_key, ma_period, initial_capital, fee_rate):
    results = {} # 결과를 저장할 딕셔너리
    log_messages = [] # 로그 메시지를 저장할 리스트

    def log(message):
        log_messages.append(message)
        # print(message) # Streamlit에서는 직접 print하지 않고 log_messages에 추가

    log(f"--- 백테스팅 파라미터 확인 ---")
    log(f"코인: {ticker}, 캔들 주기: {interval_key}, MA 기간: {ma_period}")
    log(f"초기 자본: {initial_capital}원, 수수료율: {fee_rate*100}%")
    log(f"\n[{datetime.datetime.now()}] {ticker} {interval_key}봉 이동평균선 백테스팅 시작...")

    # 과거 캔들 데이터 가져오기
    # st.spinner를 사용하여 데이터 로드 중임을 사용자에게 알림
    with st.spinner(f"'{ticker}' 코인의 '{interval_key}' 데이터를 로드 중입니다..."):
        df = pybithumb.get_ohlcv(ticker, interval=interval_key)

    if df is None or df.empty:
        log(f"[{datetime.datetime.now()}] {ticker} {interval_key} 데이터를 가져오지 못했습니다. 백테스팅을 중단합니다.")
        log("입력한 코인 티커나 캔들 주기가 올바른지 확인하거나, 네트워크 연결을 확인하세요.")
        return results, log_messages # 결과 없음 반환

    log(f"총 {len(df)}개의 {interval_key}봉 데이터 로드 완료. ({df.index[0]} ~ {df.index[-1]})")

    # 이동평균선 계산
    df['ma'] = df['close'].rolling(window=ma_period).mean()

    # NaN 값 (초기 이동평균선 계산 불가 구간) 제거
    df = df.dropna()

    if df.empty:
        log("이동평균선 계산 후 유효한 데이터가 없습니다. MA 기간을 줄이거나 데이터 양을 확인하세요.")
        return results, log_messages

    # 백테스팅 변수 초기화
    current_krw = initial_capital
    current_coin_amount = 0
    trades = []
    in_position = False

    log("\n--- 백테스팅 시뮬레이션 시작 ---")

    for i in range(1, len(df)): 
        current_candle = df.iloc[i]
        prev_candle = df.iloc[i-1]

        close_price = current_candle['close']
        ma_price = current_candle['ma']
        
        prev_close_price = prev_candle['close']
        prev_ma_price = prev_candle['ma']

        # 매수 조건: 골든 크로스 발생 및 코인 미보유 상태
        if not in_position and prev_close_price <= prev_ma_price and close_price > ma_price:
            buy_amount_krw = current_krw * (1 - fee_rate)
            if buy_amount_krw < 5000: 
                continue 

            buy_coin_amount = buy_amount_krw / close_price

            current_coin_amount += buy_coin_amount
            current_krw -= (buy_coin_amount * close_price) 

            in_position = True
            trades.append({
                'type': 'BUY',
                'timestamp': current_candle.name,
                'price': close_price,
                'amount': buy_coin_amount,
                'krw_left': current_krw,
                'coin_held': current_coin_amount
            })
            log(f"[{current_candle.name}] BUY: {close_price:.8f}원, 수량: {buy_coin_amount:.8f}, 남은 원화: {current_krw:.0f}")

        # 매도 조건: 데드 크로스 발생 및 코인 보유 상태
        elif in_position and prev_close_price >= prev_ma_price and close_price < ma_price:
            sell_coin_amount = current_coin_amount
            earned_krw = (sell_coin_amount * close_price) * (1 - fee_rate)

            current_krw += earned_krw
            current_coin_amount = 0 

            in_position = False
            trades.append({
                'type': 'SELL',
                'timestamp': current_candle.name,
                'price': close_price,
                'amount': sell_coin_amount,
                'krw_left': current_krw,
                'coin_held': current_coin_amount
            })
            log(f"[{current_candle.name}] SELL: {close_price:.8f}원, 수량: {sell_coin_amount:.8f}, 현재 원화: {current_krw:.0f}")

    log("\n--- 백테스팅 시뮬레이션 종료 ---")

    # 최종 자산 계산 (만약 코인을 보유 중이라면 마지막 종가로 평가)
    final_asset_krw = current_krw
    if in_position:
        if not df.empty:
            final_price_for_evaluation = df['close'].iloc[-1]
            final_asset_krw += (current_coin_amount * final_price_for_evaluation)
            log(f"백테스팅 종료 시 {current_coin_amount:.8f} {ticker} 보유 중. 마지막 봉 종가 {final_price_for_evaluation:.8f}원 기준 평가액 추가.")
        else:
            log("데이터프레임이 비어 최종 자산 평가를 할 수 없습니다.")

    profit_loss = final_asset_krw - initial_capital
    profit_loss_percentage = (profit_loss / initial_capital) * 100 if initial_capital > 0 else 0

    results = {
        "초기 자본": f"{initial_capital:,.0f}원",
        "최종 자산": f"{final_asset_krw:,.0f}원",
        "총 수익/손실": f"{profit_loss:,.0f}원",
        "수익률": f"{profit_loss_percentage:.2f}%",
        "총 거래 횟수": len(trades),
        "매수 횟수": len([t for t in trades if t['type'] == 'BUY']),
        "매도 횟수": len([t for t in trades if t['type'] == 'SELL']),
    }
    
    # 승률 계산
    if len(trades) > 0:
        sell_trades = [t for t in trades if t['type'] == 'SELL']
        win_count = 0
        loss_count = 0
        
        # 각 매도에 대해 직전 매수를 찾아서 비교 (간단한 로직, 정확도를 높이려면 더 복잡해짐)
        for i in range(len(sell_trades)):
            sell_price = sell_trades[i]['price']
            # 해당 매도 이전에 발생한 모든 매수 거래 찾기
            previous_buys = [t for t in trades if t['type'] == 'BUY' and t['timestamp'] < sell_trades[i]['timestamp']]
            if previous_buys:
                # 가장 최근의 매수 가격과 비교
                last_buy_price = previous_buys[-1]['price']
                if sell_price > last_buy_price:
                    win_count += 1
                elif sell_price < last_buy_price:
                    loss_count += 1
        
        total_settled_trades = win_count + loss_count
        if total_settled_trades > 0:
            results["승률 (대략)"] = f"{(win_count / total_settled_trades) * 100:.2f}%"
        else:
            results["승률 (대략)"] = "N/A (매도 거래 없음)"
    else:
        results["승률 (대략)"] = "N/A (거래 없음)"

    return results, log_messages, trades # trades 기록도 함께 반환하여 UI에 표시 가능

# --- Streamlit UI 구성 ---
st.set_page_config(layout="centered", page_title="빗썸 자동매매 백테스팅 시뮬레이터")

st.title("🚀 빗썸 자동매매 백테스팅 시뮬레이터 🚀")
st.markdown("이동평균선 크로스오버 전략을 과거 데이터에 적용하여 시뮬레이션합니다.")

# 사이드바 (파라미터 입력)
with st.sidebar:
    st.header("백테스팅 파라미터")

    # 코인 티커 입력
    ticker_input = st.text_input("거래할 코인 티커 (예: SHIB, BTC, XRP)", value="SHIB").upper()

    # 캔들봉 주기 드롭다운 (지원하는 주기 리스트)
    supported_intervals_map = {
        "1분봉": "minute1", "3분봉": "minute3", "5분봉": "minute5",
        "10분봉": "minute10", "30분봉": "minute30", "1시간봉": "hour",
        "6시간봉": "hour6", "12시간봉": "hour12", "일봉": "day"
    }
    selected_interval_name = st.selectbox(
        "캔들봉 주기 선택:",
        list(supported_intervals_map.keys()),
        index=3 # 기본값: 10분봉
    )
    interval_key_input = supported_intervals_map[selected_interval_name]


    # 이동평균선 기간 입력
    ma_period_input = st.number_input("이동평균선 기간 (정수, 예: 20)", min_value=1, value=20, step=1)

    # 초기 투자 원금 입력
    initial_capital_input = st.number_input("초기 투자 원금 (원)", min_value=5000, value=1000000, step=10000)

    # 수수료율 입력
    fee_rate_input = st.number_input("수수료율 (소수점, 예: 0.0025 for 0.25%)", min_value=0.0, max_value=1.0, value=0.0025, step=0.0001, format="%.4f")

    # 백테스팅 실행 버튼
    run_button = st.button("백테스팅 실행")

# 메인 화면 (결과 표시)
if run_button:
    st.subheader("📊 백테스팅 결과")
    
    # run_backtest 함수 실행
    results, log_messages, trades = run_backtest(
        ticker=ticker_input,
        interval_key=interval_key_input,
        ma_period=ma_period_input,
        initial_capital=initial_capital_input,
        fee_rate=fee_rate_input
    )

    if results:
        # 결과 요약 표시
        st.write("### 요약")
        result_df = pd.DataFrame(results.items(), columns=["항목", "값"])
        st.table(result_df) # st.dataframe 대신 st.table을 사용하면 고정된 테이블 형태로 보임
        
        st.write("---")
        # 로그 메시지 표시
        st.write("### 실행 로그")
        # st.text_area를 사용하여 로그를 스크롤 가능한 형태로 표시
        st.text_area("로그", "\n".join(log_messages), height=300)

        # 거래 기록 표시
        if trades:
            st.write("### 모든 거래 기록")
            trades_df = pd.DataFrame(trades)
            st.dataframe(trades_df)
        else:
            st.info("발생한 거래가 없습니다.")
    else:
        st.error("백테스팅 실행 중 오류가 발생했거나 데이터를 가져오지 못했습니다. 로그를 확인하세요.")
        st.text_area("로그", "\n".join(log_messages), height=200)

st.sidebar.markdown("---")
st.sidebar.markdown("Made with ❤️ by Your AI Assistant")
