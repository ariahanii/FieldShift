import unittest
from unittest.mock import Mock, patch

import numpy as np
import pandas as pd

from data_fetcher import aggregate_nasa_climate_profile, fetch_nasa_climate_data


def make_climate_data(start_year: int, end_year: int) -> pd.DataFrame:
    records = []
    for year in range(start_year, end_year + 1):
        for month in range(1, 13):
            year_value = float(year - 2000)
            records.append({
                "year": year,
                "month": month,
                "temp_avg": year_value,
                "temp_max": year_value + 5.0,
                "temp_min": year_value - 5.0,
                "precip_mm": year_value * 10.0,
                "soil_moisture": 0.5,
                "evapotrans": year_value / 100.0,
            })
    return pd.DataFrame(records)


class ClimateAggregationTests(unittest.TestCase):
    def test_selected_period_is_used_for_all_climate_averages(self):
        climate_data = make_climate_data(2015, 2024)

        monthly = aggregate_nasa_climate_profile(climate_data, 2022, 2024)
        january = monthly.loc[monthly["month"] == 1].iloc[0]

        self.assertAlmostEqual(january["temp_avg"], 23.0)
        self.assertAlmostEqual(january["temp_max"], 28.0)
        self.assertAlmostEqual(january["temp_min"], 18.0)
        self.assertAlmostEqual(january["precip_mm"], 230.0)
        self.assertAlmostEqual(january["evapotrans"], 0.23)
        self.assertAlmostEqual(january["water_balance"], 230.0 - 0.23 * 30.4)

    def test_missing_month_is_reported_instead_of_shortening_period(self):
        climate_data = make_climate_data(2022, 2024)
        climate_data = climate_data[
            ~((climate_data["year"] == 2023) & (climate_data["month"] == 6))
        ]

        with self.assertRaisesRegex(ValueError, "missing monthly observations: 2023-06"):
            aggregate_nasa_climate_profile(climate_data, 2022, 2024)

    def test_missing_variable_value_is_reported(self):
        climate_data = make_climate_data(2022, 2024)
        climate_data.loc[
            (climate_data["year"] == 2023) & (climate_data["month"] == 1),
            "temp_min",
        ] = np.nan

        with self.assertRaisesRegex(ValueError, "temp_min unavailable for 2023-01"):
            aggregate_nasa_climate_profile(climate_data, 2022, 2024)

    def test_nasa_missing_value_marker_is_preserved_as_unavailable(self):
        parameters = {
            parameter: {
                f"{year}{month:02d}": 1.0
                for year in range(2022, 2025)
                for month in range(1, 13)
            }
            for parameter in (
                "T2M", "T2M_MAX", "T2M_MIN", "PRECTOTCORR", "GWETROOT", "EVPTRNS"
            )
        }
        parameters["T2M_MIN"]["202301"] = -999
        response = Mock()
        response.json.return_value = {"properties": {"parameter": parameters}}

        with patch("data_fetcher.requests.get", return_value=response):
            climate_data = fetch_nasa_climate_data(45.0, 9.0, 2022, 2024)

        missing_value = climate_data.loc[
            (climate_data["year"] == 2023) & (climate_data["month"] == 1),
            "temp_min",
        ].iloc[0]
        self.assertTrue(pd.isna(missing_value))


if __name__ == "__main__":
    unittest.main()
