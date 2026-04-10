#!/usr/bin/env python3
"""
Telegram Bot VLESS Checker
Собирает vless:// ссылки из GitHub, проверяет и отправляет файлами админу
"""

import re
import subprocess
import tempfile
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
import os
import json
import socket
import logging
from datetime import datetime
from telegram import Bot
from telegram.ext import Application, CommandHandler, ContextTypes

# ========== НАСТРОЙКИ (ЗАМЕНИ НА СВОИ) ==========
BOT_TOKEN = "8695379271:AAEeFZU3I6qrV-IEJV1axB2p3tUxeBUAXoE"  # ТВОЙ ТОКЕН
ADMIN_ID = 7526512670  # ТВОЙ TELEGRAM ID (узнай у @userinfobot)
# =================================================

MAX_WORKING_KEYS = 50
CHECK_TIMEOUT = 10
MAX_WORKERS = 20
TEST_URL = "https://www.google.com"

# Источники для парсинга
GITHUB_SOURCES = [
    "https://raw.githubusercontent.com/Temnuk/naabuzil/main/",
    "https://raw.githubusercontent.com/ermaozi/get_subscribe/main/subscribe/vless.txt",
    "https://raw.githubusercontent.com/mahdibland/ShadowsocksAggregator/master/sub/share1.txt",
    "https://raw.githubusercontent.com/mahdibland/V2RayAggregator/master/sub/v2ray.txt",
    "https://raw.githubusercontent.com/mahdibland/ShadowsocksAggregator/master/sub/share_ssr.txt",
    "https://raw.githubusercontent.com/mahdibland/ShadowsocksAggregator/master/sub/share_trojan.txt",
    "https://raw.githubusercontent.com/mahdibland/ShadowsocksAggregator/master/sub/share_v2ray.txt",
    "https://raw.githubusercontent.com/mahdibland/V2RayAggregator/master/sub/share_v2ray.txt",
    "https://raw.githubusercontent.com/PooyaRaki/Configs/main/Sub.txt",
    "https://raw.githubusercontent.com/MrMohebi/xray-proxy-grabber-telegram/main/collected-proxies/vless.txt",
    "https://raw.githubusercontent.com/yebekhe/TelegramV2rayCollector/main/sub/normal/vless",
    "https://raw.githubusercontent.com/yebekhe/TelegramV2rayCollector/main/sub/splitted/vless",
    "https://raw.githubusercontent.com/vfarid/v2ray-configs/main/vless.txt",
]

# Настройка логов
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

def get_files_from_your_repo():
    """Парсит твой репозиторий Temnuk/naabuzil"""
    vless_urls = set()
    try:
        api_url = "https://api.github.com/repos/Temnuk/naabuzil/contents/"
        response = requests.get(api_url, timeout=15)
        if response.status_code == 200:
            files = response.json()
            for file in files:
                if file['type'] == 'file':
                    content_resp = requests.get(file['download_url'], timeout=15)
                    if content_resp.status_code == 200:
                        found = re.findall(r"vless://[a-zA-Z0-9\-_]+@[a-zA-Z0-9\.\-]+:\d+[^\s]*", content_resp.text)
                        vless_urls.update(found)
    except Exception as e:
        logging.error(f"Ошибка репозитория: {e}")
    return list(vless_urls)

def search_all_sources():
    """Поиск из всех источников"""
    all_urls = set(get_files_from_your_repo())
    
    for url in GITHUB_SOURCES:
        try:
            resp = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code == 200:
                found = re.findall(r"vless://[a-zA-Z0-9\-_]+@[a-zA-Z0-9\.\-]+:\d+[^\s]*", resp.text)
                all_urls.update(found)
        except:
            pass
    
    logging.info(f"Найдено уникальных ссылок: {len(all_urls)}")
    return list(all_urls)

def decode_vless_url(vless_url):
    """Декодирует vless ссылку"""
    pattern = r"vless://([a-fA-F0-9\-]+)@([^:]+):(\d+)(\?[^#]*)?(#.*)?"
    match = re.match(pattern, vless_url)
    if match:
        return {
            "uuid": match.group(1),
            "address": match.group(2),
            "port": match.group(3),
            "params": match.group(4) or "",
            "name": match.group(5) or ""
        }
    return None

