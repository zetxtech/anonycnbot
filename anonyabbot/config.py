import os
from pathlib import Path

from box import BoxError, ConfigBox
from loguru import logger

from .utils import ProxyBase

DEFAULT_CONF = {}


class ConfigError(BoxError):
    pass


class Config(ProxyBase):
    __noproxy__ = ("conf_file", "_cache", "__getitem__")

    def __init__(self, conf_file=None):
        self.conf_file = conf_file
        self._cache = None

    @property
    def __subject__(self):
        if not self._cache:
            self._cache = self.reload_conf(conf_file=self.conf_file)
        return self._cache

    def reset(self):
        self._cache = None

    @staticmethod
    def reload_conf(conf_file=None, box=None):
        """Load config from provided file or config.toml at cwd."""
        if not box:
            box = ConfigBox(DEFAULT_CONF, box_dots=True)
        default_conf = Path("./config.toml")
        if conf_file:
            conf_file = Path(conf_file)
        elif default_conf.is_file():
            conf_file = default_conf
        else:
            logger.debug(f"No config found from provided file or ./{default_conf}.")
        if conf_file:
            if conf_file.suffix.lower() == ".toml":
                box.merge_update(ConfigBox.from_toml(filename=conf_file))
            elif conf_file.suffix.lower() in (".yaml", ".yml"):
                box.merge_update(ConfigBox.from_yaml(filename=conf_file))
            else:
                logger.warning(f'Can not load config file "{conf_file}", a yaml/toml file is required.')
        return box

    def __getitem__(self, arg):
        try:
            return self.__subject__[arg]
        except BoxError:
            msg = f'can not find config key "{arg}", please check your config file or env var.'
            raise ConfigError(msg) from None


config: ConfigBox = Config()
