# trading_signal_bot.py
import time
import logging
from datetime import datetime
import pandas as pd
import numpy as np
import talib
import requests
from telegram import Bot
from telegram.ext import Application, ContextTypes
import asyncio

# ================== CONFIG ==================
TELEGRAM_TOKEN = "8522628431:AAFlVti-MyhdmdveSyJ3mmMxnk5_dqJzWrg"  # Ganti dengan token botmu
CHAT_ID = "-1003306468593"  # Ganti dengan Channelirkan Channel/Group ID

TWELVE_DATA_API_KEY = "09482106ed0a4fbcacb21ba4cbd030aa" # Dapatkan di https://twelvedata.com
BASE_URL = "https://api.twelvedata.com"

# Symbol yang dipantau
SYMBOLS = {
    "XAUUSD": "XAU/USD",
    "BTCUSD": "BTC/USD",
    "ETHUSD": "ETH/USD",
    "AAPL": "AAPL",
    "TSLA": "TSLA",
    "NVDA": "NVDA",
    "SPY": "SPY",
}

TIMEFRAMES = {
    "15m": "15min",
    "1h": "1h",
    "4h": "4h",
    "1d": "1day"
}

# ============================================

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=TELEGRAM_TOKEN)

def get_twelvedata_ohlc(symbol, interval, outputsize=100):
    params = {
        "symbol": symbol,
        "interval": interval,
        "apikey": TWELVE_DATA_API_KEY,
        "outputsize": outputsize,
        "format": "JSON"
    }
    try:
        r = requests.get(f"{BASE_URL}/time_series", params=params, timeout=10)
        data = r.json()
        if 'values' not in data:
            logger.error(f"Error fetching {symbol} {interval}: {data}")
            return None
        df = pd.DataFrame(data['values'])
        df['datetime'] = pd.to_datetime(df['datetime'])
        df = df.sort_values('datetime').reset_index(drop=True)
        for col in ['open', 'high', 'low', 'close', 'volume']:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        return df
    except Exception as e:
        logger.error(f"Exception fetching {symbol}: {e}")
        return None

def calculate_indicators(df):
    close = df['close'].values
    high = df['high'].values
    low = df['low'].values

    # MACD
    macd, macdsignal, macdhist = talib.MACD(close, fastperiod=12, slowperiod=26, signalperiod=9)
    
    # Stochastic RSI
    stochrsi = talib.STOCHRSI(close, timeperiod=14, fastk_period=3, fastd_period=3, fastd_matype=0)
    stochrsi_k = stochrsi[0]
    stochrsi_d = stochrsi[1]

    df['macd'] = macd
    df['macdsignal'] = macdsignal
    df['macdhist'] = macdhist
    df['stochrsi_k'] = stochrsi_k
    df['stochrsi_d'] = stochrsi_d

    return df

def detect_cross(df):
    df['golden_cross'] = (df['macd'] > df['macdsignal']) & (df['macd'].shift(1) <= df['macdsignal'].shift(1))
    df['death_cross'] = (df['macd'] < df['macdsignal']) & (df['macd'].shift(1) >= df['macdsignal'].shift(1))
    df['hist_green'] = df['macdhist'] > 0
    df['hist_red'] = df['macdhist'] < 0
    df['hist_turning_green'] = (df['macdhist'] < 0) & (df['macdhist'] > df['macdhist'].shift(1))
    df['hist_turning_red'] = (df['macdhist'] > 0) & (df['macdhist'] < df['macdhist'].shift(1))
    return df

async def send_signal(symbol, timeframe, signal_type, reason):
    emoji = "🚀" if "Buy" in signal_type else "🔻"
    strength = "STRONG " if "Strong" in signal_type else ""
    msg = f"""
{emoji} *{strength}{signal_type} SIGNAL* {emoji}

*Symbol:* `{symbol}`
*Timeframe:* `{timeframe.upper()}`
*Time:* {datetime.now().strftime('%Y-%m-%d %H:%M WIB')}

*Reason:* {reason}

#TradingSignal #BotAlert
    """
    try:
        await bot.send_message(chat_id=CHAT_ID, text=msg.strip(), parse_mode='Markdown', disable_web_page_preview=True)
        logger.info(f"Sent {signal_type} for {symbol}")
    except Exception as e:
        logger.error(f"Failed to send message: {e}")

