import os, asyncio, pandas as pd, yfinance as yf, feedparser, random, pytz, requests
from datetime import datetime, timedelta
from threading import Thread
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ParseMode

# --- RENDER KEEP-ALIVE ---
app = Flask('')
@app.route('/')
def home(): return "Grand Trade Bot V8.0 Ultimate Online!"

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
toplam_cuzdan = 1000.0
seen_news_ids = set()

# --- 35 STRATEJİK HESAP ---
KULLANICILAR = [
    "elonmusk", "binance", "cz_binance", "VitalikButerin", "Whale_Alert", "WatcherGuru", 
    "DeItaone", "BNONews", "spectatorindex", "unusual_whales", "zerohedge", "reuters", 
    "bloomberg", "coindesk", "cointelegraph", "saylor", "jack", "cathiedwood", 
    "brian_armstrong", "gemini", "krakenfx", "kucoincom", "okx", "bybit_official", 
    "bitfinex", "tether_to", "circle", "a16z", "paradigm", "multicoincap", "WuBlockchain",
    "AltcoinDailyio", "crypto", "Glassnode", "Santimentfeed"
]

# --- 50 KRİTİK KELİME ---
KRITIK_KELIMELER = [
    "war", "attack", "missile", "explosion", "nuclear", "fed", "inflation", "cpi", 
    "interest rate", "hike", "cut", "recession", "bull", "bear", "pump", "dump", 
    "crash", "moon", "ath", "halving", "etf", "sec", "gensler", "listing", "delisting", 
    "hack", "exploit", "scam", "rugpull", "whale", "liquidation", "short squeeze", 
    "long", "short", "leverage", "defi", "nft", "solana", "ethereum", "bitcoin", 
    "breakout", "support", "resistance", "urgent", "breaking", "blacklist", "sanctions",
    "banned", "lawsuit", "settlement"
]

NITTER_INSTANCES = ["https://nitter.net-fi.de", "https://nitter.privacydev.net", "https://nitter.unixfox.eu"]

# --- EK ÖZELLİKLER VE FONKSİYONLAR ---
def get_fear_greed():
    try:
        r = requests.get("https://api.alternative.me/fng/").json()
        return f"{r['data'][0]['value']} ({r['data'][0]['value_classification']})"
    except: return "Alınamadı"

def islem_kaydet(coin, tip, fiyat, miktar, pnl=0):
    tarih = datetime.now(TR).strftime('%Y-%m-%d %H:%M:%S')
    df = pd.DataFrame([[tarih, coin, tip, fiyat, miktar, pnl]], 
                      columns=['Tarih', 'Coin', 'Tip', 'Fiyat', 'Miktar', 'PNL'])
    df.to_csv(LOG_FILE, mode='a', header=not os.path.exists(LOG_FILE), index=False)

def pivot_hesapla(df):
    h, l, c = df['High'].iloc[-2], df['Low'].iloc[-2], df['Close'].iloc[-2]
    p = (h + l + c) / 3
    return {"Pivot": p, "R1": (2*p)-l, "R2": p+(h-l), "S1": (2*p)-h}

# --- TELEGRAM KOMUTLARI ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global BOT_ALIVE
    BOT_ALIVE = True
    await update.message.reply_text("👑 **Grand Trade V8.0 Başlatıldı!**\n\n35 Hesap ve 50 Kelime aktif olarak taranıyor.\n/help ile tüm yeteneklerimi gör.")

async def portfoy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    fng = get_fear_greed()
    msg = f"📊 **Portföy & Piyasa**\n💰 Bakiye: ${toplam_cuzdan:.2f}\n😨 Korku Endeksi: {fng}\n\n"
    for c, p in pozisyonlar.items():
        if p['miktar'] > 0: msg += f"• {c}: {p['miktar']:.4f} (@{p['alis_fiyati']})\n"
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

async def weekly_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not os.path.exists(LOG_FILE): return await update.message.reply_text("Veri yok.")
    df = pd.read_csv(LOG_FILE)
    total_pnl = df['PNL'].sum()
    win_rate = (len(df[df['PNL'] > 0]) / len(df[df['Tip'] == "SATIM"])) * 100 if len(df[df['Tip'] == "SATIM"]) > 0 else 0
    msg = (f"📅 **HAFTALIK PERFORMANS**\n"
           f"💵 Net Kâr: ${total_pnl:.2f}\n"
           f"🎯 Başarı Oranı: %{win_rate:.1f}\n"
           f"📝 Toplam İşlem: {len(df)}")
    await update.message.reply_text(msg)

