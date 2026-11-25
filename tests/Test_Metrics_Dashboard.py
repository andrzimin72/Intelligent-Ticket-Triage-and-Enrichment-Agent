"""Test metrics collection and reporting."""
import pytest
import json
from datetime import datetime


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Generate test summary report."""
    total = terminalreporter._numcollected
    passed = len(terminalreporter.stats.get('passed', []))
    failed = len(terminalreporter.stats.get('failed', []))
    skipped = len(terminalreporter.stats.get('skipped', []))
    
    report = {
        'timestamp': datetime.now().isoformat(),
        'total': total,
        'passed': passed,
        'failed': failed,
        'skipped': skipped,
        'pass_rate': (passed / total * 100) if total > 0 else 0,
    }
    
    # Save report
    with open('test-report.json', 'w') as f:
        json.dump(report, f, indent=2)
    
    # Print summary
    print(f"\n{'='*60}")
    print(f"Test Summary")
    print(f"{'='*60}")
    print(f"Total:   {total}")
    print(f"Passed:  {passed}")
    print(f"Failed:  {failed}")
    print(f"Skipped: {skipped}")
    print(f"Pass Rate: {report['pass_rate']:.2f}%")
    print(f"{'='*60}")