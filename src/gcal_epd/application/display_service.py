import logging
from pathlib import Path

from gcal_epd.domain.repositories import EventRepository, WeatherRepository
from gcal_epd.render.draw import render

log = logging.getLogger(__name__)


def run(
    event_repos: list[EventRepository],
    weather_repo: WeatherRepository | None,
    config: dict,
    project_root: Path,
    push_display: bool = False,
) -> None:
    display_cfg = config.get("display", {})
    output_path = str(project_root / display_cfg.get("output_path", "preview.png"))
    raw_font = display_cfg.get("font_path", "")
    font_path = str(project_root / raw_font) if raw_font and not raw_font.startswith("/") else raw_font

    all_events = []
    for repo in event_repos:
        source_cfg = next(
            (s for s in config.get("sources", []) if s["type"] == "google_calendar"),
            {},
        )
        days_ahead = source_cfg.get("days_ahead", 14)
        max_results = source_cfg.get("max_results_per_calendar", 100)
        all_events.extend(repo.fetch_events(days_ahead=days_ahead, max_results=max_results))

    all_events.sort(key=lambda e: e.start)

    weather = weather_repo.fetch_weather() if weather_repo else None

    img = render(all_events, weather=weather, output_path=output_path, font_path=font_path)
    log.info("Preview saved to %s", output_path)

    if push_display:
        from gcal_epd.epd import push_to_display
        push_to_display(img)
