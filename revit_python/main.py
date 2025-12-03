# import sys
# # 替换为你项目中 ironpython-stubs-master 的实际路径
# sys.path.append(r"E:\mjw\graduate\new_gradute\code\stubs.min")
import clr

# 加载 Revit DLL（路径替换为你的 Revit 2024 安装路径）
clr.AddReference(r"D:\software\Revit 2024\RevitAPI.dll")
clr.AddReference(r"D:\software\Revit 2024\RevitAPIUI.dll")

# 导入命名空间（此时不应再提示 Unresolved reference）
from Autodesk.Revit.DB import Document, ElementId, Transaction
from Autodesk.Revit.UI import UIApplication, TaskDialog


# 测试语法补全（输入 Document. 应提示 GetElement 等方法）
def test_api():
    doc = Document()  # 无报错
    trans = Transaction(doc, "测试")  # 无报错
    trans.Start()
    elem = doc.GetElement(ElementId(123))  # 无报错
    trans.Commit()
    TaskDialog.Show("Success", "Autodesk 命名空间识别成功！")  # 无报错

if __name__ == "__main__":
    test_api()