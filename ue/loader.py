import os.path
import re
import sys
import weakref
from abc import ABC, abstractmethod
from configparser import ConfigParser
from logging import NullHandler, getLogger
from pathlib import Path, PurePosixPath
from typing import *

from .asset import ExportTableItem, ImportTableItem, UAsset
from .base import UEBase
from .properties import ObjectIndex, ObjectProperty, Property
from .stream import MemoryStream

logger = getLogger(__name__)
logger.addHandler(NullHandler())

__all__ = (
    'ModNotFound',
    'AssetNotFound',
    'AssetLoadException',
    'AssetLoader',
    'load_file_into_memory',
    'ModResolver',
    'IniModResolver',
)

NO_FALLBACK = object()


class AssetLoadException(Exception):
    pass


class ModNotFound(AssetLoadException):
    def __init__(self, mod_name: str):
        super().__init__(f'Mod {mod_name} not found')


class AssetNotFound(AssetLoadException):
    def __init__(self, asset_name: str):
        super().__init__(f'Asset {asset_name} not found')


class ModResolver(ABC):
    '''Abstract class a mod resolver must implement.'''
    def initialise(self):
        pass

    @abstractmethod
    def get_name_from_id(self, modid: str) -> str:
        pass

    @abstractmethod
    def get_id_from_name(self, name: str) -> str:
        pass


class CacheManager(ABC):
    @abstractmethod
    def lookup(self, name) -> Optional[UAsset]:
        raise NotImplementedError

    @abstractmethod
    def add(self, name: str, asset: UAsset):
        raise NotImplementedError

    @abstractmethod
    def remove(self, name: str):
        raise NotImplementedError

    @abstractmethod
    def wipe(self, prefix: str = ''):
        raise NotImplementedError


class DictCacheManager(CacheManager):
    def __init__(self):
        self.cache: Dict[str, UAsset] = dict()

    def lookup(self, name) -> Optional[UAsset]:
        return self.cache.get(name, None)

    def add(self, name: str, asset: UAsset):
        self.cache[name] = asset

    def remove(self, name):
        del self.cache[name]

    def wipe(self, prefix: str = ''):
        if not prefix:
            self.cache = dict()
        else:
            for name in list(key for key in self.cache if key.startswith(prefix)):
                del self.cache[name]


class IniModResolver(ModResolver):
    '''Old-style mod resolution by hand-crafted mods.ini.'''
    def __init__(self, filename='mods.ini'):
        self.filename = filename

    def initialise(self):
        config = ConfigParser(inline_comment_prefixes='#;')
        config.optionxform = lambda v: v  # keep exact case of mod names, please
        config.read(self.filename)
        self.mods_id_to_names = dict(config['ids'])
        self.mods_names_to_ids = dict((name.lower(), id) for id, name in config['ids'].items())
        # self.mods_id_to_longnames = dict(config['names'])
        return self

    def get_name_from_id(self, modid: str) -> str:
        name = self.mods_id_to_names.get(modid, None)
        return name

    def get_id_from_name(self, name: str) -> str:
        modid = self.mods_names_to_ids.get(name.lower(), None)
        return modid


