"""AI/ML tests: Ticket triage accuracy."""
import pytest


class TestTicketTriageAccuracy:
    """Test ticket triage accuracy."""
    
    TEST_TICKETS = [
        {
            'subject': 'Password reset request',
            'description': 'User cannot log in, needs password reset',
            'expected_category': 'identity',
            'expected_complexity': 'simple',
            'expected_confidence': 0.95
        },
        {
            'subject': 'Server down - critical',
            'description': 'Production server not responding, affecting 100 users',
            'expected_category': 'infrastructure',
            'expected_complexity': 'complex',
            'expected_confidence': 0.90
        },
        {
            'subject': 'Install Microsoft Office',
            'description': 'New employee needs Office installed',
            'expected_category': 'software',
            'expected_complexity': 'simple',
            'expected_confidence': 0.92
        },
        {
            'subject': 'Suspicious email received',
            'description': 'User received phishing email, need security review',
            'expected_category': 'security',
            'expected_complexity': 'complex',
            'expected_confidence': 0.88
        },
    ]
    
    @pytest.mark.parametrize("ticket", TEST_TICKETS)
    def test_ticket_classification(self, ticket):
        """Test ticket classification accuracy."""
        result = triage_orchestrator.classify_ticket(
            subject=ticket['subject'],
            description=ticket['description']
        )
        
        assert result['category'] == ticket['expected_category']
        assert result['complexity'] == ticket['expected_complexity']
        assert result['confidence'] >= ticket['expected_confidence']
    
    def test_overall_accuracy(self):
        """Test overall triage accuracy on test dataset."""
        test_dataset = load_test_dataset('tests/fixtures/ticket_dataset.json')
        
        correct = 0
        total = len(test_dataset)
        
        for ticket in test_dataset:
            result = triage_orchestrator.classify_ticket(
                subject=ticket['subject'],
                description=ticket['description']
            )
            
            if result['category'] == ticket['expected_category']:
                correct += 1
        
        accuracy = correct / total
        print(f"Overall accuracy: {accuracy:.2%}")
        
        assert accuracy >= 0.90, f"Accuracy {accuracy:.2%} below 90% target"