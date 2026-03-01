import os, asyncio, pandas as pd, yfinance as yf, feedparser, random, pytz, requests, time
from datetime import datetime
from threading import Thread
from flask import Flask
from telegram import Update, Bot
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ParseMode

# --- RENDER WEB SERVER (main.py'den) ---
app = Flask('')
@app.route('/')
def home(): return "Grand Trade Bot V9.0 - Hibrit Sistem Aktif!"

def run_web():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# --- AYARLAR ---
TOKEN = os.getenv("TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
TR = pytz.timezone('Europe/Istanbul')

BOT_ALIVE = False
LOG_FILE = "islem_gecmisi.csv"
COINS = ["BTC-USD", "ETH-USD", "SOL-USD"]
pozisyonlar = {coin: {"miktar": 0, "alis_fiyati": 0} for coin in COINS}
toplam_cuzdan = 1000.0 # Başlangıç Bakiyesi
seen_ids = set()

# --- 35 HESAP & 50 KELİME (Tam Liste) ---
KULLANICILAR = [
    "elonmusk", "binance", "cz_binance", "VitalikButerin", "Whale_Alert", "WatcherGuru", 
    "DeItaone", "BNONews", "spectatorindex", "unusual_whales", "zerohedge", "reuters", 
    "bloomberg", "coindesk", "cointelegraph", "saylor", "jack", "cathiedwood", 
    "brian_armstrong", "gemini", "krakenfx", "kucoincom", "okx", "bybit_official", 
    "bitfinex", "tether_to", "circle", "a16z", "paradigm", "multicoincap", "WuBlockchain",
    "AltcoinDailyio", "crypto", "Glassnode", "Santimentfeed"
]

KRITIK_KELIMELER = [
    "war", "attack", "missile", "explosion", "nuclear", "fed", "inflation", "cpi", 
    "interest rate", "hike", "cut", "recession", "bull", "bear", "pump", "dump", 
    "crash", "moon", "ath", "halving", "etf", "sec", "gensler", "listing", "delisting", 
    "hack", "exploit", "scam", "rugpull", "whale", "liquidation", "short squeeze", 
    "long", "short", "leverage", "defi", "nft", "solana", "ethereum", "bitcoin", 
    "breakout", "support", "resistance", "urgent", "breaking", "blacklist", "sanctions",
    "banned", "lawsuit", "settlement"
]

NITTER_INSTANCES = [
    "https://nitter.net-fi.de", "https://nitter.privacydev.net", 
    "https://nitter.mint.lgbt", "https://nitter.unixfox.eu", "https://nitter.perennialte.ch"
]

# --- YARDIMCI FONKSİYONLAR ---
def islem_kaydet(coin, tip, fiyat, bakiye, neden):
    zaman = datetime.now(TR).strftime('%Y-%m-%d %H:%M:%S')
    if not os.path.isfile(LOG_FILE):
        with open(LOG_FILE, "w") as f: f.write("Zaman,Coin,Tip,Fiyat,Bakiye,Neden\n")
    with open(LOG_FILE, "a") as f:
        f.write(f"{zaman},{coin},{tip},{fiyat},{bakiye},{neden}\n")

def pivot_hesapla(coin):
    try:
        df = yf.download(coin, period="2d", interval="1h", progress=False)
        h, l, c = df['High'].iloc[-2], df['Low'].iloc[-2], df['Close'].iloc[-2]
        p = (h + l + c) / 3
        return {"Pivot": p, "R1": (2*p)-l, "R2": p+(h-l), "S1": (2*p)-h}
    except: return None

# --- TELEGRAM KOMUTLARI ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global BOT_ALIVE
    BOT_ALIVE = True
    await update.message.reply_text("🚀 <b>V9.0 Hibrit Sistem Devrede!</b>\n\n35 Hesap, 50 Kelime ve Pivot Trade Algoritması eşzamanlı çalışıyor.", parse_mode=ParseMode.HTML)

async def portfoy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = f"💰 <b>Güncel Durum</b>\nNakit: ${toplam_cuzdan:,.2f}\n\n"
    for c, p in pozisyonlar.items():
        if p['miktar'] > 0: msg += f"• {c}: {p['miktar']:.4f} (@{p['alis_fiyati']})\n"
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)

