
import os
import re
import requests
import pandas as pd
import numpy as np
 
ECOCROP_PARQUET_URL = "https://digital-atlas.s3.amazonaws.com/cdh/data/ecocrop/ecocrop.parquet"
LOCAL_ECOCROP_CACHE = "ecocrop_2568.parquet"
 
# Valid crop name: letters only (accents allowed), words separated by a single
# space, hyphen or apostrophe. No digits, brackets, slashes, commas, symbols.
_VALID_CROP_NAME = re.compile(r"[^\W\d_]+(?:[ '\-][^\W\d_]+)*")
 
 
# =====================================================================
# 1. FAO ECOCROP LOADER & CROP PARAMETER RESOLVER
# =====================================================================
 
def get_ecocrop_dataframe() -> pd.DataFrame:
    """
    Downloads and caches the FAO EcoCrop dataset (2,568 species)
    from CGIAR's Climate Action Data Hub.
    """
    if os.path.exists(LOCAL_ECOCROP_CACHE):
        return pd.read_parquet(LOCAL_ECOCROP_CACHE)
 
    df = pd.read_parquet(ECOCROP_PARQUET_URL)
    df.to_parquet(LOCAL_ECOCROP_CACHE, index=False)
    return df
 
 
def _flatten_list_field(val) -> str:
    """Safely joins list/array columns (comname, syno, use) into a string."""
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return ""
    if isinstance(val, (list, np.ndarray)):
        return ", ".join(str(x).strip() for x in val if x is not None)
    return str(val).strip()
 
 
def _format_crop_name(name: str) -> str:
    """Capitalizes each word without the str.title() apostrophe bug ("Farmer'S")."""
    words = str(name).strip().split(" ")
    return " ".join(w[:1].upper() + w[1:].lower() for w in words if w)
 
 
def _is_valid_crop_name(name: str) -> bool:
    """True only for real-looking crop names (3-30 chars, letters/space/-/')."""
    name = name.strip()
    return 2 < len(name) <= 30 and _VALID_CROP_NAME.fullmatch(name) is not None
 
 
def _valid_common_names(val) -> list[str]:
    """Returns the cleaned, formatted, valid common names from a comname cell."""
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return []
    items = val if isinstance(val, (list, np.ndarray)) else [val]
    result = []
    for item in items:
        if item is None:
            continue
        raw = str(item).strip()
        if _is_valid_crop_name(raw):
            result.append(_format_crop_name(raw))
    return result
 
 
def get_all_common_crop_names(ecocrop_df: pd.DataFrame) -> list[str]:
    """Extracts a clean, sorted list of real common crop names for UI autocomplete."""
    names = set()
    for val in ecocrop_df["comname"].dropna():
        names.update(_valid_common_names(val))
    return sorted(names)
 
 
