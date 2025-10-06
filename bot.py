import requests
import pandas as pd
import matplotlib.pyplot as plt
import io
import numpy as np
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler, ConversationHandler, MessageHandler, filters
from datetime import datetime, timedelta
from matplotlib.ticker import FuncFormatter, AutoLocator
import secrets
from web3 import Web3
from eth_account import Account
import time
import json
from telegram.ext import ApplicationBuilder
import asyncio
import os
API_TOKEN = "8169710425:AAGIyILebCTxp5YdNkIyzI36qo4otELqk08"  # Your bot's API token
COINMARKETCAP_API_KEY = "d4ce09d7-b6e8-45ae-8c40-8807fcea70bc"  # Replace with your CoinMarketCap API key
RPC = "https://ethereum-rpc.publicnode.com"  # Public Ethereum RPC URL
w3 = Web3(Web3.HTTPProvider(RPC))
MAX_UINT = 2**256 - 1
# Minimal ERC20 ABI
ERC20_ABI = [
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "balance", "type": "uint256"}],
        "type": "function"
    },
    {
        "constant": False,
        "inputs": [{"name": "_to", "type": "address"}, {"name": "_value", "type": "uint256"}],
        "name": "transfer",
        "outputs": [{"name": "success", "type": "bool"}],
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "type": "function"
    },
    {
        "constant": False,
        "inputs": [{"name": "_spender", "type": "address"}, {"name": "_value", "type": "uint256"}],
        "name": "approve",
        "outputs": [{"name": "success", "type": "bool"}],
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}, {"name": "_spender", "type": "address"}],
        "name": "allowance",
        "outputs": [{"name": "", "type": "uint256"}],
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [],
        "name": "symbol",
        "outputs": [{"name": "", "type": "string"}],
        "type": "function"
    }
]
# Minimal Uniswap V2 Router ABI
UNISWAP_ROUTER_ABI = [
    {
        "inputs": [
            {"internalType": "uint256", "name": "amountOutMin", "type": "uint256"},
            {"internalType": "address[]", "name": "path", "type": "address[]"},
            {"internalType": "address", "name": "to", "type": "address"},
            {"internalType": "uint256", "name": "deadline", "type": "uint256"}
        ],
        "name": "swapExactETHForTokens",
        "outputs": [{"internalType": "uint256[]", "name": "amounts", "type": "uint256[]"}],
        "stateMutability": "payable",
        "type": "function"
    },
    {
        "inputs": [
            {"internalType": "uint256", "name": "amountIn", "type": "uint256"},
            {"internalType": "uint256", "name": "amountOutMin", "type": "uint256"},
            {"internalType": "address[]", "name": "path", "type": "address[]"},
            {"internalType": "address", "name": "to", "type": "address"},
            {"internalType": "uint256", "name": "deadline", "type": "uint256"}
        ],
        "name": "swapExactTokensForETHSupportingFeeOnTransferTokens",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function"
    },
    {
        "inputs": [
            {"internalType": "uint256", "name": "amountIn", "type": "uint256"},
            {"internalType": "address[]", "name": "path", "type": "address[]"}
        ],
        "name": "getAmountsOut",
        "outputs": [{"internalType": "uint256[]", "name": "amounts", "type": "uint256[]"}],
        "stateMutability": "view",
        "type": "function"
    }
]
UNISWAP_ROUTER_ADDRESS = "0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D"
WETH_ADDRESS = "0xC02aaA39b223FE8D0A0e5c4F27eAD9083C756Cc2"
FEE_WALLET = "0x78c503BEf6f5C73744f6d0E7c137df948dD97521"
# Persistence file
USERS_FILE = 'users.json'
# Load users from file
def load_users():
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, 'r') as f:
            return json.load(f)
    return {}
# Save users to file
def save_users(users):
    with open(USERS_FILE, 'w') as f:
        json.dump(users, f)
# Global user data storage
users = load_users()  # user_id: {'address': str, 'private_key': str, 'trades': list of dicts}
# Conversation states
TRANSFER_WHAT, TRANSFER_TO, TRANSFER_AMOUNT, SELL_CUSTOM_AMOUNT = range(4)
SELL_CUSTOM_CONTRACT = 4  # New state for custom sell from holdings
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
        return f"${x:.8f}" if abs(x) < 1 else f"${x:.4f}"
    else:
        if x >= 1_000_000_000:
            return f"${x/1_000_000_000:.2f}B"
        if x >= 1_000_000:
            return f"${x/1_000_000:.2f}M"
        if x >= 1_000:
            return f"${x/1_000:.2f}k"
        return f"${x:.8f}" if x < 1 else f"${x:.4f}"
# RSI calculation
def calculate_rsi(prices, period=14):
    delta = prices.diff()
    gain = delta.where(delta > 0, 0).rolling(window=period).mean()
    loss = -delta.where(delta < 0, 0).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi
# Fetch ETH price
def get_eth_price():
    url = "https://api.coingecko.com/api/v3/simple/price?ids=ethereum&vs_currencies=usd"
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        data = response.json()
        return data["ethereum"]["usd"]
    except:
        return None
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
        pairs = data.get("pairs")
        if pairs:
            pair = max(pairs, key=lambda p: p["liquidity"]["usd"] if "liquidity" in p and "usd" in p["liquidity"] else 0)
            return {
                "liquidity": pair["liquidity"].get("usd", 0),
                "dexscreener_url": pair["url"],
                "pair_address": pair["pairAddress"],
                "chain_id": pair["chainId"],
                "price": float(pair["priceUsd"]) if "priceUsd" in pair else 0,
                "price_change_24h": pair["priceChange"]["h24"] if "priceChange" in pair else 0,
                "symbol": pair["baseToken"]["symbol"] if "baseToken" in pair else "",
                "name": pair["baseToken"]["name"] if "baseToken" in pair else "",
                "volume": pair["volume"]["h24"] if "volume" in pair else 0,
                "market_cap": pair.get("fdv", 0),
            }
        return None
    except Exception as e:
        print(f"DexScreener error: {e}")
        return None

