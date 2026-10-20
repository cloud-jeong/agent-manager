"""Print the OpenAPI schema to stdout (used by `make gen-api`)."""

import json

from app.main import app

if __name__ == "__main__":
    print(json.dumps(app.openapi(), indent=2))
