# telegram_snap_bot.py
# نسخه کامل ارتقایافته با منوی اصلی، بازگشت، نام و شماره تلفن، تشکیل خودکار گروه ناقص
# اجرا با Flask + Telebot (Webhook در Render)

import os
import threading
import time
from datetime import datetime, timedelta
from flask import Flask, request
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# ----------------------------- CONFIG -----------------------------
BOT_TOKEN = os.environ.get('BOT_TOKEN', '7476401114:AAGpXYSipVMpBZbH_hc4aRV2YfDCF_M1Qgg')
API_TOKEN = BOT_TOKEN
WEBHOOK_URL = "https://snapp-umz.onrender.com"
WEBHOOK_PATH = f"/bot{API_TOKEN}"

CITIES = os.environ.get('CITIES', 'چالوس و نوشهر,آمل,بهشهر و نکا و گلوگاه,نور و ایزدشهر,رویان و چمستان,فریدونکنار,جویبار,قایمشهر,محمودآباد,ساری,بابل').split(',')

AVAILABLE_HOURS = [h.strip() for h in os.environ.get('HOURS', '8,10,13,15,17,18,19').split(',') if h.strip()]
GROUP_CAPACITY = int(os.environ.get('GROUP_CAPACITY', '4'))

# ساعت بررسی خودکار گروه ناقص
AUTO_GROUP_HOUR = 0
AUTO_GROUP_MINUTE = 0

# ----------------------------- APP & BOT -----------------------------
app = Flask(__name__)
bot = telebot.TeleBot(BOT_TOKEN, threaded=True)

# ----------------------------- MEMORY STORAGE -----------------------------
pending = {}  # مراحل کاربر
users = {}    # اطلاعات کاربر
rides = {}
groups = []

for city in CITIES:
    rides[city] = {'رفت': {}, 'برگشت': {}}
    for t in ['رفت', 'برگشت']:
        for d in ['شنبه', 'یک‌شنبه', 'دوشنبه', 'سه‌شنبه', 'چهارشنبه']:
            rides[city][t][d] = {h: [] for h in AVAILABLE_HOURS}

# ----------------------------- HELPERS -----------------------------
def make_inline(rows):
    markup = InlineKeyboardMarkup()
    for row in rows:
        markup.row(*[InlineKeyboardButton(text=b[0], callback_data=b[1]) for b in row])
    return markup

def user_link(uid):
    u = users.get(uid, {})
    if u.get('username'):
        return '@' + u['username']
    else:
        return f"[{u.get('name','کاربر')}]({f'tg://user?id={uid}'})"

def finalize_group(city, typ, day, hour):
    ids = rides[city][typ][day][hour]
    if len(ids) >= GROUP_CAPACITY:
        members = ids[:GROUP_CAPACITY]
        rides[city][typ][day][hour] = ids[GROUP_CAPACITY:]
        g = {'city': city, 'type': typ, 'day': day, 'hour': hour, 'members': members}
        groups.append(g)
        notify_group(g)
        return g
    return None

def notify_group(g):
    member_texts = "\n".join([f"• {user_link(uid)}" for uid in g['members']])
    for uid in g['members']:
        bot.send_message(uid, f"✅ گروه شما تشکیل شد!\n"
                              f"🏙 شهر: {g['city']}\n"
                              f"🚗 {g['type']} - {g['day']} ساعت {g['hour']}\n\n"
                              f"اعضا:\n{member_texts}", parse_mode="Markdown")

def check_incomplete_groups():
    while True:
        now = datetime.now() + timedelta(hours=3.5)  # به وقت تهران
        if now.hour == AUTO_GROUP_HOUR and now.minute == AUTO_GROUP_MINUTE:
            for city in CITIES:
                for typ in ['رفت', 'برگشت']:
                    for day in rides[city][typ]:
                        for h, ids in rides[city][typ][day].items():
                            if 2 <= len(ids) < GROUP_CAPACITY:
                                g = {'city': city, 'type': typ, 'day': day, 'hour': h, 'members': ids[:]}
                                groups.append(g)
                                rides[city][typ][day][h] = []
                                notify_group(g)
            print("✅ Auto grouping executed at midnight Tehran.")
            time.sleep(70)  # جلوگیری از اجرای دوباره در همان دقیقه
        time.sleep(30)

threading.Thread(target=check_incomplete_groups, daemon=True).start()

