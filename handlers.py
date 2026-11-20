from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
import config, database as db, provisioner
import os, asyncio, time, html, datetime

states={}

def is_admin(uid): return int(uid) in getattr(config, "ADMIN_IDS", [config.ADMIN_ID])
def _name(u): return " ".join(x for x in [u.first_name,u.last_name] if x) or (u.username or "User")
def _esc(v): return html.escape(str(v or ""))
def _active_bots(uid): return [r for r in db.list_bots(uid) if r['status']!='REVOKED']
def _subscription_text(uid):
    s=db.subscription(uid)
    if not s: return "No active premium plan. Redeem a key to unlock bot creation."
    exp=datetime.datetime.fromisoformat(s['expires_at'])
    remain=max(0,(exp-datetime.datetime.utcnow()).days)
    return (f"💎 Plan: <b>{_esc(s['plan_name'])}</b>\n🗓 Expires: <b>{exp.strftime('%d %b %Y')}</b>\n"
            f"⏳ Remaining: <b>{remain} days</b>\n🤖 Bot slots: <b>{s['bot_limit']}</b>")
def _main_kb():
    return InlineKeyboardMarkup([
      [InlineKeyboardButton("👤 MY PROFILE",callback_data="profile")],
      [InlineKeyboardButton("🤖 MY BOT",callback_data="mybots"),InlineKeyboardButton("🗑 REMOVE BOT",callback_data="remove_list")],
      [InlineKeyboardButton("🎟 REDEEM KEY",callback_data="redeem")],
      [InlineKeyboardButton("➕ CREATE NEW BOT",callback_data="create_bot")],
      [InlineKeyboardButton("📩 CONTACT",callback_data="contact")]])
async def start(update, context):
    u=update.effective_user; db.save_user(u)
    botname=context.bot.username or "PX9V Store"
    await update.message.reply_text(
      f"👋 Hello <b>{_esc(_name(u))}</b>!\n\nWelcome to <b>{_esc(botname)}</b>.\n\n"
      "Your personal bot-management platform. Create and manage your bots, track your premium plan, redeem keys, and contact support from one place.\n\n"
      "⚡ Fast setup • 🔐 Managed access • 💎 Premium plans\n\nChoose an option below:",parse_mode="HTML",reply_markup=_main_kb())
async def _begin_create(message,uid):
    s=db.subscription(uid)
    bots=_active_bots(uid)
    if s:
        if len(bots)>=int(s['bot_limit']):
            await message.reply_text(f"⚠️ Your plan allows <b>{s['bot_limit']} active bot(s)</b>. Remove one bot first to free a slot.",parse_mode="HTML",reply_markup=_main_kb()); return
        states[uid]={'step':'token','premium_create':True}
        await message.reply_text("🤖 Send your new bot's Telegram token from @BotFather.",parse_mode="HTML"); return
    states[uid]={'step':'access'}
    await message.reply_text("🔐 No active premium plan found. Send your bot-creation access key to continue.")
async def home_cb(update,context):
    q=update.callback_query; await q.answer(); db.save_user(q.from_user)
    await q.message.reply_text("Father Bot main menu:",reply_markup=_main_kb())
async def create_bot_cb(update,context):
    q=update.callback_query; await q.answer(); db.save_user(q.from_user)
    await _begin_create(q.message,q.from_user.id)
async def buy(update,context):
    q=update.callback_query; await q.answer(); await _begin_create(q.message,q.from_user.id)
async def mybots(update,context):
    q=update.callback_query; await q.answer(); db.save_user(q.from_user)
    rows=db.list_bots(q.from_user.id)
    if not rows: await q.message.reply_text("📦 No bots found yet.",reply_markup=_main_kb()); return
    lines=["📦 <b>MY BOTS</b>"]
    for r in rows:
        lines.append(f"\n• #{r['id']} — @{_esc(r['bot_username'])}\n  Status: <b>{_esc(r['status'])}</b>")
    s=db.subscription(q.from_user.id); lines.append(f"\n\n{_subscription_text(q.from_user.id)}")
    await q.message.reply_text("\n".join(lines),parse_mode="HTML",reply_markup=_main_kb())
