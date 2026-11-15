import streamlit as st
import pandas as pd
import plotly.express as px
import folium
from streamlit_folium import st_folium
from data_fetcher import (
    get_ecocrop_dataframe,
    get_all_common_crop_names,
    get_crop_profile_from_ecocrop,
    get_climate_compatible_candidates,
    fetch_nasa_climate_profile,
)
from optimizer import SCORE_KEYS, generate_three_strategies

st.set_page_config(page_title="NASA Crop Rotation Advisor", layout="wide")
st.title("🛰️ Satellite-Guided Crop Rotation Decision Support")
st.caption("Combining 10-Year NASA POWER Climate & Soil Moisture Telemetry with UN FAO EcoCrop Agronomic Data")

PRIORITY_LABELS = {
    "water_resilience": "Water conservation (%)",
    "heat_fit": "Heat & climate fit (%)",
    "soil_health": "Soil health (%)",
    "pest_break": "Pest-cycle break (%)",
}
PRIORITY_PRESETS = {
    "Balanced": {
        "water_resilience": 25.0,
        "heat_fit": 25.0,
        "soil_health": 25.0,
        "pest_break": 25.0,
    },
    "Water Conservation": {
        "water_resilience": 50.0,
        "heat_fit": 15.0,
        "soil_health": 20.0,
        "pest_break": 15.0,
    },
    "Soil Health": {
        "water_resilience": 15.0,
        "heat_fit": 15.0,
        "soil_health": 55.0,
        "pest_break": 15.0,
    },
    "Climate Resilience": {
        "water_resilience": 30.0,
        "heat_fit": 35.0,
        "soil_health": 15.0,
        "pest_break": 20.0,
    },
}
CUSTOM_PRIORITY = "Custom"


def apply_priority_preset():
    preset = st.session_state.priority_preset
    if preset in PRIORITY_PRESETS:
        weights = PRIORITY_PRESETS[preset]
        st.session_state.priority_weights = dict(weights)
        for key in SCORE_KEYS:
            st.session_state[f"priority_weight_{key}"] = weights[key]


def update_custom_priority_weights():
    weights = {
        key: st.session_state[f"priority_weight_{key}"]
        for key in SCORE_KEYS
    }
    st.session_state.priority_weights = weights
    st.session_state.priority_preset = CUSTOM_PRIORITY


# Initialize persistent coordinates in session state (Default: Po Valley, Italy)
if "lat" not in st.session_state:
    st.session_state.lat = 45.4642
if "lon" not in st.session_state:
    st.session_state.lon = 9.1900
if "coordinate_lat" not in st.session_state:
    st.session_state.coordinate_lat = st.session_state.lat
if "coordinate_lon" not in st.session_state:
    st.session_state.coordinate_lon = st.session_state.lon
if "last_map_click" not in st.session_state:
    st.session_state.last_map_click = None
if "priority_preset" not in st.session_state:
    st.session_state.priority_preset = "Balanced"
if "priority_weights" not in st.session_state:
    st.session_state.priority_weights = dict(PRIORITY_PRESETS["Balanced"])
for priority_key in SCORE_KEYS:
    widget_key = f"priority_weight_{priority_key}"
    if widget_key not in st.session_state:
        st.session_state[widget_key] = PRIORITY_PRESETS["Balanced"][priority_key]


def set_location(lat: float, lon: float):
    st.session_state.lat = lat
    st.session_state.lon = lon
    st.session_state.coordinate_lat = lat
    st.session_state.coordinate_lon = lon


def update_location_from_coordinates():
    set_location(
        round(st.session_state.coordinate_lat, 4),
        round(st.session_state.coordinate_lon, 4),
    )


@st.cache_data(show_spinner="Loading FAO EcoCrop database (2,568 species)...")
def load_cached_ecocrop():
    df = get_ecocrop_dataframe()
    names = get_all_common_crop_names(df)
    return df, names


@st.cache_data(show_spinner="Fetching 10-year NASA POWER satellite telemetry...")
def load_cached_nasa(lat: float, lon: float):
    return fetch_nasa_climate_profile(lat, lon)


ecocrop_df, common_names = load_cached_ecocrop()

