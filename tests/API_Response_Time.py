"""Performance test: API response times."""
import pytest
import time
import requests
import statistics


class TestAPIPerformance:
    """Test API performance characteristics."""
    
    def test_status_api_response_time(self):
        """Test status API response time."""
        response_times = []
        
        for _ in range(100):
            start = time.time()
            response = requests.get(
                f'{API_URL}/status',
                headers={'x-api-key': API_KEY}
            )
            elapsed = (time.time() - start) * 1000  # ms
            response_times.append(elapsed)
            
            assert response.status_code == 200
        
        # Calculate statistics
        p50 = statistics.median(response_times)
        p95 = sorted(response_times)[int(len(response_times) * 0.95)]
        p99 = sorted(response_times)[int(len(response_times) * 0.99)]
        
        print(f"P50: {p50:.2f}ms, P95: {p95:.2f}ms, P99: {p99:.2f}ms")
        
        # Verify performance targets
        assert p50 < 200, f"P50 {p50:.2f}ms exceeds 200ms target"
        assert p95 < 500, f"P95 {p95:.2f}ms exceeds 500ms target"
        assert p99 < 1000, f"P99 {p99:.2f}ms exceeds 1000ms target"
    
    def test_agent_invocation_response_time(self):
        """Test Bedrock agent invocation response time."""
        response_times = []
        
        for _ in range(20):
            start = time.time()
            response = bedrock_agent.invoke_agent(
                agentId=TEST_AGENT_ID,
                agentAliasId=TEST_ALIAS_ID,
                sessionId=TEST_SESSION_ID,
                inputText="What is the time?"
            )
            elapsed = (time.time() - start) * 1000
            response_times.append(elapsed)
        
        p50 = statistics.median(response_times)
        p95 = sorted(response_times)[int(len(response_times) * 0.95)]
        
        print(f"Agent P50: {p50:.2f}ms, P95: {p95:.2f}ms")
        
        # Agent responses are slower due to LLM inference
        assert p50 < 5000, f"Agent P50 {p50:.2f}ms exceeds 5s target"
        assert p95 < 10000, f"Agent P95 {p95:.2f}ms exceeds 10s target"