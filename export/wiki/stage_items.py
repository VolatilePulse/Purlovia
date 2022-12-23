from typing import Any, Dict, List, Optional, cast

from ark.overrides import get_overrides_for_item
from ark.types import PrimalItem
from automate.hierarchy_exporter import ExportFileModel, ExportModel, Field, JsonHierarchyExportStage
from ue.asset import UAsset
from ue.hierarchy import get_parent_class
from ue.properties import FloatProperty, IntProperty, ObjectProperty
from ue.proxy import UEProxyStructure
from utils.log import get_logger

from .flags import gather_flags
from .items.cooking import CookingIngredientData, convert_cooking_values
from .items.crafting import CraftingData, RepairData, convert_crafting_values
from .items.durability import convert_durability_values
from .items.egg import EggData, convert_egg_values
from .items.status import StatEffectData, convert_status_effects

__all__ = [
    'ItemsStage',
]

logger = get_logger(__name__)

OUTPUT_FLAGS = (
    'bPreventCheatGive',
    'bDurabilityRequirementIgnoredInWater',
)


class Item(ExportModel):
    name: Optional[str]
    description: Optional[str] = None
    bp: str = Field(..., title="Blueprint path")
    parent: Optional[str] = Field(None, description="Full path to the parent class of this item")
    icon: Optional[str] = Field(None, description="Blueprint path pointing to either a texture or material instance.")
    type: Optional[str] = None
    flags: Optional[List[str]] = Field(list(), description="Relevant boolean flags that are True for this item")
    folders: List[str] = Field(
        [],
        title="Crafting station folder",
        description="These are the folders in a crafting station where this item's blueprint is shown.",
    )
    weight: Optional[FloatProperty] = Field(None, description="Weight of a single item")
    stackSize: Optional[IntProperty] = None
    spoilsIn: Optional[FloatProperty] = Field(None, description="Spoilage time in seconds")
    spoilsTo: Optional[str] = Field(None, description="Blueprint path of the spoilage product")
    durability: Optional[float] = Field(None, description="Durability at 100% quality")
    crafting: Optional[CraftingData]
    repair: Optional[RepairData]
    structure: Optional[str] = Field(
        None,
        description="Blueprint path of the structure created by this item (can by looked up in structures.json).",
    )
    weapon: Optional[str] = Field(
        None,
        description="Blueprint path of the weapon created by this item (can by looked up in weapons.json).",
    )
    statEffects: Optional[List[StatEffectData]] = Field(None, description="Stat changes caused by consumption of the item")
    egg: Optional[EggData]
    cooking: Optional[CookingIngredientData]


class ItemsExportModel(ExportFileModel):
    items: List[Item]

    class Config:
        title = "Item data for the Wiki"


