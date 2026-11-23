from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models.account import Account
from app.models.risk_score import RiskScore

router = APIRouter()

@router.get("/risk/analysis")
def risk_analysis(db: Session = Depends(get_db)):
    scores = db.query(RiskScore).all()
    buckets = {"0-20":0,"21-40":0,"41-60":0,"61-80":0,"81-100":0}
    for s in scores:
        sc = s.score
        if sc <= 20: buckets["0-20"] += 1
        elif sc <= 40: buckets["21-40"] += 1
        elif sc <= 60: buckets["41-60"] += 1
        elif sc <= 80: buckets["61-80"] += 1
        else: buckets["81-100"] += 1
    distribution = [{"range": k, "count": v} for k,v in buckets.items()]
    top = sorted(scores, key=lambda x: x.score, reverse=True)[:10]
    leaderboard = [{"account_id": s.account_id, "score": s.score} for s in top]
    avg = (sum(s.score for s in scores)/len(scores)) if scores else 0
    return {"average_portfolio_risk": avg, "score_distribution": distribution, "top_high_risk_accounts": leaderboard}
