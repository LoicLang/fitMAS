export type SportType = "running" | "cycling" | "swimming" | "climbing" | "strength" | "rest" | string;

export interface Profile {
  name: string;
  age?: number | null;
  objective?: string;
  primary_objective?: string;
  sports: string[];
  constraints: string[];
  preferences: string[];
  coach_name?: string;
  coach_style?: string;
  coach_do?: string;
  coach_dont?: string;
  coach_soul?: string;
  timezone?: string;
}

export interface ChangeNote {
  title: string;
  detail: string;
}

export interface WatchItem {
  title: string;
  detail: string;
}

export interface DayPlan {
  day: string;
  label: string;
  sport_type: SportType;
  session_type: string;
  session_title: string;
  session_goal: string;
  session_note?: string;
  session_description?: string;
  duration_min?: number | null;
  intensity?: string;
  load_score?: number;
  load_band?: string;
  priority: string;
  nutrition_focus?: string;
  completion_status?: string;
  change_notes: ChangeNote[];
  watch_items: WatchItem[];
}

export interface WeeklyPlan {
  intention: string;
  summary: string;
  mesocycle_week: number;
  mesocycle_number: number;
  cycle_length: number;
  total_weeks: number;
  is_deload: boolean;
  week_label: string;
  days: DayPlan[];
}

export interface Activity {
  id: number;
  sport_type: SportType;
  title: string;
  source: string;
  duration_min?: number | null;
  distance_m?: number | null;
  elevation_m?: number | null;
  perceived_load?: number | null;
  note?: string;
  started_at?: string | null;
  matched_day?: string | null;
  match_reason?: string | null;
  avg_hr?: number | null;
  max_hr?: number | null;
  avg_speed?: number | null;
  calories?: number | null;
  suffer_score?: number | null;
  tss?: number | null;
  scheduled_session_id?: number | null;
  external_id?: string | null;
  map_polyline?: string | null;
  start_latlng?: string | null;
}

export interface ScheduledSession {
  id: number;
  day: string;
  label: string;
  scheduled_date: string;
  sport_type: SportType;
  session_type: string;
  session_title: string;
  session_goal: string;
  session_note?: string;
  session_description?: string;
  duration_min?: number | null;
  intensity?: string;
  load_score?: number;
  load_band?: string;
  priority: string;
  nutrition_focus?: string;
  flexibility?: string;
  completion_status?: string;
  linked_activity_id?: number | null;
}

export interface TrainingLoadPoint {
  date: string;
  ctl: number;
  atl: number;
  tsb: number;
}

export interface TrainingLoadStats {
  ctl: number;
  atl: number;
  tsb: number;
  series: TrainingLoadPoint[];
}

export interface VolumeWeek {
  week_start: string;
  total_duration_min: number;
  sports: Record<string, { duration_min?: number }>;
}

export interface VolumeStats {
  weeks: VolumeWeek[];
}

export interface RecordsStats {
  sports: Record<
    string,
    {
      longest_distance_m?: number | null;
      longest_duration_min?: number | null;
      best_pace_seconds_per_km?: number | null;
      max_elevation_m?: number | null;
    }
  >;
}

export interface TodayFitness {
  ctl: number;
  atl: number;
  tsb: number;
  freshness?: string;
}

export interface TodayView {
  scheduled_session_id: number;
  scheduled_date: string;
  day: string;
  label: string;
  sport_type: SportType;
  session_type: string;
  session_title: string;
  session_goal: string;
  session_description?: string;
  duration_min?: number | null;
  intensity?: string;
  load_band?: string;
  priority: string;
  nutrition_focus?: string;
  completion_status?: string;
  change_notes: ChangeNote[];
  watch_items: WatchItem[];
  recent_activity?: Activity | null;
  fitness?: TodayFitness | null;
}

export interface Fact {
  category: string;
  source: string;
  confidence: number;
  confirmed: boolean;
  key: string;
  value: string;
}

export interface StravaStatus {
  configured: boolean;
  connected: boolean;
  last_sync_at?: string | null;
}

export interface PerformanceOverview {
  week: {
    week_start: string;
    week_end: string;
    label: string;
    mesocycle_week: number;
    mesocycle_number: number;
    is_deload: boolean;
    planning_mode?: string | null;
    adaptation_level?: string | null;
    adaptation_scope?: string | null;
    intensity_distribution?: string | null;
  };
  load: {
    ctl: number;
    atl: number;
    tsb: number;
    ramp_rate: number;
    freshness: string;
  };
  tss: {
    target: number;
    actual: number;
    remaining: number;
    delta: number;
    planned_this_week: number;
    actual_activities_this_week: number;
  };
  completion: {
    rate_14d: number;
    key_sessions_done_14d: number;
    volume_sessions_done_14d: number;
    sessions_this_week: number;
    done_this_week: number;
  };
  distribution: {
    planned: Record<string, { count: number; tss: number }>;
    completed: Record<string, { count: number; tss: number }>;
  };
  rationale: string[];
  risk_flags: string[];
}

export interface AppBootstrap {
  profile: Profile;
  week: WeeklyPlan;
  facts: Fact[];
  activities: Activity[];
  stravaStatus: StravaStatus;
  timeline: ScheduledSession[];
  trainingLoad: TrainingLoadStats;
  volume: VolumeStats;
  records: RecordsStats;
  performanceOverview: PerformanceOverview;
  today: TodayView | null;
}
