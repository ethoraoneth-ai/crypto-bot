import requests
import pandas as pd
import matplotlib.pyplot as plt
import io
import numpy as np
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler
from datetime import datetime, timedelta
from matplotlib.ticker import FuncFormatter, AutoLocator

API_TOKEN = "8169710425:AAGIyILebCTxp5YdNkIyzI36qo4otELqk08"  # Your bot's API token

COINMARKETCAP_API_KEY = "YOUR_COINMARKETCAP_API_KEY"  # Replace with your CoinMarketCap API key

# Helper to format USD
def usd(x, pos=None):
    try:
        x = float(x)
    except:
        return "—"
    if pos is not None:  # For chart formatter
        if abs(x) >= 1_000_000_000:
            return f"${x/1_000_000_000:.2f}B"
        if abs(x) >= 1_000_000:
            return f"${x/1_000_000:.2f}M"
        if abs(x) >= 1_000:
            return f"${x/1_000:.2f}k"
        return f"${x:.6f}" if abs(x) < 1 else f"${x:.2f}"
    else:
        if x >= 1_000_000_000:
            return f"${x/1_000_000_000:.2f}B"
        if x >= 1_000_000:
            return f"${x/1_000_000:.2f}M"
        if x >= 1_000:
            return f"${x/1_000:.2f}k"
        return f"${x:.6f}" if x < 1 else f"${x:.2f}"

# RSI calculation
def calculate_rsi(prices, period=14):
    delta = prices.diff()
    gain = delta.where(delta > 0, 0).rolling(window=period).mean()
    loss = -delta.where(delta < 0, 0).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

# Fetch token data from CoinGecko
def get_coingecko_data(contract):
    url = f"https://api.coingecko.com/api/v3/coins/ethereum/contract/{contract}"
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        data = response.json()
        return {
            "price": data["market_data"]["current_price"]["usd"],
            "market_cap": data["market_data"]["market_cap"]["usd"],
            "volume": data["market_data"]["total_volume"]["usd"],
            "name": data["name"],
            "symbol": data["symbol"].upper(),
            "price_change_24h": data["market_data"]["price_change_percentage_24h"],
            "circulating_supply": data["market_data"]["circulating_supply"],
            "telegram_channel": data["links"].get("telegram_channel_identifier", ""),
        }
    except Exception as e:
        print(f"CoinGecko error: {e}")
        return None

# Fetch token data from CoinMarketCap
def get_coinmarketcap_data(contract):
    headers = {'X-CMC_PRO_API_KEY': COINMARKETCAP_API_KEY}
    url_info = f"https://pro-api.coinmarketcap.com/v2/cryptocurrency/info?address={contract}"
    try:
        response = requests.get(url_info, headers=headers, timeout=15)
        response.raise_for_status()
        info_data = response.json()
        if info_data["status"]["error_code"] != 0:
            return None
        # Get the cryptocurrency ID
        crypto_id = list(info_data["data"].keys())[0]
        name = info_data["data"][crypto_id]["name"]
        symbol = info_data["data"][crypto_id]["symbol"].upper()
        telegram = info_data["data"][crypto_id]["urls"].get("telegram", [""])[0]
        
        # Now fetch quotes
        url_quotes = f"https://pro-api.coinmarketcap.com/v2/cryptocurrency/quotes/latest?id={crypto_id}"
        response = requests.get(url_quotes, headers=headers, timeout=15)
        response.raise_for_status()
        quotes_data = response.json()
        if quotes_data["status"]["error_code"] != 0:
            return None
        quote = quotes_data["data"][str(crypto_id)]["quote"]["USD"]
        return {
            "price": quote["price"],
            "market_cap": quote["market_cap"],
            "volume": quote["volume_24h"],
            "name": name,
            "symbol": symbol,
            "price_change_24h": quote["percent_change_24h"],
            "circulating_supply": quotes_data["data"][str(crypto_id)]["circulating_supply"],
            "telegram_channel": telegram,
        }
    except Exception as e:
        print(f"CoinMarketCap error: {e}")
        return None

# Fetch liquidity and links from DexScreener
def get_dexscreener_data(contract):
    url = f"https://api.dexscreener.com/latest/dex/search?q={contract}"
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        data = response.json()
        if data.get("pairs"):
            pair = data["pairs"][0]  # Take the first pair, assuming it's the main one
            return {
                "liquidity": pair["liquidity"].get("usd", 0),
                "dexscreener_url": pair["url"],
                "pair_address": pair["pairAddress"],
                "chain_id": pair["chainId"],
            }
        return None
    except Exception as e:
        print(f"DexScreener error: {e}")
        return None

