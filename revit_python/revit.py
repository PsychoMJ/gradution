# -*- coding: utf-8 -*-

# =============================================================================
# 模块0: 导入必要的库与Revit API
# =============================================================================
import clr
import json
from collections import defaultdict


clr.AddReference('RevitAPI')
from Autodesk.Revit.DB import *
clr.AddReference('ProtoGeometry')
from Autodesk.DesignScript.Geometry import *

from Autodesk.Revit.DB import *


# 加载Revit Services (用于Dynamo环境)
clr.AddReference('RevitServices')
from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager

clr.AddReference('RevitNodes')
import Revit
clr.ImportExtensions(Revit.Elements)

# 获取当前Revit文档
doc = DocumentManager.Instance.CurrentDBDocument





# =============================================================================
# 模块1: CONFIG - 全局配置参数
# =============================================================================
class CONFIG:
    """存放所有可配置的参数，便于统一管理和修改"""
    # 1. 目标构件类别筛选
    TARGET_CATEGORIES = {
        BuiltInCategory.OST_StructuralFraming: "预制梁",
        BuiltInCategory.OST_StructuralColumns: "预制柱",
        BuiltInCategory.OST_Walls: "预制墙",
        BuiltInCategory.OST_Floors: "预制板"
    }

    # 以整型类别 Id 作为键的标签映射，便于运行时快速查找
    CATEGORY_LABELS_BY_ID = {
        int(BuiltInCategory.OST_StructuralFraming): "预制梁",
        int(BuiltInCategory.OST_StructuralColumns): "预制柱",
        int(BuiltInCategory.OST_Walls): "预制墙",
        int(BuiltInCategory.OST_Floors): "预制板"
    }

    # 2. 几何判断阈值 (单位：Revit内部单位, 通常是英尺, 1 ft ≈ 0.3048 m)
    SUPPORT_TOLERANCE = 1.0  # 支撑判断的垂直距离阈值 (约0.3m)
    COLLISION_TOLERANCE = 1e-6  # 精确碰撞检测的体积阈值 (非常小)

    # 3. 输出文件路径
    OUTPUT_JSON_PATH = "bim_semantic_analysis_result.json"


# =============================================================================
# 模块2: BIM_PARSER - BIM模型解析模块
# =============================================================================
class BIM_PARSER:
    """负责从Revit模型中筛选构件并提取其语义和几何信息"""

    @staticmethod
    def get_precast_components():
        """筛选所有目标类别的预制构件"""
        all_components = []
        for category in CONFIG.TARGET_CATEGORIES.keys():
            collector = FilteredElementCollector(doc).OfCategory(category).WhereElementIsNotElementType().ToElements()
            all_components.extend(list(collector))
        return all_components


    @staticmethod
    def parse_component_data(components):
        """为每个构件提取唯一的ID、语义信息和几何信息"""
        component_data_map = {}
        for elem in components:
            bbox = elem.get_BoundingBox(None)
            if not bbox or not bbox.Min or not bbox.Max: continue

            comp_id = elem.Id.IntegerValue
            options = Options()
            options.DetailLevel = ViewDetailLevel.Fine
            options.ComputeReferences = True
            options.IncludeNonVisibleObjects = True
            geometry = elem.get_Geometry(options)
            solid_geos = [s for s in geometry if isinstance(s, Solid) and s.Volume > 0]
            if not solid_geos: continue

            level_param = elem.get_Parameter(BuiltInParameter.ELEM_LEVEL_PARAM)
            level_name = level_param.AsValueString() if level_param and level_param.HasValue else "Unknown"

            component_data_map[comp_id] = {
                "id": comp_id, "name": elem.Name,
                "type": CONFIG.CATEGORY_LABELS_BY_ID.get(elem.Category.Id.IntegerValue, "Unknown"),
                "level": level_name, "bbox": bbox,
                "z_min": bbox.Min.Z, "z_max": bbox.Max.Z,
                "solid": solid_geos[0]
            }
        return component_data_map


