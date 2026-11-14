import streamlit as st
import pandas as pd
import plotly.express as px
from data_fetcher import (
    get_ecocrop_dataframe,
    get_all_common_crop_names,
    get_crop_profile_from_ecocrop,
    get_climate_compatible_candidates,
    fetch_nasa_climate_profile,
)
from optimizer import generate_three_strategies

st.set_page_config(page_title="NASA Crop Rotation Advisor", layout="wide")
st.title("🛰️ Satellite-Guided Crop Rotation Decision Support")
st.caption("Combining 10-Year NASA POWER Climate & Soil Moisture Telemetry with UN FAO EcoCrop Agronomic Data")


@st.cache_data(show_spinner="Loading FAO EcoCrop database (2,568 species)...")
def load_cached_ecocrop():
    df = get_ecocrop_dataframe()
    names = get_all_common_crop_names(df)
    return df, names


@st.cache_data(show_spinner="Fetching 10-year NASA POWER satellite telemetry...")
def load_cached_nasa(lat: float, lon: float):
    return fetch_nasa_climate_profile(lat, lon)


ecocrop_df, common_names = load_cached_ecocrop()

# --- SIDEBAR: FARMER INPUTS ---
with st.sidebar:
    st.header("1. Farm Location & Horizon")
    lat = st.number_input("Latitude", value=45.4642, format="%.4f", help="Default: Po Valley, Italy")
    lon = st.number_input("Longitude", value=9.1900, format="%.4f")
    years = st.slider("Rotation Time Interval (Years)", min_value=1, max_value=3, value=2)

    st.header("2. Select Up to 4 Crops")
    st.caption("Choose from 2,500+ FAO EcoCrop species or type a custom crop name.")
    default_crops = ["Maize", "Soybean", "Winter Wheat", "Alfalfa"]
    farmer_crops = []
    for i in range(4):
        crop_input = st.selectbox(
            f"Crop Type {i + 1}",
            options=[""] + common_names,
            index=(common_names.index(default_crops[i]) + 1) if default_crops[i] in common_names else 0,
            key=f"crop_choice_{i}"
        )
        custom_override = st.text_input(
            f"Or type custom name for Crop {i + 1}",
            value="",
            key=f"custom_{i}",
            label_visibility="collapsed",
            placeholder="Optional custom crop name..."
        )
        chosen = custom_override.strip() if custom_override.strip() else crop_input
        if chosen:
            farmer_crops.append(chosen)

    st.header("3. Existing Seasonal Sequence")
    slot_options = list(dict.fromkeys(farmer_crops + ["Fallow"]))
    existing_sequence = []
    for s in range(years * 2):
        season_name = "Spring/Summer" if s % 2 == 0 else "Fall/Winter"
        default_slot = (
            farmer_crops[s % len(farmer_crops)]
            if (s % 2 == 0 and farmer_crops)
            else ("Fallow" if "Fallow" in slot_options else slot_options[0])
        )
        sel = st.selectbox(
            f"Year {s // 2 + 1} ({season_name})",
            options=slot_options,
            index=slot_options.index(default_slot),
            key=f"seq_slot_{s}"
        )
        existing_sequence.append(sel)

# --- FETCH TELEMETRY & RESOLVE CROPS ---
climate_df = load_cached_nasa(lat, lon)
dynamic_crop_db = get_climate_compatible_candidates(climate_df, ecocrop_df, limit=12)

resolved_profiles = []
for c in set(farmer_crops + existing_sequence):
    prof = get_crop_profile_from_ecocrop(c, ecocrop_df)
    dynamic_crop_db[prof["name"]] = prof
    resolved_profiles.append(prof)

strategies = generate_three_strategies(existing_sequence, climate_df, dynamic_crop_db)

# --- TOP KPI METRICS ---
water_trend = climate_df["long_term_water_trend"].iloc[0].upper()
annual_rain = climate_df["precip_mm"].sum()
peak_heat = climate_df["temp_max"].max()
summer_sm = climate_df[climate_df["month"].isin([6, 7, 8])]["soil_moisture"].mean()

m1, m2, m3, m4 = st.columns(4)
m1.metric("Annual Precipitation", f"{annual_rain:.0f} mm")
m2.metric("Peak Summer Max Temp", f"{peak_heat:.1f} °C")
m3.metric("Summer Root-Zone Moisture", f"{summer_sm:.2f} (0–1)")
m4.metric("10-Yr Water Storage Trend", water_trend)

# --- TELEMETRY CHARTS ---
with st.expander("📈 View 10-Year NASA Climate, Moisture & Stress Curves", expanded=True):
    c1, c2 = st.columns(2)
    with c1:
        fig_temp = px.line(
            climate_df, x="month", y=["temp_max", "temp_avg", "temp_min"],
            title="Monthly Temperature Envelope (°C)",
            labels={"value": "Temperature (°C)", "month": "Month"}
        )
        st.plotly_chart(fig_temp, use_container_width=True)
    with c2:
        fig_water = px.bar(
            climate_df, x="month", y="precip_mm",
            title="Monthly Precipitation (mm) & Water Balance",
            labels={"precip_mm": "Precipitation (mm)", "month": "Month"}
        )
        st.plotly_chart(fig_water, use_container_width=True)

# --- RESOLVED ECOCROP PARAMETERS TABLE ---
with st.expander("🌿 Resolved Crop Agronomic Profiles (FAO EcoCrop Lookup)", expanded=False):
    st.dataframe(
        pd.DataFrame(resolved_profiles)[
            ["name", "scientific_name", "family", "season", "ripening_days", "cycle_water_need_mm", "heat_tolerance_c", "frost_hardy", "source"]
        ],
        use_container_width=True
    )

# --- 3-STRATEGY COMPARISON CARDS ---
st.subheader("🌱 Recommended 3-Strategy Rotation Comparison")
cols = st.columns(3)

for col, strat in zip(cols, strategies):
    with col:
        st.markdown(f"### {strat['strategy_name']}")
        st.metric("Overall Resilience Score", f"{strat['scores']['overall']} / 100")

        formatted_seq = [
            f"**Y{i // 2 + 1} {'Warm' if i % 2 == 0 else 'Cool'}:** {crop}"
            for i, crop in enumerate(strat["sequence"])
        ]
        st.markdown(" → ".join(formatted_seq))

        st.write("**Sub-Scores:**")
        st.progress(int(strat["scores"]["water_resilience"]), text=f"Water Resilience: {strat['scores']['water_resilience']}")
        st.progress(int(strat["scores"]["soil_health"]), text=f"Soil Health: {strat['scores']['soil_health']}")
        st.progress(int(strat["scores"]["heat_fit"]), text=f"Heat & Ripening Fit: {strat['scores']['heat_fit']}")
        st.progress(int(strat["scores"]["pest_break"]), text=f"Pest-Cycle Break: {strat['scores']['pest_break']}")

        st.success("**Satellite & Agronomic Evidence:**\n" + "\n".join(f"- {e}" for e in strat["evidence"]))
        st.warning("**Local Review & Risk Flags:**\n" + "\n".join(f"- {r}" for r in strat["risks"]))

st.info(
    "ℹ️ **Human-in-the-Loop Guidance:** Satellite telemetry captures regional climate and moisture patterns, "
    "while FAO EcoCrop provides species-level thresholds. Always review soil pH, sub-surface drainage, "
    "equipment compatibility, and local market demand with an agronomist before planting."
)