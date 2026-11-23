"""
Tests for calendar_tools.py — focusing on find_free_time logic.
"""

import pytest
import sys
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src_calendar_tools'))


# =============================================================================
# HELPER FUNCTION TESTS
# =============================================================================

class TestParseGraphDatetime:
    """Tests for _parse_graph_datetime helper."""
    
    def test_parse_iso_with_z(self):
        import calendar_tools
        result = calendar_tools._parse_graph_datetime({
            'dateTime': '2026-11-16T14:00:00Z',
            'timeZone': 'UTC'
        })
        assert result == datetime(2026, 11, 16, 14, 0, 0, tzinfo=timezone.utc)
    
    def test_parse_iso_with_fractional_seconds(self):
        import calendar_tools
        result = calendar_tools._parse_graph_datetime({
            'dateTime': '2026-11-16T14:00:00.0000000',
            'timeZone': 'Eastern Standard Time'
        })
        assert result.year == 2026
        assert result.month == 11
        assert result.day == 16
    
    def test_parse_empty_object(self):
        import calendar_tools
        result = calendar_tools._parse_graph_datetime({})
        assert result is None
    
    def test_parse_none(self):
        import calendar_tools
        result = calendar_tools._parse_graph_datetime(None)
        assert result is None


class TestRoundUpToQuarter:
    """Tests for _round_up_to_quarter helper."""
    
    def test_already_on_quarter(self):
        import calendar_tools
        dt = datetime(2026, 11, 16, 14, 0, 0, tzinfo=timezone.utc)
        result = calendar_tools._round_up_to_quarter(dt)
        assert result == dt
    
    def test_round_up_from_1(self):
        import calendar_tools
        dt = datetime(2026, 11, 16, 14, 1, 0, tzinfo=timezone.utc)
        result = calendar_tools._round_up_to_quarter(dt)
        assert result.minute == 15
    
    def test_round_up_from_16(self):
        import calendar_tools
        dt = datetime(2026, 11, 16, 14, 16, 0, tzinfo=timezone.utc)
        result = calendar_tools._round_up_to_quarter(dt)
        assert result.minute == 30
    
    def test_round_up_from_46(self):
        import calendar_tools
        dt = datetime(2026, 11, 16, 14, 46, 0, tzinfo=timezone.utc)
        result = calendar_tools._round_up_to_quarter(dt)
        assert result.hour == 15
        assert result.minute == 0


class TestMergeOverlapping:
    """Tests for _merge_overlapping helper."""
    
    def test_no_overlap(self):
        import calendar_tools
        periods = [
            (datetime(2026, 11, 16, 10, 0, tzinfo=timezone.utc), datetime(2026, 11, 16, 11, 0, tzinfo=timezone.utc)),
            (datetime(2026, 11, 16, 13, 0, tzinfo=timezone.utc), datetime(2026, 11, 16, 14, 0, tzinfo=timezone.utc)),
        ]
        result = calendar_tools._merge_overlapping(periods)
        assert len(result) == 2
    
    def test_overlap(self):
        import calendar_tools
        periods = [
            (datetime(2026, 11, 16, 10, 0, tzinfo=timezone.utc), datetime(2026, 11, 16, 11, 30, tzinfo=timezone.utc)),
            (datetime(2026, 11, 16, 10, 30, tzinfo=timezone.utc), datetime(2026, 11, 16, 11, 0, tzinfo=timezone.utc)),
        ]
        result = calendar_tools._merge_overlapping(periods)
        assert len(result) == 1
        assert result[0][0].hour == 10
        assert result[0][1].hour == 11
        assert result[0][1].minute == 30
    
    def test_adjacent(self):
        import calendar_tools
        periods = [
            (datetime(2026, 11, 16, 10, 0, tzinfo=timezone.utc), datetime(2026, 11, 16, 11, 0, tzinfo=timezone.utc)),
            (datetime(2026, 11, 16, 11, 0, tzinfo=timezone.utc), datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)),
        ]
        result = calendar_tools._merge_overlapping(periods)
        assert len(result) == 1
        assert result[0][0].hour == 10
        assert result[0][1].hour == 12
    
    def test_empty_list(self):
        import calendar_tools
        result = calendar_tools._merge_overlapping([])
        assert result == []


