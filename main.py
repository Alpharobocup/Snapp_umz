# telegram_snap_bot.py
# نسخه کامل پایه برای ربات تلگرام هماهنگی 'اسنپ' دانشگاهی
# اجرا با Flask و pyTelegramBotAPI (telebot) و وبهوک — بدون دیتابیس (تماماً در RAM)
# توجه: این فایل را روی Render یا هر سرویس مشابه با متغیر محیطی تنظیم شده اجرا کنید.

import os
import threading
import time
from datetime import datetime, timedelta
from flask import Flask, request, abort
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# ----------------------------- CONFIG -----------------------------
# مقداردهی از متغیر محیطی بهتر است؛ در صورت عدم وجود، مقادیر پیشفرض استفاده می‌شود.
BOT_TOKEN = os.environ.get('BOT_TOKEN', '7476401114:AAGpXYSipVMpBZbH_hc4aRV2YfDCF_M1Qgg')
ADMIN_ID = int(os.environ.get('ADMIN_ID', '0'))  # آیدی عددی مدیر
#WEBHOOK_URL = os.environ.get('WEBHOOK_URL', None)  # مثلاً https://your-app.onrender.com/telegram
API_TOKEN = "7476401114:AAGpXYSipVMpBZbH_hc4aRV2YfDCF_M1Qgg" #os.environ.get("BOT_TOKEN")
WEBHOOK_URL = "https://snapp-umz.onrender.com"#os.environ.get("WEBHOOK_URL")
WEBHOOK_PATH = f"/bot{API_TOKEN}"
# شهرها و لینک گروه هر شهر (لینک‌ها را بعداً جایگزین کن)
CITIES = os.environ.get('CITIES', 'کما,سرخرود,دانشگاه').split(',')
GROUP_LINKS = {
    # 'شهری که تو میدی': 'https://t.me/joinchat/XXXX'
}
# می‌تونی لینک‌ها رو در متغیر محیطی یا دستی در این دیکشنری قرار بدی.

# زمان‌های کلاس قابل انتخاب (مثالی، می‌تونی این لیست رو از ENV هم بگیری)
AVAILABLE_HOURS = os.environ.get('HOURS', '8,10,13,15,17,19').split(',')
AVAILABLE_HOURS = [h.strip() for h in AVAILABLE_HOURS if h.strip()]

# ظرفیت هر گروه
GROUP_CAPACITY = int(os.environ.get('GROUP_CAPACITY', '4'))

# زمان پاکسازی روزانه - به ساعت محلی سرور (مثال: 00:01)
CLEANUP_HOUR = int(os.environ.get('CLEANUP_HOUR', '0'))
CLEANUP_MINUTE = int(os.environ.get('CLEANUP_MINUTE', '1'))

# ----------------------------- APP & BOT -----------------------------
app = Flask(__name__)
bot = telebot.TeleBot(BOT_TOKEN, threaded=True)

# ----------------------------- IN-MEMORY STORAGE -----------------------------
# ساختار داده‌ها:
# pending[user_id] = {"step": ..., "city":..., "type": 'رفت'/'برگشت', "day":..., "hour":...}
pending = {}

# users[user_id] = {"name": 'علی', "username": 'ali123' or None}
users = {}

# rides[city][type]['شنبه'][hour] = [user_id,...]
rides = {}
for city in CITIES:
    rides[city] = {'رفت': {}, 'برگشت': {}}
    for t in ['رفت', 'برگشت']:
        for d in ['شنبه','یک‌شنبه','دوشنبه','سه‌شنبه','چهارشنبه']:
            rides[city][t][d] = {h: [] for h in AVAILABLE_HOURS}

# groups ساخته‌شده: list of dicts {"city", "type", "day", "hour", "members": [ids], "created_at": datetime}
groups = []

# ----------------------------- HELPERS -----------------------------

def make_inline_keyboard(rows):
    markup = InlineKeyboardMarkup()
    for row in rows:
        buttons = [InlineKeyboardButton(text=btn[0], callback_data=btn[1]) for btn in row]
        markup.row(*buttons)
    return markup


def localized_user_link(user_id):
    # اگر یوزرنیم موجود باشه از @username استفاده کن، در غیر اینصورت لینک tg://user?id=
    u = users.get(user_id, {})
    if u.get('username'):
        return '@' + u['username']
    else:
        return f'tg://user?id={user_id} ({u.get("name","ناشناس")})'


