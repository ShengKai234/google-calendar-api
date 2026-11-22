import logging
from contextlib import nullcontext
from pathlib import Path
from typing import Callable

from gcal_epd.config import DATA_DIR, font_path, output_path as _output_path
from gcal_epd.infrastructure.panel_lock import PANEL_LOCK, panel_lock
from gcal_epd.domain.repositories import EventRepository, WeatherRepository
from gcal_epd.render.draw import render, render_privacy
from gcal_epd.version import version

log = logging.getLogger(__name__)


def run(
    event_repos: list[EventRepository],
    weather_repo: WeatherRepository | None,
    config: dict,
    project_root: Path,
    push_display: bool = False,
    data_dir: Path | None = None,
    privacy: bool = False,
    is_private: Callable[[], bool] | None = None,
) -> None:
    """Fetch, render and (optionally) push to the panel.

    Fonts come from `project_root` (the code); the preview is written to
    `data_dir` (this display's files), which defaults to `project_root`
    as in a git checkout. With `privacy`, the privacy page: date and
    weather, and no events fetched at all.

    `is_private` is asked once more just before drawing, while the panel
    lock is held; a single press switches the mode under the same lock
    (gcal_epd.buttons), so a calendar fetched before the press is never
    drawn, saved or pushed after it. The lock is taken for a push, and
    also for a preview whenever the mode can change.
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
    if not privacy:
        for repo in event_repos:
            all_events.extend(repo.fetch_events(days_ahead=days_ahead,
                                                max_results=max_results))
        all_events.sort(key=lambda e: e.start)

    weather = weather_repo.fetch_weather() if weather_repo else None

    locked = push_display or is_private is not None
    lock = panel_lock((data_dir or DATA_DIR) / PANEL_LOCK) if locked else nullcontext()
    with lock:
        if not privacy and is_private is not None and is_private():
            log.info("Switched to the privacy page meanwhile: drawing that instead.")
            privacy, all_events = True, []
        if privacy:
            img = render_privacy(weather=weather, output_path=output_path, font_path=font,
                                 version=version(project_root))
            log.info("Privacy page; preview saved to %s", output_path)
        else:
            img = render(all_events, weather=weather, output_path=output_path,
                         font_path=font, version=version(project_root))
            log.info("Preview saved to %s", output_path)

        if push_display:
            from gcal_epd.epd import push_to_display
            from gcal_epd.render.frame import frame_offset
            push_to_display(img, frame_offset(config), take_lock=False)