async def check_symbol(symbol, symbol_key):
    try:
        # Ambil data semua timeframe
        df_15m = get_twelvedata_ohlc(SYMBOLS[symbol_key], TIMEFRAMES["15m"], 100)
        df_1h = get_twelvedata_ohlc(SYMBOLS[symbol_key], TIMEFRAMES["1h"], 100)
        df_4h = get_twelvedata_ohlc(SYMBOLS[symbol_key], TIMEFRAMES["4h"], 50)
        df_1d = get_twelvedata_ohlc(SYMBOLS[symbol_key], TIMEFRAMES["1d"], 50)

        if any(x is None for x in [df_15m, df_1h, df_4h, df_1d]):
            return

        # Hitung indikator
        for df in [df_15m, df_1h, df_4h, df_1d]:
            df = calculate_indicators(df)
            df = detect_cross(df)

        last_15m = df_15m.iloc[-1]
        prev_15m = df_15m.iloc[-2]
        last_1h = df_1h.iloc[-1]
        last_4h = df_4h.iloc[-1]
        last_1d = df_1d.iloc[-1]

        # Trend confirmation dari 4h dan Daily
        trend_up_4h = last_4h['close'] > last_4h['close'].rolling(20).mean()
        trend_up_daily = last_1d['close'] > last_1d['close'].rolling(20).mean()
        higher_timeframe_uptrend = trend_up_4h and trend_up_daily

        current_price = last_15m['close']

        # === LOGIKA BUY ===
        if higher_timeframe_uptrend:
            # Buy biasa
            if last_15m['hist_turning_green'] and last_15m['stochrsi_k'] > 40:
                await send_signal(symbol, "15m", "BUY", "MACD hist turning green + StochRSI > 40 + Higher TF Uptrend")
            
            if last_1h['hist_turning_green'] and last_1h['stochrsi_k'] > 40:
                await send_signal(symbol, "1h", "BUY", "MACD 1H turning green + StochRSI > 40 + Uptrend")

            # Strong Buy - Golden Cross
            if last_15m['golden_cross']:
                await send_signal(symbol, "15m", "STRONG BUY", "🚨 GOLDEN CROSS DETECTED + Uptrend Confirmed")
            if last_1h['golden_cross']:
                await send_signal(symbol, "1h", "STRONG BUY", "🚨 GOLDEN CROSS 1H + Strong Uptrend")

        # === LOGIKA SELL ===
        if not higher_timeframe_uptrend:
            # Sell biasa
            if last_15m['hist_turning_red'] and last_15m['stochrsi_k'] > 80:
                await send_signal(symbol, "15m", "SELL", "MACD hist turning red + StochRSI > 80 + Downtrend/Correction")

            if last_1h['hist_turning_red'] and last_1h['stochrsi_k'] > 80:
                await send_signal(symbol, "1h", "SELL", "MACD 1H turning red + StochRSI > 80")

            # Strong Sell - Death Cross
            if last_15m['death_cross']:
                await send_signal(symbol, "15m", "STRONG SELL", "💀 DEATH CROSS DETECTED")
            if last_1h['death_cross']:
                await send_signal(symbol, "1h", "STRONG SELL", "💀 DEATH CROSS 1H")

    except Exception as e:
        logger.error(f"Error checking {symbol}: {e}")

async def main_loop():
    logger.info("Trading Signal Bot Started...")
    await bot.send_message(CHAT_ID, "🤖 *Trading Signal Bot Started!*\nMonitoring XAUUSD, Crypto & US Stocks...", parse_mode='Markdown')

    while True:
        try:
            for symbol_key, symbol in SYMBOLS.items():
                logger.info(f"Checking {symbol_key}...")
                await check_symbol(symbol_key, symbol_key)
                await asyncio.sleep(5)  # delay antar symbol

            # Tunggu 3 menit sebelum scan ulang (bisa diatur)
            logger.info("Scan completed. Sleeping 180 seconds...")
            await asyncio.sleep(180)

        except Exception as e:
            logger.error(f"Main loop error: {e}")
            await asyncio.sleep(60)

if __name__ == "__main__":
    # Install dulu: pip install pandas numpy talib python-telegram-bot requests
    asyncio.run(main_loop())
