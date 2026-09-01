from fastapi import FastAPI

app = FastAPI(title="slicktrace-core")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "core"}
