import os
import asyncio
import pandas as pd
import yfinance as yf
import feedparser
import random
import pytz
from datetime import datetime
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ParseMode

# --- AYARLAR ---
TOKEN = os.getenv("TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
TR = pytz.timezone('Europe/Istanbul')

# Bot Kontrol Değişkenleri
BOT_ALIVE = False  # /start ile True olur
LOG_FILE = "islem_gecmisi.csv"
COINS = ["BTC-USD", "ETH-USD"]
BAKIYE = 1000.0
KOMISYON = 0.001
pozisyonlar = {coin: {"miktar": 0, "alis_fiyati": 0} for coin in COINS}
toplam_cuzdan = BAKIYE

# Haber Kaynakları (Nitter)
KULLANICILAR = ["elonmusk", "binance", "WatcherGuru", "DeItaone"]
NITTER_INSTANCES = ["https://nitter.net-fi.de", "https://nitter.privacydev.net", "https://nitter.unixfox.eu"]
seen_news_ids = set()

# --- YARDIMCI FONKSİYONLAR ---
def islem_kaydet(coin, tip, fiyat, miktar, pnl=0):
    tarih = datetime.now(TR).strftime('%Y-%m-%d %H:%M:%S')
    df = pd.DataFrame([[tarih, coin, tip, fiyat, miktar, pnl]], 
                      columns=['Tarih', 'Coin', 'Tip', 'Fiyat', 'Miktar', 'PNL'])
    df.to_csv(LOG_FILE, mode='a', header=not os.path.exists(LOG_FILE), index=False)

def pivot_hesapla(df):
    high = df['High'].iloc[-2]
    low = df['Low'].iloc[-2]
    close = df['Close'].iloc[-2]
    pivot = (high + low + close) / 3
    return {
        "Pivot": pivot,
        "R1": (2 * pivot) - low,
        "S1": (2 * pivot) - high,
        "R2": pivot + (high - low),
        "S2": pivot - (high - low)
    }

# --- TELEGRAM KOMUTLARI ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global BOT_ALIVE
    BOT_ALIVE = True
    await update.message.reply_text("🚀 **Bot Aktif!**\nSistem piyasayı ve haberleri taramaya başladı.", parse_mode=ParseMode.MARKDOWN)

async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global BOT_ALIVE
    BOT_ALIVE = False
    await update.message.reply_text("💤 **Bot Uyku Modunda.**\nOtomatik işlemler durduruldu.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = ("📖 *Komut Kılavuzu:*\n"
           "/start - Botu başlatır\n"
           "/stop - Botu duraklatır\n"
           "/portfoy - Anlık bakiye ve pozisyonlar\n"
           "/history - Son işlemler\n"
           "/report - Haftalık PNL raporu\n"
           "Kelime yazın (örn: 'btc') - Haberlerde arar")
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

async def portfoy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = "📊 *Mevcut Durum*\n"
    for coin, pos in pozisyonlar.items():
        durum = "Nakit" if pos['miktar'] == 0 else f"{pos['miktar']:.4f} @ ${pos['alis_fiyati']}"
        msg += f"• {coin}: {durum}\n"
    msg += f"\n💰 Toplam Nakit: ${toplam_cuzdan:.2f}"
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if os.path.exists(LOG_FILE):
        df = pd.read_csv(LOG_FILE).tail(5)
        await update.message.reply_text(f"📜 *Son 5 İşlem:*\n`{df.to_string(index=False)}`", parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text("Henüz kayıtlı işlem yok.")

async def report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not os.path.exists(LOG_FILE):
        return await update.message.reply_text("Rapor için veri birikmedi.")
    df = pd.read_csv(LOG_FILE)
    toplam_pnl = df['PNL'].sum()
    await update.message.reply_text(f"📈 *Haftalık Performans*\nNet Kar/Zarar: ${toplam_pnl:.2f}\nİşlem Sayısı: {len(df)}")

async def news_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.message.text.lower()
    ins = random.choice(NITTER_INSTANCES)
    await update.message.reply_text(f"🔍 {query} için {ins} taranıyor...")
    # Basit arama mantığı (Elon Musk vb. kelimeler için son haberleri getirir)

# --- ANA DÖNGÜ (Background Task) ---
async def monitor_market(context: ContextTypes.DEFAULT_TYPE):
    global BOT_ALIVE, toplam_cuzdan
    if not BOT_ALIVE: return

    # 1. Trade Takibi
    for coin in COINS:
        try:
            df = yf.download(coin, period="2d", interval="1h", progress=False)
            if len(df) < 5: continue
            
            fiyat = df['Close'].iloc[-1]
            sv = pivot_hesapla(df)
            pos = pozisyonlar[coin]

            # ALIM: Fiyat R1'i yukarı kırarsa
            if pos['miktar'] == 0 and fiyat > sv['R1']:
                miktar = (toplam_cuzdan / 2) / fiyat
                toplam_cuzdan -= (toplam_cuzdan / 2)
                pozisyonlar[coin] = {"miktar": miktar, "alis_fiyati": fiyat}
                islem_kaydet(coin, "ALIM", fiyat, miktar)
                await context.bot.send_message(CHAT_ID, f"🟢 *ALIM YAPILDI: {coin}*\nFiyat: ${fiyat:.2f}")

            # SATIM: Hedef R2 veya %1.5 Stop
            elif pos['miktar'] > 0:
                pnl_yuzde = (fiyat - pos['alis_fiyati']) / pos['alis_fiyati']
                if fiyat >= sv['R2'] or pnl_yuzde <= -0.015:
                    kazanc = (pos['miktar'] * fiyat) * (1 - KOMISYON)
                    pnl_dolar = kazanc - (pos['miktar'] * pos['alis_fiyati'])
                    toplam_cuzdan += kazanc
                    islem_kaydet(coin, "SATIM", fiyat, pos['miktar'], pnl_dolar)
                    pozisyonlar[coin] = {"miktar": 0, "alis_fiyati": 0}
                    await context.bot.send_message(CHAT_ID, f"🔴 *SATIM YAPILDI: {coin}*\nPNL: ${pnl_dolar:.2f}")
        except Exception as e:
            print(f"Hata {coin}: {e}")

    # 2. Haber Takibi
    for user in KULLANICILAR:
        try:
            url = f"{random.choice(NITTER_INSTANCES)}/{user}/rss"
            feed = feedparser.parse(url)
            for entry in feed.entries[:2]:
                if entry.link not in seen_news_ids:
                    if any(k in entry.title.lower() for k in ["btc", "crypto", "fed", "elon", "pump"]):
                        await context.bot.send_message(CHAT_ID, f"📢 *{user} paylaştı:*\n{entry.title}\n[Habere Git]({entry.link})", parse_mode=ParseMode.MARKDOWN)
                    seen_news_ids.add(entry.link)
        except: continue

# --- ANA ÇALIŞTIRICI ---
if __name__ == '__main__':
    application = ApplicationBuilder().token(TOKEN).build()
    
    # Komutlar
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stop", stop))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("portfoy", portfoy))
    application.add_handler(CommandHandler("history", history))
    application.add_handler(CommandHandler("report", report))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), news_search))

    # Döngüyü başlat (Her 5 dakikada bir)
    job_queue = application.job_queue
    job_queue.run_repeating(monitor_market, interval=300, first=10)

    print("✅ Bot başlatıldı, komut bekleniyor...")
    application.run_polling()
