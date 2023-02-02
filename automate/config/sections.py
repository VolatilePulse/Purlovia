from pathlib import Path
from typing import Dict, Optional, Tuple

from pydantic import BaseModel, Extra

from utils.name_convert import snake_to_kebab

from .util_types import IniStringList, ModAliases, ModIdAccess


class SettingsSection(BaseModel):
    DataDir: Path = Path('livedata')
    OutputPath: Path = Path('output')

    SeparateOfficialMods: IniStringList = IniStringList()

    SkipGit: bool = False
    SkipExtract: bool = False
    SkipInstall: bool = False
    SkipRunGame: bool = False

    class Config:
        extra = Extra.forbid


class DevSection(BaseModel):
    DevMode: bool = True
    ClearHierarchyCache: bool = False

    class Config:
        extra = Extra.forbid


class SteamCmdSection(BaseModel):
    AppId: int = 376030  # Ark Dedicated Server
    RetryCount: int = 5
    UninstallUnusedMods: bool = True

    class Config:
        extra = Extra.forbid


class GitSection(BaseModel):
    Branch: str = 'master'
    UseReset: bool = False
    UseIdentity: bool = False

    SkipCommit: bool = False
    SkipPull: bool = False
    SkipPush: bool = False

    class Config:
        extra = Extra.forbid


class ErrorsSection(BaseModel):
    SendNotifications: bool = False
    MessageHeader: str = 'Purlovia ran into an error:'

    class Config:
        extra = Extra.forbid


class ExportDefaultsSection(BaseModel):
    PrettyJson: bool = True
    RestrictPath: Optional[str] = None


class ExportSection(ExportDefaultsSection):
    Skip: bool = False
    PrettyJson: Optional[bool] = None  # type: ignore  # pydantic allows this so shush
    PublishSubDir: Path
    CommitHeader: str


class ExportASBSection(ExportSection):
    ...

    class Config:
        extra = Extra.forbid


class ExportWikiSection(ExportSection):
    ExportVanillaMaps: bool = True

    class Config:
        extra = Extra.forbid


class ProcessingSection(BaseModel):
    ...

    class Config:
        extra = Extra.forbid


class OptimisationSection(BaseModel):
    SearchInclude: IniStringList = IniStringList()
    SearchIgnore: IniStringList = IniStringList()

    class Config:
        extra = Extra.forbid


# ...and one class to rule them all
class ConfigFile(BaseModel):
    settings: SettingsSection
    dev: DevSection
    steamcmd: SteamCmdSection
    git: GitSection
    errors: ErrorsSection
    optimisation: OptimisationSection

    export_asb: ExportASBSection
    export_wiki: ExportWikiSection
    processing: ProcessingSection

    run_sections: Dict[str, bool] = {'': True}
    display_sections: bool = False

    official_mods: ModIdAccess = ModIdAccess(dict())
    expansions: ModIdAccess = ModIdAccess(dict())
    combine_mods: ModAliases = ModAliases(dict())
    mods: Tuple[str, ...] = tuple()
    extract_mods: Optional[Tuple[str, ...]] = None
    extract_maps: Optional[Tuple[str, ...]] = None

    class Config:
        alias_generator = snake_to_kebab
