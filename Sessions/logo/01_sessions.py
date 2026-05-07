#!/usr/bin/env python3
"""
Full end-to-end production script with member-wise viewership sessions:
1. Query events from Postgres based on user-given date range (using events_with_hhid table)
2. Convert timestamps to UTC+4 (Yerevan)
3. Add member IDs
4. Split into daily files (02:00–01:59)
5. Extract channels (type 29/30)
6. Create member-wise viewership sessions
"""

import os
import glob
import json
import ast
import pandas as pd
from datetime import datetime, timedelta
import psycopg2
import re
from dataclasses import dataclass, asdict
from typing import Dict, List, Any, Optional, Set, Tuple
from collections import defaultdict
import yaml

# ============================================================================
# CONFIGURATION SECTION
# ============================================================================

@dataclass
class Config:
    """Central configuration for all rules and logic"""

    # File paths
    output_dir: str = 'household_viewership_memberwise_output'

    # Event type definitions
    event_types: Dict[str, int] = None

    # TV OFF/ON threshold configuration
    tv_on_off_threshold: Dict[str, Any] = None 

    # Member declaration configuration
    member_declaration: Dict[str, Any] = None

    # Rule 1: Type 30 bridging configuration
    type30_bridge: Dict[str, Any] = None

    # Rule 2: View session grouping configuration
    session_grouping: Dict[str, Any] = None

    # Rule 3: Session boundary configuration
    session_boundary: Dict[str, Any] = None

    # Backward bridging configuration
    backward_bridge: Dict[str, Any] = None

    # Date filtering configuration
    date_filtering: Dict[str, Any] = None

    def __post_init__(self):
        """Set default configurations"""
        if self.event_types is None:
            self.event_types = {
                'member_declaration': 3,
                'guest_declaration': 4,
                'tv_on_off': 23,
                'logo_recognized': 29,
                'logo_unrecognized': 30
            }
        if self.tv_on_off_threshold is None:
            self.tv_on_off_threshold = {
                'enabled': True,
                'threshold_seconds': 120,  # Default 120 seconds
                'check_channel_continuity': True
            }
        if self.member_declaration is None:
            self.member_declaration = {
                'enabled': True,
                'bridge_to_first_member': True,
                'treat_guest_as_member': True,
            }

        if self.type30_bridge is None:
            self.type30_bridge = {
                'enabled': True,
                'max_consecutive': 48,
                'require_same_channel': True,
                'convert_to_type': 29
            }

        if self.session_grouping is None:
            self.session_grouping = {
                'max_gap_seconds': 10,
                'require_same_channel': True
            }

        if self.session_boundary is None:
            self.session_boundary = {
                'first_session_start': 'tv_on',
                'last_session_end': 'tv_off',
                'middle_session_start': 'event',
                'middle_session_end': 'next_event_start'
            }

        if self.backward_bridge is None:
            self.backward_bridge = {
                'enabled': True,
                'bridge_pre_declaration_sessions': True,
                'max_minutes_before_declaration': 10  # Maximum minutes to bridge backward
            }

        if self.date_filtering is None:
            self.date_filtering = {
                'enabled': True,
                'validate_date_presence': True  # Validate that output dates exist in input file
            }


# ============================================================================
# DATA STRUCTURES FOR MEMBER TRACKING
# ============================================================================

class MemberState:
    """Track state of a single member"""

    def __init__(self, member_id: str, age: int = None, gender: str = None):
        self.member_id = member_id
        self.age = age
        self.gender = gender
        self.is_active = False
        self.activation_time = None
        self.deactivation_time = None
        self.events = []  # Viewing events during active period

    def activate(self, time_str: str, age: int = None, gender: str = None):
        """Activate member at given time"""
        self.is_active = True
        self.activation_time = time_str
        if age is not None:
            self.age = age
        if gender is not None:
            self.gender = gender
        self.events = []  # Start new event collection

    def get_member_info_string(self) -> str:
        """Return formatted member info as 'id,age,gender'"""
        if not self.member_id:
            return ""
        return self.member_id

    def deactivate(self, time_str: str):
        """Deactivate member at given time"""
        self.is_active = False
        self.deactivation_time = time_str

    def add_event(self, event: Dict):
        """Add viewing event to member's timeline"""
        self.events.append(event)