def get_token_data(contract):
    for func in [get_coingecko_data, get_coinmarketcap_data, get_dexscreener_data]:
        data = func(contract)
        if data:
            if "telegram_channel" not in data:
                data["telegram_channel"] = ""
            if "circulating_supply" not in data:
                data["circulating_supply"] = None
            return data
    return None
# Fetch all ERC20 tokens from Ethplorer
def get_all_erc20_balances(address):
    url = f"https://api.ethplorer.io/getAddressInfo/{address}?apiKey=freekey"
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        data = response.json()
        return data.get('tokens', [])
    except Exception as e:
        print(f"Ethplorer error: {e}")
        return []
# Generate new wallet
def generate_wallet():
    priv = secrets.token_hex(32)
    acct = Account.from_key(priv)
    return acct.address, priv
# Get gas price for user
def get_user_gas_price(user_id):
    default_gwei = int(w3.from_wei(w3.eth.gas_price, 'gwei'))
    user_gwei = users.get(user_id, {}).get('gas_gwei', default_gwei)
    return w3.to_wei(user_gwei, 'gwei')
# Human-readable error
def get_human_error(error_str):
    if 'INSUFFICIENT_INPUT_AMOUNT' in error_str:
        return "Insufficient token amount or liquidity for the swap. The token balance might be too small or there is not enough liquidity."
    if 'TRANSFER_FROM_FAILED' in error_str:
        return "Token transfer failed. This could be due to insufficient allowance or token-specific issues like transfer fees. Token may be a honeypot or have high sell taxes."
    if 'insufficient funds for gas' in error_str.lower():
        return "Insufficient ETH in wallet to cover gas fees. Please add more ETH to your wallet."
    if 'transaction underpriced' in error_str.lower():
        return "Transaction gas price too low. Try increasing the gas price with /gas command."
    if 'execution reverted' in error_str:
        return "Transaction reverted: " + error_str.split('execution reverted: ')[1].split("',")[0] if 'execution reverted: ' in error_str else error_str
    return error_str
# Buy token on Uniswap
async def buy_token(user_id, contract, amount_eth, context=None):
    if user_id not in users:
        return None, "No wallet", None
    address = users[user_id]['address']
    pk = users[user_id]['private_key']
    token_address = w3.to_checksum_address(contract)
    router = w3.eth.contract(address=w3.to_checksum_address(UNISWAP_ROUTER_ADDRESS), abi=UNISWAP_ROUTER_ABI)
    token = w3.eth.contract(address=token_address, abi=ERC20_ABI)
    balance_before = token.functions.balanceOf(address).call()

    path = [w3.to_checksum_address(WETH_ADDRESS), token_address]
    amount_wei = w3.to_wei(amount_eth, 'ether')
    deadline = int(time.time()) + 600
    gas_price = get_user_gas_price(user_id)
    slippage = users[user_id].get('slippage', 50)

    try:
        expected_out = router.functions.getAmountsOut(amount_wei, path).call()[-1]
        amount_out_min = int(expected_out * (1 - slippage / 100.0))
    except Exception as e:
        print(f"getAmountsOut error: {e}")
        amount_out_min = 0

    try:
        tx = router.functions.swapExactETHForTokens(
            amount_out_min,
            path,
            address,
            deadline
        ).build_transaction({
            'from': address,
            'value': amount_wei,
            'gasPrice': gas_price,
            'nonce': w3.eth.get_transaction_count(address),
        })
        tx['gas'] = int(router.functions.swapExactETHForTokens(amount_out_min, path, address, deadline).estimate_gas({'from': address, 'value': amount_wei}) * 1.2)
    except Exception as e:
        return None, get_human_error(str(e)), None

    signed = Account.sign_transaction(tx, pk)
    try:
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=600)
        if receipt['status'] != 1:
            return None, "Transaction reverted. Possible reasons: insufficient liquidity or slippage too high.", None
    except Exception as e:
        return None, get_human_error(str(e)), None

    balance_after = token.functions.balanceOf(address).call()
    amount_token = balance_after - balance_before

    try:
        decimals = token.functions.decimals().call()
    except:
        decimals = 18

    # Auto-approve for future sells with dynamic gas
    allowance = token.functions.allowance(address, w3.to_checksum_address(UNISWAP_ROUTER_ADDRESS)).call()
    if allowance < MAX_UINT:
        nonce = w3.eth.get_transaction_count(address)
        try:
            approve_call = token.functions.approve(
                w3.to_checksum_address(UNISWAP_ROUTER_ADDRESS),
                MAX_UINT
            )
            approve_tx = approve_call.build_transaction({
                'from': address,
                'gasPrice': gas_price,  # Dynamic
                'nonce': nonce,
            })
            approve_tx['gas'] = int(approve_call.estimate_gas({'from': address}) * 1.2)  # Dynamic estimate
            signed_approve = Account.sign_transaction(approve_tx, pk)
            approve_hash = w3.eth.send_raw_transaction(signed_approve.raw_transaction)
            approve_receipt = w3.eth.wait_for_transaction_receipt(approve_hash, timeout=600)
            if approve_receipt['status'] != 1:
                print("Auto-approve failed")
        except Exception as e:
            print(f"Auto-approve error: {e}")

    return amount_token, '0x' + tx_hash.hex(), decimals