def get_crop_profile_from_ecocrop(crop_query: str, ecocrop_df: pd.DataFrame) -> dict:
    """
    Searches FAO EcoCrop by common name, synonym, or scientific name,
    and converts its raw ecological thresholds into our optimizer's schema.
    Falls back to a conservative agronomic default if an obscure crop isn't matched.
    """
    q = crop_query.strip().lower()
    if not q or q == "fallow":
        return {
            "name": "Fallow",
            "scientific_name": "Bare Soil",
            "family": "None",
            "season": "Any",
            "ripening_days": 180,
            "cycle_water_need_mm": 0.0,
            "water_demand": "none",
            "opt_temp_min_c": -20.0,
            "heat_tolerance_c": 50.0,
            "abs_min_temp_c": -30.0,
            "frost_hardy": True,
            "nitrogen_impact": -10,
            "erosion_protection": 0.1,
            "source": "Baseline Management State"
        }
 
    search_series = (
        ecocrop_df["comname"].apply(_flatten_list_field).str.lower() + " | " +
        ecocrop_df["syno"].apply(_flatten_list_field).str.lower() + " | " +
        ecocrop_df["scientificname"].fillna("").str.lower()
    )
 
    matches = ecocrop_df[search_series.str.contains(rf"\b{re.escape(q)}\b", regex=True, na=False)]
    if matches.empty:
        matches = ecocrop_df[search_series.str.contains(q, regex=False, na=False)]
 
    # Safe fallback if user enters a custom/local crop name not in EcoCrop
    if matches.empty:
        return {
            "name": _format_crop_name(crop_query),
            "scientific_name": "Unmatched / Local Cultivar",
            "family": "Unknown",
            "season": "Warm",
            "ripening_days": 115,
            "cycle_water_need_mm": 350.0,
            "water_demand": "medium",
            "opt_temp_min_c": 15.0,
            "heat_tolerance_c": 33.0,
            "abs_min_temp_c": 2.0,
            "frost_hardy": False,
            "nitrogen_impact": -15,
            "erosion_protection": 0.5,
            "source": "Default Estimate (Verify Locally)"
        }
 
    matches = matches.copy()
    matches["completeness"] = matches[["gmin", "gmax", "topmn", "topmx", "ropmn"]].notna().sum(axis=1)
    row = matches.sort_values("completeness", ascending=False).iloc[0]
 
    gmin = row["gmin"] if pd.notna(row["gmin"]) else 90
    gmax = row["gmax"] if pd.notna(row["gmax"]) else gmin + 30
    ripening_days = int(np.clip(np.mean([gmin, gmax]), 30, 365))
 
    annual_opt_rain = np.nanmean([row["ropmn"], row["ropmx"]]) if pd.notna(row["ropmn"]) else 600.0
    cycle_water_need_mm = annual_opt_rain * (ripening_days / 365.0)
 
    if cycle_water_need_mm > 450:
        water_demand = "high"
    elif cycle_water_need_mm > 220:
        water_demand = "medium"
    else:
        water_demand = "low"
 
    topmx = float(row["topmx"]) if (pd.notna(row["topmx"]) and row["topmx"] < 55) else 32.0
    topmn = float(row["topmn"]) if (pd.notna(row["topmn"]) and row["topmn"] < 55) else 15.0
    tmin = float(row["tmin"]) if pd.notna(row["tmin"]) else 2.0
    frost_hardy = bool(tmin <= 0.0)
    season = "Cool" if (frost_hardy or topmn <= 14.0) else "Warm"
 
    family = str(row["famname"]).strip() if pd.notna(row["famname"]) else "Unknown"
    uses = _flatten_list_field(row.get("use", "")).lower()
    is_legume = any(leg in family.lower() for leg in ["fabaceae", "leguminosae"])
 
    return {
        "name": _format_crop_name(crop_query),
        "ecoport_code": int(row["ecoportcode"]) if pd.notna(row["ecoportcode"]) else None,
        "scientific_name": str(row["scientificname"]),
        "family": family,
        "season": season,
        "ripening_days": ripening_days,
        "cycle_water_need_mm": round(float(cycle_water_need_mm), 1),
        "water_demand": water_demand,
        "opt_temp_min_c": topmn,
        "heat_tolerance_c": topmx,
        "abs_min_temp_c": tmin,
        "frost_hardy": frost_hardy,
        "nitrogen_impact": 35 if is_legume else -25,
        "erosion_protection": 0.85 if ("forage" in uses or "cover" in uses) else 0.5,
        "source": f"FAO EcoCrop (ID: {row['ecoportcode']})"
    }
 
 
