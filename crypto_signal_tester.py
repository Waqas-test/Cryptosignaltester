import streamlit as st
import ccxt
import pandas as pd
from datetime import datetime, timedelta
import re
import time
import warnings
from typing import List

# Configure page
st.set_page_config(page_title="Crypto Trade Signal Tester", layout="wide")
st.title("📈 Crypto Trade Signal Tester")

# Initialize exchange connection
@st.cache_resource
def init_exchange(exchange_name='binance'):
    exchange = getattr(ccxt, exchange_name)({
        'enableRateLimit': True,
        'options': {'adjustForTimeDifference': True}
    })
    exchange.load_markets()
    return exchange

class CryptoTradeTester:
    def __init__(self, exchange='binance'):
        self.exchange = init_exchange(exchange)
    
    def parse_signal(self, signal_text: str) -> dict:
        """Parse unstructured trade signal text into structured format"""
        # Extract pair
        pair_match = re.search(r'([A-Z]{3,}\/[A-Z]{3,})', signal_text)
        if not pair_match:
            raise ValueError("Could not find trading pair in signal")
        pair = pair_match.group(1)
        
        # Extract prices
        entry = self._extract_price(signal_text, ['entry', 'buy at', 'enter at'])
        stop_loss = self._extract_price(signal_text, ['sl', 'stop loss', 'stoploss'])
        take_profits = self._extract_take_profits(signal_text)
        
        # Extract signal time (required)
        signal_time = self._extract_time(signal_text)
        
        # Validate signal time is not in future
        if signal_time > datetime.now():
            raise ValueError("Signal time cannot be in the future")
        
        return {
            'pair': pair,
            'entry': entry,
            'stop_loss': stop_loss,
            'take_profits': take_profits,
            'signal_time': signal_time
        }
    
    def _extract_price(self, text: str, keywords: List[str]) -> float:
        """Helper to extract price after keywords"""
        for keyword in keywords:
            match = re.search(fr'{keyword}\s*([\d.,]+)', text, re.IGNORECASE)
            if match:
                return float(match.group(1).replace(',', ''))
        raise ValueError(f"Could not find price for {keywords}")
    
    def _extract_take_profits(self, text: str) -> List[float]:
        """Extract all take profit levels"""
        tp_matches = re.findall(r'TP\d*\s*at\s*([\d.,]+)', text, re.IGNORECASE)
        if tp_matches:
            return [float(x.replace(',', '')) for x in tp_matches]
        
        single_tp = re.search(r'TP\s*at\s*([\d.,]+)', text, re.IGNORECASE)
        if single_tp:
            return [float(single_tp.group(1).replace(',', ''))]
        
        raise ValueError("Could not find take profit levels")
    
    def _extract_time(self, text: str) -> datetime:
        """Extract and parse time from signal text"""
        time_patterns = [
            (r'time:\s*(\d{4}-\d{1,2}-\d{1,2}\s*\d{1,2}:\d{2}(?::\d{2})?)', '%Y-%m-%d %H:%M:%S'),
            (r'time:\s*(\d{4}/\d{1,2}/\d{1,2}\s*\d{1,2}:\d{2}(?::\d{2})?)', '%Y/%m/%d %H:%M:%S'),
            (r'time:\s*(\d{1,2}-\w{3}-\d{4}\s*\d{1,2}:\d{2}(?::\d{2})?)', '%d-%b-%Y %H:%M:%S'),
            (r'(\d{4}-\d{1,2}-\d{1,2}\s*\d{1,2}:\d{2}(?::\d{2})?)', '%Y-%m-%d %H:%M:%S'),
            (r'(\d{4}/\d{1,2}/\d{1,2}\s*\d{1,2}:\d{2}(?::\d{2})?)', '%Y/%m/%d %H:%M:%S'),
            (r'(\d{1,2}-\w{3}-\d{4}\s*\d{1,2}:\d{2}(?::\d{2})?)', '%d-%b-%Y %H:%M:%S'),
            (r'(\d{1,2}/\d{1,2}/\d{4}\s*\d{1,2}:\d{2}(?::\d{2})?)', '%m/%d/%Y %H:%M:%S'),
            (r'(\d{1,2}\.\d{1,2}\.\d{4}\s*\d{1,2}:\d{2}(?::\d{2})?)', '%d.%m.%Y %H:%M:%S'),
        ]
        
        for pattern, time_format in time_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    return datetime.strptime(match.group(1), time_format)
                except ValueError:
                    if time_format.endswith(':%S'):
                        return datetime.strptime(match.group(1), time_format[:-3])
                    continue
        
        raise ValueError("Could not find valid time in signal. Include time like: 'Time: YYYY-MM-DD HH:MM'")
    
    def fetch_historical_data(self, pair: str, timeframe: str, start_time: datetime) -> pd.DataFrame:
        """Fetch OHLCV data from exchange from start_time to now"""
        all_ohlcv = []
        current_time = start_time
        max_attempts = 5
        attempts = 0
        end_time = datetime.now()
        
        progress_bar = st.progress(0, text="Fetching historical data...")
        status_text = st.empty()
        
        while current_time < end_time and attempts < max_attempts:
            try:
                status_text.text(f"Fetching data from {current_time}...")
                since = int(current_time.timestamp() * 1000)
                ohlcv = self.exchange.fetch_ohlcv(pair, timeframe, since, limit=1000)
                
                if not ohlcv:
                    break
                
                df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
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
        """Test the trade signal against historical data"""
        with st.spinner("Running backtest..."):
            data = self.fetch_historical_data(
                pair=signal['pair'],
                timeframe='1h',
                start_time=signal['signal_time']
            )
            
            prices = data['close']
            entry = signal['entry']
            stop_loss = signal['stop_loss']
            take_profits = sorted(signal['take_profits'])
            
            # Find closest entry point
            entry_idx = (prices - entry).abs().idxmin()
            entry_point = data.index.get_loc(entry_idx)
            
            # Initialize results
            results = {
                'pair': signal['pair'],
                'entry_price': entry,
                'entry_time': entry_idx,
                'signal_time': signal['signal_time'],
                'stop_loss': stop_loss,
                'take_profits': take_profits,
                'tp_hit': [],
                'sl_hit': False,
                'max_price': None,
                'min_price': None,
                'result': None,
                'data_points': len(prices),
                'test_period': f"{data.index[0]} to {data.index[-1]}",
                'current_price': prices.iloc[-1],
                'current_time': data.index[-1],
                'price_data': data
            }
            
            # Analyze price movement
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
                
                # Check for stop loss
                if (entry > stop_loss and current_price <= stop_loss) or \
                   (entry < stop_loss and current_price >= stop_loss):
                    results['sl_hit'] = True
                    results['result'] = 'SL hit'
                    results['exit_time'] = current_time
                    break
                
                # Check take profits
                for j, tp in enumerate(take_profits):
                    if j not in results['tp_hit']:
                        if (entry < tp and current_price >= tp) or \
                           (entry > tp and current_price <= tp):
                            results['tp_hit'].append(j)
                            results[f'tp{j+1}_hit_time'] = current_time
                
                if len(results['tp_hit']) == len(take_profits):
                    results['result'] = 'All TPs hit'
                    results['exit_time'] = current_time
                    break
            
            if not results['result']:
                if results['tp_hit']:
                    results['result'] = f"Partial TP hit ({len(results['tp_hit'])}/{len(take_profits)})"
                    results['exit_time'] = data.index[-1]
                else:
                    results['result'] = "No targets hit"
                    results['exit_time'] = data.index[-1]
            
            results['duration'] = str(results['exit_time'] - results['entry_time'])
            
            return results

