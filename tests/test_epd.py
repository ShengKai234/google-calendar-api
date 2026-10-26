"""The panel driver needs a writable directory for lgpio's pipes."""
from gcal_epd import config, epd


def test_lgpio_pipes_go_to_the_data_dir(tmp_path):
    env = {}
    epd.use_writable_lgpio_dir(tmp_path, env)
    assert env["LG_WD"] == str(tmp_path)


def test_an_lg_wd_already_set_is_kept(tmp_path):
    env = {"LG_WD": "/run/mine"}
    epd.use_writable_lgpio_dir(tmp_path, env)
    assert env["LG_WD"] == "/run/mine"


def test_default_is_this_displays_data_dir():
    env = {}
    epd.use_writable_lgpio_dir(env=env)
    assert env["LG_WD"] == str(config.DATA_DIR)