async def profile_cb(update,context):
    q=update.callback_query; await q.answer(); db.save_user(q.from_user); u=db.get_user(q.from_user.id)
    bots=db.list_bots(q.from_user.id); active=_active_bots(q.from_user.id)
    text=(f"👤 <b>MY PROFILE</b>\n\nName: <b>{_esc((u['first_name']+' '+u['last_name']).strip())}</b>\n"
      f"Username: <b>@{_esc(u['username']) if u['username'] else 'N/A'}</b>\nUser ID: <code>{u['user_id']}</code>\n"
      f"Registered: {_esc(u['registered_at'])}\n\n💎 <b>PREMIUM</b>\n{_subscription_text(q.from_user.id)}\n\n"
      f"🤖 Bots created: <b>{len(bots)}</b>\nActive bots: <b>{len(active)}</b>\n\n")
    if active: text+="\n".join(f"• @{_esc(r['bot_username'])} (#{r['id']})" for r in active)
    history=db.redemption_history(q.from_user.id)
    if history: text+="\n\n🎟 <b>REDEEM HISTORY</b>\n"+"\n".join(f"• {_esc(h['plan_name'])} — {h['bots_per_user']} bot(s), {h['duration_days']} days — {h['redeemed_at']}" for h in history[:5])
    await q.message.reply_text(text,parse_mode="HTML",reply_markup=_main_kb())
async def remove_list_cb(update,context):
    q=update.callback_query; await q.answer(); rows=_active_bots(q.from_user.id)
    if not rows: await q.message.reply_text("No active bots to remove.",reply_markup=_main_kb()); return
    kb=[[InlineKeyboardButton(f"🗑 @{r['bot_username']}",callback_data=f"remove_confirm_{r['id']}")] for r in rows]
    kb.append([InlineKeyboardButton("⬅ Back",callback_data="home")])
    await q.message.reply_text("Select a bot to remove. Removal revokes its access and frees a premium slot.",reply_markup=InlineKeyboardMarkup(kb))
async def remove_confirm_cb(update,context):
    q=update.callback_query; await q.answer(); bid=int(q.data.rsplit('_',1)[-1]); r=db.get_bot_by_id(bid)
    if not r or r['owner_id']!=q.from_user.id or r['status']=='REVOKED': await q.message.reply_text("Bot not found or already removed."); return
    kb=[[InlineKeyboardButton("✅ CONFIRM REMOVE",callback_data=f"remove_do_{bid}"),InlineKeyboardButton("Cancel",callback_data="remove_list")]]
    await q.message.reply_text(f"Confirm removal of @{_esc(r['bot_username'])}? This will revoke the bot.",parse_mode="HTML",reply_markup=InlineKeyboardMarkup(kb))
async def remove_do_cb(update,context):
    q=update.callback_query; await q.answer(); bid=int(q.data.rsplit('_',1)[-1]); r=db.get_bot_by_id(bid)
    if not r or r['owner_id']!=q.from_user.id or r['status']=='REVOKED': await q.message.reply_text("Bot not found or already removed."); return
    try: provisioner.stop_bot(r)
    except Exception as e: await q.message.reply_text(f"Removal failed: {_esc(str(e)[:200])}",parse_mode="HTML"); return
    await q.message.reply_text(f"✅ @{_esc(r['bot_username'])} removed and slot freed.",parse_mode="HTML",reply_markup=_main_kb())
async def redeem_cb(update,context):
    q=update.callback_query; await q.answer(); states[q.from_user.id]={'step':'redeem'}
    await q.message.reply_text("🎟 Send your premium redeem key.")
