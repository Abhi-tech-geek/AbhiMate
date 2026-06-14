# AbhiMate — Deployment Guide
# Subdomain pe Live Karo: abhimate.theabhinavsaxena.in

> Tera portfolio Vercel pe hai (`theabhinavsaxena.in`). AbhiMate Vercel pe
> **nahi** chal sakta (Chrome browser + SQLite + background scheduler chahiye,
> jo serverless support nahi karta). Isliye AbhiMate ko **Railway/Render/Fly**
> pe deploy karo, aur subdomain `abhimate.theabhinavsaxena.in` ko us pe point
> karo. Portfolio Vercel pe waise hi rahega.

---

## Architecture Overview

```
theabhinavsaxena.in            → Vercel (portfolio — as-is, no change)
abhimate.theabhinavsaxena.in   → Railway/Render/Fly (AbhiMate — new)
```

Dono alag hosting pe, ek hi domain ke under. DNS subdomain magic.

---

## Files Jo Add Kiye Gaye (Deployment Ke Liye)

| File | Kaam |
|---|---|
| `Dockerfile` | Container with Chromium + driver baked in |
| `.dockerignore` | Build context se secrets + cruft hatata hai |
| `railway.json` | Railway config (Dockerfile builder) |
| `render.yaml` | Render blueprint (alternative) |
| `fly.toml` | Fly.io config (alternative) |
| `.env.example` | Saare env vars documented |

**Code change:** `utils/automation_drivers.py` ab `CHROME_BIN` +
`CHROMEDRIVER_PATH` env vars padhta hai — cloud mein system Chromium use karta
hai, download nahi karta. Local pe koi change nahi (env vars set nahi honge toh
purana webdriver-manager path chalega).

---

# OPTION 1 — RAILWAY (Recommended)

## Step 1 — Code GitHub pe Push Karo

```bash
cd "C:\Users\abhin\OneDrive\Documents\AI project\Abhimate"
git add .
git commit -m "Add cloud deployment (Dockerfile + Railway/Render/Fly configs)"
git push origin main
```

## Step 2 — Railway Account + Project

1. https://railway.app pe jao → "Login with GitHub"
2. "New Project" click karo
3. "Deploy from GitHub repo" select karo
4. `Abhi-tech-geek/AbhiMate` repo choose karo
5. Railway automatically `Dockerfile` detect karega aur build shuru karega

## Step 3 — Environment Variables Add Karo

Project → "Variables" tab → ye add karo:

```
GROQ_API_KEY          = gsk_xxxxxxxxxxxxxxxxxx   (apni nayi Groq key)
ABHIMATE_PUBLIC_URL   = https://abhimate.theabhinavsaxena.in
```

(Baaki — HEADLESS, HOST, DEBUG, CHROME_BIN — Dockerfile mein already set hain.)

## Step 4 — Persistent Storage (Important!)

SQLite DB + screenshots ko deploy ke baad bachane ke liye volume attach karo:

1. Project → "Settings" → "Volumes" → "New Volume"
2. Mount path: `/app/data`
3. Ek aur volume DB ke liye: Mount path `/app/database`
4. Save

> Volume na lagaya toh har redeploy pe users + sessions reset ho jayenge.

## Step 5 — Public URL Generate Karo

1. Project → "Settings" → "Networking" → "Generate Domain"
2. Railway dega: `abhimate-production-xxxx.up.railway.app`
3. Pehle isi URL pe kholke test karo — sab kaam kar raha hai?

## Step 6 — Custom Subdomain Add Karo

1. Project → "Settings" → "Networking" → "Custom Domain"
2. Type karo: `abhimate.theabhinavsaxena.in`
3. Railway ek **CNAME target** dega, jaise:
   ```
   abhimate.theabhinavsaxena.in  →  xxxx.up.railway.app
   ```
4. Ye CNAME ab DNS mein add karna hai (Step 7)

## Step 7 — DNS Setting (Domain Registrar)

Tera domain jahan se liya hai (GoDaddy / Namecheap / Hostinger / Cloudflare),
wahan DNS management kholo:

```
Type   : CNAME
Name   : abhimate
Target : xxxx.up.railway.app     (jo Railway ne diya)
TTL    : Auto / 3600
Proxy  : OFF (agar Cloudflare hai — DNS only, orange cloud grey karo)
```

**Save karo.** DNS propagate hone mein 5 min - 1 ghanta lagta hai.

## Step 8 — Verify

```
https://abhimate.theabhinavsaxena.in
```

Browser mein kholo → AbhiMate login page dikhega → Done!

