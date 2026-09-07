from __future__ import annotations

from typing import Literal, TypedDict


class Position(TypedDict):
    x: float
    y: float


class Curve(TypedDict, total=False):
    type: Literal["ELLIPSE", "STRAIGHT_LINE"] | str
    motion_type: str
    active: bool
    dotted: bool
    direction: int
    eccentricity: float
    focus1: str
    major_axis: float
    minor_axis: float
    rotation: float
    phase: float
    phase_updated_at: float
    velocity: float
    valid_from: float
    valid_till: float
    start_location: Position
    direction_vector: Position


class RadarAttachment(TypedDict):
    type: Literal["RADAR"]
    radius: float


class GunAttachment(TypedDict):
    type: Literal["GUN"]
    velocity: float
    hit_radius: float
    range: float
    cooldown_seconds: float
    last_fired_at: float
    blast_impact: float


class UniverseObject(TypedDict, total=False):
    type: Literal["NATURAL", "ARTIFICIAL"]
    owner: str | None
    sub_type: str
    life: float
    max_life: float
    blast_impact: float
    border_radius: float
    location: Position
    curves: dict[str, Curve]
    objects: dict[str, RadarAttachment | GunAttachment | dict]
    source_objectid: str
    hit_radius: float
    delete_at: float
    death_blast_radius: float
    death_blast_damage: float
    show_blast_radius: bool


class ProjectileOutcome(TypedDict, total=False):
    status: Literal["HIT", "EXPIRED"]
    target_id: str
    hit_time: float
    recorded_at: float


class UniverseEvent(TypedDict, total=False):
    type: Literal["PROJECTILE_HIT", "OBJECT_COLLISION"] | str
    projectile_id: str
    target_id: str
    hit_time: float
    location: Position
    blast_impact: float
    life_before: float
    life_after: float
    other_object_id: str
    source_objectid: str
    source_id: str
    triggered_star_ids: list[str]
    occurred_at: float


class UniverseRecord(TypedDict, total=False):
    name: str
    creator_id: str
    active: bool
    career: bool
    darkforest: bool
    career_level: int
    career_state: "CareerState"
    participants: dict[str, "UniverseParticipant"]
    agent_state: dict[str, "AgentState"]
    time: float
    time_updated_at_ms: float
    objects: dict[str, UniverseObject]
    events: dict[str, UniverseEvent]
    recent_projectile_outcomes: dict[str, ProjectileOutcome]
    spawn_config: "SpawnConfig"


class SpawnConfig(TypedDict):
    starter_ship_count: int
    ship_orbit_radius: float
    ship_orbit_velocity: float
    gun_velocity: float
    gun_hit_radius: float
    gun_range: float
    radar_radius: float
    star_life: float
    ship_life: float
    star_border_radius: float
    ship_border_radius: float


class UniverseMembership(TypedDict):
    onboarded: bool
    star_id: str
    ship_ids: dict[str, str]
    onboarded_at: float
    universe_type: Literal["CAREER", "ARCADE"]


class OpeningBriefing(TypedDict, total=False):
    step: int
    completed: bool
    completed_at: float
    messages: list[str]


class CareerState(TypedDict, total=False):
    current_step: str
    status: Literal["BRIEFING", "ACTIVE", "TRANSITIONING", "COMPLETE"] | str
    opening_briefing: OpeningBriefing
    tutorial_step: int
    paused_time: float
    tutorial_intermission: bool
    tutorial_intermission_started_at_ms: float
    enemy_contact_tutorial_step: int
    enemy_contact_ship_id: str
    enemy_contact_star_id: str
    enemy_contact_expected_at: float
    enemy_contact_progress_starts_at: float
    enemy_contact_hold_seconds: float
    enemy_contact_duration_seconds: float
    enemy_contact_released: bool
    level_completed: bool
    completed_at: float
    tutorial_transfer_speed_multiplier: float
    tutorial_transfer_speeding: bool
    level_two_enemy_home_armed_at: float
    level_two_enemy_home_last_fire_at: float


class UniverseParticipant(TypedDict):
    type: Literal["HUMAN", "AGENT"]


class AgentState(TypedDict):
    agent_name: str
    active: bool
    mode: str
    ship_id: str


class UserRecord(TypedDict, total=False):
    username: str | None
    password: str | None
    type: Literal["HUMAN", "AGENT"]
    registration_state: Literal["PENDING", "COMPLETE"]
    career_universe: str | None
    universe_memberships: dict[str, UniverseMembership]
