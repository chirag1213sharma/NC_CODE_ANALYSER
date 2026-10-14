"""
Tests for API Endpoints
"""

import pytest
from fastapi.testclient import TestClient
from src.main import app


client = TestClient(app)


class TestHealthEndpoint:
    """Test health check endpoint."""

    def test_health_check(self):
        """Test health endpoint returns OK."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "version" in data


class TestRootEndpoint:
    """Test root endpoint."""

    def test_root(self):
        """Test root endpoint."""
        response = client.get("/")
        assert response.status_code == 200


class TestFilesAPI:
    """Test file management endpoints."""

    def test_list_files_empty(self):
        """Test listing files when none uploaded."""
        response = client.get("/api/files/list")
        assert response.status_code == 200
        data = response.json()
        assert "files" in data

    def test_upload_invalid_file_type(self):
        """Test that invalid file types are rejected."""
        response = client.post(
            "/api/files/upload",
            files={"file": ("test.pdf", b"fake content", "application/pdf")}
        )
        assert response.status_code == 400

    def test_upload_valid_file(self):
        """Test uploading a valid NC file."""
        nc_content = b"G00 X0 Y0\nG01 X10 Y10 F500"
        response = client.post(
            "/api/files/upload",
            files={"file": ("test.nc", nc_content, "text/plain")}
        )
        assert response.status_code == 200
        data = response.json()
        assert "file_id" in data
        assert data["file_name"] == "test.nc"


class TestCompareAPI:
    """Test comparison endpoints."""

    def test_compare_with_content(self):
        """Test comparison with direct content."""
        response = client.post(
            "/api/compare",
            json={
                "baseline_content": "G00 X0 Y0\nG01 X10 Y10",
                "new_content": "G00 X0 Y0\nG01 X20 Y20",
                "include_ai_classification": False  # Skip AI for faster test
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert "analysis_id" in data
        assert "files_identical" in data
        assert data["files_identical"] == False

    def test_compare_identical_content(self):
        """Test comparison of identical content."""
        content = "G00 X0 Y0\nG01 X10 Y10"
        response = client.post(
            "/api/compare",
            json={
                "baseline_content": content,
                "new_content": content,
                "include_ai_classification": False
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert data["files_identical"] == True

    def test_compare_missing_content(self):
        """Test comparison with missing content."""
        response = client.post(
            "/api/compare",
            json={}
        )
        assert response.status_code == 400


class TestFeedbackAPI:
    """Test feedback endpoints."""

    def test_feedback_stats(self):
        """Test getting feedback stats."""
        response = client.get("/api/feedback/stats")
        assert response.status_code == 200
        data = response.json()
        assert "total_feedback" in data

    def test_recent_feedback(self):
        """Test getting recent feedback."""
        response = client.get("/api/feedback/recent")
        assert response.status_code == 200
        data = response.json()
        assert "feedback" in data

    def test_submit_feedback_missing_analysis(self):
        """Test submitting feedback for non-existent analysis."""
        response = client.post(
            "/api/feedback",
            json={
                "analysis_id": "non-existent-id",
                "classification": "NEUTRAL",
                "notes": "Test",
                "reviewer": "Tester"
            }
        )
        assert response.status_code == 404


class TestReportsAPI:
    """Test report generation endpoints."""

    def test_report_missing_analysis(self):
        """Test getting report for non-existent analysis."""
        response = client.get("/api/reports/non-existent-id")
        assert response.status_code == 404
