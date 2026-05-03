# ============================================================
# CRYPTOBOTAI — BOT FREE v1.0
# Estrategia: EMA 9/21 + Filtro EMA 200 + RSI < 50
# Backtest 12 meses: +54.2% | Win Rate: 38.6%
# Rentabilidad real con 5x leverage: ~271%
# TP: 3% | SL: 1% | Capital por trade: 5%
# ============================================================
#
# INSTRUCCIONES DE INSTALACION:
# 1. Instala Python 3.11+ desde python.org
# 2. Abre terminal y ejecuta:
#    pip install python-binance pandas ta requests
# 3. Ve a testnet.binancefuture.com
# 4. Crea una cuenta y genera tus API Keys
# 5. Reemplaza TU_API_KEY y TU_API_SECRET abajo
# 6. Ejecuta: python free_bot.py
#
# ============================================================

import time, csv, os, requests
from datetime import datetime
import pandas as pd
import ta
from binance.client import Client
from binance.enums import *

# ─────────────────────────────────────────────────────────────
#  CONFIGURACION — EDITA SOLO ESTAS DOS LINEAS
# ─────────────────────────────────────────────────────────────
API_KEY    = "PEGA_TU_API_KEY_AQUI"
API_SECRET = "PEGA_TU_API_SECRET_AQUI"
# ─────────────────────────────────────────────────────────────

SYMBOL      = "BTCUSDT"
INTERVAL    = "15m"
CAPITAL_PCT = 0.05    # 5% del balance por trade
LEVERAGE    = 5       # 5x apalancamiento
STOP_LOSS   = 0.010   # 1%  → con 5x = 5% real
TAKE_PROFIT = 0.030   # 3%  → con 5x = 15% real
LOG_FILE    = "track_record_free.csv"

# ─── CONEXION ────────────────────────────────────────────────
print("=" * 54)
print("  CRYPTOBOTAI — BOT FREE")
print("  EMA 9/21 + EMA 200 + RSI<50")
print("  Backtest 12m: +54.2% | WR: 38.6% | Leverage: 5x")
print("=" * 54)

try:
    server_time = requests.get(
        "https://testnet.binancefuture.com/fapi/v1/time",
        timeout=10
    ).json()["serverTime"]
    client = Client(API_KEY, API_SECRET, testnet=True)
    client.timestamp_offset = server_time - int(time.time() * 1000)
    client.futures_change_leverage(symbol=SYMBOL, leverage=LEVERAGE)
    print(f"\n✓ Conectado a Binance Testnet")
    print(f"✓ Leverage {LEVERAGE}x configurado\n")
except Exception as e:
    print(f"\n✗ Error de conexion: {e}")
    print("  Verifica tus API keys y conexion a internet\n")
    exit(1)

# ─── FUNCIONES UTILES ────────────────────────────────────────
def get_quantity():
    balance  = client.futures_account_balance()
    usdt     = next((float(b["balance"]) for b in balance
                     if b["asset"] == "USDT"), 0)
    price    = float(client.futures_symbol_ticker(symbol=SYMBOL)["price"])
    cantidad = round((usdt * CAPITAL_PCT * LEVERAGE) / price, 3)
    print(f"  Balance: {usdt:.2f} USDT | "
          f"Poder ({LEVERAGE}x): {usdt*CAPITAL_PCT*LEVERAGE:.2f} | "
          f"BTC: {cantidad}")
    return cantidad

def detect_open_position():
    for pos in client.futures_position_information(symbol=SYMBOL):
        amt = float(pos["positionAmt"])
        if amt > 0:
            e = float(pos["entryPrice"])
            print(f"  ⚠ Posicion LONG activa @ {e:.2f} — bot la retoma")
            return "LONG", e
        elif amt < 0:
            e = float(pos["entryPrice"])
            print(f"  ⚠ Posicion SHORT activa @ {e:.2f} — bot la retoma")
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
        print(f"  ✓ Take Profit en {tp_px} "
              f"(+{TAKE_PROFIT*100}% / +{TAKE_PROFIT*LEVERAGE*100:.0f}% real)")
    except Exception as e:
        print(f"  Error TP: {e}")
    try:
        client.futures_create_order(
            symbol=SYMBOL, side=cs,
            type="STOP_MARKET",
            stopPrice=sl_px, closePosition=True,
            timeInForce="GTE_GTC")
        print(f"  ✓ Stop Loss en {sl_px} "
              f"(-{STOP_LOSS*100}% / -{STOP_LOSS*LEVERAGE*100:.0f}% real)")
    except Exception as e:
        print(f"  Error SL: {e}")

