import itertools
import random
import pandas as pd


SCORE_KEYS = ("water_resilience", "heat_fit", "soil_health", "pest_break")
DEFAULT_WEIGHTS = {key: 25.0 for key in SCORE_KEYS}


def normalize_weights(weights: dict[str, float] | None = None) -> dict[str, float]:
    """Return active evaluation weights normalized to percentages totaling 100."""
    source = weights if weights is not None else DEFAULT_WEIGHTS
    values = {key: max(float(source.get(key, 1.0)), 1.0) for key in SCORE_KEYS}
    total = sum(values.values())
    normalized = {
        key: round(values[key] / total * 100.0, 1)
        for key in SCORE_KEYS[:-1]
    }
    normalized[SCORE_KEYS[-1]] = round(100.0 - sum(normalized.values()), 1)
    return normalized


def score_rotation(
    sequence: list[str],
    climate_df: pd.DataFrame,
    crop_db: dict[str, dict],
    weights: dict[str, float] | None = None,
) -> dict:
    """
    Evaluates a multi-season crop sequence against local NASA climate telemetry
    and FAO EcoCrop agronomic parameters.
    """
    water_score, heat_score, soil_score, diversity_score = 90.0, 95.0, 50.0, 100.0
    evidence = []
    risks = []

    water_trend = climate_df["long_term_water_trend"].iloc[0]
    avg_summer_moisture = climate_df[climate_df["month"].isin([6, 7, 8])]["soil_moisture"].mean()
    max_summer_temp = climate_df[climate_df["month"].isin([6, 7, 8])]["temp_max"].max()
    min_winter_temp = climate_df[climate_df["month"].isin([12, 1, 2])]["temp_min"].min()
    winter_precip = climate_df[climate_df["month"].isin([11, 12, 1, 2])]["precip_mm"].sum()
    summer_precip = climate_df[climate_df["month"].isin([5, 6, 7, 8, 9])]["precip_mm"].sum()

    prev_family = None
    for idx, crop_name in enumerate(sequence):
        crop = crop_db[crop_name]
        is_cool_slot = (idx % 2 == 1)

        # 1. Pest & Disease Cycle Break (Consecutive botanical family check)
        if prev_family and crop["family"] == prev_family and crop_name != "Fallow":
            diversity_score -= 25
            risks.append(f"Back-to-back {crop['family']} family ({crop_name}) increases pest & pathogen carryover.")
        prev_family = crop["family"]

        # 2. Water Resilience & Long-Term Water Trend Check
        if crop_name != "Fallow":
            if crop["cycle_water_need_mm"] > summer_precip * 1.15 and (avg_summer_moisture < 0.45 or water_trend == "declining"):
                water_score -= 22
                risks.append(
                    f"{crop_name} requires ~{crop['cycle_water_need_mm']:.0f}mm water, exceeding warm-season rainfall "
                    f"({summer_precip:.0f}mm) with {water_trend} soil moisture ({avg_summer_moisture:.2f})."
                )
            elif crop["water_demand"] == "low":
                water_score = min(100.0, water_score + 6)
                evidence.append(f"{crop_name} has low cycle water demand (~{crop['cycle_water_need_mm']:.0f}mm), easing moisture stress.")

        # 3. Heat Stress, Frost Risk & Ripening Window Check
        if not is_cool_slot and max_summer_temp > crop["heat_tolerance_c"]:
            heat_score -= 18
            risks.append(
                f"Peak summer heat ({max_summer_temp:.1f}°C) exceeds {crop_name}'s optimal ceiling ({crop['heat_tolerance_c']:.1f}°C)."
            )
        if is_cool_slot and crop_name != "Fallow" and not crop["frost_hardy"] and min_winter_temp < 2.0:
            heat_score -= 25
            risks.append(f"{crop_name} is frost-sensitive (min {crop['abs_min_temp_c']:.1f}°C) for winter temps ({min_winter_temp:.1f}°C).")

        if crop["ripening_days"] > 175 and not is_cool_slot:
            heat_score -= 10
            risks.append(f"{crop_name} has a long ripening cycle ({crop['ripening_days']} days), risking late-season harvest delays.")

        # 4. Soil Health, Nitrogen & Bare-Ground Erosion Check
        soil_score += crop["nitrogen_impact"] * 0.45
        if crop["nitrogen_impact"] > 0:
            evidence.append(f"{crop_name} ({crop['family']}) fixes atmospheric nitrogen, enriching soil fertility.")

        if crop_name == "Fallow" and winter_precip > 180:
            soil_score -= 20
            evidence.append(f"Bare fallow exposes soil to {winter_precip:.0f}mm of winter rainfall, elevating erosion & runoff risk.")
        elif crop["erosion_protection"] >= 0.80:
            soil_score += 15
            evidence.append(f"{crop_name} maintains living root cover, protecting topsoil during wet periods.")

    scores = {
        "water_resilience": round(max(0.0, min(100.0, water_score)), 1),
        "heat_fit": round(max(0.0, min(100.0, heat_score)), 1),
        "soil_health": round(max(0.0, min(100.0, soil_score)), 1),
        "pest_break": round(max(0.0, min(100.0, diversity_score)), 1),
    }
    normalized_weights = normalize_weights(weights)
    scores["overall"] = round(
        sum(scores[key] * normalized_weights[key] for key in SCORE_KEYS) / 100.0,
        1,
    )

    return {
        "sequence": sequence,
        "scores": scores,
        "evidence": list(dict.fromkeys(evidence)) or ["Aligned with baseline temperature and moisture thresholds."],
        "risks": list(dict.fromkeys(risks)) or ["No major climate-crop mismatches detected; verify local soil pH and market access."]
    }