def get_climate_compatible_candidates(
    climate_df: pd.DataFrame,
    ecocrop_df: pd.DataFrame,
    limit: int = 12
) -> dict[str, dict]:
    """
    Screens FAO EcoCrop against the location's NASA POWER temperature and rainfall
    envelope to build a pool of region-suitable Warm & Cool season candidate crops.
    """
    local_warm_temp = climate_df[climate_df["month"].isin([5, 6, 7, 8, 9])]["temp_avg"].mean()
    local_annual_rain = climate_df["precip_mm"].sum()
 
    valid = ecocrop_df.dropna(subset=["comname", "famname", "topmn", "topmx", "ropmn", "ropmx", "gmin"]).copy()
    valid = valid[
        (valid["topmn"] <= local_warm_temp) &
        (valid["topmx"] >= local_warm_temp - 2) &
        (valid["ropmn"] <= local_annual_rain * 1.3) &
        (valid["ropmx"] >= local_annual_rain * 0.5) &
        (valid["gmin"] <= 210)
    ]
 
    # Prioritize agronomic staples & cover crops first, then fill from filtered EcoCrop
    seed_staples = ["Sorghum", "Soybean", "Winter Wheat", "Barley", "Alfalfa", "Crimson Clover", "Oats", "Chickpea", "Sunflower"]
    candidates = {}
 
    for staple in seed_staples:
        prof = get_crop_profile_from_ecocrop(staple, ecocrop_df)
        if prof["source"].startswith("FAO EcoCrop"):
            candidates[prof["name"]] = prof
 
    for _, row in valid.head(limit * 4).iterrows():
        if len(candidates) >= limit:
            break
        # Use the first *valid* common name (skips junk entries with symbols/digits)
        names = [n for n in _valid_common_names(row["comname"]) if len(n) <= 22]
        if not names:
            continue
        profile = get_crop_profile_from_ecocrop(names[0], ecocrop_df)
        if profile["name"] not in candidates:
            candidates[profile["name"]] = profile
 
    candidates["Fallow"] = get_crop_profile_from_ecocrop("Fallow", ecocrop_df)
    return candidates
 
 
# =====================================================================
# 2. NASA POWER TELEMETRY FETCHER
# =====================================================================
 
NASA_CLIMATE_START_YEAR = 2015
NASA_CLIMATE_END_YEAR = 2024

NASA_CLIMATE_PARAMETERS = {
    "T2M": "temp_avg",
    "T2M_MAX": "temp_max",
    "T2M_MIN": "temp_min",
    "PRECTOTCORR": "precip_mm",
    "GWETROOT": "soil_moisture",
    "EVPTRNS": "evapotrans",
}


def _parse_power_value(value) -> float:
    if value is None:
        return np.nan
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return np.nan
    return np.nan if not np.isfinite(parsed) or parsed == -999 else parsed


def fetch_nasa_climate_data(
    lat: float,
    lon: float,
    start_year: int = NASA_CLIMATE_START_YEAR,
    end_year: int = NASA_CLIMATE_END_YEAR,
) -> pd.DataFrame:
    """Fetch raw monthly NASA POWER observations for the requested year range."""
    if start_year > end_year:
        raise ValueError("The climate data start year must not exceed the end year.")

    url = "https://power.larc.nasa.gov/api/temporal/monthly/point"
    params = {
        "parameters": ",".join(NASA_CLIMATE_PARAMETERS),
        "community": "AG",
        "longitude": lon,
        "latitude": lat,
        "start": start_year,
        "end": end_year,
        "format": "JSON"
    }
 
    resp = requests.get(url, params=params, timeout=20)
    resp.raise_for_status()
    response_data = resp.json()
    properties = response_data.get("properties") if isinstance(response_data, dict) else None
    parameter_data = properties.get("parameter") if isinstance(properties, dict) else None
    if not isinstance(parameter_data, dict):
        raise ValueError("NASA POWER response did not contain climate parameter data.")
 
    records = []
    for year in range(start_year, end_year + 1):
        for month in range(1, 13):
            year_month = f"{year}{month:02d}"
            record = {"year": year, "month": month}
            for parameter, column in NASA_CLIMATE_PARAMETERS.items():
                values = parameter_data.get(parameter, {})
                value = _parse_power_value(values.get(year_month)) if isinstance(values, dict) else np.nan
                if column == "precip_mm" and pd.notna(value):
                    value *= 30.4
                record[column] = value
            records.append(record)

    return pd.DataFrame(records)