async def redeem_cmd(update,context):
    db.save_user(update.effective_user)
    if context.args:
        await _do_redeem(update.message,update.effective_user.id," ".join(context.args).strip()); return
    states[update.effective_user.id]={'step':'redeem'}; await update.message.reply_text("🎟 Send your premium redeem key.")
async def _do_redeem(message,uid,raw):
    ok,reason,key=db.redeem_premium_key(raw,uid)
    if not ok:
        texts={'INVALID':'Invalid key.','INACTIVE':'This key is inactive.','LIMIT':'This key reached its redeem-user limit.','DUPLICATE':'You have already redeemed this key.'}
        await message.reply_text("❌ "+texts.get(reason,"Could not redeem key.")); return
    states.pop(uid,None)
    await message.reply_text(f"✅ <b>PREMIUM ACTIVATED</b>\n\nPlan: <b>{_esc(key['plan_name'])}</b>\nBot slots: <b>{key['bots_per_user']}</b>\nDuration: <b>{key['duration_days']} days</b>\n\nYour profile has been updated. You can now create bots within your plan limit.",parse_mode="HTML",reply_markup=_main_kb())
async def contact_cb(update,context):
    q=update.callback_query; await q.answer(); states[q.from_user.id]={'step':'contact'}
    await q.message.reply_text("📩 Send one support message now. You may include text, a photo, video or document. The cooldown is 5 minutes.")
