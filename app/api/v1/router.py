"""Aggregate v1 API router."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import (
    assistant,
    auth,
    budget,
    cars,
    check_ins,
    connections,
    flights,
    keys,
    loyalty,
    orchestrator,
    orders,
    partners,
    paxpal,
    payments,
    places,
    preferences,
    restaurants,
    spend,
    stays,
    transfers,
    travel,
    trips,
    voice,
    wallet,
)

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(budget.router)
api_router.include_router(flights.router)
api_router.include_router(assistant.router)
api_router.include_router(stays.router)
api_router.include_router(orders.router)
api_router.include_router(check_ins.router)
api_router.include_router(voice.router)
api_router.include_router(travel.router)
api_router.include_router(loyalty.router)
api_router.include_router(connections.router)
api_router.include_router(orchestrator.router)
api_router.include_router(places.router)
api_router.include_router(preferences.router)
api_router.include_router(cars.router)
api_router.include_router(transfers.router)
api_router.include_router(restaurants.router)
api_router.include_router(trips.router)
api_router.include_router(partners.router)
api_router.include_router(keys.router)
api_router.include_router(paxpal.router)
api_router.include_router(payments.router)
api_router.include_router(wallet.router)
api_router.include_router(spend.router)
