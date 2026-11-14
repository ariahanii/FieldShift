import pandas as pd
import traceback

from data_fetcher import (
    get_ecocrop_dataframe,
    get_all_common_crop_names,
    get_crop_profile_from_ecocrop,
    get_climate_compatible_candidates,
    fetch_nasa_climate_profile,
)

from optimizer import generate_three_strategies

print("\n========== ECOCROP TEST ==========")

try:
    eco = get_ecocrop_dataframe()

    print("Dataset shape:", eco.shape)
    print("Columns:", eco.columns.tolist())

    names = get_all_common_crop_names(eco)
    print("Common crop count:", len(names))
    print("Examples:", names[:20])

    for crop in ["Maize", "Soybean", "Winter Wheat", "Alfalfa"]:
        profile = get_crop_profile_from_ecocrop(crop, eco)
        print(f"\n{crop}:")
        print(profile)

except Exception:
    print("ECOCROP ERROR:")
    traceback.print_exc()
    raise

print("\n========== NASA POWER TEST ==========")

try:
    climate = fetch_nasa_climate_profile(
        45.4642,
        9.1900,
        start_year=2015,
        end_year=2024
    )

    print("Rows:", len(climate))
    print(climate.to_string(index=False))
    print("\nMissing values:")
    print(climate.isna().sum())

except Exception:
    print("NASA ERROR:")
    traceback.print_exc()
    raise

print("\n========== CANDIDATE TEST ==========")

try:
    candidates = get_climate_compatible_candidates(
        climate,
        eco,
        limit=12
    )

    print("Candidate count:", len(candidates))

    for name, profile in candidates.items():
        print(
            name,
            "| Season:", profile["season"],
            "| Source:", profile["source"]
        )

except Exception:
    print("CANDIDATE ERROR:")
    traceback.print_exc()
    raise

print("\n========== OPTIMIZER TEST ==========")

try:
    existing = ["Maize", "Winter Wheat", "Soybean", "Alfalfa"]

    for crop in existing:
        if crop not in candidates:
            candidates[crop] = get_crop_profile_from_ecocrop(crop, eco)

    strategies = generate_three_strategies(
        existing,
        climate,
        candidates
    )

    for strategy in strategies:
        print("\n", strategy["strategy_name"])
        print("Sequence:", strategy["sequence"])
        print("Scores:", strategy["scores"])
        print("Evidence:", strategy["evidence"])
        print("Risks:", strategy["risks"])

except Exception:
    print("OPTIMIZER ERROR:")
    traceback.print_exc()
    raise
print("\n===== DATABASE STRUCTURE =====")

print("Total rows:", len(eco))

print(
    "Unique EcoCrop IDs:",
    eco["ecoportcode"].nunique()
)

print(
    "Unique scientific names:",
    eco["scientificname"].nunique()
)

print(
    "Rows with common names:",
    eco["comname"].notna().sum()
)

print(
    "Rows with missing scientific names:",
    eco["scientificname"].isna().sum()
)

print("\nExample records:")

print(
    eco[["ecoportcode", "comname", "scientificname"]]
    .head(10)
    .to_string(index=False)
)
print("\n========== ALL TESTS COMPLETED ==========")