class HouseholdState:
    """Track state of a household including all members"""

    def __init__(self, hhid: str, config: Config):
        self.hhid = hhid
        self.config = config
        self.members: Dict[str, MemberState] = {}  # member_id -> MemberState
        self.active_member_ids: Set[str] = set()   # Currently active members
        self.anonymous_events: List[Dict] = []     # Events when no member active

    def process_member_declaration(self, event: Dict):
        """Process member/guest declaration event"""
        try:
            details = json.loads(event['details']) if isinstance(event['details'], str) else event['details']
            members_list = details.get('members', [])

            for member_data in members_list:
                member_id = member_data.get('id')
                is_active = member_data.get('active', False)
                age = member_data.get('age')
                gender = member_data.get('gender')

                if member_id not in self.members:
                    self.members[member_id] = MemberState(member_id, age, gender)

                member = self.members[member_id]

                if is_active:
                    # Member is being activated
                    if not member.is_active:
                        member.activate(event['datetime_str'], age, gender)
                        self.active_member_ids.add(member_id)
                else:
                    # Member is being deactivated
                    if member.is_active:
                        member.deactivate(event['datetime_str'])
                        self.active_member_ids.discard(member_id)

        except (json.JSONDecodeError, KeyError) as e:
            print(f"Error parsing member declaration: {e}")

    def process_viewing_event(self, event: Dict):
        """Process viewing event (type 29, 30) and assign to appropriate member(s)"""
        if self.active_member_ids:
            # Assign to all currently active members
            for member_id in self.active_member_ids:
                self.members[member_id].add_event(event)
        else:
            # No active members - this is anonymous viewing
            self.anonymous_events.append(event)


# ============================================================================
# RULE ENGINE
# ============================================================================

class RuleEngine:
    """Engine to apply configurable rules"""

    def __init__(self, config: Config):
        self.config = config

    def bridge_type30_events(self, logo_df: pd.DataFrame) -> pd.DataFrame:
        """Bridge type 30 events when they appear between type 29 events of same channel"""
        if not self.config.type30_bridge['enabled']:
            return logo_df

        logo_df = logo_df.copy()
        i = 0

        while i < len(logo_df):
            if logo_df.loc[i, 'type'] == self.config.event_types['logo_unrecognized']:
                start_idx = i
                target_type = self.config.event_types['logo_unrecognized']

                # Count consecutive type 30 events
                while i < len(logo_df) and logo_df.loc[i, 'type'] == target_type:
                    i += 1
                end_idx = i - 1
                type30_count = end_idx - start_idx + 1

                # Check if we have <= max_consecutive type 30 events
                if type30_count <= self.config.type30_bridge['max_consecutive']:
                    # Check if there's a type 29 event before and after
                    has_before = start_idx > 0
                    has_after = end_idx < len(logo_df) - 1

                    if has_before and has_after:
                        before_type = logo_df.loc[start_idx - 1, 'type']
                        after_type = logo_df.loc[end_idx + 1, 'type']
                        target_before = self.config.event_types['logo_recognized']
                        target_after = self.config.event_types['logo_recognized']

                        if before_type == target_before and after_type == target_after:
                            if self.config.type30_bridge['require_same_channel']:
                                before_channel = logo_df.loc[start_idx - 1, 'channel']
                                after_channel = logo_df.loc[end_idx + 1, 'channel']

                                if before_channel == after_channel:
                                    self._convert_type30_to_type29(
                                        logo_df, start_idx, end_idx, before_channel
                                    )
                            else:
                                # If not requiring same channel, use the before channel
                                before_channel = logo_df.loc[start_idx - 1, 'channel']
                                self._convert_type30_to_type29(
                                    logo_df, start_idx, end_idx, before_channel
                                )
            else:
                i += 1

        return logo_df

    def _convert_type30_to_type29(self, df: pd.DataFrame, start_idx: int,
                                   end_idx: int, channel: str):
        """Helper to convert type 30 events to type 29"""
        for j in range(start_idx, end_idx + 1):
            df.loc[j, 'type'] = self.config.type30_bridge['convert_to_type']
            df.loc[j, 'channel'] = channel


# ============================================================================
# DURATION CALCULATION FUNCTIONS
# ============================================================================

def format_duration(seconds: float) -> str:
    """Convert seconds to HH:MM:SS format"""
    if pd.isna(seconds) or seconds < 0:
        return "00:00:00"

    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)

    return f"{hours:02d}:{minutes:02d}:{secs:02d}"

