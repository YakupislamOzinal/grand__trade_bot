import os, asyncio, random, pandas as pd, yfinance as yf, pytz
from datetime import datetime, timedelta
from telegram import Update, Bot
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ParseMode
import feedparser
from threading import Thread
from flask import Flask

# --- AYARLAR ---
TOKEN = os.getenv("TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
app = Flask('')

# Bot Durum Değişkenleri
BOT_ALIVE = False  # Botun genel çalışma durumu
LOG_FILE = "islem_gecmisi.csv"
COINS = ["BTC-USD", "ETH-USD"]
BAKIYE = 1000.0
pozisyonlar = {coin: {"miktar": 0, "alis_fiyati": 0} for coin in COINS}
toplam_cuzdan = BAKIYE

# Nitter Sunucuları
NITTER_INSTANCES = ["https://nitter.net-fi.de", "https://nitter.privacydev.net", "https://nitter.unixfox.eu"]

# --- FLASK (Render Uyku Engelleme) ---
@app.route('/')
def home(): return "Bot Merkezi Aktif!"

def run_flask():
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))

# --- YARDIMCI FONKSİYONLAR ---
def islem_kaydet(tarih, coin, tip, fiyat, miktar, kar=0):
    df = pd.DataFrame([[tarih, coin, tip, fiyat, miktar, kar]], 
                      columns=['Tarih', 'Coin', 'Tip', 'Fiyat', 'Miktar', 'PNL'])
    df.to_csv(LOG_FILE, mode='a', header=not os.path.exists(LOG_FILE), index=False)

# --- TELEGRAM KOMUTLARI ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global BOT_ALIVE
    BOT_ALIVE = True
    await update.message.reply_text("🚀 Bot Başlatıldı! Haberler ve Trade döngüsü aktif.")

async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global BOT_ALIVE
    BOT_ALIVE = False
    await update.message.reply_text("💤 Bot uyku moduna alındı. Manuel komutlar dışında işlem yapmaz.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = ("📖 *Komut Listesi:*\n"
           "/start - Botu çalıştırır\n"
           "/stop - Botu duraklatır\n"
           "/portfoy - Anlık durum ve hedefler\n"
           "/history - Geçmiş işlemler\n"
           "/report - Haftalık kapsamlı rapor\n"
           "/shutdown - Sistemi tamamen kapatır\n"
           "Kelime (örn: 'elon') - Haberlerde ara")
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

async def portfoy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = "📊 *Anlık Portföy Durumu*\n"
    for coin, pos in pozisyonlar.items():
        durum = "BOŞTA" if pos['miktar'] == 0 else f"İçeride: {pos['miktar']:.4f} @ {pos['alis_fiyati']}"
        msg += f"• {coin}: {durum}\n"
    msg += f"\n💰 Kalan Nakit: ${toplam_cuzdan:.2f}"
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if os.path.exists(LOG_FILE):
        df = pd.read_csv(LOG_FILE).tail(10)
        await update.message.reply_text(f"📜 *Son 10 İşlem:*\n\n`{df.to_string(index=False)}`", parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text("Henüz kayıtlı işlem yok.")

async def weekly_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not os.path.exists(LOG_FILE):
        return await update.message.reply_text("Rapor için yeterli veri yok.")
    
    df = pd.read_csv(LOG_FILE)
    toplam_islem = len(df)
    toplam_pnl = df['PNL'].sum()
    en_karli = df[df['PNL'] > 0]['Coin'].mode().tolist()
    
    report = (f"📅 *HAFTALIK PERFORMANS RAPORU*\n"
              f"----------------------------\n"
              f"✅ Toplam İşlem: {toplam_islem}\n"
              f"💵 Net Kâr/Zarar: ${toplam_pnl:.2f}\n"
              f"🌟 En Çok İşlem Yapılan: {en_karli[0] if en_karli else 'N/A'}\n"
              f"📈 Başlangıç: ${BAKIYE} -> Son: ${toplam_cuzdan:.2f}")
    await update.message.reply_text(report, parse_mode=ParseMode.MARKDOWN)

async def search_news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.message.text.lower()
    await update.message.reply_text(f"🔍 '{query}' için son haberler taranıyor...")
    # Nitter üzerinden hızlı bir tarama yapıp sonuç döndüren fonksiyon buraya entegre edilir.

# --- ANA DÖNGÜ (Trade & Haber) ---
async def main_loop(context: ContextTypes.DEFAULT_TYPE):
    global BOT_ALIVE, toplam_cuzdan
    if not BOT_ALIVE: return

    # 1. TRADE MANTIĞI (Pivot Kırılımı)
    for coin in COINS:
        df = yf.download(coin, period="1d", interval="1h", progress=False)
        # ... (Paylaştığın pivot hesaplama ve al-sat mantığı buraya gelir) ...
        # Her işlemde islem_kaydet() çağrılır.

    # 2. HABER MANTIĞI
    # ... (Nitter RSS okuma mantığı) ...

# --- BOT KURULUMU ---
if __name__ == '__main__':
    # Flask'ı ayrı thread'de başlat
    Thread(target=run_flask, daemon=True).start()

    # Telegram Uygulaması
    app_tg = ApplicationBuilder().token(TOKEN).build()

    # Komutları ekle
    app_tg.add_handler(CommandHandler("start", start))
    app_tg.add_handler(CommandHandler("stop", stop))
    app_tg.add_handler(CommandHandler("help", help_command))
    app_tg.add_handler(CommandHandler("portfoy", portfoy))
    app_tg.add_handler(CommandHandler("history", history))
    app_tg.add_handler(CommandHandler("report", weekly_report))
    app_tg.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), search_news))

    # Zamanlanmış Görevler (Döngü her 5 dakikada bir çalışır)
    job_queue = app_tg.job_queue
    job_queue.run_repeating(main_loop, interval=300, first=10)
    
    # Otomatik Haftalık Rapor (Her Pazar 23:59)
    # job_queue.run_daily(weekly_report, time=datetime.time(hour=23, minute=59))

    print("🤖 Bot ve Web Sunucusu Başlatılıyor...")
    app_tg.run_polling()
