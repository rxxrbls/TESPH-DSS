# 🚀 Streamlit Community Cloud Deployment Guide
**Prescriptive Analytics Decision-Support System (TESPH-DSS)**

This document provides a complete, step-by-step walkthrough for deploying the TESPH-DSS application to **Streamlit Community Cloud** (free tier).

---

## 📌 Architectural Overview: How Website & Database Work

Streamlit Community Cloud is a serverless application platform designed specifically for Streamlit apps. Here is how your components operate on the cloud:

```
┌────────────────────────────────────────────────────────────────────────┐
│                   Streamlit Community Cloud Container                  │
│                                                                        │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                Web Application Server (Streamlit)                │  │
│  │   • Public URL: https://<your-subdomain>.streamlit.app           │  │
│  │   • Multi-page router (app.py + pages/)                          │  │
│  │   • Authentication Gate (utils/auth.py via st.secrets)           │  │
│  └──────────────────────────────────┬───────────────────────────────┘  │
│                                     │                                  │
│  ┌──────────────────────────────────▼───────────────────────────────┐  │
│  │                   Python Analytical & ML Backend                 │  │
│  │   • Ingestion, Star Schema & Invariants (etl.py)                 │  │
│  │   • Forecasting Engine (Exponential Smoothing, MA, Linear Reg)   │  │
│  │   • Prescriptive Engine (Stock Risk & 3-Criterion MCA)           │  │
│  └──────────────────────────────────┬───────────────────────────────┘  │
│                                     │                                  │
│  ┌──────────────────────────────────▼───────────────────────────────┐  │
│  │                      Embedded Database Layer                     │  │
│  │   • Baseline: final_outputs/ (226,203 rows Star Schema CSVs)     │  │
│  │   • Active DB: runtime_data/active_transactions.db (SQLite)      │  │
│  │   • Auto-Bootstrapping: Handled automatically by runtime store   │  │
│  └──────────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────────┘
```

### Key Highlights for Your Capstone Evaluation:
1. **No External Database Required**: Your system is architected around an embedded SQLite engine and governed Star Schema files in `final_outputs/`. You do not need to pay for or maintain a PostgreSQL instance.
2. **Auto-Bootstrapping**: If `runtime_data/active_transactions.db` does not exist when the cloud container starts, `runtime_data_store.py` automatically reads the 226,203-row historical baseline from `final_outputs/prepared_transactions.csv`. All analytics, forecasting charts, and MCA priority rankings work immediately on initial load.
3. **Ephemeral Storage Behavior**: On the free tier, files created during a browser session (such as ad-hoc file uploads) are kept in memory and local SQLite during that session. When Streamlit Cloud reboots or restarts the container, it cleanly resets back to the governed baseline in `final_outputs/`. This ensures your demo always starts in a clean, pristine, advisor-approved state.

---

## 📋 Prerequisites Checklist

