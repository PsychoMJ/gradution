# Dynamo + Revit Python 节点语法参考与使用规范（基于 stubs.min）

本文档整理自项目中的 stubs.min 目录，面向在 Dynamo 的 Python 节点中编写 Revit API 与 DesignScript（ProtoGeometry）交互代码的常用语法、约定与示例。旨在提升脚本的可读性、一致性与稳定性。

## 目录
- 环境与程序集导入规范
- 命名空间与模块地图
- 文档、应用与选择对象
- 事务管理规范（Transaction）
- 元素检索与过滤（FilteredElementCollector）
- 参数访问与类别常量（BuiltInParameter / BuiltInCategory）
- 几何转换规范（Revit ↔ DesignScript）
- 单位、坐标与坐标系
- UI 与交互（TaskDialog / Selection）
- WPF 与 XAML 载入
- DSCore 常用工具
- Trace 与元素绑定（ElementBinder）
- 错误处理与事务失败回调
- 代码模板（从导入到事务的最小示例）
- 代码风格与命名约定
- 版本与兼容性注意事项

---

## 环境与程序集导入规范
在 Dynamo 的 Python 节点（IronPython 2.7）中使用 Revit API 与 DesignScript，需要先导入 CLR 并添加引用：

```python
import clr
# 添加 Revit API 程序集
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')
# 添加 Dynamo / ProtoGeometry / RevitNodes / DSCoreNodes / RevitServices
clr.AddReference('ProtoGeometry')
clr.AddReference('RevitNodes')
clr.AddReference('DSCoreNodes')
clr.AddReference('RevitServices')

# 可选：WPF 支持（按需使用）
clr.AddReference('IronPython.Wpf')
```

命名空间导入（按需）：

```python
# Revit API (DB/UI)
from Autodesk.Revit.DB import *
from Autodesk.Revit.UI import *

# Dynamo DesignScript 几何
from Autodesk.DesignScript.Geometry import *

# Dynamo/服务封装
from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager

# DSCore 常用工具
from DSCore import Color, Compare, DateTime

# 几何转换工具（RevitNodes）
from Revit.GeometryConversion import (
    RevitToProtoCurve, ProtoToRevitCurve,
    GeometryObjectConverter, GeometryPrimitiveConverter
)
```

建议仅按需导入具体类，避免 `import *` 污染命名空间。对于经常使用的类型可显式导入，提高可读性与 IDE 补全质量。

---

## 命名空间与模块地图
核心命名空间与用途概览（来自 stubs.min）：
- Autodesk.Revit.DB：Revit 数据层 API，元素、几何、过滤、事务、参数等核心类型（见 `__init__.py` 与大量 `__init___parts/*` 类型）。
- Autodesk.Revit.UI：Revit UI 层 API，交互、对话框、选择、面板、Ribbon 等。
- RevitServices.Persistence：Dynamo 环境下的文档/应用封装（`DocumentManager` 等）。
- RevitServices.Transactions：事务封装（`TransactionManager`、`ITransactionStrategy` 等）。
- Autodesk.DesignScript.Geometry：ProtoGeometry（Dynamo 几何），如 `Point`、`Line`、`Surface`、`Solid` 等。
- DSCore：Dynamo 常用工具集，如 `Color`、`Compare`、`DateTime` 等。
- Revit.GeometryConversion（RevitNodes）：Revit ↔ ProtoGeometry 几何互转工具类。
- IronPython.Modules / wpf：WPF/XAML 载入支持（按需）。

---

## 文档、应用与选择对象
在 Dynamo 环境下，优先使用 `DocumentManager` 获取当前文档与应用：

```python
doc = DocumentManager.Instance.CurrentDBDocument
uiapp = DocumentManager.Instance.CurrentUIApplication
uidoc = DocumentManager.Instance.CurrentUIDocument
```

选择对象（UI 层）：

```python
# 通过 UIDocument 访问选择
sel = uidoc.Selection
# 示例：获取已选元素的 ElementId 列表
ids = list(sel.GetElementIds())
```

---

## 事务管理规范（Transaction）
在 Revit 中对模型进行任何写操作都需要事务，Dynamo 下建议使用 `TransactionManager` 封装：

```python
from RevitServices.Transactions import TransactionManager

TransactionManager.Instance.EnsureInTransaction(doc)
# ... 执行创建/修改操作 ...
TransactionManager.Instance.TransactionTaskDone()
```

规范要点：
- 每个写操作块使用一段事务，避免事务范围过大导致失败定位困难。
- 有批量写入时，可分批次事务，结合 `DocumentManager.Regenerate()`（`RevitServices.Persistence`）提高稳定性。
- 调试时可考虑 `DebugTransactionStrategy`（见 `Transactions.py`），但在 Dynamo 默认场景保持 `AutomaticTransactionStrategy`。