def calculate_duration_with_date(date_str: str, start_time_str: str, end_time_str: str) -> str:
    """Calculate duration handling midnight crossover by combining with date"""
    try:
        # Combine date with time
        start_datetime = pd.to_datetime(f"{date_str} {start_time_str}")
        end_datetime = pd.to_datetime(f"{date_str} {end_time_str}")

        # If end time is earlier than start time, assume it's the next day
        if end_datetime < start_datetime:
            end_datetime = pd.to_datetime(f"{date_str} {end_time_str}") + pd.Timedelta(days=1)

        duration_seconds = (end_datetime - start_datetime).total_seconds()
        return format_duration(duration_seconds)
    except Exception as e:
        print(f"Error calculating duration: date={date_str}, start={start_time_str}, end={end_time_str}, error={e}")
        return "00:00:00"


# ============================================================================
# DATABASE FUNCTIONS
# ============================================================================

def fetch_events_from_postgres(start_date_str, end_date_str, db_config):
    """Query events from events_with_hhid table in PostgreSQL"""
    # Parse input dates
    start_dt_local = pd.Timestamp(f"{start_date_str} 02:00:00").tz_localize('Asia/Yerevan')
    end_dt_local = pd.Timestamp(f"{end_date_str} 01:59:59") + pd.Timedelta(days=1)
    end_dt_local = end_dt_local.tz_localize('Asia/Yerevan')

    # Convert to UTC for querying Postgres
    start_ts = int(start_dt_local.tz_convert('UTC').timestamp())
    end_ts = int(end_dt_local.tz_convert('UTC').timestamp())

    query = f"""
    SELECT *
    FROM events_with_assigned_hhid
    WHERE type IN ('29','30', '23','3','4')
      AND timestamp BETWEEN {start_ts} AND {end_ts}
    ORDER BY hhid ASC, timestamp ASC;
    """
    print(f"📌 Querying events from {start_dt_local} to {end_dt_local} (UNIX: {start_ts} → {end_ts})")
    conn = psycopg2.connect(**db_config)
    df = pd.read_sql(query, conn)
    conn.close()
    print(f"✅ Fetched {len(df)} rows from events_with_assigned_hhid table")
    return df


# ============================================================================
# DATA PROCESSING FUNCTIONS
# ============================================================================

def convert_timestamp(df):
    """Convert timestamp to UTC+4 (Yerevan)"""
    timestamp_cols = [c for c in df.columns if 'timestamp' in c.lower()]
    if not timestamp_cols:
        print("No timestamp column found!")
        return df
    ts_col = timestamp_cols[0]
    print(f"Converting '{ts_col}' to UTC+4 (Yerevan)")

    datetime_utc = pd.to_datetime(df[ts_col], unit='s', utc=True)
    datetime_local = datetime_utc.dt.tz_convert('Asia/Yerevan')
    df['date'] = datetime_local.dt.date
    df['time'] = datetime_local.dt.time
    df['datetime_str'] = datetime_local.dt.tz_localize(None).dt.strftime('%Y-%m-%d %H:%M:%S')
    return df

def add_member_ids(df):
    """Add member IDs and ensure details is valid JSON"""
    def assign_ids(details):
        if pd.isna(details):
            return json.dumps({})
        
        # If details is already a dict
        if isinstance(details, dict):
            details_dict = details
        # If details is a string
        elif isinstance(details, str):
            if details.strip() == '':
                return json.dumps({})
            try:
                # Try loading as JSON
                details_dict = json.loads(details)
            except json.JSONDecodeError:
                try:
                    # Fallback to literal_eval
                    details_dict = ast.literal_eval(details)
                except:
                    # If it's not valid JSON or dict-like, return as-is
                    return json.dumps({"value": details})
        else:
            # Any other type
            return json.dumps({"value": str(details)})
        
        # Process member IDs if this is type 3
        if 'members' in details_dict and isinstance(details_dict['members'], list):
            for i, m in enumerate(details_dict['members'], 1):
                m['id'] = f"M{i}"
        
        return json.dumps(details_dict)

    df['details'] = df['details'].apply(assign_ids)
    return df

