import os
import uvicorn
from web.app import app

if __name__ == "__main__":
    host = os.getenv("JOBSA_HOST", "127.0.0.1")
    port = int(os.getenv("JOBSA_PORT", "8000"))
    uvicorn.run("web.app:app", host=host, port=port, reload=True)
