export type SportType = "running" | "cycling" | "swimming" | "climbing" | "strength" | "rest" | string;

export interface ChangeNote {
  title: string;
  detail: string;
}

export interface WatchItem {
  title: string;
  detail: string;
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

export interface TodayFitness {
  ctl: number;
  atl: number;
  tsb: number;
  freshness?: string;
}

export interface RecentSportActivity {
  id: number;
  title: string;
  started_at?: string | null;
  duration_min?: number | null;
  distance_m?: number | null;
  avg_hr?: number | null;
  avg_speed?: number | null;
  tss?: number | null;
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
  recent_activity?: RecentSportActivity | null;
  fitness?: TodayFitness | null;
}

export interface CalendarItem {
  kind: "session" | "offplan";
  id: number;
  status: "planned" | "done" | "missing" | "offplan" | string;
  scheduled_date?: string | null;
  display_date?: string | null;
  executed_date?: string | null;
  day?: string;
  label?: string;
  title: string;
  goal?: string;
  description?: string;
  sport_type: SportType;
  session_type: string;
  duration_min?: number | null;
  load_band?: string | null;
  priority?: string | null;
  linked_activity_id?: number | null;
  linked_activity_title?: string | null;
  has_invalid_linked_activity?: boolean;
  completion_status?: string | null;
}

export interface OverviewView {
  today: TodayView | null;
  lead_session: CalendarItem | null;
  upcoming_sessions: CalendarItem[];
  week: {
    week_start: string;
    week_end: string;
    label: string;
    mesocycle_week: number;
    mesocycle_number: number;
    is_deload: boolean;
    planning_mode?: string | null;
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
  };
  completion: {
    rate_14d: number;
    key_sessions_done_14d: number;
    volume_sessions_done_14d: number;
    sessions_this_week: number;
    done_this_week: number;
  };
  weekly_hours: number;
  profile: {
    name: string;
    coach_name?: string | null;
    objective?: string | null;
    sports: string[];
    constraints: string[];
    preferences: string[];
  };
  strava: {
    configured: boolean;
    connected: boolean;
    last_sync_at?: string | null;
  };
}

export interface CalendarDay {
  date: string;
  day_number: number;
  in_month: boolean;
  is_today: boolean;
  is_current_week: boolean;
  items: CalendarItem[];
}

export interface CalendarView {
  month: {
    key: string;
    label: string;
    week_label: string;
    mesocycle_week: number;
    mesocycle_number: number;
    is_deload: boolean;
  };
  days: CalendarDay[];
  feed: CalendarItem[];
}

export interface EvolutionHistoryPoint {
  date: string;
  ctl: number;
  atl: number;
  tsb: number;
}

export interface EvolutionDayPoint {
  date: string;
  label: string;
  planned_tss: number;
  actual_tss: number;
  planned_duration_min: number;
  actual_duration_min: number;
}

export interface ForecastWeek {
  week_index: number;
  cycle_week: number;
  target_tss: number;
  projected_ctl: number;
  focus: string;
  planning_mode: string;
  is_deload: boolean;
}

export interface EvolutionView {
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
    planned_this_week?: number;
    actual_activities_this_week?: number;
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
  sports: {
    ctl: Record<string, number>;
    volume_hours_14d: Record<string, number>;
  };
  rationale: string[];
  risk_flags: string[];
  history: EvolutionHistoryPoint[];
  week_daily: EvolutionDayPoint[];
  forecast: ForecastWeek[];
}

export interface WorkoutDetailView {
  session: CalendarItem;
  metrics: {
    distance_m?: number | null;
    duration_min?: number | null;
    elevation_m?: number | null;
    avg_hr?: number | null;
    avg_speed?: number | null;
    tss?: number | null;
  };
  linked_activity?: Activity | null;
  fitness?: TodayFitness | null;
  recent_activity?: RecentSportActivity | null;
  coach: {
    goal: string;
    note: string;
    description: string;
    nutrition_focus?: string | null;
    change_notes: ChangeNote[];
    watch_items: WatchItem[];
  };
  zone_distribution: number[];
  map_polyline?: string | null;
}