def extract_channels(df):
    """Extract channels from details field"""
    df['channel'] = ''

    def safe_extract(details):
        if pd.isna(details):
            return ''
        
        # Handle string details
        if isinstance(details, str):
            if details.strip() == '':
                return ''
            try:
                data = json.loads(details)
            except json.JSONDecodeError:
                try:
                    data = ast.literal_eval(details)
                except:
                    return ''
        # Handle dict details (from previous step)
        elif isinstance(details, dict):
            data = details
        else:
            return ''
        
        # Extract label if data is a dict
        if isinstance(data, dict):
            return data.get('label', '')
        return ''

    mask_29 = df['type'] == 29
    mask_30 = df['type'] == 30
    
    # Apply channel extraction
    if mask_29.any():
        df.loc[mask_29, 'channel'] = df.loc[mask_29, 'details'].apply(safe_extract).astype(str).str.strip()
    
    if mask_30.any():
        df.loc[mask_30, 'channel'] = 'Others'
    
    return df

def deduplicate_type3_events(df: pd.DataFrame) -> pd.DataFrame:
    """
    For type 3 events, remove duplicates sharing the same hhid + timestamp,
    keeping the row with the higher 'id'.
    """
    type3_mask = df['type'].astype(str) == '3'
    type3_df = df[type3_mask].copy()
    other_df = df[~type3_mask].copy()

    if type3_df.empty:
        return df

    before = len(type3_df)

    # Within each hhid + timestamp group, keep the row with the highest id
    type3_df = (
        type3_df
        .sort_values('id', ascending=False)
        .drop_duplicates(subset=['hhid', 'timestamp'], keep='first')
    )

    after = len(type3_df)
    removed = before - after
    if removed > 0:
        print(f"✅ Deduplication: Removed {removed} type-3 duplicate(s) (kept higher id per hhid+timestamp)")

    return pd.concat([type3_df, other_df], ignore_index=True).sort_values(
        ['hhid', 'datetime_str']
    ).reset_index(drop=True)


# ============================================================================
# MEMBER-WISE SESSION PROCESSOR
# ============================================================================

