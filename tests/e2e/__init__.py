"""End-to-end tests.

Full API workflow tests using FastAPI TestClient:
- Complete upload lifecycle (initiate -> chunk -> complete)
- Multi-tenant isolation verification
- Error handling and edge cases
- Resume-from-offset scenarios
"""