# =============================================================================
# 模块3: GEOMETRY_ANALYZER - 几何分析模块
# =============================================================================
class GEOMETRY_ANALYZER:
    """负责计算构件间的物理约束关系"""

    @staticmethod
    def create_scan_box(bbox, z_limit):
        """根据构件包围盒创建其+Z向的扫描盒实体"""
        min_point = bbox.Min
        max_point = bbox.Max

        # 定义扫描盒的底面轮廓
        p1 = XYZ(min_point.X, min_point.Y, max_point.Z)
        p2 = XYZ(max_point.X, min_point.Y, max_point.Z)
        p3 = XYZ(max_point.X, max_point.Y, max_point.Z)
        p4 = XYZ(min_point.X, max_point.Y, max_point.Z)

        profile_lines = [Line.CreateBound(p1, p2), Line.CreateBound(p2, p3),
                         Line.CreateBound(p3, p4), Line.CreateBound(p4, p1)]

        curve_loop = CurveLoop.Create(profile_lines)
        extrude_dir = XYZ.BasisZ

        # 确保拉伸高度为正
        extrusion_height = z_limit - max_point.Z
        if extrusion_height <= 0: return None

        try:
            return GeometryCreationUtilities.CreateExtrusionGeometry([curve_loop], extrude_dir, extrusion_height)
        except Exception:
            return None

    @staticmethod
    def check_collision(solid_a, solid_b):
        """使用Revit API精确检查两个实体是否碰撞"""
        if not solid_a or not solid_b: return False
        try:
            intersection = BooleanOperationsUtils.ExecuteBooleanOperation(solid_a, solid_b,
                                                                          BooleanOperationsType.Intersect)
            return intersection is not None and intersection.Volume > CONFIG.COLLISION_TOLERANCE
        except Exception:
            return False

    @staticmethod
    def bbox_xy_overlap(b1, b2):
        """在 XY 平面判断两个 BoundingBoxXYZ 是否重叠"""
        return (b1.Min.X < b2.Max.X and b1.Max.X > b2.Min.X and
                b1.Min.Y < b2.Max.Y and b1.Max.Y > b2.Min.Y)

    @staticmethod
    def calculate_support_constraint(comp_data_map):
        """只计算支撑邻接表，因为干涉将在拆卸法中动态计算"""
        support_adj = defaultdict(list)
        all_ids = list(comp_data_map.keys())
        for i in range(len(all_ids)):
            id_i = all_ids[i]
            data_i = comp_data_map[id_i]
            for j in range(len(all_ids)):
                if i == j: continue
                id_j = all_ids[j]
                data_j = comp_data_map[id_j]

                if abs(data_j["z_min"] - data_i["z_max"]) <= CONFIG.SUPPORT_TOLERANCE:
                    if (data_i["bbox"].Min.X < data_j["bbox"].Max.X and
                            data_i["bbox"].Max.X > data_j["bbox"].Min.X and
                            data_i["bbox"].Min.Y < data_j["bbox"].Max.Y and
                            data_i["bbox"].Max.Y > data_j["bbox"].Min.Y):
                        support_adj[id_i].append(id_j)
        return dict(support_adj)


# =============================================================================
# 模块4: SEQUENCE_GENERATOR - 序列生成模块 (动态扫描盒 - 已修正)
# =============================================================================
from collections import defaultdict


# ... (假设 CONFIG 和 GEOMETRY_ANALYZER 模块已正确定义) ...

class SEQUENCE_GENERATOR:
    """
    使用基于“动态扫描盒”的反向拆卸法，生成宏观分级队列。
    """

    @staticmethod
    def is_removable(comp_id, unremoved_set, comp_data_map, support_adj, z_project_max):
        """
        判断构件是否可拆卸：1.不支撑别人 2.向上拆卸路径无碰撞
        """

        # 条件1: 检查该构件是否支撑着任何“尚未移除”的构件 (结构自由度)
        if comp_id in support_adj:
            for supported_id in support_adj[comp_id]:
                if supported_id in unremoved_set:
                    return False

        # 条件2: 检查该构件的+Z向拆卸路径是否通畅 (几何自由度)
        data_i = comp_data_map[comp_id]
        scan_box_solid = GEOMETRY_ANALYZER.create_scan_box(data_i["bbox"], z_project_max)
        if not scan_box_solid:
            return True  # 如果无法创建扫描盒（已在顶部），视为无干涉

        for other_id in unremoved_set:
            if other_id == comp_id:
                continue

            data_j = comp_data_map[other_id]

            # =======================
            # !!! 关键逻辑修正 !!!
            # =======================
            # 空间剪枝: 如果构件j的最高点(z_max)低于构件i的扫描盒的起始点(即i的z_max)，
            # 那么j不可能在i的“向上”路径上造成干涉。
            if data_j["z_max"] < data_i["z_max"]:
                continue
            # =======================
            # 修正结束
            # =======================

            # 快速筛选：使用包围盒相交测试，进一步过滤
            # 快速筛选：XY 投影重叠快速排除
            if not GEOMETRY_ANALYZER.bbox_xy_overlap(data_i["bbox"], data_j["bbox"]):
                continue

            # 精确碰撞检测
            if GEOMETRY_ANALYZER.check_collision(scan_box_solid, data_j["solid"]):
                return False

        return True

    @staticmethod
    def generate_macro_sequence(comp_data_map, support_adj):
        """主算法：通过动态扫描盒判断，生成宏观分级队列"""
        if not comp_data_map: return [], []

        unremoved_set = set(comp_data_map.keys())
        z_project_max = max(data["z_max"] for data in comp_data_map.values()) if comp_data_map else 0

        disassembly_sequence_groups = []

        while len(unremoved_set) > 0:
            removable_this_round = []

            for comp_id in list(unremoved_set):
                if SEQUENCE_GENERATOR.is_removable(comp_id, unremoved_set, comp_data_map, support_adj, z_project_max):
                    removable_this_round.append(comp_id)

            if not removable_this_round:
                print("Warning: Constraint loop detected.")
                fallback_comp = max(unremoved_set, key=lambda x: comp_data_map[x]['z_max'])
                removable_this_round.append(fallback_comp)
                print("Forcibly removing component ID: {}.".format(fallback_comp))

            if removable_this_round:
                disassembly_sequence_groups.append(sorted(removable_this_round))
                unremoved_set -= set(removable_this_round)
            else:
                break

        assembly_sequence_groups = disassembly_sequence_groups[::-1]

        return disassembly_sequence_groups, assembly_sequence_groups


