# Deployment Report

## 1. Executive Summary

This report outlines the deployment procedures, environment requirements, security configuration, and operational health checks for **TESPH-DSS** on branch `week4-integrated`. The application is packaged for reliable deployment across local workstations, on-premises servers, and containerized cloud environments.

---

## 2. System & Runtime Prerequisites

| Component | Minimum Specification | Recommended Specification | Verified Platform |
| :--- | :--- | :--- | :--- |
| **Operating System** | Windows 10/11, Ubuntu 20.04+, macOS 12+ | Windows 11 / Ubuntu 22.04 LTS | Windows 11 Pro 64-bit |
| **Python Runtime** | Python 3.10.x to 3.14.x | Python 3.11.x or 3.14.x | Python 3.14.3 |
| **System Memory (RAM)** | 4 GB | 8 GB or 16 GB | 16 GB DDR4/DDR5 |
| **Storage Space** | 500 MB free disk space | 2 GB free disk space | SSD Storage |
| **Browser Compatibility** | Chrome 100+, Edge 100+, Firefox 100+ | Modern Chromium-based browser | Chrome / Edge |

---

## 3. Dependency Management & Environment Isolation

### 3.1. Requirements Audit
The `requirements.txt` manifest has been validated to ensure strict dependency resolution without version conflicts:
- `streamlit>=1.30.0` (Verified on 1.66.1)
- `pandas>=2.0.0`
- `numpy>=1.24.0`
- `openpyxl>=3.1.0` (for Excel export ingestion)
- `filelock>=3.12.0` (for atomic file caching)
- `pytest>=8.0.0` (for regression validation)

### 3.2. Configuration & Security Audit
- **Zero Committed Secrets**: `.streamlit/secrets.toml` is ignored in `.gitignore`. A sanitized template is provided at `.streamlit/secrets.toml.example`.
- **Clean Theme Configuration**: `.streamlit/config.toml` specifies warm cream tokens, disabled telemetry, and clean headless execution defaults.
- **Data Isolation**: Persistent SQLite stores write to `runtime_data/` which is ignored in source control.

---

## 4. Deployment Instructions

### 4.1. Local Workstation Setup (Windows / PowerShell)
```powershell
# 1. Clone repository and checkout integrated branch
git clone https://github.com/Charcoal25/TESPH-DSS.git
cd TESPH-DSS
git checkout week4-integrated

# 2. Create and activate a clean virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 3. Install production dependencies
python -m pip install --upgrade pip
pip install -r requirements.txt

# 4. Run automated verification smoke test
python -m pytest tests/test_downstream_page_rendering.py -v

# 5. Launch application
streamlit run app.py
```

### 4.2. Linux / Container Deployment
```bash
# Activation & launch
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py --server.port 8501 --server.address 0.0.0.0
```

---

## 5. Post-Deployment Smoke Tests & Health Checks

Upon launch, verify system health using the following checklist:
1. **HTTP Endpoint Check**: Access `http://localhost:8501` and verify the authentication login shell renders.
2. **Authentication Check**: Log in with demo credentials. Verify navigation routes populate in the sidebar.
3. **ETL Pipeline Smoke Test**: Open `Data Upload & ETL`, upload a sample transaction export, and verify all 5 stepper stages complete.
4. **Analytical Pages Smoke Test**: Open `Dashboard`, `Demand Forecast`, `Stock-Out Risk`, and `Product Prioritization`. Verify data tables and Vega-Lite charts bind correctly.
5. **Session Reset**: In `Settings`, click `Reset session data`. Verify application state resets cleanly without unhandled server exceptions.