async def news_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.message.text.lower()
    await update.message.reply_text(f"🔍 '{query}' taranıyor...")
    ins = random.choice(NITTER_INSTANCES)
    try:
        feed = feedparser.parse(f"{ins}/search/rss?q={query}")
        if feed.entries:
            for e in feed.entries[:3]: await update.message.reply_text(f"📰 {e.title}\n{e.link}")
        else: await update.message.reply_text("Sonuç bulunamadı.")
    except: await update.message.reply_text("Haber servisi şu an meşgul.")

# --- ANA DÖNGÜLER ---
async def hourly_analysis(context: ContextTypes.DEFAULT_TYPE):
    if not BOT_ALIVE: return
    msg = "📉 **SAATLİK TEKNİK ANALİZ**\n"
    for coin in COINS:
        try:
            df = yf.download(coin, period="2d", interval="1h", progress=False)
            sv = pivot_hesapla(df)
            msg += f"\n*{coin}:* ${df['Close'].iloc[-1]:.2f}\n   🚧 R1: {sv['R1']:.2f} | ✅ S1: {sv['S1']:.2f}\n"
        except: continue
    await context.bot.send_message(CHAT_ID, msg, parse_mode=ParseMode.MARKDOWN)

async def main_engine(context: ContextTypes.DEFAULT_TYPE):
    global BOT_ALIVE, toplam_cuzdan
    if not BOT_ALIVE: return

    # 1. TRADE & VOLATİLİTE KONTROLÜ
    for coin in COINS:
        try:
            df = yf.download(coin, period="2d", interval="1h", progress=False)
            fiyat = df['Close'].iloc[-1]
            sv = pivot_hesapla(df)
            pos = pozisyonlar[coin]

            if pos['miktar'] == 0 and fiyat > sv['R1']:
                miktar = (toplam_cuzdan / len(COINS)) / fiyat
                toplam_cuzdan -= (toplam_cuzdan / len(COINS))
                pozisyonlar[coin] = {"miktar": miktar, "alis_fiyati": fiyat}
                islem_kaydet(coin, "ALIM", fiyat, miktar)
                await context.bot.send_message(CHAT_ID, f"🟢 **ALIM:** {coin} @ ${fiyat:.2f}")

            elif pos['miktar'] > 0:
                pnl = (fiyat - pos['alis_fiyati']) / pos['alis_fiyati']
                if fiyat >= sv['R2'] or pnl <= -0.015:
                    kazanc = (pos['miktar'] * fiyat) * 0.999
                    islem_kaydet(coin, "SATIM", fiyat, pos['miktar'], kazanc - (pos['miktar']*pos['alis_fiyati']))
                    toplam_cuzdan += kazanc
                    pozisyonlar[coin] = {"miktar": 0, "alis_fiyati": 0}
                    await context.bot.send_message(CHAT_ID, f"🔴 **SATIM:** {coin} | PNL: %{pnl*100:.2f}")
        except: continue

    # 2. 35 HESAP & 50 KELİME TARAMASI
    for user in random.sample(KULLANICILAR, 5): # Her döngüde rastgele 5 hesap (Rate limit için)
        try:
            feed = feedparser.parse(f"{random.choice(NITTER_INSTANCES)}/{user}/rss")
            for e in feed.entries[:2]:
                if e.link not in seen_news_ids:
                    if any(k in e.title.lower() for k in KRITIK_KELIMELER):
                        await context.bot.send_message(CHAT_ID, f"🚨 **KRİTİK (@{user}):**\n{e.title}\n[Oku]({e.link})", parse_mode=ParseMode.MARKDOWN)
                    seen_news_ids.add(e.link)
        except: continue

# --- RUN ---
if __name__ == '__main__':
    Thread(target=run_web, daemon=True).start()
    application = ApplicationBuilder().token(TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("portfoy", portfoy))
    application.add_handler(CommandHandler("report", weekly_report))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), news_search))

    application.job_queue.run_repeating(hourly_analysis, interval=3600, first=10)
    application.job_queue.run_repeating(main_engine, interval=300, first=60)

    application.run_polling()
