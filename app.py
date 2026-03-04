"""
TON Rolls - Telegram Stars Bot
================================
O'rnatish:
  pip install python-telegram-bot aiohttp

Ishga tushirish:
  python bot.py

Kerak bo'lgan narsalar:
  1. @BotFather dan bot token oling
  2. BOT_TOKEN ni quyida to'ldiring
  3. ADMIN_ID = sizning Telegram ID ingiz
  4. MINI_APP_URL = index.html joylashgan link
"""

import asyncio, json, logging, random, time
from aiohttp import web
from telegram import (Update, InlineKeyboardButton, InlineKeyboardMarkup,
                      LabeledPrice, WebAppInfo)
from telegram.ext import (Application, CommandHandler, MessageHandler,
                          PreCheckoutQueryHandler, CallbackQueryHandler,
                          ContextTypes, filters)

# ══════════════════════════════════════════════════════
# ⚙️  SOZLAMALAR
# ══════════════════════════════════════════════════════
BOT_TOKEN    = "8429885576:AAG3DAvRNl2RKtDDZoghij70ixm3CnJoTUY"      # @BotFather dan
MINI_APP_URL = ""    # index.html URL
ADMIN_ID     = 5201473096                  # Sizning Telegram ID
HOUSE_FEE    = 0.15
COUNTDOWN    = 15
COLORS       = ["#7c3aed","#3b82f6","#10b981","#f59e0b",
                "#ef4444","#ec4899","#06b6d4","#a855f7"]
STAR_PACKAGES = [
    {"stars": 25,  "label": "Starter", "emoji": "🌟"},
    {"stars": 50,  "label": "Player",  "emoji": "⭐"},
    {"stars": 100, "label": "Pro",     "emoji": "💫"},
    {"stars": 250, "label": "Whale",   "emoji": "🌠"},
    {"stars": 500, "label": "Legend",  "emoji": "✨"},
]

# ══════════════════════════════════════════════════════
# 💾  MA'LUMOTLAR
# ══════════════════════════════════════════════════════
users: dict = {}
websockets: dict = {}
last_games: list = []
game_room = {
    "state": "WAITING", "players": {}, "pot": 0,
    "countdown_end": 0, "winner": None, "game_id": 1,
}

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


def get_user(uid: int, name="Player") -> dict:
    if uid not in users:
        users[uid] = {"stars": 0, "games": 0, "wins": 0,
                      "name": name, "total_won": 0}
    return users[uid]

def room_state() -> dict:
    return {
        "game_id": game_room["game_id"],
        "state": game_room["state"],
        "players": list(game_room["players"].values()),
        "countdown_end": game_room["countdown_end"],
        "winner": game_room["winner"],
        "pot": game_room["pot"],
        "player_count": len(game_room["players"]),
    }

async def broadcast(data: dict):
    msg = json.dumps(data)
    for uid, ws in list(websockets.items()):
        try:
            await ws.send_str(msg)
        except:
            websockets.pop(uid, None)

async def send_to(uid, data: dict):
    ws = websockets.get(str(uid))
    if ws:
        try:
            await ws.send_str(json.dumps(data))
        except:
            websockets.pop(str(uid), None)

async def reset_room():
    game_room.update({"state": "WAITING", "players": {}, "pot": 0,
                      "countdown_end": 0, "winner": None,
                      "game_id": game_room["game_id"] + 1})
    await broadcast({"type": "new_room", "room": room_state()})

async def start_countdown():
    game_room["state"] = "COUNTDOWN"
    game_room["countdown_end"] = int(time.time()) + COUNTDOWN
    await broadcast({"type": "room_update", "room": room_state()})
    for i in range(COUNTDOWN, 0, -1):
        await asyncio.sleep(1)
        if game_room["state"] != "COUNTDOWN":
            return
        await broadcast({"type": "countdown", "seconds": i - 1,
                         "room": room_state()})
    if game_room["state"] == "COUNTDOWN":
        await resolve_game()