# Streamlit UI
def main():
    col1, col2 = st.columns([1, 1])
    
    with col1:
        st.subheader("Enter Trade Signal")
        signal_text = st.text_area(
            "Paste your trade signal here:",
            height=200,
            help="Example: BTC/USDT Buy at 35000, SL at 34500, TP1 at 35500, Time: 2023-11-15 08:00"
        )
        
        exchange = st.selectbox(
            "Exchange",
            ['binance', 'kucoin', 'coinbase', 'bybit'],
            index=0
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
                
                # Display parsed signal
                with st.expander("Parsed Signal Details", expanded=True):
                    st.write(f"**Pair:** {signal['pair']}")
                    st.write(f"**Entry Price:** {signal['entry']}")
                    st.write(f"**Stop Loss:** {signal['stop_loss']}")
                    st.write(f"**Take Profits:** {', '.join(map(str, signal['take_profits']))}")
                    st.write(f"**Signal Time:** {signal['signal_time']}")
                
                # Run backtest
                results = tester.test_signal(signal)
                
                # Display results
                st.subheader("Backtest Results")
                
                # Metrics row
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Entry Price", f"{results['entry_price']}")
                delta = ((results['current_price']-results['entry_price'])/results['entry_price']*100)
                m2.metric("Current Price", f"{results['current_price']}", f"{delta:.2f}%")
                m3.metric("Max Price", f"{results['max_price']}")
                m4.metric("Min Price", f"{results['min_price']}")
                
                # Results details
                with st.expander("Detailed Results", expanded=True):
                    st.write(f"**Signal Time:** {results['signal_time']}")
                    st.write(f"**Entry Time:** {results['entry_time']}")
                    st.write(f"**Test Period:** {results['test_period']}")
                    st.write(f"**Duration:** {results['duration']}")
                    st.write(f"**Data Points:** {results['data_points']}")
                    
                    st.write("\n**Stop Loss:**")
                    st.write(f"{results['stop_loss']} - {'✅ Hit' if results['sl_hit'] else '❌ Not Hit'}")
                    
                    st.write("\n**Take Profits:**")
                    for i, tp in enumerate(results['take_profits']):
                        hit = i in results['tp_hit']
                        st.write(f"TP{i+1}: {tp} - {'✅ Hit' if hit else '❌ Not Hit'} " + 
                                (f"at {results[f'tp{i+1}_hit_time']}" if hit else ""))
                    
                    st.write(f"\n**Final Result:** {results['result']}")
                
                # Price chart
                st.subheader("Price Movement")
                st.line_chart(results['price_data']['close'])
                
            except Exception as e:
                st.error(f"Error: {str(e)}")
                st.info("Example format: BTC/USDT Buy at 35000, SL at 34500, TP1 at 35500, Time: 2023-11-15 08:00")

    with col2:
        st.subheader("Example Signals")
        st.code("""BTC/USDT Buy at 35000, SL at 34500, TP1 at 35500, Time: 2023-11-15 08:00""")
        st.code("""ETH/BTC Sell at 0.075, Stop Loss 0.078, TP1 0.072, TP2 0.070, Time: 2023-12-01 12:00""")
        st.code("""SOL/USDT Entry 120, SL 115, TP1 125, TP2 130, TP3 135, Time: 2024-01-10 16:30""")
        
        st.subheader("How To Use")
        st.markdown("""
        1. Paste your trade signal in the left panel
        2. Include all required details:
           - Trading pair (e.g., BTC/USDT)
           - Entry price
           - Stop loss
           - Take profit levels
           - Signal time (required)
        3. Select your exchange
        4. Click "Test Signal"
        
        The app will:
        - Parse your signal
        - Fetch historical data from the signal time
        - Simulate the trade
        - Show which targets were hit
        """)

if __name__ == "__main__":
    main()