class ItemsStage(JsonHierarchyExportStage):

    def get_name(self) -> str:
        return "items"

    def get_format_version(self) -> str:
        return "4"

    def get_use_pretty(self) -> bool:
        return bool(self.manager.config.export_wiki.PrettyJson)

    def get_ue_type(self) -> str:
        return PrimalItem.get_ue_type()

    def get_schema_model(self):
        return ItemsExportModel

    def extract(self, proxy: UEProxyStructure) -> Any:
        if self.manager.config.export_wiki.RestrictPath:
            # Check this asset is within the path restriction
            goodpath = self.manager.config.export_wiki.RestrictPath
            assetname = proxy.get_source().asset.assetname
            if not assetname.startswith(goodpath):
                return None

        item: PrimalItem = cast(PrimalItem, proxy)

        asset: UAsset = proxy.get_source().asset
        assert asset.assetname and asset.default_class
        modid: Optional[str] = self.manager.loader.get_mod_id(asset.assetname)
        overrides = get_overrides_for_item(asset.assetname, modid)
        if overrides.skip_export:
            return None

        out = Item(
            name=get_item_name(item),
            bp=item.get_source().fullname,
        )
        out.parent = get_parent_class(out.bp)

        # Export minimal data if the item is likely a base class
        if is_item_base_class(item):
            return out

        # Export full data otherwise
        try:
            icon_ref = item.get('ItemIconMaterialParent', fallback=item.get('ItemIcon', fallback=None))
            out.description = str(item.get('ItemDescription', fallback=None))
            out.icon = _safe_get_bp_from_object(icon_ref)

            # Export item type and subtypes
            out.type = _get_pretty_item_type(item)

            # Export the boolean flags
            out.flags = gather_flags(item, OUTPUT_FLAGS)

            # Export folders seen in crafting stations
            if item.has_override('DefaultFolderPaths'):
                out.folders = [str(folder) for folder in item.DefaultFolderPaths[0].values]

            # Export weight & stack size
            out.weight = item.BaseItemWeight[0]
            out.stackSize = item.MaxItemQuantity[0]

            # Export spoilage info
            if item.has_override('SpoilingTime') or item.has_override('SpoilingItem'):
                out.spoilsIn = item.SpoilingTime[0]
                out.spoilsTo = _safe_get_bp_from_object(item.get('SpoilingItem', fallback=None))

            # Export durability info if the mechanic is enabled
            out.durability = convert_durability_values(item)

            # Export crafting info
            out.crafting, out.repair = convert_crafting_values(item, has_durability=out.durability is not None)

            # Export string references to the structure or weapon templates (if any), which can then be looked up in
            # a separate file, without having this export grow in size too much.
            if 'StructureToBuild' in item and item.StructureToBuild[0].value.value:
                out.structure = _safe_get_bp_from_object(item.StructureToBuild[0])
            if 'WeaponTemplate' in item and item.WeaponTemplate[0].value.value:
                out.weapon = _safe_get_bp_from_object(item.WeaponTemplate[0])

            # Export status effect info when item is consumed
            if item.has_override('UseItemAddCharacterStatusValues'):
                out.statEffects = convert_status_effects(item)

            # Export egg info
            if item.bIsEgg[0]:
                out.egg = convert_egg_values(item)

            # Export cooking info
            if item.bIsCookingIngredient[0]:
                out.cooking = convert_cooking_values(item)

        except Exception:  # pylint: disable=broad-except
            logger.warning(f'Export conversion failed for {proxy.get_source().fullname}', exc_info=True)
            return None

        return out

    def get_post_data(self, modid: Optional[str]) -> Optional[Dict[str, Any]]:
        if self.gathered_results and not modid:
            # Add indices from the base PGD
            pgd_asset = self.manager.loader['/Game/PrimalEarth/CoreBlueprints/BASE_PrimalGameData_BP']
            return self._add_pgd_indices(pgd_asset, None)

        return None

    def _add_pgd_indices(self, pgd_asset: UAsset, mod_data: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not self.gathered_results or not pgd_asset.default_export or mod_data:
            return None

        properties = pgd_asset.default_export.properties
        d = properties.get_property('MasterItemList', fallback=None)
        if not d:
            return None

        master_list = [ref.value.value and ref.value.value.fullname for ref in d.values]
        return dict(indices=master_list)


def is_item_base_class(item: PrimalItem) -> bool:
    item_name = item.get('DescriptiveNameBase', 0, None)
    icon_texture = item.get('ItemIcon', 0, None)
    icon_material = item.get('ItemIconMaterialParent', 0, None)

    if not item_name or (not icon_texture and not icon_material):
        return True
    return False


def get_item_name(item: PrimalItem) -> Optional[str]:
    item_name = item.get('DescriptiveNameBase', fallback=None)
    if not item_name:
        return None

    out = str(item_name)

    # The game adds the Skin suffix to the item's name if bIsItemSkin is true. This only happens when the name is
    # not overridden by any other dynamic feature, like scripts or the rarity system (that preseeds quality and
    # other stats), and it's probably safer for us to export the CDO name in these cases.
    if item.bIsItemSkin[0] and not item.bUseBPGetItemName[0] and not item.bUseItemStats[0]:
        out += ' Skin'

    return out


def _get_pretty_item_type(item: PrimalItem) -> str:
    itemType = item.get('MyItemType', 0, None)
    value = itemType.get_enum_value_name()
    if value == 'MiscConsumable':
        consumableType = item.get('MyConsumableType', 0, None)
        return value + '/' + consumableType.get_enum_value_name()
    elif value == 'Equipment':
        equipmentType = item.get('MyEquipmentType', 0, None)
        return value + '/' + equipmentType.get_enum_value_name()
    return value


def _safe_get_bp_from_object(obj: Optional[ObjectProperty]) -> Optional[str]:
    if not obj or not obj.value or not obj.value.value:
        return None
    return obj.value.value.fullname