def aggregate_nasa_climate_profile(
    climate_data: pd.DataFrame,
    start_year: int,
    end_year: int,
) -> pd.DataFrame:
    """Average complete monthly climate observations and derive stress indicators."""
    if start_year > end_year:
        raise ValueError("The climate data start year must not exceed the end year.")

    required_columns = list(NASA_CLIMATE_PARAMETERS.values())
    missing_columns = sorted(set(required_columns) - set(climate_data.columns))
    if missing_columns:
        raise ValueError(
            "Climate data is missing required variables: " + ", ".join(missing_columns)
        )

    selected = climate_data[
        climate_data["year"].between(start_year, end_year)
    ].copy()
    if selected.duplicated(["year", "month"]).any():
        raise ValueError(
            f"Climate data contains duplicate monthly observations for {start_year}-{end_year}."
        )

    expected_months = {
        (year, month)
        for year in range(start_year, end_year + 1)
        for month in range(1, 13)
    }
    available_months = set(zip(selected["year"], selected["month"]))
    missing_months = sorted(expected_months - available_months)
    problems = []
    if missing_months:
        listed_months = ", ".join(
            f"{year}-{month:02d}" for year, month in missing_months[:6]
        )
        if len(missing_months) > 6:
            listed_months += ", ..."
        problems.append(f"missing monthly observations: {listed_months}")

    for column in required_columns:
        values = pd.to_numeric(selected[column], errors="coerce")
        invalid_mask = ~np.isfinite(values.to_numpy(dtype=float))
        invalid_months = selected.loc[invalid_mask, ["year", "month"]]
        if not invalid_months.empty:
            listed_months = ", ".join(
                f"{int(row.year)}-{int(row.month):02d}"
                for row in invalid_months.head(6).itertuples(index=False)
            )
            if len(invalid_months) > 6:
                listed_months += ", ..."
            problems.append(f"{column} unavailable for {listed_months}")
        selected[column] = values

    if problems:
        details = "; ".join(problems)
        raise ValueError(
            f"Incomplete NASA POWER climate data for {start_year}-{end_year}: {details}."
        )

    monthly = selected.groupby("month").agg(
        temp_avg=("temp_avg", "mean"),
        temp_max=("temp_max", "mean"),
        temp_min=("temp_min", "mean"),
        precip_mm=("precip_mm", "mean"),
        soil_moisture=("soil_moisture", "mean"),
        evapotrans=("evapotrans", "mean")
    ).reset_index()
 
    # Derived stress indicators
    monthly["heat_stress_risk"] = np.clip((monthly["temp_max"] - 30.0) / 10.0, 0, 1)
    monthly["frost_risk"] = (monthly["temp_min"] < 2.0).astype(float)
    monthly["water_balance"] = monthly["precip_mm"] - (monthly["evapotrans"] * 30.4)
    monthly["veg_stress_index"] = np.clip((1.0 - monthly["soil_moisture"]) * monthly["heat_stress_risk"], 0, 1)
 
    annual_sm = selected.groupby("year")["soil_moisture"].mean()
    slope = np.polyfit(annual_sm.index, annual_sm.values, 1)[0]
    monthly["long_term_water_trend"] = "declining" if slope < -0.002 else "stable"
 
    return monthly


def fetch_nasa_climate_profile(
    lat: float,
    lon: float,
    start_year: int = NASA_CLIMATE_START_YEAR,
    end_year: int = NASA_CLIMATE_END_YEAR,
) -> pd.DataFrame:
    """
    Fetches monthly NASA POWER climate data and computes period-specific averages
    and seasonal stress indicators.
    """
    climate_data = fetch_nasa_climate_data(lat, lon, start_year, end_year)
    return aggregate_nasa_climate_profile(climate_data, start_year, end_year)
 