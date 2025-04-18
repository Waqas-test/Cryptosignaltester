import streamlit as st
import ccxt
import pandas as pd
from datetime import datetime, timedelta
import re
import time
import warnings
import pytz  # For UTC timezone
from typing import List, Tuple

# Configure page
st.set_page_config(page_title="Crypto Trade Signal Tester", layout="wide")
st.title("📈 Crypto Trade Signal Tester (UTC)")

# Initialize exchange connection
@st.cache_resource
def init_exchange(exchange_name='kucoin'):
    exchange = getattr(ccxt, exchange_name)({
        'enableRateLimit': True,
        'options': {'adjustForTimeDifference': True}
    })
    exchange.load_markets()
    return exchange

class CryptoTradeTester:
    def __init__(self, exchange='kucoin'):
        self.exchange = init_exchange(exchange)
    
    def parse_signal(self, signal_text: str) -> dict:
        """Parse unstructured trade signal text into structured format"""
        try:
            # Extract pair
            pair_match = re.search(r'([A-Z]{3,}\/[A-Z]{3,})', signal_text, re.IGNORECASE)
            if not pair_match:
                raise ValueError("Could not find trading pair in signal")
            pair = pair_match.group(1).upper()
            
            # Detect trade direction (buy or sell) and entry price
            direction, entry = self._extract_direction_and_price(signal_text)
            
            # Extract stop loss
            stop_loss = self._extract_price(signal_text, ['sl at', 'stop loss at', 'stoploss at', 'sl', 'stop loss', 'stoploss'])
            
            # Extract take profits
            take_profits = self._extract_take_profits(signal_text)
            
            # Extract signal time (required)
            signal_time = self._extract_time(signal_text)
            
            # Validate signal time is not in future
            if signal_time > datetime.now(pytz.utc):
                raise ValueError("Signal time cannot be in the future")
            
            return {
                'pair': pair,
                'direction': direction,
                'entry': entry,
                'stop_loss': stop_loss,
                'take_profits': take_profits,
                'signal_time': signal_time
            }
        except Exception as e:
            raise ValueError(f"Signal parsing error: {str(e)}")

    # ... [keep all other methods the same until fetch_historical_data]

    def fetch_historical_data(self, pair: str, timeframe: str, start_time: datetime) -> pd.DataFrame:
        """Fetch OHLCV data from exchange from start_time to now (UTC)"""
        all_ohlcv = []
        current_time = start_time
        max_attempts = 5
        attempts = 0
        end_time = datetime.now(pytz.utc)  # Use UTC now
        
        progress_bar = st.progress(0, text="Fetching historical data...")
        status_text = st.empty()
        
        while current_time < end_time and attempts < max_attempts:
            try:
                status_text.text(f"Fetching data from {current_time} UTC...")
                since = int(current_time.timestamp() * 1000)
                ohlcv = self.exchange.fetch_ohlcv(pair, timeframe, since, limit=1000)
                
                if not ohlcv:
                    break
                
                df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms').dt.tz_localize(pytz.utc)
                df = df[df['timestamp'] <= end_time]
                
                if len(df) > 0:
                    all_ohlcv.append(df)
                    last_timestamp = df['timestamp'].iloc[-1]
                    if last_timestamp <= current_time:
                        break
                    current_time = last_timestamp
                    attempts = 0
                    
                    # Update progress
                    progress = min(0.9, (current_time - start_time).total_seconds() / (end_time - start_time).total_seconds())
                    progress_bar.progress(progress)
                else:
                    attempts += 1
                    time.sleep(1)
                
                time.sleep(self.exchange.rateLimit / 1000)
                
            except Exception as e:
                attempts += 1
                status_text.text(f"Error fetching data (attempt {attempts}): {str(e)}")
                time.sleep(5)
        
        if not all_ohlcv:
            raise ValueError(f"No historical data available for {pair} from {start_time}")
        
        full_df = pd.concat(all_ohlcv).drop_duplicates()
        full_df.set_index('timestamp', inplace=True)
        full_df.sort_index(inplace=True)
        
        progress_bar.progress(1.0, text="Data fetch complete!")
        time.sleep(0.5)
        progress_bar.empty()
        status_text.empty()
        
        return full_df

    # ... [keep all other methods the same]

