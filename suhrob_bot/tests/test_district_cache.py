"""
п.1 ТЗ — кэш районов и сопоставление района.

Главный баг: _districts_cache был одним кортежем на весь процесс, без
company_id в ключе. BotManager держит боты всех компаний в одном процессе,
поэтому первая компания забивала кэш остальным на 10 минут.
"""
import os
import unittest

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/test")
os.environ.setdefault("DEVELOPER_TELEGRAM_ID", "1")

from src.services import ai_service
from src.services.ai_service import (
    _normalize, extract_district, load_districts, reset_districts_cache,
)


class FakeResult:
    """Итерируемый результат session.execute() для load_districts."""

    def __init__(self, rows):
        self._rows = rows

    def __iter__(self):
        return iter(self._rows)


class FakeSession:
    """
    Минимальная сессия: отдаёт районы своей компании и считает обращения,
    чтобы проверить, что кэш действительно срабатывает.
    """

    def __init__(self, districts_by_company: dict[int, list[str]]):
        self.districts_by_company = districts_by_company
        self.calls: list[int] = []

    async def execute(self, stmt):
        # company_id вытаскиваем из параметров скомпилированного запроса —
        # так тест не зависит от порядка условий в where().
        params = stmt.compile().params
        company_id = next(
            (v for k, v in params.items() if "company_id" in k), None
        )
        self.calls.append(company_id)
        rows = self.districts_by_company.get(company_id, [])
        return FakeResult([(name,) for name in rows])


class NormalizeTest(unittest.TestCase):
    def test_cyrillic_maps_to_latin(self):
        self.assertEqual(_normalize("Гагарин"), _normalize("Gagarin"))

    def test_apostrophes_stripped(self):
        self.assertEqual(_normalize("Bog'ishamol"), _normalize("Bogishamol"))

    def test_case_insensitive(self):
        self.assertEqual(_normalize("GAGARIN"), "gagarin")


class DistrictCacheTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        reset_districts_cache()

    async def test_cache_is_per_company(self):
        """
        Регрессия: компания 2 не должна получать районы компании 1 только
        потому, что компания 1 прогрела кэш первой.
        """
        session = FakeSession({
            1: ["Gagarin", "Registon"],
            2: ["Motrid"],
        })

        first = await load_districts(1, session)
        second = await load_districts(2, session)

        self.assertEqual(set(first.values()), {"Gagarin", "Registon"})
        self.assertEqual(set(second.values()), {"Motrid"})
        # Обе компании реально сходили в базу — кэш не подменил вторую
        self.assertEqual(session.calls, [1, 2])

    async def test_repeat_call_uses_cache(self):
        session = FakeSession({1: ["Gagarin"]})
        await load_districts(1, session)
        await load_districts(1, session)
        self.assertEqual(session.calls, [1], "второй вызов должен идти из кэша")

    async def test_foreign_district_never_leaks(self):
        """Запрос компании A не возвращает район, которого у A нет."""
        session = FakeSession({1: ["Gagarin"], 2: ["Motrid"]})
        # Прогреваем кэш компанией 2, затем спрашиваем компанию 1
        await load_districts(2, session)
        found = await extract_district("Motrid tomonda uy bormi?", [], 1, session)
        self.assertIsNone(found, "у компании 1 района Motrid нет")

    async def test_extract_district_cyrillic_and_latin_match(self):
        session = FakeSession({1: ["Gagarin"]})

        cyr = await extract_district("Гагарин kerak", [], 1, session)
        reset_districts_cache()
        lat = await extract_district("Gagarin kerak", [], 1, session)

        self.assertEqual(cyr, "Gagarin")
        self.assertEqual(lat, "Gagarin")

    async def test_extract_district_falls_back_to_history(self):
        session = FakeSession({1: ["Gagarin"]})
        history = [{"role": "user", "content": "Gagarin tomonda qidiryapman"}]
        found = await extract_district("Byudjetim 50000", history, 1, session)
        self.assertEqual(found, "Gagarin")

    async def test_longest_district_wins(self):
        """'Amir Temur' не должен перебиваться коротким совпадением."""
        session = FakeSession({1: ["Temur", "Amir Temur"]})
        found = await extract_district("Amir Temur ko'chasi", [], 1, session)
        self.assertEqual(found, "Amir Temur")


class SearchPropertiesQueryTest(unittest.IsolatedAsyncioTestCase):
    """
    Район ищется И в location_district, И в location_address: "Gagarin" в
    Самарканде — это улица, в location_district её может не быть вовсе.
    """

    async def test_district_filter_covers_address(self):
        captured = {}

        class CaptureSession:
            async def execute(self, stmt):
                captured["sql"] = str(stmt)

                class R:
                    def scalars(self_inner):
                        return []
                return R()

        await ai_service.search_properties(
            company_id=1, district="Gagarin", price_max=None, rooms=None,
            session=CaptureSession(), limit=3,
        )
        sql = captured["sql"]
        self.assertIn("location_district", sql)
        self.assertIn("location_address", sql)
        self.assertIn("OR", sql.upper())


if __name__ == "__main__":
    unittest.main()
