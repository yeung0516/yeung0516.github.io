# yeung0516.github.io

A collection of interactive web applications hosted on GitHub Pages.

## Pages

### 🚌 [Shuttle Bus Schedule](index.html)
Real-time shuttle bus timetable dashboard for Villa Concerto ↔ Sunshine City (Ma On Shan) / New Town Plaza (Sha Tin). Features live countdown timers, next-bus tracking, in-transit status, bilingual interface (Chinese/English), day-type auto-detection (weekday/weekend), and font-size accessibility control. Schedule data is loaded from `shuttle_bus_schedule.json`.

### 🗼 [Tokyo Itinerary](Tokyo.html)
A 7-day Tokyo travel itinerary planner (Feb 17–23, 2026) with expandable daily schedules, event check-off functionality, real-time weather widget via Open-Meteo API, embedded Google Maps links, and accommodation details. Built with Tailwind CSS for a responsive, mobile-friendly layout.

### 🇷🇺 [Russian Language Learning](Russian.html)
Interactive Russian language learning module featuring 10 real-life conversation scenarios. Includes color-coded keyword categories, text-to-speech (Web Speech API + Google Translate TTS fallback), pronunciation guides, and multi-language translations (English, Hong Kong Cantonese, Taiwan Mandarin, Mainland Chinese) with a language switcher.

### 🇪🇸 [Spanish Language Learning](Spain.html)
Spanish language learning module with 10 conversational scenarios and a unique animated walking character. Features the same multi-language translation system and TTS support as the Russian module, plus an inline SVG Spanish-style character that wanders the page with boundary-aware collision detection to avoid overlapping text content.

### 🫐 [Blueberry Washing Guide](Berry.html)
Comprehensive blueberry washing and health guide (藍莓清洗完全指南) designed for Hong Kong households. Features detailed step-by-step washing instructions with illustrated visuals, extensive health benefits section backed by academic research, interactive origin guide covering 8 major blueberry-producing regions worldwide, and seasonal harvest calendar with sweetness ratings by region. Built with Traditional Chinese (Hong Kong) language, gradient styling, and smooth animations for an engaging educational experience.

### 📊 [US Stock Market Crisis Detection Dashboard](Crisis.html)
Real-time financial crisis detection system using 10 academic and practitioner-proven methodologies with efficiency-weighted scoring. Features interactive charts showing S&P 500 historical prices overlaid with a composite crisis index, live indicator monitoring (VIX, Credit Spreads, Yield Curve, Market Momentum, CAPE Ratio, Market Breadth, Put-Call Ratio, TED Spread, Margin Debt, Cross-Asset Correlation), comprehensive methodology section with mathematical formulas and academic citations, and graceful error handling with fallback visualizations. Built with Chart.js for data visualization, responsive dark-themed design, and real-time market data integration via Yahoo Finance API.

### ⏱️ [History Incident Alignment](History.html)
White-themed horizontal timelines that align 100 incidents per region (East Asia, Europe, Middle East & Africa, Americas & Oceania) on a unified calendar year. Includes draggable timeline plates, language toggles (English, 中文, Español), a daily visitor counter that avoids duplicate refreshes, and inline self-tests for translation, marker math, and counting logic.

### 🗺️ [Hong Kong Live Map 香港即時地圖](HKMap.html)
Full-screen interactive Hong Kong map powered by Leaflet.js and CartoDB Voyager tiles in a cartoon/anime visual style. Integrates live data from multiple Hong Kong Government Open APIs across 8 toggleable layers:

| Layer | Data Source | Update Frequency |
|---|---|---|
| 🌤️ **Weather** | Hong Kong Observatory Open Data API | Real-time |
| 🚗 **Traffic** | TD Speed Map API + cached hourly snapshot | Every 2 min (live) / Hourly (CI cache) |
| 🚌 **KMB Bus** | KMB/LWB ETA Open Data API + cached route data | Every 30s (GPS tracker) |
| 🚇 **MTR** | MTR Next Train Open Data API | Real-time |
| 🅿️ **Car Parks** | TD Parking Vacancy API | Every few minutes |
| 🏠 **Housing** | HK Housing Authority / CSDI reference data | Static |
| 🎭 **Events & Culture** | LCSD venue reference data | Static |
| 🏥 **Public Health** | Hospital Authority reference data | Static |

**Traffic Speed Layer** — Color-coded polylines across 10 major expressways (Island Eastern Corridor, Tolo Highway, Tuen Mun Highway, Nathan Road Corridor, Route 8 / Stonecutters Bridge, etc.) showing real-time average vehicle speed versus the posted speed limit. Color scale:
- 🟢 **Green** ≥70% of speed limit — Free flow
- 🟠 **Amber** 40–70% — Moderate congestion
- 🔴 **Red** 20–40% — Slow traffic
- 🟣 **Purple** <20% — Near standstill

**Bus Route Selection & Filtering** — A dropdown menu allows users to select any bus route from KMB, CTB/NWFB, or NLB operators. When a route is selected:
- The map displays only the stops for that specific route
- A colored polyline traces the route path with direction indicators
- The map automatically zooms to fit the entire route
- When the dropdown is cleared, all bus stops for all routes are shown again

**Bus GPS Tracker** — For KMB routes with cached stop coordinates, the estimated live position of each bus is calculated by linearly interpolating between the previous and next stop using the KMB ETA timestamps. A directional arrow icon rotates to show the direction of travel. Positions update every 30 seconds.

**CI/CD Data Pipeline** — Low-frequency reference data (KMB route stops, TD speed map) is fetched every 10 minutes by GitHub Actions (`.github/workflows/update_hk_map_data.yml`) and committed to `data/hk_bus_routes.json` and `data/hk_traffic_speeds.json`. This dramatically reduces client-side API call volume.

**Mobile Landscape Support** — A collapsible layer panel (🎛️ toggle button) ensures all controls remain clickable in phone landscape/portrait mode. Panel auto-hides on screens ≤600 px wide or landscape viewports ≤500 px tall.

Other features: draggable/zoomable map, weather warning banner, per-station temperature badges with float animations, MTR coloured polylines with next-train schedules, carpark vacancy colour coding (green/yellow/red), marker clustering for bus stops and car parks, and comic-book cartoon styling throughout.

#### GitHub Actions Workflows

| Workflow | File | Schedule | Purpose |
|---|---|---|---|
| Update Stock Data | `update_stocks.yml` | Hourly (`:15`) | Fetch yfinance stock prices → `data/stocks.json` |
| Update HK Map Data | `update_hk_map_data.yml` | Every 10 minutes | Fetch KMB routes + TD speed map → `data/hk_bus_routes.json`, `data/hk_traffic_speeds.json` |
