"""Keep the default API test app independent of a reviewer's Bedrock shell settings.

Tests that exercise Bedrock configuration set their own environment after collection.
Clearing these before test modules import ``app.main`` prevents accidental selection of
remote providers in otherwise local fixture tests.
"""

import os


def pytest_configure():
    for name in ("COACHLENS_BEDROCK_ENABLED", "COACHLENS_BEDROCK_REGION",
                 "COACHLENS_BEDROCK_MODEL_ID"):
        os.environ.pop(name, None)
