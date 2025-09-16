import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler
)
from telegram.error import BadRequest, TimedOut
import instaloader
import os
from pathlib import Path
import shutil
from dotenv import load_dotenv
import asyncio
import traceback
import random
import json
import time
import sqlite3
import requests
from io import BytesIO
import re
import unicodedata
import urllib3

# غیرفعال کردن هشدارهای InsecureRequestWarning
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# تنظیم لاگ برای بات
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# تنظیم لاگ برای instaloader
instaloader_logger = logging.getLogger('instaloader')
instaloader_logger.setLevel(logging.DEBUG)
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
instaloader_logger.addHandler(handler)

# مسیر اصلی پروژه
BASE_DIR = Path(r"C:\Users\asus\Desktop\telegram.bot")

# بارگذاری متغیرهای محیطی از فایل .env
if not (BASE_DIR / '.env').exists():
    logger.error("فایل .env پیدا نشد! لطفاً فایل .env را در C:\\Users\\asus\\Desktop\\telegram.bot بسازید.")
    print("خطا: فایل .env پیدا نشد! لطفاً فایل .env را با محتوای زیر در C:\\Users\\asus\\Desktop\\telegram.bot بسازید:")
    print("INSTAGRAM_USERNAME=your_instagram_username")
    print("INSTAGRAM_PASSWORD=your_instagram_password")
    exit(1)
else:
    load_dotenv(BASE_DIR / '.env')

# توکن بات و کانال
BOT_TOKEN = '8454233760:AAFBcP6nsjlHWZkPEWQFpHpziOYZP0DuKnk'  # توکن بات (@PostStoryBot)
CHANNEL_USERNAME = '@MyPosStoryBot'  # نام کاربری کانال (با نام کانال خودتون جایگزین کنید)

# اطلاعات لاگین اینستاگرام
INSTAGRAM_USERNAME = os.getenv('INSTAGRAM_USERNAME')
INSTAGRAM_PASSWORD = os.getenv('INSTAGRAM_PASSWORD')

# چک کردن وجود نام کاربری و رمز عبور
if not INSTAGRAM_USERNAME or not INSTAGRAM_PASSWORD:
    logger.error("نام کاربری یا رمز عبور اینستاگرام در فایل .env تنظیم نشده است.")
    print("خطا: نام کاربری یا رمز عبور اینستاگرام در فایل .env تنظیم نشده است.")
    print("لطفاً فایل .env را در C:\\Users\\asus\\Desktop\\telegram.bot با محتوای زیر پر کنید:")
    print("INSTAGRAM_USERNAME=your_instagram_username")
    print("INSTAGRAM_PASSWORD=your_instagram_password")
    exit(1)

# فایل accounts.json برای چندین اکانت
ACCOUNTS_FILE = BASE_DIR / 'accounts.json'

# لیست پروکسی‌های چرخشی (باید پر کنید)
PROXIES = [
    # مثال: {"http": "http://proxy1:port", "https": "http://proxy1:port"},
    # {"http": "http://proxy2:port", "https": "http://proxy2:port"},
]

# لیست User-Agent‌های تصادفی
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0.3 Safari/605.1.15",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 14_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.1 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:89.0) Gecko/20100101 Firefox/89.0",
    "Mozilla/5.0 (Linux; Android 10; SM-G975F) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Mobile Safari/537.36"
]

# حالت‌های گفتگو
USERNAME, POST_LINK = range(2)

# تنظیم پایگاه داده SQLite برای کش
CACHE_DB = BASE_DIR / 'cache.db'
CACHE_TTL = 3600  # زمان انقضای کش: 1 ساعت (3600 ثانیه)