# ----------------------------- CALLBACKS -----------------------------
@bot.callback_query_handler(func=lambda c: True)
def cb(call):
    uid = call.from_user.id
    data = call.data

    if data == "back_main":
        show_main_menu(uid)
        return

    if data.startswith("city:"):
        city = data.split(':',1)[1]
        pending[uid] = {'step': 'type', 'city': city}
        kb = make_inline([[('🚗 رفت','type:رفت'),('🏠 برگشت','type:برگشت')],[('🔙 بازگشت','back_main')]])
        bot.edit_message_text(f"شهر انتخاب شد: {city}\nحالا نوع مسیر را انتخاب کن:", chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=kb)
        return

    if data.startswith("type:"):
        typ = data.split(':',1)[1]
        pending[uid].update({'type': typ, 'step': 'day'})
        days = [['شنبه','یک‌شنبه'], ['دوشنبه','سه‌شنبه'], ['چهارشنبه']]
        kb = make_inline([[ (d, f'day:{d}') for d in row] for row in days] + [[('🔙 بازگشت','back_main')]])
        bot.edit_message_text(f"مسیر {typ} انتخاب شد.\nحالا روز را انتخاب کن:", chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=kb)
        return

    if data.startswith("day:"):
        day = data.split(':',1)[1]
        city, typ = pending[uid]['city'], pending[uid]['type']
        pending[uid].update({'day': day, 'step': 'hour'})
        rows = []
        row = []
        for h in AVAILABLE_HOURS:
            count = len(rides[city][typ][day][h])
            row.append((f"{h} ({count}/{GROUP_CAPACITY})", f"hour:{h}"))
            if len(row) == 2:
                rows.append(row)
                row = []
        if row:
            rows.append(row)
        rows.append([('🔙 بازگشت','back_main')])
        bot.edit_message_text(f"روز {day} انتخاب شد، حالا ساعت را انتخاب کن:", chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=make_inline(rows))
        return

    if data.startswith("hour:"):
        hour = data.split(':',1)[1]
        pending[uid].update({'hour': hour, 'step': 'confirm'})
        info = pending[uid]
        text = f"📅 شهر: {info['city']}\n🚗 {info['type']} - {info['day']} ساعت {hour}\n\nآیا تأیید می‌کنی؟"
        kb = make_inline([[('✅ بله','confirm_yes'),('❌ خیر','back_main')]])
        bot.edit_message_text(text, chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=kb)
        return

    if data == "confirm_yes":
        info = pending.get(uid)
        if not info:
            bot.answer_callback_query(call.id, "اطلاعات ناقص است.")
            return
        if not users.get(uid, {}).get("name"):
            bot.send_message(uid, "📝 لطفاً نام و نام خانوادگی خود را بنویس:")
            pending[uid]['step'] = 'await_name'
            return
        if not users.get(uid, {}).get("phone"):
            bot.send_message(uid, "📞 لطفاً شماره تلفن خود را به‌صورت عددی بنویس (مثلاً 09123456789):")
            pending[uid]['step'] = 'await_phone'
            return

        register_user(uid)
        bot.edit_message_text("✅ ثبت‌نام انجام شد! منتظر تشکیل گروه بمانید.", chat_id=call.message.chat.id, message_id=call.message.message_id)
        pending.pop(uid, None)

# ----------------------------- REGISTER & MENU -----------------------------
def register_user(uid):
    info = pending[uid]
    city, typ, day, hour = info['city'], info['type'], info['day'], info['hour']
    if uid not in rides[city][typ][day][hour]:
        rides[city][typ][day][hour].append(uid)
        finalize_group(city, typ, day, hour)

@bot.message_handler(commands=['start'])
def start(m):
    uid = m.from_user.id
    users.setdefault(uid, {"username": m.from_user.username})
    show_main_menu(uid)

def show_main_menu(uid):
    kb = make_inline([
        [('🚀 شروع هماهنگی','start_city')],
        [('📋 لیست وضعیت','show_list')],
        [('❌ لغو ثبت‌نام','cancel_all')]
    ])
    bot.send_message(uid, "به ربات هماهنگی خوش آمدی 🌟\nیک گزینه انتخاب کن:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data in ["start_city","show_list","cancel_all"])
def menu_cb(call):
    uid = call.from_user.id
    if call.data == "start_city":
        rows = []
        row = []
        for c in CITIES:
            row.append((c, f'city:{c}'))
            if len(row) == 2:
                rows.append(row)
                row = []
        if row:
            rows.append(row)
        rows.append([('🔙 بازگشت','back_main')])
        bot.edit_message_text("🏙 لطفاً شهر را انتخاب کن:", chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=make_inline(rows))
    elif call.data == "show_list":
        text = "📋 وضعیت فعلی:\n"
        for city in CITIES:
            text += f"\n🏙 {city}\n"
            for typ in ['رفت','برگشت']:
                text += f"  {typ}:\n"
                for day in rides[city][typ]:
                    for h, lst in rides[city][typ][day].items():
                        if lst:
                            text += f"   • {day} {h}: {len(lst)}/{GROUP_CAPACITY}\n"
        bot.send_message(uid, text or "هنوز کسی ثبت‌نام نکرده.")
    elif call.data == "cancel_all":
        for city in CITIES:
            for typ in ['رفت','برگشت']:
                for day in rides[city][typ]:
                    for h in rides[city][typ][day]:
                        if uid in rides[city][typ][day][h]:
                            rides[city][typ][day][h].remove(uid)
        bot.send_message(uid, "❌ از همه صف‌ها حذف شدی.")

# ----------------------------- MESSAGE HANDLER -----------------------------
@bot.message_handler(func=lambda m: True)
def handle(m):
    uid = m.from_user.id
    txt = m.text.strip()
    if uid in pending:
        step = pending[uid].get('step')
        if step == 'await_name':
            users.setdefault(uid, {})['name'] = txt
            if not users[uid].get('phone'):
                bot.send_message(uid, "📞 حالا شماره تلفن خود را بنویس (مثلاً 09123456789):")
                pending[uid]['step'] = 'await_phone'
                return
        elif step == 'await_phone':
            if not txt.isdigit():
                bot.send_message(uid, "⚠️ شماره باید فقط شامل عدد باشد. دوباره وارد کن:")
                return
            users[uid]['phone'] = txt
            register_user(uid)
            bot.send_message(uid, "✅ ثبت‌نام تکمیل شد! منتظر تشکیل گروه بمان.")
            pending.pop(uid, None)
            return
    else:
        show_main_menu(uid)

# ----------------------------- WEBHOOK -----------------------------
@app.route(WEBHOOK_PATH, methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        update = telebot.types.Update.de_json(request.data.decode('utf-8'))
        bot.process_new_updates([update])
        return '', 200
    return 'Forbidden', 403

@app.route('/', methods=['GET'])
def index():
    return 'ربات فعال است ✅', 200

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    bot.remove_webhook()
    bot.set_webhook(url=WEBHOOK_URL + WEBHOOK_PATH)
    app.run(host='0.0.0.0', port=port)