Before you begin, ensure you have:
- [x] GitHub account that has write access to repository: **`Charcoal25/TESPH-DSS`**
- [x] Streamlit Cloud account (sign in using your GitHub account at [share.streamlit.io](https://share.streamlit.io))
- [x] Latest integration branch: **`week4-integrated`**
- [x] Updated [`.streamlit/config.toml`](.streamlit/config.toml) with `address = "0.0.0.0"` (already configured)

---

## 🛠️ Step-by-Step Deployment Instructions

### Step 1: Commit and Push the Configuration Changes

Open PowerShell on your computer and push the updated `.streamlit/config.toml` to your GitHub branch:

```powershell
# 1. Navigate to the project root
cd "C:\Users\Calee Jann\Downloads\TESPH-DSS"

# 2. Check changed files
git status

# 3. Stage the config file and this deployment guide
git add .streamlit/config.toml DEPLOY_STREAMLIT_CLOUD.md

# 4. Commit the changes
git commit -m "chore(deploy): prepare configuration and guide for Streamlit Community Cloud"

# 5. Push to GitHub
git push origin week4-integrated
```

---

### Step 2: Sign In to Streamlit Community Cloud

1. Open your web browser and go to: **[https://share.streamlit.io/](https://share.streamlit.io/)**
2. Click **"Continue with GitHub"**.
3. Authorize Streamlit to access your repositories if prompted.

---

### Step 3: Create and Deploy the New App

1. Once on your Streamlit Cloud workspace dashboard, click the blue button in the upper right: **"Create app"** (or **"New app"**).
2. If asked how you want to deploy, choose **"I already have an app"** (or **"Deploy from GitHub"**).
3. Fill in the deployment form with the following exact settings:
   - **Repository**: `Charcoal25/TESPH-DSS`
   - **Branch**: `week4-integrated`
   - **Main file path**: `app.py`
   - **App URL** *(Optional customize)*: You can set a custom subdomain such as:  
     `tesph-dss.streamlit.app` *(or any unique available name)*

> [!IMPORTANT]
> **Do not click "Deploy!" just yet.** You must first configure the secrets in Step 4.

---

### Step 4: Configure Cloud Secrets (Authentication & Database)

Before launching, click **"Advanced settings..."** (located at the bottom of the deployment popup):

1. Click on the **Secrets** tab in the dialog box.
2. Paste the following TOML configuration into the secrets text area:

```toml
[auth]
username = "admin"
password = "adminpassword123"
email = "admin@tesph.com"

# Optional: Configuration for password reset email notifications
[email]
smtp_host = "smtp.example.com"
smtp_port = "587"
smtp_username = "smtp-user"
smtp_password = "smtp-password"
from_email = "no-reply@example.com"
app_base_url = "https://tesph-dss.streamlit.app"
```

> [!TIP]
> You can change `username` and `password` to whatever login credentials you and your teammates prefer. These are encrypted at rest by Streamlit and never committed to GitHub.

3. Click **"Save"**.
4. Now, click the blue **"Deploy!"** button.

---

### Step 5: Monitor the Build & Startup

Streamlit Cloud will now launch a virtual container:
1. In the bottom right corner, click **"Manage app"** to view live terminal logs.
2. Streamlit Cloud will execute:
   - `git clone` (including Git LFS pull for CSV data files)
   - `pip install -r requirements.txt` (installing numpy, pandas, openpyxl, streamlit, filelock)
   - `streamlit run app.py`
3. The initial build typically takes **2 to 3 minutes**. When finished, the terminal will show:
   ```text
   You can now view your Streamlit app in your browser.
   URL: http://0.0.0.0:8501
   ```
4. The screen will automatically refresh and display the **TheEverythingShopPH Decision Support System** login page!

---

### Step 6: Post-Deployment Verification & Smoke Test

Now perform a live verification on the deployed website:

1. **Sign-In Verification**:
   - Enter your configured credentials:
     - **Username**: `admin`
     - **Password**: `adminpassword123`
   - Click **"Log in"**.
   - Verify that the login screen dismisses and transitions to the main application shell.

2. **Dashboard Verification**:
   - Check the top header: Status indicator should read **`Data ready`** (green dot).
   - Verify KPI cards:
     - **Gross Revenue**: `₱25,366,956.00`
     - **Net Revenue**: `₱25,347,789.00`
     - **Units Sold**: `637,133`
   - Verify the Category Mix donut chart and Monthly Sales Trend line chart render cleanly.

3. **Multi-Page Navigation Test**:
   - Navigate to **Analyze → Sales & Product Analytics**:
     - Check tabbed views: *Sales Trends*, *Category Mix*, *Product Performance*, *Order Status*.
   - Navigate to **Analyze → Demand Forecast**:
     - Confirm category-level time-series projections and holdout accuracy metrics (MAE, RMSE, MAPE).
   - Navigate to **Decide → Product Prioritization**:
     - Confirm the approved 3 criteria: *Sales Velocity*, *Forecasted Demand*, and *Return/Refund Rate*.
     - Verify equal-thirds weighting (33.33% / 33.33% / 33.34%) and top priority SKU tables.
   - Navigate to **Decide → Replenishment Recommendations**:
     - Confirm safety stock calculations, Target Stock Level, and suggested reorder quantities.

---

## 🔍 Troubleshooting & Maintenance

### 1. App goes to sleep ("Zzz")
* **What happens**: On Streamlit Community Cloud's free tier, apps that receive no traffic for a few consecutive days go to sleep to save cloud resources.
* **How to wake it**: Anyone visiting the URL simply clicks the blue **"Yes, get this app back up!"** button. The app will wake up and be ready within 30–60 seconds.

### 2. Updating Code & Redeploying
* Streamlit Community Cloud continuously monitors your GitHub branch (`week4-integrated`).
* Whenever you run `git push origin week4-integrated`, Streamlit Cloud detects the new commit and automatically initiates a fast live hot-reload without downtime.

### 3. Modifying Secrets After Deployment
* If you need to change your admin password or credentials later:
  1. Open your app URL.
  2. Click the **"Manage app"** menu in the bottom-right corner.
  3. Click the three dots `...` → **"Settings"** → **"Secrets"**.
  4. Edit the values and click **"Save"**. The app will reload with the new secrets.

### 4. Git LFS Bandwidth Caution
* GitHub provides **1 GB/month of free LFS bandwidth**.
* Because the CSV datasets in `final_outputs/` are approximately 350 MB, each complete container rebuild downloads those files.
* **Best Practice**: Avoid unnecessary multiple app deletions or redeployments in a short time frame so you stay well within GitHub's free monthly bandwidth allocation.

---

## 🎓 Summary of Files Changed for Deployment

| File | Status | Purpose |
| :--- | :--- | :--- |
| [`.streamlit/config.toml`](.streamlit/config.toml) | **Modified** | Configured `address = "0.0.0.0"`, `enableCORS = false`, `enableXsrfProtection = false` to allow Streamlit Cloud reverse-proxy routing. |
| [`DEPLOY_STREAMLIT_CLOUD.md`](DEPLOY_STREAMLIT_CLOUD.md) | **Created** | Step-by-step deployment guide placed in workspace root for easy reference during presentation and defense. |

Your workspace is now completely prepared for deployment to Streamlit Community Cloud!
