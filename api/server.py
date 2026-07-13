import logging
import os
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi_clerk_auth import (
    ClerkConfig,
    ClerkHTTPBearer,
    HTTPAuthorizationCredentials,
)
from openai import OpenAI
from pydantic import BaseModel

app = FastAPI()


# Silence access logs for static asset requests (/_next/...)
class _SkipStaticAssets(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return "/_next/" not in record.getMessage()


logging.getLogger("uvicorn.access").addFilter(_SkipStaticAssets())

# Add CORS middleware (allows frontend to call backend)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Clerk authentication setup
clerk_config = ClerkConfig(jwks_url=os.getenv("CLERK_JWKS_URL"))
clerk_guard = ClerkHTTPBearer(clerk_config)


class Visit(BaseModel):
    patient_name: str
    date_of_visit: str
    notes: str


system_prompt = """
You are provided with notes written by a doctor from a patient's visit.
Your job is to summarize the visit for the doctor and provide an email.
Reply with exactly three sections with the headings:
### Summary of visit for the doctor's records
### Next steps for the doctor
### Draft of email to patient in patient-friendly language
"""


def user_prompt_for(visit: Visit) -> str:
    return f"""Create the summary, next steps and draft email for:
Patient Name: {visit.patient_name}
Date of Visit: {visit.date_of_visit}
Notes:
{visit.notes}"""


@app.post("/api/consultation")
def consultation_summary(
    visit: Visit,
    creds: HTTPAuthorizationCredentials = Depends(clerk_guard),
):
    user_id = creds.decoded["sub"]
    client = OpenAI()

    user_prompt = user_prompt_for(visit)
    prompt = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    stream = client.chat.completions.create(
        model="gpt-5-nano",
        messages=prompt,
        stream=True,
    )

    def event_stream():
        for chunk in stream:
            text = chunk.choices[0].delta.content
            if text:
                lines = text.split("\n")
                for line in lines[:-1]:
                    yield f"data: {line}\n\n"
                    yield "data:  \n"
                yield f"data: {lines[-1]}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/health")
def health_check():
    """Health check endpoint (used for local Docker; Lambda does not invoke it)"""
    return {"status": "healthy"}


# Clerk catch-all routes — Next.js exports these as [[...sign-in]]/index.html
# which StaticFiles can't resolve. Serve them explicitly.
static_path = Path("static")

if static_path.exists():

    @app.get("/sign-in")
    @app.get("/sign-in/{path:path}")
    async def serve_sign_in():
        return FileResponse(static_path / "sign-in" / "[[...sign-in]]" / "index.html")

    @app.get("/sign-up")
    @app.get("/sign-up/{path:path}")
    async def serve_sign_up():
        return FileResponse(static_path / "sign-up" / "[[...sign-up]]" / "index.html")

    # All other static files (Next.js export with trailingSlash=true)
    app.mount("/", StaticFiles(directory="static", html=True), name="static")
