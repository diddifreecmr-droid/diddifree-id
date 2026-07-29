"""`GET /.well-known/jwks.json` — contract §2.

Mounted twice by `main.py`: at the domain root, which is where RFC 8615 says
`.well-known` lives and where any standard JWT library looks by default, and
under the API prefix, which is the path the contract document publishes. Same
handler, so the two can never disagree.

Cache headers matter here. Modules are told to cache the key set for about an
hour and to refetch on an unknown `kid`; `max-age` makes that behaviour the
default even for a consumer that forgot to implement it.
"""

from fastapi import APIRouter, Depends, Response

from identity_app.core.deps import get_jwks_query
from identity_app.modules.identity.application.queries import GetJwks

router = APIRouter(tags=["jwks"])

JWKS_MAX_AGE_SECONDS = 3600


@router.get("/.well-known/jwks.json")
async def jwks(response: Response, query: GetJwks = Depends(get_jwks_query)) -> dict:
    response.headers["Cache-Control"] = f"public, max-age={JWKS_MAX_AGE_SECONDS}"
    return await query()