SSL/HTTPS automatically Railway provide karta hai (Let's Encrypt).

---

# OPTION 2 — RENDER (Free, Thoda Slow)

## Steps:

1. https://render.com → GitHub se login
2. "New +" → "Blueprint"
3. `Abhi-tech-geek/AbhiMate` repo select karo
4. Render `render.yaml` padh lega automatically
5. `GROQ_API_KEY` set karo dashboard mein (secret)
6. Deploy!
7. Custom domain: Service → "Settings" → "Custom Domains" →
   `abhimate.theabhinavsaxena.in` add karo
8. Render CNAME dega → DNS mein add karo (same as Railway Step 7)

**Note:** Free tier 15 min inactivity ke baad sleep hota hai. Pehli request
slow (cold start ~30 sec). Always-on chahiye toh paid plan ($7/mo).

---

# OPTION 3 — FLY.IO (Best Performance)

## Steps:

```bash
# 1. flyctl install karo (https://fly.io/docs/flyctl/install/)

# 2. Login
fly auth login

# 3. App naam unique karo — fly.toml mein "app" change karo pehle
#    (jaise abhimate-abhinav)

# 4. Launch (deploy nahi, sirf setup)
cd "C:\Users\abhin\OneDrive\Documents\AI project\Abhimate"
fly launch --no-deploy

# 5. Volume banao (data persist ke liye)
fly volumes create abhimate_data --region bom --size 1

# 6. Groq key secret set karo
fly secrets set GROQ_API_KEY=gsk_xxxxxxxxxxxxx

# 7. Deploy
fly deploy

# 8. Custom domain
fly certs add abhimate.theabhinavsaxena.in
# Fly DNS instructions dega → CNAME add karo
```

---

# IMPORTANT: Selenium vs Playwright in Cloud

Default backend **Selenium** hai, aur Dockerfile mein Chromium + chromedriver
dono installed hain — ye out-of-the-box kaam karega.

Agar Playwright try karna ho (faster, auto-wait):

1. `requirements.txt` mein add karo: `playwright>=1.40`
2. Dockerfile mein Chromium ki jagah ye:
   ```dockerfile
   RUN pip install playwright && playwright install --with-deps chromium
   ```
3. Env var: `ABHIMATE_BACKEND=playwright`

Lekin shuruaat ke liye Selenium hi rakho — already configured hai.

---

# COST COMPARISON

| Platform | Free Tier | Always-On | Chrome | Best For |
|---|---|---|---|---|
| **Railway** | $5 credit/mo | Yes (credit tak) | ✅ | Recommended |
| **Render** | Yes (sleeps) | $7/mo | ✅ | Budget |
| **Fly.io** | 3 VMs free | Yes | ✅ | Performance |

Portfolio ke saath demo ke liye **Railway** sabse simple hai.

---

# TROUBLESHOOTING

## "Application failed to respond"
- Logs check karo (Railway/Render dashboard → Logs)
- `ABHIMATE_HOST=0.0.0.0` set hai? (Dockerfile mein hai, but verify)
- `$PORT` honor ho raha hai? (Dockerfile CMD handle karta hai)

## "Chrome failed to start / DevToolsActivePort"
- `--no-sandbox` flag laga hai (automation_drivers.py mein hai) ✅
- Memory kam hai? Chromium ko min 1GB RAM chahiye — VM size badhao

## "GROQ_API_KEY not set"
- Dashboard → Variables mein add kiya? Redeploy karo

## "Data reset after redeploy"
- Volume attach nahi kiya. `/app/data` + `/app/database` pe volume mount karo

## "Subdomain not working"
- DNS propagate hone do (1 ghanta)
- `nslookup abhimate.theabhinavsaxena.in` se check karo CNAME resolve ho raha hai
- Cloudflare hai? Proxy OFF karo (DNS only mode)

## "Slack links localhost dikha rahe hain"
- `ABHIMATE_PUBLIC_URL=https://abhimate.theabhinavsaxena.in` set karo

---

# DEPLOYMENT CHECKLIST

```
[ ] Code GitHub pe push kiya
[ ] Railway/Render/Fly account banaya
[ ] Repo connect kiya
[ ] GROQ_API_KEY env var set kiya (NAYI key, purani rotate ki)
[ ] ABHIMATE_PUBLIC_URL set kiya
[ ] Volume attach kiya (/app/data + /app/database)
[ ] Railway URL pe test kiya — kaam kar raha hai?
[ ] Custom domain abhimate.theabhinavsaxena.in add kiya
[ ] DNS mein CNAME add kiya
[ ] https://abhimate.theabhinavsaxena.in khulta hai
[ ] Signup → generate test → run — sab kaam karta hai
```

---

# QUICK START (TL;DR)

```bash
# 1. Push code
git add . && git commit -m "deploy setup" && git push

# 2. railway.app → New Project → from GitHub → AbhiMate

# 3. Variables: GROQ_API_KEY + ABHIMATE_PUBLIC_URL

# 4. Volumes: /app/data + /app/database

# 5. Settings → Networking → Custom Domain → abhimate.theabhinavsaxena.in

# 6. DNS (registrar): CNAME abhimate → <railway-target>

# 7. Done → https://abhimate.theabhinavsaxena.in
```