def find_group(city, typ, day, hour):
    for g in groups:
        if g['city'] == city and g['type'] == typ and g['day'] == day and g['hour'] == hour:
            return g
    return None

# وقتی گروه تکمیل شد، ساختار گروه ذخیره و نوتیف داده می‌شود

def finalize_group_if_full(city, typ, day, hour):
    member_ids = rides[city][typ][day][hour]
    if len(member_ids) >= GROUP_CAPACITY:
        members = member_ids[:GROUP_CAPACITY]
        # حذف اعضای اضافه (اگر کسی بیشتر ثبت کرده)
        rides[city][typ][day][hour] = member_ids[GROUP_CAPACITY:]
        g = {
            'city': city,
            'type': typ,
            'day': day,
            'hour': hour,
            'members': members,
            'created_at': datetime.utcnow()
        }
        groups.append(g)
        # نوتیف به اعضا بفرست
        group_link = GROUP_LINKS.get(city)
        member_texts = [localized_user_link(uid) for uid in members]
        list_text = '\n'.join([f'• {t}' for t in member_texts])
        for i, uid in enumerate(members):
            try:
                others = [localized_user_link(x) for j,x in enumerate(members) if j!=i]
                others_text = '\n'.join(others)
                msg = f'✅ گروه شما برای {typ} - {day} ساعت {hour} در شهر {city} تشکیل شد!\n\nاعضا:\n{list_text}\n\nسایر اعضا:\n{others_text}'
                if group_link:
                    msg += f"\n\nلینک گروه: {group_link}"
                bot.send_message(uid, msg)
            except Exception as e:
                print('notify error', e)
        return g
    return None

# ----------------------------- CALLBACK HANDLERS -----------------------------

