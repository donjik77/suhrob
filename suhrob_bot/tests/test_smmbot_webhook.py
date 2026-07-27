"""
Синхронный роут POST /webhook/smmbot.

В отличие от Salebot-моста, SMMBOT ждёт ответ в теле того же запроса,
поэтому роут обязан всегда отдавать 200 с полем reply (кроме случая, когда
не передан client_id) — иначе сценарий SMMBOT падает и клиент не получает
ничего.

Сам вызов модели подменён: проверяется контракт роута и работа с БД,
а не качество текста от AI.
"""
import os
import unittest

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/test")
os.environ.setdefault("DEVELOPER_TELEGRAM_ID", "1")

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import src.db.session as db_session
from src.db.models import Base, ClientConversation, Company, User
from src.services import instagram_bridge as bridge


class SmmbotWebhookTest(AioHTTPTestCase):
    async def get_application(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        self.Session = async_sessionmaker(self.engine, expire_on_commit=False)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        db_session.AsyncSessionFactory = self.Session
        self._orig_factory = bridge.AsyncSessionFactory
        bridge.AsyncSessionFactory = self.Session

        async with self.Session() as s:
            company = Company(name="Suhrob HOUSE", bot_token="123:ABC",
                              is_active=True)
            s.add(company)
            await s.commit()
            await s.refresh(company)
            self.company_id = company.id
        bridge.INSTAGRAM_COMPANY_ID = self.company_id

        # Модель подменяем — тест про контракт роута, не про текст AI
        self.ai_calls = []
        self._orig_chat = bridge.chat_with_client

        async def fake_chat(**kwargs):
            self.ai_calls.append(kwargs)
            return "Ha, bor. Qaysi tuman kerak?"

        bridge.chat_with_client = fake_chat

        async def noop_qualify(*a, **k):
            return None

        self._orig_qualify = bridge._qualify_in_background
        bridge._qualify_in_background = noop_qualify

        app = web.Application()
        bridge.register_instagram_routes(app)
        return app

    async def tearDownAsync(self):
        bridge.chat_with_client = self._orig_chat
        bridge._qualify_in_background = self._orig_qualify
        bridge.AsyncSessionFactory = self._orig_factory
        await self.engine.dispose()

    # ---------------- успешный путь ----------------

    async def test_returns_reply_200(self):
        resp = await self.client.post("/webhook/smmbot", json={
            "client_id": 999,
            "message": "Salom, uy bor mi?",
            "client_name": "Test",
        })
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertIn("reply", body)
        self.assertTrue(body["reply"], "reply не должен быть пустым")
        self.assertEqual(body["reply"], "Ha, bor. Qaysi tuman kerak?")

    async def test_uses_instagram_channel(self):
        await self.client.post("/webhook/smmbot", json={
            "client_id": 999, "message": "Salom",
        })
        self.assertEqual(self.ai_calls[0]["channel"], "instagram")

    async def test_creates_user_with_negative_id(self):
        await self.client.post("/webhook/smmbot", json={
            "client_id": 999, "message": "Salom", "client_name": "Sardor",
        })
        async with self.Session() as s:
            user = (await s.execute(
                select(User).where(User.telegram_user_id == -999)
            )).scalar_one()
            self.assertEqual(user.full_name, "Sardor")
            self.assertEqual(user.company_id, self.company_id)

    async def test_saves_both_messages(self):
        await self.client.post("/webhook/smmbot", json={
            "client_id": 999, "message": "Salom, uy bor mi?",
        })
        async with self.Session() as s:
            rows = (await s.execute(
                select(ClientConversation).order_by(ClientConversation.id)
            )).scalars().all()
            self.assertEqual([r.role for r in rows], ["user", "assistant"])
            self.assertEqual(rows[0].message, "Salom, uy bor mi?")
            self.assertEqual(rows[1].message, "Ha, bor. Qaysi tuman kerak?")

    async def test_history_passed_on_second_message(self):
        await self.client.post("/webhook/smmbot",
                               json={"client_id": 999, "message": "Salom"})
        await self.client.post("/webhook/smmbot",
                               json={"client_id": 999, "message": "2 xonali"})
        history = self.ai_calls[1]["conversation_history"]
        self.assertEqual([h["role"] for h in history], ["user", "assistant"])
        self.assertEqual(history[0]["content"], "Salom")

    async def test_same_client_reuses_user(self):
        await self.client.post("/webhook/smmbot",
                               json={"client_id": 999, "message": "Salom"})
        await self.client.post("/webhook/smmbot",
                               json={"client_id": 999, "message": "Yana"})
        async with self.Session() as s:
            users = (await s.execute(
                select(User).where(User.telegram_user_id == -999)
            )).scalars().all()
            self.assertEqual(len(users), 1)

    async def test_negative_client_id_400(self):
        """
        Правило "чистые цифры" отбраковывает id со знаком. Ни один
        конструктор отрицательные id не шлёт, а "-999" от нас же
        (мы храним клиентов с минусом) в webhook приходить не должен.
        """
        resp = await self.client.post("/webhook/smmbot",
                                      json={"client_id": -999,
                                            "message": "Salom"})
        self.assertEqual(resp.status, 400)

    async def test_card_markers_stripped(self):
        async def chat_with_marker(**kwargs):
            return "Gagarin, 2 xona, $48000.\n[CARD:142]"
        bridge.chat_with_client = chat_with_marker

        resp = await self.client.post("/webhook/smmbot",
                                      json={"client_id": 999, "message": "uy"})
        body = await resp.json()
        self.assertNotIn("CARD", body["reply"])

    # ---------------- ошибки ----------------

    async def test_missing_client_id_400(self):
        resp = await self.client.post("/webhook/smmbot",
                                      json={"message": "Salom"})
        self.assertEqual(resp.status, 400)

    async def test_unrendered_template_400(self):
        """
        Шаблон в сценарии не подставился — приходит литерал.
        Заводить пользователя с таким id нельзя.
        """
        for raw in ["{{client_id}}", "{{ client_id }}", "{{contact.id}}",
                    "prefix{{id}}suffix"]:
            resp = await self.client.post("/webhook/smmbot",
                                          json={"client_id": raw,
                                                "message": "Salom"})
            self.assertEqual(resp.status, 400, raw)
            self.assertEqual((await resp.json())["error"], "invalid client_id")

    # ---------------- SendPulse: hex ObjectId ----------------

    async def test_hex_object_id_accepted(self):
        """SendPulse шлёт ObjectId — сворачивается в стабильное число."""
        resp = await self.client.post("/webhook/smmbot", json={
            "client_id": "507f1f77bcf86cd799439011",
            "message": "Salom",
            "client_name": "SendPulse mijoz",
        })
        self.assertEqual(resp.status, 200)
        self.assertTrue((await resp.json())["reply"])

        async with self.Session() as s:
            users = (await s.execute(select(User))).scalars().all()
            self.assertEqual(len(users), 1)
            self.assertLess(users[0].telegram_user_id, 0,
                            "Instagram-клиент обязан быть отрицательным")

    async def test_hex_object_id_is_stable(self):
        """
        Один и тот же ObjectId в разных сообщениях должен давать один и тот
        же id — иначе клиент задваивается и теряет историю диалога.
        """
        oid = "507f1f77bcf86cd799439011"
        await self.client.post("/webhook/smmbot",
                               json={"client_id": oid, "message": "Salom"})
        await self.client.post("/webhook/smmbot",
                               json={"client_id": oid, "message": "2 xonali"})

        async with self.Session() as s:
            users = (await s.execute(select(User))).scalars().all()
            self.assertEqual(len(users), 1, "клиент задвоился")
            rows = (await s.execute(select(ClientConversation))).scalars().all()
            self.assertEqual(len(rows), 4)

    async def test_different_object_ids_give_different_users(self):
        for oid in ("507f1f77bcf86cd799439011", "507f191e810c19729de860ea"):
            await self.client.post("/webhook/smmbot",
                                   json={"client_id": oid, "message": "Salom"})
        async with self.Session() as s:
            ids = {u.telegram_user_id
                   for u in (await s.execute(select(User))).scalars().all()}
            self.assertEqual(len(ids), 2, "разные ObjectId слиплись в один id")

    async def test_hashed_id_fits_bigint(self):
        """15 hex-символов = 60 бит; должно влезать в BigInteger Postgres."""
        await self.client.post("/webhook/smmbot", json={
            "client_id": "ffffffffffffffffffffffff", "message": "Salom",
        })
        async with self.Session() as s:
            user = (await s.execute(select(User))).scalar_one()
            self.assertLess(abs(user.telegram_user_id), 2 ** 63 - 1)

    async def test_garbage_client_id_400(self):
        """
        Мусор не должен молча хешироваться: иначе все обращения с
        "undefined" слиплись бы в одного клиента с общей историей.
        Принимаем только чистые цифры или 24-символьный ObjectId.
        """
        for raw in ["abc", "undefined", "None", "null", "user_42",
                    "507f1f77bcf86cd7994390",     # 22 символа — короткий
                    "507f1f77bcf86cd799439011ab",  # 26 — длинный
                    "507f1f77bcf86cd79943901z"]:   # 24, но 'z' не hex
            resp = await self.client.post("/webhook/smmbot",
                                          json={"client_id": raw,
                                                "message": "hi"})
            self.assertEqual(resp.status, 400, raw)
            self.assertEqual((await resp.json())["error"], "invalid client_id")

        async with self.Session() as s:
            users = (await s.execute(select(User))).scalars().all()
            self.assertEqual(users, [], "мусор не должен заводить клиентов")

    async def test_numeric_string_client_id_accepted(self):
        """SMMBOT шлёт id строкой — должно работать."""
        resp = await self.client.post("/webhook/smmbot",
                                      json={"client_id": "999",
                                            "message": "Salom"})
        self.assertEqual(resp.status, 200)
        async with self.Session() as s:
            user = (await s.execute(
                select(User).where(User.telegram_user_id == -999)
            )).scalar_one_or_none()
            self.assertIsNotNone(user)

    async def test_padded_client_id_accepted(self):
        resp = await self.client.post("/webhook/smmbot",
                                      json={"client_id": "  999  ",
                                            "message": "Salom"})
        self.assertEqual(resp.status, 200)

    async def test_null_client_id_400(self):
        resp = await self.client.post("/webhook/smmbot",
                                      json={"client_id": None,
                                            "message": "Salom"})
        self.assertEqual(resp.status, 400)

    async def test_invalid_json_400(self):
        resp = await self.client.post("/webhook/smmbot", data="not json",
                                      headers={"Content-Type": "application/json"})
        self.assertEqual(resp.status, 400)

    async def test_empty_message_returns_empty_reply_200(self):
        resp = await self.client.post("/webhook/smmbot",
                                      json={"client_id": 999, "message": ""})
        self.assertEqual(resp.status, 200)
        self.assertEqual((await resp.json())["reply"], "")

    async def test_missing_message_returns_empty_reply_200(self):
        resp = await self.client.post("/webhook/smmbot",
                                      json={"client_id": 999})
        self.assertEqual(resp.status, 200)
        self.assertEqual((await resp.json())["reply"], "")

    async def test_ai_exception_returns_200_with_fallback(self):
        """SMMBOT не должен зависнуть из-за нашей ошибки."""
        async def boom(**kwargs):
            raise RuntimeError("openrouter down")
        bridge.chat_with_client = boom

        resp = await self.client.post("/webhook/smmbot",
                                      json={"client_id": 999, "message": "Salom"})
        self.assertEqual(resp.status, 200)
        self.assertEqual((await resp.json())["reply"], bridge.SMMBOT_ERROR_REPLY)

    async def test_ai_timeout_returns_200_with_fallback(self):
        import asyncio

        async def hang(**kwargs):
            await asyncio.sleep(5)
            return "never"
        bridge.chat_with_client = hang

        orig_timeout = bridge.SMMBOT_AI_TIMEOUT_SECONDS
        bridge.SMMBOT_AI_TIMEOUT_SECONDS = 0.2
        try:
            resp = await self.client.post(
                "/webhook/smmbot", json={"client_id": 999, "message": "Salom"})
            self.assertEqual(resp.status, 200)
            self.assertEqual((await resp.json())["reply"],
                             bridge.SMMBOT_ERROR_REPLY)
        finally:
            bridge.SMMBOT_AI_TIMEOUT_SECONDS = orig_timeout


class RouteRegistrationTest(unittest.TestCase):
    """Старые роуты Salebot должны остаться на месте."""

    def test_all_routes_registered(self):
        app = web.Application()
        bridge.register_instagram_routes(app)
        paths = {r.resource.canonical for r in app.router.routes()}
        for expected in ("/webhook/smmbot", "/webhook/instagram",
                         "/webhook/instagram/phone",
                         "/webhook/instagram/followup",
                         "/health"):
            self.assertIn(expected, paths)

    def test_smmbot_is_post(self):
        app = web.Application()
        bridge.register_instagram_routes(app)
        methods = {r.method for r in app.router.routes()
                   if r.resource.canonical == "/webhook/smmbot"}
        self.assertEqual(methods, {"POST"})


if __name__ == "__main__":
    unittest.main()
