# # 🛰️ Satellite-Guided Crop Rotation Decision Support

A farmer-centered decision-support web application that combines **NASA POWER climate data** (with a selectable 3–10-year averaging period) and the **UN FAO EcoCrop database (2,568+ species)** to evaluate existing crop rotations and recommend resilient, data-backed alternatives.

---

## 🎯 Problem & Motivation
As temperatures shift, rainfall becomes erratic, and soil organic matter declines, farmers face increasingly complex rotation decisions. A crop that builds soil health in one region may deplete groundwater, suffer heat stress during flowering, or conflict with local growing windows in another.

This tool bridges raw satellite telemetry and practical farm management by:
1. **Diagnosing field-level climate and moisture vulnerabilities** using the selected historical NASA data period.
2. **Dynamically resolving any farmer-entered crop** against peer-reviewed ecological thresholds.
3. **Comparing 3 transparent rotation strategies** (the farmer's existing baseline plus two climate- and soil-optimized alternatives) with clear evidence, benefits, and local review flags.

---

## 🛠️ Data Sources & Fusion Pipeline

### 1. NASA Earth Observations (`NASA POWER Agroclimatology API`)
For any field location selected on the interactive map, the system pulls monthly NASA POWER data for 2015–2024 and calculates averages over a user-selected 3–10-year period (10 years by default). It reports the date range used and surfaces incomplete coverage rather than silently shortening the averaging period.
- **Temperature & Frost Risk (`T2M`, `T2M_MAX`, `T2M_MIN`):** Identifies frost-free growing windows and extreme heat peaks (`>30°C`).
- **Precipitation & Water Balance (`PRECTOTCORR`, `EVPTRNS`):** Calculates monthly rainfall surpluses/deficits and flags heavy winter precipitation windows where bare soil is vulnerable to erosion.
- **Root-Zone Soil Moisture & Long-Term Water Trends (`GWETROOT`):** Tracks seasonal root-zone wetness and computes the selected-period linear trend (`stable` vs. `declining`) to guard against water depletion.
- **Vegetation Stress Proxy:** Combines root-zone moisture deficits with thermal heat stress to pinpoint periods of peak canopy vulnerability.

### 2. Agronomic Knowledge Base (`UN FAO EcoCrop`)
Rather than relying on a small static list of crops, the app queries the open **FAO EcoCrop Parquet dataset (2,568+ species)** to extract:
- **Ripening Cycle (`gmin`, `gmax`):** Average days to maturity to ensure crops fit within local seasonal windows.
- **Cycle Water Demand (`ropmn`, `ropmx`):** Annual optimal rainfall scaled to the crop's actual growing cycle.
- **Thermal & Frost Thresholds (`topmn`, `topmx`, `tmin`):** Detects mismatches between summer heat spikes or winter frosts and crop tolerances.
- **Botanical Family (`famname`):** Identifies consecutive plantings from the same plant family (e.g., *Poaceae* or *Fabaceae*) to prevent pest and pathogen carryover, while rewarding nitrogen-fixing legumes.

---

## ⚙️ Multi-Criteria Rotation Scoring Engine (`optimizer.py`)

Every candidate rotation sequence is evaluated across four normalized sub-scores (`0–100`):

1. **Water Resilience:** Compares crop cycle water requirements against local seasonal rainfall, root-zone soil moisture, and selected-period water storage trends.
2. **Heat & Ripening Fit:** Penalizes rotations where sensitive growth stages overlap with peak summer temperatures, frost windows, or overly long maturation cycles.
3. **Soil Health & Erosion Protection:** Penalizes bare `Fallow` periods during wet winter months and rewards living cover crops and nitrogen-fixing legumes.
4. **Pest-Cycle Disruption:** Rewards rotating across distinct botanical families between seasons.

### Output Strategies
- **Strategy 1 — Current Baseline Rotation:** Evaluates the farmer's existing sequence and highlights satellite-detected vulnerabilities.
- **Strategy 2 — Water & Heat Resilience Strategy:** Maximizes water efficiency and thermal tolerance for drought- or heat-stressed regions.
- **Strategy 3 — Soil Health & Erosion-Control Strategy:** Maximizes living ground cover, nitrogen fixation, and botanical diversity.

---

## 📁 Project Structure

```text
crop-rotation-advisor/
├── app.py              # Streamlit UI: interactive satellite map, inputs, charts & 3-strategy cards
├── data_fetcher.py     # NASA POWER API client & FAO EcoCrop resolver/screener
├── optimizer.py        # Multi-criteria sequence generator & explainable scoring engine
├── requirements.txt    # Python dependencies
└── README.md           # Project documentation