@bot.callback_query_handler(func=lambda c: True)
def callback_query(call):
    try:
        data = call.data
        user_id = call.from_user.id
        # مسیر کدها: city:cityname  | type:رفت | day:شنبه | hour:8 | confirm:... | cancel
        if data.startswith('city:'):
            city = data.split(':',1)[1]
            pending[user_id] = {'step':'choose_type', 'city':city}
            rows = [[('🚗 رفت','type:رفت'),('🏠 برگشت','type:برگشت')]]
            bot.edit_message_text(f'شهر انتخاب شد: {city}\nحالا انتخاب کن: رفت یا برگشت؟', chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=make_inline_keyboard(rows))
            return
        if data.startswith('type:'):
            typ = data.split(':',1)[1]
            if user_id not in pending:
                bot.answer_callback_query(call.id, 'ابتدا شهر را انتخاب کن.')
                return
            pending[user_id].update({'step':'choose_day', 'type':typ})
            rows = [[(d, f'day:{d}') for d in ['شنبه','یک‌شنبه','دوشنبه']], [(d, f'day:{d}') for d in ['سه‌شنبه','چهارشنبه']]]
            bot.edit_message_text(f'حالا روز را انتخاب کن ({typ})', chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=make_inline_keyboard(rows))
            return
        if data.startswith('day:'):
            day = data.split(':',1)[1]
            if user_id not in pending:
                bot.answer_callback_query(call.id, 'خطا: ابتدا شهر و نوع را انتخاب کن.')
                return
            pending[user_id].update({'step':'choose_hour', 'day':day})
            # نمایش ساعت‌ها به همراه ظرفیت فعلی
            rows = []
            row = []
            city = pending[user_id]['city']
            typ = pending[user_id]['type']
            for h in AVAILABLE_HOURS:
                cur = len(rides[city][typ][day][h])
                text = f"{h} ({cur}/{GROUP_CAPACITY})"
                row.append((text, f'hour:{h}'))
                if len(row) >= 2:
                    rows.append(row)
                    row = []
            if row:
                rows.append(row)
            bot.edit_message_text(f'روز {day} انتخاب شد. ساعت را انتخاب کن:', chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=make_inline_keyboard(rows))
            return
        if data.startswith('hour:'):
            hour = data.split(':',1)[1]
            if user_id not in pending:
                bot.answer_callback_query(call.id, 'ابتدا شهر/نوع/روز را انتخاب کن.')
                return
            pending[user_id].update({'step':'confirm', 'hour':hour})
            city = pending[user_id]['city']
            typ = pending[user_id]['type']
            day = pending[user_id]['day']
            text = f' می‌خوای ثبت شی برای:\n{typ} - {day} ساعت {hour} در {city}\n\nآیا تأیید می‌کنی؟'
            rows = [[('✅ تأیید','confirm:yes'),('❌ لغو','confirm:no')]]
            bot.edit_message_text(text, chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=make_inline_keyboard(rows))
            return
        if data.startswith('confirm:'):
            ans = data.split(':',1)[1]
            if ans == 'no':
                pending.pop(user_id, None)
                bot.edit_message_text('✅ ثبت‌نام لغو شد.', chat_id=call.message.chat.id, message_id=call.message.message_id)
                return
            # confirm yes
            info = pending.get(user_id)
            if not info:
                bot.answer_callback_query(call.id, 'اطلاعات ناقص است.')
                return
            city = info['city']
            typ = info['type']
            day = info['day']
            hour = info['hour']
            # قبل از ثبت، اگر اسم کاربر را نداریم ازش بپرس
            if user_id not in users or not users[user_id].get('name'):
                bot.send_message(user_id, 'لطفاً اسم خودت رو وارد کن:')
                pending[user_id]['step'] = 'awaiting_name'
                bot.edit_message_text('لطفاً در پی‌وی اسم خود را ارسال کن تا ثبت کامل شود.', chat_id=call.message.chat.id, message_id=call.message.message_id)
                return
            # ثبت نهایی
            # جلوگیری از ثبت چندباره
            if user_id in rides[city][typ][day][hour] or any(user_id in g['members'] for g in groups):
                bot.send_message(user_id, 'شما قبلاً ثبت شده‌ای یا داخل گروهی هستی.')
                pending.pop(user_id, None)
                bot.edit_message_text('ثبت شما قبلا انجام شده یا لغو شد.', chat_id=call.message.chat.id, message_id=call.message.message_id)
                return
            rides[city][typ][day][hour].append(user_id)
            bot.edit_message_text('✅ ثبت شد! به زودی اگر گروه شکل گرفت نوتیف دریافت می‌کنی.', chat_id=call.message.chat.id, message_id=call.message.message_id)
            pending.pop(user_id, None)
            g = finalize_group_if_full(city, typ, day, hour)
            if g:
                print('group formed', g)
            return
        if data == 'cancel':
            pending.pop(user_id, None)
            bot.edit_message_text('عملیات کنسل شد.', chat_id=call.message.chat.id, message_id=call.message.message_id)
            return
    except Exception as e:
        print('callback error', e)

# ----------------------------- MESSAGE HANDLERS -----------------------------

@bot.message_handler(commands=['start'])
def cmd_start(m):
    user_id = m.from_user.id
    users.setdefault(user_id, {"name": m.from_user.first_name or '---', "username": m.from_user.username})
    # نمایش انتخاب شهر اولیه
    rows = []
    row = []
    for c in CITIES:
        row.append((c, f'city:{c}'))
        if len(row) >= 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    bot.send_message(user_id, 'سلام! لطفاً شهر را انتخاب کن:', reply_markup=make_inline_keyboard(rows))


@bot.message_handler(commands=['list','لیست'])
def cmd_list(m):
    # لیست وضعیت یک شهر/روز/نوع رو نشون میده؟ اینجا ساده لیست کلی رو می‌دیم
    text = 'وضعیت فعلی ثبت‌ها:\n'
    for city in CITIES:
        text += f'\n== {city} ==\n'
        for typ in ['رفت','برگشت']:
            text += f'\n-- {typ} --\n'
            for day in rides[city][typ]:
                text += f'{day}:\n'
                for hour, lst in rides[city][typ][day].items():
                    if lst:
                        names = ', '.join([users.get(uid, {}).get('name',str(uid)) for uid in lst])
                        text += f'  {hour}: {len(lst)}/{GROUP_CAPACITY} -> {names}\n'
    bot.send_message(m.chat.id, text)