async def resolve_game():
    game_room["state"] = "SPINNING"
    await broadcast({"type": "room_update", "room": room_state()})
    await asyncio.sleep(4)

    players = game_room["players"]
    if not players:
        await reset_room()
        return

    # Weighted random — ko'proq stars = ko'proq shans
    pool = []
    for uid, p in players.items():
        pool.extend([uid] * max(1, p["stars_bet"]))

    winner_id  = random.choice(pool)
    winner_p   = players[winner_id]
    total_pot  = game_room["pot"]
    winner_bet = winner_p["stars_bet"]
    profit     = total_pot - winner_bet
    fee        = int(profit * HOUSE_FEE) if profit > 0 else 0
    payout     = total_pot - fee

    # G'olibga stars ber
    uid_int = int(winner_id)
    if uid_int in users:
        users[uid_int]["stars"]     += payout
        users[uid_int]["wins"]      += 1
        users[uid_int]["total_won"] += payout

    game_room["winner"] = {**winner_p, "user_id": winner_id,
                           "payout": payout, "fee": fee}
    game_room["state"] = "RESULT"

    last_games.insert(0, {
        "game_id": game_room["game_id"], "winner": winner_p["name"],
        "pot": total_pot, "payout": payout,
        "players": len(players), "time": int(time.time()),
    })
    if len(last_games) > 10:
        last_games.pop()

    await broadcast({"type": "result", "room": room_state(),
                     "winner_id": winner_id})

    for uid in players:
        uid_i = int(uid)
        if uid_i in users:
            users[uid_i]["games"] += 1
        await send_to(uid, {"type": "balance",
                            "stars": users.get(uid_i, {}).get("stars", 0)})

    await asyncio.sleep(5)
    await reset_room()


# ══════════════════════════════════════════════════════
# 🌐  WEBSOCKET
# ══════════════════════════════════════════════════════
async def ws_handler(request):
    uid = request.match_info.get("uid", "0")
    ws  = web.WebSocketResponse()
    await ws.prepare(request)
    websockets[uid] = ws
    uid_int = int(uid) if uid.isdigit() else 0
    u = get_user(uid_int)

    await ws.send_str(json.dumps({
        "type": "init", "user_id": uid, "stars": u["stars"],
        "room": room_state(), "last_games": last_games[:5],
    }))

    async for msg in ws:
        if msg.type == web.WSMsgType.TEXT:
            try:
                data  = json.loads(msg.data)
                mtype = data.get("type")

                if mtype == "join_game":
                    bet = int(data.get("bet", 25))
                    if bet < 25:
                        await ws.send_str(json.dumps(
                            {"type":"error","msg":"Minimal 25 ⭐!"})); continue
                    if u["stars"] < bet:
                        await ws.send_str(json.dumps(
                            {"type":"error","msg":"Stars yetarli emas! /buy"})); continue
                    if game_room["state"] in ("SPINNING","RESULT"):
                        await ws.send_str(json.dumps(
                            {"type":"error","msg":"O'yin tugashini kuting!"})); continue

                    u["stars"] -= bet
                    game_room["pot"] += bet
                    if uid in game_room["players"]:
                        game_room["players"][uid]["stars_bet"] += bet
                    else:
                        idx = len(game_room["players"])
                        game_room["players"][uid] = {
                            "user_id":   uid,
                            "name":      data.get("name", u["name"]),
                            "avatar":    data.get("avatar", "🎮"),
                            "stars_bet": bet,
                            "color":     COLORS[idx % len(COLORS)],
                        }

                    if (game_room["state"] == "WAITING"
                            and len(game_room["players"]) >= 2):
                        asyncio.create_task(start_countdown())

                    await broadcast({"type":"room_update","room":room_state()})
                    await ws.send_str(json.dumps(
                        {"type":"balance","stars":u["stars"]}))

                elif mtype == "get_state":
                    await ws.send_str(json.dumps({
                        "type": "room_update", "room": room_state(),
                        "last_games": last_games[:5],
                    }))
            except Exception as e:
                log.error(f"WS err: {e}")

    websockets.pop(uid, None)
    return ws


# ══════════════════════════════════════════════════════
# 🤖  BOT HANDLERS
# ══════════════════════════════════════════════════════
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    name = update.effective_user.first_name or "Player"
    u    = get_user(uid, name)
    kb   = InlineKeyboardMarkup([[
        InlineKeyboardButton("🎮 O'ynash",
                             web_app=WebAppInfo(url=MINI_APP_URL))
    ],[
        InlineKeyboardButton("⭐ Stars sotib olish",
                             callback_data="buy_stars")
    ]])
    await update.message.reply_text(
        f"🎡 *TON Rolls* ga xush kelibsiz, {name}!\n\n"
        f"⭐ Balans: *{u['stars']} Stars*\n\n"
        f"📋 Qoidalar:\n"
        f"• Minimal stavka: *25 ⭐*\n"
        f"• 2+ o'yinchi → 15 soniya countdown\n"
        f"• G'olib *hamma stars*ni oladi\n"
        f"• Faqat *yutuqdan 15%* komissiya oladi\n"
        f"• Stavkangizdan hech narsa olinmaydi!\n\n"
        f"🎲 Bosing va o'ynang!",
        parse_mode="Markdown", reply_markup=kb)

