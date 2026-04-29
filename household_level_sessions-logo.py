#!/usr/bin/env python3
"""
Full end-to-end production script with member-wise viewership sessions:
1. Query events from Postgres based on user-given date range
2. Convert timestamps to UTC+4 (Yerevan)
3. Add member IDs
4. Map device_id -> hhid (from meters & households tables)
5. Split into daily files (02:00–01:59)
6. Extract channels (type 29/30)
7. Create member-wise viewership sessions
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
    """Query events from PostgreSQL"""
    # Parse input dates
    start_dt_local = pd.Timestamp(f"{start_date_str} 02:00:00").tz_localize('Asia/Yerevan')
    end_dt_local = pd.Timestamp(f"{end_date_str} 01:59:59") + pd.Timedelta(days=1)
    end_dt_local = end_dt_local.tz_localize('Asia/Yerevan')

    # Convert to UTC for querying Postgres
    start_ts = int(start_dt_local.tz_convert('UTC').timestamp())
    end_ts = int(end_dt_local.tz_convert('UTC').timestamp())

    query = f"""
    SELECT *
    FROM events
    WHERE type IN ('29','30','42','23')
      AND timestamp BETWEEN {start_ts} AND {end_ts}
      AND device_id IN ('IM000413','IM000475','IM000461','IM000466','IM000118','IM000236',
    'IM000443','IM000464','IM000416','IM000434','IM000110','IM000486',
    'IM000127','IM000111','IM000490','IM000418','IM000403','IM000253',
    'IM000125','IM000120','IM000395','IM000160','IM000235','IM000241',
    'IM000222','IM000151','IM000130','IM000144','IM000142','IM000459',
    'IM000156','IM000484','IM000137','IM000477','IM000143','IM000171',
    'IM000114','IM000109','IM000460','IM000141','IM000148','IM000134',
    'IM000158','IM000133','IM000149','IM000140','IM000152','IM000175',
    'IM000154','IM000157','IM000168','IM000165','IM000164','IM000185',
    'IM000184','IM000162','IM000210','IM000215','IM000229','IM000182',
    'IM000202','IM000198','IM000227','IM000224','IM000191','IM000193',
    'IM000186','IM000230','IM000225','IM000211','IM000190','IM000206',
    'IM000223','IM000187','IM000180','IM000221','IM000209','IM000208',
    'IM000192','IM000201','IM000189','IM000179','IM000219','IM000181',
    'IM000212','IM000305','IM000285','IM000197','IM000200','IM000218',
    'IM000247','IM000303','IM000299','IM000188','IM000294','IM000217',
    'IM000295','IM000405','IM000257','IM000291','IM000254','IM000308',
    'IM000312','IM000274','IM000282','IM000268','IM000245','IM000296',
    'IM000298','IM000306','IM000269','IM000260','IM000307','IM000301',
    'IM000248','IM000304','IM000311','IM000214','IM000255','IM000104',
    'IM000216','IM000315','IM000261','IM000289','IM000251','IM000252',
    'IM000234','IM000195','IM000242','IM000258','IM000310','IM000309',
    'IM000279','IM000271','IM000281','IM000262','IM000286','IM000246',
    'IM000290','IM000250','IM000273','IM000256','IM000280','IM000207',
    'IM000244','IM000300','IM000199','IM000196','IM000284','IM000275',
    'IM000297','IM000272','IM000277','IM000220','IM000264','IM000166',
    'IM000292','IM000249','IM000302','IM000267','IM000313','IM000314',
    'IM000116','IM000270','IM000266','IM000276','IM000232','IM000204',
    'IM000259','IM000287','IM000226','IM000288','IM000336','IM000327',
    'IM000321','IM000328','IM000283','IM000278','IM000263','IM000476',
    'IM000332','IM000318','IM000334','IM000323','IM000329','IM000338',
    'IM000331','IM000339','IM000265','IM000330','IM000337','IM000340',
    'IM000325','IM000324','IM000316',
    'IM000497','IM000421','IM000401','IM000492','IM000495','IM000431','IM000415','IM000404','IM000462','IM000451',
    'IM000408','IM000470','IM000527','IM000481','IM000425','IM000349','IM000366','IM000353','IM000406','IM000371',
    'IM000365','IM000238','IM000194','IM000513','IM000507','IM000524','IM000469','IM000139','IM000293','IM000147',
    'IM000412','IM000411','IM000410','IM000402','IM000448','IM000482','IM000400','IM000388','IM000363','IM000389',
    'IM000375','IM000350','IM000386','IM000368','IM000374','IM000468','IM000496','IM000422','IM000378','IM000355',
    'IM000454','IM000237','IM000455','IM000373','IM000493','IM000474','IM000488','IM000420','IM000346','IM000453',
    'IM000347','IM000351','IM000163','IM000360','IM000485','IM000494','IM000441','IM000364','IM000423','IM000480',
    'IM000383','IM000343','IM000356','IM000358','IM000345','IM000435','IM000391','IM000432','IM000399','IM000341',
    'IM000322','IM000344','IM000382','IM000370','IM000357','IM000317','IM000381','IM000379','IM000348','IM000170',
    'IM000155','IM000167','IM000176','IM000146','IM000136','IM000479','IM000132','IM000478','IM000119','IM000376',
    'IM000387','IM000354','IM000369','IM000161','IM000177','IM000174','IM000169','IM000178','IM000362','IM000172',
    'IM000153','IM000159','IM000526','IM000473','IM000525','IM000522','IM000517','IM000500','IM000398','IM000428',
    'IM000487','IM000442','IM000385','IM000367','IM000380','IM000515','IM000521','IM000516','IM000228','IM000414',
    'IM000393','IM000424','IM000446','IM000436','IM000449','IM000384','IM000335','IM000390','IM000320','IM000333',
    'IM000319','IM000407','IM000417','IM000397','IM000359','IM000491','IM000489','IM000430','IM000426','IM000444',
    'IM000467','IM000452','IM000456','IM000342','IM000445','IM000463','IM000447','IM000438','IM000439','IM000394',
    'IM000392','IM000372','IM000377','IM000437','IM000352','IM000450','IM000409','IM000433','IM000458','IM000465',
    'IM000427','IM000117','IM000511','IM000112','IM000121','IM000129','IM000128','IM000115','IM000440','IM000108',
    'IM000508','IM000509','IM000126','IM000502','IM000514','IM000173','IM000106','IM000483','IM000471','IM000102',
    'IM000123','IM000124','IM000107','IM000122','IM000472','IM000419','IM000105'
  )
    ORDER BY device_id ASC, timestamp ASC;
    """
    print(f"📌 Querying events from {start_dt_local} to {end_dt_local} (UNIX: {start_ts} → {end_ts})")
    conn = psycopg2.connect(**db_config)
    df = pd.read_sql(query, conn)
    conn.close()
    print(f"✅ Fetched {len(df)} rows from Postgres")
    return df

def fetch_hhid_mapping(db_config):
    """Fetch meter → hhid mapping from database"""
    query = """
    SELECT 
        h.hhid AS hhid,
        m.meter_id AS meter_id
    FROM meters m
    JOIN households h
      ON m.assigned_household_id = h.id;
    """
    conn = psycopg2.connect(**db_config)
    mapping_df = pd.read_sql(query, conn)
    conn.close()
    meter_to_hhid = dict(zip(mapping_df['meter_id'], mapping_df['hhid']))
    print(f"✅ Fetched {len(meter_to_hhid)} meter → hhid mappings from DB")
    return meter_to_hhid


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



    df['details'] = df['details'].apply(assign_ids)
    return df

def map_hhid(df, meter_to_hhid):
    """Map device_id -> hhid"""
    df['hhid'] = df['device_id'].map(meter_to_hhid)
    missing = df['hhid'].isna().sum()
    print(f"✅ Mapped hhid. Rows without mapping: {missing}")
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
                
                output_rows.extend(household_sessions)

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
                

                # Select only the columns we need for output
                output_columns = ['date', 'hhid', 'tv_set', 'channel', 'start_time', 'end_time', 'duration', 'duration_seconds']
                output_df = output_df[output_columns]

                output_df = output_df.sort_values(['hhid', 'date', 'start_time']).reset_index(drop=True)

                # Create filename based on date range or specific date
                if file_date:
                    output_filename = f"{file_date}_memberwise.csv"
                else:
                    # Use date range from input
                    date_range = f"{min(input_dates)}_to_{max(input_dates)}"
                    output_filename = f"{date_range}_memberwise.csv"
                
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
                'tv_set': 1,  # Empty for now - will be assigned later
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
    
    # Step 1: Fetch data
    df = fetch_events_from_postgres(start_date, end_date, db_config)
    if df.empty:
        print("❌ No data fetched, exiting.")
        return
    
    # Step 2: Fetch mappings
    meter_to_hhid = fetch_hhid_mapping(db_config)
    
    # Step 3: Process data through pipeline
    print("🔧 Processing data through pipeline...")
    df = convert_timestamp(df)  # This now also ensures details is JSON
    df = map_hhid(df, meter_to_hhid)
    df = extract_channels(df)
    
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
    
    OUTPUT_DIR = './household_viewership_memberwise_output_all_regions'
    
    # Run the complete pipeline
    process_pipeline(start_date, end_date, db_config, OUTPUT_DIR)
    
    print("🎉 All processing complete!")