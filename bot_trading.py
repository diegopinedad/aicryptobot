# ============================================================
# BOT V3 — Estrategia N°2 Optimizer V3
# EMA 5/21 + Filtro EMA 200 + Estocástico filtro
# TP 5% | SL 1% | Capital 5% | Leverage 5x
# Backtesting: +77% en 6m | WR 41.2%
# ============================================================

import time, csv, os, requests
from datetime import datetime
import pandas as pd
import ta
from binance.client import Client
from binance.enums import *

# ─── BLOQUE 1: CONFIGURACIÓN ─────────────────────────────────
API_KEY     = "1Fh18Oa7c10YgV2FfwwukxGwea8ZZ1Gw83tCkfSfdthoELSK6Uwf8erEHABFf3FR"
API_SECRET  = "AmfRBZZA8ntFnh5csjaTrICmnvOMz03GeVzX3uq7k8u5rY59xs2qwE5vai8PLpCK"

SYMBOL      = "BTCUSDT"
INTERVAL    = "15m"
CAPITAL_PCT = 0.05
LEVERAGE    = 5
STOP_LOSS   = 0.010   # 1%
TAKE_PROFIT = 0.050   # 5%
LOG_FILE    = "track_record_v3.csv"

# ─── BLOQUE 2: CONEXIÓN ──────────────────────────────────────
print("Conectando con Binance Testnet...")
server_time = requests.get(
    "https://testnet.binancefuture.com/fapi/v1/time"
).json()["serverTime"]
client = Client(API_KEY, API_SECRET, testnet=True)
client.timestamp_offset = server_time - int(time.time() * 1000)

try:
    client.futures_change_leverage(symbol=SYMBOL, leverage=LEVERAGE)
    print(f"✓ Leverage {LEVERAGE}x configurado")
except Exception as e:
    print(f"  Aviso: {e}")

# ─── BLOQUE 3: UTILIDADES ────────────────────────────────────
def get_quantity():
    balance  = client.futures_account_balance()
    usdt     = next((float(b["balance"]) for b in balance
                     if b["asset"] == "USDT"), 0)
    price    = float(client.futures_symbol_ticker(symbol=SYMBOL)["price"])
    cantidad = round((usdt * CAPITAL_PCT * LEVERAGE) / price, 3)
    print(f"  Balance: {usdt:.2f} USDT | BTC: {cantidad} "
          f"| Poder: {usdt*CAPITAL_PCT*LEVERAGE:.2f}")
    return cantidad

def detect_open_position():
    for pos in client.futures_position_information(symbol=SYMBOL):
        amt = float(pos["positionAmt"])
        if amt > 0:
            e = float(pos["entryPrice"])
            print(f"  ⚠ LONG activo @ {e:.2f}")
            return "LONG", e
        elif amt < 0:
            e = float(pos["entryPrice"])
            print(f"  ⚠ SHORT activo @ {e:.2f}")
            return "SHORT", e
    return None, 0

def cancel_orders():
    try:
        client.futures_cancel_all_open_orders(symbol=SYMBOL)
    except:
        pass

def place_exit_orders(side, entry_px, qty):
    if side == "LONG":
        tp_px = round(entry_px * (1 + TAKE_PROFIT), 1)
        sl_px = round(entry_px * (1 - STOP_LOSS), 1)
        cs    = SIDE_SELL
    else:
        tp_px = round(entry_px * (1 - TAKE_PROFIT), 1)
        sl_px = round(entry_px * (1 + STOP_LOSS), 1)
        cs    = SIDE_BUY
    try:
        client.futures_create_order(
            symbol=SYMBOL, side=cs,
            type="TAKE_PROFIT_MARKET",
            stopPrice=tp_px, closePosition=True,
            timeInForce="GTE_GTC")
        print(f"  ✓ TP: {tp_px}")
    except Exception as e:
        print(f"  Error TP: {e}")
    try:
        client.futures_create_order(
            symbol=SYMBOL, side=cs,
            type="STOP_MARKET",
            stopPrice=sl_px, closePosition=True,
            timeInForce="GTE_GTC")
        print(f"  ✓ SL: {sl_px}")
    except Exception as e:
        print(f"  Error SL: {e}")