# --- SIDEBAR: ROTATION & CROP INPUTS ---
with st.sidebar:
    st.header("1. Rotation Horizon")
    years = st.slider("Time Interval (Years)", min_value=1, max_value=3, value=2)

    st.header("2. Select Up to 4 Crops")
    st.caption("Choose from 2,500+ FAO EcoCrop species.")
    default_crops = ["Maize", "Soybean", "Winter Wheat", "Alfalfa"]
    farmer_crops = []
    for i in range(4):
        crop_input = st.selectbox(
            f"Crop Type {i + 1}",
            options=[""] + common_names,
            index=(common_names.index(default_crops[i]) + 1) if default_crops[i] in common_names else 0,
            key=f"crop_choice_{i}"
        )
        if crop_input:
            farmer_crops.append(crop_input)

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

# --- INTERACTIVE MAP PICKER ---
st.subheader("📍 Step 1: Choose Your Field Location")
st.caption("Click the map or enter decimal-degree coordinates.")
map_col, info_col = st.columns([3, 1])

with map_col:
    m = folium.Map(
        location=[st.session_state.lat, st.session_state.lon],
        zoom_start=11,
        tiles="OpenStreetMap"
    )
    # Add Satellite Imagery layer so farmers can visually identify their fields
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri World Imagery",
        name="Satellite View",
        overlay=False,
        control=True
    ).add_to(m)
    folium.LayerControl().add_to(m)

    # Pin at currently selected coordinates
    folium.Marker(
        [st.session_state.lat, st.session_state.lon],
        popup=f"Selected Field ({st.session_state.lat:.4f}, {st.session_state.lon:.4f})",
        icon=folium.Icon(color="green", icon="leaf", prefix="fa")
    ).add_to(m)

    # Render map and capture clicks
    map_data = st_folium(m, height=350, use_container_width=True, key="field_picker_map")

    if map_data and map_data.get("last_clicked"):
        clicked_lat = round(map_data["last_clicked"]["lat"], 4)
        clicked_lon = round(map_data["last_clicked"]["lng"], 4)
        clicked_location = (clicked_lat, clicked_lon)
        if clicked_location != st.session_state.last_map_click:
            st.session_state.last_map_click = clicked_location
            if clicked_lat != st.session_state.lat or clicked_lon != st.session_state.lon:
                set_location(clicked_lat, clicked_lon)
                st.rerun()

with info_col:
    st.number_input(
        "Latitude",
        min_value=-90.0,
        max_value=90.0,
        step=0.0001,
        format="%.4f",
        key="coordinate_lat",
        on_change=update_location_from_coordinates,
    )
    st.number_input(
        "Longitude",
        min_value=-180.0,
        max_value=180.0,
        step=0.0001,
        format="%.4f",
        key="coordinate_lon",
        on_change=update_location_from_coordinates,
    )
    st.caption("💡 Switch the map to Satellite View to identify your field.")

# --- FETCH TELEMETRY & RESOLVE CROPS ---
climate_df = load_cached_nasa(st.session_state.lat, st.session_state.lon)
dynamic_crop_db = get_climate_compatible_candidates(climate_df, ecocrop_df, limit=12)

resolved_profiles = []
for c in set(farmer_crops + existing_sequence):
    prof = get_crop_profile_from_ecocrop(c, ecocrop_df)
    dynamic_crop_db[c] = prof
    resolved_profiles.append(prof)

# --- TOP KPI METRICS ---
st.divider()
water_trend = climate_df["long_term_water_trend"].iloc[0].upper()
annual_rain = climate_df["precip_mm"].sum()
peak_heat = climate_df["temp_max"].max()
summer_sm = climate_df[climate_df["month"].isin([6, 7, 8])]["soil_moisture"].mean()

m1, m2, m3, m4 = st.columns(4)
m1.metric("Annual Precipitation", f"{annual_rain:.0f} mm")
m2.metric("Peak Summer Max Temp", f"{peak_heat:.1f} °C")
m3.metric("Summer Root-Zone Moisture", f"{summer_sm:.2f} (0–1)")
m4.metric("10-Yr Water Storage Trend", water_trend)

# --- FARMER PRIORITIES ---
st.selectbox(
    "Farmer priorities",
    options=[*PRIORITY_PRESETS, CUSTOM_PRIORITY],
    key="priority_preset",
    on_change=apply_priority_preset,
)

