import logging
from pathlib import Path

from gcal_epd.config import font_path, output_path as _output_path
from gcal_epd.domain.repositories import EventRepository, WeatherRepository
from gcal_epd.render.draw import render
from gcal_epd.version import version

log = logging.getLogger(__name__)


def run(
    event_repos: list[EventRepository],
    weather_repo: WeatherRepository | None,
    config: dict,
    project_root: Path,
    push_display: bool = False,
    data_dir: Path | None = None,
) -> None:
    """Fetch, render and (optionally) push to the panel.

    Fonts come from `project_root` (the code); the preview is written to
    `data_dir` (this display's files), which defaults to `project_root`
    as in a git checkout.
    """
    output_path = _output_path(config, project_root if data_dir is None else data_dir)
    font = font_path(config, project_root)

    source_cfg = next(
        (s for s in config.get("sources", []) if s.get("type") == "ics"),
        {},
    )
    days_ahead = source_cfg.get("days_ahead", 14)
    max_results = source_cfg.get("max_results_per_calendar", 100)

    all_events = []
    for repo in event_repos:
        all_events.extend(repo.fetch_events(days_ahead=days_ahead, max_results=max_results))

    all_events.sort(key=lambda e: e.start)

    weather = weather_repo.fetch_weather() if weather_repo else None

    img = render(all_events, weather=weather, output_path=output_path, font_path=font,
                 version=version(project_root))
    log.info("Preview saved to %s", output_path)

    if push_display:
        from gcal_epd.epd import push_to_display
        push_to_display(img)