def log_trade(action, price, reason, qty=0, tp=0, sl=0):
    exists = os.path.isfile(LOG_FILE)
    with open(LOG_FILE, "a", newline="") as f:
        w = csv.writer(f)
        if not exists:
            w.writerow(["Fecha","Hora","Accion","Precio",
                        "Cantidad","TP","SL","Motivo"])
        now = datetime.now()
        w.writerow([now.strftime("%Y-%m-%d"),
                    now.strftime("%H:%M:%S"),
                    action, price, qty, tp, sl, reason])
    print(f"[{datetime.now().strftime('%H:%M:%S')}] "
          f"{action} @ {price} | {reason}")

# ─── BLOQUE 4: SEÑALES — EMA5/21/200 + STOCH FILTRO ─────────
def get_signals():
    klines = client.futures_klines(
        symbol=SYMBOL, interval=INTERVAL, limit=250)
    df = pd.DataFrame(klines, columns=[
        "time","open","high","low","close","volume",
        "close_time","qav","num_trades",
        "taker_buy_base","taker_buy_quote","ignore"])
    df["close"] = pd.to_numeric(df["close"])
    df["high"]  = pd.to_numeric(df["high"])
    df["low"]   = pd.to_numeric(df["low"])

    # EMAs
    df["ema5"]   = ta.trend.ema_indicator(df["close"], window=5)
    df["ema21"]  = ta.trend.ema_indicator(df["close"], window=21)
    df["ema200"] = ta.trend.ema_indicator(df["close"], window=200)

    # RSI
    df["rsi"] = ta.momentum.rsi(df["close"], window=14)

    # Estocástico
    stoch = ta.momentum.StochasticOscillator(
        df["high"], df["low"], df["close"],
        window=14, smooth_window=3)
    df["stoch_k"] = stoch.stoch()
    df["stoch_d"] = stoch.stoch_signal()

    return df.dropna().reset_index(drop=True)

def check_signal(df):
    last = df.iloc[-1]
    prev = df.iloc[-2]

    price  = float(last["close"])
    ema5   = float(last["ema5"])
    ema21  = float(last["ema21"])
    ema200 = float(last["ema200"])
    rsi    = float(last["rsi"])
    sk     = float(last["stoch_k"])
    sd     = float(last["stoch_d"])

    # Cruces EMA 5/21
    golden = (float(prev["ema5"]) < float(prev["ema21"])) and (ema5 > ema21)
    death  = (float(prev["ema5"]) > float(prev["ema21"])) and (ema5 < ema21)

    # Filtros
    sobre_200    = price > ema200
    bajo_200     = price < ema200
    tendencia    = "ALCISTA ▲" if sobre_200 else "BAJISTA ▼"
    stoch_no_ob  = sk < 80   # No sobrecomprado
    stoch_no_os  = sk > 20   # No sobrevendido

    print(f"  P:{price:.0f} | E5:{ema5:.0f} E21:{ema21:.0f} "
          f"E200:{ema200:.0f} | RSI:{rsi:.1f} "
          f"SK:{sk:.1f} | {tendencia}")

    # COMPRA: cruce alcista + RSI<50 + sobre EMA200 + stoch no sobrecomprado
    if golden and rsi < 50 and sobre_200 and stoch_no_ob:
        return "BUY", price, f"Golden E5/21 RSI={rsi:.1f} SK={sk:.1f}"

    # VENTA: cruce bajista + RSI>40 + bajo EMA200 + stoch no sobrevendido
    elif death and rsi > 40 and bajo_200 and stoch_no_os:
        return "SELL", price, f"Death E5/21 RSI={rsi:.1f} SK={sk:.1f}"

    # Cruces ignorados
    elif golden and not sobre_200:
        print(f"  ⚠ Golden ignorado — bajo EMA200")
        return "HOLD", price, "Filtro EMA200"
    elif death and not bajo_200:
        print(f"  ⚠ Death ignorado — sobre EMA200")
        return "HOLD", price, "Filtro EMA200"
    elif golden and sk >= 80:
        print(f"  ⚠ Golden ignorado — Stoch sobrecomprado {sk:.1f}")
        return "HOLD", price, "Filtro Stoch"
    elif death and sk <= 20:
        print(f"  ⚠ Death ignorado — Stoch sobrevendido {sk:.1f}")
        return "HOLD", price, "Filtro Stoch"
    else:
        return "HOLD", price, "Sin señal"