---

## 元素检索与过滤（FilteredElementCollector）
常见检索模式（DB 层）：

```python
from Autodesk.Revit.DB import FilteredElementCollector, BuiltInCategory

walls = FilteredElementCollector(doc)\
    .OfCategory(BuiltInCategory.OST_Walls)\
    .WhereElementIsNotElementType()\
    .ToElements()
```

规范要点：
- 优先使用 `WhereElementIsNotElementType()` 获取实例；如需类型，用 `WhereElementIsElementType()`。
- 分类与类别常量使用 `BuiltInCategory`，参数常量使用 `BuiltInParameter`。
- 大范围检索注意性能，尽量增加过滤条件（如 `OfClass()`、`OfCategory()`）。

---

## 参数访问与类别常量
访问元素参数：

```python
param = element.LookupParameter('Comments')  # 文本参数示例
if param and not param.IsReadOnly:
    TransactionManager.Instance.EnsureInTransaction(doc)
    param.Set('由脚本写入')
    TransactionManager.Instance.TransactionTaskDone()
```

使用内置参数：

```python
from Autodesk.Revit.DB import BuiltInParameter
p = element.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
if p and not p.IsReadOnly:
    # 根据参数类型选择 Set(string/int/double/ElementId)
    pass
```

类别常量：
- `BuiltInCategory` 提供所有内置类别（如 `OST_Walls`、`OST_Doors` 等）。

---

## 几何转换规范（Revit ↔ DesignScript）
在 Dynamo 中常需在 ProtoGeometry 与 Revit 几何之间转换，优先使用 `Revit.GeometryConversion`：

- 原生几何到 ProtoGeometry：
  - `RevitToProtoCurve.ToProtoType(revitCurve, performHostUnitConversion, referenceOverride)`
  - `RevitToProtoFace.ToProtoType(revitFace, performHostUnitConversion, referenceOverride)`
  - `GeometryObjectConverter.Convert(geom, reference, transform)`（自动适配）

- ProtoGeometry 到 Revit：
  - `ProtoToRevitCurve.ToRevitType(curveOrPolyCurve, performHostUnitConversion)`
  - `DynamoToRevitBRep.ToRevitType(solid_or_surface, performHostUnitConversion, materialId)`
  - `GeometryPrimitiveConverter.ToRevitType(Point/Vector/BoundingBox, convertUnits)`

要点与约定：
- `performHostUnitConversion` / `convertUnits`：根据宿主文档单位进行转换，通常在 Dynamo（毫米）与 Revit（英制/毫米）间需要开启。
- 对 `Transform` / `CoordinateSystem` 使用 `GeometryPrimitiveConverter.ToTransform/ToCoordinateSystem` 保持坐标一致性。
- 复杂体（`Solid`/`Surface`）转换可能失败，建议分解为 `Face`/`Curve` 列表逐步处理，或使用 `ProtoToRevitMesh.ToRevitType(...)` 走网格化路径。

---

## 单位、坐标与坐标系
- Revit API 原生长度单位通常为英尺；Dynamo ProtoGeometry 多为毫米。务必在转换时明确单位策略。
- 坐标系转换使用 `GeometryPrimitiveConverter.ToTransform/ToCoordinateSystem`，统一模型空间与几何空间的表达。
- 角度转换：`ToRadians/ToDegrees`（`GeometryPrimitiveConverter`）。

---

## UI 与交互（TaskDialog / Selection）
常用 UI 操作：

```python
from Autodesk.Revit.UI import TaskDialog
TaskDialog.Show('提示', '脚本执行完成')
```

选择交互（需在外部命令环境或允许 UI 交互的场景）：

```python
from Autodesk.Revit.UI.Selection import ObjectType
refs = uidoc.Selection.PickObjects(ObjectType.Element, '请选择元素')
```

在 Dynamo 的 Python 节点中通常避免阻塞式交互，更多使用节点输入驱动。

---

## WPF 与 XAML 载入
可选：在 IronPython 下使用 `wpf.LoadComponent` 或 `IronPython.Modules.Wpf.LoadComponent` 载入 XAML，实现自定义 UI（与 Dynamo 节点交互需谨慎）：

```python
import wpf
# obj = wpf.LoadComponent(self, 'path/to/ui.xaml')
```

---

