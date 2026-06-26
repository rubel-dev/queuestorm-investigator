from fastapi import APIRouter, HTTPException

from app.models import AnalysisResponse, AnalyzeTicketRequest
from app.services.analyzer import analyze_ticket

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/analyze-ticket", response_model=AnalysisResponse)
def analyze_ticket_endpoint(payload: AnalyzeTicketRequest) -> AnalysisResponse:
    if not payload.ticket_id.strip():
        raise HTTPException(
            status_code=422,
            detail={
                "error": "semantic_validation_error",
                "message": "ticket_id must not be empty.",
            },
        )

    if not payload.complaint.strip():
        raise HTTPException(
            status_code=422,
            detail={
                "error": "semantic_validation_error",
                "message": "complaint must not be empty.",
            },
        )

    return analyze_ticket(payload)