# ─── BLOQUE 5: GESTIÓN DE POSICIONES ─────────────────────────
position    = None
entry_price = 0

def open_position(side, price, qty):
    global position, entry_price
    cancel_orders()
    try:
        client.futures_create_order(
            symbol=SYMBOL,
            side=SIDE_BUY if side == "BUY" else SIDE_SELL,
            type=ORDER_TYPE_MARKET, quantity=qty)
        position    = "LONG" if side == "BUY" else "SHORT"
        entry_price = price
        tp = round(price*(1+TAKE_PROFIT) if position=="LONG"
                   else price*(1-TAKE_PROFIT), 1)
        sl = round(price*(1-STOP_LOSS) if position=="LONG"
                   else price*(1+STOP_LOSS), 1)
        place_exit_orders(position, price, qty)
        log_trade(f"ABRIR {position}", price,
                  "V3 EMA5/21+EMA200+Stoch", qty, tp, sl)
    except Exception as e:
        print(f"Error abrir: {e}")

def close_position(price, reason, qty):
    global position, entry_price
    cancel_orders()
    try:
        client.futures_create_order(
            symbol=SYMBOL,
            side=SIDE_SELL if position=="LONG" else SIDE_BUY,
            type=ORDER_TYPE_MARKET,
            quantity=qty, reduceOnly=True)
        pnl = (price-entry_price)/entry_price*100
        if position == "SHORT": pnl = -pnl
        log_trade(f"CERRAR {position}", price,
                  f"{reason} | PnL:{pnl:.2f}%"
                  f"({pnl*LEVERAGE:.2f}% con {LEVERAGE}x)", qty)
        position = None
        entry_price = 0
    except Exception as e:
        print(f"Error cerrar: {e}")

def check_exit(price, qty):
    global position, entry_price
    for pos in client.futures_position_information(symbol=SYMBOL):
        if float(pos["positionAmt"]) == 0 and position:
            print("  Posición cerrada por Binance (TP/SL)")
            position = None
            entry_price = 0
            return
    if position == "LONG":
        chg = (price - entry_price) / entry_price
        if chg <= -STOP_LOSS or chg >= TAKE_PROFIT:
            close_position(price, "Respaldo manual", qty)
    elif position == "SHORT":
        chg = (entry_price - price) / entry_price
        if chg <= -STOP_LOSS or chg >= TAKE_PROFIT:
            close_position(price, "Respaldo manual", qty)

# ─── BLOQUE 6: LOOP PRINCIPAL ─────────────────────────────────
def run_bot():
    global position, entry_price
    print("\n" + "="*54)
    print(f"  BOT V3 — {SYMBOL} {INTERVAL}")
    print(f"  Estrategia : EMA 5/21 + EMA200 + Stoch filtro")
    print(f"  Capital    : {CAPITAL_PCT*100}% | Leverage: {LEVERAGE}x")
    print(f"  TP: {TAKE_PROFIT*100}% | SL: {STOP_LOSS*100}%")
    print(f"  Backtest   : +77% en 6m | WR 41.2%")
    print("="*54)

    position, entry_price = detect_open_position()
    if position:
        qty = get_quantity()
        place_exit_orders(position, entry_price, qty)

    while True:
        try:
            print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Analizando...")
            qty    = get_quantity()
            df     = get_signals()
            signal, price, reason = check_signal(df)

            if position:
                print(f"  Pos: {position} @ {entry_price:.2f}")
                check_exit(price, qty)

            if signal == "BUY" and not position:
                open_position("BUY", price, qty)
            elif signal == "SELL" and not position:
                open_position("SELL", price, qty)

            print("  Próximo análisis en 15 min...")
            time.sleep(900)

        except Exception as e:
            print(f"Error: {e}")
            time.sleep(60)

run_bot()