# Streamlit UI updates to show UTC times
def main():
    col1, col2 = st.columns([1, 1])
    
    with col1:
        st.subheader("Enter Trade Signal (All times UTC)")
        signal_text = st.text_area(
            "Paste your trade signal here:",
            height=200,
            help="All times are interpreted as UTC\n"
                 "Example: BTC/USDT Buy at 35000, SL at 34500, TP1 at 35500, Time: 2023-11-15 08:00 UTC"
        )
        
        exchange = st.selectbox(
            "Exchange",
            ['kucoin', 'coinbase'],
            index=0
        )
        
        timeframe = st.selectbox(
            "Timeframe",
            ['1m', '5m', '15m', '1h', '4h', '1d'],
            index=3
        )
        
        if st.button("Test Signal", use_container_width=True):
            if not signal_text.strip():
                st.error("Please enter a trade signal")
                return
            
            tester = CryptoTradeTester(exchange)
            
            try:
                # Parse signal
                with st.spinner("Parsing signal..."):
                    signal = tester.parse_signal(signal_text)
                    st.session_state.signal = signal
                
                # Display parsed signal
                with st.expander("Parsed Signal Details", expanded=True):
                    st.write(f"**Pair:** {signal['pair']}")
                    st.write(f"**Direction:** {signal['direction'].upper()}")
                    st.write(f"**Entry Price:** {signal['entry']}")
                    st.write(f"**Stop Loss:** {signal['stop_loss']}")
                    st.write(f"**Take Profits:** {', '.join(map(str, signal['take_profits']))}")
                    st.write(f"**Signal Time (UTC):** {signal['signal_time']}")
                
                # Run backtest
                results = tester.test_signal(signal)
                st.session_state.results = results
                
                # Display results
                st.subheader("Backtest Results (UTC Times)")
                
                # Metrics row
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Direction", results['direction'].upper())
                m2.metric("Entry Price", f"{results['entry_price']}")
                m3.metric("Current Price", f"{results['current_price']}", f"{results['pct_change']:.2f}%")
                m4.metric("Result", results['result'])
                
                # Additional metrics
                m5, m6, m7 = st.columns(3)
                m5.metric("Max Price", f"{results['max_price']}")
                m6.metric("Min Price", f"{results['min_price']}")
                m7.metric("Duration", results['duration'])
                
                # Results details
                with st.expander("Detailed Results", expanded=True):
                    st.write(f"**Signal Time (UTC):** {results['signal_time']}")
                    st.write(f"**Entry Time (UTC):** {results['entry_time']}")
                    st.write(f"**Test Period (UTC):** {results['test_period']}")
                    st.write(f"**Data Points:** {results['data_points']}")
                    
                    st.write("\n**Stop Loss:**")
                    sl_status = f"{results['stop_loss']} - {'✅ Hit' if results['sl_hit'] else '❌ Not Hit'}"
                    if results['sl_hit']:
                        sl_status += f" at {results['sl_hit_time']} UTC"
                    st.write(sl_status)
                    
                    st.write("\n**Take Profits:**")
                    for i, tp in enumerate(results['take_profits']):
                        hit = i in results['tp_hit']
                        st.write(f"TP{i+1}: {tp} - {'✅ Hit' if hit else '❌ Not Hit'} " + 
                                (f"at {results[f'tp{i+1}_hit_time']} UTC" if hit else ""))
                
                # Price chart
                st.subheader("Price Movement (UTC Time)")
                st.line_chart(results['price_data']['close'])
                
            except Exception as e:
                st.error(f"Error: {str(e)}")

if __name__ == "__main__":
    main()
