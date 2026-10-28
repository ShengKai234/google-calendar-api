"""Moving an old checkout's own files into the data directory, once."""
from gcal_epd.infrastructure.release.migrate import LOCAL_CONFIG_NOTE, migrate_checkout

SHIPPED = '[[sources]]\ntype = "ics"\nfeeds_file = "ics_feeds.toml"\n'


def _setup(tmp_path, config=SHIPPED):
    checkout, release, data = tmp_path / "old", tmp_path / "rel", tmp_path / "data"
    checkout.mkdir()
    release.mkdir()
    (release / "config.toml").write_text(SHIPPED)
    (checkout / "config.toml").write_text(config)
    return checkout, release, data


def test_copies_feeds_parked_links_schedule_and_preview(tmp_path):
    checkout, release, data = _setup(tmp_path)
    for name in ("ics_feeds.toml", "ics_feeds.pending.toml", "power_schedule.toml",
                 "preview.png"):
        (checkout / name).write_text(name)
    copied = migrate_checkout(checkout, release, data)
    assert sorted(copied) == ["ics_feeds.pending.toml", "ics_feeds.toml", "power_schedule.toml",
                              "preview.png"]
    assert (data / "ics_feeds.toml").read_text() == "ics_feeds.toml"


def test_copies_never_moves(tmp_path):
    """The old checkout keeps working, and is the way back."""
    checkout, release, data = _setup(tmp_path)
    (checkout / "ics_feeds.toml").write_text("x")
    migrate_checkout(checkout, release, data)
    assert (checkout / "ics_feeds.toml").read_text() == "x"


def test_never_overwrites_the_data_dir(tmp_path):
    checkout, release, data = _setup(tmp_path)
    data.mkdir()
    (data / "ics_feeds.toml").write_text("newer")
    (checkout / "ics_feeds.toml").write_text("older")
    assert migrate_checkout(checkout, release, data) == []
    assert (data / "ics_feeds.toml").read_text() == "newer"


def test_follows_a_renamed_feeds_file(tmp_path):
    config = '[[sources]]\ntype = "ics"\nfeeds_file = "mine.toml"\n'
    checkout, release, data = _setup(tmp_path, config)
    (checkout / "mine.toml").write_text("x")
    (checkout / "mine.pending.toml").write_text("y")
    copied = migrate_checkout(checkout, release, data)
    assert {"mine.toml", "mine.pending.toml"} <= set(copied)


def test_unchanged_config_is_not_carried_over(tmp_path):
    checkout, release, data = _setup(tmp_path)
    migrate_checkout(checkout, release, data)
    assert not (data / "config.local.toml").exists()


def test_changed_config_becomes_the_local_config(tmp_path):
    changed = SHIPPED + '\n[[sources]]\ntype = "open_meteo"\nlocation = "Tainan"\n'
    checkout, release, data = _setup(tmp_path, changed)
    copied = migrate_checkout(checkout, release, data)
    local = (data / "config.local.toml").read_text()
    assert "config.toml -> config.local.toml" in copied
    assert local.startswith(LOCAL_CONFIG_NOTE.format(checkout=checkout))
    assert local.endswith(changed)


def test_existing_local_config_wins(tmp_path):
    checkout, release, data = _setup(tmp_path, SHIPPED + "\n[display]\nx = 1\n")
    data.mkdir()
    (data / "config.local.toml").write_text("mine\n")
    migrate_checkout(checkout, release, data)
    assert (data / "config.local.toml").read_text() == "mine\n"


def test_each_copy_is_handed_to_the_app_user(tmp_path):
    checkout, release, data = _setup(tmp_path, SHIPPED + "\n[display]\nx = 1\n")
    (checkout / "ics_feeds.toml").write_text("x")
    owned = []
    migrate_checkout(checkout, release, data, chown=owned.append)
    assert sorted(p.name for p in owned) == ["config.local.toml", "ics_feeds.toml"]


def test_nothing_to_carry_over(tmp_path):
    checkout, release, data = _setup(tmp_path)
    assert migrate_checkout(checkout, release, data) == []