def init_cache_db():
    conn = sqlite3.connect(CACHE_DB)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS cache (
            cache_key TEXT PRIMARY KEY,
            data TEXT,
            timestamp INTEGER
        )
    ''')
    conn.commit()
    conn.close()

def load_cache(cache_key):
    conn = sqlite3.connect(CACHE_DB)
    cursor = conn.cursor()
    cursor.execute('SELECT data, timestamp FROM cache WHERE cache_key = ?', (cache_key,))
    result = cursor.fetchone()
    conn.close()
    if result and time.time() - result[1] < CACHE_TTL:
        return json.loads(result[0])
    return None

def save_cache(cache_key, data):
    conn = sqlite3.connect(CACHE_DB)
    cursor = conn.cursor()
    cursor.execute('INSERT OR REPLACE INTO cache (cache_key, data, timestamp) VALUES (?, ?, ?)',
                  (cache_key, json.dumps(data, ensure_ascii=False), int(time.time())))
    conn.commit()
    conn.close()

# تابع بازسازی سشن با User-Agent تصادفی و بررسی Checkpoint
def rebuild_session(username, password, session_file):
    try:
        L = instaloader.Instaloader(
            user_agent=random.choice(USER_AGENTS),
            request_timeout=60.0
        )
        if PROXIES:
            proxy = random.choice(PROXIES)
            L.context._session.proxies.update(proxy)
            L.context._session.verify = False
            logger.info(f"Using proxy {proxy} for {username}")
        L.login(username, password)
        L.save_session_to_file(session_file)
        logger.info(f"Session rebuilt for {username} with User-Agent: {L.context._session.headers['User-Agent']}")
        return True
    except Exception as e:
        logger.error(f"Failed to rebuild session for {username}: {str(e)}")
        return False

# تابع بررسی Checkpoint
def check_checkpoint(username, password):
    try:
        session = requests.Session()
        session.headers.update({'User-Agent': random.choice(USER_AGENTS)})
        if PROXIES:
            session.proxies.update(random.choice(PROXIES))
        session.verify = False
        response = session.get('https://www.instagram.com/accounts/login/')
        csrf_token = re.search(r'"csrf_token":"(.*?)"', response.text).group(1)
        login_data = {
            'username': username,
            'password': password,
            'csrfmiddlewaretoken': csrf_token
        }
        response = session.post('https://www.instagram.com/accounts/login/ajax/', data=login_data)
        if 'checkpoint_url' in response.text:
            logger.warning(f"Checkpoint required for {username}")
            return False
        return response.status_code == 200
    except Exception as e:
        logger.error(f"Error checking checkpoint for {username}: {str(e)}")
        return False

# تابع اصلاح‌شده برای دریافت استوری‌ها
def custom_get_stories(L, userids, max_retries=10):
    from instaloader.structures import Story
    stories = []
    for attempt in range(max_retries):
        for userid in userids:
            try:
                L.context._session.headers.update({'User-Agent': random.choice(USER_AGENTS)})
                query = L.context.graphql_query(
                    "303a4ae99711322310f25250d988f3b7",
                    {"reel_ids": [str(userid)], "precomposed_overlay": False}
                )
                logger.debug(f"Attempt {attempt + 1}: API response for userid {userid}: {json.dumps(query, indent=2)}")
                with open(BASE_DIR / f"api_response_{userid}_{attempt + 1}.json", 'w', encoding='utf-8') as f:
                    json.dump(query, f, indent=2, ensure_ascii=False)
                if 'data' not in query or not query['data'].get('reels_media'):
                    logger.info(f"Attempt {attempt + 1}: No active stories or invalid response for userid {userid}")
                    if attempt < max_retries - 1:
                        time.sleep(random.uniform(300, 900))  # تأخیر 5-15 دقیقه
                        continue
                    return []
                reels = query['data']['reels_media']
                if not reels:
                    logger.info(f"No active stories found for userid {userid}")
                    return []
                for reel in reels:
                    stories.append(Story(L.context, reel, L.context.get_anonymous_profile()))
                time.sleep(random.uniform(60, 120))
                return stories
            except Exception as e:
                logger.error(f"Attempt {attempt + 1}: Error fetching stories for userid {userid}: {str(e)}\n{traceback.format_exc()}")
                if "401" in str(e) or "429" in str(e) or "403" in str(e):
                    if attempt < max_retries - 1:
                        time.sleep(random.uniform(300, 900))
                        continue
                return []
    return []

# تابع تلاش مجدد برای دانلود استوری‌ها
async def download_stories_with_retry(L, profile, stories_dir, max_retries=10):
    stories_dir = Path(stories_dir)
    for attempt in range(max_retries):
        try:
            L.dirname_pattern = str(stories_dir)
            logger.info(f"Attempt {attempt + 1}: Downloading stories to {stories_dir}")
            stories = custom_get_stories(L, [profile.userid], max_retries=max_retries)
            has_stories = False
            for story in stories:
                has_stories = True
                for item in story.get_items():
                    L.download_storyitem(item, target=str(stories_dir))
                    logger.info(f"Story {item.mediaid} from {profile.username} downloaded.")
                    await asyncio.sleep(random.uniform(60, 120))
            if not has_stories:
                return False, "This account currently has no active stories."
            return True, None
        except Exception as e:
            logger.error(f"Attempt {attempt + 1}: Error downloading stories: {str(e)}\n{traceback.format_exc()}")
            if "data" in str(e).lower() or "401" in str(e) or "429" in str(e) or "403" in str(e):
                if attempt < max_retries - 1:
                    await asyncio.sleep(random.uniform(300, 900))
                    continue
            return False, str(e)
    return False, "Failed to download stories after multiple attempts."

# تابع چک عضویت در کانال
async def check_membership(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    try:
        member = await context.bot.get_chat_member(CHANNEL_USERNAME, update.effective_user.id)
        return member.status in ['member', 'administrator', 'creator']
    except Exception as e:
        logger.error(f"Error checking membership: {e}")
        await update.effective_chat.send_message(
            f"Error checking membership: {str(e)}. 😔\n"
            f"Please ensure:\n"
            f"1. The channel {CHANNEL_USERNAME} exists and is public.\n"
            f"2. The bot @PostStoryBot is an admin in the channel.\n"
            f"3. The channel link is correct: https://t.me/{CHANNEL_USERNAME[1:]}"
        )
        return False

# پیام خوش‌آمدگویی و چک عضویت
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await check_membership(update, context):
        keyboard = [
            [InlineKeyboardButton("Join Channel", url=f"https://t.me/{CHANNEL_USERNAME[1:]}")],
            [InlineKeyboardButton("Check Again", callback_data='check_again')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            f"Hello! To use @PostStoryBot, you must first join the channel {CHANNEL_USERNAME}. 😊\n"
            "Click the button below to join the channel, then press 'Check Again' or type /start.",
            reply_markup=reply_markup
        )
        return ConversationHandler.END
    else:
        user_name = update.effective_user.first_name or "دوست عزیز"
        await update.message.reply_text(
            f"سلااام {user_name}! خیلی خوش اومدی عزیزم به صفحه من 😍\n"
            "قرار باهم دوست باشیم و کلی کارهای قشنگ برات انجام بدم:\n"
            "1. لینک پست بفرستی برات دانلود کنم 📥\n"
            "2. استوری برات دانلود کنم 🌟\n"
            "3. آمار پیج (فالوورها و فالویینگ‌ها) رو بهت بدم 📊\n"
            "4. هایلایت‌ها رو برات دانلود کنم 🎥\n"
            "\nحالا یه لینک بفرست یا آیدی موردنظرت رو بفرست! 😊"
        )
        return USERNAME

# دریافت username یا لینک پست
async def get_username(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip().lower()
    if text.startswith('https://www.instagram.com/p/') or text.startswith('https://www.instagram.com/reel/'):
        context.user_data['post_link'] = text
        return await get_post_link(update, context)
    else:
        if not text.startswith('@'):
            text = '@' + text
        context.user_data['username'] = text

        if not await check_membership(update, context):
            keyboard = [
                [InlineKeyboardButton("Join Channel", url=f"https://t.me/{CHANNEL_USERNAME[1:]}")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(
                f"Please join the channel {CHANNEL_USERNAME} first! 😊",
                reply_markup=reply_markup
            )
            return ConversationHandler.END

        keyboard = [
            [InlineKeyboardButton("Download Stories 🌟", callback_data='stories')],
            [InlineKeyboardButton("Download Highlights 🎥", callback_data='highlights')],
            [InlineKeyboardButton("Show Stats (Followers/Following) 📊", callback_data='stats')],
            [InlineKeyboardButton("Send New Username 😎", callback_data='new_username')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            f"Username received: {text}\nNow choose what you want: 😊",
            reply_markup=reply_markup
        )
        return USERNAME

# تابع اصلاح‌شده برای یافتن فایل‌ها
def find_files(directory):
    files = []
    try:
        directory = unicodedata.normalize('NFC', directory).encode('utf-8').decode('utf-8')
        for root, _, filenames in os.walk(directory):
            root = unicodedata.normalize('NFC', root).encode('utf-8').decode('utf-8')
            for filename in filenames:
                filename = unicodedata.normalize('NFC', filename).encode('utf-8').decode('utf-8')
                file_path = os.path.join(root, filename)
                if os.path.isfile(file_path) and os.access(file_path, os.R_OK):
                    file_size = os.path.getsize(file_path)
                    if file_size > 0:  # اطمینان از غیرخالی بودن فایل
                        files.append(file_path)
                        logger.info(f"Found file: {file_path} (size: {file_size} bytes)")
                    else:
                        logger.warning(f"File is empty: {file_path}")
                else:
                    logger.warning(f"File not accessible or does not exist: {file_path}")
    except Exception as e:
        logger.error(f"Error finding files in {directory}: {str(e)}\n{traceback.format_exc()}")
    return files

# دریافت لینک پست
async def get_post_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    link = update.message.text.strip()
    context.user_data['post_link'] = link
    processing_message = await update.message.reply_text("ربات در حال پردازش درخواست شماست، لطفا صبور باشید ❤️")
    
    # تنظیم instaloader
    L = instaloader.Instaloader(
        download_video_thumbnails=False,
        compress_json=False,
        request_timeout=60.0,
        user_agent=random.choice(USER_AGENTS)
    )
    if PROXIES:
        proxy = random.choice(PROXIES)
        L.context._session.proxies.update(proxy)
        L.context._session.verify = False
        logger.info(f"Using proxy {proxy} for post download")
    
    for attempt in range(10):
        try:
            # استخراج shortcode از لینک
            shortcode_match = re.search(r'instagram\.com/(?:p|reel)/([A-Za-z0-9_-]+)/?', link)
            if not shortcode_match:
                try:
                    await context.bot.delete_message(update.effective_chat.id, processing_message.message_id)
                except (BadRequest, TimedOut) as e:
                    logger.error(f"Error deleting processing message: {str(e)}")
                await update.message.reply_text(
                    f"Error: Invalid Instagram post link. 😔\n"
                    "Please send a valid post link (e.g., https://www.instagram.com/p/XXXXX/)."
                )
                return POST_LINK
            shortcode = shortcode_match.group(1)
            
            # بررسی کش
            cache_key = f"post_{shortcode}"
            cached_data = load_cache(cache_key)
            if cached_data and Path(cached_data.get('path', '')).exists():
                files = find_files(cached_data['path'])
                if files:
                    try:
                        await context.bot.delete_message(update.effective_chat.id, processing_message.message_id)
                    except (BadRequest, TimedOut) as e:
                        logger.error(f"Error deleting processing message: {str(e)}")
                    await update.message.reply_text("Using cached data. Sending files... 😊")
                    await send_files(update, context, cached_data['path'], f"Post from link {shortcode} 📥", processing_message.message_id)
                    await update.message.reply_text("Please send the next username or post link, or type /start. 😊")
                    return ConversationHandler.END

            # دانلود پست
            posts_dir = BASE_DIR / f"downloads/post_{shortcode}"
            posts_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"Attempt {attempt + 1}: Downloading post {shortcode} to {posts_dir}")
            post = instaloader.Post.from_shortcode(L.context, shortcode)
            L.download_post(post, target=str(posts_dir))
            # بررسی فایل‌ها با find_files
            files = find_files(str(posts_dir))
            logger.info(f"Files found in {posts_dir}: {files}")
            if not files:
                logger.error(f"Attempt {attempt + 1}: No files downloaded for post {shortcode}")
                if attempt < 9:
                    await asyncio.sleep(random.uniform(300, 900))  # تأخیر 5-15 دقیقه
                    continue
                try:
                    await context.bot.delete_message(update.effective_chat.id, processing_message.message_id)
                except (BadRequest, TimedOut) as e:
                    logger.error(f"Error deleting processing message: {str(e)}")
                await update.message.reply_text(
                    f"Error: No files found for post {shortcode}. 😔\n"
                    "Please check:\n"
                    "1. The post is public and not deleted.\n"
                    "2. The link is correct (e.g., https://www.instagram.com/p/XXXXX/).\n"
                    "3. Try again after 15-30 minutes or use a different network (e.g., mobile data).\n"
                    "4. Ensure the Instagram account in accounts.json is valid and not restricted."
                )
                return POST_LINK
            try:
                await context.bot.delete_message(update.effective_chat.id, processing_message.message_id)
            except (BadRequest, TimedOut) as e:
                logger.error(f"Error deleting processing message: {str(e)}")
            await send_files(update, context, str(posts_dir), f"Post from link {shortcode} 📥", processing_message.message_id)
            save_cache(cache_key, {'path': str(posts_dir), 'timestamp': int(time.time())})
            await update.message.reply_text("Please send the next username or post link, or type /start. 😊")
            return ConversationHandler.END
        except Exception as e:
            logger.error(f"Attempt {attempt + 1}: Error downloading post {shortcode}: {str(e)}\n{traceback.format_exc()}")
            if "403" in str(e) or "429" in str(e) or "401" in str(e):
                if attempt < 9:
                    # بازسازی سشن
                    account = get_random_account()
                    session_file = Path(r"C:\Users\asus\AppData\Local\Instaloader") / f"session-{account['username']}"
                    if check_checkpoint(account['username'], account['password']) and rebuild_session(account['username'], account['password'], session_file):
                        L.load_session_from_file(account['username'], session_file)
                        logger.info(f"Session loaded for {account['username']} with User-Agent: {L.context._session.headers['User-Agent']}")
                    if PROXIES:
                        proxy = random.choice(PROXIES)
                        L.context._session.proxies.update(proxy)
                        L.context._session.verify = False
                        logger.info(f"Switching to proxy {proxy} for attempt {attempt + 2}")
                    L.context._session.headers.update({'User-Agent': random.choice(USER_AGENTS)})
                    await asyncio.sleep(random.uniform(300, 900))
                    continue
            try:
                await context.bot.delete_message(update.effective_chat.id, processing_message.message_id)
            except (BadRequest, TimedOut) as e:
                logger.error(f"Error deleting processing message: {str(e)}")
            if "403" in str(e):
                await update.message.reply_text(
                    f"Error: Access forbidden (403 Forbidden) for post {shortcode}. 😔\n"
                    "Please check:\n"
                    "1. Wait 15-30 minutes or use a different network (e.g., mobile data).\n"
                    "2. The Instagram account in accounts.json is valid, does not have 2FA enabled, and is not restricted.\n"
                    "3. Log in to Instagram with the account and complete any verification (e.g., SMS or email).\n"
                    "4. Consider using a proxy to change your IP."
                )
            elif "429" in str(e):
                await update.message.reply_text(
                    f"Error: Too many requests to Instagram (429 Too Many Requests) for post {shortcode}. 😔\n"
                    "Please wait 15-30 minutes and try again or use a different network (e.g., mobile data)."
                )
            elif "401" in str(e):
                await update.message.reply_text(
                    f"Error: Unauthorized access (401 Unauthorized) for post {shortcode}. 😔\n"
                    "Please check:\n"
                    "1. Wait 15-30 minutes or use a different network (e.g., mobile data).\n"
                    "2. The Instagram account in accounts.json is valid and does not have 2FA enabled.\n"
                    "3. Log in to Instagram with the account and complete any verification."
                )
            else:
                await update.message.reply_text(
                    f"Error downloading post {shortcode}: {str(e)}. 😔\n"
                    "Please check:\n"
                    "1. The post is public and not deleted.\n"
                    "2. The link is correct (e.g., https://www.instagram.com/p/XXXXX/).\n"
                    "3. Try again later."
                )
            return POST_LINK

# تابع دانلود و ارسال عکس پروفایل
async def send_profile_picture(L, profile, update, context, caption, processing_message_id):
    for attempt in range(7):
        try:
            L.context._session.headers.update({'User-Agent': random.choice(USER_AGENTS)})
            profile_pic_url = profile.profile_pic_url
            response = requests.get(profile_pic_url, timeout=40, verify=False)
            if response.status_code == 200:
                photo = BytesIO(response.content)
                photo.name = f"{profile.username}_profile.jpg"
                try:
                    await context.bot.delete_message(update.effective_chat.id, processing_message_id)
                except (BadRequest, TimedOut) as e:
                    logger.error(f"Error deleting processing message: {str(e)}")
                await context.bot.send_photo(update.effective_chat.id, photo=photo, caption=caption + " 📸")
                return
            else:
                logger.error(f"Attempt {attempt + 1}: Failed to download profile picture for {profile.username}: HTTP {response.status_code}")
                if attempt < 6:
                    await asyncio.sleep(random.uniform(10, 20))
                    continue
        except Exception as e:
            logger.error(f"Attempt {attempt + 1}: Error downloading profile picture for {profile.username}: {str(e)}")
            if attempt < 6:
                await asyncio.sleep(random.uniform(10, 20))
                continue
    try:
        await context.bot.delete_message(update.effective_chat.id, processing_message_id)
    except (BadRequest, TimedOut) as e:
        logger.error(f"Error deleting processing message: {str(e)}")
    await context.bot.send_message(
        update.effective_chat.id,
        f"Error: Could not download profile picture for {profile.username} after 7 attempts. 😔\n"
        "Please check:\n"
        "1. The profile is public and has a profile picture.\n"
        "2. Your internet connection is stable.\n"
        "3. Try again after 15-30 minutes or use a different network (e.g., mobile data)."
    )

# تابع ارسال فایل‌ها به کاربر
async def send_files(update: Update, context: ContextTypes.DEFAULT_TYPE, folder: str, caption: str, processing_message_id):
    folder = Path(folder)
    files = find_files(str(folder))
    logger.info(f"Files found in {folder}: {files}")
    if not files:
        try:
            await context.bot.delete_message(update.effective_chat.id, processing_message_id)
        except (BadRequest, TimedOut) as e:
            logger.error(f"Error deleting processing message: {str(e)}")
        await update.effective_chat.send_message(
            f"Error: No files found in {folder}. 😔\n"
            "Please check:\n"
            "1. The content is public and not deleted.\n"
            "2. Your internet connection is stable.\n"
            "3. Try again after 15-30 minutes or use a different network (e.g., mobile data).\n"
            "4. Ensure the Instagram account in accounts.json is valid and not restricted."
        )
        return
    for file in files[:5]:
        try:
            with open(file, 'rb') as f:
                if file.endswith(('.jpg', '.png')):
                    await context.bot.send_photo(update.effective_chat.id, photo=f, caption=caption)
                elif file.endswith(('.mp4', '.mov')):
                    await context.bot.send_video(update.effective_chat.id, video=f, caption=caption)
                else:
                    await context.bot.send_document(update.effective_chat.id, document=f, caption=caption)
            await asyncio.sleep(3)
        except Exception as e:
            logger.error(f"خطا در ارسال فایل {file}: {e}")
            await context.bot.send_message(
                update.effective_chat.id,
                f"Error sending file {os.path.basename(file)}: {str(e)}. 😔\n"
                "Please try again later."
            )
    shutil.rmtree(folder, ignore_errors=True)
    try:
        await context.bot.delete_message(update.effective_chat.id, processing_message_id)
    except (BadRequest, TimedOut) as e:
        logger.error(f"Error deleting processing message: {str(e)}")

# تابع انتخاب اکانت تصادفی
def get_random_account():
    if ACCOUNTS_FILE.exists():
        with open(ACCOUNTS_FILE, 'r', encoding='utf-8') as f:
            accounts = json.load(f)
        return random.choice(accounts)
    return {'username': INSTAGRAM_USERNAME, 'password': INSTAGRAM_PASSWORD}

# هندل کردن دکمه‌ها
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    try:
        await query.answer()  # پاسخ سریع به CallbackQuery
    except BadRequest as e:
        logger.warning(f"Failed to answer callback query: {str(e)}")
        if "Query is too old" in str(e):
            pass  # نادیده گرفتن خطای قدیمی بودن
        else:
            raise

    username = context.user_data.get('username')
    if not username or not await check_membership(update, context):
        keyboard = [
            [InlineKeyboardButton("Join Channel", url=f"https://t.me/{CHANNEL_USERNAME[1:]}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.reply_text(
            f"Please join the channel {CHANNEL_USERNAME} and send a username! 😊",
            reply_markup=reply_markup
        )
        return ConversationHandler.END

    # ارسال پیام پردازش
    processing_message = await query.message.reply_text("ربات در حال پردازش درخواست شماست، لطفا صبور باشید ❤️")

    # تنظیم instaloader
    L = instaloader.Instaloader(
        download_video_thumbnails=False,
        compress_json=False,
        request_timeout=60.0,
        user_agent=random.choice(USER_AGENTS)
    )
    if PROXIES:
        proxy = random.choice(PROXIES)
        L.context._session.proxies.update(proxy)
        L.context._session.verify = False
        logger.info(f"Using proxy {proxy} for {query.data}")

    # لاگین برای استوری‌ها و هایلایت‌ها
    if query.data in ['stories', 'highlights']:
        account = get_random_account()
        current_username, current_password = account['username'], account['password']
        session_file = Path(r"C:\Users\asus\AppData\Local\Instaloader") / f"session-{current_username}"
        try:
            if session_file.exists():
                L.load_session_from_file(current_username, session_file)
                logger.info(f"Session loaded for {current_username} with User-Agent: {L.context._session.headers['User-Agent']}")
            else:
                if check_checkpoint(current_username, current_password) and rebuild_session(current_username, current_password, session_file):
                    L.load_session_from_file(current_username, session_file)
                else:
                    try:
                        await context.bot.delete_message(update.effective_chat.id, processing_message.message_id)
                    except (BadRequest, TimedOut) as e:
                        logger.error(f"Error deleting processing message: {str(e)}")
                    await query.message.reply_text(
                        f"Error: Failed to rebuild session for {current_username}. 😔\n"
                        "Please check:\n"
                        "1. Username and password in accounts.json are correct.\n"
                        "2. The Instagram account does not have 2FA enabled.\n"
                        "3. Log in to the Instagram app with the same credentials.\n"
                        "4. If Instagram requests a verification code, complete it on your phone or browser."
                    )
                    return ConversationHandler.END
        except Exception as e:
            logger.error(f"Error loading session for {current_username}: {e}")
            if check_checkpoint(current_username, current_password) and rebuild_session(current_username, current_password, session_file):
                L.load_session_from_file(current_username, session_file)
            else:
                try:
                    await context.bot.delete_message(update.effective_chat.id, processing_message.message_id)
                except (BadRequest, TimedOut) as e:
                    logger.error(f"Error deleting processing message: {str(e)}")
                await query.message.reply_text(
                    f"Error logging in to Instagram with {current_username}: {str(e)}. 😔\n"
                    "Please check:\n"
                    "1. Username and password in accounts.json are correct.\n"
                    "2. The Instagram account does not have 2FA enabled.\n"
                    "3. Log in to the Instagram app with the same credentials.\n"
                    "4. If Instagram requests a verification code, complete it on your phone or browser."
                )
                return ConversationHandler.END

    # تلاش برای دریافت پروفایل
    if query.data in ['stories', 'highlights', 'stats']:
        for attempt in range(10):
            try:
                await asyncio.sleep(random.uniform(5, 10))  # کاهش تأخیر اولیه برای سرعت
                L.context._session.headers.update({'User-Agent': random.choice(USER_AGENTS)})
                profile = instaloader.Profile.from_username(L.context, username[1:])
                if profile.is_private and query.data in ['stories', 'highlights']:
                    try:
                        await context.bot.delete_message(update.effective_chat.id, processing_message.message_id)
                    except (BadRequest, TimedOut) as e:
                        logger.error(f"Error deleting processing message: {str(e)}")
                    await query.message.reply_text(
                        f"Error: The account {username} is private. 😔\n"
                        "Stories and highlights can only be downloaded for public accounts or by followers."
                    )
                    return ConversationHandler.END
                break
            except Exception as e:
                logger.error(f"Attempt {attempt + 1}: Error finding profile {username}: {str(e)}\n{traceback.format_exc()}")
                if "401" in str(e) or "429" in str(e) or "403" in str(e):
                    if attempt < 9:
                        account = get_random_account()
                        session_file = Path(r"C:\Users\asus\AppData\Local\Instaloader") / f"session-{account['username']}"
                        if check_checkpoint(account['username'], account['password']) and rebuild_session(account['username'], account['password'], session_file):
                            L.load_session_from_file(account['username'], session_file)
                        if PROXIES:
                            proxy = random.choice(PROXIES)
                            L.context._session.proxies.update(proxy)
                            L.context._session.verify = False
                            logger.info(f"Switching to proxy {proxy} for attempt {attempt + 2}")
                        L.context._session.headers.update({'User-Agent': random.choice(USER_AGENTS)})
                        await asyncio.sleep(random.uniform(300, 900))
                        continue
                    try:
                        await context.bot.delete_message(update.effective_chat.id, processing_message.message_id)
                    except (BadRequest, TimedOut) as e:
                        logger.error(f"Error deleting processing message: {str(e)}")
                    await query.message.reply_text(
                        f"Error: {'Too many requests to Instagram (429 Too Many Requests)' if '429' in str(e) else 'Access forbidden (403 Forbidden) or Unauthorized (401 Unauthorized)'} for {username}. 😔\n"
                        "Please check:\n"
                        "1. Wait 15-30 minutes or use a different network (e.g., mobile data).\n"
                        "2. The Instagram account in accounts.json is valid, does not have 2FA enabled, and is not restricted.\n"
                        "3. Log in to Instagram with the account and complete any verification."
                    )
                    return ConversationHandler.END
                else:
                    try:
                        await context.bot.delete_message(update.effective_chat.id, processing_message.message_id)
                    except (BadRequest, TimedOut) as e:
                        logger.error(f"Error deleting processing message: {str(e)}")
                    await query.message.reply_text(
                        f"Error finding profile {username}: {str(e)}. 😔\n"
                        "Please check:\n"
                        "1. The username is correct and the profile is public.\n"
                        "2. Your internet connection is stable.\n"
                        "3. Try again later."
                    )
                    return ConversationHandler.END

    if query.data == 'stats':
        cache_key = f"stats_{username[1:]}"
        stats = (
            f"Name: {profile.full_name}\n"
            f"Bio: {profile.biography}\n"
            f"Followers: {profile.followers}\n"
            f"Following: {profile.followees}"
        )
        save_cache(cache_key, {'data': stats})
        await send_profile_picture(L, profile, update, context, stats, processing_message.message_id)
        await query.message.reply_text("Please send the next username or post link, or type /start. 😊")
        return ConversationHandler.END

    elif query.data == 'stories':
        cache_key = f"stories_{username[1:]}"
        cached_data = load_cache(cache_key)
        if cached_data and Path(cached_data.get('path', '')).exists():
            files = find_files(cached_data['path'])
            if files:
                try:
                    await context.bot.delete_message(update.effective_chat.id, processing_message.message_id)
                except (BadRequest, TimedOut) as e:
                    logger.error(f"Error deleting processing message: {str(e)}")
                await query.message.reply_text("Using cached data. Sending files... 😊")
                await send_files(update, context, cached_data['path'], f"Story from {username} 🌟", processing_message.message_id)
                await query.message.reply_text("Please send the next username or post link, or type /start. 😊")
                return ConversationHandler.END

        stories_dir = BASE_DIR / f"downloads/{username[1:]}_stories"
        stories_dir.mkdir(parents=True, exist_ok=True)
        success, error_msg = await download_stories_with_retry(L, profile, stories_dir, max_retries=10)
        if success:
            files = find_files(str(stories_dir))
            logger.info(f"Files found in {stories_dir}: {files}")
            if files:
                await send_files(update, context, str(stories_dir), f"Story from {username} 🌟", processing_message.message_id)
                save_cache(cache_key, {'path': str(stories_dir), 'timestamp': int(time.time())})
                await query.message.reply_text("Please send the next username or post link, or type /start. 😊")
            else:
                try:
                    await context.bot.delete_message(update.effective_chat.id, processing_message.message_id)
                except (BadRequest, TimedOut) as e:
                    logger.error(f"Error deleting processing message: {str(e)}")
                await query.message.reply_text(
                    f"Error: No story files found for {username}. 😔\n"
                    "Please check:\n"
                    "1. The account has active stories.\n"
                    "2. Try again after 15-30 minutes or use a different network (e.g., mobile data)."
                )
        else:
            try:
                await context.bot.delete_message(update.effective_chat.id, processing_message.message_id)
            except (BadRequest, TimedOut) as e:
                logger.error(f"Error deleting processing message: {str(e)}")
            if "data" in error_msg.lower():
                await query.message.reply_text(
                    f"Error fetching stories for {username}: Invalid response from Instagram. 😔\n"
                    "Please check:\n"
                    "1. The account is public and has active stories.\n"
                    "2. Wait 15-30 minutes or use a different network (e.g., mobile data).\n"
                    "3. The Instagram account in accounts.json is valid and not restricted."
                )
            elif "401" in error_msg or "403" in error_msg:
                await query.message.reply_text(
                    f"Error: {'Unauthorized access (401 Unauthorized)' if '401' in error_msg else 'Access forbidden (403 Forbidden)'} for {username}. 😔\n"
                    "Please check:\n"
                    "1. Wait 15-30 minutes or use a different network (e.g., mobile data).\n"
                    "2. The Instagram account in accounts.json is valid, does not have 2FA enabled, and is not restricted.\n"
                    "3. Log in to Instagram with the account and complete any verification."
                )
            elif "429" in error_msg:
                await query.message.reply_text(
                    f"Error: Too many requests to Instagram (429 Too Many Requests) for {username}. 😔\n"
                    "Please wait 15-30 minutes and try again or use a different network (e.g., mobile data)."
                )
            else:
                await query.message.reply_text(
                    f"Error downloading stories for {username}: {error_msg}. 😔\n"
                    "Please check:\n"
                    "1. The account is public and has active stories.\n"
                    "2. Your internet connection is stable.\n"
                    "3. Try again later."
                )
        return ConversationHandler.END

    elif query.data == 'highlights':
        cache_key = f"highlights_{username[1:]}"
        cached_data = load_cache(cache_key)
        if cached_data and Path(cached_data.get('path', '')).exists():
            files = find_files(cached_data['path'])
            if files:
                try:
                    await context.bot.delete_message(update.effective_chat.id, processing_message.message_id)
                except (BadRequest, TimedOut) as e:
                    logger.error(f"Error deleting processing message: {str(e)}")
                await query.message.reply_text("Using cached data. Sending files... 😊")
                await send_files(update, context, cached_data['path'], f"Highlight from {username} 🎥", processing_message.message_id)
                await query.message.reply_text("Please send the next username or post link, or type /start. 😊")
                return ConversationHandler.END

        highlights_dir = BASE_DIR / f"downloads/{username[1:]}_highlights"
        highlights_dir.mkdir(parents=True, exist_ok=True)
        try:
            for highlight in profile.get_highlights():
                L.context._session.headers.update({'User-Agent': random.choice(USER_AGENTS)})
                L.download_highlight(highlight, target=str(highlights_dir))
                await asyncio.sleep(random.uniform(60, 120))
            files = find_files(str(highlights_dir))
            logger.info(f"Files found in {highlights_dir}: {files}")
            if files:
                await send_files(update, context, str(highlights_dir), f"Highlight from {username} 🎥", processing_message.message_id)
                save_cache(cache_key, {'path': str(highlights_dir), 'timestamp': int(time.time())})
                await query.message.reply_text("Please send the next username or post link, or type /start. 😊")
            else:
                try:
                    await context.bot.delete_message(update.effective_chat.id, processing_message.message_id)
                except (BadRequest, TimedOut) as e:
                    logger.error(f"Error deleting processing message: {str(e)}")
                await query.message.reply_text(
                    f"Error: No highlight files found for {username}. 😔\n"
                    "Please check:\n"
                    "1. The account has highlights.\n"
                    "2. Try again after 15-30 minutes or use a different network (e.g., mobile data)."
                )
        except Exception as e:
            logger.error(f"Error downloading highlights for {username}: {str(e)}\n{traceback.format_exc()}")
            try:
                await context.bot.delete_message(update.effective_chat.id, processing_message.message_id)
            except (BadRequest, TimedOut) as e:
                logger.error(f"Error deleting processing message: {str(e)}")
            if "429" in str(e):
                await query.message.reply_text(
                    f"Error: Too many requests to Instagram (429 Too Many Requests) for {username}. 😔\n"
                    "Please wait 15-30 minutes and try again or use a different network (e.g., mobile data)."
                )
            elif "401" in str(e) or "403" in str(e):
                await query.message.reply_text(
                    f"Error: {'Unauthorized access (401 Unauthorized)' if '401' in str(e) else 'Access forbidden (403 Forbidden)'} for {username}. 😔\n"
                    "Please check:\n"
                    "1. Wait 15-30 minutes or use a different network (e.g., mobile data).\n"
                    "2. The Instagram account in accounts.json is valid, does not have 2FA enabled, and is not restricted.\n"
                    "3. Log in to Instagram with the account and complete any verification."
                )
            else:
                await query.message.reply_text(
                    f"Error downloading highlights for {username}: {str(e)}. 😔\n"
                    "Please check:\n"
                    "1. The account is public and has highlights.\n"
                    "2. Your internet connection is stable.\n"
                    "3. Try again later."
                )
            return ConversationHandler.END

    elif query.data == 'new_username':
        try:
            await context.bot.delete_message(update.effective_chat.id, processing_message.message_id)
        except (BadRequest, TimedOut) as e:
            logger.error(f"Error deleting processing message: {str(e)}")
        await query.message.reply_text("Please send a new Instagram username (e.g., 'nasa') or a post link. 😊")
        return USERNAME

# لغو گفتگو
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Operation canceled. Type /start to begin again. 😊")
    return ConversationHandler.END

# چک دوباره عضویت
async def check_again(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    try:
        await query.answer()
    except BadRequest as e:
        logger.warning(f"Failed to answer callback query: {str(e)}")
        if "Query is too old" in str(e):
            pass
        else:
            raise
    if await check_membership(update, context):
        await query.message.reply_text("Great! You're now a member. Type /start to begin. 😊")
    else:
        keyboard = [
            [InlineKeyboardButton("Join Channel", url=f"https://t.me/{CHANNEL_USERNAME[1:]}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.reply_text(
            f"You haven't joined the channel {CHANNEL_USERNAME} yet! Please click the button below to join and try again. 😊",
            reply_markup=reply_markup
        )

async def main():
    init_cache_db()
    app = Application.builder().token(BOT_TOKEN).connect_timeout(30.0).read_timeout(30.0).write_timeout(30.0).build()
    try:
        await app.bot.delete_webhook(drop_pending_updates=True)
        logger.info("Webhook successfully deleted.")
    except Exception as e:
        logger.error(f"Error deleting webhook: {e}")

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            USERNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_username)],
            POST_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_post_link)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )
    
    app.add_handler(conv_handler)
    app.add_handler(CallbackQueryHandler(button_handler, pattern='^(stories|highlights|stats|new_username)$'))
    app.add_handler(CallbackQueryHandler(check_again, pattern='^check_again$'))
    
    try:
        await app.initialize()
        await app.start()
        await app.updater.start_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True, timeout=30)
        while True:
            await asyncio.sleep(3600)
    except Exception as e:
        logger.error(f"Error running bot: {e}")
        print(f"Error: {e}. Please check:")
        print("1. Only one instance of the bot is running (check Task Manager).")
        print("2. Internet connection is stable.")
        print("3. Bot token is correct.")
    finally:
        try:
            await app.updater.stop()
            await app.stop()
            await app.shutdown()
        except Exception as e:
            logger.error(f"Error stopping bot: {e}")

if __name__ == '__main__':
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        print("Bot stopped by user.")
    except Exception as e:
        logger.error(f"Error running bot: {e}")
        print(f"Error running bot: {e}")
    finally:
        try:
            if loop.is_running():
                loop.run_until_complete(loop.shutdown_asyncgens())
            loop.close()
        except Exception as e:
            logger.error(f"Error closing event loop: {e}")
            print(f"Error closing event loop: {e}")