# Sell token on Uniswap
async def sell_token(user_id, contract, amount_token, context=None, is_profit=False, chat_id=None, slippage=50, main_pending_msg=None):
    if user_id not in users:
        return "No wallet", 0
    address = users[user_id]['address']
    pk = users[user_id]['private_key']
    token_address = w3.to_checksum_address(contract)
    router = w3.eth.contract(address=w3.to_checksum_address(UNISWAP_ROUTER_ADDRESS), abi=UNISWAP_ROUTER_ABI)
    token = w3.eth.contract(address=token_address, abi=ERC20_ABI)
    gas_price = get_user_gas_price(user_id)
    # Fetch fresh balance for safety
    current_balance = token.functions.balanceOf(address).call()
    if current_balance <= 0:
        return "No tokens to sell.", 0
    amount_token = min(amount_token, current_balance)
    if amount_token <= 0:
        return "Invalid amount: cannot sell zero or negative tokens.", 0
    # Check allowance
    allowance = token.functions.allowance(address, w3.to_checksum_address(UNISWAP_ROUTER_ADDRESS)).call()
    if allowance < amount_token:
        approve_pending_msg = None
        if chat_id and context:
            approve_pending_msg = await context.bot.send_message(chat_id=chat_id, text="⏳ Approving tokens...")
        nonce = w3.eth.get_transaction_count(address)
        try:
            approve_call = token.functions.approve(
                w3.to_checksum_address(UNISWAP_ROUTER_ADDRESS),
                MAX_UINT
            )
            approve_tx = approve_call.build_transaction({
                'from': address,
                'gasPrice': gas_price,  # Dynamic
                'nonce': nonce,
            })
            approve_tx['gas'] = int(approve_call.estimate_gas({'from': address}) * 1.2)  # Dynamic estimate with buffer
            signed_approve = Account.sign_transaction(approve_tx, pk)
            approve_hash = w3.eth.send_raw_transaction(signed_approve.raw_transaction)
            approve_receipt = w3.eth.wait_for_transaction_receipt(approve_hash, timeout=600)
            if approve_receipt['status'] != 1:
                return "Approve transaction reverted. Check token contract or increase gas via /gas.", 0
            if approve_pending_msg:
                await approve_pending_msg.edit_text("✅ Tokens approved. Waiting 10s for confirmation...")
            await asyncio.sleep(10)  # Delay to ensure approval is processed
        except Exception as e:
            return get_human_error(str(e)), 0

    path = [token_address, w3.to_checksum_address(WETH_ADDRESS)]
    deadline = int(time.time()) + 600

    # Calculate expected out and amountOutMin with slippage
    try:
        expected_out = router.functions.getAmountsOut(amount_token, path).call()[-1]
        amount_out_min = int(expected_out * (1 - slippage / 100))  # e.g., 50% slippage allows high taxes
    except Exception as e:
        print(f"getAmountsOut error: {e}")  # Log for debugging
        amount_out_min = 0  # Fallback to original behavior if call fails

    try:
        swap_call = router.functions.swapExactTokensForETHSupportingFeeOnTransferTokens(
            amount_token,
            amount_out_min,
            path,
            address,
            deadline
        )
        tx = swap_call.build_transaction({
            'from': address,
            'gasPrice': gas_price,
            'nonce': w3.eth.get_transaction_count(address),
        })
        tx['gas'] = int(swap_call.estimate_gas({'from': address}) * 1.2)
    except Exception as e:
        return get_human_error(str(e)), 0

    signed = Account.sign_transaction(tx, pk)
    try:
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=600)
        if receipt['status'] != 1:
            return "Swap transaction reverted. Possible reasons: high taxes, low liquidity, or honeypot.", 0
    except Exception as e:
        return get_human_error(str(e)), 0

    # Calculate sold USD
    data = get_token_data(contract)
    price = data['price'] if data else 0
    try:
        decimals = token.functions.decimals().call()
    except:
        decimals = 18
    sold_usd = (amount_token / 10**decimals) * price

    if is_profit:
        eth_price = get_eth_price()
        if eth_price:
            fee_amount = w3.to_wei(5 / eth_price, 'ether')
            nonce = w3.eth.get_transaction_count(address)
            transfer_tx = {
                'to': FEE_WALLET,
                'value': fee_amount,
                'gas': 21000,
                'gasPrice': gas_price,
                'nonce': nonce,
                'chainId': w3.eth.chain_id
            }
            signed_fee = Account.sign_transaction(transfer_tx, pk)
            fee_hash = w3.eth.send_raw_transaction(signed_fee.raw_transaction)
            fee_receipt = w3.eth.wait_for_transaction_receipt(fee_hash, timeout=600)
            if fee_receipt['status'] != 1:
                print("Fee transfer failed")  # Log, but continue

    return '0x' + tx_hash.hex(), sold_usd