class MemberViewershipProcessor:
    """Main processor with member-aware viewership tracking"""

    def __init__(self, config: Config):
        self.config = config
        self.rule_engine = RuleEngine(config)

    def process_dataframe(self, df: pd.DataFrame, output_dir: str, file_date: str = None) -> int:
        """Process a DataFrame with member tracking - pipeline version"""
        try:
            print(f"Processing data for date range...")

            # Convert datetime
            df['datetime'] = pd.to_datetime(df['datetime_str'], errors='coerce')
            df = df.dropna(subset=['datetime'])

            # Get all unique dates present in this input file
            input_dates = set(df['datetime'].dt.date.astype(str).unique())
            print(f"  Dates present in data: {sorted(input_dates)}")

            # Sort globally
            df = df.sort_values(['hhid', 'datetime']).reset_index(drop=True)

            # Output collection
            output_rows = []

            # Process each household
            for hhid, group in df.groupby('hhid'):
                group = group.sort_values('datetime').reset_index(drop=True)
                
                # First, create sessions WITHOUT member assignment (like household script)
                household_sessions = self._create_household_sessions(hhid, group)
                
                # Now assign members to these sessions
                member_assigned_sessions = self._assign_members_to_sessions(hhid, group, household_sessions)
                
                # Add to output
                output_rows.extend(member_assigned_sessions)

            # Save output
            if output_rows:
                output_df = pd.DataFrame(output_rows)

                # Apply date filtering to output if enabled
                if self.config.date_filtering['enabled']:
                    # Filter output to only include sessions with dates that exist in the input file
                    original_output_count = len(output_df)
                    
                    # Keep only rows where date is in the set of dates from the input file
                    output_df = output_df[output_df['date'].isin(input_dates)].copy()
                    
                    filtered_count = original_output_count - len(output_df)
                    if filtered_count > 0:
                        print(f"  Date filtering: Removed {filtered_count} sessions with dates not present in input file")
                        
                        # Get the dates that were removed (from the original output before filtering)
                        original_output_df = pd.DataFrame(output_rows)
                        removed_dates = set(original_output_df['date'].unique()) - input_dates
                        if removed_dates:
                            print(f"  Removed dates: {sorted(removed_dates)}")
                    
                    # Also check if any dates were created that weren't in the input
                    output_dates = set(output_df['date'].unique())
                    if output_dates - input_dates:
                        print(f"  Warning: Output contains dates not in input: {sorted(output_dates - input_dates)}")

                # Calculate duration column
                output_df['duration'] = output_df.apply(
                    lambda row: calculate_duration_with_date(row['date'], row['start_time'], row['end_time']),
                    axis=1
                )

                # Format member_id with age and gender (using the last household state)
                temp_household_state = HouseholdState(hhid, self.config)
                for _, group in df.groupby('hhid'):
                    for _, row in group.iterrows():
                        if row['type'] in [self.config.event_types['member_declaration'],
                                          self.config.event_types['guest_declaration']]:
                            temp_household_state.process_member_declaration(row.to_dict())
                
                # Format member_id with age and gender
                def format_member_id(row):
                    if not row['member_id'] or row['member_id'] == "":
                        return ""
                    
                    member_id = row['member_id']
                    
                    if member_id in temp_household_state.members:
                        member = temp_household_state.members[member_id]
                        return member.get_member_info_string()  # Now only ID
                    return member_id  # Return as-is if not found
                
                output_df['member_id'] = output_df.apply(format_member_id, axis=1)

                # Select only the columns we need for output
                output_columns = ['date', 'hhid', 'tv_set', 'member_id', 'channel', 'start_time', 'end_time', 'duration', 'duration_seconds']
                output_df = output_df[output_columns]

                output_df = output_df.sort_values(['hhid', 'member_id', 'date', 'start_time']).reset_index(drop=True)

                # Create filename based on date range or specific date
                if file_date:
                    output_filename = f"{file_date}_logo_sessions.csv"
                else:
                    # Use date range from input
                    date_range = f"{min(input_dates)}_to_{max(input_dates)}"
                    output_filename = f"{date_range}_logo_sessions.csv"
                
                output_path = os.path.join(output_dir, output_filename)
                output_df.to_csv(output_path, index=False)
                print(f"  Saved to: {output_path}")
                print(f"  Rows saved: {len(output_df)}")
                print(f"  Output dates: {sorted(output_df['date'].unique())}")
                return len(output_df)
            else:
                print(f"  No viewing sessions found")
                return 0

        except Exception as e:
            print(f"  Error: {e}")
            import traceback
            traceback.print_exc()
            return 0

    def _create_household_sessions(self, hhid: str, group: pd.DataFrame) -> List[Dict]:
        """Create household sessions with TV OFF/ON threshold rule"""
        sessions = []
        
        # Track TV state and events
        tv_on_time_str = None
        tv_off_time_str = None  # Track when TV was turned off
        tv_off_channel = None   # Track channel at TV OFF
        logo_events = []
        
        # Get threshold from config
        threshold_seconds = self.config.tv_on_off_threshold['threshold_seconds']
        check_channel = self.config.tv_on_off_threshold['check_channel_continuity']
        
        for idx, row in group.iterrows():
            if row['type'] == self.config.event_types['tv_on_off']:
                # TV on/off event
                try:
                    details = json.loads(row['details']) if isinstance(row['details'], str) else row['details']
                    state = details.get('state')
                except:
                    state = None
                
                if state is True:  # TV turned ON
                    current_time = row['datetime_str']
                    
                    # Check if we had a recent TV OFF within threshold
                    if (tv_off_time_str is not None and 
                        tv_off_channel is not None and
                        self._is_within_threshold(tv_off_time_str, current_time, threshold_seconds)):
                        
                        # Get current channel (from first logo event after TV ON, if any)
                        future_events = group.iloc[idx+1:].reset_index(drop=True)
                        current_channel = self._get_next_channel(future_events)
                        
                        # Check channel continuity if required
                        if check_channel:
                            if current_channel is None or current_channel == tv_off_channel:
                                # Within threshold AND same channel -> continue session
                                print(f"  TV OFF/ON within {threshold_seconds}s threshold with same channel ({tv_off_channel}) - continuing session")
                                tv_off_time_str = None  # Reset TV OFF tracking
                                tv_off_channel = None
                                continue  # Don't process as new TV ON
                            else:
                                # Channel changed after TV ON
                                print(f"  TV OFF/ON within threshold but channel changed from {tv_off_channel} to {current_channel} - starting new session")
                                # Close previous session and start new one
                                if logo_events:
                                    if tv_on_time_str is None:
                                        tv_on_time_str = logo_events[0]['datetime_str']
                                    tv_sessions = self._process_logo_events_to_sessions(
                                        hhid, tv_on_time_str, tv_off_time_str, logo_events
                                    )
                                    sessions.extend(tv_sessions)
                                    logo_events = []
                                tv_on_time_str = current_time  # Start new session
                                tv_off_time_str = None
                                tv_off_channel = None
                                continue
                        else:
                            # Not checking channel continuity, just time threshold
                            print(f"  TV OFF/ON within {threshold_seconds}s threshold - continuing session")
                            tv_off_time_str = None
                            tv_off_channel = None
                            continue
                    
                    # Normal TV ON processing (no recent TV OFF or outside threshold)
                    if logo_events:
                        if tv_on_time_str is None:
                            tv_on_time_str = logo_events[0]['datetime_str']
                        tv_sessions = self._process_logo_events_to_sessions(
                            hhid, tv_on_time_str, tv_off_time_str if tv_off_time_str else row['datetime_str'], logo_events
                        )
                        sessions.extend(tv_sessions)
                    tv_on_time_str = row['datetime_str']
                    tv_off_time_str = None  # Reset TV OFF tracking
                    tv_off_channel = None
                    logo_events = []
                    
                elif state is False:  # TV turned OFF
                    # Store TV OFF time and current channel
                    tv_off_time_str = row['datetime_str']
                    tv_off_channel = self._get_last_channel(logo_events)
                    print(f"  TV OFF at {tv_off_time_str} (channel: {tv_off_channel}) - waiting {threshold_seconds}s threshold")
                    
                    # Don't immediately break session - wait to see if TV ON follows within threshold
            
            elif row['type'] in [self.config.event_types['logo_recognized'],
                                self.config.event_types['logo_unrecognized']]:
                # Logo event
                if pd.notnull(row['channel']) and str(row['channel']).strip() != '':
                    logo_events.append(row.to_dict())
        
        # Process any remaining events at the end of household's data
        # If TV was OFF and never turned back ON within threshold
        if logo_events:
            if tv_on_time_str is None:
                tv_on_time_str = logo_events[0]['datetime_str']
            
            # If we have a pending TV OFF outside threshold, use it as session end
            end_time = tv_off_time_str if tv_off_time_str else group['datetime_str'].iloc[-1]
            
            tv_sessions = self._process_logo_events_to_sessions(
                hhid, tv_on_time_str, end_time, logo_events
            )
            sessions.extend(tv_sessions)
        
        # Also handle case where TV OFF occurred but no following events
        if tv_off_time_str is not None and tv_on_time_str is not None and not logo_events:
            # TV was turned OFF and not turned back ON - close session at TV OFF time
            # (This would be captured in the loop above, but included for completeness)
            pass
        
        return sessions
    
    def _is_within_threshold(self, start_time_str: str, end_time_str: str, threshold_seconds: int) -> bool:
        """Check if the time difference between two events is within threshold"""
        try:
            start_dt = pd.to_datetime(start_time_str)
            end_dt = pd.to_datetime(end_time_str)
            time_diff = (end_dt - start_dt).total_seconds()
            return 0 <= time_diff <= threshold_seconds
        except:
            return False

    def _get_last_channel(self, logo_events: List[Dict]) -> Optional[str]:
        """Get the last channel from logo events"""
        if not logo_events:
            return None
        return logo_events[-1].get('channel')

    def _get_next_channel(self, future_events: pd.DataFrame) -> Optional[str]:
        """Get the first channel from future logo events"""
        for _, row in future_events.iterrows():
            if row['type'] in [self.config.event_types['logo_recognized'],
                              self.config.event_types['logo_unrecognized']]:
                channel = row.get('channel')
                if pd.notnull(channel) and str(channel).strip() != '':
                    return channel
        return None

    def _process_logo_events_to_sessions(self, hhid: str, tv_on_str: str, tv_off_str: str, 
                                        logo_events: List[Dict]) -> List[Dict]:
        """Process logo events into sessions - EXACTLY like household script"""
        if not logo_events:
            return []
        
        # Create DataFrame from logo events
        logo_df = pd.DataFrame(logo_events)
        
        # Ensure datetime is properly parsed
        logo_df['datetime'] = pd.to_datetime(logo_df['datetime_str'], errors='coerce')
        logo_df = logo_df.dropna(subset=['datetime']).sort_values('datetime').reset_index(drop=True)
        
        if logo_df.empty:
            return []
        
        # Apply type 30 bridging
        logo_df = self._apply_type30_bridging(logo_df)
        
        # Group into view sessions
        view_sessions = []
        current_session = []
        prev_time = None
        prev_channel = None
        
        for _, row in logo_df.iterrows():
            curr_time = row['datetime']
            curr_channel = row['channel']
            
            if not current_session:
                current_session.append(row.to_dict())
                prev_time = curr_time
                prev_channel = curr_channel
                continue
            
            time_diff_seconds = (curr_time - prev_time).total_seconds()
            
            # Same grouping logic as household script
            if curr_channel == prev_channel and time_diff_seconds <= 60:
                current_session.append(row.to_dict())
            else:
                view_sessions.append(current_session)
                current_session = [row.to_dict()]
            
            prev_time = curr_time
            prev_channel = curr_channel
        
        if current_session:
            view_sessions.append(current_session)
        
        # Create session records
        session_records = []
        for i, session in enumerate(view_sessions):
            first_row = session[0]
            channel = first_row['channel']
            
            # Determine start time
            start_time = tv_on_str if i == 0 else first_row['datetime_str']
            
            # Determine end time
            if i == len(view_sessions) - 1:
                end_time = tv_off_str
            else:
                next_session_start = view_sessions[i + 1][0]['datetime_str']
                end_time = next_session_start
            
            start_dt = pd.to_datetime(start_time)
            end_dt = pd.to_datetime(end_time)
            
            # Calculate duration
            duration_seconds = (end_dt - start_dt).total_seconds()
            
            if duration_seconds < 0:
                continue
            
            # Session date
            session_date = start_dt.date().isoformat()
            
            session_records.append({
                'date': session_date,
                'hhid': hhid,
                'tv_set': 1,
                'member_id': '',  # Empty for now - will be assigned later
                'channel': channel,
                'start_time': start_dt.strftime('%H:%M:%S'),
                'end_time': end_dt.strftime('%H:%M:%S'),
                'duration_seconds': duration_seconds
            })
        
        return session_records

    def _apply_type30_bridging(self, logo_df: pd.DataFrame) -> pd.DataFrame:
        """Apply type 30 bridging - EXACTLY like household script"""
        logo_df = logo_df.copy()
        i = 0
        
        while i < len(logo_df):
            if logo_df.loc[i, 'type'] == self.config.event_types['logo_unrecognized']:
                start_idx = i
                while i < len(logo_df) and logo_df.loc[i, 'type'] == self.config.event_types['logo_unrecognized']:
                    i += 1
                end_idx = i - 1
                
                # Check if we have <= 48 consecutive type 30 events
                if end_idx - start_idx + 1 <= 48:
                    has_before = start_idx > 0 and logo_df.loc[start_idx - 1, 'type'] == self.config.event_types['logo_recognized']
                    has_after = end_idx < len(logo_df) - 1 and logo_df.loc[end_idx + 1, 'type'] == self.config.event_types['logo_recognized']
                    
                    if has_before and has_after:
                        before_channel = logo_df.loc[start_idx - 1, 'channel']
                        after_channel = logo_df.loc[end_idx + 1, 'channel']
                        
                        if before_channel == after_channel:
                            for j in range(start_idx, end_idx + 1):
                                logo_df.loc[j, 'type'] = self.config.event_types['logo_recognized']
                                logo_df.loc[j, 'channel'] = before_channel
            else:
                i += 1
        
        return logo_df

    def _assign_members_to_sessions(self, hhid: str, group: pd.DataFrame, 
                                   household_sessions: List[Dict]) -> List[Dict]:
        """Assign members to pre-created household sessions"""
        if not household_sessions:
            return []
        
        # Create household state for member tracking
        household_state = HouseholdState(hhid, self.config)
        
        # Track member declarations in chronological order
        member_declarations = []
        for idx, row in group.iterrows():
            if row['type'] in [self.config.event_types['member_declaration'],
                              self.config.event_types['guest_declaration']]:
                member_declarations.append({
                    'time': pd.to_datetime(row['datetime_str']),
                    'event': row.to_dict()
                })
        
        # Sort declarations by time
        member_declarations.sort(key=lambda x: x['time'])
        
        # For each session, determine which members were active
        member_assigned_sessions = []
        
        for session in household_sessions:
            session_start = pd.to_datetime(f"{session['date']} {session['start_time']}")
            session_end = pd.to_datetime(f"{session['date']} {session['end_time']}")
            
            # Handle midnight crossover
            if session_end < session_start:
                session_end += pd.Timedelta(days=1)
            
            # Find active members during this session
            active_members = self._find_active_members_during_session(
                household_state, member_declarations, session_start, session_end
            )
            
            # Create one session record per active member (or anonymous)
            if active_members:
                for member_id, member_info in active_members.items():
                    member_session = session.copy()
                    member_session['member_id'] = member_id  # Store ID only, will format later
                    member_assigned_sessions.append(member_session)
            else:
                # Anonymous session
                anonymous_session = session.copy()
                anonymous_session['member_id'] = ''
                member_assigned_sessions.append(anonymous_session)
        
        return member_assigned_sessions

    def _find_active_members_during_session(self, household_state: HouseholdState,
                                           member_declarations: List[Dict],
                                           session_start: pd.Timestamp,
                                           session_end: pd.Timestamp) -> Dict[str, str]:
        """Find which members were active during a session"""
        # Reset household state
        household_state.members = {}
        household_state.active_member_ids = set()
        
        # Find declarations that happened before or during this session
        relevant_declarations = []
        for decl in member_declarations:
            if decl['time'] <= session_end:  # Include declarations up to session end
                relevant_declarations.append(decl)
        
        # Process declarations in order to build timeline
        for decl in relevant_declarations:
            event = decl['event']
            # Process the declaration
            household_state.process_member_declaration(event)
        
        # Return member IDs (formatting will happen later)
        return {member_id: member_id for member_id in household_state.active_member_ids}