def generate_three_strategies(
    existing_rotation: list[str],
    climate_df: pd.DataFrame,
    crop_db: dict[str, dict],
    weights: dict[str, float] | None = None,
) -> list[dict]:
    """
    Evaluates the farmer's existing rotation and generates 2 optimized alternatives:
    1. Current Baseline Rotation
    2. Highest-scoring alternative for the selected priorities
    3. Next-highest-scoring alternative
    """
    normalized_weights = normalize_weights(weights)
    baseline = score_rotation(existing_rotation, climate_df, crop_db, normalized_weights)
    baseline["strategy_name"] = "1. Current Baseline Rotation"

    warm_pool = [c for c, d in crop_db.items() if d["season"] in ["Warm", "Any"] and c != "Fallow"]
    cool_pool = [c for c, d in crop_db.items() if d["season"] in ["Cool", "Any"]]

    # Ensure farmer's own crops remain in the candidate pools
    for idx, c in enumerate(existing_rotation):
        if idx % 2 == 0 and c not in warm_pool:
            warm_pool.append(c)
        elif idx % 2 == 1 and c not in cool_pool:
            cool_pool.append(c)

    num_slots = len(existing_rotation)
    slot_options = [warm_pool[:8] if i % 2 == 0 else cool_pool[:8] for i in range(num_slots)]

    all_combos = list(itertools.product(*slot_options))
    if len(all_combos) > 1500:
        random.seed(42)
        all_combos = random.sample(all_combos, 1500)

    candidates = []
    for seq in all_combos:
        seq_list = list(seq)
        if seq_list == existing_rotation:
            continue
        candidates.append(score_rotation(seq_list, climate_df, crop_db, normalized_weights))

    if not candidates:
        return [baseline]

    ranked_candidates = sorted(
        candidates,
        key=lambda candidate: candidate["scores"]["overall"],
        reverse=True,
    )
    alternatives = ranked_candidates[:2]
    if len(alternatives) == 1:
        alternatives.append(dict(alternatives[0]))
    alternatives[0]["strategy_name"] = "2. Priority-Aligned Alternative"
    alternatives[1]["strategy_name"] = "3. Next-Best Alternative"

    return [baseline, *alternatives]