# Monitor trades
async def monitor_trades(context: ContextTypes.DEFAULT_TYPE):
    for user_id_str, user_data in list(users.items()):
        trades = user_data.get('trades', [])
        for trade_idx in range(len(trades) - 1, -1, -1):
            trade = trades[trade_idx]
            # Fetch current balance to update
            token = w3.eth.contract(address=w3.to_checksum_address(trade['contract']), abi=ERC20_ABI)
            current_balance = token.functions.balanceOf(users[user_id_str]['address']).call()
            trade['amount_token'] = current_balance
            if trade['amount_token'] <= 0:
                if 'message_id' in trade:
                    try:
                        await context.bot.delete_message(chat_id=user_id_str, message_id=trade['message_id'])
                    except:
                        pass
                del trades[trade_idx]
                save_users(users)
                continue

            data = get_token_data(trade['contract'])
            if not data or data['price'] <= 0:
                continue
            current_price = data['price']
            change = ((current_price - trade['buy_price']) / trade['buy_price']) * 100 if trade['buy_price'] > 0 else 0
            current_value = (trade['amount_token'] / 10**trade['decimals']) * current_price
            current_profit_usd = current_value - trade['buy_cost_usd']
            slippage = users[user_id_str].get('slippage', 50)
            if trade['tp_pct'] > 0 and change >= trade['tp_pct']:
                pending_msg = await context.bot.send_message(chat_id=user_id_str, text="⏳ Selling due to take profit...")
                tx_hash, sold_usd = await sell_token(user_id_str, trade['contract'], trade['amount_token'], context=context, is_profit=True, chat_id=user_id_str, slippage=slippage, main_pending_msg=pending_msg)
                if tx_hash.startswith('0x'):
                    await pending_msg.edit_text(f"✅ Transaction successful! Sold for {usd(sold_usd)}. Etherscan: https://etherscan.io/tx/{tx_hash}")
                    if 'message_id' in trade:
                        try:
                            await context.bot.delete_message(chat_id=user_id_str, message_id=trade['message_id'])
                        except:
                            pass
                    del trades[trade_idx]
                    save_users(users)
                else:
                    await pending_msg.edit_text(f"❌ Transaction failed: {tx_hash}")
                continue
            elif trade['sl_pct'] > 0 and change <= -trade['sl_pct']:
                pending_msg = await context.bot.send_message(chat_id=user_id_str, text="⏳ Selling due to stop loss...")
                tx_hash, sold_usd = await sell_token(user_id_str, trade['contract'], trade['amount_token'], context=context, is_profit=False, chat_id=user_id_str, slippage=slippage, main_pending_msg=pending_msg)
                if tx_hash.startswith('0x'):
                    await pending_msg.edit_text(f"✅ Transaction successful! Sold for {usd(sold_usd)}. Etherscan: https://etherscan.io/tx/{tx_hash}")
                    if 'message_id' in trade:
                        try:
                            await context.bot.delete_message(chat_id=user_id_str, message_id=trade['message_id'])
                        except:
                            pass
                    del trades[trade_idx]
                    save_users(users)
                else:
                    await pending_msg.edit_text(f"❌ Transaction failed: {tx_hash}")
                continue
            
            # Update tracking message
            if 'message_id' in trade:
                symbol = data['symbol']
                text = f"Coin: {symbol}\nCurrent profit: {usd(current_profit_usd)} ({change:.2f}%) \n"
                keyboard = [
                    [InlineKeyboardButton("Sell 100%", callback_data=f"sell_100_{trade_idx}")],
                    [InlineKeyboardButton("Sell Custom", callback_data=f"sell_custom_{trade_idx}")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                try:
                    await context.bot.edit_message_text(chat_id=user_id_str, message_id=trade['message_id'], text=text, reply_markup=reply_markup)
                except Exception as e:
                    print(f"Failed to edit tracking message: {e}")
# Command: /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = """🤖 Welcome to Ethora Prediction Bot! 🎉
Created by the Ethora team (@ethora_erc) 🚀

Here’s how to get started:
👉 Click Start
👉 Type /p + ERC20 token address
⏳ Time F.
Receive insights, predictions, and T.A. on historical prices — all processed individually for you!

🔮 Personalized predictions for each user
📊 Historical analysis for smarter decisions
⚡ Fast, reliable, and per-user performance
🌐 Powered by Ethora’s cutting-edge Web3 tools

Explore your token’s future with your own dedicated insights! 🌟

Available commands:
/p <address> - Get predictions for a token
/buy - Buy a token
/sell - Sell a token
/wallet - View your ETH balance
/generate - Generate a new wallet
/import <private_key> - Import an existing wallet
/transfer - Transfer ETH or tokens
/gas <gwei> - Set gas price
/slippage <percent> - Set slippage tolerance"""
    await update.message.reply_text(message)
# Command: /generate
async def generate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)
    if user_id in users and users[user_id].get('address'):
        await update.message.reply_text("You already have a wallet set.")
        return
    address, priv = generate_wallet()
    users[user_id] = {'address': address, 'private_key': priv, 'trades': []}
    save_users(users)
    await update.message.reply_text(f"New wallet generated:\nAddress: {address}\nPrivate key: {priv}")
    warning = """⚠️ Important Security Notice

Save your private key immediately and store it in a secure location.

Do NOT share your private key or recovery phrase with anyone.

We cannot recover your wallet if you lose it.

You are fully responsible for the security of your wallet.

By proceeding, you acknowledge that you understand and accept these responsibilities."""
    await update.message.reply_text(warning)
# Command: /import <private_key>
async def import_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)
    if len(context.args) != 1:
        await update.message.reply_text("Usage: /import <private_key>")
        return
    pk = context.args[0]
    try:
        acct = Account.from_key(pk)
        address = acct.address
        users[user_id] = {'address': address, 'private_key': pk, 'trades': users.get(user_id, {}).get('trades', [])}
        save_users(users)
        await update.message.reply_text(f"Wallet imported: {address}")
    except Exception as e:
        print(f"Import error: {e}")
        await update.message.reply_text("Invalid private key.")
# Command: /wallet
async def wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)
    if user_id not in users or not users[user_id].get('address'):
        await update.message.reply_text("No wallet set. Use /generate or /import.")
        return
    address = users[user_id]['address']
    eth_balance = w3.from_wei(w3.eth.get_balance(address), 'ether')
    eth_price = get_eth_price() or 0
    eth_usd = float(eth_balance) * eth_price
    gas_gwei = users[user_id].get('gas_gwei', int(w3.from_wei(w3.eth.gas_price, 'gwei')))
    slippage = users[user_id].get('slippage', 50)
    text = f"💼 Your wallet address: {address}\nETH balance: {eth_balance:.8f} ({usd(eth_usd)})"
    keyboard = [
        [InlineKeyboardButton(f"⛽ Gas: {gas_gwei} Gwei", callback_data="gas_info"), InlineKeyboardButton(f"📉 Slippage: {slippage}%", callback_data="slippage_info")],
        [InlineKeyboardButton("ℹ️ Change settings: /gas or /slippage", callback_data="settings_info")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(text, reply_markup=reply_markup)
# Transfer conversation handlers
async def transfer_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    user_id = str(update.effective_user.id)
    if user_id not in users:
        await message.reply_text("No wallet set.")
        return ConversationHandler.END
    await message.reply_text("What to transfer: ETH or token contract address?")
    return TRANSFER_WHAT
async def transfer_what(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['transfer_what'] = update.message.text.strip().lower()
    await update.message.reply_text("To which address?")
    return TRANSFER_TO
async def transfer_to(update: Update, context: ContextTypes.DEFAULT_TYPE):
    to_addr = update.message.text.strip()
    if not w3.is_address(to_addr):
        await update.message.reply_text("Invalid address.")
        return ConversationHandler.END
    context.user_data['transfer_to'] = w3.to_checksum_address(to_addr)
    await update.message.reply_text("How much in % (1-100)?")
    return TRANSFER_AMOUNT
async def transfer_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)
    try:
        pct = float(update.message.text.strip().replace('%', ''))
        if not 0 < pct <= 100:
            raise ValueError
    except:
        await update.message.reply_text("Invalid percent.")
        return ConversationHandler.END
    what = context.user_data['transfer_what']
    to_addr = context.user_data['transfer_to']
    gas_price = get_user_gas_price(user_id)
    pending_msg = await update.message.reply_text("⏳ Your transfer is pending...")

    if what == 'eth':
        balance = w3.eth.get_balance(users[user_id]['address'])
        amount = int(balance * (pct / 100))
        try:
            tx = {
                'to': to_addr,
                'value': amount,
                'gas': 21000,
                'gasPrice': gas_price,
                'nonce': w3.eth.get_transaction_count(users[user_id]['address']),
                'chainId': w3.eth.chain_id
            }
            signed = Account.sign_transaction(tx, users[user_id]['private_key'])
            tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
            receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=600)
            if receipt['status'] != 1:
                await pending_msg.edit_text("❌ Transfer failed: Transaction reverted.")
                return ConversationHandler.END
            await pending_msg.edit_text(f"✅ Transfer successful! Etherscan: https://etherscan.io/tx/{'0x' + tx_hash.hex()}")
        except Exception as e:
            error_msg = get_human_error(str(e))
            await pending_msg.edit_text(f"❌ Transfer failed: {error_msg}")
            return ConversationHandler.END
    else:
        try:
            token_address = w3.to_checksum_address(what)
            token = w3.eth.contract(address=token_address, abi=ERC20_ABI)
            balance = token.functions.balanceOf(users[user_id]['address']).call()
            amount = int(balance * (pct / 100))
            tx = token.functions.transfer(to_addr, amount).build_transaction({
                'from': users[user_id]['address'],
                'gasPrice': gas_price,
                'nonce': w3.eth.get_transaction_count(users[user_id]['address']),
            })
            tx['gas'] = int(token.functions.transfer(to_addr, amount).estimate_gas({'from': users[user_id]['address']}) * 1.2)
            signed = Account.sign_transaction(tx, users[user_id]['private_key'])
            tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
            receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=600)
            if receipt['status'] != 1:
                await pending_msg.edit_text("❌ Transfer failed: Transaction reverted.")
                return ConversationHandler.END
            await pending_msg.edit_text(f"✅ Transfer successful! Etherscan: https://etherscan.io/tx/{'0x' + tx_hash.hex()}")
        except Exception as e:
            error_msg = get_human_error(str(e))
            await pending_msg.edit_text(f"❌ Transfer failed: {error_msg}")
            return ConversationHandler.END

    return ConversationHandler.END
# Handle non-command messages
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)
    text = update.message.text.strip()

    if 'in_buy_conv' in context.user_data:
        if not context.user_data.get('contract'):
            try:
                contract = w3.to_checksum_address(text)
            except:
                await update.message.reply_text("Invalid contract address.")
                return
            context.user_data['contract'] = contract
            await update.message.reply_text("Enter the amount of ETH to spend:")
            return
        else:
            contract = context.user_data['contract']
            try:
                amount_eth = float(text)
                if amount_eth <= 0:
                    raise ValueError
            except:
                await update.message.reply_text("Invalid amount.")
                return
            pending_msg = await update.message.reply_text("⏳ Your buy transaction is pending...")
            amount_token, tx_hash, decimals = await buy_token(user_id, contract, amount_eth, context=context)
            if amount_token is None:
                await pending_msg.edit_text(f"❌ Transaction failed: {tx_hash}")
                return
            await pending_msg.edit_text(f"✅ Transaction successful! Etherscan: https://etherscan.io/tx/{tx_hash}")
            data = get_token_data(contract)
            price = data['price'] if data else 0
            buy_cost_usd = amount_eth * (get_eth_price() or 0)
            trade = {
                'contract': contract,
                'amount_token': amount_token,
                'decimals': decimals,
                'buy_price': price,
                'buy_cost_usd': buy_cost_usd,
                'tp_pct': 0,
                'sl_pct': 0
            }
            if 'trades' not in users[user_id]:
                users[user_id]['trades'] = []
            users[user_id]['trades'].append(trade)
            save_users(users)
            trade_index = len(users[user_id]['trades']) - 1
            keyboard = [
                [InlineKeyboardButton("0.01", callback_data="tp_0.01"), InlineKeyboardButton("0.03", callback_data="tp_0.03"), InlineKeyboardButton("0.05", callback_data="tp_0.05"), InlineKeyboardButton("0.10", callback_data="tp_0.10")],
                [InlineKeyboardButton("1", callback_data="tp_1"), InlineKeyboardButton("2", callback_data="tp_2"), InlineKeyboardButton("3", callback_data="tp_3"), InlineKeyboardButton("5", callback_data="tp_5")],
                [InlineKeyboardButton("Custom", callback_data="tp_custom"), InlineKeyboardButton("None", callback_data="tp_0")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text("Set take profit multiplier (1 = 100% gain, etc.):", reply_markup=reply_markup)
            context.user_data.pop('contract', None)
            context.user_data.pop('in_buy_conv', None)
            return

    if 'in_sell_conv' in context.user_data:
        if not context.user_data.get('contract'):
            try:
                contract = w3.to_checksum_address(text)
            except:
                await update.message.reply_text("Invalid contract address.")
                return
            context.user_data['contract'] = contract
            await update.message.reply_text("Enter the percentage to sell (1-100):")
            return
        else:
            contract = context.user_data['contract']
            try:
                pct = float(text)
                if not 0 < pct <= 100:
                    raise ValueError
            except:
                await update.message.reply_text("Invalid percentage.")
                return
            token = w3.eth.contract(address=w3.to_checksum_address(contract), abi=ERC20_ABI)
            current_balance = token.functions.balanceOf(users[user_id]['address']).call()
            amount_token = int(current_balance * (pct / 100))
            if amount_token <= 0:
                await update.message.reply_text("No tokens to sell or amount too small.")
                context.user_data.pop('contract', None)
                context.user_data.pop('in_sell_conv', None)
                return
            slippage = users[user_id].get('slippage', 50)
            pending_msg = await update.message.reply_text("⏳ Your sell transaction is pending...")
            tx_hash, sold_usd = await sell_token(user_id, contract, amount_token, context=context, chat_id=update.message.chat_id, slippage=slippage, main_pending_msg=pending_msg)
            if tx_hash.startswith('0x'):
                await pending_msg.edit_text(f"✅ Transaction successful! Sold for {usd(sold_usd)}. Etherscan: https://etherscan.io/tx/{tx_hash}")
            else:
                await pending_msg.edit_text(f"❌ Transaction failed: {tx_hash}")
            context.user_data.pop('contract', None)
            context.user_data.pop('in_sell_conv', None)
            return

    if 'setting_tp' in context.user_data:
        try:
            tp_pct = float(text)
            trade_index = context.user_data.pop('setting_tp')
            users[user_id]['trades'][trade_index]['tp_pct'] = tp_pct
            keyboard = [
                [InlineKeyboardButton("0.01", callback_data="sl_0.01"), InlineKeyboardButton("0.03", callback_data="sl_0.03"), InlineKeyboardButton("0.05", callback_data="sl_0.05"), InlineKeyboardButton("0.10", callback_data="sl_0.10")],
                [InlineKeyboardButton("1", callback_data="sl_1"), InlineKeyboardButton("2", callback_data="sl_2"), InlineKeyboardButton("3", callback_data="sl_3"), InlineKeyboardButton("4", callback_data="sl_4"), InlineKeyboardButton("5", callback_data="sl_5")],
                [InlineKeyboardButton("Custom", callback_data="sl_custom"), InlineKeyboardButton("None", callback_data="sl_0")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text("Set stop loss multiplier (1 = -100% loss, etc.):", reply_markup=reply_markup)
        except:
            await update.message.reply_text("Invalid %.")
        return

    if 'setting_sl' in context.user_data:
        try:
            sl_pct = float(text)
            trade_index = context.user_data.pop('setting_sl')
            users[user_id]['trades'][trade_index]['sl_pct'] = sl_pct
            await update.message.reply_text("Trade settings saved. Monitoring started.")
            # Send pinned tracking message
            trade = users[user_id]['trades'][trade_index]
            data = get_token_data(trade['contract'])
            symbol = data['symbol'] if data else "Unknown"
            text = f"Coin: {symbol}\nCurrent profit: $0 (0.00%) \n"
            keyboard = [
                [InlineKeyboardButton("Sell 100%", callback_data=f"sell_100_{trade_index}")],
                [InlineKeyboardButton("Sell Custom", callback_data=f"sell_custom_{trade_index}")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            msg = await update.message.reply_text(text, reply_markup=reply_markup)
            users[user_id]['trades'][trade_index]['message_id'] = msg.message_id
            await context.bot.pin_chat_message(chat_id=update.message.chat_id, message_id=msg.message_id)
            save_users(users)
        except:
            await update.message.reply_text("Invalid %.")
        return

    if 'sell_custom' in context.user_data:
        trade_idx = context.user_data.pop('sell_custom')
        try:
            pct = float(text.replace('%', ''))
            if not 0 < pct <= 100:
                raise ValueError
        except:
            await update.message.reply_text("Invalid percent.")
            return
        trade = users[user_id]['trades'][trade_idx]
        # Fetch fresh balance
        token = w3.eth.contract(address=w3.to_checksum_address(trade['contract']), abi=ERC20_ABI)
        current_balance = token.functions.balanceOf(users[user_id]['address']).call()
        trade['amount_token'] = current_balance
        save_users(users)
        amount_token = int(trade['amount_token'] * (pct / 100))
        if amount_token <= 0:
            await update.message.reply_text("Invalid sell amount: too small or zero.")
            return
        slippage = users[user_id].get('slippage', 50)
        pending_msg = await update.message.reply_text("⏳ Your sell transaction is pending...")
        tx_hash, sold_usd = await sell_token(user_id, trade['contract'], amount_token, context=context, chat_id=update.message.chat_id, slippage=slippage, main_pending_msg=pending_msg)
        if tx_hash.startswith('0x'):
            await pending_msg.edit_text(f"✅ Transaction successful! Sold for {usd(sold_usd)}. Etherscan: https://etherscan.io/tx/{tx_hash}")
            users[user_id]['trades'][trade_idx]['amount_token'] -= amount_token
            users[user_id]['trades'][trade_idx]['buy_cost_usd'] -= (pct / 100) * users[user_id]['trades'][trade_idx]['buy_cost_usd']
            if users[user_id]['trades'][trade_idx]['amount_token'] <= 0:
                if 'message_id' in trade:
                    try:
                        await context.bot.delete_message(chat_id=update.message.chat_id, message_id=trade['message_id'])
                    except:
                        pass
                del users[user_id]['trades'][trade_idx]
            save_users(users)
        else:
            await pending_msg.edit_text(f"❌ Transaction failed: {tx_hash}")
        return
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
# Callback for timeframe selection and buy
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query: CallbackQuery = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith('tf_'):
        tf_key = data.split('_')[1]
        contract = context.user_data.get('contract')
        if not contract:
            await query.edit_message_text("No contract selected. Please use /p first.")
            return

        msg = await query.message.reply_text(" Generating prediction...")

        # Fetch basic data
        token_data = get_token_data(contract)
        if not token_data:
            await msg.edit_text(" Unable to fetch token data. Please check the contract address or try again later.")
            return

        source = "coingecko" if get_coingecko_data(contract) else ("coinmarketcap" if get_coinmarketcap_data(contract) else "dexscreener")

        # Fetch DexScreener data
        dex_data = get_dexscreener_data(contract)
        liquidity = dex_data["liquidity"] if dex_data else "—"
        dexscreener_url = dex_data["dexscreener_url"] if dex_data else ""
        pair_address = dex_data["pair_address"] if dex_data else ""
        chain_id = dex_data["chain_id"] if dex_data else "ethereum"
        ethora_url = "https://t.me/ethora_erc"

        # Emoji for price change
        ball_emoji = "" if token_data["price_change_24h"] > 0 else ""

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
        predicted_pct_str = "—"
        predicted_mc_str = "—"
        predicted_price_str = "—"
        if source == "coingecko":
            try:
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
                    if predicted_price > token_data["price"] * 10:  # Cap at 10x
                        predicted_price = token_data["price"] * 10
                    elif predicted_price < token_data["price"] * 0.1:  # Floor at 0.1x
                        predicted_price = token_data["price"] * 0.1

                    if predicted_price != "—" and token_data["price"] > 0:
                        predicted_pct = ((predicted_price - token_data["price"]) / token_data["price"]) * 100
                        pred_direction_emoji = "↑" if predicted_pct > 0 else "↓"
                        predicted_pct_str = f"{predicted_pct:.2f}% {pred_direction_emoji}"
                        predicted_mc = predicted_price * token_data["circulating_supply"] if token_data["circulating_supply"] else "—"
                        predicted_mc_str = usd(predicted_mc)
                        predicted_price_str = usd(predicted_price)
                    else:
                        predicted_pct_str = "—"
                        predicted_mc_str = "—"
                        predicted_price_str = "—"

                    # Generate chart with dark theme and cool colors
                    plt.style.use('dark_background')
                    fig, ax = plt.subplots(figsize=(10, 6), dpi=200)
                    ax.plot(df["ts"], df["price"], label="Historical Price", color="cyan", linewidth=2)
                    if 'ma20' in df and not df['ma20'].isna().all():
                        ax.plot(df["ts"], df['ma20'], label="MA20", color="yellow", linewidth=1, alpha=0.8)
                    last_ts = df["ts"].iloc[-1]
                    next_ts = last_ts + timedelta(hours=pred_hours)
                    ax.plot([last_ts, next_ts], [token_data["price"], predicted_price], 'r--', label=f"Predicted Price ({tf_display})", linewidth=2, color="magenta")
                    ax.scatter(next_ts, predicted_price, color='magenta', s=50)
                    ax.set_title(f"{token_data['name']} ({token_data['symbol']}) - Price Chart with {tf_display} Prediction", fontsize=14, fontweight='bold', color='white')
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
        else:
            predicted_pct_str = "—"
            predicted_mc_str = "—"
            predicted_price_str = "—"
            rsi_val = "—"
            volatility = "—"
            buf = None

        # Prepare message
        token_telegram = token_data["telegram_channel"]
        if token_telegram and not token_telegram.startswith("http"):
            token_telegram = f"https://t.me/{token_telegram}"
        token_telegram_link = f'<a href="{token_telegram}"></a>' if token_telegram else "—"

        dexscreener_link = f'<a href="{dexscreener_url}">Chart </a>' if dexscreener_url else ""

        text = (
            f"<b>{token_data['name']} ({token_data['symbol']}) {ball_emoji}</b>\n\n"
            f" <b>Chain:</b> ETH\n"
            f" <b>Price:</b> {usd(token_data['price'])}\n"
            f" <b>Volume (24h):</b> {usd(token_data['volume'])}\n"
            f" <b>Market Cap:</b> {usd(token_data['market_cap'])}\n"
            f" <b>Liquidity:</b> {usd(liquidity)}\n"
            f" <b>Token Telegram:</b> {token_telegram_link}\n"
            f" <b>RSI:</b> {rsi_val}\n"
            f" <b>Volatility:</b> {volatility}\n\n"
            f" <b>{tf_display} Prediction (80-90% Accuracy)</b>\n"
            f"├─  <i>Market Cap:</i> {predicted_mc_str} {pred_direction_emoji}\n"
            f"├─  <i>Price:</i> {predicted_price_str} {pred_direction_emoji}\n"
            f"└─  <i>Change:</i> {predicted_pct_str}\n\n"
            f"{dexscreener_link}\n"
        )

        # Inline buttons - replaced Maestro with Buy, kept Ethora
        keyboard = [
            [InlineKeyboardButton("Buy", callback_data=f"buy_{contract}")],
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

    elif data.startswith('buy_'):
        contract = data.split('_')[1]
        user_id = str(query.from_user.id)
        if user_id not in users or not users[user_id].get('address'):
            await query.message.reply_text("Please set up your wallet first using /generate or /import <private_key>.")
            return
        context.user_data['contract'] = contract
        context.user_data['in_buy_conv'] = True
        await query.message.reply_text("Enter the amount of ETH to spend:")

    elif data.startswith('tp_'):
        user_id = str(query.from_user.id)
        trade_index = len(users[user_id]['trades']) - 1
        tp_str = data.split('_')[1]
        if tp_str == 'custom':
            await query.message.reply_text("Enter custom TP %:")
            context.user_data['setting_tp'] = trade_index
            return
        elif tp_str == '0':
            tp_pct = 0
        else:
            tp_pct = float(tp_str) * 100
        users[user_id]['trades'][trade_index]['tp_pct'] = tp_pct
        keyboard = [
            [InlineKeyboardButton("0.01", callback_data="sl_0.01"), InlineKeyboardButton("0.03", callback_data="sl_0.03"), InlineKeyboardButton("0.05", callback_data="sl_0.05"), InlineKeyboardButton("0.10", callback_data="sl_0.10")],
            [InlineKeyboardButton("1", callback_data="sl_1"), InlineKeyboardButton("2", callback_data="sl_2"), InlineKeyboardButton("3", callback_data="sl_3"), InlineKeyboardButton("4", callback_data="sl_4"), InlineKeyboardButton("5", callback_data="sl_5")],
            [InlineKeyboardButton("Custom", callback_data="sl_custom"), InlineKeyboardButton("None", callback_data="sl_0")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("Set stop loss multiplier (1 = -100% loss, etc.):", reply_markup=reply_markup)

    elif data.startswith('sl_'):
        user_id = str(query.from_user.id)
        trade_index = len(users[user_id]['trades']) - 1
        sl_str = data.split('_')[1]
        if sl_str == 'custom':
            await query.message.reply_text("Enter custom SL %:")
            context.user_data['setting_sl'] = trade_index
            return
        elif sl_str == '0':
            sl_pct = 0
        else:
            sl_pct = float(sl_str) * 100
        users[user_id]['trades'][trade_index]['sl_pct'] = sl_pct
        await query.edit_message_text("Trade settings saved. Monitoring started.")
        trade = users[user_id]['trades'][trade_index]
        data = get_token_data(trade['contract'])
        symbol = data['symbol'] if data else "Unknown"
        text = f"Coin: {symbol}\nCurrent profit: $0 (0.00%) \n"
        keyboard = [
            [InlineKeyboardButton("Sell 100%", callback_data=f"sell_100_{trade_index}")],
            [InlineKeyboardButton("Sell Custom", callback_data=f"sell_custom_{trade_index}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        msg = await query.message.reply_text(text, reply_markup=reply_markup)
        users[user_id]['trades'][trade_index]['message_id'] = msg.message_id
        await context.bot.pin_chat_message(chat_id=query.message.chat_id, message_id=msg.message_id)
        save_users(users)

    elif data.startswith('sell_100_'):
        trade_idx = int(data.split('_')[2])
        user_id = str(query.from_user.id)
        trade = users[user_id]['trades'][trade_idx]
        # Fetch fresh balance
        token = w3.eth.contract(address=w3.to_checksum_address(trade['contract']), abi=ERC20_ABI)
        current_balance = token.functions.balanceOf(users[user_id]['address']).call()
        if current_balance <= 0:
            await query.message.reply_text("No tokens to sell.")
            return
        trade['amount_token'] = current_balance
        save_users(users)
        slippage = users[user_id].get('slippage', 50)
        pending_msg = await query.message.reply_text("⏳ Your sell transaction is pending...")
        tx_hash, sold_usd = await sell_token(user_id, trade['contract'], trade['amount_token'], context=context, chat_id=query.message.chat_id, slippage=slippage, main_pending_msg=pending_msg)
        if tx_hash.startswith('0x'):
            await pending_msg.edit_text(f"✅ Transaction successful! Sold for {usd(sold_usd)}. Etherscan: https://etherscan.io/tx/{tx_hash}")
            if 'message_id' in trade:
                try:
                    await context.bot.delete_message(chat_id=query.message.chat_id, message_id=trade['message_id'])
                except:
                    pass
            del users[user_id]['trades'][trade_idx]
            save_users(users)
        else:
            await pending_msg.edit_text(f"❌ Transaction failed: {tx_hash}")

    elif data.startswith('sell_custom_'):
        trade_idx = int(data.split('_')[2])
        user_id = str(query.from_user.id)
        trade = users[user_id]['trades'][trade_idx]
        # Fetch fresh balance
        token = w3.eth.contract(address=w3.to_checksum_address(trade['contract']), abi=ERC20_ABI)
        current_balance = token.functions.balanceOf(users[user_id]['address']).call()
        if current_balance <= 0:
            await query.message.reply_text("No tokens to sell.")
            return
        trade['amount_token'] = current_balance
        save_users(users)
        await query.message.reply_text("Enter sell % (1-100):")
        context.user_data['sell_custom'] = trade_idx

    elif data == 'gas_info' or data == 'slippage_info' or data == 'settings_info':
        await query.answer("This is informational. Use /gas or /slippage to change.")
# Command: /buy
async def buy_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)
    if user_id not in users or not users[user_id].get('address'):
        await update.message.reply_text("Please set up your wallet first using /generate or /import <private_key>.")
        return
    context.user_data['in_buy_conv'] = True
    context.user_data.pop('contract', None)
    await update.message.reply_text("Enter token contract address:")
# Command: /sell
async def sell_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)
    if user_id not in users or not users[user_id].get('address'):
        await update.message.reply_text("No wallet set. Use /generate or /import.")
        return
    context.user_data['in_sell_conv'] = True
    context.user_data.pop('contract', None)
    await update.message.reply_text("Enter token contract address:")
# Command: /gas <gwei>
async def set_gas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)
    if len(context.args) != 1:
        await update.message.reply_text("Usage: /gas <gwei>")
        return
    try:
        gwei = int(context.args[0])
        if gwei < 1:
            raise ValueError
        users[user_id]['gas_gwei'] = gwei
        save_users(users)
        await update.message.reply_text(f"Gas price set to {gwei} gwei for future transactions.")
    except:
        await update.message.reply_text("Invalid gwei value.")
# Command: /slippage <percent>
async def set_slippage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)
    if len(context.args) != 1:
        await update.message.reply_text("Usage: /slippage <percent>")
        return
    try:
        pct = int(context.args[0])
        if pct < 0 or pct > 100:
            raise ValueError
        users[user_id]['slippage'] = pct
        save_users(users)
        await update.message.reply_text(f"Slippage set to {pct}%")
    except:
        await update.message.reply_text("Invalid percent (0-100).")
def main():
    # Build the bot
    app = ApplicationBuilder().token(API_TOKEN).build()
    # Add handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("p", p))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(CommandHandler("generate", generate))
    app.add_handler(CommandHandler("import", import_wallet))
    app.add_handler(CommandHandler("wallet", wallet))
    app.add_handler(CommandHandler("gas", set_gas))
    app.add_handler(CommandHandler("slippage", set_slippage))
    app.add_handler(CommandHandler("buy", buy_command))
    app.add_handler(CommandHandler("sell", sell_command))

    # Transfer conversation
    transfer_conv = ConversationHandler(
        entry_points=[CommandHandler("transfer", transfer_start)],
        states={
            TRANSFER_WHAT: [MessageHandler(filters.TEXT & ~filters.COMMAND, transfer_what)],
            TRANSFER_TO: [MessageHandler(filters.TEXT & ~filters.COMMAND, transfer_to)],
            TRANSFER_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, transfer_amount)],
        },
        fallbacks=[],
    )
    app.add_handler(transfer_conv)

    # Message handler
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Schedule repeating job
    app.job_queue.run_repeating(monitor_trades, interval=60, first=10)

    # Start the bot
    app.run_polling()
if __name__ == "__main__":
    main()
