from django.test import SimpleTestCase


class HealthEndpointTests(SimpleTestCase):
    """Health endpoint must work without a database or any secrets configured."""

    databases = set()

    def test_health_returns_ok_status(self):
        response = self.client.get("/api/health/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "status": "ok",
                "service": "mycelium-backend",
                "version": "0.1.0",
            },
        )

    def test_health_exposes_no_configuration(self):
        body = self.client.get("/api/health/").content.decode().lower()
        for forbidden in ("secret", "password", "groq", "mysql", "debug"):
            self.assertNotIn(forbidden, body)
