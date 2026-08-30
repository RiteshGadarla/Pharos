from fastapi import FastAPI

app = FastAPI(title="slicktrace-detection")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "detection"}
