import os, asyncio, pandas as pd, yfinance as yf, feedparser, random, pytz, requests
from datetime import datetime
from threading import Thread
from flask import Flask
from telegram import Update, InputFile
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ParseMode

# --- RENDER WEB SERVER ---
app = Flask('')
@app.route('/')
def home(): return "Grand Trade V11.0 - Scalper & News Terminal Online!"

def run_web():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# --- AYARLAR ---
TOKEN = os.getenv("TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
TR = pytz.timezone('Europe/Istanbul')

BOT_ALIVE = True # Başlat komutu gelmeden de arka planı çalıştırır
LOG_FILE = "islem_gecmisi.csv"
COINS = ["BTC-USD", "ETH-USD", "SOL-USD"]
pozisyonlar = {coin: {"miktar": 0, "alis_fiyati": 0} for coin in COINS}
toplam_cuzdan = 1000.0
seen_ids = set()

# --- 35 HESAP & 50 KELİME ---
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

NITTER_INSTANCES = ["https://nitter.net-fi.de", "https://nitter.privacydev.net", "https://nitter.mint.lgbt", "https://nitter.unixfox.eu"]

# --- FONKSİYONLAR ---
def islem_kaydet(coin, tip, fiyat, bakiye, neden):
    zaman = datetime.now(TR).strftime('%Y-%m-%d %H:%M:%S')
    data = [[zaman, coin, tip, fiyat, bakiye, neden]]
    df = pd.DataFrame(data, columns=['Zaman', 'Coin', 'Tip', 'Fiyat', 'Bakiye', 'Neden'])
    df.to_csv(LOG_FILE, mode='a', header=not os.path.exists(LOG_FILE), index=False)

def pivot_hesapla(coin):
    try:
        df = yf.download(coin, period="2d", interval="1h", progress=False)
        if df.empty: return None
        h, l, c = df['High'].iloc[-2], df['Low'].iloc[-2], df['Close'].iloc[-2]
        p = (h + l + c) / 3
        return {"Pivot": p, "R1": (2*p)-l, "R2": p+(h-l), "S1": (2*p)-h}
    except: return None

# --- KOMUT HANDLERLARI ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚀 <b>V11.0 Scalper Sistemi Yayında!</b>\n35 Hesap ve 50 Kelime aktif olarak taranıyor.", parse_mode=ParseMode.HTML)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = ("📖 <b>Komut Listesi:</b>\n"
           "/portfoy - Mevcut nakit ve açık işlemler.\n"
           "/report - İşlem geçmişini CSV olarak gönderir.\n"
           "/history - Son 5 işlemi ekrana yansıtır.\n"
           "🔍 Manuel Arama: Bir kelime yazmanız yeterli.")
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)

async def portfoy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = f"💰 <b>Cüzdan Özeti</b>\nNakit: ${toplam_cuzdan:,.2f}\n\n"
    for c, p in pozisyonlar.items():
        if p['miktar'] > 0: msg += f"• {c}: {p['miktar']:.4f} (@{p['alis_fiyati']})\n"
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)

async def report_csv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if os.path.exists(LOG_FILE):
        await update.message.reply_document(document=open(LOG_FILE, 'rb'), filename="islem_gecmisi.csv", caption="📊 Tüm İşlem Geçmişi")
    else:
        await update.message.reply_text("❌ Henüz kaydedilmiş bir işlem yok.")

async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if os.path.exists(LOG_FILE):
        df = pd.read_csv(LOG_FILE).tail(5)
        msg = "📜 <b>Son 5 İşlem:</b>\n" + df.to_string(index=False)
        await update.message.reply_text(f"<code>{msg}</code>", parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text("Kayıt bulunamadı.")

# --- ARKA PLAN MOTORU ---
async def engine(context: ContextTypes.DEFAULT_TYPE):
    global toplam_cuzdan
    # 1. TRADE: BTC & ETH & SOL
    for coin in COINS:
        try:
            df = yf.download(coin, period="1d", interval="1m", progress=False)
            fiyat = df['Close'].iloc[-1]
            sv = pivot_hesapla(coin)
            if not sv: continue

            pos = pozisyonlar[coin]
            # ALIM KOŞULU (%0.6 kar alanı varsa)
            if pos["miktar"] == 0 and toplam_cuzdan > 10:
                if fiyat > sv["R1"] and (sv["R2"] - fiyat)/fiyat > 0.006:
                    islem_miktari = (toplam_cuzdan * 0.999) / fiyat
                    pozisyonlar[coin] = {"miktar": islem_miktari, "alis_fiyati": fiyat}
                    toplam_cuzdan = 0
                    islem_kaydet(coin, "ALIM", fiyat, 0, "R1 Kırılımı")
                    await context.bot.send_message(CHAT_ID, f"🔵 <b>ALIM: {coin}</b>\nFiyat: ${fiyat:,.2f}\nHedef: ${sv['R2']:,.2f}", parse_mode=ParseMode.HTML)

            # SATIM KOŞULU
            elif pos["miktar"] > 0:
                pnl = (fiyat - pos["alis_fiyati"]) / pos["alis_fiyati"]
                if fiyat >= sv["R2"] or pnl <= -0.015:
                    toplam_cuzdan = (pos["miktar"] * fiyat) * 0.999
                    islem_kaydet(coin, "SATIS", fiyat, toplam_cuzdan, "Hedef/Stop")
                    pozisyonlar[coin] = {"miktar": 0, "alis_fiyati": 0}
                    await context.bot.send_message(CHAT_ID, f"🔴 <b>SATIM: {coin}</b>\nKar/Zarar: %{pnl*100:.2f}\nBakiye: ${toplam_cuzdan:,.2f}", parse_mode=ParseMode.HTML)
        except: continue

    # 2. HABERLER (35 Hesap Tarama)
    for user in random.sample(KULLANICILAR, 5):
        try:
            feed = await asyncio.to_thread(feedparser.parse, f"{random.choice(NITTER_INSTANCES)}/{user}/rss")
            for entry in feed.entries[:2]:
                if entry.link not in seen_ids:
                    if any(k in entry.title.lower() for k in KRITIK_KELIMELER):
                        msg = f"📢 <b>@{user}</b>\n{entry.title}\n<a href='{entry.link}'>Habere Git</a>"
                        await context.bot.send_message(CHAT_ID, msg, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
                    seen_ids.add(entry.link)
        except: continue

async def hourly_levels(context: ContextTypes.DEFAULT_TYPE):
    msg = "📍 <b>Destek/Direnç Seviyeleri</b>\n"
    for coin in COINS:
        sv = pivot_hesapla(coin)
        if sv: msg += f"\n🪙 {coin}:\n🚧 Direnç: {sv['R1']:,.2f}\n✅ Destek: {sv['S1']:,.2f}\n"
    await context.bot.send_message(CHAT_ID, msg, parse_mode=ParseMode.HTML)

# --- RUN ---
if __name__ == '__main__':
    Thread(target=run_web, daemon=True).start()
    app_tg = ApplicationBuilder().token(TOKEN).build()
    
    app_tg.add_handler(CommandHandler("start", start))
    app_tg.add_handler(CommandHandler("help", help_command))
    app_tg.add_handler(CommandHandler("portfoy", portfoy))
    app_tg.add_handler(CommandHandler("report", report_csv))
    app_tg.add_handler(CommandHandler("history", history))
    
    jq = app_tg.job_queue
    jq.run_repeating(engine, interval=120, first=10) # 2 dakikada bir trade & haber
    jq.run_repeating(hourly_levels, interval=3600, first=30) # Saat başı seviyeler
    
    app_tg.run_polling()
