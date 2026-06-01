import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/test")
os.environ.setdefault("DEVELOPER_TELEGRAM_ID", "1")

from src.bot.handlers.agent.my_properties import _owns_property
from src.db.models import UserRole


class OwnershipHelpersTest(unittest.TestCase):
    def test_agent_only_owns_own_property(self):
        prop = SimpleNamespace(agent_id=10, company_id=1)
        agent = SimpleNamespace(id=10, role=UserRole.agent, company_id=1)
        other_agent = SimpleNamespace(id=11, role=UserRole.agent, company_id=1)

        self.assertTrue(_owns_property(prop, agent))
        self.assertFalse(_owns_property(prop, other_agent))

    def test_director_is_scoped_to_company(self):
        prop = SimpleNamespace(agent_id=10, company_id=1)
        same_company_director = SimpleNamespace(id=20, role=UserRole.director, company_id=1)
        other_company_director = SimpleNamespace(id=21, role=UserRole.director, company_id=2)

        self.assertTrue(_owns_property(prop, same_company_director))
        self.assertFalse(_owns_property(prop, other_company_director))

    def test_developer_can_access_property(self):
        prop = SimpleNamespace(agent_id=10, company_id=1)
        developer = SimpleNamespace(id=1, role=UserRole.developer, company_id=None)

        self.assertTrue(_owns_property(prop, developer))


if __name__ == "__main__":
    unittest.main()
