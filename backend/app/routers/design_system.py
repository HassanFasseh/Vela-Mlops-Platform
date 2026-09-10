"""
Design-system preview (Phase 1 of the 2026-09 redesign).

Serves the single /design page that renders every design token and core
primitive together so the whole visual language can be reviewed in one
place. It loads only the ds/* stylesheet bundle
(static/css/ds/{tokens,base,primitives,shell}.css) and touches no
database and no auth — it is a static style catalog.

Unauthenticated for now, and deliberately not linked from any nav. It
carries no product data; remove this router (and static/design.html)
once Phase 2 migration is complete, or gate it behind an admin check if
it should stay.
"""

import os

from fastapi import APIRouter
from fastapi.responses import FileResponse

router = APIRouter()

_DESIGN_HTML = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "static", "design.html"
)


@router.get("/design", include_in_schema=False)
def design_system_preview():
    return FileResponse(_DESIGN_HTML, media_type="text/html")
