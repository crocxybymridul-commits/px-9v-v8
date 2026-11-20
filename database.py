import sqlite3, os, hashlib, secrets, datetime
import config

def conn():
    c=sqlite3.connect(config.DB_PATH)
    c.row_factory=sqlite3.Row
    return c

def _ensure_column(c, table, name, definition):
    cols={r[1] for r in c.execute(f"PRAGMA table_info({table})").fetchall()}
    if name not in cols: c.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")

def init_db():
    c=conn(); x=c.cursor()
    x.execute("""CREATE TABLE IF NOT EXISTS access_keys(
      id INTEGER PRIMARY KEY AUTOINCREMENT, key_hash TEXT UNIQUE NOT NULL,
      key_hint TEXT NOT NULL, max_uses INTEGER NOT NULL DEFAULT 1, used_count INTEGER NOT NULL DEFAULT 0,
      premium_enabled INTEGER NOT NULL DEFAULT 0, premium_user_limit INTEGER,
      premium_revenue_limit INTEGER, premium_days INTEGER,
      created_by INTEGER NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP, status TEXT DEFAULT 'ACTIVE'
    )""")
    x.execute("""CREATE TABLE IF NOT EXISTS bots(
      id INTEGER PRIMARY KEY AUTOINCREMENT, owner_id INTEGER NOT NULL,
      bot_user_id INTEGER, bot_username TEXT, bot_token_enc TEXT NOT NULL,
      access_key_id INTEGER NOT NULL, admin_id INTEGER NOT NULL,
      premium_key TEXT, premium_user_limit INTEGER, premium_revenue_limit INTEGER, premium_days INTEGER,
      instance_path TEXT NOT NULL, pid INTEGER, status TEXT DEFAULT 'RUNNING',
      created_at TEXT DEFAULT CURRENT_TIMESTAMP, revoked_at TEXT
    )""")
    x.execute("""CREATE TABLE IF NOT EXISTS father_users(
      user_id INTEGER PRIMARY KEY, first_name TEXT DEFAULT '', last_name TEXT DEFAULT '', username TEXT DEFAULT '',
      registered_at TEXT DEFAULT CURRENT_TIMESTAMP, last_seen TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    x.execute("""CREATE TABLE IF NOT EXISTS father_premium_keys(
      id INTEGER PRIMARY KEY AUTOINCREMENT, key_hash TEXT UNIQUE NOT NULL, key_hint TEXT NOT NULL,
      plan_name TEXT NOT NULL DEFAULT 'ELITE', max_users INTEGER NOT NULL DEFAULT 1,
      bots_per_user INTEGER NOT NULL DEFAULT 1, duration_days INTEGER NOT NULL DEFAULT 30,
      price INTEGER NOT NULL DEFAULT 0, redeemed_count INTEGER NOT NULL DEFAULT 0,
      status TEXT NOT NULL DEFAULT 'ACTIVE', created_by INTEGER NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    x.execute("""CREATE TABLE IF NOT EXISTS father_subscriptions(
      user_id INTEGER PRIMARY KEY, plan_name TEXT NOT NULL, bot_limit INTEGER NOT NULL,
      expires_at TEXT NOT NULL, price INTEGER DEFAULT 0, source_key_id INTEGER,
      status TEXT DEFAULT 'ACTIVE', updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    x.execute("""CREATE TABLE IF NOT EXISTS father_key_redemptions(
      id INTEGER PRIMARY KEY AUTOINCREMENT, key_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
      redeemed_at TEXT DEFAULT CURRENT_TIMESTAMP, UNIQUE(key_id,user_id)
    )""")
    x.execute("""CREATE TABLE IF NOT EXISTS father_support_cooldowns(
      user_id INTEGER PRIMARY KEY, last_sent REAL NOT NULL
    )""")
    x.execute("""CREATE TABLE IF NOT EXISTS father_settings(
      name TEXT PRIMARY KEY, value TEXT DEFAULT ''
    )""")
    # Safe upgrades for older Father Bot databases.
    _ensure_column(c, 'bots', 'owner_id', 'INTEGER')
    c.commit(); c.close()

def _hash(s): return hashlib.sha256(s.encode()).hexdigest()

def save_user(user):
    c=conn(); c.execute("""INSERT INTO father_users(user_id,first_name,last_name,username,last_seen)
      VALUES(?,?,?,?,CURRENT_TIMESTAMP) ON CONFLICT(user_id) DO UPDATE SET
      first_name=excluded.first_name,last_name=excluded.last_name,username=excluded.username,last_seen=CURRENT_TIMESTAMP""",
      (int(user.id),user.first_name or '',user.last_name or '',user.username or ''))
    c.commit(); c.close()

def get_user(uid):
    c=conn(); r=c.execute('SELECT * FROM father_users WHERE user_id=?',(int(uid),)).fetchone(); c.close(); return r

def list_users():
    c=conn(); r=c.execute('SELECT * FROM father_users ORDER BY last_seen DESC').fetchall(); c.close(); return r

def make_access_key(created_by, max_uses, p_user=None, p_rev=None, p_days=None):
    raw="PX9V-ACCESS-"+secrets.token_urlsafe(22).upper().replace("-","_")
    c=conn(); c.execute("""INSERT INTO access_keys
      (key_hash,key_hint,max_uses,premium_enabled,premium_user_limit,premium_revenue_limit,premium_days,created_by)
      VALUES(?,?,?,?,?,?,?,?)""",(_hash(raw),raw[-8:],int(max_uses),int(p_user is not None),p_user,p_rev,p_days,int(created_by)))
    c.commit(); c.close(); return raw

def get_key(raw):
    c=conn(); r=c.execute("SELECT * FROM access_keys WHERE key_hash=?",(_hash(raw.strip()),)).fetchone(); c.close(); return r

def consume_key(raw):
    c=conn()
    r=c.execute("SELECT * FROM access_keys WHERE key_hash=?",(_hash(raw.strip()),)).fetchone()
    if not r: c.close(); return False,"INVALID",None
    if r["status"]!="ACTIVE": c.close(); return False,"REVOKED",r
    if r["used_count"]>=r["max_uses"]: c.close(); return False,"USED",r
    cur=c.execute("UPDATE access_keys SET used_count=used_count+1 WHERE id=? AND used_count<max_uses",(r["id"],))
    ok=cur.rowcount==1; c.commit()
    r=c.execute("SELECT * FROM access_keys WHERE id=?",(r["id"],)).fetchone(); c.close()
    return ok,"OK" if ok else "USED",r

def release_key(raw):
    c=conn(); c.execute("UPDATE access_keys SET used_count=CASE WHEN used_count>0 THEN used_count-1 ELSE 0 END WHERE key_hash=? AND status='ACTIVE'",(_hash(raw.strip()),)); c.commit(); c.close()

def create_premium_key(created_by, plan_name, max_users, bots_per_user, duration_days, price):
    raw='PX9-ELITE-'+secrets.token_urlsafe(16).upper().replace('-','_')
    c=conn(); c.execute('''INSERT INTO father_premium_keys(key_hash,key_hint,plan_name,max_users,bots_per_user,duration_days,price,created_by)
      VALUES(?,?,?,?,?,?,?,?)''',(_hash(raw),raw[-8:],plan_name,int(max_users),int(bots_per_user),int(duration_days),int(price),int(created_by)))
    c.commit(); c.close(); return raw

def get_premium_key(raw):
    c=conn(); r=c.execute('SELECT * FROM father_premium_keys WHERE key_hash=?',(_hash(raw.strip()),)).fetchone(); c.close(); return r

def redeem_premium_key(raw, uid):
    c=conn()
    try:
        c.execute('BEGIN IMMEDIATE')
        key=c.execute('SELECT * FROM father_premium_keys WHERE key_hash=?',(_hash(raw.strip()),)).fetchone()
        if not key: c.rollback(); c.close(); return False,'INVALID',None
        if key['status']!='ACTIVE': c.rollback(); c.close(); return False,'INACTIVE',key
        if key['redeemed_count']>=key['max_users']: c.rollback(); c.close(); return False,'LIMIT',key
        if c.execute('SELECT 1 FROM father_key_redemptions WHERE key_id=? AND user_id=?',(key['id'],int(uid))).fetchone():
            c.rollback(); c.close(); return False,'DUPLICATE',key
        now=datetime.datetime.utcnow()
        existing=c.execute('SELECT * FROM father_subscriptions WHERE user_id=?',(int(uid),)).fetchone()
        if existing and existing['status']=='ACTIVE' and datetime.datetime.fromisoformat(existing['expires_at'])>now:
            expiry=datetime.datetime.fromisoformat(existing['expires_at'])+datetime.timedelta(days=int(key['duration_days']))
            bot_limit=max(int(existing['bot_limit']),int(key['bots_per_user']))
        else:
            expiry=now+datetime.timedelta(days=int(key['duration_days'])); bot_limit=int(key['bots_per_user'])
        c.execute('INSERT INTO father_key_redemptions(key_id,user_id) VALUES(?,?)',(key['id'],int(uid)))
        c.execute('UPDATE father_premium_keys SET redeemed_count=redeemed_count+1 WHERE id=?',(key['id'],))
        c.execute('''INSERT INTO father_subscriptions(user_id,plan_name,bot_limit,expires_at,price,source_key_id,status,updated_at)
          VALUES(?,?,?,?,?,?,'ACTIVE',CURRENT_TIMESTAMP) ON CONFLICT(user_id) DO UPDATE SET
          plan_name=excluded.plan_name,bot_limit=excluded.bot_limit,expires_at=excluded.expires_at,price=excluded.price,
          source_key_id=excluded.source_key_id,status='ACTIVE',updated_at=CURRENT_TIMESTAMP''',
          (int(uid),key['plan_name'],bot_limit,expiry.isoformat(),int(key['price']),key['id']))
        c.commit(); c.close(); return True,'OK',key
    except sqlite3.IntegrityError:
        c.rollback(); c.close(); return False,'DUPLICATE',None
    except Exception:
        c.rollback(); c.close(); raise

def subscription(uid):
    c=conn(); r=c.execute('SELECT * FROM father_subscriptions WHERE user_id=?',(int(uid),)).fetchone(); c.close()
    if not r or r['status']!='ACTIVE': return None
    try:
        if datetime.datetime.fromisoformat(r['expires_at'])<=datetime.datetime.utcnow(): return None
    except ValueError: return None
    return r

def remove_premium(uid):
    c=conn(); cur=c.execute("UPDATE father_subscriptions SET status='REMOVED',updated_at=CURRENT_TIMESTAMP WHERE user_id=? AND status='ACTIVE'",(int(uid),)); c.commit(); c.close(); return cur.rowcount>0

def premium_users():
    c=conn(); r=c.execute("SELECT * FROM father_subscriptions WHERE status='ACTIVE' ORDER BY expires_at").fetchall(); c.close(); return [x for x in r if datetime.datetime.fromisoformat(x['expires_at'])>datetime.datetime.utcnow()]

def support_cooldown_ok(uid, now_ts, cooldown=300):
    c=conn(); r=c.execute('SELECT last_sent FROM father_support_cooldowns WHERE user_id=?',(int(uid),)).fetchone()
    if r and float(now_ts)-float(r['last_sent'])<cooldown: c.close(); return False, int(cooldown-(float(now_ts)-float(r['last_sent'])))
    c.execute('INSERT INTO father_support_cooldowns(user_id,last_sent) VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET last_sent=excluded.last_sent',(int(uid),float(now_ts)))
    c.commit(); c.close(); return True,0

def setting(name, value=None):
    c=conn()
    if value is None: r=c.execute('SELECT value FROM father_settings WHERE name=?',(name,)).fetchone(); c.close(); return r['value'] if r else ''
    c.execute('INSERT INTO father_settings(name,value) VALUES(?,?) ON CONFLICT(name) DO UPDATE SET value=excluded.value',(name,str(value))); c.commit(); c.close()

def list_bots(owner_id=None):
    c=conn()
    if owner_id is None: rows=c.execute("SELECT * FROM bots ORDER BY id DESC").fetchall()
    else: rows=c.execute("SELECT * FROM bots WHERE owner_id=? ORDER BY id DESC",(int(owner_id),)).fetchall()
    c.close(); return rows

def add_bot(data):
    c=conn()
    cur=c.execute("""INSERT INTO bots(owner_id,bot_user_id,bot_username,bot_token_enc,access_key_id,admin_id,premium_key,premium_user_limit,premium_revenue_limit,premium_days,instance_path,pid,status)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",data)
    c.commit(); bid=cur.lastrowid; c.close(); return bid

def get_bot_by_id(bid):
    c=conn(); r=c.execute("SELECT * FROM bots WHERE id=?",(int(bid),)).fetchone(); c.close(); return r

def find_bot(value):
    value=value.strip().lstrip("@")
    c=conn()
    if value.isdigit(): r=c.execute("SELECT * FROM bots WHERE id=? OR bot_user_id=?",(int(value),int(value))).fetchone()
    else: r=c.execute("SELECT * FROM bots WHERE lower(bot_username)=lower(?)",(value,)).fetchone()
    c.close(); return r

def revoke_bot(bid):
    c=conn(); cur=c.execute("UPDATE bots SET status='REVOKED',revoked_at=CURRENT_TIMESTAMP WHERE id=? AND status!='REVOKED'",(int(bid),)); ok=cur.rowcount==1; c.commit(); c.close(); return ok


def redemption_history(uid):
    c=conn(); r=c.execute('''SELECT k.plan_name,k.key_hint,k.bots_per_user,k.duration_days,k.price,x.redeemed_at
      FROM father_key_redemptions x JOIN father_premium_keys k ON k.id=x.key_id WHERE x.user_id=? ORDER BY x.id DESC''',(int(uid),)).fetchall(); c.close(); return r
