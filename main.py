# telegram_snap_bot_full.py
# نسخه کامل با کیبورد، شماره تلفن، نام، هشدار یوزرنیم و گروه نیمه‌کامل ساعت 12 شب

import os
import threading
import time
from datetime import datetime, timedelta
from flask import Flask, request
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton

# ----------------------------- CONFIG -----------------------------
BOT_TOKEN = os.environ.get('BOT_TOKEN', '7476401114:AAGpXYSipVMpBZbH_hc4aRV2YfDCF_M1Qgg')
ADMIN_ID = int(os.environ.get('ADMIN_ID', '0'))
API_TOKEN = BOT_TOKEN
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "https://snapp-umz.onrender.com")
WEBHOOK_PATH = f"/bot{API_TOKEN}"

CITIES = os.environ.get('CITIES', 'چالوس و نوشهر,آمل,بهشهر و نکا و گلوگاه ,نور و ایزدشهر,رویان و چمستان ,فریدونکنار,جویبار,قایمشهر ,محمودآباد ,ساری , بابل').split(',')
GROUP_LINKS = {}  # لینک گروه‌ها

AVAILABLE_HOURS = os.environ.get('HOURS', '8,10,13,15,17,18,19').split(',')
AVAILABLE_HOURS = [h.strip() for h in AVAILABLE_HOURS if h.strip()]

GROUP_CAPACITY = int(os.environ.get('GROUP_CAPACITY', '4'))
CLEANUP_HOUR = int(os.environ.get('CLEANUP_HOUR', '0'))
CLEANUP_MINUTE = int(os.environ.get('CLEANUP_MINUTE', '1'))
NIGHT_HOUR = 0  # ساعت 12 شب برای تشکیل گروه نیمه‌کامل

app = Flask(__name__)
bot = telebot.TeleBot(BOT_TOKEN, threaded=True)

# ----------------------------- STORAGE -----------------------------
pending = {}  # pending[user_id] = {step, city, type, day, hour}
users = {}    # users[user_id] = {name, username, phone}
rides = {}    # rides[city][type][day][hour] = [user_id,...]
groups = []   # groups = [{"city","type","day","hour","members","created_at"}]

for city in CITIES:
    rides[city] = {'رفت': {}, 'برگشت': {}}
    for t in ['رفت','برگشت']:
        for d in ['شنبه','دوشنبه','سه شنبه','یک‌شنبه','چهارشنبه']:
            rides[city][t][d] = {h: [] for h in AVAILABLE_HOURS}

# ----------------------------- HELPERS -----------------------------
def make_inline_keyboard(rows):
    markup = InlineKeyboardMarkup()
    for row in rows:
        buttons = [InlineKeyboardButton(text=btn[0], callback_data=btn[1]) for btn in row]
        markup.row(*buttons)
    return markup

def make_reply_keyboard(rows, resize=True, one_time=False):
    markup = ReplyKeyboardMarkup(resize_keyboard=resize, one_time_keyboard=one_time)
    for row in rows:
        buttons = [KeyboardButton(text=b) for b in row]
        markup.row(*buttons)
    return markup

def localized_user_link(user_id):
    u = users.get(user_id, {})
    if u.get('username'):
        return '@' + u['username']
    else:
        return f'tg://user?id={user_id} ({u.get("name","ناشناس")})'

def find_group(city, typ, day, hour):
    for g in groups:
        if g['city']==city and g['type']==typ and g['day']==day and g['hour']==hour:
            return g
    return None

