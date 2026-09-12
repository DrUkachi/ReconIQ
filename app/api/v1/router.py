from fastapi import APIRouter

from app.api.v1.routes import cases, proposals, reconciliations, settings, transactions

api_router = APIRouter()
api_router.include_router(reconciliations.router)
api_router.include_router(transactions.router)
api_router.include_router(cases.router)
api_router.include_router(proposals.router)
api_router.include_router(settings.router)