# =============================================================================
# 模块5: DATA_EXPORTER - 数据导出模块
# =============================================================================
class DATA_EXPORTER:
    """负责将所有分析结果打包并导出为JSON文件"""

    @staticmethod
    def format_output(comp_data_map, support_adj, disassembly_groups, assembly_groups):
        """将所有数据整理成一个字典"""

        semantics = [{
            "id": data["id"], "name": data["name"],
            "type": data["type"], "level": data["level"]
        } for data in comp_data_map.values()]

        # 在此版本中，干涉关系是动态计算的，不作为静态数据输出
        # 但可以导出一个空的，保持数据结构一致性
        interference_adj = {}

        output_data = {
            "project_info": {"name": doc.Title, "component_count": len(comp_data_map)},
            "components_semantics": semantics,
            "constraints": {
                "support_adjacency_list": {str(k): v for k, v in support_adj.items()},
                "interference_adjacency_list": interference_adj  # 空的，或在后续优化中按需计算
            },
            "macro_sequence": {
                "disassembly_groups": disassembly_groups,
                "assembly_groups": assembly_groups
            }
        }
        return output_data

    @staticmethod
    def export_to_json(data, file_path):
        """将字典写入JSON文件"""
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
            return "Successfully exported to {}".format(file_path)
        except Exception as e:
            return "Error exporting to JSON: {}".format(str(e))


# =============================================================================
# 模块6: MAIN - 主函数
# =============================================================================
def main():
    """主执行流程"""
    print("Starting BIM Physical Semantic Parsing (Scan-Box Method)...")

    # 1. BIM模型解析
    print("Step 1/3: Parsing BIM model and extracting component data...")
    raw_components = BIM_PARSER.get_precast_components()
    component_data_map = BIM_PARSER.parse_component_data(raw_components)
    if not component_data_map:
        return "No valid precast components found. Please check CONFIG."
    print("Found {} components.".format(len(component_data_map)))

    # 2. 几何分析，只计算支撑约束
    print("Step 2/3: Analyzing geometry and calculating SUPPORT constraints...")
    support_adj = GEOMETRY_ANALYZER.calculate_support_constraint(component_data_map)
    print("Support constraint calculation finished.")

    # 3. 生成宏观序列（动态扫描盒版）
    print("Step 3/3: Generating macro-sequence using DYNAMIC SCAN-BOX method...")
    disassembly_groups, assembly_groups = SEQUENCE_GENERATOR.generate_macro_sequence(
        component_data_map, support_adj
    )
    print("Macro-sequence generated with {} groups.".format(len(assembly_groups)))

    # 4. 格式化并导出数据
    print("Formatting and exporting data to JSON...")
    output_data = DATA_EXPORTER.format_output(
        component_data_map, support_adj, disassembly_groups, assembly_groups
    )
    result_message = DATA_EXPORTER.export_to_json(output_data, CONFIG.OUTPUT_JSON_PATH)
    print(result_message)

    return output_data


# =============================================================================
# 脚本执行入口
# =============================================================================
# 在Dynamo的Python Script节点中，最后一行应该是 OUT = main()
if __name__ == "__main__":
    OUT = main()