def finalize_group(city, typ, day, hour):
    member_ids = rides[city][typ][day][hour]
    if member_ids:
        members = member_ids[:GROUP_CAPACITY]
        rides[city][typ][day][hour] = member_ids[GROUP_CAPACITY:]
        g = {'city':city,'type':typ,'day':day,'hour':hour,'members':members,'created_at':datetime.utcnow()}
        groups.append(g)
        group_link = GROUP_LINKS.get(city)
        member_texts = [localized_user_link(uid) for uid in members]
        list_text = '\n'.join([f'• {t}' for t in member_texts])
        for i, uid in enumerate(members):
            try:
                others = [localized_user_link(x) for j,x in enumerate(members) if j!=i]
                others_text = '\n'.join(others)
                msg = f'✅ گروه شما برای {typ} - {day} ساعت {hour} در {city} تشکیل شد!\n\nاعضا:\n{list_text}\n\nسایر اعضا:\n{others_text}'
                if group_link:
                    msg += f"\n\nلینک گروه: {group_link}"
                bot.send_message(uid, msg)
            except Exception as e:
                print('notify error', e)
        return g
    return None

def nightly_finalize():
    now = datetime.now()
    for city in CITIES:
        for typ in ['رفت','برگشت']:
            for day in ['شنبه','یک‌شنبه','دوشنبه','سه شنبه','چهارشنبه']:
                for hour in AVAILABLE_HOURS:
                    if 0 < len(rides[city][typ][day][hour]) < GROUP_CAPACITY:
                        finalize_group(city, typ, day, hour)

# ----------------------------- CALLBACK -----------------------------
@bot.callback_query_handler(func=lambda c: True)
def callback_query(call):
    try:
        data = call.data
        user_id = call.from_user.id
        if data.startswith('city:'):
            city = data.split(':',1)[1]
            pending[user_id] = {'step':'choose_type','city':city}
            rows = [[('🚗 رفت','type:رفت'),('🏠 برگشت','type:برگشت')]]
            bot.edit_message_text(f'شهر انتخاب شد: {city}\nنوع را انتخاب کن:', chat_id=call.message.chat.id,message_id=call.message.message_id, reply_markup=make_inline_keyboard(rows))
            return
        if data.startswith('type:'):
            typ = data.split(':',1)[1]
            if user_id not in pending: return
            pending[user_id].update({'step':'choose_day','type':typ})
            rows = [[(d,f'day:{d}') for d in ['شنبه','یک‌شنبه','دوشنبه']],[(d,f'day:{d}') for d in ['سه‌شنبه','چهارشنبه']]]
            bot.edit_message_text(f'روز را انتخاب کن ({typ}):', chat_id=call.message.chat.id,message_id=call.message.message_id,reply_markup=make_inline_keyboard(rows))
            return
        if data.startswith('day:'):
            day = data.split(':',1)[1]
            if user_id not in pending: return
            pending[user_id].update({'step':'choose_hour','day':day})
            city = pending[user_id]['city']; typ = pending[user_id]['type']
            rows=[]; row=[]
            for h in AVAILABLE_HOURS:
                cur=len(rides[city][typ][day][h])
                text=f"{h} ({cur}/{GROUP_CAPACITY})"
                row.append((text,f'hour:{h}'))
                if len(row)>=2: rows.append(row); row=[]
            if row: rows.append(row)
            bot.edit_message_text(f'روز {day} انتخاب شد. ساعت را انتخاب کن:',chat_id=call.message.chat.id,message_id=call.message.message_id,reply_markup=make_inline_keyboard(rows))
            return
        if data.startswith('hour:'):
            hour=data.split(':',1)[1]
            if user_id not in pending: return
            pending[user_id].update({'step':'confirm','hour':hour})
            info=pending[user_id]; city=info['city']; typ=info['type']; day=info['day']
            text=f'می‌خوای ثبت شی برای:\n{typ} - {day} ساعت {hour} در {city}\n\nآیا تأیید می‌کنی؟'
            rows=[[('✅ تأیید','confirm:yes'),('❌ لغو','confirm:no')]]
            bot.edit_message_text(text,chat_id=call.message.chat.id,message_id=call.message.message_id,reply_markup=make_inline_keyboard(rows))
            return
        if data.startswith('confirm:'):
            ans = data.split(':',1)[1]
            if ans=='no': pending.pop(user_id,None); bot.edit_message_text('✅ ثبت‌نام لغو شد.',chat_id=call.message.chat.id,message_id=call.message.message_id); return
            info = pending.get(user_id)
            if not info: return
            city=info['city']; typ=info['type']; day=info['day']; hour=info['hour']
            if user_id not in users or not users[user_id].get('name') or not users[user_id].get('phone'):
                bot.send_message(user_id,'لطفاً ابتدا نام و شماره خود را ارسال کن:')
                pending[user_id]['step']='awaiting_info'
                return
            if user_id in rides[city][typ][day][hour] or any(user_id in g['members'] for g in groups):
                bot.send_message(user_id,'شما قبلاً ثبت شده‌ای یا در گروهی هستی.')
                pending.pop(user_id,None); return
            rides[city][typ][day][hour].append(user_id)
            bot.send_message(user_id,'✅ ثبت شد! به زودی اگر گروه کامل شد نوتیف دریافت می‌کنی.')
            pending.pop(user_id,None)
            finalize_group(city,typ,day,hour)
            return
        if data=='cancel': pending.pop(user_id,None); bot.edit_message_text('عملیات کنسل شد.',chat_id=call.message.chat.id,message_id=call.message.message_id); return
    except Exception as e: print('callback error', e)