@bot.message_handler(commands=['leave','لغو'])
def cmd_leave(m):
    user_id = m.from_user.id
    removed = False
    for city in CITIES:
        for typ in ['رفت','برگشت']:
            for day in rides[city][typ]:
                for hour, lst in rides[city][typ][day].items():
                    if user_id in lst:
                        lst.remove(user_id)
                        removed = True
    if removed:
        bot.reply_to(m, 'از همه صف‌ها حذف شدی.')
    else:
        bot.reply_to(m, 'شما جایی ثبت نشده بودی.')


@bot.message_handler(commands=['admin'])
def cmd_admin(m):
    if m.from_user.id != ADMIN_ID:
        bot.reply_to(m, 'فقط مدیر می‌تواند این دستور را اجرا کند.')
        return
    text = '📋 لیست گروه‌های تکمیل‌شده:\n'
    for i,g in enumerate(groups,1):
        mems = ', '.join([users.get(uid,{}).get('name',str(uid)) for uid in g['members']])
        text += f"{i}) {g['city']} - {g['type']} - {g['day']} {g['hour']} -> {mems}\n"
    bot.send_message(m.chat.id, text)


@bot.message_handler(func=lambda m: True)
def general_handler(m):
    user_id = m.from_user.id
    txt = m.text.strip()
    # اگر منتظر اسم کاربر باشیم
    p = pending.get(user_id)
    if p and p.get('step') == 'awaiting_name':
        name = txt
        users.setdefault(user_id, {})['name'] = name
        users[user_id]['username'] = m.from_user.username
        # حالا باید ثبت نهایی انجام شود: پیدا کنیم آخرین info (city,type,day,hour)
        # اگر اطلاعات کامل در pending بود، ثبت کن
        info = p
        if all(k in info for k in ('city','type','day','hour')):
            city = info['city']; typ = info['type']; day = info['day']; hour = info['hour']
            # جلوگیری از ثبت چندباره
            if user_id in rides[city][typ][day][hour] or any(user_id in g['members'] for g in groups):
                bot.send_message(user_id, 'شما قبلاً ثبت شده‌ای یا در یک گروه هستی.')
                pending.pop(user_id,None)
                return
            rides[city][typ][day][hour].append(user_id)
            bot.send_message(user_id, '✅ ثبت شد! به زودی اگر گروه شکل گرفت نوتیف دریافت می‌کنی.')
            pending.pop(user_id,None)
            finalize_group_if_full(city, typ, day, hour)
            return
        else:
            bot.send_message(user_id, 'اطلاعات ثبت ناقص بود، لطفاً دوباره شروع کن (/start).')
            pending.pop(user_id,None)
            return
    # گرفتن اسم کاربر از پیام ساده (اگر لازم باشه)
    bot.send_message(user_id, 'برای شروع /start را بزن.')

# ----------------------------- DAILY CLEANUP -----------------------------

def daily_cleanup():
    while True:
        now = datetime.now()
        target = now.replace(hour=CLEANUP_HOUR, minute=CLEANUP_MINUTE, second=0, microsecond=0)
        if target <= now:
            target = target + timedelta(days=1)
        wait_seconds = (target - now).total_seconds()
        time.sleep(wait_seconds)
        try:
            # پاکسازی: حذف همه rides و گروه‌هایی که تاریخ گذشته (در این نسخه ساده همه گروه‌ها پاک می‌شود هر شب)
            for city in CITIES:
                for typ in ['رفت','برگشت']:
                    for day in rides[city][typ]:
                        for h in rides[city][typ][day]:
                            rides[city][typ][day][h] = []
            groups.clear()
            print('Daily cleanup executed at', datetime.utcnow())
        except Exception as e:
            print('cleanup error', e)

# اجرای thread پاکسازی
cleanup_thread = threading.Thread(target=daily_cleanup, daemon=True)
cleanup_thread.start()

# ----------------------------- FLASK ENDPOINTS (for webhook) -----------------------------
@app.route(WEBHOOK_PATH, methods=["POST"])
def webhook():
    if request.headers.get("content-type") == "application/json":
        update = telebot.types.Update.de_json(request.data.decode("utf-8"))
        bot.process_new_updates([update])
        return "", 200
    return "Forbidden", 403

@app.route("/", methods=["GET"])
def index():
    return "ربات فعال.", 200



if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    bot.remove_webhook()
    bot.set_webhook(url=WEBHOOK_URL + WEBHOOK_PATH )
    app.run(host="0.0.0.0", port=port)