with st.expander("Customize", expanded=False):
    weight_cols = st.columns(2)
    for index, key in enumerate(SCORE_KEYS):
        with weight_cols[index % 2]:
            st.number_input(
                PRIORITY_LABELS[key],
                min_value=0.0,
                max_value=100.0,
                step=0.1,
                format="%.1f",
                key=f"priority_weight_{key}",
                on_change=update_custom_priority_weights,
            )
    st.caption("Values are normalized only when calculating scores. A value of 0 excludes that criterion.")

strategies = generate_three_strategies(
    existing_sequence,
    climate_df,
    dynamic_crop_db,
    st.session_state.priority_weights,
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

# --- SUPPORTING CLIMATE & CROP DATA ---
st.markdown("#### Explore supporting data")
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

with st.expander("🌿 Resolved Crop Agronomic Profiles (FAO EcoCrop Lookup)", expanded=False):
    st.dataframe(
        pd.DataFrame(resolved_profiles)[
            ["name", "scientific_name", "family", "season", "ripening_days", "cycle_water_need_mm", "heat_tolerance_c", "frost_hardy", "source"]
        ],
        use_container_width=True
    )

st.markdown(
    """
    <style>
    .fieldshift-footer {
        margin-top: 1.1rem;
        padding-top: 0.9rem;
        border-top: 1px solid rgba(128, 128, 128, 0.28);
        color: var(--text-color);
    }
    .fieldshift-footer .footer-disclaimer {
        display: flex;
        align-items: flex-start;
        gap: 0.55rem;
        padding: 0.65rem 0.8rem;
        border-radius: 0.35rem;
        background: var(--secondary-background-color);
        font-size: 0.8rem;
        line-height: 1.5;
        opacity: 0.88;
    }
    .fieldshift-footer .footer-info-icon {
        flex: 0 0 auto;
        opacity: 0.7;
    }
    .fieldshift-footer .footer-disclaimer p,
    .fieldshift-footer .footer-project-name,
    .fieldshift-footer .footer-credit {
        margin: 0;
    }
    .fieldshift-footer .footer-columns {
        display: grid;
        grid-template-columns: minmax(0, 0.85fr) minmax(0, 1.5fr);
        gap: 1.5rem;
        margin-top: 0.95rem;
    }
    .fieldshift-footer .footer-label {
        margin: 0 0 0.35rem;
        font-size: 0.68rem;
        font-weight: 600;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        opacity: 0.62;
    }
    .fieldshift-footer .footer-project-name {
        margin-bottom: 0.2rem;
        font-size: 0.9rem;
        font-weight: 600;
    }
    .fieldshift-footer .footer-credit {
        font-size: 0.76rem;
        line-height: 1.45;
        opacity: 0.72;
    }
    .fieldshift-footer .footer-sources {
        display: flex;
        flex-wrap: wrap;
        gap: 0.35rem 0.45rem;
    }
    .fieldshift-footer .footer-source {
        padding: 0.16rem 0.45rem;
        border-radius: 0.25rem;
        background: var(--secondary-background-color);
        font-size: 0.72rem;
        line-height: 1.4;
        opacity: 0.78;
    }
    @media (max-width: 640px) {
        .fieldshift-footer .footer-columns {
            grid-template-columns: minmax(0, 1fr);
            gap: 0.8rem;
        }
    }
    </style>
    <footer class="fieldshift-footer" aria-label="FieldShift disclaimer and credits">
        <div class="footer-disclaimer">
            <span class="footer-info-icon" aria-hidden="true">&#9432;</span>
            <p>FieldShift provides informational decision support, not definitive agricultural recommendations.
            Its outputs should always be evaluated alongside local conditions and farming practices.
            Farmers' knowledge, experience, and understanding of their land take priority over the tool's suggestions.</p>
        </div>
        <div class="footer-columns">
            <section>
                <h2 class="footer-label">Project</h2>
                <p class="footer-project-name">FieldShift</p>
                <p class="footer-credit">Developed by Team Ranpo<br>Team member: ranpo</p>
            </section>
            <section>
                <h2 class="footer-label">Data &amp; Acknowledgements</h2>
                <div class="footer-sources">
                    <span class="footer-source">NASA POWER</span>
                    <span class="footer-source">UN FAO EcoCrop</span>
                    <span class="footer-source">CGIAR Climate Action Data Hub</span>
                    <span class="footer-source">OpenStreetMap</span>
                    <span class="footer-source">Esri World Imagery</span>
                </div>
            </section>
        </div>
    </footer>
    """,
    unsafe_allow_html=True,
)