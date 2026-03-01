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

# --- RENDER WEB SUNUCUSU ---
app = Flask('')
@app.route('/')
def home(): return "Bot Canlı ve Görev Başında!"

def run_web():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# --- AYARLAR ---
TOKEN = os.getenv("TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
TR = pytz.timezone('Europe/Istanbul')

BOT_ALIVE = False
LOG_FILE = "islem_gecmisi.csv"
COINS = ["BTC-USD", "ETH-USD"]
pozisyonlar = {coin: {"miktar": 0, "alis_fiyati": 0} for coin in COINS}
toplam_cuzdan = 1000.0
seen_news_ids = set()
NITTER_INSTANCES = ["https://nitter.net-fi.de", "https://nitter.privacydev.net", "https://nitter.unixfox.eu"]

# --- YARDIMCI FONKSİYONLAR ---
def islem_kaydet(coin, tip, fiyat, miktar, pnl=0):
    tarih = datetime.now(TR).strftime('%Y-%m-%d %H:%M:%S')
    df = pd.DataFrame([[tarih, coin, tip, fiyat, miktar, pnl]], 
                      columns=['Tarih', 'Coin', 'Tip', 'Fiyat', 'Miktar', 'PNL'])
    df.to_csv(LOG_FILE, mode='a', header=not os.path.exists(LOG_FILE), index=False)

def pivot_hesapla(df):
    high, low, close = df['High'].iloc[-2], df['Low'].iloc[-2], df['Close'].iloc[-2]
    pivot = (high + low + close) / 3
    return {"Pivot": pivot, "R1": (2 * pivot) - low, "R2": pivot + (high - low)}

# --- TELEGRAM KOMUTLARI ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global BOT_ALIVE
    BOT_ALIVE = True
    await update.message.reply_text("🚀 **Sistem Aktif!**\nAnalizler ve haber takibi başladı. /help ile komutları gör.")

async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global BOT_ALIVE
    BOT_ALIVE = False
    await update.message.reply_text("💤 **Bot Uyku Moduna Geçti.**")

async def portfoy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = f"📊 *Portföy Özeti*\nNakit: ${toplam_cuzdan:.2f}\n"
    for c, p in pozisyonlar.items():
        if p['miktar'] > 0: msg += f"• {c}: {p['miktar']:.4f} (@{p['alis_fiyati']})\n"
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not os.path.exists(LOG_FILE): return await update.message.reply_text("Henüz işlem yok.")
    df = pd.read_csv(LOG_FILE).tail(5)
    await update.message.reply_text(f"📜 *Son İşlemler*\n`{df.to_string(index=False)}`", parse_mode=ParseMode.MARKDOWN)

async def report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not os.path.exists(LOG_FILE): return await update.message.reply_text("Veri yok.")
    df = pd.read_csv(LOG_FILE)
    await update.message.reply_text(f"📈 *Haftalık Rapor*\nNet Kar: ${df['PNL'].sum():.2f}\nİşlem: {len(df)}")

# --- ANA DÖNGÜ (Trade & Haber) ---
async def background_loop(context: ContextTypes.DEFAULT_TYPE):
    global BOT_ALIVE, toplam_cuzdan
    if not BOT_ALIVE: return

    # Trade Analizi (Yahoo Engelini Aşmak İçin Try-Except)
    for coin in COINS:
        try:
            # Rate limit'i aşmamak için 1 saatlik veri çekiyoruz
            df = yf.download(coin, period="2d", interval="1h", progress=False)
            if df.empty or len(df) < 5: continue
            
            fiyat = df['Close'].iloc[-1]
            sv = pivot_hesapla(df)
            pos = pozisyonlar[coin]

            # ALIM KOŞULU
            if pos['miktar'] == 0 and fiyat > sv['R1']:
                alım_miktarı = (toplam_cuzdan / 2) / fiyat
                toplam_cuzdan -= (toplam_cuzdan / 2)
                pozisyonlar[coin] = {"miktar": alım_miktarı, "alis_fiyati": fiyat}
                islem_kaydet(coin, "ALIM", fiyat, alım_miktarı)
                await context.bot.send_message(CHAT_ID, f"🟢 **ALIM:** {coin} @ ${fiyat:.2f}")

            # SATIM KOŞULU
            elif pos['miktar'] > 0:
                pnl_yuzde = (fiyat - pos['alis_fiyati']) / pos['alis_fiyati']
                if fiyat >= sv['R2'] or pnl_yuzde <= -0.015:
                    kazanc = (pos['miktar'] * fiyat) * 0.999
                    pnl_dolar = kazanc - (pos['miktar'] * pos['alis_fiyati'])
                    toplam_cuzdan += kazanc
                    islem_kaydet(coin, "SATIM", fiyat, pos['miktar'], pnl_dolar)
                    pozisyonlar[coin] = {"miktar": 0, "alis_fiyati": 0}
                    await context.bot.send_message(CHAT_ID, f"🔴 **SATIM:** {coin} | PNL: ${pnl_dolar:.2f}")
        except Exception as e:
            print(f"⚠️ {coin} Veri Hatası: {e}")

    # Haber Analizi
    try:
        url = f"{random.choice(NITTER_INSTANCES)}/elonmusk/rss"
        feed = feedparser.parse(url)
        for entry in feed.entries[:1]:
            if entry.link not in seen_news_ids:
                if any(k in entry.title.lower() for k in ["btc", "crypto", "fed", "doge"]):
                    await context.bot.send_message(CHAT_ID, f"📢 *Haber:* {entry.title}\n[Link]({entry.link})", parse_mode=ParseMode.MARKDOWN)
                seen_news_ids.add(entry.link)
    except: pass

# --- BAŞLATICI ---
if __name__ == '__main__':
    Thread(target=run_web, daemon=True).start() # Render Portu İçin

    application = ApplicationBuilder().token(TOKEN).build()
    
    # Komutları Tanımla
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stop", stop))
    application.add_handler(CommandHandler("portfoy", portfoy))
    application.add_handler(CommandHandler("history", history))
    application.add_handler(CommandHandler("report", report))
    application.add_handler(CommandHandler("help", lambda u, c: u.message.reply_text("/start, /stop, /portfoy, /history, /report")))

    # Arka Plan Döngüsü (5 dakikada bir)
    if application.job_queue:
        application.job_queue.run_repeating(background_loop, interval=300, first=10)

    print("🤖 Bot Dinlemede...")
    application.run_polling()
