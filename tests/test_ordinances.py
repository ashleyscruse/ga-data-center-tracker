"""Tests for the ordinance and moratorium dataset.

This workbook exists to keep detail the main dataset drops, so the tests are
mostly about that detail surviving: expired moratoria still counted, city
moratoria attributed to their county without pretending the county acted, and
every county present so the join never has a hole.
"""

from __future__ import annotations

from datetime import date

from ga_data_center_tracker import GEORGIA_COUNTY_COUNT
from ga_data_center_tracker.ordinances import ORIGINAL_COLUMNS, build
from ga_data_center_tracker.scrapers.epicenter import CountyRegulation, HubData, Moratorium

ON = date(2026, 8, 13)


def _hub() -> HubData:
    return HubData(
        moratoria=[
            # county-adopted, lapsed
            Moratorium("Douglas County, GA", "county", "Douglas County, Georgia",
                       date(2025, 6, 18), date(2025, 9, 16)),
            # city-adopted, lapsed, recorded against its county
            Moratorium("Roswell, GA", "city", "Fulton County, Georgia",
                       date(2026, 1, 12), date(2026, 4, 12)),
            # county-adopted, still in force
            Moratorium("Bartow County, GA", "county", "Bartow County, Georgia",
                       date(2026, 7, 1), date(2026, 12, 31)),
        ],
        regulations=[
            CountyRegulation("13097", "Douglas County, Georgia", True),
            CountyRegulation("13121", "Fulton County, Georgia", True),
            CountyRegulation("13045", "Carroll County, Georgia", False),
        ],
    )


class TestShape:
    def test_five_sheets_worth_of_parts(self):
        d = build(_hub(), on=ON)
        assert d.original_rows and d.long_rows and d.transformed_rows and d.variables

    def test_every_county_appears(self):
        d = build(_hub(), on=ON)
        assert len({r["county"] for r in d.long_rows}) == GEORGIA_COUNTY_COUNT

    def test_long_sheet_is_dense(self):
        d = build(_hub(), on=ON)
        assert len(d.long_rows) == GEORGIA_COUNTY_COUNT * len(d.variables)

    def test_original_rows_use_the_declared_columns(self):
        d = build(_hub(), on=ON)
        for row in d.original_rows:
            assert set(row) == set(ORIGINAL_COLUMNS)


class TestCounts:
    def _vals(self, county):
        d = build(_hub(), on=ON)
        return {r["varname"]: r["datavalue"] for r in d.long_rows if r["county"] == county}

    def test_expired_moratoria_still_count_as_adopted(self):
        # An expired moratorium is still evidence the community formally responded.
        v = self._vals("Douglas County, Georgia")
        assert v["dc_moratorium_n"] == 1
        assert v["dc_moratorium_expired_n"] == 1
        assert v["dc_moratorium_active_n"] == 0

    def test_active_moratorium_is_not_counted_as_expired(self):
        v = self._vals("Bartow County, Georgia")
        assert (v["dc_moratorium_active_n"], v["dc_moratorium_expired_n"]) == (1, 0)

    def test_city_moratorium_is_attributed_to_its_county_and_flagged(self):
        # Roswell is in Fulton. The county gets the count, but dc_moratorium_city_n
        # keeps it from reading as though Fulton County itself acted.
        v = self._vals("Fulton County, Georgia")
        assert v["dc_moratorium_n"] == 1
        assert v["dc_moratorium_city_n"] == 1

    def test_county_adopted_moratorium_is_not_flagged_as_municipal(self):
        assert self._vals("Douglas County, Georgia")["dc_moratorium_city_n"] == 0

    def test_local_action_covers_ordinance_or_moratorium(self):
        assert self._vals("Douglas County, Georgia")["dc_local_action"] == 1
        assert self._vals("Bartow County, Georgia")["dc_local_action"] == 1   # moratorium only
        assert self._vals("Echols County, Georgia")["dc_local_action"] == 0

    def test_ordinance_flag_reads_from_the_regulation_table(self):
        assert self._vals("Carroll County, Georgia")["dc_ordinance"] == 0
        assert self._vals("Fulton County, Georgia")["dc_ordinance"] == 1


class TestRecords:
    def test_both_record_types_present(self):
        d = build(_hub(), on=ON)
        kinds = {r["record_type"] for r in d.original_rows}
        assert kinds == {"ordinance", "moratorium"}

    def test_moratorium_rows_carry_their_dates_and_status(self):
        d = build(_hub(), on=ON)
        row = next(r for r in d.original_rows if r["jurisdiction"] == "Douglas County, GA")
        assert row["start_date"] == "2025-06-18"
        assert row["expiration_date"] == "2025-09-16"
        assert row["status"] == "expired"

    def test_only_ordinance_counties_get_an_ordinance_row(self):
        d = build(_hub(), on=ON)
        names = {r["jurisdiction"] for r in d.original_rows if r["record_type"] == "ordinance"}
        assert "Carroll County, Georgia" not in names   # has_ordinance is False

    def test_every_record_is_attributed(self):
        d = build(_hub(), on=ON)
        assert all("EPIcenter" in str(r["source"]) for r in d.original_rows)
