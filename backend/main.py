from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from extraction import extract

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/api/test-extract")
async def test_extract(file: UploadFile = File(...)):
    try:
        image_bytes = await file.read()
        result = extract(image_bytes)
        return result.model_dump()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
