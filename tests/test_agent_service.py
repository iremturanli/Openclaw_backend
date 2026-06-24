from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from app.services.agent_service import AgentService, _resolve_explicit_date_from_text


class _DummyFlightService:
    def __init__(self, results: list[dict[str, object]] | None = None) -> None:
        self.calls: list[dict[str, object]] = []
        self.results = results or []

    async def search(
        self,
        *,
        origin: str,
        destination: str,
        outbound_date: str,
        return_date: str | None = None,
        adults: int = 1,
        currency: str | None = None,
    ) -> list[dict[str, object]]:
        self.calls.append(
            {
                "origin": origin,
                "destination": destination,
                "outbound_date": outbound_date,
                "return_date": return_date,
                "adults": adults,
                "currency": currency,
            }
        )
        return self.results


class _DummyWallet:
    async def ensure_budget(self, guest_id: str) -> SimpleNamespace:
        return SimpleNamespace(balance_cents=100000, currency="USD")


def _service(flights: _DummyFlightService) -> AgentService:
    settings = SimpleNamespace(
        openai_api_key="test",
        openai_model="gpt-test",
        demo_budget_currency="USD",
    )
    return AgentService(
        settings=settings,
        flights=flights,
        hotels=SimpleNamespace(),
        restaurants=SimpleNamespace(),
        wallet=_DummyWallet(),
        guest_id="guest_demo",
        preferences=None,
    )


async def test_search_flights_resolves_turkish_city_names_to_iata() -> None:
    flights = _DummyFlightService()
    service = _service(flights)

    result = await service._tool_search_flights(
        {
            "origin": "Ankara",
            "destination": "İstanbul",
            "outbound_date": "2026-07-01",
        }
    )

    assert result["resolvedOrigin"] == "ESB"
    assert result["resolvedDestination"] == "IST"
    assert flights.calls[0]["origin"] == "ESB"
    assert flights.calls[0]["destination"] == "IST"


async def test_search_flights_defaults_missing_date_for_voice_queries() -> None:
    flights = _DummyFlightService()
    service = _service(flights)

    result = await service._tool_search_flights(
        {
            "origin": "Ankara",
            "destination": "Istanbul Airport",
        }
    )

    assert result["resolvedOrigin"] == "ESB"
    assert result["resolvedDestination"] == "IST"
    assert flights.calls[0]["outbound_date"]


def test_resolve_explicit_date_from_text_supports_relative_and_absolute_forms() -> None:
    anchor = date(2026, 6, 24)

    assert _resolve_explicit_date_from_text("bugün uçuş ara", today=anchor) == anchor
    assert _resolve_explicit_date_from_text(
        "5 gün sonra ankaradan istanbula",
        today=anchor,
    ) == date(2026, 6, 29)
    assert _resolve_explicit_date_from_text(
        "26 eylül için uçuş",
        today=anchor,
    ) == date(2026, 9, 26)
    assert _resolve_explicit_date_from_text(
        "26 eylül 2027 için uçuş",
        today=anchor,
    ) == date(2027, 9, 26)


async def test_search_flights_uses_spoken_turkish_relative_date_hint() -> None:
    flights = _DummyFlightService()
    service = _service(flights)
    service._latest_user_text = "ankaradan istanbula 5 gün sonra en ucuz uçuş"

    with patch("app.services.agent_service._today_local", return_value=date(2026, 6, 24)):
        await service._tool_search_flights(
            {
                "origin": "Ankara",
                "destination": "İstanbul",
            }
        )

    assert flights.calls[0]["outbound_date"] == "2026-06-29"


async def test_search_flights_uses_spoken_absolute_date_hint_with_explicit_year() -> None:
    flights = _DummyFlightService()
    service = _service(flights)
    service._latest_user_text = "26 eylül 2027 için ankara istanbul uçuş"

    with patch("app.services.agent_service._today_local", return_value=date(2026, 6, 24)):
        await service._tool_search_flights(
            {
                "origin": "Ankara",
                "destination": "İstanbul",
            }
        )

    assert flights.calls[0]["outbound_date"] == "2027-09-26"


async def test_fallback_flight_search_handles_turkish_arasi_query() -> None:
    flights = _DummyFlightService(
        results=[
            {
                "airline": "Turkish Airlines",
                "price": 120,
                "currency": "USD",
                "departureAirport": "ESB",
                "arrivalAirport": "IST",
                "departureTime": "09:00",
                "arrivalTime": "10:15",
                "stops": 0,
            }
        ]
    )
    service = _service(flights)

    message = await service._fallback_flight_search(
        [{"role": "user", "content": "Ankara İstanbul arası uçuş ara"}]
    )

    assert message is not None
    assert "ESB" in message
    assert "IST" in message
    assert flights.calls[0]["origin"] == "ESB"
    assert flights.calls[0]["destination"] == "IST"