async def contact_message(update,context):
    u=update.effective_user; msg=update.effective_message
    ok,wait=db.support_cooldown_ok(u.id,time.time(),300)
    if not ok: await msg.reply_text(f"⏳ Please wait {wait//60}m {wait%60}s before sending another support message."); return
    admins=getattr(config,'ADMIN_IDS',[config.ADMIN_ID])
    body=(f"📩 <b>NEW SUPPORT MESSAGE</b>\n\nUsername: @{_esc(u.username) if u.username else 'N/A'}\n"
      f"Name: {_esc(_name(u))}\nProfile: {_esc(_subscription_text(u.id))}\nUser ID: <code>{u.id}</code>")
    for aid in admins:
        try:
            await context.bot.send_message(aid,body,parse_mode="HTML")
            await context.bot.copy_message(aid,msg.chat_id,msg.message_id,reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩ REPLY TO USER",callback_data=f"support_reply_{u.id}")]]))
        except Exception: pass
    states.pop(u.id,None)
    await msg.reply_text("✅ Your message has been sent to support. Please wait for a reply.")
async def support_reply_cb(update,context):
    q=update.callback_query; await q.answer()
    if not is_admin(q.from_user.id): return
    uid=int(q.data.rsplit('_',1)[-1]); states[q.from_user.id]={'step':'support_reply','target':uid}
    await q.message.reply_text(f"Send your reply to user ID {uid}. Text or media is supported.")
async def revoke_help(update,context):
    q=update.callback_query; await q.answer(); await remove_list_cb(update,context)
async def text_input(update,context):
    uid=update.effective_user.id; st=states.get(uid)
    if st and is_admin(uid) and (st.get('step','').startswith('ak_') or st.get('step','').startswith('pkey_') or st.get('step','').startswith('admin_')): return await admin_text(update,context)
    if not st: return
    msg=update.effective_message; val=(msg.text or '').strip(); step=st.get('step')
    if step=='access':
        row=db.get_key(val)
        if not row: await msg.reply_text("❌ Invalid access key."); return
        if row['status']!='ACTIVE': await msg.reply_text("🔒 This access key is revoked."); return
        if row['used_count']>=row['max_uses']: await msg.reply_text("⚠️ Access key usage limit reached."); return
        st.update({'step':'token','key':row,'access_raw':val,'premium_create':False})
        await msg.reply_text("🤖 Send your bot Access Token from @BotFather."); return
    if step=='redeem': await _do_redeem(msg,uid,val); return
    if step=='token':
        me=await asyncio.to_thread(provisioner.validate_token,val)
        if not me: await msg.reply_text("❌ Invalid token. Send a valid token from @BotFather."); return
        st.update({'step':'admin','token':val,'me':me}); await msg.reply_text("👤 Send the Admin ID for your new bot (numeric Telegram ID)."); return
    if step=='admin':
        try: admin_id=int(val)
        except ValueError: await msg.reply_text("Admin ID must be numeric."); return
        premium_create=bool(st.get('premium_create'))
        keyraw=st.get('access_raw')
        if premium_create:
            keyraw=db.make_access_key(uid,1)
        await msg.reply_text("⚙️ Creating bot... please wait.")
        try:
            ok,reason,live_key=db.consume_key(keyraw)
            if not ok: raise RuntimeError({'INVALID':'Access key invalid.','REVOKED':'Access key revoked.','USED':'Access key limit reached.'}.get(reason,'Access denied.'))
            bid,username,premium=await asyncio.to_thread(provisioner.provision,uid,admin_id,st['token'],live_key)
            states.pop(uid,None)
            await msg.reply_text(f"✅ <b>BOT CREATED</b>\n\n🤖 @{_esc(username)}\n🆔 Bot record: <code>{bid}</code>\n👤 Admin ID: <code>{admin_id}</code>\n\n{_subscription_text(uid)}",parse_mode="HTML",reply_markup=_main_kb())
        except Exception as e:
            if keyraw and not premium_create:
                try: db.release_key(keyraw)
                except Exception: pass
            states.pop(uid,None); await msg.reply_text(f"❌ Creation failed: {_esc(str(e)[:700])}",parse_mode="HTML")
        return
    if step=='support_reply' and is_admin(uid):
        target=int(st['target']); states.pop(uid,None)
        try: await context.bot.copy_message(target,msg.chat_id,msg.message_id)
        except Exception as e: await msg.reply_text(f"Reply delivery failed: {e}"); return
        await msg.reply_text("✅ Reply sent."); return
    if step=='contact': await contact_message(update,context); return
async def media_input(update,context):
    uid=update.effective_user.id; st=states.get(uid)
    if st and st.get('step')=='contact': return await contact_message(update,context)
    if st and st.get('step')=='support_reply' and is_admin(uid):
        target=int(st['target']); states.pop(uid,None)
        try: await context.bot.copy_message(target,update.effective_message.chat_id,update.effective_message.message_id)
        except Exception as e: await update.effective_message.reply_text(f"Reply delivery failed: {_esc(e)}"); return
        await update.effective_message.reply_text("✅ Reply sent.")
async def remove_cmd(update,context):
    uid=update.effective_user.id
    if not context.args: return await update.message.reply_text("Usage: /remove @botusername or bot record ID")
    r=db.find_bot(" ".join(context.args))
    if not r or r['owner_id']!=uid: return await update.message.reply_text("Bot not found or not owned by you.")
    try: provisioner.stop_bot(r)
    except Exception as e: return await update.message.reply_text(f"Removal failed: {_esc(e)}",parse_mode="HTML")
    await update.message.reply_text(f"✅ @{_esc(r['bot_username'])} removed; your bot slot is free.",parse_mode="HTML")
async def revoke(update,context):
    # Legacy command kept for backwards compatibility.
    uid=update.effective_user.id
    if not context.args: return await update.message.reply_text("Usage: /revoke [bot username or access key]")
    value=" ".join(context.args).strip(); row=db.find_bot(value)
    if row:
        if not is_admin(uid) and row['owner_id']!=uid: return await update.message.reply_text("You can remove only your own bot.")
        provisioner.stop_bot(row); return await update.message.reply_text("Bot revoked.")
    key=db.get_key(value)
    if not key: return await update.message.reply_text("Bot/access key not found.")
    if not is_admin(uid) and key['created_by']!=uid: return await update.message.reply_text("You cannot revoke this key.")
    c=db.conn(); c.execute("UPDATE access_keys SET status='REVOKED' WHERE id=?",(key['id'],)); c.commit(); c.close()
    rows=[r for r in db.list_bots() if r['access_key_id']==key['id'] and r['status']!='REVOKED']
    for r in rows: provisioner.stop_bot(r)
    await update.message.reply_text(f"Access key revoked; {len(rows)} linked bot(s) stopped.")
async def removep_cmd(update,context):
    uid=update.effective_user.id
    if not is_admin(uid): return
    if not context.args: return await update.message.reply_text("Usage: /removep [user_id]")
    try: target=int(context.args[0])
    except ValueError: return await update.message.reply_text("User ID must be numeric.")
    if not db.remove_premium(target): return await update.message.reply_text("No active premium subscription found for that user.")
    await update.message.reply_text(f"Premium removed for {target}.")
    try: await context.bot.send_message(target,"Your premium subscription has been removed by an administrator. Bot creation is disabled until premium is restored.")
    except Exception: pass
async def admin(update,context):
    if not is_admin(update.effective_user.id): return
    await update.message.reply_text("🛠 <b>FATHER ADMIN PANEL</b>",parse_mode="HTML",reply_markup=InlineKeyboardMarkup([
      [InlineKeyboardButton("🎟 CREATE PREMIUM KEY",callback_data="a_pkey")],
      [InlineKeyboardButton("🔎 CHECK ELITE USER",callback_data="a_check")],
      [InlineKeyboardButton("➖ REMOVE PREMIUM",callback_data="a_remove")],
      [InlineKeyboardButton("➕ ADD PREMIUM",callback_data="a_add")],
      [InlineKeyboardButton("👥 USERS",callback_data="a_users"),InlineKeyboardButton("💎 PREMIUM USERS",callback_data="a_pusers")],
      [InlineKeyboardButton("🤖 ALL BOTS",callback_data="a_bots")],
      [InlineKeyboardButton("📩 SUPPORT INBOX HELP",callback_data="a_support")],
      [InlineKeyboardButton("🔑 LEGACY CREATE TOKEN",callback_data="a_create")],
      [InlineKeyboardButton("📊 BOT STATISTICS",callback_data="a_stats")]]))
async def create_token_cmd(update,context):
    if not is_admin(update.effective_user.id): return
    states[update.effective_user.id]={'step':'ak_uses'}; await update.message.reply_text("Legacy access token: how many bots can it create?")
async def bots_cmd(update,context):
    if not is_admin(update.effective_user.id): return
    rows=db.list_bots(); await update.message.reply_text("🤖 BOTS\n\n"+("\n".join(f"#{r['id']} @{r['bot_username']} — {r['status']}" for r in rows[:100]) or "No bots."))
async def admin_cb(update,context):
    q=update.callback_query; await q.answer()
    if not is_admin(q.from_user.id): return
    d=q.data
    if d=='a_create': states[q.from_user.id]={'step':'ak_uses'}; await q.message.reply_text("Legacy key: number of bot creations?")
    elif d=='a_pkey': states[q.from_user.id]={'step':'pkey_name'}; await q.message.reply_text("Premium plan name (example: ELITE 30 DAYS):")
    elif d=='a_check': states[q.from_user.id]={'step':'admin_check'}; await q.message.reply_text("Send user ID to check:")
    elif d=='a_remove': states[q.from_user.id]={'step':'admin_remove'}; await q.message.reply_text("Send user ID to remove premium:")
    elif d=='a_add': states[q.from_user.id]={'step':'admin_add'}; await q.message.reply_text("Send user ID to add premium:")
    elif d=='a_users':
        users=db.list_users(); await q.message.reply_text(f"👥 Registered users: {len(users)}\n"+"\n".join(f"{u['user_id']} — {_esc(u['first_name'])} @{_esc(u['username'])}" for u in users[:50]),parse_mode="HTML")
    elif d=='a_pusers':
        users=db.premium_users(); await q.message.reply_text(f"💎 Premium users: {len(users)}\n"+"\n".join(f"{u['user_id']} — {u['plan_name']} — expires {u['expires_at']}" for u in users[:50]))
    elif d=='a_bots':
        rows=db.list_bots(); await q.message.reply_text("🤖 BOT LIST\n\n"+("\n".join(f"#{r['id']} @{r['bot_username']} owner:{r['owner_id']} — {r['status']}" for r in rows[:50]) or "No bots."))
    elif d=='a_support': await q.message.reply_text("Support messages are delivered to configured Father Bot admins with a REPLY TO USER button.")
    elif d=='a_stats':
        rows=db.list_bots(); users=db.list_users(); pusers=db.premium_users(); active=sum(r['status']=='RUNNING' for r in rows)
        await q.message.reply_text(f"📊 STATS\nUsers: {len(users)}\nPremium records: {len(pusers)}\nBots: {len(rows)}\nRunning: {active}\nRevoked: {len(rows)-active}")
async def admin_text(update,context):
    uid=update.effective_user.id; st=states.get(uid)
    if not is_admin(uid) or not st: return
    val=(update.message.text or '').strip(); step=st.get('step')
    if step=='ak_uses':
        try: n=int(val); assert n>0
        except: await update.message.reply_text("Enter a positive number."); return
        st['uses']=n; st['step']='ak_premium'; await update.message.reply_text("Include the legacy Premium Key? YES/NO"); return
    if step=='ak_premium':
        if val.upper() not in ('YES','NO'): await update.message.reply_text("Send YES or NO."); return
        st['premium']=val.upper()=='YES'
        if not st['premium']:
            raw=db.make_access_key(uid,st['uses']); states.pop(uid,None); await update.message.reply_text(f"Legacy access key:\n<code>{raw}</code>",parse_mode='HTML'); return
        st['step']='ak_puser'; await update.message.reply_text("Premium user limit:"); return
    if step=='ak_puser':
        try: n=int(val); assert n>0
        except: await update.message.reply_text("Enter a positive number."); return
        st['puser']=n; st['step']='ak_prev'; await update.message.reply_text("Premium revenue limit:"); return
    if step=='ak_prev':
        try: n=int(val); assert n>=0
        except: await update.message.reply_text("Enter 0 or more."); return
        st['prev']=n; st['step']='ak_pdays'; await update.message.reply_text("Premium duration in days:"); return
    if step=='ak_pdays':
        try: n=int(val); assert n>0
        except: await update.message.reply_text("Enter positive days."); return
        raw=db.make_access_key(uid,st['uses'],st['puser'],st['prev'],n); states.pop(uid,None)
        await update.message.reply_text(f"Legacy access key:\n<code>{raw}</code>",parse_mode='HTML'); return
    if step=='pkey_name': st['plan_name']=val or 'ELITE'; st['step']='pkey_users'; await update.message.reply_text("How many users can redeem this key?"); return
    if step=='pkey_users':
        try: n=int(val); assert n>0
        except: await update.message.reply_text("Enter a positive number."); return
        st['max_users']=n; st['step']='pkey_bots'; await update.message.reply_text("Bots allowed per user:"); return
    if step=='pkey_bots':
        try: n=int(val); assert n>0
        except: await update.message.reply_text("Enter a positive number."); return
        st['bots']=n; st['step']='pkey_days'; await update.message.reply_text("Plan duration in days:"); return
    if step=='pkey_days':
        try: n=int(val); assert n>0
        except: await update.message.reply_text("Enter a positive number."); return
        st['days']=n; st['step']='pkey_price'; await update.message.reply_text("Plan price (numeric amount, 0 if free):"); return
    if step=='pkey_price':
        try: n=int(val); assert n>=0
        except: await update.message.reply_text("Enter a valid non-negative price."); return
        raw=db.create_premium_key(uid,st['plan_name'],st['max_users'],st['bots'],st['days'],n); states.pop(uid,None)
        await update.message.reply_text(f"🎟 <b>PREMIUM KEY CREATED</b>\n\n<code>{raw}</code>\nPlan: {_esc(st['plan_name'])}\nUsers: {st['max_users']}\nBots/user: {st['bots']}\nDuration: {st['days']} days\nPrice: ₹{n}",parse_mode='HTML'); return
    if step in ('admin_check','admin_remove','admin_add'):
        try: target=int(val)
        except: await update.message.reply_text("Enter numeric user ID."); return
        states.pop(uid,None)
        if step=='admin_check':
            u=db.get_user(target); sub=db.subscription(target); bots=db.list_bots(target); active=_active_bots(target)
            if not u: await update.message.reply_text("User profile not found. They may not have started the bot."); return
            history=db.redemption_history(target)
            text=f"👤 USER PROFILE\nID: {target}\nName: {_esc(u['first_name'])} {_esc(u['last_name'])}\nUsername: @{_esc(u['username'])}\nPremium: {'ACTIVE' if sub else 'INACTIVE'}\n{_subscription_text(target)}\nBots total: {len(bots)}\nActive bots: {len(active)}"
            if active: text+='\n'+ '\n'.join(f"• @{_esc(r['bot_username'])} #{r['id']}" for r in active)
            if history: text+='\n\n🎟 KEY HISTORY\n'+'\n'.join(f"• {h['plan_name']} — {h['bots_per_user']} bots / {h['duration_days']} days — ₹{h['price']} — {h['redeemed_at']}" for h in history[:10])
            await update.message.reply_text(text,parse_mode='HTML'); return
        if step=='admin_remove':
            if not db.remove_premium(target): await update.message.reply_text("No active premium subscription found."); return
            await update.message.reply_text(f"Premium removed for {target}.")
            try: await context.bot.send_message(target,"⚠️ Your premium subscription was removed by an administrator. Bot creation is disabled until you redeem/receive premium again.")
            except: pass
            return
        if step=='admin_add':
            states[uid]={'step':'admin_add_plan','target':target}; await update.message.reply_text("Plan name:"); return
    if step=='admin_add_plan': st['plan_name']=val or 'ADMIN PREMIUM'; st['step']='admin_add_bots'; await update.message.reply_text("Bot slots:"); return
    if step=='admin_add_bots':
        try: n=int(val); assert n>0
        except: await update.message.reply_text("Enter positive bot slots."); return
        st['bots']=n; st['step']='admin_add_days'; await update.message.reply_text("Duration in days:"); return
    if step=='admin_add_days':
        try: n=int(val); assert n>0
        except: await update.message.reply_text("Enter positive days."); return
        target=st['target']; expiry=(datetime.datetime.utcnow()+datetime.timedelta(days=n)).isoformat(); states.pop(uid,None)
        c=db.conn(); c.execute("INSERT INTO father_subscriptions(user_id,plan_name,bot_limit,expires_at,status,updated_at) VALUES(?,?,?,?,'ACTIVE',CURRENT_TIMESTAMP) ON CONFLICT(user_id) DO UPDATE SET plan_name=excluded.plan_name,bot_limit=excluded.bot_limit,expires_at=excluded.expires_at,status='ACTIVE',updated_at=CURRENT_TIMESTAMP",(target,st['plan_name'],st['bots'],expiry)); c.commit(); c.close()
        await update.message.reply_text(f"Premium added to {target}: {st['plan_name']} / {st['bots']} bots / {n} days."); return
async def help_cmd(update,context):
    await update.message.reply_text("/start — main menu\n/redeem [key] — redeem premium\n/remove [bot] — remove bot\n/revoke — legacy revoke command\n/admin — admin panel")