# ----------------------------- MESSAGE HANDLERS -----------------------------
@bot.message_handler(commands=['start'])
def cmd_start(m):
    user_id=m.from_user.id
    users.setdefault(user_id,{"name":m.from_user.first_name or '---',"username":m.from_user.username})
    # کیبورد اصلی
    keyboard = make_reply_keyboard([['استارت','لیست'],['لغو']])
    bot.send_message(user_id,'سلام! لطفاً شهر را انتخاب کن:',reply_markup=keyboard)
    rows=[]; row=[]
    for c in CITIES:
        row.append((c,f'city:{c}'))
        if len(row)>=2: rows.append(row); row=[]
    if row: rows.append(row)
    bot.send_message(user_id,'شهر را انتخاب کن:',reply_markup=make_inline_keyboard(rows))

@bot.message_handler(func=lambda m: True)
def general_handler(m):
    user_id = m.from_user.id
    txt = m.text.strip()
    p = pending.get(user_id)
    if p and p.get('step')=='awaiting_info':
        if txt.isdigit(): users.setdefault(user_id,{})['phone']=txt
        else: users.setdefault(user_id,{})['name']=txt
        bot.send_message(user_id,'✅ اطلاعات ذخیره شد. دوباره /start را بزن تا ثبت کامل شود.')
        pending.pop(user_id,None)
        return
    bot.send_message(user_id,'برای شروع /start را بزن.')

# ----------------------------- NIGHTLY THREAD -----------------------------
def nightly_thread():
    while True:
        now = datetime.now()
        target = now.replace(hour=NIGHT_HOUR,minute=0,second=0,microsecond=0)
        if target<=now: target+=timedelta(days=1)
        wait=(target-now).total_seconds()
        time.sleep(wait)
        try:
            nightly_finalize()
            print('Nightly finalize executed',datetime.utcnow())
        except Exception as e:
            print('Nightly error',e)

threading.Thread(target=nightly_thread,daemon=True).start()

# ----------------------------- FLASK -----------------------------
@app.route(WEBHOOK_PATH,methods=["POST"])
def webhook():
    if request.headers.get("content-type")=="application/json":
        update=telebot.types.Update.de_json(request.data.decode("utf-8"))
        bot.process_new_updates([update])
        return "",200
    return "Forbidden",403

@app.route("/",methods=["GET"])
def index(): return "ربات فعال",200

if __name__=="__main__":
    port=int(os.environ.get("PORT",5000))
    bot.remove_webhook()
    bot.set_webhook(url=WEBHOOK_URL+WEBHOOK_PATH)
    app.run(host="0.0.0.0",port=port)
