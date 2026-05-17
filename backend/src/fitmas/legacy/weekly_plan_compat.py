from __future__ import annotations

from fitmas import repository as repo
from fitmas.models import DayPlan as RuntimeDay
from fitmas.models import WeeklyPlan as RuntimeWeek


get_active_plan = repo.get_active_plan
get_active_plan_optional = repo.get_active_plan_optional
get_day_plan = repo.get_day_plan
replace_plan = repo.replace_plan
to_pydantic_plan = repo.to_pydantic_plan
