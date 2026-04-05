# Researcher AI — API package
from fastapi import FastAPI

app = FastAPI()

@app.get("/api/python")
def hello_world():
    return {"message": "Hello from FastAPI on Vercel!"}
