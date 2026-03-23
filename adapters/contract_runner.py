"""
adapters/contract_runner.py — 执行 Adapter 行为契约测试

用法:
    from adapters.contract_runner import ContractRunner
    runner = ContractRunner()
    result = runner.run_contract(adapter, "land")
    # result = {"success": bool, "violations": [...], "actual_state": {...}, "duration_ms": float}
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

from adapters.contracts import ADAPTER_CONTRACTS

logger = logging.getLogger(__name__)


@dataclass
class ContractViolation:
    """描述一个契约违规。"""
    method: str
    check: str
    expected: str
    actual: Any
    description: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


class ContractRunner:
    """
    执行 adapter 行为契约测试。
    
    对每个方法：执行 -> 读取状态 -> 逐条验证 postcondition。
    """

    def run_contract(self, adapter, method_name: str) -> dict:
        """
        执行单个方法的契约测试。
        
        Returns:
            {
                "success": bool,
                "method": str,
                "violations": [ContractViolation.to_dict(), ...],
                "actual_state": dict,
                "duration_ms": float,
                "error": str or None,
            }
        """
        contract = ADAPTER_CONTRACTS.get(method_name)
        if not contract:
            return {
                "success": False,
                "method": method_name,
                "violations": [],
                "actual_state": {},
                "duration_ms": 0,
                "error": f"未找到方法 '{method_name}' 的契约定义",
            }

        violations: List[ContractViolation] = []
        actual_state: dict = {}
        start = time.time()

        try:
            # 执行方法
            result = self._execute_method(adapter, method_name, contract["timeout"])

            # 读取执行后状态
            state = adapter.get_state()
            if state is not None:
                actual_state = {
                    "in_air": state.in_air,
                    "armed": state.armed,
                    "z": state.position_ned.down if state.position_ned else None,
                    "position": state.position_ned.to_list() if state.position_ned else None,
                }
            else:
                actual_state = {"in_air": None, "armed": None, "z": None, "position": None}

            # 验证 postconditions
            for pc in contract["postconditions"]:
                check_expr = pc["check"]
                try:
                    # 构建评估上下文
                    eval_ctx = {
                        "result": result,
                        "in_air": actual_state.get("in_air"),
                        "armed": actual_state.get("armed"),
                        "z": actual_state.get("z"),
                        "abs": abs,
                        "isinstance": isinstance,
                        "True": True,
                        "False": False,
                        "None": None,
                        "bool": bool,
                    }
                    passed = eval(check_expr, {"__builtins__": {}}, eval_ctx)
                    if not passed:
                        violations.append(ContractViolation(
                            method=method_name,
                            check=check_expr,
                            expected=f"{check_expr} should be True",
                            actual=self._format_actual(check_expr, eval_ctx),
                            description=contract["description"],
                        ))
                except Exception as eval_err:
                    violations.append(ContractViolation(
                        method=method_name,
                        check=check_expr,
                        expected=f"{check_expr} should be True",
                        actual=f"eval error: {eval_err}",
                        description=contract["description"],
                    ))

        except Exception as e:
            elapsed = (time.time() - start) * 1000
            return {
                "success": False,
                "method": method_name,
                "violations": [],
                "actual_state": actual_state,
                "duration_ms": round(elapsed, 1),
                "error": f"执行异常: {e}",
            }

        elapsed = (time.time() - start) * 1000
        return {
            "success": len(violations) == 0,
            "method": method_name,
            "violations": [v.to_dict() for v in violations],
            "actual_state": actual_state,
            "duration_ms": round(elapsed, 1),
            "error": None,
        }

    def run_all_contracts(self, adapter) -> dict:
        """
        执行所有已定义契约的测试。
        
        Returns:
            {
                "total": int,
                "passed": int,
                "failed": int,
                "results": {method_name: run_contract_result, ...},
                "summary": str,
            }
        """
        results = {}
        passed = 0
        failed = 0

        for method_name in ADAPTER_CONTRACTS:
            # 检查 adapter 是否有这个方法
            if not hasattr(adapter, method_name):
                results[method_name] = {
                    "success": False,
                    "method": method_name,
                    "violations": [],
                    "actual_state": {},
                    "duration_ms": 0,
                    "error": f"adapter 缺少方法: {method_name}",
                }
                failed += 1
                continue

            r = self.run_contract(adapter, method_name)
            results[method_name] = r
            if r["success"]:
                passed += 1
            else:
                failed += 1

        total = passed + failed
        return {
            "total": total,
            "passed": passed,
            "failed": failed,
            "results": results,
            "summary": f"{passed}/{total} 契约通过, {failed} 失败",
        }

    def _execute_method(self, adapter, method_name: str, timeout: float) -> Any:
        """执行 adapter 方法，返回结果。"""
        method = getattr(adapter, method_name)
        
        if method_name == "takeoff":
            return method(altitude=3.0)
        elif method_name == "land":
            return method()
        elif method_name == "get_state":
            return method()
        elif method_name == "fly_to_ned":
            # 飞到一个安全测试点
            return method(north=0.0, east=0.0, down=-3.0, speed=2.0)
        elif method_name == "hover":
            return method(duration=2.0)
        else:
            return method()

    @staticmethod
    def _format_actual(check_expr: str, ctx: dict) -> str:
        """格式化实际值，方便调试。"""
        parts = []
        for key in ("in_air", "armed", "z", "result"):
            if key in check_expr and key in ctx:
                parts.append(f"{key}={ctx[key]}")
        return ", ".join(parts) if parts else str(ctx)