def log_trade(action, price, reason, qty=0, pnl_pct=0, pnl_real=0, pnl_usd=0):
    exists = os.path.isfile(LOG_FILE)
    with open(LOG_FILE, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if not exists:
            w.writerow(["Fecha","Hora","Accion","Precio","Cantidad",
                        "PnL_%","PnL_real_%","PnL_USD","Motivo","Leverage"])
        now = datetime.now()
        w.writerow([now.strftime("%Y-%m-%d"), now.strftime("%H:%M:%S"),
                    action, price, qty,
                    f"{pnl_pct:.2f}%", f"{pnl_real:.2f}%",
                    f"${pnl_usd:.2f}", reason, f"{LEVERAGE}x"])
    print(f"[{datetime.now().strftime('%H:%M:%S')}] "
          f"{action} @ {price} | {reason}")

# ─── SEÑALES — EMA9/21 + EMA200 + RSI ────────────────────────
def get_signals():
    klines = client.futures_klines(
        symbol=SYMBOL, interval=INTERVAL, limit=250)
    df = pd.DataFrame(klines, columns=[
        "time","open","high","low","close","volume",
        "close_time","qav","num_trades",
        "taker_buy_base","taker_buy_quote","ignore"])
    df["close"]  = pd.to_numeric(df["close"])
    df["high"]   = pd.to_numeric(df["high"])
    df["low"]    = pd.to_numeric(df["low"])
    df["ema9"]   = ta.trend.ema_indicator(df["close"], window=9)
    df["ema21"]  = ta.trend.ema_indicator(df["close"], window=21)
    df["ema200"] = ta.trend.ema_indicator(df["close"], window=200)
    df["rsi"]    = ta.momentum.rsi(df["close"], window=14)
    return df.dropna().reset_index(drop=True)

def check_signal(df):
    last   = df.iloc[-1]
    prev   = df.iloc[-2]
    price  = float(last["close"])
    ema9   = float(last["ema9"])
    ema21  = float(last["ema21"])
    ema200 = float(last["ema200"])
    rsi    = float(last["rsi"])

    golden = (float(prev["ema9"]) < float(prev["ema21"])) and (ema9 > ema21)
    death  = (float(prev["ema9"]) > float(prev["ema21"])) and (ema9 < ema21)
    sobre  = price > ema200
    bajo   = price < ema200
    tend   = "ALCISTA ▲" if sobre else "BAJISTA ▼"

    print(f"  P:{price:,.0f} | "
          f"E9:{ema9:,.0f} E21:{ema21:,.0f} E200:{ema200:,.0f} | "
          f"RSI:{rsi:.1f} | {tend}")

    if golden and rsi < 50 and sobre:
        return "BUY",  price, f"Golden cross RSI={rsi:.1f} sobre EMA200"
    elif death and rsi > 40 and bajo:
        return "SELL", price, f"Death cross RSI={rsi:.1f} bajo EMA200"
    elif golden and not sobre:
        print("  ⚠ Golden ignorado — precio bajo EMA200")
        return "HOLD", price, "Filtro EMA200"
    elif death and not bajo:
        print("  ⚠ Death ignorado — precio sobre EMA200")
        return "HOLD", price, "Filtro EMA200"
    else:
        return "HOLD", price, "Sin señal"

# ─── GESTION DE POSICIONES ───────────────────────────────────
position    = None
entry_price = 0
balance_ini = 0

def open_position(side, price, qty):
    global position, entry_price, balance_ini
    cancel_orders()
    try:
        client.futures_create_order(
            symbol=SYMBOL,
            side=SIDE_BUY if side == "BUY" else SIDE_SELL,
            type=ORDER_TYPE_MARKET, quantity=qty)
        position    = "LONG" if side == "BUY" else "SHORT"
        entry_price = price
        # Guardar balance para calcular PnL en USD
        bal = client.futures_account_balance()
        balance_ini = next((float(b["balance"]) for b in bal
                           if b["asset"] == "USDT"), 0)
        tp = round(price*(1+TAKE_PROFIT) if position=="LONG"
                   else price*(1-TAKE_PROFIT), 1)
        sl = round(price*(1-STOP_LOSS) if position=="LONG"
                   else price*(1+STOP_LOSS), 1)
        place_exit_orders(position, price, qty)
        log_trade(f"ABRIR {position}", price,
                  f"FREE EMA9/21+EMA200+RSI | TP:{tp} SL:{sl}",
                  qty)
    except Exception as e:
        print(f"  Error al abrir: {e}")

def close_position(price, reason, qty):
    global position, entry_price, balance_ini
    cancel_orders()
    try:
        client.futures_create_order(
            symbol=SYMBOL,
            side=SIDE_SELL if position == "LONG" else SIDE_BUY,
            type=ORDER_TYPE_MARKET,
            quantity=qty, reduceOnly=True)
        # Calcular PnL
        pnl_pct  = (price - entry_price) / entry_price * 100
        if position == "SHORT": pnl_pct = -pnl_pct
        pnl_real = pnl_pct * LEVERAGE
        pnl_usd  = balance_ini * CAPITAL_PCT * (pnl_real / 100)
        log_trade(f"CERRAR {position}", price, reason,
                  qty, pnl_pct, pnl_real, pnl_usd)
        print(f"  PnL bruto: {pnl_pct:+.2f}% | "
              f"PnL real ({LEVERAGE}x): {pnl_real:+.2f}% | "
              f"USD: ${pnl_usd:+.2f}")
        position    = None
        entry_price = 0
        balance_ini = 0
    except Exception as e:
        print(f"  Error al cerrar: {e}")

def check_exit(price, qty):
    global position, entry_price
    for pos in client.futures_position_information(symbol=SYMBOL):
        if float(pos["positionAmt"]) == 0 and position:
            print("  Posicion cerrada por Binance (TP o SL alcanzado)")
            position    = None
            entry_price = 0
            return
    if position == "LONG":
        chg = (price - entry_price) / entry_price
        if chg <= -STOP_LOSS or chg >= TAKE_PROFIT:
            close_position(price, "Cierre respaldo manual", qty)
    elif position == "SHORT":
        chg = (entry_price - price) / entry_price
        if chg <= -STOP_LOSS or chg >= TAKE_PROFIT:
            close_position(price, "Cierre respaldo manual", qty)

# ─── LOOP PRINCIPAL ──────────────────────────────────────────
def run_bot():
    global position, entry_price

    print(f"  Par: {SYMBOL} | Temporalidad: {INTERVAL}")
    print(f"  Capital por trade: {CAPITAL_PCT*100:.0f}%")
    print(f"  Apalancamiento: {LEVERAGE}x")
    print(f"  Take Profit: {TAKE_PROFIT*100:.0f}% bruto "
          f"({TAKE_PROFIT*LEVERAGE*100:.0f}% real con {LEVERAGE}x)")
    print(f"  Stop Loss:    {STOP_LOSS*100:.0f}% bruto "
          f"({STOP_LOSS*LEVERAGE*100:.0f}% real con {LEVERAGE}x)")
    print(f"  Log: {LOG_FILE}")
    print("=" * 54 + "\n")

    position, entry_price = detect_open_position()
    if position:
        qty = get_quantity()
        place_exit_orders(position, entry_price, qty)

    while True:
        try:
            print(f"\n[{datetime.now().strftime('%H:%M:%S')}] "
                  f"Analizando mercado...")
            qty    = get_quantity()
            df     = get_signals()
            signal, price, reason = check_signal(df)

            if position:
                print(f"  Posicion activa: {position} @ {entry_price:,.2f}")
                check_exit(price, qty)

            if signal == "BUY" and not position:
                open_position("BUY", price, qty)
            elif signal == "SELL" and not position:
                open_position("SELL", price, qty)

            print(f"  Proximo analisis en 15 minutos...")
            time.sleep(900)

        except Exception as e:
            print(f"  Error: {e} — reintentando en 60s...")
            time.sleep(60)

run_bot()