async def news_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.message.text.lower()
    await update.message.reply_text(f"🔍 <b>'{query}'</b> için küresel ağ taranıyor...", parse_mode=ParseMode.HTML)
    ins = random.choice(NITTER_INSTANCES)
    try:
        feed = feedparser.parse(f"{ins}/search/rss?q={query}")
        if feed.entries:
            for e in feed.entries[:3]:
                await update.message.reply_text(f"📰 <b>{e.title}</b>\n<a href='{e.link}'>Habere Git</a>", parse_mode=ParseMode.HTML)
        else:
            await update.message.reply_text(f"❌ '{query}' ile ilgili sonuç bulunamadı.")
    except:
        await update.message.reply_text("⚠️ Sunucu meşgul, tekrar deneyin.")

# --- ANA MOTOR (TRADE & HABER) ---
async def hourly_report(context: ContextTypes.DEFAULT_TYPE):
    if not BOT_ALIVE: return
    msg = "📍 <b>Saatlik Hedef Raporu</b>\n"
    for coin in COINS:
        sv = pivot_hesapla(coin)
        if sv:
            msg += f"\n🪙 <b>{coin}:</b>\n🎯 Hedef (R2): {sv['R2']:.2f}\n🛡️ Destek (S1): {sv['S1']:.2f}\n"
    await context.bot.send_message(CHAT_ID, msg, parse_mode=ParseMode.HTML)

async def main_engine(context: ContextTypes.DEFAULT_TYPE):
    global BOT_ALIVE, toplam_cuzdan
    if not BOT_ALIVE: return

    # 1. TRADE ALGORİTMASI (main.py'den)
    for coin in COINS:
        try:
            df = yf.download(coin, period="1d", interval="1m", progress=False)
            if df.empty: continue
            fiyat = df['Close'].iloc[-1]
            sv = pivot_hesapla(coin)
            pos = pozisyonlar[coin]

            if pos["miktar"] == 0 and toplam_cuzdan > 10:
                # R1 Kırılımı + %0.6 Marj Kontrolü
                if fiyat > sv["R1"] and (sv["R2"] - fiyat)/fiyat > 0.006:
                    islem_miktari = (toplam_cuzdan * 0.999) / fiyat
                    pozisyonlar[coin] = {"miktar": islem_miktari, "alis_fiyati": fiyat}
                    toplam_cuzdan = 0
                    islem_kaydet(coin, "ALIM", fiyat, 0, "R1 Kırılımı")
                    await context.bot.send_message(CHAT_ID, f"🔵 <b>İŞLEME GİRİLDİ: {coin}</b>\n📉 Alış: ${fiyat:,.2f}\n🎯 Hedef R2: ${sv['R2']:,.2f}", parse_mode=ParseMode.HTML)

            elif pos["miktar"] > 0:
                pnl = (fiyat - pos["alis_fiyati"]) / pos["alis_fiyati"]
                if fiyat >= sv["R2"] or pnl <= -0.015:
                    toplam_cuzdan = (pos["miktar"] * fiyat) * 0.999
                    islem_kaydet(coin, "SATIS", fiyat, toplam_cuzdan, "Hedef/Stop")
                    pozisyonlar[coin] = {"miktar": 0, "alis_fiyati": 0}
                    emoji = "💰" if pnl > 0 else "📉"
                    await context.bot.send_message(CHAT_ID, f"{emoji} <b>POZİSYON KAPANDI: {coin}</b>\nNet PNL: %{pnl*100:.2f}\n💵 Bakiye: ${toplam_cuzdan:,.2f}", parse_mode=ParseMode.HTML)
        except: continue

    # 2. İSTİHBARAT DÖNGÜSÜ (main (1).py'den)
    for user in random.sample(KULLANICILAR, 5):
        ins = random.choice(NITTER_INSTANCES)
        try:
            url = f"{ins}/{user}/rss"
            feed = await asyncio.get_event_loop().run_in_executor(None, lambda: feedparser.parse(url))
            for entry in feed.entries[:2]:
                if entry.link not in seen_ids:
                    if any(k in entry.title.lower() for k in KRITIK_KELIMELER):
                        msg = f"🚨 <b>İstihbarat: @{user}</b>\n{entry.title}\n<a href='{entry.link}'>Detaylar</a>"
                        await context.bot.send_message(CHAT_ID, msg, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
                    seen_ids.add(entry.link)
        except: continue

# --- BAŞLATICI ---
if __name__ == '__main__':
    Thread(target=run_web, daemon=True).start()
    application = ApplicationBuilder().token(TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("portfoy", portfoy))
    application.add_handler(CommandHandler("report", lambda u,c: u.message.reply_text("Rapor CSV'ye kaydediliyor...")))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), news_search))

    application.job_queue.run_repeating(hourly_report, interval=3600, first=10)
    application.job_queue.run_repeating(main_engine, interval=300, first=60)

    application.run_polling()
