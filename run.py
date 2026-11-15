import os
import uvicorn
from app.config import settings

if __name__ == "__main__":
    port = int(os.environ.get("PORT", settings.port))
    print(f"Starting Synspeak Study Concentration Monitoring System on http://0.0.0.0:{port} ...")
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=port,
        reload=False,
        log_level="info",
        http="h11",
        ws="websockets"
    )
