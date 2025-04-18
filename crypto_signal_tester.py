import streamlit as st
import ccxt
import pandas as pd
from datetime import datetime, timedelta
import re
import time
import warnings
import pytz
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
            current_time = datetime.now(pytz.utc)
            if signal_time > current_time:
                raise ValueError(f"Signal time cannot be in the future (Current UTC: {current_time})")
            
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

    def _extract_direction_and_price(self, text: str) -> Tuple[str, float]:
        """Extract trade direction and entry price with flexible parsing"""
        # Try different patterns
        patterns = [
            (r'(buy|sell)\s*at\s*([\d.,]+)', 1, 2),  # "buy at 100" or "sell at 100"
            (r'(entry|long|short)\s*([\d.,]+)', 1, 2),  # "entry 100" or "long 100"
            (r'([\d.,]+)\s*(buy|sell)', 2, 1)  # "100 buy" or "100 sell"
        ]
        
        for pattern, dir_group, price_group in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                direction = match.group(dir_group).lower()
                if direction in ['long', 'entry']:
                    direction = 'buy'
                elif direction == 'short':
                    direction = 'sell'
                price = float(match.group(price_group).replace(',', ''))
                return (direction, price)
        
        raise ValueError("Could not determine trade direction and entry price")

    def _extract_price(self, text: str, keywords: List[str]) -> float:
        """Helper to extract price after keywords with flexible patterns"""
        for keyword in keywords:
            # Try "keyword at price" format first
            match = re.search(fr'{keyword}\s*at\s*([\d.,]+)', text, re.IGNORECASE)
            if not match:
                # Then try just "keyword price"
                match = re.search(fr'{keyword}\s*([\d.,]+)', text, re.IGNORECASE)
            if match:
                return float(match.group(1).replace(',', ''))
        raise ValueError(f"Could not find price for any of: {keywords}")

    def _extract_take_profits(self, text: str) -> List[float]:
        """Extract all take profit levels with flexible parsing"""
        # Find all TPx at y patterns
        tp_matches = re.findall(r'TP\d*\s*at\s*([\d.,]+)', text, re.IGNORECASE)
        if tp_matches:
            return [float(x.replace(',', '')) for x in tp_matches]
        
        # Find numbered TPs without "at" (TP1 100, TP2 200)
        tp_matches = re.findall(r'TP\d*\s*([\d.,]+)', text, re.IGNORECASE)
        if tp_matches:
            return [float(x.replace(',', '')) for x in tp_matches]
        
        # Find multiple TPs in a list (TP: 100, 200, 300)
        list_match = re.search(r'TPs?:?\s*([\d.,]+(?:\s*,\s*[\d.,]+)*)', text, re.IGNORECASE)
        if list_match:
            tps = [float(x.strip()) for x in list_match.group(1).split(',')]
            return tps
        
        # Find single TP if no numbered TPs
        single_tp = re.search(r'TP\s*at\s*([\d.,]+)', text, re.IGNORECASE) or \
                   re.search(r'TP\s*([\d.,]+)', text, re.IGNORECASE)
        if single_tp:
            return [float(single_tp.group(1).replace(',', ''))]
        
        raise ValueError("Could not find take profit levels")

    def _extract_time(self, text: str) -> datetime:
        """Extract and parse time from signal text with multiple format support"""
        time_patterns = [
            # With "time:" prefix
            (r'time:\s*(\d{4}-\d{1,2}-\d{1,2}\s*\d{1,2}:\d{2}(?::\d{2})?)', '%Y-%m-%d %H:%M:%S'),
            (r'time:\s*(\d{4}/\d{1,2}/\d{1,2}\s*\d{1,2}:\d{2}(?::\d{2})?)', '%Y/%m/%d %H:%M:%S'),
            (r'time:\s*(\d{1,2}-\w{3}-\d{4}\s*\d{1,2}:\d{2}(?::\d{2})?)', '%d-%b-%Y %H:%M:%S'),
            (r'time:\s*(\d{1,2}/\d{1,2}/\d{4}\s*\d{1,2}:\d{2}(?::\d{2})?)', '%m/%d/%Y %H:%M:%S'),
            
            # Without prefix
            (r'(\d{4}-\d{1,2}-\d{1,2}\s*\d{1,2}:\d{2}(?::\d{2})?)', '%Y-%m-%d %H:%M:%S'),
            (r'(\d{4}/\d{1,2}/\d{1,2}\s*\d{1,2}:\d{2}(?::\d{2})?)', '%Y/%m/%d %H:%M:%S'),
            (r'(\d{1,2}-\w{3}-\d{4}\s*\d{1,2}:\d{2}(?::\d{2})?)', '%d-%b-%Y %H:%M:%S'),
            (r'(\d{1,2}/\d{1,2}/\d{4}\s*\d{1,2}:\d{2}(?::\d{2})?)', '%m/%d/%Y %H:%M:%S'),
            (r'(\d{1,2}\.\d{1,2}\.\d{4}\s*\d{1,2}:\d{2}(?::\d{2})?)', '%d.%m.%Y %H:%M:%S'),
            
            # Date only
            (r'time:\s*(\d{4}-\d{1,2}-\d{1,2})', '%Y-%m-%d'),
            (r'time:\s*(\d{4}/\d{1,2}/\d{1,2})', '%Y/%m/%d'),
            (r'(\d{4}-\d{1,2}-\d{1,2})', '%Y-%m-%d'),
            (r'(\d{4}/\d{1,2}/\d{1,2})', '%Y/%m/%d'),
        ]
        
        for pattern, time_format in time_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    dt = datetime.strptime(match.group(1), time_format)
                    return dt.replace(tzinfo=pytz.utc)
                except ValueError:
                    continue
        
        raise ValueError("Could not find valid time in signal. Include time like: 'Time: YYYY-MM-DD HH:MM'")

    def fetch_historical_data(self, pair: str, timeframe: str, start_time: datetime) -> pd.DataFrame:
        """Fetch OHLCV data from exchange from start_time to now (UTC)"""
        all_ohlcv = []
        current_time = start_time
        max_attempts = 5
        attempts = 0
        end_time = datetime.now(pytz.utc)
        
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

    def test_signal(self, signal: dict) -> dict:
        """Test the trade signal against historical data with proper time consideration"""
        with st.spinner("Running backtest..."):
            try:
                # Verify we have enough historical data
                if signal['signal_time'] > datetime.now(pytz.utc):
                    raise ValueError("Signal time is in the future")
                
                # Fetch data starting from 24 hours before signal time to ensure we capture the entry
                data_start = signal['signal_time'] - timedelta(hours=24)
                data = self.fetch_historical_data(
                    pair=signal['pair'],
                    timeframe='1h',
                    start_time=data_start
                )
                
                # Filter to only include data from signal_time onward
                data = data[data.index >= signal['signal_time']]
                
                if len(data) == 0:
                    raise ValueError(f"No data available after signal time {signal['signal_time']}")
                
                prices = data['close']
                direction = signal['direction']
                entry = signal['entry']
                stop_loss = signal['stop_loss']
                
                # Sort take profits based on direction
                if direction == 'buy':
                    take_profits = sorted(signal['take_profits'])  # Ascending for buy
                else:
                    take_profits = sorted(signal['take_profits'], reverse=True)  # Descending for sell
                
                # Find the exact entry point at or after signal time
                entry_idx = None
                for idx in data.index:
                    if idx >= signal['signal_time']:
                        entry_idx = idx
                        break
                
                if entry_idx is None:
                    raise ValueError("Could not find suitable entry point after signal time")
                
                entry_point = data.index.get_loc(entry_idx)
                
                # Initialize results
                results = {
                    'pair': signal['pair'],
                    'direction': direction,
                    'entry_price': entry,
                    'entry_time': entry_idx,
                    'signal_time': signal['signal_time'],
                    'stop_loss': stop_loss,
                    'take_profits': take_profits,
                    'tp_hit': [],
                    'sl_hit': False,
                    'sl_hit_time': None,
                    'max_price': None,
                    'min_price': None,
                    'result': None,
                    'data_points': len(prices),
                    'test_period': f"{data.index[0]} to {data.index[-1]}",
                    'current_price': prices.iloc[-1],
                    'current_time': data.index[-1],
                    'price_data': data
                }
                
                # Analyze price movement after entry
                for i in range(entry_point + 1, len(prices)):
                    current_price = prices.iloc[i]
                    current_time = data.index[i]
                    
                    # Update max/min prices
                    if results['max_price'] is None or current_price > results['max_price']:
                        results['max_price'] = current_price
                        results['max_price_time'] = current_time
                    if results['min_price'] is None or current_price < results['min_price']:
                        results['min_price'] = current_price
                        results['min_price_time'] = current_time
                    
                    # Check for stop loss hit (direction-specific)
                    if direction == 'buy':
                        sl_condition = current_price <= stop_loss
                        tp_condition = lambda tp: current_price >= tp
                    else:  # sell
                        sl_condition = current_price >= stop_loss
                        tp_condition = lambda tp: current_price <= tp
                    
                    if sl_condition:
                        results['sl_hit'] = True
                        results['sl_hit_time'] = current_time
                        results['result'] = 'SL hit'
                        break  # Stop checking if SL is hit
                    
                    # Check for take profit hits only if SL not hit
                    if not results['sl_hit']:
                        for j, tp in enumerate(take_profits):
                            if j not in results['tp_hit'] and tp_condition(tp):
                                results['tp_hit'].append(j)
                                results[f'tp{j+1}_hit_time'] = current_time
                    
                        # Check if all TPs hit
                        if len(results['tp_hit']) == len(take_profits):
                            results['result'] = 'All TPs hit'
                            break
                
                if not results['result']:
                    if results['sl_hit']:
                        results['result'] = 'SL hit'
                    elif results['tp_hit']:
                        results['result'] = f"Partial TP hit ({len(results['tp_hit'])}/{len(take_profits)})"
                    else:
                        results['result'] = "No targets hit"
                
                # Calculate duration
                exit_time = results['sl_hit_time'] if results['sl_hit'] else (
                    results[f'tp{len(results["tp_hit"])}_hit_time'] if results['tp_hit'] else data.index[-1]
                )
                results['duration'] = str(exit_time - results['entry_time'])
                
                # Calculate PnL
                if direction == 'buy':
                    results['pct_change'] = ((results['current_price'] - entry) / entry) * 100
                else:
                    results['pct_change'] = ((entry - results['current_price']) / entry) * 100
                
                return results
            
            except Exception as e:
                raise ValueError(f"Backtesting error: {str(e)}")