def check_vless_with_xray(vless_url):
    """Проверка через xray-core"""
    xray_paths = ["xray", "/usr/local/bin/xray", "./xray"]
    xray_cmd = None
    for path in xray_paths:
        try:
            subprocess.run([path, "-version"], capture_output=True, timeout=5)
            xray_cmd = path
            break
        except:
            continue
    
    if not xray_cmd:
        return check_vless_simple(vless_url)
    
    info = decode_vless_url(vless_url)
    if not info:
        return False, None
    
    config = {
        "log": {"loglevel": "warning"},
        "inbounds": [{"port": 54321, "protocol": "socks", "settings": {"udp": False}}],
        "outbounds": [{
            "protocol": "vless",
            "settings": {"vnext": [{"address": info["address"], "port": int(info["port"]), "users": [{"id": info["uuid"]}]}]},
            "streamSettings": {"network": "tcp", "security": "none"}
        }]
    }
    
    if info["params"]:
        if "type=ws" in info["params"]:
            config["outbounds"][0]["streamSettings"]["network"] = "ws"
        if "security=tls" in info["params"] or "security=reality" in info["params"]:
            config["outbounds"][0]["streamSettings"]["security"] = "tls"
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump(config, f)
        config_path = f.name
    
    start_time = time.time()
    try:
        proc = subprocess.Popen([xray_cmd, "run", "-config", config_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(1)
        proxies = {"http": "socks5://127.0.0.1:54321", "https": "socks5://127.0.0.1:54321"}
        resp = requests.get(TEST_URL, proxies=proxies, timeout=CHECK_TIMEOUT)
        proc.terminate()
        proc.wait(timeout=2)
        if resp.status_code == 200:
            return True, int((time.time() - start_time) * 1000)
        return False, None
    except:
        return False, None
    finally:
        try:
            os.unlink(config_path)
        except:
            pass

def check_vless_simple(vless_url):
    """Простая TCP проверка"""
    info = decode_vless_url(vless_url)
    if not info:
        return False, None
    start = time.time()
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(CHECK_TIMEOUT)
        sock.connect((info["address"], int(info["port"])))
        sock.close()
        return True, int((time.time() - start) * 1000)
    except:
        return False, None

def get_country_from_ip(address):
    """Определяет страну по IP"""
    try:
        resp = requests.get(f"http://ip-api.com/json/{address}", timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("status") == "success":
                return data.get("countryCode", "XX"), data.get("country", "Unknown")
    except:
        pass
    return "XX", "Unknown"

def get_flag_emoji(country_code):
    """Конвертирует код страны в эмодзи флага"""
    if len(country_code) != 2:
        return "🌍"
    return chr(ord(country_code[0]) + 127397) + chr(ord(country_code[1]) + 127397)

def save_results(working_configs, base_filename):
    """Сохраняет рабочие конфиги в файлы по 50 штук"""
    if not working_configs:
        return []
    
    files_created = []
    file_index = 1
    saved = 0
    
    while saved < len(working_configs):
        if file_index == 1:
            filename = base_filename
        else:
            name, ext = os.path.splitext(base_filename)
            filename = f"{name}{file_index}{ext}"
        
        batch = working_configs[saved:saved + MAX_WORKING_KEYS]
        with open(filename, 'w', encoding='utf-8') as f:
            for config in batch:
                f.write(config + '\n')
        
        files_created.append(filename)
        saved += len(batch)
        file_index += 1
    
    return files_created

async def start(update, context):
    """Обработчик команды /start"""
    user_id = update.effective_user.id
    
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ Доступ запрещён. Ты не администратор.")
        return
    
    await update.message.reply_text(
        "🚀 *Бот запущен и готов к работе!*\n\n"
        "📡 *Доступные команды:*\n"
        "/check - начать проверку VLESS ключей\n"
        "/status - узнать статус последней проверки\n\n"
        "⏳ Проверка может занять 2-5 минут",
        parse_mode="Markdown"
    )

async def check(update, context):
    """Обработчик команды /check"""
    user_id = update.effective_user.id
    
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ Доступ запрещён.")
        return
    
    await update.message.reply_text(
        "🔍 *Начинаю проверку VLESS ключей...*\n"
        "⏳ Это займёт 2-5 минут. Собираю ссылки из GitHub и проверяю...",
        parse_mode="Markdown"
    )
    
    # Запускаем проверку в отдельном потоке, чтобы не блокировать бота
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, run_checker)
    
    if result["success"]:
        if result["files"]:
            await update.message.reply_text(
                f"✅ *Проверка завершена!*\n\n"
                f"📊 *Статистика:*\n"
                f"├ Найдено ссылок: {result['total_found']}\n"
                f"├ Рабочих ключей: {result['working_count']}\n"
                f"└ Файлов создано: {len(result['files'])}\n\n"
                f"📎 Отправляю файлы...",
                parse_mode="Markdown"
            )
            
            # Отправляем каждый файл
            for filepath in result["files"]:
                with open(filepath, 'rb') as f:
                    await update.message.reply_document(
                        document=f,
                        filename=os.path.basename(filepath),
                        caption=f"📁 {os.path.basename(filepath)} | {MAX_WORKING_KEYS} ключей на файл"
                    )
                # Удаляем файл после отправки
                os.remove(filepath)
        else:
            await update.message.reply_text(
                "❌ *Не найдено рабочих ключей!*\n"
                "Попробуй позже или проверь источники.",
                parse_mode="Markdown"
            )
    else:
        await update.message.reply_text(
            f"❌ *Ошибка при проверке:*\n{result['error']}",
            parse_mode="Markdown"
        )

async def status(update, context):
    """Обработчик команды /status"""
    user_id = update.effective_user.id
    
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ Доступ запрещён.")
        return
    
    await update.message.reply_text(
        "📊 *Статус бота:*\n"
        f"├ Бот активен\n"
        f"├ Админ ID: {ADMIN_ID}\n"
        f"├ Максимум ключей на файл: {MAX_WORKING_KEYS}\n"
        f"├ Таймаут проверки: {CHECK_TIMEOUT} сек\n"
        f"└ Потоков проверки: {MAX_WORKERS}\n\n"
        "🔄 Используй /check для запуска проверки",
        parse_mode="Markdown"
    )

def run_checker():
    """Запускает процесс проверки и возвращает результат"""
    try:
        # Сбор ссылок
        vless_urls = search_all_sources()
        if not vless_urls:
            return {"success": False, "error": "Не найдено ссылок"}
        
        vless_urls = list(set(vless_urls))
        total_found = len(vless_urls)
        
        # Проверка
        working = []
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            future_to_url = {executor.submit(check_vless_with_xray, url): url for url in vless_urls}
            
            for future in as_completed(future_to_url):
                url = future_to_url[future]
                try:
                    is_working, latency = future.result(timeout=CHECK_TIMEOUT + 5)
                    if is_working:
                        info = decode_vless_url(url)
                        if info:
                            country_code, country_name = get_country_from_ip(info["address"])
                            flag = get_flag_emoji(country_code)
                            new_name = f"{flag} {country_name} | Izzzy VPN"
                            if '#' in url:
                                url = re.sub(r'#.*$', f'#{new_name}', url)
                            else:
                                url += f'#{new_name}'
                        working.append(url)
                except:
                    pass
        
        # Сохранение результатов
        files = save_results(working, "Svoboda.txt")
        
        return {
            "success": True,
            "total_found": total_found,
            "working_count": len(working),
            "files": files
        }
    
    except Exception as e:
        return {"success": False, "error": str(e)}

def main():
    """Запуск бота"""
    # Создаем приложение
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Добавляем обработчики команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("check", check))
    application.add_handler(CommandHandler("status", status))
    
    print(f"🚀 Бот запущен! Админ ID: {ADMIN_ID}")
    print(f"📡 Доступные команды: /start, /check, /status")
    
    # Запускаем бота
    application.run_polling(allowed_updates=["message"])

if __name__ == "__main__":
    main()