async def cmd_balance(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    u   = get_user(uid, update.effective_user.first_name or "Player")
    await update.message.reply_text(
        f"💎 *Balansingiz*\n\n"
        f"⭐ Stars: *{u['stars']}*\n"
        f"🎮 O'yinlar: *{u['games']}*\n"
        f"🏆 G'alabalar: *{u['wins']}*\n"
        f"💰 Jami yutuq: *{u['total_won']} ⭐*",
        parse_mode="Markdown")

async def cmd_buy(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    rows = [[InlineKeyboardButton(
        f"{p['emoji']} {p['stars']} Stars — {p['label']}",
        callback_data=f"buy_{p['stars']}")] for p in STAR_PACKAGES]
    await update.message.reply_text(
        "⭐ *Stars sotib oling:*\nMinimal stavka: 25 Stars",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(rows))

async def callback_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "buy_stars":
        await cmd_buy(update, ctx)
        return
    if q.data.startswith("buy_"):
        amount = int(q.data.split("_")[1])
        pkg    = next((p for p in STAR_PACKAGES if p["stars"] == amount), None)
        if not pkg: return
        await ctx.bot.send_invoice(
            chat_id=q.from_user.id,
            title=f"{pkg['emoji']} {pkg['stars']} Stars — {pkg['label']}",
            description=f"Rolls o'yini uchun {pkg['stars']} Stars. Min stavka 25 ⭐.",
            payload=f"stars_{amount}_{q.from_user.id}",
            currency="XTR",
            prices=[LabeledPrice(f"{amount} Stars", amount)],
        )

async def pre_checkout(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.pre_checkout_query.answer(ok=True)

async def payment_done(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    payment = update.message.successful_payment
    uid     = update.effective_user.id
    name    = update.effective_user.first_name or "Player"
    try:
        amount = int(payment.invoice_payload.split("_")[1])
    except:
        amount = payment.total_amount

    new_bal = get_user(uid, name)["stars"] + amount
    users[uid]["stars"] = new_bal

    await send_to(str(uid), {"type": "balance", "stars": new_bal})
    await update.message.reply_text(
        f"✅ *To'lov qabul qilindi!*\n\n"
        f"⭐ +{amount} Stars qo'shildi\n"
        f"💎 Balans: *{new_bal} Stars*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🎮 O'ynash",
                                 web_app=WebAppInfo(url=MINI_APP_URL))
        ]]))

async def cmd_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    await update.message.reply_text(
        f"👑 *Admin*\n\n"
        f"👥 Foydalanuvchilar: {len(users)}\n"
        f"⭐ Jami stars: {sum(u['stars'] for u in users.values())}\n"
        f"🎮 O'yin #{game_room['game_id']}\n"
        f"👤 O'yinchilar: {len(game_room['players'])}\n"
        f"💰 Pot: {game_room['pot']} ⭐",
        parse_mode="Markdown")


# ══════════════════════════════════════════════════════
# 🚀  MAIN
# ══════════════════════════════════════════════════════
async def main():
    # WebSocket server
    web_app = web.Application()
    web_app.router.add_get("/ws/{uid}", ws_handler)
    web_app.router.add_get("/", lambda r: web.json_response({"status":"ok"}))
    runner = web.AppRunner(web_app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", 8000).start()
    print("🌐 ws://localhost:8000/ws/{user_id}")

    # Bot
    bot_app = Application.builder().token(BOT_TOKEN).build()
    bot_app.add_handler(CommandHandler("start",   cmd_start))
    bot_app.add_handler(CommandHandler("balance", cmd_balance))
    bot_app.add_handler(CommandHandler("buy",     cmd_buy))
    bot_app.add_handler(CommandHandler("admin",   cmd_admin))
    bot_app.add_handler(CallbackQueryHandler(callback_handler))
    bot_app.add_handler(PreCheckoutQueryHandler(pre_checkout))
    bot_app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, payment_done))

    await bot_app.initialize()
    await bot_app.start()
    await bot_app.updater.start_polling()
    print("🤖 Bot ishga tushdi!")
    print(f"⭐ Stars to'lov tayyor!")
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())