# Streamlit UI
def main():
    col1, col2 = st.columns([1, 1])
    
    with col1:
        st.subheader("Enter Trade Signal (All times UTC)")
        signal_text = st.text_area(
            "Paste your trade signal here:",
            height=200,
            help="Example formats:\n"
                 "BTC/USDT Buy at 35000, SL at 34500, TP1 at 35500, Time: 2023-11-15 08:00\n"
                 "ETH/USDT Sell at 2000, Stop Loss 2050, TP1 1950 TP2 1900, Time: 2023-12-01\n"
                 "SOL/USDT long at 120, SL 115, TPs: 125, 130, 135, Time: 01-10-2024 16:30"
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
                st.info("Try these valid example formats:\n"
                        "- BTC/USDT Buy at 35000, SL at 34500, TP1 at 35500, Time: 2023-11-15 08:00\n"
                        "- ETH/USDT Sell at 2000, Stop Loss 2050, TP1 1950 TP2 1900, Time: 2023-12-01\n"
                        "- SOL/USDT long at 120, SL 115, TPs: 125, 130, 135, Time: 01-10-2024 16:30")

    with col2:
        st.subheader("Example Signals")
        st.code("""BTC/USDT Buy at 35000, SL at 34500, TP1 at 35500, Time: 2023-11-15 08:00""")
        st.code("""ETH/USDT Sell at 2000, Stop Loss 2050, TP1 1950 TP2 1900, Time: 2023-12-01""")
        st.code("""SOL/USDT long at 120, SL 115, TPs: 125, 130, 135, Time: 01-10-2024 16:30""")
        
        st.subheader("How To Use")
        st.markdown("""
        1. **Paste your trade signal** in the left panel
        2. **Include all required details**:
           - Trading pair (e.g., BTC/USDT)
           - Direction (buy at/sell at/entry at/long/short)
           - Entry price
           - Stop loss (SL at, Stop Loss, SL)
           - Take profit levels (TP1 at, TP1, or TPs: list)
           - Time (required, multiple formats supported)
        3. Select your exchange (KuCoin or Coinbase)
        4. Select timeframe (1m, 5m, 15m, 1h, 4h, 1d)
        5. Click "Test Signal"
        
        **Features**:
        - All times in UTC
        - Supports flexible signal formats
        - Shows exact hit times for SL and TPs
        - Stops checking TPs if SL is hit first
        - Proper TP ordering for buy/sell signals
        - Calculates PnL percentage
        - Displays price movement chart
        """)

if __name__ == "__main__":
    main()