## DSCore 常用工具
- `Color.ByARGB(a, r, g, b)`：构造颜色；`Color.Components(color)` 获取分量；`Color.Lerp(start, end, t)` 插值。
- `Compare.GreaterThan/LessThan/...`：通用比较封装。
- `DateTime.ByDate(...)` / `DateTime.ByDateAndTime(...)`：日期/时间对象构造与计算。

这些工具在构造可视化、时间驱动逻辑、调试输出时十分有用。

---

## Trace 与元素绑定（ElementBinder）
在 Dynamo 中，为了在重计算时正确复用已创建的 Revit 元素，使用 `ElementBinder`：

- `ElementBinder.SetElementForTrace(element)` / `SetElementsForTrace(elements)`
- `ElementBinder.GetElementFromTrace(document)` / `GetElementsFromTrace[T](document)`

在创建新元素后调用 `CleanupAndSetElementForTrace(document, newElement)`，可提升节点的幂等性与用户体验。

---

## 错误处理与事务失败回调
- 事务失败委托：`FailureDelegate`（`RevitServices.Transactions`），可订阅处理事务期间的失败（高级用法，Dynamo 节点中少用）。
- 尽量将失败处理为可见提示（`TaskDialog`）或在输出端返回错误信息。

---

## 代码模板（最小示例）
以下模板演示了从导入、获取文档、开启事务，到创建几何并转换的最小流程。请根据实际任务替换占位内容。

```python
import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')
clr.AddReference('ProtoGeometry')
clr.AddReference('RevitNodes')
clr.AddReference('DSCoreNodes')
clr.AddReference('RevitServices')

from Autodesk.Revit.DB import *
from Autodesk.Revit.UI import *
from Autodesk.DesignScript.Geometry import *
from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager
from Revit.GeometryConversion import ProtoToRevitCurve, GeometryPrimitiveConverter

# 获取当前文档
uidoc = DocumentManager.Instance.CurrentUIDocument
doc = DocumentManager.Instance.CurrentDBDocument

# 示例：创建一条 DesignScript 直线并转换为 Revit 曲线
p0 = Point.ByCoordinates(0, 0, 0)
p1 = Point.ByCoordinates(1000, 0, 0)  # 毫米示例
line_ds = Line.ByStartPointEndPoint(p0, p1)

# 单位转换：将 DS Line 转为 Revit Curve（按需启用单位转换）
revit_curve = ProtoToRevitCurve.ToRevitType(line_ds, True)

# 在事务中将曲线放入草图或模型（示例：DetailCurve 需在视图下创建）
view = uidoc.ActiveView
TransactionManager.Instance.EnsureInTransaction(doc)
try:
    dc = doc.Create.NewDetailCurve(view, revit_curve)
finally:
    TransactionManager.Instance.TransactionTaskDone()
```

---

## 代码风格与命名约定
- 明确导入：仅导入必要的命名空间/类，避免 `import *`。
- 事务范围小而清晰：每个写操作对应一次事务，失败定位更容易。
- 单位一致：涉及几何转换时明确 `performHostUnitConversion/convertUnits`。
- 可重入性：创建元素后写入 Trace（`ElementBinder`），提高重计算体验。
- 错误可见：尽量返回信息或弹窗提示，避免静默失败。

---

## 版本与兼容性注意事项
- stubs 中显示的版本（例如 RevitAPI 17.x、DSCoreNodes 1.2.x、RevitNodes 1.2.x）与本机环境可能不同。
- 若版本不同，`clr.AddReference('AssemblyName')` 仍以装载到 Dynamo/主机中的实际 DLL 为准；命名空间与大部分类名保持兼容，但个别 API 可能发生变动。
- 如遇类型或方法缺失，优先在 `Autodesk.Revit.DB.__init___parts` 中检索具体类定义，或直接使用 IDE 的补全与对象检查。

---

## 进一步参考（stubs.min 中的关键文件）
- Autodesk.Revit.DB：类型入口位于 `__init__.py` 与大量 `__init___parts/*`。
- Autodesk.Revit.UI：入口于 `__init__.py`。
- RevitServices.Persistence：`DocumentManager`、`ElementBinder` 等。
- RevitServices.Transactions：`TransactionManager`、`ITransactionStrategy`、`FailureDelegate`。
- Autodesk.DesignScript.Geometry：`__init__.py` 包含实体类与几何操作。
- DSCore：`__init__.py` 提供工具类（`Color`、`Compare`、`DateTime` 等）。
- Revit.GeometryConversion：几何互转工具类（`RevitToProtoCurve`、`ProtoToRevitCurve`、`GeometryObjectConverter`、`GeometryPrimitiveConverter`）。

如需更细的 API 说明，可逐步阅读对应模块与 `__init___parts` 文件。
