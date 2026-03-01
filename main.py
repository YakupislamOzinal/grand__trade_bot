import os
import asyncio
import pandas as pd
import yfinance as yf
import feedparser
import random
import pytz
from datetime import datetime
from threading import Thread
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ParseMode

# --- RENDER PORT AYARI (Hata Almamak İçin Şart) ---
app = Flask('')

@app.route('/')
def home():
    return "🚀 Bot 7/24 Aktif Durumda!"

def run_web():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# --- AYARLAR ---
TOKEN = os.getenv("TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
TR = pytz.timezone('Europe/Istanbul')

BOT_ALIVE = False  # /start komutuyla True olur
LOG_FILE = "islem_gecmisi.csv"
COINS = ["BTC-USD", "ETH-USD"]
BAKIYE = 1000.0
pozisyonlar = {coin: {"miktar": 0, "alis_fiyati": 0} for coin in COINS}
toplam_cuzdan = BAKIYE
seen_news_ids = set()

# Nitter Sunucuları (Twitter Haberleri İçin)
NITTER_INSTANCES = ["https://nitter.net-fi.de", "https://nitter.privacydev.net", "https://nitter.unixfox.eu"]
KULLANICILAR = ["elonmusk", "binance", "WatcherGuru", "DeItaone"]

# --- YARDIMCI FONKSİYONLAR ---
def islem_kaydet(coin, tip, fiyat, miktar, pnl=0):
    tarih = datetime.now(TR).strftime('%Y-%m-%d %H:%M:%S')
    df = pd.DataFrame([[tarih, coin, tip, fiyat, miktar, pnl]], 
                      columns=['Tarih', 'Coin', 'Tip', 'Fiyat', 'Miktar', 'PNL'])
    df.to_csv(LOG_FILE, mode='a', header=not os.path.exists(LOG_FILE), index=False)

def pivot_hesapla(df):
    high, low, close = df['High'].iloc[-2], df['Low'].iloc[-2], df['Close'].iloc[-2]
    pivot = (high + low + close) / 3
    return {"Pivot": pivot, "R1": (2 * pivot) - low, "R2": pivot + (high - low), "S1": (2 * pivot) - high}

# --- TELEGRAM KOMUTLARI ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global BOT_ALIVE
    BOT_ALIVE = True
    await update.message.reply_text("✅ **Sistem Başlatıldı.**\nTrade döngüsü ve haber tarayıcı aktif.")

async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global BOT_ALIVE
    BOT_ALIVE = False
    await update.message.reply_text("💤 **Sistem Durduruldu.**\nBot uyku moduna geçti.")

async def portfoy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = "📊 *Anlık Portföy*\n"
    for coin, pos in pozisyonlar.items():
        durum = "Nakit" if pos['miktar'] == 0 else f"{pos['miktar']:.4f} @ ${pos['alis_fiyati']}"
        msg += f"• {coin}: {durum}\n"
    msg += f"\n💰 Kullanılabilir Nakit: ${toplam_cuzdan:.2f}"
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if os.path.exists(LOG_FILE):
        df = pd.read_csv(LOG_FILE).tail(5)
        await update.message.reply_text(f"📜 *Son 5 İşlem*\n`{df.to_string(index=False)}`", parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text("Henüz kayıtlı işlem yok.")

async def report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not os.path.exists(LOG_FILE): return await update.message.reply_text("Yetersiz veri.")
    df = pd.read_csv(LOG_FILE)
    await update.message.reply_text(f"📈 *Haftalık Rapor*\nNet PNL: ${df['PNL'].sum():.2f}\nToplam İşlem: {len(df)}")

async def news_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.message.text.lower()
    await update.message.reply_text(f"🔍 '{query}' ile ilgili son haberler taranıyor...")

# --- ANA DÖNGÜ (Trade & Haber) ---
async def background_loop(context: ContextTypes.DEFAULT_TYPE):
    global BOT_ALIVE, toplam_cuzdan
    if not BOT_ALIVE: return

    # 1. Trade Mantığı (Pivot Kırılımı)
    for coin in COINS:
        try:
            df = yf.download(coin, period="2d", interval="1h", progress=False)
            if df.empty: continue
            fiyat = df['Close'].iloc[-1]
            sv = pivot_hesapla(df)
            pos = pozisyonlar[coin]

            if pos['miktar'] == 0 and fiyat > sv['R1']:
                miktar = (toplam_cuzdan / 2) / fiyat
                toplam_cuzdan -= (toplam_cuzdan / 2)
                pozisyonlar[coin] = {"miktar": miktar, "alis_fiyati": fiyat}
                islem_kaydet(coin, "ALIM", fiyat, miktar)
                await context.bot.send_message(CHAT_ID, f"🟢 **ALIM:** {coin} @ ${fiyat:.2f}")

            elif pos['miktar'] > 0:
                pnl = (fiyat - pos['alis_fiyati']) / pos['alis_fiyati']
                if fiyat >= sv['R2'] or pnl <= -0.015:
                    kazanc = (pos['miktar'] * fiyat) * 0.999
                    kar_dolar = kazanc - (pos['miktar'] * pos['alis_fiyati'])
                    toplam_cuzdan += kazanc
                    islem_kaydet(coin, "SATIM", fiyat, pos['miktar'], kar_dolar)
                    pozisyonlar[coin] = {"miktar": 0, "alis_fiyati": 0}
                    await context.bot.send_message(CHAT_ID, f"🔴 **SATIM:** {coin} | PNL: ${kar_dolar:.2f}")
        except: continue

    # 2. Haber Mantığı
    for user in KULLANICILAR:
        try:
            feed = feedparser.parse(f"{random.choice(NITTER_INSTANCES)}/{user}/rss")
            for entry in feed.entries[:2]:
                if entry.link not in seen_news_ids:
                    if any(k in entry.title.lower() for k in ["btc", "crypto", "elon", "fed"]):
                        await context.bot.send_message(CHAT_ID, f"📢 *{user}:*\n{entry.title}\n[Haber]({entry.link})", parse_mode=ParseMode.MARKDOWN)
                    seen_news_ids.add(entry.link)
        except: continue

# --- ANA ÇALIŞTIRICI ---
if __name__ == '__main__':
    # Render'ın botu kapatmaması için web sunucusunu başlat
    Thread(target=run_web, daemon=True).start()

    application = ApplicationBuilder().token(TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stop", stop))
    application.add_handler(CommandHandler("portfoy", portfoy))
    application.add_handler(CommandHandler("history", history))
    application.add_handler(CommandHandler("report", report))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), news_search))

    job_queue = application.job_queue
    job_queue.run_repeating(background_loop, interval=300, first=10)

    print("🚀 Bot yayında...")
    application.run_polling()
