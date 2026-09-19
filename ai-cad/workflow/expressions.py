"""尺寸表达式白名单求值；不执行 Python，不引入隐式单位换算。"""

import ast
import math
import operator

OPS = {ast.Add: operator.add, ast.Sub: operator.sub,
       ast.Mult: operator.mul, ast.Div: operator.truediv}


def resolve_parameters(parameters):
    values, visiting = {}, set()

    def resolve(name):
        if name in values:
            return values[name]
        if name in visiting or name not in parameters:
            raise ValueError(f"循环依赖或未知参数：{name}")
        visiting.add(name)
        item = parameters[name]
        if ("value" in item) == ("expression" in item):
            raise ValueError("参数须且仅须指定 value 或 expression")
        if "expression" in item:
            expression = item["expression"]
            if not isinstance(expression, str) or len(expression) > 1024:
                raise ValueError("表达式必须为不超过1024字符的字符串")
            tree = ast.parse(expression, mode="eval")
            if sum(1 for _ in ast.walk(tree)) > 128:
                raise ValueError("表达式过于复杂")
            value = walk(tree.body)
        else:
            value = item["value"]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError("参数必须为有限数值")
        if value < item.get("min", -math.inf) or value > item.get("max", math.inf):
            raise ValueError(f"参数超出范围：{name}")
        visiting.remove(name)
        values[name] = value
        return value

    def walk(node):
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            return node.value
        if isinstance(node, ast.Name):
            return resolve(node.id)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            return walk(node.operand) * (-1 if isinstance(node.op, ast.USub) else 1)
        if isinstance(node, ast.BinOp) and type(node.op) in OPS:
            return OPS[type(node.op)](walk(node.left), walk(node.right))
        raise ValueError("只支持数字、参数名、括号和加减乘除")

    for name in parameters:
        resolve(name)
    return {name: {**{k: v for k, v in item.items() if k != "expression"}, "value": values[name]}
            for name, item in parameters.items()}