class TestFindFreeSlots:
    """Tests for _find_free_slots helper."""
    
    def test_no_busy_periods(self):
        import calendar_tools
        window_start = datetime(2026, 11, 16, 9, 0, tzinfo=timezone.utc)
        window_end = datetime(2026, 11, 16, 17, 0, tzinfo=timezone.utc)
        
        slots = calendar_tools._find_free_slots(
            busy_periods=[],
            window_start=window_start,
            window_end=window_end,
            duration_minutes=60,
            limit=5
        )
        
        assert len(slots) == 5
        assert slots[0]['time'] == '09:00'
        assert slots[1]['time'] == '09:15'
    
    def test_single_busy_period(self):
        import calendar_tools
        window_start = datetime(2026, 11, 16, 9, 0, tzinfo=timezone.utc)
        window_end = datetime(2026, 11, 16, 17, 0, tzinfo=timezone.utc)
        busy = [
            (datetime(2026, 11, 16, 10, 0, tzinfo=timezone.utc),
             datetime(2026, 11, 16, 11, 0, tzinfo=timezone.utc))
        ]
        
        slots = calendar_tools._find_free_slots(
            busy_periods=busy,
            window_start=window_start,
            window_end=window_end,
            duration_minutes=60,
            limit=5
        )
        
        # Should skip 10:00-11:00
        assert all(not (s['time'] >= '10:00' and s['time'] < '11:00') for s in slots)
    
    def test_working_hours_filter(self):
        import calendar_tools
        window_start = datetime(2026, 11, 16, 0, 0, tzinfo=timezone.utc)
        window_end = datetime(2026, 11, 17, 0, 0, tzinfo=timezone.utc)
        
        slots = calendar_tools._find_free_slots(
            busy_periods=[],
            window_start=window_start,
            window_end=window_end,
            duration_minutes=60,
            limit=10,
            work_start_hour=9,
            work_end_hour=17
        )
        
        # All slots should be between 9:00 and 17:00
        assert all(9 <= int(s['time'].split(':')[0]) < 17 for s in slots)
    
    def test_skip_weekends(self):
        import calendar_tools
        # Start on Friday
        window_start = datetime(2026, 11, 13, 9, 0, tzinfo=timezone.utc)  # Friday
        window_end = datetime(2026, 11, 16, 17, 0, tzinfo=timezone.utc)   # Monday
        
        slots = calendar_tools._find_free_slots(
            busy_periods=[],
            window_start=window_start,
            window_end=window_end,
            duration_minutes=60,
            limit=10,
            skip_weekends=True
        )
        
        # No slots on Saturday or Sunday
        assert all(s['day_of_week'] not in ['Saturday', 'Sunday'] for s in slots)
    
    def test_duration_too_long(self):
        import calendar_tools
        window_start = datetime(2026, 11, 16, 9, 0, tzinfo=timezone.utc)
        window_end = datetime(2026, 11, 16, 10, 0, tzinfo=timezone.utc)  # Only 1 hour
        
        slots = calendar_tools._find_free_slots(
            busy_periods=[],
            window_start=window_start,
            window_end=window_end,
            duration_minutes=120,  # 2 hours - won't fit
            limit=5
        )
        
        assert len(slots) == 0
    
    def test_limit_respected(self):
        import calendar_tools
        window_start = datetime(2026, 11, 16, 9, 0, tzinfo=timezone.utc)
        window_end = datetime(2026, 11, 16, 17, 0, tzinfo=timezone.utc)
        
        slots = calendar_tools._find_free_slots(
            busy_periods=[],
            window_start=window_start,
            window_end=window_end,
            duration_minutes=30,
            limit=3
        )
        
        assert len(slots) == 3


# =============================================================================
# INTEGRATION TEST
# =============================================================================

class TestToolFindFreeTime:
    """Integration tests for tool_find_free_time."""
    
    def test_empty_calendar(self):
        """User with no events should get slots across the whole window."""
        import calendar_tools
        
        with patch('calendar_tools.graph_request') as mock_graph:
            mock_graph.return_value = {
                'value': [{
                    'scheduleItems': []
                }]
            }
            
            identity = {'user_email': 'user@example.com'}
            params = {
                'duration_minutes': '60',
                'hours_ahead': '24',
                'limit': '5'
            }
            
            result = calendar_tools.tool_find_free_time(params, identity)
            
            assert result['success'] is True
            assert result['count'] == 5
            assert len(result['slots']) == 5
    
    def test_calendar_with_events(self):
        """User with events should get slots around those events."""
        import calendar_tools
        
        with patch('calendar_tools.graph_request') as mock_graph:
            mock_graph.return_value = {
                'value': [{
                    'scheduleItems': [
                        {
                            'subject': 'Team Meeting',
                            'start': {'dateTime': '2026-11-16T10:00:00', 'timeZone': 'UTC'},
                            'end': {'dateTime': '2026-11-16T11:00:00', 'timeZone': 'UTC'}
                        },
                        {
                            'subject': 'Lunch',
                            'start': {'dateTime': '2026-11-16T12:00:00', 'timeZone': 'UTC'},
                            'end': {'dateTime': '2026-11-16T13:00:00', 'timeZone': 'UTC'}
                        }
                    ]
                }]
            }
            
            identity = {'user_email': 'user@example.com'}
            params = {
                'duration_minutes': '60',
                'hours_ahead': '24',
                'limit': '5'
            }
            
            result = calendar_tools.tool_find_free_time(params, identity)
            
            assert result['success'] is True
            # Slots should not overlap with 10:00-11:00 or 12:00-13:00
            for slot in result['slots']:
                start = datetime.fromisoformat(slot['start'])
                end = datetime.fromisoformat(slot['end'])
                # Check no overlap with busy periods
                assert not (start < datetime(2026, 11, 16, 11, 0, tzinfo=timezone.utc) and
                           end > datetime(2026, 11, 16, 10, 0, tzinfo=timezone.utc))
    
    def test_missing_user_email(self):
        """Should fail gracefully if user email is not available."""
        import calendar_tools
        
        identity = {}  # No user_email
        params = {'duration_minutes': '60'}
        
        result = calendar_tools.tool_find_free_time(params, identity)
        
        assert result['success'] is False
        assert 'email' in result['error'].lower()
    
    def test_invalid_duration(self):
        """Should reject durations outside valid range."""
        import calendar_tools
        
        identity = {'user_email': 'user@example.com'}
        params = {'duration_minutes': '5'}  # Too short
        
        result = calendar_tools.tool_find_free_time(params, identity)
        
        assert result['success'] is False
        assert 'duration' in result['error'].lower()