# ============================================================================
# CONFIGURATION FUNCTIONS
# ============================================================================

def get_default_config() -> Config:
    """Get default configuration with member support"""
    return Config()

def get_config_with_date_filtering(enabled: bool = True) -> Config:
    """Configuration with date filtering enabled"""
    config = Config()
    config.date_filtering['enabled'] = enabled
    config.date_filtering['validate_date_presence'] = True
    return config


# ============================================================================
# MAIN PIPELINE FUNCTION
# ============================================================================

def process_pipeline(start_date, end_date, db_config, output_dir):
    """
    Complete pipeline without intermediate files
    """
    print("🚀 Starting end-to-end pipeline with member-wise sessions...")
    
    # Step 1: Fetch data from events_with_hhid table
    df = fetch_events_from_postgres(start_date, end_date, db_config)
    if df.empty:
        print("❌ No data fetched, exiting.")
        return
    
    # Step 2: Process data through pipeline
    print("🔧 Processing data through pipeline...")
    df = convert_timestamp(df)
    df = add_member_ids(df)  # This now also ensures details is JSON
    df = extract_channels(df)
    
    # Step 3: Deduplicate type 3 events before sessioning
    print("🔍 Deduplicating type-3 events...")
    df = deduplicate_type3_events(df)
    
    # Step 4: Split by date (02:00–01:59 rule) and process
    print("📅 Splitting data by date (02:00–01:59)...")
    
    # Convert datetime_str to datetime
    df['datetime'] = pd.to_datetime(df['datetime_str'], errors='coerce')
    df = df.dropna(subset=['datetime'])
    
    # Determine file date based on 02:00–01:59 rule
    def get_file_date(dt):
        return (dt - pd.Timedelta(days=1)).date() if dt.hour < 2 else dt.date()
    
    df['_file_date'] = df['datetime'].apply(get_file_date)
    
    # Get configuration
    config = get_default_config()
    processor = MemberViewershipProcessor(config)
    
    # Create output directory
    os.makedirs(output_dir, exist_ok=True)
    
    # Process each day's data
    total_sessions = 0
    for file_date, daily_df in df.groupby('_file_date'):
        print(f"  Processing date: {file_date}")
        sessions_count = processor.process_dataframe(daily_df, output_dir, str(file_date))
        total_sessions += sessions_count
        print()
    
    print(f"✅ Pipeline complete! Created {total_sessions} member-wise sessions.")


# ============================================================================
# MAIN EXECUTION
# ============================================================================

if __name__ == "__main__":
    import pytz

    tz = pytz.timezone('Asia/Yerevan')
    yesterday = datetime.now(tz) - timedelta(days=1)

    start_date = yesterday.strftime("%Y-%m-%d")
    end_date = start_date
    db_config = {
        'host': 'armenia-db-01.c960kiumy09x.ap-south-1.rds.amazonaws.com',
        'port': 5432,
        'dbname': 'meter01',
        'user': 'postgres',
        'password': 'inditronics123'
    }
    
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    OUTPUT_DIR = os.path.join(SCRIPT_DIR, 'household_viewership_memberwise_output')
    
    # Run the complete pipeline
    process_pipeline(start_date, end_date, db_config, OUTPUT_DIR)
    
    print("🎉 All processing complete!")