class AssetLoader:
    def __init__(self, modresolver: ModResolver, assetpath='.', cache_manager: CacheManager = None):
        self.cache: CacheManager = cache_manager or DictCacheManager()
        self.asset_path = Path(assetpath)
        self.absolute_asset_path = self.asset_path.absolute().resolve()  # need both absolute and resolve here
        self.modresolver = modresolver
        self.modresolver.initialise()

    def clean_asset_name(self, name: str):
        # Remove class name, if present
        if '.' in name:
            name = name[:name.index('.')]

        # Clean it up and break it into its parts
        name = name.strip().strip('/').strip('\\').replace('\\', '/')
        parts = name.split('/')

        # Convert mod names to numbers
        if len(parts) > 2 and parts[1].lower() == 'mods' and parts[2].isnumeric():
            mod_name = self.modresolver.get_name_from_id(parts[2])
            parts[2] = mod_name

        # Change Content back to name, for cache consistency
        if parts and parts[0].lower() == 'content':
            parts[0] = 'Game'

        # print(parts)
        result = '/' + '/'.join(parts)

        # print(result)
        return result

    def wipe_cache(self):
        self.cache.wipe()

    def wipe_cache_with_prefix(self, prefix: str):
        self.cache.wipe(prefix)

    def convert_asset_name_to_path(self, name: str, partial=False, ext='.uasset'):
        '''Get the filename from which an asset can be loaded.'''
        name = self.clean_asset_name(name)
        parts = name.strip('/').split('/')

        # Convert mod names to numbers
        if len(parts) > 2 and parts[1].lower() == 'mods' and not parts[2].isnumeric():
            parts[2] = self.modresolver.get_id_from_name(parts[2])

        # Game is replaced with Content
        if parts and parts[0].lower() == 'game':
            parts[0] = 'Content'

        fullname = os.path.join(self.asset_path, *parts)
        if not partial:
            fullname += ext

        return fullname

    def get_mod_name(self, assetname: str) -> Optional[str]:
        assert assetname is not None
        assetname = self.clean_asset_name(assetname)
        parts = assetname.strip('/').split('/')
        if len(parts) < 3:
            return None
        if parts[0].lower() != 'game' or parts[1].lower() != 'mods':
            return None
        mod = parts[2]
        if mod.isnumeric():
            mod = self.modresolver.get_name_from_id(mod)
        return mod

    def get_mod_id(self, assetname: str) -> Optional[str]:
        assert assetname is not None
        assetname = self.clean_asset_name(assetname)
        parts = assetname.strip('/').split('/')
        if len(parts) < 3:
            return None
        if parts[0].lower() != 'game' or parts[1].lower() != 'mods':
            return None
        mod = parts[2]
        if not mod.isnumeric():
            mod = self.modresolver.get_id_from_name(mod)
        return mod

    def find_assetnames(self,
                        regex,
                        toppath='/',
                        exclude: Union[str, Iterable[str]] = None,
                        extension: Union[str, Iterable[str]] = '.uasset',
                        return_extension=False):

        excludes: Tuple[str, ...] = tuple(exclude, ) if isinstance(exclude, str) else tuple(exclude or ())
        extensions: Tuple[str, ...] = tuple((extension, )) if isinstance(extension, str) else tuple(extension or ())
        extensions = tuple(ext.lower() for ext in extensions)
        assert extensions

        toppath = self.convert_asset_name_to_path(toppath, partial=True)
        for path, _, files in os.walk(toppath):
            for filename in files:
                fullpath = os.path.join(path, filename)
                name, ext = os.path.splitext(fullpath)

                if ext.lower() not in extensions:
                    continue

                match = re.match(regex, name)
                if not match:
                    continue

                partialpath = str(Path(fullpath).relative_to(self.asset_path).with_suffix(''))
                assetname = self.clean_asset_name(partialpath)

                if any(re.match(exclude, assetname) for exclude in excludes):
                    continue

                if return_extension:
                    yield (assetname, ext)
                else:
                    yield assetname

    def load_related(self, obj: UEBase):
        if isinstance(obj, Property):
            return self.load_related(obj.value)
        if isinstance(obj, ObjectProperty):
            return self.load_related(obj.value.value)
        if isinstance(obj, ImportTableItem):
            assetname = str(obj.namespace.value.name.value)
            loader = obj.asset.loader
            asset = loader[assetname]
            return asset

        raise ValueError(f"Unsupported type for load_related '{type(obj)}'")

    def load_class(self, fullname: str, fallback=NO_FALLBACK) -> ExportTableItem:
        (assetname, cls_name) = fullname.split('.')
        assetname = self.clean_asset_name(assetname)
        asset = self[assetname]
        for export in asset.exports:
            if str(export.name) == cls_name:
                return export

        if fallback is not NO_FALLBACK:
            return fallback

        raise KeyError(f"Export {cls_name} not found")

    def _load_raw_asset_from_file(self, filename: str):
        '''Load an asset given its filename into memory without parsing it.'''
        if not os.path.isabs(filename):
            filename = os.path.join(self.asset_path, filename)
        try:
            mem = load_file_into_memory(filename)
        except FileNotFoundError:
            raise AssetNotFound(filename)
        return mem

    def load_raw_asset(self, name: str):
        '''Load an asset given its asset name into memory without parsing it.'''
        name = self.clean_asset_name(name)
        mem = None
        for ext in ('.uasset', '.umap'):
            filename = self.convert_asset_name_to_path(name, ext=ext)
            if Path(filename).is_file():
                mem = load_file_into_memory(filename)
                break

        if mem is None:
            raise AssetNotFound(name)

        return mem

    def __getitem__(self, assetname: str):
        '''Load and parse the given asset, or fetch it from the cache if already loaded.'''
        assetname = self.clean_asset_name(assetname)
        asset = self.cache.lookup(assetname) or self._load_asset(assetname)
        return asset

    def __delitem__(self, assetname: str):
        '''Remove the specified assetname from the cache.'''
        assetname = self.clean_asset_name(assetname)
        self.cache.remove(assetname)

    def partially_load_asset(self, assetname: str):
        asset = self._load_asset(assetname, doNotLink=True)
        return asset

    def _load_asset(self, assetname: str, doNotLink=False):
        logger.debug(f"Loading asset: {assetname}")
        mem = self.load_raw_asset(assetname)
        stream = MemoryStream(mem, 0, len(mem))
        asset = UAsset(weakref.proxy(stream))
        asset.loader = self
        asset.assetname = assetname
        asset.name = assetname.split('/')[-1]
        asset.deserialise()
        if doNotLink:
            return asset
        asset.link()

        exports = [export for export in asset.exports.values if str(export.name).startswith('Default__')]
        if len(exports) > 1:
            import warnings
            warnings.warn(f'Found more than one component in {assetname}!')
        asset.default_export = exports[0] if exports else None
        if asset.default_export:
            asset.default_class = asset.default_export.klass.value

        self.cache.add(assetname, asset)
        return asset


def load_file_into_memory(filename):
    with open(filename, 'rb') as f:
        data = f.read()
        mem = memoryview(data)
    return mem
