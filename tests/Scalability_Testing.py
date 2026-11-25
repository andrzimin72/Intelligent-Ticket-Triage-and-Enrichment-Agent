"""Performance test: Scalability."""
import pytest
import concurrent.futures
import time


class TestScalability:
    """Test platform scalability."""
    
    def test_concurrent_tenant_onboarding(self):
        """Test onboarding multiple tenants concurrently."""
        num_tenants = 10
        
        def onboard_tenant(i):
            tenant_data = {
                'tenant_id': f'scale-test-{i}',
                'display_name': f'Scale Test {i}',
                'entra_tenant_id': f'55555555-5555-5555-5555-{i:012d}',
                'admin_group_id': f'eeeeeeee-eeee-eeee-eeee-{i:012d}',
                'contact_email': f'admin@scale-test-{i}.com'
            }
            
            start = time.time()
            response = requests.post(
                f'{API_URL}/tenants',
                headers={'x-api-key': API_KEY},
                json=tenant_data
            )
            elapsed = time.time() - start
            
            return response.status_code, elapsed
        
        # Onboard tenants concurrently
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(onboard_tenant, i) 
                      for i in range(num_tenants)]
            
            results = [f.result() for f in concurrent.futures.as_completed(futures)]
        
        # Verify all succeeded
        status_codes = [r[0] for r in results]
        assert all(code == 202 for code in status_codes)
        
        # Verify average onboarding time
        avg_time = sum(r[1] for r in results) / len(results)
        assert avg_time < 10, f"Average onboarding time {avg_time:.2f}s exceeds 10s"
        
        # Cleanup
        for i in range(num_tenants):
            requests.delete(
                f'{API_URL}/tenants/scale-test-{i}?confirm=true',
                headers={'x-api-key': API_KEY}
            )
    
    def test_concurrent_agent_invocations(self):
        """Test concurrent agent invocations."""
        num_invocations = 20
        
        def invoke_agent(i):
            start = time.time()
            response = bedrock_agent.invoke_agent(
                agentId=TEST_AGENT_ID,
                agentAliasId=TEST_ALIAS_ID,
                sessionId=f'session-{i}',
                inputText=f'Test message {i}'
            )
            elapsed = time.time() - start
            return elapsed
        
        # Invoke agents concurrently
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(invoke_agent, i) 
                      for i in range(num_invocations)]
            
            results = [f.result() for f in concurrent.futures.as_completed(futures)]
        
        # Verify performance under load
        avg_time = sum(results) / len(results)
        p95 = sorted(results)[int(len(results) * 0.95)]
        
        print(f"Concurrent invocations - Avg: {avg_time:.2f}s, P95: {p95:.2f}s")
        
        assert avg_time < 10, f"Average time {avg_time:.2f}s exceeds 10s"
        assert p95 < 15, f"P95 time {p95:.2f}s exceeds 15s"