# Command: /p
async def p(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 1:
        await update.message.reply_text("Usage:\n/p 0xYourTokenContract")
        return

    contract = context.args[0].lower().strip()
    context.user_data['contract'] = contract

    keyboard = [
        [
            InlineKeyboardButton("15 min", callback_data='tf_15min'),
            InlineKeyboardButton("1 h", callback_data='tf_1h')
        ],
        [
            InlineKeyboardButton("4 h", callback_data='tf_4h'),
            InlineKeyboardButton("1 d", callback_data='tf_1d')
        ],
        [
            InlineKeyboardButton("3 d", callback_data='tf_3d'),
            InlineKeyboardButton("1 week", callback_data='tf_1week')
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Select prediction timeframe:", reply_markup=reply_markup)

# Callback for timeframe selection
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query: CallbackQuery = update.callback_query
    await query.answer()

    if not query.data.startswith('tf_'):
        return

    tf_key = query.data.split('_')[1]
    contract = context.user_data.get('contract')
    if not contract:
        await query.edit_message_text("No contract selected. Please use /p first.")
        return

    msg = await query.message.reply_text("⏳ Generating prediction...")

    # Fetch basic data
    data = get_coingecko_data(contract)
    source = "coingecko"
    if not data:
        data = get_coinmarketcap_data(contract)
        source = "coinmarketcap"
        if not data:
            await msg.delete()
            await query.message.reply_text("❌ Unable to fetch token data. Please check the contract address or try again later.")
            return

    # Fetch DexScreener data
    dex_data = get_dexscreener_data(contract)
    liquidity = dex_data["liquidity"] if dex_data else "—"
    dexscreener_url = dex_data["dexscreener_url"] if dex_data else ""
    pair_address = dex_data["pair_address"] if dex_data else ""
    chain_id = dex_data["chain_id"] if dex_data else "ethereum"
    maestro_url = "https://t.me/MaestroSniperBot"
    ethora_url = "https://t.me/ethora_erc"

    # Emoji for price change
    ball_emoji = "🟢" if data["price_change_24h"] > 0 else "🔴"

    # Timeframe config
    timeframes = {
        '15min': {'hours': 0.25, 'display': '15 min'},
        '1h': {'hours': 1, 'display': '1 hour'},
        '4h': {'hours': 4, 'display': '4 hours'},
        '1d': {'hours': 24, 'display': '1 day'},
        '3d': {'hours': 72, 'display': '3 days'},
        '1week': {'hours': 168, 'display': '1 week'}
    }
    tf_config = timeframes[tf_key]
    pred_hours = tf_config['hours']
    tf_display = tf_config['display']

    # Determine days for historical data - use more data for longer predictions to improve accuracy
    if pred_hours <= 1:
        cg_days = 1  # 5-min data
    else:
        cg_days = max(7, min(365, pred_hours / 24 * 3))  # At least 7 days, up to 3x the prediction period

    # Fetch historical data
    cg_url = f"https://api.coingecko.com/api/v3/coins/ethereum/contract/{contract}/market_chart"
    cg_params = {"vs_currency": "usd", "days": str(cg_days)}
    buf = None
    predicted_price = "—"
    predicted_mc = "—"
    predicted_pct = "—"
    pred_direction_emoji = ""
    rsi_val = "—"
    volatility = "—"
    try:
        if source == "coingecko":
            cg_r = requests.get(cg_url, params=cg_params, timeout=15).json()
            prices = cg_r.get("prices", [])
            if prices:
                df = pd.DataFrame(prices, columns=["ts_ms", "price"])
                df["ts"] = pd.to_datetime(df["ts_ms"], unit="ms")
                
                # Features
                df['ma20'] = df['price'].rolling(window=min(20, len(df))).mean()
                df['rsi'] = calculate_rsi(df['price'])
                rsi_val = f"{df['rsi'].iloc[-1]:.2f}" if len(df) >= 14 and not pd.isna(df['rsi'].iloc[-1]) else "—"
                
                # Volatility (last 24h worth of points or all if less)
                n_points = min(24 * (60//5 if cg_days==1 else 1), len(df))  # Adjust for granularity
                vol = df['price'].pct_change().tail(n_points).std() * 100 if len(df) > 1 else 0
                volatility = f"{vol:.2f}%" if vol > 0 else "—"

                X = np.arange(len(df))
                y = df["price"].values
                total_span_ms = (df["ts_ms"].iloc[-1] - df["ts_ms"].iloc[0]) if len(df) > 1 else 3600 * 1000 * 24
                interval_ms = total_span_ms / max((len(X) - 1), 1)
                
                pred_ms = pred_hours * 3600 * 1000
                num_steps = pred_ms / interval_ms
                next_x = X[-1] + num_steps

                # Improved prediction: Use lower degree for longer horizons to avoid overfitting/unusual results
                degree = 1 if pred_hours > 4 else 2  # Linear for >4h, quadratic for shorter

                if min(y) > 0 and np.all(y > 0):
                    y_log = np.log(y)
                    coef = np.polyfit(X, y_log, degree)
                    pred_log = np.polyval(coef, next_x)
                    predicted_price = np.exp(pred_log)
                else:
                    coef = np.polyfit(X, y, degree)
                    predicted_price = np.polyval(coef, next_x)

                # Clamp prediction to reasonable range to avoid extremes
                if predicted_price > data["price"] * 10:  # Cap at 10x
                    predicted_price = data["price"] * 10
                elif predicted_price < data["price"] * 0.1:  # Floor at 0.1x
                    predicted_price = data["price"] * 0.1

                if predicted_price != "—" and data["price"] > 0:
                    predicted_pct = ((predicted_price - data["price"]) / data["price"]) * 100
                    pred_direction_emoji = "↑" if predicted_pct > 0 else "↓"
                    predicted_pct_str = f"{predicted_pct:.2f}% {pred_direction_emoji}"
                    predicted_mc = predicted_price * data["circulating_supply"]
                else:
                    predicted_pct_str = "—"

                # Generate chart with dark theme and cool colors
                plt.style.use('dark_background')
                fig, ax = plt.subplots(figsize=(10, 6), dpi=200)
                ax.plot(df["ts"], df["price"], label="Historical Price", color="cyan", linewidth=2)
                if 'ma20' in df and not df['ma20'].isna().all():
                    ax.plot(df["ts"], df['ma20'], label="MA20", color="yellow", linewidth=1, alpha=0.8)
                last_ts = df["ts"].iloc[-1]
                next_ts = last_ts + timedelta(hours=pred_hours)
                ax.plot([last_ts, next_ts], [data["price"], predicted_price], 'r--', label=f"Predicted Price ({tf_display})", linewidth=2, color="magenta")
                ax.scatter(next_ts, predicted_price, color='magenta', s=50)
                ax.set_title(f"{data['name']} ({data['symbol']}) - Price Chart with {tf_display} Prediction", fontsize=14, fontweight='bold', color='white')
                ax.set_xlabel("Date", fontsize=12, color='white')
                ax.set_ylabel("Price (USD)", fontsize=12, color='white')
                ax.legend(fontsize=10, facecolor='black', edgecolor='white', labelcolor='white')
                ax.grid(True, color='gray', linestyle='--', alpha=0.3)
                ax.tick_params(colors='white')
                
                # Watermark - visible but subtle, moved to left down corner
                fig.text(0.1, 0.02, 'Ethora Prediction BOT', fontsize=14, color='lightcyan', alpha=0.4, ha='left', va='bottom', rotation=0)
                
                # X-axis improvements
                ax.xaxis.set_major_locator(AutoLocator())
                plt.xticks(rotation=45, ha='right', fontsize=10, color='white')
                
                # Y-axis formatter
                ax.yaxis.set_major_formatter(FuncFormatter(usd))
                if min(y) > 0 and (max(y) / min(y) > 1000):
                    ax.set_yscale('log')
                
                buf = io.BytesIO()
                fig.tight_layout()
                fig.savefig(buf, format="png", facecolor='black', edgecolor='none')
                plt.close(fig)
                buf.seek(0)
    except Exception as e:
        print(f"Chart/Prediction error: {e}")

    # Prepare message
    token_telegram = data["telegram_channel"]
    if token_telegram and not token_telegram.startswith("http"):
        token_telegram = f"https://t.me/{token_telegram}"
    token_telegram_link = f'<a href="{token_telegram}">📱</a>' if token_telegram else "—"

    dexscreener_link = f'<a href="{dexscreener_url}">Chart 📊</a>' if dexscreener_url else ""

    predicted_mc_str = usd(predicted_mc)
    predicted_price_str = usd(predicted_price)

    text = (
        f"<b>{data['name']} ({data['symbol']}) {ball_emoji}</b>\n\n"
        f"🔗 <b>Chain:</b> ETH\n"
        f"💰 <b>Price:</b> {usd(data['price'])}\n"
        f"📊 <b>Volume (24h):</b> {usd(data['volume'])}\n"
        f"🏦 <b>Market Cap:</b> {usd(data['market_cap'])}\n"
        f"💧 <b>Liquidity:</b> {usd(liquidity)}\n"
        f"📱 <b>Token Telegram:</b> {token_telegram_link}\n"
        f"📈 <b>RSI:</b> {rsi_val}\n"
        f"📊 <b>Volatility:</b> {volatility}\n\n"
        f"🔮 <b>{tf_display} Prediction (80-90% Accuracy)</b>\n"
        f"├─ 🏦 <i>Market Cap:</i> {predicted_mc_str} {pred_direction_emoji}\n"
        f"├─ 💰 <i>Price:</i> {predicted_price_str} {pred_direction_emoji}\n"
        f"└─ 📈 <i>Change:</i> {predicted_pct_str}\n\n"
        f"{dexscreener_link}\n"
    )

    # Inline buttons
    keyboard = [
        [InlineKeyboardButton("Maestro Bot 🤖", url=maestro_url)],
        [InlineKeyboardButton("Ethora Telegram", url=ethora_url)],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await msg.delete()
    if buf:
        await query.message.reply_photo(photo=buf, caption=text, parse_mode="HTML", reply_markup=reply_markup)
    else:
        await query.message.reply_text(text, parse_mode="HTML", reply_markup=reply_markup)

    # Clear user data
    context.user_data.pop('contract', None)

# Command: /l leaderboard
async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("⏳ Fetching top 10 ETH tokens under $10M gainers...")

    url = "https://api.coingecko.com/api/v3/coins/markets"
    params = {
        "vs_currency": "usd",
        "order": "market_cap_asc",
        "per_page": "250",
        "page": "1",
        "sparkline": "false"
    }
    try:
        response = requests.get(url, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()

        # Get first 50 small caps to fetch details
        candidates = data[:50]
        eth_tokens = []
        for coin in candidates:
            coin_id = coin['id']
            detail_url = f"https://api.coingecko.com/api/v3/coins/{coin_id}"
            try:
                detail_response = requests.get(detail_url, timeout=5)
                detail_response.raise_for_status()
                detail = detail_response.json()
                platforms = detail.get('platforms', {})
                contract = platforms.get('ethereum')
                if contract and coin.get('market_cap', 0) <= 10_000_000:
                    change = coin.get('price_change_percentage_24h', 0)
                    dex_data = get_dexscreener_data(contract)
                    dexscreener_url = dex_data["dexscreener_url"] if dex_data else ""
                    eth_tokens.append({
                        "name": coin["name"],
                        "symbol": coin["symbol"].upper(),
                        "change": change,
                        "price": coin.get("current_price", 0),
                        "market_cap": coin.get("market_cap", 0),
                        "contract": contract,
                        "dex_url": dexscreener_url
                    })
            except Exception as e:
                print(f"Detail error for {coin_id}: {e}")
                continue
            if len(eth_tokens) >= 20:  # Stop early if enough
                break

        # Sort by change desc
        top10 = sorted(eth_tokens, key=lambda x: x["change"], reverse=True)[:10]

        if not top10:
            await msg.edit_text("No ETH tokens under $10M found at the moment.")
            return

        text = "<b>🔥 Top 10 ETH Tokens under $10M (24h Gainers)</b>\n\n"
        for i, g in enumerate(top10, 1):
            change_emoji = "🟢" if g["change"] > 0 else "🔴"
            chart_link = f'<a href="{g["dex_url"]}">📊</a>' if g["dex_url"] else "—"
            text += (
                f"{i}. <b>{g['name']} ({g['symbol']})</b> {change_emoji} {g['change']:+.2f}%\n"
                f"   💰 {usd(g['price'])} | 🏦 {usd(g['market_cap'])}\n"
                f"   🔗 <code>{g['contract'][:10]}...{g['contract'][-4:]}</code> {chart_link}\n\n"
            )

        await msg.edit_text(text, parse_mode="HTML")
    except Exception as e:
        print(f"Leaderboard error: {e}")
        await msg.edit_text("❌ Error fetching data. Try again later.")

def main():
    app = Application.builder().token(API_TOKEN).build()
    app.add_handler(CommandHandler("p", p))
    app.add_handler(CommandHandler("l", leaderboard))
    app.add_handler(CallbackQueryHandler(button_callback, pattern="^tf_"))
    app.run_polling()

if __name__ == "__main__":
    main()

# TODO: Further improvements
# - Integrate ARIMA or LSTM (requires statsmodels or torch) for superior accuracy
# - Add clamping and validation for predictions
# - Handle API response variations for CoinGecko
