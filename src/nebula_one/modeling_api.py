from fastapi import APIRouter, Request
from .services.modeling_handoff import HandoffStart, HandoffCredentials, HandoffCandidate, ModelingHandoffService

router = APIRouter(prefix="/api/v1/modeling")


def service(request):
    return ModelingHandoffService(request.app.state.container)


@router.get("/configuration")
def configuration(request: Request):
    return service(request).configuration()


@router.post("/handoffs", status_code=201)
def start(payload: HandoffStart, request: Request):
    return service(request).start(payload)


@router.post("/handoffs/{handoff_id}/preview")
def preview(handoff_id: str, payload: HandoffCandidate, request: Request):
    return service(request).preview(handoff_id, payload)


@router.post("/handoffs/{handoff_id}/confirm")
def confirm(handoff_id: str, payload: HandoffCandidate, request: Request):
    return service(request).confirm(handoff_id, payload)


@router.post("/handoffs/{handoff_id}/cancel")
def cancel(handoff_id: str, payload: HandoffCredentials, request: Request):
    return service(request).cancel(handoff_id, payload)
