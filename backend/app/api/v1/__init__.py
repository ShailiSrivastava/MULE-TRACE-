from fastapi import APIRouter
from app.api.v1 import auth, dashboard, transactions, graph, alerts, cases, risk, reports

router = APIRouter()
router.include_router(auth.router, tags=["auth"])
router.include_router(dashboard.router, tags=["dashboard"])
router.include_router(transactions.router, tags=["transactions"])
router.include_router(graph.router, tags=["graph"])
router.include_router(alerts.router, tags=["alerts"])
router.include_router(cases.router, tags=["cases"])
router.include_router(risk.router, tags=["risk"])
router.include_router(reports.router, tags=["reports"])
