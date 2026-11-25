"""AI/ML tests: Knowledge base retrieval."""
import pytest


class TestKnowledgeBaseRetrieval:
    """Test KB retrieval accuracy."""
    
    def test_kb_retrieval_accuracy(self):
        """Test that KB returns relevant documents."""
        # Upload test documents
        test_docs = [
            ('vpn-setup.md', 'How to set up VPN connection...'),
            ('password-policy.md', 'Company password policy requires...'),
            ('software-list.md', 'Approved software list includes...'),
        ]
        
        for filename, content in test_docs:
            upload_to_kb(TEST_TENANT_ID, filename, content)
        
        # Trigger re-ingestion
        trigger_kb_reingestion()
        wait_for_ingestion_complete()
        
        # Query KB
        queries = [
            ('How do I connect to VPN?', 'vpn-setup.md'),
            ('What is the password policy?', 'password-policy.md'),
            ('What software can I install?', 'software-list.md'),
        ]
        
        correct = 0
        for query, expected_doc in queries:
            results = query_kb(TEST_TENANT_ID, query)
            
            # Verify expected document is in top results
            top_result = results[0]['metadata']['source']
            if expected_doc in top_result:
                correct += 1
        
        accuracy = correct / len(queries)
        print(f"KB retrieval accuracy: {accuracy:.2%}")
        
        assert accuracy >= 0.85, f"KB accuracy {accuracy:.2%} below 85% target"